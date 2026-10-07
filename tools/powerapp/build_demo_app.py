"""R1 demo Canvas app source (Power Apps YAML, `*.pa.yaml`) — generic; no tenant, site, list GUID or account.

Screens: scrStartup (TS-AppOpen), scrAccessDenied (identity / config error), scrMyTimesheets (TS-ReadOwn, bounded current
pay period), scrEntry (new / edit own Draft via TS-SaveEntry). Protected lists (TimesheetEntries, AuditLog) are never data
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
REFERENCE_SOURCES = ("Projects", "ProjectPhases", "Phases", "WorkTypes", "Shifts", "HourTypes")
PROTECTED_LISTS = ("TimesheetEntries", "AuditLog", "Employees", "AppSettings")
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
    "MSG_LOCKED": "This entry is approved and can no longer be changed.",
    "MSG_CONFLICT": "This entry was changed elsewhere. Your entries were refreshed; please open it again.",
    "MSG_VALIDATION_LOOKUP": "Please choose an active project, phase, work type, shift and hour type.",
    "MSG_VALIDATION_HOURS": "Hours must be greater than 0 and at most 24.",
    "MSG_VALIDATION_DATE": "Please enter a valid work date.",
    "MSG_ERROR_LEAK": "Your entries could not be shown. Please contact the administrator.",
    "MSG_ERROR": "Something went wrong. Please try again later.",
    "WARN_HOURS_ENTRY": "Note: this entry is longer than the usual maximum per entry.",
    "WARN_HOURS_DAY": "Note: the total for this day is above the usual daily maximum.",
    "WARN_DUPLICATE": "Note: a similar entry already exists for this day.",
    "WARN_RELOAD_REQUIRED": "Saved. Your entries were reloaded before further changes.",
    "AUDIT_DEGRADED": "Saved. A background record could not be written; the administrator has been notified. Do not save again.",
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
Set(varBusy, false); Set(varSaving, false); Set(varReloadRequired, false)
""" % _table(MESSAGES)

STARTUP_ONVISIBLE = """
Set(varBusy, true);
Set(varOpen, %(F)s.Run("canvas-demo"));
Set(varBusy, false);
If(varOpen.ok = "true" && varOpen.configstatus = "OK",
    Set(varCfg, ParseJSON(varOpen.config));
    Set(varStartDay, Value(Text(varCfg.settings.PayPeriodStartDay)));
    Set(varWarnEntry, Value(Text(varCfg.settings.MaxHoursPerEntryWarn)));
    Set(varWarnDay, Value(Text(varCfg.settings.MaxHoursPerDayWarn)));
    Navigate(scrMyTimesheets, ScreenTransition.None),
    Set(varDeniedCode, If(varOpen.ok = "true", "MSG_" & varOpen.configstatus, varOpen.messagecode));
    Set(varDeniedRef, varOpen.correlationid);
    Navigate(scrAccessDenied, ScreenTransition.None))
""" % {"F": FLOW_APPOPEN}

LIST_ONVISIBLE = RANGE + ";\nSet(varAfter, Blank());\n" + READ

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

PHASES_FOR_PROJECT = ("Filter(Phases, IsActive, ID in Filter(ProjectPhases, ProjectItemId = ddProject.Selected.ID, IsActive).Phase.Id)")


