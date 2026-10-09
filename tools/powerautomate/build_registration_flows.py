"""R3 M1 flows for S12.5 Hour Registration ("Đăng ký công"): REG-ReadMatrix and REG-SaveMatrix.

Reference: tools/registration/hour_registration.py; contract: OpenSpec change `r3-planning-effort-hour-registration`
(design §8–§9, specs/hour-registration, specs/planning-audit, M1 decisions). Reuses the R1/R2 pieces unchanged: trusted
caller + guard (guard_template; capabilities REG.View / REG.Edit from registration_rules), the mandatory
AuthorizationAllow / Deny row before any business read (audit_template), one correlation id (the run name), coded
DIRECTORY_ERROR / INTERNAL_ERROR responses when the normal path does not complete, AUD-F1 option B (AUDIT_DEGRADED).

REG-SaveMatrix: preflight of every requested cell before the first write (phase in the project's current phase set,
discipline in the master, BLANK / VALUE, value digits + optional '.', <= 2 decimals, >= 0, <= 15 significant digits as a
technical limit, ETag equal to the stored one or empty for a cell without item). Any refusal -> REFUSED, nothing written.
Then each changed cell is written on its own (POST with the unique RegKey, or MERGE ManDays with IF-MATCH = stored ETag,
no retry), followed by the project's stale cells (phase no longer in the project, value not empty) cleared the same way
(OD-08 legacy parity). Exactly one WriteProxy row per committed cell. Clear keeps the item (ManDays = null; no Delete).
"""
from __future__ import annotations

import os
import sys

import audit_template as at
import build_appstart_flow as baf
import build_approval_flows as bf
import build_r1_flows as r1
import guard_template as gt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "registration"))
import hour_registration as hr  # noqa: E402
import registration_rules as rr  # noqa: E402

c, S, EMPTY, o, nz, esc, base = r1.c, r1.S, r1.EMPTY, r1.o, r1.nz, r1.esc, r1.base
_tb, _raw, _sp, _ab, _okd, _rows = r1._tb, r1._raw, r1._sp, r1._ab, r1._okd, r1._rows
LIST = hr.LIST
FAIL_HANDLED = {"failOnError": True}
ANY = ["Succeeded", "Failed", "TimedOut"]
G = lambda k: "outputs('Guard_result')?['%s']" % k  # noqa: E731


def _digits_only(x):
    return "and(not(empty(%s)), empty(%s))" % (x, r1._digits_removed(x))


# Power Apps waits at most 120 s for a flow response (live STAGING: 65 sequential cell writes, ~2 s each -> 504 at 122 s).
# Both per-cell loops run in parallel; loop bodies only Append / Increment shared variables (atomic) or set Degraded to a
# constant true, so the outcome does not depend on iteration order (result order may differ; the Canvas keys by cell).
LOOP_CONCURRENCY = 20


def _safe_int(x):
    return "int(if(%s, %s, '0'))" % (_digits_only(x), x)


def _rq(x):
    """A requested id as an integer. SharePoint returns Number columns as floats (1.0), which do not match
    integer ids in Power Automate comparisons (live STAGING: cells []); both sides are compared as int."""
    return _safe_int("string(%s)" % x)


def _value_ok(v):
    """digits with an optional single inner '.', at most 2 decimals (no sign)."""
    return "and(%s, or(not(contains(%s, '.')), less(length(last(split(%s, '.'))), 3)))" % (r1._decimal_ok(v), v, v)


def _too_long(v):
    return "greater(length(replace(%s, '.', %s)), %d)" % (v, EMPTY, hr.MAX_SIGNIFICANT)


def _guard(capability, decoys, source_flow, **kw):
    g = gt.guard_actions(rr.scope_config(), kw["role_groups"], site=kw["site"], domain=kw["domain"], emp_list=kw["emp_list"],
                         audit_list=kw["audit_list"], action_expr="'%s'" % capability, kind_expr="'self'", ref_expr=EMPTY,
                         untrusted_inputs=decoys, legacy_audit=False, fields=gt.EMPLOYEES_FIELDS)
    g.update(at.authorization_event_actions(audit_list=kw["audit_list"], environment=kw["environment"], source_flow=source_flow,
                                            after="Guard_result", name="Authz_audit"))
    return g


