"""POC P3 (save latency) and P5 (choice-column filtering) live procedures as checkable data (generic; no tenant data).

Both are PROCEDURE READY / NOT EXECUTED. Each needs its own live approval. validate(spec) checks the safety and
completeness rules every live POC here follows (STAGING only, synthetic tagged data, exact cleanup, no invented
acceptance threshold, bounded workload, no service-identity substitution). Human-readable versions:
docs/poc-p3-save-latency.md, docs/poc-p5-choice-filtering.md. Tenant-specific values live in the local evidence area.
"""
from __future__ import annotations

STATUS = "PROCEDURE READY / NOT EXECUTED"
MAX_REPETITIONS = 50          # per scenario: enough for a percentile, not a load test
MAX_NEW_SYNTHETIC_ROWS = 20   # P5 reuses the existing >5,000-row dataset; new rows only for missing statuses

P3 = {
    "id": "P3", "title": "R1 save latency through the guarded service flow",
    "status": STATUS, "executed": False, "approvalRequired": True,
    "source": ["IMPLEMENTATION-SPEC NFR-PERF-03 (save through guard flow <= 5 s p95, POC P3)", "backlog T06.11.3", "gate G4"],
    "acceptance": {"metric": "end-to-end save p95", "threshold": "<= 5 s", "thresholdSource": "NFR-PERF-03",
                   "report": ["min", "median", "p90", "p95", "max", "n"]},
    "environment": "STAGING", "mainAllowed": False,
    "blockedBy": ["TS-SaveEntry deployed legitimately in STAGING (D-3 service identity, ENV-D3, connection references bound)",
                  "TimesheetEntries (S06.1) and AuditLog (S05.5) live", "S04.3 reference lists hold canonical rows",
                  "an approved R1 test identity with an Employees row (no new users created for P3)"],
    "identity": {"caller": "approved R1 test identity", "service": "approved operational service identity (D-3)",
                 "serviceSubstitution": False},
    "flowPath": "Power Apps test screen -> TS-SaveEntry (guard, identity, settings, lookups, write, audit) -> response",
    "syntheticTag": "SYNTH-POC-P3-<yyyymmdd>",
    "measurements": [
        {"id": "E2E", "what": "client trigger to response", "how": "test screen timestamps around the flow call (ms) + Power Apps Monitor"},
        {"id": "GUARD", "what": "guard + identity overhead", "how": "run-history action timings: trigger start to Guard_result end"},
        {"id": "WRITE", "what": "SharePoint write portion", "how": "run-history timing of Create / Update (+ Get_new)"},
        {"id": "AUDIT", "what": "audit portion", "how": "run-history timing of Write_audit, Write_Authz_audit, Write_Write_proxy"},
    ],
    "scenarios": [
        {"id": "P3-C", "kind": "create", "warm": True, "repetitions": 30, "writes": 30},
        {"id": "P3-E", "kind": "edit", "warm": True, "repetitions": 30, "writes": 30, "target": "rows created by P3-C"},
        {"id": "P3-K", "kind": "conflict", "warm": True, "repetitions": 10, "writes": 0, "note": "stale ETag -> CONFLICT, nothing written"},
        {"id": "P3-V", "kind": "validation", "warm": True, "repetitions": 10, "writes": 0, "note": "Hours=0 -> VALIDATION_HOURS"},
        {"id": "P3-F", "kind": "cold", "warm": False, "repetitions": 5, "writes": 5,
         "note": "first call after >= 30 min without runs; separate idle windows; reported apart from warm runs"},
        {"id": "P3-D", "kind": "double-tap", "warm": True, "repetitions": 5, "writes": 5,
         "note": "R1-Q3 interim mitigation: Save disabled while in flight; expect exactly one row per tap pair"},
    ],
    "cleanup": {"method": "site administrator recycles each tagged entry after re-reading tag and synthetic marker; "
                          "the service identity never holds Delete", "covers": "all rows with the synthetic tag",
                "verify": "0 tagged rows remain", "auditRows": "kept (audit evidence; synthetic tag in Detail)"},
    "noRealData": True,
}

