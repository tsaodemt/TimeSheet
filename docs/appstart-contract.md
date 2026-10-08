# AppStart (TS-AppOpen) — contract and offline qualification

Status: **offline qualified** (OFFLINE-APPSTART-QUALIFICATION-01). Not deployed: no valid Power Platform STAGING environment
is available yet. Reference `tools/config/appstart.py`; generated flow `tools/powerautomate/build_appstart_flow.py`
(`appstart_actions`, alias AppStart in `tools/alm/r1_flows.py`); Canvas consumer `tools/powerapp/demo-r1/scrStartup.pa.yaml`.
Tests: `tools/config/test_appstart.py` (AO01–AO22, reference == flow in the WDL simulator) and
`tools/config/test_appstart_qualification.py` (AQ01–AQ16).

## Chain (as implemented)

```
Canvas: 'TS-AppOpen'.Run(<client type>)
  → flow: Office 365 Users MyProfile_V2 on the INVOKER's own connection   (only identity source)
  → toLower(trim(userPrincipalName)), allowed-domain check
  → SERVICE SharePoint read: Employees?$select=Id,LegacyId,IsActive,Discipline/DisciplineCode,AccountUpn
                              &$filter=AccountUpn eq '<upn>'&$top=2
  → 0 rows / >1 row / inactive → deny code;  1 active row → OK
  → AppOpen / IdentityRejected audit row (service)
  → AppSettings read (service) → client configuration subset
  → Response (PowerApp)
```

## Request

| Field | Use |
|---|---|
| `text` (client type) | logged only (truncated to 40 chars) |
| `CallerUpn`, `ActorUpn`, `OwnerUpn`, `EmployeeId`, `Role`, `Scope`, `UserPrincipalName`, `Config` | **never read for decisions**; written to the audit detail as "claimed" values only |

No request field can select, override or impersonate an employee.

## Response (current contract — all values strings)

| Key | Success | Failure |
|---|---|---|
| `ok` | `"true"` | `"false"` |
| `resultcode` | `OK` | identity deny code (below) |
| `messagecode` | `MSG_OK` | `MSG_ACCOUNT_NOT_ENABLED` / `MSG_TEMPORARY_PROBLEM` |
| `correlationid` | flow run id | flow run id |
| `employeecode` | `LegacyId` of the caller's row | empty |
| `configstatus` | `OK` / `CONFIG_UNRESOLVED` / `CONFIG_INVALID` | empty |
| `config`, `interim` | JSON text of the client settings subset / interim markers | `{}` |
| `missing` | comma list of unresolved client keys | empty |

By design the response contains **no** SharePoint item id, list name, URL, display name, Department, Discipline or Position,
and AppStart grants nothing (no role lookup). Roles, scope and discipline are resolved again by every guard flow.

## Result codes

| Code (flow / guard) | Reference resolver | Condition |
|---|---|---|
| `OK` | `OK` | exactly one active row |
| `INVALID_IDENTITY` | `INVALID_IDENTITY` | empty / malformed UPN or domain not allowed (guest `#EXT#` UPNs land here) |
| `UNMAPPED_IDENTITY` | `NOT_REGISTERED` | no row |
| `DUPLICATE_IDENTITY` | `DUPLICATE_MAPPING` | more than one row (unique index bypassed / malformed data) |
| `INACTIVE_EMPLOYEE` | `INACTIVE` | row not active |
| `DIRECTORY_ERROR` | `DIRECTORY_ERROR` | Employees read failed (never treated as "not found") |
| `ACCOUNT_NOT_ALLOWED` | `ACCOUNT_NOT_ALLOWED` | reference only (disabled / guest flag); the flow has no such flag and relies on the domain check |

`docs/identity-resolution.md` §3 uses the reference names; `tools/identity/guard.py` `ID_CODES` maps them to the flow names.

## Identity rules confirmed

- Runtime identity = `Employees.AccountUpn` (indexed, enforce-unique, stored lower-case) matched against the invoker's
  `MyProfile_V2` UPN. Never `Author`, the `EmployeeAccount` Person field, display names, `LegacyId` or e-mail guesses.
- All SharePoint calls use the service connection reference; the caller needs no direct Employees, TimesheetEntries,
  AppSettings or AuditLog permission.
- Connections are solution connection-reference placeholders; no account, UPN, URL, secret or token is in source.
- No Dataverse connector, no Default-environment or Production reference.

## Gaps (not changed — decisions required)

1. **Department / Discipline not validated by AppStart.** An active mapped row with an empty or dangling Department or
   Discipline lookup returns `OK` (AQ07). SharePoint enforces both as required on write, but nothing checks dangling
   references at runtime and no `INVALID_EMPLOYEE_REFERENCE` code exists. Decide whether AppStart (or only the guard
   flows that use the discipline) must fail closed, and with which code and message.
2. **Department / Discipline / Position / display name are not returned.** The Canvas app gets only `employeecode`.
   If the app must show employee context, the response contract must be extended (and the "no internals" rule kept).
3. **No `INTERNAL_ERROR` result.** If `MyProfile_V2` or the audit write fails, the run fails before `Respond` (AQ12);
   the app receives no response and the startup screen falls back to the access-denied screen with an empty code.
   Fail-closed, but not a deterministic coded response.
4. Position is optional in the schema and not read by AppStart, so a missing Position cannot fail AppStart (AQ08).
