"""S06.1 TimesheetEntries: schema, index decisions, lookups, permissions, provisioning plan, migration status.
Tests TE01-TE21 (offline; nothing executed). Set TS_TARGET_SCHEMA to also reconcile against the local target definition."""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for d in (HERE, os.path.join(HERE, "..", "timesheet"), os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"),
          os.path.join(HERE, "..", "config"), os.path.join(HERE, "..", "alm"), os.path.join(HERE, "..", "audit")):
    sys.path.insert(0, d)
import permission_plan as pp  # noqa: E402
import r1_lists as rl  # noqa: E402
import schema_reconcile as sr  # noqa: E402
from test_schema_reconcile import ALLOWED, MAIN, F, FakeSite  # noqa: E402

E = rl.ENTRIES
OWNERS, ADMIN, SVC = 3, 9, 77
MASTERS = ("Employees", "Shifts", "HourTypes", "Phases", "WorkTypes")


def fields(t=None):
    return {f["internalName"]: f for f in (t or rl.target(E))["fields"]}


def site(with_projects=False):
    lists = [{"title": t, "itemCount": 0, "system": False, "fields": [dict(F("Title", "Text"), builtIn=True)]}
             for t in MASTERS + (("Projects",) if with_projects else ())]
    return {"site": ALLOWED, "lists": lists}


def created(t=None):
    """Columns an R1 Phase 1 creates (ungated)."""
    return {n: f for n, f in fields(t).items() if not f.get("gate")}


def lookup_col(k, f):
    return k[:-2] if k.endswith("Id") and k[:-2] in f and f[k[:-2]]["type"] == "Lookup" else k


