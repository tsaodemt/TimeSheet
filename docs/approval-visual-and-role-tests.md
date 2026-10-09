# Approval visual state, Home pending count and role / rule tests — S07.5 / S07.6

Status 2026-10-09: **S07.5 DONE, S07.6 DONE** (STAGING live-proven; evidence kept in the private working area). Builds on
`approval-capability-rules.md` (gate G5, closed), `approve-contract.md` (S07.2 / S07.3) and `immutability-and-monitor.md` (S07.4).

## S07.5 — visual state and pending count

Legacy (reviewed in the decompiled source): an approved row shows a 16 x 16 lock icon in the grid row header; Draft rows
show nothing; there is no approval colour (the only row colour in that grid marks the hour type) and no pending count.
Approve / unapprove repaint the grid.

| Element | Target | Source of truth |
|---|---|---|
| Lock indicator | `Icon.Lock` at the start of every Approved row in **My timesheet** and **Team approval** (both modes); accessible label "Đã phê duyệt". Draft rows have no lock (legacy parity) | `status` returned by TS-ReadOwn / TS-ReadTeam |
| Row fill | Approved rows: neutral light grey (read-only convention); Draft: transparent. Secondary to the icon; no business meaning carried by colour alone | same |
| Edit affordance | Unchanged: Edit only on Draft rows; the server returns `LOCKED` anyway (S07.4) | same |
| Team approval | Pending mode (Draft, multi-select Phê duyệt) and Approved mode (per-row Hủy phê duyệt, no batch) unchanged | TS-ReadTeam |
| Home pending count | "Chờ phê duyệt: N" next to the Team approval button on the landing screen (the current app has no separate Home screen; the landing screen is the current-period summary). N = rows of the **same guarded TS-ReadTeam Pending read** as the queue (role, scope, self exclusion, Draft, period decided by the server), one bounded page of 500; a further page shows "500+" | TS-ReadTeam, Mode empty |
| Roles without approval | The count read returns `ROLE_NOT_ALLOWED`: no count, the Team approval button hides for the session, no error banner. No client-side count of entries exists | server |
| Refresh | The landing screen re-reads the count on every visit and on reload; a successful approve / unapprove clears the shown count until then | — |

"App and list views" = the Canvas galleries above. Ordinary users have no SharePoint view of TimesheetEntries (protected
list; guarded flows only); none was created. No flow contract changed (TS-ReadTeam Mode empty / Pending / Approved behave as
in S07.2 / S07.3). Note: each landing-screen visit runs one TS-ReadTeam call and writes its mandatory authorization and
ReadProxy audit rows (a role without approval writes one AuthorizationDeny per visit).

Tests: `tools/powerapp/test_approval_visual.py` V01–V22 (visual state, count = reference/flow TS-ReadTeam result per role,
refresh, compatibility, no protected data source, confirm-button geometry, known control types). Studio paste once more
moved the team gallery over the confirm buttons; it was reset and checked (the test pins the geometry).

## S07.6 — approval permission and rule tests

Rule inventory: BR-APPR-01..09 and BR-EDIT-01 / BR-EDIT-03 from the legacy rule catalogue; role expectations from gate
G5 (which overrides older role tables). Current roles = the 12 configured role keys; legacy Director is retired with no
mapping. Technical privilege (App Administrator, IT Support, owners) never implies approval.

| Role category | Approve | Unapprove |
|---|---|---|
| Employee | DENY | DENY |
| Team Leader | ALLOW own discipline (foreign rows) | DENY |
| Approver, Executive | ALLOW company (foreign rows) | ALLOW company (foreign rows) |
| PM/PMO, HR, Salary viewer, Finance, App Administrator, IT Support, Confidential owner, Migration owner | DENY | DENY |
| Any role, own row | DENY | DENY |

