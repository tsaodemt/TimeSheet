# Application Identity Resolution (contract)

Status: **specified and tested against the reference implementation** (`tools/identity/`). The resolver has not yet been wired into the production app or flows, because the app shell and the mapping load have not been built.

## 1. Chain

```
trusted authenticated identity      platform-supplied only
  → normalised UPN                  trim · Unicode NFC · lower-case · syntax · allowed tenant domain
  → Employees row                   Employees.AccountUpn eq <upn>  (indexed, unique, stored normalised)
  → application identity            EmployeeItemId (environment) + LegacyId (portable business key), discipline, active flag
  → role / capability context       live Entra group membership → AppRoles → capabilities (union)
```

**Fail closed.** If any step fails, the caller gets no employee context, no roles and no capabilities.

## 2. Sources of trust

| Client | Trusted identity | Never trusted |
|---|---|---|
| Guard flow (authoritative) | Office 365 Users `MyProfile_V2` on the **caller's own** connection (run-only user / app user) | Request fields `CallerUpn`, `OwnerUpn`, `ActorUpn`, role or reviewer flags, display name, SharePoint `Author`, arbitrary HTTP headers. `x-ms-user-*` headers are only cross-checked. |
| Power Apps (UI only) | Signed-in user (`User().Email` or `Office365Users.MyProfileV2().userPrincipalName`) | Anything typed or passed between screens |

The app's resolution only decides what the UI shows. Every guard flow resolves the caller again, independently. The app never sends an identity that a flow relies on.

## 3. Result codes

Canonical (flow / guard / AppStart response) names first; the reference resolver (`identity_resolver.py`) uses the
older names in brackets, mapped by `guard.ID_CODES`.

| Code | Condition | UI | Flow |
|---|---|---|---|
| `OK` | exactly one active row (AppStart: and required references valid) | Home | continue |
| `INVALID_IDENTITY` | no identity, malformed, or domain not in configuration | not-registered screen | reject, audit |
| `ACCOUNT_NOT_ALLOWED` | account disabled or guest (reference; flows rely on the domain check) | not-registered screen | reject, audit |
| `UNMAPPED_IDENTITY` (`NOT_REGISTERED`) | tenant user without an `Employees` row | not-registered screen | reject, audit |
| `INACTIVE_EMPLOYEE` (`INACTIVE`) | mapped row is not active | not-registered screen | reject, audit |
| `DUPLICATE_IDENTITY` (`DUPLICATE_MAPPING`) | more than one row claims the UPN (data error) | "temporarily unavailable" screen; administrator alert | reject, audit, alert |
| `INVALID_EMPLOYEE_REFERENCE` | AppStart only: required Department or Discipline does not resolve | "temporarily unavailable" | reject, audit |
| `DIRECTORY_ERROR` | lookup failed (Employees read or caller profile) | "temporarily unavailable, retry" | reject (never treated as "not found") |
| `INTERNAL_ERROR` | AppStart only: unexpected failure after identity processing started, incl. failed audit write | "temporarily unavailable" | reject; no data returned |

**Roles come only from Entra groups.** A resolved employee who is in no group gets employee context but **no** capabilities. Granting a baseline role without group membership is a configuration option and a customer decision. Unresolved production role holders receive the Employee role only.

## 4. Data rules

- `Employees.AccountUpn`: single line of text, **indexed and enforce-unique**, stored normalised (lower-case). Only the guarded mapping load writes it. HR/AppAdmin manage it through an audited flow; no one edits it directly.
- The load writes `AccountUpn` only for rows approved for the target environment. STAGING may use provisional mappings; production requires HR/IT approval. Unmapped, inactive and status-conflict rows are **never** given a UPN.
- `EmployeeAccount` (Person) is display convenience only. It is tenant-bound and never an authorisation key.
- The SharePoint numeric user ID, the Entra object ID and `Author` are **not** business keys.

## 5. Flow pattern (Power Automate)

1. `Get_caller_profile` = Office 365 Users `MyProfile_V2`, on the run-only user's connection.
2. `CallerUpn = toLower(trim(body('Get_caller_profile')?['userPrincipalName']))`. The domain is checked against the environment variable `TS_AllowedDomains`.
3. `Get items` on `Employees`: `$filter=AccountUpn eq '<CallerUpn>'`, `$top=2`, `$select=Id,LegacyId,IsActive,Discipline/DisciplineCode`
   (AppStart also `Department/DepartmentCode`).
   - 0 rows → `UNMAPPED_IDENTITY`.
   - 2 rows → `DUPLICATE_IDENTITY`.
   - `IsActive` false → `INACTIVE_EMPLOYEE`.
   - AppStart only: Department or Discipline not resolvable → `INVALID_EMPLOYEE_REFERENCE` (Position optional).
4. Role checks: live membership of the role group(s) the requested action needs. The checks run through the service Groups connection on every run and are never cached.
5. The response and audit carry the code. Request identity fields are logged as "claimed" only.

## 6. Not-registered screen

- Shows the signed-in account, a short reason ("not registered" / "inactive" / "temporarily unavailable") and whom to contact (HR).
- Loads **no** data, has no navigation and calls no data flows. The flows reject the user independently.
- The bilingual text (Vietnamese / English) is defined in the app's string table.

## 7. Session behaviour (replaces "remember login")

- No username list, password field or credential cache exists in the app. Sign-in, MFA and session lifetime are handled by Entra ID single sign-on.
- "Stay signed in" is the Entra browser/Teams session. Session length and re-authentication follow tenant policy; finer sign-in-frequency control needs Conditional Access licensing.
- Sign-out means Entra sign-out. Revocation is a disable or session revoke in Entra (see `runbook-identity-jml.md`).

## 8. Tenant portability

- Configuration supplies the allowed domains, site URLs, list names and role-group IDs. Nothing is hard-coded.
- Business identity = `LegacyId` / `EmployeeItemId`. A tenant move needs an `OldUpn → NewUpn` map; unknown UPNs are **not** guessed. Person columns must be re-resolved in the new tenant.
- Tests I1–I10 in `tools/identity/test_identity_resolver.py` cover mapped, case-insensitive, forged, unmapped, duplicate, inactive, status-conflict, non-employee, flow-usable and tenant-move cases.
