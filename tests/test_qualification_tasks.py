"""Portable qualification commands retain the existing supervision and evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import qualification_tasks as tasks
coverage = tasks.evidence


class QualificationTasksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='qualification space ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.joinpath('build').mkdir()

    def plan(self, code="print('checked')", *, backend='core', grouped=False):
        check = dict(id='source-first', scope='source', target=coverage.host_identity()['system'].lower()+'-'+{'amd64':'x86_64','arm64':'aarch64'}.get(coverage.host_identity()['machine'].lower(),coverage.host_identity()['machine'].lower()), environment='fixture',
                     backend=backend, required=True, argv=['{python}', '-c', code],
                     timeout_seconds=5, warning_seconds=4, expected_tests=[])
        rows = [check]
        if grouped:
            check.update(execution=check['id'], qualification=check['id'] + '.qualification.json')
            rows.append(dict(check, id='source-second', backend='sdl', qualification='source-second.qualification.json'))
        self.root.joinpath('input.txt').write_text('original')
        plan = coverage.freeze(dict(schema_version=1, mode='release',
            subject=dict(source_sha256='a'*64, inventory_sha256='b'*64, configuration_sha256='c'*64),
            inputs={'input.txt': coverage.sha(self.root / 'input.txt')}, checks=rows))
        coverage.write_new(self.root / 'build/check-plan.json', plan)
        return plan

    def cli(self, operation, *args):
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('GITHUB_', 'FOUNDATION_', 'GH_'))}
        environment['PATH'] = ''  # Python is explicit; no gh or provider helper is available.
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        return subprocess.run([sys.executable, str(ROOT / 'tools/qualification_tasks.py'), operation,
                               '--root', str(self.root), *args], cwd=self.root / 'build',
                              env=environment, capture_output=True, text=True, timeout=15)

    def test_cli_runs_without_provider_context_and_retains_real_child_diagnostics(self):
        plan = self.plan("import os,json; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith('FOUNDATION_')}))")
        listed = self.cli('list')
        self.assertEqual(listed.returncode, 0, listed.stderr)
        result = self.cli('run', '--check', 'source-first', '--run-id', 'local-job', '--attempt', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'passed')
        output = self.root / 'build/evidence/source-first'
        self.assertEqual(json.loads((output / 'console.log').read_text()),
            dict(FOUNDATION_PLAN_ID=plan['id'], FOUNDATION_CHECK_ID='source-first',
                 FOUNDATION_RUN_ID='local-job', FOUNDATION_RUN_ATTEMPT='2'))
        self.assertEqual(coverage.load(output / 'result.json'), report)
        self.assertEqual(json.loads(listed.stdout)['executions'][0]['reports'],
                         ['build/evidence/source-first/result.json'])
        self.assertEqual(coverage.merge(plan, [output / 'result.json'])['status'], 'passed')


    def test_cli_adopts_explicit_prior_result_without_launch_or_overwrite(self):
        plan = self.plan()
        old = self.root / 'prior'
        coverage.run_case(plan, 'source-first', self.root, old, 'same-run', 1)
        output = self.root / 'adoption.json'
        args = ('--run-id', 'same-run', '--attempt', '2', '--output', str(output), str(old / 'result.json'))
        result = self.cli('adopt', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = coverage.load(output)
        self.assertEqual(selected['results']['source-first']['attempt'], 1)
        self.assertFalse((self.root / 'build/evidence').exists())
        self.assertEqual(coverage.merge(plan, [old/'result.json'], adoption=selected)['status'], 'passed')
        original = output.read_bytes()
        again = self.cli('adopt', *args)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('new immutable output', again.stderr)
        self.assertEqual(output.read_bytes(), original)

    def test_cli_adoption_failure_leaves_no_output(self):
        plan = self.plan(); old = self.root / 'prior'
        coverage.run_case(plan, 'source-first', self.root, old, 'same-run', 1)
        (self.root / 'input.txt').write_text('changed')
        output = self.root / 'adoption.json'
        result = self.cli('adopt', '--run-id', 'same-run', '--attempt', '2', '--output', str(output), str(old / 'result.json'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('input changed', result.stderr)
        self.assertFalse(output.exists())

    def test_failed_child_is_nonzero_with_retained_failure_log(self):
        self.plan("print('compiler detail'); raise SystemExit(7)")
        result = self.cli('run', '--check', 'source-first', '--run-id', 'local-job', '--attempt', '1')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'failed')
        self.assertIn('compiler detail', self.root.joinpath('build/evidence/source-first/console.log').read_text())

    def test_grouped_inventory_lists_one_launch_and_every_logical_report(self):
        self.plan(backend='fltk', grouped=True)
        listing = tasks.executions(self.root)
        self.assertEqual(len(listing['executions']), 1)
        execution = listing['executions'][0]
        self.assertEqual(execution['checks'], ['source-first', 'source-second'])
        self.assertEqual(execution['backends'], ['fltk', 'sdl'])
        self.assertEqual(execution['reports'], ['build/evidence/source-first/source-first.result.json',
                                               'build/evidence/source-first/source-second.result.json'])
        self.assertNotIn('runner', execution)
        with self.assertRaisesRegex(ValueError, 'leader'):
            tasks.run(self.root, 'source-second', 'local', 1)
        self.assertFalse(self.root.joinpath('build/evidence').exists())

    def test_invalid_identity_or_check_cannot_launch(self):
        self.plan()
        for check, run, attempt in [('missing', 'local', 1), ('source-first', '../unsafe', 1),
                                     ('source-first', 'local', 0), ('source-first', 'local', True)]:
            with self.subTest(check=check, run=run, attempt=attempt), self.assertRaises(ValueError):
                tasks.run(self.root, check, run, attempt)
        self.assertFalse(self.root.joinpath('build/evidence').exists())

    def test_changed_input_fails_before_launch(self):
        self.plan()
        self.root.joinpath('input.txt').write_text('changed')
        result = self.cli('run', '--check', 'source-first', '--run-id', 'local', '--attempt', '1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('input changed', json.loads(result.stderr)['error'])
        self.assertFalse(self.root.joinpath('build/evidence').exists())

    def test_changed_plan_cannot_be_listed(self):
        plan = self.plan(); plan['checks'][0]['environment'] = 'different'
        self.root.joinpath('build/check-plan.json').write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'digest differs'):
            tasks.executions(self.root)

    def test_prepare_without_browser_has_no_prerequisite_or_evidence_side_effects(self):
        self.plan()
        with patch.object(tasks.ci_plan, 'install_browser_prerequisite') as install:
            self.assertEqual(tasks.prepare(self.root, 'source-first', 'local', 1)['status'], 'not_required')
        install.assert_not_called()
        self.assertFalse(self.root.joinpath('build/prerequisites').exists())
        self.assertFalse(self.root.joinpath('build/evidence').exists())

    def test_browser_prepare_is_explicit_and_binds_receipt_before_new_run_directory(self):
        plan = self.plan()
        def install(target, environment, backend, directory):
            return dict(status='passed', executable='/fixture/browser')
        with patch.object(tasks, '_needs_browser', return_value=True), \
                patch.object(tasks.ci_plan, 'install_browser_prerequisite', side_effect=install) as setup:
            with self.assertRaisesRegex(ValueError, 'explicit browser prerequisite'):
                tasks.run(self.root, 'source-first', 'local', 2)
            setup.assert_not_called()
            prepared = tasks.prepare(self.root, 'source-first', 'local', 2)
            receipt = coverage.load(Path(prepared['receipt']))
            self.assertEqual({key: receipt[key] for key in ('plan', 'check', 'run_id', 'attempt')},
                             dict(plan=plan['id'], check='source-first', run_id='local', attempt=2))
            self.assertFalse(self.root.joinpath('build/evidence').exists())
            with patch.object(coverage, 'run_execution', return_value={'status': 'passed'}) as execute:
                tasks.run(self.root, 'source-first', 'local', 2)
            self.assertEqual(setup.call_count, 1)
            self.assertEqual(execute.call_args.args[3], self.root / 'build/evidence/source-first')


if __name__ == '__main__':
    unittest.main()
