"""S07.4 server-side immutability and SEC-Monitor: tests IM01-IM26 (offline; synthetic data only).

Save cases run the reference (entries.save_entry) and the generated TS-SaveEntry flow (build_r1_flows) side by side in
the WDL simulator (helpers of test_r1_save_flow). Approval transitions reuse the S07.2 / S07.3 harnesses. Delete and
reorder have no target business path yet: their cases test the shared invariant only and say so
(NOT_IMPLEMENTED_CURRENT_PATH); nothing here claims a live result."""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (HERE, os.path.join(HERE, "..", "timesheet"), os.path.join(HERE, "..", "approval"), os.path.join(HERE, "..", "powerautomate"),
          os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config"), os.path.join(HERE, "..", "audit"),
          os.path.join(HERE, "..", "alm"), os.path.join(HERE, "..", "maintenance"), os.path.join(HERE, "..", "powerapp")):
    sys.path.insert(0, p)
import audit_event as ae  # noqa: E402
import entries as E  # noqa: E402
import poc_timesheet as pt  # noqa: E402
import sec_monitor as M  # noqa: E402
import test_approve_flow as ta  # noqa: E402
import test_r1_save_flow as ts  # noqa: E402
import test_unapprove_flow as tu  # noqa: E402
import build_sec_monitor_flow as bsm  # noqa: E402
import build_demo_app as bda  # noqa: E402
import wdl_sim  # noqa: E402

ME, OTHER = ts.ME, ts.OTHER
SVC = "svc-timesheet@tenant-a.invalid"
INTRUDER = "someone@tenant-a.invalid"
BUSINESS = ("WorkDate", "ProjectId", "PhaseId", "WorkTypeId", "ShiftId", "HourTypeId", "Hours", "Remark", "OwnerUpn", "EntryStatus")
NI = "NOT_IMPLEMENTED_CURRENT_PATH"
LOCKED_TEXT = "Dữ liệu đã được phê duyệt"
DOC = os.path.join(ROOT, "docs", "immutability-and-monitor.md")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def claims(upn):
    return {"Name": "i:0#.f|membership|%s" % upn, "EMail": upn}


def change(i, editor, version="2.0", author=None, **row):
    c = {"Id": i, "Editor": claims(editor), "Author": claims(author or SVC), "Modified": "2026-10-09T05:00:00Z",
         "Created": "2026-10-09T04:00:00Z", "OData__UIVersionString": version}
    c.update(row)
    return c


SETTINGS = {"OpsAlertRecipient": {"value": "ops-alerts@tenant-a.invalid", "resolution": "RESOLVED"}}


