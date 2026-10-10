"""EPIC 17 Discipline Effort ("Đăng ký công cho bộ môn", rev01 A.II) reference model — R3 M3.

Flows: EFF-ReadDisciplineEffort, EFF-SaveDisciplineEffort, EFF-ApproveDisciplineEffort. Source of truth: OpenSpec change
`r3-planning-effort-hour-registration` (specs/discipline-effort, planning-security; M3 decisions 2026-10-10):
- allocation = Employee × Project × WorkType (OD-30); WorkType = active `WorkTypes` item, stable LegacyId (OD-29); discipline =
  snapshot of the caller's Employees row, never from the request;
- man-days; VALUE = digits with an optional '.' and at most 2 decimals, >= 0, no business maximum; > 15 significant digits =
  TECHNICAL_LIMIT; BLANK (not registered) ≠ 0 (OD-47); project lifetime (OD-48);
- ceiling (OD-15, OD-32, OD-27): Σ non-blank rows of D in P (Draft + ApprovedLocked) ≤ A.I.3 value of `D:<D>` in P; a blank A.I.3
  refuses VALUE saves (CEILING_NOT_REGISTERED); a change that would leave Σ above the ceiling and does not reduce Σ is refused
  (OVER_CEILING); exact cent arithmetic; serialised per Project × Discipline by a technical lock item (busy -> CONFLICT);
- save: own rows only, Draft only (ApprovedLocked -> LOCKED), ETag, preflight all-or-nothing, WriteProxy per committed write;
- approve (OD-17, OD-27, OD-28): Team Leader of the row's discipline; self allowed; Draft -> ApprovedLocked with revalidation
  (value present, ceiling, ETag); exactly one Approval event per approved row; no reopen (OD-18), no revision (OD-34);
- read (OD-46): own rows / discipline rows / project-PM (EPIC 16 authoritative PM) / company; the editor also gets the aggregate
  totals of its own discipline; actual = Σ Approved TimesheetEntries hours of P and D ÷ HoursPerManDay (OD-19, OD-33), totals only.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Mapping, Optional

import de_rules as dr
import de_schema as ds
import project_effort as pe

OK, PARTIAL, REFUSED, ERROR, NO_CHANGE = "OK", "PARTIAL", "REFUSED", "ERROR", "NO_CHANGE"
NOT_WRITTEN, CONFLICT, NOT_FOUND, LOCKED = "NOT_WRITTEN", "CONFLICT", "NOT_FOUND", "LOCKED"
VALIDATION_REQUEST, VALIDATION_VALUE, VALIDATION_LOOKUP, TECHNICAL_LIMIT = (
    pe.VALIDATION_REQUEST, pe.VALIDATION_VALUE, pe.VALIDATION_LOOKUP, pe.TECHNICAL_LIMIT)
OVER_CEILING, CEILING_NOT_REGISTERED = "OVER_CEILING", "CEILING_NOT_REGISTERED"
DIRECTORY_ERROR, CONFIG_INVALID = "DIRECTORY_ERROR", "CONFIG_INVALID"
SCOPE_NOT_ALLOWED, ROLE_NOT_ALLOWED, ALLOW = "SCOPE_NOT_ALLOWED", "ROLE_NOT_ALLOWED", "ALLOW"
BLANK, VALUE = "BLANK", "VALUE"
READ_DECOYS = ["DisciplineCode", "OwnerUpn", "PmUpn", "Role", "Scope"]
SAVE_DECOYS = ["ActorUpn", "DisciplineCode", "EmployeeId", "OwnerUpn", "Role", "Scope"]
APPROVE_DECOYS = ["ApprovedBy", "DisciplineCode", "OwnerUpn", "Role", "Scope", "Status"]
MAX_CHANGES, MAX_ITEMS = 20, 50
value_code, fmt, _int = pe.value_code, pe.fmt, pe._int


class ConflictError(Exception):
    """412 on MERGE, duplicate unique key on create, or a busy ceiling lock."""


def cents(text) -> int:
    """'12' / '12.5' / '12.25' (validated, <= 2 decimals) -> integer hundredths. Exact; no float arithmetic."""
    t = str(text)
    whole, _, frac = t.partition(".")
    return int(whole or "0") * 100 + int((frac + "00")[:2])


def cents_of(v) -> Optional[int]:
    return None if v is None else cents(fmt(v))


def md(c) -> str:
    """hundredths -> man-day text ('12', '12.5', '-0.25')."""
    if c is None:
        return ""
    sign, c = ("-", -c) if c < 0 else ("", c)
    w, f = divmod(c, 100)
    return sign + (str(w) if f == 0 else ("%d.%02d" % (w, f)).rstrip("0"))


def _authz(guard_result, code, cid):
    return {"EventType": "AuthorizationAllow" if code == ALLOW else "AuthorizationDeny", "Action": guard_result.RequestedAction,
            "Decision": "ALLOW" if code == ALLOW else "DENY", "ResultCode": code, "CorrelationId": cid}


def _disc_total(rows, disc_code):
    return sum(cents_of(r["Effort"]) for r in rows if r["DisciplineCode"] == disc_code and r["Effort"] is not None)


def _ceiling(allocs, disc_legacy):
    """A.I.3 value of recipient D:<legacy> in hundredths, or None when blank / not registered."""
    for a in allocs:
        if a["RecipientKey"] == "D:%s" % disc_legacy:
            return cents_of(a["Effort"])
    return None


# ---------------------------------------------------------------- EFF-ReadDisciplineEffort

def read(guard_result, request: Mapping, data, *, correlation_id: str, profile_failed=False) -> dict:
    cid = correlation_id
    out = {"scope": "none", "project": {}, "caller": {}, "rows": [], "summary": [], "workTypes": [], "audit": []}
    if profile_failed:
        return dict(out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    pid = _int(request.get("ProjectItemId"))
    base = guard_result.ResultCode
    identity_ok = base in (ALLOW, ROLE_NOT_ALLOWED)
    try:
        a = data.assignment(pid) if identity_ok and pid > 0 else None
    except Exception:  # noqa: BLE001
        a, base = None, ERROR
    is_pm = bool(a) and int(a["PmEmployeeItemId"]) == guard_result.EmployeeId
    scope = dr.best_scope(guard_result.ResolvedRoles, dr.VIEW) if base == ALLOW else "none"
    if is_pm and dr.RANK[dr.PM_SCOPE] > dr.RANK[scope]:
        scope = dr.PM_SCOPE
    code = ERROR if base == ERROR else (ALLOW if scope != "none" else (base if base != ALLOW else ROLE_NOT_ALLOWED))
    audit = [_authz(guard_result, code, cid)]

    def done(c, **kw):
        r = dict(out, ok=c == OK, code=c, messageCode="MSG_" + c, correlationId=cid, **kw)
        r["audit"] = audit + [{"EventType": "ReadProxy", "Action": "ReadDisciplineEffort", "Decision": "ALLOW" if c == OK else "DENY",
                               "ResultCode": "ALLOW" if c == OK else c, "CorrelationId": cid, "TargetItemId": str(pid) if pid > 0 else "",
                               "TargetLegacyId": ""}]
        return r
    if code != ALLOW:
        return done(code)
    if pid <= 0:
        return done(VALIDATION_LOOKUP)
    try:
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        me = data.employee(guard_result.EmployeeId)
        cfg = pe.settings(data.settings())
        if cfg is None:
            return done(CONFIG_INVALID)
        hpm, codes = cfg
        discs = {d["DisciplineCode"]: d for d in data.disciplines()}
        emps = {int(e["Id"]): e for e in data.employees()}
        wts = {int(w["Id"]): w for w in data.worktypes()}
        rows = sorted(data.rows(pid), key=lambda r: r["Id"])
        allocs = data.allocations(pid)
        hours = data.approved_hours_by_discipline(pid)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    my_disc = (me or {}).get("DisciplineCode") or ""
    if scope == "self":
        visible = [r for r in rows if int(r["EmployeeItemId"]) == guard_result.EmployeeId]
    elif scope == "discipline":
        visible = [r for r in rows if my_disc and r["DisciplineCode"] == my_disc]
    else:
        visible = rows
    if scope in ("self", "discipline"):
        sum_codes = [my_disc] if my_disc else []
    else:
        sum_codes = list(dict.fromkeys([c for c in codes if c in discs] + [r["DisciplineCode"] for r in rows]))
    summary = []
    for c in sum_codes:
        d = discs.get(c)
        ceil = _ceiling(allocs, d["LegacyId"]) if d else None
        used = _disc_total(rows, c)
        h = float(hours.get(c, 0.0))
        summary.append({"disciplineCode": c, "disciplineName": (d or {}).get("Title") or "", "ceilingState": BLANK if ceil is None else VALUE,
                        "ceiling": md(ceil), "used": md(used), "remaining": "" if ceil is None else md(ceil - used),
                        "actualHours": fmt(h), "actualManDays": fmt(h / hpm)})
    out_rows = []
    for r in visible:
        e, w = emps.get(int(r["EmployeeItemId"])) or {}, wts.get(int(r["WorkTypeItemId"])) or {}
        out_rows.append({"id": r["Id"], "employeeId": int(r["EmployeeItemId"]), "employeeName": e.get("Title") or "",
                         "disciplineCode": r["DisciplineCode"], "workTypeId": int(r["WorkTypeItemId"]), "workTypeCode": w.get("WorkTypeCode") or "",
                         "workTypeName": w.get("Title") or "", "state": BLANK if r["Effort"] is None else VALUE, "value": fmt(r["Effort"]),
                         "status": r["Status"], "etag": r["etag"], "mine": int(r["EmployeeItemId"]) == guard_result.EmployeeId})
    can_edit = dr.best_scope(guard_result.ResolvedRoles, dr.EDIT) != "none" and bool(my_disc)
    can_approve = dr.best_scope(guard_result.ResolvedRoles, dr.APPROVE) != "none" and bool(my_disc)
    return done(OK, scope=scope, project={"id": project["Id"], "code": project.get("ProjectCode") or "", "name": project.get("Title") or ""},
                caller={"employeeId": guard_result.EmployeeId, "disciplineCode": my_disc, "canEdit": can_edit, "canApprove": can_approve},
                rows=out_rows, summary=summary,
                workTypes=[{"id": int(w["Id"]), "code": w.get("WorkTypeCode") or "", "name": w.get("Title") or ""}
                           for w in sorted(wts.values(), key=lambda w: int(w["Id"])) if w.get("IsActive") is True])


# ---------------------------------------------------------------- EFF-SaveDisciplineEffort

def parse_changes(raw):
    try:
        arr = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(arr, list) or not arr or len(arr) > MAX_CHANGES or not all(isinstance(x, dict) for x in arr):
        return None
    out = [{"workTypeId": _int(x.get("workTypeId")), "state": "" if x.get("state") is None else str(x.get("state")).strip().lower(),
            "value": "" if x.get("value") is None else str(x.get("value")).strip(),
            "etag": "" if x.get("etag") is None else str(x.get("etag"))} for x in arr]
    ids = [c["workTypeId"] for c in out]
    return out if len(set(ids)) == len(ids) else None


def save(guard_result, request: Mapping, data, store, *, correlation_id: str, now: str, profile_failed=False,
         row_audit_ok: Callable[[str], bool] = lambda key: True) -> dict:
    cid = correlation_id
    base_out = {"savedCount": 0, "results": [], "ceiling": "", "used": "", "remaining": "", "auditStatus": "", "warnings": [], "audit": [], "writes": []}
    if profile_failed:
        return dict(base_out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    code = guard_result.ResultCode
    audit = [_authz(guard_result, code, cid)]

    def done(c, **kw):
        r = dict(base_out, ok=c in (OK, PARTIAL), code=c, messageCode="MSG_" + c, correlationId=cid, **kw)
        r["audit"] = audit + r["audit"]
        return r
    if code != ALLOW:
        return done(code)
    changes = parse_changes(request.get("Changes"))
    if changes is None:
        return done(VALIDATION_REQUEST)
    pid = _int(request.get("ProjectItemId"))
    if pid <= 0:
        return done(VALIDATION_LOOKUP)
    try:
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        me = data.employee(guard_result.EmployeeId)
        discs = {d["DisciplineCode"]: d for d in data.disciplines()}
        wts = {int(w["Id"]): w for w in data.worktypes()}
        allocs = data.allocations(pid)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    d = discs.get((me or {}).get("DisciplineCode") or "")
    if d is None:
        return done(VALIDATION_LOOKUP)
    lk = ds.lock_key(project["LegacyId"], d["LegacyId"])
    try:
        store.claim(lk, pid, d["Id"], cid, now)
    except ConflictError:
        return done(CONFLICT)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    try:
        return _save_locked(guard_result, changes, pid, project, me, d, wts, allocs, data, store, cid, done, row_audit_ok)
    finally:
        store.release(lk)


def _save_locked(guard_result, changes, pid, project, me, d, wts, allocs, data, store, cid, done, row_audit_ok):
    try:
        rows = data.rows(pid)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    mine = {int(r["WorkTypeItemId"]): r for r in rows if int(r["EmployeeItemId"]) == guard_result.EmployeeId}
    pre = []
    for ch in changes:
        w, it = wts.get(ch["workTypeId"]), mine.get(ch["workTypeId"])
        if w is None or (it is None and w.get("IsActive") is not True):
            c = VALIDATION_LOOKUP
        elif ch["state"] not in ("blank", "value"):
            c = VALIDATION_VALUE
        elif ch["state"] == "value" and value_code(ch["value"]):
            c = value_code(ch["value"])
        elif it is not None and it["Status"] == ds.APPROVED:
            c = LOCKED
        elif (it is None and ch["etag"] != "") or (it is not None and ch["etag"] != it["etag"]):
            c = CONFLICT
        else:
            old = None if it is None else cents_of(it["Effort"])
            new = None if ch["state"] == "blank" else cents(ch["value"])
            c = NO_CHANGE if old == new else "WRITE"
        pre.append((ch, it, w, c))
    ceil = _ceiling(allocs, d["LegacyId"])
    old_total = _disc_total(rows, d["DisciplineCode"])
    new_total = old_total
    for ch, it, w, c in pre:
        if c == "WRITE":
            new_total += (0 if ch["state"] == "blank" else cents(ch["value"])) - ((cents_of(it["Effort"]) or 0) if it else 0)
    info = {"ceiling": md(ceil), "used": md(old_total), "remaining": "" if ceil is None else md(ceil - old_total)}
    if any(c not in ("WRITE", NO_CHANGE) for _, _, _, c in pre):
        return done(REFUSED, results=[{"workTypeId": ch["workTypeId"], "resultcode": NOT_WRITTEN if c in ("WRITE", NO_CHANGE) else c, "etag": ""}
                                      for ch, _, _, c in pre], **info)
    sets_value = any(c == "WRITE" and ch["state"] == "value" for ch, _, _, c in pre)
    if ceil is None and sets_value:
        rc = CEILING_NOT_REGISTERED
    elif ceil is not None and new_total > ceil and new_total > old_total:
        rc = OVER_CEILING
    else:
        rc = None
    if rc:
        return done(REFUSED, results=[{"workTypeId": ch["workTypeId"], "resultcode": rc if c == "WRITE" else NOT_WRITTEN, "etag": ""}
                                      for ch, _, _, c in pre], **info)
    results, rows_audit, writes = [], [], []
    saved = failed = 0
    degraded = False
    for ch, it, w, c in pre:
        if c == NO_CHANGE:
            results.append({"workTypeId": ch["workTypeId"], "resultcode": NO_CHANGE, "etag": it["etag"] if it else ""})
            continue
        new = None if ch["state"] == "blank" else float(ch["value"])
        old = None if it is None else it["Effort"]
        action = "Create" if it is None else ("Clear" if new is None else "Update")
        key = it["RegKey"] if it else ds.reg_key(project["LegacyId"], me["LegacyId"], w["LegacyId"])
        try:
            if it is None:
                fields = {"Title": key, "RegKey": key, "LegacyId": key, "ProjectId": pid, "ProjectItemId": pid,
                          "EmployeeId": guard_result.EmployeeId, "EmployeeItemId": guard_result.EmployeeId, "EmployeeLegacyId": me["LegacyId"],
                          "OwnerUpn": guard_result.AuthenticatedUpn, "DisciplineId": d["Id"], "DisciplineItemId": d["Id"],
                          "DisciplineCode": d["DisciplineCode"], "DisciplineLegacyId": d["LegacyId"], "WorkTypeId": int(w["Id"]),
                          "WorkTypeItemId": int(w["Id"]), "WorkTypeLegacyId": w["LegacyId"], "Effort": new, "Status": ds.DRAFT,
                          "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
                writes.append(("POST", None, fields))
                item_id, etag = store.create(ds.REG_LIST, fields)
            else:
                fields = {"Effort": new, "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
                writes.append(("MERGE", it["Id"], fields))
                item_id = it["Id"]
                store.update(ds.REG_LIST, item_id, fields, it["etag"])
                etag = store.etag(ds.REG_LIST, item_id)
            final = OK
        except ConflictError:
            final, etag, item_id = CONFLICT, "", None
        except Exception:  # noqa: BLE001
            final, etag, item_id = ERROR, "", None
        if final == OK:
            saved += 1
            row = {"EventType": "WriteProxy", "Action": action, "Decision": "ALLOW", "ResultCode": "ALLOW", "CorrelationId": cid,
                   "TargetList": ds.REG_LIST, "TargetItemId": str(item_id), "TargetLegacyId": key,
                   "ChangeJson": {"EffortOld": fmt(old), "Effort": "" if new is None else ch["value"]}}
            if row_audit_ok(key):
                rows_audit.append(row)
            else:
                degraded = True
        else:
            failed += 1
        results.append({"workTypeId": ch["workTypeId"], "resultcode": final, "etag": etag or ""})
    final_total = new_total if not failed else None
    info2 = {"ceiling": md(ceil), "used": md(final_total) if final_total is not None else "",
             "remaining": "" if ceil is None or final_total is None else md(ceil - final_total)}
    code = PARTIAL if failed else OK
    warnings = (["WARN_RELOAD_REQUIRED"] if failed else []) + (["AUDIT_DEGRADED"] if degraded else [])
    return done(code, savedCount=saved, results=results, auditStatus="AUDIT_DEGRADED" if degraded else "OK", warnings=warnings,
                audit=rows_audit, writes=writes, **info2)


# ---------------------------------------------------------------- EFF-ApproveDisciplineEffort

def parse_items(raw):
    try:
        arr = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(arr, list) or not arr or len(arr) > MAX_ITEMS or not all(isinstance(x, dict) for x in arr):
        return None
    out = [{"itemId": _int(x.get("itemId")), "etag": "" if x.get("etag") is None else str(x.get("etag"))} for x in arr]
    ids = [x["itemId"] for x in out]
    return out if len(set(ids)) == len(ids) and all(i > 0 for i in ids) else None


def approve(guard_result, request: Mapping, data, store, *, correlation_id: str, now: str, profile_failed=False,
            row_audit_ok: Callable[[str], bool] = lambda key: True) -> dict:
    cid = correlation_id
    base_out = {"approvedCount": 0, "results": [], "auditStatus": "", "audit": [], "writes": []}
    if profile_failed:
        return dict(base_out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    code = guard_result.ResultCode
    audit = [_authz(guard_result, code, cid)]

    def done(c, **kw):
        r = dict(base_out, ok=c in (OK, PARTIAL), code=c, messageCode="MSG_" + c, correlationId=cid, **kw)
        r["audit"] = audit + r["audit"]
        return r
    if code != ALLOW:
        return done(code)
    items = parse_items(request.get("Items"))
    if items is None:
        return done(VALIDATION_REQUEST)
    try:
        me = data.employee(guard_result.EmployeeId)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    my_disc = (me or {}).get("DisciplineCode") or ""
    if not my_disc:
        return done(VALIDATION_LOOKUP)
    results, rows_audit, writes = [], [], []
    approved = 0
    degraded = False
    for x in items:
        try:
            r = data.reg(x["itemId"])
            rc = None
            if r is None:
                rc = NOT_FOUND
            elif r["DisciplineCode"] != my_disc:
                rc = SCOPE_NOT_ALLOWED
            elif r["Status"] == ds.APPROVED:
                rc = LOCKED
            elif r["Effort"] is None:
                rc = VALIDATION_VALUE
            elif x["etag"] != r["etag"]:
                rc = CONFLICT
            else:
                pid = int(r["ProjectItemId"])
                ceil = _ceiling(data.allocations(pid), r["DisciplineLegacyId"])
                total = _disc_total(data.rows(pid), r["DisciplineCode"])
                rc = CEILING_NOT_REGISTERED if ceil is None else (OVER_CEILING if total > ceil else None)
            if rc is None:
                fields = {"Status": ds.APPROVED, "ApprovedBy": guard_result.AuthenticatedUpn, "ApprovedOn": now,
                          "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
                writes.append(("MERGE", r["Id"], fields))
                try:
                    store.update(ds.REG_LIST, r["Id"], fields, r["etag"])
                    etag = store.etag(ds.REG_LIST, r["Id"])
                    rc = OK
                except ConflictError:
                    rc, etag = CONFLICT, ""
            else:
                etag = ""
        except Exception:  # noqa: BLE001
            rc, etag = ERROR, ""
        if rc == OK:
            approved += 1
            row = {"EventType": "Approval", "Action": "Approve", "Decision": "ALLOW", "ResultCode": "ALLOW", "CorrelationId": cid,
                   "TargetList": ds.REG_LIST, "TargetItemId": str(r["Id"]), "TargetLegacyId": r["RegKey"],
                   "ChangeJson": {"Status": ds.APPROVED}}
            if row_audit_ok(r["RegKey"]):
                rows_audit.append(row)
            else:
                degraded = True
        results.append({"itemId": x["itemId"], "resultcode": rc, "etag": etag})
    code = OK if approved == len(items) else (PARTIAL if approved else REFUSED)
    return done(code, approvedCount=approved, results=results, auditStatus="AUDIT_DEGRADED" if degraded else ("OK" if approved else ""),
                audit=rows_audit, writes=writes)
