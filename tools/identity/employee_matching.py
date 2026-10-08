"""EMPLOYEE-IDENTITY-MAPPING-01 — conservative Employees <-> directory account matching (generic; no tenant data).

Produces PROPOSALS only. Nothing here writes to SharePoint or the directory; applying a mapping needs a separate,
owner-approved task (migration-mapping §4: HR-confirmed mapping file, tenant check at load).

    normalize(s) / fold(s)                  -> comparison forms (originals are never changed)
    classify_account(acct, cfg)             -> MEMBER_ENABLED | MEMBER_DISABLED | MEMBER_STATUS_UNKNOWN | GUEST | SERVICE_TEST
    match(employees, directory, cfg)        -> {"rows": [...], "conflicts": {...}, "summary": {...}}
    safe_violations(row)                    -> list of unmet AUTO_MATCH_SAFE conditions ([] = eligible)

Evidence levels (strongest first)
  L1 EXACT_EMPLOYEE_ID      employee code == directory employeeId (exact, unique)
  L2 EXACT_WORK_EMAIL       trusted work e-mail on the employee == directory UPN / mail
  L3 EXACT_LEGACY_USERNAME  legacy user name == directory UPN local part (exact, unique)
  L4 name evidence          EXACT_NAME (accented) > FOLDED_NAME (accent-insensitive) > REORDERED_NAME (same tokens)
     GIVEN_FAMILY_ONLY      family + given agree, middle names missing / different — weak, but a plausible candidate:
                            next to a stronger candidate it makes the row AMBIGUOUS (near-duplicate)
     UPN_PATTERN_ONLY       given.surname@domain inferred from the name, display name differs — candidate generation only

Name / pattern evidence never becomes AUTO_MATCH_SAFE on its own: it additionally needs supporting organisation
evidence (cfg.org_evidence, e.g. a directory department that equals the employee's department). Accent folding and
e-mail patterns are candidate-generation aids, not proof.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Sequence

# Operational classes (exactly one per employee row).
AUTO_MATCH_SAFE = "AUTO_MATCH_SAFE"
NEEDS_REVIEW = "NEEDS_REVIEW"
NO_ACCOUNT = "NO_ACCOUNT"
AMBIGUOUS = "AMBIGUOUS"
INACTIVE_EMPLOYEE = "INACTIVE_EMPLOYEE"
EXCLUDED_DEMO = "EXCLUDED_DEMO"
CLASSES = (AUTO_MATCH_SAFE, NEEDS_REVIEW, AMBIGUOUS, NO_ACCOUNT, INACTIVE_EMPLOYEE, EXCLUDED_DEMO)

# Existing AccountUpn verification (reported separately; never overwritten).
ALREADY_MAPPED_VALID = "ALREADY_MAPPED_VALID"
ALREADY_MAPPED_INVALID = "ALREADY_MAPPED_INVALID"
ALREADY_MAPPED_DUPLICATE = "ALREADY_MAPPED_DUPLICATE"

# Directory account classes.
MEMBER_ENABLED = "MEMBER_ENABLED"
MEMBER_DISABLED = "MEMBER_DISABLED"
MEMBER_STATUS_UNKNOWN = "MEMBER_STATUS_UNKNOWN"
GUEST = "GUEST"
SERVICE_TEST = "SERVICE_TEST"

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"

# Generic service / test / admin / shared-mailbox markers in a UPN local part. Tenant-specific exclusions
# (resource mailboxes, named service identities) come from Config.excluded_upns / excluded_local_patterns.
_GENERIC_SERVICE_RE = re.compile(
    r"(^|[._-])(admin|administrator|svc|service|test|testing|demo|spike|noreply|no-reply|info|support|helpdesk|it|"
    r"system|scan|scanner|mailer|bot)([._-]|\d|$)")

_STRONG = ("EXACT_EMPLOYEE_ID", "EXACT_WORK_EMAIL", "EXACT_LEGACY_USERNAME")
_NAME_RANK = {"EXACT_NAME": 3, "FOLDED_NAME": 2, "REORDERED_NAME": 1}


@dataclass(frozen=True)
class Employee:
    item_id: int
    legacy_id: str
    name: str
    active: bool
    legacy_user_name: str = ""
    account_upn: str = ""
    batch: str = ""
    department: str = ""
    employee_code: str = ""
    work_email: str = ""            # only if a trustworthy work-email field exists
    placeholder: bool = False


@dataclass(frozen=True)
class Account:
    object_id: str
    upn: str
    display_name: str
    user_type: str                   # "Member" | "Guest"
    enabled: Optional[bool]          # None = not verified
    mail: str = ""
    employee_id: str = ""
    department: str = ""


@dataclass
class Config:
    org_domains: Sequence[str]
    demo_batches: Sequence[str] = ("DEMO_ONLY",)
    # When set, rows outside these migration batches are not real employees (e.g. a manual test row): EXCLUDED_DEMO.
    real_batches: Optional[Sequence[str]] = None
    excluded_upns: Sequence[str] = ()             # named service / test / resource identities (private config)
    excluded_local_patterns: Sequence[str] = ()   # extra regexes on the UPN local part (private config)
    # Optional supporting organisation evidence: (employee, account) -> True when an independent org attribute agrees.
    org_evidence: Optional[Callable[[Employee, Account], bool]] = None


# ---------------------------------------------------------------- normalisation

def normalize(s: Optional[str]) -> str:
    """NFC, trimmed, single-spaced, case-folded. Accents are kept."""
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"\s+", " ", s).strip().casefold()


def fold(s: Optional[str]) -> str:
    """Accent-insensitive comparison form (secondary signal only): strips combining marks, maps đ -> d."""
    s = normalize(s).replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


def name_tokens(s: Optional[str]) -> list:
    return fold(s).split()


def display_core(s: Optional[str]) -> str:
    """Display name without a trailing bracketed tag, e.g. 'Name (TEAM-X)' -> 'Name'."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", s or "").strip()


