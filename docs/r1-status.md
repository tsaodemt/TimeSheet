# R1 status (authoritative summary)

As of 2026-10-08. Generic, public-safe summary; tenant-specific evidence is kept in the private working area.

| Area | Maturity | Evidence |
|---|---|---|
| SharePoint STAGING foundation | **DONE** | master lists, Employees, Projects, ProjectPhases, TimesheetEntries, AppSettings, AuditLog, permissions, indexes; ordinary users have no direct TimesheetEntries access |
| Identity STAGING pilot | **DONE** | demo identity proven interactively (one active employee, master read only, protected lists denied); temporary STAGING-only mappings recorded under `STAGING_TEMPORARY_BYPASS` (never valid for UAT / Production) |
| AppStart (TS-AppOpen) | **CLOSED** | `docs/appstart-contract.md` — AS01–AS20, AF01–AF18 |
| ReadOwn (TS-ReadOwn) | **CLOSED** | `docs/readown-contract.md` — RO01–RO30, RF01–RF24 |
| SaveEntry (TS-SaveEntry) | **CLOSED** | `docs/saveentry-contract.md` — SE01–SE44, SF01–SF24 |
| R1 offline readiness | **READY** (`OFFLINE_READY`) | `tools/alm/test_r1_release_readiness.py`; `docs/r1-error-semantics.md` |
| Deployment artifacts | **READY** (not deployed) | `docs/r1-deployment-package.md`, `docs/r1-staging-live-test-plan.md` |
| Power Platform STAGING deployment | **BLOCKED_BY_TENANT_CAPACITY** | a dedicated Sandbox needs ≥ 1 GB Dataverse database capacity; the tenant has none. Default, Production, Trial, Developer and Teams environments and PAYG are not used. |
| UAT | **NOT_STARTED** | |
| Production | **NOT_STARTED** | |

Maturity vocabulary: `OFFLINE_READY` (all offline qualification closed), `STAGING_DEPLOYMENT_BLOCKED`, `UAT_NOT_STARTED`,
`PRODUCTION_NOT_STARTED`. Offline tests never make a flow UAT- or Production-ready.

## Known limitations

`docs/r1-known-limitations.md` — notably `R1_KNOWN_LIMITATION_CREATE_RETRY_NON_IDEMPOTENT` (approved) and the
`STAGING_TEMPORARY_BYPASS` identity debt. Offline readiness is not UAT or Production readiness.

## Architecture (frozen)

Canvas App → Power Automate (connection references; invoker Users connection for identity, service SharePoint /
Groups connections for data) → SharePoint (sole data store). No Dataverse.

## Regression (offline)

Full offline suite green; reference implementations and generated flows are compared case by case in the WDL simulator;
flow laziness audit green. Counts are reported per task in the commit history.
