"""SharePoint-only demo deployment pack (no Dataverse: no solution, no environment variables, no connection references).

build(config, out_dir) compiles the three R1 flows with the environment binding taken from PRIVATE configuration
(site URL, tenant domain, list titles, role-group ids, environment label) and plain connections (SharePoint and Office 365
Groups owned by the service identity; Office 365 Users provided by the run-only user), plus the Canvas app source, and a
pack manifest. It refuses to build unless the site URL equals the approved staging site exactly and the label is not
PRODUCTION. Business settings stay in SharePoint AppSettings (read at run time by the flows).

config: {"siteUrl", "approvedSiteUrl", "domain", "environmentLabel", "roleGroups": [[key, groupObjectId]],
         "approvalRoleGroups": [[key, groupObjectId]] (optional, S07.2: TL / APR / EXE),
         "registry": {...}, "overlay": {...}}  — never committed (tenant values).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for d in ("..\\powerautomate", "..\\config", "..\\powerapp", "."):
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, d)))
import architecture_scope as scope  # noqa: E402
import build_appstart_flow as baf  # noqa: E402
import build_approval_flows as apf  # noqa: E402
import build_r1_flows as r1  # noqa: E402
import build_read_flow as base  # noqa: E402

LISTS = {"emp_list": "Employees", "audit_list": "AuditLog"}
PLAIN = {base.SP: base.SP, base.USERS: base.USERS, base.GROUPS: base.GROUPS}
SCOPE_CONFIG = {"scopes": {"EMP": {"TS.ViewOwn": "self", "TS.EditOwnDraft": "self"}}}


class PackRefused(Exception):
    pass


def _plain(x):
    """Solution binding -> plain connection key (non-solution flows)."""
    if isinstance(x, dict):
        if x.get("type") == "OpenApiConnection":
            host = dict(x["inputs"]["host"])
            host["connectionName"] = host.pop("connectionReferenceLogicalName", host.get("connectionName"))
            x = dict(x, inputs=dict(x["inputs"], host=host))
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x


def add_site_guard(actions: dict, approved_url: str) -> dict:
    """Insert Site_guard right after SiteUrl: if SiteUrl is not exactly the approved staging site (e.g. edited in the
    designer to the root site), the run terminates SITE_NOT_ALLOWED before any SharePoint call. Every action that ran
    after SiteUrl now runs after the guard."""
    g = dict(actions)
    if "SiteUrl" not in g:
        raise PackRefused("flow has no SiteUrl binding")
    lit = approved_url.replace("'", "''")
    for name, a in list(g.items()):
        if "SiteUrl" in (a.get("runAfter") or {}):
            g[name] = dict(a, runAfter={"Site_guard": ["Succeeded"]})
    g["Site_guard"] = {"type": "If", "runAfter": {"SiteUrl": ["Succeeded"]},
                       "expression": {"equals": ["@outputs('SiteUrl')", lit]},
                       "actions": {}, "else": {"actions": {"Refuse_site": {"type": "Terminate", "runAfter": {}, "inputs": {
                           "runStatus": "Failed", "runError": {"code": "SITE_NOT_ALLOWED", "message": "SharePoint target is not the approved staging site"}}}}}}
    return g


def flows(config: dict) -> dict:
    bad = scope.check_site(config.get("siteUrl"), config.get("approvedSiteUrl"))
    if bad:
        raise PackRefused("; ".join(bad))
    if str(config.get("environmentLabel", "")).upper() in ("", "PROD", "PRODUCTION"):
        raise PackRefused("environment label must be the staging label")
    common = dict(site=config["siteUrl"], domain=config["domain"], environment=config["environmentLabel"],
                  registry=config["registry"], overlay=config["overlay"], refs=PLAIN, **LISTS)
    guarded = dict(common, scope_config=SCOPE_CONFIG, role_groups=[tuple(x) for x in config["roleGroups"]], conf_audit_list="ConfidentialAuditLog")
    out = {"TS-AppOpen": baf.appstart_actions(**common), "TS-ReadOwn": r1.read_own_actions(**guarded),
           "TS-SaveEntry": r1.save_draft_actions(**guarded)}
    if config.get("approvalRoleGroups"):
        # S07.2: TS-Approve / TS-ReadTeam (capability TS.Approve; Team Leader, Approver and Executive groups)
        approval = dict(common, role_groups=[tuple(x) for x in config["approvalRoleGroups"]], conf_audit_list="ConfidentialAuditLog")
        out["TS-ReadTeam"] = apf.read_team_actions(**approval)
        out["TS-Approve"] = apf.approve_actions(**approval)
    out = {k: add_site_guard(_plain(v), config["approvedSiteUrl"]) for k, v in out.items()}
    p = scope.check_artifacts(out)
    if p:
        raise PackRefused("; ".join(p))
    return out


def build(config: dict, out_dir: str) -> dict:
    import build_demo_app as app
    fl = flows(config)
    os.makedirs(out_dir, exist_ok=True)
    files = {}
    for name, d in fl.items():
        p = os.path.join(out_dir, name + ".actions.json")
        json.dump(d, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        files[name] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    app_files = app.build(os.path.join(out_dir, "app"))
    sites = sorted({d["SiteUrl"]["inputs"] for d in fl.values()} | {u for d in fl.values() for u in _uris(d)})
    manifest = {"architecture": scope.SCOPE, "site": config["siteUrl"], "sitesReferenced": sites, "flows": files,
                "app": [os.path.basename(f) for f in app_files], "connections": {
                    "shared_sharepointonline": "service identity (interactive sign-in by its custodian)",
                    "shared_office365groups": "service identity", "shared_office365users": "provided by run-only user"}}
    if sites != [config["siteUrl"]]:
        raise PackRefused("flows reference a site other than the approved staging site: %s" % sites)
    json.dump(manifest, open(os.path.join(out_dir, "PACK-MANIFEST.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return manifest


def _uris(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "dataset" and isinstance(v, str) and v.startswith("http"):
                yield v
            yield from _uris(v)
    elif isinstance(x, list):
        for v in x:
            yield from _uris(v)
