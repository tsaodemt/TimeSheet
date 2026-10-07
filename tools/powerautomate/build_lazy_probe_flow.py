"""First-live runtime probe V-LAZY / V-SKIPPED / V-FAILONERROR (offline template; NOT deployed).

The R1 flows were rewritten so that no expression depends on lazy if()/and()/or() evaluation (lazy_if_audit.py:
0 dependent expressions; every parity suite passes in lazy and eager simulator mode). This probe confirms it on the
real runtime with the exact expression builders the R1 templates use, each fed an input whose UNUSED branch is
invalid. For every case it also evaluates the former (lazy-dependent) form, to record how the runtime behaves.

Gate (first-live check): every NEW_* compose Succeeded with its expected value. OLD_* results are informational:
Succeeded = the runtime short-circuits; Failed = it evaluates eagerly (then the rewrite was necessary).
"""
from __future__ import annotations

import build_r1_flows as r1
import build_read_flow as base
import date_range as dr
import guard_template as gt

c, S = base.c, base.S

# (case, new expression as used by R1, old lazy-dependent form, inputs, expected new value, what eager evaluation does to OLD)
CASES = [
    ("NZ", gt.nz("outputs('In_null')"), "if(equals(outputs('In_null'), null), substring('x', 0, 0), string(outputs('In_null')))",
     "In_null = null", "", "string(null) evaluated in the unused branch"),
    ("ITEMID", "int(if(empty(outputs('In_abc')), '0', if(%s, outputs('In_abc'), '-1')))" % r1._int_text_ok("outputs('In_abc')"),
     "if(empty(outputs('In_abc')), 0, if(%s, int(outputs('In_abc')), -1))" % r1._int_text_ok("outputs('In_abc')"),
     "In_abc = 'abc' (TS-SaveEntry ItemId)", -1, "int('abc') evaluated in the unused branch"),
    ("RANGE", dr.reversed_range_expr("if(false, outputs('In_bad_date'), '2000-01-01')", "if(false, outputs('In_bad_date'), '2000-01-01')"),
     "and(false, %s)" % dr.reversed_range_expr("outputs('In_bad_date')", "'2026-03-01'"),
     "In_bad_date = '2026-02-30' (TS-ReadOwn reversed-range check)", False, "formatDateTime('2026-02-30') evaluated after and(false, ...)"),
    ("SKIPPED", r1._rows("Skipped_get"), "if(equals(actions('Skipped_get')?['status'], 'Succeeded'), body('Skipped_get')?['value'], createArray())",
     "Skipped_get never runs (If false)", [], "body() of a skipped action"),
]


def probe_actions() -> dict:
    g = {"In_null": c("@null", {}), "In_abc": c("abc", S("In_null")), "In_bad_date": c("2026-02-30", S("In_abc"))}
    g["If_never"] = {"type": "If", "runAfter": S("In_bad_date"), "expression": {"equals": [1, 2]},
                     "actions": {"Skipped_get": c("@json('{\"value\": [1]}')", {})}, "else": {"actions": {}}}
    prev = "If_never"
    for name, new, old, _, _, _ in CASES:
        for kind, expr in (("NEW", new), ("OLD", old)):
            n = "%s_%s" % (kind, name)
            g[n] = dict(c("@" + expr, {prev: ["Succeeded", "Failed", "Skipped"]}), metadata={"failOnError": True})
            prev = n
    # V-FAILONERROR: an invalid date fails its Compose; the next action still runs through runAfter Failed
    g["Date_check"] = dict(c("@formatDateTime(outputs('In_bad_date'), 'yyyy-MM-dd')", {prev: ["Succeeded", "Failed", "Skipped"]}),
                           metadata={"failOnError": True})
    g["After_date_check"] = c("@actions('Date_check')?['status']", {"Date_check": ["Succeeded", "Failed"]})
    body = {n: "@{actions('%s')?['status']}|@{%s}" % (n, gt.nz("outputs('%s')" % n))
            for n in ["%s_%s" % (k, x[0]) for x in CASES for k in ("NEW", "OLD")]}
    body["DATE_CHECK"] = "@{outputs('After_date_check')}"
    g["Respond"] = {"type": "Response", "kind": "Http", "runAfter": S("After_date_check"), "inputs": {"statusCode": 200, "body": body}}
    return base._fix(g)
