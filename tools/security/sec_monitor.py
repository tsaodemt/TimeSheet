"""SEC-Monitor (S07.4 T07.4.2): detection of out-of-band TimesheetEntries writes. Reference implementation
(executable specification; no tenant data, nothing deployed).

Every legitimate write to TimesheetEntries (TS-SaveEntry, TS-Approve, TS-Unapprove, and any approved service-owned
maintenance) runs through the service connection, so SharePoint records the service identity as the item's editor.
The monitor reads that trusted SharePoint metadata (Editor / Modified / version label), never a value a writer could
put into the row itself (ActorUpn, CorrelationId, SourceFlow, or any "trusted write" marker are ignored):

    classify(change, service_upn)               -> Classification (TRUSTED_SERVICE_WRITE | OUT_OF_BAND_EDIT)
    monitor(changes, service_upn=..., settings=..., environment=..., seen=...) -> MonitorRun
        .alerts       one OUT_OF_BAND_EDIT alert per (list, item, version): a re-delivered trigger is not re-alerted
        .code         OK | SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED | MONITOR_CONFIG_INVALID
        .audit        the SecurityMonitor audit rows (operational AuditLog, never TimesheetEntries)

Detection is not prevention: it does not replace list permissions, the guarded flows or the LOCKED rule. The monitor
never writes TimesheetEntries, so it cannot re-trigger itself. The alert destination comes only from configuration
(`OpsAlertRecipient`); without it the monitor detects but reports SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED and sends
nothing (no recipient is ever assumed).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

OK = "OK"
TRUSTED_SERVICE_WRITE, OUT_OF_BAND_EDIT = "TRUSTED_SERVICE_WRITE", "OUT_OF_BAND_EDIT"
ALERT_DESTINATION_UNCONFIGURED = "SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED"
MONITOR_CONFIG_INVALID = "MONITOR_CONFIG_INVALID"
EVENT_TYPE = "SecurityMonitor"
TARGET_LIST = "TimesheetEntries"
DESTINATION_SETTING = "OpsAlertRecipient"
ALERT_SLA_SECONDS = 300
# Trusted SharePoint metadata the monitor reads. Nothing else of the row is read or forwarded.
TRUSTED_FIELDS = ("Id", "Editor", "Author", "Modified", "Created", "OData__UIVersionString")
# Values a direct editor can type into the row: never evidence of a trusted write.
UNTRUSTED_MARKERS = ("ActorUpn", "CorrelationId", "SourceFlow", "TrustedWrite", "IsServiceWrite", "WrittenBy", "OwnerUpn")
ALERT_FIELDS = ("environment", "eventType", "reason", "targetEntity", "targetItemId", "versionLabel", "modifiedUtc",
                "editorUpn", "detectedUtc", "reference")


def principal_upn(person) -> str:
    """UPN of a SharePoint person value: an expanded {EMail|Email|Name: 'i:0#.f|membership|upn'} or a claims string."""
    if isinstance(person, Mapping):
        for k in ("Name", "LoginName"):  # claims login name first: EMail can be blank or a different address
            v = str(person.get(k) or "")
            if "|" in v:
                return v.rsplit("|", 1)[1].strip().lower()
        v = person.get("EMail") or person.get("Email") or ""
        return str(v).strip().lower()
    s = str(person or "")
    return s.rsplit("|", 1)[1].strip().lower() if "|" in s else s.strip().lower()


@dataclass(frozen=True)
class Classification:
    verdict: str
    item_id: str
    version: str
    editor_upn: str
    modified_utc: str

    @property
    def reference(self) -> str:
        return "%s:%s:%s" % (TARGET_LIST, self.item_id, self.version)


def classify(change: Mapping, service_upn: str) -> Classification:
    """Trusted iff SharePoint's editor of this version is the configured service identity. An unknown editor fails closed
    (OUT_OF_BAND_EDIT); so does a created item whose author is not the service."""
    svc = (service_upn or "").strip().lower()
    if not svc:
        raise ValueError(MONITOR_CONFIG_INVALID)
    editor = principal_upn(change.get("Editor"))
    author = principal_upn(change.get("Author")) if change.get("Author") is not None else svc
    version = str(change.get("OData__UIVersionString") or "")
    created_now = version in ("1.0", "1") and change.get("Author") is not None
    trusted = editor == svc and (not created_now or author == svc)
    return Classification(TRUSTED_SERVICE_WRITE if trusted else OUT_OF_BAND_EDIT, str(change.get("Id") or ""), version,
                          editor, str(change.get("Modified") or ""))


def build_alert(c: Classification, *, environment: str, detected_utc: str) -> dict:
    """Minimal operational alert: no row content (hours, remark, project, rates), no tokens, headers or payloads."""
    return {"environment": environment, "eventType": EVENT_TYPE, "reason": OUT_OF_BAND_EDIT, "targetEntity": TARGET_LIST,
            "targetItemId": c.item_id, "versionLabel": c.version, "modifiedUtc": c.modified_utc, "editorUpn": c.editor_upn,
            "detectedUtc": detected_utc, "reference": c.reference}


def audit_row(c: Classification, *, environment: str, detected_utc: str, delivery: str) -> dict:
    """AuditLog row (operational sink) for one detection. Not an Approval/Unapproval event."""
    return {"Title": "%s %s %s" % (EVENT_TYPE, "Detect", OUT_OF_BAND_EDIT), "EventType": EVENT_TYPE, "Action": "Detect",
            "Decision": "ALERT", "ResultCode": OUT_OF_BAND_EDIT if delivery == OK else delivery, "OccurredOn": detected_utc,
            "CorrelationId": c.reference, "ActorUpn": c.editor_upn, "TargetList": TARGET_LIST, "TargetItemId": c.item_id,
            "SourceFlow": "SEC-Monitor", "Environment": environment, "Detail": "version %s modified %s" % (c.version, c.modified_utc)}


def alert_destination(settings: Mapping) -> Optional[str]:
    """Configured destination or None. Only a RESOLVED, non-empty configuration value counts."""
    v = settings.get(DESTINATION_SETTING) if settings else None
    if isinstance(v, Mapping):
        v = v.get("value") if v.get("resolution", "RESOLVED") == "RESOLVED" else None
    v = str(v or "").strip()
    return v or None


@dataclass
class MonitorRun:
    code: str
    classifications: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    destination: Optional[str] = None
    delivered: list = field(default_factory=list)


def monitor(changes: Iterable[Mapping], *, service_upn: str, settings: Mapping, environment: str, seen: Optional[set] = None,
            now: Optional[str] = None, send=None) -> MonitorRun:
    """One trigger delivery (one or more changed items). `seen` holds references already alerted (dedupe across
    re-deliveries); `send(destination, alert)` delivers one alert and is called only with a configured destination."""
    detected = now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = set() if seen is None else seen
    try:
        cls = [classify(ch, service_upn) for ch in changes]
    except ValueError:
        return MonitorRun(MONITOR_CONFIG_INVALID)
    dest = alert_destination(settings)
    run = MonitorRun(OK if dest else ALERT_DESTINATION_UNCONFIGURED, cls, destination=dest)
    for c in cls:
        if c.verdict != OUT_OF_BAND_EDIT or c.reference in seen:
            continue
        seen.add(c.reference)
        alert = build_alert(c, environment=environment, detected_utc=detected)
        run.alerts.append(alert)
        if dest and send is not None:
            send(dest, alert)
            run.delivered.append(c.reference)
        run.audit.append(audit_row(c, environment=environment, detected_utc=detected, delivery=OK if dest else ALERT_DESTINATION_UNCONFIGURED))
    return run


def _ts(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(s.replace("Z", "+0000")[:24], "%Y-%m-%dT%H:%M:%S%z")


def alert_latency_seconds(t_change_utc: str, t_alert_utc: str) -> int:
    """Measured live: change time (SharePoint Modified) to alert delivery time."""
    return int((_ts(t_alert_utc) - _ts(t_change_utc)).total_seconds())


def sla_verdict(t_change_utc: str, t_alert_utc: str, sla: int = ALERT_SLA_SECONDS) -> str:
    d = alert_latency_seconds(t_change_utc, t_alert_utc)
    return "PASS" if 0 <= d <= sla else "FAIL"
