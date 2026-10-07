"""AppSettings registry tests C01-C25 (offline; synthetic registry; run: python -m unittest test_app_settings).

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
    {"key": "EnvLabel", "type": "enum", "allowed": ["STAGING", "PRODUCTION"], "value": None, "environmentSpecific": True,
     "resolution": "ENVIRONMENT-SPECIFIC"},
    {"key": "Strict", "type": "bool", "value": "No", "resolution": "RESOLVED"},
    {"key": "LocalOffset", "type": "int", "derived": {"from": "LocalZone", "function": "utcOffsetMinutes"}, "resolution": "RESOLVED"},
], "externalConfig": [
    {"key": "ServiceUpn", "type": "upn", "where": "solution environment variable / connection ownership",
     "requiredFor": ["UAT", "PRODUCTION"], "resolution": "BLOCKED", "decision": "D-3"}]}
INTERIM = {"value": "Off", "interim": True, "basis": "owner interim for engineering", "approvedBy": "project owner",
           "approvedOn": "2099-01-01", "customerDecision": "Q-3 OPEN", "allowedEnvironments": ["STAGING"]}
STG = {"environment": "STAGING", "values": {"EnvLabel": "STAGING", "AssignmentScoping": INTERIM}, "external": {}}
PRD = {"environment": "PRODUCTION", "values": {"EnvLabel": "PRODUCTION"}, "external": {"ServiceUpn": "svc@tenant-a.invalid"}}
REQ = ("PeriodStartDay", "AssignmentScoping", "LocalZone", "LocalOffset")
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
                       lambda r: r["settings"][5].update(value="STAGING"),
                       lambda r: r["settings"][2].update(value="Off", resolution="OPEN")):
            r = copy.deepcopy(REG)
            mutate(r)
            self.assertTrue(cfg.validate_registry(r))
        r = copy.deepcopy(REG)
        r["settings"][2].update(value="Off", resolution="OPEN", valueBasis="owner approved for staging, 2099-01-01")
        self.assertEqual(cfg.validate_registry(r), [], "a recorded basis allows an interim value")

    def test_C06_environment_specific_only_from_overlay(self):
        self.assertEqual(cfg.resolve(REG)["EnvLabel"].status, cfg.UNRESOLVED)
        s = cfg.resolve(REG, overlay={"EnvLabel": "staging"})
        self.assertEqual((s["EnvLabel"].status, s["EnvLabel"].value), (cfg.CONFIGURED, "STAGING"))
        self.assertEqual(cfg.resolve(REG, overlay={"EnvLabel": "DEV"})["EnvLabel"].status, cfg.INVALID)

    def test_C07_precedence_site_over_overlay_over_registry(self):
        s = cfg.resolve(REG, overlay={"PeriodStartDay": "25"}, site_rows=[{"Title": "periodstartday", "Value": "24"}])
        self.assertEqual((s["PeriodStartDay"].value, s["PeriodStartDay"].detail), (24, "site"))
        self.assertEqual(cfg.resolve(REG, overlay={"PeriodStartDay": "25"})["PeriodStartDay"].value, 25)

    def test_C08_seed_rows(self):
        rows = {r["Title"]: r for r in cfg.seed_rows(REG)}
        self.assertEqual(set(rows), {d["key"] for d in REG["settings"] if not d.get("derived")})
        self.assertEqual((rows["PeriodStartDay"]["Value"], rows["HalfDay"]["Value"], rows["Strict"]["Value"]), ("26", "0.5", "No"))
        self.assertEqual((rows["AssignmentScoping"]["Value"], rows["RetentionDays"]["Value"], rows["EnvLabel"]["Value"]), ("", "", ""))
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
        self.assertEqual(len(r1.executed), sum(1 for d in REG["settings"] if not d.get("derived")))
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

    # ---- project-owner decisions 2026-10-07 (S04.7-Q1, S04.7-Q2, B-03 interim)

    def test_C15_time_zone_is_canonical_and_offset_is_derived(self):
        s = cfg.resolve(REG)
        self.assertEqual((s["LocalOffset"].status, s["LocalOffset"].value), (cfg.CONFIGURED, 420))
        self.assertIn("derived from LocalZone", s["LocalOffset"].detail)
        s = cfg.resolve(REG, site_rows=[{"Title": "LocalZone", "Value": "UTC"}])
        self.assertEqual(s["LocalOffset"].value, 0, "the offset follows the zone; it cannot diverge")
        self.assertEqual(cfg.resolve(REG, site_rows=[{"Title": "LocalZone", "Value": "Mars/Base"}])["LocalOffset"].status, cfg.UNRESOLVED)

    def test_C16_offset_cannot_be_set_independently(self):
        s = cfg.resolve(REG, overlay={"LocalOffset": "0"}, site_rows=[{"Title": "LocalOffset", "Value": "60"}])
        self.assertEqual(s["LocalOffset"].value, 420, "stored values for a derived setting are ignored")
        self.assertTrue(cfg.validate_overlay(REG, {"values": {"LocalOffset": "0"}}))
        self.assertIn("DERIVED", dict(cfg.drift(REG, [{"Title": "LocalOffset", "Value": "60"}]))["LocalOffset"])
        for bad in ({"value": "420"}, {"proposedDefault": "420"}, {"derived": {"from": "Nope", "function": "utcOffsetMinutes"}}):
            r = copy.deepcopy(REG)
            r["settings"][-1].update(bad)
            self.assertTrue(cfg.validate_registry(r), bad)
        self.assertNotIn("LocalOffset", {x["Title"] for x in cfg.seed_rows(REG)}, "derived settings are not seeded")

    def test_C17_service_account_is_environment_configuration_not_appsettings(self):
        r = copy.deepcopy(REG)
        r["settings"].append({"key": "ServiceUpn", "type": "text", "resolution": "BLOCKED"})
        self.assertTrue(any("environment configuration" in x for x in cfg.validate_registry(r)))
        r = copy.deepcopy(REG)
        r["settings"].append({"key": "RunAs", "type": "upn", "resolution": "ENVIRONMENT-SPECIFIC"})
        self.assertTrue(any("identity bindings" in x for x in cfg.validate_registry(r)))
        self.assertNotIn("ServiceUpn", {x["Title"] for x in cfg.seed_rows(REG, STG)})
        self.assertIn("ENVIRONMENT-CONFIG", dict(cfg.drift(REG, [{"Title": "ServiceUpn", "Value": "x@y.invalid"}]))["ServiceUpn"])
        self.assertTrue(cfg.validate_overlay(REG, {"environment": "STAGING", "values": {"ServiceUpn": "x@y.invalid"}}))

    def test_C18_missing_production_service_account_fails_production_readiness(self):
        prd = copy.deepcopy(PRD)
        prd["values"]["AssignmentScoping"] = "Off"
        r = copy.deepcopy(REG)
        r["settings"][2].update(resolution="RESOLVED", value="Off")  # pretend the customer decided
        ok, b = cfg.readiness(r, prd, "PRODUCTION", REQ)
        self.assertEqual((ok, b), (True, []))
        prd["external"] = {}
        ok, b = cfg.readiness(r, prd, "PRODUCTION", REQ)
        self.assertFalse(ok)
        self.assertIn("ServiceUpn", dict(b))

    def test_C19_staging_interim_is_identifiable(self):
        self.assertEqual(cfg.validate_overlay(REG, STG), [])
        s = cfg.resolve(REG, STG)
        a = s["AssignmentScoping"]
        self.assertEqual((a.status, a.value, a.interim), (cfg.CONFIGURED, "Off", True))
        self.assertIn("owner interim", a.basis)
        row = next(x for x in cfg.seed_rows(REG, STG) if x["Title"] == "AssignmentScoping")
        self.assertTrue(row["Description"].startswith("[INTERIM"))
        self.assertIn("INTERIM", dict(cfg.drift(REG, cfg.seed_rows(REG, STG), STG))["AssignmentScoping"])
        self.assertTrue(cfg.gate(s, "AssignmentScoping").enabled, "engineering use is allowed")
        self.assertFalse(cfg.gate(s, "AssignmentScoping", allow_interim=False).enabled)

    def test_C20_customer_decision_stays_open(self):
        self.assertEqual(next(d for d in REG["settings"] if d["key"] == "AssignmentScoping")["resolution"], "CUSTOMER DECISION")
        self.assertIsNone(next(d for d in REG["settings"] if d["key"] == "AssignmentScoping")["value"])
        self.assertEqual(cfg.resolve(REG)["AssignmentScoping"].status, cfg.UNRESOLVED, "without the STAGING overlay: unresolved")
        ok, b = cfg.readiness(REG, STG, "UAT", REQ)
        self.assertFalse(ok)
        self.assertTrue(any("interim" in why for k, why in b if k == "AssignmentScoping"), "UAT/customer acceptance refuses interim")

    def test_C21_production_cannot_use_interim(self):
        bad = copy.deepcopy(PRD)
        bad["values"]["AssignmentScoping"] = dict(INTERIM, allowedEnvironments=["STAGING", "PRODUCTION"])
        self.assertTrue(cfg.validate_overlay(REG, bad))
        self.assertEqual(cfg.resolve(REG, bad)["AssignmentScoping"].status, cfg.UNRESOLVED)
        ok, b = cfg.readiness(REG, bad, "PRODUCTION", REQ)
        self.assertFalse(ok)
        moved = copy.deepcopy(STG)
        moved["environment"] = "PRODUCTION"  # a STAGING interim copied into production
        self.assertEqual(cfg.resolve(REG, moved)["AssignmentScoping"].status, cfg.UNRESOLVED)
        prd = copy.deepcopy(PRD)
        ok, b = cfg.readiness(REG, prd, "PRODUCTION", REQ, site_rows=[{"Title": "AssignmentScoping", "Value": "Off"}])
        self.assertFalse(ok, "a site value cannot stand in for an open customer decision")
        self.assertIn("decision not approved", dict(b)["AssignmentScoping"])

    def test_C22_engineering_readiness_accepts_interim_in_staging_only(self):
        self.assertEqual(cfg.readiness(REG, STG, "ENGINEERING", REQ), (True, []))
        ok, b = cfg.readiness(REG, dict(STG, environment="DEV"), "ENGINEERING", REQ)
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            cfg.readiness(REG, STG, "GO-LIVE", REQ)

    def test_C23_interim_needs_its_full_basis(self):
        for f in ("basis", "approvedBy", "approvedOn", "customerDecision", "allowedEnvironments"):
            o = copy.deepcopy(STG)
            o["values"]["AssignmentScoping"].pop(f)
            self.assertTrue(cfg.validate_overlay(REG, o), f)

    def test_C24_unresolved_fails_closed_in_every_purpose(self):
        for purpose in cfg.PURPOSES:
            ok, b = cfg.readiness(REG, {"environment": "STAGING", "values": {}}, purpose, REQ)
            self.assertFalse(ok, purpose)
            self.assertIn("AssignmentScoping", dict(b))

    def test_C25_secrets_and_tenant_ids_rejected_in_overlay_values(self):
        r = {"settings": [{"key": "Note", "type": "text", "resolution": "RESOLVED"}]}
        for v in ("client_secret=x", "https://x.invalid/sites/a", "0f0e0d0c-0b0a-4908-8706-050403020100"):
            self.assertEqual(cfg.resolve(r, {"Note": v})["Note"].status, cfg.INVALID, v)


@unittest.skipUnless(os.environ.get("TS_APP_SETTINGS"), "set TS_APP_SETTINGS to check the real registry")
class RealRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.environ["TS_APP_SETTINGS"], encoding="utf-8") as fh:
            cls.reg = json.load(fh)
        cls.overlay = None
        if os.environ.get("TS_APP_SETTINGS_OVERLAY"):
            with open(os.environ["TS_APP_SETTINGS_OVERLAY"], encoding="utf-8") as fh:
                cls.overlay = json.load(fh)
        cls.base = cfg.resolve(cls.reg)
        cls.s = cfg.resolve(cls.reg, cls.overlay)

    def test_registry_valid_and_complete(self):
        self.assertEqual(cfg.validate_registry(self.reg), [])
        keys = {d["key"] for d in self.reg["settings"]}
        backlog_t0471 = {"PayPeriodStartDay", "HoursPerManDay", "SaturdayStdDay", "SundayStdDay", "NormalHourTypeCode",
                         "MaxHoursPerEntryWarn", "MaxHoursPerDayWarn", "ProjectAssignmentScoping", "LeaderCanUnapprove",
                         "GradeBandBoundary", "CostRateMode"}
        self.assertTrue(backlog_t0471 <= keys, backlog_t0471 - keys)
        self.assertTrue({"AuditRetentionDays", "ConfidentialAuditRetentionDays", "BusinessTimezone"} <= keys)
        ext = {e["key"] for e in self.reg.get("externalConfig", [])}
        self.assertIn("ServiceAccountUpn", ext, "S04.7-Q2: environment configuration, not an AppSettings row")
        self.assertNotIn("ServiceAccountUpn", keys)
        for d in self.reg["settings"]:
            self.assertTrue(d.get("source"), d["key"])

    def test_blocked_decisions_stay_unresolved(self):
        for k in ("ProjectAssignmentScoping", "AuditRetentionDays", "ConfidentialAuditRetentionDays"):
            self.assertEqual(self.base[k].status, cfg.UNRESOLVED, k)
        for k in ("AuditRetentionDays", "ConfidentialAuditRetentionDays"):
            self.assertEqual(self.s[k].status, cfg.UNRESOLVED, k)
        d = next(x for x in self.reg["settings"] if x["key"] == "ProjectAssignmentScoping")
        self.assertEqual((d["resolution"], d.get("value")), ("CUSTOMER DECISION", None), "B-03 stays a customer decision")

    def test_staging_b03_interim_is_engineering_only(self):
        self.assertEqual(cfg.validate_overlay(self.reg, self.overlay), [])
        a = self.s["ProjectAssignmentScoping"]
        self.assertEqual((a.status, a.value, a.interim), (cfg.CONFIGURED, "Off", True))
        req = ("ProjectAssignmentScoping", "PayPeriodStartDay", "BusinessTimezone")
        self.assertTrue(cfg.readiness(self.reg, self.overlay, "ENGINEERING", req)[0])
        self.assertFalse(cfg.readiness(self.reg, self.overlay, "UAT", req)[0])
        prod = dict(self.overlay, environment="PRODUCTION")
        ok, b = cfg.readiness(self.reg, prod, "PRODUCTION", req)
        self.assertFalse(ok)
        self.assertIn("ServiceAccountUpn", dict(b), "D-3 unresolved: no production service account")

    def test_business_time_zone(self):
        self.assertEqual(self.s["BusinessTimezone"].value, "Asia/Ho_Chi_Minh")
        off = next(x for x in self.reg["settings"] if x["key"] == "BusinessUtcOffsetMinutes")
        self.assertEqual(off["derived"], {"from": "BusinessTimezone", "function": "utcOffsetMinutes"})
        self.assertEqual((self.s["BusinessUtcOffsetMinutes"].value, self.s["BusinessUtcOffsetMinutes"].detail),
                         (420, "derived from BusinessTimezone"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
