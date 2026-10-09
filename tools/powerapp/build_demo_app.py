"""R1 demo Canvas app source (Power Apps YAML, `*.pa.yaml`) — generic; no tenant, site, list GUID or account.

Screens: scrStartup (TS-AppOpen), scrAccessDenied (identity / config error), scrMyTimesheets (TS-ReadOwn, bounded current
pay period), scrEntry (new / edit own Draft via TS-SaveEntry), scrTeamApproval (S07.2: Draft queue of the current pay
period via TS-ReadTeam, multi-select, per-row approval via TS-Approve; S07.3 Approved review mode with an explicit
per-row "Hủy phê duyệt" action, confirmed per row, via TS-Unapprove; no batch unapprove). Protected lists (TimesheetEntries, AuditLog) are never data
sources: every read and write of entries goes through the flows. Reference lists (Projects, ProjectPhases, Phases,
WorkTypes, Shifts, HourTypes) are read-only SharePoint data sources bound per environment when the app is added to the
solution (the employee group has Read on them).

Message texts are PROVISIONAL DEMO WORDING keyed by the stable messageCode (R1-Q4 stays customer-open).

    python build_demo_app.py <out_dir>   -> App.pa.yaml + one <screen>.pa.yaml per screen + messages.json
"""
from __future__ import annotations

import json
import os
import sys

import yaml

FLOW_APPOPEN, FLOW_READ, FLOW_SAVE = "'TS-AppOpen'", "'TS-ReadOwn'", "'TS-SaveEntry'"
FLOW_TEAM, FLOW_APPROVE = "'TS-ReadTeam'", "'TS-Approve'"  # S07.2 team approval (guarded; no direct entry access)
FLOW_UNAPPROVE = "'TS-Unapprove'"  # S07.3 explicit per-row unapproval
FLOW_REG_READ, FLOW_REG_SAVE = "'REG-ReadMatrix'", "'REG-SaveMatrix'"  # R3 M1 S12.5 Hour Registration (guarded; no direct list access)
REFERENCE_SOURCES = ("Projects", "ProjectPhases", "Phases", "WorkTypes", "Shifts", "HourTypes")
PROTECTED_LISTS = ("TimesheetEntries", "AuditLog", "Employees", "AppSettings", "HourRegistrations")
PAGE_SIZE = 100

# PROVISIONAL DEMO WORDING (R1-Q4 open): neutral, no internals; the correlation id is appended by the app.
MESSAGES = {
    "MSG_OK": "Saved.",
    "MSG_UNMAPPED_IDENTITY": "Your account is not registered for Timesheet. Please contact the administrator.",
    "MSG_INACTIVE_EMPLOYEE": "Your employee record is inactive. Please contact the administrator.",
    "MSG_DUPLICATE_IDENTITY": "Your account is linked to more than one employee record. Please contact the administrator.",
    "MSG_INVALID_IDENTITY": "Your sign-in could not be verified for Timesheet.",
    "MSG_ACCOUNT_NOT_ALLOWED": "This account cannot use Timesheet.",
    "MSG_DIRECTORY_ERROR": "The employee directory is not available right now. Please try again later.",
    "MSG_ROLE_NOT_ALLOWED": "You do not have permission for this action.",
    "MSG_SCOPE_NOT_ALLOWED": "You do not have permission for this action.",
    "MSG_UNKNOWN_ACTION": "This action is not available.",
    "MSG_UNKNOWN_SCOPE": "This action is not available.",
    "MSG_DECISION_PENDING": "This function is not enabled yet.",
    "MSG_TEMP_ROLE_INACTIVE": "This function is not enabled yet.",
    "MSG_CONFIG_UNRESOLVED": "Timesheet is not fully configured yet. Please contact the administrator.",
    "MSG_CONFIG_INVALID": "Timesheet configuration or your employee record is incomplete. Please contact the administrator.",
    "MSG_NOT_FOUND": "This entry no longer exists.",
    "MSG_FORBIDDEN": "You can only change your own entries.",
    "MSG_LOCKED": "Dữ liệu đã được phê duyệt",
    "MSG_CONFLICT": "This entry was changed elsewhere. Your entries were refreshed; please open it again.",
    "MSG_VALIDATION_LOOKUP": "Please choose an active project, phase, work type, shift and hour type.",
    "MSG_VALIDATION_HOURS": "Hours must be greater than 0 and at most 24.",
    "MSG_VALIDATION_DATE": "Please enter a valid work date.",
    "MSG_ERROR_LEAK": "Your entries could not be shown. Please contact the administrator.",
    "MSG_ERROR": "Something went wrong. Please try again later.",
    "MSG_ACCOUNT_NOT_ENABLED": "Your account is not enabled for Timesheet. Please contact the administrator.",
    "MSG_TEMPORARY_PROBLEM": "Timesheet is temporarily unavailable. Please try again later.",
    "WARN_HOURS_ENTRY": "Note: this entry is longer than the usual maximum per entry.",
    "WARN_HOURS_DAY": "Note: the total for this day is above the usual daily maximum.",
    "WARN_DUPLICATE": "Note: a similar entry already exists for this day.",
    "WARN_RELOAD_REQUIRED": "Saved. Your entries were reloaded before further changes.",
    "AUDIT_DEGRADED": "Saved. A background record could not be written; the administrator has been notified. Do not save again.",
    # S07.2 team approval
    "MSG_APPROVE_OK": "The selected entries were approved.",
    "MSG_ROW_APPROVED": "Approved.",
    "MSG_PARTIAL": "Some entries were approved; the others were refused (see the results).",
    "MSG_REFUSED": "No entry was approved (see the results).",
    "MSG_VALIDATION_REQUEST": "The selection could not be processed. Please select between 1 and 50 entries.",
    "MSG_APPROVE_CONFIRM": "Bạn có muốn phê duyệt nội dung chấm công không?",
    # S07.3 unapprove
    "MSG_NOT_APPROVED": "This entry is not approved.",
    "MSG_UNAPPROVE_CONFIRM": "Bạn có muốn hủy phê duyệt nội dung chấm công này không?",
    "MSG_UNAPPROVE_OK": "The approval was cancelled.",
    "MSG_ROW_UNAPPROVED": "Approval cancelled.",
    # R3 M1 Hour Registration (Đăng ký công)
    "REG_OK": "Đã lưu công đăng ký.",
    "REG_REFUSED": "Chưa lưu: có ô không hợp lệ hoặc vừa được người khác thay đổi. Dữ liệu đã được tải lại; các ô bạn sửa vẫn được giữ.",
    "REG_PARTIAL": "Đã lưu một phần: một số ô vừa được người khác thay đổi. Dữ liệu đã được tải lại; các ô chưa lưu vẫn được giữ.",
    "REG_INVALID": "Giá trị phải là số lớn hơn hoặc bằng 0, tối đa 2 chữ số thập phân.",
    "REG_LEAVE": "Có thay đổi chưa lưu. Bỏ các thay đổi này?",
    "REG_NO_ACCESS": "Bạn không có quyền xem Đăng ký công.",
}


