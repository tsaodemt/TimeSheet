# restore/: tenant portability and restore package

This is the package for rebuilding the Timesheet system in an empty site and environment, in the same tenant or in another one. **Status: DRAFT. The design is documented, but the full procedure has never been executed.**

| File | Content | Status |
|---|---|---|
| `RESTORE-RUNBOOK.md` | Ordered rebuild steps, each with a verification check, plus abort and rollback points and a list of what is not proven | DRAFT (design) |

## Reused tools (outside this folder)

| Tool | Used in runbook step | Evidence |
|---|---|---|
| `tools/provisioning/schema_reconcile.py` | 3 Schema | Offline tests; additive live apply on the build site; **no live empty-site rebuild** |
| `tools/provisioning/reference_data.py` | 6 Reference data, 7 AppSettings rows | Offline tests |
| `tools/config/app_settings.py` | 7 Environment configuration | Offline tests |
| `tools/identity/identity_resolver.py` (`migrate_upn`) | 8 / 11 UPN mapping | Offline tests |

## Still missing from the package

- Provisioning definition for views (and folders)
- Permission script (custom levels and list-class grants)
- Create plans for the Entra role groups and service identities
- Settings-file template (environment-variable keys and connection-reference names, no values)
- Target-configurable migration loader and reconciliation scripts
- Hard-code scan of the package and the solution (to run in CI)

## Rules for this folder

This repository is public. Nothing here may contain tenant names, domains, site URLs, UPNs, tenant, object, list or group IDs, connection IDs, or customer data. Values are supplied at run time from confidential per-environment files, using the placeholders listed in the runbook.

## Open points before the package can be finalised

- **`EmployeeItemId`:** `docs/identity-resolution.md` calls it environment-specific, but the portability requirement treats it as unchanged. The runbook re-keys it through `LegacyId` (§11.2).
- **`OwnerUpn` and audit `ActorUpn`:** no rewrite rule is documented for these columns in a tenant move (runbook R-D3, R-D4).
- **Role-group IDs:** they should live in solution environment variables, and the documents differ on whether `AppRoles` also stores them (R-D5).
- **Rebuild order:** the runbook creates groups before permissions. The planned order lists permissions first.
