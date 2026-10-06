"""R1 timesheet reference tests E01-E22 (offline; synthetic data; run: python -m unittest test_entries).

These are OFFLINE tests of the reference logic. They are not the R1 live tests R1-01..R1-15, which stay NOT RUN.
"""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config")):
    sys.path.insert(0, p)
import app_settings as cfg  # noqa: E402
import entries as E  # noqa: E402
from guard import ALLOW, DENY, R_ALLOW, ROLE_NOT_ALLOWED, GuardResult  # noqa: E402

ME, OTHER = "amy@tenant-a.invalid", "bob@tenant-a.invalid"
REG = {"settings": [
    {"key": "PayPeriodStartDay", "type": "int", "value": "26", "resolution": "RESOLVED"},
    {"key": "MaxHoursPerEntryWarn", "type": "decimal", "value": "4", "resolution": "RESOLVED"},
    {"key": "MaxHoursPerDayWarn", "type": "decimal", "value": "12", "resolution": "RESOLVED"},
    {"key": "ProjectAssignmentScoping", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "BLOCKED"}]}
SCOPING_OFF = [{"Title": "ProjectAssignmentScoping", "Value": "Off"}]


def settings(rows=SCOPING_OFF):
    return cfg.resolve(REG, site_rows=rows)


def guard(upn=ME, ok=True):
    return GuardResult(upn, 7, "E-7", True, ["EMP"], "TS.EditOwnDraft", "self", "self",
                       ALLOW if ok else DENY, R_ALLOW if ok else ROLE_NOT_ALLOWED, "run-1")


CALLER = E.Caller(ME, 7, "E-7", "D1")
MASTERS = E.Masters(
    projects={"P1": {"id": 11, "status": "Active"}, "P2": {"id": 12, "status": "Paused"}, "P3": {"id": 13, "status": "Active"}},
    project_phases={("P1", "PH1"): {"id": 101, "active": True}, ("P1", "PH2"): {"id": 102, "active": False},
                    ("P3", "PH1"): {"id": 103, "active": True}},
    phases={"PH1": {"id": 21, "active": True}, "PH2": {"id": 22, "active": True}, "PH9": {"id": 29, "active": False}},
    work_types={"W1": {"id": 31, "active": True}, "W0": {"id": 30, "active": False}},
    shifts={"S": {"id": 41, "active": True}, "C": {"id": 42, "active": True}},
    hour_types={"IT": {"id": 51}, "OT1": {"id": 52}},
    assignments=["P3"])


def req(**kw):
    r = {"ItemId": 0, "WorkDate": "2026-10-06", "ProjectCode": "P1", "PhaseCode": "PH1", "WorkTypeCode": "W1",
         "ShiftCode": "S", "HourTypeCode": "IT", "Hours": 4, "Remark": "x"}
    r.update(kw)
    return r


class FakeStore:
    def __init__(self):
        self.items, self.next_id, self.writes = {}, 1, []

    def get(self, i):
        return (dict(self.items[i][0]), self.items[i][1]) if i in self.items else None

    def create(self, f):
        i = self.next_id
        self.next_id += 1
        self.items[i] = (dict(f), "e%d-1" % i)
        self.writes.append(("create", i))
        return i, self.items[i][1]

    def update(self, i, f, if_match):
        cur, etag = self.items[i]
        self.last_update = dict(f)
        if etag != if_match:
            raise E.ConflictError()
        n = int(etag.split("-")[1]) + 1
        self.items[i] = (dict(cur, **f), "e%d-%d" % (i, n))
        self.writes.append(("update", i))
        return self.items[i][1]

    def find(self, **eq):
        return [(i, dict(f), e) for i, (f, e) in sorted(self.items.items()) if all(f.get(k) == v for k, v in eq.items())]

    def query(self, flt):
        rows = [(i, dict(f), e) for i, (f, e) in sorted(self.items.items())
                if f.get("OwnerUpn") == flt.owner_upn and f.get("EntryStatus") != E.DELETED and i > flt.after_id
                and (not flt.from_date or f["WorkDate"] >= flt.from_date) and (not flt.to_date or f["WorkDate"] <= flt.to_date)]
        return rows[:flt.top]