def upn_local(upn: str) -> str:
    return normalize(upn).split("@", 1)[0]


def upn_domain(upn: str) -> str:
    u = normalize(upn)
    return u.split("@", 1)[1] if "@" in u else ""


def vn_upn_local(name: str) -> str:
    """given.surname convention for a Vietnamese 'Surname [Middle...] Given' name (candidate generation only)."""
    t = name_tokens(name)
    return f"{t[-1]}.{t[0]}" if len(t) >= 2 else ""


def legacy_consistent(name: str, legacy_user_name: str) -> bool:
    """Legacy 'given.initials' user name agrees with the name (e.g. 'Surname Middle Given' -> 'given.sm')."""
    t = name_tokens(name)
    lu = normalize(legacy_user_name)
    if len(t) < 2 or "." not in lu:
        return False
    given, initials = lu.split(".", 1)
    return fold(given).replace(" ", "") == t[-1] and fold(initials).replace(" ", "") == "".join(x[0] for x in t[:-1])


# ---------------------------------------------------------------- directory

def classify_account(a: Account, cfg: Config) -> str:
    upn = normalize(a.upn)
    if a.user_type.casefold() == "guest" or "#ext#" in upn:
        return GUEST
    local = upn_local(upn)
    if upn in {normalize(x) for x in cfg.excluded_upns} or _GENERIC_SERVICE_RE.search(local) \
            or any(re.search(p, local) for p in cfg.excluded_local_patterns):
        return SERVICE_TEST
    if upn_domain(upn) not in {normalize(d) for d in cfg.org_domains}:
        return SERVICE_TEST                       # tenant-default / foreign domain member: not a business account
    if a.enabled is True:
        return MEMBER_ENABLED
    if a.enabled is False:
        return MEMBER_DISABLED
    return MEMBER_STATUS_UNKNOWN


def _name_evidence(emp_name: str, display: str) -> Optional[str]:
    core = display_core(display)
    if not core:
        return None
    if normalize(emp_name) == normalize(core):
        return "EXACT_NAME"
    if fold(emp_name) and fold(emp_name) == fold(core):
        return "FOLDED_NAME"
    te, td = name_tokens(emp_name), name_tokens(core)
    if len(te) >= 2 and Counter(te) == Counter(td):
        return "REORDERED_NAME"
    # Near-duplicate: family + given agree, middle names missing or different (either token order).
    if len(te) >= 2 and len(td) >= 2 and (td[0], td[-1]) in ((te[0], te[-1]), (te[-1], te[0])):
        return "GIVEN_FAMILY_ONLY"
    return None


