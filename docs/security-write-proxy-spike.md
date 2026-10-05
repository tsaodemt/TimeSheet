# Guarded Write-Proxy Security Spike

**Result: PASS** (staging environment). All values below are placeholders.

## Setup

| Element | Description |
|---|---|
| Protected list | Temporary list in `<staging-site>`; unique permissions; list setting "read own items", "create/edit: none" |
| Normal caller | `<test-user>`: Read on the list; no Add/Edit/Delete |
| Reviewer group | `<reviewer-group>`: Read + Override List Behaviors (see all items, no write) |
| Service identity | `<service-account>`: custom level = Contribute **without Delete** + Override List Behaviors; owns the SharePoint and Office 365 Groups connections |
| Guard flow | Instant trigger, run-only sharing. Office 365 Users connection **provided by the caller**; SharePoint and Groups connections embedded (service). |
| Audit list | Writable only by the service identity; invisible to users |

## Tests

| # | Property | Method | Result |
|---|---|---|---|
| T1 | Trusted caller | Caller sends a decoy `CallerUpn` of another user | Ignored; actor = real caller |
| T2 | Forged caller/owner | Non-reviewer requests a write for another owner; non-reviewer approves | `FORBIDDEN`; no write |
| T3 | Forged platform headers | `x-ms-user-email/-id/-name` injected into the trigger request | Overwritten by the gateway; no escalation |
| T4 | Own save | Normal user saves own entry | Written by the service connection; Actor = Owner; `IsOnBehalf=false` |
| T5 | Reviewer on-behalf | Reviewer saves for another owner | Allowed; `IsOnBehalf=true`; actor and owner stored separately |
| T6 | Approval lock | Approve, then attempt modification | `LOCKED`; item unchanged |
| T7 | UI / grid direct write | New form, edit form, grid edit as user | "Access is denied" / read-only |
| T8 | REST direct write | POST, MERGE, ValidateUpdateListItem, AddValidateUpdateItemUsingPath, DELETE, recycle | 403 (audit list 404) |
| T9 | Read scope | Normal vs reviewer | Reviewer sees all; normal user sees only items they Authored (see the lesson in `architecture.md`) |
| T10 | Effective permissions | Per identity and state | User: no Add/Edit/Delete. Service: Add/Edit, no Delete, no Manage Lists or Permissions |
| T11 | Licensing | Connector classification | Standard only; plan "user who runs the flow" |

Membership changes for reviewer vs normal mode were made only on the temporary test identity. SharePoint authorisation was re-validated until stable before each phase.

## Follow-up experiment: Author stamping with Manage Lists — FAILED

- A separate level adding only **Manage Lists**, scoped to the protected list only, did **not** let the service identity set `Author`.
- The permission was restored immediately, and no further escalation was attempted.
- Consequence: ownership is modelled with `OwnerUpn`, and reads go through a guarded read proxy (`architecture.md`, AD-3/AD-4).
