# R3 decision register (OPEN_DECISION items)

Status 2026-10-09: rows in sections A/B are **OPEN_DECISION** unless explicitly marked otherwise. Owner accepted OD-01, OD-02, OD-04, OD-09 = A on 2026-10-09 (moved to §C). A "recommended default" is evidence-based advice for the reviewer; it is **not approved** and nothing may be implemented on it before the decision owner records an answer (date, owner, source).

Resolved scope/source decisions discovered during review are moved to section C and are not counted as open blockers.

Milestones: **M1** = S12.5 Hour Registration build start; **M2** = EPIC 16 build start; **M3** = EPIC 17 build start;
**M4** = EPIC 18 reporting build start (later release); **GL** = go-live / data migration.
**BLOCKING** = the milestone cannot start without the answer (a guess would change schema, security or tests).

Existing effort decisions F-1..F-10 (customer decision pack, added 2026-10-06) are carried here as **EFF-F-n** (the plain ids F-1/F-2 collide with unrelated EPIC 03 findings; OD-39). EFF-F-8 is resolved by evidence (current-scope deferral, OD-21) in §C; the remaining effort decisions stay open until explicitly answered.

Evidence ids: **LHR-nn** = legacy Hour Registration parity rows (`traceability.md` §2); **NR-EFF-nn** = new
requirement rows (`traceability.md` §1). Legacy facts are from the decompiled legacy source and the legacy data profile.

## A. S12.5 Hour Registration (legacy budget matrix)

| ID | Question | Why it matters | Options | Recommended default (NOT approved) | Risk if wrong | Affects | Blocking | Owner |
|---|---|---|---|---|---|---|---|---|
| OD-05 | Who may view the matrix; data classification | Legacy VERIFIED (permission data, module TS.Đăng ký công): Write = CEO, Secretary, PM; Read = Manager, Leader, **IT**, HRD; Hide = Member, AD. The legacy→target role map (Manager→Approver, Leader→Team Leader, HRD→HR, CEO→Executive/Approver, Secretary/PM→PMO, IT→split: IT Support technical part (candidate for IT's read access), App Administrator, HR, Salary Viewer) is **prepared, not signed**; the `REG.View` seed (incl. AppAdmin) is unapproved; classification conflicts (legacy INTERNAL vs a target note "Confidential (budget)") | a) view TL, APR, EXE, PMO, HR; deny AppAdmin and IT Support; INTERNAL; a2) a) + IT Support view (legacy IT read kept); b) + AppAdmin; c) classify confidential (ENV-D2) | (a) — denying IT Support is a deliberate TARGET SECURITY HARDENING / DEVIATION from legacy IT read access and needs approval here; not resolved by evidence | Leak of budget data or blocked readers | guard, read flow, site placement | **BLOCKING M1** — CUSTOMER_OR_SECURITY_OWNER_REQUIRED | Security owner (project owner) + HR; customer if the role map or the IT deviation is contested |
| OD-06 | Project list scoping by assignment | Legacy scopes by the person loaded elsewhere and in practice shows all projects (LHR-07); target switch `ProjectAssignmentScoping` = Off (engineering interim, B-03 open) | a) follow the existing switch; b) always all; c) always assigned | (a) | Wrong visibility | read flow filter | NON_BLOCKING (switch exists) | Project owner |
| OD-07 | Are inactive / closed projects listed and editable? | Legacy filter was a UI flag, effectively all projects listed and editable (LHR-09) | a) all listed, editable (legacy); b) active editable, others read-only; c) active only | (a) legacy semantics | Edits to closed budgets or hidden history | read/save validation | **BLOCKING M1** — CUSTOMER | PMO |
| OD-08 | Values on a phase removed from the project or an inactive discipline | Legacy hides stale lines and silently drops them on the next save, while one report still sums them (LHR-13/14) | a) keep, show read-only and flagged, excluded from editing; b) keep hidden; c) remove | (a) never delete silently | Silent data loss or inconsistent totals | read model, reports, migration (1 stale line) | **BLOCKING M1** | PMO |
| OD-42 | Value bounds for registered man-days (minimum, maximum) — split from OD-03 | Legacy has **no** bounds (free text; a negative number parses; no maximum); data holds 2–200 only; 9,999 / 999.9 were only proposed target constraints | a) minimum 0, no business maximum (technical column limit only); b) minimum 0 + owner-set maximum; c) other | none approved (proposal: a) | Rejecting legitimate large budgets or accepting garbage/negative values | validation, tests | **BLOCKING M1** — OWNER_INTERNAL | Project owner + PMO |
| OD-10 | Multi-cell clear / spreadsheet paste (UD-06) | Legacy Delete/Backspace clears all selected cells (LHR-17); nested galleries edit one cell at a time | a) single-cell clear + "clear row" action; b) Excel-like grid (SPFx, new tech) | (a) | Productivity gap | UI only | NON_BLOCKING | PMO |
| OD-11 | Migrate legacy E14 values (199 filled cells, Σ 8,648 man-days; orphan file 9 blank lines) in R3? | Needed for reports to match legacy | a) migrate with the R3 release; b) with the historical migration epic; c) not at all | (a) or (b); orphan file excluded (0 values lost) | Empty budgets at go-live | migration plan | NON_BLOCKING for M1, **BLOCKING GL** | PMO + project owner |
| OD-12 | Per-year budget? | Legacy registration is lifetime per project; the year only filters the project list (LHR-23) | a) lifetime (legacy); b) per year | (a) | Semantics change | schema | NON_BLOCKING (default = legacy) | PMO |
| OD-13 | Show budget where a phase/project has no actuals in the period (legacy omits it, LHR-33) | Reporting presentation | a) show; b) legacy | (a) | Understated totals | reporting contract | NON_BLOCKING (decided before later reporting, M4) | PMO |

