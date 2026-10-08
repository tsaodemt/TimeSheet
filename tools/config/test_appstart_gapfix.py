"""OFFLINE-APPSTART-GAP-FIX-01 tests AF01-AF18 (synthetic data only; run: python -m unittest).

Every case runs the reference (appstart.py) and the generated flow (build_appstart_flow.py, WDL simulator) and requires
identical responses (and identical audit rows when an audit row is written).
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "audit")):
    sys.path.insert(0, p)
import appstart as A  # noqa: E402
import build_appstart_flow as baf  # noqa: E402
import test_appstart as ta  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import Employee, TrustedIdentity  # noqa: E402

KEYS = ["ok", "resultCode", "messageCode", "correlationId", "employeeCode", "configStatus", "config", "interim", "missing"]
MISSING, BROKEN = "missing", "broken"


def row(i, upn, *, dept="DEP1", disc="D1", pos="P1", active=True):
    """Operational Employees row as the service read returns it. A missing lookup is null; a broken lookup (target
    deleted / unresolvable) still has an expanded object but no projected code."""
    def lk(v, code):
        return None if v == MISSING else {code: None} if v == BROKEN else {code: v}
    r = {"Id": i, "LegacyId": "L-%d" % i, "IsActive": active, "AccountUpn": upn,
         "Department": lk(dept, "DepartmentCode"), "Discipline": lk(disc, "DisciplineCode")}
    if pos is not None:
        r["Position"] = {"Title": pos}
    return r


def to_emp(r):
    code = lambda o, k: (o or {}).get(k) or None  # noqa: E731
    return Employee(r["Id"], r["LegacyId"], r["AccountUpn"], r["IsActive"], code(r["Discipline"], "DisciplineCode"),
                    code(r["Department"], "DepartmentCode"))


def run_flow(rows, upn, *, profile_fail=False, audit_fail=False, decoys=None, cid="run-af"):
    posts = []

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return ("Failed", {"error": "profile"}) if profile_fail else ("Succeeded", {"userPrincipalName": upn})
        if p.get("parameters/method") == "GET" and "getbytitle('AppSettings')" in p["parameters/uri"]:
            return "Succeeded", {"value": ta.ROWS}
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(p["parameters/uri"], {tg.EMP_LIST: rows})
        if p.get("parameters/method") == "POST":
            if audit_fail:
                return "Failed", {"error": "audit"}
            posts.append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": 1}
        raise AssertionError(opid)
    trig = dict({"text": "Teams"}, **{"text_%d" % (i + 1): (decoys or {}).get(k, "") for i, k in enumerate(ta.UNTRUSTED)})
    run = wdl_sim.Run(trigger_body=trig, run_name=cid, mocks=mocks, now=ta.NOW).run(ta.FLOW)
    done = [n for n in ("Respond", "Respond_error") if run.results.get(n, {}).get("status") == "Succeeded"]
    assert len(done) == 1, done                                   # exactly one response per run
    out = run.results[done[0]]["outputs"]
    resp = {"ok": out["ok"] == "true", "resultCode": out["resultcode"], "messageCode": out["messagecode"],
            "correlationId": out["correlationid"], "employeeCode": out["employeecode"], "configStatus": out["configstatus"],
            "config": json.loads(out["config"]), "interim": json.loads(out["interim"]),
            "missing": [m for m in out["missing"].split(",") if m]}
    return resp, posts, run


def run_ref(rows, upn, *, profile_fail=False, audit_fail=False, decoys=None, cid="run-af"):
    written = []

    def write(r):
        if audit_fail:
            raise IOError("audit")
        written.append(r)
    emps = [to_emp(r) for r in rows]
    resp, ev = A.app_start(TrustedIdentity(upn=upn), lambda n: [e for e in emps if e.account_upn == n], tg.CFG,
                           registry=ta.REG, overlay=ta.OVL, settings_rows=ta.ROWS, correlation_id=cid, environment=ta.ENV,
                           client_type="Teams", now=ta.NOW, profile_failed=profile_fail, write_audit=write,
                           **{k: (decoys or {}).get(k, "") for k in ta.UNTRUSTED})
    return resp, written, ev


U = tg.u("emp")


class GapFix(unittest.TestCase):
    def both(self, rows, upn=U, **kw):
        r, written, ev = run_ref(rows, upn, **kw)
        f, posts, run = run_flow(rows, upn, **kw)
        self.assertEqual(f, r, "reference vs flow response differ")
        self.assertEqual(posts, written, "reference vs flow audit rows differ")
        self.assertEqual(list(r), KEYS)
        return r, written, run

    def assertDenied(self, r, code, msg="MSG_TEMPORARY_PROBLEM"):
        self.assertEqual((r["ok"], r["resultCode"], r["messageCode"]), (False, code, msg))
        self.assertEqual((r["employeeCode"], r["configStatus"], r["config"], r["interim"], r["missing"]), ("", "", {}, {}, []))

    def test_af01_valid_references_ok(self):
        r, written, _ = self.both([row(1, U)])
        self.assertEqual((r["ok"], r["resultCode"], r["employeeCode"]), (True, "OK", "L-1"))
        self.assertEqual(written[0]["ResultCode"], "OK")

    def test_af02_missing_department(self):
        r, written, _ = self.both([row(1, U, dept=MISSING)])
        self.assertDenied(r, "INVALID_EMPLOYEE_REFERENCE")
        self.assertEqual((written[0]["EventType"], written[0]["ResultCode"]), ("IdentityRejected", "INVALID_EMPLOYEE_REFERENCE"))

    def test_af03_broken_department(self):
        r, _, _ = self.both([row(1, U, dept=BROKEN)])
        self.assertDenied(r, "INVALID_EMPLOYEE_REFERENCE")

    def test_af04_missing_discipline(self):
        r, _, _ = self.both([row(1, U, disc=MISSING)])
        self.assertDenied(r, "INVALID_EMPLOYEE_REFERENCE")

    def test_af05_broken_discipline(self):
        r, _, _ = self.both([row(1, U, disc=BROKEN)])
        self.assertDenied(r, "INVALID_EMPLOYEE_REFERENCE")

    def test_af06_missing_position_ok(self):
        r, _, _ = self.both([row(1, U, pos=None)])
        self.assertEqual((r["ok"], r["resultCode"]), (True, "OK"))

    def test_af07_af08_client_department_and_discipline_ignored(self):
        # The trigger has no Department / Discipline input at all; identity-like decoys are ignored, and a valid client
        # claim cannot repair an invalid stored reference.
        for name in ("Trusted", "Caller_lookup", "Caller_rows", "IdCode", "Emp", "CallerCode"):
            self.assertNotRegex(json.dumps(ta.FLOW[name]), r"trigger(Body|Outputs)", name)  # decisions never read the request
        decoys = {"Scope": "DEP1", "Role": "D1", "Config": json.dumps({"Department": "DEP1", "Discipline": "D1"})}
        r, _, _ = self.both([row(1, U, dept=MISSING, disc=MISSING)], decoys=decoys)
        self.assertDenied(r, "INVALID_EMPLOYEE_REFERENCE")
        self.assertNotIn("text_", json.dumps(ta.FLOW["IdCode"]))

    def test_af09_profile_failure_directory_error(self):
        r, written, run = self.both([row(1, U)], profile_fail=True)
        self.assertDenied(r, "DIRECTORY_ERROR")
        self.assertEqual(written, [])
        self.assertEqual(run.results["Respond_error"]["status"], "Succeeded")

    def test_af10_af11_audit_failure_internal_error(self):
        for rows in ([row(1, U)], [row(1, U, dept=MISSING)], []):
            r, _, run = self.both(rows, audit_fail=True)
            self.assertDenied(r, "INTERNAL_ERROR")
            self.assertEqual(r["correlationId"], "run-af")
            self.assertNotEqual(run.results.get("Settings_read", {}).get("status"), "Succeeded")  # never continues

    def test_af12_key_set_fixed_on_every_path(self):
        cases = [dict(rows=[row(1, U)]), dict(rows=[]), dict(rows=[row(1, U), row(2, U)]), dict(rows=[row(1, U, active=False)]),
                 dict(rows=[row(1, U, disc=BROKEN)]), dict(rows=[row(1, U)], profile_fail=True),
                 dict(rows=[row(1, U)], audit_fail=True)]
        codes = set()
        for c in cases:
            rows = c.pop("rows")
            r, _, _ = self.both(rows, **c)
            self.assertEqual(list(r), KEYS)
            codes.add(r["resultCode"])
        r, _, _ = self.both([row(1, "x@other.invalid")], upn="x@other.invalid")
        codes.add(r["resultCode"])
        self.assertEqual(codes, {"OK", "UNMAPPED_IDENTITY", "DUPLICATE_IDENTITY", "INACTIVE_EMPLOYEE", "INVALID_EMPLOYEE_REFERENCE",
                                 "DIRECTORY_ERROR", "INTERNAL_ERROR", "INVALID_IDENTITY"})
        self.assertEqual(list(ta.FLOW["Respond_error"]["inputs"]["body"]), list(ta.FLOW["Respond"]["inputs"]["body"]))

    def test_af13_message_mapping_equal_in_reference_and_flow(self):
        for code in ("INVALID_EMPLOYEE_REFERENCE", "INTERNAL_ERROR"):
            self.assertEqual(A.MESSAGE_CODES[code], "MSG_TEMPORARY_PROBLEM")
            self.assertEqual(baf.MESSAGE[code], "MSG_TEMPORARY_PROBLEM")
        self.assertEqual(set(A.MESSAGE_CODES) - {"OK"}, set(baf.MESSAGE) - {"OK"})

    def test_af16_no_canvas_contract_change(self):
        with open(os.path.join(HERE, "..", "powerapp", "demo-r1", "scrStartup.pa.yaml"), encoding="utf-8") as f:
            src = f.read()
        used = set(re.findall(r"varOpen\.([a-z]+)", src))
        self.assertLessEqual(used, set(ta.FLOW["Respond"]["inputs"]["body"]))
        self.assertEqual(sorted(ta.FLOW["Respond"]["inputs"]["body"]),
                         sorted(["ok", "resultcode", "messagecode", "correlationid", "employeecode", "configstatus", "config",
                                 "interim", "missing"]))

    def test_af17_no_dataverse(self):
        low = json.dumps(ta.FLOW).lower()
        self.assertNotIn("commondataservice", low)
        self.assertNotIn("dataverse", low)

    def test_af18_offline_only(self):
        with open(os.path.join(HERE, "appstart.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIsNone(re.search(r"\b(urllib|requests|http\.client|socket)\b", src))


if __name__ == "__main__":
    unittest.main()
