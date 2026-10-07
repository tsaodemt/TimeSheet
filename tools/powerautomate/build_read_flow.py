"""Guarded READ proxy: definition of SPIKE-TS-ReadEntries (Power Automate, standard connectors only).

Security model
- Trusted caller = caller's OWN Office 365 Users connection (MyProfile_V2); request fields are never identity.
- Reviewer = live membership of the reviewer Entra group (Office 365 Groups, service connection).
- Normal caller: rows with OwnerUpn == trusted caller only. A foreign RequestedOwner is refused (FORBIDDEN).
- Reviewer ("team" mode): all rows, optionally one resolved owner.
- Query is server-side: indexed first filter (OwnerUpn and/or WorkDate), keyset paging (Id gt <after>),
  $top capped at 500. Rows are never loaded wholesale and filtered in memory.
- Defence in depth: returned rows are re-checked against the effective owner; any mismatch => ERROR_LEAK, no rows.
- Every read writes an audit row (decision, caller, filter, returned ids, correlation id).

Configuration (environment variables): TS_SITE_URL, TS_REVIEWER_GROUP_ID, TS_LIST (default _TS_SecuritySpike),
TS_AUDIT_LIST (default _TS_SecuritySpikeAudit), TS_BUSINESS_TIMEZONE (IANA name of the environment's business time
zone; the Windows id for convertToUtc and any UTC offset are derived from it, never configured separately).

Date range (fixed 2026-10-07): FromDate/ToDate are inclusive BUSINESS dates. A date-only value is stored as local
midnight, so the filter is the half-open UTC interval [local FromDate 00:00, local ToDate+1 00:00). The earlier version
used UTC-midnight bounds, which dropped the first day of the range in a time zone east of UTC. Both dates or neither;
a reversed range is refused (VALIDATION).
"""
import os, re

from date_range import date_clause_expr, reversed_range_expr, windows_zone_from_config

SITE = os.environ.get("TS_SITE_URL", "https://<tenant>.sharepoint.com/sites/<staging-site>")
GROUP_ID = os.environ.get("TS_REVIEWER_GROUP_ID", "<reviewer-group-object-id>")
LIST = os.environ.get("TS_LIST", "_TS_SecuritySpike")
AUDIT = os.environ.get("TS_AUDIT_LIST", "_TS_SecuritySpikeAudit")
_TZ = os.environ.get("TS_BUSINESS_TIMEZONE", "")
WIN_TZ = windows_zone_from_config(_TZ) if _TZ else "<business-windows-timezone>"  # unset: a range request cannot run
SP, USERS, GROUPS = "shared_sharepointonline", "shared_office365users", "shared_office365groups"
API = lambda n: "/providers/Microsoft.PowerApps/apis/" + n
S = lambda *n: {x: ["Succeeded"] for x in n}
o = lambda n: "outputs('%s')" % n
EMPTY = "substring('x', 0, 0)"   # classic designer drops '' literals on paste


def op(conn, opid, params, after):
    return {"type": "OpenApiConnection", "runAfter": after,
            "inputs": {"host": {"connectionName": conn, "operationId": opid, "apiId": API(conn)},
                       "parameters": params, "authentication": "@parameters('$authentication')"}}


def sp_http(method, uri, after, body=None):
    p = {"dataset": "@{outputs('SiteUrl')}", "parameters/method": method, "parameters/uri": uri,
         "parameters/headers": {"Accept": "application/json;odata=nometadata", "Content-Type": "application/json;odata=nometadata"}}
    if body is not None:
        p["parameters/body"] = body
    return op(SP, "HttpRequest", p, after)


def c(expr, after):
    return {"type": "Compose", "inputs": expr, "runAfter": after}


def tb(key):  # safe text input: empty string when missing (no coalesce/'' for the classic designer)
    return "if(empty(triggerBody()?['%s']), %s, triggerBody()?['%s'])" % (key, EMPTY, key)