## B. Shared R3 / EPIC 16 / EPIC 17

| ID | Question | Why it matters | Options | Recommended default (NOT approved) | Risk if wrong | Affects | Blocking | Owner |
|---|---|---|---|---|---|---|---|---|
| OD-14 | **EFF-F-1** Unit of "công" for rev01; precision | Comparison of registered vs actual needs one unit; timesheet uses 8 h = 1 công (`HoursPerManDay`) | a) man-day = `HoursPerManDay` hours; b) hours; c) configurable | none (customer) | Wrong totals, ceilings | all EFF schemas, reports | **BLOCKING M2** | CEO + PMO |
| OD-15 | **EFF-F-2** Ceiling scope of "mục I.3" (A.I.3) | The discipline total must not exceed it (NR-EFF-03); per project? project × discipline? phase? period? | per project; project × discipline; + phase; + period | none | Wrong validation | EFF-SaveDisciplineEffort, tests | **BLOCKING M3** | PMO |
| OD-16 | **EFF-F-3** Source and format of the project output allocation table ("bảng phân bổ sản lượng dự án") | NR-EFF-01 input; import vs manual | manual entry; Excel import; reference to finance data | none | Wrong input path | project-effort, import | **BLOCKING M2** | PMO + Finance |
| OD-17 | **EFF-F-4** Who is "Chủ trì"? Role (Team Leader, labelled "Chủ trì bộ môn" in legacy) or per-project/discipline assignment? | Approver of NR-EFF-04/06; scope model | a) Team Leader of the discipline; b) per-project assignment list; c) new role | none (evidence suggests (a), not decided) | Wrong approver authority | security, schema, guard scope | **BLOCKING M3** | CEO + HR |
| OD-18 | **EFF-F-5** Unlock / reopen after Chủ trì approval: allowed? by whom? audited? | "khóa" = lock; `Unlock` audit event is disabled until decided | a) never; b) Chủ trì; c) higher role; d) request + approve | none | Locked errors or uncontrolled edits | state machine, audit | **BLOCKING M3** | CEO |
| OD-19 | **EFF-F-6** Actual effort ("công thực hiện") = existing timesheet entries or a separate per-project registration? | Decides data model, approval overlap with EPIC 07, NR-EFF-05/06 | a) derive from TimesheetEntries; b) separate list; c) hybrid | none (wording "chấm công" suggests (a); not decided) | Duplicate entry or conflicting approvals | `design.md` §10 | **BLOCKING M2, M3** | CEO + PMO |
| OD-20 | **EFF-F-7** Salary-cost visibility per role (with S-01, ENV-D2) | NR-EFF-07/08/11/12/14 cost parts | per role options | none | Confidential leak | reporting contract only | NON_BLOCKING for M2/M3 (cost excluded); **BLOCKING M4** | CEO + HR |
| OD-22 | **EFF-F-9** Phase rules (which phases; closing; effect on registration) | A.I has no phase; legacy registration is per phase | per phase or not | none | Wrong granularity | schema | **BLOCKING M2** | PMO + Finance |
| OD-23 | **EFF-F-10** Registration period and open/close (project lifetime, month, week) | Time dimension of plans and actuals | lifetime; month; pay period (26→25) | none | Wrong schema | schema, reports | **BLOCKING M2** | PMO |
| OD-24 | Who is "the project's PM"? (PM is a legacy role; no project-manager field or assignment role exists; the guard has no project scope) | S16.2 AC "only the project's PM can register" cannot be enforced today | a) PMO role, company scope; b) per-project PM field/assignment + new project scope | none | Any PMO edits any project, or no one can | security, schema (Projects / ProjectAssignments), guard | **BLOCKING M2** | CEO + PMO |
| OD-25 | Relationship of legacy E14 / S12.5 to rev01 A.I (PM project effort) | Same name, actor and discipline columns; rev01 is classified as a new requirement; nothing decides whether A.I replaces, extends or is seeded from E14 | a) separate (S12.5 = legacy budget; A.I new); b) A.I replaces S12.5; c) A.I extends E14 (same entity) | none — the spec keeps them separate until decided | Building S12.5 twice or migrating into the wrong entity | M1 scope, schema, migration | **BLOCKING M1, M2** | CEO + PMO |
| OD-27 | Approval order (A.I final before A.II? registration approved before actuals?) | Ceiling depends on A.I values | sequential; independent | none | Ceiling against a moving number | state machine, validation | **BLOCKING M3** | PMO |
| OD-28 | Self-approval for effort (Chủ trì registers and approves own discipline) | UD-04 (blocked) covers timesheet entries only | a) deny own rows; b) allow; c) deny own person rows only | none (timesheet precedent: deny) | Segregation-of-duties gap or deadlock | guard | **BLOCKING M3** | CEO |
| OD-29 | Meaning of "Chọn công việc thực hiện" in A.II: phase or work type? | Granularity of discipline registration | phase; work type; free text | none | Wrong schema | schema, UI | **BLOCKING M3** | PMO |
| OD-30 | Discipline registration per person or per discipline aggregate | "nhân viên bộ môn (nhân viên và chủ trì)" register | per person; per discipline | none | Wrong ownership model | schema, security | **BLOCKING M3** | PMO |
| OD-31 | Role mapping of "Quản lý phòng" for B.III visibility / analytics | A.I can store `QuanLyPhong` as a recipient category without binding it to a security role; B.III still needs a target-role/person mapping | Approver (legacy Manager); position-based; new role | none | Wrong report visibility | reporting / later analytics; **does not block A.I storage** | NON_BLOCKING for M2; **BLOCKING M4** | CEO + HR |
| OD-32 | Must discipline allocations sum to the project total, or only not exceed it? | "không vượt quá" implies ≤ (lower allowed) — not stated for equality | ≤ only; = required at approval | ≤ only (from wording; not approved) | Rejecting valid plans | validation | **BLOCKING M3** | PMO |
| OD-33 | If actuals come from timesheets: count Approved only, or Draft too? | Legacy reports count unapproved hours; rev01 requires Chủ trì lock of actuals | approved only; all; both shown | none | Wrong actuals | reporting contract, M3 | **BLOCKING M3** | CEO + PMO |
| OD-34 | Revision / version model after approval (history of approved plans) | Legacy keeps no history | none (audit only); versioned plans | audit-only history | Lost baseline | schema | **BLOCKING M3** | PMO |
| OD-35 | Historical structure changes (discipline/phase changes, people moving) | RD-05 proposes discipline snapshot | snapshot at write; current | snapshot column + current lookup | Misattributed effort | schema, reports | NON_BLOCKING | PMO |
| OD-36 | Import / export (Excel) for registrations (R-03) | Bulk entry and offline review | none; export only; import + export | export only in R3 | Manual effort | UX | NON_BLOCKING (except OD-16) | PMO |
| OD-37 | Visibility of effort data per role (who sees which project's / discipline's plans and actuals) | No capability exists today | per role | none | Leak or blocked users | read flows | **BLOCKING M2** | CEO + PMO |
| OD-39 | Rename effort decisions F-1..F-10 to EFF-F-1..10 in the decision pack | Id collision with EPIC 03 findings | rename | rename | Confusion | docs | NON_BLOCKING | Project owner |
| OD-40 | EPIC 16 allocation blank/zero semantics | Legacy S12.5 `BLANK ≠ 0` is a separate concept and cannot be inherited into rev01 without evidence | a) blank distinct from 0; b) blank coerced to 0; c) value required/no blank | none | Wrong storage/API semantics for new requirements | ProjectEffortAllocations schema, UI, tests | **BLOCKING M2** | PMO |
| OD-41 | Actual-effort ownership / on-behalf semantics if OD-19 creates a separate/hybrid actual-entry path | Existing Timesheet allows authorised on-behalf editing; a new actual list may or may not. Client owner claims must never be trusted | a) own only; b) authorised on-behalf by existing scope model; c) project/discipline-specific rule | preserve existing Timesheet semantics if OD-19 = Timesheet-derived; decide explicitly for a new list | Could regress live Timesheet semantics or over-grant writes | actual-effort security, flow contract, tests | **CONDITIONAL BLOCKING M2/M3 if OD-19 = B/C** | CEO + PMO |

