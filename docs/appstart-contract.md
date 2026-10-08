# AppStart (TS-AppOpen) — contract and offline qualification

Status: **offline qualified, gaps closed** (OFFLINE-APPSTART-QUALIFICATION-01, OFFLINE-APPSTART-GAP-FIX-01). Not deployed: no valid Power Platform STAGING environment
is available yet. Reference `tools/config/appstart.py`; generated flow `tools/powerautomate/build_appstart_flow.py`
(`appstart_actions`, alias AppStart in `tools/alm/r1_flows.py`); Canvas consumer `tools/powerapp/demo-r1/scrStartup.pa.yaml`.
Tests: `tools/config/test_appstart.py` (AO01–AO22, reference == flow in the WDL simulator) and
`tools/config/test_appstart_qualification.py` (AQ01–AQ16), `tools/config/test_appstart_gapfix.py` (AF01–AF18).

## Chain (as implemented)

```
Canvas: 'TS-AppOpen'.Run(<client type>)
  → flow: Office 365 Users MyProfile_V2 on the INVOKER's own connection   (only identity source)
  → toLower(trim(userPrincipalName)), allowed-domain check
  → SERVICE SharePoint read: Employees?$select=Id,LegacyId,IsActive,Discipline/DisciplineCode,AccountUpn,
                              Department/DepartmentCode&$filter=AccountUpn eq '<upn>'&$top=2&$expand=Department,Discipline
  → 0 rows / >1 row / inactive → deny code
  → 1 active row: Department and Discipline must resolve (projected code non-empty) else INVALID_EMPLOYEE_REFERENCE;
    Position optional (not read)
  → AppOpen / IdentityRejected audit row (service) — MANDATORY
  → AppSettings read (service) → client configuration subset
  → Response (PowerApp): `Respond`, or `Respond_error` when the normal path did not complete
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
| `INVALID_EMPLOYEE_REFERENCE` | `INVALID_EMPLOYEE_REFERENCE` | AppStart only: exactly one active row, but its required Department or Discipline lookup is missing, null or does not resolve |
| `DIRECTORY_ERROR` | `DIRECTORY_ERROR` | Employees read failed, or the caller-profile read (`MyProfile_V2`) failed (never treated as "not found") |
| `INTERNAL_ERROR` | — (AppStart response only) | unexpected failure after the identity entered processing, incl. a failed mandatory AppOpen audit write |
| `ACCOUNT_NOT_ALLOWED` | `ACCOUNT_NOT_ALLOWED` | reference only (disabled / guest flag); the flow has no such flag and relies on the domain check |

Message codes: `MSG_OK`; `MSG_ACCOUNT_NOT_ENABLED` for INVALID_IDENTITY, ACCOUNT_NOT_ALLOWED, UNMAPPED_IDENTITY,
DUPLICATE_IDENTITY, INACTIVE_EMPLOYEE; `MSG_TEMPORARY_PROBLEM` for INVALID_EMPLOYEE_REFERENCE, DIRECTORY_ERROR,
INTERNAL_ERROR. Every failure returns the same keys with no employee code and no configuration; the correlation id is
always the flow run id. `tools/identity/guard.py` `ID_CODES` maps the reference names to the flow names
(see `docs/identity-resolution.md` §3).

## Employee references

| Reference | AppStart | Returned |
|---|---|---|
| Department | **required** — must resolve | no |
| Discipline | **required** — must resolve | no |
| Position | optional — not read | no |

Validated on the stored row read by the service; never from client values, display names, `Author`, `EmployeeAccount`
or `LegacyId`. The guard flows (ReadOwn / SaveEntry) do not apply this check.

## Identity rules confirmed

- Runtime identity = `Employees.AccountUpn` (indexed, enforce-unique, stored lower-case) matched against the invoker's
  `MyProfile_V2` UPN. Never `Author`, the `EmployeeAccount` Person field, display names, `LegacyId` or e-mail guesses.
- All SharePoint calls use the service connection reference; the caller needs no direct Employees, TimesheetEntries,
  AppSettings or AuditLog permission.
- Connections are solution connection-reference placeholders; no account, UPN, URL, secret or token is in source.
- No Dataverse connector, no Default-environment or Production reference.

## Former gaps (closed by OFFLINE-APPSTART-GAP-FIX-01)

1. Department / Discipline integrity → `INVALID_EMPLOYEE_REFERENCE` (decision 1; AF02–AF05, AQ07).
2. Response not extended with employee context → unchanged public contract, no Canvas change (decision 2; AF16).
3. Coded internal failure → `Respond_error`: `DIRECTORY_ERROR` for a failed caller-profile read, `INTERNAL_ERROR`
   for any later failure incl. the mandatory audit write (decision 3; AF09–AF11, AQ12).
