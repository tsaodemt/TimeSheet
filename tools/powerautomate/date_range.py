"""Workflow Definition Language expression for a business-date range filter on a date-only SharePoint column.

    [FromDate .. ToDate] (inclusive business dates in the business time zone)
      -> "<Field> ge datetime'<local FromDate 00:00 in UTC>Z' and <Field> lt datetime'<local ToDate+1 00:00 in UTC>Z' and "

The Windows time-zone id comes from the configured IANA business time zone (tools/timesheet/business_dates.py); the
UTC offset is never configured separately. Reference semantics and tests: business_dates.utc_range, test_date_range.py.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "timesheet"))
import business_dates as bd  # noqa: E402

_LOCAL = "yyyy-MM-ddTHH:mm:ss"


def _q(s: str) -> str:
    return s.replace("'", "''")


def local_midnight_utc_expr(date_expr: str, windows_tz: str) -> str:
    """UTC 'yyyy-MM-ddTHH:mm:ss' of 00:00 local on the business date given by date_expr (no 'Z')."""
    return "convertToUtc(concat(formatDateTime(%s, 'yyyy-MM-dd'), 'T00:00:00'), '%s', '%s')" % (date_expr, _q(windows_tz), _LOCAL)


def next_day_expr(date_expr: str) -> str:
    return "addDays(concat(formatDateTime(%s, 'yyyy-MM-dd'), 'T00:00:00Z'), 1, 'yyyy-MM-dd')" % date_expr


def date_clause_expr(field: str, from_expr: str, to_expr: str, windows_tz: str) -> str:
    """Expression (without the leading '@') producing the half-open filter clause, ending in ' and '."""
    lo = local_midnight_utc_expr(from_expr, windows_tz)
    hi = local_midnight_utc_expr(next_day_expr(to_expr), windows_tz)
    return ("concat('%s ge datetime''', %s, 'Z'' and %s lt datetime''', %s, 'Z'' and ')" % (field, lo, field, hi))


def reversed_range_expr(from_expr: str, to_expr: str) -> str:
    """True when FromDate is after ToDate (the request is invalid)."""
    return "greater(int(formatDateTime(%s, 'yyyyMMdd')), int(formatDateTime(%s, 'yyyyMMdd')))" % (from_expr, to_expr)


def windows_zone_from_config(iana: str) -> str:
    """Derive the Windows id from the configured IANA zone; fails closed for an unknown zone."""
    return bd.windows_zone(iana)
