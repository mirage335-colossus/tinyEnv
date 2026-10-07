import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("foundation_coverage", Path(__file__).resolve().parents[1] / "tools/coverage.py")
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def plan(command=None):
    return coverage.freeze({"schema_version": 1, "mode": "release", "subject": {
        "source_sha256": "a" * 64, "inventory_sha256": "b" * 64,
        "configuration_sha256": "c" * 64}, "inputs": {}, "checks": [{
        "id": "contract", "scope": "source", "target": "linux-x86_64", "environment": "fixture",
        "backend": "core", "required": True, "argv": command or ["{python}", "-c", "print('checked')"],
        "timeout_seconds": 5, "warning_seconds": 4, "expected_tests": []}]})


class CoverageTests(unittest.TestCase):
    def test_real_success_retains_evidence_and_rejects_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = plan()
            result = coverage.run_case(frozen, "contract", root, root / "one", "local", 1)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(coverage.merge(frozen, [root / "one/result.json"])["status"], "passed")
            with self.assertRaises(FileExistsError):
                coverage.run_case(frozen, "contract", root, root / "one", "local", 2)
            (root / "one/console.log").write_text("replaced")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                coverage.merge(frozen, [root / "one/result.json"])

    def test_child_execution_context_overrides_inheritance_without_mutating_parent(self):
        inherited = dict(FOUNDATION_PLAN_ID='stale-plan', FOUNDATION_CHECK_ID='stale-check',
                         FOUNDATION_RUN_ID='stale-run', FOUNDATION_RUN_ATTEMPT='99',
                         CHECK='hosted-check', GITHUB_RUN_ID='hosted-run', GITHUB_RUN_ATTEMPT='88',
                         FOUNDATION_TEST_KEEP='preserved caller value')
        keys = list(inherited)
        command = ['{python}', '-c', 'import os,json; print(json.dumps({key:os.environ.get(key) for key in ' + repr(keys) + '}))']
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, inherited):
            root = Path(temporary); frozen = plan(command); before = dict(os.environ)
            result = coverage.run_case(frozen, 'contract', root, root / 'context', 'local-release', 2)
            self.assertEqual(result['status'], 'passed', result)
            observed = json.loads((root / 'context/console.log').read_text())
            expected = dict(inherited, FOUNDATION_PLAN_ID=frozen['id'], FOUNDATION_CHECK_ID='contract',
                            FOUNDATION_RUN_ID='local-release', FOUNDATION_RUN_ATTEMPT='2')
            self.assertEqual(observed, expected)
            self.assertEqual(dict(os.environ), before)

    def test_invalid_execution_identity_cannot_launch_or_create_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen = plan()
            for run_id, attempt in ((None, 1), ('../run', 1), ('run', True), ('run', '2'), ('run', 0)):
                with self.subTest(run_id=run_id, attempt=attempt), self.assertRaisesRegex(ValueError, 'run identity'):
                    coverage.run_case(frozen, 'contract', root, root / 'invalid', run_id, attempt)
                self.assertFalse((root / 'invalid').exists())

    def test_failure_never_becomes_pass_and_missing_duplicate_results_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = plan(["{python}", "-c", "raise SystemExit(7)"])
            coverage.run_case(frozen, "contract", root, root / "one", "run", 1)
            report = root / "one/result.json"
            self.assertEqual(coverage.merge(frozen, [report])["status"], "failed")
            for paths in ([], [report, report]):
                with self.assertRaises(ValueError):
                    coverage.merge(frozen, paths)

    def test_different_attempts_cannot_supply_one_complete_inventory(self):
        spec={k:v for k,v in plan().items() if k!='id'}
        spec['checks'].append(dict(spec['checks'][0],id='second'))
        frozen=coverage.freeze(spec)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for index,row in enumerate(frozen['checks']):
                coverage.run_case(frozen,row['id'],root,root/row['id'],'run',index+1)
            with self.assertRaisesRegex(ValueError,'mixed runs/attempts'):
                coverage.merge(frozen,[root/row['id']/'result.json' for row in frozen['checks']])

    def test_timeout_is_incomplete_and_retains_failed_attempt(self):
        frozen = plan(["{python}", "-c", "import time;time.sleep(60)"])
        del frozen["id"]
        frozen["checks"][0].update(timeout_seconds=0.15, warning_seconds=0.1)
        frozen = coverage.freeze(frozen)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = coverage.run_case(frozen, "contract", root, root / "timeout", "run", 1)
            self.assertEqual(result["status"], "incomplete")
            self.assertLess(result["seconds"], 5)

    def test_input_mutation_after_launch_invalidates_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.txt").write_text("before")
            frozen = plan(["{python}", "-c", "from pathlib import Path;Path('input.txt').write_text('after')"])
            del frozen["id"]
            frozen["inputs"] = {"input.txt": coverage.sha(root / "input.txt")}
            frozen = coverage.freeze(frozen)
            result = coverage.run_case(frozen, "contract", root, root / "one", "run", 1)
            self.assertEqual(result["status"], "failed")
            self.assertIn("input changed", result["error"])

    def test_junit_missing_skipped_duplicate_or_failed_is_not_success(self):
        fixtures = ['<testsuite/>', '<testsuite><testcase name="one"><skipped/></testcase></testsuite>',
                    '<testsuite><testcase name="one"/><testcase name="one"/></testsuite>',
                    '<testsuite><testcase name="one"><failure/></testcase></testsuite>']
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "junit.xml"
            for xml in fixtures:
                path.write_text(xml)
                with self.assertRaises(ValueError):
                    coverage.junit(path, ["one"])
            path.write_text('<testsuite><testcase name="one"/></testsuite>')
            coverage.junit(path, ["one"])

    def test_parent_success_with_inherited_log_child_is_rejected(self):
        import os
        if os.name != "posix":
            self.skipTest("POSIX fixture; Windows job-owner fixture is separate")
        command = ["{python}", "-c", "import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = coverage.run_case(plan(command), "contract", root, root / "orphan", "run", 1)
            self.assertEqual(result["status"], "failed")
            self.assertIn("descendants outlived", result["error"])

    def test_fast_exit_still_obeys_final_output_bound(self):
        from unittest.mock import patch
        frozen = plan(["{python}", "-c", "print('x'*1000)"])
        with tempfile.TemporaryDirectory() as temporary, patch.object(coverage, "MAX_LOG", 10):
            root = Path(temporary)
            result = coverage.run_case(frozen, "contract", root, root / "large", "run", 1)
            self.assertEqual(result["status"], "incomplete")
            self.assertIn("output limit", result["error"])

    def test_plan_is_strict_and_digest_bound(self):
        original = plan()
        for change in (lambda x: x.update(mode="other"),
                       lambda x: x["checks"].append(x["checks"][0]),
                       lambda x: x["checks"][0].update(timeout_seconds=float("inf")),
                       lambda x: x["checks"][0].update(required="yes"),
                       lambda x: x.update(inputs={"../outside": "a" * 64})):
            value = copy.deepcopy(original)
            change(value)
            with self.assertRaises(ValueError):
                coverage.validate(value)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError):
                coverage.load(path)




