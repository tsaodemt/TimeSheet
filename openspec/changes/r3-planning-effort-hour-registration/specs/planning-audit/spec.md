## ADDED Requirements

### Requirement: Authorization decision audit
Every planning flow call SHALL append exactly one `AuthorizationAllow` or `AuthorizationDeny` row (capability, result
code, trusted actor, correlation id) before any business read or write; if that append fails, the call SHALL end with
INTERNAL_ERROR and no business write.

#### Scenario: Denied save
- **WHEN** a viewer calls `REG-SaveMatrix`
- **THEN** exactly one AuthorizationDeny row with ROLE_NOT_ALLOWED exists for that correlation id and no WriteProxy row

### Requirement: Change audit exactly once
Each created, changed or cleared planning value SHALL produce exactly one `WriteProxy` row (Action Create / Update /
Clear) carrying actor (trusted UPN), business scope (project, phase, discipline, owner where applicable), target item,
old → new value summary (`ChangeJson`, including the approved blank/value representation where applicable) and the shared correlation id; unchanged cells
(NO_CHANGE) SHALL produce no WriteProxy row. A failed audit append after a committed write SHALL follow the existing
AUDIT_DEGRADED rule (success kept, warning returned, run marked failed for alerting, no retry).

#### Scenario: Three changed cells
- **WHEN** a save changes 3 cells (one create, one update, one clear)
- **THEN** exactly 3 WriteProxy rows exist with Actions Create, Update, Clear and old/new values

### Requirement: Approval audit exactly once; lock is resulting state
An effort approval SHALL write exactly one `Approval` business-event row per approved item. The event SHALL record the resulting immutable state (`Approved` / locked semantics) in its change/result payload. A separate `Lock` business event SHALL NOT be emitted unless a future approved workflow introduces an independent Lock operation. Refusals SHALL write the normal AuthorizationDeny row with the typed result code. `Unlock` SHALL stay disabled until OD-18; no administrative override event SHALL exist unless a decision creates that capability.

#### Scenario: Approve two rows
- **WHEN** the Chủ trì approves 2 Draft rows in one request
- **THEN** each row has exactly one Approval business event sharing the request correlation id, and each event records the resulting locked/Approved state

### Requirement: No sensitive data in audit
Audit rows SHALL NOT contain salary, rate or cost values, tokens, or free-text personal data beyond the identifiers above.

#### Scenario: Audit content check
- **WHEN** the audit rows of a planning test run are inspected
- **THEN** no rate, salary or cost field is present
