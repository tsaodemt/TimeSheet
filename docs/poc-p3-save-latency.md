# POC P3 — R1 save latency (procedure)

Status: **PROCEDURE READY / NOT EXECUTED.** Running it needs its own live approval. Machine-checkable version: `tools/timesheet/poc_procedures.py` (`P3`), checked by `test_poc_procedures.py`.

## Purpose and acceptance

Measure the latency of an R1 save through the real path: the test screen calls `TS-SaveEntry`, which runs the guard, identity resolution, settings, lookups, the write and the audit rows, then responds.

- Acceptance: end-to-end save **p95 ≤ 5 s** (IMPLEMENTATION-SPEC NFR-PERF-03; gate G4). This threshold already exists in the specification; P3 does not set a new one.
- Reported per scenario: n, min, median, p90, p95, max.

## Blocked until

- `TS-SaveEntry` is deployed legitimately in STAGING. This needs:
  - the D-3 operational service identity;
  - the ENV-D3 decisions;
  - bound connection references.
- `TimesheetEntries` (S06.1) and `AuditLog` (S05.5) are live.
- The S04.3 reference lists hold canonical rows.
- An approved R1 test identity with an Employees row exists. P3 creates no users, and the service identity is never substituted.

## Measurements

| Id | What | How |
|---|---|---|
| E2E | client trigger → response | timestamps (ms) around the flow call on a test screen, plus Power Apps Monitor |
| GUARD | guard and identity overhead | run-history action timings, from the trigger start to `Guard_result` |
| WRITE | SharePoint write | run-history timing of `Create` or `Update` + `Get_new` |
| AUDIT | audit rows | run-history timing of `Write_audit`, `Write_Authz_audit`, `Write_Write_proxy` |

## Scenarios

| Id | Kind | Runs | Rows written |
|---|---|---|---|
| P3-C | create (warm) | 30 | 30 |
| P3-E | edit (warm; the rows from P3-C) | 30 | 0 new |
| P3-K | conflict (stale ETag → `CONFLICT`) | 10 | 0 |
| P3-V | validation rejection (Hours = 0) | 10 | 0 |
| P3-F | cold: first call after ≥ 30 min without runs; separate idle windows; reported apart from warm runs | 5 | 5 |
| P3-D | double tap: Save is disabled while a call is in flight (interim R1-Q3 mitigation); expect one row per tap pair | 5 | 5 |

30 warm runs give a p95 (nearest rank) without becoming a load test. Each scenario runs at most 50 times.

## Data and safety

- STAGING only; MAIN stays read-only.
- Synthetic data only. Every row carries the tag `SYNTH-POC-P3-<yyyymmdd>`, and its correlation ID is captured.
- Cleanup: a site administrator recycles each tagged entry after re-reading its tag and synthetic marker. The service identity never holds Delete. Verify that 0 tagged rows remain.
- Audit rows are kept as evidence. The synthetic tag is in their Detail.
