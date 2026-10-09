"""S07.5 approval visual state and Home pending count, tests V01-V22 (offline; synthetic data only).

The visual state is driven only by the `status` returned by the guarded reads (TS-ReadOwn / TS-ReadTeam). The Home count is
the guarded TS-ReadTeam Pending read itself (reference `approve_entries.read_team` vs the generated flow in the WDL simulator,
through the S07.2 `Team` harness), so it has exactly the queue's role, scope, self-exclusion, Draft and period rules."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "approval"), os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"),
          os.path.join(HERE, "..", "timesheet")):
    sys.path.insert(0, p)
import approve_entries as AE  # noqa: E402
import build_demo_app as app  # noqa: E402
import business_dates as bd  # noqa: E402
import test_approve_flow as ta  # noqa: E402
import test_unapprove_flow as tu  # noqa: E402
from test_r1_save_flow import sp_query  # noqa: E402

SCR = app.screens()


def kids(screen):
    return {k: v for x in SCR[screen]["Children"] for k, v in x.items()}


def gal(screen, name):
    g = kids(screen)[name]
    return g, {k: v for x in g["Children"] for k, v in x.items()}


def prop(c, k):
    return c["Properties"][k].lstrip("=")


ME, TL, APR, EXE = ta.ME, ta.TL, ta.APR, ta.EXE


class Visual(unittest.TestCase):
    def test_V01_draft_row_has_draft_visual_state(self):
        for screen, g, ico in (("scrMyTimesheets", "galEntries", "icoLock"), ("scrTeamApproval", "galTeam", "icoTeamLock")):
            gg, c = gal(screen, g)
            self.assertEqual(prop(c[ico], "Visible"), 'ThisItem.status = "Approved"', "Draft rows show no lock (legacy parity)")
            self.assertIn("RGBA(0, 0, 0, 0)", prop(gg, "TemplateFill"), "Draft rows keep the normal (transparent) fill")
        _, c = gal("scrMyTimesheets", "galEntries")
        self.assertIn("ThisItem.status", prop(c["lblLine1"], "Text"), "the authoritative status text stays on every row")

    def test_V02_approved_row_has_lock_visual(self):
        for screen, g, ico in (("scrMyTimesheets", "galEntries", "icoLock"), ("scrTeamApproval", "galTeam", "icoTeamLock")):
            _, c = gal(screen, g)
            self.assertEqual((c[ico]["Control"], prop(c[ico], "Icon")), ("Classic/Icon@2.5.0", "Icon.Lock"))
            self.assertEqual(prop(c[ico], "AccessibleLabel"), '"Đã phê duyệt"')

    def test_V03_draft_and_approved_distinguishable(self):
        fill = app.LOCK_FILL
        self.assertRegex(fill, r'^If\(ThisItem\.status = "Approved", RGBA\(242, 242, 242, 1\), RGBA\(0, 0, 0, 0\)\)$')
        for screen, g in (("scrMyTimesheets", "galEntries"), ("scrTeamApproval", "galTeam")):
            self.assertEqual(prop(gal(screen, g)[0], "TemplateFill"), fill)
        # distinction never relies on a client flag: only ThisItem.status from the guarded read
        self.assertNotRegex(app.LOCK_FILL + json.dumps(SCR), r"(?i)isApproved|varLocked")

    def test_V04_own_approved_row_has_no_edit_affordance(self):
        _, c = gal("scrMyTimesheets", "galEntries")
        self.assertEqual(prop(c["btnEdit"], "Visible"), 'ThisItem.status = "Draft"')

    def test_V05_own_draft_edit_unchanged(self):
        _, c = gal("scrMyTimesheets", "galEntries")
        self.assertEqual(prop(c["btnEdit"], "OnSelect"), "Set(varEdit, ThisItem); Navigate(scrEntry, ScreenTransition.None)")
        self.assertIn("status: Text(ThisRecord.Value.status)", app.READ, "status comes from TS-ReadOwn")

    def test_V06_pending_team_row_visual(self):
        _, c = gal("scrTeamApproval", "galTeam")
        self.assertEqual(prop(c["btnSel"], "Visible"), 'varTeamMode <> "Approved"', "multi-select stays in Pending mode")
        self.assertEqual(prop(c["icoTeamLock"], "Visible"), 'ThisItem.status = "Approved"')
        self.assertIn("ThisItem.status", prop(c["lblTeam2"], "Text"))

    def test_V07_approved_team_row_visual(self):
        _, c = gal("scrTeamApproval", "galTeam")
        self.assertEqual(prop(c["btnUnapprove"], "Visible"), 'varTeamMode = "Approved" && ThisItem.status = "Approved"')
        ico, sel = c["icoTeamLock"]["Properties"], c["btnSel"]["Properties"]
        x_sel_end = int(sel["X"].lstrip("=")) + int(sel["Width"].lstrip("="))
        self.assertLess(int(ico["X"].lstrip("=")) + int(ico["Width"].lstrip("=")), int(prop(c["lblTeam1"], "X")))
        self.assertLessEqual(x_sel_end, int(prop(c["lblTeam1"], "X")))
        self.assertIn('" by " & ThisItem.approvedBy', prop(c["lblTeam2"], "Text"))
        self.assertNotIn("colSel", prop(c["btnUnapprove"], "OnSelect"), "no batch unapprove")


class Count(unittest.TestCase):
    """Home count = number of rows of the guarded TS-ReadTeam Pending read (Mode empty), reference == generated flow."""
    maxDiff = None
    team = ta.Team.team  # reference vs flow harness (asserts equality), synthetic store

    def count(self, upn, roles, items=ta.ITEMS):
        f = self.team(upn, roles, size=str(app.PENDING_PAGE), items=items)
        return f, (len(f["rows"]) if f["ok"] else None)

    def test_V08_hidden_for_employee(self):
        f, n = self.count(ME, ("EMP",))
        self.assertEqual((f["code"], n), ("ROLE_NOT_ALLOWED", None))
        s = app.PENDING_COUNT
        self.assertIn('If(varPend.resultcode = "ROLE_NOT_ALLOWED", Set(varNoTeam, true))', s)
        lbl = kids("scrMyTimesheets")["lblPending"]
        self.assertEqual(prop(lbl, "Visible"), "!varNoTeam && !IsBlank(varPendingCount)")
        self.assertNotIn("Notify(", s, "silent: no error banner for roles without approval")

    def test_V09_team_leader_count(self):
        f, n = self.count(ME, TL)
        self.assertEqual(n, 6)
        self.assertEqual(sorted(x["id"] for x in f["rows"]), [1, 2, 7, 8, 10, 12])

    def test_V10_team_leader_excludes_cross_discipline(self):
        f, _ = self.count(ME, TL)
        self.assertNotIn(3, [x["id"] for x in f["rows"]])  # item 3 = discipline D2
        self.assertIn("DisciplineCode eq 'D1'", self.ctx["run"].results["Filter"]["outputs"])

    def test_V11_team_leader_excludes_self(self):
        f, _ = self.count(ME, TL)
        self.assertFalse({4, 11} & {x["id"] for x in f["rows"]})  # own by employee / by stored OwnerUpn

    def test_V12_approver_company_scope(self):
        f, n = self.count(ME, APR)
        self.assertEqual((n, sorted(x["id"] for x in f["rows"])), (7, [1, 2, 3, 7, 8, 10, 12]))
        self.assertNotIn("DisciplineCode eq", self.ctx["run"].results["Filter"]["outputs"])

    def test_V13_approver_excludes_self(self):
        f, _ = self.count(ME, APR)
        self.assertFalse({4, 11} & {x["id"] for x in f["rows"]})

    def test_V14_executive_company_scope(self):
        f, n = self.count(ME, EXE)
        self.assertEqual(n, 7)
        self.assertFalse({4, 11} & {x["id"] for x in f["rows"]})

    def test_V15_roles_without_approve_get_no_count(self):
        for roles in (("ADM",), ("PMO",), ("HR",), ("SALV",), ("FIN",), ("ITS",), ("CONFO",), ("MIGO",), ()):
            f, n = self.count(ME, roles)
            self.assertEqual((f["ok"], f["code"], n), (False, "ROLE_NOT_ALLOWED", None), roles)

    def _ref(self, store, upn, roles):
        def query(flt, top):
            return [(r["Id"], dict(r, OwnerName=(r["Employee"] or {}).get("Title"), OwnerCode=(r["Employee"] or {}).get("LegacyId")),
                     r["odata.etag"]) for r in sp_query("x?$filter=%s&$top=%d" % (flt, top), store.rows())]
        r = AE.read_team(ta.guard(upn, roles, "c"), ta.caller_disc(upn), {"PeriodKey": "2026-10", "PageSize": str(app.PENDING_PAGE)}, query,
                         correlation_id="c", business_date=lambda v: bd.business_date(v, ta.TZ))
        return len(r["rows"])

    def test_V16_approve_refreshes_count_down(self):
        store = ta.Store(ta.ITEMS)
        before = self._ref(store, ME, TL)
        r = AE.approve_entries(ta.guard(ME, TL, "a"), ta.caller_disc(ME), {"Items": json.dumps([{"itemId": 1, "etag": store.etag(1)}])},
                               store, ta.owner_lookup(), correlation_id="a", approved_on=ta.NOW)
        self.assertEqual((r.ok, r.code), (True, "OK"))
        self.assertEqual(self._ref(store, ME, TL), before - 1)
        a = app.APPROVE_ONSELECT
        self.assertIn("If(Value(varAppr.approvedcount) > 0, Set(varPendingCount, Blank()))", a)
        self.assertIn(app.PENDING_COUNT.strip(), app.LIST_ONVISIBLE, "Home re-reads the count on every visit")

    def test_V17_unapprove_refreshes_count_up(self):
        store = ta.Store(tu.ITEMS)
        guard_u = lambda: tu.guard(ME, APR, "u")  # noqa: E731
        before = self._ref(store, ME, APR)
        r = AE.unapprove_entry(guard_u(), {"ItemId": "1", "ETag": store.etag(1)}, store, ta.owner_lookup(), correlation_id="u")
        self.assertEqual(r["code"], "OK")
        self.assertEqual(self._ref(store, ME, APR), before + 1)
        self.assertIn('If(varUn.resultcode = "OK", Set(varPendingCount, Blank()))', app.UNAPPROVE_ONSELECT)

    def test_V18_readteam_pending_contract_unchanged(self):
        s = app.PENDING_COUNT
        call = re.search(r"'TS-ReadTeam'\.Run\((.*)\)\);", s).group(1)
        self.assertEqual(call, 'Text(Coalesce(varTo, Today()), "yyyy-mm"), "", "500", {text_7: ""}')
        self.assertEqual(app.PENDING_PAGE, AE.MAX_PAGE, "one bounded page; never above the server cap")
        self.assertIn('If(varPendingMore, "500+"', prop(kids("scrMyTimesheets")["lblPending"], "Text"))
        self.assertIn('{text_7: If(varTeamMode = "Approved", "Approved", "")}', app.TEAM_READ, "queue call unchanged")

    def test_V19_readteam_approved_mode_unchanged(self):
        import build_approval_flows as bf
        self.assertEqual(bf.TEAM_MODES, ("", "pending", "approved"))
        f = self.team(ME, APR, size="500")  # Pending: Draft only
        self.assertTrue(f["rows"] and all(x["status"] == "Draft" for x in f["rows"]))
        store = ta.Store([tu.approved(1, 11), tu.approved(2, 13), tu.approved(3, 12), ta.entry(5, 11)])  # 3 = own

        def query(flt, top):
            return [(r["Id"], dict(r, OwnerName="n", OwnerCode="c"), r["odata.etag"]) for r in sp_query("x?$filter=%s&$top=%d" % (flt, top), store.rows())]
        r = AE.read_team(tu.guard(ME, APR, "m"), ta.caller_disc(ME), {"PeriodKey": "2026-10", "Mode": "Approved"}, query, correlation_id="m",
                         business_date=lambda v: bd.business_date(v, ta.TZ))
        self.assertEqual(sorted(x["id"] for x in r["rows"]), [1, 2])  # S07.3 review: Approved only, own 3 excluded
        self.assertNotIn('"Approved"', app.PENDING_COUNT, "the count never asks for Approved rows")

    def test_V20_no_direct_timesheetentries_datasource(self):
        text = json.dumps(SCR, ensure_ascii=False) + app.APP_ONSTART
        for lst in app.PROTECTED_LISTS:
            self.assertNotRegex(text, r"\b%s\b" % lst, lst)
        self.assertNotRegex(app.PENDING_COUNT, r"CountRows\((colRows|Filter)", "no client-side count of entries")

    def test_V21_confirm_controls_not_overlapped(self):
        c = kids("scrTeamApproval")
        y = lambda k, p="Y": int(prop(c[k], p))  # noqa: E731
        for b in ("btnConfirmYes", "btnConfirmNo", "btnUnYes", "btnUnNo"):
            self.assertLess(y(b) + y(b, "Height"), y("galTeam"), b)
        for b in ("btnModePending", "btnModeApproved", "btnTeamRefresh", "btnApprove"):
            self.assertLess(y(b) + 40, y("galTeam"), b)
        h = kids("scrMyTimesheets")
        hy = lambda k, p="Y": int(prop(h[k], p))  # noqa: E731
        self.assertLessEqual(hy("lblPending") + hy("lblPending", "Height"), hy("galEntries"), "Home count above the gallery")
        self.assertGreaterEqual(int(prop(h["lblPending"], "X")), int(prop(h["btnTeam"], "X")) + int(prop(h["btnTeam"], "Width")))

    def test_V22_new_controls_use_known_control_types(self):
        known = {"Label@2.5.1", "Classic/Button@2.2.0", "Gallery@2.15.0", "Timer@2.1.0", "Classic/DatePicker@2.6.0",
                 "Classic/DropDown@2.3.1", "Classic/TextInput@2.3.2", "Classic/Icon@2.5.0"}
        found = set(re.findall(r'"Control": "([^"]+)"', json.dumps(SCR)))
        self.assertLessEqual(found, known)
        # App Checker itself runs in Studio (live evidence); here: no Navigate in start OnVisible, no unknown variable in count
        for v in ("varPend", "varPendingCount", "varPendingMore", "varNoTeam", "varTo"):
            self.assertIn(v, app.PENDING_COUNT + prop(kids("scrMyTimesheets")["lblPending"], "Text") + app.APP_ONSTART)


if __name__ == "__main__":
    unittest.main(verbosity=2)
