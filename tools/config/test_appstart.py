"""AppStart / client-config tests AO01-AO21: reference (appstart.py) and generated flow (build_appstart_flow.py) run in
the WDL simulator; every case compares both. Offline only; nothing is deployed."""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "audit")):
    sys.path.insert(0, p)
import app_settings as cfg  # noqa: E402
import appstart as A  # noqa: E402
import build_appstart_flow as baf  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

ENV, NOW = "STAGING", "2026-01-01T00:00:00Z"
UNTRUSTED = ["CallerUpn", "ActorUpn", "OwnerUpn", "EmployeeId", "Role", "Scope", "UserPrincipalName", "Config"]
REG = {"settings": [
    {"key": "PeriodStartDay", "type": "int", "min": 1, "max": 28, "value": "26", "resolution": "RESOLVED", "exposeToClient": True},
    {"key": "WarnEntry", "type": "decimal", "min": 0, "max": 24, "value": "4", "resolution": "CUSTOMER DECISION", "decision": "B-7",
     "exposeToClient": True},
    {"key": "WarnDay", "type": "decimal", "min": 0, "max": 24, "value": "12", "resolution": "CUSTOMER DECISION", "decision": "B-7",
     "exposeToClient": True},
    {"key": "Switch", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "CUSTOMER DECISION", "decision": "Q-3",
     "exposeToClient": True},
    {"key": "Zone", "type": "iana_tz", "value": "Asia/Ho_Chi_Minh", "resolution": "RESOLVED"},
    {"key": "RetentionDays", "type": "int", "min": 1, "value": None, "resolution": "IT DECISION"},
    {"key": "Offset", "type": "int", "derived": {"from": "Zone", "function": "utcOffsetMinutes"}, "resolution": "RESOLVED"},
    {"key": "EnvLabel", "type": "enum", "allowed": ["STAGING", "PRODUCTION"], "environmentSpecific": True, "resolution": "ENVIRONMENT-SPECIFIC"}],
    "externalConfig": [{"key": "ServiceUpn", "type": "upn", "where": "environment variable", "requiredFor": ["UAT", "PRODUCTION"]}]}
INTERIM = {"value": "Off", "interim": True, "basis": "engineering", "approvedBy": "owner", "approvedOn": "2099-01-01",
           "customerDecision": "Q-3 OPEN / CUSTOMER DECISION", "allowedEnvironments": ["STAGING"]}
OVL = {"environment": "STAGING", "values": {"EnvLabel": "STAGING", "Switch": INTERIM}, "external": {}}
ROWS = [{"Title": k, "Value": v} for k, v in (("PeriodStartDay", "26"), ("WarnEntry", "4"), ("WarnDay", "12"), ("Switch", "Off"),
                                              ("Zone", "Asia/Ho_Chi_Minh"), ("RetentionDays", ""), ("EnvLabel", "STAGING"),
                                              ("ServiceUpn", "svc@tenant-a.invalid"), ("Offset", "0"))]


def flow_for(ovl=OVL):
    return baf.appstart_actions(site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit",
                                environment=ENV, registry=REG, overlay=ovl, untrusted_inputs=UNTRUSTED)


FLOW = flow_for()


def run_flow(upn, rows=ROWS, cid="run-ao", ovl=None, decoys=None, settings_fail=False):
    posts = {}
    lists = {tg.EMP_LIST: tg.rows(tg.EMPS)}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if p.get("parameters/method") == "GET" and "getbytitle('AppSettings')" in p["parameters/uri"]:
            return ("Failed", {"error": "x"}) if settings_fail else ("Succeeded", {"value": rows})
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], lists)
        if p.get("parameters/method") == "POST":
            posts.setdefault("audit", []).append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": 1}
        raise AssertionError(opid)
    trig = dict({"text": "Teams"}, **{"text_%d" % (i + 1): (decoys or {}).get(k, "") for i, k in enumerate(UNTRUSTED)})
    run = wdl_sim.Run(trigger_body=trig, run_name=cid, mocks=mocks, now=NOW).run(flow_for(ovl) if ovl else FLOW)
    resp = run.results["Respond"]["outputs"]
    return {"ok": resp["ok"] == "true", "resultCode": resp["resultcode"], "messageCode": resp["messagecode"],
            "correlationId": resp["correlationid"], "employeeCode": resp["employeecode"], "configStatus": resp["configstatus"],
            "config": json.loads(resp["config"]), "interim": json.loads(resp["interim"]),
            "missing": [m for m in resp["missing"].split(",") if m]}, posts.get("audit", []), run


def ref(upn, rows=ROWS, cid="run-ao", ovl=OVL, decoys=None):
    lookup = lambda n: [e for e in tg.EMPS if e.account_upn == n]  # noqa: E731
    return A.app_start(TrustedIdentity(upn=upn), lookup, tg.CFG, registry=REG, overlay=ovl, settings_rows=rows, correlation_id=cid,
                       environment=ENV, client_type="Teams", now=NOW, **{k: (decoys or {}).get(k, "") for k in UNTRUSTED})


