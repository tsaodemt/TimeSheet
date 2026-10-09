"""S07.1 approval capability tests AP-R01..AP-R24 (synthetic data only; run: python -m unittest test_approval_rules).

Every guard call made by approval_rules.decide is also executed through the generated Power Automate guard
template (tools/powerautomate/guard_template.py) in the offline WDL interpreter; both must agree.

Policy: approval_rules.scope_config() (the documented S07.1 matrix). Set TS_SCOPE_CONFIG=<ScopeConfig.json> to
also check that the authoritative role seed grants exactly the same approval capabilities.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "identity"))
sys.path.insert(0, os.path.join(HERE, "..", "powerautomate"))
import approval_rules as AR  # noqa: E402
import guard as G  # noqa: E402
import guard_template  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import Config, Employee, Role, TrustedIdentity  # noqa: E402

CFG_SCOPES = AR.scope_config()
POLICY = G.Policy.from_scope_config(CFG_SCOPES)
ROLE_KEYS = [r.role for r in AR.MATRIX]
ROLE_GROUPS = [(k, "g-" + k.lower()) for k in ROLE_KEYS]
DOM = "tenant-a.invalid"
CFG = Config(allowed_domains=[DOM], roles=[Role(k, gid) for k, gid in ROLE_GROUPS])
EMP_LIST, AUDIT_LIST = "_Employees", "_Audit"
UNTRUSTED = ["OwnerUpn", "ClaimRole", "ClaimScope", "ClientRequestId"]
TEMPLATE = guard_template.guard_actions(
    CFG_SCOPES, ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=DOM, emp_list=EMP_LIST,
    audit_list=AUDIT_LIST, action_expr="triggerBody()?['text']", kind_expr="triggerBody()?['text_1']",
    ref_expr="triggerBody()?['text_2']", untrusted_inputs=UNTRUSTED)


def u(name):
    return name + "@" + DOM


EMPS = [Employee(11, "E1", u("lead"), True, "D1", "DEP1"), Employee(12, "E2", u("peer"), True, "D1", "DEP1"),
        Employee(13, "E3", u("far"), True, "D2", "DEP2"), Employee(15, "E5", u("gone"), False, "D1", "DEP1"),
        Employee(18, "E8", u("nodisc"), True, None, "DEP1")]
BY_CODE = {e.legacy_id: e for e in EMPS}
FIELDS = ["AuthenticatedUpn", "EmployeeCode", "ResolvedRoles", "RequestedAction", "RequestedScope", "ResolvedScope",
          "AuthorizationDecision", "ResultCode", "CorrelationId", "IgnoredInputs"]


def entry(code, owner_upn=None):
    """Stored row of employee `code`; owner_upn overrides the stored owner UPN (only to test the UPN self-check)."""
    e = BY_CODE.get(code)
    return AR.StoredEntry(code, owner_upn if owner_upn is not None else (e.account_upn if e else ""))


def run(upn, roles, operation, stored, decoys=None, cid="run-0001"):
    ident = TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])
    lookup = lambda n: [e for e in EMPS if e.account_upn == n]
    target = lambda code: [e for e in EMPS if e.legacy_id == code]
    untrusted = {k: (decoys or {}).get(k, "") for k in UNTRUSTED}
    return AR.decide(ident, lookup, target, CFG, POLICY, operation, stored, correlation_id=cid, **untrusted)


def flow_guard(upn, roles, action, kind, ref, decoys, cid):
    member_of = {"g-" + r.lower() for r in roles}
    lists = {EMP_LIST: [{"Id": e.item_id, "LegacyId": e.legacy_id, "IsActive": e.is_active,
                         "DisciplineCode": e.discipline_id, "AccountUpn": e.account_upn} for e in EMPS]}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        if opid == "HttpRequest" and p["parameters/method"] == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], lists)
        if opid == "HttpRequest" and p["parameters/method"] == "POST":
            return "Succeeded", {"Id": 1}
        raise AssertionError("unexpected connector call %s" % opid)
    d = decoys or {}
    trig = {"text": action, "text_1": kind, "text_2": ref, "text_3": d.get("OwnerUpn", ""),
            "text_4": d.get("ClaimRole", ""), "text_5": d.get("ClaimScope", ""), "text_6": d.get("ClientRequestId", "")}
    return wdl_sim.Run(trigger_body=trig, run_name=cid, mocks=mocks).run(TEMPLATE).results["Guard_result"]["outputs"]


class Base(unittest.TestCase):
    seq = 0

    def check(self, upn, roles, operation, stored, code, *, is_self=None, decoys=None):
        Base.seq += 1
        cid = "run-%04d" % Base.seq
        d = run(upn, roles, operation, stored, decoys, cid)
        self.assertEqual(d.result_code, code, "%s %s %s" % (roles, operation, stored))
        self.assertEqual(d.allowed, code == G.R_ALLOW)
        if is_self is not None:
            self.assertEqual(d.is_self, is_self)
        for g in d.guard_results:  # reference guard == generated flow guard, field by field
            fl = flow_guard(upn, roles, g.RequestedAction, g.RequestedScope.split(":")[0],
                            g.RequestedScope.partition(":")[2], decoys, cid)
            for f in FIELDS:
                self.assertEqual(getattr(g, f), fl[f], "flow/reference differ on %s" % f)
        return d


class MatrixTests(Base):
    def test_R01_every_role_has_one_row_with_a_valid_status(self):
        self.assertEqual(len(ROLE_KEYS), len(set(ROLE_KEYS)))
        self.assertEqual(set(ROLE_KEYS), {"EMP", "TL", "APR", "EXE", "PMO", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO"})
        for r in AR.MATRIX:
            self.assertIn(r.status, AR.STATUSES)
            self.assertIn(r.approve, ("none", "self", "discipline", "company"))
            self.assertIn(r.unapprove, ("none", "self", "discipline", "company"))
            self.assertTrue(r.evidence)

    def test_R02_pending_cells_are_never_grants(self):
        for r in AR.MATRIX:
            for cap in r.pending:
                self.assertEqual(POLICY.classify(r.role, cap), "pending", (r.role, cap))
            if r.pending:
                self.assertEqual(r.status, AR.DECISION_PENDING, r.role)

    def test_R03_self_approval_pending_for_every_role_that_can_approve(self):
        for r in AR.MATRIX:
            if r.approve != "none" or r.unapprove != "none":
                self.assertEqual(r.pending.get(AR.SELF_CAPABILITY), "UD-04", r.role)
            self.assertNotIn(POLICY.classify(r.role, AR.SELF_CAPABILITY), ("self", "discipline", "company"))

    def test_R04_capabilities_are_independent(self):
        """UD-05: approve does not imply unapprove (Team Leader)."""
        tl = {r.role: r for r in AR.MATRIX}["TL"]
        self.assertEqual((tl.approve, POLICY.classify("TL", "TS.Unapprove")), ("discipline", "pending"))

    def test_R05_no_director_role_and_no_new_action_ids(self):
        self.assertNotIn("DIR", ROLE_KEYS)
        self.assertEqual(set(POLICY.actions.values()), set(AR.APPROVAL_CAPABILITIES))

    @unittest.skipUnless(os.environ.get("TS_SCOPE_CONFIG"), "TS_SCOPE_CONFIG not set")
    def test_R06_matrix_equals_authoritative_seed(self):
        with open(os.environ["TS_SCOPE_CONFIG"], encoding="utf-8-sig") as fh:
            seed = json.load(fh)
        caps = AR.APPROVAL_CAPABILITIES
        ours = {(r, a): v for r, acts in CFG_SCOPES["scopes"].items() for a, v in acts.items()}
        theirs = {(r, a): v for r, acts in seed["scopes"].items() for a, v in acts.items() if a in caps}
        self.assertEqual(ours, theirs)
        pend = lambda c: {(p["role"], p["capability"]) for p in c["pending"] if p["capability"] in caps}
        self.assertEqual(pend(CFG_SCOPES), pend(seed))


class ApproveTests(Base):
    def test_R07_member_denied(self):
        self.check(u("lead"), ["EMP"], AR.APPROVE, entry("E2"), G.ROLE_NOT_ALLOWED)

    def test_R08_team_leader_same_discipline_allowed(self):
        self.check(u("lead"), ["TL"], AR.APPROVE, entry("E2"), G.R_ALLOW, is_self=False)

    def test_R09_team_leader_cross_discipline_denied(self):
        self.check(u("lead"), ["TL"], AR.APPROVE, entry("E3"), G.SCOPE_NOT_ALLOWED)

    def test_R10_team_leader_without_discipline_denied(self):
        self.check(u("nodisc"), ["TL"], AR.APPROVE, entry("E2"), G.SCOPE_NOT_ALLOWED)

    def test_R11_approver_company_scope(self):
        for code in ("E2", "E3"):
            self.check(u("lead"), ["APR"], AR.APPROVE, entry(code), G.R_ALLOW)

    def test_R12_executive_and_appadmin_company_scope(self):
        for role in ("EXE", "ADM"):
            self.check(u("lead"), [role], AR.APPROVE, entry("E3"), G.R_ALLOW)

    def test_R13_non_approving_roles_denied(self):
        for role in ("PMO", "HR", "SALV", "FIN", "ITS", "CONFO", "MIGO"):
            self.check(u("lead"), [role], AR.APPROVE, entry("E2"), G.ROLE_NOT_ALLOWED)
            self.check(u("lead"), [role], AR.UNAPPROVE, entry("E2"), G.ROLE_NOT_ALLOWED)

    def test_R14_self_approval_denied_for_every_approving_role(self):
        for role in ("TL", "APR", "EXE", "ADM"):
            self.check(u("lead"), [role], AR.APPROVE, entry("E1"), G.DECISION_PENDING, is_self=True)

    def test_R15_self_detected_by_upn_as_well_as_employee_code(self):
        self.check(u("lead"), ["APR"], AR.APPROVE, entry("E2", owner_upn=u("LEAD")), G.DECISION_PENDING, is_self=True)


class UnapproveTests(Base):
    def test_R16_team_leader_cannot_unapprove(self):
        self.check(u("lead"), ["TL"], AR.UNAPPROVE, entry("E2"), G.DECISION_PENDING)

    def test_R17_approver_executive_appadmin_unapprove_company(self):
        for role in ("APR", "EXE", "ADM"):
            self.check(u("lead"), [role], AR.UNAPPROVE, entry("E3"), G.R_ALLOW)

    def test_R18_own_entry_unapprove_denied(self):
        for role in ("APR", "EXE", "ADM"):
            self.check(u("lead"), [role], AR.UNAPPROVE, entry("E1"), G.DECISION_PENDING, is_self=True)

    def test_R19_member_cannot_unapprove(self):
        self.check(u("lead"), ["EMP"], AR.UNAPPROVE, entry("E2"), G.ROLE_NOT_ALLOWED)


class TrustTests(Base):
    def test_R20_multi_role_union_but_self_still_denied(self):
        self.check(u("lead"), ["EMP", "TL"], AR.APPROVE, entry("E3"), G.SCOPE_NOT_ALLOWED)
        self.check(u("lead"), ["TL", "APR"], AR.APPROVE, entry("E3"), G.R_ALLOW)
        self.check(u("lead"), ["TL", "APR"], AR.UNAPPROVE, entry("E3"), G.R_ALLOW)
        self.check(u("lead"), ["TL", "APR", "ADM"], AR.APPROVE, entry("E1"), G.DECISION_PENDING, is_self=True)

    def test_R21_inactive_employee_denied(self):
        self.check(u("gone"), ["APR"], AR.APPROVE, entry("E2"), G.INACTIVE_EMPLOYEE)

    def test_R22_forged_owner_upn_ignored(self):
        claims = {"OwnerUpn": u("peer")}
        d = self.check(u("lead"), ["TL"], AR.APPROVE, entry("E3"), G.SCOPE_NOT_ALLOWED, decoys=claims)
        self.assertIn("OwnerUpn", d.guard_results[0].IgnoredInputs)
        self.check(u("lead"), ["APR"], AR.APPROVE, entry("E1"), G.DECISION_PENDING, is_self=True,
                   decoys={"OwnerUpn": u("far")})

    def test_R23_forged_role_and_scope_ignored(self):
        claims = {"ClaimRole": "APR,EXE,ADM", "ClaimScope": "company"}
        self.check(u("lead"), ["EMP"], AR.APPROVE, entry("E2"), G.ROLE_NOT_ALLOWED, decoys=claims)
        self.check(u("lead"), ["TL"], AR.UNAPPROVE, entry("E2"), G.DECISION_PENDING, decoys=claims)

    def test_R24_unknown_operation_and_unknown_target_denied(self):
        for op in ("Lock", "Unlock", "approve ", "", None):
            d = run(u("lead"), ["ADM"], op, entry("E2"))
            self.assertEqual((d.allowed, d.result_code), (False, G.UNKNOWN_ACTION))
        self.check(u("lead"), ["APR"], AR.APPROVE, entry("NOPE"), G.SCOPE_NOT_ALLOWED)


if __name__ == "__main__":
    unittest.main()
