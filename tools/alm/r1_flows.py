"""R1 flow set for the deployment manifest, derived from the generated templates (generic; no tenant data).

Every dependency listed here is read from the generated flow actions (connection references, lists and the HTTP
methods used on them, AppSettings keys, guard capability, identity lookup, audit event types, trigger inputs) — never
typed by hand — so the manifest cannot claim a dependency a flow does not use, or miss one it does.

    flows(registry, overlay)        -> [flow entry]   (the manifest "flows" section)
    analyze(actions)                -> dependencies of one generated flow
    sample_manifest(registry, ...)  -> publishable placeholder manifest for the R1 flow set

CLI: python r1_flows.py [--registry R.json] [--overlay O.json] [--write-manifest M.json]
     prints the flows section; --write-manifest replaces the "flows" section of a local manifest in place.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for d in ("powerautomate", "timesheet", "config", "identity", "audit"):
    sys.path.insert(0, os.path.join(HERE, "..", d))
import build_appstart_flow as baf  # noqa: E402
import build_r1_flows as r1  # noqa: E402

# Canonical list titles (target data model). Templates take them as parameters; the manifest maps each to its
# environment variable <PFX>_List_<Title>.
EMPLOYEES, AUDIT, SETTINGS = "Employees", "AuditLog", "AppSettings"
AUDIT_LISTS = {AUDIT}
REFERENCE_LISTS = {"Projects", "ProjectPhases", "Phases", "WorkTypes", "Shifts", "HourTypes", "ProjectAssignments"}
EVENT_TYPES = ("AppOpen", "IdentityRejected", "AuthorizationAllow", "AuthorizationDeny", "ReadProxy", "WriteProxy")
OWNERSHIP = {"<PFX>_CR_O365Users_Invoker": "INVOKER", "<PFX>_CR_SharePoint_OpsService": "SERVICE",
             "<PFX>_CR_O365Groups_OpsService": "SERVICE"}
PLACEHOLDER_SITE = "https://placeholder.invalid/sites/ops"  # build-time stand-in for <PFX>_OpsSiteUrl
PLACEHOLDER_DOMAIN = "placeholder.invalid"

# Minimal generic registry (keys and types only) used when no registry is supplied.
GENERIC_REGISTRY = {"settings": [
    {"key": "PayPeriodStartDay", "type": "int", "min": 1, "max": 28, "value": "26", "resolution": "RESOLVED", "exposeToClient": True},
    {"key": "MaxHoursPerEntryWarn", "type": "decimal", "value": "4", "resolution": "CUSTOMER DECISION", "exposeToClient": True},
    {"key": "MaxHoursPerDayWarn", "type": "decimal", "value": "12", "resolution": "CUSTOMER DECISION", "exposeToClient": True},
    {"key": "ProjectAssignmentScoping", "type": "enum", "allowed": ["Off", "On"], "value": None, "resolution": "CUSTOMER DECISION",
     "exposeToClient": True},
    {"key": "BusinessTimezone", "type": "iana_tz", "value": "Asia/Ho_Chi_Minh", "resolution": "RESOLVED"}],
    "externalConfig": [{"key": "ServiceAccountUpn", "type": "upn", "where": "environment variable", "requiredFor": ["UAT", "PRODUCTION"]}]}
GENERIC_OVERLAY = {"environment": "STAGING", "values": {}, "external": {}}

# Runtime facts no offline test can establish; each is checked on the first live run of the flow (docs/r1-first-live-checks.md).
FIRST_LIVE = {
    "V-LAZY": "flow results identical under lazy and eager if()/and()/or() (offline: 0 dependent expressions)",
    "V-INVOKER": "the invoker Users reference runs with the run-only user's own connection inside the solution",
    "V-SKIPPED": "actions('X') of a skipped action is readable null-safely (?[]) and reports status Skipped",
    "V-FAILONERROR": "a Compose whose date expression is invalid fails and is handled by its runAfter Failed branch",
    "V-ETAG": "odata.etag of the read-back after MERGE is the new ETag (not the one sent)",
}

TEMPLATES = {
    "TS-AppOpen": {"alias": "AppStart", "template": "tools/powerautomate/build_appstart_flow.py:appstart_actions",
                   "checks": ["V-LAZY", "V-INVOKER", "V-SKIPPED"]},
    "TS-ReadOwn": {"alias": "ReadOwn", "template": "tools/powerautomate/build_r1_flows.py:read_own_actions",
                   "checks": ["V-LAZY", "V-INVOKER", "V-SKIPPED", "V-FAILONERROR"]},
    "TS-SaveEntry": {"alias": "SaveEntry", "template": "tools/powerautomate/build_r1_flows.py:save_draft_actions",
                     "checks": ["V-LAZY", "V-INVOKER", "V-SKIPPED", "V-FAILONERROR", "V-ETAG"]},
}


def build(name, registry=None, overlay=None, role_groups=(("EMP", "<GROUP-ID>"),), scope_config=None):
    registry = registry or GENERIC_REGISTRY
    overlay = overlay or GENERIC_OVERLAY
    common = dict(site=PLACEHOLDER_SITE, domain=PLACEHOLDER_DOMAIN, emp_list=EMPLOYEES, audit_list=AUDIT,
                  environment=overlay.get("environment") or "<EnvironmentLabel>", registry=registry, overlay=overlay)
    if name == "TS-AppOpen":
        return baf.appstart_actions(**common)
    if scope_config is None:
        scope_config = {"scopes": {"EMP": {"TS.ViewOwn": "self", "TS.EditOwnDraft": "self"}}}
    guarded = dict(common, scope_config=scope_config, role_groups=list(role_groups), conf_audit_list="ConfidentialAuditLog")
    if name == "TS-ReadOwn":
        return r1.read_own_actions(**guarded)
    if name == "TS-SaveEntry":
        return r1.save_draft_actions(**guarded)
    raise ValueError(name)


def _walk(x, enclosing=()):
    """Yield (action name, action, enclosing If names) for every action, nested ones included."""
    for name, a in (x or {}).items():
        yield name, a, enclosing
        if a.get("type") in ("If", "Foreach", "Scope"):
            # an If whose condition is a setting value (X_<key>) makes what it contains conditional on configuration
            gate = re.findall(r"outputs\('X_(\w+)'\)", json.dumps(a.get("expression", "")))
            inner = enclosing + (tuple(gate) if a.get("type") == "If" else ())
            yield from _walk(a.get("actions"), inner)
            yield from _walk((a.get("else") or {}).get("actions"), inner)


def analyze(actions: dict) -> dict:
    refs, lists, settings, events, trig = {}, {}, set(), set(), set()
    guard_action, identity, conditional, guard_row = None, False, {}, False
    for name, a, enc in _walk(actions):
        blob = json.dumps(a, ensure_ascii=False)
        trig |= set(re.findall(r"triggerBody\(\)\?\['(text(?:_\d+)?)'\]", blob))
        if a.get("type") == "OpenApiConnection":
            host = a["inputs"]["host"]
            refs.setdefault(host["connectionReferenceLogicalName"], set()).add(host["operationId"])
            p = a["inputs"]["parameters"]
            m = re.search(r"getbytitle\('([^']*)'\)", p.get("parameters/uri", ""))
            if m:
                write = p.get("parameters/method") != "GET"
                lists.setdefault(m.group(1), set()).add("write" if write else "read")
                conditional.setdefault(m.group(1), set()).add(enc)
        if name.startswith("Q_") and a.get("type") == "Query" and "Settings_rows" in blob:
            settings.add(name[2:])
        if name == "ActionIn":
            m = re.search(r"'([A-Z]+\.[A-Za-z]+)'", blob)
            guard_action = m.group(1) if m else None
        if name == "Caller_lookup":
            identity = True
        if name == "Write_audit":
            guard_row = True  # the guard's own decision row
        if a.get("type") == "Compose" and isinstance(a.get("inputs"), dict) and "EventType" in a["inputs"]:
            events |= {e for e in EVENT_TYPES if e in json.dumps(a["inputs"]["EventType"])}
    cond = {lst: sorted(set(x for e in encs for x in e)) for lst, encs in conditional.items() if all(encs)}
    return {"connectionReferences": {k: sorted(v) for k, v in sorted(refs.items())},
            "lists": {k: sorted(v) for k, v in sorted(lists.items())},
            "conditionalLists": cond, "settings": sorted(settings), "guardAction": guard_action,
            "identityResolution": identity, "auditEvents": sorted(events), "guardDecisionRow": guard_row, "triggerInputs": sorted(trig, key=lambda t: int(t[5:] or 0))}


def env_vars(dep: dict) -> list:
    out = ["<PFX>_OpsSiteUrl", "<PFX>_AllowedDomains" if dep["identityResolution"] else None,
           "<PFX>_EnvironmentLabel" if dep["auditEvents"] else None,
           "<PFX>_RoleGroupMap" if "<PFX>_CR_O365Groups_OpsService" in dep["connectionReferences"] else None]
    return [x for x in out if x] + ["<PFX>_List_%s" % t for t in dep["lists"]]


def flow_entry(name, registry=None, overlay=None) -> dict:
    dep = analyze(build(name, registry, overlay))
    meta = TEMPLATES[name]
    ref_lists = sorted(set(dep["lists"]) & REFERENCE_LISTS)
    e = {"name": name, "alias": meta["alias"], "template": meta["template"], "r1": True, "deployed": False,
         "connectionReferences": [{"schemaName": k, "ownership": OWNERSHIP.get(k, "UNKNOWN"), "operations": v}
                                  for k, v in dep["connectionReferences"].items()],
         "environmentVariables": env_vars(dep),
         "lists": dep["lists"],
         "settings": ({"source": "registry keys with exposeToClient", "keys": dep["settings"]} if name == "TS-AppOpen"
                      else {"source": "server-side AppSettings", "keys": dep["settings"]}),
         "guard": {"capability": dep["guardAction"], "scope": "self"} if dep["guardAction"] else None,
         "identityResolution": dep["identityResolution"],
         "audit": {"lists": sorted(set(dep["lists"]) & AUDIT_LISTS), "events": dep["auditEvents"],
                   "guardDecisionRow": dep["guardDecisionRow"]},
         "referenceData": [{"list": lst, "required": "always" if lst not in dep["conditionalLists"]
                            else "when %s = On" % "/".join(dep["conditionalLists"][lst])} for lst in ref_lists],
         "triggerInputs": dep["triggerInputs"],
         "firstLiveChecks": meta["checks"]}
    if name == "TS-SaveEntry":
        e["createIdempotency"] = {"status": "INTERIM / NOT GUARANTEED", "decision": "R1-Q3 OPEN", "requestKey": False,
                                  "mitigation": ["app disables Save while a request is in flight", "WARN_DUPLICATE warning"],
                                  "exactlyOnce": False}
        e["etagReadback"] = {"onFailure": "ok=true, etag='', warnings += WARN_RELOAD_REQUIRED; client re-reads before the next edit",
                             "staleEtagReturned": False}
    if name == "TS-ReadOwn":
        e["dateSemantics"] = "half-open UTC interval from AppSettings.BusinessTimezone (no fixed offset); proven live by POC P4"
    return e


def flows(registry=None, overlay=None) -> list:
    return [flow_entry(n, registry, overlay) for n in TEMPLATES]


def sample_manifest(registry=None, overlay=None) -> dict:
    """Publishable placeholder manifest for the R1 flow set (what the environment-local manifest must bind)."""
    fl = flows(registry, overlay)
    used_refs = sorted({r["schemaName"] for f in fl for r in f["connectionReferences"]})
    used_vars = sorted({v for f in fl for v in f["environmentVariables"]})
    purpose = {"<PFX>_CR_O365Users_Invoker": "trusted caller identity (Get my profile V2) with the run-only user's own connection",
               "<PFX>_CR_SharePoint_OpsService": "service-side operational SharePoint reads and writes (proxy pattern)",
               "<PFX>_CR_O365Groups_OpsService": "live role-group membership checks in the guard"}
    connector = {"<PFX>_CR_O365Users_Invoker": "shared_office365users", "<PFX>_CR_SharePoint_OpsService": "shared_sharepointonline",
                 "<PFX>_CR_O365Groups_OpsService": "shared_office365groups"}
    refs = []
    for n in used_refs:
        inv = OWNERSHIP[n] == "INVOKER"
        refs.append({"schemaName": n, "connectorId": connector[n], "ownership": OWNERSHIP[n], "purpose": purpose[n], "r1": True,
                     "connectionOwner": "<run-only user>" if inv else "<ServiceAccountUpn>", "invokerOwned": inv,
                     "gated": not inv, **({} if inv else {"gatedBy": "D-3 (operational service identity)"})})
    return {"solution": {"publisher": {"customizationPrefix": "<PFX: TBD>", "decision": "ENV-D3"}},
            "environmentDecisions": {k: "<ENV-D3: TBD>" for k in ("environmentType", "region", "adminsMakers", "dlp", "publisher",
                                                                  "prefix", "hosting")},
            "environmentVariables": [{"schemaName": v, "type": "Text", "purpose": "R1 flow binding", "r1": True, "sourceDecision": "AD-8",
                                      "values": {"staging": "<TBD>"}} for v in used_vars],
            "connectionReferences": refs, "flows": fl, "firstLiveChecks": FIRST_LIVE}


if __name__ == "__main__":
    args = sys.argv[1:]

    def opt(k):
        return json.load(open(args[args.index(k) + 1], encoding="utf-8")) if k in args else None
    fl = flows(opt("--registry"), opt("--overlay"))
    if "--write-manifest" in args:
        path = args[args.index("--write-manifest") + 1]
        m = json.load(open(path, encoding="utf-8"))
        m["flows"], m["firstLiveChecks"] = fl, FIRST_LIVE
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=1, ensure_ascii=False)
        print("flows section written: %s" % ", ".join(f["name"] for f in fl))
    else:
        print(json.dumps(fl, indent=1, ensure_ascii=False))
