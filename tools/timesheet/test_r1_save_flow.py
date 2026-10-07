"""R1 Save Draft (create / edit own draft): reference (entries.save_entry) vs generated flow
(build_r1_flows.save_draft_actions) in the WDL simulator, against one SharePoint-like store per side. Tests RS01-RS25
(offline; nothing deployed). Reference lists are offline fixtures only (the S04.3 lists have no rows yet)."""
import copy
import json
import os
import re
import sys
import unittest
from urllib.parse import unquote

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
ME_EMP = next(e for e in tg.EMPS if e.account_upn == ME)
REG = {"settings": [
    {"key": "PayPeriodStartDay", "type": "int", "value": "26", "min": 1, "max": 28, "resolution": "RESOLVED"},
    {"key": "MaxHoursPerEntryWarn", "type": "decimal", "value": "4", "resolution": "RESOLVED"},
    {"key": "MaxHoursPerDayWarn", "type": "decimal", "value": "12", "resolution": "RESOLVED"},
    {"key": "ProjectAssignmentScoping", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "BLOCKED"},
    {"key": "BusinessTimezone", "type": "iana_tz", "value": TZ, "resolution": "RESOLVED"}]}
OVL = {"environment": "STAGING", "values": {}, "external": {}}
B03 = {"environment": "STAGING", "external": {}, "values": {"ProjectAssignmentScoping": {
    "value": "Off", "interim": True, "allowedEnvironments": ["STAGING"], "basis": "owner engineering decision",
    "customerDecision": "B-03 open"}}}
SCOPING_OFF = [{"Title": "ProjectAssignmentScoping", "Value": "Off"}]
DECOYS = r1.SAVE_DECOYS
ENTITY = "SP.Data.TimesheetEntriesListItem"

MASTER_ROWS = {
    "Projects": [{"Id": 101, "ProjectCode": "P1", "Status": "Active"}, {"Id": 102, "ProjectCode": "P2", "Status": "Paused"},
                 {"Id": 103, "ProjectCode": "P3", "Status": "Active"}, {"Id": 104, "ProjectCode": "O'Hara", "Status": "Active"}],
    "Phases": [{"Id": 201, "PhaseCode": "PH1", "IsActive": True}, {"Id": 202, "PhaseCode": "PH2", "IsActive": False},
               {"Id": 203, "PhaseCode": "PH3", "IsActive": True}, {"Id": 204, "PhaseCode": "PH4", "IsActive": None}],
    "ProjectPhases": [{"Id": 1, "ProjectId": 101, "PhaseId": 201, "IsActive": True}, {"Id": 2, "ProjectId": 101, "PhaseId": 202, "IsActive": True},
                      {"Id": 3, "ProjectId": 101, "PhaseId": 203, "IsActive": False}, {"Id": 4, "ProjectId": 103, "PhaseId": 203, "IsActive": True},
                      {"Id": 5, "ProjectId": 101, "PhaseId": 204, "IsActive": True}, {"Id": 6, "ProjectId": 104, "PhaseId": 201, "IsActive": True}],
    "WorkTypes": [{"Id": 301, "WorkTypeCode": "WT1", "IsActive": True}, {"Id": 302, "WorkTypeCode": "WT2", "IsActive": False}],
    "Shifts": [{"Id": 401, "ShiftCode": "S1", "IsActive": True}, {"Id": 402, "ShiftCode": "S2", "IsActive": None}],
    "HourTypes": [{"Id": 501, "HourTypeCode": "NT"}, {"Id": 502, "HourTypeCode": "OT"}],
    "ProjectAssignments": [{"Id": 1, "EmployeeItemId": ME_EMP.item_id, "ProjectId": 101}],
}


def entry(i, owner, date, status="Draft", hours=2.0, project=101, phase=201, shift=401, hour_type=501):
    return {"Id": i, "WorkDate": bd.local_midnight_utc(date, TZ), "OwnerUpn": owner, "ActorUpn": owner, "EntryStatus": status,
            "ProjectId": project, "PhaseId": phase, "WorkTypeId": 301, "ShiftId": shift, "HourTypeId": hour_type, "Hours": hours,
            "Remark": "r%d" % i}


