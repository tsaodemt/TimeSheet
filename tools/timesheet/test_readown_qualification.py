"""OFFLINE-READOWN-QUALIFICATION-01 tests RQ01-RQ20 (synthetic data only; run: python -m unittest).

Pins the CURRENT TS-ReadOwn contract on the reference (entries.read_own after guard.authorize) and the generated flow
(build_r1_flows.read_own_actions in the WDL simulator), reusing test_r1_read_flow's harness. Open decisions recorded in
docs/auditlog-open-decisions.md were resolved by OFFLINE-READOWN-GAP-FIX-01 (mandatory date range; coded
DIRECTORY_ERROR / INTERNAL_ERROR responses) and are asserted in RQ07, RQ15, RQ16.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_r1_read_flow as rr  # noqa: E402  (sets sys.path for the flow / identity modules)
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402

ME, OTHER = rr.ME, rr.OTHER
OCT = {"FromDate": "2026-10-01", "ToDate": "2026-10-10"}
ITEMS = rr.ITEMS + [rr.item(16, OTHER, "2026-11-02"), rr.item(17, ME, "2026-10-07", "Approved")]
FLOW_JSON = json.dumps(rr.FLOW)
KEYS = ["ok", "code", "messageCode", "correlationId", "rows", "nextAfterId", "pageSize"]


def _host(a):
    i = a.get("inputs")
    return i.get("host", {}) if isinstance(i, dict) else {}


def _walk(actions):
    for a in actions.values():
        yield a
        if isinstance(a.get("actions"), dict):
            yield from _walk(a["actions"])
        if isinstance(a.get("else"), dict) and isinstance(a["else"].get("actions"), dict):
            yield from _walk(a["else"]["actions"])


def run_custom(mock_override, req=OCT, upn=ME):
    """Run the flow with one action's mock replaced; returns the run (no Respond assertion)."""
    member_of = {"g-emp"}

    def mocks(name, a, p):
        hit = mock_override(name, a, p)
        if hit is not None:
            return hit
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        uri = p.get("parameters/uri", "")
        if p.get("parameters/method") == "GET" and "getbytitle('AppSettings')" in uri:
            return "Succeeded", {"value": rr.SETTINGS}
        if p.get("parameters/method") == "GET" and "getbytitle('TimesheetEntries')" in uri:
            return "Succeeded", {"value": rr.sp_query(uri, ITEMS)}
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(uri, {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)})
        if p.get("parameters/method") == "POST":
            return "Succeeded", {"Id": 1}
        raise AssertionError(name)
    trig = {"text": req.get("FromDate", ""), "text_1": req.get("ToDate", ""), "text_2": "", "text_3": "", "text_4": ""}
    run = wdl_sim.Run(trigger_body=trig, run_name="run-rq", mocks=mocks)
    try:
        run.run(rr.FLOW)
    except wdl_sim.WdlError:  # an expression over a failed/skipped upstream: the action (and run) fails in Power Automate
        run.aborted = True
    return run


_HARNESS = rr.R1Read("test_RR01_valid_own_read")  # reference-vs-flow comparison from test_r1_read_flow


