"""Business-date semantics (generic; the business time zone is configuration, never a code constant).

A business date (e.g. WorkDate) is a calendar date in the business time zone. SharePoint stores a date-only value as
local midnight of the site time zone, i.e. as a UTC instant (at UTC+07:00, 2026-10-07 is 2026-10-06T17:00:00Z).

A date range [fromDate .. toDate] (both inclusive, business dates) therefore becomes the half-open UTC interval

    WorkDate >= local(fromDate 00:00) in UTC   AND   WorkDate < local(toDate + 1 day 00:00) in UTC

Never truncate a UTC value to get a business date, and never use a 23:59:59 inclusive upper bound.
The UTC offset is always DERIVED from the time-zone name (it is not an independent setting).
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# IANA -> Windows time-zone id (Power Automate convertToUtc / convertFromUtc use Windows ids). Extend deliberately;
# an unknown zone fails closed.
WINDOWS_ZONES = {
    "Asia/Ho_Chi_Minh": "SE Asia Standard Time",
    "Asia/Bangkok": "SE Asia Standard Time",
    "Asia/Jakarta": "SE Asia Standard Time",
    "UTC": "UTC",
    "America/Los_Angeles": "Pacific Standard Time",
}


class TimeZoneConfigError(ValueError):
    pass


def zone(tz_name: Optional[str]) -> ZoneInfo:
    if not tz_name:
        raise TimeZoneConfigError("business time zone not configured")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise TimeZoneConfigError("unknown time zone %r" % tz_name) from e


def windows_zone(tz_name: str) -> str:
    zone(tz_name)
    if tz_name not in WINDOWS_ZONES:
        raise TimeZoneConfigError("no Windows time-zone id mapped for %r" % tz_name)
    return WINDOWS_ZONES[tz_name]


def _utc_iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_midnight_utc(business_date: str, tz_name: str) -> str:
    """UTC instant of 00:00 local time on the business date."""
    d = _dt.date.fromisoformat(business_date)
    return _utc_iso(_dt.datetime.combine(d, _dt.time(), tzinfo=zone(tz_name)))


def utc_range(from_date: Optional[str], to_date: Optional[str], tz_name: str) -> tuple:
    """(fromUtc or None, toUtcExclusive or None) for an inclusive business-date range."""
    lo = local_midnight_utc(from_date, tz_name) if from_date else None
    hi = None
    if to_date:
        nxt = _dt.date.fromisoformat(to_date) + _dt.timedelta(days=1)
        hi = local_midnight_utc(nxt.isoformat(), tz_name)
    if lo and hi and lo >= hi:
        raise ValueError("empty range")
    return lo, hi


def business_date(utc_instant: str, tz_name: str) -> str:
    """Business date of a UTC instant: convert to the business zone first, then take the date. Never truncate UTC."""
    ts = _dt.datetime.strptime(utc_instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    return ts.astimezone(zone(tz_name)).date().isoformat()


def utc_offset_minutes(tz_name: str, on_date: str) -> int:
    """Derived offset on a given date (DST-aware). For display/diagnostics only; never stored as a setting."""
    d = _dt.datetime.combine(_dt.date.fromisoformat(on_date), _dt.time(12), tzinfo=zone(tz_name))
    return int(d.utcoffset().total_seconds() // 60)


def in_range(stored_utc: str, lo: Optional[str], hi_exclusive: Optional[str]) -> bool:
    """Half-open interval test on ISO-8601 UTC strings of the same shape."""
    return (lo is None or stored_utc >= lo) and (hi_exclusive is None or stored_utc < hi_exclusive)
