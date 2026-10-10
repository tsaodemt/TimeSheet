"""EPIC 17 Discipline Effort list definitions (R3 M3, OpenSpec `r3-planning-effort-hour-registration`, M3 decisions 2026-10-10).

DisciplineEffortRegistrations (OD-29, OD-30, OD-47, OD-48): one item per Employee × Project × WorkType that has ever held a value.
RegKey = LegacyId = <ProjectLegacyId>|<EmployeeLegacyId>|<WorkTypeLegacyId> (unique, environment portable); item ids of
Projects / Employees / WorkTypes / Disciplines are local helpers only. Discipline = snapshot of the owner's authoritative Employees
row at write time (never from the request). Effort in man-days, ≤ 2 decimals, ≥ 0, no business maximum; null = BLANK.
Status Draft → ApprovedLocked (OD-27, OD-18: no reopen). No period (OD-48), no revision (OD-34), no stored discipline total (OD-30),
no actual effort (OD-19 / OD-33 / OD-49), no task entity (OD-29), no cost / evaluation field.

DisciplineEffortLocks (technical): one item per Project × Discipline used only to serialise ceiling checks (AC-EFF17-02):
Busy / BusyUntil / Stamp; no business value, no total.

Permissions (both lists, same pattern as the M1 / M2 lists): inheritance broken; site owners Full Control; service role
"TS Service" (View, Add, Edit — no Delete, no ManageLists, no ManagePermissions); no user or business group.
"""
from __future__ import annotations

REG_LIST = "DisciplineEffortRegistrations"
LOCK_LIST = "DisciplineEffortLocks"
DRAFT, APPROVED = "Draft", "ApprovedLocked"
LOCK_MINUTES = 10

# (internal name, type, required, indexed, unique, extra)
REG_FIELDS = (
    ("RegKey", "Text", True, True, True, {"MaxLength": 255}),
    ("LegacyId", "Text", True, True, True, {"MaxLength": 255}),
    ("Project", "Lookup", True, False, False, {"LookupList": "Projects", "LookupField": "Title"}),
    ("ProjectItemId", "Number", True, True, False, {"Decimals": 0}),
    ("Employee", "Lookup", True, False, False, {"LookupList": "Employees", "LookupField": "Title"}),
    ("EmployeeItemId", "Number", True, True, False, {"Decimals": 0}),
    ("EmployeeLegacyId", "Text", True, False, False, {"MaxLength": 255}),
    ("OwnerUpn", "Text", True, True, False, {"MaxLength": 255}),
    ("Discipline", "Lookup", True, False, False, {"LookupList": "Disciplines", "LookupField": "Title"}),
    ("DisciplineItemId", "Number", True, True, False, {"Decimals": 0}),
    ("DisciplineCode", "Text", True, False, False, {"MaxLength": 255}),
    ("DisciplineLegacyId", "Text", True, False, False, {"MaxLength": 255}),
    ("WorkType", "Lookup", True, False, False, {"LookupList": "WorkTypes", "LookupField": "Title"}),
    ("WorkTypeItemId", "Number", True, False, False, {"Decimals": 0}),
    ("WorkTypeLegacyId", "Text", True, False, False, {"MaxLength": 255}),
    ("Effort", "Number", False, False, False, {"Decimals": 2}),
    ("Status", "Choice", True, False, False, {"Choices": [DRAFT, APPROVED], "Default": DRAFT}),
    ("ApprovedBy", "Text", False, False, False, {"MaxLength": 255}),
    ("ApprovedOn", "DateTime", False, False, False, {}),
    ("ActorUpn", "Text", False, False, False, {"MaxLength": 255}),
    ("CorrelationId", "Text", False, False, False, {"MaxLength": 255}),
)
LOCK_FIELDS = (
    ("LockKey", "Text", True, True, True, {"MaxLength": 255}),
    ("LegacyId", "Text", True, True, True, {"MaxLength": 255}),
    ("ProjectItemId", "Number", True, False, False, {"Decimals": 0}),
    ("DisciplineItemId", "Number", True, False, False, {"Decimals": 0}),
    ("Busy", "Boolean", False, False, False, {}),
    ("BusyUntil", "DateTime", False, False, False, {}),
    ("Stamp", "Text", False, False, False, {"MaxLength": 255}),
)
LISTS = {REG_LIST: REG_FIELDS, LOCK_LIST: LOCK_FIELDS}
SERVICE_ROLE = "TS Service"
SERVICE_RIGHTS = {"ViewListItems", "AddListItems", "EditListItems", "OpenItems", "ViewVersions", "ViewPages", "Open"}
NEVER = {"DeleteListItems", "DeleteVersions", "ManageLists", "ManagePermissions", "FullMask"}
DIRECT_USER_ACCESS = ()
FORBIDDEN_COLUMNS = {"TaskItemId", "TaskType", "ProjectTask", "PeriodKey", "Period", "Month", "Year", "RevisionNo", "VersionSet",
                     "DisciplineTotal", "Total", "ActualHours", "ActualEffort", "ManDays", "Cost", "Salary", "Evaluation", "Score",
                     "Reopened", "UnlockedBy"}


def reg_key(project_legacy: str, employee_legacy: str, worktype_legacy: str) -> str:
    return "%s|%s|%s" % (project_legacy, employee_legacy, worktype_legacy)


def lock_key(project_legacy: str, discipline_legacy: str) -> str:
    return "%s|%s" % (project_legacy, discipline_legacy)


def field(lst, name):
    return next(f for f in LISTS[lst] if f[0] == name)
