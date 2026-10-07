"""TS-AppOpen with client configuration (offline template; NOT deployed).

    trusted caller (invoker's own Users connection) -> employee -> IdCode     (guard_template identity actions)
      -> AppOpen / IdentityRejected audit row                                  (audit_template.app_open_actions, unchanged)
      -> AppSettings read by the SERVICE connection (list is locked down: no human read, AS-1)
      -> client subset (keys marked exposeToClient in the registry), typed and validated like client_config.py
      -> response {ok, resultcode, messagecode, correlationid, employeecode, configstatus, config, interim, missing}

Configuration knowledge is baked from the registry and the environment overlay at build time (exposed keys, types,
bounds, fallback values, interim values allowed in this environment); a change means regenerating the template.
Connections are solution connection-reference PLACEHOLDERS: no connection, account or UPN is bound here.
"""
from __future__ import annotations

import json

import audit_template as at
import build_read_flow as base
import guard_template as gt

c, sp_http, S, EMPTY, o, nz = base.c, base.sp_http, base.S, base.EMPTY, gt.o, gt.nz
CR = {base.SP: "<PFX>_CR_SharePoint_OpsService", base.USERS: "<PFX>_CR_O365Users_Invoker", base.GROUPS: "<PFX>_CR_O365Groups_OpsService"}
MESSAGE = {"OK": "MSG_OK", "UNMAPPED_IDENTITY": "MSG_ACCOUNT_NOT_ENABLED", "INACTIVE_EMPLOYEE": "MSG_ACCOUNT_NOT_ENABLED",
           "DUPLICATE_IDENTITY": "MSG_ACCOUNT_NOT_ENABLED", "INVALID_IDENTITY": "MSG_ACCOUNT_NOT_ENABLED",
           "ACCOUNT_NOT_ALLOWED": "MSG_ACCOUNT_NOT_ENABLED", "DIRECTORY_ERROR": "MSG_TEMPORARY_PROBLEM"}


def _lit(s):
    return "'%s'" % str(s).replace("'", "''")


def bind_connection_references(actions: dict, refs: dict = None) -> dict:
    """Replace connection names by solution connection-reference logical names (placeholders until D-3 / S05.1)."""
    refs = refs or CR

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "OpenApiConnection":
                host = dict(x["inputs"]["host"])
                name = host.pop("connectionName")
                host["connectionReferenceLogicalName"] = refs[name]
                x = dict(x, inputs=dict(x["inputs"], host=host))
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x
    return walk(actions)


def _digits_removed(v):
    e = v
    for d in "0123456789":
        e = "replace(%s, '%s', %s)" % (e, d, EMPTY)
    return e


def _rules(registry: dict, overlay: dict) -> list:
    env = (overlay or {}).get("environment")
    vals = (overlay or {}).get("values") or {}
    out = []
    for d in registry["settings"]:
        if not d.get("exposeToClient"):
            continue
        ov = vals.get(d["key"])
        interim = isinstance(ov, dict) and ov.get("interim")
        blocked = interim and (env == "PRODUCTION" or env not in (ov.get("allowedEnvironments") or []))
        ov_value = ov.get("value") if isinstance(ov, dict) else ov
        fallback = ov_value if ov_value not in (None, "") else (None if d.get("environmentSpecific") else d.get("value"))
        out.append(dict(d, fallback=None if fallback in (None, "") else str(fallback), blocked=bool(blocked),
                        interim=(str(ov_value), ov.get("customerDecision", "interim")) if interim and not blocked else None))
    return out


