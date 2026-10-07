#!/usr/bin/env python3
"""Independently verify retained opaque archives; never delete original artifacts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat

import ci_transport as bundles
import dependency_archive as archive
import github_release as delivery
import legacy_artifacts as legacy

CONTEXT = {'repository', 'run_id', 'attempt', 'source_commit', 'workflow'}
MAX_JSON = 1024 * 1024


def pointer(value, repository, *, name=None):
    fields = CONTEXT | {'schema_version', 'name', 'job_id', 'release_id', 'tag', 'manifest'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('exact preservation pointer fields required')
    bundles._context(**{key: value[key] for key in CONTEXT | {'name'}})
    item = value['manifest']
    if (type(value['schema_version']) is not int or value['schema_version'] != 1 or
            value['repository'] != repository or value['workflow'] != 'legacy-artifacts.yml' or
            name is not None and value['name'] != name or
            any(not delivery.positive(value[key]) for key in ('job_id', 'release_id')) or
            value['tag'] != f"ci-{value['run_id']}-attempt-{value['attempt']}" or
            not isinstance(item, dict) or set(item) != {'id', 'name', 'size', 'sha256'} or
            not delivery.positive(item['id']) or not delivery.positive(item['size']) or
            item['size'] > bundles.MAX_MANIFEST or item['name'] != 'bundle-' + value['name'] + '.json' or
            not isinstance(item['sha256'], str) or not delivery.SHA.fullmatch(item['sha256'])):
        raise ValueError('preservation pointer identity or bounds differ')
    return value


def read_json(path, limit=MAX_JSON):
    value = path.lstat()
    if (not stat.S_ISREG(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400 or
            not 0 < value.st_size <= limit):
        raise ValueError('bounded ordinary JSON input required')
    return delivery.parse(path.read_bytes())


def durable(path, value):
    delivery.coverage.write_new(path, value)
    # A completed receipt must precede deletion of its owned archive staging.
    if os.name == 'posix':
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)


def fetch(pinned, output, files, *, transport=None):
    """Preflight exact declared sizes before fetching the complete verified bundle."""
    remote = delivery.Remote(pinned['repository'], transport)
    info = remote.find(pinned['tag'])
    if info['id'] != pinned['release_id']: raise ValueError('preserved release ID differs')
    row = remote.assets(info).get(pinned['manifest']['name'])
    if row is None or bundles._asset(row) != pinned['manifest']:
        raise ValueError('pinned preservation manifest differs')
    manifest_path = output.parent / ('manifest-' + str(pinned['manifest']['id']) + '.json')
    remote.download(row, manifest_path, pinned['manifest']['sha256'])
    manifest = read_json(manifest_path, bundles.MAX_MANIFEST)
    context = {key: pinned[key] for key in CONTEXT | {'name'}}
    repository_id = bundles._run(remote, context)
    bundles._validate_manifest(manifest, context, info, repository_id)
    if set(manifest['files']) != set(files): raise ValueError('unexpected preservation bundle files')
    for name, size in files.items():
        declared = manifest['files'][name]['size']
        if size is None and not 0 < declared <= MAX_JSON or size is not None and declared != size:
            raise ValueError('preservation member size differs from pinned bound')
    if manifest['archive']['size'] > sum(item['size'] for item in manifest['files'].values()) + 32 * 1024**2:
        raise ValueError('preservation archive overhead exceeds supported disk bound')
    received = bundles.fetch_bundle(**context, output=output, job_id=pinned['job_id'],
        manifest_id=pinned['manifest']['id'], manifest_sha256=pinned['manifest']['sha256'], transport=transport)
    if received['pointer'] != pinned or received['manifest'] != manifest:
        raise ValueError('preservation pointer or manifest changed during fetch')
    if {entry.name for entry in output.iterdir()} != set(files): raise ValueError('unexpected fetched files')
    return received


def origin(value, request, repository, repository_id):
    fields = {'schema_version', 'kind', 'qualification', 'publication_approved', 'extracted',
              'repository', 'request', 'original'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or
            value['schema_version'] != 1 or value['kind'] != 'opaque-legacy-artifact' or
            value['qualification'] != 'not-assessed' or value['publication_approved'] is not False or
            value['extracted'] is not False or value['repository'] != repository or value['request'] != request or
            not isinstance(value['original'], dict) or set(value['original']) != {'repository', 'run', 'artifact'}):
        raise ValueError('retained original provenance differs')
    original = value['original']
    # Replay the original API identity checks against the exact retained evidence.
    class Evidence:
        def json(self, endpoint):
            return {f'repos/{repository}': original['repository'],
                    f'repos/{repository}/actions/runs/{request["run_id"]}': original['run'],
                    f'repos/{repository}/actions/artifacts/{request["artifact_id"]}': original['artifact']}[endpoint]
    if legacy.observe(delivery.Remote(repository, Evidence()), request) != original:
        raise ValueError('retained original evidence differs')
    if original['repository']['id'] != repository_id:
        raise ValueError('original repository ID differs from preservation producer')
    return original


def verify(repository, preservation_pointer, requests, output, *, transport=None, checkpoint=None):
    """Fetch each archive once; retain partial receipts and failed staging on error.

    checkpoint(receipt_path) may durably publish each small receipt. It must return
    its reference before that archive is removed; an exception preserves staging.
    An existing output cannot be resumed implicitly or overwritten.
    """
    delivery.location(repository)
    pinned = pointer(delivery.parse(archive.encoded(preservation_pointer)), repository, name='legacy-preservation')
    requests = legacy.selection(delivery.parse(archive.encoded(requests)))
    output = Path(output).absolute(); legacy.ordinary_parent(output.parent)
    if output.exists() or output.is_symlink(): raise ValueError('new owned verification output required')
    output.mkdir(parents=True); receipts = output / 'receipts'; receipts.mkdir()
    durable(receipts / 'intent.json', dict(schema_version=1, status='incomplete', repository=repository,
        preservation_pointer=pinned, requests=requests, qualification='not-assessed', original_artifacts_deleted=False))
    inventory = output / 'inventory'
    received = fetch(pinned, inventory, {'request.json': None, 'preservation.json': None}, transport=transport)
    saved = read_json(inventory / 'preservation.json'); context = {key: pinned[key] for key in CONTEXT}
    if (not isinstance(saved, dict) or set(saved) != {'schema_version', 'status', 'qualification',
            'publication_approved', 'repository', 'current_producer', 'artifacts'} or
            type(saved['schema_version']) is not int or saved['schema_version'] != 1 or saved['status'] != 'preserved' or
            saved['qualification'] != 'not-assessed' or saved['publication_approved'] is not False or
            saved['repository'] != repository or saved['current_producer'] != context or
            read_json(inventory / 'request.json') != requests or not isinstance(saved['artifacts'], list) or
            len(saved['artifacts']) != len(requests) or
            received['manifest']['metadata'] != {'kind': 'opaque-legacy-preservation', 'qualification': 'not-assessed'}):
        raise ValueError('preserved complete selection or producer differs')
    for row, request in zip(saved['artifacts'], requests):
        if (not isinstance(row, dict) or set(row) != {'request', 'pointer', 'origin_sha256'} or row['request'] != request or
                not isinstance(row['origin_sha256'], str) or not delivery.SHA.fullmatch(row['origin_sha256'])):
            raise ValueError('artifact selection or origin digest differs')
        nested = pointer(row['pointer'], repository, name='legacy-artifact-' + str(request['artifact_id']))
        if any(nested[key] != pinned[key] for key in CONTEXT | {'job_id', 'release_id', 'tag'}):
            raise ValueError('artifact bundle does not belong to the exact preservation producer')
    verified = []
    for row in saved['artifacts']:
        request = row['request']; nested = row['pointer']; stage = output / ('archive-' + str(request['artifact_id']))
        fetched = fetch(nested, stage, {'archive.zip': request['size'], 'origin.json': None}, transport=transport)
        if fetched['manifest']['metadata'] != {'kind': 'opaque-legacy-artifact', 'artifact_id': request['artifact_id'],
                'qualification': 'not-assessed', 'publication_approved': False}:
            raise ValueError('artifact bundle metadata differs')
        payload = stage / 'archive.zip'; value = payload.lstat()
        if (not stat.S_ISREG(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400 or
                value.st_size != request['size'] or archive.digest(payload) != request['sha256'] or
                archive.digest(stage / 'origin.json') != row['origin_sha256']):
            raise ValueError('independent archive or origin bytes differ')
        original = origin(read_json(stage / 'origin.json'), request, repository, received['manifest']['repository_id'])
        result = dict(schema_version=1, status='verified', request=request, pointer=nested,
            origin_sha256=row['origin_sha256'], original=original, preservation_pointer=pinned,
            qualification='not-assessed', publication_approved=False, extracted=False, original_artifacts_deleted=False)
        receipt_path = receipts / ('artifact-' + str(request['artifact_id']) + '.json')
        durable(receipt_path, result)
        if checkpoint is not None:
            reference = checkpoint(receipt_path)
            if not isinstance(reference, dict) or not reference: raise ValueError('durable checkpoint reference required')
            durable(receipts / ('checkpoint-' + str(request['artifact_id']) + '.json'), reference)
        verified.append(dict(request=request, pointer=nested, origin_sha256=row['origin_sha256'],
            receipt_sha256=archive.digest(receipt_path), original_run_id=request['run_id']))
        shutil.rmtree(stage)
        print('Verified opaque archive ' + str(request['artifact_id']) + ' (' + str(request['size']) + ' bytes)', flush=True)
    report = dict(schema_version=1, status='passed', repository=repository, preservation_pointer=pinned,
        preservation_sha256=archive.digest(inventory / 'preservation.json'), requests_sha256=archive.digest(inventory / 'request.json'),
        producer=received['producer'], artifacts=verified, artifact_count=len(verified),
        total_bytes=sum(row['request']['size'] for row in verified), qualification='not-assessed',
        publication_approved=False, extracted=False, original_artifacts_deleted=False)
    durable(receipts / 'verification.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    raw_pointer = os.environ.get('PRESERVATION_POINTER', ''); raw_requests = os.environ.get('LEGACY_ARTIFACTS', '')
    if len(raw_pointer.encode()) > 65536 or len(raw_requests.encode()) > legacy.MAX_REQUEST:
        raise ValueError('verification inputs exceed supported bounds')
    repository = os.environ['GITHUB_REPOSITORY']
    context = dict(repository=repository, run_id=int(os.environ['GITHUB_RUN_ID']), attempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
        source_commit=os.environ['GITHUB_SHA'], workflow='verify-retention.yml')
    def checkpoint(path):
        return bundles.publish_bundle(**context, name='retention-check-' + path.stem, root=path.parent, paths=[path.name],
            metadata={'kind': 'independent-opaque-byte-verification', 'qualification': 'not-assessed'})
    verify(repository, delivery.parse(raw_pointer), delivery.parse(raw_requests), args.output, checkpoint=checkpoint)
    result = bundles.publish_bundle(**context, name='legacy-verification', root=args.output / 'receipts', paths=sorted(p.name for p in (args.output / 'receipts').iterdir()),
        metadata={'kind': 'independent-opaque-byte-verification', 'status': 'passed', 'qualification': 'not-assessed'})
    durable(args.output / 'pointer.json', result)
    value = json.dumps(result, sort_keys=True, separators=(',', ':'))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream: stream.write('pointer=' + value + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('All requested opaque archives independently verified. No original artifacts deleted; qualification not assessed.\n\nPointer: `' + value + '`\n')
    print(value)


if __name__ == '__main__':
    try: main()
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        raise SystemExit('Preservation verification incomplete; retain per-archive receipts and failed staging: ' + str(error))
