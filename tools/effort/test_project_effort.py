"""R3 M2 EPIC 16 Project Effort: reference (project_effort) vs generated flows (build_effort_flows) in the WDL simulator,
one SharePoint-like store per side. Tests PE01-PE24 (offline; synthetic data only)."""
import copy
import json
import os
import re
import sys
import unittest
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity")):
    sys.path.insert(0, p)
import build_effort_flows as bf  # noqa: E402
import effort_rules as er  # noqa: E402
import guard as G  # noqa: E402
import pe_schema as ps  # noqa: E402
import project_effort as PE  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

NOW = "2026-10-10T01:02:03Z"
SITE = "https://tenant-a.invalid/sites/x"
KW = dict(role_groups=tg.ROLE_GROUPS, site=SITE, domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit",
          conf_audit_list="_ConfAudit", environment="STAGING")
READ, SAVE, SETPM = bf.read_effort_actions(**KW), bf.save_effort_actions(**KW), bf.set_pm_actions(**KW)
POLICY = G.Policy.from_scope_config(er.scope_config())
ME = tg.u("peer")  # employee 12
ENTITY = {ps.ALLOC_LIST: "SP.Data.ProjectEffortAllocationsListItem", ps.PM_LIST: "SP.Data.ProjectPmAssignmentsListItem"}
AUDIT_KEYS = ("EventType", "Action", "Decision", "ResultCode", "TargetItemId", "TargetLegacyId")


def num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


EMP_ROWS = [{"Id": e.item_id, "LegacyId": e.legacy_id, "Title": "Name %s" % e.legacy_id, "LegacyUserName": "u%s" % e.legacy_id.lower(),
             "IsActive": e.is_active} for e in tg.EMPS]


class Store:
    def __init__(self, settings=None, assign=((1, 12), (2, 13)), allocs=(), entries=(), page=3, fail=(), race=()):
        self.projects = {i: {"Id": i, "LegacyId": "PRJ-L%d" % i, "ProjectCode": "P%d" % i, "Title": "Project %d" % i, "Status": "Active"}
                         for i in (1, 2, 3)}
        self.discs = {i: {"Id": i, "LegacyId": "D-L%d" % i, "DisciplineCode": "D%d" % i, "Title": "Disc %d" % i} for i in (1, 2, 3)}
        self.settings = {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "D2,D1"} if settings is None else dict(settings)
        self.lists = {ps.PM_LIST: {}, ps.ALLOC_LIST: {}}
        self.ver, self.next_id = {}, 1
        for pid, emp in assign:
            self._put(ps.PM_LIST, {"PmKey": "PRJ-L%d" % pid, "LegacyId": "PRJ-L%d" % pid, "ProjectItemId": pid, "PmEmployeeItemId": emp,
                                   "PmEmployeeLegacyId": "E%d" % (emp - 10), "Status": "Active"})
        for pid, key, v in allocs:
            k = PE.alloc_key("PRJ-L%d" % pid, key)
            self._put(ps.ALLOC_LIST, {"AllocKey": k, "LegacyId": k, "ProjectItemId": pid, "RecipientKey": key, "Effort": num(v), "Status": "Active"})
        # TimesheetEntries: (id, project, hours, status)
        self.entries = [{"Id": i, "ProjectId": p, "Hours": h, "EntryStatus": st, "OwnerUpn": "x@y", "WorkDate": "2026-10-01"} for i, p, h, st in entries]
        self.page, self.fail, self.race = page, set(fail), set(race)

    def _put(self, lst, fields):
        i = self.next_id
        self.next_id += 1
        self.lists[lst][i] = dict(fields, Id=i)
        self.ver[i] = 1
        return i

    def etag(self, lst, i):
        return '"%d,%d"' % (i, self.ver[i])

    def rows(self, lst, **flt):
        return [dict(r, **{"odata.etag": self.etag(lst, i)}) for i, r in sorted(self.lists[lst].items())
                if all(r.get(k) == v for k, v in flt.items())]

    def create(self, lst, fields):
        keyf = "PmKey" if lst == ps.PM_LIST else "AllocKey"
        if any(r[keyf] == fields[keyf] for r in self.lists[lst].values()) or "dup" in self.fail:
            raise PE.ConflictError()
        keep = {k: v for k, v in fields.items() if k not in ("Title", "ProjectId", "DisciplineId", "PmEmployeeId", "ActorUpn", "CorrelationId")}
        if "Effort" in keep:
            keep["Effort"] = num(keep["Effort"])
        i = self._put(lst, keep)
        return i, self.etag(lst, i)

    def update(self, lst, i, fields, if_match):
        if i in self.race:
            self.ver[i] += 1
            self.race.discard(i)
        if "merge:%d" % i in self.fail:
            raise ConnectionError("500")
        if if_match != self.etag(lst, i):
            raise PE.ConflictError()
        for k, v in fields.items():
            if k not in ("ActorUpn", "CorrelationId", "PmEmployeeId"):
                self.lists[lst][i][k] = num(v) if k == "Effort" else v
        self.ver[i] += 1

    def approved_hours(self, pid):
        if "pages" in self.fail:
            raise ConnectionError("503")
        return sum(float(e["Hours"] or 0) for e in self.entries if e["ProjectId"] == pid and e["EntryStatus"] == "Approved")


