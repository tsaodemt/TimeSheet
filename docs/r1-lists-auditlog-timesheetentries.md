# S05.5 AuditLog and S06.1 TimesheetEntries — design and provisioning plan

Both lists are designed offline. **Nothing is provisioned.** Code: `tools/provisioning/r1_lists.py`.

Tests:
- `test_auditlog.py`: AL01–AL18;
- `test_timesheet_entries.py`: TE01–TE21.

Each list definition comes from:
- the target data model (§4.1, §8);
- the audit model (`audit-model.md`, `tools/audit/audit_event.py`);
- the R1 contracts and the columns the generated R1 flows write;
- the S03.5 permission model.

The definition is reconciled against the local target schema (AL18 / TE21). The only differences are the index decisions below.

## Dependency review

| | AuditLog (S05.5, operational) | TimesheetEntries (S06.1) |
|---|---|---|
| Schema provisioning | S04.1 provisioning tooling only. Backlog: S05.5 → S04.1. No lookups. | Backlog: S04.6 (Projects lists; → S04.3 + **G2**) and S05.4 (guard framework → S05.1 → **D-3 + ENV-D3**). Technically, the required `Project` lookup needs the `Projects` list (S04.6, G2). |
| Permission Phase 1 (lockdown) | Owners group only (exists) | Owners group only (exists) |
| Permission Phase 2 (service grant) | **D-3** | **D-3** |
| Service connection | D-3 + ENV-D3 (S05.1) | D-3 + ENV-D3 (S05.1) |
| Flow use | S05.1, S05.4, decision AUD-F1 | S05.1, S05.4, S05.5 live, S04.3 rows, S04.6 rows (G2) |
| Production | PROD-01/G10, D-3, ENV-D3; IT-08 only for purge | PROD-01/G10, D-3, ENV-D3; EPIC 08 migration |
| Not a dependency | ENV-D2 (only ConfidentialAuditLog), G2, B-03 | ENV-D2 (`LegacyModifiedBy` stays gated) |

Phase 1 readiness:
- **AuditLog** can be provisioned before D-3 and ENV-D3.
- **TimesheetEntries** cannot:
  - the `Project` lookup target does not exist yet (S04.6 / G2);
  - backlog dependency S05.4 is not done. S05.4 orders the read-security work, not the columns. Changing that dependency is a project-owner decision and has not been made.

## AuditLog

**Columns:** exactly the audit-model columns (22).
- Required: `EventType`, `Action`, `Decision`, `ResultCode`, `OccurredOn` (UTC date-time) and `CorrelationId`.
- Owner and actor are numeric item IDs, with no lookups, so an audit row does not depend on another list.
- There are no retention columns. Retention stays `PENDING_IT_CUSTOMER_DECISION` (IT-08) and purge stays disabled.
- Versioning is on (T05.5.3). The version limit is the tenant policy (CL 5.8), not a number set here.

**Indexes:** derived from the query paths, at about 100k rows after 5 years.

| Column | Decision | Query |
|---|---|---|
| `OccurredOn` | REQUIRED | audit-viewer views (Today, Last 7 days, On-behalf, Approvals); retention purge |
| `CorrelationId` | REQUIRED | support lookup by the correlation ID shown with every error |
| `OwnerEmployeeItemId` | REQUIRED | viewer "By owner"; per-employee history |
| `TargetLegacyId` | RECOMMENDED | the trail of one record (created before load) |
| `EventType`, `Action`, `ActorUpn` | NOT REQUIRED | each is used only after `OccurredOn` or not at all. Low-cardinality values match more than 5,000 rows, so an index cannot make them threshold-safe. Not indexed for consistency (project owner 2026-10-07). |

**Append-only:**
- The flows only `POST /items` to AuditLog: no MERGE, no item URL, no delete (AL08–AL10).
- Every row the R1 flows append fits the schema (AL16):
  - only AuditLog columns;
  - required columns filled;
  - numbers, booleans and dates correctly typed;
  - an empty `WorkDate` is `null`, never `""`.

**Fixed while designing:**
- The guard's spike-era decision row does not fit AuditLog, because it has unknown columns and lacks the required ones. The R1 flows now write the audit-model `AuthorizationAllow` / `AuthorizationDeny` row instead.
- `WorkDate` is now `null` when absent.

**Permissions:**
- Phase 1: break inheritance without copying; Owners Full Control; no ordinary access.
- Auditor-group Read (S03.5 class W) is gated by the S12.7 audit viewer.
- Phase 2 (D-3): `TS Service` for the approved operational identity. It has Add, so it is sufficient for appending. It also has Edit and Override List Behaviors, which append-only does not need; see decision AUD-P1 below.

## TimesheetEntries

**Columns:** target data model §4.1.

| Group | Columns |
|---|---|
| Created by an R1 Phase 1 | 23 columns |
| Added by S07.2 (G5 PASS) | `ApprovedBy` — single line of text (255), the trusted approver UPN, **not** a Person column (project owner 2026-10-09); `ApprovedOn` — date and time, the server UTC instant. Written only by TS-Approve; empty while Draft and on legacy rows |
| Gated (not created) | `LegacyModifiedBy` (ENV-D2), `SortOrder` (S06.7), `LegacyApprovalInfo` / `DataQualityFlags` (EPIC 08) |

