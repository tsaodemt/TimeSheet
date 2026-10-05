"""Build the Power Automate import package (legacy .zip) for SPIKE-TS-SaveEntry.

Writes <out>/SPIKE-TS-SaveEntry.zip and <out>/definition.json (for review/evidence).
Only standard connectors: SharePoint, Office 365 Users, Office 365 Groups.
Configuration (environment variables): TS_SITE_URL, TS_REVIEWER_GROUP_ID.
Usage: python build_guard_flow.py <out_dir>
"""
import json, os, sys, uuid, zipfile

SITE = os.environ.get("TS_SITE_URL", "https://<tenant>.sharepoint.com/sites/<staging-site>")
GROUP_ID = os.environ.get("TS_REVIEWER_GROUP_ID", "<reviewer-group-object-id>")  # Entra security group used for reviewer authorisation
LIST, AUDIT = "_TS_SecuritySpike", "_TS_SecuritySpikeAudit"

SP, USERS, GROUPS = "shared_sharepointonline", "shared_office365users", "shared_office365groups"
API = lambda n: "/providers/Microsoft.PowerApps/apis/" + n


def op(conn, opid, params, after):
    return {"type": "OpenApiConnection", "runAfter": after,
            "inputs": {"host": {"connectionName": conn, "operationId": opid, "apiId": API(conn)},
                       "parameters": params, "authentication": "@parameters('$authentication')"}}


def sp_http(method, uri, after, body=None):
    p = {"dataset": SITE, "parameters/method": method, "parameters/uri": uri,
         "parameters/headers": {"Accept": "application/json;odata=nometadata",
                                "Content-Type": "application/json;odata=nometadata"}}
    if body is not None:
        p["parameters/body"] = body
    return op(SP, "HttpRequest", p, after)


def compose(expr, after):
    return {"type": "Compose", "inputs": expr, "runAfter": after}


S = lambda *names: {n: ["Succeeded"] for n in names}
o = lambda n: "outputs('%s')" % n

RESULT = ("@if(and(not(empty(%(H)s)), not(equals(%(H)s, %(T)s))), 'IDENTITY_MISMATCH', "
          "if(empty(%(T)s), 'IDENTITY_MISSING', "
          "if(not(or(equals(%(A)s,'save'), equals(%(A)s,'approve'))), 'VALIDATION', "
          "if(and(greater(%(I)s,0), not(%(X)s)), 'NOT_FOUND', "
          "if(and(%(X)s, not(empty(%(P)s)), not(equals(%(P)s, %(E)s))), 'VALIDATION_OWNER_CHANGE', "
          "if(not(%(V)s), 'VALIDATION_OWNER_UNKNOWN', "
          "if(and(%(B)s, not(%(R)s)), 'FORBIDDEN', "
          "if(and(equals(%(A)s,'approve'), not(%(R)s)), 'FORBIDDEN', "
          "if(and(equals(%(A)s,'approve'), not(%(X)s)), 'VALIDATION', "
          "if(and(equals(%(A)s,'approve'), not(%(B)s)), 'FORBIDDEN_SELF_APPROVAL', "
          "if(and(%(X)s, equals(%(S)s,'Approved')), 'LOCKED', "
          "if(and(equals(%(A)s,'save'), or(lessOrEquals(%(HR)s,0), greater(%(HR)s,24))), 'VALIDATION', "
          "'OK'))))))))))))") % dict(H=o("HeaderUpn"), T=o("Trusted"), A=o("Action"), I=o("ItemIdIn"), X=o("Exists"),
                                       P=o("ParamOwner"), E=o("EffOwner"), V=o("OwnerValid"), B=o("IsOnBehalf"), R=o("IsReviewer"),
                                       S=o("ExistingStatus"), HR=o("Hours"))

ITEM = "_api/web/lists/getbytitle('%s')/items" % LIST
VU = ITEM + "(@{variables('ItemId')})/ValidateUpdateListItem"
LOGW = lambda n, after: {"type": "AppendToStringVariable", "runAfter": after,
                         "inputs": {"name": "WriteLog", "value": "@{string(body('%s'))}" % n}}