class Data:
    def __init__(self, s):
        self.s = s

    def _f(self, k):
        if k in self.s.fail:
            raise ConnectionError("503")

    def project(self, pid):
        self._f("Get_project")
        return self.s.projects.get(pid)

    def projects(self):
        self._f("Get_project")
        return list(self.s.projects.values())

    def assignment(self, pid):
        self._f("assign")
        r = self.s.rows(ps.PM_LIST, ProjectItemId=pid)
        return dict(r[0], etag=r[0]["odata.etag"]) if r else None

    def assignments(self):
        self._f("assign")
        return self.s.rows(ps.PM_LIST)

    def employee(self, eid):
        self._f("emps")
        return next((e for e in EMP_ROWS if e["Id"] == eid), None)

    def employees(self):
        self._f("emps")
        return list(EMP_ROWS)

    def settings(self):
        self._f("settings")
        return dict(self.s.settings)

    def disciplines(self):
        self._f("discs")
        return list(self.s.discs.values())

    def allocations(self, pid):
        self._f("items")
        return [dict(r, etag=r["odata.etag"]) for r in self.s.rows(ps.ALLOC_LIST, ProjectItemId=pid)]

    def approved_hours(self, pid):
        return self.s.approved_hours(pid)


class Store2:
    """Adapter so the reference write API matches (create / update / etag by list)."""

    def __init__(self, s):
        self.s = s

    def create(self, lst, fields):
        return self.s.create(lst, fields)

    def update(self, lst, i, fields, if_match):
        return self.s.update(lst, i, fields, if_match)

    def etag(self, lst, i):
        return self.s.etag(lst, i)


_EQ = re.compile(r"(\w+) eq (-?\d+)")


def mocks_for(upn, roles, s, posts, writes, uris, *, profile_fail=False, fail_audit=()):
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return ("Failed", {"statusCode": 503}) if profile_fail else ("Succeeded", {"userPrincipalName": upn})
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        method, raw = p["parameters/method"], p["parameters/uri"]
        uri = unquote(raw)
        uris.append((method, uri))
        lst = re.search(r"getbytitle\('([^']*)'\)", uri).group(1)
        if lst in ("_Audit", "_ConfAudit"):
            row = json.loads(p["parameters/body"])
            if row.get("EventType") in fail_audit:
                return "Failed", {"statusCode": 400}
            posts.append(row)
            return "Succeeded", {"Id": len(posts)}
        m = re.search(r"/items\((-?\d+)\)", uri)
        flt = uri.split("$filter=")[1].split("&")[0] if "$filter=" in uri else ""
        conds = dict((k, int(v)) for k, v in _EQ.findall(flt))
        if lst == tg.EMP_LIST:
            if "AccountUpn eq" in uri:
                return "Succeeded", wdl_sim.sharepoint_get(raw, {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)})
            if "emps" in s.fail:
                return "Failed", {"statusCode": 503}
            if m:
                e = next((x for x in EMP_ROWS if x["Id"] == int(m.group(1))), None)
                return ("Succeeded", dict(e)) if e else ("Failed", {"statusCode": 404})
            return "Succeeded", {"value": sorted([dict(e) for e in EMP_ROWS], key=lambda e: (e["Title"], e["Id"]))}
        if lst == "Projects":
            if "Get_project" in s.fail:
                return "Failed", {"statusCode": 503}
            if m:
                pr = s.projects.get(int(m.group(1)))
                return ("Succeeded", dict(pr)) if pr else ("Failed", {"statusCode": 404})
            return "Succeeded", {"value": [dict(x) for x in sorted(s.projects.values(), key=lambda x: (x["ProjectCode"], x["Id"]))]}
        if lst == "AppSettings":
            if "settings" in s.fail:
                return "Failed", {"statusCode": 503}
            return "Succeeded", {"value": [{"Title": k, "Value": v} for k, v in s.settings.items()]}
        if lst == "Disciplines":
            if "discs" in s.fail:
                return "Failed", {"statusCode": 503}
            return "Succeeded", {"value": [dict(d) for d in s.discs.values()]}
        if lst == "TimesheetEntries":
            assert method == "GET" and "EntryStatus eq 'Approved'" in uri and "$select=Id,Hours&" in uri, uri
            if "pages" in s.fail and "skiptoken" in uri:
                return "Failed", {"statusCode": 503}
            after = int(re.findall(r"p_ID=(\d+)", uri)[-1]) if "skiptoken" in uri else 0
            rows = [e for e in s.entries if e["ProjectId"] == conds["ProjectId"] and e["EntryStatus"] == "Approved" and e["Id"] > after]
            pg = rows[:s.page]
            out = {"value": [{"Id": e["Id"], "Hours": e["Hours"]} for e in pg]}
            if len(rows) > s.page:
                first = re.sub(r"&%24skiptoken=[^&]*", "", raw)
                out["odata.nextLink"] = "%s/%s&%%24skiptoken=Paged%%3DTRUE%%26p_ID%%3D%d" % (SITE, first, pg[-1]["Id"])
            return "Succeeded", out
        assert lst in (ps.PM_LIST, ps.ALLOC_LIST), uri
        if method == "GET" and uri.endswith("?$select=ListItemEntityTypeFullName"):
            return "Succeeded", {"ListItemEntityTypeFullName": ENTITY[lst]}
        if method == "GET" and m:
            i = int(m.group(1))
            return "Succeeded", {"Id": i, "odata.etag": s.etag(lst, i)}
        if method == "GET":
            if ("assign" in s.fail and lst == ps.PM_LIST) or ("items" in s.fail and lst == ps.ALLOC_LIST):
                return "Failed", {"statusCode": 503}
            return "Succeeded", {"value": s.rows(lst, **conds)}
        body = json.loads(p["parameters/body"])
        h = p["parameters/headers"]
        assert a["inputs"]["retryPolicy"] == {"type": "none"} and body["__metadata"]["type"] == ENTITY[lst]
        fields = {k: v for k, v in body.items() if k != "__metadata"}
        if m:
            assert h["X-HTTP-Method"] == "MERGE" and h["IF-MATCH"] not in ("*", "")
            writes.append((lst, "MERGE", int(m.group(1)), fields))
            try:
                s.update(lst, int(m.group(1)), fields, h["IF-MATCH"])
            except PE.ConflictError:
                return "Failed", {"statusCode": 412}
            except ConnectionError:
                return "Failed", {"statusCode": 500}
            return "Succeeded", None
        writes.append((lst, "POST", None, fields))
        try:
            i, etag = s.create(lst, fields)
        except PE.ConflictError:
            return "Failed", {"statusCode": 400}
        return "Succeeded", {"d": {"Id": i, "__metadata": {"etag": etag}}}
    return mocks


