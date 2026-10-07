"""DEMO-ONLY synthetic reference data for the R1 engineering / customer demo (generic; no tenant or customer data).

These rows are NOT canonical customer master data and NOT migration data. Every row carries MigrationBatch = DEMO_ONLY,
a DEMO- legacy id and IsLegacyPlaceholder = False, so it can be found and removed by one filter. They exist only because
the canonical S04.3 extract needs the legacy key and the Projects catalogue is gated by G2 (D-Q4, D-Q8, B-04, B-15,
which stay open and are not resolved here).

    demo_rows()                     -> {list title: [rows]} for Phases, WorkTypes, Shifts, HourTypes, Projects, ProjectPhases
    demo_employee(upn, dept_id, discipline_id) -> one Employees row for the demo identity (values from configuration)
    validate(rows)                  -> [] or problems (required fields, marker, unique codes, phase relation)
"""
from __future__ import annotations

MARKER = "DEMO_ONLY"


def _base(code, title, order):
    return {"Title": title, "LegacyId": "DEMO-" + code, "MigrationBatch": MARKER, "IsLegacyPlaceholder": False, "SortOrder": order}


def demo_rows() -> dict:
    phases = [dict(_base("PH-DESIGN", "DEMO Design", 1), PhaseCode="DEMO-DES", IsActive=True),
              dict(_base("PH-SITE", "DEMO Site support", 2), PhaseCode="DEMO-SITE", IsActive=True)]
    work_types = [dict(_base("WT-ENG", "DEMO Engineering", 1), WorkTypeCode="DEMO-ENG", IsActive=True),
                  dict(_base("WT-MEET", "DEMO Meeting", 2), WorkTypeCode="DEMO-MEET", IsActive=True)]
    shifts = [dict(_base("SH-DAY", "DEMO Day shift", 1), ShiftCode="DEMO-DAY", IsActive=True, IsDefault=True)]
    hour_types = [dict(_base("HT-NORMAL", "DEMO Normal hours", 1), HourTypeCode="DEMO-NT", Factor=1, IsNormalHours=True)]
    projects = [dict(_base("PRJ-0001", "DEMO Project (not customer data)", 1), ProjectCode="DEMO-PRJ-01", Status="Active")]
    # Project / Phase lookups are resolved to item ids at apply time (ProjectId, PhaseId, ProjectItemId)
    project_phases = [dict(_base("PP-0001", "DEMO-PRJ-01 / DEMO-DES", 1), Project="DEMO-PRJ-01", Phase="DEMO-DES", IsActive=True),
                      dict(_base("PP-0002", "DEMO-PRJ-01 / DEMO-SITE", 2), Project="DEMO-PRJ-01", Phase="DEMO-SITE", IsActive=True)]
    return {"Phases": phases, "WorkTypes": work_types, "Shifts": shifts, "HourTypes": hour_types, "Projects": projects,
            "ProjectPhases": project_phases}


def demo_employee(upn: str, department_id: int, discipline_id: int) -> dict:
    """The demo caller's Employees row. upn comes from environment configuration (never from source)."""
    if not upn or "@" not in upn:
        raise ValueError("demo identity must come from configuration")
    return dict(_base("EMP-0001", "DEMO Employee (not customer data)", 1), LegacyUserName="DEMO-EMP-0001", AccountUpn=upn.lower(),
                DepartmentId=int(department_id), DisciplineId=int(discipline_id), IsActive=True)


REQUIRED = {"Phases": ("Title", "LegacyId", "PhaseCode", "IsActive"), "WorkTypes": ("Title", "LegacyId", "WorkTypeCode", "IsActive"),
            "Shifts": ("Title", "LegacyId", "ShiftCode", "IsActive"), "HourTypes": ("Title", "LegacyId", "HourTypeCode", "Factor"),
            "Projects": ("Title", "LegacyId", "ProjectCode", "Status"), "ProjectPhases": ("LegacyId", "Project", "Phase", "IsActive")}
CODE = {"Phases": "PhaseCode", "WorkTypes": "WorkTypeCode", "Shifts": "ShiftCode", "HourTypes": "HourTypeCode", "Projects": "ProjectCode"}


def validate(rows: dict) -> list:
    p = []
    for lst, rs in rows.items():
        seen = set()
        for r in rs:
            for k in REQUIRED[lst]:
                if r.get(k) in (None, ""):
                    p.append("%s %s: %s missing" % (lst, r.get("LegacyId"), k))
            if r.get("MigrationBatch") != MARKER or not str(r.get("LegacyId", "")).startswith("DEMO-"):
                p.append("%s %s: not marked DEMO_ONLY" % (lst, r.get("LegacyId")))
            key = r.get(CODE.get(lst, "LegacyId"))
            if key in seen:
                p.append("%s: duplicate %s" % (lst, key))
            seen.add(key)
    codes = {lst: {r[CODE[lst]] for r in rows.get(lst, [])} for lst in CODE}
    for r in rows.get("ProjectPhases", []):
        if r["Project"] not in codes["Projects"] or r["Phase"] not in codes["Phases"]:
            p.append("ProjectPhases %s: relation to unknown project/phase" % r["LegacyId"])
    if not any(r.get("IsNormalHours") and r.get("Factor") == 1 for r in rows.get("HourTypes", [])):
        p.append("HourTypes: a normal hour type (factor 1) is required")
    return p
