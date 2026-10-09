# Tasks — SPEC-READY / NOT APPROVED FOR IMPLEMENTATION

> Spec baseline approved 2026-10-09 (R3-G0 = APPROVED). Tasks remain NOT APPROVED FOR IMPLEMENTATION: **none may start** until the milestone gate is released
> (`design.md` §14): owner approval of this Open Spec and the milestone's BLOCKING decisions (`decisions.md`).

## 0. Spec review and decisions (no implementation)

- [x] 0.1 Project owner review of proposal, design, specs, acceptance, role matrix — APPROVED 2026-10-09 (Open Spec V3 baseline)
- [x] 0.2 Record answers for M1 decisions — DONE 2026-10-09: OD-01, 02, 04, 09, 42 (owner), OD-03 (evidence), OD-25, OD-07, OD-08, OD-05 (owner, legacy parity). M1_IMPLEMENTATION_GATE = APPROVED
- [x] 0.2a Record owner decisions for M2 — DONE 2026-10-10: OD-14 = man-day, OD-19 = existing TimesheetEntries, OD-40 = blank not registered / zero explicit; OD-41 = NOT_APPLICABLE; OD-44 = min 0 / negative deny / no business maximum; >2 decimals rejected (no rounding)
- [ ] 0.3 Customer workshop (backlog S16.1) for the M2 and M3 gate sets in `decisions.md` (M2: OD-16, 22, 23, 33 customer; OD-24, 37 customer + security; M3: open EFF-F-2..5 and OD-27–30, 32, 34, 45 (EPIC 17 unit); non-blocking OD-31, 35, 36 may be taken at the same time)
- [ ] 0.4 Documentation sync only (no decision pending): record the RESOLVED_BY_EVIDENCE items OD-21 / OD-38 (current-scope deferral) and OD-26 (no A.I approval) in the project decision pack and `docs/roadmap.md`; apply the OD-39 id rename
- [ ] 0.5 Re-baseline this task list and the backlog source (S12.5, EPIC 16/17 wording) after decisions

## 1. M1 — S12.5 Hour Registration (blocked by 0.1, 0.2)

- [x] 1.1 Update the target data model and provisioning definition for `HourRegistrations` (§5.1) — DONE 2026-10-10 (`tools/registration/hr_schema.py`; STAGING list provisioned, unique permissions: owners + service role only)
- [x] 1.2 Reference model + tests: changed-cell diff, BLANK/VALUE encoding (OD-01 = A), ≥ 0, ≤ 2 decimals, no business maximum (OD-03, OD-42), preflight, per-cell results, replay-safe NO_CHANGE/CONFLICT semantics — DONE (`tools/registration/hour_registration.py`, HR01–HR34)
- [x] 1.3 Generate `REG-ReadMatrix` / `REG-SaveMatrix`; reference-vs-flow tests incl. audit and concurrency — DONE; live findings fixed: ids compared as integers (SharePoint numbers arrive as floats, HR33) and parallel cell loops so a 100-cell save answers within the Power Apps 120 s wait (HR34)
- [x] 1.4 Capability seed: `REG.Edit` = Executive + PMO (OD-04); `REG.View` = Team Leader, Approver, Executive, PMO, HR, IT Support (OD-05); AppAdmin removed; role × capability tests — DONE (offline + live, every role)
- [x] 1.5 Canvas Hour Registration screen + generator assertions (blank vs 0, Save rule, read-only, dirty prompt, geometry) — DONE (HC01–HC16; year list = All + 2017–2050 legacy parity, no delegation warning)
- [x] 1.6 STAGING: provision list, deploy flows, publish app, live proof with synthetic projects, per-role live results — DONE 2026-10-10: 13×5 round trip, update/clear, validation, stale ETag (preflight), removed/re-added phase, Paused project; 12/12 roles as specified; Closed status not testable (no Closed state in the target schema); post-preflight conflict (PARTIAL) proven offline only
- [ ] 1.7 (open — blocked by OD-11, migration gate; not part of the S12.5 screen closure) Migration of legacy E14 per OD-11 (199 items incl. 4 explicit zeros, blanks → no item; Σ per project reconciled; stale rows per OD-08)

## 2. M2 — EPIC 16 Project Effort (blocked by 0.3)

- [ ] 2.1 Data model for `ProjectEffortAllocations`: man-days ≤ 2 dp, more rejected (OD-14), ≥ 0 / no business maximum (OD-44), blank ≠ 0 (OD-40), own schema (OD-25); grain/source per OD-16/22/23 (`QuanLyPhong` stored as recipient category; OD-31 is a later visibility mapping)
- [ ] 2.2 Project scope in the guard per OD-24 (design + tests)
- [ ] 2.3 `EFF-ReadProjectAllocation` / `EFF-SaveProjectAllocation` (no A.I approval flow in current scope; resolved OD-26)
- [ ] 2.4 Actual effort from existing TimesheetEntries (OD-19): no new list/flow/screen; reporting/query contract hours of the OD-33 counted rows ÷ `HoursPerManDay` (not before OD-33 is decided); regression tests that existing Timesheet ownership/on-behalf/status semantics are unchanged (OD-41 NOT_APPLICABLE)
- [ ] 2.5 Canvas journey 7.2(1) and live proof

## 3. M3 — EPIC 17 Discipline Effort (blocked by 0.3, M2 data model)

- [ ] 3.1 `DisciplineEffortRegistrations` per OD-29/30; ceiling counter per OD-15/32
- [ ] 3.2 `EFF-SaveDisciplineEffort`, `EFF-ApproveDisciplineEffort` (lock), queue read
- [ ] 3.3 Actual effort approval/lock per OD-19/33; unlock only if OD-18
- [ ] 3.4 Permission tests (forged owner / approver), concurrency tests, live proof

## 4. Closure

- [ ] 4.1 Offline/reference reporting data-contract reconciliation checks (AC-R3-02); do not deploy EPIC18 analytics
- [ ] 4.2 Focused R3 E2E, security recheck, full regression, evidence, backlog closure
