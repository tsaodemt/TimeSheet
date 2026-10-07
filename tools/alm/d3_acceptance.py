"""D-3 operational service identity: acceptance criteria (generic; no tenant data, no account names).

D-3 has two parts:
  identity selection        which existing or new account is the operational service identity (a project-owner / IT decision)
  operational readiness     the selected account meets every criterion below, each with recorded read-only evidence

evaluate(record) -> (status, unmet) where status is DONE when every criterion is met with evidence, else BLOCKED, and
unmet lists (criterion, description) in the order below. A criterion without evidence counts as unmet (fail closed).
The record comes from local evidence; the account itself is resolved only from environment configuration.
"""
from __future__ import annotations

from typing import Mapping, Optional

CRITERIA = (
    ("EXISTS", "account exists in the directory"),
    ("ENABLED", "account is enabled"),
    ("LICENSED", "licence covers the required standard connectors (SharePoint, Office 365 Users, Office 365 Groups)"),
    ("NO_ADMIN_ROLE", "no administrative directory role is required or assigned"),
    ("CAN_AUTHENTICATE", "account can authenticate under the current tenant policy (no bypass)"),
    ("CUSTODIAN_LIFECYCLE_DOCUMENTED", "named custodian and backup, credential rotation, compromise and retire procedure recorded"),
    ("RETAINED", "account is not scheduled for deletion by any cleanup"),
    ("CONNECTION_OWNERSHIP_POSSIBLE", "account can own the service connections (licence and environment allow it)"),
)
IDS = tuple(c for c, _ in CRITERIA)
DONE, BLOCKED = "DONE", "BLOCKED"


def unmet(record: Optional[Mapping]) -> list:
    crit = (record or {}).get("criteria") or {}
    out = []
    for cid, text in CRITERIA:
        c = crit.get(cid) or {}
        if not (c.get("met") is True and str(c.get("evidence") or "").strip()):
            out.append((cid, text))
    return out


def evaluate(record: Optional[Mapping]) -> tuple:
    u = unmet(record)
    return (DONE if not u else BLOCKED, u)
