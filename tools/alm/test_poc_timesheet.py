"""POC-TIMESHEET-01 evaluator tests PTT01-PTT12 (offline; synthetic evidence)."""
import copy
import os
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import poc_timesheet as pt  # noqa: E402

SITE = "https://tenant-a.invalid/sites/app-staging"
COLS = {c: {"type": "Text", "required": True, "indexed": c in pt.APPROVED_INDEXES} for c in sorted(pt.APPROVED_INDEXES | {"Hours", "EntryStatus"})}
SCH = {"exists": True, "blocked": 0, "secondPlanOps": 0, "missingRequired": []}
DEMO = lambda n, p: [{"legacyId": "DEMO-%s-%d" % (p, i), "marker": "DEMO_ONLY"} for i in range(n)]  # noqa: E731
GOOD = {
    "expectedSite": SITE, "site": SITE,
    "mutations": [{"kind": k, "target": SITE} for k in ("SCHEMA", "PERMISSION", "DEMO_ROW", "ENTRY_CREATE", "ENTRY_EDIT", "FIXTURE_ROW", "FIXTURE_CLEANUP")],
    "identityRows": [{"id": 9, "active": True}], "identityRefs": {k: {"active": True} for k in ("Department", "Discipline", "Position")},
    "schema": dict({l: SCH for l in pt.REF}, Projects=SCH, TimesheetEntries=SCH, ProjectPhases=dict(SCH, lookups={"Project": "Projects", "Phase": "Phases"})),
    "demoRows": dict({l: DEMO(n, l) for l, n in pt.REF.items()}, Projects=DEMO(1, "P"), ProjectPhases=DEMO(2, "PP")), "demoValidate": [],
    "projectRelations": [{"projectIsDemo": True, "phaseIsDemo": True}] * 2,
    "entriesSchema": {"columns": COLS, "expectedColumns": copy.deepcopy(COLS), "entryStatusChoices": ["Draft", "Approved", "Deleted"], "entryStatusDefault": "Draft"},
    "entriesPermissions": {"unique": True, "ra": {"owners": ["Full Control"], "siteAdmin": ["Full Control"], "service": ["TS Service"]}, "eff": {"user": []}},
    "serviceReads": {"Phases": ["ViewListItems"], "Disciplines": ["ViewListItems"]}, "serviceReadRequired": ["Phases", "Disciplines"],
    "serviceReadNotRequired": ["AppSettings"], "guardProjectionStatus": 200,
    "create": {"ok": True, "code": "OK", "path": "service", "ignoredInputs": ["ActorUpn", "EmployeeId", "EntryStatus", "OwnerUpn"]}, "entriesCreated": 2,
    "rowA": {"id": 2, "ownerIsCaller": True, "employeeIsCaller": True, "status": "Draft", "marker": "DEMO_ONLY",
             "legacyId": str(uuid.UUID(int=1))},
    "rowB": {"id": 1},
    "workDate": {"stored": "2026-10-04T17:00:00Z", "expectedUtc": "2026-10-04T17:00:00Z", "business": "2026-10-05", "requested": "2026-10-05",
                 "sameDay": [2], "dayBefore": [], "dayAfter": []},
    "readOwn": {"ok": True, "range": ["2026-09-26", "2026-10-25"], "ids": [2], "ordered": True, "allOwnedByCaller": True},
    "foreignInRange": [1], "foreignRequest": {"code": "FORBIDDEN"},
    "userProbes": {"READ": 404, "CREATE": 404, "EDIT": 403, "DELETE": 404}, "userEntryRights": [],
    "edit": {"ok": True, "hoursSent": 12.5, "hoursReadback": 12.5, "ownerUnchanged": True, "status": "Draft", "etagBefore": '"1"', "etagAfter": '"2"'},
    "stale": {"sharepointStatus": 412, "contractCode": "CONFLICT", "unchanged": True},
    "serviceEntryRights": ["ViewListItems", "AddListItems", "EditListItems"], "serviceDeleteProbe": 403,
    "master": {"rowsUnchanged": True, "fieldsUnchanged": True, "permissionDeltas": ["Disciplines: service Read"]},
    "approvedDeltas": ["Disciplines: service Read"], "preExistingRowsChanged": 0,
    "mainMutations": 0, "productionMutations": 0, "powerPlatformMutations": 0, "entraMutations": 0,
    "pocMasterPass": True, "stagingUxPass": True,
    "warnings": {"WARN_HOURS_ENTRY": {"raised": True, "writeSucceeded": True}},
}


def ev(**kw):
    e = copy.deepcopy(GOOD)
    for k, v in kw.items():
        e[k] = v
    return e


