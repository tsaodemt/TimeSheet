"""POC-TIMESHEET-01 evaluator — SharePoint Draft CRUD through the service data path, ownership and ETag concurrency
(generic; no tenant data).

evaluate(evidence) -> {"tests": {PT01..PT30: (PASS|FAIL, reason)}, "warnings": {...}, "pass": bool, "score": "n/30", "scope": {...}}

The evidence record is built from live inventories, the service-path run and the denial probes (private evidence). Rules:
  * ownership is OwnerUpn from the trusted caller; request-supplied owner / employee / actor / status are ignored;
  * ReadOwn is bounded (both dates), filters OwnerUpn first, excludes Deleted, orders by Id; a foreign row in the result is
    a leak (FAIL), and the foreign row must provably exist in the same range (else isolation is not shown);
  * WorkDate: business date -> local midnight in UTC; a range is the half-open UTC interval (never truncated UTC);
  * a stale ETag must be rejected by SharePoint (412) and leave the item unchanged; the contract maps it to CONFLICT;
  * ordinary users have no direct access to TimesheetEntries; the service has Read / Add / Edit only (never Delete,
    Manage Lists, Manage Permissions, Full Control); a 2xx denial probe is a boundary failure;
  * warning checks (entry > 4 h, day > 12 h) are reported separately and are not part of PT01-PT30.
PASS is a backend / data-path result only: caller-identity propagation, AppStart and deployed flows stay NOT PROVEN.
"""
from __future__ import annotations

import re
from typing import Mapping

REF = {"Phases": 2, "WorkTypes": 2, "Shifts": 1, "HourTypes": 1}
PROJECT_ROWS = {"Projects": 1, "ProjectPhases": 2}
APPROVED_INDEXES = {"OwnerUpn", "WorkDate", "LegacyId", "Employee", "Project", "EmployeeItemId", "PeriodKey", "DisciplineCode"}
FORBIDDEN_COLUMNS = {"ApprovalStatus", "IsDeleted", "RequestKey"}
GATED_COLUMNS = {"LegacyModifiedBy", "SortOrder", "ApprovedBy", "ApprovedOn", "LegacyApprovalInfo", "DataQualityFlags"}
STATUS_CHOICES = ["Draft", "Approved", "Deleted"]
NEVER = {"DeleteListItems", "ManageLists", "ManagePermissions", "FullMask"}
SERVICE_ENTRY_RIGHTS = {"ViewListItems", "AddListItems", "EditListItems"}
FORGED = {"OwnerUpn", "EmployeeId", "ActorUpn", "EntryStatus"}
DEMO_MARKER = "DEMO_ONLY"
MUTATION_KINDS = {"SCHEMA", "PERMISSION", "DEMO_ROW", "ENTRY_CREATE", "ENTRY_EDIT", "FIXTURE_ROW", "FIXTURE_CLEANUP", "NAV_REPAIR"}
NOT_PROVEN = ("POWER_APPS_CALLER_IDENTITY", "POWER_AUTOMATE_RUN_ONLY_IDENTITY", "APPSTART", "DEPLOYED_TS_READOWN",
              "DEPLOYED_TS_SAVEENTRY", "CUSTOMER_UI")
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _denied(status) -> bool:
    return status in (403, 404)  # 404 = the list is not visible to the identity at all


def _schema_ok(s: Mapping) -> bool:
    return bool(s) and s.get("exists") is True and s.get("blocked", 1) == 0 and s.get("secondPlanOps", 1) == 0 and not s.get("missingRequired")


