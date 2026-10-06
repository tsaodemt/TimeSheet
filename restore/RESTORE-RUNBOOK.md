# Restore Runbook: rebuild the Timesheet system in the same or another tenant

| | |
|---|---|
| Status | **DRAFT. This is a design document.** It has never been executed end to end. See §14 for what is not proven. |
| Scope | Rebuilding the Microsoft 365 Timesheet system (SharePoint lists, AppSettings, Entra groups, service identities, Power Platform solution and data) into an **empty** target site and environment. The target can be in the same tenant or in another tenant, for disaster recovery or a tenant move. |
| Package | This folder (`restore/`). See `README.md` for what is in the package today and what is still missing. |
| Audience | Customer IT administrator, project release manager, HR/IT approvers |
| Related | `docs/provisioning.md`, `docs/app-settings.md`, `docs/role-model.md`, `docs/identity-resolution.md`, `docs/audit-model.md`, `docs/architecture.md` (AD-4, AD-5, AD-8), `docs/runbook-identity-jml.md` |

## Labels used in this runbook

| Label | Meaning |
|---|---|
| **PROVEN-LIVE** | Exercised against a real site or tenant in the build environment, with evidence |
| **PROVEN-OFFLINE** | Covered by automated tests or simulation in `tools/` (synthetic data, injected transport). Not a live proof. |
| **DESIGN** | Specified in project documents, but never executed |
| **DECISION** | Not specified anywhere. A named person must decide before the step can run. |

## Placeholders

The package contains **no tenant-specific values**. Every value below is supplied by the operator at run time from a confidential, per-environment settings file. That file is kept outside the public repository.

| Placeholder | Meaning |
|---|---|
| `<source-tenant>` / `<target-tenant>` | Source and target Microsoft 365 tenants (they can be the same tenant) |
| `<source-site-url>` / `<target-site-url>` | Operational SharePoint site, source and target |
| `<target-conf-site-url>` | Confidential container in the target, if confidential features are in scope |
| `<target-domain>` | UPN domain(s) allowed in the target, which become the `AllowedDomains` environment variable |
| `<svc-operational>` | Service identity that owns the operational guard flows and connections |
| `<svc-confidential>` | Service identity for confidential guard flows (only if confidential features are in scope) |
| `<svc-bi>` | Power BI refresh identity (only if reporting is in scope) |
| `<target-pp-environment>` | Target Power Platform environment |
| `<PFX>` | Solution publisher prefix. It must be the **same** in every environment and tenant. |
| `<settings-file>` | Per-environment deployment settings (environment-variable values and connection IDs). It is confidential. |
| `<upn-map>` | `upn-migration-map.csv`, the reviewed OldUpn to NewUpn mapping (§6) |

---

## 0. Order of steps

```
 1 Prerequisites and decisions          (stop if any decision is open)
 2 Target site(s) and regional settings
 3 Schema: lists, columns, indexes      schema_reconcile: dry run → apply → second run is a no-op
 4 Groups and service identities        by role naming pattern; approval required
 5 List permissions                     needs the groups and identities from step 4
 6 Reference / seed data                reference_data; AppRoles after the groups exist
 7 Environment configuration            AppSettings registry + overlay; unresolved settings stay unresolved
 8 UPN mapping file                     reviewed and approved; never generated automatically
 9 Power Platform solution import       managed; environment variables from the settings file
10 Connection references                bound to connections owned by service identities
11 Data load and UPN rewrite            business keys preserved; item-ID references re-keyed
12 Data reconciliation                  counts, keys, lookups, sums
13 Cutover validation                   smoke tests and go/no-go
14 What is not yet proven
15 Rollback and abort points (summary)
```

> **Order differs from the backlog task.** The backlog task lists the order as "sites → schema/indexes/views → permissions → groups/service identities → solution import → data load → reconciliation". This runbook creates groups and service identities **before** the list permissions, because a permission grant needs an existing principal. It also loads `AppRoles` after the groups exist (§6). The order needs to be confirmed when the package is finalised.

---

## 1. Prerequisites and decisions

