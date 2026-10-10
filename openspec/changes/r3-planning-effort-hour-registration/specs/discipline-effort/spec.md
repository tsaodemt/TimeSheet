## ADDED Requirements

### Requirement: Discipline effort registration (NR-EFF-02)
An employee (including a Team Leader acting as an employee) SHALL register planned discipline effort for themselves through a guarded
flow. The canonical allocation SHALL be Employee × Project × WorkType (OD-30): the WorkType SHALL be an active item of the existing
`WorkTypes` master referenced by its stable LegacyId (OD-29; no Task entity); the discipline SHALL be derived from the caller's
authoritative Employees row and stored as a snapshot, never taken from the request. Values SHALL be stored in man-days (OD-45 resolved from rev01) with at most
2 decimals (more rejected with VALIDATION_VALUE, never rounded or truncated), minimum 0, no business maximum, blank (not registered)
distinct from explicit 0 (OD-47), one project-lifetime value per allocation with no period dimension (OD-48). An employee SHALL edit
only their own Draft rows; no stored or editable discipline total SHALL exist.

#### Scenario: Forged discipline ignored
- **GIVEN** an employee of discipline Điện
- **WHEN** they save an allocation with a request claiming discipline BIM
- **THEN** the row is stored with discipline Điện from the Employees row and the claim is only logged as ignored

#### Scenario: Another employee's Draft
- **WHEN** a Team Leader saves a change to another employee's Draft row
- **THEN** the response is SCOPE_NOT_ALLOWED and nothing is written

#### Scenario: Inactive WorkType for a new row
- **WHEN** an employee creates a row with an inactive WorkType
- **THEN** the response is VALIDATION_LOOKUP and nothing is written

### Requirement: Allocation ceiling (NR-EFF-03)
For discipline D in project P, the sum of every non-blank registration of D in P (Draft and ApprovedLocked) SHALL NOT exceed (≤, OD-32)
the A.I.3 value of recipient `D:<D>` of P (project lifetime, OD-15). A blank A.I.3 value means "not registered": saving a VALUE is refused
with CEILING_NOT_REGISTERED. The check SHALL run server-side on the proposed state, serialised per Project × Discipline (concurrency-safe),
and a refusal writes nothing (OD-27).

#### Scenario: Below, exact, above
- **GIVEN** A.I.3 = 10 for D in P and 4 already registered by another employee of D
- **WHEN** an employee saves 5, then 6, then 7 for their own row
- **THEN** 5 and 6 are saved (6 reaches exactly 10) and 7 is refused with OVER_CEILING and nothing is written

#### Scenario: Concurrent registrations
- **GIVEN** a remaining allocation of 10
- **WHEN** two employees of D save 6 each at the same time
- **THEN** at most one succeeds; the other receives CONFLICT or OVER_CEILING; the stored total never exceeds 10

### Requirement: Chủ trì approval locks registered effort (NR-EFF-04)
The Chủ trì SHALL be a Team Leader acting for the discipline of their authoritative Employees row (OD-17). Approval SHALL be the single
stage Draft → ApprovedLocked (OD-27): no submit, no PM / PMO / Executive / second-stage approval, no separate Lock event. Approval SHALL
revalidate identity, role, discipline, project, ceiling and ETag server-side and write exactly one Approval audit event per approved row.
A Team Leader MAY approve their own registration of the same discipline (OD-28, EPIC 17 only). ApprovedLocked rows SHALL be immutable
for every role; no reopen, unapprove or unlock exists (OD-18) and no revision model (OD-34).

#### Scenario: Cross-discipline approval refused
- **WHEN** a Team Leader of Lạnh approves a Draft row of discipline Điện
- **THEN** the response for that row is SCOPE_NOT_ALLOWED and it stays Draft

#### Scenario: Self-approval in EPIC 17
- **GIVEN** a Team Leader's own Draft row of their discipline within the ceiling
- **WHEN** the same Team Leader approves it
- **THEN** it becomes ApprovedLocked with one Approval audit event

#### Scenario: EPIC 07 self-approval unchanged
- **WHEN** a Team Leader approves their own TimesheetEntries row through TS-Approve
- **THEN** the existing EPIC 07 refusal applies (self-approval denied)

#### Scenario: Approved row is locked
- **GIVEN** an ApprovedLocked registration
- **WHEN** any role tries to change or clear it
- **THEN** the response is LOCKED and the row is unchanged

### Requirement: Discipline effort visibility (OD-46)
Reads SHALL return only: the caller's own rows (Employee); every row of the caller's discipline (Team Leader); every row of projects where
the caller is the authoritative EPIC 16 PM; every row (PMO, Executive). Approver, HR, Salary Viewer, Finance, App Administrator, IT Support,
Confidential Owner and Migration Owner SHALL be denied. An editor additionally receives the aggregate ceiling / used / remaining of their
own discipline (totals only). This SHALL NOT be inherited from OD-05 or OD-37.

#### Scenario: Employee sees own rows only
- **GIVEN** employees A and B of discipline Điện with rows in project P
- **WHEN** A reads P
- **THEN** only A's rows and the Điện totals are returned

### Requirement: Actual effort lock is the existing timesheet approval (NR-EFF-06, OD-49)
The A.III "Chủ trì => khóa công thực hiện" SHALL be the existing Timesheet approval (EPIC 07); EPIC 17 SHALL NOT add a second approval or
lock of actual effort and SHALL NOT store actual effort. Actual effort shown in EPIC 17 SHALL be Σ Approved TimesheetEntries hours of the
project and discipline ÷ `HoursPerManDay` (OD-19, OD-33), totals only.

#### Scenario: Approved actual per discipline
- **GIVEN** Approved and Draft timesheet hours of discipline D in project P
- **WHEN** the discipline totals are read
- **THEN** only the Approved hours count and no Timesheet row is returned

### Requirement: No reopen in current R3 (OD-18)
No reopen, unapprove or unlock operation SHALL exist for discipline effort; the `Unlock` audit event stays disabled.

#### Scenario: Unlock request
- **WHEN** any client requests an unlock
- **THEN** no flow exists for it and an ApprovedLocked row stays unchanged
