"""Provisioning/reconciliation tests P01-P14 (offline; synthetic schema; run: python -m unittest test_schema_reconcile).

Set TS_TARGET_SCHEMA=<target-schema.json> to also check the real (confidential) target definition (P12/P13 extras).
"""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema_reconcile as sr  # noqa: E402

ALLOWED = "https://tenant-a.invalid/sites/app-staging"
MAIN = "https://tenant-a.invalid"
F = lambda n, t, req=False, idx=False, uq=False, **k: dict(internalName=n, displayName=n, type=t, required=req, indexed=idx, unique=uq, **k)
TARGET = {"businessTimeZone": {"iana": "Asia/Ho_Chi_Minh", "utcOffsetMinutes": 420, "dst": False}, "lists": [
    {"title": "Units", "template": 100, "fields": [F("Title", "Text", True), F("LegacyId", "Text", True, True, True),
                                                   F("UnitCode", "Text", True, True, True), F("IsActive", "Boolean", True, True)]},
    {"title": "Entries", "template": 100, "fields": [
        F("Title", "Text"), F("LegacyId", "Text", True, True, True), F("Unit", "Lookup", True, True, lookupList="Units"),
        F("OwnerUpn", "Text", True, True), F("WorkDate", "DateTime", True, True, dateOnly=True),
        F("Hours", "Number", True, decimals=2, validationFormula="=AND([Hours]>0,[Hours]<=24)"),
        F("Status", "Choice", True, True, choices=["Draft", "Approved"])]},
]}


def actual_from(target):
    """An inventory that exactly matches the target (what a correct site looks like)."""
    lists = []
    for l in target["lists"]:
        fields = [dict(f, builtIn=f["internalName"] == "Title") for f in copy.deepcopy(l["fields"])]
        lists.append({"title": l["title"], "itemCount": 0, "system": False, "fields": fields})
    return {"site": ALLOWED, "lists": lists}


class FakeSite(sr.SchemaClient):
    """In-memory SharePoint: mutates an inventory exactly as the REST client would."""
    def __init__(self, actual):
        self.actual = actual
        self.calls = []

    def _list(self, t):
        return next(l for l in self.actual["lists"] if l["title"] == t)

    def create_list(self, spec):
        self.calls.append(("create_list", spec["title"]))
        title = next((f for f in spec["fields"] if f["internalName"] == "Title"), {"required": True})
        self.actual["lists"].append({"title": spec["title"], "itemCount": 0, "system": False,
                                     "fields": [dict(F("Title", "Text", bool(title.get("required"))), builtIn=True)]})

    def create_field(self, lst, spec):
        self.calls.append(("create_field", lst, spec["internalName"]))
        self._list(lst)["fields"].append(dict(copy.deepcopy(spec), builtIn=False))

    def update_field(self, lst, name, op, value):
        self.calls.append((op, lst, name))
        f = next(x for x in self._list(lst)["fields"] if x["internalName"] == name)
        key = {"set_indexed": "indexed", "set_unique": "unique", "set_required": "required", "set_display_name": "displayName"}.get(op)
        if key:
            f[key] = value
            if op == "set_unique":
                f["indexed"] = True
        elif op == "add_choices":
            f["choices"] = (f.get("choices") or []) + [c for c in value if c not in (f.get("choices") or [])]


def statuses(findings):
    return {(f.list, f.field): f.status for f in findings}


