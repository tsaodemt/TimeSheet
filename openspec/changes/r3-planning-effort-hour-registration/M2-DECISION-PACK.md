# M2 decision pack — EPIC 16 Project Effort Registration (rev01 A.I and A.III)

Status 2026-10-10: **DECISION CLOSURE COMPLETE — NO IMPLEMENTATION.** M1 / S12.5 Hour Registration is DONE (legacy
parity) and is not reopened. Every M2 decision is now answered by the owner. **M2 decision gate: CLEAR (0 open).
M2_IMPLEMENTATION_GATE = DECISIONS_COMPLETE — AWAITING OWNER RELEASE**: implementation starts only after the owner
accepts the M2 data/security model, flow contracts, UX, tests and STAGING prerequisites (R3-G0 for M2, `design.md` §14)
and the tasks are re-baselined (task 0.5). Register: `decisions.md`. Checker: `tools/spec/check_r3_open_spec.py`.
Vietnamese record: `M2-DECISION-SUMMARY.md`.

Evidence classes: **LEGACY_FACT** · **CUSTOMER_REQUIREMENT** · **OWNER_DECISION** · **TARGET_SECURITY_REQUIREMENT** ·
**PROPOSED_DESIGN** · **OPEN_DECISION**.

## 1. Sources

| Source | What it settles | Class |
|---|---|---|
| Customer document "Đăng ký công – rev01" (re-extracted with its list numbering) | **A.I** "Đăng ký công cho dự án" (1. "Người thực hiện: PM"; 2. "Dữ liệu: từ bảng phân bổ sản lượng dự án"; 3. "Công đăng ký: cho Quản lý phòng, PM, bộ môn (điện, lạnh, nước và BIM)"), **A.II** discipline registration (ceiling "không vượt quá số công mục I.3"; Chủ trì approves → lock), **A.III** "Công thực hiện dự án" (Chấm công; Chủ trì approves → lock), **B** statistics | CUSTOMER_REQUIREMENT |
| Same document | A.I names no approver, no lock, no phase, no period, no unit other than "công" (verified absence) | CUSTOMER_REQUIREMENT (absence) |
| Owner decisions 2026-10-10 (three rounds) | OD-14, 16, 19, 22, 23, 24, 33, 37, 40, 44 decided; OD-41 not applicable | OWNER_DECISION |
| Legacy data dictionary E05 / E08; target `Projects` | no PM field today; assignment list has no role and is unused | LEGACY_FACT |
| Live Timesheet (EPIC 06/07) | trusted actor vs business owner; authorised on-behalf entry; EPIC 07 Approved state | TARGET_SECURITY_REQUIREMENT |

## 2. M2 gate (derived, not copied)

Derived by the checker from the register's Blocking column: **no open M2 decision** (no conditional blocker; OD-41
NOT_APPLICABLE). Decisions that block only M3 remain open in the register (incl. OD-45 EPIC 17 unit and OD-46 EPIC 17
visibility).

## 3. Owner decisions (not reopened)

| ID | Decision | Effect on EPIC 16 |
|---|---|---|
| OD-14 | **MAN_DAY** | Project Effort unit = man-day; ≤ 2 decimals, more is **rejected** with `VALIDATION_VALUE` (no rounding / truncation / normalisation); conversion from Timesheet hours via `HoursPerManDay`; own schema; **EPIC 16 only** (EPIC 17 unit = OD-45, OPEN_FOR_M3) |
| OD-44 | **MIN_0 / NEGATIVE_DENY / NO_BUSINESS_MAX** | Minimum 0; negative → `VALIDATION_VALUE`; no business maximum; IEEE-754 double range of SharePoint / Power Fx = TECHNICAL_LIMIT only |
| OD-40 | **BLANK_NOT_REGISTERED / ZERO_EXPLICIT** | Blank and 0 are distinct states; blank never coerced to 0; storage designed in the EPIC 16 schema |
| OD-16 | **MANUAL_PM_ENTRY** | The PM types the values; no formula, no finance derivation, no import (OD-36 stays non-blocking, outside M2); no source-reference column |
| OD-22 | **NO_PHASE_DIMENSION** | Grain = project × recipient |
| OD-23 | **PROJECT_LIFETIME** | One lifetime value per recipient; no period key, no registration window; changes audited |
| OD-24 | **ONE_AUTHORITATIVE_PM_PER_PROJECT_MAINTAINED_BY_PMO** | ≤ 1 PM (person, stable employee key) stored on the project; only PMO sets it (guarded, audited); allocations editable only by that PM (new project-PM guard scope); PMO / Executive do not edit by role; no PM → not editable. Owner wrote "OD-24 = A" with this text; it is recorded by its text, which was option (b) of the earlier list (option (a) "PMO role, company scope" is not chosen) |
| OD-19 | **TIMESHEETENTRIES** | Actual effort from existing `TimesheetEntries`; no new list / workflow / screen; existing Timesheet semantics and security unchanged; source only |
| OD-33 | **APPROVED_ONLY** | Only EPIC 07 Approved rows count; Draft excluded; actual man-days = Σ Approved hours ÷ `HoursPerManDay` in the reporting/query contract |
| OD-37 | **VIEW_PROJECT_PM_PMO_EXECUTIVE** | Planned Project Effort and the project-level Approved actual total: project PM (own projects), PMO, Executive; all other roles DENY; not inherited from OD-05; Team Leader / Quản lý phòng later (OD-46 / OD-31) |
| OD-41 | **NOT_APPLICABLE** (consequence of OD-19) | Existing Timesheet ownership rules apply unchanged |

