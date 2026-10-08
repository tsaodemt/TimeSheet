# R1 cross-flow result semantics

Intentional meanings shared by TS-AppOpen (AppStart), TS-ReadOwn and TS-SaveEntry. Codes are not normalised where the
meaning differs.

| Code | Meaning | Flows | Message |
|---|---|---|---|
| `DIRECTORY_ERROR` | caller profile (MyProfile_V2) or directory / Employees lookup operational failure | all | `MSG_TEMPORARY_PROBLEM` from the error responder; the guard path keeps `MSG_<code>` in ReadOwn/SaveEntry |
| `INTERNAL_ERROR` | a mandatory internal / infrastructure step failed and no more specific code applies (mandatory audit before data is returned or written) | all | `MSG_TEMPORARY_PROBLEM` |
| `ERROR` | SharePoint TimesheetEntries operation failure (ReadOwn query, SaveEntry write other than 412) or unreadable reference data | ReadOwn, SaveEntry | `MSG_ERROR` |
| `CONFLICT` | ETag optimistic-concurrency conflict (stale / missing ETag, SharePoint 412) | SaveEntry | `MSG_CONFLICT` |
| `AUDIT_DEGRADED` | SaveEntry write committed but the post-write WriteProxy append failed (AUD-F1 option B): `ok=true`, warning + `auditstatus`, run ends Failed for alerting | SaveEntry | warning, not a result code |
| `INVALID_EMPLOYEE_REFERENCE` | AppStart only: required Department / Discipline does not resolve | AppStart | `MSG_TEMPORARY_PROBLEM` |

Pre-write vs post-write audit: an audit append that guards data **before** it is returned or written is mandatory and
fails closed (`INTERNAL_ERROR`, no data, no write). The SaveEntry WriteProxy append **after** a committed write follows
AUD-F1 option B (`AUDIT_DEGRADED`).

Every flow ends in exactly one PowerApp response (`Respond` or `Respond_error`) with a fixed key set per flow. Contracts:
`docs/appstart-contract.md`, `docs/readown-contract.md`, `docs/saveentry-contract.md`.
