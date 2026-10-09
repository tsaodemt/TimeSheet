"""Reference implementation of the S07.1 approval capability rules (executable specification).

Approve / unapprove authorization is the EXISTING guard (tools/identity/guard.py) with the EXISTING capability
keys from the role seed: `TS.Approve`, `TS.Unapprove`, `TS.SelfApprove`. Nothing here is a second security
model; this module only fixes how an approval operation calls the guard:

    1. operation -> capability (Approve -> TS.Approve, Unapprove -> TS.Unapprove); anything else -> UNKNOWN_ACTION
    2. guard(capability, scope "employee", owner code taken from the STORED entry, never from the request)
    3. own entry (trusted caller == stored owner) -> additionally guard(TS.SelfApprove, "self");
       TS.SelfApprove is DECISION PENDING (UD-04) for every role, so own-entry approve AND unapprove are denied.

Not decided here (S07.2 / S07.3 design, see docs/approval-capability-rules.md): entry-state preconditions
(re-approve of an Approved row, unapprove of a Draft row), batch handling, the approver fields.

MATRIX is the documented S07.1 capability matrix. `scope_config()` turns it into the guard policy shape
(ScopeConfig.json: scopes + pending); test_approval_rules.py checks that it agrees with the authoritative seed
when TS_SCOPE_CONFIG is set. A cell that is not RESOLVED is never a grant.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "identity"))
import guard as G  # noqa: E402
import identity_resolver as idr  # noqa: E402

APPROVE, UNAPPROVE = "Approve", "Unapprove"
CAPABILITY = {APPROVE: "TS.Approve", UNAPPROVE: "TS.Unapprove"}
SELF_CAPABILITY = "TS.SelfApprove"
APPROVAL_CAPABILITIES = (CAPABILITY[APPROVE], CAPABILITY[UNAPPROVE], SELF_CAPABILITY)

RESOLVED, DECISION_PENDING, NOT_APPLICABLE = "RESOLVED", "DECISION_PENDING", "NOT_APPLICABLE"
STATUSES = (RESOLVED, DECISION_PENDING, NOT_APPLICABLE)


@dataclass(frozen=True)
class Row:
    """One target role. Scopes: self | discipline | company | none. `pending` lists capabilities whose decision
    is open (always denied at runtime) together with the decision ID."""
    role: str
    approve: str
    unapprove: str
    status: str
    evidence: str
    pending: Mapping[str, str] = field(default_factory=dict)


_SELF = {SELF_CAPABILITY: "UD-04"}
MATRIX = (
    Row("EMP", "none", "none", RESOLVED, "legacy Member: no approve, no unapprove"),
    Row("TL", "discipline", "none", DECISION_PENDING,
        "legacy Leader: approve own discipline; unapprove refused; LeaderCanUnapprove default No",
        {"TS.Unapprove": "LeaderCanUnapprove (B-01, UD-05)", **_SELF}),
    Row("APR", "company", "company", DECISION_PENDING, "legacy Manager: approve + unapprove", dict(_SELF)),
    Row("EXE", "company", "company", DECISION_PENDING,
        "legacy CEO: approve + unapprove; legacy Director membership NOT included (pending)", dict(_SELF)),
    Row("PMO", "none", "none", RESOLVED, "legacy PM / Secretary: no approve, no unapprove"),
    Row("HR", "none", "none", RESOLVED, "legacy HR head: no approve, no unapprove"),
    Row("SALV", "none", "none", RESOLVED, "additive rates role; no timesheet capability"),
    Row("FIN", "none", "none", RESOLVED, "legacy accounting head: no approve, no unapprove"),
    Row("ADM", "company", "company", DECISION_PENDING,
        "legacy Admin: approve + unapprove; target holders are named IT administrators (B-01 / B-4)", dict(_SELF)),
    Row("ITS", "none", "none", RESOLVED, "legacy IT: no approve, no unapprove"),
    Row("CONFO", "none", "none", RESOLVED, "site-ownership role; no timesheet capability"),
    Row("MIGO", "none", "none", RESOLVED, "temporary migration role; no timesheet capability"),
)


def scope_config(matrix: Iterable[Row] = MATRIX) -> dict:
    """Guard policy (ScopeConfig shape) for the approval capabilities only."""
    scopes, pending = {}, []
    for r in matrix:
        acts = {}
        for cap, val in ((CAPABILITY[APPROVE], r.approve), (CAPABILITY[UNAPPROVE], r.unapprove)):
            if cap in r.pending or val != "none":
                acts[cap] = "none" if cap in r.pending else val
        if r.approve != "none" or r.unapprove != "none":
            acts[SELF_CAPABILITY] = "none"
        scopes[r.role] = acts
        pending += [{"role": r.role, "capability": c, "detail": d} for c, d in sorted(r.pending.items())]
    return {"scopes": scopes, "pending": pending}


@dataclass(frozen=True)
class StoredEntry:
    """Values the flow reads from the stored TimesheetEntries row (service read), never from the request."""
    owner_employee_code: str
    owner_upn: str


@dataclass
class ApprovalDecision:
    operation: str
    allowed: bool
    result_code: str
    is_self: bool
    guard_results: list

    @property
    def correlation_id(self) -> str:
        return self.guard_results[0].CorrelationId if self.guard_results else ""


def decide(identity: Optional[idr.TrustedIdentity],
           lookup: Callable[[str], Iterable[idr.Employee]],
           target_lookup: Callable[[str], Iterable[idr.Employee]],
           config: idr.Config,
           policy: G.Policy,
           operation: str,
           entry: StoredEntry,
           *,
           correlation_id: Optional[str] = None,
           **untrusted: object) -> ApprovalDecision:
    """Fail closed. Request fields (owner, role, scope claims) are passed as `untrusted`: names recorded, never read."""
    cap = CAPABILITY.get(str(operation or "").strip())
    if cap is None:
        return ApprovalDecision(str(operation), False, G.UNKNOWN_ACTION, False, [])
    first = G.authorize(identity, lookup, target_lookup, config, policy, cap, G.K_EMPLOYEE, entry.owner_employee_code,
                        correlation_id=correlation_id, **untrusted)
    if not first.allowed:
        return ApprovalDecision(operation, False, first.ResultCode, False, [first])
    is_self = (first.EmployeeCode == entry.owner_employee_code
               or (first.AuthenticatedUpn or "").lower() == (entry.owner_upn or "").lower())
    if not is_self:
        return ApprovalDecision(operation, True, G.R_ALLOW, False, [first])
    second = G.authorize(identity, lookup, target_lookup, config, policy, SELF_CAPABILITY, G.K_SELF,
                         correlation_id=first.CorrelationId, **untrusted)
    return ApprovalDecision(operation, second.allowed, second.ResultCode, True, [first, second])