class AppStart(unittest.TestCase):
    def both(self, upn, rows=ROWS, ovl=OVL, cid="run-ao", decoys=None):
        r, ev = ref(upn, rows, cid, ovl, decoys)
        f, audit, run = run_flow(upn, rows, cid, ovl if ovl is not OVL else None, decoys)
        self.assertEqual(f, r, "reference vs flow response differ")
        self.assertEqual(audit, [ev.to_row()], "reference vs flow audit row differ")
        return r, ev, run

    def test_AO01_mapped_active_employee_succeeds(self):
        r, ev, _ = self.both(tg.u("emp"))
        self.assertEqual((r["ok"], r["resultCode"], r["messageCode"], r["employeeCode"], r["configStatus"]), (True, "OK", "MSG_OK", "E1", "OK"))
        self.assertEqual((ev.EventType, ev.Decision), ("AppOpen", "ALLOW"))

    def test_AO02_unmapped_denied(self):
        r, ev, _ = self.both(tg.u("stranger"))
        self.assertEqual((r["ok"], r["resultCode"], r["messageCode"], ev.EventType), (False, "UNMAPPED_IDENTITY", "MSG_ACCOUNT_NOT_ENABLED", "IdentityRejected"))

    def test_AO03_inactive_denied(self):
        self.assertEqual(self.both(tg.u("gone"))[0]["resultCode"], "INACTIVE_EMPLOYEE")

    def test_AO04_duplicate_and_invalid_identity_denied(self):
        self.assertEqual(self.both(tg.u("twin"))[0]["resultCode"], "DUPLICATE_IDENTITY")
        self.assertEqual(self.both("emp@other-tenant.invalid")[0]["resultCode"], "INVALID_IDENTITY")

    def test_AO05_forged_caller_ignored(self):
        forged = {"CallerUpn": tg.u("appr-boss"), "ActorUpn": tg.u("appr-boss"), "UserPrincipalName": tg.u("appr-boss"), "Role": "ADM"}
        r, ev, _ = self.both(tg.u("emp"), decoys=forged)
        self.assertEqual((r["employeeCode"], ev.ActorUpn), ("E1", tg.u("emp")))
        r, ev, _ = self.both(tg.u("stranger"), decoys=forged)
        self.assertEqual((r["ok"], ev.ActorUpn), (False, tg.u("stranger")))

    def test_AO06_success_returns_only_the_approved_subset(self):
        r, _, _ = self.both(tg.u("emp"))
        self.assertEqual(r["config"], {"PeriodStartDay": 26, "WarnEntry": 4.0, "WarnDay": 12.0, "Switch": "Off"})

    def test_AO07_denied_caller_receives_no_config_or_employee_data(self):
        for upn in (tg.u("stranger"), tg.u("gone"), tg.u("twin")):
            r, _, _ = self.both(upn)
            self.assertEqual((r["config"], r["interim"], r["employeeCode"], r["configStatus"]), ({}, {}, "", ""))

    def test_AO08_to_AO10_server_only_values_never_returned(self):
        r, _, run = self.both(tg.u("emp"))
        blob = json.dumps(run.results["Respond"]["outputs"])
        for s in ("Zone", "Asia/Ho_Chi_Minh", "RetentionDays", "Offset", "EnvLabel", "ServiceUpn", "svc@"):
            self.assertNotIn(s, blob, s)

    def test_AO11_missing_required_config_unresolved(self):
        rows = [r for r in ROWS if r["Title"] != "Switch"]
        r, _, _ = self.both(tg.u("emp"), rows=rows, ovl={"environment": "STAGING", "values": {}, "external": {}})
        self.assertEqual((r["configStatus"], r["missing"], "Switch" in r["config"]), (cfg.CONFIG_UNRESOLVED, ["Switch"], False))

    def test_AO12_invalid_config_invalid(self):
        for bad in ("x", "29", "0", "-1", "2.5", " "):
            rows = [dict(r, Value=bad) if r["Title"] == "PeriodStartDay" else r for r in ROWS]
            r, _, _ = self.both(tg.u("emp"), rows=rows)
            self.assertEqual((r["configStatus"], r["missing"]), (cfg.CONFIG_INVALID, ["PeriodStartDay"]), repr(bad))
        rows = [dict(r, Value="") if r["Title"] == "PeriodStartDay" else r for r in ROWS]
        self.assertEqual(self.both(tg.u("emp"), rows=rows)[0]["config"]["PeriodStartDay"], 26, "an empty site value falls back to the registry")
        for bad in ("4,5", ".5", "5.", "abc", "25"):
            rows = [dict(r, Value=bad) if r["Title"] == "WarnEntry" else r for r in ROWS]
            r, _, _ = self.both(tg.u("emp"), rows=rows)
            self.assertEqual(r["configStatus"], cfg.CONFIG_INVALID, bad)
        rows = [dict(r, Value="maybe") if r["Title"] == "Switch" else r for r in ROWS]
        self.assertEqual(self.both(tg.u("emp"), rows=rows)[0]["configStatus"], cfg.CONFIG_INVALID)
        rows = [dict(r, Value="ON") if r["Title"] == "Switch" else r for r in ROWS]
        r, _, _ = self.both(tg.u("emp"), rows=rows)
        self.assertEqual((r["config"]["Switch"], r["interim"]), ("On", {}), "a non-interim site value is not marked interim")

    def test_AO13_interim_allowed_for_engineering(self):
        r, _, _ = self.both(tg.u("emp"))
        self.assertEqual(r["interim"], {"Switch": "Q-3 OPEN / CUSTOMER DECISION"})
        self.assertTrue(cfg.readiness(REG, OVL, "ENGINEERING", ["PeriodStartDay", "Switch"], ROWS)[0])

    def test_AO14_AO15_interim_rejects_uat_and_production(self):
        self.assertFalse(cfg.readiness(REG, OVL, "UAT", ["Switch"], ROWS)[0])
        prod = dict(OVL, environment="PRODUCTION")
        self.assertFalse(cfg.readiness(REG, prod, "PRODUCTION", ["Switch"], ROWS)[0])
        r, _, _ = self.both(tg.u("emp"), ovl=prod)
        self.assertIn("Switch", r["missing"], "interim value is unusable outside its environment")

    def test_AO16_one_correlation_id_end_to_end(self):
        r, ev, run = self.both(tg.u("emp"), cid="run-corr-1")
        self.assertEqual((r["correlationId"], ev.CorrelationId), ("run-corr-1", "run-corr-1"))

    def test_AO17_audit_contains_no_config(self):
        _, audit, _ = run_flow(tg.u("emp"))
        blob = json.dumps(audit)
        for s in ("PeriodStartDay", "Asia/Ho_Chi_Minh", "svc@", "WarnEntry"):
            self.assertNotIn(s, blob)

    def test_AO18_caller_provided_config_ignored(self):
        r, _, _ = self.both(tg.u("emp"), decoys={"Config": json.dumps({"PeriodStartDay": 1, "Switch": "On"})})
        self.assertEqual((r["config"]["PeriodStartDay"], r["config"]["Switch"]), (26, "Off"))

    def test_AO19_connection_reference_placeholders_only(self):
        blob = json.dumps(FLOW)
        self.assertNotIn('"connectionName"', blob)
        refs = set(re.findall(r'"connectionReferenceLogicalName": "([^"]+)"', blob))
        self.assertEqual(refs, {"<PFX>_CR_SharePoint_OpsService", "<PFX>_CR_O365Users_Invoker"})
        self.assertIsNone(re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.(vn|com|net)\b", blob))
        get = next(a for k, a in FLOW.items() if k == "Settings_read")
        self.assertEqual(get["inputs"]["host"]["connectionReferenceLogicalName"], "<PFX>_CR_SharePoint_OpsService")
        prof = next(a for k, a in FLOW.items() if k == "Get_caller_profile")
        self.assertEqual(prof["inputs"]["host"]["connectionReferenceLogicalName"], "<PFX>_CR_O365Users_Invoker")

    def test_AO20_response_contains_no_sharepoint_internals(self):
        for upn in (tg.u("emp"), tg.u("stranger")):
            _, _, run = self.both(upn)
            blob = json.dumps(run.results["Respond"]["outputs"])
            for s in ("_api", "getbytitle", "AppSettings", "_Employees", "\"Id\"", "sites/", "itemId"):
                self.assertNotIn(s, blob, (upn, s))

    def test_AO21_settings_read_failure_fails_closed(self):
        f, _, _ = run_flow(tg.u("emp"), settings_fail=True)
        r, _ = ref(tg.u("emp"), rows=None)
        self.assertEqual(f, r)
        self.assertEqual((f["ok"], f["configStatus"], f["config"], len(f["missing"])), (True, cfg.CONFIG_UNRESOLVED, {}, 4))

    def test_AO22_real_registry_subset(self):
        if not (os.environ.get("TS_APP_SETTINGS") and os.environ.get("TS_APP_SETTINGS_OVERLAY")):
            self.skipTest("set the real registry/overlay")
        reg = json.load(open(os.environ["TS_APP_SETTINGS"], encoding="utf-8"))
        ovl = json.load(open(os.environ["TS_APP_SETTINGS_OVERLAY"], encoding="utf-8"))
        fl = baf.appstart_actions(site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit",
                                  environment=ENV, registry=reg, overlay=ovl)
        keys = {k[2:] for k in fl if k.startswith("S_")}
        self.assertEqual(keys, {"PayPeriodStartDay", "MaxHoursPerEntryWarn", "MaxHoursPerDayWarn", "ProjectAssignmentScoping"})
        self.assertNotIn("BusinessTimezone", json.dumps(fl["Client_config"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