ITEMS = [entry(1, ME, "2026-10-07"), entry(2, OTHER, "2026-10-07"), entry(3, ME, "2026-10-07", "Approved"),
         entry(4, ME, "2026-10-07", "Deleted", hours=9), entry(5, ME, "2026-10-08", hours=6), entry(6, ME, "2026-10-08", hours=5)]


class Store:
    """One SharePoint-like list. Date-only values are stored as local midnight in UTC (proven by POC P4)."""

    def __init__(self, items, race=False, readback="ok"):
        self.items = {x["Id"]: copy.deepcopy(x) for x in items}
        self.ver = {i: 1 for i in self.items}
        self.race = race
        self.readback = readback  # ok | fail (new ETag cannot be read back) | stale (read-back returns the sent ETag)
        self.read_back = {}

    def etag(self, i):
        return '"%d,%d"' % (i, self.ver[i])

    @staticmethod
    def _norm(fields):
        f = {k: v for k, v in fields.items() if k != "__metadata"}
        if "WorkDate" in f and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f["WorkDate"])):
            f["WorkDate"] = bd.local_midnight_utc(f["WorkDate"], TZ)
        return f

    def get(self, i):
        return (copy.deepcopy(self.items[i]), self.etag(i)) if i in self.items else None

    def create(self, fields):
        i = max(self.items) + 1
        self.items[i] = dict(self._norm(fields), Id=i)
        self.ver[i] = 1
        return i, (None if self.readback == "fail" else self.etag(i))

    def update(self, i, fields, if_match):
        if self.race:
            self.ver[i] += 1  # someone saved between the check and the write
        if if_match != self.etag(i):
            raise E.ConflictError()
        self.items[i].update(self._norm(fields))
        self.ver[i] += 1
        self.read_back[i] = {"ok": self.etag(i), "fail": None, "stale": if_match}[self.readback]
        return self.read_back[i]

    def find(self, OwnerUpn, WorkDate):
        return [(i, copy.deepcopy(f), self.etag(i)) for i, f in sorted(self.items.items())
                if f["OwnerUpn"].lower() == OwnerUpn and bd.business_date(f["WorkDate"], TZ) == WorkDate]

    def rows(self):
        return [dict(f, **{"odata.etag": self.etag(i)}) for i, f in sorted(self.items.items())]

    def state(self):
        return {i: {k: v for k, v in f.items() if k != "LegacyId"} for i, f in self.items.items()}


_COND = re.compile(r"^(\w+) (eq|ne|ge|lt|gt) (?:datetime'([^']+)'|'((?:[^']|'')*)'|(-?\d+))$")


def sp_query(uri, rows):
    q = dict(kv.split("=", 1) for kv in uri.split("?", 1)[1].split("&"))
    out = rows
    for cond in unquote(q["$filter"]).split(" and "):
        f, op, dt, s, n = _COND.match(cond).groups()
        v = dt if dt is not None else (s.replace("''", "'") if s is not None else int(n))
        test = {"eq": lambda a: a is not None and str(a).lower() == str(v).lower(), "ne": lambda a: a != v,
                "ge": lambda a: a >= v, "lt": lambda a: a < v, "gt": lambda a: a > v}[op]
        out = [x for x in out if test(x.get(f))]
    return sorted(out, key=lambda x: x["Id"])[:int(q["$top"])]


def build(reg=REG, ovl=OVL, **kw):
    return r1.save_draft_actions(scope_config=tg.SCOPE_CONFIG, role_groups=tg.ROLE_GROUPS, site="https://tenant-a.invalid/sites/x",
                                 domain=tg.DOM, emp_list=tg.EMP_LIST, audit_list="_Audit", conf_audit_list="_ConfAudit",
                                 environment="STAGING", registry=reg, overlay=ovl, **kw)


FLOW = build()
_FLOWS = {}


def flow_for(reg, ovl):
    key = json.dumps([reg, ovl], sort_keys=True)
    if key not in _FLOWS:
        _FLOWS[key] = FLOW if (reg, ovl) == (REG, OVL) else build(reg, ovl)
    return _FLOWS[key]


FIELDS = ["ItemId", "ETag", "WorkDate", "ProjectCode", "PhaseCode", "WorkTypeCode", "ShiftCode", "HourTypeCode", "Hours", "Remark"]