class GroupedExecutionTests(unittest.TestCase):
    def fixture(self, root):
        rows=[]
        for backend in ('fltk','sdl'):
            rows.append(dict(id='source-'+backend,execution='source-fltk',scope='source',target=coverage.host_identity()['system'].lower()+'-'+{'amd64':'x86_64','arm64':'aarch64'}.get(coverage.host_identity()['machine'].lower(),coverage.host_identity()['machine'].lower()),
                environment='fixture',backend=backend,required=True,argv=['{python}','{root}/once.py','{evidence}'],
                timeout_seconds=5,warning_seconds=4,expected_tests=[],qualification='source-'+backend+'.qualification.json'))
        frozen=coverage.freeze(dict(schema_version=1,mode='release',subject=dict(source_sha256='a'*64,
            inventory_sha256='b'*64,configuration_sha256='c'*64),inputs={},checks=rows))
        identity=coverage.execution_identity(frozen,rows[0],'run',1,coverage.host_identity())
        receipt=dict(schema_version=1,status='passed',source_sha256='a'*64,inventory_sha256='b'*64,
            target=rows[0]['target'],backend='fltk',scope='source',host=coverage.host_identity(),
            details={'execution':identity,'executed_tests':['fixture']},assertions=['complete-artifact'],evidence={})
        code="import json,sys,hashlib,os\nfrom pathlib import Path\nout=Path(sys.argv[1])\n"
        code+="with Path('invocations').open('a') as stream: stream.write('one\\n')\n"
        code+='identity='+repr(identity)+'\nreceipt='+repr(receipt)+'\n'
        code+="(out/'context.json').write_text(json.dumps({key:os.environ[key] for key in ('FOUNDATION_PLAN_ID','FOUNDATION_CHECK_ID','FOUNDATION_RUN_ID','FOUNDATION_RUN_ATTEMPT')}))\n"
        code+="j=out/'source.junit.xml';j.write_text('<testsuite><testcase name=\"fixture\"/></testsuite>')\n"
        code+="p=out/'execution.json';p.write_text(json.dumps(identity));receipt['evidence']={'execution.json':hashlib.sha256(p.read_bytes()).hexdigest(),'source.junit.xml':hashlib.sha256(j.read_bytes()).hexdigest()};(out/'source-fltk.qualification.json').write_text(json.dumps(receipt))\n"
        (root/'once.py').write_text(code)
        return frozen

    def test_one_real_child_produces_every_bound_logical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);frozen=self.fixture(root);out=root/'source-fltk'
            result=coverage.run_execution(frozen,'source-fltk',root,out,'run',1)
            self.assertEqual(result['status'],'passed',result)
            self.assertEqual((root/'invocations').read_text(),'one\n')
            self.assertEqual(coverage.load(out / 'context.json'), dict(FOUNDATION_PLAN_ID=frozen['id'],
                FOUNDATION_CHECK_ID='source-fltk', FOUNDATION_RUN_ID='run', FOUNDATION_RUN_ATTEMPT='1'))
            paths=[coverage.result_path(frozen,row['id'],root) for row in frozen['checks']]
            merged=coverage.merge(frozen,paths)
            self.assertEqual(set(merged['checks']),{'source-fltk','source-sdl'})
            with self.assertRaises(ValueError):coverage.merge(frozen,paths[:1])
            with self.assertRaisesRegex(ValueError,'leader'):coverage.run_execution(frozen,'source-sdl',root,root/'bad','run',1)
            with self.assertRaisesRegex(ValueError,'physical'):coverage.run_case(frozen,'source-fltk',root,root/'bad','run',1)
            second=json.loads(paths[1].read_text());second['attempt']=2;paths[1].write_text(json.dumps(second))
            with self.assertRaisesRegex(ValueError,'mixed runs/attempts'):coverage.merge(frozen,paths)
            second['attempt']=1;second['seconds']+=1;paths[1].write_text(json.dumps(second))
            with self.assertRaisesRegex(ValueError,'different physical'):coverage.merge(frozen,paths)

    def test_group_changes_and_partial_backend_receipts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);frozen=self.fixture(root)
            for key,value in [('scope','recovery'),('environment','other'),('argv',['different'])]:
                wrong=copy.deepcopy(frozen);wrong.pop('id');wrong['checks'][1][key]=value
                with self.assertRaises(ValueError):coverage.freeze(wrong)
            # ABI execution grouping remains explicitly Linux-only.
            wrong = copy.deepcopy(frozen); wrong.pop('id')
            for row in wrong['checks']:
                row.update(scope='abi', target='windows-x86_64')
            with self.assertRaisesRegex(ValueError, 'unsupported grouped execution'):
                coverage.freeze(wrong)
            coverage.run_execution(frozen,'source-fltk',root,root/'source-fltk','run',1)
            path=root/'source-fltk/source-sdl.qualification.json';value=json.loads(path.read_text());value['details']['execution']['backends']=['sdl'];path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'frozen execution'):
                coverage.qualification(path.parent,frozen['checks'][1],frozen,coverage.host_identity())

    def test_failed_execution_never_projects_a_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);frozen=self.fixture(root);(root/'once.py').write_text('raise SystemExit(2)\n')
            coverage.run_execution(frozen,'source-fltk',root,root/'source-fltk','run',1)
            paths=[coverage.result_path(frozen,row['id'],root) for row in frozen['checks']]
            self.assertEqual(coverage.merge(frozen,paths)['status'],'failed')
            self.assertTrue(all(json.loads(path.read_text())['status']=='failed' for path in paths))



