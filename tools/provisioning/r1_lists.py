"""S05.5 operational AuditLog and S06.1 TimesheetEntries: target definitions, evidence-based index decisions,
dependency review and phased provisioning / permission plans (generic; no tenant data; nothing is executed here).

Sources (authoritative): target data model §4.1 (TimesheetEntries) and §8 (growth / threshold strategy), the target
schema (environment configuration, local), docs/audit-model.md + tools/audit/audit_event.py (audit columns), R1
contracts + the generated R1 flows (columns written, query shapes), the S03.5 permission model (classes P and W,
custom level TS Service), backlog S05.5 / S06.1 dependencies.

    target(name)                 -> list definition (fields, indexes, defaults) for schema_reconcile
    INDEX_DECISIONS[name]        -> per-column index decision with the query that needs it, scale and reason
    DEPENDENCIES[name]           -> schema / permission / service / flow / production dependencies (with sources)
    phase1_ready(name, facts)    -> (ready, blockers) for schema + human lockdown (no service identity involved)
    schema_plan(name, actual, site_url, allowed_url)   -> ordered operations (refuses wrong site / drift / incomplete list)
    permission_plan(name, phase, unique, current, ...)  -> Phase 1 lockdown or Phase 2 service grant (gated by D-3)
    rest_requests(name, actual)  -> exact REST requests of the schema plan (counted with a recording transport)
"""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import permission_plan as pp  # noqa: E402
import schema_reconcile as sr  # noqa: E402

AUDITLOG, ENTRIES = "AuditLog", "TimesheetEntries"
SERVICE_LEVEL = "TS Service"  # View, Add, Edit, OverrideListBehaviors, browse/open; no Delete, DeleteVersions, ManageLists, ManagePermissions, ManageWeb


def F(name, display, typ, required=False, indexed=False, unique=False, **kw):
    return dict(internalName=name, displayName=display, type=typ, required=required, indexed=indexed, unique=unique, **kw)


# ---------------------------------------------------------------- S05.5 AuditLog (operational only)
# Columns = docs/audit-model.md "Fields" = audit_event.COLUMNS. Owner/actor are numeric item ids (no lookups: an audit
# row must not depend on, or block deletion of, another list). ConfidentialAuditLog is NOT designed here (S03.5b/ENV-D2).
_AUDIT_FIELDS = [
    F("Title", "Title", "Text"),
    F("EventType", "Event type", "Text", True),
    F("Action", "Action", "Text", True),
    F("ActionText", "Action text", "Text"),
    F("Decision", "Decision", "Text", True),
    F("ResultCode", "Result code", "Text", True),
    F("OccurredOn", "Occurred on (UTC)", "DateTime", True, True, dateOnly=False),
    F("CorrelationId", "Correlation ID", "Text", True, True),
    F("ActorUpn", "Actor UPN", "Text"),
    F("ActorEmployeeItemId", "Actor employee item ID", "Number", decimals=0),
    F("TargetList", "Target list", "Text"),
    F("TargetItemId", "Target item ID", "Text"),
    F("TargetLegacyId", "Target legacy ID", "Text", False, True),
    F("OwnerEmployeeItemId", "Owner employee item ID", "Number", False, True, decimals=0),
    F("IsOnBehalf", "On behalf", "Boolean"),
    F("WorkDate", "Work date", "DateTime", dateOnly=True),
    F("ScopeKind", "Scope kind", "Text"),
    F("ScopeRef", "Scope ref", "Text"),
    F("SourceFlow", "Source flow", "Text"),
    F("Environment", "Environment", "Text"),
    F("ChangeJson", "Change JSON", "Note"),
    F("Detail", "Detail", "Note"),
]

