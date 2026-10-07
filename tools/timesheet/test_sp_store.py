"""SharePoint data-path adapter tests SP01-SP10 (offline; synthetic fake transport; no tenant data).

These run the R1 reference operations (entries.save_entry / read_own) against a fake SharePoint REST endpoint that keeps
ETags, stores date-only values as local midnight in UTC and answers 412 on a stale If-Match."""
import os
import re
import sys
import unittest
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config")):
    sys.path.insert(0, p)
import business_dates as bd  # noqa: E402
import entries as E  # noqa: E402
import sp_store as sps  # noqa: E402
from test_entries import guard, settings  # noqa: E402

TZ = "Asia/Ho_Chi_Minh"
ME, OTHER = "amy@tenant-a.invalid", "bob@tenant-a.invalid"


class FakeSP:
    """Minimal SharePoint list REST for TimesheetEntries + lookup lists (site-relative paths)."""

    def __init__(self):
        self.items, self.next = {}, 1
        self.lists = {"Projects": [{"Id": 1, "ProjectCode": "P1", "Status": "Active"}],
                      "Phases": [{"Id": 1, "PhaseCode": "PH1", "IsActive": True}, {"Id": 2, "PhaseCode": "PH2", "IsActive": True}],
                      "WorkTypes": [{"Id": 1, "WorkTypeCode": "W1", "IsActive": True}],
                      "Shifts": [{"Id": 1, "ShiftCode": "S", "IsActive": True}], "HourTypes": [{"Id": 1, "HourTypeCode": "IT"}],
                      "ProjectPhases": [{"Id": 1, "ProjectId": 1, "PhaseId": 1, "IsActive": True}],
                      "Employees": [{"Id": 7, "LegacyId": "E-7", "IsActive": True, "AccountUpn": ME, "DisciplineId": 3,
                                     "Discipline": {"DisciplineCode": "D1"}}]}
        self.log = []

    def _row(self, i):
        f, v = self.items[i]
        return dict(f, Id=i, **{"odata.etag": '"%d"' % v})

    def _match(self, f, flt):
        for c in flt.split(" and "):
            m = re.match(r"(\w+) (eq|ne|ge|lt|gt) (?:'(.*)'|datetime'(.*)'|(\d+))$", c)
            k, op, s, d, n = m.groups()
            v = f.get(k) if k != "Id" else f["_id"]
            want = s if s is not None else d if d is not None else int(n)
            if not {"eq": v == want, "ne": v != want, "ge": v is not None and v >= want, "lt": v is not None and v < want,
                    "gt": v is not None and v > want}[op]:
                return False
        return True

    def __call__(self, method, path, body, headers):
        path = unquote(path)
        self.log.append((method, headers.get("X-HTTP-Method", method), path))
        m = re.match(r"/_api/web/lists/getbytitle\('(\w+)'\)/items(?:\((\d+)\))?(?:\?(.*))?$", path)
        lst, iid, qs = m.group(1), m.group(2), dict(x.split("=", 1) for x in (m.group(3) or "").split("&") if x)
        if lst != "TimesheetEntries":
            rows = self.lists[lst]
            if "$filter" in qs:
                rows = [r for r in rows if self._match(r, qs["$filter"])]
            return 200, {"value": rows}, None
        if method == "POST" and iid is None:
            f = dict(body)
            if isinstance(f.get("WorkDate"), str) and len(f["WorkDate"]) == 10:
                f["WorkDate"] = bd.local_midnight_utc(f["WorkDate"], TZ)  # date-only stored as local midnight in UTC
            i, self.next = self.next, self.next + 1
            self.items[i] = (f, 1)
            return 201, {"Id": i}, None
        if iid is not None:
            i = int(iid)
            if i not in self.items:
                return 404, None, None
            if method == "GET":
                return 200, self._row(i), None
            if headers.get("X-HTTP-Method") == "MERGE":
                f, v = self.items[i]
                if headers.get("IF-MATCH") not in ("*", '"%d"' % v):
                    return 412, {"odata.error": {"code": "-1"}}, None
                upd = dict(body)
                if isinstance(upd.get("WorkDate"), str) and len(upd["WorkDate"]) == 10:
                    upd["WorkDate"] = bd.local_midnight_utc(upd["WorkDate"], TZ)
                self.items[i] = (dict(f, **upd), v + 1)
                return 204, None, '"%d"' % (v + 1)
        rows = [dict(self._row(i), _id=i) for i in sorted(self.items)]
        rows = [r for r in rows if self._match(r, qs["$filter"])][: int(qs.get("$top", 5000))]
        return 200, {"value": [{k: v for k, v in r.items() if k != "_id"} for r in rows]}, None


def req(**kw):
    r = {"ItemId": 0, "WorkDate": "2026-10-05", "ProjectCode": "P1", "PhaseCode": "PH1", "WorkTypeCode": "W1", "ShiftCode": "S",
         "HourTypeCode": "IT", "Hours": 3, "Remark": "x"}
    r.update(kw)
    return r


