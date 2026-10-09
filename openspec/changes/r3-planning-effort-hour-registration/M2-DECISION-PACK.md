# M2 decision pack — EPIC 16 Project Effort Registration (rev01 A.I and A.III)

Status 2026-10-10: **DECISION CLOSURE — NO IMPLEMENTATION.** M1 / S12.5 Hour Registration is DONE (legacy parity) and is
not reopened. **M2_IMPLEMENTATION_GATE = BLOCKED — READY_FOR_OWNER_DECISIONS.** Nothing below is approved: a
"recommendation" is evidence-based advice; an unanswered decision means **BLOCK / DO NOT GUESS**.
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
| Legacy data dictionary: project master E05, assignment E08 | E05 has **no PM / manager field**; E08 employee↔project assignment carries **no role**, has 7 rows, all for locked employees (unused) | LEGACY_FACT |
| Target data model / STAGING `Projects` | no PM / owner person field; `ProjectAssignments` mirrors E08; `ProjectAssignmentScoping` = Off | LEGACY_FACT / PROPOSED_DESIGN |
| Legacy reports and E14 | "Công đăng ký" (E14) and "Công thực hiện" (timesheet hours ÷ 8) are both man-days; the timesheet module is named "Chấm công" | LEGACY_FACT |
| R3 register §C | OD-25 = separate capability; OD-26 = no A.I approval; OD-21/38 = evaluation deferred | OWNER_DECISION / evidence |
| Live Timesheet (EPIC 06/07) | trusted actor vs business owner; authorised on-behalf entry; EPIC 07 approval (TL/APR/EXE) | TARGET_SECURITY_REQUIREMENT |

M1 decisions were used **only** as dependencies (OD-25 separation). No EPIC 16 semantics were derived from M1 by analogy.

## 2. Current M2 gate (derived, not copied)

Derived by the checker from the register's Blocking column after the M1 resolutions:
**OD-14, OD-16, OD-19, OD-22, OD-23, OD-24, OD-37, OD-40** (8) + **OD-41 conditional** (only if OD-19 = b/c).
OD-25 is no longer in the gate (resolved 2026-10-09 = separate). Reviewed: 8/8 blocking + 1/1 conditional.

**Resolved by evidence in this review: none.** Each M2 decision is a genuine business or security choice that the
source does not answer; strong evidence is recorded as a recommendation, not as a resolution.

New non-blocking finding: **OD-43** (A.I recipient set — the discipline master holds QL "Quản lý" next to the four
named disciplines). Default = source wording (QLP, PM, điện, lạnh, nước, BIM); does not block M2.

## 3. Summary

| ID | Question | Recommendation (NOT approved) | Decider | Blocks M2 |
|---|---|---|---|---|
| OD-14 | Unit of "công" | man-day (= `HoursPerManDay` h), ≤ 2 dp | CUSTOMER_REQUIRED (confirmation) | yes |
| OD-16 | Source of the A.I values | PM manual entry + optional reference; no import/formula yet | CUSTOMER_REQUIRED | yes |
| OD-19 | Actual effort source (A.III) | TimesheetEntries-derived | CUSTOMER_REQUIRED | yes |
| OD-22 | Phase dimension of A.I | per project × recipient, no phase | CUSTOMER_REQUIRED | yes |
| OD-23 | Period of A.I | project lifetime | CUSTOMER_REQUIRED | yes |
| OD-24 | Who is "the project's PM" | authoritative per-project PM maintained by PMO + server project scope | CUSTOMER_AND_SECURITY | yes |
| OD-37 | Who may view A.I | project PM (scoped), PMO, Executive; others DENY; TL line in M3; QLP in M4 | CUSTOMER_AND_SECURITY | yes |
| OD-40 | Blank vs 0 in A.I | blank = not registered, 0 = explicitly none | CUSTOMER_REQUIRED | yes |
| OD-41 | Actual-entry ownership if separate | NOT_APPLICABLE if OD-19 = a | conditional | only if OD-19 = b/c |

Recommended order of asking: **OD-24 → OD-19 → OD-14 → OD-22 → OD-23 → OD-16 → OD-40 → OD-37** (who and what
first; visibility last because it depends on the PM model).

