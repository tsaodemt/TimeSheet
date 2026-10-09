# Timesheet Modernization (Microsoft 365)

Replacement of a legacy desktop timesheet application with a solution built entirely on **Microsoft 365**:

- **SharePoint Online** lists as the system of record
- **Power Apps** (canvas) as the user interface, hosted in Teams and the browser
- **Power Automate** guard flows as the only writers of protected data
- **Power BI** for cross-employee reporting
- **Microsoft Entra ID** for sign-in and security groups as the role source

Only **standard** (non-premium) connectors are used.

## Status

| Area | Status |
|---|---|
| Legacy analysis, target design, implementation plan | Done (kept private) |
| Staging environment, reference data and employee migration rehearsal | Done |
| Identity & authorisation: **guarded write proxy** security spike | **PASS** (see `docs/security-write-proxy-spike.md`) |
| Identity & authorisation: **guarded read proxy** spike (own-row reads keyed on business owner, > 5,000 rows) | **PASS** (see `docs/security-read-proxy-spike.md`) |
| Identity & authorisation: application identity resolution and data scoping | Contract and reference implementation with tests (see `docs/identity-resolution.md`); wiring into app and flows pending |

## Repository layout

```
docs/
  architecture.md                     Target architecture and key decisions
  security-write-proxy-spike.md       Write-proxy test plan (T1–T11) and results
  security-read-proxy-spike.md        Read-proxy test plan (R1–R10) and results
  identity-resolution.md              Identity-resolution contract (fail-closed), session behaviour, portability
  role-model.md                       Target roles and capabilities
  approval-capability-rules.md        Approved approve / unapprove matrix (gate G5), immutability and audit contract
  approve-contract.md                 TS-Approve / TS-Unapprove / TS-ReadTeam contract (S07.2 + S07.3 DONE, STAGING live-proven)
  runbook-identity-jml.md             Joiner / mover / leaver guidance (group propagation)
  roadmap.md                          Epic structure
tools/powerautomate/
  build_guard_flow.py                 Generates the guarded write-flow definition
  make_designer_paste_build.py        Builds the flow in the classic designer via clipboard paste
  build_read_flow.py                  Generates the guarded read-flow definition
  make_read_designer_build.py         Builds the read flow in the classic designer
  make_read_guard_repaste.py          Re-pastes the read flow's guard scope after a definition change
  build_identity_flow.py              Generates the identity-resolution guard flow
  build_role_probe_flow.py            Generates the role/scope probe flow used for role tests
tools/identity/
  identity_resolver.py                Reference identity resolver (trusted identity → employee → roles)
  scope_resolver.py                   Reference data scoping (self / discipline / company, project assignment)
  employee_matching.py                Conservative Employees ↔ directory account matching (proposals only, never applied)
  build_identity_apply_preview.py     Reviewed mapping CSV → APPLY PREVIEW (closed decision vocabulary; local file, no writes)
  test_*.py                           Contract tests I1–I10, S1–S8, EM01–EM23, AP01–AP19 (synthetic data; python -m unittest)
tools/approval/
  approval_rules.py                   Approval capability matrix and check order over the existing guard (reference)
  test_approval_rules.py              AP-R01–AP-R25 (synthetic data; python -m unittest)
  approve_entries.py                  TS-Approve / TS-ReadTeam reference (per-row approval, ETag, self / scope rules, queue)
  test_approve_flow.py                AQ01–AQ26, AQ-EQ, RT01–RT12: reference vs generated flows in the WDL simulator
  test_unapprove_flow.py              UQ01–UQ38: TS-Unapprove + TS-ReadTeam Approved mode (S07.3)
tools/powerautomate/build_approval_flows.py   TS-Approve, TS-Unapprove and TS-ReadTeam flow definitions (S07.2 / S07.3)
```

## Confidentiality

This repository is **public**. It contains **no** customer data and **no** tenant identifiers, account names, security-posture findings, legacy credentials or keys. Customer-specific values appear only as placeholders such as `<tenant>`, `<staging-site>`, `<service-account>`, `<employee-upn>` and `<tenant-id>`. All configuration is supplied through environment variables at run time.

The full investigation, migration evidence and customer decision packs are kept in a private working area that is excluded by `.gitignore`.

## Environment portability

Nothing tenant-specific is hard-coded in reusable components:
- site URLs, group IDs, connection IDs and environment IDs come from configuration;
- production deployments use Power Platform solution environment variables;
- provisioning is scripted, so an environment can be rebuilt in another tenant.
