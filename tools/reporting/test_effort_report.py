"""R3 M4 current-scope reports: reference (effort_report) vs generated flows (build_report_flows) in the WDL simulator.
Tests RP01-RP16 (offline; synthetic data only)."""
import copy
import json
import os
import re
import sys
import unittest
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "effort"),
          os.path.join(HERE, "..", "approval"), os.path.join(HERE, "..", "registration")):
    sys.path.insert(0, p)
import build_report_flows as bf  # noqa: E402
import effort_report as ER  # noqa: E402
import guard as G  # noqa: E402
import pe_schema as ps  # noqa: E402
import rpt_rules as rr  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

NOW = "2026-10-10T01:02:03Z"
SITE = "https://tenant-a.invalid/sites/x"
KW = dict(role_groups=tg.ROLE_GROUPS, site=SITE, domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit", conf_audit_list="_ConfAudit",
          environment="STAGING")
PROJ, DISC = bf.project_report_actions(**KW), bf.discipline_report_actions(**KW)
POLICY = G.Policy.from_scope_config(rr.scope_config())
AUDIT_KEYS = ("EventType", "Action", "Decision", "ResultCode")
DISCS = {1: ("D-L1", "D1", "Disc 1"), 2: ("D-L2", "D2", "Disc 2"), 3: ("D-L3", "D3", "Disc 3")}
CODE2ID = {v[1]: k for k, v in DISCS.items()}
DENY_ALL = ("HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO")


def emp_row(e):
    did = CODE2ID.get(e.discipline_id)
    disc = {"Id": did, "LegacyId": DISCS[did][0], "DisciplineCode": DISCS[did][1], "Title": DISCS[did][2]} if did else None
    return {"Id": e.item_id, "LegacyId": e.legacy_id, "Title": "Name %s" % e.legacy_id, "IsActive": e.is_active, "Discipline": disc}


EMP_ROWS = {e.item_id: emp_row(e) for e in tg.EMPS}
ME = tg.u("peer")      # 12, D1
TL1 = tg.u("emp")      # 11, D1
FAR = tg.u("far")      # 13, D2


class Store:
    def __init__(self, *, pms=((1, 12), (2, 13)), allocs=((1, "QLP", 2.5), (1, "D:D-L1", 4), (1, "PM", None), (3, "D:D-L2", 3)),
                 m1=((1, 10), (1, None), (1, 0.5), (3, 2)),
                 regs=((1, "D1", 1.75, "ApprovedLocked"), (1, "D1", 0.75, "Draft"), (1, "D2", 1, "ApprovedLocked"), (3, "D1", 2, "ApprovedLocked"),
                       (3, "D2", None, "Draft")),
                 entries=((1, "D1", 8, "Approved"), (1, "D1", 8, "Approved"), (1, "D1", 8, "Draft"), (1, "D2", 4, "Approved"),
                          (2, "D2", 1.5, "Approved"), (2, "D2", 2, "Deleted")),
                 settings=None, fail=(), big=()):
        self.projects = [{"Id": i, "LegacyId": "PRJ-L%d" % i, "ProjectCode": "P%d" % i, "Title": "Project %d" % i} for i in (1, 2, 3)]
        self.pms = [{"Id": k + 1, "ProjectItemId": p, "PmEmployeeItemId": e} for k, (p, e) in enumerate(pms)]
        self.allocs = [{"Id": k + 1, "ProjectItemId": p, "RecipientKey": r, "Effort": v} for k, (p, r, v) in enumerate(allocs)]
        self.m1 = [{"Id": k + 1, "ProjectItemId": p, "ManDays": v} for k, (p, v) in enumerate(m1)]
        self.regs = [{"Id": k + 1, "ProjectItemId": p, "DisciplineCode": d, "Effort": v, "Status": st} for k, (p, d, v, st) in enumerate(regs)]
        self.entries = [{"Id": k + 1, "ProjectId": p, "DisciplineCode": d, "Hours": h, "EntryStatus": st} for k, (p, d, h, st) in enumerate(entries)]
        self.settings = {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "D1,D2"} if settings is None else settings
        self.fail, self.big = set(fail), set(big)


class Data:
    def __init__(self, s):
        self.s = s

    def _f(self, k):
        if k in self.s.fail:
            raise ConnectionError(k)

    def pm_assignments(self):
        self._f("pms")
        return self.s.pms

    def settings(self):
        return dict(self.s.settings)

    def projects(self):
        self._f("projects")
        return self.s.projects

    def allocations(self):
        self._f("allocs")
        return self.s.allocs

    def hour_registrations(self):
        self._f("m1")
        return self.s.m1

    def registrations(self):
        self._f("regs")
        return self.s.regs

    def disciplines(self):
        return [{"Id": k, "DisciplineCode": v[1], "Title": v[2]} for k, v in DISCS.items()]

    def employee(self, eid):
        e = EMP_ROWS.get(eid)
        return {"DisciplineCode": (e["Discipline"] or {}).get("DisciplineCode")} if e else None

    def approved_hours(self, pid):
        self._f("ts")
        rows = [(e["DisciplineCode"], e["Hours"]) for e in self.s.entries if e["ProjectId"] == pid and e["EntryStatus"] == "Approved"]
        return rows + [("D1", 0)] * (ER.PAGE + 1) if pid in self.s.big else rows