def _data_reads(pid):
    """Project, its current phases (ProjectPhases IsActive, project order), all disciplines, its HourRegistrations."""
    return {
        "Get_project": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items(@{%s})?$select=Id,LegacyId,ProjectCode,Title,Status,ProjectYear" % pid),
        "Get_phases": _sp(S("Get_project"), "GET",
                          "_api/web/lists/getbytitle('ProjectPhases')/items?$select=Id,PhaseId,SortOrder,Phase/LegacyId,Phase/PhaseCode,Phase/Title"
                          "&$expand=Phase&$filter=ProjectItemId eq @{%s} and IsActive eq 1&$orderby=SortOrder asc,Id asc&$top=500" % pid),
        "Get_discs": _sp(S("Get_phases"), "GET",
                         "_api/web/lists/getbytitle('Disciplines')/items?$select=Id,LegacyId,DisciplineCode,Title,SortOrder&$orderby=SortOrder asc,Id asc&$top=500"),
        "Get_items": _sp(S("Get_discs"), "GET",
                         "_api/web/lists/getbytitle('%s')/items?$select=Id,RegKey,PhaseItemId,DisciplineItemId,ManDays&$filter=ProjectItemId eq @{%s}"
                         "&$orderby=Id asc&$top=5000" % (LIST, pid)),
    }


def _reads_ok():
    return "and(%s, %s, %s, %s)" % (_okd("Get_project"), _okd("Get_phases"), _okd("Get_discs"), _okd("Get_items"))


def _project_missing():
    return "and(not(%s), equals(actions('Get_project')?['outputs']?['statusCode'], 404))" % _okd("Get_project")


# ---------------------------------------------------------------- REG-ReadMatrix

