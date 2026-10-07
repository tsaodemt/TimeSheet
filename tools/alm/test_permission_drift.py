"""PERMISSION-DRIFT-01 evaluator tests PDT01-PDT09 (offline; synthetic evidence)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import permission_drift as pd  # noqa: E402

SITE = "https://tenant-a.invalid/sites/app-staging"
READ = ["View", "Open", "ViewPages"]
SVC = ["View", "Add", "Edit", "Open", "ViewPages"]
ADMIN = {"owners": ["Full Control"], "siteAdmin": ["Full Control"]}
APPROVED = {n: dict(ADMIN, employees=["Read"]) for n in pd.MASTER}
APPROVED["Employees"]["service"] = ["TS Service"]
APPROVED["AppSettings"] = dict(ADMIN)
APPROVED["AuditLog"] = dict(ADMIN)


def lst(name):
    a = APPROVED[name]
    eff = {"newVisitor": [], "service": SVC if "service" in a else [],
           "employees": READ if "employees" in a else [], "demoUser": READ if "employees" in a else []}
    return {"unique": True, "ra": copy.deepcopy(a), "eff": eff}


GOOD = {"expectedSite": SITE, "site": SITE, "mainMutations": 0, "productionMutations": 0, "entraMutations": 0, "mutations": [],
        "visitors": {"members": 1, "membershipCreated": "t", "intent": "UNKNOWN"}, "webRoleAssignmentsUnchanged": True,
        "lists": {n: lst(n) for n in pd.PROTECTED}, "approved": APPROVED, "approvedServiceRights": {"AppSettings": []},
        "liveReads": {"demoUser": {"AppSettings": 404}}, "businessDataUnchanged": True, "schemaUnchanged": True, "uxUnchanged": True,
        "pocMasterPass": True, "uxTaskPermissionMutations": 0, "ownerDecisionTracked": True}


def ev(**over):
    e = copy.deepcopy(GOOD)
    e.update(over)
    return e


class PermissionDriftTests(unittest.TestCase):
    def test_pdt01_clean_state_passes_with_na_repair(self):
        r = pd.evaluate(GOOD)
        self.assertTrue(r["pass"], r["tests"])
        self.assertEqual(r["tests"]["PD21"][0], "N/A")
        self.assertEqual(r["classification"]["APPSETTINGS"], "EXPECTED")
        self.assertEqual(r["classification"]["VISITORS GROUP"], "UNKNOWN")

    def test_pdt02_inheriting_appsettings_is_drift(self):
        e = ev()
        e["lists"]["AppSettings"]["unique"] = False
        r = pd.evaluate(e)
        self.assertEqual(r["classification"]["APPSETTINGS"], "PERMISSION_DRIFT")
        self.assertEqual(r["tests"]["PD21"][0], "FAIL")  # drift without repair

    def test_pdt03_visitor_member_with_effective_read_is_drift(self):
        e = ev()
        e["lists"]["AuditLog"]["eff"]["newVisitor"] = READ
        r = pd.evaluate(e)
        self.assertEqual(r["classification"]["AUDITLOG"], "PERMISSION_DRIFT")
        self.assertEqual(r["tests"]["PD13"][0], "FAIL")

    def test_pdt04_extra_role_assignment_is_drift(self):
        e = ev()
        e["lists"]["Departments"]["ra"]["visitors"] = ["Read"]
        self.assertEqual(pd.evaluate(e)["classification"]["DEPARTMENTS"], "PERMISSION_DRIFT")

    def test_pdt05_employee_write_is_drift(self):
        e = ev()
        e["lists"]["Employees"]["eff"]["demoUser"] = READ + ["Edit"]
        self.assertEqual(pd.evaluate(e)["tests"]["PD15"][0], "FAIL")

    def test_pdt06_minimal_repair_accepted_only_for_drifted_list(self):
        e = ev()
        e["lists"]["AppSettings"]["unique"] = False
        e["repair"] = {"lists": ["AppSettings"], "siteChanged": False, "reverified": True}
        r = pd.evaluate(e)
        self.assertEqual(r["tests"]["PD21"][0], "PASS")
        e["repair"] = {"lists": ["AppSettings", "Employees"], "siteChanged": False, "reverified": True}
        self.assertEqual(pd.evaluate(e)["tests"]["PD21"][0], "FAIL")
        e["repair"] = {"lists": ["AppSettings"], "siteChanged": True, "reverified": True}
        self.assertEqual(pd.evaluate(e)["tests"]["PD21"][0], "FAIL")

    def test_pdt07_ux_reassessment_rules(self):
        self.assertEqual(pd.evaluate(GOOD)["uxReassessment"], "PASS 22/22")
        self.assertEqual(pd.evaluate(ev(ownerDecisionTracked=False))["uxReassessment"], "OWNER DECISION REQUIRED")
        self.assertEqual(pd.evaluate(ev(uxTaskPermissionMutations=1))["uxReassessment"], "OWNER DECISION REQUIRED")
        e = ev()
        e["lists"]["AppSettings"]["eff"]["newVisitor"] = READ
        self.assertEqual(pd.evaluate(e)["uxReassessment"], "FAIL / SECURITY DRIFT OPEN")

    def test_pdt08_intent_must_be_classified(self):
        self.assertEqual(pd.evaluate(ev(visitors={"members": 1, "membershipCreated": "t"}))["tests"]["PD05"][0], "FAIL")

    def test_pdt09_service_beyond_approved_fails(self):
        e = ev()
        e["lists"]["AppSettings"]["eff"]["service"] = READ
        self.assertEqual(pd.evaluate(e)["tests"]["PD11"][0], "FAIL")


if __name__ == "__main__":
    unittest.main()
