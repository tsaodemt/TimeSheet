"""R1 flow-set manifest and readiness tests RA01-RA14 (offline; synthetic configuration; no tenant data).
Set TS_SOLUTION_MANIFEST (+ TS_R1_STATE, TS_R1_REGISTRY, TS_R1_OVERLAY) to print the real local readiness."""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d3_acceptance as d3  # noqa: E402
import manifest_check as mc  # noqa: E402
import r1_flows as rf  # noqa: E402
import r1_readiness as rr  # noqa: E402

REG = rf.GENERIC_REGISTRY
INTERIM = {"value": "Off", "interim": True, "basis": "engineering", "approvedBy": "owner", "approvedOn": "2099-01-01",
           "customerDecision": "B-03 OPEN", "allowedEnvironments": ["STAGING"]}
SVC = "svc-operational@tenant-a.invalid"
OVL_NOW = {"environment": "STAGING", "values": {"ProjectAssignmentScoping": INTERIM}, "external": {}}
OVL_D3 = dict(OVL_NOW, external={"ServiceAccountUpn": SVC})
SAMPLE = rf.sample_manifest()
LISTS_ALL = ("Employees", "AppSettings", "TimesheetEntries", "AuditLog", "Projects", "ProjectPhases", "Phases", "WorkTypes",
             "Shifts", "HourTypes", "ProjectAssignments")
# Current STAGING shape (generic): Employees/AppSettings populated, S04.3 lists schema only, R1 lists not created yet.
STATE_NOW = {"Employees": {"exists": True, "canonicalRows": 100}, "AppSettings": {"exists": True, "canonicalRows": 15},
             **{t: {"exists": True, "canonicalRows": 0} for t in ("Phases", "WorkTypes", "Shifts", "HourTypes")}}
STATE_OK = {t: {"exists": True, "canonicalRows": 5, "live": True} for t in LISTS_ALL}
ACCEPTED = {"criteria": {c: {"met": True, "evidence": "read-only check (synthetic)"} for c in d3.IDS}}


def resolved_manifest(owner=SVC):
    m = copy.deepcopy(SAMPLE)
    m["solution"]["publisher"]["customizationPrefix"] = "ts"
    m["environmentDecisions"] = {k: "decided" for k in rr.ENV_DECISIONS}
    js = json.dumps(m).replace("<PFX>", "ts")
    m = json.loads(js)
    for v in m["environmentVariables"]:
        v["values"]["staging"] = "value"
    for r in m["connectionReferences"]:
        if r["ownership"] == "SERVICE":
            r.update(gated=False, connectionOwner=owner)
    return m


def perms(upn=SVC, write_role=rr.WRITE_LEVEL):
    out = {}
    for t in LISTS_ALL:
        role = write_role if t in ("TimesheetEntries", "AuditLog") else "Read"
        out[t] = {"unique": True, "assignments": [{"login": "c:0-.f|owners", "roles": ["Full Control"]},
                                                  {"login": "i:0#.f|membership|" + upn, "roles": [role]}]}
    return out


def check(purpose="ENGINEERING", flows=rr.R1_FLOWS, manifest=None, overlay=OVL_D3, state=None, permissions=None, **kw):
    return rr.readiness(purpose, flows, manifest=manifest or resolved_manifest(), overlay=overlay, registry=REG,
                        list_state=STATE_OK if state is None else state, permissions=perms() if permissions is None else permissions,
                        **dict({"identity_acceptance": ACCEPTED, "temporary_accounts": ("temp-test-svc",)}, **kw))


