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
    return errs, {"blocking": sorted(blocking), "conditional": sorted(conditional), "nonblocking": sorted(nonblocking),
                  "resolved": sorted(resolved), "not_applicable": sorted(not_applicable),
                  "gates": {g: sorted(v) for g, v in derived.items()}, "m2_state": m2_state}


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
    # EPIC 17 unit: own open decision, no hidden dependency on OD-14.
    if EPIC17_UNIT not in blocking or "M3" not in blocking.get(EPIC17_UNIT, ()):
        errs.append("%s (EPIC 17 unit) must stay an open M3 blocker until decided" % EPIC17_UNIT)
    disc = read(d, "specs", "discipline-effort", "spec.md")
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
    asked = {re.match(r"\| (OD-\d\d)", l).group(1) for l in summ.splitlines() if re.match(r"\| OD-\d\d \|", l)}
    if asked != set(m2_gate):
        errs.append("M2-DECISION-SUMMARY table %s != M2 gate %s" % (sorted(asked), sorted(m2_gate)))
    for oid in sorted((resolved | not_applicable) & set(M2_DECISIONS)):
        if oid in summ:
            errs.append("M2-DECISION-SUMMARY still mentions closed decision %s" % oid)
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


if __name__ == "__main__":
    e, info = check(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
    print(info)
    print("\n".join(e) if e else "CONSISTENT")
    sys.exit(1 if e else 0)
