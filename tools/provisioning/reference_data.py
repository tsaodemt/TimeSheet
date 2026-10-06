"""Idempotent reference-data (seed) reconciliation for small master lists (generic; no tenant data in code).

    seed rows (JSON, from the canonical extract) + list rules (JSON) + actual items (read-only)
      -> validate_seed()   -> seed problems (any problem stops the load)
      -> reconcile_items() -> findings: OK | CREATE | DRIFT | EXTRA | BLOCKED
      -> plan_items()      -> CREATE only; drift is reported, never "fixed" automatically
      -> apply_items()     -> dry-run by default; exact site-URL guard; refuses while the list schema is not OK,
                              while the seed is invalid, or while any item is BLOCKED; never updates or deletes

A second run after a successful load plans nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Callable, Iterable, Optional

from schema_reconcile import OK, CREATE, BLOCKED, EXTRA, SiteGuardError, guard_site

DRIFT = "DRIFT"

# Item operations and their rollback class.
ROLLBACK = {
    "create_item": "REVERSIBLE while nothing references the item; REVERSIBLE-WITH-DATA-RISK once referenced by a lookup",
}

TRANSFORMS = {
    # legacy parity (e.g. an hour-type factor <= 0 or empty is treated as 1)
    "nonpositive_or_null_to_1": lambda v: 1 if v is None or v == "" or float(v) <= 0 else v,
    "strip": lambda v: v.strip() if isinstance(v, str) else v,
}


@dataclass
class Problem:
    rule: str
    detail: str


@dataclass
class ItemFinding:
    status: str
    list: str
    key: str
    detail: str = ""
    ops: list = dc_field(default_factory=list)

    def line(self) -> str:
        return "%-10s %-14s %-40s %s" % (self.status, self.list, self.key, self.detail)


def normalise(rows: Iterable[dict], rules: dict) -> list:
    """Apply the declared migration transforms (copy; the input is not changed)."""
    out = []
    for r in rows:
        r = dict(r)
        for fname, tname in (rules.get("transforms") or {}).items():
            r[fname] = TRANSFORMS[tname](r.get(fname))
        out.append(r)
    return out


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "1"))


def validate_seed(rows: list, rules: dict, settings: Optional[dict] = None) -> list:
    """Rule checks on a seed. `settings` supplies values that rules may reference (e.g. NormalHourTypeCode)."""
    p = []
    key, code = rules["key"], rules.get("code")
    if rules.get("expectedCount") is not None and len(rows) != rules["expectedCount"]:
        p.append(Problem("count", "%d rows, expected %d" % (len(rows), rules["expectedCount"])))
    for f in rules.get("required", []):
        miss = [r.get(key, "?") for r in rows if r.get(f) in (None, "")]
        if miss:
            p.append(Problem("required", "%s empty for %s" % (f, miss)))
    for f in [key] + ([code] if code else []) + list(rules.get("unique", [])):
        seen, dup = set(), set()
        for r in rows:
            v = r.get(f)
            v = v.strip().lower() if isinstance(v, str) else v  # SharePoint uniqueness is case-insensitive
            (dup if v in seen else seen).add(v)
        dup.discard(None)
        if dup:
            p.append(Problem("unique", "%s duplicated: %s" % (f, sorted(map(str, dup)))))
    for f in rules.get("positive", []):
        bad = [r.get(key) for r in rows if not isinstance(r.get(f), (int, float)) or r.get(f) <= 0]
        if bad:
            p.append(Problem("positive", "%s must be > 0 for %s" % (f, bad)))
    for f in rules.get("exactlyOneTrue", []):
        n = sum(1 for r in rows if _truthy(r.get(f)))
        if n != 1:
            p.append(Problem("exactlyOneTrue", "%s is true on %d rows, expected 1" % (f, n)))
    if rules.get("firstBySortOrderIs"):
        f = rules["firstBySortOrderIs"]
        ordered = sorted(rows, key=lambda r: (r.get("SortOrder") is None, r.get("SortOrder")))
        if ordered and not _truthy(ordered[0].get(f)):
            p.append(Problem("firstBySortOrderIs", "%s is not set on the first row by SortOrder (%s)" % (f, ordered[0].get(key))))
    for rule in rules.get("flagIffCodeIn", []):
        codes = set(rule.get("codes") or [])
        if rule.get("codesFromSetting"):
            v = (settings or {}).get(rule["codesFromSetting"])
            if v in (None, ""):
                p.append(Problem("flagIffCodeIn", "setting %s unresolved; %s cannot be checked" % (rule["codesFromSetting"], rule["field"])))
                continue
            codes |= {v}
        up = {c.upper() for c in codes}
        wrong = [r.get(code) for r in rows if _truthy(r.get(rule["field"])) != (str(r.get(code, "")).upper() in up)]
        if wrong:
            p.append(Problem("flagIffCodeIn", "%s must be true exactly for %s; wrong on %s" % (rule["field"], sorted(codes), wrong)))
    return p


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return _truthy(a) == _truthy(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-9
    return (a if a is not None else "") == (b if b is not None else "")


def reconcile_items(list_title: str, rows: list, actual_items: list, rules: dict) -> list:
    """Compare seed rows with the items on the site, matched by the business key. Never mutates anything."""
    key, code = rules["key"], rules.get("code")
    compared = rules.get("compare") or sorted({k for r in rows for k in r})
    by_key = {str(i.get(key)): i for i in actual_items if i.get(key) not in (None, "")}
    by_code = {str(i.get(code)).lower(): i for i in actual_items if code and i.get(code) not in (None, "")}
    out = []
    for r in rows:
        k = str(r[key])
        a = by_key.get(k)
        if a is None:
            clash = by_code.get(str(r.get(code)).lower()) if code else None
            if clash is not None:
                out.append(ItemFinding(BLOCKED, list_title, k, "%s %r already used by item with %s %r" % (code, r.get(code), key, clash.get(key))))
            else:
                out.append(ItemFinding(CREATE, list_title, k, "item missing", [("create_item", r)]))
            continue
        diff = [f for f in compared if f in r and not _same(r.get(f), a.get(f))]
        if diff:
            out.append(ItemFinding(DRIFT, list_title, k, "differs: " + ", ".join(
                "%s site=%r seed=%r" % (f, a.get(f), r.get(f)) for f in diff) + " (not changed automatically)"))
        else:
            out.append(ItemFinding(OK, list_title, k))
    seed_keys = {str(r[key]) for r in rows}
    for i in actual_items:
        if str(i.get(key)) not in seed_keys:
            out.append(ItemFinding(EXTRA, list_title, str(i.get(key)), "on the site, not in the seed (never deleted automatically)"))
    return out


def plan_items(findings: Iterable[ItemFinding]) -> list:
    return [(f.list, f.key, op) for f in findings if f.status == CREATE for op in f.ops]


class ItemClient:
    """Mutation interface used by apply_items(). Implementations: RestItemClient (live), fakes in tests."""
    def create_item(self, list_title: str, values: dict) -> None: raise NotImplementedError


@dataclass
class ItemApplyResult:
    executed: list
    skipped: list
    dry_run: bool


def apply_items(list_title: str, rows: list, actual_items: list, rules: dict, client: ItemClient, site_url: str, *,
                allowed_url: Optional[str], schema_findings: Iterable, settings: Optional[dict] = None,
                dry_run: bool = True) -> ItemApplyResult:
    """Load missing seed rows. Preconditions, all checked before any call:
    exact site; the list and every target column reconcile OK; the seed is valid; no item is BLOCKED."""
    guard_site(site_url, allowed_url)
    not_ok = [f for f in schema_findings if f.list == list_title and f.status != OK]
    if not [f for f in schema_findings if f.list == list_title] or not_ok:
        raise SiteGuardError("list schema not reconciled OK, nothing loaded: " + "; ".join(
            "%s %s" % (f.field or "(list)", f.status) for f in not_ok) if not_ok else "list %s not in the schema findings" % list_title)
    rows = normalise(rows, rules)
    problems = validate_seed(rows, rules, settings)
    if problems:
        raise SiteGuardError("invalid seed, nothing loaded: " + "; ".join(p.rule + ": " + p.detail for p in problems))
    findings = reconcile_items(list_title, rows, actual_items, rules)
    blocked = [f for f in findings if f.status == BLOCKED]
    if blocked:
        raise SiteGuardError("item conflicts, nothing loaded: " + "; ".join(f.key + " " + f.detail for f in blocked))
    steps = plan_items(findings)
    if dry_run:
        return ItemApplyResult([], steps, True)
    done = []
    for lst, k, (op, values) in steps:
        client.create_item(lst, {f: values[f] for f in rules.get("load") or values})
        done.append((lst, k, op))
    return ItemApplyResult(done, [], False)


class RestItemClient(ItemClient):
    """Uses transport(method, path, body, headers) -> (status, json). Paths are site-relative."""
    VERBOSE = {"Accept": "application/json;odata=verbose", "Content-Type": "application/json;odata=verbose"}

    def __init__(self, transport: Callable):
        self.t = transport

    def _call(self, method, path, body=None):
        status, data = self.t(method, path, body, dict(self.VERBOSE))
        if status >= 300:
            raise RuntimeError("%s %s -> %s %s" % (method, path, status, json.dumps(data)[:300]))
        return data

    def create_item(self, list_title, values):
        q = list_title.replace("'", "''")
        etype = self._call("GET", "/_api/web/lists/getbytitle('%s')?$select=ListItemEntityTypeFullName" % q)["d"]["ListItemEntityTypeFullName"]
        self._call("POST", "/_api/web/lists/getbytitle('%s')/items" % q, dict({"__metadata": {"type": etype}}, **values))
