"""Reference implementation of the R1 timesheet operations (executable specification; no tenant data).

    TS-SaveEntry (create / edit own draft) and TS-ReadOwn (own entries, keyset paging), as specified in
    docs/timesheet-r1-contracts.md. The guard decision (tools/identity/guard.py) is an input: these functions run
    only after it, and take the caller from it, never from the request.

Order of checks (save): guard -> configuration gates -> edit checks (NOT_FOUND, FORBIDDEN, LOCKED, CONFLICT)
-> validation (VALIDATION_LOOKUP, VALIDATION_HOURS, VALIDATION_DATE) -> warnings (non-blocking) -> write.

Create idempotency is NOT decided (R1-Q3). It is a pluggable strategy:
- NoIdempotency (default; the current interim: the app disables Save while a call is in flight, and the duplicate
  warning makes repeats visible);
- RequestKeyIdempotency (option under review; needs an approved, indexed and unique key column).
"""
from __future__ import annotations

import datetime as _dt
import re
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Protocol

import business_dates as bd

OK, OK_REPLAY = "OK", "OK_REPLAY"
NOT_FOUND, FORBIDDEN, LOCKED, CONFLICT = "NOT_FOUND", "FORBIDDEN", "LOCKED", "CONFLICT"
VALIDATION_LOOKUP, VALIDATION_HOURS, VALIDATION_DATE = "VALIDATION_LOOKUP", "VALIDATION_HOURS", "VALIDATION_DATE"
WARN_HOURS_ENTRY, WARN_HOURS_DAY, WARN_DUPLICATE = "WARN_HOURS_ENTRY", "WARN_HOURS_DAY", "WARN_DUPLICATE"
# The write succeeded but its new ETag could not be read back: etag is "" and the client must re-read the item
# before another edit (it never keeps using the ETag it sent).
WARN_RELOAD_REQUIRED = "WARN_RELOAD_REQUIRED"
CONFIG_UNRESOLVED, CONFIG_INVALID = "CONFIG_UNRESOLVED", "CONFIG_INVALID"
ERROR_LEAK, IDEMPOTENCY_KEY_REUSED = "ERROR_LEAK", "IDEMPOTENCY_KEY_REUSED"
ERROR = "ERROR"  # technical failure, e.g. reference data unreadable (fail closed)
VALIDATION_REQUEST_KEY = "VALIDATION_REQUEST_KEY"  # only with the request-key strategy (R1-Q3 option, not approved)

DRAFT, APPROVED, DELETED = "Draft", "Approved", "Deleted"
SAVE_INPUTS = {"ItemId", "ETag", "WorkDate", "ProjectCode", "PhaseCode", "WorkTypeCode", "ShiftCode", "HourTypeCode",
               "Hours", "Remark", "RequestKey"}
READ_INPUTS = {"FromDate", "ToDate", "AfterId", "PageSize", "RequestedOwner"}
MAX_PAGE = 500
# Settings every save needs. ProjectAssignmentScoping is included on purpose: while it is unresolved the save
# refuses (CONFIG_UNRESOLVED) instead of assuming "Off".
SAVE_SETTINGS = ("PayPeriodStartDay", "MaxHoursPerEntryWarn", "MaxHoursPerDayWarn", "ProjectAssignmentScoping", "BusinessTimezone")


@dataclass(frozen=True)
class Caller:
    """Trusted values from an ALLOWED guard result and the resolved employee row."""
    upn: str
    employee_item_id: int
    employee_code: str
    discipline_code: str


@dataclass
class Masters:
    """Small reference lists, keyed by code (case-insensitive). Values are dicts with at least `id`."""
    projects: Mapping[str, dict]           # {"id", "status": Active|Paused}
    project_phases: Mapping[tuple, dict]   # (projectCode, phaseCode) -> {"id", "active"}
    phases: Mapping[str, dict]             # {"id", "active"}
    work_types: Mapping[str, dict]         # {"id", "active"}
    shifts: Mapping[str, dict]             # {"id", "active"}
    hour_types: Mapping[str, dict]         # {"id"}
    assignments: Iterable[str] = ()        # project codes assigned to the caller (used only when scoping is On)


