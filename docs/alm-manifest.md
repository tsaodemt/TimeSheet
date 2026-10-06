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
