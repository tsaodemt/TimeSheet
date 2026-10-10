"""Consistency check for the R3 Open Spec (OpenSpec change `r3-planning-effort-hour-registration`). Spec-only: reads markdown,
changes nothing.

Checks: decision register parse (BLOCKING / conditional / NON_BLOCKING / RESOLVED / NOT_APPLICABLE), milestone gate sets in the
register equal the sets derived from its Blocking column, tally numbers in register / proposal / design agree, every OD id
referenced anywhere in the change exists in the register, all 14 NR-EFF rows carry a decision dependency that refers only to
registered ids, and known stale wording is absent. M2 (EPIC 16) checks: while an M2 decision is open, the project-effort
spec states its topic only next to that decision id (no hard-coded unit / phase / period / actual source / visibility /
blank-zero / PM rule), EPIC 16 has no approval workflow (OD-26), and no HourRegistrations field or link leaks into EPIC 16.
Once an M2 decision is resolved (OD-14 / OD-19 / OD-40) its §C answer and the spec statement must agree; OD-41 is
NOT_APPLICABLE exactly when OD-19 = TIMESHEETENTRIES; the Vietnamese M2 summary table equals the derived M2 gate and does
not mention closed M2 decisions. The derived state of every M2 decision is printed as `m2_state`.

    python tools/spec/check_r3_open_spec.py [change_dir]      -> exit 0 when consistent, 1 otherwise
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "..", "openspec", "changes", "r3-planning-effort-hour-registration")
R3_GATES = ("M1", "M2", "M3", "GL")


def read(d, *p):
    with open(os.path.join(d, *p), encoding="utf-8") as fh:
        return fh.read()


def rows(md):
    for line in md.splitlines():
        if line.startswith("| OD-"):
            yield [c.strip() for c in line.strip().strip("|").split("|")]


def classify(md):
    """-> (blocking{id: set(gates)}, conditional{id: set}, nonblocking set, resolved set, not_applicable set)"""
    blocking, conditional, nonblocking, resolved, not_applicable = {}, {}, set(), set(), set()
    for c in rows(md):
        oid = re.match(r"OD-\d\d", c[0]).group(0)
        if c[1].lstrip("*").startswith("NOT_APPLICABLE"):  # §C: made moot by another decision
            not_applicable.add(oid)
            continue
        if "RESOLVED" in c[1]:  # §C: owner decision or evidence
            resolved.add(oid)
            continue
        if len(c) < 8:
            continue
        col = c[7]
        gates = set()
        for m in re.finditer(r"(?<!NON_)BLOCKING\*?\*?\s*([^|;(]*)", col):
            gates |= set(re.findall(r"\b(M[1-4]|GL)\b", m.group(1)))
        if "CONDITIONAL" in col:
            conditional[oid] = set(re.findall(r"\b(M[1-4]|GL)\b", col))
        elif gates & set(R3_GATES):
            blocking[oid] = gates & set(R3_GATES)
        else:
            nonblocking.add(oid)
    return blocking, conditional, nonblocking, resolved, not_applicable


def resolution(md, oid):
    """§C resolution cell of a decision, or '' when it is still open."""
    for c in rows(md):
        if re.match(oid + r"(?!\d)", c[0]) and len(c) < 8:
            return c[1]
    return ""


def gate_table(md):
    out = {}
    for line in md.splitlines():
        m = re.match(r"\| (M[1-4]|GL)(?: \([^|]*\))? \| ([^|]*) \|", line)
        if m:
            out[m.group(1)] = set(re.findall(r"OD-\d\d", m.group(2)))
    return out


def check(d=DEFAULT):
    errs = []
    dec = read(d, "decisions.md")
    blocking, conditional, nonblocking, resolved, not_applicable = classify(dec)
    registered = set(blocking) | set(conditional) | nonblocking | resolved | not_applicable
    derived = {g: {o for o, gs in blocking.items() if g in gs} for g in R3_GATES}
    table = gate_table(dec)
    for g in R3_GATES:
        if table.get(g) != derived[g]:
            errs.append("gate %s table %s != derived %s" % (g, sorted(table.get(g, [])), sorted(derived[g])))
    n_open = len(blocking) + len(conditional) + len(nonblocking)
    expect = {"unconditional": len(blocking), "conditional": len(conditional), "non": len(nonblocking), "open": n_open,
              "resolved": len(resolved)}
    for name, txt in (("decisions.md", dec), ("proposal.md", read(d, "proposal.md")), ("design.md", read(d, "design.md"))):
        for pat, key in ((r"(\d+) unconditional BLOCKING", "unconditional"), (r"(\d+) NON_BLOCKING", "non"),
                         (r"Open decisions total: \*\*(\d+)\*\*", "open"), (r"(\d+) open items after review", "open"),
                         (r"the (\d+) OPEN_DECISION items", "open"), (r"(\d+) RESOLVED_BY_EVIDENCE", "resolved"), (r"plus (\d+) resolved items", "resolved"), (r"Resolved in §C: \*\*(\d+)\*\*", "resolved")):
            for m in re.finditer(pat, txt):
                if int(m.group(1)) != expect[key]:
                    errs.append("%s: '%s' says %s, register has %d" % (name, m.group(0), m.group(1), expect[key]))
    files = []
    for root, _, fs in os.walk(d):
        files += [os.path.join(root, f) for f in fs if f.endswith(".md")]
    for f in files:
        txt = open(f, encoding="utf-8").read()
        for oid in set(re.findall(r"OD-\d\d", txt)) - registered:
            errs.append("%s references unregistered %s" % (os.path.relpath(f, d), oid))
        if os.path.basename(f).startswith("REVIEW-FIXES"):
            continue
        for bad in (r"(?<!ENV-)\bD2\b", r"already established", r"RESOLVED_RECORDED", r"RESOLVED_DEFERRED_CURRENT_SCOPE",
                    r"migration preserves both states", r"null excluded from counts, treated 0 in sums",
                    r"approved Timesheet hours", r"EPIC 17 storage unit is designed at M3"):
            if re.search(bad, txt):
                errs.append("%s contains stale wording /%s/" % (os.path.relpath(f, d), bad))
    tr = read(d, "traceability.md")
    hdr = [l for l in tr.splitlines() if l.startswith("| NR | Requirement")]
    cols = [c.strip() for c in hdr[0].strip().strip("|").split("|")]
    di = cols.index("Decision dependency")
    nr = [l for l in tr.splitlines() if re.match(r"\| NR-EFF-\d\d \|", l)]
    if len(nr) != 14:
        errs.append("NR-EFF rows %d != 14" % len(nr))
    for l in nr:
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        ids = set(re.findall(r"OD-\d\d", c[di]))
        if not ids:
            errs.append("%s has no decision dependency" % c[0])
    for nid in ("NR-EFF-13", "NR-EFF-14"):
        row = [l for l in nr if l.startswith("| " + nid)][0]
        if "OD-31" not in row:
            errs.append("%s does not reference OD-31" % nid)
    m2_state = {o: ("RESOLVED" if o in resolved else "NOT_APPLICABLE" if o in not_applicable else
                    "BLOCKING" if o in blocking else "CONDITIONAL" if o in conditional else "NON_BLOCKING")
                for o in M2_DECISIONS + (EPIC17_UNIT,)}
    errs += check_m2(d, dec, blocking, conditional, resolved, not_applicable, derived["M2"])
    errs += check_m3(d, dec, resolved)
    errs += check_m4(d, dec, resolved)
    return errs, {"blocking": sorted(blocking), "conditional": sorted(conditional), "nonblocking": sorted(nonblocking),
                  "resolved": sorted(resolved), "not_applicable": sorted(not_applicable),
                  "gates": dict({g: sorted(v) for g, v in derived.items()}, M4=sorted(m4_gate(dec))), "m2_state": m2_state}


# M2 (EPIC 16): topic -> (decision id, pattern). A requirement section of the project-effort spec that mentions a topic
# must cite the decision while it is still open (no unconditional SHALL on an unanswered question).
M2_TOPICS = {
    "unit": ("OD-14", r"\b(man-?days?|ManDays|HoursPerManDay)\b|\bhours?\b(?! ?Registration)"),
    "source": ("OD-16", r"allocation table|bảng phân bổ|import"),
    "actual source": ("OD-19", r"TimesheetEntries|timesheet"),
    "phase": ("OD-22", r"\bphases?\b"),
    "period": ("OD-23", r"\b(period|lifetime|monthly|yearly|pay period)\b"),
    "PM": ("OD-24", r"project's PM"),
    "visibility": ("OD-37", r"\b(view|visible|visibility)\b"),
    "blank/zero": ("OD-40", r"\b(blank|zero|null)\b"),
    "actual row inclusion": ("OD-33", r"\b(counted|counts|status|approved-only|draft)\b"),
}


# Every decision that was in (or entered) the M2 gate during the M2 decision work (2026-10-10), plus the M2 value-bounds
# decision; state is derived from the register.
M2_DECISIONS = ("OD-14", "OD-16", "OD-19", "OD-22", "OD-23", "OD-24", "OD-33", "OD-37", "OD-40", "OD-41", "OD-44")
EPIC17_UNIT = "OD-45"  # OD-14 is EPIC 16 only; the EPIC 17 unit stays its own M3 decision
# Once resolved, the project-effort spec must state the answer unconditionally: decision -> (answer in §C, spec patterns).
M2_RESOLVED_RULES = {
    "OD-14": (r"MAN_DAY", (r"stored and handled in man-days",
                           r"more than 2 decimal places SHALL be rejected with the typed validation error",
                           r"SHALL NOT be rounded, truncated or silently normalised")),
    "OD-19": (r"TIMESHEETENTRIES", (r"derived from the existing `TimesheetEntries`", r"OD-19 fixes the source only")),
    "OD-40": (r"BLANK_NOT_REGISTERED / ZERO_EXPLICIT", (r"distinguish BLANK \(not registered\) from numeric 0",)),
    "OD-44": (r"MIN_0 / NEGATIVE_DENY / NO_BUSINESS_MAX", (r"minimum 0", r"Negative values SHALL be denied",
                                                            r"no business maximum", r"TECHNICAL_LIMIT, not a business rule")),
    "OD-16": (r"MANUAL_PM_ENTRY", (r"entered manually by the PM \(OD-16\): no formula, no derivation from finance data and no import",)),
    "OD-22": (r"NO_PHASE_DIMENSION", (r"project × recipient with no phase dimension \(OD-22\)",)),
    "OD-23": (r"PROJECT_LIFETIME", (r"one project-lifetime value per recipient with no period dimension",)),
    "OD-24": (r"ONE_AUTHORITATIVE_PM_PER_PROJECT_MAINTAINED_BY_PMO", (r"zero or one authoritative PM",
                                                                       r"Only PMO SHALL assign or change it",
                                                                       r"PMO and Executive SHALL NOT edit allocations merely by role")),
    "OD-33": (r"APPROVED_ONLY", (r"Only `TimesheetEntries` in the Approved state SHALL count",)),
    "OD-37": (r"VIEW_PROJECT_PM_PMO_EXECUTIVE", (r"visible only to the project's authoritative PM \(own projects\), PMO \(all projects\) and Executive",
                                                 r"SHALL NOT inherit the legacy Hour Registration visibility")),
}


def check_m2(d, dec, blocking, conditional, resolved, not_applicable, m2_gate):
    errs = []
    open_ids = set(blocking) | set(conditional)
    spec = read(d, "specs", "project-effort", "spec.md")
    for oid, (answer, pats) in M2_RESOLVED_RULES.items():
        if oid in resolved:
            if not re.search(answer, resolution(dec, oid)):
                errs.append("%s resolution does not record %s" % (oid, answer))
            for pat in pats:
                if not re.search(pat, spec):
                    errs.append("%s resolved but project-effort spec does not state /%s/" % (oid, pat))
    # No business maximum: no arbitrary upper limit (999.9, 9999, 9999.99, ...) in the EPIC 16 spec.
    if "OD-44" in resolved and re.search(r"\b9{3,}(\.9+)?\b", spec):
        errs.append("project-effort spec contains an arbitrary maximum although OD-44 = NO_BUSINESS_MAX")
    # OD-19 decides the source only; the row-inclusion rule is OD-33. If M2 acceptance needs an actual-effort total
    # (HoursPerManDay conversion in an EPIC 16 criterion), an open OD-33 must block M2.
    acc = read(d, "acceptance.md")
    eff16 = [l for l in acc.splitlines() if l.startswith("| AC-EFF16-")]
    if "OD-33" not in resolved and any("HoursPerManDay" in l for l in eff16) and "OD-33" not in m2_gate:
        errs.append("M2 acceptance computes an actual-effort total but open OD-33 is not in the M2 gate")
    # EPIC 17 unit: own decision, no hidden dependency on OD-14. Either an open M3 blocker, or resolved with its own evidence
    # (rev01 A.II compares the two "số công" quantities directly) and stated in the discipline-effort spec.
    disc = read(d, "specs", "discipline-effort", "spec.md")
    if EPIC17_UNIT in resolved:
        row45 = next((l for l in dec.splitlines() if l.startswith("| %s " % EPIC17_UNIT)), "")
        if not re.search(r"MAN_DAY", resolution(dec, EPIC17_UNIT)) or "compares" not in row45:
            errs.append("%s resolved without the A.II comparison evidence" % EPIC17_UNIT)
        if not re.search(r"stored in man-days \(%s resolved" % EPIC17_UNIT, disc):
            errs.append("%s resolved but discipline-effort spec does not state man-days" % EPIC17_UNIT)
    elif EPIC17_UNIT not in blocking or "M3" not in blocking.get(EPIC17_UNIT, ()):
        errs.append("%s (EPIC 17 unit) must stay an open M3 blocker until decided" % EPIC17_UNIT)
    if EPIC17_UNIT not in disc or re.search(r"unit \(OD-14\)", disc):
        errs.append("discipline-effort unit must cite %s, not OD-14" % EPIC17_UNIT)
    tr = read(d, "traceability.md")
    for nid in ("NR-EFF-02", "NR-EFF-03"):
        line = [l for l in tr.splitlines() if l.startswith("| %s |" % nid)][0]
        if "OD-14" in line or EPIC17_UNIT not in line:
            errs.append("%s must depend on %s (EPIC 17 unit), not OD-14" % (nid, EPIC17_UNIT))
    # OD-41 only exists for a separate/hybrid actual-entry path (OD-19 = b/c).
    od19 = resolution(dec, "OD-19")
    if "TIMESHEETENTRIES" in od19 and "OD-41" not in not_applicable:
        errs.append("OD-19 = TIMESHEETENTRIES but OD-41 is not NOT_APPLICABLE")
    if "OD-41" in not_applicable and "TIMESHEETENTRIES" not in od19:
        errs.append("OD-41 NOT_APPLICABLE without OD-19 = TIMESHEETENTRIES")
    if "TIMESHEETENTRIES" in od19:
        design = read(d, "design.md")
        if re.search(r"(?m)^\| `ActualEffortEntries`(?! — \*\*not created)", design):
            errs.append("design still proposes ActualEffortEntries although OD-19 = TIMESHEETENTRIES")
    # Vietnamese meeting summary: table = exactly the derived M2 gate; no closed M2 decision is asked again.
    summ = read(d, "M2-DECISION-SUMMARY.md")
    m = re.search(r"(?ms)^## Bảng câu hỏi\n(.*?)(?=^## |\Z)", summ)
    if not m:
        errs.append("M2-DECISION-SUMMARY has no '## Bảng câu hỏi' section")
    else:
        questions = m.group(1)
        asked = {re.match(r"\| (OD-\d\d)", l).group(1) for l in questions.splitlines() if re.match(r"\| OD-\d\d \|", l)}
        if asked != set(m2_gate):
            errs.append("M2-DECISION-SUMMARY question table %s != M2 gate %s" % (sorted(asked), sorted(m2_gate)))
        for oid in sorted((resolved | not_applicable) & set(M2_DECISIONS)):
            if oid in questions:
                errs.append("M2-DECISION-SUMMARY still asks closed decision %s" % oid)
    # M3 (EPIC 17) Vietnamese meeting summary, once it exists: question table = exactly the derived M3 gate.
    if os.path.exists(os.path.join(d, "M3-DECISION-SUMMARY.md")):
        m3 = {o for o, gs in blocking.items() if "M3" in gs}
        summ3 = read(d, "M3-DECISION-SUMMARY.md")
        mm = re.search(r"(?ms)^## Bảng câu hỏi\n(.*?)(?=^## |\Z)", summ3)
        asked3 = {re.match(r"\| (OD-\d\d)", l).group(1) for l in (mm.group(1) if mm else "").splitlines() if re.match(r"\| OD-\d\d \|", l)}
        if asked3 != m3:
            errs.append("M3-DECISION-SUMMARY question table %s != M3 gate %s" % (sorted(asked3), sorted(m3)))
        for oid in sorted(resolved | not_applicable):
            if mm and re.search(r"(?m)^\| %s \|" % oid, mm.group(1)):
                errs.append("M3-DECISION-SUMMARY still asks closed decision %s" % oid)
    sections = re.split(r"(?m)^### Requirement: ", spec)[1:]
    for sec in sections:
        title = sec.splitlines()[0].strip()
        body = "\n".join(l for l in sec.splitlines()[1:] if not l.startswith("#"))
        for topic, (oid, pat) in M2_TOPICS.items():
            if oid in open_ids and re.search(pat, body, re.I) and oid not in sec:
                errs.append("project-effort '%s' states %s without open %s" % (title, topic, oid))
        if re.search(r"\b(approval|approve|lock|locked|unlock)\b", body, re.I) and "OD-26" not in sec and not title.startswith("No A.I approval"):
            errs.append("project-effort '%s' mentions approval/lock outside the OD-26 no-approval requirement" % title)
        if re.search(r"\b(ManDays|RegKey|SourceRegistration)\b", sec):
            errs.append("project-effort '%s' reuses a HourRegistrations field" % title)
        if "HourRegistrations" in sec and not title.startswith("Separate from legacy"):
            errs.append("project-effort '%s' references HourRegistrations outside the separation requirement" % title)
    if not any(t.startswith("No A.I approval") for t in (x.splitlines()[0] for x in sections)):
        errs.append("project-effort has no 'No A.I approval workflow' requirement (OD-26)")
    sec_md = read(d, "specs", "planning-security", "spec.md")
    for cap, oid in (("EFF.ProjectApprove", None), ("EFF.ProjectView", "OD-37"), ("EFF.ProjectEdit", "OD-24")):
        row = [l for l in sec_md.splitlines() if l.startswith("| `%s`" % cap)]
        if not row:
            errs.append("planning-security has no %s row" % cap)
            continue
        cells = [c.strip() for c in row[0].strip().strip("|").split("|")][1:]
        if oid is None and any(c != "NOT_APPLICABLE" for c in cells):
            errs.append("%s must be NOT_APPLICABLE for every role (OD-26)" % cap)
        if oid in open_ids and any(c == "ALLOW" for c in cells):
            errs.append("%s grants ALLOW while %s is open" % (cap, oid))
    hr = read(d, "specs", "hour-registration", "spec.md")
    for bad in ("ProjectEffortAllocations", "EFF."):
        if bad in hr:
            errs.append("hour-registration spec references EPIC 16 concept %s (M1/M2 collapse)" % bad)
    design = read(d, "design.md")
    pea = [l for l in design.splitlines() if l.startswith("| `ProjectEffortAllocations`")]
    if not pea or re.search(r"ManDays|RegKey|SourceRegistration|HourRegistrations`?\s*,? *OD-25|link to `HourRegistrations`", pea[0]):
        errs.append("design §5.2 ProjectEffortAllocations row missing or linked to HourRegistrations fields")
    return errs


# M3 (EPIC 17) owner decisions 2026-10-10: decision -> (answer in §C, checks over the change files).
M3_RESOLVED = {"OD-17": "TEAMLEADER_SAME_DISCIPLINE", "OD-18": "NO_REOPEN", "OD-27": "SINGLE_STAGE_APPROVAL",
               "OD-28": "SELF_APPROVAL_ALLOWED_EPIC17_ONLY", "OD-29": "EXISTING_ACTIVE_WORKTYPES",
               "OD-30": "EMPLOYEE_X_PROJECT_X_WORKTYPE", "OD-34": "AUDIT_ONLY", "OD-46": "M3_CAPABILITY_MATRIX",
               "OD-47": "MAN_DAY_MIN_0_2DP_NO_MAX_BLANK_NE_0", "OD-48": "PROJECT_LIFETIME"}


def _cap_row(sec_md, cap):
    row = [l for l in sec_md.splitlines() if l.startswith("| `%s`" % cap)]
    return [c.strip() for c in row[0].strip().strip("|").split("|")][1:] if row else None



M4_FORBIDDEN_SCOPE = ("KPI", "salary review", "bonus", "ranking", "resource scoring")


def m4_gate(dec):
    """Open decisions whose Blocking column names M4 (current-scope reporting; not an R3 build gate)."""
    out = set()
    for c in rows(dec):
        if len(c) < 8 or "RESOLVED" in c[1] or c[1].lstrip("*").startswith("NOT_APPLICABLE"):
            continue
        for m in re.finditer(r"(?<!NON_)BLOCKING\*?\*?\s*([^|;(]*)", c[7]):
            if "M4" in re.findall(r"\b(M[1-4]|GL)\b", m.group(1)):
                out.add(re.match(r"OD-\d\d", c[0]).group(0))
    return out


def check_m4(d, dec, resolved):
    """M4 gate table = derived; M4 Vietnamese summary asks exactly the gate; the pack keeps KPI / salary / bonus / ranking out."""
    errs = []
    gate = m4_gate(dec)
    table = gate_table(dec).get("M4", set())
    if table != gate:
        errs.append("gate M4 table %s != derived %s" % (sorted(table), sorted(gate)))
    if os.path.exists(os.path.join(d, "M4-DECISION-SUMMARY.md")):
        summ = read(d, "M4-DECISION-SUMMARY.md")
        mm = re.search(r"(?ms)^## Bảng câu hỏi\n(.*?)(?=^## |\Z)", summ)
        asked = {re.match(r"\| (OD-\d\d)", l).group(1) for l in (mm.group(1) if mm else "").splitlines() if re.match(r"\| OD-\d\d \|", l)}
        if asked != gate:
            errs.append("M4-DECISION-SUMMARY question table %s != M4 gate %s" % (sorted(asked), sorted(gate)))
        for oid in sorted(resolved):
            if mm and re.search(r"(?m)^\| %s \|" % oid, mm.group(1)):
                errs.append("M4-DECISION-SUMMARY still asks closed decision %s" % oid)
    if os.path.exists(os.path.join(d, "M4-DECISION-PACK.md")):
        pack = read(d, "M4-DECISION-PACK.md")
        scope = re.search(r"(?ms)^## 2\. Derived M4 gate\n(.*?)(?=^## |\Z)", pack)
        for bad in M4_FORBIDDEN_SCOPE:
            if scope and re.search(bad, scope.group(1), re.I):
                errs.append("M4-DECISION-PACK gate reactivates out-of-scope %s" % bad)
        if "Not in M4" not in pack:
            errs.append("M4-DECISION-PACK does not state the excluded scope (KPI / salary / bonus / ranking)")
    errs += check_m4_resolved(d, dec, resolved)
    return errs


M4_RESOLVED = {"OD-50": "IN_APP_GUARDED_REPORTING", "OD-20": "EFFORT_ONLY_NO_LABOUR_COST", "OD-31": "APPROVER_AS_QUAN_LY_PHONG_FOR_M4_ONLY",
               "OD-13": "PLAN_WITH_NO_ACTUAL_VISIBLE_ACTUAL_ZERO", "OD-51": "APPROVEDLOCKED_ONLY", "OD-52": "M2_PROJECT_PLAN_M1_SEPARATE"}


def check_m4_resolved(d, dec, resolved):
    """Each resolved M4 decision is reflected in the reporting contract, the security matrix and the design."""
    errs = []
    con = read(d, "specs", "effort-reporting-contract", "spec.md")
    sec = read(d, "specs", "planning-security", "spec.md")
    design = read(d, "design.md")
    flat = re.sub(r"\s+", " ", con)
    for oid, key in M4_RESOLVED.items():
        if oid in resolved and key not in resolution(dec, oid):
            errs.append("%s resolution does not record %s" % (oid, key))
    if "OD-50" in resolved:
        for need in ("inside the existing Power Apps application", "return aggregates only", "SHALL NOT require a Power BI licence"):
            if need not in flat:
                errs.append("OD-50: reporting contract lacks '%s'" % need)
    if "OD-20" in resolved:
        if "no M4 report response or screen SHALL contain salary" not in flat:
            errs.append("OD-20: reporting contract does not forbid money in M4 responses")
        for cap in ("RPT.ProjectView", "RPT.DisciplineView"):
            row = [l for l in sec.splitlines() if l.startswith("| `%s`" % cap)]
            if row and re.search(r"(?i)cost|salary|rate\b", row[0]):
                errs.append("OD-20: %s grants cost / salary data" % cap)
    if "OD-31" in resolved:
        for cap in ("RPT.ProjectView", "RPT.DisciplineView"):
            r = _cap_row(sec, cap)
            if not r or r[2] != "company":
                errs.append("OD-31: Approver is not company on %s" % cap)
        for cap in ("EFF.ProjectView", "EFF.ProjectEdit", "EFF.DisciplineView", "EFF.DisciplineEdit", "EFF.DisciplineApprove"):
            r = _cap_row(sec, cap)
            if r and r[2] != "DENY":
                errs.append("OD-31: Approver gained %s (M4 mapping must not change M2 / M3)" % cap)
        if "no M2 / M3 / EPIC 07 / Timesheet right follows from it" not in sec:
            errs.append("OD-31: security spec does not limit the Approver mapping to M4 reporting")
    if "OD-13" in resolved:
        if "remains undecided" in con or "derived actual of 0" not in flat:
            errs.append("OD-13: plan-with-no-actual rule not applied in the reporting contract")
    if "OD-51" in resolved:
        if "count only ApprovedLocked EPIC 17 registrations as the plan" not in flat or "Draft registrations SHALL be excluded" not in flat:
            errs.append("OD-51: discipline plan is not ApprovedLocked-only in the reporting contract")
        if not re.search(r"Σ ApprovedLocked `DisciplineEffortRegistrations\.Effort` \(Draft excluded", design):
            errs.append("OD-51: design §11.1 discipline plan is not ApprovedLocked-only")
    if "OD-52" in resolved:
        if "EPIC 16 Project Effort total as the plan" not in flat or "never added to, netted with or substituted for the plan" not in flat:
            errs.append("OD-52: project plan / M1 separation not in the reporting contract")
        if "separate column, only for `REG.View` holders" not in design:
            errs.append("OD-52: design §11.1 does not keep M1 as a separate REG.View column")
    return errs


def check_m3(d, dec, resolved):
    errs = []
    disc = read(d, "specs", "discipline-effort", "spec.md")
    design = read(d, "design.md")
    sec_md = read(d, "specs", "planning-security", "spec.md")
    for oid, answer in M3_RESOLVED.items():
        if oid in resolved and answer not in resolution(dec, oid):
            errs.append("%s resolution does not record %s" % (oid, answer))
    if "OD-28" in resolved:  # self-approval allowed in EPIC 17 must not change EPIC 07
        if "EPIC 07 self-approval unchanged" not in disc or "EPIC 07 Timesheet self-approval stays denied" not in sec_md:
            errs.append("OD-28: EPIC 17 self-approval without the EPIC 07 self-approval denial being preserved in spec / security")
    if "OD-29" in resolved:  # WorkTypes, no new task entity
        drow = next((l for l in design.splitlines() if l.startswith("| `DisciplineEffortRegistrations`")), "")
        if re.search(r"\b(TaskItemId|TaskType|ProjectTasks?|TaskDefinitions?)\b", disc + drow) or "WorkType" not in drow:
            errs.append("OD-29: discipline effort must reference WorkTypes, not a task entity")
    if "OD-30" in resolved:  # no stored / editable discipline total
        drow = next((l for l in design.splitlines() if l.startswith("| `DisciplineEffortRegistrations`")), "")
        if re.search(r"`Discipline(Effort)?Total`|`Total`", drow + disc) or "no stored or editable discipline total" not in disc:
            errs.append("OD-30: a stored / editable discipline total is defined")
    if "OD-18" in resolved:  # no reopen
        cells = _cap_row(sec_md, "EFF.Unlock")
        if not cells or any(c != "NOT_APPLICABLE" for c in cells):
            errs.append("OD-18: EFF.Unlock must be NOT_APPLICABLE for every role")
        if re.search(r"Approved(Locked)?\s*(→|->)\s*Draft", disc.replace("no Approved → Draft", "")):
            errs.append("OD-18: discipline-effort defines an Approved -> Draft transition")
    if "OD-46" in resolved:  # own matrix, not inherited from M2
        view, pview = _cap_row(sec_md, "EFF.DisciplineView"), _cap_row(sec_md, "EFF.ProjectView")
        if not view or view == pview or view[0] != "self" or view[1] != "discipline" or "OPEN_DECISION" in view:
            errs.append("OD-46: EFF.DisciplineView must be its own matrix (EMP self, TL discipline), not inherited")
        if "EPIC 16 authoritative PM" not in sec_md:
            errs.append("OD-46: the PM view grant must use the EPIC 16 authoritative PM")
        for cap in ("EFF.DisciplineEdit", "EFF.DisciplineApprove"):
            c = _cap_row(sec_md, cap)
            if not c or "OPEN_DECISION" in c or any(x == "company" for x in c):
                errs.append("OD-46: %s must be decided and never company-wide" % cap)
    if "SHALL NOT store actual effort" not in disc:
        errs.append("EPIC 17 must not store actual effort (OD-19 / OD-33 / OD-49)")
    return errs


if __name__ == "__main__":
    e, info = check(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
    print(info)
    print("\n".join(e) if e else "CONSISTENT")
    sys.exit(1 if e else 0)
