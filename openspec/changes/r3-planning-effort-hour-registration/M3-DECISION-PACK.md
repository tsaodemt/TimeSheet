# M3 decision pack — EPIC 17 Discipline Effort Planning / Approval (rev01 A.II, A.III lock)

Status 2026-10-10: **DECISION REVIEW — NO IMPLEMENTATION.** M1 (S12.5) and M2 (EPIC 16) are DONE on STAGING (main 1480de9) and
are not reopened. **M3_IMPLEMENTATION_GATE = BLOCKED — M3 DECISION CHECKPOINT.** A "recommendation" is evidence-based advice, not an
approval; an unanswered decision means **BLOCK / DO NOT GUESS**. Register: `decisions.md`. Vietnamese meeting summary:
`M3-DECISION-SUMMARY.md`. Checker: `tools/spec/check_r3_open_spec.py` (M3 summary table = derived M3 gate).

Evidence classes: **LEGACY_FACT** · **CUSTOMER_REQUIREMENT** · **OWNER_DECISION** · **TARGET_SECURITY_REQUIREMENT** ·
**PROPOSED_DESIGN** · **OPEN_DECISION**.

## 1. Source (rev01, re-extracted with its numbering)

A.II "Đăng ký công cho bộ môn": 1. "Người thực hiện: Nhân viên bộ môn (nhân viên và chủ trì)"; 2. "Đăng ký công": (a) "Theo dự án",
(b) "Chọn công việc thực hiện", (c) "Số công của bộ môn không vượt quá số công mục I.3"; 3. "Người phê duyệt: Chủ trì => khóa công
Đăng Ký". A.III "Công thực hiện dự án": 1. "Chấm công thực hiện dự án: nhân viên bộ môn (nhân viên và chủ trì)"; 2. "Người phê duyệt:
Chủ trì => khóa công thực hiện". **Not stated** (verified absence): unlock / reopen, approval order, self-approval, revision, period,
value rules, visibility.

Legacy facts used: role "Leader" is labelled "Chủ trì bộ môn" in the legacy UI and maps to Team Leader (role map); the legacy
timesheet input `cmb_cvduan` "Công việc dự án" = project phases, `cmb_cvth` = work type (E10 "Loại hình công việc");
EPIC 07 approval locks Approved timesheet entries (live since R2).

## 2. M3 gate (derived from the register)

Before this review: OD-15, OD-17, OD-18, OD-27, OD-28, OD-29, OD-30, OD-32, OD-34, OD-45, OD-46 (11).
After: **OD-17, OD-18, OD-27, OD-28, OD-29, OD-30, OD-34, OD-46, OD-47, OD-48** (10).

## 3. Resolved by evidence in this review (owner may override)

| ID | Topic | Resolution | Evidence |
|---|---|---|---|
| OD-15 | A. ceiling scope | **project × discipline, lifetime**: the ceiling of discipline D in project P is the A.I.3 value of recipient `D:<D>` of P | rev01 A.II.2 "Theo dự án" + "không vượt quá số công mục I.3"; A.I has no phase and no period (OD-22, OD-23) |
| OD-32 | H. ceiling relation | **≤ (not exceed)**; equality not required | "không vượt quá" |
| OD-45 | K. EPIC 17 unit | **man-day**: A.II compares "số công của bộ môn" directly with "số công mục I.3" (no conversion), and I.3 is in man-days (OD-14). Derived from the source, not propagated automatically | rev01 A.II.2(c); OD-14 |
| OD-49 | I. actual lock (A.III) | **existing EPIC 07 timesheet approval**: no second approval / lock of actuals in EPIC 17 (`EFF.ActualApprove` NOT_APPLICABLE) | OD-19 (no duplicate actual-effort workflow), OD-33 (Approved only) |

## 4. Remaining decisions (genuine business / security choices)

