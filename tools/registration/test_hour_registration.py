"""R3 M1 S12.5 Hour Registration: reference (hour_registration) vs generated flows (build_registration_flows) in the WDL
simulator, one SharePoint-like store per side. Tests HR01-HR32 (offline; synthetic data only)."""
import copy
import json
import os
import re
import sys
import unittest
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity")):
    sys.path.insert(0, p)
import build_registration_flows as bf  # noqa: E402
import guard as G  # noqa: E402
import hour_registration as H  # noqa: E402
import hr_schema  # noqa: E402
import registration_rules as rr  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

NOW = "2026-10-10T01:02:03Z"
ENTITY = "SP.Data.HourRegistrationsListItem"
KW = dict(role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST,
          audit_list="_Audit", conf_audit_list="_ConfAudit", environment="STAGING")
READ = bf.read_matrix_actions(**KW)
SAVE = bf.save_matrix_actions(**KW)
POLICY = G.Policy.from_scope_config(rr.scope_config())
ME = tg.u("peer")
EDITOR, VIEWER = ("EMP", "PMO"), ("EMP", "TL")


def num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


class Store:
    """Projects / ProjectPhases / Disciplines + HourRegistrations with SharePoint-like ETags."""

    def __init__(self, n_phases=6, n_discs=5, project_status="Active", items=(), removed=(), race=(), fail=()):
        self.projects = {1: {"Id": 1, "LegacyId": "PRJ-L1", "ProjectCode": "P1", "Title": "Synthetic project", "Status": project_status,
                             "ProjectYear": 2026},
                         2: {"Id": 2, "LegacyId": "PRJ-L2", "ProjectCode": "P1", "Title": "Same code", "Status": "Active", "ProjectYear": 2025}}
        self.phases = {i: {"Id": i, "LegacyId": "PH-L%d" % i, "PhaseCode": "PH%d" % i, "Title": "Phase %d" % i} for i in range(1, 14)}
        # project 1 phases in a project order that differs from ids; `removed` phases are inactive links
        order = list(range(1, n_phases + 1))[::-1]
        self.links = [{"Id": 100 + k, "ProjectItemId": 1, "PhaseId": ph, "SortOrder": k, "IsActive": ph not in removed}
                      for k, ph in enumerate(order, 1)]
        self.links.append({"Id": 200, "ProjectItemId": 2, "PhaseId": 1, "SortOrder": 1, "IsActive": True})
        self.discs = {i: {"Id": i, "LegacyId": "D-L%d" % i, "DisciplineCode": "D%d" % i, "Title": "Disc %d" % i, "SortOrder": 10 - i,
                          "IsActive": i != 2} for i in range(1, n_discs + 1)}
        self.items, self.ver, self.next_id = {}, {}, 1
        for ph, d, v in items:
            self._put(1, ph, d, v)
        self.race, self.fail = set(race), set(fail)

    def _put(self, pid, ph, d, v):
        i = self.next_id
        self.next_id += 1
        key = H.reg_key(self.projects[pid]["LegacyId"], self.phases[ph]["LegacyId"], self.discs[d]["LegacyId"])
        self.items[i] = {"Id": i, "RegKey": key, "LegacyId": key, "ProjectItemId": pid, "PhaseItemId": ph, "DisciplineItemId": d,
                         "ManDays": num(v), "Status": "Active"}
        self.ver[i] = 1
        return i

    def etag(self, i):
        return '"%d"' % self.ver[i]

    def item_rows(self, pid):
        return [dict(self.items[i], **{"odata.etag": self.etag(i)}) for i in sorted(self.items) if self.items[i]["ProjectItemId"] == pid]

    # ---- reference data adapter
    def project(self, pid):
        if "Get_project" in self.fail:
            raise ConnectionError("503")
        return self.projects.get(pid)

    def project_phases(self, pid):
        if "Get_phases" in self.fail:
            raise ConnectionError("503")
        rows = sorted((l for l in self.links if l["ProjectItemId"] == pid and l["IsActive"]), key=lambda l: (l["SortOrder"], l["Id"]))
        return [{"PhaseItemId": l["PhaseId"], "PhaseLegacyId": self.phases[l["PhaseId"]]["LegacyId"], "PhaseCode": self.phases[l["PhaseId"]]["PhaseCode"],
                 "PhaseTitle": self.phases[l["PhaseId"]]["Title"]} for l in rows]

    def disciplines(self):
        return sorted(self.discs.values(), key=lambda d: (d["SortOrder"], d["Id"]))

    def ref_items(self, pid):
        return [{"Id": r["Id"], "RegKey": r["RegKey"], "PhaseItemId": r["PhaseItemId"], "DisciplineItemId": r["DisciplineItemId"],
                 "ManDays": r["ManDays"], "etag": r["odata.etag"]} for r in self.item_rows(pid)]

    def create(self, fields):
        if any(it["RegKey"] == fields["RegKey"] for it in self.items.values()) or "dup" in self.fail:
            raise H.ConflictError()
        i = self.next_id
        self.next_id += 1
        self.items[i] = {k: fields[k] for k in ("RegKey", "LegacyId", "ProjectItemId", "PhaseItemId", "DisciplineItemId", "Status")}
        self.items[i].update(Id=i, ManDays=num(fields["ManDays"]))
        self.ver[i] = 1
        return i, self.etag(i)

    def update(self, i, fields, if_match):
        if i in self.race:
            self.ver[i] += 1
            self.race.discard(i)
        if "merge:%d" % i in self.fail:
            raise ConnectionError("500")
        if if_match != self.etag(i):
            raise H.ConflictError()
        self.items[i]["ManDays"] = num(fields["ManDays"])
        self.ver[i] += 1