OKW = lambda n, after: {"type": "SetVariable", "runAfter": after,
                        "inputs": {"name": "WriteOk", "value": "@not(contains(string(body('%s')), '\"HasException\":true'))" % n}}
fv = lambda name, val: {"FieldName": name, "FieldValue": val}

actions = {
    "Init_ItemId": {"type": "InitializeVariable", "runAfter": {},
                    "inputs": {"variables": [{"name": "ItemId", "type": "integer", "value": "@int(coalesce(triggerBody()?['number'], 0))"}]}},
    "Init_WriteLog": {"type": "InitializeVariable", "runAfter": S("Init_ItemId"),
                      "inputs": {"variables": [{"name": "WriteLog", "type": "string", "value": ""}]}},
    "Init_WriteOk": {"type": "InitializeVariable", "runAfter": S("Init_WriteLog"),
                     "inputs": {"variables": [{"name": "WriteOk", "type": "boolean", "value": True}]}},
    # 1. trusted caller = profile from the INVOKER's own Office 365 Users connection
    "Get_caller_profile": op(USERS, "MyProfile_V2", {"$select": "userPrincipalName,mail,id,displayName"}, S("Init_WriteOk")),
    # 2. reviewer authorisation = live Entra group membership (service connection)
    "List_reviewer_members": op(GROUPS, "ListGroupMembers", {"groupId": GROUP_ID, "$top": 999}, S("Get_caller_profile")),
    "Get_existing": sp_http("GET", ITEM + "?$filter=Id eq @{int(coalesce(triggerBody()?['number'], 0))}&$select=Id,OwnerUpn,EntryStatus",
                            S("List_reviewer_members")),
    "Trusted": compose("@toLower(trim(coalesce(body('Get_caller_profile')?['userPrincipalName'], '')))", S("Get_existing")),
    "HeaderUpn": compose("@toLower(trim(coalesce(triggerOutputs()?['headers']?['x-ms-user-email'], '')))", S("Trusted")),
    "Filter_reviewer": {"type": "Query", "runAfter": S("HeaderUpn"),
                        "inputs": {"from": "@body('List_reviewer_members')?['value']",
                                   "where": "@equals(toLower(coalesce(item()?['userPrincipalName'], '')), outputs('Trusted'))"}},
    "IsReviewer": compose("@greater(length(body('Filter_reviewer')), 0)", S("Filter_reviewer")),
    "Exists": compose("@not(empty(body('Get_existing')?['value']))", S("IsReviewer")),
    "ExistingStatus": compose("@if(outputs('Exists'), coalesce(first(body('Get_existing')?['value'])?['EntryStatus'], ''), '')", S("Exists")),
    "ParamOwner": compose("@toLower(trim(coalesce(triggerBody()?['text_1'], '')))", S("ExistingStatus")),
    "EffOwner": compose("@if(outputs('Exists'), toLower(coalesce(first(body('Get_existing')?['value'])?['OwnerUpn'], '')), "
                        "if(empty(outputs('ParamOwner')), outputs('Trusted'), outputs('ParamOwner')))", S("ParamOwner")),
    "Resolve_owner": op(USERS, "UserProfile_V2", {"id": "@outputs('EffOwner')", "$select": "userPrincipalName,accountEnabled"}, S("EffOwner")),
    "OwnerValid": compose("@and(equals(actions('Resolve_owner')?['status'], 'Succeeded'), not(empty(body('Resolve_owner')?['userPrincipalName'])))",
                          {"Resolve_owner": ["Succeeded", "Failed"]}),
    "OwnerCanon": compose("@if(outputs('OwnerValid'), toLower(body('Resolve_owner')?['userPrincipalName']), outputs('EffOwner'))", S("OwnerValid")),
    "IsOnBehalf": compose("@not(equals(outputs('OwnerCanon'), outputs('Trusted')))", S("OwnerCanon")),
    "Action": compose("@toLower(trim(coalesce(triggerBody()?['text'], '')))", S("IsOnBehalf")),
    "Hours": compose("@float(coalesce(triggerBody()?['number_1'], 0))", S("Action")),
    "ItemIdIn": compose("@int(coalesce(triggerBody()?['number'], 0))", S("Hours")),
    "ResultCode": compose(RESULT, S("ItemIdIn")),
    "Operation": compose("@if(not(equals(outputs('ResultCode'), 'OK')), 'NONE', if(equals(outputs('Action'), 'approve'), 'APPROVE', "
                         "if(outputs('Exists'), 'UPDATE', 'CREATE')))", S("ResultCode")),
    "Create_body": compose({"Title": "SPIKE entry @{outputs('OwnerCanon')}", "OwnerUpn": "@{outputs('OwnerCanon')}",
                            "ActorUpn": "@{outputs('Trusted')}", "IsOnBehalf": "@outputs('IsOnBehalf')", "EntryStatus": "Draft",
                            "Hours": "@outputs('Hours')", "CorrelationId": "@{workflow()?['run']?['name']}"}, S("Operation")),
    "Switch_operation": {"type": "Switch", "expression": "@outputs('Operation')", "runAfter": S("Create_body"),
                         "default": {"actions": {}},
                         "cases": {
        "Case_CREATE": {"case": "CREATE", "actions": {
            "Create_item": sp_http("POST", ITEM, {}, "@{string(outputs('Create_body'))}"),
            "Set_ItemId": {"type": "SetVariable", "runAfter": S("Create_item"),
                           "inputs": {"name": "ItemId", "value": "@int(body('Create_item')?['Id'])"}},
            "Stamp_author": sp_http("POST", VU, S("Set_ItemId"),
                                    "@{string(json(concat('{\"formValues\":[{\"FieldName\":\"Author\",\"FieldValue\":\"[{''Key'':''i:0#.f|membership|', outputs('OwnerCanon'), '''}]\"}],\"bNewDocumentUpdate\":true}')))}"),
            "Log_create": LOGW("Stamp_author", S("Stamp_author")),
            "Ok_create": OKW("Stamp_author", S("Log_create"))}},
        "Case_UPDATE": {"case": "UPDATE", "actions": {
            "Update_item": sp_http("POST", VU, {}, "@{string(json(concat('{\"formValues\":[{\"FieldName\":\"Hours\",\"FieldValue\":\"', string(outputs('Hours')), '\"},{\"FieldName\":\"ActorUpn\",\"FieldValue\":\"', outputs('Trusted'), '\"},{\"FieldName\":\"IsOnBehalf\",\"FieldValue\":\"', if(outputs('IsOnBehalf'), '1', '0'), '\"},{\"FieldName\":\"CorrelationId\",\"FieldValue\":\"', workflow()?['run']?['name'], '\"}],\"bNewDocumentUpdate\":false}')))}"),
            "Log_update": LOGW("Update_item", S("Update_item")),
            "Ok_update": OKW("Update_item", S("Log_update"))}},
        "Case_APPROVE": {"case": "APPROVE", "actions": {
            "Approve_item": sp_http("POST", VU, {}, "@{string(json(concat('{\"formValues\":[{\"FieldName\":\"EntryStatus\",\"FieldValue\":\"Approved\"},{\"FieldName\":\"ActorUpn\",\"FieldValue\":\"', outputs('Trusted'), '\"},{\"FieldName\":\"CorrelationId\",\"FieldValue\":\"', workflow()?['run']?['name'], '\"}],\"bNewDocumentUpdate\":false}')))}"),
            "Log_approve": LOGW("Approve_item", S("Approve_item")),
            "Ok_approve": OKW("Approve_item", S("Log_approve"))}}}},
    "FinalCode": compose("@if(equals(outputs('ResultCode'), 'OK'), if(and(equals(actions('Switch_operation')?['status'], 'Succeeded'), variables('WriteOk')), 'OK', 'ERROR'), outputs('ResultCode'))",
                         {"Switch_operation": ["Succeeded", "Failed", "Skipped", "TimedOut"]}),
    "Detail_obj": compose({"action": "@{outputs('Action')}", "operation": "@{outputs('Operation')}",
                           "requestedOwner": "@{outputs('ParamOwner')}", "ownerValid": "@outputs('OwnerValid')",
                           "existingStatus": "@{outputs('ExistingStatus')}", "clientRequestId": "@{coalesce(triggerBody()?['text_3'], '')}",
                           "headerUserName": "@{coalesce(triggerOutputs()?['headers']?['x-ms-user-name'], '')}"}, S("FinalCode")),
    "Audit_body": compose({"Title": "@{outputs('Action')} @{outputs('FinalCode')}",
                           "Decision": "@{if(equals(outputs('FinalCode'), 'OK'), 'ALLOWED', 'DENIED')}",
                           "ResultCode": "@{outputs('FinalCode')}",
                           "CallerUpnTrusted": "@{outputs('Trusted')}",
                           "CallerUpnHeader": "@{outputs('HeaderUpn')}",
                           "CallerUpnParam": "@{coalesce(triggerBody()?['text_2'], '')}",
                           "OwnerUpn": "@{outputs('OwnerCanon')}",
                           "IsOnBehalf": "@outputs('IsOnBehalf')",
                           "IsReviewer": "@outputs('IsReviewer')",
                           "TargetItemId": "@variables('ItemId')",
                           "CorrelationId": "@{workflow()?['run']?['name']}",
                           "Detail": "@{string(outputs('Detail_obj'))} | write=@{variables('WriteLog')}"},
                          S("Detail_obj")),
    "Write_audit": sp_http("POST", "_api/web/lists/getbytitle('%s')/items" % AUDIT, S("Audit_body"), "@{string(outputs('Audit_body'))}"),
    "If_denied": {"type": "If", "runAfter": S("Write_audit"),
                  "expression": {"not": {"equals": ["@outputs('FinalCode')", "OK"]}},
                  "actions": {"Terminate_denied": {"type": "Terminate", "runAfter": {},
                                                   "inputs": {"runStatus": "Failed",
                                                              "runError": {"code": "@{outputs('FinalCode')}",
                                                                           "message": "SPIKE guard decision @{outputs('FinalCode')} audit=@{body('Write_audit')?['Id']} correlation=@{workflow()?['run']?['name']}"}}}},
                  "else": {"actions": {}}},
}

