"""AppStart / client-config reference (executable specification; no tenant data).

    trusted identity (invoker's own connection) -> identity_resolver.resolve (mapped, active, unique)
      -> required references: Department and Discipline resolvable (Position optional) else INVALID_EMPLOYEE_REFERENCE
      -> AppOpen audit event (audit_event.app_open: AppOpen/ALLOW/OK or IdentityRejected/DENY/<code>), MANDATORY:
         a failed audit write -> INTERNAL_ERROR (no employee code, no configuration)
      -> server-side AppSettings read (service connection) -> client_config subset
      -> response {ok, resultCode, messageCode, correlationId, employeeCode, configStatus, config, interim, missing}

AppOpen grants nothing: there is no role lookup (unchanged from the audit model). Denied callers receive no
configuration and no employee data. Request fields that claim identity, role or scope are ignored by name.
The response never contains SharePoint item IDs, list names, URLs or raw AppSettings rows, nor Department, Discipline
or Position values (they are validated internally only). Every path returns the same key set. A failed caller-profile
read (MyProfile_V2) -> DIRECTORY_ERROR.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Iterable, Mapping, Optional

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
                 G.ACCOUNT_NOT_ALLOWED: "MSG_ACCOUNT_NOT_ENABLED", G.DIRECTORY_ERROR: "MSG_TEMPORARY_PROBLEM",
                 G.INVALID_EMPLOYEE_REFERENCE: "MSG_TEMPORARY_PROBLEM", G.INTERNAL_ERROR: "MSG_TEMPORARY_PROBLEM"}


def _response(code: str, correlation_id: str) -> dict:
    return {"ok": code == "OK", "resultCode": code, "messageCode": MESSAGE_CODES.get(code, "MSG_TEMPORARY_PROBLEM"),
            "correlationId": correlation_id, "employeeCode": "", "configStatus": "", "config": {}, "interim": {}, "missing": []}


def app_start(identity: Optional[idr.TrustedIdentity], lookup, config: idr.Config, *, registry: dict, overlay,
              settings_rows: Optional[Iterable[Mapping]], correlation_id: str, environment: str, client_type: str = "",
              now: Optional[str] = None, profile_failed: bool = False,
              write_audit: Optional[Callable[[dict], None]] = None, **untrusted) -> tuple:
    """(response dict, audit event or None). settings_rows = AppSettings rows read by the service (Title, Value);
    None = the read failed. profile_failed = the platform caller-profile read failed (no identity, no audit).
    write_audit = the mandatory audit write (raises on failure); None = the caller writes the returned event."""
    if profile_failed:
        return _response(G.DIRECTORY_ERROR, correlation_id), None
    event = ae.app_open(identity, lookup, config, correlation_id=correlation_id, environment=environment,
                        client_type=client_type, now=now, require_references=True, **untrusted)
    if write_audit is not None:
        try:
            write_audit(event.to_row())
        except Exception:  # audit is mandatory: never continue, never return employee data or configuration
            return _response(G.INTERNAL_ERROR, correlation_id), event
    ok = event.ResultCode == "OK"
    resp = _response(event.ResultCode, correlation_id)
    if not ok:
        return resp, event
    res = idr.resolve(identity, lookup, config, require_references=True)
    if settings_rows is None:  # the service could not read AppSettings: live values unknown -> unresolved, nothing returned
        keys = [d["key"] for d in registry["settings"] if d.get("exposeToClient")]
        resp.update(employeeCode=res.employee.legacy_id, configStatus=cc.cfg.CONFIG_UNRESOLVED, missing=keys)
        return resp, event
    c = cc.client_config(registry, overlay, settings_rows, identity_ok=True)
    resp.update(employeeCode=res.employee.legacy_id, configStatus=c["status"], config=c["settings"], interim=c["interim"],
                missing=c["missing"])
    return resp, event
