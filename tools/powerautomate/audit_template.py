"""Audit event actions for Power Automate flows (same row as tools/audit/audit_event.py, verified by test_audit.py).

- app_open_actions(): the AppOpen flow the app shell calls once per session. Reuses the guard's identity actions
  (trusted caller -> employee -> IdCode); writes one row (AppOpen/ALLOW/OK or IdentityRejected/DENY/<code>) and
  returns the result to Power Apps. No role lookup: AppOpen grants nothing.
- authorization_event_actions(): the guard decision as an audit row, appended after the `Guard` scope actions.
- operation_event_actions(): a business operation after the guard. Change fields are server-side expressions
  chosen at generation time; secret and (for the operational log) confidential names are removed here, so no
  sanitising is needed at run time.
"""
from __future__ import annotations

import os
import sys

import build_read_flow as base
import guard_template as gt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audit"))
import audit_event as ae  # noqa: E402

c, sp_http, S, EMPTY, nz = base.c, base.sp_http, base.S, base.EMPTY, gt.nz
o = lambda n: "outputs('%s')" % n


def _lit(s):
    return "'%s'" % str(s).replace("'", "''")


def _arr(names):
    return "createArray(%s)" % ", ".join(_lit(n) for n in names) if names else "createArray()"


def _detail(ignored, omitted, client_expr):
    return ("concat('ignored=', join(%s, ','), ';omitted=', join(%s, ','), ';client=', %s)"
            % (_arr(sorted(ignored)), _arr(sorted(omitted)), client_expr))


def _write(audit_list, name):
    return sp_http("POST", "_api/web/lists/getbytitle('%s')/items" % audit_list, S(name), "@{string(outputs('%s'))}" % name)


def app_open_actions(*, site: str, domain: str, emp_list: str, audit_list: str, environment: str,
                     client_type_expr: str, untrusted_inputs=(), source_flow: str = "TS-AppOpen",
                     fields=gt.FIELDS, name: str = "Audit_event") -> dict:
    g = gt.caller_actions(site=site, emp_list=emp_list, fields=fields)
    g.update(gt.identity_code_actions(domain=domain, after="Caller_rows", fields=fields))
    ok = "equals(outputs('IdCode'), 'OK')"
    g["ClientType"] = c("@if(greater(length(%s), 40), substring(%s, 0, 40), %s)" % ((nz(client_type_expr),) * 3), S("CallerDisc"))
    code = "if(%s, 'OK', outputs('IdCode'))" % ok
    g[name] = c({
        "Title": "@{concat(if(%s, 'AppOpen', 'IdentityRejected'), ' AppOpen ', %s)}" % (ok, code),
        "EventType": "@{if(%s, 'AppOpen', 'IdentityRejected')}" % ok,
        "Action": "AppOpen", "ActionText": "", "Decision": "@{if(%s, 'ALLOW', 'DENY')}" % ok,
        "ResultCode": "@{%s}" % code, "OccurredOn": "@{utcNow('yyyy-MM-ddTHH:mm:ssZ')}",
        "CorrelationId": "@{workflow()?['run']?['name']}", "ActorUpn": "@{outputs('Trusted')}",
        "ActorEmployeeItemId": "@if(%s, outputs('Emp')?['%s'], null)" % (ok, fields[0]),
        "TargetList": "", "TargetItemId": "", "TargetLegacyId": "", "OwnerEmployeeItemId": None, "IsOnBehalf": None,
        "WorkDate": "", "ScopeKind": "", "ScopeRef": "", "SourceFlow": source_flow, "Environment": environment,
        "ChangeJson": "", "Detail": "@{%s}" % _detail(untrusted_inputs, (), "outputs('ClientType')"),
    }, S("ClientType"))
    g["Write_" + name] = _write(audit_list, name)
    g["Respond"] = {"type": "Response", "kind": "PowerApp", "runAfter": S("Write_" + name),
                    "inputs": {"statusCode": 200,
                               "body": {"resultcode": "@{%s}" % code, "employeecode": "@{outputs('CallerCode')}",
                                        "correlationid": "@{workflow()?['run']?['name']}"},
                               "schema": {"type": "object", "properties": {k: {"title": k, "x-ms-dynamically-added": True, "type": "string"}
                                                                            for k in ["resultcode", "employeecode", "correlationid"]}}}}
    return base._fix(g)


def _guard_fields():
    gr = lambda k: "outputs('Guard_result')?['%s']" % k
    rs = gr("RequestedScope")
    kind = "first(split(%s, ':'))" % rs
    ref = "if(contains(%s, ':'), substring(%s, add(indexOf(%s, ':'), 1)), %s)" % (rs, rs, rs, EMPTY)
    return gr, kind, ref


