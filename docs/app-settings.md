# AppSettings: typed, fail-closed configuration

`tools/config/app_settings.py` manages the `AppSettings` list (one row per key: `Title` = key, unique; `Value` = text; `Description`). The registry of keys is project configuration (JSON) and is not kept in this repository.

## Registry entry

| Field | Meaning |
|---|---|
| `key` | PascalCase ASCII; case-insensitive unique |
| `type` | `int`, `decimal` (`.` separator only), `bool` (Yes/No, On/Off, True/False), `enum` (+ `allowed`), `text`, `iana_tz` |
| `min` / `max` | numeric bounds |
| `value` | the value, **only** when an authoritative source fixes it |
| `proposedDefault` | documentation of a recommended value; **never applied** |
| `resolution` | `RESOLVED`, `OPEN`, `BLOCKED`, `ENVIRONMENT-SPECIFIC`, `CUSTOMER DECISION`, `IT DECISION` |
| `valueBasis` | required for a value on an `OPEN`/`BLOCKED` setting |
| `environmentSpecific` | the value comes only from the per-environment overlay |
| `derived` | `{"from": <key>, "function": <name>}`: the value is always computed from another setting (e.g. a UTC offset from the business time zone). A derived setting has no value of its own, is not seeded, and any stored value for it is ignored and reported. One fact, one authority. |

`externalConfig` lists environment-specific **Power Platform** configuration that is deliberately *not* an AppSettings row: identities such as the operational service account (connection ownership / environment variable), with `where`, `requiredFor` (purposes) and the deciding decision. Identity bindings (`upn` type) are refused as AppSettings rows.

## Environment overlay

Per environment (confidential, not in this repository): `{"environment", "values", "external"}`.

An **interim** value is an owner-approved engineering value while a customer decision is still open:

```json
"SomeSwitch": {"value": "Off", "interim": true, "basis": "...", "approvedBy": "...", "approvedOn": "...",
               "customerDecision": "<id> OPEN", "allowedEnvironments": ["STAGING"]}
```

- It is usable only in its allowed environments and never in a production overlay (`validate_overlay` refuses it; `resolve` treats it as unresolved there).
- The resolved setting carries `interim = true` and its basis; the seeded row's description is marked `[INTERIM …]`; `drift()` reports it.
- It never changes the registry: the customer decision stays open until it is replaced explicitly.

## Resolution, gates and readiness

Precedence: site row → environment overlay → registry value. Derived settings are computed after their source.

| Effective state | Meaning | Dependent function |
|---|---|---|
| `CONFIGURED` | parsed and within bounds | runs |
| `UNRESOLVED` | missing, empty, or interim outside its environments | **refuses** with `CONFIG_UNRESOLVED` |
| `INVALID` | not parsable / out of bounds / forbidden content | **refuses** with `CONFIG_INVALID` |

`gate(settings, *keys, allow_interim=True)` returns `enabled=False` unless every key is `CONFIGURED` (and not interim, when `allow_interim=False`). A consumer never chooses a value itself.

`readiness(registry, overlay, purpose, required)`:

| Purpose | Accepts |
|---|---|
| `ENGINEERING` | configured values, including interim values in their allowed environment |
| `UAT` / `PRODUCTION` | only approved values (registry resolution `RESOLVED` or `ENVIRONMENT-SPECIFIC`, no interim) and every `externalConfig` item required for that purpose; `PRODUCTION` also requires the production overlay |

So a production deployment cannot pass while a customer decision is only covered by an interim value, or while the production service identity is not configured.

## What never goes into AppSettings

- Secrets, passwords, tokens, keys, connection strings: refused by key name and by value pattern.
- Tenant-bound technical bindings (site URLs, list/group IDs, domains, identities): refused in text values or declared as `externalConfig`; they belong in solution environment variables / connection ownership, so a solution moves between environments and tenants by changing those values only.

## Provisioning and drift

- `seed_rows()` produces one row per non-derived key; unresolved keys get an empty `Value`, so administrators see what is missing and the app still reads them as unresolved.
- Rows are loaded with `reference_data.apply_items` (key `Title`): missing rows are created; a value changed by an administrator is reported as drift and **not** overwritten.
- `drift()` reports unknown keys, environment configuration stored as a row, stored values of derived settings, invalid and unresolved values, interim values in effect, and site values that differ from the registry.

Tests: `tools/config/test_app_settings.py` C01–C25.