class SaveImmutability(ts._Both):
    """IM01-IM06, IM25: TS-SaveEntry edit of an Approved row (item 3, owner ME) is LOCKED, nothing written."""

    def locked(self, request, **kw):
        before = copy.deepcopy(ts.ITEMS[2])
        f = self.both(ME, request, **kw)
        self.assertEqual((f["ok"], f["code"], f["messageCode"]), (False, "LOCKED", "MSG_LOCKED"))
        self.nothing_written()
        row = self.ctx["store"].items[3]
        self.assertEqual({k: row.get(k) for k in BUSINESS}, {k: before.get(k) for k in BUSINESS})
        return f

    def test_IM01_draft_save_allowed(self):
        f = self.both(ME, ts.req(ItemId="1", ETag='"1,1"', Hours="3"))
        self.assertEqual((f["ok"], f["code"]), (True, "OK"))
        self.assertEqual(self.ctx["store"].items[1]["Hours"], 3.0)

    def test_IM02_approved_save_locked(self):
        self.locked(ts.req(ItemId="3", ETag='"3,1"'))

    def test_IM03_approved_save_changes_zero_business_fields(self):
        self.locked(ts.req(ItemId="3", ETag='"3,1"', Hours="7", Remark="tamper", ProjectCode="P3", PhaseCode="PH3"))
        self.assertEqual(self.ctx["posts"][-1]["ResultCode"] if self.ctx["posts"] else "LOCKED", "LOCKED")

    def test_IM04_forged_entry_status_no_bypass(self):
        self.locked(ts.req(ItemId="3", ETag='"3,1"'), decoys={"EntryStatus": "Draft"})

    def test_IM05_forged_owner_no_bypass(self):
        # a forged owner never selects the row's owner; a foreign Approved row is FORBIDDEN (no write) before LOCKED
        self.locked(ts.req(ItemId="3", ETag='"3,1"'), decoys={"OwnerUpn": OTHER, "ActorUpn": OTHER, "Role": "ADM", "Scope": "company"})
        f = self.both(OTHER, ts.req(ItemId="3", ETag='"3,1"'), decoys={"OwnerUpn": ME})
        self.assertEqual(f["code"], "FORBIDDEN")
        self.nothing_written()

    def test_IM06_locked_precedes_etag(self):
        for etag in ('"3,1"', '"3,0"', "", "*"):
            self.locked(ts.req(ItemId="3", ETag=etag))

    def test_IM06b_approved_between_read_and_write_is_conflict_no_write(self):
        class ApproveRace(ts.Store):
            def update(self, i, fields, if_match):
                self.items[i]["EntryStatus"] = "Approved"  # TS-Approve committed between the GET and the MERGE
                self.ver[i] += 1
                return super().update(i, fields, if_match)
        fs = ApproveRace(ts.ITEMS)
        f, _, _, _ = ts.run_flow(ME, ts.req(ItemId="1", ETag='"1,1"', Hours="9"), fs, ts.SCOPING_OFF)
        rs = ApproveRace(ts.ITEMS)
        r, _ = ts.ref(ME, ts.req(ItemId="1", ETag='"1,1"', Hours="9"), rs, ts.SCOPING_OFF)
        self.assertEqual((f["code"], r["code"]), ("CONFLICT", "CONFLICT"))
        self.assertEqual((fs.items[1]["Hours"], rs.items[1]["Hours"]), (2.0, 2.0))

    def test_IM25_canonical_locked_unchanged(self):
        self.assertEqual(E.LOCKED, "LOCKED")
        src = read("tools", "powerautomate", "build_r1_flows.py")
        self.assertIn("'LOCKED'", src)
        self.assertFalse(re.search(r"'(APPROVED_LOCKED|IMMUTABLE|ROW_LOCKED)'", src), "no near-duplicate result code")
        self.assertIn("MSG_LOCKED", json.loads(read("tools", "powerapp", "demo-r1", "messages.json"))["messages"])

    def test_IM27_locked_message_is_the_legacy_wording(self):
        # W-1 (owner 2026-10-09): code LOCKED, message exactly the verified legacy text
        self.assertEqual(bda.MESSAGES["MSG_LOCKED"], LOCKED_TEXT)
        self.assertEqual(json.loads(read("tools", "powerapp", "demo-r1", "messages.json"))["messages"]["MSG_LOCKED"], LOCKED_TEXT)
        self.assertIn('{code: "MSG_LOCKED", text: "%s"}' % LOCKED_TEXT, read("tools", "powerapp", "demo-r1", "App.pa.yaml"))
        f = self.locked(ts.req(ItemId="3", ETag='"3,1"'))
        self.assertEqual((f["code"], f["messageCode"]), ("LOCKED", "MSG_LOCKED"))


