"""EPIC 17 Discipline Effort capability matrix (R3 M3, owner decision OD-46 2026-10-10; OD-17, OD-28).

EFF.DisciplineView:    EMP self, TL discipline, PMO company, EXE company; + project-PM grant (EPIC 16 authoritative PM, own projects).
EFF.DisciplineEdit:    EMP self, TL self (own Draft rows only).
EFF.DisciplineApprove: TL discipline (Chủ trì = Team Leader of the authoritative discipline, OD-17); self-approval allowed (OD-28,
                       EPIC 17 only — EPIC 07 TS.SelfApprove stays ungranted).
Approver, HR, Salary Viewer, Finance, App Administrator, IT Support, Confidential Owner, Migration Owner: none (an employee who
holds one of these roles keeps only the Employee rights of the SG-TS-STG-Employees group). No reopen capability (OD-18).
"""
from __future__ import annotations

VIEW, EDIT, APPROVE = "EFF.DisciplineView", "EFF.DisciplineEdit", "EFF.DisciplineApprove"
ROLES = ("EMP", "TL", "APR", "EXE", "PMO", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO")
GRANTS = {
    VIEW: {"EMP": "self", "TL": "discipline", "PMO": "company", "EXE": "company"},
    EDIT: {"EMP": "self", "TL": "self"},
    APPROVE: {"TL": "discipline"},
}
PM_SCOPE = "project-pm"
RANK = {"none": 0, "self": 1, "discipline": 2, PM_SCOPE: 3, "company": 4}


def scope_config() -> dict:
    scopes = {r: {} for r in ROLES}
    for cap, g in GRANTS.items():
        for r in ROLES:
            scopes[r][cap] = g.get(r, "none")
    return {"scopes": scopes, "pending": []}


def best_scope(roles, cap) -> str:
    s = "none"
    for r in roles:
        v = GRANTS[cap].get(r, "none")
        if RANK[v] > RANK[s]:
            s = v
    return s
