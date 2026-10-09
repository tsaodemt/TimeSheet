"""S07.2 TS-Approve / TS-ReadTeam: reference (approve_entries) vs generated flows (build_approval_flows) in the WDL
simulator, against one SharePoint-like store per side. Tests AQ01-AQ26, AQ-EQ, AQ-T1..T3 (flow technical paths),
RT01-RT12, ST01-ST03 (schema). Offline; synthetic data only."""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "timesheet"),
          os.path.join(HERE, "..", "provisioning")):
    sys.path.insert(0, p)
import approval_rules as ar  # noqa: E402
import approve_entries as AE  # noqa: E402
import build_approval_flows as bf  # noqa: E402
import business_dates as bd  # noqa: E402
import guard as G  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402
from test_r1_save_flow import sp_query  # noqa: E402

TZ = "Asia/Ho_Chi_Minh"
REG = {"settings": [{"key": "BusinessTimezone", "type": "iana_tz", "value": TZ, "resolution": "RESOLVED"}]}
OVL = {"environment": "STAGING", "values": {}, "external": {}}
SETTINGS = [{"Title": "BusinessTimezone", "Value": TZ}]
POLICY = G.Policy.from_scope_config(ar.scope_config())
EMPS = tg.EMPS
BY_ID = {e.item_id: e for e in EMPS}
u = tg.u
NOW = "2026-10-09T03:04:05Z"
ENTITY = "SP.Data.TimesheetEntriesListItem"
KW = dict(role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit",
          conf_audit_list="_ConfAudit", environment="STAGING", registry=REG, overlay=OVL)
APPROVE = bf.approve_actions(**KW)
TEAM = bf.read_team_actions(**KW)


def entry(i, emp, date="2026-10-07", status="Draft", period="2026-10", disc=None, owner_upn=None):
    e = BY_ID[emp]
    return {"Id": i, "OwnerUpn": owner_upn or e.account_upn, "ActorUpn": e.account_upn, "EmployeeId": emp, "EmployeeItemId": emp,
            "DisciplineCode": disc if disc is not None else e.discipline_id, "LegacyId": "L-%d" % i, "WorkDate": bd.local_midnight_utc(date, TZ),
            "PeriodKey": period, "EntryStatus": status, "ProjectId": 101, "PhaseId": 201, "WorkTypeId": 301, "ShiftId": 401, "HourTypeId": 501,
            "Hours": 2.0, "Remark": "r%d" % i, "Created": "2026-10-01T00:00:00Z", "AuthorId": 7, "CorrelationId": "c-%d" % i,
            "ApprovedBy": None, "ApprovedOn": None}


# 11 emp (D1), 12 peer (D1), 13 far (D2), 18 nodisc (None), 15 gone (inactive, D1); 99 = no Employees row
ITEMS = [entry(1, 11), entry(2, 11, "2026-10-08"), entry(3, 13), entry(4, 12), entry(5, 11, status="Approved"),
         entry(6, 11, status="Deleted"), entry(7, 18, disc="D1"), entry(8, 15), entry(9, 11, period="2026-11"),
         entry(10, 13, disc="D1"), entry(11, 12, owner_upn=u("emp").upper())]
ITEMS[8]["EmployeeItemId"] = ITEMS[8]["EmployeeId"] = 11
ORPHAN = dict(entry(12, 11), EmployeeItemId=99, EmployeeId=99)
ITEMS.append(ORPHAN)


class Store:
    def __init__(self, items, race=(), readback="ok", fail_get=(), fail_write=()):
        self.items = {x["Id"]: copy.deepcopy(x) for x in items}
        self.ver = {i: 1 for i in self.items}
        self.race, self.readback, self.fail_get, self.fail_write = set(race), readback, set(fail_get), set(fail_write)
        self.read_back = {}

    def etag(self, i):
        return '"%d,%d"' % (i, self.ver[i])

    def get(self, i):
        if i in self.fail_get:
            raise ConnectionError("503")
        if i not in self.items:
            return None
        f = copy.deepcopy(self.items[i])
        f["WorkDateText"] = bd.business_date(f["WorkDate"], TZ)
        return f, self.etag(i)

    def update(self, i, body, if_match):
        if i in self.race:
            self.ver[i] += 1  # someone saved between the read and the MERGE
        if i in self.fail_write:
            raise ConnectionError("500")
        if if_match != self.etag(i):
            raise AE.ConflictError()
        self.items[i].update({k: v for k, v in body.items() if k != "__metadata"})
        self.ver[i] += 1
        self.read_back[i] = {"ok": self.etag(i), "fail": None}[self.readback]
        return self.read_back[i]

    def rows(self):
        out = []
        for i, f in sorted(self.items.items()):
            e = BY_ID.get(f["EmployeeItemId"])
            out.append(dict(f, **{"odata.etag": self.etag(i), "Employee": {"Title": "Name %s" % e.legacy_id, "LegacyId": e.legacy_id} if e else None}))
        return out


