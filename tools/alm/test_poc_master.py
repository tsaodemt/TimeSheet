"""POC-MASTER-01 evaluator tests PMT01-PMT12 (offline; synthetic evidence)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import poc_master as pm  # noqa: E402

SITE = "https://tenant-a.invalid/sites/app-staging"
READ = ["ViewListItems", "OpenItems", "ViewVersions", "ViewFormPages", "Open", "ViewPages"]
SVC = ["ViewListItems", "AddListItems", "EditListItems", "OpenItems", "Open", "ViewPages", "UseRemoteAPIs"]


def probes():
    p = []
    for l in pm.PROTECTED:
        p += [{"list": l, "op": "CREATE", "status": 403}, {"list": l, "op": "EDIT", "status": 403}]
        p += [{"list": l, "op": "DELETE", "status": 412}]
    p.append({"list": "Employees", "op": "DELETE", "status": 403})
    return p


GOOD = {
    "expectedSite": SITE, "site": SITE,
    "lists": {l: {"exists": True, "uniquePermissions": True, "itemCount": 5} for l in pm.PROTECTED},
    "integrity": {"brokenLookups": 0, "missingDepartment": 0, "missingDiscipline": 0, "missingPosition": 1},
    "identityRows": [{"id": 9, "active": True}],
    "identityRefs": {k: {"id": 1, "active": True} for k in ("Department", "Discipline", "Position")},
    "userReads": {l: 200 for l in pm.PROTECTED},
    "probes": probes(),
    "itemEffective": {l: {"items": 5, "add": 0, "edit": 0, "delete": 0} for l in pm.PROTECTED},
    "userRights": {l: READ for l in pm.PROTECTED},
    "serviceRights": {"Employees": SVC}, "serviceApproved": {"Employees": SVC},
    "change": {"preExistingRowsChanged": 0, "otherListsChanged": 0, "schemaOrPermissionChanged": 0},
    "mainMutations": 0, "productionMutations": 0,
    "mutations": [{"kind": "DEMO_EMPLOYEE_ROW", "target": SITE, "marker": "DEMO_ONLY"}, {"kind": "GROUP_MEMBERSHIP"}],
}


def ev(**over):
    e = copy.deepcopy(GOOD)
    e.update(over)
    return e


class PocMasterTests(unittest.TestCase):
    def test_pmt01_good_evidence_passes_20_of_20(self):
        r = pm.evaluate(GOOD)
        self.assertTrue(r["pass"], r["tests"])
        self.assertEqual(r["score"], "20/20")

    def test_pmt02_identity_cardinality_rules(self):
        self.assertEqual(pm.resolve_identity([])[0], "UNMAPPED_IDENTITY")
        self.assertEqual(pm.resolve_identity([{"active": True}, {"active": True}])[0], "DUPLICATE_IDENTITY")
        self.assertEqual(pm.resolve_identity([{"active": False}])[0], "INACTIVE_EMPLOYEE")
        self.assertEqual(pm.evaluate(ev(identityRows=[]))["tests"]["PM07"], ("FAIL", "UNMAPPED_IDENTITY"))

    def test_pmt03_allowed_probe_is_boundary_failure(self):
        p = probes()
        p[1] = {"list": "Departments", "op": "EDIT", "status": 204}
        r = pm.evaluate(ev(probes=p))
        self.assertFalse(r["pass"])
        self.assertIn("PERMISSION_BOUNDARY_FAILURE", r["tests"]["PM13"][1])

    def test_pmt04_inconclusive_needs_item_level_proof(self):
        eff = copy.deepcopy(GOOD["itemEffective"])
        eff["Positions"]["delete"] = 1
        self.assertEqual(pm.evaluate(ev(itemEffective=eff))["tests"]["PM14"][0], "FAIL")
        self.assertEqual(pm.evaluate(ev(itemEffective={}))["tests"]["PM14"][0], "FAIL")

    def test_pmt05_employee_delete_must_be_live_denied_or_proven(self):
        p = [x for x in probes() if not (x["list"] == "Employees" and x["status"] == 403 and x["op"] == "DELETE")]
        eff = copy.deepcopy(GOOD["itemEffective"])
        eff["Employees"]["delete"] = 2
        self.assertEqual(pm.evaluate(ev(probes=p, itemEffective=eff))["tests"]["PM15"][0], "FAIL")

    def test_pmt06_unprobed_operation_fails(self):
        p = [x for x in probes() if x["op"] != "CREATE"]
        self.assertEqual(pm.evaluate(ev(probes=p))["tests"]["PM12"][0], "FAIL")

    def test_pmt07_service_broader_than_approved_fails(self):
        self.assertEqual(pm.evaluate(ev(serviceRights={"Employees": SVC, "Departments": READ}))["tests"]["PM16"][0], "FAIL")
        self.assertEqual(pm.evaluate(ev(serviceRights={"Employees": SVC + ["DeleteListItems"]},
                                        serviceApproved={"Employees": SVC + ["DeleteListItems"]}))["tests"]["PM16"][0], "FAIL")

    def test_pmt08_user_full_control_fails(self):
        self.assertEqual(pm.evaluate(ev(userRights={"Employees": READ + ["FullMask"]}))["tests"]["PM16"][0], "FAIL")

    def test_pmt09_unexpected_mutations_fail(self):
        extra = GOOD["mutations"] + [{"kind": "PERMISSION_GRANT", "target": SITE}]
        self.assertEqual(pm.evaluate(ev(mutations=extra))["tests"]["PM20"][0], "FAIL")
        two = GOOD["mutations"] + [{"kind": "DEMO_EMPLOYEE_ROW", "target": SITE, "marker": "DEMO_ONLY"}]
        self.assertEqual(pm.evaluate(ev(mutations=two))["tests"]["PM20"][0], "FAIL")
        unmarked = [{"kind": "DEMO_EMPLOYEE_ROW", "target": SITE, "marker": None}]
        self.assertEqual(pm.evaluate(ev(mutations=unmarked))["tests"]["PM20"][0], "FAIL")

    def test_pmt10_wrong_target_fails(self):
        r = pm.evaluate(ev(mutations=[{"kind": "DEMO_EMPLOYEE_ROW", "target": "https://tenant-a.invalid/", "marker": "DEMO_ONLY"}]))
        self.assertEqual(r["tests"]["PM01"][0], "FAIL")
        self.assertEqual(pm.evaluate(ev(mainMutations=1))["tests"]["PM18"][0], "FAIL")

    def test_pmt11_broken_lookup_or_changed_rows_fail(self):
        self.assertEqual(pm.evaluate(ev(integrity={"brokenLookups": 1, "missingDepartment": 0, "missingDiscipline": 0}))["tests"]["PM06"][0], "FAIL")
        self.assertEqual(pm.evaluate(ev(change={"preExistingRowsChanged": 1, "otherListsChanged": 0,
                                                "schemaOrPermissionChanged": 0}))["tests"]["PM17"][0], "FAIL")

    def test_pmt12_pass_never_claims_later_stages(self):
        f = pm.evaluate(GOOD)["foundation"]
        self.assertEqual(f["POC-MASTER-01"], "PASS")
        for s in pm.LATER_STAGES:
            self.assertEqual(f[s], "NOT DONE")
        self.assertEqual(pm.evaluate(ev(productionMutations=1))["foundation"]["POC-MASTER-01"], "FAIL")


if __name__ == "__main__":
    unittest.main()