P5 = {
    "id": "P5", "title": "Choice-column (EntryStatus) filtering at > 5,000 rows",
    "status": STATUS, "executed": False, "approvalRequired": True,
    "source": ["IMPLEMENTATION-SPEC 11.4 (choice-column equality proven in POC P5 or replaced by a text code column)",
               "backlog T06.11.3", "gate G4", "R1 read contract ($filter EntryStatus ne 'Deleted')"],
    "environment": "STAGING", "mainAllowed": False,
    "dataset": {"reuse": "existing synthetic read-proxy spike list (> 5,000 rows; OwnerUpn and WorkDate indexed)",
                "precondition": "read-only check: EntryStatus is a Choice column with Draft / Approved / Deleted; row counts per status "
                                "for the synthetic owners",
                "fallback": "if EntryStatus is not a Choice column there, run P5 on TimesheetEntries after S06.1 instead"},
    # STEP 0 (read-only, run 2026-10-07 on STAGING, 7 GET requests, 0 writes): the spike list's EntryStatus is a
    # single-line TEXT column (not Choice), not indexed, no choices; rows hold only Draft / Approved (no Deleted).
    # A Text column cannot prove Choice-filter semantics, so the choice checks wait for TimesheetEntries (S06.1).
    "stepZero": {"executed": True, "readOnly": True, "writes": 0, "fieldExists": True, "fieldType": "Text", "indexed": False,
                 "choices": None, "statusesPresent": ["Approved", "Draft"], "conclusion": "BLOCKED UNTIL TIMESHEETENTRIES"},
    "newRows": {"count": 6, "only_if": "the dataset has no Deleted (or no Draft/Approved) rows for a synthetic owner",
                "shape": "2 Draft, 2 Approved, 2 Deleted for one synthetic owner on 3 business dates"},
    "syntheticTag": "SYNTH-POC-P5-<yyyymmdd>",
    "identity": {"caller": "site administrator (read-only REST) for the filter matrix", "serviceSubstitution": False},
    "checks": [
        {"id": "P5-01", "verifies": "Draft", "filter": "OwnerUpn eq '<owner>' and EntryStatus eq 'Draft'"},
        {"id": "P5-02", "verifies": "Approved", "filter": "OwnerUpn eq '<owner>' and EntryStatus eq 'Approved'"},
        {"id": "P5-03", "verifies": "Deleted exclusion", "filter": "OwnerUpn eq '<owner>' and EntryStatus ne 'Deleted'"},
        {"id": "P5-04", "verifies": "OwnerUpn + EntryStatus", "filter": "as P5-01..03; result = reference count from an owner-only read"},
        {"id": "P5-05", "verifies": "date + status", "filter": "<R1 read filter with FromDate/ToDate: generated by TS-ReadOwn>"},
        {"id": "P5-06", "verifies": "non-indexed status alone", "filter": "EntryStatus eq 'Draft'",
         "expect": "list view threshold error (status is never the first or only filter)"},
        {"id": "P5-07", "verifies": "indexed first filter keeps status filtering under the threshold", "filter": "P5-03 at > 5,000 rows"},
        {"id": "P5-08", "verifies": "query syntax generated by Power Automate", "filter": "TS-ReadOwn Filter output, byte for byte"},
        {"id": "P5-09", "verifies": "paging stability", "filter": "P5-03 + Id gt <AfterId>, $orderby Id, $top 2/3",
         "expect": "pages concatenated = single query; no duplicates; nextAfterId 0 on the last page"},
    ],
    "appDelegation": {"id": "P5-A", "verifies": "Power Apps choice equality delegation (Status.Value = \"Active\") on lists the app reads",
                      "blockedBy": "canvas app and Projects list (S06.x / G2)", "evidence": "Studio delegation warnings + solution checker"},
    "cleanup": {"method": "site administrator recycles each tagged row after re-reading tag and synthetic owner (only if new rows were created)",
                "covers": "all rows with the synthetic tag", "verify": "0 tagged rows remain; list count back to its pre-write value"},
    "noRealData": True,
}

