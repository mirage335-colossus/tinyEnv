import copy
import importlib.util
from pathlib import Path
import tempfile
import json
import platform
import unittest

spec = importlib.util.spec_from_file_location("certify", Path(__file__).resolve().parents[1] / "tools/certify_release.py")
certify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certify)
c = certify.coverage


class CertificationTests(unittest.TestCase):
    def fixture(self, root):
        machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
        target = platform.system().lower() + "-" + machine
        manifest = {"source": {"sha256": "a" * 64}, "artifacts": [
            {"target": target, "backends": ["core"]}], "required_scopes": ["source", "archive", "recovery"]}
        c.write_new(root / "release.json", manifest)
        rows = [{"target": target, "backend": "core", "environment": "fixture", "scope": scope}
                for scope in ("source", "archive", "recovery")]
        policy = {"schema_version": 1, "profiles": {"fixture": {"description": "unit fixture",
                  "targets": {target: ["core"]}, "checks": rows}}}
        runner = root / "fixture.py"
        runner.write_text("""import json,sys,hashlib
from pathlib import Path
out, data = Path(sys.argv[1]), json.loads(sys.argv[2])
if data['scope'] in ('source', 'recovery'):
    junit = out / 'source.junit.xml'
    junit.write_text('<testsuite><testcase name="fixture"/></testsuite>')
    data['evidence'] = {'source.junit.xml': hashlib.sha256(junit.read_bytes()).hexdigest()}
    data['details'] = {'executed_tests': ['fixture']}
(out / 'qualification.json').write_text(json.dumps(data))
""")
        def command(row):
            receipt = dict(schema_version=1, source_sha256="a" * 64,
                           inventory_sha256=c.sha(root / "release.json"), host=c.host_identity(),
                           status="passed", details={}, assertions=["unit-fixture"], evidence={},
                           **{k: row[k] for k in ("target", "backend", "scope")})
            return ["{python}", "{root}/fixture.py", "{evidence}", json.dumps(receipt)]
        plan = c.freeze({"schema_version": 1, "mode": "release", "subject": {
            "source_sha256": "a" * 64, "inventory_sha256": c.sha(root / "release.json"),
            "configuration_sha256": c.digest({"policy": policy, "profile": "fixture"})}, "inputs": {"fixture.py": c.sha(runner)},
            "checks": [dict(row, id=row["scope"], required=True, argv=command(row), qualification="qualification.json",
                            timeout_seconds=5, warning_seconds=4, expected_tests=[]) for row in rows]})
        reports = []
        for row in rows:
            out = root / row["scope"]
            c.run_case(plan, row["scope"], root, out, "run", 1)
            reports.append(out / "result.json")
        return manifest, plan, reports, policy

    def test_complete_exact_evidence_and_experiment_consequence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, plan, reports, policy = self.fixture(root)
            result = certify.certify(root, manifest, plan, reports, policy, "fixture")
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["eligible_for_promotion"])
            self.assertFalse(certify.certify(root, manifest, plan, reports, policy, "fixture", True)["eligible_for_promotion"])


    def test_retry_certifies_exact_original_evidence_only_with_explicit_adoption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, plan, reports, policy = self.fixture(root)
            prior_bytes = {path: path.read_bytes() for path in reports}
            current = root / 'retry-source'
            c.run_case(plan, 'source', root, current, 'run', 2)
            selected = c.adopt(plan, reports[1:], root, 'run', 2)
            mixed = [current/'result.json', *reports[1:]]
            with self.assertRaisesRegex(ValueError, 'mixed runs/attempts'):
                certify.certify(root, manifest, plan, mixed, policy, 'fixture')
            result = certify.certify(root, manifest, plan, mixed, policy, 'fixture', adoption=selected)
            self.assertEqual(result['status'], 'passed')
            self.assertTrue(result['eligible_for_promotion'])
            self.assertEqual(result['adoption'], selected)
            self.assertEqual(result['coverage']['source']['attempt'], 2)
            self.assertEqual(result['coverage']['archive']['attempt'], 1)
            self.assertEqual({path: path.read_bytes() for path in reports}, prior_bytes)
            (reports[1].parent/'qualification.json').write_text('{}')
            with self.assertRaises(ValueError):
                certify.certify(root, manifest, plan, mixed, policy, 'fixture', adoption=selected)

    def test_diagnostic_or_mutated_release_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, plan, reports, policy = self.fixture(root)
            altered = {k: v for k, v in plan.items() if k != "id"}
            altered["mode"] = "diagnostic"
            with self.assertRaises(ValueError):
                certify.certify(root, manifest, c.freeze(altered), reports, policy, "fixture")
            (root / "release.json").write_text("changed")
            with self.assertRaises(ValueError):
                certify.certify(root, manifest, plan, reports, policy, "fixture")

    def test_missing_platform_scope_and_optional_required_scope_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, plan, reports, policy = self.fixture(root)
            for change in (lambda x: x["checks"].pop(), lambda x: x["checks"][0].update(required=False)):
                altered = copy.deepcopy(plan)
                del altered["id"]
                change(altered)
                with self.assertRaises(ValueError):
                    certify.certify(root, manifest, c.freeze(altered), reports, policy, "fixture")
            manifest["artifacts"][0]["backends"].append("fltk")
            with self.assertRaises(ValueError):
                certify.certify(root, manifest, plan, reports, policy, "fixture")

    def test_noop_or_removed_receipt_never_certifies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, plan, reports, policy = self.fixture(root)
            (reports[0].parent / "qualification.json").unlink()
            with self.assertRaises((ValueError, OSError)):
                certify.certify(root, manifest, plan, reports, policy, "fixture")
            altered = copy.deepcopy(plan)
            del altered["id"]
            del altered["checks"][0]["qualification"]
            with self.assertRaisesRegex(ValueError, "bound qualification"):
                certify.certify(root, manifest, c.freeze(altered), reports, policy, "fixture")

    def test_group_must_cover_every_delivered_backend_before_evidence_merge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target='linux-x86_64';backends=['fltk','sdl','rev']
            manifest={'source':{'sha256':'a'*64},'artifacts':[{'target':target,'backends':backends}],
                      'required_scopes':['source','archive','recovery']}
            c.write_new(root/'release.json',manifest)
            rows=[dict(target=target,backend=b,environment='fixture',scope=scope)
                  for scope in ('source','archive','recovery') for b in backends]
            policy={'schema_version':1,'profiles':{'fixture':{'description':'complete group fixture',
                    'targets':{target:backends},'checks':rows}}}
            checks=[dict(row,id=row['scope']+'-'+row['backend'],required=True,argv=['fixture'],
                         timeout_seconds=5,warning_seconds=4,expected_tests=[],qualification='qualification.json') for row in rows]
            for row in checks[:2]:
                row.update(execution='source-fltk',qualification=row['id']+'.qualification.json')
            frozen=c.freeze(dict(schema_version=1,mode='release',inputs={},checks=checks,
                subject=dict(source_sha256='a'*64,inventory_sha256=c.sha(root/'release.json'),
                             configuration_sha256=c.digest({'policy':policy,'profile':'fixture'}))))
            with self.assertRaisesRegex(ValueError,'every delivered backend'):
                certify.certify(root,manifest,frozen,[],policy,'fixture')

    def test_shipped_policies_have_source_archive_and_recovery_per_backend(self):
        policy = c.load(Path(__file__).resolve().parents[1] / "docs/release-policy.json")
        for name in policy["profiles"]:
            certify.requirements(policy, name)


if __name__ == "__main__":
    unittest.main()
