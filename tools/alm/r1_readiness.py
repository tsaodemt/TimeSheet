"""R1 flow-set deployment readiness (generic; no tenant data, no hard-coded account).

readiness(purpose, flows=..., *, manifest, overlay, registry, list_state, ...) -> Result(ready, blockers, notices)
for ENGINEERING | UAT | PRODUCTION. Dependencies come from the manifest "flows" section (generated from the
templates by r1_flows.py), so a flow is only blocked by what it actually uses. Every blocker has a category:

  PUBLISHER_PREFIX_UNRESOLVED           <PFX> still in a schema name / publisher prefix not decided (ENV-D3)
  ENVIRONMENT_UNRESOLVED                an ENV-D3 environment decision or a used environment variable has no value
  D3_SERVICE_IDENTITY_MISSING           no approved operational service identity configured (or a temporary one)
  CONNECTION_REFERENCE_UNBOUND          a used SERVICE-owned reference is gated, unowned or owned by another account;
                                        or a used reference is undeclared / its ownership unknown
  PERMISSION_NOT_VERIFIED               service identity set, but no permission snapshot for a used list
  READ_PERMISSION_MISSING / WRITE_PERMISSION_MISSING / SECURITY_DRIFT   exact service rights per used list
  TARGET_LIST_MISSING                   an operational list a flow uses does not exist
  REFERENCE_DATA_MISSING                a reference list a flow uses has no canonical business rows (existing is not enough)
  AUDIT_DEPENDENCY_UNAVAILABLE          the audit list a flow writes is not live
  INTERIM_CONFIG_NOT_UAT_READY / INTERIM_CONFIG_NOT_PRODUCTION_READY   an interim (engineering-only) value is in use
  CONFIG_NOT_READY                      any other AppSettings readiness failure

INVOKER-owned references (the run-only user's own connection) are never reported as missing service ownership.
Notices do not block: first-live runtime checks still to run, interim create idempotency (R1-Q3).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "config"))
sys.path.insert(0, HERE)
import app_settings as cfg  # noqa: E402
import manifest_check as mc  # noqa: E402

R1_FLOWS = ("TS-AppOpen", "TS-ReadOwn", "TS-SaveEntry")
WRITE_LEVEL = "TS Service"   # view/add/edit, no delete/manage (D-7)
STRUCTURAL = {"Limited Access"}
ENV_DECISIONS = ("environmentType", "region", "adminsMakers", "dlp", "publisher", "prefix", "hosting")


@dataclass
class Result:
    ready: bool
    blockers: list = field(default_factory=list)   # (category, flow or "*", detail)
    notices: list = field(default_factory=list)

    def categories(self) -> list:
        return sorted({c for c, _, _ in self.blockers})


def classify(ref: Optional[Mapping]) -> str:
    """INVOKER | SERVICE | APP_USER | UNKNOWN (explicit `ownership`, else the legacy invokerOwned flag)."""
    if not ref:
        return "UNKNOWN"
    own = str(ref.get("ownership") or "").upper()
    if own in ("INVOKER", "SERVICE", "APP_USER"):
        return own
    return "INVOKER" if ref.get("invokerOwned") else "UNKNOWN"


def _login_matches(a: Mapping, upn: str) -> bool:
    login = str(a.get("login") or "").lower()
    return bool(upn) and (login == upn or login.endswith("|" + upn))


def readiness(purpose: str, flows: Iterable[str] = R1_FLOWS, *, manifest: dict, overlay: Mapping, registry: dict,
              list_state: Mapping, environment: str = "staging", permissions: Optional[Mapping] = None,
              settings_rows: Optional[Iterable[Mapping]] = None, temporary_accounts: Iterable[str] = (),
              service_key: str = "ServiceAccountUpn") -> Result:
    if purpose not in cfg.PURPOSES:
        raise ValueError("purpose must be one of %s" % (cfg.PURPOSES,))
    defs = {f["name"]: f for f in manifest.get("flows", [])}
    r = Result(False)
    b = r.blockers.append
    for name in flows:
        if name not in defs:
            b(("CONNECTION_REFERENCE_UNBOUND", name, "flow not declared in the manifest flows section"))
    fl = [defs[n] for n in flows if n in defs]

    # ENV-D3: publisher prefix and environment decisions
    names = [x.get("schemaName", "") for k in ("environmentVariables", "connectionReferences") for x in manifest.get(k, [])]
    names += [x["schemaName"] for f in fl for x in f["connectionReferences"]] + [v for f in fl for v in f["environmentVariables"]]
    prefix = str(((manifest.get("solution") or {}).get("publisher") or {}).get("customizationPrefix") or "")
    if any("<PFX>" in n for n in names) or not prefix or "<" in prefix:
        b(("PUBLISHER_PREFIX_UNRESOLVED", "*", "publisher customization prefix not decided (ENV-D3)"))
    decisions = manifest.get("environmentDecisions") or {}
    for k in ENV_DECISIONS:
        v = decisions.get(k)
        if v in (None, "") or mc.is_placeholder(str(v)):
            b(("ENVIRONMENT_UNRESOLVED", "*", "ENV-D3 %s not decided" % k))
    variables = {x["schemaName"]: x for x in manifest.get("environmentVariables", [])}
    for v in sorted({v for f in fl for v in f["environmentVariables"]}):
        x = variables.get(v)
        val = ((x or {}).get("values") or {}).get(environment)
        if x is None:
            b(("ENVIRONMENT_UNRESOLVED", "*", "%s not declared" % v))
        elif x.get("gated") or val in (None, "") or mc.is_placeholder(str(val)):
            b(("ENVIRONMENT_UNRESOLVED", "*", "%s has no %s value%s" % (v, environment, " (gated: %s)" % x.get("gatedBy") if x.get("gated") else "")))

    # D-3: service identity and the references it must own
    upn = str(((overlay or {}).get("external") or {}).get(service_key) or "").strip().lower()
    temp = {t.lower() for t in temporary_accounts}
    if not upn:
        b(("D3_SERVICE_IDENTITY_MISSING", "*", "%s is not configured (D-3)" % service_key))
    elif upn in temp or upn.split("@")[0] in temp:
        b(("D3_SERVICE_IDENTITY_MISSING", "*", "the configured identity is a temporary/test account; it is never a substitute"))
        upn = ""
    refs = {x["schemaName"]: x for x in manifest.get("connectionReferences", [])}
    for f in fl:
        for used in f["connectionReferences"]:
            n, decl = used["schemaName"], refs.get(used["schemaName"])
            kind = classify(decl)
            if decl is None:
                b(("CONNECTION_REFERENCE_UNBOUND", f["name"], "%s not declared" % n))
            elif kind != used.get("ownership", kind):
                b(("CONNECTION_REFERENCE_UNBOUND", f["name"], "%s ownership %s does not match the flow's %s" % (n, kind, used.get("ownership"))))
            elif kind == "INVOKER":
                continue  # the caller's own connection: never a service-ownership blocker
            elif kind != "SERVICE":
                b(("CONNECTION_REFERENCE_UNBOUND", f["name"], "%s ownership not declared" % n))
            elif decl.get("gated"):
                b(("CONNECTION_REFERENCE_UNBOUND", f["name"], "%s gated: %s" % (n, decl.get("gatedBy"))))
            elif not upn or str(decl.get("connectionOwner") or "").strip().lower() != upn:
                b(("CONNECTION_REFERENCE_UNBOUND", f["name"], "%s is not owned by the approved service identity" % n))

    # lists: existence, reference data, audit, exact service rights
    # one service identity serves every flow in the manifest: its required level per list comes from the whole set,
    # and the lists checked are those the requested flows use
    needs = {}
    for f in defs.values():
        for lst, modes in f["lists"].items():
            needs.setdefault(lst, set()).update(modes)
    used = {lst for f in fl for lst in f["lists"]}
    eff = cfg.plain(cfg.resolve(registry, overlay, settings_rows))
    for f in fl:
        ref = {x["list"]: x for x in f.get("referenceData", [])}
        audit = set((f.get("audit") or {}).get("lists", []))
        for lst in f["lists"]:
            st = list_state.get(lst) or {}
            if lst in ref:
                cond = ref[lst]["required"]
                if cond != "always" and eff.get("ProjectAssignmentScoping") != "On":
                    continue
                if not st.get("exists"):
                    b(("REFERENCE_DATA_MISSING", f["name"], "%s: list does not exist" % lst))
                elif not st.get("canonicalRows"):
                    b(("REFERENCE_DATA_MISSING", f["name"], "%s: no canonical business rows (schema only)" % lst))
            elif lst in audit:
                if not st.get("exists") or not st.get("live", st.get("exists")):
                    b(("AUDIT_DEPENDENCY_UNAVAILABLE", f["name"], "%s not live (S05.5)" % lst))
            elif not st.get("exists"):
                b(("TARGET_LIST_MISSING", f["name"], lst))
    if upn:
        for lst in sorted(used):
            snap = (permissions or {}).get(lst)
            if snap is None:
                b(("PERMISSION_NOT_VERIFIED", "*", "%s: no permission snapshot" % lst))
                continue
            roles = {x for a in snap.get("assignments", []) if _login_matches(a, upn) for x in a.get("roles", [])} - STRUCTURAL
            want = WRITE_LEVEL if "write" in needs[lst] else "Read"
            if want not in roles:
                b(("WRITE_PERMISSION_MISSING" if want == WRITE_LEVEL else "READ_PERMISSION_MISSING", "*", lst))
            if roles - {want, "Read"}:  # Read beside the write level adds nothing; anything else is broader than needed
                b(("SECURITY_DRIFT", "*", "%s: service holds %s" % (lst, "+".join(sorted(roles)))))
            if not snap.get("unique"):
                b(("SECURITY_DRIFT", "*", "%s: list inherits site permissions" % lst))

    # configuration (interim values: engineering only)
    keys = sorted({k for f in fl for k in f["settings"]["keys"]})
    _, cb = cfg.readiness(registry, overlay, purpose, keys, settings_rows)
    for k, why in cb:
        if k in (service_key,) or k == "overlay" and service_key in why:
            continue  # reported once as D3_SERVICE_IDENTITY_MISSING
        if "interim" in why and purpose in ("UAT", "PRODUCTION"):
            b(("INTERIM_CONFIG_NOT_%s_READY" % purpose, "*", "%s: %s" % (k, why)))
        else:
            b(("CONFIG_NOT_READY", "*", "%s: %s" % (k, why)))

    for f in fl:
        for c in f.get("firstLiveChecks", []):
            r.notices.append(("FIRST_LIVE_CHECK_PENDING", f["name"], c))
        idem = f.get("createIdempotency")
        if idem:
            r.notices.append(("CREATE_IDEMPOTENCY_INTERIM", f["name"], "%s; exactly-once not guaranteed" % idem["decision"]))
    seen, out = set(), []
    for x in r.blockers:
        if x not in seen:
            seen.add(x)
            out.append(x)
    r.blockers = out
    r.ready = not out
    return r