def screens() -> dict:
    hdr = lambda t: ctl("Label@2.5.1", Text='"%s"' % t, X="20", Y="10", Width="Parent.Width - 40", Height="50", Size="20",  # noqa: E731
                        FontWeight="FontWeight.Bold")
    busy = ctl("Label@2.5.1", Text='If(varBusy || varSaving, "Working…", "")', X="20", Y="60", Width="400", Height="30")
    lookup = lambda src, idf, field: "LookUp(%s, ID = %s, %s)" % (src, idf, field)  # noqa: E731
    return {
        "scrStartup": {"Properties": {"OnVisible": _f(STARTUP_ONVISIBLE)},
                       "Children": [{"lblTitle": hdr("Timesheet")}, {"lblBusy": busy},
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
            {"galEntries": {"Control": "Gallery@2.15.0", "Variant": "Vertical", "Properties": {
                "Items": _f("SortByColumns(colRows, \"workDate\", SortOrder.Descending, \"id\", SortOrder.Descending)"),
                "X": "=20", "Y": "=180", "Width": "=Parent.Width - 40", "Height": "=Parent.Height - 260", "TemplateSize": "=70"},
                "Children": [
                    {"lblLine1": ctl("Label@2.5.1", X="10", Y="5", Width="Parent.TemplateWidth - 20", Height="30",
                                     Text='Text(ThisItem.workDate, "dd/mm/yyyy") & "  ·  " & %s & " / " & %s & "  ·  " & Text(ThisItem.hours) & " h  ·  " & ThisItem.status'
                                     % (lookup("Projects", "ThisItem.projectId", "ProjectCode"), lookup("Phases", "ThisItem.phaseId", "PhaseCode")))},
                    {"lblLine2": ctl("Label@2.5.1", X="10", Y="35", Width="Parent.TemplateWidth - 20", Height="30",
                                     Text='%s & "  ·  " & ThisItem.remark' % lookup("WorkTypes", "ThisItem.workTypeId", "Title"))},
                    {"btnEdit": ctl("Classic/Button@2.2.0", Text='"Edit"', X="Parent.TemplateWidth - 110", Y="15", Width="90",
                                    Visible='ThisItem.status = "Draft"',
                                    OnSelect="Set(varEdit, ThisItem); Navigate(scrEntry, ScreenTransition.None)")}]}},
            {"btnMore": ctl("Classic/Button@2.2.0", Text='"Load more"', X="20", Y="Parent.Height - 70",
                            Visible="!IsBlank(varNextAfter) && varNextAfter <> \"\"",
                            OnSelect="Set(varAfter, Value(varNextAfter));\n" + READ)}]},
        "scrEntry": {"Children": [
            {"lblTitle": ctl("Label@2.5.1", Text='If(IsBlank(varEdit), "New entry", "Edit draft")', X="20", Y="10", Width="600", Height="50",
                             Size="20", FontWeight="FontWeight.Bold")}, {"lblBusy": busy},
            {"dpWorkDate": ctl("Classic/DatePicker@2.6.0", X="20", Y="100", Width="300",
                               DefaultDate="If(IsBlank(varEdit), Today(), varEdit.workDate)", Format='"dd/mm/yyyy"')},
            {"ddProject": ctl("Classic/DropDown@2.3.1", X="20", Y="150", Width="400", Items='Filter(Projects, Status.Value = "Active")',
                              Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("Projects", "varEdit.projectId", "ProjectCode"), Value='"ProjectCode"')},
            {"ddPhase": ctl("Classic/DropDown@2.3.1", X="20", Y="200", Width="400", Items=PHASES_FOR_PROJECT,
                            Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("Phases", "varEdit.phaseId", "PhaseCode"), Value='"PhaseCode"')},
            {"ddWorkType": ctl("Classic/DropDown@2.3.1", X="20", Y="250", Width="400", Items="Filter(WorkTypes, IsActive)",
                               Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("WorkTypes", "varEdit.workTypeId", "WorkTypeCode"), Value='"WorkTypeCode"')},
            {"ddShift": ctl("Classic/DropDown@2.3.1", X="20", Y="300", Width="400", Items="Filter(Shifts, IsActive)",
                            Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("Shifts", "varEdit.shiftId", "ShiftCode"), Value='"ShiftCode"')},
            {"ddHourType": ctl("Classic/DropDown@2.3.1", X="20", Y="350", Width="400", Items="HourTypes",
                               Default="If(IsBlank(varEdit), Blank(), %s)" % lookup("HourTypes", "varEdit.hourTypeId", "HourTypeCode"), Value='"HourTypeCode"')},
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
