"""M4 current-scope effort reports — reference model (R3, owner decisions 2026-10-10: OD-50, OD-20, OD-31, OD-13, OD-51, OD-52).

Flows: RPT-ProjectReport, RPT-DisciplineReport. Contract: OpenSpec change `r3-planning-effort-hour-registration` (design §11.1,
specs/effort-reporting-contract, planning-security; AC-RPT-01..06).
- in-app, guarded, aggregate-only (OD-50): no source row, owner, employee, salary, rate or cost field leaves the flow (OD-20);
- project plan = Σ non-blank EPIC 16 `ProjectEffortAllocations.Effort` (BLANK when none); M1 registered = Σ non-blank
  `HourRegistrations.ManDays` incl. stale lines (OD-08), separate, REG.View holders only, never added to the plan (OD-52);
- discipline plan = Σ ApprovedLocked EPIC 17 registrations (Draft excluded, OD-51);
- actual = Σ Approved TimesheetEntries hours ÷ HoursPerManDay (OD-19, OD-33); 0 when there is no row and the row is still shown
  (OD-13); variance = planned − actual (design §11, shown as "Còn lại (Kế hoạch − Thực hiện)") when a plan exists;
  project-lifetime only (M4 R3 planning reporting; legacy / EPIC 11 period reporting = parity item PARITY-RPT-PERIOD-LIFETIME);
- scope (M4 report matrix): company (PMO / EXE / APR) ∪ discipline (TL, discipline report) ∪ projects where the caller is the EPIC 16
  authoritative PM; others ROLE_NOT_ALLOWED. One Authorization row + one ReadProxy row per call.
- per project, Approved actual rows are read in one page of 5,000; more fails closed (ERROR).
"""
from __future__ import annotations

import os
import sys
from typing import Mapping

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effort"))
import project_effort as pe  # noqa: E402
import rpt_rules as rr  # noqa: E402

OK, ERROR, CONFIG_INVALID, DIRECTORY_ERROR = "OK", "ERROR", "CONFIG_INVALID", "DIRECTORY_ERROR"
ALLOW, ROLE_NOT_ALLOWED = "ALLOW", "ROLE_NOT_ALLOWED"
BLANK, VALUE = "BLANK", "VALUE"
DECOYS = ["DisciplineCode", "EmployeeId", "OwnerUpn", "PmUpn", "ProjectItemId", "Role", "Scope"]
PAGE = 5000


class TooManyRows(Exception):
    """A project has more Approved Timesheet rows than one page: fail closed."""


def cents(text) -> int:
    t = str(text)
    neg = t.startswith("-")
    whole, _, frac = t.lstrip("-").partition(".")
    v = int(whole or "0") * 100 + int((frac + "00")[:2])
    return -v if neg else v


def fnum(v) -> str:
    """number -> text as the flow renders it (integral floats without '.0')."""
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def md(c) -> str:
    if c is None:
        return ""
    sign, c = ("-", -c) if c < 0 else ("", c)
    w, f = divmod(c, 100)
    return sign + (str(w) if f == 0 else ("%d.%02d" % (w, f)).rstrip("0"))


def _sum(values):
    """Σ of non-null hundredths, None when every value is null (BLANK)."""
    vals = [cents(fnum(v)) for v in values if v is not None]
    return sum(vals) if vals else None


def _hpm(settings):
    """HoursPerManDay as the M2 flows validate it (with the recipient configuration): None -> CONFIG_INVALID."""
    cfg = pe.settings(settings)
    return None if cfg is None else float(cfg[0])


def _authz(guard_result, code, cid):
    return {"EventType": "AuthorizationAllow" if code == ALLOW else "AuthorizationDeny", "Action": guard_result.RequestedAction,
            "Decision": "ALLOW" if code == ALLOW else "DENY", "ResultCode": code, "CorrelationId": cid}


def _scope(guard_result, data, cap):
    """-> (code, company, discipline, pm_ids)."""
    base = guard_result.ResultCode
    if base not in (ALLOW, ROLE_NOT_ALLOWED):
        return base, False, False, set()
    try:
        pm_ids = {int(a["ProjectItemId"]) for a in data.pm_assignments() if int(a["PmEmployeeItemId"]) == guard_result.EmployeeId}
    except Exception:  # noqa: BLE001
        return ERROR, False, False, set()
    roles = set(guard_result.ResolvedRoles) if base == ALLOW else set()
    company = bool(roles & set(rr.COMPANY_ROLES)) and cap in (rr.PROJECT, rr.DISCIPLINE)
    disc = cap == rr.DISCIPLINE and "TL" in roles
    if company or disc or pm_ids:
        return ALLOW, company, disc, pm_ids
    return ROLE_NOT_ALLOWED, False, False, set()


def _scope_label(company, disc, pm_ids):
    if company:
        return "company"
    return "+".join(x for x, on in (("discipline", disc), (rr.PM_SCOPE, bool(pm_ids))) if on) or "none"


def _done(out, audit, action, c, cid, **kw):
    r = dict(out, ok=c == OK, code=c, messageCode="MSG_" + c, correlationId=cid, **kw)
    r["audit"] = audit + [{"EventType": "ReadProxy", "Action": action, "Decision": "ALLOW" if c == OK else "DENY",
                           "ResultCode": "ALLOW" if c == OK else c, "CorrelationId": cid, "TargetItemId": "", "TargetLegacyId": ""}]
    return r


