# AuditLog and R1 read: open decisions (AUD-P1, AUD-F1; unbounded read RESOLVED)

Decision support only. Nothing here is approved or deployed. The recommendations are for the project owner to accept or reject.

Code: `tools/provisioning/r1_lists.py` (`aud_p1_options`, tests AL20/AL21), `tools/powerautomate/build_r1_flows.py`, `tools/timesheet/entries.py`.

## AUD-P1 — which SharePoint level the operational service identity gets on `AuditLog`

The audit list must be append-only. The service identity writes audit rows through the guard flows. It never edits or deletes them.

SharePoint has no add-only level: **Add Items depends on View Items** (and Open, View Pages). Any level that can append can also read rows.

| | A. Reuse `TS Service` | B. New `TS Audit Append` level |
|---|---|---|
| Base permissions | View, Add, **Edit** items, Open Items, View Versions, **Override List Behaviors**, Manage Personal Views, View Form Pages, Open, View Pages, Browse Directories, Browse User Info, personal web parts, Use Client Integration, Use Remote Interfaces, Create Alerts, Edit My User Info. The proven mask (Low 1011028839 / High 432) also carries **Use Self-Service Site Creation**, which is not in the documented list. | View Items, Add Items, Open, View Pages, Use Remote Interfaces. Mask Low 196611 / High 32 (computed; verify with `roledefinitions` after creation). |
| Can add audit rows | yes | yes |
| Reads rows | yes (needed by nothing in R1) | yes (a SharePoint dependency of Add Items) |
| Can edit existing rows | **yes**. Version history records the change, but the row is no longer trustworthy by design. | **no** |
| Can delete rows or versions | no | no |
| New role definition | no | yes: one per site, created by the provisioning script (a live permission-level change that needs approval) |
| Operations and debugging | A support fix through the service could rewrite history. Nobody should ever need to do that. | Corrections are made by an administrator under an audited maintenance change. The service can still read rows if a later support flow needs a CorrelationId lookup. |
| Portability | already scripted | scripted the same way (`rights_mask`), recreated per environment |

Exact right-by-right analysis (named BasePermissions, dependencies, absent rights): `tools/provisioning/r1_lists.py`
`aud_p1_analysis()` (test AL22) and the table below.

| Check (named BasePermissions) | A. `TS Service` (proven mask) | B. `TS Audit Append` (proposed) |
|---|---|---|
| Rights | ViewListItems, AddListItems, EditListItems, OpenItems, ViewVersions, CancelCheckout (Override List Behaviors), ManagePersonalViews, ViewFormPages, Open, ViewPages, **CreateSSCSite**, BrowseDirectories, BrowseUserInfo, AddDelPrivateWebParts, UpdatePersonalWebParts, UseClientIntegration, UseRemoteAPIs, CreateAlerts, EditMyUserInfo | ViewListItems, AddListItems, Open, ViewPages, UseRemoteAPIs |
| Dependencies complete | yes | yes (Add Items → View Items, View Pages, Open; Use Remote Interfaces → Open) |
| Add Items works | VERIFIED (spike) | INFERRED — STAGING probe needed before approval |
| View Items unavoidable | yes | yes |
| Edit Items absent | **no** | yes |
| Delete Items / Delete Versions absent | yes | yes |
| Manage Lists / Manage Permissions absent | yes | yes |
| Site / subsite creation absent | **no** (Use Self-Service Site Creation) | yes (no CreateSSCSite, ManageSubwebs, ManageWeb) |
| Unrelated broad rights | CancelCheckout, CreateSSCSite, Edit, personal views/web parts, alerts, client integration, directories, user info | none |
| Unknown bits | none | none |

**Recommendation: B.** It is the least privilege that can append. It takes Edit, Override List Behaviors and web-level extras away from the account that writes every audit row. The cost is one extra role definition per environment.

Before production, run a STAGING check (decision-gated) that the flow's SharePoint connector can append with level B, and that an edit attempt is refused with 403.

The `AuditLog` Phase 2 grant stays **BLOCKED by AUD-P1**. TS Service is not granted on `AuditLog` until this is decided.

## AUD-F1 — the business save succeeded but the final audit append failed

How the generated save flow behaves today (test AL17):
1. The decision row (`AuthorizationAllow`/`Deny`) is appended **before** any write. If it fails, the run stops and nothing is written.
2. The entry is written.
3. The `WriteProxy` row is appended. If it fails, the run fails and the app receives **no response**.

So the entry is persisted, but the user sees a failure. R1 create is non-idempotent (approved known limitation), so a retry creates a **duplicate**.

