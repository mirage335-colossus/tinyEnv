from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import prepare_dependencies as p


class PreparedDependencies(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='native development ');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.packages=self.root/'packages';self.packages.mkdir();self.tree=self.root/'deb'
        (self.tree/'DEBIAN').mkdir(parents=True);(self.tree/'usr/include').mkdir(parents=True)
        self.arch=p.run('dpkg','--print-architecture')
        (self.tree/'DEBIAN/control').write_text('Package: foundation-fixture-dev\nSource: foundation-fixture\nVersion: 1.0-1\nArchitecture: '+self.arch+'\nMaintainer: Example <example@example.invalid>\nDescription: Offline development fixture\n')
        (self.tree/'usr/include/fixture.h').write_text('#define FOUNDATION_FIXTURE_VALUE 7\n')
        self.archive=self.packages/'fixture.deb';self.rebuild()
    def rebuild(self):
        subprocess.run(['dpkg-deb','--build',str(self.tree),str(self.archive)],check=True,stdout=subprocess.DEVNULL)
        self.data={'schema_version':1,'architecture':self.arch,'packages':[{'package':'foundation-fixture-dev','version':'1.0-1','file':'fixture.deb','sha256':p.digest(self.archive),'source_package':'foundation-fixture','url':'https://deb.debian.org/debian/pool/fixture.deb'}],'runtime_libraries':[]}
        self.manifest=self.root/'manifest.json';self.manifest.write_text(json.dumps(self.data))
    def test_real_deb_prepare_verify_retained_inputs_and_offline_compile(self):
        output=self.root/'prepared'
        with patch.object(p.urllib.request,'urlopen',side_effect=AssertionError('unexpected network')):
            state=p.prepare(self.manifest,self.packages,output)
            self.assertEqual(p.verify(output)['sha256'],p.digest(output/'prepared.json'))
        self.assertEqual(p.digest(output/'retained-packages/fixture.deb'),p.digest(self.archive))
        cc=shutil.which('cc');self.assertTrue(cc,'Native C compiler is a documented fixture prerequisite')
        source=self.root/'consumer.c';source.write_text('#include <fixture.h>\nint main(void){return FOUNDATION_FIXTURE_VALUE != 7;}\n')
        subprocess.run([cc,'-I'+str(output/'usr/include'),str(source),'-o',str(self.root/'consumer')],check=True)
        subprocess.run([str(self.root/'consumer')],check=True)
        (output/'usr/include/fixture.h').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):p.verify(output)
    def test_checksum_and_package_metadata_changes_are_rejected(self):
        self.data['packages'][0]['version']='2.0';self.manifest.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError,'metadata'):p.prepare(self.manifest,self.packages,self.root/'bad')
        self.data['packages'][0]['sha256']='0'*64;self.manifest.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError,'retained'):p.prepare(self.manifest,self.packages,self.root/'bad')
    def test_matching_architecture_qualified_runtime_and_mutation(self):
        library=self.root/'libfixture.so.1';library.write_bytes(b'provider')
        self.data['runtime_libraries']=[{'package':'fixture-runtime','development':'foundation-fixture-dev','soname':library.name,'link':'usr/lib/libfixture.so'}]
        def query(*args):
            if args[0]=='dpkg':return self.arch
            self.assertEqual(args[-1],'fixture-runtime:'+self.arch)
            return str(library) if args[1]=='-L' else '1.0-1'
        with patch.object(p,'run',side_effect=query):
            result=p.runtimes(self.data);self.assertEqual(result['usr/lib/libfixture.so']['sha256'],p.digest(library))
        with patch.object(p,'run',side_effect=lambda *a:self.arch if a[0]=='dpkg' else '2.0'):
            with self.assertRaisesRegex(ValueError,'versions differ'):p.runtimes(self.data)
    def test_traversal_and_alias_parent_rejected_without_external_write(self):
        for name,link in [('../escape',None),('alias','/tmp'),('alias/child',None)]:
            raw=io.BytesIO()
            with tarfile.open(fileobj=raw,mode='w') as tar:
                if name.startswith('alias/'):
                    parent=tarfile.TarInfo('alias');parent.type=tarfile.SYMTYPE;parent.linkname='/tmp';tar.addfile(parent)
                member=tarfile.TarInfo(name)
                if link:member.type=tarfile.SYMTYPE;member.linkname=link;tar.addfile(member)
                else:member.size=1;tar.addfile(member,io.BytesIO(b'x'))
            stage=self.root/('stage-'+str(len(list(self.root.glob('stage-*')))));stage.mkdir()
            with patch.object(p.subprocess,'check_output',return_value=raw.getvalue()):
                if name=='alias':
                    p.extract_deb(self.archive,stage)
                    with self.assertRaises(ValueError):p.inventory(stage,{})
                else:
                    with self.assertRaises(ValueError):p.extract_deb(self.archive,stage)
            self.assertFalse((self.root/'escape').exists())
    def test_configured_identity_rejects_rewritten_valid_metadata(self):
        output=self.root/'prepared';p.prepare(self.manifest,self.packages,output)
        expected=p.verify(output)['sha256']
        source=self.root/'source';(source/'tools').mkdir(parents=True)
        repository=Path(__file__).resolve().parents[1]
        shutil.copyfile(repository/'tools/prepare_dependencies.py',source/'tools/prepare_dependencies.py')
        (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(Fixture NONE)\ninclude("'+str(repository/'cmake/BuildPolicy.cmake')+'")\nfoundation_finalize_build_policy()\n')
        build=self.root/'build';configure=['cmake','-G','Ninja','-S',str(source),'-B',str(build),'-DFOUNDATION_DEPENDENCY_PREFIX='+str(output)]
        result=subprocess.run(configure,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
        command=['cmake','--build',str(build),'--target','foundation-prefix-check']
        result=subprocess.run(command,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((output/'prepared.json').read_text());state['review_note']='changed'
        (output/'prepared.json').write_text(json.dumps(state))
        p.verify(output)
        with self.assertRaisesRegex(ValueError,'configured'):p.verify(output,expected)
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('identity changed',result.stdout+result.stderr)
        result=subprocess.run(configure,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('identity changed',result.stdout+result.stderr)

    def test_existing_output_is_never_replaced(self):
        output=self.root/'prepared';output.mkdir();(output/'foreign').write_text('keep')
        with self.assertRaisesRegex(ValueError,'new'):p.prepare(self.manifest,self.packages,output)
        self.assertEqual((output/'foreign').read_text(),'keep')


if __name__=='__main__':unittest.main()