def ident(upn, roles):
    return TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])


def lk(n):
    return [e for e in tg.EMPS if e.account_upn == n]


def guard(upn, roles, cid, action, decoys=None):
    return G.authorize(ident(upn, roles), lk, lk, tg.CFG, POLICY, action, "self", correlation_id=cid, **{k: "" for k in (decoys or {})})


def ch(*cells):
    return json.dumps([{"key": k, "state": st, "value": v, "etag": et} for k, st, v, et in cells])


def akeys(rows):
    return [tuple(str(r.get(k, "")) for k in AUDIT_KEYS) for r in rows]


class _Both(unittest.TestCase):
    maxDiff = None
    branches = None

    def _run(self, actions, trig, upn, roles, fs, cid, profile_fail, fail_audit):
        posts, writes, uris = [], [], []
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW, branches=self.branches,
                          mocks=mocks_for(upn, roles, fs, posts, writes, uris, profile_fail=profile_fail, fail_audit=fail_audit)).run(actions)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        return resp, posts, writes, uris

    def read(self, roles=("EMP",), pid="1", store=None, upn=ME, decoys=None, cid="run-r", profile_fail=False, fail_audit=()):
        fs = copy.deepcopy(store or Store())
        rs = copy.deepcopy(fs)
        trig = {"text": pid}
        trig.update({"text_%d" % (1 + i): (decoys or {}).get(k, "") for i, k in enumerate(PE.READ_DECOYS)})
        resp, posts, writes, uris = self._run(READ, trig, upn, roles, fs, cid, profile_fail, fail_audit)
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "mode": resp["mode"],
             "projects": sorted(json.loads(resp["projects"]), key=lambda p: p["id"]), "project": json.loads(resp["project"]),
             "pm": json.loads(resp["pm"]), "recipients": json.loads(resp["recipients"]), "plannedTotal": resp["plannedtotal"],
             "actualHours": resp["actualhours"], "actualManDays": resp["actualmandays"], "variance": resp["variance"],
             "hoursPerManDay": resp["hourspermanday"], "canEdit": resp["canedit"] == "true", "canAssignPm": resp["canassignpm"] == "true",
             "pmEtag": resp["pmetag"], "employees": json.loads(resp["employees"])}
        r = PE.read_effort(guard(upn, roles, cid, er.VIEW, decoys), dict({"ProjectItemId": pid}, **(decoys or {})), Data(rs),
                           correlation_id=cid, profile_failed=profile_fail)
        r["projects"] = sorted(r["projects"], key=lambda p: p["id"])
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
            self.assertEqual(akeys(posts), akeys(r["audit"]), "audit rows")
        self.ctx = dict(posts=posts, writes=writes, uris=uris, ref=r, store=fs, resp=resp)
        return f

    def save(self, cells=None, roles=("EMP",), pid="1", store=None, upn=ME, decoys=None, cid="run-s", raw=None, profile_fail=False, fail_audit=()):
        fs = copy.deepcopy(store or Store())
        rs = copy.deepcopy(fs)
        changes = raw if raw is not None else ch(*cells)
        trig = {"text": pid, "text_1": changes, "text_2": "client-1"}
        trig.update({"text_%d" % (3 + i): (decoys or {}).get(k, "") for i, k in enumerate(PE.SAVE_DECOYS)})
        resp, posts, writes, uris = self._run(SAVE, trig, upn, roles, fs, cid, profile_fail, fail_audit)
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "savedCount": int(resp["savedcount"]),
             "results": sorted(json.loads(resp["results"]), key=lambda x: x["key"]), "auditStatus": resp["auditstatus"],
             "warnings": json.loads(resp["warnings"])}
        r = PE.save_effort(guard(upn, roles, cid, er.EDIT, decoys), dict({"ProjectItemId": pid, "Changes": changes}, **(decoys or {})),
                           Data(rs), Store2(rs), correlation_id=cid, profile_failed=profile_fail,
                           row_audit_ok=lambda k: "WriteProxy" not in fail_audit)
        r["results"] = sorted(r["results"], key=lambda x: x["key"])
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
            self.assertEqual(sorted(akeys(posts)), sorted(akeys(r["audit"])), "audit rows")
            self.assertEqual(fs.lists, rs.lists, "store after flow == store after reference")
        self.ctx = dict(posts=posts, writes=writes, uris=uris, ref=r, store=fs, resp=resp)
        return f

    def setpm(self, eid, etag="", roles=("PMO",), pid="1", store=None, upn=ME, decoys=None, cid="run-p", profile_fail=False, fail_audit=()):
        fs = copy.deepcopy(store or Store())
        rs = copy.deepcopy(fs)
        trig = {"text": pid, "text_1": str(eid), "text_2": etag}
        trig.update({"text_%d" % (3 + i): (decoys or {}).get(k, "") for i, k in enumerate(PE.PM_DECOYS)})
        resp, posts, writes, uris = self._run(SETPM, trig, upn, roles, fs, cid, profile_fail, fail_audit)
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "etag": resp["etag"], "pm": json.loads(resp["pm"]), "auditStatus": resp["auditstatus"]}
        r = PE.set_pm(guard(upn, roles, cid, er.ASSIGN, decoys), dict({"ProjectItemId": pid, "EmployeeItemId": str(eid), "ETag": etag}, **(decoys or {})),
                      Data(rs), Store2(rs), correlation_id=cid, profile_failed=profile_fail, row_audit_ok=lambda k: "WriteProxy" not in fail_audit)
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
            self.assertEqual(akeys(posts), akeys(r["audit"]), "audit rows")
            self.assertEqual(fs.lists, rs.lists)
        self.ctx = dict(posts=posts, writes=writes, uris=uris, ref=r, store=fs, resp=resp)
        return f


