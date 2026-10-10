# R3 M4 — current-scope reporting — decision pack (no implementation)

Status 2026-10-10. Change `r3-planning-effort-hour-registration`. M1, M2 (EPIC 16, main 1480de9) and M3 (EPIC 17, main ed38f24) are DONE on STAGING. **M4_IMPLEMENTATION_GATE = RELEASED** — all six M4 decisions resolved by the owner 2026-10-10 (§4).
M4 = the current-scope reporting step of the master task R3-COMPLETE-M2-M3-M4 (Part E): project planned vs actual, discipline
planned vs actual, variance, and the effort summaries planning needs. **Not in M4:** KPI, salary review, bonus / reward, resource
scoring, ranking, advanced evaluation analytics (NR-EFF-09 stays deferred, OD-21 / OD-38). This pack derives the M4 gate from the
register and the approved M2 / M3 facts; it implements nothing.

## 1. What is already decided (no question needed)

| Topic | Decided by | M4 consequence |
|---|---|---|
| Project planned effort | OD-14, OD-16, OD-23, OD-40, OD-44 | `ProjectEffortAllocations`: man-days, ≤ 2 dp, project lifetime, blank = not registered, 0 explicit |
| Discipline planned effort | OD-30, OD-45, OD-47, OD-48 | `DisciplineEffortRegistrations`: man-days per Employee × Project × WorkType, project lifetime; discipline total = aggregate |
| Actual effort | OD-19, OD-33, OD-49 | Σ **Approved** `TimesheetEntries.Hours` ÷ `HoursPerManDay` (8), per project and per `DisciplineCode`; computed, never stored |
| Revision | OD-34 | audit only — reports read the current value; no revision history measure |
| Time dimension of the plan | OD-23, OD-48 | lifetime only — a period filter can apply to actual hours only, never to planned values |
| Legacy M1 registration | OD-25, OD-05 | `HourRegistrations` (Đăng ký công) is a separate capability; the shared man-day unit does not link it to EPIC 16 |
| Visibility of EPIC 16 facts | OD-37 | project PM (own projects), PMO, Executive |
| Visibility of EPIC 17 facts | OD-46 | own rows; TL own discipline; PM own projects; PMO / Executive company; others deny |
| Evaluation / KPI / ranking | OD-21, OD-38 + master task | out of scope |
| Technical roles | security baseline | AppAdmin / IT Support / service identity get no business reporting access |

Measure contract (reporting fact rules, §49 of the master task) — fixed by the decisions above, open points marked:

| Measure | Source | Unit | Normalisation | Period | Approval state | Revision | Blank / 0 | Security scope |
|---|---|---|---|---|---|---|---|---|
| Project planned (A.I) | ProjectEffortAllocations | man-day | none | lifetime | n/a (no approval in EPIC 16) | current | blank excluded from count, adds 0 to sums | OD-37 |
| Project actual | TimesheetEntries | hour → man-day | ÷ HoursPerManDay | lifetime (period filter = **OD-13**) | Approved only | current | n/a | OD-37 (totals only) |
| Project variance | derived | man-day | – | lifetime | – | – | blank plan = no plan (**OD-13**) | OD-37 |
| Discipline planned | DisciplineEffortRegistrations | man-day | none | lifetime | **OD-51** (Draft + ApprovedLocked or ApprovedLocked only) | current | blank excluded, 0 explicit | OD-46 |
| Discipline actual | TimesheetEntries by DisciplineCode | hour → man-day | ÷ HoursPerManDay | lifetime | Approved only | current | n/a | OD-46 (totals only) |
| Discipline ceiling (A.I.3) | ProjectEffortAllocations D:<discipline> | man-day | none | lifetime | n/a | current | blank = not registered | OD-46 |
| Legacy registered (M1) | HourRegistrations | man-day | none | lifetime | n/a | current | OD-01 | OD-05 — shown only if **OD-52** = include |
| Cost | – | – | – | – | – | – | – | **OD-20** |

## 2. Derived M4 gate

| Id | Question | Why it blocks M4 | Recommendation | Decider |
|---|---|---|---|---|
| OD-50 (new) | Reporting surface | Approved architecture = Power BI with RLS, but **no Power BI SKU is in the tenant** (preflight IT-01; IT-02 open). A report cannot be built or secured without choosing the surface | (b) guarded in-app summary screens (same Power Automate guard + scope as M2 / M3, server-side totals, no new licence); (a) Power BI Pro for authors + every viewer, RLS mirroring OD-37 / OD-46 — when licensed | Project owner + IT |
| OD-20 | Salary / labour cost in reports | NR-EFF-07/08/11/12/14 ask for cost; the master task allows cost only if explicitly confirmed — not confirmed; confidential (S-01, ENV-D2) | exclude cost from current M4 (no rate / salary data read) | CEO + HR |
| OD-31 | Quản lý phòng reporting scope (NR-EFF-13/14) | NR-EFF-13 gives Quản lý phòng a cross-project view; no target role / person is mapped | no separate grant in M4: report visibility = M2 / M3 matrices (PMO and Executive already see company totals); a later mapping can add it | CEO + HR |
| OD-13 | Show planned rows that have no actual (legacy omits, LHR-33) | Decides row inclusion of every planned-vs-actual table | (a) show them (planned with actual 0) | PMO |
| OD-51 (new) | Discipline planned in reports: which EPIC 17 states count | EPIC 17 stores Draft and ApprovedLocked; the ceiling counts both (OD-27 derived rule) but a report may present only approved plans | show both: "đã duyệt" (ApprovedLocked) and "tổng đăng ký" (Draft + ApprovedLocked); variance against the approved figure | PMO |
| OD-52 (new) | "Kế hoạch" of the project report | Two planned sources exist in man-days (EPIC 16 A.I and legacy M1 Đăng ký công); OD-25 keeps them unlinked | EPIC 16 A.I is the project plan; M1 Đăng ký công shown as a separate column, never added or netted | PMO |

Not blocking M4: OD-06, 10, 12 (lifetime, = OD-23), 35, 36, 39, 43 (UI / migration / naming). OD-11 stays GL.

## 3. Reconciliation the M4 build must prove (after the answers)
M2 planned per project = report planned; Approved actual = report actual (11 h = 1.375 công on DEMO-PRJ-01); M3 planned per discipline
= report discipline planned (per OD-51); unit conversion exact; blank vs 0; role / scope filtering per OD-37 / OD-46; no cost column.

## 4. Closure 2026-10-10 (owner decisions, task R3-M4-APPLY-OWNER-DECISIONS-AND-IMPLEMENT)

| Id | Answer | Key |
|---|---|---|
| OD-50 | b | IN_APP_GUARDED_REPORTING |
| OD-20 | a | EFFORT_ONLY_NO_LABOUR_COST |
| OD-31 | b (M4 reporting only) | APPROVER_AS_QUAN_LY_PHONG_FOR_M4_ONLY |
| OD-13 | a | PLAN_WITH_NO_ACTUAL_VISIBLE_ACTUAL_ZERO |
| OD-51 | b | APPROVEDLOCKED_ONLY |
| OD-52 | a | M2_PROJECT_PLAN_M1_SEPARATE |

Derived M4 gate after closure: none. Report capability matrix: `decisions.md` (M4 report capability matrix); contracts:
`design.md` §11.1; acceptance AC-RPT-01..06. The measure table of §1 now reads: discipline planned = ApprovedLocked only; project
plan = EPIC 16; M1 registered separate (REG.View holders); plan with no actual shown with actual 0; cost = none.
