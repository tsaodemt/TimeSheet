"""R3 M2 flows for EPIC 16 Project Effort: EFF-SetProjectPm, EFF-ReadProjectEffort, EFF-SaveProjectEffort.

Reference: tools/effort/project_effort.py; contract: OpenSpec change `r3-planning-effort-hour-registration` (specs/project-effort,
planning-security, effort-reporting-contract; M2 decisions). Reuses the R1/R2/M1 pieces unchanged: trusted caller + guard
(guard_template), the mandatory AuthorizationAllow / Deny row before any business read (audit_template), one correlation id
(the run name), coded DIRECTORY_ERROR / INTERNAL_ERROR responses when the normal path does not complete, AUD-F1 option B.

Project-PM scope (OD-24, OD-37): the guard's role decision (`Guard_base`) is combined with the authoritative PM data of
ProjectPmAssignments into the final `Guard_result` (same shape) BEFORE the authorization audit row is written, so the
audit records the final decision. EFF.ProjectEdit is granted to no role: only the project's PM edits.

Actual effort (OD-19, OD-33): Approved TimesheetEntries hours of the project, read page by page (Do-until on the
odata.nextLink; any failed page fails the read closed — never a partial total), divided by HoursPerManDay; only the
totals leave the flow (no Timesheet row).
"""
from __future__ import annotations

import os
import sys

import audit_template as at
import build_appstart_flow as baf
import build_approval_flows as bf
import build_r1_flows as r1
import build_read_flow as base
import guard_template as gt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effort"))
import effort_rules as er  # noqa: E402
import pe_schema as ps  # noqa: E402
import project_effort as pe  # noqa: E402

c, S, EMPTY, o, nz, esc = r1.c, r1.S, r1.EMPTY, r1.o, r1.nz, r1.esc
_tb, _raw, _sp, _ab, _okd, _rows = r1._tb, r1._raw, r1._sp, r1._ab, r1._okd, r1._rows
FAIL_HANDLED = {"failOnError": True}
ANY = ["Succeeded", "Failed", "TimedOut"]
G = lambda k: "outputs('Guard_result')?['%s']" % k  # noqa: E731
B = lambda k: "outputs('Guard_base')?['%s']" % k  # noqa: E731
LOOP_CONCURRENCY = 20
# outputs of actions inside a branch that may not have run are read null-safe (the expression must not depend on lazy if())
CFG_OK = ("and(equals(actions('HpmOk')?['outputs'], true), equals(actions('CodesOk')?['outputs'], true), not(variables('Missing')))")
HPM = "if(equals(actions('Hpm')?['outputs'], null), 1, actions('Hpm')?['outputs'])"
ENTRIES = "TimesheetEntries"
PAGE = 5000
MAX_PAGES = 200


def _digits_only(x):
    return "and(not(empty(%s)), empty(%s))" % (x, r1._digits_removed(x))


def _safe_int(x):
    """Digits -> int; a float rendering such as '7.0' (SharePoint Number columns) -> its integer part; else 0."""
    core = "if(contains(%s, '.'), first(split(%s, '.')), %s)" % (x, x, x)
    zeros = "if(contains(%s, '.'), last(split(%s, '.')), '0')" % (x, x)
    ok = "and(%s, empty(replace(%s, '0', %s)))" % (_digits_only(core), zeros, EMPTY)
    return "int(if(%s, %s, '0'))" % (ok, core)


def _rq(x):
    """A stored / requested id as int; null-safe (null -> 0). SharePoint Number columns arrive as floats (1.0)."""
    return _safe_int(nz(x))


def _value_ok(v):
    return "and(%s, or(not(contains(%s, '.')), less(length(last(split(%s, '.'))), 3)))" % (r1._decimal_ok(v), v, v)


def _too_long(v):
    return "greater(length(replace(%s, '.', %s)), %d)" % (v, EMPTY, pe.MAX_SIGNIFICANT)


def _guard_pm(capability, decoys, source_flow, decide, after_pid, **kw):
    """Guard (role decision) -> Guard_base; PM data read; final Guard_result (same shape) via `decide`; authorization row.
    decide(g) adds the actions computing outputs('Final_authz') and outputs('Final_scope') and returns the last name."""
    g = gt.guard_actions(er.scope_config(), kw["role_groups"], site=kw["site"], domain=kw["domain"], emp_list=kw["emp_list"],
                         audit_list=kw["audit_list"], action_expr="'%s'" % capability, kind_expr="'self'", ref_expr=EMPTY,
                         untrusted_inputs=decoys, legacy_audit=False, fields=gt.EMPLOYEES_FIELDS)
    g["Guard_base"] = g.pop("Guard_result")
    g.update(after_pid("Guard_base"))
    last = decide(g)
    res = dict(g["Guard_base"]["inputs"])
    res["ResolvedScope"] = "@outputs('Final_scope')"
    res["AuthorizationDecision"] = "@if(equals(outputs('Final_authz'), 'ALLOW'), 'ALLOW', 'DENY')"
    res["ResultCode"] = "@outputs('Final_authz')"
    g["Guard_result"] = c(res, S(last))
    g.update(at.authorization_event_actions(audit_list=kw["audit_list"], environment=kw["environment"], source_flow=source_flow,
                                            after="Guard_result", name="Authz_audit"))
    return g


def _pid_actions(after):
    return {"PidIn": c("@" + _tb("text"), S(after)), "Pid": c("@" + _safe_int(o("PidIn")), S("PidIn"))}


def _identity_ok():
    return "or(equals(%s, 'ALLOW'), equals(%s, 'ROLE_NOT_ALLOWED'))" % (B("ResultCode"), B("ResultCode"))


def _caller_emp():
    return "int(if(equals(%s, null), 0, %s))" % (B("EmployeeId"), B("EmployeeId"))


def _settings_reads(after):
    return {"Get_settings": _sp(S(after), "GET", "_api/web/lists/getbytitle('AppSettings')/items?$select=Title,Value&$top=500")}


