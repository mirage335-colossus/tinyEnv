"""Private credential fixtures only: no real keys or network activity."""

import importlib
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest import mock

from workbench.services import credentials


_guards = []


def _no_network(*args, **kwargs):
    raise AssertionError('Credential tests must not contact external services.')


def setUpModule():
    for name in ('create_connection', 'getaddrinfo'):
        guard = mock.patch.object(socket, name, side_effect=_no_network)
        guard.start()
        _guards.append(guard)
    for name in ('connect', 'connect_ex', 'sendto'):
        guard = mock.patch.object(socket.socket, name, side_effect=_no_network)
        guard.start()
        _guards.append(guard)


def tearDownModule():
    while _guards:
        _guards.pop().stop()


class CredentialLocationTests(unittest.TestCase):
    def test_import_and_default_location_do_not_open_files(self):
        home = Path(tempfile.gettempdir()) / 'fake-home'
        with mock.patch.object(os, 'open', side_effect=self.fail), \
                mock.patch.object(Path, 'open', side_effect=self.fail), \
                mock.patch.dict(os.environ, {'HOME': str(home)}, clear=True), \
                mock.patch.object(credentials.sys, 'platform', 'linux'):
            importlib.reload(credentials)
            self.assertEqual(credentials.default_config_directory(), home / '.config' / 'tinyEnv')

    def test_defaults_match_native_preferences_for_supported_platforms(self):
        home = Path(tempfile.gettempdir()) / 'fake-home'
        xdg = Path(tempfile.gettempdir()) / 'fake-xdg'
        appdata = Path(tempfile.gettempdir()) / 'fake-appdata'
        profile = Path(tempfile.gettempdir()) / 'fake-profile'
        cases = (
            ('linux', {'HOME': str(home)}, home / '.config' / 'tinyEnv'),
            ('linux', {'XDG_CONFIG_HOME': str(xdg)}, xdg / 'tinyEnv'),
            ('linux', {'HOME': str(home), 'XDG_CONFIG_HOME': ''}, home / '.config' / 'tinyEnv'),
            ('darwin', {'HOME': str(home)}, home / 'Library' / 'Application Support' / 'tinyEnv'),
            ('win32', {'APPDATA': str(appdata)}, appdata / 'tinyEnv'),
            ('win32', {'USERPROFILE': str(profile)}, profile / 'AppData' / 'Roaming' / 'tinyEnv'),
        )
        for platform, environment, expected in cases:
            with self.subTest(platform=platform, expected=expected), \
                    mock.patch.object(credentials.sys, 'platform', platform), \
                    mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(credentials.default_config_directory(), Path(expected))
        for environment in ({}, {'HOME': 'fake-relative-home'},
                            {'HOME': str(home), 'XDG_CONFIG_HOME': 'fake-relative-xdg'}):
            with self.subTest(environment=environment), \
                    mock.patch.object(credentials.sys, 'platform', 'linux'), \
                    mock.patch.dict(os.environ, environment, clear=True), \
                    self.assertRaises(credentials.CredentialError) as caught:
                credentials.default_config_directory()
            self.assertNotIn('fake-relative', str(caught.exception))

    def test_unqualified_host_preserves_implicit_environment_fallback_only(self):
        with mock.patch.object(credentials, '_qualified_posix', return_value=False), \
                mock.patch.object(credentials, '_directory_parts', side_effect=self.fail):
            self.assertIsNone(credentials.load_saved_key('openai'))
            with self.assertRaises(credentials.CredentialError) as caught:
                credentials.load_saved_key('openai', '/private-fixture-store')
            self.assertNotIn('/private-fixture-store', str(caught.exception))


