"""Deployment readiness after the service-identity decision (generic; no tenant data, no hard-coded account).

readiness(purpose, ...) -> (ready, blockers[(code, detail)]) for ENGINEERING | UAT | PRODUCTION. Refuses when:
  SERVICE_IDENTITY_MISSING      the approved service identity is not configured for the environment
  SERVICE_IDENTITY_TEMPORARY    the configured identity is a temporary/test account
  D3_OPERATIONAL_READINESS_INCOMPLETE  the configured identity does not yet meet a D-3 acceptance criterion (d3_acceptance)
  CONNECTION_REFERENCE_*        a required connection reference is missing, still gated, or owned by another account
  READ_PERMISSION_MISSING       the service identity lacks Read on a required list
  SECURITY_DRIFT                the service identity holds more than Read on a required list
  ENV_BINDING_UNRESOLVED        a required environment variable has no value for the environment (manifest_check)
  CONFIG_NOT_READY              AppSettings readiness for the purpose fails (interim values refused for UAT/PRODUCTION)
The identity comes only from environment configuration (overlay `external`); nothing is compared with a literal UPN.
"""
from __future__ import annotations

import os
import sys
from typing import Iterable, Mapping, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "config"))
sys.path.insert(0, HERE)
import app_settings as cfg  # noqa: E402
import d3_acceptance as d3  # noqa: E402
import manifest_check as mc  # noqa: E402

STRUCTURAL = {"Limited Access"}


def _matches(assignment: Mapping, upn: str) -> bool:
    login = str(assignment.get("login") or "").lower()
    return bool(upn) and (login == upn or login.endswith("|" + upn))


def readiness(purpose: str, *, environment: str, overlay: Mapping, registry: dict, manifest: dict, permissions: Mapping,
              required_lists: Iterable[str], required_settings: Iterable[str], required_connection_refs: Iterable[str],
              temporary_accounts: Iterable[str] = (), service_key: str = "ServiceAccountUpn",
              settings_rows: Optional[Iterable[Mapping]] = None, scope: Optional[str] = "r1",
              identity_acceptance: Optional[Mapping] = None) -> tuple:
    if purpose not in cfg.PURPOSES:
        raise ValueError("purpose must be one of %s" % (cfg.PURPOSES,))
    b = []
    upn = str(((overlay or {}).get("external") or {}).get(service_key) or "").strip().lower()
    temp = {t.lower() for t in temporary_accounts}
    if not upn:
        b.append(("SERVICE_IDENTITY_MISSING", "%s is not configured for %s" % (service_key, environment)))
    elif upn in temp or upn.split("@")[0] in temp:
        b.append(("SERVICE_IDENTITY_TEMPORARY", "the configured service identity is a temporary/test account"))
        upn = ""
    else:
        b += [("D3_OPERATIONAL_READINESS_INCOMPLETE", "%s: %s" % x) for x in d3.unmet(identity_acceptance)]
    refs = {r["schemaName"]: r for r in manifest.get("connectionReferences", [])}
    for name in required_connection_refs:
        r = refs.get(name)
        if r is None:
            b.append(("CONNECTION_REFERENCE_MISSING", name))
        elif r.get("gated"):
            b.append(("CONNECTION_REFERENCE_UNBOUND", "%s gated: %s" % (name, r.get("gatedBy"))))
        elif r.get("invokerOwned"):
            continue
        elif not upn or str(r.get("connectionOwner") or "").lower() != upn:
            b.append(("CONNECTION_REFERENCE_OWNER_MISMATCH", "%s is not owned by the approved service identity" % name))
    for lst in required_lists:
        snap = permissions.get(lst)
        if snap is None:
            b.append(("READ_PERMISSION_MISSING", "%s: no permission snapshot" % lst))
            continue
        mine = [a for a in snap.get("assignments", []) if _matches(a, upn)]
        roles = {r for a in mine for r in a.get("roles", [])} - STRUCTURAL
        if not upn or "Read" not in roles:
            b.append(("READ_PERMISSION_MISSING", lst))
        if roles - {"Read"}:
            b.append(("SECURITY_DRIFT", "%s: service holds %s" % (lst, "+".join(sorted(roles)))))
        if not snap.get("unique"):
            b.append(("SECURITY_DRIFT", "%s: list inherits site permissions" % lst))
    _, env_blockers = mc.readiness(manifest, environment.lower(), scope=scope)
    b += [("ENV_BINDING_UNRESOLVED", "%s: %s" % x) for x in env_blockers]
    ok, cb = cfg.readiness(registry, overlay, purpose, required_settings, settings_rows)
    b += [("CONFIG_NOT_READY", "%s: %s" % x) for x in cb]
    return (not b, b)
