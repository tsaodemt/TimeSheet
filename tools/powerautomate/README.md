# Power Automate guard-flow tooling

| Script | Purpose |
|---|---|
| `build_guard_flow.py` | Defines the guarded write flow (trusted caller, live group check, owner resolution, lock, audit) and writes `definition.json` plus a legacy import package |
| `make_designer_paste_build.py` | Generates a Playwright script that builds the flow in the classic designer through clipboard paste (used where legacy package import is unavailable) |
| `build_read_flow.py` | Defines the guarded read flow (trusted caller, live reviewer check, owner filter, indexed server-side query, keyset paging, leak check, audit) |
| `make_read_designer_build.py` | Generates a Playwright script that builds the read flow in the classic designer |
| `make_read_guard_repaste.py` | Generates a Playwright script that replaces the `Guard` scope in an existing flow (any flow module via `TS_FLOW_MODULE`) |
| `build_identity_flow.py` | Defines the identity-resolution guard flow (trusted caller → normalised UPN → indexed, unique `AccountUpn` lookup → OK / NOT_REGISTERED / INACTIVE / DUPLICATE_MAPPING / INVALID_IDENTITY; live role-group check; audit). Build it with `make_read_designer_build.py` and `TS_FLOW_MODULE=build_identity_flow`. |
| `guard_template.py` | **Reusable authorization guard**: generates the `Guard` scope every guarded flow embeds (trusted caller → employee → live role groups → scope → `Guard_result` + audit). See `docs/authorization-guard.md`. |
| `build_guard_template_flow.py` | Test harness flow consisting only of the guard template. Build with `make_read_designer_build.py` and `TS_FLOW_MODULE=build_guard_template_flow`. |
| `date_range.py` | WDL expression for a business-date range on a date-only column: half-open UTC interval [local from 00:00, local to+1 00:00); the Windows zone id is derived from the configured IANA zone. Used by `build_read_flow.py`; tested against `tools/timesheet/business_dates.py` (`tools/timesheet/test_date_range.py`). |
| `wdl_sim.py` | Offline interpreter for the expression subset the guard uses (plus `formatDateTime`, `addDays`, `convertToUtc` for date ranges). `tools/identity/test_guard.py` uses it to run the generated template against the reference. |
| `build_r1_flows.py` | **R1 flow templates (offline; not deployed)**: `read_own_actions` (TS-ReadOwn: own entries, both-or-neither business-date range, keyset paging, leak re-check, `ReadProxy` audit) and `save_draft_actions` (TS-SaveEntry: create / edit own draft only; edit checks with ETag, lookups fail closed, hours/date validation, non-blocking warnings, JSON item POST / MERGE with `IF-MATCH`, `AuthorizationAllow`/`Deny` + `WriteProxy` audit). Connections are connection-reference placeholders only. Create idempotency is an open decision: only `idempotency="none"` can be generated; UAT/PRODUCTION builds refuse interim settings. Parity tests against `tools/timesheet/entries.py`: `tools/timesheet/test_r1_read_flow.py` (RR01–RR22), `test_r1_save_flow.py` (RS01–RS25). |
| `build_role_probe_flow.py` | Defines a role/scope probe flow: live membership of every configured role group → roles → scope table → allow/deny per probe (action × target), with audit. Used to test the role model one temporary membership at a time. |

Configuration comes from environment variables. Nothing tenant-specific is stored in the source.

| Variable | Meaning |
|---|---|
| `TS_SITE_URL` | `https://<tenant>.sharepoint.com/sites/<staging-site>` |
| `TS_REVIEWER_GROUP_ID` | Object ID of the reviewer security group |
| `TS_PP_ENVIRONMENT` | Power Platform environment ID |
| `TS_CONN_SHAREPOINT`, `TS_CONN_O365USERS`, `TS_CONN_O365GROUPS` | Connection IDs owned by `<service-account>` |
| `TS_LIST`, `TS_AUDIT_LIST` | Protected list and audit list titles |
| `TS_BUSINESS_TIMEZONE` | IANA name of the business time zone (read-flow date range); the UTC offset and the Windows id are derived |
| `TS_FLOW_MODULE`, `TS_FLOW_NAME` | Flow definition module and display name for the designer build |
| `TS_ROLE_GROUPS`, `TS_SCOPE_CONFIG`, `TS_PROBE_ACTIONS` | Role probe: JSON list of [roleKey, groupId], scope-table file, probed actions |
| `TS_ALLOWED_DOMAIN`, `TS_ROLE_GROUP_ID`, `TS_ROLE_KEY`, `TS_EMP_LIST` | Identity flow: accepted tenant domain, role group, role key, employee list |
| `TS_FLOW_ID` (or `TS_READ_FLOW_ID`) | Existing flow ID for `make_read_guard_repaste.py` (re-paste only; module from `TS_FLOW_MODULE`) |
| `TS_REQUIRED_INPUTS` | Number of leading trigger inputs left required by the designer build (default 3) |
| `TS_BUILD_SCRIPT_OUT` | Output path of the generated designer script (do not commit) |

Known classic-designer limitation: pasted expressions lose `coalesce(x, '<string>')` and empty string literals. The generator rewrites them as `if(empty(x), substring('x', 0, 0), x)`, which has the same meaning.
