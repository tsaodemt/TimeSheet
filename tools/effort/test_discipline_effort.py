"""R3 M3 EPIC 17 Discipline Effort: reference (discipline_effort) vs generated flows (build_discipline_flows) in the WDL simulator,
one SharePoint-like store per side. Tests DE01-DE24 (offline; synthetic data only)."""
import copy
import json
import os
import re
import sys
import unittest
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "approval")):
    sys.path.insert(0, p)
import build_discipline_flows as bf  # noqa: E402
import de_rules as dr  # noqa: E402
import de_schema as ds  # noqa: E402
import discipline_effort as DE  # noqa: E402
import guard as G  # noqa: E402
import pe_schema as ps  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

NOW = "2026-10-10T01:02:03Z"
SITE = "https://tenant-a.invalid/sites/x"
KW = dict(role_groups=tg.ROLE_GROUPS, site=SITE, domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit", conf_audit_list="_ConfAudit",
          environment="STAGING")
READ, SAVE, APPROVE = bf.read_actions(**KW), bf.save_actions(**KW), bf.approve_actions(**KW)
POLICY = G.Policy.from_scope_config(dr.scope_config())
ME = tg.u("peer")  # employee 12, discipline D1
ENTITY = {ds.REG_LIST: "SP.Data.DisciplineEffortRegistrationsListItem", ds.LOCK_LIST: "SP.Data.DisciplineEffortLocksListItem"}
AUDIT_KEYS = ("EventType", "Action", "Decision", "ResultCode", "TargetItemId", "TargetLegacyId")
DISCS = {1: ("D-L1", "D1", "Disc 1"), 2: ("D-L2", "D2", "Disc 2"), 3: ("D-L3", "D3", "Disc 3")}
CODE2ID = {v[1]: k for k, v in DISCS.items()}


def num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def emp_row(e):
    did = CODE2ID.get(e.discipline_id)
    disc = {"Id": did, "LegacyId": DISCS[did][0], "DisciplineCode": DISCS[did][1], "Title": DISCS[did][2]} if did else None
    return {"Id": e.item_id, "LegacyId": e.legacy_id, "Title": "Name %s" % e.legacy_id, "IsActive": e.is_active, "Discipline": disc}


EMP_ROWS = {e.item_id: emp_row(e) for e in tg.EMPS}


class Store:
    def __init__(self, regs=(), allocs=((1, "D:D-L1", 10),), assign=(), entries=(), page=3, fail=(), race=(), lock_busy=False, settings=None):
        self.projects = {i: {"Id": i, "LegacyId": "PRJ-L%d" % i, "ProjectCode": "P%d" % i, "Title": "Project %d" % i} for i in (1, 2)}
        self.wts = {1: {"Id": 1, "LegacyId": "WT-L1", "WorkTypeCode": "WT1", "Title": "Work 1", "IsActive": True},
                    2: {"Id": 2, "LegacyId": "WT-L2", "WorkTypeCode": "WT2", "Title": "Work 2", "IsActive": True},
                    3: {"Id": 3, "LegacyId": "WT-L3", "WorkTypeCode": "WT3", "Title": "Old work", "IsActive": False}}
        self.settings = {"HoursPerManDay": "8", ps.RECIPIENT_SETTING: "D1,D2"} if settings is None else settings
        self.lists = {ds.REG_LIST: {}, ds.LOCK_LIST: {}, ps.ALLOC_LIST: {}, ps.PM_LIST: {}}
        self.ver, self.next_id = {}, 1
        for pid, key, v in allocs:
            self._put(ps.ALLOC_LIST, {"ProjectItemId": pid, "RecipientKey": key, "Effort": num(v)})
        for pid, emp in assign:
            self._put(ps.PM_LIST, {"ProjectItemId": pid, "PmEmployeeItemId": emp})
        for pid, emp, wt, v, st in regs:
            e = EMP_ROWS[emp]
            key = ds.reg_key("PRJ-L%d" % pid, e["LegacyId"], self.wts[wt]["LegacyId"])
            self._put(ds.REG_LIST, {"RegKey": key, "LegacyId": key, "ProjectItemId": pid, "EmployeeItemId": emp, "EmployeeLegacyId": e["LegacyId"],
                                    "DisciplineCode": e["Discipline"]["DisciplineCode"], "DisciplineLegacyId": e["Discipline"]["LegacyId"],
                                    "DisciplineItemId": e["Discipline"]["Id"], "WorkTypeItemId": wt, "WorkTypeLegacyId": self.wts[wt]["LegacyId"],
                                    "Effort": num(v), "Status": st})
        self.entries = [{"Id": i, "ProjectId": p, "Hours": h, "EntryStatus": s, "DisciplineCode": d} for i, p, h, s, d in entries]
        self.page, self.fail, self.race, self.lock_busy = page, set(fail), set(race), lock_busy

    def _put(self, lst, f):
        i = self.next_id
        self.next_id += 1
        self.lists[lst][i] = dict(f, Id=i)
        self.ver[i] = 1
        return i

    def etag(self, lst, i):
        return '"%d,%d"' % (i, self.ver[i])

    def rows(self, lst, **flt):
        return [dict(r, **{"odata.etag": self.etag(lst, i)}) for i, r in sorted(self.lists[lst].items()) if all(r.get(k) == v for k, v in flt.items())]

    # ---- reference write API
    def create(self, lst, fields):
        if any(r.get("RegKey") == fields["RegKey"] for r in self.lists[lst].values()) or "dup" in self.fail:
            raise DE.ConflictError()
        keep = {k: v for k, v in fields.items() if k not in ("Title", "ProjectId", "EmployeeId", "DisciplineId", "WorkTypeId", "ActorUpn", "CorrelationId", "OwnerUpn")}
        keep["Effort"] = num(keep["Effort"])
        i = self._put(lst, keep)
        return i, self.etag(lst, i)

    def update(self, lst, i, fields, if_match):
        if i in self.race:
            self.ver[i] += 1
            self.race.discard(i)
        if if_match != "*" and if_match != self.etag(lst, i):
            raise DE.ConflictError()
        for k, v in fields.items():
            if k in ("Effort",):
                self.lists[lst][i][k] = num(v)
            elif k in ("Status", "ApprovedBy", "ApprovedOn", "Busy", "BusyUntil", "Stamp"):
                self.lists[lst][i][k] = v
        self.ver[i] += 1

    def claim(self, key, pid, did, cid, now):
        if "lockfail" in self.fail:
            raise DE.ConflictError()
        rows = [r for r in self.lists[ds.LOCK_LIST].values() if r["LockKey"] == key]
        if not rows:
            self._put(ds.LOCK_LIST, {"LockKey": key, "LegacyId": key, "ProjectItemId": pid, "DisciplineItemId": did, "Busy": False, "Stamp": cid})
            rows = [r for r in self.lists[ds.LOCK_LIST].values() if r["LockKey"] == key]
        r = rows[0]
        if self.lock_busy or (r.get("Busy") and (r.get("BusyUntil") or "") > now):
            raise DE.ConflictError()
        self.update(ds.LOCK_LIST, r["Id"], {"Busy": True, "BusyUntil": "2026-10-10T01:12:03Z", "Stamp": cid}, self.etag(ds.LOCK_LIST, r["Id"]))

    def release(self, key):
        r = [r for r in self.lists[ds.LOCK_LIST].values() if r["LockKey"] == key][0]
        self.update(ds.LOCK_LIST, r["Id"], {"Busy": False}, "*")


