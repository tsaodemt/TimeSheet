"""Business-date range tests RD01-RD15 + generated read-flow date clause G-RD (offline).

Model of SharePoint used here: a date-only WorkDate is stored as local midnight of the business time zone, expressed
as a UTC instant (documented observation: a 15/09 value reads back as ...-14T17:00:00Z at UTC+07). The read filter is
the half-open interval [local from 00:00, local to+1 00:00) in UTC. Run: python -m unittest test_date_range.
"""
import datetime as dt
import importlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PA = os.path.join(HERE, "..", "powerautomate")
for p in (HERE, PA, os.path.join(HERE, "..", "identity")):
    sys.path.insert(0, p)
import business_dates as bd  # noqa: E402
import entries as E  # noqa: E402
import wdl_sim  # noqa: E402
from guard import ALLOW, R_ALLOW, GuardResult  # noqa: E402

TZ = "Asia/Ho_Chi_Minh"
ME = "amy@tenant-a.invalid"
CALLER = E.Caller(ME, 7, "E-7", "D1")
GUARD = GuardResult(ME, 7, "E-7", True, ["EMP"], "TS.ReadOwn", "self", "self", ALLOW, R_ALLOW, "run-1")


def stored(business_date, tz=TZ):
    """What SharePoint stores for a date-only value: local midnight as a UTC instant."""
    return bd.local_midnight_utc(business_date, tz)


class SharePointLike:
    """Rows carry WorkDate as the stored UTC instant; the query applies the UTC bounds exactly like the $filter."""
    def __init__(self, dates, tz=TZ):
        self.rows = {i + 1: {"OwnerUpn": ME, "EntryStatus": "Draft", "WorkDate": stored(d, tz), "Business": d}
                     for i, d in enumerate(dates)}

    def query(self, flt):
        lo, hi = flt.utc_bounds()
        hits = [(i, dict(f), "e") for i, f in sorted(self.rows.items())
                if f["OwnerUpn"] == flt.owner_upn and f["EntryStatus"] != "Deleted" and i > flt.after_id
                and bd.in_range(f["WorkDate"], lo, hi)]
        return hits[:flt.top]


def read(store, **req):
    r = E.read_own(GUARD, CALLER, req, store, correlation_id="c", business_timezone=TZ)
    return r, [store.rows[x["id"]]["Business"] for x in r["rows"]]


def days(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(n)).isoformat() for n in range((d1 - d0).days + 1)]


