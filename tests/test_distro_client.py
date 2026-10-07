"""Authenticated client selection, rollback, and retained-generation behavior."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import distro_client as client
import test_distribution_release as fixtures


def config(location):
    return dict(schema_version=1, repository='example/project', target='linux-x86_64',
        trusted_fingerprint='A'*40, policy_sha256='b'*64, location=str(location),
        selection={'tag':'distro-1.2.3-x86_64-r1-s7','manifest_sha256':'c'*64})


def marker(target='linux-x86_64'):
    checks = ['apt-bookworm','apt-trixie','apt-ubuntu']+(['arch','gentoo'] if target.endswith('x86_64') else [])
    return dict(schema_version=1,target=target,source_commit='a'*40,run_id=1,attempt=1,checks={name:'b'*64 for name in checks})


def asset_row(identity, name, data, tag='distro-1.2.3-x86_64-r1-s7'):
    return dict(id=identity, name=name, state='uploaded', size=len(data), digest='sha256:' + hashlib.sha256(data).hexdigest(),
                browser_download_url='https://github.com/example/project/releases/download/' + quote(tag, safe='') + '/' + quote(name, safe=''))


def asset_response(data, url='https://release-assets.githubusercontent.com/fixture/object?signature=exact'):
    result = io.BytesIO(data); result.url = url
    return result


class PublicDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.transport = client.PublicGitHub('example/project')
        self.tag = 'distro-1.2.3-x86_64-r1-s7'
        self.releases = 'repos/example/project/releases?per_page=100'
        self.assets = 'repos/example/project/releases/1/assets?per_page=100'

    def bind(self, rows):
        with patch.object(self.transport, 'json', side_effect=[[dict(id=1, tag_name=self.tag)], rows]):
            self.transport.pages(self.releases); self.transport.pages(self.assets)

    def test_seventy_asset_downloads_use_public_urls_without_asset_rest_requests(self):
        rows = [asset_row(index + 1, 'asset-' + str(index), str(index).encode()) for index in range(70)]
        bodies = {row['browser_download_url']: str(index).encode() for index, row in enumerate(rows)}
        with patch.object(self.transport, 'json', side_effect=[[dict(id=1, tag_name=self.tag)], rows]) as metadata, \
                patch.object(self.transport, 'request', side_effect=AssertionError('no per-asset REST request')), \
                patch.object(client, 'build_opener') as build:
            build.return_value.open.side_effect = lambda request, **options: asset_response(bodies[request.full_url])
            self.transport.pages(self.releases); self.transport.pages(self.assets)
            for row in rows: self.transport.download(row['id'], self.root / row['name'])
        self.assertEqual(metadata.call_count, 2); self.assertEqual(build.return_value.open.call_count, 70)
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()},
                         {row['name']: bodies[row['browser_download_url']] for row in rows})

    def test_canonical_encoded_release_components_keep_exact_asset_binding(self):
        self.tag = 'release+one'
        name = 'software-foundation-core_1.2.3+r1_amd64.deb'
        canonical = ('https://github.com/example/project/releases/download/release%2Bone/'
                     'software-foundation-core_1.2.3%2Br1_amd64.deb')
        row = dict(id=1, name=name, state='uploaded', size=5,
                   digest='sha256:'+hashlib.sha256(b'exact').hexdigest(), browser_download_url=canonical)
        self.bind([row])
        with patch.object(client, 'build_opener') as build:
            build.return_value.open.return_value = asset_response(b'exact')
            self.transport.download(1, self.root/name)
            self.assertEqual(build.return_value.open.call_args.args[0].full_url, canonical)
        self.assertEqual((self.root/name).read_bytes(), b'exact')
        for url in (canonical.replace('%2B', '+'), canonical.replace('%2B', '%252B'),
                    canonical.replace('%2B', '%2F'), canonical+'?replacement=1'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'exact release URL'):
                self.transport.remember(self.assets, [dict(row, browser_download_url=url)])
        self.assertEqual(self.transport.assets[1]['url'], canonical)

    def test_incomplete_asset_pagination_never_authorizes_download(self):
        rows = [asset_row(index + 1, 'asset-' + str(index), b'x') for index in range(100)]
        with patch.object(self.transport, 'json', side_effect=[[dict(id=1, tag_name=self.tag)], rows, OSError('page two failed')]):
            self.transport.pages(self.releases)
            with self.assertRaises(OSError): self.transport.pages(self.assets)
        with patch.object(client, 'build_opener') as build, self.assertRaisesRegex(ValueError, 'complete public asset inventory'):
            self.transport.download(1, self.root / 'payload')
        build.assert_not_called(); self.assertEqual(self.transport.assets, {})

    def test_asset_binding_rejects_foreign_url_unbound_release_and_rebinding(self):
        row = asset_row(1, 'payload', b'exact')
        with self.assertRaisesRegex(ValueError, 'observed public release'):
            self.transport.remember(self.assets, [row])
        self.bind([row])
        for changed in (dict(row, browser_download_url=row['browser_download_url'].replace('/example/project/', '/foreign/project/')),
                        dict(row, browser_download_url=row['browser_download_url'].replace(self.tag, 'foreign-tag')),
                        dict(row, browser_download_url=row['browser_download_url'] + '?replacement=1'),
                        dict(row, name='../escape'), dict(row, size=client.release.MAX_ASSET+1),
                        dict(row, digest='sha256:' + 'a'*64)):
            with self.subTest(changed=changed), self.assertRaises(ValueError): self.transport.remember(self.assets, [changed])
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.transport.remember(self.releases, [dict(id=1, tag_name='different')])
        self.assertEqual(self.transport.assets[1]['sha256'], hashlib.sha256(b'exact').hexdigest())

    def test_truncated_excessive_or_changed_payload_never_publishes_destination(self):
        self.bind([asset_row(1, 'payload', b'exact')]); destination = self.root / 'payload'
        for data in (b'exac', b'exact!', b'wrong'):
            with self.subTest(data=data), patch.object(client, 'build_opener') as build:
                build.return_value.open.return_value = asset_response(data)
                with self.assertRaises(ValueError): self.transport.download(1, destination)
                self.assertFalse(destination.exists()); self.assertEqual(list(self.root.iterdir()), [])
        destination.write_bytes(b'preserve')
        with patch.object(client, 'build_opener') as build, self.assertRaisesRegex(ValueError, 'must be new'):
            self.transport.download(1, destination)
        build.assert_not_called(); self.assertEqual(destination.read_bytes(), b'preserve')

    def test_slow_trickle_has_whole_transfer_deadline_and_no_partial_destination(self):
        self.bind([asset_row(1, 'payload', b'exact')]); destination = self.root / 'payload'
        response = asset_response(b'exact'); response.read1 = Mock(side_effect=[b'e', b'x', b'a', b'c', b't', b''])
        with patch.object(client, 'build_opener') as build, patch.object(client, 'MAX_DOWNLOAD_SECONDS', 3), \
                patch.object(client.time, 'monotonic', side_effect=[0, 0, 0, 1, 3]):
            build.return_value.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'deadline'): self.transport.download(1, destination)
        self.assertEqual(response.read1.call_count, 1)
        self.assertFalse(destination.exists()); self.assertEqual(list(self.root.iterdir()), [])

    def test_redirects_reject_downgrade_foreign_hosts_credentials_ports_and_other_release(self):
        initial = asset_row(1, 'payload', b'x')['browser_download_url']; handler = client.ReleaseRedirects(initial)
        request = client.Request(initial)
        for url in ('http://release-assets.githubusercontent.com/object', 'https://example.invalid/object',
                    'https://release-assets.githubusercontent.com.evil.invalid/object',
                    'https://user@release-assets.githubusercontent.com/object', 'https://release-assets.githubusercontent.com:443/object',
                    initial.replace(self.tag, 'foreign-tag'), initial + '#fragment'):
            with self.subTest(url=url), self.assertRaises(ValueError): handler.redirect_request(request, None, 302, 'Found', {}, url)
        allowed = 'https://release-assets.githubusercontent.com/object?signature=exact'
        self.assertEqual(handler.redirect_request(request, None, 302, 'Found', {}, allowed).full_url, allowed)

    def test_redirect_chain_is_bounded_before_unlimited_network_requests(self):
        from email.message import Message
        initial = asset_row(1, 'payload', b'x')['browser_download_url']; handler = client.ReleaseRedirects(initial)
        calls = []
        def redirect(request, **options):
            calls.append(request.full_url); request.timeout = 1
            headers = Message(); headers['Location'] = 'https://release-assets.githubusercontent.com/object?hop=' + str(len(calls))
            return handler.http_error_302(request, io.BytesIO(b''), 302, 'Found', headers)
        handler.parent = Mock(open=Mock(side_effect=redirect))
        with self.assertRaises(client.HTTPError): redirect(client.Request(initial))
        self.assertLessEqual(len(calls), 7)


class PublicRateTests(unittest.TestCase):
    def setUp(self):
        self.transport = client.PublicGitHub('example/project')
        self.endpoint = 'repos/example/project/releases?per_page=100'
        self.elapsed = 0
        self.sleeps = []
        def sleep(seconds):
            self.sleeps.append(seconds); self.elapsed += seconds
        for target, replacement in ((client.time, dict(monotonic=lambda: self.elapsed,
                time=lambda: 1000 + self.elapsed, sleep=sleep)),
                (client.release.delivery.random, dict(uniform=lambda a, b: 0))):
            for name, value in replacement.items():
                patcher = patch.object(target, name, value); patcher.start(); self.addCleanup(patcher.stop)

    def failure(self, status=403, headers=None, message='API rate limit exceeded.'):
        return client.HTTPError('https://api.github.com/' + self.endpoint, status, 'untrusted reason',
            headers or {}, io.BytesIO(json.dumps({'message': message}).encode()))

    def response(self, value):
        return asset_response(json.dumps(value).encode(), 'https://api.github.com/' + self.endpoint)

    def test_primary_reset_recovers_without_credentials_and_closes_failed_response(self):
        error = self.failure(headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1002'})
        with patch.dict(client.os.environ, {'GH_TOKEN': 'must-not-be-used', 'GITHUB_TOKEN': 'also-unused'}), \
                patch.object(client, 'urlopen', side_effect=[error, self.response([])]) as request:
            self.assertEqual(self.transport.json(self.endpoint), [])
        self.assertEqual(request.call_count, 2); self.assertEqual(sum(self.sleeps), 2)
        self.assertTrue(error.closed)
        for call in request.call_args_list:
            self.assertFalse(call.args[0].has_header('Authorization'))
            self.assertEqual(call.args[0].get_method(), 'GET')
            self.assertLessEqual(call.kwargs['timeout'], 60)

    def test_retry_after_uses_later_delay_than_primary_reset(self):
        for retry in ('5', 'Thu, 01 Jan 1970 00:16:45 GMT'):
            with self.subTest(retry=retry):
                self.elapsed = 0; self.sleeps.clear()
                error = self.failure(headers={'retry-after': retry, 'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '1002'})
                with patch.object(self.transport, 'request', side_effect=[error, self.response([])]):
                    self.assertEqual(self.transport.json(self.endpoint), [])
                self.assertEqual(sum(self.sleeps), 5)

    def test_non_rate_forbidden_is_not_retried_or_reported_as_absence(self):
        with patch.object(self.transport, 'request', side_effect=self.failure(message='secret forbidden body')) as request:
            with self.assertRaisesRegex(ValueError, 'endpoint=.*HTTP 403') as caught:
                self.transport.json(self.endpoint, missing=True)
        self.assertEqual(request.call_count, 1); self.assertEqual(self.sleeps, [])
        self.assertNotIn('secret', str(caught.exception)); self.assertNotIn('untrusted reason', str(caught.exception))

    def test_rate_wait_budget_is_shared_across_metadata_operations(self):
        with patch.object(self.transport, 'request', side_effect=[self.failure(429, {'retry-after': '70'}), self.response([])]):
            self.transport.json(self.endpoint)
        with patch.object(self.transport, 'request', side_effect=self.failure(429, {'retry-after': '51'})) as request:
            with self.assertRaisesRegex(ValueError, 'wait budget exhausted'):
                self.transport.json(self.endpoint)
        self.assertEqual(request.call_count, 1); self.assertEqual(sum(self.sleeps), 70)
        self.assertLessEqual(max(self.sleeps), 60)

    def test_far_reset_fails_with_endpoint_and_quota_diagnostics_without_waiting(self):
        error = self.failure(headers={'x-ratelimit-limit': '60', 'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '5000'})
        with patch.object(self.transport, 'request', side_effect=error) as request:
            with self.assertRaisesRegex(ValueError, 'endpoint=.*limit=60; remaining=0; reset=5000'):
                self.transport.json(self.endpoint)
        self.assertEqual(request.call_count, 1); self.assertEqual(self.sleeps, [])

    def test_exhausted_retry_after_guidance_omits_arbitrary_query_values(self):
        endpoint = self.endpoint + '&page=2&access_token=do-not-log&per_page=secret'
        with patch.object(self.transport, 'request', side_effect=self.failure(429, {'retry-after': '121'})):
            with self.assertRaisesRegex(ValueError, r'endpoint=.*per_page=100&page=2.*retry-delay=121.000s') as caught:
                self.transport.json(endpoint)
        self.assertNotIn('access_token', str(caught.exception))
        self.assertNotIn('do-not-log', str(caught.exception)); self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(self.sleeps, [])

    def test_repeated_rate_limit_stops_at_attempt_bound(self):
        def rejected(*args, **kwargs): raise self.failure(429, {'retry-after': '1'})
        with patch.object(self.transport, 'request', side_effect=rejected) as request:
            with self.assertRaisesRegex(ValueError, 'attempt limit exhausted'):
                self.transport.json(self.endpoint)
        self.assertEqual(request.call_count, 3); self.assertEqual(sum(self.sleeps), 2)

    def test_malformed_reset_is_not_permission_to_retry_unclassified_forbidden(self):
        for reset in ('tomorrow', '9' * 100):
            error = self.failure(headers={'x-ratelimit-remaining': '0', 'x-ratelimit-reset': reset}, message='Forbidden')
            with self.subTest(reset=reset), patch.object(self.transport, 'request', side_effect=error) as request:
                with self.assertRaisesRegex(ValueError, 'HTTP 403'):
                    self.transport.json(self.endpoint)
                self.assertEqual(request.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_late_page_rate_limit_restarts_inventory_without_retaining_prefix(self):
        self.transport.releases[1] = 'distro-1.2.3-x86_64-r1-s7'
        endpoint = 'repos/example/project/releases/1/assets?per_page=100'
        stale = [asset_row(i + 1, 'old-' + str(i), b'x') for i in range(100)]
        fresh = [asset_row(201, 'fresh', b'y')]
        with patch.object(self.transport, 'request', side_effect=[self.response(stale),
                self.failure(429, {'retry-after': '1'}), self.response(fresh)]) as request:
            self.assertEqual(self.transport.pages(endpoint), fresh)
        self.assertEqual([c.args[0] for c in request.call_args_list],
                         [endpoint + '&page=1', endpoint + '&page=2', endpoint + '&page=1'])
        self.assertEqual(set(self.transport.assets), {201})

    def test_late_page_exhaustion_does_not_authorize_any_partial_asset(self):
        self.transport.releases[1] = 'distro-1.2.3-x86_64-r1-s7'
        rows = [asset_row(i + 1, 'asset-' + str(i), b'x') for i in range(100)]
        endpoint = 'repos/example/project/releases/1/assets?per_page=100'
        with patch.object(self.transport, 'request', side_effect=[self.response(rows), self.failure(429, {'retry-after': '121'})]):
            with self.assertRaisesRegex(ValueError, r'endpoint=.*page=2.*wait budget exhausted'):
                self.transport.pages(endpoint)
        self.assertEqual(self.transport.assets, {}); self.assertEqual(self.sleeps, [])

    def test_json_whole_response_deadline_stops_slow_trickle(self):
        response = self.response([])
        def slow_read(size):
            self.elapsed += 181
            return b'['
        response.read1 = Mock(side_effect=slow_read)
        with patch.object(self.transport, 'request', return_value=response):
            with self.assertRaisesRegex(ValueError, 'deadline exhausted'):
                self.transport.json(self.endpoint)
        self.assertTrue(response.closed); self.assertEqual(response.read1.call_count, 1)

    def test_public_scope_and_read_only_guards_survive_retry_wrapper(self):
        with patch.object(client, 'urlopen') as request:
            for endpoint, options in (('repos/foreign/project/releases', {}),
                    (self.endpoint, {'method': 'POST'}), (self.endpoint, {'body': {}})):
                with self.subTest(endpoint=endpoint, options=options), self.assertRaises(ValueError):
                    self.transport.json(endpoint, **options)
            request.assert_not_called()


class PublicTransientTests(unittest.TestCase):
    def setUp(self):
        PublicRateTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = asset_row(1, 'payload', b'exact')
        self.transport.remember(self.endpoint, [dict(id=1, tag_name='distro-1.2.3-x86_64-r1-s7')])
        self.assets_endpoint = 'repos/example/project/releases/1/assets?per_page=100'
        self.transport.remember(self.assets_endpoint, [self.row])

    failure = PublicRateTests.failure
    response = PublicRateTests.response

    def test_each_transient_metadata_status_recovers_and_closes_response(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                failure = self.failure(status)
                with patch.object(self.transport, 'request', side_effect=[failure, self.response([])]) as request:
                    self.assertEqual(self.transport.json(self.endpoint), [])
                self.assertEqual(request.call_count, 2); self.assertTrue(failure.closed)
        self.assertEqual(self.sleeps, [2] * 4)

    def test_each_transient_metadata_status_exhausts_three_attempts(self):
        for status in (500, 502, 503, 504):
            errors = [self.failure(status) for _ in range(3)]
            with self.subTest(status=status), patch.object(self.transport, 'request', side_effect=errors) as request:
                with self.assertRaisesRegex(ValueError, 'endpoint=.*attempt limit exhausted.*HTTP ' + str(status)):
                    self.transport.json(self.endpoint)
            self.assertEqual(request.call_count, 3); self.assertTrue(all(error.closed for error in errors))
        self.assertEqual(self.sleeps, [2, 4] * 4)

    def test_late_transient_page_restarts_complete_asset_inventory(self):
        self.transport.assets.clear()
        stale = [asset_row(i + 1, 'stale-' + str(i), b'x') for i in range(100)]
        fresh = [asset_row(201, 'fresh', b'y')]
        with patch.object(self.transport, 'request', side_effect=[self.response(stale),
                self.failure(503), self.response(fresh)]) as request:
            self.assertEqual(self.transport.pages(self.assets_endpoint), fresh)
        self.assertEqual([call.args[0] for call in request.call_args_list],
            [self.assets_endpoint + '&page=1', self.assets_endpoint + '&page=2', self.assets_endpoint + '&page=1'])
        self.assertEqual(set(self.transport.assets), {201})

    def test_each_transient_asset_status_recovers_using_bound_public_url(self):
        for status in (500, 502, 503, 504):
            error = self.failure(status)
            with self.subTest(status=status), patch.object(client, 'build_opener') as build, \
                    patch.object(client, 'urlopen', side_effect=AssertionError('no asset REST request')), \
                    patch.dict(client.os.environ, {'GH_TOKEN': 'unused', 'GITHUB_TOKEN': 'unused'}):
                build.return_value.open.side_effect = [error, asset_response(b'exact')]
                self.transport.download(1, self.root / str(status))
                self.assertEqual(build.call_count, 2)
                self.assertIsNot(build.call_args_list[0].args[0], build.call_args_list[1].args[0])
                for call in build.return_value.open.call_args_list:
                    self.assertEqual(call.args[0].full_url, self.row['browser_download_url'])
                    self.assertEqual(call.args[0].get_method(), 'GET')
                    self.assertFalse(call.args[0].has_header('Authorization'))
                    self.assertLessEqual(call.kwargs['timeout'], 60)
            self.assertTrue(error.closed); self.assertEqual((self.root / str(status)).read_bytes(), b'exact')
        self.assertEqual(self.sleeps, [2] * 4)

    def test_each_transient_asset_status_exhausts_without_destination_or_response_leaks(self):
        for status in (500, 502, 503, 504):
            errors = [self.failure(status, message='private error body') for _ in range(3)]
            for error in errors: error.url = 'https://release-assets.githubusercontent.com/private?signature=do-not-log'
            with self.subTest(status=status), patch.object(client, 'build_opener') as build:
                build.return_value.open.side_effect = errors
                with self.assertRaisesRegex(ValueError, 'public asset id=1:.*attempt limit exhausted.*HTTP ' + str(status)) as caught:
                    self.transport.download(1, self.root / 'payload')
                self.assertEqual(build.return_value.open.call_count, 3)
            self.assertTrue(all(error.closed for error in errors)); self.assertEqual(list(self.root.iterdir()), [])
            for private in ('signature', 'do-not-log', 'private error body', 'untrusted reason'):
                self.assertNotIn(private, str(caught.exception))

    def test_failed_partial_attempt_is_closed_and_removed_before_retry(self):
        error = self.failure(503); first = asset_response(b'')
        first.read1 = Mock(side_effect=[b'e', error])
        sleep = client.time.sleep
        def checked_sleep(seconds):
            self.assertTrue(first.closed); self.assertTrue(error.closed)
            self.assertEqual(list(self.root.iterdir()), [])
            sleep(seconds)
        with patch.object(client, 'build_opener') as build, patch.object(client.time, 'sleep', side_effect=checked_sleep):
            build.return_value.open.side_effect = [first, asset_response(b'exact')]
            self.transport.download(1, self.root / 'payload')
        self.assertEqual((self.root / 'payload').read_bytes(), b'exact')
        self.assertEqual([path.name for path in self.root.iterdir()], ['payload'])

    def test_asset_and_metadata_share_retry_wait_budget(self):
        with patch.object(self.transport, 'request', side_effect=[self.failure(503, {'retry-after': '70'}), self.response([])]):
            self.transport.json(self.endpoint)
        error = self.failure(503, {'retry-after': '51'})
        with patch.object(client, 'build_opener') as build:
            build.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError, 'public asset id=1:.*wait budget exhausted.*retry-delay=51.000s'):
                self.transport.download(1, self.root / 'payload')
        self.assertEqual(build.return_value.open.call_count, 1)
        self.assertTrue(error.closed); self.assertEqual(sum(self.sleeps), 70)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_asset_deadline_spans_failed_transfer_wait_and_new_attempt(self):
        error = self.failure(503); first = asset_response(b'')
        def failed_read(size):
            self.elapsed += 598
            raise error
        first.read1 = Mock(side_effect=failed_read)
        with patch.object(client, 'build_opener') as build:
            build.return_value.open.side_effect = [first, asset_response(b'exact')]
            with self.assertRaisesRegex(ValueError, 'deadline exhausted'):
                self.transport.download(1, self.root / 'payload')
        self.assertEqual(build.return_value.open.call_count, 1); self.assertEqual(self.sleeps, [])
        self.assertTrue(first.closed); self.assertTrue(error.closed)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_remaining_asset_deadline_limits_retry_socket_and_body(self):
        error = self.failure(503); first = asset_response(b''); second = asset_response(b'exact')
        def failed_read(size):
            self.elapsed += 596
            raise error
        def late_read(size):
            self.elapsed += 3
            return b'e'
        first.read1 = Mock(side_effect=failed_read); second.read1 = Mock(side_effect=late_read)
        with patch.object(client, 'build_opener') as build:
            build.return_value.open.side_effect = [first, second]
            with self.assertRaisesRegex(ValueError, 'deadline exhausted'):
                self.transport.download(1, self.root / 'payload')
        self.assertEqual([call.kwargs['timeout'] for call in build.return_value.open.call_args_list], [60, 2])
        self.assertEqual(self.sleeps, [2]); self.assertTrue(second.closed)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_asset_validation_errors_and_unclassified_http_failures_never_retry(self):
        for status in (400, 403, 404, 501):
            error = self.failure(status, message='Forbidden')
            with self.subTest(status=status), patch.object(client, 'build_opener') as build:
                build.return_value.open.side_effect = error
                with self.assertRaisesRegex(ValueError, 'HTTP ' + str(status)):
                    self.transport.download(1, self.root / 'payload')
                self.assertEqual(build.return_value.open.call_count, 1)
            self.assertTrue(error.closed)
        for response in (asset_response(b'wrong'), asset_response(b'exac'), asset_response(b'exact!'),
                         asset_response(b'exact', 'https://foreign.invalid/payload')):
            with patch.object(client, 'build_opener') as build:
                build.return_value.open.return_value = response
                with self.assertRaises(ValueError): self.transport.download(1, self.root / 'payload')
                self.assertEqual(build.return_value.open.call_count, 1)
            self.assertTrue(response.closed)
        self.assertEqual(self.sleeps, []); self.assertEqual(list(self.root.iterdir()), [])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.value=config(self.root/'state')

    def test_only_explicit_missing_404_is_absence(self):
        transport = client.PublicGitHub('example/project')
        for status, missing in ((404,True),(404,False),(403,True),(501,True)):
            error = client.HTTPError('https://api.github.com/repos/example/project/releases/latest',status,'fixture',{},None)
            with self.subTest(status=status,missing=missing), patch.object(transport,'request',side_effect=error):
                if status == 404 and missing:
                    self.assertIsNone(transport.json('repos/example/project/releases/latest',missing=missing))
                else:
                    with self.assertRaises(ValueError):transport.json('repos/example/project/releases/latest',missing=missing)

    def test_generation_sync_flushes_nested_payload_before_directories(self):
        import os,stat
        root=self.root/'generation';(root/'nested').mkdir(parents=True)
        (root/'nested/payload').write_bytes(b'complete');events=[]
        def sync(fd):events.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
        with patch.object(client.os,'fsync',side_effect=sync):client.sync_tree(root)
        self.assertEqual(['file','directory','directory'],events)
        (root/'link').symlink_to(root/'nested/payload')
        with self.assertRaisesRegex(ValueError,'non-regular'):client.sync_tree(root)

    def test_configuration_rejects_ambiguous_or_linked_destinations(self):
        self.assertEqual(self.value,client.configuration(self.value))
        for key,value in [('schema_version',True),('target','linux-unknown'),('policy_sha256','x'),('location','/'),('selection',{'track':'latest','format':'unknown'})]:
            with self.subTest(key=key), self.assertRaises(ValueError):client.configuration(dict(self.value,**{key:value}))
        (self.root/'alias').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):client.configuration(dict(self.value,location=str(self.root/'alias/state')))

    def test_only_qualified_target_is_automatically_selected(self):
        value=dict(self.value,selection={'track':'qualified'})
        def row(sequence,**kwargs):
            return dict(tag_name=f'distro-1.2.3-x86_64-r1-s{sequence}',draft=False,prerelease=False,
                body=json.dumps(dict(kind='signed-distribution',manifest_sha256='c'*64,native_qualification=marker())),**kwargs)
        from unittest.mock import Mock
        remote=Mock();remote.pages.return_value=[row(7),dict(row(8),prerelease=True),dict(row(9),draft=True)]
        self.assertEqual('distro-1.2.3-x86_64-r1-s7',client.select(value,remote)['tag'])
        remote.pages.return_value=[row(7),row(7)]
        with self.assertRaisesRegex(ValueError,'ambiguous'):client.select(value,remote)
        remote.pages.return_value=[dict(row(7),body=json.dumps(dict(kind='signed-distribution',manifest_sha256='c'*64,native_qualification={})))]
        with self.assertRaises(ValueError):client.select(value,remote)

    def test_native_configs_require_signatures_and_regular_update_adapter(self):
        for kind in ('apt','arch','gentoo'):
            text=client.native_config(self.value,kind,'/trusted/tools/distro_client.py','/etc/foundation.json')
            self.assertIn('/current/',text)
            self.assertNotIn('SigLevel = Never',text)
        self.assertIn('Signed-By:',client.native_config(self.value,'apt','/tool','/cfg'))
        self.assertIn('auto-sync = yes',client.native_config(self.value,'gentoo','/tool','/cfg'))
        compile(client.PORTAGE_ADAPTER,'adapter','exec')

    def test_rollback_and_package_replacement_are_rejected(self):
        spec={'version':'1.2.3','package_release':1}
        previous={'request':dict(repository='example/project',target='linux-x86_64',trusted_fingerprint='A'*40,sequence=7),
                  'backends':['core'],'specifications':{'core':spec}}
        client.advance(previous,copy.deepcopy(previous))
        for changed in (dict(previous,request=dict(previous['request'],sequence=6)),
                        dict(previous,backends=[]),
                        dict(previous,request=dict(previous['request'],sequence=8),specifications={'core':dict(spec,version='1.2.2')}),
                        dict(previous,request=dict(previous['request'],sequence=8),specifications={'core':dict(spec,extra='replacement')})):
            with self.assertRaises(ValueError):client.advance(previous,changed)


@unittest.skipUnless(sys.platform.startswith('linux'), 'native Linux upgrade orchestration')
class NativeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.value = config(self.root/'channel')
        self.generation = self.root/'channel/generations'/('7-'+'c'*64)
        self.result = {'changed':True, 'tag':self.value['selection']['tag'], 'sequence':7, 'manifest_sha256':'c'*64}
        self.manifest = {'tag':self.result['tag'], 'request':{'sequence':7,'target':'linux-x86_64'}}

    def enter(self, stack, *, kind='apt'):
        from contextlib import nullcontext
        patches = [(client.os, 'geteuid', {'return_value':0}), (client.os, 'access', {'return_value':True}),
            (client, 'locked', {'side_effect':lambda path:nullcontext()}),
            (client, 'current', {'return_value':self.generation}),
            (client, 'previous_identity', {'return_value':self.manifest}),
            (client, 'channel_format', {'return_value':'distribution'}),
            (client.release.archive, 'digest', {'return_value':'b'*64}),
            (client.release, 'verify_native', {'return_value':self.manifest}),
            (client.release, 'verify_native_channels', {})]
        for obj, name, options in patches: stack.enter_context(patch.object(obj, name, create=(name == 'geteuid'), **options))
        refresh = stack.enter_context(patch.object(client, 'refresh', return_value=self.result))
        run = stack.enter_context(patch.object(client.subprocess, 'run'))
        return refresh, run

    def test_verified_refresh_precedes_interactive_native_commands(self):
        from contextlib import ExitStack
        for kind in ('apt','arch'):
            with self.subTest(kind=kind), ExitStack() as stack:
                refresh, run = self.enter(stack); events = []
                refresh.side_effect = lambda *args: events.append('verified-refresh') or self.result
                run.side_effect = lambda command, **kwargs: events.append(command)
                self.assertEqual(client.native_upgrade(self.value, self.root/'policy', kind)['native_upgrade'], 'completed')
                self.assertEqual(events[0], 'verified-refresh')
                expected = ([['/usr/bin/apt-get','update','-o','APT::Update::Error-Mode=any'],
                             ['/usr/bin/apt-get','upgrade']] if kind == 'apt' else [['/usr/bin/pacman','-Syu']])
                self.assertEqual(events[1:], expected)
                self.assertTrue(all(call.kwargs == {'check':True} for call in run.call_args_list))

    def test_refresh_verification_or_native_update_failure_stops_upgrade(self):
        from contextlib import ExitStack
        import subprocess
        for stage in ('refresh','signature','channel','update'):
            with self.subTest(stage=stage), ExitStack() as stack:
                refresh, run = self.enter(stack)
                if stage == 'refresh': refresh.side_effect = ValueError('refresh rejected')
                elif stage == 'signature': client.release.verify_native.side_effect = ValueError('signature rejected')
                elif stage == 'channel': client.release.verify_native_channels.side_effect = ValueError('channel changed')
                else: run.side_effect = subprocess.CalledProcessError(1, ['apt-get','update'])
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    client.native_upgrade(self.value, self.root/'policy', 'apt')
                self.assertEqual(run.call_count, 1 if stage == 'update' else 0)

    def test_generation_race_and_missing_tools_fail_before_native_command(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            refresh, run = self.enter(stack)
            client.previous_identity.return_value = {'tag':'changed','request':{'sequence':8}}
            with self.assertRaisesRegex(ValueError, 'generation changed'):
                client.native_upgrade(self.value, self.root/'policy', 'apt')
            run.assert_not_called()
        with ExitStack() as stack:
            refresh, run = self.enter(stack); client.os.access.return_value = False
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                client.native_upgrade(self.value, self.root/'policy', 'apt')
            refresh.assert_not_called(); run.assert_not_called()

    def test_unsupported_scope_and_unprivileged_operation_do_not_refresh(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            refresh, run = self.enter(stack)
            for kind in ('gentoo','custom;command'):
                with self.assertRaises(ValueError): client.native_upgrade(self.value, self.root/'policy', kind)
            client.os.geteuid.return_value = 1000
            with self.assertRaisesRegex(ValueError, 'requires root'):
                client.native_upgrade(self.value, self.root/'policy', 'apt')
            refresh.assert_not_called(); run.assert_not_called()


class IntegratedClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.value = config(self.root/'state')
        self.tag = 'release-123-attempt-1'
        self.selected = dict(format=client.PACKAGE_FORMAT, tag=self.tag, manifest_sha256='c'*64)

    def test_latest_and_exact_integrated_selections_are_explicit_and_bounded(self):
        for selected in ({'track':'latest'}, {'track':'latest','format':client.PACKAGE_FORMAT}, self.selected):
            value = dict(self.value, selection=selected)
            self.assertEqual(value, client.configuration(value))
        for selected in ({'track':'latest','tag':self.tag}, dict(self.selected,format='distribution'),
                         dict(self.selected,manifest_sha256='x'), {'track':'qualified','format':client.PACKAGE_FORMAT}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                client.configuration(dict(self.value,selection=selected))

    def test_latest_pins_only_pointer_and_exact_packages_asset_without_legacy_scan(self):
        remote = Mock(); info = dict(id=17, tag_name=self.tag, draft=False, prerelease=False)
        remote.json.return_value = info
        remote.pages.return_value = [dict(id=18,name='packages.json',size=100,state='uploaded',digest='sha256:'+'c'*64)]
        selected = client.select(dict(self.value,selection={'track':'latest'}),remote)
        self.assertEqual(self.selected,selected)
        remote.json.assert_called_once_with('repos/example/project/releases/latest')
        remote.pages.assert_called_once_with('repos/example/project/releases/17/assets?per_page=100')
        for rows in ([], remote.pages.return_value*2,
                     [dict(remote.pages.return_value[0],digest=None)],
                     [dict(remote.pages.return_value[0],size=client.MAX_JSON+1)]):
            remote.pages.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                client.select(dict(self.value,selection={'track':'latest'}),remote)
        remote.json.return_value = dict(info,prerelease=True); remote.pages.reset_mock()
        with self.assertRaises(ValueError): client.select(dict(self.value,selection={'track':'latest'}),remote)
        remote.pages.assert_not_called()

    def test_public_latest_single_release_binding_does_not_need_release_history(self):
        remote = client.PublicGitHub('example/project')
        info = dict(id=17, tag_name=self.tag, draft=False, prerelease=False)
        rows = [asset_row(18,'packages.json',b'{}',self.tag)]
        with patch.object(remote,'json',return_value=info), patch.object(remote,'pages',return_value=rows):
            selected = client.select(dict(self.value,selection={'track':'latest'}),remote)
        self.assertEqual({17:self.tag},remote.releases)
        remote.remember('repos/example/project/releases/17/assets?per_page=100',rows)
        self.assertEqual(hashlib.sha256(b'{}').hexdigest(),selected['manifest_sha256'])
        with self.assertRaisesRegex(ValueError,'identity changed'):
            remote.observe_release(dict(info,tag_name='foreign-tag'))

    def test_public_transport_admits_exact_repository_visibility_and_rejects_foreign_routes(self):
        remote = client.PublicGitHub('example/project')
        response = asset_response(b'{}','https://api.github.com/repos/example/project')
        with patch.object(client,'urlopen',return_value=response) as request:
            self.assertIs(response,remote.request('repos/example/project'))
            self.assertEqual('https://api.github.com/repos/example/project',request.call_args.args[0].full_url)
            for route in ('repos/foreign/project','repos/example/project-foreign/releases'):
                with self.subTest(route=route),self.assertRaisesRegex(ValueError,'escaped'):
                    remote.request(route)
            self.assertEqual(1,request.call_count)
        response.close()

    def test_manifest_identity_and_integrated_api_routing_keep_legacy_independent(self):
        assets = self.root/'assets'; assets.mkdir(); (assets/'packages.json').write_bytes(b'{}')
        module = Mock(); view = {'format':client.PACKAGE_FORMAT,'request':{'target':'linux-x86_64'}}
        module.verify.return_value = view; module.fetch.return_value = view
        self.assertEqual(hashlib.sha256(b'{}').hexdigest(),client.manifest_digest(assets))
        with self.assertRaisesRegex(ValueError,'format differs'): client.manifest_digest(assets,'distribution')
        with patch.object(client,'package_tools',return_value=module), patch.object(client.release,'verify_native') as old_verify, \
                patch.object(client.release,'fetch') as old_fetch:
            self.assertEqual(view,client.verify_channel(assets,'policy','A'*40,target='linux-x86_64',format=client.PACKAGE_FORMAT))
            selected = dict(self.selected,target='linux-x86_64')
            self.assertEqual(view,client.fetch_channel(selected,'example/project',self.root/'fetch','policy','A'*40))
            module.verify.assert_called_once_with(assets,'policy','A'*40,target='linux-x86_64')
            module.fetch.assert_called_once_with('example/project',self.tag,'c'*64,self.root/'fetch','policy','A'*40,
                                                 target='linux-x86_64',transport=None)
            old_verify.assert_not_called(); old_fetch.assert_not_called()
        (assets/'distribution.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'one exact'): client.manifest_digest(assets)

    def test_integrated_extraction_normalizes_only_fresh_directories(self):
        channels = self.root/'channels'; (channels/'apt').mkdir(parents=True,mode=0o700)
        (channels/'native/packages').mkdir(parents=True,mode=0o700)
        channels.chmod(0o700); (channels/'native').chmod(0o700)
        payload = channels/'apt/Packages'; payload.write_bytes(b'signed'); payload.chmod(0o644)
        module = Mock(); module.extract_channels.return_value = channels
        view = dict(format=client.PACKAGE_FORMAT,request={'target':'linux-x86_64'})
        with patch.object(client,'package_tools',return_value=module):
            self.assertEqual(channels,client.extract_channels('assets',channels,view))
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o755
                            for path in (channels,channels/'apt',channels/'native',channels/'native/packages')))
        self.assertEqual(0o644,payload.stat().st_mode & 0o777); self.assertEqual(b'signed',payload.read_bytes())

    def test_expired_predecessor_uses_signed_identity_and_raw_generation_digest(self):
        raw = b'{"expired":true}\n'; digest = hashlib.sha256(raw).hexdigest()
        generation = self.root/('7-'+digest); (generation/'assets').mkdir(parents=True)
        (generation/'assets/packages.json').write_bytes(raw)
        request = dict(repository='example/project',target='linux-x86_64',trusted_fingerprint='A'*40,sequence=7)
        view = dict(format=client.PACKAGE_FORMAT,request=request)
        module = Mock(); module.native_identity.return_value = view
        with patch.object(client,'package_tools',return_value=module):
            self.assertEqual(view,client.previous_identity(generation,self.value))
            module.native_identity.assert_called_once_with(generation/'assets','A'*40,target='linux-x86_64')
            module.verify.assert_not_called()
            (generation/'assets/packages.json').write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'generation name'):
                client.previous_identity(generation,self.value)
            (generation/'assets/packages.json').write_bytes(raw)
            module.native_identity.return_value = dict(view,request=dict(request,repository='foreign/project'))
            with self.assertRaisesRegex(ValueError,'trust or target'):
                client.previous_identity(generation,self.value)

    def test_cross_format_upgrade_retains_strict_version_and_specification_rules(self):
        before = dict(request=dict(repository='example/project',target='linux-x86_64',trusted_fingerprint='A'*40,sequence=7),
                      backends=['core'],specifications={'core':dict(version='1.2.3',package_release=1)})
        after = copy.deepcopy(before); after['format'] = client.PACKAGE_FORMAT; after['request']['sequence'] = 8
        client.advance(before,after)
        changed = copy.deepcopy(after); changed['specifications']['core']['archive_url'] = 'replacement'
        with self.assertRaisesRegex(ValueError,'same-version'): client.advance(before,changed)
        changed['specifications']['core']['package_release'] = 2
        client.advance(before,changed)


@unittest.skipUnless(sys.platform.startswith('linux') and all(shutil.which(x) for x in ('cc','dpkg-deb','gpg','gpgv','gpgconf','git')),
                     'actual Linux ELF and signing prerequisites required')
class SignedClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=fixtures.SignedDistributionTests
        cls.fixture.setUpClass();cls.addClassCleanup(cls.fixture.doClassCleanups)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=self.fixture.root);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.f=self.fixture
        self.value=dict(config(self.root/'state'),target=self.f.req['target'],trusted_fingerprint=self.f.trusted,
            policy_sha256=client.release.archive.digest(self.f.policy),selection={'tag':self.f.frozen['tag'],
                'manifest_sha256':client.release.archive.digest(self.f.prepared/'distribution.json')})

    def test_native_upgrade_consumes_real_signed_generation_and_refuses_changed_payload(self):
        original_refresh = client.refresh; original_run = client.subprocess.run; commands = []
        def execute(command, **kwargs):
            if str(command[0]) == '/usr/bin/apt-get':
                commands.append(command)
                return client.subprocess.CompletedProcess(command, 0)
            return original_run(command, **kwargs)
        def refresh(value, policy):
            return original_refresh(value, policy, prepared=self.f.prepared)
        with patch.object(client.os, 'geteuid', return_value=0), \
                patch.object(client.os, 'access', return_value=True), \
                patch.object(client, 'refresh', side_effect=refresh), \
                patch.object(client.subprocess, 'run', side_effect=execute):
            result = client.native_upgrade(self.value, self.f.policy, 'apt')
            self.assertEqual(result['manifest_sha256'], self.value['selection']['manifest_sha256'])
            self.assertEqual(len(commands), 2)
            generation = client.current(self.value['location'])
            (generation/'channels/unexpected').write_bytes(b'changed')
            commands.clear()
            with self.assertRaisesRegex(ValueError, 'derived channel changed'):
                client.native_upgrade(self.value, self.f.policy, 'apt')
            self.assertEqual(commands, [])
            self.assertEqual(client.current(self.value['location']), generation)

    def test_prepared_verified_generation_refresh_is_idempotent_and_preserves_old_state_on_tampering(self):
        first=client.refresh(self.value,self.f.policy,prepared=self.f.prepared)
        self.assertTrue(first['changed']);current=client.current(self.root/'state')
        self.assertFalse(client.refresh(self.value,self.f.policy,prepared=self.f.prepared)['changed'])
        changed=self.root/'changed';shutil.copytree(self.f.prepared,changed)
        (changed/'Packages').write_bytes(b'tampered')
        with self.assertRaises(ValueError):client.refresh(self.value,self.f.policy,prepared=changed)
        self.assertEqual(current,client.current(self.root/'state'))
        (current/'channels/native/gentoo/foreign').write_bytes(b'foreign')
        (current/'channels/native/gentoo/foreign').chmod(0o644)
        with self.assertRaisesRegex(ValueError,'derived channel changed'):client.refresh(self.value,self.f.policy,prepared=self.f.prepared)
        self.assertEqual(current,client.current(self.root/'state'))

    def test_projected_refresh_downloads_only_native_assets_then_small_controls(self):
        remote = self.f.f.remote
        # Fixture publication is preserved; each test has its own public copy.
        transport = fixtures.fixtures.FakeGitHub()
        transport.releases = copy.deepcopy(remote.releases)
        transport.refs = copy.deepcopy(remote.refs)
        transport.data = copy.deepcopy(remote.data)
        transport.next_asset = remote.next_asset
        transport.next_id = remote.next_id
        client.release.publish(self.f.prepared, self.f.policy, self.f.trusted, execute=True, transport=transport)
        transport.calls.clear()
        first = client.refresh(self.value, self.f.policy, transport=transport)
        self.assertTrue(first['changed'])
        active = client.current(self.root/'state')
        self.assertEqual(client.release.NATIVE_ASSETS, {p.name for p in (active/'assets').iterdir()})
        observed = {call[1] for call in transport.calls if call[0] == 'download'}
        rows = {row['id']: row['name'] for row in transport.releases[-1]['assets']}
        self.assertEqual(client.release.NATIVE_ASSETS, {rows[name] for name in observed})
        transport.calls.clear()
        self.assertFalse(client.refresh(self.value, self.f.policy, transport=transport)['changed'])
        observed = {rows[call[1]] for call in transport.calls if call[0] == 'download'}
        self.assertEqual(client.release.NATIVE_ASSETS - {'channels.tar.gz'}, observed)
        # A damaged private recipe cannot be hidden by an unchanged remote tag.
        foreign = active/'channels/native/gentoo/foreign'; foreign.write_bytes(b'foreign'); foreign.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'derived channel changed'):
            client.refresh(self.value, self.f.policy, transport=transport)
        self.assertEqual(active, client.current(self.root/'state'))

    def test_public_asset_refresh_replays_signed_inventory_and_preserves_active_generation_on_bad_bytes(self):
        tag = self.f.frozen['tag']; bodies = {}; rows = []
        for identity, path in enumerate(sorted(self.f.prepared.iterdir()), 1):
            row = asset_row(identity, path.name, path.read_bytes(), tag)
            rows.append(row); bodies[row['browser_download_url']] = path.read_bytes()
        info = dict(id=1, tag_name=tag, name=tag, draft=False, prerelease=True)
        def metadata(endpoint, **options):
            if '/releases/1/assets?' in endpoint: return rows
            if endpoint.endswith('/releases/1'): return info
            if '/releases?' in endpoint: return [info]
            if '/git/ref/tags/' in endpoint: return {'object': {'type': 'commit', 'sha': self.f.req['packager_commit']}}
            if endpoint.endswith('/releases/latest'): return None
            self.fail('unexpected REST request: ' + endpoint)
        transport = client.PublicGitHub('example/project')
        with patch.object(transport, 'json', side_effect=metadata), patch.object(client, 'build_opener') as build:
            build.return_value.open.side_effect = lambda request, **options: asset_response(bodies[request.full_url])
            self.assertTrue(client.refresh(self.value, self.f.policy, transport=transport)['changed'])
            current = client.current(self.root/'state')
            manifest_url = next(url for url in bodies if url.endswith('/distribution.json'))
            bodies[manifest_url] += b'changed'
            with self.assertRaises(ValueError): client.refresh(self.value, self.f.policy, transport=transport)
            self.assertEqual(current, client.current(self.root/'state'))
            self.assertEqual(client.release.verify_native(current/'assets', self.f.policy, self.f.trusted), self.f.frozen)

    def test_transient_public_asset_refresh_recovers_then_exhausts_preserving_signed_generation(self):
        client.refresh(self.value, self.f.policy, prepared=self.f.prepared)
        current = client.current(self.root / 'state'); tag = self.f.frozen['tag']
        rows = [asset_row(i, path.name, path.read_bytes(), tag)
                for i, path in enumerate(sorted(self.f.prepared.iterdir()), 1)]
        bodies = {row['browser_download_url']: (self.f.prepared / row['name']).read_bytes() for row in rows}
        info = dict(id=1, tag_name=tag, name=tag, draft=False, prerelease=True)
        def metadata(endpoint, **options):
            if '/releases/1/assets?' in endpoint: return rows
            if endpoint.endswith('/releases/1'): return info
            if '/releases?' in endpoint: return [info]
            if '/git/ref/tags/' in endpoint: return {'object': {'type': 'commit', 'sha': self.f.req['packager_commit']}}
            if endpoint.endswith('/releases/latest'): return None
            self.fail('unexpected REST request: ' + endpoint)
        errors = []
        def failure():
            error = client.HTTPError('https://release-assets.githubusercontent.com/object?signature=private',
                500, 'private reason', {}, io.BytesIO(b'private body'))
            errors.append(error); return error
        def recovering(request, **options):
            if not errors: raise failure()
            return asset_response(bodies[request.full_url])
        transport = client.PublicGitHub('example/project')
        with patch.object(transport, 'json', side_effect=metadata), patch.object(client, 'build_opener') as build, \
                patch.object(client.time, 'sleep'), patch.object(client.release.delivery.random, 'uniform', return_value=0):
            build.return_value.open.side_effect = recovering
            self.assertFalse(client.refresh(self.value, self.f.policy, transport=transport)['changed'])
            self.assertEqual(len(errors), 1); self.assertTrue(errors[0].closed)
            self.assertEqual(client.current(self.root / 'state'), current)
            def rejected(*args, **kwargs): raise failure()
            build.return_value.open.side_effect = rejected; build.return_value.open.reset_mock()
            with self.assertRaisesRegex(ValueError, 'public asset id=.*attempt limit exhausted.*HTTP 500'):
                client.refresh(self.value, self.f.policy, transport=transport)
            self.assertEqual(build.return_value.open.call_count, 3)
        self.assertTrue(all(error.closed for error in errors))
        self.assertEqual(client.current(self.root / 'state'), current)
        self.assertEqual(client.release.verify_native(current / 'assets', self.f.policy, self.f.trusted), self.f.frozen)
        self.assertEqual(list((self.root / 'state').glob('.refresh-*')), [])
        self.assertEqual(list((self.root / 'state/generations').iterdir()), [current])

    def test_public_rate_exhaustion_preserves_verified_active_generation(self):
        client.refresh(self.value, self.f.policy, prepared=self.f.prepared)
        current = client.current(self.root/'state')
        error = client.HTTPError('https://api.github.com/repos/example/project/releases', 403, 'rate limited',
            {'x-ratelimit-remaining': '0', 'retry-after': '150'}, io.BytesIO(b'{"message":"API rate limit exceeded."}'))
        # 150 seconds exceeds the public 120-second wait budget but fits its
        # 180-second request deadline. Freeze elapsed time and jitter so this
        # assertion tests budget exhaustion independently of deadline precedence.
        # Bind the transport's clock without changing stdlib subprocess/GPG waits.
        sleep = Mock()
        clock = SimpleNamespace(monotonic=lambda: 100, time=client.release.delivery.time.time, sleep=sleep)
        with patch.object(client, 'urlopen', side_effect=error) as request, \
                patch.object(client, 'build_opener') as download, \
                patch.object(client.release.delivery, 'time', clock), \
                patch.object(client.release.delivery.random, 'uniform', return_value=0):
            with self.assertRaisesRegex(ValueError, 'wait budget exhausted'):
                client.refresh(self.value, self.f.policy)
        self.assertEqual(request.call_count, 1); download.assert_not_called(); sleep.assert_not_called()
        self.assertTrue(error.closed)
        self.assertEqual(client.current(self.root/'state'), current)
        self.assertEqual(client.release.verify_native(current/'assets', self.f.policy, self.f.trusted), self.f.frozen)
        self.assertEqual(list((self.root/'state').glob('.refresh-*')), [])

    def test_payload_sync_failure_cannot_publish_generation_or_pointer(self):
        with patch.object(client,'sync_tree',side_effect=OSError('durability fixture')):
            with self.assertRaisesRegex(OSError,'durability fixture'):
                client.refresh(self.value,self.f.policy,prepared=self.f.prepared)
        self.assertIsNone(client.current(self.root/'state'))
        self.assertEqual([],list((self.root/'state/generations').iterdir()))

    def test_pointer_failure_leaves_complete_inactive_generation_for_exact_retry(self):
        with patch.object(client.os,'replace',side_effect=OSError('activation fixture')):
            with self.assertRaisesRegex(OSError,'activation fixture'):
                client.refresh(self.value,self.f.policy,prepared=self.f.prepared)
        self.assertIsNone(client.current(self.root/'state'))
        generations=list((self.root/'state/generations').iterdir());self.assertEqual(len(generations),1)
        self.assertTrue((generations[0]/'assets/distribution.json').is_file());self.assertTrue((generations[0]/'channels/apt/Packages').is_file())
        self.assertTrue(client.refresh(self.value,self.f.policy,prepared=self.f.prepared)['changed'])
        self.assertEqual(generations[0],client.current(self.root/'state'))

    def test_unsigned_previous_identity_and_changed_policy_cannot_be_used(self):
        client.refresh(self.value,self.f.policy,prepared=self.f.prepared)
        current=client.current(self.root/'state')
        manifest=current/'assets/distribution.json';manifest.write_bytes(manifest.read_bytes()+b' ')
        with self.assertRaises((ValueError,client.subprocess.SubprocessError)):client.refresh(self.value,self.f.policy,prepared=self.f.prepared)
        with self.assertRaisesRegex(ValueError,'policy'):client.refresh(dict(self.value,policy_sha256='0'*64),self.f.policy,prepared=self.f.prepared)


if __name__=='__main__':unittest.main()
