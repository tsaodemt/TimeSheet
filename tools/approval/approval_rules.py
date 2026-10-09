"""Reference implementation of the approval capability rules (EPIC 07 S07.1, executable specification).

Gate G5 decisions (project owner, APPROVED 2026-10-09): B-01 matrix, UD-04 no self-approval, UD-05 independent
capabilities, legacy Director retired, B-02 per-row approval only.

Approve / unapprove authorization is the EXISTING guard (tools/identity/guard.py) with the EXISTING capability
keys from the role seed: `TS.Approve`, `TS.Unapprove`, `TS.SelfApprove`. Nothing here is a second security
model; this module only fixes how an approval operation calls the guard:

    1. operation -> capability (Approve -> TS.Approve, Unapprove -> TS.Unapprove); anything else -> UNKNOWN_ACTION
    2. guard(capability, scope "employee", owner code taken from the STORED entry, never from the request)
    3. own entry (trusted caller == stored owner) -> additionally guard(TS.SelfApprove, "self"). No role holds
       TS.SelfApprove (UD-04), so own-entry approve AND unapprove are denied (ROLE_NOT_ALLOWED) whatever the scope.

MATRIX is the approved capability matrix. `scope_config()` turns it into the guard policy shape (ScopeConfig.json:
scopes + pending); test_approval_rules.py checks that it equals the authoritative seed when TS_SCOPE_CONFIG is set.
Entry-state rules, ETag and audit belong to TS-Approve (S07.2) and are specified in docs/approval-capability-rules.md.
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
    """One target role. Scopes: self | discipline | company | none. `denied` lists capabilities written to the
    seed as an explicit deny, with the decision that denies them."""
    role: str
    approve: str
    unapprove: str
    status: str
    evidence: str
    denied: Mapping[str, str] = field(default_factory=dict)


_NO_SELF = {SELF_CAPABILITY: "UD-04"}
MATRIX = (
    Row("EMP", "none", "none", RESOLVED, "B-01: no approval capability"),
    Row("TL", "discipline", "none", RESOLVED, "B-01 own discipline; UD-05 no unapprove",
        {"TS.Unapprove": "UD-05", **_NO_SELF}),
    Row("APR", "company", "company", RESOLVED, "B-01", dict(_NO_SELF)),
    Row("EXE", "company", "company", RESOLVED, "B-01; legacy Director retired, not mapped here", dict(_NO_SELF)),
    Row("PMO", "none", "none", RESOLVED, "B-01: PM / PMO no approval capability"),
    Row("HR", "none", "none", RESOLVED, "B-01: no approval capability"),
    Row("SALV", "none", "none", RESOLVED, "B-01: no approval capability"),
    Row("FIN", "none", "none", RESOLVED, "B-01: no approval capability"),
    Row("ADM", "none", "none", RESOLVED, "B-01: technical administration role, no business approval",
        {"TS.Approve": "B-01", "TS.Unapprove": "B-01"}),
    Row("ITS", "none", "none", RESOLVED, "B-01: no approval capability"),
    Row("CONFO", "none", "none", RESOLVED, "B-01: no approval capability"),
    Row("MIGO", "none", "none", RESOLVED, "B-01: no approval capability"),
)
RETIRED_LEGACY_ROLES = ("Director",)  # T07.1.2: no target role, no mapping, no capability


def scope_config(matrix: Iterable[Row] = MATRIX) -> dict:
    """Guard policy (ScopeConfig shape) for the approval capabilities only. Nothing is pending."""
    scopes = {}
    for r in matrix:
        acts = {cap: val for cap, val in ((CAPABILITY[APPROVE], r.approve), (CAPABILITY[UNAPPROVE], r.unapprove))
                if val != "none"}
        acts.update({cap: "none" for cap in r.denied})
        scopes[r.role] = acts
    return {"scopes": scopes, "pending": []}


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
