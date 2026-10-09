# Approve (TS-Approve) and team approval queue (TS-ReadTeam) — S07.2 implementation contract

Status 2026-10-09: **DESIGN READY, not built, not deployed.** It rests on gate G5 (PASS; `docs/approval-capability-rules.md`) and reuses the R1 architecture (`docs/saveentry-contract.md`, `docs/readown-contract.md`, `docs/r1-error-semantics.md`). Unapprove is S07.3 and is not part of this contract. There is no period submission (B-02).

## A. SharePoint schema delta (`TimesheetEntries`)

| Column | Type | Rule |
|---|---|---|
| `ApprovedBy` | Single line of text (255) | Trusted approver UPN from the guard. Never the request, never `Author` / `Editor`. Empty while Draft. Not indexed. |
| `ApprovedOn` | Date and time | UTC instant of the approval request (`utcNow()` ISO-8601 `Z`). Empty while Draft. Not indexed. |

- No other column, index or choice change. `EntryStatus` already has `Draft` / `Approved` / `Deleted`. The queue query uses the existing `PeriodKey` and `DisciplineCode` indexes.
- **Conflict to confirm before provisioning:** the earlier target data model and the gated definition in `tools/provisioning/r1_lists.py` declare `ApprovedBy` as a *Person* column. This contract uses text UPN, for three reasons:
  - it matches `OwnerUpn` / `ActorUpn`, and `AuditLog` already replaced its planned Person `Actor` with `ActorUpn` text;
  - authorization never depends on Person-field resolution;
  - it is tenant-portable and needs no `ensureuser` call by the service.
- The gated definition is changed when the column is provisioned (next task). Legacy rows keep both columns empty (approver unknown).

## B. TS-Approve input (Power Apps V2 trigger)

| Input | Rule |
|---|---|
| `Items` | JSON array of `{"itemId": <int>, "etag": "<etag from TS-ReadTeam>"}`. 1–50 entries. Request order is kept. A duplicate `itemId`, invalid JSON, an empty array or more than 50 entries → `VALIDATION_REQUEST` and nothing is written |
| `ClientRequestId` | optional, audit only |
| Claimed `OwnerUpn`, `ApproverUpn`, `Role`, `Scope`, `EntryStatus` | Untrusted. The names are logged in `IgnoredInputs`; the values are never read |

## C. TS-Approve response (all values strings)

`ok`, `resultcode`, `messagecode` (`MSG_<code>`), `correlationid`, `approvedcount`, `refusedcount`, `auditstatus` (`OK` / `AUDIT_DEGRADED`), and `results`. `results` is a JSON array in request order, one entry per item: `{itemid, resultcode, messagecode, etag}`, where `etag` is the new ETag after approval and empty otherwise.

| Request `resultcode` | When |
|---|---|
| `OK` | every row approved |
| `PARTIAL` | at least one row approved and at least one refused (`ok=true`) |
| `REFUSED` | no row approved; every row has its own code (`ok=false`) |
| guard codes (`ROLE_NOT_ALLOWED`, `INACTIVE_EMPLOYEE`, `UNMAPPED_IDENTITY`, …) | caller-level refusal; `results=[]`; nothing read or written |
| `VALIDATION_REQUEST` | malformed `Items` |
| `DIRECTORY_ERROR` / `INTERNAL_ERROR` | caller profile failed / mandatory pre-write authorization audit failed (`MSG_TEMPORARY_PROBLEM`, `results=[]`) |

| Row `resultcode` | Meaning |
|---|---|
| `OK` | Draft → Approved written |
| `NOT_FOUND` | item missing, `Deleted`, or `itemId` not a positive integer |
| `SCOPE_NOT_ALLOWED` | Team Leader and the owner's current discipline differs from the caller's (also when either discipline is missing) |
| `ROLE_NOT_ALLOWED` | own entry (UD-04, every role) |
| `LOCKED` | entry already Approved; no re-stamp, and the original `ApprovedBy` / `ApprovedOn` are kept |
| `CONFLICT` | client ETag missing or different from the stored one, or SharePoint 412 on the MERGE |
| `ERROR` | SharePoint write failure other than 412 |

## D. Authorization path

1. **Request-level guard (once).** `guard(TS.Approve, scope self)`, using the existing guard template:
   - MyProfile_V2 on the invoker connection → one active `Employees` row → live role groups (Team Leader, Approver and Executive groups configured; a missing group can only remove rights) → scope table → `AuthorizationAllow` / `AuthorizationDeny` row (mandatory, before any read of entries).
   - ALLOW gives the caller's effective scope: `discipline` (Team Leader) or `company` (Approver / Executive).
   - App Administrator, Employee, PMO and every other role → `ROLE_NOT_ALLOWED`.
