# R1 first-live runtime checks

Some runtime facts cannot be established offline. Each check below runs on the first live deployment of the R1 flows (STAGING, after D-3 / ENV-D3) and before R1-01..R1-15. Readiness reports them as `FIRST_LIVE_CHECK_PENDING` notices (`tools/alm/r1_readiness.py`).

| Check | Flows | What is confirmed |
|---|---|---|
| V-LAZY | all | Flow results are the same whether the runtime evaluates if()/and()/or() lazily or eagerly. |
| V-INVOKER | all | The invoker Users reference runs with the run-only user's own connection inside the solution (formerly gate V-6). |
| V-SKIPPED | all | `actions('X')` of a skipped action is readable null-safely (`?[]`) and reports `Skipped`. |
| V-FAILONERROR | ReadOwn, SaveEntry | A Compose whose date expression is invalid fails, and the flow continues through its `runAfter: Failed` branch. |
| V-ERROR-RESPONDER | all | A second Response action that runs after `Respond` is `Skipped` (`Respond_error`) returns to Power Apps when an earlier mandatory step failed (caller profile → `DIRECTORY_ERROR`, mandatory audit → `INTERNAL_ERROR`), and never runs when `Respond` ran. |
| V-ETAG | SaveEntry | `odata.etag` read back after a MERGE is the new ETag. If it can't be read, the response has an empty ETag and `WARN_RELOAD_REQUIRED`. |

## V-LAZY — lazy branch evaluation

The offline simulator can evaluate if()/and()/or() in three modes: `lazy`, `eager` and `audit`.
- **Audit sweep:** `tools/powerautomate/lazy_if_audit.py` runs the flow parity suites in audit mode. The suites are AppStart, ReadOwn, SaveEntry, the guard and maintenance.
- **Before the rewrite:** the sweep found 35 expressions that depended on lazy evaluation:
  - the null-coalesce helper, which applied `string()` inside the if();
  - `int()` and `formatDateTime()` on unvalidated input;
  - `body()` of a skipped action;
  - maintenance number checks.
- **After the rewrite:** the sweep finds 0. Every parity suite passes in both lazy and eager mode (`test_lazy_if.py` LZ02/LZ03).

Simulator results are not live proof. The first-live probe `tools/powerautomate/build_lazy_probe_flow.py` runs the exact expression builders the R1 templates use. It is not deployed.

| Case | Expression (as used by R1) | Safe-branch input | Invalid unused-branch input | Expected | Failure mode if evaluation were eager and the old form were kept |
|---|---|---|---|---|---|
| NZ | `string(if(equals(x, null), '', x))` | `x` = null | `string(null)` (old form) | `''` | null-coalesce helper fails: guard, audit and edit checks error |
| ITEMID | `int(if(empty(raw), '0', if(<digits>, raw, '-1')))` | `raw` = `'abc'` | `int('abc')` (old form) | `-1` (→ `NOT_FOUND`) | save fails for a non-numeric ItemId instead of returning `NOT_FOUND` |
| RANGE | reversed-range test on dates replaced by `'2000-01-01'` unless well-formed | `FromDate` = `'2026-02-30'` | `formatDateTime('2026-02-30')` after `and(false, …)` | `false`, no error | read fails instead of returning `VALIDATION_DATE` |
| SKIPPED | `if(<status> = Succeeded, actions('X')?['outputs']?['body']?['value'], createArray())` | `X` skipped | `body('X')` of a skipped action | `[]` | read fails after any refusal (query skipped) |

The probe reports `NEW_*` (the R1 forms) and `OLD_*` (the former forms) with status and value.
- **Gate:** every `NEW_*` Succeeded with its expected value, and `DATE_CHECK` = `Failed` (V-FAILONERROR).
- **Informational:** `OLD_*` = Succeeded means the runtime short-circuits; Failed means it evaluates eagerly. Either outcome is fine, because R1 no longer uses those forms.

## V-ETAG — new ETag after an edit

Contract: an edit that persisted is always `ok = true`.
- If the new ETag cannot be read back, or equals the ETag that was sent, the response has `etag = ""` and `warnings` contains `WARN_RELOAD_REQUIRED`.
- The client then discards any ETag it holds for the item and re-reads it before another edit.
- A stale ETag is never returned as current. A later edit with the old ETag gets `CONFLICT` (tests ET01–ET07).

The live check confirms that the read-back after a MERGE returns the new ETag.
