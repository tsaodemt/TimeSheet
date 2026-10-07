"""SharePoint-only architecture scope SD01-SD10 and the SharePoint-only deployment pack PK01-PK04 (offline; synthetic)."""
import copy
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "powerapp")]
import architecture_scope as scope  # noqa: E402
import r1_flows as rf  # noqa: E402
import sharepoint_only_pack as pack  # noqa: E402
import wdl_sim  # noqa: E402

SITE = "https://tenant-a.invalid/sites/app-staging"
APPROVED = {"environmentName": "App-Staging", "environmentType": "Sandbox"}
ENV_OK = {"displayName": "App-Staging", "type": "Sandbox", "isDefault": False, "hasDataverse": False, "payAsYouGo": False}
CONFIG = {"siteUrl": SITE, "approvedSiteUrl": SITE, "domain": "tenant-a.invalid", "environmentLabel": "STAGING",
          "roleGroups": [["EMP", "00000000-0000-4000-8000-0000000000e1"]], "registry": rf.GENERIC_REGISTRY, "overlay": rf.GENERIC_OVERLAY}


class Scope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flows = pack.flows(CONFIG)

    def test_SD01_dataverse_rejected(self):
        self.assertEqual((scope.SCOPE["dataStore"], scope.SCOPE["dataverse"]), ("SharePoint", "REJECTED"))

    def test_SD02_no_dataverse_table_or_connector_dependency(self):
        self.assertEqual(scope.check_artifacts(self.flows, open(os.path.join(HERE, "..", "powerapp", "build_demo_app.py"), encoding="utf-8").read()), [])
        bad = {"x": {"a": {"type": "OpenApiConnection", "inputs": {"host": {"connectionName": "shared_commondataserviceforapps"}}}}}
        self.assertTrue(scope.check_artifacts(bad))

    def test_SD03_no_dataverse_environment_binding(self):
        s = json.dumps(self.flows)
        self.assertNotIn("connectionReferenceLogicalName", s)
        self.assertNotIn("<PFX>", s)
        self.assertEqual(scope.check_environment(dict(ENV_OK, hasDataverse=True), APPROVED)[0][:9], "Dataverse")
        self.assertTrue(scope.check_environment(dict(ENV_OK, hasDataverse=None), APPROVED), "unknown counts as present")

    def test_SD04_no_default_target(self):
        self.assertTrue(scope.check_environment(dict(ENV_OK, displayName="Contoso (default)", type="Default", isDefault=True), APPROVED))

    def test_SD05_no_production_target(self):
        self.assertTrue(scope.check_environment(dict(ENV_OK, type="Production"), APPROVED))
        with self.assertRaises(pack.PackRefused):
            pack.flows(dict(CONFIG, environmentLabel="PRODUCTION"))

    def test_SD06_exact_staging_sharepoint_url(self):
        for url in ("https://tenant-a.invalid/", SITE + "/", SITE.upper(), "https://tenant-a.invalid/sites/app"):
            with self.assertRaises(pack.PackRefused, msg=url):
                pack.flows(dict(CONFIG, siteUrl=url))
        self.assertEqual({d["SiteUrl"]["inputs"] for d in self.flows.values()}, {SITE})

    def test_SD07_payg_out_of_scope(self):
        self.assertEqual(scope.SCOPE["payAsYouGo"], "OUT_OF_SCOPE")
        self.assertTrue(scope.check_environment(dict(ENV_OK, payAsYouGo=True), APPROVED))

    def test_SD08_capacity_workaround_rejected(self):
        self.assertEqual(scope.SCOPE["capacityPurchase"], "OUT_OF_SCOPE")
        self.assertTrue(scope.check_environment(dict(ENV_OK, capacityPurchase=True), APPROVED))
        for t in ("Trial", "Developer", "Teams"):
            self.assertTrue(scope.check_environment(dict(ENV_OK, type=t), APPROVED), t)

    def test_SD09_target_must_be_the_dedicated_staging_environment(self):
        self.assertEqual(scope.check_environment(ENV_OK, APPROVED), [])
        self.assertTrue(scope.check_environment(dict(ENV_OK, displayName="Other-Sandbox"), APPROVED))

    def test_SD10_alm_classification_complete(self):
        items = {i for i, _, _ in scope.ALM}
        for need in ("solution", "publisher / prefix", "environment variables", "connection references", "deployment pipelines",
                     "canvas app (non-solution)", "cloud flows (non-solution, Power Apps V2 trigger)"):
            self.assertIn(need, items)
        for i, cls, repl in scope.ALM:
            self.assertIn(cls, (scope.WORKS, scope.DEPENDENT, scope.PROOF), i)
            self.assertTrue(repl, i)


class Pack(unittest.TestCase):
    def test_PK01_flows_use_only_plain_scope_connectors(self):
        f = pack.flows(CONFIG)
        conns = {a["inputs"]["host"]["connectionName"] for d in f.values() for _, a, _ in rf._walk(d) if a.get("type") == "OpenApiConnection"}
        self.assertEqual(conns, set(scope.SCOPE["connectors"]))

    def test_PK02_site_guard_precedes_every_sharepoint_call(self):
        for name, d in pack.flows(CONFIG).items():
            self.assertEqual(d["Site_guard"]["expression"]["equals"][1], SITE, name)
            self.assertEqual([n for n, a in d.items() if "SiteUrl" in (a.get("runAfter") or {})], ["Site_guard"], name)

    def test_PK03_tampered_site_terminates_before_any_call(self):
        d = pack.flows(CONFIG)["TS-AppOpen"]
        mini = {"SiteUrl": dict(d["SiteUrl"], inputs="https://tenant-a.invalid/"), "Site_guard": d["Site_guard"]}
        run = wdl_sim.Run(trigger_body={}, mocks=lambda *a: (_ for _ in ()).throw(AssertionError("no call"))).run(mini)
        self.assertEqual(run.terminated["runError"]["code"], "SITE_NOT_ALLOWED")
        ok = wdl_sim.Run(trigger_body={}, mocks=None).run({"SiteUrl": d["SiteUrl"], "Site_guard": d["Site_guard"]})
        self.assertIsNone(ok.terminated)

    def test_PK04_pack_build_writes_manifest_with_one_site(self):
        out = tempfile.mkdtemp()
        m = pack.build(copy.deepcopy(CONFIG), out)
        self.assertEqual(m["sitesReferenced"], [SITE])
        self.assertEqual(sorted(m["flows"]), ["TS-AppOpen", "TS-ReadOwn", "TS-SaveEntry"])
        self.assertTrue(os.path.exists(os.path.join(out, "app", "scrEntry.pa.yaml")))
        self.assertEqual(m["architecture"]["dataverse"], "REJECTED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