## 4. Capability effect (proposed seed, `planning-security`)

| Capability | Role grants | Project-PM scope grant |
|---|---|---|
| `EFF.ProjectView` | PMO, Executive (all projects) | the project's PM (own projects) |
| `EFF.ProjectEdit` | none | the project's PM (own projects) |
| `EFF.ProjectPmAssign` | PMO | – |
| `EFF.ActualView` (project-level Approved actual total) | PMO, Executive | the project's PM (own projects) |
| `EFF.ProjectApprove` | NOT_APPLICABLE (OD-26) | – |

Existing Timesheet capabilities are unchanged.

## 5. Preserved resolutions

- **OD-26 — NO_A_I_APPROVAL.** EPIC 16 A.I gets **no** Approve / Unapprove / Lock / Unlock; `EFF.ProjectApprove` stays NOT_APPLICABLE for every role.
- **OD-25 — separate.** `HourRegistrations` ≠ `ProjectEffortAllocations`: no shared field, key, link or seeding; M2 values are never linked to M1 values; M1 SharePoint fields are not reused merely because both use man-days.

## 6. Contract EPIC 17 needs from EPIC 16 (definition only)

- **Exposed fact:** one lifetime planned value per **project × recipient** (Quản lý phòng, PM, or a discipline), in man-days (≤ 2 dp, ≥ 0, no business maximum) with its blank / explicit-zero state.
- **Consumed by A.II:** the discipline recipients' values (A.I.3) as the ceiling reference.
- **Still open (M3):** ceiling scope (OD-15), ≤ vs = (OD-32), order (OD-27), behaviour on a blank allocation, concurrency counter, EPIC 17 unit (OD-45 — OD-14 is not propagated), EPIC 17 visibility (OD-46).

## 7. Data model (`ProjectEffortAllocations`, candidate)

- Key: `<ProjectLegacyId>|<RecipientKey>` with `RecipientKey` = `QLP` / `PM` / `D:<DisciplineLegacyId>`; no phase or period segment. SharePoint item ids are local helpers only.
- `Effort` in man-days (≤ 2 dp, more rejected; ≥ 0; no business maximum) with an explicit not-registered state distinct from 0.
- `Projects` gains the authoritative PM (stable employee key), written only by PMO through `EFF-SetProjectPm`.
- Not added: status/approval, cost, salary, rate, evaluation, phase, period, source reference, EPIC 17/18 fields, any `HourRegistrations` field or link, any actual-effort list.

## 8. Reporting boundary

Contract only: planned fact in man-days; actual effort = Σ Approved `TimesheetEntries` hours ÷ `HoursPerManDay`,
computed in the query, never stored back; reconciliation = Σ planned per project/recipient equals stored rows. Not in
scope: Power BI, EPIC 18 dashboards, evaluation, ranking, salary/cost analytics (OD-20, OD-21).

## 9. Follow-ups (no decision pending for M2)

- Backlog S16.3 acceptance "Employee records only own actual effort" must be re-baselined to the OD-19 outcome (existing
  timesheet, existing on-behalf semantics) at the next backlog re-baseline (task 0.5).
- Owner release of the M2 implementation gate (R3-G0 for M2); then tasks 2.1–2.5.