class Invariant(unittest.TestCase):
    """The shared server-side rule every ordinary mutation uses (save edit today; planned soft delete / reorder)."""

    def row(self, status):
        return {"OwnerUpn": ME, "EntryStatus": status, "Hours": 2.0}

    def test_IM09_approved_delete_refused_by_shared_invariant(self):
        self.assertEqual(E.ordinary_mutation_refusal(self.row("Approved"), ME), "LOCKED")
        self.assertIsNone(E.ordinary_mutation_refusal(self.row("Draft"), ME))
        self.assertEqual(E.ordinary_mutation_refusal(self.row("Deleted"), ME), "NOT_FOUND")
        self.assertEqual(E.ordinary_mutation_refusal(None, ME), "NOT_FOUND")
        self.assertEqual(E.ordinary_mutation_refusal(self.row("Approved"), OTHER), "FORBIDDEN")

    def test_IM10_invariant_has_no_side_effect_and_no_delete_path_exists(self):
        r = self.row("Approved")
        before = dict(r)
        E.ordinary_mutation_refusal(r, ME)
        self.assertEqual(r, before)
        # current target: no TimesheetEntries delete / soft-delete business path is generated (NOT_IMPLEMENTED_CURRENT_PATH)
        for f in ("build_r1_flows.py", "build_approval_flows.py"):
            src = read("tools", "powerautomate", f)
            self.assertNotIn("SoftDelete", src, f)
            self.assertFalse(re.search(r"\"EntryStatus\"\s*:\s*\"Deleted\"", src), f)

    def test_IM11_no_hard_delete_permission_required(self):
        self.assertEqual(pt.SERVICE_ENTRY_RIGHTS, {"ViewListItems", "AddListItems", "EditListItems"})
        self.assertIn("DeleteListItems", pt.NEVER)
        for f in ("build_r1_flows.py", "build_approval_flows.py"):
            src = read("tools", "powerautomate", f)
            self.assertFalse(re.search(r"X-HTTP-Method\"?: *\"?DELETE|\"method\": *\"DELETE\"", src), f)

    def test_IM12_approved_reorder_refused_by_shared_invariant(self):
        self.assertEqual(E.ordinary_mutation_refusal(self.row("Approved"), ME), "LOCKED")
        self.assertIn("SortOrder", pt.GATED_COLUMNS, "reorder column not provisioned: no current reorder path")

    def test_IM13_draft_reorder_unchanged(self):
        self.skipTest("%s: no target reorder path (F-TS-15 not built; SortOrder gated)" % NI)


class ApprovalTransitions(tu._Both):
    """IM07, IM08: the invariant does not block the authorised approval state transitions."""

    def test_IM07_unapprove_still_allowed_for_authorised_approved_row(self):
        f = self.unapprove(tu.ME, tu.APR, 1, '"1,1"')
        self.assertEqual((f["ok"], f["code"]), (True, "OK"))
        self.assertEqual(self.ctx["store"].items[1]["EntryStatus"], "Draft")

    def test_IM08_approve_still_works_for_eligible_draft(self):
        h = ta.Approve("test_AQ01_team_leader_same_discipline_ok")
        f = h.approve(ta.ME, ta.TL, [(1, '"1,1"')])
        self.assertEqual((f["ok"], f["code"], h.ctx["store"].items[1]["EntryStatus"]), (True, "OK", "Approved"))


class Regression(unittest.TestCase):
    def _suite(self, mod):
        with open(os.devnull, "w") as null:
            r = unittest.TextTestRunner(stream=null, verbosity=0).run(unittest.defaultTestLoader.loadTestsFromModule(mod))
        self.assertTrue(r.wasSuccessful() and r.testsRun > 30, (len(r.failures), len(r.errors)))

    def test_IM23_s072_approval_regression(self):
        self._suite(ta)

    def test_IM24_s073_unapproval_regression(self):
        self._suite(tu)


