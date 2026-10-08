# ReadOwn (TS-ReadOwn) — contract and offline qualification

Status: **offline qualified with open decisions** (OFFLINE-READOWN-QUALIFICATION-01). Not deployed.
Reference `tools/timesheet/entries.py` (`read_own`, `ReadFilter`) after `tools/identity/guard.py` (`authorize`);
generated flow `tools/powerautomate/build_r1_flows.py` (`read_own_actions`); date semantics `tools/timesheet/business_dates.py`
and `tools/powerautomate/date_range.py` (POC P4 proven); Canvas consumer `tools/powerapp/demo-r1/scrMyTimesheets.pa.yaml`.
Tests: `tools/timesheet/test_r1_read_flow.py` (RR01–RR23, reference == flow) and `test_readown_qualification.py` (RQ01–RQ20).

## Chain

```
Canvas: 'TS-ReadOwn'.Run(FromDate, ToDate, AfterId, PageSize, RequestedOwner)
  → guard (TS.ViewOwn, scope self): MyProfile_V2 on the INVOKER's connection → AccountUpn → exactly one active row
    → live role group (EMP) → AuthorizationAllow/Deny audit row (mandatory)
  → validation: RequestedOwner, dates, BusinessTimezone (AppSettings, service), AfterId/PageSize
  → SERVICE query: TimesheetEntries?$filter=OwnerUpn eq '<trusted upn>' and WorkDate ge … and WorkDate lt …
       and EntryStatus ne 'Deleted' and Id gt <AfterId> &$orderby=Id asc &$top=<PageSize ≤ 500>
  → leak check (any foreign or Deleted row → ERROR_LEAK, no rows)
  → ReadProxy audit row (mandatory) → Response
```

## Ownership

| Field | Role |
|---|---|
| `OwnerUpn` (indexed) | **authoritative** ownership / security key (written from the trusted caller by the save flow) |
| `Employee` (lookup), `EmployeeItemId` | denormalised reference / query support — never an authorization input |
| `Author` | service metadata only |

The trusted UPN is the only owner value in the query. `OwnerUpn`, `ActorUpn`, `EmployeeId`, `Role`, `Scope` request
fields are logged as claimed values only; there is no request field for an employee item id or lookup.
`RequestedOwner` other than the caller → `FORBIDDEN` (never widens).

## Request

| Input | Rule |
|---|---|
| `FromDate`, `ToDate` | `yyyy-MM-dd` business dates; **both or neither**; reversed / malformed / single → `VALIDATION_DATE` |
| `AfterId` | keyset cursor (integer ≥ 0) |
| `PageSize` | 1–500 (default 500; clamped) |
| `RequestedOwner` | optional; must equal the caller |

Business dates use the configured `BusinessTimezone` (Asia/Ho_Chi_Minh): a date is stored as local midnight in UTC; a
range is the half-open UTC interval [local from 00:00, local to+1 00:00). No pay-period / PeriodKey input; no maximum
span is defined.

## Response (all values strings)

`ok`, `resultcode`, `messagecode` (= `MSG_<resultcode>`), `correlationid` (flow run id), `rows` (JSON array of
`{id, workDate, projectId, phaseId, workTypeId, shiftId, hourTypeId, hours, remark, status, etag}`), `nextafterid`
(last id when the page is full, else 0), `pagesize`. Failures return `rows = []`, `nextafterid = 0`, `pagesize = 0`.
Empty own result → `ok = true`, `rows = []`. Status filter: Draft and Approved returned; Deleted excluded server-side
(and by the leak check).

## Result codes

`OK`; guard codes `INVALID_IDENTITY`, `UNMAPPED_IDENTITY`, `DUPLICATE_IDENTITY`, `INACTIVE_EMPLOYEE`, `DIRECTORY_ERROR`,
`ROLE_NOT_ALLOWED` (and the other guard deny codes); `FORBIDDEN`; `VALIDATION_DATE`; `VALIDATION_LOOKUP` (bad
AfterId / PageSize); `CONFIG_UNRESOLVED` (business time zone); `ERROR` (TimesheetEntries query failed); `ERROR_LEAK`.

## Paging and volume

Keyset paging (`Id gt AfterId`, `$orderby=Id asc`, `$top ≤ 500`, `nextafterid`) returns every row exactly once across
pages (RQ12); the Canvas app pages with `nextafterid` and always sends a date range. The first indexed filter is
`OwnerUpn`: an owner with more than 5,000 rows makes an unbounded query exceed the list view threshold and return
`ERROR` (safe, no rows).

## Open decisions (not changed here)

1. **Unbounded read** — dates are optional by contract; without them the read is bounded by page size only. Decide
   before production: keep optional unbounded reads, or reject them / cap the span (`docs/auditlog-open-decisions.md`).
2. **Read-audit failure semantics** — if the Authorization or ReadProxy audit append fails (or the caller profile read
   fails) the run ends before `Respond`: fail closed (no rows reach the caller) but no coded response. AUD-F1 option B
   was decided for SaveEntry only; decide the read-side behaviour (e.g. a coded `ERROR` / `DIRECTORY_ERROR` response).
3. **PeriodKey** — the read is date-range based; PeriodKey is not an input. Confirm that a pay-period read is always
   expressed as a date range by the client.
