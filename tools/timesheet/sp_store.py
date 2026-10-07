"""SharePoint data-path adapter for the R1 reference operations (generic; no tenant data; transport injected).

Lets entries.save_entry / entries.read_own run against a real SharePoint list through the SERVICE identity's session,
exactly as the R1 flows do (TS-SaveEntry / TS-ReadOwn), so a backend POC can prove create, bounded own-read, ETag
concurrency and owner isolation before any flow is deployed. It does NOT prove caller-identity propagation: the
trusted caller comes from resolve_caller(), which a POC harness feeds with a configured, already verified identity.

    transport(method, path, body, headers) -> (status, json_or_None, etag_header_or_None)   site-relative paths

    SharePointStore(transport, list_title, business_timezone)  -> entries.Store
    load_masters(transport)                                     -> entries.Masters (the R1 lookup lists, by code)
    resolve_caller(transport, upn, allowed_domains, employees="Employees") -> (identity_resolver.Resolution, entries.Caller|None)
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "identity"))
import business_dates as bd  # noqa: E402
import entries as E  # noqa: E402
import identity_resolver as idr  # noqa: E402

# Columns the R1 save flow writes / the read flow selects (build_r1_flows.py), plus the stored owner columns.
SELECT = ("Id,WorkDate,ProjectId,PhaseId,WorkTypeId,ShiftId,HourTypeId,Hours,Remark,EntryStatus,OwnerUpn,ActorUpn,IsOnBehalf,"
          "EmployeeId,EmployeeItemId,DisciplineCode,PeriodKey,CorrelationId,LegacyId,LegacyOrigin,MigrationBatch")
JSON = {"Accept": "application/json;odata=minimalmetadata", "Content-Type": "application/json;odata=minimalmetadata"}


class TransportError(RuntimeError):
    pass


def _q(s: str) -> str:
    return str(s).replace("'", "''")


class SharePointStore:
    """entries.Store over one SharePoint list. `stamp` adds fixed columns to every create (e.g. a POC data marker);
    it can never set an owner, actor, status or identifier column."""
    PROTECTED = {"OwnerUpn", "ActorUpn", "EmployeeId", "EmployeeItemId", "EntryStatus", "LegacyId", "IsOnBehalf"}

    def __init__(self, transport: Callable, list_title: str, business_timezone: str, *, stamp: Optional[dict] = None):
        bd.windows_zone(business_timezone)  # fail closed on an unusable zone
        if set(stamp or {}) & self.PROTECTED:
            raise ValueError("stamp may not set owner / actor / status / identifier columns")
        self.t, self.tz, self.stamp = transport, business_timezone, dict(stamp or {})
        self.base = "/_api/web/lists/getbytitle('%s')" % _q(list_title)
        self.calls = []

    def _call(self, method, path, body=None, headers=None):
        status, data, etag = self.t(method, self.base + path, body, dict(JSON, **(headers or {})))
        self.calls.append((method, path, status))
        return status, data, etag

    def _fields(self, row: dict) -> dict:
        f = {k: v for k, v in row.items() if not k.startswith("odata.") and k not in ("ID", "Id")}
        if isinstance(f.get("WorkDate"), str) and f["WorkDate"].endswith("Z"):
            f["WorkDateUtc"] = f["WorkDate"]
            f["WorkDate"] = bd.business_date(f["WorkDate"], self.tz)  # business date, never a truncated UTC value
        return f

    def get(self, item_id: int):
        status, data, _ = self._call("GET", "/items(%d)?$select=%s" % (int(item_id), SELECT))
        if status == 404:
            return None
        if status != 200:
            raise TransportError("get %s -> %s" % (item_id, status))
        return self._fields(data), data.get("odata.etag")

    def create(self, fields: dict):
        body = dict(fields, **self.stamp)
        status, data, _ = self._call("POST", "/items", body)
        if status != 201:
            raise TransportError("create -> %s %s" % (status, str(data)[:300]))
        got = self.get(data["Id"])  # read back (the flow's response carries the stored ETag)
        return data["Id"], (got[1] if got else None)

    def update(self, item_id: int, fields: dict, if_match: str):
        status, data, _ = self._call("POST", "/items(%d)" % int(item_id), dict(fields),
                                     {"X-HTTP-Method": "MERGE", "IF-MATCH": if_match})
        if status == 412:
            raise E.ConflictError()
        if status not in (200, 204):
            raise TransportError("update %s -> %s %s" % (item_id, status, str(data)[:300]))
        got = self.get(item_id)
        return got[1] if got else None

    def query(self, flt: "E.ReadFilter") -> list:
        status, data, _ = self._call("GET", "/items?$select=%s&$filter=%s&$orderby=Id asc&$top=%d" % (SELECT, flt.odata(), flt.top))
        if status != 200:
            raise TransportError("query -> %s %s" % (status, str(data)[:300]))
        return [(r["Id"], self._fields(r), r.get("odata.etag")) for r in data["value"]]

    def find(self, **equals) -> list:
        """Owner + business-date lookups as the save flow's same-day query: OwnerUpn first (indexed), WorkDate as the
        half-open UTC interval of that business date. Other equality filters are applied to the returned rows."""
        owner, day = equals.pop("OwnerUpn", None), equals.pop("WorkDate", None)
        if owner is None:
            raise ValueError("find needs OwnerUpn (indexed first filter)")
        parts = ["OwnerUpn eq '%s'" % _q(owner)]
        if day:
            lo, hi = bd.utc_range(day, day, self.tz)
            parts += ["WorkDate ge datetime'%s'" % lo, "WorkDate lt datetime'%s'" % hi]
        status, data, _ = self._call("GET", "/items?$select=%s&$filter=%s&$orderby=Id asc&$top=500" % (SELECT, " and ".join(parts)))
        if status != 200:
            raise TransportError("find -> %s" % status)
        rows = [(r["Id"], self._fields(r), r.get("odata.etag")) for r in data["value"]]
        return [x for x in rows if all(x[1].get(k) == v for k, v in equals.items())]


# lookup list -> (code column, flag column, Masters attribute) as the R1 save flow (build_r1_flows.MASTERS)
_MASTERS = {"Projects": ("ProjectCode", "Status", "projects"), "Phases": ("PhaseCode", "IsActive", "phases"),
            "WorkTypes": ("WorkTypeCode", "IsActive", "work_types"), "Shifts": ("ShiftCode", "IsActive", "shifts"),
            "HourTypes": ("HourTypeCode", None, "hour_types")}


def _rows(transport, title, select):
    status, data, _ = transport("GET", "/_api/web/lists/getbytitle('%s')/items?$select=%s&$top=5000" % (_q(title), select), None, JSON)
    if status != 200:
        raise TransportError("%s unreadable (%s)" % (title, status))  # unreadable reference data fails closed
    return data["value"]


def load_masters(transport) -> "E.Masters":
    out = {}
    for title, (code, flag, attr) in _MASTERS.items():
        m = {}
        for r in _rows(transport, title, ",".join(x for x in ("Id", code, flag) if x)):
            v = {"id": r["Id"]}
            if flag == "Status":
                v["status"] = r.get("Status")
            elif flag:
                v["active"] = r.get(flag) is not False
            m[r[code]] = v
        out[attr] = m
    by_id = {a: {v["id"]: c for c, v in out[a].items()} for a in ("projects", "phases")}
    pp = {}
    for r in _rows(transport, "ProjectPhases", "Id,ProjectId,PhaseId,IsActive"):
        key = (by_id["projects"].get(r["ProjectId"]), by_id["phases"].get(r["PhaseId"]))
        if None not in key:
            pp[key] = {"id": r["Id"], "active": r.get("IsActive") is not False}
    return E.Masters(projects=out["projects"], project_phases=pp, phases=out["phases"], work_types=out["work_types"],
                     shifts=out["shifts"], hour_types=out["hour_types"], assignments=())


def resolve_caller(transport, upn: str, allowed_domains, employees: str = "Employees"):
    """Employees.AccountUpn -> exactly one active row (identity_resolver rules: UNMAPPED / DUPLICATE / INACTIVE never
    weakened) and the discipline through the required Discipline lookup, as the R1 guard reads it."""
    norm = idr.normalise_upn(upn)

    def lookup(u):
        status, data, _ = transport("GET", "/_api/web/lists/getbytitle('%s')/items?$select=Id,LegacyId,IsActive,AccountUpn,DisciplineId,"
                                    "Discipline/DisciplineCode&$expand=Discipline&$filter=AccountUpn eq '%s'&$top=5" % (_q(employees), _q(u)), None, JSON)
        if status != 200:
            raise TransportError("Employees lookup %s" % status)
        lookup.rows = data["value"]
        return [idr.Employee(r["Id"], r.get("LegacyId") or "", r.get("AccountUpn") or "", r.get("IsActive") is True, r.get("DisciplineId"))
                for r in data["value"]]
    lookup.rows = []
    res = idr.resolve(idr.TrustedIdentity(norm or ""), lookup, idr.Config(allowed_domains=allowed_domains))
    if not res.ok:
        return res, None
    row = next(r for r in lookup.rows if r["Id"] == res.employee.item_id)
    disc = (row.get("Discipline") or {}).get("DisciplineCode") or ""
    return res, E.Caller(res.upn, res.employee.item_id, res.employee.legacy_id, disc)
