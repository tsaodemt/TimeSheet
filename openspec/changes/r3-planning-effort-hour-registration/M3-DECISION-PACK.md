# M3 decision pack — EPIC 17 Discipline Effort Planning / Approval (rev01 A.II, A.III lock)

Status 2026-10-10: **DECISION CLOSURE COMPLETE — M3_IMPLEMENTATION_GATE = RELEASED.** The M3 checkpoint (commit 950f3cc) asked ten
questions; the project owner resolved all of them on 2026-10-10. M1 and M2 are DONE and not reopened. Register: `decisions.md`.
Vietnamese record: `M3-DECISION-SUMMARY.md`. Checker: `tools/spec/check_r3_open_spec.py`.

## 1. Source

rev01 A.II "Đăng ký công cho bộ môn": registrants "Nhân viên bộ môn (nhân viên và chủ trì)"; "Theo dự án"; "Chọn công việc thực hiện";
"Số công của bộ môn không vượt quá số công mục I.3"; approver "Chủ trì => khóa công Đăng Ký". A.III: "Chủ trì => khóa công thực hiện".

## 2. M3 gate (derived)

Before: OD-17, 18, 27, 28, 29, 30, 34, 46, 47, 48. After: **none**.

## 3. Resolved by evidence (review 2026-10-10)

| ID | Resolution |
|---|---|
| OD-15 | ceiling = A.I.3 value of the same discipline recipient of the project, lifetime |
| OD-32 | Σ ≤ ceiling |
| OD-45 | man-day (rev01 compares the two "số công" directly; not inherited from OD-14) |
| OD-49 | A.III lock = existing EPIC 07 timesheet approval; no second actual workflow |

## 4. Owner decisions 2026-10-10

| ID | Decision | Effect |
|---|---|---|
| OD-17 | Chủ trì = Team Leader of the caller's authoritative discipline (owner target mapping) | no new role; several TLs per discipline; not Approver |
| OD-18 | no reopen | Draft → ApprovedLocked only; `EFF.Unlock` N/A |
| OD-27 | single approval stage; approval = lock | no submit / PM / PMO / Executive stage; no Lock event |
| OD-28 | self-approval allowed in EPIC 17 only | EPIC 07 self-approval stays denied (regression tests) |
| OD-29 | existing active WorkTypes (stable LegacyId) | no Task entity; inactive not selectable for new rows |
| OD-30 | Employee × Project × WorkType; discipline from Employees | no stored / editable discipline total |
| OD-34 | audit only | no revision entity; approved rows immutable |
| OD-46 | view own / discipline / PM project / PMO / Executive; edit own Draft; approve TL same discipline | others denied; not inherited from OD-05 / OD-37 |
| OD-47 | man-day, ≥ 0, ≤ 2 dp (reject), blank ≠ 0, no maximum | TECHNICAL_LIMIT only from the platform |
| OD-48 | project lifetime | no period / window |

## 5. Derived rules recorded (not new business decisions; owner may override)

- **Ceiling basis:** every non-blank registration of D in P counts (Draft + ApprovedLocked) — "all applicable allocations" (OD-30); the
  save-time check must include other employees' drafts or concurrent drafts could exceed the ceiling.
- **Blank A.I.3:** "not registered" (OD-40) is not a number; saving a VALUE is refused (CEILING_NOT_REGISTERED); clearing is allowed.
- **A.I.3 lowered later (M2 unchanged):** the discipline can be over its ceiling; further increases and approvals of D in P are refused
  (OVER_CEILING) until A.I.3 is raised or drafts are reduced.
- **Editor totals:** the employee editor shows the aggregate ceiling / used / remaining of the caller's own discipline (totals only), as the
  owner's UI list requires; no other person's rows.
- **Concurrency:** a technical lock item per Project × Discipline (`DisciplineEffortLocks`: Busy / BusyUntil / Stamp, no business value)
  serialises ceiling checks; a concurrent saver gets CONFLICT with 0 writes.

## 6. Not reopened

M1 decisions; M2 decisions (OD-14, 16, 19, 22, 23, 24, 33, 37, 40, 44; OD-41 N/A); OD-25, OD-26.
