"""List permission hardening: safety classification, idempotent plan and REST requests (generic; no tenant data).

    current state (unique flag + role assignments, read-only)  +  target (JSON, per list)
      -> unsafe()  -> principals that hold write-capable rights without being approved writers
      -> plan()    -> ordered operations: break inheritance (no copy) / add / remove; GATED grants listed, never executed
      -> requests()-> SharePoint REST calls for the plan

Rules:
- Phase 1 (no service identity needed): stop inheriting, keep only the approved administrative principals.
- A service grant is GATED until its decision is approved; it is refused for temporary/test principals and for any
  role that can delete or manage (only roles in SERVICE_ROLES may ever be granted to a service identity).
- "Limited Access" is a structural SharePoint entry (rights elsewhere in the site), not list access; it is ignored.
- A second run against the resulting state plans nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

WRITE_ROLES = {"Full Control", "Design", "Edit", "Contribute", "TS Contribute-NoDelete", "TS Service"}
STRUCTURAL = {"Limited Access"}
SERVICE_ROLES = {"Read", "TS Service"}  # TS Service = view/add/edit + override list behaviours; no delete/manage (D-7)
ROLE_IDS = {"Full Control": 1073741829, "Read": 1073741826, "Edit": 1073741830, "Contribute": 1073741827, "Design": 1073741828}


class PlanRefused(Exception):
    pass


@dataclass(frozen=True)
class Assignment:
    principal_id: int
    title: str
    roles: tuple

    @property
    def effective(self) -> set:
        return set(self.roles) - STRUCTURAL


@dataclass
class Target:
    """required: principal_id -> role. allowed_extra: principal ids that may keep what they have (e.g. the site
    collection administrator, who keeps Full Control on a list after breaking inheritance).
    gated: grants that need a decision, e.g. {"principal": "<service>", "role": "Read", "gate": "D-3"}."""
    required: dict
    allowed_extra: tuple = ()
    gated: list = field(default_factory=list)
    temporary_principals: tuple = ()


def parse(ra: Iterable[str]) -> list:
    """'id:Title=Role1+Role2' strings (read-only inventory format) -> Assignments."""
    out = []
    for s in ra:
        pid, rest = s.split(":", 1)
        title, roles = rest.rsplit("=", 1)
        out.append(Assignment(int(pid), title, tuple(sorted(roles.split("+")))))
    return out


def unsafe(current: Iterable[Assignment], approved_writers: Iterable[int]) -> list:
    """Assignments that give write-capable rights to a principal that is not an approved writer.
    Empty groups count too: safety must not depend on today's membership."""
    ok = set(approved_writers)
    return [a for a in current if a.principal_id not in ok and a.effective & WRITE_ROLES]


def plan(unique: bool, current: Iterable[Assignment], target: Target, *, approved_grants: Iterable[dict] = ()) -> dict:
    """{'ops': [...], 'gated': [...]} for one list. approved_grants: gated grants whose decision is approved and that
    name a concrete, non-temporary principal id ({'principal_id', 'role', 'gate', 'approval'})."""
    current = list(current)
    ops, gated = [], []
    have = {a.principal_id: a for a in current}
    if not unique:
        ops.append(("break", {"copyRoleAssignments": False, "clearSubscopes": True}))
        # after a break without copy only the caller (site administrator) remains; inherited entries are gone
        have = {pid: a for pid, a in have.items() if pid in target.allowed_extra}
    else:
        for pid, a in have.items():
            if pid in target.required or pid in target.allowed_extra or not a.effective:
                continue
            for role in sorted(a.effective):
                ops.append(("remove", {"principal_id": pid, "title": a.title, "role": role}))
    for pid, role in target.required.items():
        if role in (have.get(pid).effective if pid in have else set()):
            continue
        ops.append(("add", {"principal_id": pid, "role": role}))
    for g in target.gated:
        appr = next((x for x in approved_grants if x.get("gate") == g["gate"] and x.get("role") == g["role"]), None)
        if appr is None:
            gated.append(dict(g, status="GATED"))
            continue
        if appr["role"] not in SERVICE_ROLES:
            raise PlanRefused("role %r may not be granted to a service identity (delete/manage rights)" % appr["role"])
        if not appr.get("principal_id") or str(appr.get("principal_title", "")).lower() in {str(t).lower() for t in target.temporary_principals} \
                or appr["principal_id"] in target.temporary_principals:
            raise PlanRefused("a temporary/test principal is never the approved service identity")
        if not appr.get("approval"):
            raise PlanRefused("service grant without an approval record")
        if appr["role"] not in (have.get(appr["principal_id"]).effective if appr["principal_id"] in have else set()):
            ops.append(("add", {"principal_id": appr["principal_id"], "role": appr["role"], "gate": g["gate"]}))
    return {"ops": ops, "gated": gated}


