#!/usr/bin/env python3
"""Authenticate immutable earlier-attempt native handoffs before receipt adoption.

This deliberately does not change ci_artifacts' exact-current-run fast path.
Historical reads require successful remote producers, immutable artifact IDs and
ZIP digests, and the original manifest/attempt. No artifact is renamed or replaced.
"""
import datetime
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

import ci_artifacts as artifacts
import ci_plan
import ci_transport as bundles
import dependency_archive as archive
import github_release as delivery

MAX_ATTEMPTS = 64


def origin_attempt(text, current):
    if not isinstance(text, str) or not re.fullmatch(r'[1-9][0-9]*', text):
        raise ValueError('exact positive original attempt required')
    attempt = int(text)
    if not 1 <= attempt <= current <= MAX_ATTEMPTS:
        raise ValueError('original attempt must precede or equal this bounded attempt')
    return attempt


def _time(text):
    try:
        value = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
        if value.utcoffset() is None: raise ValueError('missing timezone')
        return value
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('authenticated producer timestamps required') from error


def _matches(name, suffix):
    # Reusable workflow calls prepend their calling job path. Never select merely
    # by runner name: several matrix jobs can share a self-hosted runner.
    return isinstance(name, str) and (name == suffix or name.endswith(' / ' + suffix))


def local_present(context, name, slot):
    """Absence is selection information only; fetch_local still validates bytes."""
    import os
    configured = os.environ.get(artifacts.ROOT_ENV)
    if not configured: return False
    path = Path(configured) / artifacts.artifact_name(context, slot)
    if path.is_symlink(): raise ValueError('linked artifact directory')
    return path.exists()


