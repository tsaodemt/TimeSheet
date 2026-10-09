"""Reference implementation of TS-Approve, TS-Unapprove and TS-ReadTeam (EPIC 07 S07.2 / S07.3, executable specification;
no tenant data).

Contract: docs/approve-contract.md. The guard decision for `TS.Approve` (scope self) is an input; the caller, the
caller's discipline and the effective scope come from it, never from the request. Per row, in this order:

    item id not a positive integer / missing / Deleted        -> NOT_FOUND
    owner (stored EmployeeItemId -> Employees row) outside the effective scope:
        discipline scope: owner's CURRENT discipline must equal the caller's (both non-empty)
        company scope:    any existing owner
        owner row missing                                     -> SCOPE_NOT_ALLOWED
    own entry (owner employee = caller, or stored OwnerUpn = trusted caller UPN) -> ROLE_NOT_ALLOWED (UD-04)
    not Draft (Approved or any other non-deleted state)       -> LOCKED
    client ETag missing or different from the stored ETag     -> CONFLICT
    MERGE {EntryStatus, ApprovedBy, ApprovedOn} with IF-MATCH = stored ETag; 412 -> CONFLICT, other failure -> ERROR

TS-Unapprove (S07.3) applies the same order with capability TS.Unapprove (Approver / Executive, company), one row per
request, status Approved required (Draft -> NOT_APPROVED) and MERGE {EntryStatus: Draft, ApprovedBy: null, ApprovedOn: null}.

These per-row outcomes equal approval_rules.decide for every role x target (test AQ-EQ). Rows are processed
sequentially in request order; one row never rolls back another. ApprovedBy is the trusted caller UPN (text);
ApprovedOn is the server UTC instant of the request. Owner, employee, discipline snapshot, LegacyId, PeriodKey,
WorkDate, Created and Author are never written.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

OK, PARTIAL, REFUSED = "OK", "PARTIAL", "REFUSED"
NOT_FOUND, SCOPE_NOT_ALLOWED, ROLE_NOT_ALLOWED = "NOT_FOUND", "SCOPE_NOT_ALLOWED", "ROLE_NOT_ALLOWED"
LOCKED, CONFLICT, ERROR = "LOCKED", "CONFLICT", "ERROR"
NOT_APPROVED = "NOT_APPROVED"  # S07.3: unapprove target is not Approved (Draft); never a no-op success
VALIDATION_REQUEST, VALIDATION_DATE, VALIDATION_LOOKUP = "VALIDATION_REQUEST", "VALIDATION_DATE", "VALIDATION_LOOKUP"
CONFIG_UNRESOLVED, ERROR_LEAK = "CONFIG_UNRESOLVED", "ERROR_LEAK"
DIRECTORY_ERROR, INTERNAL_ERROR, MSG_TEMPORARY_PROBLEM = "DIRECTORY_ERROR", "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM"
WARN_RELOAD_REQUIRED, AUDIT_DEGRADED = "WARN_RELOAD_REQUIRED", "AUDIT_DEGRADED"
DRAFT, APPROVED, DELETED = "Draft", "Approved", "Deleted"
MAX_ITEMS, MAX_PAGE = 50, 500
DISCIPLINE, COMPANY = "discipline", "company"
APPROVE_INPUTS = {"Items", "ClientRequestId"}
TEAM_INPUTS = {"PeriodKey", "AfterId", "PageSize", "Mode"}
UNAPPROVE_INPUTS = {"ItemId", "ETag"}
# The only columns an approval writes (AQ16). Everything else on the row is preserved by construction.
APPROVAL_FIELDS = ("EntryStatus", "ApprovedBy", "ApprovedOn")
# per operation: the status that can be written, the code for any other non-deleted status, the MERGE body, audit event
OPS = {
    "approve": dict(need=DRAFT, state=LOCKED, event=("Approval", "Approve", "Phê duyệt: %s"),
                    body=lambda upn, at: {"EntryStatus": APPROVED, "ApprovedBy": upn, "ApprovedOn": at}),
    "unapprove": dict(need=APPROVED, state=NOT_APPROVED, event=("Unapproval", "Unapprove", "Hủy phê duyệt: %s"),
                      body=lambda upn, at: {"EntryStatus": DRAFT, "ApprovedBy": None, "ApprovedOn": None}),
}


class ConflictError(Exception):
    """SharePoint 412: the stored ETag changed between the read and the MERGE."""


@dataclass(frozen=True)
class Owner:
    """The owner's CURRENT Employees row (looked up by the stored EmployeeItemId)."""
    item_id: int
    code: str
    discipline: Optional[str]
    name: str = ""


