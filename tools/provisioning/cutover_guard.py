"""DESIGN ONLY (not wired into schema_reconcile.apply): validation of a future production/cutover override for a target
that is an approved ROOT production site. The normal guard (schema_reconcile.guard_site) keeps refusing every root
site; nothing in this module changes that.

An override is acceptable only if ALL of these hold, checked before any call:
  1. explicit cutover mode;
  2. the exact approved production URL (no pattern, no trailing variants);
  3. a human approval record (approver, date/time, change reference);
  4. a fresh drift check of that exact site (inventory age within the limit) with 0 BLOCKED-INCOMPATIBLE;
  5. a dry run whose plan hash equals the plan hash the approver approved;
  6. an explicit typed confirmation naming the URL and the plan hash;
  7. an audit evidence record is produced (returned) for the run log.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

CUTOVER_MODE = "PRODUCTION-CUTOVER"
MAX_DRIFT_AGE = _dt.timedelta(minutes=60)


class CutoverRefused(Exception):
    pass


@dataclass(frozen=True)
class CutoverApproval:
    mode: str
    approved_url: str
    approver: str
    approved_at: str          # ISO UTC
    change_reference: str
    approved_plan_hash: str


def plan_hash(plan: Iterable) -> str:
    """Stable hash of a plan (list, field, operation, value)."""
    norm = [[l, f, op, v if not isinstance(v, dict) else v.get("internalName") or v.get("title")] for l, f, (op, v) in plan]
    return hashlib.sha256(json.dumps(norm, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def confirmation_text(url: str, phash: str) -> str:
    return "PROVISION %s PLAN %s" % (url, phash[:12])


def validate_cutover(site_url: str, approval: CutoverApproval, *, drift_findings: list, drift_checked_at: str,
                     drift_site_url: str, dry_run_plan: list, confirmation: str, now: str) -> dict:
    """Return the audit evidence record, or raise CutoverRefused with every failed condition."""
    fails = []
    t_now = _dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    if approval.mode != CUTOVER_MODE:
        fails.append("not in explicit cutover mode")
    if not approval.approved_url or site_url != approval.approved_url:
        fails.append("target is not the exact approved URL")
    if not (approval.approver and approval.approved_at and approval.change_reference):
        fails.append("human approval record incomplete")
    if drift_site_url != site_url:
        fails.append("drift check was not taken on the target site")
    try:
        age = t_now - _dt.datetime.fromisoformat(drift_checked_at.replace("Z", "+00:00"))
        if age < _dt.timedelta(0) or age > MAX_DRIFT_AGE:
            fails.append("drift check not fresh (%s)" % age)
    except ValueError:
        fails.append("drift check time invalid")
    if any(getattr(f, "status", "") == "BLOCKED-INCOMPATIBLE" for f in drift_findings):
        fails.append("incompatible drift present")
    ph = plan_hash(dry_run_plan)
    if ph != approval.approved_plan_hash:
        fails.append("dry-run plan differs from the approved plan")
    if confirmation != confirmation_text(site_url, ph):
        fails.append("explicit confirmation missing or wrong")
    if fails:
        raise CutoverRefused("; ".join(fails))
    return {"event": "ProvisioningCutoverOverride", "site": site_url, "approver": approval.approver,
            "approvedAt": approval.approved_at, "changeReference": approval.change_reference, "planHash": ph,
            "operations": len(dry_run_plan), "driftCheckedAt": drift_checked_at, "validatedAt": now}
