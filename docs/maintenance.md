# Guarded maintenance of configuration and master data

Protected configuration (`AppSettings`) and master/reference lists are never edited directly by application users. Changes go through a guarded, audited maintenance flow:

```
trusted caller → guard (action for this target) → validation → one service operation → audit row (AdminMaintenance)
```

`tools/maintenance/maintenance.py` is the reference implementation of the validation step.

## Rules

- The guard decision must be for exactly the action the target requires. A grant for another action does not authorise the target.
- Request fields that claim actor, employee, role or scope are ignored and recorded by name only.
- Per target: allowed operations, field whitelist, soft-delete field, decision-dependent fields and invariants. Unknown target, operation or field is refused.
- No hard delete. Business deletion is a soft delete where the list defines one (`IsActive = false`). The service identity never holds Delete.
- Business keys (legacy key, code) are not maintainable through the flow.
- Optimistic concurrency: an ETag is required for updates.
- Configuration: `Value` only. The key must exist in the registry. Derived settings are read-only. Environment configuration (identities, URLs, IDs) is refused. Interim values are protected (they are replaced only through the decision record). Settings whose decision is not approved are refused. Environment-specific values come only from the environment overlay. Values are type-checked; secret-like values, URLs and IDs are refused.
- Fields that need a decision before they may change (for example a calculation factor whose change is retroactive) are refused with `DECISION_PENDING` until the rule exists.
- Every outcome, allowed or refused, produces one audit event with the trusted actor and the correlation ID. Secret keys are dropped from the change record, and rejected values are redacted.

## List permission hardening

`tools/provisioning/permission_plan.py` plans the permission change of one list from a read-only snapshot:
- `unsafe()` lists principals with write-capable rights that are not approved writers. An empty group counts too: safety must not depend on today's membership.
- `plan()` stops inheritance without copying, keeps the approved administrators, and removes stray writers on a list that already has unique permissions.
- Service grants are GATED until their decision is approved. They are refused for temporary/test principals, without an approval record, and for any role other than Read or a no-delete service level.
- A second run plans nothing. `requests()` returns the SharePoint REST calls.

Tests: `tools/maintenance/test_maintenance.py` AP01–AP24.
