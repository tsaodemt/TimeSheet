"""EMPLOYEE-IDENTITY-MAPPING-01 matcher tests EM01-EM23 (synthetic data only; run: python -m unittest)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from employee_matching import (  # noqa: E402
    ALREADY_MAPPED_DUPLICATE, ALREADY_MAPPED_INVALID, ALREADY_MAPPED_VALID, AMBIGUOUS, AUTO_MATCH_SAFE, EXCLUDED_DEMO,
    GUEST, INACTIVE_EMPLOYEE, MEMBER_DISABLED, MEMBER_ENABLED, NEEDS_REVIEW, NO_ACCOUNT, SERVICE_TEST, Account, Config,
    Employee, classify_account, fold, legacy_consistent, match, normalize, review_sort_key, safe_violations,
    vn_upn_local)

DOM = "tenant-a.invalid"
CFG = Config(org_domains=[DOM], excluded_upns=["named-svc@" + DOM])


def acct(i, upn, name, kind="Member", enabled=True, **kw):
    return Account(f"id-{i}", upn if "@" in upn else f"{upn}@{DOM}", name, kind, enabled, **kw)


def emp(i, name, active=True, user="", **kw):
    return Employee(i, f"L-{i:03d}", name, active, legacy_user_name=user, batch=kw.pop("batch", "RUN1"), **kw)


def by_id(res, i):
    return next(r for r in res["rows"] if r["itemId"] == i)


class Normalisation(unittest.TestCase):
    def test_em01_normalize_keeps_accents_fold_removes(self):
        self.assertEqual(normalize("  Trần   Văn  An "), "trần văn an")
        self.assertEqual(fold("Đặng Thị Ánh"), "dang thi anh")
        self.assertNotEqual(normalize("Lê An"), normalize("Le An"))
        self.assertEqual(fold("Lê An"), fold("Le An"))

    def test_em02_pattern_and_legacy_helpers(self):
        self.assertEqual(vn_upn_local("Trần Văn An"), "an.tran")
        self.assertTrue(legacy_consistent("Trần Văn An", "an.tv"))
        self.assertFalse(legacy_consistent("Trần Văn An", "an,tv"))
        self.assertFalse(legacy_consistent("Trần Văn An", "binh.tv"))


class Directory(unittest.TestCase):
    def test_em03_account_kinds(self):
        self.assertEqual(classify_account(acct(1, "x_ext.com#EXT#@t.onmicrosoft.invalid", "X", "Guest"), CFG), GUEST)
        self.assertEqual(classify_account(acct(2, "named-svc", "Svc"), CFG), SERVICE_TEST)
        self.assertEqual(classify_account(acct(3, "admin", "Admin"), CFG), SERVICE_TEST)
        self.assertEqual(classify_account(acct(4, "user@other.invalid", "Foreign"), CFG), SERVICE_TEST)
        self.assertEqual(classify_account(acct(5, "an.tran", "Tran Van An", enabled=False), CFG), MEMBER_DISABLED)
        self.assertEqual(classify_account(acct(6, "an.tran", "Tran Van An"), CFG), MEMBER_ENABLED)
        self.assertEqual(classify_account(acct(7, "kiet.vo", "Vo Kiet"), CFG), MEMBER_ENABLED)   # 'it' inside a word


class Classification(unittest.TestCase):
    def test_em04_demo_excluded(self):
        res = match([emp(1, "DEMO Employee", batch="DEMO_ONLY", account_upn="demo@" + DOM)], [], CFG)
        self.assertEqual(by_id(res, 1)["classification"], EXCLUDED_DEMO)
        self.assertEqual(res["summary"]["realEmployees"], 0)

    def test_em04b_unbatched_test_row_excluded(self):
        cfg = Config(org_domains=[DOM], real_batches=["RUN1"])
        res = match([emp(1, "it", batch=""), emp(2, "Trần Văn An")], [], cfg)
        self.assertEqual((by_id(res, 1)["classification"], by_id(res, 1)["reasons"]), (EXCLUDED_DEMO, ["UNBATCHED_TEST_ROW"]))
        self.assertEqual(res["summary"]["realEmployees"], 1)

    def test_em05_name_only_never_safe(self):
        res = match([emp(1, "Trần Văn An", user="an.tv")], [acct(1, "an.tran", "Trần Văn An")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], NEEDS_REVIEW)
        self.assertEqual(r["confidence"], "HIGH")
        self.assertIn("NAME_ONLY", r["reasons"])

    def test_em06_folded_and_reordered_candidates(self):
        res = match([emp(1, "Trần Văn An", user="an.tv"), emp(2, "Lê Bình", user="binh.l")],
                    [acct(1, "an.tran", "Tran Van An"), acct(2, "binh.le", "Binh Le")], CFG)
        self.assertIn("FOLDED_NAME", by_id(res, 1)["candidate"]["evidence"])
        self.assertIn("REORDERED_NAME", by_id(res, 2)["candidate"]["evidence"])
        self.assertTrue(all(by_id(res, i)["classification"] == NEEDS_REVIEW for i in (1, 2)))

    def test_em07_deterministic_identifier_is_safe(self):
        res = match([emp(1, "Trần Văn An", employee_code="E-1")], [acct(1, "an.tran", "Tran Van An", employee_id="E-1")],
                    CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], AUTO_MATCH_SAFE)
        self.assertIn("EXACT_EMPLOYEE_ID", r["reasons"])
        self.assertEqual(safe_violations(r), [])

    def test_em08_exact_legacy_username_safe_only_when_unique(self):
        res = match([emp(1, "Trần Văn An", user="an.tran")], [acct(1, "an.tran", "Somebody Else")], CFG)
        self.assertEqual(by_id(res, 1)["classification"], AUTO_MATCH_SAFE)
        res = match([emp(1, "Trần Văn An", user="an.tran")],
                    [acct(1, "an.tran", "Somebody Else"), acct(2, "an.tran2", "Trần Văn An")], CFG)
        self.assertEqual(by_id(res, 1)["classification"], AMBIGUOUS)

    def test_em09_disabled_never_safe(self):
        res = match([emp(1, "Trần Văn An", employee_code="E-1")],
                    [acct(1, "an.tran", "Tran Van An", enabled=False, employee_id="E-1")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], NEEDS_REVIEW)
        self.assertIn("DIRECTORY_ACCOUNT_DISABLED", r["reasons"])

    def test_em10_guest_only_never_safe(self):
        res = match([emp(1, "Trần Văn An", employee_code="E-1")],
                    [acct(1, "an_x.com#EXT#@t.onmicrosoft.invalid", "Trần Văn An", "Guest", employee_id="E-1")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], NEEDS_REVIEW)
        self.assertIn("GUEST_ACCOUNT_ONLY", r["reasons"])

    def test_em11_service_account_conflict(self):
        res = match([emp(1, "Named Svc")], [acct(1, "named-svc", "Named Svc")], CFG)
        r = by_id(res, 1)
        self.assertNotEqual(r["classification"], AUTO_MATCH_SAFE)
        self.assertIn("SERVICE_ACCOUNT_CONFLICT", r["reasons"])

    def test_em12_multiple_directory_candidates_ambiguous(self):
        res = match([emp(1, "Trần Văn An", user="an.tv")],
                    [acct(1, "an.tran", "Tran Van An"), acct(2, "an.tran1", "Trần Văn An")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], AMBIGUOUS)
        self.assertIsNone(r["candidate"])             # never picks the "closest" one
        self.assertIn(1, res["conflicts"]["multipleCandidateCases"])

    def test_em13_duplicate_employee_names_ambiguous(self):
        res = match([emp(1, "Trần Văn An"), emp(2, "Tran Van An")], [acct(1, "an.tran", "Tran Van An")], CFG)
        self.assertTrue(all(by_id(res, i)["classification"] == AMBIGUOUS for i in (1, 2)))
        self.assertEqual(len(res["conflicts"]["duplicateEmployeeNames"]), 1)

    def test_em14_duplicate_directory_names_detected(self):
        res = match([], [acct(1, "an.tran", "Tran Van An"), acct(2, "an.tran.x", "Trần Văn An")], CFG)
        self.assertEqual(len(res["conflicts"]["duplicateDirectoryNames"]), 1)

    def test_em15_inactive_not_onboarded(self):
        res = match([emp(1, "Trần Văn An", active=False, employee_code="E-1")],
                    [acct(1, "an.tran", "Tran Van An", employee_id="E-1")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], INACTIVE_EMPLOYEE)
        self.assertEqual(r["candidate"]["objectId"], "id-1")    # kept privately for analysis

    def test_em16_no_account(self):
        res = match([emp(1, "Trần Văn An")], [acct(1, "binh.le", "Le Binh")], CFG)
        self.assertEqual(by_id(res, 1)["classification"], NO_ACCOUNT)

    def test_em17_upn_pattern_only_is_low_review(self):
        res = match([emp(1, "Trần Văn An")], [acct(1, "an.tran", "Mr A")], CFG)
        r = by_id(res, 1)
        self.assertEqual((r["classification"], r["confidence"]), (NEEDS_REVIEW, "LOW"))
        self.assertIn("UPN_PATTERN_ONLY", r["reasons"])

    def test_em18_proposed_upn_collision(self):
        # Two employees whose strong evidence lands on the same account.
        res = match([emp(1, "Trần Văn An", employee_code="E-1"), emp(2, "Lê Văn Bình", user="an.tran")],
                    [acct(1, "an.tran", "Somebody", employee_id="E-1")], CFG)
        self.assertTrue(all(by_id(res, i)["classification"] == AMBIGUOUS for i in (1, 2)))
        self.assertIn(normalize("an.tran@" + DOM), res["conflicts"]["proposedUpnCollisions"])

    def test_em19_existing_accountupn_states(self):
        emps = [emp(1, "Trần Văn An", account_upn="an.tran@" + DOM), emp(2, "Lê Bình", account_upn="gone@" + DOM),
                emp(3, "Võ C", account_upn="dup@" + DOM), emp(4, "Võ D", account_upn="dup@" + DOM)]
        res = match(emps, [acct(1, "an.tran", "Tran Van An"), acct(2, "dup", "Dup")], CFG)
        self.assertEqual(by_id(res, 1)["mappedState"], ALREADY_MAPPED_VALID)
        self.assertEqual(by_id(res, 2)["mappedState"], ALREADY_MAPPED_INVALID)
        self.assertEqual(by_id(res, 3)["mappedState"], ALREADY_MAPPED_DUPLICATE)
        self.assertTrue(all(by_id(res, i)["classification"] != AUTO_MATCH_SAFE for i in (1, 2, 3, 4)))

    def test_em20_existing_mapping_conflict_and_sort(self):
        emps = [emp(1, "DEMO Employee", batch="DEMO_ONLY", account_upn="an.tran@" + DOM),
                emp(2, "Trần Văn An", user="an.tv"), emp(3, "Zed Q"), emp(4, "Ánh B", active=False)]
        res = match(emps, [acct(1, "an.tran", "Tran Van An")], CFG)
        r = by_id(res, 2)
        self.assertEqual(r["classification"], AMBIGUOUS)
        self.assertIn("EXISTING_MAPPING_CONFLICT", r["reasons"])
        order = [x["itemId"] for x in sorted(res["rows"], key=review_sort_key)]
        self.assertEqual(order, [2, 3, 4, 1])

    def test_em21_near_duplicate_directory_name_ambiguous(self):
        res = match([emp(1, "Đỗ Quốc Bảo", user="bao.dq")],
                    [acct(1, "bao.do", "Do Quoc Bao"), acct(2, "bao.do2", "Do Tan Bao")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], AMBIGUOUS)
        self.assertIn("NEAR_DUPLICATE_DIRECTORY_NAME", r["reasons"])
        self.assertIsNone(r["candidate"])

    def test_em22_given_family_only_is_low_review(self):
        res = match([emp(1, "Hà Văn Minh Sơn", user="son.hvm")], [acct(1, "son.ha", "Ha Son")], CFG)
        r = by_id(res, 1)
        self.assertEqual((r["classification"], r["confidence"]), (NEEDS_REVIEW, "LOW"))
        self.assertIn("GIVEN_FAMILY_ONLY", r["reasons"])
        self.assertIn("NO_STRONG_DETERMINISTIC_EVIDENCE", safe_violations(r))

    def test_em23_inactive_with_enabled_account_flagged(self):
        res = match([emp(1, "Trần Văn An", active=False)], [acct(1, "an.tran", "Tran Van An")], CFG)
        r = by_id(res, 1)
        self.assertEqual(r["classification"], INACTIVE_EMPLOYEE)
        self.assertIn("INACTIVE_WITH_ENABLED_ACCOUNT", r["evidence"])


if __name__ == "__main__":
    unittest.main()
