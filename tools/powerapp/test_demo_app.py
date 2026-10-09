"""R1 demo Canvas app source tests DA01-DA12 (offline; generated Power Apps YAML) and DEMO_ONLY data tests DD01-DD04."""
import json
import os
import re
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "demo")]
import build_demo_app as app  # noqa: E402
import demo_data as dd  # noqa: E402

CONTRACT = os.path.join(HERE, "..", "..", "docs", "timesheet-r1-contracts.md")


def source():
    d = tempfile.mkdtemp()
    files = app.build(d)
    text = "\n".join(open(f, encoding="utf-8").read() for f in files if f.endswith(".pa.yaml"))
    return files, text


class DemoApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.text = source()

    def test_DA01_four_screens_and_valid_yaml(self):
        names = {os.path.basename(f) for f in self.files}
        self.assertEqual(names, {"App.pa.yaml", "scrStartup.pa.yaml", "scrAccessDenied.pa.yaml", "scrMyTimesheets.pa.yaml",
                                 "scrEntry.pa.yaml", "scrTeamApproval.pa.yaml", "messages.json"})
        for f in self.files:
            if f.endswith(".pa.yaml"):
                self.assertIsInstance(yaml.safe_load(open(f, encoding="utf-8")), dict, f)

    def test_DA02_startup_calls_appopen_and_routes_denied_or_config_error(self):
        scr = app.screens()["scrStartup"]
        route = [c["tmrRoute"] for c in scr["Children"] if "tmrRoute" in c][0]["Properties"]
        self.assertIn("'TS-AppOpen'.Run(", scr["Properties"]["OnVisible"])
        s = scr["Properties"]["OnVisible"] + route["OnTimerEnd"]
        self.assertIn('varOpen.configstatus = "OK"', s)
        self.assertIn("Navigate(scrAccessDenied", s)
        self.assertIn("Navigate(scrMyTimesheets", s)

    def test_DA03_list_is_bounded_current_pay_period(self):
        s = app.screens()["scrMyTimesheets"]["Properties"]["OnVisible"]
        self.assertIn("varStartDay", s)
        self.assertRegex(s, r"'TS-ReadOwn'\.Run\(Text\(varFrom, \"yyyy-mm-dd\"\), Text\(varTo, \"yyyy-mm-dd\"\)")
        self.assertNotRegex(self.text, r"'TS-ReadOwn'\.Run\(\"\", *\"\"", "never an unbounded read")

    def test_DA04_requested_owner_never_sent(self):
        for m in re.finditer(r"'TS-ReadOwn'\.Run\(([^;]*?)\);", self.text, re.S):
            self.assertTrue(m.group(1).rstrip().rstrip(")").endswith('""'), "RequestedOwner must stay empty (server uses the trusted caller)")

    def test_DA05_save_arguments_match_the_trigger(self):
        s = app.SAVE_ONSELECT
        args = s[s.index("'TS-SaveEntry'.Run(") + len("'TS-SaveEntry'.Run("):s.index(");\nSet(varSaving, false)")]
        depth, parts, cur = 0, [], ""
        for ch in args:
            depth += ch == "(" or ch == "{"
            depth -= ch == ")" or ch == "}"
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        self.assertEqual(len(parts), 10, "ItemId, ETag, WorkDate, Project, Phase, WorkType, Shift, HourType, Hours, Remark")
        self.assertNotIn("Owner", args)
        self.assertNotIn("User()", args)

    def test_DA06_save_disabled_while_running(self):
        e = {k: v for c in app.screens()["scrEntry"]["Children"] for k, v in c.items()}
        self.assertIn("varSaving", e["btnSave"]["Properties"]["DisplayMode"])
        self.assertTrue(app.SAVE_ONSELECT.strip().startswith("Set(varSaving, true)"))

    def test_DA07_audit_degraded_is_success_with_warning(self):
        s = app.SAVE_ONSELECT
        self.assertIn('If(varSave.ok = "true"', s)
        self.assertIn("AUDIT_DEGRADED", app.MESSAGES)
        self.assertIn("Do not save again", app.MESSAGES["AUDIT_DEGRADED"])
        self.assertNotIn("Run(", s[s.index('If(varSave.ok = "true"'):], "no automatic retry")

    def test_DA08_conflict_and_reload_required_force_a_reread(self):
        s = app.SAVE_ONSELECT
        self.assertIn('varSave.resultcode = "CONFLICT"', s)
        self.assertIn("varReloadRequired", s)
        self.assertIn("Navigate(scrMyTimesheets", s)  # list OnVisible re-reads (fresh ETags)

    def test_DA09_every_contract_code_has_provisional_wording(self):
        txt = open(CONTRACT, encoding="utf-8").read()
        codes = set(re.findall(r"`([A-Z][A-Z_]{2,})`", txt.split("## Result codes shown to users")[1].split("## ")[0]))
        codes -= {"OK"}
        for c in codes:
            key = c if c.startswith("WARN_") or c == "AUDIT_DEGRADED" else "MSG_" + c
            self.assertIn(key, app.MESSAGES, c)
        self.assertIn("PROVISIONAL", open(next(f for f in self.files if f.endswith("messages.json")), encoding="utf-8").read())

    def test_DA10_no_protected_list_data_source_or_direct_write(self):
        for lst in app.PROTECTED_LISTS:
            self.assertNotRegex(self.text, r"\b%s\b" % lst, lst)
        for verb in ("Patch(", "SubmitForm(", "Remove(", "RemoveIf(", "UpdateIf("):
            self.assertNotIn(verb, self.text)

    def test_DA11_no_tenant_values_in_source(self):
        self.assertEqual(re.findall(r"https?://|@[a-z0-9-]+\.[a-z]{2,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", self.text, re.I), [])

    def test_DA13_appopen_message_codes_covered(self):
        sys.path.insert(0, os.path.join(HERE, "..", "powerautomate"))
        import build_appstart_flow as baf
        for code in set(baf.MESSAGE.values()) | {"MSG_CONFIG_UNRESOLVED", "MSG_CONFIG_INVALID"}:
            self.assertIn(code, app.MESSAGES, code)

    def test_DA12_warnings_never_block_and_messages_hide_internals(self):
        for k, v in app.MESSAGES.items():
            self.assertNotRegex(v, r"(?i)sharepoint|list|flow|http|stack", k)
        self.assertIn("you can still save", self.text)


    def test_DA14_dropdown_display_column_uses_items_value(self):
        # live STAGING (Power Apps Studio paste): a Classic/DropDown `Value` property is rejected ("something wrong with
        # the pasted code"); the display column is `Items.Value: =<column>`
        f = [f for f in self.files if f.endswith("scrEntry.pa.yaml")][0]
        scr = yaml.safe_load(open(f, encoding="utf-8"))
        dds = {k: v for c in scr["Screens"]["scrEntry"]["Children"] for k, v in c.items() if v["Control"].startswith("Classic/DropDown")}
        self.assertEqual({k: v["Properties"].get("Items.Value") for k, v in dds.items()},
                         {"ddProject": "=ProjectCode", "ddPhase": "=PhaseCode", "ddWorkType": "=WorkTypeCode", "ddShift": "=ShiftCode",
                          "ddHourType": "=HourTypeCode"})
        self.assertFalse(any("Value" in v["Properties"] for v in dds.values()))

    def test_DA16_team_approval_mode(self):
        """S07.2: queue from the guarded TS-ReadTeam, multi-select, Approve via TS-Approve with {itemId, etag} only, refresh."""
        scr = app.screens()["scrTeamApproval"]
        c = {k: v for x in scr["Children"] for k, v in x.items()}
        self.assertIn("'TS-ReadTeam'.Run(varTeamPeriod,", scr["Properties"]["OnVisible"])
        self.assertIn('"yyyy-mm"', scr["Properties"]["OnVisible"])
        sel = c["galTeam"]["Children"][0]["btnSel"]["Properties"]["OnSelect"]
        self.assertIn("Collect(colSel, {id: ThisItem.id, etag: ThisItem.etag})", sel)
        self.assertIn("CountRows(colSel) = 0", c["btnApprove"]["Properties"]["DisplayMode"])
        self.assertIn("CountRows(colSel) > 50", c["btnApprove"]["Properties"]["DisplayMode"])
        self.assertEqual(c["btnApprove"]["Properties"]["OnSelect"], "=Set(varConfirm, true)")  # confirm first
        ap = c["btnConfirmYes"]["Properties"]["OnSelect"]
        self.assertIn("'TS-Approve'.Run(JSON(ForAll(colSel, {itemId: id, etag: etag}), JSONFormat.Compact), \"\")", ap)
        call = ap[ap.index("'TS-Approve'.Run("):ap.index("));", ap.index("'TS-Approve'.Run("))]
        self.assertNotRegex(call, r"(?i)owner|approvedby|role|scope|discipline|User\(\)", "only item ids and ETags are sent")
        self.assertIn("'TS-ReadTeam'.Run(", ap[ap.index("'TS-Approve'"):], "the queue is re-read after approving")
        # S07.3 adds TS-Unapprove only behind the explicit per-row action (test_unapprove_flow UQ38); never on the batch path
        self.assertNotIn("'TS-Unapprove'", c["btnConfirmYes"]["Properties"]["OnSelect"])
        self.assertIn("MSG_APPROVE_CONFIRM", app.MESSAGES)
        num = lambda c, k: int(c[k]["Properties"]["Y"].lstrip("="))  # noqa: E731
        bottom = int(c["btnConfirmYes"]["Properties"]["Y"].lstrip("=")) + int(c["btnConfirmYes"]["Properties"]["Height"].lstrip("="))
        self.assertLess(bottom, num(c, "galTeam"), "confirm buttons must not overlap the gallery (live finding)")
        for k in ("MSG_PARTIAL", "MSG_REFUSED", "MSG_VALIDATION_REQUEST", "MSG_ROW_APPROVED"):
            self.assertIn(k, app.MESSAGES)
        lst = {k: v for x in app.screens()["scrMyTimesheets"]["Children"] for k, v in x.items()}
        self.assertEqual(lst["btnTeam"]["Properties"]["Visible"], "=!varNoTeam")
        edit = lst["galEntries"]["Children"][2]["btnEdit"]["Properties"]["Visible"]
        self.assertEqual(edit, '=ThisItem.status = "Draft"', "Edit only for Draft (Approved rows are locked)")

    def test_DA15_start_screen_onvisible_never_navigates(self):
        # live STAGING (Studio app checker): Navigate in the start screen's OnVisible is an error; a hidden timer routes
        scr = app.screens()["scrStartup"]
        self.assertNotIn("Navigate(", scr["Properties"]["OnVisible"])
        self.assertIn("Set(varRoute, true)", scr["Properties"]["OnVisible"])
        t = [c["tmrRoute"] for c in scr["Children"] if "tmrRoute" in c][0]
        self.assertEqual((t["Control"], t["Properties"]["Start"], t["Properties"]["Visible"], t["Properties"]["AutoStart"]),
                         ("Timer@2.1.0", "=varRoute", "=false", "=false"))
        self.assertTrue(t["Properties"]["OnTimerEnd"].lstrip("=\n").startswith("Set(varRoute, false)"))

    def test_DA16_phase_filter_reads_lookup_ids_per_row(self):
        # live STAGING (Studio): `<table>.Phase.Id` is invalid Power Fx ("'Id' isn't recognized"); ids come from ForAll
        items = [c["ddPhase"] for c in app.screens()["scrEntry"]["Children"] if "ddPhase" in c][0]["Properties"]["Items"]
        self.assertIn("ForAll(Filter(ProjectPhases, ProjectItemId = ddProject.Selected.ID, IsActive), Phase.Id)", items)
        self.assertNotIn(").Phase.Id", items)


    def test_DA17_load_more_hidden_on_last_page(self):
        # live STAGING: ReadOwn returns nextafterid "0" when the page is not full; the button must stay hidden
        more = [c["btnMore"] for c in app.screens()["scrMyTimesheets"]["Children"] if "btnMore" in c][0]["Properties"]["Visible"]
        self.assertIn('varNextAfter <> "0"', more)


