"""S04.3 work-classification lists (Phases, WorkTypes, Shifts, HourTypes): target-definition and provisioning tests
W01-W10 (offline). Run with TS_TARGET_SCHEMA=<target-schema.json> (the target definition is environment configuration
and is not kept in this repository); skipped otherwise.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema_reconcile as sr  # noqa: E402
from test_schema_reconcile import ALLOWED, FakeSite, statuses  # noqa: E402

LISTS = ("Phases", "WorkTypes", "Shifts", "HourTypes")
CODE = {"Phases": "PhaseCode", "WorkTypes": "WorkTypeCode", "Shifts": "ShiftCode", "HourTypes": "HourTypeCode"}
EXTRA_COLS = {"Phases": {"Remark": "Note", "IsAbsenceBucket": "Boolean", "IsActive": "Boolean"},
              "WorkTypes": {"Remark": "Note", "IsActive": "Boolean"},
              "Shifts": {"TimeWindow": "Text", "IsDefault": "Boolean", "IsActive": "Boolean"},
              "HourTypes": {"Factor": "Number", "IsNormalHours": "Boolean", "RuleText": "Note"}}
STD = {"LegacyId": "Text", "LegacyModifiedOn": "DateTime", "MigrationBatch": "Text", "IsLegacyPlaceholder": "Boolean", "SortOrder": "Number"}


@unittest.skipUnless(os.environ.get("TS_TARGET_SCHEMA"), "set TS_TARGET_SCHEMA to check the real S04.3 target definition")
class WorkClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8") as fh:
            cls.full = json.load(fh)
        cls.target = {"lists": [copy.deepcopy(l) for l in cls.full["lists"] if l["title"] in LISTS]}

    def _decided(self, n1="<X>Code"):
        """The S04.3 target with the story gate opened (R04-N1 is resolved: <X>Code, 2026-10-07).
        Field gates (e.g. the confidential LegacyModifiedBy) stay closed."""
        t = copy.deepcopy(self.target)
        for l in t["lists"]:
            l.pop("gate", None)
            for f in l["fields"]:
                if f["internalName"] == CODE[l["title"]] and n1 == "<X>Code":
                    f.pop("decision", None)
        return t

    def _fields(self, title, t=None):
        return {f["internalName"]: f for f in next(l for l in (t or self.target)["lists"] if l["title"] == title)["fields"]}

    def test_W01_exact_columns_types_and_flags(self):
        for t in LISTS:
            fl = self._fields(t)
            want = dict(STD, **EXTRA_COLS[t], **{CODE[t]: "Text", "Title": "Text"})
            want.pop("LegacyModifiedBy", None)
            got = {n: f["type"] for n, f in fl.items() if not f.get("gate", "").startswith("CONFIDENTIAL")}
            self.assertEqual(got, want, t)
            c = fl[CODE[t]]
            self.assertEqual((c["required"], c["indexed"], c["unique"]), (True, True, True), t)
            lid = fl["LegacyId"]
            self.assertEqual((lid["required"], lid["indexed"], lid["unique"]), (True, True, True), t)
            self.assertIn("ENV-D2", fl["LegacyModifiedBy"]["gate"], "LegacyModifiedBy stays confidential")
            self.assertEqual(sum(1 for f in fl.values() if f.get("indexed")), 2, "spec 6.2 indexes: LegacyId + code")
        self.assertNotIn("IsActive", self._fields("HourTypes"), "HourTypes has no IsActive in spec 6.2 or target model 4.3")
        factor = self._fields("HourTypes")["Factor"]
        self.assertEqual((factor["required"], factor["decimals"], factor["validationFormula"]), (True, 2, "=[Factor]>0"))
        self.assertIn("<Validation>=[Factor]&gt;0</Validation>", sr.field_schema_xml(factor))
        self.assertFalse({"ApprovalStatus", "IsDeleted"} & {n for t in LISTS for n in self._fields(t)})

    def test_W02_r04_n1_resolved_and_only_the_story_gate_holds_the_lists(self):
        for t in LISTS:
            fl = self._fields(t)
            self.assertFalse([n for n, f in fl.items() if f.get("decision")], "no open decision on any S04.3 column (R04-N1, R04-N3 resolved)")
            self.assertNotIn("Code", fl, "never a generic Code column (R04-N1)")
            self.assertEqual(sorted(n for n in fl if n.endswith("Code")), [CODE[t]])
        f = sr.reconcile(self.target, {"site": ALLOWED, "lists": []})
        s = statuses(f)
        for t in LISTS:
            self.assertEqual(s[(t, "")], sr.GATED, t)  # S04.3 live provisioning still needs the owner go
        self.assertEqual(sr.plan(f), [])
        site = FakeSite({"site": ALLOWED, "lists": []})
        sr.apply(self.target, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual(site.calls, [])

    def test_W03_story_gate_alone_also_blocks(self):
        t = self._decided()
        for l in t["lists"]:
            l["gate"] = "S04.3 live provisioning"
        self.assertEqual(sr.plan(sr.reconcile(t, {"site": ALLOWED, "lists": []})), [])

    def test_W04_empty_target_after_decision_creates_exact_plan(self):
        f = sr.reconcile(self._decided(), {"site": ALLOWED, "lists": []})
        ops = sr.plan(f)
        self.assertEqual([o[0] for o in ops if o[2][0] == "create_list"], list(LISTS))
        for t in LISTS:
            created = sorted(n for l, n, op in ops if l == t and op[0] == "create_field")
            want = sorted(set(STD) | set(EXTRA_COLS[t]) | {CODE[t]})
            self.assertEqual(created, want, t)
        self.assertNotIn("LegacyModifiedBy", {n for _, n, _ in ops})
        self.assertTrue(all(op[0] in sr.ROLLBACK for _, _, op in ops))

    def test_W05_apply_then_second_run_is_a_no_op(self):
        t = self._decided()
        site = FakeSite({"site": ALLOWED, "lists": []})
        r1 = sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual(sum(1 for x in r1.executed if x[2] == "create_list"), 4)
        after = sr.reconcile(t, site.actual)
        self.assertEqual({x.status for x in after} - {sr.OK, sr.GATED, sr.DECISION}, set())
        self.assertEqual(sr.plan(after), [])
        n = len(site.calls)
        self.assertEqual(sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False).executed, [])
        self.assertEqual(len(site.calls), n)

    def test_W06_missing_field_is_recreated_only(self):
        t = self._decided()
        site = FakeSite({"site": ALLOWED, "lists": []})
        sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        ht = next(l for l in site.actual["lists"] if l["title"] == "HourTypes")
        ht["fields"] = [x for x in ht["fields"] if x["internalName"] != "IsNormalHours"]
        self.assertEqual([(l, n, o[0]) for l, n, o in sr.plan(sr.reconcile(t, site.actual))],
                         [("HourTypes", "IsNormalHours", "create_field")])

    def test_W07_wrong_type_or_lost_uniqueness(self):
        t = self._decided()
        site = FakeSite({"site": ALLOWED, "lists": []})
        sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        a = copy.deepcopy(site.actual)
        sh = {x["internalName"]: x for x in next(l for l in a["lists"] if l["title"] == "Shifts")["fields"]}
        sh["ShiftCode"]["unique"] = False
        f = sr.reconcile(t, a)
        code = next(x for x in f if x.list == "Shifts" and x.field == "ShiftCode")
        self.assertEqual(code.status, sr.UPDATE_SAFE)
        self.assertIn("precondition: no duplicate values", code.detail)
        next(x for x in next(l for l in a["lists"] if l["title"] == "HourTypes")["fields"] if x["internalName"] == "Factor")["type"] = "Text"
        self.assertEqual(statuses(sr.reconcile(t, a))[("HourTypes", "Factor")], sr.BLOCKED)

    def test_W08_incompatible_drift_stops_the_whole_run(self):
        t = self._decided()
        site = FakeSite({"site": ALLOWED, "lists": []})
        sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        next(x for x in next(l for l in site.actual["lists"] if l["title"] == "Phases")["fields"]
             if x["internalName"] == "IsAbsenceBucket")["type"] = "Text"
        site.actual["lists"] = [l for l in site.actual["lists"] if l["title"] != "WorkTypes"]  # something else to do
        n = len(site.calls)
        with self.assertRaises(sr.SiteGuardError):
            sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual(len(site.calls), n, "nothing executed, not even the unrelated missing list")

    def test_W09_no_destructive_auto_fix(self):
        t = self._decided()
        site = FakeSite({"site": ALLOWED, "lists": []})
        sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        ph = next(l for l in site.actual["lists"] if l["title"] == "Phases")
        ph["fields"].append({"internalName": "Code", "displayName": "Code", "type": "Text", "required": True,
                             "indexed": True, "unique": True, "builtIn": False})
        ph["itemCount"] = 13
        f = sr.reconcile(t, site.actual)
        self.assertEqual(statuses(f)[("Phases", "Code")], sr.EXTRA)
        self.assertEqual(sr.plan(f), [])
        self.assertFalse(set(sr.ROLLBACK) & {"delete_list", "delete_field", "rename_field", "change_type"})

    def test_W10_a_reopened_key_decision_would_block_the_lists_again(self):
        """Safety mechanism kept: an open decision on a key column blocks creating the list (no partial list)."""
        t = self._decided()
        for l in t["lists"]:
            next(f for f in l["fields"] if f["internalName"] == CODE[l["title"]]).update(decision="reopened", decisionBlocksList=True)
        f = sr.reconcile(t, {"site": ALLOWED, "lists": []})
        self.assertTrue(all(statuses(f)[(x, "")] == sr.DECISION for x in LISTS))
        self.assertEqual(sr.plan(f), [])


@unittest.skipUnless(os.environ.get("TS_TARGET_SCHEMA") and os.environ.get("TS_ASBUILT_LIVE"),
                     "set TS_TARGET_SCHEMA and TS_ASBUILT_LIVE (inventory after the S04.3/S04.7 live run)")
class PostLive(unittest.TestCase):
    """L01-L03: the live STAGING schema equals the S04.3/S04.7 target; a second run plans nothing."""

    @classmethod
    def setUpClass(cls):
        with open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8") as fh:
            cls.full = json.load(fh)
        with open(os.environ["TS_ASBUILT_LIVE"], encoding="utf-8") as fh:
            cls.inv = json.load(fh)

    def _opened(self, titles):
        t = {"lists": [copy.deepcopy(l) for l in self.full["lists"] if l["title"] in titles]}
        for l in t["lists"]:
            l.pop("gate", None)
        return t

    def test_L01_s043_lists_reconcile_ok_except_the_confidential_gate(self):
        f = sr.reconcile(self._opened(LISTS), self.inv)
        bad = [x.line() for x in f if x.list in LISTS and not (x.status == sr.OK or (x.status == sr.GATED and x.field == "LegacyModifiedBy"))]
        self.assertEqual(bad, [])
        self.assertEqual(sr.plan(f), [])
        for t in LISTS:
            l = next(x for x in self.inv["lists"] if x["title"] == t)
            self.assertEqual(l["itemCount"], 0, "schema only: no business rows")

    def test_L02_appsettings_reconciles_ok(self):
        f = [x for x in sr.reconcile(self._opened(["AppSettings"]), self.inv) if x.list == "AppSettings"]
        self.assertTrue(f and all(x.status == sr.OK for x in f), [x.line() for x in f])

    def test_L03_full_target_no_blocked_and_no_plan(self):
        f = sr.reconcile(self.full, self.inv)
        self.assertFalse([x for x in f if x.status == sr.BLOCKED])
        self.assertEqual(sr.plan(f), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