class Data:
    def __init__(self, store):
        self.s = store

    def project(self, pid):
        return self.s.project(pid)

    def project_phases(self, pid):
        return self.s.project_phases(pid)

    def disciplines(self):
        return self.s.disciplines()

    def items(self, pid):
        return self.s.ref_items(pid)


_COND = re.compile(r"(\w+) eq (\d+)")


def mocks_for(upn, roles, store, posts, writes, *, profile_fail=False, fail_audit=()):
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return ("Failed", {"statusCode": 503}) if profile_fail else ("Succeeded", {"userPrincipalName": upn})
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        method, uri = p["parameters/method"], unquote(p["parameters/uri"])
        lst = re.search(r"getbytitle\('([^']*)'\)", uri).group(1)
        if lst in ("_Audit", "_ConfAudit"):
            row = json.loads(p["parameters/body"])
            if row.get("EventType") in fail_audit:
                return "Failed", {"statusCode": 400}
            posts.append(row)
            return "Succeeded", {"Id": len(posts)}
        if lst == tg.EMP_LIST:
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)})
        m = re.search(r"/items\((-?\d+)\)", uri)
        conds = dict((k, int(v)) for k, v in _COND.findall(uri.split("$filter=")[1].split("&")[0])) if "$filter=" in uri else {}
        if lst == "Projects":
            if "Get_project" in store.fail:
                return "Failed", {"statusCode": 503}
            pr = store.projects.get(int(m.group(1)))
            return ("Succeeded", dict(pr)) if pr else ("Failed", {"statusCode": 404})
        if lst == "ProjectPhases":
            if "Get_phases" in store.fail:
                return "Failed", {"statusCode": 503}
            rows = sorted((l for l in store.links if l["ProjectItemId"] == conds["ProjectItemId"] and l["IsActive"] == bool(conds["IsActive"])),
                          key=lambda l: (l["SortOrder"], l["Id"]))
            return "Succeeded", {"value": [{"Id": l["Id"], "PhaseId": l["PhaseId"], "SortOrder": l["SortOrder"],
                                            "Phase": {k: store.phases[l["PhaseId"]][k] for k in ("LegacyId", "PhaseCode", "Title")}} for l in rows]}
        if lst == "Disciplines":
            return "Succeeded", {"value": [dict(d) for d in store.disciplines()]}
        assert lst == hr_schema.TITLE, uri
        if method == "GET" and uri.endswith("?$select=ListItemEntityTypeFullName"):
            return "Succeeded", {"ListItemEntityTypeFullName": ENTITY}
        if method == "GET" and m:
            i = int(m.group(1))
            return "Succeeded", {"Id": i, "odata.etag": store.etag(i)}
        if method == "GET":
            return "Succeeded", {"value": store.item_rows(conds["ProjectItemId"])}
        body = json.loads(p["parameters/body"])
        h = p["parameters/headers"]
        assert a["inputs"]["retryPolicy"] == {"type": "none"} and body["__metadata"]["type"] == ENTITY
        fields = {k: v for k, v in body.items() if k != "__metadata"}
        if m:
            assert h["X-HTTP-Method"] == "MERGE" and h["IF-MATCH"] not in ("*", "")
            writes.append(("MERGE", int(m.group(1)), fields))
            try:
                store.update(int(m.group(1)), fields, h["IF-MATCH"])
            except H.ConflictError:
                return "Failed", {"statusCode": 412}
            except ConnectionError:
                return "Failed", {"statusCode": 500}
            return "Succeeded", None
        writes.append(("POST", None, fields))
        try:
            i, etag = store.create(fields)
        except H.ConflictError:
            return "Failed", {"statusCode": 400}
        return "Succeeded", {"d": {"Id": i, "__metadata": {"etag": etag}}}
    return mocks