## 4. Decision cards

### OD-14 — Unit of project effort ("công")
- **Business question:** in rev01, is "công" a man-day (and how many hours), an hour, or configurable? Precision?
- **Why it blocks M2:** the stored measure, validation, UI label and every later comparison (A.II ceiling, B registered vs actual) depend on it.
- **Exact evidence:** rev01 uses only "công" ("Công đăng ký", "Công thực hiện", "Số công") — CUSTOMER_REQUIREMENT. Legacy: "Công đăng ký" (E14) and "Công thực hiện" (timesheet hours ÷ `HoursPerManDay` = 8) are man-days, and rev01 B.II reuses exactly that pair ("công đăng ký và công thực hiện => so sánh") — LEGACY_FACT. The source does **not** define the unit — OPEN_DECISION.
- **OpenSpec state:** BLOCKING M2; spec stores "in the unit decided by OD-14" and exposes the source unit to the reporting contract.
- **Options:** a) man-day = `HoursPerManDay` hours; b) hours; c) configurable.
- **Recommendation:** **(a)**, precision ≤ 2 decimals, min 0. **Reason:** the company's established meaning of "công" in its own system and reports; one unit for A.I, A.II and actuals makes the ceiling and the comparison exact; storage unit stays separate from any later reporting normalisation.
- **Impact:** business — labels in "công"; data — `Effort` numeric (unit metadata in the contract); workflow — none; security — none; migration — none (new data); reporting — actuals normalised hours ÷ `HoursPerManDay`; EPIC 17 — A.II uses the same unit (ceiling comparable).
- **Decider:** CUSTOMER_REQUIRED — a yes/no confirmation (CEO + PMO). **Default if unanswered:** BLOCK.

### OD-16 — Source of the project-level planned effort (A.I.2)
- **Business question:** "Dữ liệu: từ bảng phân bổ sản lượng dự án" — is the PM typing the values (reading the allocation table), importing a file, or are the values derived from finance data?
- **Why it blocks M2:** decides the input path (screen vs import vs derived), the validation and the "values match the source" acceptance.
- **Exact evidence:** A.I.2 wording only — CUSTOMER_REQUIREMENT. The table's format, owner and location are not described anywhere; no screen, entity or report of that name appears in the legacy feature, screen, data-dictionary or report inventories — LEGACY_FACT (absence in the inventories). No formula is stated — OPEN_DECISION.
- **OpenSpec state:** BLOCKING M2; design §5.2 keeps `SourceRef`† conditional.
- **Options:** a) PM manual entry; b) Excel import; c) reference/derivation from finance data.
- **Recommendation:** **(a)** manual entry by the PM in R3 with an optional free-text reference to the allocation table; **no derivation formula**; import stays OD-36 (later). **Reason:** the only input that does not invent a format or formula; finance values are CONFIDENTIAL and would widen the security scope.
- **Impact:** business — PM transcribes; data — optional `SourceRef` text; workflow — save = effective (OD-26); security — no finance read; migration — none; reporting — planned effort is a user-entered fact; EPIC 17 — ceiling uses the entered value.
- **Decider:** CUSTOMER_REQUIRED (PMO + Finance). **Default if unanswered:** BLOCK.