def ident(upn, roles):
    return TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])


def lk(n):
    return [e for e in EMPS if e.account_upn == n]


def guard(upn, roles, cid, decoys=None):
    return G.authorize(ident(upn, roles), lk, lk, tg.CFG, POLICY, "TS.Approve", "self", correlation_id=cid,
                       **{k: "" for k in (decoys or {})})


def caller_disc(upn):
    rows = lk(upn)
    return rows[0].discipline_id if len(rows) == 1 and rows[0].discipline_id else ""


def owner_lookup(fail=False):
    def f(i):
        if fail:
            raise ConnectionError("503")
        e = BY_ID.get(i)
        return AE.Owner(e.item_id, e.legacy_id, e.discipline_id) if e else None
    return f


def mocks_for(upn, roles, store, posts, writes, *, profile_fail=False, fail_audit=(), fail_owner=False, fail_type=False, fail_settings=False):
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return ("Failed", {"statusCode": 503}) if profile_fail else ("Succeeded", {"userPrincipalName": upn})
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        method, uri = p["parameters/method"], p["parameters/uri"]
        lst = re.search(r"getbytitle\('([^']*)'\)", uri).group(1)
        if lst == "AppSettings":
            return ("Failed", {"statusCode": 503}) if fail_settings else ("Succeeded", {"value": SETTINGS})
        if lst in ("_Audit", "_ConfAudit"):
            row = json.loads(p["parameters/body"])
            key = row.get("EventType") if row.get("EventType") != "Approval" else "Approval:%s" % row.get("TargetItemId")
            if row.get("EventType") in fail_audit or key in fail_audit:
                return "Failed", {"statusCode": 400}
            posts.append(row)
            return "Succeeded", {"Id": len(posts)}
        m = re.search(r"/items\((-?\d+)\)", uri)
        if lst == tg.EMP_LIST:
            if m:
                if fail_owner:
                    return "Failed", {"statusCode": 503}
                e = BY_ID.get(int(m.group(1)))
                return ("Failed", {"statusCode": 404}) if e is None else ("Succeeded", tg.lookup_rows([e])[0])
            return "Succeeded", wdl_sim.sharepoint_get(uri, {tg.EMP_LIST: tg.lookup_rows(EMPS)})
        assert lst == "TimesheetEntries", uri
        if method == "GET" and uri.endswith("?$select=ListItemEntityTypeFullName"):
            return ("Failed", {"statusCode": 503}) if fail_type else ("Succeeded", {"ListItemEntityTypeFullName": ENTITY})
        if method == "GET" and m and uri.endswith(")?$select=Id"):
            v = store.read_back.get(int(m.group(1)))
            return ("Failed", {"statusCode": 503}) if v is None else ("Succeeded", {"Id": int(m.group(1)), "odata.etag": v})
        if method == "GET" and m:
            i = int(m.group(1))
            if i in store.fail_get:
                return "Failed", {"statusCode": 503}
            got = store.get(i)
            if got is None:
                return "Failed", {"statusCode": 404}
            f = {k: v for k, v in got[0].items() if k != "WorkDateText"}
            return "Succeeded", dict(f, **{"odata.etag": got[1]})
        if method == "GET":
            assert "$expand=Employee" in uri
            return "Succeeded", {"value": sp_query(uri, store.rows())}
        body = json.loads(p["parameters/body"])
        h = p["parameters/headers"]
        assert h["X-HTTP-Method"] == "MERGE" and body["__metadata"]["type"] == ENTITY and a["inputs"]["retryPolicy"] == {"type": "none"}
        assert h["IF-MATCH"] != "*", "never a wildcard ETag"
        writes.append((int(m.group(1)), {k: v for k, v in body.items() if k != "__metadata"}, h["IF-MATCH"]))
        try:
            store.update(int(m.group(1)), body, h["IF-MATCH"])
        except AE.ConflictError:
            return "Failed", {"statusCode": 412}
        except ConnectionError:
            return "Failed", {"statusCode": 500}
        return "Succeeded", None
    return mocks


def items_json(*pairs):
    return json.dumps([{"itemId": i, "etag": e} for i, e in pairs])


