"""STAGING-UX-01 evaluator tests SUX01-SUX10 (offline; synthetic evidence)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import staging_ux as ux  # noqa: E402

SITE = "https://tenant-a.invalid/sites/app-staging"
TECH = ["LinkTitle", "LegacyId", "IsActive", "SortOrder"]


def views(lst, default_fields):
    return [{"Title": "All Items", "DefaultView": False, "fields": TECH},
            {"Title": lst + " clean", "DefaultView": True, "fields": default_fields}]


BEFORE = {"quickLaunch": [{"Title": t} for t in ("Home", "Notebook", "Documents", "Pages", "Recent", "Site contents")],
          "lists": [{"title": t} for t in ("Documents", "Site Pages", "AuditLog") + ux.MASTER_LISTS],
          "views": {l: [{"Title": "All Items", "DefaultView": True, "fields": TECH}] for l in ux.MASTER_LISTS}}
AFTER = {"welcomePage": "SitePages/Staging.aspx", "quickLaunch": [{"Title": t} for t in ux.NAV_TARGET],
         "lists": BEFORE["lists"], "views": {l: views(l, ux.BUSINESS_FIELDS[l]) for l in ux.MASTER_LISTS}}
GOOD = {"expectedSite": SITE, "site": SITE, "mainMutations": 0, "productionMutations": 0,
        "mutations": [{"kind": "page", "target": SITE}], "before": BEFORE, "after": AFTER, "newHomePage": "SitePages/Staging.aspx",
        "homeRender": {"ok": True, "url": SITE + "/SitePages/Staging.aspx", "text": "TimeSheet Staging\nSTAGING / NON-PRODUCTION"},
        "homeContent": "<h2>TimeSheet Staging</h2><p>STAGING / NON-PRODUCTION</p>",
        "homeLinks": ["/sites/app-staging/Lists/" + l for l in ux.MASTER_LISTS],
        "listRender": {l: {"ok": True} for l in ux.MASTER_LISTS},
        "permissionsUnchanged": True, "businessDataUnchanged": True, "schemaUnchanged": True, "pocMasterStillPass": True}


def ev(path=None, value=None, **over):
    e = copy.deepcopy(GOOD)
    e.update(over)
    if path:
        d = e
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
    return e


class StagingUxTests(unittest.TestCase):
    def test_sux01_good_evidence_22_of_22(self):
        r = ux.evaluate(GOOD)
        self.assertTrue(r["pass"], r["tests"])
        self.assertEqual(r["score"], "22/22")

    def test_sux02_security_wins(self):
        for k in ("permissionsUnchanged", "businessDataUnchanged", "schemaUnchanged", "pocMasterStillPass"):
            self.assertFalse(ux.evaluate(ev(**{k: False}))["pass"], k)

    def test_sux03_wrong_target_fails(self):
        self.assertEqual(ux.evaluate(ev(mutations=[{"target": "https://tenant-a.invalid/"}]))["tests"]["UX01"][0], "FAIL")

    def test_sux04_technical_column_in_default_fails(self):
        r = ux.evaluate(ev(("after", "views", "Employees"), views("Employees", ux.BUSINESS_FIELDS["Employees"] + ["LegacyId"])))
        self.assertEqual(r["tests"]["UX14"][0], "FAIL")
        self.assertEqual(r["tests"]["UX15"][0], "FAIL")

    def test_sux05_technical_view_must_be_preserved(self):
        v = [{"Title": "Employees clean", "DefaultView": True, "fields": ux.BUSINESS_FIELDS["Employees"]}]
        self.assertEqual(ux.evaluate(ev(("after", "views", "Employees"), v))["tests"]["UX15"][0], "FAIL")

    def test_sux06_admin_assets_not_promoted(self):
        nav = [{"Title": t} for t in ux.NAV_TARGET + ["AuditLog"]]
        r = ux.evaluate(ev(("after", "quickLaunch"), nav))
        self.assertEqual(r["tests"]["UX11"][0], "FAIL")
        self.assertEqual(r["tests"]["UX12"][0], "FAIL")
        self.assertEqual(ux.evaluate(ev(homeLinks=GOOD["homeLinks"] + ["/x/Lists/AppSettings"]))["tests"]["UX12"][0], "FAIL")

    def test_sux07_library_deleted_fails(self):
        lists = [l for l in BEFORE["lists"] if l["title"] != "Documents"]
        self.assertEqual(ux.evaluate(ev(("after", "lists"), lists))["tests"]["UX13"][0], "FAIL")

    def test_sux08_staging_label_and_no_identifiers(self):
        self.assertEqual(ux.evaluate(ev(homeRender={"ok": True, "url": "", "text": "TimeSheet Staging"}))["tests"]["UX06"][0], "FAIL")
        self.assertEqual(ux.evaluate(ev(homeContent="contact svc-ops@tenant-a.invalid"))["tests"]["UX06"][0], "FAIL")

    def test_sux09_home_must_be_welcome_page(self):
        self.assertEqual(ux.evaluate(ev(("after", "welcomePage"), "SitePages/Home.aspx"))["tests"]["UX04"][0], "FAIL")

    def test_sux10_missing_list_link_fails(self):
        self.assertEqual(ux.evaluate(ev(homeLinks=GOOD["homeLinks"][:3]))["tests"]["UX10"][0], "FAIL")


if __name__ == "__main__":
    unittest.main()
