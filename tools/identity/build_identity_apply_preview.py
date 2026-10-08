"""EMPLOYEE-IDENTITY-MAPPING-REVIEW-01 — build an APPLY PREVIEW from a human-reviewed mapping CSV (generic; no tenant data).

PREVIEW ONLY. This module never calls SharePoint, the directory or any network API; it reads local files and writes a
local preview. Applying the preview is a separate task (EMPLOYEE-IDENTITY-APPLY-01) that needs explicit owner approval.

    validate_review(rows)                                  -> list of vocabulary / structure errors per row
    build_preview(rows, employees, directory, cfg)         -> {"apply": [...], "rejected": [...], "summary": {...}}

Review decisions (closed vocabulary):
    APPROVE               CandidateUpn confirmed (ReviewerUpn empty or equal to CandidateUpn)
    CHANGE                ReviewerUpn REQUIRED: the approved replacement account
    REJECT                candidate wrong              -> no mapping
    NO_ACCOUNT_CONFIRMED  no existing account          -> no mapping
    DEFER                 unresolved                   -> no mapping
    (blank)               not reviewed                 -> no mapping
A row is never approved merely because CandidateUpn exists.

Approval basis (column ApprovalBasis, closed vocabulary) and environment boundary:
    HR_IT_APPROVED            HR/IT signed the mapping - valid in every environment
    STAGING_TEMPORARY_BYPASS  Project Owner temporary bypass - valid for environment STAGING ONLY; never UAT/PRODUCTION
is_identity_approved_for(basis, environment) is the single readiness predicate; tooling must use it rather than read
the marker itself.

An apply row is produced only when every check passes (otherwise the row is rejected with reason codes):
    one row per employee, one employee per UPN, no duplicate proposed UPN, no clash with another employee's AccountUpn;
    account exists in the supplied directory snapshot, is enabled, is a Member (not Guest), is not a service / test /
    admin / shared identity; employee exists, is active, identity (LegacyId) unchanged, and its current AccountUpn is
    empty and equal to the value seen at review time.

CLI:
    python build_identity_apply_preview.py --review reviewed.csv --employees employees.json --directory directory.json
        --config config.json --environment STAGING --out preview.json
    employees.json : [{"itemId", "legacyId", "active", "accountUpn"}]
    directory.json : [{"objectId", "upn", "displayName", "userType", "enabled"}]
    config.json    : {"orgDomains": [...], "excludedUpns": [...], "excludedLocalPatterns": [...]}
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from typing import Iterable, Mapping, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from employee_matching import MEMBER_ENABLED, Account, Config, classify_account, normalize  # noqa: E402

DECISIONS = ("APPROVE", "REJECT", "CHANGE", "NO_ACCOUNT_CONFIRMED", "DEFER")
HR_IT_APPROVED = "HR_IT_APPROVED"
STAGING_TEMPORARY_BYPASS = "STAGING_TEMPORARY_BYPASS"
APPROVAL_BASES = (HR_IT_APPROVED, STAGING_TEMPORARY_BYPASS)
ENVIRONMENTS = ("STAGING", "UAT", "PRODUCTION")
NO_MAPPING = ("REJECT", "NO_ACCOUNT_CONFIRMED", "DEFER", "")
_UPN_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}$")


def is_identity_approved_for(basis: str, environment: str) -> bool:
    """True only if a mapping with this approval basis may be applied / relied on in the environment."""
    if environment not in ENVIRONMENTS:
        return False
    if basis == HR_IT_APPROVED:
        return True
    return basis == STAGING_TEMPORARY_BYPASS and environment == "STAGING"


def _s(row: Mapping, k: str) -> str:
    return str(row.get(k) or "").strip()


def validate_review(rows: Sequence[Mapping]) -> list:
    """Structural errors: [{"row": n, "employeeItemId": id, "errors": [...]}] (empty list = file is well formed)."""
    out = []
    for n, r in enumerate(rows, 1):
        e = []
        d = _s(r, "ReviewerDecision").upper()
        if d and d not in DECISIONS:
            e.append("INVALID_DECISION")
        if d in DECISIONS and _s(r, "ReviewerDecision") != d:
            e.append("DECISION_NOT_CANONICAL_CASE")
        ru = normalize(_s(r, "ReviewerUpn"))
        if d == "CHANGE" and not ru:
            e.append("CHANGE_REQUIRES_REVIEWER_UPN")
        if ru and not _UPN_RE.match(ru):
            e.append("REVIEWER_UPN_INVALID_FORMAT")
        if d == "APPROVE" and not _s(r, "CandidateUpn") and not ru:
            e.append("APPROVE_WITHOUT_CANDIDATE")
        if d == "APPROVE" and ru and _s(r, "CandidateUpn") and ru != normalize(_s(r, "CandidateUpn")):
            e.append("APPROVE_WITH_DIFFERENT_UPN_USE_CHANGE")
        if d in ("REJECT", "NO_ACCOUNT_CONFIRMED", "DEFER") and ru:
            e.append("REVIEWER_UPN_NOT_ALLOWED_FOR_DECISION")
        if d in ("APPROVE", "CHANGE") and not (_s(r, "ReviewedBy") and _s(r, "ReviewedOn")):
            e.append("REVIEWER_IDENTITY_OR_DATE_MISSING")
        if d in ("APPROVE", "CHANGE") and _s(r, "ApprovalBasis") not in APPROVAL_BASES:
            e.append("APPROVAL_BASIS_MISSING_OR_INVALID")
        if e:
            out.append({"row": n, "employeeItemId": _s(r, "EmployeeItemId"), "errors": e})
    return out


def _proposed_upn(r: Mapping) -> str:
    d = _s(r, "ReviewerDecision")
    if d == "CHANGE":
        return normalize(_s(r, "ReviewerUpn"))
    if d == "APPROVE":
        return normalize(_s(r, "ReviewerUpn") or _s(r, "CandidateUpn"))
    return ""


def build_preview(rows: Sequence[Mapping], employees: Iterable[Mapping], directory: Iterable[Mapping],
                  cfg: Config, environment: str) -> dict:
    emps = {int(e["itemId"]): e for e in employees}
    accts = {normalize(a["upn"]): a for a in directory}
    struct = {x["row"]: x["errors"] for x in validate_review(rows)}
    item_count = Counter(_s(r, "EmployeeItemId") for r in rows)
    candidates = []
    rejected = []
    for n, r in enumerate(rows, 1):
        d = _s(r, "ReviewerDecision")
        if d in NO_MAPPING or d.upper() not in DECISIONS:
            if n in struct:
                rejected.append({"row": n, "employeeItemId": _s(r, "EmployeeItemId"), "decision": d,
                                 "reasons": struct[n]})
            continue
        reasons = list(struct.get(n, []))
        basis = _s(r, "ApprovalBasis")
        if basis in APPROVAL_BASES and not is_identity_approved_for(basis, environment):
            reasons.append(f"APPROVAL_BASIS_NOT_VALID_FOR_{environment}")
        upn = _proposed_upn(r)
        try:
            item = int(_s(r, "EmployeeItemId"))
        except ValueError:
            item = None
            reasons.append("EMPLOYEE_ITEM_ID_INVALID")
        if item_count[_s(r, "EmployeeItemId")] > 1:
            reasons.append("DUPLICATE_EMPLOYEE_ROW_IN_REVIEW")
        e = emps.get(item)
        if e is None:
            reasons.append("EMPLOYEE_NOT_FOUND")
        else:
            if e.get("active") is not True:
                reasons.append("EMPLOYEE_NOT_ACTIVE")
            if normalize(e.get("legacyId")) != normalize(_s(r, "LegacyId")):
                reasons.append("EMPLOYEE_IDENTITY_CHANGED")
            cur = normalize(e.get("accountUpn"))
            if cur != normalize(_s(r, "CurrentAccountUpn")):
                reasons.append("ACCOUNTUPN_CHANGED_SINCE_REVIEW")
            elif cur:
                reasons.append("ALREADY_MAPPED_NO_OVERWRITE")
        a = accts.get(upn)
        if not upn or not _UPN_RE.match(upn):
            reasons.append("PROPOSED_UPN_INVALID")
        elif a is None:
            reasons.append("ACCOUNT_NOT_FOUND")
        else:
            kind = classify_account(Account(a.get("objectId", ""), a["upn"], a.get("displayName", ""),
                                            a.get("userType", ""), a.get("enabled")), cfg)
            if kind != MEMBER_ENABLED:
                reasons.append({"GUEST": "ACCOUNT_IS_GUEST", "SERVICE_TEST": "ACCOUNT_IS_SERVICE_OR_TEST",
                                "MEMBER_DISABLED": "ACCOUNT_DISABLED",
                                "MEMBER_STATUS_UNKNOWN": "ACCOUNT_STATUS_UNVERIFIED"}[kind])
        candidates.append({"row": n, "employeeItemId": item, "legacyId": _s(r, "LegacyId"), "decision": d,
                           "upn": upn, "basis": basis, "reasons": reasons})

    # One employee per UPN, and no clash with another employee's existing AccountUpn.
    upn_count = Counter(c["upn"] for c in candidates if c["upn"])
    owners = {normalize(e.get("accountUpn")): i for i, e in emps.items() if e.get("accountUpn")}
    for c in candidates:
        if c["upn"] and upn_count[c["upn"]] > 1:
            c["reasons"].append("UPN_PROPOSED_FOR_MULTIPLE_EMPLOYEES")
        if c["upn"] in owners and owners[c["upn"]] != c["employeeItemId"]:
            c["reasons"].append("UPN_ALREADY_USED_BY_OTHER_EMPLOYEE")
    apply_rows = [{"employeeItemId": c["employeeItemId"], "legacyId": c["legacyId"], "accountUpn": c["upn"],
                   "decision": c["decision"], "approvalBasis": c["basis"]} for c in candidates if not c["reasons"]]
    rejected += [{"row": c["row"], "employeeItemId": c["employeeItemId"], "decision": c["decision"],
                  "reasons": list(dict.fromkeys(c["reasons"]))} for c in candidates if c["reasons"]]
    decisions = Counter(_s(r, "ReviewerDecision") or "(blank)" for r in rows)
    return {"mode": "PREVIEW_ONLY_NO_WRITES", "environment": environment, "apply": apply_rows, "rejected": rejected,
            "summary": {"reviewRows": len(rows), "decisions": dict(decisions), "applyRows": len(apply_rows),
                        "rejectedRows": len(rejected), "structuralErrors": len(struct)}}


def _read_csv(path: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build an identity APPLY PREVIEW (no writes).")
    for k in ("review", "employees", "directory", "config", "out"):
        p.add_argument("--" + k, required=True)
    p.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    a = p.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        c = json.load(f)
    cfg = Config(org_domains=c["orgDomains"], excluded_upns=c.get("excludedUpns", ()),
                 excluded_local_patterns=c.get("excludedLocalPatterns", ()))
    with open(a.employees, encoding="utf-8") as f:
        emps = json.load(f)
    with open(a.directory, encoding="utf-8") as f:
        dirs = json.load(f)
    res = build_preview(_read_csv(a.review), emps, dirs, cfg, a.environment)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps(res["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
