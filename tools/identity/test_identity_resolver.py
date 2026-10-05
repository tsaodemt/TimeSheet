"""Identity-resolution contract tests I1-I10 (synthetic data only; run: python -m unittest)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from identity_resolver import (  # noqa: E402
    ACCOUNT_NOT_ALLOWED, DIRECTORY_ERROR, DUPLICATE_MAPPING, INACTIVE, INVALID_IDENTITY, NOT_REGISTERED, OK,
    Config, Employee, Role, TrustedIdentity, migrate_upn, resolve)

DOM = "tenant-a.invalid"
G_EMP, G_TL = "group-emp", "group-tl"
CFG = Config(allowed_domains=[DOM], roles=[
    Role("EMP", G_EMP, ["TS.ViewOwn", "TS.EditOwnDraft"]),
    Role("TL", G_TL, ["TS.Approve", "TS.ViewOthers"]),
])

EMPLOYEES = [
    Employee(1, "L-001", "anna.active@" + DOM, True, 10),
    Employee(2, "L-002", "ivan.inactive@" + DOM, False, 10),
    Employee(3, "L-003", "dup.user@" + DOM, True, 11),
    Employee(4, "L-004", "dup.user@" + DOM, True, 12),
    Employee(5, "L-005", "", True, 10),            # unmapped active employee: AccountUpn empty
]


def lookup(upn):
    return [e for e in EMPLOYEES if e.account_upn.lower() == upn]


def ident(upn, groups=(G_EMP,), **kw):
    return TrustedIdentity(upn=upn, group_ids=groups, **kw)


class IdentityContract(unittest.TestCase):
    def test_I1_mapped_active_user(self):
        r = resolve(ident("anna.active@" + DOM), lookup, CFG)
        self.assertEqual(r.code, OK)
        self.assertEqual((r.employee.legacy_id, r.roles), ("L-001", ["EMP"]))
        self.assertIn("TS.ViewOwn", r.capabilities)

    def test_I2_case_insensitive_and_whitespace(self):
        r = resolve(ident("  Anna.ACTIVE@Tenant-A.invalid "), lookup, CFG)
        self.assertEqual((r.code, r.employee.item_id), (OK, 1))

    def test_I3_forged_upn_fields_are_ignored(self):
        r = resolve(ident("anna.active@" + DOM), lookup, CFG,
                    CallerUpn="dup.user@" + DOM, OwnerUpn="ivan.inactive@" + DOM, ActorUpn="x@" + DOM,
                    DisplayName="Someone Else", Author="ivan.inactive@" + DOM,
                    headers={"x-ms-user-email": "ivan.inactive@" + DOM}, ClaimReviewer=True)
        self.assertEqual((r.code, r.employee.item_id, r.roles), (OK, 1, ["EMP"]))
        # a caller with no trusted identity cannot become someone via request fields
        r2 = resolve(None, lookup, CFG, CallerUpn="anna.active@" + DOM)
        self.assertEqual((r2.code, r2.employee), (INVALID_IDENTITY, None))

    def test_I4_unmapped_user(self):
        r = resolve(ident("nobody.mapped@" + DOM), lookup, CFG)
        self.assertEqual((r.code, r.employee, r.capabilities), (NOT_REGISTERED, None, []))

    def test_I5_duplicate_mapping_fails_closed(self):
        r = resolve(ident("dup.user@" + DOM), lookup, CFG)
        self.assertEqual((r.code, r.employee, r.roles), (DUPLICATE_MAPPING, None, []))

    def test_I6_inactive_employee(self):
        r = resolve(ident("ivan.inactive@" + DOM), lookup, CFG)
        self.assertEqual((r.code, r.employee, r.roles), (INACTIVE, None, []))

    def test_I7_status_conflict_is_not_resolved(self):
        # A STATUS_CONFLICT person (inactive in HR data, active directory account) is never loaded into
        # AccountUpn (load rule S03.3); the account signs in and resolves to nothing.
        r = resolve(ident("conflict.person@" + DOM), lookup, CFG)
        self.assertEqual((r.code, r.employee), (NOT_REGISTERED, None))
        # If the mapping were loaded by mistake onto the inactive row, it still fails closed.
        emps = EMPLOYEES + [Employee(9, "L-009", "conflict.person@" + DOM, False)]
        r2 = resolve(ident("conflict.person@" + DOM), lambda u: [e for e in emps if e.account_upn == u], CFG)
        self.assertEqual(r2.code, INACTIVE)

    def test_I8_tenant_user_not_employee_guest_disabled_foreign(self):
        self.assertEqual(resolve(ident("shared.mailbox@" + DOM), lookup, CFG).code, NOT_REGISTERED)
        self.assertEqual(resolve(ident("anna.active@" + DOM, user_type="Guest"), lookup, CFG).code,
                         ACCOUNT_NOT_ALLOWED)
        self.assertEqual(resolve(ident("anna.active@" + DOM, account_enabled=False), lookup, CFG).code,
                         ACCOUNT_NOT_ALLOWED)
        self.assertEqual(resolve(ident("anna.active@other.invalid"), lookup, CFG).code, INVALID_IDENTITY)
        self.assertEqual(resolve(ident("not-an-upn"), lookup, CFG).code, INVALID_IDENTITY)
        self.assertEqual(resolve(ident(""), lookup, CFG).code, INVALID_IDENTITY)

    def test_I9_usable_by_guarded_flows(self):
        # flows need: canonical owner key, stable business key, discipline, live roles; errors fail closed
        r = resolve(ident("anna.active@" + DOM, groups=(G_EMP, G_TL)), lookup, CFG)
        self.assertEqual(r.upn, "anna.active@" + DOM)
        self.assertEqual((r.employee.legacy_id, r.employee.discipline_id), ("L-001", 10))
        self.assertEqual(r.roles, ["EMP", "TL"])
        # membership removed -> next resolution has no TL capability (live check, no cache)
        r2 = resolve(ident("anna.active@" + DOM, groups=(G_EMP,)), lookup, CFG)
        self.assertNotIn("TS.Approve", r2.capabilities)
        # no group at all -> employee context but no capability (roles only from groups)
        r3 = resolve(ident("anna.active@" + DOM, groups=()), lookup, CFG)
        self.assertEqual((r3.code, r3.roles, r3.capabilities), (OK, [], []))

        def broken(_):
            raise TimeoutError()
        self.assertEqual(resolve(ident("anna.active@" + DOM), broken, CFG).code, DIRECTORY_ERROR)

    def test_I10_tenant_portability(self):
        new_dom = "tenant-b.invalid"
        upn_map = {"anna.active@" + DOM: "anna.a@" + new_dom}
        new_upn = migrate_upn("ANNA.active@" + DOM, upn_map)
        self.assertEqual(new_upn, "anna.a@" + new_dom)
        self.assertIsNone(migrate_upn("unknown@" + DOM, upn_map))  # never guessed
        # same business key, new item IDs and group IDs in the new tenant: only configuration changes
        emps_b = [Employee(101, "L-001", new_upn, True, 77)]
        cfg_b = Config(allowed_domains=[new_dom], roles=[Role("EMP", "group-emp-b", ["TS.ViewOwn"])])
        r = resolve(ident(new_upn, groups=("group-emp-b",)), lambda u: [e for e in emps_b if e.account_upn == u], cfg_b)
        self.assertEqual((r.code, r.employee.legacy_id, r.roles), (OK, "L-001", ["EMP"]))
        # old-tenant identities are rejected by the new configuration
        self.assertEqual(resolve(ident("anna.active@" + DOM), lookup, cfg_b).code, INVALID_IDENTITY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