class Data:
    def __init__(self, s):
        self.s = s

    def _f(self, k):
        if k in self.s.fail:
            raise ConnectionError("503")

    def project(self, pid):
        self._f("project")
        return self.s.projects.get(pid)

    def assignment(self, pid):
        self._f("assign")
        r = self.s.rows(ps.PM_LIST, ProjectItemId=pid)
        return r[0] if r else None

    def employee(self, eid):
        self._f("me")
        e = EMP_ROWS.get(eid)
        if e is None:
            return None
        d = e["Discipline"] or {}
        return {"Id": e["Id"], "LegacyId": e["LegacyId"], "Title": e["Title"], "IsActive": e["IsActive"], "DisciplineCode": d.get("DisciplineCode")}

    def employees(self):
        return [{"Id": e["Id"], "Title": e["Title"]} for e in EMP_ROWS.values()]

    def settings(self):
        return dict(self.s.settings)

    def disciplines(self):
        return [{"Id": k, "LegacyId": v[0], "DisciplineCode": v[1], "Title": v[2]} for k, v in DISCS.items()]

    def worktypes(self):
        return list(self.s.wts.values())

    def rows(self, pid):
        self._f("regs")
        return [dict(r, etag=r["odata.etag"]) for r in self.s.rows(ds.REG_LIST, ProjectItemId=pid)]

    def reg(self, i):
        r = self.s.lists[ds.REG_LIST].get(i)
        return dict(r, etag=self.s.etag(ds.REG_LIST, i)) if r else None

    def allocations(self, pid):
        self._f("allocs")
        return self.s.rows(ps.ALLOC_LIST, ProjectItemId=pid)

    def approved_hours_by_discipline(self, pid):
        if "pages" in self.s.fail:
            raise ConnectionError("503")
        out = {}
        for e in self.s.entries:
            if e["ProjectId"] == pid and e["EntryStatus"] == "Approved":
                out[e["DisciplineCode"]] = out.get(e["DisciplineCode"], 0.0) + float(e["Hours"] or 0)
        return out