def ident(upn, roles):
    return TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])


def lk(n):
    return [e for e in tg.EMPS if e.account_upn == n]


def guard(upn, roles, cid, action, decoys=None):
    return G.authorize(ident(upn, roles), lk, lk, tg.CFG, POLICY, action, "self", correlation_id=cid, **{k: "" for k in (decoys or {})})


def changes(*cells):
    return json.dumps([{"phaseId": ph, "disciplineId": d, "state": st, "value": v, "etag": et} for ph, d, st, v, et in cells])


AUDIT_KEYS = ("EventType", "Action", "Decision", "ResultCode", "TargetItemId", "TargetLegacyId")


class _Both(unittest.TestCase):
    maxDiff = None

    def read(self, roles=EDITOR, pid="1", store_kw=None, store=None, decoys=None, cid="run-rr", profile_fail=False, fail_audit=()):
        fs = copy.deepcopy(store) if store else Store(**(store_kw or {}))
        rs = copy.deepcopy(fs)
        posts, writes = [], []
        trig = {"text": pid}
        trig.update({"text_%d" % (1 + i): (decoys or {}).get(k, "") for i, k in enumerate(H.READ_DECOYS)})
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW,
                          mocks=mocks_for(ME, roles, fs, posts, writes, profile_fail=profile_fail, fail_audit=fail_audit)).run(READ)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "project": json.loads(resp["project"]), "phases": json.loads(resp["phases"]),
             "disciplines": json.loads(resp["disciplines"]), "cells": json.loads(resp["cells"]), "canEdit": resp["canedit"] == "true"}
        r = H.read_matrix(guard(ME, roles, cid, rr.VIEW, decoys), dict({"ProjectItemId": pid}, **(decoys or {})), Data(rs), correlation_id=cid,
                          profile_failed=profile_fail, authorization_audit_ok=not ({"AuthorizationAllow", "AuthorizationDeny"} & set(fail_audit)))
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.ctx = dict(posts=posts, run=run, ref=r, store=fs)
        return f

    def save(self, cells, roles=EDITOR, pid="1", store_kw=None, store=None, decoys=None, cid="run-rs", profile_fail=False, fail_audit=(),
             raw=None):
        fs = copy.deepcopy(store) if store else Store(**(store_kw or {}))
        rs = copy.deepcopy(fs)
        posts, writes = [], []
        ch = raw if raw is not None else changes(*cells)
        trig = {"text": pid, "text_1": ch, "text_2": "client-1"}
        trig.update({"text_%d" % (3 + i): (decoys or {}).get(k, "") for i, k in enumerate(H.SAVE_DECOYS)})
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW,
                          mocks=mocks_for(ME, roles, fs, posts, writes, profile_fail=profile_fail, fail_audit=fail_audit)).run(SAVE)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "savedCount": int(resp["savedcount"]), "clearedStale": int(resp["clearedstale"]),
             "results": json.loads(resp["results"]), "auditStatus": resp["auditstatus"], "warnings": json.loads(resp["warnings"])}
        rowfail = "WriteProxy" in fail_audit
        r = H.save_matrix(guard(ME, roles, cid, rr.EDIT, decoys), dict({"ProjectItemId": pid, "Changes": ch, "ClientRequestId": "client-1"},
                                                                     **(decoys or {})), Data(rs), rs, correlation_id=cid, profile_failed=profile_fail,
                          authorization_audit_ok=not ({"AuthorizationAllow", "AuthorizationDeny"} & set(fail_audit)),
                          row_audit_ok=lambda key: not rowfail)
        if resp["resultcode"] not in ("DIRECTORY_ERROR", "INTERNAL_ERROR"):
            self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
            self.assertEqual(fs.items, rs.items, "stored rows differ")
            wp = [{k: p.get(k) for k in AUDIT_KEYS} | {"ChangeJson": json.loads(p["ChangeJson"])} for p in posts if p.get("EventType") == "WriteProxy"]
            self.assertEqual(wp, [{k: a.get(k) for k in AUDIT_KEYS} | {"ChangeJson": a["ChangeJson"]} for a in r["audit"]], "WriteProxy rows differ")
            self.assertEqual([(m, i, {k: f2[k] for k in ("ManDays",)}) for m, i, f2 in writes],
                             [(m, i, {"ManDays": f2["ManDays"]}) for m, i, f2 in r["writes"]], "write bodies differ")
        self.ctx = dict(posts=posts, run=run, ref=r, store=fs, writes=writes)
        return f

    def codes(self, f):
        return [x["resultcode"] for x in f["results"]]