class DemoData(unittest.TestCase):
    def test_DD01_rows_valid_and_marked(self):
        self.assertEqual(dd.validate(dd.demo_rows()), [])
        for lst, rs in dd.demo_rows().items():
            for r in rs:
                self.assertEqual(r["MigrationBatch"], "DEMO_ONLY", lst)
                self.assertTrue(r["LegacyId"].startswith("DEMO-"))

    def test_DD02_validation_catches_problems(self):
        bad = dd.demo_rows()
        bad["Phases"][0]["MigrationBatch"] = "CANONICAL"
        bad["ProjectPhases"][0]["Phase"] = "NOPE"
        bad["HourTypes"] = []
        p = dd.validate(bad)
        self.assertTrue(any("DEMO_ONLY" in x for x in p) and any("unknown" in x for x in p) and any("normal hour" in x for x in p), p)

    def test_DD03_minimal_set_is_enough_for_the_save_path(self):
        r = dd.demo_rows()
        self.assertEqual([len(r[k]) for k in ("Projects", "Shifts", "HourTypes")], [1, 1, 1])
        self.assertTrue(all(x["Status"] == "Active" for x in r["Projects"]))
        self.assertEqual({x["Phase"] for x in r["ProjectPhases"]}, {x["PhaseCode"] for x in r["Phases"]})

    def test_DD04_demo_employee_identity_from_configuration_only(self):
        with self.assertRaises(ValueError):
            dd.demo_employee("", 1, 1)
        e = dd.demo_employee("Someone@Tenant-A.invalid", 3, 4)
        self.assertEqual((e["AccountUpn"], e["DepartmentId"], e["DisciplineId"], e["IsActive"], e["MigrationBatch"]),
                         ("someone@tenant-a.invalid", 3, 4, True, "DEMO_ONLY"))
        src = open(os.path.join(HERE, "..", "demo", "demo_data.py"), encoding="utf-8").read()
        self.assertEqual(re.findall(r"[a-z0-9.-]+@[a-z0-9-]+\.(?:vn|com)", src), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
