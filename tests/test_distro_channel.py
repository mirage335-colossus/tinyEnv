"""Packaging contracts and actual signature/atomic activation failure fixtures."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('distro_channel', Path(__file__).resolve().parents[1] / 'tools/distro_channel.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def unresolved_lock(path, *args, **kwargs):
    if Path(path).name=='gui-boundary.lock.json':
        return b'{"license":"NOASSERTION","redistribution":{"approved":false}}',0o644
    return ORIGINAL_ORDINARY(path,*args,**kwargs)


ORIGINAL_ORDINARY=d.ordinary


def source_group(root, version='1.0.0', release=1, backends=(), backend='core', schema=1, offline=False):
    root.mkdir()
    archive = root / 'application.tar.gz'
    data = {
        'prefix/bin/foundation-cli': (b'#!/bin/sh\nprintf "' + version.encode() + b'\\n"\n', 0o755),
        'prefix/share/doc/Foundation/LICENSE': (b'Fixture redistribution terms\n', 0o644),
        'prefix/lib/private-data.txt': (b'Preserved companion data\n', 0o644),
        'prefix/share/man/man1/foundation-cli.1': (b'.TH FOUNDATION-CLI 1\n', 0o644),
        'prefix/share/man/man7/software-foundation.7': (b'.TH SOFTWARE-FOUNDATION 7\n', 0o644),
    }
    for item in backends:
        name = 'foundation-gui-' + ('web' if item == 'hosted-web' else item)
        data['prefix/bin/' + name] = (b'#!/bin/sh\nexit 0\n', 0o755)
    if backends:
        data.update({'prefix/lib/runtime/private.so': (b'fixture shared runtime\n', 0o755),
                     'prefix/lib/cmake/Foundation/FoundationConfig.cmake': (b'# fixture SDK export\n', 0o644),
                     'prefix/share/software-foundation/web/serve.py': (b'# fixture shared resource\n', 0o644)})
    if 'hosted-web' in backends:
        data.update({'prefix/share/software-foundation/web/' + name: (b'# fixture asset\n', 0o644)
                     for name in ('host.py', 'index.html', 'boot.mjs', 'renderer.mjs', 'style.css',
                                  'browser_lifecycle.mjs', 'wasm_transport.mjs', 'browser_presenter.mjs',
                                  'file_services.mjs', 'wasm_worker.mjs')})
    if backends and schema >= 3:
        gui = 'prefix/share/doc/Foundation/gui-boundary/'
        terms = b'Fixture GUI terms\n'
        data[gui + 'LICENSE'] = (terms, 0o644)
        data[gui + 'gui-boundary.lock.json'] = (d.encoded({'redistribution': {'approved': True, 'license_files': ['LICENSE']},
            'files': {'LICENSE': d.digest(terms)}}), 0o644)
        data['prefix/share/doc/Foundation/dependency-notices/index.json'] = (d.encoded({'schema_version': 1, 'providers': [], 'files': {}}), 0o644)
    if offline:
        data.update({'prefix/share/software-foundation/' + ('wasm/' if not name.startswith('open-') else '') + name:
                     (b'offline fixture ' + name.encode(), 0o755 if name.endswith('.sh') else 0o644)
                     for name in ('software-foundation-wasm.html', 'web-manifest.json', 'manifest.sha256',
                                  'open-offline.sh', 'open-offline.cmd')})
    archive.write_bytes(d.tar_bytes(data))
    manifest = root / 'archive.json'
    manifest.write_bytes(d.encoded(d.artifact.describe(archive)))
    identity = d.digest(archive.read_bytes())
    reference = lambda char: {'url': 'https://example.invalid/sha256/' + char * 64 + '/group.tar.gz', 'sha256': char * 64}
    specification = {
        'schema_version': schema, 'version': version, 'package_release': release,
        'architecture': 'x86_64', 'backend': backend,
        'archive_url': 'https://example.invalid/sha256/' + identity + '/application.tar.gz',
        'archive_sha256': identity, 'license_files': ['share/doc/Foundation/LICENSE'],
        'redistribution_approved': True, 'application_source': reference('a'), 'sdk': reference('b'),
        'packaging_tool': reference('c'),
        'dependencies': [], 'runtime_dependencies': d.runtime_policy(backend) if schema >= 3 else {'arch': ['glibc>=2.36'], 'gentoo': ['>=sys-libs/glibc-2.36']},
    }
    if schema >= 3:
        specification['license_files'] = d.required_license_files({p.removeprefix('prefix/'): v for p,v in data.items()})
    spec_path = root / 'spec.json'
    spec_path.write_bytes(d.encoded(specification))
    group = root / 'group'
    d.package(archive, manifest, spec_path, group)
    return group


class CapacityTests(unittest.TestCase):
    def test_channel_growth_preserves_complete_aggregate_boundary(self):
        class SizedPayload:
            def __init__(self, size): self.size = size
            def __len__(self): return self.size

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name in ('a', 'b'): (root / name).write_bytes(b'fixture')
            # Model retained package sizes without allocating hundreds of MiB.
            first = SizedPayload(208957183)
            second = SizedPayload(320 * 1024 * 1024 - len(first))
            with patch.object(d, 'ordinary', side_effect=[(first, 0o644), (second, 0o644)]):
                self.assertEqual(set(d.tree(root)), {'a', 'b'})
            second.size += 1
            with patch.object(d, 'ordinary', side_effect=[(first, 0o644), (second, 0o644)]), \
                    self.assertRaisesRegex(ValueError, 'bounded example size'):
                d.tree(root)

    def test_oversized_individual_channel_file_fails_before_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'oversized'
            with path.open('wb') as stream: stream.truncate(320 * 1024 * 1024 + 1)
            with patch.object(d.os, 'open', side_effect=AssertionError('oversized input was opened')), \
                    self.assertRaisesRegex(ValueError, 'bounded singly linked regular file'):
                d.ordinary(path)


class RecipeTests(unittest.TestCase):
    def test_historical_recipe_inventories_remain_byte_identical(self):
        expected = {
            1: 'e352499fc2964a14546b6a22db432378b8c4730999622792e882ef7571a5d16d',
            2: '3ed74ffbb3a93e6e93833adb8ee6f68fb61b533bd0a46f7be8223a85fbba61b0',
            3: 'ed88f35210be2e9e0c4acae680629cd43ca9caa82678c5f0a3ecbf9dddadd076',
            4: 'b8629dcbd0025917d77ebdee59d16f871e7cfd82f12671cd8a339f281f2d0dd9',
        }
        with tempfile.TemporaryDirectory() as temporary:
            for schema, digest in expected.items():
                with self.subTest(schema=schema):
                    group = source_group(Path(temporary)/str(schema), schema=schema)
                    self.assertEqual(d.digest(d.encoded(d.inventory(d.tree(group)))), digest)

    def test_offline_launchers_preserve_payload_and_historical_recipe_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            group = source_group(Path(temporary)/'offline', schema=d.CURRENT_SCHEMA, offline=True)
            generated, _ = d.expected_package(d.tree(group))
            archive = next(v[0] for n,v in generated.items() if n.endswith('.pkg.tar.gz'))
            with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as bundle:
                contents = {p.name:bundle.extractfile(p).read() for p in bundle if p.isfile()}
            self.assertIn('usr/bin/foundation-gui-offline-core', contents)
            self.assertIn(b'/opt/software-foundation/core/share/software-foundation/open-offline.sh',
                          contents['usr/bin/foundation-gui-offline-core'])
            self.assertEqual(contents['opt/software-foundation/core/share/software-foundation/wasm/software-foundation-wasm.html'],
                             b'offline fixture software-foundation-wasm.html')
            for path in ('recipes/arch/software-foundation-core-bin/PKGBUILD',
                         'gentoo/app-misc/software-foundation-core-bin/software-foundation-core-bin-1.0.0.ebuild'):
                self.assertIn(b'foundation-gui-offline-core', generated[path][0])
            old_spec = dict(d.document((group/'spec.json').read_bytes()), schema_version=5)
            archive_name = 'application.tar.gz'
            original = group/'retained'/archive_name
            root_name, payload = d.archive_payload(original, d.document((group/'portable-manifest.json').read_bytes()))
            old_spec.update(archive_size=original.stat().st_size, archive_sha512=d.hashlib.sha512(original.read_bytes()).hexdigest())
            old = d.recipe_files(old_spec, root_name, payload, archive_name)
            self.assertFalse(any('/foundation-gui-offline-' in path for path in old))

    def test_current_gentoo_prepare_honors_eapi_phase_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for schema in (3, d.CURRENT_SCHEMA):
                group = source_group(root/str(schema), schema=schema)
                ebuild = next(group.glob('gentoo/app-misc/*/*.ebuild'))
                # EAPI >= 6 requires the user-patch hook even for binary recipes.
                # Model the manager's post-phase invariant, not just phase exit0.
                script = 'eapply_user() { called=yes; }; source "$1"; src_prepare; test "${called:-no}" = yes'
                result = subprocess.run(['bash','-euc',script,'phase',str(ebuild)],
                    env=dict(os.environ,WORKDIR=str(root)), capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0 if schema == d.CURRENT_SCHEMA else 1)
                if schema == d.CURRENT_SCHEMA:
                    original = root/str(schema)/'application.tar.gz'
                    prefix, complete = d.archive_payload(original, d.document((group/'portable-manifest.json').read_bytes()))
                    generated, _ = d.expected_package(d.tree(group))
                    archive = next(v[0] for n,v in generated.items() if n.endswith('.pkg.tar.gz'))
                    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as bundle:
                        installed = {entry.name:(bundle.extractfile(entry).read(),entry.mode)
                            for entry in bundle if entry.isfile() and not entry.name.startswith('.')}
                    self.execute_recipes(root/'execute-current',group,complete,installed,'core')


    def test_current_desktop_and_browser_files_match_both_executable_recipes(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(d, 'require_gui_terms'):
            root = Path(temporary)
            for backend in ('terminal', 'fltk', 'rev', 'sdl', 'hosted-web', 'framebuffer'):
                with self.subTest(backend=backend):
                    group = source_group(root/backend, backends=(backend,), backend=backend, schema=d.CURRENT_SCHEMA)
                    original = root/backend/'application.tar.gz'
                    _, complete = d.archive_payload(original, d.document((group/'portable-manifest.json').read_bytes()))
                    generated, _ = d.expected_package(d.tree(group))
                    archive = next(v[0] for n,v in generated.items() if n.endswith('.pkg.tar.gz'))
                    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
                        installed = {e.name: (bundle.extractfile(e).read(), e.mode)
                                     for e in bundle if e.isfile() and not e.name.startswith('.')}
                    expected = 'usr/share/applications/software-foundation-' + backend + '.desktop'
                    self.assertEqual(expected in installed, backend != 'framebuffer')
                    self.assertEqual('usr/bin/foundation-gui-browser' in installed, backend == 'hosted-web')
                    self.execute_recipes(root/('execute-' + backend), group, complete, installed, backend)
                    old_spec = dict(d.document((group/'spec.json').read_bytes()), schema_version=4)
                    old = d.recipe_files(dict(old_spec, archive_size=original.stat().st_size,
                        archive_sha512=d.hashlib.sha512(original.read_bytes()).hexdigest()), 'prefix', complete, original.name)
                    self.assertFalse(any(path.endswith('.desktop') or path.endswith('/foundation-gui-browser') for path in old))

    def test_current_recipes_require_complete_authenticated_notice_inventory(self):
        gui='share/doc/Foundation/gui-boundary/';deps='share/doc/Foundation/dependency-notices/'
        terms=b'Supplier terms\n';runtime=b'Runtime terms\n'
        lock={'redistribution':{'approved':True,'license_files':['LICENSE']},'files':{'LICENSE':d.digest(terms)}}
        index={'schema_version':1,'providers':[],'files':{'runtime.txt':{'sha256':d.digest(runtime),'size':len(runtime)}}}
        payload={'bin/foundation-cli':(b'cli',0o755),'share/doc/Foundation/LICENSE':(b'Project terms',0o644),
                 gui+'gui-boundary.lock.json':(d.encoded(lock),0o644),gui+'LICENSE':(terms,0o644),
                 deps+'index.json':(d.encoded(index),0o644),deps+'runtime.txt':(runtime,0o644)}
        expected=set(payload)-{'bin/foundation-cli'}
        self.assertEqual(expected,set(d.required_license_files(payload)))
        spec={'schema_version':3,'backend':'core','architecture':'x86_64','archive_sha256':'a'*64,
              'license_files':['share/doc/Foundation/LICENSE']}
        with self.assertRaisesRegex(ValueError,'omits required'):d.recipe_files(spec,'prefix',payload,'archive.tar.gz')
        for missing in expected:
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                d.required_license_files({k:v for k,v in payload.items() if k!=missing})
        for changed in (gui+'LICENSE',deps+'runtime.txt'):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                d.required_license_files(dict(payload,**{changed:(b'changed',0o644)}))
        with self.assertRaisesRegex(ValueError,'omits installed'):
            d.required_license_files(dict(payload,**{deps+'unindexed.txt':(b'unlisted',0o644)}))
        for bad in ('../escape','/absolute','index.json'):
            altered=copy.deepcopy(index);altered['files']={bad:next(iter(index['files'].values()))}
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                d.required_license_files(dict(payload,**{deps+'index.json':(d.encoded(altered),0o644)}))
        lock['redistribution']['approved']=False
        with self.assertRaisesRegex(ValueError,'redistribution'):
            d.required_license_files(dict(payload,**{gui+'gui-boundary.lock.json':(d.encoded(lock),0o644)}))

    def test_combined_archive_projects_every_backend_and_executes_matching_recipes(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(d, 'require_gui_terms'):
            # Fixture approval is scoped here; the real public gate is tested below.
            root = Path(temporary)
            initial = source_group(root / 'input', backends=sorted(d.BACKENDS - {'core'}), schema=2)
            original = root / 'input/application.tar.gz'
            before = original.read_bytes()
            manifest = d.document((initial / 'portable-manifest.json').read_bytes())
            prefix, complete = d.archive_payload(original, manifest)
            specification = d.document((initial / 'spec.json').read_bytes())
            all_launchers = set()
            for backend in sorted(d.BACKENDS):
                with self.subTest(backend=backend):
                    spec_path = root / (backend + '.json')
                    spec_path.write_bytes(d.encoded(dict(specification, backend=backend)))
                    group = root / backend
                    d.package(original, root / 'input/archive.json', spec_path, group)
                    files = d.tree(group)
                    self.assertEqual(files, d.expected_package(files)[0])
                    self.assertEqual((group / 'retained/application.tar.gz').read_bytes(), before)
                    receipt = d.document(files['backend-selection.json'][0])
                    selected = {'bin/foundation-cli'}
                    if backend != 'core':
                        selected.add('bin/foundation-gui-' + ('web' if backend == 'hosted-web' else backend))
                    self.assertEqual(set(receipt['selected_executables']), selected)
                    excluded = {path for path in complete if path.startswith('bin/')} - selected
                    self.assertEqual(receipt['excluded_executables'], d.inventory({path: complete[path] for path in excluded}))
                    self.assertEqual(receipt['archive_sha256'], d.digest(before))
                    self.assertEqual(receipt['source_file_inventory_sha256'], d.digest(d.encoded(d.inventory(complete))))
                    native = next(value[0] for name, value in files.items() if name.endswith('.pkg.tar.gz'))
                    with tarfile.open(fileobj=io.BytesIO(native), mode='r:gz') as bundle:
                        installed = {entry.name: (bundle.extractfile(entry).read(), entry.mode)
                                     for entry in bundle if entry.isfile() and not entry.name.startswith('.')}
                    private = 'opt/software-foundation/' + backend + '/'
                    private_files = {path.removeprefix(private): value for path, value in installed.items() if path.startswith(private)}
                    self.assertEqual(set(path for path in private_files if path.startswith('bin/')), selected)
                    for path, value in complete.items():
                        if not path.startswith('bin/'):
                            self.assertEqual(private_files[path], value)
                    self.assertEqual(private_files[d.SELECTION_PATH], files['backend-selection.json'])
                    launchers = {path for path in installed if path.startswith('usr/bin/')}
                    self.assertFalse(all_launchers & launchers)
                    all_launchers.update(launchers)
                    self.execute_recipes(root / ('execute-' + backend), group, complete, installed, backend)
            self.assertEqual(original.read_bytes(), before)

    def execute_recipes(self, root, group, complete, installed, backend):
        """Run generated install bodies; fixtures model manager helpers, not managers."""
        root.mkdir()
        source = root / 'source'
        source.mkdir()
        d.write_files(source, {'prefix/' + path: value for path, value in complete.items()})
        recipe = group / ('recipes/arch/software-foundation-' + backend + '-bin')
        for path in recipe.iterdir():
            if path.name not in ('PKGBUILD', '.SRCINFO'):
                shutil.copy2(path, source / path.name)
        arch = root / 'arch'
        subprocess.run(['bash', '-euc', 'source "$1"; package', 'recipe', str(recipe / 'PKGBUILD')],
                       env=dict(os.environ, srcdir=str(source), pkgdir=str(arch)), check=True,
                       capture_output=True, timeout=20)
        self.assertEqual(d.tree(arch), installed)
        gentoo = root / 'gentoo'
        gentoo.mkdir()
        ebuild = next(group.glob('gentoo/app-misc/*/*.ebuild'))
        functions = '''
die() { exit 1; }
eapply_user() { :; }
docompress() { test "$1" = -x; }
insinto() { target="$D/$1"; install -d "$target"; }
doins() { test "$1" = -r; cp -a "$2" "$target/"; find "$target" -type f -exec chmod 0644 {} +; }
newins() { install -m644 "$1" "$target/$2"; }
fperms() { chmod "$1" "$D/$2"; }
dobin() { install -Dm755 "$1" "$D/usr/bin/$(basename "$1")"; }
source "$1"
src_prepare
src_configure
src_compile
src_install
'''
        subprocess.run(['bash', '-euc', functions, 'recipe', str(ebuild)],
                       env=dict(os.environ, D=str(gentoo), WORKDIR=str(source), FILESDIR=str(ebuild.parent / 'files')),
                       check=True, capture_output=True, timeout=20)
        self.assertEqual(d.tree(gentoo), {path: value for path, value in installed.items()
                                       if path.startswith(('opt/', 'usr/bin/', 'usr/share/man/', 'usr/share/applications/'))})

    def test_combined_projection_rejects_unknown_missing_bad_mode_and_receipt_collision(self):
        base = {'bin/foundation-cli': (b'cli', 0o755), 'bin/foundation-gui-fltk': (b'gui', 0o755),
                'bin/foundation-gui-terminal': (b'terminal', 0o755)}
        specification = {'schema_version': 2, 'backend': 'fltk', 'archive_sha256': 'a' * 64}
        invalid = [dict(base, **{'bin/unreviewed': (b'unknown', 0o755)}),
                   dict(base, **{'bin/helpers/run': (b'unknown', 0o755)}),
                   {key: value for key, value in base.items() if key != 'bin/foundation-gui-fltk'},
                   dict(base, **{'bin/foundation-gui-terminal': (b'terminal', 0o644)}),
                   dict(base, **{d.SELECTION_PATH: (b'prior receipt', 0o644)}),
                   dict(base, **{'share/doc/foundation/LICENSE': (b'aliased ancestor', 0o644)}),
                   dict(base, **{'share/doc/Foundation': (b'blocked ancestor', 0o644)})]
        for payload in invalid:
            with self.subTest(files=list(payload)), self.assertRaises(ValueError):
                d.select_payload(specification, 'prefix', payload)

    def test_schema_one_rejects_combined_archive_and_core_projection_keeps_terms_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'public executable'):
                source_group(root / 'old', backends=['fltk'])
            with patch.object(d,'ordinary',side_effect=unresolved_lock),self.assertRaisesRegex(ValueError,'GUI dependency'):
                source_group(root / 'new', backends=['fltk'], schema=2)
            self.assertFalse((root / 'new/group').exists())

    def test_complete_binary_wrapping_and_no_implicit_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            group = source_group(root / 'input')
            files = d.tree(group)
            expected, metadata = d.expected_package(files)
            self.assertEqual(files, expected)
            native = next(value[0] for name, value in files.items() if name.endswith('.pkg.tar.gz'))
            with tarfile.open(fileobj=io.BytesIO(native), mode='r:gz') as archive:
                names = set(archive.getnames())
                self.assertIn('.PKGINFO', names)
                self.assertIn('.MTREE', names)
                mtree = gzip.decompress(archive.extractfile('.MTREE').read())
                self.assertIn(b'./opt/software-foundation/core type=dir', mtree)
                self.assertNotIn('.INSTALL', names)
                self.assertIn('opt/software-foundation/core/bin/foundation-cli', names)
                launcher = archive.extractfile('usr/bin/foundation-cli').read()
                self.assertIn(b'/opt/software-foundation/core/bin/foundation-cli', launcher)
            ebuild = next(value[0] for name, value in files.items() if name.endswith('.ebuild'))
            self.assertIn(b'src_compile() { :; }', ebuild)
            self.assertIn(metadata['archive_sha256'].encode(), ebuild)
            self.assertNotIn(b'emerge ', ebuild)
            self.assertTrue(any(name.endswith('/Manifest') for name in files))
            self.assertTrue(any(name.endswith('/.SRCINFO') for name in files))
            for name in files:
                if name.endswith(('/PKGBUILD', '.ebuild')):
                    d.run('bash', '-n', group / name)
            srcinfo = next(value[0] for name, value in files.items() if name.endswith('/.SRCINFO'))
            self.assertIn(b'options = !strip', srcinfo)
            with self.assertRaises(ValueError):
                d.package(root / 'input/application.tar.gz', root / 'input/archive.json', root / 'input/spec.json', group)

    def test_current_runtime_policy_rejects_missing_host_services_and_unsafe_use_atoms(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_group(Path(temporary)/'input')
            spec=json.loads((Path(temporary)/'input/spec.json').read_text())
            spec.update(schema_version=3,backend='hosted-web')
            with patch.object(d,'require_gui_terms'):
                with self.assertRaisesRegex(ValueError,'runtime dependencies'):d.validate_spec(spec)
                spec['runtime_dependencies']=d.runtime_policy('hosted-web');d.validate_spec(spec)
                spec.update(backend='fltk',runtime_dependencies=d.runtime_policy('fltk'));d.validate_spec(spec)
                for manager,package in (('arch','fontconfig'),('arch','ttf-dejavu'),
                                        ('gentoo','media-libs/fontconfig'),('gentoo','media-fonts/dejavu')):
                    spec['runtime_dependencies']=d.runtime_policy('fltk')
                    spec['runtime_dependencies'][manager].remove(package)
                    with self.assertRaisesRegex(ValueError,'runtime dependencies'):d.validate_spec(spec)
                spec.update(backend='rev',runtime_dependencies=d.runtime_policy('rev'));d.validate_spec(spec)
                for atom in ('media-libs/mesa[X,$(false)]','media-libs/mesa[X,opengl]\nother','media-libs/mesa[X, opengl]'):
                    spec['runtime_dependencies']['gentoo']=['>=sys-libs/glibc-2.36',atom]
                    with self.assertRaises(ValueError):d.validate_spec(spec)

    def test_specs_reject_moving_urls_unknown_fields_and_injection(self):
        with tempfile.TemporaryDirectory() as temporary:
            group = source_group(Path(temporary) / 'input')
            original = d.document((group / 'spec.json').read_bytes())
            for change in ({'archive_url': 'https://example.invalid/latest/application.tar.gz'},
                           {'version': '1.0.0;false'}, {'package_release': True},
                           {'schema_version': True}, {'redistribution_approved': False},
                           {'runtime_dependencies': {'arch': ['$(false)'], 'gentoo': ['sys-libs/glibc']}},
                           {'hidden_hook': 'install'}, {'license_files': ['../LICENSE']}):
                with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                    d.validate_spec(dict(original, **change))
            with patch.object(d,'ordinary',side_effect=unresolved_lock),self.assertRaisesRegex(ValueError,'GUI'):
                d.validate_spec(dict(original, backend='fltk'))

    def test_archive_traversal_links_duplicates_and_case_conflicts(self):
        for bad in ('../out', '/absolute', 'a//b', 'a/../b', 'CON', 'trailing.', 'a\nb', 'a/./b'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                d.safe_name(bad)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'good').write_text('one')
            (root / 'GOOD').write_text('two')
            (root / 'good').chmod(0o644)
            (root / 'GOOD').chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                d.tree(root)
            (root / 'GOOD').unlink()
            (root / 'link').symlink_to(root / 'good')
            with self.assertRaises(ValueError):
                d.tree(root)
            (root / 'link').unlink()
            (root / 'empty').mkdir()
            (root / 'empty').chmod(0o755)
            with self.assertRaisesRegex(ValueError, 'directory inventory'):
                d.tree(root)
            (root / 'empty').rmdir()
            os.link(root / 'good', root / 'alias')
            with self.assertRaises(ValueError):
                d.tree(root)

    def test_noncanonical_archive_path_and_failed_staging_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'unsafe.tar.gz'
            with tarfile.open(archive, 'w:gz') as bundle:
                info = tarfile.TarInfo('prefix/./bin/foundation-cli')
                info.mode, info.size = 0o755, 1
                bundle.addfile(info, io.BytesIO(b'a'))
            with self.assertRaises(ValueError):
                d.archive_payload(archive, d.artifact.describe(archive))
            output = root / 'published'
            with patch.object(d, 'write_files', side_effect=OSError('staging failed')):
                with self.assertRaises(OSError):
                    d.publish_new(output, {'one': (b'1', 0o644)})
            self.assertFalse(output.exists())

    def test_backend_launchers_and_private_payloads_do_not_collide(self):
        with tempfile.TemporaryDirectory() as temporary:
            group = source_group(Path(temporary) / 'input')
            files = d.tree(group)
            specification = d.document(files['spec.json'][0])
            archive = group / 'retained/application.tar.gz'
            root, payload = d.archive_payload(archive, d.document(files['portable-manifest.json'][0]))
            public = set()
            for backend in sorted(d.BACKENDS - {'core'}):
                gui = 'foundation-gui-' + ('web' if backend == 'hosted-web' else backend)
                content = dict(payload, **{'bin/' + gui: (b'#!/bin/sh\nexit 0\n', 0o755)})
                augmented = dict(specification, backend=backend, archive_size=archive.stat().st_size,
                                 archive_sha512='a' * 128)
                recipes = d.recipe_files(augmented, root, content, archive.name)
                native = next(value[0] for name, value in recipes.items() if name.endswith('.pkg.tar.gz'))
                with tarfile.open(fileobj=io.BytesIO(native), mode='r:gz') as bundle:
                    launchers = {name for name in bundle.getnames() if name.startswith('usr/bin/')}
                    self.assertFalse(public & launchers)
                    public.update(launchers)
                    self.assertIn('usr/bin/foundation-cli-' + backend, launchers)
                    self.assertIn('opt/software-foundation/' + backend + '/bin/' + gui, bundle.getnames())


@unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgv') and os.name == 'posix',
                     'actual signing tools and qualified POSIX activation required')
class SignedChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='foundation channel tests ')
        cls.root = Path(cls.temporary.name)
        home = cls.root / 'keyhome'
        home.mkdir(mode=0o700)
        try:
            d.run('gpg', '--batch', '--homedir', home, '--pinentry-mode', 'loopback', '--passphrase', '',
                  '--quick-generate-key', 'Fixture <fixture@example.invalid>', 'ed25519', 'sign', '1d')
            public = cls.root / 'public.gpg'
            public.write_bytes(d.run('gpg', '--batch', '--homedir', home, '--export'))
            cls.trusted = d.apt.fingerprint(public)
            cls.private = cls.root / 'private.asc'
            cls.private.write_bytes(d.run('gpg', '--batch', '--homedir', home, '--armor', '--export-secret-keys', cls.trusted))
        finally:
            d.run('gpgconf', '--homedir', home, '--kill', 'all')
        cls.first = source_group(cls.root / 'input-a', '1.0.0')
        cls.second = source_group(cls.root / 'input-b', '1.1.0')
        cls.one, cls.two = cls.root / 'one', cls.root / 'two'
        d.assemble([cls.first], cls.one, cls.private, cls.trusted, 1)
        d.assemble([cls.second], cls.two, cls.private, cls.trusted, 2)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def resign(self, files):
        files = copy.deepcopy(files)
        metadata = d.document(files['channel.json'][0])
        metadata['files'] = d.inventory({name: row for name, row in files.items() if name not in d.CONTROL})
        files['channel.json'] = (d.encoded(metadata), 0o644)
        with d.signing(self.private, self.trusted) as (_, sign):
            files['channel.json.sig'] = (sign(files['channel.json'][0]), 0o644)
        return files

    def test_actual_signature_and_a_to_b_atomic_idempotent_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            location = Path(temporary) / 'channel'
            first = d.sync(self.one, location, self.trusted)
            self.assertTrue(first['changed'])
            before = os.readlink(location / 'current')
            self.assertFalse(d.sync(self.one, location, self.trusted)['changed'])
            second = d.sync(self.two, location, self.trusted)
            self.assertTrue(second['changed'])
            self.assertNotEqual(os.readlink(location / 'current'), before)
            self.assertTrue((location / before / 'channel.json').is_file())
            self.assertEqual(d.verify(location / second['current'], self.trusted)['sequence'], 2)
            self.assertFalse(d.sync(self.two, location, self.trusted)['changed'])
            with self.assertRaisesRegex(ValueError, 'rollback'):
                d.sync(self.one, location, self.trusted)
        files = d.tree(self.one)
        with tarfile.open(fileobj=io.BytesIO(files['arch/software-foundation.files'][0]), mode='r:gz') as bundle:
            listings = [member for member in bundle if member.name.endswith('/files')]
            self.assertEqual(len(listings), 1)
            self.assertIn(b'usr/bin/foundation-cli\n', bundle.extractfile(listings[0]).read())

    def test_combined_archive_channel_binds_backend_selection_and_rejects_receipt_tampering(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(d, 'require_gui_terms'):
            root = Path(temporary)
            terminal = source_group(root / 'input', backends=['fltk', 'terminal'], backend='terminal', schema=2)
            specification = d.document((terminal / 'spec.json').read_bytes())
            other_spec = root / 'fltk.json'
            other_spec.write_bytes(d.encoded(dict(specification, backend='fltk')))
            fltk = root / 'fltk'
            d.package(root / 'input/application.tar.gz', root / 'input/archive.json', other_spec, fltk)
            channel = root / 'channel'
            d.assemble([terminal, fltk], channel, self.private, self.trusted, 1)
            self.assertEqual(set(d.verify(channel, self.trusted)['packages']), {'x86_64-terminal', 'x86_64-fltk'})
            location = root / 'accepted'
            self.assertTrue(d.sync(channel, location, self.trusted)['changed'])
            changed = d.tree(channel)
            receipt_path = next(path for path in changed if path.endswith('/backend-selection.json'))
            receipt = d.document(changed[receipt_path][0])
            receipt['excluded_executables'].clear()
            changed[receipt_path] = (d.encoded(receipt), 0o644)
            with self.assertRaises(ValueError):
                d.verify_files(self.resign(changed), self.trusted)

    def test_same_sequence_and_package_downgrade_rejected(self):
        old, new = d.verify(self.one, self.trusted), d.verify(self.two, self.trusted)
        changed = copy.deepcopy(new)
        changed['sequence'] = old['sequence']
        with self.assertRaisesRegex(ValueError, 'same-sequence'):
            d.advance(old, changed)
        downgraded = copy.deepcopy(old)
        downgraded['sequence'] = new['sequence'] + 1
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            d.advance(new, downgraded)
        missing = copy.deepcopy(new)
        missing['packages'].clear()
        with self.assertRaisesRegex(ValueError, 'removal'):
            d.advance(old, missing)
        replaced = copy.deepcopy(old)
        replaced['sequence'] += 1
        replaced['packages']['x86_64-core']['archive_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'same-version'):
            d.advance(old, replaced)

    def test_tamper_incomplete_import_untrusted_key_and_signed_hooks(self):
        files = d.tree(self.one)
        for path in ('channel.json', 'arch/software-foundation.db', 'gentoo/profiles/repo_name'):
            changed = copy.deepcopy(files)
            changed[path] = (changed[path][0] + b'changed', 0o644)
            with self.subTest(path=path), self.assertRaises((ValueError, subprocess.SubprocessError)):
                d.verify_files(changed, self.trusted)
        missing = copy.deepcopy(files)
        missing.pop('gentoo/metadata/layout.conf')
        with self.assertRaises(ValueError):
            d.verify_files(self.resign(missing), self.trusted)
        hooked = copy.deepcopy(files)
        path = next(name for name in hooked if name.endswith('.ebuild') and name.startswith('gentoo/'))
        hooked[path] = (hooked[path][0] + b'pkg_postinst() { false; }\n', 0o644)
        with self.assertRaisesRegex(ValueError, 'overlay'):
            d.verify_files(self.resign(hooked), self.trusted)
        with self.assertRaisesRegex(ValueError, 'untrusted'):
            d.verify_files(files, 'A' * 40)
        unexpected = copy.deepcopy(files)
        unexpected['gentoo/.hidden-hook'] = (b'never execute\n', 0o644)
        with self.assertRaisesRegex(ValueError, 'unexpected hooks'):
            d.verify_files(self.resign(unexpected), self.trusted)

    def test_expired_and_duplicate_metadata(self):
        files = d.tree(self.one)
        metadata = d.document(files['channel.json'][0])
        past = datetime.now(timezone.utc) - timedelta(days=4)
        metadata.update(created=past.isoformat(), expires=(past + timedelta(days=1)).isoformat())
        files['channel.json'] = (d.encoded(metadata), 0o644)
        with self.assertRaisesRegex(ValueError, 'expired'):
            d.verify_files(self.resign(files), self.trusted)
        with self.assertRaises(ValueError):
            d.document(b'{"key":1,"key":2}')

    def test_failed_activation_preserves_previous_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            location = Path(temporary) / 'channel'
            d.sync(self.one, location, self.trusted)
            original = os.readlink(location / 'current')
            with patch.object(d.os, 'replace', side_effect=OSError('injected before activation')):
                with self.assertRaises(OSError):
                    d.sync(self.two, location, self.trusted)
            self.assertEqual(os.readlink(location / 'current'), original)
            self.assertEqual(d.verify(location / original, self.trusted)['sequence'], 1)
            foreign = location / original / 'foreign.txt'
            foreign.write_text('Keep this file')
            with self.assertRaises(ValueError):
                d.sync(self.two, location, self.trusted)
            self.assertEqual(foreign.read_text(), 'Keep this file')
            self.assertEqual(os.readlink(location / 'current'), original)

    def test_unmanaged_and_unsafe_destinations_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / 'channel'
            location.mkdir()
            (location / 'foreign').write_text('keep')
            with self.assertRaises(ValueError):
                d.sync(self.one, location, self.trusted)
            self.assertEqual((location / 'foreign').read_text(), 'keep')
            link = root / 'linked'
            link.symlink_to(location, target_is_directory=True)
            with self.assertRaises(ValueError):
                d.sync(self.one, link, self.trusted)

    def test_post_activation_failure_is_explicit_and_preserves_both_generations(self):
        with tempfile.TemporaryDirectory() as temporary:
            location = Path(temporary) / 'channel'
            d.sync(self.one, location, self.trusted)
            original = os.readlink(location / 'current')
            real_sync = d.sync_directory
            def fail_after_activation(path):
                if Path(path) == location and os.readlink(location / 'current') != original:
                    raise OSError('final acknowledgment unavailable')
                real_sync(path)
            with patch.object(d, 'sync_directory', side_effect=fail_after_activation):
                with self.assertRaises(d.CommitUncertain):
                    d.sync(self.two, location, self.trusted)
            self.assertNotEqual(os.readlink(location / 'current'), original)
            self.assertEqual(d.verify(location / os.readlink(location / 'current'), self.trusted)['sequence'], 2)
            self.assertEqual(d.verify(location / original, self.trusted)['sequence'], 1)
            self.assertFalse(d.sync(self.two, location, self.trusted)['changed'])

    def test_lock_alias_and_signed_symlink_input_do_not_replace_active_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / 'channel'
            d.sync(self.one, location, self.trusted)
            original = os.readlink(location / 'current')
            os.link(location / '.sync.lock', root / 'alias')
            with self.assertRaisesRegex(ValueError, 'aliases'):
                d.sync(self.two, location, self.trusted)
            (root / 'alias').unlink()
            source = root / 'source'
            shutil.copytree(self.two, source)
            data = source / 'gentoo/profiles/repo_name'
            data.unlink()
            data.symlink_to(self.two / 'gentoo/profiles/repo_name')
            with self.assertRaisesRegex(ValueError, 'linked'):
                d.sync(source, location, self.trusted)
            self.assertEqual(os.readlink(location / 'current'), original)


if __name__ == '__main__':
    unittest.main()