## C. Resolved decisions (owner decision or evidence) / scope facts

| ID | Resolution | Evidence / rationale | Effect |
|---|---|---|---|
| OD-01 | **RESOLVED — OWNER_DECISION 2026-10-09 = A** (blank ≠ 0) | Owner decision; legacy storage distinguishes "" and "0" (4 zero cells) while its UI collapsed them; report totals are unchanged because blank and 0 both sum as 0 | Storage `ManDays` null = BLANK, 0 = VALUE; wire `state` BLANK/VALUE; UI shows blank vs "0"; migration keeps the 4 legacy zeros as 0 |
| OD-02 | **RESOLVED_BY_EVIDENCE — owner accepted 2026-10-09 = A** | Legacy VERIFIED: rows = the selected project's phases in project order; no customer requirement asked for all phases (UD-07 was an analysis proposal based on a wrong description) | Rows = the project's phases; a phase outside the project is refused at save |
| OD-03 | **RESOLVED_BY_EVIDENCE — 2026-10-09**: numeric only; decimals allowed; at most 2 decimal places | Legacy VERIFIED: input is parsed as a number with decimal point (no precision limit, no validation); every legacy output shows 2 decimals (report totals `#,0.00`); data holds integers only. Non-numeric input is a legacy defect (silently lost) | 2-dp precision preserved; bounds are **not** decided here → OD-42 |
| OD-04 | **RESOLVED_BY_EVIDENCE — owner accepted 2026-10-09 = A** | Legacy VERIFIED writers CEO, Secretary, PM (+ technical Admin bypass); mapped to Executive and PMO; owner rule: technical admin gets no business authority | `REG.Edit` = Executive, PMO; AppAdmin DENY (seed to be corrected at implementation) |
| OD-09 | **RESOLVED_BY_EVIDENCE — owner accepted 2026-10-09 = A** | D-7 (no Delete right, soft delete only) excludes item deletion; a soft-delete flag would duplicate "blank" | Clear keeps the item and sets `ManDays = null` (BLANK, per OD-01); history in versions and audit |
| OD-21 / EFF-F-8 | **RESOLVED_BY_EVIDENCE — DEFERRED_CURRENT_SCOPE** | project-owner current-scope directive of 2026-10-09 (R3 Open Spec task scope: KPI, Evaluation, salary review, bonus/reward and advanced employee scoring/ranking are deferred / out of current implementation scope) | No evaluation formula is designed or implemented in R3; NR-EFF-09 stays a future-phase requirement (not removed). No customer decision is pending for the current scope |
| OD-26 | **RESOLVED_BY_EVIDENCE — NO_A_I_APPROVAL** | NR-EFF-01 source/traceability states no approval/lock for A.I; inventing one would add a workflow absent from the requirement | EPIC 16 A.I save is effective after a successful guarded write; no `EFF.ProjectApprove` flow/capability in current scope |
| OD-38 | **RESOLVED_BY_EVIDENCE — DOCUMENTATION_SYNC_ONLY** | Same owner directive as OD-21. The repository decision pack and `docs/roadmap.md` do not yet carry it; recording it there is a documentation task (`tasks.md` 0.4), not a decision | No customer decision pending; sync only |