### OD-19 — Actual effort source (A.III, NR-EFF-05)
- **Business question:** is "công thực hiện" the existing timesheet (TimesheetEntries), a separate per-project actual registration, or a hybrid?
- **Why it blocks M2:** EPIC 16 includes S16.3 (actual effort); decides whether a new list/screen exists, double entry, and how the A.III Chủ trì lock relates to the live EPIC 07 approval.
- **Exact evidence:** A.III.1 "Chấm công thực hiện dự án: nhân viên bộ môn (nhân viên và chủ trì)" — CUSTOMER_REQUIREMENT; "Chấm công" is the legacy timesheet module name and legacy "Công thực hiện" is computed from timesheet hours — LEGACY_FACT; A.III.2 "Người phê duyệt: Chủ trì => khóa công thực hiện" — CUSTOMER_REQUIREMENT. Whether this is the timesheet is not stated — OPEN_DECISION.
- **OpenSpec state:** BLOCKING M2 and M3; design §10 lists A/B/C without choosing.
- **Options:** a) derive from TimesheetEntries; b) separate list; c) hybrid snapshot.
- **Recommendation:** **(a)**. **Reason:** source wording + legacy meaning; no double entry; preserves the live actor vs business-owner and authorised on-behalf Timesheet semantics unchanged. The "Chủ trì lock" then relates to EPIC 07 approval — reconciled in M3 (OD-17, OD-33), not here.
- **Impact:** business — no new entry screen; data — none new for actuals; workflow — A.III approval = existing EPIC 07 approval (if OD-17 maps Chủ trì to TL) — M3; security — existing trusted owner/on-behalf rules unchanged; migration — none; reporting — actual = Σ timesheet hours ÷ `HoursPerManDay` per project (status filter OD-33, M3); EPIC 17 — A.III approval depends on OD-17.
- **Conditional:** IF (a) THEN **OD-41 = NOT_APPLICABLE**; IF (b) or (c) THEN **OD-41 becomes BLOCKING** for M2/M3.
- **Decider:** CUSTOMER_REQUIRED (CEO + PMO). **Default if unanswered:** BLOCK.

### OD-22 — Phase dimension of A.I
- **Business question:** is the PM's planned effort per project only, per phase, or both?
- **Why it blocks M2:** changes the business key and the grid shape.
- **Exact evidence:** A.I names no phase (verified absence) — CUSTOMER_REQUIREMENT; phases appear only in B.II.2 "Chi phí dự án: các giai đoạn và kết thúc dự án" (cost statistics) — CUSTOMER_REQUIREMENT; legacy E14 is per phase, but M1 semantics must not be inherited (OD-25) — LEGACY_FACT, not applicable.
- **OpenSpec state:** BLOCKING M2; `PhaseItemId`† conditional.
- **Options:** a) per project × recipient; b) per project × phase × recipient; c) both.
- **Recommendation:** **(a)**. **Reason:** exact A.I wording; phase cost (B.II.2) can come from actuals, which carry the phase in the timesheet.
- **Impact:** business — one figure per recipient; data — no phase column; workflow — none; security — none; migration — none; reporting — planned vs actual per phase not available unless (b); EPIC 17 — ceiling per project × discipline (OD-15 still decides the ceiling scope).
- **Decider:** CUSTOMER_REQUIRED (PMO + Finance). **Default if unanswered:** BLOCK.

### OD-23 — Period / time dimension of A.I
- **Business question:** is planned effort a project-lifetime figure, yearly, monthly, per pay period or revision-based; when is registration open?
- **Why it blocks M2:** the period is part of the key and the "open/closed" validation (`OUT_OF_PERIOD`).
- **Exact evidence:** no period in rev01 (verified absence) — CUSTOMER_REQUIREMENT; A.I is "cho dự án" and is the reference of the A.II ceiling; B.II.2 mentions "kết thúc dự án" (end of project) — CUSTOMER_REQUIREMENT. Lifetime is **not** assumed from M1.
- **OpenSpec state:** BLOCKING M2; `PeriodKey`† conditional.
- **Options:** lifetime; year; month; pay period (26→25); versioned revisions.
- **Recommendation:** **project lifetime**, changes kept by audit/version history (no revision entity). **Reason:** the only reading consistent with "cho dự án", the project-end comparison and a single ceiling reference.
- **Impact:** business — one total per recipient; data — no period column; workflow — always open while the project is listed (any project-status rule would be a new decision); security — none; migration — none; reporting — period breakdowns come from actuals; EPIC 17 — ceiling is a lifetime total unless OD-15 says otherwise.
- **Decider:** CUSTOMER_REQUIRED (PMO). **Default if unanswered:** BLOCK.

