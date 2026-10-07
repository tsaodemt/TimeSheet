# R1 customer demo (demo-first mode)

Goal: a customer can click through R1 on the staging site. **Demo ready ≠ UAT ready ≠ production ready.** Production and
UAT governance items stay open in the backlog and never block the demo; nothing is marked done because of the demo.

## Definition of done (demo)
The app opens in the browser → Entra sign-in → the caller resolves to one active employee → the own list for the
current pay period (bounded) → New entry (WorkDate, Project, Phase, WorkType, Shift, HourType, Hours) → Save → Draft
appears → edit own Draft with ETag concurrency → validation blocks, warnings (> 4 h / entry, > 12 h / day) do not →
another owner's rows can never be read or changed → the app never writes lists directly.

## Pieces
| Piece | Source | Status |
|---|---|---|
| Flows TS-AppOpen / TS-ReadOwn / TS-SaveEntry | `tools/powerautomate/build_r1_flows.py`, `build_appstart_flow.py` | offline ready, tested |
| Canvas app (4 screens: startup, access denied / config error, my timesheet, entry) | `tools/powerapp/build_demo_app.py` → `demo-r1/*.pa.yaml` (Power Apps YAML, paste into Studio code view) | offline ready, tested (DA01–DA12) |
| Message texts | `demo-r1/messages.json` | **PROVISIONAL DEMO WORDING** keyed by messageCode (R1-Q4 open) |
| DEMO_ONLY reference / project / employee rows | `tools/demo/demo_data.py` | synthetic, marked `MigrationBatch = DEMO_ONLY`; not customer master data, not migration data (DD01–DD04) |
| Demo readiness | `tools/alm/demo_readiness.py` | separate from UAT / production readiness (DM01–DM04) |

App rules: the list always calls TS-ReadOwn with the current pay period (from `PayPeriodStartDay` in the AppOpen client
config); RequestedOwner is never sent; Save is disabled while a request runs; `AUDIT_DEGRADED` is a success with a warning
(never save again); `CONFLICT` and a missing ETag force a re-read; only reference lists are data sources (read-only),
never TimesheetEntries, AuditLog, Employees or AppSettings; no URL, account or GUID in the source.

## Demo smoke tests (separate from R1-01..R1-15)
| ID | Check |
|---|---|
| DEMO-01 | app opens |
| DEMO-02 | the demo user resolves to its employee |
| DEMO-03 | the current pay-period list loads |
| DEMO-04 | create a Draft |
| DEMO-05 | the new Draft appears in the list |
| DEMO-06 | edit own Draft (ETag) |
| DEMO-07 | Hours ≤ 0 is blocked |
| DEMO-08 | > 4 h shows a warning, Save still works |
| DEMO-09 | another owner's row cannot be read or changed |
| DEMO-10 | audit / correlation evidence exists, or AUDIT_DEGRADED behaves as specified |

The formal live acceptance suite R1-01..R1-15 is separate and still has to run.