RESULT = ("@if(and(not(empty({H})), not(equals({H}, {T}))), 'IDENTITY_MISMATCH', "
          "if(empty({T}), 'IDENTITY_MISSING', "
          "if(not(or(equals({M}, 'own'), equals({M}, 'team'))), 'VALIDATION', "
          "if(and(equals({M}, 'team'), not({R})), 'FORBIDDEN', "
          "if(and(equals({M}, 'own'), not(empty({Q})), not(equals({Q}, {T}))), 'FORBIDDEN', "
          "if(and(equals({M}, 'team'), not(empty({Q})), not({V})), 'VALIDATION_OWNER_UNKNOWN', "
          "if(and({HR}, or(empty({FR}), empty({TO}))), 'VALIDATION', "
          "if(and({HR}, {REV}), 'VALIDATION', 'OK'))))))))").format(
    H=o("HeaderUpn"), T=o("Trusted"), M=o("Mode"), R=o("IsReviewer"), Q=o("ReqOwner"), V=o("ReqOwnerValid"),
    HR=o("HasRange"), FR=o("FromRaw"), TO=o("ToRaw"),
    REV=reversed_range_expr("if(empty(%s), '2000-01-01', %s)" % (o("FromRaw"), o("FromRaw")),
                            "if(empty(%s), '2000-01-01', %s)" % (o("ToRaw"), o("ToRaw"))))

INIT = {
    "Init_RowsJson": ("RowsJson", "string", "[]"),
    "Init_ReturnedIds": ("ReturnedIds", "string", "[]"),
    "Init_Count": ("Count", "integer", 0),
    "Init_NextAfterId": ("NextAfterId", "integer", 0),
    "Init_Leak": ("Leak", "integer", 0),
}
inits = {}
prev = None
for k, (n, t, v) in INIT.items():
    inits[k] = {"type": "InitializeVariable", "runAfter": S(prev) if prev else {}, "inputs": {"variables": [{"name": n, "type": t, "value": v}]}}
    prev = k