ENTRIES = [(1, 1, 8, "Approved"), (2, 1, 4.5, "Draft"), (3, 1, 3.5, "Approved"), (4, 2, 7, "Approved"), (5, 1, 2, "Deleted"),
           (6, 1, 0.25, "Approved"), (7, 1, 4, "Approved"), (8, 1, None, "Approved")]
FULL = dict(allocs=((1, "QLP", 10), (1, "D:D-L1", 0), (1, "PM", None), (2, "QLP", 5)), entries=ENTRIES)
ROLES = er.ROLES


class Schema(unittest.TestCase):
    def test_PE01_schema_portable_keys_no_forbidden_fields(self):
        for lst, fields in ps.LISTS.items():
            names = {f[0] for f in fields}
            self.assertFalse(names & ps.FORBIDDEN_COLUMNS, lst)
            self.assertTrue(ps.field(lst, "LegacyId")[4], "unique canonical key")
            self.assertNotIn("HourRegistrations", json.dumps(fields))
        self.assertTrue(ps.field(ps.PM_LIST, "PmKey")[4] and ps.field(ps.ALLOC_LIST, "AllocKey")[4])
        self.assertEqual(ps.field(ps.ALLOC_LIST, "Effort")[5], {"Decimals": 2})
        self.assertFalse(ps.field(ps.ALLOC_LIST, "Effort")[2], "nullable: blank != 0")
        self.assertFalse(ps.SERVICE_RIGHTS & ps.NEVER)
        self.assertEqual(ps.DIRECT_USER_ACCESS, ())
        self.assertEqual(PE.alloc_key("PRJ-9", "D:abc"), "PRJ-9|D:abc")

    def test_PE02_capability_matrix(self):
        sc = er.scope_config()["scopes"]
        for r in ROLES:
            self.assertEqual(sc[r][er.VIEW] == "company", r in ("EXE", "PMO"), r)
            self.assertEqual(sc[r][er.ASSIGN] == "company", r == "PMO", r)
            self.assertEqual(sc[r][er.EDIT], "none", "nobody edits by role")
        for r in ("ADM", "ITS", "MIGO", "CONFO", "SALV", "FIN", "HR", "TL", "APR", "EMP"):
            self.assertFalse(er.role_can([r], er.VIEW) or er.role_can([r], er.ASSIGN) or er.role_can([r], er.EDIT), r)
        self.assertEqual(er.edit_decision("ALLOW", False), ("SCOPE_NOT_ALLOWED", "none"), "PMO / EXE role does not grant edit")

    def test_PE03_value_domain(self):
        for v, code in (("0", None), ("12", None), ("1.5", None), ("1.25", None), ("1.255", "VALIDATION_VALUE"), ("-1", "VALIDATION_VALUE"),
                        ("1,5", "VALIDATION_VALUE"), ("abc", "VALIDATION_VALUE"), ("", "VALIDATION_VALUE"), (".5", "VALIDATION_VALUE"),
                        ("123456789012.34", None), ("1234567890123456", "TECHNICAL_LIMIT"), ("9999999999999999.9", "TECHNICAL_LIMIT")):
            self.assertEqual(PE.value_code(v), code, v)

    def test_PE04_settings_fail_closed(self):
        self.assertEqual(PE.settings({"HoursPerManDay": "8"}), (8.0, ["ELE", "HVAC", "PSF", "BIM"]), "OD-43 default")
        for bad in ({"HoursPerManDay": "0"}, {"HoursPerManDay": "x"}, {}, {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "A,,B"},
                    {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "A,a"}):
            self.assertIsNone(PE.settings(bad), bad)