def req(**kw):
    r = {"ItemId": "", "ETag": "", "WorkDate": "2026-10-09", "ProjectCode": "P1", "PhaseCode": "PH1", "WorkTypeCode": "WT1",
         "ShiftCode": "S1", "HourTypeCode": "NT", "Hours": "2", "Remark": "work"}
    r.update(kw)
    return r


def run_flow(upn, request, store, settings, roles=("EMP",), decoys=None, cid="run-rs", fail=(), reg=REG, ovl=OVL, fail_audit=None):
    posts, writes = [], []
    member_of = {"g-" + r.lower() for r in roles}

    def mocks(name, a, p):
        opid = a["inputs"]["host"]["operationId"]
        if opid == "MyProfile_V2":
            return "Succeeded", {"userPrincipalName": upn}
        if opid == "ListGroupMembers":
            return "Succeeded", {"value": [{"userPrincipalName": upn}] if p["groupId"] in member_of else []}
        method, uri = p.get("parameters/method"), p.get("parameters/uri", "")
        lst = re.search(r"getbytitle\('([^']*)'\)", uri).group(1)
        if lst in fail:
            return "Failed", {"statusCode": 503}
        if method == "GET" and lst == "AppSettings":
            return "Succeeded", {"value": settings}
        if method == "GET" and lst in MASTER_ROWS:
            return "Succeeded", {"value": sp_query(uri, MASTER_ROWS[lst])}
        if lst == "TimesheetEntries":
            m = re.search(r"/items\((-?\d+)\)", uri)
            if method == "GET" and uri.endswith("?$select=ListItemEntityTypeFullName"):
                return "Succeeded", {"ListItemEntityTypeFullName": ENTITY}
            if method == "GET" and m and uri.endswith(")?$select=Id"):  # read-back of the new ETag after an update
                v = store.read_back.get(int(m.group(1)))
                return ("Failed", {"statusCode": 503}) if v is None else ("Succeeded", {"Id": int(m.group(1)), "odata.etag": v})
            if method == "GET" and m:
                got = store.get(int(m.group(1)))
                return ("Failed", {"statusCode": 404}) if got is None else ("Succeeded", dict(got[0], **{"odata.etag": got[1]}))
            if method == "GET":
                return "Succeeded", {"value": sp_query(uri, store.rows())}
            body = json.loads(p["parameters/body"])
            assert body["__metadata"]["type"] == ENTITY and p["parameters/headers"]["Content-Type"] == "application/json;odata=verbose"
            writes.append((uri, p["parameters/headers"], body))
            if m:
                assert p["parameters/headers"]["X-HTTP-Method"] == "MERGE"
                try:
                    store.update(int(m.group(1)), body, p["parameters/headers"]["IF-MATCH"])
                except E.ConflictError:
                    return "Failed", {"statusCode": 412}
                return "Succeeded", None
            i, etag = store.create(body)
            return "Succeeded", {"d": {"Id": i, "__metadata": {"etag": etag} if etag else {}}}
        if method == "GET":
            return "Succeeded", wdl_sim.sharepoint_get(uri, {tg.EMP_LIST: tg.rows(tg.EMPS)})
        if method == "POST":
            row = json.loads(p["parameters/body"])
            if fail_audit and row.get("EventType") == fail_audit:
                return "Failed", {"statusCode": 400}
            posts.append(row)
            return "Succeeded", {"Id": 1}
        raise AssertionError(name)
    trig = {"text" + ("" if i == 0 else "_%d" % i): str(request.get(k, "")) for i, k in enumerate(FIELDS)}
    trig.update({"text_%d" % (10 + i): (decoys or {}).get(k, "") for i, k in enumerate(DECOYS)})
    run = wdl_sim.Run(trigger_body=trig, run_name=cid, mocks=mocks).run(flow_for(reg, ovl))
    b = run.results["Respond"]["outputs"]
    return ({"ok": b["ok"] == "true", "code": b["resultcode"], "messageCode": b["messagecode"], "itemId": int(b["itemid"]),
             "etag": b["etag"], "correlationId": b["correlationid"], "warnings": json.loads(b["warnings"]),
             "interim": json.loads(b["interim"])}, posts, writes, run)


