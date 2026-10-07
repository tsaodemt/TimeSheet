"""R1 flows (offline templates; NOT deployed): TS-ReadOwn and TS-SaveEntry. Reference: tools/timesheet/entries.py.

Both reuse the proven pieces: trusted caller + guard (guard_template), AppSettings read by the service connection with
the same per-key validation as the app-start flow (build_appstart_flow.setting_value_actions), business-date filter
(date_range, proven live by POC P4), audit rows (audit_template), one correlation ID (the flow run name).
Connections are solution connection-reference placeholders only (no account bound).
"""
from __future__ import annotations

import json
import os
import sys

import audit_template as at
import build_appstart_flow as baf
import build_read_flow as base
import date_range as dr
import guard_template as gt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audit"))
import app_settings as cfg  # noqa: E402
import audit_event as ae  # noqa: E402

c, S, EMPTY, o, nz, esc = base.c, base.S, base.EMPTY, gt.o, gt.nz, gt.esc
DECOYS = ["OwnerUpn", "ActorUpn", "EmployeeId", "Role", "Scope"]
ENTRIES = "TimesheetEntries"
_lit = baf._lit


def _tb(key):
    return "trim(if(empty(triggerBody()?['%s']), %s, string(triggerBody()?['%s'])))" % (key, EMPTY, key)


def _sp(name_after, method, uri, *, body=None, headers=None, meta="minimalmetadata"):
    h = {"Accept": "application/json;odata=%s" % meta, "Content-Type": "application/json;odata=%s" % meta}
    h.update(headers or {})
    p = {"dataset": "@{outputs('SiteUrl')}", "parameters/method": method, "parameters/uri": uri, "parameters/headers": h}
    if body is not None:
        p["parameters/body"] = body
    return base.op(base.SP, "HttpRequest", p, name_after)


def _digits_removed(v):
    return baf._digits_removed(v)


def _int_text_ok(x):
    """Optional leading '-', then digits (reference: int(str))."""
    core = "if(startsWith(%s, '-'), substring(%s, 1), %s)" % (x, x, x)
    return "and(not(empty(%s)), empty(%s))" % (core, _digits_removed(core))


def _date_shape_ok(x):
    return "and(equals(length(%s), 10), equals(%s, '--'))" % (x, _digits_removed(x))


def _settings(g, registry, overlay, keys, after, settings_list):
    g["Settings_read"] = base.sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=Title,Value&$top=500" % settings_list, S(after))
    g["Settings_rows"] = c("@if(equals(actions('Settings_read')?['status'], 'Succeeded'), body('Settings_read')?['value'], createArray())",
                           {"Settings_read": ["Succeeded", "Failed"]})
    rules = baf._rules(registry, overlay, keys=keys)
    missing = set(keys) - {r["key"] for r in rules}
    if missing:
        raise ValueError("settings not in the registry: %s" % sorted(missing))
    return baf.setting_value_actions(g, rules, "Settings_rows")


