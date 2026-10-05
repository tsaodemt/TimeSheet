# Runbook — Identity Joiner / Mover / Leaver (Timesheet)

| | |
|---|---|
| Status | Draft (EPIC 03); operational guidance from the S03.0 spike |
| Applies to | Entra security groups `SG-TS-*`, SharePoint lists secured by those groups, guard flows |

## F-2 — authorisation propagation (observed 2026-10-05)

| Layer | What happens after an Entra group change | Observed |
|---|---|---|
| Guard flows (Office 365 Groups connector, live membership) | Uses the new membership on the **next run** | Immediate (first run after removal showed `IsReviewer=false`) |
| SharePoint direct access (list UI, REST, Excel) | Front-ends cache group membership. Some requests keep honouring the **old** permission until the caches expire. | Intermittent stale access for **≈ 22 minutes** after removal (load-balancer dependent); stable from ≈ 22 min onwards |

## Procedures

**Leaver** (or loss of a privileged role, e.g. Team Leader, Approver, HR, Finance, AppAdmin):
1. Remove the user from the `SG-TS-*` group(s). Guard-flow rights stop immediately.
2. If **immediate** SharePoint cut-off is required (privileged or confidential access), also:
   - disable the account or **revoke sessions** in Entra; or
   - remove the user from the list or site role assignments directly.
3. Do not treat a single successful denial test as proof of revocation. Re-test over at least 25 minutes, or after a re-authentication in a **new browser session**.
4. Record the change in the access log (`AuditLog` / IT ticket).

**Mover** (discipline or role change):
- Add the new group first, then remove the old one.
- Expect up to ≈ 22 min of **overlapping** SharePoint read rights from the old role. Flow-enforced rights switch immediately.

**Joiner:** a new membership may also take minutes to appear in SharePoint. Ask the user to sign out and in again, or open a new browser session, if access is missing.

**Validation tip:** check a user's current SharePoint authorisation from **their own session** (`_api/web/lists/…/EffectiveBasePermissions`) repeatedly. The admin-side `getusereffectivepermissions` may not reflect front-end caches.

**Requirement note:** if a security requirement demands *instantaneous* revocation of SharePoint read access, group-based permissions alone do not meet it. Session revocation or account disable is required.

**Proxy-only lists:** some lists give employees and reviewers no direct permission, and every read and write goes through a guard flow that checks live group membership (see `security-read-proxy-spike.md`). On these lists, removal from a group takes effect on the next flow run, and the SharePoint cache latency above does not apply. Prefer this pattern for timesheet and confidential data.
