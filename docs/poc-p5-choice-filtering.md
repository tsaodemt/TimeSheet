# POC P5 — choice-column filtering (procedure)

Status: **PROCEDURE READY / NOT EXECUTED.** Running it needs its own live approval. Machine-checkable version: `tools/timesheet/poc_procedures.py` (`P5`), checked by `test_poc_procedures.py`.

## Scope

IMPLEMENTATION-SPEC §11.4 requires choice-column equality to be proven in POC P5, or replaced by a text code column. R1 depends on this in two places:
- the read and save flows filter `EntryStatus` (a Choice column) server-side, through REST `$filter`. P5 proves this part on the existing data;
- the app may filter Choice columns on lists it reads directly, for example the active projects (P5-A). That part is blocked until the canvas app and the Projects list exist.

Offline simulation is not evidence of SharePoint's choice-filter semantics. P5 compares SharePoint's actual result with the reference.

## Data

- Reuse the existing synthetic read-proxy list: more than 5,000 rows, with `OwnerUpn` and `WorkDate` indexed. P5 does not create thousands of rows.
- Read-only precondition: `EntryStatus` is a Choice column with Draft / Approved / Deleted. Record the row counts per status for the synthetic owners.
  - If it is not a Choice column on that list, run P5 on `TimesheetEntries` after S06.1 instead.
- New rows only if a status is missing for a synthetic owner: exactly 6 (2 Draft, 2 Approved, 2 Deleted, on 3 business dates). Each carries the tag `SYNTH-POC-P5-<yyyymmdd>`.

## Checks

| Id | Verifies | Filter / expectation |
|---|---|---|
| P5-01 | Draft | `OwnerUpn eq '<owner>' and EntryStatus eq 'Draft'` = reference count |
| P5-02 | Approved | `... and EntryStatus eq 'Approved'` = reference count |
| P5-03 | Deleted exclusion | `... and EntryStatus ne 'Deleted'` returns no Deleted row |
| P5-04 | OwnerUpn + EntryStatus | P5-01..03 = counts from an owner-only read, compared client-side |
| P5-05 | date + status | the exact `TS-ReadOwn` filter for a date range (half-open UTC interval, proven by P4) |
| P5-06 | status filter alone, non-indexed | `EntryStatus eq 'Draft'` → list-view threshold error (status is never the first or only filter) |
| P5-07 | indexed first filter | P5-03 at more than 5,000 rows succeeds |
| P5-08 | Power Automate query syntax | the generated `Filter` output, byte for byte (`test_poc_procedures.py` PP06 pins its shape) |
| P5-09 | paging stability | P5-03 + `Id gt <AfterId>`, `$orderby Id`, small `$top`; the pages concatenated equal a single query, with no duplicates |
| P5-A | app-side choice delegation | `Status.Value = "Active"`: Studio delegation warnings + solution checker (blocked: app, Projects list) |

Indexing `EntryStatus` would change the list schema, so P5 does not add that index. Whether to index it is part of the S06.1 index plan.

## Safety

- STAGING only; MAIN stays read-only. Filter reads run as the site administrator; there is no service identity substitution.
- Cleanup (only if new rows were created): recycle each tagged row after re-reading its tag and owner. Verify that 0 tagged rows remain and that the list count is back to its pre-write value.