class Read(_Both):
    def test_PE05_list_mode_by_role_and_pm_scope(self):
        st = Store(**FULL)
        for roles in (("EMP", "PMO"), ("EMP", "EXE")):
            f = self.read(roles, pid="0", store=st)
            self.assertEqual((f["code"], [p["id"] for p in f["projects"]]), ("OK", [1, 2, 3]))
            self.assertEqual([p["canEdit"] for p in f["projects"]], [True, False, False], "only own PM project editable")
        f = self.read(("EMP",), pid="0", store=st)
        self.assertEqual((f["code"], [p["id"] for p in f["projects"]], f["projects"][0]["pmName"]), ("OK", [1], "Name E2"))
        self.assertFalse(f["canAssignPm"])
        f = self.read(("EMP",), pid="0", store=st, upn=tg.u("emp"))
        self.assertEqual((f["code"], f["projects"]), ("ROLE_NOT_ALLOWED", []))
        for r in ("ADM", "ITS", "TL", "APR", "HR", "FIN", "SALV", "CONFO", "MIGO"):
            f = self.read(("EMP", r), pid="0", store=st, upn=tg.u("emp"))
            self.assertEqual(f["code"], "ROLE_NOT_ALLOWED" if r != "MIGO" else f["code"], r)
            self.assertNotEqual(f["code"], "OK", r)

    def test_PE06_detail_as_pm(self):
        f = self.read(("EMP",), store=Store(**FULL))
        self.assertEqual(f["code"], "OK")
        self.assertEqual([r["key"] for r in f["recipients"]], ["QLP", "PM", "D:D-L2", "D:D-L1"], "QLP, PM, configured order")
        rs = {r["key"]: (r["state"], r["value"]) for r in f["recipients"]}
        self.assertEqual(rs, {"QLP": ("VALUE", "10"), "PM": ("BLANK", ""), "D:D-L2": ("BLANK", ""), "D:D-L1": ("VALUE", "0")},
                         "blank (incl. a stored null) != explicit 0")
        self.assertEqual((f["plannedTotal"], f["actualHours"], f["actualManDays"], f["variance"], f["hoursPerManDay"]),
                         ("10", "15.75", "1.96875", "-8.03125", "8"), "Approved only: 8 + 3.5 + 0.25 + 4 (+ null) = 15.75 h / 8")
        self.assertTrue(f["canEdit"])
        self.assertFalse(f["canAssignPm"])
        self.assertEqual(f["employees"], [])
        self.assertEqual(f["pm"], {"employeeId": 12, "name": "Name E2", "code": "ue2"})

    def test_PE07_detail_viewers_and_denials(self):
        st = Store(**FULL)
        f = self.read(("EMP", "PMO"), pid="2", store=st)
        self.assertEqual((f["code"], f["canEdit"], f["canAssignPm"]), ("OK", False, True), "PMO views, cannot edit")
        self.assertEqual([e["id"] for e in f["employees"]], [11, 12, 13, 14, 16, 17, 18], "active employees only (15 inactive)")
        self.assertEqual((f["actualHours"], f["actualManDays"]), ("7", "0.875"))
        f = self.read(("EMP", "EXE"), pid="3", store=st)
        self.assertEqual((f["code"], f["canEdit"], f["pm"], f["pmEtag"]), ("OK", False, {}, ""), "no PM project viewable, not editable")
        self.assertEqual(self.read(("EMP",), pid="2", store=st)["code"], "SCOPE_NOT_ALLOWED", "PM of another project")
        self.assertEqual(self.read(("EMP", "TL"), pid="1", store=st, upn=tg.u("emp"))["code"], "ROLE_NOT_ALLOWED")
        self.assertEqual(self.read(("EMP", "ADM"), pid="1", store=st, upn=tg.u("emp"))["code"], "ROLE_NOT_ALLOWED", "AppAdmin no business access")
        self.assertEqual(self.read(("EMP", "ITS"), pid="1", store=st, upn=tg.u("emp"))["code"], "ROLE_NOT_ALLOWED")
        self.assertEqual(self.read(("EMP", "PMO"), pid="99", store=st)["code"], "NOT_FOUND")
        self.assertEqual(self.read(("EMP",), pid="99", store=st)["code"], "SCOPE_NOT_ALLOWED")
        self.assertEqual(self.read(("EMP", "PMO"), store=st, upn=tg.u("gone"))["code"], "INACTIVE_EMPLOYEE")
        self.assertEqual(self.read(("EMP", "PMO"), store=st, upn=tg.u("nobody"))["code"], "UNMAPPED_IDENTITY")

    def test_PE08_config_fail_closed(self):
        for s in ({"HoursPerManDay": "0"}, {ps.RECIPIENT_SETTING: "D1"}, {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "D1,XX"},
                  {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "D1,d1"}):
            self.assertEqual(self.read(("EMP",), store=Store(settings=s, **FULL))["code"], "CONFIG_INVALID", s)
        f = self.read(("EMP",), store=Store(settings={"HoursPerManDay": "7.5", ps.RECIPIENT_SETTING: " D3 "}, **FULL))
        self.assertEqual(([r["key"] for r in f["recipients"]], f["hoursPerManDay"]), (["QLP", "PM", "D:D-L3"], "7.5"))

    def test_PE09_actual_paging_and_fail_closed(self):
        many = [(i, 1, 1.5, "Approved" if i % 3 else "Draft") for i in range(1, 41)]
        f = self.read(("EMP",), store=Store(entries=many, page=4))
        self.assertEqual(f["actualHours"], str(1.5 * len([i for i in range(1, 41) if i % 3])))
        n = sum(1 for m, u in self.ctx["uris"] if "TimesheetEntries" in u)
        self.assertGreater(n, 5, "several pages read")
        f = self.read(("EMP",), store=Store(entries=many, page=4, fail={"pages"}))
        self.assertEqual((f["code"], f["actualHours"], f["recipients"]), ("ERROR", "", []), "no partial total")

    def test_PE10_no_timesheet_row_leakage(self):
        self.read(("EMP", "PMO"), store=Store(**FULL))
        text = json.dumps(self.ctx["resp"], ensure_ascii=False)
        for bad in ("WorkDate", "OwnerUpn", "x@y", "EntryStatus", "2026-10-01"):
            self.assertNotIn(bad, text)
        for m, u in self.ctx["uris"]:
            if "TimesheetEntries" in u:
                self.assertIn("$select=Id,Hours&", u)
                self.assertEqual(m, "GET")

    def test_PE11_read_failures(self):
        for k in ("assign", "items", "emps", "discs", "settings"):
            self.assertEqual(self.read(("EMP", "PMO"), store=Store(fail={k}, **FULL))["code"], "ERROR", k)
        self.assertEqual(self.read(("EMP",), pid="0", store=Store(fail={"assign"}, **FULL))["code"], "ERROR")
        f = self.read(("EMP",), store=Store(**FULL), profile_fail=True)
        self.assertEqual(f["code"], "DIRECTORY_ERROR")
        f = self.read(("EMP",), store=Store(**FULL), fail_audit=("AuthorizationAllow",))
        self.assertEqual((f["ok"], f["code"]), (False, "INTERNAL_ERROR"), "mandatory authorization audit")