class BusinessDateRange(unittest.TestCase):
    def test_RD01_single_business_date(self):
        self.assertEqual(bd.utc_range("2026-10-07", "2026-10-07", TZ), ("2026-10-06T17:00:00Z", "2026-10-07T17:00:00Z"))
        st = SharePointLike(["2026-10-06", "2026-10-07", "2026-10-08"])
        self.assertEqual(read(st, FromDate="2026-10-07", ToDate="2026-10-07")[1], ["2026-10-07"])

    def test_RD02_first_instant_of_the_date_is_included(self):
        lo, hi = bd.utc_range("2026-10-07", "2026-10-07", TZ)
        self.assertTrue(bd.in_range("2026-10-06T17:00:00Z", lo, hi))

    def test_RD03_instant_immediately_before_is_excluded(self):
        lo, hi = bd.utc_range("2026-10-07", "2026-10-07", TZ)
        self.assertFalse(bd.in_range("2026-10-06T16:59:59Z", lo, hi))

    def test_RD04_last_instant_before_next_local_midnight_is_included(self):
        lo, hi = bd.utc_range("2026-10-07", "2026-10-07", TZ)
        self.assertTrue(bd.in_range("2026-10-07T16:59:59Z", lo, hi))

    def test_RD05_next_local_midnight_is_excluded(self):
        lo, hi = bd.utc_range("2026-10-07", "2026-10-07", TZ)
        self.assertFalse(bd.in_range("2026-10-07T17:00:00Z", lo, hi))
        self.assertNotIn("23:59:59", "".join(bd.utc_range("2026-10-07", "2026-10-07", TZ)))

    def test_RD06_multi_day_range(self):
        st = SharePointLike(days("2026-09-28", "2026-10-10"))
        self.assertEqual(read(st, FromDate="2026-10-01", ToDate="2026-10-07")[1], days("2026-10-01", "2026-10-07"))

    def test_RD07_month_boundary(self):
        st = SharePointLike(days("2026-10-29", "2026-11-03"))
        self.assertEqual(read(st, FromDate="2026-10-31", ToDate="2026-11-01")[1], ["2026-10-31", "2026-11-01"])
        self.assertEqual(bd.utc_range("2026-10-31", "2026-10-31", TZ), ("2026-10-30T17:00:00Z", "2026-10-31T17:00:00Z"))

    def test_RD08_year_boundary(self):
        st = SharePointLike(days("2026-12-29", "2027-01-03"))
        self.assertEqual(read(st, FromDate="2026-12-31", ToDate="2027-01-01")[1], ["2026-12-31", "2027-01-01"])
        self.assertEqual(bd.utc_range("2027-01-01", "2027-01-01", TZ), ("2026-12-31T17:00:00Z", "2027-01-01T17:00:00Z"))

    def test_RD09_utc_date_differs_from_business_date(self):
        inst = "2026-10-06T18:30:00Z"  # UTC date 06, Vietnam date 07
        self.assertEqual(bd.business_date(inst, TZ), "2026-10-07")
        self.assertTrue(bd.in_range(inst, *bd.utc_range("2026-10-07", "2026-10-07", TZ)))
        self.assertFalse(bd.in_range(inst, *bd.utc_range("2026-10-06", "2026-10-06", TZ)))

    def test_RD10_no_utc_truncation(self):
        self.assertNotEqual(bd.business_date("2026-10-06T18:30:00Z", TZ), "2026-10-06T18:30:00Z"[:10])
        f = E.ReadFilter(ME, "2026-10-07", "2026-10-07", 0, 50, TZ).odata()
        self.assertNotIn("2026-10-07T00:00:00Z", f, "UTC-midnight bound of the business date = the old defect")
        self.assertIn("WorkDate ge datetime'2026-10-06T17:00:00Z' and WorkDate lt datetime'2026-10-07T17:00:00Z'", f)

    def test_RD11_from_date_only_is_rejected(self):
        st = SharePointLike(days("2026-10-05", "2026-10-09"))
        r, got = read(st, FromDate="2026-10-07")
        self.assertEqual((r["code"], got), (E.VALIDATION_DATE, []), "R1 contract: both dates or neither")
        self.assertNotIn(" lt ", E.ReadFilter(ME, "2026-10-07", None, 0, 5, TZ).odata())

    def test_RD12_to_date_only_is_rejected(self):
        st = SharePointLike(days("2026-10-05", "2026-10-09"))
        r, got = read(st, ToDate="2026-10-07")
        self.assertEqual((r["code"], got), (E.VALIDATION_DATE, []), "R1 contract: both dates or neither")
        self.assertNotIn(" ge datetime", E.ReadFilter(ME, None, "2026-10-07", 0, 5, TZ).odata())

    def test_RD13_undated_read_refused(self):
        # OFFLINE-READOWN-GAP-FIX-01: FromDate + ToDate are mandatory; an undated read never reaches the query.
        st = SharePointLike(days("2026-10-05", "2026-10-09"))
        r, got = read(st)
        self.assertEqual((r["code"], got), (E.VALIDATION_DATE, []))
        self.assertNotIn("WorkDate", E.ReadFilter(ME, None, None, 0, 5, TZ).odata())  # internal filter builder only
        r = E.read_own(GUARD, CALLER, {"FromDate": "2026-10-05", "ToDate": "2026-10-06"}, st, correlation_id="c")
        self.assertEqual(r["code"], E.CONFIG_UNRESOLVED, "the zone is needed for every read")
        r = E.read_own(GUARD, CALLER, {"FromDate": "2026-10-05", "ToDate": "2026-10-06"}, st, correlation_id="c", business_timezone="Mars/Base")
        self.assertEqual(r["code"], E.CONFIG_UNRESOLVED, "unknown time zone fails closed")

    def test_RD14_paging_with_date_range(self):
        st = SharePointLike(days("2026-09-20", "2026-10-20"))
        seen, after = [], 0
        while True:
            r, got = read(st, FromDate="2026-10-01", ToDate="2026-10-10", PageSize=3, AfterId=after)
            seen += got
            after = r["nextAfterId"]
            if not after:
                break
        self.assertEqual(seen, days("2026-10-01", "2026-10-10"))

    def test_RD15_first_day_is_never_lost(self):
        year = days("2026-01-01", "2026-12-31")
        st = SharePointLike(year)
        for d in year:
            self.assertEqual(read(st, FromDate=d, ToDate=d)[1], [d], d)
            nxt = (dt.date.fromisoformat(d) + dt.timedelta(5)).isoformat()
            got = read(st, FromDate=d, ToDate=nxt, PageSize=500)[1]
            self.assertEqual(got[0], d, "first day of %s..%s" % (d, nxt))

    def test_RD_old_bounds_demonstrably_lost_the_first_day(self):
        """Regression proof of the defect: the old UTC-midnight bounds miss the first business date at UTC+07."""
        old_lo, old_hi = "2026-10-07T00:00:00Z", "2026-10-07T00:00:00Z"  # 'ge d T00:00Z and le d T00:00Z'
        self.assertFalse(old_lo <= stored("2026-10-07") <= old_hi)
        self.assertTrue(bd.in_range(stored("2026-10-07"), *bd.utc_range("2026-10-07", "2026-10-07", TZ)))

    def test_RD_dst_zone_is_handled_by_name(self):
        """The offset is derived from the zone name, so a DST zone gets the correct boundary on each side."""
        z = "America/Los_Angeles"
        self.assertEqual(bd.utc_range("2026-03-08", "2026-03-08", z), ("2026-03-08T08:00:00Z", "2026-03-09T07:00:00Z"))
        self.assertEqual(bd.utc_offset_minutes(TZ, "2026-01-15"), bd.utc_offset_minutes(TZ, "2026-07-15"))


