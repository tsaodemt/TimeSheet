# Approval capability rules (EPIC 07, S07.1)

Status 2026-10-09: **rules documented and testable; gate G5 BLOCKED_DECISION.** Nothing is deployed. No TS-Approve or TS-Unapprove flow exists yet.

| Artefact | Role |
|---|---|
| `tools/approval/approval_rules.py` | Reference implementation: the capability matrix and how an approve/unapprove operation calls the existing guard |
| `tools/approval/test_approval_rules.py` | AP-R01–R24. Each guard call also runs through the generated Power Automate guard template (offline WDL interpreter); results must match. With `TS_SCOPE_CONFIG` set, AP-R06 checks that the matrix equals the role seed |

## Principles

- No second security model. Approval uses the existing guard (`docs/authorization-guard.md`): trusted caller → `Employees` → live role groups → scope table → decision → audit, with one CorrelationId.
- Existing capability keys only: `TS.Approve`, `TS.Unapprove`, `TS.SelfApprove`.
- An undecided cell is `DECISION_PENDING` in the guard, which means **DENY**. Ambiguity never becomes ALLOW.
- Approve and unapprove are separate capabilities. Neither implies the other.
- The owner always comes from the **stored** entry. Owner, role or scope values in the request are ignored and recorded by name only.

## Check order (one entry)

1. Operation → capability (`Approve` → `TS.Approve`, `Unapprove` → `TS.Unapprove`). Anything else → `UNKNOWN_ACTION`.
2. Guard: capability on scope `employee:<owner employee code from the stored row>`. Team Leader scope = the owner's current discipline equals the caller's.
3. If the caller is the owner (employee code, or `OwnerUpn` case-insensitively): guard `TS.SelfApprove` on `self` as well. This applies to approve **and** unapprove. Company scope never implies it.

## Matrix

Legacy-exact means the capability the replaced legacy role verifiably had. It is the staging default and is **not yet signed for production** (decision B-01).

| Role | CanApprove | ApproveScope | CanUnapprove | UnapproveScope | Own entry (approve / unapprove) | DecisionStatus |
|---|---|---|---|---|---|---|
| Employee | No | – | No | – | N/A | RESOLVED |
| Team Leader | Yes (legacy-exact) | own discipline | No (`LeaderCanUnapprove`, default No) | – | No (UD-04) | DECISION_PENDING |
| Approver | Yes (legacy-exact) | company | Yes (legacy-exact) | company | No / No (UD-04) | DECISION_PENDING |
| Executive | Yes (legacy-exact) | company | Yes (legacy-exact) | company | No / No (UD-04) | DECISION_PENDING |
| PMO | No | – | No | – | N/A | RESOLVED |
| HR | No | – | No | – | N/A | RESOLVED |
| Salary Viewer | No | – | No | – | N/A | RESOLVED |
| Finance | No | – | No | – | N/A | RESOLVED |
| App Administrator | Yes (legacy-exact) | company | Yes (legacy-exact) | company | No / No (UD-04) | DECISION_PENDING |
| IT Support | No | – | No | – | N/A | RESOLVED |
| Confidential Site Owner | No | – | No | – | N/A | RESOLVED |
| Migration Owner | No | – | No | – | N/A | RESOLVED |
| Legacy Director (no target role) | No | – | No | – | N/A | DECISION_PENDING: no mapping until decided |

People with several roles get the union of the scopes. Their own entries stay denied.

## Gate G5

| ID | Question | Status | Runtime until decided |
|---|---|---|---|
| B-01 | Who may approve and unapprove, with which scope | UNRESOLVED | Legacy-exact staging default (matrix above) |
| B-02 | Per-row approval only, or also period submission | UNRESOLVED | Per-row only; no period submission is built |
| UD-04 | Self-approval | UNRESOLVED | DENY for every role (approve and unapprove) |
| UD-05 | Does approve imply unapprove | UNRESOLVED | Independent capabilities; Team Leader cannot unapprove |
| Director | The legacy Director could unapprove but not approve, and had no holders | UNRESOLVED | No mapping; no capability |

Decisions needed:
1. Production sign-off of the legacy-exact matrix (B-01).
2. Self-approval blocked for every role (UD-04).
3. Separate capabilities, `LeaderCanUnapprove` = No (UD-05).
4. The legacy Director: map to Executive (symmetric) or retire it.
5. Per-row approval only (B-02).

## Approved-row immutability (design for S07.4)

- **Draft:** editable through `TS-SaveEntry` (R1 rules).
- **Approved:** every business mutation refuses it. Save → `LOCKED`, already in the reference and generated flow, but not yet live-tested because no approved row exists. Delete and reorder are refused and reported.
- **Approve / unapprove:** server-only status change by the service identity, with an ETag check:
  - Draft ↔ Approved;
  - unapprove clears `ApprovedBy` and `ApprovedOn`.
- **Metadata:** approval never changes `OwnerUpn`, `ActorUpn`, `EmployeeItemId`, `LegacyId`, `WorkDate` or any business column. `Author` and `Created` are never written.
- **Fields present:** `EntryStatus` (Draft / Approved / Deleted), `OwnerUpn`, `ActorUpn`, `EmployeeItemId`, `DisciplineCode`, `PeriodKey`, `LegacyId`, `WorkDate`.
- **Missing, dependency of S07.2:** `ApprovedBy` and `ApprovedOn` are defined but gated and not provisioned. Confirm the `ApprovedBy` column type (User vs trusted UPN text) before provisioning.
- **Open S07.2 / S07.3 design points:**
  - re-approving an Approved row;
  - unapproving a Draft row.

## Audit (design)

| Event | Rows | Content |
|---|---|---|
| `AuthorizationAllow` / `AuthorizationDeny` | one per guard call | capability, scope `employee:<owner>`, result code |
| `Approval` (`Approve`) | one per entry | trusted actor, target item and `LegacyId`, owner, `IsOnBehalf`, `WorkDate`, ActionText `Phê duyệt: <WorkDate>`, ChangeJson `EntryStatus`, CorrelationId shared by the batch |
| `Unapproval` (`Unapprove`) | one per entry | same, ActionText `Hủy phê duyệt: <WorkDate>` |
| `WriteProxy` DENY `LOCKED` | refused write on an approved row | as in `docs/audit-model.md` |

`Lock` is not emitted for timesheet approval, because the `Approval` row is the lock event (one row per mutation). `Unlock` stays disabled. No confidential values are written.