### OD-24 — Who is "the project's PM" / project scope
- **Business question:** A.I.1 "Người thực hiện: PM". Who is the PM of a given project, where is that kept, and does only that person register?
- **Why it blocks M2:** the backlog acceptance "only the project's PM can register; others denied server-side" cannot be enforced today; caller-supplied role or ownership is never trusted.
- **Exact evidence:** project master E05 has **no PM field**; E08 assignment has **no role** and is unused (7 rows, locked employees); target `Projects` has no PM field; the guard has no project scope — LEGACY_FACT. Legacy "PM" is a role (mapped to PMO), not a per-project person — LEGACY_FACT. Server-side scope from authoritative data only — TARGET_SECURITY_REQUIREMENT.
- **OpenSpec state:** BLOCKING M2; `EFF.ProjectEdit` OPEN_DECISION for PMO/TL/APR/EXE cells.
- **Options:** a) PMO role, company scope (any PMO edits any project); b) authoritative per-project PM (person) field/assignment maintained by PMO + guard project scope; c) both (b, with PMO override).
- **Recommendation:** **(b)**; (a) only as an explicitly approved, time-boxed interim. **Reason:** matches "the project's PM"; enforceable server-side from authoritative data; no invented mapping.
- **Impact:** business — PMO maintains a PM per project; data — new authoritative PM attribute (person key) on the project or assignment; workflow — PM change audited; security — new project scope in the guard (design + tests); migration — PM values must be supplied (no legacy source); reporting — "PM's projects" for B.II; EPIC 17 — none directly.
- **Decider:** CUSTOMER_AND_SECURITY (CEO + PMO; security owner for the scope model). **Default if unanswered:** BLOCK.

### OD-37 — Visibility of EPIC 16 data
- **Business question:** who may view project planned effort (A.I) and actual effort per project?
- **Why it blocks M2:** no `EFF.*` view capability is granted today; read flows cannot be built without it.
- **Exact evidence:** rev01 B lists who receives statistics (Nhân viên, Chủ trì, PM, Quản lý phòng) — CUSTOMER_REQUIREMENT; it does not grant raw view rights on A.I — OPEN_DECISION; M1 OD-05 (legacy Hour Registration view) is a different capability and is **not** inherited.
- **OpenSpec state:** BLOCKING M2; `EFF.ProjectView` / `EFF.ActualView` rows OPEN_DECISION.
- **Options:** per role / per scope.
- **Recommendation:** A.I view = the project's PM (OD-24 scope), PMO, Executive; Team Leader sees only the own-discipline line when EPIC 17 needs it (decided in M3); Quản lý phòng via OD-31 (M4); Employee, HR, Finance, Salary Viewer, App Administrator, Confidential Owner, Migration Owner **DENY**. Actual view follows OD-19 (if (a): existing Timesheet read rules). **Reason:** least privilege; only the actors rev01 names for A.I and its oversight.
- **Impact:** business — PM/PMO/Executive see allocations; data — none; workflow — none; security — new capability seed; migration — none; reporting — M4 roles later; EPIC 17 — TL visibility of the ceiling decided there.
- **Decider:** CUSTOMER_AND_SECURITY (CEO + PMO; security owner). **Default if unanswered:** BLOCK (deny all).

### OD-40 — Blank vs zero in A.I
- **Business question:** for a recipient row, does blank mean "not registered yet" and 0 "explicitly none", or are blank and 0 the same, or is a value required?
- **Why it blocks M2:** storage, API state, UI and the A.II ceiling behaviour ("no allocation yet" vs "zero allowed") differ.
- **Exact evidence:** rev01 is silent — OPEN_DECISION. OD-01 (M1) is a legacy-parity decision for another capability and is **not** copied (OD-25).
- **OpenSpec state:** BLOCKING M2; spec requirement "Allocation blank and zero" follows OD-40.
- **Options:** a) blank ≠ 0; b) blank = 0; c) value required (no blank).
- **Recommendation:** **(a)**: blank = not registered, 0 = explicitly none. **Reason:** keeps "not yet planned" distinguishable from "planned as zero", which the A.II ceiling and the PM's completeness view need.
- **Impact:** business — PM can leave a recipient unplanned; data — nullable `Effort` with explicit state; workflow — none; security — none; migration — none; reporting — blank sums as 0, counts exclude blank; EPIC 17 — behaviour of a ceiling on a blank allocation decided in M3 (OD-15/32).
- **Decider:** CUSTOMER_REQUIRED (PMO). **Default if unanswered:** BLOCK.

