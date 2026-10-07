"""POC P3 / P5 procedure checks PP01-PP06 (offline; nothing executed)."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import poc_procedures as pp  # noqa: E402
import test_r1_read_flow as rf  # noqa: E402


class PocProcedures(unittest.TestCase):
    def test_PP01_both_procedures_valid_and_not_executed(self):
        for spec in (pp.P3, pp.P5):
            self.assertEqual(pp.validate(spec), [], spec["id"])
            self.assertEqual((spec["status"], spec["executed"]), ("PROCEDURE READY / NOT EXECUTED", False))
        for doc in ("poc-p3-save-latency.md", "poc-p5-choice-filtering.md"):
            text = open(os.path.join(HERE, "..", "..", "docs", doc), encoding="utf-8").read()
            self.assertIn("NOT EXECUTED", text)
            self.assertNotIn("PASS", text.replace("PASS/FAIL", ""), doc)

    def test_PP02_validator_refuses_unsafe_or_incomplete_procedures(self):
        cases = [("environment", "MAIN"), ("mainAllowed", True), ("status", "PASS"), ("executed", True), ("noRealData", False),
                 ("approvalRequired", False), ("syntheticTag", "")]
        for k, v in cases:
            s = copy.deepcopy(pp.P3)
            s[k] = v
            self.assertTrue(pp.validate(s), k)
        s = copy.deepcopy(pp.P3)
        s["identity"]["serviceSubstitution"] = True
        self.assertTrue(pp.validate(s))
        s = copy.deepcopy(pp.P3)
        s["cleanup"] = {}
        self.assertTrue(pp.validate(s), "writes without cleanup")

    def test_PP03_no_invented_sla(self):
        self.assertEqual((pp.P3["acceptance"]["threshold"], pp.P3["acceptance"]["thresholdSource"]), ("<= 5 s", "NFR-PERF-03"))
        s = copy.deepcopy(pp.P3)
        s["acceptance"]["thresholdSource"] = ""
        self.assertTrue(pp.validate(s), "threshold without source")
        s["acceptance"]["threshold"] = "DECISION REQUIRED"
        self.assertEqual(pp.validate(s), [], "no approved SLA -> distribution only, threshold DECISION REQUIRED")

    def test_PP04_p3_shape_and_bounded_workload(self):
        self.assertEqual({x["kind"] for x in pp.P3["scenarios"]} >= pp.P3_REQUIRED_KINDS, True)
        self.assertLessEqual(sum(x["repetitions"] for x in pp.P3["scenarios"]), 100)
        s = copy.deepcopy(pp.P3)
        s["scenarios"][0]["repetitions"] = 1000
        self.assertTrue(pp.validate(s), "statistically excessive workload")
        s = copy.deepcopy(pp.P3)
        s["scenarios"] = [x for x in s["scenarios"] if x["kind"] != "conflict"]
        self.assertTrue(pp.validate(s))
        self.assertTrue(any("D-3" in b for b in pp.P3["blockedBy"]))

    def test_PP05_p5_covers_required_checks_and_reuses_dataset(self):
        self.assertEqual({x["verifies"] for x in pp.P5["checks"]} >= pp.P5_REQUIRED, True)
        self.assertIn("> 5,000", pp.P5["dataset"]["reuse"])
        s = copy.deepcopy(pp.P5)
        s["newRows"]["count"] = 3000
        self.assertTrue(pp.validate(s), "no thousands of new rows")
        s = copy.deepcopy(pp.P5)
        s["checks"] = s["checks"][1:]
        self.assertTrue(pp.validate(s))

    def test_PP06_p5_filter_is_the_generated_one(self):
        """P5-05/P5-08 compare SharePoint with the exact filter TS-ReadOwn emits; this is that filter's shape."""
        _, _, run = rf.run_flow(rf.ME, {"FromDate": "2026-10-03", "ToDate": "2026-10-05"})
        flt = run.results["Filter"]["outputs"]
        self.assertEqual(flt, "OwnerUpn eq '%s' and WorkDate ge datetime'2026-10-02T17:00:00Z' and WorkDate lt "
                              "datetime'2026-10-05T17:00:00Z' and EntryStatus ne 'Deleted' and Id gt 0" % rf.ME)
        self.assertTrue(flt.startswith("OwnerUpn eq "), "indexed owner first: status never the first filter")


if __name__ == "__main__":
    unittest.main(verbosity=2)
