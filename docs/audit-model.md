# Application audit model

One audit row per security-relevant event. Rows go to `AuditLog` (operational) or `ConfidentialAuditLog` (rate, finance, KPI-score and permission changes). The model exists once and is consumed by every flow.

| Artefact | Role |
|---|---|
| `tools/audit/audit_event.py` | Reference implementation: event catalogue, row builder, sanitising, retention policy |
| `tools/powerautomate/audit_template.py` | Generates the same rows inside flows: the AppOpen flow, the guard decision event, business-operation events |
| `tools/audit/test_audit.py` | A1–A10. Each case runs through the reference **and** the generated flow actions (offline WDL interpreter); the rows must be identical |

Status: specification, reference implementation and generators. The audit lists are provisioned and wired into flows later, when the audit lists and the app shell are built. Nothing here is deployed yet.

## Event types

| EventType | When | Action examples |
|---|---|---|
| `AppOpen` | App start, resolved and active employee: session start | `AppOpen` |
| `IdentityRejected` | App start, identity not usable: access denied | `AppOpen` |
| `IdentityResolved` | Identity-only call succeeded (no authorization decision) | – |
| `AuthorizationAllow` / `AuthorizationDeny` | The guard's decision | capability, e.g. `TS.Approve` |
| `ReadProxy` | Guarded read | – |
| `WriteProxy` | Guarded create or update | `Create`, `Update` |
| `Approval` / `Unapproval` | Approve or unapprove | `Approve`, `Unapprove` |
| `Lock` | A lock is applied | – |
| `SoftDelete` | Record marked deleted (no hard delete by the service) | `Delete` |
| `AdminMaintenance` | Audited administrative changes | `EmployeeMaintain`, `MasterDataChange`, `PermissionChange` |
| `Unlock` | **Disabled.** The business rule is not decided; the builders reject it unless it is explicitly enabled. | – |

A write refused because the record is locked is a `WriteProxy` event with `Decision=DENY` and `ResultCode=LOCKED`.

Legacy display wording is kept in `ActionText`: `Tạo mới`, `Thay đổi`, `Xóa`, `Phê duyệt: <date>`, `Hủy phê duyệt: <date>`.

## Fields

| Model field | List column | Source |
|---|---|---|
| TimestampUtc | `OccurredOn` | flow `utcNow()` |
| CorrelationId | `CorrelationId` | flow run name, shared by every row of one run |
| EventType, Action, ActionText | same | generator / builder |
| ActorUpn | `ActorUpn` | **trusted** identity only |
| EmployeeId | `ActorEmployeeItemId` | resolved employee row |
| TargetEntity, TargetId | `TargetList`, `TargetItemId` | the stored record that was acted on |
| Decision, ResultCode | same | guard result; a later refusal (e.g. `LOCKED`) can only turn `ALLOW` into `DENY`, never the reverse |
| ScopeKind, ScopeRef | same | requested scope (checked by the guard) |
| SourceFlow, Environment | same | configuration |
| TargetLegacyId, OwnerEmployeeItemId, IsOnBehalf, WorkDate, ChangeJson | same | stored record / server-side values (`TargetLegacyId` = the stored record's `LegacyId`, stamped together with `TargetItemId`; empty when no record was written) |
| IgnoredInputs, OmittedFields, ClientType | `Detail` | names only |

Result codes reuse the guard vocabulary (`docs/authorization-guard.md`):
- `OK` for a session start;
- `UNMAPPED_IDENTITY`, `INACTIVE_EMPLOYEE`, `DUPLICATE_IDENTITY`, `INVALID_IDENTITY`, `DIRECTORY_ERROR` for rejected identities;
- `ALLOW` and the guard deny codes for decisions.

## Trust boundary

- The actor, the actor's employee ID and the roles come only from identity resolution or the guard result. A request cannot set `ActorUpn`, `EmployeeId`, role, scope or owner.
- Request fields that claim identity, role or scope are listed by **name** in `IgnoredInputs`. Their values are not written.
- Owner and target values must come from the stored record that the flow read, not from the request.

## What is never written

- **Secrets.** Any change field whose name matches password, token, secret, cookie, authorization/bearer, OTP/TOTP/MFA, API key, signature or credential. These are dropped, also in nested objects, and their names are listed in `OmittedFields`.
- **Confidential values in the operational log.** Rate, finance-amount and KPI-score columns are dropped from `AuditLog` rows. Changes to confidential lists go to `ConfidentialAuditLog`, where values are kept, but secrets are still removed.
- **Personal telemetry.** IP addresses, device details and raw authentication data are not written. The sign-in platform already records them.

In flows, change fields are server-side expressions chosen when the flow is generated. The generator removes secret and confidential names at that point, so no sanitising runs at run time.

## AppOpen

The app shell calls the AppOpen flow once per session. The flow reuses the guard's identity actions: trusted caller (the invoker's own connection), then the employee by `AccountUpn`, then the identity code. It does not look up roles, because AppOpen grants nothing.

- Resolved and active: one row `AppOpen / ALLOW / OK`. The response carries the employee code and the correlation ID.
- Anything else: one row `IdentityRejected / DENY / <identity code>`. The response carries the code, and the app shows the "not registered" screen.

## Retention

**RETENTION = PENDING_IT_CUSTOMER_DECISION.** No duration exists in code.

Retention comes from `AppSettings`:
- `AuditRetentionDays`;
- `ConfidentialAuditRetentionDays`.

| Setting value | Result |
|---|---|
| Missing or empty | `PENDING_IT_CUSTOMER_DECISION`; purge disabled; nothing is ever treated as expired |
| Zero, negative or not an integer | `INVALID_SETTING`; purge disabled |
| Positive integer | `CONFIGURED`; rows older than N days are purge candidates |

## Using the templates in a flow

Several audit events can live in one flow. Use the `name` parameter to keep action names apart; the default is `Audit_event` / `Write_Audit_event`.

The guard's spike-era audit row (`legacy_audit=True`, the default) remains as live-validated for the spike flows. It does not fit `AuditLog`, because it has unknown columns and lacks the required ones. Flows that write `AuditLog` (the R1 flows) pass `legacy_audit=False` and record the decision with `authorization_event_actions()`.

A row without a work date sends `WorkDate = null`, never `""`, because the column is a date.

What happens when an audit append fails is an open decision (AUD-F1). Today the flows fail closed: nothing runs after a failed append, so a failed append after a persisted write leaves the caller without a response. See `r1-lists-auditlog-timesheetentries.md`.
