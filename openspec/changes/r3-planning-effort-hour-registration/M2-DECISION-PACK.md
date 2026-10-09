# M2 decision pack — EPIC 16 Project Effort Registration (rev01 A.I and A.III)

Status 2026-10-10: **DECISION CLOSURE — NO IMPLEMENTATION.** M1 / S12.5 Hour Registration is DONE (legacy parity) and is
not reopened. Owner decisions recorded 2026-10-10: **OD-14 = MAN_DAY**, **OD-19 = TIMESHEETENTRIES**,
**OD-40 = BLANK_NOT_REGISTERED / ZERO_EXPLICIT** (RESOLVED_OWNER_DECISION); **OD-41 = NOT_APPLICABLE**.
**M2_IMPLEMENTATION_GATE = BLOCKED** on five external decisions. A "recommendation" below is evidence-based advice, not
an approval; an unanswered decision means **BLOCK / DO NOT GUESS**.
Vietnamese meeting summary: `M2-DECISION-SUMMARY.md`. Register: `decisions.md`. Checker: `tools/spec/check_r3_open_spec.py`.

Evidence classes: **LEGACY_FACT** · **CUSTOMER_REQUIREMENT** · **OWNER_DECISION** · **TARGET_SECURITY_REQUIREMENT** ·
**PROPOSED_DESIGN** · **OPEN_DECISION**.

## 1. Sources re-read for this review

| Source | What it settles | Class |
|---|---|---|
| Customer document "Đăng ký công – rev01" (28 lines; re-extracted from the original file including its list numbering) | Structure **A** "Đăng ký công": **A.I** "Đăng ký công cho dự án" (1. "Người thực hiện: PM"; 2. "Dữ liệu: từ bảng phân bổ sản lượng dự án"; 3. "Công đăng ký: cho Quản lý phòng, PM, bộ môn (điện, lạnh, nước và BIM)"), **A.II** discipline registration (ceiling "không vượt quá số công mục I.3"; Chủ trì approves → lock), **A.III** "Công thực hiện dự án" (1. "Chấm công thực hiện dự án: nhân viên bộ môn (nhân viên và chủ trì)"; 2. Chủ trì approves → lock); **B** statistics. No table, no comment, no other text | CUSTOMER_REQUIREMENT |
| Same document, numbering | "mục I.3" = **A.I.3** (upper-Roman sections, decimal items) — structural fact; what the ceiling means stays OD-15 (M3) | CUSTOMER_REQUIREMENT (structure) |
| Same document | **A.I names no approver, no lock, no phase, no period, no unit other than the word "công"** (verified absence) | CUSTOMER_REQUIREMENT (absence) |
| Customer decision pack §F (EFF-F-1..10) | All answers blank — no customer decision recorded | OPEN_DECISION |
| Owner decisions 2026-10-10 (task R3-M2-EPIC16-APPLY-OWNER-DECISIONS) | OD-14, OD-19, OD-40 decided; OD-41 not applicable | OWNER_DECISION |
| Legacy data dictionary: project master E05, assignment E08 | E05 has **no PM / manager field**; E08 employee↔project assignment carries **no role**, has 7 rows, all for locked employees (unused) | LEGACY_FACT |
| Target data model / STAGING `Projects` | no PM / owner person field; `ProjectAssignments` mirrors E08; `ProjectAssignmentScoping` = Off | LEGACY_FACT / PROPOSED_DESIGN |
| Legacy reports and E14 | "Công đăng ký" (E14) and "Công thực hiện" (timesheet hours ÷ 8) are both man-days; the timesheet module is named "Chấm công" | LEGACY_FACT |
| R3 register §C | OD-25 = separate capability; OD-26 = no A.I approval; OD-21/38 = evaluation deferred | OWNER_DECISION / evidence |
| Live Timesheet (EPIC 06/07) | trusted actor vs business owner; authorised on-behalf entry; EPIC 07 approval (TL/APR/EXE) | TARGET_SECURITY_REQUIREMENT |

M1 decisions were used **only** as dependencies (OD-25 separation). No EPIC 16 semantics were derived from M1 by analogy.

## 2. Current M2 gate (derived, not copied)

Derived by the checker from the register's Blocking column after the owner decisions of 2026-10-10:
**OD-16, OD-22, OD-23, OD-24, OD-37** (5); no conditional blocker (OD-41 NOT_APPLICABLE).

| Class | Decisions |
|---|---|
| CUSTOMER_REQUIRED | OD-16, OD-22, OD-23 |
| CUSTOMER_AND_SECURITY_REQUIRED | OD-24, OD-37 |

## 3. Owner decisions applied 2026-10-10 (not reopened)

