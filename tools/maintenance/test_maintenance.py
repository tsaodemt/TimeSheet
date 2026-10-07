"""Protected configuration / master-data maintenance tests AP01-AP24 (offline; synthetic data).

AP01-AP05, AP15, AP16, AP20: list permission hardening plan (tools/provisioning/permission_plan.py).
AP06-AP14, AP17-AP19, AP21-AP24: guarded maintenance (tools/maintenance/maintenance.py) on real guard decisions.
Set TS_SCOPE_CONFIG / TS_APP_SETTINGS / TS_APP_SETTINGS_OVERLAY to also run against the real role seed and registry.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "provisioning"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config")):
    sys.path.insert(0, p)
import guard as G  # noqa: E402
import maintenance as M  # noqa: E402
import permission_plan as pp  # noqa: E402
from identity_resolver import Config, Employee, Role, TrustedIdentity  # noqa: E402

DOM = "tenant-a.invalid"
SCOPES = {"scopes": {"EMP": {"TS.ViewOwn": "self"}, "HR": {"EMP.Maintain": "company", "MD.Maintain": "restricted:org, positions"},
                     "ADM": {"EMP.Maintain": "company", "MD.Maintain": "company", "ROLE.Admin": "company"}}, "pending": []}
if os.environ.get("TS_SCOPE_CONFIG"):
    SCOPES = json.load(open(os.environ["TS_SCOPE_CONFIG"], encoding="utf-8"))
POLICY = G.Policy.from_scope_config(SCOPES)
CFG = Config(allowed_domains=[DOM], roles=[Role(k, "g-" + k.lower()) for k in ("EMP", "HR", "ADM", "ITS", "EXE")])
EMPS = [Employee(1, "E1", "staff@" + DOM, True, "D1"), Employee(2, "E2", "hr@" + DOM, True, "D1"), Employee(3, "E3", "admin@" + DOM, True, "D1")]


def guard(upn, roles, action):
    ident = TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])
    lk = lambda n: [e for e in EMPS if e.account_upn == n]  # noqa: E731
    return G.authorize(ident, lk, lk, CFG, POLICY, action, "company", correlation_id="run-1",
                       ActorUpn="ceo@" + DOM, Role="ADM", Scope="company")


REG = {"settings": [
    {"key": "PeriodStartDay", "type": "int", "min": 1, "max": 28, "value": "26", "resolution": "RESOLVED"},
    {"key": "Switch", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "CUSTOMER DECISION", "decision": "Q-3"},
    {"key": "RetentionDays", "type": "int", "min": 1, "value": None, "resolution": "IT DECISION", "decision": "IT-8"},
    {"key": "Note", "type": "text", "value": "x", "resolution": "RESOLVED"},
    {"key": "Zone", "type": "iana_tz", "value": "Asia/Ho_Chi_Minh", "resolution": "RESOLVED"},
    {"key": "Offset", "type": "int", "derived": {"from": "Zone", "function": "utcOffsetMinutes"}, "resolution": "RESOLVED"},
    {"key": "EnvLabel", "type": "enum", "allowed": ["STAGING", "PRODUCTION"], "environmentSpecific": True, "resolution": "ENVIRONMENT-SPECIFIC"}],
    "externalConfig": [{"key": "ServiceUpn", "type": "upn", "where": "environment variable", "requiredFor": ["PRODUCTION"]}]}
INTERIM = {"value": "Off", "interim": True, "basis": "eng", "approvedBy": "owner", "approvedOn": "2099-01-01",
           "customerDecision": "Q-3 OPEN", "allowedEnvironments": ["STAGING"]}
OVL = {"environment": "STAGING", "values": {"EnvLabel": "STAGING", "Switch": INTERIM}, "external": {}}
CFG_ACTION = "CFG.Maintain"  # PROPOSED, not in the authorization seed -> denied until mapped
MD_POLICY = {
    "AppSettings": {"action": CFG_ACTION, "kind": "config", "operations": ["Update"], "fields": ["Value"], "auditAction": "MasterDataChange"},
    "Units": {"action": "MD.Maintain", "operations": ["Create", "Update", "SoftDelete"], "fields": ["Title", "UnitCode", "IsActive", "SortOrder"],
              "softDelete": "IsActive"},
    "Rates": {"action": "MD.Maintain", "operations": ["Create", "Update"], "fields": ["Title", "Factor", "IsNormal", "SortOrder"],
              "decisionFields": {"Factor": "HT-1 OPEN: approval semantics for factor changes not defined"},
              "invariants": {"IsNormal": lambda v, cur, reg, ovl: "IsNormal is derived from the normal-hour code setting" if v["IsNormal"] != (cur or {}).get("IsNormal") else ""}},
    "People": {"action": "EMP.Maintain", "kind": "employee", "operations": ["Update"], "fields": ["Title", "AccountUpn", "IsActive"]},
}
ROW = {"Title": "PeriodStartDay", "Value": "26"}


def cfg_change(g, key, value, current=ROW, etag="e1", **kw):
    return M.maintain(g, {"Target": "AppSettings", "Operation": "Update", "Key": key, "Values": {"Value": value}, "ETag": "e1"},
                      policy=MD_POLICY, current=current, etag=etag, registry=REG, overlay=OVL, environment="STAGING", **kw)


def as_cfg_admin():
    """A guard result for the proposed config action, as it would look once the action is mapped (synthetic)."""
    pol = G.Policy.from_scope_config({"scopes": {"ADM": {CFG_ACTION: "company"}}, "pending": []})
    ident = TrustedIdentity(upn="admin@" + DOM, group_ids=["g-adm"])
    lk = lambda n: [e for e in EMPS if e.account_upn == n]  # noqa: E731
    return G.authorize(ident, lk, lk, CFG, pol, CFG_ACTION, "company", correlation_id="run-2", ActorUpn="ceo@" + DOM)


# ---------------------------------------------------------------- permission plan
OWNERS, ADMIN, MEMBERS, VISITORS, VIEWERS, EMPLOYEES, SPIKE = 7, 10, 9, 8, 4, 15, 13
INHERITED = pp.parse(["4:Viewers=View Only", "7:Site Owners=Full Control+Limited Access", "8:Site Visitors=Read",
                      "9:Site Members=Edit", "10:Site Admin=Limited Access", "13:Spike Service=Limited Access",
                      "15:Staff Group=Limited Access"])
TARGET = pp.Target(required={OWNERS: "Full Control"}, allowed_extra=(ADMIN,),
                   gated=[{"principal": "<approved operational service identity>", "role": "Read", "gate": "D-3"}],
                   temporary_principals=(SPIKE, "Spike Service"))


class PermissionPlan(unittest.TestCase):
    def test_AP01_members_direct_edit_is_unsafe_even_when_the_group_is_empty(self):
        bad = pp.unsafe(INHERITED, approved_writers=[OWNERS, ADMIN])
        self.assertIn(MEMBERS, [a.principal_id for a in bad])
        self.assertNotIn(VISITORS, [a.principal_id for a in bad], "Read is not write")

    def test_AP02_target_removes_inherited_user_access(self):
        p = pp.plan(False, INHERITED, TARGET)
        self.assertEqual(p["ops"][0][0], "break")
        self.assertFalse(p["ops"][0][1]["copyRoleAssignments"])
        _, after = pp.simulate(False, INHERITED, p["ops"], admin_id=ADMIN)
        ids = {a.principal_id for a in after}
        self.assertFalse(ids & {MEMBERS, VISITORS, VIEWERS, EMPLOYEES}, "no direct user access remains")
        self.assertEqual(pp.unsafe(after, [OWNERS, ADMIN]), [])

    def test_AP03_owners_keep_full_control(self):
        p = pp.plan(False, INHERITED, TARGET)
        self.assertIn(("add", {"principal_id": OWNERS, "role": "Full Control"}), p["ops"])
        _, after = pp.simulate(False, INHERITED, p["ops"], admin_id=ADMIN)
        self.assertIn("Full Control", next(a for a in after if a.principal_id == OWNERS).effective)

    def test_AP04_service_permission_is_gated_by_d3(self):
        p = pp.plan(False, INHERITED, TARGET)
        self.assertEqual([g["gate"] for g in p["gated"]], ["D-3"])
        self.assertFalse(any(a.get("gate") for _, a in p["ops"]), "no service grant without the decision")

    def test_AP05_spike_account_never_substituted(self):
        for appr in ({"gate": "D-3", "role": "Read", "principal_id": SPIKE, "approval": "x"},
                     {"gate": "D-3", "role": "Read", "principal_id": 99, "principal_title": "spike service", "approval": "x"}):
            with self.assertRaises(pp.PlanRefused):
                pp.plan(False, INHERITED, TARGET, approved_grants=[appr])
        with self.assertRaises(pp.PlanRefused):
            pp.plan(False, INHERITED, TARGET, approved_grants=[{"gate": "D-3", "role": "Read", "principal_id": 77}])  # no approval record
        p = pp.plan(False, INHERITED, TARGET, approved_grants=[{"gate": "D-3", "role": "Read", "principal_id": 77, "approval": "IT CHG-1"}])
        self.assertIn(("add", {"principal_id": 77, "role": "Read", "gate": "D-3"}), p["ops"])

    def test_AP15_no_delete_capable_role_for_the_service(self):
        t = pp.Target(required={OWNERS: "Full Control"}, allowed_extra=(ADMIN,),
                      gated=[{"principal": "<svc>", "role": "Contribute", "gate": "D-3"}])
        with self.assertRaises(pp.PlanRefused):
            pp.plan(False, INHERITED, t, approved_grants=[{"gate": "D-3", "role": "Contribute", "principal_id": 77, "approval": "x"}])
        self.assertFalse(pp.SERVICE_ROLES & {"Full Control", "Edit", "Contribute", "Design"})

    def test_AP16_second_apply_plan_is_idempotent(self):
        p = pp.plan(False, INHERITED, TARGET)
        u, after = pp.simulate(False, INHERITED, p["ops"], admin_id=ADMIN)
        self.assertEqual(pp.plan(u, after, TARGET)["ops"], [])

    def test_AP20_unique_list_with_stray_writer_is_cleaned_and_rest_calls_exact(self):
        cur = pp.parse(["7:Site Owners=Full Control", "10:Site Admin=Full Control", "9:Site Members=Edit"])
        p = pp.plan(True, cur, TARGET)
        self.assertEqual(p["ops"], [("remove", {"principal_id": MEMBERS, "title": "Site Members", "role": "Edit"})])
        reqs = pp.requests("AppSettings", pp.plan(False, INHERITED, TARGET)["ops"])
        self.assertEqual(reqs, [("POST", "/_api/web/lists/getbytitle('AppSettings')/breakroleinheritance(copyRoleAssignments=false,clearSubscopes=true)"),
                                ("POST", "/_api/web/lists/getbytitle('AppSettings')/roleassignments/addroleassignment(principalid=7,roledefid=1073741829)")])


# ---------------------------------------------------------------- maintenance
class Maintenance(unittest.TestCase):
    def test_AP06_ordinary_employee_cannot_maintain(self):
        r = M.maintain(guard("staff@" + DOM, ["EMP"], "MD.Maintain"), {"Target": "Units", "Operation": "Update", "Key": "u1",
                       "Values": {"Title": "x"}, "ETag": "e"}, policy=MD_POLICY, current={"Title": "a"}, etag="e")
        self.assertEqual((r.ok, r.code, r.operation), (False, G.ROLE_NOT_ALLOWED, None))
        self.assertEqual((r.audit.EventType, r.audit.Decision), ("AdminMaintenance", G.DENY))

    def test_AP07_admin_maintenance_goes_through_the_guard_and_yields_one_service_operation(self):
        r = M.maintain(guard("admin@" + DOM, ["ADM"], "MD.Maintain"), {"Target": "Units", "Operation": "Update", "Key": "u1",
                       "Values": {"Title": "New"}, "ETag": "e"}, policy=MD_POLICY, current={"Title": "Old"}, etag="e")
        self.assertEqual((r.ok, r.code), (True, M.OK))
        self.assertEqual(r.operation, {"list": "Units", "operation": "Update", "key": "u1", "set": {"Title": "New"}, "ifMatch": "e"})
        self.assertEqual((r.audit.Action, r.audit.Decision, r.audit.ChangeJson), ("MasterDataChange", G.ALLOW, '{"Title":{"new":"New","old":"Old"}}'))
        wrong = M.maintain(guard("admin@" + DOM, ["ADM"], "EMP.Maintain"), {"Target": "Units", "Operation": "Update", "Key": "u1",
                           "Values": {"Title": "New"}, "ETag": "e"}, policy=MD_POLICY, current={"Title": "Old"}, etag="e")
        self.assertEqual(wrong.code, M.FORBIDDEN, "a grant for another action does not authorise this target")

    def test_AP08_forged_actor_role_scope_ignored(self):
        r = M.maintain(guard("admin@" + DOM, ["ADM"], "MD.Maintain"), {"Target": "Units", "Operation": "Update", "Key": "u1", "ActorUpn": "x",
                       "Values": {"Title": "New", "Editor": "x", "Role": "ADM"}, "ETag": "e"}, policy=MD_POLICY, current={"Title": "Old"}, etag="e")
        self.assertTrue(r.ok)
        self.assertEqual(r.audit.ActorUpn, "admin@" + DOM)
        self.assertEqual(r.ignored, ["ActorUpn", "Editor", "Role"])
        self.assertNotIn("Editor", r.operation["set"])
        self.assertIn("ActorUpn", r.audit.IgnoredInputs, "guard-level decoys are recorded by name")

    def test_AP09_invalid_setting_rejected(self):
        g = as_cfg_admin()
        for key, value, code in (("PeriodStartDay", "29", M.VALIDATION), ("PeriodStartDay", "x", M.VALIDATION),
                                 ("Nope", "1", M.NOT_FOUND), ("Offset", "60", M.DERIVED_READONLY)):
            self.assertEqual(cfg_change(g, key, value).code, code, (key, value))
        ok = cfg_change(g, "PeriodStartDay", "25")
        self.assertEqual((ok.ok, ok.operation["set"], ok.operation["ifMatch"]), (True, {"Value": "25"}, "e1"))
        self.assertEqual(cfg_change(g, "PeriodStartDay", "25", etag="e2").code, M.CONFLICT)

    def test_AP10_secret_like_or_tenant_values_rejected_and_never_logged(self):
        g = as_cfg_admin()
        for v in ("password=abc", "Bearer abc", "https://x.invalid/sites/a", "0f0e0d0c-0b0a-4908-8706-050403020100"):
            r = cfg_change(g, "Note", v, current={"Title": "Note", "Value": "x"})
            self.assertEqual(r.code, M.VALIDATION, v)
            self.assertNotIn(v, r.audit.ChangeJson)
            self.assertIn("redacted", r.audit.ChangeJson)

    def test_AP11_interim_value_cannot_be_changed_or_promoted(self):
        r = cfg_change(as_cfg_admin(), "Switch", "On", current={"Title": "Switch", "Value": "Off"})
        self.assertEqual((r.ok, r.code), (False, M.INTERIM_PROTECTED))
        self.assertEqual(cfg_change(as_cfg_admin(), "Switch", "Off", current={"Title": "Switch", "Value": "Off"}).code, M.INTERIM_PROTECTED)
        import app_settings as cfg
        ok, _ = cfg.readiness(REG, dict(OVL, environment="PRODUCTION"), "PRODUCTION", ["Switch"])
        self.assertFalse(ok, "the interim value never passes production readiness")
        r = M.maintain(as_cfg_admin(), {"Target": "AppSettings", "Operation": "Update", "Key": "Switch", "ETag": "e1",
                       "Values": {"Value": "On", "Description": "approved"}}, policy=MD_POLICY, current={"Title": "Switch"}, etag="e1",
                       registry=REG, overlay=OVL, environment="STAGING")
        self.assertEqual(r.code, M.FIELD_NOT_ALLOWED, "decision metadata/description cannot be edited through maintenance")

    def test_AP12_unset_retention_stays_unset(self):
        r = cfg_change(as_cfg_admin(), "RetentionDays", "365", current={"Title": "RetentionDays", "Value": ""})
        self.assertEqual((r.ok, r.code), (False, M.DECISION_PENDING))
        self.assertIn("IT-8", r.detail)

    def test_AP13_service_account_is_not_an_appsetting(self):
        r = cfg_change(as_cfg_admin(), "ServiceUpn", "svc@" + DOM, current={"Title": "ServiceUpn", "Value": ""})
        self.assertEqual(r.code, M.ENVIRONMENT_CONFIG)
        self.assertNotEqual(MD_POLICY["AppSettings"]["operations"], ["Create"], "rows are never created by maintenance")
        c = M.maintain(as_cfg_admin(), {"Target": "AppSettings", "Operation": "Create", "Key": "ServiceUpn", "Values": {"Value": "x"}},
                       policy=MD_POLICY, current=None, registry=REG, overlay=OVL, environment="STAGING")
        self.assertEqual(c.code, M.OPERATION_NOT_ALLOWED)

    def test_AP14_audit_payload_excludes_secrets(self):
        r = M.maintain(guard("admin@" + DOM, ["ADM"], "MD.Maintain"), {"Target": "Units", "Operation": "Update", "Key": "u1", "ETag": "e",
                       "Values": {"Title": "T"}}, policy=MD_POLICY, current={"Title": "Old", "password": "p"}, etag="e")
        self.assertNotIn("p\"", r.audit.ChangeJson.replace('"Old"', ""))
        import audit_event as ae
        cj, omitted = ae.sanitize_change({"Value": {"old": 1, "new": 2}, "clientSecret": "s", "token": "t"}, ae.OPS_LOG)
        self.assertEqual((sorted(omitted), "s" in cj, "t\"" in cj), (["clientSecret", "token"], False, False))

    def test_AP17_proposed_config_action_is_denied_until_mapped(self):
        g = guard("admin@" + DOM, ["ADM"], CFG_ACTION)
        self.assertEqual(g.ResultCode, G.UNKNOWN_ACTION)
        r = cfg_change(g, "PeriodStartDay", "25")
        self.assertEqual((r.ok, r.code), (False, G.UNKNOWN_ACTION))

    def test_AP18_hard_delete_never_and_soft_delete_where_defined(self):
        g = guard("admin@" + DOM, ["ADM"], "MD.Maintain")
        r = M.maintain(g, {"Target": "Units", "Operation": "Delete", "Key": "u1", "ETag": "e"}, policy=MD_POLICY, current={"Title": "a"}, etag="e")
        self.assertEqual(r.code, M.HARD_DELETE_FORBIDDEN)
        r = M.maintain(g, {"Target": "Units", "Operation": "SoftDelete", "Key": "u1", "ETag": "e"}, policy=MD_POLICY,
                       current={"Title": "a", "IsActive": True}, etag="e")
        self.assertEqual(r.operation["set"], {"IsActive": False})
        r = M.maintain(g, {"Target": "Rates", "Operation": "SoftDelete", "Key": "r1", "ETag": "e"}, policy=MD_POLICY, current={"Title": "a"}, etag="e")
        self.assertEqual(r.code, M.OPERATION_NOT_ALLOWED)

    def test_AP19_restricted_scope_denies(self):
        r = M.maintain(guard("hr@" + DOM, ["HR"], "MD.Maintain"), {"Target": "Units", "Operation": "Update", "Key": "u1", "ETag": "e",
                       "Values": {"Title": "x"}}, policy=MD_POLICY, current={"Title": "a"}, etag="e")
        self.assertEqual((r.ok, r.code), (False, G.UNKNOWN_SCOPE), "restricted:* scopes are not evaluated -> deny")

    def test_AP21_sensitive_fields_wait_for_their_decision(self):
        g = guard("admin@" + DOM, ["ADM"], "MD.Maintain")
        base = {"Target": "Rates", "Operation": "Update", "Key": "r1", "ETag": "e"}
        r = M.maintain(g, dict(base, Values={"Factor": 2.5}), policy=MD_POLICY, current={"Factor": 2, "IsNormal": False}, etag="e")
        self.assertEqual((r.code, "HT-1" in r.detail), (M.DECISION_PENDING, True))
        r = M.maintain(g, dict(base, Values={"IsNormal": True}), policy=MD_POLICY, current={"Factor": 2, "IsNormal": False}, etag="e")
        self.assertEqual(r.code, M.VALIDATION)
        r = M.maintain(g, dict(base, Values={"Title": "Overtime"}), policy=MD_POLICY, current={"Factor": 2, "Title": "OT"}, etag="e")
        self.assertTrue(r.ok, "non-sensitive fields remain maintainable")

    def test_AP22_unknown_target_and_field_refused(self):
        g = guard("admin@" + DOM, ["ADM"], "MD.Maintain")
        self.assertEqual(M.maintain(g, {"Target": "Holidays", "Operation": "Update"}, policy=MD_POLICY, current={}).code, M.UNKNOWN_TARGET)
        r = M.maintain(g, {"Target": "Units", "Operation": "Update", "Key": "u1", "ETag": "e", "Values": {"LegacyId": "z"}},
                       policy=MD_POLICY, current={"Title": "a"}, etag="e")
        self.assertEqual(r.code, M.FIELD_NOT_ALLOWED, "keys are not maintainable")

    def test_AP23_employee_self_modification_refused(self):
        r = M.maintain(guard("admin@" + DOM, ["ADM"], "EMP.Maintain"), {"Target": "People", "Operation": "Update", "Key": "E3", "ETag": "e",
                       "Values": {"IsActive": False}}, policy=MD_POLICY, current={"AccountUpn": "admin@" + DOM, "IsActive": True}, etag="e")
        self.assertEqual(r.code, M.SELF_MODIFICATION)
        self.assertEqual(r.audit.Action, "MasterDataChange" if MD_POLICY["People"].get("auditAction") is None else MD_POLICY["People"]["auditAction"])

    def test_AP24_environment_specific_value_follows_the_environment(self):
        r = cfg_change(as_cfg_admin(), "EnvLabel", "PRODUCTION", current={"Title": "EnvLabel", "Value": "STAGING"})
        self.assertEqual(r.code, M.ENVIRONMENT_RULE)


@unittest.skipUnless(os.environ.get("TS_APP_SETTINGS") and os.environ.get("TS_APP_SETTINGS_OVERLAY"), "set the real registry and overlay")
class RealRegistry(unittest.TestCase):
    def test_real_keys_follow_their_decision_state(self):
        reg = json.load(open(os.environ["TS_APP_SETTINGS"], encoding="utf-8"))
        ovl = json.load(open(os.environ["TS_APP_SETTINGS_OVERLAY"], encoding="utf-8"))
        g = as_cfg_admin()

        def ch(key, value):
            return M.maintain(g, {"Target": "AppSettings", "Operation": "Update", "Key": key, "Values": {"Value": value}, "ETag": "e"},
                              policy=MD_POLICY, current={"Title": key, "Value": ""}, etag="e", registry=reg, overlay=ovl, environment="STAGING")
        self.assertEqual(ch("ProjectAssignmentScoping", "On").code, M.INTERIM_PROTECTED)
        self.assertEqual(ch("AuditRetentionDays", "365").code, M.DECISION_PENDING)
        self.assertEqual(ch("ConfidentialAuditRetentionDays", "365").code, M.DECISION_PENDING)
        self.assertEqual(ch("ServiceAccountUpn", "x@y.invalid").code, M.ENVIRONMENT_CONFIG)
        self.assertEqual(ch("BusinessUtcOffsetMinutes", "0").code, M.DERIVED_READONLY)
        self.assertEqual(ch("MaxHoursPerEntryWarn", "5").code, M.DECISION_PENDING, "B-07 is a customer decision")
        self.assertTrue(ch("PayPeriodStartDay", "26").ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