def save(store, r, g=None, s=None, **kw):
    return E.save_entry(g or guard(), CALLER, r, MASTERS, s or settings(), store, correlation_id="run-1", **kw)


class Save(unittest.TestCase):
    def test_E01_create_own_draft_sets_trusted_fields(self):
        st = FakeStore()
        r = save(st, req(OwnerUpn=OTHER, ActorUpn=OTHER, CallerUpn=OTHER))
        self.assertEqual((r.ok, r.code, r.itemId), (True, E.OK, 1))
        f = st.items[1][0]
        self.assertEqual((f["OwnerUpn"], f["ActorUpn"], f["IsOnBehalf"], f["EntryStatus"], f["LegacyOrigin"]), (ME, ME, False, "Draft", "New"))
        self.assertEqual((f["EmployeeItemId"], f["DisciplineCode"], f["PeriodKey"], f["CorrelationId"]), (7, "D1", "2026-10", "run-1"))
        self.assertEqual(r.ignoredInputs, ["ActorUpn", "CallerUpn", "OwnerUpn"])
        self.assertEqual(r.audit[0]["Action"], "Create")

    def test_E02_guard_denial_passes_through_without_store_access(self):
        st = FakeStore()
        r = save(st, req(), g=guard(ok=False))
        self.assertEqual((r.ok, r.code, st.writes), (False, ROLE_NOT_ALLOWED, []))
        r = E.save_entry(guard(upn=OTHER), CALLER, req(), MASTERS, settings(), st, correlation_id="c")
        self.assertEqual((r.code, st.writes), (E.FORBIDDEN, []), "caller must be the guard's identity")

    def test_E03_unresolved_or_invalid_setting_fails_closed(self):
        st = FakeStore()
        self.assertEqual(save(st, req(), s=settings([])).code, E.CONFIG_UNRESOLVED)
        self.assertEqual(save(st, req(), s=settings([{"Title": "ProjectAssignmentScoping", "Value": "Maybe"}])).code, E.CONFIG_INVALID)
        self.assertEqual(st.writes, [])

    def test_E04_edit_own_draft_with_etag(self):
        st = FakeStore()
        c = save(st, req())
        r = save(st, req(ItemId=c.itemId, ETag=c.etag, Hours=3, OwnerUpn=OTHER))
        self.assertEqual((r.ok, r.code), (True, E.OK))
        self.assertNotEqual(r.etag, c.etag)
        f = st.items[1][0]
        self.assertEqual((f["Hours"], f["OwnerUpn"], f["LegacyOrigin"]), (3.0, ME, "New"))
        self.assertFalse({"OwnerUpn", "LegacyId", "LegacyOrigin", "EntryStatus"} & set(st.last_update), "an edit never rewrites them")

    def test_E05_stale_etag_conflict_no_lost_update(self):
        st = FakeStore()
        c = save(st, req())
        save(st, req(ItemId=1, ETag=c.etag, Hours=2))
        r = save(st, req(ItemId=1, ETag=c.etag, Hours=1))
        self.assertEqual(r.code, E.CONFLICT)
        self.assertEqual(st.items[1][0]["Hours"], 2.0)

    def test_E06_edit_checks_in_order(self):
        st = FakeStore()
        st.items[5] = ({"OwnerUpn": OTHER, "EntryStatus": "Draft"}, "e5-1")
        st.items[6] = ({"OwnerUpn": ME, "EntryStatus": "Approved"}, "e6-1")
        st.items[7] = ({"OwnerUpn": ME, "EntryStatus": "Deleted"}, "e7-1")
        self.assertEqual(save(st, req(ItemId=99)).code, E.NOT_FOUND)
        self.assertEqual(save(st, req(ItemId=5, ETag="e5-1")).code, E.FORBIDDEN)
        self.assertEqual(save(st, req(ItemId=6, ETag="e6-1")).code, E.LOCKED)
        self.assertEqual(save(st, req(ItemId=6, ETag="stale", Hours=0)).code, E.LOCKED, "lock before etag and validation")
        self.assertEqual(save(st, req(ItemId=7, ETag="e7-1")).code, E.NOT_FOUND, "soft-deleted rows are not editable")
        self.assertEqual(save(st, req(ItemId="x")).code, E.NOT_FOUND)
        self.assertEqual(st.writes, [])

    def test_E07_lookup_validation(self):
        st = FakeStore()
        for bad in ({"ProjectCode": "P2"}, {"ProjectCode": "PX"}, {"PhaseCode": "PH2"}, {"PhaseCode": "PH9"},
                    {"ProjectCode": "P3", "PhaseCode": "PH2"}, {"WorkTypeCode": "W0"}, {"WorkTypeCode": "W?"},
                    {"ShiftCode": None}, {"HourTypeCode": "OT9"}):
            self.assertEqual(save(st, req(**bad)).code, E.VALIDATION_LOOKUP, bad)
        self.assertEqual(st.writes, [])
        self.assertTrue(save(st, req(ProjectCode="p1", PhaseCode="ph1", ShiftCode="s")).ok, "codes are case-insensitive")

    def test_E08_hours_validation(self):
        st = FakeStore()
        for h in (0, -1, 24.25, "abc", "", None, True, "4,5"):
            self.assertEqual(save(st, req(Hours=h)).code, E.VALIDATION_HOURS, h)
        for h in (0.25, 24, "7.5"):
            self.assertTrue(save(st, req(Hours=h, WorkDate="2026-01-0%d" % (1 + len(st.items)))).ok, h)

    def test_E09_date_validation(self):
        st = FakeStore()
        for d in ("2026-02-30", "06/10/2026", "", None, "2026-10-06T00:00:00Z"):
            self.assertEqual(save(st, req(WorkDate=d)).code, E.VALIDATION_DATE, d)

    def test_E10_validation_order_lookup_then_hours_then_date(self):
        st = FakeStore()
        self.assertEqual(save(st, req(ProjectCode="PX", Hours=0, WorkDate="x")).code, E.VALIDATION_LOOKUP)
        self.assertEqual(save(st, req(Hours=0, WorkDate="x")).code, E.VALIDATION_HOURS)

    def test_E11_warnings_do_not_block(self):
        st = FakeStore()
        r = save(st, req(Hours=4.25))
        self.assertEqual((r.ok, r.warnings), (True, [E.WARN_HOURS_ENTRY]))
        save(st, req(Hours=4, ShiftCode="C"))
        r = save(st, req(Hours=4, HourTypeCode="OT1"))
        self.assertEqual(r.warnings, [E.WARN_HOURS_DAY])
        r = save(st, req(Hours=1))
        self.assertIn(E.WARN_DUPLICATE, r.warnings)
        self.assertTrue(r.ok)

    def test_E12_editing_a_row_does_not_count_itself(self):
        st = FakeStore()
        c = save(st, req(Hours=4))
        r = save(st, req(ItemId=c.itemId, ETag=c.etag, Hours=4))
        self.assertEqual(r.warnings, [])

    def test_E13_scoping_on_restricts_to_assigned_projects(self):
        st = FakeStore()
        on = settings([{"Title": "ProjectAssignmentScoping", "Value": "On"}])
        self.assertEqual(save(st, req(), s=on).code, E.VALIDATION_LOOKUP)
        self.assertTrue(save(st, req(ProjectCode="P3"), s=on).ok)

    def test_E14_period_key_boundaries(self):
        pk = lambda s: E.period_key(dt.date.fromisoformat(s), 26)  # noqa: E731
        self.assertEqual([pk(d) for d in ("2026-10-01", "2026-10-25", "2026-10-26", "2026-10-31", "2026-12-25", "2026-12-26", "2027-01-01")],
                         ["2026-10", "2026-10", "2026-11", "2026-11", "2026-12", "2027-01", "2027-01"])

    def test_E15_no_idempotency_duplicates_on_retry_but_warns(self):
        st = FakeStore()
        a, b = save(st, req()), save(st, req())
        self.assertEqual((a.itemId, b.itemId), (1, 2))
        self.assertIn(E.WARN_DUPLICATE, b.warnings)

    def test_E16_request_key_strategy_replays_same_create(self):
        st, k = FakeStore(), "0f0e0d0c-0b0a-4908-8706-050403020100"
        strat = E.RequestKeyIdempotency()
        a = save(st, req(RequestKey=k), idempotency=strat)
        b = save(st, req(RequestKey=k.upper()), idempotency=strat)
        self.assertEqual((a.code, b.code, b.itemId, len(st.items)), (E.OK, E.OK_REPLAY, a.itemId, 1))
        self.assertEqual(save(st, req(RequestKey=k, Hours=2), idempotency=strat).code, E.IDEMPOTENCY_KEY_REUSED)
        self.assertEqual(save(st, req(RequestKey="nope"), idempotency=strat).code, E.VALIDATION_REQUEST_KEY)
        self.assertEqual(len(st.items), 1)

    def test_E17_request_key_of_another_owner_is_not_revealed(self):
        st, k = FakeStore(), "0f0e0d0c-0b0a-4908-8706-050403020100"
        mine = FakeStore()
        save(mine, req(RequestKey=k), idempotency=E.RequestKeyIdempotency())
        st.items[9] = (dict(mine.items[1][0], OwnerUpn=OTHER), "e9-1")  # same key and identical payload, other owner
        r = save(st, req(RequestKey=k), idempotency=E.RequestKeyIdempotency())
        self.assertEqual((r.ok, r.code, r.itemId, r.etag), (False, E.IDEMPOTENCY_KEY_REUSED, 0, ""))


