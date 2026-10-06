# Schema provisioning and drift reconciliation

`tools/provisioning/schema_reconcile.py` compares a target list schema (environment configuration, JSON) with a read-only inventory of a site. It then plans and, if explicitly requested, applies only safe additive changes.

## Findings

| Status | Meaning | Executed by `apply` |
|---|---|---|
| `OK` | Matches the target | – |
| `CREATE` | List or column missing | yes |
| `UPDATE-SAFE` | Index, unique (with a no-duplicates precondition), required, display name, or additional choice values | yes |
| `BLOCKED-INCOMPATIBLE` | Wrong type, date-only vs date-time, or wrong lookup target | **no**. The whole run stops before any call. |
| `DECISION-REQUIRED` | The target object carries an open decision | no |
| `GATED` | The object belongs to a later story or gate | no |
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
- **Idempotent:** after a successful run the reconciliation reports `OK` everywhere, and a second run does nothing.
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

## Tests

`tools/provisioning/test_schema_reconcile.py` covers P01–P14:
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
- REST request building.
