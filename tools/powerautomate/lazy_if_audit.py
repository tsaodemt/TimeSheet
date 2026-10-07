"""Lazy-evaluation dependency audit for generated flows (offline).

Runs the flow parity suites with the simulator in `audit` mode: every if()/and()/or() returns its lazy result, and
each argument that a lazy runtime skips is also evaluated. An error there marks an expression whose correctness
depends on lazy branch evaluation. Usage: python lazy_if_audit.py [--json]

The suites must also pass in `eager` mode (TS_WDL_BRANCHES=eager): then the flows are correct whichever way the
runtime evaluates branches, and the first-live check only confirms it (docs/r1-first-live-checks.md, V-LAZY).
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SUITES = [("timesheet", "test_r1_read_flow"), ("timesheet", "test_r1_save_flow"), ("config", "test_appstart"),
          ("identity", "test_guard"), ("maintenance", "test_maintenance_flow")]


def run(suites=SUITES, mode="audit") -> tuple:
    for d in ("timesheet", "config", "identity", "maintenance", "powerautomate", "audit", "provisioning"):
        sys.path.insert(0, os.path.join(ROOT, d))
    import wdl_sim
    wdl_sim.BRANCH_MODE = mode
    del wdl_sim.LAZY_HITS[:]
    loader, result = unittest.TestLoader(), unittest.TestResult()
    for d, mod in suites:
        loader.loadTestsFromName(mod).run(result)
    hits = {}
    for h in wdl_sim.LAZY_HITS:
        hits.setdefault((h["action"], h["function"], h["unused"]), h)
    wdl_sim.BRANCH_MODE = "lazy"
    return result, sorted(hits.values(), key=lambda h: (str(h["action"]), h["unused"]))


if __name__ == "__main__":
    mode = os.environ.get("TS_WDL_BRANCHES", "audit")
    res, hits = run(mode=mode)
    if "--json" in sys.argv:
        print(json.dumps(hits, indent=1, ensure_ascii=False))
    else:
        for h in hits:
            print("%-22s %-4s unused: %s\n%28s%s" % (h["action"], h["function"], h["unused"][:150], "", h["error"][:120]))
    print("mode=%s tests=%d failures=%d errors=%d lazy-dependent expressions=%d"
          % (mode, res.testsRun, len(res.failures), len(res.errors), len(hits)))
    for t, tb in (res.failures + res.errors)[:5]:
        print(t, tb.splitlines()[-1])