def read_own_actions(*, scope_config, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                     registry, overlay, settings_list="AppSettings", source_flow="TS-ReadOwn", refs=None) -> dict:
    """Trigger: text FromDate, text_1 ToDate, text_2 AfterId, text_3 PageSize, text_4 RequestedOwner, text_5..9 decoys."""
    g = gt.guard_actions(scope_config, role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list,
                         action_expr="'TS.ViewOwn'", kind_expr="'self'", ref_expr=EMPTY, untrusted_inputs=DECOYS, legacy_audit=False)
    g.update(at.authorization_event_actions(audit_list=audit_list, environment=environment, source_flow=source_flow,
                                            after="Guard_result", name="Authz_audit"))
    g["From"] = c("@" + _tb("text"), S("Write_Authz_audit"))
    g["To"] = c("@" + _tb("text_1"), S("From"))
    g["AfterRaw"] = c("@" + _tb("text_2"), S("To"))
    g["SizeRaw"] = c("@" + _tb("text_3"), S("AfterRaw"))
    g["ReqOwner"] = c("@toLower(%s)" % _tb("text_4"), S("SizeRaw"))
    F, T = o("From"), o("To")
    g["Date_check"] = dict(c("@concat(formatDateTime(if(empty(%s), '2000-01-01', %s), 'yyyy-MM-dd'), formatDateTime(if(empty(%s), '2000-01-01', %s), 'yyyy-MM-dd'))"
                             % (F, F, T, T), S("ReqOwner")), metadata={"failOnError": True})
    status, value, _, last = _settings(g, registry, overlay, ["BusinessTimezone"], "Date_check", settings_list)
    g["Settings_read"]["runAfter"] = {"Date_check": ["Succeeded", "Failed"]}
    trusted = o("Trusted")
    has = "or(not(empty(%s)), not(empty(%s)))" % (F, T)
    # the reversed-range test only ever sees well-formed dates: invalid input is replaced before any date function runs
    both_ok = "and(%s, %s, equals(actions('Date_check')?['status'], 'Succeeded'))" % (_date_shape_ok(F), _date_shape_ok(T))
    date_bad = ("or(not(equals(actions('Date_check')?['status'], 'Succeeded')), not(equals(empty(%s), empty(%s))), "
                "and(not(empty(%s)), not(%s)), and(not(empty(%s)), not(%s)), "
                "and(not(empty(%s)), not(empty(%s)), %s))"
                % (F, T, F, _date_shape_ok(F), T, _date_shape_ok(T), F, T,
                   dr.reversed_range_expr("if(%s, %s, '2000-01-01')" % (both_ok, F), "if(%s, %s, '2000-01-01')" % (both_ok, T))))
    checks = [
        ("not(equals(outputs('Guard_result')?['ResultCode'], 'ALLOW'))", "outputs('Guard_result')?['ResultCode']"),
        ("and(not(empty(%s)), not(equals(%s, %s)))" % (o("ReqOwner"), o("ReqOwner"), trusted), "'FORBIDDEN'"),
        (date_bad, "'VALIDATION_DATE'"),
        ("not(equals(%s, 'OK'))" % status["BusinessTimezone"], "'CONFIG_UNRESOLVED'"),
        ("or(and(not(empty(%s)), not(%s)), and(not(empty(%s)), not(%s)))" % (o("AfterRaw"), _int_text_ok(o("AfterRaw")),
                                                                           o("SizeRaw"), _int_text_ok(o("SizeRaw"))), "'VALIDATION_LOOKUP'"),
    ]
    expr = "'OK'"
    for cond, code in reversed(checks):
        expr = "if(%s, %s, %s)" % (cond, code, expr)
    g["Validation"] = c("@" + expr, S(last))
    safe_int = lambda x: "int(if(%s, %s, '0'))" % (_int_text_ok(x), x)  # noqa: E731
    g["After"] = c("@if(empty(%s), 0, max(%s, 0))" % (o("AfterRaw"), safe_int(o("AfterRaw"))), S("Validation"))
    g["Size"] = c("@if(empty(%s), 500, min(max(%s, 1), 500))" % (o("SizeRaw"), safe_int(o("SizeRaw"))), S("After"))
    win = value["BusinessTimezone"]
    clause = "if(%s, %s, %s)" % (has, dr.date_clause_expr("WorkDate", "if(empty(%s), '2000-01-01', %s)" % (F, F),
                                                         "if(empty(%s), '2000-01-01', %s)" % (T, T),
                                                         "if(equals(%s, null), 'UTC', %s)" % (win, win), tz_is_expression=True), EMPTY)
    sel = "Id,WorkDate,ProjectId,PhaseId,WorkTypeId,ShiftId,HourTypeId,Hours,Remark,EntryStatus,OwnerUpn"
    # the filter is composed only inside the validated branch: no date or zone expression runs on invalid input
    filt = c("@concat('OwnerUpn eq ''', %s, ''' and ', %s, 'EntryStatus ne ''Deleted'' and Id gt ', string(%s))"
             % (esc(trusted), clause, o("After")), {})
    query = _sp(S("Filter"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=%s&$filter=@{outputs('Filter')}&$orderby=Id asc&$top=@{outputs('Size')}"
                % (ENTRIES, sel))
    g["If_ok"] = {"type": "If", "runAfter": S("Size"), "expression": {"equals": ["@outputs('Validation')", "OK"]},
                  "actions": {"Filter": filt, "Query": query}, "else": {"actions": {}}}
    rows = _rows("Query")
    g["Rows"] = c("@" + rows, {"If_ok": ["Succeeded", "Failed", "Skipped", "TimedOut"]})
    g["Leak"] = {"type": "Query", "runAfter": S("Rows"), "inputs": {"from": "@outputs('Rows')", "where":
                 "@or(not(equals(toLower(%s), %s)), equals(%s, 'Deleted'))" % (nz("item()?['OwnerUpn']"), trusted, nz("item()?['EntryStatus']"))}}
    g["Final_code"] = c("@if(not(equals(outputs('Validation'), 'OK')), outputs('Validation'), if(not(equals(actions('Query')?['status'], 'Succeeded')), 'ERROR', "
                        "if(greater(length(body('Leak')), 0), 'ERROR_LEAK', 'OK')))", S("Leak"))
    ok = "equals(outputs('Final_code'), 'OK')"
    g["Out_rows"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {
        "from": "@if(%s, outputs('Rows'), createArray())" % ok,
        "select": {"id": "@item()?['Id']", "workDate": "@convertFromUtc(item()?['WorkDate'], %s, 'yyyy-MM-dd')" % win,
                   "projectId": "@item()?['ProjectId']", "phaseId": "@item()?['PhaseId']", "workTypeId": "@item()?['WorkTypeId']",
                   "shiftId": "@item()?['ShiftId']", "hourTypeId": "@item()?['HourTypeId']", "hours": "@item()?['Hours']",
                   "remark": "@item()?['Remark']", "status": "@item()?['EntryStatus']", "etag": "@item()?['odata.etag']"}}}
    g["Next"] = c("@if(and(%s, equals(length(body('Out_rows')), outputs('Size'))), last(body('Out_rows'))?['id'], 0)" % ok, S("Out_rows"))
    g.update(at.operation_event_actions("ReadProxy", "ReadOwn", target_entity=ENTRIES, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                        environment=environment, source_flow=source_flow,
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, after="Next", name="Read_audit"))
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "rows": "@{string(body('Out_rows'))}", "nextafterid": "@{string(outputs('Next'))}",
            "pagesize": "@{string(if(%s, outputs('Size'), 0))}" % ok}
    g["Respond"] = {"type": "Response", "kind": "PowerApp", "runAfter": S("Write_Read_audit"),
                    "inputs": {"statusCode": 200, "body": body, "schema": {"type": "object", "properties": {
                        k: {"title": k, "x-ms-dynamically-added": True, "type": "string"} for k in body}}}}
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- TS-SaveEntry (create / edit own draft)

