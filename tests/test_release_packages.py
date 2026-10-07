"""Pure package inventory bindings and extraction guards, without signing claims."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dependency_archive as archive
import dependency_store
import release
import release_packages as packages


class PackageBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'candidate'; self.directory.mkdir()
        self.files = {}

        def put(name, data):
            path = self.directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.files[name] = archive.digest(path)
            return {'size': len(data), 'sha256': self.files[name]}

        # Archives and signature bytes are deliberately inert: these tests cover
        # the metadata boundary, not GPG authentication or native package ABI.
        source = 'source.tar.gz'; put(source, b'fixture application source')
        artifacts, dependencies = [], []
        recipes = ['a' * 64, 'b' * 64]
        for target, recipe in zip(('linux-x86_64', 'linux-aarch64'), recipes):
            name = target + '.tar.gz'; sidecar = name + '.json'
            put(name, target.encode()); put(sidecar, b'fixture application manifest')
            artifacts.append(dict(target=target, archive=name, sha256=self.files[name],
                manifest=sidecar, manifest_sha256=self.files[sidecar], backends=[],
                sdk_recipe=recipe, dependency_recipes=recipes))
            group = {}
            for member in dependency_store.names(recipe):
                logical = 'dependencies/' + recipe + '/' + member
                put(logical, member.encode()); group[member] = self.files[logical]
            dependencies.append({'recipe_id': recipe, 'files': group})
        inputs = {Path(name).name: {'size': (self.directory / name).stat().st_size, 'sha256': digest}
                  for name, digest in self.files.items()}
        request = dict(repository='example/project', application_tag='v2', source_commit='c' * 40,
                       version='1.2.3', package_release=2, sequence=8, valid_days=30,
                       trusted_fingerprint='D' * 40)
        base = 'https://github.com/example/project/releases/download/v2/'
        ref = lambda name: {'url': base + name, 'sha256': inputs[name]['sha256']}
        apt_names = ['archive-keyring.gpg', 'InRelease', 'Release', 'Release.gpg',
                     'Packages', 'Packages.gz', 'repository.json']
        arch_names = ['software-foundation.db.tar.gz', 'software-foundation.db.tar.gz.sig']
        asset_rows = {name: put(name, ('fixture ' + name).encode())
                      for name in [*apt_names, *arch_names, 'INSTALL.md']}
        targets = {}
        closure = sorted(Path(name).name for name in self.files if name.startswith('dependencies/'))
        for entry in artifacts:
            target = entry['target']; native_name = 'native-' + target + '.tar.gz'
            native = self.root / ('native fixture ' + target); native.mkdir()
            (native / 'marker').write_text(target)
            archive.archive_tree(native, self.directory / native_name)
            self.files[native_name] = archive.digest(self.directory / native_name)
            asset_rows[native_name] = dict(size=(self.directory / native_name).stat().st_size,
                                           sha256=self.files[native_name])
            primary = dependency_store.names(entry['sdk_recipe'])[0]
            spec = dict(schema_version=packages.distro.RELEASE_TAG_SCHEMA, version='1.2.3',
                package_release=2, architecture=target.removeprefix('linux-'), backend='core',
                archive_url=base + entry['archive'], archive_sha256=entry['sha256'],
                license_files=['share/doc/Foundation/LICENSE'], redistribution_approved=True,
                application_source=ref(source), packaging_tool=ref(source), sdk=ref(primary),
                dependencies=[ref(name) for name in closure if name != primary],
                runtime_dependencies=packages.distro.runtime_policy('core'))
            targets[target] = dict(backends=['core'], specifications={'core': spec},
                native_archive=native_name, application_archive=entry['archive'],
                application_manifest=entry['manifest'],
                payloads={kind: {'core': {'files': 1, 'payload_sha256': 'e' * 64}}
                          for kind in ('apt', 'arch', 'gentoo')})
        self.document = dict(schema_version=1, request=request, policy_sha256='f' * 64,
            targets=targets, apt_files=sorted(apt_names), arch_files=sorted(arch_names),
            inputs=inputs, files=asset_rows)
        archive.write_json(self.directory / 'packages.json', self.document)
        self.files['packages.json'] = archive.digest(self.directory / 'packages.json')
        put('packages.json.sig', b'inert signature fixture')
        self.manifest = dict(schema_version=1, qualification='candidate',
            source={'archive': source, 'sha256': self.files[source], 'tree_sha256': '1' * 64},
            artifacts=artifacts, dependencies=dependencies, required_scopes=['source', 'archive', 'recovery'],
            packages={'manifest': 'packages.json', 'files': sorted(set(asset_rows) | packages.CONTROL)},
            files=dict(self.files))
        archive.write_json(self.directory / 'release.json', self.manifest)

    def test_complete_package_roles_bind_both_targets_and_every_retained_input(self):
        self.assertEqual(release.verify_metadata(self.directory), self.manifest)
        self.assertEqual(packages.binding(self.directory, self.manifest), self.document)
        self.assertEqual(set(self.document['targets']), {'linux-x86_64', 'linux-aarch64'})
        for entry in self.manifest['artifacts']:
            spec = self.document['targets'][entry['target']]['specifications']['core']
            self.assertEqual(spec['application_source']['sha256'], self.manifest['source']['sha256'])
            primary = dependency_store.names(entry['sdk_recipe'])[0]
            self.assertEqual(spec['sdk']['sha256'], self.document['inputs'][primary]['sha256'])

    def test_package_binding_rejects_changed_roles_source_dependencies_and_target(self):
        for mutation in ('role', 'control', 'source', 'dependency', 'target', 'application'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.manifest)
                if mutation == 'role':
                    changed['packages']['files'].remove('native-linux-aarch64.tar.gz')
                elif mutation == 'control': changed['files']['packages.json.sig'] = '0' * 64
                elif mutation == 'source':
                    changed['source']['sha256'] = '0' * 64
                    changed['files'][changed['source']['archive']] = '0' * 64
                elif mutation == 'dependency':
                    group = changed['dependencies'][0]; member = next(iter(group['files']))
                    group['files'][member] = '0' * 64
                    changed['files']['dependencies/' + group['recipe_id'] + '/' + member] = '0' * 64
                elif mutation == 'target': changed['artifacts'][1]['target'] = 'windows-x86_64'
                else:
                    left, right = changed['artifacts']
                    for field in ('archive', 'sha256', 'manifest', 'manifest_sha256'):
                        left[field], right[field] = right[field], left[field]
                with self.assertRaises(ValueError):
                    packages.binding(self.directory, changed)

    def test_document_rejects_partial_targets_backends_payload_anchors_and_overlaps(self):
        for mutation in ('target', 'backend', 'payload', 'apt-control', 'input-overlap'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.document)
                item = changed['targets']['linux-aarch64']
                if mutation == 'target': del changed['targets']['linux-aarch64']
                elif mutation == 'backend': item['backends'].append('terminal')
                elif mutation == 'payload': del item['payloads']['gentoo']['core']
                elif mutation == 'apt-control': changed['apt_files'].remove('Packages.gz')
                else: changed['files']['source.tar.gz'] = changed['inputs']['source.tar.gz']
                archive.write_json(self.directory / 'packages.json', changed)
                with self.assertRaises(ValueError):
                    packages.binding(self.directory, self.manifest)

    def test_selected_extraction_preserves_target_and_rejects_changed_asset_bytes(self):
        output = self.root / 'ARM restored'
        packages.extract_channels(self.directory, output, 'linux-aarch64')
        self.assertEqual((output / 'native/marker').read_text(), 'linux-aarch64')
        self.assertEqual({p.name for p in (output / 'apt').iterdir()}, set(self.document['apt_files']))
        unsupported = self.root / 'unsupported'
        with self.assertRaisesRegex(ValueError, 'selected package extraction'):
            packages.extract_channels(self.directory, unsupported, 'windows-x86_64')
        self.assertFalse(unsupported.exists())
        for name in ('Packages', 'native-linux-aarch64.tar.gz'):
            with self.subTest(asset=name):
                path = self.directory / name; original = path.read_bytes()
                path.write_bytes(original + b'substitution')
                rejected = self.root / ('rejected ' + name)
                with self.assertRaisesRegex(ValueError, 'input changed before extraction'):
                    packages.extract_channels(self.directory, rejected, 'linux-aarch64')
                self.assertFalse((rejected / 'native').exists())
                path.write_bytes(original)


if __name__ == '__main__': unittest.main()