@dataclass
class RowResult:
    itemid: str
    resultcode: str
    etag: str = ""

    def out(self) -> dict:
        return {"itemid": self.itemid, "resultcode": self.resultcode, "messagecode": "MSG_" + self.resultcode, "etag": self.etag}


@dataclass
class ApproveResponse:
    ok: bool
    code: str
    messageCode: str
    correlationId: str
    approvedCount: int = 0
    refusedCount: int = 0
    auditStatus: str = ""
    results: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    audit: list = field(default_factory=list)     # Approval rows appended (one per item)
    writes: list = field(default_factory=list)    # (itemId, body) MERGE bodies sent
    ignoredInputs: list = field(default_factory=list)


def _text(v) -> str:
    """Item values as the flow sees them: string(x), null -> ''. JSON booleans stringify as 'True' / 'False'."""
    return "" if v is None else str(v).strip()


def _pos_int(s: str) -> int:
    return int(s) if re.fullmatch(r"-?\d+", s or "") and int(s) > 0 else 0


def parse_items(raw) -> Optional[list]:
    """`Items` -> [(itemIdText, etag)] or None (VALIDATION_REQUEST): invalid JSON, not an array, an element that is not
    an object, empty, more than 50, or a duplicate item id."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(data, list) or not data or len(data) > MAX_ITEMS or not all(isinstance(x, dict) for x in data):
        return None
    out = [(_text(x.get("itemId")), "" if x.get("etag") is None else str(x.get("etag"))) for x in data]
    ids = [i for i, _ in out]
    if len(set(ids)) != len(ids):
        return None
    return out


def approve_entries(guard_result, caller_discipline: str, request: Mapping, store, owner_lookup: Callable[[int], Optional[Owner]],
                    *, correlation_id: str, approved_on: str, profile_failed: bool = False,
                    authorization_audit_ok: bool = True, row_audit_ok: Callable[[str], bool] = lambda item: True) -> ApproveResponse:
    """TS-Approve. store.get(id) -> (fields, etag) | None, raises on a technical failure; store.update(id, body, if_match)
    -> new etag (None when it cannot be read back), raises ConflictError on 412 and any other exception on failure.
    owner_lookup(employeeItemId) -> Owner | None, raises on a technical failure."""
    ignored = sorted(k for k in request if k not in APPROVE_INPUTS)

    def caller_level(code, msg=None):
        return ApproveResponse(False, code, msg or "MSG_" + code, correlation_id, ignoredInputs=ignored,
                               auditStatus="" if msg else "OK")
    if profile_failed:
        return caller_level(DIRECTORY_ERROR, MSG_TEMPORARY_PROBLEM)
    if not authorization_audit_ok:  # the mandatory AuthorizationAllow / Deny row precedes any entry read
        return caller_level(INTERNAL_ERROR, MSG_TEMPORARY_PROBLEM)
    if not guard_result.allowed:
        return caller_level(guard_result.ResultCode)
    items = parse_items(request.get("Items"))
    if items is None:
        return caller_level(VALIDATION_REQUEST)
    caller_upn = (guard_result.AuthenticatedUpn or "").lower()
    caller_emp = guard_result.EmployeeId
    scope = guard_result.ResolvedScope
    r = ApproveResponse(True, OK, "MSG_OK", correlation_id, auditStatus="OK", ignoredInputs=ignored)
    for item_text, client_etag in items:
        row = _row(OPS["approve"], item_text, client_etag, store, owner_lookup, scope, caller_discipline, caller_upn, caller_emp,
                   approved_on, r, correlation_id, row_audit_ok)
        if row.resultcode == OK:
            r.approvedCount += 1
        else:
            r.refusedCount += 1
    if r.approvedCount and r.refusedCount:
        r.code = PARTIAL
    elif not r.approvedCount:
        r.ok, r.code = False, REFUSED
    r.messageCode = "MSG_" + r.code
    if any(x["resultcode"] == OK and not x["etag"] for x in r.results):
        r.warnings.append(WARN_RELOAD_REQUIRED)
    if r.auditStatus == AUDIT_DEGRADED:
        r.warnings.append(AUDIT_DEGRADED)
    return r


def _row(op, item_text, client_etag, store, owner_lookup, scope, caller_disc, caller_upn, caller_emp, at, r, cid, row_audit_ok):
    """One row: result appended to r.results, one audit row appended to r.audit (removed and AUDIT_DEGRADED when the
    append fails)."""
    row, legacy, work_date, owner_emp = _check_and_write(op, item_text, client_etag, store, owner_lookup, scope, caller_disc,
                                                         caller_upn, caller_emp, at, r)
    r.results.append(row.out())
    ok = row.resultcode == OK
    event, action, text = op["event"]
    r.audit.append({"EventType": event, "Action": action, "ActionText": text % work_date, "Decision": "ALLOW" if ok else "DENY",
                    "ResultCode": "ALLOW" if ok else row.resultcode,
                    "TargetItemId": str(_pos_int(item_text)) if _pos_int(item_text) else "", "TargetLegacyId": legacy,
                    "OwnerEmployeeItemId": owner_emp, "WorkDate": work_date or None, "IsOnBehalf": True,
                    "ChangeJson": json.dumps({"EntryStatus": op["body"]("", "")["EntryStatus"]}, separators=(",", ":")) if ok else "",
                    "CorrelationId": cid, "ActorUpn": caller_upn})
    if not row_audit_ok(item_text):
        r.audit.pop()
        r.auditStatus = AUDIT_DEGRADED
    return row


def _check_and_write(op, item_text, client_etag, store, owner_lookup, scope, caller_disc, caller_upn, caller_emp, at, r):
    """-> (RowResult, TargetLegacyId, WorkDate business text, OwnerEmployeeItemId or None)."""
    i = _pos_int(item_text)
    res = RowResult(item_text, NOT_FOUND)
    if not i:
        return res, "", "", None
    try:
        got = store.get(i)
    except Exception:  # noqa: BLE001 - technical read failure: fail closed
        res.resultcode = ERROR
        return res, "", "", None
    if got is None:
        return res, "", "", None
    f, stored_etag = got
    legacy, work_date, owner_emp = f.get("LegacyId") or "", f.get("WorkDateText") or "", f.get("EmployeeItemId")
    if f.get("EntryStatus") == DELETED:
        return res, legacy, work_date, owner_emp
    try:
        owner = owner_lookup(owner_emp) if owner_emp else None
    except Exception:  # noqa: BLE001
        res.resultcode = ERROR
        return res, legacy, work_date, owner_emp
    in_scope = owner is not None and (scope == COMPANY or (scope == DISCIPLINE and bool(owner.discipline) and bool(caller_disc)
                                                           and owner.discipline == caller_disc))
    if not in_scope:
        res.resultcode = SCOPE_NOT_ALLOWED
    elif owner.item_id == caller_emp or (f.get("OwnerUpn") or "").lower() == caller_upn:
        res.resultcode = ROLE_NOT_ALLOWED
    elif f.get("EntryStatus") != op["need"]:
        res.resultcode = op["state"]
    elif not client_etag or client_etag != stored_etag:
        res.resultcode = CONFLICT
    else:
        body = op["body"](caller_upn, at)
        r.writes.append((i, body))
        try:
            new = store.update(i, body, stored_etag)
        except ConflictError:
            res.resultcode = CONFLICT
            return res, legacy, work_date, owner_emp
        except Exception:  # noqa: BLE001
            res.resultcode = ERROR
            return res, legacy, work_date, owner_emp
        res.resultcode = OK
        res.etag = new if new and new != stored_etag else ""
    return res, legacy, work_date, owner_emp


def unapprove_entry(guard_result, request: Mapping, store, owner_lookup: Callable[[int], Optional[Owner]], *, correlation_id: str,
                    profile_failed: bool = False, authorization_audit_ok: bool = True,
                    row_audit_ok: Callable[[str], bool] = lambda item: True) -> dict:
    """TS-Unapprove (S07.3): one row. guard_result is the guard decision for TS.Unapprove (scope self). Response keys:
    ok, code, messageCode, correlationId, itemId, etag, auditStatus, warnings (+ audit / writes for tests)."""
    ignored = sorted(k for k in request if k not in UNAPPROVE_INPUTS)
    item_text, etag = _text(request.get("ItemId")), "" if request.get("ETag") is None else str(request.get("ETag"))

    def done(code, msg=None, audit_status="OK", out_etag="", warnings=(), audit=(), writes=()):
        return {"ok": code == OK, "code": code, "messageCode": msg or "MSG_" + code, "correlationId": correlation_id,
                "itemId": "" if msg else item_text, "etag": out_etag, "auditStatus": "" if msg else audit_status,
                "warnings": list(warnings), "audit": list(audit), "writes": list(writes), "ignoredInputs": ignored}
    if profile_failed:
        return done(DIRECTORY_ERROR, MSG_TEMPORARY_PROBLEM)
    if not authorization_audit_ok:
        return done(INTERNAL_ERROR, MSG_TEMPORARY_PROBLEM)
    if not guard_result.allowed:
        return done(guard_result.ResultCode)
    r = ApproveResponse(True, OK, "MSG_OK", correlation_id, auditStatus="OK")
    row = _row(OPS["unapprove"], item_text, etag, store, owner_lookup, guard_result.ResolvedScope, "",
               (guard_result.AuthenticatedUpn or "").lower(), guard_result.EmployeeId, "", r, correlation_id, row_audit_ok)
    warnings = []
    if row.resultcode == OK and not row.etag:
        warnings.append(WARN_RELOAD_REQUIRED)
    if r.auditStatus == AUDIT_DEGRADED:
        warnings.append(AUDIT_DEGRADED)
    return done(row.resultcode, audit_status=r.auditStatus, out_etag=row.etag, warnings=warnings, audit=r.audit, writes=r.writes)


# ---------------------------------------------------------------- TS-ReadTeam (approval queue)

def period_key_ok(p: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", p or ""))


def team_filter(period: str, caller_upn: str, caller_emp: int, discipline: Optional[str], after: int, status: str = DRAFT) -> str:
    """The $filter the flow sends: PeriodKey (indexed) first; caller values are trusted, quotes doubled."""
    q = lambda s: s.replace("'", "''")  # noqa: E731
    parts = ["PeriodKey eq '%s'" % q(period), "EntryStatus eq '%s'" % status]
    if discipline is not None:
        parts.append("DisciplineCode eq '%s'" % q(discipline))
    parts += ["OwnerUpn ne '%s'" % q(caller_upn), "EmployeeItemId ne %d" % caller_emp, "Id gt %d" % after]
    return " and ".join(parts)


def read_team(guard_result, caller_discipline: str, request: Mapping, query: Callable[[str, int], list], *, correlation_id: str,
              business_date: Callable[[str], str], timezone_ok: bool = True, profile_failed: bool = False,
              authorization_audit_ok: bool = True) -> dict:
    """TS-ReadTeam. Mode "" / "pending": Draft rows (guard TS.Approve); "approved": Approved rows (guard TS.Unapprove; the
    caller passes the matching guard_result). query(filter, top) -> [(id, fields, etag)] ordered by id (fields include OwnerName / OwnerCode from
    the expanded Employee lookup); raises on failure. Returns the contract response plus the ReadProxy audit row."""
    ignored = sorted(k for k in request if k not in TEAM_INPUTS)
    base = {"correlationId": correlation_id, "rows": [], "nextAfterId": 0, "pageSize": 0, "ignoredInputs": ignored}

    def done(code, msg=None, rows=None, nxt=0, size=0):
        out = dict(base, ok=code == OK, code=code, messageCode=msg or "MSG_" + code, rows=rows or [], nextAfterId=nxt, pageSize=size)
        out["audit"] = [] if msg else [{"EventType": "ReadProxy", "Action": "ReadTeam", "Decision": "ALLOW" if code == OK else "DENY",
                                        "ResultCode": "ALLOW" if code == OK else code, "CorrelationId": correlation_id,
                                        "RowCount": len(out["rows"])}]
        return out
    if profile_failed:
        return done(DIRECTORY_ERROR, MSG_TEMPORARY_PROBLEM)
    if not authorization_audit_ok:
        return done(INTERNAL_ERROR, MSG_TEMPORARY_PROBLEM)
    if not guard_result.allowed:
        return done(guard_result.ResultCode)
    mode = _text(request.get("Mode")).lower()
    if mode not in ("", "pending", "approved"):
        return done(VALIDATION_REQUEST)
    want = APPROVED if mode == "approved" else DRAFT
    period = _text(request.get("PeriodKey"))
    if not period_key_ok(period):
        return done(VALIDATION_DATE)
    if not timezone_ok:
        return done(CONFIG_UNRESOLVED)
    a, s = _text(request.get("AfterId")), _text(request.get("PageSize"))
    if (a and not re.fullmatch(r"-?\d+", a)) or (s and not re.fullmatch(r"-?\d+", s)):
        return done(VALIDATION_LOOKUP)
    after = max(int(a), 0) if a else 0
    size = min(max(int(s), 1), MAX_PAGE) if s else MAX_PAGE
    scope = guard_result.ResolvedScope
    if scope == DISCIPLINE and not caller_discipline:
        return done(SCOPE_NOT_ALLOWED)
    disc = caller_discipline if scope == DISCIPLINE else None
    upn = (guard_result.AuthenticatedUpn or "").lower()
    try:
        rows = query(team_filter(period, upn, guard_result.EmployeeId, disc, after, want), size)
    except Exception:  # noqa: BLE001
        return done(ERROR)
    leak = any((f.get("OwnerUpn") or "").lower() == upn or f.get("EmployeeItemId") == guard_result.EmployeeId
               or f.get("EntryStatus") != want or f.get("PeriodKey") != period
               or (disc is not None and f.get("DisciplineCode") != disc) for _, f, _ in rows)
    if leak:
        return done(ERROR_LEAK)
    out = [{"id": i, "ownerName": f.get("OwnerName"), "ownerCode": f.get("OwnerCode"), "workDate": business_date(f.get("WorkDate")),
            "projectId": f.get("ProjectId"), "phaseId": f.get("PhaseId"), "workTypeId": f.get("WorkTypeId"),
            "shiftId": f.get("ShiftId"), "hourTypeId": f.get("HourTypeId"), "hours": f.get("Hours"), "remark": f.get("Remark"),
            "status": f.get("EntryStatus"), "etag": e, "approvedBy": f.get("ApprovedBy"), "approvedOn": f.get("ApprovedOn")}
           for i, f, e in rows]
    return done(OK, rows=out, nxt=out[-1]["id"] if len(out) == size else 0, size=size)