_EQ = re.compile(r"(\w+) eq (-?\d+)")


def mocks_for(upn, roles, s, posts, gets):
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        method, raw = p["parameters/method"], p["parameters/uri"]
        uri = unquote(raw)
        lst = re.search(r"getbytitle\('([^']*)'\)", uri).group(1)
        if lst in ("_Audit", "_ConfAudit"):
            posts.append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": len(posts)}
        assert method == "GET", (method, uri)
        gets.append(uri)
        conds = dict((k, int(v)) for k, v in _EQ.findall(uri.split("$filter=")[1].split("&")[0] if "$filter=" in uri else ""))
        m = re.search(r"/items\((-?\d+)\)", uri)
        if lst == tg.EMP_LIST:
            if "AccountUpn eq" in uri or "LegacyId eq" in uri:
                return "Succeeded", wdl_sim.sharepoint_get(raw, {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)})
            e = EMP_ROWS.get(int(m.group(1)))
            return ("Succeeded", copy.deepcopy(e)) if e else ("Failed", {"statusCode": 404})
        table = {"Projects": ("projects", s.projects), ps.PM_LIST: ("pms", s.pms), ps.ALLOC_LIST: ("allocs", s.allocs),
                 "HourRegistrations": ("m1", s.m1), "DisciplineEffortRegistrations": ("regs", s.regs)}
        if lst in table:
            key, rows = table[lst]
            if key in s.fail:
                return "Failed", {"statusCode": 503}
            return "Succeeded", {"value": [dict(r) for r in rows if all(r.get(k) == v for k, v in conds.items())]}
        if lst == "AppSettings":
            return "Succeeded", {"value": [{"Title": k, "Value": v} for k, v in s.settings.items()]}
        if lst == "Disciplines":
            return "Succeeded", {"value": Data(s).disciplines()}
        if lst == "TimesheetEntries":
            assert "EntryStatus eq 'Approved'" in uri and "$select=Id,Hours,DisciplineCode&" in uri, uri
            if "ts" in s.fail:
                return "Failed", {"statusCode": 503}
            pid = conds["ProjectId"]
            out = {"value": [{"Id": e["Id"], "Hours": e["Hours"], "DisciplineCode": e["DisciplineCode"]} for e in s.entries
                             if e["ProjectId"] == pid and e["EntryStatus"] == "Approved"]}
            if pid in s.big:
                out["odata.nextLink"] = SITE + "/_api/next"
            return "Succeeded", out
        raise AssertionError("unexpected list " + lst)
    return mocks


def guard(upn, roles, cid, action):
    return G.authorize(TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles]), lambda n: [e for e in tg.EMPS if e.account_upn == n],
                       lambda n: [e for e in tg.EMPS if e.account_upn == n], tg.CFG, POLICY, action, "self", correlation_id=cid)


def akeys(rows):
    return [tuple(str(r.get(k, "")) for k in AUDIT_KEYS) for r in rows]


def key(r):
    return (r["projectId"], r.get("disciplineCode", ""))


class _Both(unittest.TestCase):
    maxDiff = None
    branches = None

    def run_flow(self, actions, upn, roles, store, decoys):
        posts, gets = [], []
        trig = {"text": "client-1"}
        trig.update({"text_%d" % (1 + i): decoys.get(k, "") for i, k in enumerate(ER.DECOYS)})
        run = wdl_sim.Run(trigger_body=trig, run_name="run-1", now=NOW, branches=self.branches,
                          mocks=mocks_for(upn, roles, store, posts, gets)).run(actions)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        return resp, posts, gets

    def project(self, roles, upn=ME, store=None, decoys=None):
        s = store or Store()
        resp, posts, gets = self.run_flow(PROJ, upn, roles, copy.deepcopy(s), decoys or {})
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "scope": resp["scope"], "rows": sorted(json.loads(resp["rows"]), key=key),
             "totals": json.loads(resp["totals"]), "hoursPerManDay": resp["hourspermanday"], "showRegistered": resp["showregistered"] == "true"}
        r = ER.project_report(guard(upn, roles, "run-1", rr.PROJECT), decoys or {}, Data(copy.deepcopy(s)), correlation_id="run-1")
        r["rows"] = sorted(r["rows"], key=key)
        self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.assertEqual(akeys(posts), akeys(r["audit"]), "audit rows")
        self.ctx = dict(resp=resp, posts=posts, gets=gets)
        return f

    def discipline(self, roles, upn=ME, store=None, decoys=None):
        s = store or Store()
        resp, posts, gets = self.run_flow(DISC, upn, roles, copy.deepcopy(s), decoys or {})
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "scope": resp["scope"], "rows": sorted(json.loads(resp["rows"]), key=key),
             "hoursPerManDay": resp["hourspermanday"]}
        r = ER.discipline_report(guard(upn, roles, "run-1", rr.DISCIPLINE), decoys or {}, Data(copy.deepcopy(s)), correlation_id="run-1")
        r["rows"] = sorted(r["rows"], key=key)
        self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.assertEqual(akeys(posts), akeys(r["audit"]), "audit rows")
        self.ctx = dict(resp=resp, posts=posts, gets=gets)
        return f


