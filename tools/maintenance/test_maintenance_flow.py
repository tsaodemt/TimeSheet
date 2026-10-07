"""Generated D-6 maintenance flow template, executed in the WDL simulator (offline; nothing deployed). MF01-MF11.
The template must never be looser than the reference (tools/maintenance/maintenance.py)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config")):
    sys.path.insert(0, p)
import build_maintenance_flow as bmf  # noqa: E402
import guard as G  # noqa: E402
import maintenance as M  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import Config, Employee, Role, TrustedIdentity  # noqa: E402
import test_maintenance as TM  # noqa: E402  (shared synthetic policy, registry, overlay)

DOM = TM.DOM
SCOPES = {"scopes": {"EMP": {"TS.ViewOwn": "self"}, "ADM": {"MD.Maintain": "company", "EMP.Maintain": "company"},
                     "HR": {"MD.Maintain": "restricted:org, positions"}}, "pending": []}
ROLE_GROUPS = [("EMP", "g-emp"), ("HR", "g-hr"), ("ADM", "g-adm")]
EMP_LIST, AUDIT = "_Employees", "_Audit"
PEOPLE = [{"Id": 1, "LegacyId": "E1", "IsActive": True, "DisciplineCode": "D1", "AccountUpn": "staff@" + DOM},
          {"Id": 2, "LegacyId": "E2", "IsActive": True, "DisciplineCode": "D1", "AccountUpn": "hr@" + DOM},
          {"Id": 3, "LegacyId": "E3", "IsActive": True, "DisciplineCode": "D1", "AccountUpn": "admin@" + DOM}]


def flow(target, **kw):
    return bmf.maintenance_actions(target, TM.MD_POLICY[target], scope_config=kw.pop("scopes", SCOPES), role_groups=ROLE_GROUPS,
                                   site="https://tenant-a.invalid/sites/x", domain=DOM, emp_list=EMP_LIST, audit_list=AUDIT,
                                   conf_audit_list="_ConfAudit", environment="STAGING", **kw)


def run(actions, target, upn, roles, *, op, key, values, etag="e", items=None, write_status=("Succeeded", 204), decoys=None):
    calls, audit = [], {}
    lists = {EMP_LIST: PEOPLE, target: items or []}
    member = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member else []}
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], lists)
        if name == "Write_item":
            calls.append((p["parameters/uri"], p["parameters/headers"], json.loads(p["parameters/body"])))
            return write_status[0], {"statusCode": write_status[1]}
        if p.get("parameters/method") == "POST":
            if name == "Write_Maint_audit":
                audit.update(json.loads(p["parameters/body"]))
            return "Succeeded", {}
        raise AssertionError(name)
    d = decoys or {}
    trig = {"text": op, "text_1": key, "text_2": json.dumps(values), "text_3": etag,
            "text_4": d.get("ActorUpn", ""), "text_5": d.get("Role", ""), "text_6": d.get("Scope", "")}
    r = wdl_sim.Run(trigger_body=trig, run_name="run-9", mocks=mocks).run(actions)
    return r.results["Final_code"]["outputs"], calls, audit, r


ITEM = [{"Id": 5, "LegacyId": "u1", "Title": "Old", "IsActive": True}]


class MaintenanceFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units = flow("Units")

    def test_MF01_admin_update_merges_with_if_match(self):
        code, calls, audit, _ = run(self.units, "Units", "admin@" + DOM, ["ADM"], op="Update", key="u1", values={"Title": "New"}, items=ITEM)
        self.assertEqual(code, "OK")
        uri, headers, body = calls[0]
        self.assertEqual((uri, headers["X-HTTP-Method"], headers["IF-MATCH"], body),
                         ("_api/web/lists/getbytitle('Units')/items(5)", "MERGE", "e", {"Title": "New"}))
        self.assertEqual((audit["EventType"], audit["Action"], audit["Decision"], audit["ActorUpn"]),
                         ("AdminMaintenance", "MasterDataChange", "ALLOW", "admin@" + DOM))

    def test_MF02_employee_denied_no_write(self):
        code, calls, audit, _ = run(self.units, "Units", "staff@" + DOM, ["EMP"], op="Update", key="u1", values={"Title": "New"}, items=ITEM)
        self.assertEqual((code, calls, audit["Decision"]), (G.ROLE_NOT_ALLOWED, [], "DENY"))

    def test_MF03_no_hard_delete_and_soft_delete(self):
        code, calls, _, _ = run(self.units, "Units", "admin@" + DOM, ["ADM"], op="Delete", key="u1", values={}, items=ITEM)
        self.assertEqual((code, calls), ("HARD_DELETE_FORBIDDEN", []))
        code, calls, _, _ = run(self.units, "Units", "admin@" + DOM, ["ADM"], op="SoftDelete", key="u1", values={}, items=ITEM)
        self.assertEqual((code, calls[0][2]), ("OK", {"IsActive": False}))
        self.assertNotIn("DELETE", json.dumps(self.units).replace("HARD_DELETE_FORBIDDEN", "").replace("SoftDelete", "").replace("'Delete'", ""))

    def test_MF04_forged_fields_ignored_and_recorded(self):
        code, calls, audit, r = run(self.units, "Units", "admin@" + DOM, ["ADM"], op="Update", key="u1",
                                    values={"Title": "New", "Editor": "x", "ActorUpn": "boss@" + DOM}, items=ITEM,
                                    decoys={"ActorUpn": "boss@" + DOM, "Role": "ADM"})
        self.assertEqual((code, calls[0][2]), ("OK", {"Title": "New"}))
        self.assertEqual(audit["ActorUpn"], "admin@" + DOM)
        self.assertIn("ActorUpn", r.results["Guard_result"]["outputs"]["IgnoredInputs"])
        self.assertEqual(r.results["Ignored_fields"]["outputs"]["body"], ["ActorUpn", "Editor"])

    def test_MF05_field_whitelist_key_and_etag(self):
        for values, etag, items, want in (({"LegacyId": "z"}, "e", ITEM, "FIELD_NOT_ALLOWED"), ({"Title": "x"}, "", ITEM, "CONFLICT"),
                                          ({"Title": "x"}, "e", [], "NOT_FOUND"), ({}, "e", ITEM, "VALIDATION")):
            code, calls, _, _ = run(self.units, "Units", "admin@" + DOM, ["ADM"], op="Update", key="u1", values=values, etag=etag, items=items)
            self.assertEqual((code, calls), (want, []), values)

    def test_MF06_stale_etag_returns_conflict(self):
        code, calls, audit, _ = run(self.units, "Units", "admin@" + DOM, ["ADM"], op="Update", key="u1", values={"Title": "x"}, items=ITEM,
                                    write_status=("Failed", 412))
        self.assertEqual((code, audit["Decision"]), ("CONFLICT", "DENY"))

    def test_MF07_restricted_scope_denied(self):
        code, calls, _, _ = run(self.units, "Units", "hr@" + DOM, ["HR"], op="Update", key="u1", values={"Title": "x"}, items=ITEM)
        self.assertEqual((code, calls), (G.UNKNOWN_SCOPE, []))

    def test_MF08_decision_and_invariant_fields_refused(self):
        rates = flow("Rates")
        items = [{"Id": 6, "LegacyId": "r1", "Title": "OT", "Factor": 2, "IsNormal": False}]
        for values, want in (({"Factor": 2.5}, "DECISION_PENDING"), ({"IsNormal": True}, "VALIDATION"), ({"Title": "Overtime"}, "OK")):
            code, _, _, _ = run(rates, "Rates", "admin@" + DOM, ["ADM"], op="Update", key="r1", values=values, items=items)
            self.assertEqual(code, want, values)

    def test_MF09_config_rules_and_proposed_action_denied(self):
        cfgflow = flow("AppSettings", key_field="Title", registry=TM.REG, overlay=TM.OVL,
                       scopes={"scopes": {"ADM": {"CFG.Maintain": "company"}}, "pending": []})
        rows = [{"Id": i + 1, "Title": k} for i, k in enumerate(["PeriodStartDay", "Switch", "RetentionDays", "Offset", "EnvLabel", "Note", "Zone"])]
        for key, value, want in (("PeriodStartDay", "25", "OK"), ("PeriodStartDay", "29", "VALIDATION"), ("Switch", "On", "INTERIM_PROTECTED"),
                                 ("RetentionDays", "365", "DECISION_PENDING"), ("Offset", "0", "DERIVED_READONLY"),
                                 ("EnvLabel", "PRODUCTION", "ENVIRONMENT_RULE"), ("ServiceUpn", "x@y.invalid", "ENVIRONMENT_CONFIG"),
                                 ("Note", "password=x", "VALIDATION")):
            items = rows + ([{"Id": 99, "Title": "ServiceUpn"}] if key == "ServiceUpn" else [])
            code, calls, audit, _ = run(cfgflow, "AppSettings", "admin@" + DOM, ["ADM"], op="Update", key=key, values={"Value": value}, items=items)
            self.assertEqual(code, want, (key, value))
            if want != "OK":
                self.assertEqual(calls, [])
                self.assertNotIn(value if value not in ("On", "0") else "\u0000", audit["ChangeJson"])
        denied = flow("AppSettings", key_field="Title", registry=TM.REG, overlay=TM.OVL)  # CFG.Maintain not in the seed
        code, calls, _, _ = run(denied, "AppSettings", "admin@" + DOM, ["ADM"], op="Update", key="PeriodStartDay", values={"Value": "25"}, items=rows)
        self.assertEqual((code, calls), (G.UNKNOWN_ACTION, []))

    def test_MF10_employee_self_modification(self):
        people = flow("People", key_field="LegacyId")
        items = [{"Id": 3, "LegacyId": "E3", "Title": "Admin", "AccountUpn": "admin@" + DOM, "IsActive": True}]
        code, calls, _, _ = run(people, "People", "admin@" + DOM, ["ADM"], op="Update", key="E3", values={"IsActive": False}, items=items)
        self.assertEqual((code, calls), ("SELF_MODIFICATION", []))

    def test_MF11_template_never_looser_than_reference(self):
        """For a matrix of requests: whenever the template allows, the reference allows the same operation."""
        rates = flow("Rates")
        items = [{"Id": 6, "LegacyId": "r1", "Title": "OT", "Factor": 2, "IsNormal": False}]
        g_adm = TM.guard("admin@" + DOM, ["ADM"], "MD.Maintain")
        for op in ("Create", "Update", "SoftDelete", "Delete", "Merge"):
            for values in ({"Title": "x"}, {"Factor": 2}, {"Factor": 3}, {"IsNormal": False}, {"Foo": 1}, {}):
                code, _, _, _ = run(rates, "Rates", "admin@" + DOM, ["ADM"], op=op, key="r1", values=values, items=items)
                ref = M.maintain(g_adm, {"Target": "Rates", "Operation": op, "Key": "r1", "Values": values, "ETag": "e"},
                                 policy=TM.MD_POLICY, current=items[0], etag="e")
                if code == "OK":
                    self.assertTrue(ref.ok, (op, values, ref.code))


if __name__ == "__main__":
    unittest.main(verbosity=2)