class Monitor(unittest.TestCase):

    def test_IM14_saveentry_write_trusted(self):
        # TS-SaveEntry create (v1.0) and edit: editor and author = service connection
        self.assertEqual(M.classify(change(7, SVC, "1.0", ActorUpn=ME), SVC).verdict, M.TRUSTED_SERVICE_WRITE)
        self.assertEqual(M.classify(change(1, SVC, "3.0", ActorUpn=ME), SVC).verdict, M.TRUSTED_SERVICE_WRITE)

    def test_IM15_approve_write_trusted(self):
        self.assertEqual(M.classify(change(5, SVC.upper(), "4.0", EntryStatus="Approved", ApprovedBy=OTHER), SVC).verdict,
                         M.TRUSTED_SERVICE_WRITE)

    def test_IM16_unapprove_write_trusted(self):
        run = M.monitor([change(5, SVC, "5.0", EntryStatus="Draft")], service_upn=SVC, settings=SETTINGS, environment="STAGING")
        self.assertEqual((run.code, run.alerts, run.audit), ("OK", [], []))

    def test_IM17_out_of_band_write_detected(self):
        sent = []
        run = M.monitor([change(5, INTRUDER, "6.0"), change(9, SVC, "2.0"), change(10, INTRUDER, "1.0", author=INTRUDER)],
                        service_upn=SVC, settings=SETTINGS, environment="STAGING", now="2026-10-09T05:01:00Z",
                        send=lambda d, a: sent.append((d, a["targetItemId"])))
        self.assertEqual([c.verdict for c in run.classifications], [M.OUT_OF_BAND_EDIT, M.TRUSTED_SERVICE_WRITE, M.OUT_OF_BAND_EDIT])
        self.assertEqual(sent, [("ops-alerts@tenant-a.invalid", "5"), ("ops-alerts@tenant-a.invalid", "10")])
        # created directly by someone else, even if the service edits it later, stays visible as out-of-band at v1.0
        self.assertEqual(M.classify(change(11, SVC, "1.0", author=INTRUDER), SVC).verdict, M.OUT_OF_BAND_EDIT)
        # unknown editor fails closed
        self.assertEqual(M.classify({"Id": 12, "OData__UIVersionString": "2.0"}, SVC).verdict, M.OUT_OF_BAND_EDIT)
        # duplicate delivery of the same version is not re-alerted; a later version is
        seen = set()
        a = M.monitor([change(5, INTRUDER, "6.0")], service_upn=SVC, settings=SETTINGS, environment="STAGING", seen=seen)
        b = M.monitor([change(5, INTRUDER, "6.0"), change(5, INTRUDER, "7.0")], service_upn=SVC, settings=SETTINGS,
                      environment="STAGING", seen=seen)
        self.assertEqual((len(a.alerts), [x["versionLabel"] for x in b.alerts]), (1, ["7.0"]))

    def test_IM18_alert_payload_required_fields(self):
        run = M.monitor([change(5, INTRUDER, "6.0")], service_upn=SVC, settings=SETTINGS, environment="STAGING",
                        now="2026-10-09T05:01:00Z")
        a = run.alerts[0]
        self.assertEqual(tuple(a), M.ALERT_FIELDS)
        self.assertEqual((a["environment"], a["reason"], a["targetEntity"], a["targetItemId"], a["editorUpn"], a["modifiedUtc"],
                          a["detectedUtc"], a["reference"]),
                         ("STAGING", "OUT_OF_BAND_EDIT", "TimesheetEntries", "5", INTRUDER, "2026-10-09T05:00:00Z",
                          "2026-10-09T05:01:00Z", "TimesheetEntries:5:6.0"))
        row = run.audit[0]
        self.assertEqual((row["EventType"], row["SourceFlow"], row["TargetList"]), ("SecurityMonitor", "SEC-Monitor", "TimesheetEntries"))
        self.assertNotIn(row["EventType"], ("Approval", "Unapproval"))
        self.assertFalse(ae.EVENT_TYPES["SecurityMonitor"]["enabled"], "pending until the alert destination exists")

    def test_IM19_alert_payload_excludes_prohibited_material(self):
        c = change(5, INTRUDER, "6.0", Hours=8, Remark="private", ProjectId=101, Rate=999, Salary=1, Authorization="Bearer x",
                   Cookie="c", Password="p", OwnerUpn=ME, CorrelationId="cid")
        run = M.monitor([c], service_upn=SVC, settings=SETTINGS, environment="STAGING")
        blob = json.dumps([run.alerts, run.audit]).lower()
        for bad in ("private", "999", "bearer", "cookie", "password", "salary", "rate", ME.lower(), "hours", "remark", "projectid"):
            self.assertNotIn(bad, blob, bad)

    def test_IM20_destination_from_configuration_only(self):
        sent = []
        for s in ({}, {"OpsAlertRecipient": ""}, {"OpsAlertRecipient": {"value": "x@y.invalid", "resolution": "BLOCKED"}}):
            run = M.monitor([change(5, INTRUDER)], service_upn=SVC, settings=s, environment="STAGING", send=lambda d, a: sent.append(d))
            self.assertEqual((run.code, run.destination, len(run.alerts)), (M.ALERT_DESTINATION_UNCONFIGURED, None, 1))
            self.assertEqual(run.audit[0]["ResultCode"], M.ALERT_DESTINATION_UNCONFIGURED)
        self.assertEqual(sent, [], "no recipient is assumed")
        self.assertEqual(M.monitor([change(5, INTRUDER)], service_upn="", settings=SETTINGS, environment="STAGING").code,
                         M.MONITOR_CONFIG_INVALID)
        src = read("tools", "security", "sec_monitor.py")
        self.assertFalse(re.search(r"[\w.-]+@(?!tenant-a\.invalid)[\w-]+\.[a-z]{2,}", src), "no hard-coded recipient")

    def test_IM21_no_client_controlled_bypass_marker(self):
        forged = change(5, INTRUDER, "6.0", ActorUpn=SVC, SourceFlow="TS-SaveEntry", TrustedWrite=True, IsServiceWrite=True,
                        CorrelationId="run-1", WrittenBy=SVC)
        self.assertEqual(M.classify(forged, SVC).verdict, M.OUT_OF_BAND_EDIT)
        src = read("tools", "timesheet", "entries.py")
        self.assertNotIn("TrustedWrite", src)

    def test_IM22_alert_sla_harness(self):
        self.assertEqual(M.ALERT_SLA_SECONDS, 300)
        self.assertEqual(M.alert_latency_seconds("2026-10-09T05:00:00Z", "2026-10-09T05:04:59Z"), 299)
        self.assertEqual(M.sla_verdict("2026-10-09T05:00:00Z", "2026-10-09T05:05:00Z"), "PASS")
        self.assertEqual(M.sla_verdict("2026-10-09T05:00:00Z", "2026-10-09T05:05:01Z"), "FAIL")
        self.assertEqual(M.sla_verdict("2026-10-09T05:00:00Z", "2026-10-09T04:59:00Z"), "FAIL")

    def test_IM21b_monitor_never_writes_timesheet_entries(self):
        src = read("tools", "security", "sec_monitor.py")
        self.assertNotRegex(src, r"(?i)merge|update\(|create\(")


