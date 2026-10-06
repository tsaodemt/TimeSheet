"""Audit model tests A1-A10 (synthetic data only; run: python -m unittest test_audit).

Each case is produced twice and the rows must be identical:
  1. the Python reference (audit_event.py), and
  2. the generated flow actions (tools/powerautomate/audit_template.py, appended to the guard template where
     relevant) executed by the offline WDL interpreter with mocked connectors.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "identity"))
sys.path.insert(0, os.path.join(HERE, "..", "powerautomate"))
import audit_event as ae  # noqa: E402
import audit_template as at  # noqa: E402
import test_guard as tg  # noqa: E402  (shared synthetic directory, policy and guard template)
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

NOW = "2026-10-06T10:00:00Z"
ENV = "TEST"
UNTRUSTED = ["CallerUpn", "ClaimRole"]
APP_OPEN = at.app_open_actions(site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST,
                               audit_list=ae.OPS_LOG, environment=ENV, client_type_expr="triggerBody()?['text']",
                               untrusted_inputs=UNTRUSTED)
SECRETS = {"Password": "P@ss-123", "accessToken": "eyJhbGciOi.secret", "Authorization": "Bearer abc.def",
           "Cookie": "FedAuth=xyz", "totpSecret": "JBSWY3DPEHPK3PXP", "mfaCode": "908172", "clientSecret": "s3cr3t"}
SECRET_VALUES = list(SECRETS.values())


def run_flow(actions, upn, roles=(), trigger=None, emps=tg.EMPS, cid="run-a", directory_down=False):
    posts = {}
    lists = {tg.EMP_LIST: tg.rows(emps)}
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        if opid == "HttpRequest" and p["parameters/method"] == "GET":
            if directory_down and name == "Caller_lookup":
                return "Failed", {"error": "down"}
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], lists)
        if opid == "HttpRequest" and p["parameters/method"] == "POST":
            title = p["parameters/uri"].split("getbytitle('")[1].split("')")[0]
            posts.setdefault(title, []).append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": 1}
        raise AssertionError(opid)
    run = wdl_sim.Run(trigger_body=trigger or {}, run_name=cid, mocks=mocks, now=NOW).run(actions)
    return run, posts


def py_app_open(upn, cid, client="", emps=tg.EMPS, directory_down=False, **untrusted):
    def lookup(n):
        if directory_down:
            raise ConnectionError("down")
        return [e for e in emps if e.account_upn == n]
    return ae.app_open(TrustedIdentity(upn=upn), lookup, tg.CFG, correlation_id=cid, environment=ENV,
                       client_type=client, now=NOW, **{k: untrusted.get(k, "") for k in UNTRUSTED})


def flow_app_open(upn, cid, client="", **kw):  # kw: CallerUpn, ClaimRole, directory_down
    run, posts = run_flow(APP_OPEN, upn, trigger={"text": client, "text_1": kw.get("CallerUpn", ""), "text_2": kw.get("ClaimRole", "")},
                          cid=cid, directory_down=kw.get("directory_down", False))
    return posts[ae.OPS_LOG][0], run.results["Respond"]["outputs"]


def guard_then(extra, case):
    """Guard template + extra audit actions, executed for a test_guard Case."""
    actions = dict(tg.TEMPLATE)
    actions.update(extra)
    trig = {"text": case.action, "text_1": case.kind, "text_2": case.ref, "text_3": case.decoys.get("CallerUpn", ""),
            "text_4": case.decoys.get("ClaimRole", ""), "text_5": case.decoys.get("ClaimScope", ""), "text_6": ""}
    run, posts = run_flow(actions, case.upn, case.roles, trig, cid=case.cid)
    return posts


AUTH = at.authorization_event_actions(audit_list=ae.OPS_LOG, environment=ENV, source_flow="TS-Test")


def op_actions(event_type, action, entity, change=None, outcome=""):  # appended after the guard's own audit write
    return at.operation_event_actions(event_type, action, target_entity=entity, audit_list=ae.OPS_LOG, conf_audit_list=ae.CONF_LOG,
                                      environment=ENV, source_flow="TS-Test", target_id_expr="'42'",
                                      outcome_code_expr=outcome, work_date_expr="'2026-10-01'",
                                      change_fields=change, after="Write_audit")


def expr(v):
    """Python value -> equivalent WDL literal expression."""
    return str(v) if isinstance(v, int) and not isinstance(v, bool) else "'%s'" % str(v).replace("'", "''")


class AppOpenTests(unittest.TestCase):
    def both(self, upn, cid, code, event_type, **kw):
        py = py_app_open(upn, cid, kw.get("client", ""), directory_down=kw.get("directory_down", False),
                         **{k: kw.get(k, "") for k in UNTRUSTED}).to_row()
        fl, resp = flow_app_open(upn, cid, **kw)
        self.assertEqual(py, fl, "python vs flow row differ")
        self.assertEqual(set(py), set(ae.COLUMNS))
        self.assertEqual((py["EventType"], py["ResultCode"]), (event_type, code))
        self.assertEqual(resp["resultcode"], code)
        return py, resp

    def test_A1_successful_app_open_starts_session(self):
        r, resp = self.both(tg.u("emp"), "run-a1", "OK", "AppOpen", client="Teams")
        self.assertEqual((r["Decision"], r["ActorEmployeeItemId"], r["ActorUpn"], r["Action"]), ("ALLOW", 11, tg.u("emp"), "AppOpen"))
        self.assertEqual(resp["employeecode"], "E1")
        self.assertTrue(r["Detail"].endswith("client=Teams"))

    def test_A2_unmapped_identity_access_denied(self):
        r, resp = self.both(tg.u("stranger"), "run-a2", "UNMAPPED_IDENTITY", "IdentityRejected")
        self.assertEqual((r["Decision"], r["ActorEmployeeItemId"], r["ActorUpn"]), ("DENY", None, tg.u("stranger")))
        self.assertEqual(resp["employeecode"], "")

    def test_A3_inactive_identity_access_denied(self):
        r, _ = self.both(tg.u("gone"), "run-a3", "INACTIVE_EMPLOYEE", "IdentityRejected")
        self.assertEqual((r["Decision"], r["ActorEmployeeItemId"]), ("DENY", None))

    def test_A4_duplicate_invalid_and_directory_failure_denied(self):
        self.both(tg.u("twin"), "run-a4", "DUPLICATE_IDENTITY", "IdentityRejected")
        self.both("emp@other-tenant.invalid", "run-a4b", "INVALID_IDENTITY", "IdentityRejected")
        self.both(tg.u("emp"), "run-a4c", "DIRECTORY_ERROR", "IdentityRejected", directory_down=True)


class GuardEventTests(unittest.TestCase):
    def auth_both(self, case):
        py = ae.authorization_event(case.python(), source_flow="TS-Test", environment=ENV, now=NOW).to_row()
        fl = guard_then(AUTH, case)[ae.OPS_LOG][0]
        self.assertEqual(py, fl, "python vs flow row differ")
        return py

    def op_both(self, case, event_type, action, entity, change=None, outcome="", outcome_py=None):
        py = ae.operation_event(case.python(), event_type, action, target_entity=entity, target_id="42", source_flow="TS-Test",
                                environment=ENV, outcome_code=outcome_py, work_date="2026-10-01", change=change, now=NOW)
        posts = guard_then(op_actions(event_type, action, entity, {k: expr(v) for k, v in (change or {}).items()}, outcome), case)
        fl = posts[py.Sink][0]
        self.assertEqual(py.to_row(), fl, "python vs flow row differ")
        return py

    def test_A5_authorization_deny(self):
        r = self.auth_both(tg.Case(tg.u("emp"), ["TL"], "TS.Approve", "employee", "E3"))
        self.assertEqual((r["EventType"], r["Decision"], r["ResultCode"], r["ScopeKind"], r["ScopeRef"]),
                         ("AuthorizationDeny", "DENY", "SCOPE_NOT_ALLOWED", "employee", "E3"))
        e = self.op_both(tg.Case(tg.u("emp"), ["EMP"], "TS.Approve", "employee", "E2"), "Approval", "Approve", "TimesheetEntries")
        self.assertEqual((e.Decision, e.ResultCode), ("DENY", "ROLE_NOT_ALLOWED"))
        e = self.op_both(tg.Case(tg.u("emp"), ["EMP"], "TS.Approve", "employee", "E2"), "Approval", "Approve", "TimesheetEntries",
                         outcome="'ALLOW'", outcome_py="ALLOW")
        self.assertEqual(e.Decision, "DENY", "a refused guard can never be logged as allowed")

    def test_A6_authorization_allow_and_operations(self):
        r = self.auth_both(tg.Case(tg.u("emp"), ["TL"], "TS.Approve", "employee", "E2"))
        self.assertEqual((r["EventType"], r["Decision"], r["ResultCode"]), ("AuthorizationAllow", "ALLOW", "ALLOW"))
        case = tg.Case(tg.u("emp"), ["TL"], "TS.Approve", "employee", "E2")
        e = self.op_both(case, "Approval", "Approve", "TimesheetEntries", {"EntryStatus": "Approved"})
        self.assertEqual((e.Decision, e.ActionText, e.ChangeJson), ("ALLOW", "Phê duyệt: 2026-10-01", '{"EntryStatus":"Approved"}'))
        e = self.op_both(case, "WriteProxy", "Update", "TimesheetEntries", outcome="'LOCKED'", outcome_py="LOCKED")
        self.assertEqual((e.Decision, e.ResultCode, e.ActionText), ("DENY", "LOCKED", "Thay đổi"))
        e = self.op_both(tg.Case(tg.u("emp"), ["EMP"], "TS.EditOwnDraft", "self"), "SoftDelete", "Delete", "TimesheetEntries",
                         {"EntryStatus": "Deleted"})
        self.assertEqual((e.Decision, e.ActionText), ("ALLOW", "Xóa"))

    def test_A7_correlation_id_propagates(self):
        case = tg.Case(tg.u("emp"), ["TL"], "TS.Approve", "employee", "E2")
        actions = dict(AUTH)
        actions.update(at.operation_event_actions("Approval", "Approve", target_entity="TimesheetEntries", audit_list=ae.OPS_LOG,
                                                  conf_audit_list=ae.CONF_LOG, environment=ENV, source_flow="TS-Test",
                                                  after="Write_Audit_event", name="Op_event"))
        rows = guard_then(actions, case)[ae.OPS_LOG]
        self.assertEqual([r["CorrelationId"] for r in rows], [case.cid, case.cid])
        py = case.python()
        self.assertEqual(ae.authorization_event(py, source_flow="x", environment=ENV).CorrelationId, case.cid)
        a1, _ = flow_app_open(tg.u("emp"), "run-a7")
        self.assertEqual(a1["CorrelationId"], "run-a7")

    def test_A8_untrusted_caller_fields_not_trusted_or_persisted(self):
        forged = {"CallerUpn": tg.u("appr-boss"), "ClaimRole": "APR,ADM"}
        py = py_app_open(tg.u("stranger"), "run-a8", **forged).to_row()
        fl, _ = flow_app_open(tg.u("stranger"), "run-a8", **forged)
        self.assertEqual(py, fl)
        self.assertEqual((py["ActorUpn"], py["ResultCode"]), (tg.u("stranger"), "UNMAPPED_IDENTITY"))
        self.assertIn("ignored=CallerUpn,ClaimRole", py["Detail"])
        self.assertNotIn("appr-boss", json.dumps(py))
        self.assertNotIn("APR,ADM", json.dumps(py))
        case = tg.Case(tg.u("emp"), ["EMP"], "TS.Approve", "company", decoys={"CallerUpn": tg.u("appr-boss"), "ClaimRole": "APR,ADM"})
        r = self.auth_both(case)
        self.assertEqual((r["ActorUpn"], r["Decision"]), (tg.u("emp"), "DENY"))
        self.assertNotIn("appr-boss", json.dumps(r))

    def test_A9_no_secret_or_confidential_values_in_audit_rows(self):
        case = tg.Case(tg.u("emp"), ["EMP"], "TS.EditOwnDraft", "self")
        change = dict(SECRETS, Hours=8, DailyRate=1234567, ResultScore=91)
        e = self.op_both(case, "WriteProxy", "Update", "TimesheetEntries", change)
        row = json.dumps(e.to_row(), ensure_ascii=False)
        for v in SECRET_VALUES + ["1234567", "91"]:
            self.assertNotIn(v, row)
        self.assertEqual(json.loads(e.ChangeJson), {"Hours": 8})
        self.assertEqual(e.Sink, ae.OPS_LOG)
        self.assertEqual(sorted(e.OmittedFields), sorted(list(SECRETS) + ["DailyRate", "ResultScore"]))
        c = self.op_both(tg.Case(tg.u("emp"), ["ADM"], "EMP.Maintain", "company"), "AdminMaintenance", "MasterDataChange",
                         "PositionRates", dict(SECRETS, DailyRate=1234567))
        self.assertEqual(c.Sink, ae.CONF_LOG)
        self.assertIn("1234567", c.ChangeJson)
        for v in SECRET_VALUES:
            self.assertNotIn(v, json.dumps(c.to_row()))
        self.assertEqual(set(e.to_row()), set(ae.COLUMNS))
        nested, omitted = ae.sanitize_change({"a": {"token": "x", "ok": 1}, "list": [{"password": "y"}]}, ae.OPS_LOG)
        self.assertEqual((json.loads(nested), omitted), ({"a": {"ok": 1}, "list": [{}]}, ["a.token", "list.password"]))

    def test_A9b_undecided_and_unknown_events_rejected(self):
        g = tg.Case(tg.u("emp"), ["TL"], "TS.Approve", "employee", "E2").python()
        with self.assertRaises(ae.EventNotEnabled):
            ae.operation_event(g, "Unlock", "Unlock", target_entity="X", source_flow="f", environment=ENV)
        with self.assertRaises(ae.EventNotEnabled):
            op_actions("Unlock", "Unlock", "X")
        with self.assertRaises(ValueError):
            ae.operation_event(g, "Delete", "Delete", target_entity="X", source_flow="f", environment=ENV)
        with self.assertRaises(ValueError):
            ae.operation_event(g, "AdminMaintenance", "Reboot", target_entity="X", source_flow="f", environment=ENV)
        ok = ae.operation_event(g, "Unlock", "Unlock", target_entity="X", source_flow="f", environment=ENV, enabled_pending=["Unlock"])
        self.assertEqual(ok.EventType, "Unlock")


class RetentionTests(unittest.TestCase):
    def test_A10_unset_retention_never_purges_and_has_no_default(self):
        import datetime as dt
        far = dt.datetime(2100, 1, 1, tzinfo=dt.timezone.utc)
        for settings in ({}, {"AuditRetentionDays": ""}, {"AuditRetentionDays": None}):
            p = ae.RetentionPolicy.from_settings(settings)
            self.assertEqual((p.days, p.status, p.purge_enabled), (None, "PENDING_IT_CUSTOMER_DECISION", False))
            self.assertFalse(p.is_expired("2000-01-01T00:00:00Z", far))
        for bad in ("0", "-5", "ten", "3.5"):
            p = ae.RetentionPolicy.from_settings({"AuditRetentionDays": bad})
            self.assertEqual((p.status, p.purge_enabled), ("INVALID_SETTING", False))
            self.assertFalse(p.is_expired("2000-01-01T00:00:00Z", far))
        p = ae.RetentionPolicy.from_settings({"AuditRetentionDays": "30"})
        self.assertTrue(p.is_expired("2000-01-01T00:00:00Z", far))
        self.assertEqual(ae.RetentionPolicy.from_settings({"AuditRetentionDays": "30"}, ae.CONF_LOG).status, "PENDING_IT_CUSTOMER_DECISION")


if __name__ == "__main__":
    unittest.main(verbosity=2)