SAVE_SETTINGS = ("PayPeriodStartDay", "MaxHoursPerEntryWarn", "MaxHoursPerDayWarn", "ProjectAssignmentScoping", "BusinessTimezone")
SAVE_DECOYS = DECOYS + ["EntryStatus"]
# list -> (code column, extra column, active test on a row); a missing IsActive counts as active, as in the reference
MASTERS = {
    "Projects": ("ProjectCode", "Status", "equals(%s?['Status'], 'Active')"),
    "Phases": ("PhaseCode", "IsActive", "not(equals(%s?['IsActive'], false))"),
    "WorkTypes": ("WorkTypeCode", "IsActive", "not(equals(%s?['IsActive'], false))"),
    "Shifts": ("ShiftCode", "IsActive", "not(equals(%s?['IsActive'], false))"),
    "HourTypes": ("HourTypeCode", None, "not(equals(%s, null))"),
}
LOOKUPS = (("Projects", "Get_project", "PC", "ProjectId"), ("Phases", "Get_phase", "PH", "PhaseId"),
           ("WorkTypes", "Get_worktype", "WT", "WorkTypeId"), ("Shifts", "Get_shift", "SH", "ShiftId"),
           ("HourTypes", "Get_hourtype", "HT", "HourTypeId"))


def _raw(key):
    """Untrimmed text input (ETag, Remark: compared / stored as sent)."""
    return "if(empty(triggerBody()?['%s']), %s, string(triggerBody()?['%s']))" % (key, EMPTY, key)