class Save(_Both):
    def test_PE12_pm_saves_blank_zero_decimals(self):
        st = Store(**FULL)
        f = self.read(("EMP",), store=st)
        et = {r["key"]: r["etag"] for r in f["recipients"]}
        f = self.save([("PM", "value", "0", et["PM"]), ("D:D-L2", "value", "12.25", ""), ("QLP", "value", "10", et["QLP"]),
                       ("D:D-L1", "blank", "", et["D:D-L1"])], store=st)
        self.assertEqual((f["code"], f["savedCount"]), ("OK", 3))
        self.assertEqual({r["key"]: r["resultcode"] for r in f["results"]}, {"PM": "OK", "D:D-L2": "OK", "QLP": "NO_CHANGE", "D:D-L1": "OK"})
        vals = {r["RecipientKey"]: r["Effort"] for r in self.ctx["store"].lists[ps.ALLOC_LIST].values() if r["ProjectItemId"] == 1}
        self.assertEqual(vals, {"QLP": 10, "PM": 0, "D:D-L1": None, "D:D-L2": 12.25}, "0 explicit, cleared = null, no rounding")
        acts = sorted(r["Action"] for r in self.ctx["posts"] if r["EventType"] == "WriteProxy")
        self.assertEqual(acts, ["Clear", "Create", "Update"])
        self.assertTrue(all(r["TargetList"] == ps.ALLOC_LIST for r in self.ctx["posts"] if r["EventType"] == "WriteProxy"))
        new = [w for w in self.ctx["writes"] if w[1] == "POST"][0][3]
        self.assertEqual((new["AllocKey"], new["RecipientCategory"], new["DisciplineItemId"]), ("PRJ-L1|D:D-L2", "Discipline", 2))
        self.assertEqual(self.save([("QLP", "value", "1234567.89", et["QLP"])], store=st)["code"], "OK", "no business maximum")

    def test_PE13_edit_only_by_the_project_pm(self):
        st = Store(**FULL)
        cell = [("D:D-L2", "value", "1", "")]
        self.assertEqual(self.save(cell, roles=("EMP", "PMO"), pid="2", store=st)["code"], "SCOPE_NOT_ALLOWED", "PMO not PM of 2")
        self.assertEqual(self.save(cell, roles=("EMP", "EXE"), pid="2", store=st)["code"], "SCOPE_NOT_ALLOWED")
        self.assertEqual(self.save(cell, roles=("EMP", "PMO", "EXE"), pid="3", store=st)["code"], "SCOPE_NOT_ALLOWED", "no PM -> not editable")
        for r in ("ADM", "ITS", "TL", "APR", "HR", "FIN", "SALV", "CONFO"):
            self.assertEqual(self.save(cell, roles=("EMP", r), store=st, upn=tg.u("emp"))["code"], "SCOPE_NOT_ALLOWED", r)
            self.assertEqual(self.ctx["writes"], [])
        self.assertEqual(self.save(cell, store=st, upn=tg.u("gone"))["code"], "INACTIVE_EMPLOYEE")
        self.assertEqual(self.save(cell, store=st, pid="0")["code"], "SCOPE_NOT_ALLOWED")
        f = self.save(cell, roles=("EMP", "PMO"), pid="1", store=st)
        self.assertEqual(f["code"], "OK", "a PMO user who is also the designated PM edits as PM")

    def test_PE14_validation_refuses_everything(self):
        st = Store(**FULL)
        for cells, code in (([("QLP", "value", "1.255", "")], "VALIDATION_VALUE"), ([("QLP", "value", "-1", "")], "VALIDATION_VALUE"),
                            ([("QLP", "value", "1,5", "")], "VALIDATION_VALUE"), ([("QLP", "value", "abc", "")], "VALIDATION_VALUE"),
                            ([("QLP", "value", "1234567890123456", "")], "TECHNICAL_LIMIT"), ([("D:D-L3", "value", "1", "")], "VALIDATION_LOOKUP"),
                            ([("QLP", "x", "1", "")], "VALIDATION_VALUE"), ([("QLP", "value", "", "")], "VALIDATION_VALUE")):
            f = self.save(cells + [("D:D-L2", "value", "2", "")], store=st)
            self.assertEqual((f["code"], {r["key"]: r["resultcode"] for r in f["results"]}), ("REFUSED", {cells[0][0]: code, "D:D-L2": "NOT_WRITTEN"}), cells)
            self.assertEqual(self.ctx["writes"], [])
        for raw in ("", "x", "{}", "[]", json.dumps([{"key": "QLP", "state": "blank"}] * 2),
                    ch(*[("K%d" % i, "blank", "", "") for i in range(21)])):
            self.assertEqual(self.save(raw=raw, store=st)["code"], "VALIDATION_REQUEST", raw[:40])

    def test_PE15_concurrency(self):
        st = Store(**FULL)
        f = self.save([("QLP", "value", "11", '"1,0"'), ("D:D-L2", "value", "1", "")], store=st)
        self.assertEqual((f["code"], {r["key"]: r["resultcode"] for r in f["results"]}), ("REFUSED", {"QLP": "CONFLICT", "D:D-L2": "NOT_WRITTEN"}),
                         "stale ETag at preflight: nothing written")
        self.assertEqual(self.save([("D:D-L2", "value", "1", '"9,9"')], store=st)["code"], "REFUSED", "etag for a cell without item")
        qid = [i for i, r in st.lists[ps.ALLOC_LIST].items() if r["RecipientKey"] == "QLP" and r["ProjectItemId"] == 1][0]
        race = Store(race={qid}, **FULL)
        f = self.save([("QLP", "value", "11", race.etag(ps.ALLOC_LIST, qid)), ("D:D-L2", "value", "1", "")], store=race)
        self.assertEqual((f["code"], {r["key"]: r["resultcode"] for r in f["results"]}, f["warnings"]),
                         ("PARTIAL", {"QLP": "CONFLICT", "D:D-L2": "OK"}, ["WARN_RELOAD_REQUIRED"]), "race after preflight: explicit PARTIAL")
        f = self.save([("D:D-L2", "value", "1", "")], store=Store(fail={"dup"}, **FULL))
        self.assertEqual((f["code"], f["results"][0]["resultcode"]), ("PARTIAL", "CONFLICT"), "concurrent create of the same key")

    def test_PE16_audit_and_decoys(self):
        st = Store(**FULL)
        f = self.save([("D:D-L2", "value", "3", "")], store=st, decoys={"ActorUpn": "boss@x", "OwnerUpn": "a@b", "PmUpn": "peer", "Role": "PMO", "Scope": "company"})
        self.assertEqual(f["code"], "OK")
        authz = [r for r in self.ctx["posts"] if r["EventType"].startswith("Authorization")]
        self.assertEqual(len(authz), 1)
        self.assertIn("ignored=ActorUpn,OwnerUpn,PmUpn,Role,Scope", authz[0]["Detail"])
        self.assertTrue(all(r["ActorUpn"] == ME for r in self.ctx["posts"]))
        f = self.save([("D:D-L2", "value", "4", "")], store=st, fail_audit=("WriteProxy",))
        self.assertEqual((f["code"], f["auditStatus"], f["warnings"]), ("OK", "AUDIT_DEGRADED", ["AUDIT_DEGRADED"]))
        self.assertEqual(self.save([("PM", "value", "3", "")], store=st, profile_fail=True)["code"], "DIRECTORY_ERROR")


