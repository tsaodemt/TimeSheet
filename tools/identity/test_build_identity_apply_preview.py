"""Apply-preview tests AP01-AP19 (synthetic data only; run: python -m unittest)."""
import csv
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_identity_apply_preview as bp  # noqa: E402
from employee_matching import Config  # noqa: E402

DOM = "tenant-a.invalid"
CFG = Config(org_domains=[DOM], excluded_upns=["shared-box@" + DOM])
EMPS = [{"itemId": 1, "legacyId": "L-1", "active": True, "accountUpn": None},
        {"itemId": 2, "legacyId": "L-2", "active": True, "accountUpn": None},
        {"itemId": 3, "legacyId": "L-3", "active": False, "accountUpn": None},
        {"itemId": 4, "legacyId": "L-4", "active": True, "accountUpn": "taken@" + DOM}]
DIR = [{"objectId": "o1", "upn": "an.tran@" + DOM, "displayName": "Tran Van An", "userType": "Member", "enabled": True},
       {"objectId": "o2", "upn": "binh.le@" + DOM, "displayName": "Le Binh", "userType": "Member", "enabled": True},
       {"objectId": "o3", "upn": "off.user@" + DOM, "displayName": "Off User", "userType": "Member", "enabled": False},
       {"objectId": "o4", "upn": "g_x.com#EXT#@t.invalid", "displayName": "Guest", "userType": "Guest", "enabled": True},
       {"objectId": "o5", "upn": "shared-box@" + DOM, "displayName": "Shared", "userType": "Member", "enabled": True},
       {"objectId": "o6", "upn": "taken@" + DOM, "displayName": "Taken", "userType": "Member", "enabled": True}]


def row(item, legacy, cand="", decision="", rupn="", cur="", by="hr.reviewer", on="2026-10-08",
        basis=bp.HR_IT_APPROVED):
    return {"EmployeeItemId": str(item), "LegacyId": legacy, "CandidateUpn": cand, "CurrentAccountUpn": cur,
            "ReviewerDecision": decision, "ReviewerUpn": rupn, "ReviewedBy": by if decision else "",
            "ReviewedOn": on if decision else "", "ApprovalBasis": basis if decision else ""}


def run(rows, env="STAGING"):
    return bp.build_preview(rows, EMPS, DIR, CFG, env)


def reasons(res, item):
    return next(x["reasons"] for x in res["rejected"] if str(x["employeeItemId"]) == str(item))