| # | Prerequisite | Verification |
|---|---|---|
| 1.1 | Written approval for the restore: target tenant, target site(s), target Power Platform environment, and the person accountable | Approval record exists (who, when, scope) |
| 1.2 | Target site(s) are **empty** and are **not** the tenant root site. The provisioning tool refuses root sites (`docs/provisioning.md`, site guard). | Read-only inventory of the target shows no Timesheet lists; the URL path starts with `/sites/` or `/teams/` |
| 1.3 | The source system is frozen (read-only), or a consistent export point is fixed and recorded | Freeze time recorded; source write permissions removed or flows turned off |
| 1.4 | Source data export available: every list of the system of record, with business keys (`LegacyId`, codes) and lookup business keys, plus audit lists | Export manifest with row count and checksum per list |
| 1.5 | Target schema definition (JSON), reference-data seeds and list rules, AppSettings registry and the **target** overlay, all taken from source control at a tagged version | Version or tag recorded; files hash-checked |
| 1.6 | Managed solution package (`Timesheet`) at the same version as the source, plus a settings-file **template** (keys only) | Package version recorded; template contains no values |
| 1.7 | Publisher and prefix `<PFX>` are the same as in the source. Upgrades need the same publisher. | Publisher name and prefix match the source manifest |
| 1.8 | Licences in the target: Power Automate for the service identity (standard connectors only) and Power BI if reporting is in scope | IT confirmation |
| 1.9 | DLP in the target environment: SharePoint, Office 365 Users and Office 365 Groups are in the same group; HTTP and custom connectors are blocked | DLP policy screenshot or export; a test flow with HTTP is refused |
| 1.10 | **Decisions closed** (§1a) | Every row in §1a has an owner, a decision and a date |

### 1a. Decisions that must be closed before step 3

| ID | Decision | Why it blocks |
|---|---|---|
| R-D1 | Is the target the same tenant (DR) or another tenant (tenant move)? | A tenant move needs a UPN map (§8) and new groups and identities. Same-tenant DR may reuse them. |
| R-D2 | Are confidential features in scope (a separate confidential container and `<svc-confidential>`)? | Decides whether steps 2–11 run for a second site |
| R-D3 | Rule for **historical actor values** in audit rows (`ActorUpn` in `AuditLog` / `ConfidentialAuditLog`) | Not documented. See §11.4. |
| R-D4 | Rule for rewriting **business-owner UPN text columns** (`OwnerUpn`) during the load | The project documents describe re-resolving Person columns and remapping `AccountUpn`, but no explicit rule for `OwnerUpn` text columns. See §11.3. |
| R-D5 | Where role-group IDs are held: only in the solution environment variable (`RoleGroupMap`), or also in `AppRoles` rows | The documents differ. See §6.3. |
| R-D6 | Source of the service-account UPN, if one is needed at run time: environment variable or AppSettings overlay | Open in the AppSettings design. `docs/app-settings.md` places tenant bindings in environment variables. |
| R-D7 | Whether `Created`/`Modified`/`Author` provenance must be kept. These cannot be preserved by a least-privilege service identity (`docs/architecture.md`, platform lessons). | Decides whether the provenance moves into explicit columns (`LegacyModifiedOn` etc.) or is accepted as lost |

**Abort point A0:** if any decision is open, stop. Nothing has been changed yet.

---

## 2. Target site(s) and regional settings: DESIGN

| # | Action | Verification |
|---|---|---|
| 2.1 | IT creates the empty operational site `<target-site-url>` (and `<target-conf-site-url>` if R-D2 = yes) under change control. Sharing is disabled. The confidential container has different owners from the operational site. | The site exists; external sharing is off; the owners lists are different |
| 2.2 | Set the site's regional time zone to the **business time zone** of the source **before** any date column is created. Date-only business columns hold a business calendar date (`docs/provisioning.md`, Business dates). The provisioning tool does **not** change regional settings. | Regional settings read back: the time zone equals the source; a UTC→local check of a known instant gives the expected date |
| 2.3 | Record the site URLs only in the confidential `<settings-file>`, never in the package | The package hard-code scan (§13, C-10) finds no URL |