def appstart_actions(*, site: str, domain: str, emp_list: str, audit_list: str, environment: str, registry: dict, overlay: dict,
                     settings_list: str = "AppSettings", client_type_expr: str = "triggerBody()?['text']",
                     untrusted_inputs=("CallerUpn", "ActorUpn", "OwnerUpn", "EmployeeId", "Role", "Scope", "UserPrincipalName", "Config"),
                     refs: dict = None) -> dict:
    g = at.app_open_actions(site=site, domain=domain, emp_list=emp_list, audit_list=audit_list, environment=environment,
                            client_type_expr=client_type_expr, untrusted_inputs=untrusted_inputs)
    g.pop("Respond")
    ok = "equals(outputs('IdCode'), 'OK')"
    g["Settings_read"] = sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=Title,Value&$top=500" % settings_list,
                                 S("Write_Audit_event"))
    g["Settings_rows"] = c("@if(equals(actions('Settings_read')?['status'], 'Succeeded'), body('Settings_read')?['value'], createArray())",
                           {"Settings_read": ["Succeeded", "Failed"]})
    prev = "Settings_rows"
    rules = _rules(registry, overlay)
    status, value, interim = {}, {}, {}
    for r in rules:
        k = r["key"]
        q = "Q_" + k
        g[q] = {"type": "Query", "runAfter": S(prev), "inputs": {"from": "@outputs('Settings_rows')",
                                                                 "where": "@equals(toLower(%s), %s)" % (nz("item()?['Title']"), _lit(k.lower()))}}
        raw = nz("if(equals(length(body('%s')), 0), null, first(body('%s'))?['Value'])" % (q, q))
        fb = _lit(r["fallback"]) if r["fallback"] is not None else "null"
        g["V_" + k] = c("@if(empty(%s), %s, trim(%s))" % (raw, fb, raw), S(q))  # whitespace is a value (-> INVALID), as in the reference
        V = o("V_" + k)
        sv = nz(V)
        t = r["type"]
        if t == "int":
            valid = "and(not(empty(%s)), empty(%s))" % (sv, _digits_removed(sv))
            num = "int(if(%s, %s, '0'))" % (valid, sv)
        elif t == "decimal":
            rest = _digits_removed(sv)
            valid = ("and(not(empty(%s)), or(empty(%s), equals(%s, '.')), not(startsWith(%s, '.')), not(endsWith(%s, '.')))"
                     % (sv, rest, rest, sv, sv))
            num = "float(if(%s, %s, '0'))" % (valid, sv)
        elif t == "enum":
            m = _lit(json.dumps({a.lower(): a for a in r["allowed"]}))
            valid = "not(equals(json(%s)?[toLower(%s)], null))" % (m, sv)
            num = "json(%s)?[toLower(%s)]" % (m, sv)
        else:
            raise ValueError("client exposure supports int, decimal and enum only: %s" % k)
        bounds = []
        if t in ("int", "decimal"):
            if r.get("min") is not None:
                bounds.append("not(less(%s, %s))" % (num, r["min"]))
            if r.get("max") is not None:
                bounds.append("not(greater(%s, %s))" % (num, r["max"]))
        okexpr = "and(%s)" % ", ".join([valid] + bounds) if bounds else valid
        read_ok = "equals(actions('Settings_read')?['status'], 'Succeeded')"  # unknown live values -> unresolved (fail closed)
        st = "'MISSING'" if r["blocked"] else "if(not(%s), 'MISSING', if(equals(%s, null), 'MISSING', if(%s, 'OK', 'INVALID')))" % (read_ok, V, okexpr)
        g["S_" + k] = c("@" + st, S("V_" + k))
        g["X_" + k] = c("@if(equals(outputs('S_%s'), 'OK'), %s, null)" % (k, num), S("S_" + k))
        status[k], value[k] = "outputs('S_%s')" % k, "outputs('X_%s')" % k
        if r["interim"]:
            interim[k] = "and(equals(outputs('S_%s'), 'OK'), equals(string(outputs('X_%s')), %s))" % (k, k, _lit(r["interim"][0]))
        prev = "X_" + k
    cfg = "json('{}')"
    for k in status:
        cfg = "if(equals(%s, 'OK'), setProperty(%s, %s, %s), %s)" % (status[k], cfg, _lit(k), value[k], cfg)
    g["Client_config"] = c("@" + cfg, S(prev))
    im = "json('{}')"
    for k, cond in interim.items():
        decision = next(r["interim"][1] for r in rules if r["key"] == k)
        im = "if(%s, setProperty(%s, %s, %s), %s)" % (cond, im, _lit(k), _lit(decision), im)
    g["Client_interim"] = c("@" + im, S("Client_config"))
    g["Statuses"] = c({k: "@" + v for k, v in status.items()}, S("Client_interim"))
    g["Missing"] = {"type": "Query", "runAfter": S("Statuses"), "inputs": {
        "from": "@createArray(%s)" % ", ".join(_lit(k) for k in status), "where": "@not(equals(outputs('Statuses')?[item()], 'OK'))"}}
    invalid = "or(false, %s)" % ", ".join("equals(%s, 'INVALID')" % v for v in status.values())
    g["Config_status"] = c("@if(empty(body('Missing')), 'OK', if(%s, 'CONFIG_INVALID', 'CONFIG_UNRESOLVED'))" % invalid, S("Missing"))
    code = "if(%s, 'OK', outputs('IdCode'))" % ok
    msg = "json(%s)?[%s]" % (_lit(json.dumps(MESSAGE)), code)
    body = {"ok": "@{if(%s, 'true', 'false')}" % ok, "resultcode": "@{%s}" % code,
            "messagecode": "@{if(equals(%s, null), 'MSG_TEMPORARY_PROBLEM', %s)}" % (msg, msg),
            "correlationid": "@{workflow()?['run']?['name']}",
            "employeecode": "@{if(%s, outputs('CallerCode'), %s)}" % (ok, EMPTY),
            "configstatus": "@{if(%s, outputs('Config_status'), %s)}" % (ok, EMPTY),
            "config": "@{if(%s, string(outputs('Client_config')), '{}')}" % ok,
            "interim": "@{if(%s, string(outputs('Client_interim')), '{}')}" % ok,
            "missing": "@{if(%s, join(body('Missing'), ','), %s)}" % (ok, EMPTY)}
    g["Respond"] = {"type": "Response", "kind": "PowerApp", "runAfter": S("Config_status"),
                    "inputs": {"statusCode": 200, "body": body,
                               "schema": {"type": "object", "properties": {k: {"title": k, "x-ms-dynamically-added": True, "type": "string"}
                                                                            for k in body}}}}
    return bind_connection_references(base._fix(g), refs)