_EQ = re.compile(r"(\w+) eq (-?\d+)")
_EQS = re.compile(r"(\w+) eq '([^']*)'")


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
        sconds = dict(_EQS.findall(flt))
        if lst == tg.EMP_LIST:
            if "AccountUpn eq" in uri:
                return "Succeeded", wdl_sim.sharepoint_get(raw, {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)})
            if m:
                if "me" in s.fail:
                    return "Failed", {"statusCode": 503}
                e = EMP_ROWS.get(int(m.group(1)))
                return ("Succeeded", copy.deepcopy(e)) if e else ("Failed", {"statusCode": 404})
            return "Succeeded", {"value": [{"Id": e["Id"], "Title": e["Title"]} for e in EMP_ROWS.values()]}
        if lst == "Projects":
            if "project" in s.fail:
                return "Failed", {"statusCode": 503}
            pr = s.projects.get(int(m.group(1)))
            return ("Succeeded", dict(pr)) if pr else ("Failed", {"statusCode": 404})
        if lst == "AppSettings":
            return "Succeeded", {"value": [{"Title": k, "Value": v} for k, v in s.settings.items()]}
        if lst == "Disciplines":
            return "Succeeded", {"value": Data(s).disciplines()}
        if lst == "WorkTypes":
            return "Succeeded", {"value": [dict(w) for w in sorted(s.wts.values(), key=lambda w: w["Id"])]}
        if lst == "TimesheetEntries":
            assert method == "GET" and "EntryStatus eq 'Approved'" in uri and "$select=Id,Hours,DisciplineCode&" in uri, uri
            if "pages" in s.fail and "skiptoken" in uri:
                return "Failed", {"statusCode": 503}
            after = int(re.findall(r"p_ID=(\d+)", uri)[-1]) if "skiptoken" in uri else 0
            rows = [e for e in s.entries if e["ProjectId"] == conds["ProjectId"] and e["EntryStatus"] == "Approved" and e["Id"] > after]
            pg = rows[:s.page]
            out = {"value": [{"Id": e["Id"], "Hours": e["Hours"], "DisciplineCode": e["DisciplineCode"]} for e in pg]}
            if len(rows) > s.page:
                first = re.sub(r"&%24skiptoken=[^&]*", "", raw)
                out["odata.nextLink"] = "%s/%s&%%24skiptoken=Paged%%3DTRUE%%26p_ID%%3D%d" % (SITE, first, pg[-1]["Id"])
            return "Succeeded", out
        if lst in (ps.ALLOC_LIST, ps.PM_LIST):
            if (lst == ps.ALLOC_LIST and "allocs" in s.fail) or (lst == ps.PM_LIST and "assign" in s.fail):
                return "Failed", {"statusCode": 503}
            return "Succeeded", {"value": s.rows(lst, **conds)}
        assert lst in (ds.REG_LIST, ds.LOCK_LIST), uri
        if method == "GET" and uri.endswith("?$select=ListItemEntityTypeFullName"):
            return "Succeeded", {"ListItemEntityTypeFullName": ENTITY[lst]}
        if method == "GET" and m:
            i = int(m.group(1))
            r = s.lists[lst].get(i)
            return ("Succeeded", dict(r, **{"odata.etag": s.etag(lst, i)})) if r else ("Failed", {"statusCode": 404})
        if method == "GET":
            if lst == ds.REG_LIST and "regs" in s.fail:
                return "Failed", {"statusCode": 503}
            if lst == ds.LOCK_LIST:
                rows = s.rows(lst, LockKey=sconds.get("LockKey"))
                if s.lock_busy:
                    rows = [dict(r, Busy=True, BusyUntil="2099-01-01T00:00:00Z") for r in rows] or [{"Id": 999, "LockKey": sconds.get("LockKey"), "Busy": True,
                                                                                                   "BusyUntil": "2099-01-01T00:00:00Z", "odata.etag": '"999,1"'}]
                return "Succeeded", {"value": rows}
            return "Succeeded", {"value": s.rows(lst, **conds)}
        body = json.loads(p["parameters/body"])
        h = p["parameters/headers"]
        assert a["inputs"]["retryPolicy"] == {"type": "none"} and body["__metadata"]["type"] == ENTITY[lst]
        fields = {k: v for k, v in body.items() if k != "__metadata"}
        if m:
            assert h["X-HTTP-Method"] == "MERGE"
            writes.append((lst, "MERGE", int(m.group(1)), fields))
            if lst == ds.LOCK_LIST and "lockfail" in s.fail:
                return "Failed", {"statusCode": 412}
            try:
                s.update(lst, int(m.group(1)), fields, h["IF-MATCH"])
            except DE.ConflictError:
                return "Failed", {"statusCode": 412}
            return "Succeeded", None
        writes.append((lst, "POST", None, fields))
        if lst == ds.LOCK_LIST:
            i = s._put(lst, {k: v for k, v in fields.items() if k != "Title"})
            return "Succeeded", {"d": {"Id": i, "__metadata": {"etag": s.etag(lst, i)}}}
        try:
            i, etag = s.create(lst, fields)
        except DE.ConflictError:
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
    return json.dumps([{"workTypeId": w, "state": st, "value": v, "etag": et} for w, st, v, et in cells])