def simulate(unique: bool, current: Iterable[Assignment], ops: list, admin_id: Optional[int] = None) -> tuple:
    """State after applying ops (used for the idempotency check). Breaking inheritance keeps only the caller."""
    cur = {a.principal_id: a for a in current}
    for op, arg in ops:
        if op == "break":
            unique = True
            # observed: a break without copy leaves only the calling site administrator, with Full Control
            title = cur[admin_id].title if admin_id in cur else "site administrator"
            cur = {admin_id: Assignment(admin_id, title, ("Full Control",))} if admin_id is not None else {}
        elif op == "add":
            a = cur.get(arg["principal_id"], Assignment(arg["principal_id"], str(arg["principal_id"]), ()))
            cur[arg["principal_id"]] = Assignment(a.principal_id, a.title, tuple(sorted(set(a.roles) | {arg["role"]})))
        elif op == "remove":
            a = cur[arg["principal_id"]]
            left = tuple(sorted(set(a.roles) - {arg["role"]}))
            if left:
                cur[arg["principal_id"]] = Assignment(a.principal_id, a.title, left)
            else:
                cur.pop(arg["principal_id"])
    return unique, list(cur.values())


PHASE2_ROLES = {"Read"}


def service_read_plan(site_url: str, allowed_url: str, lists: dict, *, owners_id: int, admin_id: int,
                      service: Optional[dict], temporary_principals: Iterable = (), allowed_readers: dict = None) -> dict:
    """Phase 2: grant the APPROVED operational service identity Read on already-hardened lists, nothing else.

    lists: {title: (unique, [Assignment])} from a read-only snapshot. service: {"principal_id", "title", "approval"} from
    environment configuration (None while D-3 is open -> GATED). allowed_readers: {title: {principal_id: role}} that may
    legitimately exist (e.g. staff Read on master lists). Findings are reported, never auto-fixed:
    NOT_HARDENED, OWNERS_MISSING, SECURITY_DRIFT (service holds more than Read), UNEXPECTED_PRINCIPAL.
    Never removes anything, never touches Owners, never grants anything but Read."""
    import schema_reconcile as sr  # site guard: exact allowed site, never a root site
    sr.guard_site(site_url, allowed_url)
    temp = {str(t).lower() for t in temporary_principals}
    if service is not None:
        if not service.get("principal_id") or not service.get("approval"):
            raise PlanRefused("service grant without a resolved principal and an approval record")
        if str(service["principal_id"]).lower() in temp or str(service.get("title", "")).lower() in temp:
            raise PlanRefused("a temporary/test principal is never the approved service identity")
    out = {"gated": service is None, "lists": {}}
    for title, (unique, current) in lists.items():
        ops, findings = [], []
        have = {a.principal_id: a for a in current}
        readers = (allowed_readers or {}).get(title, {})
        if not unique:
            findings.append(("NOT_HARDENED", "list still inherits site permissions"))
        if "Full Control" not in (have.get(owners_id).effective if owners_id in have else set()):
            findings.append(("OWNERS_MISSING", "Owners do not hold Full Control"))
        known = {owners_id, admin_id} | set(readers) | ({service["principal_id"]} if service else set())
        for pid, a in have.items():
            if pid not in known and a.effective:
                findings.append(("UNEXPECTED_PRINCIPAL", "%s holds %s" % (a.title, "+".join(sorted(a.effective)))))
            elif pid in readers and a.effective - {readers[pid]}:
                findings.append(("SECURITY_DRIFT", "%s holds %s (expected %s)" % (a.title, "+".join(sorted(a.effective)), readers[pid])))
        if service is not None and unique:
            cur = have.get(service["principal_id"])
            eff = cur.effective if cur else set()
            if eff - PHASE2_ROLES:
                findings.append(("SECURITY_DRIFT", "service holds %s (expected Read only)" % "+".join(sorted(eff))))
            elif "Read" not in eff:
                ops.append(("add", {"principal_id": service["principal_id"], "role": "Read", "gate": "D-3"}))
        out["lists"][title] = {"ops": ops, "findings": findings}
    return out


def requests(list_title: str, ops: list, role_ids: Optional[dict] = None) -> list:
    """SharePoint REST calls (site-relative) for the plan. Role definition ids are resolved at run time for custom levels."""
    ids = dict(ROLE_IDS, **(role_ids or {}))
    q = list_title.replace("'", "''")
    base = "/_api/web/lists/getbytitle('%s')" % q
    out = []
    for op, arg in ops:
        if op == "break":
            out.append(("POST", base + "/breakroleinheritance(copyRoleAssignments=false,clearSubscopes=true)"))
        elif op == "add":
            out.append(("POST", base + "/roleassignments/addroleassignment(principalid=%d,roledefid=%d)" % (arg["principal_id"], ids[arg["role"]])))
        elif op == "remove":
            out.append(("POST", base + "/roleassignments/removeroleassignment(principalid=%d,roledefid=%d)" % (arg["principal_id"], ids[arg["role"]])))
    return out