def _table(d):
    return "Table(%s)" % ", ".join('{code: "%s", text: "%s"}' % (k, v.replace('"', '""')) for k, v in sorted(d.items()))


def _f(s):
    """Formula property value (leading '=')."""
    return "=" + s.strip()


def ctl(control, **props):
    return {"Control": control, "Properties": {k: _f(v) for k, v in props.items()}}


MSG = 'Coalesce(LookUp(colMessages, code = %s, text), LookUp(colMessages, code = "MSG_ERROR", text))'
RANGE = """
// current pay period (bounded; never unbounded history): PayPeriodStartDay from AppOpen client config (default 26 only
// for display if the config is missing; the server enforces its own settings)
With({d: Today(), s: Coalesce(varStartDay, 26)},
    If(Day(d) >= s,
        Set(varFrom, Date(Year(d), Month(d), s)); Set(varTo, DateAdd(Date(Year(d), Month(d) + 1, s), -1, TimeUnit.Days)),
        Set(varFrom, Date(Year(d), Month(d) - 1, s)); Set(varTo, DateAdd(Date(Year(d), Month(d), s), -1, TimeUnit.Days))))
"""
READ = """
Set(varBusy, true);
Set(varRead, %(F)s.Run(Text(varFrom, "yyyy-mm-dd"), Text(varTo, "yyyy-mm-dd"), If(IsBlank(varAfter), "", Text(varAfter)), "%(N)d", ""));
Set(varBusy, false);
If(varRead.ok = "true",
    If(IsBlank(varAfter), Clear(colRows));
    Collect(colRows, ForAll(Table(ParseJSON(varRead.rows)), {
        id: Value(ThisRecord.Value.id), workDate: DateValue(Text(ThisRecord.Value.workDate)),
        projectId: Value(ThisRecord.Value.projectId), phaseId: Value(ThisRecord.Value.phaseId),
        workTypeId: Value(ThisRecord.Value.workTypeId), shiftId: Value(ThisRecord.Value.shiftId),
        hourTypeId: Value(ThisRecord.Value.hourTypeId), hours: Value(ThisRecord.Value.hours),
        remark: Text(ThisRecord.Value.remark), status: Text(ThisRecord.Value.status), etag: Text(ThisRecord.Value.etag)}));
    Set(varNextAfter, varRead.nextafterid),
    Notify(%(MSG)s & " (" & varRead.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_READ, "N": PAGE_SIZE, "MSG": MSG % "varRead.messagecode"}

APP_ONSTART = """
ClearCollect(colMessages, %s);
Set(varBusy, false); Set(varSaving, false); Set(varReloadRequired, false); Set(varNoTeam, false); Set(varApproving, false);
Set(varConfirm, false); Set(varTeamMode, ""); Set(varNoUnapprove, false); Set(varUnConfirm, false); Set(varPendingCount, Blank());
Set(varNoReg, false); Set(varRegPid, Blank()); Set(varRegCanEdit, false); Set(varRegLeave, false); Set(varRegSwitch, false)
""" % _table(MESSAGES)

# Power Apps Studio rejects Navigate in the start screen's OnVisible ("would automatically always navigate away"):
# OnVisible calls AppOpen and arms a hidden timer; the timer's OnTimerEnd routes (live STAGING finding).
STARTUP_ONVISIBLE = """
Set(varRoute, false);
Set(varBusy, true);
Set(varOpen, %(F)s.Run("canvas-demo"));
Set(varBusy, false);
Set(varRoute, true)
""" % {"F": FLOW_APPOPEN}

STARTUP_ROUTE = """
Set(varRoute, false);
If(varOpen.ok = "true" && varOpen.configstatus = "OK",
    Set(varCfg, ParseJSON(varOpen.config));
    Set(varStartDay, Value(Text(varCfg.settings.PayPeriodStartDay)));
    Set(varWarnEntry, Value(Text(varCfg.settings.MaxHoursPerEntryWarn)));
    Set(varWarnDay, Value(Text(varCfg.settings.MaxHoursPerDayWarn)));
    Navigate(scrMyTimesheets, ScreenTransition.None),
    Set(varDeniedCode, If(varOpen.ok = "true", "MSG_" & varOpen.configstatus, varOpen.messagecode));
    Set(varDeniedRef, varOpen.correlationid);
    Navigate(scrAccessDenied, ScreenTransition.None))
"""

# S07.5 Home pending count: the SAME guarded TS-ReadTeam Pending read as the queue (role, scope, self exclusion, Draft and
# period are decided server-side), first page of at most PENDING_PAGE rows; a further page is shown as "500+". Silent: a role
# without TS.Approve gets ROLE_NOT_ALLOWED, the count stays hidden and the Team approval button hides for the session.
# Never a client-side count of entries.
PENDING_PAGE = 500
PENDING_COUNT = """
If(!varNoTeam,
    Set(varPend, %(F)s.Run(Text(Coalesce(varTo, Today()), "yyyy-mm"), "", "%(N)d", {text_7: ""}));
    If(varPend.ok = "true",
        Set(varPendingCount, CountRows(Table(ParseJSON(varPend.rows))));
        Set(varPendingMore, !IsBlank(varPend.nextafterid) && varPend.nextafterid <> "" && varPend.nextafterid <> "0"),
        Set(varPendingCount, Blank());
        If(varPend.resultcode = "ROLE_NOT_ALLOWED", Set(varNoTeam, true))))
