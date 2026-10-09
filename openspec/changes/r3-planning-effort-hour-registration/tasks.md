# Tasks — SPEC-READY / NOT APPROVED FOR IMPLEMENTATION

> Spec baseline approved 2026-10-09 (R3-G0 = APPROVED). Tasks remain NOT APPROVED FOR IMPLEMENTATION: **none may start** until the milestone gate is released
> (`design.md` §14): owner approval of this Open Spec and the milestone's BLOCKING decisions (`decisions.md`).

## 0. Spec review and decisions (no implementation)

- [x] 0.1 Project owner review of proposal, design, specs, acceptance, role matrix — APPROVED 2026-10-09 (Open Spec V3 baseline)
- [ ] 0.2 Record answers for M1 decisions — DONE 2026-10-09: OD-01, 02, 04, 09 (owner), OD-03 (evidence); OPEN: OD-25 (customer, first), OD-07, OD-08 (customer), OD-05 (security owner), OD-42 (owner) — see `M1-DECISION-PACK.md`
- [ ] 0.3 Customer workshop (backlog S16.1) for the M2 and M3 gate sets in `decisions.md` (open EFF-F-1..7, 9, 10 and OD-24, 25, 27–30, 32–34, 37, 40; non-blocking OD-31, 35, 36 may be taken at the same time); include OD-41 only if OD-19 selects separate/hybrid actual entry
- [ ] 0.4 Documentation sync only (no decision pending): record the RESOLVED_BY_EVIDENCE items OD-21 / OD-38 (current-scope deferral) and OD-26 (no A.I approval) in the project decision pack and `docs/roadmap.md`; apply the OD-39 id rename
- [ ] 0.5 Re-baseline this task list and the backlog source (S12.5, EPIC 16/17 wording) after decisions

## 1. M1 — S12.5 Hour Registration (blocked by 0.1, 0.2)

- [ ] 1.1 Update the target data model and provisioning definition for `HourRegistrations` (§5.1)
- [ ] 1.2 Reference model + tests: changed-cell diff, BLANK/VALUE encoding (OD-01 = A), 2-dp precision + OD-42 bounds, preflight, per-cell results, replay-safe NO_CHANGE/CONFLICT semantics
- [ ] 1.3 Generate `REG-ReadMatrix` / `REG-SaveMatrix`; reference-vs-flow tests incl. audit and concurrency
- [ ] 1.4 Capability seed: `REG.Edit` = Executive + PMO, AppAdmin removed (OD-04); `REG.View` per OD-05; role × capability tests
- [ ] 1.5 Canvas Hour Registration screen + generator assertions (blank vs 0, Save rule, read-only, dirty prompt, geometry)
- [ ] 1.6 STAGING: provision list, deploy flows, publish app, live proof with synthetic projects, per-role live results
- [ ] 1.7 Migration of legacy E14 per OD-11 (199 items incl. 4 explicit zeros, blanks → no item; Σ per project reconciled; stale rows per OD-08)

## 2. M2 — EPIC 16 Project Effort (blocked by 0.3)

- [ ] 2.1 Data model for `ProjectEffortAllocations` per OD-14/16/22/23/25/40 (`QuanLyPhong` stored as recipient category; OD-31 is a later visibility mapping)
- [ ] 2.2 Project scope in the guard per OD-24 (design + tests)
- [ ] 2.3 `EFF-ReadProjectAllocation` / `EFF-SaveProjectAllocation` (no A.I approval flow in current scope; resolved OD-26)
- [ ] 2.4 Actual effort boundary per OD-19; preserve existing Timesheet ownership/on-behalf semantics if reused, otherwise close OD-41 before a new actual-entry path
- [ ] 2.5 Canvas journey 7.2(1) and live proof

## 3. M3 — EPIC 17 Discipline Effort (blocked by 0.3, M2 data model)

- [ ] 3.1 `DisciplineEffortRegistrations` per OD-29/30; ceiling counter per OD-15/32
- [ ] 3.2 `EFF-SaveDisciplineEffort`, `EFF-ApproveDisciplineEffort` (lock), queue read
- [ ] 3.3 Actual effort approval/lock per OD-19/33; unlock only if OD-18
- [ ] 3.4 Permission tests (forged owner / approver), concurrency tests, live proof

## 4. Closure

- [ ] 4.1 Offline/reference reporting data-contract reconciliation checks (AC-R3-02); do not deploy EPIC18 analytics
- [ ] 4.2 Focused R3 E2E, security recheck, full regression, evidence, backlog closure
