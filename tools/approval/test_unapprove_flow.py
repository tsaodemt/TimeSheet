"""S07.3 TS-Unapprove and the TS-ReadTeam Approved review mode: reference (approve_entries.unapprove_entry / read_team) vs
generated flows (build_approval_flows.unapprove_actions / read_team_actions) in the WDL simulator, one SharePoint-like
store per side. Tests UQ01-UQ38 (offline; synthetic data only)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "timesheet"),
          os.path.join(HERE, "..", "powerapp")):
    sys.path.insert(0, p)
import approve_entries as AE  # noqa: E402
import build_approval_flows as bf  # noqa: E402
import business_dates as bd  # noqa: E402
import guard as G  # noqa: E402
import test_approve_flow as ta  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from test_r1_save_flow import sp_query  # noqa: E402

UNAPPROVE = bf.unapprove_actions(**ta.KW)
TEAM = ta.TEAM
u, BY_ID, NOW = tg.u, ta.BY_ID, ta.NOW
ME = u("peer")  # caller: employee 12, discipline D1
APPROVED_BY = u("emp")


def approved(i, emp, **kw):
    e = ta.entry(i, emp, **kw)
    e.update(EntryStatus="Approved", ApprovedBy=APPROVED_BY, ApprovedOn="2026-10-08T01:02:03Z")
    return e


# 1 foreign D1, 2 foreign D2, 3 own (employee 12), 4 own by stored OwnerUpn only, 5 Draft, 6 Deleted, 7 owner row missing
ITEMS = [approved(1, 11), approved(2, 13), approved(3, 12), approved(4, 11, owner_upn=ME.upper()), ta.entry(5, 11),
         dict(approved(6, 11), EntryStatus="Deleted"), dict(approved(7, 11), EmployeeItemId=99, EmployeeId=99),
         approved(8, 11, period="2026-11")]
PRESERVED = ("OwnerUpn", "ActorUpn", "EmployeeId", "EmployeeItemId", "DisciplineCode", "LegacyId", "PeriodKey", "WorkDate",
             "Created", "AuthorId", "CorrelationId", "Hours", "Remark", "ProjectId")
AUDIT_KEYS = ta.AUDIT_KEYS


def guard(upn, roles, cid, action="TS.Unapprove", decoys=None):
    return G.authorize(ta.ident(upn, roles), ta.lk, ta.lk, tg.CFG, ta.POLICY, action, "self", correlation_id=cid,
                       **{k: "" for k in (decoys or {})})


class _Both(unittest.TestCase):
    maxDiff = None

    def unapprove(self, upn, roles, item, etag, *, decoys=None, cid="run-uq", store_kw=None, fail_audit=(), fail_owner=False,
                  profile_fail=False):
        fs, rs = ta.Store(ITEMS, **(store_kw or {})), ta.Store(ITEMS, **(store_kw or {}))
        posts, writes = [], []
        trig = {"text": str(item), "text_1": etag}
        trig.update({"text_%d" % (2 + i): (decoys or {}).get(k, "") for i, k in enumerate(bf.UNAPPROVE_DECOYS)})
        run = wdl_sim.Run(trigger_body=trig, run_name=cid, now=NOW, mocks=ta.mocks_for(
            upn, roles, fs, posts, writes, fail_audit=fail_audit, fail_owner=fail_owner, profile_fail=profile_fail)).run(UNAPPROVE)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        f = {"ok": resp["ok"] == "true", "code": resp["resultcode"], "messageCode": resp["messagecode"], "correlationId": resp["correlationid"],
             "itemId": resp["itemid"], "etag": resp["etag"], "auditStatus": resp["auditstatus"], "warnings": json.loads(resp["warnings"])}
        r = AE.unapprove_entry(guard(upn, roles, cid, decoys=decoys), dict({"ItemId": trig["text"], "ETag": etag}, **(decoys or {})), rs,
                               ta.owner_lookup(fail_owner), correlation_id=cid, profile_failed=profile_fail,
                               authorization_audit_ok=not ({"AuthorizationAllow", "AuthorizationDeny"} & set(fail_audit)),
                               row_audit_ok=lambda t: "Unapproval" not in fail_audit)
        self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.assertEqual(fs.items, rs.items, "stored rows differ")
        un = [{k: p.get(k) for k in AUDIT_KEYS} for p in posts if p.get("EventType") == "Unapproval"]
        self.assertEqual(un, [{k: a.get(k) for k in AUDIT_KEYS} for a in r["audit"]], "Unapproval audit rows differ")
        self.assertEqual([(i, b) for i, b, _ in writes], r["writes"], "MERGE bodies differ")
        self.ctx = dict(store=fs, posts=posts, writes=writes, run=run, ref=r)
        return f

    def no_write(self):
        self.assertEqual(self.ctx["writes"], [])
        self.assertFalse([p for p in self.ctx["posts"] if p.get("EventType") == "Unapproval" and p.get("Decision") == "ALLOW"])


APR, EXE = ("EMP", "APR"), ("EXE",)
BASE = {r["Id"]: r for r in ITEMS}


class Unapprove(_Both):

    def test_UQ01_approver_unapproves_foreign_approved_row(self):
        f = self.unapprove(ME, APR, 1, '"1,1"')
        self.assertEqual((f["ok"], f["code"], f["messageCode"], f["itemId"], f["etag"]), (True, "OK", "MSG_OK", "1", '"1,2"'))

    def test_UQ02_executive_unapproves_foreign_approved_row_any_discipline(self):
        self.assertEqual(self.unapprove(ME, EXE, 2, '"2,1"')["code"], "OK")

    def test_UQ03_team_leader_denied(self):
        f = self.unapprove(ME, ("EMP", "TL"), 1, '"1,1"')
        self.assertEqual((f["ok"], f["code"], f["itemId"]), (False, "ROLE_NOT_ALLOWED", "1"))
        self.no_write()

    def test_UQ04_employee_denied(self):
        self.assertEqual(self.unapprove(ME, ("EMP",), 1, '"1,1"')["code"], "ROLE_NOT_ALLOWED")
        self.no_write()

    def test_UQ05_pm_denied(self):
        self.assertEqual(self.unapprove(ME, ("PMO",), 1, '"1,1"')["code"], "ROLE_NOT_ALLOWED")
        self.no_write()

    def test_UQ06_app_admin_denied(self):
        self.assertEqual(self.unapprove(ME, ("ADM",), 1, '"1,1"')["code"], "ROLE_NOT_ALLOWED")
        self.no_write()

    def test_UQ07_self_unapprove_denied_for_approver(self):
        for item in (3, 4):  # own employee; stored OwnerUpn = caller (case-insensitive)
            self.assertEqual(self.unapprove(ME, APR, item, '"%d,1"' % item)["code"], "ROLE_NOT_ALLOWED", item)
            self.no_write()

    def test_UQ08_self_unapprove_denied_for_executive_company_scope_no_bypass(self):
        for roles in (EXE, ("APR", "EXE", "TL")):
            self.assertEqual(self.unapprove(ME, roles, 3, '"3,1"')["code"], "ROLE_NOT_ALLOWED", roles)
            self.no_write()

    def test_UQ09_missing_target_not_found(self):
        for item in ("404", "abc", "-3", "0", ""):
            self.assertEqual(self.unapprove(ME, APR, item, '"x"')["code"], "NOT_FOUND", item)
            self.no_write()

    def test_UQ10_deleted_target_not_found(self):
        self.assertEqual(self.unapprove(ME, APR, 6, '"6,1"')["code"], "NOT_FOUND")
        self.no_write()

    def test_UQ11_draft_target_rejected_not_a_noop(self):
        f = self.unapprove(ME, APR, 5, '"5,1"')
        self.assertEqual((f["ok"], f["code"], f["messageCode"]), (False, "NOT_APPROVED", "MSG_NOT_APPROVED"))
        self.no_write()
        self.assertEqual(self.ctx["store"].ver[5], 1, "no write at all on a Draft")

    def test_UQ12_approved_target_eligible(self):
        self.assertEqual(self.unapprove(ME, APR, 1, '"1,1"')["code"], "OK")
        self.assertEqual(self.unapprove(ME, APR, 7, '"7,1"')["code"], "SCOPE_NOT_ALLOWED")  # owner row missing: never eligible

    def test_UQ13_current_etag_succeeds_if_match_stored(self):
        self.unapprove(ME, APR, 1, '"1,1"')
        (i, body, if_match), = self.ctx["writes"]
        self.assertEqual(if_match, '"1,1"')

    def test_UQ14_stale_or_missing_etag_conflict_row_unchanged(self):
        for etag in ('"1,0"', "", "*"):
            f = self.unapprove(ME, APR, 1, etag)
            self.assertEqual(f["code"], "CONFLICT", etag)
            self.no_write()
            self.assertEqual(self.ctx["store"].items[1]["EntryStatus"], "Approved")
        f = self.unapprove(ME, APR, 1, '"1,1"', store_kw={"race": [1]})  # changed between read and MERGE -> 412
        self.assertEqual(f["code"], "CONFLICT")
        self.assertEqual(self.ctx["store"].items[1]["EntryStatus"], "Approved")

    def test_UQ15_no_wildcard_no_retry(self):
        merge = UNAPPROVE["If_ok"]["actions"]["Rows"]["actions"]["If_write"]["actions"]["Merge"]["inputs"]
        self.assertEqual(merge["retryPolicy"], {"type": "none"})
        self.assertNotIn("*", merge["parameters"]["parameters/headers"]["IF-MATCH"])
        self.assertNotIn("If_retry", json.dumps(UNAPPROVE))
        self.unapprove(ME, APR, 1, '"1,1"', store_kw={"race": [1]})
        self.assertEqual(len(self.ctx["writes"]), 1, "exactly one MERGE attempt, never a second unconditional write")

    def test_UQ16_status_approved_to_draft(self):
        self.unapprove(ME, APR, 1, '"1,1"')
        self.assertEqual(self.ctx["store"].items[1]["EntryStatus"], "Draft")

    def test_UQ17_approved_by_cleared(self):
        self.unapprove(ME, APR, 1, '"1,1"')
        self.assertIsNone(self.ctx["store"].items[1]["ApprovedBy"])

    def test_UQ18_approved_on_cleared(self):
        self.unapprove(ME, APR, 1, '"1,1"')
        self.assertIsNone(self.ctx["store"].items[1]["ApprovedOn"])
        (_, body, _), = self.ctx["writes"]
        self.assertEqual(body, {"EntryStatus": "Draft", "ApprovedBy": None, "ApprovedOn": None}, "exactly the three fields")

    def _preserved(self, k):
        self.unapprove(ME, EXE, 2, '"2,1"')
        self.assertEqual(self.ctx["store"].items[2][k], BASE[2][k], k)

    def test_UQ19_owner_preserved(self):
        self._preserved("OwnerUpn")
        self._preserved("ActorUpn")

    def test_UQ20_employee_preserved(self):
        self._preserved("EmployeeId")

    def test_UQ21_employee_item_id_preserved(self):
        self._preserved("EmployeeItemId")

    def test_UQ22_discipline_preserved(self):
        self._preserved("DisciplineCode")

    def test_UQ23_legacy_id_preserved(self):
        self._preserved("LegacyId")

    def test_UQ24_period_key_preserved(self):
        self._preserved("PeriodKey")

    def test_UQ25_work_date_preserved(self):
        self._preserved("WorkDate")

    def test_UQ26_created_preserved(self):
        self._preserved("Created")

    def test_UQ27_author_preserved(self):
        self._preserved("AuthorId")
        for k in PRESERVED:
            self.assertEqual(self.ctx["store"].items[2][k], BASE[2][k], k)

    def test_UQ28_forged_owner_ignored(self):
        f = self.unapprove(ME, APR, 3, '"3,1"', decoys={"OwnerUpn": u("far"), "EmployeeItemId": "13"})
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED")  # own row stays own whatever the request claims
        self.no_write()

    def test_UQ29_forged_role_ignored(self):
        f = self.unapprove(ME, ("EMP", "TL"), 1, '"1,1"', decoys={"Role": "APR"})
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED")
        self.assertEqual(self.ctx["run"].results["Guard_result"]["outputs"]["IgnoredInputs"], sorted(bf.UNAPPROVE_DECOYS))

    def test_UQ30_forged_scope_ignored(self):
        f = self.unapprove(ME, ("EMP", "TL"), 1, '"1,1"', decoys={"Scope": "company", "DisciplineCode": "D2"})
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED")
        self.no_write()

    def test_UQ31_forged_approved_by_and_status_ignored(self):
        self.unapprove(ME, APR, 1, '"1,1"', decoys={"ApprovedBy": u("far"), "ApprovedOn": "2030-01-01T00:00:00Z", "EntryStatus": "Approved"})
        row = self.ctx["store"].items[1]
        self.assertEqual((row["EntryStatus"], row["ApprovedBy"], row["ApprovedOn"]), ("Draft", None, None))

    def test_UQ32_exactly_one_unapproval_audit_event(self):
        self.unapprove(ME, APR, 1, '"1,1"', cid="run-corr-u")
        ev = [p["EventType"] for p in self.ctx["posts"]]
        self.assertEqual(ev, ["AuthorizationAllow", "Unapproval"])
        un = self.ctx["posts"][1]
        self.assertEqual((un["Action"], un["ActionText"], un["Decision"], un["ResultCode"], un["ChangeJson"], un["TargetItemId"],
                          un["TargetLegacyId"], un["ActorUpn"], un["CorrelationId"]),
                         ("Unapprove", "Hủy phê duyệt: 2026-10-07", "ALLOW", "ALLOW", '{"EntryStatus":"Draft"}', "1", "L-1", ME, "run-corr-u"))
        self.assertFalse([p for p in self.ctx["posts"] if p["EventType"] == "Approval"], "never a fake Approval event")
        self.assertEqual(UNAPPROVE["If_ok"]["actions"]["Rows"]["actions"]["Write_Row_audit"]["inputs"]["retryPolicy"], {"type": "none"})

    def test_UQ33_authorization_deny_audit_semantics(self):
        self.unapprove(ME, ("EMP", "TL"), 1, '"1,1"')
        self.assertEqual([(p["EventType"], p["Action"], p["Decision"], p["ResultCode"]) for p in self.ctx["posts"]],
                         [("AuthorizationDeny", "TS.Unapprove", "DENY", "ROLE_NOT_ALLOWED")])
        self.unapprove(ME, APR, 3, '"3,1"')  # allowed request, refused row: one Unapproval DENY row, no ChangeJson
        un = [p for p in self.ctx["posts"] if p["EventType"] == "Unapproval"]
        self.assertEqual([(p["Decision"], p["ResultCode"], p["ChangeJson"]) for p in un], [("DENY", "ROLE_NOT_ALLOWED", "")])

    def test_UQ34_canonical_response_keys_and_error_paths(self):
        keys = ["ok", "resultcode", "messagecode", "correlationid", "itemid", "etag", "auditstatus", "warnings"]
        self.assertEqual(list(UNAPPROVE["Respond"]["inputs"]["body"]), keys)
        self.assertEqual(list(UNAPPROVE["Respond_error"]["inputs"]["body"]), keys)
        f = self.unapprove(ME, APR, 1, '"1,1"', fail_audit=("AuthorizationAllow",))
        self.assertEqual((f["code"], f["messageCode"]), ("INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM"))
        self.no_write()
        f = self.unapprove(ME, APR, 1, '"1,1"', profile_fail=True)
        self.assertEqual(f["code"], "DIRECTORY_ERROR")
        f = self.unapprove(ME, APR, 1, '"1,1"', fail_audit=("Unapproval",))
        self.assertEqual((f["ok"], f["auditStatus"], f["warnings"]), (True, "AUDIT_DEGRADED", ["AUDIT_DEGRADED"]))
        self.assertEqual(self.ctx["run"].terminated["runError"]["code"], "AUDIT_DEGRADED")
        f = self.unapprove(ME, APR, 1, '"1,1"', store_kw={"readback": "fail"})
        self.assertEqual((f["etag"], f["warnings"]), ("", ["WARN_RELOAD_REQUIRED"]))
        f = self.unapprove(ME, APR, 1, '"1,1"', store_kw={"fail_write": [1]})
        self.assertEqual(f["code"], "ERROR")
        f = self.unapprove(ME, APR, 1, '"1,1"', fail_owner=True)
        self.assertEqual(f["code"], "ERROR")

    def test_UQ35_runtime_safe_expressions(self):
        s = json.dumps(UNAPPROVE)
        self.assertNotIn("createArray()", s)
        self.assertNotRegex(s, r"(?<![\w'])''(?!')", "no empty string literal (dropped by the classic designer)")
        hits = []
        old = wdl_sim.BRANCH_MODE
        try:
            wdl_sim.BRANCH_MODE = "audit"
            del wdl_sim.LAZY_HITS[:]
            for roles, item, etag in ((APR, 1, '"1,1"'), (APR, 5, '"5,1"'), (("EMP",), 1, '"1,1"'), (APR, "x", "")):
                self.unapprove(ME, roles, item, etag)
            hits = list(wdl_sim.LAZY_HITS)
        finally:
            wdl_sim.BRANCH_MODE = old
        self.assertEqual(hits, [], "no expression depends on lazy if()/and()/or() evaluation")

    def test_UQ36_ts_approve_not_regressed(self):
        res = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.TestLoader().loadTestsFromTestCase(ta.Approve))
        self.assertTrue(res.wasSuccessful() and res.testsRun >= 27, res.failures[:1])
        approve_body = bf.approve_actions(**ta.KW)["If_ok"]["actions"]["Rows"]["actions"]["If_write"]["actions"]["R_body"]["inputs"]
        self.assertEqual({k: v for k, v in approve_body.items() if k != "__metadata"},
                         {"EntryStatus": "Approved", "ApprovedBy": "@{outputs('Trusted')}", "ApprovedOn": "@{outputs('ApprovedAt')}"})

    def test_UQ37_ts_readteam_pending_not_regressed_and_approved_mode(self):
        res = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.TestLoader().loadTestsFromTestCase(ta.Team))
        self.assertTrue(res.wasSuccessful() and res.testsRun >= 12, res.failures[:1])
        t = Team()
        # row 4 (own by upper-case stored OwnerUpn) is left out here: the test store's `ne` is case-sensitive, SharePoint's is not
        f = t.team(ME, APR, mode="Approved", items=[r for r in ITEMS if r["Id"] != 4])
        self.assertEqual([x["id"] for x in f["rows"]], [1, 2, 7])  # Approved, period 2026-10, never own (3, 4)
        self.assertEqual((f["rows"][0]["approvedBy"], f["rows"][0]["approvedOn"], f["rows"][0]["etag"]), (APPROVED_BY, "2026-10-08T01:02:03Z", '"1,1"'))
        self.assertEqual(t.team(ME, ("EMP", "TL"), mode="Approved")["code"], "ROLE_NOT_ALLOWED")  # TL can approve, cannot review for unapprove
        self.assertEqual(t.team(ME, ("ADM",), mode="Approved")["code"], "ROLE_NOT_ALLOWED")
        self.assertEqual([x["id"] for x in t.team(ME, APR, mode="")["rows"]], [5])  # pending mode: Draft only
        self.assertEqual([x["id"] for x in t.team(ME, APR, mode="Pending")["rows"]], [5])
        self.assertEqual(t.team(ME, APR, mode="all")["code"], "VALIDATION_REQUEST")
        self.assertEqual(t.team(ME, APR, mode="Approved", leak=5, items=[r for r in ITEMS if r["Id"] != 4])["code"], "ERROR_LEAK")  # a Draft row in Approved mode
        t.team(ME, APR, mode="Approved")
        self.assertIn("EntryStatus eq 'Approved'", t.ctx["run"].results["Filter"]["outputs"])

    def test_UQ38_canvas_explicit_action_and_per_row_confirm(self):
        import build_demo_app as app
        scr = app.screens()["scrTeamApproval"]
        c = {k: v for x in scr["Children"] for k, v in x.items()}
        gal = {k: v for x in c["galTeam"]["Children"] for k, v in x.items()}
        btn = gal["btnUnapprove"]["Properties"]
        self.assertEqual(btn["Text"], '="Hủy phê duyệt"')
        self.assertIn('varTeamMode = "Approved"', btn["Visible"])
        self.assertIn("Set(varUnConfirm, true)", btn["OnSelect"])
        self.assertNotIn("TS-Unapprove", btn["OnSelect"], "never without the per-row confirmation")
        self.assertNotIn("OnDoubleClick", json.dumps(app.screens()))
        yes = c["btnUnYes"]["Properties"]["OnSelect"]
        call = yes[yes.index("'TS-Unapprove'.Run("):yes.index("));", yes.index("'TS-Unapprove'.Run("))]
        self.assertEqual(call, "'TS-Unapprove'.Run(Text(varUnRow.id), varUnRow.etag")
        self.assertIn("'TS-ReadTeam'.Run(", yes[yes.index("'TS-Unapprove'"):], "server state is re-read after the action")
        self.assertIn("varUnConfirm", c["lblUnConfirm"]["Properties"]["Visible"])
        self.assertIn('"Approved"', c["btnModeApproved"]["Properties"]["OnSelect"])
        self.assertEqual(c["btnModeApproved"]["Properties"]["Visible"], "=!varNoUnapprove")
        self.assertIn('varTeamMode <> "Approved"', gal["btnSel"]["Properties"]["Visible"])  # no batch unapprove
        self.assertIn('varTeamMode <> "Approved"', c["btnApprove"]["Properties"]["Visible"])
        for k in ("MSG_NOT_APPROVED", "MSG_UNAPPROVE_CONFIRM", "MSG_ROW_UNAPPROVED", "MSG_UNAPPROVE_OK"):
            self.assertIn(k, app.MESSAGES)
        bottom = int(c["btnUnYes"]["Properties"]["Y"].lstrip("=")) + int(c["btnUnYes"]["Properties"]["Height"].lstrip("="))
        self.assertLess(bottom, int(c["galTeam"]["Properties"]["Y"].lstrip("=")), "confirm buttons clear of the gallery")


class Team(unittest.TestCase):
    """TS-ReadTeam harness with the S07.3 Mode input (text_7); the reference guard follows the mode's capability."""

    def runTest(self):  # allow standalone instances
        pass

    def team(self, upn, roles, period="2026-10", after="", size="", decoys=None, cid="run-rt", items=ITEMS, fail_audit=(), leak=None, mode=""):
        fs = ta.Store(items)
        posts, writes = [], []
        trig = {"text": period, "text_1": after, "text_2": size, "text_7": mode}
        trig.update({"text_%d" % (3 + i): (decoys or {}).get(k, "") for i, k in enumerate(bf.TEAM_DECOYS)})
        inner = ta.mocks_for(upn, roles, fs, posts, writes, fail_audit=fail_audit)

        def mocks(name, a, p):
            st, body = inner(name, a, p)
            if leak and name == "Query":
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
        action = "TS.Unapprove" if mode.strip().lower() == "approved" else "TS.Approve"
        r = AE.read_team(guard(upn, roles, cid, action, decoys), ta.caller_disc(upn),
                         dict({"PeriodKey": period, "AfterId": after, "PageSize": size, "Mode": mode}, **(decoys or {})),
                         query, correlation_id=cid, business_date=lambda v: bd.business_date(v, ta.TZ),
                         authorization_audit_ok=not ({"AuthorizationAllow", "AuthorizationDeny"} & set(fail_audit)))
        self.assertEqual(f, {k: r[k] for k in f}, "reference vs flow")
        self.ctx = dict(posts=posts, run=run, writes=writes)
        return f


if __name__ == "__main__":
    unittest.main()
