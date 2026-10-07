"""Actual signed local channel fixtures and mocked immutable remote lifecycle."""
import copy
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import distribution_release as d
import test_github_release as fixtures


def request():
    return dict(schema_version=1, repository='example/project', application_tag='v1', inventory_sha256='a' * 64,
        profile='fixture', certificate_run='qualification-run', certificate_attempt=1, certificate_sha256='b' * 64,
        target='linux-x86_64', version='1.2.3', package_release=1, sequence=7, valid_days=30,
        trusted_fingerprint='A' * 40, license_files=['share/doc/Foundation/LICENSE'],
        runtime_dependencies={'arch': ['glibc>=2.36'], 'gentoo': ['>=sys-libs/glibc-2.36']}, packager_commit='a' * 40)


def git_fixture(root, algorithm='sha1'):
    root.mkdir(); (root / 'a').mkdir()
    (root / 'a/z').write_bytes(b'checkout source\n'); (root / 'a.c').write_bytes(b'lexical tree order\n')
    (root / 'script').write_bytes(b'#!/bin/sh\nexit 0\n'); (root / 'script').chmod(0o755)
    args = ['git', '-C', str(root), '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false']
    subprocess.run([*args, 'init', '--quiet', '--object-format=' + algorithm], check=True, capture_output=True)
    subprocess.run([*args, 'add', '.'], check=True, capture_output=True)
    subprocess.run([*args, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '--quiet', '-m', 'Fixture'], check=True, capture_output=True)
    return subprocess.run([*args, 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.transport=fixtures.FakeGitHub()
        self.remote=d.delivery.Remote('example/project',self.transport)
        self.tag='distro-fixture';self.commit='a'*40;self.body='exact body'
        self.sleep=patch.object(d.delivery.time,'sleep');self.sleeps=self.sleep.start();self.addCleanup(self.sleep.stop)

    def initialize(self):
        return d.initialize_channel(self.remote,self.tag,self.commit,self.body)

    def release_posts(self):
        return [c for c in self.transport.calls if c[:2]==('POST','repos/example/project/releases')]

    def test_orphan_matching_tag_never_authorizes_creation(self):
        self.transport.refs[self.tag]=self.commit
        with self.assertRaisesRegex(ValueError,'not visible'):self.initialize()
        self.assertEqual([],self.release_posts());self.assertFalse(self.transport.releases)

    def test_successful_creation_waits_for_exact_visible_id(self):
        original=self.transport.json;remaining=3;reads=[]
        def delayed(endpoint,**kwargs):
            nonlocal remaining
            result=original(endpoint,**kwargs)
            if endpoint=='repos/example/project/releases/1':
                reads.append(kwargs)
                if remaining:remaining-=1;return None
            return result
        with patch.object(self.transport,'json',side_effect=delayed), \
                patch.object(self.transport,'pages',side_effect=AssertionError('unrelated inventory')):
            result=self.initialize()
        self.assertEqual(0,remaining);self.assertEqual([{'missing':True}]*4,reads)
        self.assertEqual([.25,.5,1],[c.args[0] for c in self.sleeps.call_args_list])
        self.assertEqual(1,result['id']);self.assertEqual(1,len(self.release_posts()))

    def test_uncertain_ref_response_grants_no_creation(self):
        original=self.transport.json
        def lost(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if endpoint.endswith('/git/refs') and kwargs.get('method')=='POST':
                raise d.delivery.DeliveryError('uncertain reference creation',True)
            return result
        with patch.object(self.transport,'json',side_effect=lost),self.assertRaisesRegex(ValueError,'not visible'):
            self.initialize()
        self.assertEqual(self.commit,self.transport.refs[self.tag]);self.assertEqual([],self.release_posts())

    def test_lost_creation_response_reconciles_without_second_post(self):
        original=self.transport.json
        def lost(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if endpoint.endswith('/releases') and kwargs.get('method')=='POST':
                raise d.delivery.DeliveryError('uncertain draft creation',True)
            return result
        with patch.object(self.transport,'json',side_effect=lost):result=self.initialize()
        self.assertEqual(1,result['id']);self.assertEqual(1,len(self.release_posts()))

    def test_two_initializers_only_atomic_ref_winner_creates_draft(self):
        original=self.remote.change;entered=False;winner=[]
        def race(endpoint,**kwargs):
            nonlocal entered
            if endpoint=='/git/refs' and not entered:
                entered=True;winner.append(self.initialize())
                raise d.delivery.DeliveryError('reference already exists')
            return original(endpoint,**kwargs)
        with patch.object(self.remote,'change',side_effect=race):result=self.initialize()
        self.assertEqual(winner[0]['id'],result['id']);self.assertEqual(1,len(self.release_posts()))

    def test_unknown_creation_response_id_exhausts_only_bounded_exact_reads(self):
        original=self.transport.json;reads=[]
        def changed(endpoint,**kwargs):
            if endpoint=='repos/example/project/releases/101':reads.append(kwargs)
            result=original(endpoint,**kwargs)
            if endpoint.endswith('/releases') and kwargs.get('method')=='POST':result['id']+=100
            return result
        with patch.object(self.transport,'json',side_effect=changed), \
                patch.object(self.transport,'pages',side_effect=AssertionError('inventory fallback')), \
                self.assertRaisesRegex(ValueError,'release is not visible; preserve initialization state'):
            self.initialize()
        self.assertEqual([{'missing':True}]*7,reads)
        self.assertEqual([.25,.5,1,2,4,8],[c.args[0] for c in self.sleeps.call_args_list])
        self.assertEqual(1,len(self.release_posts()))
        self.assertEqual([1],[r['id'] for r in self.transport.releases])
        self.assertEqual(self.commit,self.transport.refs[self.tag])
        self.assertTrue(self.transport.releases[0]['draft'])
        self.assertEqual([],self.transport.releases[0]['assets'])
        self.assertFalse(any(c[0]=='upload' for c in self.transport.calls))

    def test_wrong_observed_id_is_rejected_without_retry_or_creation_replay(self):
        original=self.transport.json;reads=[]
        def changed(endpoint,**kwargs):
            result=original(endpoint,**kwargs)
            if endpoint=='repos/example/project/releases/1':
                reads.append(kwargs);result['id']+=100
            return result
        with patch.object(self.transport,'json',side_effect=changed), \
                patch.object(self.transport,'pages',side_effect=AssertionError('inventory fallback')), \
                self.assertRaisesRegex(ValueError,'observed release ID differs from creation response'):
            self.initialize()
        self.assertEqual([{'missing':True}],reads);self.sleeps.assert_not_called()
        self.assertEqual(1,len(self.release_posts()))
        self.assertEqual([1],[r['id'] for r in self.transport.releases])
        self.assertEqual([],self.transport.releases[0]['assets'])
        self.assertFalse(any(c[0]=='upload' for c in self.transport.calls))

    def test_duplicate_matching_tag_drafts_are_rejected_without_creation_replay(self):
        self.initialize()
        self.transport.releases.append(dict(self.transport.releases[0],id=99))
        with self.assertRaisesRegex(ValueError,'duplicate release tags'):self.initialize()
        self.assertEqual(1,len(self.release_posts()));self.sleeps.assert_not_called()
        self.assertEqual([[],[]],[r['assets'] for r in self.transport.releases])
        self.assertFalse(any(c[0]=='upload' for c in self.transport.calls))


class ParallelUploadTests(unittest.TestCase):
    def test_payloads_are_bounded_and_controls_wait_for_all_payloads(self):
        active = 0; maximum = 0; completed = set(); lock = threading.Lock()
        barrier = threading.Barrier(4)
        names = [f'payload-{i}' for i in range(8)]
        class Remote:
            def upload(self, tag, path):
                nonlocal active, maximum
                name = path.name
                with lock:
                    active += 1; maximum = max(maximum, active)
                    if name in d.CONTROL:
                        self_check.assertEqual(set(names), completed - d.CONTROL)
                if name not in d.CONTROL:
                    barrier.wait(timeout=5)
                with lock:
                    completed.add(name); active -= 1
        self_check = self
        d.upload_files(Remote(), 'tag', '/unused', [*names, *sorted(d.CONTROL)])
        self.assertEqual(4, maximum)
        self.assertEqual(set(names) | d.CONTROL, completed)
        self.assertEqual(0, active)

    def test_failed_batch_joins_workers_and_prevents_later_payloads_and_controls(self):
        completed = set(); barrier = threading.Barrier(4); lock = threading.Lock()
        class Remote:
            def upload(self, tag, path):
                name = path.name
                barrier.wait(timeout=5)
                with lock: completed.add(name)
                if name == 'payload-0': raise d.delivery.DeliveryError('lost upload response')
        with self.assertRaisesRegex(d.delivery.DeliveryError, 'lost upload response'):
            d.upload_files(Remote(), 'tag', '/unused', [f'payload-{i}' for i in range(8)] + sorted(d.CONTROL))
        self.assertEqual({f'payload-{i}' for i in range(4)}, completed)

    def test_known_release_id_avoids_tag_lookup_and_keeps_controls_last(self):
        calls = []; info = {'id': 37}; owner = self
        class Remote:
            def upload_to(self, actual, path):
                owner.assertIs(actual, info); calls.append(path.name)
            def upload(self, *args):
                raise AssertionError('unexpected tag lookup')
        d.upload_files(Remote(), 'tag', '/unused', ['payload', *sorted(d.CONTROL)], release_info=info)
        self.assertEqual(calls[0], 'payload')
        self.assertEqual(set(calls[1:]), d.CONTROL)

    def test_duplicate_assets_fail_before_upload(self):
        with patch.object(d.delivery.Remote, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, 'distinct'):
                d.upload_files(d.delivery.Remote('example/project'), 'tag', '/unused', ['a', 'a'])
            upload.assert_not_called()


class RequestTests(unittest.TestCase):
    def test_workflow_retains_complete_large_notice_inventory(self):
        value = request()
        value['license_files'] = ['share/doc/Foundation/dependencies/' + str(i) + '/COPYING.txt' for i in range(400)]
        raw = json.dumps(value, separators=(',', ':'))
        self.assertGreater(len(raw.encode('utf-8')), 16 * 1024)
        self.assertEqual(value, d.workflow_request(raw))

    def test_workflow_request_exact_byte_bound_precedes_parsing(self):
        raw = json.dumps(request(), separators=(',', ':'))
        bounded = raw + ' ' * (d.MAX_WORKFLOW_REQUEST_BYTES - len(raw.encode('utf-8')))
        self.assertEqual(request(), d.workflow_request(bounded))
        for excessive in (bounded + ' ', 'é' * (d.MAX_WORKFLOW_REQUEST_BYTES // 2 + 1), None):
            with self.subTest(value_type=type(excessive)), patch.object(d.delivery, 'parse', side_effect=AssertionError('must reject before parse')):
                with self.assertRaisesRegex(ValueError, 'input bound'):
                    d.workflow_request(excessive)
        utf8_boundary = 'é' * (d.MAX_WORKFLOW_REQUEST_BYTES // 2)
        with patch.object(d.delivery, 'parse', return_value=request()) as parse:
            self.assertEqual(request(), d.workflow_request(utf8_boundary))
            parse.assert_called_once_with(utf8_boundary)

    def test_workflow_request_preserves_json_and_semantic_validation(self):
        raw = json.dumps(request())
        for invalid in (raw[:-1] + ',"sequence":8}', '{}', json.dumps(dict(request(), sequence=True))):
            with self.subTest(raw=invalid), self.assertRaises(ValueError):
                d.workflow_request(invalid)

    def test_plan_has_no_remote_or_signing_side_effect(self):
        with patch.object(d.delivery, 'Remote', side_effect=AssertionError('no network')):
            result = d.plan(request())
        self.assertFalse(result['execute']); self.assertEqual('distro-1.2.3-x86_64-r1-s7', result['tag'])

    def test_exact_request_rejects_injection_unknown_fields_and_unsupported_targets(self):
        for changes in ({'target': 'windows-x86_64'}, {'version': '1.0;exit'}, {'sequence': True},
                        {'certificate_attempt': 0}, {'extra': 1}, {'repository': 'bad/repo/extra'},
                        {'license_files': ['../file']}, {'runtime_dependencies': {'arch': ['$(x)'], 'gentoo': ['glibc']}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): d.plan(dict(request(), **changes))

    def test_native_cli_fetch_and_verify_are_explicit(self):
        common = ['--policy', '/tmp/policy.json', '--trusted-fingerprint', 'A' * 40]
        with patch.object(d, 'fetch', return_value={}) as fetch, patch('builtins.print'):
            d.main(['fetch', '--repository', 'example/project', '--tag', 'channel',
                    '--manifest-sha256', 'a' * 64, '--output', '/tmp/assets', '--native-only', *common])
        self.assertTrue(fetch.call_args.kwargs['native_only'])
        with patch.object(d, 'verify_native', return_value={}) as verify, patch('builtins.print'):
            d.main(['verify', '--directory', '/tmp/assets', '--native-only', *common])
        verify.assert_called_once_with(Path('/tmp/assets'), Path('/tmp/policy.json'), 'A' * 40)
        with patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            d.main(['publish', '--native-only', *common])
        self.assertEqual(2, error.exception.code)

    def test_native_instructions_keep_legacy_rendering_available(self):
        self.assertNotIn(b'--native-only', d.instructions(request(), ['core']))
        current = d.instructions(request(), ['core'], native_only=True)
        self.assertIn(b'verify --native-only', current)
        self.assertIn(b'fetch --native-only', current)

    def test_private_key_inside_checkout_or_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); key = root / 'key'; key.write_bytes(b'private')
            with self.assertRaisesRegex(ValueError, 'outside'): d._key_outside(key, root)


@unittest.skipUnless(sys.platform.startswith('linux') and all(shutil.which(x) for x in ('cc', 'dpkg-deb', 'gpg', 'gpgv', 'gpgconf', 'git')),
                     'Linux ELF, Debian package and real signing tools required')
class SignedDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = fixtures.DeliveryTests(); cls.f.setUp(); cls.root = cls.f.root
        cls.addClassCleanup(cls.f.doCleanups)
        # Use a genuine native executable in one real installation root.
        cls.arch = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine().lower(), platform.machine().lower())
        if cls.arch not in ('x86_64', 'aarch64'): raise RuntimeError('unsupported Linux qualification architecture')
        app = cls.root / 'application'; (app / 'share/doc/Foundation').mkdir(parents=True)
        (app / 'share/doc/Foundation/LICENSE').write_bytes(b'Fixture redistribution terms\n')
        c = cls.root / 'main.c'; c.write_text('int main(void) { return 0; }\n')
        subprocess.run(['cc', str(c), '-o', str(app / 'bin/foundation-cli')], check=True)
        wrapper = cls.root / 'wrapper'; wrapper.mkdir(); shutil.copytree(app, wrapper / 'prefix')
        package = cls.root / 'application.tar.gz'; package.unlink(); d.archive.archive_tree(wrapper, package)
        d.archive.write_json(cls.root / 'application.tar.gz.json', d.release.artifact.describe(package))
        cls.f.fixture.spec['artifacts'][0]['sha256'] = d.archive.digest(package)
        d.archive.write_json(cls.f.fixture.spec_path, cls.f.fixture.spec)
        shutil.rmtree(cls.f.directory); d.release.assemble(cls.f.fixture.spec_path, cls.f.fixture.base, cls.f.directory)
        cls.f.delivery = d.delivery.publish_candidate(**cls.f.args)['delivery']; cls.f.publish()
        cls.cert = cls.f.cert(); d.delivery.attach_certificate(**cls.cert, execute=True, transport=cls.f.remote)
        cls.f.promotion(cls.cert, execute=True)
        home = cls.root / 'keyhome'; home.mkdir(mode=0o700)
        try:
            d.distro.run('gpg', '--batch', '--homedir', home, '--pinentry-mode', 'loopback', '--passphrase', '',
                        '--quick-generate-key', 'Fixture <fixture@example.invalid>', 'ed25519', 'sign', '1d')
            public = cls.root / 'public.gpg'; public.write_bytes(d.distro.run('gpg', '--batch', '--homedir', home, '--export'))
            cls.trusted = d.apt.fingerprint(public); cls.private = cls.root / 'private.asc'
            cls.private.write_bytes(d.distro.run('gpg', '--batch', '--homedir', home, '--armor', '--export-secret-keys', cls.trusted))
        finally: d.distro.run('gpgconf', '--homedir', home, '--kill', 'all')
        cls.req = dict(request(), trusted_fingerprint=cls.trusted, target='linux-' + cls.arch,
                       inventory_sha256=cls.f.delivery['inventory_sha256'], certificate_sha256=d.archive.digest(cls.cert['certificate']))
        cls.policy = cls.cert['policy']; cls.packaging = cls.root / 'packaging-source.tar.gz'
        cls.checkout = cls.root / 'packaging-checkout'
        cls.req['packager_commit'] = git_fixture(cls.checkout)
        d.source_identity.archive_source(cls.checkout, cls.packaging)
        cls.prepared = cls.root / 'distribution'
        cls.frozen = d.prepare(cls.req, cls.f.directory, cls.f.delivery, cls.policy, cls.packaging, cls.prepared,
                               cls.private, transport=cls.f.remote, packaging_checkout=cls.checkout)
        cls.remote_state = copy.deepcopy(cls.f.remote)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.root); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name); self.remote = copy.deepcopy(self.remote_state)

    def test_unpromoted_application_is_rejected_before_certificate_replay(self):
        self.remote.releases[0]['prerelease'] = True
        before = len(self.remote.mutations)
        with patch.object(d.delivery, 'verify_certificate') as replay:
            with self.assertRaisesRegex(ValueError, 'lifecycle'):
                d.certified(d.delivery.Remote('example/project', self.remote), self.f.directory,
                            self.f.delivery, self.policy, self.req)
        replay.assert_not_called()
        self.assertEqual(before, len(self.remote.mutations))

    def test_prepare_fetches_only_one_exact_certificate_pair(self):
        self.remote.calls.clear()
        output = self.work / 'prepared-once'
        d.prepare(self.req, self.f.directory, self.f.delivery, self.policy, self.packaging, output,
                  self.private, transport=self.remote, packaging_checkout=self.checkout)
        names = {row['id']: row['name'] for row in self.remote.releases[0]['assets']}
        downloads = [names[call[1]] for call in self.remote.calls if call[0] == 'download']
        stem = f'certification-{self.req["certificate_run"]}-attempt-{self.req["certificate_attempt"]}'
        self.assertCountEqual(['delivery.json', stem + '.json', stem + '.tar.gz'], downloads)
        self.assertIn(b'fetch --native-only', (output / 'INSTALL.md').read_bytes())

    def test_cached_certificate_must_match_current_remote_digest(self):
        stem = f'certification-{self.req["certificate_run"]}-attempt-{self.req["certificate_attempt"]}'
        self.remote.replace_asset(stem + '.tar.gz', b'changed certificate')
        before = len(self.remote.mutations)
        with self.assertRaisesRegex(ValueError, 'retained certificate changed'):
            d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertEqual(before, len(self.remote.mutations))

    def test_legacy_signed_instructions_remain_verifiable(self):
        output = self.work / 'legacy-instructions'
        shutil.copytree(self.prepared, output)
        (output / 'INSTALL.md').write_bytes(d.instructions(self.req, self.frozen['backends']))
        value = d.archive.read_json(output / 'distribution.json')
        value['files']['INSTALL.md'] = d.asset_info(output / 'INSTALL.md')
        d.archive.write_json(output / 'distribution.json', value)
        with d.distro.signing(self.private, self.trusted) as (_, sign):
            (output / 'distribution.json.sig').write_bytes(sign((output / 'distribution.json').read_bytes()))
        self.assertEqual(value, d.verify(output, self.policy, self.trusted))

    def test_real_signatures_packages_and_source_closure_verify(self):
        value = d.verify(self.prepared, self.policy, self.trusted)
        self.assertEqual(value, self.frozen); self.assertEqual(['core'], value['backends'])
        self.assertEqual({6}, {spec['schema_version'] for spec in value['specifications'].values()})
        self.assertTrue((self.prepared / 'Packages').is_file()); self.assertTrue((self.prepared / 'software-foundation.db').is_file())
        self.assertEqual(set(value['retained']), {'application/' + name for name in self.f.delivery['files']} |
            {'delivery.json', 'policy.json', 'packaging-source.tar.gz', 'certification-qualification-run-attempt-1.json', 'certification-qualification-run-attempt-1.tar.gz'})
        for name in value['retained'].values(): self.assertIn(d.archive.digest(self.prepared / name), name)
        with (self.prepared / 'Packages').open() as stream:
            filename = next(line.removeprefix('Filename: ').strip() for line in stream if line.startswith('Filename: '))
        self.assertTrue((self.prepared / filename).is_file())
        self.assertNotIn(self.private.read_bytes(), b''.join(p.read_bytes() for p in self.prepared.iterdir()))

    def test_old_signed_schema_three_channel_still_replays_exactly(self):
        legacy = self.work/'schema-three'
        with patch.object(d.distro, 'CURRENT_SCHEMA', 3):
            previous = d.prepare(self.req, self.f.directory, self.f.delivery, self.policy,
                self.packaging, legacy, self.private, transport=self.remote, packaging_checkout=self.checkout)
        self.assertEqual({3}, {spec['schema_version'] for spec in previous['specifications'].values()})
        self.assertEqual(d.verify(legacy, self.policy, self.trusted), previous)

    def test_real_signed_combined_archive_verifies_every_backend(self):
        f = fixtures.DeliveryTests(); f.setUp(); self.addCleanup(f.doCleanups)
        app = f.root / 'application'
        for name in ('foundation-cli', 'foundation-gui-terminal'):
            shutil.copy2(self.root / 'application/bin/foundation-cli', app / 'bin' / name)
        info = app / 'build-info.txt'
        info.write_text(info.read_text().replace('gui_backends=\n', 'gui_backends=terminal\n'))
        docs = app / 'share/doc/Foundation'; (docs / 'gui-boundary').mkdir(parents=True)
        (docs / 'LICENSE').write_bytes(b'Fixture redistribution terms\n')
        terms = b'Fixture GUI redistribution terms\n'
        (docs / 'gui-boundary/LICENSE').write_bytes(terms)
        gui_lock = dict(license='MIT', redistribution=dict(approved=True, license_files=['LICENSE']),
                        files={'LICENSE': d.apt.byte_record(terms, 0o644)['sha256']})
        d.archive.write_json(docs / 'gui-boundary/gui-boundary.lock.json', gui_lock)
        (docs / 'dependency-notices').mkdir()
        d.archive.write_json(docs / 'dependency-notices/index.json', dict(schema_version=1, providers=[], files={}))
        wrapper = f.root / 'wrapper'; wrapper.mkdir(); shutil.copytree(app, wrapper / 'prefix')
        package = f.root / 'application.tar.gz'; package.unlink(); d.archive.archive_tree(wrapper, package)
        d.archive.write_json(f.root / 'application.tar.gz.json', d.release.artifact.describe(package))
        f.fixture.spec['artifacts'][0].update(sha256=d.archive.digest(package), backends=['terminal'])
        d.archive.write_json(f.fixture.spec_path, f.fixture.spec)
        shutil.rmtree(f.directory); d.release.assemble(f.fixture.spec_path, f.fixture.base, f.directory)
        f.delivery = f.publish()['delivery']

        # Run the existing real certificate adapter for the combined archive's
        # terminal backend, retaining independent source/archive/recovery reports.
        c = d.delivery.coverage; policy = copy.deepcopy(c.load(self.policy))
        policy['profiles']['fixture']['targets'][f.target] = ['terminal']
        for row in policy['profiles']['fixture']['checks']: row['backend'] = 'terminal'
        template = c.load(self.cert['check_plan'])
        subject = dict(source_sha256=f.delivery['source_sha256'], inventory_sha256=f.delivery['inventory_sha256'],
                       configuration_sha256=c.digest({'policy': policy, 'profile': 'fixture'}))
        checks = copy.deepcopy(template['checks'])
        for check in checks:
            check['backend'] = 'terminal'
            receipt = json.loads(check['argv'][-1]); receipt.update(backend='terminal', **{
                key: subject[key] for key in ('source_sha256', 'inventory_sha256')})
            check['argv'][-1] = json.dumps(receipt)
        plan = c.freeze(dict(schema_version=1, mode='release', subject=subject, inputs=template['inputs'], checks=checks))
        evidence = self.work / 'certificate'; evidence.mkdir(); reports = []
        for check in checks:
            result = c.run_case(plan, check['id'], self.cert['check_plan'].parent,
                                evidence / check['id'], 'qualification-run', 1)
            self.assertEqual('passed', result['status'])
            reports.append(evidence / check['id'] / 'result.json')
        certificate = d.delivery.certification.certify(f.directory, d.release.verify_release(f.directory),
                                                       plan, reports, policy, 'fixture')
        paths = {}
        for key, value in (('certificate', certificate), ('check_plan', plan), ('policy', policy)):
            paths[key] = evidence / (key + '.json'); c.write_new(paths[key], value)
        cert = dict(repository='example/project', tag='v1', directory=str(f.directory), delivery=f.delivery,
                    profile='fixture', reports=reports, attempt=1, **paths)
        d.delivery.attach_certificate(**cert, execute=True, transport=f.remote); f.promotion(cert, execute=True)
        req = dict(self.req, inventory_sha256=f.delivery['inventory_sha256'],
                   certificate_sha256=c.sha(paths['certificate']),
                   license_files=[*self.req['license_files'], 'share/doc/Foundation/gui-boundary/LICENSE',
                                  'share/doc/Foundation/gui-boundary/gui-boundary.lock.json',
                                  'share/doc/Foundation/dependency-notices/index.json'])
        load = d.apt.c.load
        def fixture_terms(path):
            if Path(path) == ROOT / 'third_party/gui-boundary.lock.json':
                return gui_lock
            return load(path)
        # Supplier approval is explicit fixture input; signing, certificate replay,
        # both native package formats and every retained reference are verified.
        output = self.work / 'combined-distribution'
        with patch.object(d.distro, 'require_gui_terms'), patch.object(d.apt.c, 'load', side_effect=fixture_terms):
            prepared = d.prepare(req, f.directory, f.delivery, paths['policy'], self.packaging, output,
                                 self.private, transport=f.remote, packaging_checkout=self.checkout)
            verified = d.verify(output, paths['policy'], self.trusted)
            projection = self.work/'combined-native'
            projection.mkdir()
            for name in d.NATIVE_ASSETS: shutil.copy2(output/name, projection/name)
            self.assertEqual(verified, d.verify_native(projection, paths['policy'], self.trusted))
        self.assertEqual(prepared, verified)
        self.assertEqual(['core', 'terminal'], verified['backends'])
        self.assertEqual({'core', 'terminal'}, set(verified['specifications']))
        for backend, spec in verified['specifications'].items():
            self.assertEqual(backend, spec['backend'])
            self.assertEqual(d.archive.digest(package), spec['archive_sha256'])
        for backend in verified['backends']:
            self.assertTrue(any(name.startswith('software-foundation-' + backend + '_') and name.endswith('.deb')
                                for name in verified['apt_files']))
            self.assertTrue(any(name.startswith('software-foundation-' + backend + '-') and name.endswith('.pkg.tar.gz')
                                for name in verified['arch_files']))

    def test_complete_retained_delivery_requires_terms_even_for_selected_core_target(self):
        manifest = copy.deepcopy(d.release.verify_release(self.f.directory))
        manifest['artifacts'].append(dict(manifest['artifacts'][0], target='windows-x86_64', backends=['fltk']))
        with patch.object(d.release, 'verify_release', return_value=manifest), \
                patch.object(d.distro, 'require_gui_terms', side_effect=ValueError('unresolved terms')) as terms:
            with self.assertRaisesRegex(ValueError, 'terms'):
                d.prepare(self.req, self.f.directory, self.f.delivery, self.policy, self.packaging,
                          self.work / 'terms', self.private, transport=self.remote, packaging_checkout=self.checkout)
        terms.assert_called_once()
        self.assertFalse((self.work / 'terms').exists())

    def test_packaging_commit_proof_rejects_different_bytes_modes_and_commit_object(self):
        proof = self.frozen['packaging_source_proof']
        self.assertEqual(proof, d.verify_source_commit(self.packaging, proof, self.req['packager_commit']))
        changed = copy.deepcopy(proof); changed['commit_object'] = d.base64.b64encode(b'tree ' + b'0' * 40 + b'\n').decode()
        with self.assertRaisesRegex(ValueError, 'Git commit'): d.verify_source_commit(self.packaging, changed, self.req['packager_commit'])
        raw = d.base64.b64decode(proof['commit_object'])
        duplicate = raw.split(b'\n', 1)[0] + b'\n' + raw
        changed = dict(proof, commit_object=d.base64.b64encode(duplicate).decode(),
                       commit=d._git_object('commit', duplicate, 'sha1').hex())
        with self.assertRaisesRegex(ValueError, 'Git commit'): d.verify_source_commit(self.packaging, changed, changed['commit'])
        for mode in ('bytes', 'executable'):
            root = self.work / mode
            shutil.copytree(self.checkout, root)
            if mode == 'bytes': (root / 'a/z').write_bytes(b'substituted source\n')
            else: (root / 'script').chmod(0o644)
            bundled = self.work / (mode + '.tar.gz'); d.source_identity.archive_source(root, bundled)
            with self.assertRaisesRegex(ValueError, 'Git commit'): d.verify_source_commit(bundled, proof, self.req['packager_commit'])
            with self.assertRaisesRegex(ValueError, 'clean'): d.source_commit_proof(root, bundled, self.req['packager_commit'])

    def test_sha256_repository_commit_proof_is_verified_without_checkout(self):
        root = self.work / 'sha256'; commit = git_fixture(root, 'sha256')
        bundled = self.work / 'sha256-source.tar.gz'; d.source_identity.archive_source(root, bundled)
        proof = d.source_commit_proof(root, bundled, commit); shutil.rmtree(root)
        self.assertEqual(proof, d.verify_source_commit(bundled, proof, commit))

    def test_publish_is_plan_by_default(self):
        before = len(self.remote.mutations)
        self.assertFalse(d.publish(self.prepared, self.policy, self.trusted, transport=self.remote)['execute'])
        self.assertEqual(before, len(self.remote.mutations))

    def test_publish_readback_fetch_and_identical_retry_preserve_application_and_latest(self):
        application = copy.deepcopy(self.remote.releases[0]); self.remote.latest = application['id']
        self.remote.calls.clear()
        result = d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertTrue(result['execute']); self.assertEqual(application, self.remote.releases[0]); self.assertEqual(application['id'], self.remote.latest)
        application_names = {row['id']: row['name'] for row in self.remote.releases[0]['assets']}
        app_downloads = [application_names[call[1]] for call in self.remote.calls
                         if call[0] == 'download' and call[1] in application_names]
        self.assertEqual(['delivery.json'], app_downloads)
        channel_ids = {row['id'] for row in self.remote.releases[-1]['assets']}
        self.assertEqual(channel_ids, {call[1] for call in self.remote.calls if call[0] == 'download'} - set(application_names))
        restored = self.work / 'restored'
        self.assertEqual(self.frozen, d.fetch('example/project', d.tag_for(self.req), d.archive.digest(self.prepared / 'distribution.json'),
                         restored, self.policy, self.trusted, transport=self.remote))
        self.remote.calls.clear()
        d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertFalse(any(call[0] == 'upload' for call in self.remote.calls))
        self.assertEqual(['delivery.json'], [application_names[call[1]] for call in self.remote.calls if call[0] == 'download'])

    def test_publish_final_readback_ignores_unstable_release_history(self):
        application = copy.deepcopy(self.remote.releases[0])
        self.remote.latest = application['id']
        pages = self.remote.pages
        def unstable_history(endpoint):
            rows = pages(endpoint)
            if endpoint.endswith('/releases?per_page=100') and any(
                    row['tag_name'] == d.tag_for(self.req) and not row['draft']
                    for row in self.remote.releases):
                return rows + [copy.deepcopy(rows[0])]
            return rows
        self.remote.calls.clear()
        with patch.object(self.remote, 'pages', side_effect=unstable_history):
            result = d.publish(self.prepared, self.policy, self.trusted,
                               execute=True, transport=self.remote)
        channel = self.remote.releases[-1]
        self.assertEqual(channel['id'], result['release_id'])
        self.assertFalse(channel['draft'])
        self.assertTrue(channel['prerelease'])
        self.assertEqual(application, self.remote.releases[0])
        self.assertEqual(application['id'], self.remote.latest)
        patches = [i for i, call in enumerate(self.remote.calls) if call[0] == 'PATCH']
        self.assertEqual(1, len(patches))
        final_reads = self.remote.calls[patches[0] + 1:]
        self.assertIn(('GET', 'repos/example/project/releases/' + str(channel['id']), None), final_reads)
        self.assertNotIn(('pages', 'repos/example/project/releases?per_page=100'), final_reads)

    def test_native_projection_keeps_signed_complete_inventory_without_sdk_downloads(self):
        d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.remote.calls.clear()
        output = self.work/'native-projection'
        digest = d.archive.digest(self.prepared/'distribution.json')
        self.assertEqual(self.frozen, d.fetch('example/project', d.tag_for(self.req), digest,
            output, self.policy, self.trusted, transport=self.remote, native_only=True))
        self.assertEqual(d.NATIVE_ASSETS, {p.name for p in output.iterdir()})
        assets = {row['id']: row['name'] for row in self.remote.releases[-1]['assets']}
        downloaded = {assets[call[1]] for call in self.remote.calls if call[0] == 'download'}
        self.assertEqual(d.NATIVE_ASSETS, downloaded)
        with self.assertRaises(ValueError): d.verify(output, self.policy, self.trusted)
        self.assertEqual(self.frozen, d.verify_native(output, self.policy, self.trusted))
        self.remote.calls.clear()
        again = self.work/'native-reuse'
        self.assertEqual(self.frozen, d.fetch('example/project', d.tag_for(self.req), digest,
            again, self.policy, self.trusted, transport=self.remote, native_only=True, reuse=output))
        downloaded = {assets[call[1]] for call in self.remote.calls if call[0] == 'download'}
        self.assertEqual(d.NATIVE_ASSETS - {'channels.tar.gz'}, downloaded)
        self.assertNotEqual((output/'channels.tar.gz').stat().st_ino, (again/'channels.tar.gz').stat().st_ino)
        (again/'channels.tar.gz').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'channel archive bytes'):
            d.verify_native(again, self.policy, self.trusted)

    def test_native_projection_rejects_signed_map_mismatch_and_inventory_changes(self):
        d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        channel = self.remote.releases[-1]; original = copy.deepcopy(channel['assets'])
        digest = d.archive.digest(self.prepared/'distribution.json')
        for case in ('digest', 'absent_digest', 'size', 'missing', 'extra'):
            with self.subTest(case=case):
                channel['assets'] = copy.deepcopy(original)
                row = next(item for item in channel['assets'] if item['name'].startswith('sha256-'))
                if case == 'digest': row['digest'] = 'sha256:'+'e'*64
                elif case == 'absent_digest': row.pop('digest')
                elif case == 'size': row['size'] += 1
                elif case == 'missing': channel['assets'].remove(row)
                else:
                    extra = dict(row, id=999999, name='foreign'); channel['assets'].append(extra)
                output = self.work/('bad-native-'+case)
                with self.assertRaises(ValueError):
                    d.fetch('example/project', d.tag_for(self.req), digest, output,
                        self.policy, self.trusted, transport=self.remote, native_only=True)
                self.assertFalse(output.exists())
        channel['assets'] = original

    def test_native_acceptance_checks_payload_then_preserves_qualified_retry(self):
        import distro_check
        d.publish(self.prepared,self.policy,self.trusted,execute=True,transport=self.remote)
        channel=self.remote.releases[-1]
        selected=dict(tag=d.tag_for(self.req),manifest_sha256=d.archive.digest(self.prepared/'distribution.json'),target=self.req['target'])
        env=dict(GITHUB_REPOSITORY='example/project',GITHUB_SHA=self.req['packager_commit'],GITHUB_RUN_ID='901',GITHUB_RUN_ATTEMPT='1',TRUSTED_FINGERPRINT=self.trusted)
        channels=distro_check.extract_channels(self.prepared,self.work/'expected')
        records=[]
        for row in distro_check.matrix(selected['target'])['include']:
            expected=distro_check.expected_payload(channels,self.frozen,'core',row['kind'])
            records.append(dict(schema_version=1,status='passed',id=row['id'],kind=row['kind'],image=row['image'],image_id='sha256:'+'a'*64,
                target=selected['target'],tag=selected['tag'],manifest_sha256=selected['manifest_sha256'],
                checks=['signature','published-download','install','repeated-update','exact-payload','self-check','remove'],
                source_commit=env['GITHUB_SHA'],run_id='901',attempt='1',commands=[['fixture-only']],
                backends=[dict(backend='core',files=len(expected),payload_sha256=d.distro.digest(d.distro.encoded(expected)))]))
        checkout=self.work/'client';(checkout/'docs').mkdir(parents=True);shutil.copyfile(self.policy,checkout/'docs/release-policy.json')
        original=d.delivery.Remote
        with patch.object(d,'ROOT',checkout),patch.object(d.delivery,'Remote',side_effect=lambda repository,transport=None:original(repository,self.remote)):
            bad=copy.deepcopy(records);bad[0]['backends'][0]['payload_sha256']='b'*64
            with self.assertRaisesRegex(ValueError,'exact signed channel'):
                distro_check.accept(selected,bad,env,self.work/'bad-evidence')
            self.assertTrue(channel['prerelease'])
            pages = self.remote.pages
            def unstable_history(endpoint):
                rows = pages(endpoint)
                if endpoint.endswith('/releases?per_page=100') and not channel['prerelease']:
                    return rows + [copy.deepcopy(channel)]
                return rows
            with patch.object(self.remote, 'pages', side_effect=unstable_history):
                distro_check.accept(selected,records,env,self.work/'accepted')
            last_patch = max(i for i, call in enumerate(self.remote.calls) if call[0] == 'PATCH')
            final_reads = self.remote.calls[last_patch + 1:]
            self.assertIn(('GET', 'repos/example/project/releases/' + str(channel['id']), None), final_reads)
            self.assertNotIn(('pages', 'repos/example/project/releases?per_page=100'), final_reads)
            self.assertFalse(channel['prerelease'])
            saved=copy.deepcopy(channel)
            distro_check.accept(selected,records,env,self.work/'accepted-retry')
            self.assertEqual(saved,channel)
        d.publish(self.prepared,self.policy,self.trusted,execute=True,transport=self.remote)
        self.assertEqual(saved,channel)
        marker=json.loads(channel['body']);marker['native_qualification']['target']='linux-aarch64' if self.req['target']=='linux-x86_64' else 'linux-x86_64'
        channel['body']=json.dumps(marker)
        with self.assertRaises(ValueError):
            d.fetch('example/project',selected['tag'],selected['manifest_sha256'],self.work/'wrong-target',self.policy,self.trusted,transport=self.remote)

    def test_partial_upload_failure_retains_draft_and_exact_retry_reconciles(self):
        self.remote.calls.clear()
        self.remote.fail_upload = 'Packages'
        with self.assertRaises(d.delivery.DeliveryError) as failed:
            d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertTrue(failed.exception.uncertain)
        channel = self.remote.releases[-1]; self.assertTrue(channel['draft']); self.assertTrue(channel['assets'])
        self.assertFalse(d.CONTROL & {row['name'] for row in channel['assets']})
        self.assertFalse(any(call[0] == 'PATCH' for call in self.remote.calls))
        self.remote.fail_upload = None
        d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertFalse(self.remote.releases[-1]['draft'])

    def test_changed_remote_asset_is_never_overwritten(self):
        d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.remote.replace_asset('Packages', b'changed'); before = len(self.remote.mutations)
        with self.assertRaises(ValueError): d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertEqual(before, len(self.remote.mutations))

    def test_signed_manifest_and_unsigned_flat_payload_tampering_fail(self):
        for name in ('distribution.json', 'Packages', 'software-foundation.db', 'channels.tar.gz'):
            with self.subTest(name=name):
                stage = self.work / name.replace('.', '-'); shutil.copytree(self.prepared, stage)
                with (stage / name).open('ab') as stream: stream.write(b'changed')
                with self.assertRaises((ValueError, subprocess.SubprocessError)): d.verify(stage, self.policy, self.trusted)

    def test_other_policy_certificate_and_trust_cannot_authorize_publication(self):
        other = self.work / 'policy.json'; other.write_bytes(self.policy.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'policy'): d.verify(self.prepared, other, self.trusted)
        with self.assertRaisesRegex(ValueError, 'policy'): d.verify(self.prepared, self.policy, 'F' * 40)
        changed = dict(self.req, certificate_sha256='0' * 64)
        with self.assertRaises(ValueError): d.prepare(changed, self.f.directory, self.f.delivery, self.policy, self.packaging,
            self.work / 'bad', self.private, transport=self.remote, packaging_checkout=self.checkout)
        self.assertFalse((self.work / 'bad').exists())

    def resign(self, directory, value):
        d.archive.write_json(directory / 'distribution.json', value)
        with d.distro.signing(self.private, self.trusted) as (_, sign):
            (directory / 'distribution.json.sig').write_bytes(sign((directory / 'distribution.json').read_bytes()))

    def test_valid_outer_signature_cannot_relabel_certified_package_version(self):
        stage = self.work / 'relabeled'; shutil.copytree(self.prepared, stage)
        value = copy.deepcopy(self.frozen); value['request']['version'] = '9.0.0'
        value['tag'] = d.tag_for(value['request'])
        self.resign(stage, value)
        with self.assertRaisesRegex(ValueError, 'URL|certified|version'): d.verify(stage, self.policy, self.trusted)

    def test_valid_outer_signature_cannot_replace_flat_channel_bytes(self):
        stage = self.work / 'changed'; shutil.copytree(self.prepared, stage)
        (stage / 'Packages').write_bytes(b'changed flat metadata\n')
        value = copy.deepcopy(self.frozen); value['files']['Packages'] = d.asset_info(stage / 'Packages')
        self.resign(stage, value)
        with self.assertRaisesRegex(ValueError, 'flat channel'): d.verify(stage, self.policy, self.trusted)
        projected = self.work/'changed-native'; projected.mkdir()
        for name in d.NATIVE_ASSETS: shutil.copy2(stage/name, projected/name)
        with self.assertRaisesRegex(ValueError, 'flat channel'): d.verify_native(projected, self.policy, self.trusted)

    def test_application_change_during_upload_preserves_private_failure(self):
        original = self.remote.upload; replaced = False
        def upload(tag, path):
            nonlocal replaced
            original(tag, path)
            if not replaced:
                replaced = True; self.remote.replace_asset('delivery.json')
        with patch.object(self.remote, 'upload', side_effect=upload), self.assertRaises(ValueError):
            d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        self.assertTrue(self.remote.releases[-1]['draft'])

    def test_fetch_rejects_replaced_asset_identity_without_exposing_output(self):
        d.publish(self.prepared, self.policy, self.trusted, execute=True, transport=self.remote)
        original = copy.deepcopy(self.remote)
        for native_only in (False, True):
            with self.subTest(native_only=native_only):
                self.remote = copy.deepcopy(original)
                self.remote.change_download = lambda: self.remote.replace_asset('Packages')
                output = self.work / ('changed-native' if native_only else 'changed')
                with self.assertRaises(ValueError):
                    d.fetch('example/project', d.tag_for(self.req), d.archive.digest(self.prepared / 'distribution.json'),
                            output, self.policy, self.trusted, transport=self.remote, native_only=native_only)
                self.assertFalse(output.exists())

    def test_asset_limit_preflight_prevents_a_remote_partial_channel(self):
        with patch.object(d, 'MAX_ASSET', 1), self.assertRaisesRegex(ValueError, 'limits'):
            d.prepare(self.req, self.f.directory, self.f.delivery, self.policy, self.packaging,
                      self.work / 'oversized', self.private, transport=self.remote, packaging_checkout=self.checkout)
        self.assertFalse((self.work / 'oversized').exists())


if __name__ == '__main__': unittest.main()
