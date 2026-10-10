## ADDED Requirements

### Requirement: Reporting data contract and current-scope in-app reports
R3 SHALL define and populate the persisted facts/keys for registered/planned effort, actual effort, variance, project summary and discipline summary. Current-scope M4 reports (OD-50 resolved = in-app guarded reporting) SHALL run inside the existing Power Apps application through guarded Power Automate reporting flows that resolve the caller and scope server-side and return aggregates only; they SHALL NOT require a Power BI licence and SHALL NOT return a protected source row because a report shows its total. R3 SHALL NOT deploy resource evaluation (NR-EFF-09), KPI, salary review, bonus / reward, resource scoring or ranking.

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
The R3 contract SHALL contain no salary, rate or labour-cost column, and no M4 report response or screen SHALL contain salary, daily / employee / position rate, labour monetary cost, bonus, reward or salary recommendation; no confidential rate data SHALL be read to compute a hidden value (OD-20 resolved = effort only, current scope).

#### Scenario: Contract schema check
- **WHEN** the R3 planning fact columns are listed
- **THEN** no salary, rate or cost column is present

### Requirement: Plan with no actual is shown
A report row with a planned value and no included Approved Timesheet row SHALL be shown with a derived actual of 0 (OD-13 resolved, deviation from legacy LHR-33); no Timesheet row SHALL be written for it.

#### Scenario: Planned project without actuals
- **GIVEN** a project with planned effort 5 and no Approved Timesheet row
- **WHEN** the project report is read
- **THEN** the row is shown with actual 0 and variance 5

### Requirement: Project and discipline report measures
The project report SHALL use the EPIC 16 Project Effort total as the plan (OD-52 resolved); M1 `HourRegistrations` SHALL be shown only as a separate column, never added to, netted with or substituted for the plan. The discipline report SHALL count only ApprovedLocked EPIC 17 registrations as the plan (OD-51 resolved); Draft registrations SHALL be excluded and no "including drafts" figure SHALL be shown. Actual = Σ Approved Timesheet hours ÷ `HoursPerManDay`; variance = planned − actual; plan and actual are project-lifetime figures.

#### Scenario: Draft plan and Draft actual are excluded
- **GIVEN** a discipline with ApprovedLocked 1.75, Draft 0.75, Approved Timesheet 16 h and Draft Timesheet 8 h, `HoursPerManDay` = 8
- **WHEN** the discipline report is read
- **THEN** planned is 1.75, actual is 2 and variance is −0.25

#### Scenario: M1 stays separate
- **GIVEN** a project with M2 plan 17.5 and M1 registered 10
- **WHEN** the project report is read by a caller holding `REG.View`
- **THEN** planned is 17.5 and M1 registered 10 is a separate value; neither is added to the other

### Requirement: Report scope
Report visibility SHALL follow the M4 report matrix: project report — project PM (own projects), PMO, Executive, Approver (= Quản lý phòng for M4 only, OD-31); discipline report — Team Leader (own discipline), project PM (own projects), PMO, Executive, Approver. Employee and technical / confidential roles SHALL be denied. The OD-31 mapping SHALL NOT change any M2, M3, EPIC 07 or Timesheet right.

#### Scenario: Approver reads reports but gains no planning right
- **GIVEN** a caller holding only Approver and Employee
- **WHEN** the caller reads the reports and then calls the M3 approve flow
- **THEN** both reports return company aggregates and the approval is refused ROLE_NOT_ALLOWED