def _settings_actions(g, after):
    """HPM (float), HpmOk, Codes (array of trimmed codes), CodesOk — fail closed (CONFIG_INVALID)."""
    rows = _rows("Get_settings")
    q = lambda k: "Q_" + k  # noqa: E731
    for key in (ps.HPM_SETTING, ps.RECIPIENT_SETTING):
        g[q(key)] = {"type": "Query", "runAfter": S(after), "inputs": {"from": "@%s" % rows,
                     "where": "@equals(toLower(%s), '%s')" % (nz("item()?['Title']"), key.lower())}}
        after = q(key)
    raw = lambda k: "trim(%s)" % nz("if(equals(length(body('%s')), 0), null, first(body('%s'))?['Value'])" % (q(k), q(k)))  # noqa: E731
    g["HpmRaw"] = c("@" + raw(ps.HPM_SETTING), S(after))
    h = o("HpmRaw")
    g["HpmOk"] = c("@and(%s, greater(float(if(%s, %s, '0')), 0))" % (r1._decimal_ok(h), r1._decimal_ok(h), h), S("HpmRaw"))
    g["Hpm"] = c("@float(if(outputs('HpmOk'), %s, '1'))" % h, S("HpmOk"))
    g["RecRaw"] = c("@if(empty(%s), '%s', %s)" % (raw(ps.RECIPIENT_SETTING), ps.RECIPIENT_DEFAULT, raw(ps.RECIPIENT_SETTING)), S("Hpm"))
    g["Codes"] = {"type": "Select", "runAfter": S("RecRaw"), "inputs": {"from": "@split(outputs('RecRaw'), ',')", "select": "@trim(item())"}}
    g["Codes_low"] = {"type": "Select", "runAfter": S("Codes"), "inputs": {"from": "@body('Codes')", "select": "@toLower(item())"}}
    g["Codes_empty"] = {"type": "Query", "runAfter": S("Codes_low"), "inputs": {"from": "@body('Codes')", "where": "@empty(item())"}}
    g["CodesOk"] = c("@and(equals(length(body('Codes_empty')), 0), equals(length(union(body('Codes_low'), body('Codes_low'))), length(body('Codes_low'))))",
                     S("Codes_empty"))
    return "CodesOk"


def _recipients_actions(g, after):
    """Variable Recs (ordered: QLP, PM, configured disciplines) and Missing (unknown configured code)."""
    g["Rec_loop"] = {"type": "Foreach", "runAfter": S(after), "foreach": "@body('Codes')",
                     "runtimeConfiguration": {"concurrency": {"repetitions": 1}}, "actions": {
                         "Find_code": {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_discs"),
                                       "where": "@equals(toLower(%s), toLower(items('Rec_loop')))" % nz("item()?['DisciplineCode']")}},
                         "If_found": {"type": "If", "runAfter": S("Find_code"), "expression": {"equals": ["@greater(length(body('Find_code')), 0)", True]},
                                      "actions": {"Add_rec": {"type": "AppendToArrayVariable", "runAfter": {}, "inputs": {"name": "Recs", "value": {
                                          "key": "@{concat('D:', first(body('Find_code'))?['LegacyId'])}", "category": "Discipline",
                                          "disciplineId": "@int(first(body('Find_code'))?['Id'])", "label": "@{%s}" % nz("first(body('Find_code'))?['Title']")}}}},
                                      "else": {"actions": {"Set_missing": {"type": "SetVariable", "runAfter": {}, "inputs": {"name": "Missing", "value": True}}}}}}}
    return "Rec_loop"


def _init(name, typ, value):
    return {"type": "InitializeVariable", "runAfter": {}, "inputs": {"variables": [{"name": name, "type": typ, "value": value}]}}


def _actual_actions(pid):
    """Do-until over the pages of Approved TimesheetEntries of the project; Hours (float), PageFail (bool)."""
    first = ("_api/web/lists/getbytitle('%s')/items?$select=Id,Hours&$filter=ProjectId eq @{%s} and EntryStatus eq 'Approved'"
             "&$orderby=Id asc&$top=%d" % (ENTRIES, pid, PAGE))
    page = _sp({}, "GET", "@{variables('Next')}", meta="nometadata")
    nxt = "%s?['odata.nextLink']" % _ab("Get_page")
    return {
        "Set_next": {"type": "SetVariable", "runAfter": {}, "inputs": {"name": "Next", "value": first}},
        "Pages": {"type": "Until", "runAfter": S("Set_next"), "expression": "@or(empty(variables('Next')), variables('PageFail'))",
                  "limit": {"count": MAX_PAGES, "timeout": "PT1H"}, "actions": {
                      "Get_page": page,
                      "Sum_page": {"type": "Foreach", "runAfter": S("Get_page"), "foreach": "@%s" % _rows("Get_page"),
                                   "runtimeConfiguration": {"concurrency": {"repetitions": LOOP_CONCURRENCY}}, "actions": {
                                       "Add_hours": {"type": "IncrementVariable", "runAfter": {}, "inputs": {"name": "Hours",
                                                     "value": "@float(if(equals(items('Sum_page')?['Hours'], null), '0', %s))" % nz("items('Sum_page')?['Hours']")}}}},
                      "Set_more": {"type": "SetVariable", "runAfter": {"Sum_page": ANY + ["Skipped"]}, "inputs": {"name": "Next", "value":
                                   "@if(and(%s, not(empty(%s))), concat('_api/', last(split(%s, '/_api/'))), %s)" % (_okd("Get_page"), nz(nxt), nz(nxt), EMPTY)}},
                      "Set_fail": {"type": "SetVariable", "runAfter": S("Set_more"), "inputs": {"name": "PageFail",
                                   "value": "@not(and(%s, %s))" % (_okd("Get_page"), _okd("Sum_page"))}}}},
    }


# ---------------------------------------------------------------- EFF-ReadProjectEffort

