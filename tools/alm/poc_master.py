"""POC-MASTER-01 evaluator — master data + employee identity + permission foundation (generic; no tenant data).

evaluate(evidence) -> {"tests": {PM01..PM20: (PASS|FAIL, reason)}, "pass": bool, "score": "n/20", "foundation": {...}}

The evidence record is built from live read-only inventories and the user-session probes (private evidence). Rules:
  * every probe is a non-writing attempt; a 2xx probe is a PERMISSION_BOUNDARY_FAILURE (POC FAIL, never compensated).
  * a probe answered 403 is DENIED. A non-writing probe answered otherwise (412 stale ETag, 404, ...) is INCONCLUSIVE and
    counts only when server-side item-level effective permissions prove the right is absent on EVERY item of the list
    (used for DELETE on real master rows, where a destructive attempt is not allowed).
  * identity: exactly one ACTIVE Employees row for the normalized UPN, else UNMAPPED_IDENTITY / DUPLICATE_IDENTITY /
    INACTIVE_EMPLOYEE (never weakened).
  * the service identity must hold exactly the approved minimum on the protected lists and never Full Control / Delete /
    Manage Permissions / Manage Lists.
POC-MASTER-01 PASS is a foundation result only: Power App, Power Automate, Timesheet CRUD, UAT and Production stay NOT DONE.
"""
from __future__ import annotations

from typing import Mapping

MASTER = ("Departments", "Disciplines", "Positions")
PROTECTED = MASTER + ("Employees",)
FORBIDDEN_RIGHTS = {"DeleteListItems", "ManageLists", "ManagePermissions", "FullMask"}
ALLOWED_MUTATIONS = {"DEMO_EMPLOYEE_ROW", "GROUP_MEMBERSHIP"}
LATER_STAGES = ("POWER_APP_INTEGRATION", "POWER_AUTOMATE_INTEGRATION", "TIMESHEET_CRUD", "UAT", "PRODUCTION")
DEMO_MARKER = "DEMO_ONLY"


def resolve_identity(rows: list) -> tuple:
    """(status, row). rows = Employees rows whose AccountUpn equals the normalized UPN."""
    if not rows:
        return "UNMAPPED_IDENTITY", None
    if len(rows) > 1:
        return "DUPLICATE_IDENTITY", None
    if rows[0].get("active") is not True:
        return "INACTIVE_EMPLOYEE", rows[0]
    return "RESOLVED", rows[0]


def probe_verdict(status: int) -> str:
    return "DENIED" if status == 403 else "ALLOWED" if 200 <= status < 300 else "INCONCLUSIVE"


def _denied(ev: Mapping, lst: str, op: str) -> tuple:
    ps = [p for p in ev.get("probes", []) if p["list"] == lst and p["op"] == op]
    if not ps:
        return False, "%s %s: not probed" % (lst, op)
    vs = [probe_verdict(p["status"]) for p in ps]
    if "ALLOWED" in vs:
        return False, "%s %s: PERMISSION_BOUNDARY_FAILURE" % (lst, op)
    if "DENIED" in vs:
        return True, "%s %s: 403" % (lst, op)
    eff = ev.get("itemEffective", {}).get(lst)
    right = {"CREATE": "add", "EDIT": "edit", "DELETE": "delete"}[op]
    if eff and eff.get("items", 0) > 0 and eff.get(right) == 0:
        return True, "%s %s: non-writing probe inconclusive; right absent on all %d items" % (lst, op, eff["items"])
    return False, "%s %s: inconclusive" % (lst, op)


def _all(results: list) -> tuple:
    bad = [r for ok, r in results if not ok]
    return (not bad), "; ".join(bad) if bad else "; ".join(r for _, r in results)


def evaluate(ev: Mapping) -> dict:
    t = {}
    staging = ev["expectedSite"]
    t["PM01"] = (ev.get("site") == staging and all(m.get("target") == staging for m in ev.get("mutations", []) if m.get("kind") != "GROUP_MEMBERSHIP"),
                 "exact STAGING target and every SharePoint mutation target")
    for n, lst in zip(("PM02", "PM03", "PM04", "PM05"), PROTECTED):
        l = ev.get("lists", {}).get(lst)
        t[n] = (bool(l) and l.get("exists") is True and l.get("uniquePermissions") is True and l.get("itemCount", 0) > 0,
                "%s exists with unique permissions" % lst)
    integ = ev.get("integrity", {})
    t["PM06"] = (integ.get("brokenLookups", 1) == 0 and integ.get("missingDepartment", 1) == 0 and integ.get("missingDiscipline", 1) == 0,
                 "required lookups valid; optional-Position gaps are classified anomalies")
    status, row = resolve_identity(ev.get("identityRows", []))
    t["PM07"] = (status == "RESOLVED", status)
    refs = ev.get("identityRefs", {})
    for n, k in (("PM08", "Department"), ("PM09", "Discipline"), ("PM10", "Position")):
        r = refs.get(k)
        t[n] = (row is not None and bool(r) and r.get("active") is True, "%s resolves to an existing active row" % k)
    reads = ev.get("userReads", {})
    t["PM11"] = (all(reads.get(l) == 200 for l in PROTECTED), "user reads all protected lists")
    for n, op in (("PM12", "CREATE"), ("PM13", "EDIT"), ("PM14", "DELETE")):
        t[n] = _all([_denied(ev, l, op) for l in MASTER])
    t["PM15"] = _all([_denied(ev, "Employees", op) for op in ("CREATE", "EDIT", "DELETE")])
    svc = ev.get("serviceRights", {})
    approved = ev.get("serviceApproved", {})
    svc_ok = all(set(svc.get(l, [])) == set(approved.get(l, [])) for l in PROTECTED) and \
        not any(FORBIDDEN_RIGHTS & set(svc.get(l, [])) for l in PROTECTED)
    user_fc = any(FORBIDDEN_RIGHTS & set(ev.get("userRights", {}).get(l, [])) for l in PROTECTED)
    t["PM16"] = (svc_ok and not user_fc, "service = approved minimum; no Full Control / Delete / Manage for user or service")
    ch = ev.get("change", {})
    t["PM17"] = (ch.get("preExistingRowsChanged", 1) == 0 and ch.get("otherListsChanged", 1) == 0 and ch.get("schemaOrPermissionChanged", 1) == 0,
                 "no pre-existing row, other list, schema or permission changed")
    t["PM18"] = (ev.get("mainMutations", 1) == 0, "MAIN untouched")
    t["PM19"] = (ev.get("productionMutations", 1) == 0, "Production untouched")
    muts = ev.get("mutations", [])
    kinds = [m["kind"] for m in muts]
    t["PM20"] = (set(kinds) <= ALLOWED_MUTATIONS and kinds.count("DEMO_EMPLOYEE_ROW") <= 1 and kinds.count("GROUP_MEMBERSHIP") <= 1
                 and all(m.get("marker") == DEMO_MARKER for m in muts if m["kind"] == "DEMO_EMPLOYEE_ROW"),
                 "only the DEMO_ONLY row and the one approved membership")
    ok = all(v[0] for v in t.values())
    return {"tests": {k: ("PASS" if v[0] else "FAIL", v[1]) for k, v in sorted(t.items())},
            "pass": ok, "score": "%d/20" % sum(v[0] for v in t.values()),
            "foundation": dict({"POC-MASTER-01": "PASS" if ok else "FAIL"}, **{s: "NOT DONE" for s in LATER_STAGES})}
