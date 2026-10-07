"""Deployment target guard for the staging / demo solution (generic; the approved values come from private configuration).

check(manifest, environment, approved) -> [] or refusal reasons. A deployment (or readiness claim) for `environment`
is refused unless ALL hold:
  - the Power Platform environment is the approved one (exact display name, type Sandbox, never Default/Production/
    Developer/Teams), and the solution's publisher prefix is the approved staging prefix;
  - the environment marker variable (*_EnvironmentLabel) equals the approved label (e.g. STAGING), never PRODUCTION;
  - every site-URL variable (*_OpsSiteUrl) equals the approved site URL exactly (string equality; no root site, no
    other site, no trailing-slash or case variants);
  - no variable value for this environment contains a GUID (list GUIDs are resolved at run time by title).
approved: {"environmentName", "environmentType", "siteUrl", "environmentLabel", "prefix"}
"""
from __future__ import annotations

import re

_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
FORBIDDEN_TYPES = {"default", "production", "developer", "teams", "trial"}


def check(manifest: dict, environment: str, approved: dict, target_env: dict) -> list:
    """target_env: the environment actually selected for deployment {"displayName", "type", "isDefault"} (read-only)."""
    p = []
    if (target_env or {}).get("displayName") != approved.get("environmentName"):
        p.append("target environment %r is not the approved %r" % ((target_env or {}).get("displayName"), approved.get("environmentName")))
    t = str((target_env or {}).get("type") or "").lower()
    if (target_env or {}).get("isDefault") or t in FORBIDDEN_TYPES or t != str(approved.get("environmentType", "")).lower():
        p.append("target environment type %r is not allowed (approved %r; never Default / Production)" % (t, approved.get("environmentType")))
    prefix = str(((manifest.get("solution") or {}).get("publisher") or {}).get("customizationPrefix") or "")
    if prefix != approved.get("prefix"):
        p.append("publisher prefix %r is not the approved staging prefix" % prefix)
    for v in manifest.get("environmentVariables", []):
        name, val = v.get("schemaName", ""), (v.get("values") or {}).get(environment)
        if name.endswith("_EnvironmentLabel"):
            if val != approved.get("environmentLabel") or str(val).upper() == "PRODUCTION":
                p.append("%s = %r, expected %r" % (name, val, approved.get("environmentLabel")))
        if name.endswith("_OpsSiteUrl") and val != approved.get("siteUrl"):
            p.append("%s does not equal the approved site URL exactly" % name)
        if isinstance(val, str) and _GUID.search(val):
            p.append("%s holds a GUID (resolve lists by title at run time)" % name)
    if not any(v.get("schemaName", "").endswith("_OpsSiteUrl") for v in manifest.get("environmentVariables", [])):
        p.append("no site-URL variable declared")
    return p