trigger = {"manual": {"type": "Request", "kind": "Button", "inputs": {"schema": {"type": "object", "properties": {
    "text": {"title": "Action", "type": "string", "x-ms-dynamically-added": True, "description": "save | approve", "x-ms-content-hint": "TEXT"},
    "number": {"title": "ItemId", "type": "number", "x-ms-dynamically-added": True, "description": "0 = new entry", "x-ms-content-hint": "NUMBER"},
    "number_1": {"title": "Hours", "type": "number", "x-ms-dynamically-added": True, "description": "hours", "x-ms-content-hint": "NUMBER"},
    "text_1": {"title": "OwnerUpn", "type": "string", "x-ms-dynamically-added": True, "description": "requested owner (blank = self)", "x-ms-content-hint": "TEXT"},
    "text_2": {"title": "CallerUpn", "type": "string", "x-ms-dynamically-added": True, "description": "DECOY - logged, never trusted", "x-ms-content-hint": "TEXT"},
    "text_3": {"title": "ClientRequestId", "type": "string", "x-ms-dynamically-added": True, "description": "caller correlation token", "x-ms-content-hint": "TEXT"}},
    "required": ["text", "number", "number_1"]}}}}


def _split_args(s, i):
    """s[i] is just after '('; return (args, index_after_closing_paren)."""
    depth, q, start, args = 0, False, i, []
    while i < len(s):
        c = s[i]
        if q:
            if c == "'" and i + 1 < len(s) and s[i + 1] == "'": i += 1
            elif c == "'": q = False
        elif c == "'": q = True
        elif c in "([": depth += 1
        elif c in ")]":
            if depth == 0:
                args.append(s[start:i].strip()); return args, i + 1
            depth -= 1
        elif c == "," and depth == 0:
            args.append(s[start:i].strip()); start = i + 1
        i += 1
    raise ValueError(s)


