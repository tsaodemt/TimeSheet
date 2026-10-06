"""Live test harness for the reusable guard: definition of SPIKE-TS-GuardTemplate.

The flow consists only of the `Guard` scope from guard_template.guard_actions() (incl. its audit row);
it is the first consumer of the template and the pattern later guarded flows follow.
Build with make_read_designer_build.py and TS_FLOW_MODULE=build_guard_template_flow.

Configuration (environment variables): TS_SITE_URL, TS_ALLOWED_DOMAIN, TS_EMP_LIST (default _TS_IdentityTest),
TS_AUDIT_LIST (default _TS_SecuritySpikeAudit), TS_ROLE_GROUPS (JSON [[roleKey, groupObjectId], ...]),
TS_SCOPE_CONFIG (path to ScopeConfig.json).
"""
import json
import os

import guard_template

SITE = os.environ.get("TS_SITE_URL", "https://<tenant>.sharepoint.com/sites/<staging-site>")
DOMAIN = os.environ.get("TS_ALLOWED_DOMAIN", "<tenant-domain>")
EMP = os.environ.get("TS_EMP_LIST", "_TS_IdentityTest")
AUDIT = os.environ.get("TS_AUDIT_LIST", "_TS_SecuritySpikeAudit")
ROLE_GROUPS = json.loads(os.environ.get("TS_ROLE_GROUPS", '[["EMP", "<group-id>"]]'))
SCOPE_PATH = os.environ.get("TS_SCOPE_CONFIG")
SCOPE_CONFIG = {"scopes": {}, "pending": []}
if SCOPE_PATH:
    with open(SCOPE_PATH, encoding="utf-8") as fh:
        SCOPE_CONFIG = json.load(fh)

INPUTS = [("Text", "Action", "capability, e.g. TS.Approve"),
          ("Text", "ScopeKind", "self | employee | discipline | company"),
          ("Text", "ScopeRef", "employee code or discipline code"),
          ("Text", "CallerUpn", "DECOY - never trusted"),
          ("Text", "ClaimRole", "DECOY - never trusted"),
          ("Text", "ClaimScope", "DECOY - never trusted"),
          ("Text", "ClientRequestId", "caller correlation token")]
guard = guard_template.guard_actions(
    SCOPE_CONFIG, ROLE_GROUPS, site=SITE, domain=DOMAIN, emp_list=EMP, audit_list=AUDIT,
    action_expr="triggerBody()?['text']", kind_expr="triggerBody()?['text_1']", ref_expr="triggerBody()?['text_2']",
    untrusted_inputs=[n for _, n, _ in INPUTS[3:]])
inits = {}
