"""R1-LIVE-BLOCKER-FIX-01 tests BF01-BF15 (synthetic data only; run: python -m unittest).

Live STAGING L01 (2026-10-08) found two runtime differences the simulator did not model:
- `createArray()` without parameters is rejected by Power Automate (InvalidTemplate). The guard's `Caller_rows` used it as
  the empty fallback after a failed Employees lookup, so the run skipped everything and the error responder answered
  INTERNAL_ERROR instead of the contract's DIRECTORY_ERROR. Generated flows now use `json('[]')`; the simulator raises.
- The classic designer drops properties whose value is "" on paste, so error responses lost canonical keys
  (employeecode, configstatus, missing, etag, auditstatus). Generated flows now write such values as `@{<empty expr>}`.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "config")]
import test_readown_qualification as rq  # noqa: E402  (sets sys.path for the flow / identity modules)
import test_saveentry_qualification as sq  # noqa: E402
import test_appstart as ta  # noqa: E402
import test_appstart_qualification as aq  # noqa: E402
import test_guard as tg  # noqa: E402
import build_read_flow as base  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

APP_KEYS = ["ok", "resultcode", "messagecode", "correlationid", "employeecode", "configstatus", "config", "interim", "missing"]
READ_KEYS = ["ok", "resultcode", "messagecode", "correlationid", "rows", "nextafterid", "pagesize"]
SAVE_KEYS = ["ok", "resultcode", "messagecode", "itemid", "etag", "correlationid", "warnings", "interim", "auditstatus"]
FLOWS = {"TS-AppOpen": ta.FLOW, "TS-ReadOwn": rq.rr.FLOW, "TS-SaveEntry": sq.t.FLOW}


def _strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    elif isinstance(x, str):
        yield x


def _is_lookup(p):
    return p.get("parameters/method") == "GET" and "getbytitle('%s')" % tg.EMP_LIST in p.get("parameters/uri", "")


def appstart_run(lookup_fails=False, profile_fails=False, upn=None):
    upn = upn or tg.u("emp")
    audit = []
    lists = {tg.EMP_LIST: tg.lookup_rows(tg.EMPS)}

    def mocks(name, a, p):
        if a["inputs"]["host"]["operationId"] == "MyProfile_V2":
            return ("Failed", {"error": "x"}) if profile_fails else ("Succeeded", {"userPrincipalName": upn})
        if lookup_fails and _is_lookup(p):
            return "Failed", {"status": 403, "message": "Access is denied."}
        if p.get("parameters/method") == "GET" and "getbytitle('AppSettings')" in p["parameters/uri"]:
            return "Succeeded", {"value": ta.ROWS}
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], lists)
        if p.get("parameters/method") == "POST":
            audit.append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": 1}
        raise AssertionError(name)
    trig = dict({"text": "Teams"}, **{"text_%d" % (i + 1): "" for i in range(len(ta.UNTRUSTED))})
    run = wdl_sim.Run(trigger_body=trig, run_name="run-bf", mocks=mocks, now=ta.NOW).run(ta.FLOW)
    return run, audit


def answered(run):
    """The one response the caller receives: (action name, body)."""
    hits = [(n, run.results[n]["outputs"]) for n in ("Respond", "Respond_error") if run.results.get(n, {}).get("status") == "Succeeded"]
    assert len(hits) == 1, hits
    return hits[0]


class LiveFixes(unittest.TestCase):
    def test_BF01_employees_lookup_failure_is_directory_error(self):
        run, audit = appstart_run(lookup_fails=True)
        name, body = answered(run)
        self.assertEqual((name, body["ok"], body["resultcode"], body["messagecode"]), ("Respond", "false", "DIRECTORY_ERROR", "MSG_TEMPORARY_PROBLEM"))
        self.assertEqual(run.results["Caller_rows"]["status"], "Succeeded")
        self.assertEqual([(r["EventType"], r["Decision"], r["ResultCode"]) for r in audit], [("IdentityRejected", "DENY", "DIRECTORY_ERROR")])
        # ReadOwn / SaveEntry guard: the same lookup failure is coded DIRECTORY_ERROR too, with no data and no write
        r = rq.run_custom(lambda n, a, p: ("Failed", {"status": 403}) if _is_lookup(p) else None)
        self.assertEqual(answered(r)[1]["resultcode"], "DIRECTORY_ERROR")
        resp, writes, _, _ = sq.run_hooked(lambda n, a, p: ("Failed", {"status": 403}) if _is_lookup(p) else None)
        self.assertEqual((resp["code"], resp["itemId"], resp["etag"], writes), ("DIRECTORY_ERROR", 0, "", []))

    def test_BF02_employees_lookup_failure_is_not_internal_error(self):
        _, body = answered(appstart_run(lookup_fails=True)[0])
        self.assertNotEqual(body["resultcode"], "INTERNAL_ERROR")
        self.assertEqual((body["employeecode"], body["config"]), ("", "{}"))

    def test_BF03_appstart_error_response_keeps_every_canonical_key(self):
        for kw in ({"profile_fails": True}, {"lookup_fails": True}):
            _, body = answered(appstart_run(**kw)[0])
            self.assertEqual(list(body), APP_KEYS, kw)
        self.assertEqual(list(ta.FLOW["Respond_error"]["inputs"]["body"]), APP_KEYS)

    def test_BF04_empty_employeecode_survives_generation(self):
        b = ta.FLOW["Respond_error"]["inputs"]["body"]
        self.assertEqual(b["employeecode"], base.EMPTY_VALUE)
        self.assertEqual(answered(appstart_run(profile_fails=True)[0])[1]["employeecode"], "")

    def test_BF05_empty_configstatus_survives_generation(self):
        self.assertEqual(ta.FLOW["Respond_error"]["inputs"]["body"]["configstatus"], base.EMPTY_VALUE)
        self.assertEqual(answered(appstart_run(profile_fails=True)[0])[1]["configstatus"], "")

    def test_BF06_empty_missing_keeps_its_string_type(self):
        f = ta.FLOW["Respond_error"]["inputs"]
        self.assertEqual(f["body"]["missing"], base.EMPTY_VALUE)
        self.assertEqual(f["schema"]["properties"]["missing"]["type"], "string")
        self.assertEqual(answered(appstart_run(profile_fails=True)[0])[1]["missing"], "")

    def test_BF07_readown_failure_response_keeps_every_canonical_key(self):
        run = rq.run_custom(lambda n, a, p: ("Failed", {"error": "x"}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None)
        name, body = answered(run)
        self.assertEqual((name, list(body)), ("Respond_error", READ_KEYS))
        self.assertEqual((body["rows"], body["nextafterid"], body["pagesize"]), ("[]", "0", "0"))

    def test_BF08_saveentry_failure_response_keeps_every_canonical_key(self):
        _, _, _, run = sq.run_hooked(lambda n, a, p: ("Failed", {"error": "x"}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None)
        name, body = answered(run)
        self.assertEqual((name, list(body)), ("Respond_error", SAVE_KEYS))

    def test_BF09_empty_etag_survives_saveentry_generation(self):
        self.assertEqual(sq.t.FLOW["Respond_error"]["inputs"]["body"]["etag"], base.EMPTY_VALUE)
        _, _, _, run = sq.run_hooked(lambda n, a, p: ("Failed", {"error": "x"}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None)
        self.assertEqual((answered(run)[1]["etag"], answered(run)[1]["itemid"]), ("", "0"))

    def test_BF10_empty_auditstatus_survives_saveentry_generation(self):
        self.assertEqual(sq.t.FLOW["Respond_error"]["inputs"]["body"]["auditstatus"], base.EMPTY_VALUE)
        _, _, _, run = sq.run_hooked(lambda n, a, p: ("Failed", {"error": "x"}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None)
        self.assertEqual(answered(run)[1]["auditstatus"], "")

    def test_BF11_success_behaviour_unchanged(self):
        name, body = answered(appstart_run()[0])
        self.assertEqual((name, body["ok"], body["resultcode"], body["employeecode"], body["configstatus"]), ("Respond", "true", "OK", "E1", "OK"))
        r, _, _ = rq._HARNESS.both(rq.ME, dict(rq.OCT), items=rq.ITEMS)
        self.assertTrue(r["ok"])
        resp, writes, _, _ = sq.run_hooked(lambda n, a, p: None)
        self.assertEqual((resp["ok"], resp["code"], writes), (True, "OK", ["Create"]))
        for f, flow in FLOWS.items():  # no designer- or runtime-unsafe literal remains anywhere in the generated flows
            s = list(_strings(flow))
            self.assertNotIn("", s, f)
            self.assertFalse([x for x in s if "createArray()" in x], f)

    def test_BF12_reference_equals_generated_on_lookup_failure(self):
        def raising(_):
            raise PermissionError("403")
        ref, ev = ta.A.app_start(TrustedIdentity(upn=tg.u("emp")), raising, tg.CFG, registry=ta.REG, overlay=ta.OVL,
                                 settings_rows=ta.ROWS, correlation_id="run-bf", environment=ta.ENV, client_type="Teams", now=ta.NOW,
                                 **{k: "" for k in ta.UNTRUSTED})
        run, audit = appstart_run(lookup_fails=True)
        _, body = answered(run)
        self.assertEqual((body["ok"] == "true", body["resultcode"], body["messagecode"], body["employeecode"], body["configstatus"]),
                         (ref["ok"], ref["resultCode"], ref["messageCode"], ref["employeeCode"], ref["configStatus"]))
        self.assertEqual(audit, [ev.to_row()])

    def _suite_ok(self, module):
        with open(os.devnull, "w") as null:
            res = unittest.TextTestRunner(stream=null).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        self.assertTrue(res.wasSuccessful() and res.testsRun > 0, module.__name__)

    def test_BF13_appstart_regression(self):
        self._suite_ok(aq)
        self._suite_ok(ta)

    def test_BF14_readown_regression(self):
        self._suite_ok(rq)

    def test_BF15_saveentry_regression(self):
        self._suite_ok(sq)


if __name__ == "__main__":
    unittest.main(verbosity=2)
