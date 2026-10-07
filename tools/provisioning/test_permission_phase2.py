"""Phase 2 service-permission plan tests P201-P213 (offline; synthetic snapshot)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import permission_plan as pp  # noqa: E402
import schema_reconcile as sr  # noqa: E402

SITE = "https://tenant-a.invalid/sites/app-staging"
OWNERS, ADMIN, STAFF, MEMBERS, SVC, SPIKE = 7, 10, 15, 9, 77, 13
HARDENED = pp.parse(["7:Site Owners=Full Control", "10:Site Admin=Full Control"])
MASTER = pp.parse(["7:Site Owners=Full Control", "10:Site Admin=Full Control", "15:Staff Group=Read"])
SERVICE = {"principal_id": SVC, "title": "svc-operational", "approval": "IT approval CHG-1"}
TEMP = (SPIKE, "Spike Service")
READERS = {"Phases": {STAFF: "Read"}}


def plan(lists, service=SERVICE, site=SITE):
    return pp.service_read_plan(site, SITE, lists, owners_id=OWNERS, admin_id=ADMIN, service=service,
                                temporary_principals=TEMP, allowed_readers=READERS)


class Phase2(unittest.TestCase):
    def test_P201_missing_read_is_created(self):
        p = plan({"AppSettings": (True, HARDENED)})
        self.assertEqual(p["lists"]["AppSettings"]["ops"], [("add", {"principal_id": SVC, "role": "Read", "gate": "D-3"})])
        self.assertEqual(pp.requests("AppSettings", p["lists"]["AppSettings"]["ops"]),
                         [("POST", "/_api/web/lists/getbytitle('AppSettings')/roleassignments/addroleassignment(principalid=77,roledefid=1073741826)")])

    def test_P202_exact_read_is_a_no_op(self):
        p = plan({"AppSettings": (True, HARDENED + pp.parse(["77:svc-operational=Read"]))})
        self.assertEqual(p["lists"]["AppSettings"], {"ops": [], "findings": []})

    def test_P203_P204_broader_service_rights_are_security_drift(self):
        for roles in ("Edit", "Full Control", "Read+Contribute", "TS Service"):
            p = plan({"AppSettings": (True, HARDENED + pp.parse(["77:svc-operational=%s" % roles]))})
            self.assertEqual(p["lists"]["AppSettings"]["ops"], [], roles)
            self.assertEqual([f[0] for f in p["lists"]["AppSettings"]["findings"]], ["SECURITY_DRIFT"], roles)

    def test_P205_spike_account_never_the_production_identity(self):
        for svc in ({"principal_id": SPIKE, "title": "x", "approval": "y"}, {"principal_id": 99, "title": "spike service", "approval": "y"},
                    {"principal_id": SVC, "title": "svc"}):
            with self.assertRaises(pp.PlanRefused):
                plan({"AppSettings": (True, HARDENED)}, service=svc)

    def test_P206_no_approved_identity_is_gated(self):
        p = plan({"AppSettings": (True, HARDENED), "Phases": (True, MASTER)}, service=None)
        self.assertTrue(p["gated"])
        self.assertTrue(all(v["ops"] == [] for v in p["lists"].values()))

    def test_P207_owners_untouched_and_missing_owners_reported(self):
        p = plan({"AppSettings": (True, HARDENED)})
        self.assertFalse(any(a.get("principal_id") == OWNERS for _, a in p["lists"]["AppSettings"]["ops"]))
        p = plan({"AppSettings": (True, pp.parse(["10:Site Admin=Full Control"]))})
        self.assertIn("OWNERS_MISSING", [f[0] for f in p["lists"]["AppSettings"]["findings"]])

    def test_P208_P209_no_employee_member_or_visitor_access_added_and_strays_reported(self):
        p = plan({"AppSettings": (True, HARDENED + pp.parse(["9:Site Members=Edit"]))})
        ops = p["lists"]["AppSettings"]["ops"]
        self.assertTrue(all(a["principal_id"] == SVC and a["role"] == "Read" for _, a in ops))
        self.assertIn("UNEXPECTED_PRINCIPAL", [f[0] for f in p["lists"]["AppSettings"]["findings"]])
        self.assertFalse(any(op == "remove" for op, _ in ops), "never auto-removed in phase 2")
        p = plan({"Phases": (True, MASTER)})
        self.assertEqual(p["lists"]["Phases"]["findings"], [], "approved staff Read on a master list is expected")
        p = plan({"Phases": (True, pp.parse(["7:Site Owners=Full Control", "15:Staff Group=Edit"]))})
        self.assertEqual([f[0] for f in p["lists"]["Phases"]["findings"]], ["SECURITY_DRIFT"])

    def test_P210_no_delete_ever_planned(self):
        p = plan({t: (True, HARDENED) for t in ("AppSettings", "Phases", "WorkTypes", "Shifts", "HourTypes")})
        roles = {a["role"] for v in p["lists"].values() for _, a in v["ops"]}
        self.assertEqual(roles, {"Read"})
        self.assertEqual(pp.PHASE2_ROLES, {"Read"})

    def test_P211_second_run_is_a_no_op(self):
        p = plan({"AppSettings": (True, HARDENED)})
        _, after = pp.simulate(True, HARDENED, p["lists"]["AppSettings"]["ops"], admin_id=None)
        self.assertEqual(plan({"AppSettings": (True, after)})["lists"]["AppSettings"]["ops"], [])

    def test_P212_wrong_target_url_rejected(self):
        for url in ("https://tenant-a.invalid", SITE + "-other", "https://other.invalid/sites/app-staging"):
            with self.assertRaises(sr.SiteGuardError):
                plan({"AppSettings": (True, HARDENED)}, site=url)

    def test_P213_unhardened_list_is_reported_not_granted(self):
        p = plan({"AppSettings": (False, HARDENED)})
        self.assertEqual((p["lists"]["AppSettings"]["ops"], [f[0] for f in p["lists"]["AppSettings"]["findings"]]), ([], ["NOT_HARDENED"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