P3_REQUIRED_KINDS = {"create", "edit", "conflict", "validation", "cold"}
P3_REQUIRED_MEASUREMENTS = {"E2E", "GUARD", "WRITE", "AUDIT"}
P5_REQUIRED = {"Draft", "Approved", "Deleted exclusion", "OwnerUpn + EntryStatus", "date + status", "non-indexed status alone",
               "query syntax generated by Power Automate", "paging stability"}


def validate(spec: dict) -> list:
    p = []
    if spec.get("environment") != "STAGING" or spec.get("mainAllowed"):
        p.append("STAGING only; MAIN is read-only")
    if spec.get("status") != STATUS or spec.get("executed"):
        p.append("a prepared procedure is never marked executed or PASS")
    if not spec.get("approvalRequired"):
        p.append("a separate live approval is required")
    if not spec.get("noRealData"):
        p.append("synthetic data only")
    if (spec.get("identity") or {}).get("serviceSubstitution") is not False:
        p.append("no service identity substitution")
    if not spec.get("syntheticTag", "").startswith("SYNTH-POC-%s-" % spec.get("id")):
        p.append("synthetic tag missing")
    writes = sum(s.get("writes", 0) for s in spec.get("scenarios", [])) + (spec.get("newRows") or {}).get("count", 0)
    c = spec.get("cleanup") or {}
    if writes and not (c.get("method") and c.get("verify") and "synthetic tag" in c.get("covers", "")):
        p.append("every synthetic write needs a documented cleanup and its verification")
    if "Delete" in c.get("method", "") and "never holds Delete" not in c.get("method", ""):
        p.append("cleanup must not give the service identity Delete")
    acc = spec.get("acceptance")
    if acc is not None and acc.get("threshold") not in (None, "DECISION REQUIRED") and not acc.get("thresholdSource"):
        p.append("acceptance threshold without an authoritative source (never invent an SLA)")
    for s in spec.get("scenarios", []):
        if not 1 <= s.get("repetitions", 0) <= MAX_REPETITIONS:
            p.append("%s: repetitions outside 1..%d" % (s["id"], MAX_REPETITIONS))
    if spec.get("id") == "P3":
        kinds = {s["kind"] for s in spec["scenarios"]}
        if P3_REQUIRED_KINDS - kinds:
            p.append("P3 scenarios missing: %s" % sorted(P3_REQUIRED_KINDS - kinds))
        if P3_REQUIRED_MEASUREMENTS - {m["id"] for m in spec["measurements"]}:
            p.append("P3 measurements missing")
        if any(s["warm"] and s["kind"] in ("create", "edit") and s["repetitions"] < 20 for s in spec["scenarios"]):
            p.append("P3 warm create/edit need >= 20 runs for a p95")
        if not spec.get("blockedBy"):
            p.append("P3 stays blocked until the R1 flow path is deployed legitimately")
    z = spec.get("stepZero")
    if z and z.get("executed") and (not z.get("readOnly") or z.get("writes")):
        p.append("step 0 is read-only")
    if z and z.get("fieldType") not in (None, "Choice") and z.get("conclusion") != "BLOCKED UNTIL TIMESHEETENTRIES":
        p.append("a non-Choice field cannot prove Choice semantics: P5 waits for TimesheetEntries")
    if spec.get("id") == "P5":
        if P5_REQUIRED - {x["verifies"] for x in spec["checks"]}:
            p.append("P5 checks missing: %s" % sorted(P5_REQUIRED - {x["verifies"] for x in spec["checks"]}))
        if (spec.get("newRows") or {}).get("count", 0) > MAX_NEW_SYNTHETIC_ROWS:
            p.append("P5 reuses the existing dataset; at most %d new rows" % MAX_NEW_SYNTHETIC_ROWS)
        if "reuse" not in (spec.get("dataset") or {}):
            p.append("P5 must say which existing dataset it reuses")
    return p