| ID | Decision | Effect on EPIC 16 |
|---|---|---|
| OD-14 | **MAN_DAY** — RESOLVED_OWNER_DECISION | Project Effort business/storage unit = man-day; ≤ 2 decimals; conversion from Timesheet hours via the approved `HoursPerManDay`; own schema (no `HourRegistrations` storage/schema inherited); later reporting normalises explicitly; no EPIC 18 authorisation |
| OD-19 | **TIMESHEETENTRIES** — RESOLVED_OWNER_DECISION | Actual effort derived from existing `TimesheetEntries`; no new actual-effort list, duplicate workflow or employee entry screen; existing Timesheet actor identity, business owner / Employee relationship, authorised on-behalf editing, entry status semantics and security model preserved; nothing in the live Timesheet is restricted; actual man-days = approved Timesheet hours ÷ `HoursPerManDay` per the reporting/query contract (status set OD-33, M3) |
| OD-40 | **BLANK_NOT_REGISTERED / ZERO_EXPLICIT** — RESOLVED_OWNER_DECISION | Blank and 0 are distinct business states; blank never coerced to 0; storage designed in the EPIC 16 schema, not inferred from M1 (not an inheritance of OD-01) |
| OD-41 | **NOT_APPLICABLE** (consequence of OD-19) | No new actual-entry ownership rule; existing Timesheet rules apply unchanged |

Previous evidence and recommendations for these decisions are kept in the register as rationale only.

## 4. Remaining decisions — summary

| ID | Question | Recommendation (NOT approved) | Decider | Blocks M2 |
|---|---|---|---|---|
| OD-16 | Source of the A.I values | PM manually enters the planned Project Effort; no formula/import unless explicitly requested | CUSTOMER_REQUIRED | yes |
| OD-22 | Phase dimension of A.I | project × recipient, **no** phase dimension | CUSTOMER_REQUIRED | yes |
| OD-23 | Period of A.I | project-lifetime value with change history/audit | CUSTOMER_REQUIRED | yes |
| OD-24 | Who is "the project's PM" | one authoritative PM per project, maintained by PMO, validated server-side | CUSTOMER_AND_SECURITY_REQUIRED | yes |
| OD-37 | Who may view A.I | project's PM, PMO, Executive; not inherited from M1 OD-05; TL / QLP in later decisions | CUSTOMER_AND_SECURITY_REQUIRED | yes |

Recommended order of asking: **OD-24 → OD-22 → OD-23 → OD-16 → OD-37** (who and what first; visibility last because it
depends on the PM model).

## 5. Decision cards (remaining)

### OD-16 — Source of the project-level planned effort (A.I.2)
- **Business question:** "Dữ liệu: từ bảng phân bổ sản lượng dự án" — is the PM typing the values (reading the allocation table), importing a file, or are the values derived from finance data?
- **Why it blocks M2:** decides the input path (screen vs import vs derived), the validation and the "values match the source" acceptance.
- **Exact evidence:** A.I.2 wording only — CUSTOMER_REQUIREMENT. The table's format, owner and location are not described anywhere; no screen, entity or report of that name appears in the legacy feature, screen, data-dictionary or report inventories — LEGACY_FACT (absence in the inventories). No formula is stated — OPEN_DECISION.
- **OpenSpec state:** BLOCKING M2; design §5.2 keeps `SourceRef`† conditional.
- **Options:** a) PM manual entry; b) Excel import; c) reference/derivation from finance data.
- **Recommendation:** **(a)** the PM manually enters the planned Project Effort, with an optional free-text reference to the allocation table; **no formula and no import** unless explicitly requested (import = OD-36, later). **Reason:** the only input that does not invent a format or formula; finance values are CONFIDENTIAL and would widen the security scope.
- **Impact:** business — PM transcribes; data — optional `SourceRef` text; workflow — save = effective (OD-26); security — no finance read; migration — none; reporting — planned effort is a user-entered fact; EPIC 17 — ceiling uses the entered value.
- **Decider:** CUSTOMER_REQUIRED (PMO + Finance). **Default if unanswered:** BLOCK.