def akeys(rows):
    return [tuple(str(r.get(k, "")) for k in AUDIT_KEYS) for r in rows]


def regs_of(s):
    return {(r["ProjectItemId"], r["EmployeeItemId"], r["WorkTypeItemId"]): (r["Effort"], r["Status"]) for r in s.lists[ds.REG_LIST].values()}


class _Both(unittest.TestCase):
    maxDiff = None
    branches = None

    def _run(self, actions, trig, upn, roles, fs, cid, profile_fail, fail_audit):
        posts, writes, uris = [], [], []
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW, branches=self.branches,
                          mocks=mocks_for(upn, roles, fs, posts, writes, uris, profile_fail=profile_fail, fail_audit=fail_audit)).run(actions)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        return resp, posts, writes, uris

    def read(self, roles=("EMP",), pid="1", store=None, upn=ME, decoys=None, cid="run-r", profile_fail=False):
        fs = copy.deepcopy(store or Store())
        rs = copy.deepcopy(fs)
        trig = {"text": pid}
        trig.update({"text_%d" % (1 + i): (decoys or {}).get(k, "") for i, k in enumerate(DE.READ_DECOYS)})
        resp, posts, writes, uris = self._run(READ, trig, upn, roles, fs, cid, profile_fail, ())
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "scope": resp["scope"], "project": json.loads(resp["project"]),
             "caller": json.loads(resp["caller"]), "rows": sorted(json.loads(resp["rows"]), key=lambda r: r["id"]), "summary": json.loads(resp["summary"]),
             "workTypes": json.loads(resp["worktypes"])}
        r = DE.read(guard(upn, roles, cid, dr.VIEW, decoys), dict({"ProjectItemId": pid}, **(decoys or {})), Data(rs), correlation_id=cid, profile_failed=profile_fail)
        r["rows"] = sorted(r["rows"], key=lambda x: x["id"])
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
            self.assertEqual(akeys(posts), akeys(r["audit"]), "audit rows")
        self.ctx = dict(posts=posts, writes=writes, uris=uris, resp=resp, store=fs)
        return f

    def save(self, cells=None, roles=("EMP",), pid="1", store=None, upn=ME, decoys=None, cid="run-s", raw=None, profile_fail=False, fail_audit=()):
        fs = copy.deepcopy(store or Store())
        rs = copy.deepcopy(fs)
        changes = raw if raw is not None else ch(*cells)
        trig = {"text": pid, "text_1": changes, "text_2": "client-1"}
        trig.update({"text_%d" % (3 + i): (decoys or {}).get(k, "") for i, k in enumerate(DE.SAVE_DECOYS)})
        resp, posts, writes, uris = self._run(SAVE, trig, upn, roles, fs, cid, profile_fail, fail_audit)
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "savedCount": int(resp["savedcount"]),
             "results": sorted(json.loads(resp["results"]), key=lambda x: x["workTypeId"]), "ceiling": resp["ceiling"], "used": resp["used"],
             "remaining": resp["remaining"], "auditStatus": resp["auditstatus"], "warnings": json.loads(resp["warnings"])}
        r = DE.save(guard(upn, roles, cid, dr.EDIT, decoys), dict({"ProjectItemId": pid, "Changes": changes}, **(decoys or {})), Data(rs), rs,
                    correlation_id=cid, now=NOW, profile_failed=profile_fail, row_audit_ok=lambda k: "WriteProxy" not in fail_audit)
        r["results"] = sorted(r["results"], key=lambda x: x["workTypeId"])
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
            self.assertEqual(sorted(akeys(posts)), sorted(akeys(r["audit"])), "audit rows")
            self.assertEqual(regs_of(fs), regs_of(rs), "stored registrations")
            self.assertTrue(all(not x.get("Busy") for x in fs.lists[ds.LOCK_LIST].values() if x["Id"] != 999), "lock released")
        self.ctx = dict(posts=posts, writes=writes, uris=uris, resp=resp, store=fs)
        return f

    def approve(self, items, roles=("EMP", "TL"), store=None, upn=ME, decoys=None, cid="run-a", raw=None, fail_audit=()):
        fs = copy.deepcopy(store or Store())
        rs = copy.deepcopy(fs)
        txt = raw if raw is not None else json.dumps([{"itemId": i, "etag": e} for i, e in items])
        trig = {"text": txt, "text_1": "client-1"}
        trig.update({"text_%d" % (2 + i): (decoys or {}).get(k, "") for i, k in enumerate(DE.APPROVE_DECOYS)})
        resp, posts, writes, uris = self._run(APPROVE, trig, upn, roles, fs, cid, False, fail_audit)
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "approvedCount": int(resp["approvedcount"]),
             "results": sorted([{k: v for k, v in x.items() if k != "etag"} for x in json.loads(resp["results"])], key=lambda x: x["itemId"]),
             "auditStatus": resp["auditstatus"]}
        r = DE.approve(guard(upn, roles, cid, dr.APPROVE, decoys), dict({"Items": txt}, **(decoys or {})), Data(rs), rs, correlation_id=cid, now=NOW,
                       row_audit_ok=lambda k: "Approval" not in fail_audit)
        r["results"] = sorted([{k: v for k, v in x.items() if k != "etag"} for x in r["results"]], key=lambda x: x["itemId"])
        self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.assertEqual(sorted(akeys(posts)), sorted(akeys(r["audit"])), "audit rows")
        self.assertEqual({k: v[1] for k, v in regs_of(fs).items()}, {k: v[1] for k, v in regs_of(rs).items()})
        self.ctx = dict(posts=posts, writes=writes, uris=uris, resp=resp, store=fs)
        return f


