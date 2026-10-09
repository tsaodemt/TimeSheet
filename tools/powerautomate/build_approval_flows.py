"""EPIC 07 flows: TS-Approve (S07.2, per-row approval), TS-Unapprove (S07.3, explicit per-row unapproval) and
TS-ReadTeam (S07.2 approval queue; S07.3 adds the Approved review mode). Reference:
tools/approval/approve_entries.py; contract: docs/approve-contract.md.

Both reuse the R1 pieces unchanged: trusted caller + guard (guard_template, capability `TS.Approve`, scope self), the
mandatory AuthorizationAllow / Deny row before any entry read (audit_template), AppSettings BusinessTimezone read by the
service connection (build_r1_flows._settings), one correlation id (the run name), coded DIRECTORY_ERROR /
INTERNAL_ERROR responses when the normal path does not complete, and AUD-F1 option B for the per-row Approval rows.

TS-Approve writes exactly EntryStatus=Approved, ApprovedBy=<trusted caller UPN> (text), ApprovedOn=<server UTC instant
of the request> with IF-MATCH = the stored ETag (no wildcard, no retry). Rows are processed sequentially in request
order. Claimed owner / approver / role / scope / status / discipline inputs are logged by name only.

TS-Unapprove (capability `TS.Unapprove`: Approver / Executive, company; Team Leader never; own entries never) writes exactly
EntryStatus=Draft, ApprovedBy=null, ApprovedOn=null on one Approved row, with the same per-row checks, ETag rule and audit
(`Unapproval`, ActionText "Hủy phê duyệt: <date>") as TS-Approve. A Draft target is refused NOT_APPROVED.
"""
from __future__ import annotations

import os
import sys

import audit_template as at
import build_appstart_flow as baf
import build_r1_flows as r1
import guard_template as gt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "approval"))
import approval_rules as ar  # noqa: E402

c, S, EMPTY, o, nz, esc, base = r1.c, r1.S, r1.EMPTY, r1.o, r1.nz, r1.esc, r1.base
_tb, _raw, _sp, _ab, _okd, _rows, _int_text_ok = r1._tb, r1._raw, r1._sp, r1._ab, r1._okd, r1._rows, r1._int_text_ok
ENTRIES = r1.ENTRIES
APPROVE_DECOYS = ["ApprovedBy", "ApproverUpn", "DisciplineCode", "EntryStatus", "OwnerUpn", "Role", "Scope"]
UNAPPROVE_DECOYS = ["ApprovedBy", "ApprovedOn", "DisciplineCode", "EmployeeItemId", "EntryStatus", "OwnerUpn", "Role", "Scope"]
TEAM_DECOYS = ["DisciplineCode", "OwnerUpn", "Role", "Scope"]
TEAM_MODES = ("", "pending", "approved")  # text_7 Mode (S07.3); empty = pending (S07.2 callers unchanged)
APPROVER_ROLES = tuple(r.role for r in ar.MATRIX if r.approve != "none")  # TL, APR, EXE
MAX_ITEMS = 50
FAIL_HANDLED = {"failOnError": True}
ANY = ["Succeeded", "Failed", "TimedOut"]
G = lambda k: "outputs('Guard_result')?['%s']" % k  # noqa: E731


def approval_scope_config() -> dict:
    """Guard policy for the approval capabilities (approval_rules.MATRIX; nothing pending)."""
    return ar.scope_config()


def _guard(scope_config, role_groups, decoys, source_flow, action_expr="'TS.Approve'", **kw):
    g = gt.guard_actions(scope_config, role_groups, site=kw["site"], domain=kw["domain"], emp_list=kw["emp_list"],
                         audit_list=kw["audit_list"], action_expr=action_expr, kind_expr="'self'", ref_expr=EMPTY,
                         untrusted_inputs=decoys, legacy_audit=False, fields=gt.EMPLOYEES_FIELDS)
    g.update(at.authorization_event_actions(audit_list=kw["audit_list"], environment=kw["environment"], source_flow=source_flow,
                                            after="Guard_result", name="Authz_audit"))
    return g


