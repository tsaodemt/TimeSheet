"""R3 M3 EPIC 17 Discipline Effort Canvas screen (generated Power Apps YAML): tests DC01-DC12 (offline)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "effort"), os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity")]
import build_demo_app as app  # noqa: E402
import build_discipline_flows as bf  # noqa: E402
import test_guard as tg  # noqa: E402

SCR = app.screens()
KW = dict(role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit",
          conf_audit_list="_ConfAudit", environment="STAGING")


def kids_of(scr):
    out = {}

    def walk(children):
        for x in children:
            for k, v in x.items():
                out[k] = v
                walk(v.get("Children", []))
    walk(scr["Children"])
    return out


def kids(screen):
    out = {}

    def walk(children):
        for x in children:
            for k, v in x.items():
                out[k] = v
                walk(v.get("Children", []))
    walk(SCR[screen]["Children"])
    return out


C = kids("scrDisciplineEffort")
P = lambda k, p: C[k]["Properties"][p].lstrip("=")  # noqa: E731
SRC = json.dumps(SCR["scrDisciplineEffort"], ensure_ascii=False)
ALL = SRC + app.DE_READ + app.DE_SAVE + app.DE_APPROVE


def resp_keys(actions):
    return set(actions["Respond"]["inputs"]["body"])


class DisciplineEffortCanvas(unittest.TestCase):
    def test_DC01_navigation_and_title(self):
        home = kids("scrMyTimesheets")
        self.assertIn("Navigate(scrDisciplineEffort", home["btnDe"]["Properties"]["OnSelect"])
        self.assertEqual(home["btnDe"]["Properties"]["Visible"], "=!varNoDe")
        self.assertEqual(P("lblDeTitle", "Text"), '"Công bộ môn"')
        for v in ("varNoDe", "varDePid", "varDeCanEdit", "varDeCanApprove", "varDeLeave", "varDeSwitch", "varDeConfirm"):
            self.assertIn("Set(%s," % v, app.APP_ONSTART)

    def test_DC02_requests_carry_no_identity_claims(self):
        self.assertIn("'EFF-ReadDisciplineEffort'.Run(Text(varDePid))", app.DE_READ)
        self.assertIn("'EFF-ApproveDisciplineEffort'.Run(JSON(ForAll(colDeSel As x, {itemId: x.id, etag: x.etag}), JSONFormat.Compact), GUID())", app.DE_APPROVE)
        for f in (app.DE_READ, app.DE_SAVE, app.DE_APPROVE):
            for call in re.findall(r"'EFF-\w+DisciplineEffort'\.Run\((.*?)\)\);", f, re.S):
                self.assertNotRegex(call, r"(?i)User\(\)|role|upn|ActorUpn|OwnerUpn|disc|employee|scope|status", call)

    def test_DC03_save_sends_changed_cells_only_and_rereads(self):
        s = app.DE_SAVE
        self.assertIn("'EFF-SaveDisciplineEffort'.Run(Text(varDePid), JSON(ForAll(%s As c, {workTypeId: c.k" % app.DE_DIRTY, s)
        self.assertIn('state: If(IsBlank(Trim(c.t)), "blank", "value")', s)
        self.assertTrue(s.rstrip().endswith(app.DE_READ.rstrip()), "re-read after every save")
        self.assertTrue(app.DE_APPROVE.rstrip().endswith(app.DE_READ.rstrip()), "re-read after every approval")
        self.assertIn('Filter(colDeRes, rc = "OK" || rc = "NO_CHANGE").k', s)

    def test_DC04_edit_only_own_draft_active_when_server_allows(self):
        self.assertEqual(P("btnDeSave", "Visible"), "varDeCanEdit")
        dm = P("txtDeVal", "DisplayMode")
        for part in ("varDeCanEdit", "ThisItem.active", 'ThisItem.status <> "ApprovedLocked"'):
            self.assertIn(part, dm)
        self.assertEqual(P("galDeMine", "Items"), "colDeMine")
        self.assertIn("mine && wt = w.id", app.DE_READ, "own rows only in the editable grid")
        self.assertIn("Filter(colDeRows, mine && !(wt in colDeWts.id))", app.DE_READ, "own rows of an inactive WorkType: shown read-only")
        self.assertEqual(P("icoDeLock", "Visible"), 'ThisItem.status = "ApprovedLocked"')
        self.assertIn("Boolean(ParseJSON(varDe.caller).canEdit)", app.DE_READ)

    def test_DC05_blank_and_zero_distinct_client_validation(self):
        self.assertNotIn("Value(", P("txtDeVal", "Default"))
        self.assertEqual(P("txtDeVal", "HintText"), '"—"')
        rx = re.search(r'IsMatch\(Trim\(e\.t\), "([^"]+)"\)', app.DE_INVALID).group(1)
        for v in ("0", "7", "12.5", "12,25", "100000"):
            self.assertTrue(re.fullmatch(rx, v), v)
        for v in ("-1", "1.234", "abc", "1e3"):
            self.assertFalse(re.fullmatch(rx, v), v)
        self.assertIn(app.DE_INVALID.split(" As e")[0], P("btnDeSave", "DisplayMode"))
        self.assertNotRegex(ALL, r"999|Max\(", "no business maximum (OD-47)")

    def test_DC06_approval_team_leader_own_discipline_confirm_no_reopen(self):
        self.assertEqual(P("btnDeApprove", "Visible"), "varDeCanApprove && !IsBlank(varDePid)")
        self.assertIn("CountRows(colDeSel) > 50", P("btnDeApprove", "DisplayMode"))
        self.assertIn("CountRows(%s) > 0" % app.DE_DIRTY, P("btnDeApprove", "DisplayMode"), "no approval over unsaved edits")
        self.assertEqual(P("btnDeApprove", "OnSelect"), "Set(varDeConfirm, true)", "confirmation first")
        self.assertEqual(P("btnDeConfirmYes", "OnSelect").strip(), app.DE_APPROVE.strip())
        self.assertEqual(P("btnDeSel", "Visible"), app.DE_SELECTABLE)
        for part in ('ThisItem.status = "Draft"', 'ThisItem.state = "VALUE"', "ThisItem.disc = varDeMyDisc", "varDeCanApprove"):
            self.assertIn(part, app.DE_SELECTABLE)
        self.assertNotIn("mine", app.DE_SELECTABLE, "own rows are approvable too (OD-28, EPIC 17 only)")
        self.assertNotRegex(ALL, r"(?i)unapprove|reopen|unlock|Hủy phê duyệt|mở lại phê")

    def test_DC07_no_protected_list_and_no_direct_write(self):
        for lst in ("DisciplineEffortRegistrations", "DisciplineEffortLocks", "ProjectEffortAllocations", "ProjectPmAssignments", "TimesheetEntries",
                    "Employees", "AppSettings"):
            self.assertIn(lst, app.PROTECTED_LISTS)
            self.assertNotRegex(ALL, r"\b%s\b" % lst)
        for verb in ("Patch(", "SubmitForm(", "Remove(", "RemoveIf(", "UpdateIf("):
            self.assertNotIn(verb, ALL)
        self.assertIn("SortByColumns(Projects,", P("ddDeProject", "Items"), "reference source only")

    def test_DC08_fields_match_flow_responses(self):
        for f, acts in ((app.DE_READ, bf.read_actions(**KW)), (app.DE_SAVE, bf.save_actions(**KW)), (app.DE_APPROVE, bf.approve_actions(**KW))):
            used = set(re.findall(r"\bvarDe(?:Save|Appr)?\.(\w+)", f))
            keys = resp_keys(bf.read_actions(**KW)) | resp_keys(acts)
            self.assertLessEqual(used, keys, used - keys)
        row_keys = set(re.findall(r"ThisRecord\.Value\.(\w+)", app.DE_READ + app.DE_SAVE + app.DE_APPROVE))
        self.assertLessEqual(row_keys, {"id", "employeeName", "disciplineCode", "workTypeId", "workTypeCode", "workTypeName", "state", "value", "status",
                                        "etag", "mine", "code", "name", "disciplineName", "ceilingState", "ceiling", "used", "remaining", "actualHours",
                                        "actualManDays", "resultcode", "itemId"})

    def test_DC09_totals_come_from_server(self):
        t = P("lblDeSumVals", "Text")
        for k in ("ThisItem.ceiling", "ThisItem.remaining", "ThisItem.used", "ThisItem.mds", "ThisItem.hours", '"Trần: chưa có"', "đã duyệt"):
            self.assertIn(k, t)
        self.assertNotRegex(ALL, r"\bSum\(", "no client-side total")

    def test_DC10_dirty_prompts(self):
        self.assertIn("Set(varDeLeave, true)", P("btnDeBack", "OnSelect"))
        self.assertIn("Set(varDeSwitch, true)", P("ddDeProject", "OnChange"))
        self.assertIn("Set(varDeSwitch, true)", P("btnDeReload", "OnSelect"))
        self.assertIn("Reset(ddDeProject)", P("btnDeLeaveNo", "OnSelect"))

    def test_DC11_messages_cover_result_codes(self):
        for k in ("DE_OK", "DE_REFUSED", "DE_INVALID", "DE_LEAVE", "DE_NO_ACCESS", "DE_APPROVE_CONFIRM", "DE_APPROVED", "DE_APPROVE_PARTIAL",
                  "DE_APPROVE_REFUSED"):
            self.assertIn(k, app.MESSAGES)
        for code in ("OVER_CEILING", "CEILING_NOT_REGISTERED", "VALIDATION_VALUE", "TECHNICAL_LIMIT", "NO_CHANGE", "LOCKED", "CONFLICT", "NOT_FOUND",
                     "SCOPE_NOT_ALLOWED", "VALIDATION_LOOKUP", "VALIDATION_REQUEST", "ROLE_NOT_ALLOWED", "ERROR"):
            self.assertIn("MSG_" + code, app.MESSAGES, code)
        for k, v in app.MESSAGES.items():
            if k.startswith("DE_") or k in ("MSG_OVER_CEILING", "MSG_CEILING_NOT_REGISTERED"):
                self.assertNotRegex(v, r"(?i)sharepoint|list|flow|http|stack|A\.I\.3")

    def test_DC13_studio_paste_accepts_the_properties(self):
        # live: Studio rejected the pasted screen ("something wrong with the pasted code") for AccessibleLabel on Classic/Button@2.2.0
        for scr in SCR.values():
            for k, v in kids_of(scr).items():
                if v.get("Control") == "Classic/Button@2.2.0":
                    self.assertNotIn("AccessibleLabel", v["Properties"], k)

    def test_DC12_geometry_and_chained_blocks(self):
        y = lambda k, p="Y": int(P(k, p))  # noqa: E731
        x = lambda k, p="X": int(P(k, p))  # noqa: E731
        self.assertLessEqual(y("btnDeLeaveYes") + y("btnDeLeaveYes", "Height"), y("lblDeMine"))
        self.assertLessEqual(y("lblDeMine") + y("lblDeMine", "Height"), y("galDeMine"))
        self.assertLessEqual(x("galDeMine") + x("galDeMine", "Width"), x("galDeSum"))
        self.assertLessEqual(y("galDeSum") + y("galDeSum", "Height"), y("lblDeTeam"))
        self.assertLessEqual(y("btnDeConfirmYes") + y("btnDeConfirmYes", "Height"), y("galDeTeam"))
        home = kids("scrMyTimesheets")
        hp = lambda k, p: int(home[k]["Properties"][p].lstrip("="))  # noqa: E731
        self.assertLessEqual(hp("btnDe", "X") + hp("btnDe", "Width"), hp("btnEff", "X"))
        self.assertLessEqual(hp("btnDe", "Y") + hp("btnDe", "Height"), hp("lblPending", "Y"))
        for name in ("DE_SAVE", "DE_APPROVE", "DE_ONVISIBLE", "DE_OPEN", "DE_READ"):
            self.assertIsNone(re.search(r"\)\s*\n\s*(Set|Notify|ClearCollect)\(", getattr(app, name)), name)
        for k, v in C.items():
            for prop, val in v.get("Properties", {}).items():
                self.assertIsNone(re.search(r"\)\s*\n\s*(Set|Notify|ClearCollect)\(", val), (k, prop))


if __name__ == "__main__":
    unittest.main(verbosity=2)
