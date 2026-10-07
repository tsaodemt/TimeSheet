"""S05.5 operational AuditLog: schema, indexes, permissions, append-only use, provisioning plan. Tests AL01-AL18
(offline; nothing executed). Set TS_TARGET_SCHEMA to also reconcile against the local target definition."""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for d in (HERE, os.path.join(HERE, "..", "audit"), os.path.join(HERE, "..", "timesheet"), os.path.join(HERE, "..", "powerautomate"),
          os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config"), os.path.join(HERE, "..", "alm")):
    sys.path.insert(0, d)
import audit_event as ae  # noqa: E402
import permission_plan as pp  # noqa: E402
import r1_lists as rl  # noqa: E402
import schema_reconcile as sr  # noqa: E402
from test_schema_reconcile import ALLOWED, MAIN, FakeSite  # noqa: E402

A = rl.AUDITLOG
OWNERS, ADMIN, MEMBERS, SVC = 3, 9, 5, 77


def fields(t=None):
    return {f["internalName"]: f for f in (t or rl.target(A))["fields"]}


def empty_site():
    return {"site": ALLOWED, "lists": []}


def audit_rows():
    """Every audit row the generated R1 flows append, across allow / deny / refusal paths."""
    import test_r1_read_flow as rr
    import test_r1_save_flow as rs
    import test_appstart as ao
    rows = []
    for upn in (rr.ME, rr.tg.u("stranger")):
        rows += rr.run_flow(upn, {})[1]
        rows += rr.run_flow(upn, {"FromDate": "x", "ToDate": "y"})[1]
    for req in (rs.req(), rs.req(ItemId="1", ETag='"1,1"'), rs.req(Hours="0"), rs.req(ItemId="3", ETag='"3,1"')):
        rows += rs.run_flow(rs.ME, req, rs.Store(rs.ITEMS), rs.SCOPING_OFF)[1]
    rows += rs.run_flow(rs.tg.u("gone"), rs.req(), rs.Store(rs.ITEMS), rs.SCOPING_OFF)[1]
    for upn in (ao.tg.u("emp"), ao.tg.u("stranger")):
        rows += ao.run_flow(upn)[1]
    return rows


class AuditLog(unittest.TestCase):
    def test_AL01_exact_schema_is_the_audit_model(self):
        self.assertEqual(list(fields()), list(ae.COLUMNS))
        f = fields()
        self.assertEqual((f["OccurredOn"]["type"], f["OccurredOn"]["dateOnly"]), ("DateTime", False))
        self.assertEqual((f["WorkDate"]["type"], f["WorkDate"]["dateOnly"]), ("DateTime", True))
        self.assertEqual({n for n, x in f.items() if x["type"] == "Number"}, {"ActorEmployeeItemId", "OwnerEmployeeItemId"})
        self.assertEqual({n for n, x in f.items() if x["type"] == "Note"}, {"ChangeJson", "Detail"})
        self.assertFalse([n for n, x in f.items() if x["type"] in ("Lookup", "User")], "no lookups: audit rows stand alone")

    def test_AL02_required_fields(self):
        self.assertEqual({n for n, x in fields().items() if x["required"]},
                         {"EventType", "Action", "Decision", "ResultCode", "OccurredOn", "CorrelationId"})

    def test_AL03_intended_indexes_only(self):
        self.assertEqual({n for n, x in fields().items() if x["indexed"]}, {"OccurredOn", "CorrelationId", "OwnerEmployeeItemId", "TargetLegacyId"})
        for n, (dec, query, scale, why) in rl.INDEX_DECISIONS[A].items():
            self.assertTrue(query and scale and why, n)
        self.assertEqual(rl.INDEX_DECISIONS[A]["EventType"][0], rl.NOT_REQUIRED)

    def test_AL04_no_confidential_only_fields(self):
        names = set(fields())
        self.assertFalse(names & set(ae.CONF_FIELDS))
        self.assertFalse(names & rl.FORBIDDEN_COLUMNS[A])
        self.assertNotIn("ConfidentialAuditLog", rl.TARGETS)

    def test_AL05_retention_not_invented(self):
        self.assertFalse([n for n in fields() if re.search(r"retention|purge|expire", n, re.I)])
        src = open(os.path.join(HERE, "r1_lists.py"), encoding="utf-8").read()
        self.assertNotRegex(src, r"RetentionDays\s*=\s*\d")
        self.assertIn(("IT-08", "retention duration (purge stays disabled until decided; not needed to create the list)"),
                      rl.DEPENDENCIES[A]["production"])
        p = ae.RetentionPolicy.from_settings({}) if hasattr(ae.RetentionPolicy, "from_settings") else None
        if p is not None:
            self.assertNotEqual(getattr(p, "status", None), "CONFIGURED")

    def test_AL06_ordinary_users_no_direct_access(self):
        cur = [pp.Assignment(OWNERS, "Owners", ("Full Control",)), pp.Assignment(MEMBERS, "Members", ("Edit",)),
               pp.Assignment(4, "Visitors", ("Read",)), pp.Assignment(ADMIN, "admin", ("Full Control",))]
        p = rl.permission_plan(A, 1, False, cur, owners_id=OWNERS, admin_id=ADMIN)
        self.assertEqual(p["ops"][0][0], "break")
        self.assertEqual(p["ops"][0][1]["copyRoleAssignments"], False)
        uniq, after = pp.simulate(False, cur, p["ops"], admin_id=ADMIN)
        self.assertEqual({a.principal_id: a.effective for a in after}, {ADMIN: {"Full Control"}, OWNERS: {"Full Control"}})
        self.assertEqual(p["gated"][0]["gate"], "D-3")

    def test_AL07_service_never_delete(self):
        lv = rl.level_assessment(A)
        self.assertTrue(lv["sufficient"])
        self.assertEqual(lv["forbiddenPresent"], [])
        self.assertEqual(lv["beyondNeed"], ["EditListItems", "OverrideListBehaviors"], "TS Service is broader than append-only (decision AUD-P1)")
        with self.assertRaises(pp.PlanRefused):
            pp.plan(True, [], pp.Target(required={}, gated=[{"principal": "s", "role": "Full Control", "gate": "D-3"}]),
                    approved_grants=[{"gate": "D-3", "role": "Full Control", "principal_id": SVC, "approval": "x"}])

    def test_AL08_AL09_AL10_flows_only_append(self):
        import r1_flows
        flows = [r1_flows.build(n) for n in r1_flows.TEMPLATES]
        import build_maintenance_flow  # noqa: F401  (maintenance flows append AdminMaintenance rows the same way)
        calls = []
        for g in flows:
            for _, a, _ in r1_flows._walk(g):
                if a.get("type") == "OpenApiConnection" and "getbytitle('AuditLog')" in a["inputs"]["parameters"].get("parameters/uri", ""):
                    calls.append((a["inputs"]["parameters"]["parameters/method"], a["inputs"]["parameters"]["parameters/uri"],
                                  a["inputs"]["parameters"].get("parameters/headers", {})))
        self.assertTrue(calls)
        for m, uri, h in calls:
            self.assertEqual(m, "POST")
            self.assertTrue(uri.endswith("/items"), uri)  # append: never items(<id>)
            self.assertNotIn("X-HTTP-Method", json.dumps(h))  # no MERGE / DELETE
        self.assertFalse(any("recycle" in u or "DELETE" in m for m, u, _ in calls))

    def test_AL11_second_provisioning_run_is_noop(self):
        site = FakeSite(empty_site())
        ops = rl.schema_plan(A, site.actual, ALLOWED, ALLOWED)
        r = sr.apply({"lists": [rl.target(A)]}, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        self.assertEqual(len(r.executed), len(ops))
        self.assertEqual(rl.schema_plan(A, site.actual, ALLOWED, ALLOWED), [])

    def test_AL12_incompatible_field_type_blocks(self):
        site = FakeSite(empty_site())
        sr.apply({"lists": [rl.target(A)]}, site.actual, site, ALLOWED, allowed_url=ALLOWED, dry_run=False)
        drift = copy.deepcopy(site.actual)
        next(f for f in drift["lists"][0]["fields"] if f["internalName"] == "OccurredOn")["type"] = "Text"
        with self.assertRaises(sr.SiteGuardError):
            rl.schema_plan(A, drift, ALLOWED, ALLOWED)

    def test_AL13_wrong_target_refused(self):
        for url in (MAIN, ALLOWED + "-other", ALLOWED.replace("app-staging", "app")):
            with self.assertRaises(sr.SiteGuardError):
                rl.schema_plan(A, empty_site(), url, ALLOWED)

    def test_AL14_service_grant_gated_by_d3(self):
        cur = [pp.Assignment(OWNERS, "Owners", ("Full Control",)), pp.Assignment(ADMIN, "admin", ("Full Control",))]
        p2 = rl.permission_plan(A, 2, True, cur, owners_id=OWNERS, admin_id=ADMIN, service=None)
        self.assertEqual((p2["ops"], [g["status"] for g in p2["gated"]]), ([], ["GATED"]))
        p2 = rl.permission_plan(A, 2, True, cur, owners_id=OWNERS, admin_id=ADMIN,
                                service={"principal_id": SVC, "title": "svc-operational", "approval": "D-3 approval record"})
        self.assertEqual(p2["ops"], [("add", {"principal_id": SVC, "role": "TS Service", "gate": "D-3"})])
        with self.assertRaises(pp.PlanRefused):
            rl.permission_plan(A, 2, True, cur, owners_id=OWNERS, admin_id=ADMIN, temporary_principals=("temp-test-svc",),
                               service={"principal_id": SVC, "title": "temp-test-svc", "approval": "x"})

    def test_AL15_confidential_audit_stays_gated(self):
        self.assertIn("ENV-D2 (only ConfidentialAuditLog)", rl.DEPENDENCIES[A]["notIn"])
        self.assertEqual(set(rl.TARGETS), {"AuditLog", "TimesheetEntries"})

    def test_AL16_every_appended_row_fits_the_schema(self):
        f = fields()
        rows = audit_rows()
        self.assertGreater(len(rows), 15)
        types = {r["EventType"] for r in rows}
        self.assertTrue({"AppOpen", "IdentityRejected", "AuthorizationAllow", "AuthorizationDeny", "ReadProxy", "WriteProxy"} <= types, types)
        for r in rows:
            self.assertEqual(set(r) - set(f), set(), "columns not in AuditLog: %s" % r.get("EventType"))
            for n, spec in f.items():
                v = r.get(n)
                if spec["required"]:
                    self.assertTrue(v not in (None, ""), (n, r["EventType"]))
                if v is None:
                    continue
                if spec["type"] == "Number":
                    self.assertIsInstance(v, int, n)
                elif spec["type"] == "Boolean":
                    self.assertIsInstance(v, bool, n)
                elif spec["type"] == "DateTime":
                    self.assertRegex(v, r"^\d{4}-\d{2}-\d{2}$" if spec["dateOnly"] else r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", n)
                else:
                    self.assertIsInstance(v, str, n)

    def test_AL17_current_audit_failure_behaviour_is_fail_closed(self):
        """Documents what the generated flows do today (decision AUD-F1 is open): a failed decision append stops the run
        before any write; a failed WriteProxy append after a persisted write leaves the caller without a response."""
        import test_r1_save_flow as rs

        def attempt(event):
            store = rs.Store(rs.ITEMS)
            try:
                resp = rs.run_flow(rs.ME, rs.req(), store, rs.SCOPING_OFF, fail_audit=event)[3].results["Respond"]["status"]
            except Exception:  # noqa: BLE001 - a downstream expression error ends the run (no response either way)
                resp = "NO RESPONSE (run failed)"
            return resp, store
        resp, store = attempt("AuthorizationAllow")
        self.assertNotEqual(resp, "Succeeded")
        self.assertEqual(len(store.items), len(rs.ITEMS), "no write after a failed decision append")
        resp, store = attempt("WriteProxy")
        self.assertNotEqual(resp, "Succeeded", "no response after a failed post-write append")
        self.assertEqual(len(store.items), len(rs.ITEMS) + 1, "the entry was persisted (AUD-F1)")

    @unittest.skipUnless(os.environ.get("TS_TARGET_SCHEMA"), "set TS_TARGET_SCHEMA to reconcile with the local target")
    def test_AL18_reconciles_with_the_target_schema(self):
        t = json.load(open(os.environ["TS_TARGET_SCHEMA"], encoding="utf-8"))
        tl = next(l for l in t["lists"] if l["title"] == A)
        self.assertEqual([f["internalName"] for f in tl["fields"]], list(fields()))
        for f in tl["fields"]:
            mine = fields()[f["internalName"]]
            self.assertEqual((f["type"], f["required"], f.get("dateOnly")), (mine["type"], mine["required"], mine.get("dateOnly")), f["internalName"])
        diff = sorted(n for n in fields() if bool(fields()[n]["indexed"]) != bool(next(f for f in tl["fields"] if f["internalName"] == n)["indexed"]))
        self.assertEqual(diff, ["Action", "ActorUpn", "EventType"], "documented index reconciliation (target 7 -> 4)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