class R1Alm(unittest.TestCase):
    def test_RA01_manifest_includes_the_r1_flow_set_and_lints(self):
        self.assertEqual([(f["name"], f["alias"]) for f in SAMPLE["flows"]],
                         [("TS-AppOpen", "AppStart"), ("TS-ReadOwn", "ReadOwn"), ("TS-SaveEntry", "SaveEntry")])
        for f in SAMPLE["flows"]:
            path = os.path.join(HERE, "..", "..", f["template"].split(":")[0])
            self.assertTrue(os.path.exists(path), f["template"])
            self.assertFalse(f["deployed"])
        self.assertEqual(mc.lint(SAMPLE), [])
        bad = copy.deepcopy(SAMPLE)
        bad["connectionReferences"] = [r for r in bad["connectionReferences"] if "Groups" not in r["schemaName"]]
        self.assertTrue(any("not declared" in p for p in mc.lint(bad)))

    def test_RA02_dependencies_are_read_from_the_templates(self):
        f = {x["name"]: x for x in SAMPLE["flows"]}
        refs = lambda n: {r["schemaName"]: r["ownership"] for r in f[n]["connectionReferences"]}  # noqa: E731
        self.assertEqual(refs("TS-AppOpen"), {"<PFX>_CR_O365Users_Invoker": "INVOKER", "<PFX>_CR_SharePoint_OpsService": "SERVICE"})
        for n in ("TS-ReadOwn", "TS-SaveEntry"):
            self.assertEqual(refs(n)["<PFX>_CR_O365Groups_OpsService"], "SERVICE")
        self.assertEqual(f["TS-AppOpen"]["lists"], {"AppSettings": ["read"], "AuditLog": ["write"], "Employees": ["read"]})
        self.assertEqual(f["TS-ReadOwn"]["lists"]["TimesheetEntries"], ["read"])
        self.assertEqual(f["TS-ReadOwn"]["settings"]["keys"], ["BusinessTimezone"])
        self.assertEqual(f["TS-ReadOwn"]["referenceData"], [])
        self.assertEqual(f["TS-SaveEntry"]["lists"]["TimesheetEntries"], ["read", "write"])
        self.assertEqual({x["list"]: x["required"] for x in f["TS-SaveEntry"]["referenceData"]},
                         {**{t: "always" for t in ("Projects", "ProjectPhases", "Phases", "WorkTypes", "Shifts", "HourTypes")},
                          "ProjectAssignments": "when ProjectAssignmentScoping = On"})
        self.assertEqual(f["TS-SaveEntry"]["guard"], {"capability": "TS.EditOwnDraft", "scope": "self"})
        self.assertEqual(f["TS-ReadOwn"]["guard"], {"capability": "TS.ViewOwn", "scope": "self"})
        self.assertIsNone(f["TS-AppOpen"]["guard"])
        self.assertEqual(f["TS-SaveEntry"]["audit"]["events"], ["AuthorizationAllow", "AuthorizationDeny", "WriteProxy"])
        self.assertNotIn("ConfidentialAuditLog", json.dumps(SAMPLE["flows"]), "no dependency that the flows do not use")
        self.assertNotIn("<PFX>_RoleGroupMap", f["TS-AppOpen"]["environmentVariables"])
        self.assertNotIn("BusinessUtcOffsetMinutes", json.dumps(SAMPLE["flows"]), "no fixed UTC offset")

    def test_RA03_connection_reference_classification(self):
        self.assertEqual(rr.classify({"ownership": "invoker"}), "INVOKER")
        self.assertEqual(rr.classify({"invokerOwned": True}), "INVOKER")
        self.assertEqual(rr.classify({"ownership": "SERVICE"}), "SERVICE")
        self.assertEqual(rr.classify({}), "UNKNOWN")
        r = check()
        self.assertEqual(r.blockers, [])  # invoker reference with a "<run-only user>" owner is not a blocker
        m = resolved_manifest()
        next(x for x in m["connectionReferences"] if "Groups" in x["schemaName"]).update(gated=True, gatedBy="D-3")
        self.assertEqual(check(manifest=m).categories(), ["CONNECTION_REFERENCE_UNBOUND"])
        self.assertEqual({fl for c, fl, _ in check(manifest=m).blockers}, {"TS-ReadOwn", "TS-SaveEntry"}, "AppStart uses no Groups")
        m = resolved_manifest(owner="someone-else@tenant-a.invalid")
        self.assertIn("CONNECTION_REFERENCE_UNBOUND", check(manifest=m).categories())
        m = resolved_manifest()
        next(x for x in m["connectionReferences"] if "Invoker" in x["schemaName"]).pop("ownership")
        next(x for x in m["connectionReferences"] if "Invoker" in x["schemaName"]).pop("invokerOwned")
        self.assertIn("CONNECTION_REFERENCE_UNBOUND", check(manifest=m).categories())

    def test_RA04_service_identity_missing_or_temporary(self):
        r = check(overlay=OVL_NOW)
        self.assertIn("D3_SERVICE_IDENTITY_MISSING", r.categories())
        self.assertIn("CONNECTION_REFERENCE_UNBOUND", r.categories())
        self.assertNotIn("PERMISSION_NOT_VERIFIED", r.categories(), "permissions are checked once an identity exists")
        r = check(overlay=dict(OVL_NOW, external={"ServiceAccountUpn": "temp-test-svc@tenant-a.invalid"}))
        self.assertIn("D3_SERVICE_IDENTITY_MISSING", r.categories())
        self.assertNotIn("INVOKER", " ".join(d for c, _, d in r.blockers if c == "CONNECTION_REFERENCE_UNBOUND"))

    def test_RA05_prefix_and_environment_unresolved(self):
        r = check(manifest=SAMPLE)
        self.assertIn("PUBLISHER_PREFIX_UNRESOLVED", r.categories())
        self.assertIn("ENVIRONMENT_UNRESOLVED", r.categories())
        self.assertEqual({d for c, _, d in r.blockers if c == "ENVIRONMENT_UNRESOLVED" and "ENV-D3" in d},
                         {"ENV-D3 %s not decided" % k for k in rr.ENV_DECISIONS})
        m = resolved_manifest()
        m["environmentVariables"][0]["values"]["staging"] = "<TBD>"
        self.assertEqual(check(manifest=m).categories(), ["ENVIRONMENT_UNRESOLVED"])

    def test_RA06_reference_data_existing_is_not_ready(self):
        st = dict(STATE_OK, Phases={"exists": True, "canonicalRows": 0}, Projects={"exists": False})
        r = check(state=st)
        self.assertEqual(r.categories(), ["REFERENCE_DATA_MISSING"])
        self.assertEqual(sorted(d for _, _, d in r.blockers),
                         ["Phases: no canonical business rows (schema only)", "Projects: list does not exist"])
        self.assertTrue(check(flows=["TS-AppOpen", "TS-ReadOwn"], state=st).ready, "only SaveEntry uses reference data")
        st = dict(STATE_OK, ProjectAssignments={"exists": False})
        self.assertTrue(check(state=st).ready, "assignments are not read while scoping is Off")
        on = dict(OVL_D3, values={"ProjectAssignmentScoping": "On"})
        self.assertIn("REFERENCE_DATA_MISSING", check(state=st, overlay=on).categories())

    def test_RA07_audit_dependency(self):
        r = check(state=dict(STATE_OK, AuditLog={"exists": False}))
        self.assertEqual(r.categories(), ["AUDIT_DEPENDENCY_UNAVAILABLE"])
        self.assertEqual({fl for _, fl, _ in r.blockers}, set(rr.R1_FLOWS))

    def test_RA08_interim_b03_engineering_only(self):
        self.assertTrue(check("ENGINEERING").ready)
        u = check("UAT")
        self.assertIn("INTERIM_CONFIG_NOT_UAT_READY", u.categories())
        p = check("PRODUCTION")
        self.assertIn("INTERIM_CONFIG_NOT_PRODUCTION_READY", p.categories())
        self.assertNotIn("INTERIM_CONFIG_NOT_UAT_READY", p.categories())
        u2 = check("UAT", overlay=dict(OVL_D3, environment="UAT"))
        self.assertIn("INTERIM_CONFIG_NOT_UAT_READY", u2.categories(), "interim value refused outside its environment")

    def test_RA09_resolved_engineering_is_ready_with_notices(self):
        r = check()
        self.assertEqual((r.ready, r.blockers), (True, []))
        self.assertIn(("CREATE_IDEMPOTENCY_INTERIM", "TS-SaveEntry", "R1-Q3 OPEN; exactly-once not guaranteed"), r.notices)
        self.assertIn(("FIRST_LIVE_CHECK_PENDING", "TS-SaveEntry", "V-ETAG"), r.notices)
        self.assertIn(("FIRST_LIVE_CHECK_PENDING", "TS-ReadOwn", "V-LAZY"), r.notices)

    def test_RA10_exact_service_permissions(self):
        p = perms()
        p["TimesheetEntries"]["assignments"][1]["roles"] = ["Read"]
        self.assertEqual(check(permissions=p).categories(), ["WRITE_PERMISSION_MISSING"])
        p = perms()
        p["Employees"]["assignments"][1]["roles"] = ["Read", "Edit"]
        self.assertEqual(check(permissions=p).categories(), ["SECURITY_DRIFT"])
        p = perms()
        p["TimesheetEntries"]["assignments"][1]["roles"] = ["TS Service", "Full Control"]
        self.assertEqual(check(permissions=p).categories(), ["SECURITY_DRIFT"])
        p = perms()
        del p["Shifts"]
        self.assertEqual(check(permissions=p).categories(), ["PERMISSION_NOT_VERIFIED"])
        self.assertEqual(check(flows=["TS-AppOpen"], permissions={k: v for k, v in perms().items() if k in ("Employees", "AppSettings", "AuditLog")}).blockers, [])

    def test_RA11_current_staging_shape(self):
        r = check(manifest=SAMPLE, overlay=OVL_NOW, state=STATE_NOW, permissions={})
        cats = {fl: sorted({c for c, f, _ in r.blockers if f == fl}) for fl in rr.R1_FLOWS}
        self.assertEqual(cats["TS-AppOpen"], ["AUDIT_DEPENDENCY_UNAVAILABLE", "CONNECTION_REFERENCE_UNBOUND"])
        self.assertEqual(cats["TS-ReadOwn"], ["AUDIT_DEPENDENCY_UNAVAILABLE", "CONNECTION_REFERENCE_UNBOUND", "TARGET_LIST_MISSING"])
        self.assertEqual(cats["TS-SaveEntry"], ["AUDIT_DEPENDENCY_UNAVAILABLE", "CONNECTION_REFERENCE_UNBOUND", "REFERENCE_DATA_MISSING",
                                                "TARGET_LIST_MISSING"])
        glob = sorted({c for c, f, _ in r.blockers if f == "*"})
        self.assertEqual(glob, ["D3_SERVICE_IDENTITY_MISSING", "ENVIRONMENT_UNRESOLVED", "PUBLISHER_PREFIX_UNRESOLVED"])
        self.assertEqual(sorted(d.split(":")[0] for c, f, d in r.blockers if c == "REFERENCE_DATA_MISSING"),
                         ["HourTypes", "Phases", "ProjectPhases", "Projects", "Shifts", "WorkTypes"])
        u = check("UAT", manifest=SAMPLE, overlay=OVL_NOW, state=STATE_NOW, permissions={})
        self.assertIn("INTERIM_CONFIG_NOT_UAT_READY", u.categories())
        self.assertFalse(r.ready or u.ready)

    def test_RA15_phase1_lists_remove_only_their_own_blockers(self):
        now = check(manifest=SAMPLE, overlay=OVL_NOW, state=STATE_NOW, permissions={}).categories()
        audit = dict(STATE_NOW, AuditLog={"exists": True, "canonicalRows": 0, "live": True})
        after = check(manifest=SAMPLE, overlay=OVL_NOW, state=audit, permissions={}).categories()
        self.assertEqual(sorted(set(now) - set(after)), ["AUDIT_DEPENDENCY_UNAVAILABLE"])
        both = dict(audit, TimesheetEntries={"exists": True, "canonicalRows": 0})
        after2 = check(manifest=SAMPLE, overlay=OVL_NOW, state=both, permissions={}).categories()
        self.assertEqual(sorted(set(now) - set(after2)), ["AUDIT_DEPENDENCY_UNAVAILABLE", "TARGET_LIST_MISSING"])
        for c in ("D3_SERVICE_IDENTITY_MISSING", "CONNECTION_REFERENCE_UNBOUND", "PUBLISHER_PREFIX_UNRESOLVED", "ENVIRONMENT_UNRESOLVED",
                  "REFERENCE_DATA_MISSING"):
            self.assertIn(c, after2, "a list existing never removes D-3 / ENV-D3 / reference-data blockers")

    def test_RA12_unknown_purpose_or_flow(self):
        with self.assertRaises(ValueError):
            check("GO-LIVE")
        self.assertIn("CONNECTION_REFERENCE_UNBOUND", check(flows=("TS-Unknown",)).categories())

    def test_RA13_no_hard_coded_account_or_tenant(self):
        for name in ("r1_readiness.py", "r1_flows.py"):
            src = open(os.path.join(HERE, name), encoding="utf-8").read()
            self.assertEqual(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[a-z]{2,}", src), [], name)
            self.assertNotIn("spike", src.lower(), name)

    @unittest.skipUnless(os.environ.get("TS_SOLUTION_MANIFEST") and os.environ.get("TS_R1_STATE"), "set TS_SOLUTION_MANIFEST and TS_R1_STATE")
    def test_RA14_real_local_readiness(self):
        load = lambda k: json.load(open(os.environ[k], encoding="utf-8"))  # noqa: E731
        m, st = load("TS_SOLUTION_MANIFEST"), load("TS_R1_STATE")
        reg = load("TS_R1_REGISTRY") if os.environ.get("TS_R1_REGISTRY") else REG
        ovl = load("TS_R1_OVERLAY") if os.environ.get("TS_R1_OVERLAY") else OVL_NOW
        acc = load("TS_D3_ACCEPTANCE") if os.environ.get("TS_D3_ACCEPTANCE") else None
        self.assertEqual(mc.lint(m), [])
        for purpose in rr.cfg.PURPOSES:
            r = rr.readiness(purpose, manifest=m, overlay=ovl, registry=reg, list_state=st, permissions={}, identity_acceptance=acc)
            self.assertFalse(r.ready, purpose)
            print("\n%s: %s" % (purpose, ", ".join(r.categories())))
            for c, f, d in r.blockers:
                print("  %-36s %-13s %s" % (c, f, d))

    def test_RA16_promoted_identity_clears_only_the_identity_blocker(self):
        """An existing (formerly temporary) account selected as the operational identity: once it is configured and no
        longer listed as temporary, D3_SERVICE_IDENTITY_MISSING disappears; every other open category stays."""
        promoted = "former-spike-svc@tenant-a.invalid"
        ovl = dict(OVL_NOW, external={"ServiceAccountUpn": promoted})
        before = check(overlay=ovl, manifest=SAMPLE, state=STATE_NOW, permissions={}, temporary_accounts=("temp-test-svc", promoted))
        after = check(overlay=ovl, manifest=SAMPLE, state=STATE_NOW, permissions={}, temporary_accounts=("temp-test-svc",))
        self.assertIn("D3_SERVICE_IDENTITY_MISSING", before.categories())
        self.assertNotIn("D3_SERVICE_IDENTITY_MISSING", after.categories())
        self.assertNotIn("D3_OPERATIONAL_READINESS_INCOMPLETE", after.categories())
        for c in ("CONNECTION_REFERENCE_UNBOUND", "ENVIRONMENT_UNRESOLVED", "PUBLISHER_PREFIX_UNRESOLVED", "REFERENCE_DATA_MISSING",
                  "TARGET_LIST_MISSING"):
            self.assertIn(c, after.categories(), c)
        self.assertFalse(any("new service account" in d.lower() for _, _, d in after.blockers))

    def test_RA17_unmet_acceptance_criterion_is_named_exactly(self):
        acc = {"criteria": dict(ACCEPTED["criteria"], CUSTODIAN_LIFECYCLE_DOCUMENTED={"met": False, "evidence": "custodian not named"})}
        r = check(identity_acceptance=acc)
        self.assertEqual([(c, d) for c, _, d in r.blockers if c.startswith("D3_")],
                         [("D3_OPERATIONAL_READINESS_INCOMPLETE", "CUSTODIAN_LIFECYCLE_DOCUMENTED: " + dict(d3.CRITERIA)["CUSTODIAN_LIFECYCLE_DOCUMENTED"])])
        self.assertTrue(check().ready, "all criteria met + everything else resolved -> ready")


if __name__ == "__main__":
    unittest.main(verbosity=2)
