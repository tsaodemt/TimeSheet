"""EPIC 16 Project Effort list definitions (R3 M2, OpenSpec `r3-planning-effort-hour-registration`, M2 decisions).

Two new protected lists; the master `Projects` list and its permissions are not changed (OD-24 clarification).

ProjectPmAssignments (OD-24): zero or one item per project. Business key PmKey = LegacyId = the project's LegacyId
(unique); the PM is stored as the ACTIVE employee's stable LegacyId (canonical) plus local helper ids. Written only by
EFF-SetProjectPm (PMO). No clearing operation.

ProjectEffortAllocations (NR-EFF-01; OD-14/16/22/23/40/44): one item per project x recipient that has ever held a value.
AllocKey = LegacyId = <ProjectLegacyId>|<RecipientKey>, RecipientKey = QLP | PM | D:<DisciplineLegacyId>. Effort in
man-days, at most 2 decimals, >= 0, no business maximum; null = BLANK (not registered), 0 = explicit zero. No phase,
period, approval, cost, EPIC 17 or HourRegistrations field (OD-25, OD-26). SharePoint item ids are helpers only.

Permissions (both lists, same pattern as HourRegistrations): inheritance broken; site owners Full Control; the service
role "TS Service" (View, Add, Edit — no Delete, no ManageLists, no ManagePermissions); no ordinary user or business
group has direct access.
"""
from __future__ import annotations

PM_LIST = "ProjectPmAssignments"
ALLOC_LIST = "ProjectEffortAllocations"
RECIPIENT_SETTING = "ProjectEffortRecipientDisciplines"
RECIPIENT_DEFAULT = "ELE,HVAC,PSF,BIM"  # OD-43 default (a): the four disciplines named by rev01 A.I.3 (QL is not a recipient)
HPM_SETTING = "HoursPerManDay"
CATEGORIES = ("QLP", "PM", "Discipline")

# (internal name, type, required, indexed, unique, extra)
PM_FIELDS = (
    ("PmKey", "Text", True, True, True, {"MaxLength": 255}),
    ("LegacyId", "Text", True, True, True, {"MaxLength": 255}),
    ("Project", "Lookup", True, False, False, {"LookupList": "Projects", "LookupField": "Title"}),
    ("ProjectItemId", "Number", True, True, False, {"Decimals": 0}),
    ("PmEmployeeLegacyId", "Text", True, True, False, {"MaxLength": 255}),
    ("PmEmployee", "Lookup", True, False, False, {"LookupList": "Employees", "LookupField": "Title"}),
    ("PmEmployeeItemId", "Number", True, True, False, {"Decimals": 0}),
    ("Status", "Choice", True, False, False, {"Choices": ["Active"], "Default": "Active"}),
    ("ActorUpn", "Text", False, False, False, {"MaxLength": 255}),
    ("CorrelationId", "Text", False, False, False, {"MaxLength": 255}),
)
ALLOC_FIELDS = (
    ("AllocKey", "Text", True, True, True, {"MaxLength": 255}),
    ("LegacyId", "Text", True, True, True, {"MaxLength": 255}),
    ("Project", "Lookup", True, False, False, {"LookupList": "Projects", "LookupField": "Title"}),
    ("ProjectItemId", "Number", True, True, False, {"Decimals": 0}),
    ("RecipientKey", "Text", True, False, False, {"MaxLength": 255}),
    ("RecipientCategory", "Choice", True, False, False, {"Choices": list(CATEGORIES)}),
    ("Discipline", "Lookup", False, False, False, {"LookupList": "Disciplines", "LookupField": "Title"}),
    ("DisciplineItemId", "Number", False, False, False, {"Decimals": 0}),
    ("Effort", "Number", False, False, False, {"Decimals": 2}),
    ("Status", "Choice", True, False, False, {"Choices": ["Active"], "Default": "Active"}),
    ("ActorUpn", "Text", False, False, False, {"MaxLength": 255}),
    ("CorrelationId", "Text", False, False, False, {"MaxLength": 255}),
)
LISTS = {PM_LIST: PM_FIELDS, ALLOC_LIST: ALLOC_FIELDS}
DESCRIPTIONS = {
    PM_LIST: "EPIC 16: authoritative PM per project (OD-24; protected; written only by EFF-SetProjectPm).",
    ALLOC_LIST: "EPIC 16 Công dự án: planned man-days per project x recipient (protected; guarded flows only).",
}
VERSIONING = True
SERVICE_ROLE = "TS Service"
SERVICE_RIGHTS = {"ViewListItems", "AddListItems", "EditListItems", "OpenItems", "ViewVersions", "ViewPages", "Open"}
NEVER = {"DeleteListItems", "DeleteVersions", "ManageLists", "ManagePermissions", "FullMask"}
DIRECT_USER_ACCESS = ()
# forbidden in EPIC 16 storage (OD-22, OD-23, OD-25, OD-26, OD-20/21)
FORBIDDEN_COLUMNS = {"Phase", "PhaseItemId", "PeriodKey", "Period", "ManDays", "RegKey", "SourceRef", "SourceRegistration",
                     "ApprovalStatus", "ApprovedBy", "ApprovedOn", "Locked", "Cost", "Rate", "Salary", "Evaluation", "Score"}


def field(lst, name):
    return next(f for f in LISTS[lst] if f[0] == name)
