"""R3 M3 flows for EPIC 17 Discipline Effort: EFF-ReadDisciplineEffort, EFF-SaveDisciplineEffort, EFF-ApproveDisciplineEffort.

Reference: tools/effort/discipline_effort.py; contract: OpenSpec change `r3-planning-effort-hour-registration` (specs/discipline-effort,
planning-security; M3 decisions 2026-10-10). Reuses the proven pieces: trusted caller + guard (guard_template), the mandatory
AuthorizationAllow / Deny row with the FINAL decision before any business read (audit_template), one correlation id (run name),
coded DIRECTORY_ERROR / INTERNAL_ERROR responses, AUD-F1 option B, `retryPolicy: none` on writes.

Ceiling arithmetic is exact: every value is turned into integer hundredths from its decimal text (no float sums). Ceiling checks of one
Project × Discipline are serialised by a technical lock item (DisciplineEffortLocks: claim with If-Match, busy -> CONFLICT, release
after the writes). Actual effort = Σ Approved TimesheetEntries hours of the project and discipline (paged, fail closed) ÷
HoursPerManDay; only totals leave the flow.
"""
from __future__ import annotations

import os
import sys

import audit_template as at
import build_appstart_flow as baf
import build_approval_flows as bf
import build_effort_flows as bef
import build_r1_flows as r1
import build_read_flow as base
import guard_template as gt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effort"))
import de_rules as dr  # noqa: E402
import de_schema as ds  # noqa: E402
import discipline_effort as de  # noqa: E402
import pe_schema as ps  # noqa: E402

c, S, EMPTY, o, nz = r1.c, r1.S, r1.EMPTY, r1.o, r1.nz
_tb, _raw, _sp, _ab, _okd, _rows = r1._tb, r1._raw, r1._sp, r1._ab, r1._okd, r1._rows
_safe_int, _rq, _value_ok, _too_long, _init = bef._safe_int, bef._rq, bef._value_ok, bef._too_long, bef._init
FAIL_HANDLED = bef.FAIL_HANDLED
ANY = ["Succeeded", "Failed", "TimedOut"]
ALL = ANY + ["Skipped"]
G = lambda k: "outputs('Guard_result')?['%s']" % k  # noqa: E731
B = lambda k: "outputs('Guard_base')?['%s']" % k  # noqa: E731
LOOP = bef.LOOP_CONCURRENCY
REG, LOCK = ds.REG_LIST, ds.LOCK_LIST
NOW = "utcNow('yyyy-MM-ddTHH:mm:ssZ')"


def cents(x):
    """decimal text (validated or a rendered stored number) -> integer hundredths (null / empty -> 0)."""
    s = "if(empty(%s), '0', %s)" % (x, x)
    return ("add(mul(int(first(split(%s, '.'))), 100), int(substring(concat(if(contains(%s, '.'), last(split(%s, '.')), %s), '00'), 0, 2)))"
            % (s, s, s, EMPTY))


def md(cx):
    """integer hundredths -> man-day text, same as discipline_effort.md."""
    a = "if(less(%s, 0), sub(0, %s), %s)" % (cx, cx, cx)
    f = "mod(%s, 100)" % a
    frac = "if(equals(mod(%s, 10), 0), string(div(%s, 10)), if(less(%s, 10), concat('0', string(%s)), string(%s)))" % (f, f, f, f, f)
    return "concat(if(less(%s, 0), '-', %s), string(div(%s, 100)), if(equals(%s, 0), %s, concat('.', %s)))" % (cx, EMPTY, a, f, EMPTY, frac)


def _guard(cap, decoys, source_flow, **kw):
    g = gt.guard_actions(dr.scope_config(), kw["role_groups"], site=kw["site"], domain=kw["domain"], emp_list=kw["emp_list"],
                         audit_list=kw["audit_list"], action_expr="'%s'" % cap, kind_expr="'self'", ref_expr=EMPTY,
                         untrusted_inputs=decoys, legacy_audit=False, fields=gt.EMPLOYEES_FIELDS)
    g.update(at.authorization_event_actions(audit_list=kw["audit_list"], environment=kw["environment"], source_flow=source_flow,
                                            after="Guard_result", name="Authz_audit"))
    return g


def _me(emp_list, after, emp_expr):
    return _sp(S(after) if after else {}, "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id,LegacyId,Title,IsActive,"
               "Discipline/Id,Discipline/LegacyId,Discipline/DisciplineCode,Discipline/Title&$expand=Discipline" % (emp_list, emp_expr))


ME = lambda k: "%s?['Discipline']?['%s']" % (_ab("Get_me"), k)  # noqa: E731


def _rows_uri(pid):
    return ("_api/web/lists/getbytitle('%s')/items?$select=Id,RegKey,ProjectItemId,EmployeeItemId,DisciplineCode,DisciplineLegacyId,"
            "WorkTypeItemId,Effort,Status&$filter=ProjectItemId eq @{%s}&$orderby=Id asc&$top=5000" % (REG, pid))


def _allocs_uri(pid):
    return ("_api/web/lists/getbytitle('%s')/items?$select=Id,RecipientKey,Effort&$filter=ProjectItemId eq @{%s}&$top=500" % (ps.ALLOC_LIST, pid))


def _sum_cents(g, name, rows_expr, where, after, var):
    """g[name]: Foreach over rows_expr where `where` (item fields via items(name)) adding cents(Effort) to variable `var`."""
    X = "items('%s')" % name
    g[name] = {"type": "Foreach", "runAfter": S(after) if isinstance(after, str) else after, "foreach": "@%s" % rows_expr,
               "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}}, "actions": {
                   "Add_" + name: {"type": "IncrementVariable", "runAfter": {}, "inputs": {"name": var, "value": "@if(and(%s, not(equals(%s?['Effort'], null))), %s, 0)"
                                                                                           % (where % X, X, cents(nz("%s?['Effort']" % X)))}}}}
    return name


# ---------------------------------------------------------------- EFF-ReadDisciplineEffort

