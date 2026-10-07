# Schema provisioning and drift reconciliation

`tools/provisioning/schema_reconcile.py` compares a target list schema (environment configuration, JSON) with a read-only inventory of a site. It then plans and, if explicitly requested, applies only safe additive changes.

## Findings

| Status | Meaning | Executed by `apply` |
|---|---|---|
| `OK` | Matches the target | – |
| `CREATE` | List or column missing | yes |
| `UPDATE-SAFE` | Index, unique (with a no-duplicates precondition), required, display name, or additional choice values | yes |
| `BLOCKED-INCOMPATIBLE` | Wrong type, date-only vs date-time, or wrong lookup target | **no**. The whole run stops before any call. |
| `DECISION-REQUIRED` | The target object carries an open decision. A missing list whose key column has an open decision marked `decisionBlocksList` is not created at all (internal names are permanent, so a list is never created without its key column). | no |
| `GATED` | The object belongs to a later story or gate, or it is a lookup column whose target list neither exists nor is created in the same run | no |
| `EXTRA` | Present on the site but not in the target | no (never removed automatically) |

## Safety rules

- **Dry run by default.** Mutation requires `dry_run=False`.
- **Site guard:**
  - the target URL must equal the configured URL exactly;
  - tenant root sites are always refused, even if misconfigured;
  - a missing configuration is refused.
- **Never** deletes, renames or retypes lists or columns.
- **No IDs in code or schema.**
  - Lookup list IDs are resolved at run time.
  - Internal names are fixed at creation: the column is created with the internal name as its display name, then renamed.
- **Ordering:** every list is created before any column, so a lookup column always finds its target list. A new list's built-in `Title` gets its required flag, index/unique (key lists such as `AppSettings`) and display name in the same run.
- **Idempotent:** after a successful run the reconciliation reports `OK` everywhere, and a second run does nothing. An interrupted run is completed by running again from a fresh inventory.
- **Transport is injected** (`transport(method, path, body, headers)`), so the tool holds no credentials and no tenant URLs.

## Rollback classes

SharePoint has no transactional schema rollback.

| Operation | Rollback class |
|---|---|
| Add index, enforce unique, change required, rename display | REVERSIBLE |
| New column, new list | REVERSIBLE while empty; REVERSIBLE-WITH-DATA-RISK once data exists. Internal names stay consumed. |
| Added choice values | REVERSIBLE-WITH-DATA-RISK |
| Retype / rename / delete | not performed by the tool; manual, NOT-AUTO-REVERSIBLE |

## Business dates

Date-only business columns hold a business calendar date in the configured business time zone (`businessTimeZone` in the target schema). To derive a business date from an instant: convert the UTC instant to the business time zone, then take the local date (`business_date()`). Never truncate UTC.

## Root sites and a future production cutover (design only)

The site guard refuses every tenant root site, also when it is configured as the allowed site. This stays so.

If production cutover ever targets an approved root site, an explicit override procedure is needed. `tools/provisioning/cutover_guard.py` is the offline design of its checks; it is **not** wired into `apply()`:
- explicit cutover mode;
- the exact approved production URL;
- a human approval record (approver, time, change reference);
- a fresh drift check of that site (within 60 minutes) without incompatible drift;
- a dry-run plan whose hash equals the approved plan hash;
- an explicit typed confirmation naming the URL and the plan hash;
- an audit evidence record for the run log.

Every failed condition is reported together. Tests: `test_cutover_guard.py` O01–O09 (including that the normal guard still refuses root sites).

## Reference data (seed rows)

`tools/provisioning/reference_data.py` loads small master lists from a seed (rows keyed by a business key) with the same safety model:
- seed validation first (count, required, unique case-insensitive, `> 0`, exactly-one flags, "first by SortOrder is the default", "flag true exactly for the codes in a setting"); an unresolved setting fails the validation;
- item findings `OK` / `CREATE` / `DRIFT` / `EXTRA` / `BLOCKED` (business-key clash);
- only `CREATE` is executed; drift is reported and never overwritten, extra items are never deleted;
- refuses unless the list schema reconciles `OK`; exact site guard; dry run by default.

## Tests

- `test_reference_data.py` D01–D14: seed rules, idempotent load, drift, clash, fail-closed settings, REST request.
- `test_ac1_rebuild.py` R01–R06: empty-site rebuild simulation (child-before-parent ordering, interrupted run recovers on re-run, unavailable lookup targets, dry-run plan = executed plan; with a target definition: every list rebuilt and converged in one run, rebuilt lists match the as-built ones). This is offline evidence, **not** a live empty-site proof.
- `test_s043_schema.py` W01–W10: work-classification list definitions (needs the target definition).

`tools/provisioning/test_schema_reconcile.py` covers P01–P15:
- empty site;
- no-op;
- missing list, missing column, missing index;
- incompatible drift;
- safe updates;
- idempotent re-run;
- gated and undecided objects;
- root and foreign site rejection;
- business-date semantics;
- no hard-coded IDs;
- no destructive operations;
- REST request building;
- an open key-column decision blocks the whole list (P15).
