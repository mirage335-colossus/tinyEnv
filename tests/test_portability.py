from pathlib import Path
import json
import os
import stat
import tarfile
import shutil
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import verify_abi
import stage_runtime


class InstructionPropertyTests(unittest.TestCase):
    def test_optional_used_instructions_do_not_raise_required_baseline(self):
        for notes in (
            'x86 ISA needed: x86-64-baseline, x86 feature used: x86, x86 ISA used: x86-64-baseline, x86-64-v2, x86-64-v3',
            'x86 ISA used: x86-64-v4, x86 ISA needed: x86-64-baseline',
            'x86 ISA needed: x86-64-baseline\nx86 ISA used: x86-64-v3',
            'x86 ISA used: x86-64-v2', ''):
            with self.subTest(notes=notes):
                self.assertFalse(verify_abi.requires_extended_x86_isa(notes))

    def test_required_higher_instructions_always_raise_baseline(self):
        for level in (2, 3, 4):
            for suffix in ('', ', x86 ISA used: x86-64-baseline', '\nx86 ISA used: x86-64-baseline'):
                with self.subTest(level=level, suffix=suffix):
                    self.assertTrue(verify_abi.requires_extended_x86_isa(
                        'x86 ISA needed: x86-64-baseline, x86-64-v' + str(level) + suffix))


