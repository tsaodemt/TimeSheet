"""Lazy-evaluation independence tests LZ01-LZ05 (offline).

LZ01 simulator branch modes; LZ02 no generated R1/guard/maintenance expression depends on lazy evaluation (audit mode);
LZ03 every flow parity suite passes with eager evaluation; LZ04/LZ05 the first-live probe (build_lazy_probe_flow.py)
gives the expected NEW results under both semantics and shows what the OLD forms would do.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_lazy_probe_flow as probe  # noqa: E402
import lazy_if_audit  # noqa: E402
import wdl_sim  # noqa: E402


def run_probe(mode):
    return wdl_sim.Run(branches=mode).run(probe.probe_actions()).results["Respond"]["outputs"]


class LazyIf(unittest.TestCase):
    def test_LZ01_branch_modes(self):
        expr = wdl_sim.parse("if(equals(1, 1), 'ok', int('x'))")
        self.assertEqual(wdl_sim.Run(branches="lazy").ev(expr), "ok")
        with self.assertRaises(Exception):
            wdl_sim.Run(branches="eager").ev(expr)
        del wdl_sim.LAZY_HITS[:]
        self.assertEqual(wdl_sim.Run(branches="audit").ev(expr), "ok")
        self.assertEqual([h["unused"] for h in wdl_sim.LAZY_HITS], ["int('x')"])
        self.assertTrue(wdl_sim.Run(branches="lazy").ev(wdl_sim.parse("or(true, int('x'))")))
        with self.assertRaises(Exception):
            wdl_sim.Run(branches="eager").ev(wdl_sim.parse("and(false, int('x'))"))
        del wdl_sim.LAZY_HITS[:]

    def test_LZ02_no_lazy_dependent_expression(self):
        res, hits = lazy_if_audit.run(mode="audit")
        self.assertTrue(res.wasSuccessful(), res.failures + res.errors)
        self.assertGreater(res.testsRun, 80)
        self.assertEqual(hits, [], "expressions that depend on lazy evaluation")

    def test_LZ03_parity_suites_pass_with_eager_evaluation(self):
        res, _ = lazy_if_audit.run(mode="eager")
        self.assertTrue(res.wasSuccessful(), [str(t) for t, _ in res.failures + res.errors][:5])

    def test_LZ04_probe_new_forms_hold_under_both_semantics(self):
        for mode in ("lazy", "eager"):
            out = run_probe(mode)
            for name, _, _, _, expected, _ in probe.CASES:
                status, value = out["NEW_" + name].split("|", 1)
                self.assertEqual(status, "Succeeded", (mode, name))
                self.assertEqual(value, wdl_sim._str(expected) if not isinstance(expected, str) else expected, (mode, name))
            self.assertEqual(out["DATE_CHECK"], "Failed", "V-FAILONERROR: invalid date fails its compose, the flow continues")

    def test_LZ05_probe_old_forms_reveal_the_runtime(self):
        lazy, eager = run_probe("lazy"), run_probe("eager")
        for name, *_ in probe.CASES:
            self.assertTrue(lazy["OLD_" + name].startswith("Succeeded"), name)
            self.assertTrue(eager["OLD_" + name].startswith("Failed"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
