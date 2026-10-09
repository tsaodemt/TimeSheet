## ADDED Requirements

### Requirement: Reporting data contract only
R3 SHALL define and populate the persisted facts/keys that later reporting can consume for registered/planned effort, actual effort, variance, project summary and discipline summary. R3 SHALL NOT deploy an EPIC 18 analytics screen, Power BI page, reporting API solely to satisfy this contract, resource evaluation (NR-EFF-09), KPI, salary review or cost figures. Contract verification in R3 is an offline/reference or read-only data-shape/reconciliation test.

#### Scenario: Contract reconciliation test
- **GIVEN** synthetic registrations and actuals for a project
- **WHEN** the R3 reference contract calculation is executed over persisted facts
- **THEN** planned, actual and variance reconcile using the documented keys and conversion rule without requiring a deployed analytics surface

### Requirement: Source units are preserved; comparison unit is normalised explicitly
Legacy `HourRegistrations.ManDays` SHALL remain stored in man-days (LHR-39). New EPIC 16/17 effort SHALL be stored in the unit decided by OD-14. Reporting SHALL NOT rewrite either source unit. When a comparison needs a common unit and OD-14 is not man-days, the reporting contract SHALL normalise explicitly using the approved conversion (`HoursPerManDay` where applicable) and SHALL expose/document the comparison unit. Blank/zero counting semantics for each source SHALL follow that source's approved rule (OD-01 for Hour Registration, OD-40 for Project Effort).

#### Scenario: Legacy budget with hour-based rev01 effort
- **GIVEN** OD-14 selects hours
- **WHEN** a later report compares legacy Hour Registration with rev01 actual/planned effort
- **THEN** Hour Registration remains stored as man-days and the comparison calculation converts it explicitly rather than mutating the source data

### Requirement: Registered budget sums remain reconcilable
Registered man-days per project SHALL equal the sum of applicable `HourRegistrations` values after applying the approved stale-row rule OD-08; blank cells contribute zero to arithmetic sums without being rewritten as explicit zero unless OD-01 says so.

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