---

## 3. Schema provisioning: PROVEN-OFFLINE (incremental apply PROVEN-LIVE)

Tool: `tools/provisioning/schema_reconcile.py`. It is a library with injected transport and holds no credentials or URLs. Rules: `docs/provisioning.md`.

| # | Action | Verification |
|---|---|---|
| 3.1 | Take a read-only inventory of `<target-site-url>` (`inventory()`). | Inventory JSON saved with a timestamp |
| 3.2 | Run `reconcile(target, inventory)` and **dry run** `apply(..., site_url=<target-site-url>, allowed_url=<target-site-url>, dry_run=True)`. `allowed_url` must be the **exact** target URL, never a pattern and never the source. | Findings: `CREATE` for every in-scope list and column; **0 `BLOCKED-INCOMPATIBLE`**; `GATED` / `DECISION-REQUIRED` only for objects that are deliberately out of scope. The plan is reviewed and signed. |
| 3.3 | Apply: the same call with `dry_run=False`. All lists are created before any column, so lookups find their targets. Internal names are fixed at creation. | `ApplyResult.executed` equals the reviewed plan (same operations, same order) |
| 3.4 | Take a fresh inventory and reconcile again. | Every in-scope object is `OK`; `CREATE` = 0; `BLOCKED` = 0 |
| 3.5 | **Second run is a no-op:** dry run again. | Plan is empty (0 operations) |
| 3.6 | If the run was interrupted, take a fresh inventory and run again from 3.2. The tool converges. | Same as 3.4 and 3.5 |
| 3.7 | Indexes and unique constraints are in place **before** any data load (list view threshold). | The inventory shows `Indexed` / `EnforceUniqueValues` as defined in the target schema |
| 3.8 | Views. **Not covered by the tool today.** The backlog package task names views. | **DESIGN gap.** Create views manually from the view definition, or extend the package. Check against the source view list. |

**Never:** run against the source site, a root site, or any URL other than the approved target. The tool never deletes, renames or retypes anything, and `EXTRA` objects are reported only.

**Abort point A1 (after 3.2):** `BLOCKED-INCOMPATIBLE` or an unexpected finding means stop and investigate. Nothing has been changed.
**Rollback after 3.3:** new lists and columns are REVERSIBLE while they are empty. Delete them manually in reverse order. Internal names stay consumed (`docs/provisioning.md`, rollback classes).

Evidence status: the empty-site rebuild is simulated offline (`test_ac1_rebuild.py` R01–R06, `test_schema_reconcile.py`). An **additive** apply has been run live on the build site. A **live empty-site rebuild has never been run.**

---

## 4. Groups and service identities: DESIGN (approval required)

### 4.1 Role groups

| # | Action | Verification |
|---|---|---|
| 4.1.1 | IT creates the role security groups **by the naming pattern** in `docs/role-model.md` (`SG-TS-*`, one group per role, 12 roles). In a tenant that hosts a staging copy as well, use the separate staging pattern (`SG-TS-STG-*`, proposed). Security groups are assigned (not dynamic), not role-assignable, and **start empty**. | Group count = number of roles; names match the pattern exactly; 0 members; owners recorded |
| 4.1.2 | Record the new group object IDs **only** in the confidential `<settings-file>` (`RoleGroupMap` environment variable: role key → group ID). | `RoleGroupMap` has exactly one entry per role; no ID appears in the package |
| 4.1.3 | Membership: HR owns business-role groups and IT owns administrative groups (`docs/role-model.md`). Membership is **re-established from an approved list**, never copied blindly from the source. Unresolved production identities get Employee rights only. | Membership list signed by HR/IT; group membership equals the signed list |
| 4.1.4 | Allow for propagation: SharePoint can take about 20–30 minutes to reflect a group change (`docs/runbook-identity-jml.md`). | Access checks in §13 are run from the user's own session after the propagation window |

### 4.2 Service identities

