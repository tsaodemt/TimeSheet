# R1 known limitations (authoritative)

Accepted for R1 by the project owner. They do not block R1 offline readiness; none of them weakens ownership or
exposes another employee's data.

## R1_KNOWN_LIMITATION_CREATE_RETRY_NON_IDEMPOTENT

TS-SaveEntry CREATE is **non-idempotent** (`NON_IDEMPOTENT_R1`). Every valid create is an independent command with a
fresh `LegacyId`. If the write succeeds but the response is lost and the caller submits the same create again, a
second row is created.

- The second row has its own item id and `LegacyId` and is owned by the authenticated caller; lookup and ownership
  validation run again.
- `WARN_DUPLICATE` is advisory: it never blocks, rolls back, merges or deletes.
- No silent deduplication; duplicates stay visible to the employee and reviewers.
- Mitigation: the app disables Save while a call is in flight.
- Not used: RequestKey or any idempotency-key column, payload hash, deterministic LegacyId, correlation-id reuse.
- Updates are not affected: a retry with the old ETag is a `CONFLICT` (optimistic concurrency, no wildcard).
- A formal idempotency mechanism may be considered after R1; it is not promised.

## Other deferred items (unchanged, tracked separately)

- `STAGING_TEMPORARY_BYPASS` identity mappings: STAGING only, never valid for UAT / Production
  (`is_identity_approved_for`); HR/IT identity verification is open.
- ReadOwn has no maximum date span (a business-period cap is a separate decision).
- AUD-F1 option B: a failed post-write WriteProxy append returns `ok=true` with `AUDIT_DEGRADED` and alerts operations.
- Live STAGING deployment is blocked by tenant Dataverse capacity (`docs/r1-status.md`).