""" % {"F": FLOW_TEAM, "N": PENDING_PAGE}

LIST_ONVISIBLE = RANGE + ";\nSet(varAfter, Blank());\n" + READ + ";\n" + PENDING_COUNT

SAVE_ONSELECT = """
Set(varSaving, true);
Set(varSave, %(F)s.Run(If(IsBlank(varEdit), "", Text(varEdit.id)), If(IsBlank(varEdit), "", varEdit.etag),
    Text(dpWorkDate.SelectedDate, "yyyy-mm-dd"), ddProject.Selected.ProjectCode, ddPhase.Selected.PhaseCode,
    ddWorkType.Selected.WorkTypeCode, ddShift.Selected.ShiftCode, ddHourType.Selected.HourTypeCode, txtHours.Text, txtRemark.Text));
Set(varSaving, false);
ClearCollect(colWarnings, ForAll(Table(ParseJSON(varSave.warnings)), {w: Text(ThisRecord.Value)}));
If(varSave.ok = "true",
    // success stays success (AUD-F1 option B): AUDIT_DEGRADED is a warning, never a reason to save again
    Set(varReloadRequired, IsBlank(varSave.etag) || varSave.etag = "");
    Notify(%(OK)s & Concat(colWarnings, " " & %(W)s) & " (" & varSave.correlationid & ")",
           If(CountRows(colWarnings) > 0, NotificationType.Warning, NotificationType.Success));
    Set(varEdit, Blank());
    Navigate(scrMyTimesheets, ScreenTransition.None),
    Notify(%(ERR)s & " (" & varSave.correlationid & ")", NotificationType.Error);
    If(varSave.resultcode = "CONFLICT", Set(varEdit, Blank()); Navigate(scrMyTimesheets, ScreenTransition.None)))
""" % {"F": FLOW_SAVE, "OK": MSG % '"MSG_OK"', "W": MSG % "w", "ERR": MSG % "varSave.messagecode"}

# S07.2 team approval queue: the guarded backend decides access (AppStart grants nothing); ROLE_NOT_ALLOWED hides the
# navigation button for the session. The period key of the current pay period is the month of its last day (BR-DATE-02).
TEAM_READ = """
Set(varBusy, true);
Set(varTeam, %(F)s.Run(varTeamPeriod, If(IsBlank(varTeamAfter), "", Text(varTeamAfter)), "%(N)d",
    {text_7: If(varTeamMode = "Approved", "Approved", "")}));  // optional V2 trigger input Mode = key text_7, passed as a record (live finding)
