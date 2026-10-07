"""R1 Read Own Entries: reference (entries.read_own) vs generated flow (build_r1_flows.read_own_actions) in the WDL
simulator, against a SharePoint-like store that evaluates the $filter. Tests RR01-RR22 (offline; nothing deployed)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"), os.path.join(HERE, "..", "config")):
    sys.path.insert(0, p)
import app_settings as cfg  # noqa: E402
import build_r1_flows as r1  # noqa: E402
import business_dates as bd  # noqa: E402
import entries as E  # noqa: E402
import guard as G  # noqa: E402
import test_guard as tg  # noqa: E402
import wdl_sim  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402

TZ = "Asia/Ho_Chi_Minh"
ME, OTHER = tg.u("emp"), tg.u("peer")
REG = {"settings": [{"key": "BusinessTimezone", "type": "iana_tz", "value": "Asia/Ho_Chi_Minh", "resolution": "RESOLVED"}]}
OVL = {"environment": "STAGING", "values": {}, "external": {}}
SETTINGS = [{"Title": "BusinessTimezone", "Value": TZ}]
DECOYS = ["OwnerUpn", "ActorUpn", "EmployeeId", "Role", "Scope"]


def item(i, owner, date, status="Draft"):
    return {"Id": i, "WorkDate": bd.local_midnight_utc(date, TZ), "OwnerUpn": owner, "EntryStatus": status, "ProjectId": 11,
            "PhaseId": 21, "WorkTypeId": 31, "ShiftId": 41, "HourTypeId": 51, "Hours": 2, "Remark": "r%d" % i, "odata.etag": "\"%d\"" % i}


ITEMS = ([item(i, ME, "2026-10-%02d" % i) for i in range(1, 11)] + [item(11, OTHER, "2026-10-05"), item(12, ME, "2026-10-06", "Deleted")]
         + [item(i, ME, "2026-11-%02d" % (i - 12)) for i in range(13, 16)])
_COND = re.compile(r"^(\w+) (eq|ne|ge|lt|gt) (?:datetime'([^']+)'|'((?:[^']|'')*)'|(\d+))$")


def sp_query(uri, items):
    q = dict(kv.split("=", 1) for kv in uri.split("?", 1)[1].split("&"))
    out = items
    for cond in q["$filter"].split(" and "):
        f, op, dt, s, n = _COND.match(cond).groups()
        v = dt if dt is not None else (s.replace("''", "'") if s is not None else int(n))
        test = {"eq": lambda a: str(a).lower() == str(v).lower(), "ne": lambda a: a != v, "ge": lambda a: a >= v,
                "lt": lambda a: a < v, "gt": lambda a: a > v}[op]
        out = [x for x in out if test(x.get(f))]
    return sorted(out, key=lambda x: x["Id"])[:int(q["$top"])]


FLOW = r1.read_own_actions(scope_config=tg.SCOPE_CONFIG, role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x", domain=tg.DOM,
                           emp_list=tg.EMP_LIST, audit_list="_Audit", conf_audit_list="_ConfAudit", environment="STAGING",
                           registry=REG, overlay=OVL)


def run_flow(upn, req, items=ITEMS, settings=SETTINGS, roles=("EMP",), decoys=None, cid="run-rr", leak=False, flow=None):
    posts = []
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        uri = p.get("parameters/uri", "")
        if p.get("parameters/method") == "GET" and "getbytitle('AppSettings')" in uri:
            return "Succeeded", {"value": settings}
        if p.get("parameters/method") == "GET" and "getbytitle('TimesheetEntries')" in uri:
            rows = sp_query(uri, items)
            return "Succeeded", {"value": rows + ([item(99, OTHER, "2026-10-01")] if leak else [])}
        if p.get("parameters/method") == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(uri, {tg.EMP_LIST: tg.rows(tg.EMPS)})
        if p.get("parameters/method") == "POST":
            posts.append(json.loads(p["parameters/body"]))
            return "Succeeded", {"Id": 1}
        raise AssertionError(name)
    trig = {"text": req.get("FromDate", ""), "text_1": req.get("ToDate", ""), "text_2": str(req.get("AfterId", "")),
            "text_3": str(req.get("PageSize", "")), "text_4": req.get("RequestedOwner", "")}
    trig.update({"text_%d" % (5 + i): (decoys or {}).get(k, "") for i, k in enumerate(DECOYS)})
    run = wdl_sim.Run(trigger_body=trig, run_name=cid, mocks=mocks).run(flow or FLOW)
    b = run.results["Respond"]["outputs"]
    return {"ok": b["ok"] == "true", "code": b["resultcode"], "messageCode": b["messagecode"], "correlationId": b["correlationid"],
            "rows": json.loads(b["rows"]), "nextAfterId": int(b["nextafterid"]), "pageSize": int(b["pagesize"])}, posts, run


class RefStore:
    def __init__(self, items, leak=False):
        self.items, self.leak = items, leak

    def query(self, flt):
        lo, hi = flt.utc_bounds()
        rows = [x for x in sorted(self.items, key=lambda x: x["Id"]) if x["OwnerUpn"].lower() == flt.owner_upn and x["EntryStatus"] != "Deleted"
                and x["Id"] > flt.after_id and bd.in_range(x["WorkDate"], lo, hi)][:flt.top]
        rows += [item(99, OTHER, "2026-10-01")] if self.leak else []
        return [(x["Id"], x, x["odata.etag"]) for x in rows]


def ref(upn, req, items=ITEMS, settings=SETTINGS, roles=("EMP",), cid="run-rr", leak=False, reg=REG):
    ident = TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])
    lk = lambda n: [e for e in tg.EMPS if e.account_upn == n]  # noqa: E731
    g = G.authorize(ident, lk, lk, tg.CFG, tg.POLICY, "TS.ViewOwn", "self", correlation_id=cid)
    emp = next((e for e in tg.EMPS if e.account_upn == upn), None)
    caller = E.Caller(upn, emp.item_id, emp.legacy_id, emp.discipline_id) if emp and g.allowed else None
    s = cfg.resolve(reg, OVL, settings)
    tz = s["BusinessTimezone"].value if s["BusinessTimezone"].status == cfg.CONFIGURED else None
    r = E.read_own(g, caller, req, RefStore(items, leak), correlation_id=cid, business_timezone=tz)
    return {"ok": r["ok"], "code": r["code"], "messageCode": "MSG_" + r["code"], "correlationId": cid, "rows": r["rows"],
            "nextAfterId": r["nextAfterId"], "pageSize": r["pageSize"]}


class R1Read(unittest.TestCase):
    def both(self, upn, req, **kw):
        f, posts, run = run_flow(upn, req, **{k: v for k, v in kw.items()})
        r = ref(upn, req, **{k: v for k, v in kw.items() if k not in ("decoys",)})
        self.assertEqual(f, r, "reference vs flow differ for %s" % req)
        return f, posts, run

    def dates(self, res):
        return [x["workDate"] for x in res["rows"]]

    def test_RR01_valid_own_read(self):
        f, _, _ = self.both(ME, {})
        self.assertEqual((f["ok"], f["code"], len(f["rows"])), (True, "OK", 13))
        self.assertEqual(f["rows"][0], {"id": 1, "workDate": "2026-10-01", "projectId": 11, "phaseId": 21, "workTypeId": 31, "shiftId": 41,
                                         "hourTypeId": 51, "hours": 2, "remark": "r1", "status": "Draft", "etag": "\"1\""})

    def test_RR02_other_owner_excluded(self):
        f, _, _ = self.both(ME, {})
        self.assertNotIn(11, [x["id"] for x in f["rows"]])

    def test_RR03_forged_owner_ignored_and_foreign_request_refused(self):
        f, _, run = self.both(ME, {}, decoys={"OwnerUpn": OTHER, "ActorUpn": OTHER, "Role": "ADM"})
        self.assertNotIn(11, [x["id"] for x in f["rows"]])
        self.assertIn("OwnerUpn", run.results["Guard_result"]["outputs"]["IgnoredInputs"])
        f, _, _ = self.both(ME, {"RequestedOwner": OTHER})
        self.assertEqual((f["code"], f["rows"]), ("FORBIDDEN", []))

    def test_RR04_deleted_excluded(self):
        self.assertNotIn(12, [x["id"] for x in self.both(ME, {})[0]["rows"]])

    def test_RR05_no_date_read(self):
        self.assertEqual(len(self.both(ME, {})[0]["rows"]), 13)

    def test_RR06_to_RR09_range_first_last_next(self):
        f, _, run = self.both(ME, {"FromDate": "2026-10-03", "ToDate": "2026-10-05"})
        self.assertEqual(self.dates(f), ["2026-10-03", "2026-10-04", "2026-10-05"])
        flt = run.results["Filter"]["outputs"]
        self.assertIn("WorkDate ge datetime'2026-10-02T17:00:00Z' and WorkDate lt datetime'2026-10-05T17:00:00Z'", flt)

    def test_RR10_reversed_range_rejected(self):
        self.assertEqual(self.both(ME, {"FromDate": "2026-10-05", "ToDate": "2026-10-03"})[0]["code"], "VALIDATION_DATE")

    def test_RR11_single_date_rejected_and_bad_dates(self):
        for req in ({"FromDate": "2026-10-03"}, {"ToDate": "2026-10-03"}, {"FromDate": "2026-02-30", "ToDate": "2026-03-01"},
                    {"FromDate": "03/10/2026", "ToDate": "2026-10-04"}):
            self.assertEqual(self.both(ME, req)[0]["code"], "VALIDATION_DATE", req)

    def test_RR12_to_RR15_paging(self):
        p1, _, _ = self.both(ME, {"PageSize": 5})
        p2, _, _ = self.both(ME, {"PageSize": 5, "AfterId": p1["nextAfterId"]})
        p3, _, _ = self.both(ME, {"PageSize": 5, "AfterId": p2["nextAfterId"]})
        ids = [x["id"] for p in (p1, p2, p3) for x in p["rows"]]
        self.assertEqual(ids, sorted(ids), "stable ordering by Id")
        self.assertEqual(len(ids), len(set(ids)), "no duplicates between pages")
        self.assertEqual((len(ids), p3["nextAfterId"]), (13, 0))

    def test_RR16_page_size_capped(self):
        self.assertEqual(self.both(ME, {"PageSize": 10000})[0]["pageSize"], 500)
        self.assertEqual(self.both(ME, {"PageSize": 0})[0]["pageSize"], 1)
        self.assertEqual(self.both(ME, {"PageSize": "x"})[0]["code"], "VALIDATION_LOOKUP")

    def test_RR17_RR18_missing_or_invalid_zone_fails_closed(self):
        for settings in ([{"Title": "BusinessTimezone", "Value": "Mars/Base"}], [{"Title": "BusinessTimezone", "Value": "Europe/Paris"}]):
            f, _, _ = self.both(ME, {"FromDate": "2026-10-03", "ToDate": "2026-10-05"}, settings=settings)
            self.assertEqual((f["code"], f["rows"]), ("CONFIG_UNRESOLVED", []), settings)  # unknown / no Windows mapping
        noval = {"settings": [dict(REG["settings"][0], value=None)]}
        flow = r1.read_own_actions(scope_config=tg.SCOPE_CONFIG, role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x",
                                   domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit", conf_audit_list="_ConfAudit",
                                   environment="STAGING", registry=noval, overlay=OVL)
        for settings in ([], [{"Title": "BusinessTimezone", "Value": ""}]):
            f = run_flow(ME, {}, settings=settings, flow=flow)[0]
            r = ref(ME, {}, settings=settings, reg=noval)
            self.assertEqual(f, r)
            self.assertEqual((f["code"], f["rows"]), ("CONFIG_UNRESOLVED", []), "missing zone")

    def test_RR19_correlation_preserved(self):
        f, posts, _ = self.both(ME, {}, cid="run-corr-9")
        self.assertEqual(f["correlationId"], "run-corr-9")
        self.assertTrue(posts and all(p.get("CorrelationId") == "run-corr-9" for p in posts))
        self.assertEqual([p["EventType"] for p in posts if p.get("EventType")], ["ReadProxy"])

    def test_RR20_denied_identity_gets_no_rows(self):
        for upn, code in ((tg.u("stranger"), "UNMAPPED_IDENTITY"), (tg.u("gone"), "INACTIVE_EMPLOYEE")):
            f, posts, _ = self.both(upn, {})
            self.assertEqual((f["ok"], f["code"], f["rows"]), (False, code, []))
            self.assertEqual(next(p for p in posts if p.get("EventType"))["Decision"], "DENY")

    def test_RR21_leak_returns_no_rows(self):
        f, _, _ = self.both(ME, {}, leak=True)
        self.assertEqual((f["code"], f["rows"]), ("ERROR_LEAK", []))

    def test_RR22_no_sharepoint_internals_or_bound_accounts(self):
        blob = json.dumps(FLOW)
        self.assertNotIn('"connectionName"', blob)
        self.assertEqual(set(re.findall(r'"connectionReferenceLogicalName": "([^"]+)"', blob)),
                         {"<PFX>_CR_SharePoint_OpsService", "<PFX>_CR_O365Users_Invoker", "<PFX>_CR_O365Groups_OpsService"})
        f, _, run = self.both(ME, {"FromDate": "x", "ToDate": "y"})
        self.assertNotIn("_api", json.dumps(run.results["Respond"]["outputs"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
