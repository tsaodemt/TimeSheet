## ADDED Requirements

### Requirement: Discipline effort registration (NR-EFF-02)
Discipline staff (employees and the Chủ trì) SHALL register discipline effort per project and task through a guarded
flow, only for their own discipline. Values SHALL be stored in man-days (OD-45 resolved by evidence: rev01 compares them directly with the A.I.3 man-days).
Task meaning (OD-29), ownership grain (OD-30), time dimension (OD-48) and value domain (OD-47) SHALL be implemented as decided; until then BLOCKED (M3).

#### Scenario: Other discipline denied
- **GIVEN** a staff member of discipline Điện
- **WHEN** they register effort for discipline BIM
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

### Requirement: Allocation ceiling (NR-EFF-03)
For discipline D in project P, the total registered effort of D in P SHALL NOT exceed (≤; equality not required, OD-32 resolved)
the A.I.3 value of recipient `D:<D>` of P, a project-lifetime value (OD-15 resolved by evidence). Which registration states count and
the behaviour on a blank A.I.3 value SHALL follow OD-27. The check SHALL run server-side, concurrency-safe, at write time.

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

### Requirement: Actual effort lock is the existing timesheet approval (NR-EFF-06, OD-49)
The A.III "Chủ trì => khóa công thực hiện" SHALL be the existing Timesheet approval (EPIC 07: Approved entries are locked); EPIC 17
SHALL NOT add a second approval or lock of actual effort (OD-49 resolved by evidence from OD-19 and OD-33). Actual effort counts
Approved TimesheetEntries only (OD-33) and existing Timesheet behaviour SHALL NOT be restricted.

#### Scenario: Approved timesheet entry is locked
- **GIVEN** a TimesheetEntries row approved through the existing approval
- **WHEN** its owner edits it
- **THEN** the response is LOCKED (existing EPIC 07 behaviour) and EPIC 17 creates no other approval state

### Requirement: Unlock is not available until decided
No unlock or reopen operation SHALL exist until OD-18 is decided; the `Unlock` audit event stays disabled.

#### Scenario: Unlock request before decision
- **WHEN** any client requests an unlock
- **THEN** the response is UNKNOWN_ACTION and nothing changes
