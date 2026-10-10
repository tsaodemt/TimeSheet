"""R3 M2 EPIC 16 Project Effort Canvas screen (generated Power Apps YAML): tests PC01-PC12 (offline)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "effort")]
import build_demo_app as app  # noqa: E402
import project_effort as PE  # noqa: E402

SCR = app.screens()


def kids(screen):
    out = {}

    def walk(children):
        for x in children:
            for k, v in x.items():
                out[k] = v
                walk(v.get("Children", []))
    walk(SCR[screen]["Children"])
    return out


C = kids("scrProjectEffort")
P = lambda k, p: C[k]["Properties"][p].lstrip("=")  # noqa: E731
SRC = json.dumps(SCR["scrProjectEffort"], ensure_ascii=False)


class ProjectEffortCanvas(unittest.TestCase):
    def test_PC01_navigation_and_title(self):
        home = kids("scrMyTimesheets")
        self.assertIn("Navigate(scrProjectEffort", home["btnEff"]["Properties"]["OnSelect"])
        self.assertEqual(home["btnEff"]["Properties"]["Visible"], "=!varNoEff")
        self.assertEqual(P("lblEffTitle", "Text"), '"Công dự án"')

    def test_PC02_project_list_comes_from_the_guarded_flow(self):
        self.assertIn("'EFF-ReadProjectEffort'.Run(\"0\")", app.EFF_LIST)
        self.assertEqual(P("ddEffProject", "Items"), 'SortByColumns(colEffProjects, "code", SortOrder.Ascending)')
        self.assertNotRegex(SRC, r"\bProjects\b(?!\w)", "no direct Projects data source: the list is caller-scoped by the server")
        self.assertEqual(P("ddEffProject", "AllowEmptySelection"), "true")

    def test_PC03_requests_carry_no_identity_claims(self):
        for f, flow in ((app.EFF_READ, "EFF-ReadProjectEffort"), (app.EFF_SAVE, "EFF-SaveProjectEffort"), (app.EFF_SETPM, "EFF-SetProjectPm")):
            for call in re.findall(r"'%s'\.Run\((.*?)\)\);" % flow, f, re.S):
                self.assertNotRegex(call, r"(?i)User\(\)|role|upn|ActorUpn|OwnerUpn", flow)
        self.assertIn("'EFF-SetProjectPm'.Run(Text(varEffPid), Text(ddEffPm.Selected.id), varEff.pmetag)", app.EFF_SETPM)

    def test_PC04_save_sends_changed_recipients_only(self):
        s = app.EFF_SAVE
        self.assertIn("'EFF-SaveProjectEffort'.Run(Text(varEffPid), JSON(ForAll(%s As c" % app.EFF_DIRTY, s)
        self.assertIn('state: If(IsBlank(Trim(c.t)), "blank", "value")', s)
        self.assertIn("JSONFormat.Compact), GUID())", s)
        self.assertTrue(s.rstrip().endswith(app.EFF_READ.rstrip()), "re-read after every save")
        self.assertIn('Filter(colEffRes, rc = "OK" || rc = "NO_CHANGE").k', s)

    def test_PC05_read_only_unless_server_says_canedit(self):
        self.assertEqual(P("btnEffSave", "Visible"), "varEffCanEdit")
        self.assertIn("varEffCanEdit", P("txtEffVal", "DisplayMode"))
        self.assertIn('varEff.canedit = "true"', app.EFF_READ)
        self.assertEqual(P("ddEffPm", "Visible"), "varEffCanAssign && !IsBlank(varEffPid)")
        self.assertIn('varEff.canassignpm = "true"', app.EFF_READ)

    def test_PC06_blank_and_zero_distinct(self):
        d = P("txtEffVal", "Default")
        self.assertIn("ThisItem.value", d)
        self.assertNotIn("Value(", d)
        self.assertEqual(P("txtEffVal", "HintText"), '"—"')
        self.assertIn('ThisItem.state = "BLANK", "chưa đăng ký"', P("lblEffState", "Text"))

    def test_PC07_client_validation_matches_server(self):
        rx = re.search(r'IsMatch\(Trim\(e\.t\), "([^"]+)"\)', app.EFF_INVALID).group(1)
        for v in ("0", "7", "12.5", "12,25", "999999.99"):
            self.assertTrue(re.fullmatch(rx, v), v)
            self.assertIsNone(PE.value_code(v.replace(",", ".")), v)
        for v in ("-1", "1.234", "abc", "1e3"):
            self.assertFalse(re.fullmatch(rx, v), v)
            self.assertIsNotNone(PE.value_code(v), v)
        self.assertIn(app.EFF_INVALID.split(" As e")[0], P("btnEffSave", "DisplayMode"))

    def test_PC08_dirty_prompts(self):
        self.assertIn("Set(varEffLeave, true)", P("btnEffBack", "OnSelect"))
        self.assertIn("Set(varEffSwitch, true)", P("ddEffProject", "OnChange"))
        self.assertIn("Set(varEffSwitch, true)", P("btnEffReload", "OnSelect"))
        self.assertIn("Reset(ddEffProject)", P("btnEffLeaveNo", "OnSelect"))
        self.assertIn("CountRows(%s) > 0" % app.EFF_DIRTY, P("btnEffSetPm", "DisplayMode"), "no PM change over unsaved edits")

    def test_PC09_no_protected_list_and_no_direct_write(self):
        for lst in ("ProjectPmAssignments", "ProjectEffortAllocations", "TimesheetEntries"):
            self.assertIn(lst, app.PROTECTED_LISTS) if lst != "TimesheetEntries" else None
            self.assertNotRegex(SRC, r"\b%s\b" % lst)
        for verb in ("Patch(", "SubmitForm(", "Remove(", "RemoveIf(", "UpdateIf("):
            self.assertNotIn(verb, SRC)

    def test_PC10_no_business_maximum_no_approval_no_eval(self):
        for bad in ("999.9", "9999", "Max(", "Phê duyệt", "Approve", "Lock", "Khóa", "KPI", "Lương", "Salary"):
            self.assertNotIn(bad, SRC, bad)

    def test_PC11_totals_and_comparison_from_server(self):
        self.assertIn("varEff.plannedtotal", P("lblEffPlanned", "Text"))
        self.assertIn("varEff.actualmandays", P("lblEffActual", "Text"))
        self.assertIn("varEff.variance", P("lblEffVar", "Text"))
        self.assertIn("đã duyệt", P("lblEffActual", "Text"))
        self.assertNotRegex(SRC, r"Sum\(", "no client-side total: the server computes the facts")

    def test_PC13_chained_blocks_are_separated(self):
        # a statement block that ends with ")" followed by a new Set( needs ";" (live App checker: 4 errors on btnEffSetPm)
        for name in ("EFF_SAVE", "EFF_SETPM", "EFF_ONVISIBLE", "EFF_OPEN"):
            f = getattr(app, name)
            self.assertIsNone(re.search(r"\)\s*\n\s*(Set|Notify|ClearCollect)\(", f), name)
        for k, v in C.items():
            for prop, val in v.get("Properties", {}).items():
                self.assertIsNone(re.search(r"\)\s*\n\s*(Set|Notify|ClearCollect)\(", val), (k, prop))

    def test_PC12_geometry_no_overlap_and_messages(self):
        y = lambda k, p="Y": int(P(k, p))  # noqa: E731
        self.assertLess(y("btnEffLeaveYes") + y("btnEffLeaveYes", "Height"), y("galEffRows"))
        self.assertLess(y("btnEffSetPm") + y("btnEffSetPm", "Height"), y("lblEffInfo") + 1)
        self.assertLessEqual(int(P("galEffRows", "X")) + int(P("galEffRows", "Width")), int(P("lblEffPlanned", "X")))
        home = kids("scrMyTimesheets")
        hp = lambda k, p: int(home[k]["Properties"][p].lstrip("="))  # noqa: E731
        self.assertLessEqual(hp("btnEff", "Y") + hp("btnEff", "Height"), hp("btnReg", "Y"))
        self.assertGreater(hp("btnEff", "X"), int(home["lblRange"]["Properties"]["X"].lstrip("=")) + int(home["lblRange"]["Properties"]["Width"].lstrip("=")))
        for k in ("EFF_OK", "EFF_REFUSED", "EFF_PARTIAL", "EFF_INVALID", "EFF_LEAVE", "EFF_NO_ACCESS", "EFF_NO_PM", "EFF_PM_OK", "EFF_PM_SAME",
                  "EFF_CONFIG_INVALID"):
            self.assertIn(k, app.MESSAGES)
            self.assertNotRegex(app.MESSAGES[k], r"(?i)sharepoint|list|flow|http|stack")


if __name__ == "__main__":
    unittest.main(verbosity=2)