## Tally

Unconditional BLOCKING (any milestone M1–M3 or GL): OD-05, 07, 08, 11 (GL), 14, 15, 16, 17, 18, 19, 22, 23, 24, 25, 27, 28, 29, 30, 32, 33, 34, 37, 40, 42 → **24**. Of these, blocking **M1 (S12.5)**: OD-05, 07, 08, 25, 42 → **5**.

CONDITIONAL BLOCKING: OD-41 → **1** (only if OD-19 selects a separate/hybrid actual-entry path).

NON_BLOCKING for R3 build: OD-06, 10, 12, 13, 20, 31, 35, 36, 39 → **9** (OD-20 and OD-31 become blocking for M4/reporting scope).

Open decisions total: **34**. Resolved in §C: **8** (OD-01 by owner decision; OD-02, OD-03, OD-04, OD-09 by evidence accepted by the owner; OD-21, OD-26, OD-38 by evidence).

Changes since the V3 baseline (2026-10-09, M1 decision cleanup): OD-01, 02, 04, 09 resolved by the owner (−4 blocking); OD-03 resolved by evidence for precision (−1) and its unresolved bounds split into new OD-42 (+1). Net blocking 28 → 24; open 38 → 34.

Milestone gate sets (derived from the Blocking column above; checked by `tools/spec/check_r3_open_spec.py`):

| Gate | BLOCKING decisions | Conditional |
|---|---|---|
| M1 | OD-05, OD-07, OD-08, OD-25, OD-42 | – |
| M2 | OD-14, OD-16, OD-19, OD-22, OD-23, OD-24, OD-25, OD-37, OD-40 | OD-41 (if OD-19 = b/c) |
| M3 | OD-15, OD-17, OD-18, OD-19, OD-27, OD-28, OD-29, OD-30, OD-32, OD-33, OD-34 (+ M2 gate satisfied) | OD-41 (if OD-19 = b/c) |
| GL | OD-11 | – |
| M4 (later release, outside R3) | OD-20, OD-31 (non-blocking for R3) | – |
