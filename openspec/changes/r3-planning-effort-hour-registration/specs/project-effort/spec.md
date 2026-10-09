## ADDED Requirements

### Requirement: PM project effort registration (NR-EFF-01)
The system SHALL let the project's authoritative PM (OD-24) register Project Effort for the recipient categories named in the customer document (Quản lý phòng, PM and the disciplines điện, lạnh, nước, BIM) through a guarded flow. Values SHALL be entered manually by the PM (OD-16): no formula, no derivation from finance data and no import. The grain SHALL be project × recipient with no phase dimension (OD-22) and one project-lifetime value per recipient with no period dimension or registration window (OD-23); every change SHALL be audited. `QuanLyPhong` is a recipient category for A.I storage; OD-31 is required later for mapping that category to a human role/person in B.III reporting, not to create the A.I row.

#### Scenario: Only the project's PM registers
- **GIVEN** user P is the authoritative PM of project A but not of project B
- **WHEN** P saves an allocation for project B
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

#### Scenario: One lifetime value per recipient
- **WHEN** the PM saves 12.5 for recipient BIM of project A and later changes it to 14
- **THEN** project A has exactly one BIM value (14), with no phase or period key, and both changes are audited

### Requirement: Authoritative project PM (OD-24)
Each project SHALL have at most one authoritative PM, a person identified by a stable employee key and stored with the project. Only PMO SHALL set, change or remove it, through a guarded and audited flow. The server SHALL resolve the PM from this stored value; a client-supplied PM, role or scope claim SHALL be ignored. PMO and Executive SHALL NOT edit allocations merely by role. A project without a PM SHALL NOT be editable by anyone.

#### Scenario: PMO designates the PM
- **WHEN** a PMO user sets employee P as PM of project A
- **THEN** P can save project A's allocations, the change is audited, and the previous PM (if any) can no longer save them

#### Scenario: Non-PMO cannot designate
- **WHEN** an Executive or Team Leader user tries to set the PM of a project
- **THEN** the response is ROLE_NOT_ALLOWED and nothing is written

#### Scenario: PMO without designation cannot edit allocations
- **GIVEN** PMO user Q is not the PM of project A
- **WHEN** Q saves an allocation for project A
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

### Requirement: Project effort visibility (OD-37)
Project Effort data (planned values and the project-level Approved actual total) SHALL be visible only to the project's authoritative PM (own projects), PMO (all projects) and Executive (all projects). Every other role SHALL be denied server-side. This SHALL NOT inherit the legacy Hour Registration visibility (OD-05). Team Leader and Quản lý phòng visibility is not granted here (EPIC 17: OD-46; reporting: OD-31). Existing Timesheet read rules are unchanged.

#### Scenario: Other roles denied
- **WHEN** a Team Leader, HR, Finance or Employee user (not the project's PM) reads project A's Project Effort
- **THEN** the response is ROLE_NOT_ALLOWED or SCOPE_NOT_ALLOWED and no data is returned

#### Scenario: PM sees own projects only
- **GIVEN** P is the PM of project A only
- **WHEN** P reads project B's Project Effort
- **THEN** the response is SCOPE_NOT_ALLOWED

### Requirement: Project effort unit is the man-day (OD-14)
Project Effort SHALL be stored and handled in man-days (business and storage unit; OD-14 resolved by owner decision 2026-10-10) with at most 2 decimal places. Input with more than 2 decimal places SHALL be rejected with the typed validation error `VALIDATION_VALUE` and SHALL NOT be rounded, truncated or silently normalised. OD-14 applies to EPIC 16 only; it SHALL NOT set the EPIC 17 unit (OD-45). Conversion from Timesheet hours SHALL use the approved `HoursPerManDay` setting. EPIC 16 SHALL use its own schema; the man-day unit SHALL NOT be a reason to reuse the M1 schema or storage. This requirement does not authorise EPIC 18 implementation.

#### Scenario: Unit is explicit
- **WHEN** an allocation is saved
- **THEN** it is stored in man-days with at most 2 decimals and the unit `man-day` is exposed to the reporting contract

#### Scenario: Excess precision is rejected
- **WHEN** the PM saves 1.255 for a recipient
- **THEN** the response is VALIDATION_VALUE, nothing is written and no rounded or truncated value (1.25 / 1.26) is stored

### Requirement: Project effort value bounds (OD-44)
Project Effort SHALL accept numeric values with minimum 0 (OD-44 resolved by owner decision 2026-10-10). Negative values SHALL be denied with the typed validation error `VALIDATION_VALUE`. There SHALL be no business maximum; no arbitrary upper limit SHALL be configured or validated. Validation SHALL run server-side (client-side validation is a convenience only). The platform numeric range (IEEE-754 double, about 15 significant digits, in SharePoint Number columns and Power Fx) is a TECHNICAL_LIMIT, not a business rule.

#### Scenario: Negative value denied
- **WHEN** the PM saves -1 for a recipient
- **THEN** the response is VALIDATION_VALUE and nothing is written

#### Scenario: Zero and large values accepted
- **WHEN** the PM saves 0 for one recipient and 250000.5 for another
- **THEN** both are stored exactly as entered

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
Actual project effort SHALL be derived from the existing `TimesheetEntries` (OD-19 resolved by owner decision 2026-10-10). R3 SHALL NOT create a new actual-effort entry list, a duplicate actual-effort workflow or a new employee actual-effort entry screen. The existing Timesheet semantics SHALL be preserved unchanged: trusted actor identity, the business owner / Employee relationship, existing authorised on-behalf editing, existing entry status semantics and the existing security model; no existing Timesheet function SHALL be restricted. Caller-supplied owner identity SHALL never be trusted. OD-19 fixes the source only. Only `TimesheetEntries` in the Approved state SHALL count as actual effort (OD-33 resolved = Approved only); Draft and other states SHALL be excluded. Actual effort in man-days SHALL be computed by the reporting/query contract as Σ Approved hours ÷ `HoursPerManDay`; `TimesheetEntries` SHALL NOT be rewritten. OD-41 is NOT_APPLICABLE.

#### Scenario: Forged owner is never trusted
- **WHEN** a caller submits another person's identity as an actual-effort owner claim
- **THEN** the server ignores that claim and resolves the business owner from the existing server-side Timesheet ownership/scope rule; it never writes merely because the client supplied the identity

#### Scenario: Actual effort is converted, not stored
- **GIVEN** project A has 20 Approved and 8 Draft Timesheet hours, with `HoursPerManDay` = 8
- **WHEN** the contract computes actual effort for project A
- **THEN** the result is 2.50 man-days (Draft hours excluded) and no `TimesheetEntries` item is created or changed

#### Scenario: Existing on-behalf entry still works
- **GIVEN** a user authorised today to edit another employee's timesheet
- **WHEN** EPIC 16 is deployed
- **THEN** that on-behalf edit behaves exactly as before
