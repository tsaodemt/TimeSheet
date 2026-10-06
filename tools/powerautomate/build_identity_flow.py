"""Identity-resolution guard: definition of SPIKE-TS-ResolveIdentity (Power Automate, standard connectors only).

Flow-side implementation of docs/identity-resolution.md (reference: tools/identity/identity_resolver.py).
- Trusted identity = caller's OWN Office 365 Users connection (MyProfile_V2). Request fields are decoys only.
- Normalise (trim, lower-case), check the allowed tenant domain (configuration).
- Lookup in the employee list by AccountUpn (indexed, enforce-unique), $top=2 to detect duplicates.
- Result codes: OK, INVALID_IDENTITY, IDENTITY_MISMATCH, NOT_REGISTERED, DUPLICATE_MAPPING, INACTIVE, ERROR.
- Role context: live membership of the configured role group (service Groups connection), never a request flag.
- Every resolution writes an audit row.

Configuration (environment variables): TS_SITE_URL, TS_ALLOWED_DOMAIN, TS_ROLE_GROUP_ID, TS_ROLE_KEY (default REV),
TS_EMP_LIST (default _TS_IdentityTest - synthetic test list), TS_AUDIT_LIST (default _TS_SecuritySpikeAudit).
"""
import os

import build_read_flow as base  # shared helpers (op, sp_http, c, tb, S, _fix, EMPTY)

SITE = os.environ.get("TS_SITE_URL", "https://<tenant>.sharepoint.com/sites/<staging-site>")
DOMAIN = os.environ.get("TS_ALLOWED_DOMAIN", "<tenant-domain>")
GROUP_ID = os.environ.get("TS_ROLE_GROUP_ID", "<role-group-object-id>")
ROLE_KEY = os.environ.get("TS_ROLE_KEY", "REV")
EMP = os.environ.get("TS_EMP_LIST", "_TS_IdentityTest")
AUDIT = os.environ.get("TS_AUDIT_LIST", "_TS_SecuritySpikeAudit")
c, op, sp_http, tb, S, EMPTY = base.c, base.op, base.sp_http, base.tb, base.S, base.EMPTY
USERS, GROUPS = base.USERS, base.GROUPS
o = lambda n: "outputs('%s')" % n

CODE = ("@if(empty({T}), 'INVALID_IDENTITY', "
        "if(not(endsWith({T}, '@{D}')), 'INVALID_IDENTITY', "
        "if(and(not(empty({H})), not(equals({H}, {T}))), 'IDENTITY_MISMATCH', "
        "if(not(equals(actions('Lookup')?['status'], 'Succeeded')), 'ERROR', "
        "if(equals(length(body('Lookup')?['value']), 0), 'NOT_REGISTERED', "
        "if(greater(length(body('Lookup')?['value']), 1), 'DUPLICATE_MAPPING', "
        "if(not(equals(first(body('Lookup')?['value'])?['IsActive'], true)), 'INACTIVE', 'OK')))))))").format(
    T=o("Trusted"), H=o("HeaderUpn"), D=DOMAIN.lower())

guard = {
    "SiteUrl": c(SITE, {}),
    "Get_caller_profile": op(USERS, "MyProfile_V2", {"$select": "userPrincipalName,mail,id"}, S("SiteUrl")),
    "Trusted": c("@toLower(trim(if(empty(body('Get_caller_profile')?['userPrincipalName']), %s, body('Get_caller_profile')?['userPrincipalName'])))" % EMPTY, S("Get_caller_profile")),
    "HeaderUpn": c("@toLower(trim(if(empty(triggerOutputs()?['headers']?['x-ms-user-email']), %s, triggerOutputs()?['headers']?['x-ms-user-email'])))" % EMPTY, S("Trusted")),
    "Lookup": sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=Id,LegacyId,IsActive,DisciplineCode,AccountUpn&$filter=AccountUpn eq '@{replace(outputs('Trusted'), decodeUriComponent('%%27'), concat(decodeUriComponent('%%27'), decodeUriComponent('%%27')))}'&$top=2" % EMP, S("HeaderUpn")),
    "List_role_members": op(GROUPS, "ListGroupMembers", {"groupId": GROUP_ID, "$top": 999}, {"Lookup": ["Succeeded", "Failed"]}),
    "Filter_role": {"type": "Query", "runAfter": S("List_role_members"), "inputs": {"from": "@body('List_role_members')?['value']",
                    "where": "@equals(toLower(if(empty(item()?['userPrincipalName']), %s, item()?['userPrincipalName'])), outputs('Trusted'))" % EMPTY}},
    "HasRole": c("@greater(length(body('Filter_role')), 0)", S("Filter_role")),
    "ResultCode": c(CODE, S("HasRole")),
    "Emp": c("@if(equals(outputs('ResultCode'), 'OK'), first(body('Lookup')?['value']), json('{}'))", S("ResultCode")),
    "Roles": c("@if(and(equals(outputs('ResultCode'), 'OK'), outputs('HasRole')), '%s', %s)" % (ROLE_KEY, EMPTY), S("Emp")),
    "Audit_body": c({"Title": "identity @{outputs('ResultCode')}", "Decision": "@{if(equals(outputs('ResultCode'), 'OK'), 'ALLOWED', 'DENIED')}",
                     "ResultCode": "@{outputs('ResultCode')}", "CallerUpnTrusted": "@{outputs('Trusted')}", "CallerUpnHeader": "@{outputs('HeaderUpn')}",
                     "CallerUpnParam": "@{%s}" % tb("text"), "OwnerUpn": "@{outputs('Trusted')}", "IsReviewer": "@outputs('HasRole')",
                     "CorrelationId": "@{workflow()?['run']?['name']}",
                     "Detail": "@{concat('kind=identity;legacyId=', string(outputs('Emp')?['LegacyId']), ';itemId=', string(outputs('Emp')?['Id']), ';discipline=', string(outputs('Emp')?['DisciplineCode']), ';roles=', outputs('Roles'), ';matches=', string(length(body('Lookup')?['value'])), ';claimRoleParam=', %s, ';clientRequestId=', %s)}" % (tb("text_1"), tb("text_2"))},
                    S("Roles")),
    "Write_audit": sp_http("POST", "_api/web/lists/getbytitle('%s')/items" % AUDIT, S("Audit_body"), "@{string(outputs('Audit_body'))}"),
    "Respond": {"type": "Response", "kind": "PowerApp", "runAfter": S("Write_audit"),
                "inputs": {"statusCode": 200,
                           "body": {"resultcode": "@{outputs('ResultCode')}", "legacyid": "@{outputs('Emp')?['LegacyId']}",
                                    "itemid": "@{outputs('Emp')?['Id']}", "roles": "@{outputs('Roles')}", "upn": "@{outputs('Trusted')}"},
                           "schema": {"type": "object", "properties": {k: {"title": k, "x-ms-dynamically-added": True, "type": "string"}
                                                                        for k in ["resultcode", "legacyid", "itemid", "roles", "upn"]}}}},
}
guard = base._fix(guard)
inits = {}
INPUTS = [("Text", "CallerUpn", "DECOY - logged, never trusted"), ("Text", "ClaimRole", "DECOY - logged, never trusted"),
          ("Text", "ClientRequestId", "caller correlation token")]