| # | Action | Verification |
|---|---|---|
| 4.2.1 | IT creates `<svc-operational>` from its **create plan**: cloud-only, non-personal, no admin role, **no group membership**, no mailbox use, standard licence, MFA method held by IT. Create `<svc-confidential>` and `<svc-bi>` only if they are in scope. The secret is never seen by the project or stored in any file. | Account enabled; 0 admin roles; 0 group memberships; 1 licence; owner and backup custodian recorded |
| 4.2.2 | Service identities are **not** employees and are never members of `SG-TS-*` groups. The guard rejects them as callers. | The identity resolver returns `NOT_REGISTERED` for the service UPN |
| 4.2.3 | Each identity has its own scope: operational, confidential and BI are separate accounts. | Each account's grants are limited to its own container (step 5) |

**Abort point A2:** if the approval or the create plan is missing, stop. Do **not** substitute a personal account, an administrator, or a test account from another environment.

---

## 5. List permissions: DESIGN (least privilege)

| # | Action | Verification |
|---|---|---|
| 5.1 | Create the custom permission levels: **Service** = View, Add, Edit items + Override List Behaviors; **no** Delete, Delete Versions, Manage Lists, Manage Permissions or Manage Web. Also create **Contribute without Delete** (`docs/architecture.md`). | The permission-level masks read back exactly; Delete is absent |
| 5.2 | Apply list-class permissions with the permission script (P proxy-only, W flow-write, M master data, I identity-bearing; `docs/architecture.md`). Grant the Service level to `<svc-operational>` only on the lists its flows write. **The service identity never holds Delete.** Business deletion is a soft delete. | For every list, the effective permissions of the service identity are View/Add/Edit = yes and Delete / ManageLists / ManagePermissions / ManageWeb = no |
| 5.3 | No human write permission on protected (class P) lists; no service grant on master-data lists until a guarded master-data flow exists. | A direct REST write by a test user returns 403 on protected lists |
| 5.4 | Check group-based access from the **user's own session** (`EffectiveBasePermissions`). The admin-side check is not authoritative for access through security groups (`docs/runbook-identity-jml.md`). | Recorded per role after the propagation window |

The permission script and the group and identity create plans are **not yet part of this package** (backlog package task).

---

## 6. Reference and seed data: PROVEN-OFFLINE

Tool: `tools/provisioning/reference_data.py` (`docs/provisioning.md`, Reference data).

| # | Action | Verification |
|---|---|---|
| 6.1 | For each small master list: `validate_seed(rows, rules, settings)`. An unresolved setting used by a rule **fails** the validation. | 0 seed problems |
| 6.2 | Dry run `apply_items(..., site_url=<target-site-url>, allowed_url=<target-site-url>, dry_run=True)`. The tool refuses unless the list schema reconciles `OK`. | Findings: `CREATE` only on an empty target; 0 `BLOCKED` (business-key clash) |
| 6.3 | `AppRoles` / `RolePermissions`: load **after** step 4. The documents differ on whether `AppRoles` rows carry group IDs (decision R-D5). If they do, the IDs come from the `<settings-file>` and never from the source. | `AppRoles` has one row per role; every group reference resolves to an existing target group |
| 6.4 | Apply (`dry_run=False`), then run the dry run again. | Second run: plan empty; every item `OK`. `DRIFT` is reported, never overwritten. `EXTRA` is never deleted. |

---

## 7. Environment configuration: PROVEN-OFFLINE

Tool: `tools/config/app_settings.py` (`docs/app-settings.md`).

| # | Action | Verification |
|---|---|---|
| 7.1 | `validate_registry(registry)` with the project registry. Secrets and tenant identifiers are refused. | 0 problems |
| 7.2 | Prepare a **target** environment overlay (per-environment JSON, confidential). Copy only the values that are valid for the target. Do **not** copy source-tenant values (UPNs, domains). | The overlay contains only keys marked `environmentSpecific`; a reviewer has signed it |
| 7.3 | `seed_rows(registry, overlay)` → load with `reference_data.apply_items` (key `Title`). **Unresolved settings get an empty value and stay unresolved.** `proposedDefault` is never applied. | `drift()` lists the unresolved keys. Every function gated on them refuses with `CONFIG_UNRESOLVED` (fail closed). |
| 7.4 | Settings changed by administrators in the source are **not** silently copied. Bring each one over through the overlay with its approval basis, or leave it unresolved. | The `drift()` report is reviewed: every difference from the source is explained |
| 7.5 | Audit retention keys: if they are missing, purge is disabled (`docs/audit-model.md`). | Retention status = `PENDING` or `CONFIGURED`, as decided |
| 7.6 | Site URLs, list IDs, group IDs and domains go **only** into solution environment variables (§9), never into AppSettings. | `validate_registry` and the hard-code scan are clean |