AUDIT_KEYS = ("EventType", "Action", "ActionText", "Decision", "ResultCode", "TargetItemId", "TargetLegacyId", "OwnerEmployeeItemId",
              "WorkDate", "IsOnBehalf", "ChangeJson", "CorrelationId", "ActorUpn")


class _Both(unittest.TestCase):
    maxDiff = None

    def approve(self, upn, roles, items, *, decoys=None, cid="run-aq", store_kw=None, fail_audit=(), fail_owner=False, profile_fail=False,
                items_list=ITEMS):
        fs, rs = Store(items_list, **(store_kw or {})), Store(items_list, **(store_kw or {}))
        posts, writes = [], []
        trig = {"text": items if isinstance(items, str) else items_json(*items), "text_1": "client-1"}
        trig.update({"text_%d" % (2 + i): (decoys or {}).get(k, "") for i, k in enumerate(bf.APPROVE_DECOYS)})
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW, mocks=mocks_for(
            upn, roles, fs, posts, writes, fail_audit=fail_audit, fail_owner=fail_owner, profile_fail=profile_fail)).run(APPROVE)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "messageCode": resp["messagecode"], "correlationId": resp["correlationid"],
             "approvedCount": int(resp["approvedcount"]), "refusedCount": int(resp["refusedcount"]), "auditStatus": resp["auditstatus"],
             "results": json.loads(resp["results"]), "warnings": json.loads(resp["warnings"])}
        g = guard(upn, roles, cid, decoys)
        r = AE.approve_entries(g, caller_disc(upn), dict({"Items": trig["text"], "ClientRequestId": "client-1"}, **(decoys or {})), rs,
                               owner_lookup(fail_owner), correlation_id=cid, approved_on=NOW, profile_failed=profile_fail,
                               authorization_audit_ok=not ({"AuthorizationAllow", "AuthorizationDeny"} & set(fail_audit)),
                               row_audit_ok=lambda t: "Approval:%s" % (str(AE._pos_int(t)) if AE._pos_int(t) else "") not in fail_audit
                               and "Approval" not in fail_audit)
        rd = {k: getattr(r, k) for k in f}
        self.assertEqual(f, rd, "reference vs flow")
        self.assertEqual(fs.items, rs.items, "stored rows differ")
        appr = [{k: p.get(k) for k in AUDIT_KEYS} for p in posts if p.get("EventType") == "Approval"]
        self.assertEqual(appr, [{k: a.get(k) for k in AUDIT_KEYS} for a in r.audit], "Approval audit rows differ")
        self.assertEqual([(i, b) for i, b, _ in writes], r.writes, "MERGE bodies differ")
        self.ctx = dict(store=fs, posts=posts, writes=writes, run=run, ref=r)
        return f

    def codes(self, f):
        return [x["resultcode"] for x in f["results"]]


TL, APR, EXE = ("EMP", "TL"), ("EMP", "APR"), ("EXE",)
ME = u("peer")  # caller: employee 12, discipline D1