Set(varBusy, false);
If(varTeam.ok = "true",
    If(IsBlank(varTeamAfter), Clear(colTeam));
    Collect(colTeam, ForAll(Table(ParseJSON(varTeam.rows)), {
        id: Value(ThisRecord.Value.id), ownerName: Text(ThisRecord.Value.ownerName), ownerCode: Text(ThisRecord.Value.ownerCode),
        workDate: DateValue(Text(ThisRecord.Value.workDate)), projectId: Value(ThisRecord.Value.projectId),
        phaseId: Value(ThisRecord.Value.phaseId), hours: Value(ThisRecord.Value.hours), remark: Text(ThisRecord.Value.remark),
        status: Text(ThisRecord.Value.status), etag: Text(ThisRecord.Value.etag),
        approvedBy: Text(ThisRecord.Value.approvedBy), approvedOn: Text(ThisRecord.Value.approvedOn)}));
    Set(varTeamNext, varTeam.nextafterid),
    If(varTeam.resultcode = "ROLE_NOT_ALLOWED",
        If(varTeamMode = "Approved", Set(varNoUnapprove, true); Set(varTeamMode, ""), Set(varNoTeam, true)));
    Notify(%(MSG)s & " (" & varTeam.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_TEAM, "N": PAGE_SIZE, "MSG": MSG % "varTeam.messagecode"}

TEAM_ONVISIBLE = """
Set(varTeamPeriod, Text(Coalesce(varTo, Today()), "yyyy-mm"));
Set(varUnConfirm, false); Set(varConfirm, false);
Set(varTeamAfter, Blank());
Clear(colSel);
""" + TEAM_READ

# per-row approval of the selected rows (1-50); the server re-checks role, scope, self, status and ETag for every row
APPROVE_ONSELECT = """
Set(varConfirm, false);
Set(varApproving, true);
Set(varAppr, %(F)s.Run(JSON(ForAll(colSel, {itemId: id, etag: etag}), JSONFormat.Compact), ""));
Set(varApproving, false);
ClearCollect(colApprRes, ForAll(Table(ParseJSON(varAppr.results)), {itemid: Text(ThisRecord.Value.itemid),
    resultcode: Text(ThisRecord.Value.resultcode), messagecode: Text(ThisRecord.Value.messagecode)}));
Notify(If(varAppr.resultcode = "OK", %(OK)s, %(MSG)s) & " (" & varAppr.correlationid & ")",
       If(varAppr.resultcode = "OK", NotificationType.Success, varAppr.resultcode = "PARTIAL", NotificationType.Warning, NotificationType.Error));
Clear(colSel);
If(Value(varAppr.approvedcount) > 0, Set(varPendingCount, Blank()));  // S07.5: a stale Home count is never shown; Home re-reads
Set(varTeamAfter, Blank());
""" % {"F": FLOW_APPROVE, "OK": MSG % '"MSG_APPROVE_OK"', "MSG": MSG % "varAppr.messagecode"} + TEAM_READ

# S07.3: one row, after the per-row confirmation; the server re-checks role (TS.Unapprove), scope, self, status and ETag
UNAPPROVE_ONSELECT = """
Set(varUnConfirm, false);
Set(varApproving, true);
Set(varUn, %(F)s.Run(Text(varUnRow.id), varUnRow.etag));
Set(varApproving, false);
ClearCollect(colApprRes, {itemid: Text(varUnRow.id), resultcode: varUn.resultcode, messagecode: varUn.messagecode});
Notify(If(varUn.resultcode = "OK", %(OK)s, %(MSG)s) & " (" & varUn.correlationid & ")",
       If(varUn.resultcode = "OK", NotificationType.Success, NotificationType.Error));
Set(varUnRow, Blank());
If(varUn.resultcode = "OK", Set(varPendingCount, Blank()));  // S07.5: a stale Home count is never shown; Home re-reads
Set(varTeamAfter, Blank());
""" % {"F": FLOW_UNAPPROVE, "OK": MSG % '"MSG_UNAPPROVE_OK"', "MSG": MSG % "varUn.messagecode"} + TEAM_READ


# R3 M1 S12.5 Hour Registration. The matrix comes only from the guarded REG-ReadMatrix (rows = the project's current
# phases, columns = every discipline; BLANK vs explicit 0 kept); edits are held in colRegEdit {k, ph, d, t} and only
# changed cells are sent to REG-SaveMatrix (one call, <= 100 cells). Read-only when the server says canedit = false.
REG_READ = """
Set(varBusy, true);
Set(varReg, %(F)s.Run(Text(varRegPid)));
Set(varBusy, false);
If(varReg.ok = "true",
    Set(varRegCanEdit, varReg.canedit = "true");
    // STT = the row's position in the project's phase order (legacy column "STT")
    ClearCollect(colRegPhases, With({t: Table(ParseJSON(varReg.phases))}, ForAll(Sequence(CountRows(t)), With({r: Index(t, Value).Value},
        {n: Value, id: Value(r.id), code: Text(r.code), name: Text(r.name)}))));
    ClearCollect(colRegDiscs, ForAll(Table(ParseJSON(varReg.disciplines)), {id: Value(ThisRecord.Value.id), code: Text(ThisRecord.Value.code),
        name: Text(ThisRecord.Value.name)}));
    ClearCollect(colRegCells, ForAll(Table(ParseJSON(varReg.cells)), {k: Text(ThisRecord.Value.phaseId) & "|" & Text(ThisRecord.Value.disciplineId),
        state: Text(ThisRecord.Value.state), value: Text(ThisRecord.Value.value), etag: Text(ThisRecord.Value.etag)})),
    Clear(colRegPhases); Clear(colRegDiscs); Clear(colRegCells);
    If(varReg.resultcode = "ROLE_NOT_ALLOWED", Set(varNoReg, true));
    Notify(If(varReg.resultcode = "ROLE_NOT_ALLOWED", %(NA)s, %(MSG)s) & " (" & varReg.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_REG_READ, "NA": MSG % '"REG_NO_ACCESS"', "MSG": MSG % "varReg.messagecode"}

REG_OPEN = "Set(varRegPid, ddRegProject.Selected.ID); Clear(colRegEdit); Set(varRegSwitch, false);\n" + REG_READ
REG_DIRTY = 'Filter(colRegEdit As e, e.t <> Coalesce(LookUp(colRegCells, k = e.k).value, ""))'
REG_INVALID = 'Filter(colRegEdit As e, !IsBlank(Trim(e.t)) && !IsMatch(Trim(e.t), "[0-9]+([.,][0-9]{1,2})?"))'
REG_SAVE = """
Set(varSaving, true);
Set(varRegSave, %(F)s.Run(Text(varRegPid), JSON(ForAll(%(DIRTY)s As c, {phaseId: c.ph, disciplineId: c.d,
    state: If(IsBlank(Trim(c.t)), "blank", "value"), value: Substitute(Trim(c.t), ",", "."),
    etag: Coalesce(LookUp(colRegCells, k = c.k).etag, "")}), JSONFormat.Compact), GUID()));
Set(varSaving, false);
ClearCollect(colRegRes, ForAll(Table(ParseJSON(varRegSave.results)), {k: Text(ThisRecord.Value.phaseId) & "|" & Text(ThisRecord.Value.disciplineId),
    rc: Text(ThisRecord.Value.resultcode)}));
// committed / unchanged cells leave the edit set; refused or conflicting cells stay dirty against the reloaded values
ClearCollect(colRegEditTmp, Filter(colRegEdit As e, !(e.k in Filter(colRegRes, rc = "OK" || rc = "NO_CHANGE").k)));
ClearCollect(colRegEdit, colRegEditTmp);
Notify(Switch(varRegSave.resultcode, "OK", %(OK)s, "REFUSED", %(REF)s, "PARTIAL", %(PAR)s, %(MSG)s) & " (" & varRegSave.correlationid & ")",
    Switch(varRegSave.resultcode, "OK", NotificationType.Success, "PARTIAL", NotificationType.Warning, NotificationType.Error));
""" % {"F": FLOW_REG_SAVE, "DIRTY": REG_DIRTY, "OK": MSG % '"REG_OK"', "REF": MSG % '"REG_REFUSED"', "PAR": MSG % '"REG_PARTIAL"',
       "MSG": MSG % "varRegSave.messagecode"} + REG_READ
REG_CELL = 'Text(ThisItem.phid) & "|" & Text(ThisItem.id)'
REG_CELL_ORIG = 'Coalesce(LookUp(colRegCells, k = %s).value, "")' % REG_CELL
REG_CELL_EDIT = "LookUp(colRegEdit, k = %s)" % REG_CELL
REG_ONVISIBLE = """
Set(varRegLeave, false); Set(varRegSwitch, false);
ClearCollect(colRegYears, {y: "All"});
Collect(colRegYears, ForAll(Sort(Distinct(Filter(Projects, !IsBlank(ProjectYear)), ProjectYear), Value), {y: Text(Value)}));
If(!IsBlank(varRegPid), """ + REG_READ.strip() + """)
"""


def _mode(label, value):
    return ("Set(varTeamMode, %s); Set(varConfirm, false); Set(varUnConfirm, false); Clear(colSel); Clear(colApprRes); "
            "Set(varTeamAfter, Blank());\n" % value) + TEAM_READ


PHASES_FOR_PROJECT = ("Filter(Phases, IsActive, ID in ForAll(Filter(ProjectPhases, ProjectItemId = ddProject.Selected.ID, IsActive), Phase.Id))")


LOCK_FILL = 'If(ThisItem.status = "Approved", RGBA(242, 242, 242, 1), RGBA(0, 0, 0, 0))'  # neutral read-only fill; meaning carried by the icon


def lock_icon(x):
    """Approved = locked: lock icon at the row start (legacy row-header lock, F-APPR-04 / BR-APPR-06); Draft rows show none.
    Driven only by the status returned by the guarded read."""
    return ctl("Classic/Icon@2.5.0", Icon="Icon.Lock", X=x, Y="20", Width="24", Height="24", Visible='ThisItem.status = "Approved"',
               Tooltip='"Đã phê duyệt"', AccessibleLabel='"Đã phê duyệt"')


def screens() -> dict:
    hdr = lambda t: ctl("Label@2.5.1", Text='"%s"' % t, X="20", Y="10", Width="Parent.Width - 40", Height="50", Size="20",  # noqa: E731
                        FontWeight="FontWeight.Bold")
    busy = ctl("Label@2.5.1", Text='If(varBusy || varSaving, "Working…", "")', X="20", Y="60", Width="400", Height="30")
    lookup = lambda src, idf, field: "LookUp(%s, ID = %s, %s)" % (src, idf, field)  # noqa: E731
    return {
        "scrStartup": {"Properties": {"OnVisible": _f(STARTUP_ONVISIBLE)},
                       "Children": [{"tmrRoute": ctl("Timer@2.1.0", Duration="1", Start="varRoute", AutoStart="false", Repeat="false",
                                                     Visible="false", OnTimerEnd=STARTUP_ROUTE)},
                                    {"lblTitle": hdr("Timesheet")}, {"lblBusy": busy},
                                    {"lblLoading": ctl("Label@2.5.1", Text='"Loading your timesheet…"', X="20", Y="100", Width="600", Height="40")}]},
        "scrAccessDenied": {"Children": [
            {"lblTitle": hdr("Timesheet is not available")},
            {"lblReason": ctl("Label@2.5.1", Text=MSG % "varDeniedCode", X="20", Y="80", Width="Parent.Width - 40", Height="80")},
            {"lblRef": ctl("Label@2.5.1", Text='"Reference: " & varDeniedRef', X="20", Y="170", Width="600", Height="30")},
            {"btnRetry": ctl("Classic/Button@2.2.0", Text='"Try again"', X="20", Y="220", OnSelect="Navigate(scrStartup, ScreenTransition.None)")}]},
        "scrMyTimesheets": {"Properties": {"OnVisible": _f(LIST_ONVISIBLE)}, "Children": [
            {"lblTitle": hdr("My timesheet")}, {"lblBusy": busy},
            {"lblRange": ctl("Label@2.5.1", Text='"Pay period " & Text(varFrom, "dd/mm/yyyy") & " – " & Text(varTo, "dd/mm/yyyy")',
                             X="20", Y="90", Width="600", Height="30")},
            {"btnNew": ctl("Classic/Button@2.2.0", Text='"New entry"', X="20", Y="130", DisplayMode="If(varBusy, DisplayMode.Disabled, DisplayMode.Edit)",
                           OnSelect="Set(varEdit, Blank()); Navigate(scrEntry, ScreenTransition.None)")},
            {"btnRefresh": ctl("Classic/Button@2.2.0", Text='"Refresh"', X="200", Y="130",
                               OnSelect="Set(varAfter, Blank());\n" + READ)},
            {"btnTeam": ctl("Classic/Button@2.2.0", Text='"Team approval"', X="380", Y="130", Width="200", Visible="!varNoTeam",
                            OnSelect="Navigate(scrTeamApproval, ScreenTransition.None)")},
            {"lblPending": ctl("Label@2.5.1", X="600", Y="130", Width="400", Height="40", FontWeight="FontWeight.Bold",
                               Visible="!varNoTeam && !IsBlank(varPendingCount)",
                               Text='"Chờ phê duyệt: " & If(varPendingMore, "%d+", Text(varPendingCount))' % PENDING_PAGE)},
            {"btnReg": ctl("Classic/Button@2.2.0", Text='"Đăng ký công"', X="1020", Y="130", Width="200", Visible="!varNoReg",
                           OnSelect="Navigate(scrHourRegistration, ScreenTransition.None)")},
            {"galEntries": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("SortByColumns(colRows, \"workDate\", SortOrder.Descending, \"id\", SortOrder.Descending)"),
                "X": "=20", "Y": "=180", "Width": "=Parent.Width - 40", "Height": "=Parent.Height - 260", "TemplateSize": "=70",
                "TemplateFill": _f(LOCK_FILL)},
                "Children": [
                    {"lblLine1": ctl("Label@2.5.1", X="44", Y="5", Width="Parent.TemplateWidth - 164", Height="30",
                                     Text='Text(ThisItem.workDate, "dd/mm/yyyy") & "  ·  " & %s & " / " & %s & "  ·  " & Text(ThisItem.hours) & " h  ·  " & ThisItem.status'
                                     % (lookup("Projects", "ThisItem.projectId", "ProjectCode"), lookup("Phases", "ThisItem.phaseId", "PhaseCode")))},
                    {"lblLine2": ctl("Label@2.5.1", X="44", Y="35", Width="Parent.TemplateWidth - 54", Height="30",
                                     Text='%s & "  ·  " & ThisItem.remark' % lookup("WorkTypes", "ThisItem.workTypeId", "Title"))},
                    {"btnEdit": ctl("Classic/Button@2.2.0", Text='"Edit"', X="Parent.TemplateWidth - 110", Y="15", Width="90",
                                    Visible='ThisItem.status = "Draft"',
                                    OnSelect="Set(varEdit, ThisItem); Navigate(scrEntry, ScreenTransition.None)")},
                    {"icoLock": lock_icon("10")}]}},
            {"btnMore": ctl("Classic/Button@2.2.0", Text='"Load more"', X="20", Y="Parent.Height - 70",
                            Visible="!IsBlank(varNextAfter) && varNextAfter <> \"\" && varNextAfter <> \"0\"",  # contract: nextafterid 0 = no more pages
                            OnSelect="Set(varAfter, Value(varNextAfter));\n" + READ)}]},
        "scrTeamApproval": {"Properties": {"OnVisible": _f(TEAM_ONVISIBLE)}, "Children": [
            {"lblTeamTitle": hdr("Team approval")},
            {"lblTeamBusy": ctl("Label@2.5.1", Text='If(varBusy || varApproving, "Working…", "")', X="20", Y="60", Width="400", Height="30")},
            {"lblTeamPeriod": ctl("Label@2.5.1", Text='"Pay period " & varTeamPeriod & "  ·  " & If(varTeamMode = "Approved", "Approved entries: ", "Draft entries waiting for approval: ") & CountRows(colTeam)',
                                  X="20", Y="90", Width="800", Height="30")},
            {"btnTeamBack": ctl("Classic/Button@2.2.0", Text='"Back"', X="20", Y="130", Width="120",
                                OnSelect="Navigate(scrMyTimesheets, ScreenTransition.None)")},
            {"btnSelAll": ctl("Classic/Button@2.2.0", Text='"Select all on page"', X="160", Y="130", Width="200", Visible='varTeamMode <> "Approved"',
                              OnSelect="ClearCollect(colSel, ForAll(colTeam, {id: id, etag: etag}))")},
            {"btnApprove": ctl("Classic/Button@2.2.0", Text='"Phê duyệt (" & CountRows(colSel) & ")"', X="380", Y="130", Width="200",
                               Visible='varTeamMode <> "Approved"',
                               DisplayMode="If(varApproving || varBusy || CountRows(colSel) = 0 || CountRows(colSel) > 50, DisplayMode.Disabled, DisplayMode.Edit)",
                               OnSelect="Set(varConfirm, true)")},
            {"btnModePending": ctl("Classic/Button@2.2.0", Text='"Pending"', X="740", Y="130", Width="130", OnSelect=_mode("Pending", '""'))},
            {"btnModeApproved": ctl("Classic/Button@2.2.0", Text='"Approved"', X="880", Y="130", Width="130", Visible="!varNoUnapprove",
                                    OnSelect=_mode("Approved", '"Approved"'))},
            {"lblUnConfirm": ctl("Label@2.5.1", Text=(MSG % '"MSG_UNAPPROVE_CONFIRM"') + ' & " #" & varUnRow.id', X="20", Y="175", Width="560",
                                 Height="30", Visible="varUnConfirm", FontWeight="FontWeight.Bold")},
            {"btnUnYes": ctl("Classic/Button@2.2.0", Text='"Yes"', X="600", Y="175", Width="90", Height="40", Visible="varUnConfirm",
                             DisplayMode="If(varApproving, DisplayMode.Disabled, DisplayMode.Edit)", OnSelect=UNAPPROVE_ONSELECT)},
            {"btnUnNo": ctl("Classic/Button@2.2.0", Text='"No"', X="700", Y="175", Width="90", Height="40", Visible="varUnConfirm",
                            OnSelect="Set(varUnConfirm, false); Set(varUnRow, Blank())")},
            {"btnTeamRefresh": ctl("Classic/Button@2.2.0", Text='"Refresh"', X="600", Y="130", Width="120",
                                   OnSelect="Clear(colSel); Set(varTeamAfter, Blank());\n" + TEAM_READ)},
            # the confirm row must not overlap the gallery (live STAGING: the gallery intercepted clicks on Yes)
            {"lblConfirm": ctl("Label@2.5.1", Text=MSG % '"MSG_APPROVE_CONFIRM"', X="20", Y="175", Width="560", Height="30", Visible="varConfirm",
                               FontWeight="FontWeight.Bold")},
            {"btnConfirmYes": ctl("Classic/Button@2.2.0", Text='"Yes"', X="600", Y="175", Width="90", Height="40", Visible="varConfirm",
                                  DisplayMode="If(varApproving, DisplayMode.Disabled, DisplayMode.Edit)", OnSelect=APPROVE_ONSELECT)},
            {"btnConfirmNo": ctl("Classic/Button@2.2.0", Text='"No"', X="700", Y="175", Width="90", Height="40", Visible="varConfirm",
                                 OnSelect="Set(varConfirm, false)")},
            {"galTeam": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("SortByColumns(colTeam, \"workDate\", SortOrder.Descending, \"id\", SortOrder.Descending)"),
                "X": "=20", "Y": "=240", "Width": "=Parent.Width - 40", "Height": "=Parent.Height - 490", "TemplateSize": "=70",
                "TemplateFill": _f(LOCK_FILL)},
                "Children": [
                    {"btnSel": ctl("Classic/Button@2.2.0", Text='If(ThisItem.id in colSel.id, "[x]", "[ ]")', X="5", Y="15", Width="60",
                                   Visible='varTeamMode <> "Approved"',
                                   OnSelect="If(ThisItem.id in colSel.id, ClearCollect(colSelTmp, Filter(colSel, id <> ThisItem.id)); ClearCollect(colSel, colSelTmp), Collect(colSel, {id: ThisItem.id, etag: ThisItem.etag}))")},
                    {"lblTeam1": ctl("Label@2.5.1", X="80", Y="5", Width="Parent.TemplateWidth - 90", Height="30",
                                     Text='ThisItem.ownerName & " (" & ThisItem.ownerCode & ")  ·  " & Text(ThisItem.workDate, "dd/mm/yyyy") & "  ·  " & %s & " / " & %s & "  ·  " & Text(ThisItem.hours) & " h"'
                                     % (lookup("Projects", "ThisItem.projectId", "ProjectCode"), lookup("Phases", "ThisItem.phaseId", "PhaseCode")))},
                    {"lblTeam2": ctl("Label@2.5.1", X="80", Y="35", Width="Parent.TemplateWidth - 280", Height="30",
                                     Text='"#" & ThisItem.id & "  ·  " & ThisItem.status & If(ThisItem.status = "Approved", " by " & ThisItem.approvedBy & " " & ThisItem.approvedOn, "") & "  ·  " & ThisItem.remark')},
                    {"btnUnapprove": ctl("Classic/Button@2.2.0", Text='"Hủy phê duyệt"', X="Parent.TemplateWidth - 190", Y="15", Width="170",
                                         Visible='varTeamMode = "Approved" && ThisItem.status = "Approved"',
                                         DisplayMode="If(varApproving || varBusy, DisplayMode.Disabled, DisplayMode.Edit)",
                                         OnSelect="Set(varUnRow, ThisItem); Set(varUnConfirm, true)")},
                    {"icoTeamLock": lock_icon("30")}]}},
            {"btnTeamMore": ctl("Classic/Button@2.2.0", Text='"Load more"', X="20", Y="Parent.Height - 240",
                                Visible="!IsBlank(varTeamNext) && varTeamNext <> \"\" && varTeamNext <> \"0\"",
                                OnSelect="Set(varTeamAfter, Value(varTeamNext));\n" + TEAM_READ)},
            {"lblResTitle": ctl("Label@2.5.1", Text='If(CountRows(colApprRes) > 0, "Last approval results", "")', X="20", Y="Parent.Height - 195",
                                Width="600", Height="30", FontWeight="FontWeight.Bold")},
            {"galResults": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("colApprRes"), "X": "=20", "Y": "=Parent.Height - 160", "Width": "=Parent.Width - 40", "Height": "=150",
                "TemplateSize": "=30"},
                "Children": [
                    {"lblRes": ctl("Label@2.5.1", X="5", Y="0", Width="Parent.TemplateWidth - 10", Height="30",
                                   Text='"#" & ThisItem.itemid & ": " & If(ThisItem.resultcode = "OK", If(varTeamMode = "Approved", %s, %s), %s)'
                                   % (MSG % '"MSG_ROW_UNAPPROVED"', MSG % '"MSG_ROW_APPROVED"', MSG % "ThisItem.messagecode"))}]}}]},
        "scrHourRegistration": {"Properties": {"OnVisible": _f(REG_ONVISIBLE)}, "Children": [
            {"lblRegTitle": hdr("Đăng ký công")},
            {"lblRegBusy": ctl("Label@2.5.1", Text='If(varBusy || varSaving, "Working…", "")', X="20", Y="60", Width="400", Height="30")},
            {"btnRegBack": ctl("Classic/Button@2.2.0", Text='"Back"', X="20", Y="100", Width="120",
                               OnSelect="If(CountRows(%s) > 0, Set(varRegLeave, true), Navigate(scrMyTimesheets, ScreenTransition.None))" % REG_DIRTY)},
            {"ddRegYear": ctl("Classic/DropDown@2.3.1", X="160", Y="100", Width="140", Items="colRegYears", **{"Items.Value": "y"})},
            {"ddRegProject": ctl("Classic/DropDown@2.3.1", X="320", Y="100", Width="600",
                                 Items='SortByColumns(AddColumns(If(ddRegYear.Selected.y = "All", Projects, Filter(Projects, ProjectYear = Value(ddRegYear.Selected.y))), "Label", ProjectCode & " — " & Title), "Label", SortOrder.Ascending)',
                                 Default="If(IsBlank(varRegPid), Blank(), LookUp(Projects, ID = varRegPid).Title)",
                                 OnChange="If(CountRows(%s) > 0, Set(varRegSwitch, true), %s)" % (REG_DIRTY, "Set(varRegPid, ddRegProject.Selected.ID); Clear(colRegEdit);\n" + REG_READ.strip()),
                                 **{"Items.Value": "Label"})},
            {"btnRegReload": ctl("Classic/Button@2.2.0", Text='"Tải lại"', X="940", Y="100", Width="120",
                                 DisplayMode="If(IsBlank(varRegPid) || varBusy || varSaving, DisplayMode.Disabled, DisplayMode.Edit)",
                                 OnSelect="If(CountRows(%s) > 0, Set(varRegSwitch, true), %s)" % (REG_DIRTY, REG_READ.strip()))},
            {"btnRegSave": ctl("Classic/Button@2.2.0", Text='If(varSaving, "Saving…", "Lưu (" & CountRows(%s) & ")")' % REG_DIRTY,
                               X="1080", Y="100", Width="160", Visible="varRegCanEdit",
                               DisplayMode="If(varSaving || varBusy || IsBlank(varRegPid) || CountRows(%s) = 0 || CountRows(%s) > 0 || CountRows(%s) > 100, DisplayMode.Disabled, DisplayMode.Edit)"
                                           % (REG_DIRTY, REG_INVALID, REG_DIRTY),
                               OnSelect=REG_SAVE)},
            {"lblRegInfo": ctl("Label@2.5.1", X="20", Y="145", Width="1200", Height="30",
                               Text='If(IsBlank(varRegPid), "", If(varRegCanEdit, "", "Chỉ xem  ·  ") & "Công đăng ký cho dự án (công)" & If(CountRows(%s) > 0, "  ·  " & %s, ""))'
                                    % (REG_INVALID, MSG % '"REG_INVALID"'))},
            {"lblRegLeave": ctl("Label@2.5.1", Text=MSG % '"REG_LEAVE"', X="20", Y="180", Width="560", Height="30", FontWeight="FontWeight.Bold",
                                Visible="varRegLeave || varRegSwitch")},
            {"btnRegLeaveYes": ctl("Classic/Button@2.2.0", Text='"Yes"', X="600", Y="180", Width="90", Height="40", Visible="varRegLeave || varRegSwitch",
                                   OnSelect="Clear(colRegEdit); If(varRegLeave, Set(varRegLeave, false); Navigate(scrMyTimesheets, ScreenTransition.None), "
                                            "Set(varRegSwitch, false); Set(varRegPid, ddRegProject.Selected.ID);\n" + REG_READ.strip() + ")")},
            {"btnRegLeaveNo": ctl("Classic/Button@2.2.0", Text='"No"', X="700", Y="180", Width="90", Height="40", Visible="varRegLeave || varRegSwitch",
                                  OnSelect="Set(varRegLeave, false); Set(varRegSwitch, false); Reset(ddRegProject)")},
            {"galRegHead": {"Control": "Gallery@2.15.0", "Variant": "Horizontal", "Properties": {
                "Items": _f("colRegDiscs"), "X": "=300", "Y": "=230", "Width": "=Parent.Width - 320", "Height": "=40", "TemplateSize": "=100",
                "Visible": _f("!IsBlank(varRegPid)")},
                "Children": [{"lblRegHead": ctl("Label@2.5.1", X="0", Y="0", Width="96", Height="40", Text="ThisItem.name", Align="Align.Center",
                                                FontWeight="FontWeight.Bold")}]}},
            {"galRegRows": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("colRegPhases"), "X": "=20", "Y": "=275", "Width": "=Parent.Width - 40", "Height": "=Parent.Height - 295",
                "TemplateSize": "=50", "Visible": _f("!IsBlank(varRegPid)")},
                "Children": [
                    {"lblRegPhase": ctl("Label@2.5.1", X="0", Y="5", Width="270", Height="40",
                                        Text='Text(ThisItem.n) & ".  " & ThisItem.code & "  ·  " & ThisItem.name')},
                    {"galRegCells": {"Control": "Gallery@2.15.0", "Variant": "Horizontal", "Properties": {
                        "Items": _f('AddColumns(colRegDiscs, "phid", ThisItem.id)'), "X": "=280", "Y": "=0", "Width": "=Parent.TemplateWidth - 290",
                        "Height": "=50", "TemplateSize": "=100"},
                        "Children": [
                            {"txtRegCell": ctl("Classic/TextInput@2.3.2", X="2", Y="5", Width="92", Height="40", Align="Align.Center",
                                               HintText='"—"',
                                               Default="If(IsBlank(%s), %s, %s.t)" % (REG_CELL_EDIT, REG_CELL_ORIG, REG_CELL_EDIT),
                                               DisplayMode="If(varRegCanEdit && !varSaving, DisplayMode.Edit, DisplayMode.View)",
                                               Fill='If(Self.Text <> %s, RGBA(255, 244, 206, 1), RGBA(255, 255, 255, 1))' % REG_CELL_ORIG,
                                               BorderColor='If(!IsBlank(Trim(Self.Text)) && !IsMatch(Trim(Self.Text), "[0-9]+([.,][0-9]{1,2})?"), RGBA(196, 49, 75, 1), RGBA(166, 166, 166, 1))',
                                               AccessibleLabel='ThisItem.name & " / " & LookUp(colRegPhases, id = ThisItem.phid).name',
                                               OnChange="ClearCollect(colRegEditTmp, Filter(colRegEdit, k <> %s)); Collect(colRegEditTmp, {k: %s, ph: ThisItem.phid, d: ThisItem.id, t: Self.Text}); ClearCollect(colRegEdit, colRegEditTmp)"
                                                        % (REG_CELL, REG_CELL))}]}}]}}]},
        "scrEntry": {"Children": [
            {"lblTitle": ctl("Label@2.5.1", Text='If(IsBlank(varEdit), "New entry", "Edit draft")', X="20", Y="10", Width="600", Height="50",
                             Size="20", FontWeight="FontWeight.Bold")}, {"lblBusy": busy},
            {"dpWorkDate": ctl("Classic/DatePicker@2.6.0", X="20", Y="100", Width="300",
                               DefaultDate="If(IsBlank(varEdit), Today(), varEdit.workDate)", Format='"dd/mm/yyyy"')},
            {"ddProject": ctl("Classic/DropDown@2.3.1", X="20", Y="150", Width="400", Items='Filter(Projects, Status.Value = "Active")',
                              Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("Projects", "varEdit.projectId", "ProjectCode"), **{"Items.Value": "ProjectCode"})},
            {"ddPhase": ctl("Classic/DropDown@2.3.1", X="20", Y="200", Width="400", Items=PHASES_FOR_PROJECT,
                            Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("Phases", "varEdit.phaseId", "PhaseCode"), **{"Items.Value": "PhaseCode"})},
            {"ddWorkType": ctl("Classic/DropDown@2.3.1", X="20", Y="250", Width="400", Items="Filter(WorkTypes, IsActive)",
                               Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("WorkTypes", "varEdit.workTypeId", "WorkTypeCode"), **{"Items.Value": "WorkTypeCode"})},
            {"ddShift": ctl("Classic/DropDown@2.3.1", X="20", Y="300", Width="400", Items="Filter(Shifts, IsActive)",
                            Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("Shifts", "varEdit.shiftId", "ShiftCode"), **{"Items.Value": "ShiftCode"})},
            {"ddHourType": ctl("Classic/DropDown@2.3.1", X="20", Y="350", Width="400", Items="HourTypes",
                               Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("HourTypes", "varEdit.hourTypeId", "HourTypeCode"), **{"Items.Value": "HourTypeCode"})},
            {"txtHours": ctl("Classic/TextInput@2.3.2", X="20", Y="400", Width="200", Format="TextFormat.Number",
                             Default='If(IsBlank(varEdit), "", Text(varEdit.hours))', HintText='"Hours"')},
            {"lblHoursHint": ctl("Label@2.5.1", X="240", Y="400", Width="500", Height="40",
                                 Text='If(Value(txtHours.Text) > Coalesce(varWarnEntry, 4), "Above the usual maximum per entry — you can still save.", "")')},
            {"txtRemark": ctl("Classic/TextInput@2.3.2", X="20", Y="450", Width="600", Mode="TextMode.MultiLine", Height="80",
                              Default='If(IsBlank(varEdit), "", varEdit.remark)', HintText='"Remark (optional)"')},
            {"btnSave": ctl("Classic/Button@2.2.0", Text='If(varSaving, "Saving…", "Save")', X="20", Y="550",
                            DisplayMode="If(varSaving || IsBlank(ddProject.Selected) || IsBlank(ddPhase.Selected) || IsBlank(ddWorkType.Selected) "
                                        "|| IsBlank(ddShift.Selected) || IsBlank(ddHourType.Selected) || IsBlank(txtHours.Text), DisplayMode.Disabled, DisplayMode.Edit)",
                            OnSelect=SAVE_ONSELECT)},
            {"btnCancel": ctl("Classic/Button@2.2.0", Text='"Cancel"', X="200", Y="550", DisplayMode="If(varSaving, DisplayMode.Disabled, DisplayMode.Edit)",
                              OnSelect="Set(varEdit, Blank()); Navigate(scrMyTimesheets, ScreenTransition.None)")}]},
    }


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, v):  # multi-line formulas as literal blocks (readable, pasteable into Power Apps Studio code view)
    return dumper.represent_scalar("tag:yaml.org,2002:str", v, style="|" if "\n" in v else None)


_Dumper.add_representer(str, _str)


def build(out_dir: str) -> list:
    os.makedirs(out_dir, exist_ok=True)
    files = []
    app = {"App": {"Properties": {"OnStart": _f(APP_ONSTART), "StartScreen": "=scrStartup"}}}
    for name, doc in [("App", app)] + [(n, {"Screens": {n: s}}) for n, s in screens().items()]:
        p = os.path.join(out_dir, name + ".pa.yaml")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# GENERATED by tools/powerapp/build_demo_app.py — R1 DEMO (provisional wording; R1-Q4 open). Do not edit by hand.\n")
            yaml.dump(doc, fh, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=200)
        files.append(p)
    p = os.path.join(out_dir, "messages.json")
    json.dump({"status": "PROVISIONAL DEMO WORDING (R1-Q4 open)", "messages": MESSAGES}, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return files + [p]


if __name__ == "__main__":
    for f in build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-r1")):
        print(f)
