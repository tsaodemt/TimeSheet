# AppSettings: typed, fail-closed configuration

`tools/config/app_settings.py` manages the `AppSettings` list (one row per key: `Title` = key, unique; `Value` = text; `Description`). The registry of keys is project configuration (JSON) and is not kept in this repository.

## Registry entry

| Field | Meaning |
|---|---|
| `key` | PascalCase ASCII; case-insensitive unique |
| `type` | `int`, `decimal` (`.` separator only), `bool` (Yes/No, On/Off, True/False), `enum` (+ `allowed`), `text`, `upn`, `iana_tz` |
| `min` / `max` | numeric bounds |
| `value` | the value, **only** when an authoritative source fixes it |
| `proposedDefault` | documentation of a recommended value; **never applied** |
| `resolution` | `RESOLVED`, `OPEN`, `BLOCKED`, `ENVIRONMENT-SPECIFIC`, `CUSTOMER DECISION`, `IT DECISION` |
| `valueBasis` | required for a value on an `OPEN`/`BLOCKED` setting (who approved an interim value, when) |
| `environmentSpecific` | the value comes only from the per-environment overlay |

## Resolution and gates

Precedence: site row → environment overlay → registry value.

| Effective state | Meaning | Dependent function |
|---|---|---|
| `CONFIGURED` | parsed and within bounds | runs |
| `UNRESOLVED` | missing or empty | **refuses** with `CONFIG_UNRESOLVED` |
| `INVALID` | not parsable / out of bounds / forbidden content | **refuses** with `CONFIG_INVALID` |

`gate(settings, *keys)` returns `enabled=False` unless every key is `CONFIGURED`. A consumer never chooses a value itself. Example: while a project-assignment switch is unresolved, the functions that depend on it refuse rather than assume "on" or "off". Audit retention follows the same rule (`docs/audit-model.md`): unset means purge disabled.

## What never goes into AppSettings

- Secrets, passwords, tokens, keys, connection strings: refused by key name and by value pattern.
- Tenant-bound technical bindings (site URLs, list/group IDs, domains): refused in text values; they belong in solution environment variables, so a solution can move between environments and tenants by changing environment-variable values only.

## Provisioning and drift

- `seed_rows()` produces one row per key; unresolved keys get an empty `Value`, so administrators see what is missing and the app still reads them as unresolved.
- Rows are loaded with `reference_data.apply_items` (key `Title`): missing rows are created; a value changed by an administrator is reported as drift and **not** overwritten.
- `drift()` reports unknown keys, invalid values, unresolved keys and site values that differ from the registry.

Tests: `tools/config/test_app_settings.py` C01–C14.
