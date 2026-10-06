"""Data-scoping tests S1-S8 (synthetic data only; run: python -m unittest)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from identity_resolver import Config, Employee, Role, TrustedIdentity, resolve  # noqa: E402
from scope_resolver import Target, allowed, effective_scope  # noqa: E402

DOM = "tenant-a.invalid"
CFG = Config(allowed_domains=[DOM], roles=[Role("EMP", "g-emp"), Role("TL", "g-tl"), Role("APR", "g-apr")])
EMPS = [Employee(1, "E1", "emp@" + DOM, True, "D1"), Employee(2, "E2", "lead@" + DOM, True, "D1"),
        Employee(3, "E3", "appr@" + DOM, True, "D2"), Employee(4, "E4", "other@" + DOM, True, "D2"),
        Employee(5, "E5", "nodisc@" + DOM, True, None)]
SCOPES = {"EMP": {"ts.read": "self", "ts.edit": "self"},
          "TL": {"ts.read": "discipline", "ts.edit": "discipline", "ts.approve": "discipline"},
          "APR": {"ts.read": "company", "ts.edit": "company", "ts.approve": "company"}}


def who(upn, groups):
    return resolve(TrustedIdentity(upn=upn + "@" + DOM, group_ids=groups),
                   lambda u: [e for e in EMPS if e.account_upn == u], CFG)


T_OWN_D1 = Target("E1", "D1")
T_OTHER_D1 = Target("E2", "D1")
T_D2 = Target("E4", "D2")


class Scoping(unittest.TestCase):
    def test_S1_employee_self_only(self):
        r = who("emp", ("g-emp",))
        self.assertTrue(allowed(r, "ts.read", T_OWN_D1, SCOPES))
        self.assertFalse(allowed(r, "ts.read", T_OTHER_D1, SCOPES))
        self.assertFalse(allowed(r, "ts.approve", T_OWN_D1, SCOPES))  # no scope for action -> deny

    def test_S2_leader_own_discipline_only(self):
        r = who("lead", ("g-emp", "g-tl"))
        self.assertTrue(allowed(r, "ts.approve", T_OWN_D1, SCOPES))
        self.assertFalse(allowed(r, "ts.approve", T_D2, SCOPES))

    def test_S3_approver_company(self):
        r = who("appr", ("g-emp", "g-apr"))
        self.assertTrue(allowed(r, "ts.approve", T_OWN_D1, SCOPES))
        self.assertTrue(allowed(r, "ts.read", T_D2, SCOPES))

    def test_S4_union_is_most_permissive(self):
        self.assertEqual(effective_scope(["EMP", "TL"], "ts.read", SCOPES), "discipline")
        self.assertEqual(effective_scope(["EMP", "TL", "APR"], "ts.read", SCOPES), "company")

    def test_S5_leader_without_discipline_fails_closed(self):
        r = who("nodisc", ("g-emp", "g-tl"))
        self.assertFalse(allowed(r, "ts.read", Target("E9", None), SCOPES))
        self.assertFalse(allowed(r, "ts.read", T_OWN_D1, SCOPES))

    def test_S6_unresolved_identity_denied(self):
        r = who("stranger", ("g-apr",))
        self.assertFalse(r.ok)
        self.assertFalse(allowed(r, "ts.read", T_OWN_D1, SCOPES))
        self.assertFalse(allowed(None, "ts.read", T_OWN_D1, SCOPES))

    def test_S7_project_assignment_scoping(self):
        r = who("emp", ("g-emp",))
        t = Target("E1", "D1", project_id="P1")
        self.assertTrue(allowed(r, "ts.edit", t, SCOPES))  # setting Off (default): no restriction
        self.assertFalse(allowed(r, "ts.edit", t, SCOPES, project_assignment_scoping=True, assigned_projects=["P2"]))
        self.assertTrue(allowed(r, "ts.edit", t, SCOPES, project_assignment_scoping=True, assigned_projects=["P1"]))
        a = who("appr", ("g-emp", "g-apr"))
        self.assertTrue(allowed(a, "ts.edit", t, SCOPES, project_assignment_scoping=True, exempt_roles=["APR"]))

    def test_S9_unknown_or_restricted_scope_values_deny(self):
        table = {"EMP": {"ts.read": "restricted:pending decision", "ts.edit": "Company", "ts.approve": ""}}
        r = who("emp", ("g-emp",))
        for action in ("ts.read", "ts.edit", "ts.approve", "not.configured"):
            self.assertEqual(effective_scope(["EMP"], action, table), "none")
            self.assertFalse(allowed(r, action, T_OWN_D1, table))

    def test_S8_role_removed_scope_shrinks_next_call(self):
        self.assertTrue(allowed(who("lead", ("g-emp", "g-tl")), "ts.read", T_OWN_D1, SCOPES))  # E1, same discipline
        self.assertFalse(allowed(who("lead", ("g-emp",)), "ts.read", T_OWN_D1, SCOPES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
