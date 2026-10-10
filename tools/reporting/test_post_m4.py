"""Post-M4 clarification (2026-10-10): explicit M4 Employee rule, lifetime boundary, directional variance labels. Tests PM01-PM05."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "effort"), os.path.join(HERE, "..", "powerautomate"), os.path.join(HERE, "..", "identity"),
          os.path.join(HERE, "..", "powerapp"), os.path.join(HERE, "..", "alm"), os.path.join(HERE, "..", "approval")):
    sys.path.insert(0, p)
import build_demo_app as app  # noqa: E402
import guard as G  # noqa: E402
import rpt_rules as rr  # noqa: E402
import sharepoint_only_pack as pack  # noqa: E402
import test_discipline_effort as TDE  # noqa: E402
import test_effort_report as TER  # noqa: E402
import test_guard as tg  # noqa: E402
import test_project_effort as TPE  # noqa: E402
from identity_resolver import TrustedIdentity  # noqa: E402


def kids(screen):
    out = {}

    def walk(children):
        for x in children:
            for k, v in x.items():
                out[k] = v
                walk(v.get("Children", []))
    walk(app.screens()[screen]["Children"])
    return out


class M2Variance(TPE._Both):
    def test_PM01_m2_variance_is_actual_minus_plan_and_labelled(self):
        st = TPE.Store(allocs=((1, "QLP", 12), (1, "D:D-L1", 9.5)), entries=((1, 1, 8, "Approved"), (2, 1, 3, "Approved"), (3, 1, 4, "Draft")))
        f = self.read(("EMP", "PMO"), store=st)
        self.assertEqual((f["plannedTotal"], f["actualManDays"], f["variance"]), ("21.5", "1.375", "-20.125"))
        lbl = kids("scrProjectEffort")["lblEffVar"]["Properties"]["Text"]
        self.assertIn("Chênh lệch (thực hiện − kế hoạch)", lbl, "label names the direction: actual − plan")


class M4Variance(TER._Both):
    def test_PM02_m4_variance_is_plan_minus_actual_and_labelled(self):
        st = TER.Store(allocs=((1, "QLP", 12), (1, "D:D-L1", 9.5)), entries=((1, "D1", 8, "Approved"), (1, "D1", 3, "Approved"), (1, "D1", 4, "Draft")),
                       m1=(), regs=())
        f = self.project(("EMP", "PMO"), store=st)
        row = [r for r in f["rows"] if r["projectId"] == 1][0]
        self.assertEqual((row["planned"], row["actualManDays"], row["variance"]), ("21.5", "1.375", "20.125"))
        c = kids("scrEffortReport")
        for k in ("lblRptPHead", "lblRptDHead"):
            self.assertIn("Còn lại (Kế hoạch − Thực hiện)", c[k]["Properties"]["Text"], k)
            self.assertNotRegex(c[k]["Properties"]["Text"], r"Chênh lệch", "no generic label with the opposite meaning of M2")
        self.assertIn("còn lại (kế hoạch − thực hiện)", c["lblRptPTotal"]["Properties"]["Text"])


class EmployeeRule(TER._Both):
    def test_PM03_m4_aggregate_deny_does_not_imply_own_summary_deny(self):
        f = self.project(("EMP",), upn=tg.u("far2"))
        self.assertEqual(f["code"], "ROLE_NOT_ALLOWED", "M4 project aggregate denied")
        self.assertEqual(self.discipline(("EMP",), upn=tg.u("far2"))["code"], "ROLE_NOT_ALLOWED", "M4 discipline aggregate denied")
        m3 = TDE.Read("test_DE04_employee_own_rows_and_own_discipline_totals")
        own = m3.read(("EMP",), store=TDE.Store(**TDE.BASE))
        self.assertEqual((own["code"], own["scope"]), ("OK", "self"), "M3 own rows unchanged")
        self.assertEqual([s["disciplineCode"] for s in own["summary"]], ["D1"], "M3 own-discipline summary unchanged")
        pol = G.Policy.from_scope_config(pack.SCOPE_CONFIG)
        g = G.authorize(TrustedIdentity(upn=tg.u("peer"), group_ids=["g-emp"]), lambda n: [e for e in tg.EMPS if e.account_upn == n],
                        lambda n: [e for e in tg.EMPS if e.account_upn == n], tg.CFG, pol, "TS.ViewOwn", "self", correlation_id="x")
        self.assertEqual(g.ResultCode, "ALLOW", "own Timesheet unchanged")

    def test_PM04_m4_rule_is_report_only(self):
        self.assertEqual({c for c in rr.GRANTS}, {rr.PROJECT, rr.DISCIPLINE}, "only RPT.* capabilities are defined by the M4 matrix")
        self.assertNotIn("EMP", rr.GRANTS[rr.PROJECT])
        self.assertNotIn("EMP", rr.GRANTS[rr.DISCIPLINE])


class LifetimeBoundary(unittest.TestCase):
    def test_PM05_lifetime_label_and_parity_item_kept_separate(self):
        info = kids("scrEffortReport")["lblRptInfo"]["Properties"]["Text"]
        self.assertIn("toàn bộ vòng đời dự án", info)
        root = os.path.join(HERE, "..", "..", "openspec", "changes", "r3-planning-effort-hour-registration")
        with open(os.path.join(root, "decisions.md"), encoding="utf-8") as fh:
            dec = fh.read()
        with open(os.path.join(root, "design.md"), encoding="utf-8") as fh:
            design = fh.read()
        self.assertIn("PARITY-RPT-PERIOD-LIFETIME", dec)
        self.assertNotIn("no period filter is defined", design)
        self.assertIn("not derived from OD-46", dec)


if __name__ == "__main__":
    unittest.main()
