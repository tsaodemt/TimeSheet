"""`HourRegistrations` list definition (R3 M1, OpenSpec design §5.1 + M1 decisions). Spec only: provisioning runs through
a separate guarded STAGING script that compares the live list with this definition first (idempotent / reconcilable).

Unpivoted: one item per (project, phase, discipline) cell that has ever held a value. ManDays null = BLANK, 0 = explicit
zero (OD-01). Clear keeps the item (OD-09, D-7). The stable business key RegKey (= LegacyId) is built from immutable,
environment-portable master LegacyIds; SharePoint item ids (ProjectItemId, PhaseItemId, DisciplineItemId) are local
lookup / query helpers only. No EPIC 16/17 field, no salary / rate / cost field.

Permissions (protected business list, same pattern as TimesheetEntries): inheritance broken; site owners Full Control;
the service identity "TS Service" (View, Add, Edit — no Delete, no ManageLists, no ManagePermissions); no ordinary
user or business group has any direct access (reads and writes go through REG-ReadMatrix / REG-SaveMatrix).
"""
from __future__ import annotations

TITLE = "HourRegistrations"
DESCRIPTION = "S12.5 Đăng ký công: registered man-days per project x phase x discipline (protected; guarded flows only)."
# (internal name, type, required, indexed, unique, extra)
FIELDS = (
    ("RegKey", "Text", True, True, True, {"MaxLength": 255}),
    ("LegacyId", "Text", True, True, True, {"MaxLength": 255}),
    ("Project", "Lookup", True, False, False, {"LookupList": "Projects", "LookupField": "Title"}),
    ("ProjectItemId", "Number", True, True, False, {"Decimals": 0}),
    ("Phase", "Lookup", True, False, False, {"LookupList": "Phases", "LookupField": "Title"}),
    ("PhaseItemId", "Number", True, False, False, {"Decimals": 0}),
    ("Discipline", "Lookup", True, False, False, {"LookupList": "Disciplines", "LookupField": "Title"}),
    ("DisciplineItemId", "Number", True, False, False, {"Decimals": 0}),
    ("ManDays", "Number", False, False, False, {"Decimals": 2}),
    ("Status", "Choice", True, False, False, {"Choices": ["Active"], "Default": "Active"}),
    ("ActorUpn", "Text", False, False, False, {"MaxLength": 255}),
    ("CorrelationId", "Text", False, False, False, {"MaxLength": 255}),
)
VERSIONING = True
SERVICE_ROLE = "TS Service"
SERVICE_RIGHTS = {"ViewListItems", "AddListItems", "EditListItems", "OpenItems", "ViewVersions", "ViewPages", "Open"}
NEVER = {"DeleteListItems", "DeleteVersions", "ManageLists", "ManagePermissions", "FullMask"}
DIRECT_USER_ACCESS = ()  # no user, no business group


def field(name):
    return next(f for f in FIELDS if f[0] == name)