---

## 8. UPN mapping file: DESIGN (format defined; never applied)

Applies when R-D1 = tenant move, or whenever UPNs change.

| # | Action | Verification |
|---|---|---|
| 8.1 | HR/IT prepare `<upn-map>` (`upn-migration-map.csv`) with the columns `LegacyId`, `OldUpn`, `NewUpn`, `Source` (HR/IT), `ApprovedBy`, `ApprovedOn`. | The file has the required columns; every row has an approver and a date |
| 8.2 | **Never auto-map.** No rule such as "same local part, new domain" is applied. Every row is reviewed by a person. | The review record lists the reviewer; 0 rows are generated by a script without review |
| 8.3 | Validate: every `NewUpn` exists in the target directory, is enabled and is a member (not a guest); `NewUpn` is unique; the `<target-domain>` is in `AllowedDomains`; inactive employees are not mapped. | Validation report: 0 missing, 0 disabled, 0 guest, 0 duplicate, 0 inactive mapped |
| 8.4 | Rows that are **unmapped** stay unmapped: such an employee has no `AccountUpn` and resolves as `NOT_REGISTERED` (fail closed). They are reported as exceptions, never guessed (`identity_resolver.migrate_upn` returns nothing for an unknown UPN). | The exception list is signed by HR/IT |

**Abort point A3:** an unsigned map, or any validation failure, means stop before step 11.

---

## 9. Power Platform solution import: DESIGN (never run in a tenant)

| # | Action | Verification |
|---|---|---|
| 9.1 | Target environment `<target-pp-environment>` exists with a Dataverse database, the approved region and DLP (1.9). | Environment details recorded (confidential) |
| 9.2 | Fill a copy of the settings-file template with target values: site URLs, list IDs (captured after step 3), `RoleGroupMap` (step 4), `AllowedDomains` = `<target-domain>`, environment label, business time zone. Keep it confidential. | Every environment variable in the template has a value; none is copied from the source unless it is identical by design (for example the time zone) |
| 9.3 | Import the **managed** solution with the settings file. Never author in the target environment. | Import succeeds; the solution version equals the source; environment-variable current values equal the settings file |
| 9.4 | Hard-code check: the solution contains no URL, tenant domain, list GUID or group GUID (repeat the export scan on the same package). | Scan: 0 findings |

**Abort point A4:** if the import fails, remove the managed solution from the empty target environment. Data is not affected.

---

## 10. Connection references: DESIGN

| # | Action | Verification |
|---|---|---|
| 10.1 | The IT custodian signs in **interactively** as `<svc-operational>` in the target environment and creates its SharePoint, Office 365 Groups and Office 365 Users connections (standard connectors only). | Connections show Connected; owner = service identity; no Premium connector |
| 10.2 | Bind the service connection references to those connections. Keep **separate references** for the service and the invoker: the invoker's Office 365 Users reference is "provided by run-only user", because the trusted caller must come from the caller's own connection (`docs/architecture.md`, guard-flow contract). | Each connection reference points to a connection owned by the right identity; no personal connection is bound to a write path |
| 10.3 | Turn on the flows; set run-only users (the employee role group); share the app with the role groups. | Flows on; run-only users set; app shared with groups only |
| 10.4 | Guard smoke test (before any real data): a caller with a forged `CallerUpn` / `OwnerUpn` is ignored; an unregistered user is denied; a write is performed by the service connection and audited. | Audit row: actor = trusted caller; `Decision` as expected; correlation ID on item, audit row and flow run |

**Platform point to verify:** that a solution-aware flow keeps "provided by run-only user" and the caller stays trustworthy. This has been shown only for non-solution flows.

