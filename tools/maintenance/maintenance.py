"""Guarded, audited maintenance of protected configuration and master/reference data (D-6). Reference implementation
(executable specification; no tenant data). A maintenance flow runs: trusted caller -> guard -> this validation ->
service operation -> audit row. Nobody edits the lists directly.

    maintain(guard_result, request, policy=..., current=..., registry=..., overlay=...) -> MaintResult
        .ok / .code      decision (codes below)
        .operation       the single service-side operation to execute (None when refused)
        .audit           the AdminMaintenance audit event (always produced, also for refusals)

Fail closed everywhere: unknown target, operation, field, key, value, decision state or environment -> refused.
Request fields that claim identity, role or scope are never read; their names are recorded.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Mapping, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
for p in ("config", "audit", "identity"):
    sys.path.insert(0, os.path.join(HERE, "..", p))
import app_settings as cfg  # noqa: E402
import audit_event as ae  # noqa: E402

OK = "OK"
FORBIDDEN, UNKNOWN_TARGET, OPERATION_NOT_ALLOWED = "FORBIDDEN", "UNKNOWN_TARGET", "OPERATION_NOT_ALLOWED"
HARD_DELETE_FORBIDDEN, FIELD_NOT_ALLOWED, VALIDATION = "HARD_DELETE_FORBIDDEN", "FIELD_NOT_ALLOWED", "VALIDATION"
NOT_FOUND, CONFLICT, DECISION_PENDING = "NOT_FOUND", "CONFLICT", "DECISION_PENDING"
INTERIM_PROTECTED, DERIVED_READONLY, ENVIRONMENT_CONFIG = "INTERIM_PROTECTED", "DERIVED_READONLY", "ENVIRONMENT_CONFIG"
ENVIRONMENT_RULE, SELF_MODIFICATION = "ENVIRONMENT_RULE", "SELF_MODIFICATION"
UNTRUSTED = {"actorupn", "actor", "callerupn", "employeeid", "employeeitemid", "role", "roles", "scope", "author", "editor", "ownerupn"}
OPS = ("Create", "Update", "SoftDelete")
REDACTED = "<redacted: rejected value>"


@dataclass
class MaintResult:
    ok: bool
    code: str
    operation: Optional[dict] = None
    audit: Optional[object] = None
    ignored: list = field(default_factory=list)
    detail: str = ""


def _audit(guard_result, target, admin_action, code, change, environment, item_key, source_flow):
    return ae.operation_event(guard_result, "AdminMaintenance", admin_action, target_entity=target, target_id=item_key or "",
                              source_flow=source_flow, environment=environment, outcome_code=None if code == OK else code,
                              change=change)


def maintain(guard_result, request: Mapping, *, policy: Mapping, current: Optional[Mapping], etag: str = "",
             registry: Optional[Mapping] = None, overlay: Optional[Mapping] = None, environment: str = "",
             source_flow: str = "MD-Maintain") -> MaintResult:
    target = str(request.get("Target") or "")
    op = str(request.get("Operation") or "")
    values = dict(request.get("Values") or {})
    ignored = sorted(k for k in list(request) + list(values) if k.lower() in UNTRUSTED)
    for k in list(values):
        if k.lower() in UNTRUSTED:
            values.pop(k)
    pol = policy.get(target)
    admin_action = (pol or {}).get("auditAction", "MasterDataChange")
    key = str(request.get("Key") or "")

    def done(ok, code, operation=None, change=None, detail=""):
        return MaintResult(ok, code, operation, _audit(guard_result, target or "(unknown)", admin_action, code, change, environment,
                                                       key, source_flow), ignored, detail)

    # 1. guard decision for exactly the action this target requires (trusted identity only)
    if pol is None:
        return done(False, UNKNOWN_TARGET)
    if guard_result is None or not guard_result.allowed or guard_result.RequestedAction != pol["action"]:
        return done(False, guard_result.ResultCode if guard_result is not None and not guard_result.allowed else FORBIDDEN)
    # 2. operation
    if op == "Delete":
        return done(False, HARD_DELETE_FORBIDDEN, detail="business deletion is soft delete (D-7); the service never holds Delete")
    if op not in OPS or op not in pol["operations"]:
        return done(False, OPERATION_NOT_ALLOWED)
    if op != "Create" and current is None:
        return done(False, NOT_FOUND)
    if op != "Create" and (not etag or str(request.get("ETag") or "") != etag):
        return done(False, CONFLICT)
    if op == "SoftDelete":
        fld = pol.get("softDelete")
        if not fld:
            return done(False, OPERATION_NOT_ALLOWED)
        values = {fld: False}
    bad = sorted(set(values) - set(pol["fields"]))
    if bad:
        return done(False, FIELD_NOT_ALLOWED, detail=", ".join(bad))
    if not values:
        return done(False, VALIDATION, detail="no change")
    # 3. target-specific rules
    rule = pol.get("kind")
    if rule == "config":
        return _config(done, key, values, current, registry, overlay, environment, target, etag)
    for f, why in (pol.get("decisionFields") or {}).items():
        if f in values and (current is None or values[f] != current.get(f)):
            return done(False, DECISION_PENDING, change={f: {"requested": values[f]}}, detail=why)
    if rule == "employee":
        caller = (guard_result.AuthenticatedUpn or "").lower()
        if current is not None and str(current.get("AccountUpn") or "").lower() == caller and set(values) & {"AccountUpn", "IsActive"}:
            return done(False, SELF_MODIFICATION)
    for f, check in (pol.get("invariants") or {}).items():
        if f in values:
            err = check(values, current, registry, overlay)
            if err:
                return done(False, VALIDATION, change={f: {"requested": values[f]}}, detail=err)
    change = {f: {"old": (current or {}).get(f), "new": v} for f, v in values.items()}
    operation = {"list": target, "operation": op, "key": key, "set": values, "ifMatch": etag if op != "Create" else ""}
    return done(True, OK, operation, change)


def _config(done, key, values, current, registry, overlay, environment, target, etag):
    if set(values) != {"Value"}:
        return done(False, FIELD_NOT_ALLOWED, detail="only Value is maintainable; decision metadata is not")
    defs = {d["key"]: d for d in (registry or {}).get("settings", [])}
    ext = {e["key"] for e in (registry or {}).get("externalConfig", [])}
    if key in ext:
        return done(False, ENVIRONMENT_CONFIG, detail="environment configuration is not an AppSettings row")
    d = defs.get(key)
    if d is None or current is None:
        return done(False, NOT_FOUND)
    if d.get("derived"):
        return done(False, DERIVED_READONLY, detail="derived from %s" % d["derived"]["from"])
    _, ov_values, _ = cfg._overlay_parts(overlay)
    ov = ov_values.get(key)
    if isinstance(ov, dict) and ov.get("interim"):
        return done(False, INTERIM_PROTECTED, detail="%s; replace explicitly through the decision record" % ov.get("customerDecision", ""))
    if d.get("resolution") not in cfg.APPROVED_RESOLUTIONS:
        return done(False, DECISION_PENDING, detail="%s (%s)" % (d.get("resolution"), d.get("decision", "")))
    if d.get("environmentSpecific"):
        return done(False, ENVIRONMENT_RULE, detail="environment-specific values come only from the environment overlay")
    v, err = cfg._parse(d, values["Value"])
    if err:
        return done(False, VALIDATION, change={"Value": {"old": current.get("Value"), "new": REDACTED}}, detail=err)
    text = cfg._text(v)
    change = {"Value": {"old": current.get("Value"), "new": text}}
    return done(True, OK, {"list": target, "operation": "Update", "key": key, "set": {"Value": text}, "ifMatch": etag}, change)