def read_matrix_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                        source_flow="REG-ReadMatrix", refs=None) -> dict:
    """Trigger: text ProjectItemId, text_1..4 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = _guard(rr.VIEW, hr.READ_DECOYS, source_flow, **kw)
    g["PidIn"] = c("@" + _tb("text"), S("Write_Authz_audit"))
    g["Pid"] = c("@" + _safe_int(o("PidIn")), S("PidIn"))
    g["Pre"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(greater(outputs('Pid'), 0)), 'VALIDATION_LOOKUP', 'OK'))"
                 % (G("ResultCode"), G("ResultCode")), S("Pid"))
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@outputs('Pre')", "OK"]},
                  "actions": _data_reads(o("Pid")), "else": {"actions": {}}}
    g["Final_code"] = c("@if(not(equals(outputs('Pre'), 'OK')), outputs('Pre'), if(%s, 'NOT_FOUND', if(not(%s), 'ERROR', 'OK')))"
                        % (_project_missing(), _reads_ok()), {"If_ok": ANY})
    ok = "equals(outputs('Final_code'), 'OK')"
    g["Phases"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {
        "from": "@if(%s, %s, createArray())" % (ok, _rows("Get_phases")),
        "select": {"id": "@int(item()?['PhaseId'])", "code": "@item()?['Phase']?['PhaseCode']", "name": "@item()?['Phase']?['Title']"}}}
    g["Phase_ids"] = {"type": "Select", "runAfter": S("Phases"), "inputs": {"from": "@body('Phases')", "select": "@item()?['id']"}}
    g["Discs"] = {"type": "Select", "runAfter": S("Phase_ids"), "inputs": {
        "from": "@if(%s, %s, createArray())" % (ok, _rows("Get_discs")),
        "select": {"id": "@int(item()?['Id'])", "code": "@item()?['DisciplineCode']", "name": "@item()?['Title']"}}}
    g["Current"] = {"type": "Query", "runAfter": S("Discs"), "inputs": {
        "from": "@if(%s, %s, createArray())" % (ok, _rows("Get_items")),
        "where": "@contains(body('Phase_ids'), int(item()?['PhaseItemId']))"}}
    g["Cells"] = {"type": "Select", "runAfter": S("Current"), "inputs": {"from": "@body('Current')", "select": {
        "phaseId": "@int(item()?['PhaseItemId'])", "disciplineId": "@int(item()?['DisciplineItemId'])",
        "state": "@if(equals(item()?['ManDays'], null), 'BLANK', 'VALUE')",
        "value": "@%s" % nz("item()?['ManDays']"), "etag": "@item()?['odata.etag']"}}}
    P = _ab("Get_project")
    g["Project"] = c({"id": "@if(%s, %s?['Id'], null)" % (ok, P), "code": "@if(%s, %s, %s)" % (ok, nz("%s?['ProjectCode']" % P), EMPTY),
                      "name": "@if(%s, %s, %s)" % (ok, nz("%s?['Title']" % P), EMPTY),
                      "status": "@if(%s, %s, %s)" % (ok, nz("%s?['Status']" % P), EMPTY),
                      "year": "@if(%s, %s?['ProjectYear'], null)" % (ok, P)}, S("Cells"))
    editors = "createArray(%s)" % ", ".join("'%s'" % r for r in rr.EDITORS)
    g["CanEdit"] = c("@and(%s, greater(length(intersection(%s, %s)), 0))" % (ok, G("ResolvedRoles"), editors), S("Project"))
    g.update(at.operation_event_actions("ReadProxy", "ReadMatrix", target_entity=LIST, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                        environment=environment, source_flow=source_flow,
                                        target_id_expr="if(greater(outputs('Pid'), 0), string(outputs('Pid')), %s)" % EMPTY,
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, after="CanEdit", name="Read_audit"))
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "project": "@{string(outputs('Project'))}", "phases": "@{string(body('Phases'))}", "disciplines": "@{string(body('Discs'))}",
            "cells": "@{string(body('Cells'))}", "canedit": "@{if(outputs('CanEdit'), 'true', 'false')}"}
    g["Respond"] = bf._respond(body, "Write_Read_audit")
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "project": "{}", "phases": "[]", "disciplines": "[]", "cells": "[]", "canedit": "false"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- REG-SaveMatrix

def _pre_loop(project_legacy):
    """One requested cell (X = items('Pre_loop')): find its item, compute the preflight code, append to variable Pre."""
    X = "items('Pre_loop')"
    ph, dc, st, v, et = ("%s?['%s']" % (X, k) for k in ("phaseId", "disciplineId", "state", "value", "etag"))
    a = {}
    a["Find"] = {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_items"), "where":
                 "@and(equals(int(item()?['PhaseItemId']), %s), equals(int(item()?['DisciplineItemId']), %s))" % (_rq(ph), _rq(dc))}}
    a["Find_phase"] = {"type": "Query", "runAfter": S("Find"), "inputs": {"from": "@%s" % _rows("Get_phases"),
                       "where": "@equals(int(item()?['PhaseId']), %s)" % _rq(ph)}}
    a["Find_disc"] = {"type": "Query", "runAfter": S("Find_phase"), "inputs": {"from": "@%s" % _rows("Get_discs"),
                      "where": "@equals(int(item()?['Id']), %s)" % _rq(dc)}}
    F = "first(body('Find'))"
    stored_val = nz("%s?['ManDays']" % F)
    stored_etag = nz("%s?['odata.etag']" % F)
    found = "not(equals(%s, null))" % F
    has_val = "and(%s, not(equals(%s?['ManDays'], null)))" % (found, F)
    vok = _value_ok(v)
    same = ("if(equals(%(st)s, 'blank'), not(%(hv)s), and(%(hv)s, equals(float(if(empty(%(sv)s), '0', %(sv)s)), float(if(%(vok)s, %(v)s, '0')))))"
            % dict(st=st, hv=has_val, sv=stored_val, vok=vok, v=v))
    code = ("if(not(and(greater(length(body('Find_phase')), 0), greater(length(body('Find_disc')), 0))), 'VALIDATION_LOOKUP', "
            "if(not(or(equals(%(st)s, 'blank'), equals(%(st)s, 'value'))), 'VALIDATION_VALUE', "
            "if(and(equals(%(st)s, 'value'), not(%(vok)s)), 'VALIDATION_VALUE', "
            "if(and(equals(%(st)s, 'value'), %(long)s), 'TECHNICAL_LIMIT', "
            "if(and(not(%(found)s), not(empty(%(et)s))), 'CONFLICT', "
            "if(and(%(found)s, not(equals(%(et)s, %(se)s))), 'CONFLICT', "
            "if(%(same)s, 'NO_CHANGE', 'WRITE')))))))"
            % dict(st=st, vok=vok, long=_too_long(v), found=found, et=et, se=stored_etag, same=same))
    a["P_code"] = c("@" + code, S("Find_disc"))
    key_new = "concat(%s, '|', %s, '|', %s)" % (project_legacy, nz("first(body('Find_phase'))?['Phase']?['LegacyId']"),
                                               nz("first(body('Find_disc'))?['LegacyId']"))
    a["Add_pre"] = {"type": "AppendToArrayVariable", "runAfter": S("P_code"), "inputs": {"name": "Pre", "value": {
        "phaseId": "@%s" % ph, "disciplineId": "@%s" % dc, "state": "@%s" % st, "value": "@%s" % v, "etag": "@%s" % et,
        "code": "@{outputs('P_code')}", "itemId": "@if(%s, %s?['Id'], 0)" % (found, F), "stored": "@%s" % stored_etag,
        "old": "@%s" % stored_val, "regkey": "@if(%s, %s, %s)" % (found, nz("%s?['RegKey']" % F), key_new), "stale": False}}}
    return a


def _write_loop(pid, *, audit_list, conf_audit_list, environment, source_flow):
    """One planned write (W = items('Writes')): NO_CHANGE -> result only; else POST (new item) or MERGE (IF-MATCH stored
    ETag, no retry), read the new ETag, one WriteProxy row when committed, one result entry."""
    W = "items('Writes')"
    w = lambda k: "%s?['%s']" % (W, k)  # noqa: E731
    T = o("Trusted")
    is_new = "equals(%s, 0)" % w("itemId")
    blank = "equals(%s, 'blank')" % w("state")
    newval = "if(%s, null, float(if(%s, '0', %s)))" % (blank, blank, w("value"))
    a = {}
    a["W_create"] = c({"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")},
                       "Title": "@{%s}" % w("regkey"), "RegKey": "@{%s}" % w("regkey"), "LegacyId": "@{%s}" % w("regkey"),
                       "ProjectId": "@%s" % pid, "ProjectItemId": "@%s" % pid, "PhaseId": "@%s" % w("phaseId"),
                       "PhaseItemId": "@%s" % w("phaseId"), "DisciplineId": "@%s" % w("disciplineId"),
                       "DisciplineItemId": "@%s" % w("disciplineId"), "ManDays": "@%s" % newval, "Status": "Active",
                       "ActorUpn": "@{%s}" % T, "CorrelationId": "@{workflow()?['run']?['name']}"}, {})
    a["W_merge"] = c({"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")},
                      "ManDays": "@%s" % newval, "ActorUpn": "@{%s}" % T, "CorrelationId": "@{workflow()?['run']?['name']}"}, S("W_create"))
    create = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items" % LIST, body="@{string(outputs('W_create'))}", meta="verbose")
    merge = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s})" % (LIST, w("itemId")), body="@{string(outputs('W_merge'))}",
                meta="verbose", headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % w("stored")})
    for x in (create, merge):
        x["inputs"]["retryPolicy"] = {"type": "none"}
    a["If_change"] = {"type": "If", "runAfter": S("W_merge"), "expression": {"not": {"equals": ["@%s" % w("code"), "NO_CHANGE"]}},
                      "actions": {"If_new": {"type": "If", "runAfter": {}, "expression": {"equals": ["@%s" % is_new, True]},
                                             "actions": {"Create": create},
                                             "else": {"actions": {"Merge": merge,
                                                                  "Get_new": _sp(S("Merge"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id"
                                                                                 % (LIST, w("itemId")))}}}},
                      "else": {"actions": {}}}
    sc = lambda n: "actions('%s')?['outputs']?['statusCode']" % n  # noqa: E731
    written = "if(%s, %s, %s)" % (is_new, _okd("Create"), _okd("Merge"))
    # create: a duplicate unique RegKey (concurrent creator) is 4xx -> CONFLICT; merge 412 -> CONFLICT; else ERROR
    nn = lambda x: "if(equals(%s, null), 0, %s)" % (x, x)  # noqa: E731 - null-safe status code (untaken branch / skipped action)
    conflict = "if(%s, and(greater(%s, 399), less(%s, 500)), equals(%s, 412))" % (is_new, nn(sc("Create")), nn(sc("Create")), nn(sc("Merge")))
    a["W_final"] = c("@if(equals(%s, 'NO_CHANGE'), 'NO_CHANGE', if(%s, 'OK', if(%s, 'CONFLICT', 'ERROR')))" % (w("code"), written, conflict),
                     {"If_change": ANY})
    ok = "equals(outputs('W_final'), 'OK')"
    a["W_id"] = c("@if(%s, %s, %s)" % (is_new, "if(%s, %s?['d']?['Id'], 0)" % (ok, _ab("Create")), w("itemId")), S("W_final"))
    new_etag = nz("if(%s, %s?['d']?['__metadata']?['etag'], %s?['odata.etag'])" % (is_new, _ab("Create"), _ab("Get_new")))
    a["W_etag"] = c("@if(equals(outputs('W_final'), 'NO_CHANGE'), %s, if(%s, %s, %s))" % (w("stored"), ok, new_etag, EMPTY), S("W_id"))
    action = "if(%s, 'Create', if(%s, 'Clear', 'Update'))" % (is_new, blank)
    ev = at.operation_event_actions("WriteProxy", "Update", target_entity=LIST, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                    environment=environment, source_flow=source_flow, target_id_expr="string(outputs('W_id'))",
                                    target_legacy_id_expr=w("regkey"),
                                    change_fields={"ManDaysOld": w("old"), "ManDays": "if(%s, %s, %s)" % (blank, EMPTY, w("value"))},
                                    after="W_etag", name="Cell_audit")
    # the audit action is the cell's real operation (Create / Update / Clear); ActionText stays legacy-free (no legacy text)
    ev["Cell_audit"]["inputs"]["Action"] = "@{%s}" % action
    ev["Cell_audit"]["inputs"]["Title"] = "@{concat('WriteProxy ', %s, ' ALLOW')}" % action
    ev["Cell_audit"]["inputs"]["ActionText"] = ""
    write_audit = ev.pop("Write_Cell_audit")
    a["If_committed"] = {"type": "If", "runAfter": S("W_etag"), "expression": {"equals": ["@" + ok, True]},
                         "actions": dict({k: dict(v, runAfter=({} if k == "Cell_audit_change" else v["runAfter"])) for k, v in ev.items()},
                                         Write_Cell_audit=write_audit,
                                         Mark_degraded={"type": "SetVariable", "runAfter": {"Write_Cell_audit": ["Failed", "TimedOut"]},
                                                        "inputs": {"name": "Degraded", "value": True}}),
                         "else": {"actions": {}}}
    a["Add_result"] = {"type": "AppendToArrayVariable", "runAfter": {"If_committed": ANY}, "inputs": {"name": "Results", "value": {
        "phaseId": "@%s" % w("phaseId"), "disciplineId": "@%s" % w("disciplineId"), "stale": "@%s" % w("stale"),
        "resultcode": "@{outputs('W_final')}", "etag": "@{outputs('W_etag')}"}}}
    a["Count_saved"] = {"type": "IncrementVariable", "runAfter": S("Add_result"),
                        "inputs": {"name": "Saved", "value": "@if(and(%s, not(%s)), 1, 0)" % (ok, w("stale"))}}
    a["Count_cleared"] = {"type": "IncrementVariable", "runAfter": S("Count_saved"),
                          "inputs": {"name": "Cleared", "value": "@if(and(%s, %s), 1, 0)" % (ok, w("stale"))}}
    a["Count_failed"] = {"type": "IncrementVariable", "runAfter": S("Count_cleared"),
                         "inputs": {"name": "Failed", "value": "@if(or(%s, equals(outputs('W_final'), 'NO_CHANGE')), 0, 1)" % ok}}
    return a


def save_matrix_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                        source_flow="REG-SaveMatrix", refs=None) -> dict:
    """Trigger: text ProjectItemId, text_1 Changes (JSON [{phaseId, disciplineId, state, value, etag}], 1-100),
    text_2 ClientRequestId (correlation only), text_3..7 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = _guard(rr.EDIT, hr.SAVE_DECOYS, source_flow, **kw)
    g["PidIn"] = c("@" + _tb("text"), S("Write_Authz_audit"))
    g["Pid"] = c("@" + _safe_int(o("PidIn")), S("PidIn"))
    g["ChangesRaw"] = c("@" + _raw("text_1"), S("Pid"))
    g["ClientRequestId"] = c("@" + _tb("text_2"), S("ChangesRaw"))
    for v, typ, val in (("Pre", "array", "@json('[]')"), ("Results", "array", "@json('[]')"), ("Saved", "integer", 0),
                        ("Cleared", "integer", 0), ("Failed", "integer", 0), ("Degraded", "boolean", False)):
        g["Init_" + v] = {"type": "InitializeVariable", "runAfter": {}, "inputs": {"variables": [{"name": v, "type": typ, "value": val}]}}
    g["Ch_parse"] = dict(c("@json(if(empty(outputs('ChangesRaw')), 'x', outputs('ChangesRaw')))", S("ClientRequestId")), metadata=FAIL_HANDLED)
    g["Ch_arr"] = {"type": "Query", "runAfter": S("Ch_parse"), "metadata": FAIL_HANDLED, "inputs": {"from": "@outputs('Ch_parse')", "where": "@true"}}
    sx = lambda k: "trim(%s)" % nz("item()?['%s']" % k)  # noqa: E731
    g["Ch_norm"] = {"type": "Select", "runAfter": S("Ch_arr"), "metadata": FAIL_HANDLED, "inputs": {"from": "@body('Ch_arr')", "select": {
        "phaseId": "@" + _safe_int(sx("phaseId")), "disciplineId": "@" + _safe_int(sx("disciplineId")),
        "state": "@toLower(%s)" % sx("state"), "value": "@" + sx("value"), "etag": "@" + nz("item()?['etag']")}}}
    g["Ch_keys"] = {"type": "Select", "runAfter": {"Ch_norm": ANY + ["Skipped"], "ClientRequestId": ["Succeeded"]}, "inputs": {
        "from": "@if(%s, %s, json('[]'))" % (_okd("Ch_norm"), _ab("Ch_norm")),
        "select": "@concat(string(item()?['phaseId']), '|', string(item()?['disciplineId']))"}}
    keys = "body('Ch_keys')"
    shape_ok = ("and(%s, greater(length(%s), 0), not(greater(length(%s), %d)), equals(length(union(%s, %s)), length(%s)))"
                % (_okd("Ch_norm"), keys, keys, hr.MAX_CHANGES, keys, keys, keys))
    g["Pre_code"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(%s), 'VALIDATION_REQUEST', if(not(greater(outputs('Pid'), 0)), 'VALIDATION_LOOKUP', 'OK')))"
                      % (G("ResultCode"), G("ResultCode"), shape_ok), S("Ch_keys"))
    reads = _data_reads(o("Pid"))
    reads["Pre_loop"] = {"type": "Foreach", "runAfter": S("Get_items"), "foreach": "@%s" % _ab("Ch_norm"),
                         "runtimeConfiguration": {"concurrency": {"repetitions": LOOP_CONCURRENCY}},
                         "actions": _pre_loop(nz("%s?['LegacyId']" % _ab("Get_project")))}
    g["If_ok"] = {"type": "If", "runAfter": S("Pre_code"), "expression": {"equals": ["@outputs('Pre_code')", "OK"]},
                  "actions": reads, "else": {"actions": {}}}
    g["Read_code"] = c("@if(not(equals(outputs('Pre_code'), 'OK')), outputs('Pre_code'), if(%s, 'NOT_FOUND', if(not(and(%s, %s)), 'ERROR', 'OK')))"
                       % (_project_missing(), _reads_ok(), _okd("Pre_loop")), {"If_ok": ANY})
    g["Bad"] = {"type": "Query", "runAfter": S("Read_code"), "inputs": {"from": "@variables('Pre')",
                "where": "@not(or(equals(item()?['code'], 'WRITE'), equals(item()?['code'], 'NO_CHANGE')))"}}
    g["Pre_ok"] = c("@and(equals(outputs('Read_code'), 'OK'), equals(length(body('Bad')), 0))", S("Bad"))
    g["Phase_ids"] = {"type": "Select", "runAfter": S("Pre_ok"), "inputs": {"from": "@%s" % _rows("Get_phases"), "select": "@int(item()?['PhaseId'])"}}
    g["Stale_rows"] = {"type": "Query", "runAfter": S("Phase_ids"), "inputs": {
        "from": "@if(outputs('Pre_ok'), %s, createArray())" % _rows("Get_items"),
        "where": "@and(not(contains(body('Phase_ids'), int(item()?['PhaseItemId']))), not(equals(item()?['ManDays'], null)))"}}
    g["Stale_plan"] = {"type": "Select", "runAfter": S("Stale_rows"), "inputs": {"from": "@body('Stale_rows')", "select": {
        "phaseId": "@int(item()?['PhaseItemId'])", "disciplineId": "@int(item()?['DisciplineItemId'])", "state": "blank", "value": "",
        "etag": "@item()?['odata.etag']", "code": "WRITE", "itemId": "@item()?['Id']", "stored": "@item()?['odata.etag']",
        "old": "@%s" % nz("item()?['ManDays']"), "regkey": "@item()?['RegKey']", "stale": True}}}
    write_loop = _write_loop(o("Pid"), audit_list=audit_list, conf_audit_list=conf_audit_list, environment=environment, source_flow=source_flow)
    g["If_write"] = {"type": "If", "runAfter": S("Stale_plan"), "expression": {"equals": ["@outputs('Pre_ok')", True]},
                     "actions": {
                         "Get_type": _sp({}, "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % LIST),
                         "Writes": {"type": "Foreach", "runAfter": S("Get_type"),
                                    "foreach": "@union(variables('Pre'), body('Stale_plan'))",
                                    "runtimeConfiguration": {"concurrency": {"repetitions": LOOP_CONCURRENCY}}, "actions": write_loop}},
                     "else": {"actions": {}}}
    F = "variables('Failed')"
    g["Final_code"] = c("@if(not(equals(outputs('Read_code'), 'OK')), outputs('Read_code'), if(not(outputs('Pre_ok')), 'REFUSED', "
                        "if(not(%s), 'ERROR', if(greater(%s, 0), 'PARTIAL', 'OK'))))" % (_okd("Get_type"), F), {"If_write": ANY})
    g["Refused_results"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {
        "from": "@if(equals(outputs('Final_code'), 'REFUSED'), variables('Pre'), createArray())", "select": {
            "phaseId": "@item()?['phaseId']", "disciplineId": "@item()?['disciplineId']", "stale": False,
            "resultcode": "@if(or(equals(item()?['code'], 'WRITE'), equals(item()?['code'], 'NO_CHANGE')), 'NOT_WRITTEN', item()?['code'])",
            "etag": ""}}}
    g["Audit_status"] = c("@if(variables('Degraded'), 'AUDIT_DEGRADED', if(or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL')), 'OK', %s))"
                          % EMPTY, S("Refused_results"))
    g["Warnings"] = {"type": "Query", "runAfter": S("Audit_status"), "inputs": {
        "from": "@createArray(if(greater(%s, 0), 'WARN_RELOAD_REQUIRED', %s), if(variables('Degraded'), 'AUDIT_DEGRADED', %s))" % (F, EMPTY, EMPTY),
        "where": "@not(empty(item()))"}}
    ok = "or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL'))"
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "savedcount": "@{string(variables('Saved'))}", "clearedstale": "@{string(variables('Cleared'))}",
            "results": "@{string(if(equals(outputs('Final_code'), 'REFUSED'), body('Refused_results'), variables('Results')))}",
            "auditstatus": "@{outputs('Audit_status')}", "warnings": "@{string(body('Warnings'))}"}
    g["Respond"] = bf._respond(body, "Warnings")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {
                                  "runStatus": "Failed", "runError": {"code": "AUDIT_DEGRADED",
                                                                      "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}},
                              "else": {"actions": {}}}
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "savedcount": "0", "clearedstale": "0", "results": "[]", "auditstatus": "", "warnings": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)
