# ReadOwn (TS-ReadOwn) — contract and offline qualification

Status: **offline qualified, decisions implemented** (OFFLINE-READOWN-QUALIFICATION-01, OFFLINE-READOWN-GAP-FIX-01). Not deployed.
Reference `tools/timesheet/entries.py` (`read_own`, `ReadFilter`) after `tools/identity/guard.py` (`authorize`);
generated flow `tools/powerautomate/build_r1_flows.py` (`read_own_actions`); date semantics `tools/timesheet/business_dates.py`
and `tools/powerautomate/date_range.py` (POC P4 proven); Canvas consumer `tools/powerapp/demo-r1/scrMyTimesheets.pa.yaml`.
Tests: `tools/timesheet/test_r1_read_flow.py` (RR01–RR23, reference == flow), `test_readown_qualification.py` (RQ01–RQ20),
`test_readown_gapfix.py` (RF01–RF24).

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
  (normal path not completed → Respond_error: DIRECTORY_ERROR for a failed caller-profile read, INTERNAL_ERROR for a
   failed mandatory audit append or other internal step; no rows)
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
| `FromDate`, `ToDate` | `yyyy-MM-dd` business dates; **both mandatory**; missing, single, malformed or reversed → `VALIDATION_DATE` |
| `AfterId` | keyset cursor (integer ≥ 0) |
| `PageSize` | 1–500 (default 500; clamped) |
| `RequestedOwner` | optional; must equal the caller |

Business dates use the configured `BusinessTimezone` (Asia/Ho_Chi_Minh): a date is stored as local midnight in UTC; a
range is the half-open UTC interval [local from 00:00, local to+1 00:00). An undated read is forbidden. **No maximum span
is currently defined** (bounded by the mandatory range, PageSize ≤ 500 and keyset paging). **PeriodKey is not a request
field**: a pay period is sent as FromDate + ToDate; `TimesheetEntries.PeriodKey` is never used for filtering, ownership or
authorization by ReadOwn.

## Response (all values strings)

`ok`, `resultcode`, `messagecode` (= `MSG_<resultcode>`), `correlationid` (flow run id), `rows` (JSON array of
`{id, workDate, projectId, phaseId, workTypeId, shiftId, hourTypeId, hours, remark, status, etag}`), `nextafterid`
(last id when the page is full, else 0), `pagesize`. Failures return `rows = []`, `nextafterid = 0`, `pagesize = 0`.
Empty own result → `ok = true`, `rows = []`. Status filter: Draft and Approved returned; Deleted excluded server-side
(and by the leak check).

## Result codes

`OK`; guard codes `INVALID_IDENTITY`, `UNMAPPED_IDENTITY`, `DUPLICATE_IDENTITY`, `INACTIVE_EMPLOYEE`, `DIRECTORY_ERROR`,
`ROLE_NOT_ALLOWED` (and the other guard deny codes); `FORBIDDEN`; `VALIDATION_DATE`; `VALIDATION_LOOKUP` (bad
AfterId / PageSize); `CONFIG_UNRESOLVED` (business time zone); `ERROR` (TimesheetEntries query failed); `ERROR_LEAK`;
`DIRECTORY_ERROR` / `MSG_TEMPORARY_PROBLEM` (caller-profile read failed); `INTERNAL_ERROR` / `MSG_TEMPORARY_PROBLEM`
(a mandatory audit append — Authorization or ReadProxy — or another internal step failed). Every handled failure returns
the same keys with `rows = []`, `nextafterid = 0`, `pagesize = 0`; a mandatory audit failure never returns rows.

## Paging and volume

Keyset paging (`Id gt AfterId`, `$orderby=Id asc`, `$top ≤ 500`, `nextafterid`) returns every row exactly once across
pages (RQ12, RF20); the Canvas app pages with `nextafterid` and always sends a date range. The first indexed filter is
`OwnerUpn`; with the mandatory range the threshold risk of an undated owner-wide query no longer exists. A query that
still exceeds a SharePoint limit returns `ERROR` (safe, no rows).

## Decisions (OFFLINE-READOWN-GAP-FIX-01)

1. **Mandatory date range** — FromDate + ToDate required; undated reads → `VALIDATION_DATE`. No maximum span yet (a
   business-period cap would be a separate decision).
2. **PeriodKey** — not part of the request contract; pay periods are expressed as FromDate + ToDate.
3. **Coded failures** — `DIRECTORY_ERROR` (caller profile / directory), `ERROR` (TimesheetEntries query),
   `INTERNAL_ERROR` (mandatory audit or other internal failure); both audit appends stay mandatory.
