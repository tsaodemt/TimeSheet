# R3 Open Spec — Review Fixes V2

This revision applies the project-owner review before implementation approval. No tenant mutation or implementation is included.

Key corrections:

1. Canonical `HourRegistrations.RegKey` is environment-portable and uses immutable master LegacyId/stable values; SharePoint ItemId is local lookup/query metadata only.
2. Approval audit is exactly one Approval business event per approved item; lock is the resulting state, not a second business event.
3. OPEN_DECISION items no longer leak into unconditional `SHALL` behavior; key rules are conditional until approved.
4. EPIC16 blank/zero semantics are separated from legacy S12.5 via OD-40.
5. Actual-effort ownership no longer narrows live Timesheet behavior; Timesheet reuse preserves existing trusted on-behalf semantics, while separate/hybrid actual entry requires OD-41.
6. Protected planning lists deny ordinary direct SharePoint read as well as write; authorised access is via guarded flows.
7. `ClientRequestId` is documented as correlation only; current design is replay-safe via state/ETag, not true request-id idempotency.
8. REG Save limit is 100 changed cells so the current 13 × 5 / 13 × 6 matrix fits one user Save call; the client must not silently split a Save into independent commits.
9. Migration counts are conditional on OD-01/OD-09 instead of hard-coded to 199/4 before the business decision.
10. Legacy Hour Registration remains stored in man-days; new EFF unit follows OD-14 and later comparisons normalise explicitly.
11. OD-13 no longer hard-codes "show budget without actuals" before the decision.
12. EFF-F-8 / advanced resource evaluation and scope deferral are recorded as resolved current-scope facts; A.I has no approval workflow unless a future explicit change requests one.
13. `Quản lý phòng` is an A.I recipient category; its human role mapping is deferred to later reporting visibility and does not block A.I storage.
14. Legacy LHR-27 security wording now uses list-level protected permissions + guarded proxy, not item-level unique permissions.
15. R3 only validates reporting facts/contracts offline/read-only; EPIC18 analytics UI/API remains outside R3.
16. Timeline now includes the established customer-facing targets: S12.5 testable STAGING around 03–05/11, stabilisation around 10/11, Planning & Effort closure around 20/11 (targets, decision-dependent).

Status after this revision: **OPEN SPEC — READY FOR REVIEW, NOT APPROVED, NO IMPLEMENTATION.**
