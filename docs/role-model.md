# Role Model (target)

Security roles come **only** from Entra security groups (`SG-TS-*`). The app's module visibility (Hide/Read/Write) is a UI convenience. Enforcement is SharePoint permissions + guard flows + Power BI RLS.

| Role | Group | Scope | Key capabilities |
|---|---|---|---|
| Employee | `SG-TS-Employees` | self | Own draft entries; own KPI self-score; own reports |
| Team Leader | `SG-TS-TeamLeaders` | own discipline | On-behalf entry, approve (discipline); never unapprove |
| Approver | `SG-TS-Approvers` | company | Approve / unapprove; on-behalf entry |
| Executive | `SG-TS-Executives` | company | Approver rights + project create/delete, finance edit (per policy) |
| PMO | `SG-TS-PMO` | projects | Project edit (no delete), hour registration, contract/other-cost edit |
| HR | `SG-TS-HR` | company | Employee master, rates (with Salary Viewer) |
| Salary Viewer | `SG-TS-SalaryViewers` | rates | Additive: view rates / labour cost |
| Finance | `SG-TS-Finance` | finance | Project finance, cost structure |
| App Administrator | `SG-TS-AppAdmins` | application | Configuration, roles; **no** approve/unapprove; **no** access to salary, finance or KPI data |
| IT Support | `SG-TS-ITSupport` | operations | Operational audit, health |
| Confidential Site Owner | `SG-TS-ConfOwners` | confidential site | Ownership of the confidential container |
| Migration Owner (temporary) | `SG-TS-MigrationOwners` | migration | Removed after hypercare |

Rules:
- Capabilities are the **union** of a person's roles.
- Approved entries are immutable for every role. No role may approve or unapprove its own entry (see `approval-capability-rules.md`).
- The legacy Director role is retired; it has no target role.
- **Unresolved production identities receive Employee rights only.** No elevated role is granted until HR/IT confirm the assignment.
- Business-role membership is owned by HR; administrative groups by IT. Access is reviewed quarterly.
- **Proposed** (pending IT approval): staging and production share a tenant, so they use separate groups (`SG-TS-STG-*` vs `SG-TS-*`). Staging test memberships never reach production groups. Group IDs come from per-environment configuration.
