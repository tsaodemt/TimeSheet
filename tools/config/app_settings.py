"""AppSettings: typed configuration registry with fail-closed resolution (generic; no tenant data in code).

    registry (JSON, per project)  +  environment overlay (JSON, per environment)  +  site rows (read-only)
      -> validate_registry() / validate_overlay() -> problems
      -> resolve()   -> Setting(status CONFIGURED | UNRESOLVED | INVALID, value, interim)
      -> gate()      -> dependent functionality is disabled unless every required setting is CONFIGURED
      -> readiness() -> per purpose (ENGINEERING / UAT / PRODUCTION): approved values only for UAT and PRODUCTION
      -> seed_rows() -> rows for the AppSettings list (Title = key); loaded with reference_data.apply_items

Rules:
- An unresolved setting is never replaced by a guess. `proposedDefault` is documentation; it is never applied.
- AppSettings hold non-secret, portable business configuration only. Secrets are refused. Tenant-bound bindings
  (site URLs, list/group IDs, domains, identities such as a service-account UPN) are ENVIRONMENT configuration
  (`externalConfig`: Power Platform environment variables / connection ownership), never AppSettings rows.
- One authoritative source per fact: a DERIVED setting (e.g. a UTC offset derived from the business time zone) has
  no value of its own; any stored value for it is ignored and reported.
- An INTERIM value (owner-approved engineering value while a customer decision is open) lives in the environment
  overlay, carries its basis, and is usable only where allowed (never PRODUCTION, never UAT/customer acceptance).
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONFIGURED, UNRESOLVED, INVALID = "CONFIGURED", "UNRESOLVED", "INVALID"
RESOLUTIONS = {"RESOLVED", "OPEN", "BLOCKED", "ENVIRONMENT-SPECIFIC", "CUSTOMER DECISION", "IT DECISION"}
APPROVED_RESOLUTIONS = {"RESOLVED", "ENVIRONMENT-SPECIFIC"}
TYPES = {"int", "decimal", "bool", "enum", "text", "iana_tz"}
EXTERNAL_TYPES = {"upn", "text", "url", "guid"}
PURPOSES = ("ENGINEERING", "UAT", "PRODUCTION")
CONFIG_UNRESOLVED, CONFIG_INVALID = "CONFIG_UNRESOLVED", "CONFIG_INVALID"
INTERIM_FIELDS = ("basis", "approvedBy", "approvedOn", "customerDecision", "allowedEnvironments")

_SECRET_KEY = re.compile(r"(secret|password|passwd|pwd|token|apikey|api_key|clientkey|connectionstring|sas|credential)", re.I)
_SECRET_VALUE = re.compile(r"(AccountKey=|SharedAccessSignature|sig=|Bearer\s|-----BEGIN|client_secret|password=)", re.I)
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_URL = re.compile(r"https?://", re.I)
_UPN = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


def _utc_offset_minutes(tz: str) -> int:
    now = _dt.datetime.now(_dt.timezone.utc)
    return int(now.astimezone(ZoneInfo(tz)).utcoffset().total_seconds() // 60)


DERIVATIONS = {"utcOffsetMinutes": _utc_offset_minutes}


@dataclass
class Setting:
    key: str
    status: str
    value: object = None
    detail: str = ""
    interim: bool = False
    basis: str = ""
    decision: str = ""


@dataclass
class Gate:
    enabled: bool
    code: str = "OK"
    missing: tuple = ()


def _parse(defn: dict, raw) -> tuple:
    """(value, error). Raw values come from a SharePoint text column, so strings are the normal input."""
    t = defn["type"]
    s = raw.strip() if isinstance(raw, str) else raw
    if t == "int":
        if isinstance(s, bool) or not re.fullmatch(r"-?\d+", str(s)):
            return None, "not an integer"
        v = int(s)
    elif t == "decimal":
        if isinstance(s, bool) or not re.fullmatch(r"-?\d+(\.\d+)?", str(s)):  # '.' only: no locale-dependent comma
            return None, "not a decimal (use '.')"
        v = float(s)
    elif t == "bool":
        m = {"true": True, "yes": True, "on": True, "false": False, "no": False, "off": False}
        if str(s).lower() not in m:
            return None, "not a boolean (Yes/No, On/Off, True/False)"
        v = m[str(s).lower()]
    elif t == "enum":
        hit = [a for a in defn["allowed"] if a.lower() == str(s).lower()]
        if not hit:
            return None, "not one of %s" % defn["allowed"]
        v = hit[0]
    elif t == "upn":
        v = str(s).lower()
        if not _UPN.match(v):
            return None, "not a UPN"
    elif t == "iana_tz":
        v = str(s)
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            return None, "not an IANA time zone name"
    else:
        v = str(s)
    if t in ("int", "decimal"):
        if defn.get("min") is not None and v < defn["min"]:
            return None, "below minimum %s" % defn["min"]
        if defn.get("max") is not None and v > defn["max"]:
            return None, "above maximum %s" % defn["max"]
    if t == "text":
        if _URL.search(v) or _GUID.search(v):
            return None, "URLs and IDs belong in environment variables, not AppSettings"
        if _SECRET_VALUE.search(v):
            return None, "looks like a secret"
    return v, None


def _external(registry: dict) -> dict:
    return {e["key"].lower(): e for e in registry.get("externalConfig", [])}


def validate_registry(registry: dict) -> list:
    """Static checks of the registry definition. Any problem must stop provisioning."""
    p = []
    seen = set()
    keys = {d.get("key", "") for d in registry["settings"]}
    ext = _external(registry)
    for d in registry["settings"]:
        k = d.get("key", "")
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", k):
            p.append("%s: key must be PascalCase ASCII" % k)
        if k.lower() in seen:
            p.append("%s: duplicate key (keys are case-insensitive in the list)" % k)
        seen.add(k.lower())
        if k.lower() in ext:
            p.append("%s: declared as environment configuration; it is not an AppSettings row" % k)
        if d.get("secret") or _SECRET_KEY.search(k):
            p.append("%s: secrets are never stored in AppSettings" % k)
        if d.get("type") == "upn":
            p.append("%s: identity bindings are environment configuration, not AppSettings" % k)
        elif d.get("type") not in TYPES:
            p.append("%s: unknown type %r" % (k, d.get("type")))
        if d.get("resolution") not in RESOLUTIONS:
            p.append("%s: resolution must be one of %s" % (k, sorted(RESOLUTIONS)))
        if d.get("type") == "enum" and not d.get("allowed"):
            p.append("%s: enum without allowed values" % k)
        der = d.get("derived")
        if der:
            if der.get("from") not in keys or der.get("function") not in DERIVATIONS:
                p.append("%s: derived from an unknown key or function" % k)
            if d.get("value") not in (None, "") or d.get("proposedDefault") not in (None, ""):
                p.append("%s: a derived setting has no value of its own (one authoritative source)" % k)
            continue
        if d.get("value") not in (None, ""):
            if d.get("type") in TYPES:
                _, err = _parse(d, d["value"])
                if err:
                    p.append("%s: value %s" % (k, err))
            if d.get("resolution") in ("OPEN", "BLOCKED") and not d.get("valueBasis"):
                p.append("%s: a value on an %s setting needs a recorded valueBasis" % (k, d["resolution"]))
        if d.get("environmentSpecific") and d.get("value") not in (None, ""):
            p.append("%s: environment-specific values belong in the environment overlay, not the shared registry" % k)
    for e in registry.get("externalConfig", []):
        if e.get("type") not in EXTERNAL_TYPES:
            p.append("%s: unknown external type %r" % (e.get("key"), e.get("type")))
        if e.get("value") not in (None, ""):
            p.append("%s: environment configuration has no value in the shared registry" % e.get("key"))
        if not e.get("where"):
            p.append("%s: external configuration must say where it lives" % e.get("key"))
    return p


def _overlay_parts(overlay) -> tuple:
    """(environment, values, external). Accepts an overlay document or a plain {key: value} mapping."""
    if overlay is None:
        return None, {}, {}
    if "values" in overlay or "environment" in overlay or "external" in overlay:
        return overlay.get("environment"), overlay.get("values") or {}, overlay.get("external") or {}
    return None, dict(overlay), {}


def validate_overlay(registry: dict, overlay: dict) -> list:
    p = []
    env, values, external = _overlay_parts(overlay)
    defs = {d["key"].lower(): d for d in registry["settings"]}
    ext = _external(registry)
    for k, v in values.items():
        d = defs.get(k.lower())
        if d is None:
            p.append("%s: %s" % (k, "environment configuration goes under 'external'" if k.lower() in ext else "unknown key"))
            continue
        if d.get("derived"):
            p.append("%s: derived setting cannot be set (one authoritative source)" % k)
        if isinstance(v, dict) and v.get("interim"):
            miss = [f for f in INTERIM_FIELDS if not v.get(f)]
            if miss:
                p.append("%s: interim value without %s" % (k, ", ".join(miss)))
            if env == "PRODUCTION" or "PRODUCTION" in (v.get("allowedEnvironments") or []):
                p.append("%s: an interim value is never permitted in PRODUCTION" % k)
            if env and env not in (v.get("allowedEnvironments") or []):
                p.append("%s: interim value not allowed in environment %s" % (k, env))
    for k, v in external.items():
        e = ext.get(k.lower())
        if e is None:
            p.append("%s: not declared as environment configuration" % k)
        elif v not in (None, "") and e["type"] == "upn" and not _UPN.match(str(v).lower()):
            p.append("%s: not a UPN" % k)
    return p


def resolve(registry: dict, overlay=None, site_rows: Optional[Iterable[Mapping]] = None) -> dict:
    """Effective settings. Precedence: site row (what the running app reads) > environment overlay > registry value.
    Missing or empty -> UNRESOLVED; unparsable -> INVALID. Derived settings are always computed from their source;
    stored values for them are ignored. Interim overlay values are UNRESOLVED outside their allowed environments."""
    env, values, _ = _overlay_parts(overlay)
    rows = {str(r.get("Title", "")).lower(): r.get("Value") for r in (site_rows or [])}
    out = {}
    derived = []
    for d in registry["settings"]:
        k = d["key"]
        if d.get("derived"):
            derived.append(d)
            continue
        ov = values.get(k)
        interim = isinstance(ov, dict) and bool(ov.get("interim"))
        ov_value = ov.get("value") if isinstance(ov, dict) else ov
        if interim and (env == "PRODUCTION" or env not in (ov.get("allowedEnvironments") or [])):
            out[k] = Setting(k, UNRESOLVED, None, "interim value not permitted in %s; %s" % (env, ov.get("customerDecision", "")))
            continue
        raw, src = rows.get(k.lower()), "site"
        if raw in (None, ""):
            raw, src = ov_value, "overlay"
        if raw in (None, "") and not d.get("environmentSpecific"):
            raw, src = d.get("value"), "registry"
        if raw in (None, ""):
            out[k] = Setting(k, UNRESOLVED, None, "%s (%s)" % (d.get("resolution"), d.get("decision", "no decision recorded")))
            continue
        v, err = _parse(d, raw)
        if err:
            out[k] = Setting(k, INVALID, None, err)
            continue
        is_interim = interim and _parse(d, ov_value)[0] == v
        out[k] = Setting(k, CONFIGURED, v, src, interim=is_interim, basis=ov.get("basis", "") if is_interim else "",
                         decision=ov.get("customerDecision", "") if is_interim else "")
    for d in derived:
        src = out.get(d["derived"]["from"])
        if src is None or src.status != CONFIGURED:
            out[d["key"]] = Setting(d["key"], UNRESOLVED, None, "derived from unresolved %s" % d["derived"]["from"])
        else:
            out[d["key"]] = Setting(d["key"], CONFIGURED, DERIVATIONS[d["derived"]["function"]](src.value),
                                    "derived from %s" % d["derived"]["from"], interim=src.interim)
    return out


def gate(settings: Mapping[str, Setting], *keys: str, allow_interim: bool = True) -> Gate:
    """Fail closed: the dependent function runs only if every key is CONFIGURED (and, if required, not interim)."""
    bad = [k for k in keys if k not in settings or settings[k].status != CONFIGURED
           or (settings[k].interim and not allow_interim)]
    if not bad:
        return Gate(True)
    code = CONFIG_INVALID if any(k in settings and settings[k].status == INVALID for k in bad) else CONFIG_UNRESOLVED
    return Gate(False, code, tuple(bad))


def readiness(registry: dict, overlay, purpose: str, required: Iterable[str],
              site_rows: Optional[Iterable[Mapping]] = None) -> tuple:
    """(ready, blockers). ENGINEERING accepts owner-approved interim values in their allowed environment.
    UAT and PRODUCTION accept only approved values (registry resolution RESOLVED / ENVIRONMENT-SPECIFIC, no interim),
    and every external configuration required for that purpose must be present."""
    if purpose not in PURPOSES:
        raise ValueError("purpose must be one of %s" % (PURPOSES,))
    env, _, external = _overlay_parts(overlay)
    blockers = [("overlay", x) for x in validate_overlay(registry, overlay or {})]
    if purpose == "PRODUCTION" and env != "PRODUCTION":
        blockers.append(("environment", "production readiness needs the PRODUCTION overlay (got %s)" % env))
    s = resolve(registry, overlay, site_rows)
    defs = {d["key"]: d for d in registry["settings"]}
    for k in required:
        st = s.get(k)
        if st is None or st.status != CONFIGURED:
            blockers.append((k, (st.status + ": " + st.detail) if st else "unknown key"))
        elif purpose != "ENGINEERING" and st.interim:
            blockers.append((k, "interim value (%s) is not approved for %s" % (st.basis, purpose)))
        elif purpose != "ENGINEERING" and not defs[k].get("derived") and defs[k].get("resolution") not in APPROVED_RESOLUTIONS:
            blockers.append((k, "decision not approved: %s (%s)" % (defs[k].get("resolution"), defs[k].get("decision", ""))))
    for e in registry.get("externalConfig", []):
        if purpose in (e.get("requiredFor") or []) and external.get(e["key"]) in (None, ""):
            blockers.append((e["key"], "environment configuration unset (%s; %s)" % (e.get("where"), e.get("decision", ""))))
    return (not blockers, blockers)


def plain(settings: Mapping[str, Setting]) -> dict:
    """{key: value} with None for anything not CONFIGURED (for consumers such as the audit RetentionPolicy)."""
    return {k: (s.value if s.status == CONFIGURED else None) for k, s in settings.items()}


def _text(v) -> str:
    return "Yes" if v is True else "No" if v is False else ("%g" % v if isinstance(v, float) else str(v))


def seed_rows(registry: dict, overlay=None) -> list:
    """One row per non-derived key. Unresolved keys get an empty Value (visible to administrators, still UNRESOLVED
    when read). An interim value is marked in its Description. Environment configuration is never seeded."""
    eff = resolve(registry, overlay)
    rows = []
    for d in registry["settings"]:
        if d.get("derived"):
            continue
        s = eff[d["key"]]
        desc = d.get("description", "")
        if s.interim:
            desc = ("[INTERIM: YES | %s | ENGINEERING ONLY: YES | UAT READY: NO | PRODUCTION READY: NO] " % (s.decision or "customer decision OPEN")) + desc
        rows.append({"Title": d["key"], "Value": _text(s.value) if s.status == CONFIGURED else "", "Description": desc})
    return rows


def drift(registry: dict, site_rows: Iterable[Mapping], overlay=None) -> list:
    """(key, finding) for administrator attention. Nothing is changed automatically."""
    out = []
    keys = {d["key"].lower(): d for d in registry["settings"]}
    ext = _external(registry)
    rows = list(site_rows)
    for r in rows:
        t = str(r.get("Title", "")).lower()
        if t in ext:
            out.append((r.get("Title"), "ENVIRONMENT-CONFIG stored as an AppSettings row (ignored; belongs in %s)" % ext[t].get("where")))
        elif t not in keys:
            out.append((r.get("Title"), "UNKNOWN-KEY (not in registry; ignored by the app)"))
        elif keys[t].get("derived") and r.get("Value") not in (None, ""):
            out.append((r.get("Title"), "DERIVED setting stored independently (ignored; derived from %s)" % keys[t]["derived"]["from"]))
    eff = resolve(registry, overlay, rows)
    expected = resolve(registry, overlay)
    for k, s in eff.items():
        if s.status == INVALID:
            out.append((k, "INVALID on site: " + s.detail))
        elif s.status == UNRESOLVED:
            out.append((k, "UNRESOLVED: " + s.detail))
        elif expected[k].status == CONFIGURED and expected[k].value != s.value:
            out.append((k, "DIFFERS from registry (site=%r registry=%r); site value is in effect" % (s.value, expected[k].value)))
        if s.interim:
            out.append((k, "INTERIM value in effect (%s)" % s.basis))
    return out
