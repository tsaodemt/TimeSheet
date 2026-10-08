"""OFFLINE-APPSTART-QUALIFICATION-01 tests AQ01-AQ16 (synthetic data only; run: python -m unittest).
Updated by OFFLINE-APPSTART-GAP-FIX-01: the former gaps AS09/AS10/AS13 are now asserted as closed (AQ07, AQ12).

Pins the CURRENT AppStart contract (reference appstart.py == generated flow build_appstart_flow.py, both run through the
WDL simulator via test_appstart's harness) for the qualification checks AS02-AS17. Behaviour that the current contract
does not define is asserted AS IT IS and listed as a gap in docs/appstart-contract.md; nothing here changes AppStart.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "audit")):
    sys.path.insert(0, p)
import test_appstart as ta  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402

RESPONSE_KEYS = ["ok", "resultCode", "messageCode", "correlationId", "employeeCode", "configStatus", "config", "interim", "missing"]
CODES = {"OK", "INVALID_IDENTITY", "ACCOUNT_NOT_ALLOWED", "UNMAPPED_IDENTITY", "DUPLICATE_IDENTITY", "INACTIVE_EMPLOYEE",
         "DIRECTORY_ERROR", "INVALID_EMPLOYEE_REFERENCE", "INTERNAL_ERROR"}
FLOW_JSON = json.dumps(ta.FLOW)


_HARNESS = ta.AppStart("test_AO01_mapped_active_employee_succeeds")  # reuse the reference-vs-flow comparison


def both(upn, decoys=None):
    return _HARNESS.both(upn, decoys=decoys)


def _host(a):
    i = a.get("inputs")
    return i.get("host", {}) if isinstance(i, dict) else {}


def emp_of(upn):
    return next(e for e in tg.EMPS if e.account_upn == upn)


class Qualification(unittest.TestCase):
    def test_aq01_identity_from_invoker_profile_only(self):
        # AS02: the only identity source in the flow is MyProfile_V2 on the invoker's own Users connection.
        prof = [a for a in _walk(ta.FLOW) if _host(a).get("operationId") == "MyProfile_V2"]
        self.assertEqual(len(prof), 1)
        self.assertEqual(prof[0]["inputs"]["host"]["connectionReferenceLogicalName"], "<PFX>_CR_O365Users_Invoker")
        self.assertIn("Get_caller_profile", FLOW_JSON)
        self.assertNotIn("x-ms-user", FLOW_JSON.lower())

    def test_aq02_forged_employee_id_and_account_upn_ignored(self):
        # AS03 / AS04: request fields naming another employee change nothing.
        other = emp_of(tg.u("peer"))
        decoys = {"EmployeeId": str(other.item_id), "UserPrincipalName": other.account_upn, "CallerUpn": other.account_upn,
                  "OwnerUpn": other.account_upn, "ActorUpn": other.account_upn, "Role": "APR", "Scope": "company"}
        r, _, _ = both(tg.u("emp"), decoys)
        self.assertTrue(r["ok"])
        self.assertEqual(r["employeeCode"], emp_of(tg.u("emp")).legacy_id)
        forged, _, _ = both(tg.u("nobody"), decoys)
        self.assertFalse(forged["ok"])
        self.assertEqual((forged["resultCode"], forged["employeeCode"]), ("UNMAPPED_IDENTITY", ""))

    def test_aq03_one_active_mapping_succeeds(self):
        # AS05 (synthetic stand-in for the demo identity -> its single active row).
        r, ev, _ = both(tg.u("emp"))
        self.assertEqual((r["ok"], r["resultCode"], r["messageCode"]), (True, "OK", "MSG_OK"))
        self.assertEqual(r["employeeCode"], "E1")
        self.assertEqual(ev.ResultCode, "OK")

    def test_aq04_zero_mapping_fails_closed(self):
        r, _, _ = both(tg.u("nobody"))
        self.assertEqual((r["ok"], r["resultCode"], r["messageCode"]), (False, "UNMAPPED_IDENTITY", "MSG_ACCOUNT_NOT_ENABLED"))
        self.assertEqual((r["employeeCode"], r["config"], r["configStatus"]), ("", {}, ""))

    def test_aq05_duplicate_mapping_fails_closed(self):
        # Malformed data (unique index bypassed / mock): two rows for one UPN.
        r, _, _ = both(tg.u("twin"))
        self.assertEqual((r["ok"], r["resultCode"], r["employeeCode"]), (False, "DUPLICATE_IDENTITY", ""))
        # The flow detects duplicates by reading at most two rows for the UPN.
        self.assertRegex(FLOW_JSON, r"AccountUpn eq '@\{[^}]+\}'&\$top=2")

    def test_aq06_inactive_fails_closed(self):
        r, _, _ = both(tg.u("gone"))
        self.assertEqual((r["ok"], r["resultCode"], r["employeeCode"], r["config"]), (False, "INACTIVE_EMPLOYEE", "", {}))

    def test_aq07_missing_discipline_fails_closed(self):
        # AS09 / AS10 (OFFLINE-APPSTART-GAP-FIX-01, decision 1): a required reference that does not resolve -> coded deny.
        r, _, _ = both(tg.u("nodisc"))
        self.assertEqual((r["ok"], r["resultCode"], r["messageCode"], r["employeeCode"], r["config"]),
                         (False, "INVALID_EMPLOYEE_REFERENCE", "MSG_TEMPORARY_PROBLEM", "", {}))

    def test_aq08_position_not_read(self):
        # AS11: Position (optional) is not part of the projection -> an absent Position cannot fail AppStart.
        uri = next(re.search(r"\$select=([^&]+)", json.dumps(a)).group(1) for a in _walk(ta.FLOW)
                   if "AccountUpn eq" in json.dumps(a) and "$select=" in json.dumps(a) and a.get("type") != "Scope")
        self.assertEqual(set(uri.split(",")), {"Id", "LegacyId", "IsActive", "Discipline/DisciplineCode", "AccountUpn",
                                               "Department/DepartmentCode"})
        self.assertEqual(len(uri.split(",")), 6)

    def test_aq09_response_shape_fixed_and_minimal(self):
        # AS12: the same keys for success and every failure; no item id, list name, URL, department / position values.
        for upn in (tg.u("emp"), tg.u("nobody"), tg.u("twin"), tg.u("gone")):
            r, _, _ = both(upn)
            self.assertEqual(list(r), RESPONSE_KEYS)
        body = ta.FLOW["Respond"]["inputs"]["body"]
        self.assertEqual(sorted(body), sorted(k.lower() for k in RESPONSE_KEYS))

    def test_aq10_deterministic_for_same_input(self):
        a, _, _ = both(tg.u("emp"))
        b, _, _ = both(tg.u("emp"))
        self.assertEqual(a, b)

    def test_aq11_error_codes_closed_set_and_message_total(self):
        # AS13: every identity code the flow can emit has a message code; no other result code exists.
        emitted = set(re.findall(r"'([A-Z_]+)'", ta.FLOW["IdCode"]["inputs"]))
        self.assertEqual(emitted, {"OK", "INVALID_IDENTITY", "DIRECTORY_ERROR", "UNMAPPED_IDENTITY", "DUPLICATE_IDENTITY",
                                   "INACTIVE_EMPLOYEE", "INVALID_EMPLOYEE_REFERENCE"})
        self.assertLessEqual(emitted, CODES)
        self.assertLessEqual(emitted, set(json.loads(json.dumps(__import__("build_appstart_flow").MESSAGE))))

    def test_aq12_profile_failure_is_coded(self):
        # AS13 (decision 3): a failed MyProfile_V2 still ends in exactly one coded response.
        def mocks(name, a, p):
            if a["inputs"]["host"]["operationId"] == "MyProfile_V2":
                return "Failed", {"error": "x"}
            return "Succeeded", {"value": []}
        run = wdl_sim.Run(trigger_body={"text": "Teams"}, run_name="r", mocks=mocks, now=ta.NOW).run(ta.FLOW)
        self.assertNotEqual(run.results["Respond"]["status"], "Succeeded")
        out = run.results["Respond_error"]["outputs"]
        self.assertEqual((out["ok"], out["resultcode"], out["messagecode"], out["employeecode"], out["config"]),
                         ("false", "DIRECTORY_ERROR", "MSG_TEMPORARY_PROBLEM", "", "{}"))

    def test_aq13_employees_read_by_service_not_user(self):
        # AS14: every SharePoint call uses the service connection reference; the caller needs no Employees access.
        sp = [_host(a) for a in _walk(ta.FLOW) if _host(a).get("operationId") == "HttpRequest"]
        self.assertTrue(sp)
        self.assertTrue(all(h["connectionReferenceLogicalName"] == "<PFX>_CR_SharePoint_OpsService" for h in sp))

    def test_aq14_no_timesheetentries_dependency(self):
        self.assertNotIn("timesheetentries", FLOW_JSON.lower())

    def test_aq15_no_dataverse_default_or_production_dependency(self):
        low = FLOW_JSON.lower()
        for bad in ("commondataservice", "dataverse", "shared_commondataserviceforapps", "default-", "/environments/"):
            self.assertNotIn(bad, low)
        self.assertNotIn("PRODUCTION", json.dumps(ta.flow_for()["Respond"]))

    def test_aq16_canvas_startup_fails_closed_on_not_ok(self):
        # The demo startup screen navigates only when ok = "true"; anything else (incl. no response) -> access denied.
        with open(os.path.join(HERE, "..", "powerapp", "demo-r1", "scrStartup.pa.yaml"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("'TS-AppOpen'.Run(", src)
        self.assertRegex(src, r'varOpen\.ok\s*=\s*"true"')
        self.assertIn("scrAccessDenied", src)


def _walk(actions):
    for a in actions.values():
        yield a
        for k in ("actions", "else"):
            sub = a.get(k)
            if isinstance(sub, dict):
                yield from _walk(sub.get("actions", sub) if k == "else" else sub)


if __name__ == "__main__":
    unittest.main()