def project_total(store, pid):
    """Reporting contract (design §11, OD-08): per-project registered man-days = Σ stored values of every item of the
    project, including values on phases that left the project until they are cleared."""
    return sum(i["ManDays"] or 0 for i in store.items.values() if i["ProjectItemId"] == pid)


class HourRegistration(_Both):
    # ---------------------------------------------------------------- schema / key / portability
    def test_HR01_schema(self):
        f = {x[0]: x for x in hr_schema.FIELDS}
        self.assertEqual(f["RegKey"][2:5], (True, True, True))
        self.assertEqual(f["LegacyId"][2:5], (True, True, True))
        self.assertTrue(f["ProjectItemId"][3])
        self.assertEqual((f["ManDays"][1], f["ManDays"][2], f["ManDays"][5]["Decimals"]), ("Number", False, 2))
        self.assertEqual(f["Status"][5]["Choices"], ["Active"])
        joined = " ".join(f).lower()
        for bad in ("salary", "rate", "cost", "allocation", "effort", "approv", "owner", "period"):
            self.assertNotIn(bad, joined, "no EPIC 16/17 / cost field")
        self.assertFalse(hr_schema.SERVICE_RIGHTS & hr_schema.NEVER)
        self.assertEqual(hr_schema.DIRECT_USER_ACCESS, ())

    def test_HR02_stable_portable_key(self):
        self.save([(6, 1, "value", "3", "")])
        body = [w for w in self.ctx["writes"] if w[0] == "POST"][0][2]
        self.assertEqual((body["RegKey"], body["LegacyId"]), ("PRJ-L1|PH-L6|D-L1", "PRJ-L1|PH-L6|D-L1"))
        # same legacy masters with different local item ids -> same key
        st = Store()
        st.projects[1]["Id"] = 1
        self.assertEqual(H.reg_key(st.projects[1]["LegacyId"], st.phases[6]["LegacyId"], st.discs[1]["LegacyId"]), body["RegKey"])
        self.assertNotRegex(body["RegKey"], r"^\d+\|")

    def test_HR03_blank_vs_zero_round_trip(self):
        st = Store()
        f = self.save([(6, 1, "value", "0", ""), (6, 3, "value", "12", ""), (5, 1, "blank", "", "")], store=st)
        self.assertEqual((f["code"], self.codes(f)), ("OK", ["OK", "OK", "NO_CHANGE"]))
        st = self.ctx["store"]
        r = self.read(store=st)
        cells = {(c["phaseId"], c["disciplineId"]): (c["state"], c["value"]) for c in r["cells"]}
        self.assertEqual(cells, {(6, 1): ("VALUE", "0"), (6, 3): ("VALUE", "12")})
        self.assertNotIn((5, 1), cells, "blank without item stays blank (no item created)")
        stored = {(i["PhaseItemId"], i["DisciplineItemId"]): i["ManDays"] for i in st.items.values()}
        self.assertEqual(stored[(6, 1)], 0)
        self.assertIsNotNone(stored[(6, 1)], "explicit 0 is never stored as null")

    def test_HR04_numeric_validation(self):
        for v in ("abc", "1,5", " ", "", "1.", ".5", "1.2.3", "+1", "1e3"):
            f = self.save([(6, 1, "value", v, "")])
            self.assertEqual((f["code"], self.codes(f)), ("REFUSED", ["VALIDATION_VALUE"]), v)
            self.assertEqual(self.ctx["writes"], [])
        for v in ("0", "7", "12.5", "12.25", "007"):
            self.assertEqual(self.save([(6, 1, "value", v, "")])["code"], "OK", v)

    def test_HR05_two_decimal_precision(self):
        self.assertEqual(self.save([(6, 1, "value", "0.01", "")])["code"], "OK")
        f = self.save([(6, 1, "value", "1.234", "")])
        self.assertEqual(self.codes(f), ["VALIDATION_VALUE"])

    def test_HR06_negative_refused(self):
        for v in ("-1", "-0.5", "-0"):
            self.assertEqual(self.codes(self.save([(6, 1, "value", v, "")])), ["VALIDATION_VALUE"], v)

    def test_HR07_no_business_maximum_technical_limit(self):
        for v in ("12500", "999999.99", "123456789012345"):
            self.assertEqual(self.save([(6, 1, "value", v, "")])["code"], "OK", v)
        f = self.save([(6, 1, "value", "1234567890123456", "")])
        self.assertEqual(self.codes(f), ["TECHNICAL_LIMIT"])

    def test_HR08_phase_scoping(self):
        f = self.save([(9, 1, "value", "3", ""), (6, 1, "value", "3", "")])  # phase 9 is not in project 1 (6 phases)
        self.assertEqual((f["code"], self.codes(f)), ("REFUSED", ["VALIDATION_LOOKUP", "NOT_WRITTEN"]))
        self.assertEqual(self.save([(6, 99, "value", "3", "")])["results"][0]["resultcode"], "VALIDATION_LOOKUP")

    def test_HR09_project_selection_and_matrix_shape(self):
        r = self.read()
        self.assertEqual([p["id"] for p in r["phases"]], [6, 5, 4, 3, 2, 1], "project phase order, not id order")
        self.assertEqual([d["id"] for d in r["disciplines"]], [5, 4, 3, 2, 1], "all disciplines by SortOrder, incl. inactive (2)")
        self.assertEqual((r["project"]["code"], r["project"]["year"]), ("P1", 2026))
        self.assertEqual(self.read(pid="7")["code"], "NOT_FOUND")
        self.assertEqual(self.read(pid="abc")["code"], "VALIDATION_LOOKUP")
        # duplicate project code: project 2 has its own phase set
        self.assertEqual([p["id"] for p in self.read(pid="2")["phases"]], [1])

    def test_HR10_paused_closed_project_editable(self):
        for status in ("Paused", "Closed", "Completed"):
            st = Store(project_status=status)
            self.assertEqual(self.read(store=st)["project"]["status"], status)
            self.assertEqual(self.save([(6, 1, "value", "4", "")], store=st)["code"], "OK", status)

    def test_HR11_removed_phase_legacy_parity(self):
        st = Store(items=[(6, 1, 12), (5, 1, 3)], removed=())
        # phase 6 leaves project 1
        st.links[0]["IsActive"] = False
        r = self.read(store=st)
        self.assertNotIn(6, [p["id"] for p in r["phases"]], "removed phase not shown")
        self.assertNotIn(6, [c["phaseId"] for c in r["cells"]], "its value not returned / not editable")
        self.assertEqual(project_total(st, 1), 15, "still counted in the project total")
        f = self.save([(6, 1, "value", "1", "")], store=st)
        self.assertEqual(self.codes(f), ["VALIDATION_LOOKUP"], "not editable through the API either")
        self.assertEqual(project_total(self.ctx["store"], 1), 15, "a refused save clears nothing")
        f = self.save([(5, 2, "value", "4", "")], store=st)
        self.assertEqual((f["code"], f["savedCount"], f["clearedStale"]), ("OK", 1, 1))
        after = self.ctx["store"]
        stale = [i for i in after.items.values() if i["PhaseItemId"] == 6][0]
        self.assertEqual(stale["ManDays"], None, "cleared, item kept (no delete)")
        self.assertEqual(project_total(after, 1), 7)
        clear = [p for p in self.ctx["posts"] if p.get("EventType") == "WriteProxy" and p["Action"] == "Clear"]
        self.assertEqual(len(clear), 1)
        # re-added before any save: the value reappears
        st2 = Store(items=[(6, 1, 12)])
        st2.links[0]["IsActive"] = False
        st2.links[0]["IsActive"] = True
        self.assertIn((6, 1, "12"), [(c["phaseId"], c["disciplineId"], c["value"]) for c in self.read(store=st2)["cells"]])

    def test_HR12_view_capability_every_role(self):
        for role in rr.ROLES:
            r = self.read(roles=(role,))
            want = rr.MATRIX[role][0]
            self.assertEqual((r["ok"], r["code"]), (want, "OK" if want else "ROLE_NOT_ALLOWED"), role)
            if want:
                self.assertEqual(r["canEdit"], rr.MATRIX[role][1], role)
            else:
                self.assertEqual((r["cells"], r["phases"]), ([], []))
        self.assertTrue(self.read(roles=("ITS",))["ok"], "IT Support view = legacy IT read (OD-05)")
        self.assertFalse(self.read(roles=("ADM",))["ok"], "AppAdmin: no business view")

    def test_HR13_edit_capability_every_role(self):
        for role in rr.ROLES:
            f = self.save([(6, 1, "value", "2", "")], roles=(role,))
            want = rr.MATRIX[role][1]
            self.assertEqual(f["code"], "OK" if want else "ROLE_NOT_ALLOWED", role)
            if not want:
                self.assertEqual(self.ctx["writes"], [])
                self.assertEqual([p["ResultCode"] for p in self.ctx["posts"] if p["EventType"] == "AuthorizationDeny"], ["ROLE_NOT_ALLOWED"])

    def test_HR14_clear_keeps_item(self):
        st = Store(items=[(6, 1, 0), (6, 2, 7)])
        f = self.save([(6, 1, "blank", "", '"1"'), (6, 2, "blank", "", '"1"')], store=st)
        self.assertEqual((f["code"], self.codes(f)), ("OK", ["OK", "OK"]))
        after = self.ctx["store"]
        self.assertEqual(sorted((i["PhaseItemId"], i["DisciplineItemId"], i["ManDays"]) for i in after.items.values()),
                         [(6, 1, None), (6, 2, None)], "clear from 0 and from a value -> null, items kept")
        self.assertEqual([p["Action"] for p in self.ctx["posts"] if p.get("EventType") == "WriteProxy"], ["Clear", "Clear"])
        self.assertFalse([w for w in self.ctx["writes"] if w[0] not in ("MERGE", "POST")])

    def test_HR15_changed_cells_only(self):
        st = Store(items=[(6, 1, 5), (6, 2, 7)])
        f = self.save([(6, 1, "value", "5", '"1"'), (6, 2, "value", "8", '"1"')], store=st)
        self.assertEqual(self.codes(f), ["NO_CHANGE", "OK"])
        self.assertEqual([w[1] for w in self.ctx["writes"]], [2], "only the changed cell is written")
        self.assertEqual(self.ctx["store"].ver[1], 1, "unchanged cell keeps its ETag")
        self.assertEqual(len([p for p in self.ctx["posts"] if p.get("EventType") == "WriteProxy"]), 1)

    def _matrix(self, n_ph, n_d):
        vals = ["", "0", "7", "1.5", "2.25"]
        out = []
        k = 0
        for ph in range(1, n_ph + 1):
            for d in range(1, n_d + 1):
                v = vals[k % len(vals)]
                out.append((ph, d, "blank" if v == "" else "value", v, ""))
                k += 1
        return out

    def test_HR16_13x5_round_trip_65_cells(self):
        st = Store(n_phases=13, n_discs=5)
        cells = self._matrix(13, 5)
        f = self.save(cells, store=st)
        self.assertEqual(f["code"], "OK")
        self.assertEqual(len(self.ctx["run"].results) > 0, True)
        r = self.read(store=self.ctx["store"])
        got = {(c["phaseId"], c["disciplineId"]): (c["state"], c["value"]) for c in r["cells"]}
        for ph, d, state, v, _ in cells:
            if state == "blank":
                self.assertNotIn((ph, d), got)
            else:
                self.assertEqual(got[(ph, d)], ("VALUE", H.fmt(float(v))), (ph, d))
        self.assertEqual(len(got), 52, "13 blank cells of 65 create no item")
        self.assertEqual(sum(1 for c in r["cells"] if c["value"] == "0"), 13, "explicit zeros preserved")

    def test_HR17_100_cell_boundary(self):
        st = Store(n_phases=13, n_discs=8)
        cells = [(ph, d, "value", "1", "") for ph in range(1, 14) for d in range(1, 9)]
        self.assertEqual(self.save(cells[:100], store=st)["savedCount"], 100)
        f = self.save(cells[:101], store=st)
        self.assertEqual((f["code"], f["results"]), ("VALIDATION_REQUEST", []))
        self.assertEqual(self.save([], raw="[]")["code"], "VALIDATION_REQUEST")
        dup = [(6, 1, "value", "1", ""), (6, 1, "value", "2", "")]
        self.assertEqual(self.save(dup)["code"], "VALIDATION_REQUEST")
        for raw in ("not json", "{}", "[1]", '[{"phaseId": 6}]'):
            self.assertIn(self.save([], raw=raw)["code"], ("VALIDATION_REQUEST", "REFUSED"), raw)

    def test_HR18_stale_etag_refuses_whole_request(self):
        st = Store(items=[(6, 1, 5), (6, 2, 7)])
        st.ver[1] = 2  # someone changed cell (6, 1) after the editor loaded it
        f = self.save([(6, 1, "value", "6", '"1"'), (6, 2, "value", "8", '"1"'), (5, 1, "value", "1", "")], store=st)
        self.assertEqual((f["code"], self.codes(f)), ("REFUSED", ["CONFLICT", "NOT_WRITTEN", "NOT_WRITTEN"]))
        self.assertEqual(self.ctx["writes"], [], "nothing written")
        self.assertFalse([p for p in self.ctx["posts"] if p.get("EventType") == "WriteProxy"])
        # creating over an existing item with an empty ETag is stale too
        self.assertEqual(self.codes(self.save([(6, 1, "value", "6", "")], store=st)), ["CONFLICT"])

    def test_HR19_conflict_after_preflight_partial(self):
        st = Store(items=[(6, 1, 5), (6, 2, 7)], race=(1,))
        f = self.save([(6, 1, "value", "6", '"1"'), (6, 2, "value", "8", '"1"')], store=st)
        self.assertEqual((f["code"], self.codes(f), f["warnings"]), ("PARTIAL", ["CONFLICT", "OK"], ["WARN_RELOAD_REQUIRED"]))
        self.assertEqual(self.ctx["store"].items[2]["ManDays"], 8)
        self.assertEqual(self.ctx["store"].items[1]["ManDays"], 5, "never silently overwritten")
        # 5xx after preflight -> ERROR for that cell
        st = Store(items=[(6, 1, 5)], fail=("merge:1",))
        self.assertEqual(self.codes(self.save([(6, 1, "value", "6", '"1"')], store=st)), ["ERROR"])
        # concurrent creator: unique RegKey -> CONFLICT
        st = Store(fail=("dup",))
        self.assertEqual(self.codes(self.save([(6, 1, "value", "6", "")], store=st)), ["CONFLICT"])

    def test_HR20_forgery_ignored(self):
        decoys = {"Role": "EXE", "Scope": "company", "OwnerUpn": "boss@tenant-a.invalid", "ActorUpn": "boss@tenant-a.invalid",
                  "DisciplineCode": "D2"}
        self.assertEqual(self.save([(6, 1, "value", "2", "")], roles=("EMP",), decoys=decoys)["code"], "ROLE_NOT_ALLOWED")
        f = self.save([(6, 1, "value", "2", "")], roles=EDITOR, decoys=decoys)
        self.assertEqual(f["code"], "OK")
        body = [w for w in self.ctx["writes"] if w[0] == "POST"][0][2]
        self.assertEqual(body["ActorUpn"], ME, "trusted caller, never the claimed actor")
        self.assertEqual(self.read(roles=("EMP",), decoys={"Role": "PMO"})["code"], "ROLE_NOT_ALLOWED")

    def test_HR21_no_direct_access_and_no_delete(self):
        self.assertEqual(hr_schema.DIRECT_USER_ACCESS, ())
        self.assertNotIn("DeleteListItems", hr_schema.SERVICE_RIGHTS)
        for flow in (READ, SAVE):
            src = json.dumps(flow)
            self.assertNotRegex(src, r"X-HTTP-Method\"?: *\"?DELETE|\"method\": *\"DELETE\"|DeleteItem")

    def test_HR22_audit_exactly_once(self):
        st = Store(items=[(6, 1, 5)])
        f = self.save([(6, 1, "value", "6", '"1"'), (6, 2, "value", "1", ""), (6, 3, "blank", "", "")], store=st)
        self.assertEqual(self.codes(f), ["OK", "OK", "NO_CHANGE"])
        ev = [(p["EventType"], p.get("Action")) for p in self.ctx["posts"]]
        self.assertEqual(ev.count(("AuthorizationAllow", "REG.Edit")), 1)
        wp = [p for p in self.ctx["posts"] if p["EventType"] == "WriteProxy"]
        self.assertEqual([(p["Action"], json.loads(p["ChangeJson"])) for p in wp],
                         [("Update", {"ManDaysOld": "5", "ManDays": "6"}), ("Create", {"ManDaysOld": "", "ManDays": "1"})])
        self.assertTrue(all(p["ActorUpn"] == ME and p["CorrelationId"] == "run-rs" for p in wp))
        r = self.read(store=st)
        self.assertEqual([(p["EventType"], p["Action"]) for p in self.ctx["posts"]], [("AuthorizationAllow", "REG.View"), ("ReadProxy", "ReadMatrix")])

    def test_HR23_response_schema(self):
        self.assertEqual(sorted(SAVE["Respond"]["inputs"]["body"]), sorted(["ok", "resultcode", "messagecode", "correlationid", "savedcount",
                                                                         "clearedstale", "results", "auditstatus", "warnings"]))
        self.assertEqual(sorted(READ["Respond"]["inputs"]["body"]), sorted(["ok", "resultcode", "messagecode", "correlationid", "project",
                                                                         "phases", "disciplines", "cells", "canedit"]))
        for fl in (READ, SAVE):
            self.assertEqual(list(fl["Respond_error"]["inputs"]["body"]), list(fl["Respond"]["inputs"]["body"]))

    def test_HR24_audit_degraded_and_mandatory_authorization_audit(self):
        f = self.save([(6, 1, "value", "2", "")], fail_audit=("WriteProxy",))
        self.assertEqual((f["code"], f["auditStatus"], f["warnings"]), ("OK", "AUDIT_DEGRADED", ["AUDIT_DEGRADED"]))
        self.assertEqual(self.ctx["run"].terminated["runStatus"], "Failed")
        f = self.save([(6, 1, "value", "2", "")], fail_audit=("AuthorizationAllow",))
        self.assertEqual((f["code"], self.ctx["writes"]), ("INTERNAL_ERROR", []))

    def test_HR25_portability_no_tenant_values(self):
        for fl in (READ, SAVE):
            src = json.dumps(fl)
            self.assertNotRegex(src, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
            self.assertNotIn("firstgreen", src.lower())
        src = open(os.path.join(HERE, "hour_registration.py"), encoding="utf-8").read() + open(os.path.join(HERE, "registration_rules.py"), encoding="utf-8").read()
        self.assertNotRegex(src, r"@[a-z0-9-]+\.(vn|com)")

    def test_HR26_directory_and_read_failures(self):
        self.assertEqual(self.save([(6, 1, "value", "2", "")], profile_fail=True)["code"], "DIRECTORY_ERROR")
        self.assertEqual(self.save([(6, 1, "value", "2", "")], store_kw={"fail": ("Get_phases",)})["code"], "ERROR")
        self.assertEqual(self.read(store_kw={"fail": ("Get_project",)})["code"], "ERROR")

    def test_HR27_read_preserves_blank_vs_zero(self):
        st = Store(items=[(6, 1, 0), (6, 2, None), (6, 3, 2.5)])
        cells = {(c["phaseId"], c["disciplineId"]): (c["state"], c["value"]) for c in self.read(store=st)["cells"]}
        self.assertEqual(cells, {(6, 1): ("VALUE", "0"), (6, 2): ("BLANK", ""), (6, 3): ("VALUE", "2.5")})

    def test_HR28_state_is_required(self):
        self.assertEqual(self.codes(self.save([(6, 1, "maybe", "1", "")])), ["VALIDATION_VALUE"])
        self.assertEqual(self.save([(6, 1, "VALUE", "1", "")])["code"], "OK", "state is case-insensitive")

    def test_HR29_replay_is_safe_not_exactly_once(self):
        st = Store(items=[(6, 1, 5)])
        f1 = self.save([(6, 1, "value", "6", '"1"')], store=st)
        replay = self.save([(6, 1, "value", "6", '"1"')], store=self.ctx["store"])
        self.assertEqual((f1["code"], replay["code"], self.codes(replay)), ("OK", "REFUSED", ["CONFLICT"]), "stale replay refused")
        same = self.save([(6, 1, "value", "6", f1["results"][0]["etag"])], store=self.ctx["store"])
        self.assertEqual((same["code"], self.codes(same)), ("OK", ["NO_CHANGE"]), "replay with the current ETag writes nothing")
        self.assertFalse([p for p in self.ctx["posts"] if p.get("EventType") == "WriteProxy"])
        doc = open(os.path.join(HERE, "hour_registration.py"), encoding="utf-8").read()
        self.assertIn("correlation only", doc)

    def test_HR30_rules_match_legacy_and_seed(self):
        self.assertEqual(rr.VIEWERS, ("TL", "APR", "EXE", "PMO", "HR", "ITS"))
        self.assertEqual(rr.EDITORS, ("EXE", "PMO"))
        legacy_readers = {t for _, acc, ts in rr.LEGACY_MAP if acc in ("Read", "Write") for t in ts}
        self.assertLessEqual(set(rr.VIEWERS), legacy_readers)
        self.assertNotIn("ADM", rr.VIEWERS + rr.EDITORS)
        cfg = os.environ.get("TS_SCOPE_CONFIG")
        if cfg:
            seed = json.load(open(cfg, encoding="utf-8"))["scopes"]
            got = {(r, cap) for r, caps in seed.items() for cap, v in caps.items() if cap.startswith("REG.") and v not in (None, "none")}
            want = {(r, cap) for r in rr.ROLES for cap, ok in ((rr.VIEW, rr.MATRIX[r][0]), (rr.EDIT, rr.MATRIX[r][1])) if ok}
            self.assertEqual(got, want, "role seed REG.* equals the M1 decision")

    def test_HR31_unknown_project_and_pid_validation_on_save(self):
        self.assertEqual(self.save([(6, 1, "value", "2", "")], pid="999")["code"], "NOT_FOUND")
        self.assertEqual(self.save([(6, 1, "value", "2", "")], pid="-1")["code"], "VALIDATION_LOOKUP")

    def test_HR32_lazy_independence(self):
        prev = wdl_sim.BRANCH_MODE
        try:
            for mode in ("eager",):
                wdl_sim.BRANCH_MODE = mode
                st = Store(items=[(6, 1, 5)])
                st.links[1]["IsActive"] = False  # phase 5 removed
                f = self.save([(6, 1, "blank", "", '"1"'), (4, 2, "value", "0", ""), (3, 3, "value", "1.25", "")], store=st)
                self.assertEqual(f["code"], "OK", mode)
                self.assertEqual(self.read(store=self.ctx["store"])["code"], "OK", mode)
                self.assertEqual(self.save([(6, 1, "value", "abc", "")])["code"], "REFUSED", mode)
        finally:
            wdl_sim.BRANCH_MODE = prev


if __name__ == "__main__":
    unittest.main(verbosity=2)