- `EntryStatus`:
  - Choice Draft / Approved / Deleted, default Draft;
  - `Rejected` is reserved and not provisioned;
  - soft delete = `Deleted`.
- No `ApprovalStatus`, `IsDeleted`, `RequestKey` (R1 create is non-idempotent by approved decision) or version column. The SharePoint ETag is the concurrency mechanism.
- `OwnerUpn` is the indexed ownership key. `Author` is metadata only.
- `WorkDate`:
  - date-only;
  - written as `yyyy-MM-dd` through the JSON item API;
  - read through the half-open UTC interval from `BusinessTimezone` (POC P4).
- Lookups: Employee, Project (both indexed, restrict delete), Shift, HourType, Phase, WorkType. `ProjectPhases` is not a lookup: the save flow validates the (Project, Phase) pair, so migrated rows stay valid.
- Every column the save flow writes exists, and every required column is written on create (TE13).
- Migration (EPIC 08, not now): legacy `Lock` maps to Approved; empty or absent maps to Draft. No legacy value maps to Deleted (the D-Q1 rows are evidence only), and any other value is refused.

**Indexes:** 8 (the target had 9).

| Column | Decision | Query |
|---|---|---|
| `OwnerUpn` | REQUIRED | R1 read and the same-day check (security first filter) |
| `WorkDate` | REQUIRED | views `Recent` / `PendingRecent` (S06.1 AC2) |
| `LegacyId` | REQUIRED | unique key, migration upsert |
| `Employee`, `Project` | REQUIRED | restrict-delete relationships need an indexed lookup |
| `EmployeeItemId`, `PeriodKey` | REQUIRED | person × period queries; `ByPeriod` |
| `DisciplineCode` | RECOMMENDED | EPIC 07 approval scoping. That query must put `PeriodKey` first. |
| `EntryStatus` | **NOT REQUIRED** | No query filters it first. R1 uses `ne 'Deleted'` after `OwnerUpn`, and `ne` cannot use an index. With 3 values, each matches more than 5,000 rows, so an index cannot make a status-first query threshold-safe. P5-06/07 will confirm this live. |

**Permissions:**
- Phase 1: break inheritance without copying; Owners Full Control; no direct human read or write (class P, proxy-only).
- Phase 2 (D-3): `TS Service` gives Read / Add / Edit without Delete. It is sufficient; the only right beyond what the flows need is Override List Behaviors.

## Open decisions found

Options and recommendations for AUD-F1, AUD-P1 and the unbounded read: `docs/auditlog-open-decisions.md`.

- **AUD-F1 (critical before R1 live) — audit append failure.** Today the flows fail closed (AL17):
  - if the decision append fails, the run stops before any write;
  - if the WriteProxy append fails *after* a persisted write, the caller gets no response. A retry can then duplicate a create, because R1-Q3 is open.

  The specification does not decide this. Options:
  - keep fail-closed;
  - respond OK with a warning and alert operations;
  - retry the append.
- **AUD-P1 — append-only service level.** `TS Service` can edit audit rows. A stricter level (View + Add, no Edit) would enforce append-only in SharePoint itself. Today it is enforced by the flow design plus version history.
- **Index targets — approved by the project owner 2026-10-07** (supersede the earlier 7 / 9):
  - AuditLog: exactly 4 indexes (`OccurredOn`, `CorrelationId`, `OwnerEmployeeItemId`, `TargetLegacyId`);
  - TimesheetEntries: 8 indexes; `EntryStatus` NOT REQUIRED FOR CURRENT R1 TARGET / REVISIT AFTER P5 IF NEEDED (P5 not run).
- **Findings for the flows (2026-10-07):**
  - the WriteProxy row now stamps `TargetLegacyId` (the stored record's `LegacyId`) — fixed;
  - the discipline is read through the required `Discipline` lookup; an employee without one gets `CONFIG_INVALID` before any write — fixed;
  - a no-date `TS-ReadOwn` for an owner with more than 5,000 entries would hit the threshold. RESOLVED: the API now requires FromDate + ToDate (`VALIDATION_DATE` otherwise; OFFLINE-READOWN-GAP-FIX-01).

## Phased live plans

Status 2026-10-07: **AuditLog Phase 1 (schema + lockdown) applied on STAGING** — 48/48 requests, post-live reconciliation 0
operations, unique permissions = site administrator + Owners Full Control only, no service grant (AUD-P1 open). All other
plans below are not executed.

| Plan | Mutating REST calls | Second run |
|---|---|---|
| AuditLog Phase 1 schema | 46 POST: create list 1, Title 2, 21 columns × 2, versioning 1 | 0 |
| AuditLog Phase 1 lockdown | 2 POST (break inheritance without copy; Owners Full Control) | 0 |
| AuditLog Phase 2 (after AUD-P1) | 1 POST (the AUD-P1 level for the configured operational identity) | 0 |
| TimesheetEntries Phase 1 schema (when S04.6 / S05.4 allow) | 49 POST + 6 GET (lookup list IDs) | 0 |
| TimesheetEntries Phase 1 lockdown | 2 POST | 0 |
| TimesheetEntries Phase 2 (after Phase 1) | 1 POST (TS Service for the configured operational identity) | 0 |

Rollback categories (`schema_reconcile.ROLLBACK`):
- an empty list is reversible;
- a column is reversible with data risk (its internal name is fixed for ever);
- indexes are reversible;
- a permission change is reversed by re-inheriting.