# ---------------------------------------------------------------- S06.1 TimesheetEntries
# Target data model §4.1 / target schema. Lookups: Employee, Project (restrict delete, indexed), Shift, HourType, Phase,
# WorkType. ProjectPhases is NOT a lookup: the save flow validates the (Project, Phase) pair (F-TS-07), migrated rows
# are exempt. Gated columns are part of the target but are not created by an R1 Phase 1.
_ENTRY_FIELDS = [
    F("Title", "Entry ref", "Text"),
    F("LegacyId", "Legacy ID", "Text", True, True, True),
    F("LegacyModifiedBy", "Legacy modified by", "Text", gate="CONFIDENTIAL / ENV-D2: not provisioned on operational lists"),
    F("LegacyModifiedOn", "Legacy modified on", "DateTime", dateOnly=False),
    F("MigrationBatch", "Migration batch", "Text"),
    F("IsLegacyPlaceholder", "Legacy placeholder", "Boolean"),
    F("SortOrder", "Sort order", "Number", decimals=0, gate="S06.7 reorder"),
    F("LegacyOrigin", "Origin", "Choice", True, choices=["New", "LegacyLatest", "LegacyRestored"]),
    F("Employee", "Employee", "Lookup", True, True, lookupList="Employees"),
    F("EmployeeItemId", "Employee item ID", "Number", True, True, decimals=0),
    F("DisciplineCode", "Discipline at entry", "Text", True, True),
    F("OwnerUpn", "Owner UPN", "Text", True, True),
    F("ActorUpn", "Actor UPN", "Text", True),
    F("IsOnBehalf", "On behalf", "Boolean"),
    F("WorkDate", "Work date", "DateTime", True, True, dateOnly=True),
    F("PeriodKey", "Pay period", "Text", True, True),
    F("Shift", "Shift", "Lookup", True, lookupList="Shifts"),
    F("HourType", "Hour type", "Lookup", True, lookupList="HourTypes"),
    F("Hours", "Hours", "Number", True, decimals=2, validationFormula="=AND([Hours]>0,[Hours]<=24)"),
    F("Project", "Project", "Lookup", True, True, lookupList="Projects"),
    F("Phase", "Phase", "Lookup", True, lookupList="Phases"),
    F("WorkType", "Work type", "Lookup", True, lookupList="WorkTypes"),
    F("Remark", "Remark", "Note"),
    F("EntryStatus", "Status", "Choice", True, False, choices=["Draft", "Approved", "Deleted"], default="Draft",
      reservedChoices=["Rejected"]),
    F("CorrelationId", "Correlation ID", "Text"),
    F("ApprovedBy", "Approved by", "User", gate="EPIC 07 / gate G5"),
    F("ApprovedOn", "Approved on", "DateTime", dateOnly=False, gate="EPIC 07 / gate G5"),
    F("LegacyApprovalInfo", "Legacy approval info", "Text", gate="EPIC 08 migration"),
    F("DataQualityFlags", "DQ flags", "Text", gate="EPIC 08 migration"),
]

TARGETS = {
    AUDITLOG: {"title": AUDITLOG, "template": 100, "class": "W", "versioning": True, "fields": _AUDIT_FIELDS},
    ENTRIES: {"title": ENTRIES, "template": 100, "class": "P", "versioning": True, "fields": _ENTRY_FIELDS},
}
FORBIDDEN_COLUMNS = {ENTRIES: {"ApprovalStatus", "IsDeleted", "RequestKey", "EntryStatusCode"},
                     AUDITLOG: {"DailyRate", "Amount", "Percent", "KpiPlus", "KpiMinus", "RetentionDays", "PurgeAfter", "ExpiresOn"}}

# ---------------------------------------------------------------- index decisions (from query paths, not habit)
REQUIRED, RECOMMENDED, NOT_REQUIRED, DEFER_P5 = "REQUIRED", "RECOMMENDED", "NOT REQUIRED", "DEFER P5"
# Approved by the project owner 2026-10-07 (supersedes the earlier 7 / 9 index targets): AuditLog exactly these 4;
# TimesheetEntries these 8 (EntryStatus NOT REQUIRED FOR CURRENT R1 TARGET / REVISIT AFTER P5 IF NEEDED).
APPROVED_INDEXES = {AUDITLOG: ("OccurredOn", "CorrelationId", "OwnerEmployeeItemId", "TargetLegacyId"),
                    ENTRIES: ("OwnerUpn", "WorkDate", "LegacyId", "Employee", "Project", "EmployeeItemId", "PeriodKey",
                                         "DisciplineCode")}
