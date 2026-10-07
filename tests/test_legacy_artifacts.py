"""Explicit byte preservation never interprets archive members or grants approval."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import legacy_artifacts as L
import test_ci_transport as fixtures


class Remote(fixtures.FakeGitHub):
    def __init__(self):
        super().__init__();self.run['path']='.github/workflows/legacy-artifacts.yml'
        self.original_run=dict(id=44,head_sha='b'*40,status='completed',conclusion='failure',
            repository=self.repo.copy(),head_repository=self.repo.copy())
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as stream:
            stream.writestr('../never-extract.sh',b'never execute archive content')
        self.payload=raw.getvalue()
        self.artifacts={75:dict(id=75,name='old evidence',size_in_bytes=len(self.payload),expired=False,
            digest='sha256:'+hashlib.sha256(self.payload).hexdigest(),
            workflow_run=dict(id=44,repository_id=7,head_repository_id=7,head_sha='b'*40))}
        self.downloaded=[]

    def json(self,endpoint,**kwargs):
        if endpoint.endswith('/actions/runs/44'): return copy.deepcopy(self.original_run)
        if '/actions/artifacts/' in endpoint:
            return copy.deepcopy(self.artifacts[int(endpoint.rsplit('/',1)[1])])
        return super().json(endpoint,**kwargs)

    def legacy_download(self,repository,artifact_id,path,size):
        self.downloaded.append(artifact_id)
        with path.open('xb') as stream: stream.write(self.payload)


class LegacyArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.remote=Remote()
        self.request=dict(artifact_id=75,sha256=hashlib.sha256(self.remote.payload).hexdigest(),
            run_id=44,source_commit='b'*40,name='old evidence',size=len(self.remote.payload))
        self.context=dict(repository='example/project',run_id=12,attempt=2,source_commit='a'*40,
                          workflow='legacy-artifacts.yml')
        self.addCleanup(patch.stopall);patch.dict(os.environ,{'RUNNER_NAME':'Runner 1'}).start()

    def preserve(self,requests=None,**kwargs):
        return L.preserve('example/project',requests or [self.request],self.root/'output',self.context,
            transport=self.remote,downloader=self.remote.legacy_download,**kwargs)

    def fetch(self,pointer,path):
        return L.ci_transport.fetch_bundle(**self.context,name=pointer['name'],output=path,
            job_id=pointer['job_id'],manifest_id=pointer['manifest']['id'],
            manifest_sha256=pointer['manifest']['sha256'],transport=self.remote)

    def test_exact_opaque_zip_and_origin_roundtrip_without_extraction_or_approval(self):
        result=self.preserve();self.remote.complete()
        self.assertEqual(result['preservation']['qualification'],'not-assessed')
        self.assertFalse(result['preservation']['publication_approved'])
        receipt=result['preservation']['artifacts'][0]
        self.fetch(receipt['pointer'],self.root/'copy')
        self.assertEqual((self.root/'copy/archive.zip').read_bytes(),self.remote.payload)
        origin=json.loads((self.root/'copy/origin.json').read_text())
        self.assertEqual(origin['request'],self.request);self.assertFalse(origin['extracted'])
        self.assertEqual(origin['original']['run']['conclusion'],'failure')
        self.assertEqual(origin['original']['run']['head_sha'],'b'*40)
        self.assertEqual(receipt['pointer']['source_commit'],'a'*40)
        self.assertEqual(L.archive.digest(self.root/'copy/origin.json'),receipt['origin_sha256'])
        self.fetch(result['pointer'],self.root/'inventory')
        self.assertEqual(json.loads((self.root/'inventory/preservation.json').read_text()),result['preservation'])
        self.assertFalse((self.root/'never-extract.sh').exists())
        self.assertEqual(set(p.name for p in (self.root/'copy').iterdir()),{'origin.json','archive.zip'})
        self.assertFalse(any(call[0]=='DELETE' for call in self.remote.calls))
        self.assertEqual(list((self.root/'output').glob('artifact-75-*')),[])

    def test_explicit_list_requires_exact_types_unique_ids_and_bounds(self):
        invalid=[[],{},[dict(self.request,artifact_id=True)],[dict(self.request,size=0)],
            [dict(self.request,size=L.MAX_ARTIFACT+1)],[dict(self.request,sha256='x')],
            [dict(self.request,source_commit='main')],[dict(self.request,name='line\nbreak')],
            [dict(self.request,unknown=1)],[self.request,self.request]]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError): L.selection(value)
        with patch.object(L,'MAX_TOTAL',self.request['size']-1),self.assertRaisesRegex(ValueError,'total'):
            L.selection([self.request])
        self.assertEqual(self.remote.calls,[])

    def test_original_repo_run_and_immutable_metadata_must_match_before_download(self):
        original=copy.deepcopy(self.remote.artifacts[75])
        for key,value in [('id',76),('name','different'),('size_in_bytes',5),('digest','sha256:'+'c'*64),
            ('expired',True),('workflow_run',dict(original['workflow_run'],head_repository_id=8))]:
            with self.subTest(key=key):
                self.remote.artifacts[75]=dict(original,**{key:value})
                with self.assertRaisesRegex(ValueError,'identity differs'): L.observe(L.delivery.Remote('example/project',self.remote),self.request)
        self.remote.artifacts[75]=original
        self.remote.original_run['head_repository']['id']=8
        with self.assertRaisesRegex(ValueError,'identity differs'): self.preserve()
        self.assertEqual(self.remote.downloaded,[]);self.assertFalse(self.remote.releases)

    def test_download_size_or_digest_mismatch_prevents_any_publication(self):
        for payload in (self.remote.payload[:-1],b'x'*len(self.remote.payload)):
            self.remote.payload=payload
            with self.assertRaisesRegex(ValueError,'pinned complete bytes'): self.preserve()
            self.assertFalse(self.remote.releases)
            self.assertTrue(list((self.root/'output').glob('artifact-75-*')))
            # Each rejected attempt gets a distinct explicitly owned destination.
            (self.root/'output').rename(self.root/('failed-'+str(len(list(self.root.glob('failed-*'))))))

    def test_changed_metadata_after_download_prevents_publication(self):
        def changed(*args):
            self.remote.legacy_download(*args);self.remote.artifacts[75]['created_at']='changed'
        with self.assertRaisesRegex(ValueError,'changed during download'):
            L.preserve('example/project',[self.request],self.root/'output',self.context,
                transport=self.remote,downloader=changed)
        self.assertFalse(self.remote.releases)

    def test_changed_original_after_upload_keeps_staging_without_completion_claim(self):
        def publish(**kwargs):
            pointer=L.ci_transport.publish_bundle(**kwargs)
            self.remote.artifacts[75]['created_at']='changed'
            return pointer
        with self.assertRaisesRegex(ValueError,'changed during preservation'):
            self.preserve(publisher=publish)
        self.assertTrue(self.remote.releases)
        self.assertFalse((self.root/'output/artifact-75.json').exists())
        self.assertTrue(list((self.root/'output').glob('artifact-75-*')))

    def test_partial_failure_retains_completed_pointer_and_incomplete_staging(self):
        second=dict(self.request,artifact_id=76);self.remote.artifacts[76]=dict(self.remote.artifacts[75],id=76)
        original=self.remote.legacy_download
        def fail(repository,artifact_id,path,size):
            if artifact_id==76: raise ValueError('injected second transfer failure')
            original(repository,artifact_id,path,size)
        with self.assertRaisesRegex(ValueError,'second transfer'):
            L.preserve('example/project',[self.request,second],self.root/'output',self.context,
                transport=self.remote,downloader=fail)
        self.assertTrue((self.root/'output/artifact-75.json').is_file())
        self.assertFalse((self.root/'output/preservation.json').exists())
        self.assertTrue(list((self.root/'output').glob('artifact-76-*')))
        self.assertFalse(list((self.root/'output').glob('artifact-75-*')))
        self.remote.complete('failure')
        pointer=json.loads((self.root/'output/artifact-75.json').read_text())['pointer']
        L.ci_transport.fetch_bundle(**self.context,name=pointer['name'],output=self.root/'recovered',
            job_id=pointer['job_id'],manifest_id=pointer['manifest']['id'],
            manifest_sha256=pointer['manifest']['sha256'],allow_failed=True,transport=self.remote)
        self.assertEqual((self.root/'recovered/archive.zip').read_bytes(),self.remote.payload)

    def test_existing_output_is_not_overwritten(self):
        (self.root/'output').mkdir();(self.root/'output/foreign').write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError,'new owned'): self.preserve()
        self.assertEqual((self.root/'output/foreign').read_bytes(),b'foreign');self.assertFalse(self.remote.releases)

    def test_wrong_current_workflow_is_rejected_before_download(self):
        self.context['workflow']='candidate.yml'
        with self.assertRaisesRegex(ValueError,'current preservation'): self.preserve()
        self.assertFalse(self.remote.downloaded);self.assertFalse(self.remote.releases)

    def test_upload_failure_preserves_exact_staging_and_no_completion_receipt(self):
        with self.assertRaisesRegex(ValueError,'upload failed'):
            self.preserve(publisher=lambda **kwargs: (_ for _ in ()).throw(ValueError('upload failed')))
        stages=list((self.root/'output').glob('artifact-75-*'));self.assertEqual(len(stages),1)
        self.assertEqual((stages[0]/'archive.zip').read_bytes(),self.remote.payload)
        self.assertFalse((self.root/'output/artifact-75.json').exists())

    def test_downloader_checks_completion_and_stops_owned_writers_on_failure(self):
        from unittest.mock import Mock
        child=Mock();child.poll.return_value=0;child.finish.return_value=0
        path=self.root/'archive.zip'
        with patch.object(L.process_tree,'launch',return_value=child),self.assertRaisesRegex(ValueError,'incomplete'):
            L.download('example/project',75,path,10)
        child.finish.assert_called_once();child.terminate.assert_called_once();child.close.assert_called_once()

    def test_real_supervised_transfer_preserves_binary_bytes_and_rejects_extra_bytes(self):
        original=L.process_tree.launch
        def launch(argv,cwd,stream):
            self.assertEqual(argv[-1],'repos/example/project/actions/artifacts/75/zip')
            return original([sys.executable,'-c','import sys;sys.stdout.buffer.write(bytes(range(256)))'],cwd,stream)
        with patch.object(L.process_tree,'launch',side_effect=launch):
            L.download('example/project',75,self.root/'complete.zip',256,timeout=5)
            self.assertEqual((self.root/'complete.zip').read_bytes(),bytes(range(256)))
            with self.assertRaisesRegex(ValueError,'incomplete|exceeded'):
                L.download('example/project',75,self.root/'oversized.zip',1,timeout=5)

    def test_workflow_is_manual_pointer_only_and_has_no_deletion_or_actions_upload(self):
        text=(ROOT/'.github/workflows/legacy-artifacts.yml').read_text()
        self.assertIn('workflow_dispatch:',text);self.assertIn('contents: write',text)
        self.assertIn('if: failure()',text);self.assertIn('artifact-*.json',text)
        for forbidden in ('actions/upload-artifact','actions/download-artifact','gh run delete','DELETE'):
            self.assertNotIn(forbidden,text)


if __name__=='__main__': unittest.main()
