# Guarded Read-Proxy Security Spike

**Result: PASS** (staging environment). All values below are placeholders.

## Why

A least-privilege service identity cannot set the SharePoint `Author` field (see `security-write-proxy-spike.md`). With all writes done by the service, the SharePoint list setting "read own items" can no longer express ownership. Ownership is therefore stored in a business column (`OwnerUpn`), and reads are served by a guarded read flow.

## Setup

| Element | Description |
|---|---|
| Protected list | Temporary list in `<staging-site>`; unique permissions; **no** direct permission for employees or the reviewer group |
| Service identity | `<service-account>`: View, Add, Edit. **No** Delete, Manage Lists, Manage Permissions or Full Control |
| Read flow | Instant trigger, run-only sharing. Office 365 Users connection **provided by the caller** (trusted identity); SharePoint and Office 365 Groups connections embedded (service) |
| Reviewer check | Live membership of `<reviewer-group>`, read on every run |
| Dataset | > 5,000 synthetic rows across many synthetic owners (reserved `.invalid` domain), dated over nine months |
| Indexes | `OwnerUpn`, `WorkDate` |

## Request contract

| Input | Treatment |
|---|---|
| `Mode` (`own` / `team`) | `team` allowed only for live reviewer-group members |
| `RequestedOwner` | Reviewers only. For any other caller, a value different from the trusted caller → `FORBIDDEN` |
| `AfterId`, `PageSize` | Keyset cursor; page size clamped server-side to 1…500 |
| `FromDate`, `ToDate` | Optional bounded range on the indexed `WorkDate` |
| `CallerUpn`, `ClaimReviewer` | Decoys. Logged, never trusted |

Server-side query (no full-list load, no in-memory filtering):

```
$filter = OwnerUpn eq '<trusted-or-authorised-owner>'
          [and WorkDate ge datetime'<from>' and WorkDate le datetime'<to>']
          and Id gt <afterId>
$orderby = Id asc
$top     = <pageSize ≤ 500>
```

Defence in depth: after the query, every returned row is checked against the filter owner (leak check). One audit row is written per read: caller, mode, owner, result code, row count and cursor.

## Tests

| # | Property | Result |
|---|---|---|
| R1 | Own read with decoy `CallerUpn` and `ClaimReviewer=true` | Only the caller's rows are returned; the decoys are ignored |
| R1h | Forged `x-ms-user-*` headers | Overwritten by the gateway; no escalation |
| R2 | Paging and date range | Keyset pages are complete and non-overlapping; the cursor ends at 0 |
| R3 | Forged `RequestedOwner` (other employee, administrator) | `FORBIDDEN`, 0 rows |
| R4 | Independent check of every returned ID | 0 foreign rows; own-row set complete |
| R5 | Reviewer team read | Full scope, including targeted owner and date range; 500-row page cap |
| R6 | Fake reviewer after group removal | `FORBIDDEN` on the first run after removal |
| R7 | Direct list access (UI and REST, list and audit) | Denied / not found |
| R8 | Writes through the write proxy still work | OK |
| R9 | Modification of an approved row | `LOCKED` |
| R10 | Scale and platform | > 5,000 rows; indexed filters; keyset paging; Standard connectors only |

Threshold check: a filter on a non-indexed column fails with the list-view-threshold error. The same query on an indexed column succeeds in a few hundred milliseconds.

## Consequences

- `Author` is **not** an authorisation key. `OwnerUpn` plus the guarded proxies is the target pattern for timesheet data.
- Employees need no direct permission on the protected list. Revocation through group removal takes effect on the next flow run. The SharePoint front-end cache latency (see `runbook-identity-jml.md`) does not apply.
- The synthetic dataset is kept for the permission test suite and removed afterwards by an administrator under an audited change. The service identity is **not** given Delete for cleanup.