| Rule | Target behaviour | Deviation (signed) | Offline | Live | Result |
|---|---|---|---|---|---|
| BR-APPR-01 approve selected rows after confirm | per-row TS-Approve after the legacy confirm text; Approved row not re-stamped | no restamp (immutability) | RM02, RM04 | approve paths | PASS |
| BR-APPR-02 who may approve | G5 matrix above | G5 | RM01, RM02, RM06, RM12 | every role | PASS |
| BR-APPR-03 self-approval | denied for all roles | UD-04 (legacy gap fixed) | RM03 | self cases | PASS |
| BR-APPR-04 unapprove | explicit per-row action + confirm; typed refusal instead of silent no-op | G5 / UD-05 | RM05, RM06 | every role | PASS |
| BR-APPR-05 per row, no period / notification | same | — | RM07 | per-row results | PASS |
| BR-APPR-06 approved rows highlighted | lock icon (+ neutral fill) | — | RM08, V01–V07 | S07.5 | PASS |
| BR-APPR-07 approval does not change data / reports | only approval fields written; reports not built yet | reports NOT_IMPLEMENTED_CURRENT_PATH | RM09 | owner read | PASS |
| BR-APPR-08 author overwritten | author / created / owner preserved | defect fixed | RM10 | provenance checks | PASS |
| BR-APPR-09 current-year copy only | single row per entry | defect not replicated | RM11 | single-row writes | PASS |
| BR-EDIT-01 approved edit refused | `LOCKED` "Dữ liệu đã được phê duyệt" | W-1 | RM13 | S07.4 LIVE | PASS |
| BR-EDIT-03 approved delete skipped silently | shared invariant returns typed `LOCKED`; delete path not built | D-1; reorder R-1 | RM14 | — (no path) | PASS (invariant); path NOT_IMPLEMENTED_CURRENT_PATH |

Offline: `tools/approval/test_approval_role_matrix.py` RM01–RM14 + RM99 runs every role (alone and on top of Employee)
through the reference and the generated flows side by side, checks typed refusal, no write, no successful event and the
deny audit for every denial, the full success proof (state, approver, UTC time, preserved provenance, exactly one event)
for every allow, and forged client claims (role, scope, owner, approver, status, discipline). It writes a
machine-checkable role x rule matrix (PASS / NOT_APPLICABLE with reason; no skip).

Live (STAGING, one test identity, temporary membership of one role group at a time, each group restored to its baseline
before the next): every role has a server-side approve and unapprove result; negative cases for roles without a UI path
re-point the app's own request to the approve / unapprove flow with the caller identity untouched.

### Live result summary (STAGING, 2026-10-09; sanitized)

| Rule | Role category | Expected | Actual | Result | Evidence type |
|---|---|---|---|---|---|
| BR-APPR-02 | Employee | approve DENY | ROLE_NOT_ALLOWED | PASS | live server call |
| BR-APPR-04 | Employee | unapprove DENY | ROLE_NOT_ALLOWED | PASS | live server call |
| BR-APPR-02 | Team Leader | same-discipline approve ALLOW | OK, one Approval event | PASS | live app (UI) |
| BR-APPR-02 | Team Leader | cross-discipline approve DENY | SCOPE_NOT_ALLOWED, no write | PASS | live server call |
| BR-APPR-04 | Team Leader | unapprove DENY | ROLE_NOT_ALLOWED | PASS | live app + earlier live evidence |
| BR-APPR-01/02, 04 | Approver | approve / unapprove ALLOW (company) | OK / OK, one event each | PASS | live app (UI) |
| BR-APPR-01/02, 04 | Executive | approve / unapprove ALLOW (company, other discipline) | OK / OK, one event each | PASS | live app (UI) |
| BR-APPR-03 | Team Leader, Approver, Executive | self approve DENY | ROLE_NOT_ALLOWED, no write | PASS | live server call |
| BR-APPR-04 | Approver, Executive | self unapprove DENY | ROLE_NOT_ALLOWED, no write | PASS | live server call |
| BR-APPR-02 / 04 | PM/PMO, HR, Salary viewer, Finance, App Administrator, IT Support, Confidential owner, Migration owner | approve DENY, unapprove DENY | ROLE_NOT_ALLOWED / ROLE_NOT_ALLOWED | PASS | live server call |
| BR-APPR-06 | all | lock on Approved, none on Draft | as expected | PASS | live app |
| BR-APPR-08 | approve / unapprove | provenance preserved, approver fields set / cleared | as expected | PASS | live data read |
| BR-EDIT-01 | owner | Approved save LOCKED | LOCKED "Dữ liệu đã được phê duyệt" | PASS | earlier live evidence (S07.4) |
| BR-EDIT-03 | all | typed LOCKED (invariant) | invariant PASS; no delete path | PASS (path not built) | offline |

Unexpected allow: 0. Unexpected deny: 0. All temporary role memberships were restored to their baselines; the security
baseline (no direct list access for users, service View/Add/Edit only, protected lists absent from the app) is unchanged.