class Provisioning(unittest.TestCase):
    def test_P01_empty_target_site_gives_create_plan(self):
        f = sr.reconcile(TARGET, {"site": ALLOWED, "lists": []})
        s = statuses(f)
        self.assertEqual(s[("Units", "")], sr.CREATE)
        self.assertEqual(s[("Entries", "WorkDate")], sr.CREATE)
        ops = [o[2][0] for o in sr.plan(f)]
        self.assertEqual(ops.count("create_list"), 2)
        self.assertEqual(sum(1 for o in ops if o == "create_field"), 9)

    def test_P02_correct_site_is_a_no_op(self):
        f = sr.reconcile(TARGET, actual_from(TARGET))
        self.assertEqual(set(sr.summary(f)), {sr.OK})
        self.assertEqual(sr.plan(f), [])

    def test_P03_missing_list(self):
        a = actual_from(TARGET)
        a["lists"] = [l for l in a["lists"] if l["title"] != "Entries"]
        f = sr.reconcile(TARGET, a)
        self.assertEqual(statuses(f)[("Entries", "")], sr.CREATE)
        self.assertEqual(sr.plan(f)[0][2][0], "create_list")

    def test_P04_missing_column(self):
        a = actual_from(TARGET)
        a["lists"][1]["fields"] = [x for x in a["lists"][1]["fields"] if x["internalName"] != "OwnerUpn"]
        f = sr.reconcile(TARGET, a)
        self.assertEqual(statuses(f)[("Entries", "OwnerUpn")], sr.CREATE)
        self.assertEqual([(l, n, o[0]) for l, n, o in sr.plan(f)], [("Entries", "OwnerUpn", "create_field")])

    def test_P05_wrong_type_or_date_kind_or_lookup_blocks(self):
        for mutate, why in ((lambda x: x.update(type="Text"), "type"), (lambda x: x.update(dateOnly=False), "dateOnly")):
            a = actual_from(TARGET)
            mutate(next(x for x in a["lists"][1]["fields"] if x["internalName"] == "WorkDate"))
            f = sr.reconcile(TARGET, a)
            self.assertEqual(statuses(f)[("Entries", "WorkDate")], sr.BLOCKED, why)
            with self.assertRaises(sr.SiteGuardError):
                sr.apply(TARGET, a, FakeSite(a), ALLOWED, allowed_url=ALLOWED, dry_run=False)
        a = actual_from(TARGET)
        next(x for x in a["lists"][1]["fields"] if x["internalName"] == "Unit")["lookupList"] = "Other"
        self.assertEqual(statuses(sr.reconcile(TARGET, a))[("Entries", "Unit")], sr.BLOCKED)

    def test_P06_wrong_required_or_index_config_is_update_safe(self):
        a = actual_from(TARGET)
        fl = {x["internalName"]: x for x in a["lists"][1]["fields"]}
        fl["Hours"]["required"] = False
        fl["Status"]["choices"] = ["Draft"]
        f = sr.reconcile(TARGET, a)
        self.assertEqual(statuses(f)[("Entries", "Hours")], sr.UPDATE_SAFE)
        self.assertEqual(statuses(f)[("Entries", "Status")], sr.UPDATE_SAFE)
        fl["LegacyId"]["unique"] = False
        f = sr.reconcile(TARGET, a)
        lid = next(x for x in f if x.field == "LegacyId" and x.list == "Entries")
        self.assertEqual(lid.status, sr.UPDATE_SAFE)
        self.assertIn("precondition: no duplicate values", lid.detail)

    def test_P07_missing_index(self):
        a = actual_from(TARGET)
        for x in a["lists"][1]["fields"]:
            if x["internalName"] in ("OwnerUpn", "WorkDate"):
                x["indexed"] = False
        f = sr.reconcile(TARGET, a)
        ops = [(n, o[0]) for _, n, o in sr.plan(f)]
        self.assertEqual(sorted(ops), [("OwnerUpn", "set_indexed"), ("WorkDate", "set_indexed")])

    def test_P08_second_run_is_a_no_op(self):
        a = {"site": ALLOWED, "lists": []}
        site = FakeSite(a)
        r1 = sr.apply(TARGET, a, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertTrue(r1.executed)
        self.assertEqual(set(sr.summary(sr.reconcile(TARGET, site.actual))), {sr.OK})
        n = len(site.calls)
        r2 = sr.apply(TARGET, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual((r2.executed, len(site.calls)), ([], n))

    def test_P09_unresolved_decision_or_gate_blocks_mutation(self):
        t = copy.deepcopy(TARGET)
        st = next(x for x in t["lists"][1]["fields"] if x["internalName"] == "Status")
        st["decision"] = "Q-1 open"
        t["lists"][0]["gate"] = "story S-1 not started"
        site = FakeSite({"site": ALLOWED, "lists": []})
        f = sr.reconcile(t, site.actual)
        s = statuses(f)
        self.assertEqual((s[("Units", "")], s[("Entries", "Status")]), (sr.GATED, sr.DECISION))
        self.assertTrue(all(not x.ops for x in f if x.status in (sr.GATED, sr.DECISION)), "gated/undecided findings carry no operations")
        sr.apply(t, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertNotIn(("create_list", "Units"), site.calls)
        self.assertNotIn(("create_field", "Entries", "Status"), site.calls)

    def test_P10_main_root_site_rejected(self):
        for url in (MAIN, MAIN + "/"):
            with self.assertRaises(sr.SiteGuardError):
                sr.guard_site(url, ALLOWED)
            with self.assertRaises(sr.SiteGuardError):
                sr.guard_site(url, url)  # even if misconfigured to allow the root
            with self.assertRaises(sr.SiteGuardError):
                sr.apply(TARGET, {"site": url, "lists": []}, FakeSite({"lists": []}), url, allowed_url=ALLOWED, dry_run=False)

    def test_P11_other_sites_rejected(self):
        for url in (ALLOWED + "-confidential", ALLOWED.replace("app-staging", "other"), ALLOWED.upper(),
                    "https://other.invalid/sites/app-staging", ALLOWED + "/subsite"):
            with self.assertRaises(sr.SiteGuardError, msg=url):
                sr.guard_site(url, ALLOWED)
        with self.assertRaises(sr.SiteGuardError):
            sr.guard_site(ALLOWED, None)
        self.assertEqual(sr.guard_site(ALLOWED + "/", ALLOWED), ALLOWED)

    def test_P12_workdate_business_date_semantics(self):
        wd = next(x for x in TARGET["lists"][1]["fields"] if x["internalName"] == "WorkDate")
        self.assertEqual((wd["type"], wd["dateOnly"], wd["required"], wd["indexed"]), ("DateTime", True, True, True))
        self.assertIn('Format="DateOnly"', sr.field_schema_xml(wd))
        off = TARGET["businessTimeZone"]["utcOffsetMinutes"]
        self.assertEqual(sr.business_date("2026-10-06T18:30:00Z", off), "2026-10-07")
        self.assertEqual(sr.business_date("2026-10-06T16:59:59Z", off), "2026-10-06")
        self.assertEqual(sr.business_date("2026-10-06T17:00:00Z", off), "2026-10-07")
        self.assertEqual(sr.business_date("2026-01-15T17:00:00Z", off), "2026-01-16")  # winter
        self.assertEqual(sr.business_date("2026-07-15T17:00:00Z", off), "2026-07-16")  # summer: same offset, no DST
        self.assertNotEqual(sr.business_date("2026-10-06T18:30:00Z", off), "2026-10-06T18:30:00Z"[:10], "must not truncate UTC")
        if os.environ.get("TS_TARGET_SCHEMA"):
            with open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8") as fh:
                real = json.load(fh)
            self.assertEqual((real["businessTimeZone"]["iana"], real["businessTimeZone"]["utcOffsetMinutes"], real["businessTimeZone"]["dst"]),
                             ("Asia/Ho_Chi_Minh", 420, False))
            for l in real["lists"]:
                for f in l["fields"]:
                    if f["internalName"] == "WorkDate":
                        self.assertTrue(f["dateOnly"])
                        if l["title"] == "TimesheetEntries":
                            self.assertTrue(f["required"] and f["indexed"])

    def test_P13_no_hard_coded_tenant_list_or_group_ids(self):
        with open(os.path.join(HERE, "schema_reconcile.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIsNone(re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", src))
        self.assertIsNone(re.search(r"https?://[a-z0-9-]+\.sharepoint\.com", src, re.IGNORECASE))
        xml = sr.field_schema_xml(F("Unit", "Lookup", True, True, lookupList="Units"), "runtime-resolved-id")
        self.assertIn('List="{runtime-resolved-id}"', xml)
        with self.assertRaises(ValueError):
            sr.field_schema_xml(F("Unit", "Lookup", lookupList="Units"))
        if os.environ.get("TS_TARGET_SCHEMA"):
            with open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8") as fh:
                raw = fh.read()
            self.assertIsNone(re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", raw))

    def test_P14_destructive_change_never_executed(self):
        a = actual_from(TARGET)
        a["lists"][1]["fields"].append(dict(F("Obsolete", "Text"), builtIn=False))
        a["lists"].append({"title": "OldList", "itemCount": 3, "system": False, "fields": []})
        next(x for x in a["lists"][1]["fields"] if x["internalName"] == "Hours")["type"] = "Text"
        f = sr.reconcile(TARGET, a)
        s = statuses(f)
        self.assertEqual((s[("Entries", "Obsolete")], s[("OldList", "")], s[("Entries", "Hours")]), (sr.EXTRA, sr.EXTRA, sr.BLOCKED))
        site = FakeSite(a)
        with self.assertRaises(sr.SiteGuardError):
            sr.apply(TARGET, a, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual(site.calls, [])
        ops = {o for o in sr.ROLLBACK}
        self.assertFalse(ops & {"delete_list", "delete_field", "change_type", "rename_field"})
        a2 = actual_from(TARGET)
        a2["lists"][1]["fields"][3]["indexed"] = True
        a2["lists"][1]["fields"].append(dict(F("Extra", "Text", idx=True), builtIn=False))
        self.assertTrue(all(o[2][0] in sr.ROLLBACK for o in sr.plan(sr.reconcile(TARGET, a2))))

    def test_dry_run_executes_nothing(self):
        site = FakeSite({"site": ALLOWED, "lists": []})
        r = sr.apply(TARGET, site.actual, site, ALLOWED, allowed_url=ALLOWED)
        self.assertTrue(r.dry_run and r.skipped and not r.executed and not site.calls)


@unittest.skipUnless(os.environ.get("TS_TARGET_SCHEMA") and os.environ.get("TS_ASBUILT"),
                     "set TS_TARGET_SCHEMA and TS_ASBUILT to check the real target against the as-built inventory")
class TargetPolicy(unittest.TestCase):
    """Project-owner decisions of 2026-10-06 (R1-Q2, R04-N2, R04-N4, LegacyModifiedBy classification)."""

    @classmethod
    def setUpClass(cls):
        with open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8") as fh:
            cls.target = json.load(fh)
        with open(os.environ["TS_ASBUILT"], encoding="utf-8") as fh:
            cls.actual = json.load(fh)
        cls.findings = sr.reconcile(cls.target, cls.actual)
        cls.plan = sr.plan(cls.findings)

    def _list(self, title, target=None):
        return next(l for l in (target or self.target)["lists"] if l["title"] == title)

    def _opened(self):
        """Target with every story gate opened (decisions kept): what would run once all dependencies close."""
        t = copy.deepcopy(self.target)
        for l in t["lists"]:
            l.pop("gate", None)
            for f in l["fields"]:
                f.pop("gate", None)
        return t

    def test_approvalstatus_not_canonical(self):
        names = {f["internalName"] for l in self.target["lists"] for f in l["fields"]}
        self.assertNotIn("ApprovalStatus", names)
        es = next(f for f in self._list("TimesheetEntries")["fields"] if f["internalName"] == "EntryStatus")
        self.assertEqual((es["type"], es["choices"], es["required"], es["indexed"]), ("Choice", ["Draft", "Approved", "Deleted"], True, True))
        self.assertNotIn("decision", es)
        self.assertNotIn("Rejected", es["choices"])

    def test_entrystatus_provisioned_when_dependency_opens(self):
        f = sr.reconcile(self._opened(), {"site": ALLOWED, "lists": []})
        planned = {(l, n) for l, n, op in sr.plan(f) if op[0] == "create_field"}
        self.assertIn(("TimesheetEntries", "EntryStatus"), planned)
        self.assertNotIn(("TimesheetEntries", "ApprovalStatus"), planned)
        xml = sr.field_schema_xml(next(x for x in self._list("TimesheetEntries")["fields"] if x["internalName"] == "EntryStatus"))
        self.assertIn("<CHOICE>Deleted</CHOICE>", xml)
        self.assertNotIn("Rejected", xml)

    def test_no_isdeleted_column(self):
        names = {f["internalName"].lower() for l in self.target["lists"] for f in l["fields"]}
        self.assertFalse(names & {"isdeleted", "deleted", "deletedflag"})
        planned = {n.lower() for _, n, _ in sr.plan(sr.reconcile(self._opened(), {"site": ALLOWED, "lists": []}))}
        self.assertNotIn("isdeleted", planned)

    def test_legacymodifiedby_gated_by_env_d2_on_operational_masters(self):
        st = statuses(self.findings)
        for lst in ("Departments", "Disciplines", "Positions", "Employees"):
            self.assertEqual(st[(lst, "LegacyModifiedBy")], sr.GATED)
            f = next(x for x in self.findings if x.list == lst and x.field == "LegacyModifiedBy")
            self.assertIn("ENV-D2", f.detail)
        self.assertFalse(any(n == "LegacyModifiedBy" for _, n, _ in self.plan))

    def test_locale_not_altered(self):
        self.assertFalse(self.target["siteSettings"]["managedByTool"])
        with open(os.path.join(HERE, "schema_reconcile.py"), encoding="utf-8") as fh:
            src = fh.read()
        for word in ("RegionalSettings", "LocaleId", "regionalsetng", "TimeZone"):
            self.assertNotIn(word, src)
        self.assertTrue(all(op[0] in sr.ROLLBACK for _, _, op in self.plan))

    def test_retained_as_built_columns_kept(self):
        retained = [(l["title"], f["internalName"]) for l in self.target["lists"] for f in l["fields"] if "retained" in f.get("note", "")]
        self.assertTrue(retained, "the target marks retained as-built columns")
        st = statuses(self.findings)
        for key in retained:
            self.assertEqual(st[key], sr.OK, key)
            self.assertFalse(any((l, n) == key for l, n, _ in self.plan))

    def test_no_destructive_cleanup_and_exact_live_plan(self):
        self.assertTrue(all(op[0] == "create_field" for _, _, op in self.plan))
        extra = [f for f in self.findings if f.status == sr.EXTRA]
        self.assertTrue(extra and all(not f.ops for f in extra))
        self.assertEqual(sorted((l, n) for l, n, _ in self.plan), sorted(
            [(l, n) for l in ("Departments", "Disciplines", "Positions") for n in ("LegacyModifiedOn", "MigrationBatch", "IsLegacyPlaceholder")]
            + [("Employees", "LegacyModifiedOn"), ("Employees", "IsLegacyPlaceholder"), ("Employees", "SortOrder")]))
        self.assertEqual(len(self.plan), 12)
        self.assertEqual([f for f in self.findings if f.status == sr.BLOCKED], [])


class RestRequests(unittest.TestCase):
    def test_rest_client_builds_expected_requests(self):
        calls = []

        def transport(method, path, body, headers):
            calls.append((method, path, body, headers))
            if path.endswith("?$select=Id"):
                return 200, {"d": {"Id": "lookup-list-id"}}
            if path.endswith("?$select=Choices"):
                return 200, {"d": {"Choices": {"results": ["Draft"]}}}
            return 201, {"d": {}}
        c = sr.RestSchemaClient(transport)
        c.create_field("Entries", next(x for x in TARGET["lists"][1]["fields"] if x["internalName"] == "Unit"))
        post = next(x for x in calls if x[1].endswith("createfieldasxml"))
        xml = post[2]["parameters"]["SchemaXml"]
        for frag in ('Name="Unit"', 'StaticName="Unit"', 'List="{lookup-list-id}"', 'Indexed="TRUE"', 'RelationshipDeleteBehavior="Restrict"'):
            self.assertIn(frag, xml)
        c.update_field("Entries", "Status", "add_choices", ["Approved"])
        merge = calls[-1]
        self.assertEqual((merge[0], merge[3]["X-HTTP-Method"]), ("POST", "MERGE"))
        self.assertEqual(merge[2]["Choices"]["results"], ["Draft", "Approved"])
        self.assertFalse(any(x[0] == "DELETE" or x[3].get("X-HTTP-Method") == "DELETE" for x in calls))
        hours = sr.field_schema_xml(next(x for x in TARGET["lists"][1]["fields"] if x["internalName"] == "Hours"))
        self.assertIn("<Validation>=AND([Hours]&gt;0,[Hours]&lt;=24)</Validation>", hours)
        with self.assertRaises(ValueError):
            sr.field_schema_xml(F("Bad Name", "Text"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