TS = [(1, 1, 8, "Approved", "D1"), (2, 1, 4, "Draft", "D1"), (3, 1, 2.5, "Approved", "D2"), (4, 1, 1.5, "Approved", "D1"), (5, 2, 3, "Approved", "D1"),
      (6, 1, 2, "Deleted", "D1")]
BASE = dict(regs=((1, 11, 1, 4, ds.DRAFT), (1, 13, 1, 2, ds.DRAFT), (1, 12, 2, 1, ds.APPROVED), (1, 16, 1, None, ds.DRAFT)), entries=TS)


def item_of(s, emp, wt, pid=1):
    return next((i, s.etag(ds.REG_LIST, i)) for i, r in s.lists[ds.REG_LIST].items() if (r["ProjectItemId"], r["EmployeeItemId"], r["WorkTypeItemId"]) == (pid, emp, wt))


class Schema(unittest.TestCase):
    def test_DE01_schema_portable_keys_no_forbidden(self):
        for lst, fields in ds.LISTS.items():
            self.assertFalse({f[0] for f in fields} & ds.FORBIDDEN_COLUMNS, lst)
            self.assertTrue(ds.field(lst, "LegacyId")[4])
        self.assertEqual(ds.field(ds.REG_LIST, "Status")[5]["Choices"], ["Draft", "ApprovedLocked"])
        self.assertFalse(ds.field(ds.REG_LIST, "Effort")[2], "nullable: blank != 0")
        self.assertEqual(ds.reg_key("P", "E", "W"), "P|E|W")
        self.assertFalse(ds.SERVICE_RIGHTS & ds.NEVER)
        self.assertNotIn("Total", json.dumps(ds.LOCK_FIELDS), "the lock item holds no business total")

    def test_DE02_capability_matrix(self):
        sc = dr.scope_config()["scopes"]
        self.assertEqual({r: sc[r][dr.VIEW] for r in dr.ROLES if sc[r][dr.VIEW] != "none"}, {"EMP": "self", "TL": "discipline", "PMO": "company", "EXE": "company"})
        self.assertEqual({r: sc[r][dr.EDIT] for r in dr.ROLES if sc[r][dr.EDIT] != "none"}, {"EMP": "self", "TL": "self"})
        self.assertEqual({r: sc[r][dr.APPROVE] for r in dr.ROLES if sc[r][dr.APPROVE] != "none"}, {"TL": "discipline"})
        for r in ("APR", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO"):
            self.assertTrue(all(sc[r][cap] == "none" for cap in (dr.VIEW, dr.EDIT, dr.APPROVE)), r)

    def test_DE03_exact_cents(self):
        self.assertEqual((DE.cents("0.1") + DE.cents("0.2"), DE.cents("0.3")), (30, 30))
        self.assertEqual([DE.md(x) for x in (0, 5, 50, 1250, 1201, -25, 100000000012)], ["0", "0.05", "0.5", "12.5", "12.01", "-0.25", "1000000000.12"])


class Read(_Both):
    def test_DE04_employee_own_rows_and_own_discipline_totals(self):
        f = self.read(("EMP",), store=Store(**BASE))
        self.assertEqual((f["code"], f["scope"]), ("OK", "self"))
        self.assertEqual([(r["employeeId"], r["workTypeId"], r["status"]) for r in f["rows"]], [(12, 2, "ApprovedLocked")])
        self.assertEqual(f["summary"], [{"disciplineCode": "D1", "disciplineName": "Disc 1", "ceilingState": "VALUE", "ceiling": "10", "used": "5",
                                         "remaining": "5", "actualHours": "9.5", "actualManDays": "1.1875"}], "aggregate totals only; Approved actual only")
        self.assertEqual(f["caller"], {"employeeId": 12, "disciplineCode": "D1", "canEdit": True, "canApprove": False})
        self.assertEqual([w["id"] for w in f["workTypes"]], [1, 2], "inactive WorkType not offered")

    def test_DE05_team_leader_discipline_rows(self):
        f = self.read(("EMP", "TL"), store=Store(**BASE))
        self.assertEqual((f["scope"], sorted({r["disciplineCode"] for r in f["rows"]}), len(f["rows"])), ("discipline", ["D1"], 3))
        self.assertTrue(f["caller"]["canApprove"])

    def test_DE06_pmo_executive_company_and_pm_project(self):
        for roles in (("EMP", "PMO"), ("EMP", "EXE")):
            f = self.read(roles, store=Store(**BASE))
            self.assertEqual((f["scope"], len(f["rows"]), [s["disciplineCode"] for s in f["summary"]]), ("company", 4, ["D1", "D2"]))
            self.assertEqual(f["summary"][1]["ceilingState"], "BLANK")
        f = self.read((), store=Store(assign=((1, 12),), **BASE), upn=ME)
        self.assertEqual((f["code"], f["scope"], len(f["rows"])), ("OK", "project-pm", 4), "designated EPIC 16 PM sees the project")
        f = self.read((), pid="2", store=Store(assign=((1, 12),), **BASE))
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED", "PM of another project only")

    def test_DE07_denied_roles(self):
        for r in ("APR", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO"):
            f = self.read((r,), store=Store(**BASE))
            self.assertEqual((f["code"], f["rows"], f["summary"]), ("ROLE_NOT_ALLOWED", [], []), r)
        self.assertEqual(self.read(("EMP", "PMO"), store=Store(**BASE), upn=tg.u("gone"))["code"], "INACTIVE_EMPLOYEE")

    def test_DE08_no_timesheet_leak_and_paging(self):
        many = [(i, 1, 1.5, "Approved" if i % 3 else "Draft", "D1") for i in range(1, 31)]
        f = self.read(("EMP",), store=Store(entries=many, page=4, regs=BASE["regs"]))
        self.assertEqual(f["summary"][0]["actualHours"], "30")
        text = json.dumps(self.ctx["resp"])
        for bad in ("EntryStatus", "OwnerUpn", "WorkDate"):
            self.assertNotIn(bad, text)
        f = self.read(("EMP",), store=Store(entries=many, page=4, regs=BASE["regs"], fail={"pages"}))
        self.assertEqual(f["code"], "ERROR")


class Save(_Both):
    def test_DE09_own_draft_values_blank_zero_decimals(self):
        st = Store(**BASE)
        f = self.save([(1, "value", "0", "")], store=st)
        self.assertEqual((f["code"], f["used"], f["remaining"]), ("OK", "5", "5"), "explicit 0 stored, total unchanged")
        f = self.save([(1, "value", "2.25", "")], store=st)
        self.assertEqual(regs_of(self.ctx["store"])[(1, 12, 1)], (2.25, "Draft"))
        new = [w for w in self.ctx["writes"] if w[1] == "POST" and w[0] == ds.REG_LIST][0][3]
        self.assertEqual((new["RegKey"], new["DisciplineCode"], new["EmployeeItemId"], new["WorkTypeLegacyId"]), ("PRJ-L1|E2|WT-L1", "D1", 12, "WT-L1"))
        for v, code in (("1.255", "VALIDATION_VALUE"), ("-1", "VALIDATION_VALUE"), ("1,5", "VALIDATION_VALUE"), ("1234567890123456", "TECHNICAL_LIMIT")):
            f = self.save([(1, "value", v, "")], store=st)
            self.assertEqual((f["code"], f["results"][0]["resultcode"]), ("REFUSED", code), v)
            self.assertEqual([w for w in self.ctx["writes"] if w[0] == ds.REG_LIST], [])

    def test_DE10_ceiling_below_exact_above(self):
        st = Store(**BASE)  # D1 ceiling 10; used 4 (emp 11) + 1 (me, approved)
        self.assertEqual(self.save([(1, "value", "4", "")], store=st)["code"], "OK")
        f = self.save([(1, "value", "5", "")], store=st)
        self.assertEqual((f["code"], f["used"], f["remaining"]), ("OK", "10", "0"), "exactly at the ceiling")
        f = self.save([(1, "value", "5.01", "")], store=st)
        self.assertEqual((f["code"], f["results"][0]["resultcode"], f["remaining"]), ("REFUSED", "OVER_CEILING", "5"))
        self.assertEqual([w for w in self.ctx["writes"] if w[0] == ds.REG_LIST], [])

    def test_DE11_multi_row_aggregate_and_reduction_over_ceiling(self):
        st = Store(regs=((1, 11, 1, 8, ds.DRAFT), (1, 12, 1, 3, ds.DRAFT)), allocs=((1, "D:D-L1", 10),))  # already 11 > 10 (A.I.3 lowered)
        i, et = item_of(st, 12, 1)
        f = self.save([(1, "value", "2.5", et)], store=st)
        self.assertEqual((f["code"], f["used"], f["remaining"]), ("OK", "10.5", "-0.5"), "a reduction is allowed even while over")
        f = self.save([(2, "value", "1", "")], store=st)
        self.assertEqual(f["results"][0]["resultcode"], "OVER_CEILING")
        f = self.save([(1, "value", "1", et), (2, "value", "0.5", "")], store=st)
        self.assertEqual(f["code"], "OK", "multi-row change judged on the resulting aggregate (11 -> 9.5)")

    def test_DE12_blank_ceiling(self):
        st = Store(regs=(), allocs=((1, "D:D-L2", 5),))
        f = self.save([(1, "value", "1", "")], store=st)
        self.assertEqual((f["code"], f["results"][0]["resultcode"], f["ceiling"]), ("REFUSED", "CEILING_NOT_REGISTERED", ""))
        st2 = Store(regs=((1, 12, 1, 2, ds.DRAFT),), allocs=())
        i, et = item_of(st2, 12, 1)
        self.assertEqual(self.save([(1, "blank", "", et)], store=st2)["code"], "OK", "clearing is allowed without a ceiling")

    def test_DE13_scope_lock_worktype_conflict(self):
        st = Store(**BASE)
        i, et = item_of(st, 12, 2)
        self.assertEqual(self.save([(2, "value", "2", et)], store=st)["results"][0]["resultcode"], "LOCKED", "ApprovedLocked immutable")
        self.assertEqual(self.save([(3, "value", "1", "")], store=st)["results"][0]["resultcode"], "VALIDATION_LOOKUP", "inactive WorkType")
        self.assertEqual(self.save([(9, "value", "1", "")], store=st)["results"][0]["resultcode"], "VALIDATION_LOOKUP")
        self.assertEqual(self.save([(1, "value", "1", '"9,9"')], store=st)["results"][0]["resultcode"], "CONFLICT")
        f = self.save([(1, "value", "1", "")], store=st, decoys={"DisciplineCode": "D2", "EmployeeId": "13", "OwnerUpn": "x"})
        self.assertEqual(f["code"], "OK")
        self.assertEqual(regs_of(self.ctx["store"])[(1, 12, 1)], (1, "Draft"), "own row, own discipline whatever the claims")
        for r in ("APR", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO", "PMO", "EXE"):
            self.assertEqual(self.save([(1, "value", "1", "")], roles=(r,), store=st)["code"], "ROLE_NOT_ALLOWED", r)
        self.assertEqual(self.save([(1, "value", "1", "")], store=st, upn=tg.u("nodisc"))["code"], "VALIDATION_LOOKUP", "no discipline")
        for raw in ("", "x", "[]", json.dumps([{"workTypeId": 1, "state": "blank"}] * 2)):
            self.assertEqual(self.save(raw=raw, store=st)["code"], "VALIDATION_REQUEST")

    def test_DE14_concurrency_lock(self):
        f = self.save([(1, "value", "1", "")], store=Store(lock_busy=True, **BASE))
        self.assertEqual((f["code"], self.ctx["writes"]), ("CONFLICT", []), "busy lock: concurrent saver refused, 0 writes")
        f = self.save([(1, "value", "1", "")], store=Store(fail={"lockfail"}, **BASE))
        self.assertEqual(f["code"], "CONFLICT", "lost the lock claim (412)")
        st = Store(**BASE)
        self.save([(1, "value", "1", "")], store=st)
        locks = list(self.ctx["store"].lists[ds.LOCK_LIST].values())
        self.assertEqual((len(locks), locks[0]["LockKey"], locks[0]["Busy"]), (1, "PRJ-L1|D-L1", False), "one lock per Project x Discipline, released")

    def test_DE15_audit_and_failures(self):
        st = Store(**BASE)
        f = self.save([(1, "value", "1", "")], store=st)
        w = [r for r in self.ctx["posts"] if r["EventType"] == "WriteProxy"]
        self.assertEqual([(r["Action"], r["TargetList"]) for r in w], [("Create", ds.REG_LIST)])
        self.assertTrue(all(r["ActorUpn"] == ME for r in self.ctx["posts"]))
        f = self.save([(1, "value", "2", "")], store=st, fail_audit=("WriteProxy",))
        self.assertEqual((f["code"], f["auditStatus"]), ("OK", "AUDIT_DEGRADED"))
        for k in ("project", "regs", "allocs", "me"):
            self.assertEqual(self.save([(1, "value", "1", "")], store=Store(fail={k}, **BASE))["code"], "ERROR", k)
        self.assertEqual(self.save([(1, "value", "1", "")], pid="9", store=st)["code"], "NOT_FOUND")


class Approve(_Both):
    def test_DE16_same_discipline_and_self_approval(self):
        st = Store(regs=((1, 11, 1, 4, ds.DRAFT), (1, 12, 1, 3, ds.DRAFT)), allocs=((1, "D:D-L1", 10),))
        a, b = item_of(st, 11, 1), item_of(st, 12, 1)
        f = self.approve([a, b], store=st)
        self.assertEqual((f["code"], f["approvedCount"]), ("OK", 2), "employee row + own row (OD-28)")
        self.assertEqual({k: v[1] for k, v in regs_of(self.ctx["store"]).items()}, {(1, 11, 1): "ApprovedLocked", (1, 12, 1): "ApprovedLocked"})
        ev = [r for r in self.ctx["posts"] if r["EventType"] == "Approval"]
        self.assertEqual(len(ev), 2, "exactly one Approval event per row, no separate Lock")
        self.assertFalse(any(r["EventType"] not in ("AuthorizationAllow", "Approval") for r in self.ctx["posts"]))

    def test_DE17_refusals(self):
        st = Store(regs=((1, 13, 1, 2, ds.DRAFT), (1, 11, 1, 4, ds.APPROVED), (1, 16, 1, None, ds.DRAFT), (1, 11, 2, 1, ds.DRAFT)), allocs=((1, "D:D-L1", 10),))
        ids = [item_of(st, 13, 1), item_of(st, 11, 1), item_of(st, 16, 1), (item_of(st, 11, 2)[0], '"0,0"'), (999, '"1"')]
        f = self.approve(ids, store=st)
        self.assertEqual({r["itemId"]: r["resultcode"] for r in f["results"]},
                         dict(zip([i for i, _ in ids], ("SCOPE_NOT_ALLOWED", "LOCKED", "VALIDATION_VALUE", "CONFLICT", "NOT_FOUND"))))
        self.assertEqual(f["code"], "REFUSED")
        for r in ("EMP", "APR", "EXE", "PMO", "HR", "ADM", "ITS"):
            self.assertEqual(self.approve([item_of(st, 11, 2)], roles=(r,), store=st)["code"], "ROLE_NOT_ALLOWED", r)

    def test_DE18_approval_revalidates_ceiling(self):
        st = Store(regs=((1, 11, 1, 8, ds.DRAFT), (1, 12, 1, 3, ds.DRAFT)), allocs=((1, "D:D-L1", 10),))
        f = self.approve([item_of(st, 11, 1)], store=st)
        self.assertEqual(f["results"][0]["resultcode"], "OVER_CEILING")
        st2 = Store(regs=((1, 11, 1, 8, ds.DRAFT),), allocs=())
        self.assertEqual(self.approve([item_of(st2, 11, 1)], store=st2)["results"][0]["resultcode"], "CEILING_NOT_REGISTERED")
        st3 = Store(regs=((1, 11, 1, 2, ds.DRAFT),), race=set(), allocs=((1, "D:D-L1", 10),))
        i, et = item_of(st3, 11, 1)
        st3.race.add(i)
        self.assertEqual(self.approve([(i, et)], store=st3)["results"][0]["resultcode"], "CONFLICT", "race after the checks")

    def test_DE19_no_reopen_flow_or_operation(self):
        for fl in (READ, SAVE, APPROVE):
            t = json.dumps(fl)
            self.assertNotRegex(t, r"(?i)unapprove|reopen|unlock")
        self.assertNotIn('"Status": "Draft"', json.dumps(APPROVE), "approval never writes Draft")
        self.assertEqual(json.dumps(SAVE).count('"Status": "Draft"'), 1, "Draft only on the create body")
        self.assertNotIn("Unlock", json.dumps(dr.GRANTS))


class Boundaries(unittest.TestCase):
    def test_DE20_lists_touched_and_writes(self):
        for name, fl in (("read", READ), ("save", SAVE), ("approve", APPROVE)):
            t = json.dumps(fl)
            lists = set(re.findall(r"getbytitle\('([^']*)'\)", t))
            self.assertTrue(lists <= {"Projects", "AppSettings", "Disciplines", "WorkTypes", tg.EMP_LIST, ps.PM_LIST, ps.ALLOC_LIST, "TimesheetEntries",
                                      ds.REG_LIST, ds.LOCK_LIST, "_Audit", "_ConfAudit"}, (name, lists))
            self.assertNotIn("HourRegistrations", t)
            posts = re.findall(r"\"parameters/method\": \"POST\", \"parameters/uri\": \"_api/web/lists/getbytitle\('([^']*)'\)", t)
            self.assertTrue(set(posts) <= {ds.REG_LIST, ds.LOCK_LIST, "_Audit", "_ConfAudit"}, posts)
            self.assertNotIn('"DELETE"', t)

    def test_DE21_epic07_self_approval_still_denied(self):
        """OD-28 allows self-approval in EPIC 17 only: the EPIC 07 approval rules keep TS.SelfApprove ungranted."""
        import approval_rules as AR
        import test_approval_rules as TAR
        self.assertEqual({r.role for r in AR.MATRIX if AR.SELF_CAPABILITY in r.denied}, {"TL", "APR", "EXE"})
        self.assertFalse(any(v.get(AR.SELF_CAPABILITY) not in (None, "none") for v in AR.scope_config()["scopes"].values()))
        t = TAR.ApproveTests("test_R13_self_approve_denied_for_every_role")
        t.setUp() if hasattr(t, "setUp") else None
        t.test_R13_self_approve_denied_for_every_role()
        self.assertNotIn("TS.SelfApprove", json.dumps(dr.scope_config()))


class Eager(Read, Save, Approve):
    branches = "eager"


if __name__ == "__main__":
    unittest.main()