def masters():
    code = {lst: {r["Id"]: r[lst[:-1] + "Code"] for r in MASTER_ROWS[lst]} for lst in ("Projects", "Phases")}
    act = lambda r: r.get("IsActive") is not False  # noqa: E731
    return E.Masters(
        projects={r["ProjectCode"]: {"id": r["Id"], "status": r["Status"]} for r in MASTER_ROWS["Projects"]},
        project_phases={(code["Projects"][r["ProjectId"]], code["Phases"][r["PhaseId"]]): {"id": r["Id"], "active": act(r)}
                        for r in MASTER_ROWS["ProjectPhases"]},
        phases={r["PhaseCode"]: {"id": r["Id"], "active": act(r)} for r in MASTER_ROWS["Phases"]},
        work_types={r["WorkTypeCode"]: {"id": r["Id"], "active": act(r)} for r in MASTER_ROWS["WorkTypes"]},
        shifts={r["ShiftCode"]: {"id": r["Id"], "active": act(r)} for r in MASTER_ROWS["Shifts"]},
        hour_types={r["HourTypeCode"]: {"id": r["Id"]} for r in MASTER_ROWS["HourTypes"]},
        assignments=[code["Projects"][r["ProjectId"]] for r in MASTER_ROWS["ProjectAssignments"] if r["EmployeeItemId"] == ME_EMP.item_id])


def ref(upn, request, store, settings, roles=("EMP",), cid="run-rs", fail=(), reg=REG, ovl=OVL):
    ident = TrustedIdentity(upn=upn, group_ids=["g-" + r.lower() for r in roles])
    lk = lambda n: [e for e in tg.EMPS if e.account_upn == n]  # noqa: E731
    g = G.authorize(ident, lk, lk, tg.CFG, tg.POLICY, "TS.EditOwnDraft", "self", correlation_id=cid)
    emp = next((e for e in tg.EMPS if e.account_upn == upn), None)
    caller = E.Caller(upn, emp.item_id, emp.legacy_id, emp.discipline_id) if emp and g.allowed else None
    s = cfg.resolve(reg, ovl, settings)
    lists = set(MASTER_ROWS) - ({"ProjectAssignments"} if cfg.plain(s).get("ProjectAssignmentScoping") != "On" else set())
    m = None if set(fail) & lists else masters()  # the reference takes reference data all-or-nothing
    r = E.save_entry(g, caller, {k: v for k, v in request.items() if v != ""}, m, s, store, correlation_id=cid)
    return {"ok": r.ok, "code": r.code, "messageCode": r.messageCode, "itemId": r.itemId, "etag": r.etag, "correlationId": cid,
            "warnings": r.warnings, "interim": r.interim}, r


class _Both(unittest.TestCase):
    def both(self, upn, request, items=ITEMS, settings=SCOPING_OFF + [], decoys=None, race=False, readback="ok", **kw):
        fs, rs = Store(items, race, readback), Store(items, race, readback)
        f, posts, writes, run = run_flow(upn, request, fs, settings, decoys=decoys, **kw)
        r, rr = ref(upn, request, rs, settings, **kw)
        self.assertEqual(f, r, "reference vs flow differ for %s" % request)
        self.assertEqual(fs.state(), rs.state(), "stored rows differ for %s" % request)
        self.ctx = dict(store=fs, posts=posts, writes=writes, run=run, ref=rr)
        return f

    def code(self, request, **kw):
        return self.both(ME, request, **kw)["code"]

    def nothing_written(self):
        self.assertEqual(self.ctx["writes"], [])