def read_effort_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                        source_flow="EFF-ReadProjectEffort", refs=None) -> dict:
    """Trigger: text ProjectItemId (0 / empty = list mode), text_1..4 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    P = o("Pid")

    def decide(g):
        g["Get_mine"] = _sp(S("Pid"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,ProjectItemId,PmEmployeeItemId"
                            "&$filter=PmEmployeeItemId eq @{%s}&$top=5000" % (ps.PM_LIST, _caller_emp()))
        g["Mine_pids"] = {"type": "Select", "runAfter": {"Get_mine": ["Succeeded", "Failed"]},
                          "inputs": {"from": "@%s" % _rows("Get_mine"), "select": "@%s" % _rq("item()?['ProjectItemId']")}}
        mine = "body('Mine_pids')"
        any_pm = "greater(length(%s), 0)" % mine
        this_pm = "contains(%s, %s)" % (mine, P)
        bc = B("ResultCode")
        err = "and(%s, not(%s))" % (_identity_ok(), _okd("Get_mine"))
        lst = "if(equals(%s, 'ALLOW'), 'ALLOW', if(equals(%s, 'ROLE_NOT_ALLOWED'), if(%s, 'ALLOW', 'ROLE_NOT_ALLOWED'), %s))" % (bc, bc, any_pm, bc)
        det = ("if(equals(%s, 'ALLOW'), 'ALLOW', if(equals(%s, 'ROLE_NOT_ALLOWED'), if(%s, 'ALLOW', if(%s, 'SCOPE_NOT_ALLOWED', 'ROLE_NOT_ALLOWED')), %s))"
               % (bc, bc, this_pm, any_pm, bc))
        g["Final_authz"] = c("@if(%s, 'ERROR', if(greater(%s, 0), %s, %s))" % (err, P, det, lst), S("Mine_pids"))
        g["Final_scope"] = c("@if(not(equals(outputs('Final_authz'), 'ALLOW')), 'none', if(equals(%s, 'ALLOW'), 'company', '%s'))" % (bc, er.PM_SCOPE),
                             S("Final_authz"))
        return "Final_scope"
    g = _guard_pm(er.VIEW, pe.READ_DECOYS, source_flow, decide, _pid_actions, **kw)
    for v, typ, val in (("Recs", "array", "@json('[{\"key\":\"QLP\",\"category\":\"QLP\",\"disciplineId\":0,\"label\":\"%s\"},"
                                                  "{\"key\":\"PM\",\"category\":\"PM\",\"disciplineId\":0,\"label\":\"PM\"}]')" % pe.LABELS["QLP"]),
                        ("Missing", "boolean", False), ("RecOut", "array", "@json('[]')"), ("Total", "float", 0.0),
                        ("Projects", "array", "@json('[]')"), ("Next", "string", ""), ("Hours", "float", 0.0), ("PageFail", "boolean", False)):
        g["Init_" + v] = _init(v, typ, val)
    ok_authz = "equals(outputs('Final_authz'), 'ALLOW')"
    g["Pre"] = c("@outputs('Final_authz')", S("Write_Authz_audit"))
    mine = "body('Mine_pids')"
    pm_scope = "equals(outputs('Final_scope'), '%s')" % er.PM_SCOPE
    emps = "_api/web/lists/getbytitle('%s')/items?$select=Id,Title,LegacyUserName,IsActive&$orderby=Title asc,Id asc&$top=5000" % emp_list
    # ---- list mode
    list_actions = {
        "Get_projects": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items?$select=Id,ProjectCode,Title,Status&$orderby=ProjectCode asc,Id asc&$top=5000"),
        "Get_assign_all": _sp(S("Get_projects"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,ProjectItemId,PmEmployeeItemId&$top=5000" % ps.PM_LIST),
        "Get_emps_l": _sp(S("Get_assign_all"), "GET", emps),
        "Visible": {"type": "Query", "runAfter": S("Get_emps_l"), "inputs": {"from": "@%s" % _rows("Get_projects"),
                    "where": "@or(not(%s), contains(%s, int(item()?['Id'])))" % (pm_scope, mine)}},
        "Proj_loop": {"type": "Foreach", "runAfter": S("Visible"), "foreach": "@body('Visible')",
                      "runtimeConfiguration": {"concurrency": {"repetitions": LOOP_CONCURRENCY}}, "actions": {
                          "Find_assign": {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_assign_all"),
                                          "where": "@equals(%s, int(items('Proj_loop')?['Id']))" % _rq("item()?['ProjectItemId']")}},
                          "Find_pm": {"type": "Query", "runAfter": S("Find_assign"), "inputs": {"from": "@%s" % _rows("Get_emps_l"),
                                      "where": "@and(greater(length(body('Find_assign')), 0), equals(int(item()?['Id']), %s))"
                                               % _rq("first(body('Find_assign'))?['PmEmployeeItemId']")}},
                          "Add_project": {"type": "AppendToArrayVariable", "runAfter": S("Find_pm"), "inputs": {"name": "Projects", "value": {
                              "id": "@int(items('Proj_loop')?['Id'])", "code": "@{%s}" % nz("items('Proj_loop')?['ProjectCode']"),
                              "name": "@{%s}" % nz("items('Proj_loop')?['Title']"), "status": "@{%s}" % nz("items('Proj_loop')?['Status']"),
                              "pmName": "@{%s}" % nz("first(body('Find_pm'))?['Title']"),
                              "canEdit": "@and(greater(length(body('Find_assign')), 0), equals(%s, %s))"
                                         % (_rq("first(body('Find_assign'))?['PmEmployeeItemId']"), _caller_emp())}}}}},
    }
    # ---- detail mode
    det = {
        "Get_project": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items(@{%s})?$select=Id,LegacyId,ProjectCode,Title,Status" % P),
    }
    det.update(_settings_reads("Get_project"))
    det["Get_discs"] = _sp(S("Get_settings"), "GET", "_api/web/lists/getbytitle('Disciplines')/items?$select=Id,LegacyId,DisciplineCode,Title&$top=500")
    det["Get_assign"] = _sp(S("Get_discs"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,ProjectItemId,PmEmployeeItemId&$filter=ProjectItemId eq @{%s}&$top=2"
                            % (ps.PM_LIST, P))
    det["Get_items"] = _sp(S("Get_assign"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,AllocKey,RecipientKey,Effort&$filter=ProjectItemId eq @{%s}&$orderby=Id asc&$top=5000"
                           % (ps.ALLOC_LIST, P))
    det["Get_emps"] = _sp(S("Get_items"), "GET", emps)
    last = _settings_actions(det, "Get_emps")
    last = _recipients_actions(det, last)
    det["Out_loop"] = {"type": "Foreach", "runAfter": S(last), "foreach": "@variables('Recs')",
                       "runtimeConfiguration": {"concurrency": {"repetitions": 1}}, "actions": {
                           "Find_item": {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_items"),
                                         "where": "@equals(%s, items('Out_loop')?['key'])" % nz("item()?['RecipientKey']")}},
                           "Has_val": c("@and(greater(length(body('Find_item')), 0), not(equals(first(body('Find_item'))?['Effort'], null)))", S("Find_item")),
                           "Add_total": {"type": "IncrementVariable", "runAfter": S("Has_val"), "inputs": {"name": "Total",
                                         "value": "@float(if(outputs('Has_val'), %s, '0'))" % nz("first(body('Find_item'))?['Effort']")}},
                           "Add_out": {"type": "AppendToArrayVariable", "runAfter": S("Add_total"), "inputs": {"name": "RecOut", "value": {
                               "key": "@{items('Out_loop')?['key']}", "category": "@{items('Out_loop')?['category']}",
                               "disciplineId": "@items('Out_loop')?['disciplineId']", "label": "@{items('Out_loop')?['label']}",
                               "state": "@{if(outputs('Has_val'), 'VALUE', 'BLANK')}",
                               "value": "@{%s}" % nz("first(body('Find_item'))?['Effort']"),
                               "etag": "@{%s}" % nz("first(body('Find_item'))?['odata.etag']")}}}}}
    det.update(_actual_actions(P))
    det["Set_next"]["runAfter"] = S("Out_loop")
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@" + ok_authz, True]},
                  "actions": {"If_list": {"type": "If", "runAfter": {}, "expression": {"equals": ["@greater(%s, 0)" % P, True]},
                                          "actions": det, "else": {"actions": list_actions}}},
                  "else": {"actions": {}}}
    missing = "and(not(%s), equals(actions('Get_project')?['outputs']?['statusCode'], 404))" % _okd("Get_project")
    det_ok = "and(%s, %s, %s, %s, %s, %s, %s, not(variables('PageFail')))" % (
        _okd("Get_project"), _okd("Get_settings"), _okd("Get_discs"), _okd("Get_assign"), _okd("Get_items"), _okd("Get_emps"), _okd("Pages"))
    cfg_ok = CFG_OK
    list_ok = "and(%s, %s, %s, %s)" % (_okd("Get_projects"), _okd("Get_assign_all"), _okd("Get_emps_l"), _okd("Proj_loop"))
    g["Final_code"] = c("@if(not(%s), outputs('Pre'), if(greater(%s, 0), if(%s, 'NOT_FOUND', if(not(%s), 'ERROR', if(not(%s), 'CONFIG_INVALID', 'OK'))), "
                        "if(%s, 'OK', 'ERROR')))" % (ok_authz, P, missing, det_ok, cfg_ok, list_ok), {"If_ok": ANY})
    ok = "equals(outputs('Final_code'), 'OK')"
    detail_ok = "and(%s, greater(%s, 0))" % (ok, P)
    A = "first(%s)" % _rows("Get_assign")
    has_a = "and(%s, greater(length(%s), 0))" % (detail_ok, _rows("Get_assign"))
    g["Pm_emp"] = {"type": "Query", "runAfter": S("Final_code"), "inputs": {"from": "@if(%s, %s, createArray())" % (has_a, _rows("Get_emps")),
                   "where": "@equals(int(item()?['Id']), %s)" % _rq("%s?['PmEmployeeItemId']" % A)}}
    E = "first(body('Pm_emp'))"
    g["Pm_obj"] = c("@if(%s, setProperty(setProperty(setProperty(json('{}'), 'employeeId', %s), 'name', %s), 'code', %s), json('{}'))"
                    % (has_a, _rq("%s?['PmEmployeeItemId']" % A), nz("%s?['Title']" % E), nz("%s?['LegacyUserName']" % E)), S("Pm_emp"))
    can_assign = "contains(%s, 'PMO')" % G("ResolvedRoles")
    g["Emps"] = {"type": "Select", "runAfter": S("Pm_obj"), "inputs": {
        "from": "@if(and(%s, %s), %s, createArray())" % (detail_ok, can_assign, _rows("Get_emps")),
        "select": {"id": "@int(item()?['Id'])", "name": "@{%s}" % nz("item()?['Title']"), "code": "@{%s}" % nz("item()?['LegacyUserName']"),
                   "active": "@equals(item()?['IsActive'], true)"}}}
    g["Emps_active"] = {"type": "Query", "runAfter": S("Emps"), "inputs": {"from": "@body('Emps')", "where": "@item()?['active']"}}
    g["Emps_out"] = {"type": "Select", "runAfter": S("Emps_active"), "inputs": {"from": "@body('Emps_active')",
                     "select": {"id": "@item()?['id']", "name": "@item()?['name']", "code": "@item()?['code']"}}}
    PR = _ab("Get_project")
    g["Project"] = c("@if(%s, setProperty(setProperty(setProperty(setProperty(json('{}'), 'id', %s), 'code', %s), 'name', %s), 'status', %s), json('{}'))"
                     % (detail_ok, _rq("%s?['Id']" % PR), nz("%s?['ProjectCode']" % PR), nz("%s?['Title']" % PR), nz("%s?['Status']" % PR)), S("Emps_out"))
    g["Md"] = c("@if(%s, div(variables('Hours'), %s), 0)" % (detail_ok, HPM), S("Project"))
    g.update(at.operation_event_actions("ReadProxy", "ReadProjectEffort", target_entity=ps.ALLOC_LIST, audit_list=audit_list,
                                        conf_audit_list=conf_audit_list, environment=environment, source_flow=source_flow,
                                        target_id_expr="if(greater(%s, 0), string(%s), %s)" % (P, P, EMPTY),
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, after="Md", name="Read_audit"))
    s = lambda e: "@{if(%s, %s, %s)}" % (detail_ok, e, EMPTY)  # noqa: E731
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "mode": "@{if(greater(%s, 0), 'detail', 'list')}" % P,
            "projects": "@{string(if(and(%s, not(greater(%s, 0))), variables('Projects'), json('[]')))}" % (ok, P),
            "project": "@{string(outputs('Project'))}", "pm": "@{string(outputs('Pm_obj'))}",
            "recipients": "@{string(if(%s, variables('RecOut'), json('[]')))}" % detail_ok,
            "plannedtotal": s("string(variables('Total'))"), "actualhours": s("string(variables('Hours'))"),
            "actualmandays": s("string(outputs('Md'))"), "variance": s("string(sub(outputs('Md'), variables('Total')))"),
            "hourspermanday": s("string(%s)" % HPM),
            "canedit": "@{if(and(%s, contains(%s, %s)), 'true', 'false')}" % (detail_ok, mine, P),
            "canassignpm": "@{if(and(%s, %s), 'true', 'false')}" % (ok, can_assign),
            "pmetag": "@{if(%s, %s?['odata.etag'], %s)}" % (has_a, A, EMPTY),
            "employees": "@{string(body('Emps_out'))}"}
    g["Respond"] = bf._respond(body, "Write_Read_audit")
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "mode": "", "projects": "[]", "project": "{}", "pm": "{}", "recipients": "[]", "plannedtotal": "", "actualhours": "",
                           "actualmandays": "", "variance": "", "hourspermanday": "", "canedit": "false", "canassignpm": "false", "pmetag": "",
                           "employees": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- EFF-SaveProjectEffort

def _pre_loop(project_legacy):
    X = "items('Pre_loop')"
    k, st, v, et = ("%s?['%s']" % (X, f) for f in ("key", "state", "value", "etag"))
    a = {}
    a["Find"] = {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_items"), "where": "@equals(%s, %s)" % (nz("item()?['RecipientKey']"), k)}}
    a["Find_rec"] = {"type": "Query", "runAfter": S("Find"), "inputs": {"from": "@variables('Recs')", "where": "@equals(item()?['key'], %s)" % k}}
    F = "first(body('Find'))"
    stored_val = nz("%s?['Effort']" % F)
    stored_etag = nz("%s?['odata.etag']" % F)
    found = "not(equals(%s, null))" % F
    has_val = "and(%s, not(equals(%s?['Effort'], null)))" % (found, F)
    vok = _value_ok(v)
    same = ("if(equals(%(st)s, 'blank'), not(%(hv)s), and(%(hv)s, equals(float(if(empty(%(sv)s), '0', %(sv)s)), float(if(%(vok)s, %(v)s, '0')))))"
            % dict(st=st, hv=has_val, sv=stored_val, vok=vok, v=v))
    code = ("if(equals(length(body('Find_rec')), 0), 'VALIDATION_LOOKUP', "
            "if(not(or(equals(%(st)s, 'blank'), equals(%(st)s, 'value'))), 'VALIDATION_VALUE', "
            "if(and(equals(%(st)s, 'value'), not(%(vok)s)), 'VALIDATION_VALUE', "
            "if(and(equals(%(st)s, 'value'), %(long)s), 'TECHNICAL_LIMIT', "
            "if(and(not(%(found)s), not(empty(%(et)s))), 'CONFLICT', "
            "if(and(%(found)s, not(equals(%(et)s, %(se)s))), 'CONFLICT', "
            "if(%(same)s, 'NO_CHANGE', 'WRITE')))))))"
            % dict(st=st, vok=vok, long=_too_long(v), found=found, et=et, se=stored_etag, same=same))
    a["P_code"] = c("@" + code, S("Find_rec"))
    R = "first(body('Find_rec'))"
    a["Add_pre"] = {"type": "AppendToArrayVariable", "runAfter": S("P_code"), "inputs": {"name": "Pre", "value": {
        "key": "@%s" % k, "state": "@%s" % st, "value": "@%s" % v, "etag": "@%s" % et, "code": "@{outputs('P_code')}",
        "itemId": "@if(%s, %s?['Id'], 0)" % (found, F), "stored": "@%s" % stored_etag, "old": "@%s" % stored_val,
        "allockey": "@if(%s, %s, concat(%s, '|', %s))" % (found, nz("%s?['AllocKey']" % F), project_legacy, k),
        "category": "@{%s}" % nz("%s?['category']" % R), "disciplineId": "@if(equals(%s, null), 0, %s?['disciplineId'])" % (R, R)}}}
    return a


def _write_loop(pid, *, audit_list, conf_audit_list, environment, source_flow):
    W = "items('Writes')"
    w = lambda k: "%s?['%s']" % (W, k)  # noqa: E731
    T = o("Trusted")
    is_new = "equals(%s, 0)" % w("itemId")
    blank = "equals(%s, 'blank')" % w("state")
    newval = "if(%s, null, float(if(%s, '0', %s)))" % (blank, blank, w("value"))
    disc = "if(greater(%s, 0), %s, null)" % (w("disciplineId"), w("disciplineId"))
    a = {}
    a["W_create"] = c({"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")},
                       "Title": "@{%s}" % w("allockey"), "AllocKey": "@{%s}" % w("allockey"), "LegacyId": "@{%s}" % w("allockey"),
                       "ProjectId": "@%s" % pid, "ProjectItemId": "@%s" % pid, "RecipientKey": "@{%s}" % w("key"),
                       "RecipientCategory": "@{%s}" % w("category"), "DisciplineId": "@%s" % disc, "DisciplineItemId": "@%s" % disc,
                       "Effort": "@%s" % newval, "Status": "Active", "ActorUpn": "@{%s}" % T, "CorrelationId": "@{workflow()?['run']?['name']}"}, {})
    a["W_merge"] = c({"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")},
                      "Effort": "@%s" % newval, "ActorUpn": "@{%s}" % T, "CorrelationId": "@{workflow()?['run']?['name']}"}, S("W_create"))
    L = ps.ALLOC_LIST
    create = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items" % L, body="@{string(outputs('W_create'))}", meta="verbose")
    merge = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s})" % (L, w("itemId")), body="@{string(outputs('W_merge'))}",
                meta="verbose", headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % w("stored")})
    for x in (create, merge):
        x["inputs"]["retryPolicy"] = {"type": "none"}
    a["If_change"] = {"type": "If", "runAfter": S("W_merge"), "expression": {"not": {"equals": ["@%s" % w("code"), "NO_CHANGE"]}},
                      "actions": {"If_new": {"type": "If", "runAfter": {}, "expression": {"equals": ["@%s" % is_new, True]},
                                             "actions": {"Create": create},
                                             "else": {"actions": {"Merge": merge,
                                                                  "Get_new": _sp(S("Merge"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id" % (L, w("itemId")))}}}},
                      "else": {"actions": {}}}
    sc = lambda n: "actions('%s')?['outputs']?['statusCode']" % n  # noqa: E731
    written = "if(%s, %s, %s)" % (is_new, _okd("Create"), _okd("Merge"))
    nn = lambda x: "if(equals(%s, null), 0, %s)" % (x, x)  # noqa: E731
    conflict = "if(%s, and(greater(%s, 399), less(%s, 500)), equals(%s, 412))" % (is_new, nn(sc("Create")), nn(sc("Create")), nn(sc("Merge")))
    a["W_final"] = c("@if(equals(%s, 'NO_CHANGE'), 'NO_CHANGE', if(%s, 'OK', if(%s, 'CONFLICT', 'ERROR')))" % (w("code"), written, conflict),
                     {"If_change": ANY})
    ok = "equals(outputs('W_final'), 'OK')"
    a["W_id"] = c("@if(%s, %s, %s)" % (is_new, "if(%s, %s?['d']?['Id'], 0)" % (ok, _ab("Create")), w("itemId")), S("W_final"))
    new_etag = nz("if(%s, %s?['d']?['__metadata']?['etag'], %s?['odata.etag'])" % (is_new, _ab("Create"), _ab("Get_new")))
    a["W_etag"] = c("@if(equals(outputs('W_final'), 'NO_CHANGE'), %s, if(%s, %s, %s))" % (w("stored"), ok, new_etag, EMPTY), S("W_id"))
    action = "if(%s, 'Create', if(%s, 'Clear', 'Update'))" % (is_new, blank)
    ev = at.operation_event_actions("WriteProxy", "Update", target_entity=L, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                    environment=environment, source_flow=source_flow, target_id_expr="string(outputs('W_id'))",
                                    target_legacy_id_expr=w("allockey"),
                                    change_fields={"EffortOld": w("old"), "Effort": "if(%s, %s, %s)" % (blank, EMPTY, w("value"))},
                                    after="W_etag", name="Cell_audit")
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
        "key": "@%s" % w("key"), "resultcode": "@{outputs('W_final')}", "etag": "@{outputs('W_etag')}"}}}
    a["Count_saved"] = {"type": "IncrementVariable", "runAfter": S("Add_result"), "inputs": {"name": "Saved", "value": "@if(%s, 1, 0)" % ok}}
    a["Count_failed"] = {"type": "IncrementVariable", "runAfter": S("Count_saved"),
                         "inputs": {"name": "Failed", "value": "@if(or(%s, equals(outputs('W_final'), 'NO_CHANGE')), 0, 1)" % ok}}
    return a


def save_effort_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                        source_flow="EFF-SaveProjectEffort", refs=None) -> dict:
    """Trigger: text ProjectItemId, text_1 Changes (JSON [{key, state, value, etag}], 1-20), text_2 ClientRequestId
    (correlation only), text_3..7 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    P = o("Pid")

    def decide(g):
        g["Get_assign"] = _sp(S("Pid"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,ProjectItemId,PmEmployeeItemId&$filter=ProjectItemId eq @{%s}&$top=2"
                              % (ps.PM_LIST, P))
        A = "first(%s)" % _rows("Get_assign")
        is_pm = "and(greater(length(%s), 0), equals(%s, %s))" % (_rows("Get_assign"), _rq("%s?['PmEmployeeItemId']" % A), _caller_emp())
        bc = B("ResultCode")
        err = "and(%s, greater(%s, 0), not(%s))" % (_identity_ok(), P, _okd("Get_assign"))
        g["Final_authz"] = c("@if(%s, 'ERROR', if(not(%s), %s, if(%s, 'ALLOW', 'SCOPE_NOT_ALLOWED')))" % (err, _identity_ok(), bc, is_pm),
                             {"Get_assign": ["Succeeded", "Failed"]})
        g["Final_scope"] = c("@if(equals(outputs('Final_authz'), 'ALLOW'), '%s', 'none')" % er.PM_SCOPE, S("Final_authz"))
        return "Final_scope"
    g = _guard_pm(er.EDIT, pe.SAVE_DECOYS, source_flow, decide, _pid_actions, **kw)
    g["ChangesRaw"] = c("@" + _raw("text_1"), S("Write_Authz_audit"))
    g["ClientRequestId"] = c("@" + _tb("text_2"), S("ChangesRaw"))
    for v, typ, val in (("Pre", "array", "@json('[]')"), ("Results", "array", "@json('[]')"), ("Saved", "integer", 0),
                        ("Failed", "integer", 0), ("Degraded", "boolean", False), ("Missing", "boolean", False),
                        ("Recs", "array", "@json('[{\"key\":\"QLP\",\"category\":\"QLP\",\"disciplineId\":0,\"label\":\"%s\"},"
                                          "{\"key\":\"PM\",\"category\":\"PM\",\"disciplineId\":0,\"label\":\"PM\"}]')" % pe.LABELS["QLP"])):
        g["Init_" + v] = _init(v, typ, val)
    g["Ch_parse"] = dict(c("@json(if(empty(outputs('ChangesRaw')), 'x', outputs('ChangesRaw')))", S("ClientRequestId")), metadata=FAIL_HANDLED)
    g["Ch_arr"] = {"type": "Query", "runAfter": S("Ch_parse"), "metadata": FAIL_HANDLED, "inputs": {"from": "@outputs('Ch_parse')", "where": "@true"}}
    sx = lambda k: "trim(%s)" % nz("item()?['%s']" % k)  # noqa: E731
    g["Ch_norm"] = {"type": "Select", "runAfter": S("Ch_arr"), "metadata": FAIL_HANDLED, "inputs": {"from": "@body('Ch_arr')", "select": {
        "key": "@" + sx("key"), "state": "@toLower(%s)" % sx("state"), "value": "@" + sx("value"), "etag": "@" + nz("item()?['etag']")}}}
    g["Ch_keys"] = {"type": "Select", "runAfter": {"Ch_norm": ANY + ["Skipped"], "ClientRequestId": ["Succeeded"]}, "inputs": {
        "from": "@if(%s, %s, json('[]'))" % (_okd("Ch_norm"), _ab("Ch_norm")), "select": "@item()?['key']"}}
    keys = "body('Ch_keys')"
    shape_ok = ("and(%s, greater(length(%s), 0), not(greater(length(%s), %d)), equals(length(union(%s, %s)), length(%s)))"
                % (_okd("Ch_norm"), keys, keys, pe.MAX_CHANGES, keys, keys, keys))
    g["Pre_code"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(%s), 'VALIDATION_REQUEST', 'OK'))" % (G("ResultCode"), G("ResultCode"), shape_ok), S("Ch_keys"))
    reads = {"Get_project": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items(@{%s})?$select=Id,LegacyId,ProjectCode,Title,Status" % P)}
    reads.update(_settings_reads("Get_project"))
    reads["Get_discs"] = _sp(S("Get_settings"), "GET", "_api/web/lists/getbytitle('Disciplines')/items?$select=Id,LegacyId,DisciplineCode,Title&$top=500")
    reads["Get_items"] = _sp(S("Get_discs"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,AllocKey,RecipientKey,Effort&$filter=ProjectItemId eq @{%s}&$orderby=Id asc&$top=5000"
                             % (ps.ALLOC_LIST, P))
    last = _settings_actions(reads, "Get_items")
    last = _recipients_actions(reads, last)
    reads["If_cfg"] = {"type": "If", "runAfter": S(last), "expression": {"and": [{"equals": ["@outputs('HpmOk')", True]}, {"equals": ["@outputs('CodesOk')", True]},
                                                                                 {"equals": ["@variables('Missing')", False]}]},
                       "actions": {"Pre_loop": {"type": "Foreach", "runAfter": {}, "foreach": "@%s" % _ab("Ch_norm"),
                                                "runtimeConfiguration": {"concurrency": {"repetitions": LOOP_CONCURRENCY}},
                                                "actions": _pre_loop(nz("%s?['LegacyId']" % _ab("Get_project")))}},
                       "else": {"actions": {}}}
    g["If_ok"] = {"type": "If", "runAfter": S("Pre_code"), "expression": {"equals": ["@outputs('Pre_code')", "OK"]}, "actions": reads, "else": {"actions": {}}}
    missing = "and(not(%s), equals(actions('Get_project')?['outputs']?['statusCode'], 404))" % _okd("Get_project")
    cfg_ok = CFG_OK
    g["Read_code"] = c("@if(not(equals(outputs('Pre_code'), 'OK')), outputs('Pre_code'), if(%s, 'NOT_FOUND', if(not(and(%s, %s, %s)), 'ERROR', "
                       "if(not(%s), 'CONFIG_INVALID', if(not(and(%s, %s)), 'ERROR', 'OK')))))"
                       % (missing, _okd("Get_project"), _okd("Get_settings"), _okd("Get_discs"), cfg_ok, _okd("Get_items"), _okd("Pre_loop")),
                       {"If_ok": ANY})
    g["Bad"] = {"type": "Query", "runAfter": S("Read_code"), "inputs": {"from": "@variables('Pre')",
                "where": "@not(or(equals(item()?['code'], 'WRITE'), equals(item()?['code'], 'NO_CHANGE')))"}}
    g["Pre_ok"] = c("@and(equals(outputs('Read_code'), 'OK'), equals(length(body('Bad')), 0))", S("Bad"))
    write_loop = _write_loop(P, audit_list=audit_list, conf_audit_list=conf_audit_list, environment=environment, source_flow=source_flow)
    g["If_write"] = {"type": "If", "runAfter": S("Pre_ok"), "expression": {"equals": ["@outputs('Pre_ok')", True]},
                     "actions": {"Get_type": _sp({}, "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % ps.ALLOC_LIST),
                                 "Writes": {"type": "Foreach", "runAfter": S("Get_type"), "foreach": "@variables('Pre')",
                                            "runtimeConfiguration": {"concurrency": {"repetitions": LOOP_CONCURRENCY}}, "actions": write_loop}},
                     "else": {"actions": {}}}
    F = "variables('Failed')"
    g["Final_code"] = c("@if(not(equals(outputs('Read_code'), 'OK')), outputs('Read_code'), if(not(outputs('Pre_ok')), 'REFUSED', "
                        "if(not(%s), 'ERROR', if(greater(%s, 0), 'PARTIAL', 'OK'))))" % (_okd("Get_type"), F), {"If_write": ANY})
    g["Refused_results"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {
        "from": "@if(equals(outputs('Final_code'), 'REFUSED'), variables('Pre'), createArray())", "select": {
            "key": "@item()?['key']",
            "resultcode": "@if(or(equals(item()?['code'], 'WRITE'), equals(item()?['code'], 'NO_CHANGE')), 'NOT_WRITTEN', item()?['code'])", "etag": ""}}}
    g["Audit_status"] = c("@if(variables('Degraded'), 'AUDIT_DEGRADED', if(or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL')), 'OK', %s))"
                          % EMPTY, S("Refused_results"))
    g["Warnings"] = {"type": "Query", "runAfter": S("Audit_status"), "inputs": {
        "from": "@createArray(if(greater(%s, 0), 'WARN_RELOAD_REQUIRED', %s), if(variables('Degraded'), 'AUDIT_DEGRADED', %s))" % (F, EMPTY, EMPTY),
        "where": "@not(empty(item()))"}}
    ok = "or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL'))"
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "savedcount": "@{string(variables('Saved'))}",
            "results": "@{string(if(equals(outputs('Final_code'), 'REFUSED'), body('Refused_results'), variables('Results')))}",
            "auditstatus": "@{outputs('Audit_status')}", "warnings": "@{string(body('Warnings'))}"}
    g["Respond"] = bf._respond(body, "Warnings")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {
                                  "runStatus": "Failed", "runError": {"code": "AUDIT_DEGRADED",
                                                                      "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}},
                              "else": {"actions": {}}}
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "savedcount": "0", "results": "[]", "auditstatus": "", "warnings": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- EFF-SetProjectPm

def set_pm_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                   source_flow="EFF-SetProjectPm", refs=None) -> dict:
    """Trigger: text ProjectItemId, text_1 EmployeeItemId, text_2 ETag of the assignment item (empty when none), text_3..6 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    P = o("Pid")

    def decide(g):
        g["Final_authz"] = c("@%s" % B("ResultCode"), S("Pid"))
        g["Final_scope"] = c("@%s" % B("ResolvedScope"), S("Final_authz"))
        return "Final_scope"
    g = _guard_pm(er.ASSIGN, pe.PM_DECOYS, source_flow, decide, _pid_actions, **kw)
    g["EidIn"] = c("@" + _tb("text_1"), S("Write_Authz_audit"))
    g["Eid"] = c("@" + _safe_int(o("EidIn")), S("EidIn"))
    g["EtagIn"] = c("@" + _raw("text_2"), S("Eid"))
    g["Pre"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(greater(%s, 0)), 'VALIDATION_LOOKUP', 'OK'))" % (G("ResultCode"), G("ResultCode"), P), S("EtagIn"))
    reads = {
        "Get_project": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items(@{%s})?$select=Id,LegacyId,ProjectCode,Title" % P),
        "Get_emp": _sp(S("Get_project"), "GET", "_api/web/lists/getbytitle('%s')/items(@{if(greater(outputs('Eid'), 0), outputs('Eid'), -1)})"
                       "?$select=Id,LegacyId,Title,LegacyUserName,IsActive" % emp_list),
        "Get_assign": _sp({"Get_emp": ["Succeeded", "Failed"]}, "GET",
                          "_api/web/lists/getbytitle('%s')/items?$select=Id,PmEmployeeItemId,PmEmployeeLegacyId&$filter=ProjectItemId eq @{%s}&$top=2"
                          % (ps.PM_LIST, P)),
    }
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@outputs('Pre')", "OK"]}, "actions": reads, "else": {"actions": {}}}
    sc = lambda n: "actions('%s')?['outputs']?['statusCode']" % n  # noqa: E731
    p_missing = "and(not(%s), equals(%s, 404))" % (_okd("Get_project"), sc("Get_project"))
    e_missing = "or(not(greater(outputs('Eid'), 0)), and(not(%s), equals(%s, 404)))" % (_okd("Get_emp"), sc("Get_emp"))
    EM = _ab("Get_emp")
    A = "first(%s)" % _rows("Get_assign")
    has_a = "greater(length(%s), 0)" % _rows("Get_assign")
    a_etag = nz("%s?['odata.etag']" % A)
    E_in = o("EtagIn")
    g["Code"] = c("@if(not(equals(outputs('Pre'), 'OK')), outputs('Pre'), if(%s, 'NOT_FOUND', if(not(%s), 'ERROR', "
                  "if(%s, 'VALIDATION_LOOKUP', if(not(and(%s, %s)), 'ERROR', "
                  "if(not(equals(%s?['IsActive'], true)), 'VALIDATION_LOOKUP', "
                  "if(if(%s, not(equals(%s, %s)), not(empty(%s))), 'CONFLICT', "
                  "if(and(%s, equals(%s, %s)), 'NO_CHANGE', 'WRITE'))))))))"
                  % (p_missing, _okd("Get_project"), e_missing, _okd("Get_emp"), _okd("Get_assign"), EM,
                     has_a, E_in, a_etag, E_in, has_a, _rq("%s?['PmEmployeeItemId']" % A), _rq("%s?['Id']" % EM)), {"If_ok": ANY})
    W = lambda: {"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")}}  # noqa: E731
    PR = _ab("Get_project")
    L = ps.PM_LIST
    create = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items" % L, body="@{string(outputs('W_create'))}", meta="verbose")
    merge = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s?['Id']})" % (L, A), body="@{string(outputs('W_merge'))}",
                meta="verbose", headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % a_etag})
    for x in (create, merge):
        x["inputs"]["retryPolicy"] = {"type": "none"}
    wr = {}
    wr["W_create"] = c(dict(W(), Title="@{%s?['LegacyId']}" % PR, PmKey="@{%s?['LegacyId']}" % PR, LegacyId="@{%s?['LegacyId']}" % PR,
                           ProjectId="@%s" % P, ProjectItemId="@%s" % P, PmEmployeeLegacyId="@{%s?['LegacyId']}" % EM,
                           PmEmployeeId="@int(%s?['Id'])" % EM, PmEmployeeItemId="@int(%s?['Id'])" % EM, Status="Active",
                           ActorUpn="@{%s}" % o("Trusted"), CorrelationId="@{workflow()?['run']?['name']}"), {})
    wr["W_merge"] = c(dict(W(), PmEmployeeLegacyId="@{%s?['LegacyId']}" % EM, PmEmployeeId="@int(%s?['Id'])" % EM,
                          PmEmployeeItemId="@int(%s?['Id'])" % EM, ActorUpn="@{%s}" % o("Trusted"), CorrelationId="@{workflow()?['run']?['name']}"),
                     S("W_create"))
    wr["W_create"]["runAfter"] = S("Get_type")
    wr["W_merge"]["runAfter"] = S("W_create")
    g["If_write"] = {"type": "If", "runAfter": S("Code"), "expression": {"equals": ["@outputs('Code')", "WRITE"]},
                     "actions": dict(wr, **{"Get_type": _sp({}, "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % L),
                                 "If_new": {"type": "If", "runAfter": S("W_merge"), "expression": {"equals": ["@" + has_a, False]},
                                            "actions": {"Create": create},
                                            "else": {"actions": {"Merge": merge, "Get_new": _sp(S("Merge"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s?['Id']})?$select=Id" % (L, A))}}}}),
                     "else": {"actions": {}}}
    nn = lambda x: "if(equals(%s, null), 0, %s)" % (x, x)  # noqa: E731
    written = "if(%s, and(%s, %s), %s)" % (has_a, _okd("Merge"), _okd("Get_new"), _okd("Create"))
    conflict = "if(%s, equals(%s, 412), and(greater(%s, 399), less(%s, 500)))" % (has_a, nn(sc("Merge")), nn(sc("Create")), nn(sc("Create")))
    g["Final_code"] = c("@if(not(equals(outputs('Code'), 'WRITE')), outputs('Code'), if(not(%s), 'ERROR', if(%s, 'OK', if(%s, 'CONFLICT', 'ERROR'))))"
                        % (_okd("Get_type"), written, conflict), {"If_write": ANY})
    ok_w = "equals(outputs('Final_code'), 'OK')"
    g["W_id"] = c("@if(%s, if(%s, %s?['Id'], %s?['d']?['Id']), 0)" % (ok_w, has_a, A, _ab("Create")), S("Final_code"))
    action = "if(%s, 'Update', 'Create')" % has_a
    ev = at.operation_event_actions("WriteProxy", "Update", target_entity=L, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                    environment=environment, source_flow=source_flow, target_id_expr="string(outputs('W_id'))",
                                    target_legacy_id_expr="%s?['LegacyId']" % PR,
                                    change_fields={"PmOld": "if(%s, %s, %s)" % (has_a, nz("%s?['PmEmployeeLegacyId']" % A), EMPTY),
                                                   "Pm": nz("%s?['LegacyId']" % EM)}, after="W_id", name="Pm_audit")
    ev["Pm_audit"]["inputs"]["Action"] = "@{%s}" % action
    ev["Pm_audit"]["inputs"]["Title"] = "@{concat('WriteProxy ', %s, ' ALLOW')}" % action
    ev["Pm_audit"]["inputs"]["ActionText"] = ""
    write_audit = ev.pop("Write_Pm_audit")
    g["If_committed"] = {"type": "If", "runAfter": S("W_id"), "expression": {"equals": ["@" + ok_w, True]},
                         "actions": dict({k: dict(v, runAfter=({} if k == "Pm_audit_change" else v["runAfter"])) for k, v in ev.items()},
                                         Write_Pm_audit=write_audit), "else": {"actions": {}}}
    g["Audit_status"] = c("@if(not(%s), %s, if(equals(actions('Write_Pm_audit')?['status'], 'Succeeded'), 'OK', 'AUDIT_DEGRADED'))" % (ok_w, EMPTY),
                          {"If_committed": ANY})
    out_ok = "or(%s, equals(outputs('Final_code'), 'NO_CHANGE'))" % ok_w
    new_etag = nz("if(%s, %s?['odata.etag'], %s?['d']?['__metadata']?['etag'])" % (has_a, _ab("Get_new"), _ab("Create")))
    body = {"ok": "@{if(%s, 'true', 'false')}" % out_ok, "resultcode": "@{outputs('Final_code')}",
            "messagecode": "@{concat('MSG_', outputs('Final_code'))}", "correlationid": "@{workflow()?['run']?['name']}",
            "etag": "@{if(%s, %s, if(equals(outputs('Final_code'), 'NO_CHANGE'), %s, %s))}" % (ok_w, new_etag, a_etag, EMPTY),
            "pm": "@{string(if(%s, setProperty(setProperty(setProperty(json('{}'), 'employeeId', %s), 'name', %s), 'code', %s), json('{}')))}"
                  % (out_ok, _rq("%s?['Id']" % EM), nz("%s?['Title']" % EM), nz("%s?['LegacyUserName']" % EM)),
            "auditstatus": "@{outputs('Audit_status')}"}
    g["Respond"] = bf._respond(body, "Audit_status")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {
                                  "runStatus": "Failed", "runError": {"code": "AUDIT_DEGRADED",
                                                                      "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}},
                              "else": {"actions": {}}}
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "etag": "", "pm": "{}", "auditstatus": ""})
    return baf.bind_connection_references(base._fix(g), refs)
