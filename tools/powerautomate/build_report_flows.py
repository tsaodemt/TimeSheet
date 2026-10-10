"""R3 M4 current-scope report flows: RPT-ProjectReport, RPT-DisciplineReport (OD-50 in-app guarded reporting, aggregate-only).

Reference: tools/reporting/effort_report.py; contract: OpenSpec change `r3-planning-effort-hour-registration` (design §11.1,
effort-reporting-contract, planning-security; M4 decisions 2026-10-10). Reuses the proven pieces: trusted caller + guard with the
project-PM grant (build_effort_flows._guard_pm), the mandatory Authorization row with the FINAL decision before any business read,
ReadProxy audit, coded DIRECTORY_ERROR / INTERNAL_ERROR responses, settings validation (CONFIG_INVALID).

Query strategy: master / plan lists are read once (one page of 5,000; a next page fails closed); Approved TimesheetEntries are read per
authorized project in a parallel loop (one page of 5,000 per project, fail closed beyond). Sums use the WDL xpath sum over a JSON
array (no shared variable inside a parallel loop); all arithmetic is in integer hundredths, man-days = hours ÷ HoursPerManDay.
Only aggregates leave the flow: no TimesheetEntries / registration / allocation row, no employee, owner, salary, rate or cost field.
"""
from __future__ import annotations

import os
import sys

import audit_template as at
import build_appstart_flow as baf
import build_approval_flows as bf
import build_discipline_flows as bdf
import build_effort_flows as bef
import build_r1_flows as r1
import build_read_flow as base

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reporting"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effort"))
import effort_report as er  # noqa: E402
import pe_schema as ps  # noqa: E402
import rpt_rules as rr  # noqa: E402

c, S, EMPTY, o, nz = r1.c, r1.S, r1.EMPTY, r1.o, r1.nz
_sp, _ab, _okd, _rows = r1._sp, r1._ab, r1._okd, r1._rows
_rq, _init = bef._rq, bef._init
cents, md = bdf.cents, bdf.md
ANY = ["Succeeded", "Failed", "TimedOut"]
B = lambda k: "outputs('Guard_base')?['%s']" % k  # noqa: E731
LOOP = bef.LOOP_CONCURRENCY
HPM = bef.HPM


def xsum(arr):
    """Σ of a JSON array of numbers without a variable (WDL xpath sum) -> integer."""
    return "int(string(xpath(xml(json(concat('{\"r\":{\"v\":', string(%s), '}}'))), 'sum(/r/v)')))" % arr


def _one_page(name):
    """the read succeeded and returned no next page (a next page fails closed)."""
    return "and(%s, empty(%s))" % (_okd(name), nz("%s?['odata.nextLink']" % _ab(name)))


def _pms(after):
    return {"Get_pms": _sp(S(after), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,ProjectItemId,PmEmployeeItemId&$filter=PmEmployeeItemId eq @{%s}"
                           "&$top=5000" % (ps.PM_LIST, bef._caller_emp()))}


def _decide(cap):
    def decide(g):
        R = B("ResolvedRoles")
        has = lambda *rs: "or(false, %s)" % ", ".join("contains(%s, '%s')" % (R, r) for r in rs)  # noqa: E731
        bc = B("ResultCode")
        allow = "equals(%s, 'ALLOW')" % bc
        g["Pm_ids"] = {"type": "Select", "runAfter": {"Get_pms": ["Succeeded", "Failed"]}, "inputs": {
            "from": "@if(%s, %s, createArray())" % (_okd("Get_pms"), _rows("Get_pms")), "select": "@%s" % _rq("item()?['ProjectItemId']")}}
        g["Company"] = c("@and(%s, %s)" % (allow, has(*rr.COMPANY_ROLES)), S("Pm_ids"))
        g["Disc"] = c("@and(%s, %s)" % (allow, has("TL") if cap == rr.DISCIPLINE else "false"), S("Company"))
        err = "and(%s, not(%s))" % (bef._identity_ok(), _okd("Get_pms"))
        has_pm = "and(%s, greater(length(body('Pm_ids')), 0))" % bef._identity_ok()
        g["Final_scope"] = c("@if(%s, 'none', if(outputs('Company'), 'company', if(and(outputs('Disc'), %s), 'discipline+%s', if(outputs('Disc'), 'discipline', "
                             "if(%s, '%s', 'none')))))" % (err, has_pm, rr.PM_SCOPE, has_pm, rr.PM_SCOPE), S("Disc"))
        g["Final_authz"] = c("@if(%s, 'ERROR', if(not(equals(outputs('Final_scope'), 'none')), 'ALLOW', if(%s, 'ROLE_NOT_ALLOWED', %s)))"
                             % (err, allow, bc), S("Final_scope"))
        return "Final_authz"
    return decide