class AdoptionTests(unittest.TestCase):
    def fixture(self, root):
        value = {key: item for key, item in plan().items() if key != 'id'}
        host = coverage.host_identity()
        machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(host['machine'].lower(), host['machine'].lower())
        value['checks'][0]['target'] = host['system'].lower() + '-' + machine
        value['checks'].append(dict(value['checks'][0], id='second'))
        (root / 'dependency').write_text('exact dependency')
        value['inputs'] = {'dependency': coverage.sha(root / 'dependency')}
        frozen = coverage.freeze(value)
        paths = []
        for name, attempt in [('contract', 1), ('second', 2)]:
            coverage.run_case(frozen, name, root, root / name, 'retry-run', attempt)
            paths.append(root / name / 'result.json')
        return frozen, paths

    def test_explicit_selection_reuses_only_exact_receipt_and_retains_original_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen, paths = self.fixture(root)
            originals = {path: path.read_bytes() for path in paths}
            with self.assertRaisesRegex(ValueError, 'mixed runs/attempts'):
                coverage.merge(frozen, paths)
            adoption = coverage.adopt(frozen, paths[:1], root, 'retry-run', 2)
            result = coverage.merge(frozen, paths, adoption=adoption)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['checks']['contract']['attempt'], 1)
            self.assertEqual(result['checks']['second']['attempt'], 2)
            self.assertEqual(result['adoption'], adoption)
            self.assertEqual(adoption['results']['contract']['sha256'], coverage.sha(paths[0]))
            self.assertEqual({path: path.read_bytes() for path in paths}, originals)

    def test_changed_plan_source_configuration_environment_or_dependency_cannot_be_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen, paths = self.fixture(root)
            for field in ('source_sha256', 'inventory_sha256', 'configuration_sha256', 'environment'):
                wrong = copy.deepcopy(frozen); del wrong['id']
                if field == 'environment': wrong['checks'][0]['environment'] = 'different'
                else: wrong['subject'][field] = 'e'*64
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'stale result'):
                    coverage.adopt(coverage.freeze(wrong), paths[:1], root, 'retry-run', 2)
            (root / 'dependency').write_text('new dependency')
            with self.assertRaisesRegex(ValueError, 'input changed'):
                coverage.adopt(frozen, paths[:1], root, 'retry-run', 2)

    def test_failed_current_future_other_run_and_unknown_receipts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen, paths = self.fixture(root)
            for run_id, attempt in [('other-run', 2), ('retry-run', 1), ('retry-run', 0), ('retry-run', True)]:
                with self.subTest(run_id=run_id, attempt=attempt), self.assertRaises(ValueError):
                    coverage.adopt(frozen, paths[:1], root, run_id, attempt)
            with self.assertRaisesRegex(ValueError, 'earlier attempts'):
                coverage.adopt(frozen, paths[1:], root, 'retry-run', 2)
            row = coverage.load(paths[0]); row.update(status='failed', exit_code=7, error='assertion')
            paths[0].write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'successful earlier'):
                coverage.adopt(frozen, paths[:1], root, 'retry-run', 2)
            with self.assertRaises(ValueError): coverage.adopt(frozen, [], root, 'retry-run', 2)
            with self.assertRaises(ValueError): coverage.adopt(frozen, [paths[0], paths[0]], root, 'retry-run', 2)

    def test_report_or_log_mutation_invalidates_adoption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen, paths = self.fixture(root)
            adoption = coverage.adopt(frozen, paths[:1], root, 'retry-run', 2)
            original = paths[0].read_bytes()
            row = coverage.load(paths[0]); row['seconds'] += 1
            paths[0].write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'identity or bytes changed'):
                coverage.merge(frozen, paths, adoption=adoption)
            paths[0].write_bytes(original)
            (paths[0].parent / 'console.log').write_text('changed retained evidence')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                coverage.merge(frozen, paths, adoption=adoption)

    def test_tampered_manifest_unused_selection_and_unapproved_prior_result_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen, paths = self.fixture(root)
            adoption = coverage.adopt(frozen, paths[:1], root, 'retry-run', 3)
            with self.assertRaisesRegex(ValueError, 'explicit adoption'):
                coverage.merge(frozen, paths, adoption=adoption)
            adoption['attempt'] = 2
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                coverage.merge(frozen, paths, adoption=adoption)
            adoption['id'] = coverage.digest({k:v for k,v in adoption.items() if k != 'id'})
            wrong = copy.deepcopy(adoption); wrong['results']['unexpected'] = wrong['results']['contract']
            wrong['id'] = coverage.digest({k:v for k,v in wrong.items() if k != 'id'})
            with self.assertRaisesRegex(ValueError, 'known results'):
                coverage.merge(frozen, paths, adoption=wrong)
            # Complete required inventory remains mandatory with explicit reuse.
            with self.assertRaisesRegex(ValueError, 'missing results'):
                coverage.merge(frozen, paths[:1], adoption=adoption)

    def test_actual_host_mismatch_cannot_be_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen, paths = self.fixture(root)
            row = coverage.load(paths[0]); row['host']['machine'] = 'wrong-architecture'
            paths[0].write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'actual execution host'):
                coverage.adopt(frozen, paths[:1], root, 'retry-run', 2)

    def test_grouped_execution_requires_complete_original_projections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = GroupedExecutionTests().fixture(root)
            coverage.run_execution(frozen, 'source-fltk', root, root / 'source-fltk', 'run', 1)
            paths = [coverage.result_path(frozen, row['id'], root) for row in frozen['checks']]
            with self.assertRaisesRegex(ValueError, 'every logical result'):
                coverage.adopt(frozen, paths[:1], root, 'run', 2)
            adoption = coverage.adopt(frozen, paths, root, 'run', 2)
            merged = coverage.merge(frozen, paths, adoption=adoption)
            self.assertEqual(merged['status'], 'passed')
            self.assertEqual((root / 'invocations').read_text(), 'one\n')
            self.assertEqual({row['attempt'] for row in merged['checks'].values()}, {1})
            wrong = copy.deepcopy(adoption); del wrong['results']['source-sdl']
            wrong['id'] = coverage.digest({k:v for k,v in wrong.items() if k != 'id'})
            with self.assertRaisesRegex(ValueError, 'explicit adoption'):
                coverage.merge(frozen, paths, adoption=wrong)

if __name__ == "__main__":
    unittest.main()
