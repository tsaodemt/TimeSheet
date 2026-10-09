## ADDED Requirements

### Requirement: PM project effort registration (NR-EFF-01)
The system SHALL let the project's PM register project effort for the recipient categories named in the customer document (Quản lý phòng, PM and the disciplines điện, lạnh, nước, BIM) through a guarded flow. The PM definition (OD-24), phase granularity (OD-22), period (OD-23) and input source (OD-16) SHALL be implemented exactly as decided; until those blocking decisions are closed this requirement is BLOCKED (M2). Unit and blank/zero semantics are decided (OD-14, OD-40; requirements below). `QuanLyPhong` is a recipient category for A.I storage; OD-31 is required later for mapping that category to a human role/person in B.III reporting, not to create the A.I row.

#### Scenario: Only the project's PM registers
- **GIVEN** OD-24 is decided and user P is the PM of project A but not of project B
- **WHEN** P saves an allocation for project B
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

### Requirement: Project effort unit is the man-day (OD-14)
Project Effort SHALL be stored and handled in man-days (business and storage unit; OD-14 resolved by owner decision 2026-10-10) with at most 2 decimal places. A value with more than 2 decimal places SHALL be refused server-side, not silently rounded. Conversion from Timesheet hours SHALL use the approved `HoursPerManDay` setting. EPIC 16 SHALL use its own schema; the man-day unit SHALL NOT be a reason to reuse the M1 schema or storage. This requirement does not authorise EPIC 18 implementation.

#### Scenario: Unit is explicit
- **WHEN** an allocation is saved
- **THEN** it is stored in man-days with at most 2 decimals and the unit `man-day` is exposed to the reporting contract

#### Scenario: Excess precision is refused
- **WHEN** the PM saves 1.255 for a recipient
- **THEN** the response is VALIDATION_VALUE and nothing is written

### Requirement: Allocation blank and zero (OD-40)
A recipient allocation SHALL distinguish BLANK (not registered) from numeric 0 (explicitly registered zero) as distinct business states (OD-40 resolved by owner decision 2026-10-10). Blank SHALL NOT be coerced to 0 on save, read, display or contract export. The storage representation SHALL be designed in the EPIC 16 schema and SHALL NOT be inferred from legacy Hour Registration (OD-01 is a separate decision).

#### Scenario: Explicit zero is kept
- **WHEN** the PM saves 0 for a recipient and reloads
- **THEN** the recipient shows the value 0 and the persisted state is "registered zero"

#### Scenario: Blank stays not registered
- **GIVEN** a recipient for which nothing has been registered
- **WHEN** the allocation is read
- **THEN** it is returned and shown as blank (not registered), never as 0

#### Scenario: Clearing returns to not registered
- **GIVEN** a recipient with a registered value
- **WHEN** the PM clears the value and saves
- **THEN** the recipient is blank (not registered), not 0

### Requirement: No A.I approval workflow in current scope
NR-EFF-01 defines registration but no approval/lock for A.I. The current R3 scope SHALL NOT create an `EFF.ProjectApprove` capability, queue or flow. A later customer request to add A.I approval SHALL require a new explicit decision/spec delta.

#### Scenario: Successful save is effective
- **WHEN** an authorised PM successfully saves an A.I allocation
- **THEN** the allocation is effective immediately and no project-allocation approval queue item or Approval audit event is created

### Requirement: Separate from legacy hour registration
Project effort SHALL be stored separately from `HourRegistrations` (OD-25 resolved = separate capability): no shared
entity, field, key or workflow, and no automatic seeding from legacy budget cells. Both use the man-day; that SHALL NOT
link Project Effort values to legacy budget values or justify reusing legacy budget fields. A later seeding request SHALL
require a new explicit decision and spec delta.

#### Scenario: Legacy budget change does not touch project effort
- **WHEN** a legacy budget cell changes
- **THEN** no project effort allocation changes

### Requirement: Actual project effort from existing timesheet entries (NR-EFF-05, OD-19)
Actual project effort SHALL be derived from the existing `TimesheetEntries` (OD-19 resolved by owner decision 2026-10-10). R3 SHALL NOT create a new actual-effort entry list, a duplicate actual-effort workflow or a new employee actual-effort entry screen. The existing Timesheet semantics SHALL be preserved unchanged: trusted actor identity, the business owner / Employee relationship, existing authorised on-behalf editing, existing entry status semantics and the existing security model; no existing Timesheet function SHALL be restricted. Caller-supplied owner identity SHALL never be trusted. Actual effort in man-days SHALL be computed by the approved reporting/query contract as Timesheet hours ÷ `HoursPerManDay` over the entry statuses fixed by OD-33 (M3); `TimesheetEntries` SHALL NOT be rewritten. OD-41 is NOT_APPLICABLE.

#### Scenario: Forged owner is never trusted
- **WHEN** a caller submits another person's identity as an actual-effort owner claim
- **THEN** the server ignores that claim and resolves the business owner from the existing server-side Timesheet ownership/scope rule; it never writes merely because the client supplied the identity

#### Scenario: Actual effort is converted, not stored
- **GIVEN** 20 counted Timesheet hours on project A and `HoursPerManDay` = 8
- **WHEN** the contract computes actual effort for project A
- **THEN** the result is 2.50 man-days and no `TimesheetEntries` item is created or changed

#### Scenario: Existing on-behalf entry still works
- **GIVEN** a user authorised today to edit another employee's timesheet
- **WHEN** EPIC 16 is deployed
- **THEN** that on-behalf edit behaves exactly as before
