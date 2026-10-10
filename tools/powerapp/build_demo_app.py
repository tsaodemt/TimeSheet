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
# R3 M2 EPIC 16 Project Effort (guarded; no direct list access)
FLOW_EFF_READ, FLOW_EFF_SAVE, FLOW_EFF_PM = "'EFF-ReadProjectEffort'", "'EFF-SaveProjectEffort'", "'EFF-SetProjectPm'"
# R3 M3 EPIC 17 Discipline Effort (guarded; no direct list access)
FLOW_DE_READ, FLOW_DE_SAVE, FLOW_DE_APPROVE = "'EFF-ReadDisciplineEffort'", "'EFF-SaveDisciplineEffort'", "'EFF-ApproveDisciplineEffort'"
# R3 M4 current-scope reports (OD-50: in-app, guarded, aggregate-only)
FLOW_RPT_PROJECT, FLOW_RPT_DISCIPLINE = "'RPT-ProjectReport'", "'RPT-DisciplineReport'"
REFERENCE_SOURCES = ("Projects", "ProjectPhases", "Phases", "WorkTypes", "Shifts", "HourTypes")
PROTECTED_LISTS = ("TimesheetEntries", "AuditLog", "Employees", "AppSettings", "HourRegistrations", "ProjectPmAssignments",
                   "ProjectEffortAllocations", "DisciplineEffortRegistrations", "DisciplineEffortLocks")
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
    # R3 M2 EPIC 16 Project Effort (Công dự án)
    "EFF_OK": "Đã lưu công dự án.",
    "EFF_REFUSED": "Chưa lưu: có giá trị không hợp lệ hoặc vừa được người khác thay đổi. Dữ liệu đã được tải lại; các giá trị bạn sửa vẫn được giữ.",
    "EFF_PARTIAL": "Đã lưu một phần: một số giá trị vừa được người khác thay đổi. Dữ liệu đã được tải lại; các giá trị chưa lưu vẫn được giữ.",
    "EFF_INVALID": "Giá trị phải là số lớn hơn hoặc bằng 0, tối đa 2 chữ số thập phân.",
    "EFF_LEAVE": "Có thay đổi chưa lưu. Bỏ các thay đổi này?",
    "EFF_NO_ACCESS": "Bạn không có quyền xem Công dự án.",
    "EFF_NO_PM": "Dự án chưa có PM: chưa thể nhập công dự án.",
    "EFF_PM_OK": "Đã cập nhật PM của dự án.",
    "EFF_PM_SAME": "PM của dự án không thay đổi.",
    "EFF_CONFIG_INVALID": "Cấu hình Công dự án chưa hợp lệ. Vui lòng liên hệ quản trị.",
    # R3 M3 EPIC 17 Discipline Effort (Công bộ môn)
    "DE_OK": "Đã lưu công bộ môn.",
    "DE_REFUSED": "Chưa lưu: có giá trị không hợp lệ, vượt trần công bộ môn hoặc vừa được người khác thay đổi. Dữ liệu đã được tải lại; các giá trị bạn sửa vẫn được giữ.",
    "DE_INVALID": "Giá trị phải là số lớn hơn hoặc bằng 0, tối đa 2 chữ số thập phân.",
    "DE_LEAVE": "Có thay đổi chưa lưu. Bỏ các thay đổi này?",
    "DE_NO_ACCESS": "Bạn không có quyền xem Công bộ môn.",
    "DE_APPROVE_CONFIRM": "Phê duyệt các dòng đã chọn? Sau khi phê duyệt, dòng bị khóa và không mở lại được.",
    "DE_APPROVED": "Đã phê duyệt và khóa các dòng đã chọn.",
    "DE_APPROVE_PARTIAL": "Đã phê duyệt một phần; các dòng còn lại bị từ chối (xem kết quả).",
    "DE_APPROVE_REFUSED": "Không dòng nào được phê duyệt (xem kết quả).",
    "MSG_OVER_CEILING": "Vượt trần công bộ môn của dự án (Công dự án).",
    "MSG_CEILING_NOT_REGISTERED": "Bộ môn chưa có trần công trong Công dự án: chưa thể nhập giá trị.",
    "MSG_VALIDATION_VALUE": "Giá trị phải là số lớn hơn hoặc bằng 0, tối đa 2 chữ số thập phân.",
    "MSG_TECHNICAL_LIMIT": "Giá trị vượt giới hạn kỹ thuật.",
    "MSG_NO_CHANGE": "Không có thay đổi.",
    # R3 M4 Báo cáo công (current scope: effort only, OD-20)
    "RPT_NO_ACCESS": "Bạn không có quyền xem báo cáo này.",
    "RPT_EMPTY": "Không có dữ liệu trong phạm vi của bạn.",
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
Set(varNoReg, false); Set(varRegPid, Blank()); Set(varRegCanEdit, false); Set(varRegLeave, false); Set(varRegSwitch, false);
Set(varNoEff, false); Set(varEffPid, Blank()); Set(varEffCanEdit, false); Set(varEffCanAssign, false); Set(varEffLeave, false); Set(varEffSwitch, false);
Set(varNoDe, false); Set(varDePid, Blank()); Set(varDeCanEdit, false); Set(varDeCanApprove, false); Set(varDeLeave, false); Set(varDeSwitch, false);
Set(varDeConfirm, false);
Set(varNoRptP, false); Set(varNoRptD, false); Set(varRptTab, "project")
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
Collect(colRegYears, ForAll(Sequence(34, 2017), {y: Text(Value)}));  // legacy F-REG-01: All + 2017..2050 (fixed list)
If(!IsBlank(varRegPid), """ + REG_READ.strip() + """)
"""

# R3 M2 EPIC 16 Project Effort ("Công dự án"). Projects the caller may view come from EFF-ReadProjectEffort list mode
# (PMO / Executive: all; the designated PM: own projects); one project's recipients, PM, planned total and Approved actual
# total come from detail mode. Edits are held in colEffEdit {k, t}; only changed recipients go to EFF-SaveProjectEffort.
# Editable only when the server says canedit (the project's PM); PMO assigns / changes the PM via EFF-SetProjectPm.
EFF_LIST = """
Set(varBusy, true);
Set(varEffList, %(F)s.Run("0"));
Set(varBusy, false);
If(varEffList.ok = "true",
    Set(varEffCanAssign, varEffList.canassignpm = "true");
    ClearCollect(colEffProjects, ForAll(Table(ParseJSON(varEffList.projects)), {id: Value(ThisRecord.Value.id), code: Text(ThisRecord.Value.code),
        name: Text(ThisRecord.Value.name), pmName: Text(ThisRecord.Value.pmName), canEdit: Boolean(ThisRecord.Value.canEdit)})),
    Clear(colEffProjects);
    If(varEffList.resultcode = "ROLE_NOT_ALLOWED", Set(varNoEff, true));
    Notify(If(varEffList.resultcode = "ROLE_NOT_ALLOWED", %(NA)s, %(MSG)s) & " (" & varEffList.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_EFF_READ, "NA": MSG % '"EFF_NO_ACCESS"', "MSG": MSG % "varEffList.messagecode"}
EFF_READ = """
Set(varBusy, true);
Set(varEff, %(F)s.Run(Text(varEffPid)));
Set(varBusy, false);
If(varEff.ok = "true",
    Set(varEffCanEdit, varEff.canedit = "true");
    Set(varEffCanAssign, varEff.canassignpm = "true");
    Set(varEffPmName, Text(ParseJSON(varEff.pm).name)); Set(varEffPmCode, Text(ParseJSON(varEff.pm).code));
    ClearCollect(colEffRecs, ForAll(Table(ParseJSON(varEff.recipients)), {key: Text(ThisRecord.Value.key), label: Text(ThisRecord.Value.label),
        state: Text(ThisRecord.Value.state), value: Text(ThisRecord.Value.value), etag: Text(ThisRecord.Value.etag)}));
    ClearCollect(colEffEmps, ForAll(Table(ParseJSON(varEff.employees)), {id: Value(ThisRecord.Value.id), name: Text(ThisRecord.Value.name),
        code: Text(ThisRecord.Value.code)})),
    Set(varEffCanEdit, false); Clear(colEffRecs); Clear(colEffEmps); Set(varEffPmName, ""); Set(varEffPmCode, "");
    Notify(If(varEff.resultcode = "CONFIG_INVALID", %(CI)s, %(MSG)s) & " (" & varEff.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_EFF_READ, "CI": MSG % '"EFF_CONFIG_INVALID"', "MSG": MSG % "varEff.messagecode"}
EFF_DIRTY = 'Filter(colEffEdit As e, e.t <> Coalesce(LookUp(colEffRecs, key = e.k).value, ""))'
EFF_INVALID = 'Filter(colEffEdit As e, !IsBlank(Trim(e.t)) && !IsMatch(Trim(e.t), "[0-9]+([.,][0-9]{1,2})?"))'
EFF_SAVE = """
Set(varSaving, true);
Set(varEffSave, %(F)s.Run(Text(varEffPid), JSON(ForAll(%(DIRTY)s As c, {key: c.k,
    state: If(IsBlank(Trim(c.t)), "blank", "value"), value: Substitute(Trim(c.t), ",", "."),
    etag: Coalesce(LookUp(colEffRecs, key = c.k).etag, "")}), JSONFormat.Compact), GUID()));
Set(varSaving, false);
ClearCollect(colEffRes, ForAll(Table(ParseJSON(varEffSave.results)), {k: Text(ThisRecord.Value.key), rc: Text(ThisRecord.Value.resultcode)}));
// committed / unchanged recipients leave the edit set; refused or conflicting ones stay dirty against the reloaded values
ClearCollect(colEffEditTmp, Filter(colEffEdit As e, !(e.k in Filter(colEffRes, rc = "OK" || rc = "NO_CHANGE").k)));
ClearCollect(colEffEdit, colEffEditTmp);
Notify(Switch(varEffSave.resultcode, "OK", %(OK)s, "REFUSED", %(REF)s, "PARTIAL", %(PAR)s, %(MSG)s) & " (" & varEffSave.correlationid & ")",
    Switch(varEffSave.resultcode, "OK", NotificationType.Success, "PARTIAL", NotificationType.Warning, NotificationType.Error));
""" % {"F": FLOW_EFF_SAVE, "DIRTY": EFF_DIRTY, "OK": MSG % '"EFF_OK"', "REF": MSG % '"EFF_REFUSED"', "PAR": MSG % '"EFF_PARTIAL"',
       "MSG": MSG % "varEffSave.messagecode"} + EFF_READ
EFF_SETPM = """
Set(varSaving, true);
Set(varEffPmRes, %(F)s.Run(Text(varEffPid), Text(ddEffPm.Selected.id), varEff.pmetag));
Set(varSaving, false);
Notify(Switch(varEffPmRes.resultcode, "OK", %(OK)s, "NO_CHANGE", %(SAME)s, %(MSG)s) & " (" & varEffPmRes.correlationid & ")",
    If(varEffPmRes.ok = "true", NotificationType.Success, NotificationType.Error));
""" % {"F": FLOW_EFF_PM, "OK": MSG % '"EFF_PM_OK"', "SAME": MSG % '"EFF_PM_SAME"', "MSG": MSG % "varEffPmRes.messagecode"} + EFF_LIST.strip() + ";\n" + EFF_READ
EFF_OPEN = "Set(varEffPid, ddEffProject.Selected.id); Clear(colEffEdit);\n" + EFF_READ.strip()
EFF_ONVISIBLE = """
Set(varEffLeave, false); Set(varEffSwitch, false);
""" + EFF_LIST.strip() + """;
If(!IsBlank(varEffPid), """ + EFF_READ.strip() + """)
"""
EFF_NUM = 'If(IsBlank(%s), "", Text(Value(%s), "#,##0.00"))'


# R3 M3 EPIC 17 Discipline Effort ("Công bộ môn"). One project at a time (Projects reference source, as Hour Registration).
# EFF-ReadDisciplineEffort returns what the caller may see (OD-46: own rows; Team Leader: own discipline; PMO / Executive:
# company; the designated EPIC 16 PM: own projects), the aggregate per-discipline ceiling / used / remaining / Approved actual,
# the active WorkTypes, and canEdit / canApprove. The caller edits only own Draft rows (colDeMine, one per active WorkType plus
# own rows of inactive WorkTypes, read-only); edits are held in colDeEdit {k = WorkType id, t}. Approval (Team Leader, own
# discipline, own rows included — OD-28) locks the selected Draft rows; there is no reopen (OD-18).
DE_READ = """
Set(varBusy, true);
Set(varDe, %(F)s.Run(Text(varDePid)));
Set(varBusy, false);
If(varDe.ok = "true",
    Set(varDeScope, varDe.scope);
    Set(varDeCanEdit, Boolean(ParseJSON(varDe.caller).canEdit)); Set(varDeCanApprove, Boolean(ParseJSON(varDe.caller).canApprove));
    Set(varDeMyDisc, Text(ParseJSON(varDe.caller).disciplineCode));
    ClearCollect(colDeRows, ForAll(Table(ParseJSON(varDe.rows)), {id: Value(ThisRecord.Value.id), emp: Text(ThisRecord.Value.employeeName),
        disc: Text(ThisRecord.Value.disciplineCode), wt: Value(ThisRecord.Value.workTypeId), wtLabel: Text(ThisRecord.Value.workTypeCode) & " – " & Text(ThisRecord.Value.workTypeName),
        state: Text(ThisRecord.Value.state), value: Text(ThisRecord.Value.value), status: Text(ThisRecord.Value.status), etag: Text(ThisRecord.Value.etag),
        mine: Boolean(ThisRecord.Value.mine)}));
    ClearCollect(colDeWts, ForAll(Table(ParseJSON(varDe.worktypes)), {id: Value(ThisRecord.Value.id), label: Text(ThisRecord.Value.code) & " – " & Text(ThisRecord.Value.name)}));
    ClearCollect(colDeMine, ForAll(colDeWts As w, {wt: w.id, label: w.label, active: true, value: Coalesce(LookUp(colDeRows, mine && wt = w.id).value, ""),
        status: Coalesce(LookUp(colDeRows, mine && wt = w.id).status, "Draft"), etag: Coalesce(LookUp(colDeRows, mine && wt = w.id).etag, "")}));
    Collect(colDeMine, ForAll(Filter(colDeRows, mine && !(wt in colDeWts.id)) As r, {wt: r.wt, label: r.wtLabel, active: false, value: r.value,
        status: r.status, etag: r.etag}));
    ClearCollect(colDeSum, ForAll(Table(ParseJSON(varDe.summary)), {code: Text(ThisRecord.Value.disciplineCode), name: Text(ThisRecord.Value.disciplineName),
        cstate: Text(ThisRecord.Value.ceilingState), ceiling: Text(ThisRecord.Value.ceiling), used: Text(ThisRecord.Value.used),
        remaining: Text(ThisRecord.Value.remaining), hours: Text(ThisRecord.Value.actualHours), mds: Text(ThisRecord.Value.actualManDays)}));
    ClearCollect(colDeSelTmp, Filter(colDeSel, id in Filter(colDeRows, status = "Draft").id)); ClearCollect(colDeSel, colDeSelTmp),
    Set(varDeCanEdit, false); Set(varDeCanApprove, false); Set(varDeScope, "none"); Clear(colDeRows); Clear(colDeWts); Clear(colDeMine); Clear(colDeSum);
    Clear(colDeSel);
    If(varDe.resultcode = "ROLE_NOT_ALLOWED", Set(varNoDe, true));
    Notify(If(varDe.resultcode = "ROLE_NOT_ALLOWED", %(NA)s, %(MSG)s) & " (" & varDe.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_DE_READ, "NA": MSG % '"DE_NO_ACCESS"', "MSG": MSG % "varDe.messagecode"}
DE_DIRTY = 'Filter(colDeEdit As e, e.t <> Coalesce(LookUp(colDeMine, wt = e.k).value, ""))'
DE_INVALID = 'Filter(colDeEdit As e, !IsBlank(Trim(e.t)) && !IsMatch(Trim(e.t), "[0-9]+([.,][0-9]{1,2})?"))'
DE_SAVE = """
Set(varSaving, true);
Set(varDeSave, %(F)s.Run(Text(varDePid), JSON(ForAll(%(DIRTY)s As c, {workTypeId: c.k,
    state: If(IsBlank(Trim(c.t)), "blank", "value"), value: Substitute(Trim(c.t), ",", "."),
    etag: Coalesce(LookUp(colDeMine, wt = c.k).etag, "")}), JSONFormat.Compact), GUID()));
Set(varSaving, false);
ClearCollect(colDeRes, ForAll(Table(ParseJSON(varDeSave.results)), {k: Value(ThisRecord.Value.workTypeId), rc: Text(ThisRecord.Value.resultcode)}));
// committed / unchanged cells leave the edit set; refused ones stay dirty against the reloaded values; nothing was written for them
ClearCollect(colDeEditTmp, Filter(colDeEdit As e, !(e.k in Filter(colDeRes, rc = "OK" || rc = "NO_CHANGE").k)));
ClearCollect(colDeEdit, colDeEditTmp);
Notify(Switch(varDeSave.resultcode, "OK", %(OK)s, "REFUSED", %(REF)s, %(MSG)s) & " (" & varDeSave.correlationid & ")",
    If(varDeSave.resultcode = "OK", NotificationType.Success, NotificationType.Error));
""" % {"F": FLOW_DE_SAVE, "DIRTY": DE_DIRTY, "OK": MSG % '"DE_OK"', "REF": MSG % '"DE_REFUSED"', "MSG": MSG % "varDeSave.messagecode"} + DE_READ
DE_APPROVE = """
Set(varDeConfirm, false);
Set(varSaving, true);
Set(varDeAppr, %(F)s.Run(JSON(ForAll(colDeSel As x, {itemId: x.id, etag: x.etag}), JSONFormat.Compact), GUID()));
Set(varSaving, false);
ClearCollect(colDeApprRes, ForAll(Table(ParseJSON(varDeAppr.results)), {id: Value(ThisRecord.Value.itemId), rc: Text(ThisRecord.Value.resultcode)}));
Clear(colDeSel);
Notify(Switch(varDeAppr.resultcode, "OK", %(OK)s, "PARTIAL", %(PAR)s, "REFUSED", %(REF)s, %(MSG)s) & " (" & varDeAppr.correlationid & ")",
    Switch(varDeAppr.resultcode, "OK", NotificationType.Success, "PARTIAL", NotificationType.Warning, NotificationType.Error));
""" % {"F": FLOW_DE_APPROVE, "OK": MSG % '"DE_APPROVED"', "PAR": MSG % '"DE_APPROVE_PARTIAL"', "REF": MSG % '"DE_APPROVE_REFUSED"',
       "MSG": MSG % "varDeAppr.messagecode"} + DE_READ
DE_OPEN = "Set(varDePid, ddDeProject.Selected.ID); Clear(colDeEdit); Clear(colDeSel); Clear(colDeRes); Clear(colDeApprRes);\n" + DE_READ.strip()
DE_ONVISIBLE = """
Set(varDeLeave, false); Set(varDeSwitch, false); Set(varDeConfirm, false); Clear(colDeRes); Clear(colDeApprRes);
If(!IsBlank(varDePid), """ + DE_READ.strip() + """)
"""
DE_NUM = 'If(IsBlank(%s), "", Text(Value(%s), "#,##0.00"))'
DE_SELECTABLE = 'varDeCanApprove && ThisItem.status = "Draft" && ThisItem.state = "VALUE" && ThisItem.disc = varDeMyDisc'


# R3 M4 current-scope reports ("Báo cáo công"). Aggregates come from the guarded report flows (OD-50); the screen computes no total.
# Project report: plan = EPIC 16 Project Effort (OD-52), actual = Approved timesheet hours ÷ HoursPerManDay, variance = plan − actual,
# M1 "Đăng ký công" as a separate column only when the server says showregistered. Discipline report: plan = ApprovedLocked only
# (OD-51). Plan with no actual is a row with actual 0 (OD-13). No money (OD-20).
RPT_PROJECT = """
Set(varBusy, true);
Set(varRptP, %(F)s.Run(GUID()));
Set(varBusy, false);
If(varRptP.ok = "true",
    Set(varNoRptP, false);
    ClearCollect(colRptP, ForAll(Table(ParseJSON(varRptP.rows)), {id: Value(ThisRecord.Value.projectId), code: Text(ThisRecord.Value.code),
        name: Text(ThisRecord.Value.name), planState: Text(ThisRecord.Value.planState), planned: Text(ThisRecord.Value.planned),
        hours: Text(ThisRecord.Value.actualHours), actual: Text(ThisRecord.Value.actualManDays), variance: Text(ThisRecord.Value.variance),
        registered: Text(ThisRecord.Value.registered)}));
    Set(varRptPT, {planned: Text(ParseJSON(varRptP.totals).planned), hours: Text(ParseJSON(varRptP.totals).actualHours),
        actual: Text(ParseJSON(varRptP.totals).actualManDays), variance: Text(ParseJSON(varRptP.totals).variance),
        registered: Text(ParseJSON(varRptP.totals).registered)}),
    Clear(colRptP); Set(varRptPT, Blank());
    If(varRptP.resultcode = "ROLE_NOT_ALLOWED", Set(varNoRptP, true));
    Notify(If(varRptP.resultcode = "ROLE_NOT_ALLOWED", %(NA)s, %(MSG)s) & " (" & varRptP.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_RPT_PROJECT, "NA": MSG % '"RPT_NO_ACCESS"', "MSG": MSG % "varRptP.messagecode"}
RPT_DISCIPLINE = """
Set(varBusy, true);
Set(varRptD, %(F)s.Run(GUID()));
Set(varBusy, false);
If(varRptD.ok = "true",
    Set(varNoRptD, false);
    ClearCollect(colRptD, ForAll(Table(ParseJSON(varRptD.rows)), {id: Value(ThisRecord.Value.projectId), code: Text(ThisRecord.Value.code),
        disc: Text(ThisRecord.Value.disciplineCode), discName: Text(ThisRecord.Value.disciplineName), planState: Text(ThisRecord.Value.planState),
        planned: Text(ThisRecord.Value.planned), hours: Text(ThisRecord.Value.actualHours), actual: Text(ThisRecord.Value.actualManDays),
        variance: Text(ThisRecord.Value.variance)})),
    Clear(colRptD);
    If(varRptD.resultcode = "ROLE_NOT_ALLOWED", Set(varNoRptD, true));
    Notify(If(varRptD.resultcode = "ROLE_NOT_ALLOWED", %(NA)s, %(MSG)s) & " (" & varRptD.correlationid & ")", NotificationType.Error))
""" % {"F": FLOW_RPT_DISCIPLINE, "NA": MSG % '"RPT_NO_ACCESS"', "MSG": MSG % "varRptD.messagecode"}
RPT_LOAD = 'If(varRptTab = "project", ' + RPT_PROJECT.strip() + ', ' + RPT_DISCIPLINE.strip() + ')'
RPT_ONVISIBLE = RPT_LOAD
RPT_NUM = 'If(IsBlank(%s), "—", Text(Value(%s), "#,##0.00"))'


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
            {"btnEff": ctl("Classic/Button@2.2.0", Text='"Công dự án"', X="1020", Y="80", Width="200", Height="40", Visible="!varNoEff",
                           OnSelect="Navigate(scrProjectEffort, ScreenTransition.None)")},
            {"btnRpt": ctl("Classic/Button@2.2.0", Text='"Báo cáo"', X="1240", Y="80", Width="120", Height="40", Visible="!(varNoRptP && varNoRptD)",
                           OnSelect="Navigate(scrEffortReport, ScreenTransition.None)")},
            {"btnDe": ctl("Classic/Button@2.2.0", Text='"Công bộ môn"', X="800", Y="80", Width="200", Height="40", Visible="!varNoDe",
                          OnSelect="Navigate(scrDisciplineEffort, ScreenTransition.None)")},
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
            {"ddRegProject": ctl("Classic/DropDown@2.3.1", X="320", Y="100", Width="260",
                                 Items='SortByColumns(If(ddRegYear.Selected.y = "All", Projects, Filter(Projects, ProjectYear = Value(ddRegYear.Selected.y))), "ProjectCode", SortOrder.Ascending)',
                                 Default='If(IsBlank(varRegPid), "", LookUp(Projects, ID = varRegPid).ProjectCode)', AllowEmptySelection="true",
                                 OnChange="If(CountRows(%s) > 0, Set(varRegSwitch, true), %s)" % (REG_DIRTY, "Set(varRegPid, ddRegProject.Selected.ID); Clear(colRegEdit);\n" + REG_READ.strip()),
                                 **{"Items.Value": "ProjectCode"})},
            {"lblRegProject": ctl("Label@2.5.1", Text="ddRegProject.Selected.Title", X="600", Y="100", Width="330", Height="40")},
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
                        "Items": _f('AddColumns(colRegDiscs, phid, ThisItem.id)'), "X": "=280", "Y": "=0", "Width": "=Parent.TemplateWidth - 290",
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
        "scrProjectEffort": {"Properties": {"OnVisible": _f(EFF_ONVISIBLE)}, "Children": [
            {"lblEffTitle": hdr("Công dự án")},
            {"lblEffBusy": ctl("Label@2.5.1", Text='If(varBusy || varSaving, "Working…", "")', X="20", Y="60", Width="400", Height="30")},
            {"btnEffBack": ctl("Classic/Button@2.2.0", Text='"Back"', X="20", Y="100", Width="120",
                               OnSelect="If(CountRows(%s) > 0, Set(varEffLeave, true), Navigate(scrMyTimesheets, ScreenTransition.None))" % EFF_DIRTY)},
            {"ddEffProject": ctl("Classic/DropDown@2.3.1", X="160", Y="100", Width="260", Items='SortByColumns(colEffProjects, "code", SortOrder.Ascending)',
                                 Default='If(IsBlank(varEffPid), "", LookUp(colEffProjects, id = varEffPid).code)', AllowEmptySelection="true",
                                 OnChange="If(CountRows(%s) > 0, Set(varEffSwitch, true), %s)" % (EFF_DIRTY, EFF_OPEN),
                                 **{"Items.Value": "code"})},
            {"lblEffProject": ctl("Label@2.5.1", Text='If(IsBlank(varEffPid), "", ddEffProject.Selected.name)', X="440", Y="100", Width="420", Height="40")},
            {"btnEffReload": ctl("Classic/Button@2.2.0", Text='"Tải lại"', X="880", Y="100", Width="120",
                                 DisplayMode="If(IsBlank(varEffPid) || varBusy || varSaving, DisplayMode.Disabled, DisplayMode.Edit)",
                                 OnSelect="If(CountRows(%s) > 0, Set(varEffSwitch, true), %s)" % (EFF_DIRTY, EFF_READ.strip()))},
            {"btnEffSave": ctl("Classic/Button@2.2.0", Text='If(varSaving, "Saving…", "Lưu (" & CountRows(%s) & ")")' % EFF_DIRTY,
                               X="1020", Y="100", Width="160", Visible="varEffCanEdit",
                               DisplayMode="If(varSaving || varBusy || IsBlank(varEffPid) || CountRows(%s) = 0 || CountRows(%s) > 0, DisplayMode.Disabled, DisplayMode.Edit)"
                                           % (EFF_DIRTY, EFF_INVALID),
                               OnSelect=EFF_SAVE)},
            {"lblEffPm": ctl("Label@2.5.1", X="20", Y="150", Width="620", Height="30",
                             Text='If(IsBlank(varEffPid), "", "PM: " & If(IsBlank(varEffPmName), "(chưa có)", varEffPmName & " (" & varEffPmCode & ")"))')},
            {"ddEffPm": ctl("Classic/DropDown@2.3.1", X="660", Y="145", Width="300", Items='SortByColumns(colEffEmps, "name", SortOrder.Ascending)',
                            Visible="varEffCanAssign && !IsBlank(varEffPid)", AllowEmptySelection="true", Default='""', **{"Items.Value": "name"})},
            {"btnEffSetPm": ctl("Classic/Button@2.2.0", Text='"Gán PM"', X="980", Y="145", Width="120", Height="40",
                                Visible="varEffCanAssign && !IsBlank(varEffPid)",
                                DisplayMode="If(varSaving || varBusy || IsBlank(ddEffPm.Selected) || CountRows(%s) > 0, DisplayMode.Disabled, DisplayMode.Edit)" % EFF_DIRTY,
                                OnSelect=EFF_SETPM)},
            {"lblEffInfo": ctl("Label@2.5.1", X="20", Y="190", Width="1200", Height="30",
                               Text='If(IsBlank(varEffPid), "", If(varEffCanEdit, "", If(IsBlank(varEffPmName), %s, "Chỉ xem")) & "  ·  Đơn vị: công (ngày công)" & If(CountRows(%s) > 0, "  ·  " & %s, ""))'
                                    % (MSG % '"EFF_NO_PM"', EFF_INVALID, MSG % '"EFF_INVALID"'))},
            {"lblEffLeave": ctl("Label@2.5.1", Text=MSG % '"EFF_LEAVE"', X="20", Y="225", Width="560", Height="30", FontWeight="FontWeight.Bold",
                                Visible="varEffLeave || varEffSwitch")},
            {"btnEffLeaveYes": ctl("Classic/Button@2.2.0", Text='"Yes"', X="600", Y="225", Width="90", Height="40", Visible="varEffLeave || varEffSwitch",
                                   OnSelect="Clear(colEffEdit); If(varEffLeave, Set(varEffLeave, false); Navigate(scrMyTimesheets, ScreenTransition.None), "
                                            "Set(varEffSwitch, false); Set(varEffPid, ddEffProject.Selected.id);\n" + EFF_READ.strip() + ")")},
            {"btnEffLeaveNo": ctl("Classic/Button@2.2.0", Text='"No"', X="700", Y="225", Width="90", Height="40", Visible="varEffLeave || varEffSwitch",
                                  OnSelect="Set(varEffLeave, false); Set(varEffSwitch, false); Reset(ddEffProject)")},
            {"galEffRows": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("colEffRecs"), "X": "=20", "Y": "=275", "Width": "=640", "Height": "=Parent.Height - 295", "TemplateSize": "=50",
                "Visible": _f("!IsBlank(varEffPid)")},
                "Children": [
                    {"lblEffRec": ctl("Label@2.5.1", X="0", Y="5", Width="300", Height="40", Text="ThisItem.label")},
                    {"txtEffVal": ctl("Classic/TextInput@2.3.2", X="320", Y="5", Width="140", Height="40", Align="Align.Right", HintText='"—"',
                                      Default='If(IsBlank(LookUp(colEffEdit, k = ThisItem.key)), ThisItem.value, LookUp(colEffEdit, k = ThisItem.key).t)',
                                      DisplayMode="If(varEffCanEdit && !varSaving, DisplayMode.Edit, DisplayMode.View)",
                                      Fill='If(Self.Text <> ThisItem.value, RGBA(255, 244, 206, 1), RGBA(255, 255, 255, 1))',
                                      BorderColor='If(!IsBlank(Trim(Self.Text)) && !IsMatch(Trim(Self.Text), "[0-9]+([.,][0-9]{1,2})?"), RGBA(196, 49, 75, 1), RGBA(166, 166, 166, 1))',
                                      AccessibleLabel="ThisItem.label",
                                      OnChange="ClearCollect(colEffEditTmp, Filter(colEffEdit, k <> ThisItem.key)); Collect(colEffEditTmp, {k: ThisItem.key, t: Self.Text}); ClearCollect(colEffEdit, colEffEditTmp)")},
                    {"lblEffState": ctl("Label@2.5.1", X="470", Y="5", Width="150", Height="40",
                                        Text='If(ThisItem.state = "BLANK", "chưa đăng ký", "công")')}]}},
            {"lblEffPlanned": ctl("Label@2.5.1", X="700", Y="275", Width="600", Height="40",
                                  Visible="!IsBlank(varEffPid)", Text='"Công đăng ký (kế hoạch): " & %s & " công"' % (EFF_NUM % ("varEff.plannedtotal", "varEff.plannedtotal")))},
            {"lblEffActual": ctl("Label@2.5.1", X="700", Y="320", Width="600", Height="40",
                                 Visible="!IsBlank(varEffPid)",
                                 Text='"Công thực hiện (chấm công đã duyệt): " & %s & " công (" & %s & " giờ; " & varEff.hourspermanday & " giờ = 1 công)"'
                                      % (EFF_NUM % ("varEff.actualmandays", "varEff.actualmandays"), EFF_NUM % ("varEff.actualhours", "varEff.actualhours")))},
            {"lblEffVar": ctl("Label@2.5.1", X="700", Y="365", Width="600", Height="40", FontWeight="FontWeight.Bold",
                              Visible="!IsBlank(varEffPid)", Text='"Chênh lệch (thực hiện − kế hoạch): " & %s & " công"' % (EFF_NUM % ("varEff.variance", "varEff.variance")))}]},
        "scrDisciplineEffort": {"Properties": {"OnVisible": _f(DE_ONVISIBLE)}, "Children": [
            {"lblDeTitle": hdr("Công bộ môn")},
            {"lblDeBusy": ctl("Label@2.5.1", Text='If(varBusy || varSaving, "Working…", "")', X="20", Y="60", Width="400", Height="30")},
            {"btnDeBack": ctl("Classic/Button@2.2.0", Text='"Back"', X="20", Y="100", Width="120",
                              OnSelect="If(CountRows(%s) > 0, Set(varDeLeave, true), Navigate(scrMyTimesheets, ScreenTransition.None))" % DE_DIRTY)},
            {"ddDeProject": ctl("Classic/DropDown@2.3.1", X="160", Y="100", Width="260", Items='SortByColumns(Projects, "ProjectCode", SortOrder.Ascending)',
                                Default='If(IsBlank(varDePid), "", LookUp(Projects, ID = varDePid).ProjectCode)', AllowEmptySelection="true",
                                OnChange="If(CountRows(%s) > 0, Set(varDeSwitch, true), %s)" % (DE_DIRTY, DE_OPEN),
                                **{"Items.Value": "ProjectCode"})},
            {"lblDeProject": ctl("Label@2.5.1", Text='If(IsBlank(varDePid), "", ddDeProject.Selected.Title)', X="440", Y="100", Width="420", Height="40")},
            {"btnDeReload": ctl("Classic/Button@2.2.0", Text='"Tải lại"', X="880", Y="100", Width="120",
                                DisplayMode="If(IsBlank(varDePid) || varBusy || varSaving, DisplayMode.Disabled, DisplayMode.Edit)",
                                OnSelect="If(CountRows(%s) > 0, Set(varDeSwitch, true), %s)" % (DE_DIRTY, DE_READ.strip()))},
            {"btnDeSave": ctl("Classic/Button@2.2.0", Text='If(varSaving, "Saving…", "Lưu (" & CountRows(%s) & ")")' % DE_DIRTY,
                              X="1020", Y="100", Width="160", Visible="varDeCanEdit",
                              DisplayMode="If(varSaving || varBusy || IsBlank(varDePid) || CountRows(%s) = 0 || CountRows(%s) > 0, DisplayMode.Disabled, DisplayMode.Edit)"
                                          % (DE_DIRTY, DE_INVALID),
                              OnSelect=DE_SAVE)},
            {"lblDeInfo": ctl("Label@2.5.1", X="20", Y="150", Width="1200", Height="30",
                              Text='If(IsBlank(varDePid), "", "Bộ môn của bạn: " & varDeMyDisc & If(varDeCanEdit, "", "  ·  Chỉ xem") & "  ·  Đơn vị: công (ngày công)" & If(CountRows(%s) > 0, "  ·  " & %s, ""))'
                                   % (DE_INVALID, MSG % '"DE_INVALID"'))},
            {"lblDeLeave": ctl("Label@2.5.1", Text=MSG % '"DE_LEAVE"', X="20", Y="190", Width="560", Height="30", FontWeight="FontWeight.Bold",
                               Visible="varDeLeave || varDeSwitch")},
            {"btnDeLeaveYes": ctl("Classic/Button@2.2.0", Text='"Yes"', X="600", Y="190", Width="90", Height="40", Visible="varDeLeave || varDeSwitch",
                                  OnSelect="Clear(colDeEdit); If(varDeLeave, Set(varDeLeave, false); Navigate(scrMyTimesheets, ScreenTransition.None), "
                                           "Set(varDeSwitch, false); " + DE_OPEN + ")")},
            {"btnDeLeaveNo": ctl("Classic/Button@2.2.0", Text='"No"', X="700", Y="190", Width="90", Height="40", Visible="varDeLeave || varDeSwitch",
                                 OnSelect="Set(varDeLeave, false); Set(varDeSwitch, false); Reset(ddDeProject)")},
            {"lblDeMine": ctl("Label@2.5.1", Text='"Công đăng ký của tôi"', X="20", Y="235", Width="560", Height="30", FontWeight="FontWeight.Bold",
                              Visible="!IsBlank(varDePid)")},
            {"galDeMine": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("colDeMine"), "X": "=20", "Y": "=270", "Width": "=640", "Height": "=Parent.Height - 290", "TemplateSize": "=50",
                "Visible": _f("!IsBlank(varDePid)")},
                "Children": [
                    {"icoDeLock": ctl("Classic/Icon@2.5.0", Icon="Icon.Lock", X="0", Y="13", Width="24", Height="24", Visible='ThisItem.status = "ApprovedLocked"',
                                      Tooltip='"Đã phê duyệt"', AccessibleLabel='"Đã phê duyệt"')},
                    {"lblDeWt": ctl("Label@2.5.1", X="30", Y="5", Width="270", Height="40", Text="ThisItem.label")},
                    {"txtDeVal": ctl("Classic/TextInput@2.3.2", X="310", Y="5", Width="130", Height="40", Align="Align.Right", HintText='"—"',
                                     Default='If(IsBlank(LookUp(colDeEdit, k = ThisItem.wt)), ThisItem.value, LookUp(colDeEdit, k = ThisItem.wt).t)',
                                     DisplayMode='If(varDeCanEdit && !varSaving && ThisItem.active && ThisItem.status <> "ApprovedLocked", DisplayMode.Edit, DisplayMode.View)',
                                     Fill='If(Self.Text <> ThisItem.value, RGBA(255, 244, 206, 1), RGBA(255, 255, 255, 1))',
                                     BorderColor='If(!IsBlank(Trim(Self.Text)) && !IsMatch(Trim(Self.Text), "[0-9]+([.,][0-9]{1,2})?"), RGBA(196, 49, 75, 1), RGBA(166, 166, 166, 1))',
                                     AccessibleLabel="ThisItem.label",
                                     OnChange="ClearCollect(colDeEditTmp, Filter(colDeEdit, k <> ThisItem.wt)); Collect(colDeEditTmp, {k: ThisItem.wt, t: Self.Text}); ClearCollect(colDeEdit, colDeEditTmp)")},
                    {"lblDeRc": ctl("Label@2.5.1", X="450", Y="5", Width="190", Height="40", Size="10",
                                    Text='With({rc: LookUp(colDeRes, k = ThisItem.wt).rc}, If(IsBlank(rc) || rc = "OK" || rc = "NO_CHANGE", If(ThisItem.status = "ApprovedLocked", "đã duyệt", ""), %s))'
                                         % (MSG % '"MSG_" & rc'))}]}},
            {"lblDeSumTitle": ctl("Label@2.5.1", Text='"Tổng theo bộ môn"', X="700", Y="235", Width="560", Height="30", FontWeight="FontWeight.Bold",
                                  Visible="!IsBlank(varDePid)")},
            {"galDeSum": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("colDeSum"), "X": "=700", "Y": "=270", "Width": "=Parent.Width - 720", "Height": "=150", "TemplateSize": "=70",
                "Visible": _f("!IsBlank(varDePid)")},
                "Children": [
                    {"lblDeSumName": ctl("Label@2.5.1", X="0", Y="0", Width="Parent.TemplateWidth", Height="30", FontWeight="FontWeight.Bold",
                                         Text='ThisItem.name & " (" & ThisItem.code & ")"')},
                    {"lblDeSumVals": ctl("Label@2.5.1", X="0", Y="30", Width="Parent.TemplateWidth", Height="35",
                                         Text='If(ThisItem.cstate = "BLANK", "Trần: chưa có", "Trần: " & %s & " · Còn lại: " & %s) & " · Đã đăng ký: " & %s & " · Thực hiện (đã duyệt): " & %s & " công (" & %s & " giờ)"'
                                              % (DE_NUM % ("ThisItem.ceiling", "ThisItem.ceiling"), DE_NUM % ("ThisItem.remaining", "ThisItem.remaining"),
                                                 DE_NUM % ("ThisItem.used", "ThisItem.used"), DE_NUM % ("ThisItem.mds", "ThisItem.mds"),
                                                 DE_NUM % ("ThisItem.hours", "ThisItem.hours")))}]}},
            {"lblDeTeam": ctl("Label@2.5.1", Text='"Công đăng ký đã xem được"', X="700", Y="430", Width="400", Height="30", FontWeight="FontWeight.Bold",
                              Visible='!IsBlank(varDePid) && varDeScope <> "self"')},
            {"btnDeApprove": ctl("Classic/Button@2.2.0", Text='"Phê duyệt (" & CountRows(colDeSel) & ")"', X="1120", Y="425", Width="160", Height="40",
                                 Visible="varDeCanApprove && !IsBlank(varDePid)",
                                 DisplayMode="If(varSaving || varBusy || CountRows(colDeSel) = 0 || CountRows(colDeSel) > 50 || CountRows(%s) > 0, DisplayMode.Disabled, DisplayMode.Edit)" % DE_DIRTY,
                                 OnSelect="Set(varDeConfirm, true)")},
            {"lblDeConfirm": ctl("Label@2.5.1", Text=MSG % '"DE_APPROVE_CONFIRM"', X="700", Y="470", Width="440", Height="40", FontWeight="FontWeight.Bold",
                                 Visible="varDeConfirm")},
            {"btnDeConfirmYes": ctl("Classic/Button@2.2.0", Text='"Yes"', X="1150", Y="470", Width="80", Height="40", Visible="varDeConfirm",
                                    DisplayMode="If(varSaving, DisplayMode.Disabled, DisplayMode.Edit)", OnSelect=DE_APPROVE)},
            {"btnDeConfirmNo": ctl("Classic/Button@2.2.0", Text='"No"', X="1240", Y="470", Width="80", Height="40", Visible="varDeConfirm",
                                   OnSelect="Set(varDeConfirm, false)")},
            {"galDeTeam": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f('SortByColumns(colDeRows, "disc", SortOrder.Ascending, "emp", SortOrder.Ascending, "wt", SortOrder.Ascending)'),
                "X": "=700", "Y": "=515", "Width": "=Parent.Width - 720", "Height": "=Parent.Height - 535", "TemplateSize": "=45",
                "Visible": _f('!IsBlank(varDePid) && varDeScope <> "self"')},
                "Children": [
                    {"btnDeSel": ctl("Classic/Button@2.2.0", Text='If(ThisItem.id in colDeSel.id, "[x]", "[ ]")', X="0", Y="5", Width="40", Height="35",
                                     Visible=DE_SELECTABLE,
                                     OnSelect="If(ThisItem.id in colDeSel.id, ClearCollect(colDeSelTmp, Filter(colDeSel, id <> ThisItem.id)); ClearCollect(colDeSel, colDeSelTmp), "
                                              "Collect(colDeSel, {id: ThisItem.id, etag: ThisItem.etag}))")},
                    {"icoDeTeamLock": ctl("Classic/Icon@2.5.0", Icon="Icon.Lock", X="8", Y="10", Width="24", Height="24", Visible='ThisItem.status = "ApprovedLocked"',
                                          Tooltip='"Đã phê duyệt"', AccessibleLabel='"Đã phê duyệt"')},
                    {"lblDeTeamRow": ctl("Label@2.5.1", X="45", Y="5", Width="Parent.TemplateWidth - 245", Height="35",
                                         Text='ThisItem.disc & " · " & ThisItem.emp & " · " & ThisItem.wtLabel')},
                    {"lblDeTeamVal": ctl("Label@2.5.1", X="Parent.TemplateWidth - 195", Y="5", Width="80", Height="35", Align="Align.Right",
                                         Text='If(ThisItem.state = "BLANK", "—", %s)' % (DE_NUM % ("ThisItem.value", "ThisItem.value")))},
                    {"lblDeTeamRc": ctl("Label@2.5.1", X="Parent.TemplateWidth - 110", Y="5", Width="110", Height="35", Size="10",
                                        Text='With({rc: LookUp(colDeApprRes, id = ThisItem.id).rc}, If(IsBlank(rc) || rc = "OK", If(ThisItem.status = "ApprovedLocked", "đã duyệt", "nháp"), %s))'
                                             % (MSG % '"MSG_" & rc'))}]}}]},
        "scrEffortReport": {"Properties": {"OnVisible": _f(RPT_ONVISIBLE)}, "Children": [
            {"lblRptTitle": hdr("Báo cáo công")},
            {"lblRptBusy": ctl("Label@2.5.1", Text='If(varBusy, "Working…", "")', X="20", Y="60", Width="400", Height="30")},
            {"btnRptBack": ctl("Classic/Button@2.2.0", Text='"Back"', X="20", Y="100", Width="120", OnSelect="Navigate(scrMyTimesheets, ScreenTransition.None)")},
            {"btnRptProject": ctl("Classic/Button@2.2.0", Text='"Theo dự án"', X="160", Y="100", Width="160",
                                  DisplayMode="If(varBusy, DisplayMode.Disabled, DisplayMode.Edit)",
                                  OnSelect='Set(varRptTab, "project");\n' + RPT_PROJECT.strip())},
            {"btnRptDiscipline": ctl("Classic/Button@2.2.0", Text='"Theo bộ môn"', X="340", Y="100", Width="160",
                                     DisplayMode="If(varBusy, DisplayMode.Disabled, DisplayMode.Edit)",
                                     OnSelect='Set(varRptTab, "discipline");\n' + RPT_DISCIPLINE.strip())},
            {"btnRptReload": ctl("Classic/Button@2.2.0", Text='"Tải lại"', X="520", Y="100", Width="120",
                                 DisplayMode="If(varBusy, DisplayMode.Disabled, DisplayMode.Edit)", OnSelect=RPT_LOAD)},
            {"lblRptInfo": ctl("Label@2.5.1", X="20", Y="150", Width="1300", Height="30", Size="11",
                               Text='"Đơn vị: công (" & If(varRptTab = "project", varRptP.hourspermanday, varRptD.hourspermanday) & " giờ = 1 công) · Thực hiện = giờ chấm công đã duyệt · Chênh lệch = kế hoạch − thực hiện" & If(varRptTab = "discipline", " · Kế hoạch bộ môn = dòng đã phê duyệt", " · Kế hoạch = Công dự án")')},
            {"lblRptEmpty": ctl("Label@2.5.1", X="20", Y="230", Width="800", Height="40", Text=MSG % '"RPT_EMPTY"',
                                Visible='!varBusy && If(varRptTab = "project", varRptP.ok = "true" && CountRows(colRptP) = 0, varRptD.ok = "true" && CountRows(colRptD) = 0)')},
            {"lblRptPHead": ctl("Label@2.5.1", X="20", Y="190", Width="1300", Height="30", FontWeight="FontWeight.Bold", Visible='varRptTab = "project"',
                                Text='"Dự án · Kế hoạch (công dự án) · Thực hiện (công) · Giờ · Chênh lệch" & If(varRptP.showregistered = "true", " · Đăng ký công (M1, riêng)", "")')},
            {"galRptP": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f('SortByColumns(colRptP, "code", SortOrder.Ascending)'), "X": "=20", "Y": "=225", "Width": "=1300", "Height": "=Parent.Height - 300",
                "TemplateSize": "=40", "Visible": _f('varRptTab = "project"')},
                "Children": [
                    {"lblRptPRow": ctl("Label@2.5.1", X="0", Y="2", Width="Parent.TemplateWidth", Height="36",
                                       Text='ThisItem.code & " — " & ThisItem.name & " · " & If(ThisItem.planState = "BLANK", "chưa đăng ký", %s) & " · " & %s & " · " & %s & " giờ · " & %s & If(varRptP.showregistered = "true", " · M1: " & %s, "")'
                                            % (RPT_NUM % ("ThisItem.planned", "ThisItem.planned"), RPT_NUM % ("ThisItem.actual", "ThisItem.actual"),
                                               RPT_NUM % ("ThisItem.hours", "ThisItem.hours"), RPT_NUM % ("ThisItem.variance", "ThisItem.variance"),
                                               RPT_NUM % ("ThisItem.registered", "ThisItem.registered")))}]}},
            {"lblRptPTotal": ctl("Label@2.5.1", X="20", Y="Parent.Height - 70", Width="1300", Height="40", FontWeight="FontWeight.Bold",
                                 Visible='varRptTab = "project" && !IsBlank(varRptPT)',
                                 Text='"Tổng: kế hoạch " & %s & " · thực hiện " & %s & " công (" & %s & " giờ) · chênh lệch " & %s & If(varRptP.showregistered = "true", " · M1 " & %s, "")'
                                      % (RPT_NUM % ("varRptPT.planned", "varRptPT.planned"), RPT_NUM % ("varRptPT.actual", "varRptPT.actual"),
                                         RPT_NUM % ("varRptPT.hours", "varRptPT.hours"), RPT_NUM % ("varRptPT.variance", "varRptPT.variance"),
                                         RPT_NUM % ("varRptPT.registered", "varRptPT.registered")))},
            {"lblRptDHead": ctl("Label@2.5.1", X="20", Y="190", Width="1300", Height="30", FontWeight="FontWeight.Bold", Visible='varRptTab = "discipline"',
                                Text='"Dự án · Bộ môn · Kế hoạch (đã duyệt) · Thực hiện (công) · Giờ · Chênh lệch"')},
            {"galRptD": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f('SortByColumns(colRptD, "code", SortOrder.Ascending, "disc", SortOrder.Ascending)'), "X": "=20", "Y": "=225", "Width": "=1300",
                "Height": "=Parent.Height - 245", "TemplateSize": "=40", "Visible": _f('varRptTab = "discipline"')},
                "Children": [
                    {"lblRptDRow": ctl("Label@2.5.1", X="0", Y="2", Width="Parent.TemplateWidth", Height="36",
                                       Text='ThisItem.code & " · " & ThisItem.discName & " (" & ThisItem.disc & ") · " & If(ThisItem.planState = "BLANK", "chưa có kế hoạch duyệt", %s) & " · " & %s & " · " & %s & " giờ · " & %s'
                                            % (RPT_NUM % ("ThisItem.planned", "ThisItem.planned"), RPT_NUM % ("ThisItem.actual", "ThisItem.actual"),
                                               RPT_NUM % ("ThisItem.hours", "ThisItem.hours"), RPT_NUM % ("ThisItem.variance", "ThisItem.variance")))}]}}]},
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