class R1Save(_Both):

    def test_RS01_create_own_draft(self):
        f = self.both(ME, req())
        self.assertEqual((f["ok"], f["code"], f["itemId"], f["etag"]), (True, "OK", 7, '"7,1"'))
        row = self.ctx["store"].items[7]
        self.assertEqual((row["OwnerUpn"], row["ActorUpn"], row["EntryStatus"], row["LegacyOrigin"], row["IsOnBehalf"]),
                         (ME, ME, "Draft", "New", False))
        self.assertEqual((row["EmployeeId"], row["EmployeeItemId"], row["DisciplineCode"]), (ME_EMP.item_id, ME_EMP.item_id, "D1"))
        self.assertEqual(row["WorkDate"], "2026-10-08T17:00:00Z")  # local midnight of the business date, as POC P4 observed
        self.assertTrue(re.fullmatch(r"[0-9a-f-]{36}", row["LegacyId"]))
        self.assertEqual(self.ctx["writes"][0][2]["WorkDate"], "2026-10-09")  # yyyy-MM-dd over JSON, never the validate API

    def test_RS02_forged_identity_and_status_ignored(self):
        f = self.both(ME, req(), decoys={"OwnerUpn": OTHER, "ActorUpn": OTHER, "EmployeeId": "12", "Role": "ADM",
                                         "Scope": "company", "EntryStatus": "Approved"})
        row = self.ctx["store"].items[f["itemId"]]
        self.assertEqual((row["OwnerUpn"], row["ActorUpn"], row["EmployeeId"], row["EntryStatus"]), (ME, ME, ME_EMP.item_id, "Draft"))
        self.assertEqual(self.ctx["run"].results["Guard_result"]["outputs"]["IgnoredInputs"], sorted(DECOYS))

    def test_RS03_edit_own_draft(self):
        f = self.both(ME, req(ItemId="1", ETag='"1,1"', Hours="3", Remark="changed"))
        self.assertEqual((f["ok"], f["code"], f["itemId"], f["etag"]), (True, "OK", 1, '"1,2"'))
        row = self.ctx["store"].items[1]
        self.assertEqual((row["Hours"], row["Remark"], row["OwnerUpn"], row["EntryStatus"]), (3.0, "changed", ME, "Draft"))
        uri, headers, body = self.ctx["writes"][0]
        self.assertEqual(headers["IF-MATCH"], '"1,1"')
        self.assertFalse({"OwnerUpn", "EmployeeId", "EmployeeItemId", "EntryStatus", "LegacyId"} & set(body), "owner/status never rewritten")

    def test_RS04_stale_etag_conflict(self):
        f = self.both(ME, req(ItemId="1", ETag='"1,0"'))
        self.assertEqual((f["ok"], f["code"], f["itemId"], f["etag"]), (False, "CONFLICT", 1, ""))
        self.nothing_written()

    def test_RS05_concurrent_change_at_write_is_conflict(self):
        f = self.both(ME, req(ItemId="1", ETag='"1,1"'), race=True)
        self.assertEqual((f["code"], f["itemId"]), ("CONFLICT", 1))
        self.assertEqual(self.ctx["store"].items[1]["Hours"], 2.0)

    def test_RS06_foreign_entry_forbidden(self):
        self.assertEqual(self.code(req(ItemId="2", ETag='"2,1"')), "FORBIDDEN")
        self.nothing_written()

    def test_RS07_approved_entry_locked(self):
        self.assertEqual(self.code(req(ItemId="3", ETag='"3,1"')), "LOCKED")
        self.nothing_written()

    def test_RS08_deleted_missing_or_bad_item_not_found(self):
        for item_id in ("4", "99", "abc", "-3", "1.5"):
            self.assertEqual(self.code(req(ItemId=item_id, ETag='"%s,1"' % item_id)), "NOT_FOUND", item_id)
            self.nothing_written()

    def test_RS09_project_unknown_or_paused(self):
        for pc in ("P9", "P2", "", "P1' or 1 eq 1"):
            self.assertEqual(self.code(req(ProjectCode=pc)), "VALIDATION_LOOKUP", pc)
        self.assertEqual(self.code(req(ProjectCode="o'hara")), "OK")  # quote in a code: escaped, case-insensitive

    def test_RS10_phase_must_belong_to_project_and_be_active(self):
        for ph in ("PH2", "PH3", "PH9", ""):  # inactive phase / inactive project-phase / unknown / missing
            self.assertEqual(self.code(req(PhaseCode=ph)), "VALIDATION_LOOKUP", ph)
        self.assertEqual(self.code(req(ProjectCode="P3", PhaseCode="PH3")), "OK")
        self.assertEqual(self.code(req(PhaseCode="PH4")), "OK")  # IsActive not set counts as active

    def test_RS11_work_type_shift_hour_type(self):
        for kw in ({"WorkTypeCode": "WT2"}, {"WorkTypeCode": "WTX"}, {"ShiftCode": "SX"}, {"HourTypeCode": "XX"}):
            self.assertEqual(self.code(req(**kw)), "VALIDATION_LOOKUP", kw)
        self.assertEqual(self.code(req(ShiftCode="s2", HourTypeCode="ot")), "OK")

    def test_RS12_hours(self):
        for h in ("0", "-1", "24.01", "abc", "1.", ".5", "", "1e1", "2,5"):
            self.assertEqual(self.code(req(Hours=h)), "VALIDATION_HOURS", h)
            self.nothing_written()
        for h in ("24", "0.25", "007.5"):
            self.assertEqual(self.code(req(Hours=h)), "OK", h)

    def test_RS13_dates(self):
        for d in ("2026-02-30", "07/10/2026", "", "2026-1-07", "2026-10-07T00:00:00Z"):
            self.assertEqual(self.code(req(WorkDate=d)), "VALIDATION_DATE", d)
            self.nothing_written()

    def test_RS14_entry_hours_warning_does_not_block(self):
        f = self.both(ME, req(Hours="4.5"))
        self.assertEqual((f["ok"], f["warnings"]), (True, ["WARN_HOURS_ENTRY"]))
        self.assertIn(f["itemId"], self.ctx["store"].items)
        self.assertEqual(self.both(ME, req(Hours="4"))["warnings"], [])

    def test_RS15_day_hours_warning(self):
        f = self.both(ME, req(WorkDate="2026-10-08", Hours="1.5", ShiftCode="S2"))
        self.assertEqual((f["ok"], f["warnings"]), (True, ["WARN_HOURS_DAY"]))  # 6 + 5 + 1.5 > 12
        self.assertEqual(self.both(ME, req(WorkDate="2026-10-08", Hours="1", ShiftCode="S2"))["warnings"], [])  # 12 is not > 12
        f = self.both(ME, req(ItemId="5", ETag='"5,1"', WorkDate="2026-10-08", Hours="7", ShiftCode="S2"))
        self.assertEqual(f["warnings"], ["WARN_HOURS_ENTRY"])  # the edited entry itself is not counted twice: 5 + 7

    def test_RS16_duplicate_warning_ignores_deleted_and_other_owners(self):
        f = self.both(ME, req(WorkDate="2026-10-07"))
        self.assertEqual(f["warnings"], ["WARN_DUPLICATE"])  # item 1 (own Draft); 2 is foreign, 4 is Deleted
        f = self.both(ME, req(WorkDate="2026-10-07", ShiftCode="S2"))
        self.assertEqual(f["warnings"], [])

    def test_RS17_same_day_is_the_business_day(self):
        items = ITEMS + [entry(7, ME, "2026-10-10", hours=11)]  # stored 2026-10-09T17:00:00Z
        f = self.both(ME, req(WorkDate="2026-10-10", Hours="2"), items=items)
        self.assertEqual(f["warnings"], ["WARN_HOURS_DAY", "WARN_DUPLICATE"])
        self.assertIn("WorkDate ge datetime'2026-10-09T17:00:00Z' and WorkDate lt datetime'2026-10-10T17:00:00Z'",
                      self.ctx["run"].results["Day_filter"]["outputs"])
        f = self.both(ME, req(WorkDate="2026-10-09", Hours="2"), items=items)
        self.assertEqual(f["warnings"], [])

    def test_RS18_settings_fail_closed(self):
        self.assertEqual(self.code(req(), settings=[]), "CONFIG_UNRESOLVED")  # scoping switch unresolved: never assumed Off
        self.nothing_written()
        self.assertEqual(self.code(req(), settings=[{"Title": "ProjectAssignmentScoping", "Value": "Maybe"}]), "CONFIG_INVALID")
        self.assertEqual(self.code(req(), settings=SCOPING_OFF + [{"Title": "MaxHoursPerDayWarn", "Value": "x"}]), "CONFIG_INVALID")
        self.assertEqual(self.code(req(), settings=SCOPING_OFF + [{"Title": "BusinessTimezone", "Value": "Europe/Paris"}]), "CONFIG_INVALID")
        self.assertEqual(self.code(req(), settings=SCOPING_OFF + [{"Title": "PayPeriodStartDay", "Value": "31"}]), "CONFIG_INVALID")

    def test_RS19_b03_interim_off_engineering_only(self):
        f = self.both(ME, req(), settings=[], ovl=B03)
        self.assertEqual((f["ok"], f["interim"]), (True, ["ProjectAssignmentScoping"]))
        uat = dict(B03, environment="UAT")
        self.assertEqual(self.code(req(), settings=[], ovl=uat), "CONFIG_UNRESOLVED")  # interim refused outside its environment
        self.assertEqual(self.both(ME, req(), settings=SCOPING_OFF)["interim"], [])
        for purpose, ovl in (("UAT", B03), ("PRODUCTION", dict(B03, environment="PRODUCTION"))):
            with self.assertRaises(ValueError, msg=purpose):
                build(ovl=ovl, purpose=purpose)

    def test_RS20_assignment_scoping_on(self):
        on = [{"Title": "ProjectAssignmentScoping", "Value": "On"}]
        self.assertEqual(self.code(req(), settings=on), "OK")
        self.assertEqual(self.code(req(ProjectCode="P3", PhaseCode="PH3"), settings=on), "VALIDATION_LOOKUP")

    def test_RS21_reference_data_unavailable_fails_closed(self):
        for lst in ("Projects", "Phases", "ProjectPhases", "WorkTypes", "Shifts", "HourTypes"):
            self.assertEqual(self.code(req(), fail=(lst,)), "ERROR", lst)
            self.nothing_written()
        on = [{"Title": "ProjectAssignmentScoping", "Value": "On"}]
        self.assertEqual(self.code(req(), settings=on, fail=("ProjectAssignments",)), "ERROR")
        self.assertEqual(self.code(req(), fail=("ProjectAssignments",)), "OK")  # not read while scoping is Off

    def test_RS22_denied_identity_writes_nothing(self):
        for upn, code in ((tg.u("stranger"), "UNMAPPED_IDENTITY"), (tg.u("gone"), "INACTIVE_EMPLOYEE")):
            f = self.both(upn, req())
            self.assertEqual((f["ok"], f["code"], f["itemId"]), (False, code, 0))
            self.nothing_written()
            ev = {p["EventType"]: p for p in self.ctx["posts"] if p.get("EventType")}
            self.assertEqual((ev["AuthorizationDeny"]["Decision"], ev["WriteProxy"]["Decision"], ev["WriteProxy"]["Action"]),
                             ("DENY", "DENY", "Save"))
        self.assertEqual(self.both(ME, req(), roles=())["code"], "ROLE_NOT_ALLOWED")
        self.nothing_written()

    def test_RS23_audit_one_correlation_id(self):
        for request, action in ((req(), "Create"), (req(ItemId="1", ETag='"1,1"'), "Update"), (req(Hours="0"), "Save")):
            f = self.both(ME, request, cid="run-corr-%s" % action)
            posts = self.ctx["posts"]
            self.assertTrue(posts and all(p.get("CorrelationId") == f["correlationId"] == "run-corr-" + action for p in posts))
            ev = [p for p in posts if p.get("EventType")]
            self.assertEqual([p["EventType"] for p in ev], ["AuthorizationAllow", "WriteProxy"])
            self.assertEqual((ev[1]["Action"], ev[1]["Decision"]), (action, "ALLOW" if f["ok"] else "DENY"))
            self.assertEqual(self.ctx["ref"].audit[0]["Action"], action)
            if f["ok"]:
                self.assertEqual(self.ctx["store"].items[f["itemId"]]["CorrelationId"], "run-corr-" + action)

    def test_RS24_period_key(self):
        for d, pk in (("2026-10-25", "2026-10"), ("2026-10-26", "2026-11"), ("2026-12-26", "2027-01"), ("2026-12-01", "2026-12"),
                      ("2026-09-30", "2026-10")):
            f = self.both(ME, req(WorkDate=d))
            self.assertEqual(self.ctx["store"].items[f["itemId"]]["PeriodKey"], pk, d)

    def test_RS25_template_hygiene(self):
        blob = json.dumps(FLOW)
        self.assertNotIn('"connectionName"', blob)
        self.assertEqual(set(re.findall(r'"connectionReferenceLogicalName": "([^"]+)"', blob)),
                         {"<PFX>_CR_SharePoint_OpsService", "<PFX>_CR_O365Users_Invoker", "<PFX>_CR_O365Groups_OpsService"})
        for word in ("recycle", "DELETE", "ApprovedBy", "ApprovedOn", "RequestKey", "AddValidateUpdateItemUsingPath", "spike"):
            self.assertNotIn(word, blob)
        self.assertEqual(re.findall(r"[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.", blob), [], "no bound account")
        with self.assertRaises(ValueError):
            build(idempotency="request-key")
        self.both(ME, req(Hours="x"))
        self.assertNotIn("_api", json.dumps(self.ctx["run"].results["Respond"]["outputs"]))


