"""EMPLOYEE-IDENTITY-MAPPING-01 evaluator tests IME01-IME12 (synthetic data only; run: python -m unittest)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "identity"))
from employee_matching import AUTO_MATCH_SAFE, Account, Config, Employee, match  # noqa: E402
from identity_mapping import TESTS, evaluate  # noqa: E402

DOM = "tenant-a.invalid"
CFG = Config(org_domains=[DOM], excluded_upns=["named-svc@" + DOM])
STG, MAIN = "https://tenant-a.invalid/sites/stg", "https://tenant-a.invalid/"


def build():
    emps = [Employee(1, "L-1", "Trần Văn An", True, "an.tv", batch="RUN1"),
            Employee(2, "L-2", "Lê Bình", False, "binh.l", batch="RUN1"),
            Employee(3, "L-3", "Võ Cường", True, "cuong.v", batch="RUN1"),
            Employee(4, "D-1", "DEMO Employee", True, "D-1", "named-svc@" + DOM, batch="DEMO_ONLY")]
    accts = [Account("o1", "an.tran@" + DOM, "Tran Van An", "Member", True),
             Account("o2", "named-svc@" + DOM, "Named Svc", "Member", True),
             Account("o3", "g_x.com#EXT#@t.invalid", "Guest X", "Guest", None)]
    fp = {"count": 4, "maxModified": "2026-01-01T00:00:00Z"}
    return {
        "target": {"expectedUrl": STG, "resolvedUrl": STG, "mainUrl": MAIN, "employeesListFound": True},
        "spRequests": [{"method": "GET", "url": STG + "/_api/web"}],
        "employeesBefore": fp, "employeesAfter": dict(fp),
        "entra": {"mutations": 0, "actionKinds": ["NAV", "DOM_READ", "SCROLL"], "readOnly": True,
                  "directoryBefore": 3, "directoryAfter": 3, "crossCheckTotal": 3},
        "match": match(emps, accts, CFG),
        "expectedRealEmployees": 3, "expectedDemoRows": 1, "employeeRowsLive": 4, "expectedActiveInactive": [2, 1],
        "configuredExclusions": ["o2"],
        "schema": {"AccountUpn": {"Indexed": True, "EnforceUniqueValues": True}},
        "accountUpnWrites": 0, "mappingsApplied": 0, "usersCreated": 0,
        "privateArtifacts": {"exists": {"csv": True, "json": True}, "gitIgnored": True},
        "publicScan": {"scannedFiles": 5, "realUpnHits": 0, "realNameHits": 0, "tenantHits": 0},
        "powerPlatformMutations": 0, "mainRequests": 0, "mainMutations": 0,
        "productionRequests": 0, "productionMutations": 0,
    }


class Evaluator(unittest.TestCase):
    def fails(self, ev):
        return {k for k, v in evaluate(ev)["tests"].items() if v[0] == "FAIL"}

    def test_ime01_clean_run_passes_24(self):
        r = evaluate(build())
        self.assertEqual(set(r["tests"]), set(TESTS))
        self.assertTrue(r["pass"], r["tests"])
        self.assertEqual(r["score"], "24/24")

    def test_ime02_wrong_target(self):
        ev = build()
        ev["target"]["resolvedUrl"] = MAIN
        self.assertIn("IM01", self.fails(ev))

    def test_ime03_sharepoint_write_detected(self):
        ev = build()
        ev["spRequests"].append({"method": "POST", "url": STG + "/_api/web/lists"})
        self.assertIn("IM02", self.fails(ev))
        ev = build()
        ev["employeesAfter"]["maxModified"] = "2026-02-01T00:00:00Z"
        self.assertIn("IM02", self.fails(ev))
        # An added row is acceptable only when proven out-of-band (provenance, not attributed to the task).
        ev["employeesDiff"] = {"added": [9], "removed": [], "changed": []}
        self.assertIn("IM02", self.fails(ev))
        ev["externalChanges"] = [{"itemId": 9, "attributedToTask": False, "provenance": "created by another actor"}]
        self.assertNotIn("IM02", self.fails(ev))
        ev["employeesDiff"]["changed"] = [1]
        self.assertIn("IM02", self.fails(ev))

    def test_ime04_directory_mutation_or_click(self):
        ev = build()
        ev["entra"]["actionKinds"].append("CLICK_MENU_ITEM")
        self.assertIn("IM03", self.fails(ev))
        ev = build()
        ev["entra"].update(actionKinds=["NAV", "MENU_OPEN_NO_ITEM", "ESCAPE"], menuItemsInvoked=0, rowsSelected=0)
        self.assertNotIn("IM03", self.fails(ev))
        ev["entra"]["menuItemsInvoked"] = 1
        self.assertIn("IM03", self.fails(ev))

    def test_ime05_count_mismatch(self):
        ev = build()
        ev["expectedRealEmployees"] = 4
        self.assertTrue({"IM04", "IM05"} <= self.fails(ev))

    def test_ime06_forced_unsafe_safe_row(self):
        ev = build()
        r = next(x for x in ev["match"]["rows"] if x["itemId"] == 1)
        r["classification"] = AUTO_MATCH_SAFE              # name-only evidence: must be caught
        self.assertIn("IM17", self.fails(ev))

    def test_ime07_unique_constraint_missing(self):
        ev = build()
        ev["schema"]["AccountUpn"]["EnforceUniqueValues"] = False
        self.assertIn("IM16", self.fails(ev))

    def test_ime08_public_leak(self):
        ev = build()
        ev["publicScan"]["realUpnHits"] = 1
        self.assertIn("IM21", self.fails(ev))

    def test_ime09_main_or_production_touched(self):
        ev = build()
        ev["mainRequests"] = 1
        ev["productionMutations"] = 1
        self.assertTrue({"IM23", "IM24"} <= self.fails(ev))

    def test_ime10_user_created_or_mapping_applied(self):
        ev = build()
        ev["usersCreated"] = 1
        ev["mappingsApplied"] = 1
        self.assertTrue({"IM18", "IM19"} <= self.fails(ev))

    def test_ime11_proposed_collision_detected(self):
        ev = build()
        rows = ev["match"]["rows"]
        a, c = rows[0], rows[2]
        c.update(classification="NEEDS_REVIEW", candidate=copy.deepcopy(a["candidate"]))
        self.assertIn("IM14", self.fails(ev))

    def test_ime12_service_account_proposed(self):
        ev = build()
        r = next(x for x in ev["match"]["rows"] if x["itemId"] == 3)
        r.update(classification="NEEDS_REVIEW",
                 candidate={"objectId": "o2", "upn": "named-svc@" + DOM, "kind": "SERVICE_TEST", "evidence": []})
        self.assertTrue({"IM08", "IM14"} <= self.fails(ev))


if __name__ == "__main__":
    unittest.main()