def _no_str_coalesce(s):
    """Classic designer drops coalesce(x, <string>) on paste: rewrite as if(empty(x), <string>, x)."""
    out, i = "", 0
    while True:
        j = s.find("coalesce(", i)
        if j < 0: return out + s[i:]
        args, k = _split_args(s, j + 9)
        if len(args) == 2 and not args[1].lstrip("-").isdigit():
            a = _no_str_coalesce(args[0])
            out += s[i:j] + "if(empty(%s), %s, %s)" % (a, args[1], a)
        else:
            out += s[i:k]
        i = k

# Classic-designer paste drops empty-string literals; use an equivalent non-empty literal form.
EMPTY_RE = __import__("re").compile(r"(?<![\w'])''(?![\w'])")
def _fix(o):
    if isinstance(o, dict): return {k: _fix(v) for k, v in o.items()}
    if isinstance(o, list): return [_fix(v) for v in o]
    if isinstance(o, str) and "@" in o: return _no_str_coalesce(EMPTY_RE.sub("substring('x', 0, 0)", o))
    return o
actions = _fix(actions)

definition = {"$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
              "contentVersion": "1.0.0.0",
              "parameters": {"$connections": {"defaultValue": {}, "type": "Object"},
                             "$authentication": {"defaultValue": {}, "type": "SecureObject"}},
              "triggers": trigger, "actions": actions, "outputs": {}}


