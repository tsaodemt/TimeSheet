"""Production root-site override (design) tests O01-O09 (offline). The normal root-site guard must stay unchanged."""
import dataclasses
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cutover_guard as cg  # noqa: E402
import schema_reconcile as sr  # noqa: E402

ROOT = "https://tenant-a.invalid"
PLAN = [("Units", "", ("create_list", {"title": "Units"})), ("Units", "UnitCode", ("create_field", {"internalName": "UnitCode"}))]
NOW = "2099-01-01T10:30:00Z"
APP = cg.CutoverApproval(cg.CUTOVER_MODE, ROOT, "release manager", "2099-01-01T09:00:00Z", "CHG-0001", cg.plan_hash(PLAN))


def ok_kwargs(**over):
    k = dict(drift_findings=[sr.Finding(sr.OK, "Units")], drift_checked_at="2099-01-01T10:00:00Z", drift_site_url=ROOT,
             dry_run_plan=PLAN, confirmation=cg.confirmation_text(ROOT, cg.plan_hash(PLAN)), now=NOW)
    k.update(over)
    return k


class Cutover(unittest.TestCase):
    def test_O01_all_conditions_met_returns_audit_evidence(self):
        ev = cg.validate_cutover(ROOT, APP, **ok_kwargs())
        self.assertEqual((ev["event"], ev["site"], ev["changeReference"], ev["operations"]), ("ProvisioningCutoverOverride", ROOT, "CHG-0001", 2))

    def test_O02_mode_and_exact_url(self):
        for app in (dataclasses.replace(APP, mode="NORMAL"), dataclasses.replace(APP, approved_url=ROOT + "/")):
            with self.assertRaises(cg.CutoverRefused):
                cg.validate_cutover(ROOT, app, **ok_kwargs())
        with self.assertRaises(cg.CutoverRefused):
            cg.validate_cutover("https://tenant-b.invalid", APP, **ok_kwargs(drift_site_url="https://tenant-b.invalid"))

    def test_O03_human_approval_required(self):
        for f in ("approver", "approved_at", "change_reference"):
            with self.assertRaises(cg.CutoverRefused, msg=f):
                cg.validate_cutover(ROOT, dataclasses.replace(APP, **{f: ""}), **ok_kwargs())

    def test_O04_fresh_drift_check_on_the_target(self):
        for kw in ({"drift_checked_at": "2099-01-01T08:00:00Z"}, {"drift_checked_at": "2099-01-01T11:00:00Z"},
                   {"drift_checked_at": "yesterday"}, {"drift_site_url": ROOT + "/sites/other"},
                   {"drift_findings": [sr.Finding(sr.BLOCKED, "Units", "UnitCode")]}):
            with self.assertRaises(cg.CutoverRefused, msg=kw):
                cg.validate_cutover(ROOT, APP, **ok_kwargs(**kw))

    def test_O05_dry_run_must_equal_the_approved_plan(self):
        more = PLAN + [("Units", "Extra", ("create_field", {"internalName": "Extra"}))]
        with self.assertRaises(cg.CutoverRefused):
            cg.validate_cutover(ROOT, APP, **ok_kwargs(dry_run_plan=more, confirmation=cg.confirmation_text(ROOT, cg.plan_hash(more))))

    def test_O06_explicit_confirmation(self):
        for c in ("", "yes", cg.confirmation_text(ROOT + "/", APP.approved_plan_hash)):
            with self.assertRaises(cg.CutoverRefused):
                cg.validate_cutover(ROOT, APP, **ok_kwargs(confirmation=c))

    def test_O07_all_failures_are_reported_together(self):
        with self.assertRaises(cg.CutoverRefused) as e:
            cg.validate_cutover(ROOT, dataclasses.replace(APP, mode="X", approver=""), **ok_kwargs(confirmation=""))
        self.assertEqual(str(e.exception).count(";"), 2)

    def test_O08_normal_guard_still_refuses_root_even_with_an_approval(self):
        with self.assertRaises(sr.SiteGuardError):
            sr.guard_site(ROOT, ROOT)
        self.assertNotIn("cutover", inspect.signature(sr.apply).parameters)
        self.assertNotIn("cutover_guard", open(sr.__file__, encoding="utf-8").read(), "override is not wired into apply")

    def test_O09_plan_hash_is_stable_and_order_sensitive(self):
        self.assertEqual(cg.plan_hash(PLAN), cg.plan_hash(list(PLAN)))
        self.assertNotEqual(cg.plan_hash(PLAN), cg.plan_hash(PLAN[::-1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
