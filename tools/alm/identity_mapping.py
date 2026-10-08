"""EMPLOYEE-IDENTITY-MAPPING-01 evaluator — read-only Employees <-> directory account matching (generic; no tenant data).

evaluate(evidence) -> {"tests": {IM01..IM24: (PASS|FAIL, reason)}, "pass": bool, "score": "n/24"}

The evidence record is built privately from the live read captures and tools/identity/employee_matching.match(). Rules:
  * the SharePoint target must resolve to the configured STAGING site; every SharePoint request is a GET (search
    included); Employees fingerprints before == after, or every difference is an added row proven out-of-band
    (provenance recorded, not attributed to the task) with no pre-existing row changed or removed;
  * directory data is read through navigation / DOM reads only; zero directory, group or Power Platform mutations;
  * the demo row is excluded from the real-employee totals; every real employee gets exactly one operational class;
  * AUTO_MATCH_SAFE is granted only when employee_matching.safe_violations() is empty — name, accent-folded name and
    e-mail-pattern evidence alone never qualify; disabled, guest and service/test accounts never qualify;
  * no proposed UPN is shared by two employees or collides with an existing AccountUpn (demo rows included);
  * AccountUpn must be Indexed and Unique (verified live, not changed);
  * the public repository must contain no real UPN / name from the private capture (scanned before commit).
PASS means "analysis complete" only: no mapping is applied, no group changed, no account created.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Mapping

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "identity"))
from employee_matching import (  # noqa: E402
    AMBIGUOUS, AUTO_MATCH_SAFE, CLASSES, EXCLUDED_DEMO, GUEST, INACTIVE_EMPLOYEE, MEMBER_DISABLED, MEMBER_ENABLED,
    NEEDS_REVIEW, NO_ACCOUNT, SERVICE_TEST, normalize, safe_violations)

TESTS = [f"IM{i:02d}" for i in range(1, 25)]
REAL_CLASSES = set(CLASSES) - {EXCLUDED_DEMO}


def _proposed(rows):
    return [r for r in rows if r["classification"] in (AUTO_MATCH_SAFE, NEEDS_REVIEW) and r["candidate"]
            and not r["currentAccountUpn"]]


def evaluate(ev: Mapping) -> dict:
    m = ev["match"]
    rows = m["rows"]
    real = [r for r in rows if r["classification"] != EXCLUDED_DEMO]
    demo = [r for r in rows if r["classification"] == EXCLUDED_DEMO]
    kinds = m["accountKinds"]
    safe = [r for r in real if r["classification"] == AUTO_MATCH_SAFE]
    t = {}

    tgt = ev["target"]
    t["IM01"] = (normalize(tgt["resolvedUrl"]).rstrip("/") == normalize(tgt["expectedUrl"]).rstrip("/")
                 and normalize(tgt["resolvedUrl"]).rstrip("/") != normalize(tgt["mainUrl"]).rstrip("/")
                 and tgt.get("employeesListFound") is True, "resolved web == configured STAGING, not MAIN")

    methods = Counter(x["method"].upper() for x in ev["spRequests"])
    # Before/after differences are allowed only when each one is a proven out-of-band change (provenance outside
    # every task request window, not attributed to the task) and no pre-existing row changed or disappeared.
    diff = ev.get("employeesDiff") or {"added": [], "removed": [], "changed": []}
    ext = {x["itemId"] for x in ev.get("externalChanges", []) if x.get("attributedToTask") is False
           and x.get("provenance")}
    unchanged = ev["employeesBefore"] == ev["employeesAfter"]
    explained = not diff["removed"] and not diff["changed"] and set(diff["added"]) <= ext and bool(diff["added"])
    t["IM02"] = (set(methods) <= {"GET"} and (unchanged or explained),
                 f"SharePoint methods {dict(methods)}; Employees "
                 + ("unchanged" if unchanged else f"+{len(diff['added'])} out-of-band row(s), not by this task"))

    ent = ev["entra"]
    # MENU_OPEN_NO_ITEM: a toolbar menu was opened and closed with no item invoked and no row selected (not a write).
    t["IM03"] = (ent["mutations"] == 0 and ent.get("menuItemsInvoked", 0) == 0 and ent.get("rowsSelected", 0) == 0
                 and set(ent["actionKinds"]) <= {"NAV", "DOM_READ", "SCROLL", "ESCAPE", "MENU_OPEN_NO_ITEM"}
                 and ent["directoryBefore"] == ent["directoryAfter"],
                 f"directory actions {sorted(set(ent['actionKinds']))}; 0 mutations")

    t["IM04"] = (len(demo) == ev["expectedDemoRows"]
                 and all(r["reasons"] in (["DEMO_ONLY"], ["UNBATCHED_TEST_ROW"]) for r in demo)
                 and sum(r["reasons"] == ["DEMO_ONLY"] for r in demo) >= 1
                 and len(real) == ev["expectedRealEmployees"], f"{len(demo)} demo/test row(s) excluded")

    t["IM05"] = (len(real) == ev["expectedRealEmployees"] and len(rows) == ev["employeeRowsLive"]
                 and all(r["classification"] in REAL_CLASSES for r in real),
                 f"{len(real)}/{ev['expectedRealEmployees']} real employees classified")

    act = [r for r in real if r["active"]]
    ina = [r for r in real if not r["active"]]
    t["IM06"] = (len(act) + len(ina) == len(real) and all(r["classification"] == INACTIVE_EMPLOYEE for r in ina)
                 and not any(r["classification"] == INACTIVE_EMPLOYEE for r in act)
                 and (len(act), len(ina)) == tuple(ev["expectedActiveInactive"]),
                 f"active {len(act)} / inactive {len(ina)}")

    d = m["summary"]["directory"]
    t["IM07"] = (d["total"] > 0 and ent["readOnly"] is True and len(kinds) == d["total"]
                 and ent.get("crossCheckTotal") in (None, d["total"]),
                 f"{d['total']} directory accounts collected read-only")

    excl = set(ev.get("configuredExclusions", []))
    t["IM08"] = (all(kinds[o] == SERVICE_TEST for o in excl)
                 and not any(r["candidate"] and r["candidate"]["kind"] == SERVICE_TEST for r in _proposed(real)),
                 f"{d['serviceTestExcluded']} service/test/admin identities excluded")

    dup_e = {i for g in m["conflicts"]["duplicateEmployeeNames"] for i in g}
    t["IM09"] = ("duplicateEmployeeNames" in m["conflicts"]
                 and all(r["classification"] in (AMBIGUOUS, INACTIVE_EMPLOYEE) for r in real if r["itemId"] in dup_e),
                 f"{len(m['conflicts']['duplicateEmployeeNames'])} duplicate employee-name group(s)")

    dup_d = {i for g in m["conflicts"]["duplicateDirectoryNames"] for i in g}
    t["IM10"] = ("duplicateDirectoryNames" in m["conflicts"]
                 and not any(r["candidate"]["objectId"] in dup_d for r in safe),
                 f"{len(m['conflicts']['duplicateDirectoryNames'])} duplicate directory-name group(s)")

    multi = [r for r in real if "MULTIPLE_DIRECTORY_CANDIDATES" in r["reasons"]]
    t["IM11"] = (all((r["classification"] == AMBIGUOUS and r["candidate"] is None) or
                     r["classification"] == INACTIVE_EMPLOYEE for r in multi),
                 f"{len(multi)} multiple-candidate case(s) left AMBIGUOUS")

    t["IM12"] = (not any(r["candidate"]["kind"] == MEMBER_DISABLED for r in safe)
                 and not any(r["classification"] == AUTO_MATCH_SAFE for r in real
                             if "DIRECTORY_ACCOUNT_DISABLED" in r["reasons"]), "disabled accounts never SAFE")

    t["IM13"] = (not any(r["candidate"]["kind"] == GUEST for r in safe)
                 and not any(r["candidate"] and r["candidate"]["kind"] == GUEST for r in _proposed(real)),
                 "guest accounts never SAFE / proposed")

    prop = Counter(normalize(r["candidate"]["upn"]) for r in _proposed(rows))
    existing = {normalize(r["currentAccountUpn"]) for r in rows if r["currentAccountUpn"]}
    t["IM14"] = (all(n == 1 for n in prop.values()) and not (set(prop) & existing),
                 f"{len(prop)} proposed UPN(s), 0 shared, 0 clash with existing values")

    mapped = [r for r in real if r["currentAccountUpn"]]
    t["IM15"] = (all(r["mappedState"] for r in mapped) and len(mapped) == m["summary"]["accountUpnPopulated"]
                 and ev["accountUpnWrites"] == 0, f"{len(mapped)} existing real AccountUpn value(s) verified")

    s = ev["schema"]["AccountUpn"]
    t["IM16"] = (s["Indexed"] is True and s["EnforceUniqueValues"] is True, "AccountUpn Indexed + Unique (live)")

    t["IM17"] = (all(safe_violations(r) == [] and r["candidate"]["kind"] == MEMBER_ENABLED for r in safe),
                 f"{len(safe)} AUTO_MATCH_SAFE row(s), every criterion enforced")

    amb = [r for r in real if r["classification"] == AMBIGUOUS]
    t["IM18"] = (not any(r in _proposed(real) for r in amb) and ev["mappingsApplied"] == 0,
                 f"{len(amb)} AMBIGUOUS row(s) unresolved, none proposed or applied")

    noacc = [r for r in real if r["classification"] == NO_ACCOUNT]
    t["IM19"] = (all(r["candidate"] is None for r in noacc) and ev["usersCreated"] == 0,
                 f"{len(noacc)} NO_ACCOUNT row(s), 0 users created")

    pa = ev["privateArtifacts"]
    t["IM20"] = (all(pa["exists"].values()) and pa["gitIgnored"] is True, f"{len(pa['exists'])} private artefact(s)")

    ps = ev["publicScan"]
    t["IM21"] = (ps["scannedFiles"] > 0 and ps["realUpnHits"] == 0 and ps["realNameHits"] == 0
                 and ps["tenantHits"] == 0, f"{ps['scannedFiles']} public file(s) scanned, 0 hits")

    t["IM22"] = (ev["powerPlatformMutations"] == 0, "0 Power Platform mutations")
    t["IM23"] = (ev["mainRequests"] == 0 and ev["mainMutations"] == 0, "MAIN not requested, not modified")
    t["IM24"] = (ev["productionRequests"] == 0 and ev["productionMutations"] == 0, "Production not touched")

    ok = all(v[0] for v in t.values()) and set(t) == set(TESTS)
    return {"tests": {k: ("PASS" if v[0] else "FAIL", v[1]) for k, v in sorted(t.items())}, "pass": ok,
            "score": f"{sum(1 for v in t.values() if v[0])}/{len(TESTS)}"}