def _exclusion(e: Employee, cfg: Config) -> Optional[str]:
    if e.batch in cfg.demo_batches or (e.legacy_id or "").upper().startswith("DEMO-") \
            or (e.name or "").upper().startswith("DEMO "):
        return "DEMO_ONLY"
    if cfg.real_batches is not None and e.batch not in cfg.real_batches:
        return "UNBATCHED_TEST_ROW"
    return None


def _is_demo(e: Employee, cfg: Config) -> bool:
    return _exclusion(e, cfg) is not None


# ---------------------------------------------------------------- matching

def match(employees: Iterable[Employee], directory: Iterable[Account], cfg: Config) -> dict:
    emps = list(employees)
    accts = list(directory)
    kind = {a.object_id: classify_account(a, cfg) for a in accts}
    by_upn = {normalize(a.upn): a for a in accts}
    real = [e for e in emps if not _is_demo(e, cfg)]

    # Duplicate detection (employees: real rows; directory: all non-guest accounts).
    def groups(items, key):
        g = defaultdict(list)
        for it in items:
            k = key(it)
            if k:
                g[k].append(it)
        return {k: v for k, v in g.items() if len(v) > 1}

    emp_dup_folded = groups(real, lambda e: fold(e.name))
    emp_dup_tokens = groups(real, lambda e: " ".join(sorted(name_tokens(e.name))))
    emp_dup_pattern = groups(real, lambda e: vn_upn_local(e.name))      # same given.surname -> pattern collision
    dir_people = [a for a in accts if kind[a.object_id] != GUEST]
    dir_dup_folded = groups(dir_people, lambda a: fold(display_core(a.display_name)))
    dir_dup_tokens = groups(dir_people, lambda a: " ".join(sorted(name_tokens(display_core(a.display_name)))))
    dup_emp_ids = {e.item_id for v in list(emp_dup_folded.values()) + list(emp_dup_tokens.values()) for e in v}
    dup_dir_ids = {a.object_id for v in list(dir_dup_folded.values()) + list(dir_dup_tokens.values()) for a in v}
    pattern_dup_ids = {e.item_id for v in emp_dup_pattern.values() for e in v}

    # Existing AccountUpn values (all rows incl. demo: they occupy the unique index).
    existing = Counter(normalize(e.account_upn) for e in emps if e.account_upn)

    rows = []
    for e in emps:
        row = {"itemId": e.item_id, "legacyId": e.legacy_id, "name": e.name, "active": e.active,
               "department": e.department, "currentAccountUpn": e.account_upn, "candidate": None,
               "candidates": [], "classification": None, "confidence": None, "reasons": [],
               "mappedState": None, "evidence": []}
        if _is_demo(e, cfg):
            row.update(classification=EXCLUDED_DEMO, reasons=[_exclusion(e, cfg)])
            rows.append(row)
            continue

        if e.account_upn:
            a = by_upn.get(normalize(e.account_upn))
            if existing[normalize(e.account_upn)] > 1:
                row["mappedState"] = ALREADY_MAPPED_DUPLICATE
            elif a and kind[a.object_id] == MEMBER_ENABLED:
                row["mappedState"] = ALREADY_MAPPED_VALID
            else:
                row["mappedState"] = ALREADY_MAPPED_INVALID
            row["reasons"].append("ALREADY_MAPPED")

        # Candidate generation over every directory account.
        cands = []
        for a in accts:
            ev = []
            if e.employee_code and a.employee_id and normalize(e.employee_code) == normalize(a.employee_id):
                ev.append("EXACT_EMPLOYEE_ID")
            if e.work_email and normalize(e.work_email) in (normalize(a.upn), normalize(a.mail)):
                ev.append("EXACT_WORK_EMAIL")
            if e.legacy_user_name and normalize(e.legacy_user_name) == upn_local(a.upn) \
                    and upn_domain(a.upn) in {normalize(d) for d in cfg.org_domains}:
                ev.append("EXACT_LEGACY_USERNAME")
            ne = _name_evidence(e.name, a.display_name)
            if ne:
                ev.append(ne)
            pat = vn_upn_local(e.name)
            if pat and upn_local(a.upn) == pat and upn_domain(a.upn) in {normalize(d) for d in cfg.org_domains}:
                ev.append("UPN_MATCHES_NAME_PATTERN")
            if not ev:
                continue
            if not any(x in _STRONG or x in _NAME_RANK or x == "GIVEN_FAMILY_ONLY" for x in ev):
                ev = ["UPN_PATTERN_ONLY"]
            if cfg.org_evidence and cfg.org_evidence(e, a):
                ev.append("ORG_EVIDENCE")
            cands.append({"objectId": a.object_id, "upn": a.upn, "displayName": a.display_name,
                          "kind": kind[a.object_id], "enabled": a.enabled, "evidence": ev})
        row["candidates"] = cands
        if e.legacy_user_name and legacy_consistent(e.name, e.legacy_user_name):
            row["evidence"].append("LEGACY_USERNAME_CONSISTENT_WITH_NAME")
        if e.item_id in dup_emp_ids:
            row["reasons"].append("DUPLICATE_EMPLOYEE_NAME")
        if e.item_id in pattern_dup_ids:
            row["evidence"].append("SHARED_NAME_PATTERN_WITH_OTHER_EMPLOYEE")

        biz = (MEMBER_ENABLED, MEMBER_DISABLED, MEMBER_STATUS_UNKNOWN)
        strong = [c for c in cands if any(x in _STRONG or x in _NAME_RANK for x in c["evidence"])]
        weak = [c for c in cands if c not in strong]
        business = [c for c in strong if c["kind"] in biz]
        weak_biz = [c for c in weak if c["kind"] in biz]
        near = [c for c in weak_biz if "GIVEN_FAMILY_ONLY" in c["evidence"]]
        if business and any(c["evidence"] == ["UPN_PATTERN_ONLY"] for c in weak_biz):
            row["evidence"].append("NAME_PATTERN_UPN_BELONGS_TO_OTHER_ACCOUNT")

        if not e.active:
            # Candidate kept for analysis only; no onboarding recommendation.
            row.update(classification=INACTIVE_EMPLOYEE, confidence=None)
            row["reasons"].append("INACTIVE_EMPLOYEE")
            if len(business) == 1:
                row["candidate"] = business[0]
                if business[0]["kind"] == MEMBER_ENABLED:
                    row["evidence"].append("INACTIVE_WITH_ENABLED_ACCOUNT")
            rows.append(row)
            continue

        if len(business) > 1 or (business and near):
            # >1 plausible account (incl. a same family+given near-duplicate): never pick the "closest".
            row.update(classification=AMBIGUOUS, confidence=LOW)
            row["reasons"].append("MULTIPLE_DIRECTORY_CANDIDATES")
            if near:
                row["reasons"].append("NEAR_DUPLICATE_DIRECTORY_NAME")
        elif len(business) == 1:
            c = business[0]
            row["candidate"] = c
            if c["kind"] == MEMBER_DISABLED:
                row.update(classification=NEEDS_REVIEW, confidence=LOW)
                row["reasons"].append("DIRECTORY_ACCOUNT_DISABLED")
            elif c["kind"] == MEMBER_STATUS_UNKNOWN:
                row.update(classification=NEEDS_REVIEW, confidence=LOW)
                row["reasons"].append("DIRECTORY_STATUS_UNVERIFIED")
            else:
                row.update(classification=NEEDS_REVIEW, confidence=_confidence(row, c))
                row["reasons"] += [x for x in c["evidence"] if x in _STRONG]
                names = [x for x in c["evidence"] if x in _NAME_RANK]
                if names and not any(x in _STRONG for x in c["evidence"]):
                    row["reasons"].append("UNIQUE_NAME_MATCH_WITH_SUPPORT" if "ORG_EVIDENCE" in c["evidence"]
                                          else "NAME_ONLY")
            if c["objectId"] in dup_dir_ids:
                row["reasons"].append("DUPLICATE_DIRECTORY_NAME")
            if "DUPLICATE_EMPLOYEE_NAME" in row["reasons"] or "DUPLICATE_DIRECTORY_NAME" in row["reasons"]:
                row.update(classification=AMBIGUOUS, confidence=LOW)
        else:
            others = [c for c in strong if c["kind"] in (GUEST, SERVICE_TEST)]
            if others:
                row.update(classification=NEEDS_REVIEW, confidence=LOW)
                if any(c["kind"] == GUEST for c in others):
                    row["reasons"].append("GUEST_ACCOUNT_ONLY")
                if any(c["kind"] == SERVICE_TEST for c in others):
                    row["reasons"].append("SERVICE_ACCOUNT_CONFLICT")
            elif len(weak_biz) > 1:
                row.update(classification=AMBIGUOUS, confidence=LOW)
                row["reasons"].append("MULTIPLE_DIRECTORY_CANDIDATES")
            elif len(weak_biz) == 1:
                c = weak_biz[0]
                row.update(classification=NEEDS_REVIEW, confidence=LOW, candidate=c)
                row["reasons"].append("GIVEN_FAMILY_ONLY" if "GIVEN_FAMILY_ONLY" in c["evidence"] else "UPN_PATTERN_ONLY")
                if c["kind"] == MEMBER_DISABLED:
                    row["reasons"].append("DIRECTORY_ACCOUNT_DISABLED")
                elif c["kind"] == MEMBER_STATUS_UNKNOWN:
                    row["reasons"].append("DIRECTORY_STATUS_UNVERIFIED")
            else:
                row.update(classification=NO_ACCOUNT, confidence=None)
                row["reasons"].append("NO_DIRECTORY_CANDIDATE")

        if row["mappedState"]:
            # Existing value is never overwritten: report it, never propose a different one automatically.
            if row["classification"] == AUTO_MATCH_SAFE:
                row["classification"] = NEEDS_REVIEW
            if row["mappedState"] != ALREADY_MAPPED_VALID or (
                    row["candidate"] and normalize(row["candidate"]["upn"]) != normalize(e.account_upn)):
                row.update(classification=AMBIGUOUS if row["candidate"] else NEEDS_REVIEW)
        rows.append(row)

    # Promote to AUTO_MATCH_SAFE only where every condition holds (strong deterministic evidence required).
    for r in rows:
        if r["classification"] == NEEDS_REVIEW and r["candidate"] and not _pre_safe_violations(r, kind):
            r["classification"] = AUTO_MATCH_SAFE
            r["confidence"] = HIGH

    # Final-set simulation: one proposed UPN per employee, no clash with existing values (incl. demo rows).
    proposed = defaultdict(list)
    for r in rows:
        if r["classification"] in (AUTO_MATCH_SAFE, NEEDS_REVIEW) and r["candidate"] and not r["currentAccountUpn"]:
            proposed[normalize(r["candidate"]["upn"])].append(r)
    collisions = {}
    for upn, rs in proposed.items():
        clash_existing = existing.get(upn, 0) > 0
        if len(rs) > 1 or clash_existing:
            collisions[upn] = {"employees": [r["itemId"] for r in rs], "existingMapping": clash_existing}
            for r in rs:
                r["classification"] = AMBIGUOUS
                r["confidence"] = LOW
                r["reasons"].append("PROPOSED_UPN_COLLISION" if len(rs) > 1 else "EXISTING_MAPPING_CONFLICT")
    for r in rows:
        r["reasons"] = list(dict.fromkeys(r["reasons"]))
        r["safeViolations"] = safe_violations(r) if r["classification"] == AUTO_MATCH_SAFE else None

    conflicts = {
        "duplicateEmployeeNames": [[e.item_id for e in v] for v in _uniq(emp_dup_folded, emp_dup_tokens)],
        "employeeNamePatternCollisions": [[e.item_id for e in v] for v in emp_dup_pattern.values()],
        "duplicateDirectoryNames": [[a.object_id for a in v] for v in _uniq(dir_dup_folded, dir_dup_tokens)],
        "multipleCandidateCases": [r["itemId"] for r in rows if "MULTIPLE_DIRECTORY_CANDIDATES" in r["reasons"]],
        "proposedUpnCollisions": collisions,
        "existingAccountUpnDuplicates": [u for u, n in existing.items() if n > 1],
    }
    return {"rows": rows, "conflicts": conflicts, "accountKinds": kind, "summary": summarize(rows, accts, kind)}


