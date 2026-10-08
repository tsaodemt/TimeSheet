"""Reference implementation of the application audit event model (executable specification).

One event = one row in `AuditLog` (operational) or `ConfidentialAuditLog` (rate, finance, KPI-score and
permission changes). Flows emit the same row through tools/powerautomate/audit_template.py; test_audit.py
compares both.

Rules
- The actor always comes from the trusted identity (identity resolution / guard result), never from a request.
- Request fields that claim identity, role or scope are recorded by NAME only (IgnoredInputs).
- Secrets (passwords, tokens, cookies, Authorization headers, MFA/TOTP values, signatures) are never stored:
  matching ChangeJson keys are dropped and listed by name in OmittedFields.
- Confidential values (rates, finance amounts, KPI scores) never reach the operational log.
- Event types whose business rule is still undecided (Unlock, F-5) are rejected unless explicitly enabled.
- Retention is configuration (AppSettings). Unset = decision pending = nothing is ever purged.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "identity"))
import guard as G  # noqa: E402
import identity_resolver as idr  # noqa: E402

OPS_LOG, CONF_LOG = "AuditLog", "ConfidentialAuditLog"

# Event catalogue. `source` = where the spec/backlog defines the behaviour; `enabled` False = decision pending.
EVENT_TYPES = {
    "AppOpen":            {"source": "S03.7 T03.7.2 (built in S05.x)", "enabled": True},
    "IdentityResolved":   {"source": "docs/identity-resolution.md", "enabled": True},
    "IdentityRejected":   {"source": "docs/identity-resolution.md", "enabled": True},
    "AuthorizationAllow": {"source": "docs/authorization-guard.md", "enabled": True},
    "AuthorizationDeny":  {"source": "docs/authorization-guard.md", "enabled": True},
    "ReadProxy":          {"source": "AD-3 guarded read proxy", "enabled": True},
    "WriteProxy":         {"source": "AD-2 guarded write proxy; spec 8.2 #18", "enabled": True},
    "Approval":           {"source": "S07.2 TS-Approve", "enabled": True},
    "Unapproval":         {"source": "S07.3 TS-Unapprove", "enabled": True},
    "Lock":               {"source": "spec 8.2 #17; EPIC 17 registration lock", "enabled": True},
    "Unlock":             {"source": "EPIC 17 decision F-5 (pending)", "enabled": False},
    "SoftDelete":         {"source": "D-7 soft delete", "enabled": True},
    "AdminMaintenance":   {"source": "D-6 EMP-Maintain; MasterDataChange; PermissionChange", "enabled": True},
}
# Legacy display wording required by the backlog (S06.9, S07.2, S07.3).
ACTION_TEXT = {"Create": "Tạo mới", "Update": "Thay đổi", "Delete": "Xóa",
               "Approve": "Phê duyệt: {date}", "Unapprove": "Hủy phê duyệt: {date}"}
ADMIN_ACTIONS = ("EmployeeMaintain", "MasterDataChange", "PermissionChange")

# Lists whose changes belong in ConfidentialAuditLog (spec CONF site catalogue).
CONF_ENTITIES = ("EmployeeRates", "PositionRates", "ProjectFinance", "ProjectPhaseFinance", "ProjectOtherCosts",
                 "CostStructure", "KpiSheets", "KpiLines", "GradeBands", "SalaryBands", "SalaryReviews",
                 "AppRoles", "RolePermissions")
# Value-bearing confidential columns (spec CONF lists). Never written to the operational log.
CONF_FIELDS = ("DailyRate", "ContractValue", "ContractTotal", "RevenueCollected", "RevenueTotal", "OtherCostTotal",
               "Amount", "ExampleAmount", "Percent", "KpiPlus", "KpiMinus", "GradePoints", "GradePointsSum",
               "MinPoints", "MaxPoints", "MinScore", "MaxScore")
_SECRET = re.compile(r"pass(word|wd)?|pwd|token|secret|cookie|authori[sz]ation|bearer|otp|totp|mfa|api[-_]?key|signature|\bsig\b|credential",
                     re.IGNORECASE)
_CONF = re.compile(r"^(result|grade)", re.IGNORECASE)  # KpiSheets Result*/Grade* columns

COLUMNS = ("Title", "EventType", "Action", "ActionText", "Decision", "ResultCode", "OccurredOn", "CorrelationId",
           "ActorUpn", "ActorEmployeeItemId", "TargetList", "TargetItemId", "TargetLegacyId", "OwnerEmployeeItemId",
           "IsOnBehalf", "WorkDate", "ScopeKind", "ScopeRef", "SourceFlow", "Environment", "ChangeJson", "Detail")


class EventNotEnabled(ValueError):
    pass


@dataclass
class AuditEvent:
    TimestampUtc: str
    CorrelationId: str
    EventType: str
    ActorUpn: str
    EmployeeId: Optional[int]
    TargetEntity: str
    TargetId: str
    Action: str
    Decision: str
    ResultCode: str
    ScopeKind: str
    ScopeRef: str
    SourceFlow: str
    Environment: str
    ActionText: str = ""
    TargetLegacyId: str = ""
    OwnerEmployeeId: Optional[int] = None
    IsOnBehalf: Optional[bool] = None
    WorkDate: str = ""
    ChangeJson: str = ""
    IgnoredInputs: list = field(default_factory=list)
    OmittedFields: list = field(default_factory=list)
    ClientType: str = ""
    Sink: str = OPS_LOG

    def to_row(self) -> dict:
        """SharePoint row for AuditLog / ConfidentialAuditLog (spec columns + proposed extension, see docs/audit-model.md)."""
        detail = "ignored=%s;omitted=%s;client=%s" % (",".join(self.IgnoredInputs), ",".join(self.OmittedFields), self.ClientType)
        return {"Title": "%s %s %s" % (self.EventType, self.Action, self.ResultCode),
                "EventType": self.EventType, "Action": self.Action, "ActionText": self.ActionText,
                "Decision": self.Decision, "ResultCode": self.ResultCode, "OccurredOn": self.TimestampUtc,
                "CorrelationId": self.CorrelationId, "ActorUpn": self.ActorUpn,
                "ActorEmployeeItemId": self.EmployeeId, "TargetList": self.TargetEntity, "TargetItemId": self.TargetId,
                "TargetLegacyId": self.TargetLegacyId, "OwnerEmployeeItemId": self.OwnerEmployeeId,
                "IsOnBehalf": self.IsOnBehalf, "WorkDate": self.WorkDate or None, "ScopeKind": self.ScopeKind,
                "ScopeRef": self.ScopeRef, "SourceFlow": self.SourceFlow, "Environment": self.Environment,
                "ChangeJson": self.ChangeJson, "Detail": detail}


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_type(event_type: str, enabled_pending: Iterable[str]) -> None:
    meta = EVENT_TYPES.get(event_type)
    if meta is None:
        raise ValueError("unknown event type %r" % event_type)
    if not meta["enabled"] and event_type not in set(enabled_pending):
        raise EventNotEnabled("%s is not enabled: %s" % (event_type, meta["source"]))


def sanitize_change(change: Optional[Mapping], sink: str) -> tuple:
    """(ChangeJson, OmittedFields). Secret keys are always dropped; confidential values are dropped from the OPS log.
    Nested objects are sanitised recursively; omitted names are reported as dotted paths."""
    omitted = []

    def walk(obj, path):
        if isinstance(obj, Mapping):
            out = {}
            for k, v in obj.items():
                p = "%s.%s" % (path, k) if path else str(k)
                if _SECRET.search(str(k)) or (sink == OPS_LOG and (str(k) in CONF_FIELDS or _CONF.match(str(k)))):
                    omitted.append(p)
                    continue
                out[k] = walk(v, p)
            return out
        if isinstance(obj, list):
            return [walk(v, path) for v in obj]
        return obj
    if not change:
        return "", []
    clean = walk(change, "")
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")), sorted(omitted)


def _split_scope(requested: str) -> tuple:
    kind, _, ref = (requested or "").partition(":")
    return kind, ref


def app_open(identity: Optional[idr.TrustedIdentity], lookup, config: idr.Config, *, correlation_id: str,
             environment: str, client_type: str = "", source_flow: str = "TS-AppOpen", now: Optional[str] = None,
             require_references: bool = False, **untrusted) -> AuditEvent:
    """Application start. Resolved, active employee -> AppOpen/ALLOW/OK (session start).
    Anything else -> IdentityRejected/DENY with the guard's identity code (access denied).
    require_references (AppStart): invalid Department/Discipline -> IdentityRejected/DENY/INVALID_EMPLOYEE_REFERENCE."""
    res = idr.resolve(identity, lookup, config, require_references=require_references)
    ok = res.ok
    emp = res.employee
    return AuditEvent(TimestampUtc=now or utc_now(), CorrelationId=correlation_id,
                      EventType="AppOpen" if ok else "IdentityRejected", ActorUpn=res.upn or "",
                      EmployeeId=emp.item_id if ok else None, TargetEntity="", TargetId="", Action="AppOpen",
                      Decision=G.ALLOW if ok else G.DENY, ResultCode="OK" if ok else G.ID_CODES.get(res.code, G.DIRECTORY_ERROR),
                      ScopeKind="", ScopeRef="", SourceFlow=source_flow, Environment=environment,
                      IgnoredInputs=sorted(untrusted), ClientType=str(client_type or "")[:40])


def authorization_event(result: G.GuardResult, *, source_flow: str, environment: str, now: Optional[str] = None) -> AuditEvent:
    """The guard's own decision as an event (AuthorizationAllow / AuthorizationDeny)."""
    kind, ref = _split_scope(result.RequestedScope)
    return AuditEvent(TimestampUtc=now or utc_now(), CorrelationId=result.CorrelationId,
                      EventType="AuthorizationAllow" if result.allowed else "AuthorizationDeny",
                      ActorUpn=result.AuthenticatedUpn or "", EmployeeId=result.EmployeeId, TargetEntity="", TargetId="",
                      Action=result.RequestedAction, Decision=result.AuthorizationDecision, ResultCode=result.ResultCode,
                      ScopeKind=kind, ScopeRef=ref, SourceFlow=source_flow, Environment=environment,
                      IgnoredInputs=list(result.IgnoredInputs))


