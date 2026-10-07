"""Solution deployment-manifest checks (generic; no tenant data in code).

A manifest lists the solution's environment variables and connection references with per-environment values:

    {"environmentVariables": [{"schemaName", "type", "purpose", "r1", "sourceDecision", "gated", "gatedBy",
                               "values": {"<env>": "<value or <placeholder>>"}}],
     "connectionReferences": [{"schemaName", "connectorId", "connectionOwner", "purpose", "r1", "gated", "gatedBy"}]}

- lint(manifest, publishable=True)  -> problems. A publishable manifest (source control) holds placeholders only:
                                       no URLs with real hosts, no GUIDs, no e-mail addresses.
- readiness(manifest, env, scope)   -> (ready, blockers). Ready only when every in-scope variable has a real value for
                                       the environment and nothing in scope is gated. Fails closed.
"""
from __future__ import annotations

import re
from typing import Optional

PLACEHOLDER = re.compile(r"^<[^<>]+>$")
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_URL = re.compile(r"https?://(?!<)[^\s/]+", re.I)
_MAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]{2,}")
_SECRET = re.compile(r"(secret|password|token|apikey|connectionstring)", re.I)
SCHEMA = re.compile(r"^(<PFX>|[a-z][a-z0-9]{1,7})_[A-Za-z][A-Za-z0-9_]*$")


def is_placeholder(v) -> bool:
    return isinstance(v, str) and bool(PLACEHOLDER.match(v.strip()))


def lint(manifest: dict, publishable: bool = True) -> list:
    p = []
    seen = set()
    for kind in ("environmentVariables", "connectionReferences"):
        for x in manifest.get(kind, []):
            n = x.get("schemaName", "")
            if not SCHEMA.match(n):
                p.append("%s: schema name must be <prefix>_Name" % n)
            if n.lower() in seen:
                p.append("%s: duplicate schema name" % n)
            seen.add(n.lower())
            if _SECRET.search(n):
                p.append("%s: secrets are not environment variables here (use a secret store / connection)" % n)
            for f in ("purpose", "sourceDecision") if kind == "environmentVariables" else ("purpose", "connectorId"):
                if not x.get(f):
                    p.append("%s: %s missing" % (n, f))
            if x.get("gated") and not x.get("gatedBy"):
                p.append("%s: gated without gatedBy" % n)
            if kind == "connectionReferences" and not x.get("connectionOwner"):
                p.append("%s: connection owner missing (service identity required)" % n)
            if publishable:
                vals = list((x.get("values") or {}).values()) + [x.get("connectionOwner") or ""]
                for v in vals:
                    s = str(v)
                    if is_placeholder(s) or not s:
                        continue
                    if _URL.search(s) or _GUID.search(s) or _MAIL.search(s):
                        p.append("%s: tenant-specific value in a publishable manifest" % n)
    refs = {x.get("schemaName"): x for x in manifest.get("connectionReferences", [])}
    names = {x.get("schemaName") for x in manifest.get("environmentVariables", [])}
    for f in manifest.get("flows", []):
        fn = f.get("name", "?")
        for r in f.get("connectionReferences", []):
            d = refs.get(r["schemaName"])
            if d is None:
                p.append("%s: connection reference %s not declared" % (fn, r["schemaName"]))
            elif r.get("ownership") not in ("INVOKER", "SERVICE", "APP_USER"):
                p.append("%s: %s ownership must be INVOKER, SERVICE or APP_USER" % (fn, r["schemaName"]))
            elif (d.get("ownership") or ("INVOKER" if d.get("invokerOwned") else None)) != r["ownership"]:
                p.append("%s: %s declared ownership differs from the flow's %s" % (fn, r["schemaName"], r["ownership"]))
        for v in f.get("environmentVariables", []):
            if v not in names:
                p.append("%s: environment variable %s not declared" % (fn, v))
        if publishable and (_URL.search(str(f)) or _GUID.search(str(f)) or _MAIL.search(str(f))):
            p.append("%s: tenant-specific value in a publishable manifest" % fn)
    return p


def readiness(manifest: dict, env: str, scope: Optional[str] = "r1") -> tuple:
    """(ready, blockers) for deploying `scope` (r1 or None = everything) into `env`."""
    blockers = []
    for x in manifest.get("environmentVariables", []):
        if scope == "r1" and not x.get("r1"):
            continue
        v = (x.get("values") or {}).get(env)
        if x.get("gated"):
            blockers.append((x["schemaName"], "gated: " + str(x.get("gatedBy"))))
        elif v in (None, "") or is_placeholder(str(v)):
            blockers.append((x["schemaName"], "no value for %s" % env))
    for x in manifest.get("connectionReferences", []):
        if scope == "r1" and not x.get("r1"):
            continue
        if x.get("gated"):
            blockers.append((x["schemaName"], "gated: " + str(x.get("gatedBy"))))
        elif x.get("invokerOwned"):
            continue  # "provided by run-only user": the caller's own connection, deliberately not a service owner
        elif is_placeholder(str(x.get("connectionOwner") or "")) or not x.get("connectionOwner"):
            blockers.append((x["schemaName"], "connection owner not assigned"))
    if "<PFX>" in str([x.get("schemaName") for k in ("environmentVariables", "connectionReferences") for x in manifest.get(k, [])]):
        blockers.append(("publisher", "publisher prefix not decided"))
    return (not blockers, blockers)
