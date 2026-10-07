"""AppOpen client-config contract tests CC01-CC08 (offline). Set TS_APP_SETTINGS / TS_APP_SETTINGS_OVERLAY for the real registry."""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import app_settings as cfg  # noqa: E402
import client_config as cc  # noqa: E402

REG = {"settings": [
    {"key": "PeriodStartDay", "type": "int", "value": "26", "resolution": "RESOLVED", "exposeToClient": True},
    {"key": "WarnEntry", "type": "decimal", "value": "4", "resolution": "CUSTOMER DECISION", "valueBasis": "spec default", "exposeToClient": True},
    {"key": "Switch", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "CUSTOMER DECISION", "exposeToClient": True},
    {"key": "Zone", "type": "iana_tz", "value": "Asia/Ho_Chi_Minh", "resolution": "RESOLVED"},
    {"key": "RetentionDays", "type": "int", "value": None, "resolution": "IT DECISION"},
    {"key": "Offset", "type": "int", "derived": {"from": "Zone", "function": "utcOffsetMinutes"}, "resolution": "RESOLVED"}],
    "externalConfig": [{"key": "ServiceUpn", "type": "upn", "where": "environment variable"}]}
OVL = {"environment": "STAGING", "values": {"Switch": {"value": "Off", "interim": True, "basis": "eng", "approvedBy": "owner",
                                                       "approvedOn": "2099-01-01", "customerDecision": "Q-3 OPEN",
                                                       "allowedEnvironments": ["STAGING"]}}, "external": {}}


class ClientConfig(unittest.TestCase):
    def test_CC01_only_exposed_keys_are_returned(self):
        r = cc.client_config(REG, OVL, [], identity_ok=True)
        self.assertEqual((r["status"], set(r["settings"])), ("OK", {"PeriodStartDay", "WarnEntry", "Switch"}))

    def test_CC02_server_only_values_never_leave(self):
        r = cc.client_config(REG, OVL, [], identity_ok=True)
        self.assertFalse({"Zone", "RetentionDays", "Offset", "ServiceUpn"} & set(r["settings"]))
        for bad in ({"key": "Zone"}, {"key": "Offset"}, {"key": "RetentionDays"}):
            reg = copy.deepcopy(REG)
            next(d for d in reg["settings"] if d["key"] == bad["key"])["exposeToClient"] = True
            if bad["key"] != "Zone":
                self.assertTrue(cc.validate_exposure(reg), bad)

    def test_CC03_interim_is_visible(self):
        r = cc.client_config(REG, OVL, [], identity_ok=True)
        self.assertEqual(r["interim"], {"Switch": "Q-3 OPEN"})

    def test_CC04_unresolved_required_key_fails_closed(self):
        r = cc.client_config(REG, {"environment": "STAGING", "values": {}}, [], identity_ok=True)
        self.assertEqual((r["status"], r["missing"], "Switch" in r["settings"]), (cfg.CONFIG_UNRESOLVED, ["Switch"], False))

    def test_CC05_invalid_value_fails_closed(self):
        r = cc.client_config(REG, OVL, [{"Title": "PeriodStartDay", "Value": "x"}], identity_ok=True)
        self.assertEqual((r["status"], r["missing"]), (cfg.CONFIG_INVALID, ["PeriodStartDay"]))

    def test_CC06_denied_identity_gets_nothing(self):
        self.assertEqual(cc.client_config(REG, OVL, [], identity_ok=False)["settings"], {})

    def test_CC07_interim_outside_its_environment_is_missing(self):
        r = cc.client_config(REG, dict(OVL, environment="PRODUCTION"), [], identity_ok=True)
        self.assertIn("Switch", r["missing"])

    def test_CC08_site_value_wins_but_is_typed(self):
        r = cc.client_config(REG, OVL, [{"Title": "PeriodStartDay", "Value": "25"}], identity_ok=True)
        self.assertEqual(r["settings"]["PeriodStartDay"], 25)


@unittest.skipUnless(os.environ.get("TS_APP_SETTINGS") and os.environ.get("TS_APP_SETTINGS_OVERLAY"), "set the real registry/overlay")
class RealRegistry(unittest.TestCase):
    def test_real_client_subset(self):
        reg = json.load(open(os.environ["TS_APP_SETTINGS"], encoding="utf-8"))
        ovl = json.load(open(os.environ["TS_APP_SETTINGS_OVERLAY"], encoding="utf-8"))
        self.assertEqual(cc.validate_exposure(reg), [])
        r = cc.client_config(reg, ovl, [], identity_ok=True)
        self.assertEqual(set(r["settings"]), {"PayPeriodStartDay", "MaxHoursPerEntryWarn", "MaxHoursPerDayWarn", "ProjectAssignmentScoping"})
        self.assertNotIn("BusinessTimezone", r["settings"])
        self.assertEqual(r["interim"], {"ProjectAssignmentScoping": "B-03 OPEN / CUSTOMER DECISION"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
