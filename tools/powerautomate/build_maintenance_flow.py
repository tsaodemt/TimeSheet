"""D-6 guarded maintenance flow template (offline; NOT deployed). One flow per maintained target.

    trusted caller (invoker's own Users connection) -> Guard (action of this target, scope company)
      -> Validation (same rules as tools/maintenance/maintenance.py where WDL can express them; otherwise STRICTER)
      -> one SharePoint operation by the service connection (MERGE with IF-MATCH / POST; never DELETE)
      -> AdminMaintenance audit row -> response {code, correlationId}

Trigger inputs: text = Operation (Create|Update|SoftDelete), text_1 = Key (item business key), text_2 = ValuesJson
(object of field -> value), text_3 = ETag, text_4..text_6 = decoys (ActorUpn, Role, Scope: logged by name only).

Where WDL cannot express a reference rule the template refuses instead (stricter, never looser):
- decision-dependent fields: refused when present (the reference allows an unchanged value);
- invariant fields: refused when present (custom invariants are not evaluated in the flow);
- configuration values: only enum and int keys are maintainable through the template; an unparsable int fails the
  run (ERROR) instead of returning VALIDATION.
The configuration action (CFG.Maintain) is proposed and unmapped: the guard denies it until it is approved.
"""
from __future__ import annotations

import json

import audit_template as at
import build_read_flow as base
import guard_template as gt

c, sp_http, S, EMPTY, o, nz, esc = base.c, base.sp_http, base.S, base.EMPTY, gt.o, gt.nz, gt.esc
UNTRUSTED_FIELDS = ("ActorUpn", "Actor", "CallerUpn", "EmployeeId", "EmployeeItemId", "Role", "Roles", "Scope", "Author", "Editor", "OwnerUpn")
DECOYS = ["ActorUpn", "Role", "Scope"]


def _tb(key):
    return "if(empty(triggerBody()?['%s']), %s, triggerBody()?['%s'])" % (key, EMPTY, key)


def _lit(s):
    return "'%s'" % str(s).replace("'", "''")


def _arr(xs):
    return "createArray(%s)" % ", ".join(_lit(x) for x in xs)


def _remove_all(obj_expr, names):
    e = obj_expr
    for n in names:
        e = "removeProperty(%s, %s)" % (e, _lit(n))
    return e


def config_rules(registry: dict, overlay: dict) -> tuple:
    """(code map for non-maintainable keys, {key: value rule}) baked from the registry and overlay at build time.
    A decision change requires regenerating the flow: explicit and reviewable."""
    ext = {e["key"] for e in registry.get("externalConfig", [])}
    ov = (overlay or {}).get("values", {})
    codes, rules = {}, {}
    for e in ext:
        codes[e] = "ENVIRONMENT_CONFIG"
    for d in registry["settings"]:
        k = d["key"]
        if d.get("derived"):
            codes[k] = "DERIVED_READONLY"
        elif isinstance(ov.get(k), dict) and ov[k].get("interim"):
            codes[k] = "INTERIM_PROTECTED"
        elif d.get("resolution") not in ("RESOLVED", "ENVIRONMENT-SPECIFIC"):
            codes[k] = "DECISION_PENDING"
        elif d.get("environmentSpecific"):
            codes[k] = "ENVIRONMENT_RULE"
        elif d.get("type") == "enum":
            rules[k] = {"enum": d["allowed"]}
        elif d.get("type") == "int":
            rules[k] = {"min": d.get("min"), "max": d.get("max")}
        else:
            codes[k] = "VALIDATION"  # type not maintainable through the template (stricter than the reference)
    return codes, rules


