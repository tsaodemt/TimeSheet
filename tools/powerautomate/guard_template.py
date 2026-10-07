"""Reusable authorization guard for Power Automate flows (standard connectors only).

Every guarded flow embeds the actions returned by `guard_actions()` in a scope named `Guard` and acts only on
`outputs('Guard_result')?['AuthorizationDecision']`. The logic exists once, here; flows never re-implement it.
It is inlined rather than called as a child flow because the trusted identity is the INVOKER's own
Office 365 Users connection, which a child flow cannot use.

Decision chain (same as tools/identity/guard.py, verified case-by-case by tools/identity/test_guard.py):
  MyProfile_V2 (invoker connection) -> normalised UPN, allowed domain
  -> employee list by AccountUpn (indexed, unique; $top=2 detects duplicates) -> active?
  -> live membership of every configured role group (service Groups connection)
  -> class table from ScopeConfig.json -> effective scope = most permissive across roles
  -> requested scope (self | employee:<code> | discipline:<code> | company) checked against list data
  -> Guard_result + audit row.
Pending decisions, temporary roles and unknown scope values never grant (fail closed).
Request fields that claim identity, role, scope or reviewer status are logged by name only.
"""
from __future__ import annotations

import build_read_flow as base

c, op, sp_http, S, EMPTY = base.c, base.op, base.sp_http, base.S, base.EMPTY
USERS, GROUPS = base.USERS, base.GROUPS
VALID = ("self", "discipline", "company")
KINDS = ("self", "employee", "discipline", "company")
o = lambda n: "outputs('%s')" % n
Q = "decodeUriComponent('%27')"
def esc(x):
    """OData string-literal escaping (' -> '') without a '' literal, which the classic designer drops."""
    return "replace(%s, %s, concat(%s, %s))" % (x, Q, Q, Q)


def nz(x):
    """string(x), or empty string for null. empty() rejects numbers in Power Automate, so test for null.
    string() is applied outside the if(): both branches are plain values, so the result does not depend on whether the
    runtime evaluates the unused branch (lazy_if_audit.py)."""
    return "string(if(equals(%s, null), %s, %s))" % (x, EMPTY, x)


def class_table(scope_config: dict, temporary_roles=("MIGO",)) -> dict:
    """role -> action -> self|discipline|company|pending|temp|unknown (entries that grant nothing are omitted)."""
    pending = {(p["role"], p["capability"]) for p in scope_config.get("pending", ())}
    out = {}
    for role, acts in scope_config["scopes"].items():
        for a, v in acts.items():
            if (role, a) in pending:
                k = "pending"
            elif v in VALID:
                k = v
            elif v in (None, "none"):
                continue
            else:
                k = "temp" if role in temporary_roles else "unknown"
            out.setdefault(role, {})[a] = k
    for role, a in pending:
        out.setdefault(role, {})[a] = "pending"
    return out


def action_map(scope_config: dict) -> dict:
    names = {a for acts in scope_config["scopes"].values() for a in acts}
    names |= {p["capability"] for p in scope_config.get("pending", ())}
    return {a.lower(): a for a in sorted(names)}


FIELDS = ("Id", "LegacyId", "IsActive", "DisciplineCode", "AccountUpn")


def caller_actions(*, site: str, emp_list: str, fields=FIELDS) -> dict:
    """Trusted caller (invoker's own Users connection) -> employee rows by AccountUpn ($top=2)."""
    sel, f_upn, T = ",".join(fields), fields[4], o("Trusted")
    return {
        "SiteUrl": c(site, {}),
        "Get_caller_profile": op(USERS, "MyProfile_V2", {"$select": "userPrincipalName,id"}, S("SiteUrl")),
        "Trusted": c("@toLower(trim(%s))" % nz("body('Get_caller_profile')?['userPrincipalName']"), S("Get_caller_profile")),
        "Caller_lookup": sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=%s&$filter=%s eq '@{%s}'&$top=2"
                                 % (emp_list, sel, f_upn, esc(T)), S("Trusted")),
        "Caller_rows": {"type": "Query", "runAfter": {"Caller_lookup": ["Succeeded", "Failed"]},
                        "inputs": {"from": "@if(equals(actions('Caller_lookup')?['status'], 'Succeeded'), body('Caller_lookup')?['value'], createArray())",
                                   "where": "@equals(toLower(trim(%s)), %s)" % (nz("item()?['%s']" % f_upn), T)}},
    }


