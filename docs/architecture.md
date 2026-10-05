# Target Architecture

```
Entra ID (SSO, security groups = roles)
        │
Power Apps (canvas, Teams/browser) ──calls──► Power Automate guard flows ──► SharePoint lists (system of record)
        │   UI only, not a security boundary      (service account connection)        │
        └──────────────────────────────────────────────────────────────────────── Power BI (RLS)
```

## Key decisions

| # | Decision | Reason |
|---|---|---|
| AD-1 | Two SharePoint containers: operational, and confidential (rates, finance, KPI, archives) | Operational-site owners must not see salary or finance data |
| AD-2 | **Guarded write proxy.** Users have no write permission on protected lists. All writes go through Power Automate guard flows running on a service-account connection. | Enforces own-only edit, on-behalf entry, approval lock and audit server-side, with no per-item permissions |
| AD-3 | **Guarded read proxy** (validated, see `security-read-proxy-spike.md`). Employees read their own rows through a guard flow that filters on the business-owner key. Employees and reviewers hold no direct permission on protected lists. | SharePoint `Author` cannot be set by a least-privilege service account, so Author-based "read own items" cannot express ownership |
| AD-4 | **`OwnerUpn` / `EmployeeItemId` is the business ownership key.** SharePoint `Author` is **not** an authorisation key. `ActorUpn` records who acted; `IsOnBehalf` marks delegated entries. | Separates ownership from the technical writer identity |
| AD-5 | Historical references use lookup / item-ID keys to the employee master, never Person columns | Former employees have no directory account |
| AD-6 | Large-list queries always start with an indexed column (`OwnerUpn`/`EmployeeItemId`, `WorkDate`/`PeriodKey`) and are paged by keyset (`Id gt <last>`) | 5,000-item list view threshold; growth past 100k rows |
| AD-7 | Standard connectors only (SharePoint, Office 365 Users, Office 365 Groups, Outlook, Teams, Approvals) | Licensing |
| AD-8 | Solution-aware components with environment variables for every URL and ID | Tenant portability; staging → production without editing |

## Guard-flow contract (write)

1. **Trusted caller.** Taken from the caller's **own** Office 365 Users connection ("provided by run-only user" / app user). Parameters such as `CallerUpn` are logged and never trusted. The platform `x-ms-user-*` headers are only cross-checked.
2. **Authorisation.** Live membership of the Entra role group, read through the service connection. Client-supplied role flags are ignored.
3. **Owner.**
   - The default owner is the caller. On-behalf entry requires the reviewer role.
   - The owner is resolved against the directory, and the canonical UPN is used for every write.
4. **State.** Approved entries are immutable (`LOCKED`); self-approval is blocked.
5. **Write.** Performed only by the service connection. Service rights: View, Add, Edit. **No** Delete, Manage Lists, Manage Permissions or Full Control.
6. **Audit.** One audit row per allow/deny decision. The same correlation ID is stored on the item, the audit row and the flow run.

## Read-proxy contract (validated)

- **Normal employee:** rows where `OwnerUpn` = trusted caller only. A requested foreign owner is refused.
- **Reviewer** (verified by live group membership): the broader scope; may target a specific owner.
- **Query:** server-side, with an indexed first filter, optional bounded date range, keyset paging and a capped page size. The list is never loaded and then filtered in memory.
- Defence in depth: every returned row is re-checked against the authorised owner.
- Every read is audited.
- Revocation through group removal takes effect on the next run, because there is no direct SharePoint permission to cache.

## List classes (permission model derived from the proxies)

| Class | Rule | Examples |
|---|---|---|
| P: proxy-only | No human permission; every read and write goes through guard flows | timesheet entries |
| W: flow-write | Authorised groups read directly; writes only through flows | audit log, project finance |
| M: master data | All staff read; the owning group writes | departments, holidays, projects |
| I: identity-bearing | All staff read; writes only through an audited flow, because the account link is the identity key (**proposed**, pending review) | employee master, role catalogue |

Custom permission levels:
- **Service:** View, Add and Edit items, plus Override List Behaviors. **No** Delete, Manage Lists or Manage Permissions.
- **Contribute without Delete.**

A reviewer level is not needed under the read proxy. **Proposed** (pending review): deleting a draft is a soft delete (hidden, audited, purged by a controlled job), so the service identity never needs Delete.

Identity resolution: see `identity-resolution.md`.

## Platform lessons from the spikes

- **Author stamping:** `ValidateUpdateListItem(Author, bNewDocumentUpdate=true)` is silently ignored for a service account with Contribute-level rights, **even with Manage Lists**. Only site-collection administrators were observed to succeed. This is why ownership is modelled explicitly (AD-3, AD-4).
- **Group revocation latency:** after removal from a security group:
  - guard flows (which check live membership) see the change immediately;
  - SharePoint front-ends intermittently honoured the old permission for about 20–25 minutes.
  - See `runbook-identity-jml.md`.
- **Platform identity headers:** `x-ms-user-*` headers injected by a client were overwritten by the connector gateway with the authenticated caller.
