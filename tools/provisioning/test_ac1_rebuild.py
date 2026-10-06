"""Empty-site rebuild simulation R01-R06 (offline evidence towards "the template re-creates every list idempotently in an
empty site"). An in-memory SharePoint (FakeSite, which refuses a lookup to a missing list) stands in for the empty site.
This is NOT live proof: it validates the plan, ordering, idempotence and recovery, not SharePoint itself.

Run: python -m unittest test_ac1_rebuild. Set TS_TARGET_SCHEMA (and TS_ASBUILT) to rebuild the real target definition.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema_reconcile as sr  # noqa: E402
from test_schema_reconcile import ALLOWED, TARGET, FakeSite, F  # noqa: E402


def opened(target, keep_field_gates=("CONFIDENTIAL",)):
    """Every story gate opened and every decision taken as drafted; field gates of a kept class stay closed."""
    t = copy.deepcopy(target)
    for l in t["lists"]:
        l.pop("gate", None)
        l.pop("decision", None)
        for f in l["fields"]:
            f.pop("decision", None)
            if f.get("gate") and not any(f["gate"].startswith(k) for k in keep_field_gates):
                f.pop("gate")
    return t


class FlakySite(FakeSite):
    """Fails once on the n-th mutation (throttling, network), like a live run interrupted half-way."""
    def __init__(self, actual, fail_at):
        super().__init__(actual)
        self.n, self.fail_at = 0, fail_at

    def _tick(self):
        self.n += 1
        if self.n == self.fail_at:
            raise RuntimeError("simulated transient failure")

    def create_list(self, spec):
        self._tick()
        super().create_list(spec)

    def create_field(self, lst, spec):
        self._tick()
        super().create_field(lst, spec)

    def update_field(self, lst, name, op, value):
        self._tick()
        super().update_field(lst, name, op, value)


def rebuild(target):
    site = FakeSite({"site": ALLOWED, "lists": []})
    r = sr.apply(target, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
    return site, r


def comparable(inv, title, skip=()):
    l = next(x for x in inv["lists"] if x["title"] == title)
    keys = ("type", "required", "indexed", "unique", "lookupList", "dateOnly")
    # lookupList is compared for Lookup columns only (User columns point at the hidden user list)
    return {f["internalName"]: tuple(f.get(k) if k != "lookupList" or f.get("type") == "Lookup" else None for k in keys)
            for f in l["fields"]
            if f["internalName"] not in skip and not (f["internalName"] == "Title" and f.get("builtIn"))}


class Rebuild(unittest.TestCase):
    """Synthetic target (always runs)."""
    T = {"lists": [  # deliberately ordered child-before-parent
        {"title": "Entries", "template": 100, "fields": [F("Title", "Text"), F("LegacyId", "Text", True, True, True),
                                                         F("Unit", "Lookup", True, True, lookupList="Units")]},
        {"title": "Units", "template": 100, "fields": [F("Title", "Text", True), F("UnitCode", "Text", True, True, True)]}]}

    def test_R01_child_before_parent_still_builds(self):
        site, r = rebuild(self.T)
        kinds = [x[2] for x in r.executed]
        self.assertEqual(kinds[:2], ["create_list", "create_list"], "all lists first")
        self.assertEqual(sr.plan(sr.reconcile(self.T, site.actual)), [])

    def test_R02_interrupted_run_recovers_on_rerun(self):
        clean, _ = rebuild(self.T)
        total = len(sr.plan(sr.reconcile(self.T, {"lists": []})))
        for k in range(1, total + 1):
            site = FlakySite({"site": ALLOWED, "lists": []}, fail_at=k)
            with self.assertRaises(RuntimeError):
                sr.apply(self.T, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
            sr.apply(self.T, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)  # re-run from the new inventory
            self.assertEqual(sr.plan(sr.reconcile(self.T, site.actual)), [], "failure at op %d" % k)
            for t in ("Entries", "Units"):
                self.assertEqual(comparable(site.actual, t), comparable(clean.actual, t), (k, t))

    def test_R03_lookup_to_list_that_is_not_built_is_not_attempted(self):
        t = copy.deepcopy(self.T)
        t["lists"][1]["gate"] = "later story"
        site, r = rebuild(t)
        self.assertNotIn(("Entries", "Unit", "create_field"), r.executed)
        self.assertEqual(sr.summary(sr.reconcile(t, site.actual)).get(sr.CREATE, 0), 0)

    def test_R04_dry_run_plan_equals_executed_plan(self):
        dry = sr.apply(self.T, {"lists": []}, FakeSite({"lists": []}), ALLOWED, allowed_url=ALLOWED)
        _, live = rebuild(self.T)
        self.assertEqual([(l, n, o[0]) for l, n, o in dry.skipped], live.executed)


@unittest.skipUnless(os.environ.get("TS_TARGET_SCHEMA"), "set TS_TARGET_SCHEMA to rebuild the real target definition")
class RealTargetRebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8") as fh:
            cls.target = opened(json.load(fh))
        cls.site, cls.result = rebuild(cls.target)

    def test_R05_every_list_rebuilt_idempotently(self):
        titles = [l["title"] for l in self.target["lists"]]
        self.assertEqual(sorted(l["title"] for l in self.site.actual["lists"]), sorted(titles))
        f = sr.reconcile(self.target, self.site.actual)
        self.assertEqual({x.status for x in f} - {sr.OK, sr.GATED}, set(), [x.line() for x in f if x.status not in (sr.OK, sr.GATED)])
        self.assertTrue(all(x.field for x in f if x.status == sr.GATED), "only confidential field gates remain")
        self.assertTrue(all("CONFIDENTIAL" in x.detail for x in f if x.status == sr.GATED))
        n = len(self.site.calls)
        self.assertEqual(sr.apply(self.target, self.site.actual, self.site, ALLOWED, allowed_url=ALLOWED, dry_run=False).executed, [])
        self.assertEqual(len(self.site.calls), n)
        self.assertTrue(all(op in sr.ROLLBACK for _, _, op in self.result.executed))

    @unittest.skipUnless(os.environ.get("TS_ASBUILT"), "set TS_ASBUILT to compare with the as-built site")
    def test_R06_rebuilt_existing_lists_equal_the_as_built_lists(self):
        with open(os.environ["TS_ASBUILT"], encoding="utf-8") as fh:
            asbuilt = json.load(fh)
        built = [l["title"] for l in asbuilt["lists"] if not l.get("system") and not l["title"].startswith("_")]
        self.assertTrue(built)
        for t in built:
            if not any(l["title"] == t for l in self.target["lists"]):
                continue
            gated = {f["internalName"] for f in next(l for l in self.target["lists"] if l["title"] == t)["fields"] if f.get("gate")}
            extra = {f["internalName"] for f in next(l for l in asbuilt["lists"] if l["title"] == t)["fields"]
                     if f.get("builtIn")}
            a = comparable(asbuilt, t, skip=gated | extra)
            b = comparable(self.site.actual, t, skip=gated | extra)
            self.assertTrue(set(a) <= set(b), (t, set(a) - set(b)))  # rebuilt may add not-yet-live target columns
            for name in a:
                self.assertIn(name, b, (t, name))
                self.assertEqual(a[name][:5], b[name][:5], (t, name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
