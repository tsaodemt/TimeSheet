"""OFFLINE-SAVEENTRY-QUALIFICATION-01 tests SQ01-SQ25 (synthetic data only; run: python -m unittest).

Pins the CURRENT TS-SaveEntry contract on the reference (guard.authorize + entries.save_entry + finalize_audit) and the
generated flow (build_r1_flows.save_draft_actions in the WDL simulator), reusing test_r1_save_flow's harness, for the
qualification points not already asserted by RS01-RS25, ET01-ET07, FG01-FG05 and AF01-AF08. Open decisions are
resolved by SAVEENTRY-FINALIZE-AND-R1-OFFLINE-READINESS (non-idempotent create accepted for R1; coded pre-write
failures) and asserted in SQ09, SQ10, SQ12.
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_r1_save_flow as t  # noqa: E402  (sets sys.path)
import entries as E  # noqa: E402
import wdl_sim  # noqa: E402

ME, OTHER = t.ME, t.OTHER
_Run = wdl_sim.Run
FLOW_JSON = json.dumps(t.FLOW)


def run_hooked(hook, upn=ME, request=None, items=None):
    """Run the flow with `hook(name, action, params) -> (status, body) | None` in front of the harness mocks.
    Returns (response or None, writes, posts, run); an expression error over skipped inputs aborts the simulated run
    (in Power Automate that action fails), recorded as run.aborted."""
    holder = {}

    class HookRun:
        def __init__(self, trigger_body, run_name, mocks):
            self.inner = _Run(trigger_body=trigger_body, run_name=run_name,
                              mocks=lambda n, a, p: hook(n, a, p) or mocks(n, a, p))
            holder["run"] = self.inner

        def run(self, flow):
            try:
                self.inner.run(flow)
            except (wdl_sim.WdlError, TypeError, KeyError, ValueError):
                self.inner.aborted = True
            return self.inner
    store = t.Store(items or t.ITEMS)
    with mock.patch.object(t.wdl_sim, "Run", HookRun):
        try:
            resp, posts, writes, run = t.run_flow(upn, request or t.req(), store, t.SCOPING_OFF)
        except (KeyError, TypeError):  # Respond skipped: read the pre-write failure response instead
            run = holder["run"]
            b = (run.results.get("Respond_error") or {}).get("outputs")
            resp = None if b is None else {
                "ok": b["ok"] == "true", "code": b["resultcode"], "messageCode": b["messagecode"], "itemId": int(b["itemid"]),
                "etag": b["etag"], "correlationId": b["correlationid"], "warnings": json.loads(b["warnings"]),
                "interim": json.loads(b["interim"]), "auditStatus": b["auditstatus"]}
    sp_writes = [n for n, v in run.results.items() if n in ("Create", "Update") and v["status"] == "Succeeded"]
    return resp, sp_writes, store, run


class SaveQualification(t._Both):
    def test_sq01_identity_from_invoker_profile_only(self):
        hosts = [a["inputs"]["host"] for a in _walk(t.FLOW) if isinstance(a.get("inputs"), dict) and "host" in a["inputs"]]
        prof = [h for h in hosts if h.get("operationId") == "MyProfile_V2"]
        self.assertEqual(len(prof), 1)
        self.assertEqual(prof[0]["connectionReferenceLogicalName"], "<PFX>_CR_O365Users_Invoker")
        sp = [h for h in hosts if h.get("operationId") == "HttpRequest"]
        self.assertTrue(sp and all(h["connectionReferenceLogicalName"] == "<PFX>_CR_SharePoint_OpsService" for h in sp))

    def test_sq02_server_owned_fields_never_from_request(self):
        # Payload values for the ownership / identity columns are trusted expressions, never trigger inputs.
        pc = t.FLOW["If_write"]["actions"]["Payload_create"]["inputs"]
        for k in ("OwnerUpn", "ActorUpn", "EmployeeId", "EmployeeItemId", "DisciplineCode", "PeriodKey", "LegacyId",
                  "LegacyOrigin", "EntryStatus", "CorrelationId", "IsOnBehalf"):
            self.assertNotRegex(json.dumps(pc[k]), r"trigger(Body|Outputs)", k)
        self.assertEqual((pc["OwnerUpn"], pc["EmployeeItemId"], pc["DisciplineCode"], pc["LegacyId"], pc["EntryStatus"]),
                         ("@{outputs('Trusted')}", "@outputs('Guard_result')?['EmployeeId']", "@{outputs('CallerDisc')}",
                          "@{guid()}", "Draft"))
        pe = t.FLOW["If_write"]["actions"]["Payload_edit"]["inputs"]
        for k in ("OwnerUpn", "EmployeeId", "EmployeeItemId", "LegacyId", "EntryStatus", "LegacyOrigin"):
            self.assertNotIn(k, pe)                                        # an edit never rewrites them

    def test_sq03_forged_fields_in_reference_are_ignored(self):
        st = t.Store(t.ITEMS)
        forged = dict(t.req(), OwnerUpn=OTHER, EmployeeItemId=12, Employee=12, EmployeeId=12, ActorUpn=OTHER, CallerUpn=OTHER,
                      DisciplineCode="D2", LegacyId="LEGACY-OTHER", PeriodKey="1999-01", EntryStatus="Approved", Author=OTHER)
        f, rr = t.ref(ME, {k: v for k, v in forged.items()}, st, t.SCOPING_OFF)
        self.assertTrue(f["ok"])
        row = st.items[f["itemId"]]
        self.assertEqual((row["OwnerUpn"], row["EmployeeItemId"], row["DisciplineCode"], row["EntryStatus"]),
                         (ME, t.ME_EMP.item_id, t.ME_EMP.discipline_id, "Draft"))
        self.assertNotEqual(row["LegacyId"], "LEGACY-OTHER")
        self.assertEqual(row["PeriodKey"], E.period_key(__import__("datetime").date(2026, 10, 9), 26))
        self.assertLessEqual({"OwnerUpn", "EmployeeItemId", "Employee", "EmployeeId", "ActorUpn", "CallerUpn", "DisciplineCode",
                              "LegacyId", "PeriodKey", "EntryStatus", "Author"}, set(rr.ignoredInputs))
        self.assertNotIn("Author", row)                                  # SharePoint metadata, never written by the flow

    def test_sq04_foreign_row_with_forged_self_claims_denied(self):
        decoys = {"OwnerUpn": ME, "EmployeeId": str(t.ME_EMP.item_id), "ActorUpn": ME}
        f = self.both(ME, t.req(ItemId="2", ETag='"2,1"'), decoys=decoys)
        self.assertEqual((f["ok"], f["code"]), (False, "FORBIDDEN"))
        self.nothing_written()

    def test_sq05_missing_etag_on_edit_is_conflict_without_write(self):
        f = self.both(ME, t.req(ItemId="1", ETag=""))
        self.assertEqual((f["ok"], f["code"]), (False, "CONFLICT"))
        self.nothing_written()

    def test_sq06_no_wildcard_and_single_conditional_update(self):
        updates = [a for a in _walk(t.FLOW) if json.dumps(a).count("X-HTTP-Method") and a.get("type") in ("OpenApiConnection",)]
        self.assertEqual(len(updates), 1)
        h = updates[0]["inputs"]["parameters"]["parameters/headers"]
        self.assertEqual(h["X-HTTP-Method"], "MERGE")
        self.assertNotIn("*", h["IF-MATCH"])
        self.assertIn("Get_item", h["IF-MATCH"])                        # the stored ETag the client's ETag was checked against
        self.assertNotIn('"*"', FLOW_JSON)
        self.assertNotRegex(FLOW_JSON, r"retryPolicy")

    def test_sq07_create_write_failure_is_error_without_row(self):
        hook = lambda n, a, p: ("Failed", {"statusCode": 500}) if n == "Create" else None  # noqa: E731
        resp, writes, store, _ = run_hooked(hook)
        self.assertEqual((resp["ok"], resp["code"], resp["itemId"], resp["etag"]), (False, "ERROR", 0, ""))
        self.assertEqual(len(store.items), len(t.ITEMS))

    def test_sq08_update_write_failure_non_412_is_error(self):
        hook = lambda n, a, p: ("Failed", {"statusCode": 500}) if n == "Update" else None  # noqa: E731
        resp, _, store, _ = run_hooked(hook, request=t.req(ItemId="1", ETag='"1,1"'))
        self.assertEqual((resp["ok"], resp["code"]), (False, "ERROR"))
        self.assertEqual(store.items[1]["Hours"], 2.0)

    def test_sq09_decision_audit_failure_coded_without_write(self):
        # SE37 (SAVEENTRY-FINALIZE): the mandatory pre-write permission audit failed -> INTERNAL_ERROR, nothing written.
        hook = lambda n, a, p: ("Failed", {"statusCode": 400}) if n == "Write_Authz_audit" else None  # noqa: E731
        resp, writes, store, run = run_hooked(hook)
        self.assertFalse(getattr(run, "aborted", False))
        self.assertEqual(writes, [])
        self.assertEqual(len(store.items), len(t.ITEMS))
        self.assertEqual((resp["ok"], resp["code"], resp["messageCode"], resp["itemId"], resp["etag"], resp["warnings"]),
                         (False, "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM", 0, "", []))
        self.assertEqual(t.FLOW["If_write"]["expression"], {"equals": ["@outputs('Valid')", "OK"]})

    def test_sq10_profile_failure_coded_without_write(self):
        hook = lambda n, a, p: ("Failed", {"statusCode": 500}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None  # noqa: E731
        resp, writes, store, run = run_hooked(hook)
        self.assertFalse(getattr(run, "aborted", False))
        self.assertEqual(writes, [])
        self.assertEqual((resp["ok"], resp["code"], resp["messageCode"]), (False, "DIRECTORY_ERROR", "MSG_TEMPORARY_PROBLEM"))

    def test_sq11_post_write_audit_failure_is_aud_f1_option_b(self):
        f = self.both(ME, t.req(), fail_audit="WriteProxy")
        self.assertEqual((f["ok"], f["code"], f["auditStatus"]), (True, "OK", "AUDIT_DEGRADED"))
        self.assertIn("AUDIT_DEGRADED", f["warnings"])
        run = self.ctx["run"]
        self.assertEqual(run.results["Alert_audit_degraded"]["status"], "Succeeded")  # run ends Failed for monitoring

    def test_sq12_create_retry_duplicates_with_warning(self):
        # R1-Q3 OPEN: no create idempotency; a repeated create makes a second row and WARN_DUPLICATE shows it.
        st = t.Store(t.ITEMS)
        a, _ = t.ref(ME, t.req(), st, t.SCOPING_OFF)
        b, _ = t.ref(ME, t.req(), st, t.SCOPING_OFF)
        self.assertNotEqual(a["itemId"], b["itemId"])
        self.assertIn("WARN_DUPLICATE", b["warnings"])
        self.assertNotEqual(st.items[a["itemId"]]["LegacyId"], st.items[b["itemId"]]["LegacyId"])
        with self.assertRaises(ValueError):
            t.build(idempotency="request-key")

    def test_sq13_edit_keeps_legacy_id_and_owner(self):
        st_before = t.Store(t.ITEMS).items[1].get("LegacyId")
        f = self.both(ME, t.req(ItemId="1", ETag='"1,1"', Hours="3"))
        self.assertTrue(f["ok"])
        row = self.ctx["store"].items[1]
        self.assertEqual((row.get("LegacyId"), row["OwnerUpn"], row["EntryStatus"]), (st_before, ME, "Draft"))
        self.assertNotIn("LegacyId", self.ctx["writes"][0][2])

    def test_sq14_status_contract(self):
        self.assertEqual(self.code(t.req(ItemId="3", ETag='"3,1"')), "LOCKED")          # Approved not editable
        self.assertEqual(self.code(t.req(ItemId="4", ETag='"4,1"')), "NOT_FOUND")       # Deleted
        f = self.both(ME, t.req(), decoys={"EntryStatus": "Approved"})
        self.assertEqual(self.ctx["store"].items[f["itemId"]]["EntryStatus"], "Draft")  # create is always Draft
        self.assertNotIn("DELETE", FLOW_JSON.replace("'Deleted'", ""))                  # no delete operation

    def test_sq15_hours_contract(self):
        for h, code in (("0", "VALIDATION_HOURS"), ("-1", "VALIDATION_HOURS"), ("24.5", "VALIDATION_HOURS"),
                        ("x", "VALIDATION_HOURS"), ("", "VALIDATION_HOURS"), ("1.5", "OK"), ("24", "OK")):
            self.assertEqual(self.code(t.req(Hours=h)), code, h)

    def test_sq16_warnings_nonblocking_and_caller_scoped(self):
        f = self.both(ME, t.req(WorkDate="2026-10-08", Hours="5"))
        self.assertTrue(f["ok"])
        self.assertLessEqual({"WARN_HOURS_ENTRY", "WARN_HOURS_DAY"}, set(f["warnings"]))
        day = t.FLOW["If_write"]["actions"]["Day_filter"]["inputs"]
        self.assertTrue(day.startswith("@concat('OwnerUpn eq '''"))
        f2 = self.both(OTHER, t.req(WorkDate="2026-10-08", Hours="5"))        # ME's 11h that day must not count for OTHER
        self.assertNotIn("WARN_HOURS_DAY", f2["warnings"])

    def test_sq17_business_date_and_period_key(self):
        f = self.both(ME, t.req(WorkDate="2026-10-26"))
        row = self.ctx["store"].items[f["itemId"]]
        self.assertEqual(row["WorkDate"], "2026-10-25T17:00:00Z")              # local midnight UTC+07
        self.assertEqual(row["PeriodKey"], "2026-11")                           # on/after start day 26 -> next period
        for bad in ("2026-02-30", "26/10/2026", "2026-10-26T00:00:00Z", ""):
            self.assertEqual(self.code(t.req(WorkDate=bad)), "VALIDATION_DATE", bad)

    def test_sq18_lookup_and_project_phase(self):
        self.assertEqual(self.code(t.req(ProjectCode="NOPE")), "VALIDATION_LOOKUP")
        self.assertEqual(self.code(t.req(ProjectCode="P3", PhaseCode="PH1")), "VALIDATION_LOOKUP")  # phase not of project
        self.assertTrue(self.both(ME, t.req())["ok"])

    def test_sq19_denied_and_invalid_write_nothing(self):
        for upn, request in ((t.tg.u("nobody"), t.req()), (ME, t.req(Hours="0")), (ME, t.req(ItemId="1", ETag='"1,9"'))):
            self.both(upn, request)
            self.nothing_written()

    def test_sq20_response_shape(self):
        keys = ["ok", "resultcode", "messagecode", "itemid", "etag", "correlationid", "warnings", "interim", "auditstatus"]
        self.assertEqual(list(t.FLOW["Respond"]["inputs"]["body"]), keys)
        for request in (t.req(), t.req(Hours="0"), t.req(ItemId="2", ETag='"2,1"')):
            f = self.both(ME, request)
            self.assertEqual(list(f), ["ok", "code", "messageCode", "itemId", "etag", "correlationId", "warnings", "interim",
                                       "auditStatus"])

    def test_sq21_no_dataverse_default_production(self):
        low = FLOW_JSON.lower()
        for bad in ("commondataservice", "dataverse", "default-", "/environments/"):
            self.assertNotIn(bad, low)

    def test_sq22_canvas_consumer_uses_flow_only(self):
        with open(os.path.join(HERE, "..", "powerapp", "demo-r1", "scrEntry.pa.yaml"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("'TS-SaveEntry'.Run(", src)
        self.assertNotRegex(src, r"Patch\(|SubmitForm\(|TimesheetEntries")       # no direct list write from the app

    def test_sq25_retry_with_stale_etag_after_successful_update(self):
        # Case E: the first update succeeded (new ETag); a retry with the old ETag is a CONFLICT, nothing written.
        st = t.Store(t.ITEMS)
        a, _ = t.ref(ME, t.req(ItemId="1", ETag='"1,1"', Hours="3"), st, t.SCOPING_OFF)
        before = dict(st.items[1])
        b, _ = t.ref(ME, t.req(ItemId="1", ETag='"1,1"', Hours="4"), st, t.SCOPING_OFF)
        self.assertEqual((a["code"], b["code"]), ("OK", "CONFLICT"))
        self.assertEqual(st.items[1], before)

    def test_sq23_conflict_exposes_no_foreign_data(self):
        f = self.both(ME, t.req(ItemId="1", ETag='"1,9"'))
        self.assertEqual((f["code"], f["etag"], f["warnings"]), ("CONFLICT", "", []))

    def test_sq24_messagecode_convention(self):
        self.assertEqual(self.both(ME, t.req(Hours="0"))["messageCode"], "MSG_VALIDATION_HOURS")


def _walk(actions):
    for a in actions.values():
        yield a
        if isinstance(a.get("actions"), dict):
            yield from _walk(a["actions"])
        if isinstance(a.get("else"), dict) and isinstance(a["else"].get("actions"), dict):
            yield from _walk(a["else"]["actions"])


if __name__ == "__main__":
    unittest.main()
