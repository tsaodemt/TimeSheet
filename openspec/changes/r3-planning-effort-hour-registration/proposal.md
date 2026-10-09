# R3 Planning & Effort — Hour Registration (S12.5), Project Effort (EPIC 16), Discipline Effort (EPIC 17)

> **Status: OPEN_SPEC_V3 = APPROVED (project owner, 2026-10-09) as the specification baseline. R3-G0 = APPROVED.**
> **READY_FOR_IMPLEMENTATION = NO** — implementation is gated per milestone (M1 / M2 / M3) by the blocking decisions in `decisions.md`.
> Process: `docs/delivery-process.md` (Open Spec first, project owner 2026-10-09). Baseline: main after EPIC 07 closure.
> Unknown business rules are `OPEN_DECISION` items in `decisions.md`; recommended defaults there are **not** approved.

## Why

R3 delivers planning and effort: the legacy budget matrix "Đăng ký công" (S12.5) must be replaced, and the customer's new
requirement "Đăng ký công – rev01" adds project effort registration by the PM (EPIC 16), discipline effort registration
with a ceiling, Chủ trì approval and lock (EPIC 17), and planned-vs-actual figures for later analytics (EPIC 18 boundary).
EFF-F-1..7, 9 and 10 remain open; EFF-F-8 (resource evaluation) is RESOLVED_BY_EVIDENCE as deferred for the current scope (OD-21; project-owner scope directive) and remains a future-phase requirement. Legacy behaviour contradicts parts of the current backlog contract
(blank vs zero, matrix rows, read-only behaviour), and the two "Đăng ký công" concepts share a name but not a proven
model. Writing code now would mean guessing business rules, which the new process forbids.

## What Changes

- **Specification only.** This change defines requirements, design options, a decision register, a traceability map,
  acceptance criteria and an implementation entry gate (R3-G0). It creates no list, flow, app version or tenant data.
- **S12.5 Hour Registration** — legacy-first parity spec built from the decompiled legacy source and the legacy data
  profile (39 legacy behaviours classified REPLICATE / REPLACE / FIX_LEGACY_DEFECT / SECURITY_HARDENING /
  NOT_APPLICABLE / OPEN_DECISION). Writes move from a client-side file overwrite to a guarded, audited, per-cell
  changed-cell save with ETag concurrency (**BREAKING vs legacy**: whole-matrix last-writer-wins is removed).
- **EPIC 16 / EPIC 17** — requirement-level specs for all 14 NR-EFF items, with every unresolved rule bound to an
  `OPEN_DECISION`; candidate data models and guarded flow contracts parameterised by those decisions.
- **Shared contracts** — planning security (capabilities per role, server-side guard, untrusted client claims), audit
  events, concurrency and batch semantics, actual-effort boundary (options, not a choice), reporting data contract for
  EPIC 18 (no analytics implementation).
- **Out of scope:** KPI, evaluation, salary review, bonus, resource evaluation formula (F-8), salary-cost analytics,
  Production cutover, EPIC 07 fixture cleanup, any tenant mutation.

## Capabilities

### New Capabilities
- `hour-registration`: legacy S12.5 budget matrix (project × phase × discipline, man-days) — selection, matrix
  read/edit/clear/save, blank vs zero, read-only mode, validation, conflict handling.
- `project-effort`: EPIC 16 — PM registration of project effort for Quản lý phòng, PM and disciplines from the project
  output allocation; actual project effort capture boundary (NR-EFF-01, NR-EFF-05).
- `discipline-effort`: EPIC 17 — discipline effort registration per project and task, ceiling validation, Chủ trì
  approval and lock of registered and actual effort (NR-EFF-02, -03, -04, -06).
- `planning-security`: roles, capabilities, scopes and the guarded write path for every planning operation.
- `planning-audit`: audit events, exactly-once semantics, correlation, change summaries for planning writes.
- `effort-reporting-contract`: data contract consumed by later reporting (registered/planned, actual, variance,
  project and discipline summaries; NR-EFF-07..14 boundary).

### Modified Capabilities
- None. `openspec/specs/` is empty (first OpenSpec change in this repository). Existing timesheet behaviour (EPIC 06/07)
  is referenced, not modified.

## Impact

- **Future lists (SharePoint, OPS site, not provisioned here):** `HourRegistrations` (existing target design, revised);
  candidate EPIC 16/17 lists named in `design.md` §5.
- **Future flows (not built):** `REG-ReadMatrix`, `REG-SaveMatrix`, `EFF-*` proposals in `design.md` §8.
- **Future Canvas screens:** Hour Registration matrix; effort registration journeys (`design.md` §7).
- **Existing artefacts touched later (not now):** role seed / ScopeConfig (`REG.*`, new `EFF.*` capabilities), audit catalogue (Approval records the resulting locked state; `Unlock` stays disabled until EFF-F-5/OD-18), backlog S12.5 / EPIC 16–18 wording after decisions.
- **Decisions:** `decisions.md` contains 38 open items after review (28 unconditional BLOCKING, 1 CONDITIONAL BLOCKING, 9 NON_BLOCKING) plus 3 RESOLVED_BY_EVIDENCE items (OD-21, OD-26, OD-38). Nine open items block S12.5; gate sets per milestone are in `decisions.md`. Implementation entry gate R3-G0 is CLOSED.
