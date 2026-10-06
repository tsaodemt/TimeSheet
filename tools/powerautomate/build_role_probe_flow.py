"""Role/scope probe guard: definition of SPIKE-TS-RoleProbe (Power Automate, standard connectors only).

Server-side evaluation of the role model for the TRUSTED caller:
- Trusted identity = caller's own Office 365 Users connection (MyProfile_V2); request fields are decoys.
- Employee context from the (synthetic) employee list by AccountUpn; fail closed if not exactly one active row.
- Roles = live membership of every configured role group (Office 365 Groups, service connection), never a flag.
- For each probe {a: action, t: target row index}, effective scope = most permissive scope across the caller's
  roles (scope table from configuration; missing/unknown = none), then the decision:
  company -> allow; discipline -> same non-empty discipline; self -> target is the caller; otherwise deny.
- One audit row per run with roles and every probe decision.

Configuration (environment variables): TS_SITE_URL, TS_ALLOWED_DOMAIN, TS_EMP_LIST (default _TS_IdentityTest),
TS_AUDIT_LIST (default _TS_SecuritySpikeAudit), TS_ROLE_GROUPS (JSON [[roleKey, groupObjectId], ...]),
TS_SCOPE_CONFIG (path to ScopeConfig.json), TS_PROBE_ACTIONS (comma list limiting the embedded scope table).
"""
import json
import os

import build_read_flow as base

SITE = os.environ.get("TS_SITE_URL", "https://<tenant>.sharepoint.com/sites/<staging-site>")
DOMAIN = os.environ.get("TS_ALLOWED_DOMAIN", "<tenant-domain>").lower()
EMP = os.environ.get("TS_EMP_LIST", "_TS_IdentityTest")
AUDIT = os.environ.get("TS_AUDIT_LIST", "_TS_SecuritySpikeAudit")
ROLE_GROUPS = json.loads(os.environ.get("TS_ROLE_GROUPS", '[["EMP", "<group-id>"]]'))
SCOPE_PATH = os.environ.get("TS_SCOPE_CONFIG")
ACTIONS = [a for a in os.environ.get("TS_PROBE_ACTIONS", "").split(",") if a]
c, op, sp_http, tb, S, EMPTY = base.c, base.op, base.sp_http, base.tb, base.S, base.EMPTY
USERS, GROUPS = base.USERS, base.GROUPS

table = {}
if SCOPE_PATH:
    raw = json.load(open(SCOPE_PATH, encoding="utf-8"))["scopes"]
    for role, acts in raw.items():
        keep = {a: s for a, s in acts.items() if s in ("self", "discipline", "company") and (not ACTIONS or a in ACTIONS)}
        if keep:
            table[role] = keep

guard = {
    "SiteUrl": c(SITE, {}),
    "Get_caller_profile": op(USERS, "MyProfile_V2", {"$select": "userPrincipalName,mail,id"}, S("SiteUrl")),
    "Trusted": c("@toLower(trim(if(empty(body('Get_caller_profile')?['userPrincipalName']), %s, body('Get_caller_profile')?['userPrincipalName'])))" % EMPTY, S("Get_caller_profile")),
    "Rows": base.sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,LegacyId,IsActive,DisciplineCode,AccountUpn&$orderby=Id asc&$top=50" % EMP, S("Trusted")),
    "Caller_rows": {"type": "Query", "runAfter": S("Rows"), "inputs": {"from": "@body('Rows')?['value']",
                    "where": "@equals(toLower(string(item()?['AccountUpn'])), outputs('Trusted'))"}},
}
prev = "Caller_rows"
for key, gid in ROLE_GROUPS:
    guard["List_" + key] = op(GROUPS, "ListGroupMembers", {"groupId": gid, "$top": 999}, S(prev))
    guard["Filter_" + key] = {"type": "Query", "runAfter": S("List_" + key), "inputs": {"from": "@body('List_%s')?['value']" % key,
                              "where": "@equals(toLower(string(item()?['userPrincipalName'])), outputs('Trusted'))"}}
    guard["M_" + key] = c("@greater(length(body('Filter_%s')), 0)" % key, S("Filter_" + key))
    prev = "M_" + key
