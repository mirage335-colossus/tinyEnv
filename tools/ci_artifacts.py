#!/usr/bin/env python3
"""Bounded native Actions handoffs, without redundant same-run REST queries.

Trust comes from the executing Actions run, immutable artifact names and explicit
workflow needs. Byte/context validation is independent of qualification results.
Legacy release transport is available only when deliberately selected.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

import ci_transport as bundles
import dependency_archive as archive
import github_release as delivery

MIB = 1024 * 1024
MAX_BUNDLE_BYTES = 3 * MIB  # Check evidence; small receipt slots remain 2 MiB.
MAX_MANIFEST_BYTES = 4 * MIB
MAX_EXPANDED_BYTES = 512 * MIB
MAX_FILES = bundles.MAX_FILES
MAX_EVIDENCE_SLOTS = 48
TARGETS = ('linux-x86_64', 'linux-aarch64', 'windows-x86_64')
APPLICATION_TARGETS = TARGETS + ('browser-wasm32',)
SCOPES = ('core', 'tools', 'integration')
CONTROLS = ('qualification-inputs', 'certificate', 'certification-delivery',
            'candidate-coverage', 'apt-mechanism')
SLOT_BUDGETS = {('source-' + target + '-' + scope): 2 * MIB for target in TARGETS for scope in SCOPES}
SLOT_BUDGETS.update({name: 2 * MIB for name in CONTROLS})
SLOT_BUDGETS.update({'certificate': 40 * MIB, 'source': 40 * MIB, 'candidate': 64 * MIB,
                     'candidate-delivery': 2 * MIB, 'latest-verification': 2 * MIB,
                     'promotion-inputs': 2 * MIB, 'promotion-delivery': 2 * MIB})
SLOT_BUDGETS.update({'application-' + target: 16 * MIB for target in APPLICATION_TARGETS})
SLOT_BUDGETS.update({'application-' + target: 20 * MIB for target in TARGETS if target.startswith('linux-')})
SLOT_BUDGETS.update({'application-evidence-' + target: 8 * MIB for target in APPLICATION_TARGETS})
SLOT_BUDGETS.update({'package-' + target: 16 * MIB for target in TARGETS})
FIXED_SLOTS = tuple(SLOT_BUDGETS)
SLOT_BUDGETS.update({'evidence-' + str(index).zfill(2): MAX_BUNDLE_BYTES for index in range(MAX_EVIDENCE_SLOTS)})
SLOTS = tuple(SLOT_BUDGETS)
MAX_ARTIFACTS = len(SLOTS)
MAX_RUN_BYTES = sum(SLOT_BUDGETS.values())
ROOT_ENV = 'FOUNDATION_CI_ARTIFACTS_DIR'
REQUIRED_ENV = 'FOUNDATION_CI_ARTIFACTS_REQUIRED'
FALLBACK_ENV = 'FOUNDATION_CI_ARTIFACT_RELEASE_FALLBACK'
TRUST_BASIS = 'same-run-actions-context-and-workflow-needs'


def _fallback(reason, allowed):
    if allowed: return dict(transport='release', reason=reason)
    _error(reason + '; native artifact publication failed; release fallback requires explicit opt-in')


def _sdk_payload(name):
    leaf = Path(name).name.casefold()
    return leaf.startswith('sdk-') and leaf.endswith(('.tar.gz', '.tar.xz', '.tar.zst', '.tgz', '.zip'))



def _error(message):
    raise bundles.TransportError(message)


def _directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        _error('artifact paths require ordinary directories without links')


def _parents(path):
    for current in (path, *path.parents):
        try: _directory(current)
        except FileNotFoundError: pass


def slot_for(name, attempt, index=None):
    """Finite immutable names bound storage even when the check matrix grows."""
    suffix = '-' + str(attempt)
    if not name.endswith(suffix): return None
    label = name[:-len(suffix)]
    if label in FIXED_SLOTS: return label
    if re.fullmatch(r'evidence-batch-[a-z0-9_-]+', label):
        if type(index) is int and 0 <= index < MAX_EVIDENCE_SLOTS:
            return 'evidence-' + str(index).zfill(2)
    return None


def artifact_name(context, slot):
    if slot not in SLOTS: _error('unknown bounded artifact slot')
    return f"foundation-evidence-{context['run_id']}-{context['attempt']}-{slot}"


def current_context():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        _error('native artifacts require the executing Actions context')
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    reference = os.environ.get('GITHUB_WORKFLOW_REF', '')
    prefix = repository + '/.github/workflows/'
    if not reference.startswith(prefix) or '@' not in reference[len(prefix):]:
        _error('artifact context requires the exact current workflow reference')
    try:
        value = dict(repository=repository, run_id=int(os.environ['GITHUB_RUN_ID']),
                     attempt=int(os.environ['GITHUB_RUN_ATTEMPT']), source_commit=os.environ['GITHUB_SHA'],
                     workflow=reference[len(prefix):].split('@', 1)[0])
    except (KeyError, ValueError): _error('artifact context requires the exact current workflow run')
    bundles._context(**value, name='context')
    return value


def prepare(repository, run_id, attempt, source_commit, workflow, name, root, paths, output, *,
            slot=None, metadata=None, job_key=None, runner_name=None, outcome='success',
            allow_missing=False, allow_release_fallback=False):
    """Stage a complete bounded handoff, with no truncation or automatic relay."""
    context = bundles._context(repository, run_id, attempt, source_commit, workflow, name)
    selected = slot_for(name, attempt, slot)
    if type(allow_release_fallback) is not bool: _error('fallback policy must be boolean')
    if selected is None: return _fallback('outside finite artifact slots', allow_release_fallback)
    budget = SLOT_BUDGETS[selected]
    if not isinstance(runner_name, str) or not runner_name or len(runner_name) > 1024:
        _error('artifact producer requires its exact runner name')
    if not isinstance(job_key, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]{0,99}', job_key):
        _error('artifact producer requires its executing workflow job key')
    if outcome not in ('success', 'failure', 'cancelled'): _error('invalid producer outcome')
    files = bundles._inventory(root, paths, allow_missing)
    if any(_sdk_payload(name) for name in files):
        return _fallback('SDK payloads belong in release storage', allow_release_fallback)
    if len(files) > MAX_FILES or sum(item['size'] for item in files.values()) > MAX_EXPANDED_BYTES:
        return _fallback('handoff exceeds expanded byte or file budget', allow_release_fallback)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): _error('artifact staging output must be new')
    _parents(output.parent); output.parent.mkdir(parents=True, exist_ok=True)
    staged = bundles._stage_bundle(output, context, root, paths, metadata=metadata,
                                  allow_missing=allow_missing, compress=True)
    if len(staged['chunks']) != 1: _error('bounded evidence unexpectedly produced multiple parts')
    payload = output / 'payload.tar.gz'
    staged['chunks'][0][0].rename(payload)
    manifest = dict(schema_version=2, kind='actions-ci-evidence', **context, slot=selected,
                    trust_basis=TRUST_BASIS, producer=dict(job_key=job_key, runner_name=runner_name, outcome=outcome),
                    metadata=staged['metadata'],
                    files=staged['files'], archive={key: staged['whole'][key] for key in ('size', 'sha256')})
    encoded = archive.encoded(manifest)
    payload_bytes = payload.stat().st_size
    complete_bytes = len(encoded) + payload_bytes
    if len(encoded) > MAX_MANIFEST_BYTES or complete_bytes > budget:
        shutil.rmtree(output)
        return _fallback('complete compressed handoff exceeds artifact byte budget '
                         f'(slot={selected}, total_bytes={complete_bytes}, slot_budget_bytes={budget}, '
                         f'archive_bytes={payload_bytes}, manifest_bytes={len(encoded)}, '
                         f'manifest_budget_bytes={MAX_MANIFEST_BYTES})', allow_release_fallback)
    with (output / 'manifest.json').open('xb') as stream: stream.write(encoded)
    return dict(transport='actions', artifact_name=artifact_name(context, selected), path=str(output),
                bytes=complete_bytes, manifest_sha256=archive.digest(output / 'manifest.json'))


def _validate(value, context, directory_name):
    fields = set(context) | {'schema_version', 'kind', 'slot', 'trust_basis', 'producer', 'metadata', 'files', 'archive'}
    if (not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or
            value['schema_version'] != 2 or value['kind'] != 'actions-ci-evidence' or value['trust_basis'] != TRUST_BASIS or
            any(type(value.get(key)) is not type(expected) or value[key] != expected for key, expected in context.items())):
        _error('artifact manifest provenance differs')
    slot = value['slot']
    index = int(slot[-2:]) if isinstance(slot, str) and re.fullmatch(r'evidence-[0-9]{2}', slot) else None
    if slot_for(context['name'], context['attempt'], index) != slot or directory_name != artifact_name(context, slot):
        _error('artifact name or fixed slot differs')
    producer = value['producer']
    if (not isinstance(producer, dict) or set(producer) != {'job_key', 'runner_name', 'outcome'} or
            not isinstance(producer['runner_name'], str) or not 0 < len(producer['runner_name']) <= 1024 or
            not isinstance(producer['job_key'], str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]{0,99}', producer['job_key']) or
            producer['outcome'] not in ('success', 'failure', 'cancelled')):
        _error('artifact executing-job descriptor differs')
    if not isinstance(value['metadata'], dict) or len(archive.encoded(value['metadata'])) > MAX_MANIFEST_BYTES:
        _error('artifact metadata must be a bounded object')
    files = value['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES: _error('artifact file inventory is invalid')
    registry = archive.PathInventory(); total = 0
    for name, item in files.items():
        bundles._path(name); registry.add(name, False)
        if _sdk_payload(name): _error('SDK payloads are excluded from native artifacts')
        if (not isinstance(item, dict) or set(item) != {'size', 'mode', 'sha256'} or
                type(item['size']) is not int or item['size'] < 0 or type(item['mode']) is not int or
                item['mode'] not in (0o644, 0o755) or not isinstance(item['sha256'], str) or
                not bundles.SHA.fullmatch(item['sha256'])):
            _error('artifact file identity differs')
        total += item['size']
    package = value['archive']
    if (total > MAX_EXPANDED_BYTES or not isinstance(package, dict) or set(package) != {'size', 'sha256'} or
            type(package['size']) is not int or not 0 < package['size'] <= SLOT_BUDGETS[slot] or
            not isinstance(package['sha256'], str) or not bundles.SHA.fullmatch(package['sha256'])):
        _error('artifact archive identity or expanded size differs')


def fetch_local(context, request, output_stage):
    """Return validated local bytes, or None only when the exact bundle is absent.

    The caller must be executing this exact Actions run and have workflow needs
    gating. No REST job inventory is implied by the returned provenance record.
    """
    configured = os.environ.get(ROOT_ENV)
    if not configured:
        if os.environ.get(REQUIRED_ENV) == 'true': _error('native artifact download directory is missing')
        return None
    expected = bundles._context(**{key: context[key] for key in ('repository', 'run_id', 'attempt', 'source_commit', 'workflow')},
                                name=request['name'])
    if current_context() != {key: value for key, value in expected.items() if key != 'name'}:
        _error('local artifacts may only satisfy their exact current run and workflow')
    root = Path(configured).absolute(); _parents(root)
    if not root.exists():
        if os.environ.get(FALLBACK_ENV) == 'true': return None
        _error('required native artifact download directory is absent')
    entries = sorted(root.iterdir())
    if len(entries) > MAX_ARTIFACTS: _error('artifact inventory exceeds finite storage slots')
    found = None; selected_manifest = None; selected_bytes = None; names = set()
    prefix = f"foundation-evidence-{expected['run_id']}-{expected['attempt']}-"
    for directory in entries:
        _directory(directory)
        if not directory.name.startswith(prefix) or directory.name[len(prefix):] not in SLOTS:
            _error('unexpected same-run artifact directory')
        if {path.name for path in directory.iterdir()} != {'manifest.json', 'payload.tar.gz'}:
            _error('artifact must contain only its manifest and complete archive')
        manifest_path = directory / 'manifest.json'; info = bundles._ordinary(manifest_path)
        payload_info = bundles._ordinary(directory / 'payload.tar.gz')
        if not 0 < info.st_size <= MAX_MANIFEST_BYTES or info.st_size + payload_info.st_size > SLOT_BUDGETS[directory.name[len(prefix):]]:
            _error('artifact exceeds stored byte budget')
        data = manifest_path.read_bytes(); manifest = delivery.parse(data)
        if not isinstance(manifest, dict) or not isinstance(manifest.get('name'), str): _error('artifact name is absent')
        selected = dict(expected, name=manifest['name'])
        bundles._context(**selected); _validate(manifest, selected, directory.name)
        if manifest['name'] in names: _error('duplicate artifact bundle name')
        names.add(manifest['name'])
        if manifest['name'] == expected['name']:
            found, selected_manifest, selected_bytes = directory, manifest, data
    if found is None:
        if os.environ.get(FALLBACK_ENV) == 'true': return None
        _error('required native artifact is absent: ' + expected['name'])
    if request.get('manifest_id') is not None or request.get('manifest_sha256') is not None:
        _error('release asset pins cannot be satisfied by an Actions artifact')
    if request.get('job_name') is not None or request.get('job_id') is not None:
        _error('REST producer pins require legacy release verification')
    if type(request.get('allow_failed', False)) is not bool: _error('failure policy must be boolean')
    producer = selected_manifest['producer']
    if producer['outcome'] != 'success' and not request.get('allow_failed', False):
        _error('failed native producer requires an explicit evidence-only consumer')
    payload = found / 'payload.tar.gz'; package = selected_manifest['archive']
    if payload.stat().st_size != package['size'] or archive.digest(payload) != package['sha256']:
        _error('artifact archive bytes differ')
    output_stage = Path(output_stage).absolute()
    if output_stage.exists() or output_stage.is_symlink(): _error('artifact extraction output must be new')
    _parents(output_stage.parent); output_stage.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.artifact-check-', dir=output_stage.parent) as temporary:
        stage = Path(temporary) / 'payload'; stage.mkdir()
        bundles._extract(payload, stage, selected_manifest['files'])
        # Catch replacement during extraction; the whole hash and per-file hashes
        # are independently checked before any bytes leave the private stage.
        if (found / 'manifest.json').read_bytes() != selected_bytes or archive.digest(payload) != package['sha256']:
            _error('artifact changed during verification')
        if output_stage.exists() or output_stage.is_symlink(): _error('artifact extraction output must be new')
        stage.rename(output_stage)
    pointer = dict(schema_version=2, transport='actions', trust_basis=TRUST_BASIS, **expected, artifact_name=found.name,
                   manifest_sha256=archive.digest(found / 'manifest.json'))
    return dict(pointer=pointer, manifest=selected_manifest, producer=dict(kind='workflow-needs',
                trust_basis=TRUST_BASIS, job_key=producer['job_key'], runner_name=producer['runner_name'],
                conclusion=producer['outcome']))


def _lifecycle():
    path = Path(__file__).resolve().parents[1] / '.github/scripts/lifecycle.py'
    spec = importlib.util.spec_from_file_location('foundation_artifact_lifecycle', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _output(name, value):
    if any(c in str(value) for c in '\r\n'): _error('workflow outputs require single lines')
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
        stream.write(name + '=' + str(value) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'fallback'))
    args = parser.parse_args(argv)
    lifecycle = _lifecycle()
    if args.operation == 'fallback':
        if os.environ.get(FALLBACK_ENV) != 'true': _error('release fallback is not enabled')
        # Retain every original selected file if size or service quota prevented
        # the Actions upload. Release transport keeps its immutable validation.
        lifecycle.store_bundle()
        return
    context = current_context(); name = os.environ['BUNDLE_NAME']; slot = os.environ.get('ARTIFACT_SLOT', '')
    if slot and not slot.isdecimal(): _error('artifact slot must be a nonnegative matrix index')
    root, paths = lifecycle.bundle_inputs(os.environ['BUNDLE_PATHS'])
    destination = Path(os.environ['RUNNER_TEMP']) / ('foundation-evidence-stage-' + name)
    allowed = os.environ.get(FALLBACK_ENV, 'false')
    if allowed not in ('true', 'false'): _error('release fallback policy must be true or false')
    if os.environ.get('GITHUB_SERVER_URL', 'https://github.com') != 'https://github.com':
        result = _fallback('native artifact v4 requires GitHub.com', allowed == 'true')
    else:
        result = prepare(**context, name=name, root=root, paths=paths, output=destination,
                         slot=int(slot) if slot else None, runner_name=os.environ.get('RUNNER_NAME'),
                         job_key=os.environ.get('GITHUB_JOB'), outcome=os.environ.get('ARTIFACT_PRODUCER_STATUS', ''),
                         allow_release_fallback=allowed == 'true')
    for key in ('transport', 'artifact_name', 'path'):
        _output(key.replace('_', '-'), result.get(key, ''))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    delivery.enable_metrics()
    try: main()
    except (ValueError, OSError, delivery.DeliveryError) as error:
        raise SystemExit('ci-artifacts: ' + str(error))
