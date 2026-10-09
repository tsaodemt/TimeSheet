"""S12.5 Hour Registration capability matrix (R3 M1, owner decisions OD-04 and OD-05, 2026-10-09, legacy parity).

Legacy module "TS.Đăng ký công": write = CEO, Secretary, PM; read = Manager, Leader, IT, HRD; hidden = Member, AD.
Mapped through the legacy -> target role map: VIEW = Team Leader, Approver, Executive, PMO, HR, IT Support;
EDIT (edit / clear / save) = Executive, PMO. App Administrator, Employee, Finance, Salary Viewer, Confidential Owner and
Migration Owner get neither (technical privilege never implies business authority). Legacy Director is retired.
"""
from __future__ import annotations

VIEW, EDIT = "REG.View", "REG.Edit"
ROLES = ("EMP", "TL", "APR", "EXE", "PMO", "HR", "SALV", "FIN", "ADM", "ITS", "CONFO", "MIGO")
MATRIX = {  # role -> (view, edit)
    "EMP": (False, False), "TL": (True, False), "APR": (True, False), "EXE": (True, True), "PMO": (True, True),
    "HR": (True, False), "SALV": (False, False), "FIN": (False, False), "ADM": (False, False), "ITS": (True, False),
    "CONFO": (False, False), "MIGO": (False, False),
}
LEGACY_MAP = (  # legacy role, legacy access, target role(s)
    ("CEO", "Write", ("EXE", "APR")), ("Manager", "Read", ("APR",)), ("Leader", "Read", ("TL",)), ("Member", "Hide", ("EMP",)),
    ("Secretary", "Write", ("PMO",)), ("PM", "Write", ("PMO",)), ("IT", "Read", ("ITS", "ADM", "HR", "SALV")),
    ("HRD", "Read", ("HR",)), ("AD", "Hide", ("FIN",)),
)
EDITORS = tuple(r for r in ROLES if MATRIX[r][1])
VIEWERS = tuple(r for r in ROLES if MATRIX[r][0])


def scope_config() -> dict:
    """Guard policy: company scope for every granted capability (the matrix is company-wide, legacy had no scope)."""
    scopes = {}
    for r in ROLES:
        v, e = MATRIX[r]
        caps = {}
        if v:
            caps[VIEW] = "company"
        if e:
            caps[EDIT] = "company"
        scopes[r] = caps
    return {"scopes": scopes, "pending": []}


def can(roles, capability) -> bool:
    return any(MATRIX.get(r, (False, False))[0 if capability == VIEW else 1] for r in roles)
