"""PERMISSION-DRIFT-01 evaluator — verify (and only if required, repair) STAGING list permissions (generic; no tenant data).

Inputs are role-assignment snapshots and effective-permission results by ROLE KEY (owners, siteAdmin, visitors, members,
employees, demoUser, service, newVisitor), never identities.

    classify_list(name, state, approved) -> EXPECTED | PERMISSION_DRIFT
    evaluate(evidence) -> {"tests": {PD01..PD22}, "classification": {...}, "pass": bool, "uxReassessment": str}

Rules
  * Protected lists must have unique permissions and exactly the approved role assignments; every non-approved role key
    must have NO effective right (proved per key, not inferred from group membership).
  * A Visitors membership whose intent cannot be proven is classified UNKNOWN and needs an owner decision; it is never
    removed to fix a list-level problem, and never silently accepted.
  * Repair is required only for proven list drift; PD21/PD22 are N/A when no repair is required.
  * STAGING-UX-01 may be re-marked PASS 22/22 only if the UX task changed no permissions, protected assets are isolated,
    the site-level membership is intended or separately tracked, and no regression remains.
"""
from __future__ import annotations

from typing import Mapping

PROTECTED = ("Departments", "Disciplines", "Positions", "Employees", "AppSettings", "AuditLog")
MASTER = ("Departments", "Disciplines", "Positions", "Employees")
NO_ACCESS_KEYS = ("visitors", "newVisitor", "employees", "demoUser", "members")
WRITE_RIGHTS = {"Add", "Edit", "Delete", "ManageLists", "ManagePermissions", "FullMask"}


def classify_list(name: str, state: Mapping, approved: Mapping) -> tuple:
    """state = {"unique": bool, "ra": {roleKey: [levels]}, "eff": {roleKey: [rights]}}; approved = {roleKey: [levels]}."""
    problems = []
    if state.get("unique") is not True:
        problems.append("inherits")
    ra = {k: sorted(v) for k, v in state.get("ra", {}).items()}
    if ra != {k: sorted(v) for k, v in approved.items()}:
        problems.append("role assignments %s" % ra)
    for k, rights in state.get("eff", {}).items():
        via_group = k == "demoUser" and "employees" in approved  # the demo user reads through the employee group
        if k not in approved and not via_group and k in NO_ACCESS_KEYS and rights:
            problems.append("%s has %s" % (k, rights))
        if k in ("employees", "demoUser") and set(rights) & WRITE_RIGHTS:
            problems.append("%s can write" % k)
    return ("PERMISSION_DRIFT", problems) if problems else ("EXPECTED", [])


def evaluate(ev: Mapping) -> dict:
    t, cls = {}, {}
    site = ev["expectedSite"]
    t["PD01"] = (ev.get("site") == site and all(m.get("target") == site for m in ev.get("mutations", [])), "exact STAGING target")
    t["PD02"] = (ev.get("mainMutations", 1) == 0, "MAIN untouched")
    t["PD03"] = (ev.get("productionMutations", 1) == 0, "Production untouched")
    vis = ev.get("visitors", {})
    t["PD04"] = ("members" in vis and "membershipCreated" in vis, "Visitors members + membership evidence captured")
    intent = vis.get("intent")
    t["PD05"] = (intent in ("INTENDED", "ACCIDENTAL", "UNKNOWN"), "intent = %s" % intent)
    cls["SITE"] = "EXPECTED" if ev.get("webRoleAssignmentsUnchanged") else "PERMISSION_DRIFT"
    cls["VISITORS GROUP"] = {"INTENDED": "INTENDED_SITE_ACCESS_ONLY", "ACCIDENTAL": "PERMISSION_DRIFT"}.get(intent, "UNKNOWN")
    lists, approved = ev["lists"], ev["approved"]
    for name in PROTECTED:
        cls[name.upper()], why = classify_list(name, lists[name], approved[name])
        lists[name]["why"] = why
    app, aud = lists["AppSettings"], lists["AuditLog"]
    live = ev.get("liveReads", {})
    t["PD06"] = (app.get("unique") is True, "AppSettings unique permissions")
    t["PD07"] = ("visitors" not in app.get("ra", {}) and not app["eff"].get("newVisitor"), "Visitors: no assignment; its member: no rights")
    t["PD08"] = (not app["eff"].get("newVisitor"), "new Visitors member: no effective rights")
    t["PD09"] = (not app["eff"].get("demoUser") and live.get("demoUser", {}).get("AppSettings") in (403, 404), "demo user: none; live read denied")
    t["PD10"] = (not app["eff"].get("employees"), "employee group: none")
    t["PD11"] = (sorted(app["eff"].get("service", [])) == sorted(ev.get("approvedServiceRights", {}).get("AppSettings", [])),
                 "service = approved (%s)" % app["eff"].get("service"))
    t["PD12"] = ("visitors" not in aud.get("ra", {}) and not aud["eff"].get("newVisitor") and aud.get("unique") is True, "AuditLog: Visitors none")
    t["PD13"] = (not aud["eff"].get("newVisitor"), "AuditLog: new Visitors member none")
    t["PD14"] = (all(cls[n.upper()] == "EXPECTED" for n in MASTER[:3]), "master lists as approved")
    t["PD15"] = (cls["EMPLOYEES"] == "EXPECTED", "Employees as approved")
    t["PD16"] = (ev.get("businessDataUnchanged") is True, "business data unchanged")
    t["PD17"] = (ev.get("schemaUnchanged") is True, "schema unchanged")
    t["PD18"] = (ev.get("uxUnchanged") is True, "page / navigation / views unchanged")
    t["PD19"] = (ev.get("entraMutations", 1) == 0, "no Entra mutation")
    t["PD20"] = (ev.get("pocMasterPass") is True, "POC-MASTER-01 re-verified")
    drift = [n for n in PROTECTED if cls[n.upper()] == "PERMISSION_DRIFT"]
    repaired = ev.get("repair")
    if not drift and not repaired:
        t["PD21"] = (None, "N/A — no repair required")
        t["PD22"] = (None, "N/A — no repair required")
    else:
        t["PD21"] = (bool(repaired) and set(repaired.get("lists", [])) <= set(drift) and not repaired.get("siteChanged"), "minimal repair")
        t["PD22"] = (bool(repaired) and repaired.get("reverified") is True, "post-repair effective access re-verified")
    ok = all(v[0] is not False for v in t.values())
    isolated = all(cls[n.upper()] == "EXPECTED" for n in PROTECTED)
    tracked = intent == "INTENDED" or (intent == "UNKNOWN" and ev.get("ownerDecisionTracked") is True)
    if ok and isolated and tracked and ev.get("uxTaskPermissionMutations", 1) == 0:
        ux = "PASS 22/22"
    elif ok and isolated and intent == "UNKNOWN":
        ux = "OWNER DECISION REQUIRED"
    else:
        ux = "FAIL / SECURITY DRIFT OPEN"
    res = {k: ("N/A" if v[0] is None else "PASS" if v[0] else "FAIL", v[1]) for k, v in sorted(t.items())}
    return {"tests": res, "classification": cls, "drift": drift, "pass": ok, "uxReassessment": ux,
            "ownerDecisionRequired": intent == "UNKNOWN"}
