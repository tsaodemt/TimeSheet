# R1 status (authoritative summary)

As of 2026-10-08. Generic, public-safe summary; tenant-specific evidence is kept in the private working area.

| Area | Maturity | Evidence |
|---|---|---|
| SharePoint STAGING foundation | **DONE** | master lists, Employees, Projects, ProjectPhases, TimesheetEntries, AppSettings, AuditLog, permissions, indexes; ordinary users have no direct TimesheetEntries access |
| Identity STAGING pilot | **DONE** | demo identity proven interactively (one active employee, master read only, protected lists denied); temporary STAGING-only mappings recorded under `STAGING_TEMPORARY_BYPASS` (never valid for UAT / Production) |
| AppStart (TS-AppOpen) | **CLOSED** | `docs/appstart-contract.md` — AS01–AS20, AF01–AF18 |
| ReadOwn (TS-ReadOwn) | **CLOSED** | `docs/readown-contract.md` — RO01–RO30, RF01–RF24 |
| SaveEntry (TS-SaveEntry) | **BLOCKED_BY_DESIGN_DECISIONS** | `docs/saveentry-contract.md` — 42/44 (SE30, SE37 open) |
| R1 offline readiness | **BLOCKED** | waits for the SaveEntry decisions below |
| Power Platform STAGING deployment | **BLOCKED_BY_TENANT_CAPACITY** | a dedicated Sandbox needs ≥ 1 GB Dataverse database capacity; the tenant has none. Default, Production, Trial, Developer and Teams environments and PAYG are not used. |
| UAT | **NOT_STARTED** | |
| Production | **NOT_STARTED** | |

Maturity vocabulary: `OFFLINE_READY` (all offline qualification closed), `STAGING_DEPLOYMENT_BLOCKED`, `UAT_NOT_STARTED`,
`PRODUCTION_NOT_STARTED`. Offline tests never make a flow UAT- or Production-ready.

## Decisions required before R1 offline readiness (SaveEntry)

1. **Create retry / idempotency (R1-Q3).** Today a retried create (e.g. after a lost response) writes a second row;
   `WARN_DUPLICATE` makes it visible. RequestKey is out of scope. Decide: accept the visible-duplicate behaviour for R1,
   or approve another mechanism.
2. **Coded response for pre-write failures.** A failed caller-profile read or a failed pre-write Authorization audit
   append stops SaveEntry before any write (safe) but returns no coded response. Decide whether SaveEntry adopts the
   AppStart / ReadOwn convention (`DIRECTORY_ERROR` for the profile, `INTERNAL_ERROR` for the audit,
   `MSG_TEMPORARY_PROBLEM`, no data). The post-write audit failure is already decided (AUD-F1 option B).

## Architecture (frozen)

Canvas App → Power Automate (connection references; invoker Users connection for identity, service SharePoint /
Groups connections for data) → SharePoint (sole data store). No Dataverse.

## Regression (offline)

Full offline suite green; reference implementations and generated flows are compared case by case in the WDL simulator;
flow laziness audit green. Counts are reported per task in the commit history.