class TestSpStore(unittest.TestCase):
    def setUp(self):
        self.sp = FakeSP()
        self.store = sps.SharePointStore(self.sp, "TimesheetEntries", TZ, stamp={"MigrationBatch": "DEMO_ONLY"})
        res, self.caller = sps.resolve_caller(self.sp, ME.upper(), ["tenant-a.invalid"])
        self.masters = sps.load_masters(self.sp)

    def save(self, r):
        return E.save_entry(guard(), self.caller, r, self.masters, settings(), self.store, correlation_id="c")

    def test_SP01_caller_resolved_once_with_discipline_projection(self):
        self.assertEqual((self.caller.upn, self.caller.employee_item_id, self.caller.discipline_code), (ME, 7, "D1"))
        self.sp.lists["Employees"].append(dict(self.sp.lists["Employees"][0], Id=8))
        res, c = sps.resolve_caller(self.sp, ME, ["tenant-a.invalid"])
        self.assertEqual((res.code, c), ("DUPLICATE_MAPPING", None))

    def test_SP02_masters_by_code_and_project_phase_pairs(self):
        self.assertEqual(self.masters.projects["P1"], {"id": 1, "status": "Active"})
        self.assertEqual(set(self.masters.project_phases), {("P1", "PH1")})

    def test_SP03_create_stamps_marker_owner_from_caller_and_reads_etag(self):
        r = self.save(req(OwnerUpn=OTHER, EntryStatus="Approved"))
        self.assertEqual((r.ok, r.etag), (True, '"1"'))
        f, _ = self.store.get(r.itemId)
        self.assertEqual((f["OwnerUpn"], f["EntryStatus"], f["MigrationBatch"]), (ME, "Draft", "DEMO_ONLY"))
        self.assertIn("OwnerUpn", r.ignoredInputs)

    def test_SP04_stamp_cannot_set_owner_or_status(self):
        with self.assertRaises(ValueError):
            sps.SharePointStore(self.sp, "TimesheetEntries", TZ, stamp={"OwnerUpn": OTHER})

    def test_SP05_workdate_is_local_midnight_and_reads_back_as_business_date(self):
        r = self.save(req())
        f, _ = self.store.get(r.itemId)
        self.assertEqual((f["WorkDateUtc"], f["WorkDate"]), ("2026-10-04T17:00:00Z", "2026-10-05"))

    def test_SP06_read_own_bounded_excludes_foreign_and_day_outside(self):
        mine = self.save(req()).itemId
        self.sp.items[99] = ({"OwnerUpn": OTHER, "WorkDate": "2026-10-04T17:00:00Z", "EntryStatus": "Draft", "Hours": 10}, 1)
        ro = E.read_own(guard(), self.caller, {"FromDate": "2026-09-26", "ToDate": "2026-10-25"}, self.store, correlation_id="r", business_timezone=TZ)
        self.assertEqual(([x["id"] for x in ro["rows"]], ro["rows"][0]["workDate"]), ([mine], "2026-10-05"))
        ro = E.read_own(guard(), self.caller, {"FromDate": "2026-10-06", "ToDate": "2026-10-06"}, self.store, correlation_id="r", business_timezone=TZ)
        self.assertEqual(ro["rows"], [])

    def test_SP07_same_day_sum_ignores_other_owner(self):
        self.sp.items[99] = ({"OwnerUpn": OTHER, "WorkDate": "2026-10-04T17:00:00Z", "EntryStatus": "Draft", "Hours": 10}, 1)
        self.assertNotIn(E.WARN_HOURS_DAY, self.save(req(Hours=3)).warnings)
        self.assertIn(E.WARN_HOURS_DAY, self.save(req(Hours=10)).warnings)

    def test_SP08_edit_with_current_etag_changes_etag(self):
        a = self.save(req())
        b = self.save(req(ItemId=a.itemId, ETag=a.etag, Hours=5))
        self.assertEqual((b.ok, b.etag != a.etag, self.store.get(a.itemId)[0]["Hours"]), (True, True, 5))

    def test_SP09_stale_etag_is_conflict_at_contract_and_412_at_sharepoint(self):
        a = self.save(req())
        self.save(req(ItemId=a.itemId, ETag=a.etag, Hours=5))
        self.assertEqual(self.save(req(ItemId=a.itemId, ETag=a.etag, Hours=6)).code, E.CONFLICT)
        with self.assertRaises(E.ConflictError):
            self.store.update(a.itemId, {"Hours": 7}, a.etag)
        self.assertEqual(self.store.get(a.itemId)[0]["Hours"], 5)

    def test_SP10_unreadable_reference_list_fails_closed(self):
        def broken(m, p, b, h):
            return (403, None, None) if "ProjectPhases" in p else self.sp(m, p, b, h)
        with self.assertRaises(sps.TransportError):
            sps.load_masters(broken)


if __name__ == "__main__":
    unittest.main()
