"""Guard tests G1-G15 (synthetic data only; run: python -m unittest test_guard).

Every case runs twice and must agree field-by-field:
  1. the Python reference guard (guard.authorize), and
  2. the generated Power Automate guard template (tools/powerautomate/guard_template.py) executed by the
     offline WDL interpreter with mocked connectors.

Policy: a synthetic subset of the role seed by default. Set TS_SCOPE_CONFIG=<ScopeConfig.json> to run against
the authoritative table, and TS_ROLE_PROBE_EXPECTED=<role-probe-expected.json> to replay the live-proven
role-probe decisions through both implementations.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "powerautomate"))
import guard as G  # noqa: E402
import guard_template  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import Config, Employee, Role, TrustedIdentity  # noqa: E402

FIXTURE = {
    "scopes": {
        "EMP": {"TS.ViewOwn": "self", "TS.EditOwnDraft": "self", "KPI.SelfScore": "self"},
        "TL": {"TS.ViewOwn": "self", "TS.ViewOthers": "discipline", "TS.EditOwnDraft": "self", "TS.EditOnBehalf": "discipline",
               "TS.Approve": "discipline", "TS.Unapprove": "none", "TS.SelfApprove": "none", "KPI.ManagerScore": "discipline"},
        "APR": {"TS.ViewOwn": "self", "TS.ViewOthers": "company", "TS.Approve": "company", "TS.Unapprove": "company",
                "TS.SelfApprove": "none", "SAL.Review": "company", "BI.FinanceReports": "none"},
        "EXE": {"TS.ViewOthers": "company", "TS.SelfApprove": "none", "RATE.View": "none", "BI.FinanceReports": "company"},
        "HR": {"TS.ViewOwn": "self", "TS.ViewOthers": "none", "MD.Maintain": "restricted:org, positions", "RATE.View": "company"},
        "SALV": {"RATE.View": "company"},
        "FIN": {"FIN.RevenueEdit": "company", "BI.FinanceReports": "company"},
        "ADM": {"TS.ViewOwn": "self", "TS.ViewOthers": "company", "TS.SelfApprove": "none", "EMP.Maintain": "company",
                "ROLE.Admin": "company"},
        "MIGO": {"MIG.Run": "restricted:until hypercare end"},
    },
    "pending": [{"role": r, "capability": a} for r, a in [
        ("TL", "TS.Unapprove"), ("TL", "TS.SelfApprove"), ("APR", "TS.SelfApprove"), ("APR", "BI.FinanceReports"),
        ("EXE", "TS.SelfApprove"), ("EXE", "RATE.View"), ("HR", "TS.ViewOthers"), ("ADM", "TS.SelfApprove")]],
}
SCOPE_CONFIG = FIXTURE
if os.environ.get("TS_SCOPE_CONFIG"):
    with open(os.environ["TS_SCOPE_CONFIG"], encoding="utf-8") as _fh:
        SCOPE_CONFIG = json.load(_fh)
POLICY = G.Policy.from_scope_config(SCOPE_CONFIG)
ROLE_KEYS = ["EMP", "TL", "APR", "EXE", "PMO", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO"]
ROLE_GROUPS = [(k, "g-" + k.lower()) for k in ROLE_KEYS]
DOM = "tenant-a.invalid"
CFG = Config(allowed_domains=[DOM], roles=[Role(k, gid) for k, gid in ROLE_GROUPS])
EMP_LIST, AUDIT_LIST = "_Employees", "_Audit"
UNTRUSTED = ["CallerUpn", "ClaimRole", "ClaimScope", "ClientRequestId"]

TEMPLATE = guard_template.guard_actions(
    SCOPE_CONFIG, ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=DOM, emp_list=EMP_LIST,
    audit_list=AUDIT_LIST, action_expr="triggerBody()?['text']", kind_expr="triggerBody()?['text_1']",
    ref_expr="triggerBody()?['text_2']", untrusted_inputs=UNTRUSTED)


def u(name):
    return name + "@" + DOM


EMPS = [Employee(11, "E1", u("emp"), True, "D1", "DEP1"), Employee(12, "E2", u("peer"), True, "D1", "DEP1"),
        Employee(13, "E3", u("far"), True, "D2", "DEP2"), Employee(14, "E4", u("far2"), True, "D2", "DEP2"),
        Employee(15, "E5", u("gone"), False, "D1", "DEP1"), Employee(16, "E6", u("twin"), True, "D1", "DEP1"),
        Employee(17, "E7", u("twin"), True, "D2", "DEP2"), Employee(18, "E8", u("nodisc"), True, None, "DEP1")]


def rows(emps):
    return [{"Id": e.item_id, "LegacyId": e.legacy_id, "IsActive": e.is_active, "DisciplineCode": e.discipline_id,
             "AccountUpn": e.account_upn} for e in emps]


def lookup_rows(emps):
    """Operational `Employees` shape: the discipline code arrives through the expanded `Discipline` lookup (null when unset)."""
    return [{"Id": e.item_id, "LegacyId": e.legacy_id, "IsActive": e.is_active, "AccountUpn": e.account_upn,
             "Discipline": {"DisciplineCode": e.discipline_id} if e.discipline_id else None,
             "Department": {"DepartmentCode": e.department_id} if e.department_id else None} for e in emps]


class Case:
    seq = 0

    def __init__(self, upn, roles=(), action="TS.ViewOwn", kind="self", ref="", decoys=None, emps=EMPS, directory_down=False):
        Case.seq += 1
        self.upn, self.roles, self.action, self.kind, self.ref = upn, tuple(roles), action, kind, ref
        self.decoys = decoys or {}
        self.emps, self.directory_down = emps, directory_down
        self.cid = "run-%04d" % Case.seq

    def python(self):
        ident = TrustedIdentity(upn=self.upn, group_ids=["g-" + r.lower() for r in self.roles])

        def lookup(n):
            if self.directory_down:
                raise ConnectionError("down")
            return [e for e in self.emps if e.account_upn == n]
        target = lambda code: [e for e in self.emps if e.legacy_id == code]
        untrusted = {k: self.decoys.get(k, "") for k in UNTRUSTED}
        return G.authorize(ident, lookup, target, CFG, POLICY, self.action, self.kind, self.ref,
                           correlation_id=self.cid, **untrusted)

    def flow(self):
        audit = {}
        lists = {EMP_LIST: rows(self.emps)}
        member_of = {"g-" + r.lower() for r in self.roles}

        def mocks(name, a, p):
            opid = a["inputs"]["host"]["operationId"]
            if opid == "MyProfile_V2":
                return "Succeeded", {"userPrincipalName": self.upn}
            if opid == "ListGroupMembers":
                others = [{"userPrincipalName": u("someone-else")}]
                return "Succeeded", {"value": others + ([{"userPrincipalName": self.upn.upper()}] if p["groupId"] in member_of else [])}
            if opid == "HttpRequest" and p["parameters/method"] == "GET":
                if self.directory_down and name == "Caller_lookup":
                    return "Failed", {"error": "down"}
                return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], lists)
            if opid == "HttpRequest" and p["parameters/method"] == "POST":
                assert "getbytitle('%s')" % AUDIT_LIST in p["parameters/uri"]
                audit.update(json.loads(p["parameters/body"]))
                return "Succeeded", {"Id": 1}
            raise AssertionError("unexpected connector call %s" % opid)
        trig = {"text": self.action, "text_1": self.kind, "text_2": self.ref,
                "text_3": self.decoys.get("CallerUpn", ""), "text_4": self.decoys.get("ClaimRole", ""),
                "text_5": self.decoys.get("ClaimScope", ""), "text_6": self.decoys.get("ClientRequestId", "")}
        run = wdl_sim.Run(trigger_body=trig, run_name=self.cid, mocks=mocks).run(TEMPLATE)
        return run.results["Guard_result"]["outputs"], audit


FIELDS = ["AuthenticatedUpn", "EmployeeId", "EmployeeCode", "IsActive", "ResolvedRoles", "RequestedAction",
          "RequestedScope", "ResolvedScope", "AuthorizationDecision", "ResultCode", "CorrelationId", "IgnoredInputs"]


class Base(unittest.TestCase):
    def check(self, case, code, decision=None):
        py = case.python()
        fl, audit = case.flow()
        got = {k: getattr(py, k) for k in FIELDS}
        self.assertEqual(got, {k: fl.get(k) for k in FIELDS}, "python vs flow template differ")
        self.assertEqual(py.audit_payload(), audit, "audit payload python vs flow template differ")
        self.assertEqual(py.ResultCode, code)
        self.assertEqual(py.AuthorizationDecision, decision or ("ALLOW" if code == "ALLOW" else "DENY"))
        return py, audit


class GuardTests(Base):
    def test_G01_active_employee_own_scope_allowed(self):
        r, _ = self.check(Case(u("emp"), ["EMP"], "TS.ViewOwn", "self"), "ALLOW")
        self.assertEqual((r.EmployeeId, r.EmployeeCode, r.IsActive, r.ResolvedRoles, r.ResolvedScope), (11, "E1", True, ["EMP"], "self"))
        self.check(Case(u("emp"), ["EMP"], "TS.EditOwnDraft", "employee", "E1"), "ALLOW")

    def test_G02_forged_caller_ignored(self):
        forged = {"CallerUpn": u("appr-boss"), "ClientRequestId": "x"}
        r, _ = self.check(Case(u("emp"), ["EMP"], "TS.ViewOwn", "self", decoys=forged), "ALLOW")
        self.assertEqual(r.AuthenticatedUpn, u("emp"))
        self.assertEqual(r.EmployeeCode, "E1")
        self.check(Case(u("emp"), ["EMP"], "TS.ViewOthers", "employee", "E3", decoys=forged), "ROLE_NOT_ALLOWED")
        self.check(Case(u("stranger"), ["APR"], "TS.ViewOwn", "self", decoys={"CallerUpn": u("emp")}), "UNMAPPED_IDENTITY")

    def test_G03_employee_other_employee_denied(self):
        for ref in ("E2", "E3"):
            self.check(Case(u("emp"), ["EMP"], "TS.ViewOwn", "employee", ref), "SCOPE_NOT_ALLOWED")
            self.check(Case(u("emp"), ["EMP"], "TS.EditOwnDraft", "employee", ref), "SCOPE_NOT_ALLOWED")
        self.check(Case(u("emp"), ["EMP"], "TS.ViewOwn", "discipline", "D1"), "SCOPE_NOT_ALLOWED")
        self.check(Case(u("emp"), ["EMP"], "TS.ViewOwn", "company"), "SCOPE_NOT_ALLOWED")
        self.check(Case(u("emp"), ["EMP"], "TS.ViewOwn", "employee", "NOPE"), "SCOPE_NOT_ALLOWED")

    def test_G04_team_leader_own_discipline_allowed(self):
        for a in ("TS.ViewOthers", "TS.EditOnBehalf", "TS.Approve", "KPI.ManagerScore"):
            r, _ = self.check(Case(u("emp"), ["TL"], a, "employee", "E2"), "ALLOW")
            self.assertEqual(r.ResolvedScope, "discipline")
            self.check(Case(u("emp"), ["TL"], a, "discipline", "D1"), "ALLOW")

    def test_G05_team_leader_other_discipline_denied(self):
        for a in ("TS.ViewOthers", "TS.EditOnBehalf", "TS.Approve", "KPI.ManagerScore"):
            self.check(Case(u("emp"), ["TL"], a, "employee", "E3"), "SCOPE_NOT_ALLOWED")
            self.check(Case(u("emp"), ["TL"], a, "discipline", "D2"), "SCOPE_NOT_ALLOWED")
            self.check(Case(u("emp"), ["TL"], a, "company"), "SCOPE_NOT_ALLOWED")
        self.check(Case(u("nodisc"), ["TL"], "TS.Approve", "employee", "E8"), "SCOPE_NOT_ALLOWED")

    def test_G06_unknown_scope_denied(self):
        for kind, ref in (("everyone", ""), ("", ""), ("tenant", "x"), ("employee", ""), ("discipline", "")):
            self.check(Case(u("emp"), ["APR"], "TS.ViewOthers", kind, ref), "UNKNOWN_SCOPE")
        self.check(Case(u("emp"), ["HR"], "MD.Maintain", "company"), "UNKNOWN_SCOPE")

    def test_G07_unknown_action_denied(self):
        for a in ("TS.DeleteAll", "", "ROLE.Admin2", "*"):
            self.check(Case(u("emp"), ["ADM", "APR", "EXE"], a, "company"), "UNKNOWN_ACTION")
        r, _ = self.check(Case(u("emp"), ["EMP"], "  ts.viewown ", "self"), "ALLOW")
        self.assertEqual(r.RequestedAction, "TS.ViewOwn")

    def test_G08_app_admin_has_no_salary_capability(self):
        for a in ("RATE.View", "SAL.Review", "FIN.RevenueEdit", "BI.FinanceReports"):
            self.check(Case(u("emp"), ["ADM"], a, "self"), "ROLE_NOT_ALLOWED")
            self.check(Case(u("emp"), ["ADM"], a, "company"), "ROLE_NOT_ALLOWED")
        self.check(Case(u("emp"), ["ADM", "SALV"], "RATE.View", "company"), "ALLOW")

    def test_G09_salary_viewer_rate_view_only(self):
        r, _ = self.check(Case(u("emp"), ["SALV"], "RATE.View", "company"), "ALLOW")
        self.assertEqual(r.ResolvedScope, "company")
        self.check(Case(u("emp"), ["SALV"], "RATE.View", "employee", "E3"), "ALLOW")
        for a in ("SAL.Review", "TS.ViewOwn", "TS.ViewOthers", "BI.FinanceReports"):
            self.check(Case(u("emp"), ["SALV"], a, "self"), "ROLE_NOT_ALLOWED")

    def test_G10_unresolved_decisions_denied(self):
        pend = list(POLICY.pending)
        self.assertGreater(len(pend), 0)
        for role, action in pend:
            for kind, ref in (("self", ""), ("employee", "E2"), ("company", "")):
                r, _ = self.check(Case(u("emp"), [role], action, kind, ref), "DECISION_PENDING")
                self.assertEqual(r.ResolvedScope, "none")
        if os.environ.get("TS_SCOPE_CONFIG"):
            self.assertEqual(len(pend), 11)

    def test_G11_inactive_employee_denied(self):
        r, _ = self.check(Case(u("gone"), ["APR", "ADM"], "TS.ViewOwn", "self"), "INACTIVE_EMPLOYEE")
        self.assertEqual((r.IsActive, r.EmployeeId, r.ResolvedRoles), (False, None, []))

    def test_G12_unmapped_duplicate_invalid_identity_denied(self):
        r, _ = self.check(Case(u("stranger"), ["APR"], "TS.ViewOwn", "self"), "UNMAPPED_IDENTITY")
        self.assertEqual((r.EmployeeId, r.ResolvedRoles), (None, []))
        self.check(Case(u("twin"), ["APR"], "TS.ViewOwn", "self"), "DUPLICATE_IDENTITY")
        self.check(Case("emp@other-tenant.invalid", ["APR"], "TS.ViewOwn", "self"), "INVALID_IDENTITY")
        self.check(Case(u("emp"), ["APR"], "TS.ViewOwn", "self", directory_down=True), "DIRECTORY_ERROR")

    def test_G13_multiple_roles_union_most_permissive(self):
        r, _ = self.check(Case(u("emp"), ["EMP", "TL"], "TS.ViewOthers", "employee", "E2"), "ALLOW")
        self.assertEqual((r.ResolvedRoles, r.ResolvedScope), (["EMP", "TL"], "discipline"))
        self.check(Case(u("emp"), ["EMP", "TL"], "TS.ViewOthers", "employee", "E3"), "SCOPE_NOT_ALLOWED")
        r, _ = self.check(Case(u("emp"), ["EMP", "TL", "APR"], "TS.ViewOthers", "employee", "E3"), "ALLOW")
        self.assertEqual(r.ResolvedScope, "company")
        self.check(Case(u("emp"), ["TL", "SALV"], "RATE.View", "company"), "ALLOW")
        self.check(Case(u("emp"), ["TL", "SALV"], "TS.Approve", "employee", "E3"), "SCOPE_NOT_ALLOWED")
        self.check(Case(u("emp"), ["TL", "APR"], "TS.Unapprove", "employee", "E3"), "ALLOW")
        self.check(Case(u("emp"), ["TL", "APR"], "TS.SelfApprove", "self"), "DECISION_PENDING")
        self.check(Case(u("emp"), ["EMP", "MIGO"], "MIG.Run", "company"), "TEMP_ROLE_INACTIVE")
        self.check(Case(u("emp"), ["ADM", "HR"], "MD.Maintain", "company"),
                   "ALLOW" if POLICY.classify("ADM", "MD.Maintain") == "company" else "UNKNOWN_SCOPE")

    def test_G14_caller_supplied_role_and_scope_claims_ignored(self):
        claims = {"ClaimRole": "APR,ADM,SALV", "ClaimScope": "company", "CallerUpn": u("emp")}
        r, audit = self.check(Case(u("emp"), ["EMP"], "TS.Approve", "company", decoys=claims), "ROLE_NOT_ALLOWED")
        self.assertEqual(r.ResolvedRoles, ["EMP"])
        self.assertEqual(r.IgnoredInputs, sorted(UNTRUSTED))
        self.check(Case(u("emp"), [], "ROLE.Admin", "company", decoys=claims), "ROLE_NOT_ALLOWED")
        self.check(Case(u("emp"), [], "RATE.View", "company", decoys=claims), "ROLE_NOT_ALLOWED")
        self.assertNotIn("APR,ADM,SALV", json.dumps(audit))

    def test_G14b_template_reads_only_action_and_scope_from_request(self):
        src = json.dumps(TEMPLATE)
        self.assertEqual(set(re.findall(r"triggerBody\(\)\?\['(\w+)'\]", src)), {"text", "text_1", "text_2"})
        self.assertNotIn("triggerOutputs", src)
        self.assertNotIn("x-ms-user", src)
        self.assertNotIn("''", src)
        self.assertNotIn("coalesce(", src)

    def test_G15_correlation_and_audit_payload(self):
        c1, c2 = Case(u("emp"), ["TL"], "TS.Approve", "employee", "E2"), Case(u("emp"), ["TL"], "TS.Approve", "employee", "E3")
        r1, a1 = self.check(c1, "ALLOW")
        r2, a2 = self.check(c2, "SCOPE_NOT_ALLOWED")
        self.assertEqual((a1["CorrelationId"], a2["CorrelationId"]), (c1.cid, c2.cid))
        self.assertNotEqual(a1["CorrelationId"], a2["CorrelationId"])
        self.assertEqual((a1["Decision"], a2["Decision"]), ("ALLOWED", "DENIED"))
        self.assertEqual(a1["CallerUpnTrusted"], u("emp"))
        self.assertEqual(a1["Title"], "guard TS.Approve ALLOW")
        self.assertEqual(a1["Detail"], "kind=guard;employeeId=11;employeeCode=E1;isActive=true;roles=TL;action=TS.Approve;"
                                       "scope=employee:E2;resolvedScope=discipline;ignored=CallerUpn,ClaimRole,ClaimScope,ClientRequestId;")
        _, a3 = self.check(Case(u("emp"), ["TL"], "TS.Approve", "employee", "NOPE"), "SCOPE_NOT_ALLOWED")
        self.assertTrue(a3["Detail"].endswith(";target=0"))
        _, a4 = self.check(Case(u("stranger"), [], "TS.ViewOwn", "self"), "UNMAPPED_IDENTITY")
        self.assertEqual((a4["Decision"], a4["CallerUpnTrusted"]), ("DENIED", u("stranger")))


@unittest.skipUnless(os.environ.get("TS_ROLE_PROBE_EXPECTED") and os.environ.get("TS_SCOPE_CONFIG"),
                     "set TS_SCOPE_CONFIG and TS_ROLE_PROBE_EXPECTED to replay the live role-probe decisions")
class ProbeReplay(Base):
    def test_replay_live_role_probe_decisions(self):
        with open(os.environ["TS_ROLE_PROBE_EXPECTED"], encoding="utf-8") as fh:
            d = json.load(fh)
        tgt = [Employee(100 + i, code, u("syn%d" % i), True, disc) for i, (code, disc) in enumerate(d["targets"])]
        n = 0
        for role, exp in d["expected"].items():
            roles = [] if role == "NONE" else [role]
            for e in exp:
                case = Case(u("syn0"), roles, e["a"], "employee", d["targets"][e["t"]][0], emps=tgt)
                py = case.python()
                fl, _ = case.flow()
                self.assertEqual(py.allowed, e["allow"], (role, e))
                self.assertEqual(fl["AuthorizationDecision"], "ALLOW" if e["allow"] else "DENY", (role, e))
                n += 1
        print("\nreplayed %d live role-probe decisions" % n)
        self.assertEqual(n, 273)


if __name__ == "__main__":
    unittest.main(verbosity=2)
