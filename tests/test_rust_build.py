"""Controlled Cargo input, ownership, freshness and generated-archive contracts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import rust_build


class RustBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='foundation Rust tests ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source tree'
        self.build = self.root / 'build tree'
        self.source.mkdir()
        self.build.mkdir()
        self.crate = self.source / 'rust/text_validation'
        (self.crate / 'src').mkdir(parents=True)
        for path in (self.source / 'rust/Cargo.toml', self.source / 'rust/Cargo.lock',
                     self.crate / 'Cargo.toml', self.crate / 'src/lib.rs'):
            path.write_text('controlled input\n', encoding='utf-8')
        (self.source / 'rust/Cargo.lock').write_text('version = 3\n\n[[package]]\n', encoding='utf-8')
        self.tools = {}
        for name in ('cargo', 'rustc'):
            path = self.root / name
            path.write_bytes(name.encode())
            path.chmod(0o755)
            self.tools[name] = str(path)
        self.sysroot = self.root / 'retained sysroot'
        self.libdir = self.sysroot / 'lib/rustlib/x86_64-unknown-linux-gnu/lib'
        self.libdir.mkdir(parents=True)
        for name in ('libcore-identified.rlib', 'libcompiler_builtins-identified.rlib',
                     'libstd-a5a48102fbd58791.rlib', 'libtest-8bb3380c32c2be31.rlib'):
            (self.libdir / name).write_bytes(name.encode())
        self.notice = self.root / 'copyright'
        self.notice.write_text('Complete retained compiler support license\n', encoding='utf-8')
        self.target = 'x86_64-unknown-linux-gnu'
        self.metadata = {'packages': [{'id': 'foundation-text-validation 0.1.0 (path+file://fixture)',
                                      'name': 'foundation-text-validation',
                                      'source': None, 'dependencies': [], 'edition': '2021',
                                      'rust_version': '1.63', 'manifest_path': str(self.crate / 'Cargo.toml'),
                                      'targets': [{'name': 'foundation_rust',
                                                   'crate_types': ['staticlib', 'rlib'],
                                                   'kind': ['staticlib', 'rlib']}]}],
                         'workspace_members': ['foundation-text-validation 0.1.0 (path+file://fixture)'],
                         'workspace_root': str(self.source / 'rust')}
        self.config_path = self.build / 'config.json'
        self.calls = []
        self.fake_fresh = False
        self.fake_native_libs = 'note: native-static-libs: -lgcc_s -lutil -lrt -lpthread -lm -ldl -lc\n'

    def fake_run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if '-vV' in argv:
            return 'rustc 1.63.0\nhost: ' + self.target + '\nrelease: 1.63.0\nLLVM version: 14.0.6\n'
        if '--version' in argv:
            return 'cargo 1.65.0\n'
        if '--print' in argv:
            mode = argv[argv.index('--print') + 1]
            if mode == 'sysroot':
                return str(self.sysroot) + '\n'
            if mode == 'target-libdir':
                return str(self.libdir) + '\n'
            if mode == 'native-static-libs':
                Path(argv[argv.index('-o') + 1]).write_bytes(b'probe archive')
                return self.fake_native_libs
        if 'metadata' in argv:
            return json.dumps(self.metadata)
        if 'build' in argv:
            artifact = self.build / 'target' / self.target / 'debug/libfoundation_rust.a'
            artifact.parent.mkdir(parents=True, exist_ok=True)
            if not artifact.exists() or not self.fake_fresh:
                artifact.write_bytes(b'produced static archive')
            return json.dumps({'reason': 'compiler-artifact',
                               'package_id': self.metadata['packages'][0]['id'],
                               'filenames': [str(artifact)], 'fresh': self.fake_fresh}) + '\n'
        if 'clean' in argv:
            return ''
        if 'test' in argv:
            return 'test result: ok. 4 passed; 0 failed\n'
        raise AssertionError('unexpected controlled command: ' + repr(argv))

    def describe(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(rust_build, '_run', side_effect=self.fake_run), \
             patch.object(rust_build.package_notices, 'distro_notice', return_value=({}, self.notice)):
            return rust_build.describe(str(self.source), str(self.build), self.target,
                                       self.tools['cargo'], self.tools['rustc'])

    def configured(self):
        data = self.describe()
        rust_build.save_config(self.config_path, data)
        return data

    def built(self):
        data = self.configured()
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            rust_build.build(str(self.config_path))
        return data

    def test_describe_binds_sources_tools_target_libraries_and_native_linkage(self):
        data = self.describe()
        self.assertEqual(data['tools']['rustc']['version'], '1.63.0')
        self.assertEqual(data['source_inputs'], sorted(data['sources']))
        self.assertEqual(len([path for path in data['source_inputs'] if str(self.source / 'rust') in path]), 4)
        self.assertIn(str(Path(rust_build.__file__).resolve()), data['source_inputs'])
        self.assertEqual(len(data['target_libraries']), 4)
        self.assertEqual(data['native_static_libs'], ['gcc_s', 'util', 'rt', 'pthread', 'm', 'dl', 'c'])
        self.assertEqual(data['notice_files'], [str(self.notice)])
        metadata_call = next(row for row in self.calls if 'metadata' in row[0])
        self.assertIn('--frozen', metadata_call[0])
        self.assertIn('--no-deps', metadata_call[0])
        probe_call = next(row for row in self.calls if 'native-static-libs' in row[0])
        self.assertIs(probe_call[1]['compiler'], True)
        self.assertIn('-Cpanic=abort', probe_call[0])
        self.assertIn('-Clto=no', probe_call[0])

    def test_paths_with_spaces_use_encoded_flags_and_private_cargo_directories(self):
        environment = rust_build.child_environment(self.build, self.tools['cargo'], self.tools['rustc'],
                                                    ['--sysroot', str(self.sysroot), '-Clto=no'], {})
        self.assertNotIn('RUSTFLAGS', environment)
        self.assertEqual(environment['CARGO_ENCODED_RUSTFLAGS'].split('\x1f'),
                         ['--sysroot', str(self.sysroot), '-Clto=no'])
        self.assertEqual(environment['CARGO_HOME'], str(self.build / 'cargo-home'))
        self.assertEqual(environment['CARGO_TARGET_DIR'], str(self.build / 'target'))
        self.assertEqual(environment['RUSTC'], self.tools['rustc'])

    def test_ambient_flags_wrappers_target_settings_and_proxies_are_rejected(self):
        for key in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER',
                    'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER', 'CARGO_BUILD_TARGET',
                    'CARGO_PROFILE_RELEASE_PANIC', 'RUSTUP_TOOLCHAIN'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'ambient Rust setting'):
                rust_build.child_environment(self.build, self.tools['cargo'], self.tools['rustc'], [], {key: 'foreign'})
        for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'host search override'):
                rust_build.child_environment(self.build, self.tools['cargo'], self.tools['rustc'], [], {key: 'foreign'})
        rustup = self.root / 'rustup'
        rustup.write_bytes(b'proxy')
        rustup.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'proxies are unsupported'):
            rust_build.native_tool_identity(str(rustup), self.tools['rustc'])
        proxy = self.root / 'proxy-cargo'
        os.link(rustup, proxy)
        with self.assertRaisesRegex(ValueError, 'proxies are unsupported'):
            rust_build.native_tool_identity(str(proxy), self.tools['rustc'])
        proxy_copy = self.root / 'copied-proxy-cargo'
        proxy_copy.write_bytes(rustup.read_bytes())
        proxy_copy.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'proxies are unsupported'):
            rust_build.native_tool_identity(str(proxy_copy), self.tools['rustc'])

    def test_inherited_jobserver_and_cache_selection_never_reach_cargo(self):
        inherited = {'PATH': '/selected/cxx', 'MAKEFLAGS': '--jobserver-auth=3,4 -j8',
                     'MFLAGS': '-j8', 'CARGO_MAKEFLAGS': '--jobserver-auth=3,4', 'MAKELEVEL': '2',
                     'CARGO_HOME': '/foreign/cache', 'CARGO_TARGET_DIR': '/foreign/output'}
        environment = rust_build.child_environment(self.build, self.tools['cargo'], self.tools['rustc'], [], inherited)
        for name in ('MAKEFLAGS', 'MFLAGS', 'CARGO_MAKEFLAGS', 'MAKELEVEL'):
            self.assertNotIn(name, environment)
        self.assertEqual(environment['CARGO_BUILD_JOBS'], '1')
        self.assertNotIn('/foreign/', environment['CARGO_HOME'])
        self.assertEqual(inherited['MAKELEVEL'], '2')

    def test_ancestor_or_private_cargo_configuration_blocks_before_tool_execution(self):
        directory = self.source / '.cargo'
        directory.mkdir()
        (directory / 'config.toml').write_text('[build]\nrustc-wrapper="foreign"\n')
        with self.assertRaisesRegex(ValueError, 'ambient Cargo configuration'):
            self.describe()
        self.assertEqual(self.calls, [])
        (directory / 'config.toml').unlink()
        private = self.build / 'cargo-home'
        private.mkdir()
        (private / 'config').write_text('[source.crates-io]\nreplace-with="foreign"\n')
        with self.assertRaisesRegex(ValueError, 'private Cargo home'):
            self.describe()
        self.assertEqual(self.calls, [])

    def test_unprepared_cross_target_and_unknown_unknown_are_not_substituted(self):
        for target in ('wasm32-unknown-unknown', 'wasm32-unknown-emscripten', 'x86_64-pc-windows-msvc'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'unsupported|prepared retained'):
                rust_build.describe(str(self.source), str(self.build), target, **self.tools)
        self.target = 'aarch64-unknown-linux-gnu'
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(rust_build, '_run', return_value='release: 1.63.0\nhost: x86_64-unknown-linux-gnu\n'):
            with self.assertRaisesRegex(ValueError, 'exact host target'):
                rust_build.describe(str(self.source), str(self.build), self.target, **self.tools)

    def test_missing_absolute_tools_workspace_and_target_core_are_actionable(self):
        with self.assertRaisesRegex(ValueError, 'absolute paths'):
            rust_build.native_tool_identity('cargo', self.tools['rustc'])
        (self.source / 'rust/Cargo.lock').unlink()
        with self.assertRaisesRegex(ValueError, 'missing Rust workspace'):
            self.describe()
        (self.source / 'rust/Cargo.lock').write_text('version = 3\n')
        (self.libdir / 'libcore-identified.rlib').unlink()
        with self.assertRaisesRegex(ValueError, 'missing matched libcore'):
            self.describe()

    def test_lockfile_and_actual_compiler_keep_the_baseline(self):
        (self.source / 'rust/Cargo.lock').write_text('version = 4\n')
        with self.assertRaisesRegex(ValueError, 'Cargo.lock format 3'):
            self.describe()
        (self.source / 'rust/Cargo.lock').write_text('version = 3\n')
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', return_value='release: 1.62.0\nhost: ' + self.target):
            with self.assertRaisesRegex(ValueError, 'at least version 1.63.0'):
                rust_build.describe(str(self.source), str(self.build), self.target, **self.tools)
        self.metadata['workspace_root'] = str(self.source)
        with self.assertRaisesRegex(ValueError, 'one dependency-free workspace member'):
            self.describe()

    def test_retained_executable_versions_and_host_must_match_sdk_metadata(self):
        import rust_sdk
        compiler = {'version': '1.63.0', 'cargo_version': '1.65.0', 'host': self.target,
                    'rustc': 'rustc', 'cargo': 'cargo', 'sysroot': 'retained sysroot'}
        manifest = {'compiler': compiler, 'target': {'library_directory': str(self.libdir.relative_to(self.root))},
                    'licenses': ['copyright']}
        (self.root / 'rust-sdk.json').write_text(json.dumps(manifest))
        for name, value in (('version', '1.64.0'), ('cargo_version', '1.64.0'),
                            ('host', 'aarch64-unknown-linux-gnu')):
            original = compiler[name]
            compiler[name] = value
            with self.subTest(field=name), patch.dict(os.environ, {}, clear=True), \
                 patch.object(rust_build, '_run', side_effect=self.fake_run), \
                 patch.object(rust_sdk, 'verify_rust_sdk', return_value=manifest):
                with self.assertRaisesRegex(ValueError, 'versions differ from retained SDK metadata'):
                    rust_build.describe(str(self.source), str(self.build), self.target,
                                        **self.tools, sdk_root=str(self.root))
            compiler[name] = original

    def test_workspace_external_crates_build_scripts_and_proc_macros_are_rejected(self):
        package = self.metadata['packages'][0]
        package['dependencies'] = [{'name': 'foreign', 'source': 'registry+https://index.crates.io'}]
        with self.assertRaisesRegex(ValueError, 'zero external crates'):
            self.describe()
        package['dependencies'] = []
        package['targets'].append({'name': 'build-script-build', 'kind': ['custom-build'], 'crate_types': ['bin']})
        with self.assertRaisesRegex(ValueError, 'no build scripts or macros'):
            self.describe()
        package['targets'].pop()
        package['targets'][0]['crate_types'] = ['proc-macro']
        with self.assertRaisesRegex(ValueError, 'no build scripts or macros'):
            self.describe()
        package['targets'][0]['crate_types'] = ['staticlib', 'rlib']
        (self.crate / 'build.rs').write_text('fn main() {}')
        with self.assertRaisesRegex(ValueError, 'build scripts are unsupported'):
            self.describe()

    def test_source_links_and_output_beneath_rust_are_rejected(self):
        if os.name != 'nt':
            (self.crate / 'src/foreign.rs').symlink_to(self.notice)
            with self.assertRaisesRegex(ValueError, 'source tree must not contain links'):
                self.describe()
            (self.crate / 'src/foreign.rs').unlink()
        with self.assertRaisesRegex(ValueError, 'outside the Rust source tree'):
            rust_build.describe(str(self.source), str(self.source / 'rust/target'), self.target, **self.tools)

    def distro_layout(self):
        usr = self.root / 'usr'
        self.sysroot.rename(usr)
        self.sysroot = usr
        self.libdir = usr / 'lib/rustlib' / self.target / 'lib'
        (usr / 'bin').mkdir()
        for name in ('cargo', 'rustc'):
            destination = usr / 'bin' / name
            shutil.copy2(self.tools[name], destination)
            self.tools[name] = str(destination)
        (usr / 'bin/dpkg-query').write_bytes(b'identified package ownership tool')
        runtime = usr / 'lib/x86_64-linux-gnu'
        runtime.mkdir()
        self.owners = {self.tools['rustc']: 'rustc'}
        self.versions = {package: '1.63.0+dfsg1-2' for package in
                         ('rustc', 'libstd-rust-dev:amd64', 'libstd-rust-1.63:amd64')}
        self.statuses = {}
        self.runtime_links = []
        for rlib in sorted(self.libdir.glob('libstd-*.rlib')) + sorted(self.libdir.glob('libtest-*.rlib')):
            link = rlib.with_suffix('.so')
            destination = runtime / link.name
            destination.write_bytes(link.name.encode())
            link.symlink_to('../../../x86_64-linux-gnu/' + link.name)
            self.owners[str(link)] = 'libstd-rust-dev:amd64'
            self.owners[str(destination)] = 'libstd-rust-1.63:amd64'
            self.runtime_links.append((link, destination))
        self.distro_notices = []
        for name in ('libstd-rust-dev', 'libstd-rust-1.63'):
            notice = usr / 'share/doc' / name / 'copyright'
            notice.parent.mkdir(parents=True)
            notice.write_text('Complete ' + name + ' copyright\n', encoding='utf-8')
            self.distro_notices.append(notice)
        for mock in (patch.object(rust_build, 'DISTRO_USR', usr),
                     patch.object(rust_build.package_notices, 'command', side_effect=self.distro_query)):
            mock.start()
            self.addCleanup(mock.stop)

    def distro_query(self, query, operation, *args):
        self.assertEqual(query, str(self.sysroot / 'bin/dpkg-query'))
        if operation == '-S':
            path = args[0]
            if path not in self.owners:
                raise subprocess.CalledProcessError(1, [query, operation, path])
            package = self.owners[path]
            return package + ': ' + path
        self.assertEqual(operation, '-W')
        self.assertEqual(args[0], '-f=${db:Status-Abbrev}\n${Version}')
        return self.statuses.get(args[1], 'ii ') + '\n' + self.versions.get(args[1], '1.63.0+dfsg1-2')

    def test_native_distro_links_bind_owners_versions_link_and_runtime_notices(self):
        self.distro_layout()
        data = self.built()
        self.assertEqual(len(data['target_libraries']), 6)
        for link, target in self.runtime_links:
            row = data['target_libraries'][str(link)]
            self.assertEqual(row['path'], str(link))
            self.assertEqual(row['link'], os.readlink(link))
            self.assertEqual(row['target'], rust_build._snapshot(target))
            self.assertEqual(row['compiler_package'], {'package': 'rustc', 'version': '1.63.0+dfsg1-2'})
            self.assertEqual(row['target_package']['package'], 'libstd-rust-1.63:amd64')
        self.assertEqual(data['notice_files'], sorted(map(str, [self.notice] + self.distro_notices)))
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            self.fake_fresh = True
            rust_build.build(str(self.config_path))
            rust_build.test(str(self.config_path))
        rust_build.verify(str(self.config_path))

    def test_retained_target_libraries_still_reject_native_distro_links(self):
        self.distro_layout()
        with self.assertRaisesRegex(ValueError, 'must not contain symlinks'):
            rust_build._target_libraries(self.libdir)

    def test_native_distro_bad_dangling_escaping_chained_and_special_link_targets(self):
        self.distro_layout()
        link, target = self.runtime_links[0]
        original = os.readlink(link)
        foreign = self.root / link.name
        foreign.write_bytes(b'foreign runtime')
        for text in ('missing-runtime.so', str(foreign), str(target.parent / 'other-name.so')):
            link.unlink()
            link.symlink_to(text)
            with self.subTest(target=text), self.assertRaisesRegex(ValueError, 'invalid native Rust library link'):
                self.describe()
        link.unlink()
        link.symlink_to(original)
        target.unlink()
        with self.assertRaisesRegex(ValueError, 'invalid native Rust library link'):
            self.describe()
        target.symlink_to(foreign)
        with self.assertRaisesRegex(ValueError, 'invalid native Rust library link'):
            self.describe()
        target.unlink()
        os.mkfifo(target)
        with self.assertRaisesRegex(ValueError, 'invalid native Rust library link'):
            self.describe()

    def test_native_distro_directory_links_and_other_library_names_are_not_allowed(self):
        self.distro_layout()
        link, _ = self.runtime_links[0]
        link.rename(link.with_name('libforeign-1234.so'))
        with self.assertRaisesRegex(ValueError, 'unsupported native Rust library link layout'):
            self.describe()
        link.with_name('libforeign-1234.so').unlink()
        (self.libdir / 'foreign-directory').symlink_to(self.libdir, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsupported native Rust library link layout'):
            self.describe()

    def test_native_distro_package_ambiguity_unowned_wrong_owner_and_versions_fail(self):
        self.distro_layout()
        link, target = self.runtime_links[0]
        for path, owner in ((link, 'foreign:amd64'), (target, 'libstd-rust-1.63:arm64'),
                            (link, 'libstd-rust-dev:amd64: ' + str(link) + '\nforeign')):
            original = self.owners[str(path)]
            self.owners[str(path)] = owner
            with self.subTest(owner=owner), self.assertRaisesRegex(ValueError, 'package ownership|package owners or versions differ'):
                self.describe()
            self.owners[str(path)] = original
        original = self.owners.pop(str(link))
        with self.assertRaisesRegex(ValueError, 'package ownership is unavailable'):
            self.describe()
        self.owners[str(link)] = original
        for package in self.versions:
            previous = self.versions[package]
            self.versions[package] = '1.63.0+dfsg1-3'
            with self.subTest(package=package), self.assertRaisesRegex(ValueError, 'package owners or versions differ'):
                self.describe()
            self.versions[package] = previous
        self.statuses['libstd-rust-dev:amd64'] = 'rc '
        with self.assertRaisesRegex(ValueError, 'package is not installed'):
            self.describe()
        self.statuses.clear()
        self.versions['rustc'] = '1.63.0+dfsg1-2\nambiguous version'
        with self.assertRaisesRegex(ValueError, 'one identified version'):
            self.describe()

    def test_native_distro_changed_target_and_retargeted_link_block_all_operations(self):
        self.distro_layout()
        self.built()
        link, target = self.runtime_links[0]
        original = target.read_bytes()
        target.write_bytes(original + b'changed')
        for operation in (rust_build.build, rust_build.test, rust_build.verify):
            with self.subTest(operation=operation.__name__), patch.object(rust_build, '_run') as command:
                with self.assertRaisesRegex(ValueError, 'target library inputs changed'):
                    operation(str(self.config_path))
                command.assert_not_called()
        target.write_bytes(original)
        self.config_path.unlink()
        rust_build.save_config(self.config_path, self.describe())
        link.unlink()
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'target library inputs changed'):
            rust_build.test(str(self.config_path))

    def test_native_distro_ownership_changes_and_missing_harness_family_invalidate_inputs(self):
        self.distro_layout()
        self.configured()
        self.versions = {package: '1.63.0+dfsg1-3' for package in self.versions}
        with self.assertRaisesRegex(ValueError, 'target library inputs changed'):
            rust_build.build(str(self.config_path))
        for link, _ in self.runtime_links:
            if link.name.startswith('libtest-'):
                link.unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete native Rust distro runtime library family'):
            self.describe()
        (self.libdir / 'libtest-8bb3380c32c2be31.rlib').unlink()
        with self.assertRaisesRegex(ValueError, 'missing matched libtest'):
            self.describe()

    def test_native_distro_target_replacement_during_ownership_queries_is_rejected(self):
        self.distro_layout()
        link, target = self.runtime_links[0]
        foreign = self.root / target.name
        foreign.write_bytes(b'foreign target substituted during package query')
        def retarget(query, operation, *args):
            result = self.distro_query(query, operation, *args)
            if operation == '-S' and args[0] == str(target):
                target.unlink()
                target.symlink_to(foreign)
            return result
        with patch.object(rust_build.package_notices, 'command', side_effect=retarget):
            with self.assertRaisesRegex(ValueError, 'link or target changed while identified'):
                rust_build._distro_library_link(link, self.libdir, self.target,
                                               self.tools['rustc'], '1.63.0')

    def test_native_distro_link_text_cannot_hide_intermediate_symlink_traversal(self):
        self.distro_layout()
        link, _ = self.runtime_links[0]
        intermediate = self.libdir / 'intermediate'
        intermediate.symlink_to(self.root, target_is_directory=True)
        link.unlink()
        link.symlink_to('intermediate/../../../../x86_64-linux-gnu/' + link.name)
        with self.assertRaisesRegex(ValueError, 'invalid native Rust library link'):
            rust_build._distro_library_link(link, self.libdir, self.target,
                                           self.tools['rustc'], '1.63.0')

    def test_native_linkage_rejects_search_paths_dynamic_rust_and_unknown_flags(self):
        self.assertEqual(rust_build.parse_native_static_libs('note: native-static-libs: -lm -lm -lc\n', 'Linux'), ['m', 'c'])
        self.assertEqual(rust_build.parse_native_static_libs('note: native-static-libs: kernel32.lib libcmt.lib\n', 'Windows'),
                         ['kernel32', 'libcmt'])
        for token in ('-L/tmp/foreign', '/tmp/libforeign.a', '-lstd', '-Wl,-rpath,/foreign', '-lforeign'):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, 'unapproved Rust native'):
                rust_build.parse_native_static_libs('note: native-static-libs: ' + token + '\n', 'Linux')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            rust_build.parse_native_static_libs('native-static-libs: -lc\nnative-static-libs: -lc\n', 'Linux')

    def test_frozen_incremental_build_and_receipt_preserve_unchanged_outputs(self):
        data = self.built()
        before = {name: Path(data[name]).stat().st_mtime_ns for name in ('artifact_path', 'receipt_path')}
        self.fake_fresh = True
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            rust_build.build(str(self.config_path))
        self.assertEqual(before, {name: Path(data[name]).stat().st_mtime_ns for name in before})
        rust_build.verify(str(self.config_path))
        command, kwargs = next(row for row in self.calls if 'build' in row[0])
        self.assertIn('--frozen', command)
        self.assertEqual(command[command.index('--jobs') + 1], '1')
        self.assertIs(kwargs['compiler'], True)
        self.assertEqual(kwargs['environment']['CARGO_INCREMENTAL'], '0')

    def test_fresh_cargo_cannot_replace_a_receipt_for_a_modified_or_unbound_archive(self):
        data = self.built()
        receipt = Path(data['receipt_path']).read_bytes()
        Path(data['artifact_path']).write_bytes(b'tampered archive')
        self.fake_fresh = True
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            with self.assertRaisesRegex(ValueError, 'reused an unbound or changed Rust archive'):
                rust_build.build(str(self.config_path))
        self.assertEqual(Path(data['receipt_path']).read_bytes(), receipt)
        Path(data['receipt_path']).unlink()
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            with self.assertRaisesRegex(ValueError, 'reused an unbound or changed Rust archive'):
                rust_build.build(str(self.config_path))
        self.assertFalse(Path(data['receipt_path']).exists())

    def test_changed_source_config_cannot_rebind_an_old_fresh_artifact(self):
        data = self.built()
        previous = Path(data['receipt_path']).read_bytes()
        (self.crate / 'src/lib.rs').write_text('changed source with restored old timestamps')
        changed = self.describe()
        rust_build.save_config(self.config_path, changed)
        self.fake_fresh = True
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            with self.assertRaisesRegex(ValueError, 'reused an unbound or changed Rust archive'):
                rust_build.build(str(self.config_path))
        self.assertEqual(Path(data['receipt_path']).read_bytes(), previous)
        self.assertEqual(self.calls[-2][0][1], 'clean')
        self.assertIn('--package', self.calls[-2][0])

    def test_missing_or_modified_generated_archive_never_verifies_as_current(self):
        data = self.built()
        artifact = Path(data['artifact_path'])
        artifact.write_bytes(b'foreign archive')
        with self.assertRaisesRegex(ValueError, 'bound build receipt'):
            rust_build.verify(str(self.config_path))
        artifact.unlink()
        with self.assertRaises(FileNotFoundError):
            rust_build.verify(str(self.config_path))
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            rust_build.build(str(self.config_path))
        rust_build.verify(str(self.config_path))

    def test_sources_tools_and_target_libraries_are_rechecked_before_build(self):
        data = self.configured()
        for path, message in ((self.crate / 'src/lib.rs', 'source inputs changed'),
                              (Path(self.tools['rustc']), 'selected Rust tool changed'),
                              (self.libdir / 'libcore-identified.rlib', 'target library inputs changed')):
            original = path.read_bytes()
            path.write_bytes(original + b' changed')
            with self.subTest(path=path), patch.object(rust_build, '_run') as command:
                with self.assertRaisesRegex(ValueError, message):
                    rust_build.build(str(self.config_path))
                command.assert_not_called()
            path.write_bytes(original)
            # Exact physical input identity requires a new configuration even when bytes are restored.
            data = self.describe()
            self.config_path.unlink()
            rust_build.save_config(self.config_path, data)

    def test_new_module_requires_reconfigure_and_tool_changes_require_fresh_tree(self):
        data = self.configured()
        (self.crate / 'src/added.rs').write_text('pub fn added() {}')
        with self.assertRaisesRegex(ValueError, 'source inputs changed'):
            rust_build.build(str(self.config_path))
        changed = self.describe()
        rust_build.save_config(self.config_path, changed)
        self.assertIn(str(self.crate / 'src/added.rs'), changed['source_inputs'])
        Path(self.tools['rustc']).write_bytes(b'new compiler')
        changed = self.describe()
        with self.assertRaisesRegex(ValueError, 'fresh build tree'):
            rust_build.save_config(self.config_path, changed)

    def test_source_or_config_change_during_compilation_prevents_completion_receipt(self):
        data = self.configured()
        def changed_source(argv, **kwargs):
            raw = self.fake_run(argv, **kwargs)
            (self.crate / 'src/lib.rs').write_text('changed while compiling')
            return raw
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=changed_source):
            with self.assertRaisesRegex(ValueError, 'source inputs changed'):
                rust_build.build(str(self.config_path))
        self.assertFalse(Path(data['receipt_path']).exists())

    def test_output_symlinks_and_configuration_flag_injection_are_rejected(self):
        data = self.configured()
        changed = dict(data, flags=data['flags'] + ['-Clink-arg=-Wl,-rpath,/foreign'])
        self.config_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'uncontrolled flags'):
            rust_build.build(str(self.config_path))
        self.config_path.write_text(json.dumps(data))
        if os.name != 'nt':
            target = self.build / 'target' / self.target
            target.symlink_to(self.root)
            with self.assertRaisesRegex(ValueError, 'ordinary directory'):
                rust_build.build(str(self.config_path))

    def test_unit_harness_uses_private_outputs_and_does_not_force_abort_panics(self):
        self.configured()
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            rust_build.test(str(self.config_path))
        command, kwargs = self.calls[-1]
        self.assertIn('--frozen', command)
        self.assertIn('--lib', command)
        self.assertIn(str(self.build / 'unit-target'), command)
        self.assertNotIn('-Cpanic=abort', kwargs['environment']['CARGO_ENCODED_RUSTFLAGS'].split('\x1f'))
        self.assertNotIn('CARGO_PROFILE_DEV_PANIC', kwargs['environment'])
        self.assertIs(kwargs['compiler'], True)

    def test_unit_cache_rebind_cleans_only_private_package_after_source_changes(self):
        self.configured()
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            rust_build.test(str(self.config_path))
            first_clean = len([row for row in self.calls if 'clean' in row[0]])
            rust_build.test(str(self.config_path))
            self.assertEqual(len([row for row in self.calls if 'clean' in row[0]]), first_clean)
        (self.crate / 'src/lib.rs').write_text('changed source with old mtime')
        rust_build.save_config(self.config_path, self.describe())
        with patch.dict(os.environ, {}, clear=True), patch.object(rust_build, '_run', side_effect=self.fake_run):
            rust_build.test(str(self.config_path))
        clean = self.calls[-2][0]
        self.assertEqual(clean[1], 'clean')
        self.assertEqual(clean[clean.index('--target-dir') + 1], str(self.build / 'unit-target'))
        self.assertEqual(clean[clean.index('--package') + 1], 'foundation-text-validation')

    def test_empty_rust_unit_harness_is_not_reported_as_a_pass(self):
        self.configured()
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(rust_build, '_run', return_value='test result: ok. 0 passed; 0 failed'):
            with self.assertRaisesRegex(ValueError, 'no passing assertions'):
                rust_build.test(str(self.config_path))
        self.assertFalse((self.build / 'unit-state.json').exists())


class RustOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_windows_capture_joins_private_compiler_services_before_success(self):
        owner = Mock()
        owner.poll.return_value = 0
        owner.process.returncode = 0
        session = Mock(environment={'private': 'endpoint'})
        events = []
        session.finish.side_effect = lambda value: events.append('joined')
        owner.close.side_effect = lambda: events.append('closed')
        with patch.object(rust_build, 'os', SimpleNamespace(name='nt', fstat=os.fstat)), \
             patch.object(rust_build.windows_compiler, 'BuildSession', return_value=session), \
             patch.object(rust_build.process_tree, 'launch', return_value=owner) as launch:
            self.assertEqual(rust_build._run(['cargo', 'build'], cwd=self.root, environment={}, compiler=True), '')
        self.assertEqual(events, ['joined', 'closed'])
        self.assertEqual(launch.call_args.kwargs['env'], session.environment)
        owner.finish.assert_not_called()

    def test_failed_or_unjoined_commands_do_not_claim_completion(self):
        owner = Mock()
        owner.poll.return_value = 7
        owner.process.returncode = 7
        session = Mock(environment={})
        with patch.object(rust_build.windows_compiler, 'BuildSession', return_value=session), \
             patch.object(rust_build.process_tree, 'launch', return_value=owner):
            with self.assertRaisesRegex(ValueError, 'Rust command failed'):
                rust_build._run(['cargo', 'build'], cwd=self.root, environment={}, compiler=True)
        session.finish.assert_not_called()
        owner.finish.assert_called_once_with()
        owner.terminate.assert_called_once_with()
        owner.close.assert_called_once_with()
        owner = Mock()
        owner.poll.return_value = 0
        owner.process.returncode = 0
        owner.finish.side_effect = rust_build.process_tree.ProcessTreeError('unjoined writer')
        with patch.object(rust_build.process_tree, 'launch', return_value=owner):
            with self.assertRaisesRegex(rust_build.process_tree.ProcessTreeError, 'unjoined writer'):
                rust_build._run(['cargo'], cwd=self.root, environment={})
        owner.close.assert_called_once_with()

    def test_failed_windows_compiler_tree_is_stopped_and_joined_before_diagnostics(self):
        owner = Mock()
        owner.poll.return_value = 7
        owner.process.returncode = 7
        session = Mock(environment={'private': 'endpoint'})
        events = []
        owner.terminate.side_effect = lambda: events.append('stopped')
        owner.finish.side_effect = lambda: events.append('joined')
        owner.close.side_effect = lambda: events.append('closed')
        with patch.object(rust_build, 'os', SimpleNamespace(name='nt', fstat=os.fstat)), \
             patch.object(rust_build.windows_compiler, 'BuildSession', return_value=session), \
             patch.object(rust_build.process_tree, 'launch', return_value=owner):
            with self.assertRaisesRegex(ValueError, 'Rust command failed'):
                rust_build._run(['cargo', 'build'], cwd=self.root, environment={}, compiler=True)
        self.assertEqual(events, ['stopped', 'joined', 'closed'])
        session.finish.assert_not_called()

    def test_timeout_stops_and_closes_complete_owned_tree(self):
        owner = Mock()
        owner.poll.return_value = None
        with patch.object(rust_build.process_tree, 'launch', return_value=owner), \
             patch.object(rust_build.time, 'monotonic', side_effect=[0, 10]):
            with self.assertRaisesRegex(ValueError, 'time or output bound'):
                rust_build._run(['rustc'], cwd=self.root, environment={}, timeout=1)
        owner.terminate.assert_called_once_with()
        owner.close.assert_called_once_with()
        owner.finish.assert_not_called()


class RustUnitCMakeRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='Rust unit registration ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cmake = shutil.which('cmake')
        self.ctest = shutil.which('ctest')
        self.assertTrue(self.cmake, 'CMake is a required build prerequisite')
        self.assertTrue(self.ctest, 'CTest is a required build prerequisite')
        module = Path(__file__).resolve().parents[1] / 'cmake/RustComponent.cmake'
        text = module.read_text(encoding='utf-8')
        start = text.index('  if(BUILD_TESTING AND')
        end = text.index('  endif()', start) + len('  endif()')
        self.registration = text[start:end]

    def inventory(self, name, *, host, target, cross=True, emscripten=False, testing=True):
        source = self.root / name
        build = source / 'build'
        source.mkdir()
        script = '\n'.join((
            'cmake_minimum_required(VERSION 3.24)',
            'project(RustUnitRegistration NONE)',
            'enable_testing()',
            'function(foundation_test_prerequisites name)',
            '  if(NOT ARGN STREQUAL "foundation-rust")',
            '    message(FATAL_ERROR "Rust unit test lost its build prerequisite")',
            '  endif()',
            'endfunction()',
            'set(Python3_EXECUTABLE [==[' + Path(sys.executable).as_posix() + ']==])',
            'set(selected_config "fixture-config.json")',
            'set(BUILD_TESTING ' + ('TRUE' if testing else 'FALSE') + ')',
            'set(CMAKE_CROSSCOMPILING ' + ('TRUE' if cross else 'FALSE') + ')',
            'set(EMSCRIPTEN ' + ('TRUE' if emscripten else 'FALSE') + ')',
            'set(compiler_host "' + host + '")',
            'set(target "' + target + '")',
            self.registration,
        ))
        (source / 'CMakeLists.txt').write_text(script + '\n', encoding='utf-8')
        configured = subprocess.run([self.cmake, '-S', str(source), '-B', str(build), '-G', 'Ninja'],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
        inventory = subprocess.run([self.ctest, '--test-dir', str(build), '--show-only=json-v1'],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(inventory.returncode, 0, inventory.stdout + inventory.stderr)
        return json.loads(inventory.stdout)['tests']

    def test_matching_rust_host_registers_units_despite_cpp_sysroot_cross_flag(self):
        for target in ('x86_64-unknown-linux-gnu', 'aarch64-unknown-linux-gnu'):
            for cross in (True, False):
                with self.subTest(target=target, cpp_cross=cross):
                    tests = self.inventory(target + str(cross), host=target, target=target, cross=cross)
                    self.assertEqual([test['name'] for test in tests], ['rust.unit'])
                    properties = {value['name']: value['value'] for value in tests[0]['properties']}
                    self.assertEqual(properties['LABELS'], ['rust', 'unit'])
                    self.assertEqual(properties['RESOURCE_LOCK'], ['rust-build'])

    def test_foreign_rust_targets_omit_units_independently_of_cpp_cross_flag(self):
        for cross in (True, False):
            with self.subTest(cpp_cross=cross):
                tests = self.inventory('foreign' + str(cross), host='x86_64-unknown-linux-gnu',
                                       target='aarch64-unknown-linux-gnu', cross=cross)
                self.assertEqual(tests, [])

    def test_emscripten_and_disabled_testing_omit_units(self):
        target = 'x86_64-unknown-linux-gnu'
        self.assertEqual(self.inventory('emscripten', host=target, target=target, emscripten=True), [])
        self.assertEqual(self.inventory('disabled', host=target, target=target, testing=False), [])


if __name__ == '__main__':
    unittest.main()