def _ab(name):
    """Null-safe body of an action that may have been skipped."""
    return "actions('%s')?['outputs']?['body']" % name


def _okd(name):
    return "equals(actions('%s')?['status'], 'Succeeded')" % name


def _rows(name):
    return "if(%s, %s?['value'], createArray())" % (_okd(name), _ab(name))


def _q(x):
    """A value inside an OData string literal in the request URI: quotes doubled, then URI-encoded."""
    return "encodeUriComponent(replace(%s, '''', ''''''))" % x


def _decimal_ok(x):
    rest = _digits_removed(x)
    return ("and(not(empty(%s)), or(empty(%s), equals(%s, '.')), not(startsWith(%s, '.')), not(endsWith(%s, '.')))"
            % (x, rest, rest, x, x))


def _period_key(wd, start_day):
    """BR-DATE-02 on a validated 'yyyy-MM-dd': on/after the start day -> next month's period (Dec -> January next year)."""
    y, m, d = "int(substring(%s, 0, 4))" % wd, "int(substring(%s, 5, 2))" % wd, "int(substring(%s, 8, 2))" % wd
    nm = "add(%s, 1)" % m
    nxt = ("if(equals(%s, 12), concat(string(add(%s, 1)), '-01'), concat(substring(%s, 0, 4), '-', if(less(%s, 10), '0', %s), string(%s)))"
           % (m, y, wd, nm, EMPTY, nm))
    return "if(less(%s, %s), substring(%s, 0, 7), %s)" % (d, start_day, wd, nxt)