def _reads(det, after, *, m1):
    det.update(bef._settings_reads(after))
    det["Get_projects"] = _sp(S("Get_settings"), "GET", "_api/web/lists/getbytitle('Projects')/items?$select=Id,LegacyId,ProjectCode,Title&$orderby=Id asc&$top=5000")
    last = "Get_projects"
    if m1:
        det["Get_allocs"] = _sp(S(last), "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,ProjectItemId,Effort&$top=5000" % ps.ALLOC_LIST)
        det["Show_m1"] = c("@or(false, %s)" % ", ".join("contains(%s, '%s')" % (B("ResolvedRoles"), r) for r in rr.REG_VIEW_ROLES), S("Get_allocs"))
        det["If_m1"] = {"type": "If", "runAfter": S("Show_m1"), "expression": {"equals": ["@outputs('Show_m1')", True]}, "actions": {
            "Get_m1": _sp({}, "GET", "_api/web/lists/getbytitle('HourRegistrations')/items?$select=Id,ProjectItemId,ManDays&$top=5000")}, "else": {"actions": {}}}
        last = "If_m1"
    return bef._settings_actions(det, last)


def _actual_loop(det, after, *, per_discipline):
    """Facts += {pid, d, c} (per discipline) or {pid, c} (project), or {pid, err: true} when the page failed / overflowed."""
    X = "items('Proj_loop')"
    pid = _rq("%s?['Id']" % X)
    inner = {"Get_ts": _sp({}, "GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,Hours,DisciplineCode&$filter=ProjectId eq @{%s} and "
                           "EntryStatus eq 'Approved'&$orderby=Id asc&$top=%d" % (bef.ENTRIES, pid, er.PAGE))}
    inner["Ts_c"] = {"type": "Select", "runAfter": {"Get_ts": ANY}, "inputs": {"from": "@if(%s, %s, createArray())" % (_okd("Get_ts"), _rows("Get_ts")),
                     "select": {"d": "@%s" % nz("item()?['DisciplineCode']"),
                                "c": "@%s" % cents("string(if(equals(item()?['Hours'], null), 0, item()?['Hours']))")}}}
    ok = _one_page("Get_ts")
    if per_discipline:
        inner["Ts_d"] = {"type": "Select", "runAfter": S("Ts_c"), "inputs": {"from": "@body('Ts_c')", "select": "@item()?['d']"}}
        inner["If_ts_ok"] = {"type": "If", "runAfter": S("Ts_d"), "expression": {"equals": ["@" + ok, True]}, "actions": {
            "D_loop": {"type": "Foreach", "runAfter": {}, "foreach": "@union(body('Ts_d'), body('Ts_d'))", "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                       "actions": {
                           "Ts_of_d": {"type": "Query", "runAfter": {}, "inputs": {"from": "@body('Ts_c')", "where": "@equals(item()?['d'], items('D_loop'))"}},
                           "C_of_d": {"type": "Select", "runAfter": S("Ts_of_d"), "inputs": {"from": "@body('Ts_of_d')", "select": "@item()?['c']"}},
                           "Add_fact": {"type": "AppendToArrayVariable", "runAfter": S("C_of_d"), "inputs": {"name": "Facts", "value": {
                               "pid": "@%s" % pid, "d": "@{items('D_loop')}", "c": "@" + xsum("body('C_of_d')"), "err": False}}}}}},
            "else": {"actions": {"Add_err": {"type": "AppendToArrayVariable", "runAfter": {}, "inputs": {"name": "Facts", "value": {"pid": "@%s" % pid, "err": True}}}}}}
    else:
        inner["C_all"] = {"type": "Select", "runAfter": S("Ts_c"), "inputs": {"from": "@body('Ts_c')", "select": "@item()?['c']"}}
        inner["Add_fact"] = {"type": "AppendToArrayVariable", "runAfter": S("C_all"), "inputs": {"name": "Facts", "value": {
            "pid": "@%s" % pid, "d": "", "c": "@if(%s, %s, 0)" % (ok, xsum("body('C_all')")), "err": "@not(%s)" % ok}}}
    det["Proj_loop"] = {"type": "Foreach", "runAfter": S(after), "foreach": "@body('Visible')", "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                        "actions": inner}
    det["Fact_err"] = {"type": "Query", "runAfter": S("Proj_loop"), "inputs": {"from": "@variables('Facts')", "where": "@equals(item()?['err'], true)"}}
    return "Fact_err"


def _respond(g, ok, extra, source_flow, action, kw, after):
    g.update(at.operation_event_actions("ReadProxy", action, target_entity="Report", audit_list=kw["audit_list"], conf_audit_list=kw["conf_audit_list"],
                                        environment=kw["environment"], source_flow=source_flow, target_id_expr=EMPTY,
                                        outcome_code_expr="if(%s, 'ALLOW', outputs('Final_code'))" % ok, after=after, name="Read_audit"))
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{outputs('Final_code')}", "messagecode": "@{concat('MSG_', outputs('Final_code'))}",
            "correlationid": "@{workflow()?['run']?['name']}", "scope": "@{if(%s, outputs('Final_scope'), 'none')}" % ok,
            "hourspermanday": "@{if(%s, string(%s), '')}" % (ok, HPM)}
    body.update(extra)
    g["Respond"] = bf._respond(body, "Write_Read_audit")
    err = {"ok": "false", "resultcode": "", "messagecode": "MSG_TEMPORARY_PROBLEM", "correlationid": "@{workflow()?['run']?['name']}", "scope": "none",
           "hourspermanday": ""}
    err.update({k: ("[]" if k == "rows" else "{}" if k == "totals" else "false") for k in extra})
    bf._error_response(g, err)