SITE = "https://tenant-a.invalid/sites/x"
RCPT = "ops@tenant-a.invalid"


def flow_run(versions, scheduled, *, interval=2, fail=()):
    acts = bsm.monitor_actions(site=SITE, service_upn=SVC, recipient=RCPT, environment="STAGING", interval_minutes=interval)
    calls, sent = [], []

    def mocks(name, a, p):
        host = a["inputs"]["host"]
        if host["connectionName"] == bsm.OUTLOOK:
            assert host["operationId"] == "SendEmailV2"
            sent.append(p)
            return "Succeeded", {}
        assert p["parameters/method"] == "GET" and p["dataset"] == SITE, "monitor only reads"
        uri = p["parameters/uri"]
        calls.append(uri)
        if name in fail:
            return "Failed", {"statusCode": 503}
        m = re.search(r"items\((\d+)\)/versions", uri)
        if m:
            return "Succeeded", {"value": versions[int(m.group(1))]}
        since = re.search(r"Modified ge datetime'([^']+)Z'", uri).group(1)
        return "Succeeded", {"value": [{"Id": i} for i, vs in versions.items() if any(v["Created"] >= since for v in vs)]}
    run = wdl_sim.Run(trigger_body={"scheduledTime": scheduled}, mocks=mocks, now="2026-10-09T06:02:03Z").run(acts)
    return run, calls, sent


def ver(label, created, upn):
    return {"VersionLabel": label, "Created": created, "Editor": {"LookupId": 1, "LookupValue": "x", "Email": upn}}


VERSIONS = {5: [ver("1.0", "2026-10-09T05:00:00", SVC), ver("2.0", "2026-10-09T06:00:30", INTRUDER)],
            7: [ver("1.0", "2026-10-09T05:00:00", SVC), ver("2.0", "2026-10-09T06:00:10", SVC)],
            9: [ver("1.0", "2026-10-09T05:58:59", INTRUDER), ver("2.0", "2026-10-09T06:01:00", SVC.upper())]}


