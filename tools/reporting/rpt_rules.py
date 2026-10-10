"""M4 current-scope report capability matrix (R3, owner decisions 2026-10-10: OD-50, OD-31; derived from OD-37 / OD-46 / OD-24).

RPT.ProjectView    : PMO, EXE, APR company (APR = Quản lý phòng for M4 reporting only, OD-31) + project-PM grant (own projects).
RPT.DisciplineView : PMO, EXE, APR company; TL discipline (own authoritative discipline) + project-PM grant (own projects).
Employee, HR, Salary Viewer, Finance, App Administrator, IT Support, Confidential Owner, Migration Owner: none.
Grants are additive (union of rows). A report capability never grants a write capability or direct list access; the OD-31 mapping
changes no M2 / M3 / EPIC 07 / Timesheet right. The M1 registered column is returned only to REG.View holders (OD-05, OD-52).
"""
from __future__ import annotations

PROJECT, DISCIPLINE = "RPT.ProjectView", "RPT.DisciplineView"
ROLES = ("EMP", "TL", "APR", "EXE", "PMO", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO")
GRANTS = {
    PROJECT: {"PMO": "company", "EXE": "company", "APR": "company"},
    DISCIPLINE: {"PMO": "company", "EXE": "company", "APR": "company", "TL": "discipline"},
}
COMPANY_ROLES = ("PMO", "EXE", "APR")
REG_VIEW_ROLES = ("TL", "APR", "EXE", "PMO", "HR", "ITS")  # registration_rules VIEWERS (OD-05)
PM_SCOPE = "project-pm"
MONEY_WORDS = ("salary", "rate", "cost", "bonus", "reward", "luong", "lương", "thưởng", "đơn giá", "chi phí")


def scope_config() -> dict:
    scopes = {r: {} for r in ROLES}
    for cap, g in GRANTS.items():
        for r in ROLES:
            scopes[r][cap] = g.get(r, "none")
    return {"scopes": scopes, "pending": []}