@dataclass
class Response:
    ok: bool
    code: str
    message: str = ""
    itemId: int = 0
    etag: str = ""
    correlationId: str = ""
    warnings: list = field(default_factory=list)
    ignoredInputs: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    messageCode: str = ""
    interim: list = field(default_factory=list)  # settings in effect that are interim (engineering only; e.g. B-03)
    auditStatus: str = "OK"  # AUDIT_DEGRADED when the operation's audit append failed (AUD-F1 option B)


class Store(Protocol):
    def get(self, item_id: int) -> Optional[tuple]: ...                       # (fields, etag) or None
    def create(self, fields: dict) -> tuple: ...                              # (item_id, etag or None if not read back)
    def update(self, item_id: int, fields: dict, if_match: str) -> Optional[str]: ...  # new etag (None if not read back); raises ConflictError
    def query(self, flt: "ReadFilter") -> list: ...                          # [(item_id, fields, etag)] ordered by id
    def find(self, **equals) -> list: ...                                    # [(item_id, fields, etag)]


class ConflictError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def period_key(work_date: _dt.date, start_day: int) -> str:
    """BR-DATE-02: a day on or after the start day belongs to the next month's period; Dec 26 -> January next year."""
    y, m = work_date.year, work_date.month
    if work_date.day >= start_day:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return "%04d-%02d" % (y, m)


def _date(s) -> Optional[_dt.date]:
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()):
        return None
    try:
        return _dt.date.fromisoformat(s.strip())
    except ValueError:
        return None


def _hours(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        h = float(v)
    elif isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v.strip()):
        h = float(v)
    else:
        return None
    return h if 0 < h <= 24 else None


def _ci(m: Mapping, code) -> Optional[dict]:
    if not isinstance(code, str):
        return None
    for k, v in m.items():
        if isinstance(k, str) and k.lower() == code.strip().lower():
            return dict(v, code=k)
    return None


def _setting(settings, key):
    s = settings.get(key)
    return s.value if s is not None else None


def _gate(settings, keys):
    bad = [k for k in keys if k not in settings or settings[k].status != "CONFIGURED"]
    if not bad:
        return None
    invalid = any(k in settings and settings[k].status == "INVALID" for k in bad)
    return (CONFIG_INVALID if invalid else CONFIG_UNRESOLVED), bad


# ---------------------------------------------------------------- idempotency strategies (R1-Q3 open)

class NoIdempotency:
    """Current interim: every create call creates. Retries can duplicate; WARN_DUPLICATE makes them visible."""
    name = "none"

    def before_create(self, store, caller, request, payload):
        return None

    def stamp(self, fields, request):
        return fields