### OD-22 — Phase dimension of A.I
- **Business question:** is the PM's planned effort per project only, per phase, or both?
- **Why it blocks M2:** changes the business key and the grid shape.
- **Exact evidence:** A.I names no phase (verified absence) — CUSTOMER_REQUIREMENT; phases appear only in B.II.2 "Chi phí dự án: các giai đoạn và kết thúc dự án" (cost statistics) — CUSTOMER_REQUIREMENT; legacy E14 is per phase, but M1 semantics must not be inherited (OD-25) — LEGACY_FACT, not applicable.
- **OpenSpec state:** BLOCKING M2; `PhaseItemId`† conditional.
- **Options:** a) per project × recipient; b) per project × phase × recipient; c) both.
- **Recommendation:** **(a)**. **Reason:** exact A.I wording; phase cost (B.II.2) can come from actuals, which carry the phase in the timesheet.
- **Impact:** business — one figure per recipient; data — no phase column; workflow — none; security — none; migration — none; reporting — planned vs actual per phase not available unless (b) (actuals keep their timesheet phase); EPIC 17 — ceiling per project × discipline (OD-15 still decides the ceiling scope).
- **Decider:** CUSTOMER_REQUIRED (PMO + Finance). **Default if unanswered:** BLOCK.

### OD-23 — Period / time dimension of A.I
- **Business question:** is planned effort a project-lifetime figure, yearly, monthly, per pay period or revision-based; when is registration open?
- **Why it blocks M2:** the period is part of the key and the "open/closed" validation (`OUT_OF_PERIOD`).
- **Exact evidence:** no period in rev01 (verified absence) — CUSTOMER_REQUIREMENT; A.I is "cho dự án" and is the reference of the A.II ceiling; B.II.2 mentions "kết thúc dự án" (end of project) — CUSTOMER_REQUIREMENT. Lifetime is **not** assumed from M1.
- **OpenSpec state:** BLOCKING M2; `PeriodKey`† conditional.
- **Options:** lifetime; year; month; pay period (26→25); versioned revisions.
- **Recommendation:** **project-lifetime value with change history/audit** (no revision entity). **Reason:** the only reading consistent with "cho dự án", the project-end comparison and a single ceiling reference.
- **Impact:** business — one total per recipient; data — no period column; workflow — always open while the project is listed (any project-status rule would be a new decision); security — none; migration — none; reporting — period breakdowns come from actuals; EPIC 17 — ceiling is a lifetime total unless OD-15 says otherwise.
- **Decider:** CUSTOMER_REQUIRED (PMO). **Default if unanswered:** BLOCK.

### OD-24 — Who is "the project's PM" / project scope
- **Business question:** A.I.1 "Người thực hiện: PM". Who is the PM of a given project, where is that kept, and does only that person register?
- **Why it blocks M2:** the backlog acceptance "only the project's PM can register; others denied server-side" cannot be enforced today; caller-supplied role or ownership is never trusted.
- **Exact evidence:** project master E05 has **no PM field**; E08 assignment has **no role** and is unused (7 rows, locked employees); target `Projects` has no PM field; the guard has no project scope — LEGACY_FACT. Legacy "PM" is a role (mapped to PMO), not a per-project person — LEGACY_FACT. Server-side scope from authoritative data only — TARGET_SECURITY_REQUIREMENT.
- **OpenSpec state:** BLOCKING M2; `EFF.ProjectEdit` OPEN_DECISION for PMO/TL/APR/EXE cells.
- **Options:** a) PMO role, company scope (any PMO edits any project); b) authoritative per-project PM (person) field/assignment maintained by PMO + guard project scope; c) both (b, with PMO override).
- **Recommendation:** **(b)** one authoritative PM per project, maintained by PMO, validated server-side; (a) only as an explicitly approved, time-boxed interim. Requires business **and** security confirmation because the current project data has no authoritative PM field. **Reason:** matches "the project's PM"; enforceable server-side from authoritative data; no invented mapping.
- **Impact:** business — PMO maintains a PM per project; data — new authoritative PM attribute (person key) on the project or assignment; workflow — PM change audited; security — new project scope in the guard (design + tests); migration — PM values must be supplied (no legacy source); reporting — "PM's projects" for B.II; EPIC 17 — none directly.
- **Decider:** CUSTOMER_AND_SECURITY_REQUIRED (CEO + PMO; security owner for the scope model). **Default if unanswered:** BLOCK.