def identity_code_actions(*, domain: str, after: str, fields=FIELDS) -> dict:
    """IdCode (OK or the identity deny code), Emp, CallerCode, CallerDisc."""
    f_id, f_code, f_active, f_disc, f_upn = fields
    T, rows = o("Trusted"), "body('Caller_rows')"
    g = {"IdCode": c("@if(or(empty(%(T)s), not(endsWith(%(T)s, '@%(D)s'))), 'INVALID_IDENTITY', "
                     "if(not(equals(actions('Caller_lookup')?['status'], 'Succeeded')), 'DIRECTORY_ERROR', "
                     "if(equals(length(%(R)s), 0), 'UNMAPPED_IDENTITY', "
                     "if(greater(length(%(R)s), 1), 'DUPLICATE_IDENTITY', "
                     "if(not(equals(first(%(R)s)?['%(A)s'], true)), 'INACTIVE_EMPLOYEE', 'OK')))))"
                     % dict(T=T, D=domain.lower(), R=rows, A=f_active), S(after))}
    ok = "equals(%s, 'OK')" % o("IdCode")
    g["Emp"] = c("@if(%s, first(%s), json('{}'))" % (ok, rows), S("IdCode"))
    g["CallerCode"] = c("@%s" % nz("outputs('Emp')?['%s']" % f_code), S("Emp"))
    g["CallerDisc"] = c("@%s" % nz("outputs('Emp')?['%s']" % f_disc), S("CallerCode"))
    return g