def evaluate(ev: Mapping) -> dict:
    t = {}
    st = ev["expectedSite"]
    muts = ev.get("mutations", [])
    t["PT01"] = (ev.get("site") == st and all(m.get("target") == st for m in muts) and {m.get("kind") for m in muts} <= MUTATION_KINDS,
                 "exact STAGING target for the site and every mutation (%d)" % len(muts))
    rows = ev.get("identityRows", [])
    one = len(rows) == 1 and rows[0].get("active") is True
    t["PT02"] = (one and all(r.get("active") is True for r in ev.get("identityRefs", {}).values()) and len(ev.get("identityRefs", {})) == 3,
                 "AccountUpn -> exactly one active Employees row; Department / Discipline / Position active")
    sch = ev.get("schema", {})
    t["PT03"] = (all(_schema_ok(sch.get(l)) for l in REF), "reference schemas present, 0 incompatible")
    dr = ev.get("demoRows", {})
    t["PT04"] = (all(len(dr.get(l, [])) == n and all(r.get("marker") == DEMO_MARKER and str(r.get("legacyId", "")).startswith("DEMO-")
                                                       for r in dr.get(l, [])) for l, n in REF.items()) and ev.get("demoValidate") == [],
                 "DEMO_ONLY reference rows %s" % {l: len(dr.get(l, [])) for l in REF})
    t["PT05"] = (_schema_ok(sch.get("Projects")), "Projects schema = target")
    pp = sch.get("ProjectPhases") or {}
    t["PT06"] = (_schema_ok(pp) and pp.get("lookups") == {"Project": "Projects", "Phase": "Phases"}, "ProjectPhases schema = target, lookups")
    rel = ev.get("projectRelations", [])
    t["PT07"] = (all(len(dr.get(l, [])) == n and all(r.get("marker") == DEMO_MARKER for r in dr.get(l, [])) for l, n in PROJECT_ROWS.items())
                 and len(rel) == 2 and all(r.get("projectIsDemo") and r.get("phaseIsDemo") for r in rel),
                 "1 DEMO project + 2 DEMO project/phase relations")
    te = ev.get("entriesSchema", {})
    cols = te.get("columns", {})
    t["PT08"] = (cols == te.get("expectedColumns") and not (set(cols) & (FORBIDDEN_COLUMNS | GATED_COLUMNS))
                 and te.get("entryStatusChoices") == STATUS_CHOICES and te.get("entryStatusDefault") == "Draft" and _schema_ok(sch.get("TimesheetEntries")),
                 "TimesheetEntries = approved Phase 1 schema (%d columns)" % len(cols))
    idx = {c for c, v in cols.items() if v.get("indexed")}
    t["PT09"] = (idx == APPROVED_INDEXES and "EntryStatus" not in idx, "indexes = approved 8: %s" % sorted(idx))
    p = ev.get("entriesPermissions", {})
    t["PT10"] = (p.get("unique") is True and p.get("ra") == {"owners": ["Full Control"], "siteAdmin": ["Full Control"], "service": ["TS Service"]}
                 and not any(p.get("eff", {}).get(k) for k in ("user", "employees", "visitors", "members")),
                 "unique; Owners FC + site admin + service TS Service only; no ordinary access")
    sr = ev.get("serviceReads", {})
    req = ev.get("serviceReadRequired", [])
    t["PT11"] = (bool(req) and all(sr.get(l) == ["ViewListItems"] for l in req) and all(not sr.get(l) for l in ev.get("serviceReadNotRequired", []))
                 and ev.get("guardProjectionStatus") == 200, "service Read exactly on %s; none elsewhere" % req)
    c = ev.get("create", {})
    t["PT12"] = (c.get("ok") is True and c.get("code") == "OK" and c.get("path") == "service" and ev.get("entriesCreated", 99) <= 2,
                 "Draft created through the service data path")
    a = ev.get("rowA", {})
    t["PT13"] = (a.get("ownerIsCaller") is True and a.get("employeeIsCaller") is True and a.get("status") == "Draft"
                 and a.get("marker") == DEMO_MARKER and bool(_GUID.match(str(a.get("legacyId", "")))) and FORGED <= set(c.get("ignoredInputs", [])),
                 "OwnerUpn / Employee from the trusted caller; forged inputs ignored")
    w = ev.get("workDate", {})
    t["PT14"] = (w.get("stored") == w.get("expectedUtc") and w.get("business") == w.get("requested") and a.get("id") in w.get("sameDay", [])
                 and a.get("id") not in w.get("dayBefore", [1]) + w.get("dayAfter", [1]), "local midnight UTC; half-open day bounds")
    r = ev.get("readOwn", {})
    bounded = len(r.get("range", [])) == 2 and all(r["range"])
    t["PT15"] = (r.get("ok") is True and bounded and a.get("id") in r.get("ids", []) and r.get("ordered") is True, "bounded ReadOwn returns own Draft")
    b = ev.get("rowB", {})
    t["PT16"] = (b.get("id") not in r.get("ids", []) and b.get("id") in ev.get("foreignInRange", []) and r.get("allOwnedByCaller") is True
                 and ev.get("foreignRequest", {}).get("code") == "FORBIDDEN", "foreign Draft excluded (and present in range)")
    u = ev.get("userProbes", {})
    t["PT17"] = (all(_denied(u.get(op)) for op in ("READ", "CREATE", "EDIT", "DELETE")) and not ev.get("userEntryRights"),
                 "direct user access denied %s" % u)
    e = ev.get("edit", {})
    t["PT18"] = (e.get("ok") is True and e.get("hoursReadback") == e.get("hoursSent") and e.get("ownerUnchanged") is True and e.get("status") == "Draft",
                 "own Draft edited with the current ETag")
    t["PT19"] = (bool(e.get("etagBefore")) and e.get("etagAfter") not in (None, "", e.get("etagBefore")), "ETag changed after edit")
    s = ev.get("stale", {})
    t["PT20"] = (s.get("sharepointStatus") == 412 and s.get("contractCode") == "CONFLICT" and s.get("unchanged") is True,
                 "stale ETag rejected (SharePoint %s -> CONFLICT), item unchanged" % s.get("sharepointStatus"))
    svc = set(ev.get("serviceEntryRights", []))
    t["PT21"] = ("DeleteListItems" not in svc and ev.get("serviceDeleteProbe") == 403, "service: no Delete (live probe %s)" % ev.get("serviceDeleteProbe"))
    t["PT22"] = (not (svc & NEVER) and SERVICE_ENTRY_RIGHTS <= svc, "service: Read/Add/Edit; no Full Control / Manage")
    m = ev.get("master", {})
    t["PT23"] = (m.get("rowsUnchanged") is True and m.get("fieldsUnchanged") is True and set(m.get("permissionDeltas", [])) <= set(ev.get("approvedDeltas", [])),
                 "master foundation unchanged except approved deltas %s" % m.get("permissionDeltas"))
    t["PT24"] = (ev.get("preExistingRowsChanged", 1) == 0, "no pre-existing business row changed")
    for n, k in (("PT25", "mainMutations"), ("PT26", "productionMutations"), ("PT27", "powerPlatformMutations"), ("PT28", "entraMutations")):
        t[n] = (ev.get(k, 1) == 0, "%s = 0" % k)
    t["PT29"] = (ev.get("pocMasterPass") is True, "POC-MASTER-01 re-verified")
    t["PT30"] = (ev.get("stagingUxPass") is True, "STAGING-UX-01 re-verified")
    ok = all(v[0] for v in t.values())
    wr = ev.get("warnings", {})

    def wv(code):
        x = wr.get(code)
        return "NOT RUN" if not x else "PASS" if x.get("raised") and x.get("writeSucceeded") else "FAIL"
    return {"tests": {k: ("PASS" if v[0] else "FAIL", v[1]) for k, v in sorted(t.items())}, "pass": ok,
            "score": "%d/30" % sum(v[0] for v in t.values()),
            "warnings": {"ENTRY > 4 HOURS": wv("WARN_HOURS_ENTRY"), "DAY > 12 HOURS": wv("WARN_HOURS_DAY")},
            "scope": dict({"POC-TIMESHEET-01": "PASS" if ok else "FAIL"}, **{x: "NOT PROVEN" for x in NOT_PROVEN})}