def read_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                 source_flow="EFF-ReadDisciplineEffort", refs=None) -> dict:
    """Trigger: text ProjectItemId, text_1..5 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    P = o("Pid")

    def decide(g):
        g["Get_assign"] = _sp(S("Pid"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,PmEmployeeItemId&$filter=ProjectItemId eq @{%s}&$top=2"
                              % (ps.PM_LIST, P))
        A = "first(%s)" % _rows("Get_assign")
        is_pm = "and(greater(length(%s), 0), equals(%s, %s))" % (_rows("Get_assign"), _rq("%s?['PmEmployeeItemId']" % A), bef._caller_emp())
        R = B("ResolvedRoles")
        has = lambda *rs: "or(false, %s)" % ", ".join("contains(%s, '%s')" % (R, r) for r in rs)  # noqa: E731
        bc = B("ResultCode")
        role_scope = ("if(not(equals(%s, 'ALLOW')), 'none', if(%s, 'company', if(%s, 'discipline', if(%s, 'self', 'none'))))"
                      % (bc, has("PMO", "EXE"), has("TL"), has("EMP")))
        err = "and(%s, greater(%s, 0), not(%s))" % (bef._identity_ok(), P, _okd("Get_assign"))
        g["Role_scope"] = c("@" + role_scope, {"Get_assign": ["Succeeded", "Failed"]})
        g["Final_scope"] = c("@if(%s, 'none', if(and(%s, not(equals(outputs('Role_scope'), 'company'))), '%s', outputs('Role_scope')))"
                             % (err, is_pm, dr.PM_SCOPE), S("Role_scope"))
        g["Final_authz"] = c("@if(%s, 'ERROR', if(not(equals(outputs('Final_scope'), 'none')), 'ALLOW', if(equals(%s, 'ALLOW'), 'ROLE_NOT_ALLOWED', %s)))"
                             % (err, bc, bc), S("Final_scope"))
        return "Final_authz"
    g = bef._guard_pm(dr.VIEW, de.READ_DECOYS, source_flow, decide, bef._pid_actions, scope_config=dr.scope_config(), **kw)
    for v, typ, val in (("Ts", "array", "@json('[]')"), ("Next", "string", ""), ("PageFail", "boolean", False), ("Summary", "array", "@json('[]')"),
                        ("Rows_out", "array", "@json('[]')"), ("UsedC", "integer", 0), ("HoursD", "float", 0.0)):
        g["Init_" + v] = _init(v, typ, val)
    ok_authz = "equals(outputs('Final_authz'), 'ALLOW')"
    g["Pre"] = c("@if(not(%s), outputs('Final_authz'), if(not(greater(%s, 0)), 'VALIDATION_LOOKUP', 'OK'))" % (ok_authz, P), S("Write_Authz_audit"))
    det = {"Get_project": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items(@{%s})?$select=Id,LegacyId,ProjectCode,Title" % P)}
    det["Get_me"] = _me(emp_list, "Get_project", bef._caller_emp())
    det.update(bef._settings_reads("Get_me"))
    det["Get_discs"] = _sp(S("Get_settings"), "GET", "_api/web/lists/getbytitle('Disciplines')/items?$select=Id,LegacyId,DisciplineCode,Title&$top=500")
    det["Get_emps"] = _sp(S("Get_discs"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,Title&$top=5000" % emp_list)
    det["Get_wts"] = _sp(S("Get_emps"), "GET", "_api/web/lists/getbytitle('WorkTypes')/items?$select=Id,LegacyId,WorkTypeCode,Title,IsActive&$orderby=Id asc&$top=500")
    det["Get_regs"] = _sp(S("Get_wts"), "GET", _rows_uri(P))
    det["Get_allocs"] = _sp(S("Get_regs"), "GET", _allocs_uri(P))
    last = bef._settings_actions(det, "Get_allocs")
    # actual: Approved TimesheetEntries of the project, paged; collect {Id, Hours, DisciplineCode}
    first = ("_api/web/lists/getbytitle('%s')/items?$select=Id,Hours,DisciplineCode&$filter=ProjectId eq @{%s} and EntryStatus eq 'Approved'"
             "&$orderby=Id asc&$top=%d" % (bef.ENTRIES, P, bef.PAGE))
    nxt = "%s?['odata.nextLink']" % _ab("Get_page")
    det["Set_next"] = {"type": "SetVariable", "runAfter": S(last), "inputs": {"name": "Next", "value": first}}
    det["Pages"] = {"type": "Until", "runAfter": S("Set_next"), "expression": "@or(empty(variables('Next')), variables('PageFail'))",
                    "limit": {"count": bef.MAX_PAGES, "timeout": "PT1H"}, "actions": {
                        "Get_page": _sp({}, "GET", "@{variables('Next')}", meta="nometadata"),
                        "Page_rows": {"type": "Select", "runAfter": {"Get_page": ANY}, "inputs": {"from": "@%s" % _rows("Get_page"), "select": {
                            "id": "@item()?['Id']", "h": "@float(if(equals(item()?['Hours'], null), '0', %s))" % nz("item()?['Hours']"),
                            "d": "@%s" % nz("item()?['DisciplineCode']")}}},
                        # no self-referencing SetVariable (rejected by the platform): append the page item by item
                        "Add_page": {"type": "Foreach", "runAfter": S("Page_rows"), "foreach": "@body('Page_rows')", "actions": {
                            "Add_t": {"type": "AppendToArrayVariable", "runAfter": {}, "inputs": {"name": "Ts", "value": "@items('Add_page')"}}}},
                        "Set_more": {"type": "SetVariable", "runAfter": {"Add_page": ALL}, "inputs": {"name": "Next", "value":
                                     "@if(and(%s, not(empty(%s))), concat('_api/', last(split(%s, '/_api/'))), %s)" % (_okd("Get_page"), nz(nxt), nz(nxt), EMPTY)}},
                        "Set_fail": {"type": "SetVariable", "runAfter": S("Set_more"), "inputs": {"name": "PageFail", "value": "@not(%s)" % _okd("Get_page")}}}}
    scope = "outputs('Final_scope')"
    mydisc = nz(ME("DisciplineCode"))
    me_id = bef._caller_emp()
    vis = ("@or(or(equals(%s, 'company'), equals(%s, '%s')), and(equals(%s, 'discipline'), not(empty(%s)), equals(item()?['DisciplineCode'], %s)), "
           "and(equals(%s, 'self'), equals(%s, %s)))" % (scope, scope, dr.PM_SCOPE, scope, mydisc, mydisc, scope, _rq("item()?['EmployeeItemId']"), me_id))
    det["Visible"] = {"type": "Query", "runAfter": S("Pages"), "inputs": {"from": "@%s" % _rows("Get_regs"), "where": vis}}
    X = "items('Out_rows')"
    det["Out_rows"] = {"type": "Foreach", "runAfter": S("Visible"), "foreach": "@body('Visible')", "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                       "actions": {
                           "Find_emp": {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_emps"), "where": "@equals(int(item()?['Id']), %s)" % _rq("%s?['EmployeeItemId']" % X)}},
                           "Find_wt": {"type": "Query", "runAfter": S("Find_emp"), "inputs": {"from": "@%s" % _rows("Get_wts"), "where": "@equals(int(item()?['Id']), %s)" % _rq("%s?['WorkTypeItemId']" % X)}},
                           "Add_row": {"type": "AppendToArrayVariable", "runAfter": S("Find_wt"), "inputs": {"name": "Rows_out", "value": {
                               "id": "@int(%s?['Id'])" % X, "employeeId": "@%s" % _rq("%s?['EmployeeItemId']" % X),
                               "employeeName": "@{%s}" % nz("first(body('Find_emp'))?['Title']"), "disciplineCode": "@{%s}" % nz("%s?['DisciplineCode']" % X),
                               "workTypeId": "@%s" % _rq("%s?['WorkTypeItemId']" % X), "workTypeCode": "@{%s}" % nz("first(body('Find_wt'))?['WorkTypeCode']"),
                               "workTypeName": "@{%s}" % nz("first(body('Find_wt'))?['Title']"),
                               "state": "@{if(equals(%s?['Effort'], null), 'BLANK', 'VALUE')}" % X, "value": "@{%s}" % nz("%s?['Effort']" % X),
                               "status": "@{%s}" % nz("%s?['Status']" % X), "etag": "@{%s}" % nz("%s?['odata.etag']" % X),
                               "mine": "@equals(%s, %s)" % (_rq("%s?['EmployeeItemId']" % X), me_id)}}}}}
    # summary disciplines: own discipline for self / discipline scope; else configured recipients (existing) then row disciplines
    det["Disc_codes"] = {"type": "Select", "runAfter": S("Out_rows"), "inputs": {"from": "@%s" % _rows("Get_discs"), "select": "@item()?['DisciplineCode']"}}
    det["Cfg_existing"] = {"type": "Query", "runAfter": S("Disc_codes"), "inputs": {"from": "@body('Codes')", "where": "@contains(body('Disc_codes'), item())"}}
    det["Row_codes"] = {"type": "Select", "runAfter": S("Cfg_existing"), "inputs": {"from": "@%s" % _rows("Get_regs"), "select": "@item()?['DisciplineCode']"}}
    det["Sum_codes"] = c("@if(or(equals(%s, 'self'), equals(%s, 'discipline')), if(empty(%s), json('[]'), createArray(%s)), union(body('Cfg_existing'), body('Row_codes')))"
                         % (scope, scope, mydisc, mydisc), S("Row_codes"))
    Y = "items('Sum_loop')"
    inner = {}
    inner["Find_d"] = {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_discs"), "where": "@equals(item()?['DisciplineCode'], %s)" % Y}}
    inner["Find_a"] = {"type": "Query", "runAfter": S("Find_d"), "inputs": {"from": "@%s" % _rows("Get_allocs"), "where":
                       "@equals(%s, concat('D:', %s))" % (nz("item()?['RecipientKey']"), nz("first(body('Find_d'))?['LegacyId']"))}}
    inner["Ceil_has"] = c("@and(greater(length(body('Find_a')), 0), not(equals(first(body('Find_a'))?['Effort'], null)))", S("Find_a"))
    inner["Ceil_c"] = c("@if(outputs('Ceil_has'), %s, 0)" % cents(nz("first(body('Find_a'))?['Effort']")), S("Ceil_has"))
    inner["Reset_used"] = {"type": "SetVariable", "runAfter": S("Ceil_c"), "inputs": {"name": "UsedC", "value": 0}}
    _sum_cents(inner, "Used_loop", _rows("Get_regs"), "equals(%%s?['DisciplineCode'], %s)" % Y, "Reset_used", "UsedC")
    inner["Ts_d"] = {"type": "Query", "runAfter": S("Used_loop"), "inputs": {"from": "@variables('Ts')", "where": "@equals(item()?['d'], %s)" % Y}}
    inner["Reset_h"] = {"type": "SetVariable", "runAfter": S("Ts_d"), "inputs": {"name": "HoursD", "value": 0.0}}
    inner["Hours_loop"] = {"type": "Foreach", "runAfter": S("Reset_h"), "foreach": "@body('Ts_d')", "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                           "actions": {"Add_h": {"type": "IncrementVariable", "runAfter": {}, "inputs": {"name": "HoursD", "value": "@items('Hours_loop')?['h']"}}}}
    U = "variables('UsedC')"
    inner["Add_sum"] = {"type": "AppendToArrayVariable", "runAfter": S("Hours_loop"), "inputs": {"name": "Summary", "value": {
        "disciplineCode": "@{%s}" % Y, "disciplineName": "@{%s}" % nz("first(body('Find_d'))?['Title']"),
        "ceilingState": "@{if(outputs('Ceil_has'), 'VALUE', 'BLANK')}", "ceiling": "@{if(outputs('Ceil_has'), %s, %s)}" % (md("outputs('Ceil_c')"), EMPTY),
        "used": "@{%s}" % md(U), "remaining": "@{if(outputs('Ceil_has'), %s, %s)}" % (md("sub(outputs('Ceil_c'), %s)" % U), EMPTY),
        "actualHours": "@{string(variables('HoursD'))}", "actualManDays": "@{string(div(variables('HoursD'), %s))}" % bef.HPM}}}
    det["Sum_loop"] = {"type": "Foreach", "runAfter": S("Sum_codes"), "foreach": "@outputs('Sum_codes')",
                       "runtimeConfiguration": {"concurrency": {"repetitions": 1}}, "actions": inner}
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@outputs('Pre')", "OK"]}, "actions": det, "else": {"actions": {}}}
    missing = "and(not(%s), equals(actions('Get_project')?['outputs']?['statusCode'], 404))" % _okd("Get_project")
    reads_ok = "and(%s, %s, %s, %s, %s, %s, %s, %s, %s, not(variables('PageFail')), %s)" % tuple(
        _okd(n) for n in ("Get_project", "Get_me", "Get_settings", "Get_discs", "Get_emps", "Get_wts", "Get_regs", "Get_allocs", "Pages", "Sum_loop"))
    hpm_ok = "equals(actions('HpmOk')?['outputs'], true)"
    g["Final_code"] = c("@if(not(equals(outputs('Pre'), 'OK')), outputs('Pre'), if(%s, 'NOT_FOUND', if(not(and(%s, %s, %s)), 'ERROR', "
                        "if(not(and(%s, equals(actions('CodesOk')?['outputs'], true))), 'CONFIG_INVALID', if(not(%s), 'ERROR', 'OK')))))"
                        % (missing, _okd("Get_project"), _okd("Get_me"), _okd("Get_settings"), hpm_ok, reads_ok), {"If_ok": ANY})
    ok = "equals(outputs('Final_code'), 'OK')"
    R = G("ResolvedRoles")
    has = lambda *rs: "or(false, %s)" % ", ".join("contains(%s, '%s')" % (R, r) for r in rs)  # noqa: E731
    PR = _ab("Get_project")
    g["Project"] = c("@if(%s, setProperty(setProperty(setProperty(json('{}'), 'id', %s), 'code', %s), 'name', %s), json('{}'))"
                     % (ok, _rq("%s?['Id']" % PR), nz("%s?['ProjectCode']" % PR), nz("%s?['Title']" % PR)), S("Final_code"))
    g["Caller"] = c("@if(%s, setProperty(setProperty(setProperty(setProperty(json('{}'), 'employeeId', %s), 'disciplineCode', %s), 'canEdit', and(%s, not(empty(%s)))), "
                    "'canApprove', and(%s, not(empty(%s)))), json('{}'))" % (ok, me_id, mydisc, has("EMP", "TL"), mydisc, has("TL"), mydisc), S("Project"))
    g["Wts_active"] = {"type": "Query", "runAfter": S("Caller"), "inputs": {"from": "@if(%s, %s, createArray())" % (ok, _rows("Get_wts")), "where": "@equals(item()?['IsActive'], true)"}}
    g["Wts_out"] = {"type": "Select", "runAfter": S("Wts_active"), "inputs": {"from": "@body('Wts_active')", "select": {
        "id": "@int(item()?['Id'])", "code": "@{%s}" % nz("item()?['WorkTypeCode']"), "name": "@{%s}" % nz("item()?['Title']")}}}
    g.update(at.operation_event_actions("ReadProxy", "ReadDisciplineEffort", target_entity=REG, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                        environment=environment, source_flow=source_flow,
                                        target_id_expr="if(greater(%s, 0), string(%s), %s)" % (P, P, EMPTY),
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, after="Wts_out", name="Read_audit"))
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}", "messagecode": "@{concat('MSG_', outputs('Final_code'))}",
            "correlationid": "@{workflow()?['run']?['name']}", "scope": "@{if(%s, %s, 'none')}" % (ok, scope),
            "project": "@{string(outputs('Project'))}", "caller": "@{string(outputs('Caller'))}",
            "rows": "@{string(if(%s, variables('Rows_out'), json('[]')))}" % ok, "summary": "@{string(if(%s, variables('Summary'), json('[]')))}" % ok,
            "worktypes": "@{string(body('Wts_out'))}"}
    g["Respond"] = bf._respond(body, "Write_Read_audit")
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "scope": "none", "project": "{}", "caller": "{}", "rows": "[]", "summary": "[]", "worktypes": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- EFF-SaveDisciplineEffort

def _pre_loop():
    X = "items('Pre_loop')"
    wt, st, v, et = ("%s?['%s']" % (X, f) for f in ("workTypeId", "state", "value", "etag"))
    me_id = "int(%s)" % G("EmployeeId")
    a = {}
    a["Find_wt"] = {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_wts"), "where": "@equals(int(item()?['Id']), %s)" % _rq(wt)}}
    a["Find"] = {"type": "Query", "runAfter": S("Find_wt"), "inputs": {"from": "@%s" % _rows("Get_regs"), "where":
                 "@and(equals(%s, %s), equals(%s, %s))" % (_rq("item()?['EmployeeItemId']"), me_id, _rq("item()?['WorkTypeItemId']"), _rq(wt))}}
    F, W = "first(body('Find'))", "first(body('Find_wt'))"
    found = "not(equals(%s, null))" % F
    stored = nz("%s?['Effort']" % F)
    has_val = "and(%s, not(equals(%s?['Effort'], null)))" % (found, F)
    se = nz("%s?['odata.etag']" % F)
    # split into small Composes: the platform limits one expression to 8192 characters
    a["P_vok"] = c("@" + _value_ok(v), S("Find"))
    vok = "outputs('P_vok')"
    a["P_newc"] = c("@if(equals(%s, 'blank'), 0, %s)" % (st, cents("if(%s, %s, '0')" % (vok, v))), S("P_vok"))
    a["P_oldc"] = c("@if(%s, %s, 0)" % (has_val, cents(stored)), S("P_newc"))
    a["P_same"] = c("@if(equals(%s, 'blank'), not(%s), and(%s, equals(outputs('P_oldc'), outputs('P_newc'))))" % (st, has_val, has_val), S("P_oldc"))
    code = ("if(or(equals(%(W)s, null), and(not(%(found)s), not(equals(%(W)s?['IsActive'], true)))), 'VALIDATION_LOOKUP', "
            "if(not(or(equals(%(st)s, 'blank'), equals(%(st)s, 'value'))), 'VALIDATION_VALUE', "
            "if(and(equals(%(st)s, 'value'), not(%(vok)s)), 'VALIDATION_VALUE', "
            "if(and(equals(%(st)s, 'value'), %(long)s), 'TECHNICAL_LIMIT', "
            "if(and(%(found)s, equals(%(F)s?['Status'], '%(ap)s')), 'LOCKED', "
            "if(or(and(not(%(found)s), not(empty(%(et)s))), and(%(found)s, not(equals(%(et)s, %(se)s)))), 'CONFLICT', "
            "if(outputs('P_same'), 'NO_CHANGE', 'WRITE')))))))"
            % dict(W=W, found=found, st=st, vok=vok, long=_too_long(v), F=F, ap=ds.APPROVED, et=et, se=se))
    a["P_code"] = c("@" + code, S("P_same"))
    a["P_delta"] = c("@if(equals(outputs('P_code'), 'WRITE'), sub(outputs('P_newc'), outputs('P_oldc')), 0)", S("P_code"))
    a["Add_pre"] = {"type": "AppendToArrayVariable", "runAfter": S("P_delta"), "inputs": {"name": "Pre", "value": {
        "workTypeId": "@%s" % _rq(wt), "state": "@%s" % st, "value": "@%s" % v, "etag": "@%s" % et, "code": "@{outputs('P_code')}",
        "itemId": "@if(%s, %s?['Id'], 0)" % (found, F), "stored": "@%s" % se, "old": "@%s" % stored,
        "regkey": "@if(%s, %s, concat(%s, '|', %s, '|', %s))" % (found, nz("%s?['RegKey']" % F), nz("%s?['LegacyId']" % _ab("Get_project")),
                                                               nz("%s?['LegacyId']" % _ab("Get_me")), nz("%s?['LegacyId']" % W)),
        "wtLegacy": "@{%s}" % nz("%s?['LegacyId']" % W), "setsValue": "@and(equals(outputs('P_code'), 'WRITE'), equals(%s, 'value'))" % st}}}
    a["Add_delta"] = {"type": "IncrementVariable", "runAfter": S("Add_pre"), "inputs": {"name": "DeltaC", "value": "@outputs('P_delta')"}}
    return a


def _write_loop(*, audit_list, conf_audit_list, environment, source_flow):
    W = "items('Writes')"
    w = lambda k: "%s?['%s']" % (W, k)  # noqa: E731
    T, P = o("Trusted"), o("Pid")
    is_new = "equals(%s, 0)" % w("itemId")
    blank = "equals(%s, 'blank')" % w("state")
    newval = "if(%s, null, float(if(%s, '0', %s)))" % (blank, blank, w("value"))
    meta = {"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")}}
    a = {}
    a["W_create"] = c(dict(meta, Title="@{%s}" % w("regkey"), RegKey="@{%s}" % w("regkey"), LegacyId="@{%s}" % w("regkey"),
                           ProjectId="@%s" % P, ProjectItemId="@%s" % P, EmployeeId="@int(%s)" % G("EmployeeId"),
                           EmployeeItemId="@int(%s)" % G("EmployeeId"), EmployeeLegacyId="@{%s}" % nz("%s?['LegacyId']" % _ab("Get_me")),
                           OwnerUpn="@{%s}" % T, DisciplineId="@int(%s)" % ME("Id"), DisciplineItemId="@int(%s)" % ME("Id"),
                           DisciplineCode="@{%s}" % nz(ME("DisciplineCode")), DisciplineLegacyId="@{%s}" % nz(ME("LegacyId")),
                           WorkTypeId="@%s" % w("workTypeId"), WorkTypeItemId="@%s" % w("workTypeId"), WorkTypeLegacyId="@{%s}" % w("wtLegacy"),
                           Effort="@%s" % newval, Status=ds.DRAFT, ActorUpn="@{%s}" % T, CorrelationId="@{workflow()?['run']?['name']}"), {})
    a["W_merge"] = c(dict(meta, Effort="@%s" % newval, ActorUpn="@{%s}" % T, CorrelationId="@{workflow()?['run']?['name']}"), S("W_create"))
    create = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items" % REG, body="@{string(outputs('W_create'))}", meta="verbose")
    merge = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s})" % (REG, w("itemId")), body="@{string(outputs('W_merge'))}",
                meta="verbose", headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % w("stored")})
    for x in (create, merge):
        x["inputs"]["retryPolicy"] = {"type": "none"}
    a["If_change"] = {"type": "If", "runAfter": S("W_merge"), "expression": {"not": {"equals": ["@%s" % w("code"), "NO_CHANGE"]}},
                      "actions": {"If_new": {"type": "If", "runAfter": {}, "expression": {"equals": ["@%s" % is_new, True]}, "actions": {"Create": create},
                                             "else": {"actions": {"Merge": merge, "Get_new": _sp(S("Merge"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s})?$select=Id" % (REG, w("itemId")))}}}},
                      "else": {"actions": {}}}
    sc = lambda n: "actions('%s')?['outputs']?['statusCode']" % n  # noqa: E731
    nn = lambda x: "if(equals(%s, null), 0, %s)" % (x, x)  # noqa: E731
    written = "if(%s, %s, %s)" % (is_new, _okd("Create"), _okd("Merge"))
    conflict = "if(%s, and(greater(%s, 399), less(%s, 500)), equals(%s, 412))" % (is_new, nn(sc("Create")), nn(sc("Create")), nn(sc("Merge")))
    a["W_final"] = c("@if(equals(%s, 'NO_CHANGE'), 'NO_CHANGE', if(%s, 'OK', if(%s, 'CONFLICT', 'ERROR')))" % (w("code"), written, conflict), {"If_change": ANY})
    ok = "equals(outputs('W_final'), 'OK')"
    a["W_id"] = c("@if(%s, if(%s, %s?['d']?['Id'], 0), %s)" % (is_new, ok, _ab("Create"), w("itemId")), S("W_final"))
    new_etag = nz("if(%s, %s?['d']?['__metadata']?['etag'], %s?['odata.etag'])" % (is_new, _ab("Create"), _ab("Get_new")))
    a["W_etag"] = c("@if(equals(outputs('W_final'), 'NO_CHANGE'), %s, if(%s, %s, %s))" % (w("stored"), ok, new_etag, EMPTY), S("W_id"))
    action = "if(%s, 'Create', if(%s, 'Clear', 'Update'))" % (is_new, blank)
    ev = at.operation_event_actions("WriteProxy", "Update", target_entity=REG, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                    environment=environment, source_flow=source_flow, target_id_expr="string(outputs('W_id'))",
                                    target_legacy_id_expr=w("regkey"), change_fields={"EffortOld": w("old"), "Effort": "if(%s, %s, %s)" % (blank, EMPTY, w("value"))},
                                    after="W_etag", name="Cell_audit")
    ev["Cell_audit"]["inputs"]["Action"] = "@{%s}" % action
    ev["Cell_audit"]["inputs"]["Title"] = "@{concat('WriteProxy ', %s, ' ALLOW')}" % action
    ev["Cell_audit"]["inputs"]["ActionText"] = ""
    write_audit = ev.pop("Write_Cell_audit")
    a["If_committed"] = {"type": "If", "runAfter": S("W_etag"), "expression": {"equals": ["@" + ok, True]},
                         "actions": dict({k: dict(v, runAfter=({} if k == "Cell_audit_change" else v["runAfter"])) for k, v in ev.items()},
                                         Write_Cell_audit=write_audit,
                                         Mark_degraded={"type": "SetVariable", "runAfter": {"Write_Cell_audit": ["Failed", "TimedOut"]},
                                                        "inputs": {"name": "Degraded", "value": True}}), "else": {"actions": {}}}
    a["Add_result"] = {"type": "AppendToArrayVariable", "runAfter": {"If_committed": ANY}, "inputs": {"name": "Results", "value": {
        "workTypeId": "@%s" % w("workTypeId"), "resultcode": "@{outputs('W_final')}", "etag": "@{outputs('W_etag')}"}}}
    a["Count_saved"] = {"type": "IncrementVariable", "runAfter": S("Add_result"), "inputs": {"name": "Saved", "value": "@if(%s, 1, 0)" % ok}}
    a["Count_failed"] = {"type": "IncrementVariable", "runAfter": S("Count_saved"),
                         "inputs": {"name": "Failed", "value": "@if(or(%s, equals(outputs('W_final'), 'NO_CHANGE')), 0, 1)" % ok}}
    return a


def save_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                 source_flow="EFF-SaveDisciplineEffort", refs=None) -> dict:
    """Trigger: text ProjectItemId, text_1 Changes (JSON [{workTypeId, state, value, etag}], 1-20), text_2 ClientRequestId, text_3..8 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = _guard(dr.EDIT, de.SAVE_DECOYS, source_flow, **kw)
    g["PidIn"] = c("@" + _tb("text"), S("Write_Authz_audit"))
    g["Pid"] = c("@" + _safe_int(o("PidIn")), S("PidIn"))
    P = o("Pid")
    g["ChangesRaw"] = c("@" + _raw("text_1"), S("Pid"))
    g["ClientRequestId"] = c("@" + _tb("text_2"), S("ChangesRaw"))
    for v, typ, val in (("Pre", "array", "@json('[]')"), ("Results", "array", "@json('[]')"), ("Saved", "integer", 0), ("Failed", "integer", 0),
                        ("Degraded", "boolean", False), ("OldC", "integer", 0), ("DeltaC", "integer", 0), ("Claimed", "boolean", False)):
        g["Init_" + v] = _init(v, typ, val)
    g["Ch_parse"] = dict(c("@json(if(empty(outputs('ChangesRaw')), 'x', outputs('ChangesRaw')))", S("ClientRequestId")), metadata=FAIL_HANDLED)
    g["Ch_arr"] = {"type": "Query", "runAfter": S("Ch_parse"), "metadata": FAIL_HANDLED, "inputs": {"from": "@outputs('Ch_parse')", "where": "@true"}}
    sx = lambda k: "trim(%s)" % nz("item()?['%s']" % k)  # noqa: E731
    g["Ch_norm"] = {"type": "Select", "runAfter": S("Ch_arr"), "metadata": FAIL_HANDLED, "inputs": {"from": "@body('Ch_arr')", "select": {
        "workTypeId": "@" + _safe_int(sx("workTypeId")), "state": "@toLower(%s)" % sx("state"), "value": "@" + sx("value"), "etag": "@" + nz("item()?['etag']")}}}
    g["Ch_keys"] = {"type": "Select", "runAfter": {"Ch_norm": ALL, "ClientRequestId": ["Succeeded"]}, "inputs": {
        "from": "@if(%s, %s, json('[]'))" % (_okd("Ch_norm"), _ab("Ch_norm")), "select": "@item()?['workTypeId']"}}
    keys = "body('Ch_keys')"
    shape_ok = ("and(%s, greater(length(%s), 0), not(greater(length(%s), %d)), equals(length(union(%s, %s)), length(%s)))"
                % (_okd("Ch_norm"), keys, keys, de.MAX_CHANGES, keys, keys, keys))
    g["Pre_code"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(%s), 'VALIDATION_REQUEST', if(not(greater(%s, 0)), 'VALIDATION_LOOKUP', 'OK')))"
                      % (G("ResultCode"), G("ResultCode"), shape_ok, P), S("Ch_keys"))
    reads = {"Get_project": _sp({}, "GET", "_api/web/lists/getbytitle('Projects')/items(@{%s})?$select=Id,LegacyId,ProjectCode,Title" % P)}
    reads["Get_me"] = _me(emp_list, "Get_project", "int(%s)" % G("EmployeeId"))
    reads["Get_wts"] = _sp(S("Get_me"), "GET", "_api/web/lists/getbytitle('WorkTypes')/items?$select=Id,LegacyId,WorkTypeCode,Title,IsActive&$top=500")
    reads["Get_allocs"] = _sp(S("Get_wts"), "GET", _allocs_uri(P))
    LK = "concat(%s, '|', %s)" % (nz("%s?['LegacyId']" % _ab("Get_project")), nz(ME("LegacyId")))
    reads["Has_disc"] = c("@not(empty(%s))" % nz(ME("DisciplineCode")), S("Get_allocs"))
    reads["Get_lock"] = _sp(S("Has_disc"), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,LockKey,Busy,BusyUntil&$filter=LockKey eq '@{%s}'&$top=2" % (LOCK, LK))
    reads["Get_ltype"] = _sp(S("Get_lock"), "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % LOCK)
    lmeta = {"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_ltype")}}
    L = "first(%s)" % _rows("Get_lock")
    reads["If_nolock"] = {"type": "If", "runAfter": S("Get_ltype"), "expression": {"equals": ["@and(%s, equals(length(%s), 0), outputs('Has_disc'))" % (_okd("Get_lock"), _rows("Get_lock")), True]},
                          "actions": {"L_body": c(dict(lmeta, Title="@{%s}" % LK, LockKey="@{%s}" % LK, LegacyId="@{%s}" % LK, ProjectItemId="@%s" % P,
                                                      DisciplineItemId="@int(%s)" % ME("Id"), Busy=False, Stamp="@{workflow()?['run']?['name']}"), {}),
                                      "L_create": dict(_sp(S("L_body"), "POST", "_api/web/lists/getbytitle('%s')/items" % LOCK, body="@{string(outputs('L_body'))}", meta="verbose"))},
                          "else": {"actions": {}}}
    reads["If_nolock"]["actions"]["L_create"]["inputs"]["retryPolicy"] = {"type": "none"}
    reads["Get_lock2"] = _sp({"If_nolock": ANY}, "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,LockKey,Busy,BusyUntil&$filter=LockKey eq '@{%s}'&$top=2" % (LOCK, LK))
    L2 = "first(%s)" % _rows("Get_lock2")
    busy = "and(equals(%s?['Busy'], true), greater(%s, %s))" % (L2, nz("%s?['BusyUntil']" % L2), NOW)
    reads["Lock_ok"] = c("@and(outputs('Has_disc'), %s, equals(length(%s), 1), not(%s))" % (_okd("Get_lock2"), _rows("Get_lock2"), busy), S("Get_lock2"))
    claim = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s?['Id']})" % (LOCK, L2), meta="verbose",
                headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s}" % nz("%s?['odata.etag']" % L2)},
                body="@{string(outputs('C_body'))}")
    claim["inputs"]["retryPolicy"] = {"type": "none"}
    reads["If_claim"] = {"type": "If", "runAfter": S("Lock_ok"), "expression": {"equals": ["@outputs('Lock_ok')", True]},
                         "actions": {"C_body": c(dict(lmeta, Busy=True, BusyUntil="@{addMinutes(utcNow(), %d, 'yyyy-MM-ddTHH:mm:ssZ')}" % ds.LOCK_MINUTES,
                                                     Stamp="@{workflow()?['run']?['name']}"), {}),
                                     "Claim": dict(claim, runAfter=S("C_body")),
                                     "Set_claimed": {"type": "SetVariable", "runAfter": S("Claim"), "inputs": {"name": "Claimed", "value": True}},
                                     "Get_regs": _sp(S("Set_claimed"), "GET", _rows_uri(P))},
                         "else": {"actions": {}}}
    reads["Pre_loop"] = {"type": "Foreach", "runAfter": {"If_claim": ANY}, "foreach": "@if(variables('Claimed'), %s, json('[]'))" % _ab("Ch_norm"),
                         "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}}, "actions": _pre_loop()}
    D = nz(ME("DisciplineCode"))
    _sum_cents(reads, "Old_loop", "if(variables('Claimed'), %s, json('[]'))" % _rows("Get_regs"), "equals(%%s?['DisciplineCode'], %s)" % D, "Pre_loop", "OldC")
    g["If_ok"] = {"type": "If", "runAfter": S("Pre_code"), "expression": {"equals": ["@outputs('Pre_code')", "OK"]}, "actions": reads, "else": {"actions": {}}}
    missing = "and(not(%s), equals(actions('Get_project')?['outputs']?['statusCode'], 404))" % _okd("Get_project")
    g["Read_code"] = c("@if(not(equals(outputs('Pre_code'), 'OK')), outputs('Pre_code'), if(%s, 'NOT_FOUND', if(not(and(%s, %s, %s, %s)), 'ERROR', "
                       "if(not(equals(actions('Has_disc')?['outputs'], true)), 'VALIDATION_LOOKUP', if(not(variables('Claimed')), "
                       "if(or(not(%s), not(%s)), 'ERROR', 'CONFLICT'), if(not(and(%s, %s)), 'ERROR', 'OK'))))))"
                       % (missing, _okd("Get_project"), _okd("Get_me"), _okd("Get_wts"), _okd("Get_allocs"), _okd("Get_lock"), _okd("Get_ltype"),
                          _okd("Get_regs"), _okd("Pre_loop")), {"If_ok": ANY})
    g["Bad"] = {"type": "Query", "runAfter": S("Read_code"), "inputs": {"from": "@variables('Pre')", "where": "@not(or(equals(item()?['code'], 'WRITE'), equals(item()?['code'], 'NO_CHANGE')))"}}
    A = "first(body('Ceil_a'))"
    g["Ceil_a"] = {"type": "Query", "runAfter": S("Bad"), "inputs": {"from": "@%s" % _rows("Get_allocs"), "where": "@equals(%s, concat('D:', %s))" % (nz("item()?['RecipientKey']"), nz(ME("LegacyId")))}}
    g["Ceil_has"] = c("@and(greater(length(body('Ceil_a')), 0), not(equals(%s?['Effort'], null)))" % A, S("Ceil_a"))
    g["Ceil_c"] = c("@if(outputs('Ceil_has'), %s, 0)" % cents(nz("%s?['Effort']" % A)), S("Ceil_has"))
    g["Sets"] = {"type": "Query", "runAfter": S("Ceil_c"), "inputs": {"from": "@variables('Pre')", "where": "@equals(item()?['setsValue'], true)"}}
    oldc, newc = "variables('OldC')", "add(variables('OldC'), variables('DeltaC'))"
    g["Ceil_code"] = c("@if(and(not(outputs('Ceil_has')), greater(length(body('Sets')), 0)), 'CEILING_NOT_REGISTERED', "
                       "if(and(outputs('Ceil_has'), greater(%s, outputs('Ceil_c')), greater(%s, %s)), 'OVER_CEILING', 'OK'))" % (newc, newc, oldc), S("Sets"))
    g["Pre_ok"] = c("@and(equals(outputs('Read_code'), 'OK'), equals(length(body('Bad')), 0), equals(outputs('Ceil_code'), 'OK'))", S("Ceil_code"))
    g["If_write"] = {"type": "If", "runAfter": S("Pre_ok"), "expression": {"equals": ["@outputs('Pre_ok')", True]},
                     "actions": {"Get_type": _sp({}, "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % REG),
                                 "Writes": {"type": "Foreach", "runAfter": S("Get_type"), "foreach": "@variables('Pre')",
                                            "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                                            "actions": _write_loop(audit_list=audit_list, conf_audit_list=conf_audit_list, environment=environment, source_flow=source_flow)}},
                     "else": {"actions": {}}}
    rel = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s?['Id']})" % (LOCK, L2), meta="verbose",
              headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "*"}, body="@{string(outputs('R_body'))}")
    rel["inputs"]["retryPolicy"] = {"type": "none"}
    g["If_release"] = {"type": "If", "runAfter": {"If_write": ANY}, "expression": {"equals": ["@variables('Claimed')", True]},
                       "actions": {"R_body": c(dict(lmeta, Busy=False, Stamp="@{workflow()?['run']?['name']}"), {}), "Release": dict(rel, runAfter=S("R_body"))},
                       "else": {"actions": {}}}
    F = "variables('Failed')"
    g["Final_code"] = c("@if(not(equals(outputs('Read_code'), 'OK')), outputs('Read_code'), if(not(equals(length(body('Bad')), 0)), 'REFUSED', "
                        "if(not(equals(outputs('Ceil_code'), 'OK')), 'REFUSED', if(not(%s), 'ERROR', if(greater(%s, 0), 'PARTIAL', 'OK')))))" % (_okd("Get_type"), F),
                        {"If_release": ANY})
    refused_code = ("if(not(equals(length(body('Bad')), 0)), if(or(equals(item()?['code'], 'WRITE'), equals(item()?['code'], 'NO_CHANGE')), 'NOT_WRITTEN', item()?['code']), "
                    "if(equals(item()?['code'], 'WRITE'), outputs('Ceil_code'), 'NOT_WRITTEN'))")
    g["Refused_results"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {
        "from": "@if(equals(outputs('Final_code'), 'REFUSED'), variables('Pre'), createArray())", "select": {
            "workTypeId": "@item()?['workTypeId']", "resultcode": "@" + refused_code, "etag": ""}}}
    fin_ok = "or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL'))"
    used_after = "if(%s, %s, %s)" % (fin_ok, newc, oldc)
    show = "or(%s, equals(outputs('Final_code'), 'REFUSED'))" % fin_ok
    clean = "and(%s, equals(%s, 0))" % (show, F)
    g["Audit_status"] = c("@if(variables('Degraded'), 'AUDIT_DEGRADED', if(%s, 'OK', %s))" % (fin_ok, EMPTY), S("Refused_results"))
    g["Warnings"] = {"type": "Query", "runAfter": S("Audit_status"), "inputs": {
        "from": "@createArray(if(greater(%s, 0), 'WARN_RELOAD_REQUIRED', %s), if(variables('Degraded'), 'AUDIT_DEGRADED', %s))" % (F, EMPTY, EMPTY), "where": "@not(empty(item()))"}}
    body = {"ok": "@{if(%s, 'true', 'false')}" % fin_ok, "resultcode": "@{outputs('Final_code')}", "messagecode": "@{concat('MSG_', outputs('Final_code'))}",
            "correlationid": "@{workflow()?['run']?['name']}", "savedcount": "@{string(variables('Saved'))}",
            "results": "@{string(if(equals(outputs('Final_code'), 'REFUSED'), body('Refused_results'), variables('Results')))}",
            "ceiling": "@{if(and(%s, outputs('Ceil_has')), %s, %s)}" % (show, md("outputs('Ceil_c')"), EMPTY),
            "used": "@{if(%s, %s, %s)}" % (clean, md(used_after), EMPTY),
            "remaining": "@{if(and(%s, outputs('Ceil_has')), %s, %s)}" % (clean, md("sub(outputs('Ceil_c'), %s)" % used_after), EMPTY),
            "auditstatus": "@{outputs('Audit_status')}", "warnings": "@{string(body('Warnings'))}"}
    g["Respond"] = bf._respond(body, "Warnings")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {"runStatus": "Failed", "runError": {
                                  "code": "AUDIT_DEGRADED", "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}}, "else": {"actions": {}}}
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "savedcount": "0", "results": "[]", "ceiling": "", "used": "", "remaining": "", "auditstatus": "", "warnings": "[]"})
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- EFF-ApproveDisciplineEffort

