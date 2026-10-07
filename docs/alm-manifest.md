# Solution deployment manifest and readiness check

The Power Platform solution moves between environments (and tenants) by changing environment-variable values and connection-reference owners only (AD-8). A deployment manifest lists every environment variable and connection reference with:
- schema name (`<prefix>_Name`; the publisher prefix is a pending decision, written `<PFX>` until then);
- purpose and the decision that defines it;
- whether release 1 needs it;
- whether it is gated (and by which decision);
- one value per environment.

`tools/alm/manifest_check.py`:
- `lint(manifest, publishable=True)` — a manifest kept in source control holds placeholders (`<...>`) only: no URLs with real hosts, GUIDs or e-mail addresses; schema names unique; secrets are never environment variables; every connection reference has a service-identity owner.
- `readiness(manifest, env, scope="r1")` — fails closed: the deployment is ready only when every in-scope variable has a real value for that environment, no in-scope item is gated, and the publisher prefix is decided. The result lists each blocker with its reason.

The environment-local manifest with real values is never committed.

Tests: `tools/alm/test_manifest_check.py` M01–M07.

A manifest may also carry a `flows` section. `lint` then checks that every connection reference and environment variable a flow uses is declared, and that each reference's ownership (`INVOKER`, `SERVICE`, `APP_USER`) matches. The R1 flow set, its generated dependencies and the categorised R1 readiness check are described in `r1-deployment-readiness.md`.

## Readiness after the service-identity decision

`tools/alm/d3_readiness.py` refuses a deployment for a purpose (ENGINEERING, UAT, PRODUCTION) when the approved service identity is not configured for the environment (or is a temporary/test account), a required connection reference is missing, gated or owned by another account (references "provided by run-only user" are exempt by design), the service identity lacks Read — or holds more than Read — on a required list, an environment binding is unresolved, or configuration readiness fails (interim values are refused for UAT and PRODUCTION). It also refuses while the configured identity misses a D-3 acceptance criterion (`tools/alm/d3_acceptance.py`; each criterion needs recorded evidence, and the blocker names it). The identity comes only from environment configuration; no account is hard-coded. Tests: `tools/alm/test_d3_readiness.py` DR01–DR12.

## Deployment target guard (staging / demo)

`tools/alm/deployment_target_guard.py` refuses a deployment or readiness claim unless the selected Power Platform
environment is exactly the approved dedicated staging environment (type Sandbox; never Default, Production, Developer,
Teams or Trial), the publisher prefix is the approved staging prefix, the environment label variable equals the approved
label (never PRODUCTION), every site-URL variable equals the approved staging site URL by exact string equality, and no
variable value is a GUID. The approved values live in private configuration. Tests: `test_manifest_check.py` DG01–DG05.

Creating a Sandbox with Dataverse needs available Dataverse database capacity (at least 1 GB) or a pay-as-you-go
billing plan. A tenant with only Microsoft 365 licences has none; that is a capacity/billing decision, not something
to work around with the Default environment.
