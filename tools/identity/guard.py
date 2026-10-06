"""Reference implementation of the reusable authorization guard (executable specification).

One call answers: may the AUTHENTICATED caller perform <action> on <requested scope>?

    trusted platform identity -> Employee (identity_resolver.resolve)
      -> live role-group membership -> roles
      -> scope table (configuration) -> effective scope (scope_resolver.effective_scope, union rule)
      -> requested scope checked against trusted data (scope_resolver.allowed)
      -> GuardResult (+ audit payload)

The Power Automate guard template (tools/powerautomate/guard_template.py) emits the same decision logic;
test_guard.py runs every case through both (template via tools/powerautomate/wdl_sim.py) and requires
identical results.

Never read from the request: caller UPN, owner/actor UPN, role, scope grant, discipline of the caller,
reviewer flag, x-ms-user-* headers. They may be passed as `untrusted` for audit only.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Sequence

import identity_resolver as idr
from scope_resolver import COMPANY, DISCIPLINE, NONE, SELF, Target, allowed, effective_scope

ALLOW, DENY = "ALLOW", "DENY"

# Result codes. Exactly one per decision; only ALLOW allows.
R_ALLOW = "ALLOW"
INVALID_IDENTITY = "INVALID_IDENTITY"        # no / malformed / foreign-domain platform identity
ACCOUNT_NOT_ALLOWED = "ACCOUNT_NOT_ALLOWED"  # disabled or guest account
UNMAPPED_IDENTITY = "UNMAPPED_IDENTITY"      # no Employees row for the authenticated UPN
DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"    # more than one Employees row claims the UPN (configuration error)
INACTIVE_EMPLOYEE = "INACTIVE_EMPLOYEE"
DIRECTORY_ERROR = "DIRECTORY_ERROR"          # lookup failed; never treated as "not found"
UNKNOWN_ACTION = "UNKNOWN_ACTION"            # action not in the capability catalogue
UNKNOWN_SCOPE = "UNKNOWN_SCOPE"              # requested scope kind unknown, or configured scope value not self/discipline/company
DECISION_PENDING = "DECISION_PENDING"        # role/action decision not yet taken by the customer (default deny)
TEMP_ROLE_INACTIVE = "TEMP_ROLE_INACTIVE"    # only a temporary role holds the action and no activation is in force
ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"        # none of the caller's roles grants the action
SCOPE_NOT_ALLOWED = "SCOPE_NOT_ALLOWED"      # action granted, requested target outside the effective scope (or target not found)

_ID_CODES = {idr.INVALID_IDENTITY: INVALID_IDENTITY, idr.ACCOUNT_NOT_ALLOWED: ACCOUNT_NOT_ALLOWED,
             idr.NOT_REGISTERED: UNMAPPED_IDENTITY, idr.DUPLICATE_MAPPING: DUPLICATE_IDENTITY,
             idr.INACTIVE: INACTIVE_EMPLOYEE, idr.DIRECTORY_ERROR: DIRECTORY_ERROR}

# Requested scope kinds. `ref` is the target employee code (employee) or discipline code (discipline).
K_SELF, K_EMPLOYEE, K_DISCIPLINE, K_COMPANY = "self", "employee", "discipline", "company"
SCOPE_KINDS = (K_SELF, K_EMPLOYEE, K_DISCIPLINE, K_COMPANY)
_VALID = (SELF, DISCIPLINE, COMPANY)


@dataclass(frozen=True)
class Policy:
    """Authorization configuration, generated from the role seed (ScopeConfig.json). Never request data."""
    scopes: Mapping[str, Mapping[str, str]]          # role -> action -> scope value
    pending: Sequence[tuple] = ()                    # (role, action) decisions not yet taken -> deny
    temporary_roles: Sequence[str] = ()              # roles that need an explicit activation (none modelled yet)

    @property
    def actions(self) -> dict:
        """Capability catalogue, case-insensitive name -> canonical name."""
        names = {a for acts in self.scopes.values() for a in acts} | {a for _, a in self.pending}
        return {a.lower(): a for a in names}

    @classmethod
    def from_scope_config(cls, cfg: Mapping, temporary_roles: Sequence[str] = ("MIGO",)) -> "Policy":
        return cls(scopes=cfg["scopes"], pending=tuple((p["role"], p["capability"]) for p in cfg.get("pending", ())),
                   temporary_roles=tuple(temporary_roles))

    def classify(self, role: str, action: str) -> str:
        """self|discipline|company|pending|temp|unknown|none for one role and canonical action."""
        if (role, action) in set(self.pending):
            return "pending"
        v = self.scopes.get(role, {}).get(action)
        if v is None or v == NONE:
            return "none"
        if v in _VALID:
            return v
        return "temp" if role in self.temporary_roles else "unknown"


@dataclass
class GuardResult:
    AuthenticatedUpn: Optional[str]
    EmployeeId: Optional[int]
    EmployeeCode: Optional[str]
    IsActive: Optional[bool]
    ResolvedRoles: list
    RequestedAction: str
    RequestedScope: str
    ResolvedScope: str
    AuthorizationDecision: str
    ResultCode: str
    CorrelationId: str
    Detail: str = ""
    IgnoredInputs: list = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.AuthorizationDecision == ALLOW and self.ResultCode == R_ALLOW

    def audit_payload(self) -> dict:
        """Row written to the audit list by every guarded flow (same field names as the flow template)."""
        return {"Title": "guard %s %s" % (self.RequestedAction, self.ResultCode),
                "Decision": "ALLOWED" if self.allowed else "DENIED",
                "ResultCode": self.ResultCode,
                "CallerUpnTrusted": self.AuthenticatedUpn or "",
                "CorrelationId": self.CorrelationId,
                "Detail": "kind=guard;employeeId=%s;employeeCode=%s;isActive=%s;roles=%s;action=%s;scope=%s;resolvedScope=%s;ignored=%s;%s" % (
                    "" if self.EmployeeId is None else self.EmployeeId, self.EmployeeCode or "",
                    "" if self.IsActive is None else str(self.IsActive).lower(), ",".join(self.ResolvedRoles),
                    self.RequestedAction, self.RequestedScope, self.ResolvedScope, ",".join(self.IgnoredInputs), self.Detail)}


def authorize(identity: Optional[idr.TrustedIdentity],
              lookup: Callable[[str], Iterable[idr.Employee]],
              target_lookup: Callable[[str], Iterable[idr.Employee]],
              config: idr.Config,
              policy: Policy,
              action: str,
              scope_kind: str,
              scope_ref: str = "",
              *,
              correlation_id: Optional[str] = None,
              **untrusted: object) -> GuardResult:
    """Fail closed at every step. `untrusted` request fields are recorded by name only, never read."""
    cid = correlation_id or str(uuid.uuid4())
    act_in, kind_in, ref = str(action or "").strip(), str(scope_kind or "").strip().lower(), str(scope_ref or "").strip()
    res = idr.resolve(identity, lookup, config)
    emp = res.employee
    out = GuardResult(AuthenticatedUpn=res.upn, EmployeeId=emp.item_id if emp else None,
                      EmployeeCode=emp.legacy_id if emp else None, IsActive=emp.is_active if emp else None,
                      ResolvedRoles=list(res.roles) if res.ok else [], RequestedAction=act_in,
                      RequestedScope=kind_in + (":" + ref if ref else ""), ResolvedScope=NONE,
                      AuthorizationDecision=DENY, ResultCode="", CorrelationId=cid,
                      IgnoredInputs=sorted(untrusted))
    if not res.ok:
        if res.code == idr.INACTIVE:  # identity_resolver withholds the row; report what is known
            out.IsActive = False
        out.ResultCode = _ID_CODES.get(res.code, DIRECTORY_ERROR)
        return out
    act = policy.actions.get(act_in.lower())
    if act is None:
        out.ResultCode = UNKNOWN_ACTION
        return out
    out.RequestedAction = act
    if kind_in not in SCOPE_KINDS or (kind_in in (K_EMPLOYEE, K_DISCIPLINE) and not ref):
        out.ResultCode = UNKNOWN_SCOPE
        return out
    usable = {r: {act: v} for r in res.roles for v in [policy.scopes.get(r, {}).get(act)] if policy.classify(r, act) in _VALID}
    scope = effective_scope(res.roles, act, usable)
    out.ResolvedScope = scope
    if scope == NONE:
        classes = {policy.classify(r, act) for r in res.roles}
        out.ResultCode = (DECISION_PENDING if "pending" in classes else TEMP_ROLE_INACTIVE if "temp" in classes
                          else UNKNOWN_SCOPE if "unknown" in classes else ROLE_NOT_ALLOWED)
        return out
    if kind_in == K_SELF:
        target = Target(emp.legacy_id, emp.discipline_id)
    elif kind_in == K_EMPLOYEE:
        rows = list(target_lookup(ref))
        if len(rows) != 1:
            out.ResultCode, out.Detail = SCOPE_NOT_ALLOWED, "target=%d" % len(rows)
            return out
        target = Target(rows[0].legacy_id, rows[0].discipline_id)
    elif kind_in == K_DISCIPLINE:
        target = Target("", ref)
    else:
        target = Target("", None)
        if scope != COMPANY:
            out.ResultCode = SCOPE_NOT_ALLOWED
            return out
    if kind_in == K_DISCIPLINE and scope == SELF:
        out.ResultCode = SCOPE_NOT_ALLOWED
        return out
    ok = allowed(res, act, target, usable)
    out.ResultCode = R_ALLOW if ok else SCOPE_NOT_ALLOWED
    out.AuthorizationDecision = ALLOW if ok else DENY
    return out