class Approve(_Both):

    def test_AQ01_team_leader_same_discipline_ok(self):
        f = self.approve(ME, TL, [(1, '"1,1"')])
        self.assertEqual((f["ok"], f["code"], f["approvedCount"], self.codes(f), f["results"][0]["etag"]), (True, "OK", 1, ["OK"], '"1,2"'))
        row = self.ctx["store"].items[1]
        self.assertEqual((row["EntryStatus"], row["ApprovedBy"], row["ApprovedOn"]), ("Approved", ME, NOW))

    def test_AQ02_team_leader_cross_discipline_denied_no_write(self):
        for item in (3, 10):  # 10: DisciplineCode snapshot D1 but the owner is now in D2 (transfer) -> current discipline wins
            f = self.approve(ME, TL, [(item, '"%d,1"' % item)])
            self.assertEqual((f["code"], self.codes(f)), ("REFUSED", ["SCOPE_NOT_ALLOWED"]), item)
            self.assertEqual(self.ctx["writes"], [])

    def test_AQ03_approver_and_executive_company(self):
        for roles in (APR, EXE):
            f = self.approve(ME, roles, [(3, '"3,1"'), (1, '"1,1"')])
            self.assertEqual(self.codes(f), ["OK", "OK"], roles)

    def test_AQ04_admin_employee_pmo_request_level_denied(self):
        for roles in (("ADM",), ("EMP",), ("PMO",), ("EMP", "ADM", "PMO", "HR", "FIN")):
            f = self.approve(ME, roles, [(1, '"1,1"')])
            self.assertEqual((f["ok"], f["code"], f["results"], f["auditStatus"]), (False, "ROLE_NOT_ALLOWED", [], "OK"), roles)
            self.assertEqual(self.ctx["writes"], [])
            self.assertFalse([p for p in self.ctx["posts"] if p["EventType"] == "Approval"])

    def test_AQ05_self_approval_denied_for_every_role(self):
        for roles in (TL, APR, EXE, ("TL", "APR", "EXE")):
            f = self.approve(ME, roles, [(4, '"4,1"'), (11, '"11,1"')])  # own employee; own employee + forged upper-case OwnerUpn
            self.assertEqual(self.codes(f), ["ROLE_NOT_ALLOWED", "ROLE_NOT_ALLOWED"], roles)
            self.assertEqual(self.ctx["writes"], [])
        f = self.approve(u("emp"), APR, [(11, '"11,1"')])  # stored OwnerUpn = caller (case-insensitive) -> self even if the employee differs
        self.assertEqual(self.codes(f), ["ROLE_NOT_ALLOWED"])

    def test_AQ06_approved_locked_original_stamp_kept(self):
        f = self.approve(ME, APR, [(5, '"5,1"')])
        self.assertEqual(self.codes(f), ["LOCKED"])
        self.assertEqual((self.ctx["store"].items[5]["ApprovedBy"], self.ctx["writes"]), (None, []))

    def test_AQ07_deleted_missing_or_bad_id_not_found(self):
        f = self.approve(ME, APR, [(6, '"6,1"'), (404, '"x"'), ("abc", ""), (-3, ""), (0, ""), ("1.5", ""), (None, "")])
        self.assertEqual(self.codes(f), ["NOT_FOUND"] * 7)
        self.assertEqual(self.ctx["writes"], [])

    def test_AQ08_stale_missing_or_wildcard_etag_conflict(self):
        f = self.approve(ME, APR, [(1, '"1,0"'), (2, ""), (3, "*")])
        self.assertEqual(self.codes(f), ["CONFLICT"] * 3)
        self.assertEqual(self.ctx["writes"], [])

    def test_AQ09_owner_without_discipline_or_missing_owner_row(self):
        f = self.approve(ME, TL, [(7, '"7,1"')])
        self.assertEqual(self.codes(f), ["SCOPE_NOT_ALLOWED"])
        for roles in (TL, APR):
            f = self.approve(ME, roles, [(12, '"12,1"')])
            self.assertEqual(self.codes(f), ["SCOPE_NOT_ALLOWED"], roles)
        f = self.approve(u("nodisc"), TL, [(1, '"1,1"')])  # Team Leader without a discipline: caller-level refusal
        self.assertEqual((f["code"], f["results"]), ("SCOPE_NOT_ALLOWED", []))

    def test_AQ10_inactive_owner_approvable_in_scope(self):
        self.assertEqual(self.codes(self.approve(ME, TL, [(8, '"8,1"')])), ["OK"])

    def test_AQ11_request_order_kept(self):
        f = self.approve(ME, APR, [(3, '"3,1"'), (1, '"1,1"'), (2, '"2,1"')])
        self.assertEqual([x["itemid"] for x in f["results"]], ["3", "1", "2"])

    def test_AQ12_mixed_partial_and_all_refused(self):
        f = self.approve(ME, TL, [(1, '"1,1"'), (3, '"3,1"'), (4, '"4,1"'), (5, '"5,1"')])
        self.assertEqual((f["ok"], f["code"], f["messageCode"], f["approvedCount"], f["refusedCount"]), (True, "PARTIAL", "MSG_PARTIAL", 1, 3))
        self.assertEqual(self.codes(f), ["OK", "SCOPE_NOT_ALLOWED", "ROLE_NOT_ALLOWED", "LOCKED"])
        self.assertEqual([x["messagecode"] for x in f["results"]], ["MSG_OK", "MSG_SCOPE_NOT_ALLOWED", "MSG_ROLE_NOT_ALLOWED", "MSG_LOCKED"])
        f = self.approve(ME, TL, [(3, '"3,1"'), (4, '"4,1"')])
        self.assertEqual((f["ok"], f["code"], f["messageCode"]), (False, "REFUSED", "MSG_REFUSED"))

    def test_AQ13_malformed_items_validation_request(self):
        bad = ["", "not json", "{}", "[]", "[1, 2]", '{"itemId": 1}', json.dumps([{"itemId": 1, "etag": "a"}, {"itemId": "1", "etag": "b"}]),
               json.dumps([{"itemId": i, "etag": "e"} for i in range(1, 52)])]
        for raw in bad:
            f = self.approve(ME, APR, raw)
            self.assertEqual((f["ok"], f["code"], f["results"]), (False, "VALIDATION_REQUEST", []), raw[:40])
            self.assertEqual(self.ctx["writes"], [])
        f = self.approve(ME, APR, json.dumps([{"itemId": 404, "etag": "e"}] + [{"itemId": i, "etag": "e"} for i in range(1000, 1049)]))
        self.assertEqual((f["code"], len(f["results"])), ("REFUSED", 50))  # exactly 50 accepted

    def test_AQ14_one_row_412_does_not_affect_others(self):
        f = self.approve(ME, APR, [(1, '"1,1"'), (2, '"2,1"'), (3, '"3,1"')], store_kw={"race": [2]})
        self.assertEqual(self.codes(f), ["OK", "CONFLICT", "OK"])
        self.assertEqual(self.ctx["store"].items[2]["EntryStatus"], "Draft")

    def test_AQ15_write_failure_error_and_read_failure_error(self):
        f = self.approve(ME, APR, [(1, '"1,1"'), (2, '"2,1"')], store_kw={"fail_write": [1], "fail_get": [2]})
        self.assertEqual(self.codes(f), ["ERROR", "ERROR"])
        f = self.approve(ME, APR, [(1, '"1,1"')], fail_owner=True)
        self.assertEqual(self.codes(f), ["ERROR"])

    def test_AQ16_merge_body_exactly_three_fields_if_match_stored(self):
        self.approve(ME, APR, [(1, '"1,1"')])
        (i, body, if_match), = self.ctx["writes"]
        self.assertEqual((i, sorted(body), if_match), (1, ["ApprovedBy", "ApprovedOn", "EntryStatus"], '"1,1"'))

    def test_AQ17_preserved_columns(self):
        before = copy.deepcopy(next(x for x in ITEMS if x["Id"] == 1))
        self.approve(ME, APR, [(1, '"1,1"')])
        after = self.ctx["store"].items[1]
        for k in ("OwnerUpn", "ActorUpn", "EmployeeId", "EmployeeItemId", "DisciplineCode", "LegacyId", "PeriodKey", "WorkDate",
                  "Created", "AuthorId", "CorrelationId", "Hours", "Remark", "ProjectId"):
            self.assertEqual(after[k], before[k], k)

    def test_AQ18_approved_on_is_utc_z_instant_and_approver_from_trusted_caller(self):
        self.approve(ME.upper(), APR, [(1, '"1,1"')], decoys={"ApprovedBy": u("far"), "ApproverUpn": u("far"), "OwnerUpn": ME})
        row = self.ctx["store"].items[1]
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["ApprovedOn"]))
        self.assertEqual(row["ApprovedBy"], ME)  # normalised trusted UPN, never a request value
        self.assertEqual(self.ctx["run"].results["ApprovedAt"]["inputs"] if "inputs" in self.ctx["run"].results["ApprovedAt"] else
                         APPROVE["ApprovedAt"]["inputs"], "@utcNow('yyyy-MM-ddTHH:mm:ssZ')")

    def test_AQ19_one_authorization_row_one_approval_row_per_item(self):
        self.approve(ME, TL, [(1, '"1,1"'), (3, '"3,1"'), ("x", "")])
        ev = [p["EventType"] for p in self.ctx["posts"]]
        self.assertEqual(ev, ["AuthorizationAllow", "Approval", "Approval", "Approval"])

    def test_AQ20_action_text_and_change_json(self):
        self.approve(ME, TL, [(2, '"2,1"'), (3, '"3,1"')])
        ok, refused = [p for p in self.ctx["posts"] if p["EventType"] == "Approval"]
        self.assertEqual((ok["ActionText"], ok["Decision"], ok["ResultCode"], ok["ChangeJson"], ok["IsOnBehalf"]),
                         ("Phê duyệt: 2026-10-08", "ALLOW", "ALLOW", '{"EntryStatus":"Approved"}', True))
        self.assertEqual((refused["Decision"], refused["ResultCode"], refused["ChangeJson"], refused["TargetLegacyId"]),
                         ("DENY", "SCOPE_NOT_ALLOWED", "", "L-3"))

    def test_AQ21_correlation_id_shared(self):
        f = self.approve(ME, TL, [(1, '"1,1"'), (3, '"3,1"')], cid="run-corr-1")
        self.assertTrue(all(p["CorrelationId"] == f["correlationId"] == "run-corr-1" for p in self.ctx["posts"]))

    def test_AQ22_pre_write_audit_failure_internal_error_no_write(self):
        for ev in ("AuthorizationAllow",):
            f = self.approve(ME, APR, [(1, '"1,1"')], fail_audit=(ev,))
            self.assertEqual((f["ok"], f["code"], f["messageCode"], f["results"]), (False, "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM", []))
            self.assertEqual(self.ctx["writes"], [])
        f = self.approve(ME, APR, [(1, '"1,1"')], profile_fail=True)
        self.assertEqual((f["code"], f["writes"] if "writes" in f else self.ctx["writes"]), ("DIRECTORY_ERROR", []))

    def test_AQ23_post_write_audit_failure_degraded_row_stays_ok(self):
        f = self.approve(ME, APR, [(1, '"1,1"'), (2, '"2,1"')], fail_audit=("Approval:1",))
        self.assertEqual((f["ok"], f["code"], self.codes(f), f["auditStatus"], f["warnings"]), (True, "OK", ["OK", "OK"], "AUDIT_DEGRADED", ["AUDIT_DEGRADED"]))
        self.assertEqual(self.ctx["run"].terminated["runError"]["code"], "AUDIT_DEGRADED")
        self.assertEqual(self.ctx["store"].items[1]["EntryStatus"], "Approved")  # no undo, no retry

    def test_AQ24_forged_inputs_ignored(self):
        decoys = {"OwnerUpn": u("far"), "ApprovedBy": u("far"), "ApproverUpn": u("far"), "Role": "APR", "Scope": "company",
                  "EntryStatus": "Draft", "DisciplineCode": "D2"}
        f = self.approve(ME, TL, [(3, '"3,1"')], decoys=decoys)
        self.assertEqual(self.codes(f), ["SCOPE_NOT_ALLOWED"])  # TL stays discipline scope whatever the request claims
        self.assertEqual(self.ctx["run"].results["Guard_result"]["outputs"]["IgnoredInputs"], sorted(bf.APPROVE_DECOYS))
        f = self.approve(ME, ("EMP",), [(1, '"1,1"')], decoys=decoys)
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED")

    def test_AQ25_inactive_unmapped_duplicate_caller_denied(self):
        for upn, code in ((u("gone"), "INACTIVE_EMPLOYEE"), (u("nobody"), "UNMAPPED_IDENTITY"), (u("twin"), "DUPLICATE_IDENTITY")):
            f = self.approve(upn, APR, [(1, '"1,1"')])
            self.assertEqual((f["code"], f["results"]), (code, []), upn)
            self.assertEqual(self.ctx["writes"], [])

    def test_AQ26_new_etag_not_read_back_reload_warning(self):
        f = self.approve(ME, APR, [(1, '"1,1"')], store_kw={"readback": "fail"})
        self.assertEqual((self.codes(f), f["results"][0]["etag"], f["warnings"]), (["OK"], "", ["WARN_RELOAD_REQUIRED"]))

    def test_AQ_EQ_per_row_outcome_equals_approval_rules_decide(self):
        """For every role x {own, same discipline, other discipline, missing owner}: TS-Approve's row code (Draft, fresh ETag)
        equals approval_rules.decide (request-level refusals are reported as that code with no rows)."""
        targets = {"own": 4, "same": 1, "other": 3, "missing": 12}
        for role in tg.ROLE_KEYS:
            for kind, item in targets.items():
                f = self.approve(ME, (role,), [(item, '"%d,1"' % item)])
                got = f["results"][0]["resultcode"] if f["results"] else f["code"]
                owner = BY_ID.get(next(x for x in ITEMS if x["Id"] == item)["EmployeeItemId"])
                d = ar.decide(ident(ME, (role,)), lk, lambda c: [e for e in EMPS if e.legacy_id == c], tg.CFG, POLICY, "Approve",
                              ar.StoredEntry(owner.legacy_id if owner else "NO-SUCH", next(x for x in ITEMS if x["Id"] == item)["OwnerUpn"]))
                self.assertEqual(got, "OK" if d.allowed else d.result_code, (role, kind))