def guard_actions(scope_config: dict, role_groups, *, site: str, domain: str, emp_list: str, audit_list: str,
                  action_expr: str, kind_expr: str, ref_expr: str, untrusted_inputs=(),
                  fields=FIELDS, temporary_roles=("MIGO",)) -> dict:
    """Actions for the `Guard` scope. *_expr are expressions (without '@') yielding the request's raw
    action name, scope kind and scope reference. role_groups = [(roleKey, groupObjectId), ...] (configuration)."""
    f_id, f_code, f_active, f_disc, f_upn = fields
    sel = ",".join(fields)
    T = o("Trusted")
    g = caller_actions(site=site, emp_list=emp_list, fields=fields)
    prev = "Caller_rows"
    for key, gid in role_groups:
        g["List_" + key] = op(GROUPS, "ListGroupMembers", {"groupId": gid, "$top": 999}, S(prev))
        g["Filter_" + key] = {"type": "Query", "runAfter": S("List_" + key), "inputs": {
            "from": "@body('List_%s')?['value']" % key,
            "where": "@equals(toLower(%s), %s)" % (nz("item()?['userPrincipalName']"), T)}}
        g["M_" + key] = c("@greater(length(body('Filter_%s')), 0)" % key, S("Filter_" + key))
        prev = "M_" + key
    g.update(identity_code_actions(domain=domain, after=prev, fields=fields))
    ok = "equals(%s, 'OK')" % o("IdCode")
    g["ActionMap"] = c(action_map(scope_config), S("CallerDisc"))
    g["ClassTable"] = c(class_table(scope_config, temporary_roles), S("ActionMap"))
    g["ActionIn"] = c("@trim(%s)" % nz(action_expr), S("ClassTable"))
    g["Action"] = c("@%s" % nz("outputs('ActionMap')?[toLower(outputs('ActionIn'))]"), S("ActionIn"))
    g["Kind"] = c("@toLower(trim(%s))" % nz(kind_expr), S("Action"))
    g["Ref"] = c("@trim(%s)" % nz(ref_expr), S("Kind"))
    K, A, REF = o("Kind"), o("Action"), o("Ref")
    g["KindOk"] = c("@and(contains(createArray(%s), %s), or(not(or(equals(%s, 'employee'), equals(%s, 'discipline'))), not(empty(%s))))"
                    % (", ".join("'%s'" % k for k in KINDS), K, K, K, REF), S("Ref"))
    g["Target_lookup"] = sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=%s&$filter=%s eq '@{%s}'&$top=2"
                                 % (emp_list, sel, f_code, esc(REF)), S("KindOk"))
    g["Target_rows"] = c("@if(equals(actions('Target_lookup')?['status'], 'Succeeded'), body('Target_lookup')?['value'], createArray())",
                         {"Target_lookup": ["Succeeded", "Failed"]})
    keys = [k for k, _ in role_groups]
    cls = lambda k: "if(empty(outputs('ClassTable')?['%s']?[%s]), 'none', outputs('ClassTable')?['%s']?[%s])" % (k, A, k, A)
    rank = lambda k: ("if(outputs('M_%s'), if(equals(%s, 'company'), 3, if(equals(%s, 'discipline'), 2, if(equals(%s, 'self'), 1, 0))), 0)"
                      % (k, cls(k), cls(k), cls(k)))
    has = lambda kind: "@or(false, false, %s)" % ", ".join("and(outputs('M_%s'), equals(%s, '%s'))" % (k, cls(k), kind) for k in keys)
    g["Rank"] = c("@max(0, %s)" % ", ".join(rank(k) for k in keys), S("Target_rows"))
    g["HasPending"] = c(has("pending"), S("Rank"))
    g["HasTemp"] = c(has("temp"), S("HasPending"))
    g["HasUnknown"] = c(has("unknown"), S("HasTemp"))
    R, CD, TR = o("Rank"), o("CallerDisc"), o("Target_rows")
    tgt = "first(%s)" % TR
    in_scope = ("@or(equals({K}, 'self'), "
                "and(equals({K}, 'company'), equals({R}, 3)), "
                "and(equals({K}, 'discipline'), or(equals({R}, 3), and(equals({R}, 2), not(empty({CD})), equals({REF}, {CD})))), "
                "and(equals({K}, 'employee'), equals(length({TR}), 1), or(equals({R}, 3), "
                "and(equals({R}, 2), not(empty({CD})), equals({TD}, {CD})), "
                "and(equals({R}, 1), equals({TC}, outputs('CallerCode'))))))").format(
        K=K, R=R, CD=CD, REF=REF, TR=TR, TD=nz("%s?['%s']" % (tgt, f_disc)), TC=nz("%s?['%s']" % (tgt, f_code)))
    g["InScope"] = c(in_scope, S("HasUnknown"))
    g["ResultCode"] = c("@if(not(%(ok)s), outputs('IdCode'), if(empty(%(A)s), 'UNKNOWN_ACTION', if(not(outputs('KindOk')), 'UNKNOWN_SCOPE', "
                        "if(equals(%(R)s, 0), if(outputs('HasPending'), 'DECISION_PENDING', if(outputs('HasTemp'), 'TEMP_ROLE_INACTIVE', "
                        "if(outputs('HasUnknown'), 'UNKNOWN_SCOPE', 'ROLE_NOT_ALLOWED'))), "
                        "if(outputs('InScope'), 'ALLOW', 'SCOPE_NOT_ALLOWED')))))" % dict(ok=ok, A=A, R=R), S("InScope"))
    code = o("ResultCode")
    g["Roles"] = {"type": "Query", "runAfter": S("ResultCode"), "inputs": {
        "from": "@createArray(%s)" % ", ".join("if(and(%s, outputs('M_%s')), '%s', %s)" % (ok, k, k, EMPTY) for k in keys),
        "where": "@not(empty(item()))"}}
    resolved = ("@if(and(%s, not(empty(%s)), outputs('KindOk')), if(equals(%s, 3), 'company', if(equals(%s, 2), 'discipline', "
                "if(equals(%s, 1), 'self', 'none'))), 'none')" % (ok, A, R, R, R))
    g["ResolvedScope"] = c(resolved, S("Roles"))
    req_action = "if(empty(%s), outputs('ActionIn'), %s)" % (A, A)
    g["Guard_result"] = c({
        "AuthenticatedUpn": "@if(empty(%s), null, %s)" % (T, T),
        "EmployeeId": "@if(%s, outputs('Emp')?['%s'], null)" % (ok, f_id),
        "EmployeeCode": "@if(%s, outputs('CallerCode'), null)" % ok,
        "IsActive": "@if(%s, true, if(equals(outputs('IdCode'), 'INACTIVE_EMPLOYEE'), false, null))" % ok,
        "ResolvedRoles": "@body('Roles')",
        "RequestedAction": "@%s" % req_action,
        "RequestedScope": "@concat(%s, if(empty(%s), %s, concat(':', %s)))" % (K, REF, EMPTY, REF),
        "ResolvedScope": "@outputs('ResolvedScope')",
        "AuthorizationDecision": "@if(equals(%s, 'ALLOW'), 'ALLOW', 'DENY')" % code,
        "ResultCode": "@%s" % code,
        "CorrelationId": "@{workflow()?['run']?['name']}",
        "IgnoredInputs": sorted(untrusted_inputs),
    }, S("ResolvedScope"))
    gr = lambda k: "outputs('Guard_result')?['%s']" % k
    detail = ("concat('kind=guard;employeeId=', %s, ';employeeCode=', %s, ';isActive=', if(%s, 'true', if(equals(outputs('IdCode'), 'INACTIVE_EMPLOYEE'), 'false', %s)), "
              "';roles=', join(body('Roles'), ','), ';action=', %s, ';scope=', %s, ';resolvedScope=', %s, ';ignored=', join(%s, ','), ';', "
              "if(and(equals(%s, 'SCOPE_NOT_ALLOWED'), equals(%s, 'employee'), not(equals(length(%s), 1))), concat('target=', string(length(%s))), %s))"
              % (nz(gr("EmployeeId")), nz(gr("EmployeeCode")), ok, EMPTY, gr("RequestedAction"), gr("RequestedScope"),
                 gr("ResolvedScope"), gr("IgnoredInputs"), code, K, TR, TR, EMPTY))
    g["Audit_body"] = c({"Title": "@{concat('guard ', %s, ' ', %s)}" % (gr("RequestedAction"), code),
                         "Decision": "@{if(equals(%s, 'ALLOW'), 'ALLOWED', 'DENIED')}" % code,
                         "ResultCode": "@{%s}" % code,
                         "CallerUpnTrusted": "@{%s}" % T,
                         "CorrelationId": "@{workflow()?['run']?['name']}",
                         "Detail": "@{%s}" % detail}, S("Guard_result"))
    g["Write_audit"] = sp_http("POST", "_api/web/lists/getbytitle('%s')/items" % audit_list, S("Audit_body"),
                               "@{string(outputs('Audit_body'))}")
    return base._fix(g)
