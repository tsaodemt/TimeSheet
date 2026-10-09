# Roadmap (epic structure)

| Epic | Scope | Status |
|---|---|---|
| 01 Platform Foundation | Legacy analysis; staging environment aligned with production site settings | Done |
| 02 Employee Master | Reference lists and employee master migrated and reconciled in staging | Done |
| 03 Identity & Authorization | Entra sign-in; role groups; write/read proxy; permission model; permission test suite | In progress (write and read proxy PASS; guard and role tests PASS; operational permission model approved; confidential container and production service identities waiting for decisions) |
| 04 Remaining Master Data | Projects, phases, work/hour types, holidays, settings | Planned |
| 05 Application UI Foundation | Power Platform environment and ALM; app shell; guard-flow framework; audit | Planned |
| 06 Timesheet Core | Entry, pay-period engine, summary, timesheet guard flows | Planned |
| 07 Approval & Locking | Approve / unapprove flows; immutability; direct-edit monitor; lock visual and pending count; role / rule tests | Done (2026-10-09, STAGING; S07.1–S07.6 done; delete / reorder business paths not built yet) |
| 08 Historical Migration | Decision closure; loaders; reconciliation; timed delta rehearsal | Planned |
| 09 KPI | KPI sheets, scoring stages, folder-scoped security | Planned |
| 10 Salary & Finance | Rates and project finance in the confidential container | Planned |
| 11 Reporting | Power BI models with RLS | Planned |
| 12 Administration | Admin screens, health monitoring, backup/restore drill | Planned |
| 13 Feature Parity Verification | Parity catalogue and rule tests | Planned |
| 14 UAT | User acceptance | Planned |
| 15 Production Cutover | Freeze, final migration, go-live | Planned |
| 16 Project Effort Registration | New requirement: project effort registration and actual effort | Captured; decisions open |
| 17 Discipline Effort Planning & Approval | New requirement: discipline plan, allocation ceiling, approval and lock | Captured; decisions open |
| 18 Effort Analytics & Resource Evaluation | New requirement: registered vs actual, cost and resource evaluation | Captured; decisions open |

New epics and business areas start with an Open Spec, not with code (`delivery-process.md`). Next: Open Spec for R3 Planning & Effort (Hour Registration S12.5, EPIC 16, EPIC 17); no implementation before spec approval.

Tenant portability: the system must be rebuildable in another Microsoft 365 tenant (configuration-driven URLs and IDs, stable business keys, old→new UPN mapping, provisioning scripts, solution export, restore runbook). This is tracked as an administration story.

## Permission model split

The storage security / permission-model story is split into three parts so that the operational path is not held up by confidential-data or production decisions:

| Part | Scope | Status | Blocks |
|---|---|---|---|
| a — Operational permission model (staging) | Non-confidential lists: proxy-only writes, guarded read/write, role/scope authorisation, service least privilege, soft delete, protected master data | Approved (done) | – |
| b — Confidential container and data | Salary, rates, finance, confidential KPI data, confidential audit log | Waiting for the confidential-container decision | Confidential features only |
| c — Production service identities | Permanent service accounts and connection ownership | Waiting for IT approval | Power Platform solution set-up, production flows, deployment, cutover |

## Release 1 (Employee Timesheet Pilot)

Operational scope only; confidential features are deferred. The confidential part of the identity/authorization entry gate stays open, but it gates confidential work only; it does not block operational schema provisioning, the guard-flow framework, operational permission validation or release 1. Temporary test identities and spike assets are removed only after the last release 1 live test that needs them. Critical path:

```text
Operational permission sign-off (done) -> operational schema standard columns (done) -> Power Platform environment and solution (after production service identities and environment decision) -> app shell, shared components, guard-flow framework -> timesheet core -> release 1 live test
```
