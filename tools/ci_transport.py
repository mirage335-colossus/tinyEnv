#!/usr/bin/env python3
"""Native same-run handoffs and strict legacy draft-release transport.

Native artifacts use the executing Actions context and workflow needs, with full
byte/context validation. Legacy relay bundles retain complete remote provenance
checks and bounded assets. Stored bytes alone never grant qualification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import time
import unicodedata

import dependency_archive as archive
import github_release as delivery

CHUNK_BYTES = 512 * 1024 * 1024
MAX_BYTES = 64 * 1024**3
MAX_FILES = 16000
MAX_MANIFEST = 8 * 1024 * 1024
MAX_PARTS = 256
MAX_BUNDLES = 128
NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,79}')
SHA = re.compile(r'[0-9a-f]{64}')


class TransportError(ValueError):
    pass


def _positive(value):
    return type(value) is int and value > 0


def _context(repository, run_id, attempt, source_commit, workflow, name):
    delivery.location(repository)
    if (not _positive(run_id) or not _positive(attempt) or
            not isinstance(source_commit, str) or not delivery.OID.fullmatch(source_commit) or
            not isinstance(workflow, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.yml', workflow) or
            not isinstance(name, str) or not NAME.fullmatch(name)):
        raise TransportError('exact run, attempt, commit, workflow and portable bundle name required')
    return dict(repository=repository, run_id=run_id, attempt=attempt,
                source_commit=source_commit, workflow=workflow, name=name)


def _same_run(context):
    """Reuse immutable run identity only inside its exact executing workflow.

    This is a request-local optimization, never a persistent provenance cache.
    Historical/cross-run reads keep every strict remote boundary check.
    """
    return (os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REPOSITORY', '').casefold() == context['repository'].casefold() and
            os.environ.get('GITHUB_RUN_ID') == str(context['run_id']) and
            os.environ.get('GITHUB_RUN_ATTEMPT') == str(context['attempt']) and
            os.environ.get('GITHUB_SHA') == context['source_commit'] and
            os.environ.get('GITHUB_WORKFLOW_REF', '').startswith(
                context['repository'] + '/.github/workflows/' + context['workflow'] + '@'))


def _run(remote, context):
    repo = remote.transport.json(remote.base)
    run = remote.transport.json(remote.base + '/actions/runs/' + str(context['run_id']) +
                                '/attempts/' + str(context['attempt']))
    qualification_push = (context['workflow'] == 'rust-qualification.yml' and run.get('event') == 'push' and
                          isinstance(run.get('head_branch'), str) and
                          re.fullmatch(r'codex/rust-[A-Za-z0-9._-]+', run['head_branch']))
    if (not _positive(repo.get('id')) or repo.get('full_name', '').casefold() != remote.repository.casefold() or
            run.get('id') != context['run_id'] or run.get('run_attempt') != context['attempt'] or
            run.get('head_sha') != context['source_commit'] or
            run.get('path') != '.github/workflows/' + context['workflow'] or
            not (run.get('event') in ('workflow_dispatch', 'workflow_call') or qualification_push) or
            any(run.get(key, {}).get('id') != repo['id'] or
                run.get(key, {}).get('full_name', '').casefold() != remote.repository.casefold()
                for key in ('repository', 'head_repository'))):
        raise TransportError('producer repository, workflow, attempt or source differs')
    return repo['id']


def _jobs(remote, context):
    rows, total = [], None
    for page in range(1, 101):
        item = remote.transport.json(remote.base + '/actions/runs/' + str(context['run_id']) +
            '/attempts/' + str(context['attempt']) + '/jobs?per_page=100&page=' + str(page))
        if (type(item.get('total_count')) is not int or not 0 <= item['total_count'] <= 10000 or
                not isinstance(item.get('jobs'), list) or total not in (None, item['total_count'])):
            raise TransportError('incomplete or changed producer job inventory')
        total = item['total_count']; rows.extend(item['jobs'])
        if len(rows) >= total:
            if len(rows) != total or len({x.get('id') for x in rows}) != total:
                raise TransportError('ambiguous producer job inventory')
            return rows
        if not item['jobs']: break
    raise TransportError('producer job inventory exceeds supported bounds')


def _producer(remote, context, *, job_id=None, job_name=None, runner_name=None,
              publishing=False, allow_failed=False, observed=None):
    if observed is not None:
        job = observed
        if job_id is not None and job.get("id") != job_id:
            raise TransportError("producer job identity differs")
    elif job_id is not None:
        if not _positive(job_id): raise TransportError('positive producer job ID required')
        job = remote.transport.json(remote.base + '/actions/jobs/' + str(job_id))
    else:
        runner_name = runner_name or (os.environ.get('RUNNER_NAME') if publishing else None)
        if not job_name and not runner_name: raise TransportError('exact producer job or runner required')
        matches = [x for x in _jobs(remote, context)
                   if (not job_name or x.get('name') == job_name) and
                   (not runner_name or x.get('runner_name') == runner_name) and
                   (not publishing or x.get('status') == 'in_progress')]
        if len(matches) != 1: raise TransportError('producer job selection is absent or ambiguous')
        job = matches[0]
    if (not _positive(job.get('id')) or job.get('run_id') != context['run_id'] or
            job.get('run_attempt') != context['attempt'] or job.get('head_sha') != context['source_commit'] or
            not isinstance(job.get('name'), str) or not job['name'] or
            not _positive(job.get('runner_id')) or not isinstance(job.get('runner_name'), str) or
            not job['runner_name'] or job_name is not None and job['name'] != job_name or
            runner_name is not None and job['runner_name'] != runner_name):
        raise TransportError('producer job identity differs')
    if publishing:
        valid = job.get('status') == 'in_progress' or (
            job.get('status') == 'completed' and job.get('conclusion') in ('success', 'failure'))
    else:
        valid = job.get('status') == 'completed' and job.get('conclusion') in (
            ('success', 'failure') if allow_failed else ('success',))
    if not valid: raise TransportError('producer job has not reached the required completion state')
    return {k: job[k] for k in ('id', 'name', 'runner_id', 'runner_name')}, job


def _tag(context):
    return 'ci-' + str(context['run_id']) + '-attempt-' + str(context['attempt'])


def _store(remote, context, repository_id, *, create=False, release_id=None):
    tag = _tag(context)
    identity = {k: v for k, v in context.items() if k != 'name'}
    identity.update(schema_version=1, kind='private-ci-transport', repository_id=repository_id)
    if release_id is None:
        info = remote.find(tag, required=False)
    else:
        # Once selected in this request, an exact ID avoids paginating every
        # historical release. A replacement draft cannot satisfy this identity.
        info = remote.transport.json(remote.base + '/releases/' + str(release_id))
        remote.info(info, tag)
        if info['id'] != release_id: raise TransportError('release changed')
    if info is None and create:
        ref = remote.reference(tag, missing=True)
        if ref not in (None, context['source_commit']): raise TransportError('transport tag source differs')
        # GitHub permits several drafts for one tag. Only the confirmed winner
        # of atomic ref creation may initialize its draft; list absence grants
        # no ownership. An uncertain ref response must never create a second one.
        owns_initialization = False
        if ref is None:
            try:
                remote.change('/git/refs', body={'ref': 'refs/tags/' + tag, 'sha': context['source_commit']})
                owns_initialization = True
            except delivery.DeliveryError:
                if remote.reference(tag, missing=True) != context['source_commit']: raise
        creation_error = None
        created_id = None
        if owns_initialization:
            try:
                created = remote.change('/releases', body={'tag_name': tag, 'target_commitish': context['source_commit'],
                    'name': tag, 'body': archive.encoded(identity).decode(), 'draft': True,
                    'prerelease': True, 'make_latest': 'false'})
            except delivery.DeliveryError as error:
                creation_error = error
            else:
                remote.info(created, tag)
                if (created['draft'] is not True or created['prerelease'] is not True or
                        created['name'] != tag or created.get('target_commitish') != context['source_commit'] or
                        delivery.parse(created.get('body', 'null')) != identity):
                    raise TransportError('created transport release identity or lifecycle differs')
                created_id = created['id']
        # Observe a confirmed creation by its exact ID. A lost response or a
        # competing initializer still requires strict complete discovery; neither
        # path can repeat the creation mutation.
        if created_id is not None:
            info = remote.wait_find(tag, release_id=created_id)
        else:
            for delay in (0, .25, .5, 1, 2, 4, 8):
                if delay: time.sleep(delay)
                info = remote.find(tag, required=False)
                if info is not None: break
        if info is None:
            if creation_error is not None: raise creation_error
            raise TransportError('transport draft is not visible; preserve initialization state and reconcile')
    if (info is None or info.get('draft') is not True or info.get('prerelease') is not True or
            info.get('name') != tag or delivery.parse(info.get('body', 'null')) != identity or
            remote.reference(tag) != context['source_commit']):
        raise TransportError('private transport release identity or lifecycle differs')
    return info


def _prefix(name):
    return 'blob-' + hashlib.sha256(name.encode()).hexdigest() + '-'


def _manifest_name(name):
    return 'bundle-' + name + '.json'


def _asset_inventory(remote, info):
    rows = remote.transport.pages(remote.base + '/releases/' + str(info['id']) + '/assets?per_page=100')
    result, names, ids = {}, set(), set()
    for row in rows:
        key = row.get('name')
        if not isinstance(key, str) or key.casefold() in names or not _positive(row.get('id')) or row['id'] in ids:
            raise TransportError('duplicate or incomplete remote asset inventory')
        names.add(key.casefold()); ids.add(row['id']); result[key] = row
    return result


def _bundle_assets(inventory, name):
    result = {}
    for key, row in inventory.items():
        if key != _manifest_name(name) and not key.startswith(_prefix(name)): continue
        if (row.get('state') != 'uploaded' or type(row.get('size')) is not int or
                not 0 <= row['size'] < 2 * 1024**3 or not isinstance(row.get('digest'), str) or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', row['digest'])):
            raise TransportError('bundle contains an incomplete or unbound remote asset; preserve it')
        result[key] = {k: row[k] for k in ('id', 'name', 'state', 'size', 'digest')}
    return result


def _assets(remote, info, name):
    return _bundle_assets(_asset_inventory(remote, info), name)


def _path(name):
    path = archive.relative(name)
    if str(path) != unicodedata.normalize('NFC', str(path)) or len(name.encode()) > 4096:
        raise TransportError('noncanonical or oversized portable path')
    if any(re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p) or
           any(ord(c) == 127 for c in p) for p in path.parts):
        raise TransportError('reserved portable path component')
    return path


def _ordinary(path, directory=False):
    info = path.lstat()
    if (getattr(info, 'st_file_attributes', 0) & 0x400 or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or info.st_mode & 0o7000):
        raise TransportError('only ordinary unprivileged files and directories may be transported')
    return info


def _inventory(root, paths, allow_missing):
    root = Path(root).absolute(); _ordinary(root, True)
    names = set()
    for selected in paths:
        relative = _path(selected); current = root
        missing = False
        for index, component in enumerate(relative.parts):
            current /= component
            try: info = current.lstat()
            except FileNotFoundError:
                if allow_missing: missing = True; break
                raise
            if index + 1 < len(relative.parts): _ordinary(current, True)
        if missing: continue
        if stat.S_ISDIR(info.st_mode):
            _ordinary(current, True)
            for parent, dirs, files in os.walk(current, followlinks=False):
                for d in dirs: _ordinary(Path(parent) / d, True)
                for f in files: names.add((Path(parent) / f).relative_to(root).as_posix())
        else: names.add(relative.as_posix())
    if not names or len(names) > MAX_FILES: raise TransportError('empty or oversized bundle inventory')
    registry = archive.PathInventory(); result = {}; total = 0
    for name in sorted(names):
        _path(name); registry.add(name, False); path = root / name; info = _ordinary(path)
        total += info.st_size
        if total > MAX_BYTES: raise TransportError('bundle exceeds supported byte limit')
        result[name] = dict(size=info.st_size, mode=0o755 if info.st_mode & 0o111 else 0o644, sha256=archive.digest(path))
    return result


def _asset(row):
    return dict(id=row['id'], name=row['name'], size=row['size'], sha256=row['digest'][7:])


def _pointer(context, info, producer, row):
    value = dict(schema_version=1, **context, job_id=producer['id'], release_id=info['id'],
                 tag=info['tag_name'], manifest=_asset(row))
    if len(archive.encoded(value)) > 65536: raise TransportError('transport pointer exceeds output bound')
    return value


def _put(remote, context, info, path, expected, *, known=None):
    rows = _assets(remote, info, context['name']) if known is None else known
    row = rows.get(path.name)
    if row is None:
        remote.upload(_tag(context), path)
        row = _assets(remote, info, context['name']).get(path.name)
    if row is None or row['size'] != path.stat().st_size or row['digest'] != 'sha256:' + expected:
        raise TransportError('immutable remote asset differs; never overwrite it')
    return row


def _batch_requests(requests, required, optional):
    if not isinstance(requests, (list, tuple)) or not 1 <= len(requests) <= MAX_BUNDLES:
        raise TransportError('nonempty bounded bundle request list required')
    seen = set()
    for request in requests:
        if (not isinstance(request, dict) or not required <= set(request) or
                set(request) - required - optional or not isinstance(request.get('name'), str) or
                not NAME.fullmatch(request['name']) or request['name'] in seen):
            raise TransportError('complete distinct bundle requests required')
        seen.add(request['name'])
    return [dict(request) for request in requests]


def _parallel(operations):
    # One flattened pool: no per-bundle pools multiply the transport bound.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(operation) for operation in operations]
        return [future.result() for future in futures]


def _stage_bundle(stage, context, root, paths, *, metadata=None, allow_missing=False,
                  chunk_bytes=CHUNK_BYTES, compress=False):
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= CHUNK_BYTES:
        raise TransportError('chunk size exceeds transport policy')
    if type(compress) is not bool or type(allow_missing) is not bool:
        raise TransportError('compression and missing selections must be boolean')
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, dict) or len(archive.encoded(metadata)) > 65536:
        raise TransportError('bounded metadata object required')
    metadata = delivery.parse(archive.encoded(metadata))
    root = Path(root).absolute(); paths = list(paths); files = _inventory(root, paths, allow_missing)
    stage.mkdir(); bundle = stage / 'payload.tar'
    with ExitStack() as stack:
        stream = stack.enter_context(bundle.open('wb'))
        if compress:
            stream = stack.enter_context(gzip.GzipFile(filename='', mode='wb', fileobj=stream, compresslevel=6, mtime=0))
        output = stack.enter_context(tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT))
        for relative, item in files.items():
            header = tarfile.TarInfo(relative); header.size = item['size']; header.mode = item['mode']; header.mtime = 0
            with (root / relative).open('rb') as incoming: output.addfile(header, incoming)
    if _inventory(root, paths, allow_missing) != files: raise TransportError('input changed while staging bundle')
    whole = dict(size=bundle.stat().st_size, sha256=None, parts=[])
    if whole['size'] > MAX_BYTES + 32 * 1024**2: raise TransportError('bundle archive exceeds supported limit')
    if (whole['size'] + chunk_bytes - 1) // chunk_bytes > MAX_PARTS:
        raise TransportError('bundle needs too many bounded chunks')
    if whole['size'] <= chunk_bytes:
        # Small receipts and single-asset archives already have their final bytes.
        # Rename within the private staging directory instead of copying them.
        whole['sha256'] = archive.digest(bundle)
        part = stage / (_prefix(context['name']) + '0000-' + whole['sha256'])
        bundle.rename(part)
        return dict(context=context, stage=stage, root=root, paths=paths, files=files,
                    metadata=metadata, allow_missing=allow_missing, whole=whole,
                    chunks=[(part, whole['sha256'])])
    chunks, hasher = [], hashlib.sha256()
    with bundle.open('rb') as stream:
        index = 0
        while True:
            data = stream.read(chunk_bytes)
            if not data: break
            hasher.update(data); sha = hashlib.sha256(data).hexdigest()
            part = stage / (_prefix(context['name']) + str(index).zfill(4) + '-' + sha)
            part.write_bytes(data); chunks.append((part, sha)); index += 1
    whole['sha256'] = hasher.hexdigest()
    bundle.unlink()  # Chunks retain exact bytes; batch staging need not keep a second complete copy.
    return dict(context=context, stage=stage, root=root, paths=paths, files=files,
                metadata=metadata, allow_missing=allow_missing, whole=whole, chunks=chunks)


def publish_bundles(repository, run_id, attempt, source_commit, workflow, requests, *,
                    job_id=None, job_name=None, runner_name=None, transport=None):
    """Publish one producer's bundles with shared authoritative boundaries.

    Payload writes join before any manifest marker. All selected existing IDs and
    immutable bytes remain pinned; unrelated bundles may progress independently.
    """
    requests = _batch_requests(requests, {'name', 'root', 'paths'},
        {'metadata', 'allow_missing', 'chunk_bytes', 'compress'})
    contexts = [_context(repository, run_id, attempt, source_commit, workflow, request['name']) for request in requests]
    context = contexts[0]; remote = delivery.Remote(repository, transport); same_run = _same_run(context)
    with tempfile.TemporaryDirectory(prefix='foundation-ci-publish-') as temporary:
        work = Path(temporary)
        staged = [_stage_bundle(work / str(index), selected, **{key: value for key, value in request.items() if key != 'name'})
                  for index, (selected, request) in enumerate(zip(contexts, requests))]
        def act():
            repository_id = _run(remote, context)
            producer, _ = _producer(remote, context, job_id=job_id, job_name=job_name,
                                     runner_name=runner_name, publishing=True)
            info = _store(remote, context, repository_id, create=True)
            before = _asset_inventory(remote, info); operations = []
            for item in staged:
                rows = _bundle_assets(before, item['context']['name']); item['before'] = rows
                expected = {path.name for path, _ in item['chunks']} | {_manifest_name(item['context']['name'])}
                item['expected'] = expected
                if set(rows) - expected: raise TransportError('unexpected prior bundle assets; preserve and inspect')
                for path, sha in item['chunks']:
                    row = rows.get(path.name)
                    if row is not None:
                        if row['size'] != path.stat().st_size or row['digest'] != 'sha256:' + sha:
                            raise TransportError('immutable remote asset differs; never overwrite it')
                    else:
                        operations.append(lambda path=path: remote.upload_to(info, path))
            _parallel(operations)
            payloads = _asset_inventory(remote, info)
            for item in staged:
                rows = _bundle_assets(payloads, item['context']['name'])
                if set(rows) - item['expected'] or any(rows.get(name) != row for name, row in item['before'].items()):
                    raise TransportError('bundle assets changed before commit marker')
                for path, sha in item['chunks']:
                    row = rows.get(path.name)
                    if row is None or row['size'] != path.stat().st_size or row['digest'] != 'sha256:' + sha:
                        raise TransportError('immutable remote asset differs; never overwrite it')
                    item['whole']['parts'].append(_asset(row))
                item['manifest'] = dict(schema_version=1, **item['context'], repository_id=repository_id,
                    release_id=info['id'], producer=producer, metadata=item['metadata'],
                    files=item['files'], archive=item['whole'])
                raw = archive.encoded(item['manifest'])
                if len(raw) > MAX_MANIFEST: raise TransportError('manifest exceeds bounded inventory size')
                path = item['stage'] / _manifest_name(item['context']['name']); path.write_bytes(raw)
                item['marker'] = path; item['marker_sha'] = hashlib.sha256(raw).hexdigest()
                prior = rows.get(path.name)
                if prior is not None and (prior['size'] != len(raw) or prior['digest'] != 'sha256:' + item['marker_sha']):
                    raise TransportError('immutable remote asset differs; never overwrite it')
                if _inventory(item['root'], item['paths'], item['allow_missing']) != item['files']:
                    raise TransportError('input changed before commit marker')
            if not same_run:
                if _run(remote, context) != repository_id or _producer(remote, context, job_id=producer['id'], publishing=True)[0] != producer:
                    raise TransportError('producer identity changed before commit marker')
                if _store(remote, context, repository_id)['id'] != info['id']: raise TransportError('release changed')
            _parallel([lambda item=item: remote.upload_to(info, item['marker']) for item in staged
                       if item['marker'].name not in _bundle_assets(payloads, item['context']['name'])])
            markers = None if same_run else _asset_inventory(remote, info)
            if _store(remote, context, repository_id, release_id=info['id'] if same_run else None)['id'] != info['id']:
                raise TransportError('release changed after commit marker')
            final = _asset_inventory(remote, info)
            if markers is None: markers = final
            pointers = []
            for item in staged:
                rows = _bundle_assets(final, item['context']['name']); marker = rows.get(item['marker'].name)
                if (rows != _bundle_assets(markers, item['context']['name']) or
                        set(rows) != item['expected'] or marker is None or
                        marker['size'] != item['marker'].stat().st_size or marker['digest'] != 'sha256:' + item['marker_sha'] or
                        any(_asset(rows[part['name']]) != part for part in item['whole']['parts']) or
                        any(rows.get(name) != row for name, row in item['before'].items())):
                    raise TransportError('bundle assets changed after commit marker')
                pointers.append(_pointer(item['context'], info, producer, marker))
            return pointers
        return delivery.run_mutation(remote, act)


def publish_bundle(repository, run_id, attempt, source_commit, workflow, name, root, paths, *,
                   job_id=None, job_name=None, runner_name=None, metadata=None, allow_missing=False,
                   transport=None, chunk_bytes=CHUNK_BYTES, compress=False):
    return publish_bundles(repository, run_id, attempt, source_commit, workflow,
        [dict(name=name, root=root, paths=paths, metadata=metadata, allow_missing=allow_missing,
              chunk_bytes=chunk_bytes, compress=compress)], job_id=job_id, job_name=job_name,
        runner_name=runner_name, transport=transport)[0]


def _validate_manifest(value, context, info, repository_id):
    fields = set(context) | {'schema_version', 'repository_id', 'release_id', 'producer', 'metadata', 'files', 'archive'}
    if (not isinstance(value, dict) or set(value) != fields or type(value.get('schema_version')) is not int or value['schema_version'] != 1 or
            any(type(value.get(k)) is not type(v) or value[k] != v for k, v in context.items()) or
            not _positive(value['repository_id']) or value['repository_id'] != repository_id or
            not _positive(value['release_id']) or value['release_id'] != info['id'] or
            not isinstance(value['producer'], dict) or
            set(value['producer']) != {'id', 'name', 'runner_id', 'runner_name'} or
            not _positive(value['producer'].get('id')) or not _positive(value['producer'].get('runner_id')) or
            any(not isinstance(value['producer'].get(k), str) or not value['producer'][k] for k in ('name', 'runner_name')) or
            not isinstance(value['metadata'], dict) or len(archive.encoded(value['metadata'])) > 65536):
        raise TransportError('manifest provenance differs')
    files, bundle = value['files'], value['archive']
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise TransportError('invalid complete file inventory')
    registry = archive.PathInventory(); total = 0
    for name, item in files.items():
        _path(name); registry.add(name, False)
        if (not isinstance(item, dict) or set(item) != {'size', 'mode', 'sha256'} or
                type(item['size']) is not int or item['size'] < 0 or type(item['mode']) is not int or
                item['mode'] not in (0o644, 0o755) or not isinstance(item['sha256'], str) or not SHA.fullmatch(item['sha256'])):
            raise TransportError('invalid file identity or mode')
        total += item['size']
    if total > MAX_BYTES or not isinstance(bundle, dict) or set(bundle) != {'size', 'sha256', 'parts'}:
        raise TransportError('invalid bundle byte inventory')
    if (type(bundle['size']) is not int or not 0 < bundle['size'] <= MAX_BYTES + 32 * 1024**2 or
            not isinstance(bundle['sha256'], str) or not SHA.fullmatch(bundle['sha256']) or
            not isinstance(bundle['parts'], list) or not 1 <= len(bundle['parts']) <= MAX_PARTS):
        raise TransportError('invalid bounded archive identity')
    ids = set(); size = 0
    for index, part in enumerate(bundle['parts']):
        if (not isinstance(part, dict) or set(part) != {'id', 'name', 'size', 'sha256'} or
                not _positive(part['id']) or part['id'] in ids or type(part['size']) is not int or
                not 0 < part['size'] <= CHUNK_BYTES or not isinstance(part['sha256'], str) or
                not SHA.fullmatch(part['sha256']) or
                part['name'] != _prefix(context['name']) + str(index).zfill(4) + '-' + part['sha256']):
            raise TransportError('invalid ordered archive chunk')
        ids.add(part['id']); size += part['size']
    if size != bundle['size']: raise TransportError('archive chunk sizes do not cover complete bytes')


@contextmanager
def _tar_input(bundle, files):
    # Bound expanded bytes before tarfile parses variable-length PAX headers.
    # Names/records are already bounded by the complete authenticated manifest.
    with bundle.open('rb') as stream:
        compressed = stream.read(2) == b'\x1f\x8b'
    if not compressed:
        yield bundle
        return
    limit = sum(item['size'] for item in files.values()) + 2 * MAX_MANIFEST + len(files) * 1024 + 10240
    with tempfile.TemporaryDirectory(prefix='expanded-', dir=bundle.parent) as temporary:
        expanded = Path(temporary) / 'payload.tar'
        total = 0
        with gzip.open(bundle, 'rb') as stream, expanded.open('xb') as target:
            while True:
                data = stream.read(min(1024 * 1024, limit-total+1))
                if not data: break
                total += len(data)
                if total > limit: raise TransportError('expanded archive exceeds declared payload bound')
                target.write(data)
        yield expanded


def _extract(bundle, output, files):
    seen = set()
    with _tar_input(bundle, files) as raw, tarfile.open(raw, 'r:') as source:
        for item in source:
            _path(item.name)
            if not item.isfile() or item.sparse is not None or item.name in seen or item.name not in files:
                raise TransportError('unexpected, linked or duplicate transport member')
            expected = files[item.name]
            if item.size != expected['size'] or item.mode != expected['mode']:
                raise TransportError('transport header differs from file inventory')
            destination = output / item.name; destination.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(item) as stream, destination.open('xb') as target: shutil.copyfileobj(stream, target)
            if archive.digest(destination) != expected['sha256']: raise TransportError('transport member bytes differ')
            destination.chmod(expected['mode']); seen.add(item.name)
    if seen != set(files): raise TransportError('transport is missing declared files')


def _fetch_requests(repository, run_id, attempt, source_commit, workflow, requests):
    requests = _batch_requests(requests, {'name', 'output'},
        {'job_id', 'job_name', 'manifest_id', 'manifest_sha256', 'allow_failed'})
    contexts = [_context(repository, run_id, attempt, source_commit, workflow, request['name']) for request in requests]
    outputs = [Path(request['output']).absolute() for request in requests]
    for index, output in enumerate(outputs):
        if output.exists() or output.is_symlink(): raise TransportError('transport output must be new')
        if any(output == other or output in other.parents or other in output.parents for other in outputs[:index]):
            raise TransportError('batch outputs must be distinct without overlapping ancestors')
    for request in requests:
        mid, digest = request.get('manifest_id'), request.get('manifest_sha256')
        if ((mid is None) != (digest is None) or mid is not None and
                (not _positive(mid) or not isinstance(digest, str) or not SHA.fullmatch(digest))):
            raise TransportError('pin both manifest asset ID and SHA256')
        if type(request.get('allow_failed', False)) is not bool: raise TransportError('failure policy must be boolean')
        if request.get('job_id') is not None and not _positive(request['job_id']):
            raise TransportError('positive producer job ID required')
    return requests, contexts, outputs


def fetch_bundles(repository, run_id, attempt, source_commit, workflow, requests, *, transport=None):
    """Verify native same-run bytes; use strict relay only when explicitly selected."""
    requests, contexts, outputs = _fetch_requests(repository, run_id, attempt, source_commit, workflow, requests)
    if (_same_run(contexts[0]) and os.environ.get('FOUNDATION_CI_ARTIFACTS_REQUIRED') == 'true' and
            not os.environ.get('FOUNDATION_CI_ARTIFACTS_DIR')):
        raise TransportError('required native artifact directory is missing')
    if not os.environ.get('FOUNDATION_CI_ARTIFACTS_DIR') or not _same_run(contexts[0]):
        return _fetch_release_bundles(repository, run_id, attempt, source_commit, workflow, requests, transport=transport)
    # The helper imports archive primitives from this module; import it only at
    # the opt-in workflow boundary to keep offline/retained release use independent.
    import ci_artifacts
    with ExitStack() as stack:
        selected = []; missing = []
        for request, context, output in zip(requests, contexts, outputs):
            output.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.foundation-ci-input-', dir=output.parent))) / 'payload'
            receipt = ci_artifacts.fetch_local(context, request, stage)
            item = dict(request=request, context=context, output=output, stage=stage, receipt=receipt)
            selected.append(item)
            if receipt is None: missing.append(item)
        if missing:
            if os.environ.get('FOUNDATION_CI_ARTIFACT_RELEASE_FALLBACK') != 'true':
                raise TransportError('required native artifact is absent; release relay is not enabled')
            remote_requests = [dict(item['request'], output=item['stage']) for item in missing]
            receipts = _fetch_release_bundles(repository, run_id, attempt, source_commit, workflow,
                                             remote_requests, transport=transport)
            for item, receipt in zip(missing, receipts): item['receipt'] = receipt
        for item in selected:
            if item['output'].exists() or item['output'].is_symlink(): raise TransportError('transport output must be new')
        for item in selected: item['stage'].rename(item['output'])
        return [item['receipt'] for item in selected]


def _fetch_release_bundles(repository, run_id, attempt, source_commit, workflow, requests, *, transport=None):
    """Quarantine release bundles until their remote boundaries pass."""
    requests, contexts, outputs = _fetch_requests(repository, run_id, attempt, source_commit, workflow, requests)
    context = contexts[0]; remote = delivery.Remote(repository, transport); same_run = _same_run(context)
    repository_id = _run(remote, context); info = _store(remote, context, repository_id)
    inventory = _asset_inventory(remote, info)
    with ExitStack() as stack:
        selections = []
        for index, (request, selected, output) in enumerate(zip(requests, contexts, outputs)):
            rows = _bundle_assets(inventory, selected['name']); row = rows.get(_manifest_name(selected['name']))
            if (row is None or not 0 < row['size'] <= MAX_MANIFEST or request.get('manifest_id') is not None and
                    (row['id'] != request['manifest_id'] or row['digest'] != 'sha256:' + request['manifest_sha256'])):
                raise TransportError('complete pinned transport manifest is absent or differs')
            output.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.foundation-ci-fetch-', dir=output.parent)))
            selections.append(dict(context=selected, request=request, output=output, stage=stage, rows=rows, row=row))
        _parallel([lambda item=item: remote.download(item['row'], item['stage'] / 'manifest.json') for item in selections])
        # One complete job inventory covers every selected producer, including
        # multiple bundles from the same job. Other jobs may progress normally.
        jobs = {job['id']: job for job in _jobs(remote, context)}
        downloads = []
        for item in selections:
            manifest = delivery.parse((item['stage'] / 'manifest.json').read_bytes())
            _validate_manifest(manifest, item['context'], info, repository_id)
            request = item['request']; selected_id = manifest['producer']['id']
            if request.get('job_id') is not None and selected_id != request['job_id']:
                raise TransportError('manifest producer differs')
            producer, job = _producer(remote, context, job_id=selected_id, job_name=request.get('job_name'),
                allow_failed=request.get('allow_failed', False), observed=jobs.get(selected_id, {}))
            if producer != manifest['producer']: raise TransportError('manifest producer identity differs')
            item.update(manifest=manifest, producer=producer, job=job)
            parts = manifest['archive']['parts']; expected = {part['name'] for part in parts} | {item['row']['name']}
            if set(item['rows']) != expected or any(_asset(item['rows'][part['name']]) != part for part in parts):
                raise TransportError('remote bundle is not the complete declared asset set')
            downloads += [lambda item=item, part=part: remote.download(item['rows'][part['name']], item['stage'] / part['name'], part['sha256']) for part in parts]
        _parallel(downloads)
        for item in selections:
            manifest = item['manifest']; bundle = item['stage'] / 'payload.tar'
            parts = manifest['archive']['parts']
            if len(parts) == 1:
                (item['stage'] / parts[0]['name']).rename(bundle)
            else:
                with bundle.open('xb') as stream:
                    for part in parts:
                        path = item['stage'] / part['name']
                        with path.open('rb') as source: shutil.copyfileobj(source, stream)
                        path.unlink()
            if bundle.stat().st_size != manifest['archive']['size'] or archive.digest(bundle) != manifest['archive']['sha256']:
                raise TransportError('reconstructed archive bytes differ')
            extracted = item['stage'] / 'payload'; extracted.mkdir(); _extract(bundle, extracted, manifest['files'])
        if ((not same_run and _run(remote, context) != repository_id) or
                _store(remote, context, repository_id, release_id=info['id'] if same_run else None)['id'] != info['id']):
            raise TransportError('producer or release assets changed during fetch')
        after = _asset_inventory(remote, info)
        jobs_after = jobs if same_run else {job['id']: job for job in _jobs(remote, context)}
        for item in selections:
            if (_bundle_assets(after, item['context']['name']) != item['rows'] or
                    jobs_after.get(item['producer']['id']) != item['job']):
                raise TransportError('producer or release assets changed during fetch')
            _producer(remote, context, job_id=item['producer']['id'], allow_failed=item['request'].get('allow_failed', False),
                      observed=jobs_after.get(item['producer']['id'], {}))
            if item['output'].exists() or item['output'].is_symlink(): raise TransportError('transport output must be new')
        results = []
        for item in selections:
            (item['stage'] / 'payload').rename(item['output'])
            results.append(dict(pointer=_pointer(item['context'], info, item['producer'], item['row']),
                                manifest=item['manifest'], producer=item['job']))
        return results


def fetch_bundle(repository, run_id, attempt, source_commit, workflow, name, output, *,
                 job_id=None, job_name=None, manifest_id=None, manifest_sha256=None,
                 allow_failed=False, transport=None):
    """Fetch an exact completed producer; no automatic failed-run fallback."""
    return fetch_bundles(repository, run_id, attempt, source_commit, workflow,
        [dict(name=name, output=output, job_id=job_id, job_name=job_name, manifest_id=manifest_id,
              manifest_sha256=manifest_sha256, allow_failed=allow_failed)], transport=transport)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('publish', 'fetch'))
    for flag in ('repository', 'source-commit', 'workflow', 'name'): parser.add_argument('--' + flag, required=True)
    for flag in ('run-id', 'attempt'): parser.add_argument('--' + flag, type=int, required=True)
    parser.add_argument('--job-id', type=int); parser.add_argument('--job-name')
    parser.add_argument('--root', type=Path); parser.add_argument('--path', action='append', default=[])
    parser.add_argument('--metadata', type=Path); parser.add_argument('--pointer', type=Path)
    parser.add_argument('--compress', action='store_true', help='fast deterministic compression for text evidence')
    parser.add_argument('--allow-missing', action='store_true'); parser.add_argument('--allow-failed', action='store_true')
    parser.add_argument('--output', type=Path); parser.add_argument('--receipt', type=Path)
    parser.add_argument('--manifest-id', type=int); parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    common = dict(repository=args.repository, run_id=args.run_id, attempt=args.attempt,
                  source_commit=args.source_commit, workflow=args.workflow, name=args.name,
                  job_id=args.job_id, job_name=args.job_name)
    if args.operation == 'publish':
        if args.root is None or not args.path: parser.error('publish requires --root and --path')
        result = publish_bundle(**common, root=args.root, paths=args.path, allow_missing=args.allow_missing,
                                metadata=delivery.parse(args.metadata.read_bytes()) if args.metadata else None, compress=args.compress)
        destination = args.pointer
    else:
        if args.output is None: parser.error('fetch requires --output')
        result = fetch_bundle(**common, output=args.output, manifest_id=args.manifest_id,
                              manifest_sha256=args.manifest_sha256, allow_failed=args.allow_failed)
        destination = args.receipt
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream: stream.write(archive.encoded(result))
    print(json.dumps(result if args.operation == 'publish' else result['pointer'], sort_keys=True))


if __name__ == '__main__':
    delivery.enable_metrics()
    try: main()
    except (ValueError, OSError, delivery.DeliveryError) as error:
        raise SystemExit('ci-transport: ' + str(error) + '; preserve remote state and reconcile before retry')
