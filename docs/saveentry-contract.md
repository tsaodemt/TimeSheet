# SaveEntry (TS-SaveEntry) — contract and offline qualification

Status: **offline qualified with open decisions** (OFFLINE-SAVEENTRY-QUALIFICATION-01). Not deployed.
Reference `tools/timesheet/entries.py` (`save_entry`, `finalize_audit`) after `tools/identity/guard.py` (`authorize`,
capability `TS.EditOwnDraft`, scope self); generated flow `tools/powerautomate/build_r1_flows.py` (`save_draft_actions`);
business rules `docs/timesheet-r1-contracts.md`; audit decision `docs/auditlog-open-decisions.md` (AUD-F1 = option B);
Canvas consumer `tools/powerapp/demo-r1/scrEntry.pa.yaml`. Tests: `tools/timesheet/test_r1_save_flow.py` (RS01–RS25,
ET01–ET07, FG01–FG05, AF01–AF08; reference == flow, stored rows compared) and `test_saveentry_qualification.py`
(SQ01–SQ24).

## Chain

```
Canvas: 'TS-SaveEntry'.Run(ItemId, ETag, WorkDate, ProjectCode, PhaseCode, WorkTypeCode, ShiftCode, HourTypeCode, Hours, Remark)
  → guard (MyProfile_V2 on the INVOKER's connection → AccountUpn → one active row → live EMP group)
  → AuthorizationAllow/Deny audit row (mandatory, before anything else)
  → settings gate (PayPeriodStartDay, warn thresholds, ProjectAssignmentScoping, BusinessTimezone) → caller discipline
  → edit only: GET item (service) → NOT_FOUND / FORBIDDEN (owner) / LOCKED (not Draft) / CONFLICT (ETag ≠ stored)
  → lookups (service) → hours → date
  → warnings (caller's own same-day rows only) → write (service): POST create / MERGE with IF-MATCH = stored ETag
  → WriteProxy audit row (AUD-F1 B) → Response
```

## Field authority

| Field | Source |
|---|---|
| `OwnerUpn`, `ActorUpn` | trusted caller UPN (create); never rewritten by an edit |
| `Employee` (`EmployeeId`), `EmployeeItemId` | guard-resolved employee item id (create); never rewritten |
| `DisciplineCode` | caller's `Employees.Discipline` lookup code; missing → `CONFIG_INVALID` before any write |
| `PeriodKey` | derived server-side from WorkDate + `PayPeriodStartDay` (day ≥ start → next month; Dec → January) |
| `LegacyId` | `guid()` on create (`LegacyOrigin = New`); never written by an edit |
| `EntryStatus` | `Draft` on create; edit allowed only on Draft and does not change it |
| `CorrelationId`, `IsOnBehalf=false` | server |
| `WorkDate`, Project/Phase/WorkType/Shift/HourType (by code), `Hours`, `Remark`, `ItemId`, `ETag` | client input, validated |
| `OwnerUpn`, `ActorUpn`, `EmployeeId`, `Role`, `Scope`, `EntryStatus` request decoys | claimed only (audit) |
| `EmployeeItemId`, `Employee`, `CallerUpn`, `DisciplineCode`, `LegacyId`, `PeriodKey` | no request slot (reference: ignored) |

## Create / update

- `ItemId` empty/0 → create; > 0 → edit; non-integer → `NOT_FOUND`.
- Edit: the stored item must exist and not be Deleted (`NOT_FOUND`), be owned by the caller (`FORBIDDEN`), be Draft
  (`LOCKED`), and the client ETag must equal the stored ETag (missing or different → `CONFLICT`, no write). The MERGE
  sends `IF-MATCH` = the stored ETag; a concurrent change in between → SharePoint 412 → `CONFLICT`. No wildcard, no
  retry, no second unconditional write. Editable: WorkDate, lookups, Hours, Remark (+ re-derived PeriodKey,
  DisciplineCode, ActorUpn, CorrelationId).
- No approval and no delete operation in this contract.
- Validation order: lookups (`VALIDATION_LOOKUP`; project Active; phase active and an active ProjectPhases link to the
  project; work type / shift active; hour type exists; assignment scoping when `On`), hours (`VALIDATION_HOURS` unless
  0 < h ≤ 24), date (`VALIDATION_DATE` unless a valid `yyyy-MM-dd`). Unreadable reference data → `ERROR`.
- WorkDate is a business date stored as local midnight in UTC (Asia/Ho_Chi_Minh, POC P4); the same conversion is used
  for create, edit and the same-day warning query.
- Warnings never block: `WARN_HOURS_ENTRY` (> MaxHoursPerEntryWarn), `WARN_HOURS_DAY` (caller's same-day total >
  MaxHoursPerDayWarn), `WARN_DUPLICATE`, `WARN_RELOAD_REQUIRED` (new ETag not read back), `AUDIT_DEGRADED`.

## Response

`ok`, `resultcode`, `messagecode` (`MSG_<code>`), `itemid` (saved id; the item id on CONFLICT; else 0), `etag` (new
ETag or empty), `correlationid`, `warnings` (JSON array), `interim` (JSON array of interim settings), `auditstatus`
(`OK` / `AUDIT_DEGRADED`). Codes: `OK`; guard codes; `FORBIDDEN`, `NOT_FOUND`, `LOCKED`, `CONFLICT`,
`VALIDATION_LOOKUP`, `VALIDATION_HOURS`, `VALIDATION_DATE`, `CONFIG_UNRESOLVED`, `CONFIG_INVALID`, `ERROR` (reference
data unreadable or SharePoint write failure other than 412).

## Atomicity and audit

| Situation | Result |
|---|---|
| guard deny / validation / conflict | no write; WriteProxy row with Decision DENY; coded response |
| SharePoint write fails (non-412) | no row; `ERROR` |
| write succeeds, WriteProxy append fails | AUD-F1 option B: `ok=true`, `auditstatus=AUDIT_DEGRADED` + warning, run ends Failed (alert); no retry |
| decision (Authorization) append fails | run stops before any write; **no coded response** (gap 2) |
| caller-profile read fails | no write; **no coded response** (gap 2) |
| response fails after a committed write | the entry exists; the client sees a failure (gap 1 risk: a retried create duplicates) |

## Open decisions (not changed here)

1. **Create idempotency (R1-Q3)** — none: a retried create makes a second row (`WARN_DUPLICATE` shows it). RequestKey is
   out of scope; a production decision is required.
2. **Pre-write failure response** — caller-profile or decision-audit failure ends the run without a coded response
   (fail closed, nothing written). AppStart/ReadOwn now return `DIRECTORY_ERROR` / `INTERNAL_ERROR`; decide whether
   SaveEntry adopts the same.
