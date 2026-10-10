# Tasks — SPEC-READY / NOT APPROVED FOR IMPLEMENTATION

> Spec baseline approved 2026-10-09 (R3-G0 = APPROVED). Tasks remain NOT APPROVED FOR IMPLEMENTATION: **none may start** until the milestone gate is released
> (`design.md` §14): owner approval of this Open Spec and the milestone's BLOCKING decisions (`decisions.md`).

## 0. Spec review and decisions (no implementation)

- [x] 0.1 Project owner review of proposal, design, specs, acceptance, role matrix — APPROVED 2026-10-09 (Open Spec V3 baseline)
- [x] 0.2 Record answers for M1 decisions — DONE 2026-10-09: OD-01, 02, 04, 09, 42 (owner), OD-03 (evidence), OD-25, OD-07, OD-08, OD-05 (owner, legacy parity). M1_IMPLEMENTATION_GATE = APPROVED
- [x] 0.2a Record owner decisions for M2 — DONE 2026-10-10: OD-14 = man-day, OD-19 = existing TimesheetEntries, OD-40 = blank not registered / zero explicit; OD-41 = NOT_APPLICABLE; OD-44 = min 0 / negative deny / no business maximum; >2 decimals rejected (no rounding)
- [x] 0.2b Record owner decisions closing the M2 gate — DONE 2026-10-10: OD-16 manual, OD-22 no phase, OD-23 lifetime, OD-24 one authoritative PM per project (PMO), OD-33 Approved only, OD-37 PM + PMO + Executive; EPIC 17 visibility split out as OD-46
- [ ] 0.3 Customer workshop (backlog S16.1) for the M3 gate set in `decisions.md` (open EFF-F-2, 4, 5 and OD-27–30, 32, 34, 45 (EPIC 17 unit), 46 (EPIC 17 visibility); non-blocking OD-31, 35, 36 may be taken at the same time)
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

## 2. M2 — EPIC 16 Project Effort (decisions complete; rebaselined 2026-10-10)

Prerequisites (verified on STAGING read-only 2026-10-10): `Projects` has no PM field and unique permissions (master data, unchanged);
`Employees.IsActive` / `LegacyId` exist; `Disciplines` ELE, HVAC, PSF, BIM, QL; AppSettings `HoursPerManDay` = 8;
`TimesheetEntries` has `Project` (indexed lookup), `Hours`, `EntryStatus` (Draft / Approved / Deleted).

- [ ] 2.1 Schema definitions + tests: `ProjectPmAssignments` (PM, OD-24) and `ProjectEffortAllocations` (project × recipient, man-days ≤ 2 dp, ≥ 0, no maximum, blank ≠ 0, portable keys; no phase / period / approval / M1 link / cost); AppSettings `ProjectEffortRecipientDisciplines` (OD-43 default ELE,HVAC,PSF,BIM)
- [ ] 2.2 Capability seed + guard project-PM scope: `EFF.ProjectView` (PMO, EXE + PM scope), `EFF.ProjectEdit` (PM scope only), `EFF.ProjectPmAssign` (PMO); role × capability tests incl. AppAdmin / IT Support DENY
- [ ] 2.3 Reference model + tests: PM assignment, read (list / detail, Approved actual aggregation, no row leakage), save (preflight, ETag, typed errors, changed-only, audit)
- [ ] 2.4 Flows `EFF-SetProjectPm`, `EFF-ReadProjectEffort`, `EFF-SaveProjectEffort` generated; reference-vs-flow tests (simulator) incl. paging of TimesheetEntries
- [ ] 2.5 Canvas Project Effort screen (navigation, project picker from the flow, PM display + PMO assignment, recipient entry, planned total, Approved actual, comparison, blank vs 0, dirty / save / reload / typed errors) + generator assertions
- [ ] 2.6 STAGING: provision lists + AppSettings key, deploy flows (run-only), publish app; live E2E, 12-role matrix, security probes, audit; evidence; backlog
- Data impact: new lists only; no migration (no legacy data; OD-25 no seeding); existing Timesheet and M1 untouched

## 3. M3 — EPIC 17 Discipline Effort (blocked by 0.3, M2 data model)

- [ ] 3.1 `DisciplineEffortRegistrations` per OD-29/30; ceiling counter per OD-15/32
- [ ] 3.2 `EFF-SaveDisciplineEffort`, `EFF-ApproveDisciplineEffort` (lock), queue read
- [ ] 3.3 Actual effort approval/lock per OD-19/33; unlock only if OD-18
- [ ] 3.4 Permission tests (forged owner / approver), concurrency tests, live proof

## 4. Closure

- [ ] 4.1 Offline/reference reporting data-contract reconciliation checks (AC-R3-02); do not deploy EPIC18 analytics
- [ ] 4.2 Focused R3 E2E, security recheck, full regression, evidence, backlog closure
