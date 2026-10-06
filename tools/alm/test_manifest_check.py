"""Manifest checks M01-M07 (offline; synthetic manifest; run: python -m unittest test_manifest_check).
Set TS_SOLUTION_MANIFEST=<manifest.json> to lint the real (local) draft and print its readiness blockers."""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manifest_check as mc  # noqa: E402

M = {"environmentVariables": [
        {"schemaName": "<PFX>_OpsSiteUrl", "type": "Text", "purpose": "ops site", "r1": True, "sourceDecision": "AD-8",
         "gated": False, "values": {"staging": "<staging ops site>", "production": "<prod ops site>"}},
        {"schemaName": "<PFX>_ConfSiteUrl", "type": "Text", "purpose": "conf site", "r1": False, "sourceDecision": "ENV-D2",
         "gated": True, "gatedBy": "ENV-D2", "values": {"staging": "<TBD>"}}],
     "connectionReferences": [
        {"schemaName": "<PFX>_CR_Ops", "connectorId": "shared_sharepointonline", "connectionOwner": "<svc-operational>",
         "purpose": "guard flows", "r1": True, "gated": True, "gatedBy": "D-3"}]}


class Manifest(unittest.TestCase):
    def test_M01_placeholder_manifest_is_publishable(self):
        self.assertEqual(mc.lint(M), [])

    def test_M02_tenant_values_refused_in_publishable_manifest(self):
        for v in ("https://contoso.sharepoint.example/sites/x", "0f0e0d0c-0b0a-4908-8706-050403020100", "svc@contoso.example"):
            m = copy.deepcopy(M)
            m["environmentVariables"][0]["values"]["staging"] = v
            self.assertTrue(mc.lint(m), v)
            self.assertEqual(mc.lint(m, publishable=False), [], "an environment-local manifest may hold real values")

    def test_M03_schema_hygiene(self):
        for mutate in (lambda m: m["environmentVariables"].append(dict(m["environmentVariables"][0])),
                       lambda m: m["environmentVariables"][0].update(schemaName="OpsSiteUrl"),
                       lambda m: m["environmentVariables"][0].update(schemaName="<PFX>_ClientSecret"),
                       lambda m: m["environmentVariables"][1].pop("gatedBy"),
                       lambda m: m["connectionReferences"][0].update(connectionOwner=""),
                       lambda m: m["environmentVariables"][0].update(sourceDecision="")):
            m = copy.deepcopy(M)
            mutate(m)
            self.assertTrue(mc.lint(m))

    def test_M04_readiness_fails_closed(self):
        ready, b = mc.readiness(M, "staging")
        self.assertFalse(ready)
        names = {n for n, _ in b}
        self.assertEqual(names, {"<PFX>_OpsSiteUrl", "<PFX>_CR_Ops", "publisher"})
        self.assertNotIn("<PFX>_ConfSiteUrl", names, "out-of-scope (not R1) items do not block R1")
        self.assertIn("<PFX>_ConfSiteUrl", {n for n, _ in mc.readiness(M, "staging", scope=None)[1]})

    def test_M05_ready_when_everything_in_scope_is_resolved(self):
        m = copy.deepcopy(M)
        for x in m["environmentVariables"] + m["connectionReferences"]:
            x["schemaName"] = x["schemaName"].replace("<PFX>", "ts")
        m["environmentVariables"][0]["values"]["staging"] = "https://real.example/sites/a"
        m["connectionReferences"][0].update(gated=False, connectionOwner="svc-operational")
        self.assertEqual(mc.readiness(m, "staging"), (True, []))
        self.assertFalse(mc.readiness(m, "production")[0])

    def test_M06_missing_environment_value_blocks(self):
        m = copy.deepcopy(M)
        del m["environmentVariables"][0]["values"]["staging"]
        self.assertIn(("<PFX>_OpsSiteUrl", "no value for staging"), mc.readiness(m, "staging")[1])

    @unittest.skipUnless(os.environ.get("TS_SOLUTION_MANIFEST"), "set TS_SOLUTION_MANIFEST to lint the real draft")
    def test_M07_real_draft(self):
        with open(os.environ["TS_SOLUTION_MANIFEST"], encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual(mc.lint(m), [])
        ready, blockers = mc.readiness(m, "staging")
        self.assertFalse(ready, "S05.1 is blocked by D-3 / ENV-D3")
        print("\nR1 staging readiness blockers: %d" % len(blockers))
        for n, why in blockers:
            print("  %-40s %s" % (n, why))


if __name__ == "__main__":
    unittest.main(verbosity=2)