def main(out):
    os.makedirs(out, exist_ok=True)
    flow_id = str(uuid.uuid4())
    conns = {SP: "SharePoint", USERS: "Office 365 Users", GROUPS: "Office 365 Groups"}
    api_res = {k: str(uuid.uuid4()) for k in conns}
    con_res = {k: str(uuid.uuid4()) for k in conns}
    flow_res = str(uuid.uuid4())
    resources = {flow_res: {"type": "Microsoft.Flow/flows", "suggestedCreationType": "New", "creationType": "Existing, New, Update",
                            "details": {"displayName": "SPIKE-TS-SaveEntry"}, "configurableBy": "User", "hierarchy": "Root",
                            "dependsOn": list(api_res.values()) + list(con_res.values())}}
    for k, n in conns.items():
        resources[api_res[k]] = {"id": API(k), "name": k, "type": "Microsoft.PowerApps/apis", "suggestedCreationType": "Existing",
                                 "details": {"displayName": n, "iconUri": ""}, "configurableBy": "System", "hierarchy": "Child",
                                 "dependsOn": []}
        resources[con_res[k]] = {"type": "Microsoft.PowerApps/apis/connections", "suggestedCreationType": "Existing",
                                 "creationType": "Existing", "details": {"displayName": n, "iconUri": ""},
                                 "configurableBy": "User", "hierarchy": "Child", "dependsOn": [api_res[k]]}
    manifest = {"schema": "1.0", "details": {"displayName": "SPIKE-TS-SaveEntry", "description": "TEMPORARY EPIC 03 write-proxy spike. Delete after evidence review.",
                                             "createdTime": "2026-10-05T00:00:00Z", "packageTelemetryId": str(uuid.uuid4()),
                                             "creator": "spike", "sourceEnvironment": ""}, "resources": resources}
    flowdef = {"name": flow_id, "id": "/providers/Microsoft.Flow/flows/" + flow_id, "type": "Microsoft.Flow/flows",
               "properties": {"apiId": "/providers/Microsoft.PowerApps/apis/shared_logicflows", "displayName": "SPIKE-TS-SaveEntry",
                              "definition": definition,
                              "connectionReferences": {k: {"connectionName": "placeholder-" + k, "source": "Embedded", "id": API(k), "tier": "NotSpecified"} for k in conns},
                              "flowFailureAlertSubscribed": False}}
    zp = os.path.join(out, "SPIKE-TS-SaveEntry.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        z.writestr("Microsoft.Flow/flows/manifest.json", json.dumps({"packageSchemaVersion": "1.0", "flowAssets": {"assetPaths": [flow_id]}}))
        z.writestr("Microsoft.Flow/flows/%s/definition.json" % flow_id, json.dumps(flowdef, indent=1))
        z.writestr("Microsoft.Flow/flows/%s/apisMap.json" % flow_id, json.dumps(api_res))
        z.writestr("Microsoft.Flow/flows/%s/connectionsMap.json" % flow_id, json.dumps(con_res))
    json.dump(definition, open(os.path.join(out, "definition.json"), "w", encoding="utf-8"), indent=1)
    print(zp)


if __name__ == "__main__":
    main(sys.argv[1])
