# R3 acceptance criteria (proposed; require owner approval)

Each criterion is observable and traceable (requirement / legacy row / decision). "Live" = STAGING with synthetic data. These are implementation acceptance criteria; the current Open Spec remains NOT APPROVED until AC-SPEC-* passes.

## S12.5 Hour Registration

| AC | Criterion (measurable) | Trace |
|---|---|---|
| AC-REG-01 | For a synthetic 13 × 5 matrix and a real-shape 6 × 5 matrix containing BLANK, explicit 0, integers and 2-decimal values and a large value (no business maximum, OD-42), save + reload returns every cell in the same state and value (0 differences) | S12.5 AC, OD-01, OD-03 |
| AC-REG-02 | A first successful user Save containing k genuinely changed cells (1 ≤ k ≤ 100; current designed maximum 13 × 6 = 78) is submitted in one guarded flow call and produces exactly one WriteProxy row per committed changed cell; unchanged cells have unchanged ETags | LHR-18, planning-audit |
| AC-REG-03 | A request with any invalid or unauthorised cell writes 0 items (REFUSED) | design §9.2 |
| AC-REG-04 | Two editors changing the same cell: the second Save is REFUSED at preflight with that cell CONFLICT and 0 cells written, and the stored value equals the first editor's; editors changing different cells are both stored; a change landing between preflight and write yields PARTIAL with the affected cell CONFLICT | LHR-29, design §9.2–9.3 |
| AC-REG-05 | Every role in the approved matrix gets the approved REG.View / REG.Edit result live (0 unexpected allow / deny); viewers have no Save and a forged save returns ROLE_NOT_ALLOWED | LHR-24/25, OD-04/05 |
| AC-REG-06 | Duplicate project codes: opening and saving each project touches only the selected project's stable-key/lookup rows, never another same-code project | LHR-06 |
| AC-REG-07 | Matrix rows equal the project's phases in project order (OD-02); a save on a phase outside the project is refused; columns = every discipline of the master by sort order (OD-08); a value on a removed phase stays stored, is not shown or editable, is counted in the project total, and is cleared (item kept, Clear audited) by the next successful save; re-adding the phase shows it again | LHR-10/12/14, OD-08 |
| AC-REG-11 | A project whose target status is not Active is listed and editable exactly like an active project (OD-07) | OD-07 |
| AC-REG-12 | VIEW / EDIT per role equal the OD-04/OD-05 table: VIEW Team Leader, Approver, Executive, PMO, HR, IT Support; EDIT Executive, PMO; all other roles denied server-side | OD-04, OD-05 |
| AC-REG-08 | Non-numeric input, more than 2 decimals and negative values are rejected client-side and server-side with a typed message; 0 and large values are accepted (no business maximum; only the platform numeric range applies as a TECHNICAL_LIMIT) | LHR-15/16, OD-03, OD-42 |
| AC-REG-09 | No protected planning list is a Canvas data source; an ordinary user's direct SharePoint REST **read and write** are denied while guarded read/write flows enforce capability | planning-security |
| AC-REG-10 | If migrated (OD-11): 199 items (195 non-zero + 4 explicit zeros stored as 0; 271 blank cells → no item; orphan file excluded with 0 values), Σ per project equals the legacy total (8,648 overall), stale rows per OD-08, 0 silent loss | design §12, OD-01, OD-09 |

## EPIC 16 Project Effort (after M2 decisions)

