"""R3 M1 S12.5 Hour Registration Canvas screen (generated Power Apps YAML): tests HC01-HC13 (offline)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "registration")]
import build_demo_app as app  # noqa: E402
import hour_registration as H  # noqa: E402

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


C = kids("scrHourRegistration")
P = lambda k, p: C[k]["Properties"][p].lstrip("=")  # noqa: E731
SRC = json.dumps(SCR["scrHourRegistration"], ensure_ascii=False)


class HourRegistrationCanvas(unittest.TestCase):
    def test_HC01_screen_and_navigation(self):
        home = kids("scrMyTimesheets")
        self.assertIn("Navigate(scrHourRegistration", home["btnReg"]["Properties"]["OnSelect"])
        self.assertEqual(home["btnReg"]["Properties"]["Visible"], "=!varNoReg")
        self.assertEqual(P("lblRegTitle", "Text"), '"Đăng ký công"')

    def test_HC02_read_sends_only_the_project(self):
        calls = re.findall(r"'REG-ReadMatrix'\.Run\((.*?)\)\);", app.REG_READ)
        self.assertEqual(calls, ["Text(varRegPid)"])
        self.assertNotRegex(calls[0], r"(?i)User\(\)|role|upn")

    def test_HC03_save_sends_changed_cells_only(self):
        s = app.REG_SAVE
        self.assertIn("'REG-SaveMatrix'.Run(Text(varRegPid), JSON(ForAll(%s As c" % app.REG_DIRTY, s)
        self.assertIn('state: If(IsBlank(Trim(c.t)), "blank", "value")', s)
        self.assertIn('value: Substitute(Trim(c.t), ",", ".")', s)
        self.assertIn("JSONFormat.Compact), GUID())", s)
        self.assertIn("CountRows(%s) > 100" % app.REG_DIRTY, P("btnRegSave", "DisplayMode"), "never silently split into several saves")
        call = s[s.index("'REG-SaveMatrix'.Run("):s.index("GUID()")]
        self.assertNotRegex(call, r"(?i)ActorUpn|OwnerUpn|Role|Scope|User\(\)")

    def test_HC04_read_only_mode(self):
        self.assertEqual(P("btnRegSave", "Visible"), "varRegCanEdit")
        self.assertIn("varRegCanEdit", P("txtRegCell", "DisplayMode"))
        self.assertIn('varReg.canedit = "true"', app.REG_READ)

    def test_HC05_blank_and_zero_distinct(self):
        d = P("txtRegCell", "Default")
        self.assertIn('Coalesce(LookUp(colRegCells, k = Text(ThisItem.phid) & "|" & Text(ThisItem.id)).value, "")', d)
        self.assertNotIn("Value(", d, "no numeric coercion of a blank cell")
        self.assertEqual(P("txtRegCell", "HintText"), '"—"')
        self.assertNotIn("Blank() = 0", SRC)

    def test_HC06_client_validation_matches_server(self):
        rx = re.search(r'IsMatch\(Trim\(e\.t\), "([^"]+)"\)', app.REG_INVALID).group(1)
        for v in ("0", "7", "12.5", "12,25", "999999.99"):
            self.assertTrue(re.fullmatch(rx, v), v)
            self.assertIsNone(H.value_code(v.replace(",", ".")), v)
        for v in ("-1", "1.234", "abc", "1e3"):
            self.assertFalse(re.fullmatch(rx, v), v)
            self.assertIsNotNone(H.value_code(v), v)
        self.assertIn(app.REG_INVALID.split(" As e")[0], P("btnRegSave", "DisplayMode"))

    def test_HC07_dirty_prompts(self):
        self.assertIn("Set(varRegLeave, true)", P("btnRegBack", "OnSelect"))
        self.assertIn("Set(varRegSwitch, true)", P("ddRegProject", "OnChange"))
        self.assertEqual(P("lblRegLeave", "Visible"), "varRegLeave || varRegSwitch")
        self.assertIn("Reset(ddRegProject)", P("btnRegLeaveNo", "OnSelect"))

    def test_HC08_no_protected_list_and_no_direct_write(self):
        self.assertIn("HourRegistrations", app.PROTECTED_LISTS)
        self.assertNotRegex(SRC, r"\bHourRegistrations\b")
        for verb in ("Patch(", "SubmitForm(", "Remove(", "RemoveIf(", "UpdateIf("):
            self.assertNotIn(verb, SRC)

    def test_HC09_geometry_no_overlap(self):
        y = lambda k, p="Y": int(P(k, p))  # noqa: E731
        bottom = y("btnRegLeaveYes") + y("btnRegLeaveYes", "Height")
        self.assertLess(bottom, y("galRegHead"))
        self.assertLess(y("galRegHead") + y("galRegHead", "Height"), y("galRegRows") + 1)
        self.assertLess(y("btnRegSave") + 40, y("lblRegLeave"))

    def test_HC10_no_business_maximum(self):
        for cap in ("999.9", "9999", "999)", "Max("):
            self.assertNotIn(cap, SRC)

    def test_HC11_all_projects_listed_any_status(self):
        items = P("ddRegProject", "Items")
        self.assertNotIn("Status", items, "OD-07: no status filter")
        self.assertIn('ProjectCode & " — " & Title', items)
        self.assertIn("ProjectYear", items)

    def test_HC12_result_handling_keeps_unsaved_cells(self):
        s = app.REG_SAVE
        self.assertIn('Filter(colRegRes, rc = "OK" || rc = "NO_CHANGE").k', s)
        for code in ('"REFUSED"', '"PARTIAL"', '"OK"'):
            self.assertIn(code, s)
        self.assertTrue(s.rstrip().endswith(app.REG_READ.rstrip()), "matrix re-read after every save")

    def test_HC13_messages(self):
        for k in ("REG_OK", "REG_REFUSED", "REG_PARTIAL", "REG_INVALID", "REG_LEAVE", "REG_NO_ACCESS"):
            self.assertIn(k, app.MESSAGES)
            self.assertNotRegex(app.MESSAGES[k], r"(?i)sharepoint|list|flow|http|stack")


if __name__ == "__main__":
    unittest.main(verbosity=2)
