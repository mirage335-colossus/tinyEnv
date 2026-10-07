from pathlib import Path
import copy
import shutil
import json
import subprocess
from unittest.mock import patch
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import artifact
from dependency_archive import archive_tree, digest, read_json, write_json
from dependency_store import put
import release
from test_sdk import fixture
from source_identity import archive_source


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recipe, _, _, group = fixture(self.root)
        self.base = self.root / 'base'
        put(self.base, group, self.recipe)
        source = self.root / 'application-source.tar.gz'
        source_manifest = archive_source(self.root / 'sources', source)
        tree = self.root / 'application'
        (tree / 'bin').mkdir(parents=True)
        (tree / 'bin/foundation-cli').write_text('inert archive fixture')
        (tree / 'build-info.txt').write_text('sdk_recipe_id=' + self.recipe + '\nsource_tree_sha256=' + source_manifest['tree_sha256'] + '\ntarget=linux-x86_64\ngui_backends=\ndependency_recipes=' + self.recipe + '\n')
        archive = self.root / 'application.tar.gz'
        archive_tree(tree, archive)
        manifest = self.root / 'application.tar.gz.json'
        write_json(manifest, artifact.describe(archive))
        self.spec = {'schema_version': 1, 'source': {'path': str(source), 'sha256': digest(source)},
          'artifacts': [{'path': str(archive), 'manifest_path': str(manifest), 'sha256': digest(archive),
                         'target': 'linux-x86_64', 'backends': [], 'sdk_recipe': self.recipe}],
          'required_scopes': ['core', 'installed-consumer', 'abi', 'offline-recovery']}
        self.spec_path = self.root / 'spec.json'
        write_json(self.spec_path, self.spec)

    def tearDown(self): self.temp.cleanup()

    def release_with_packages(self):
        output = self.root / 'release with packages'
        metadata = release.assemble(self.spec_path, self.base, output)
        # These inert bytes exercise the complete release hash inventory. The
        # package builder separately validates its manifest and signatures.
        package_assets = {
            'packages.json': b'{"format":"release-packages"}\n',
            'packages.json.sig': b'inert signature fixture',
            'archive-keyring.gpg': b'inert keyring fixture',
            'INSTALL.md': b'fixture installation instructions',
            'foundation-linux-x86_64-native.tar.gz': b'inert native bundle fixture',
        }
        for name, content in package_assets.items():
            (output / name).write_bytes(content)
            metadata['files'][name] = digest(output / name)
        metadata['packages'] = {'manifest': 'packages.json', 'files': sorted(package_assets)}
        write_json(output / 'release.json', metadata)
        return output, metadata

    def test_optional_package_assets_are_bound_to_the_complete_release_inventory(self):
        output, metadata = self.release_with_packages()
        self.assertEqual(release.verify_metadata(output)['packages'], metadata['packages'])
        release.verify_inventory(output, metadata['files'], exclude=('release.json',))
        # Metadata-only reconciliation keeps the frozen hash; physical acceptance
        # must reject substituted package bytes even when applications are intact.
        (output / 'foundation-linux-x86_64-native.tar.gz').write_bytes(b'substituted bundle')
        self.assertEqual(release.verify_metadata(output), metadata)
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            release.verify_release(output)

    def test_package_declaration_requires_every_signing_and_installation_control(self):
        output, metadata = self.release_with_packages()
        for name in ('packages.json', 'packages.json.sig', 'archive-keyring.gpg', 'INSTALL.md'):
            with self.subTest(control=name):
                changed = copy.deepcopy(metadata)
                changed['packages']['files'].remove(name)
                del changed['files'][name]
                write_json(output / 'release.json', changed)
                with self.assertRaisesRegex(ValueError, 'package assets'):
                    release.verify_metadata(output)

    def test_package_assets_cannot_duplicate_overlap_or_invent_release_files(self):
        output, metadata = self.release_with_packages()
        for kind in ('duplicate', 'application-overlap', 'absent', 'nonflat', 'wrong-manifest'):
            with self.subTest(kind=kind):
                changed = copy.deepcopy(metadata)
                names = changed['packages']['files']
                if kind == 'duplicate':
                    names.append(names[0]); names.sort()
                elif kind == 'application-overlap':
                    names.append(changed['artifacts'][0]['archive']); names.sort()
                elif kind == 'absent':
                    names.append('unretained-native.tar.gz'); names.sort()
                elif kind == 'nonflat':
                    names.append('nested/native.tar.gz'); names.sort()
                    changed['files']['nested/native.tar.gz'] = 'a' * 64
                else:
                    changed['packages']['manifest'] = 'other.json'
                write_json(output / 'release.json', changed)
                with self.assertRaises(ValueError):
                    release.verify_metadata(output)

    def test_explicit_null_packages_cannot_disguise_a_legacy_package_free_inventory(self):
        output = self.root / 'legacy release'
        metadata = release.assemble(self.spec_path, self.base, output)
        self.assertNotIn('packages', release.verify_metadata(output))
        metadata['packages'] = None
        write_json(output / 'release.json', metadata)
        with self.assertRaisesRegex(ValueError, 'package asset declaration'):
            release.verify_metadata(output)

    def test_package_validation_reads_archive_once_without_full_extraction(self):
        from unittest.mock import patch
        entry = self.spec['artifacts'][0]
        source = read_json(Path(entry['manifest_path']))
        source_identity = archive_source(self.root / 'sources', self.root / 'test-source.tar.gz')['tree_sha256']
        with patch.object(artifact, 'inspect_archive', wraps=artifact.inspect_archive) as inspect:
            release.validate_package(Path(entry['path']), entry, source_identity, source)
            self.assertEqual(inspect.call_count, 1)
            self.assertIsNone(inspect.call_args.args[1])
            self.assertEqual(list(inspect.call_args.kwargs['contents']), ['build-info.txt'])

    def test_selected_inventory_is_hashed_once_and_still_rejects_changes(self):
        from unittest.mock import patch
        output = self.root / 'release'; release.assemble(self.spec_path, self.base, output)
        with patch.object(release, 'file_inventory', wraps=release.file_inventory) as inventory:
            release.verify_selection(output, 'linux-x86_64', 'core', 'archive')
            self.assertEqual(inventory.call_count, 1)
        (output / 'application.tar.gz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            release.verify_selection(output, 'linux-x86_64', 'core', 'archive')

    def test_release_owns_exact_groups_and_recovers_without_base(self):
        output = self.root / 'release'
        release.assemble(self.spec_path, self.base, output)
        shutil.rmtree(self.base)
        metadata = release.verify_release(output)
        release.recover(output, self.root / 'restored')
        self.assertEqual(metadata['dependencies'][0]['recipe_id'], self.recipe)
        self.assertTrue((self.root / 'restored/dependencies' / self.recipe).is_dir())
        self.assertEqual(metadata['qualification'], 'candidate')

    def recovery_kit(self):
        original = self.root / 'release'
        metadata = release.assemble(self.spec_path, self.base, original)
        expected = digest(original / 'release.json')
        kit = self.root / 'recovery kit'
        self.assertEqual(metadata, release.recover(original, kit))
        self.assertEqual((original / 'release.json').read_bytes(), (kit / 'release.json').read_bytes())
        return original, kit, metadata, expected

    def test_recovery_is_independent_of_release_base_and_original_sources(self):
        original, kit, metadata, expected = self.recovery_kit()
        # Leave only the kit: no application binaries, base, compiler checkout or
        # source working tree may supply hidden recovery dependencies.
        for path in self.root.iterdir():
            if path == kit:
                continue
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
        result = release.verify_recovery(kit, expected)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['scope'], 'retained-recovery-inputs')
        self.assertTrue(result['release_pin_verified'])
        self.assertEqual(result['artifacts'], metadata['artifacts'])
        self.assertFalse((kit / metadata['artifacts'][0]['archive']).exists())
        self.assertFalse(release.verify_recovery(kit)['release_pin_verified'])
        command = [sys.executable, '-B', str(Path(release.__file__)), 'verify-recovery',
                   str(kit), '--expected-release-sha256', expected]
        checked = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout), result)
        import sdk
        sdk.install(kit / 'dependencies' / self.recipe, self.recipe,
                    self.root / 'restored SDK', production=False)
        sdk.restore_sources(kit / 'dependencies' / self.recipe, self.recipe,
                            self.root / 'restored SDK sources')
        self.assertTrue((self.root / 'restored SDK/sdk.json').is_file())
        self.assertTrue((self.root / 'restored SDK sources/sources.json').is_file())

    def test_recovery_trust_pin_checks_actual_retained_metadata(self):
        _, kit, _, expected = self.recovery_kit()
        for bad in ('0' * 64, 'not-a-digest', ''):
            with self.subTest(pin=bad), self.assertRaises(ValueError):
                release.verify_recovery(kit, bad)
        # Rewriting both local manifests cannot bypass the independently supplied
        # release identity, even when the altered metadata is internally valid.
        data = read_json(kit / 'release.json')
        data['artifacts'][0]['target'] = 'forged-target'
        write_json(kit / 'release.json', data)
        with self.assertRaisesRegex(ValueError, 'metadata is missing or changed'):
            release.verify_recovery(kit)
        receipt = read_json(kit / 'recovery.json')
        receipt['release_sha256'] = digest(kit / 'release.json')
        write_json(kit / 'recovery.json', receipt)
        with self.assertRaisesRegex(ValueError, 'trusted release identity'):
            release.verify_recovery(kit, expected)
        self.assertFalse(release.verify_recovery(kit)['release_pin_verified'])

    def test_recovery_requires_exact_source_dependency_and_file_inventory(self):
        _, kit, data, expected = self.recovery_kit()
        source = data['source']['archive']
        member = next(iter(data['dependencies'][0]['files']))
        dependency = Path('dependencies') / self.recipe / member
        def replace_source(root):
            other = self.root / 'other source'; other.mkdir(exist_ok=True)
            (other / 'different.cpp').write_text('valid but unrelated source')
            (root / source).unlink()
            archive_source(other, root / source)
        mutations = {
            'missing-source': lambda root: (root / source).unlink(),
            'valid-wrong-source': replace_source,
            'missing-dependency-member': lambda root: (root / dependency).unlink(),
            'corrupt-dependency': lambda root: (root / dependency).write_bytes(b'changed'),
            'extra-file': lambda root: (root / 'unlisted').write_text('extra'),
            'extra-directory': lambda root: (root / 'unlisted').mkdir(),
            'renamed-group': lambda root: (root / 'dependencies' / self.recipe).rename(root / 'dependencies' / ('b' * 64)),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                copy = self.root / name; shutil.copytree(kit, copy); mutate(copy)
                with self.assertRaises((ValueError, OSError)):
                    release.verify_recovery(copy, expected)

    def test_recovery_rejects_changed_receipt_and_legacy_provenance(self):
        _, kit, _, expected = self.recovery_kit()
        original = read_json(kit / 'recovery.json')
        for change in ({'schema_version': 2}, {'schema_version': True},
                       {'release_sha256': 'bad'}, {'source': {}}, {'dependencies': []}):
            with self.subTest(change=change):
                write_json(kit / 'recovery.json', dict(original, **change))
                with self.assertRaises(ValueError): release.verify_recovery(kit, expected)
        legacy = dict(original); del legacy['schema_version']
        write_json(kit / 'recovery.json', legacy)
        with self.assertRaisesRegex(ValueError, 'legacy.*re-export'):
            release.verify_recovery(kit, expected)
        (kit / 'recovery.json').write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            release.verify_recovery(kit)

    def test_recovery_validates_inner_source_and_complete_recipe_relationships(self):
        _, kit, data, _ = self.recovery_kit()
        for name in ('tree-identity', 'duplicate-recipe', 'required-second-recipe'):
            with self.subTest(mutation=name):
                copy = self.root / name; shutil.copytree(kit, copy)
                metadata = read_json(copy / 'release.json')
                if name == 'tree-identity': metadata['source']['tree_sha256'] = '0' * 64
                elif name == 'duplicate-recipe': metadata['dependencies'].append(metadata['dependencies'][0])
                else: metadata['artifacts'][0]['dependency_recipes'].append('b' * 64)
                write_json(copy / 'release.json', metadata)
                receipt = read_json(copy / 'recovery.json')
                receipt.update(release_sha256=digest(copy / 'release.json'),
                               source=metadata['source'], dependencies=metadata['dependencies'])
                write_json(copy / 'recovery.json', receipt)
                with self.assertRaises(ValueError): release.verify_recovery(copy)

    def test_recovery_preserves_existing_destinations_and_original_release(self):
        original, _, _, _ = self.recovery_kit()
        for name, is_directory in (('existing-file', False), ('existing-directory', True)):
            output = self.root / name
            if is_directory:
                output.mkdir(); marker = output / 'keep'
            else: marker = output
            marker.write_text('preserve')
            with self.assertRaisesRegex(ValueError, 'must be new'):
                release.recover(original, output)
            self.assertEqual(marker.read_text(), 'preserve')
        with self.assertRaisesRegex(ValueError, 'outside the release tree'):
            release.recover(original, original / 'nested-kit')
        release.verify_release(original)

    def test_recovery_copy_mutation_never_publishes_partial_kit(self):
        original = self.root / 'release'; release.assemble(self.spec_path, self.base, original)
        for member in ('application-source.tar.gz', 'release.json'):
            with self.subTest(member=member):
                output = self.root / ('failed-' + member)
                copy = shutil.copyfile
                def corrupt(source, destination, *args, **kwargs):
                    result = copy(source, destination, *args, **kwargs)
                    if Path(source).resolve() == (original / member).resolve():
                        Path(destination).write_bytes(b'corrupted while copying')
                    return result
                with patch.object(release.shutil, 'copyfile', side_effect=corrupt):
                    with self.assertRaises(ValueError): release.recover(original, output)
                self.assertFalse(output.exists())
                release.verify_release(original)

    def test_missing_base_fails_without_partial_release(self):
        shutil.rmtree(self.base)
        with self.assertRaisesRegex(ValueError, 'missing'):
            release.assemble(self.spec_path, self.base, self.root / 'release')
        self.assertFalse((self.root / 'release').exists())

    def test_wrong_sdk_in_package_fails(self):
        self.spec['artifacts'][0]['sdk_recipe'] = 'b' * 64
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'packaged SDK'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_frozen_source_digest_required(self):
        self.spec['source']['sha256'] = '0' * 64
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'source archive differs'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_changed_retained_asset_invalidates_release(self):
        output = self.root / 'release'
        release.assemble(self.spec_path, self.base, output)
        (output / 'application.tar.gz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            release.verify_release(output)

    def test_added_untracked_asset_invalidates_release(self):
        output = self.root / 'release'
        release.assemble(self.spec_path, self.base, output)
        (output / 'extra').write_text('unlisted')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            release.verify_release(output)

    def test_declared_target_cannot_relabel_package(self):
        self.spec['artifacts'][0]['target'] = 'linux-aarch64'
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'packaged target'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_declared_backend_cannot_relabel_package(self):
        self.spec['artifacts'][0]['backends'] = ['terminal']
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'packaged backends'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_unrelated_source_archive_cannot_substitute(self):
        (self.root / 'sources/other.cpp').write_text('different source')
        replacement = self.root / 'replacement-source.tar.gz'
        archive_source(self.root / 'sources', replacement)
        self.spec['source'] = {'path': str(replacement), 'sha256': digest(replacement)}
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'packaged source tree'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_unbound_dependency_cannot_be_omitted(self):
        self.spec['artifacts'][0]['dependency_recipes'] = [self.recipe, 'b' * 64]
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'packaged dependency list'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_duplicate_required_scope_rejected(self):
        self.spec['required_scopes'] = ['core', 'core']
        write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'unique'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def repack_provider(self, **identity):
        tree = self.root / 'application'
        info = dict(line.split('=', 1) for line in (tree / 'build-info.txt').read_text().splitlines())
        info.update(identity)
        (tree / 'build-info.txt').write_text(''.join(key + '=' + value + '\n' for key, value in info.items()))
        archive = Path(self.spec['artifacts'][0]['path']); archive.unlink()
        archive_tree(tree, archive)
        self.spec['artifacts'][0]['sha256'] = digest(archive)
        write_json(Path(self.spec['artifacts'][0]['manifest_path']), artifact.describe(archive))
        write_json(self.spec_path, self.spec)

    def rust_identity(self):
        return {'core_provider': 'rust', 'rust_sdk_recipe_id': 'b' * 64,
                'rust_compiler_version': '1.63.0', 'rust_target': 'x86_64-unknown-linux-gnu',
                'rust_sdk_manifest_sha256': 'c' * 64, 'rust_compiler_sha256': 'd' * 64}

    def test_omitted_provider_retains_historical_cpp_identity(self):
        self.assertEqual(release.provider_identity(self.spec['artifacts'][0]), {'core_provider': 'cpp'})
        rust_fields_without_provider = self.rust_identity()
        del rust_fields_without_provider['core_provider']
        with self.assertRaisesRegex(ValueError, r'C\+\+ artifact'):
            release.provider_identity(rust_fields_without_provider)

    def test_rust_package_cannot_lose_provider_identity_in_cpp_manifest(self):
        self.repack_provider(**self.rust_identity())
        with self.assertRaisesRegex(ValueError, 'core provider or Rust toolchain'):
            release.assemble(self.spec_path, self.base, self.root / 'release')

    def test_rust_artifact_requires_complete_distinct_retained_sdk(self):
        identity = self.rust_identity()
        entry = dict(self.spec['artifacts'][0], **identity)
        with self.assertRaisesRegex(ValueError, 'distinct Rust SDK'):
            release.dependency_recipes(entry)
        entry['dependency_recipes'] = [self.recipe, identity['rust_sdk_recipe_id']]
        self.assertEqual(release.dependency_kinds([entry]), {self.recipe: 'sdk', 'b' * 64: 'rust'})
        for key in release.RUST_IDENTITY_FIELDS:
            broken = dict(entry); del broken[key]
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'complete compiler'):
                release.provider_identity(broken)

    def test_same_target_two_provider_outputs_are_rejected(self):
        output = self.root / 'release'; release.assemble(self.spec_path, self.base, output)
        data = read_json(output / 'release.json')
        data['artifacts'].append(dict(data['artifacts'][0], core_provider='cpp'))
        write_json(output / 'release.json', data)
        with self.assertRaisesRegex(ValueError, 'duplicate release target'):
            release.verify_release(output)

    def test_rust_identity_cannot_be_relabelled_or_attached_to_cpp(self):
        identity = self.rust_identity()
        entry = dict(self.spec['artifacts'][0], dependency_recipes=[self.recipe, 'b' * 64], **identity)
        self.spec['artifacts'][0] = entry
        self.repack_provider(dependency_recipes=self.recipe + ',' + 'b' * 64, **identity)
        entry['rust_target'] = 'aarch64-unknown-linux-gnu'; write_json(self.spec_path, self.spec)
        with self.assertRaisesRegex(ValueError, 'core provider or Rust toolchain'):
            release.assemble(self.spec_path, self.base, self.root / 'release')
        with self.assertRaisesRegex(ValueError, r'C\+\+ artifact'):
            release.provider_identity(dict(identity, core_provider='cpp'))

    def test_actual_rust_group_is_retained_recovered_and_rejects_missing_sources(self):
        from test_rust_sdk import RustSdkTests
        import rust_sdk
        fixture = RustSdkTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        tree, sources, rust = fixture.sdk()
        recipe = rust['recipe_id']
        group = self.root / 'rust-group'; rust_sdk.export_group(tree, sources, group)
        release.copy_dependency_group(group, self.base / recipe, recipe, 'rust')
        identity = {'core_provider': 'rust', 'rust_sdk_recipe_id': recipe,
                    'rust_compiler_version': rust['compiler']['version'], 'rust_target': rust['target']['triple'],
                    'rust_sdk_manifest_sha256': digest(tree / 'rust-sdk.json'),
                    'rust_compiler_sha256': digest(tree / rust['compiler']['rustc'])}
        self.spec['artifacts'][0].update(identity, dependency_recipes=[self.recipe, recipe])
        self.repack_provider(dependency_recipes=self.recipe + ',' + recipe, **identity)
        original, kit, metadata, expected = self.recovery_kit()
        rust_group = next(item for item in metadata['dependencies'] if item['recipe_id'] == recipe)
        self.assertEqual(rust_group['kind'], 'rust')
        self.assertEqual(release.verify_selection(original, 'linux-x86_64', 'core', 'source'), metadata)
        shutil.rmtree(original); shutil.rmtree(self.base); fixture.doCleanups()
        self.assertEqual(release.verify_recovery(kit, expected)['artifacts'][0]['core_provider'], 'rust')
        (kit / 'dependencies' / recipe / rust_sdk.group_names(recipe)[1]).unlink()
        with self.assertRaises(ValueError): release.verify_recovery(kit, expected)


if __name__ == '__main__': unittest.main()
