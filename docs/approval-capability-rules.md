# Approval capability rules (EPIC 07, S07.1)

Status 2026-10-09: **gate G5 PASS — S07.1 DONE.** Decisions approved by the project owner. Nothing is deployed. TS-Approve is designed in `docs/approve-contract.md`. TS-Approve (S07.2) and TS-Unapprove (S07.3) are implemented and live-proven on STAGING (`docs/approve-contract.md`).

| Artefact | Role |
|---|---|
| `tools/approval/approval_rules.py` | Reference implementation: the approved matrix and how an approve/unapprove operation calls the existing guard |
| `tools/approval/test_approval_rules.py` | AP-R01–R25. Each guard call also runs through the generated Power Automate guard template (offline WDL interpreter); results must match. With `TS_SCOPE_CONFIG` set, AP-R05 checks that the matrix equals the role seed |

## Decisions (gate G5)

| ID | Decision |
|---|---|
| B-01 | Team Leader approves own discipline and cannot unapprove. Approver and Executive approve and unapprove company-wide. **App Administrator is a technical role: no approve, no unapprove.** Employee, PMO and every other role: neither. |
| UD-04 | No role may approve or unapprove **its own** entry. This is enforced separately from scope; company scope does not override it. |
| UD-05 | Approve and unapprove are independent capabilities. Approve never implies unapprove. |
| Director | The legacy Director role is **retired**: no target role, no mapping, no capability. |
| B-02 | **Per-row approval only.** There is no period submission or period state machine. Approval acts directly on individual Draft entries. |

## Principles

- No second security model. Approval uses the existing guard (`docs/authorization-guard.md`): trusted caller → `Employees` → live role groups → scope table → decision → audit, with one CorrelationId.
- Existing capability keys only:
  - `TS.Approve`;
  - `TS.Unapprove`;
  - `TS.SelfApprove`, which no role holds.
- The role seed writes explicit denies (App Administrator approve/unapprove, Team Leader unapprove, self-approval). A decided deny is never "pending".
- The owner always comes from the **stored** entry. Owner, role or scope values in the request are ignored and recorded by name only.

## Check order (one entry)

1. Operation → capability (`Approve` → `TS.Approve`, `Unapprove` → `TS.Unapprove`). Anything else → `UNKNOWN_ACTION`.
2. Capability and scope check against the owner of the stored row:
   - no role grants the capability → `ROLE_NOT_ALLOWED`;
   - Team Leader and the owner's current discipline differs from the caller's → `SCOPE_NOT_ALLOWED`.
3. If the caller is the owner (employee code, or `OwnerUpn` case-insensitively) → `TS.SelfApprove` → `ROLE_NOT_ALLOWED`. This applies to approve **and** unapprove, for every role.

## Matrix

| Role | Approve | Scope | Unapprove | Scope | Approve own | Unapprove own |
|---|---|---|---|---|---|---|
| Employee | No | – | No | – | No | No |
| Team Leader | **Yes** | own discipline | No | – | No | No |
| Approver | **Yes** | company | **Yes** | company | No | No |
| Executive | **Yes** | company | **Yes** | company | No | No |
| PMO (legacy PM / Secretary) | No | – | No | – | No | No |
| HR | No | – | No | – | No | No |
| Salary Viewer | No | – | No | – | No | No |
| Finance | No | – | No | – | No | No |
| App Administrator | No | – | No | – | No | No |
| IT Support | No | – | No | – | No | No |
| Confidential Site Owner | No | – | No | – | No | No |
| Migration Owner | No | – | No | – | No | No |
| Legacy Director | retired: no role | – | – | – | – | – |

People with several roles get the union of the scopes, which is deterministic and independent of order. App Administrator adds nothing to approval. Own entries stay denied whatever the union. A group that is not configured as a role grants nothing.

## Approved-row immutability (contract for S07.2–S07.4)

| | Behaviour |
|---|---|
| Draft | Editable through `TS-SaveEntry` under the R1 rules |
| Approved | Every business mutation refuses it:<br>• Save → `LOCKED` (already in the reference and the generated flow);<br>• delete and reorder are refused and reported |
| Approve / unapprove | Server-only status change by the service identity, with an ETag check. Draft → Approved sets `ApprovedBy` / `ApprovedOn`. Unapprove (S07.3) goes back to Draft and clears both |
| Metadata | Approval never changes `OwnerUpn`, `ActorUpn`, `EmployeeItemId`, `LegacyId`, `WorkDate` or any business column. `Author` and `Created` are never written; `Author` is never the approver |

## Audit

| Event | Rows | Content |
|---|---|---|
| `AuthorizationAllow` / `AuthorizationDeny` | one per guard call | capability, scope, result code |
| `Approval` (`Approve`) | one per entry | trusted actor, target item and `LegacyId`, owner, `WorkDate`, ActionText `Phê duyệt: <WorkDate>`, ChangeJson `EntryStatus`, Decision / ResultCode, CorrelationId shared by the request |
| `Unapproval` (`Unapprove`) | one per entry | same, with ActionText `Hủy phê duyệt: <WorkDate>` (S07.3) |
| `WriteProxy` DENY `LOCKED` | refused write on an approved row | as in `docs/audit-model.md` |

`Lock` is not emitted for timesheet approval, because the `Approval` row is the lock event (one row per mutation). `Unlock` stays disabled. No confidential values are written.