def _uniq(*gs):
    seen, out = set(), []
    for g in gs:
        for v in g.values():
            k = tuple(sorted(id(x) for x in v))
            if k not in seen:
                seen.add(k)
                out.append(v)
    return out


def _confidence(row, c) -> str:
    ev = c["evidence"]
    if any(x in _STRONG for x in ev):
        return HIGH
    rank = max((_NAME_RANK.get(x, 0) for x in ev), default=0)
    support = ("UPN_MATCHES_NAME_PATTERN" in ev) + ("LEGACY_USERNAME_CONSISTENT_WITH_NAME" in row["evidence"])
    if rank >= 2 and support == 2:
        return HIGH
    if rank >= 1 and support >= 1:
        return MEDIUM
    return LOW


def _pre_safe_violations(r, kind) -> list:
    v = []
    c = r["candidate"]
    if not r["active"]:
        v.append("EMPLOYEE_NOT_ACTIVE")
    if not c or c["kind"] != MEMBER_ENABLED:
        v.append("CANDIDATE_NOT_ENABLED_MEMBER")
    if c and sum(1 for x in r["candidates"] if x["kind"] in (MEMBER_ENABLED, MEMBER_DISABLED, MEMBER_STATUS_UNKNOWN)
                 and x["evidence"] != ["UPN_PATTERN_ONLY"]) != 1:      # near-duplicates count as candidates
        v.append("NOT_EXACTLY_ONE_CANDIDATE")
    for bad in ("DUPLICATE_EMPLOYEE_NAME", "DUPLICATE_DIRECTORY_NAME", "MULTIPLE_DIRECTORY_CANDIDATES",
                "SERVICE_ACCOUNT_CONFLICT", "GUEST_ACCOUNT_ONLY", "DIRECTORY_ACCOUNT_DISABLED",
                "PROPOSED_UPN_COLLISION", "EXISTING_MAPPING_CONFLICT", "ALREADY_MAPPED", "UPN_PATTERN_ONLY",
                "GIVEN_FAMILY_ONLY", "NEAR_DUPLICATE_DIRECTORY_NAME", "DIRECTORY_STATUS_UNVERIFIED"):
        if bad in r["reasons"]:
            v.append(bad)
    if c:
        ev = c["evidence"]
        deterministic = any(x in _STRONG for x in ev)
        supported_name = any(x in _NAME_RANK for x in ev) and "ORG_EVIDENCE" in ev \
            and "UPN_MATCHES_NAME_PATTERN" in ev and "LEGACY_USERNAME_CONSISTENT_WITH_NAME" in r["evidence"] \
            and "SHARED_NAME_PATTERN_WITH_OTHER_EMPLOYEE" not in r["evidence"]
        if not (deterministic or supported_name):
            v.append("NO_STRONG_DETERMINISTIC_EVIDENCE")
        # Contradiction: a strong identifier points at a different account than the candidate.
        others = [x for x in r["candidates"] if x is not c and any(y in _STRONG for y in x["evidence"])]
        if others:
            v.append("CONTRADICTORY_EVIDENCE")
    return v


