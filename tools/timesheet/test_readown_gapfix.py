"""OFFLINE-READOWN-GAP-FIX-01 tests RF01-RF24 (synthetic data only; run: python -m unittest).

Every case runs the reference (guard.authorize + entries.read_own) and the generated flow (build_r1_flows.read_own_actions
in the WDL simulator) and requires identical responses. Covers the approved changes: mandatory FromDate + ToDate,
PeriodKey not a request field, coded DIRECTORY_ERROR (caller profile) and INTERNAL_ERROR (mandatory audit) responses.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_r1_read_flow as rr  # noqa: E402  (sets sys.path)
import app_settings as cfg  # noqa: E402
import entries as E  # noqa: E402
import guard as G  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

ME, OTHER = rr.ME, rr.OTHER
OCT = {"FromDate": "2026-10-01", "ToDate": "2026-10-10"}
ITEMS = rr.ITEMS + [rr.item(16, OTHER, "2026-11-02"), rr.item(17, ME, "2026-10-07", "Approved")]
KEYS = ["ok", "code", "messageCode", "correlationId", "rows", "nextAfterId", "pageSize"]
AUDITS = {"Authorization": "Write_Authz_audit", "ReadProxy": "Write_Read_audit"}


def flow(upn, req, *, profile_fail=False, audit_fail=None, query_fail=False, extra=None, cid="run-rf"):
    posts = []

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return ("Failed", {"error": "profile"}) if profile_fail else ("Succeeded", {"userPrincipalName": upn})
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] == "g-emp" else []}
        uri = p.get("parameters/uri", "")
        if p.get("parameters/method") == "GET" and "getbytitle('AppSettings')" in uri:
            return "Succeeded", {"value": rr.SETTINGS}
        if p.get("parameters/method") == "GET" and "getbytitle('TimesheetEntries')" in uri:
            return ("Failed", {"error": "sp"}) if query_fail else ("Succeeded", {"value": rr.sp_query(uri, ITEMS)})
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(uri, {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)})
        if p.get("parameters/method") == "POST":
            if audit_fail and name == AUDITS[audit_fail]:
                return "Failed", {"error": "audit"}
            posts.append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": 1}
        raise AssertionError(name)
    trig = {"text": req.get("FromDate", ""), "text_1": req.get("ToDate", ""), "text_2": str(req.get("AfterId", "")),
            "text_3": str(req.get("PageSize", "")), "text_4": req.get("RequestedOwner", "")}
    trig.update(extra or {})
    run = wdl_sim.Run(trigger_body=trig, run_name=cid, mocks=mocks).run(rr.FLOW)
    done = [n for n in ("Respond", "Respond_error") if run.results.get(n, {}).get("status") == "Succeeded"]
    assert len(done) == 1, done                                     # exactly one response per run
    b = run.results[done[0]]["outputs"]
    return {"ok": b["ok"] == "true", "code": b["resultcode"], "messageCode": b["messagecode"], "correlationId": b["correlationid"],
            "rows": json.loads(b["rows"]), "nextAfterId": int(b["nextafterid"]), "pageSize": int(b["pagesize"])}, posts, run


def ref(upn, req, *, profile_fail=False, audit_fail=None, query_fail=False, cid="run-rf"):
    ident = TrustedIdentity(upn=upn, group_ids=["g-emp"])
    lk = lambda n: [e for e in tg.EMPS if e.account_upn == n]  # noqa: E731
    g = G.authorize(ident, lk, lk, tg.CFG, tg.POLICY, "TS.ViewOwn", "self", correlation_id=cid)
    emp = next((e for e in tg.EMPS if e.account_upn == upn), None)
    caller = E.Caller(upn, emp.item_id, emp.legacy_id, emp.discipline_id) if emp and g.allowed else None
    s = cfg.resolve(rr.REG, rr.OVL, rr.SETTINGS)

    class Store(rr.RefStore):
        def query(self, flt):
            if query_fail:
                raise IOError("sharepoint")
            return super().query(flt)

    def writer(kind):
        if kind == audit_fail:
            raise IOError("audit")
    r = E.read_own(g, caller, req, Store(ITEMS), correlation_id=cid, business_timezone=s["BusinessTimezone"].value,
                   profile_failed=profile_fail, audit_writer=writer)
    return {"ok": r["ok"], "code": r["code"], "messageCode": r.get("messageCode", "MSG_" + r["code"]), "correlationId": cid,
            "rows": r["rows"], "nextAfterId": r["nextAfterId"], "pageSize": r["pageSize"]}


class GapFix(unittest.TestCase):
    def both(self, upn, req, **kw):
        f, posts, run = flow(upn, req, **kw)
        r = ref(upn, req, **{k: v for k, v in kw.items() if k != "extra"})
        self.assertEqual(f, r, "reference vs flow differ for %s %s" % (req, kw))
        self.assertEqual(list(f), KEYS)
        return f, posts, run

    def denied(self, r, code, msg):
        self.assertEqual((r["ok"], r["code"], r["messageCode"], r["rows"], r["nextAfterId"], r["pageSize"]), (False, code, msg, [], 0, 0))

    def test_rf01_to_rf06_mandatory_valid_range(self):
        for req in ({}, {"FromDate": "2026-10-01"}, {"ToDate": "2026-10-10"}, {"FromDate": "2026-10-xx", "ToDate": "2026-10-10"},
                    {"FromDate": "2026-10-01", "ToDate": "10/10/2026"}, {"FromDate": "2026-10-10", "ToDate": "2026-10-01"}):
            r, _, _ = self.both(ME, req)
            self.denied(r, "VALIDATION_DATE", "MSG_VALIDATION_DATE")

    def test_rf07_valid_range_normal(self):
        r, posts, _ = self.both(ME, dict(OCT))
        self.assertEqual((r["ok"], r["code"]), (True, "OK"))
        self.assertEqual([p["EventType"] for p in posts], ["AuthorizationAllow", "ReadProxy"])

    def test_rf08_period_key_not_an_input(self):
        base, _, _ = self.both(ME, dict(OCT))
        f, _, run = flow(ME, dict(OCT), extra={"PeriodKey": "2026-11", "text_10": "2026-11", "text_5": "2026-11"})
        self.assertEqual(f, base)
        self.assertNotIn("PeriodKey", json.dumps(rr.FLOW["If_ok"]["actions"]["Filter"]))
        self.assertNotIn("periodkey", json.dumps(rr.FLOW).lower())
        r = E.read_own(type("G", (), {"allowed": True, "AuthenticatedUpn": ME, "ResultCode": "ALLOW"})(),
                       E.Caller(ME, 11, "E1", "D1"), dict(OCT, PeriodKey="2026-11"), rr.RefStore(ITEMS), correlation_id="c",
                       business_timezone=rr.TZ)
        self.assertIn("PeriodKey", r["ignoredInputs"])
        self.assertEqual([x["id"] for x in r["rows"]], [x["id"] for x in base["rows"]])

    def test_rf09_rf10_profile_failure(self):
        r, posts, _ = self.both(ME, dict(OCT), profile_fail=True)
        self.denied(r, "DIRECTORY_ERROR", "MSG_TEMPORARY_PROBLEM")
        self.assertEqual(r["correlationId"], "run-rf")
        self.assertEqual(posts, [])

    def test_rf11_rf13_rf14_authorization_audit_failure(self):
        r, posts, run = self.both(ME, dict(OCT), audit_fail="Authorization")
        self.denied(r, "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM")
        self.assertNotIn("Query", [k for k, v in run.results.items() if v["status"] == "Succeeded"])  # nothing read

    def test_rf12_rf13_readproxy_audit_failure(self):
        r, posts, run = self.both(ME, dict(OCT), audit_fail="ReadProxy")
        self.denied(r, "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM")
        self.assertEqual(run.results["Query"]["status"], "Succeeded")          # rows were read but are discarded
        self.assertEqual(run.results["Respond"]["status"], "Skipped")

    def test_rf15_query_failure_remains_error(self):
        r, _, _ = self.both(ME, dict(OCT), query_fail=True)
        self.denied(r, "ERROR", "MSG_ERROR")

    def test_rf16_key_set_on_every_handled_path(self):
        cases = [(ME, dict(OCT), {}), (ME, {}, {}), (tg.u("nobody"), dict(OCT), {}), (ME, dict(OCT, RequestedOwner=OTHER), {}),
                 (ME, dict(OCT), {"profile_fail": True}), (ME, dict(OCT), {"audit_fail": "ReadProxy"}),
                 (ME, dict(OCT), {"audit_fail": "Authorization"}), (ME, dict(OCT), {"query_fail": True})]
        codes = set()
        for upn, req, kw in cases:
            r, _, _ = self.both(upn, req, **kw)
            self.assertEqual(list(r), KEYS)
            codes.add(r["code"])
        self.assertEqual(codes, {"OK", "VALIDATION_DATE", "UNMAPPED_IDENTITY", "FORBIDDEN", "DIRECTORY_ERROR", "INTERNAL_ERROR", "ERROR"})
        self.assertEqual(list(rr.FLOW["Respond_error"]["inputs"]["body"]), list(rr.FLOW["Respond"]["inputs"]["body"]))

    def test_rf17_owner_filter_unchanged(self):
        filt = rr.FLOW["If_ok"]["actions"]["Filter"]["inputs"]
        self.assertTrue(filt.startswith("@concat('OwnerUpn eq '''"))
        self.assertIn("outputs('Trusted')", filt)

    def test_rf18_rf19_foreign_and_deleted_excluded(self):
        r, _, _ = self.both(ME, dict(OCT))
        ids = [x["id"] for x in r["rows"]]
        self.assertNotIn(11, ids)
        self.assertNotIn(12, ids)
        self.assertIn(17, ids)
        self.assertIn("EntryStatus ne ''Deleted''", rr.FLOW["If_ok"]["actions"]["Filter"]["inputs"])

    def test_rf20_keyset_paging(self):
        seen, after = [], 0
        for _ in range(10):
            r, _, _ = self.both(ME, dict(OCT, PageSize=3, AfterId=after))
            seen += [x["id"] for x in r["rows"]]
            after = r["nextAfterId"]
            if not after:
                break
        full, _, _ = self.both(ME, dict(OCT))
        self.assertEqual(seen, [x["id"] for x in full["rows"]])

    def test_rf22_canvas_sends_both_dates(self):
        with open(os.path.join(HERE, "..", "powerapp", "demo-r1", "scrMyTimesheets.pa.yaml"), encoding="utf-8") as f:
            calls = re.findall(r"'TS-ReadOwn'\.Run\(([^;]+)\);", f.read())
        self.assertTrue(calls)
        self.assertTrue(all(c.startswith('Text(varFrom, "yyyy-mm-dd"), Text(varTo, "yyyy-mm-dd")') for c in calls))

    def test_rf24_offline_only(self):
        with open(os.path.join(HERE, "entries.py"), encoding="utf-8") as f:
            self.assertIsNone(re.search(r"\b(urllib|requests|http\.client|socket)\b", f.read()))


if __name__ == "__main__":
    unittest.main()
