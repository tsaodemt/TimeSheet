## ADDED Requirements

### Requirement: Discipline effort registration (NR-EFF-02)
Discipline staff (employees and the Chủ trì) SHALL register discipline effort per project and task through a guarded
flow, only for their own discipline. Task meaning (OD-29), ownership grain (OD-30), unit (OD-14) and period (OD-23)
SHALL be implemented as decided; until then BLOCKED (M3).

#### Scenario: Other discipline denied
- **GIVEN** a staff member of discipline Điện
- **WHEN** they register effort for discipline BIM
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

### Requirement: Allocation ceiling (NR-EFF-03)
The total registered discipline effort SHALL NOT exceed the applicable A.I.3 allocation; the comparison scope SHALL be the
one decided by OD-15, and equality rules by OD-32. The check SHALL run server-side, concurrency-safe, at write time.

#### Scenario: Over the ceiling
- **GIVEN** a remaining allocation of 10 in the decided scope
- **WHEN** a registration of 12 is saved
- **THEN** the response is OVER_CEILING with the remaining value and nothing is written

#### Scenario: Concurrent registrations
- **GIVEN** a remaining allocation of 10
- **WHEN** two users save 6 each at the same time
- **THEN** exactly one succeeds and the other receives CONFLICT or OVER_CEILING; the stored total never exceeds 10

### Requirement: Chủ trì approval locks registered effort (NR-EFF-04)
The Chủ trì (as decided by OD-17) SHALL approve Draft registrations in scope; approval SHALL lock the row (Approved is
immutable for every role). Self-approval SHALL follow OD-28; approval order SHALL follow OD-27.

#### Scenario: Approved row is locked
- **GIVEN** an Approved registration
- **WHEN** any role tries to change or clear it
- **THEN** the response is LOCKED and the row is unchanged

#### Scenario: Non-Chủ trì cannot approve
- **WHEN** a staff member without the Chủ trì capability approves a row
- **THEN** the response is ROLE_NOT_ALLOWED and no Approval audit row with ALLOW exists

### Requirement: Chủ trì approval locks actual effort (NR-EFF-06)
Actual effort approved by the Chủ trì SHALL be immutable for every role, with the actual-effort source per OD-19 and the
Approved/Draft rule per OD-33. If OD-19 selects the timesheet, the interaction with the closed EPIC 07 approval roles
SHALL be resolved by decision before implementation.

#### Scenario: Approved actual is immutable
- **GIVEN** an approved actual effort record
- **WHEN** its owner edits it
- **THEN** the response is LOCKED

### Requirement: Unlock is not available until decided
No unlock or reopen operation SHALL exist until OD-18 is decided; the `Unlock` audit event stays disabled.

#### Scenario: Unlock request before decision
- **WHEN** any client requests an unlock
- **THEN** the response is UNKNOWN_ACTION and nothing changes
