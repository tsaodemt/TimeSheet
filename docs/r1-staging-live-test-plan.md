# R1 STAGING live test plan (prepared; NOT executed)

Preconditions: dedicated STAGING Power Platform environment, deployment per `docs/r1-deployment-package.md`, first-live
checks passed. Demo / synthetic identities and DEMO_ONLY data only; every created row recorded for cleanup.

| # | Flow | Case | Expected |
|---|---|---|---|
| L01 | AppStart | demo identity opens the app | `OK`; employee code of the demo row; client config |
| L02 | AppStart | identity without an Employees row (test account if available) | `UNMAPPED_IDENTITY`, access-denied screen |
| L03 | ReadOwn | current pay period (FromDate + ToDate) | own rows only; Draft + Approved; no Deleted |
| L04 | ReadOwn | a foreign DEMO row in the same period | not returned |
| L05 | ReadOwn | request without dates | `VALIDATION_DATE` |
| L06 | ReadOwn | PageSize 2 over ≥ 3 own rows | `nextafterid`; next page completes the set without repeats |
| L07 | SaveEntry | create own Draft | `OK`, item id, ETag; row owned by the caller; PeriodKey derived |
| L08 | SaveEntry | create with forged OwnerUpn / EmployeeId decoys | persisted owner = caller |
| L09 | SaveEntry | edit a foreign row id with its ETag | `FORBIDDEN`, no write |
| L10 | SaveEntry | edit own Draft with the current ETag | `OK`, new ETag |
| L11 | SaveEntry | repeat L10 with the old ETag | `CONFLICT`, no write |
| L12 | SaveEntry | 5 h entry; day total > 12 h | `OK` with `WARN_HOURS_ENTRY` / `WARN_HOURS_DAY` |
| L13 | SaveEntry | post-write audit failure (only if it can be induced safely) | `OK` + `AUDIT_DEGRADED`, run Failed (AUD-F1 B); otherwise verified offline only |
| L14 | all | AuditLog | one decision row + one operation row per call, same correlation id |

Cleanup: delete the recorded DEMO rows by id; verify the TimesheetEntries count returns to the baseline.
