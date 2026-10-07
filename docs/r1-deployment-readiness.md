# R1 flow set — dependencies and deployment readiness

The R1 flow set is three offline templates. None is deployed.

| Flow | Alias | Template |
|---|---|---|
| `TS-AppOpen` | AppStart | `tools/powerautomate/build_appstart_flow.py` `appstart_actions` |
| `TS-ReadOwn` | ReadOwn | `tools/powerautomate/build_r1_flows.py` `read_own_actions` |
| `TS-SaveEntry` | SaveEntry | `tools/powerautomate/build_r1_flows.py` `save_draft_actions` |

The manifest `flows` section is **generated from the templates** (`tools/alm/r1_flows.py`). Each dependency is read from the generated actions: connection references, lists with their HTTP methods, AppSettings keys, guard capability, identity lookup and audit events. So the manifest cannot list a dependency a flow does not use. `sample_manifest()` gives the publishable placeholder version; the environment-local manifest with real values is never committed.

## Connection references

| Reference | Ownership | Purpose | Used by |
|---|---|---|---|
| `<PFX>_CR_O365Users_Invoker` | INVOKER (run-only user's own connection) | trusted caller identity (Get my profile V2) | AppStart, ReadOwn, SaveEntry |
| `<PFX>_CR_SharePoint_OpsService` | SERVICE (D-3) | service-side SharePoint reads and writes | AppStart, ReadOwn, SaveEntry |
| `<PFX>_CR_O365Groups_OpsService` | SERVICE (D-3) | live role-group membership in the guard | ReadOwn, SaveEntry (AppStart grants nothing and checks no groups) |

The INVOKER reference is never reported as missing service ownership. SERVICE references block readiness until D-3 is resolved and they are owned by the configured service identity. No account or UPN appears in code or in the public manifest.

## Dependencies (from the generated templates)

| | AppStart | ReadOwn | SaveEntry |
|---|---|---|---|
| Identity resolution (Employees by `AccountUpn`) | yes | yes | yes |
| Guard capability | — (AppOpen grants nothing) | `TS.ViewOwn`, self | `TS.EditOwnDraft`, self |
| Lists read | Employees, AppSettings | Employees, AppSettings, TimesheetEntries | Employees, AppSettings, TimesheetEntries, Projects, ProjectPhases, Phases, WorkTypes, Shifts, HourTypes; ProjectAssignments only when `ProjectAssignmentScoping = On` |
| Lists written | AuditLog | AuditLog | TimesheetEntries (create / MERGE, no delete), AuditLog |
| AppSettings | keys with `exposeToClient` (client subset only) | `BusinessTimezone` (no fixed UTC offset) | `PayPeriodStartDay`, `MaxHoursPerEntryWarn`, `MaxHoursPerDayWarn`, `ProjectAssignmentScoping`, `BusinessTimezone` |
| Audit events | AppOpen / IdentityRejected | AuthorizationAllow / AuthorizationDeny + ReadProxy | AuthorizationAllow / AuthorizationDeny + WriteProxy |
| Environment variables | `OpsSiteUrl`, `AllowedDomains`, `EnvironmentLabel`, list bindings | + `RoleGroupMap` | + `RoleGroupMap`, master-list bindings |
| Date semantics | — | half-open UTC interval from `BusinessTimezone` (proven live by POC P4) | same-day sum on the business day |

## Readiness

`tools/alm/r1_readiness.py` reports readiness per purpose and per flow. Each blocker names a category:

| Category | Meaning |
|---|---|
| `PUBLISHER_PREFIX_UNRESOLVED` | `<PFX>` is still in a schema name; the publisher prefix is not decided (ENV-D3) |
| `ENVIRONMENT_UNRESOLVED` | an ENV-D3 environment decision (type, region, admins/makers, DLP, publisher, prefix, hosting) or a used environment variable has no value |
| `D3_SERVICE_IDENTITY_MISSING` | no approved operational service identity is configured, or a temporary one is (never a substitute) |
| `CONNECTION_REFERENCE_UNBOUND` | a used SERVICE reference is gated, unowned or owned by another account; or a used reference is undeclared |
| `PERMISSION_NOT_VERIFIED`, `READ_PERMISSION_MISSING`, `WRITE_PERMISSION_MISSING`, `SECURITY_DRIFT` | exact service rights per list: Read on read lists; `TS Service` (no delete) on written lists; nothing broader |
| `TARGET_LIST_MISSING` | an operational list a flow uses does not exist |
| `REFERENCE_DATA_MISSING` | a reference list has no canonical business rows. **A list that exists is not ready.** |
| `AUDIT_DEPENDENCY_UNAVAILABLE` | the audit list a flow writes is not live (S05.5). The audit requirement is never weakened to pass readiness. |
| `INTERIM_CONFIG_NOT_UAT_READY` / `INTERIM_CONFIG_NOT_PRODUCTION_READY` | an interim engineering value is in use |
| `CONFIG_NOT_READY` | any other AppSettings readiness failure |

What each purpose accepts:
- **ENGINEERING** accepts owner-approved interim values in their allowed environment. B-03 `ProjectAssignmentScoping = Off` is a STAGING-only engineering interim, so it passes that check.
- **UAT** and **PRODUCTION** refuse interim values.

Notices do not block:
- `FIRST_LIVE_CHECK_PENDING` (`r1-first-live-checks.md`);
- `CREATE_IDEMPOTENCY_INTERIM`.

## Create idempotency (R1-Q3 open)

Create idempotency is **INTERIM / NOT GUARANTEED**. There is no RequestKey, and the generator accepts only `idempotency="none"`.

Current engineering mitigation:
- the app disables Save while a call is in flight;
- `WARN_DUPLICATE` makes a repeated create visible.

Exactly-once creation is not claimed.

## D-3 — when the operational service identity exists

1. Set the `ServiceAccountUpn` environment binding. It comes from environment configuration only, never a literal and never a temporary/test account.
2. Bind the SERVICE-owned connection references to that identity.
3. Apply the Phase 2 Read grants (`tools/provisioning/permission_plan.py` `service_read_plan`), plus `TS Service` on the written lists.
4. Verify the exact permissions: a snapshot per used list, with no drift.
5. Rerun ENGINEERING readiness.

## ENV-D3 — still unresolved

Environment type, region, admins/makers, DLP, publisher, prefix and Teams/browser hosting are all undecided. The prefix stays `<PFX>`, and readiness fails with `PUBLISHER_PREFIX_UNRESOLVED` / `ENVIRONMENT_UNRESOLVED` until they are decided.

Tests:
- `tools/alm/test_r1_readiness.py` RA01–RA14;
- `tools/alm/test_manifest_check.py` (flows-section lint).
