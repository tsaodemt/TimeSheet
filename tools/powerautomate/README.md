# Power Automate guard-flow tooling

| Script | Purpose |
|---|---|
| `build_guard_flow.py` | Defines the guarded write flow (trusted caller, live group check, owner resolution, lock, audit) and writes `definition.json` plus a legacy import package |
| `make_designer_paste_build.py` | Generates a Playwright script that builds the flow in the classic designer through clipboard paste (used where legacy package import is unavailable) |

Configuration comes from environment variables. Nothing tenant-specific is stored in the source.

| Variable | Meaning |
|---|---|
| `TS_SITE_URL` | `https://<tenant>.sharepoint.com/sites/<staging-site>` |
| `TS_REVIEWER_GROUP_ID` | Object ID of the reviewer security group |
| `TS_PP_ENVIRONMENT` | Power Platform environment ID |
| `TS_CONN_SHAREPOINT`, `TS_CONN_O365USERS`, `TS_CONN_O365GROUPS` | Connection IDs owned by `<service-account>` |
| `TS_BUILD_SCRIPT_OUT` | Output path of the generated designer script (do not commit) |

Known classic-designer limitation: pasted expressions lose `coalesce(x, '<string>')` and empty string literals. The generator rewrites them as `if(empty(x), substring('x', 0, 0), x)`, which has the same meaning.
