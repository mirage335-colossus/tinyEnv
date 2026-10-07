#!/usr/bin/env python3
"""Offline group identity, failure isolation and complete-source tests."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_group', ROOT / 'gui/source_group.py')
subject = importlib.util.module_from_spec(spec); spec.loader.exec_module(subject)


class SourceGroupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.foundation = self.root / 'foundation'
        (self.foundation / 'third_party').mkdir(parents=True)
        (self.foundation / 'gui/patches').mkdir(parents=True)
        (self.foundation / 'gui/patches/apply.py').write_bytes(b'apply = True\n')
        (self.foundation / 'gui/patches/host.patch').write_bytes(b'reviewed patch\n')
        (self.source / 'api.hpp').write_bytes(b'int result();\n')
        (self.source / 'include/gui').mkdir(parents=True)
        (self.source / 'include/gui/contract.hpp').write_bytes(b'int fixture_contract();\n')
        (self.source / 'retained.txt').write_bytes(b'Complete retained source\n')
        (self.source / 'run.sh').write_bytes(b'#!/bin/sh\nexit 0\n'); (self.source / 'run.sh').chmod(0o755)
        def git(*args):
            return subprocess.run(['git', '-C', str(self.source), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
        git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture')
        # Retain exact fixture bytes and index modes on every host, independently
        # of user Git newline settings or filesystem executable-bit support.
        git('config', 'core.autocrlf', 'false'); git('config', 'core.filemode', 'false')
        git('add', '.'); git('update-index', '--chmod=+x', 'run.sh')
        git('commit', '-qm', 'Fixture input')
        self.lock = {'revision': git('rev-parse', 'HEAD'), 'source_tree': git('rev-parse', 'HEAD^{tree}'),
                     'upstream': 'https://example.invalid/gui', 'license': 'NOASSERTION',
                     'redistribution': {'approved': False, 'license_files': []},
                     'patches': ['gui/patches/host.patch: fixture'],
                     'files': {'api.hpp': subject.archive.digest(self.source / 'api.hpp')}}
        (self.foundation / 'third_party/gui-boundary.lock.json').write_bytes(subject.archive.encoded(self.lock))
        self.group = self.root / 'group'
        subject.export(self.source, self.group, self.foundation)

    def rewrite(self, change, change_manifest=False):
        manifest = subject.archive.read_json(self.group / 'manifest.json')
        with tarfile.open(self.group / 'gui-inputs.tar.gz') as archive:
            entries = [(member, archive.extractfile(member).read()) for member in archive]
        entries = change(entries)
        with tarfile.open(self.group / 'gui-inputs.tar.gz', 'w:gz') as archive:
            for member, data in entries:
                member.size = len(data); archive.addfile(member, io.BytesIO(data))
                if change_manifest:
                    manifest['files'][member.name] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'mode': member.mode}
        manifest['archive_sha256'] = subject.archive.digest(self.group / 'gui-inputs.tar.gz')
        (self.group / 'manifest.json').write_bytes(subject.archive.encoded(manifest))
        (self.group / 'SHA256SUMS').write_text(''.join(f'{subject.archive.digest(self.group / name)}  {name}\n' for name in ['gui-inputs.tar.gz', 'manifest.json']))

    def verify(self):
        return subject.verify(self.group, foundation_root=self.foundation)

    def test_checkout_retains_complete_reviewed_gui_group(self):
        manifest = subject.verify(ROOT / 'third_party/gui-inputs', foundation_root=ROOT)
        lock = subject.archive.read_json(ROOT / 'third_party/gui-boundary.lock.json')
        self.assertEqual(lock['revision'], manifest['revision'])
        self.assertEqual(lock['source_tree'], manifest['source_tree'])
        self.assertIn('upstream/LICENSE', manifest['files'])
        self.assertIn('upstream/include/gui/contract.hpp', manifest['files'])
        self.assertTrue(manifest['redistributable'])

    def cmake_input_fixture(self):
        # Execute the maintained input module with tiny retained inputs. CMake
        # initializes C++/Threads, but builds no compiler or toolkit target.
        (self.foundation / 'cmake').mkdir()
        shutil.copyfile(ROOT / 'cmake/GuiInputs.cmake', self.foundation / 'cmake/GuiInputs.cmake')
        (self.foundation / 'gui/CMakeLists.txt').write_text(
            'foundation_register_build_directory()\n'
            'include("${CMAKE_CURRENT_SOURCE_DIR}/../cmake/GuiInputs.cmake")\n'
            'foundation_gui_inputs()\n')
        (self.foundation / 'tools').mkdir()
        shutil.copyfile(ROOT / 'gui/source_group.py', self.foundation / 'gui/source_group.py')
        shutil.copyfile(ROOT / 'tools/dependency_archive.py', self.foundation / 'tools/dependency_archive.py')
        shutil.copytree(self.group, self.foundation / 'third_party/gui-inputs')
        (self.foundation / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.24)\nproject(InputSelection LANGUAGES CXX)\n'
            'function(foundation_register_build_directory)\nendfunction()\n'
            'add_subdirectory(gui)\n'
            'file(WRITE "${CMAKE_BINARY_DIR}/selected.txt" "${FOUNDATION_GUI_SOURCE}")\n')

    def configure_inputs(self, name, *arguments):
        output = self.root / name
        result = subprocess.run(['cmake', '-G', 'Ninja', '-S', str(self.foundation), '-B', str(output),
                                 '-DPython3_EXECUTABLE=' + sys.executable, *arguments],
                                text=True, capture_output=True)
        return output, result

    def test_cmake_default_group_and_explicit_inputs(self):
        self.cmake_input_fixture()
        output, result = self.configure_inputs('default')
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        restored = output / 'gui/retained-inputs/upstream'
        self.assertEqual(restored.resolve(), Path((output / 'selected.txt').read_text()).resolve())
        self.assertEqual((self.source / 'api.hpp').read_bytes(), (restored / 'api.hpp').read_bytes())
        # A broken bundled group must not override a caller's explicit input.
        archive = self.foundation / 'third_party/gui-inputs/gui-inputs.tar.gz'
        archive.write_bytes(b'corrupt local default')
        output, result = self.configure_inputs('explicit-source', '-DFOUNDATION_GUI_SOURCE=' + self.source.as_posix())
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(self.source.as_posix(), (output / 'selected.txt').read_text())
        self.assertFalse((output / 'gui/retained-inputs').exists())
        output, result = self.configure_inputs('explicit-group', '-DFOUNDATION_GUI_INPUT_GROUP=' + self.group.as_posix())
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((output / 'gui/retained-inputs/upstream/api.hpp').is_file())
        output, result = self.configure_inputs('conflict', '-DFOUNDATION_GUI_SOURCE=' + self.source.as_posix(),
                                               '-DFOUNDATION_GUI_INPUT_GROUP=' + self.group.as_posix())
        self.assertNotEqual(0, result.returncode)
        self.assertIn('not both', result.stdout + result.stderr)
        self.assertFalse((output / 'gui/retained-inputs').exists())

    def test_cmake_corrupt_default_fails_without_partial_restore(self):
        self.cmake_input_fixture()
        archive = self.foundation / 'third_party/gui-inputs/gui-inputs.tar.gz'
        archive.write_bytes(b'corrupt local default')
        output, result = self.configure_inputs('corrupt-default')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('checksum', result.stdout + result.stderr)
        self.assertFalse((output / 'gui/retained-inputs').exists())
        self.assertEqual(b'corrupt local default', archive.read_bytes())

    def test_checkout_preserves_retained_text_with_windows_newline_settings(self):
        repo = self.root/'checkout';repo.mkdir()
        def git(*args):
            return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
        git('init','-q');git('config','core.autocrlf','true')
        shutil.copyfile(ROOT/'.gitattributes',repo/'.gitattributes')
        files = {'gui/patches/host.patch':b'--- old\n+++ new\n@@ -1 +1 @@\n-old\n+new\n',
                 'gui/browser.mjs':b'export const ready = true;\n', 'CMakeLists.txt':b'project(Example)\n'}
        for name,data in files.items():
            path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        git('add','.')
        for name in files:(repo/name).unlink()
        git('checkout-index','--all','--force')
        for name,data in files.items():self.assertEqual(data,(repo/name).read_bytes(),name)

    def test_export_deterministic_restore_and_repeat(self):
        other = self.root / 'other'; subject.export(self.source, other, self.foundation)
        self.assertEqual(subject.archive.file_inventory(self.group), subject.archive.file_inventory(other))
        output = self.root / 'restored'; result = subject.restore(self.group, output, self.foundation)
        self.assertEqual(str(output / 'upstream'), result['source'])
        self.assertEqual(result, subject.restore(self.group, output, self.foundation))
        self.assertEqual(self.source.joinpath('retained.txt').read_bytes(), output.joinpath('upstream/retained.txt').read_bytes())
        restored = output / 'upstream/run.sh'
        self.assertEqual(0o755, self.verify()['files']['upstream/run.sh']['mode'])
        with tarfile.open(self.group / 'gui-inputs.tar.gz') as archive:
            self.assertEqual(0o755, archive.getmember('upstream/run.sh').mode)
        self.assertEqual(0o755, subject.metadata(restored, 0o755)['mode'])
        if not subject.WINDOWS:
            self.assertTrue(restored.stat().st_mode & 0o111)

    def test_fixture_retains_exact_git_bytes_and_executable_index_mode(self):
        for name in ('api.hpp', 'retained.txt', 'run.sh'):
            content = (self.source / name).read_bytes()
            self.assertNotIn(b'\r', content)
            committed = subprocess.check_output(['git', '-C', str(self.source), 'show', 'HEAD:' + name])
            self.assertEqual(content, committed)
        entry = subprocess.check_output(['git', '-C', str(self.source), 'ls-files', '-s', 'run.sh'])
        self.assertEqual(b'100755', entry.split()[0])
        self.assertEqual(0o755, self.verify()['files']['upstream/run.sh']['mode'])

    def test_git_clean_newline_conversion_still_fails_complete_tree_check(self):
        target = self.source / 'retained.txt'
        changed = target.read_bytes().replace(b'\n', b'\r\n')
        target.write_bytes(changed)
        subprocess.run(['git', '-C', str(self.source), 'config', 'core.autocrlf', 'true'], check=True)
        subprocess.run(['git', '-C', str(self.source), 'add', 'retained.txt'], check=True)
        status = subprocess.check_output(['git', '-C', str(self.source), 'status', '--porcelain'])
        self.assertEqual(b'', status, 'Git normalizes these bytes; complete-tree verification must still reject them')
        output = self.root / 'newline-mismatch'
        with self.assertRaisesRegex(ValueError, 'complete source tree'):
            subject.export(self.source, output, self.foundation)
        self.assertFalse(output.exists())
        self.assertEqual(changed, target.read_bytes())

    def test_repeat_restore_uses_archive_paths_and_keeps_strict_inventory(self):
        output = self.root / 'restored'
        result = subject.restore(self.group, output, self.foundation)
        original = subject.archive.file_inventory(output)
        expected_dirs = {'foundation', 'foundation/gui', 'foundation/gui/patches',
                         'foundation/third_party', 'upstream', 'upstream/include', 'upstream/include/gui'}
        self.assertEqual(expected_dirs, {p.relative_to(output).as_posix()
                                       for p in output.rglob('*') if p.is_dir()})
        logical_names = self.verify()['files']

        def host_path(value):
            # Emulate Windows spelling for logical names while keeping actual
            # fixture filesystem operations native to the running test host.
            if isinstance(value, str) and value in logical_names:
                return PureWindowsPath(value)
            return Path(value)

        with patch.object(subject, 'Path', side_effect=host_path):
            self.assertEqual(result, subject.restore(self.group, output, self.foundation))
            foreign_dir = output / 'foundation/gui/foreign'; foreign_dir.mkdir()
            with self.assertRaisesRegex(ValueError, 'foreign entries'):
                subject.restore(self.group, output, self.foundation)
            self.assertTrue(foreign_dir.is_dir()); foreign_dir.rmdir()
            foreign_file = output / 'upstream/foreign.txt'; foreign_file.write_bytes(b'local')
            with self.assertRaisesRegex(ValueError, 'foreign entries'):
                subject.restore(self.group, output, self.foundation)
            self.assertEqual(b'local', foreign_file.read_bytes()); foreign_file.unlink()
            target = output / 'upstream/api.hpp'; saved = target.read_bytes()
            target.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'foreign entries'):
                subject.restore(self.group, output, self.foundation)
            self.assertEqual(b'changed', target.read_bytes()); target.write_bytes(saved)
            self.assertEqual(result, subject.restore(self.group, output, self.foundation))
        self.assertEqual(original, subject.archive.file_inventory(output))
        self.assertEqual(expected_dirs, {p.relative_to(output).as_posix()
                                       for p in output.rglob('*') if p.is_dir()})

    def test_terms_block_redistribution_only(self):
        self.assertFalse(self.verify()['redistributable'])
        with self.assertRaisesRegex(ValueError, 'terms'):
            subject.verify(self.group, True, self.foundation)

    def test_mutated_existing_restore_preserved(self):
        output = self.root / 'restored'; subject.restore(self.group, output, self.foundation)
        target = output / 'upstream/api.hpp'; target.write_text('local work')
        with self.assertRaises(ValueError): subject.restore(self.group, output, self.foundation)
        self.assertEqual('local work', target.read_text())

    def test_foreign_directory_and_input_rejected(self):
        output = self.root / 'restored'; subject.restore(self.group, output, self.foundation)
        (output / 'foreign').mkdir()
        with self.assertRaises(ValueError): subject.restore(self.group, output, self.foundation)
        (self.group / 'unexpected').write_text('extra')
        with self.assertRaises(ValueError): self.verify()

    def test_integration_change_rejected(self):
        (self.foundation / 'gui/patches/host.patch').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'integration'): self.verify()

    def test_unconsumed_source_tamper_rejected_by_complete_tree(self):
        self.rewrite(lambda entries: [(member, b'tampered' if member.name == 'upstream/retained.txt' else data) for member, data in entries], True)
        with self.assertRaisesRegex(ValueError, 'complete source tree'): self.verify()

    def test_duplicate_archive_entry_rejected_before_output(self):
        self.rewrite(lambda entries: entries + [entries[0]])
        output = self.root / 'output'
        with self.assertRaises(ValueError): subject.restore(self.group, output, self.foundation)
        self.assertFalse(output.exists())

    def test_unsafe_archive_path_rejected(self):
        def change(entries):
            entries[0][0].name = '../outside'; return entries
        self.rewrite(change, True)
        with self.assertRaises(ValueError): self.verify()
        self.assertFalse((self.root / 'outside').exists())

    def test_link_and_checksum_tamper_rejected(self):
        path = self.group / 'SHA256SUMS'; content = path.read_text(); path.unlink(); path.symlink_to(self.source / 'retained.txt')
        with self.assertRaises(ValueError): self.verify()
        path.unlink(); path.write_text(content + 'invalid\n')
        with self.assertRaises(ValueError): self.verify()

    def test_bounded_inventory_and_case_collision(self):
        value = {'sha256': 'a' * 64, 'size': 1, 'mode': 0o644}
        for entries in ({'a/x': value, 'A/y': value}, {'x': value, 'x/y': value}, {'CON': value}, {'x': dict(value, size=subject.MAX_FILE + 1)}):
            with self.assertRaises(ValueError): subject.validate_entries(entries)

    def test_windows_logical_modes_do_not_depend_on_chmod(self):
        path = self.source / 'run.sh'; path.chmod(0o644)
        with patch.object(subject, 'WINDOWS', True):
            self.assertEqual(0o755, subject.metadata(path, 0o755)['mode'])
        with patch.object(subject, 'WINDOWS', False):
            self.assertEqual(0o644, subject.metadata(path, 0o755)['mode'])

    def test_missing_archive_member_and_truncated_input_rejected(self):
        self.rewrite(lambda entries: entries[1:])
        with self.assertRaises(ValueError): self.verify()
        target = self.group / 'gui-inputs.tar.gz'; target.write_bytes(target.read_bytes()[:20])
        with self.assertRaises(ValueError): self.verify()

    def test_dirty_checkout_rejected(self):
        (self.source / 'retained.txt').write_text('changed')
        with self.assertRaises(ValueError): subject.export(self.source, self.root / 'dirty', self.foundation)


    def test_one_guarded_group_digest_observation_per_verify(self):
        digest = subject.archive.digest
        with patch.object(subject.archive, 'digest', wraps=digest) as observed:
            manifest = self.verify()
        for name in subject.GROUP_FILES:
            self.assertEqual(1, sum(call.args[0] == self.group / name for call in observed.call_args_list), name)
        self.assertEqual(self.lock['source_tree'], manifest['source_tree'])
        # No cached success crosses invocations, even for an unchanged directory.
        with patch.object(subject.archive, 'digest', wraps=digest) as observed:
            self.verify()
        self.assertEqual(1, sum(call.args[0] == self.group / 'gui-inputs.tar.gz' for call in observed.call_args_list))

    def test_group_change_between_hashing_and_decode_is_rejected(self):
        identity = subject.stream_identity; changed = False
        def mutate(stream, size):
            nonlocal changed
            result = identity(stream, size)
            if not changed:
                changed = True
                path = self.group / 'manifest.json'
                # Even replacing equivalent bytes invalidates this observation.
                staged = self.group / 'replacement'; staged.write_bytes(path.read_bytes()); staged.replace(path)
            return result
        with patch.object(subject, 'stream_identity', side_effect=mutate), self.assertRaisesRegex(ValueError, 'changed during verification'):
            self.verify()

    def test_file_change_while_hashing_is_rejected(self):
        path = self.source / 'retained.txt'; digest = subject.archive.digest
        def mutate(source):
            result = digest(source); source.write_bytes(source.read_bytes() + b'changed'); return result
        with patch.object(subject.archive, 'digest', side_effect=mutate), self.assertRaisesRegex(ValueError, 'changed while hashing'):
            subject.metadata(path)

    def test_streamed_blob_identity_has_bounded_reads_and_exact_size(self):
        payload = b'complete source bytes' * 200000
        class BoundedRead(io.BytesIO):
            def read(self, size=-1):
                if not 0 <= size <= 1024 * 1024: raise AssertionError('unbounded member read')
                return super().read(size)
        digest, blob = subject.stream_identity(BoundedRead(payload), len(payload))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
        expected = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).digest()
        self.assertEqual(expected, blob)
        self.assertEqual(subject.tree_identity({'nested/file': (0o644, payload)}),
                         subject.tree_from_blobs({'nested/file': (0o644, blob)}))
        for stream, size in [(io.BytesIO(b'ab'), 3), (io.BytesIO(b'abcd'), 3)]:
            with self.assertRaises(ValueError): subject.stream_identity(stream, size)

    def test_large_member_verification_does_not_retain_whole_source_bytes(self):
        target = self.source / 'retained.txt'
        with target.open('wb') as output:
            for _ in range(12): output.write(b'x' * (1024 * 1024))
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.source), 'commit', '-qm', 'Large retained fixture'], check=True)
        self.lock['revision'] = subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD']).decode().strip()
        self.lock['source_tree'] = subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD^{tree}']).decode().strip()
        (self.foundation / 'third_party/gui-boundary.lock.json').write_bytes(subject.archive.encoded(self.lock))
        group = self.root / 'large-group'; subject.export(self.source, group, self.foundation)
        tracemalloc.start()
        try:
            subject.verify(group, foundation_root=self.foundation)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # Generous headroom over the 1MiB chunks; old whole-member retention needs
        # at least12MiB and then duplicates payload bytes for Git blob hashing.
        self.assertLess(peak, 8 * 1024 * 1024, 'verification retained an entire large source member')


if __name__ == '__main__':
    unittest.main()
