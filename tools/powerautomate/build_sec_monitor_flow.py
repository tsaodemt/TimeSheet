"""SEC-Monitor flow (S07.4 T07.4.2): scheduled detection of out-of-band TimesheetEntries writes. Reference:
tools/security/sec_monitor.py. Offline template; the site, service identity, alert recipient and environment come from
environment configuration at build time (never literals in this file).

Runtime adaptation of the reference (documented in docs/immutability-and-monitor.md):
- Schedule, not the item trigger: the SharePoint item trigger polls, and on Microsoft 365 seeded licences the interval
  leaves no headroom inside the 300 s alert SLA. A Recurrence of `interval_minutes` scans one half-open window
  [scheduledTime - interval, scheduledTime) per run.
- Per version, not per item: every version created inside the window is read from the item's version history and
  classified by SharePoint's own Editor of that version. A version belongs to exactly one window, so it is alerted once
  (the per-version dedupe of the reference) without any stored state, and an out-of-band version later overwritten by a
  service write is still seen.
- Read only: the monitor reads TimesheetEntries and sends mail; it writes no SharePoint item, so it cannot trigger
  itself and leaves no non-service write in the protected lists.
"""
from __future__ import annotations

import build_read_flow as base
import guard_template as gt

c, S, o, nz = base.c, base.S, base.o, gt.nz
OUTLOOK = "shared_office365"
ENTRIES = "TimesheetEntries"
SUBJECT = "[%s][SECURITY] Timesheet out-of-band edit detected"
REASON = "OUT_OF_BAND_EDIT"
FMT = "yyyy-MM-ddTHH:mm:ss"


def trigger(interval_minutes: int) -> dict:
    return {"type": "Recurrence", "recurrence": {"frequency": "Minute", "interval": int(interval_minutes)}}


def _lit(s: str) -> str:
    return "'%s'" % str(s).replace("'", "''")


def monitor_actions(*, site: str, service_upn: str, recipient: str, environment: str, interval_minutes: int = 2) -> dict:
    if not (site and service_upn and recipient and environment):
        raise ValueError("SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED" if not recipient else "MONITOR_CONFIG_INVALID")
    n = int(interval_minutes)
    sched = "trigger()['scheduledTime']"
    a = {}
    a["SiteUrl"] = c(site, {})
    a["Window"] = c({"start": "@{formatDateTime(addMinutes(%s, -%d), '%s')}" % (sched, n, FMT),
                     "end": "@{formatDateTime(%s, '%s')}" % (sched, FMT)}, S("SiteUrl"))
    a["Get_changed"] = base.sp_http("GET", "_api/web/lists/getbytitle('%s')/items?$select=Id&$filter=Modified ge datetime'@{%s?['start']}Z'&$top=5000"
                                    % (ENTRIES, o("Window")), S("Window"))
    start, end = "%s?['start']" % o("Window"), "%s?['end']" % o("Window")
    editor = "toLower(%s)" % nz("item()?['Editor']?['Email']")
    loop = {}
    loop["Get_versions"] = base.sp_http("GET", "_api/web/lists/getbytitle('%s')/items(@{items('Each_item')?['Id']})/versions"
                                        "?$select=VersionLabel,Created,Editor" % ENTRIES, {})
    loop["Out_of_band"] = {"type": "Query", "runAfter": S("Get_versions"),
                           "inputs": {"from": "@body('Get_versions')?['value']",
                                      "where": "@and(greaterOrEquals(item()?['Created'], %s), less(item()?['Created'], %s), not(equals(%s, %s)))"
                                               % (start, end, editor, _lit(service_upn.lower()))}}
    v = "items('Each_alert')"
    body = ("<p>Environment: %s<br>Event: SecurityMonitor<br>Reason: %s<br>Target: %s<br>Item: @{items('Each_item')?['Id']}<br>"
            "Version: @{%s?['VersionLabel']}<br>Modified (UTC): @{%s?['Created']}<br>Modified by: @{%s?['Editor']?['Email']}<br>"
            "Detected (UTC): @{utcNow()}<br>Reference: %s:@{items('Each_item')?['Id']}:@{%s?['VersionLabel']}<br>"
            "Run: @{workflow()['run']['name']}</p>" % (environment, REASON, ENTRIES, v, v, v, ENTRIES, v))
    send = base.op(OUTLOOK, "SendEmailV2", {"emailMessage/To": recipient, "emailMessage/Subject": SUBJECT % environment,
                                             "emailMessage/Body": body, "emailMessage/Importance": "High"}, {})
    loop["Each_alert"] = {"type": "Foreach", "foreach": "@body('Out_of_band')", "runAfter": S("Out_of_band"),
                          "actions": {"Send_alert": send}}
    a["Each_item"] = {"type": "Foreach", "foreach": "@body('Get_changed')?['value']", "runAfter": S("Get_changed"), "actions": loop}
    return a
