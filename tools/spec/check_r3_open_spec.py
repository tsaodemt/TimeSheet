"""Consistency check for the R3 Open Spec (OpenSpec change `r3-planning-effort-hour-registration`). Spec-only: reads markdown,
changes nothing.

Checks: decision register parse (BLOCKING / conditional / NON_BLOCKING / RESOLVED_BY_EVIDENCE), milestone gate sets in the
register equal the sets derived from its Blocking column, tally numbers in register / proposal / design agree, every OD id
referenced anywhere in the change exists in the register, all 14 NR-EFF rows carry a decision dependency that refers only to
registered ids, and known stale wording is absent.

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
    """-> (blocking{id: set(gates)}, conditional{id: set}, nonblocking set, resolved set)"""
    blocking, conditional, nonblocking, resolved = {}, {}, set(), set()
    for c in rows(md):
        oid = re.match(r"OD-\d\d", c[0]).group(0)
        if "RESOLVED_BY_EVIDENCE" in c[1]:
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
    return blocking, conditional, nonblocking, resolved


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
    blocking, conditional, nonblocking, resolved = classify(dec)
    registered = set(blocking) | set(conditional) | nonblocking | resolved
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
                         (r"the (\d+) OPEN_DECISION items", "open"), (r"(\d+) RESOLVED_BY_EVIDENCE", "resolved")):
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
                    r"migration preserves both states", r"null excluded from counts, treated 0 in sums"):
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
    return errs, {"blocking": sorted(blocking), "conditional": sorted(conditional), "nonblocking": sorted(nonblocking),
                  "resolved": sorted(resolved), "gates": {g: sorted(v) for g, v in derived.items()}}


if __name__ == "__main__":
    e, info = check(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
    print(info)
    print("\n".join(e) if e else "CONSISTENT")
    sys.exit(1 if e else 0)