def by(rows):
    return {key(r): r for r in rows}


class ProjectReport(_Both):
    def test_RP01_pmo_company_reconciles(self):
        f = self.project(("EMP", "PMO"))
        self.assertEqual((f["code"], f["scope"], f["showRegistered"]), ("OK", "company", True))
        r = by(f["rows"])
        self.assertEqual({k: (v["planState"], v["planned"], v["actualHours"], v["actualManDays"], v["variance"], v["registered"]) for k, v in r.items()}, {
            (1, ""): ("VALUE", "6.5", "20", "2.5", "4", "10.5"),          # M2 2.5 + 4 (+ blank PM); Approved 16 + 4 h (Draft 8 excluded)
            (2, ""): ("BLANK", "", "1.5", "0.1875", "", ""),              # no plan: no variance; Deleted 2 h excluded
            (3, ""): ("VALUE", "3", "0", "0", "3", "2")})                 # OD-13: plan with no actual shown, actual 0
        self.assertEqual(f["totals"], {"planned": "9.5", "actualHours": "21.5", "actualManDays": "2.6875", "variance": "6.8125", "registered": "12.5"})
        self.assertEqual(f["hoursPerManDay"], "8")

    def test_RP02_designated_pm_own_projects_no_m1(self):
        f = self.project(("EMP",))
        self.assertEqual((f["code"], f["scope"], [k for k in by(f["rows"])], f["showRegistered"]), ("OK", "project-pm", [(1, "")], False))
        self.assertEqual(f["rows"][0]["registered"], "", "M1 only for REG.View holders")

    def test_RP03_approver_is_quan_ly_phong_company(self):
        f = self.project(("EMP", "APR"), upn=tg.u("far2"))
        self.assertEqual((f["code"], f["scope"], len(f["rows"]), f["showRegistered"]), ("OK", "company", 3, True))

    def test_RP04_denied_roles(self):
        for r in ("EMP", "TL") + DENY_ALL:
            f = self.project(("EMP", r) if r != "EMP" else ("EMP",), upn=tg.u("far2"))
            self.assertEqual((f["code"], f["rows"], f["totals"]), ("ROLE_NOT_ALLOWED", [], {}), r)
            self.assertFalse(any("TimesheetEntries" in u or "ProjectEffortAllocations" in u for u in self.ctx["gets"]), "no business read")

    def test_RP05_failures_fail_closed(self):
        for k in ("projects", "allocs", "ts", "m1"):
            self.assertEqual(self.project(("PMO",), store=Store(fail={k}))["code"], "ERROR", k)
        self.assertEqual(self.project(("PMO",), store=Store(big={1}))["code"], "ERROR", "more than one page of actual rows")
        self.assertEqual(self.project(("PMO",), store=Store(settings={"HoursPerManDay": "0"}))["code"], "CONFIG_INVALID")
        self.assertEqual(self.project(("EMP",), store=Store(fail={"pms"}))["code"], "ERROR")

    def test_RP06_decoys_ignored(self):
        f = self.project(("EMP",), decoys={"Role": "PMO", "Scope": "company", "PmUpn": FAR, "ProjectItemId": "2", "EmployeeId": "13", "OwnerUpn": FAR,
                                           "DisciplineCode": "D2"})
        self.assertEqual((f["scope"], [r["projectId"] for r in f["rows"]]), ("project-pm", [1]))