class GeneratedReadFlowDateClause(unittest.TestCase):
    """The read-flow generator's WDL clause, executed in the simulator, equals the reference bounds."""

    @classmethod
    def setUpClass(cls):
        os.environ["TS_BUSINESS_TIMEZONE"] = TZ
        sys.path.insert(0, PA)
        cls.rf = importlib.reload(importlib.import_module("build_read_flow"))
        cls.date_expr = cls.rf.guard["If_ok"]["actions"]["DateClause"]["inputs"]
        cls.result_expr = cls.rf.guard["ResultCode"]["inputs"]

    def run_expr(self, expr, **outputs):
        r = wdl_sim.Run()
        for k, v in outputs.items():
            r.results[k] = {"status": "Succeeded", "outputs": v, "body": v}
        return r.value(expr)

    def clause(self, f, t):
        return self.run_expr(self.date_expr, FromRaw=f, ToRaw=t, HasRange=bool(f or t))

    def code(self, f, t):
        base = dict(HeaderUpn="", Trusted=ME, Mode="own", IsReviewer=False, ReqOwner="", ReqOwnerValid=False)
        return self.run_expr(self.result_expr, FromRaw=f, ToRaw=t, HasRange=bool(f or t), **base)

    def test_GRD1_clause_equals_reference_for_every_day_of_a_year(self):
        for d in days("2026-01-01", "2026-12-31"):
            t = (dt.date.fromisoformat(d) + dt.timedelta(2)).isoformat()
            lo, hi = bd.utc_range(d, t, TZ)
            self.assertEqual(self.clause(d, t), "WorkDate ge datetime'%s' and WorkDate lt datetime'%s' and " % (lo, hi), d)

    def test_GRD2_both_dates_or_neither_and_no_reversed_range(self):
        self.assertEqual(self.code("2026-10-07", "2026-10-07"), "OK")
        self.assertEqual(self.code("", ""), "OK")
        self.assertEqual(self.code("2026-10-07", ""), "VALIDATION", "RD11 in the flow: from only is refused")
        self.assertEqual(self.code("", "2026-10-07"), "VALIDATION", "RD12 in the flow: to only is refused (was silently ignored)")
        self.assertEqual(self.code("2026-10-08", "2026-10-07"), "VALIDATION")
        self.assertEqual(self.clause("", ""), "")

    def test_GRD3_no_utc_midnight_bound_and_derived_zone(self):
        src = self.rf.guard["If_ok"]["actions"]["DateClause"]["inputs"]
        self.assertNotIn("T00:00:00Z'' and WorkDate le", src)
        self.assertIn("'SE Asia Standard Time'", src)
        self.assertIsNone(re.search(r"\b420\b|\+07", src), "no fixed offset in the flow")
        with self.assertRaises(bd.TimeZoneConfigError):
            bd.windows_zone("Mars/Base")
        with self.assertRaises(bd.TimeZoneConfigError):
            bd.windows_zone("")


if __name__ == "__main__":
    unittest.main(verbosity=2)