| | A. Fail the whole request | B. Business success + `AUDIT_DEGRADED` | C. Durable outbox / retry |
|---|---|---|---|
| Behaviour | Response `ok=false`, code `ERROR`, although the entry exists | Response `ok=true` with warning `AUDIT_DEGRADED`; the run is marked failed; operations are alerted | The flow writes the audit event to a durable outbox (or retries with a bounded policy); a sweeper appends it later; the response is `ok=true` |
| Data correctness | correct, but the client believes it failed | correct, and the client knows it was saved | correct |
| Duplicate risk | **high** while R1-Q3 is open: the user retries a "failed" create | low: the user sees success and does not retry | low |
| Audit integrity | the decision row exists; the operation row is missing and the gap is invisible to the user | the decision row exists; the missing operation row is flagged by the failed run plus an alert, and can be reconstructed from the entry (`CorrelationId`, `Modified`) | complete after the sweep; eventual consistency |
| User behaviour | retries → duplicates; confusion | continues normally; the warning can be shown discreetly | continues normally |
| Implementation | none (current) | small: run-after on the append, a warning, an alert; tests | large: another list or queue, a sweeper flow, idempotent append keyed by CorrelationId, monitoring |
| R1 suitability | **not suitable** while R1-Q3 is open | suitable | over-engineered for an R1 pilot |
| Production suitability | not suitable | acceptable only if the alert is monitored and a reconciliation procedure exists | best long-term option |

**Recommendation for R1: B**, together with a run-level alert and a documented reconciliation procedure. Evaluate C for production.

A reaches acceptable only after R1-Q3 provides create idempotency. With B, a user is never led into creating a duplicate. The decision row still proves the authorization, and the missing operation row stays detectable.

**Decided for R1 (project owner 2026-10-07): option B.** Implemented in the save flow template and the reference
(`auditStatus`, warning `AUDIT_DEGRADED`, run ends Failed for monitoring, correlation id = reconciliation key, no retry;
tests AF01–AF08). Option C (durable outbox / retry) is a production-hardening item that is **not designed**.
`TS-SaveEntry` is not deployed.

## R1 read without a date range (owner with more than 5,000 entries)

`TS-ReadOwn` accepts `FromDate`/`ToDate` as optional (both or neither; R1 contract). Without a range, the query filters only `OwnerUpn eq <caller>` (indexed) and `EntryStatus ne 'Deleted'`. If one owner holds more than 5,000 rows, that query exceeds the list view threshold and the read returns `ERROR`. At about 40–60 entries per period this is years away, but it is not impossible for long-serving staff after migration.

| Option | Contract change | Effect |
|---|---|---|
| 1. The app always sends a bounded range (current pay period; history screens send an explicit period) | none (the app only) | removes the risk for every app call; the API keeps optional dates for other callers |
| 2. The API keeps optional dates, documents the limit, and returns `ERROR` above the threshold | none | the current behaviour; the failure is safe (no rows, no leak) but not user-friendly |
| 3. The API rejects an unbounded read with `VALIDATION_DATE`, or limits the span (e.g. at most 12 periods) | **yes** (R1 contract) | threshold-safe by design |

**Recorded recommendation (project owner 2026-10-07):** the Power App always calls `TS-ReadOwn` with a bounded range,
normally the active pay period.

**RESOLVED (project owner, OFFLINE-READOWN-GAP-FIX-01): option 3 without a span cap** — `TS-ReadOwn` requires
`FromDate` and `ToDate`; an undated read returns `VALIDATION_DATE`. No maximum span is defined yet (separate decision).
Read-side audit failure is also decided: a failed Authorization or ReadProxy append returns `INTERNAL_ERROR` with no rows;
a failed caller-profile read returns `DIRECTORY_ERROR` (`docs/readown-contract.md`).

Earlier recommendation (superseded): adopt 1 now and decide between 2 and 3 before production. Decided: 3 (mandatory range, no cap yet).

## Fixed in this change (no decision needed)

- **Save audit record link.** The `WriteProxy` row now stamps `TargetLegacyId`, the stored record's `LegacyId` (audit model: owner and target values come from the stored record):
  - on create: the value the flow wrote (a new row's `LegacyId` is a generated GUID);
  - on edit: the value read from the stored item.

  It is stamped together with `TargetItemId` only. A refused save has no record link. No legacy ID is invented. Tests FG01–FG03.
- **Employee without Discipline.**
  - The guard selected `DisciplineCode` from `Employees`, but the operational list has only the required `Discipline` lookup to `Disciplines`. SharePoint answers `400 "The field or property 'DisciplineCode' does not exist"`, so every caller would have got `DIRECTORY_ERROR`.
  - The R1 flows now project `Discipline/DisciplineCode` (`$expand=Discipline`; `guard_template.EMPLOYEES_FIELDS`).
  - Both `Employees.Discipline` and `TimesheetEntries.DisciplineCode` are required. An employee row without a discipline is therefore a master-data **configuration error**: the save refuses it with `CONFIG_INVALID` before any write. The discipline is never guessed.
  - Reading own rows does not need the discipline and still works.
  - Tests FG04, FG05, RR23. The maintenance flow template still uses the legacy field set; align it in its own story.