def authorization_event_actions(*, audit_list: str, environment: str, source_flow: str, after: str = "Guard_result",
                                name: str = "Audit_event") -> dict:
    gr, kind, ref = _guard_fields()
    allow = "equals(%s, 'ALLOW')" % gr("ResultCode")
    g = {name: c({
        "Title": "@{concat(if(%s, 'AuthorizationAllow', 'AuthorizationDeny'), ' ', %s, ' ', %s)}" % (allow, gr("RequestedAction"), gr("ResultCode")),
        "EventType": "@{if(%s, 'AuthorizationAllow', 'AuthorizationDeny')}" % allow,
        "Action": "@{%s}" % gr("RequestedAction"), "ActionText": "", "Decision": "@{%s}" % gr("AuthorizationDecision"),
        "ResultCode": "@{%s}" % gr("ResultCode"), "OccurredOn": "@{utcNow('yyyy-MM-ddTHH:mm:ssZ')}",
        "CorrelationId": "@{%s}" % gr("CorrelationId"), "ActorUpn": "@{%s}" % nz(gr("AuthenticatedUpn")),
        "ActorEmployeeItemId": "@%s" % gr("EmployeeId"), "TargetList": "", "TargetItemId": "", "TargetLegacyId": "",
        "OwnerEmployeeItemId": None, "IsOnBehalf": None, "WorkDate": "",
        "ScopeKind": "@{%s}" % kind, "ScopeRef": "@{%s}" % ref, "SourceFlow": source_flow, "Environment": environment,
        "ChangeJson": "", "Detail": "@{concat('ignored=', join(%s, ','), ';omitted=;client=')}" % gr("IgnoredInputs"),
    }, S(after))}
    g["Write_" + name] = _write(audit_list, name)
    return base._fix(g)


def operation_event_actions(event_type: str, action: str, *, target_entity: str, audit_list: str, conf_audit_list: str,
                            environment: str, source_flow: str, target_id_expr: str = "", outcome_code_expr: str = "",
                            target_legacy_id_expr: str = "", owner_employee_id_expr: str = "", is_on_behalf_expr: str = "",
                            work_date_expr: str = "", change_fields: dict = None, enabled_pending=(),
                            after: str = "Guard_result", name: str = "Audit_event") -> dict:
    """outcome_code_expr: empty = the operation succeeded as the guard allowed; otherwise an expression giving the
    refusal code (e.g. LOCKED). change_fields: {column: server-side expression}."""
    ae._check_type(event_type, enabled_pending)
    if event_type == "AdminMaintenance" and action not in ae.ADMIN_ACTIONS:
        raise ValueError("unknown admin action %r" % action)
    sink = ae.CONF_LOG if target_entity in ae.CONF_ENTITIES else ae.OPS_LOG
    fields = change_fields or {}
    keep = {k: fields[k] for k in sorted(fields)
            if not (ae._SECRET.search(k) or (sink == ae.OPS_LOG and (k in ae.CONF_FIELDS or ae._CONF.match(k))))}
    omitted = sorted(k for k in fields if k not in keep)
    gr, kind, ref = _guard_fields()
    guard_ok = "equals(%s, 'ALLOW')" % gr("ResultCode")
    out = nz(outcome_code_expr) if outcome_code_expr else EMPTY
    allowed = "and(%s, or(empty(%s), equals(%s, 'ALLOW')))" % (guard_ok, out, out)
    code = "if(%s, 'ALLOW', if(not(%s), %s, %s))" % (allowed, guard_ok, gr("ResultCode"), out)
    wd = nz(work_date_expr) if work_date_expr else EMPTY
    text = ae.ACTION_TEXT.get(action, "")
    text_expr = ("replace(%s, '{date}', %s)" % (_lit(text), wd)) if "{date}" in text else _lit(text)
    opt = lambda e: ("@%s" % e) if e else None
    txt = lambda e: ("@{%s}" % nz(e)) if e else ""
    g = {}
    prev = after
    if keep:
        g[name + "_change"] = c({k: "@%s" % v for k, v in keep.items()}, S(after))
        prev = name + "_change"
    g[name] = c({
        "Title": "@{concat(%s, ' ', %s, ' ', %s)}" % (_lit(event_type), _lit(action), code),
        "EventType": event_type, "Action": action, "ActionText": "@{%s}" % text_expr,
        "Decision": "@{if(%s, 'ALLOW', 'DENY')}" % allowed, "ResultCode": "@{%s}" % code,
        "OccurredOn": "@{utcNow('yyyy-MM-ddTHH:mm:ssZ')}", "CorrelationId": "@{%s}" % gr("CorrelationId"),
        "ActorUpn": "@{%s}" % nz(gr("AuthenticatedUpn")), "ActorEmployeeItemId": "@%s" % gr("EmployeeId"),
        "TargetList": target_entity, "TargetItemId": txt(target_id_expr), "TargetLegacyId": txt(target_legacy_id_expr),
        "OwnerEmployeeItemId": opt(owner_employee_id_expr), "IsOnBehalf": opt(is_on_behalf_expr),
        "WorkDate": txt(work_date_expr), "ScopeKind": "@{%s}" % kind, "ScopeRef": "@{%s}" % ref,
        "SourceFlow": source_flow, "Environment": environment,
        "ChangeJson": "@{string(outputs('%s_change'))}" % name if keep else "",
        "Detail": "@{concat('ignored=', join(%s, ','), ';omitted=%s;client=')}" % (gr("IgnoredInputs"), ",".join(omitted)),
    }, S(prev))
    g["Write_" + name] = _write(conf_audit_list if sink == ae.CONF_LOG else audit_list, name)
    return base._fix(g)