def _final_code(g, reads):
    ok_reads = "and(%s)" % ", ".join(reads)
    g["Final_code"] = c("@if(not(equals(outputs('Pre'), 'OK')), outputs('Pre'), if(not(%s), 'ERROR', "
                        "if(not(and(equals(actions('HpmOk')?['outputs'], true), equals(actions('CodesOk')?['outputs'], true))), 'CONFIG_INVALID', "
                        "if(greater(length(if(equals(actions('Fact_err')?['outputs']?['body'], null), createArray(), actions('Fact_err')?['outputs']?['body'])), 0), 'ERROR', 'OK'))))" % ok_reads, {"If_ok": ANY})
    return "equals(outputs('Final_code'), 'OK')"


def _common(g):
    g["Pre"] = c("@if(equals(outputs('Final_authz'), 'ALLOW'), 'OK', outputs('Final_authz'))", S("Write_Authz_audit"))


# ---------------------------------------------------------------- RPT-ProjectReport

def project_report_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                           source_flow="RPT-ProjectReport", refs=None) -> dict:
    """Trigger: text ClientRequestId (correlation only), text_1..7 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = bef._guard_pm(rr.PROJECT, er.DECOYS, source_flow, _decide(rr.PROJECT), _pms, scope_config=rr.scope_config(), **kw)
    for v in ("Facts", "Rows"):
        g["Init_" + v] = _init(v, "array", "@json('[]')")
    _common(g)
    det = {}
    last = _reads(det, None, m1=True)
    det["Get_settings"]["runAfter"] = {}
    det["Visible"] = {"type": "Query", "runAfter": S(last), "inputs": {"from": "@%s" % _rows("Get_projects"),
                      "where": "@or(outputs('Company'), contains(body('Pm_ids'), %s))" % _rq("item()?['Id']")}}
    last = _actual_loop(det, "Visible", per_discipline=False)
    X = "items('Row_loop')"
    pid = _rq("%s?['Id']" % X)
    m1rows = "if(equals(actions('Show_m1')?['outputs'], true), if(%s, %s, createArray()), createArray())" % (_okd("Get_m1"), _rows("Get_m1"))
    row = {
        "A_p": {"type": "Query", "runAfter": {}, "inputs": {"from": "@%s" % _rows("Get_allocs"),
                "where": "@and(equals(%s, %s), not(equals(item()?['Effort'], null)))" % (_rq("item()?['ProjectItemId']"), pid)}},
        "A_c": {"type": "Select", "runAfter": S("A_p"), "inputs": {"from": "@body('A_p')", "select": "@%s" % cents("string(item()?['Effort'])")}},
        "M_p": {"type": "Query", "runAfter": S("A_c"), "inputs": {"from": "@%s" % m1rows,
                "where": "@and(equals(%s, %s), not(equals(item()?['ManDays'], null)))" % (_rq("item()?['ProjectItemId']"), pid)}},
        "M_c": {"type": "Select", "runAfter": S("M_p"), "inputs": {"from": "@body('M_p')", "select": "@%s" % cents("string(item()?['ManDays'])")}},
        "F_p": {"type": "Query", "runAfter": S("M_c"), "inputs": {"from": "@variables('Facts')", "where": "@equals(item()?['pid'], %s)" % pid}},
        "Add_row": {"type": "AppendToArrayVariable", "runAfter": S("F_p"), "inputs": {"name": "Rows", "value": {
            "projectId": "@%s" % pid, "code": "@{%s}" % nz("%s?['ProjectCode']" % X), "name": "@{%s}" % nz("%s?['Title']" % X),
            "hasPlan": "@greater(length(body('A_p')), 0)", "pc": "@" + xsum("body('A_c')"),
            "hasM1": "@greater(length(body('M_p')), 0)", "mc": "@" + xsum("body('M_c')"),
            "hc": "@if(greater(length(body('F_p')), 0), first(body('F_p'))?['c'], 0)"}}}}
    det["Row_loop"] = {"type": "Foreach", "runAfter": S(last), "foreach": "@body('Visible')", "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                       "actions": row}
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@outputs('Pre')", "OK"]}, "actions": det, "else": {"actions": {}}}
    ok = _final_code(g, [_one_page("Get_settings"), _one_page("Get_projects"), _one_page("Get_allocs"),
                         "or(not(equals(actions('Show_m1')?['outputs'], true)), %s)" % _one_page("Get_m1"), _okd("Proj_loop"), _okd("Row_loop")])
    Z = "item()"
    h100 = "mul(%s, 100)" % HPM
    out_sel = {
        "projectId": "@%s?['projectId']" % Z, "code": "@%s?['code']" % Z, "name": "@%s?['name']" % Z,
        "planState": "@{if(%s?['hasPlan'], 'VALUE', 'BLANK')}" % Z,
        "planned": "@{if(%s?['hasPlan'], %s, '')}" % (Z, md("int(%s?['pc'])" % Z)),
        "actualHours": "@{%s}" % md("int(%s?['hc'])" % Z),
        "actualManDays": "@{string(div(float(%s?['hc']), %s))}" % (Z, h100),
        "variance": "@{if(%s?['hasPlan'], string(div(sub(mul(float(%s?['pc']), %s), float(%s?['hc'])), %s)), '')}" % (Z, Z, HPM, Z, h100),
        "registered": "@{if(and(equals(actions('Show_m1')?['outputs'], true), %s?['hasM1']), %s, '')}" % (Z, md("int(%s?['mc'])" % Z))}
    g["Rows_out"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {"from": "@if(%s, variables('Rows'), createArray())" % ok, "select": out_sel}}
    # totals over the rows (hundredths)
    for k, flag in (("pc", "hasPlan"), ("hc", None), ("mc", "hasM1")):
        g["T_q_" + k] = {"type": "Query", "runAfter": S("Rows_out" if k == "pc" else "T_" + {"hc": "pc", "mc": "hc"}[k]), "inputs": {
            "from": "@if(%s, variables('Rows'), createArray())" % ok, "where": "@%s" % ("equals(item()?['%s'], true)" % flag if flag else "true")}}
        g["T_s_" + k] = {"type": "Select", "runAfter": S("T_q_" + k), "inputs": {"from": "@body('T_q_%s')" % k, "select": "@item()?['%s']" % k}}
        g["T_" + k] = c("@" + xsum("body('T_s_%s')" % k), S("T_s_" + k))
    has_tp = "greater(length(body('T_q_pc')), 0)"
    has_tm = "and(equals(actions('Show_m1')?['outputs'], true), greater(length(body('T_q_mc')), 0))"
    g["Totals"] = c({"planned": "@{if(%s, %s, '')}" % (has_tp, md("outputs('T_pc')")), "actualHours": "@{%s}" % md("outputs('T_hc')"),
                     "actualManDays": "@{if(%s, string(div(float(outputs('T_hc')), %s)), '')}" % (ok, h100),
                     "variance": "@{if(and(%s, %s), string(div(sub(mul(float(outputs('T_pc')), %s), float(outputs('T_hc'))), %s)), '')}" % (ok, has_tp, HPM, h100),
                     "registered": "@{if(%s, %s, '')}" % (has_tm, md("outputs('T_mc')"))}, S("T_mc"))
    _respond(g, ok, {"rows": "@{string(body('Rows_out'))}", "totals": "@{if(%s, string(outputs('Totals')), '{}')}" % ok,
                     "showregistered": "@{if(and(%s, equals(actions('Show_m1')?['outputs'], true)), 'true', 'false')}" % ok},
             source_flow, "ProjectReport", dict(kw, conf_audit_list=conf_audit_list), "Totals")
    return baf.bind_connection_references(base._fix(g), refs)


# ---------------------------------------------------------------- RPT-DisciplineReport

def discipline_report_actions(*, role_groups, site, domain, emp_list, audit_list, conf_audit_list, environment,
                              source_flow="RPT-DisciplineReport", refs=None) -> dict:
    """Trigger: text ClientRequestId (correlation only), text_1..7 decoys."""
    kw = dict(role_groups=role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment)
    g = bef._guard_pm(rr.DISCIPLINE, er.DECOYS, source_flow, _decide(rr.DISCIPLINE), _pms, scope_config=rr.scope_config(), **kw)
    for v in ("Facts", "Rows"):
        g["Init_" + v] = _init(v, "array", "@json('[]')")
    _common(g)
    det = {"Get_me": bdf._me(emp_list, None, bef._caller_emp())}
    last = _reads(det, "Get_me", m1=False)
    det["Get_regs"] = _sp(S(last), "GET", "_api/web/lists/getbytitle('DisciplineEffortRegistrations')/items?$select=Id,ProjectItemId,DisciplineCode,Effort,Status&$top=5000")
    det["Get_discs"] = _sp(S("Get_regs"), "GET", "_api/web/lists/getbytitle('Disciplines')/items?$select=Id,DisciplineCode,Title&$top=500")
    mydisc = nz("%s?['Discipline']?['DisciplineCode']" % _ab("Get_me"))
    det["My_disc"] = c("@" + mydisc, S("Get_discs"))
    det["Approved"] = {"type": "Query", "runAfter": S("My_disc"), "inputs": {"from": "@%s" % _rows("Get_regs"),
                       "where": "@and(equals(item()?['Status'], 'ApprovedLocked'), not(equals(item()?['Effort'], null)))"}}
    det["Visible"] = {"type": "Query", "runAfter": S("Approved"), "inputs": {"from": "@%s" % _rows("Get_projects"),
                      "where": "@or(outputs('Company'), contains(body('Pm_ids'), %s), and(outputs('Disc'), not(empty(outputs('My_disc')))))" % _rq("item()?['Id']")}}
    last = _actual_loop(det, "Visible", per_discipline=True)
    X = "items('Row_loop')"
    pid = _rq("%s?['Id']" % X)
    Y = "items('Code_loop')"
    full = "or(outputs('Company'), contains(body('Pm_ids'), %s))" % pid
    code_actions = {
        "R_d": {"type": "Query", "runAfter": {}, "inputs": {"from": "@body('R_p')", "where": "@equals(item()?['DisciplineCode'], %s)" % Y}},
        "R_c": {"type": "Select", "runAfter": S("R_d"), "inputs": {"from": "@body('R_d')", "select": "@%s" % cents("string(item()?['Effort'])")}},
        "F_d": {"type": "Query", "runAfter": S("R_c"), "inputs": {"from": "@body('F_p')", "where": "@equals(item()?['d'], %s)" % Y}},
        "N_d": {"type": "Query", "runAfter": S("F_d"), "inputs": {"from": "@%s" % _rows("Get_discs"), "where": "@equals(item()?['DisciplineCode'], %s)" % Y}},
        "Add_row": {"type": "AppendToArrayVariable", "runAfter": S("N_d"), "inputs": {"name": "Rows", "value": {
            "projectId": "@%s" % pid, "code": "@{%s}" % nz("%s?['ProjectCode']" % X), "name": "@{%s}" % nz("%s?['Title']" % X),
            "disciplineCode": "@{%s}" % Y, "disciplineName": "@{%s}" % nz("first(body('N_d'))?['Title']"),
            "hasPlan": "@greater(length(body('R_d')), 0)", "pc": "@" + xsum("body('R_c')"),
            "hc": "@if(greater(length(body('F_d')), 0), first(body('F_d'))?['c'], 0)"}}}}
    row = {
        "R_p": {"type": "Query", "runAfter": {}, "inputs": {"from": "@body('Approved')", "where": "@equals(%s, %s)" % (_rq("item()?['ProjectItemId']"), pid)}},
        "F_p": {"type": "Query", "runAfter": S("R_p"), "inputs": {"from": "@variables('Facts')", "where": "@and(equals(item()?['pid'], %s), not(empty(%s)))"
                                                                    % (pid, nz("item()?['d']"))}},
        "R_codes": {"type": "Select", "runAfter": S("F_p"), "inputs": {"from": "@body('R_p')", "select": "@item()?['DisciplineCode']"}},
        "F_codes": {"type": "Select", "runAfter": S("R_codes"), "inputs": {"from": "@body('F_p')", "select": "@item()?['d']"}},
        "Codes_vis": {"type": "Query", "runAfter": S("F_codes"), "inputs": {"from": "@union(body('R_codes'), body('F_codes'))",
                      "where": "@or(%s, equals(item(), outputs('My_disc')))" % full}},
        "Code_loop": {"type": "Foreach", "runAfter": S("Codes_vis"), "foreach": "@body('Codes_vis')", "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                      "actions": code_actions}}
    det["Row_loop"] = {"type": "Foreach", "runAfter": S(last), "foreach": "@body('Visible')", "runtimeConfiguration": {"concurrency": {"repetitions": LOOP}},
                       "actions": row}
    g["If_ok"] = {"type": "If", "runAfter": S("Pre"), "expression": {"equals": ["@outputs('Pre')", "OK"]}, "actions": det, "else": {"actions": {}}}
    ok = _final_code(g, [_okd("Get_me"), _one_page("Get_settings"), _one_page("Get_projects"), _one_page("Get_regs"), _one_page("Get_discs"),
                         _okd("Proj_loop"), _okd("Row_loop")])
    Z = "item()"
    h100 = "mul(%s, 100)" % HPM
    out_sel = {
        "projectId": "@%s?['projectId']" % Z, "code": "@%s?['code']" % Z, "name": "@%s?['name']" % Z,
        "disciplineCode": "@%s?['disciplineCode']" % Z, "disciplineName": "@%s?['disciplineName']" % Z,
        "planState": "@{if(%s?['hasPlan'], 'VALUE', 'BLANK')}" % Z,
        "planned": "@{if(%s?['hasPlan'], %s, '')}" % (Z, md("int(%s?['pc'])" % Z)),
        "actualHours": "@{%s}" % md("int(%s?['hc'])" % Z),
        "actualManDays": "@{string(div(float(%s?['hc']), %s))}" % (Z, h100),
        "variance": "@{if(%s?['hasPlan'], string(div(sub(mul(float(%s?['pc']), %s), float(%s?['hc'])), %s)), '')}" % (Z, Z, HPM, Z, h100)}
    g["Rows_out"] = {"type": "Select", "runAfter": S("Final_code"), "inputs": {"from": "@if(%s, variables('Rows'), createArray())" % ok, "select": out_sel}}
    _respond(g, ok, {"rows": "@{string(body('Rows_out'))}"}, source_flow, "DisciplineReport", dict(kw, conf_audit_list=conf_audit_list), "Rows_out")
    return baf.bind_connection_references(base._fix(g), refs)
