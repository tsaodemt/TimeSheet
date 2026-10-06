# Authorization guard (reusable guard-flow template)

Every guarded flow answers one question the same way: *may the authenticated caller perform this action on this scope?*
The logic exists once and is consumed by every flow.

| Artefact | Role |
|---|---|
| `tools/identity/guard.py` | Reference implementation (executable specification). Reuses `identity_resolver.resolve` and `scope_resolver.effective_scope` / `allowed`. |
| `tools/powerautomate/guard_template.py` | Generates the `Guard` scope that every flow embeds. Configuration in, actions out. |
| `tools/powerautomate/build_guard_template_flow.py` | Test harness flow that consists only of the template (first consumer). |
| `tools/identity/test_guard.py` | G1–G15. Each case runs through **both** the reference and the generated template (executed offline by `tools/powerautomate/wdl_sim.py`); every output field and the audit row must match. |

**Why inlined, not a child flow:** the trusted identity is `MyProfile_V2` on the **invoker's own** Office 365 Users connection. A child flow runs on embedded connections and cannot see the invoker. So the generator is the single source, and its output is pasted into each flow.

## Chain

```
MyProfile_V2 (invoker connection) ─► normalised UPN, allowed domain
  ─► Employees by AccountUpn (indexed, unique, $top=2) ─► exactly one active row
  ─► live membership of every configured role group (service Groups connection)
  ─► class table (generated from the role seed) ─► effective scope = most permissive across roles
  ─► requested scope checked against list data ─► Guard_result + audit row
```

## Request

| Input | Meaning |
|---|---|
| Action | Capability name, e.g. `TS.Approve`. Matching is case-insensitive; the canonical name is returned. |
| ScopeKind | `self`, `employee`, `discipline` or `company` |
| ScopeRef | Target employee code (`employee`) or discipline code (`discipline`). Required for those two kinds. |

The target's discipline is always read from the employee list. It is never taken from the request.

**Never read:** caller, owner or actor UPN; role; granted scope; the caller's discipline, department or project; reviewer flag; `x-ms-user-*` headers. A flow may pass such fields to the guard. They are recorded **by name** in `IgnoredInputs`. Their values are not logged.

## Result (`outputs('Guard_result')`)

`AuthenticatedUpn`, `EmployeeId`, `EmployeeCode`, `IsActive`, `ResolvedRoles`, `RequestedAction`, `RequestedScope`, `ResolvedScope`, `AuthorizationDecision` (`ALLOW` / `DENY`), `ResultCode`, `CorrelationId` (flow run name), `IgnoredInputs`.

A consuming flow acts **only** when `AuthorizationDecision = ALLOW`.

| ResultCode | When (first match wins) |
|---|---|
| `INVALID_IDENTITY` | No platform identity, or a foreign domain |
| `DIRECTORY_ERROR` | Employee lookup failed. This is never treated as "not found". |
| `UNMAPPED_IDENTITY` | No employee row for the UPN |
| `DUPLICATE_IDENTITY` | More than one row claims the UPN (configuration error) |
| `INACTIVE_EMPLOYEE` | Row is not active |
| `UNKNOWN_ACTION` | Action is not in the capability catalogue |
| `UNKNOWN_SCOPE` | Unknown scope kind, a missing reference, or only a configured scope value that is not self/discipline/company (e.g. `restricted:…`) |
| `DECISION_PENDING` | No role grants the action, and one of the caller's roles has it as an open customer decision |
| `TEMP_ROLE_INACTIVE` | Only a temporary role (e.g. Migration Owner) holds the action. No activation mechanism exists yet. |
| `ROLE_NOT_ALLOWED` | None of the caller's roles grants the action |
| `SCOPE_NOT_ALLOWED` | Action granted, but the target is outside the effective scope. An unknown target employee gets the same code, so the response does not reveal whether the employee exists. |
| `ALLOW` | In scope |

## Scope rules

The rules come from the role seed. The guard adds none.

- `self` scope: target must be the caller.
- `discipline` scope: target discipline must equal the caller's non-empty discipline. A caller without a discipline is denied.
- `company` scope: any target.
- Multiple roles: per action, the **most permissive** valid scope across the caller's roles. A pending, temporary or unknown entry never grants. Another role's valid grant still applies.

Open customer decisions stay `DECISION_PENDING` (deny). Only the scope table changes when a decision is taken; the guard does not change.

## Audit

Each evaluation writes one row: `Title`, `Decision` (ALLOWED/DENIED), `ResultCode`, `CallerUpnTrusted`, `CorrelationId`, `Detail` (employee ID/code, active flag, roles, action, requested and resolved scope, ignored input names).

## Propagation (operational rule)

- **Guard flows** read group membership live. A change applies on the next run, usually within a minute.
- **SharePoint direct access** through Entra groups can lag **≈ 20–30 minutes** after an add or a removal.
- Admin-side `getusereffectivepermissions` does not reflect access inherited through Entra security groups. It is not proof. Test from the affected user's own session.

## Limits of the offline verification

`wdl_sim.py` implements only the expression functions and action types the guard uses. It is deliberately as strict as Power Automate where they differ in practice. For example, `empty()` accepts only strings, arrays and objects; a number raises an error. The template therefore tests nullable numbers with `equals(x, null)`. String comparisons in the simulator are case-sensitive, and SharePoint `eq` filters are case-insensitive. Business keys are expected in canonical case. The live harness run in Power Automate remains the acceptance evidence for the deployed flow.