@unittest.skipUnless(credentials._qualified_posix(), 'Requires qualified POSIX private storage primitives')
class CredentialReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tinyenv-private-key-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'application'
        self.config.mkdir(mode=0o700)
        self.store = self.config / 'credentials'
        self.store.mkdir(mode=0o700)

    def keyfile(self, provider='openai', raw=b'fake-saved-key\n'):
        path = self.store / (provider + '.key')
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def test_supported_providers_are_isolated_and_boundary_keys_round_trip(self):
        self.keyfile('openai', b'fake-openai-key\n')
        self.keyfile('openrouter', b'fake-router-key\n')
        self.assertEqual(credentials.load_saved_key('openai', self.config), 'fake-openai-key')
        self.assertEqual(credentials.load_saved_key('openrouter', self.config), 'fake-router-key')
        for key in ('!', 'x' * credentials.MAX_KEY_BYTES, 'fake-\\"-key'):
            with self.subTest(length=len(key)):
                self.keyfile(raw=key.encode('ascii') + b'\n')
                self.assertEqual(credentials.load_saved_key('openai', self.config), key)
        for provider in ('ollama', 'unknown', '', None, []):
            with self.subTest(provider_type=type(provider).__name__), \
                    self.assertRaises(credentials.CredentialError):
                credentials.load_saved_key(provider, self.config)

    def test_absent_storage_has_no_side_effects(self):
        self.assertIsNone(credentials.load_saved_key('openai', self.config))
        self.store.rmdir()
        self.assertIsNone(credentials.load_saved_key('openai', self.config))
        self.config.rmdir()
        self.assertIsNone(credentials.load_saved_key('openai', self.config))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_directory_paths_are_sanitized(self):
        paths = ('private-fixture-relative', '/', str(self.config) + '/../private-fixture',
                 str(self.config) + '/./private-fixture', str(self.root / 'private-fixture:bad'),
                 str(self.root / 'private-fixture\\bad'), str(self.root / ('x' * 256)),
                 str(self.config) + '\0private-fixture', str(self.config) + '\ud800')
        for path in paths:
            with self.subTest(path_type='fixture'), self.assertRaises(credentials.CredentialError) as caught:
                credentials.load_saved_key('openai', path)
            self.assertNotIn('private-fixture', str(caught.exception))

    def test_malformed_keys_are_refused_without_returning_input(self):
        for raw in (b'', b'\n', b'fake-secret', b'fake-secret\n\n', b'fake secret\n',
                    b'fake\tsecret\n', b'fake-secret\r\n', b'fake\x00secret\n',
                    b'fake\x1bsecret\n', b'fake\x7fsecret\n', b'fake\x80secret\n',
                    b'x' * (credentials.MAX_KEY_BYTES + 1) + b'\n'):
            with self.subTest(length=len(raw)):
                self.keyfile(raw=raw)
                with self.assertRaises(credentials.CredentialError) as caught:
                    credentials.load_saved_key('openai', self.config)
                self.assertNotIn('fake', str(caught.exception))
                self.assertNotIn(str(self.config), str(caught.exception))

    def test_private_directory_and_file_permissions_are_enforced(self):
        path = self.keyfile()
        for selected, modes in ((self.config, (0o770, 0o702, 0o777)),
                                (self.store, (0o750, 0o701, 0o1700)),
                                (path, (0o640, 0o604, 0o400, 0o1600))):
            original = stat.S_IMODE(selected.stat().st_mode)
            for mode in modes:
                with self.subTest(kind=selected.name, mode=oct(mode)):
                    selected.chmod(mode)
                    with self.assertRaises(credentials.CredentialError):
                        credentials.load_saved_key('openai', self.config)
                    selected.chmod(original)
        self.config.chmod(0o750)
        self.assertEqual(credentials.load_saved_key('openai', self.config), 'fake-saved-key')

    def test_unsafe_config_directory_fails_even_without_a_saved_provider_file(self):
        self.config.chmod(0o770)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', self.config)

    def test_current_user_ownership_is_required(self):
        self.keyfile()
        uid = os.geteuid()
        for ownership in ((uid + 1,), (uid, uid + 1), (uid, uid, uid + 1)):
            with self.subTest(check=len(ownership)), mock.patch.object(os, 'geteuid', side_effect=ownership):
                with self.assertRaises(credentials.CredentialError):
                    credentials.load_saved_key('openai', self.config)

    def test_symlink_components_and_hardlinked_keys_are_refused(self):
        path = self.keyfile()
        config_link = self.root / 'application-link'
        config_link.symlink_to(self.config, target_is_directory=True)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', config_link)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', config_link / 'absent')
        path.rename(self.store / 'original.key')
        path.symlink_to(self.store / 'original.key')
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', self.config)
        path.unlink()
        os.link(self.store / 'original.key', path)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', self.config)
        path.unlink()
        (self.store / 'original.key').unlink()
        self.store.rmdir()
        outside = self.root / 'outside'
        outside.mkdir(mode=0o700)
        self.store.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', self.config)

    def test_nonregular_key_file_does_not_block(self):
        path = self.store / 'openai.key'
        os.mkfifo(path, mode=0o600)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', self.config)
        path.unlink()
        path.mkdir(mode=0o600)
        with self.assertRaises(credentials.CredentialError):
            credentials.load_saved_key('openai', self.config)

    def test_bounded_read_and_changed_file_fail_closed(self):
        path = self.keyfile()
        read = os.read
        requested = []
        def changing_read(descriptor, maximum):
            requested.append(maximum)
            result = read(descriptor, maximum)
            if result:
                path.write_bytes(b'fake-replacement-key\n')
                path.chmod(0o600)
            return result
        with mock.patch.object(os, 'read', side_effect=changing_read):
            with self.assertRaises(credentials.CredentialError):
                credentials.load_saved_key('openai', self.config)
        self.assertLessEqual(max(requested), credentials.MAX_KEY_BYTES + 2)

    def test_replaced_key_and_config_subtree_fail_closed(self):
        path = self.keyfile()
        read = os.read
        for change in ('key', 'subtree'):
            with self.subTest(change=change):
                changed = False
                def replacing_read(descriptor, maximum):
                    nonlocal changed
                    result = read(descriptor, maximum)
                    if result and not changed:
                        changed = True
                        if change == 'key':
                            replacement = self.store / 'replacement.key'
                            replacement.write_bytes(b'fake-replacement-key\n')
                            replacement.chmod(0o600)
                            replacement.replace(path)
                        else:
                            self.config.rename(self.root / 'original-application')
                            self.config.mkdir(mode=0o700)
                    return result
                with mock.patch.object(os, 'read', side_effect=replacing_read):
                    with self.assertRaises(credentials.CredentialError):
                        credentials.load_saved_key('openai', self.config)

    def test_io_errors_and_all_descriptors_are_sanitized_and_closed(self):
        self.keyfile()
        close = os.close
        closed = []
        def recorded_close(descriptor):
            closed.append(descriptor)
            return close(descriptor)
        with mock.patch.object(os, 'read', side_effect=OSError('fake-secret fixture path')), \
                mock.patch.object(os, 'close', side_effect=recorded_close):
            with self.assertRaises(credentials.CredentialError) as caught:
                credentials.load_saved_key('openai', self.config)
        self.assertNotIn('fake-secret', str(caught.exception))
        self.assertGreaterEqual(len(closed), len(self.config.parts) + 1)
        self.assertEqual(len(closed), len(set(closed)))
