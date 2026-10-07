"""Architecture scope (project owner, FINAL): SharePoint is the only application data store; Dataverse is REJECTED.

Platform: Entra ID, Power Apps Canvas, Power Automate, SharePoint lists, Office 365 Users, Office 365 Groups.
No Dataverse (tables, database, capacity, pay-as-you-go), no model-driven apps, no Dynamics 365.

    SCOPE                         -> the decision (tests SD01, SD07, SD08)
    ALM                           -> every ALM item classified: WORKS_WITHOUT_DATAVERSE | DATAVERSE_DEPENDENT | NEEDS_LIVE_PROOF,
                                     with the SharePoint-only replacement for the staging demo (SD10)
    check_environment(env, approved)  -> refusals for a deployment target (SD03-SD05, SD07-SD09)
    check_artifacts(flows, app_text)  -> refusals for Dataverse connectors / solution-only bindings in artifacts (SD02, SD03)
    check_site(url, approved_url)     -> exact staging site URL (SD06)
"""
from __future__ import annotations

import json
import re

SCOPE = {"dataStore": "SharePoint", "dataverse": "REJECTED", "payAsYouGo": "OUT_OF_SCOPE", "capacityPurchase": "OUT_OF_SCOPE",
         "apps": "Canvas only", "connectors": ("shared_sharepointonline", "shared_office365users", "shared_office365groups"),
         "forbidden": ("Dataverse", "model-driven apps", "Dynamics 365")}

WORKS, DEPENDENT, PROOF = "WORKS_WITHOUT_DATAVERSE", "DATAVERSE_DEPENDENT", "NEEDS_LIVE_PROOF"
ALM = [
    ("solution", DEPENDENT, "none for the demo: non-solution ('My flows' / app) assets; the deployment pack is the unit of release"),
    ("publisher / prefix", DEPENDENT, "not used; names come from the pack (TS-AppOpen, TS-ReadOwn, TS-SaveEntry)"),
    ("environment variables", DEPENDENT, "build-time binding from private configuration compiled into the flow definitions "
                                         "(site URL, list titles, domain, role-group ids); business settings stay in SharePoint AppSettings"),
    ("connection references", DEPENDENT, "direct connections in the flows: SharePoint + Office 365 Groups owned by the service identity; "
                                         "Office 365 Users 'provided by run-only user' (invoker)"),
    ("deployment pipelines", DEPENDENT, "manual deployment checklist + pack builder + guards; export/import legacy packages"),
    ("managed solution promotion", DEPENDENT, "legacy package export (.zip) of flows and app, re-bound per environment by the pack builder"),
    ("canvas app (non-solution)", WORKS, "Power Apps YAML source pasted in Studio; SharePoint data sources; flows added to the app"),
    ("cloud flows (non-solution, Power Apps V2 trigger)", WORKS, "definitions from the generators; designer paste build"),
    ("connections (environment level)", WORKS, "created by interactive sign-in of the owning account (MFA by the user)"),
    ("run-only user connection ('provided by run-only user')", PROOF, "proven for non-solution flows in the spike; re-prove in the target "
                                                                       "environment (V-INVOKER first-live check)"),
    ("legacy package export/import of flows and app", PROOF, "used only if the app/flows must move; otherwise rebuilt from source"),
    ("environment without a Dataverse database (creation)", PROOF, "UI offers Sandbox with Database = No; whether creation is refused at "
                                                                    "0 MB tenant capacity is only known at Save"),
]

FORBIDDEN_TYPES = {"default", "production", "developer", "teams", "trial"}
_DATAVERSE_CONNECTORS = re.compile(r"shared_commondataservice(forapps)?|shared_dynamicscrm|Microsoft\.Dynamics|dataverse", re.I)


def check_environment(env: dict, approved: dict) -> list:
    """env (read-only facts of the selected target): {displayName, type, isDefault, hasDataverse, payAsYouGo}."""
    p = []
    if env.get("displayName") != approved.get("environmentName"):
        p.append("not the approved dedicated staging environment")
    t = str(env.get("type") or "").lower()
    if env.get("isDefault") or t in FORBIDDEN_TYPES or t != str(approved.get("environmentType", "")).lower():
        p.append("environment type %r refused (never Default / Production / Developer / Teams / Trial)" % t)
    if env.get("hasDataverse") is not False:
        p.append("Dataverse database present or unknown: refused (Dataverse is rejected)")
    if env.get("payAsYouGo") is not False:
        p.append("pay-as-you-go present or unknown: refused (out of scope)")
    if env.get("capacityPurchase"):
        p.append("capacity purchase is out of scope")
    return p


def check_artifacts(flows: dict, app_text: str = "") -> list:
    p = []
    for name, d in flows.items():
        s = json.dumps(d)
        if _DATAVERSE_CONNECTORS.search(s):
            p.append("%s uses a Dataverse connector" % name)
        if "connectionReferenceLogicalName" in s:
            p.append("%s uses solution connection references (Dataverse-backed)" % name)
        if re.search(r"environmentVariables|parameters\('[^']*\(\w+_\w+\)'\)", s):
            p.append("%s reads solution environment variables (Dataverse-backed)" % name)
        conns = set(re.findall(r'"connectionName": "([^"]+)"', s))
        if conns - set(SCOPE["connectors"]):
            p.append("%s uses connectors outside scope: %s" % (name, sorted(conns - set(SCOPE["connectors"]))))
    if _DATAVERSE_CONNECTORS.search(app_text or ""):
        p.append("app uses a Dataverse data source")
    return p


def check_site(url: str, approved_url: str) -> list:
    return [] if url == approved_url else ["site URL %r is not exactly the approved staging site" % url]
