"""R1-OFFLINE-RELEASE-READINESS-01 cross-flow checks RR-X01..RR-X12 (synthetic placeholders only; run: python -m unittest).

AppStart, ReadOwn and SaveEntry as one system: one identity source, service-only data access, deterministic response
shapes on every path, Canvas calls matching the flow triggers, message codes known to the app, no Dataverse / Default /
Production dependency, and the release documentation present.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
for d in ("powerautomate", "config", "identity", "audit", "timesheet"):
    sys.path.insert(0, os.path.join(ROOT, "tools", d))
import test_appstart as ta  # noqa: E402
import test_r1_read_flow as tr  # noqa: E402
import test_r1_save_flow as ts  # noqa: E402

FLOWS = {"TS-AppOpen": ta.FLOW, "TS-ReadOwn": tr.FLOW, "TS-SaveEntry": ts.FLOW}
APP = os.path.join(ROOT, "tools", "powerapp", "demo-r1")
DOCS = os.path.join(ROOT, "docs")


def _walk(actions):
    for a in actions.values():
        yield a
        if isinstance(a.get("actions"), dict):
            yield from _walk(a["actions"])
        if isinstance(a.get("else"), dict) and isinstance(a["else"].get("actions"), dict):
            yield from _walk(a["else"]["actions"])


def _hosts(flow):
    return [a["inputs"]["host"] for a in _walk(flow) if isinstance(a.get("inputs"), dict) and "host" in a["inputs"]]


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


class ReleaseReadiness(unittest.TestCase):
    def test_x01_single_identity_source(self):
        for name, flow in FLOWS.items():
            prof = [h for h in _hosts(flow) if h.get("operationId") == "MyProfile_V2"]
            self.assertEqual([h["connectionReferenceLogicalName"] for h in prof], ["<PFX>_CR_O365Users_Invoker"], name)

    def test_x02_data_only_through_service_connection(self):
        for name, flow in FLOWS.items():
            sp = [h for h in _hosts(flow) if h.get("operationId") == "HttpRequest"]
            self.assertTrue(sp, name)
            self.assertTrue(all(h["connectionReferenceLogicalName"] == "<PFX>_CR_SharePoint_OpsService" for h in sp), name)

    def test_x03_connection_placeholders_only(self):
        for name, flow in FLOWS.items():
            blob = json.dumps(flow)
            self.assertNotIn('"connectionName"', blob, name)
            refs = set(re.findall(r'"connectionReferenceLogicalName": "([^"]+)"', blob))
            self.assertTrue(refs and all(r.startswith("<PFX>_CR_") for r in refs), name)

    def test_x04_every_flow_has_one_error_responder_with_same_keys(self):
        for name, flow in FLOWS.items():
            self.assertEqual(list(flow["Respond_error"]["inputs"]["body"]), list(flow["Respond"]["inputs"]["body"]), name)
            self.assertEqual(flow["Respond_error"]["inputs"]["body"]["messagecode"], "MSG_TEMPORARY_PROBLEM", name)
            err = flow["Respond_error"]["inputs"]["body"]["resultcode"]
            self.assertIn("'DIRECTORY_ERROR'", err, name)
            self.assertIn("'INTERNAL_ERROR'", err, name)

    def test_x05_no_dataverse_default_production(self):
        for name, flow in FLOWS.items():
            low = json.dumps(flow).lower()
            for bad in ("commondataservice", "dataverse", "default-", "/environments/"):
                self.assertNotIn(bad, low, name)

    def test_x06_users_never_need_timesheetentries_access(self):
        # AppStart never touches TimesheetEntries; ReadOwn/SaveEntry touch it only through the service connection (x02).
        self.assertNotIn("timesheetentries", json.dumps(FLOWS["TS-AppOpen"]).lower())

    def test_x07_canvas_calls_match_trigger_arity(self):
        expect = {"TS-AppOpen": 1, "TS-ReadOwn": 5, "TS-SaveEntry": 10}
        src = "".join(_read(APP, f) for f in os.listdir(APP) if f.endswith(".pa.yaml"))
        for name, n in expect.items():
            calls = re.findall(r"'%s'\.Run\(" % re.escape(name), src)
            self.assertTrue(calls, name)
            for m in re.finditer(r"'%s'\.Run\(" % re.escape(name), src):
                depth, args, i = 1, 1, m.end()
                while depth:
                    ch = src[i]
                    depth += ch == "(" or 0
                    depth -= ch == ")" or 0
                    if ch == "," and depth == 1:
                        args += 1
                    i += 1
                self.assertEqual(args, n, name)

    def test_x08_app_message_catalogue_covers_shared_codes(self):
        cat = json.loads(_read(APP, "messages.json"))
        codes = set(cat["messages"])
        for c in ("MSG_OK", "MSG_TEMPORARY_PROBLEM", "MSG_ACCOUNT_NOT_ENABLED", "MSG_CONFLICT", "MSG_VALIDATION_DATE",
                  "MSG_VALIDATION_HOURS", "MSG_VALIDATION_LOOKUP", "MSG_FORBIDDEN", "MSG_ERROR"):
            self.assertIn(c, codes)

    def test_x09_readown_canvas_always_sends_range(self):
        for c in re.findall(r"'TS-ReadOwn'\.Run\(([^;]+)\);", _read(APP, "scrMyTimesheets.pa.yaml")):
            self.assertTrue(c.startswith('Text(varFrom, "yyyy-mm-dd"), Text(varTo, "yyyy-mm-dd")'))

    def test_x10_save_create_non_idempotent_declared(self):
        import r1_flows
        m = r1_flows.sample_manifest() if hasattr(r1_flows, "sample_manifest") else None
        blob = json.dumps(m) if m else _read(HERE, "r1_flows.py")
        self.assertIn("NON_IDEMPOTENT_R1", blob)
        self.assertNotIn("requestkey", json.dumps(FLOWS["TS-SaveEntry"]).lower())

    def test_x11_release_docs_present_and_consistent(self):
        status = _read(DOCS, "r1-status.md")
        for s in ("AppStart (TS-AppOpen) | **CLOSED**", "ReadOwn (TS-ReadOwn) | **CLOSED**", "SaveEntry (TS-SaveEntry) | **CLOSED**",
                  "BLOCKED_BY_TENANT_CAPACITY", "UAT | **NOT_STARTED**", "Production | **NOT_STARTED**"):
            self.assertIn(s, status)
        for doc in ("r1-known-limitations.md", "r1-deployment-package.md", "r1-staging-live-test-plan.md",
                    "appstart-contract.md", "readown-contract.md", "saveentry-contract.md"):
            self.assertTrue(os.path.exists(os.path.join(DOCS, doc)), doc)
        self.assertIn("R1_KNOWN_LIMITATION_CREATE_RETRY_NON_IDEMPOTENT", _read(DOCS, "r1-known-limitations.md"))

    def test_x12_no_tenant_values_in_flows(self):
        for name, flow in FLOWS.items():
            blob = json.dumps(flow)
            self.assertNotRegex(blob, r"[a-z0-9-]+\.sharepoint\.com", name)
            self.assertNotRegex(blob, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", name)


if __name__ == "__main__":
    unittest.main()
