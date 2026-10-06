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
| Trusted / derived (flow only) | `OwnerUpn`, `ActorUpn`, `IsOnBehalf`, employee reference, discipline, `PeriodKey`, business key, `EntryStatus` (`Draft` / `Approved` / `Deleted`; soft delete = `Deleted`, no separate flag), `CorrelationId` |
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
           and EntryStatus ne 'Deleted'
           and Id gt <AfterId>
$orderby = Id asc
$top     = <PageSize>
```

- Date bounds are business dates. A date-only value is stored as local midnight of the business time zone, so the bound sent to SharePoint is that instant in UTC: at UTC+07:00, `FromDate` 2026-10-01 becomes `datetime'2026-09-30T17:00:00Z'` (a bound of `…-10-01T00:00:00Z` would miss the first day). The offset comes from configuration; a date-range read without it refuses with `CONFIG_UNRESOLVED`. To be confirmed in the timesheet POC (date round-trip).
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

Customer-facing wording is not decided yet. The app maps each code to a message; the flows return the code.

| Code | Source | Blocks the save |
|---|---|---|
| `OK` | flow | – |
| identity codes (`UNMAPPED_IDENTITY`, `INACTIVE_EMPLOYEE`, `DUPLICATE_IDENTITY`, `INVALID_IDENTITY`, `ACCOUNT_NOT_ALLOWED`, `DIRECTORY_ERROR`) | guard | yes |
| authorization codes (`ROLE_NOT_ALLOWED`, `SCOPE_NOT_ALLOWED`, `UNKNOWN_ACTION`, `UNKNOWN_SCOPE`, `DECISION_PENDING`, `TEMP_ROLE_INACTIVE`) | guard | yes |
| `CONFIG_UNRESOLVED` / `CONFIG_INVALID` | a required setting is not configured (`app-settings.md`) | yes |
| `NOT_FOUND`, `FORBIDDEN`, `LOCKED`, `CONFLICT` | edit checks | yes |
| `VALIDATION_LOOKUP`, `VALIDATION_HOURS`, `VALIDATION_DATE` | validation | yes |
| `WARN_HOURS_ENTRY`, `WARN_HOURS_DAY`, `WARN_DUPLICATE` | warnings (in `warnings[]`) | no |
| `ERROR_LEAK` | read leak check | read returns no rows |

## Configuration the operations need

The save needs the pay-period start day, the two warning limits and the project-assignment switch. If any of them is unresolved or invalid, the save refuses with `CONFIG_UNRESOLVED` / `CONFIG_INVALID`; it never assumes a value.

## Create idempotency (open)

Edits are protected by the ETag. Create idempotency is an open decision. The reference implementation keeps it pluggable:
- default: none — the app disables Save while a call is in flight, and `WARN_DUPLICATE` makes a repeated create visible;
- option under review: a client-generated request key stored in an indexed, unique column; a repeat of the same key by the same owner with the same values returns the existing entry (`OK_REPLAY`), any other reuse is refused (`IDEMPOTENCY_KEY_REUSED`) without revealing the other entry. This needs a schema change and is not provisioned.

## Reference implementation

`tools/timesheet/entries.py` implements the save and read rules above after the guard decision (`tools/identity/guard.py`); `tools/timesheet/test_entries.py` E01–E24 covers them offline. These offline tests are not the release live tests.
