## ADDED Requirements

### Requirement: Guarded write path
Every planning write (HourRegistrations and every EPIC 16/17 list) SHALL go through a guarded Power Automate flow
running as the service identity; Canvas SHALL NOT bind or write any planning list; ordinary users SHALL have no direct read or write permission on protected planning lists; reads and writes SHALL go through guarded flows according to capability. No item-level unique permissions SHALL be created; the service SHALL keep View/Add/Edit only
(no Delete, D-7).

#### Scenario: Direct list write by a user
- **WHEN** an ordinary user calls the SharePoint REST API to update a planning list item
- **THEN** the call is denied (403/404) and the item is unchanged

#### Scenario: Canvas data sources
- **WHEN** the Canvas app source is inspected
- **THEN** no planning list appears as a data source

#### Scenario: Direct list read by a user
- **WHEN** an ordinary user, including one who can view planning data through the app, calls SharePoint REST directly against a protected planning list
- **THEN** the list/item read is denied (403/404); authorised viewing is available only through the guarded read flow

### Requirement: Trusted identity and untrusted claims
Each flow SHALL resolve the caller from the platform identity (not from inputs), map it to one active Employees row,
and SHALL ignore client-provided UPN, role, scope, discipline, project, owner, approver and status values (logged by
name only).

#### Scenario: Forged discipline
- **WHEN** a staff member of discipline Điện sends `DisciplineCode=BIM` with a registration
- **THEN** the server uses Điện from the Employees row and refuses the BIM target with SCOPE_NOT_ALLOWED

### Requirement: Capability matrix
Authorisation SHALL use named capabilities granted by role (union of roles), checked server-side before any read or
write. The proposed matrix below is NOT approved; OPEN_DECISION cells SHALL be resolved before the milestone that uses
them; technical administration SHALL NOT imply business authority.

| Capability | EMP | TL | APR | EXE | PMO | HR | SALV | FIN | ADM | ITS | CONFO | MIGO |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `REG.View` view Hour Registration (OD-05 resolved, legacy parity) | DENY | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | DENY | DENY | DENY | ALLOW | DENY | DENY |
| `REG.Edit` edit / clear / save matrix (OD-04 resolved) | DENY | DENY | DENY | ALLOW | ALLOW | DENY | DENY | DENY | DENY | DENY | DENY | DENY |
| `EFF.ProjectView` view project planned effort (OD-37) | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | OPEN_DECISION | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.ProjectEdit` edit project planned effort (OD-24) | DENY | DENY | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | DENY | DENY | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.ProjectApprove` project planned-effort approval | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE |
| `EFF.DisciplineView` view discipline allocation / registration (OD-37) | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | DENY | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.DisciplineEdit` register discipline effort (OD-30) | OPEN_DECISION | OPEN_DECISION | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.DisciplineApprove` approve discipline effort = lock (OD-17) | DENY | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | DENY | DENY | DENY | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.ActualView` view actual effort (OD-19, OD-37) | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | OPEN_DECISION | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.ActualApprove` approve actual effort (OD-17, OD-19) | DENY | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | DENY | DENY | DENY | DENY | DENY | DENY | NOT_APPLICABLE |
| `EFF.Unlock` unlock / reopen (OD-18) | DENY | OPEN_DECISION | OPEN_DECISION | OPEN_DECISION | DENY | DENY | DENY | DENY | DENY | DENY | DENY | NOT_APPLICABLE |
| Planning configuration (AppSettings keys, e.g. unit, period windows) | DENY | DENY | DENY | DENY | DENY | DENY | DENY | DENY | ALLOW (configuration only) | DENY | DENY | NOT_APPLICABLE |

`REG.Edit`: OD-04 resolved (Executive, PMO). `REG.View`: OD-05 resolved by owner decision = legacy parity (legacy read Manager, Leader, IT, HRD + writers → Team Leader, Approver, IT Support, HR, Executive, PMO; full role table in `decisions.md`). App Administrator has no business VIEW/EDIT (technical role); Migration Owner has none.
has no business capability. Legacy Director is retired (no mapping). A.I project allocation has no approval capability in current scope (resolved OD-26). Self-approval of discipline/actual effort: OD-28.

#### Scenario: Matrix is machine-checked
- **WHEN** the capability tests run
- **THEN** every role × capability cell yields ALLOW or DENY exactly as approved, with 0 unexpected allow and 0 unexpected deny

#### Scenario: AppAdmin has no business authority
- **WHEN** a user who is only App Administrator saves a hour registration or approves effort
- **THEN** the response is ROLE_NOT_ALLOWED unless an approved decision grants that capability

### Requirement: Scopes
Scopes SHALL be enforced server-side: discipline scope from the caller's Employees row; project scope only after OD-24 /
OD-17 define how a person is tied to a project (the current guard has self, discipline and company scopes only — a
project scope is new work and SHALL be specified before M2/M3).

#### Scenario: Cross-project write
- **GIVEN** a project scope is defined and user P is not assigned to project B
- **WHEN** P writes planning data of project B
- **THEN** the response is SCOPE_NOT_ALLOWED
