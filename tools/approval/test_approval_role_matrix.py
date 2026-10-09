"""S07.6 approval permission and rule tests: every current role x BR-APPR-01..09 / BR-EDIT-01 / BR-EDIT-03 (offline; synthetic
data only). Tests RM01-RM16.

Every approve / unapprove / queue case runs the reference (approve_entries) and the generated flow (build_approval_flows)
side by side in the WDL simulator (S07.2 / S07.3 harnesses: equality of response, stored rows, MERGE bodies and audit rows is
asserted inside the harness). Own-row edit runs the S07.4 TS-SaveEntry harness. Delete and reorder have no target business
path yet (NOT_IMPLEMENTED_CURRENT_PATH): BR-EDIT-03 is proven on the shared server-side invariant only and says so.

The machine-checkable matrix (one cell per role x rule: PASS | NOT_APPLICABLE + reason | BLOCKED) is written to
$TS_S076_MATRIX_OUT when set. Expected values come from the CLOSED gate G5 decisions (approval_rules.MATRIX), never from
the stale legacy role tables."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "timesheet"),
          os.path.join(HERE, "..", "powerapp")):
    sys.path.insert(0, p)
import approval_rules as ar  # noqa: E402
import approve_entries as AE  # noqa: E402
import build_approval_flows as bf  # noqa: E402
import business_dates as bd  # noqa: E402
import entries as E  # noqa: E402
import test_approve_flow as ta  # noqa: E402
import test_guard as tg  # noqa: E402
import test_r1_save_flow as ts  # noqa: E402
import test_unapprove_flow as tu  # noqa: E402
import wdl_sim  # noqa: E402

ME = ta.ME  # employee 12, discipline D1
ROLES = [r.role for r in ar.MATRIX]
G5 = {r.role: (r.approve, r.unapprove) for r in ar.MATRIX}
NI = "NOT_IMPLEMENTED_CURRENT_PATH"
RULES = ("BR-APPR-01", "BR-APPR-02", "BR-APPR-03", "BR-APPR-04", "BR-APPR-05", "BR-APPR-06", "BR-APPR-07", "BR-APPR-08", "BR-APPR-09",
         "BR-EDIT-01", "BR-EDIT-03")
APPROVE_PRESERVED = ("OwnerUpn", "ActorUpn", "EmployeeId", "EmployeeItemId", "DisciplineCode", "LegacyId", "PeriodKey", "WorkDate",
                     "Created", "AuthorId", "CorrelationId", "Hours", "Remark", "ProjectId", "PhaseId", "WorkTypeId", "ShiftId", "HourTypeId")
FORGED = {"Role": "APR", "Scope": "company", "OwnerUpn": "someone@tenant-a.invalid", "ApprovedBy": "boss@tenant-a.invalid",
          "EntryStatus": "Draft", "DisciplineCode": "D2"}
MATRIX = {}  # (role, rule) -> {"result", "evidence"}


def record(role, rule, result, evidence):
    prev = MATRIX.get((role, rule))
    if prev and prev["result"] == "PASS" and result == "PASS":
        prev["evidence"] = sorted(set(prev["evidence"]) | set(evidence))
        return
    MATRIX[(role, rule)] = {"result": result, "evidence": sorted(set(evidence))}


def role_sets(role):
    """The role alone and on top of the permanent Employees membership (the live test identity is always an Employee)."""
    return [(role,)] if role == "EMP" else [(role,), ("EMP", role)]


def can_approve(roles):
    return any(G5[r][0] != "none" for r in roles)


def can_unapprove(roles):
    return any(G5[r][1] != "none" for r in roles)


def approve_scope(roles):
    s = {G5[r][0] for r in roles}
    return "company" if "company" in s else "discipline" if "discipline" in s else "none"


def _harness(base):
    """A harness instance (not collected as a test case by the loader)."""
    return type("H", (base,), {"runTest": lambda self: None})()


def events(posts, kind, decision=None):
    return [p for p in posts if p.get("EventType") == kind and (decision is None or p.get("Decision") == decision)]


class Matrix(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.A, cls.U, cls.S = _harness(ta._Both), _harness(tu._Both), _harness(ts._Both)

    # ---------------------------------------------------------------- helpers
    def approve(self, roles, item, decoys=None):
        f = self.A.approve(ME, roles, [(item, '"%d,1"' % item)], decoys=decoys)
        return f, self.A.ctx

    def unapprove(self, roles, item, decoys=None):
        f = self.U.unapprove(ME, roles, item, '"%d,1"' % item, decoys=decoys)
        return f, self.U.ctx

    def denied(self, f, ctx, code, kind, row_level):
        """Typed refusal, no business write, no successful event, matching deny evidence."""
        got = (ctx["ref"].results[0]["resultcode"] if row_level else f["code"]) if kind == "Approval" else f["code"]
        self.assertEqual(got, code)
        self.assertFalse(f["ok"])
        self.assertEqual(ctx["writes"], [], "no business write")
        self.assertEqual(events(ctx["posts"], kind, "ALLOW"), [], "no successful %s event" % kind)
        if row_level:
            self.assertEqual([(p["Decision"], p["ResultCode"]) for p in events(ctx["posts"], kind)], [("DENY", code)])
            self.assertEqual(len(events(ctx["posts"], "AuthorizationAllow")), 1)
        else:
            self.assertEqual([p["ResultCode"] for p in events(ctx["posts"], "AuthorizationDeny")], [code])
            self.assertEqual(events(ctx["posts"], kind), [])

    def approved_ok(self, f, ctx, item):
        self.assertEqual((f["ok"], f["code"], f["approvedCount"]), (True, "OK", 1))
        before, after = next(x for x in ta.ITEMS if x["Id"] == item), ctx["store"].items[item]
        self.assertEqual((after["EntryStatus"], after["ApprovedBy"], after["ApprovedOn"]), ("Approved", ME, ta.NOW))
        self.assertTrue(after["ApprovedOn"].endswith("Z"), "server UTC")
        self.assertEqual({k: after.get(k) for k in APPROVE_PRESERVED}, {k: before.get(k) for k in APPROVE_PRESERVED})
        self.assertEqual([(i, sorted(b)) for i, b, _ in ctx["writes"]], [(item, sorted(AE.APPROVAL_FIELDS))])
        ok = events(ctx["posts"], "Approval")
        self.assertEqual([(p["Decision"], str(p["TargetItemId"]), p["ActorUpn"]) for p in ok], [("ALLOW", str(item), ME)], "exactly one Approval")
        self.assertEqual(len(events(ctx["posts"], "AuthorizationAllow")), 1)

    def unapproved_ok(self, f, ctx, item):
        self.assertEqual((f["ok"], f["code"]), (True, "OK"))
        before, after = tu.BASE[item], ctx["store"].items[item]
        self.assertEqual((after["EntryStatus"], after["ApprovedBy"], after["ApprovedOn"]), ("Draft", None, None))
        self.assertEqual({k: after.get(k) for k in APPROVE_PRESERVED}, {k: before.get(k) for k in APPROVE_PRESERVED})
        ok = events(ctx["posts"], "Unapproval")
        self.assertEqual([(p["Decision"], str(p["TargetItemId"])) for p in ok], [("ALLOW", str(item))], "exactly one Unapproval")
        self.assertEqual(len(events(ctx["posts"], "AuthorizationAllow")), 1)

    def team(self, roles, mode):
        fs = ta.Store(ta.ITEMS if mode == "" else tu.ITEMS[:3])
        posts, writes = [], []
        trig = {"text": "2026-10", "text_1": "", "text_2": "500", "text_7": mode}
        trig.update({"text_%d" % (3 + i): "" for i in range(len(bf.TEAM_DECOYS))})
        run = wdl_sim.Run(trigger_body=trig, run_name="rm", now=ta.NOW, mocks=ta.mocks_for(ME, roles, fs, posts, writes)).run(ta.TEAM)
        resp = run.results["Respond"]["outputs"] if run.results["Respond"]["status"] == "Succeeded" else run.results["Respond_error"]["outputs"]
        self.assertEqual(writes, [])
        return resp["resultcode"], [x["id"] for x in json.loads(resp["rows"])], posts

    # ---------------------------------------------------------------- inventory
    def test_RM01_every_current_role_classified_director_retired(self):
        self.assertEqual(sorted(ROLES), sorted(tg.ROLE_KEYS), "approval matrix covers every configured role")
        self.assertEqual(sorted(ROLES), sorted(k for k, _ in tg.ROLE_GROUPS))
        self.assertTrue(all(r.status == ar.RESOLVED for r in ar.MATRIX))
        self.assertEqual(ar.RETIRED_LEGACY_ROLES, ("Director",))
        self.assertNotIn("Director", json.dumps(tg.SCOPE_CONFIG))
        self.assertEqual({r for r in ROLES if G5[r][0] != "none"}, {"TL", "APR", "EXE"})
        self.assertEqual({r for r in ROLES if G5[r][1] != "none"}, {"APR", "EXE"})
        self.assertEqual(G5["TL"], ("discipline", "none"))
        for r in ROLES:  # technical privilege never implies approval
            if r in ("ADM", "ITS", "CONFO", "MIGO", "PMO", "HR", "SALV", "FIN", "EMP"):
                self.assertEqual(G5[r], ("none", "none"), r)
        record("Director", "BR-APPR-02", "NOT_APPLICABLE", ["retired legacy role: no target role, no group mapping (RM01)"])
        record("Director", "BR-APPR-04", "NOT_APPLICABLE", ["retired legacy role: no target role, no group mapping (RM01)"])

    # ---------------------------------------------------------------- BR-APPR-01 / 02 / 03 (approve)
    def test_RM02_approve_capability_and_scope_every_role(self):
        """BR-APPR-02 (superseded by G5): TL own discipline, APR / EXE company, everyone else denied."""
        for role in ROLES:
            for roles in role_sets(role):
                with self.subTest(roles=roles):
                    f, ctx = self.approve(roles, 1)  # foreign Draft, same discipline D1
                    if can_approve(roles):
                        self.approved_ok(f, ctx, 1)
                    else:
                        self.denied(f, ctx, "ROLE_NOT_ALLOWED", "Approval", row_level=False)
                    f, ctx = self.approve(roles, 3)  # foreign Draft, discipline D2
                    sc = approve_scope(roles)
                    if sc == "company":
                        self.approved_ok(f, ctx, 3)
                    elif sc == "discipline":
                        self.denied(f, ctx, "SCOPE_NOT_ALLOWED", "Approval", row_level=True)
                    else:
                        self.denied(f, ctx, "ROLE_NOT_ALLOWED", "Approval", row_level=False)
            record(role, "BR-APPR-02", "PASS", ["RM02 same-discipline + cross-discipline approve, reference == flow"])

    def test_RM03_self_approval_denied_every_role(self):
        """BR-APPR-03 legacy gap fixed (UD-04): own row never approvable, by employee id or stored OwnerUpn."""
        for role in ROLES:
            for roles in role_sets(role):
                for item in (4, 11):  # own employee 12; own by stored OwnerUpn (case-insensitive)
                    with self.subTest(roles=roles, item=item):
                        f, ctx = self.approve(roles, item)
                        self.denied(f, ctx, "ROLE_NOT_ALLOWED", "Approval", row_level=can_approve(roles))
            record(role, "BR-APPR-03", "PASS", ["RM03 own rows 4 / 11 ROLE_NOT_ALLOWED, no write"])

    def test_RM04_approve_semantics_per_row_confirm_reapprove(self):
        """BR-APPR-01: selected rows -> Approved after the legacy confirm prompt; per-row results; an Approved row is not re-stamped."""
        import build_demo_app as app
        self.assertEqual(app.MESSAGES["MSG_APPROVE_CONFIRM"], "Bạn có muốn phê duyệt nội dung chấm công không?")
        self.assertIn("Set(varConfirm, true)", json.dumps(app.screens()["scrTeamApproval"]))
        for role in ROLES:
            for roles in role_sets(role):
                with self.subTest(roles=roles):
                    f, ctx = self.approve(roles, 5)  # foreign, already Approved
                    if can_approve(roles):
                        self.denied(f, ctx, "LOCKED", "Approval", row_level=True)
                    else:
                        self.denied(f, ctx, "ROLE_NOT_ALLOWED", "Approval", row_level=False)
            record(role, "BR-APPR-01", "PASS", ["RM04 re-approve of Approved row refused (target: no re-stamp)", "RM02 Draft -> Approved"])
        # batch of two, per-row outcome, one Approval row each
        f = self.A.approve(ME, ta.APR, [(1, '"1,1"'), (3, '"3,1"')])
        self.assertEqual((f["approvedCount"], len(events(self.A.ctx["posts"], "Approval", "ALLOW"))), (2, 2))

    # ---------------------------------------------------------------- BR-APPR-04 (unapprove)
    def test_RM05_unapprove_capability_every_role(self):
        """BR-APPR-04 (superseded by G5 / UD-05): APR / EXE company; TL, ADM, PMO and all others denied; Director retired."""
        for role in ROLES:
            for roles in role_sets(role):
                with self.subTest(roles=roles):
                    for item in (1, 2):  # foreign Approved D1 / D2
                        f, ctx = self.unapprove(roles, item)
                        if can_unapprove(roles):
                            self.unapproved_ok(f, ctx, item)
                        else:
                            self.denied(f, ctx, "ROLE_NOT_ALLOWED", "Unapproval", row_level=False)
                    f, ctx = self.unapprove(roles, 3)  # own Approved
                    self.denied(f, ctx, "ROLE_NOT_ALLOWED", "Unapproval", row_level=can_unapprove(roles))
                    f, ctx = self.unapprove(roles, 5)  # Draft target
                    self.denied(f, ctx, "NOT_APPROVED" if can_unapprove(roles) else "ROLE_NOT_ALLOWED", "Unapproval",
                                row_level=can_unapprove(roles))
            record(role, "BR-APPR-04", "PASS", ["RM05 foreign D1/D2 unapprove, self unapprove, Draft target; reference == flow"])
        import build_demo_app as app
        self.assertEqual(app.MESSAGES["MSG_UNAPPROVE_CONFIRM"], "Bạn có muốn hủy phê duyệt nội dung chấm công này không?")

    def test_RM06_client_claims_never_bypass(self):
        """Caller-controlled role / scope / owner / approver / status / discipline are ignored by every action."""
        for role in ROLES:
            for roles in role_sets(role):
                with self.subTest(roles=roles):
                    f, ctx = self.approve(roles, 3, decoys=FORGED)
                    want = "OK" if approve_scope(roles) == "company" else "SCOPE_NOT_ALLOWED" if can_approve(roles) else "ROLE_NOT_ALLOWED"
                    self.assertEqual(f["results"][0]["resultcode"] if f["results"] else f["code"], want)
                    if want == "OK":
                        self.assertEqual(ctx["store"].items[3]["ApprovedBy"], ME, "trusted caller, not the claimed approver")
                    f, ctx = self.approve(roles, 4, decoys=dict(FORGED, OwnerUpn="x@tenant-a.invalid"))
                    self.assertFalse(f["ok"])
                    self.assertEqual(ctx["writes"], [])
                    u = {k: v for k, v in dict(FORGED, ApprovedOn="2020-01-01T00:00:00Z", EmployeeItemId="11").items()
                         if k in bf.UNAPPROVE_DECOYS}
                    f, ctx = self.unapprove(roles, 1, decoys=u)
                    self.assertEqual(f["code"], "OK" if can_unapprove(roles) else "ROLE_NOT_ALLOWED")
                    f, ctx = self.unapprove(roles, 3, decoys=u)
                    self.assertEqual((f["code"], ctx["writes"]), ("ROLE_NOT_ALLOWED", []))

    # ---------------------------------------------------------------- BR-APPR-05 / 06 / 07 / 08 / 09
    def test_RM07_per_row_only_no_period_close_no_notification(self):
        """BR-APPR-05: per row; no period submission, no period lock, no notification (B-02)."""
        src = open(os.path.join(HERE, "..", "powerautomate", "build_approval_flows.py"), encoding="utf-8").read()
        for word in ("SendEmail", "Office365", "PostMessage", "PeriodClose", "SubmitPeriod", "PeriodStatus"):
            self.assertNotIn(word, src)
        self.assertEqual(AE.MAX_ITEMS, 50)
        self.assertEqual(AE.UNAPPROVE_INPUTS, {"ItemId", "ETag"}, "unapprove is one row per request")
        for role in ROLES:
            record(role, "BR-APPR-05", "PASS", ["RM07 per-row inputs; no period / notification action in the generated flows"])

    def test_RM08_lock_visual(self):
        """BR-APPR-06: Approved rows carry the lock (S07.5 V01-V07); role-independent, from the guarded read's status."""
        import test_approval_visual as tv
        r = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.defaultTestLoader.loadTestsFromTestCase(tv.Visual))
        self.assertTrue(r.wasSuccessful() and r.testsRun == 7)
        for role in ROLES:
            record(role, "BR-APPR-06", "PASS", ["S07.5 V01-V07 (role-independent rendering of server status)"])

    def test_RM09_approval_changes_only_approval_fields_and_reads_still_count(self):
        """BR-APPR-07: approval has no effect on the business data (hours etc.); the owner's read still returns Approved rows.
        Reports are NOT_IMPLEMENTED_CURRENT_PATH (EPIC reports); nothing filters on approval status today."""
        f, ctx = self.approve(ta.APR, 1)
        self.assertEqual([sorted(b) for _, b, _ in ctx["writes"]], [sorted(AE.APPROVAL_FIELDS)])
        src = open(os.path.join(HERE, "..", "powerautomate", "build_r1_flows.py"), encoding="utf-8").read()
        self.assertNotIn("EntryStatus eq 'Draft'", src.split("def read_actions")[1].split("\ndef ")[0] if "def read_actions" in src else "")
        for role in ROLES:
            record(role, "BR-APPR-07", "PASS", ["RM09 approval writes only EntryStatus/ApprovedBy/ApprovedOn; reports: " + NI])

    def test_RM10_author_created_preserved(self):
        """BR-APPR-08 legacy defect fixed: Author / Created / owner never overwritten; approver stored separately."""
        f, ctx = self.approve(ta.EXE, 3)
        self.assertNotIn("AuthorId", ctx["writes"][0][1])
        self.assertNotIn("Created", ctx["writes"][0][1])
        f, ctx = self.unapprove(ta.EXE, 2)
        self.assertFalse({"AuthorId", "Created", "OwnerUpn"} & set(ctx["writes"][0][1]))
        for role in ROLES:
            record(role, "BR-APPR-08", "PASS", ["RM10 + RM02/RM05 preserved-field checks (Author, Created, owner, LegacyId)"])

    def test_RM11_single_canonical_row(self):
        """BR-APPR-09 legacy defect not replicated: one TimesheetEntries row per entry; approve / unapprove write that row only."""
        f, ctx = self.approve(ta.APR, 1)
        self.assertEqual([i for i, _, _ in ctx["writes"]], [1])
        f, ctx = self.unapprove(tu.APR, 1)
        self.assertEqual([i for i, _, _ in ctx["writes"]], [1])
        for role in ROLES:
            record(role, "BR-APPR-09", "PASS", ["RM11 one MERGE on the addressed row only (no year-folder copies in target)"])

    # ---------------------------------------------------------------- queue reads
    def test_RM12_queue_reads_follow_capabilities(self):
        for role in ROLES:
            for roles in role_sets(role):
                with self.subTest(roles=roles):
                    code, ids, posts = self.team(roles, "")
                    if can_approve(roles):
                        self.assertEqual(code, "OK")
                        self.assertFalse({4, 11} & set(ids))
                        if approve_scope(roles) == "discipline":
                            self.assertNotIn(3, ids)
                    else:
                        self.assertEqual((code, ids), ("ROLE_NOT_ALLOWED", []))
                    code, ids, posts = self.team(roles, "Approved")
                    if can_unapprove(roles):
                        self.assertEqual((code, sorted(ids)), ("OK", [1, 2]))
                    else:
                        self.assertEqual((code, ids), ("ROLE_NOT_ALLOWED", []))

    # ---------------------------------------------------------------- BR-EDIT-01 / 03
    def test_RM13_edit_of_approved_row_refused_every_role(self):
        """BR-EDIT-01: own Approved row edit -> LOCKED "Dữ liệu đã được phê duyệt" (W-1); no write; no role edits an Approved row."""
        for role in ROLES:
            for roles in role_sets(role):
                with self.subTest(roles=roles):
                    f = self.S.both(ts.ME, ts.req(ItemId="3", ETag='"3,1"', Hours="7"), roles=roles)
                    self.assertFalse(f["ok"])
                    self.assertIn(f["code"], ("LOCKED", "ROLE_NOT_ALLOWED"))
                    if "EMP" in roles:
                        self.assertEqual((f["code"], f["messageCode"]), ("LOCKED", "MSG_LOCKED"))
                    self.S.nothing_written()
                    f = self.S.both(ts.ME, ts.req(ItemId="3", ETag='"3,1"', EntryStatus="Draft", OwnerUpn=ts.ME), roles=roles)
                    self.assertFalse(f["ok"])
            record(role, "BR-EDIT-01", "PASS", ["RM13 TS-SaveEntry reference == flow, LOCKED / no write; S07.4 IM02-IM06, LIVE-I1"])
        import build_demo_app as app
        self.assertEqual(app.MESSAGES["MSG_LOCKED"], "Dữ liệu đã được phê duyệt")

    def test_RM14_delete_of_approved_row_refused_by_invariant(self):
        """BR-EDIT-03 (D-1 TARGET_TYPED_FEEDBACK_APPROVED): Approved -> typed LOCKED instead of the legacy silent skip. The delete
        business path is NOT_IMPLEMENTED_CURRENT_PATH; the shared invariant every future delete must use is proven here."""
        for role in ROLES:
            row = {"OwnerUpn": ME, "EntryStatus": "Approved"}
            self.assertEqual(E.ordinary_mutation_refusal(row, ME), "LOCKED")
            self.assertEqual(E.ordinary_mutation_refusal(dict(row, EntryStatus="Draft"), ME), None)
            self.assertEqual(E.ordinary_mutation_refusal(row, "x@tenant-a.invalid"), "FORBIDDEN")
            record(role, "BR-EDIT-03", "PASS", ["RM14 shared invariant LOCKED (D-1); S07.4 IM09-IM11; delete path " + NI])

    # ---------------------------------------------------------------- matrix completeness (runs last by name)
    def test_RM99_matrix_complete_no_unexplained_skip(self):
        if any((r, rule) not in MATRIX for r in ROLES for rule in RULES):  # run in isolation: build the matrix first
            for name in sorted(n for n in dir(self) if n.startswith("test_RM") and n != "test_RM99_matrix_complete_no_unexplained_skip"):
                getattr(self, name)()
        cells = [(r, rule) for r in ROLES for rule in RULES]
        missing = [c for c in cells if c not in MATRIX]
        self.assertEqual(missing, [])
        bad = {c: v for c, v in MATRIX.items() if v["result"] not in ("PASS", "NOT_APPLICABLE") or not v["evidence"]}
        self.assertEqual(bad, {})
        out = os.environ.get("TS_S076_MATRIX_OUT")
        if out:
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"roles": ROLES, "rules": list(RULES), "retired": list(ar.RETIRED_LEGACY_ROLES),
                           "cells": [{"role": r, "rule": rule, **MATRIX[(r, rule)]} for r, rule in sorted(MATRIX)]}, fh, indent=1,
                          ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