class Read(unittest.TestCase):
    def setUp(self):
        self.st = FakeStore()
        for i in range(1, 8):
            self.st.items[i] = ({"OwnerUpn": ME if i != 4 else OTHER, "WorkDate": "2026-10-%02d" % i,
                                 "EntryStatus": "Deleted" if i == 5 else "Draft", "Hours": 1}, "e%d-1" % i)

    def read(self, **r):
        return E.read_own(guard(), CALLER, r, self.st, correlation_id="run-2")

    def test_E18_own_rows_only_paged_without_deleted(self):
        p1 = self.read(PageSize=2, CallerUpn=OTHER)
        self.assertEqual(([x["id"] for x in p1["rows"]], p1["nextAfterId"], p1["ignoredInputs"]), ([1, 2], 2, ["CallerUpn"]))
        p2 = self.read(PageSize=2, AfterId=2)
        p3 = self.read(PageSize=2, AfterId=p2["nextAfterId"])
        self.assertEqual(([x["id"] for x in p2["rows"]], [x["id"] for x in p3["rows"]], p3["nextAfterId"]), ([3, 6], [7], 0))

    def test_E19_date_range_and_validation(self):
        self.assertEqual([x["id"] for x in self.read(FromDate="2026-10-02", ToDate="2026-10-03")["rows"]], [2, 3])
        for bad in ({"FromDate": "x"}, {"FromDate": "2026-10-05", "ToDate": "2026-10-01"}):
            self.assertEqual(self.read(**bad)["code"], E.VALIDATION_DATE)

    def test_E20_foreign_owner_request_refused(self):
        r = self.read(RequestedOwner=OTHER)
        self.assertEqual((r["ok"], r["code"], r["rows"]), (False, E.FORBIDDEN, []))
        self.assertTrue(self.read(RequestedOwner=ME.upper())["ok"])
        self.assertEqual(E.read_own(guard(ok=False), CALLER, {}, self.st, correlation_id="c")["code"], ROLE_NOT_ALLOWED)

    def test_E21_leak_check_returns_no_rows(self):
        class Leaky(FakeStore):
            def query(self, flt):
                return [(4, {"OwnerUpn": OTHER, "EntryStatus": "Draft"}, "e")]
        r = E.read_own(guard(), CALLER, {}, Leaky(), correlation_id="c")
        self.assertEqual((r["ok"], r["code"], r["rows"]), (False, E.ERROR_LEAK, []))

    def test_E22_page_size_clamped_and_filter_text(self):
        self.assertEqual(self.read(PageSize=10000)["pageSize"], 500)
        self.assertEqual(self.read(PageSize=0)["pageSize"], 1)
        f = E.ReadFilter("o'neil@tenant-a.invalid", "2026-10-01", None, 5, 50).odata()
        self.assertEqual(f, "OwnerUpn eq 'o''neil@tenant-a.invalid' and WorkDate ge '2026-10-01' and EntryStatus ne 'Deleted' and Id gt 5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