---

## 11. Data load and UPN rewrite: DESIGN

The migration loader and reconciliation scripts are **not yet target-configurable** (backlog task). Rules from the project documents:

### 11.1 Load rules

- Load in dependency order: masters → employees → projects → project children → confidential finance → timesheets → KPI → approvals → history/archive → reconciliation.
- Upsert by business key (`LegacyId`, codes). Stamp a `MigrationBatch`. Never delete during a load step. Indexes exist before loading.
- Honour throttling (HTTP 429 `Retry-After`); use bounded batches.

### 11.2 Item-ID references

SharePoint item IDs are **assigned by the target** and are not preserved. Every column that stores an item ID of another list (`EmployeeItemId`, `OwnerEmployeeItemId`, `ProjectItemId`, `TargetItemId`, lookups) must be **re-keyed** through the business key (`LegacyId` / code) of the referenced row in the target. Never copy the numeric value from the source.
Verification: for a sample and for the full set, every re-keyed reference resolves to a target row with the same business key as in the source.

> The documents call `EmployeeItemId` both environment-specific and unchanged in a restore. See the README notes. Until that is resolved, treat `LegacyId` as the portable key and `EmployeeItemId` as re-derived.

### 11.3 UPN rewrite (only with the reviewed `<upn-map>`)

| Column | Rule | Status |
|---|---|---|
| `Employees.AccountUpn` | Set from `NewUpn` by the guarded mapping load, for approved rows only. Unmapped, inactive and conflict rows get **no** UPN. Stored normalised (lower-case). Indexed and unique. | DESIGN (documented) |
| Person columns (e.g. `EmployeeAccount`) | Re-resolved in the target from `NewUpn`. Display only, never an authorisation key. | DESIGN (documented) |
| `OwnerUpn` (business-owner key on timesheet rows, `docs/architecture.md` AD-4) | **DECISION R-D4.** Not documented. If rewritten: only through the `<upn-map>` keyed by the owner's `LegacyId`; rows whose owner is unmapped keep the old value and are reported. They then cannot be read by that owner until the mapping is fixed (fail closed). | DECISION |
| Configuration values of type `upn` in AppSettings | Never copied. Re-entered through the target overlay (§7). | DESIGN |

### 11.4 Audit rows

**DECISION R-D3.** The audit model (`docs/audit-model.md`) defines `ActorUpn` as the trusted identity at the time of the event. It does **not** define what happens to historical audit rows in a restore or tenant move. Options to decide: (a) keep historical `ActorUpn` values unchanged as evidence, and link them to the person through `ActorEmployeeItemId` (re-keyed per §11.2) and the `<upn-map>`; (b) add the new UPN in a separate column; (c) rewrite. Until this is decided, the audit lists are loaded **without** changing `ActorUpn`, and no option is assumed.

New audit rows written in the target carry the target `Environment` label.

**Abort point A5:** if a load step fails its per-step check, stop. The load is idempotent: fix the cause and re-run the step. The source stays authoritative until cutover.

---

## 12. Data reconciliation: DESIGN

Run after the load (and after any delta). Every check compares the source export with the target.

| # | Check | Pass criterion |
|---|---|---|
| 12.1 | Row count per list | Target = source (or source minus a signed, listed exception) |
| 12.2 | Business-key set per list (`LegacyId` / code) | Identical key sets; 0 duplicates in the target |
| 12.3 | Lookups and re-keyed item-ID references | 0 dangling; each resolves to the same business key as in the source |
| 12.4 | Sums of business measures (hours, weighted hours) overall, per employee-month and per project | Equal to the source |
| 12.5 | Approval and lock states | Count of approved/locked rows equals the source |
| 12.6 | Identity | `AccountUpn` count = approved map rows; 0 duplicates; 0 inactive rows with a UPN; unmapped list = the signed exception list |
| 12.7 | Configuration | `drift()` report matches the expected unresolved list; seeds reconcile `OK` |
| 12.8 | Schema | Schema reconcile of target vs definition = `OK`; schema diff source vs target = 0 unexplained |
| 12.9 | File and attachment hashes (archive libraries, if in scope) | Hashes equal |