class EarlierAttempts:
    """One bounded request-local inventory, never a persistent provenance cache."""
    def __init__(self, context, *, transport=None, download=None):
        if context != artifacts.current_context():
            raise ValueError('retry consumer must be the exact executing Actions context')
        origin_attempt(str(context['attempt']), context['attempt'])
        self.current = dict(context)
        self.remote = delivery.Remote(context['repository'], transport)
        self.download = download or ci_plan._download_legacy_artifact
        self.observed = {}
        self.inventory = None

    def attempt(self, attempt):
        origin_attempt(str(attempt), self.current['attempt'])
        if attempt not in self.observed:
            context = dict(self.current, attempt=attempt)
            repository_id = bundles._run(self.remote, context)
            jobs = bundles._jobs(self.remote, context)
            self.observed[attempt] = context, repository_id, jobs
        return self.observed[attempt]

    def producer(self, attempt, role, batch=None):
        if role not in ('prepare', 'check', 'record') or (role == 'check') != (batch is not None):
            raise ValueError('known qualification producer role required')
        suffix = 'Qualify ' + batch if batch is not None else role
        context, _, jobs = self.attempt(attempt)
        rows = [job for job in jobs if _matches(job.get('name'), suffix)]
        if len(rows) > 1: raise ValueError('ambiguous original qualification producer')
        if not rows: return None
        producer, job = bundles._producer(self.remote, context, observed=rows[0])
        return producer, job

    def select_batch(self, batch):
        """Latest execution wins; a failed/missing current attempt cannot be hidden."""
        for attempt in range(self.current['attempt'], 0, -1):
            result = self.producer(attempt, 'check', batch)
            if result is not None:
                if attempt == self.current['attempt']:
                    raise ValueError('current batch artifact missing; earlier success cannot replace it')
                return attempt
        raise ValueError('no completed successful original batch producer')

    def artifact(self, name):
        if self.inventory is None:
            rows, total = [], None
            for page in range(1, 101):
                value = self.remote.transport.json(self.remote.base + '/actions/runs/' +
                    str(self.current['run_id']) + '/artifacts?per_page=100&page=' + str(page))
                if (type(value.get('total_count')) is not int or not 0 <= value['total_count'] <= 10000 or
                        not isinstance(value.get('artifacts'), list) or total not in (None, value['total_count'])):
                    raise ValueError('incomplete or changed retry artifact inventory')
                total = value['total_count']; rows.extend(value['artifacts'])
                if len(rows) >= total:
                    if len(rows) != total or len({item.get('id') for item in rows}) != total:
                        raise ValueError('ambiguous retry artifact inventory')
                    self.inventory = rows; break
                if not value['artifacts']: break
            if self.inventory is None: raise ValueError('retry artifact inventory exceeds supported bounds')
        rows = [item for item in self.inventory if item.get('name') == name]
        if len(rows) != 1: raise ValueError('original artifact is absent or ambiguous; rerun all jobs')
        return rows[0]

    def restore(self, attempt, name, slot, output, *, role, batch=None):
        if not 1 <= attempt < self.current['attempt']:
            raise ValueError('historical retrieval requires an earlier attempt')
        selected = self.producer(attempt, role, batch)
        if selected is None: raise ValueError('original producer is absent')
        producer, job = selected
        context, repository_id, _ = self.attempt(attempt)
        context = dict(context, name=name)
        bundles._context(**context)
        artifact_name = artifacts.artifact_name(context, slot)
        row = self.artifact(artifact_name); run = row.get('workflow_run', {})
        limit = artifacts.SLOT_BUDGETS[slot] + artifacts.MIB  # ZIP envelope overhead.
        if (not bundles._positive(row.get('id')) or row.get('expired') is not False or
                type(row.get('size_in_bytes')) is not int or not 0 < row['size_in_bytes'] <= limit or
                not isinstance(row.get('digest'), str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', row['digest']) or
                run.get('id') != context['run_id'] or run.get('head_sha') != context['source_commit'] or
                run.get('repository_id') != repository_id or run.get('head_repository_id') != repository_id or
                not _time(job['started_at']) <= _time(row.get('created_at')) <= _time(job['completed_at'])):
            raise ValueError('original artifact immutable identity or producer differs')
        output = Path(output).absolute()
        for parent in (output, *output.parents): ci_plan._bundle_directory(parent)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.prior-evidence-', dir=output.parent) as temporary:
            root = Path(temporary); zipped = root / 'artifact.zip'
            self.download(context['repository'], row['id'], zipped)
            if zipped.stat().st_size != row['size_in_bytes'] or archive.digest(zipped) != row['digest'][7:]:
                raise ValueError('original artifact ZIP bytes differ')
            members = ci_plan._retained_zip(zipped, max_bytes=artifacts.SLOT_BUDGETS[slot])
            if set(members) != {'manifest.json', 'payload.tar.gz'}:
                raise ValueError('original artifact must contain only its manifest and archive')
            if members['manifest.json'].file_size > artifacts.MAX_MANIFEST_BYTES:
                raise ValueError('original artifact manifest exceeds bound')
            with zipfile.ZipFile(zipped) as source:
                encoded = source.read(members['manifest.json'])
                manifest = delivery.parse(encoded)
                artifacts._validate(manifest, context, artifact_name)
                if manifest['producer'] != dict(job_key=role, runner_name=producer['runner_name'], outcome='success'):
                    raise ValueError('artifact executing producer differs from authenticated job')
                payload = root / 'payload.tar.gz'
                with source.open(members['payload.tar.gz']) as incoming, payload.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
            if payload.stat().st_size != manifest['archive']['size'] or archive.digest(payload) != manifest['archive']['sha256']:
                raise ValueError('original archive bytes differ')
            stage = root / 'files'; stage.mkdir()
            bundles._extract(payload, stage, manifest['files'])
            # Reconcile immutable object and actual completed producer before any
            # bytes leave this private verification stage.
            if self.remote.transport.json(self.remote.base + '/actions/artifacts/' + str(row['id'])) != row:
                raise ValueError('original artifact identity changed during retrieval')
            if bundles._run(self.remote, context) != repository_id:
                raise ValueError('original repository changed during retrieval')
            final, final_job = bundles._producer(self.remote, context, job_id=producer['id'])
            if final != producer or final_job != job:
                raise ValueError('original producer changed during retrieval')
            for relative in manifest['files']:
                target = output / archive.relative(relative)
                if target.exists() or target.is_symlink(): raise ValueError('retry restore refuses existing file: ' + relative)
                for parent in target.parents: ci_plan._bundle_directory(parent)
            for relative, info in manifest['files'].items():
                target = output / archive.relative(relative); target.parent.mkdir(parents=True, exist_ok=True)
                with (stage / relative).open('rb') as incoming, target.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(info['mode'])
        return dict(schema_version=1, transport='authenticated-earlier-actions-attempt', **context,
                    repository_id=repository_id, artifact=dict(id=row['id'], name=row['name'], sha256=row['digest'][7:]),
                    manifest_sha256=delivery.sha(encoded), producer=producer)
