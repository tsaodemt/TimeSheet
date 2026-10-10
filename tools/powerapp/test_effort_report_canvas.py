"""R3 M4 current-scope report Canvas screen (generated Power Apps YAML): tests RC01-RC09 (offline)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "reporting"), os.path.join(HERE, "..", "effort"), os.path.join(HERE, "..", "powerautomate"),
                os.path.join(HERE, "..", "identity")]
import build_demo_app as app  # noqa: E402
import build_report_flows as bf  # noqa: E402
import test_guard as tg  # noqa: E402

SCR = app.screens()
KW = dict(role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit",
          conf_audit_list="_ConfAudit", environment="STAGING")


def kids(screen):
    out = {}

    def walk(children):
        for x in children:
            for k, v in x.items():
                out[k] = v
                walk(v.get("Children", []))
    walk(SCR[screen]["Children"])
    return out


C = kids("scrEffortReport")
P = lambda k, p: C[k]["Properties"][p].lstrip("=")  # noqa: E731
SRC = json.dumps(SCR["scrEffortReport"], ensure_ascii=False)
ALL = SRC + app.RPT_PROJECT + app.RPT_DISCIPLINE


class EffortReportCanvas(unittest.TestCase):
    def test_RC01_navigation_title_onstart(self):
        home = kids("scrMyTimesheets")
        self.assertIn("Navigate(scrEffortReport", home["btnRpt"]["Properties"]["OnSelect"])
        self.assertEqual(P("lblRptTitle", "Text"), '"Báo cáo công"')
        for v in ("varNoRptP", "varNoRptD", "varRptTab"):
            self.assertIn("Set(%s," % v, app.APP_ONSTART)
        hp = lambda k, p: int(home[k]["Properties"][p].lstrip("="))  # noqa: E731
        self.assertGreaterEqual(hp("btnRpt", "X"), hp("btnEff", "X") + hp("btnEff", "Width"))
        self.assertLessEqual(hp("btnRpt", "X") + hp("btnRpt", "Width"), 1366)

    def test_RC02_requests_carry_no_identity_or_scope(self):
        self.assertIn("'RPT-ProjectReport'.Run(GUID())", app.RPT_PROJECT)
        self.assertIn("'RPT-DisciplineReport'.Run(GUID())", app.RPT_DISCIPLINE)
        self.assertEqual(set(re.findall(r"'RPT-\w+'\.Run\(([^)]*)\)", ALL)), {"GUID("}, "only GUID() is sent")
        self.assertNotRegex(ALL, r"\.Run\([^)]*(User\(\)|upn|role|disc|project)", "no caller-supplied claims")

    def test_RC03_aggregates_only_no_client_total(self):
        self.assertNotRegex(ALL, r"\bSum\(|\bAverage\(", "the server computes every figure")
        for lst in ("TimesheetEntries", "ProjectEffortAllocations", "DisciplineEffortRegistrations", "HourRegistrations", "ProjectPmAssignments"):
            self.assertIn(lst, app.PROTECTED_LISTS)
            self.assertNotRegex(ALL, r"\b%s\b" % lst)
        for verb in ("Patch(", "SubmitForm(", "Remove(", "RemoveIf(", "UpdateIf("):
            self.assertNotIn(verb, ALL)

    def test_RC04_no_money(self):
        self.assertNotRegex(ALL, r"(?i)salary|\brate\b|cost|bonus|reward|lương|thưởng|đơn giá|chi phí|VND|₫")

    def test_RC05_m1_separate_and_server_driven(self):
        self.assertIn('If(varRptP.showregistered = "true", " · M1: "', P("lblRptPRow", "Text"))
        self.assertIn("Đăng ký công (M1, riêng)", P("lblRptPHead", "Text"))
        self.assertNotRegex(ALL, r"planned\s*\+\s*\w*registered|registered\s*\+\s*\w*planned", "M1 never added to the plan")

    def test_RC06_blank_plan_zero_actual_and_labels(self):
        self.assertIn('If(ThisItem.planState = "BLANK", "chưa đăng ký"', P("lblRptPRow", "Text"))
        self.assertIn('"chưa có kế hoạch duyệt"', P("lblRptDRow", "Text"))
        info = P("lblRptInfo", "Text")
        for need in ("Chênh lệch = kế hoạch − thực hiện", "đã duyệt", "Kế hoạch bộ môn = dòng đã phê duyệt", "Kế hoạch = Công dự án"):
            self.assertIn(need, info)
        self.assertIn(app.MSG % '"RPT_EMPTY"', P("lblRptEmpty", "Text"))

    def test_RC07_fields_match_flow_responses(self):
        pk = set(bf.project_report_actions(**KW)["Respond"]["inputs"]["body"])
        dk = set(bf.discipline_report_actions(**KW)["Respond"]["inputs"]["body"])
        self.assertLessEqual(set(re.findall(r"\bvarRptP\.(\w+)", ALL)), pk)
        self.assertLessEqual(set(re.findall(r"\bvarRptD\.(\w+)", ALL)), dk)
        self.assertLessEqual(set(re.findall(r"ThisRecord\.Value\.(\w+)", ALL)),
                             {"projectId", "code", "name", "planState", "planned", "actualHours", "actualManDays", "variance", "registered",
                              "disciplineCode", "disciplineName"})

    def test_RC08_errors_and_denial(self):
        for f, n in ((app.RPT_PROJECT, "varNoRptP"), (app.RPT_DISCIPLINE, "varNoRptD")):
            self.assertIn('= "ROLE_NOT_ALLOWED", Set(%s, true)' % n, f)
            self.assertIn('correlationid & ")", NotificationType.Error', f)
        self.assertEqual(kids("scrMyTimesheets")["btnRpt"]["Properties"]["Visible"], "=!(varNoRptP && varNoRptD)")
        for k in ("RPT_NO_ACCESS", "RPT_EMPTY"):
            self.assertIn(k, app.MESSAGES)

    def test_RC09_chained_blocks_and_studio_rules(self):
        for name in ("RPT_PROJECT", "RPT_DISCIPLINE", "RPT_LOAD"):
            self.assertIsNone(re.search(r"\)\s*\n\s*(Set|Notify|ClearCollect)\(", getattr(app, name)), name)
        for k, v in C.items():
            for prop, val in v.get("Properties", {}).items():
                self.assertIsNone(re.search(r"\)\s*\n\s*(Set|Notify|ClearCollect)\(", val), (k, prop))
            if v.get("Control") == "Classic/Button@2.2.0":
                self.assertNotIn("AccessibleLabel", v["Properties"], k)


if __name__ == "__main__":
    unittest.main(verbosity=2)