2. **Per row, in this order** (service reads):
   1. GET the item. Missing or Deleted → `NOT_FOUND`.
   2. Scope: owner = the stored `Employee` / `EmployeeItemId` → that `Employees` row's current discipline.
      - `discipline` scope requires it to equal the caller's discipline;
      - `company` scope accepts any owner.
      - These are the same semantics as `scope_resolver.allowed`. The `DisciplineCode` snapshot on the entry is used only for the queue query.
   3. Self: owner employee = caller employee, or stored `OwnerUpn` = trusted caller UPN (case-insensitive) → `ROLE_NOT_ALLOWED`.
   4. State and ETag (section E / F).
3. **Reference equivalence.** For every role × target the per-row outcome must equal `approval_rules.decide` (offline test AQ-EQ). The guard runs once per request instead of once per row; the decision is the same because identity and roles are constant within one run.

## E. ETag / concurrency

- Each row carries the ETag that TS-ReadTeam returned. A stored ETag that differs, or a missing client ETag → `CONFLICT`, no write.
- MERGE with `IF-MATCH` = the stored ETag. A concurrent change in between → 412 → `CONFLICT`. No wildcard, no retry, no second unconditional write (same as SaveEntry).
- After the MERGE, the new ETag is returned per row. If it cannot be read back → row `OK` with an empty `etag` and warning `WARN_RELOAD_REQUIRED`.
- Rows are processed **sequentially** (concurrency 1) in request order. One row's failure never rolls back another row. There is no `$batch`: per-row ETag, result and audit are clearer and deterministic.

## F. Status transition rules

| Stored `EntryStatus` | Approve |
|---|---|
| `Draft` | → `Approved`; MERGE body exactly `{EntryStatus: "Approved", ApprovedBy: <trusted UPN>, ApprovedOn: <request UTC instant>}` |
| `Approved` | `LOCKED` (no write) |
| `Deleted` | `NOT_FOUND` |

- The MERGE never touches `OwnerUpn`, `ActorUpn`, `EmployeeItemId`, `Employee`, `LegacyId`, `WorkDate`, `PeriodKey`, `DisciplineCode`, `CorrelationId` or any business column.
- SharePoint `Author` / `Created` are never written by MERGE. `Editor` / `Modified` become the service account, as for every R1 write.
- Immutability: TS-SaveEntry already returns `LOCKED` for any non-Draft row. S07.4 adds delete / reorder refusal and the direct-edit monitor.

## G. Audit

- One `AuthorizationAllow` / `AuthorizationDeny` row per request (mandatory, before any entry read). If it fails → `INTERNAL_ERROR`, nothing read or written.
- One `Approval` row per item, including refused rows:
  - `Action=Approve`, `ActionText="Phê duyệt: <WorkDate>"`;
  - `Decision` ALLOW / DENY with the row `resultcode`;
  - `TargetItemId`, `TargetLegacyId`, `OwnerEmployeeItemId`, `WorkDate`, `IsOnBehalf=true`;
  - `ChangeJson={"EntryStatus":"Approved"}` on success;
  - the shared `CorrelationId`.
- A refused row before the GET has no `TargetLegacyId`.
- A failed append after a committed MERGE follows AUD-F1 option B: the row stays `OK`, `auditstatus=AUDIT_DEGRADED`, a warning is returned, and the run ends Failed for alerting. No retry and no undo.
- No confidential values. The approver is the trusted actor, never `Author`.

## TS-ReadTeam (approval queue, read-only)

| | Rule |
|---|---|
| Input | `PeriodKey` (`yyyy-MM`, required; `VALIDATION_DATE` otherwise), `AfterId`, `PageSize` (1–500) |
| Guard | `TS.Approve`, scope self. The queue is purpose-bound: App Administrator holds `TS.ViewOthers` but not `TS.Approve`, so it gets `ROLE_NOT_ALLOWED` |
| Query (service) | `PeriodKey eq '<p>' and EntryStatus eq 'Draft' [and DisciplineCode eq '<caller discipline>' when scope = discipline] and OwnerUpn ne '<caller>' and Id gt <AfterId>`, `$orderby=Id`, `$top`. `PeriodKey` is the first, indexed filter (the approved index decision) |
| Response | `ok`, `resultcode`, `messagecode`, `correlationid`, `rows` = `{id, ownerName, ownerCode, workDate, project, phase, workType, shift, hourType, hours, remark, status, etag}`, `nextafterid`, `pagesize` |
| Audit | `AuthorizationAllow` / `AuthorizationDeny` + `ReadProxy` (both mandatory, as ReadOwn); leak check: an own row or a non-Draft row → `ERROR_LEAK`, no rows |

A row shown in the queue can still be refused by TS-Approve, for example after a discipline transfer. That is safe and intended.

## H. Canvas team-approval UI (minimum)

- **New screen `scrTeamApproval`:**
  - period picker (`PeriodKey`), loaded through TS-ReadTeam with keyset paging;
  - gallery with a checkbox per row (multi-select) and owner, date, project, phase and hours;
  - "Select all on page";
  - **Phê duyệt** button, enabled when at least one row is selected, with the confirm prompt "Bạn có muốn phê duyệt nội dung chấm công không?";
  - TS-Approve with the selected `{itemId, etag}`;
  - a per-row result list (`MSG_<code>`), then reload.
