"""Reference implementation of the application identity-resolution contract.

The same rules are implemented in Power Apps (app start, UI only) and in every guard flow
(authoritative). This module is the executable specification: the tests in
test_identity_resolver.py define the expected behaviour (cases I1-I10).

Chain:
    trusted authenticated identity  (platform-supplied; never a request field)
      -> normalised UPN
      -> exactly one active Employees row (Employees.AccountUpn, indexed, stored normalised)
      -> application identity (EmployeeItemId / LegacyId, discipline)
      -> role / capability context (live Entra group membership -> AppRoles -> capabilities)

Every failure is fail-closed: no employee context, no roles, no capabilities.
Nothing tenant-specific is hard-coded; domains, group IDs and role catalogue come from configuration.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Sequence

# Result codes (also used by guard flows and the "not registered" screen).
OK = "OK"
INVALID_IDENTITY = "INVALID_IDENTITY"      # missing / malformed / foreign-domain identity
ACCOUNT_NOT_ALLOWED = "ACCOUNT_NOT_ALLOWED"  # disabled account or guest
NOT_REGISTERED = "NOT_REGISTERED"          # tenant user without an Employees row
INACTIVE = "INACTIVE"                      # mapped employee is not active
DUPLICATE_MAPPING = "DUPLICATE_MAPPING"    # more than one Employees row claims the UPN (data error)
DIRECTORY_ERROR = "DIRECTORY_ERROR"        # lookup failed; never treated as "not found"

_UPN_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}$")


@dataclass(frozen=True)
class TrustedIdentity:
    """Identity as supplied by the platform, e.g. Office 365 Users MyProfile_V2 on the caller's own
    connection (flows) or the signed-in user (Power Apps). Never built from request parameters."""
    upn: str
    account_enabled: bool = True
    user_type: str = "Member"           # Member | Guest
    group_ids: Sequence[str] = ()        # live transitive membership of SG-TS-* groups (flows: re-read each run)


@dataclass(frozen=True)
class Employee:
    item_id: int                         # SharePoint item ID in this environment (not portable)
    legacy_id: str                       # stable business key (portable)
    account_upn: str                     # Employees.AccountUpn (stored normalised)
    is_active: bool
    discipline_id: Optional[int] = None


@dataclass(frozen=True)
class Role:
    key: str                             # e.g. EMP, TL, APR
    group_id: str                        # environment-specific Entra group object ID (configuration)
    capabilities: Sequence[str] = ()


@dataclass(frozen=True)
class Config:
    allowed_domains: Sequence[str]       # tenant domains accepted for sign-in (configuration, not code)
    roles: Sequence[Role] = ()
    # Roles come only from Entra groups (SPEC). A baseline role granted without group membership is
    # possible but is a customer decision; default None = strictly group-based.
    baseline_role_key: Optional[str] = None


@dataclass
class Resolution:
    code: str
    upn: Optional[str] = None
    employee: Optional[Employee] = None
    roles: list = field(default_factory=list)
    capabilities: list = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.code == OK


def normalise_upn(raw: Optional[str]) -> Optional[str]:
    """Trim, Unicode NFC, lower-case. Returns None when the value is not a plausible UPN."""
    if raw is None:
        return None
    s = unicodedata.normalize("NFC", str(raw)).strip().lower()
    return s if _UPN_RE.match(s) else None


def resolve(identity: Optional[TrustedIdentity],
            lookup: Callable[[str], Iterable[Employee]],
            config: Config,
            **untrusted: object) -> Resolution:
    """Resolve the caller. `untrusted` swallows request-supplied fields (CallerUpn, OwnerUpn,
    ActorUpn, display name, Author, headers ...) so that callers can pass them for logging;
    they are deliberately never read."""
    del untrusted  # never trusted, never used
    if identity is None:
        return Resolution(INVALID_IDENTITY, detail="no platform identity")
    upn = normalise_upn(identity.upn)
    if upn is None:
        return Resolution(INVALID_IDENTITY, detail="malformed identity")
    domains = {d.strip().lower() for d in config.allowed_domains}
    if not domains or upn.rsplit("@", 1)[1] not in domains:
        return Resolution(INVALID_IDENTITY, upn=upn, detail="domain not allowed")
    if not identity.account_enabled or identity.user_type.lower() != "member":
        return Resolution(ACCOUNT_NOT_ALLOWED, upn=upn)
    try:
        matches = [e for e in lookup(upn) if normalise_upn(e.account_upn) == upn]
    except Exception as exc:  # fail closed, never "not found"
        return Resolution(DIRECTORY_ERROR, upn=upn, detail=type(exc).__name__)
    if not matches:
        return Resolution(NOT_REGISTERED, upn=upn)
    if len(matches) > 1:
        return Resolution(DUPLICATE_MAPPING, upn=upn, detail="%d rows" % len(matches))
    emp = matches[0]
    if not emp.is_active:
        return Resolution(INACTIVE, upn=upn)
    member_of = {g.lower() for g in identity.group_ids}
    roles = [r for r in config.roles
             if (config.baseline_role_key and r.key == config.baseline_role_key)
             or (r.group_id and r.group_id.lower() in member_of)]
    caps = sorted({c for r in roles for c in r.capabilities})
    return Resolution(OK, upn=upn, employee=emp, roles=[r.key for r in roles], capabilities=caps)


def migrate_upn(upn: str, upn_map: Mapping[str, str]) -> Optional[str]:
    """Tenant move: OldUpn -> NewUpn. Unknown UPNs are not guessed (returns None)."""
    n = normalise_upn(upn)
    if n is None:
        return None
    m = {normalise_upn(k): normalise_upn(v) for k, v in upn_map.items()}
    return m.get(n)