### OD-17 — B. Who is the "Chủ trì" (A.II approver)?
- **Question:** the Team Leader of the discipline, a per-project / per-discipline assignment, or a new role?
- **Evidence:** legacy label "Chủ trì bộ môn" on the Leader role → Team Leader (LEGACY_FACT); the guard already enforces discipline scope; rev01 names "Chủ trì" without a project scope.
- **Options:** a) Team Leader of the discipline; b) per-project Chủ trì list; c) new role.
- **Recommendation:** (a). **Impact:** approvals in discipline scope with the existing group; (b) needs a new assignment list + project scope.
- **Decider:** CUSTOMER_AND_SECURITY (CEO + HR; security owner).

### OD-30 — G. Registration granularity
- **Question:** does each staff member register their own effort (person × project × task) or does the discipline register an aggregate?
- **Evidence:** "Người thực hiện: Nhân viên bộ môn (nhân viên và chủ trì)" — individuals act.
- **Recommendation:** per person × project × task; the ceiling sums all persons of the discipline in the project. **Decider:** CUSTOMER.

### OD-29 — F. Meaning of "Chọn công việc thực hiện"
- **Options:** a) work type (E10); b) project phase; c) free text.
- **Evidence:** legacy timesheet: `cmb_cvth` = work type, phases are "Công việc dự án" (`cmb_cvduan`) — INFERRED from legacy naming.
- **Recommendation:** (a) work type. **Decider:** CUSTOMER.

### OD-48 — G. Time dimension of A.II
- **Recommendation:** one project-lifetime value per person × project × task ("Theo dự án"; the ceiling is lifetime). **Decider:** CUSTOMER.

### OD-47 — Value domain of A.II
- **Recommendation:** same as EPIC 16 — at most 2 decimals (more refused, no rounding), ≥ 0, no business maximum, blank ≠ 0. Confirmation only. **Decider:** CUSTOMER.

### OD-27 — D. Order and ceiling basis
- **Questions:** (1) Can A.II be registered while the discipline's A.I.3 value is blank (not registered)? (2) Do Draft and Approved registrations both count against the ceiling? (3) If the PM later lowers A.I.3 below the registered total, is that refused or allowed?
- **Recommendation:** (1) no — a blank ceiling means "not planned" (OD-40), registration refused until the PM registers it; (2) both count (the rule limits registration, not approval); (3) refused at A.I save (keeps the rule true; requires a small M2 change through a spec delta).
- **Decider:** CUSTOMER (PMO).

### OD-28 — E. Self-approval
- **Question:** may the Chủ trì approve their own A.II rows? **Recommendation:** no (timesheet precedent UD-04: no self-approval); another Chủ trì of the discipline, or Executive, approves. **Decider:** CUSTOMER_AND_SECURITY.

### OD-18 — C. Unlock / reopen after approval
- **Options:** a) never; b) Chủ trì; c) higher role; d) request + approve. **Recommendation:** (a) none in R3 (rev01 states only the lock); corrections later through a new decision. **Decider:** CUSTOMER (CEO).

### OD-34 — J. Revision model
- **Recommendation:** no revision entity; history = audit rows + SharePoint versions (with OD-18 = none, an approved row never changes). **Decider:** CUSTOMER.

### OD-46 — L. Visibility and permissions of A.II data
- **Recommendation (separate permissions):** VIEW: staff own rows; Chủ trì own discipline; the project's PM own project; PMO and Executive all. EDIT: staff own Draft rows (OD-30). APPROVE: Chủ trì (OD-17), not own rows (OD-28). REOPEN: per OD-18. HR, Finance, Salary Viewer, App Administrator, IT Support, Confidential Owner, Migration Owner: DENY. Quản lý phòng: OD-31 (M4). Not inherited from OD-05 / OD-37.
- **Decider:** CUSTOMER_AND_SECURITY.

## 5. Not reopened

M1 decisions; M2 decisions OD-14, 16, 19, 22, 23, 24, 33, 37, 40, 44 (OD-41 NOT_APPLICABLE); OD-25 (separation), OD-26 (no A.I approval).