class SetPm(_Both):
    def test_PE17_pmo_assigns_and_changes(self):
        st = Store(**FULL)
        f = self.setpm(14, pid="3", store=st)
        self.assertEqual((f["code"], f["pm"]["employeeId"]), ("OK", 14))
        row = [w for w in self.ctx["writes"] if w[1] == "POST"][0][3]
        self.assertEqual((row["PmKey"], row["PmEmployeeLegacyId"], row["PmEmployeeItemId"]), ("PRJ-L3", "E4", 14))
        w = [r for r in self.ctx["posts"] if r["EventType"] == "WriteProxy"][0]
        self.assertEqual((w["Action"], json.loads(w["ChangeJson"])), ("Create", {"Pm": "E4", "PmOld": ""}))
        a = [r for r in st.rows(ps.PM_LIST, ProjectItemId=1)][0]
        f = self.setpm(13, etag=a["odata.etag"], store=st)
        self.assertEqual(f["code"], "OK")
        w = [r for r in self.ctx["posts"] if r["EventType"] == "WriteProxy"][0]
        self.assertEqual((w["Action"], json.loads(w["ChangeJson"])), ("Update", {"Pm": "E3", "PmOld": "E2"}))
        self.assertEqual(self.setpm(12, etag=a["odata.etag"], store=st)["code"], "NO_CHANGE")
        self.assertEqual(self.ctx["writes"], [])

    def test_PE18_pm_assignment_refusals(self):
        st = Store(**FULL)
        a = st.rows(ps.PM_LIST, ProjectItemId=1)[0]["odata.etag"]
        self.assertEqual(self.setpm(15, etag=a, store=st)["code"], "VALIDATION_LOOKUP", "inactive employee")
        self.assertEqual(self.setpm(99, etag=a, store=st)["code"], "VALIDATION_LOOKUP", "unknown employee")
        self.assertEqual(self.setpm("peer@x", etag=a, store=st)["code"], "VALIDATION_LOOKUP", "arbitrary UPN is not a PM identity")
        self.assertEqual(self.setpm(13, etag='"1,9"', store=st)["code"], "CONFLICT", "stale ETag")
        self.assertEqual(self.setpm(13, etag="", store=st)["code"], "CONFLICT", "assignment exists, empty ETag")
        self.assertEqual(self.setpm(13, pid="99", store=st)["code"], "NOT_FOUND")
        for r in ("EXE", "ADM", "ITS", "TL", "APR", "HR", "EMP"):
            self.assertEqual(self.setpm(13, etag=a, roles=("EMP", r), store=st)["code"], "ROLE_NOT_ALLOWED", r)
            self.assertEqual(self.ctx["writes"], [])
        f = self.setpm(13, etag=a, store=st, decoys={"PmUpn": tg.u("far"), "Role": "PMO"}, roles=("EMP",))
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED", "forged role / PM claims ignored")
        race = Store(race={st.rows(ps.PM_LIST, ProjectItemId=1)[0]["Id"]}, **FULL)
        self.assertEqual(self.setpm(13, etag=race.rows(ps.PM_LIST, ProjectItemId=1)[0]["odata.etag"], store=race)["code"], "CONFLICT", "race")
        f = self.setpm(13, etag=a, store=st, fail_audit=("WriteProxy",))
        self.assertEqual((f["code"], f["auditStatus"]), ("OK", "AUDIT_DEGRADED"))