class TimesheetEntries(unittest.TestCase):
    def test_TE01_exact_schema(self):
        self.assertEqual(list(created()), ["Title", "LegacyId", "LegacyModifiedOn", "MigrationBatch", "IsLegacyPlaceholder", "LegacyOrigin",
                                           "Employee", "EmployeeItemId", "DisciplineCode", "OwnerUpn", "ActorUpn", "IsOnBehalf", "WorkDate",
                                           "PeriodKey", "Shift", "HourType", "Hours", "Project", "Phase", "WorkType", "Remark",
                                           "EntryStatus", "CorrelationId", "ApprovedBy", "ApprovedOn"])
        self.assertEqual({n: f["gate"] for n, f in fields().items() if f.get("gate")},
                         {"LegacyModifiedBy": "CONFIDENTIAL / ENV-D2: not provisioned on operational lists", "SortOrder": "S06.7 reorder",
                          "LegacyApprovalInfo": "EPIC 08 migration", "DataQualityFlags": "EPIC 08 migration"})
        self.assertEqual(fields()["Hours"]["validationFormula"], "=AND([Hours]>0,[Hours]<=24)")

    def test_TE01b_approved_by_text_upn_not_person(self):
        f = fields()
        self.assertEqual((f["ApprovedBy"]["type"], f["ApprovedBy"]["maxLength"], f["ApprovedBy"]["required"], f["ApprovedBy"]["indexed"]),
                         ("Text", 255, False, False))
        self.assertEqual((f["ApprovedOn"]["type"], f["ApprovedOn"]["dateOnly"], f["ApprovedOn"]["required"]), ("DateTime", False, False))
        self.assertNotIn("User", {x["type"] for x in f.values()}, "no Person column on TimesheetEntries")

    def test_TE02_owner_upn_indexed_security_key(self):
        f = fields()["OwnerUpn"]
        self.assertEqual((f["type"], f["required"], f["indexed"]), ("Text", True, True))
        self.assertEqual(rl.INDEX_DECISIONS[E]["OwnerUpn"][0], rl.REQUIRED)

    def test_TE03_index_decisions_enforced(self):
        idx = {n for n, f in created().items() if f["indexed"]}
        self.assertEqual(idx, {"LegacyId", "Employee", "EmployeeItemId", "DisciplineCode", "OwnerUpn", "WorkDate", "PeriodKey", "Project"})
        self.assertEqual(rl.INDEX_DECISIONS[E]["WorkDate"][0], rl.REQUIRED)
        self.assertEqual(rl.INDEX_DECISIONS[E]["EntryStatus"][0], rl.NOT_REQUIRED)
        for n, (dec, query, scale, why) in rl.INDEX_DECISIONS[E].items():
            self.assertTrue(dec and query and scale and why, n)

    def test_TE04_entry_status_choices(self):
        f = fields()["EntryStatus"]
        self.assertEqual((f["type"], f["choices"], f["default"], f["required"]), ("Choice", ["Draft", "Approved", "Deleted"], "Draft", True))
        self.assertNotIn("Rejected", f["choices"], "Rejected is reserved, not provisioned")
        self.assertIn("<Default>Draft</Default>", sr.field_schema_xml(f))

    def test_TE05_TE06_TE07_forbidden_columns(self):
        self.assertEqual(rl.FORBIDDEN_COLUMNS[E] & {"ApprovalStatus", "IsDeleted", "RequestKey"}, {"ApprovalStatus", "IsDeleted", "RequestKey"})
        self.assertFalse(set(fields()) & rl.FORBIDDEN_COLUMNS[E])

    def test_TE08_no_author_based_ownership(self):
        import r1_flows
        for n in ("TS-ReadOwn", "TS-SaveEntry"):
            blob = json.dumps(r1_flows.build(n))
            self.assertNotRegex(blob, r"Author(Id)?\s+eq|Author(Id)?(?!ization)", n)  # never an ownership filter or column
            self.assertIn("OwnerUpn eq ", blob, n)
        self.assertNotIn("Author", fields())

    def test_TE09_service_level_never_delete(self):
        lv = rl.level_assessment(E)
        self.assertEqual((lv["sufficient"], lv["missing"], lv["forbiddenPresent"]), (True, [], []))
        self.assertEqual(lv["beyondNeed"], ["OverrideListBehaviors"])

    def test_TE10_ordinary_users_no_direct_access(self):
        cur = [pp.Assignment(OWNERS, "Owners", ("Full Control",)), pp.Assignment(5, "Members", ("Edit",)),
               pp.Assignment(4, "Visitors", ("Read",)), pp.Assignment(ADMIN, "admin", ("Full Control",))]
        p = rl.permission_plan(E, 1, False, cur, owners_id=OWNERS, admin_id=ADMIN)
        _, after = pp.simulate(False, cur, p["ops"], admin_id=ADMIN)
        self.assertEqual({a.principal_id for a in after}, {OWNERS, ADMIN})
        self.assertEqual(pp.requests(E, p["ops"])[0][1],
                         "/_api/web/lists/getbytitle('TimesheetEntries')/breakroleinheritance(copyRoleAssignments=false,clearSubscopes=true)")

    def test_TE11_second_provisioning_run_is_noop(self):
        s = FakeSite(site(with_projects=True))
        ops = rl.schema_plan(E, s.actual, ALLOWED, ALLOWED)
        sr.apply({"lists": [rl.target(E)]}, s.actual, s, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertTrue(ops)
        self.assertEqual(rl.schema_plan(E, s.actual, ALLOWED, ALLOWED), [])

    def test_TE12_incompatible_drift_blocks(self):
        s = FakeSite(site(with_projects=True))
        sr.apply({"lists": [rl.target(E)]}, s.actual, s, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        for name, key, val in (("WorkDate", "dateOnly", False), ("OwnerUpn", "type", "Note"), ("Project", "lookupList", "Phases")):
            drift = copy.deepcopy(s.actual)
            lst = next(x for x in drift["lists"] if x["title"] == E)
            next(f for f in lst["fields"] if f["internalName"] == name)[key] = val
            with self.assertRaises(sr.SiteGuardError, msg=name):
                rl.schema_plan(E, drift, ALLOWED, ALLOWED)

    def test_TE13_lookups_and_internal_names_match_the_save_flow(self):
        import test_r1_save_flow as rs
        _, _, writes, _ = rs.run_flow(rs.ME, rs.req(), rs.Store(rs.ITEMS), rs.SCOPING_OFF)
        body = {k: v for k, v in writes[0][2].items() if k != "__metadata"}
        f = created()
        for k in body:
            self.assertIn(lookup_col(k, f), f, k)
        self.assertEqual({n: x["lookupList"] for n, x in f.items() if x["type"] == "Lookup"},
                         {"Employee": "Employees", "Shift": "Shifts", "HourType": "HourTypes", "Project": "Projects", "Phase": "Phases",
                          "WorkType": "WorkTypes"})
        self.assertNotIn("ProjectPhases", json.dumps(f), "the (Project, Phase) pair is validated by the flow, not a lookup")
        for n in f:
            self.assertRegex(n, r"^[A-Za-z][A-Za-z0-9]*$")
        required = {n for n, x in f.items() if x["required"]}
        self.assertEqual(required - {lookup_col(k, f) for k in body}, set(), "every required column is written on create")

    def test_TE14_workdate_date_only(self):
        f = fields()["WorkDate"]
        self.assertEqual((f["type"], f["dateOnly"]), ("DateTime", True))
        self.assertIn('Format="DateOnly"', sr.field_schema_xml(f))
        import test_r1_save_flow as rs
        _, _, writes, _ = rs.run_flow(rs.ME, rs.req(), rs.Store(rs.ITEMS), rs.SCOPING_OFF)
        self.assertRegex(writes[0][2]["WorkDate"], r"^\d{4}-\d{2}-\d{2}$")  # JSON item write, proven by POC P4
        self.assertNotIn("ValidateUpdate", json.dumps(writes))

    def test_TE15_wrong_target_refused(self):
        for url in (MAIN, ALLOWED + "x"):
            with self.assertRaises(sr.SiteGuardError):
                rl.schema_plan(E, site(True), url, ALLOWED)

    def test_TE16_service_grant_gated_by_d3(self):
        cur = [pp.Assignment(OWNERS, "Owners", ("Full Control",)), pp.Assignment(ADMIN, "admin", ("Full Control",))]
        self.assertEqual(rl.permission_plan(E, 2, True, cur, owners_id=OWNERS, admin_id=ADMIN)["ops"], [])
        p = rl.permission_plan(E, 2, True, cur, owners_id=OWNERS, admin_id=ADMIN, service={"principal_id": SVC, "approval": "D-3 record"})
        self.assertEqual(p["ops"], [("add", {"principal_id": SVC, "role": "TS Service", "gate": "D-3"})])

    def test_TE17_schema_phase_needs_no_service_identity_but_needs_projects(self):
        with self.assertRaises(rl.IncompleteList):
            rl.schema_plan(E, site(with_projects=False), ALLOWED, ALLOWED)
        ok, b = rl.phase1_ready(E, {"lists": set(MASTERS)})
        self.assertFalse(ok)
        self.assertEqual(sorted(c for c, _ in b), ["LOOKUP_TARGET_MISSING", "S04.6", "S05.4"])
        self.assertFalse(any("D-3" == c for c, _ in b), "no service identity in Phase 1")
        self.assertTrue(rl.phase1_ready(E, {"lists": set(MASTERS) | {"Projects"}, "S04.6": "DONE", "S05.4": "DONE"})[0])
        self.assertEqual(rl.phase1_ready(rl.AUDITLOG, {"lists": set()}), (True, []))

    def test_TE18_deleted_is_a_status_not_a_physical_delete(self):
        import r1_flows
        blob = json.dumps([r1_flows.build(n) for n in r1_flows.TEMPLATES])
        self.assertNotIn("recycle", blob)
        self.assertNotIn('"DELETE"', blob)
        self.assertIn("Deleted", fields()["EntryStatus"]["choices"])
        self.assertNotIn("DeleteListItems", rl.TS_SERVICE_RIGHTS)

    def test_TE19_rest_requests_and_second_run(self):
        reqs = rl.rest_requests(E, site(True), ALLOWED, ALLOWED)
        self.assertEqual(reqs[0], ("POST", "/_api/web/lists"))
        self.assertEqual(sum(1 for m, _ in reqs if m == "GET"), 6, "one lookup-list id per lookup column")
        s = FakeSite(site(True))
        sr.apply({"lists": [rl.target(E)]}, s.actual, s, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual(rl.rest_requests(E, s.actual, ALLOWED, ALLOWED), [])

    def test_TE20_migration_status_mapping(self):
        self.assertEqual([rl.migrate_status(v) for v in ("Lock", "", None)], ["Approved", "Draft", "Draft"])
        for v in ("lock", "Deleted", "Rejected", "1"):
            with self.assertRaises(rl.UnmappedLegacyValue):
                rl.migrate_status(v)

    @unittest.skipUnless(os.environ.get("TS_TARGET_SCHEMA"), "set TS_TARGET_SCHEMA to reconcile with the local target")
    def test_TE21_reconciles_with_the_target_schema(self):
        t = json.load(open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8"))
        tl = {f["internalName"]: f for f in next(x for x in t["lists"] if x["title"] == E)["fields"]}
        self.assertEqual(list(tl), list(fields()))
        for n, f in tl.items():
            m = fields()[n]
            self.assertEqual((f["type"], f["required"], f.get("dateOnly"), f.get("lookupList"), f.get("choices"), bool(f.get("gate"))),
                             (m["type"], m["required"], m.get("dateOnly"), m.get("lookupList"), m.get("choices"), bool(m.get("gate"))), n)
        self.assertEqual(sorted(n for n in tl if bool(tl[n]["indexed"]) != bool(fields()[n]["indexed"])), [],
                         "target schema carries the owner-approved 8 indexes (9 -> 8 superseded 2026-10-07)")

    def test_TE22_owner_approved_eight_indexes_entry_status_revisit_after_p5(self):
        self.assertEqual(sorted(n for n, x in fields().items() if x["indexed"]), sorted(rl.APPROVED_INDEXES[E]))
        self.assertEqual(len(rl.APPROVED_INDEXES[E]), 8)
        self.assertFalse(fields()["EntryStatus"]["indexed"])
        self.assertEqual(rl.INDEX_DECISIONS[E]["EntryStatus"][0], rl.NOT_REQUIRED)
        self.assertIn("revisit after P5", rl.INDEX_DECISIONS[E]["EntryStatus"][3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