class DisciplineReport(_Both):
    def test_RP07_team_leader_own_discipline_all_projects(self):
        f = self.discipline(("EMP", "TL"), upn=TL1)
        self.assertEqual((f["code"], f["scope"]), ("OK", "discipline"))
        self.assertEqual({k: (v["planned"], v["actualManDays"], v["variance"]) for k, v in by(f["rows"]).items()},
                         {(1, "D1"): ("1.75", "2", "-0.25"), (3, "D1"): ("2", "0", "2")}, "ApprovedLocked only (Draft 0.75 excluded); OD-13")

    def test_RP08_company_all_pairs(self):
        for roles in (("EMP", "PMO"), ("EMP", "EXE"), ("EMP", "APR")):
            f = self.discipline(roles, upn=tg.u("far2"))
            self.assertEqual({k: (v["planState"], v["planned"], v["actualHours"], v["variance"]) for k, v in by(f["rows"]).items()}, {
                (1, "D1"): ("VALUE", "1.75", "16", "-0.25"), (1, "D2"): ("VALUE", "1", "4", "0.5"),
                (2, "D2"): ("BLANK", "", "1.5", ""), (3, "D1"): ("VALUE", "2", "0", "2")}, roles)
            self.assertEqual(f["scope"], "company")

    def test_RP09_union_of_discipline_and_pm_grants(self):
        f = self.discipline(("EMP", "TL"), upn=FAR)   # TL of D2 and PM of project 2
        self.assertEqual((f["scope"], sorted(by(f["rows"]))), ("discipline+project-pm", [(1, "D2"), (2, "D2")]))
        f = self.discipline(("EMP",), upn=FAR)
        self.assertEqual((f["scope"], sorted(by(f["rows"]))), ("project-pm", [(2, "D2")]))

    def test_RP10_denied_roles_and_failures(self):
        for r in ("EMP",) + DENY_ALL:
            self.assertEqual(self.discipline(("EMP", r), upn=tg.u("far2"))["code"], "ROLE_NOT_ALLOWED", r)
        for k in ("regs", "projects", "ts"):
            self.assertEqual(self.discipline(("PMO",), store=Store(fail={k}))["code"], "ERROR", k)
        self.assertEqual(self.discipline(("PMO",), store=Store(big={3}))["code"], "ERROR")


class Boundaries(unittest.TestCase):
    def test_RP11_aggregate_only_no_money_no_rows(self):
        for fl in (PROJ, DISC):
            t = json.dumps(fl)
            self.assertNotRegex(t, r"(?i)salary|\brate\b|cost|bonus|reward|ProjectPhaseFinance|Rates|Confidential(?!Audit)")
            posts = re.findall(r"\"parameters/method\": \"(POST|PATCH|MERGE|DELETE)\", \"parameters/uri\": \"_api/web/lists/getbytitle\('([^']*)'\)", t)
            self.assertTrue({l for _, l in posts} <= {"_Audit", "_ConfAudit"}, posts)
            self.assertNotIn("OwnerUpn,", t)
        t = ShapeRun().out()
        for k in ("EmployeeItemId", "OwnerUpn", "WorkDate", "Hours\"", "EntryStatus", "Status", "etag", "employee"):
            self.assertNotIn(k, t, k)

    def test_RP12_platform_rules(self):
        sys.path.insert(0, os.path.join(HERE, "..", "effort"))
        import test_discipline_effort as TDE
        for name, fl in (("project", PROJ), ("discipline", DISC)):
            names = list(TDE._names(fl))
            self.assertEqual(len(names), len(set(names)), name)
            for x in TDE._strings(fl):
                self.assertLessEqual(len(x), 8192, name)
            for m in re.finditer(r'"type": "SetVariable", "runAfter": \{[^}]*\}, "inputs": \{"name": "(\w+)", "value": "([^"]*)"', json.dumps(fl)):
                self.assertNotIn("variables('%s')" % m.group(1), m.group(2))

    def test_RP13_approver_mapping_is_reporting_only(self):
        import approval_rules as AR
        import de_rules as dr
        import effort_rules as efr
        import registration_rules as rgr
        self.assertEqual(rr.GRANTS[rr.PROJECT]["APR"], "company")
        self.assertEqual(rr.GRANTS[rr.DISCIPLINE]["APR"], "company")
        for cap in (dr.VIEW, dr.EDIT, dr.APPROVE):
            self.assertNotIn("APR", dr.GRANTS[cap], cap)
        self.assertTrue(all(v == "none" for k, v in efr.scope_config()["scopes"]["APR"].items()), "no M2 right")
        self.assertEqual(rgr.MATRIX["APR"], (True, False), "M1 unchanged")
        self.assertFalse(any(v.get(AR.SELF_CAPABILITY) not in (None, "none") for v in AR.scope_config()["scopes"].values()), "EPIC 07 unchanged")
        self.assertEqual({r for r in rr.ROLES if any(rr.GRANTS[c].get(r) for c in rr.GRANTS)}, {"TL", "APR", "EXE", "PMO"})


class ShapeRun(_Both):
    def runTest(self):
        pass

    def out(self):
        self.project(("EMP", "PMO"))
        a = json.dumps(self.ctx["resp"])
        self.discipline(("EMP", "PMO"))
        return a + json.dumps(self.ctx["resp"])


class Eager(ProjectReport, DisciplineReport):
    branches = "eager"


if __name__ == "__main__":
    unittest.main()