INDEX_DECISIONS = {
    AUDITLOG: {  # scale: 0 -> ~100k rows at +5 years (target model §8), so every first filter must be indexed
        "OccurredOn": (REQUIRED, "audit viewer views Today / Last 7 days / On-behalf / Approvals (RPT-15); retention purge OccurredOn lt cutoff",
                       "~100k", "date range is the first filter of every viewer view and of purge; ~50-400 rows/day"),
        "CorrelationId": (REQUIRED, "support lookup CorrelationId eq <id> (the ID shown with every error; NFR correlation app->flow->audit)",
                          "~100k", "selective (1-5 rows/run); an unindexed eq filter fails above 5,000 rows"),
        "OwnerEmployeeItemId": (REQUIRED, "viewer view 'By owner'; per-employee history (target model §8)", "~100k",
                                "selective (rows of one employee); listed in the §8 threshold strategy"),
        "TargetLegacyId": (RECOMMENDED, "history of one record: TargetLegacyId eq <LegacyId> (record trail, S06.9 / reporting join)",
                           "~100k", "selective; created before load (adding later re-indexes a large list); R1 rows do not yet stamp it"),
        "ActorUpn": (NOT_REQUIRED, "no approved query filters by actor first", "~100k",
                     "investigations use OccurredOn first; not indexed for consistency (project owner 2026-10-07)"),
        "EventType": (NOT_REQUIRED, "only as a second filter after OccurredOn", "~100k",
                      "~10 values: each value matches > 5,000 rows, so an index cannot make an EventType-first query threshold-safe"),
        "Action": (NOT_REQUIRED, "only as a second filter after OccurredOn ('Approvals' view)", "~100k",
                   "low cardinality, same reason as EventType (project owner 2026-10-07)"),
    },
    ENTRIES: {  # scale: 44,997 legacy rows -> ~95-105k at +5 years; one period <= ~1.2k rows; one person x period 40-60 rows
        "OwnerUpn": (REQUIRED, "R1 read: OwnerUpn eq <caller> [and WorkDate range] and EntryStatus ne 'Deleted' and Id gt <after>; "
                     "save same-day check", "~100k", "security-critical first filter (read-proxy spike R10 proved it at > 5,000 rows)"),
        "WorkDate": (REQUIRED, "views Recent (WorkDate >= Today-31) and PendingRecent (WorkDate >= Today-62 first); S06.1 AC2",
                     "~100k", "first filter of the admin/support views; R1 itself filters it after OwnerUpn"),
        "LegacyId": (REQUIRED, "migration upsert and unique business key (LegacyId unique)", "~100k", "a unique constraint needs an index"),
        "Employee": (REQUIRED, "relationship enforcement (restrict delete of an employee with entries)", "~100k",
                     "SharePoint enforces Restrict only on an indexed lookup"),
        "Project": (REQUIRED, "relationship enforcement (restrict delete of a project with entries); per-project reporting",
                    "~100k", "SharePoint enforces Restrict only on an indexed lookup"),
        "EmployeeItemId": (REQUIRED, "EmployeeItemId = x and PeriodKey = p (team / on-behalf period view, target model §4.1)",
                           "~100k", "delegation-safe key (AD-5); <= 60 rows per person x period"),
        "PeriodKey": (REQUIRED, "ByPeriod view; period queries (<= ~1.2k rows per period)", "~100k", "selective first filter for period work"),
        "DisciplineCode": (RECOMMENDED, "approval scoping DisciplineCode = d and PeriodKey = p and EntryStatus = 'Draft' (EPIC 07)",
                           "~100k", "kept from the target for EPIC 07; that query must put PeriodKey first (a discipline can exceed 5,000 rows)"),
        "EntryStatus": (NOT_REQUIRED, "none filters EntryStatus first: R1 uses ne 'Deleted' after OwnerUpn; PendingRecent after WorkDate; "
                        "approval after PeriodKey", "~100k",
                        "3 values (Approved ~ most rows): each value matches > 5,000 rows, so an index cannot make a status-first query "
                        "threshold-safe; 'ne' cannot use an index. Project owner 2026-10-07: not required for the current R1 target; "
                        "revisit after P5 only if live Choice-column evidence shows a need"),
    },
}


def target(name: str) -> dict:
    """List definition with the index decisions applied (REQUIRED / RECOMMENDED indexed; others not)."""
    t = copy.deepcopy(TARGETS[name])
    dec = INDEX_DECISIONS[name]
    for f in t["fields"]:
        if f["internalName"] in dec:
            f["indexed"] = dec[f["internalName"]][0] in (REQUIRED, RECOMMENDED) or f.get("unique", False)
    return t


