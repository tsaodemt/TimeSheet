# Roadmap (epic structure)

| Epic | Scope | Status |
|---|---|---|
| 01 Platform Foundation | Legacy analysis; staging environment aligned with production site settings | Done |
| 02 Employee Master | Reference lists and employee master migrated and reconciled in staging | Done |
| 03 Identity & Authorization | Entra sign-in; role groups; write/read proxy; permission model; permission test suite | In progress (write and read proxy PASS; identity resolution specified and tested; approvals pending) |
| 04 Remaining Master Data | Projects, phases, work/hour types, holidays, settings | Planned |
| 05 Application UI Foundation | Power Platform environment and ALM; app shell; guard-flow framework; audit | Planned |
| 06 Timesheet Core | Entry, pay-period engine, summary, timesheet guard flows | Planned |
| 07 Approval & Locking | Approve / unapprove flows; immutability; direct-edit monitor | Planned |
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

Tenant portability: the system must be rebuildable in another Microsoft 365 tenant (configuration-driven URLs and IDs, stable business keys, old→new UPN mapping, provisioning scripts, solution export, restore runbook). This is tracked as an administration story.
