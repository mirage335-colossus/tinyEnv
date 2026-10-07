#!/usr/bin/env python3
"""Rust extension boundaries and complete retained recovery inputs."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from dependency_archive import digest, encoded, file_inventory, read_json, write_json
import rust_sdk


class RustSdkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.work = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def sources(self):
        sources = self.work / 'sources'
        sources.mkdir()
        data = read_json(ROOT / 'third_party/rust/linux-x86_64.json')
        (sources / 'inputs').mkdir()
        for item in data['inputs']:
            path = sources / 'inputs' / item['file']
            path.write_bytes(('supplier ' + item['name']).encode())
            item['sha256'] = digest(path)
        write_json(sources / 'recipe/rust.json', data)
        for name in rust_sdk.TOOLS:
            path = sources / 'tools' / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('retained ' + name)
        stage0 = {'compiler': data['bootstrap'], 'checksums_sha256': {
            'dist/' + data['bootstrap']['date'] + '/' + item['file']: item['sha256']
            for item in data['inputs'] if item['name'].startswith('stage0-')}}
        write_json(sources / 'bootstrap/stage0.json', stage0)
        files = file_inventory(sources)
        recipe_files = {'recipe/rust.json': files['recipe/rust.json']}
        recipe_files.update({'tools/' + name: files['tools/' + name] for name in rust_sdk.TOOLS})
        identity = hashlib.sha256(encoded(recipe_files)).hexdigest()
        write_json(sources / 'sources.json', {'schema_version': 1, 'recipe_id': identity,
                   'files': files, 'recovery_scope': rust_sdk.RECOVERY_SCOPE,
                   'bootstrap_reconstructed': False})
        return sources, identity

    def sdk(self):
        sources, identity = self.sources()
        tree = self.work / 'sdk'
        paths = {'bin/rustc': b'compiler', 'bin/cargo': b'cargo', 'notices/LICENSE': b'license'}
        library = 'lib/rustlib/x86_64-unknown-linux-gnu/lib'
        for crate in ('core', 'std', 'compiler_builtins'):
            paths[library + '/lib' + crate + '-1234abcd.rlib'] = crate.encode()
        for name, contents in paths.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        data = {'schema_version': 1, 'kind': 'rust-extension', 'recipe_id': identity,
                'sources_sha256': digest(sources / 'sources.json'),
                'compiler': {'rustc': 'bin/rustc', 'cargo': 'bin/cargo', 'sysroot': '.',
                             'version': '1.63.0', 'cargo_version': '1.63.0',
                             'host': 'x86_64-unknown-linux-gnu'},
                'host': {'system': 'Linux', 'processor': 'x86_64'},
                'target': {'system': 'Linux', 'processor': 'x86_64',
                           'triple': 'x86_64-unknown-linux-gnu', 'library_directory': library},
                'licenses': ['notices/LICENSE'], 'recovery_scope': rust_sdk.RECOVERY_SCOPE,
                'files': file_inventory(tree)}
        write_json(tree / 'rust-sdk.json', data)
        return tree, sources, data

    def test_inventory_missing_extra_changed_and_linked_files(self):
        tree, _, data = self.sdk()
        self.assertEqual(rust_sdk.verify_rust_sdk(tree), data)
        path = tree / 'bin/rustc'
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            rust_sdk.verify_rust_sdk(tree)
        path.write_bytes(b'compiler')
        extra = tree / 'ambient'
        extra.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            rust_sdk.verify_rust_sdk(tree)
        extra.unlink()
        if hasattr(Path, 'symlink_to'):
            try:
                extra.symlink_to(path)
            except OSError:
                return
            with self.assertRaisesRegex(ValueError, 'unsupported retained entry'):
                rust_sdk.verify_rust_sdk(tree)

    def test_metadata_cannot_select_external_compiler(self):
        tree, _, data = self.sdk()
        data['compiler']['rustc'] = '../rustc'
        write_json(tree / 'rust-sdk.json', data)
        with self.assertRaisesRegex(ValueError, 'relative path'):
            rust_sdk.verify_rust_sdk(tree)

    def test_target_and_required_support_crates(self):
        tree, _, data = self.sdk()
        with self.assertRaisesRegex(ValueError, 'selected Rust target'):
            rust_sdk.verify_rust_sdk(tree, target='wasm32-unknown-emscripten')
        name = next(name for name in data['files'] if '/libcore-' in name)
        (tree / name).unlink()
        data['files'] = file_inventory(tree, exclude=('rust-sdk.json',))
        write_json(tree / 'rust-sdk.json', data)
        with self.assertRaisesRegex(ValueError, 'target crate: core'):
            rust_sdk.verify_rust_sdk(tree)

    def test_native_host_and_foreign_execution_rejected(self):
        tree, _, data = self.sdk()
        with patch('rust_sdk.platform.system', return_value='Windows'):
            with self.assertRaisesRegex(ValueError, 'native host'):
                rust_sdk.verify_rust_sdk(tree, execute=True)
        data['compiler']['host'] = 'x86_64-pc-windows-msvc'
        data['host']['system'] = 'Windows'
        write_json(tree / 'rust-sdk.json', data)
        with self.assertRaisesRegex(ValueError, 'host differs from target'):
            rust_sdk.verify_rust_sdk(tree)

    def test_linux_windows_and_emscripten_pairing(self):
        _, _, data = self.sdk()
        cpp = {'recipe_id': 'a' * 64, 'kind': 'source-build', 'host': data['host'],
               'target': {'system': 'Linux', 'processor': 'x86_64', 'triple': 'x86_64-buildroot-linux-gnu'}}
        rust_sdk.verify_pair(data, cpp)
        cpp['target']['processor'] = 'aarch64'
        with self.assertRaisesRegex(ValueError, 'target differs'):
            rust_sdk.verify_pair(data, cpp)
        windows = copy.deepcopy(data)
        windows['host']['system'] = 'Windows'
        windows['target'].update(system='Windows', triple='x86_64-pc-windows-msvc')
        cpp = {'recipe_id': 'a' * 64, 'kind': 'windows-dependencies',
               'external_toolchain': {'toolset': 'v143'},
               'target': {'system': 'Windows', 'processor': 'x86_64', 'triple': 'x64-windows-static'}}
        rust_sdk.verify_pair(windows, cpp)
        cpp['external_toolchain']['toolset'] = 'v142'
        with self.assertRaisesRegex(ValueError, 'Windows MSVC'):
            rust_sdk.verify_pair(windows, cpp)
        wasm = copy.deepcopy(data)
        wasm['target'].update(system='Emscripten', processor='wasm32', triple='wasm32-unknown-emscripten',
                              cpp_sdk_recipe_id='a' * 64)
        cpp = {'recipe_id': 'b' * 64, 'host': data['host'],
               'target': {'system': 'Emscripten', 'processor': 'wasm32', 'triple': 'wasm32-emscripten'}}
        with self.assertRaisesRegex(ValueError, 'different paired'):
            rust_sdk.verify_pair(wasm, cpp)

    def test_offline_fetch_never_acquires_inputs(self):
        with patch('rust_sdk.urllib.request.urlopen', side_effect=AssertionError('network attempted')):
            with self.assertRaisesRegex(ValueError, 'explicit fetch required'):
                rust_sdk.fetch(ROOT / 'third_party/rust/linux-x86_64.json', self.work / 'empty')

    def test_all_pinned_recipes_and_declared_archive_tuple(self):
        for recipe in sorted((ROOT / 'third_party/rust').glob('*.json')):
            data = rust_sdk.checked_recipe(recipe)
            self.assertEqual(len(rust_sdk.recipe_identity(recipe)), 64)
            data['version'] = '1.64.0'
            with self.assertRaisesRegex(ValueError, 'component tuple'):
                rust_sdk.check_recipe_data(data)

    def test_duplicate_supplier_filename_rejected(self):
        data = read_json(ROOT / 'third_party/rust/linux-x86_64.json')
        data['inputs'][1]['file'] = data['inputs'][0]['file']
        with self.assertRaisesRegex(ValueError, 'duplicate Rust supplier filename'):
            rust_sdk.check_recipe_data(data)

    def test_sources_require_actual_binary_bootstrap_inputs(self):
        sources, _ = self.sources()
        rust_sdk.verify_sources(sources)
        data = read_json(sources / 'sources.json')
        path = next(name for name in data['files'] if 'rustc-1.62.0-' in name)
        (sources / path).unlink()
        data['files'] = file_inventory(sources, exclude=('sources.json',))
        write_json(sources / 'sources.json', data)
        with self.assertRaisesRegex(ValueError, 'pinned supplier input'):
            rust_sdk.verify_sources(sources)

    def test_source_recipe_helper_binding_and_bootstrap_tuple(self):
        sources, _ = self.sources()
        path = sources / 'tools/rust_sdk.py'
        path.write_text('changed helper')
        data = read_json(sources / 'sources.json')
        data['files'] = file_inventory(sources, exclude=('sources.json',))
        write_json(sources / 'sources.json', data)
        with self.assertRaisesRegex(ValueError, 'recipe/helper identity differs'):
            rust_sdk.verify_sources(sources)
        recipe = read_json(sources / 'recipe/rust.json')
        stage0 = read_json(sources / 'bootstrap/stage0.json')
        stage0['compiler']['version'] = '1.61.0'
        with self.assertRaisesRegex(ValueError, 'bootstrap tuple'):
            rust_sdk.verify_stage0(recipe, stage0)

    def test_group_restore_sources_and_relocation(self):
        tree, sources, data = self.sdk()
        group = self.work / 'group'
        result = rust_sdk.export_group(tree, sources, group)
        self.assertEqual(result['files'], rust_sdk.verify_group(group, data['recipe_id']))
        restored = self.work / 'relocated'
        rust_sdk.restore(group, data['recipe_id'], restored)
        self.assertEqual(rust_sdk.verify_rust_sdk(restored), data)
        source_root = self.work / 'restored-sources'
        rust_sdk.restore_sources(group, data['recipe_id'], source_root)
        self.assertEqual(rust_sdk.verify_sources(source_root), read_json(sources / 'sources.json'))
        with self.assertRaisesRegex(ValueError, 'must be new'):
            rust_sdk.restore(group, data['recipe_id'], restored)

    def test_group_rejects_extra_and_corrupt_archives(self):
        tree, sources, data = self.sdk()
        group = self.work / 'group'
        rust_sdk.export_group(tree, sources, group)
        extra = group / 'extra'
        extra.write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'triplet'):
            rust_sdk.verify_group(group, data['recipe_id'])
        extra.unlink()
        binary = group / rust_sdk.names(data['recipe_id'])[0]
        binary.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            rust_sdk.verify_group(group, data['recipe_id'])

    def test_malformed_metadata_fails_closed(self):
        for value in ([], {}, {'schema_version': 1, 'kind': 'rust-extension', 'compiler': 'bad'}):
            with self.assertRaises(ValueError):
                rust_sdk.check_extension_data(value)


if __name__ == '__main__':
    unittest.main()
