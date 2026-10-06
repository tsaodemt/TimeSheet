"""Reference implementation of server-side data scoping (self / discipline / company) and optional
project-assignment scoping. Used by guard flows after identity resolution (identity_resolver.resolve).

Scope per action comes from configuration (the role catalogue), never from the request. Values not
yet decided by the customer are passed in as configuration and default to the most restrictive choice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

SELF, DISCIPLINE, COMPANY, NONE = "self", "discipline", "company", "none"
_RANK = {NONE: 0, SELF: 1, DISCIPLINE: 2, COMPANY: 3}


@dataclass(frozen=True)
class Target:
    employee_legacy_id: str
    discipline_id: Optional[object]
    project_id: Optional[object] = None


def effective_scope(roles: Sequence[str], action: str, scope_table: Mapping[str, Mapping[str, str]]) -> str:
    """Most permissive scope across the caller's roles for one action; unknown role/action -> none."""
    best = NONE
    for r in roles:
        s = scope_table.get(r, {}).get(action, NONE)
        if _RANK.get(s, 0) > _RANK[best]:
            best = s
    return best


def allowed(resolution, action: str, target: Target, scope_table, *,
            project_assignment_scoping: bool = False,
            assigned_projects: Iterable[object] = (),
            exempt_roles: Sequence[str] = ()) -> bool:
    """Fail closed: no resolved identity, unknown action or out-of-scope target -> False."""
    if resolution is None or not getattr(resolution, "ok", False) or resolution.employee is None:
        return False
    scope = effective_scope(resolution.roles, action, scope_table)
    me = resolution.employee
    if scope not in (SELF, DISCIPLINE, COMPANY):
        return False
    if scope == SELF and target.employee_legacy_id != me.legacy_id:
        return False
    if scope == DISCIPLINE and (me.discipline_id is None or target.discipline_id != me.discipline_id):
        return False
    if project_assignment_scoping and target.project_id is not None \
            and not any(r in exempt_roles for r in resolution.roles):
        if target.project_id not in set(assigned_projects):
            return False
    return True
