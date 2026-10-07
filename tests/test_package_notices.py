from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import package_notices as n


class Notices(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.share=self.root/'share';(self.share/'doc/library-dev').mkdir(parents=True);(self.share/'common-licenses').mkdir()
        self.lib=self.root/'libfixture.a';self.lib.write_bytes(b'archive')
        self.notice=self.share/'doc/library-dev/copyright';self.notice.write_text('Terms: /usr/share/common-licenses/Example-1\n')
        (self.share/'common-licenses/Example-1').write_text('Full reviewed example text\n')
    def query(self,*args):
        if args[1]=='-S':return 'library-dev:amd64: '+str(self.lib.resolve())
        return '1.0-1'
    def collect(self,**kwargs):
        return n.collect(self.root/'notices',libraries=[self.lib],share=self.share,query=self.query,**kwargs)
    def test_copies_static_input_notice_and_referenced_full_text(self):
        report=self.collect();self.assertEqual(len(report['files']),2)
        self.assertEqual(report['providers'][0]['input']['sha256'],n.sha(self.lib))
        self.assertEqual(report['providers'][0]['package'],'library-dev:amd64')
        self.assertEqual(report['providers'][0]['version'],'1.0-1')
        for name,item in report['files'].items():self.assertEqual(n.sha(self.root/'notices'/name),item['sha256'])
    def test_terminal_punctuation_and_exact_repeat_install_are_supported(self):
        self.notice.write_text('See /usr/share/common-licenses/Example-1.\n')
        first=self.collect();self.assertEqual(first,self.collect())
        (self.root/'notices/foreign').write_text('keep')
        with self.assertRaisesRegex(ValueError,'existing'):self.collect()
        self.assertTrue((self.root/'notices/foreign').exists())
    def test_repeat_install_rejects_changed_permissions_on_posix(self):
        self.collect()
        path=self.root/'notices/index.json';path.chmod(0o600)
        if os.name=='posix':
            with self.assertRaisesRegex(ValueError,'existing'):self.collect()
        else:
            # Windows file permissions do not expose POSIX group/other bits.
            self.assertEqual(self.collect()['schema_version'],1)

    def test_windows_each_selected_port_requires_its_own_notice(self):
        sdk=self.root/'sdk';(sdk/'prefix/installed/x64-windows-static/share/first').mkdir(parents=True)
        (sdk/'prefix/installed/x64-windows-static/share/first/copyright').write_text('First full terms')
        metadata={'recipe_id':'a'*64,'provenance':{'triplet':'x64-windows-static','ports':['first','second[feature]']}}
        (sdk/'sdk.json').write_text(json.dumps(metadata))
        with patch('sdk_manifest.verify_sdk'),self.assertRaisesRegex(ValueError,'second'):
            n.collect(self.root/'notices',windows_dependencies=sdk)
        directory=sdk/'prefix/installed/x64-windows-static/share/second';directory.mkdir();(directory/'copyright').write_text('Second full terms')
        with patch('sdk_manifest.verify_sdk'):
            report=n.collect(self.root/'notices',windows_dependencies=sdk)
        self.assertEqual(len(report['files']),2)

    def test_transitive_copied_runtime_gets_its_exact_notice_provider(self):
        runtime=self.root/'runtime.json';runtime.write_text(json.dumps({'files':{self.lib.name:n.sha(self.lib)}}))
        report=n.collect(self.root/'notices',runtime_inventory=runtime,runtime_roots=[self.root],share=self.share,query=self.query)
        self.assertEqual(report['providers'][0]['input']['sha256'],n.sha(self.lib))
        self.lib.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'unavailable'):
            n.collect(self.root/'other-notices',runtime_inventory=runtime,runtime_roots=[self.root],share=self.share,query=self.query)
    def test_missing_referenced_text_is_a_failure_before_publication(self):
        (self.share/'common-licenses/Example-1').unlink()
        with self.assertRaisesRegex(ValueError,'common license'):self.collect()
        self.assertFalse((self.root/'notices').exists())
    def test_wrong_package_ownership_and_ambiguous_owner_fail(self):
        other=self.root/'other';other.write_bytes(b'different')
        for owner in ['library-dev: '+str(other),'library-dev: '+str(self.lib)+'\nother-dev: '+str(self.lib)]:
            with self.assertRaises(ValueError):n.distro_notice(self.lib,self.share,lambda *a:owner)
    def test_explicit_manifest_covers_exact_library_bytes_only(self):
        manifest=self.root/'notices.json';text=self.root/'LICENSE';text.write_text('reviewed text')
        manifest.write_text(json.dumps({'schema_version':1,'components':[{'name':'fixture','inputs':[n.sha(self.lib)],'notices':{'LICENSE':n.sha(text)}}]}))
        report=self.collect(manifest=manifest);self.assertEqual(report['providers'][0]['provider'],'explicit')
        text.write_text('changed')
        with self.assertRaisesRegex(ValueError,'digest'):n.manual_components(manifest)
    def test_configured_source_notice_is_rechecked(self):
        before=n.sha(self.notice);self.notice.write_text('changed')
        with self.assertRaisesRegex(ValueError,'configured'):n.collect(self.root/'notices',files=[(self.notice,before)])
    def test_retained_sdk_copies_all_declared_notices_without_host_queries(self):
        sdk=self.root/'sdk';(sdk/'share/legal').mkdir(parents=True);(sdk/'share/legal/LICENSE').write_text('SDK text')
        (sdk/'sdk.json').write_text(json.dumps({'recipe_id':'a'*64,'licenses':['share/legal'],'target':{'sysroot':'target'}}))
        with patch('sdk_manifest.verify_sdk') as verify:
            report=n.collect(self.root/'notices',sdk=sdk,query=lambda *args:self.fail('host package lookup'))
        verify.assert_called_once_with(sdk.resolve(),release=True)
        self.assertEqual(len(report['files']),1);self.assertEqual(report['providers'][0]['recipe_id'],'a'*64)
    def test_wasm_runtime_terms_are_required_from_authenticated_sdk_files(self):
        sdk=self.root/'sdk';sdk.mkdir();(sdk/'LICENSE').write_text('top level')
        files={}
        for relative in n.WASM_RUNTIME_NOTICES:
            path=sdk/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('terms '+relative)
            files[relative]=n.sha(path)
        metadata={'recipe_id':'a'*64,'licenses':['LICENSE'],'target':{'system':'Emscripten','sysroot':'cache/sysroot'},'files':files}
        (sdk/'sdk.json').write_text(json.dumps(metadata))
        with patch('sdk_manifest.verify_sdk'):
            report=n.collect(self.root/'notices',sdk=sdk)
            self.assertEqual(1+len(n.WASM_RUNTIME_NOTICES),len(report['files']))
            (sdk/n.WASM_RUNTIME_NOTICES[0]).write_text('changed')
            with self.assertRaisesRegex(ValueError,'retained inventory'):
                n.collect(self.root/'other-notices',sdk=sdk)

    def test_sdk_never_satisfies_missing_common_license_from_host(self):
        sdk=self.root/'sdk';(sdk/'legal').mkdir(parents=True);(sdk/'legal/COPYING').write_text(self.notice.read_text())
        (sdk/'sdk.json').write_text(json.dumps({'recipe_id':'a'*64,'licenses':['legal'],'target':{'sysroot':'target'}}))
        with patch('sdk_manifest.verify_sdk'),self.assertRaisesRegex(ValueError,'common license'):
            n.collect(self.root/'notices',sdk=sdk,share=self.share)
    def test_empty_sdk_notice_tree_fails(self):
        empty=self.root/'empty';empty.mkdir()
        with self.assertRaisesRegex(ValueError,'empty'):n.notice_files(empty)


if __name__=='__main__':unittest.main()