def save_draft_actions(*, scope_config, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                       registry, overlay, purpose="ENGINEERING", idempotency="none", settings_list="AppSettings",
                       source_flow="TS-SaveEntry", refs=None) -> dict:
    """Create / edit own draft. Trigger: text ItemId, text_1 ETag, text_2 WorkDate, text_3 ProjectCode, text_4 PhaseCode,
    text_5 WorkTypeCode, text_6 ShiftCode, text_7 HourTypeCode, text_8 Hours, text_9 Remark, text_10..15 decoys
    (OwnerUpn, ActorUpn, EmployeeId, Role, Scope, EntryStatus: recorded by name, never used).

    No approval, no delete. Create idempotency is R1-Q3 (open): only "none" can be generated. UAT and PRODUCTION
    builds refuse interim or unapproved settings (B-03 interim Off is engineering only)."""
    if idempotency != "none":
        raise ValueError("create idempotency is an open decision (R1-Q3): only 'none' can be generated")
    if purpose not in cfg.PURPOSES:
        raise ValueError("purpose must be one of %s" % (cfg.PURPOSES,))
    if purpose != "ENGINEERING":
        ready, blockers = cfg.readiness(registry, overlay, purpose, SAVE_SETTINGS)
        if not ready:
            raise ValueError("not ready for %s: %s" % (purpose, blockers))
    g = gt.guard_actions(scope_config, role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list,
                         action_expr="'TS.EditOwnDraft'", kind_expr="'self'", ref_expr=EMPTY, untrusted_inputs=SAVE_DECOYS,
                         legacy_audit=False)
    g.update(at.authorization_event_actions(audit_list=audit_list, environment=environment, source_flow=source_flow,
                                            after="Guard_result", name="Authz_audit"))
    prev = "Write_Authz_audit"
    for name, expr in (("ItemRaw", _tb("text")), ("ETagIn", _raw("text_1")), ("WD", _tb("text_2")), ("PC", _tb("text_3")),
                       ("PH", _tb("text_4")), ("WT", _tb("text_5")), ("SH", _tb("text_6")), ("HT", _tb("text_7")),
                       ("HRaw", _tb("text_8")), ("RemarkIn", _raw("text_9"))):
        g[name] = c("@" + expr, S(prev))
        prev = name
    WD, H, ITEM, T = o("WD"), o("HRaw"), o("ItemId"), o("Trusted")
    g["Date_check"] = dict(c("@formatDateTime(if(%s, %s, '2000-01-01'), 'yyyy-MM-dd')" % (_date_shape_ok(WD), WD), S(prev)),
                           metadata={"failOnError": True})
    status, value, interim, last = _settings(g, registry, overlay, list(SAVE_SETTINGS), "Date_check", settings_list)
    g["Settings_read"]["runAfter"] = {"Date_check": ["Succeeded", "Failed"]}
    g["Init_daysum"] = {"type": "InitializeVariable", "runAfter": S(last),
                        "inputs": {"variables": [{"name": "DaySum", "type": "float", "value": 0}]}}
    g["Interim"] = {"type": "Query", "runAfter": S("Init_daysum"), "inputs": {
        "from": "@createArray(%s)" % ", ".join("if(%s, '%s', %s)" % (interim[k], k, EMPTY) for k in sorted(interim)),
        "where": "@not(empty(item()))"}}
    g["ItemId"] = c("@int(if(empty(%s), '0', if(%s, %s, '-1')))" % (o("ItemRaw"), _int_text_ok(o("ItemRaw")), o("ItemRaw")), S("Interim"))
    is_edit = "greater(%s, 0)" % ITEM
    bad_cfg = "or(%s)" % ", ".join("not(equals(%s, 'OK'))" % status[k] for k in SAVE_SETTINGS)
    any_invalid = "or(%s)" % ", ".join("equals(%s, 'INVALID')" % status[k] for k in SAVE_SETTINGS)
    g["Pre"] = c("@if(not(equals(outputs('Guard_result')?['ResultCode'], 'ALLOW')), outputs('Guard_result')?['ResultCode'], "
                 "if(%s, if(%s, 'CONFIG_INVALID', 'CONFIG_UNRESOLVED'), if(less(%s, 0), 'NOT_FOUND', 'OK')))" % (bad_cfg, any_invalid, ITEM), S("ItemId"))
    pre_ok = "equals(outputs('Pre'), 'OK')"

    # edit checks: the stored item (owner, status, ETag), read by the service connection
    g["If_edit"] = {"type": "If", "runAfter": S("Pre"),
                    "expression": {"and": [{"equals": ["@outputs('Pre')", "OK"]}, {"equals": ["@%s" % is_edit, True]}]},
                    "actions": {"Get_item": _sp({}, "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id,OwnerUpn,EntryStatus" % (ENTRIES, ITEM))},
                    "else": {"actions": {}}}
    it = _ab("Get_item")
    stored_etag = "%s?['odata.etag']" % it
    edit = ("if(not(%s), outputs('Pre'), if(not(%s), 'OK', if(not(%s), if(equals(actions('Get_item')?['outputs']?['statusCode'], 404), 'NOT_FOUND', 'ERROR'), "
            "if(equals(%s?['EntryStatus'], 'Deleted'), 'NOT_FOUND', if(not(equals(toLower(%s), %s)), 'FORBIDDEN', "
            "if(not(equals(%s?['EntryStatus'], 'Draft')), 'LOCKED', if(not(equals(%s, %s)), 'CONFLICT', 'OK')))))))"
            % (pre_ok, is_edit, _okd("Get_item"), it, nz("%s?['OwnerUpn']" % it), T, it, o("ETagIn"), nz(stored_etag)))
    g["Edit_code"] = c("@" + edit, {"If_edit": ["Succeeded", "Failed", "Skipped", "TimedOut"]})

    # lookups: reference lists read by code; any unreadable list fails closed (ERROR), nothing is assumed
    first = lambda n: "first(%s)" % _rows(n)  # noqa: E731
    one = lambda n: "equals(length(%s), 1)" % _rows(n)  # noqa: E731
    ids = {fld: "if(%s, %s?['Id'], 0)" % (one(n), first(n)) for _, n, _, fld in LOOKUPS}
    look, after = {}, {}
    for lst, n, src, _ in LOOKUPS:
        col, extra, _ = MASTERS[lst]
        look[n] = _sp(after, "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,%s&$filter=%s eq '@{%s}'&$top=2"
                      % (lst, ",".join(x for x in (col, extra) if x), col, _q(o(src))))
        after = S(n)
    look["Get_pp"] = _sp(after, "GET", "_api/web/lists/getbytitle('ProjectPhases')/items?$select=Id,IsActive"
                         "&$filter=ProjectId eq @{%s} and PhaseId eq @{%s}&$top=1" % (ids["ProjectId"], ids["PhaseId"]))
    look["If_scoping"] = {"type": "If", "runAfter": S("Get_pp"), "expression": {"equals": ["@%s" % value["ProjectAssignmentScoping"], "On"]},
                          "actions": {"Get_assign": _sp({}, "GET", "_api/web/lists/getbytitle('ProjectAssignments')/items?$select=Id"
                                                        "&$filter=EmployeeItemId eq @{outputs('Guard_result')?['EmployeeId']} and ProjectId eq @{%s}&$top=1"
                                                        % ids["ProjectId"])},
                          "else": {"actions": {}}}
    g["If_lookup"] = {"type": "If", "runAfter": S("Edit_code"), "expression": {"equals": ["@outputs('Edit_code')", "OK"]},
                      "actions": look, "else": {"actions": {}}}
    scoping_on = "equals(%s, 'On')" % value["ProjectAssignmentScoping"]
    masters_ok = "and(%s, or(not(%s), %s))" % (", ".join(_okd(n) for n in [x[1] for x in LOOKUPS] + ["Get_pp", "If_scoping"]),
                                               scoping_on, _okd("Get_assign"))
    valid_lookup = "and(%s)" % ", ".join(
        ["and(%s, %s)" % (one(n), MASTERS[lst][2] % first(n)) for lst, n, _, _ in LOOKUPS]
        + ["or(not(%s), greater(length(%s), 0))" % (scoping_on, _rows("Get_assign")),
           "greater(length(%s), 0)" % _rows("Get_pp"), "not(equals(%s?['IsActive'], false))" % first("Get_pp")])
    g["Lookup_code"] = c("@if(not(equals(outputs('Edit_code'), 'OK')), outputs('Edit_code'), if(not(%s), 'ERROR', if(not(%s), 'VALIDATION_LOOKUP', 'OK')))"
                         % (masters_ok, valid_lookup), {"If_lookup": ["Succeeded", "Failed", "Skipped", "TimedOut"]})
    g["Hours"] = c("@float(if(%s, %s, '0'))" % (_decimal_ok(H), H), S("Lookup_code"))
    hours_ok = "and(%s, greater(outputs('Hours'), 0), not(greater(outputs('Hours'), 24)))" % _decimal_ok(H)
    date_ok = "and(%s, equals(actions('Date_check')?['status'], 'Succeeded'))" % _date_shape_ok(WD)
    g["Valid"] = c("@if(not(equals(outputs('Lookup_code'), 'OK')), outputs('Lookup_code'), if(not(%s), 'VALIDATION_HOURS', if(not(%s), 'VALIDATION_DATE', 'OK')))"
                   % (hours_ok, date_ok), S("Hours"))

    # warnings (never block), then the write by the service connection (JSON item POST / MERGE, as proven by POC P4)
    win = value["BusinessTimezone"]
    day = dr.date_clause_expr("WorkDate", WD, WD, win, tz_is_expression=True)
    w = {}
    w["Day_filter"] = c("@concat('OwnerUpn eq ''', %s, ''' and ', %s, 'EntryStatus ne ''Deleted''')" % (esc(T), day), {})
    w["Day_query"] = _sp(S("Day_filter"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,Hours,ProjectId,PhaseId,ShiftId,HourTypeId"
                         "&$filter=@{outputs('Day_filter')}&$orderby=Id asc&$top=500" % ENTRIES)
    w["Same_day"] = {"type": "Query", "runAfter": S("Day_query"), "inputs": {"from": "@%s?['value']" % _ab("Day_query"),
                                                                            "where": "@not(equals(item()?['Id'], %s))" % ITEM}}
    w["Sum_day"] = {"type": "Foreach", "runAfter": S("Same_day"), "foreach": "@body('Same_day')",
                    "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                    "actions": {"Add_hours": {"type": "IncrementVariable", "runAfter": {}, "inputs": {
                        "name": "DaySum", "value": "@if(equals(items('Sum_day')?['Hours'], null), 0, float(items('Sum_day')?['Hours']))"}}}}
    w["Dup"] = {"type": "Query", "runAfter": S("Sum_day"), "inputs": {"from": "@body('Same_day')", "where": "@and(%s)" % ", ".join(
        "equals(item()?['%s'], %s)" % (k, ids[k]) for k in ("ShiftId", "ProjectId", "PhaseId", "HourTypeId"))}}
    w["Warn_all"] = c("@createArray(if(greater(outputs('Hours'), %s), 'WARN_HOURS_ENTRY', %s), if(greater(add(variables('DaySum'), outputs('Hours')), %s), "
                      "'WARN_HOURS_DAY', %s), if(greater(length(body('Dup')), 0), 'WARN_DUPLICATE', %s))"
                      % (value["MaxHoursPerEntryWarn"], EMPTY, value["MaxHoursPerDayWarn"], EMPTY, EMPTY), S("Dup"))
    w["Get_type"] = _sp(S("Warn_all"), "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % ENTRIES)
    G = lambda k: "outputs('Guard_result')?['%s']" % k  # noqa: E731
    common = {"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")},
              "WorkDate": "@{%s}" % WD, **{k: "@%s" % v for k, v in ids.items()}, "Hours": "@outputs('Hours')",
              "Remark": "@{outputs('RemarkIn')}", "ActorUpn": "@{%s}" % T, "IsOnBehalf": False,
              "DisciplineCode": "@{outputs('CallerDisc')}", "PeriodKey": "@{%s}" % _period_key(WD, value["PayPeriodStartDay"]),
              "CorrelationId": "@{workflow()?['run']?['name']}"}
    # create: owner = actor = trusted caller; status forced to Draft. Edit: the owner columns are never rewritten.
    w["Payload_create"] = c(dict(common, OwnerUpn="@{%s}" % T, EmployeeId="@%s" % G("EmployeeId"),
                                 EmployeeItemId="@%s" % G("EmployeeId"), LegacyId="@{guid()}", LegacyOrigin="New", EntryStatus="Draft"), S("Get_type"))
    w["Payload_edit"] = c(dict(common), S("Payload_create"))
    w["If_create"] = {"type": "If", "runAfter": S("Payload_edit"), "expression": {"equals": ["@%s" % is_edit, False]},
                      "actions": {"Create": _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items" % ENTRIES,
                                                body="@{string(outputs('Payload_create'))}", meta="verbose")},
                      "else": {"actions": {
                          "Update": _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s})" % (ENTRIES, ITEM),
                                        body="@{string(outputs('Payload_edit'))}", meta="verbose",
                                        headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % nz(stored_etag)}),
                          "Get_new": _sp(S("Update"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id" % (ENTRIES, ITEM))}}}
    g["If_write"] = {"type": "If", "runAfter": S("Valid"), "expression": {"equals": ["@outputs('Valid')", "OK"]},
                     "actions": w, "else": {"actions": {}}}
    written = "if(%s, %s, %s)" % (is_edit, _okd("Update"), _okd("Create"))
    g["Final_code"] = c("@if(not(equals(outputs('Valid'), 'OK')), outputs('Valid'), if(not(and(%s, %s)), 'ERROR', if(%s, 'OK', "
                        "if(and(%s, equals(actions('Update')?['outputs']?['statusCode'], 412)), 'CONFLICT', 'ERROR'))))"
                        % (_okd("Day_query"), _okd("Get_type"), written, is_edit),
                        {"If_write": ["Succeeded", "Failed", "Skipped", "TimedOut"]})
    ok = "equals(outputs('Final_code'), 'OK')"
    g["Out_id"] = c("@if(%s, if(%s, %s, %s?['d']?['Id']), if(equals(outputs('Final_code'), 'CONFLICT'), %s, 0))"
                    % (ok, is_edit, ITEM, _ab("Create"), ITEM), S("Final_code"))
    # a persisted write stays OK; without a usable new ETag (not read back, or equal to the one sent) the response has
    # no ETag and WARN_RELOAD_REQUIRED, so the client re-reads before another edit and never reuses the old ETag
    g["New_etag"] = c("@" + nz("if(%s, %s?['odata.etag'], %s?['d']?['__metadata']?['etag'])" % (is_edit, _ab("Get_new"), _ab("Create"))), S("Out_id"))
    usable = "and(not(empty(outputs('New_etag'))), not(and(%s, equals(outputs('New_etag'), %s))))" % (is_edit, o("ETagIn"))
    g["Out_etag"] = c("@if(and(%s, %s), outputs('New_etag'), %s)" % (ok, usable, EMPTY), S("New_etag"))
    W = "actions('Warn_all')?['outputs']"
    g["Warnings"] = {"type": "Query", "runAfter": S("Out_etag"), "inputs": {
        "from": "@createArray(%s, if(and(%s, not(%s)), 'WARN_RELOAD_REQUIRED', %s))"
                % (", ".join("if(%s, %s, %s)" % (ok, nz("%s?[%d]" % (W, i)), EMPTY) for i in range(3)), ok, usable, EMPTY),
        "where": "@not(empty(item()))"}}
    g.update(at.operation_event_actions("WriteProxy", "Create", target_entity=ENTRIES, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                        environment=environment, source_flow=source_flow,
                                        target_id_expr="if(greater(outputs('Out_id'), 0), string(outputs('Out_id')), %s)" % EMPTY,
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, owner_employee_id_expr=G("EmployeeId"),
                                        is_on_behalf_expr="false", work_date_expr="if(%s, %s, %s)" % (ok, WD, EMPTY),
                                        after="Warnings", name="Write_proxy"))
    # one WriteProxy row per decision: Create / Update when written, Save when refused
    act = "if(%s, if(%s, 'Update', 'Create'), 'Save')" % (ok, is_edit)
    row = g["Write_proxy"]["inputs"]
    assert ", 'Create', " in row["Title"]
    row["Title"] = row["Title"].replace(", 'Create', ", ", %s, " % act, 1)
    row["Action"] = "@{%s}" % act
    row["ActionText"] = "@{if(%s, if(%s, %s, %s), %s)}" % (ok, is_edit, _lit(ae.ACTION_TEXT["Update"]), _lit(ae.ACTION_TEXT["Create"]), EMPTY)
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "itemid": "@{string(outputs('Out_id'))}",
            "etag": "@{outputs('Out_etag')}", "correlationid": "@{workflow()?['run']?['name']}",
            "warnings": "@{string(body('Warnings'))}", "interim": "@{string(body('Interim'))}"}
    g["Respond"] = {"type": "Response", "kind": "PowerApp", "runAfter": S("Write_Write_proxy"),
                    "inputs": {"statusCode": 200, "body": body, "schema": {"type": "object", "properties": {
                        k: {"title": k, "x-ms-dynamically-added": True, "type": "string"} for k in body}}}}
    return baf.bind_connection_references(base._fix(g), refs)