def _error_response(g, body):
    """Exactly one coded response when the normal path did not complete (profile read -> DIRECTORY_ERROR, mandatory
    authorization audit or another internal step -> INTERNAL_ERROR). Nothing was written."""
    err = "if(equals(actions('Get_caller_profile')?['status'], 'Succeeded'), 'INTERNAL_ERROR', 'DIRECTORY_ERROR')"
    g["Respond_error"] = {"type": "Response", "kind": "PowerApp", "runAfter": {"Respond": ["Skipped"]},
                          "inputs": {"statusCode": 200, "body": dict(body, resultcode="@{%s}" % err), "schema": g["Respond"]["inputs"]["schema"]}}
    assert list(g["Respond_error"]["inputs"]["body"]) == list(g["Respond"]["inputs"]["body"])


def _respond(body, after):
    return {"type": "Response", "kind": "PowerApp", "runAfter": S(after), "inputs": {"statusCode": 200, "body": body, "schema": {
        "type": "object", "properties": {k: {"title": k, "x-ms-dynamically-added": True, "type": "string"} for k in body}}}}


# ---------------------------------------------------------------- one row (shared by TS-Approve and TS-Unapprove)

OPS = {
    # need: the only status that can be written; state: code for any other non-deleted status; body: the MERGE fields
    "approve": dict(need="Draft", state="LOCKED", event=("Approval", "Approve"), change="'Approved'",
                    body=lambda T: {"EntryStatus": "Approved", "ApprovedBy": "@{%s}" % T, "ApprovedOn": "@{outputs('ApprovedAt')}"}),
    "unapprove": dict(need="Approved", state="NOT_APPROVED", event=("Unapproval", "Unapprove"), change="'Draft'",
                      body=lambda T: {"EntryStatus": "Draft", "ApprovedBy": None, "ApprovedOn": None}),
}