def approve_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                    source_flow="EFF-ApproveDisciplineEffort", refs=None) -> dict:
    """Trigger: text Items (JSON [{itemId, etag}], 1-50), text_1 ClientRequestId, text_2..7 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = _guard(dr.APPROVE, de.APPROVE_DECOYS, source_flow, **kw)
    g["ItemsRaw"] = c("@" + _raw("text"), S("Write_Authz_audit"))
    for v, typ, val in (("Rows", "array", "@json('[]')"), ("Totals", "array", "@json('[]')"), ("Results", "array", "@json('[]')"),
                        ("Approved", "integer", 0), ("Degraded", "boolean", False), ("TotC", "integer", 0)):
        g["Init_" + v] = _init(v, typ, val)
    g["It_parse"] = dict(c("@json(if(empty(outputs('ItemsRaw')), 'x', outputs('ItemsRaw')))", S("ItemsRaw")), metadata=FAIL_HANDLED)
    g["It_arr"] = {"type": "Query", "runAfter": S("It_parse"), "metadata": FAIL_HANDLED, "inputs": {"from": "@outputs('It_parse')", "where": "@true"}}
    g["It_norm"] = {"type": "Select", "runAfter": S("It_arr"), "metadata": FAIL_HANDLED, "inputs": {"from": "@body('It_arr')", "select": {
        "itemId": "@" + _safe_int("trim(%s)" % nz("item()?['itemId']")), "etag": "@" + nz("item()?['etag']")}}}
    g["It_ids"] = {"type": "Select", "runAfter": {"It_norm": ALL}, "inputs": {"from": "@if(%s, %s, json('[]'))" % (_okd("It_norm"), _ab("It_norm")), "select": "@item()?['itemId']"}}
    ids = "body('It_ids')"
    g["It_zero"] = {"type": "Query", "runAfter": S("It_ids"), "inputs": {"from": "@%s" % ids, "where": "@not(greater(item(), 0))"}}
    shape_ok = ("and(%s, greater(length(%s), 0), not(greater(length(%s), %d)), equals(length(union(%s, %s)), length(%s)), equals(length(body('It_zero')), 0))"
                % (_okd("It_norm"), ids, ids, de.MAX_ITEMS, ids, ids, ids))
    g["Pre_code"] = c("@if(not(equals(%s, 'ALLOW')), %s, if(not(%s), 'VALIDATION_REQUEST', 'OK'))" % (G("ResultCode"), G("ResultCode"), shape_ok), S("It_zero"))
    reads = {"Get_me": _me(emp_list, None, "int(%s)" % G("EmployeeId"))}
    MYD = nz(ME("DisciplineCode"))
    X = "items('Load')"
    reads["Load"] = {"type": "Foreach", "runAfter": S("Get_me"), "foreach": "@%s" % _ab("It_norm"), "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                     "actions": {"Get_row": _sp({}, "GET", "_api/web/lists/getbytitle('%s')/items(@{%s?['itemId']})?$select=Id,RegKey,ProjectItemId,DisciplineCode,"
                                                "DisciplineLegacyId,Effort,Status" % (REG, X)),
                                 "Add_row": {"type": "AppendToArrayVariable", "runAfter": {"Get_row": ANY}, "inputs": {"name": "Rows", "value": {
                                     "itemId": "@%s?['itemId']" % X, "etag": "@%s?['etag']" % X, "found": "@%s" % _okd("Get_row"),
                                     "missing": "@equals(actions('Get_row')?['outputs']?['statusCode'], 404)",
                                     "row": "@if(%s, %s, json('{}'))" % (_okd("Get_row"), _ab("Get_row"))}}}}}
    reads["Pids"] = {"type": "Select", "runAfter": S("Load"), "inputs": {"from": "@variables('Rows')", "select": "@%s" % _rq("item()?['row']?['ProjectItemId']")}}
    reads["Pids_mine"] = {"type": "Query", "runAfter": S("Pids"), "inputs": {"from": "@union(body('Pids'), body('Pids'))", "where": "@greater(item(), 0)"}}
    Z = "items('Per_project')"
    per = {"Get_pregs": _sp({}, "GET", _rows_uri(Z)), "Get_pallocs": _sp(S("Get_pregs"), "GET", _allocs_uri(Z)),
           "Reset_t": {"type": "SetVariable", "runAfter": S("Get_pallocs"), "inputs": {"name": "TotC", "value": 0}}}
    _sum_cents(per, "Tot_loop", _rows("Get_pregs"), "equals(%%s?['DisciplineCode'], %s)" % MYD, "Reset_t", "TotC")
    per["Pa"] = {"type": "Query", "runAfter": S("Tot_loop"), "inputs": {"from": "@%s" % _rows("Get_pallocs"), "where": "@equals(%s, concat('D:', %s))" % (nz("item()?['RecipientKey']"), nz(ME("LegacyId")))}}
    PA = "first(body('Pa'))"
    per["Add_tot"] = {"type": "AppendToArrayVariable", "runAfter": S("Pa"), "inputs": {"name": "Totals", "value": {
        "pid": "@%s" % Z, "ok": "@and(%s, %s)" % (_okd("Get_pregs"), _okd("Get_pallocs")), "total": "@variables('TotC')",
        "hasCeil": "@and(greater(length(body('Pa')), 0), not(equals(%s?['Effort'], null)))" % PA,
        "ceil": "@if(and(greater(length(body('Pa')), 0), not(equals(%s?['Effort'], null))), %s, 0)" % (PA, cents(nz("%s?['Effort']" % PA)))}}}
    reads["Per_project"] = {"type": "Foreach", "runAfter": S("Pids_mine"), "foreach": "@body('Pids_mine')", "runtimeConfiguration": {"concurrency": {"repetitions": 1}}, "actions": per}
    reads["Get_type"] = _sp(S("Per_project"), "GET", "_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % REG)
    Rw = "items('Rows_loop')"
    rr = lambda k: "%s?['row']?['%s']" % (Rw, k)  # noqa: E731
    row = {}
    row["Tot"] = {"type": "Query", "runAfter": {}, "inputs": {"from": "@variables('Totals')", "where": "@equals(item()?['pid'], %s)" % _rq(rr("ProjectItemId"))}}
    TT = "first(body('Tot'))"
    row["R_code"] = c("@if(not(%s?['found']), if(%s?['missing'], 'NOT_FOUND', 'ERROR'), if(not(equals(%s, %s)), 'SCOPE_NOT_ALLOWED', "
                      "if(equals(%s, '%s'), 'LOCKED', if(equals(%s, null), 'VALIDATION_VALUE', if(not(equals(%s?['etag'], %s)), 'CONFLICT', "
                      "if(or(equals(%s, null), not(%s?['ok'])), 'ERROR', if(not(%s?['hasCeil']), 'CEILING_NOT_REGISTERED', "
                      "if(greater(coalesce(%s?['total'], 0), coalesce(%s?['ceil'], 0)), 'OVER_CEILING', 'WRITE'))))))))"
                      % (Rw, Rw, nz(rr("DisciplineCode")), MYD, nz(rr("Status")), ds.APPROVED, rr("Effort"), Rw, nz(rr("odata.etag")),
                         TT, TT, TT, TT, TT), S("Tot"))
    row["A_body"] = c({"__metadata": {"type": "@{%s?['ListItemEntityTypeFullName']}" % _ab("Get_type")}, "Status": ds.APPROVED,
                       "ApprovedBy": "@{%s}" % o("Trusted"), "ApprovedOn": "@{%s}" % NOW, "ActorUpn": "@{%s}" % o("Trusted"),
                       "CorrelationId": "@{workflow()?['run']?['name']}"}, S("R_code"))
    merge = _sp({}, "POST", "_api/web/lists/getbytitle('%s')/items(@{%s?['itemId']})" % (REG, Rw), meta="verbose",
                headers={"X-HTTP-Method": "MERGE", "IF-MATCH": "@{%s?['etag']}" % Rw}, body="@{string(outputs('A_body'))}")
    merge["inputs"]["retryPolicy"] = {"type": "none"}
    row["If_w"] = {"type": "If", "runAfter": S("A_body"), "expression": {"equals": ["@outputs('R_code')", "WRITE"]},
                   "actions": {"Approve_m": merge, "Get_after": _sp(S("Approve_m"), "GET", "_api/web/lists/getbytitle('%s')/items(@{%s?['itemId']})?$select=Id" % (REG, Rw))},
                   "else": {"actions": {}}}
    nn = lambda x: "if(equals(%s, null), 0, %s)" % (x, x)  # noqa: E731
    row["R_final"] = c("@if(not(equals(outputs('R_code'), 'WRITE')), outputs('R_code'), if(%s, 'OK', if(equals(%s, 412), 'CONFLICT', 'ERROR')))"
                       % (_okd("Approve_m"), nn("actions('Approve_m')?['outputs']?['statusCode']")), {"If_w": ANY})
    okr = "equals(outputs('R_final'), 'OK')"
    ev = at.operation_event_actions("Approval", "Approve", target_entity=REG, audit_list=audit_list, conf_audit_list=conf_audit_list,
                                    environment=environment, source_flow=source_flow, target_id_expr="string(%s?['itemId'])" % Rw,
                                    target_legacy_id_expr=nz(rr("RegKey")), change_fields={"Status": "'%s'" % ds.APPROVED}, after="R_final", name="Row_audit")
    write_audit = ev.pop("Write_Row_audit")
    row["If_row_ok"] = {"type": "If", "runAfter": S("R_final"), "expression": {"equals": ["@" + okr, True]},
                    "actions": dict({k: dict(v, runAfter=({} if k == "Row_audit_change" else v["runAfter"])) for k, v in ev.items()}, Write_Row_audit=write_audit,
                                    Mark_degraded={"type": "SetVariable", "runAfter": {"Write_Row_audit": ["Failed", "TimedOut"]}, "inputs": {"name": "Degraded", "value": True}}),
                    "else": {"actions": {}}}
    row["Add_result"] = {"type": "AppendToArrayVariable", "runAfter": {"If_row_ok": ANY}, "inputs": {"name": "Results", "value": {
        "itemId": "@%s?['itemId']" % Rw, "resultcode": "@{outputs('R_final')}", "etag": "@{if(%s, %s, %s)}" % (okr, nz("%s?['odata.etag']" % _ab("Get_after")), EMPTY)}}}
    row["Count"] = {"type": "IncrementVariable", "runAfter": S("Add_result"), "inputs": {"name": "Approved", "value": "@if(%s, 1, 0)" % okr}}
    reads["Rows_loop"] = {"type": "Foreach", "runAfter": {"Get_type": ANY}, "foreach": "@variables('Rows')", "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                          "actions": row}
    g["If_ok"] = {"type": "If", "runAfter": S("Pre_code"), "expression": {"equals": ["@outputs('Pre_code')", "OK"]}, "actions": reads, "else": {"actions": {}}}
    g["Final_code"] = c("@if(not(equals(outputs('Pre_code'), 'OK')), outputs('Pre_code'), if(not(%s), 'ERROR', if(empty(%s), 'VALIDATION_LOOKUP', "
                        "if(not(and(%s, %s, %s)), 'ERROR', if(equals(variables('Approved'), length(variables('Rows'))), 'OK', if(greater(variables('Approved'), 0), 'PARTIAL', 'REFUSED'))))))"
                        % (_okd("Get_me"), MYD, _okd("Load"), _okd("Per_project"), _okd("Rows_loop")), {"If_ok": ANY})
    fin_ok = "or(equals(outputs('Final_code'), 'OK'), equals(outputs('Final_code'), 'PARTIAL'))"
    g["Audit_status"] = c("@if(variables('Degraded'), 'AUDIT_DEGRADED', if(greater(variables('Approved'), 0), 'OK', %s))" % EMPTY, S("Final_code"))
    body = {"ok": "@{if(%s, 'true', 'false')}" % fin_ok, "resultcode": "@{outputs('Final_code')}", "messagecode": "@{concat('MSG_', outputs('Final_code'))}",
            "correlationid": "@{workflow()?['run']?['name']}", "approvedcount": "@{string(variables('Approved'))}",
            "results": "@{string(if(or(%s, equals(outputs('Final_code'), 'REFUSED')), variables('Results'), json('[]')))}" % fin_ok,
            "auditstatus": "@{outputs('Audit_status')}"}
    g["Respond"] = bf._respond(body, "Audit_status")
    g["If_audit_degraded"] = {"type": "If", "runAfter": S("Respond"), "expression": {"equals": ["@outputs('Audit_status')", "AUDIT_DEGRADED"]},
                              "actions": {"Alert_audit_degraded": {"type": "Terminate", "runAfter": {}, "inputs": {"runStatus": "Failed", "runError": {
                                  "code": "AUDIT_DEGRADED", "message": "@{concat('audit append failed; correlation ', workflow()?['run']?['name'])}"}}}}, "else": {"actions": {}}}
    bf._error_response(g, {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}",
                           "approvedcount": "0", "results": "[]", "auditstatus": ""})
    return baf.bind_connection_references(base._fix(g), refs)
