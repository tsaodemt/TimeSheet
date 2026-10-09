"""S12.5 Hour Registration ("Đăng ký công") reference model — REG-ReadMatrix and REG-SaveMatrix (R3 M1).

Source of truth: OpenSpec change `r3-planning-effort-hour-registration` (V3 + M1 decisions, legacy parity):
- rows = the project's current phases (ProjectPhases IsActive, in project order) (OD-02);
- columns = every discipline of the master in SortOrder, no active filter (OD-08 legacy parity);
- a cell is BLANK or VALUE; explicit 0 is a VALUE; storage ManDays null vs number (OD-01);
- VALUE: digits with an optional '.' and at most 2 decimals, >= 0, no business maximum (OD-03, OD-42); more than 15
  significant digits is refused as TECHNICAL_LIMIT (double precision of SharePoint / Power Fx numbers, not a business rule);
- clear keeps the item and sets ManDays = null (OD-09, D-7: no Delete);
- every project is listed and editable whatever its target status (OD-07);
- a value on a phase that left the project's phase set stays stored, is not returned, not editable, and is cleared by the
  next save of that project whose preflight passes (OD-08 legacy parity);
- preflight all-or-nothing: authorization, validation and ETag of every requested cell before the first write; any
  refusal (incl. a stale ETag) -> REFUSED, 0 writes; a failure after preflight -> that cell CONFLICT / ERROR, PARTIAL;
- one WriteProxy audit row per committed changed cell (Create / Update / Clear); NO_CHANGE writes nothing;
- `ClientRequestId` is correlation only (no exactly-once claim); unique RegKey prevents duplicate cell items;
- the stable business key RegKey = <ProjectLegacyId>|<PhaseLegacyId>|<DisciplineLegacyId>; SharePoint item ids are
  environment-local lookup/query helpers only.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Mapping, Optional

import registration_rules as rr

LIST = "HourRegistrations"
MAX_CHANGES = 100
MAX_SIGNIFICANT = 15
OK, PARTIAL, REFUSED, ERROR = "OK", "PARTIAL", "REFUSED", "ERROR"
NO_CHANGE, NOT_WRITTEN, CONFLICT = "NO_CHANGE", "NOT_WRITTEN", "CONFLICT"
VALIDATION_REQUEST, VALIDATION_VALUE, VALIDATION_LOOKUP, TECHNICAL_LIMIT = (
    "VALIDATION_REQUEST", "VALIDATION_VALUE", "VALIDATION_LOOKUP", "TECHNICAL_LIMIT")
NOT_FOUND, INTERNAL_ERROR, DIRECTORY_ERROR = "NOT_FOUND", "INTERNAL_ERROR", "DIRECTORY_ERROR"
BLANK, VALUE = "BLANK", "VALUE"   # read response states; requests use them case-insensitively
REQ_BLANK, REQ_VALUE = "blank", "value"
READ_DECOYS = ["DisciplineCode", "OwnerUpn", "Role", "Scope"]
SAVE_DECOYS = ["ActorUpn", "DisciplineCode", "OwnerUpn", "Role", "Scope"]
_NUM = re.compile(r"^[0-9]+(\.[0-9]{1,2})?$")


class ConflictError(Exception):
    """412 on MERGE, or a duplicate unique RegKey on create."""


def reg_key(project_legacy: str, phase_legacy: str, discipline_legacy: str) -> str:
    return "%s|%s|%s" % (project_legacy, phase_legacy, discipline_legacy)


def value_code(text) -> Optional[str]:
    """None when `text` is a valid VALUE, else the refusal code (more than 15 digits = TECHNICAL_LIMIT: double precision of
    SharePoint / Power Fx numbers, not a business rule)."""
    t = "" if text is None else str(text)
    if not _NUM.match(t):
        return VALIDATION_VALUE
    if len(t.replace(".", "")) > MAX_SIGNIFICANT:
        return TECHNICAL_LIMIT
    return None


def fmt(v) -> str:
    """Stored number -> wire text as the platform renders a JSON number (12 -> '12', 12.5 -> '12.5'); None -> ''."""
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def _int(s) -> int:
    s = "" if s is None else str(s).strip()
    return int(s) if re.fullmatch(r"[0-9]+", s) else 0


def _guard_fail(guard_result, correlation_id, extra):
    return dict(extra, ok=False, code=guard_result.ResultCode, messageCode="MSG_" + guard_result.ResultCode, correlationId=correlation_id)


# ---------------------------------------------------------------- REG-ReadMatrix

def read_matrix(guard_result, request: Mapping, data, *, correlation_id: str, profile_failed=False, authorization_audit_ok=True) -> dict:
    """data: project(id), project_phases(id), disciplines(), items(project_id) (all raise on a technical failure)."""
    empty = {"project": {"id": None, "code": "", "name": "", "status": "", "year": None}, "phases": [], "disciplines": [], "cells": [],
             "canEdit": False, "audit": []}
    if profile_failed:
        return dict(empty, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=correlation_id)
    if not authorization_audit_ok:
        return dict(empty, ok=False, code=INTERNAL_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=correlation_id)

    def done(code, **kw):
        out = dict(empty, ok=code == OK, code=code, messageCode="MSG_" + code, correlationId=correlation_id, **kw)
        out["audit"] = [{"EventType": "ReadProxy", "Action": "ReadMatrix", "Decision": "ALLOW" if code == OK else "DENY",
                         "ResultCode": "ALLOW" if code == OK else code, "CorrelationId": correlation_id,
                         "RowCount": len(out["cells"])}]
        return out
    if not guard_result.allowed:
        return done(guard_result.ResultCode)
    pid = _int(request.get("ProjectItemId"))
    if pid <= 0:
        return done(VALIDATION_LOOKUP)
    try:
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        phases = data.project_phases(pid)
        discs = data.disciplines()
        items = data.items(pid)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    current = {p["PhaseItemId"] for p in phases}
    cells = [{"phaseId": it["PhaseItemId"], "disciplineId": it["DisciplineItemId"],
              "state": BLANK if it["ManDays"] is None else VALUE, "value": fmt(it["ManDays"]), "etag": it["etag"]}
             for it in sorted(items, key=lambda i: i["Id"]) if it["PhaseItemId"] in current]
    return done(OK, project={"id": project["Id"], "code": project.get("ProjectCode") or "", "name": project.get("Title") or "",
                             "status": project.get("Status") or "", "year": project.get("ProjectYear")},
                phases=[{"id": p["PhaseItemId"], "code": p["PhaseCode"], "name": p["PhaseTitle"]} for p in phases],
                disciplines=[{"id": d["Id"], "code": d["DisciplineCode"], "name": d["Title"]} for d in discs],
                cells=cells, canEdit=rr.can(guard_result.ResolvedRoles, rr.EDIT))


# ---------------------------------------------------------------- REG-SaveMatrix

def parse_changes(raw):
    """-> normalised list or None (invalid JSON / not a list / bad element / size / duplicate key)."""
    try:
        arr = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(arr, list) or not arr or len(arr) > MAX_CHANGES or not all(isinstance(x, dict) for x in arr):
        return None
    out = []
    for x in arr:
        out.append({"phaseId": _int(x.get("phaseId")), "disciplineId": _int(x.get("disciplineId")),
                    "state": "" if x.get("state") is None else str(x.get("state")).strip().lower(),
                    "value": "" if x.get("value") is None else str(x.get("value")).strip(),
                    "etag": "" if x.get("etag") is None else str(x.get("etag"))})
    keys = ["%d|%d" % (c["phaseId"], c["disciplineId"]) for c in out]
    if len(set(keys)) != len(keys):
        return None
    return out


def save_matrix(guard_result, request: Mapping, data, store, *, correlation_id: str, profile_failed=False,
                authorization_audit_ok=True, row_audit_ok: Callable[[str], bool] = lambda key: True) -> dict:
    """data: as read_matrix; store.create(fields) -> (id, etag) (ConflictError on duplicate key),
    store.update(id, fields, if_match) (ConflictError on 412), store.etag(id); all raise on technical failures."""
    base = {"savedCount": 0, "clearedStale": 0, "results": [], "auditStatus": "", "warnings": [], "audit": [], "writes": []}
    if profile_failed:
        return dict(base, ok=False, code=DIRECTORY_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=correlation_id)
    if not authorization_audit_ok:
        return dict(base, ok=False, code=INTERNAL_ERROR, messageCode="MSG_TEMPORARY_PROBLEM", correlationId=correlation_id)

    def done(code, **kw):
        return dict(base, ok=code in (OK, PARTIAL), code=code, messageCode="MSG_" + code, correlationId=correlation_id, **kw)
    if not guard_result.allowed:
        return done(guard_result.ResultCode)
    pid = _int(request.get("ProjectItemId"))
    changes = parse_changes(request.get("Changes"))
    if changes is None:
        return done(VALIDATION_REQUEST)
    if pid <= 0:
        return done(VALIDATION_LOOKUP)
    try:
        project = data.project(pid)
        if project is None:
            return done(NOT_FOUND)
        phases = data.project_phases(pid)
        discs = data.disciplines()
        items = data.items(pid)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    ph = {p["PhaseItemId"]: p for p in phases}
    dc = {d["Id"]: d for d in discs}
    by_key = {(i["PhaseItemId"], i["DisciplineItemId"]): i for i in items}

    # ---------------- preflight (no write)
    pre = []
    for ch in changes:
        it = by_key.get((ch["phaseId"], ch["disciplineId"]))
        if ch["phaseId"] not in ph or ch["disciplineId"] not in dc:
            code = VALIDATION_LOOKUP
        elif ch["state"] not in (REQ_BLANK, REQ_VALUE):
            code = VALIDATION_VALUE
        elif ch["state"] == REQ_VALUE and value_code(ch["value"]):
            code = value_code(ch["value"])
        elif it is None and ch["etag"] != "":
            code = CONFLICT
        elif it is not None and ch["etag"] != it["etag"]:
            code = CONFLICT
        else:
            stored = None if it is None else it["ManDays"]
            want = None if ch["state"] == REQ_BLANK else float(ch["value"])
            same = (stored is None and want is None) or (stored is not None and want is not None and float(stored) == want)
            code = NO_CHANGE if same else "WRITE"
        pre.append((ch, it, code))
    refused = any(code not in ("WRITE", NO_CHANGE) for _, _, code in pre)
    if refused:
        results = [{"phaseId": ch["phaseId"], "disciplineId": ch["disciplineId"], "stale": False,
                    "resultcode": NOT_WRITTEN if code in ("WRITE", NO_CHANGE) else code, "etag": ""} for ch, _, code in pre]
        return done(REFUSED, results=results)

    # ---------------- writes: requested cells, then stale cells of the project (OD-08)
    stale = [i for i in sorted(items, key=lambda i: i["Id"]) if i["PhaseItemId"] not in ph and i["ManDays"] is not None]
    plan = [(ch, it, code, False) for ch, it, code in pre]
    plan += [({"phaseId": i["PhaseItemId"], "disciplineId": i["DisciplineItemId"], "state": REQ_BLANK, "value": "", "etag": i["etag"]},
              i, "WRITE", True) for i in stale]
    results, audit, writes = [], [], []
    saved = cleared = failed = 0
    degraded = False
    for ch, it, code, is_stale in plan:
        if code == NO_CHANGE:
            results.append({"phaseId": ch["phaseId"], "disciplineId": ch["disciplineId"], "stale": False, "resultcode": NO_CHANGE,
                            "etag": it["etag"] if it else ""})
            continue
        new = None if ch["state"] == REQ_BLANK else float(ch["value"])
        old = None if it is None else it["ManDays"]
        action = "Create" if it is None else ("Clear" if new is None else "Update")
        if it is None:
            key = reg_key(project["LegacyId"], ph[ch["phaseId"]]["PhaseLegacyId"], dc[ch["disciplineId"]]["LegacyId"])
        else:
            key = it["RegKey"]
        try:
            if it is None:
                fields = {"Title": key, "RegKey": key, "LegacyId": key, "ProjectId": pid, "ProjectItemId": pid,
                          "PhaseId": ch["phaseId"], "PhaseItemId": ch["phaseId"], "DisciplineId": ch["disciplineId"],
                          "DisciplineItemId": ch["disciplineId"], "ManDays": new, "Status": "Active",
                          "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": correlation_id}
                writes.append(("POST", None, fields))
                item_id, etag = store.create(fields)
            else:
                fields = {"ManDays": new, "ActorUpn": guard_result.AuthenticatedUpn, "CorrelationId": correlation_id}
                writes.append(("MERGE", it["Id"], fields))
                item_id = it["Id"]
                store.update(item_id, fields, it["etag"])
                etag = store.etag(item_id)
            final = OK
        except ConflictError:
            final, etag, item_id = CONFLICT, "", (None if it is None else it["Id"])
        except Exception:  # noqa: BLE001
            final, etag, item_id = ERROR, "", (None if it is None else it["Id"])
        if final == OK:
            if is_stale:
                cleared += 1
            else:
                saved += 1
            row = {"EventType": "WriteProxy", "Action": action, "Decision": "ALLOW", "ResultCode": "ALLOW", "CorrelationId": correlation_id,
                   "TargetList": LIST, "TargetItemId": str(item_id), "TargetLegacyId": key,
                   "ChangeJson": {"ManDaysOld": fmt(old), "ManDays": "" if new is None else ch["value"]}}
            if row_audit_ok(key):
                audit.append(row)
            else:
                degraded = True
        else:
            failed += 1
        results.append({"phaseId": ch["phaseId"], "disciplineId": ch["disciplineId"], "stale": is_stale, "resultcode": final,
                        "etag": etag or ""})
    code = PARTIAL if failed else OK
    warnings = (["WARN_RELOAD_REQUIRED"] if failed else []) + (["AUDIT_DEGRADED"] if degraded else [])
    return done(code, savedCount=saved, clearedStale=cleared, results=results, auditStatus="AUDIT_DEGRADED" if degraded else "OK",
                warnings=warnings, audit=audit, writes=writes)