class ApproveFlowOnly(unittest.TestCase):
    """Technical paths without a reference counterpart."""

    def run_flow(self, **kw):
        store, posts, writes = Store(ITEMS), [], []
        run = wdl_sim.Run(trigger_body={"text": items_json((1, '"1,1"')), "text_1": ""}, run_name="run-t", now=NOW,
                          mocks=mocks_for(ME, APR, store, posts, writes, **kw)).run(APPROVE)
        out = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        return out, writes

    def test_AQ_T1_entity_type_unreadable_error_no_write(self):
        out, writes = self.run_flow(fail_type=True)
        self.assertEqual((out["resultcode"], writes), ("ERROR", []))

    def test_AQ_T2_settings_unreadable_config_unresolved_no_read(self):
        out, writes = self.run_flow(fail_settings=True)
        self.assertEqual((out["resultcode"], writes), ("CONFIG_UNRESOLVED", []))

    def test_AQ_T3_error_body_has_response_keys(self):
        self.assertEqual(list(APPROVE["Respond_error"]["inputs"]["body"]), list(APPROVE["Respond"]["inputs"]["body"]))
        self.assertEqual(list(APPROVE["Respond"]["inputs"]["body"]), ["ok", "resultcode", "messagecode", "correlationid", "approvedcount",
                                                                      "refusedcount", "auditstatus", "results", "warnings"])