| AC | Criterion | Trace |
|---|---|---|
| AC-EFF16-01 | Only the project's authoritative PM (OD-24) can save its allocations; PMO / Executive without the designation, other roles and other projects get ROLE_NOT_ALLOWED or SCOPE_NOT_ALLOWED with 0 writes; a project without a PM is not editable | NR-EFF-01, OD-24 |
| AC-EFF16-02 | Stored allocations are in man-days with at most 2 decimals (OD-14 resolved); input with more than 2 decimals or a negative value is rejected server-side with VALIDATION_VALUE (no rounding/truncation); 0 and large values are accepted (minimum 0, no business maximum, OD-44; platform range only as TECHNICAL_LIMIT); keep blank (not registered) distinct from explicit 0 (OD-40 resolved), one lifetime value per project × recipient with no phase or period key (OD-22, OD-23), entered manually by the PM with no formula or import (OD-16) | NR-EFF-01 |
| AC-EFF16-03 | A.I has no approval/lock workflow in current scope; a successful guarded PM save is effective immediately and produces no Approval event | resolved OD-26 |
| AC-EFF16-04 | Actual effort is derived from existing TimesheetEntries (OD-19 resolved): no new actual-effort list, workflow or entry screen; existing trusted owner/on-behalf semantics unchanged; forged owner claims never grant ownership; man-days = Σ Approved hours ÷ `HoursPerManDay` in the contract, Draft excluded (OD-33 resolved) (OD-41 NOT_APPLICABLE) | NR-EFF-05, OD-19, OD-33, OD-41 |
| AC-EFF16-05 | Only PMO can assign / change a project's authoritative PM; the PM must be an ACTIVE employee resolved server-side (inactive / unknown → VALIDATION_LOOKUP); each change is audited with old and new PM; client PM claims are ignored | OD-24 |
| AC-EFF16-06 | Project Effort (planned and Approved actual total) is visible live to the project's PM (own projects only), PMO and Executive; every other role is denied server-side (0 unexpected allow / deny) | OD-37 |
| AC-EFF16-07 | The project-level Approved actual total (hours and man-days = hours ÷ `HoursPerManDay`) equals the synthetic expected total (Draft and Deleted excluded) and no Project Effort response contains a Timesheet row, employee or date | OD-19, OD-33, OD-37 |

## EPIC 17 Discipline Effort (after M3 decisions)

| AC | Criterion | Trace |
|---|---|---|
| AC-EFF17-01 | A staff member can register only in the approved discipline/ownership scope (cross-discipline → SCOPE_NOT_ALLOWED) | NR-EFF-02, OD-30 |
| AC-EFF17-02 | No accepted save makes the decided ceiling total exceed the allocation, including two concurrent saves | NR-EFF-03, OD-15 |
| AC-EFF17-03 | Only the OD-17 Chủ trì can approve; approval locks the row; every role gets LOCKED on ordinary change afterwards | NR-EFF-04/06 |
| AC-EFF17-04 | Self-approval behaves exactly as OD-28 | OD-28 |
| AC-EFF17-05 | No unlock path exists unless OD-18 defines one; if defined later, its audit semantics are specified before implementation | OD-18 |

## Shared R3

| AC | Criterion | Trace |
|---|---|---|
| AC-R3-01 | Exactly one AuthorizationAllow/Deny per flow call; exactly one WriteProxy per committed changed value; exactly one Approval business event per approved item (lock is the resulting state, not a second event) | planning-audit |
| AC-R3-02 | Persisted R3 facts support an offline/reference reconciliation of planned, actual and variance using explicit source-unit normalisation; legacy HourRegistration stays man-days; no salary/rate/cost column; no EPIC18 analytics surface is required to pass R3 | effort-reporting-contract |
| AC-R3-03 | Service permissions unchanged (View/Add/Edit, no Delete / ManageLists / ManagePermissions); ordinary direct read/write to protected planning lists denied after R3 deployment | D-7, planning-security |
| AC-R3-04 | Stable canonical keys use environment-portable immutable master identifiers; SharePoint ItemId is used only as an environment-local lookup/query accelerator | design §5 |

## Open Spec approval gate

| AC | Criterion |
|---|---|
| AC-SPEC-01 | Project owner records approval of proposal, design, specs, acceptance and the role matrix (date, role/name as appropriate) |
| AC-SPEC-02 | All BLOCKING decisions of the milestone to start are answered and recorded; conditional blockers are closed when their triggering option is selected |
| AC-SPEC-03 | `openspec validate` passes for this change |
| AC-SPEC-04 | Tasks in `tasks.md` are re-baselined after decisions and only then marked approved for implementation |
