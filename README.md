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
| Identity & authorisation: **guarded read proxy** spike (own-row reads keyed on business owner) | In progress |

## Repository layout

```
docs/
  architecture.md                     Target architecture and key decisions
  security-write-proxy-spike.md       Write-proxy test plan (T1–T11) and results
  role-model.md                       Target roles and capabilities
  runbook-identity-jml.md             Joiner / mover / leaver guidance (group propagation)
  roadmap.md                          Epic structure
tools/powerautomate/
  build_guard_flow.py                 Generates the guarded write-flow definition
  make_designer_paste_build.py        Builds the flow in the classic designer via clipboard paste
```

## Confidentiality

This repository is **public**. It contains **no** customer data and **no** tenant identifiers, account names, security-posture findings, legacy credentials or keys. Customer-specific values appear only as placeholders such as `<tenant>`, `<staging-site>`, `<service-account>`, `<employee-upn>` and `<tenant-id>`. All configuration is supplied through environment variables at run time.

The full investigation, migration evidence and customer decision packs are kept in a private working area that is excluded by `.gitignore`.

## Environment portability

Nothing tenant-specific is hard-coded in reusable components:
- site URLs, group IDs, connection IDs and environment IDs come from configuration;
- production deployments use Power Platform solution environment variables;
- provisioning is scripted, so an environment can be rebuilt in another tenant.