# ---------------------------------------------------------------- dependency review (backlog + technical)
DEPENDENCIES = {
    AUDITLOG: {
        "schema": [("S04.1", "provisioning tooling (schema_reconcile: exact-site guard, dry run, no deletes) — backlog S05.5 depends on S04.1 only; "
                             "S04.1 is IN PROGRESS but its operational tooling is the one used for the live S04.3 / S04.7 lists")],
        "permissionPhase1": [("Owners group", "exists on STAGING (S03.5a DONE)")],
        "permissionPhase2": [("D-3", "operational service identity (S03.5c) for the TS Service grant")],
        "serviceConnection": [("D-3", "SERVICE connection references owned by the approved identity"), ("ENV-D3", "solution environment / prefix (S05.1)")],
        "flowUse": [("S05.1", "solution + connection references (D-3, ENV-D3)"), ("S05.4", "guard-flow framework"),
                    ("AUD-F1", "audit-failure semantics decision (open)")],
        "production": [("PROD-01 / G10", "production site"), ("D-3", "production service identity"), ("ENV-D3", "production environment"),
                       ("IT-08", "retention duration (purge stays disabled until decided; not needed to create the list)")],
        "notIn": ["ENV-D2 (only ConfidentialAuditLog)", "G2", "B-03"],
    },
    ENTRIES: {
        "schema": [("S04.6", "lookup target Projects must exist (required Project lookup) — S04.6 depends on S04.3 and G2 (customer)"),
                   ("S05.4", "declared by backlog S06.1 (guard framework, -> S05.1 -> D-3 + ENV-D3); it orders the read-security work "
                             "(T06.1.2/T06.1.3), not the columns — changing it is a project-owner decision, not done here"),
                   ("S04.3", "lookup targets Phases / WorkTypes / Shifts / HourTypes (lists exist; rows not needed for the schema)")],
        "permissionPhase1": [("Owners group", "exists on STAGING")],
        "permissionPhase2": [("D-3", "TS Service grant to the approved operational service identity")],
        "serviceConnection": [("D-3", "SERVICE connection references"), ("ENV-D3", "solution environment / prefix")],
        "flowUse": [("S05.1", "solution (D-3, ENV-D3)"), ("S05.4", "guard framework"), ("S05.5", "AuditLog live"),
                    ("S04.3 rows", "canonical reference rows"), ("S04.6 rows", "projects / project phases loaded (G2)")],
        "production": [("PROD-01 / G10", "production site"), ("D-3", "production identity"), ("ENV-D3", "production environment"),
                       ("EPIC 08 / G6", "migration of legacy rows (not R1 Phase 1)")],
        "notIn": ["ENV-D2 (LegacyModifiedBy is gated, not provisioned)"],
    },
}


def phase1_ready(name: str, facts: dict) -> tuple:
    """facts: {"lists": set of existing list titles, "S04.6": status, "S05.4": status, "S04.1_tooling": bool}.
    Phase 1 = schema + human lockdown. A service identity is never needed for it."""
    b = []
    if not facts.get("S04.1_tooling", True):
        b.append(("S04.1", "provisioning tooling not available"))
    t = target(name)
    for f in t["fields"]:
        if f["type"] == "Lookup" and f.get("required") and not f.get("gate") and f["lookupList"] not in facts.get("lists", set()):
            b.append(("LOOKUP_TARGET_MISSING", "%s -> %s" % (f["internalName"], f["lookupList"])))
    if name == ENTRIES:
        for dep in ("S04.6", "S05.4"):
            if facts.get(dep) != "DONE":
                b.append((dep, "backlog dependency of S06.1 not done (%s)" % facts.get(dep, "NOT STARTED")))
    return (not b, b)


# ---------------------------------------------------------------- schema plan (Phase 1)
class IncompleteList(Exception):
    pass


def schema_plan(name: str, actual: dict, site_url: str, allowed_url: str) -> list:
    """Executable operations for the list (never deletes/retypes). Refuses: wrong site, incompatible drift, and a list
    whose required, ungated columns cannot all be created (e.g. a missing lookup target)."""
    sr.guard_site(site_url, allowed_url)
    t = {"lists": [target(name)]}
    findings = sr.reconcile(t, actual)
    blocked = [f for f in findings if f.status == sr.BLOCKED]
    if blocked:
        raise sr.SiteGuardError("incompatible drift, nothing planned: " + "; ".join("%s.%s %s" % (f.list, f.field, f.detail) for f in blocked))
    req = {f["internalName"] for f in t["lists"][0]["fields"] if f.get("required") and not f.get("gate")}
    missing = [f for f in findings if f.field in req and f.status == sr.GATED]
    if missing:
        raise IncompleteList("required columns cannot be created now: " + "; ".join("%s (%s)" % (f.field, f.detail) for f in missing))
    return sr.plan(findings)


