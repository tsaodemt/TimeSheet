## ADDED Requirements

### Requirement: Reporting data contract only
R3 SHALL define and populate the persisted facts/keys that later reporting can consume for registered/planned effort, actual effort, variance, project summary and discipline summary. R3 SHALL NOT deploy an EPIC 18 analytics screen, Power BI page, reporting API solely to satisfy this contract, resource evaluation (NR-EFF-09), KPI, salary review or cost figures. Contract verification in R3 is an offline/reference or read-only data-shape/reconciliation test.

#### Scenario: Contract reconciliation test
- **GIVEN** synthetic registrations and actuals for a project
- **WHEN** the R3 reference contract calculation is executed over persisted facts
- **THEN** planned, actual and variance reconcile using the documented keys and conversion rule without requiring a deployed analytics surface

### Requirement: Source units are preserved; comparison unit is normalised explicitly
Legacy `HourRegistrations.ManDays` SHALL remain stored in man-days (LHR-39). EPIC 16 Project Effort SHALL be stored in man-days with at most 2 decimals (OD-14 resolved; bounds OD-44). Actual effort SHALL be read from the existing `TimesheetEntries` hours (OD-19 resolved) and SHALL be converted to man-days in the reporting/query contract as Σ hours of Approved Timesheet rows ÷ `HoursPerManDay` (OD-33 resolved = Approved only; Draft excluded); the hours SHALL NOT be rewritten. Reporting SHALL NOT rewrite any source unit and SHALL expose/document the comparison unit. Sharing the man-day unit SHALL NOT link Hour Registration and Project Effort values; any comparison between them is an explicit later reporting calculation. Blank/zero counting semantics for each source SHALL follow that source's approved rule (OD-01 = A for Hour Registration; OD-40 = blank not registered / zero explicit for Project Effort). EPIC 17 discipline effort is stored in man-days (OD-45, resolved from rev01, not inherited from OD-14) per Employee × Project × WorkType with Draft / ApprovedLocked state exposed; the discipline total is an aggregate, never stored. Actual effort per project × discipline is Σ Approved TimesheetEntries hours (`DisciplineCode`) ÷ `HoursPerManDay`, computed, never stored in EPIC 17.

#### Scenario: Actual hours normalised in the query
- **GIVEN** a project has 20 Approved and 8 Draft Timesheet hours and `HoursPerManDay` = 8
- **WHEN** the contract compares planned Project Effort with actual effort
- **THEN** actual effort is 2.50 man-days, computed in the query, and the Timesheet hours remain stored unchanged

#### Scenario: Blank planned effort is not a zero plan
- **GIVEN** a recipient with no registered Project Effort (blank) and one registered as 0
- **WHEN** the contract lists planned effort
- **THEN** the first is exposed as not registered and the second as an explicit 0; arithmetic sums may add blank as 0 without rewriting it

### Requirement: Registered budget sums remain reconcilable
Registered man-days per project SHALL equal the sum of applicable `HourRegistrations` values after applying the approved stale-row rule OD-08; blank cells contribute zero to arithmetic sums without being rewritten as explicit zero (OD-01 resolved = A).

#### Scenario: Legacy budget sum
- **GIVEN** the migrated legacy budget of a project
- **WHEN** the per-project registered total is computed
- **THEN** it equals the approved legacy-reconciliation total for that project

### Requirement: No cost leakage
The R3 contract SHALL contain no salary, rate or labour-cost column. OD-20 is a later reporting decision and cannot add confidential cost data to R3 planning lists.

#### Scenario: Contract schema check
- **WHEN** the R3 planning fact columns are listed
- **THEN** no salary, rate or cost column is present

### Requirement: Budget-without-actuals presentation remains undecided
Whether later reporting shows budget/planned rows that have no actual effort SHALL follow OD-13. R3 SHALL preserve enough independent budget/planning facts for either presentation; it SHALL NOT hard-code option (a) before OD-13 is decided.

#### Scenario: OD-13 option is applied later
- **GIVEN** a project with budget but no actuals in a period
- **WHEN** later reporting is implemented
- **THEN** inclusion/exclusion follows the recorded OD-13 decision without requiring a change to R3 source facts
