"""Historical native evidence requires independent authenticated provenance."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ci_artifacts as artifacts
import ci_retry as retry
import coverage
import dependency_archive as archive

spec = importlib.util.spec_from_file_location('retry_lifecycle', ROOT / '.github/scripts/lifecycle.py')
lifecycle = importlib.util.module_from_spec(spec); spec.loader.exec_module(lifecycle)


class RetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.context = dict(repository='example/project', run_id=123, attempt=3,
                            source_commit='a' * 40, workflow='certify.yml')
        self.env = patch.dict(os.environ, dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='example/project',
            GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='3', GITHUB_SHA='a' * 40,
            GITHUB_WORKFLOW_REF='example/project/.github/workflows/certify.yml@refs/heads/main'))
        self.env.start(); self.addCleanup(self.env.stop)
        self.repo = dict(id=5, full_name='example/project')
        self.batch = 'batch-linux-source-012345abcdef'
        self.jobs = {1: [], 2: [self.job()], 3: []}
        self.rows = []; self.downloads = {}; self.calls = []
        self.overrides = {}

    def job(self, attempt=2, role='check'):
        return dict(id=456 + attempt, run_id=123, run_attempt=attempt, head_sha='a' * 40,
            name='certification / ' + ('Qualify ' + self.batch if role == 'check' else role),
            runner_id=8, runner_name='runner-7', status='completed', conclusion='success',
            started_at='2026-10-03T01:00:00Z', completed_at='2026-10-03T01:01:00Z')

    def json(self, endpoint):
        self.calls.append(endpoint)
        if endpoint in self.overrides: return copy.deepcopy(self.overrides[endpoint])
        base = 'repos/example/project'
        if endpoint == base: return copy.deepcopy(self.repo)
        if '/attempts/' in endpoint:
            attempt = int(endpoint.split('/attempts/')[1].split('/')[0])
            if '/jobs?' in endpoint: return dict(total_count=len(self.jobs[attempt]), jobs=copy.deepcopy(self.jobs[attempt]))
            return dict(id=123, run_attempt=attempt, head_sha='a' * 40, path='.github/workflows/certify.yml',
                        event='workflow_dispatch', repository=self.repo, head_repository=self.repo)
        if '/actions/jobs/' in endpoint:
            return copy.deepcopy(next(job for rows in self.jobs.values() for job in rows if job['id'] == int(endpoint.rsplit('/', 1)[1])))
        if '/artifacts?' in endpoint: return dict(total_count=len(self.rows), artifacts=copy.deepcopy(self.rows))
        if '/actions/artifacts/' in endpoint:
            return copy.deepcopy(next(row for row in self.rows if row['id'] == int(endpoint.rsplit('/', 1)[1])))
        raise AssertionError(endpoint)

    def download(self, repository, identity, output):
        self.assertEqual(repository, self.context['repository'])
        shutil.copyfile(self.downloads[identity], output)

    def reader(self): return retry.EarlierAttempts(self.context, transport=self, download=self.download)

    def artifact(self, *, attempt=2, role='check', slot='evidence-00', change=None, files=None):
        name = ('evidence-' + self.batch if role == 'check' else 'qualification-inputs' if role == 'prepare' else 'certificate') + '-' + str(attempt)
        source = self.root / ('source-' + str(len(self.rows))); source.mkdir()
        for path, content in (files or {'evidence/result.json': b'{"status":"passed"}\n'}).items():
            target = source / path; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
        selected = dict(self.context, attempt=attempt)
        prepared = artifacts.prepare(**selected, name=name, root=source, paths=list(files or {'evidence': ''}),
            output=self.root / ('stage-' + str(len(self.rows))), slot=int(slot[-2:]) if slot.startswith('evidence-') else None,
            job_key=role, runner_name='runner-7')
        stage = Path(prepared['path'])
        if change: change(stage)
        zipped = self.root / ('artifact-' + str(len(self.rows)) + '.zip')
        with zipfile.ZipFile(zipped, 'w') as output:
            for path in stage.iterdir(): output.write(path, path.name)
        identity = 900 + len(self.rows)
        row = dict(id=identity, name=prepared['artifact_name'], expired=False, digest='sha256:' + archive.digest(zipped),
            size_in_bytes=zipped.stat().st_size, created_at='2026-10-03T01:00:30Z',
            workflow_run=dict(id=123, head_sha='a' * 40, repository_id=5, head_repository_id=5))
        self.rows.append(row); self.downloads[identity] = zipped
        return name, row

    def restore(self, reader=None, **kwargs):
        return (reader or self.reader()).restore(2, 'evidence-' + self.batch + '-2', 'evidence-00',
            self.root / 'restored', role='check', batch=self.batch, **kwargs)

    def test_restores_original_bytes_and_retains_immutable_identity(self):
        name, row = self.artifact()
        receipt = self.restore()
        self.assertEqual(receipt['attempt'], 2)
        self.assertEqual(receipt['artifact']['id'], row['id'])
        self.assertEqual(receipt['artifact']['sha256'], row['digest'][7:])
        self.assertEqual((self.root / 'restored/evidence/result.json').read_text(), '{"status":"passed"}\n')
        self.assertEqual(receipt['producer']['id'], 458)
        with self.assertRaisesRegex(ValueError, 'existing file'): self.restore()

    def test_original_control_and_certificate_have_exact_roles(self):
        for role, slot in [('prepare', 'qualification-inputs'), ('record', 'certificate')]:
            with self.subTest(role=role):
                self.jobs[2] = [self.job(role=role)]
                name, _ = self.artifact(role=role, slot=slot)
                result = self.reader().restore(2, name, slot, self.root / role, role=role)
                self.assertEqual(result['producer']['name'], 'certification / ' + role)

    def test_current_context_and_attempt_bounds_are_mandatory(self):
        for text in ('0', '-1', '03', 'true', '4', '3\n'):
            with self.subTest(text=text), self.assertRaises(ValueError): retry.origin_attempt(text, 3)
        with self.assertRaises(ValueError): retry.origin_attempt('1', 65)
        with self.assertRaises(ValueError): retry.EarlierAttempts(dict(self.context, source_commit='b' * 40), transport=self)
        with self.assertRaises(ValueError): self.reader().restore(3, 'certificate-3', 'certificate', self.root / 'none', role='record')

    def test_latest_execution_selected_without_repeating_remote_inventories(self):
        reader = self.reader()
        self.assertEqual(reader.select_batch(self.batch), 2)
        self.assertEqual(reader.select_batch(self.batch), 2)
        self.assertEqual(sum('/attempts/2/jobs?' in endpoint for endpoint in self.calls), 1)

    def test_current_missing_artifact_never_falls_back(self):
        self.jobs[3] = [self.job(attempt=3)]
        with self.assertRaisesRegex(ValueError, 'current batch artifact missing'): self.reader().select_batch(self.batch)

    def test_failed_cancelled_incomplete_or_ambiguous_producer_never_falls_back(self):
        self.jobs[1] = [self.job(attempt=1)]
        for field, value in [('conclusion', 'failure'), ('conclusion', 'cancelled'), ('status', 'in_progress'),
                             ('head_sha', 'b' * 40), ('run_attempt', 1), ('run_id', 999), ('runner_id', 0)]:
            with self.subTest(field=field, value=value):
                original = self.jobs[2][0]; self.jobs[2][0] = dict(original, **{field: value})
                with self.assertRaises(ValueError): self.reader().select_batch(self.batch)
                self.jobs[2][0] = original
        self.jobs[2].append(dict(self.jobs[2][0], id=900))
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.reader().select_batch(self.batch)

    def test_missing_all_producers_rejected(self):
        self.jobs[2] = []
        with self.assertRaisesRegex(ValueError, 'no completed'): self.reader().select_batch(self.batch)

    def test_repository_workflow_source_and_attempt_must_match(self):
        endpoint = 'repos/example/project/actions/runs/123/attempts/2'
        good = self.json(endpoint)
        for field, value in [('head_sha', 'b' * 40), ('path', '.github/workflows/other.yml'), ('run_attempt', 1),
                             ('event', 'pull_request'), ('repository', dict(id=6, full_name='example/project'))]:
            with self.subTest(field=field):
                self.overrides[endpoint] = dict(good, **{field: value})
                with self.assertRaises(ValueError): self.reader().select_batch(self.batch)
        self.overrides.clear()

    def test_artifact_identity_and_creation_interval_must_match(self):
        _, row = self.artifact(); original = copy.deepcopy(row)
        for field, value in [('expired', True), ('digest', None), ('digest', 'sha256:' + '0' * 64),
                             ('size_in_bytes', 0), ('created_at', '2026-10-03T00:00:00Z'),
                             ('created_at', '2026-10-03T01:00:30'), ('name', 'different'),
                             ('workflow_run', dict(original['workflow_run'], head_repository_id=6))]:
            with self.subTest(field=field):
                row.clear(); row.update(copy.deepcopy(original)); row[field] = value
                with self.assertRaises(ValueError): self.restore()
                self.assertFalse((self.root / 'restored').exists())
        row.clear(); row.update(original)
        self.rows.append(dict(row, id=999))
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.restore()

    def test_original_manifest_producer_and_payload_validated(self):
        for field, value in [('attempt', 1), ('source_commit', 'b' * 40),
                             ('producer', dict(job_key='record', runner_name='runner-7', outcome='success')),
                             ('producer', dict(job_key='check', runner_name='other', outcome='success')),
                             ('producer', dict(job_key='check', runner_name='runner-7', outcome='failure'))]:
            with self.subTest(field=field):
                def change(stage):
                    path = stage / 'manifest.json'; document = json.loads(path.read_text()); document[field] = value
                    path.write_bytes(archive.encoded(document))
                self.rows.clear(); self.downloads.clear()
                # Each iteration owns a new temporary namespace.
                old = self.root; self.root = old / ('case-' + str(len(list(old.iterdir())))); self.root.mkdir()
                self.artifact(change=change)
                with self.assertRaises(ValueError): self.restore()
                self.root = old

    def test_archive_bytes_and_unexpected_zip_member_rejected(self):
        for mutation in (lambda stage: (stage / 'payload.tar.gz').write_bytes(b'changed'),
                         lambda stage: (stage / 'unexpected').write_text('extra')):
            with self.subTest(mutation=mutation):
                old = self.root; self.root = old / str(len(list(old.iterdir()))); self.root.mkdir()
                self.rows.clear(); self.artifact(change=mutation)
                with self.assertRaises(ValueError): self.restore()
                self.assertFalse((self.root / 'restored').exists()); self.root = old

    def test_remote_artifact_or_producer_change_during_download_rejected(self):
        _, row = self.artifact()
        self.overrides['repos/example/project/actions/artifacts/900'] = dict(row, expired=True)
        with self.assertRaisesRegex(ValueError, 'changed during retrieval'): self.restore()
        self.assertFalse((self.root / 'restored').exists())
        self.overrides.clear()
        self.overrides['repos/example/project/actions/jobs/458'] = dict(self.jobs[2][0], conclusion='failure')
        with self.assertRaises(ValueError): self.restore()
        self.assertFalse((self.root / 'restored').exists())

    def test_current_local_artifacts_remain_exact_attempt_only(self):
        name, _ = self.artifact()
        with patch.dict(os.environ, {artifacts.ROOT_ENV: str(self.root)}), self.assertRaisesRegex(ValueError, 'exact current'):
            artifacts.fetch_local(dict(self.context, attempt=2, name=name), dict(name=name), self.root / 'output')

    def test_workflow_keeps_original_control_and_certificate_attempts(self):
        text = (ROOT / '.github/workflows/certify.yml').read_text()
        self.assertIn('control_attempt: ${{ steps.origin.outputs.attempt }}', text)
        self.assertIn('CONTROL_ATTEMPT: ${{ needs.prepare.outputs.control_attempt }}', text)
        self.assertIn('CERTIFICATE_ATTEMPT: ${{ needs.record.outputs.certification_attempt }}', text)
        self.assertIn('CERTIFICATE_SHA256: ${{ needs.record.outputs.certificate_sha256 }}', text)
        self.assertNotIn('overwrite: true', text)

    def test_original_controls_do_not_use_current_fast_path(self):
        with patch.object(lifecycle, 'ROOT', self.root), patch.dict(os.environ, CONTROL_ATTEMPT='2'), \
                patch.object(lifecycle, 'fetch_bundle') as current, patch.object(lifecycle, 'write'), \
                patch.object(lifecycle.ci_retry, 'EarlierAttempts') as historical:
            lifecycle.restore_controls()
            current.assert_not_called()
            historical.return_value.restore.assert_called_once_with(2, 'qualification-inputs-2',
                'qualification-inputs', self.root / 'build', role='prepare')

    def test_attachment_restores_exact_original_certificate_and_verifies_hash(self):
        build = self.root / 'build'; build.mkdir(); certificate = build / 'certificate.json'; certificate.write_text('{}')
        with patch.object(lifecycle, 'ROOT', self.root), patch.dict(os.environ,
                CERTIFICATE_ATTEMPT='2', CERTIFICATE_SHA256=coverage.sha(certificate)), \
                patch.object(lifecycle, 'write'), patch.object(lifecycle, 'fetch_bundle') as current, \
                patch.object(lifecycle.ci_retry, 'EarlierAttempts') as historical:
            lifecycle.fetch_certificate(); current.assert_not_called()
            historical.return_value.restore.assert_called_once_with(2, 'certificate-2', 'certificate', build, role='record')
            certificate.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'exact successful record'): lifecycle.fetch_certificate()


    def collector_fixture(self):
        import platform
        target = platform.system().lower() + '-' + {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine().lower(), platform.machine().lower())
        source = self.root / 'input.txt'; source.write_text('frozen source')
        base = dict(scope='source', target=target, environment='fixture', backend='core', required=True,
                    argv=['{python}', '-c', "print('checked')"], timeout_seconds=5, warning_seconds=4, expected_tests=[])
        plan = coverage.freeze(dict(schema_version=1, mode='release', subject=dict(source_sha256='a'*64,
            inventory_sha256='b'*64, configuration_sha256='c'*64), inputs={'input.txt': coverage.sha(source)},
            checks=[dict(base, id='earlier'), dict(base, id='current')]))
        original = self.root / 'original'; current = self.root / 'current'
        coverage.run_case(plan, 'earlier', self.root, original / 'evidence/earlier', '123', 2)
        coverage.run_case(plan, 'current', self.root, current / 'evidence/current', '123', 3)
        # These are retained evidence bytes, including their original newline encoding.
        files = {path.relative_to(original).as_posix(): path.read_bytes() for path in original.rglob('*') if path.is_file()}
        self.artifact(files=files)
        other = 'batch-linux-source-abcdef012345'
        prepared = artifacts.prepare(**self.context, name='evidence-' + other + '-3', root=current,
            paths=['evidence'], output=self.root / 'native-stage', slot=1, job_key='check', runner_name='runner-7')
        downloads = self.root / 'current-downloads'; downloads.mkdir()
        shutil.copytree(prepared['path'], downloads / prepared['artifact_name'])
        build = self.root / 'build'; build.mkdir(); (build / 'candidate').mkdir()
        coverage.write_new(build / 'check-plan.json', plan)
        coverage.write_new(build / 'delivery.json', {})
        coverage.write_new(build / 'candidate-remote.json', {})
        matrix = {'include': [dict(id=self.batch, checks=['earlier']), dict(id=other, checks=['current'])]}
        return plan, matrix, downloads, (original / 'evidence/earlier/result.json').read_bytes()

    def test_collector_combines_real_prior_and_current_receipts_without_rewriting(self):
        plan, matrix, downloads, original = self.collector_fixture()
        reader = self.reader(); real_module = lifecycle.ci.module
        with patch.object(lifecycle, 'ROOT', self.root), patch.dict(os.environ, CONTROL_ATTEMPT='2',
                CHECK_BATCHES=json.dumps(matrix), TAG='candidate', INVENTORY='b'*64,
                FOUNDATION_CI_ARTIFACTS_DIR=str(downloads), FOUNDATION_CI_ARTIFACTS_REQUIRED='true'), \
                patch.object(lifecycle, 'restore_controls'), patch.object(lifecycle, 'selected_runners', return_value={}), \
                patch.object(lifecycle.ci, 'qualification_batches', return_value=matrix), \
                patch.object(lifecycle.ci_retry, 'EarlierAttempts', return_value=reader), \
                patch.object(lifecycle.ci, 'fetch_candidate_payloads') as payloads, \
                patch.object(lifecycle.ci, 'module', side_effect=lambda name: SimpleNamespace(verify_metadata=lambda _: {}) if name == 'release' else real_module(name)):
            lifecycle.fetch_certification_evidence()
            self.assertIsNone(payloads.call_args.kwargs['trusted_context'])
            self.assertEqual(payloads.call_args.args[7], ['earlier'])
        reports = [coverage.result_path(plan, item['id'], self.root / 'build/evidence') for item in plan['checks']]
        adopted = coverage.load(self.root / 'build/adoption.json')
        result = coverage.merge(plan, reports, adoption=adopted)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['checks']['earlier']['attempt'], 2)
        self.assertEqual(result['checks']['current']['attempt'], 3)
        self.assertEqual(reports[0].read_bytes(), original)
        self.assertEqual(set(adopted['results']), {'earlier'})
        (self.root / 'input.txt').write_text('changed source')
        with self.assertRaisesRegex(ValueError, 'check input changed'):
            coverage.adopt(plan, reports[:1], self.root, '123', 3)

    def test_collector_rejects_changed_frozen_matrix_before_batch_download(self):
        plan, matrix, downloads, _ = self.collector_fixture()
        reader = self.reader(); real_module = lifecycle.ci.module
        with patch.object(lifecycle, 'ROOT', self.root), patch.dict(os.environ, CONTROL_ATTEMPT='2',
                CHECK_BATCHES=json.dumps(matrix), FOUNDATION_CI_ARTIFACTS_DIR=str(downloads)), \
                patch.object(lifecycle, 'restore_controls'), patch.object(lifecycle, 'selected_runners', return_value={}), \
                patch.object(lifecycle.ci, 'qualification_batches', return_value={'include': []}), \
                patch.object(lifecycle.ci_retry, 'EarlierAttempts', return_value=reader), \
                patch.object(lifecycle.ci, 'module', side_effect=lambda name: SimpleNamespace(verify_metadata=lambda _: {}) if name == 'release' else real_module(name)), \
                patch.object(reader, 'restore') as restore, self.assertRaisesRegex(ValueError, 'complete frozen'):
            lifecycle.fetch_certification_evidence()
        restore.assert_not_called()


if __name__ == '__main__': unittest.main()