class TestPocTimesheet(unittest.TestCase):
    def test_PTT01_good_evidence_passes_30(self):
        r = pt.evaluate(ev())
        self.assertTrue(r["pass"], [k for k, v in r["tests"].items() if v[0] != "PASS"])
        self.assertEqual(r["score"], "30/30")
        self.assertTrue(all(v == "NOT PROVEN" for k, v in r["scope"].items() if k != "POC-TIMESHEET-01"))

    def test_PTT02_wrong_mutation_target_fails(self):
        r = pt.evaluate(ev(mutations=GOOD["mutations"] + [{"kind": "SCHEMA", "target": "https://tenant-a.invalid/"}]))
        self.assertEqual(r["tests"]["PT01"][0], "FAIL")

    def test_PTT03_duplicate_or_inactive_identity_fails(self):
        self.assertEqual(pt.evaluate(ev(identityRows=[{"active": True}, {"active": True}]))["tests"]["PT02"][0], "FAIL")
        self.assertEqual(pt.evaluate(ev(identityRows=[{"active": False}]))["tests"]["PT02"][0], "FAIL")

    def test_PTT04_forbidden_gated_column_or_extra_index_fails(self):
        cols = dict(COLS, RequestKey={"type": "Text", "required": False, "indexed": False})
        self.assertEqual(pt.evaluate(ev(entriesSchema=dict(GOOD["entriesSchema"], columns=cols, expectedColumns=cols)))["tests"]["PT08"][0], "FAIL")
        cols = dict(COLS, EntryStatus={"type": "Choice", "required": True, "indexed": True})
        self.assertEqual(pt.evaluate(ev(entriesSchema=dict(GOOD["entriesSchema"], columns=cols, expectedColumns=cols)))["tests"]["PT09"][0], "FAIL")

    def test_PTT05_human_access_to_entries_fails(self):
        p = dict(GOOD["entriesPermissions"], ra=dict(GOOD["entriesPermissions"]["ra"], employees=["Read"]))
        self.assertEqual(pt.evaluate(ev(entriesPermissions=p))["tests"]["PT10"][0], "FAIL")
        self.assertEqual(pt.evaluate(ev(userProbes=dict(GOOD["userProbes"], READ=200)))["tests"]["PT17"][0], "FAIL")

    def test_PTT06_overbroad_service_read_fails(self):
        r = pt.evaluate(ev(serviceReads=dict(GOOD["serviceReads"], AppSettings=["ViewListItems"])))
        self.assertEqual(r["tests"]["PT11"][0], "FAIL")
        r = pt.evaluate(ev(serviceReads=dict(GOOD["serviceReads"], Phases=["ViewListItems", "EditListItems"])))
        self.assertEqual(r["tests"]["PT11"][0], "FAIL")

    def test_PTT07_forged_owner_not_ignored_fails(self):
        r = pt.evaluate(ev(create=dict(GOOD["create"], ignoredInputs=["EntryStatus"]), rowA=dict(GOOD["rowA"], ownerIsCaller=False)))
        self.assertEqual(r["tests"]["PT13"][0], "FAIL")

    def test_PTT08_utc_truncation_or_open_range_fails(self):
        self.assertEqual(pt.evaluate(ev(workDate=dict(GOOD["workDate"], business="2026-10-04")))["tests"]["PT14"][0], "FAIL")
        self.assertEqual(pt.evaluate(ev(readOwn=dict(GOOD["readOwn"], range=["", ""])))["tests"]["PT15"][0], "FAIL")

    def test_PTT09_foreign_leak_or_unproven_isolation_fails(self):
        self.assertEqual(pt.evaluate(ev(readOwn=dict(GOOD["readOwn"], ids=[1, 2])))["tests"]["PT16"][0], "FAIL")
        self.assertEqual(pt.evaluate(ev(foreignInRange=[]))["tests"]["PT16"][0], "FAIL", "absent foreign row proves nothing")

    def test_PTT10_stale_overwrite_or_unchanged_etag_fails(self):
        self.assertEqual(pt.evaluate(ev(stale=dict(GOOD["stale"], sharepointStatus=204, unchanged=False)))["tests"]["PT20"][0], "FAIL")
        self.assertEqual(pt.evaluate(ev(edit=dict(GOOD["edit"], etagAfter='"1"')))["tests"]["PT19"][0], "FAIL")

    def test_PTT11_service_delete_or_manage_fails(self):
        r = pt.evaluate(ev(serviceEntryRights=GOOD["serviceEntryRights"] + ["DeleteListItems"], serviceDeleteProbe=200))
        self.assertEqual((r["tests"]["PT21"][0], r["tests"]["PT22"][0]), ("FAIL", "FAIL"))
        self.assertEqual(pt.evaluate(ev(serviceEntryRights=GOOD["serviceEntryRights"] + ["ManagePermissions"]))["tests"]["PT22"][0], "FAIL")

    def test_PTT12_unapproved_master_delta_and_warnings_reporting(self):
        r = pt.evaluate(ev(master=dict(GOOD["master"], permissionDeltas=["Positions: service Read"])))
        self.assertEqual(r["tests"]["PT23"][0], "FAIL")
        w = pt.evaluate(ev())["warnings"]
        self.assertEqual(w, {"ENTRY > 4 HOURS": "PASS", "DAY > 12 HOURS": "NOT RUN"}, "never a faked warning PASS")


if __name__ == "__main__":
    unittest.main()