def list_settings_requests(name: str) -> list:
    """List-level settings applied after creation (T05.5.3 versioning on every list; the version limit stays the tenant
    policy, CL 5.8 — no number is invented here)."""
    q = name.replace("'", "''")
    return [("POST", "/_api/web/lists/getbytitle('%s')" % q, {"__metadata": {"type": "SP.List"}, "EnableVersioning": True},
             {"X-HTTP-Method": "MERGE", "IF-MATCH": "*"})] if TARGETS[name].get("versioning") else []


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body, headers):
        self.calls.append((method, path))
        if method == "GET" and "$select=Id" in path:
            return 200, {"d": {"Id": "00000000-0000-0000-0000-000000000000"}}
        if method == "GET" and "$select=Choices" in path:
            return 200, {"d": {"Choices": {"results": []}}}
        return 201, {}


def rest_requests(name: str, actual: dict, site_url: str, allowed_url: str) -> list:
    """Exact REST requests of the schema plan + list settings (recorded, nothing sent)."""
    ops = schema_plan(name, actual, site_url, allowed_url)
    rec = _Recorder()
    client = sr.RestSchemaClient(rec)
    for lst, fld, (op, val) in ops:
        if op == "create_list":
            client.create_list(val)
        elif op == "create_field":
            client.create_field(lst, val)
        else:
            client.update_field(lst, fld, op, val)
    if any(o[2][0] == "create_list" for o in ops):
        rec.calls += [(m, p) for m, p, _, _ in list_settings_requests(name)]
    return rec.calls


# ---------------------------------------------------------------- permissions
def permission_plan(name: str, phase: int, unique: bool, current, *, owners_id: int, admin_id: int,
                    service: dict = None, temporary_principals=()) -> dict:
    """Phase 1: break inheritance (no copy), Owners Full Control; nobody else (ordinary users: no direct read or write).
    Phase 2 (after D-3): additionally TS Service for the approved operational identity — never Delete, Manage
    Permissions or Full Control. Without an approved service the grant stays GATED."""
    tgt = pp.Target(required={owners_id: "Full Control"}, allowed_extra=(admin_id,),
                    gated=[{"principal": "<operational service identity>", "role": SERVICE_LEVEL, "gate": "D-3"}],
                    temporary_principals=tuple(temporary_principals))
    approved = []
    if phase == 2 and service is not None:
        approved = [{"gate": "D-3", "role": SERVICE_LEVEL, "principal_id": service.get("principal_id"),
                     "principal_title": service.get("title", ""), "approval": service.get("approval")}]
    elif phase not in (1, 2):
        raise ValueError("phase is 1 or 2")
    return pp.plan(unique, current, tgt, approved_grants=approved)


GATED_GRANTS = {AUDITLOG: [("auditor groups (Approver, Executive, HR, AppAdmin, IT Support)", "Read", "S12.7 audit viewer (RPT-15)")],
                ENTRIES: [("BI service identity", "Read", "EPIC 11 / BI (svc-ts-bi)")]}

# The TS Service level against what each list needs.
NEEDED_RIGHTS = {AUDITLOG: {"ViewListItems", "AddListItems"}, ENTRIES: {"ViewListItems", "AddListItems", "EditListItems"}}
TS_SERVICE_RIGHTS = {"ViewListItems", "AddListItems", "EditListItems", "OpenItems", "ViewVersions", "OverrideListBehaviors",
                     "ManagePersonalViews", "ViewFormPages", "Open", "ViewPages", "BrowseDirectories", "BrowseUserInfo",
                     "AddDelPrivateWebParts", "UpdatePersonalWebParts", "UseClientIntegration", "UseRemoteAPIs", "CreateAlerts",
                     "EditMyUserInfo"}
NEVER = {"DeleteListItems", "DeleteVersions", "ManageLists", "ManagePermissions", "ManageWeb", "FullMask"}


