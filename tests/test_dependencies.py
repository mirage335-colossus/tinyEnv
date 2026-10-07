import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from dependency_archive import extract, file_inventory, read_json
from dependency_store import copy_group, fetch, names, put, verify_group
from test_sdk import fixture


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recipe, self.tree, _, self.group = fixture(self.root)

    def tearDown(self): self.temp.cleanup()

    def retained_archive(self, name, entries, policy='linux-case-sensitive-v1', host='Linux', target='Linux'):
        import hashlib
        from dependency_archive import encoded
        archive = self.root/name
        files = {name: hashlib.sha256(data).hexdigest() for name, data, kind in entries if kind == tarfile.REGTYPE}
        metadata = {'schema_version':1,'recipe_id':self.recipe,'files':files,
                    'host':{'system':host},'target':{'system':target},'path_policy':policy,
                    'sources_sha256':read_json(self.tree/'sdk.json')['sources_sha256']}
        with tarfile.open(archive, 'w') as stream:
            for filename, data, kind in entries:
                info = tarfile.TarInfo(filename); info.type=kind; info.size=len(data); info.linkname='outside'
                stream.addfile(info, io.BytesIO(data))
            data = encoded(metadata); info=tarfile.TarInfo('sdk.json'); info.size=len(data)
            stream.addfile(info, io.BytesIO(data))
        return archive

    def test_sdk_archive_selects_exact_bounded_manifest_before_case_validation(self):
        from dependency_archive import LINUX_SDK_PATHS, inspect_manifest_archive
        archive = self.retained_archive('paired.tar', [('include/Header.h',b'upper',tarfile.REGTYPE),
                                                       ('include/header.h',b'lower',tarfile.REGTYPE)])
        metadata, _ = inspect_manifest_archive(archive, 'sdk.json', sdk_archive=True)
        self.assertEqual(metadata['path_policy'], LINUX_SDK_PATHS)
        self.assertEqual(len(metadata['files']), 2)
        with self.assertRaisesRegex(ValueError, 'case-insensitive'):
            inspect_manifest_archive(archive, 'sdk.json')
        with self.assertRaisesRegex(ValueError, 'binary SDK manifest'):
            inspect_manifest_archive(archive, 'sources.json', sdk_archive=True)

    def test_sdk_archive_rejects_unknown_nonlinux_or_missing_case_policy(self):
        from dependency_archive import inspect_manifest_archive
        for index, (policy, host, target) in enumerate((('unknown','Linux','Linux'),
            ('linux-case-sensitive-v1','Windows','Linux'), ('linux-case-sensitive-v1','Linux','Windows'),
            ('linux-case-sensitive-v1','Linux','Emscripten'), ('portable','Linux','Linux'))):
            archive = self.retained_archive('policy'+str(index)+'.tar', [('Header.h',b'A',tarfile.REGTYPE),
                ('header.h',b'B',tarfile.REGTYPE)], policy, host, target)
            with self.subTest(policy=policy,host=host,target=target), self.assertRaises(ValueError):
                inspect_manifest_archive(archive, 'sdk.json', sdk_archive=True)

    def test_all_policies_reject_duplicates_traversal_links_and_file_parents(self):
        from dependency_archive import inspect_manifest_archive, LINUX_SDK_PATHS
        cases = ([('same',b'A',tarfile.REGTYPE),('same',b'B',tarfile.REGTYPE)],
                 [('dir',b'',tarfile.DIRTYPE),('dir',b'',tarfile.DIRTYPE)],
                 [('parent',b'A',tarfile.REGTYPE),('parent/child',b'B',tarfile.REGTYPE)],
                 [('parent/child',b'B',tarfile.REGTYPE),('parent',b'A',tarfile.REGTYPE)],
                 [('../outside',b'bad',tarfile.REGTYPE)], [('/outside',b'bad',tarfile.REGTYPE)],
                 [('dir//child',b'bad',tarfile.REGTYPE)], [('dir/./child',b'bad',tarfile.REGTYPE)],
                 [('alias',b'',tarfile.SYMTYPE)], [('alias',b'',tarfile.LNKTYPE)],
                 [('device',b'',tarfile.CHRTYPE)])
        for index, entries in enumerate(cases):
            archive = self.retained_archive('unsafe'+str(index)+'.tar',entries)
            for policy in ('portable', LINUX_SDK_PATHS):
                with self.subTest(index=index, policy=policy):
                    output=self.root/('unsafe-output-'+str(index)+'-'+policy)
                    with self.assertRaises(ValueError): extract(archive, output, path_policy=policy)
                    self.assertFalse(output.exists())
            with self.subTest(index=index), self.assertRaises(ValueError):
                inspect_manifest_archive(archive,'sdk.json',sdk_archive=True)

    def test_portable_registry_rejects_implicit_directory_and_excluded_file_aliases(self):
        from dependency_archive import PathInventory
        for entries in ((('A/x',False),('a/y',False)), (('A',False),('a/x',False)),
                        (('a/x',False),('A',False)), (('sdk.json',False),('SDK.JSON',False))):
            registry=PathInventory()
            with self.subTest(entries=entries), self.assertRaisesRegex(ValueError,'case-insensitive'):
                for name,directory in entries: registry.add(name,directory)
        registry=PathInventory();registry.add('parent/child',False);registry.add('parent',True)
        for entries in ([('A/x',b'1',tarfile.REGTYPE),('a/y',b'2',tarfile.REGTYPE)],
                        [('A',b'1',tarfile.REGTYPE),('a/x',b'2',tarfile.REGTYPE)]):
            archive=self.retained_archive('implicit.tar',entries,'portable')
            with self.assertRaisesRegex(ValueError,'case-insensitive'):
                extract(archive,self.root/'implicit-output')
            self.assertFalse((self.root/'implicit-output').exists())

    def test_sdk_manifest_alias_duplicate_and_oversize_are_rejected(self):
        from dependency_archive import inspect_manifest_archive, encoded
        for index, name in enumerate(('sdk.json','sdk.json/child')):
            archive=self.retained_archive('manifest-bad'+str(index)+'.tar',[(name,b'{}',tarfile.REGTYPE)])
            with self.assertRaises(ValueError): inspect_manifest_archive(archive,'sdk.json',sdk_archive=True)
        archive=self.root/'oversized.tar'
        with tarfile.open(archive,'w') as stream:
            info=tarfile.TarInfo('sdk.json');info.size=32*1024**2+1
            # Sparse/incomplete body is enough: the declared bound must reject it.
            stream.fileobj.write(info.tobuf());stream.fileobj.write(b'{}')
        with self.assertRaises((ValueError,tarfile.ReadError)):
            inspect_manifest_archive(archive,'sdk.json',sdk_archive=True)

    def test_put_reuse_fetch_no_network(self):
        base = self.root / 'base'
        self.assertFalse(put(base, self.group, self.recipe)['reused'])
        self.assertTrue(put(base, self.group, self.recipe)['reused'])
        fetch(base, self.recipe, self.root / 'fetched')
        self.assertEqual(file_inventory(self.group), file_inventory(self.root / 'fetched'))

    def test_missing_base_never_prepares(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            fetch(self.root / 'absent', self.recipe, self.root / 'out')
        self.assertFalse((self.root / 'out').exists())

    def test_incomplete_group_rejected(self):
        (self.group / names(self.recipe)[1]).unlink()
        with self.assertRaisesRegex(ValueError, 'exactly'):
            verify_group(self.group, self.recipe)

    def test_changed_archive_rejected(self):
        (self.group / names(self.recipe)[0]).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            put(self.root / 'base', self.group, self.recipe)

    def test_unexpected_asset_rejected(self):
        (self.group / 'extra').write_text('unlisted')
        with self.assertRaisesRegex(ValueError, 'exactly'):
            verify_group(self.group, self.recipe)

    def test_duplicate_checksum_rejected(self):
        path = self.group / names(self.recipe)[2]
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + '\n')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            verify_group(self.group, self.recipe)

    def test_unsafe_archive_entries_leave_no_output(self):
        for index, (name, kind) in enumerate((('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE), ('link', tarfile.SYMTYPE), ('file', tarfile.FIFOTYPE))):
            archive = self.root / ('bad-' + str(index) + '.tar')
            with tarfile.open(archive, 'w') as stream:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = 'outside'
                stream.addfile(info, io.BytesIO())
            output = self.root / ('bad-output-' + str(index))
            with self.assertRaises(ValueError): extract(archive, output)
            self.assertFalse(output.exists())

    def test_file_parent_collision_is_rejected_before_writing(self):
        archive = self.root / 'collision.tar'
        with tarfile.open(archive, 'w') as stream:
            for name in ('parent', 'parent/child'):
                info = tarfile.TarInfo(name)
                stream.addfile(info, io.BytesIO())
        with self.assertRaisesRegex(ValueError, 'parent'):
            extract(archive, self.root / 'collision')
        self.assertFalse((self.root / 'collision').exists())


if __name__ == '__main__': unittest.main()
