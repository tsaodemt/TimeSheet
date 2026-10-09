## ADDED Requirements

### Requirement: PM project effort registration (NR-EFF-01)
The system SHALL let the project's PM register project effort for the recipient categories named in the customer document (Quản lý phòng, PM and the disciplines điện, lạnh, nước, BIM) through a guarded flow. The PM definition (OD-24), unit (OD-14), phase granularity (OD-22), period (OD-23), input source (OD-16) and allocation blank/zero semantics (OD-40) SHALL be implemented exactly as decided; until those blocking decisions are closed this requirement is BLOCKED (M2). `QuanLyPhong` is a recipient category for A.I storage; OD-31 is required later for mapping that category to a human role/person in B.III reporting, not to create the A.I row.

#### Scenario: Only the project's PM registers
- **GIVEN** OD-24 is decided and user P is the PM of project A but not of project B
- **WHEN** P saves an allocation for project B
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

#### Scenario: Unit is explicit
- **WHEN** an allocation is saved
- **THEN** it is stored in the unit decided by OD-14 and the source unit is exposed to the reporting-normalisation contract

### Requirement: Allocation blank and zero
Allocation blank/zero semantics SHALL follow OD-40 and SHALL NOT be inherited from legacy Hour Registration merely because both concepts are called "Đăng ký công".

#### Scenario: Zero handling follows the approved rule
- **GIVEN** OD-40 has been decided
- **WHEN** the PM saves or clears a recipient allocation
- **THEN** the stored state and displayed state match OD-40 exactly

### Requirement: No A.I approval workflow in current scope
NR-EFF-01 defines registration but no approval/lock for A.I. The current R3 scope SHALL NOT create an `EFF.ProjectApprove` capability, queue or flow. A later customer request to add A.I approval SHALL require a new explicit decision/spec delta.

#### Scenario: Successful save is effective
- **WHEN** an authorised PM successfully saves an A.I allocation
- **THEN** the allocation is effective immediately and no project-allocation approval queue item or Approval audit event is created

### Requirement: Link to legacy hour registration
Project effort SHALL be stored separately from `HourRegistrations` unless OD-25 decides otherwise; if OD-25 decides that legacy values seed the allocation, the seed SHALL be an audited, one-time, reconcilable operation.

#### Scenario: Separate until decided
- **WHEN** a legacy budget cell changes
- **THEN** no project effort allocation changes unless OD-25 defines a link

### Requirement: Actual project effort boundary (NR-EFF-05)
Actual effort SHALL come from the source decided by OD-19 (timesheet-derived, separate registration or hybrid; `design.md` §10). Caller-supplied owner identity SHALL never be trusted. If OD-19 selects existing `TimesheetEntries`, R3 SHALL preserve the existing trusted owner/on-behalf authorisation semantics of the live timesheet path and SHALL NOT narrow them to caller-only ownership. If OD-19 selects a separate or hybrid actual-entry list, ownership/on-behalf semantics SHALL follow OD-41 before implementation.

#### Scenario: Forged owner is never trusted
- **WHEN** a caller submits another person's identity as an actual-effort owner claim
- **THEN** the server ignores that claim and resolves the business owner from the approved server-side ownership/scope rule; it never writes merely because the client supplied the identity