class R1SaveEtag(_Both):
    """ET01-ET07: the new ETag after a write. A persisted write is never reported as failed because its ETag could
    not be read back, and the ETag the client sent is never returned as the new one."""
    def edit(self, readback="ok", etag='"1,1"', **kw):
        return self.both(ME, req(ItemId="1", ETag=etag, Hours="3"), readback=readback, **kw)

    def test_ET01_edit_returns_new_etag(self):
        f = self.edit()
        self.assertEqual((f["ok"], f["etag"], f["warnings"]), (True, '"1,2"', []))

    def test_ET02_edit_succeeds_when_etag_readback_fails(self):
        f = self.edit("fail")
        self.assertEqual((f["ok"], f["code"], f["itemId"], f["etag"]), (True, "OK", 1, ""))
        self.assertEqual(self.ctx["store"].items[1]["Hours"], 3.0)

    def test_ET03_old_etag_never_returned_as_new(self):
        for mode in ("fail", "stale"):
            f = self.edit(mode)
            self.assertNotEqual(f["etag"], '"1,1"', mode)
            self.assertEqual(f["etag"], "", mode)

    def test_ET04_contract_says_reload_required(self):
        for mode in ("fail", "stale"):
            f = self.edit(mode)
            self.assertIn("WARN_RELOAD_REQUIRED", f["warnings"], mode)
        self.assertNotIn("WARN_RELOAD_REQUIRED", self.edit()["warnings"])
        f = self.both(ME, req(ItemId="1", ETag='"1,1"', Hours="4.5"), readback="fail")
        self.assertEqual(f["warnings"], ["WARN_HOURS_ENTRY", "WARN_RELOAD_REQUIRED"], "other warnings are kept")

    def test_ET05_next_edit_with_stale_etag_conflicts(self):
        self.edit("fail")
        store = self.ctx["store"]
        f, _, writes, _ = run_flow(ME, req(ItemId="1", ETag='"1,1"', Hours="5"), store, SCOPING_OFF)
        self.assertEqual((f["ok"], f["code"]), (False, "CONFLICT"))
        self.assertEqual((writes, store.items[1]["Hours"]), ([], 3.0))
        current = store.get(1)[1]  # what a re-read returns
        f, _, _, _ = run_flow(ME, req(ItemId="1", ETag=current, Hours="5"), store, SCOPING_OFF)
        self.assertEqual(f["code"], "OK")

    def test_ET06_create_returns_usable_etag(self):
        f = self.both(ME, req())
        self.assertEqual((f["etag"], f["warnings"]), ('"7,1"', []))
        g, _, _, _ = run_flow(ME, req(ItemId="7", ETag=f["etag"], Hours="3"), self.ctx["store"], SCOPING_OFF)
        self.assertEqual(g["code"], "OK", "the returned ETag is usable for the next edit")
        f = self.both(ME, req(), readback="fail")
        self.assertEqual((f["ok"], f["itemId"], f["etag"], f["warnings"]), (True, 7, "", ["WARN_RELOAD_REQUIRED"]))

    def test_ET07_persisted_write_not_reported_as_failed(self):
        for mode in ("fail", "stale"):
            f = self.edit(mode)
            self.assertTrue(f["ok"], mode)
            posts = self.ctx["posts"]
            wp = next(p for p in posts if p.get("EventType") == "WriteProxy")
            self.assertEqual((wp["Action"], wp["Decision"]), ("Update", "ALLOW"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
