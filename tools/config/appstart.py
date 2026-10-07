"""AppStart / client-config reference (executable specification; no tenant data).

    trusted identity (invoker's own connection) -> identity_resolver.resolve (mapped, active, unique)
      -> AppOpen audit event (audit_event.app_open: AppOpen/ALLOW/OK or IdentityRejected/DENY/<code>)
      -> server-side AppSettings read (service connection) -> client_config subset
      -> response {ok, resultCode, messageCode, correlationId, employeeCode, configStatus, config, interim, missing}

AppOpen grants nothing: there is no role lookup (unchanged from the audit model). Denied callers receive no
configuration and no employee data. Request fields that claim identity, role or scope are ignored by name.
The response never contains SharePoint item IDs, list names, URLs or raw AppSettings rows.
"""
from __future__ import annotations

import os
import sys
from typing import Iterable, Mapping, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "audit"), os.path.join(HERE, "..", "identity")):
    sys.path.insert(0, p)
import audit_event as ae  # noqa: E402
import client_config as cc  # noqa: E402
import guard as G  # noqa: E402
import identity_resolver as idr  # noqa: E402

# Stable message codes for the client (customer wording is R1-Q4, not decided here).
MESSAGE_CODES = {"OK": "MSG_OK", G.UNMAPPED_IDENTITY: "MSG_ACCOUNT_NOT_ENABLED", G.INACTIVE_EMPLOYEE: "MSG_ACCOUNT_NOT_ENABLED",
                 G.DUPLICATE_IDENTITY: "MSG_ACCOUNT_NOT_ENABLED", G.INVALID_IDENTITY: "MSG_ACCOUNT_NOT_ENABLED",
                 G.ACCOUNT_NOT_ALLOWED: "MSG_ACCOUNT_NOT_ENABLED", G.DIRECTORY_ERROR: "MSG_TEMPORARY_PROBLEM"}


def app_start(identity: Optional[idr.TrustedIdentity], lookup, config: idr.Config, *, registry: dict, overlay,
              settings_rows: Optional[Iterable[Mapping]], correlation_id: str, environment: str, client_type: str = "",
              now: Optional[str] = None, **untrusted) -> tuple:
    """(response dict, audit event). settings_rows = AppSettings rows read by the service (Title, Value);
    None = the read failed."""
    event = ae.app_open(identity, lookup, config, correlation_id=correlation_id, environment=environment,
                        client_type=client_type, now=now, **untrusted)
    ok = event.ResultCode == "OK"
    code = event.ResultCode
    resp = {"ok": ok, "resultCode": code, "messageCode": MESSAGE_CODES.get(code, "MSG_TEMPORARY_PROBLEM"),
            "correlationId": correlation_id, "employeeCode": "", "configStatus": "", "config": {}, "interim": {}, "missing": []}
    if not ok:
        return resp, event
    res = idr.resolve(identity, lookup, config)
    if settings_rows is None:  # the service could not read AppSettings: live values unknown -> unresolved, nothing returned
        keys = [d["key"] for d in registry["settings"] if d.get("exposeToClient")]
        resp.update(employeeCode=res.employee.legacy_id, configStatus=cc.cfg.CONFIG_UNRESOLVED, missing=keys)
        return resp, event
    c = cc.client_config(registry, overlay, settings_rows, identity_ok=True)
    resp.update(employeeCode=res.employee.legacy_id, configStatus=c["status"], config=c["settings"], interim=c["interim"],
                missing=c["missing"])
    return resp, event