- **`scrMyTimesheets`:**
  - a "Duyệt chấm công" navigation button;
  - the Edit button is disabled for `status = Approved`. This is a UI convenience; the server already returns `LOCKED`.
- **Visibility:** AppStart grants nothing and returns no roles, and it stays unchanged. The button is shown, and the screen's first TS-ReadTeam call decides access. `ROLE_NOT_ALLOWED` shows `MSG_ROLE_NOT_ALLOWED` and hides the button for the session.
- **`messages.json`:** add `MSG_PARTIAL`, `MSG_REFUSED`, `MSG_VALIDATION_REQUEST` and a per-row success text. The other codes already exist.

## I. Offline tests (next task)

| Area | Cases |
|---|---|
| Reference `approve_entries` (tools/approval) | AQ01–AQ10:<br>• Team Leader same discipline OK, cross discipline `SCOPE_NOT_ALLOWED`;<br>• Approver / Executive company OK;<br>• App Administrator / Employee / PMO request-level `ROLE_NOT_ALLOWED`;<br>• own row `ROLE_NOT_ALLOWED`;<br>• Approved → `LOCKED`, Deleted / missing → `NOT_FOUND`;<br>• stale or missing ETag → `CONFLICT` |
| Equivalence | AQ-EQ: per-row outcome = `approval_rules.decide` for every role × {own, same discipline, other discipline, missing} |
| Batch | AQ11–AQ15:<br>• request order kept;<br>• mixed outcomes → `PARTIAL` / `REFUSED`;<br>• duplicate `itemId`, > 50 items or bad JSON → `VALIDATION_REQUEST`;<br>• one row's 412 does not affect the others |
| Metadata | AQ16–AQ18:<br>• the MERGE body has exactly the 3 fields;<br>• `OwnerUpn` / `ActorUpn` / `LegacyId` unchanged;<br>• `ApprovedOn` is a UTC `Z` instant |
| Audit | AQ19–AQ23:<br>• one authorization row, one `Approval` row per item;<br>• ActionText;<br>• CorrelationId shared;<br>• pre-write audit failure → `INTERNAL_ERROR`, no write;<br>• post-write failure → `AUDIT_DEGRADED` |
| Trust | AQ24–AQ26:<br>• forged owner / role / scope / approver inputs ignored;<br>• inactive caller denied |
| Flow == reference | every AQ case through the generated flow in the offline WDL interpreter, with stored rows compared (as RS / RR) |
| TS-ReadTeam | RT01–RT12:<br>• scope filter;<br>• own rows excluded;<br>• Draft only;<br>• paging;<br>• App Administrator denied;<br>• leak check;<br>• mandatory audits |
| Canvas | build test: new screen, controls and message keys present; Edit disabled for Approved |

## J. Live-test plan (STAGING, after approval of each live step)

Preconditions, each a separate approval:
- provision `ApprovedBy` / `ApprovedOn`;
- deploy TS-ReadTeam and TS-Approve, and publish the app version;
- temporary role-group memberships for the test identities, with the baseline restored afterwards;
- synthetic Draft rows created through TS-SaveEntry by a second test identity;
- a cross-discipline case needs an owner in another discipline: a third mapped identity, or an approved temporary discipline on a synthetic employee.

| ID | Case | Expected |
|---|---|---|
| L01 | Approver approves another employee's Draft row | `OK`; `Approved`, `ApprovedBy` = approver UPN, `ApprovedOn` UTC; `Author` / `Created` / `OwnerUpn` / `ActorUpn` unchanged |
| L02 | Team Leader, same discipline | `OK` |
| L03 | Team Leader, other discipline | `SCOPE_NOT_ALLOWED`, no write |
| L04 | Own row (Approver) | `ROLE_NOT_ALLOWED`, no write |
| L05 | Employee / App Administrator caller | request `ROLE_NOT_ALLOWED`; App Administrator also denied by TS-ReadTeam |
| L06 | Stale ETag | `CONFLICT` |
| L07 | Approve an already Approved row | `LOCKED`, approver fields unchanged |
| L08 | TS-SaveEntry edit of the approved row by its owner | `LOCKED` (first live proof of R1 immutability) |
| L09 | Three rows: OK + stale + own | `PARTIAL`, per-row codes in order |
| L10 | Audit | 1 authorization row + 1 `Approval` row per item, shared CorrelationId, exactly once |
| L11 | ReadOwn after approval | row `status = Approved`; Canvas Edit disabled |
| L12 | Cleanup | synthetic rows soft-deleted or removed by the approved cleanup procedure; memberships restored |

## K. STAGING permission changes

**None for the service identity.** `TS Service` on `TimesheetEntries` already grants Read / Add / Edit (no Delete). The same holds for `AuditLog` (Add) and `Employees` (Read). Required configuration, which is not a permission change:
- the Team Leader, Approver and Executive STAGING group IDs in the flow build configuration;
- the existing invoker and service connections.

Schema provisioning (section A) is a site-owner schema change in its own approved step.