### OD-37 — Visibility of EPIC 16 data
- **Business question:** who may view project planned effort (A.I) and actual effort per project?
- **Why it blocks M2:** no `EFF.*` view capability is granted today; read flows cannot be built without it.
- **Exact evidence:** rev01 B lists who receives statistics (Nhân viên, Chủ trì, PM, Quản lý phòng) — CUSTOMER_REQUIREMENT; it does not grant raw view rights on A.I — OPEN_DECISION; M1 OD-05 (legacy Hour Registration view) is a different capability and is **not** inherited.
- **OpenSpec state:** BLOCKING M2; `EFF.ProjectView` / `EFF.ActualView` rows OPEN_DECISION.
- **Options:** per role / per scope.
- **Recommendation:** VIEW = the project's PM (OD-24 scope), PMO, Executive; Employee, HR, Finance, Salary Viewer, App Administrator, Confidential Owner, Migration Owner **DENY**. M1 OD-05 visibility is **not** inherited. Team Leader / Quản lý phòng visibility belongs to later decisions where applicable (EPIC 17 / M3; OD-31 / M4). Actual effort stays readable through the existing Timesheet read rules (OD-19 resolved); a new project-level actual view needs this decision. **Reason:** least privilege; only the actors rev01 names for A.I and its oversight.
- **Impact:** business — PM/PMO/Executive see allocations; data — none; workflow — none; security — new capability seed; migration — none; reporting — M4 roles later; EPIC 17 — TL visibility of the ceiling decided there.
- **Decider:** CUSTOMER_AND_SECURITY_REQUIRED (CEO + PMO; security owner). **Default if unanswered:** BLOCK (deny all).

## 6. Preserved resolutions

- **OD-26 — NO_A_I_APPROVAL (preserved).** A.I.1–3 state no approver or lock; approval/lock appear only in A.II.3 and A.III.2. EPIC 16 A.I gets **no** Approve / Unapprove / Lock / Unlock; `EFF.ProjectApprove` stays NOT_APPLICABLE for every role.
- **OD-25 — separate (preserved).** `HourRegistrations` ≠ `ProjectEffortAllocations`: no shared field, key, link or seeding; M2 values are never linked to M1 values; M1 SharePoint fields are not reused merely because both use man-days.

## 7. Contract EPIC 17 needs from EPIC 16 (definition only)

- **Exposed fact:** planned project effort per **project × recipient** (recipient = Quản lý phòng, PM, or a discipline), value in **man-days** (≤ 2 dp) with its blank / explicit-zero state; phase/period keys only if OD-22/OD-23 add them.
- **Consumed by A.II:** the discipline recipients' values (A.I.3) as the reference of the ceiling.
- **Still open (M3):** ceiling scope (OD-15), ≤ vs = (OD-32), order A.I-final-before-A.II (OD-27), behaviour of a ceiling on a blank allocation, concurrency counter, EPIC 17 storage unit design.
- **Stable now:** recipient categories (source wording), man-day unit, blank ≠ 0, separation from `HourRegistrations`, no A.I approval state, actual effort from the existing timesheet.

## 8. Data model review (`ProjectEffortAllocations`, candidate)

- Settled dimensions: **Project + RecipientCategory (QLP / PM / Discipline) + Discipline (for the discipline category)** + `Effort` in man-days (≤ 2 dp) with an explicit not-registered state distinct from 0 (representation designed in this schema).
- Conditional only: `PhaseLegacyId` (OD-22), `PeriodKey` (OD-23), `SourceRef` (OD-16).
- Stable business key (environment independent): `<ProjectLegacyId>|<RecipientKey>` with `RecipientKey` = `QLP` / `PM` / `D:<DisciplineLegacyId>` (+ phase/period segments only if decided). SharePoint item ids are local helpers, never the canonical identity.
- Not added: status/approval, cost, salary, rate, evaluation, EPIC 17/18 fields, any `HourRegistrations` field or link, any actual-effort list (OD-19).
- The entity name is a candidate; it is confirmed only when the M2 gate is released.

## 9. Reporting boundary

Allowed now (contract only): planned-effort fact in man-days; actual effort from `TimesheetEntries` hours converted in
the query (hours ÷ `HoursPerManDay`), never stored back; reconciliation = Σ planned per project/recipient equals stored
rows. Not in scope: Power BI, EPIC 18 dashboards, evaluation, ranking, salary/cost analytics (OD-20, OD-21).

## 10. Customer question minimisation

Not asked: who registers A.I (PM — the identity question is OD-24 only), recipients (QLP, PM, four named disciplines),
A.I approval (none, OD-26), what "mục I.3" points to (A.I.3), separation from legacy Hour Registration (OD-25), unit
(OD-14), actual source (OD-19), blank vs 0 (OD-40), actual-entry ownership (OD-41, not applicable). Remaining questions
are genuine business or security choices the source does not answer.

## 11. Follow-ups (documentation only, no decision)

- Backlog S16.3 acceptance "Employee records only own actual effort" must be re-baselined to the OD-19 outcome (existing
  timesheet, existing on-behalf semantics) at the next backlog re-baseline (task 0.5); it must not narrow the live
  Timesheet.
- After answers: record each in `decisions.md` §C (decision, answer, source, class, affected requirements, milestone),
  then re-run the checker; the M2 gate turns empty only when OD-16, OD-22, OD-23, OD-24 and OD-37 are answered.