### OD-41 — Actual-entry ownership (conditional)
- Applies only if OD-19 = b or c. IF OD-19 = a: **NOT_APPLICABLE** — existing Timesheet actor/business-owner and authorised on-behalf rules stay unchanged and must not be narrowed. IF b/c: BLOCKING M2/M3 — options own only / authorised on-behalf by the existing scope model / project-discipline rule; recommendation then: the existing on-behalf scope model (consistency with the live Timesheet). Decider CEO + PMO (+ security).

## 5. Preserved resolutions

- **OD-26 — NO_A_I_APPROVAL (preserved).** Re-reading confirms A.I.1–3 state no approver or lock; approval/lock appear only in A.II.3 and A.III.2. EPIC 16 A.I gets **no** Approve / Unapprove / Lock / Unlock; `EFF.ProjectApprove` stays NOT_APPLICABLE for every role.
- **OD-25 — separate (preserved).** `HourRegistrations` is not part of the EPIC 16 model: no shared field, key, link or seeding (stale "link/seed" wording removed from design and spec in this review).

## 6. Contract EPIC 17 needs from EPIC 16 (definition only)

- **Exposed fact:** planned project effort per **project × recipient** (recipient = Quản lý phòng, PM, or a discipline), value in the OD-14 unit with its OD-40 state; phase/period keys only if OD-22/OD-23 add them.
- **Consumed by A.II:** the discipline recipients' values (A.I.3) as the reference of the ceiling.
- **Still open (M3):** ceiling scope (OD-15), ≤ vs = (OD-32), order A.I-final-before-A.II (OD-27), behaviour on a blank allocation, concurrency counter.
- **Stable enough now:** the recipient categories (source wording), the separation from `HourRegistrations`, no A.I approval state.

## 7. Data model review (`ProjectEffortAllocations`, candidate)

- Minimum dimensions settled by the source: **Project + RecipientCategory (QLP / PM / Discipline) + Discipline (for the discipline category)** + `Effort`.
- Conditional only: `PhaseLegacyId` (OD-22), `PeriodKey` (OD-23), `SourceRef` (OD-16); unit and blank/zero are attributes of `Effort` per OD-14/OD-40.
- Stable business key (environment independent): `<ProjectLegacyId>|<RecipientKey>` with `RecipientKey` = `QLP` / `PM` / `D:<DisciplineLegacyId>` (+ phase/period segments only if decided). SharePoint item ids are local helpers, never the canonical identity.
- Not added (no M2 need): status/approval, cost, salary, rate, evaluation, EPIC 17/18 fields, any `HourRegistrations` field or link.
- The entity name is a candidate; it is confirmed only when the M2 gate is released.

## 8. Reporting boundary

Allowed now (contract only): planned-effort fact in its source unit; actual effort per OD-19; explicit normalisation
(hours ÷ `HoursPerManDay`) kept separate from storage; reconciliation = Σ planned per project/recipient equals stored
rows. Not in scope: Power BI, EPIC 18 dashboards, evaluation, ranking, salary/cost analytics (OD-20, OD-21).

## 9. Customer question minimisation

Answered from the source and not asked: who registers A.I (PM — the identity question is OD-24 only), recipients
(QLP, PM, four named disciplines), A.I approval (none, OD-26), what "mục I.3" points to (A.I.3), separation from legacy
Hour Registration (OD-25). Remaining questions are genuine choices the source does not answer.

## 10. Follow-ups (documentation only, no decision)

- Backlog S16.3 acceptance "Employee records only own actual effort" must be made conditional on OD-19/OD-41 at the next
  backlog re-baseline (task 0.5); it must not narrow the live Timesheet on-behalf semantics.
- After answers: record each in `decisions.md` §C (decision, answer, source, class, affected requirements, milestone),
  then re-run the checker; the M2 gate turns empty only when all eight are answered (and OD-41 if OD-19 = b/c).