class Boundaries(unittest.TestCase):
    def _all(self, x, out):
        if isinstance(x, dict):
            for k, v in x.items():
                self._all(v, out)
        elif isinstance(x, list):
            for v in x:
                self._all(v, out)
        elif isinstance(x, str):
            out.append(x)
        return out

    def test_PE19_lists_touched_and_m1_separation(self):
        for name, fl in (("read", READ), ("save", SAVE), ("setpm", SETPM)):
            text = "\n".join(self._all(fl, []))
            lists = set(re.findall(r"getbytitle\('([^']*)'\)", text))
            self.assertNotIn("HourRegistrations", text, name)
            self.assertTrue(lists <= {"Projects", "AppSettings", "Disciplines", tg.EMP_LIST, ps.PM_LIST, ps.ALLOC_LIST, "TimesheetEntries",
                                      "_Audit", "_ConfAudit"}, (name, lists))
            for m in re.findall(r"getbytitle\('(TimesheetEntries)'\)[^\n]*", text):
                pass
            self.assertFalse(re.search(r"(?i)approv[ae]d?By|ApprovalStatus|Unlock|\bLock\b", text.replace("EntryStatus eq 'Approved'", "")), name)
        # writes only to the two new lists
        for fl in (SAVE, SETPM):
            posts = re.findall(r"\"parameters/method\": \"POST\", \"parameters/uri\": \"_api/web/lists/getbytitle\('([^']*)'\)", json.dumps(fl))
            self.assertTrue(set(posts) <= {ps.ALLOC_LIST, ps.PM_LIST, "_Audit", "_ConfAudit"}, posts)

    def test_PE20_no_retry_on_writes_and_no_delete(self):
        text = json.dumps([READ, SAVE, SETPM])
        self.assertNotIn('"DELETE"', text)
        self.assertNotIn('"X-HTTP-Method": "DELETE"', text)


class Eager(Read, Save, SetPm):
    """The same scenarios with eager branch evaluation (the flows must not depend on lazy if())."""
    branches = "eager"


if __name__ == "__main__":
    unittest.main()
