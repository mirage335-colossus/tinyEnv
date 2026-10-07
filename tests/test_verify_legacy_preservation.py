"""Independent retention checks use real transport archives and no network."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_legacy_preservation as V
import test_legacy_artifacts as fixtures


class VerificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='retention verification '); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.remote = fixtures.Remote()
        self.request = dict(artifact_id=75, sha256=V.delivery.sha(self.remote.payload),
            run_id=44, source_commit='b' * 40, name='old evidence', size=len(self.remote.payload))
        self.context = dict(repository='example/project', run_id=12, attempt=2, source_commit='a' * 40,
                            workflow='legacy-artifacts.yml')
        self.env = patch.dict(os.environ, {'RUNNER_NAME': 'Runner 1'}); self.env.start(); self.addCleanup(self.env.stop)
        self.requests = [self.request]

    def prepare(self, *, second=False, complete=True):
        if second:
            next_request = dict(self.request, artifact_id=76, name='second evidence')
            self.remote.artifacts[76] = dict(copy.deepcopy(self.remote.artifacts[75]), id=76, name='second evidence')
            self.requests.append(next_request)
        self.saved = V.legacy.preserve('example/project', self.requests, self.root / 'preserved', self.context,
            transport=self.remote, downloader=self.remote.legacy_download)
        if complete: self.remote.complete()
        self.before = len(self.remote.calls)
        return self.saved

    def verify(self, **kwargs):
        return V.verify('example/project', self.saved['pointer'], self.requests, self.root / 'verification',
                        transport=self.remote, **kwargs)

    def test_exact_bytes_provenance_and_all_pointers_without_extracting_opaque_zip(self):
        self.prepare(second=True); checkpoints = []
        def checkpoint(path):
            item = V.read_json(path); aid = item['request']['artifact_id']
            self.assertTrue((self.root / f'verification/archive-{aid}/archive.zip').exists())
            # Each earlier payload is gone before the next archive is inspected.
            self.assertEqual(len(list((self.root / 'verification').glob('archive-*'))), 1)
            checkpoints.append(aid); return {'durable': aid}
        result = self.verify(checkpoint=checkpoint)
        self.assertEqual(result['status'], 'passed'); self.assertEqual(checkpoints, [75, 76])
        self.assertEqual(result['total_bytes'], 2 * len(self.remote.payload)); self.assertEqual(result['artifact_count'], 2)
        self.assertEqual([row['pointer'] for row in result['artifacts']], [row['pointer'] for row in self.saved['preservation']['artifacts']])
        self.assertEqual([row['original_run_id'] for row in result['artifacts']], [44, 44])
        self.assertFalse(result['extracted']); self.assertFalse(result['publication_approved'])
        self.assertEqual(result['qualification'], 'not-assessed'); self.assertFalse(result['original_artifacts_deleted'])
        self.assertFalse(list((self.root / 'verification').glob('archive-*')))
        self.assertFalse(list(self.root.rglob('never-extract.sh')))
        self.assertEqual(set(self.remote.artifacts), {75, 76})
        self.assertFalse(any(c[0] in ('POST', 'PATCH', 'DELETE', 'upload') for c in self.remote.calls[self.before:]))
        self.assertEqual(V.read_json(self.root / 'verification/receipts/verification.json'), result)

    def test_strict_pointer_repository_workflow_manifest_and_types_before_outputs(self):
        self.prepare()
        for change in ({'repository': 'other/project'}, {'workflow': 'candidate.yml'}, {'job_id': True},
                       {'release_id': 0}, {'tag': 'other'}, {'name': 'other'}, {'schema_version': True}, {'extra': 1}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    V.verify('example/project', dict(self.saved['pointer'], **change), self.requests,
                             self.root / 'verification', transport=self.remote)
                self.assertFalse((self.root / 'verification').exists())
        broken = copy.deepcopy(self.saved['pointer']); broken['manifest']['sha256'] = 'invalid'
        with self.assertRaises(ValueError): V.pointer(broken, 'example/project')

    def test_current_completed_producer_required(self):
        self.prepare(complete=False)
        with self.assertRaisesRegex(ValueError, 'completion state'): self.verify()
        self.assertFalse((self.root / 'verification/receipts/verification.json').exists())
        self.assertFalse(list((self.root / 'verification').glob('archive-*')))

    def test_expected_selection_mismatch_fails_before_large_payload(self):
        self.prepare(); self.requests = [dict(self.request, name='wrong')]
        with self.assertRaisesRegex(ValueError, 'selection'): self.verify()
        self.assertFalse(list((self.root / 'verification').glob('archive-*')))

    def test_nested_bundle_from_other_job_rejected_before_archive_fetch(self):
        self.prepare(); original = V.fetch
        def fetch(p, output, files, **kwargs):
            result = original(p, output, files, **kwargs)
            if p['name'] == 'legacy-preservation':
                path = output / 'preservation.json'; value = V.read_json(path)
                value['artifacts'][0]['pointer']['job_id'] += 1; path.write_bytes(V.archive.encoded(value))
            return result
        with patch.object(V, 'fetch', side_effect=fetch), self.assertRaisesRegex(ValueError, 'exact preservation producer'):
            self.verify()
        self.assertFalse(list((self.root / 'verification').glob('archive-*')))

    def test_independent_hash_failure_keeps_payload_and_has_no_completed_receipt(self):
        self.prepare(); original = V.fetch
        def fetch(p, output, files, **kwargs):
            result = original(p, output, files, **kwargs)
            if p['name'].startswith('legacy-artifact-'):
                path = output / 'archive.zip'; raw = path.read_bytes(); path.write_bytes(b'X' + raw[1:])
            return result
        with patch.object(V, 'fetch', side_effect=fetch), self.assertRaisesRegex(ValueError, 'independent archive'):
            self.verify()
        self.assertTrue((self.root / 'verification/archive-75/archive.zip').exists())
        self.assertFalse((self.root / 'verification/receipts/artifact-75.json').exists())
        self.assertFalse((self.root / 'verification/receipts/verification.json').exists())

    def test_later_failure_preserves_prior_durable_receipt_and_failed_staging(self):
        self.prepare(second=True); checkpoints = []
        def checkpoint(path):
            aid = V.read_json(path)['request']['artifact_id']
            if aid == 76: raise RuntimeError('receipt upload response lost')
            checkpoints.append(aid); return {'verified_artifact': aid}
        with self.assertRaisesRegex(RuntimeError, 'response lost'): self.verify(checkpoint=checkpoint)
        self.assertEqual(checkpoints, [75]); out = self.root / 'verification'
        self.assertFalse((out / 'archive-75').exists()); self.assertTrue((out / 'archive-76/archive.zip').exists())
        self.assertTrue((out / 'receipts/checkpoint-75.json').exists())
        self.assertFalse((out / 'receipts/checkpoint-76.json').exists())
        self.assertFalse((out / 'receipts/verification.json').exists())

    def test_local_receipt_save_failure_prevents_cleanup(self):
        self.prepare(); original = V.durable
        def save(path, value):
            if path.name == 'artifact-75.json': raise OSError('receipt flush failed')
            return original(path, value)
        with patch.object(V, 'durable', side_effect=save), self.assertRaisesRegex(OSError, 'flush'):
            self.verify()
        self.assertTrue((self.root / 'verification/archive-75/archive.zip').exists())

    def test_changed_manifest_asset_identity_fails_before_bundle_transfer(self):
        self.prepare(); self.saved['pointer']['manifest']['id'] += 1
        with self.assertRaisesRegex(ValueError, 'pinned preservation manifest'): self.verify()
        self.assertFalse((self.root / 'verification/inventory').exists())

    def test_original_provenance_rejects_foreign_repository_and_false_qualification(self):
        self.prepare(); row = self.saved['preservation']['artifacts'][0]
        fetched = self.root / 'source'; V.fetch(row['pointer'], fetched, {'archive.zip': self.request['size'], 'origin.json': None}, transport=self.remote)
        value = V.read_json(fetched / 'origin.json')
        self.assertEqual(V.origin(value, self.request, 'example/project', 7)['run']['id'], 44)
        for field, replacement in (('extracted', True), ('publication_approved', True), ('qualification', 'passed')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                V.origin(dict(value, **{field: replacement}), self.request, 'example/project', 7)
        wrong = copy.deepcopy(value); wrong['original']['artifact']['workflow_run']['head_repository_id'] = 8
        with self.assertRaises(ValueError): V.origin(wrong, self.request, 'example/project', 7)
        with self.assertRaisesRegex(ValueError, 'repository ID'): V.origin(value, self.request, 'example/project', 8)

    def test_existing_output_is_never_overwritten(self):
        self.prepare(); out = self.root / 'verification'; out.mkdir(); (out / 'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'new owned'): self.verify()
        self.assertEqual((out / 'keep').read_bytes(), b'keep')

    def test_cli_retains_only_small_receipts_and_final_pointer(self):
        self.prepare(); original_verify = V.verify; calls = []; out = self.root / 'cli'
        def verify(*args, **kwargs):
            return original_verify(*args, **kwargs, transport=self.remote)
        def publish(**kwargs):
            calls.append(kwargs)
            self.assertEqual(kwargs['workflow'], 'verify-retention.yml')
            self.assertTrue(all(name.endswith('.json') for name in kwargs['paths']))
            self.assertNotIn('archive.zip', kwargs['paths'])
            return {'stored_receipt': kwargs['name']}
        environment = dict(PRESERVATION_POINTER=json.dumps(self.saved['pointer']), LEGACY_ARTIFACTS=json.dumps(self.requests),
            GITHUB_REPOSITORY='example/project', GITHUB_RUN_ID='99', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='c' * 40,
            GITHUB_OUTPUT=str(self.root / 'outputs'), GITHUB_STEP_SUMMARY=str(self.root / 'summary'))
        with patch.dict(os.environ, environment), patch.object(V, 'verify', side_effect=verify), \
                patch.object(V.bundles, 'publish_bundle', side_effect=publish):
            V.main(['--output', str(out)])
        self.assertEqual([call['name'] for call in calls], ['retention-check-artifact-75', 'legacy-verification'])
        self.assertIn('verification.json', calls[-1]['paths'])
        self.assertIn('pointer=', (self.root / 'outputs').read_text())
        self.assertEqual(V.read_json(out / 'pointer.json'), {'stored_receipt': 'legacy-verification'})

    def test_workflow_has_only_explicit_small_receipt_transport_and_no_deletion(self):
        text = (ROOT / '.github/workflows/verify-retention.yml').read_text()
        self.assertIn('workflow_dispatch:', text); self.assertIn('contents: write', text); self.assertIn('actions: read', text)
        self.assertIn('PRESERVATION_POINTER: ${{ inputs.pointer }}', text)
        self.assertIn('LEGACY_ARTIFACTS: ${{ inputs.artifacts }}', text)
        self.assertNotIn('upload-artifact', text); self.assertNotIn('download-artifact', text); self.assertNotIn('DELETE', text)


if __name__ == '__main__': unittest.main()
