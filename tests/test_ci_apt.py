#!/usr/bin/env python3
"""Offline container APT recovery and mirror policy fixtures (no system writes)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/ci-apt.sh'


class CiAptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='foundation-ci-apt-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.apt = self.root / 'etc/apt'
        (self.apt / 'sources.list.d').mkdir(parents=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, CI_APT_ROOT=str(self.root),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        TEST_APT_ROOT=str(self.root), TEST_APT_ARCH='amd64')
        self.executable('dpkg', '#!/bin/sh\nprintf "%s\\n" "$TEST_APT_ARCH"\n')
        self.executable('sleep', '#!/bin/sh\nprintf "%s\\n" "$1" >> "$TEST_APT_ROOT/sleeps"\n')
        self.executable('apt-get', f'''#!{sys.executable}
import json, os, pathlib, sys
root = pathlib.Path(os.environ['TEST_APT_ROOT'])
with (root / 'calls').open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
steps = json.loads((root / 'steps.json').read_text())
if not steps:
    print('Unexpected extra APT call', file=sys.stderr)
    sys.exit(97)
step = steps.pop(0)
(root / 'steps.json').write_text(json.dumps(steps))
command = 'install' if 'install' in sys.argv else 'update'
if command != step['command']:
    print('Unexpected APT command: ' + command, file=sys.stderr)
    sys.exit(98)
print(step.get('output', ''), flush=True)
sys.exit(step.get('status', 0))
''')
        self.distro('ubuntu', 'noble')

    def executable(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def distro(self, name, codename, arch='amd64'):
        (self.root / 'etc/os-release').write_text(f'ID={name}\nVERSION_CODENAME={codename}\n')
        self.env['TEST_APT_ARCH'] = arch

    def source(self, text, name='sources.list'):
        path = self.apt / name
        path.write_text(text)
        return path

    def run_helper(self, *args, steps=(), expected=0):
        (self.root / 'steps.json').write_text(json.dumps(list(steps)))
        result = subprocess.run(['sh', str(HELPER), *args], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.root / 'steps.json').read_text()), [])
        return result

    def calls(self):
        return [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]

    @staticmethod
    def step(command, output='', status=0):
        return dict(command=command, output=output, status=status)

    def test_ubuntu_legacy_sources_keep_options_and_prefer_azure(self):
        source = self.source('deb [arch=amd64 signed-by=/keys/ubuntu.gpg] http://archive.ubuntu.com/ubuntu/ noble main universe\n'
                             'deb-src http://security.ubuntu.com/ubuntu noble-security main\n')
        self.run_helper('configure')
        self.assertEqual(source.read_text(),
                         f'deb [arch=amd64 signed-by=/keys/ubuntu.gpg] mirror+file:{self.apt}/ci-ubuntu-http.mirrors noble main universe\n'
                         f'deb-src mirror+file:{self.apt}/ci-ubuntu-http.mirrors noble-security main\n')
        mirrors = (self.apt / 'ci-ubuntu-http.mirrors').read_text().splitlines()
        self.assertEqual(mirrors, ['http://azure.archive.ubuntu.com/ubuntu/\tpriority:1',
                                  'http://archive.ubuntu.com/ubuntu/\tpriority:2',
                                  'http://security.ubuntu.com/ubuntu/\tpriority:3'])

    def test_deb822_https_preserves_tls_security_suites_and_key(self):
        source = self.source('Types: deb deb-src\nURIs: https://archive.ubuntu.com/ubuntu/\n'
                             'Suites: noble noble-updates noble-backports noble-security\n'
                             'Components: main universe restricted multiverse\n'
                             'Architectures: amd64\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n',
                             'sources.list.d/ubuntu.sources')
        before = source.read_text()
        self.run_helper('configure')
        self.assertEqual(source.read_text(), before.replace('https://archive.ubuntu.com/ubuntu/',
                         f'mirror+file:{self.apt}/ci-ubuntu-https.mirrors'))
        self.assertTrue(all(line.startswith('https://') for line in
                            (self.apt / 'ci-ubuntu-https.mirrors').read_text().splitlines()))

    def test_third_party_and_lookalike_uris_remain_verbatim(self):
        original = ('# deb http://archive.ubuntu.com/ubuntu noble main\n'
                    'deb https://packages.microsoft.com/repos/code stable main\n'
                    'deb https://github.com/owner/project/releases/download/tag/ ./\n'
                    'deb http://archive.ubuntu.com/ubuntu-other noble main\n'
                    'deb https://example.invalid/?origin=http://archive.ubuntu.com/ubuntu noble main\n'
                    'deb https://archive.ubuntu.com.evil.invalid/ubuntu noble main\n')
        source = self.source(original)
        self.run_helper('configure')
        self.assertEqual(source.read_text(), original)

    def test_adjacent_deb822_uris_are_each_rewritten(self):
        source = self.source('Types: deb\nURIs: http://archive.ubuntu.com/ubuntu http://archive.ubuntu.com/ubuntu/\n'
                             'Suites: noble\nComponents: main\n', 'sources.list.d/ubuntu.sources')
        self.run_helper('configure')
        self.assertEqual(source.read_text().count('mirror+file:'), 2)

    def test_debian_archive_and_security_have_separate_fallbacks(self):
        self.distro('debian', 'bookworm', 'arm64')
        source = self.source('Types: deb\nURIs: http://deb.debian.org/debian\nSuites: bookworm bookworm-updates\n'
                             'Components: main\nSigned-By: /keys/debian.gpg\n\n'
                             'Types: deb\nURIs: http://security.debian.org/debian-security\n'
                             'Suites: bookworm-security\nComponents: main\nSigned-By: /keys/debian.gpg\n',
                             'sources.list.d/debian.sources')
        self.run_helper('configure')
        contents = source.read_text()
        self.assertIn(f'URIs: mirror+file:{self.apt}/ci-debian-http.mirrors\n', contents)
        self.assertIn(f'URIs: mirror+file:{self.apt}/ci-debian-security-http.mirrors\n', contents)
        self.assertEqual(contents.count('Signed-By: /keys/debian.gpg'), 2)
        security = (self.apt / 'ci-debian-security-http.mirrors').read_text()
        self.assertEqual(security, 'http://deb.debian.org/debian-security/\tpriority:1\n'
                                  'http://security.debian.org/debian-security/\tpriority:2\n')

    def test_debian_cdn_security_is_not_rewritten_as_main_archive(self):
        self.distro('debian', 'trixie')
        source = self.source('deb http://deb.debian.org/debian-security/ trixie-security main\n')
        self.run_helper('configure')
        self.assertEqual(source.read_text(),
                         f'deb mirror+file:{self.apt}/ci-debian-security-http.mirrors trixie-security main\n')

    def test_older_arm_and_other_ports_remain_on_ports(self):
        for codename, arch in [('jammy', 'arm64'), ('noble', 'arm64'), ('resolute', 'armhf')]:
            with self.subTest(codename=codename, arch=arch):
                self.distro('ubuntu', codename, arch)
                original = f'deb http://ports.ubuntu.com/ubuntu-ports {codename} main universe\n'
                source = self.source(original)
                self.run_helper('configure')
                self.assertEqual(source.read_text(), original)

    def test_resolute_arm64_can_use_azure_main_archive(self):
        self.distro('ubuntu', 'resolute', 'arm64')
        source = self.source('deb http://archive.ubuntu.com/ubuntu resolute main\n')
        self.run_helper('configure')
        self.assertIn('ci-ubuntu-http.mirrors', source.read_text())

    def test_configuration_is_idempotent_and_persists_strict_policy(self):
        source = self.source('deb http://archive.ubuntu.com/ubuntu noble main\n')
        self.run_helper('configure')
        original = source.read_text()
        self.run_helper('configure')
        self.assertEqual(source.read_text(), original)
        policy = (self.apt / 'apt.conf.d/99foundation-ci').read_text()
        self.assertIn('Acquire::Retries "3";', policy)
        self.assertIn('Acquire::http::Timeout "30";', policy)
        self.assertIn('APT::Update::Error-Mode "any";', policy)
        self.assertNotRegex(policy, r'(?i)(AllowUnauthenticated|AllowInsecure|Verify-Peer|Check-Valid-Until)')

    def test_install_refreshes_before_retrying_a_stale_package_404(self):
        result = self.run_helper('install', 'libexpat1', 'python3', steps=[
            self.step('update'),
            self.step('install', 'E: Failed to fetch http://security.ubuntu.com/ubuntu/pool/libexpat1.deb  404 Not Found', 100),
            self.step('update'), self.step('install')])
        calls = self.calls()
        self.assertEqual(['install' if 'install' in call else 'update' for call in calls],
                         ['update', 'install', 'update', 'install'])
        self.assertEqual(calls[1][-5:], ['install', '-y', '--no-install-recommends', 'libexpat1', 'python3'])
        for call in calls:
            self.assertIn('Acquire::Retries=3', call)
            self.assertIn('APT::Update::Error-Mode=any', call)
        self.assertEqual((self.root / 'sleeps').read_text(), '5\n')
        self.assertNotIn('Acquire::http::No-Cache=true', calls[0])
        self.assertIn('Acquire::http::No-Cache=true', calls[2])
        self.assertIn('attempt 2/3', result.stdout)

    def test_partial_update_fetch_failure_retries_before_install(self):
        self.run_helper('install', 'git', steps=[
            self.step('update', 'E: Failed to fetch http://deb.debian.org/debian/dists/bookworm/InRelease Temporary failure resolving deb.debian.org', 100),
            self.step('update'), self.step('install')])
        self.assertEqual(sum('install' in call for call in self.calls()), 1)

    def test_recovery_exhaustion_is_fatal_and_bounded(self):
        steps = []
        for _ in range(3):
            steps += [self.step('update'), self.step('install',
                      'E: Failed to fetch http://mirror.invalid/missing.deb 404 Not Found', 100)]
        result = self.run_helper('install', 'package', steps=steps, expected=100)
        self.assertEqual(len(self.calls()), 6)
        self.assertEqual((self.root / 'sleeps').read_text(), '5\n15\n')
        self.assertIn('exhausted after 3 attempts', result.stderr)

    def test_update_only_retries_transient_http_failure(self):
        self.run_helper('update', steps=[
            self.step('update', 'E: Failed to fetch http://mirror.invalid/InRelease 503 Service Unavailable', 100),
            self.step('update')])
        self.assertEqual(len(self.calls()), 2)

    def test_authentication_and_non_network_errors_are_immediately_fatal(self):
        errors = [
            'E: The repository http://mirror.invalid stable InRelease is not signed.',
            'E: Failed to fetch https://mirror.invalid/InRelease Certificate verification failed.',
            'W: GPG error: NO_PUBKEY 0123456789ABCDEF\nE: Failed to fetch http://mirror.invalid/InRelease 503 Service Unavailable',
            'E: Failed to fetch http://mirror.invalid/package.deb Hash Sum mismatch',
            'E: Unable to locate package does-not-exist',
            'dpkg: error processing package broken\nE: Failed to fetch http://mirror.invalid/package.deb 404 Not Found',
            'E: The repository http://mirror.invalid missing Release does not have a Release file.',
            'E: Disk quota exceeded',
        ]
        for error in errors:
            with self.subTest(error=error):
                self.run_helper('install', 'package', steps=[self.step('update'),
                                self.step('install', error, 100)], expected=100)
                self.assertFalse((self.root / 'sleeps').exists())

    def test_unknown_distribution_keeps_its_repositories(self):
        self.distro('other', 'custom')
        original = 'deb http://archive.ubuntu.com/ubuntu noble main\n'
        source = self.source(original)
        self.run_helper('configure')
        self.assertEqual(source.read_text(), original)

    def test_usage_errors_fail_before_running_apt(self):
        for args in [(), ('install',), ('configure', 'extra'), ('update', 'extra'), ('upgrade',)]:
            with self.subTest(args=args):
                self.run_helper(*args, expected=2)
        self.assertFalse((self.root / 'calls').exists())


if __name__ == '__main__':
    unittest.main()