class ReadOwnQualification(unittest.TestCase):
    def both(self, upn, req, **kw):
        return _HARNESS.both(upn, req, **kw)

    def ids(self, res):
        return [x["id"] for x in res["rows"]]

    def test_rq01_identity_from_invoker_profile_only(self):
        prof = [_host(a) for a in _walk(rr.FLOW) if _host(a).get("operationId") == "MyProfile_V2"]
        self.assertEqual(len(prof), 1)
        self.assertEqual(prof[0]["connectionReferenceLogicalName"], "<PFX>_CR_O365Users_Invoker")
        for name in ("Trusted", "Caller_lookup", "IdCode"):
            self.assertNotRegex(json.dumps(rr.FLOW[name]), r"trigger(Body|Outputs)", name)

    def test_rq02_client_owner_employeeid_lookup_decoys_ignored(self):
        other = next(e for e in tg.EMPS if e.account_upn == OTHER)
        decoys = {"OwnerUpn": OTHER, "EmployeeId": str(other.item_id), "ActorUpn": OTHER, "Role": "APR", "Scope": "company"}
        r, _, _ = self.both(ME, dict(OCT), items=ITEMS, decoys=decoys)
        self.assertTrue(r["ok"])
        self.assertNotIn(11, self.ids(r))
        # The trigger has no employee-item-id / Employee-lookup input; the query filter reads only the trusted UPN,
        # the validated dates and AfterId.
        filt = json.dumps(rr.FLOW["If_ok"]["actions"]["Filter"])
        self.assertNotRegex(filt, r"text_[4-9]")
        self.assertIn("outputs('Trusted')", filt)

    def test_rq03_requested_foreign_owner_refused(self):
        r, _, _ = self.both(ME, dict(OCT, RequestedOwner=OTHER), items=ITEMS)
        self.assertEqual((r["ok"], r["code"], r["rows"]), (False, "FORBIDDEN", []))

    def test_rq04_identity_failures_fail_closed(self):
        for upn, code in ((tg.u("nobody"), "UNMAPPED_IDENTITY"), (tg.u("twin"), "DUPLICATE_IDENTITY"),
                          (tg.u("gone"), "INACTIVE_EMPLOYEE"), ("not-an-upn", "INVALID_IDENTITY")):
            r, _, _ = self.both(upn, dict(OCT), items=ITEMS)
            self.assertEqual((r["ok"], r["code"], r["rows"], r["nextAfterId"]), (False, code, [], 0), upn)

    def test_rq05_period_ownership_matrix(self):
        r, _, _ = self.both(ME, dict(OCT), items=ITEMS)
        got = set(self.ids(r))
        self.assertTrue({1, 5, 10, 17} <= got)          # own in period (Draft and Approved)
        self.assertNotIn(11, got)                       # foreign in period
        self.assertFalse({13, 14, 15} & got)            # own out of period
        self.assertNotIn(16, got)                       # foreign out of period
        self.assertNotIn(12, got)                       # own Deleted

    def test_rq06_server_side_owner_filter_first(self):
        filt = rr.FLOW["If_ok"]["actions"]["Filter"]["inputs"]
        self.assertTrue(filt.startswith("@concat('OwnerUpn eq '''"))
        self.assertIn("EntryStatus ne ''Deleted''", filt)
        self.assertIn("ERROR_LEAK", rr.FLOW["Final_code"]["inputs"])   # defence in depth after the server filter

    def test_rq07_undated_read_rejected(self):
        # RO15 (OFFLINE-READOWN-GAP-FIX-01): FromDate + ToDate are mandatory; no maximum span is defined.
        r, _, _ = self.both(ME, {}, items=ITEMS)
        self.assertEqual((r["ok"], r["code"], r["rows"], r["pageSize"]), (False, "VALIDATION_DATE", [], 0))

    def test_rq08_invalid_period_rejected(self):
        for req in ({"FromDate": "2026-10-10", "ToDate": "2026-10-01"}, {"FromDate": "2026-10-01"}, {"ToDate": "2026-10-01"},
                    {"FromDate": "2026-13-01", "ToDate": "2026-13-02"}, {"FromDate": "01/10/2026", "ToDate": "02/10/2026"}):
            r, _, _ = self.both(ME, req, items=ITEMS)
            self.assertEqual((r["ok"], r["code"], r["rows"]), (False, "VALIDATION_DATE", []), req)

    def test_rq09_vietnam_business_dates(self):
        # A business date is stored as local midnight in UTC (POC P4); the range is the half-open local interval.
        r, _, _ = self.both(ME, {"FromDate": "2026-10-01", "ToDate": "2026-10-01"}, items=ITEMS)
        self.assertEqual([x["workDate"] for x in r["rows"]], ["2026-10-01"])

    def test_rq10_status_filter(self):
        r, _, _ = self.both(ME, dict(OCT), items=ITEMS)
        self.assertEqual({x["status"] for x in r["rows"]}, {"Draft", "Approved"})

    def test_rq11_empty_own_result(self):
        r, _, _ = self.both(ME, {"FromDate": "2027-01-01", "ToDate": "2027-01-31"}, items=ITEMS)
        self.assertEqual((r["ok"], r["code"], r["rows"], r["nextAfterId"]), (True, "OK", [], 0))

    def test_rq12_keyset_paging_complete(self):
        seen, after = [], 0
        for _ in range(10):
            r, _, _ = self.both(ME, dict(OCT, PageSize=3, AfterId=after), items=ITEMS)
            seen += self.ids(r)
            after = r["nextAfterId"]
            if not after:
                break
        full, _, _ = self.both(ME, dict(OCT), items=ITEMS)
        self.assertEqual(seen, self.ids(full))                     # no row lost or repeated across pages
        self.assertIn("$orderby=Id asc", FLOW_JSON)

    def test_rq13_service_connection_for_entries(self):
        sp = [_host(a) for a in _walk(rr.FLOW) if _host(a).get("operationId") == "HttpRequest"]
        self.assertTrue(sp)
        self.assertTrue(all(h["connectionReferenceLogicalName"] == "<PFX>_CR_SharePoint_OpsService" for h in sp))

    def test_rq14_query_failure_coded(self):
        run = run_custom(lambda n, a, p: ("Failed", {"error": "x"}) if "getbytitle('TimesheetEntries')" in p.get("parameters/uri", "")
                         and p.get("parameters/method") == "GET" else None)
        out = run.results["Respond"]["outputs"]
        self.assertEqual((out["ok"], out["resultcode"], out["rows"]), ("false", "ERROR", "[]"))

        class Boom(rr.RefStore):
            def query(self, flt):
                raise IOError("sharepoint")
        import entries as E
        g = type("G", (), {"allowed": True, "AuthenticatedUpn": ME, "ResultCode": "ALLOW"})()
        r = E.read_own(g, E.Caller(ME, 11, "E1", "D1"), dict(OCT), Boom([]), correlation_id="c", business_timezone=rr.TZ)
        self.assertEqual((r["ok"], r["code"], r["rows"]), (False, "ERROR", []))

    def test_rq15_audit_failure_coded_no_data(self):
        # RO23 / RO24: a failed mandatory audit append ends in a coded INTERNAL_ERROR response with no rows.
        for audit in ("Write_Authz_audit", "Write_Read_audit"):
            run = run_custom(lambda n, a, p, audit=audit: ("Failed", {"error": "x"}) if n == audit else None)
            self.assertFalse(getattr(run, "aborted", False))
            self.assertEqual(run.results["Respond"]["status"], "Skipped", audit)
            out = run.results["Respond_error"]["outputs"]
            self.assertEqual((out["ok"], out["resultcode"], out["messagecode"], out["rows"], out["nextafterid"], out["pagesize"]),
                             ("false", "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM", "[]", "0", "0"), audit)

    def test_rq16_profile_failure_coded_no_data(self):
        run = run_custom(lambda n, a, p: ("Failed", {"error": "x"}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None)
        out = run.results["Respond_error"]["outputs"]
        self.assertEqual((out["ok"], out["resultcode"], out["messagecode"], out["rows"]), ("false", "DIRECTORY_ERROR", "MSG_TEMPORARY_PROBLEM", "[]"))
        self.assertNotIn("Query", [k for k, v in run.results.items() if v["status"] == "Succeeded"])

    def test_rq17_response_shape_fixed(self):
        for upn, req in ((ME, dict(OCT)), (tg.u("nobody"), dict(OCT)), (ME, {"FromDate": "x", "ToDate": "y"})):
            r, _, _ = self.both(upn, req, items=ITEMS)
            self.assertEqual(list(r), KEYS)
        self.assertEqual(sorted(rr.FLOW["Respond"]["inputs"]["body"]),
                         sorted(["ok", "resultcode", "messagecode", "correlationid", "rows", "nextafterid", "pagesize"]))
        row_keys = sorted(rr.FLOW["Out_rows"]["inputs"]["select"])
        self.assertEqual(row_keys, sorted(["id", "workDate", "projectId", "phaseId", "workTypeId", "shiftId", "hourTypeId", "hours",
                                           "remark", "status", "etag"]))

    def test_rq18_no_dataverse_default_production(self):
        low = FLOW_JSON.lower()
        for bad in ("commondataservice", "dataverse", "default-", "/environments/"):
            self.assertNotIn(bad, low)

    def test_rq19_canvas_pages_with_bounded_range(self):
        with open(os.path.join(HERE, "..", "powerapp", "demo-r1", "scrMyTimesheets.pa.yaml"), encoding="utf-8") as f:
            src = f.read()
        calls = re.findall(r"'TS-ReadOwn'\.Run\(([^;]+)\);", src)
        self.assertTrue(calls)
        self.assertTrue(all(c.startswith("Text(varFrom") and "Text(varTo" in c for c in calls))  # always a date range
        self.assertIn("varRead.nextafterid", src)

    def test_rq20_message_code_convention(self):
        r, _, _ = self.both(tg.u("nobody"), dict(OCT), items=ITEMS)
        self.assertEqual(r["messageCode"], "MSG_UNMAPPED_IDENTITY")


if __name__ == "__main__":
    unittest.main()