ITEMS = "_api/web/lists/getbytitle('%s')/items" % LIST
guard = {
    "SiteUrl": c(SITE, {}),
    "Get_caller_profile": op(USERS, "MyProfile_V2", {"$select": "userPrincipalName,mail,id"}, S("SiteUrl")),
    "List_reviewer_members": op(GROUPS, "ListGroupMembers", {"groupId": GROUP_ID, "$top": 999}, S("Get_caller_profile")),
    "Trusted": c("@toLower(trim(if(empty(body('Get_caller_profile')?['userPrincipalName']), %s, body('Get_caller_profile')?['userPrincipalName'])))" % EMPTY, S("List_reviewer_members")),
    "HeaderUpn": c("@toLower(trim(if(empty(triggerOutputs()?['headers']?['x-ms-user-email']), %s, triggerOutputs()?['headers']?['x-ms-user-email'])))" % EMPTY, S("Trusted")),
    "Filter_reviewer": {"type": "Query", "runAfter": S("HeaderUpn"), "inputs": {"from": "@body('List_reviewer_members')?['value']",
                        "where": "@equals(toLower(if(empty(item()?['userPrincipalName']), %s, item()?['userPrincipalName'])), outputs('Trusted'))" % EMPTY}},
    "IsReviewer": c("@greater(length(body('Filter_reviewer')), 0)", S("Filter_reviewer")),
    "Mode": c("@toLower(trim(%s))" % tb("text"), S("IsReviewer")),
    "ReqOwner": c("@toLower(trim(%s))" % tb("text_1"), S("Mode")),
    "Resolve_req_owner": op(USERS, "UserProfile_V2", {"id": "@if(empty(outputs('ReqOwner')), outputs('Trusted'), outputs('ReqOwner'))",
                                                    "$select": "userPrincipalName"}, S("ReqOwner")),
    "ReqOwnerValid": c("@and(equals(actions('Resolve_req_owner')?['status'], 'Succeeded'), not(empty(body('Resolve_req_owner')?['userPrincipalName'])))",
                       {"Resolve_req_owner": ["Succeeded", "Failed"]}),
    "ReqOwnerCanon": c("@if(outputs('ReqOwnerValid'), toLower(body('Resolve_req_owner')?['userPrincipalName']), outputs('ReqOwner'))", S("ReqOwnerValid")),
    "PageSize": c("@min(max(int(triggerBody()?['number_1']), 1), 500)", S("ReqOwnerCanon")),  # required numeric input; empty() is invalid on integers
    "AfterId": c("@max(int(triggerBody()?['number']), 0)", S("PageSize")),
    "FromRaw": c("@trim(%s)" % tb("text_4"), S("AfterId")),
    "ToRaw": c("@trim(%s)" % tb("text_5"), S("FromRaw")),
    "HasRange": c("@or(not(empty(outputs('FromRaw'))), not(empty(outputs('ToRaw'))))", S("ToRaw")),
    "ResultCode": c(RESULT, S("HasRange")),
    "FilterOwner": c("@if(equals(outputs('Mode'), 'team'), if(empty(outputs('ReqOwner')), %s, outputs('ReqOwnerCanon')), outputs('Trusted'))" % EMPTY, S("ResultCode")),
    "If_ok": {"type": "If", "runAfter": S("FilterOwner"),
              "expression": {"equals": ["@outputs('ResultCode')", "OK"]},
              "actions": {
                  "OwnerClause": c("@if(empty(outputs('FilterOwner')), %s, concat('OwnerUpn eq ''', outputs('FilterOwner'), ''' and '))" % EMPTY, {}),
                  "DateClause": c("@if(outputs('HasRange'), %s, %s)" % (date_clause_expr("WorkDate", o("FromRaw"), o("ToRaw"), WIN_TZ), EMPTY), S("OwnerClause")),
                  "FilterExpr": c("@concat(outputs('OwnerClause'), outputs('DateClause'), 'Id gt ', string(outputs('AfterId')))", S("DateClause")),
                  "Query": sp_http("GET", ITEMS + "?$select=Id,Title,OwnerUpn,ActorUpn,IsOnBehalf,EntryStatus,Hours,WorkDate&$filter=@{outputs('FilterExpr')}&$orderby=Id asc&$top=@{outputs('PageSize')}", S("FilterExpr")),
                  "Select_rows": {"type": "Select", "runAfter": S("Query"), "inputs": {"from": "@body('Query')?['value']",
                                  "select": {"Id": "@item()?['Id']", "Title": "@item()?['Title']", "OwnerUpn": "@item()?['OwnerUpn']",
                                             "ActorUpn": "@item()?['ActorUpn']", "IsOnBehalf": "@item()?['IsOnBehalf']",
                                             "EntryStatus": "@item()?['EntryStatus']", "Hours": "@item()?['Hours']", "WorkDate": "@item()?['WorkDate']"}}},
                  "Select_ids": {"type": "Select", "runAfter": S("Select_rows"), "inputs": {"from": "@body('Query')?['value']", "select": "@item()?['Id']"}},
                  "Leak_check": {"type": "Query", "runAfter": S("Select_ids"), "inputs": {"from": "@body('Query')?['value']",
                                 "where": "@and(not(empty(outputs('FilterOwner'))), not(equals(toLower(string(item()?['OwnerUpn'])), outputs('FilterOwner'))))"}},
                  "Set_Leak": {"type": "SetVariable", "runAfter": S("Leak_check"), "inputs": {"name": "Leak", "value": "@length(body('Leak_check'))"}},
                  "Set_Count": {"type": "SetVariable", "runAfter": S("Set_Leak"), "inputs": {"name": "Count", "value": "@if(greater(variables('Leak'), 0), 0, length(body('Select_rows')))"}},
                  "Set_RowsJson": {"type": "SetVariable", "runAfter": S("Set_Count"), "inputs": {"name": "RowsJson", "value": "@{if(greater(variables('Leak'), 0), '[]', string(body('Select_rows')))}"}},
                  "Set_ReturnedIds": {"type": "SetVariable", "runAfter": S("Set_RowsJson"), "inputs": {"name": "ReturnedIds", "value": "@{if(greater(variables('Leak'), 0), '[]', string(body('Select_ids')))}"}},
                  "Set_NextAfterId": {"type": "SetVariable", "runAfter": S("Set_ReturnedIds"), "inputs": {"name": "NextAfterId",
                                      "value": "@if(and(equals(variables('Leak'), 0), equals(length(body('Select_ids')), outputs('PageSize'))), int(last(body('Select_ids'))), 0)"}}},
              "else": {"actions": {}}},
    "FinalCode": c("@if(empty(string(outputs('ResultCode'))), 'ERROR', if(not(equals(outputs('ResultCode'), 'OK')), outputs('ResultCode'), if(greater(variables('Leak'), 0), 'ERROR_LEAK', if(equals(actions('If_ok')?['status'], 'Succeeded'), 'OK', 'ERROR'))))",
                   {"If_ok": ["Succeeded", "Failed", "Skipped", "TimedOut"]}),
    "Detail_obj": c({"kind": "read", "mode": "@{outputs('Mode')}", "requestedOwner": "@{outputs('ReqOwner')}",
                     "claimReviewerParam": "@{%s}" % tb("text_3"), "from": "@{outputs('FromRaw')}", "to": "@{outputs('ToRaw')}",
                     "pageSize": "@outputs('PageSize')", "afterId": "@outputs('AfterId')", "count": "@variables('Count')",
                     "nextAfterId": "@variables('NextAfterId')", "returnedIds": "@{variables('ReturnedIds')}",
                     "clientRequestId": "@{%s}" % tb("text_6")}, S("FinalCode")),
    "Audit_body": c({"Title": "read @{outputs('FinalCode')}", "Decision": "@{if(equals(outputs('FinalCode'), 'OK'), 'ALLOWED', 'DENIED')}",
                     "ResultCode": "@{outputs('FinalCode')}", "CallerUpnTrusted": "@{outputs('Trusted')}", "CallerUpnHeader": "@{outputs('HeaderUpn')}",
                     "CallerUpnParam": "@{%s}" % tb("text_2"), "OwnerUpn": "@{if(empty(outputs('FilterOwner')), '*', outputs('FilterOwner'))}",
                     "IsOnBehalf": "@equals(outputs('Mode'), 'team')", "IsReviewer": "@outputs('IsReviewer')", "TargetItemId": "@variables('Count')",
                     "CorrelationId": "@{workflow()?['run']?['name']}", "Detail": "@{string(outputs('Detail_obj'))}"}, S("Detail_obj")),
    "Write_audit": sp_http("POST", "_api/web/lists/getbytitle('%s')/items" % AUDIT, S("Audit_body"), "@{string(outputs('Audit_body'))}"),
    "Respond": {"type": "Response", "kind": "PowerApp", "runAfter": S("Write_audit"),
                "inputs": {"statusCode": 200,
                           "body": {"resultcode": "@{outputs('FinalCode')}", "count": "@{variables('Count')}", "nextafterid": "@{variables('NextAfterId')}",
                                    "rowsjson": "@{variables('RowsJson')}", "correlationid": "@{workflow()?['run']?['name']}"},
                           "schema": {"type": "object", "properties": {k: {"title": k, "x-ms-dynamically-added": True, "type": "string"}
                                                                        for k in ["resultcode", "count", "nextafterid", "rowsjson", "correlationid"]}}}},
    "If_denied": {"type": "If", "runAfter": S("Respond"), "expression": {"not": {"equals": ["@outputs('FinalCode')", "OK"]}},
                  "actions": {"Terminate_denied": {"type": "Terminate", "runAfter": {}, "inputs": {"runStatus": "Failed",
                              "runError": {"code": "@{outputs('FinalCode')}", "message": "SPIKE read guard @{outputs('FinalCode')} correlation=@{workflow()?['run']?['name']}"}}}},
                  "else": {"actions": {}}},
}

_EMPTY_RE = re.compile(r"(?<![\w'])''(?![\w'])")


def _fix(x):
    if isinstance(x, dict): return {k: _fix(v) for k, v in x.items()}
    if isinstance(x, list): return [_fix(v) for v in x]
    if isinstance(x, str) and "@" in x: return _EMPTY_RE.sub(EMPTY, x)
    return x


inits = _fix(inits)
guard = _fix(guard)
INPUTS = [("Text", "Mode", "own | team"), ("Number", "AfterId", "keyset paging: last Id seen (0 = first page)"),
          ("Number", "PageSize", "1-500 (default 50)"), ("Text", "RequestedOwner", "optional; honoured only for verified reviewers"),
          ("Text", "CallerUpn", "DECOY - logged, never trusted"), ("Text", "ClaimReviewer", "DECOY - logged, never trusted"),
          ("Text", "FromDate", "yyyy-MM-dd business date (optional; with ToDate)"),
          ("Text", "ToDate", "yyyy-MM-dd business date, inclusive (required with FromDate)"),
          ("Text", "ClientRequestId", "caller correlation token")]