guard["Role_candidates"] = c("@createArray(%s)" % ", ".join("if(outputs('M_%s'), '%s', %s)" % (k, k, EMPTY) for k, _ in ROLE_GROUPS), S(prev))
guard["Roles"] = {"type": "Query", "runAfter": S("Role_candidates"), "inputs": {"from": "@outputs('Role_candidates')", "where": "@not(empty(item()))"}}
guard["Code"] = c("@if(or(empty(outputs('Trusted')), not(endsWith(outputs('Trusted'), '@%s'))), 'INVALID_IDENTITY', "
                  "if(not(equals(length(body('Caller_rows')), 1)), if(equals(length(body('Caller_rows')), 0), 'NOT_REGISTERED', 'DUPLICATE_MAPPING'), "
                  "if(not(equals(first(body('Caller_rows'))?['IsActive'], true)), 'INACTIVE', 'OK')))" % DOMAIN, S("Roles"))
guard["CallerLegacyId"] = c("@if(equals(outputs('Code'), 'OK'), string(first(body('Caller_rows'))?['LegacyId']), %s)" % EMPTY, S("Code"))
guard["CallerDisc"] = c("@if(equals(outputs('Code'), 'OK'), string(first(body('Caller_rows'))?['DisciplineCode']), %s)" % EMPTY, S("CallerLegacyId"))
guard["ScopeTable"] = c(table, S("CallerDisc"))
guard["Probes"] = c("@json(if(empty(triggerBody()?['text_1']), '[]', triggerBody()?['text_1']))", S("ScopeTable"))


def rk(k):
    v = "string(outputs('ScopeTable')?['%s']?[item()?['a']])" % k
    return "if(equals(%s, 'company'), 3, if(equals(%s, 'discipline'), 2, if(equals(%s, 'self'), 1, 0)))" % (v, v, v)


rank = "@max(0, %s)" % ", ".join("if(outputs('M_%s'), %s, 0)" % (k, rk(k)) for k, _ in ROLE_GROUPS)
guard["Ranks"] = {"type": "Select", "runAfter": S("Probes"), "inputs": {"from": "@outputs('Probes')",
                  "select": {"a": "@item()?['a']", "t": "@item()?['t']", "r": rank}}}
T = "body('Rows')?['value']?[int(item()?['t'])]"
allow = ("@and(equals(outputs('Code'), 'OK'), or(equals(item()?['r'], 3), "
         "and(equals(item()?['r'], 2), not(empty(outputs('CallerDisc'))), equals(string(%s?['DisciplineCode']), outputs('CallerDisc'))), "
         "and(equals(item()?['r'], 1), equals(string(%s?['LegacyId']), outputs('CallerLegacyId')))))") % (T, T)
guard["Results"] = {"type": "Select", "runAfter": S("Ranks"), "inputs": {"from": "@body('Ranks')",
                    "select": {"a": "@item()?['a']", "t": "@item()?['t']", "r": "@item()?['r']", "allow": allow}}}
guard["Audit_body"] = c({"Title": "roleprobe @{outputs('Code')}", "Decision": "@{if(equals(outputs('Code'), 'OK'), 'ALLOWED', 'DENIED')}",
                         "ResultCode": "@{outputs('Code')}", "CallerUpnTrusted": "@{outputs('Trusted')}",
                         "CallerUpnParam": "@{%s}" % tb("text"), "OwnerUpn": "@{outputs('Trusted')}",
                         "CorrelationId": "@{workflow()?['run']?['name']}",
                         "Detail": "@{concat('kind=roleprobe;legacyId=', outputs('CallerLegacyId'), ';roles=', join(body('Roles'), ','), ';clientRequestId=', %s, ';results=', string(body('Results')))}" % tb("text_2")},
                        S("Results"))
guard["Write_audit"] = sp_http("POST", "_api/web/lists/getbytitle('%s')/items" % AUDIT, S("Audit_body"), "@{string(outputs('Audit_body'))}")
guard = base._fix(guard)
inits = {}
INPUTS = [("Text", "CallerUpn", "DECOY - logged, never trusted"), ("Text", "Probes", "JSON [{a: action, t: target row index}]"),
          ("Text", "ClientRequestId", "caller correlation token")]
