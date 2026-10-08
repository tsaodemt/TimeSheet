"""SAVEENTRY-FINALIZE-AND-R1-OFFLINE-READINESS tests SF01-SF24 (synthetic data only; run: python -m unittest).

Approved decisions: R1 create is NON-IDEMPOTENT (R1_KNOWN_LIMITATION_CREATE_RETRY_NON_IDEMPOTENT; no RequestKey, no
duplicate suppression); caller-profile failure -> DIRECTORY_ERROR and pre-write permission-audit failure ->
INTERNAL_ERROR (both MSG_TEMPORARY_PROBLEM, no write, no item data); post-write audit failure stays AUD-F1 option B.
Reference (entries.save_entry) and generated flow (save_draft_actions, WDL simulator) are compared case by case.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_r1_save_flow as t  # noqa: E402  (sets sys.path)
import test_saveentry_qualification as q  # noqa: E402
import app_settings as cfg  # noqa: E402
import entries as E  # noqa: E402
import guard as G  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

ME, OTHER = t.ME, t.OTHER
KEYS = ["ok", "code", "messageCode", "itemId", "etag", "correlationId", "warnings", "interim", "auditStatus"]
FLOW_JSON = json.dumps(t.FLOW)


def ref_prewrite(request, store, *, profile_fail=False, audit_fail=False, upn=ME, cid="run-rs"):
    ident = TrustedIdentity(upn=upn, group_ids=["g-emp"])
    lk = lambda n: [e for e in t.tg.EMPS if e.account_upn == n]  # noqa: E731
    g = G.authorize(ident, lk, lk, t.tg.CFG, t.tg.POLICY, "TS.EditOwnDraft", "self", correlation_id=cid)
    emp = next(e for e in t.tg.EMPS if e.account_upn == upn)
    caller = E.Caller(upn, emp.item_id, emp.legacy_id, emp.discipline_id)

    def writer(kind):
        if audit_fail and kind == "Authorization":
            raise IOError("audit")
    r = E.save_entry(g, caller, {k: v for k, v in request.items() if v != ""}, t.masters(), cfg.resolve(t.REG, t.OVL, t.SCOPING_OFF),
                     store, correlation_id=cid, profile_failed=profile_fail, audit_writer=writer)
    return {"ok": r.ok, "code": r.code, "messageCode": r.messageCode, "itemId": r.itemId, "etag": r.etag, "correlationId": cid,
            "warnings": r.warnings, "interim": r.interim, "auditStatus": r.auditStatus}


class Finalize(t._Both):
    def prewrite_both(self, request, **kw):
        hook = ((lambda n, a, p: ("Failed", {"statusCode": 500}) if a["inputs"]["host"]["operationId"] == "MyProfile_V2" else None)
                if kw.get("profile_fail") else
                (lambda n, a, p: ("Failed", {"statusCode": 400}) if n == "Write_Authz_audit" else None))
        f, writes, fstore, run = q.run_hooked(hook, request=request)
        rstore = t.Store(t.ITEMS)
        r = ref_prewrite(request, rstore, **kw)
        self.assertEqual(f, r, "reference vs flow differ")
        self.assertEqual(fstore.state(), rstore.state())
        return f, writes, fstore, run

    # ---- R1 create retry contract (non-idempotent)
    def test_sf01_sf02_sf03_sf04_retry_creates_independent_own_row(self):
        st = t.Store(t.ITEMS)
        a, _ = t.ref(ME, t.req(), st, t.SCOPING_OFF)
        b, _ = t.ref(ME, t.req(), st, t.SCOPING_OFF)                     # "lost response" -> the caller retries
        self.assertTrue(a["ok"] and b["ok"])
        self.assertNotEqual(a["itemId"], b["itemId"])
        ra, rb = st.items[a["itemId"]], st.items[b["itemId"]]
        self.assertNotEqual(ra["LegacyId"], rb["LegacyId"])
        self.assertEqual((rb["OwnerUpn"], rb["EmployeeItemId"], rb["EntryStatus"]), (ME, t.ME_EMP.item_id, "Draft"))
        self.assertIn("WARN_DUPLICATE", b["warnings"])                    # advisory only: the save succeeded
        # the flow behaves the same: two creates against one store -> two rows
        fs = t.Store(t.ITEMS)
        f1 = t.run_flow(ME, t.req(), fs, t.SCOPING_OFF)[0]
        f2 = t.run_flow(ME, t.req(), fs, t.SCOPING_OFF)[0]
        self.assertTrue(f1["ok"] and f2["ok"] and f1["itemId"] != f2["itemId"])
        self.assertIn("WARN_DUPLICATE", f2["warnings"])

    def test_sf05_sf06_no_idempotency_key_or_suppression(self):
        low = FLOW_JSON.lower()
        for bad in ("requestkey", "idempotency", "payloadhash"):
            self.assertNotIn(bad, low)
        with self.assertRaises(ValueError):
            t.build(idempotency="request-key")
        self.assertNotRegex(FLOW_JSON, r'"X-HTTP-Method": "DELETE"')
        self.assertIsInstance(E.NoIdempotency().before_create(None, None, {}, {}), type(None))

    def test_sf07_sf20_update_retry_old_etag_conflict(self):
        f = self.both(ME, t.req(ItemId="1", ETag='"1,1"', Hours="3"))
        self.assertTrue(f["ok"])
        st = t.Store(t.ITEMS)
        a, _ = t.ref(ME, t.req(ItemId="1", ETag='"1,1"', Hours="3"), st, t.SCOPING_OFF)
        b, _ = t.ref(ME, t.req(ItemId="1", ETag='"1,1"', Hours="4"), st, t.SCOPING_OFF)
        self.assertEqual((a["code"], b["code"], st.items[1]["Hours"]), ("OK", "CONFLICT", 3.0))

    # ---- pre-write failures
    def test_sf08_sf09_sf10_profile_failure(self):
        f, writes, store, run = self.prewrite_both(t.req(), profile_fail=True)
        self.assertEqual((f["ok"], f["code"], f["messageCode"]), (False, "DIRECTORY_ERROR", "MSG_TEMPORARY_PROBLEM"))
        self.assertEqual(writes, [])
        self.assertEqual(len(store.items), len(t.ITEMS))

    def test_sf11_sf12_sf13_permission_audit_failure(self):
        for request in (t.req(), t.req(ItemId="1", ETag='"1,1"')):
            f, writes, store, run = self.prewrite_both(request, audit_fail=True)
            self.assertEqual((f["ok"], f["code"], f["messageCode"]), (False, "INTERNAL_ERROR", "MSG_TEMPORARY_PROBLEM"))
            self.assertEqual(writes, [])
            self.assertNotEqual(run.results.get("Get_item", {}).get("status"), "Succeeded")   # no validation / edit reads
            self.assertEqual(store.items[1]["Hours"], 2.0)

    def test_sf14_sf15_sf16_prewrite_shape(self):
        for kw in ({"profile_fail": True}, {"audit_fail": True}):
            f, _, _, _ = self.prewrite_both(t.req(ItemId="1", ETag='"1,1"'), **kw)
            self.assertEqual(list(f), KEYS)
            self.assertEqual((f["itemId"], f["etag"], f["warnings"], f["interim"], f["auditStatus"], f["correlationId"]),
                             (0, "", [], [], "", "run-rs"))
        self.assertEqual(list(t.FLOW["Respond_error"]["inputs"]["body"]), list(t.FLOW["Respond"]["inputs"]["body"]))

    # ---- post-write audit failure unchanged
    def test_sf17_sf18_post_write_audit_is_aud_f1_b(self):
        f = self.both(ME, t.req(), fail_audit="WriteProxy")
        self.assertEqual((f["ok"], f["code"], f["auditStatus"]), (True, "OK", "AUDIT_DEGRADED"))
        self.assertNotEqual(f["code"], "INTERNAL_ERROR")
        self.assertEqual(self.ctx["run"].results["Respond_error"]["status"], "Skipped")

    def test_sf19_ownership_unchanged(self):
        f = self.both(ME, t.req(ItemId="2", ETag='"2,1"'), decoys={"OwnerUpn": ME, "EmployeeId": str(t.ME_EMP.item_id)})
        self.assertEqual(f["code"], "FORBIDDEN")
        self.nothing_written()
        pc = t.FLOW["If_write"]["actions"]["Payload_create"]["inputs"]
        self.assertEqual(pc["OwnerUpn"], "@{outputs('Trusted')}")

    def test_sf21_reference_equals_flow_on_normal_paths(self):
        for request in (t.req(), t.req(Hours="0"), t.req(ItemId="1", ETag='"1,1"'), t.req(ItemId="3", ETag='"3,1"')):
            self.both(ME, request)                                      # asserts equality of response and stored rows

    def test_sf24_offline_only(self):
        with open(os.path.join(HERE, "entries.py"), encoding="utf-8") as f:
            self.assertIsNone(re.search(r"\b(urllib|requests|http\.client|socket)\b", f.read()))


if __name__ == "__main__":
    unittest.main()
