"""DEMO readiness (R1 engineering / customer demo on STAGING) — separate from UAT / PRODUCTION readiness (generic).

demo_readiness(result, facts) takes the ENGINEERING r1_readiness Result and demo facts, and splits blockers into
  demo      : things that stop the defined demo path (app opens -> identity -> own list -> create / edit Draft)
  postDemo  : production / UAT governance that never blocks the demo (they stay open; nothing is marked DONE)
The demo is READY only when there is no demo blocker. UAT / PRODUCTION readiness is unchanged and may stay NOT READY.

facts (all booleans unless noted): environmentSelected, demoPrefix (str), flowsDeployed, appDeployed, identityMapped,
identityInRoleGroup.
"""
from __future__ import annotations

from typing import Mapping

DEMO_CATEGORIES = {"CONNECTION_REFERENCE_UNBOUND", "TARGET_LIST_MISSING", "REFERENCE_DATA_MISSING", "AUDIT_DEPENDENCY_UNAVAILABLE",
                   "READ_PERMISSION_MISSING", "WRITE_PERMISSION_MISSING", "PERMISSION_NOT_VERIFIED", "SECURITY_DRIFT", "CONFIG_NOT_READY"}
POST_DEMO_CATEGORIES = {"D3_OPERATIONAL_READINESS_INCOMPLETE", "INTERIM_CONFIG_NOT_UAT_READY", "INTERIM_CONFIG_NOT_PRODUCTION_READY"}
# ENV-D3 production decisions (environment type, region, makers, DLP, publisher, prefix, hosting) do not block a demo
# in an existing usable environment; an unset list / site variable does (the flows cannot bind).
ENV_DECISION_MARK = "ENV-D3 "
DEMO_CHECKS = (("environmentSelected", "DEMO_ENVIRONMENT_NOT_SELECTED", "a usable existing Power Platform environment is selected for the demo"),
               ("identityMapped", "DEMO_IDENTITY_NOT_MAPPED", "the demo user resolves to one active Employees row with a discipline"),
               ("identityInRoleGroup", "DEMO_IDENTITY_NO_ROLE", "the demo user is in the employee role group"),
               ("flowsDeployed", "FLOWS_NOT_DEPLOYED", "TS-AppOpen, TS-ReadOwn, TS-SaveEntry deployed and bound"),
               ("appDeployed", "APP_NOT_DEPLOYED", "the demo Canvas app is published and shared"))


def demo_readiness(result, facts: Mapping) -> dict:
    demo, post = [], []
    for cat, flow, detail in result.blockers:
        if cat in POST_DEMO_CATEGORIES:
            post.append((cat, flow, detail))
        elif cat == "PUBLISHER_PREFIX_UNRESOLVED":
            (post if facts.get("demoPrefix") else demo).append((cat, flow, detail + ("" if facts.get("demoPrefix") else " (no DEMO INTERIM prefix either)")))
        elif cat == "ENVIRONMENT_UNRESOLVED":
            (post if detail.startswith(ENV_DECISION_MARK) and facts.get("environmentSelected") else demo).append((cat, flow, detail))
        elif cat in DEMO_CATEGORIES:
            demo.append((cat, flow, detail))
        else:
            demo.append((cat, flow, detail))  # unknown category: fail closed for the demo
    for key, code, text in DEMO_CHECKS:
        if not facts.get(key):
            demo.append((code, "*", text))
    return {"ready": not demo, "demo": demo, "postDemo": post}
