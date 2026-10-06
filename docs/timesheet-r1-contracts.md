# Timesheet R1 contracts (own entries)

Design contract for the first vertical slice: an employee creates, edits and reads **own** timesheet entries. Every operation goes through guarded flows. It builds on the live-validated read/write proxies (`security-read-proxy-spike.md`, `security-write-proxy-spike.md`), the guard (`authorization-guard.md`) and the audit model (`audit-model.md`).

Status: design. The lists and flows are built later, following the backlog dependency order.

## Ownership

| Key | Meaning | Set by | Used for |
|---|---|---|---|
| `OwnerUpn` | Business and authorization owner | Guard flow, from the trusted caller | Every read filter and every edit check |
| `ActorUpn` | Who performed the operation | Guard flow, from the trusted caller | Audit, `IsOnBehalf` |
| `Author` / `Editor` | Platform metadata (always the service identity) | SharePoint | Nothing security-related |

- **Create:** owner = actor = trusted caller.
- **Edit:** only if the stored `OwnerUpn` equals the trusted caller, the entry is not locked, and the ETag matches. The owner and actor are never taken from the request, and an edit never rewrites `OwnerUpn`.
- **Read:** `OwnerUpn eq <trusted caller>`. A requested foreign owner is refused.
- **Not used:** the "read own items" list setting, `Author`-based checks, and per-item permissions.

## Entry fields (R1)

| Class | Fields |
|---|---|
| Trusted / derived (flow only) | `OwnerUpn`, `ActorUpn`, `IsOnBehalf`, employee reference, discipline, `PeriodKey`, business key, status, `CorrelationId` |
| User-editable | `WorkDate`, `Hours`, `Remark` |
| Lookups (validated server-side) | project (active only), phase of that project (active), work type, shift, hour type |
| Metadata | `Created`, `Modified`, `Author`, `Editor` |
| Later releases | approval fields, ordering, migration lineage |

## Read

Request:
- `FromDate` / `ToDate` (optional, bounded);
- `AfterId` (default 0);
- `PageSize` (clamped to 1…500).

Identity-, role- or scope-claiming fields are ignored and recorded by name only.

```
$filter  = OwnerUpn eq '<trusted caller>'
           [and WorkDate ge '<from>' and WorkDate le '<to>']
           and <status> ne 'Deleted'
           and Id gt <AfterId>
$orderby = Id asc
$top     = <PageSize>
```

- `OwnerUpn` and `WorkDate` are indexed before any data is loaded.
- The list is never loaded and then filtered in memory.
- Every returned row is re-checked against the owner. Any mismatch returns `ERROR_LEAK` and no rows.

Response:

```
{ok, code, message, correlationId, rows[{id, workDate, project, phase, workType, shift, hourType, hours, remark, status, etag}], nextAfterId, pageSize}
```

`nextAfterId = 0` marks the last page.

## Write (create / edit own draft)

Request:
- `ItemId` (0 = create);
- `ETag` (edit);
- `WorkDate`;
- project, phase, work type, shift and hour-type codes;
- `Hours`;
- `Remark`.

Checks, in order:
1. Guard for the own-draft capability with `self` scope. Identity and authorization codes per `authorization-guard.md`.
2. Edit only:
   - `NOT_FOUND` if the item does not exist;
   - `FORBIDDEN` if the stored owner differs from the caller;
   - `LOCKED` if the entry is approved;
   - `CONFLICT` if the ETag does not match.
3. Validation:
   - `VALIDATION_LOOKUP` for an inactive or unknown project, a phase not of the project, or an unknown lookup;
   - `VALIDATION_HOURS` unless 0 < hours ≤ 24;
   - `VALIDATION_DATE`.
4. Warnings: per-entry hours, per-day hours, possible duplicate. These do not block.
5. Write by the service identity only, which has no Delete permission. The flow derives the system fields.
6. One audit row per decision, with the run's correlation ID.

Response:

```
{ok, code, message, itemId, etag, correlationId, warnings[]}
```

## Time semantics

The business time zone is environment configuration: a site regional setting plus an app/flow setting, never a code constant. The current business requirement is Vietnam local time: UTC+07:00, `Asia/Ho_Chi_Minh`, no DST.

- `WorkDate` is a business calendar date in the business time zone, stored date-only.
- Business times are displayed in the business time zone.
- Audit and system timestamps (`TimestampUtc` / `OccurredOn`) stay in UTC and are never converted for storage.
- Business date from an instant: convert the UTC instant to the business time zone, then take the local date. Never truncate the UTC value. Example at UTC+07:00: `2026-10-06T18:30:00Z` → business date `2026-10-07`.
- No DST logic.

## Correlation

The flow run name is the correlation ID. It appears in:
- the response;
- the item;
- every audit row of the run;
- any error shown in the app.

## Result codes shown to users

Codes are stable and shown together with a short message and the correlation ID. Internal details are never shown: no list names, URLs, stack traces or other users' data.