def operation_event(result: G.GuardResult, event_type: str, action: str, *, target_entity: str, target_id: str = "",
                    source_flow: str, environment: str, outcome_code: Optional[str] = None,
                    target_legacy_id: str = "", owner_employee_id: Optional[int] = None,
                    is_on_behalf: Optional[bool] = None, work_date: str = "", change: Optional[Mapping] = None,
                    enabled_pending: Iterable[str] = (), now: Optional[str] = None) -> AuditEvent:
    """A business operation performed (or refused) after the guard ran.
    The decision can never be ALLOW when the guard denied; `outcome_code` lets the flow report a later refusal
    (e.g. LOCKED, VALIDATION, ERROR) for an operation the guard allowed."""
    _check_type(event_type, enabled_pending)
    if event_type == "AdminMaintenance" and action not in ADMIN_ACTIONS:
        raise ValueError("unknown admin action %r" % action)
    allowed = result.allowed and outcome_code in (None, G.R_ALLOW)
    code = G.R_ALLOW if allowed else (result.ResultCode if not result.allowed else outcome_code)
    sink = CONF_LOG if target_entity in CONF_ENTITIES else OPS_LOG
    change_json, omitted = sanitize_change(change, sink)
    kind, ref = _split_scope(result.RequestedScope)
    text = ACTION_TEXT.get(action, "").format(date=work_date) if action in ACTION_TEXT else ""
    return AuditEvent(TimestampUtc=now or utc_now(), CorrelationId=result.CorrelationId, EventType=event_type,
                      ActorUpn=result.AuthenticatedUpn or "", EmployeeId=result.EmployeeId, TargetEntity=target_entity,
                      TargetId=str(target_id or ""), Action=action, ActionText=text,
                      Decision=G.ALLOW if allowed else G.DENY, ResultCode=code, ScopeKind=kind, ScopeRef=ref,
                      SourceFlow=source_flow, Environment=environment, TargetLegacyId=target_legacy_id,
                      OwnerEmployeeId=owner_employee_id, IsOnBehalf=is_on_behalf, WorkDate=work_date,
                      ChangeJson=change_json, IgnoredInputs=list(result.IgnoredInputs), OmittedFields=omitted, Sink=sink)


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention comes from AppSettings (`AuditRetentionDays`, `ConfidentialAuditRetentionDays`).
    Unset -> status PENDING_IT_CUSTOMER_DECISION, purge disabled. No default duration exists in code (IT-08 open)."""
    days: Optional[int]
    status: str

    @classmethod
    def from_settings(cls, settings: Mapping[str, object], sink: str = OPS_LOG) -> "RetentionPolicy":
        key = "AuditRetentionDays" if sink == OPS_LOG else "ConfidentialAuditRetentionDays"
        raw = settings.get(key)
        if raw is None or str(raw).strip() == "":
            return cls(None, "PENDING_IT_CUSTOMER_DECISION")
        try:
            days = int(str(raw).strip())
        except ValueError:
            return cls(None, "INVALID_SETTING")
        if days <= 0:
            return cls(None, "INVALID_SETTING")
        return cls(days, "CONFIGURED")

    @property
    def purge_enabled(self) -> bool:
        return self.status == "CONFIGURED"

    def is_expired(self, occurred_on: str, now: _dt.datetime) -> bool:
        """Fail safe: never expired unless a valid retention period is configured."""
        if not self.purge_enabled:
            return False
        ts = _dt.datetime.strptime(occurred_on, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        return now - ts > _dt.timedelta(days=self.days)
