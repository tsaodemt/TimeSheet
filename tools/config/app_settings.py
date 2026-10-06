"""AppSettings: typed configuration registry with fail-closed resolution (generic; no tenant data in code).

    registry (JSON, per project)  +  environment overlay (JSON, per environment)  +  site rows (read-only)
      -> validate_registry() -> problems (secrets, tenant identifiers, bad types, unknown keys)
      -> resolve()           -> Setting(status CONFIGURED | UNRESOLVED | INVALID, value)
      -> gate()              -> dependent functionality is disabled unless every required setting is CONFIGURED
      -> seed_rows()         -> rows for the AppSettings list (Title = key); loaded with reference_data.apply_items

Rules:
- An unresolved setting is never replaced by a guess. `proposedDefault` is documentation; it is never applied.
- AppSettings hold non-secret business configuration only. Secrets, credentials and connection strings are refused.
- Tenant-bound technical bindings (site URLs, list/group IDs, domains) belong in solution environment variables,
  not in AppSettings; values that look like URLs or GUIDs are refused unless the type explicitly allows them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

CONFIGURED, UNRESOLVED, INVALID = "CONFIGURED", "UNRESOLVED", "INVALID"
RESOLUTIONS = {"RESOLVED", "OPEN", "BLOCKED", "ENVIRONMENT-SPECIFIC", "CUSTOMER DECISION", "IT DECISION"}
TYPES = {"int", "decimal", "bool", "enum", "text", "upn", "iana_tz"}
CONFIG_UNRESOLVED, CONFIG_INVALID = "CONFIG_UNRESOLVED", "CONFIG_INVALID"

_SECRET_KEY = re.compile(r"(secret|password|passwd|pwd|token|apikey|api_key|clientkey|connectionstring|sas|credential)", re.I)
_SECRET_VALUE = re.compile(r"(AccountKey=|SharedAccessSignature|sig=|Bearer\s|-----BEGIN|client_secret|password=)", re.I)
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_URL = re.compile(r"https?://", re.I)
_UPN = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


@dataclass
class Setting:
    key: str
    status: str
    value: object = None
    detail: str = ""


@dataclass
class Gate:
    enabled: bool
    code: str = "OK"
    missing: tuple = ()


def _parse(defn: dict, raw) -> tuple:
    """(value, error). Raw values come from a SharePoint text column, so strings are the normal input."""
    t = defn["type"]
    s = raw.strip() if isinstance(raw, str) else raw
    try:
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
            allowed = defn["allowed"]
            hit = [a for a in allowed if a.lower() == str(s).lower()]
            if not hit:
                return None, "not one of %s" % allowed
            v = hit[0]
        elif t == "upn":
            v = str(s).lower()
            if not _UPN.match(v):
                return None, "not a UPN"
        elif t == "iana_tz":
            v = str(s)
            if not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z_+-]+)+|UTC", v):
                return None, "not an IANA time zone name"
        else:
            v = str(s)
    except (TypeError, ValueError) as e:  # pragma: no cover - defensive
        return None, str(e)
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


def validate_registry(registry: dict) -> list:
    """Static checks of the registry definition. Any problem must stop provisioning."""
    p = []
    seen = set()
    for d in registry["settings"]:
        k = d.get("key", "")
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", k):
            p.append("%s: key must be PascalCase ASCII" % k)
        if k.lower() in seen:
            p.append("%s: duplicate key (keys are case-insensitive in the list)" % k)
        seen.add(k.lower())
        if d.get("secret") or _SECRET_KEY.search(k):
            p.append("%s: secrets are never stored in AppSettings" % k)
        if d.get("type") not in TYPES:
            p.append("%s: unknown type %r" % (k, d.get("type")))
        if d.get("resolution") not in RESOLUTIONS:
            p.append("%s: resolution must be one of %s" % (k, sorted(RESOLUTIONS)))
        if d.get("type") == "enum" and not d.get("allowed"):
            p.append("%s: enum without allowed values" % k)
        if d.get("value") not in (None, ""):
            _, err = _parse(d, d["value"])
            if err:
                p.append("%s: value %s" % (k, err))
            if d.get("resolution") in ("OPEN", "BLOCKED") and not d.get("valueBasis"):
                p.append("%s: a value on an %s setting needs a recorded valueBasis" % (k, d["resolution"]))
        if d.get("environmentSpecific") and d.get("value") not in (None, ""):
            p.append("%s: environment-specific values belong in the environment overlay, not the shared registry" % k)
    return p


def resolve(registry: dict, overlay: Optional[Mapping[str, object]] = None,
            site_rows: Optional[Iterable[Mapping]] = None) -> dict:
    """Effective settings. Precedence: site row (what the running app reads) > environment overlay > registry value.
    Missing or empty -> UNRESOLVED; unparsable -> INVALID. Keys not in the registry are ignored (reported by drift())."""
    rows = {str(r.get("Title", "")).lower(): r.get("Value") for r in (site_rows or [])}
    out = {}
    for d in registry["settings"]:
        k = d["key"]
        raw = rows.get(k.lower())
        src = "site"
        if raw in (None, ""):
            raw, src = (overlay or {}).get(k), "overlay"
        if raw in (None, "") and not d.get("environmentSpecific"):
            raw, src = d.get("value"), "registry"
        if raw in (None, ""):
            out[k] = Setting(k, UNRESOLVED, None, "%s (%s)" % (d.get("resolution"), d.get("decision", "no decision recorded")))
            continue
        v, err = _parse(d, raw)
        out[k] = Setting(k, INVALID, None, err) if err else Setting(k, CONFIGURED, v, src)
    return out


def gate(settings: Mapping[str, Setting], *keys: str) -> Gate:
    """Fail closed: the dependent function runs only if every key is CONFIGURED."""
    bad = [k for k in keys if k not in settings or settings[k].status != CONFIGURED]
    if not bad:
        return Gate(True)
    code = CONFIG_INVALID if any(k in settings and settings[k].status == INVALID for k in bad) else CONFIG_UNRESOLVED
    return Gate(False, code, tuple(bad))


def plain(settings: Mapping[str, Setting]) -> dict:
    """{key: value} with None for anything not CONFIGURED (for consumers such as the audit RetentionPolicy)."""
    return {k: (s.value if s.status == CONFIGURED else None) for k, s in settings.items()}


def seed_rows(registry: dict, overlay: Optional[Mapping[str, object]] = None) -> list:
    """One row per key. Unresolved keys get an empty Value (visible to administrators, still UNRESOLVED when read)."""
    eff = resolve(registry, overlay)
    rows = []
    for d in registry["settings"]:
        s = eff[d["key"]]
        value = "" if s.status != CONFIGURED else ("Yes" if s.value is True else "No" if s.value is False else
                                                     ("%g" % s.value if isinstance(s.value, float) else str(s.value)))
        rows.append({"Title": d["key"], "Value": value, "Description": d.get("description", "")})
    return rows


def drift(registry: dict, site_rows: Iterable[Mapping], overlay: Optional[Mapping[str, object]] = None) -> list:
    """(key, finding) for administrator attention. Nothing is changed automatically."""
    out = []
    keys = {d["key"].lower(): d for d in registry["settings"]}
    rows = list(site_rows)
    for r in rows:
        if str(r.get("Title", "")).lower() not in keys:
            out.append((r.get("Title"), "UNKNOWN-KEY (not in registry; ignored by the app)"))
    eff = resolve(registry, overlay, rows)
    expected = resolve(registry, overlay)
    for k, s in eff.items():
        if s.status == INVALID:
            out.append((k, "INVALID on site: " + s.detail))
        elif s.status == UNRESOLVED:
            out.append((k, "UNRESOLVED: " + s.detail))
        elif expected[k].status == CONFIGURED and expected[k].value != s.value:
            out.append((k, "DIFFERS from registry (site=%r registry=%r); site value is in effect" % (s.value, expected[k].value)))
    return out
