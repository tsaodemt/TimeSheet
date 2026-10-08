# R1 deployment package (offline; NOT deployed)

Status: **READY offline** — live deployment **BLOCKED_BY_TENANT_CAPACITY** (no dedicated Power Platform STAGING
environment). Never Default, Production, Trial, Developer or Teams environments; no PAYG; no Dataverse.

## Artifacts

| Artifact | Source | Notes |
|---|---|---|
| TS-AppOpen (AppStart) actions | `tools/powerautomate/build_appstart_flow.py` | Power Apps V2 trigger; `Respond` / `Respond_error` |
| TS-ReadOwn actions | `tools/powerautomate/build_r1_flows.py` `read_own_actions` | |
| TS-SaveEntry actions | `tools/powerautomate/build_r1_flows.py` `save_draft_actions` | `idempotency="none"` only (R1 non-idempotent) |
| Canvas app source | `tools/powerapp/demo-r1/*.pa.yaml`, `messages.json` | calls the three flows only; no direct list writes |
| Flow manifest | `tools/alm/r1_flows.py` (generated from the templates) | dependencies, connection references, settings, audit events |
| SharePoint-only STAGING pack | `tools/alm/sharepoint_only_pack.py` `build(config, out_dir)` | binds the approved STAGING site from PRIVATE config; refuses any other site or a PRODUCTION label; writes `PACK-MANIFEST.json` (sha256 per flow) and a deployment checklist. The built pack (tenant values) stays in the private working area. |
| Readiness gate | `tools/alm/r1_readiness.py`, `tools/alm/test_r1_release_readiness.py` | blockers vs notices |

## Connections

| Reference | Owner | Use |
|---|---|---|
| `<PFX>_CR_O365Users_Invoker` | run-only user's own connection | trusted caller identity (MyProfile_V2) in all three flows |
| `<PFX>_CR_SharePoint_OpsService` | operational service identity | every SharePoint read / write |
| `<PFX>_CR_O365Groups_OpsService` | operational service identity | live role-group membership (ReadOwn, SaveEntry) |

## Configuration

Environment-specific values come from configuration, never source: site URL (exact STAGING site), tenant domain,
role-group object ids, environment label, service identity. Business settings stay in SharePoint `AppSettings`
(read by the service at run time; client subset exposed by AppStart). Interim settings are STAGING/engineering only.

## STAGING deployment checklist (when an environment exists)

1. Confirm the environment picker shows only the dedicated STAGING environment (`architecture_scope.check_environment`).
2. Rebuild the private pack (`make_pack`); verify `sitesReferenced` = the STAGING site only and the flow hashes.
3. Create the SharePoint and Office 365 Groups connections as the service identity; Users = provided by run-only user.
4. Create the three flows (Power Apps V2 trigger) from the actions files; check `Site_guard`, no Dataverse action.
5. Share run-only with the STAGING employee group; import the Canvas source; add the flows; publish; share with the
   demo identity only.
6. Run the first-live checks (`docs/r1-first-live-checks.md`, incl. V-ERROR-RESPONDER), then the live test plan.

## Post-deployment smoke test

AppStart OK for the demo identity; ReadOwn of the current pay period returns only own rows; one SaveEntry create and
one edit with the returned ETag; one stale-ETag edit returns `CONFLICT`; AuditLog has the matching rows with one
correlation id per call.

## Rollback

Turn off and delete the three flows; delete the Canvas app; remove run-only sharing; delete the connections; delete
DEMO_ONLY / smoke-test TimesheetEntries rows by id (recorded during the run). SharePoint schema and permissions are not
changed by deployment.

Known limitations: `docs/r1-known-limitations.md`. Status: `docs/r1-status.md`.
