## ADDED Requirements

### Requirement: Project selection
The Hour Registration screen SHALL let a user with `REG.View` filter projects by year ("All" by default; years taken
from project data, not a hard-coded list) and select one project through a single picker that shows code and name and
is keyed by project id. Duplicate project codes SHALL NOT cause another project's data to be shown or saved (LHR-03,
LHR-05, LHR-06). A year with no projects SHALL clear the selection and the matrix (LHR-04). Listing of inactive or
closed projects SHALL follow OD-07; assignment scoping SHALL follow OD-06.

#### Scenario: Duplicate code resolves by id
- **GIVEN** two projects share the code "X" with different phase lists
- **WHEN** the user selects the second project
- **THEN** the matrix shows the second project's phases and a save writes only items keyed by the second project's id

#### Scenario: Empty year
- **WHEN** the user picks a year that has no projects
- **THEN** the project picker is empty and no matrix is shown

### Requirement: Matrix structure
Rows SHALL be the selected project's phases in the project's phase order (OD-02 resolved = legacy parity, LHR-10); a save for a phase outside the project SHALL be refused. The matrix SHALL show read-only sequence, phase name and phase code, and one editable column per active discipline ordered by discipline sort order, without a hard-coded discipline count (LHR-10..12). Values on removed phases or inactive disciplines SHALL be handled per OD-08 and SHALL NOT be deleted silently.

#### Scenario: Project with six phases
- **GIVEN** a project with 6 phases and 5 active disciplines
- **WHEN** the matrix loads
- **THEN** 6 rows × 5 editable cells are shown in the stored phase order

#### Scenario: New discipline
- **GIVEN** a sixth discipline becomes active
- **WHEN** any matrix loads
- **THEN** a sixth column appears without layout overlap

### Requirement: Blank and zero are distinct
A cell SHALL be in exactly one state, BLANK or VALUE, and an explicit 0 SHALL be a VALUE (OD-01 resolved = A); storage (`ManDays` null vs number), the flow contract (`state` + `value`) and the UI SHALL preserve that state. Clearing a cell SHALL keep its item and set the value to null (OD-09 resolved = A). Reports SHALL sum BLANK as 0 without erasing the distinction.

#### Scenario: Zero round-trip
- **WHEN** the user enters 0 in a blank cell, saves and reloads
- **THEN** the cell shows "0" and the stored value is 0

#### Scenario: Clear round-trip
- **WHEN** the user clears a cell holding 12 and saves
- **THEN** the cell is BLANK after reload, the item still exists and its stored value is null

### Requirement: Value validation
The system SHALL accept only numeric values with at most 2 decimal places (OD-03 resolved by evidence: legacy parses
decimals and reports 2 decimals) and SHALL reject non-numeric input or more than 2 decimals with a typed message before
saving, client-side and again server-side (LHR-15, LHR-16). A typed decimal comma SHALL be normalised to the stored
decimal value. Minimum and maximum bounds SHALL follow OD-42 (BLOCKING M1; no bound is assumed). No value SHALL be
silently changed.

#### Scenario: Invalid text or precision
- **WHEN** the user types "abc" or "1.234" in a cell
- **THEN** the cell is marked invalid, Save is disabled, and a direct flow call with that value returns VALIDATION_VALUE without any write

### Requirement: Changed-cell save
Save SHALL send only cells whose state or value changed since load, with each cell's load ETag, through `REG-SaveMatrix` (1–100 cells per call). The server SHALL validate and authorise every cell before writing any (preflight); then write
each cell individually and report a per-cell result; overall result OK, PARTIAL or REFUSED (LHR-18, LHR-29).

#### Scenario: k changed cells
- **GIVEN** a loaded 6 × 5 matrix
- **WHEN** the user changes 3 cells and saves
- **THEN** exactly 3 items are created or updated and the other 27 are untouched

#### Scenario: Preflight refusal writes nothing
- **WHEN** one of 4 changed cells fails validation or authorisation
- **THEN** the result is REFUSED and none of the 4 cells is written

#### Scenario: Concurrent edit of the same cell
- **GIVEN** two editors loaded the same matrix
- **WHEN** both change the same cell and save, one after the other
- **THEN** the second save is REFUSED at preflight, that cell is reported CONFLICT, none of the second editor's cells is written, and the stored value is the first editor's

#### Scenario: Race after preflight
- **GIVEN** a save passed preflight
- **WHEN** another writer changes one of its cells before that cell is written
- **THEN** that cell returns CONFLICT, the other cells are written, and the overall result is PARTIAL with committed and failed cells identified

### Requirement: Save feedback and dirty state
Save SHALL be enabled only with a selected project, at least one changed cell and no invalid cell; success and failure
SHALL be shown with the correlation id; leaving the screen or changing project with unsaved changes SHALL ask for
confirmation (LHR-19, LHR-20).

#### Scenario: Leave with unsaved changes
- **WHEN** the user switches project with 2 unsaved cells
- **THEN** a confirmation is shown and the changes are kept if the user cancels

### Requirement: Read-only access
A user with `REG.View` but without `REG.Edit` SHALL see the matrix in view mode without Save; any write attempt through
the flow SHALL be refused server-side with ROLE_NOT_ALLOWED and no write (LHR-24, SECURITY_HARDENING).

#### Scenario: Viewer forges a save
- **WHEN** a viewer sends a `REG-SaveMatrix` request directly
- **THEN** the response is ROLE_NOT_ALLOWED, an AuthorizationDeny audit row exists and no item changes

### Requirement: Lifetime budget
The time dimension of registered man-days SHALL follow OD-12 (NON_BLOCKING; recommended default = legacy lifetime).
IF OD-12 keeps the legacy option (a), registered man-days SHALL be a lifetime value per project, phase and discipline and
the year filter SHALL NOT change stored values (LHR-23). IF OD-12 selects a per-year budget, this requirement and the
data model SHALL be re-baselined before implementation. In every option, values SHALL be labelled as man-days
("Công đăng ký"), not hours (LHR-39).

#### Scenario: Year filter does not change values under the legacy option
- **GIVEN** OD-12 keeps the legacy lifetime option
- **WHEN** the same project is opened under two different year filters
- **THEN** the same values are shown