def safe_violations(r) -> list:
    """Unmet AUTO_MATCH_SAFE conditions for a row after the final-set simulation ([] = eligible)."""
    return _pre_safe_violations(r, None)


def summarize(rows, accts, kind) -> dict:
    real = [r for r in rows if r["classification"] != EXCLUDED_DEMO]
    k = Counter(kind.values())
    reasons = Counter(x for r in real for x in r["reasons"])
    return {
        "employeeRows": len(rows), "realEmployees": len(real),
        "demoRows": sum(1 for r in rows if r["classification"] == EXCLUDED_DEMO),
        "activeReal": sum(1 for r in real if r["active"]), "inactiveReal": sum(1 for r in real if not r["active"]),
        "accountUpnPopulated": sum(1 for r in real if r["currentAccountUpn"]),
        "directory": {"total": len(accts), "enabledMembers": k[MEMBER_ENABLED], "disabledMembers": k[MEMBER_DISABLED],
                      "unknownStatusMembers": k[MEMBER_STATUS_UNKNOWN], "guests": k[GUEST],
                      "serviceTestExcluded": k[SERVICE_TEST]},
        "classes": {c: sum(1 for r in rows if r["classification"] == c) for c in CLASSES},
        "mapped": {s: sum(1 for r in real if r["mappedState"] == s)
                   for s in (ALREADY_MAPPED_VALID, ALREADY_MAPPED_INVALID, ALREADY_MAPPED_DUPLICATE)},
        "confidence": dict(Counter(r["confidence"] for r in real if r["confidence"])),
        "topReasons": reasons.most_common(),
    }


REVIEW_ORDER = {AUTO_MATCH_SAFE: 0, NEEDS_REVIEW: 1, AMBIGUOUS: 2, NO_ACCOUNT: 3, INACTIVE_EMPLOYEE: 4, EXCLUDED_DEMO: 5}


def review_sort_key(r) -> tuple:
    return (REVIEW_ORDER[r["classification"]], normalize(r["name"]))