Acceptance (backlog): reconciliation = **0 differences**, or signed exceptions.

---

## 13. Cutover validation checklist: DESIGN

| ID | Check | Evidence |
|---|---|---|
| C-1 | Steps 1–12 complete; every verification recorded | Run log |
| C-2 | Second schema run and second seed run planned nothing | Dry-run outputs |
| C-3 | Service identity effective permissions: no Delete / Manage Lists / Manage Permissions / Manage Web on any list | Per-list effective-permission export |
| C-4 | Group-based access per role, checked from each test user's own session after the propagation window | Test log per role |
| C-5 | App start (AppOpen): a mapped user gets Home and an `AppOpen / ALLOW` audit row; an unmapped user gets the not-registered screen and `IdentityRejected` | Audit rows |
| C-6 | Guarded save and guarded read of own rows; a foreign owner is refused; an approved row is `LOCKED` | Flow responses and audit rows |
| C-7 | A gated feature whose setting is unresolved refuses (`CONFIG_UNRESOLVED`) | Flow response |
| C-8 | Correlation ID is the same on the item, the audit row and the flow run | Sample |
| C-9 | Reconciliation (§12) = 0 differences or signed exceptions | Signed report |
| C-10 | No tenant-specific literal in the package or the unpacked solution | Scan output |
| C-11 | Go/no-go decision recorded; users admitted only after C-1…C-10 pass | Decision record |

---

## 14. What is not yet proven

| Item | Status |
|---|---|
| Live rebuild of the schema into an **empty** site | **Not run.** Offline simulation only (`test_ac1_rebuild.py`). An additive live apply on an existing site has been done. |
| Views and folders in the provisioning definition | Not covered by the tool |
| Permission script, group and identity create plans, settings-file template in this package | **Not yet in the package** |
| Power Platform solution export or import (managed or unmanaged) | **Never run in any tenant.** The guard flows so far were built as non-solution flows. |
| "Provided by run-only user" in a solution-aware flow | Not verified |
| Connection re-authentication after a service credential rotation | Not tested |
| Target-configurable migration loader and reconciliation scripts | Not built |
| UPN remap (`<upn-map>`) applied to real data | Format defined; `migrate_upn` tested offline only |
| `OwnerUpn` rewrite rule, audit `ActorUpn` rule | **Open decisions** (R-D4, R-D3) |
| Restore rehearsal into an empty staging-class site with reconciliation evidence | Planned (backlog), not done |
| Platform backup/restore of a single list | Not done |

---

## 15. Rollback and abort points (summary)

The restore writes only into an **empty target**. The source is frozen and is never modified by this runbook, so the safest rollback is always to **abandon the target** and continue on the source.

| Point | When | Action | Rollback class |
|---|---|---|---|
| A0 | Before step 2 | Decisions open: stop | Nothing to undo |
| A1 | After schema dry run (3.2) | Blocked or unexpected findings: stop | Nothing to undo |
| – | After schema apply (3.3) | Delete the new (empty) lists and columns manually | REVERSIBLE while empty; internal names stay consumed |
| A2 | Before groups/identities | No approval or create plan: stop | Nothing to undo |
| – | After step 4 | Disable or delete the new groups and identities through IT change control | IT-reversible |
| A3 | Before data load | UPN map unsigned or invalid: stop | Nothing to undo |
| A4 | Solution import fails | Remove the managed solution from the target environment | Reversible; no data involved |
| A5 | During data load | Stop; fix; re-run the idempotent step | Loaded rows stay; re-run upserts by business key |
| A6 | Reconciliation fails | Do not admit users; fix and reconcile again, or abandon the target | Target abandoned; source remains authoritative |
| A7 | After go-live | No reverse sync exists. Rolling back means returning to the frozen source and losing target-side changes made after cutover. This must be agreed at go/no-go. | DECISION at go/no-go |

SharePoint has no transactional schema rollback. Retype, rename and delete are never performed by the tools and are manual, NOT-AUTO-REVERSIBLE operations.
