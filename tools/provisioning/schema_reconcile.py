"""Idempotent SharePoint list-schema reconciliation and provisioning (generic; no tenant data in code).

    target schema (JSON, environment config)  +  actual schema (read-only inventory)
      -> reconcile()  -> findings: OK | CREATE | UPDATE-SAFE | BLOCKED-INCOMPATIBLE | DECISION-REQUIRED | GATED | EXTRA
      -> plan()       -> only CREATE / UPDATE-SAFE operations of objects that are neither gated nor undecided
      -> apply()      -> dry-run by default; exact site-URL guard; never deletes, renames or retypes anything

Run the reconciliation before and after provisioning: after a successful apply every planned item reports OK, and a
second apply plans nothing.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

OK, CREATE, UPDATE_SAFE = "OK", "CREATE", "UPDATE-SAFE"
BLOCKED, DECISION, GATED, EXTRA = "BLOCKED-INCOMPATIBLE", "DECISION-REQUIRED", "GATED", "EXTRA"
SYSTEM_FIELDS = {"ID", "Title", "Created", "Modified", "Author", "Editor"}

# Operation -> rollback class (SharePoint has no transactional schema rollback).
ROLLBACK = {
    "create_list": "REVERSIBLE (delete the empty list); REVERSIBLE-WITH-DATA-RISK once items exist",
    "create_field": "REVERSIBLE-WITH-DATA-RISK (deleting the column deletes its values); the internal name is fixed for ever",
    "set_indexed": "REVERSIBLE",
    "set_unique": "REVERSIBLE",
    "set_required": "REVERSIBLE",
    "add_choices": "REVERSIBLE-WITH-DATA-RISK (items may already use the new value)",
    "set_display_name": "REVERSIBLE",
}


class SiteGuardError(Exception):
    pass


def guard_site(url: str, allowed_url: Optional[str]) -> str:
    """Return the normalised URL if mutation is allowed there; raise otherwise.
    Rules: an allowed URL must be configured; the target must equal it exactly; a tenant root site is never allowed."""
    if not allowed_url:
        raise SiteGuardError("no allowed site configured")
    u, a = (url or "").rstrip("/"), allowed_url.rstrip("/")
    path = urlparse(u).path.strip("/")
    if not path.lower().startswith("sites/") and not path.lower().startswith("teams/"):
        raise SiteGuardError("root/tenant-level site is never a mutation target: %s" % u)
    if u != a:
        raise SiteGuardError("target %s is not the allowed site" % u)
    return u


@dataclass
class Finding:
    status: str
    list: str
    field: str = ""
    detail: str = ""
    ops: list = dc_field(default_factory=list)

    def line(self) -> str:
        where = self.list + ("." + self.field if self.field else "")
        return "%-21s %-45s %s" % (self.status, where, self.detail)


def _fmap(lst):
    return {f["internalName"]: f for f in lst.get("fields", [])}


def _field_checks(t: dict, a: dict) -> tuple:
    """(blocking problems, safe updates, decision notes) for one existing field."""
    block, ops, notes = [], [], []
    if t["type"] != a["type"]:
        block.append("type %s, expected %s" % (a["type"], t["type"]))
    if t["type"] == "DateTime" and bool(t.get("dateOnly")) != bool(a.get("dateOnly")):
        block.append("dateOnly %s, expected %s" % (a.get("dateOnly"), t.get("dateOnly")))
    if t.get("lookupList") and t["lookupList"] != a.get("lookupList"):
        block.append("lookup target %s, expected %s" % (a.get("lookupList"), t["lookupList"]))
    if block:
        return block, [], []
    if bool(t.get("indexed")) and not a.get("indexed"):
        ops.append(("set_indexed", True))
    if bool(t.get("unique")) and not a.get("unique"):
        ops.append(("set_unique", True))
    if bool(t.get("required")) != bool(a.get("required")):
        ops.append(("set_required", bool(t.get("required"))))
    if not t.get("indexed") and a.get("indexed") and not t.get("unique"):
        notes.append("indexed but not in target (kept; no automatic index removal)")
    if not t.get("unique") and a.get("unique"):
        notes.append("unique in actual but not in target (kept)")
    missing = [c for c in t.get("choices") or [] if c not in (a.get("choices") or [])]
    if missing:
        ops.append(("add_choices", missing))
    extra = [c for c in a.get("choices") or [] if c not in (t.get("choices") or [])]
    if t.get("choices") is not None and extra:
        notes.append("extra choices %s (kept)" % extra)
    if t.get("displayName") and t["displayName"] != a.get("displayName"):
        ops.append(("set_display_name", t["displayName"]))
    return block, ops, notes


def _title_ops(tf: dict) -> list:
    """The built-in Title column of a new list: required, plus index/unique where the target asks (e.g. a key list)."""
    ops = [("set_required", bool(tf.get("required")))]
    if tf.get("unique"):
        ops.append(("set_unique", True))
    elif tf.get("indexed"):
        ops.append(("set_indexed", True))
    if tf.get("displayName") and tf["displayName"] != "Title":
        ops.append(("set_display_name", tf["displayName"]))
    return ops


def _missing_list_status(tl: dict) -> tuple:
    """(status, detail) of a target list that does not exist on the site."""
    decision = tl.get("decision")
    if not decision:
        # An open decision on a field that cannot be fixed later (e.g. the internal name of the business key)
        # blocks the whole list: never create a list without its key column.
        key_decisions = [f["internalName"] + ": " + f["decision"] for f in tl["fields"]
                         if f.get("decision") and f.get("decisionBlocksList")]
        decision = "; ".join(key_decisions) or None
    if decision:
        return DECISION, decision
    if tl.get("gate"):
        return GATED, tl["gate"]
    return CREATE, "list missing"


def reconcile(target: dict, actual: dict) -> list:
    """Compare a target schema with an inventory. Never mutates anything."""
    out = []
    alists = {l["title"]: l for l in actual.get("lists", [])}
    missing = {tl["title"]: _missing_list_status(tl) for tl in target["lists"] if tl["title"] not in alists}
    available = set(alists) | {n for n, (s, _) in missing.items() if s == CREATE}

    def unavailable_lookup(tf):
        """A lookup column can only be created once its target list exists or is created in the same run."""
        t = tf.get("lookupList") if tf["type"] == "Lookup" else None
        if t and t not in available:
            return "lookup target %s not available (%s)" % (t, missing[t][0] if t in missing else "not in target")
        return None

    for tl in target["lists"]:
        name = tl["title"]
        al = alists.get(name)
        if al is None:
            status, detail = missing[name]
            out.append(Finding(status, name, detail=detail, ops=[] if status != CREATE else [("create_list", tl)]))
            if status != CREATE:
                continue
            for tf in tl["fields"]:
                if tf["internalName"] in SYSTEM_FIELDS and tf["internalName"] != "Title":
                    continue
                dep = unavailable_lookup(tf)
                fs = DECISION if tf.get("decision") else GATED if tf.get("gate") or dep else CREATE
                op = [] if fs != CREATE else ([("create_field", tf)] if tf["internalName"] != "Title" else _title_ops(tf))
                out.append(Finding(fs, name, tf["internalName"], tf.get("decision") or tf.get("gate") or dep or "new list", op))
            continue
        afields = _fmap(al)
        out.append(Finding(OK, name, detail="list exists (%d items)" % al.get("itemCount", 0)))
        for tf in tl["fields"]:
            fn = tf["internalName"]
            af = afields.get(fn)
            if tf.get("decision"):
                out.append(Finding(DECISION, name, fn, tf["decision"]))
                continue
            if af is None:
                dep = unavailable_lookup(tf)
                if tf.get("gate") or dep:
                    out.append(Finding(GATED, name, fn, tf.get("gate") or dep))
                else:
                    out.append(Finding(CREATE, name, fn, "column missing", [("create_field", tf)]))
                continue
            block, ops, notes = _field_checks(tf, af)
            if block:
                out.append(Finding(BLOCKED, name, fn, "; ".join(block)))
            elif tf.get("gate") and ops:
                out.append(Finding(GATED, name, fn, tf["gate"] + "; pending: " + ", ".join(o[0] for o in ops)))
            elif ops:
                pre = " (precondition: no duplicate values)" if any(o[0] == "set_unique" for o in ops) else ""
                out.append(Finding(UPDATE_SAFE, name, fn, ", ".join("%s=%s" % o for o in ops) + pre, ops))
            else:
                out.append(Finding(OK, name, fn, "; ".join(notes)))
        known = {f["internalName"] for f in tl["fields"]}
        for fn, af in afields.items():
            if fn not in known and not af.get("builtIn"):
                out.append(Finding(EXTRA, name, fn, "%s (not in target; never removed automatically)" % af["type"]))
    tnames = {l["title"] for l in target["lists"]}
    for name, al in alists.items():
        if name not in tnames and not al.get("system"):
            out.append(Finding(EXTRA, name, detail="list not in target (never removed automatically)"))
    return out


def plan(findings: Iterable[Finding]) -> list:
    """Executable operations only. A list whose own creation is gated/undecided contributes nothing.
    Every list is created before any column, so a lookup column always finds its target list."""
    ops = []
    for f in findings:
        if f.status in (CREATE, UPDATE_SAFE):
            ops.extend((f.list, f.field, op) for op in f.ops)
    return [o for o in ops if o[2][0] == "create_list"] + [o for o in ops if o[2][0] != "create_list"]


def summary(findings: Iterable[Finding]) -> dict:
    s = {}
    for f in findings:
        s[f.status] = s.get(f.status, 0) + 1
    return s


class SchemaClient:
    """Mutation interface used by apply(). Implementations: RestSchemaClient (live), fakes in tests."""
    def create_list(self, spec: dict) -> None: raise NotImplementedError
    def create_field(self, list_title: str, spec: dict) -> None: raise NotImplementedError
    def update_field(self, list_title: str, internal_name: str, op: str, value) -> None: raise NotImplementedError


@dataclass
class ApplyResult:
    executed: list
    skipped: list
    dry_run: bool


def apply(target: dict, actual: dict, client: SchemaClient, site_url: str, *, allowed_url: Optional[str],
          dry_run: bool = True) -> ApplyResult:
    """Execute the plan. Refuses any site but the configured one, and refuses to run while any finding is
    BLOCKED-INCOMPATIBLE (drift must be resolved by a person first)."""
    guard_site(site_url, allowed_url)
    findings = reconcile(target, actual)
    blocked = [f for f in findings if f.status == BLOCKED]
    if blocked:
        raise SiteGuardError("incompatible drift, nothing executed: " + "; ".join(f.list + "." + f.field for f in blocked))
    steps = plan(findings)
    if dry_run:
        return ApplyResult([], steps, True)
    done = []
    for lst, fld, (op, val) in steps:
        if op == "create_list":
            client.create_list(val)
        elif op == "create_field":
            client.create_field(lst, val)
        else:
            client.update_field(lst, fld, op, val)
        done.append((lst, fld, op))
    return ApplyResult(done, [], False)


# ---- SharePoint REST implementation (transport injected; no URLs or IDs embedded) ----

_XML_TYPES = {"Text": "Text", "Note": "Note", "Number": "Number", "Boolean": "Boolean", "DateTime": "DateTime",
              "Choice": "Choice", "Lookup": "Lookup", "User": "User"}


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"))


def field_schema_xml(spec: dict, lookup_list_id: Optional[str] = None) -> str:
    """CAML for createfieldasxml. Created with DisplayName = internal name (fixes the internal name);
    the display name is set afterwards."""
    t = spec["type"]
    if t not in _XML_TYPES:
        raise ValueError("unsupported field type %s" % t)
    n = spec["internalName"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", n):
        raise ValueError("internal name must be ASCII PascalCase: %r" % n)
    attrs = {"Type": t, "Name": n, "StaticName": n, "DisplayName": n,
             "Required": "TRUE" if spec.get("required") else "FALSE"}
    if spec.get("indexed"):
        attrs["Indexed"] = "TRUE"
    if spec.get("unique"):
        attrs["EnforceUniqueValues"] = "TRUE"
        attrs["Indexed"] = "TRUE"
    if t == "DateTime":
        attrs["Format"] = "DateOnly" if spec.get("dateOnly") else "DateTime"
    if t == "Number" and spec.get("decimals") is not None:
        attrs["Decimals"] = str(spec["decimals"])
    if t == "Note":
        attrs["RichText"] = "FALSE"
    if t == "Lookup":
        if not lookup_list_id:
            raise ValueError("lookup list id must be resolved at run time")
        attrs["List"] = "{%s}" % lookup_list_id
        attrs["ShowField"] = spec.get("lookupField", "Title")
        if spec.get("indexed"):
            attrs["RelationshipDeleteBehavior"] = "Restrict"
    inner = ""
    if t == "Choice":
        inner = "<CHOICES>%s</CHOICES>" % "".join("<CHOICE>%s</CHOICE>" % _esc(c) for c in spec.get("choices", []))
    if spec.get("validationFormula"):
        inner += "<Validation>%s</Validation>" % _esc(spec["validationFormula"])
    return "<Field %s>%s</Field>" % (" ".join('%s="%s"' % (k, _esc(v)) for k, v in attrs.items()), inner)


class RestSchemaClient(SchemaClient):
    """Uses transport(method, path, body, headers) -> (status, json). Paths are site-relative."""
    VERBOSE = {"Accept": "application/json;odata=verbose", "Content-Type": "application/json;odata=verbose"}

    def __init__(self, transport: Callable):
        self.t = transport

    def _call(self, method, path, body=None, extra=None):
        h = dict(self.VERBOSE, **(extra or {}))
        status, data = self.t(method, path, body, h)
        if status >= 300:
            raise RuntimeError("%s %s -> %s %s" % (method, path, status, json.dumps(data)[:300]))
        return data

    @staticmethod
    def _q(s):
        return s.replace("'", "''")

    def _list_id(self, title):
        d = self._call("GET", "/_api/web/lists/getbytitle('%s')?$select=Id" % self._q(title))
        return d["d"]["Id"]

    def create_list(self, spec):
        self._call("POST", "/_api/web/lists", {"__metadata": {"type": "SP.List"}, "Title": spec["title"],
                                               "BaseTemplate": spec.get("template", 100)})
        title = next((f for f in spec["fields"] if f["internalName"] == "Title"), None)
        if title is not None:
            self.update_field(spec["title"], "Title", "set_required", bool(title.get("required")))

    def create_field(self, list_title, spec):
        lid = self._list_id(spec["lookupList"]) if spec["type"] == "Lookup" else None
        xml = field_schema_xml(spec, lid)
        self._call("POST", "/_api/web/lists/getbytitle('%s')/fields/createfieldasxml" % self._q(list_title),
                   {"parameters": {"__metadata": {"type": "SP.XmlSchemaFieldCreationInformation"},
                                   "SchemaXml": xml, "Options": 8 | 4 | 16}})
        if spec.get("displayName"):
            self.update_field(list_title, spec["internalName"], "set_display_name", spec["displayName"])

    def update_field(self, list_title, internal_name, op, value):
        path = "/_api/web/lists/getbytitle('%s')/fields/getbyinternalnameortitle('%s')" % (self._q(list_title), self._q(internal_name))
        body = {"__metadata": {"type": "SP.Field"}}
        if op == "set_indexed":
            body["Indexed"] = bool(value)
        elif op == "set_unique":
            body["Indexed"] = True
            body["EnforceUniqueValues"] = bool(value)
        elif op == "set_required":
            body["Required"] = bool(value)
        elif op == "set_display_name":
            body["Title"] = value
        elif op == "add_choices":
            cur = self._call("GET", path + "?$select=Choices")["d"]["Choices"]["results"]
            body = {"__metadata": {"type": "SP.FieldChoice"},
                    "Choices": {"__metadata": {"type": "Collection(Edm.String)"}, "results": cur + [c for c in value if c not in cur]}}
        else:
            raise ValueError("unsupported update %s" % op)
        self._call("POST", path, body, {"X-HTTP-Method": "MERGE", "IF-MATCH": "*"})


def inventory(get_json: Callable[[str], dict], site_url: str) -> dict:
    """Read-only inventory in the format reconcile() expects. get_json(site-relative path) -> parsed nometadata JSON."""
    web = get_json("/_api/web?$select=Url")
    lists = [l for l in get_json("/_api/web/lists?$select=Id,Title,Hidden,BaseTemplate,ItemCount,HasUniqueRoleAssignments")["value"]
             if not l["Hidden"]]
    by_id = {l["Id"].lower(): l["Title"] for l in lists}
    out = {"site": web["Url"], "lists": []}
    for l in lists:
        fs = get_json("/_api/web/lists(guid'%s')/fields?$select=InternalName,Title,TypeAsString,Required,Indexed,"
                      "EnforceUniqueValues,Hidden,CanBeDeleted,LookupList,DisplayFormat,Choices" % l["Id"])["value"]
        fields = []
        for x in fs:
            if x["Hidden"] or not (x["CanBeDeleted"] or x["InternalName"] in SYSTEM_FIELDS):
                continue
            fields.append({"internalName": x["InternalName"], "displayName": x["Title"], "type": x["TypeAsString"],
                           "required": x["Required"], "indexed": x["Indexed"], "unique": x["EnforceUniqueValues"],
                           "lookupList": by_id.get((x.get("LookupList") or "").strip("{}").lower()) if x.get("LookupList") else None,
                           "dateOnly": (x.get("DisplayFormat") == 0) if x["TypeAsString"] == "DateTime" else None,
                           "choices": x.get("Choices"), "builtIn": not x["CanBeDeleted"]})
        out["lists"].append({"title": l["Title"], "itemCount": l["ItemCount"], "uniquePerms": l["HasUniqueRoleAssignments"],
                             "system": l["BaseTemplate"] != 100, "fields": fields})
    return out


def business_date(utc_instant: str, utc_offset_minutes: int) -> str:
    """Business calendar date of a UTC instant in a fixed-offset (no-DST) business time zone.
    The UTC value is converted first; it is never truncated."""
    ts = _dt.datetime.strptime(utc_instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    return (ts + _dt.timedelta(minutes=utc_offset_minutes)).date().isoformat()
