#!/usr/bin/env python3
"""Explicit opaque archive preservation; no extraction, approval or remote deletion."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

import ci_transport
import dependency_archive as archive
import github_release as delivery
import process_tree

MAX_ARTIFACT = 16 * 1024**3
MAX_TOTAL = 64 * 1024**3
MAX_REQUEST = 256 * 1024
FIELDS = {'artifact_id', 'sha256', 'run_id', 'source_commit', 'name', 'size'}


def selection(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError('explicit bounded artifact list required')
    ids, total = set(), 0
    for item in value:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ValueError('exact artifact identity fields required')
        if (any(type(item[key]) is not int or item[key] < 1 for key in ('artifact_id', 'run_id', 'size')) or
                item['size'] > MAX_ARTIFACT or item['artifact_id'] in ids or
                not isinstance(item['sha256'], str) or not delivery.SHA.fullmatch(item['sha256']) or
                not isinstance(item['source_commit'], str) or not delivery.OID.fullmatch(item['source_commit']) or
                not isinstance(item['name'], str) or not 1 <= len(item['name']) <= 255 or
                any(ord(c) < 32 or ord(c) == 127 for c in item['name'])):
            raise ValueError('invalid, duplicate or unbounded artifact identity')
        ids.add(item['artifact_id']); total += item['size']
    if total > MAX_TOTAL:
        raise ValueError('selected archive bytes exceed supported total')
    return value


def ordinary_parent(path):
    for parent in (path, *path.parents):
        try: value = parent.lstat()
        except FileNotFoundError: continue
        if not stat.S_ISDIR(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
            raise ValueError('preservation output requires ordinary directory parents')


def observe(remote, request):
    repo = remote.transport.json(remote.base)
    run = remote.transport.json(remote.base + '/actions/runs/' + str(request['run_id']))
    row = remote.transport.json(remote.base + '/actions/artifacts/' + str(request['artifact_id']))
    if not all(isinstance(value,dict) for value in (repo,run,row)):
        raise ValueError('original provenance requires complete API objects')
    source = row.get('workflow_run', {})
    if (not isinstance(source,dict) or not delivery.positive(run.get('id')) or
            not delivery.positive(row.get('id')) or not delivery.positive(source.get('id')) or
            any(not isinstance(run.get(key),dict) or not delivery.positive(run[key].get('id'))
                for key in ('repository','head_repository')) or
            any(not delivery.positive(source.get(key)) for key in ('repository_id','head_repository_id')) or
            not delivery.positive(repo.get('id')) or repo.get('full_name', '').casefold() != remote.repository.casefold() or
            run.get('id') != request['run_id'] or run.get('head_sha') != request['source_commit'] or
            any(run.get(key, {}).get('id') != repo['id'] or
                run.get(key, {}).get('full_name', '').casefold() != remote.repository.casefold()
                for key in ('repository', 'head_repository')) or
            row.get('id') != request['artifact_id'] or row.get('name') != request['name'] or
            type(row.get('size_in_bytes')) is not int or row['size_in_bytes'] != request['size'] or
            row.get('expired') is not False or row.get('digest') != 'sha256:' + request['sha256'] or
            source.get('id') != request['run_id'] or source.get('head_sha') != request['source_commit'] or
            source.get('repository_id') != repo['id'] or source.get('head_repository_id') != repo['id']):
        raise ValueError('original repository, run or immutable artifact identity differs')
    return {'repository': {'id': repo['id'], 'full_name': repo['full_name']}, 'run': run, 'artifact': row}


def download(repository, artifact_id, output, expected_size, *, timeout=1800):
    """Supervise one bounded CLI transfer without buffering the archive in memory."""
    with output.open('xb') as stream:
        child = process_tree.launch(['gh', 'api', '--hostname', 'github.com',
            f'repos/{repository}/actions/artifacts/{artifact_id}/zip'], output.parent, stream)
        try:
            deadline = time.monotonic() + timeout
            while child.poll() is None:
                if output.stat().st_size > expected_size or time.monotonic() >= deadline:
                    raise ValueError('legacy archive transfer exceeded its byte or time bound')
                time.sleep(.05)
            result = child.finish()
            if result or output.stat().st_size != expected_size:
                raise ValueError('legacy archive transfer failed or has incomplete bytes')
        except BaseException:
            child.terminate()
            raise
        finally:
            child.close()


def preserve(repository, requests, directory, context, *, transport=None, downloader=None, publisher=None):
    """Store one verified opaque ZIP per bundle; retain receipts after partial failure."""
    delivery.location(repository); requests=selection(delivery.parse(archive.encoded(requests)))
    expected_context = {'repository', 'run_id', 'attempt', 'source_commit', 'workflow'}
    if (not isinstance(context, dict) or set(context) != expected_context or context['repository'] != repository or
            context['workflow'] != 'legacy-artifacts.yml'):
        raise ValueError('explicit current preservation workflow context required')
    ci_transport._context(**context, name='legacy-preservation')
    directory = Path(directory).absolute()
    ordinary_parent(directory.parent)
    if directory.exists() or directory.is_symlink(): raise ValueError('new owned preservation directory required')
    directory.mkdir(parents=True)
    remote = delivery.Remote(repository, transport)
    receipts = []
    archive.write_json(directory / 'request.json', requests)
    for request in requests:
        stage = Path(tempfile.mkdtemp(prefix='artifact-' + str(request['artifact_id']) + '-', dir=directory))
        before = observe(remote, request)
        payload = stage / 'archive.zip'
        (downloader or download)(repository, request['artifact_id'], payload, request['size'])
        value = payload.lstat()
        if (not stat.S_ISREG(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400 or
                value.st_size != request['size'] or archive.digest(payload) != request['sha256']):
            raise ValueError('downloaded opaque ZIP differs from pinned complete bytes')
        if observe(remote, request) != before:
            raise ValueError('original artifact or producer changed during download')
        origin = dict(schema_version=1, kind='opaque-legacy-artifact', qualification='not-assessed',
            publication_approved=False, extracted=False, repository=repository, request=request, original=before)
        archive.write_json(stage / 'origin.json', origin)
        pointer = (publisher or ci_transport.publish_bundle)(**context,
            name='legacy-artifact-' + str(request['artifact_id']), root=stage, paths=['archive.zip', 'origin.json'],
            metadata={'kind': 'opaque-legacy-artifact', 'artifact_id': request['artifact_id'],
                      'qualification': 'not-assessed', 'publication_approved': False}, transport=transport)
        if observe(remote,request)!=before:
            raise ValueError('original artifact or producer changed during preservation')
        # Publication already rechecks exact local bytes and remote asset IDs.
        # Record each completed bundle before releasing its private staging bytes.
        receipt = dict(request=request, pointer=pointer, origin_sha256=archive.digest(stage / 'origin.json'))
        delivery.coverage.write_new(directory / ('artifact-' + str(request['artifact_id']) + '.json'), receipt)
        receipts.append(receipt)
        shutil.rmtree(stage)
    result = dict(schema_version=1, status='preserved', qualification='not-assessed', publication_approved=False,
                  repository=repository, current_producer=context, artifacts=receipts)
    delivery.coverage.write_new(directory / 'preservation.json', result)
    pointer = (publisher or ci_transport.publish_bundle)(**context, name='legacy-preservation', root=directory,
        paths=['request.json', 'preservation.json'],
        metadata={'kind': 'opaque-legacy-preservation', 'qualification': 'not-assessed'}, transport=transport)
    delivery.coverage.write_new(directory / 'pointer.json', pointer)
    return {'pointer': pointer, 'preservation': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    raw = os.environ.get('LEGACY_ARTIFACTS', '')
    if len(raw.encode('utf-8')) > MAX_REQUEST: raise ValueError('explicit request exceeds supported bound')
    repository = os.environ['GITHUB_REPOSITORY']
    context = dict(repository=repository, run_id=int(os.environ['GITHUB_RUN_ID']),
        attempt=int(os.environ['GITHUB_RUN_ATTEMPT']), source_commit=os.environ['GITHUB_SHA'], workflow='legacy-artifacts.yml')
    result = preserve(repository, delivery.parse(raw), args.output, context)
    pointer = json.dumps(result['pointer'], sort_keys=True, separators=(',', ':'))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream: stream.write('pointer=' + pointer + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('Preserved exact opaque archives; qualification not assessed. No original artifacts deleted.\n\n'
                         'Manifest pointer: `' + pointer + '`\n')
    print(pointer)


if __name__ == '__main__':
    try: main()
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        raise SystemExit('Legacy preservation failed; retain existing local receipts and inspect draft bundles: ' + str(error))