class MonitorFlow(unittest.TestCase):
    """IM28-IM32: generated SEC-Monitor flow vs the reference scan_versions model (WDL simulator)."""

    def alerts(self, sent):
        return [(re.search(r"Item: (\d+)", s["emailMessage/Body"]).group(1), re.search(r"Version: ([\d.]+)", s["emailMessage/Body"]).group(1))
                for s in sent]

    def test_IM28_flow_matches_reference(self):
        for sched in ("2026-10-09T06:00:00Z", "2026-10-09T06:02:00Z", "2026-10-09T06:04:00Z"):
            _, _, sent = flow_run(VERSIONS, sched)
            ref = M.scan_versions(VERSIONS, service_upn=SVC, scheduled_utc=sched, interval_minutes=2)
            self.assertEqual(self.alerts(sent), [(c.item_id, c.version) for c in ref], sched)

    def test_IM29_each_version_alerted_once_across_consecutive_windows(self):
        got = []
        for t in ("05:56", "05:58", "06:00", "06:02", "06:04", "06:06"):
            got += self.alerts(flow_run(VERSIONS, "2026-10-09T%s:00Z" % t)[2])
        self.assertEqual(sorted(got), [("5", "2.0"), ("9", "1.0")], "one alert per out-of-band version; service versions never")

    def test_IM30_alert_content(self):
        _, _, sent = flow_run(VERSIONS, "2026-10-09T06:02:00Z")
        s = sent[0]
        self.assertEqual((s["emailMessage/To"], s["emailMessage/Subject"]), (RCPT, "[STAGING][SECURITY] Timesheet out-of-band edit detected"))
        b = s["emailMessage/Body"]
        for x in ("Environment: STAGING", "Reason: OUT_OF_BAND_EDIT", "Target: TimesheetEntries", "Item: 5", "Version: 2.0",
                  "Modified (UTC): 2026-10-09T06:00:30", "Modified by: " + INTRUDER, "Reference: TimesheetEntries:5:2.0", "Run: run-0"):
            self.assertIn(x, b)
        for bad in ("Hours", "Remark", "Bearer", "Cookie", "token", "ProjectId", "Rate"):
            self.assertNotIn(bad, b)

    def test_IM31_read_only_and_config_driven(self):
        run, calls, _ = flow_run(VERSIONS, "2026-10-09T06:02:00Z")
        self.assertTrue(calls and all("TimesheetEntries" in u for u in calls))
        src = read("tools", "powerautomate", "build_sec_monitor_flow.py")
        self.assertFalse(re.search(r"[\w.-]+@[\w-]+\.[a-z]{2,}", src), "no address in source")
        self.assertNotIn("sharepoint.com", src)
        with self.assertRaises(ValueError) as e:
            bsm.monitor_actions(site=SITE, service_upn=SVC, recipient="", environment="STAGING")
        self.assertEqual(str(e.exception), "SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED")
        self.assertEqual(bsm.trigger(2), {"type": "Recurrence", "recurrence": {"frequency": "Minute", "interval": 2}})

    def test_IM32_read_failure_fails_the_run_no_silent_pass(self):
        run, _, sent = flow_run(VERSIONS, "2026-10-09T06:02:00Z", fail=("Get_changed",))
        self.assertEqual((run.results["Get_changed"]["status"], run.results["Each_item"]["status"], sent), ("Failed", "Skipped", []))


class Records(unittest.TestCase):
    def test_IM26_legacy_behaviour_matrix_documented(self):
        doc = read("docs", "immutability-and-monitor.md")
        for op in ("| Edit |", "| Delete |", "| Reorder |"):
            self.assertIn(op, doc)
        for s in (LOCKED_TEXT, NI, "SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED", "TS-Unapprove",
                  "SIGNED_DEVIATION_TARGET_HARDENING", "TARGET_TYPED_FEEDBACK_APPROVED"):
            self.assertIn(s, doc)


if __name__ == "__main__":
    unittest.main()
