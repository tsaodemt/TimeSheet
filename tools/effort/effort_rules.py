"""EPIC 16 Project Effort capability matrix and project-PM scope (R3 M2; OD-24, OD-37).

Role grants (company scope): EFF.ProjectView = Executive, PMO; EFF.ProjectPmAssign = PMO. EFF.ProjectEdit is granted to
no role (registered with scope "none" so the guard knows the action and answers ROLE_NOT_ALLOWED).

Project-PM scope grant (independent of role): the authoritative PM of a project (ProjectPmAssignments, resolved
server-side) gets EFF.ProjectView and EFF.ProjectEdit for that project only. App Administrator, IT Support and every
other role get nothing (technical privilege never implies business authority).
"""
from __future__ import annotations

VIEW, EDIT, ASSIGN = "EFF.ProjectView", "EFF.ProjectEdit", "EFF.ProjectPmAssign"
ROLES = ("EMP", "TL", "APR", "EXE", "PMO", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO")
ROLE_GRANTS = {VIEW: ("EXE", "PMO"), ASSIGN: ("PMO",), EDIT: ()}
ALLOW, ROLE_NOT_ALLOWED, SCOPE_NOT_ALLOWED = "ALLOW", "ROLE_NOT_ALLOWED", "SCOPE_NOT_ALLOWED"
PM_SCOPE = "project-pm"


def scope_config() -> dict:
    scopes = {r: {} for r in ROLES}
    for cap, roles in ROLE_GRANTS.items():
        for r in ROLES:
            scopes[r][cap] = "company" if r in roles else "none"
    return {"scopes": scopes, "pending": []}


def role_can(roles, capability) -> bool:
    return any(r in ROLE_GRANTS[capability] for r in roles)


def view_decision(base_code: str, is_pm_of_project: bool, is_pm_anywhere: bool) -> tuple:
    """(code, scope) for EFF.ProjectView on one project. Identity / config failures of the guard pass through."""
    if base_code == ALLOW:
        return ALLOW, "company"
    if base_code != ROLE_NOT_ALLOWED:
        return base_code, "none"
    if is_pm_of_project:
        return ALLOW, PM_SCOPE
    return (SCOPE_NOT_ALLOWED if is_pm_anywhere else ROLE_NOT_ALLOWED), "none"


def list_decision(base_code: str, is_pm_anywhere: bool) -> tuple:
    if base_code == ALLOW:
        return ALLOW, "company"
    if base_code != ROLE_NOT_ALLOWED:
        return base_code, "none"
    return (ALLOW, PM_SCOPE) if is_pm_anywhere else (ROLE_NOT_ALLOWED, "none")


def edit_decision(base_code: str, is_pm_of_project: bool) -> tuple:
    """EFF.ProjectEdit: only the project's PM; nobody by role (PMO / Executive included)."""
    if base_code not in (ALLOW, ROLE_NOT_ALLOWED):
        return base_code, "none"
    return (ALLOW, PM_SCOPE) if is_pm_of_project else (SCOPE_NOT_ALLOWED, "none")