# ---------------------------------------------------------------- AUD-P1 (open): service level for AuditLog
# SP.PermissionKind numbers (bit = kind - 1; kinds > 32 go to the High word). "OverrideListBehaviors" is the
# CancelCheckout kind ("Override List Behaviors" in the permission-level UI).
PERMISSION_KIND = {"ViewListItems": 1, "AddListItems": 2, "EditListItems": 3, "DeleteListItems": 4, "ApproveItems": 5, "OpenItems": 6,
                   "ViewVersions": 7, "DeleteVersions": 8, "OverrideListBehaviors": 9, "ManagePersonalViews": 10, "ManageLists": 12,
                   "ViewFormPages": 13, "Open": 17, "ViewPages": 18, "CreateSSCSite": 23, "ManagePermissions": 26, "BrowseDirectories": 27,
                   "BrowseUserInfo": 28, "AddDelPrivateWebParts": 29, "UpdatePersonalWebParts": 30, "ManageWeb": 31,
                   "UseClientIntegration": 37, "UseRemoteAPIs": 38, "CreateAlerts": 40, "EditMyUserInfo": 41}
AUDIT_APPEND_LEVEL = "TS Audit Append"  # option B (not created; a live permission-level change needs separate approval)
# Add Items cannot exist without View Items (+ Open, View Pages) in SharePoint; Use Remote Interfaces is needed for the
# REST call the flow makes. Nothing else: no Edit, Delete, versions management, Override List Behaviors or web rights.
AUDIT_APPEND_RIGHTS = {"ViewListItems", "AddListItems", "Open", "ViewPages", "UseRemoteAPIs"}


def rights_mask(rights) -> tuple:
    low = high = 0
    for r in rights:
        b = PERMISSION_KIND[r] - 1
        if b < 32:
            low |= 1 << b
        else:
            high |= 1 << (b - 32)
    return low, high


def rights_from_mask(low: int, high: int) -> set:
    return {r for r, k in PERMISSION_KIND.items() if ((low >> (k - 1)) & 1 if k <= 32 else (high >> (k - 33)) & 1)}


def aud_p1_options() -> dict:
    """AUD-P1 analysis: A = reuse TS Service on AuditLog; B = dedicated append level. Decision stays with the owner."""
    def row(rights, level):
        return {"level": level, "rights": sorted(rights), "mask": rights_mask(rights),
                "canAdd": "AddListItems" in rights, "readsRows": "ViewListItems" in rights,
                "canEditExisting": "EditListItems" in rights, "canDelete": "DeleteListItems" in rights,
                "canOverrideListBehaviors": "OverrideListBehaviors" in rights, "forbiddenPresent": sorted(set(rights) & NEVER),
                "beyondAppend": sorted(set(rights) - AUDIT_APPEND_RIGHTS)}
    return {"A": dict(row(TS_SERVICE_RIGHTS, SERVICE_LEVEL), newRoleDefinition=False),
            "B": dict(row(AUDIT_APPEND_RIGHTS, AUDIT_APPEND_LEVEL), newRoleDefinition=True),
            "recommended": "B"}


def level_assessment(name: str) -> dict:
    need = NEEDED_RIGHTS[name]
    item_rights = {"ViewListItems", "AddListItems", "EditListItems", "DeleteListItems", "OverrideListBehaviors"}
    return {"sufficient": need <= TS_SERVICE_RIGHTS, "missing": sorted(need - TS_SERVICE_RIGHTS),
            "beyondNeed": sorted((TS_SERVICE_RIGHTS & item_rights) - need), "forbiddenPresent": sorted(TS_SERVICE_RIGHTS & NEVER)}


# ---------------------------------------------------------------- migration status (EPIC 08; nothing migrated now)
class UnmappedLegacyValue(ValueError):
    pass


def migrate_status(legacy_lock) -> str:
    """migration-mapping E13-13: 'Lock' -> Approved; '' or key absent (None, 104 older rows) -> Draft. No legacy value maps
    to Deleted: suspected-loss rows (D-Q1 / D2) are evidence in the history list, never an automatic delete. Any other
    value is refused rather than guessed."""
    if legacy_lock is None or legacy_lock == "":
        return "Draft"
    if legacy_lock == "Lock":
        return "Approved"
    raise UnmappedLegacyValue("legacy Lock value %r has no approved mapping" % (legacy_lock,))