# ---------------------------------------------------------------- TS-ReadTeam

class Team(unittest.TestCase):
    maxDiff = None

    def team(self, upn, roles, period="2026-10", after="", size="", decoys=None, cid="run-rt", items=ITEMS, fail_audit=(), leak=None):
        fs = Store(items)
        posts, writes = [], []
        trig = {"text": period, "text_1": after, "text_2": size}
        trig.update({"text_%d" % (3 + i): (decoys or {}).get(k, "") for i, k in enumerate(bf.TEAM_DECOYS)})
        mocks = mocks_for(upn, roles, fs, posts, writes, fail_audit=fail_audit)
        if leak:
            inner = mocks

            def mocks(name, a, p):  # noqa: F811 - a misbehaving query that returns an extra row
                st, body = inner(name, a, p)
                if name == "Query":
                    body = {"value": body["value"] + [dict(fs.rows()[leak - 1])]}
                return st, body
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW, mocks=mocks).run(TEAM)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "messageCode": resp["messagecode"], "rows": json.loads(resp["rows"]),
             "nextAfterId": int(resp["nextafterid"]), "pageSize": int(resp["pagesize"])}

        def query(flt, top):
            got = sp_query("x?$filter=%s&$top=%d" % (flt, top), fs.rows())
            if leak:
                got = got + [fs.rows()[leak - 1]]
            return [(r["Id"], dict(r, OwnerName=(r["Employee"] or {}).get("Title"), OwnerCode=(r["Employee"] or {}).get("LegacyId")),
                     r["odata.etag"]) for r in got]
        r = AE.read_team(guard(upn, roles, cid, decoys), caller_disc(upn), dict({"PeriodKey": period, "AfterId": after, "PageSize": size},
                                                                                 **(decoys or {})),
                         query, correlation_id=cid, business_date=lambda v: bd.business_date(v, TZ),
                         authorization_audit_ok=not ({"AuthorizationAllow", "AuthorizationDeny"} & set(fail_audit)))
        self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.ctx = dict(posts=posts, run=run, writes=writes)
        return f

    def ids(self, f):
        return [x["id"] for x in f["rows"]]

    def test_RT01_team_leader_discipline_drafts_of_period_not_own(self):
        f = self.team(ME, TL)
        self.assertEqual(self.ids(f), [1, 2, 7, 8, 10, 12])  # D1 snapshot, Draft, 2026-10; own 4 / 11 excluded; 10 (D2 owner, D1 snapshot) listed
        row = f["rows"][0]
        self.assertEqual((row["ownerName"], row["ownerCode"], row["workDate"], row["status"], row["etag"]), ("Name E1", "E1", "2026-10-07", "Draft", '"1,1"'))

    def test_RT02_company_scope_all_disciplines(self):
        self.assertEqual(self.ids(self.team(ME, APR)), [1, 2, 3, 7, 8, 10, 12])

    def test_RT03_own_rows_excluded_by_upn_and_employee(self):
        f = self.team(ME, EXE)
        self.assertFalse({4, 11} & set(self.ids(f)))
        self.assertIn("OwnerUpn ne 'peer@tenant-a.invalid' and EmployeeItemId ne 12", self.ctx["run"].results["Filter"]["outputs"])

    def test_RT04_draft_only_and_period_only(self):
        f = self.team(ME, APR)
        self.assertFalse({5, 6, 9} & set(self.ids(f)))
        self.assertEqual(self.ids(self.team(ME, APR, period="2026-11")), [9])

    def test_RT05_paging(self):
        f = self.team(ME, APR, size="3")
        self.assertEqual((self.ids(f), f["nextAfterId"], f["pageSize"]), ([1, 2, 3], 3, 3))
        f = self.team(ME, APR, after="3", size="3")
        self.assertEqual((self.ids(f), f["nextAfterId"]), ([7, 8, 10], 10))
        f = self.team(ME, APR, after="10", size="3")
        self.assertEqual((self.ids(f), f["nextAfterId"]), ([12], 0))

    def test_RT06_admin_employee_denied(self):
        for roles in (("ADM",), ("EMP",), ("PMO",)):
            f = self.team(ME, roles)
            self.assertEqual((f["ok"], f["code"], f["rows"]), (False, "ROLE_NOT_ALLOWED", []), roles)
            self.assertFalse([p for p in self.ctx["posts"] if p["EventType"] == "ReadProxy" and p["Decision"] == "ALLOW"])

    def test_RT07_period_validation(self):
        for p in ("", "2026-13", "2026-00", "2026-1", "26-10", "2026/10", "202610-", "2026-10-01", "abcd-ef"):
            self.assertEqual(self.team(ME, APR, period=p)["code"], "VALIDATION_DATE", p)

    def test_RT08_paging_validation(self):
        for a, s in (("x", ""), ("", "1.5"), ("", "ten")):
            self.assertEqual(self.team(ME, APR, after=a, size=s)["code"], "VALIDATION_LOOKUP")

    def test_RT09_leak_check(self):
        self.assertEqual(self.team(ME, APR, leak=4)["code"], "ERROR_LEAK")   # own row returned by a broken query
        self.assertEqual(self.team(ME, APR, leak=5)["code"], "ERROR_LEAK")   # non-Draft row
        self.assertEqual(self.team(ME, TL, leak=3)["code"], "ERROR_LEAK")    # other discipline under discipline scope

    def test_RT10_mandatory_audits(self):
        self.team(ME, TL)
        self.assertEqual([p["EventType"] for p in self.ctx["posts"]], ["AuthorizationAllow", "ReadProxy"])
        self.assertEqual(self.ctx["posts"][1]["Action"], "ReadTeam")
        f = self.team(ME, TL, fail_audit=("AuthorizationAllow",))
        self.assertEqual((f["code"], f["rows"]), ("INTERNAL_ERROR", []))

    def test_RT11_forged_scope_ignored_and_read_only(self):
        f = self.team(ME, TL, decoys={"DisciplineCode": "D2", "Scope": "company", "Role": "APR", "OwnerUpn": u("far")})
        self.assertEqual(self.ids(f), [1, 2, 7, 8, 10, 12])
        self.assertEqual(self.ctx["writes"], [])

    def test_RT12_team_leader_without_discipline_denied(self):
        self.assertEqual(self.team(u("nodisc"), TL)["code"], "SCOPE_NOT_ALLOWED")


