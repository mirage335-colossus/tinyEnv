"""Fail-closed orchestration contracts and exact final remote pointer verification."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import latest_release as L
import test_github_release as fixtures


def request(execute=True):
    return {'repository': 'example/project', 'source_commit': 'a' * 40, 'run_id': '123', 'attempt': 1,
            'tag': 'v1', 'profile': 'core', 'recipes': {target: 'b' * 64 for target in L.ci.STANDARD},
            'gui_group': '', 'graphics_archive_url': '', 'execute': execute, 'jobs': '2'}


def previous_packages():
    return {target: {'tag': 'distro-0.1.0-' + target.removeprefix('linux-') + '-r1-s1',
                     'manifest_sha256': 'c' * 64, 'target': target}
            for target in ('linux-x86_64', 'linux-aarch64')}


def results(execute=True):
    value = {name: {'result': 'success', 'outputs': {}} for name in L.STAGES}
    value['application']['outputs'] = {'source_commit': 'a' * 40, 'tag': 'v1', 'inventory_sha256': 'c' * 64,
                                      'delivery_sha256': 'd' * 64, 'published': 'true' if execute else 'false'}
    value['certification']['outputs'] = {'inventory_sha256': 'c' * 64, 'certificate_sha256': 'e' * 64,
        'certification_run': '123', 'certification_attempt': '1', 'eligible_for_promotion': 'true', 'attached': 'true'}
    value['promotion']['outputs'] = {'promoted': 'true'}
    if not execute:
        for name in L.STAGES[3:]: value[name] = {'result': 'skipped', 'outputs': {}}
    return value


def retained_base(names):
    remote = fixtures.FakeGitHub()
    remote.refs['base'] = 'a' * 40
    remote.releases.append({'id': 1, 'tag_name': 'base', 'draft': False,
        'prerelease': True, 'name': 'base', 'assets': [
            {'id': index + 100, 'name': name, 'state': 'uploaded',
             'size': 1, 'digest': 'sha256:' + 'a' * 64}
            for index, name in enumerate(sorted(names))]})
    return remote


class LatestReleaseTests(unittest.TestCase):
    def test_cli_creates_fresh_receipt_parent_without_overwriting(self):
        # Supply a fixture request and preflight response in a fresh child;
        # argument parsing, Git identity and file publication remain real.
        program = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv.pop(1))
import latest_release as L
L.ROOT = Path(sys.argv.pop(1))
request = json.loads(sys.argv.pop(1))
L.environment_request = lambda: request
L.preflight = lambda value: dict(value, status='prepared')
L.main()
'''
        with tempfile.TemporaryDirectory() as temporary:
            # Source releases deliberately omit Git history. Keep this real Git
            # fixture independent of the checkout containing the test itself.
            repository = Path(temporary) / 'fixture-repository'
            repository.mkdir()
            def git(*args):
                return subprocess.run(['git', *args], cwd=repository, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '--quiet')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'fixture')
            value = dict(request(False), source_commit=git('rev-parse', 'HEAD'))
            output = Path(temporary) / 'absent' / 'build' / 'receipt.json'
            command = [sys.executable, '-B', '-c', program, str(L.ROOT / 'tools'), str(repository),
                       json.dumps(value), 'preflight', '--output', str(output)]
            environment = dict(os.environ, GITHUB_OUTPUT=str(Path(temporary) / 'workflow-output'))
            first = subprocess.run(command, cwd=temporary, capture_output=True, text=True, env=environment)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            self.assertEqual(json.loads(original)['status'], 'prepared')
            second = subprocess.run(command, cwd=temporary, capture_output=True, text=True, env=environment)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('FileExistsError', second.stderr)
            self.assertEqual(output.read_bytes(), original)
            mismatch = command.copy()
            mismatch[6] = json.dumps(dict(value, source_commit='0' * 40))
            mismatch[-1] = str(Path(temporary) / 'mismatch.json')
            rejected = subprocess.run(mismatch, cwd=temporary, capture_output=True, text=True, env=environment)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('checked-out source does not match workflow commit', rejected.stderr)
            self.assertFalse(Path(mismatch[-1]).exists())

    def test_preflight_requires_complete_target_recipes_and_separate_tag(self):
        prepared = L.preflight(request(), remote=False)
        self.assertEqual(prepared['tag'], 'v1')
        self.assertEqual(prepared['core_provider'], 'rust')
        self.assertEqual(prepared['rust_recipes'],
                         {target: L.ci.rust_recipe(target) for target in L.ci.STANDARD})
        for changes in ({'recipes': {}}, {'tag': 'base'}, {'tag': 'screenshots-1'}, {'tag': 'ci-1'},
                        {'execute': 'true'}, {'source_commit': 'main'}, {'gui_group': 'a' * 64},
                        {'core_provider': ''}, {'core_provider': 'automatic'}, {'unknown': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                L.preflight(dict(request(), **changes), remote=False)
        self.assertEqual(L.preflight(dict(request(), tag=''), remote=False)['tag'], 'release-123-attempt-1')

    def test_default_preflight_requires_every_exact_retained_rust_group_without_acquisition(self):
        cpp_names = {name for recipe in request()['recipes'].values()
                     for name in L.delivery.store.names(recipe)}
        rust_names = {name for target in L.ci.STANDARD
                      for name in L.ci.rust_base_names(L.ci.rust_recipe(target))}
        complete = cpp_names | rust_names
        cases = [cpp_names, complete - {sorted(rust_names)[0]},
                 cpp_names | set(L.ci.rust_base_names('f' * 64))]
        for names in cases:
            with self.subTest(names=sorted(names)):
                remote = retained_base(names)
                with self.assertRaisesRegex(ValueError, 'complete Rust base recipe missing'):
                    L.preflight(request(), transport=remote)
                self.assertEqual(remote.mutations, [])
                self.assertFalse(any(call[0] == 'download' for call in remote.calls))
        remote = retained_base(complete)
        prepared = L.preflight(request(), transport=remote)
        self.assertEqual(prepared['core_provider'], 'rust')
        self.assertEqual(len(prepared['rust_recipes']), len(L.ci.STANDARD))
        self.assertEqual(remote.mutations, [])
        self.assertFalse(any(call[0] == 'download' for call in remote.calls))

    def test_explicit_cpp_recovery_preflight_uses_cpp_base_without_rust_inputs(self):
        names = {name for recipe in request()['recipes'].values()
                 for name in L.delivery.store.names(recipe)}
        remote = retained_base(names)
        prepared = L.preflight(dict(request(), core_provider='cpp'), transport=remote)
        self.assertEqual(prepared['core_provider'], 'cpp')
        self.assertEqual(prepared['rust_recipes'], {})
        self.assertTrue(all(row['core_provider'] == 'cpp' and not row['rust_recipe']
                            for row in prepared['matrix']['include']))
        self.assertEqual(remote.mutations, [])

    def test_package_revision_bounds_reject_before_remote_work(self):
        for revision in ('1', '999999'):
            prepared = L.preflight(dict(request(False), package_release=revision,
                                        previous_packages={}, attempt=999), remote=False)
            self.assertEqual(prepared['package_release'], revision)
            self.assertFalse(prepared['execute'])
        for changes in ({'package_release': ''}, {'package_release': '0'}, {'package_release': '01'},
                        {'package_release': '1000000'}, {'package_release': 1},
                        {'package_release': True}, {'package_release': '1', 'attempt': 1000},
                        {'package_release': '1', 'tag': 'latest'}, {'package_release': '1', 'tag': 'Latest'}):
            remote = fixtures.FakeGitHub()
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'package revision'):
                L.preflight(dict(request(False), **changes), transport=remote)
            self.assertEqual(remote.calls, [])

    def test_package_execution_requires_both_exact_predecessors(self):
        complete = previous_packages()
        for provider in ('rust', 'cpp'):
            prepared = L.preflight(dict(request(), core_provider=provider, package_release='2',
                                        previous_packages=complete), remote=False)
            self.assertEqual(prepared['previous_packages'], complete)
            self.assertEqual(prepared['core_provider'], provider)
        integrated = {target: dict(selected, tag='previous-application', format='release-packages')
                      for target, selected in complete.items()}
        self.assertEqual(L.preflight(dict(request(), package_release='2', previous_packages=integrated),
                                     remote=False)['previous_packages'], integrated)
        malformed = [None, [], {}, {'linux-x86_64': complete['linux-x86_64']},
                     dict(complete, **{'windows-x86_64': complete['linux-x86_64']})]
        for mutation in ('swapped-target', 'missing-digest', 'extra-selector-field', 'new-candidate'):
            changed = copy.deepcopy(complete)
            selected = changed['linux-x86_64']
            if mutation == 'swapped-target': selected['target'] = 'linux-aarch64'
            elif mutation == 'missing-digest': del selected['manifest_sha256']
            elif mutation == 'extra-selector-field': selected['track'] = 'latest'
            else: selected['tag'] = 'release-123-attempt-1'
            malformed.append(changed)
        for previous in malformed:
            remote = fixtures.FakeGitHub()
            with self.subTest(previous=previous), self.assertRaises(ValueError):
                L.preflight(dict(request(), tag='', package_release='2', previous_packages=previous),
                            transport=remote)
            self.assertEqual(remote.calls, [])

    def test_predecessor_controls_cannot_be_orphaned_from_package_revision(self):
        remote = fixtures.FakeGitHub()
        with self.assertRaisesRegex(ValueError, 'package revision'):
            L.preflight(dict(request(False), previous_packages=previous_packages()), transport=remote)
        self.assertEqual(remote.calls, [])

    def test_environment_provider_defaults_rust_and_preserves_explicit_cpp(self):
        environment = {'GITHUB_REPOSITORY': 'example/project', 'GITHUB_SHA': 'a' * 40,
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'PROFILE': 'core',
            'RECIPES': json.dumps(request()['recipes']), 'EXECUTE': 'false', 'JOBS': '2'}
        with mock.patch.dict(os.environ, environment, clear=True):
            defaults = L.environment_request()
            self.assertEqual(defaults['core_provider'], 'rust')
            self.assertNotIn('package_release', defaults)
            self.assertNotIn('previous_packages', defaults)
            with mock.patch.dict(os.environ, PACKAGE_RELEASE=''):
                self.assertEqual(L.environment_request()['package_release'], '')
                self.assertEqual(L.environment_request()['previous_packages'], {})
            with mock.patch.dict(os.environ, PACKAGE_RELEASE='2', PREVIOUS_PACKAGES=json.dumps(previous_packages())):
                selected = L.environment_request()
                self.assertEqual(selected['package_release'], '2')
                self.assertEqual(selected['previous_packages'], previous_packages())
            with mock.patch.dict(os.environ, CORE_PROVIDER='cpp'):
                self.assertEqual(L.environment_request()['core_provider'], 'cpp')
            with mock.patch.dict(os.environ, PREVIOUS_PACKAGES='{"linux-x86_64":{},"linux-x86_64":{}}'):
                with self.assertRaisesRegex(ValueError, 'duplicate JSON field: linux-x86_64'):
                    L.environment_request()

    def test_unresolved_gui_redistribution_fails_before_remote_work(self):
        policy=(L.ci.ROOT/'docs/release-policy.json').read_bytes()
        modules={name:L.ci.module(name) for name in ('coverage','certify_release')}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'third_party').mkdir();(root/'docs').mkdir()
            (root/'docs/release-policy.json').write_bytes(policy)
            (root/'third_party/gui-boundary.lock.json').write_text('{"redistribution":{"approved":false}}')
            with mock.patch.object(L.ci,'ROOT',root),mock.patch.object(L.ci,'module',side_effect=modules.__getitem__),self.assertRaisesRegex(ValueError,'licens'):
                L.preflight(dict(request(),profile='all-gui',recipes={**request()['recipes'],'browser-wasm32':'b'*64}),remote=False)

    def test_preflight_missing_base_has_no_cold_build_or_mutation(self):
        remote = fixtures.FakeGitHub()
        with self.assertRaisesRegex(ValueError, 'absent'):
            L.preflight(request(), transport=remote)
        self.assertEqual(remote.mutations, [])

    def test_every_mandatory_stage_must_actually_succeed(self):
        L.require_stages(results(), request())
        for stage in L.STAGES:
            for outcome in ('failure', 'cancelled', 'skipped', 'neutral'):
                value = results(); value[stage]['result'] = outcome
                with self.subTest(stage=stage, outcome=outcome), self.assertRaisesRegex(ValueError, 'mandatory'):
                    L.require_stages(value, request())

    def test_incomplete_inventory_is_not_a_successful_orchestration(self):
        value = results(); value.pop('regression')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            L.require_stages(value, request())

    def test_source_tag_inventory_and_publication_outputs_are_bound(self):
        for key, changed in [('source_commit', 'b' * 40), ('tag', 'v2'), ('inventory_sha256', ''),
                             ('delivery_sha256', ''), ('published', 'false')]:
            value = results(); value['application']['outputs'][key] = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'application outputs'):
                L.require_stages(value, request())

    def test_certificate_cannot_come_from_another_attempt_or_delivery(self):
        for key, changed in [('inventory_sha256', 'f' * 64), ('certificate_sha256', ''),
                             ('certification_run', '124'), ('certification_attempt', '2'),
                             ('eligible_for_promotion', 'false'), ('attached', 'false')]:
            value = results(); value['certification']['outputs'][key] = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'certificate'):
                L.require_stages(value, request())

    def test_plan_only_explicitly_omits_qualification_and_remote_calls(self):
        remote = fixtures.FakeGitHub()
        value = L.verify_latest(request(False), results(False), transport=remote)
        self.assertEqual(value['status'], 'prepared'); self.assertFalse(value['qualified'])
        self.assertFalse(value['published']); self.assertEqual(remote.calls, [])
        unexpected = results(False); unexpected['certification']['result'] = 'success'
        with self.assertRaisesRegex(ValueError, 'unexpectedly entered'):
            L.verify_latest(request(False), unexpected, transport=remote)

    def test_final_remote_review_reproduces_real_certificate_and_detects_latest_change(self):
        fixture = fixtures.DeliveryTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.publish(); cert = fixture.cert()
        L.delivery.attach_certificate(**cert, execute=True, transport=fixture.remote)
        fixture.promotion(cert, execute=True)
        req = dict(request(), profile='fixture', run_id='qualification-run')
        value = results(); app = value['application']['outputs']; app['inventory_sha256'] = fixture.delivery['inventory_sha256']
        app['delivery_sha256'] = L.delivery.sha(L.delivery.archive.encoded(fixture.delivery))
        value['certification']['outputs'].update(inventory_sha256=app['inventory_sha256'],
            certificate_sha256=L.delivery.archive.digest(cert['certificate']), certification_run='qualification-run')
        real_verify = L.delivery.verify_certificate
        def verify(*args, **kwargs):
            args = list(args); args[4] = cert['policy']
            return real_verify(*args, **kwargs)
        with mock.patch.object(L.delivery, 'verify_certificate', side_effect=verify):
            checked = L.verify_latest(req, value, transport=fixture.remote)
            self.assertTrue(checked['qualified']); self.assertEqual(checked['assets'].keys(),
                {a['name'] for a in fixture.remote.releases[0]['assets']})
            # A genuine ordinary certificate and Latest pointer remain sufficient
            # for historical candidates, but cannot qualify a future package-
            # enabled request whose complete inventory has no package repositories.
            future = dict(req, package_release='2', previous_packages=previous_packages())
            before = copy.deepcopy(fixture.remote.releases)
            with mock.patch.object(L.delivery, 'verify_certificate') as replay:
                with self.assertRaisesRegex(ValueError, 'required package repositories'):
                    L.verify_latest(future, value, transport=fixture.remote)
            replay.assert_not_called()
            self.assertEqual(fixture.remote.releases, before)
            fixture.remote.releases[0]['prerelease'] = True
            with mock.patch.object(L.delivery, 'verify_certificate') as replay:
                with self.assertRaisesRegex(ValueError, 'lifecycle'):
                    L.verify_latest(req, value, transport=fixture.remote)
            replay.assert_not_called()
            fixture.remote.releases[0]['prerelease'] = False
            fixture.remote.releases.append(dict(id=99, tag_name='different', draft=False, prerelease=False, name='different', assets=[]))
            fixture.remote.latest = 99
            with self.assertRaisesRegex(ValueError, 'identity|Latest'):
                L.verify_latest(req, value, transport=fixture.remote)


class WorkflowOverlapTests(unittest.TestCase):
    def test_package_signing_secret_is_explicitly_forwarded_and_optional(self):
        root = Path(__file__).resolve().parents[1]
        latest = (root/'.github/workflows/_release-latest.yml').read_text()
        application = (root/'.github/workflows/sdk-application.yml').read_text()
        caller = latest.split('\njobs:\n', 1)[1].split('  application:\n', 1)[1].split('  certification:\n', 1)[0]
        self.assertIn('    uses: ./.github/workflows/sdk-application.yml\n', caller)
        self.assertIn('    secrets:\n      DISTRIBUTION_SIGNING_KEY: ${{ secrets.DISTRIBUTION_SIGNING_KEY }}\n', caller)
        self.assertEqual(caller.count('    secrets:\n'), 1)
        self.assertNotIn('secrets: inherit', latest)
        contract = application.split('  workflow_call:\n', 1)[1].split('\npermissions:\n', 1)[0]
        secrets = contract.split('    secrets:\n', 1)[1].split('    outputs:\n', 1)[0]
        self.assertEqual([line.strip() for line in secrets.splitlines()
                          if line.startswith('      ') and not line.startswith('        ')],
                         ['DISTRIBUTION_SIGNING_KEY:'])
        self.assertIn('        required: false\n', secrets)
        dispatch = application.split('  workflow_dispatch:\n', 1)[1].split('  workflow_call:\n', 1)[0]
        package_input = dispatch.split('      package_repository:\n', 1)[1].split('      package_release:\n', 1)[0]
        self.assertIn('        default: false\n', package_input)
        assembly = application.split('  assemble:\n', 1)[1].split('\nenv:\n', 1)[0]
        self.assertIn("environment: ${{ (inputs.execute || inputs.package_repository) && 'release-publisher' || '' }}", assembly)
        self.assertIn("SIGNING_PRIVATE_KEY: ${{ inputs.package_repository && secrets.DISTRIBUTION_SIGNING_KEY || '' }}", assembly)

    def test_package_signing_guard_keeps_key_private_and_optional(self):
        root = Path(__file__).resolve().parents[1]
        application = (root/'.github/workflows/sdk-application.yml').read_text()
        assembly = application.split('  assemble:\n', 1)[1].split('\nenv:\n', 1)[0]
        step = assembly.split('    - shell: python\n      env:\n        SIGNING_PRIVATE_KEY:', 1)[1]
        code = step.split('      run: |-\n', 1)[1].split('      id: result\n', 1)[0]
        code = '\n'.join(line[8:] for line in code.splitlines())
        program = compile(code, 'protected-package-assembly', 'exec')
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(os, 'putenv', side_effect=AssertionError('synthetic signing fixture must not modify the native environment')) as native_write:
            runner_temp = Path(directory).resolve()
            environment = {'PACKAGE_REPOSITORY': 'true', 'RUNNER_TEMP': str(runner_temp)}
            oversized = 'x' * (1024 * 1024 + 1)
            original_environment = os.environ
            before = dict(original_environment)
            # Guard inputs remain ordinary Python data, including oversized keys.
            for private in ('', oversized):
                with self.subTest(key_available=bool(private)), \
                        mock.patch.object(os, 'environ', dict(environment, SIGNING_PRIVATE_KEY=private)), \
                        mock.patch.object(subprocess, 'run') as run, \
                        mock.patch.object(tempfile, 'TemporaryDirectory') as private_directory:
                    with self.assertRaisesRegex(ValueError, 'bounded protected distribution signing key required'):
                        exec(program, {})
                    run.assert_not_called()
                    private_directory.assert_not_called()
                    self.assertNotIn('SIGNING_PRIVATE_KEY', os.environ)
                self.assertEqual(list(runner_temp.iterdir()), [])
            for child_fails in (False, True):
                keys = []
                def assemble(command, *, check, env):
                    self.assertEqual(command, [sys.executable, '.github/scripts/lifecycle.py', 'assemble'])
                    self.assertTrue(check)
                    self.assertNotIn('SIGNING_PRIVATE_KEY', os.environ)
                    self.assertNotIn('SIGNING_PRIVATE_KEY', env)
                    key = Path(env['PACKAGE_SIGNING_KEY'])
                    keys.append(key)
                    self.assertTrue(key.is_relative_to(runner_temp))
                    self.assertEqual(key.read_text(), 'synthetic private key fixture')
                    if os.name == 'posix':
                        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
                    if child_fails:
                        raise subprocess.CalledProcessError(1, command)
                with self.subTest(child_fails=child_fails), \
                        mock.patch.object(os, 'environ', dict(environment, SIGNING_PRIVATE_KEY='synthetic private key fixture')), \
                        mock.patch.object(subprocess, 'run', side_effect=assemble) as run:
                    if child_fails:
                        with self.assertRaises(subprocess.CalledProcessError):
                            exec(program, {})
                    else:
                        exec(program, {})
                    run.assert_called_once()
                    self.assertNotIn('SIGNING_PRIVATE_KEY', os.environ)
                self.assertEqual(len(keys), 1)
                self.assertFalse(keys[0].exists())
                self.assertEqual(list(runner_temp.iterdir()), [])
            with mock.patch.object(os, 'environ', dict(environment, PACKAGE_REPOSITORY='false', SIGNING_PRIVATE_KEY='')), \
                    mock.patch.object(subprocess, 'run') as run, \
                    mock.patch.object(tempfile, 'TemporaryDirectory') as private_directory:
                exec(program, {})
                run.assert_called_once_with([sys.executable, '.github/scripts/lifecycle.py', 'assemble'], check=True)
                private_directory.assert_not_called()
                self.assertNotIn('SIGNING_PRIVATE_KEY', os.environ)
            self.assertEqual(native_write.call_count, 0)
            self.assertIs(os.environ, original_environment)
            self.assertTrue(dict(original_environment) == before)

    def test_certification_restores_exact_frozen_payloads_once_and_keeps_diagnostics(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root/'.github/workflows/certify.yml').read_text()
        prepare = workflow.split('  prepare:\n', 1)[1].split('  check:\n', 1)[0]
        self.assertIn('qualification-metadata', prepare)
        self.assertNotIn('qualification-payloads', prepare)
        self.assertEqual(prepare.count('uses: ./.github/actions/ci-evidence-publish'), 1)
        self.assertIn('name: qualification-inputs-${{ github.run_attempt }}', prepare)
        self.assertIn('qualification-metadata-check', prepare)
        self.assertNotIn('build/candidate/dependencies/', prepare)
        self.assertNotIn('bundle-store', prepare)
        check = workflow.split('  check:\n', 1)[1].split('  record:\n', 1)[0]
        self.assertEqual(check.count("'fetch-published-check-inputs'"), 1)
        self.assertIn('CHECK_PAYLOADS: ${{ toJSON(matrix.payloads) }}', check)
        self.assertNotIn("'bundle-fetch'", check)
        self.assertNotIn("'fetch-check-payloads'", check)
        self.assertIn('    - if: always()\n      name: Retain verified evidence-', check)
        self.assertIn('paths: |-\n          build/evidence/\n          build/prerequisites/', check)
        self.assertIn('uses: ./.github/actions/ci-evidence-publish', check)
        self.assertIn('slot: ${{ strategy.job-index }}', check)
        self.assertNotIn('browser-prerequisite-', check)
        self.assertIn('      fail-fast: false', check)
        self.assertIn("'check-batch'", check)
        record = workflow.split('  record:\n',1)[1].split('  attach:\n',1)[0]
        self.assertIn("if: always() && needs.prepare.result == 'success'", record)
        self.assertEqual(record.count("'fetch-certification-evidence'"),1)
        self.assertIn('CHECK_BATCHES: ${{ needs.prepare.outputs.matrix }}',record)
        self.assertIn('build/candidate-remote.json',record)

    def test_nested_regression_receipt_fails_closed_and_does_not_repeat_work(self):
        root = Path(__file__).resolve().parents[1]
        latest = (root/'.github/workflows/_release-latest.yml').read_text()
        application = (root/'.github/workflows/sdk-application.yml').read_text()
        gate = latest.split('  regression:\n', 1)[1].split('  application:\n', 1)[0]
        code = gate.split('      run: |\n', 1)[1]
        code = '\n'.join(line[8:] for line in code.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory)/'summary.md'
            for app, result in (('failure', 'success'), ('success', 'failure'), ('success', 'cancelled'),
                                ('success', 'skipped'), ('success', '')):
                with mock.patch.dict(os.environ, {'APPLICATION_RESULT': app, 'REGRESSION_RESULT': result,
                                                  'GITHUB_STEP_SUMMARY': str(summary)}):
                    with self.assertRaises(SystemExit): exec(compile(code, 'regression-receipt', 'exec'), {})
            self.assertFalse(summary.exists())
            with mock.patch.dict(os.environ, {'APPLICATION_RESULT': 'success', 'REGRESSION_RESULT': 'success',
                                              'GITHUB_STEP_SUMMARY': str(summary)}):
                exec(compile(code, 'regression-receipt', 'exec'), {})
            self.assertIn('does not repeat regression', summary.read_text())
        outer_app = latest.split('  application:\n', 1)[1].split('  certification:\n', 1)[0]
        self.assertIn('    needs: prepare\n', outer_app)
        self.assertIn('      require_regression: true', outer_app)
        # Anchor the job inventory: an input such as build_jobs also ends in
        # "jobs:" and must never be interpreted as a workflow job boundary.
        nested = application.split('\njobs:\n', 1)[1].split('  prepare:\n', 1)[0]
        self.assertIn('uses: ./.github/workflows/candidate.yml', nested)
        self.assertIn('    needs: prepare\n', nested)
        self.assertNotIn('needs: application', nested)
        assembly = application.split('  assemble:\n', 1)[1].split('\nenv:\n', 1)[0]
        self.assertIn('needs: [prepare, application, regression]', assembly)
        self.assertIn("inputs.require_regression && needs.regression.result == 'success'", assembly)
        self.assertIn("!inputs.require_regression && needs.regression.result == 'skipped'", assembly)
        self.assertIn("environment: ${{ (inputs.execute || inputs.package_repository) && 'release-publisher' || '' }}", assembly)
        self.assertIn('group: foundation-release-lifecycle', assembly)
        self.assertIn('publish-candidate', assembly)
        self.assertIn('regression_result: ${{ needs.regression.result }}', assembly)
        self.assertIn('value: ${{ jobs.assemble.outputs.regression_result }}', application)
        self.assertNotIn('  publish:\n', application)
        self.assertIn('    - if: ${{ !inputs.execute }}\n      name: Retain candidate preparation controls', assembly)
        self.assertIn('          build/publication-request.json', assembly)
        self.assertIn('          build/publication-plan.json', assembly)
        self.assertNotIn('BUNDLE_OUTPUT: build\n', assembly)


if __name__ == '__main__': unittest.main()
