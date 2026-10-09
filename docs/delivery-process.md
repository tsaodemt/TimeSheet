# Delivery process for new epics / business areas (Open Spec first)

Approved by the project owner on 2026-10-09, at the close of EPIC 07 (Approval & Locking). From now on, **no new epic or
business area starts by writing code**. Each one follows these steps:

```text
DISCOVER
-> APPLY RELEVANT SKILLS / TOOLS
-> LEGACY SOURCE REVIEW
-> OPEN SPEC
-> BUSINESS / CUSTOMER DECISION REGISTER
-> ARCHITECTURE + SECURITY + DATA + UI DESIGN
-> TEST / MIGRATION / ACCEPTANCE DESIGN
-> SPEC REVIEW
-> SPEC APPROVAL
-> STORY / TASK BREAKDOWN
-> IMPLEMENTATION
-> LIVE TEST
-> E2E
-> EPIC CLOSURE
```

## Open Spec minimum content

- business outcome
- scope:
  - IN
  - OUT
  - DEFERRED
- legacy mapping:
  - features
  - rules
  - workflows
- known legacy defects, each marked:
  - preserve
  - fix
  - do not replicate
- roles and permissions
- data / schema
- Power Apps UX
- Power Automate contracts
- audit
- error handling
- concurrency
- security
- migration / data impact
- dependencies
- open decisions
- test strategy
- live proof plan
- E2E plan
- acceptance criteria
- Definition of Done
- deployment and rollback
- evidence
- timeline / milestones

**Unknown business rules are recorded as `OPEN_DECISION`, never invented.**

## Rules that carry over

- Legacy behaviour is the reference unless one of these says otherwise:
  - a signed gate decision;
  - a deliberate replacement in the backlog;
  - a documented, safer security design.
- The closed decisions of earlier gates override older role tables.
- Nothing runs in Production.
- The MAIN SharePoint site is read-only.
- Live work runs only on the STAGING site.

## Next activity

The next activity is an **Open Spec** for R3 Planning & Effort. It covers:

- S12.5 Đăng ký công / Hour Registration;
- EPIC 16 Project Effort Registration;
- EPIC 17 Discipline Effort Planning & Approval.

None of these is implemented before its spec is approved.