class RequestKeyIdempotency:
    """Option under review (NOT approved): the app sends a GUID per logical create; the flow stores it in an
    indexed, unique column and returns the existing item when the same key comes back from the same owner."""
    name = "request-key"

    def __init__(self, column: str = "RequestKey"):
        self.column = column

    def before_create(self, store, caller, request, payload):
        key = str(request.get("RequestKey") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", key):
            return Response(False, VALIDATION_REQUEST_KEY)
        hits = store.find(**{self.column: key})
        if not hits:
            return None
        item_id, f, etag = hits[0]
        same = f.get("OwnerUpn") == caller.upn and all(f.get(k) == v for k, v in payload.items())
        if not same:
            return Response(False, IDEMPOTENCY_KEY_REUSED)  # never reveal the other item
        return Response(True, OK_REPLAY, itemId=item_id, etag=etag)

    def stamp(self, fields, request):
        return dict(fields, **{self.column: str(request.get("RequestKey")).strip().lower()})


# ---------------------------------------------------------------- save

def save_entry(guard_result, caller: Optional[Caller], request: Mapping, masters: Optional[Masters], settings: Mapping,
               store: Store, *, correlation_id: str, idempotency=None, messages: Optional[Mapping] = None) -> Response:
    """TS-SaveEntry for own drafts. `guard_result` is the guard decision for the own-draft capability (scope self)."""
    idem = idempotency or NoIdempotency()
    msg = lambda c: (messages or {}).get(c, "")  # noqa: E731  customer wording is R1-Q4 (open)
    ignored = sorted(k for k in request if k not in SAVE_INPUTS)

    def done(ok, code, **kw):
        action = kw.pop("_action", "Save")
        r = Response(ok, code, msg(code), correlationId=correlation_id, ignoredInputs=ignored, messageCode="MSG_" + code,
                     interim=sorted(k for k in SAVE_SETTINGS if k in settings and getattr(settings[k], "interim", False)), **kw)
        r.audit.append({"EventType": "WriteProxy", "Action": action, "Decision": "ALLOW" if ok else "DENY",
                        "ResultCode": code, "CorrelationId": correlation_id, "ActorUpn": caller.upn if caller else "",
                        "TargetItemId": str(r.itemId or ""), "IgnoredInputs": ignored})
        return r

    if guard_result is None or not guard_result.allowed or caller is None:
        return done(False, guard_result.ResultCode if guard_result is not None and guard_result.ResultCode else FORBIDDEN)
    if caller.upn != guard_result.AuthenticatedUpn:
        return done(False, FORBIDDEN)  # caller must be the guard's trusted identity
    g = _gate(settings, SAVE_SETTINGS)
    if g:
        return done(False, g[0], warnings=[])
    try:  # flows convert with the Windows id: a configured zone without a mapping is unusable
        bd.windows_zone(_setting(settings, "BusinessTimezone"))
    except bd.TimeZoneConfigError:
        return done(False, CONFIG_INVALID)
    if not caller.discipline_code:
        # Employees.Discipline and TimesheetEntries.DisciplineCode are both required: master-data configuration error
        return done(False, CONFIG_INVALID)

    item_id = request.get("ItemId") or 0
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return done(False, NOT_FOUND)
    existing = None
    if item_id:
        got = store.get(item_id)
        if got is None or got[0].get("EntryStatus") == DELETED:
            return done(False, NOT_FOUND)
        existing, etag = got
        if existing.get("OwnerUpn") != caller.upn:
            return done(False, FORBIDDEN)
        if existing.get("EntryStatus") != DRAFT:
            return done(False, LOCKED)
        if str(request.get("ETag") or "") != etag:
            return done(False, CONFLICT, itemId=item_id)

    # validation: lookups, then hours, then date. Unreadable reference data (masters=None) fails closed.
    if masters is None:
        return done(False, ERROR)
    project = _ci(masters.projects, request.get("ProjectCode"))
    if project is None or project.get("status") != "Active":
        return done(False, VALIDATION_LOOKUP)
    if _setting(settings, "ProjectAssignmentScoping") == "On" and project["code"].lower() not in {a.lower() for a in masters.assignments}:
        return done(False, VALIDATION_LOOKUP)
    phase = _ci(masters.phases, request.get("PhaseCode"))
    pp = None
    if phase is not None:
        pp = next((v for (pc, ph), v in masters.project_phases.items()
                   if pc.lower() == project["code"].lower() and ph.lower() == phase["code"].lower()), None)
    if phase is None or not phase.get("active", True) or pp is None or not pp.get("active", True):
        return done(False, VALIDATION_LOOKUP)
    lk = {}
    for name, table, active_col in (("WorkType", masters.work_types, True), ("Shift", masters.shifts, True),
                                    ("HourType", masters.hour_types, False)):
        v = _ci(table, request.get(name + "Code"))
        if v is None or (active_col and not v.get("active", True)):
            return done(False, VALIDATION_LOOKUP)
        lk[name] = v
    hours = _hours(request.get("Hours"))
    if hours is None:
        return done(False, VALIDATION_HOURS)
    wd = _date(request.get("WorkDate"))
    if wd is None:
        return done(False, VALIDATION_DATE)

    payload = {"WorkDate": wd.isoformat(), "ProjectId": project["id"], "PhaseId": phase["id"], "WorkTypeId": lk["WorkType"]["id"],
               "ShiftId": lk["Shift"]["id"], "HourTypeId": lk["HourType"]["id"], "Hours": hours,
               "Remark": str(request.get("Remark") or "")}

    # warnings (never block)
    warnings = []
    if hours > float(_setting(settings, "MaxHoursPerEntryWarn")):
        warnings.append(WARN_HOURS_ENTRY)
    same_day = [(i, f) for i, f, _ in store.find(OwnerUpn=caller.upn, WorkDate=wd.isoformat())
                if i != item_id and f.get("EntryStatus") != DELETED]
    if sum(float(f.get("Hours") or 0) for _, f in same_day) + hours > float(_setting(settings, "MaxHoursPerDayWarn")):
        warnings.append(WARN_HOURS_DAY)
    dup_keys = ("ShiftId", "ProjectId", "PhaseId", "HourTypeId")
    if any(all(f.get(k) == payload[k] for k in dup_keys) for _, f in same_day):
        warnings.append(WARN_DUPLICATE)

    trusted = {"OwnerUpn": caller.upn, "ActorUpn": caller.upn, "IsOnBehalf": False, "EmployeeId": caller.employee_item_id,
               "EmployeeItemId": caller.employee_item_id,
               "DisciplineCode": caller.discipline_code,
               "PeriodKey": period_key(wd, int(_setting(settings, "PayPeriodStartDay"))), "CorrelationId": correlation_id}
    if existing is None:
        replay = idem.before_create(store, caller, request, payload)
        if replay is not None:
            return done(replay.ok, replay.code, itemId=replay.itemId, etag=replay.etag, warnings=warnings if replay.ok else [])
        fields = idem.stamp(dict(payload, **trusted, LegacyId=str(uuid.uuid4()), LegacyOrigin="New", EntryStatus=DRAFT), request)
        new_id, new_etag = store.create(fields)
        new_etag, warnings = _readback(new_etag, None, warnings)
        return done(True, OK, itemId=new_id, etag=new_etag, warnings=warnings, _action="Create")
    fields = dict(payload, **{k: v for k, v in trusted.items() if k not in ("OwnerUpn", "EmployeeId", "EmployeeItemId")})
    # the owner (OwnerUpn, Employee lookup, EmployeeItemId) is never rewritten by an edit
    try:
        new_etag = store.update(item_id, fields, etag)
    except ConflictError:
        return done(False, CONFLICT, itemId=item_id)
    new_etag, warnings = _readback(new_etag, etag, warnings)
    return done(True, OK, itemId=item_id, etag=new_etag, warnings=warnings, _action="Update")


def _readback(new_etag, sent_etag, warnings):
    """A persisted write stays a success. Without a usable new ETag (not read back, or equal to the one sent) the
    response carries no ETag and WARN_RELOAD_REQUIRED: the client re-reads the item before another edit."""
    if not new_etag or new_etag == sent_etag:
        return "", warnings + [WARN_RELOAD_REQUIRED]
    return new_etag, warnings


# ---------------------------------------------------------------- read

@dataclass(frozen=True)
class ReadFilter:
    owner_upn: str
    from_date: Optional[str]
    to_date: Optional[str]
    after_id: int
    top: int
    business_timezone: Optional[str] = None

    def utc_bounds(self) -> tuple:
        """Half-open UTC interval [local from 00:00, local to+1 00:00) of the inclusive business-date range
        (business_dates.utc_range). A date-only value is stored as local midnight; at UTC+07, 2026-10-07 is
        2026-10-06T17:00:00Z, so a UTC-midnight bound would lose the first day."""
        if not (self.from_date or self.to_date):
            return None, None
        return bd.utc_range(self.from_date, self.to_date, self.business_timezone)

    def odata(self) -> str:
        """The $filter the read flow sends (indexed OwnerUpn first; values are trusted or validated, quotes doubled).
        Stored-instant behaviour of date-only columns: confirm in the timesheet POC (S06.11 P4)."""
        q = lambda s: s.replace("'", "''")  # noqa: E731
        parts = ["OwnerUpn eq '%s'" % q(self.owner_upn)]
        lo, hi = self.utc_bounds()
        if lo:
            parts.append("WorkDate ge datetime'%s'" % lo)
        if hi:
            parts.append("WorkDate lt datetime'%s'" % hi)
        parts += ["EntryStatus ne '%s'" % DELETED, "Id gt %d" % self.after_id]
        return " and ".join(parts)


def read_own(guard_result, caller: Optional[Caller], request: Mapping, store: Store, *, correlation_id: str,
             business_timezone: Optional[str] = None) -> dict:
    """TS-ReadOwn. Returns the contract response dict, with the one `ReadProxy` audit row of the call in `audit`.
    `business_timezone` is the configured IANA zone (AppSettings BusinessTimezone); the offset is derived from it."""
    r = _read_own(guard_result, caller, request, store, correlation_id, business_timezone)
    r["audit"] = [{"EventType": "ReadProxy", "Action": "ReadOwn", "Decision": "ALLOW" if r["ok"] else "DENY",
                   "ResultCode": r["code"], "CorrelationId": correlation_id, "ActorUpn": caller.upn if caller else "",
                   "RowCount": len(r["rows"]), "IgnoredInputs": r["ignoredInputs"]}]
    return r


def _read_own(guard_result, caller, request, store, correlation_id, tz):
    ignored = sorted(k for k in request if k not in READ_INPUTS)
    base = {"correlationId": correlation_id, "rows": [], "nextAfterId": 0, "pageSize": 0, "ignoredInputs": ignored}
    if guard_result is None or not guard_result.allowed or caller is None or caller.upn != guard_result.AuthenticatedUpn:
        return dict(base, ok=False, code=guard_result.ResultCode if guard_result is not None and guard_result.ResultCode else FORBIDDEN)
    ro = str(request.get("RequestedOwner") or "").strip().lower()
    if ro and ro != caller.upn:
        return dict(base, ok=False, code=FORBIDDEN)
    fd, td = request.get("FromDate"), request.get("ToDate")
    fdd, tdd = (_date(fd) if fd else None), (_date(td) if td else None)
    if (fd and fdd is None) or (td and tdd is None) or (fdd and tdd and fdd > tdd) or (bool(fd) != bool(td)):
        return dict(base, ok=False, code=VALIDATION_DATE)  # both dates or neither (R1 read contract); no reversed range
    try:  # always needed: stored date-only values are instants; the response returns business dates.
        bd.windows_zone(tz)  # flows convert with the Windows id: a zone without a mapping is unusable
    except bd.TimeZoneConfigError:
        return dict(base, ok=False, code=CONFIG_UNRESOLVED)  # business time zone not configured / unknown
    try:
        after = max(0, int(request.get("AfterId") or 0))
        ps = request.get("PageSize")
        size = MAX_PAGE if ps in (None, "") else int(ps)  # 0 is a value (clamped to 1), not "missing"
    except (TypeError, ValueError):
        return dict(base, ok=False, code=VALIDATION_LOOKUP)
    size = min(max(size, 1), MAX_PAGE)
    flt = ReadFilter(caller.upn, fdd.isoformat() if fdd else None, tdd.isoformat() if tdd else None, after, size, tz)
    try:
        rows = store.query(flt)
    except Exception:  # SharePoint / query failure: fail closed with the technical code, as the flow does
        return dict(base, ok=False, code=ERROR)
    if any(f.get("OwnerUpn") != caller.upn or f.get("EntryStatus") == DELETED for _, f, _ in rows):
        return dict(base, ok=False, code=ERROR_LEAK)  # never return a page that contains anything foreign
    biz = lambda v: bd.business_date(v, tz) if isinstance(v, str) and v.endswith("Z") else v  # noqa: E731
    out = [{"id": i, "workDate": biz(f.get("WorkDate")), "projectId": f.get("ProjectId"), "phaseId": f.get("PhaseId"),
            "workTypeId": f.get("WorkTypeId"), "shiftId": f.get("ShiftId"), "hourTypeId": f.get("HourTypeId"),
            "hours": f.get("Hours"), "remark": f.get("Remark"), "status": f.get("EntryStatus"), "etag": e} for i, f, e in rows]
    nxt = out[-1]["id"] if len(out) == size else 0
    return dict(base, ok=True, code=OK, rows=out, nextAfterId=nxt, pageSize=size)


AUDIT_DEGRADED = "AUDIT_DEGRADED"


def finalize_audit(r: Response, appended: bool) -> Response:
    """AUD-F1 option B (R1): the operation audit row could not be appended. A committed result stays a success
    (never a generic failure that invites a duplicate retry) and carries AUDIT_DEGRADED; a refusal keeps its code.
    Either way the correlation id is unchanged and nothing is retried."""
    if not appended:
        r.auditStatus = AUDIT_DEGRADED
        if r.ok and AUDIT_DEGRADED not in r.warnings:
            r.warnings = list(r.warnings) + [AUDIT_DEGRADED]
    return r
