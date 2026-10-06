"""Reference-data (seed) tests D01-D14 (offline; synthetic rows; run: python -m unittest test_reference_data).

Set TS_SEED_RULES=<seed-rules.json> and TS_SEED_EXPECTED=<seed-expected.json> to also check the real (confidential) rules.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reference_data as rd  # noqa: E402
import schema_reconcile as sr  # noqa: E402

ALLOWED = "https://tenant-a.invalid/sites/app-staging"
RULES = {"key": "LegacyId", "code": "RateCode", "required": ["LegacyId", "RateCode", "Title", "Factor"],
         "positive": ["Factor"], "transforms": {"Factor": "nonpositive_or_null_to_1"},
         "flagIffCodeIn": [{"field": "IsNormal", "codesFromSetting": "NormalRateCode"}],
         "expectedCount": 3, "compare": ["RateCode", "Title", "Factor", "IsNormal", "SortOrder"]}
ROWS = [{"LegacyId": "g-1", "RateCode": "N", "Title": "Normal", "Factor": 1, "IsNormal": True, "SortOrder": 1},
        {"LegacyId": "g-2", "RateCode": "X1", "Title": "Extra 1", "Factor": 1.5, "IsNormal": False, "SortOrder": 2},
        {"LegacyId": "g-3", "RateCode": "X2", "Title": "Extra 2", "Factor": 0, "IsNormal": False, "SortOrder": 3}]
SETTINGS = {"NormalRateCode": "N"}
SLOT_RULES = {"key": "LegacyId", "code": "SlotCode", "exactlyOneTrue": ["IsDefault"], "firstBySortOrderIs": "IsDefault"}
SLOTS = [{"LegacyId": "s-1", "SlotCode": "A", "IsDefault": True, "SortOrder": 1},
         {"LegacyId": "s-2", "SlotCode": "B", "IsDefault": False, "SortOrder": 2}]


def schema_ok(title="Rates"):
    return [sr.Finding(sr.OK, title), sr.Finding(sr.OK, title, "RateCode")]


class FakeItems(rd.ItemClient):
    def __init__(self, items=None):
        self.items = items if items is not None else []
        self.calls = []

    def create_item(self, list_title, values):
        self.calls.append(("create_item", list_title, values["LegacyId"]))
        self.items.append(dict(values))


def load(items, rows=ROWS, rules=RULES, schema=None, dry_run=False, client=None, settings=SETTINGS):
    client = client or FakeItems(items)
    r = rd.apply_items("Rates", copy.deepcopy(rows), client.items, rules, client, ALLOWED, allowed_url=ALLOWED,
                       schema_findings=schema if schema is not None else schema_ok(), settings=settings, dry_run=dry_run)
    return r, client


class ReferenceData(unittest.TestCase):
    def test_D01_empty_list_plans_every_row(self):
        rows = rd.normalise(ROWS, RULES)
        f = rd.reconcile_items("Rates", rows, [], RULES)
        self.assertEqual([x.status for x in f], [sr.CREATE] * 3)
        self.assertEqual([k for _, k, _ in rd.plan_items(f)], ["g-1", "g-2", "g-3"])

    def test_D02_legacy_transform_nonpositive_factor_to_1(self):
        rows = rd.normalise(ROWS + [{"LegacyId": "g-4", "Factor": None}], RULES)
        self.assertEqual([r["Factor"] for r in rows], [1, 1.5, 1, 1])
        self.assertEqual(ROWS[2]["Factor"], 0, "input not mutated")

    def test_D03_load_then_second_run_is_a_no_op(self):
        r1, c = load([])
        self.assertEqual(len(r1.executed), 3)
        n = len(c.calls)
        r2, _ = load(c.items, client=c)
        self.assertEqual((r2.executed, len(c.calls)), ([], n))
        self.assertTrue(all(x.status == sr.OK for x in rd.reconcile_items("Rates", rd.normalise(ROWS, RULES), c.items, RULES)))

    def test_D04_missing_row_only_is_created(self):
        _, c = load([])
        c.items.pop(1)
        r, _ = load(c.items, client=c)
        self.assertEqual([k for _, k, _ in r.executed], ["g-2"])

    def test_D05_drift_is_reported_never_updated(self):
        _, c = load([])
        c.items[1]["Factor"] = 2.5  # someone changed a factor on the site
        f = rd.reconcile_items("Rates", rd.normalise(ROWS, RULES), c.items, RULES)
        d = next(x for x in f if x.key == "g-2")
        self.assertEqual(d.status, rd.DRIFT)
        self.assertIn("Factor site=2.5 seed=1.5", d.detail)
        n = len(c.calls)
        load(c.items, client=c)
        self.assertEqual(len(c.calls), n)
        self.assertEqual(c.items[1]["Factor"], 2.5)
        self.assertEqual(set(rd.ROLLBACK), {"create_item"}, "no update/delete operation exists")

    def test_D06_extra_item_never_deleted(self):
        _, c = load([])
        c.items.append({"LegacyId": "g-9", "RateCode": "Z", "Title": "Local"})
        f = rd.reconcile_items("Rates", rd.normalise(ROWS, RULES), c.items, RULES)
        self.assertEqual(next(x for x in f if x.key == "g-9").status, sr.EXTRA)
        load(c.items, client=c)
        self.assertIn("g-9", [i["LegacyId"] for i in c.items])

    def test_D07_code_clash_blocks_whole_load(self):
        items = [{"LegacyId": "other", "RateCode": "x1", "Title": "Clash"}]  # case-insensitive, like SharePoint
        with self.assertRaises(sr.SiteGuardError):
            load(items)
        self.assertEqual(FakeItems(items).calls, [])
        f = rd.reconcile_items("Rates", rd.normalise(ROWS, RULES), items, RULES)
        self.assertEqual(next(x for x in f if x.key == "g-2").status, sr.BLOCKED)

    def test_D08_invalid_seed_loads_nothing(self):
        bad = copy.deepcopy(ROWS)
        bad[2]["RateCode"] = "n"  # duplicate code, case-insensitive
        p = rd.validate_seed(rd.normalise(bad, RULES), RULES, SETTINGS)
        self.assertIn("unique", [x.rule for x in p])
        for rows in (bad, ROWS[:2], [dict(ROWS[0], Title="")] + ROWS[1:]):
            c = FakeItems([])
            with self.assertRaises(sr.SiteGuardError):
                load([], rows=rows, client=c)
            self.assertEqual(c.calls, [])

    def test_D09_flag_must_match_setting_and_unresolved_setting_fails_closed(self):
        self.assertEqual(rd.validate_seed(rd.normalise(ROWS, RULES), RULES, SETTINGS), [])
        wrong = copy.deepcopy(ROWS)
        wrong[1]["IsNormal"] = True
        self.assertEqual([x.rule for x in rd.validate_seed(rd.normalise(wrong, RULES), RULES, SETTINGS)], ["flagIffCodeIn"])
        for settings in ({}, {"NormalRateCode": ""}, None):
            p = rd.validate_seed(rd.normalise(ROWS, RULES), RULES, settings)
            self.assertTrue(any("unresolved" in x.detail for x in p))
            c = FakeItems([])
            with self.assertRaises(sr.SiteGuardError):
                load([], client=c, settings=settings)
            self.assertEqual(c.calls, [])

    def test_D10_default_is_exactly_one_and_first_by_sort_order(self):
        self.assertEqual(rd.validate_seed(SLOTS, SLOT_RULES), [])
        two = [dict(s, IsDefault=True) for s in SLOTS]
        self.assertIn("exactlyOneTrue", [x.rule for x in rd.validate_seed(two, SLOT_RULES)])
        moved = [dict(SLOTS[0], SortOrder=3), SLOTS[1]]
        self.assertEqual([x.rule for x in rd.validate_seed(moved, SLOT_RULES)], ["firstBySortOrderIs"])

    def test_D11_schema_must_reconcile_ok_first(self):
        for schema in ([], [sr.Finding(sr.OK, "Rates"), sr.Finding(sr.CREATE, "Rates", "Factor")],
                       [sr.Finding(sr.DECISION, "Rates", detail="R-1 open")], schema_ok("Other")):
            c = FakeItems([])
            with self.assertRaises(sr.SiteGuardError):
                load([], schema=schema, client=c)
            self.assertEqual(c.calls, [])

    def test_D12_site_guard(self):
        c = FakeItems([])
        for url in ("https://tenant-a.invalid", ALLOWED + "-other"):
            with self.assertRaises(sr.SiteGuardError):
                rd.apply_items("Rates", ROWS, [], RULES, c, url, allowed_url=ALLOWED, schema_findings=schema_ok(),
                               settings=SETTINGS, dry_run=False)
        self.assertEqual(c.calls, [])

    def test_D13_dry_run_executes_nothing(self):
        r, c = load([], dry_run=True)
        self.assertTrue(r.dry_run and len(r.skipped) == 3 and not r.executed and not c.calls)

    def test_D14_rest_item_request(self):
        calls = []

        def transport(method, path, body, headers):
            calls.append((method, path, body))
            if "ListItemEntityTypeFullName" in path:
                return 200, {"d": {"ListItemEntityTypeFullName": "SP.Data.RatesListItem"}}
            return 201, {"d": {}}
        rd.RestItemClient(transport).create_item("Rates", {"LegacyId": "g-1", "RateCode": "N"})
        post = calls[-1]
        self.assertEqual((post[0], post[1]), ("POST", "/_api/web/lists/getbytitle('Rates')/items"))
        self.assertEqual(post[2], {"__metadata": {"type": "SP.Data.RatesListItem"}, "LegacyId": "g-1", "RateCode": "N"})
        self.assertFalse(any(m in ("DELETE", "PATCH", "MERGE") for m, _, _ in calls))


@unittest.skipUnless(os.environ.get("TS_SEED_RULES") and os.environ.get("TS_SEED_EXPECTED"),
                     "set TS_SEED_RULES and TS_SEED_EXPECTED to check the real seed rules")
class RealSeedRules(unittest.TestCase):
    """The confidential seed rules agree with the documented expected codes (codes/counts only; no load)."""

    def test_rules_accept_expected_codes(self):
        with open(os.environ["TS_SEED_RULES"], encoding="utf-8") as fh:
            rules = json.load(fh)
        with open(os.environ["TS_SEED_EXPECTED"], encoding="utf-8") as fh:
            expected = json.load(fh)
        for title, spec in expected["lists"].items():
            r = rules["lists"][title]
            self.assertEqual(r["expectedCount"], len(spec["codes"]), title)
            rows = [dict({r["key"]: "k%d" % i, r["code"]: c, "SortOrder": i + 1}, **spec.get("flags", {}).get(c, {}))
                    for i, c in enumerate(spec["codes"])]
            for fname in r.get("required", []):
                for row in rows:
                    row.setdefault(fname, 1 if fname in r.get("positive", []) else "x")
            p = rd.validate_seed(rd.normalise(rows, r), r, expected.get("settings"))
            self.assertEqual(p, [], title)


if __name__ == "__main__":
    unittest.main(verbosity=2)
