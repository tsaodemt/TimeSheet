"""D-3 deployment readiness tests DR01-DR10 (offline; synthetic configuration)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d3_acceptance as d3  # noqa: E402
import d3_readiness as dr  # noqa: E402

REG = {"settings": [{"key": "PeriodStartDay", "type": "int", "value": "26", "resolution": "RESOLVED"},
                    {"key": "Switch", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "CUSTOMER DECISION"}],
       "externalConfig": [{"key": "ServiceAccountUpn", "type": "upn", "where": "environment variable", "requiredFor": ["UAT", "PRODUCTION"]}]}
INTERIM = {"value": "Off", "interim": True, "basis": "eng", "approvedBy": "owner", "approvedOn": "2099-01-01",
           "customerDecision": "Q-3 OPEN", "allowedEnvironments": ["STAGING"]}
SVC = "svc-operational@tenant-a.invalid"
OVL = {"environment": "STAGING", "values": {"Switch": INTERIM}, "external": {"ServiceAccountUpn": SVC}}
MAN = {"environmentVariables": [{"schemaName": "ts_OpsSiteUrl", "purpose": "site", "sourceDecision": "AD-8", "r1": True,
                                 "values": {"staging": "https://tenant-a.invalid/sites/app-staging"}}],
       "connectionReferences": [{"schemaName": "ts_CR_SharePoint_OpsService", "connectorId": "shared_sharepointonline", "purpose": "service",
                                 "r1": True, "connectionOwner": SVC},
                                {"schemaName": "ts_CR_O365Users_Invoker", "connectorId": "shared_office365users", "purpose": "trusted caller",
                                 "r1": True, "connectionOwner": "<run-only user>", "invokerOwned": True}]}
LISTS = ("AppSettings", "Phases")
PERMS = {t: {"unique": True, "assignments": [{"principal_id": 7, "login": "c:0-.f|owners", "roles": ["Full Control"]},
                                              {"principal_id": 77, "login": "i:0#.f|membership|" + SVC, "roles": ["Read"]}]} for t in LISTS}
REFS = ("ts_CR_SharePoint_OpsService", "ts_CR_O365Users_Invoker")
ACCEPTED = {"criteria": {c: {"met": True, "evidence": "read-only check (synthetic)"} for c in d3.IDS}}


def acceptance(**unmet):
    r = {"criteria": dict(ACCEPTED["criteria"])}
    for c, ev in unmet.items():
        r["criteria"][c] = {"met": False, "evidence": ev}
    return r


def check(purpose="ENGINEERING", overlay=OVL, manifest=MAN, perms=PERMS, env="STAGING", **kw):
    return dr.readiness(purpose, environment=env, overlay=overlay, registry=REG, manifest=manifest, permissions=perms,
                        required_lists=LISTS, required_settings=("PeriodStartDay", "Switch"), required_connection_refs=REFS,
                        temporary_accounts=("temp-test-svc", "spike-svc@tenant-a.invalid"),
                        **dict({"identity_acceptance": ACCEPTED}, **kw))


def codes(r):
    return sorted({c for c, _ in r[1]})


class D3Readiness(unittest.TestCase):
    def test_DR01_all_present_engineering_ready(self):
        self.assertEqual(check(), (True, []))

    def test_DR02_service_identity_missing(self):
        o = copy.deepcopy(OVL)
        o["external"] = {}
        self.assertIn("SERVICE_IDENTITY_MISSING", codes(check(overlay=o)))

    def test_DR03_temporary_identity_refused(self):
        o = copy.deepcopy(OVL)
        o["external"]["ServiceAccountUpn"] = "temp-test-svc@tenant-a.invalid"
        self.assertIn("SERVICE_IDENTITY_TEMPORARY", codes(check(overlay=o)))

    def test_DR04_connection_reference_missing_gated_or_foreign_owner(self):
        m = copy.deepcopy(MAN)
        m["connectionReferences"] = m["connectionReferences"][1:]
        self.assertIn("CONNECTION_REFERENCE_MISSING", codes(check(manifest=m)))
        m = copy.deepcopy(MAN)
        m["connectionReferences"][0].update(gated=True, gatedBy="D-3")
        self.assertIn("CONNECTION_REFERENCE_UNBOUND", codes(check(manifest=m)))
        m = copy.deepcopy(MAN)
        m["connectionReferences"][0]["connectionOwner"] = "someone@tenant-a.invalid"
        self.assertIn("CONNECTION_REFERENCE_OWNER_MISMATCH", codes(check(manifest=m)))

    def test_DR05_read_permission_missing(self):
        p = copy.deepcopy(PERMS)
        p["Phases"]["assignments"] = p["Phases"]["assignments"][:1]
        self.assertEqual(codes(check(perms=p)), ["READ_PERMISSION_MISSING"])
        self.assertIn("READ_PERMISSION_MISSING", codes(check(perms={"AppSettings": PERMS["AppSettings"]})))

    def test_DR06_broader_service_rights_are_drift(self):
        p = copy.deepcopy(PERMS)
        p["AppSettings"]["assignments"][1]["roles"] = ["Read", "Edit"]
        self.assertEqual(codes(check(perms=p)), ["SECURITY_DRIFT"])
        p = copy.deepcopy(PERMS)
        p["AppSettings"]["unique"] = False
        self.assertIn("SECURITY_DRIFT", codes(check(perms=p)))

    def test_DR07_environment_binding_unresolved(self):
        m = copy.deepcopy(MAN)
        m["environmentVariables"][0]["values"]["staging"] = "<TBD>"
        self.assertIn("ENV_BINDING_UNRESOLVED", codes(check(manifest=m)))

    def test_DR08_interim_refused_for_uat_and_production(self):
        self.assertIn("CONFIG_NOT_READY", codes(check("UAT")))
        o = dict(copy.deepcopy(OVL), environment="PRODUCTION")
        r = check("PRODUCTION", overlay=o, env="PRODUCTION")
        self.assertIn("CONFIG_NOT_READY", codes(r))

    def test_DR09_identity_comes_from_configuration_only(self):
        src = open(os.path.join(HERE, "d3_readiness.py"), encoding="utf-8").read()
        self.assertNotRegex(src, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.(vn|com|net)\b")
        o = copy.deepcopy(OVL)
        o["external"]["ServiceAccountUpn"] = "other@tenant-a.invalid"
        self.assertIn("READ_PERMISSION_MISSING", codes(check(overlay=o)), "a different configured identity is not the one granted")

    def test_DR10_unknown_purpose_refused(self):
        with self.assertRaises(ValueError):
            check("GO-LIVE")

    def test_DR11_selected_identity_blocked_only_by_unmet_acceptance_criteria(self):
        ok, b = check(identity_acceptance=acceptance(CUSTODIAN_LIFECYCLE_DOCUMENTED="custodian not named"))
        self.assertFalse(ok)
        self.assertEqual(b, [("D3_OPERATIONAL_READINESS_INCOMPLETE", "CUSTODIAN_LIFECYCLE_DOCUMENTED: " + dict(d3.CRITERIA)["CUSTODIAN_LIFECYCLE_DOCUMENTED"])])
        self.assertNotIn("SERVICE_IDENTITY_MISSING", codes((ok, b)))
        self.assertFalse(any("new service account" in d.lower() for _, d in b))
        ok, b = check(identity_acceptance=None)  # no evidence recorded: every criterion unmet (fail closed)
        self.assertEqual([d.split(":")[0] for c, d in b if c == "D3_OPERATIONAL_READINESS_INCOMPLETE"], list(d3.IDS))

    def test_DR12_acceptance_needs_met_and_evidence(self):
        self.assertEqual(d3.evaluate(ACCEPTED), (d3.DONE, []))
        r = acceptance(RETAINED="scheduled for deletion")
        self.assertEqual(d3.evaluate(r), (d3.BLOCKED, [("RETAINED", dict(d3.CRITERIA)["RETAINED"])]))
        r = {"criteria": dict(ACCEPTED["criteria"], ENABLED={"met": True, "evidence": " "})}
        self.assertEqual(d3.evaluate(r)[1][0][0], "ENABLED", "met without evidence is unmet")
        self.assertEqual(len(d3.IDS), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
