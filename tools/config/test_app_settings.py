"""AppSettings registry tests C01-C14 (offline; synthetic registry; run: python -m unittest test_app_settings).

Set TS_APP_SETTINGS=<app-settings-registry.json> (and optionally TS_APP_SETTINGS_OVERLAY=<overlay.json>) to also check the
real (confidential) registry.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "provisioning"))
sys.path.insert(0, os.path.join(HERE, "..", "audit"))
sys.path.insert(0, os.path.join(HERE, "..", "identity"))
import app_settings as cfg  # noqa: E402
import reference_data as rd  # noqa: E402
import schema_reconcile as sr  # noqa: E402

REG = {"settings": [
    {"key": "PeriodStartDay", "type": "int", "min": 1, "max": 28, "value": "26", "resolution": "RESOLVED"},
    {"key": "HalfDay", "type": "decimal", "min": 0, "max": 1, "value": "0.5", "resolution": "RESOLVED"},
    {"key": "AssignmentScoping", "type": "enum", "allowed": ["Off", "On"], "value": None, "proposedDefault": "Off",
     "resolution": "CUSTOMER DECISION", "decision": "Q-3"},
    {"key": "RetentionDays", "type": "int", "min": 1, "value": None, "resolution": "IT DECISION", "decision": "IT-8"},
    {"key": "LocalZone", "type": "iana_tz", "value": "Asia/Ho_Chi_Minh", "resolution": "RESOLVED"},
    {"key": "ServiceUpn", "type": "upn", "value": None, "environmentSpecific": True, "resolution": "ENVIRONMENT-SPECIFIC"},
    {"key": "Strict", "type": "bool", "value": "No", "resolution": "RESOLVED"},
]}
ALLOWED = "https://tenant-a.invalid/sites/app-staging"


class AppSettings(unittest.TestCase):
    def test_C01_valid_registry_resolves(self):
        self.assertEqual(cfg.validate_registry(REG), [])
        s = cfg.resolve(REG)
        self.assertEqual((s["PeriodStartDay"].status, s["PeriodStartDay"].value), (cfg.CONFIGURED, 26))
        self.assertEqual(s["HalfDay"].value, 0.5)
        self.assertIs(s["Strict"].value, False)

    def test_C02_unresolved_never_takes_proposed_default_and_gate_fails_closed(self):
        s = cfg.resolve(REG)
        self.assertEqual((s["AssignmentScoping"].status, s["AssignmentScoping"].value), (cfg.UNRESOLVED, None))
        self.assertIn("Q-3", s["AssignmentScoping"].detail)
        g = cfg.gate(s, "PeriodStartDay", "AssignmentScoping")
        self.assertEqual((g.enabled, g.code, g.missing), (False, cfg.CONFIG_UNRESOLVED, ("AssignmentScoping",)))
        self.assertTrue(cfg.gate(s, "PeriodStartDay", "HalfDay").enabled)
        self.assertFalse(cfg.gate(s, "NotAKey").enabled, "unknown keys fail closed too")

    def test_C03_invalid_site_value(self):
        for raw in ("0", "29", "26.0", "x", ""):
            s = cfg.resolve(REG, site_rows=[{"Title": "PeriodStartDay", "Value": raw}])
            if raw == "":
                self.assertEqual(s["PeriodStartDay"].status, cfg.CONFIGURED, "empty site value falls back to the registry")
                continue
            self.assertEqual(s["PeriodStartDay"].status, cfg.INVALID, raw)
            self.assertEqual(cfg.gate(s, "PeriodStartDay").code, cfg.CONFIG_INVALID)
        s = cfg.resolve(REG, site_rows=[{"Title": "HalfDay", "Value": "0,5"}])
        self.assertEqual(s["HalfDay"].status, cfg.INVALID, "locale comma refused")

    def test_C04_secrets_and_tenant_bindings_refused(self):
        for bad in ({"key": "ClientSecret", "type": "text", "resolution": "RESOLVED"},
                    {"key": "Note", "type": "text", "value": "password=abc", "resolution": "RESOLVED"},
                    {"key": "SiteLink", "type": "text", "value": "https://x.invalid/sites/a", "resolution": "RESOLVED"},
                    {"key": "GroupRef", "type": "text", "value": "0f0e0d0c-0b0a-0908-0706-050403020100", "resolution": "RESOLVED"},
                    {"key": "Flag", "type": "bool", "secret": True, "resolution": "RESOLVED"}):
            r = copy.deepcopy(REG)
            r["settings"].append(bad)
            self.assertTrue(cfg.validate_registry(r), bad["key"])
        s = cfg.resolve({"settings": [{"key": "Note", "type": "text", "resolution": "RESOLVED"}]},
                        site_rows=[{"Title": "Note", "Value": "Bearer abc"}])
        self.assertEqual(s["Note"].status, cfg.INVALID)

    def test_C05_registry_hygiene(self):
        for mutate in (lambda r: r["settings"].append(dict(r["settings"][0], key="periodstartday")),
                       lambda r: r["settings"][0].update(resolution="MAYBE"),
                       lambda r: r["settings"][0].update(type="date"),
                       lambda r: r["settings"][2].update(allowed=[]),
                       lambda r: r["settings"][5].update(value="svc@x.invalid"),
                       lambda r: r["settings"][2].update(value="Off", resolution="OPEN")):
            r = copy.deepcopy(REG)
            mutate(r)
            self.assertTrue(cfg.validate_registry(r))
        r = copy.deepcopy(REG)
        r["settings"][2].update(value="Off", resolution="OPEN", valueBasis="owner approved for staging, 2099-01-01")
        self.assertEqual(cfg.validate_registry(r), [], "a recorded basis allows an interim value")

    def test_C06_environment_specific_only_from_overlay(self):
        self.assertEqual(cfg.resolve(REG)["ServiceUpn"].status, cfg.UNRESOLVED)
        s = cfg.resolve(REG, overlay={"ServiceUpn": "Svc@Tenant-A.invalid"})
        self.assertEqual((s["ServiceUpn"].status, s["ServiceUpn"].value), (cfg.CONFIGURED, "svc@tenant-a.invalid"))
        self.assertEqual(cfg.resolve(REG, overlay={"ServiceUpn": "not-an-upn"})["ServiceUpn"].status, cfg.INVALID)

    def test_C07_precedence_site_over_overlay_over_registry(self):
        s = cfg.resolve(REG, overlay={"PeriodStartDay": "25"}, site_rows=[{"Title": "periodstartday", "Value": "24"}])
        self.assertEqual((s["PeriodStartDay"].value, s["PeriodStartDay"].detail), (24, "site"))
        self.assertEqual(cfg.resolve(REG, overlay={"PeriodStartDay": "25"})["PeriodStartDay"].value, 25)

    def test_C08_seed_rows(self):
        rows = {r["Title"]: r for r in cfg.seed_rows(REG)}
        self.assertEqual(set(rows), {d["key"] for d in REG["settings"]})
        self.assertEqual((rows["PeriodStartDay"]["Value"], rows["HalfDay"]["Value"], rows["Strict"]["Value"]), ("26", "0.5", "No"))
        self.assertEqual((rows["AssignmentScoping"]["Value"], rows["RetentionDays"]["Value"], rows["ServiceUpn"]["Value"]), ("", "", ""))
        back = cfg.resolve(REG, site_rows=list(rows.values()))
        self.assertEqual({k: v.status for k, v in back.items()}, {k: v.status for k, v in cfg.resolve(REG).items()},
                         "seeded rows read back to the same resolution")

    def test_C09_seed_is_idempotent_and_admin_changes_are_not_overwritten(self):
        rules = {"key": "Title", "required": ["Title"], "compare": ["Value"]}
        items = []

        class C(rd.ItemClient):
            def create_item(self, lst, values):
                items.append(dict(values))
        schema = [sr.Finding(sr.OK, "AppSettings")]
        r1 = rd.apply_items("AppSettings", cfg.seed_rows(REG), items, rules, C(), ALLOWED, allowed_url=ALLOWED,
                            schema_findings=schema, dry_run=False)
        self.assertEqual(len(r1.executed), len(REG["settings"]))
        next(i for i in items if i["Title"] == "AssignmentScoping")["Value"] = "On"  # admin decision recorded on the site
        r2 = rd.apply_items("AppSettings", cfg.seed_rows(REG), items, rules, C(), ALLOWED, allowed_url=ALLOWED,
                            schema_findings=schema, dry_run=False)
        self.assertEqual(r2.executed, [])
        f = rd.reconcile_items("AppSettings", cfg.seed_rows(REG), items, rules)
        self.assertEqual(next(x for x in f if x.key == "AssignmentScoping").status, rd.DRIFT)
        self.assertEqual(cfg.resolve(REG, site_rows=items)["AssignmentScoping"].value, "On")

    def test_C10_drift_report(self):
        rows = cfg.seed_rows(REG) + [{"Title": "Legacy", "Value": "1"}]
        next(r for r in rows if r["Title"] == "HalfDay")["Value"] = "0.25"
        next(r for r in rows if r["Title"] == "PeriodStartDay")["Value"] = "x"
        d = dict(cfg.drift(REG, rows))
        self.assertIn("UNKNOWN-KEY", d["Legacy"])
        self.assertIn("DIFFERS", d["HalfDay"])
        self.assertIn("INVALID", d["PeriodStartDay"])
        self.assertIn("UNRESOLVED", d["AssignmentScoping"])

    def test_C11_audit_retention_stays_disabled_while_unresolved(self):
        import audit_event as ae
        p = ae.RetentionPolicy.from_settings(cfg.plain(cfg.resolve(REG)) | {"AuditRetentionDays": cfg.plain(cfg.resolve(REG))["RetentionDays"]})
        self.assertEqual((p.status, p.purge_enabled), ("PENDING_IT_CUSTOMER_DECISION", False))
        s = cfg.resolve(REG, site_rows=[{"Title": "RetentionDays", "Value": "400"}])
        p = ae.RetentionPolicy.from_settings({"AuditRetentionDays": cfg.plain(s)["RetentionDays"]})
        self.assertEqual((p.status, p.days), ("CONFIGURED", 400))

    def test_C12_scope_switch_unresolved_disables_assignment_dependent_path(self):
        import scope_resolver as scr  # noqa: F401  (consumer of the boolean switch)
        s = cfg.resolve(REG)
        g = cfg.gate(s, "AssignmentScoping")
        self.assertFalse(g.enabled)
        # A consumer must deny with g.code instead of choosing On or Off itself.
        self.assertEqual(g.code, "CONFIG_UNRESOLVED")
        s = cfg.resolve(REG, site_rows=[{"Title": "AssignmentScoping", "Value": "off"}])
        self.assertEqual((cfg.gate(s, "AssignmentScoping").enabled, s["AssignmentScoping"].value), (True, "Off"))

    def test_C13_bool_and_enum_parsing_is_case_insensitive_and_strict(self):
        for raw, want in (("YES", True), ("off", False), ("True", True)):
            self.assertEqual(cfg.resolve(REG, site_rows=[{"Title": "Strict", "Value": raw}])["Strict"].value, want)
        self.assertEqual(cfg.resolve(REG, site_rows=[{"Title": "Strict", "Value": "1"}])["Strict"].status, cfg.INVALID)
        self.assertEqual(cfg.resolve(REG, site_rows=[{"Title": "AssignmentScoping", "Value": "Maybe"}])["AssignmentScoping"].status, cfg.INVALID)

    def test_C14_no_tenant_values_in_code(self):
        import re
        with open(os.path.join(HERE, "app_settings.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIsNone(re.search(r"https?://[a-z0-9-]+\.sharepoint\.com", src, re.I))
        self.assertIsNone(re.search(r"@[a-z0-9-]+\.(vn|com)\b", src, re.I))


@unittest.skipUnless(os.environ.get("TS_APP_SETTINGS"), "set TS_APP_SETTINGS to check the real registry")
class RealRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.environ["TS_APP_SETTINGS"], encoding="utf-8") as fh:
            cls.reg = json.load(fh)
        cls.overlay = {}
        if os.environ.get("TS_APP_SETTINGS_OVERLAY"):
            with open(os.environ["TS_APP_SETTINGS_OVERLAY"], encoding="utf-8") as fh:
                cls.overlay = json.load(fh)["values"]
        cls.s = cfg.resolve(cls.reg, cls.overlay)

    def test_registry_valid_and_complete(self):
        self.assertEqual(cfg.validate_registry(self.reg), [])
        keys = {d["key"] for d in self.reg["settings"]}
        backlog_t0471 = {"PayPeriodStartDay", "HoursPerManDay", "SaturdayStdDay", "SundayStdDay", "NormalHourTypeCode",
                         "MaxHoursPerEntryWarn", "MaxHoursPerDayWarn", "ProjectAssignmentScoping", "LeaderCanUnapprove",
                         "GradeBandBoundary", "CostRateMode", "ServiceAccountUpn"}
        self.assertTrue(backlog_t0471 <= keys, backlog_t0471 - keys)
        self.assertTrue({"AuditRetentionDays", "ConfidentialAuditRetentionDays", "BusinessTimeZone"} <= keys)
        for d in self.reg["settings"]:
            self.assertTrue(d.get("source"), d["key"])

    def test_blocked_decisions_stay_unresolved(self):
        for k in ("ProjectAssignmentScoping", "AuditRetentionDays", "ConfidentialAuditRetentionDays"):
            self.assertEqual(self.s[k].status, cfg.UNRESOLVED, k)
        self.assertFalse(cfg.gate(self.s, "ProjectAssignmentScoping").enabled)

    def test_business_time_zone(self):
        self.assertEqual((self.s["BusinessTimeZone"].value, self.s["BusinessUtcOffsetMinutes"].value), ("Asia/Ho_Chi_Minh", 420))


if __name__ == "__main__":
    unittest.main(verbosity=2)
