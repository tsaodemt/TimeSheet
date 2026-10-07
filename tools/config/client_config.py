"""AppOpen client-configuration contract (generic; no tenant data).

Clients never read the AppSettings list. The AppOpen flow (service side) resolves the settings and returns only the
keys the registry marks `exposeToClient`, for a resolved, active employee:

    {"status": "OK" | "CONFIG_UNRESOLVED" | "CONFIG_INVALID", "settings": {key: value}, "interim": {key: decision},
     "missing": [keys]}

- Server-only settings (business time zone, retention, environment configuration, derived values, anything not
  marked) are never returned.
- A required client key that is unresolved or invalid -> the status says so and that key is absent; the UI shows
  the banner and the dependent function stays disabled (the server refuses anyway).
- An interim value is returned with its decision reference so the UI/test evidence can show it; readiness logic on
  the server still decides whether interim values are acceptable for the purpose.
- Nothing is returned when the identity was not resolved (AppOpen deny).
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

import app_settings as cfg

NEVER_CLIENT_TYPES = {"upn", "url", "guid"}


def validate_exposure(registry: dict) -> list:
    """Registry rules for exposeToClient: never derived, environment-specific, external or retention/secret-like keys."""
    p = []
    ext = {e["key"] for e in registry.get("externalConfig", [])}
    for d in registry["settings"]:
        if not d.get("exposeToClient"):
            continue
        k = d["key"]
        if d.get("derived") or d.get("environmentSpecific") or k in ext or d.get("type") in NEVER_CLIENT_TYPES:
            p.append("%s: not exposable to clients" % k)
        if "retention" in k.lower() or d.get("secret") or d.get("confidential"):
            p.append("%s: retention/secret/confidential settings are server-only" % k)
    return p


def client_config(registry: dict, overlay, site_rows: Optional[Iterable[Mapping]], *, identity_ok: bool) -> dict:
    if not identity_ok:
        return {"status": "DENIED", "settings": {}, "interim": {}, "missing": []}
    if validate_exposure(registry):
        return {"status": cfg.CONFIG_INVALID, "settings": {}, "interim": {}, "missing": []}
    eff = cfg.resolve(registry, overlay, site_rows)
    keys = [d["key"] for d in registry["settings"] if d.get("exposeToClient")]
    out, interim, missing, invalid = {}, {}, [], False
    for k in keys:
        s = eff[k]
        if s.status != cfg.CONFIGURED:
            missing.append(k)
            invalid |= s.status == cfg.INVALID
            continue
        out[k] = s.value
        if s.interim:
            interim[k] = s.decision or "interim"
    status = "OK" if not missing else (cfg.CONFIG_INVALID if invalid else cfg.CONFIG_UNRESOLVED)
    return {"status": status, "settings": out, "interim": interim, "missing": missing}
