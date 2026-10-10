"""EPIC 16 Project Effort ("Đăng ký công cho dự án", rev01 A.I + A.III actuals) reference model — R3 M2.

Flows: EFF-SetProjectPm, EFF-ReadProjectEffort, EFF-SaveProjectEffort. Source of truth: OpenSpec change
`r3-planning-effort-hour-registration` (specs/project-effort, planning-security, effort-reporting-contract; M2 decisions):
- unit man-day; VALUE = digits with an optional '.' and at most 2 decimals, >= 0, no business maximum (OD-14, OD-44); more
  than 15 significant digits is refused as TECHNICAL_LIMIT (double precision of SharePoint / Power Fx, not a business rule);
  more than 2 decimals is refused (never rounded or truncated);
- BLANK (not registered) and explicit 0 are distinct (OD-40); clear keeps the item with Effort = null (no Delete, D-7);
- one lifetime value per project x recipient; no phase, no period, manual entry only (OD-16, OD-22, OD-23);
- recipients = QLP, PM and the configured disciplines (AppSettings ProjectEffortRecipientDisciplines, OD-43 default);
- PM (OD-24): zero or one ACTIVE employee per project, assigned / changed only by PMO, stored in ProjectPmAssignments;
- edit = the project's PM only; view = the project's PM (own projects), PMO, Executive (OD-37); no approval (OD-26);
- actual effort = sum of Approved TimesheetEntries hours of the project / HoursPerManDay (OD-19, OD-33); project level only,
  computed, never stored; no Timesheet row is returned (aggregated actual visibility is not row visibility);
- one AuthorizationAllow / Deny row with the FINAL decision (role grant or project-PM scope); one ReadProxy row per read;
  one WriteProxy row per committed write; preflight all-or-nothing; ETag concurrency; ClientRequestId is correlation only.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Mapping, Optional

import effort_rules as er
import pe_schema as ps

OK, PARTIAL, REFUSED, ERROR, NO_CHANGE = "OK", "PARTIAL", "REFUSED", "ERROR", "NO_CHANGE"
NOT_WRITTEN, CONFLICT, NOT_FOUND = "NOT_WRITTEN", "CONFLICT", "NOT_FOUND"
VALIDATION_REQUEST, VALIDATION_VALUE, VALIDATION_LOOKUP, TECHNICAL_LIMIT = (
    "VALIDATION_REQUEST", "VALIDATION_VALUE", "VALIDATION_LOOKUP", "TECHNICAL_LIMIT")
CONFIG_INVALID, INTERNAL_ERROR, DIRECTORY_ERROR = "CONFIG_INVALID", "INTERNAL_ERROR", "DIRECTORY_ERROR"
BLANK, VALUE = "BLANK", "VALUE"
MAX_SIGNIFICANT = 15
READ_DECOYS = ["OwnerUpn", "PmUpn", "Role", "Scope"]
SAVE_DECOYS = ["ActorUpn", "OwnerUpn", "PmUpn", "Role", "Scope"]
PM_DECOYS = ["ActorUpn", "PmUpn", "Role", "Scope"]
LABELS = {"QLP": "Quản lý phòng", "PM": "PM"}
_NUM = re.compile(r"^[0-9]+(\.[0-9]{1,2})?$")
_DEC = re.compile(r"^[0-9]+(\.[0-9]+)?$")


class ConflictError(Exception):
    """412 on MERGE, or a duplicate unique key on create."""


def alloc_key(project_legacy: str, recipient_key: str) -> str:
    return "%s|%s" % (project_legacy, recipient_key)


def value_code(text) -> Optional[str]:
    t = "" if text is None else str(text)
    if not _NUM.match(t):
        return VALIDATION_VALUE
    if len(t.replace(".", "")) > MAX_SIGNIFICANT:
        return TECHNICAL_LIMIT
    return None


def fmt(v) -> str:
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def _int(s) -> int:
    s = "" if s is None else str(s).strip()
    if re.fullmatch(r"[0-9]+\.0+", s):
        s = s.split(".")[0]
    return int(s) if re.fullmatch(r"[0-9]+", s) else 0


def settings(rows: Mapping) -> tuple:
    """-> (hours_per_manday float, [discipline codes]) or None when invalid (fail closed)."""
    low = {str(k).lower(): ("" if v is None else str(v).strip()) for k, v in rows.items()}
    hpm = low.get(ps.HPM_SETTING.lower(), "")
    if not _DEC.match(hpm) or float(hpm) <= 0:
        return None
    rec = low.get(ps.RECIPIENT_SETTING.lower(), "") or ps.RECIPIENT_DEFAULT
    codes = [c.strip() for c in rec.split(",")]
    if not codes or any(not c for c in codes) or len(set(c.lower() for c in codes)) != len(codes):
        return None
    return float(hpm), codes


def recipients(codes, disciplines):
    """[{key, category, disciplineId, disciplineLegacyId, label}] or None when a configured code is unknown."""
    by_code = {str(d["DisciplineCode"]).lower(): d for d in disciplines}
    out = [{"key": "QLP", "category": "QLP", "disciplineId": 0, "disciplineLegacyId": "", "label": LABELS["QLP"]},
           {"key": "PM", "category": "PM", "disciplineId": 0, "disciplineLegacyId": "", "label": LABELS["PM"]}]
    for c in codes:
        d = by_code.get(c.lower())
        if d is None:
            return None
        out.append({"key": "D:%s" % d["LegacyId"], "category": "Discipline", "disciplineId": d["Id"],
                    "disciplineLegacyId": d["LegacyId"], "label": d["Title"]})
    return out


def _authz_row(guard_result, code, scope, cid):
    return {"EventType": "AuthorizationAllow" if code == er.ALLOW else "AuthorizationDeny", "Action": guard_result.RequestedAction,
            "Decision": "ALLOW" if code == er.ALLOW else "DENY", "ResultCode": code, "CorrelationId": cid}


# ---------------------------------------------------------------- EFF-ReadProjectEffort

def read_effort(guard_result, request: Mapping, data, *, correlation_id: str, profile_failed=False) -> dict:
    """ProjectItemId 0 / empty = list mode (projects the caller may view); > 0 = detail mode."""
    cid = correlation_id
    out = {"mode": "", "projects": [], "project": {}, "pm": {}, "recipients": [], "plannedTotal": "", "actualHours": "",
           "actualManDays": "", "variance": "", "hoursPerManDay": "", "canEdit": False, "canAssignPm": False, "pmEtag": "",
           "employees": [], "audit": []}
    if profile_failed:
        return dict(out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    pid = _int(request.get("ProjectItemId"))
    base = guard_result.ResultCode
    emp_id = guard_result.EmployeeId
    identity_ok = base in (er.ALLOW, er.ROLE_NOT_ALLOWED)
    try:
        mine = [a for a in data.assignments() if int(a["PmEmployeeItemId"]) == emp_id] if identity_ok else []
    except Exception:  # noqa: BLE001
        mine, base = [], ERROR
    mine_pids = {int(a["ProjectItemId"]) for a in mine}
    if base == ERROR:
        code, scope = ERROR, "none"
    elif pid <= 0:
        code, scope = er.list_decision(base, bool(mine_pids))
    else:
        code, scope = er.view_decision(base, pid in mine_pids, bool(mine_pids))
    audit = [_authz_row(guard_result, code, scope, cid)]

    def done(c, **kw):
        r = dict(out, ok=c == OK, code=c, messageCode="MSG_" + c, correlationId=cid, mode="list" if pid <= 0 else "detail", **kw)
        rows = len(r["projects"]) if pid <= 0 else len(r["recipients"])
        r["audit"] = audit + [{"EventType": "ReadProxy", "Action": "ReadProjectEffort", "Decision": "ALLOW" if c == OK else "DENY",
                               "ResultCode": "ALLOW" if c == OK else c, "CorrelationId": cid, "RowCount": rows,
                               "TargetItemId": str(pid) if pid > 0 else "", "TargetLegacyId": ""}]
        return r
    if code != er.ALLOW:
        return done(code)
    can_assign = er.role_can(guard_result.ResolvedRoles, er.ASSIGN)
    try:
        names = {int(e["Id"]): e for e in data.employees()}
        if pid <= 0:
            assigns = {int(a["ProjectItemId"]): a for a in data.assignments()}
            projs = sorted(data.projects(), key=lambda p: (str(p.get("ProjectCode") or ""), p["Id"]))
            if scope == er.PM_SCOPE:
                projs = [p for p in projs if p["Id"] in mine_pids]
            lst = []
            for p in projs:
                a = assigns.get(p["Id"])
                pm = names.get(int(a["PmEmployeeItemId"])) if a else None
                lst.append({"id": p["Id"], "code": p.get("ProjectCode") or "", "name": p.get("Title") or "", "status": p.get("Status") or "",
                            "pmName": (pm or {}).get("Title") or "", "canEdit": bool(a) and int(a["PmEmployeeItemId"]) == emp_id})
            return done(OK, projects=lst, canAssignPm=can_assign)
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        cfg = settings(data.settings())
        if cfg is None:
            return done(CONFIG_INVALID)
        hpm, codes = cfg
        recs = recipients(codes, data.disciplines())
        if recs is None:
            return done(CONFIG_INVALID)
        a = data.assignment(pid)
        items = {it["RecipientKey"]: it for it in data.allocations(pid)}
        hours = float(data.approved_hours(pid))
    except Exception:  # noqa: BLE001
        return done(ERROR)
    pm = {}
    if a:
        e = names.get(int(a["PmEmployeeItemId"])) or {}
        pm = {"employeeId": int(a["PmEmployeeItemId"]), "name": e.get("Title") or "", "code": e.get("LegacyUserName") or ""}
    rec_out, total = [], 0.0
    for r in recs:
        it = items.get(r["key"])
        val = None if it is None else it["Effort"]
        if val is not None:
            total += float(val)
        rec_out.append({"key": r["key"], "category": r["category"], "disciplineId": r["disciplineId"], "label": r["label"],
                        "state": BLANK if val is None else VALUE, "value": fmt(val), "etag": it["etag"] if it else ""})
    md = hours / hpm
    emps = []
    if can_assign:
        emps = [{"id": int(e["Id"]), "name": e.get("Title") or "", "code": e.get("LegacyUserName") or ""}
                for e in sorted(names.values(), key=lambda e: (str(e.get("Title") or ""), int(e["Id"]))) if e.get("IsActive") is True]
    return done(OK, project={"id": project["Id"], "code": project.get("ProjectCode") or "", "name": project.get("Title") or "",
                             "status": project.get("Status") or ""},
                pm=pm, recipients=rec_out, plannedTotal=fmt(total), actualHours=fmt(hours), actualManDays=fmt(md),
                variance=fmt(md - total), hoursPerManDay=fmt(hpm),
                canEdit=pid in mine_pids, canAssignPm=can_assign, pmEtag=a["etag"] if a else "", employees=emps)


# ---------------------------------------------------------------- EFF-SaveProjectEffort

def parse_changes(raw, max_changes):
    try:
        arr = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(arr, list) or not arr or len(arr) > max_changes or not all(isinstance(x, dict) for x in arr):
        return None
    out = [{"key": "" if x.get("key") is None else str(x.get("key")).strip(),
            "state": "" if x.get("state") is None else str(x.get("state")).strip().lower(),
            "value": "" if x.get("value") is None else str(x.get("value")).strip(),
            "etag": "" if x.get("etag") is None else str(x.get("etag"))} for x in arr]
    keys = [c["key"] for c in out]
    if len(set(keys)) != len(keys):
        return None
    return out


MAX_CHANGES = 20


def save_effort(guard_result, request: Mapping, data, store, *, correlation_id: str, profile_failed=False,
                row_audit_ok: Callable[[str], bool] = lambda key: True) -> dict:
    cid = correlation_id
    base_out = {"savedCount": 0, "results": [], "auditStatus": "", "warnings": [], "audit": [], "writes": []}
    if profile_failed:
        return dict(base_out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    pid = _int(request.get("ProjectItemId"))
    base = guard_result.ResultCode
    a = None
    if base in (er.ALLOW, er.ROLE_NOT_ALLOWED) and pid > 0:
        try:
            a = data.assignment(pid)
        except Exception:  # noqa: BLE001
            base = ERROR
    if base == ERROR:
        code, scope = ERROR, "none"
    else:
        code, scope = er.edit_decision(base, bool(a) and int(a["PmEmployeeItemId"]) == guard_result.EmployeeId)
    audit = [_authz_row(guard_result, code, scope, cid)]

    def done(c, **kw):
        r = dict(base_out, ok=c in (OK, PARTIAL), code=c, messageCode="MSG_" + c, correlationId=cid, **kw)
        r["audit"] = audit + r["audit"]
        return r
    if code != er.ALLOW:
        return done(code)
    changes = parse_changes(request.get("Changes"), MAX_CHANGES)
    if changes is None:
        return done(VALIDATION_REQUEST)
    try:
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        cfg = settings(data.settings())
        recs = recipients(cfg[1], data.disciplines()) if cfg else None
        if recs is None:
            return done(CONFIG_INVALID)
        items = {it["RecipientKey"]: it for it in data.allocations(pid)}
    except Exception:  # noqa: BLE001
        return done(ERROR)
    rk = {r["key"]: r for r in recs}
    pre = []
    for ch in changes:
        it = items.get(ch["key"])
        if ch["key"] not in rk:
            c = VALIDATION_LOOKUP
        elif ch["state"] not in ("blank", "value"):
            c = VALIDATION_VALUE
        elif ch["state"] == "value" and value_code(ch["value"]):
            c = value_code(ch["value"])
        elif it is None and ch["etag"] != "":
            c = CONFLICT
        elif it is not None and ch["etag"] != it["etag"]:
            c = CONFLICT
        else:
            stored = None if it is None else it["Effort"]
            want = None if ch["state"] == "blank" else float(ch["value"])
            same = (stored is None and want is None) or (stored is not None and want is not None and float(stored) == want)
            c = NO_CHANGE if same else "WRITE"
        pre.append((ch, it, c))
    if any(c not in ("WRITE", NO_CHANGE) for _, _, c in pre):
        return done(REFUSED, results=[{"key": ch["key"], "resultcode": NOT_WRITTEN if c in ("WRITE", NO_CHANGE) else c, "etag": ""}
                                      for ch, _, c in pre])
    results, rows, writes = [], [], []
    saved = failed = 0
    degraded = False
    for ch, it, c in pre:
        if c == NO_CHANGE:
            results.append({"key": ch["key"], "resultcode": NO_CHANGE, "etag": it["etag"] if it else ""})
            continue
        new = None if ch["state"] == "blank" else float(ch["value"])
        old = None if it is None else it["Effort"]
        action = "Create" if it is None else ("Clear" if new is None else "Update")
        r = rk[ch["key"]]
        key = it["AllocKey"] if it else alloc_key(project["LegacyId"], ch["key"])
        try:
            if it is None:
                fields = {"Title": key, "AllocKey": key, "LegacyId": key, "ProjectId": pid, "ProjectItemId": pid,
                          "RecipientKey": ch["key"], "RecipientCategory": r["category"],
                          "DisciplineId": r["disciplineId"] or None, "DisciplineItemId": r["disciplineId"] or None,
                          "Effort": new, "Status": "Active", "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
                writes.append(("POST", None, fields))
                item_id, etag = store.create(ps.ALLOC_LIST, fields)
            else:
                fields = {"Effort": new, "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
                writes.append(("MERGE", it["Id"], fields))
                item_id = it["Id"]
                store.update(ps.ALLOC_LIST, item_id, fields, it["etag"])
                etag = store.etag(ps.ALLOC_LIST, item_id)
            final = OK
        except ConflictError:
            final, etag, item_id = CONFLICT, "", None if it is None else it["Id"]
        except Exception:  # noqa: BLE001
            final, etag, item_id = ERROR, "", None if it is None else it["Id"]
        if final == OK:
            saved += 1
            row = {"EventType": "WriteProxy", "Action": action, "Decision": "ALLOW", "ResultCode": "ALLOW", "CorrelationId": cid,
                   "TargetList": ps.ALLOC_LIST, "TargetItemId": str(item_id), "TargetLegacyId": key,
                   "ChangeJson": {"EffortOld": fmt(old), "Effort": "" if new is None else ch["value"]}}
            if row_audit_ok(key):
                rows.append(row)
            else:
                degraded = True
        else:
            failed += 1
        results.append({"key": ch["key"], "resultcode": final, "etag": etag or ""})
    code = PARTIAL if failed else OK
    warnings = (["WARN_RELOAD_REQUIRED"] if failed else []) + (["AUDIT_DEGRADED"] if degraded else [])
    return done(code, savedCount=saved, results=results, auditStatus="AUDIT_DEGRADED" if degraded else "OK", warnings=warnings,
                audit=rows, writes=writes)


# ---------------------------------------------------------------- EFF-SetProjectPm

def set_pm(guard_result, request: Mapping, data, store, *, correlation_id: str, profile_failed=False,
           row_audit_ok: Callable[[str], bool] = lambda key: True) -> dict:
    cid = correlation_id
    out = {"etag": "", "pm": {}, "auditStatus": "", "audit": [], "writes": []}
    if profile_failed:
        return dict(out, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=cid)
    code = guard_result.ResultCode
    audit = [_authz_row(guard_result, code, guard_result.ResolvedScope if code == er.ALLOW else "none", cid)]

    def done(c, **kw):
        r = dict(out, ok=c in (OK, NO_CHANGE), code=c, messageCode="MSG_" + c, correlationId=cid, **kw)
        r["audit"] = audit + r["audit"]
        return r
    if code != er.ALLOW:
        return done(code)
    pid, eid = _int(request.get("ProjectItemId")), _int(request.get("EmployeeItemId"))
    etag_in = "" if request.get("ETag") is None else str(request.get("ETag"))
    if pid <= 0:
        return done(VALIDATION_LOOKUP)
    try:
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        emp = data.employee(eid) if eid > 0 else None
        a = data.assignment(pid)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    if emp is None or emp.get("IsActive") is not True:
        return done(VALIDATION_LOOKUP)
    pm = {"employeeId": int(emp["Id"]), "name": emp.get("Title") or "", "code": emp.get("LegacyUserName") or ""}
    if (a is None and etag_in != "") or (a is not None and etag_in != a["etag"]):
        return done(CONFLICT)
    if a is not None and int(a["PmEmployeeItemId"]) == int(emp["Id"]):
        return done(NO_CHANGE, etag=a["etag"], pm=pm)
    key = project["LegacyId"]
    try:
        if a is None:
            fields = {"Title": key, "PmKey": key, "LegacyId": key, "ProjectId": pid, "ProjectItemId": pid,
                      "PmEmployeeLegacyId": emp["LegacyId"], "PmEmployeeId": int(emp["Id"]), "PmEmployeeItemId": int(emp["Id"]),
                      "Status": "Active", "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
            out["writes"].append(("POST", None, fields))
            item_id, etag = store.create(ps.PM_LIST, fields)
        else:
            fields = {"PmEmployeeLegacyId": emp["LegacyId"], "PmEmployeeId": int(emp["Id"]), "PmEmployeeItemId": int(emp["Id"]),
                      "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": cid}
            out["writes"].append(("MERGE", a["Id"], fields))
            item_id = a["Id"]
            store.update(ps.PM_LIST, item_id, fields, a["etag"])
            etag = store.etag(ps.PM_LIST, item_id)
    except ConflictError:
        return done(CONFLICT)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    row = {"EventType": "WriteProxy", "Action": "Create" if a is None else "Update", "Decision": "ALLOW", "ResultCode": "ALLOW",
           "CorrelationId": cid, "TargetList": ps.PM_LIST, "TargetItemId": str(item_id), "TargetLegacyId": key,
           "ChangeJson": {"PmOld": "" if a is None else a["PmEmployeeLegacyId"], "Pm": emp["LegacyId"]}}
    ok_audit = row_audit_ok(key)
    return done(OK, etag=etag, pm=pm, auditStatus="OK" if ok_audit else "AUDIT_DEGRADED", audit=[row] if ok_audit else [])
