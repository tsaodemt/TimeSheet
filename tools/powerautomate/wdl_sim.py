"""Minimal offline interpreter for the Workflow Definition Language subset used by the guard template.

Purpose: execute generated flow actions against mocked connectors so the template's decision logic can be
compared with the Python reference. It is a test aid, not a Power Automate emulator: only the functions
and action types the guard uses are implemented, and anything unsupported raises instead of guessing.
Strict on purpose: string(null), indexing null without '?', unknown functions -> error.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo


class WdlError(Exception):
    pass


# Branch evaluation of if() / and() / or():
#   lazy  - only the selected branch / short-circuit (what the generated flows were first written against)
#   eager - every argument is evaluated; an error in an unused branch fails the expression (the opposite assumption)
#   audit - lazy result, but every unused branch is also evaluated and its error recorded in LAZY_HITS
# Flows that pass their parity tests in both lazy and eager mode do not depend on the runtime's choice.
BRANCH_MODE = os.environ.get("TS_WDL_BRANCHES", "lazy")
LAZY_HITS = []


def unparse(n) -> str:
    if n[0] == "lit":
        v = n[1]
        return "null" if v is None else ("'%s'" % v.replace("'", "''") if isinstance(v, str) else json.dumps(v))
    if n[0] == "idx":
        return "%s%s[%s]" % (unparse(n[1]), "?" if n[3] else "", unparse(n[2]))
    return "%s(%s)" % (n[1], ", ".join(unparse(a) for a in n[2]))


def _tokens(s):
    i, out = 0, []
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
        elif ch == "'":
            j, buf = i + 1, []
            while True:
                if j >= len(s):
                    raise WdlError("unterminated string")
                if s[j] == "'":
                    if j + 1 < len(s) and s[j + 1] == "'":
                        buf.append("'"); j += 2; continue
                    break
                buf.append(s[j]); j += 1
            out.append(("str", "".join(buf))); i = j + 1
        elif ch.isdigit() or (ch == "-" and i + 1 < len(s) and s[i + 1].isdigit()):
            m = re.match(r"-?\d+(\.\d+)?", s[i:])
            out.append(("num", float(m.group()) if m.group(1) else int(m.group()))); i += len(m.group())
        elif ch.isalpha() or ch == "_":
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", s[i:])
            out.append(("id", m.group())); i += len(m.group())
        elif ch in "(),[]?.":
            out.append((ch, ch)); i += 1
        else:
            raise WdlError("bad char %r in %s" % (ch, s))
    return out


class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self, kind=None):
        tok = self.peek()
        if kind and tok[0] != kind:
            raise WdlError("expected %s got %s" % (kind, tok))
        self.i += 1
        return tok

    def expr(self):
        kind, val = self.take()
        if kind in ("str", "num"):
            node = ("lit", val)
        elif kind == "id":
            if val in ("true", "false", "null") and self.peek()[0] != "(":
                node = ("lit", {"true": True, "false": False, "null": None}[val])
            else:
                self.take("(")
                args = []
                if self.peek()[0] != ")":
                    args.append(self.expr())
                    while self.peek()[0] == ",":
                        self.take(","); args.append(self.expr())
                self.take(")")
                node = ("call", val, args)
        else:
            raise WdlError("unexpected %s" % kind)
        while True:
            safe = False
            if self.peek()[0] == "?" and self.peek(1)[0] in ("[", "."):
                self.take("?"); safe = True
            if self.peek()[0] == "[":
                self.take("["); idx = self.expr(); self.take("]")
                node = ("idx", node, idx, safe)
            elif self.peek()[0] == ".":
                self.take("."); node = ("idx", node, ("lit", self.take("id")[1]), safe)
            else:
                return node


def parse(s):
    p = _P(_tokens(s))
    n = p.expr()
    if p.i != len(p.t):
        raise WdlError("trailing tokens in %s" % s)
    return n


def _str(v):
    if v is None:
        raise WdlError("string(null)")
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if isinstance(v, float) and v.is_integer():  # Power Automate renders an integral double without ".0"
        return str(int(v))
    return str(v)


def _empty(v):
    return v is None or v == "" or v == [] or v == {}


# Windows time-zone ids used by convertToUtc in the simulator (fixed, no-DST zones plus one DST zone for tests).
_WIN_TO_IANA = {"SE Asia Standard Time": "Asia/Bangkok", "UTC": "UTC", "Pacific Standard Time": "America/Los_Angeles"}
_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?)?(Z)?$")


def _parse_ts(s):
    m = _TS.match(_str(s).strip())
    if not m:
        raise WdlError("not a timestamp: %r" % s)
    y, mo, d, hh, mi, ss, z = m.groups()
    try:
        t = _dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
    except ValueError as e:
        raise WdlError("invalid timestamp %r" % s) from e
    return t, bool(z)


def _fmt(t, fmt):
    if fmt in (None, "o"):
        return t.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    out = fmt
    for a, b in (("yyyy", "%Y"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S")):  # yyyy-MM too
        out = out.replace(a, b)
    if re.search(r"[A-Za-z]", re.sub(r"%[YmdHMS]|[TZ]", "", out)):
        raise WdlError("unsupported format %r" % fmt)
    return t.strftime(out)


class Run:
    def __init__(self, trigger_body=None, run_name="run-0", mocks=None, now="2026-01-01T00:00:00Z", branches=None):
        self.branches = branches or BRANCH_MODE
        self.terminated = None  # inputs of a Terminate action (run ended Failed / Cancelled), else None
        self.action = None
        self.now = now  # utcNow() value (fixed so outputs are comparable)
        self.trigger_body = trigger_body or {}
        self.run_name = run_name
        self.mocks = mocks  # callable(action_name, action_def, evaluated_params) -> (status, body)
        self.results = {}   # name -> {"status", "outputs", "body"}
        self.item_stack = []
        self.vars = {}
        self.loop_items = {}

    # ---- expressions
    def ev(self, n):
        kind = n[0]
        if kind == "lit":
            return n[1]
        if kind == "idx":
            base = self.ev(n[1])
            key = self.ev(n[2])
            if base is None:
                if n[3]:
                    return None
                raise WdlError("index into null")
            if isinstance(base, list):
                return base[int(key)] if isinstance(key, int) and 0 <= key < len(base) else self._miss(n[3])
            if isinstance(base, dict):
                if key in base:
                    return base[key]
                return self._miss(n[3])
            raise WdlError("index into %r" % type(base))
        name, args = n[1], n[2]
        if name in ("if", "and", "or"):
            return self._branch(name, n, args)
        v = [self.ev(a) for a in args]
        f = getattr(self, "f_" + name, None)
        if f is None:
            raise WdlError("unsupported function %s" % name)
        return f(*v)

    def _branch(self, name, n, args):
        if self.branches == "eager":
            v = [self.ev(a) for a in args]
            return (v[1] if v[0] else v[2]) if name == "if" else (all(v) if name == "and" else any(v))
        if name == "if":
            cond = self.ev(args[0])
            used, unused = (args[1], args[2]) if cond else (args[2], args[1])
            out, rest = self.ev(used), [unused]
        else:
            out, rest = (name == "or"), []
            for i, a in enumerate(args):
                if bool(self.ev(a)) == (name == "or"):
                    rest = list(args[i + 1:])
                    break
            else:
                out = (name == "and")
        if self.branches == "audit":
            for a in rest:
                try:
                    self.ev(a)
                except Exception as e:  # noqa: BLE001 - any evaluation error is what an eager runtime would raise
                    LAZY_HITS.append({"action": self.action, "function": name, "expression": unparse(n),
                                      "unused": unparse(a), "error": "%s: %s" % (type(e).__name__, e)})
        return out

    @staticmethod
    def _miss(safe):
        if safe:
            return None
        raise WdlError("missing member")

    def f_toLower(self, s): return _str(s).lower()
    def f_trim(self, s): return _str(s).strip()
    def f_empty(self, x):
        if x is not None and not isinstance(x, (str, list, dict)):
            raise WdlError("empty() expects an object, an array or a string, got %s" % type(x).__name__)
        return _empty(x)
    def f_not(self, x): return not x
    def f_equals(self, a, b):
        if isinstance(a, bool) != isinstance(b, bool):
            return False
        return a == b
    def f_greater(self, a, b): return a > b
    def f_less(self, a, b): return a < b
    def f_setProperty(self, obj, k, v): return dict(obj, **{k: v})
    def f_union(self, a, b):  # arrays: items of a then new items of b, duplicates removed (Power Automate semantics)
        out = []
        for x in list(a or []) + list(b or []):
            if x not in out:
                out.append(x)
        return out
    def f_intersection(self, a, b):  # arrays: items of a also in b, duplicates removed (Power Automate semantics)
        out = []
        for x in list(a or []):
            if x in list(b or []) and x not in out:
                out.append(x)
        return out
    def f_startsWith(self, s, t): return _str(s).lower().startswith(_str(t).lower())
    def f_float(self, x): return float(x)
    def f_removeProperty(self, obj, k): return {x: v for x, v in obj.items() if x != k}
    def f_length(self, x): return len(x)
    def f_first(self, x): return x[0] if x else None
    def f_string(self, x): return _str(x)
    def f_int(self, x): return int(x)
    def f_json(self, s): return json.loads(s)
    def f_xml(self, x):  # only what the report flows use: a JSON object document for xpath('sum(/a/b)')
        if not isinstance(x, dict) or len(x) != 1:
            raise WdlError("xml() needs an object with one root")
        return ("__xml__", x)

    def f_xpath(self, doc, expr):
        m = re.fullmatch(r"sum\(/(\w+)/(\w+)\)", expr)
        if not (isinstance(doc, tuple) and doc[0] == "__xml__" and m):
            raise WdlError("unsupported xpath %r" % expr)
        root = doc[1].get(m.group(1)) or {}
        v = root.get(m.group(2)) if isinstance(root, dict) else None
        vals = v if isinstance(v, list) else ([] if v is None else [v])
        return float(sum(float(x) for x in vals))
    def f_createArray(self, *a):
        if not a:  # Power Automate: "expects a comma separated list of parameters" (InvalidTemplate)
            raise WdlError("createArray() expects at least one parameter")
        return list(a)
    def f_max(self, *a): return max(a)
    def f_coalesce(self, *a): return next((x for x in a if x is not None), None)
    def f_min(self, *a): return min(a)
    def f_endsWith(self, s, t): return _str(s).lower().endswith(_str(t).lower())
    def f_replace(self, s, a, b): return _str(s).replace(a, b)
    def f_concat(self, *a): return "".join(_str(x) for x in a)
    def f_join(self, arr, sep): return sep.join(_str(x) for x in arr)
    def f_substring(self, s, i, n=None): return _str(s)[i:] if n is None else _str(s)[i:i + n]
    def f_decodeUriComponent(self, s): return unquote(s)
    def f_encodeUriComponent(self, s): return quote(_str(s), safe="-_.!~*'()")
    def f_contains(self, coll, x): return x in coll
    def f_utcNow(self, fmt=None): return self.now
    def f_split(self, s, sep): return _str(s).split(sep)
    def f_indexOf(self, s, t): return _str(s).find(t)
    def f_add(self, a, b): return a + b
    # date functions (subset): timestamps are ISO-8601 strings; formats are .NET custom formats (yyyy MM dd HH mm ss)
    def f_formatDateTime(self, ts, fmt="o"): return _fmt(_parse_ts(ts)[0], fmt)
    def f_addDays(self, ts, n, fmt=None):
        t, _ = _parse_ts(ts)
        t = t + _dt.timedelta(days=int(n))
        return _fmt(t, fmt) if fmt else t.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    def f_convertToUtc(self, ts, tz, fmt=None):
        t, zoned = _parse_ts(ts)
        if zoned:
            raise WdlError("convertToUtc expects a local (unzoned) timestamp")
        if tz not in _WIN_TO_IANA:
            raise WdlError("unknown time zone %s" % tz)
        u = t.replace(tzinfo=ZoneInfo(_WIN_TO_IANA[tz])).astimezone(_dt.timezone.utc).replace(tzinfo=None)
        return _fmt(u, fmt) if fmt else u.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    def f_convertFromUtc(self, ts, tz, fmt=None):
        t, _ = _parse_ts(ts)
        if tz not in _WIN_TO_IANA:
            raise WdlError("unknown time zone %s" % tz)
        u = t.replace(tzinfo=_dt.timezone.utc).astimezone(ZoneInfo(_WIN_TO_IANA[tz])).replace(tzinfo=None)
        return _fmt(u, fmt) if fmt else u.strftime("%Y-%m-%dT%H:%M:%S.0000000")
    def f_guid(self):
        self._guid = getattr(self, "_guid", 0) + 1
        return "00000000-0000-4000-8000-%012d" % self._guid
    def f_last(self, x): return x[-1] if x else None
    def f_div(self, a, b): return a // b if isinstance(a, int) and isinstance(b, int) else a / b
    def f_sub(self, a, b): return a - b
    def f_mul(self, a, b): return a * b
    def f_mod(self, a, b):  # Power Automate mod(): remainder with the sign of the dividend (integers here)
        r = abs(a) % abs(b)
        return -r if a < 0 else r
    def f_variables(self, n): return self.vars[n]
    def f_items(self, n): return self.loop_items[n]
    def f_workflow(self): return {"run": {"name": self.run_name}}
    def f_triggerBody(self): return self.trigger_body
    def f_trigger(self): return self.trigger_body  # Recurrence: {"scheduledTime": ..., "startTime": ...}
    def f_addMinutes(self, ts, n, fmt=None):
        t, _ = _parse_ts(ts)
        t = t + _dt.timedelta(minutes=int(n))
        return _fmt(t, fmt) if fmt else t.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    def f_greaterOrEquals(self, a, b): return a >= b
    def f_item(self): return self.item_stack[-1]
    def f_actions(self, n): return {"status": self.results[n]["status"], "outputs": self.results[n]["outputs"]} if n in self.results else None
    def f_body(self, n): return self.results[n]["body"]
    def f_outputs(self, n): return self.results[n]["outputs"]
    def f_parameters(self, n): return {}

    def value(self, x):
        """Evaluate an action input: '@expr', '@{interp}' strings, and containers recursively."""
        if isinstance(x, dict):
            return {k: self.value(v) for k, v in x.items()}
        if isinstance(x, list):
            return [self.value(v) for v in x]
        if not isinstance(x, str) or "@" not in x:
            return x
        if x.startswith("@") and not x.startswith("@{"):
            return self.ev(parse(x[1:]))
        out, i = [], 0
        while True:
            j = x.find("@{", i)
            if j < 0:
                out.append(x[i:]); break
            out.append(x[i:j])
            k, depth, q = j + 2, 0, False
            while True:
                ch = x[k]
                if q:
                    if ch == "'":
                        if k + 1 < len(x) and x[k + 1] == "'":
                            k += 1
                        else:
                            q = False
                elif ch == "'":
                    q = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    if depth == 0:
                        break
                    depth -= 1
                k += 1
            v = self.ev(parse(x[j + 2:k]))
            out.append("" if v is None else _str(v))
            i = k + 1
        return "".join(out)

    # ---- actions
    def run(self, actions):
        pending = dict(actions)
        while pending:
            progressed = False
            for name, a in list(pending.items()):
                deps = a.get("runAfter", {})
                if any(d not in self.results for d in deps):
                    continue
                del pending[name]
                progressed = True
                if not all(self.results[d]["status"] in st for d, st in deps.items()):
                    self.results[name] = {"status": "Skipped", "outputs": None, "body": None}
                    continue
                self._exec(name, a)
            if not progressed:
                raise WdlError("dependency cycle or unknown runAfter: %s" % list(pending))
        return self

    def _cond(self, e):
        """If-action expression object: {"equals": [a, b]} | {"not": {...}} | {"and": [...]} | {"or": [...]}."""
        (op, arg), = e.items()
        if op == "equals":
            return self.f_equals(self.value(arg[0]), self.value(arg[1]))
        if op == "not":
            return not self._cond(arg)
        if op == "and":
            return all(self._cond(x) for x in arg)
        if op == "or":
            return any(self._cond(x) for x in arg)
        raise WdlError("unsupported condition %s" % op)

    def _exec(self, name, a):
        t = a["type"]
        self.action = name
        if t == "Compose":
            if (a.get("metadata") or {}).get("failOnError"):  # expression errors fail the action, as in Power Automate (only where a flow handles it)
                try:
                    v = self.value(a["inputs"])
                except (WdlError, ValueError, TypeError, KeyError) as e:
                    self.results[name] = {"status": "Failed", "outputs": None, "body": None, "error": str(e)}
                    return
            else:
                v = self.value(a["inputs"])
            self.results[name] = {"status": "Succeeded", "outputs": v, "body": v}
        elif t == "InitializeVariable":
            v = a["inputs"]["variables"][0]
            self.vars[v["name"]] = self.value(v.get("value"))
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t == "IncrementVariable":
            self.vars[a["inputs"]["name"]] += self.value(a["inputs"]["value"])
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t == "SetVariable":
            self.vars[a["inputs"]["name"]] = self.value(a["inputs"]["value"])
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t == "AppendToArrayVariable":
            self.vars[a["inputs"]["name"]] = self.vars[a["inputs"]["name"]] + [self.value(a["inputs"]["value"])]
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t == "Foreach":
            for it in self.value(a["foreach"]):
                self.loop_items[name] = it
                for k in _nested_names(a["actions"]):  # every iteration starts clean, nested If branches included
                    self.results.pop(k, None)
                self.run(a["actions"])
            self.loop_items.pop(name, None)
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t == "Until":  # do-until: run the body, then test the expression; capped by limit.count (default 60)
            limit = int(((a.get("limit") or {}).get("count")) or 60)
            for _ in range(limit):
                for k in _nested_names(a["actions"]):
                    self.results.pop(k, None)
                self.run(a["actions"])
                if self.value(a["expression"]):
                    break
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t in ("Select", "Query") and (a.get("metadata") or {}).get("failOnError"):
            # a non-array source or an item expression error fails the action, as in Power Automate (only where a flow handles it)
            try:
                src = self.value(a["inputs"]["from"])
                if not isinstance(src, list):
                    raise WdlError("from is not an array")
                self._exec(name, dict(a, metadata={}))
            except (WdlError, ValueError, TypeError, KeyError) as e:
                self.results[name] = {"status": "Failed", "outputs": None, "body": None, "error": str(e)}
        elif t == "Select":
            src = self.value(a["inputs"]["from"])
            out = []
            for it in src:
                self.item_stack.append(it)
                try:
                    out.append(self.value(a["inputs"]["select"]))
                finally:
                    self.item_stack.pop()
            self.results[name] = {"status": "Succeeded", "outputs": {"body": out}, "body": out}
        elif t == "Query":
            src = self.value(a["inputs"]["from"])
            out = []
            for it in src:
                self.item_stack.append(it)
                try:
                    if self.value(a["inputs"]["where"]):
                        out.append(it)
                finally:
                    self.item_stack.pop()
            self.results[name] = {"status": "Succeeded", "outputs": {"body": out}, "body": out}
        elif t == "OpenApiConnection":
            params = self.value(a["inputs"]["parameters"])
            status, body = self.mocks(name, a, params)
            outs = {"body": body}
            if isinstance(body, dict) and "statusCode" in body:  # mock convention: connector HTTP status
                outs["statusCode"] = body["statusCode"]
            self.results[name] = {"status": status, "outputs": outs, "body": body}
        elif t == "If":
            cond = self._cond(a["expression"])
            branch = a["actions"] if cond else a.get("else", {}).get("actions", {})
            self.run(branch)
            self.results[name] = {"status": "Succeeded", "outputs": None, "body": None}
        elif t == "Response":
            v = self.value(a["inputs"]["body"])
            self.results[name] = {"status": "Succeeded", "outputs": v, "body": v}
        elif t == "Terminate":
            v = self.value(a["inputs"])
            self.terminated = v
            self.results[name] = {"status": "Succeeded", "outputs": v, "body": None}
        else:
            raise WdlError("unsupported action type %s" % t)


def _nested_names(actions):
    for k, a in actions.items():
        yield k
        yield from _nested_names(a.get("actions") or {})
        yield from _nested_names((a.get("else") or {}).get("actions") or {})


_GET = re.compile(r"getbytitle\('([^']*)'\)/items\?.*\$filter=(\w+) eq '((?:[^']|'')*)'&\$top=(\d+)")


def sharepoint_get(uri, lists):
    """Mock SharePoint REST GET with one `Field eq 'value'` filter and $top. lists: title -> rows."""
    m = _GET.search(uri)
    if not m:
        raise WdlError("unsupported uri %s" % uri)
    title, fld, val, top = m.group(1), m.group(2), m.group(3).replace("''", "'"), int(m.group(4))
    rows = [r for r in lists[title] if r.get(fld) is not None and str(r.get(fld)).lower() == val.lower()]
    return {"value": rows[:top]}
