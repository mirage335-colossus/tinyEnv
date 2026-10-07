from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import sys
import types
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location("apt_repo", Path(__file__).resolve().parents[1] / "tools/apt_repo.py")
apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apt)


@unittest.skipUnless(shutil.which("dpkg-deb"), "Debian package tooling required")
class AptTests(unittest.TestCase):
    def archive(self, root, binaries=None, extra=None, binary_mode=0o755, terms=b"fixture terms\n"):
        archive = root / "application.tar"
        source, binary = root / "fixture.c", root / "fixture"
        source.write_text("int main(void) { return 0; }\n")
        subprocess.run(["cc", str(source), "-o", str(binary)], check=True)
        entries = [("prefix/bin/" + name, binary.read_bytes(), binary_mode)
                   for name in (binaries or ["foundation-cli"])]
        entries += [("prefix/share/doc/Foundation/LICENSE", terms, 0o644)]
        entries += [("prefix/" + name, data, mode) for name, (data, mode) in (extra or {}).items()]
        with tarfile.open(archive, "w") as bundle:
            for name, data, mode in entries:
                item = tarfile.TarInfo(name)
                item.size, item.mode = len(data), mode
                bundle.addfile(item, io.BytesIO(data))
        manifest = root / "archive.json"
        apt.c.write_new(manifest, apt.artifact.describe(archive))
        return archive, manifest

    def fixture(self, root, terms=b"fixture terms\n"):
        archive, manifest = self.archive(root, terms=terms)
        receipt = apt.package(archive, manifest, "1.0.0", "amd64", "core", root / "packages")
        return root / "packages" / (receipt["package"] + ".json")

    def approved_fixture_terms(self):
        original = apt.c.load
        def load(path):
            if Path(path).name == 'gui-boundary.lock.json':
                return {'license': 'MIT', 'redistribution': {'approved': True, 'license_files': ['LICENSE']},
                        'files': {'LICENSE': apt.byte_record(b'GUI fixture terms\n', 0o644)['sha256']}}
            return original(path)
        return patch.object(apt.c, 'load', side_effect=load)

    def test_payload_preservation_no_hooks_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = self.fixture(root)
            data = apt.c.load(receipt)
            package = receipt.parent / data["package"]
            self.assertEqual(apt.verify_package(package, data)["Architecture"], "amd64")
            self.assertEqual(set(apt.deb_contents(package, True)), {"control"})
            self.assertIn("opt/software-foundation/core/bin/foundation-cli", data["payload"])
            with self.assertRaisesRegex(ValueError, "destination must be new"):
                apt.package(root / 'application.tar', root / 'archive.json', '1.0.0', 'amd64', 'core', receipt.parent)
            package.write_bytes(package.read_bytes() + b"tamper")
            with self.assertRaises(ValueError):
                apt.verify_package(package, data)

    def test_combined_archive_projects_backend_and_retains_shared_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = ['foundation-cli', 'foundation-gui-terminal', 'foundation-gui-framebuffer', 'foundation-gui-web']
            extra = {'share/doc/Foundation/gui-boundary/LICENSE': (b'GUI fixture terms\n', 0o644),
                     'lib/runtime/shared-data.txt': (b'unchanged shared runtime data\n', 0o644),
                     'share/man/man1/foundation-cli.1': (b'.TH FOUNDATION-CLI 1\n', 0o644),
                     'share/man/man7/software-foundation.7': (b'.TH SOFTWARE-FOUNDATION 7\n', 0o644),
                     'share/software-foundation/web/renderer.mjs': (b'export const fixture = true;\n', 0o644)}
            archive, manifest = self.archive(root, binaries, extra)
            original = archive.read_bytes()
            for backend, gui in (('core', None), ('terminal', 'foundation-gui-terminal'), ('hosted-web', 'foundation-gui-web')):
                with self.subTest(backend=backend), self.approved_fixture_terms():
                    output = root / backend
                    receipt = apt.package(archive, manifest, '1.0.0', 'amd64', backend, output)
                    package = output / receipt['package']
                    fields = apt.verify_package(package, receipt)
                    self.assertEqual(fields['Package'], 'software-foundation-' + backend)
                    self.assertEqual(receipt['schema_version'], 4)
                    extracted = root / ('installed-' + backend)
                    apt.run('dpkg-deb', '--extract', package, extracted)
                    private = extracted / 'opt/software-foundation' / backend
                    selected = {'foundation-cli'} | ({gui} if gui else set())
                    self.assertEqual({p.name for p in (private / 'bin').iterdir()}, selected)
                    expected_launchers = {'foundation-cli' + ('-' + backend if backend != 'core' else '')} | ({gui} if gui else set())
                    self.assertEqual({p.name for p in (extracted / 'usr/bin').iterdir()}, expected_launchers)
                    for name in selected:
                        self.assertEqual((private / 'bin' / name).read_bytes(), (root / 'fixture').read_bytes())
                        subprocess.run([str(private / 'bin' / name)], check=True)
                    for name, (data, _) in extra.items():
                        self.assertEqual((private / name).read_bytes(), data)
                    for source_name, destination in apt.manual_paths(backend, receipt['selection']['retained_files']).items():
                        self.assertEqual((extracted / destination).read_bytes(), (private / source_name).read_bytes())
                    self.assertEqual(apt.c.load(private / apt.SELECTION_PATH), receipt['selection'])
                    self.assertEqual(set(receipt['selection']['excluded_executables']),
                                     {'bin/' + name for name in set(binaries) - selected})
                    self.assertEqual(archive.read_bytes(), original)


    def test_desktop_entries_and_browser_lifetime_match_supported_payload(self):
        for backend in ('terminal', 'fltk', 'rev', 'sdl'):
            files = apt.desktop_files(backend, {'bin/foundation-gui-' + backend: {}})
            path = 'usr/share/applications/software-foundation-' + backend + '.desktop'
            self.assertEqual(set(files), {path})
            entry, mode = files[path]
            self.assertEqual(mode, 0o644)
            self.assertIn(('Exec=foundation-gui-' + backend + '\n').encode(), entry)
            self.assertIn(('Terminal=' + ('true' if backend == 'terminal' else 'false')).encode(), entry)
        for backend in ('core', 'framebuffer', 'hosted-web'):
            self.assertEqual(apt.desktop_files(backend, {'bin/foundation-gui-web': {}}), {})
        payload = {'bin/foundation-gui-web': {}}
        payload.update({'share/software-foundation/web/' + name: {} for name in
                        ('serve.py', 'host.py', 'index.html', 'boot.mjs', 'renderer.mjs', 'style.css',
                         'browser_lifecycle.mjs', 'wasm_transport.mjs', 'browser_presenter.mjs',
                         'file_services.mjs', 'wasm_worker.mjs')})
        for dependency in ('browser_lifecycle.mjs', 'wasm_transport.mjs', 'browser_presenter.mjs',
                           'file_services.mjs', 'wasm_worker.mjs'):
            with self.subTest(missing=dependency):
                partial = dict(payload)
                del partial['share/software-foundation/web/' + dependency]
                self.assertEqual(apt.desktop_files('hosted-web', partial), {})
        files = apt.desktop_files('hosted-web', payload)
        launcher, mode = files['usr/bin/foundation-gui-browser']
        self.assertEqual(mode, 0o755)
        entry = files['usr/share/applications/software-foundation-hosted-web.desktop'][0]
        self.assertIn(b'Exec=foundation-gui-browser\n', entry)
        self.assertIn(b'Terminal=true\n', entry)
        for failure in (KeyboardInterrupt(), RuntimeError('browser launch failed')):
            server = Mock(authority='127.0.0.1:12345')
            factory = Mock(return_value=server)
            loader = Mock(return_value={'boundary': types.SimpleNamespace(Host=factory)})
            browser = Mock(return_value=True)
            if isinstance(failure, KeyboardInterrupt):
                server.serve_forever.side_effect = failure
            else:
                browser.side_effect = failure
            with patch.dict(sys.modules, runpy=types.SimpleNamespace(run_path=loader),
                            webbrowser=types.SimpleNamespace(open=browser)):
                try:
                    exec(compile(launcher, 'installed-browser', 'exec'), {})
                except RuntimeError:
                    self.assertIsInstance(failure, RuntimeError)
            factory.assert_called_once_with(('127.0.0.1', 0), '/opt/software-foundation/hosted-web/bin/foundation-gui-web')
            browser.assert_called_once_with('http://127.0.0.1:12345/')
            server.server_close.assert_called_once_with()

    def test_historical_debian_projection_keeps_its_original_contract(self):
        with tempfile.TemporaryDirectory() as temporary, self.approved_fixture_terms():
            root = Path(temporary)
            archive, manifest = self.archive(root, ['foundation-cli', 'foundation-gui-terminal'],
                {'share/doc/Foundation/gui-boundary/LICENSE': (b'GUI fixture terms\n', 0o644)})
            # Reproduce schema 2's original package bytes, then verify with the new reader.
            with patch.object(apt, 'desktop_files', return_value={}):
                receipt = apt.package(archive, manifest, '1.0.0', 'amd64', 'terminal', root/'old')
            receipt['schema_version'] = 2
            package = root/'old'/receipt['package']
            apt.verify_package(package, receipt)
            receipt['schema_version'] = 3
            with self.assertRaisesRegex(ValueError, 'projection'):
                apt.verify_package(package, receipt)

    def test_offline_document_is_retained_and_launch_projection_is_versioned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix = 'share/software-foundation/wasm/'
            extra = {(prefix if not name.startswith('open-') else 'share/software-foundation/') + name:
                     (b'fixture ' + name.encode(), 0o755 if name.endswith('.sh') else 0o644)
                     for name in ('software-foundation-wasm.html', 'web-manifest.json', 'manifest.sha256',
                                  'open-offline.sh', 'open-offline.cmd')}
            archive, manifest = self.archive(root, extra=extra)
            receipt = apt.package(archive, manifest, '1.0.0', 'amd64', 'core', root/'current')
            apt.verify_package(root/'current'/receipt['package'], receipt)
            self.assertIn('usr/bin/foundation-gui-offline-core', receipt['payload'])
            self.assertIn('usr/share/applications/software-foundation-offline-core.desktop', receipt['payload'])
            for name in extra:
                self.assertEqual(receipt['payload']['opt/software-foundation/core/' + name], receipt['selection']['retained_files'][name])
            with patch.object(apt, 'offline_desktop_files', return_value={}):
                old = apt.package(archive, manifest, '1.0.0', 'amd64', 'core', root/'historical')
            old['schema_version'] = 3
            apt.verify_package(root/'historical'/old['package'], old)
            for missing in extra:
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'Incomplete'):
                    apt.offline_desktop_files('core', {name: value for name, value in extra.items() if name != missing})

    def test_core_projection_cannot_bypass_combined_gui_terms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, manifest = self.archive(root, ['foundation-cli', 'foundation-gui-terminal'])
            load=apt.c.load
            def unresolved(path):
                return {'redistribution':{'approved':False}} if Path(path).name=='gui-boundary.lock.json' else load(path)
            with patch.object(apt.c,'load',side_effect=unresolved),self.assertRaisesRegex(ValueError,'redistribution'):
                apt.package(archive, manifest, '1.0.0', 'amd64', 'core', root / 'rejected')
            self.assertFalse((root / 'rejected').exists())

    def test_unknown_missing_nonexecutable_and_colliding_inputs_fail_without_output(self):
        cases = [('unknown', ['foundation-cli', 'foundation-other'], {}, 0o755, 'core'),
                 ('nested', ['foundation-cli', 'nested/foundation-gui-web'], {}, 0o755, 'core'),
                 ('missing', ['foundation-cli'], {}, 0o755, 'terminal'),
                 ('mode', ['foundation-cli'], {}, 0o644, 'core'),
                 ('collision', ['foundation-cli'], {apt.SELECTION_PATH: (b'old receipt\n', 0o644)}, 0o755, 'core'),
                 ('alias', ['foundation-cli'], {'share/doc/foundation/other.txt': (b'alias\n', 0o644)}, 0o755, 'core')]
        for label, binaries, extra, mode, backend in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive, manifest = self.archive(root, binaries, extra, mode)
                with self.assertRaises(ValueError):
                    apt.package(archive, manifest, '1.0.0', 'amd64', backend, root / 'rejected')
                self.assertFalse((root / 'rejected').exists())

    def test_selection_receipt_cannot_relabel_or_omit_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = self.fixture(root)
            receipt = apt.c.load(receipt_path)
            package = receipt_path.parent / receipt['package']
            for field in ('backend', 'archive_sha256', 'source_file_inventory_sha256'):
                changed = json.loads(json.dumps(receipt))
                changed['selection'][field] = 'terminal' if field == 'backend' else '0' * 64
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'selection'):
                    apt.verify_package(package, changed)
            receipt['archive_manifest']['files'].pop('prefix/share/doc/Foundation/LICENSE')
            with self.assertRaisesRegex(ValueError, 'original archive projection'):
                apt.verify_package(package, receipt)

    @unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "repository signing tools required")
    def test_signed_repository_update_idempotence_rollback_expiry_and_tamper(self):
        with tempfile.TemporaryDirectory() as temporary, apt.signing_home() as home:
            root = Path(temporary)
            receipt = self.fixture(root)
            apt.run("gpg", "--batch", "--homedir", home, "--pinentry-mode", "loopback", "--passphrase", "",
                    "--quick-generate-key", "Fixture <fixture@example.invalid>", "default", "sign", "1d")
            public = root / "public.gpg"
            public.write_bytes(apt.run("gpg", "--batch", "--homedir", home, "--export"))
            trusted = apt.fingerprint(public)
            private = root / "private.asc"
            private.write_bytes(apt.run("gpg", "--batch", "--homedir", home, "--armor", "--export-secret-keys", trusted))
            url = "https://example.invalid/releases/download/v1/"
            apt.repository([receipt], root / "one", url, private, trusted, 1)
            index = apt.control_fields((root / "one/Packages").read_text().strip())
            expected_package = apt.c.load(receipt)['package']
            self.assertEqual(index['Filename'], expected_package)
            self.assertEqual(url + index['Filename'], url + expected_package)
            self.assertNotIn('://', index['Filename'])
            first = apt.verify_repository(root / "one", trusted)
            self.assertEqual(apt.verify_repository(root / "one", trusted, first), first)
            apt.repository([receipt], root / "two", url, private, trusted, 2)
            second = apt.verify_repository(root / "two", trusted, first)
            self.assertEqual(second['package_sha256'], first['package_sha256'])
            missing_identity = dict(first)
            missing_identity.pop('package_sha256')
            with self.assertRaisesRegex(ValueError, 'missing previous payload identity'):
                apt.verify_repository(root / 'two', trusted, missing_identity)
            changed = root / 'changed'
            changed.mkdir()
            replacement = self.fixture(changed, terms=b'changed retained terms\n')
            apt.repository([replacement], root / 'replacement', url, private, trusted, 3)
            with self.assertRaisesRegex(ValueError, 'same-version package replacement'):
                apt.verify_repository(root / 'replacement', trusted, second)
            upgraded = apt.package(changed / 'application.tar', changed / 'archive.json', '1.0.1', 'amd64',
                                   'core', changed / 'upgrade')
            apt.repository([changed / 'upgrade' / (upgraded['package'] + '.json')],
                           root / 'upgrade', url, private, trusted, 3)
            accepted = apt.verify_repository(root / 'upgrade', trusted, second)
            self.assertEqual(accepted['versions']['software-foundation-core:amd64'], '1.0.1')
            incompatible = dict(first, versions={"software-foundation-core:amd64": "2.0.0"})
            with self.assertRaisesRegex(ValueError, "version rollback"):
                apt.verify_repository(root / "two", trusted, incompatible)
            with self.assertRaisesRegex(ValueError, "rollback"):
                apt.verify_repository(root / "one", trusted, second)
            with self.assertRaisesRegex(ValueError, "expired"):
                apt.verify_repository(root / "two", trusted, now=datetime.now(timezone.utc) + timedelta(days=31))
            (root / "two/Packages").write_text("changed")
            with self.assertRaises(ValueError):
                apt.verify_repository(root / "two", trusted)

    @unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "repository signing tools required")
    def test_cleartext_provider_delimiters_preserve_both_signature_checks(self):
        with tempfile.TemporaryDirectory() as temporary, apt.signing_home() as home:
            root = Path(temporary)
            receipt = self.fixture(root)
            apt.run("gpg", "--batch", "--homedir", home, "--pinentry-mode", "loopback", "--passphrase", "",
                    "--quick-generate-key", "Fixture <fixture@example.invalid>", "ed25519", "sign", "1d")
            public = root / "public.gpg"
            public.write_bytes(apt.run("gpg", "--batch", "--homedir", home, "--export"))
            trusted = apt.fingerprint(public)
            private = root / "private.asc"
            private.write_bytes(apt.run("gpg", "--batch", "--homedir", home, "--armor", "--export-secret-keys", trusted))
            repository = root / "repository"
            apt.repository([receipt], repository, "https://example.invalid/releases/download/v1/", private, trusted, 1)
            release = (repository / "Release").read_bytes()
            expected = apt.verify_repository(repository, trusted)

            def clearsigned(body):
                # Explicit signed text plus one unsigned framing LF models both
                # stock and Arch CSF producers, independent of the host signer.
                source, signature = root / "signed-text", root / "text-signature.asc"
                source.write_bytes(body)
                apt.run("gpg", "--batch", "--yes", "--homedir", home, "--local-user", trusted,
                        "--digest-algo", "SHA256", "--textmode", "--armor", "--output", signature,
                        "--detach-sign", source)
                (repository / "InRelease").write_bytes(
                    b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n" + body + b"\n" + signature.read_bytes())

            for producer, body in (("stock", release[:-1]), ("extra-separator", release)):
                with self.subTest(producer=producer):
                    clearsigned(body)
                    with patch.object(apt, "run", wraps=apt.run) as calls:
                        self.assertEqual(apt.verify_repository(repository, trusted), expected)
            verifications = [call.args for call in calls.call_args_list if call.args[0] == "gpgv"]
            self.assertEqual(len(verifications), 2)
            self.assertEqual(verifications[0][-3:], ("--output", "-", repository / "InRelease"))
            self.assertEqual(verifications[1][-2:], (repository / "Release.gpg", repository / "Release"))

            for body in (release.replace(b"Origin:", b"Changed:"), release[:-2], release + b"\n\n"):
                with self.subTest(valid_signature_wrong_text=body):
                    clearsigned(body)
                    with self.assertRaisesRegex(ValueError, "signed metadata disagree"):
                        apt.verify_repository(repository, trusted)
            clearsigned(release[:-1])
            valid = (repository / "InRelease").read_bytes()
            (repository / "InRelease").write_bytes(valid.replace(b"Origin:", b"Changed:"))
            with self.assertRaises(subprocess.CalledProcessError):
                apt.verify_repository(repository, trusted)
            (repository / "InRelease").write_bytes(valid)
            detached = (repository / "Release.gpg").read_bytes()
            (repository / "Release.gpg").write_bytes(b"not a signature")
            with self.assertRaises(subprocess.CalledProcessError):
                apt.verify_repository(repository, trusted)
            (repository / "Release.gpg").write_bytes(detached)
            with self.assertRaisesRegex(ValueError, "untrusted repository key"):
                apt.verify_repository(repository, "0" * 40)

    def test_cleartext_comparison_does_not_normalize_other_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = b"Origin: Fixture\nSHA256:\n one metadata\n"
            (root / "Release").write_bytes(release)
            trusted = "A" * 40
            for decoded in (release, release[:-1], release + b"\n"):
                with self.subTest(accepted=decoded), patch.object(apt, "fingerprint", return_value=trusted), \
                        patch.object(apt, "run", side_effect=[decoded, b""]) as verify, \
                        patch.object(apt, "control_fields", side_effect=RuntimeError("metadata reached")):
                    with self.assertRaisesRegex(RuntimeError, "metadata reached"):
                        apt.verify_repository(root, trusted)
                    self.assertEqual(verify.call_count, 2)
            for decoded in (b"", release[:-2], release + b"\n\n", release.replace(b"\n", b"\r\n"),
                            release.replace(b"Fixture", b"Fixture "), release.replace(b"one", b"two"),
                            release[:-1] + b" \n", release[:-1] + b"\t\n"):
                with self.subTest(rejected=decoded), patch.object(apt, "fingerprint", return_value=trusted), \
                        patch.object(apt, "run", side_effect=[decoded, b""]) as verify:
                    with self.assertRaisesRegex(ValueError, "signed metadata disagree"):
                        apt.verify_repository(root, trusted)
                    self.assertEqual(verify.call_count, 2)
            for noncanonical in (release[:-1], release + b"\n", release.replace(b"\n", b"\r\n")):
                (root / "Release").write_bytes(noncanonical)
                with self.subTest(noncanonical=noncanonical), patch.object(apt, "fingerprint", return_value=trusted), \
                        patch.object(apt, "run", side_effect=[noncanonical, b""]):
                    with self.assertRaisesRegex(ValueError, "canonical LF"):
                        apt.verify_repository(root, trusted)

    def test_backend_runtime_dependencies_are_explicit(self):
        self.assertEqual('libc6 (>= 2.36)',apt.runtime_dependencies('core'))
        self.assertIn('python3',apt.runtime_dependencies('hosted-web'))
        for package in ('fontconfig-config','fonts-dejavu-core'):
            self.assertIn(package,apt.runtime_dependencies('fltk'))
        for backend in ('rev','sdl'):self.assertIn('libglx-mesa0',apt.runtime_dependencies(backend))
        with self.assertRaises(ValueError):apt.runtime_dependencies('unknown')

    def test_metadata_injection_and_incomplete_trust_rejected(self):
        for value in ("short", "a" * 41, "A\n" * 20):
            with self.assertRaises(ValueError):
                apt.full_fingerprint(value)
        with self.assertRaises(ValueError):
            apt.control_fields("Package: one\nPackage: two\n")


if __name__ == "__main__":
    unittest.main()