def _actual(data, pids):
    """{pid: {disciplineCode: hours hundredths}}; raises on read failure / TooManyRows."""
    out = {}
    for pid in pids:
        rows = data.approved_hours(pid)
        if len(rows) > PAGE:
            raise TooManyRows(pid)
        per = {}
        for d, h in rows:
            per[d or ""] = per.get(d or "", 0) + cents(fnum(h if h is not None else 0))
        out[pid] = per
    return out


def _measures(planned_c, hours_c, hpm):
    actual = fnum(hours_c / (hpm * 100))
    variance = "" if planned_c is None else fnum((planned_c * hpm - hours_c) / (hpm * 100))
    return actual, variance


# ---------------------------------------------------------------- RPT-ProjectReport

def project_report(guard_result, request: Mapping, data, *, correlation_id: str, profile_failed=False) -> dict:
    cid = correlation_id
    out = {"scope": "none", "rows": [], "totals": {}, "hoursPerManDay": "", "showRegistered": False, "audit": []}
    if profile_failed:
        return dict(out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    code, company, disc, pm_ids = _scope(guard_result, data, rr.PROJECT)
    audit = [_authz(guard_result, code, cid)]
    if code != ALLOW:
        return _done(out, audit, "ProjectReport", code, cid)
    show_m1 = bool(set(guard_result.ResolvedRoles) & set(rr.REG_VIEW_ROLES))
    try:
        hpm = _hpm(data.settings())
        if hpm is None:
            return _done(out, audit, "ProjectReport", CONFIG_INVALID, cid)
        projects = [p for p in data.projects() if company or int(p["Id"]) in pm_ids]
        allocs = data.allocations()
        m1 = data.hour_registrations() if show_m1 else []
        actual = _actual(data, [int(p["Id"]) for p in projects])
    except Exception:  # noqa: BLE001
        return _done(out, audit, "ProjectReport", ERROR, cid)
    rows, tp, th, tm = [], None, 0, None
    for p in projects:
        pid = int(p["Id"])
        pc = _sum(a["Effort"] for a in allocs if int(a["ProjectItemId"]) == pid)
        hc = sum(actual[pid].values())
        mc = _sum(h["ManDays"] for h in m1 if int(h["ProjectItemId"]) == pid) if show_m1 else None
        a, v = _measures(pc, hc, hpm)
        rows.append({"projectId": pid, "code": p.get("ProjectCode") or "", "name": p.get("Title") or "", "planState": BLANK if pc is None else VALUE,
                     "planned": md(pc), "actualHours": md(hc), "actualManDays": a, "variance": v, "registered": md(mc) if show_m1 else ""})
        tp = (tp or 0) + pc if pc is not None else tp
        th += hc
        tm = (tm or 0) + mc if mc is not None else tm
    ta, tv = _measures(tp, th, hpm)
    totals = {"planned": md(tp), "actualHours": md(th), "actualManDays": ta, "variance": tv, "registered": md(tm) if show_m1 else ""}
    return _done(out, audit, "ProjectReport", OK, cid, scope=_scope_label(company, disc, pm_ids), rows=rows, totals=totals,
                 hoursPerManDay=fnum(hpm), showRegistered=show_m1)


# ---------------------------------------------------------------- RPT-DisciplineReport

def discipline_report(guard_result, request: Mapping, data, *, correlation_id: str, profile_failed=False) -> dict:
    cid = correlation_id
    out = {"scope": "none", "rows": [], "hoursPerManDay": "", "audit": []}
    if profile_failed:
        return dict(out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    code, company, disc, pm_ids = _scope(guard_result, data, rr.DISCIPLINE)
    audit = [_authz(guard_result, code, cid)]
    if code != ALLOW:
        return _done(out, audit, "DisciplineReport", code, cid)
    try:
        hpm = _hpm(data.settings())
        if hpm is None:
            return _done(out, audit, "DisciplineReport", CONFIG_INVALID, cid)
        my_disc = ((data.employee(guard_result.EmployeeId) or {}).get("DisciplineCode") or "") if disc else ""
        projects = [p for p in data.projects() if company or int(p["Id"]) in pm_ids or (disc and my_disc)]
        regs = [r for r in data.registrations() if r["Status"] == "ApprovedLocked"]
        names = {d["DisciplineCode"]: d.get("Title") or "" for d in data.disciplines()}
        actual = _actual(data, [int(p["Id"]) for p in projects])
    except Exception:  # noqa: BLE001
        return _done(out, audit, "DisciplineReport", ERROR, cid)
    rows = []
    for p in projects:
        pid = int(p["Id"])
        full = company or pid in pm_ids
        planned = {}
        for r in regs:
            if int(r["ProjectItemId"]) == pid:
                planned.setdefault(r["DisciplineCode"], []).append(r["Effort"])
        codes = list(dict.fromkeys(sorted(planned) + sorted(k for k in actual[pid] if k)))
        for dcode in codes:
            if not full and dcode != my_disc:
                continue
            pc = _sum(planned.get(dcode, []))
            hc = actual[pid].get(dcode, 0)
            a, v = _measures(pc, hc, hpm)
            rows.append({"projectId": pid, "code": p.get("ProjectCode") or "", "name": p.get("Title") or "", "disciplineCode": dcode,
                         "disciplineName": names.get(dcode, ""), "planState": BLANK if pc is None else VALUE, "planned": md(pc),
                         "actualHours": md(hc), "actualManDays": a, "variance": v})
    return _done(out, audit, "DisciplineReport", OK, cid, scope=_scope_label(company, disc, pm_ids), rows=rows, hoursPerManDay=fnum(hpm))