def maintenance_actions(target: str, pol: dict, *, scope_config: dict, role_groups, site: str, domain: str, emp_list: str,
                        audit_list: str, conf_audit_list: str, environment: str, key_field: str = "LegacyId",
                        registry: dict = None, overlay: dict = None, source_flow: str = "MD-Maintain") -> dict:
    g = gt.guard_actions(scope_config, role_groups, site=site, domain=domain, emp_list=emp_list, audit_list=audit_list,
                         action_expr=_lit(pol["action"]), kind_expr="'company'", ref_expr=EMPTY, untrusted_inputs=DECOYS)
    ops = [x for x in pol["operations"] if x in ("Create", "Update", "SoftDelete")]
    fields = list(pol["fields"])
    sel = ",".join(["Id", key_field] + [f for f in fields if f != key_field] + (["AccountUpn"] if pol.get("kind") == "employee" else []))
    g["Op"] = c("@trim(%s)" % _tb("text"), S("Write_audit"))
    g["Key"] = c("@trim(%s)" % _tb("text_1"), S("Op"))
    g["ETag"] = c("@trim(%s)" % _tb("text_3"), S("Key"))
    g["Values_raw"] = c("@json(if(empty(%s), '{}', %s))" % (_tb("text_2"), _tb("text_2")), S("ETag"))
    g["Values"] = c("@%s" % _remove_all("outputs('Values_raw')", UNTRUSTED_FIELDS), S("Values_raw"))
    g["Ignored_fields"] = {"type": "Query", "runAfter": S("Values"), "inputs": {
        "from": "@%s" % _arr(UNTRUSTED_FIELDS), "where": "@not(equals(outputs('Values_raw')?[item()], null))"}}
    g["Extra_fields"] = c("@%s" % _remove_all("outputs('Values')", fields), S("Ignored_fields"))
    g["Item_lookup"] = sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=%s&$filter=%s eq '@{%s}'&$top=2"
                               % (target, sel, key_field, esc(o("Key"))), S("Extra_fields"))
    g["Rows"] = c("@if(equals(actions('Item_lookup')?['status'], 'Succeeded'), body('Item_lookup')?['value'], createArray())",
                  {"Item_lookup": ["Succeeded", "Failed"]})
    OP, V, ROWS, KEY = o("Op"), o("Values"), o("Rows"), o("Key")
    checks = [
        ("not(equals(outputs('Guard_result')?['ResultCode'], 'ALLOW'))", "outputs('Guard_result')?['ResultCode']"),
        ("equals(%s, 'Delete')" % OP, "'HARD_DELETE_FORBIDDEN'"),
        ("not(contains(%s, %s))" % (_arr(ops), OP), "'OPERATION_NOT_ALLOWED'"),
        ("and(not(equals(%s, 'Create')), not(equals(length(%s), 1)))" % (OP, ROWS), "'NOT_FOUND'"),
        ("and(not(equals(%s, 'Create')), empty(%s))" % (OP, o("ETag")), "'CONFLICT'"),
        ("not(empty(%s))" % o("Extra_fields"), "'FIELD_NOT_ALLOWED'"),
        ("and(not(equals(%s, 'SoftDelete')), empty(%s))" % (OP, V), "'VALIDATION'"),
    ]
    for f in sorted(pol.get("decisionFields") or {}):
        checks.append(("not(equals(%s?[%s], null))" % (V, _lit(f)), "'DECISION_PENDING'"))
    for f in sorted(pol.get("invariants") or {}):
        checks.append(("not(equals(%s?[%s], null))" % (V, _lit(f)), "'VALIDATION'"))
    if pol.get("kind") == "employee":
        checks.append(("and(equals(length(%s), 1), equals(toLower(%s), toLower(%s)), or(not(equals(%s?['AccountUpn'], null)), "
                       "not(equals(%s?['IsActive'], null))))" % (ROWS, nz("first(%s)?['AccountUpn']" % ROWS),
                                                               nz("outputs('Guard_result')?['AuthenticatedUpn']"), V, V), "'SELF_MODIFICATION'"))
    if pol.get("kind") == "config":
        codes, rules = config_rules(registry, overlay)
        g["Config_codes"] = c(codes, S("Rows"))
        g["Config_rules"] = c(rules, S("Config_codes"))
        val = nz("%s?['Value']" % V)
        rule = "outputs('Config_rules')?[%s]" % KEY
        checks.append(("not(equals(outputs('Config_codes')?[%s], null))" % KEY, "outputs('Config_codes')?[%s]" % KEY))
        checks.append(("equals(%s, null)" % rule, "'NOT_FOUND'"))
        checks.append(("and(not(equals(%s?['enum'], null)), not(contains(%s?['enum'], %s)))" % (rule, rule, val), "'VALIDATION'"))
        checks.append(("and(equals(%s?['enum'], null), not(equals(string(int(%s)), %s)))" % (rule, "if(equals(%s?['enum'], null), %s, '0')" % (rule, val), val),
                       "'VALIDATION'"))
        checks.append(("and(equals(%s?['enum'], null), not(equals(%s?['min'], null)), less(int(%s), %s?['min']))"
                       % (rule, rule, "if(equals(%s?['enum'], null), %s, '0')" % (rule, val), rule), "'VALIDATION'"))
        checks.append(("and(equals(%s?['enum'], null), not(equals(%s?['max'], null)), greater(int(%s), %s?['max']))"
                       % (rule, rule, "if(equals(%s?['enum'], null), %s, '0')" % (rule, val), rule), "'VALIDATION'"))
    expr = "'OK'"
    for cond, code in reversed(checks):
        expr = "if(%s, %s, %s)" % (cond, code, expr)
    g["Validation"] = c("@" + expr, S("Config_rules" if pol.get("kind") == "config" else "Rows"))
    soft = pol.get("softDelete")
    body = "if(equals(%s, 'SoftDelete'), json(%s), %s)" % (OP, _lit(json.dumps({soft: False})) if soft else "'{}'", V)
    q = target.replace("'", "''")
    uri = ("if(equals(%s, 'Create'), '_api/web/lists/getbytitle(''%s'')/items', "
           "concat('_api/web/lists/getbytitle(''%s'')/items(', %s, ')'))" % (OP, q, q, nz("first(%s)?['Id']" % ROWS)))
    g["If_valid"] = {"type": "If", "runAfter": S("Validation"), "expression": {"equals": ["@outputs('Validation')", "OK"]},
                     "actions": {
                         "Write_item": {"type": "OpenApiConnection", "runAfter": {}, "inputs": {
                             "host": {"connectionName": base.SP, "operationId": "HttpRequest", "apiId": base.API(base.SP)},
                             "parameters": {"dataset": "@{outputs('SiteUrl')}",
                                            "parameters/method": "POST",
                                            "parameters/uri": "@{%s}" % uri,
                                            "parameters/headers": {"Accept": "application/json;odata=nometadata",
                                                                   "Content-Type": "application/json;odata=nometadata",
                                                                   "X-HTTP-Method": "@{if(equals(%s, 'Create'), 'POST', 'MERGE')}" % OP,
                                                                   "IF-MATCH": "@{if(equals(%s, 'Create'), '*', %s)}" % (OP, o("ETag"))},
                                            "parameters/body": "@{string(%s)}" % body},
                             "authentication": "@parameters('$authentication')"}}},
                     "else": {"actions": {}}}
    g["Final_code"] = c("@if(not(equals(outputs('Validation'), 'OK')), outputs('Validation'), "
                        "if(equals(actions('Write_item')?['status'], 'Succeeded'), 'OK', "
                        "if(equals(%s, '412'), 'CONFLICT', 'ERROR')))" % nz("actions('Write_item')?['outputs']?['statusCode']"),
                        {"If_valid": ["Succeeded", "Failed", "Skipped", "TimedOut"]})
    redacted = "if(equals(outputs('Validation'), 'OK'), %s, '<redacted: rejected value>')" % V
    g.update(at.operation_event_actions(
        "AdminMaintenance", pol.get("auditAction", "MasterDataChange"), target_entity=target, audit_list=audit_list,
        conf_audit_list=conf_audit_list, environment=environment, source_flow=source_flow,
        target_id_expr="if(equals(length(%s), 1), string(first(%s)?['Id']), %s)" % (ROWS, ROWS, EMPTY),
        outcome_code_expr="if(equals(outputs('Final_code'), 'OK'), 'ALLOW', outputs('Final_code'))",
        target_legacy_id_expr=KEY, change_fields={"new": redacted, "old": "if(equals(length(%s), 1), first(%s), null)" % (ROWS, ROWS),
                                                 "operation": OP, "ignored": "join(body('Ignored_fields'), ',')"},
        after="Final_code", name="Maint_audit"))
    g["Respond"] = {"type": "Response", "kind": "PowerApp", "runAfter": S("Write_Maint_audit"),
                    "inputs": {"statusCode": 200, "body": {"code": "@{outputs('Final_code')}", "correlationid": "@{workflow()?['run']?['name']}"}}}
    return base._fix(g)