class Schema(unittest.TestCase):
    def test_ST01_approved_by_is_text_upn_not_person(self):
        import r1_lists
        cols = {c["internalName"]: c for c in r1_lists.TARGETS[r1_lists.ENTRIES]["fields"]}
        self.assertEqual((cols["ApprovedBy"]["type"], cols["ApprovedBy"].get("gate")), ("Text", None))
        self.assertEqual((cols["ApprovedOn"]["type"], cols["ApprovedOn"]["dateOnly"], cols["ApprovedOn"].get("gate")), ("DateTime", False, None))
        body = APPROVE["If_ok"]["actions"]["Rows"]["actions"]["If_write"]["actions"]["R_body"]["inputs"]
        self.assertEqual(sorted(k for k in body if k != "__metadata"), sorted(AE.APPROVAL_FIELDS))
        self.assertEqual(set(AE.APPROVAL_FIELDS) - set(cols), set(), "every written column exists in the data model")

    def test_ST02_canvas_has_no_direct_entries_source(self):
        sys.path.insert(0, os.path.join(HERE, "..", "powerapp"))
        import build_demo_app as app
        self.assertNotIn("TimesheetEntries", app.REFERENCE_SOURCES)
        src = json.dumps(app.screens())
        self.assertNotIn("TimesheetEntries", src)

    def test_ST03_flows_write_only_entries_and_audit(self):
        def posts(x, out):
            if isinstance(x, dict):
                if x.get("parameters/method") == "POST":
                    out.append(re.search(r"getbytitle\('([^']*)'\)", x["parameters/uri"]).group(1))
                for v in x.values():
                    posts(v, out)
            return out
        self.assertEqual(sorted(set(posts(APPROVE, []))), ["TimesheetEntries", "_Audit"])
        self.assertEqual(sorted(set(posts(TEAM, []))), ["_Audit"])


if __name__ == "__main__":
    unittest.main()