def _row_actions(op, win, *, emp_list, audit_list, conf_audit_list, environment, source_flow):
    """Per-row checks in this order: NOT_FOUND (bad id, missing, Deleted) -> owner read error ERROR -> SCOPE_NOT_ALLOWED
    (owner's current discipline / company) -> own entry ROLE_NOT_ALLOWED -> status (op need) -> ETag CONFLICT -> MERGE with
    IF-MATCH stored ETag (412 CONFLICT, other ERROR) -> one audit row. X = the current request item {itemId, etag}."""
    T, EMP, DISC, SCOPE = o("Trusted"), G("EmployeeId"), o("CallerDisc"), G("ResolvedScope")
    X = "items('Rows')"
    row = {}
    row["R_text"] = c("@%s?['itemId']" % X, {})
    rt = o("R_text")
    row["R_id"] = c("@int(if(and(%s, not(startsWith(%s, '-'))), %s, '0'))" % (_int_text_ok(rt), rt, rt), S("R_text"))
    rid = o("R_id")
    it = _ab("Get_row")
    own = _ab("Get_owner")
    row["If_id"] = {"type": "If", "runAfter": S("R_id"), "expression": {"not": {"equals": ["@%s" % rid, 0]}},
                    "actions": {
                        "Get_row": _sp({}, "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id,OwnerUpn,EntryStatus,LegacyId,EmployeeItemId,WorkDate"
                                       % (ENTRIES, rid)),
                        "If_owner": {"type": "If", "runAfter": {"Get_row": ["Succeeded", "Failed"]},
                                     "expression": {"and": [{"equals": ["@%s" % _okd("Get_row"), True]},
                                                            {"not": {"equals": ["@%s?['EntryStatus']" % it, "Deleted"]}},
                                                            {"not": {"equals": ["@%s?['EmployeeItemId']" % it, None]}}]},
                                     "actions": {"Get_owner": _sp({}, "GET", "_api/web/lists/getbytitle('%s')/items(@{%s?['EmployeeItemId']})"
                                                                  "?$select=Id,LegacyId,Discipline/DisciplineCode&$expand=Discipline" % (emp_list, it))},
                                     "else": {"actions": {}}}},
                    "else": {"actions": {}}}
    sc = lambda n: "actions('%s')?['outputs']?['statusCode']" % n  # noqa: E731
    owner_disc = nz("%s?['Discipline']?['DisciplineCode']" % own)
    owner_found = _okd("Get_owner")
    in_scope = ("and(%s, or(equals(%s, 'company'), and(equals(%s, 'discipline'), not(empty(%s)), not(empty(%s)), equals(%s, %s))))"
                % (owner_found, SCOPE, SCOPE, owner_disc, DISC, owner_disc, DISC))
    is_self = "or(equals(%s?['Id'], %s), equals(toLower(%s), %s))" % (own, EMP, nz("%s?['OwnerUpn']" % it), T)
    stored_etag = nz("%s?['odata.etag']" % it)
    client_etag = "%s?['etag']" % X
    # owner read: 404 = no such employee (out of scope, as the guard's target=0); any other failure -> ERROR (fail closed)
    owner_err = "and(not(%s), not(equals(%s, 404)))" % (owner_found, sc("Get_owner"))
    code = ("if(equals(%(rid)s, 0), 'NOT_FOUND', if(not(%(rowok)s), if(equals(%(rsc)s, 404), 'NOT_FOUND', 'ERROR'), "
            "if(equals(%(it)s?['EntryStatus'], 'Deleted'), 'NOT_FOUND', if(and(not(equals(%(it)s?['EmployeeItemId'], null)), %(oerr)s), 'ERROR', "
            "if(not(%(scope)s), 'SCOPE_NOT_ALLOWED', if(%(self)s, 'ROLE_NOT_ALLOWED', if(not(equals(%(it)s?['EntryStatus'], '%(need)s')), '%(state)s', "
            "if(or(empty(%(ce)s), not(equals(%(ce)s, %(se)s))), 'CONFLICT', 'WRITE'))))))))"
            % dict(rid=rid, rowok=_okd("Get_row"), rsc=sc("Get_row"), it=it, oerr=owner_err, scope=in_scope, self=is_self, ce=client_etag,
                   se=stored_etag, need=op["need"], state=op["state"]))
    row["R_code"] = c("@" + code, {"If_id": ANY})
    merge = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s})" % (ENTRIES, rid),
                body="@{string(outputs('R_body'))}", meta="verbose", headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % stored_etag})
    merge["inputs"]["retryPolicy"] = {"type": "none"}  # a retried MERGE after a committed write would report CONFLICT
    row["If_write"] = {"type": "If", "runAfter": S("R_code"), "expression": {"equals": ["@outputs('R_code')", "WRITE"]},
                       "actions": {
                           "R_body": c(dict({"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")}},
                                            **op["body"](T)), {}),
                           "Merge": dict(merge, runAfter=S("R_body")),
                           "Get_new": _sp(S("Merge"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id" % (ENTRIES, rid))},
                       "else": {"actions": {}}}
    row["R_final"] = c("@if(not(equals(outputs('R_code'), 'WRITE')), outputs('R_code'), if(%s, 'OK', if(equals(%s, 412), 'CONFLICT', 'ERROR')))"
                       % (_okd("Merge"), sc("Merge")), {"If_write": ANY})
    ok_row = "equals(outputs('R_final'), 'OK')"
    new_etag = nz("%s?['odata.etag']" % _ab("Get_new"))
    row["R_etag"] = c("@if(and(%s, not(empty(%s)), not(equals(%s, %s))), %s, %s)" % (ok_row, new_etag, new_etag, stored_etag, new_etag, EMPTY),
                      S("R_final"))
    has_wd = "and(%s, not(equals(%s?['WorkDate'], null)))" % (_okd("Get_row"), it)
    # the date function only ever sees a real instant (no dependency on lazy if() evaluation)
    row["R_date"] = c("@if(%s, convertFromUtc(if(%s, %s?['WorkDate'], '2000-01-01T00:00:00Z'), %s, 'yyyy-MM-dd'), %s)"
                      % (has_wd, has_wd, it, "if(equals(%s, null), 'UTC', %s)" % (win, win), EMPTY), S("R_etag"))
    row.update(at.operation_event_actions(
        op["event"][0], op["event"][1], target_entity=ENTRIES, audit_list=audit_list, conf_audit_list=conf_audit_list, environment=environment,
        source_flow=source_flow, target_id_expr="if(greater(%s, 0), string(%s), %s)" % (rid, rid, EMPTY),
        target_legacy_id_expr="if(%s, %s, %s)" % (_okd("Get_row"), nz("%s?['LegacyId']" % it), EMPTY),
        outcome_code_expr="if(%s, 'ALLOW', outputs('R_final'))" % ok_row,
        owner_employee_id_expr="if(%s, %s?['EmployeeItemId'], null)" % (_okd("Get_row"), it), is_on_behalf_expr="true",
        work_date_expr="outputs('R_date')", change_fields={"EntryStatus": op["change"]}, after="R_date", name="Row_audit"))
    # ChangeJson only for a written row; a refusal changed nothing
    row["Row_audit"]["inputs"]["ChangeJson"] = "@{if(%s, string(outputs('Row_audit_change')), %s)}" % (ok_row, EMPTY)
    row["Mark_degraded"] = {"type": "SetVariable", "runAfter": {"Write_Row_audit": ["Failed", "TimedOut"]},
                            "inputs": {"name": "Degraded", "value": True}}
    row["Add_result"] = {"type": "AppendToArrayVariable", "runAfter": {"Write_Row_audit": ANY}, "inputs": {"name": "Results", "value": {
        "itemid": "@{%s}" % rt, "resultcode": "@{outputs('R_final')}", "messagecode": "@{concat('MSG_', outputs('R_final'))}",
        "etag": "@{outputs('R_etag')}"}}}
    row["Count_ok"] = {"type": "IncrementVariable", "runAfter": S("Add_result"), "inputs": {"name": "Approved", "value": "@if(%s, 1, 0)" % ok_row}}
    row["Count_refused"] = {"type": "IncrementVariable", "runAfter": S("Count_ok"), "inputs": {"name": "Refused", "value": "@if(%s, 0, 1)" % ok_row}}

    return row


# ---------------------------------------------------------------- TS-Approve

def approve_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment, registry, overlay,
                    scope_config=None, settings_list="AppSettings", source_flow="TS-Approve", refs=None) -> dict:
    """Trigger: text Items (JSON [{itemId, etag}], 1-50), text_1 ClientRequestId (audit only), text_2..8 decoys."""
    kw = dict(site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = _guard(scope_config or approval_scope_config(), role_groups, APPROVE_DECOYS, source_flow, **kw)
    g["ItemsRaw"] = c("@" + _raw("text"), S("Write_Authz_audit"))
    g["ClientRequestId"] = c("@" + _tb("text_1"), S("ItemsRaw"))
    for v, typ, val in (("Results", "array", "@json('[]')"), ("Approved", "integer", 0), ("Refused", "integer", 0), ("Degraded", "boolean", False)):
        g["Init_" + v] = {"type": "InitializeVariable", "runAfter": {}, "inputs": {"variables": [{"name": v, "type": typ, "value": val}]}}
    # Items: invalid JSON, a non-array, a non-object element -> the handled action fails -> VALIDATION_REQUEST
    g["Items_parse"] = dict(c("@json(if(empty(outputs('ItemsRaw')), 'x', outputs('ItemsRaw')))", S("ClientRequestId")), metadata=FAIL_HANDLED)
    g["Items_arr"] = {"type": "Query", "runAfter": S("Items_parse"), "metadata": FAIL_HANDLED,
                      "inputs": {"from": "@outputs('Items_parse')", "where": "@true"}}
    g["Items_norm"] = {"type": "Select", "runAfter": S("Items_arr"), "metadata": FAIL_HANDLED, "inputs": {
        "from": "@body('Items_arr')", "select": {"itemId": "@trim(%s)" % nz("item()?['itemId']"), "etag": "@%s" % nz("item()?['etag']")}}}
    g["Item_ids"] = {"type": "Select", "runAfter": {"Items_norm": ANY + ["Skipped"], "ClientRequestId": ["Succeeded"]}, "inputs": {
        "from": "@if(%s, %s, json('[]'))" % (_okd("Items_norm"), _ab("Items_norm")), "select": "@item()?['itemId']"}}
    ids = "body('Item_ids')"
    status, value, _, last = r1._settings(g, registry, overlay, ["BusinessTimezone"], "Item_ids", settings_list)
    g["Settings_read"]["runAfter"] = {"Item_ids": ["Succeeded"]}
    items_ok = ("and(%s, greater(length(%s), 0), not(greater(length(%s), %d)), equals(length(union(%s, %s)), length(%s)))"
                % (_okd("Items_norm"), ids, ids, MAX_ITEMS, ids, ids, ids))
    # a Team Leader without a discipline approves nothing (the reference guard's self-scope check; caller-level refusal)
    g["Pre"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(and(equals(%s, 'discipline'), empty(outputs('CallerDisc'))), 'SCOPE_NOT_ALLOWED', "
                 "if(not(%s), 'VALIDATION_REQUEST', if(not(equals(%s, 'OK')), 'CONFIG_UNRESOLVED', 'OK'))))"
                 % (G("ResultCode"), G("ResultCode"), G("ResolvedScope"), items_ok, status["BusinessTimezone"]), S(last))
    g["ApprovedAt"] = c("@utcNow('yyyy-MM-ddTHH:mm:ssZ')", S("Pre"))
    win = value["BusinessTimezone"]
    row = _row_actions(OPS["approve"], win, emp_list=emp_list, audit_list=audit_list, conf_audit_list=conf_audit_list,
                       environment=environment, source_flow=source_flow)

    g["If_ok"] = {"type": "If", "runAfter": S("ApprovedAt"), "expression": {"equals": ["@outputs('Pre')", "OK"]},
                  "actions": {
                      "Get_type": _sp({}, "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % ENTRIES),
                      "Rows": {"type": "Foreach", "runAfter": S("Get_type"), "foreach": "@body('Items_norm')",
                               "runtimeConfiguration": {"concurrency": {"repetitions": 1}}, "actions": row}},
                  "else": {"actions": {}}}
    A, R = "variables('Approved')", "variables('Refused')"
    # not after Skipped: If_ok is skipped only when a mandatory earlier step failed; that path ends in Respond_error
    g["Final_code"] = c("@if(not(equals(outputs('Pre'), 'OK')), outputs('Pre'), if(not(%s), 'ERROR', if(and(greater(%s, 0), greater(%s, 0)), 'PARTIAL', "
                        "if(greater(%s, 0), 'OK', 'REFUSED'))))" % (_okd("Get_type"), A, R, A), {"If_ok": ANY})
    g["Audit_status"] = c("@if(variables('Degraded'), 'AUDIT_DEGRADED', 'OK')", S("Final_code"))
    g["Reload"] = {"type": "Query", "runAfter": S("Audit_status"), "inputs": {"from": "@variables('Results')",
                   "where": "@and(equals(item()?['resultcode'], 'OK'), empty(item()?['etag']))"}}
    g["Warnings"] = {"type": "Query", "runAfter": S("Reload"), "inputs": {
        "from": "@createArray(if(greater(length(body('Reload')), 0), 'WARN_RELOAD_REQUIRED', %s), if(variables('Degraded'), 'AUDIT_DEGRADED', %s))"
                % (EMPTY, EMPTY), "where": "@not(empty(item()))"}}
    ok = "or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL'))"
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "approvedcount": "@{string(%s)}" % A, "refusedcount": "@{string(%s)}" % R, "auditstatus": "@{outputs('Audit_status')}",
            "results": "@{string(variables('Results'))}", "warnings": "@{string(body('Warnings'))}"}
    g["Respond"] = _respond(body, "Warnings")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {
                                  "runStatus": "Failed", "runError": {"code": "AUDIT_DEGRADED",
                                                                      "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}},
                              "else": {"actions": {}}}
    _error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                        "approvedcount": "0", "refusedcount": "0", "auditstatus": "", "results": "[]", "warnings": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- TS-Unapprove (S07.3)

def unapprove_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment, registry, overlay,
                      scope_config=None, settings_list="AppSettings", source_flow="TS-Unapprove", refs=None) -> dict:
    """Trigger: text ItemId, text_1 ETag (both from TS-ReadTeam Approved mode), text_2..9 decoys. One row per request
    (explicit per-row action; no batch). Approved -> Draft, ApprovedBy / ApprovedOn cleared (null)."""
    kw = dict(site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = _guard(scope_config or approval_scope_config(), role_groups, UNAPPROVE_DECOYS, source_flow, action_expr="'TS.Unapprove'", **kw)
    g["ItemIn"] = c("@" + _tb("text"), S("Write_Authz_audit"))
    g["ETagIn"] = c("@" + _raw("text_1"), S("ItemIn"))
    for v, typ, val in (("Results", "array", "@json('[]')"), ("Approved", "integer", 0), ("Refused", "integer", 0), ("Degraded", "boolean", False)):
        g["Init_" + v] = {"type": "InitializeVariable", "runAfter": {}, "inputs": {"variables": [{"name": v, "type": typ, "value": val}]}}
    g["Item_obj"] = c({"itemId": "@{outputs('ItemIn')}", "etag": "@{outputs('ETagIn')}"}, S("ETagIn"))
    status, value, _, last = r1._settings(g, registry, overlay, ["BusinessTimezone"], "Item_obj", settings_list)
    g["Settings_read"]["runAfter"] = {"Item_obj": ["Succeeded"]}
    g["Pre"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(equals(%s, 'OK')), 'CONFIG_UNRESOLVED', 'OK'))"
                 % (G("ResultCode"), G("ResultCode"), status["BusinessTimezone"]), S(last))
    row = _row_actions(OPS["unapprove"], value["BusinessTimezone"], emp_list=emp_list, audit_list=audit_list,
                       conf_audit_list=conf_audit_list, environment=environment, source_flow=source_flow)
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@outputs('Pre')", "OK"]},
                  "actions": {
                      "Get_type": _sp({}, "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % ENTRIES),
                      "Rows": {"type": "Foreach", "runAfter": S("Get_type"), "foreach": "@createArray(outputs('Item_obj'))",
                               "runtimeConfiguration": {"concurrency": {"repetitions": 1}}, "actions": row}},
                  "else": {"actions": {}}}
    first = "first(variables('Results'))"
    g["Final_code"] = c("@if(not(equals(outputs('Pre'), 'OK')), outputs('Pre'), if(not(%s), 'ERROR', %s))"
                        % (_okd("Get_type"), "if(equals(%s, null), 'ERROR', %s?['resultcode'])" % (first, first)), {"If_ok": ANY})
    g["Audit_status"] = c("@if(variables('Degraded'), 'AUDIT_DEGRADED', 'OK')", S("Final_code"))
    ok = "equals(outputs('Final_code'), 'OK')"
    out_etag = "if(and(%s, not(equals(%s, null))), %s, %s)" % (ok, first, nz("%s?['etag']" % first), EMPTY)
    g["Warnings"] = {"type": "Query", "runAfter": S("Audit_status"), "inputs": {
        "from": "@createArray(if(and(%s, empty(%s)), 'WARN_RELOAD_REQUIRED', %s), if(variables('Degraded'), 'AUDIT_DEGRADED', %s))"
                % (ok, out_etag, EMPTY, EMPTY), "where": "@not(empty(item()))"}}
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "itemid": "@{outputs('ItemIn')}", "etag": "@{%s}" % out_etag, "auditstatus": "@{outputs('Audit_status')}",
            "warnings": "@{string(body('Warnings'))}"}
    g["Respond"] = _respond(body, "Warnings")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {
                                  "runStatus": "Failed", "runError": {"code": "AUDIT_DEGRADED",
                                                                      "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}},
                              "else": {"actions": {}}}
    _error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                        "itemid": "", "etag": "", "auditstatus": "", "warnings": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- TS-ReadTeam

def _period_ok(p):
    p7 = "concat(%s, '0000000')" % p
    month = ("int(if(and(equals(length(%s), 7), equals(substring(%s, 4, 1), '-'), equals(%s, '-')), substring(%s, 5, 2), '01'))"
             % (p, p7, r1._digits_removed(p), p7))
    return ("and(equals(length(%s), 7), equals(substring(%s, 4, 1), '-'), equals(%s, '-'), greater(%s, 0), less(%s, 13))"
            % (p, p7, r1._digits_removed(p), month, month))


def read_team_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment, registry, overlay,
                      scope_config=None, settings_list="AppSettings", source_flow="TS-ReadTeam", refs=None) -> dict:
    """Trigger: text PeriodKey (yyyy-MM), text_1 AfterId, text_2 PageSize, text_3..6 decoys, text_7 Mode (optional, S07.3).
    Mode empty / "Pending": Draft rows, capability TS.Approve (S07.2, unchanged). Mode "Approved": Approved rows, capability
    TS.Unapprove (review before Hủy phê duyệt). Rows of the period in the caller's scope for that capability, never the
    caller's own; indexed PeriodKey first; keyset paging; leak re-check."""
    kw = dict(site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    mode_in = "toLower(trim(%s))" % nz("triggerBody()?['text_7']")
    g = _guard(scope_config or approval_scope_config(), role_groups, TEAM_DECOYS, source_flow,
               action_expr="if(equals(%s, 'approved'), 'TS.Unapprove', 'TS.Approve')" % mode_in, **kw)
    g["Period"] = c("@" + _tb("text"), S("Write_Authz_audit"))
    g["AfterRaw"] = c("@" + _tb("text_1"), S("Period"))
    g["SizeRaw"] = c("@" + _tb("text_2"), S("AfterRaw"))
    g["Mode"] = c("@" + mode_in, S("SizeRaw"))
    g["Want"] = c("@if(equals(outputs('Mode'), 'approved'), 'Approved', 'Draft')", S("Mode"))
    status, value, _, last = r1._settings(g, registry, overlay, ["BusinessTimezone"], "Want", settings_list)
    P, T, EMP, DISC, SCOPE = o("Period"), o("Trusted"), G("EmployeeId"), o("CallerDisc"), G("ResolvedScope")
    disc_scope = "equals(%s, 'discipline')" % SCOPE
    checks = [
        ("not(equals(%s, 'ALLOW'))" % G("ResultCode"), G("ResultCode")),
        ("not(contains(createArray(%s, 'pending', 'approved'), outputs('Mode')))" % EMPTY, "'VALIDATION_REQUEST'"),
        ("not(%s)" % _period_ok(P), "'VALIDATION_DATE'"),
        ("not(equals(%s, 'OK'))" % status["BusinessTimezone"], "'CONFIG_UNRESOLVED'"),
        ("or(and(not(empty(%s)), not(%s)), and(not(empty(%s)), not(%s)))" % (o("AfterRaw"), _int_text_ok(o("AfterRaw")),
                                                                           o("SizeRaw"), _int_text_ok(o("SizeRaw"))), "'VALIDATION_LOOKUP'"),
        ("and(%s, empty(%s))" % (disc_scope, DISC), "'SCOPE_NOT_ALLOWED'"),
    ]
    expr = "'OK'"
    for cond, code in reversed(checks):
        expr = "if(%s, %s, %s)" % (cond, code, expr)
    g["Validation"] = c("@" + expr, S(last))
    safe_int = lambda x: "int(if(%s, %s, '0'))" % (_int_text_ok(x), x)  # noqa: E731
    g["After"] = c("@if(empty(%s), 0, max(%s, 0))" % (o("AfterRaw"), safe_int(o("AfterRaw"))), S("Validation"))
    g["Size"] = c("@if(empty(%s), 500, min(max(%s, 1), 500))" % (o("SizeRaw"), safe_int(o("SizeRaw"))), S("After"))
    q = "concat('''', %s, '''')"
    filt = c("@concat('PeriodKey eq ', %s, ' and EntryStatus eq ', %s, ' and ', if(%s, concat('DisciplineCode eq ', %s, ' and '), %s), "
             "'OwnerUpn ne ', %s, ' and EmployeeItemId ne ', string(%s), ' and Id gt ', string(outputs('After')))"
             % (q % esc(P), q % "outputs('Want')", disc_scope, q % esc(DISC), EMPTY, q % esc(T), EMP), {})
    sel = ("Id,WorkDate,ProjectId,PhaseId,WorkTypeId,ShiftId,HourTypeId,Hours,Remark,EntryStatus,OwnerUpn,EmployeeItemId,DisciplineCode,"
           "PeriodKey,ApprovedBy,ApprovedOn,Employee/Title,Employee/LegacyId")
    query = _sp(S("Filter"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=%s&$expand=Employee&$filter=@{outputs('Filter')}"
                "&$orderby=Id asc&$top=@{outputs('Size')}" % (ENTRIES, sel))
    g["If_ok"] = {"type": "If", "runAfter": S("Size"), "expression": {"equals": ["@outputs('Validation')", "OK"]},
                  "actions": {"Filter": filt, "Query": query}, "else": {"actions": {}}}
    g["Rows"] = c("@" + _rows("Query"), {"If_ok": ANY})
    g["Leak"] = {"type": "Query", "runAfter": S("Rows"), "inputs": {"from": "@outputs('Rows')", "where":
                 "@or(equals(toLower(%s), %s), equals(item()?['EmployeeItemId'], %s), not(equals(%s, outputs('Want'))), not(equals(%s, %s)), "
                 "and(%s, not(equals(%s, %s))))" % (nz("item()?['OwnerUpn']"), T, EMP, nz("item()?['EntryStatus']"), nz("item()?['PeriodKey']"), P,
                                                    disc_scope, nz("item()?['DisciplineCode']"), DISC)}}
    g["Final_code"] = c("@if(not(equals(outputs('Validation'), 'OK')), outputs('Validation'), if(not(%s), 'ERROR', "
                        "if(greater(length(body('Leak')), 0), 'ERROR_LEAK', 'OK')))" % _okd("Query"), S("Leak"))
    ok = "equals(outputs('Final_code'), 'OK')"
    win = value["BusinessTimezone"]
    g["Out_rows"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {
        "from": "@if(%s, outputs('Rows'), createArray())" % ok,
        "select": {"id": "@item()?['Id']", "ownerName": "@item()?['Employee']?['Title']", "ownerCode": "@item()?['Employee']?['LegacyId']",
                   "workDate": "@convertFromUtc(item()?['WorkDate'], %s, 'yyyy-MM-dd')" % win,
                   "projectId": "@item()?['ProjectId']", "phaseId": "@item()?['PhaseId']", "workTypeId": "@item()?['WorkTypeId']",
                   "shiftId": "@item()?['ShiftId']", "hourTypeId": "@item()?['HourTypeId']", "hours": "@item()?['Hours']",
                   "remark": "@item()?['Remark']", "status": "@item()?['EntryStatus']", "etag": "@item()?['odata.etag']",
                   "approvedBy": "@item()?['ApprovedBy']", "approvedOn": "@item()?['ApprovedOn']"}}}
    g["Next"] = c("@if(and(%s, equals(length(body('Out_rows')), outputs('Size'))), last(body('Out_rows'))?['id'], 0)" % ok, S("Out_rows"))
    g.update(at.operation_event_actions("ReadProxy", "ReadTeam", target_entity=ENTRIES, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                        environment=environment, source_flow=source_flow,
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, after="Next", name="Read_audit"))
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "rows": "@{string(body('Out_rows'))}", "nextafterid": "@{string(outputs('Next'))}",
            "pagesize": "@{string(if(%s, outputs('Size'), 0))}" % ok}
    g["Respond"] = _respond(body, "Write_Read_audit")
    _error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                        "rows": "[]", "nextafterid": "0", "pagesize": "0"})
    return baf.bind_connection_references(base._fix(g), refs)
