"""STAGING-UX-01 evaluator — clean SharePoint staging home, navigation and master-data views (generic; no tenant data).

evaluate(evidence) -> {"tests": {UX01..UX22: (PASS|FAIL, reason)}, "pass": bool, "score": "n/22"}

Presentation only. Security wins: any permission, schema or business-data difference fails the task, and the
POC-MASTER-01 behaviour (read-only master data, direct writes denied, one active identity row) must still hold.
Navigation clutter may be hidden or removed as LINKS only; every library / list must still exist afterwards.
"""
from __future__ import annotations

import re
from typing import Mapping

MASTER_LISTS = ("Employees", "Departments", "Disciplines", "Positions")
NAV_TARGET = ["Home", "Employees", "Departments", "Disciplines", "Positions"]
NAV_NOISE = {"Notebook", "News", "Documents", "Pages", "Recent", "Site contents"}
NOT_PROMOTED = re.compile(r"auditlog|appsettings|_ts_|spike|projects|projectphases|timesheetentries", re.I)
TECHNICAL_FIELDS = {"LegacyId", "LegacyUserName", "MigrationBatch", "LegacyModifiedOn", "IsLegacyPlaceholder", "SortOrder", "ID",
                    "AccountUpn", "EmployeeAccount", "PositionLegacyId", "Author", "Editor", "Created", "Modified"}
BUSINESS_FIELDS = {"Employees": ["LinkTitle", "Department", "Discipline", "Position", "IsActive"],
                   "Departments": ["LinkTitle", "DepartmentCode", "IsActive"],
                   "Disciplines": ["LinkTitle", "DisciplineCode", "IsActive"],
                   "Positions": ["LinkTitle", "PositionCode", "IsActive"]}
HOME_TITLE = "TimeSheet Staging"
STAGING_LABEL = "STAGING / NON-PRODUCTION"
_LEAK = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\w.-]+@[\w-]+\.[\w.]+|svc|tenant", re.I)


def default_view(views: list) -> dict:
    d = [v for v in views if v.get("DefaultView") and not v.get("PersonalView")]
    return d[0] if len(d) == 1 else {}


def _view_ok(views: list, lst: str) -> tuple:
    v = default_view(views)
    f = v.get("fields", [])
    if f != BUSINESS_FIELDS[lst]:
        return False, "%s default view fields %s" % (lst, f)
    return True, "%s default '%s': %s" % (lst, v.get("Title"), ", ".join(f))


def evaluate(ev: Mapping) -> dict:
    t = {}
    site = ev["expectedSite"]
    b, a = ev["before"], ev["after"]
    t["UX01"] = (ev.get("site") == site and all(m.get("target") == site for m in ev.get("mutations", [])), "exact STAGING target")
    t["UX02"] = (ev.get("mainMutations", 1) == 0, "MAIN untouched")
    t["UX03"] = (ev.get("productionMutations", 1) == 0, "Production untouched")
    home = ev.get("homeRender", {})
    text = home.get("text", "")
    t["UX04"] = (home.get("ok") is True and "AccessDenied" not in home.get("url", "") and a.get("welcomePage") == ev.get("newHomePage"),
                 "home page opens for the authorised reviewer")
    t["UX05"] = (HOME_TITLE in text, "title present")
    t["UX06"] = (STAGING_LABEL in text and not _LEAK.search(ev.get("homeContent", "")), "staging label present; no identifiers on the page")
    nav = [n["Title"] for n in a.get("quickLaunch", [])]
    links = ev.get("homeLinks", [])
    for n, lst in zip(("UX07", "UX08", "UX09", "UX10"), MASTER_LISTS):
        r = ev.get("listRender", {}).get(lst, {})
        t[n] = (lst in nav and any(l.rstrip("/").endswith("/Lists/" + lst) for l in links) and r.get("ok") is True,
                "%s: nav + home link + list opens" % lst)
    t["UX11"] = (nav == NAV_TARGET, "navigation = %s" % nav)
    removed = {n["Title"] for n in b.get("quickLaunch", [])} - set(nav)
    t["UX12"] = (removed <= NAV_NOISE and not any(NOT_PROMOTED.search(x) for x in nav) and not any(NOT_PROMOTED.search(l) for l in links),
                 "links removed: %s" % sorted(removed))
    bl, al = {l["title"]: l for l in b["lists"]}, {l["title"]: l for l in a["lists"]}
    t["UX13"] = (set(bl) <= set(al), "every library / list still exists")
    t["UX14"] = _view_ok(a["views"]["Employees"], "Employees")
    ef = set(default_view(a["views"]["Employees"]).get("fields", []))
    tech_kept = any(v.get("Title") == "All Items" and v.get("fields") == bv.get("fields")
                    for v in a["views"]["Employees"] for bv in b["views"]["Employees"] if bv.get("Title") == "All Items")
    t["UX15"] = (not (ef & TECHNICAL_FIELDS) and tech_kept, "no technical columns in default; technical view preserved")
    for n, lst in (("UX16", "Departments"), ("UX17", "Disciplines"), ("UX18", "Positions")):
        t[n] = _view_ok(a["views"][lst], lst)
    t["UX19"] = (ev.get("permissionsUnchanged") is True, "web / list role assignments, role definitions, groups unchanged")
    t["UX20"] = (ev.get("businessDataUnchanged") is True, "master and employee rows unchanged")
    t["UX21"] = (ev.get("schemaUnchanged") is True, "fields of the master lists unchanged")
    t["UX22"] = (ev.get("pocMasterStillPass") is True, "POC-MASTER-01 security behaviour re-verified")
    ok = all(v[0] for v in t.values())
    return {"tests": {k: ("PASS" if v[0] else "FAIL", v[1]) for k, v in sorted(t.items())}, "pass": ok,
            "score": "%d/22" % sum(v[0] for v in t.values())}