class Preview(unittest.TestCase):
    def test_ap01_blank_review_produces_nothing(self):
        res = run([row(1, "L-1", "an.tran@" + DOM), row(2, "L-2", "binh.le@" + DOM)])
        self.assertEqual(res["apply"], [])
        self.assertEqual(res["mode"], "PREVIEW_ONLY_NO_WRITES")

    def test_ap02_approve_accepted(self):
        res = run([row(1, "L-1", "an.tran@" + DOM, "APPROVE")])
        self.assertEqual(res["apply"], [{"employeeItemId": 1, "legacyId": "L-1", "accountUpn": "an.tran@" + DOM,
                                         "decision": "APPROVE", "approvalBasis": bp.HR_IT_APPROVED}])

    def test_ap03_change_requires_reviewer_upn(self):
        res = run([row(1, "L-1", "an.tran@" + DOM, "CHANGE")])
        self.assertEqual(res["apply"], [])
        self.assertIn("CHANGE_REQUIRES_REVIEWER_UPN", reasons(res, 1))
        res = run([row(1, "L-1", "", "CHANGE", "an.tran@" + DOM)])
        self.assertEqual(res["apply"][0]["accountUpn"], "an.tran@" + DOM)

    def test_ap04_no_mapping_decisions_excluded(self):
        for d in ("REJECT", "NO_ACCOUNT_CONFIRMED", "DEFER"):
            self.assertEqual(run([row(1, "L-1", "an.tran@" + DOM, d)])["apply"], [], d)

    def test_ap05_vocabulary_enforced(self):
        for d in ("approved", "Yes", "OK", "MAYBE"):
            res = run([row(1, "L-1", "an.tran@" + DOM, d)])
            self.assertEqual(res["apply"], [], d)
        errs = bp.validate_review([row(1, "L-1", "an.tran@" + DOM, "Yes")])
        self.assertIn("INVALID_DECISION", errs[0]["errors"])
        errs = bp.validate_review([row(1, "L-1", "an.tran@" + DOM, "approve")])
        self.assertIn("DECISION_NOT_CANONICAL_CASE", errs[0]["errors"])

    def test_ap06_approve_with_different_upn_must_use_change(self):
        res = run([row(1, "L-1", "an.tran@" + DOM, "APPROVE", "binh.le@" + DOM)])
        self.assertIn("APPROVE_WITH_DIFFERENT_UPN_USE_CHANGE", reasons(res, 1))

    def test_ap07_disabled_guest_service_rejected(self):
        for upn, code in (("off.user@" + DOM, "ACCOUNT_DISABLED"), ("g_x.com#ext#@t.invalid", None),
                          ("shared-box@" + DOM, "ACCOUNT_IS_SERVICE_OR_TEST")):
            res = run([row(1, "L-1", "", "CHANGE", upn)])
            self.assertEqual(res["apply"], [], upn)
            if code:
                self.assertIn(code, reasons(res, 1))

    def test_ap08_guest_with_valid_format_rejected(self):
        d = DIR + [{"objectId": "o7", "upn": "guest.user@" + DOM, "displayName": "G", "userType": "Guest",
                    "enabled": True}]
        res = bp.build_preview([row(1, "L-1", "", "CHANGE", "guest.user@" + DOM)], EMPS, d, CFG, "STAGING")
        self.assertIn("ACCOUNT_IS_GUEST", reasons(res, 1))

    def test_ap09_unknown_account_rejected(self):
        res = run([row(1, "L-1", "", "CHANGE", "nobody@" + DOM)])
        self.assertIn("ACCOUNT_NOT_FOUND", reasons(res, 1))

    def test_ap10_upn_collision_rejects_all(self):
        res = run([row(1, "L-1", "an.tran@" + DOM, "APPROVE"), row(2, "L-2", "", "CHANGE", "an.tran@" + DOM)])
        self.assertEqual(res["apply"], [])
        self.assertIn("UPN_PROPOSED_FOR_MULTIPLE_EMPLOYEES", reasons(res, 1))
        self.assertIn("UPN_PROPOSED_FOR_MULTIPLE_EMPLOYEES", reasons(res, 2))

    def test_ap11_upn_used_by_other_employee(self):
        res = run([row(1, "L-1", "", "CHANGE", "taken@" + DOM)])
        self.assertIn("UPN_ALREADY_USED_BY_OTHER_EMPLOYEE", reasons(res, 1))

    def test_ap12_inactive_employee_rejected(self):
        res = run([row(3, "L-3", "binh.le@" + DOM, "APPROVE")])
        self.assertIn("EMPLOYEE_NOT_ACTIVE", reasons(res, 3))

    def test_ap13_accountupn_changed_since_review(self):
        res = run([row(4, "L-4", "binh.le@" + DOM, "APPROVE", cur="")])
        self.assertIn("ACCOUNTUPN_CHANGED_SINCE_REVIEW", reasons(res, 4))
        res = run([row(4, "L-4", "binh.le@" + DOM, "APPROVE", cur="taken@" + DOM)])
        self.assertIn("ALREADY_MAPPED_NO_OVERWRITE", reasons(res, 4))

    def test_ap14_duplicate_employee_rows_and_identity_change(self):
        res = run([row(1, "L-1", "an.tran@" + DOM, "APPROVE"), row(1, "L-1", "binh.le@" + DOM, "APPROVE")])
        self.assertEqual(res["apply"], [])
        res = run([row(1, "L-9", "an.tran@" + DOM, "APPROVE")])
        self.assertIn("EMPLOYEE_IDENTITY_CHANGED", reasons(res, 1))

    def test_ap15_reviewer_identity_required(self):
        res = run([row(1, "L-1", "an.tran@" + DOM, "APPROVE", by="", on="")])
        self.assertIn("REVIEWER_IDENTITY_OR_DATE_MISSING", reasons(res, 1))

    def test_ap16_no_network_and_cli_writes_only_out_file(self):
        src = open(os.path.join(HERE, "build_identity_apply_preview.py"), encoding="utf-8").read()
        self.assertIsNone(re.search(r"\b(urllib|requests|http\.client|socket|fetch\(|subprocess)\b", src))
        with tempfile.TemporaryDirectory() as d:
            p = lambda n: os.path.join(d, n)  # noqa: E731
            with open(p("r.csv"), "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(row(1, "L-1").keys()))
                w.writeheader()
                w.writerow(row(1, "L-1", "an.tran@" + DOM, "APPROVE"))
            for n, v in (("e.json", EMPS), ("d.json", DIR), ("c.json", {"orgDomains": [DOM],
                                                                         "excludedUpns": ["shared-box@" + DOM]})):
                with open(p(n), "w", encoding="utf-8") as f:
                    json.dump(v, f)
            before = set(os.listdir(d))
            bp.main(["--review", p("r.csv"), "--employees", p("e.json"), "--directory", p("d.json"),
                     "--config", p("c.json"), "--environment", "STAGING", "--out", p("out.json")])
            self.assertEqual(set(os.listdir(d)) - before, {"out.json"})
            with open(p("out.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["summary"]["applyRows"], 1)

    def test_ap17_staging_bypass_only_valid_in_staging(self):
        r = [row(1, "L-1", "an.tran@" + DOM, "APPROVE", basis=bp.STAGING_TEMPORARY_BYPASS)]
        self.assertEqual(len(run(r, "STAGING")["apply"]), 1)
        for env in ("UAT", "PRODUCTION"):
            res = run(r, env)
            self.assertEqual(res["apply"], [], env)
            self.assertIn(f"APPROVAL_BASIS_NOT_VALID_FOR_{env}", reasons(res, 1))
        self.assertEqual(len(run([row(1, "L-1", "an.tran@" + DOM, "APPROVE")], "PRODUCTION")["apply"]), 1)

    def test_ap18_approval_basis_required(self):
        for b in ("", "OWNER_SAID_OK", "staging_temporary_bypass"):
            res = run([row(1, "L-1", "an.tran@" + DOM, "APPROVE", basis=b)])
            self.assertEqual(res["apply"], [], b)
            self.assertIn("APPROVAL_BASIS_MISSING_OR_INVALID", reasons(res, 1))

    def test_ap19_readiness_predicate(self):
        f = bp.is_identity_approved_for
        self.assertTrue(f(bp.STAGING_TEMPORARY_BYPASS, "STAGING"))
        self.assertFalse(f(bp.STAGING_TEMPORARY_BYPASS, "UAT"))
        self.assertFalse(f(bp.STAGING_TEMPORARY_BYPASS, "PRODUCTION"))
        self.assertTrue(f(bp.HR_IT_APPROVED, "PRODUCTION"))
        self.assertFalse(f("", "STAGING"))
        self.assertFalse(f(bp.HR_IT_APPROVED, "prod"))


if __name__ == "__main__":
    unittest.main()