@unittest.skipUnless(platform.system() == 'Linux' and shutil.which('cc') and shutil.which('readelf'), 'native Linux ELF toolchain required')
class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.processor = {'arm64': 'aarch64', 'AMD64': 'x86_64'}.get(platform.machine(), platform.machine())
        (self.root / 'main.c').write_text('int main(void) { return 0; }\n')
        subprocess.run(['cc', str(self.root / 'main.c'), '-o', str(self.root / 'application')], check=True)

    def tearDown(self): self.temp.cleanup()

    def test_real_elf_needed_and_used_properties_remain_distinct(self):
        import struct
        # Build an ELF64 format specimen, never executable host code. Native
        # readelf can inspect its x86 properties on both Linux architectures.
        names = b'\0.note.gnu.property\0.shstrtab\0'
        for needed in (1, 2, 4, 8):
            library = self.root / ('isa-' + str(needed) + '.so')
            note = struct.pack('<III4sIIIIIIII', 4, 32, 5, b'GNU\0',
                               0xc0008002, 4, needed, 0, 0xc0010002, 4, 15, 0)
            sections_offset = 64 + len(note)
            names_offset = sections_offset + 3 * 64
            header = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01' + b'\0' * 9,
                                 3, 62, 1, 0, 0, sections_offset, 0, 64, 56, 0, 64, 3, 2)
            note_section = struct.pack('<IIQQQQIIQQ', 1, 7, 2, 0, 64, len(note), 0, 0, 8, 0)
            names_section = struct.pack('<IIQQQQIIQQ', names.index(b'.shstrtab'), 3, 0, 0,
                                        names_offset, len(names), 0, 0, 1, 0)
            library.write_bytes(header + note + b'\0' * 64 + note_section + names_section + names)
            notes = verify_abi.run('readelf', '--notes', library)
            self.assertIn('x86 ISA used:', notes)
            self.assertIn('x86-64-v4', notes)
            if needed == 1:
                self.assertIn('x86 ISA needed: x86-64-baseline', notes)
                self.assertEqual('passed', verify_abi.audit(library)['status'])
            else:
                with self.assertRaisesRegex(ValueError, 'above the generic x86_64 baseline'):
                    verify_abi.audit(library)

    def test_real_native_elf_inspection(self):
        report = verify_abi.audit(self.root / 'application', processor=self.processor)
        self.assertEqual(report['status'], 'passed')
        self.assertIn('application', report['files'])

    def test_real_named_abi_import_requires_glibc_236(self):
        # A controlled versioned import exercises the ABI reader on baseline
        # linkers for both Linux architectures. This does not generate RELR.
        package = self.root / 'named capability package'
        package.mkdir()
        provider = package / 'libcapability.so.1'
        executable = package / 'consumer'
        (self.root / 'capability.c').write_text('int capability_value(void) { return 42; }\n')
        (self.root / 'capability.map').write_text('GLIBC_ABI_DT_RELR { global: capability_value; local: *; };\n')
        subprocess.run(['cc', '-shared', '-nostdlib', '-fPIC', str(self.root / 'capability.c'),
                        '-Wl,--version-script=' + str(self.root / 'capability.map'),
                        '-Wl,-soname,libcapability.so.1', '-o', str(provider)], check=True)
        (self.root / 'consumer.c').write_text('extern int capability_value(void); int main(void) { return capability_value()!=42; }\n')
        subprocess.run(['cc', str(self.root / 'consumer.c'), str(provider),
                        '-Wl,-rpath,$ORIGIN', '-o', str(executable)], check=True)
        versions = subprocess.check_output(['readelf', '--wide', '--version-info', str(executable)], text=True)
        self.assertIn('Version needs section', versions)
        self.assertIn('File: libcapability.so.1', versions)
        self.assertIn('Name: GLIBC_ABI_DT_RELR', versions)
        self.assertEqual({}, verify_abi.inspect(provider)['named_requirements'])
        for sdk_private in (False, True):
            with self.subTest(sdk_private=sdk_private):
                report = verify_abi.inspect(executable, sdk_private=sdk_private)
                self.assertIn('libcapability.so.1', report['needed'])
                self.assertEqual({'GLIBC_ABI_DT_RELR': '2.36'}, report['named_requirements'])
                self.assertEqual('2.36', report['requirements']['GLIBC'])
        audit = verify_abi.audit(package, processor=self.processor)
        self.assertEqual('passed', audit['status'])
        self.assertEqual([{'from': 'consumer', 'needed': 'libcapability.so.1',
                           'provider': 'libcapability.so.1'}], audit['resolution'])
        with self.assertRaisesRegex(ValueError, 'above ceiling: GLIBC_2.36'):
            verify_abi.audit(package, processor=self.processor, ceilings={'GLIBC': '2.35'})
        subprocess.run([str(executable)], check=True, cwd=self.root,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    def test_named_requirement_rules_remain_exact_and_family_specific(self):
        original_run = verify_abi.run
        import re
        for name in ('GLIBC_ABI_FUTURE', 'GLIBC_PRIVATE', 'GLIBCXX_ABI_DT_RELR', 'CXXABI_ABI_DT_RELR'):
            with self.subTest(name=name):
                def altered(readelf, *args):
                    data = original_run(readelf, *args)
                    if args[0] == '--version-info':
                        data, count = re.subn(r'Name: GLIBC_[0-9.]+', 'Name: ' + name, data, count=1)
                        self.assertEqual(1, count)
                    return data
                with patch('verify_abi.run', side_effect=altered):
                    with self.assertRaisesRegex(ValueError, 'unsupported named ABI requirement'):
                        verify_abi.inspect(self.root / 'application')

    def test_named_floor_does_not_hide_newer_numerical_requirement(self):
        original_run = verify_abi.run
        def altered(readelf, *args):
            data = original_run(readelf, *args)
            if args[0] == '--version-info':
                self.assertIn('Version needs section', data)
                data += '\n  Name: GLIBC_ABI_DT_RELR\n  Name: GLIBC_2.37\n'
            return data
        with patch('verify_abi.run', side_effect=altered):
            report = verify_abi.inspect(self.root / 'application')
            self.assertEqual('2.37', report['requirements']['GLIBC'])
            self.assertEqual({'GLIBC_ABI_DT_RELR': '2.36'}, report['named_requirements'])
            with self.assertRaisesRegex(ValueError, 'above ceiling: GLIBC_2.37'):
                verify_abi.audit(self.root / 'application', processor=self.processor)

    def test_above_runtime_floor_rejected(self):
        with self.assertRaisesRegex(ValueError, 'above ceiling'):
            verify_abi.audit(self.root / 'application', processor=self.processor, ceilings={'GLIBC': '2.2.5'})

    def test_architecture_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'architecture'):
            verify_abi.audit(self.root / 'application', processor='aarch64' if self.processor == 'x86_64' else 'x86_64')

    def test_absolute_runtime_search_path_rejected(self):
        subprocess.run(['cc', str(self.root / 'main.c'), '-Wl,-rpath,/temporary/library', '-o', str(self.root / 'absolute')], check=True)
        with self.assertRaisesRegex(ValueError, 'relative'):
            verify_abi.audit(self.root / 'absolute', processor=self.processor)

    def test_non_elf_is_not_passing_coverage(self):
        with self.assertRaisesRegex(ValueError, 'no ELF'):
            verify_abi.audit(self.root / 'main.c')

    def test_missing_runtime_dependency_fails(self):
        info = verify_abi.inspect(self.root / 'application')
        info['needed'].append('libmissing.so.1')
        with patch('verify_abi.inspect', return_value=info):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                verify_abi.audit(self.root / 'application', processor=self.processor)

    def test_recursive_runtime_staging(self):
        libs = self.root / 'supplier'
        libs.mkdir()
        (libs / 'tiny.c').write_text('int value(void) { return 42; }\n')
        subprocess.run(['cc', '-shared', '-fPIC', str(libs / 'tiny.c'), '-Wl,-soname,libtiny.so.1', '-o', str(libs / 'libtiny.so.1')], check=True)
        (self.root / 'use.c').write_text('extern int value(void); int main(void) { return value()!=42; }\n')
        subprocess.run(['cc', str(self.root / 'use.c'), str(libs / 'libtiny.so.1'), '-o', str(self.root / 'use')], check=True)
        result = stage_runtime.stage([self.root / 'use'], [libs], self.root / 'private', processor=self.processor)
        self.assertEqual(set(result['files']), {'libtiny.so.1'})
        with self.assertRaisesRegex(ValueError, 'missing'):
            stage_runtime.stage([self.root / 'use'], [], self.root / 'missing', processor=self.processor)

    def test_staged_public_metadata_ignores_restrictive_umask(self):
        from dependency_archive import write_json
        destination = self.root / 'public-runtime'
        private = self.root / 'private-metadata.json'
        previous = os.umask(0o077)
        try:
            stage_runtime.stage([self.root / 'application'], [], destination, processor=self.processor)
            write_json(private, {'private': True})
        finally:
            os.umask(previous)
        self.assertEqual(0o644, stat.S_IMODE((destination / 'runtime-inventory.json').stat().st_mode))
        self.assertEqual(0o755, stat.S_IMODE(destination.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(private.stat().st_mode))

    def test_installed_runtime_metadata_survives_archive_package_selection(self):
        import apt_repo
        package, binary, libraries = self.linked_package()
        supplier = self.root / 'supplier'
        libraries.rename(supplier)
        executable = binary / 'foundation-cli'
        (binary / 'application').rename(executable)
        executable.chmod(0o755)
        (package / 'share/doc/Foundation').mkdir(parents=True)
        tool = Path(stage_runtime.__file__).with_name('package_runtime.py')
        # Execute the installed runtime producer under a restrictive child umask;
        # actual ELF libraries and the final loader audit stay in this regression.
        command = ('import os, runpy, sys; os.umask(0o077); '
                   'sys.path.insert(0, str(__import__("pathlib").Path(sys.argv[1]).parent)); '
                   'sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name="__main__")')
        subprocess.run([sys.executable, '-B', '-c', command, str(tool), '--prefix', str(package),
                        '--root', str(supplier), '--processor', self.processor], check=True)
        public = ('lib/runtime/runtime-inventory.json', 'share/doc/Foundation/runtime-audit.json')
        for name in public:
            with self.subTest(metadata=name):
                self.assertEqual(0o644, stat.S_IMODE((package / name).stat().st_mode))
                self.assertEqual(2 if name.endswith('runtime-inventory.json') else 1,
                                 json.loads((package / name).read_text())['schema_version'])
        self.assertEqual('passed', json.loads((package / public[1]).read_text())['status'])
        subprocess.run([str(executable)], check=True, cwd=self.root,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        archive = self.root / 'package.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            bundle.add(package, arcname='package')
        descriptor = apt_repo.artifact.describe(archive)
        modes = apt_repo.source_modes(archive)
        files = {name.removeprefix('package/'): dict(record, mode=modes[name])
                 for name, record in descriptor['files'].items()}
        chosen = apt_repo.selection('package', files, 'core', descriptor['sha256'])
        for name in public:
            self.assertEqual(0o644, chosen['retained_files'][name]['mode'])
        files[public[0]]['mode'] = 0o600
        with self.assertRaisesRegex(ValueError, 'invalid source file inventory identity'):
            apt_repo.selection('package', files, 'core', descriptor['sha256'])

    def linked_package(self, inherited=True, middle_path=False):
        package = self.root / 'package'
        binary, libraries = package / 'bin', package / 'lib' / 'runtime'
        binary.mkdir(parents=True)
        libraries.mkdir(parents=True)
        (self.root / 'leaf.c').write_text('int leaf(void) { return 42; }\n')
        (self.root / 'middle.c').write_text('extern int leaf(void); int middle(void) { return leaf(); }\n')
        (self.root / 'entry.c').write_text('extern int middle(void); int main(void) { return middle()!=42; }\n')
        subprocess.run(['cc', '-shared', '-fPIC', str(self.root / 'leaf.c'),
                        '-Wl,-soname,libleaf.so.1', '-o', str(libraries / 'libleaf.so.1')], check=True)
        args = ['cc', '-shared', '-fPIC', str(self.root / 'middle.c'), str(libraries / 'libleaf.so.1'),
                '-Wl,-soname,libmiddle.so.1', '-o', str(libraries / 'libmiddle.so.1')]
        if middle_path: args += ['-Wl,-rpath,$ORIGIN']
        subprocess.run(args, check=True)
        subprocess.run(['cc', str(self.root / 'entry.c'), str(libraries / 'libmiddle.so.1'),
                        '-Wl,-rpath-link,' + str(libraries), '-Wl,-rpath,$ORIGIN/../lib/runtime',
                        '-Wl,--disable-new-dtags' if inherited else '-Wl,--enable-new-dtags',
                        '-o', str(binary / 'application')], check=True)
        return package, binary, libraries

    def test_inherited_rpath_resolves_indirect_private_library(self):
        package, binary, libraries = self.linked_package()
        report = verify_abi.audit(package, processor=self.processor)
        self.assertEqual(len(report['resolution']), 2)
        self.assertEqual(report['runtime_resolution'], 'passed')
        subprocess.run([str(binary / 'application')], check=True,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, cwd=self.root)

    def test_empty_supplier_runpath_staging_restores_real_indirect_loading(self):
        from dependency_archive import digest
        package, binary, libraries = self.linked_package()
        middle = libraries / 'libmiddle.so.1'
        clean = self.root / 'middle-without-path.so'
        shutil.copyfile(middle, clean)
        subprocess.run(['cc', '-shared', '-fPIC', str(self.root / 'middle.c'),
                        str(libraries / 'libleaf.so.1'), '-Wl,-soname,libmiddle.so.1',
                        '-Wl,--enable-new-dtags', '-Wl,-rpath,', '-o', str(middle)], check=True)
        self.assertEqual([''], verify_abi.inspect(middle)['runpath'])
        # Even a matching current-directory library must not rescue the empty tag.
        shutil.copyfile(libraries / 'libleaf.so.1', self.root / 'libleaf.so.1')
        environment = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
        self.assertNotEqual(0, subprocess.run([str(binary / 'application')], cwd=self.root,
                                             env=environment, capture_output=True).returncode)
        supplier = self.root / 'supplier'
        libraries.rename(supplier)
        original = {p.name: digest(p) for p in supplier.iterdir()}
        editor = self.root / 'fixture-editor'
        editor.write_text('editor protocol fixture'); editor.chmod(0o755)
        real_run = subprocess.run
        def edit_copy(argv, **kwargs):
            if argv[0] != str(editor):
                return real_run(argv, **kwargs)
            self.assertEqual(argv[1], '--remove-rpath')
            # The protocol fixture supplies a separately linked real ELF with
            # identical contracts and no search tags. Retained-SDK qualification
            # separately exercises the actual authenticated patchelf executable.
            shutil.copyfile(clean, argv[2])
            return subprocess.CompletedProcess(argv, 0)
        with patch('stage_runtime.subprocess.run', side_effect=edit_copy):
            result = stage_runtime.stage([binary / 'application'], [supplier], libraries,
                                        processor=self.processor, elf_editor=editor)
        self.assertEqual(original, {p.name: digest(p) for p in supplier.iterdir()})
        self.assertEqual(original, result['files'])
        self.assertEqual(digest(libraries / middle.name), result['installed_files'][middle.name])
        self.assertNotEqual(result['files'][middle.name], result['installed_files'][middle.name])
        receipt = result['transformations'][middle.name]
        self.assertEqual(digest(editor), receipt['editor_sha256'])
        self.assertEqual([''], receipt['original_runpath'])
        self.assertEqual(original[middle.name], receipt['source_sha256'])
        self.assertEqual('passed', verify_abi.audit(package, processor=self.processor)['runtime_resolution'])
        supplier.rename(self.root / 'unavailable-supplier')
        relocated = self.root / 'relocated package'; package.rename(relocated)
        subprocess.run([str(relocated / 'bin/application')], check=True, env=environment, cwd=self.root)

    def test_nonempty_unsafe_path_is_not_normalized(self):
        package, binary, libraries = self.linked_package()
        subprocess.run(['cc', '-shared', '-fPIC', str(self.root / 'middle.c'),
                        str(libraries / 'libleaf.so.1'), '-Wl,-soname,libmiddle.so.1',
                        '-Wl,-rpath,:$ORIGIN', '-o', str(libraries / 'libmiddle.so.1')], check=True)
        with self.assertRaisesRegex(ValueError, 'must be relative'):
            stage_runtime.stage([binary / 'application'], [libraries], self.root / 'rejected',
                                processor=self.processor, elf_editor='must-not-run')
        self.assertFalse((self.root / 'rejected').exists())

    def test_empty_path_editor_failure_does_not_publish(self):
        package, binary, libraries = self.linked_package()
        middle = libraries / 'libmiddle.so.1'
        subprocess.run(['cc', '-shared', '-fPIC', str(self.root / 'middle.c'),
                        str(libraries / 'libleaf.so.1'), '-Wl,-soname,libmiddle.so.1',
                        '-Wl,-rpath,', '-o', str(middle)], check=True)
        before = middle.read_bytes()
        for editor, error in ((self.root / 'absent-editor', ValueError),
                              (shutil.which('false'), subprocess.CalledProcessError),
                              (shutil.which('true'), ValueError)):
            with self.subTest(editor=editor), self.assertRaises(error):
                stage_runtime.stage([binary / 'application'], [libraries], self.root / 'rejected',
                                    processor=self.processor, elf_editor=editor)
            self.assertFalse((self.root / 'rejected').exists())
            self.assertEqual(before, middle.read_bytes())

    def test_mixed_tags_never_invoke_editor(self):
        with patch('stage_runtime.inspect', return_value={'rpaths': ['', '$ORIGIN']}), \
             patch('stage_runtime.shutil.which') as editor:
            with self.assertRaisesRegex(ValueError, 'mixed empty'):
                stage_runtime.normalize_empty_paths(self.root / 'application')
            editor.assert_not_called()

    def test_runpath_is_not_inherited(self):
        package, _, _ = self.linked_package(inherited=False)
        with self.assertRaisesRegex(ValueError, 'loader cannot resolve libleaf'):
            verify_abi.audit(package, processor=self.processor)

    def test_each_library_own_runpath_can_resolve_closure(self):
        package, binary, _ = self.linked_package(inherited=False, middle_path=True)
        self.assertEqual(verify_abi.audit(package, processor=self.processor)['runtime_resolution'], 'passed')
        subprocess.run([str(binary / 'application')], check=True,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, cwd=self.root)

    def test_provider_in_unsearched_directory_rejected(self):
        package, _, libraries = self.linked_package()
        wrong = package / 'wrong'
        wrong.mkdir()
        (libraries / 'libleaf.so.1').rename(wrong / 'libleaf.so.1')
        with self.assertRaisesRegex(ValueError, 'loader cannot resolve libleaf'):
            verify_abi.audit(package, processor=self.processor)

    def test_multiple_searched_providers_rejected(self):
        package, binary, libraries = self.linked_package()
        other = package / 'other'
        other.mkdir()
        shutil.copyfile(libraries / 'libmiddle.so.1', other / 'libmiddle.so.1')
        subprocess.run(['cc', str(self.root / 'entry.c'), str(libraries / 'libmiddle.so.1'),
                        '-Wl,-rpath-link,' + str(libraries),
                        '-Wl,-rpath,$ORIGIN/../lib/runtime:$ORIGIN/../other',
                        '-Wl,--disable-new-dtags', '-o', str(binary / 'application')], check=True)
        with self.assertRaisesRegex(ValueError, 'ambiguous runtime loader'):
            verify_abi.audit(package, processor=self.processor)

    def test_native_staging_records_newer_floor_without_claiming_bookworm(self):
        libraries = self.root / 'supplier'
        libraries.mkdir()
        (self.root / 'leaf.c').write_text('int late(void) { return 42; }\n')
        (self.root / 'middle.c').write_text('extern int late(void); int value(void) { return late(); }\n')
        (self.root / 'versions.map').write_text('GLIBC_2.37 { global: late; local: *; };\n')
        subprocess.run(['cc', '-shared', '-fPIC', str(self.root / 'leaf.c'),
                        '-Wl,--version-script=' + str(self.root / 'versions.map'),
                        '-Wl,-soname,libleaf.so.1', '-o', str(libraries / 'libleaf.so.1')], check=True)
        subprocess.run(['cc', '-shared', '-fPIC', str(self.root / 'middle.c'),
                        str(libraries / 'libleaf.so.1'), '-Wl,-soname,libmiddle.so.1',
                        '-o', str(libraries / 'libmiddle.so.1')], check=True)
        self.assertEqual(verify_abi.inspect(libraries / 'libmiddle.so.1')['requirements']['GLIBC'], '2.37')
        # Include the dependent object itself in the copied closure, so staging
        # audits its real imported requirement rather than only its provider.
        (self.root / 'use.c').write_text('extern int value(void); int main(void) { return value()!=42; }\n')
        subprocess.run(['cc', str(self.root / 'use.c'), str(libraries / 'libmiddle.so.1'),
                        '-Wl,-rpath-link,' + str(libraries), '-o', str(self.root / 'use')], check=True)
        with self.assertRaisesRegex(ValueError, 'above ceiling'):
            stage_runtime.stage([self.root / 'use'], [libraries], self.root / 'fixed-package',
                                processor=self.processor)
        self.assertFalse((self.root / 'fixed-package').exists())
        report = stage_runtime.stage([self.root / 'use'], [libraries], self.root / 'native',
                                     processor=self.processor, audit_baseline=False)
        self.assertEqual(report['abi']['ceilings']['GLIBC'], '2.37')
        self.assertEqual(report['baseline_qualification'], 'native-observed-requirements-only')
        self.assertEqual(report['runtime_resolution'], 'requires_final_package_audit')



    def sdk_runtime_fixture(self, libc_version='2.36'):
        from dependency_archive import file_inventory
        sysroot = self.root / 'sysroot'; libraries = sysroot / 'lib'; libraries.mkdir(parents=True)
        loader = 'ld-linux-x86-64.so.2' if self.processor == 'x86_64' else 'ld-linux-aarch64.so.1'
        (self.root / 'loader.c').write_text('int internal_value(void) { return 1; }\n')
        (self.root / 'loader.map').write_text('GLIBC_PRIVATE { global: internal_value; local: *; };\n')
        (self.root / 'libc.c').write_text('extern int internal_value(void); int public_value(void) { return internal_value(); } int libc_internal_value(void) { return internal_value(); }\n')
        (self.root / 'libc.map').write_text('GLIBC_' + libc_version + ' { global: public_value; local: *; };\nGLIBC_PRIVATE { global: libc_internal_value; };\n')
        subprocess.run(['cc', '-shared', '-nostdlib', '-fPIC', str(self.root / 'loader.c'),
                        '-Wl,--version-script=' + str(self.root / 'loader.map'), '-Wl,-soname,' + loader,
                        '-o', str(libraries / loader)], check=True)
        subprocess.run(['cc', '-shared', '-nostdlib', '-fPIC', str(self.root / 'libc.c'), str(libraries / loader),
                        '-Wl,--version-script=' + str(self.root / 'libc.map'), '-Wl,-soname,libc.so.6',
                        '-o', str(libraries / 'libc.so.6')], check=True)
        context = {'recipe_id': 'a' * 64, 'source_sha256': 'b' * 64, 'glibc': '2.36',
                   'processor': self.processor, 'files': file_inventory(sysroot)}
        return sysroot, context

    def sdk_companion_fixture(self):
        from dependency_archive import file_inventory
        sysroot, context = self.sdk_runtime_fixture()
        loader = next(path for path in (sysroot / 'lib').iterdir() if path.name.startswith('ld-'))
        (self.root / 'companion.c').write_text('extern int internal_value(void); int companion(void) { return internal_value(); }\n')
        (self.root / 'companion.map').write_text('GLIBC_2.22 { global: companion; local: *; };\n')
        for name in ('libmvec.so.1', 'libresolv.so.2', 'libnss_db.so.2', 'libc_malloc_debug.so.0', 'libcrypt.so.1'):
            path = sysroot / 'lib' / name
            body = 'internal_value()'
            providers = [loader]
            if name in ('libc_malloc_debug.so.0', 'libcrypt.so.1'):
                body = ('internal_value() + ' if name == 'libc_malloc_debug.so.0' else '') + 'libc_internal_value()'
                providers = ([loader] if name == 'libc_malloc_debug.so.0' else []) + [sysroot/'lib/libc.so.6']
            (self.root/'companion.c').write_text('extern int internal_value(void); extern int libc_internal_value(void); int companion(void) { return '+body+'; }\n')
            subprocess.run(['cc', '-shared', '-nostdlib', '-fPIC', str(self.root / 'companion.c'), *map(str, providers),
                            '-Wl,--version-script=' + str(self.root / 'companion.map'), '-Wl,-soname,' + name,
                            '-o', str(path)], check=True)
            shutil.copyfile(path, path.with_name(name.rsplit('.', 1)[0]))
        context['files'] = file_inventory(sysroot)
        return sysroot, context

    def test_sdk_debug_library_and_linking_inputs_remain_in_exact_cohort(self):
        from dependency_archive import file_inventory
        sysroot, context = self.sdk_companion_fixture()
        # The real supplier installs this independent static linking input too.
        linking = sysroot / 'lib/libmcheck.a'; linking.write_bytes(b'!<arch>\n')
        legacy = dict(context, files={name: value for name, value in context['files'].items()
                                    if Path(name).name not in ('libc_malloc_debug.so', 'libc_malloc_debug.so.0', 'libcrypt.so', 'libcrypt.so.1')})
        with self.assertRaisesRegex(ValueError, 'PRIVATE'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=legacy)
        before = file_inventory(sysroot)
        report = verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        for name in ('lib/libc_malloc_debug.so', 'lib/libc_malloc_debug.so.0'):
            self.assertEqual(report['files'][name]['private_requirements'],
                             ['ld-linux-x86-64.so.2' if self.processor == 'x86_64' else 'ld-linux-aarch64.so.1', 'libc.so.6'])
        for name in ('lib/libcrypt.so', 'lib/libcrypt.so.1'):
            self.assertEqual(report['files'][name]['private_requirements'], ['libc.so.6'])
        self.assertEqual(file_inventory(sysroot), before)
        self.assertEqual(linking.read_bytes(), b'!<arch>\n')
        with self.assertRaisesRegex(ValueError, 'PRIVATE'):
            verify_abi.audit(sysroot / 'lib/libc_malloc_debug.so.0', processor=self.processor)
        with self.assertRaisesRegex(ValueError, 'application packages'):
            verify_abi.audit(sysroot, processor=self.processor, sdk_sysroot=context)
        with self.assertRaisesRegex(ValueError, 'must not bundle'):
            verify_abi.resolve_closure(sysroot, report['files'])

    def test_sdk_debug_cohort_rejects_wrong_name_location_provider_or_hash(self):
        from dependency_archive import digest, file_inventory
        sysroot, context = self.sdk_companion_fixture()
        alias = sysroot/'lib/libc_malloc_debug.so'; provider = sysroot/'lib/libc_malloc_debug.so.0'
        original = provider.read_bytes()
        context['files']['lib/libc_malloc_debug.so.0'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'path or digest'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        context['files'] = file_inventory(sysroot)
        for name in ('lib/libc_malloc_debug_extra.so', 'bin/libc_malloc_debug.so.0'):
            destination = sysroot/name; destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(provider, destination)
            context['files'] = file_inventory(sysroot)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'path or digest'):
                verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
            del context['files'][name]
            with self.assertRaisesRegex(ValueError, 'PRIVATE'):
                verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
            destination.unlink()
        provider.write_bytes(original+b'different provider bytes')
        context['files'] = file_inventory(sysroot)
        with self.assertRaisesRegex(ValueError, 'identical runtime provider'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        provider.write_bytes(original); context['files'] = file_inventory(sysroot)
        del context['files']['lib/libc_malloc_debug.so.0']
        with self.assertRaisesRegex(ValueError, 'identical runtime provider'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)

    def test_sdk_companions_and_identical_development_aliases_are_audited(self):
        sysroot, context = self.sdk_companion_fixture()
        report = verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        for name in ('libmvec.so', 'libmvec.so.1', 'libresolv.so', 'libnss_db.so'):
            self.assertTrue(report['files']['lib/' + name]['private_requirements'])
        with self.assertRaisesRegex(ValueError, 'PRIVATE'):
            verify_abi.audit(sysroot / 'lib/libmvec.so.1', processor=self.processor)

    def test_sdk_development_alias_needs_exact_provider_bytes(self):
        from dependency_archive import file_inventory
        sysroot, context = self.sdk_companion_fixture()
        alias = sysroot / 'lib/libmvec.so'
        alias.write_bytes(alias.read_bytes() + b'changed')
        context['files'] = file_inventory(sysroot)
        with self.assertRaisesRegex(ValueError, 'identical runtime provider'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        shutil.copyfile(sysroot / 'lib/libmvec.so.1', alias)
        context['files'] = file_inventory(sysroot); del context['files']['lib/libmvec.so.1']
        with self.assertRaisesRegex(ValueError, 'identical runtime provider'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)

    def test_target_projection_does_not_exempt_other_private_consumers(self):
        import distro_sdk
        sysroot, context = self.sdk_companion_fixture()
        (sysroot / 'usr/bin').mkdir(parents=True)
        for name in ('gencat', 'iconv', 'application'):
            shutil.copyfile(sysroot / 'lib/libmvec.so.1', sysroot / 'usr/bin' / name)
        relocations = self.root / 'share/buildroot/sdk-relocs'; relocations.parent.mkdir(parents=True)
        relocations.write_text('')
        distro_sdk.omit_target_runtime(self.root, 'sysroot', distro_sdk.GLIBC_RUNTIME_SOURCE)
        self.assertFalse((sysroot / 'usr/bin/iconv').exists())
        self.assertFalse((sysroot / 'usr/bin/gencat').exists())
        self.assertTrue((sysroot / 'usr/bin/application').is_file())
        with self.assertRaisesRegex(ValueError, 'PRIVATE'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)

    def test_sdk_private_cohort_does_not_weaken_package_audit(self):
        sysroot, context = self.sdk_runtime_fixture()
        with self.assertRaisesRegex(ValueError, 'PRIVATE'):
            verify_abi.audit(sysroot, processor=self.processor, host=True)
        report = verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        self.assertEqual(report['scope'], 'sdk-sysroot')
        self.assertTrue(report['files']['lib/libc.so.6']['private_requirements'])
        with self.assertRaisesRegex(ValueError, 'application packages'):
            verify_abi.audit(sysroot, processor=self.processor, sdk_sysroot=context)

    def test_sdk_private_cohort_requires_exact_files_and_locations(self):
        sysroot, context = self.sdk_runtime_fixture()
        context['files']['lib/libc.so.6'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'path or digest'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        from dependency_archive import file_inventory
        (sysroot / 'bin').mkdir(); (sysroot / 'lib/libc.so.6').rename(sysroot / 'bin/libc.so.6')
        context['files'] = file_inventory(sysroot)
        with self.assertRaisesRegex(ValueError, 'path or digest'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)

    def test_sdk_private_cohort_checks_runtime_version_and_source_binding(self):
        sysroot, context = self.sdk_runtime_fixture('2.37')
        with self.assertRaisesRegex(ValueError, 'definition exceeds'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)
        context['source_sha256'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'source identities'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)

    def test_sdk_private_cohort_requires_matching_provider(self):
        from dependency_archive import file_inventory
        sysroot, context = self.sdk_runtime_fixture()
        loader = next(path for path in (sysroot / 'lib').iterdir() if path.name.startswith('ld-'))
        (self.root / 'loader.map').write_text('UNRELATED { global: internal_value; local: *; };\n')
        subprocess.run(['cc', '-shared', '-nostdlib', '-fPIC', str(self.root / 'loader.c'),
                        '-Wl,--version-script=' + str(self.root / 'loader.map'), '-Wl,-soname,' + loader.name,
                        '-o', str(loader)], check=True)
        context['files'] = file_inventory(sysroot)
        with self.assertRaisesRegex(ValueError, 'matched runtime provider'):
            verify_abi.audit(sysroot, processor=self.processor, host=True, sdk_sysroot=context)


class WindowsInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def sample(self, name='application.exe', dependency='kernel32.dll', machine=0x8664, delayed=False):
        import struct
        data = bytearray(1024)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 128)
        data[128:132] = b'PE\0\0'
        struct.pack_into('<HH', data, 132, machine, 1)
        struct.pack_into('<H', data, 148, 240)
        optional = 152
        struct.pack_into('<H', data, optional, 0x20b)
        struct.pack_into('<HH', data, optional + 40, 6, 0)
        struct.pack_into('<I', data, optional + 60, 512)
        struct.pack_into('<I', data, optional + 108, 16)
        index = 13 if delayed else 1
        width = 32 if delayed else 20
        struct.pack_into('<II', data, optional + 112 + index * 8, 4096, width * 2)
        section = optional + 240
        struct.pack_into('<IIII', data, section + 8, 512, 4096, 512, 512)
        if delayed: struct.pack_into('<II', data, 512, 1, 4224)
        else: struct.pack_into('<I', data, 524, 4224)
        encoded = dependency.encode() + b'\0'
        data[640:640 + len(encoded)] = encoded
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_pe_system_import(self):
        import verify_pe
        self.sample()
        self.assertEqual(verify_pe.audit(self.root)['status'], 'passed')

    def test_shared_runtime_not_assumed_os_library(self):
        import verify_pe
        self.sample(dependency='VCRUNTIME140.dll')
        with self.assertRaisesRegex(ValueError, 'static CRT'):
            verify_pe.audit(self.root)

    def test_delayed_missing_library_rejected(self):
        import verify_pe
        self.sample(dependency='optional-provider.dll', delayed=True)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            verify_pe.audit(self.root)

    def test_pe_wrong_architecture_rejected(self):
        import verify_pe
        self.sample(machine=0xaa64)
        with self.assertRaisesRegex(ValueError, 'architecture'):
            verify_pe.audit(self.root)

    def test_truncated_pe_rejected(self):
        import verify_pe
        path = self.sample()
        path.write_bytes(path.read_bytes()[:200])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            verify_pe.audit(self.root)

if __name__ == '__main__': unittest.main()
