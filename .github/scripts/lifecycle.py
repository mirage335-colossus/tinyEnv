#!/usr/bin/env python3
"""Thin hosted adapters; substantive byte and lifecycle checks live in tools/."""
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ci_plan as ci
import github_release as delivery
import dependency_store
import coverage as evidence
import qualification_tasks
import ci_retry
import build_capacity
from process_tree import ProcessTreeError


def retained_graphics(url, archive):
    """Read an exact private own-repository asset or an explicit HTTPS mirror."""
    from urllib.parse import urlsplit
    import windows_graphics
    parsed = urlsplit(url)
    if parsed.hostname != 'api.github.com':
        return windows_graphics.fetch_retained(url, archive)
    repository = delivery.location(value('GITHUB_REPOSITORY'))
    prefix = '/repos/'+repository+'/releases/assets/'
    if (parsed.scheme != 'https' or parsed.netloc != 'api.github.com' or parsed.query or parsed.fragment or
            not parsed.path.startswith(prefix) or not parsed.path[len(prefix):].isdigit() or
            int(parsed.path[len(prefix):]) < 1):
        raise ValueError('private graphics asset must belong to this repository')
    remote = delivery.Remote(repository)
    row = remote.transport.json(parsed.path.lstrip('/'))
    expected = windows_graphics.lock()['archive']
    if (row.get('id') != int(parsed.path[len(prefix):]) or row.get('name') != expected['name'] or
            row.get('state') != 'uploaded' or row.get('size') != expected['size'] or
            row.get('digest') != 'sha256:'+expected['sha256']):
        raise ValueError('private graphics asset differs from locked archive')
    if archive.exists() or archive.is_symlink():
        receipt = windows_graphics.verify_archive(archive)
    else:
        # A failed transfer remains an invalid input, never a supplier fallback.
        remote.download(row, archive, expected['sha256'])
        receipt = windows_graphics.verify_archive(archive)
    receipt['acquisition'] = 'private-repository-retention'
    receipt['asset_id'] = row['id']
    return receipt


def value(name):
    text = os.environ.get(name, '')
    if not text: raise ValueError('missing workflow input: ' + name)
    return text


def boolean(name):
    item = value(name)
    if item not in ('true', 'false'): raise ValueError('invalid boolean: ' + name)
    return item == 'true'


def write(path, item):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_new(path, item)


def output(name, item):
    with Path(value('GITHUB_OUTPUT')).open('a', encoding='utf-8') as stream:
        stream.write(name + '=' + json.dumps(item, separators=(',', ':')) + '\n')


def scalar_output(name, item):
    text = str(item).lower() if isinstance(item, bool) else str(item)
    if any(c in text for c in '\r\n'): raise ValueError('workflow output must occupy one line')
    with Path(value('GITHUB_OUTPUT')).open('a', encoding='utf-8') as stream:
        stream.write(name + '=' + text + '\n')


def storage_context():
    # Reusable jobs belong to their caller's exact run, not a new callee run.
    reference = value('GITHUB_WORKFLOW_REF')
    prefix = value('GITHUB_REPOSITORY') + '/.github/workflows/'
    if not reference.startswith(prefix) or '@' not in reference[len(prefix):]:
        raise ValueError('workflow reference does not belong to this repository')
    filename = reference[len(prefix):].split('@', 1)[0]
    if not ci.re.fullmatch(r'[a-zA-Z0-9_-]+\.ya?ml', filename):
        raise ValueError('invalid workflow identity')
    return dict(repository=value('GITHUB_REPOSITORY'), run_id=int(value('GITHUB_RUN_ID')),
        attempt=int(value('GITHUB_RUN_ATTEMPT')), source_commit=value('GITHUB_SHA'), workflow=filename)


def bundle_inputs(specification):
    """Preserve the selected common-root layout, with no implicit entire-tree upload."""
    import glob
    declarations = [line.strip() for line in specification.splitlines() if line.strip()]
    if not declarations or len(declarations) > 100 or len(specification) > 65536:
        raise ValueError('bounded explicit bundle paths required')
    bases, matches = [], set()
    for text in declarations:
        path = Path(text)
        if path.is_absolute() or '..' in path.parts or '\\' in text or ':' in text:
            raise ValueError('bundle path must be relative to the checkout')
        prefix = []
        for part in path.parts:
            if glob.has_magic(part): break
            prefix.append(part)
        base = Path(*prefix)
        if len(prefix) == len(path.parts) and not (ROOT/base).is_dir(): base=base.parent
        bases.append(ROOT/base)
        matches.update(Path(item).absolute() for item in glob.glob(str(ROOT/path), recursive=True))
    base = Path(os.path.commonpath(bases))
    if base != ROOT and ROOT not in base.parents: raise ValueError('bundle root escaped checkout')
    if base in matches:
        matches.remove(base); matches.update(base.iterdir())
    return base, sorted(str(path.relative_to(base)).replace('\\','/') for path in matches)


def store_bundle():
    import ci_transport
    base, paths = bundle_inputs(value('BUNDLE_PATHS'))
    if not paths: raise ValueError('bundle selection contains no files')
    name=value('BUNDLE_NAME')
    text_bundle = name.startswith(('evidence-', 'source-linux-', 'source-windows-', 'qualification-inputs-', 'candidate-coverage-', 'certificate-', 'browser-prerequisite-', 'application-evidence-', 'native-gui-evidence-', 'certification-delivery-', 'candidate-delivery-')) or name.endswith(('-diagnostics', '-publication'))
    pointer=ci_transport.publish_bundle(**storage_context(), name=name, root=base, paths=paths,
        runner_name=value('RUNNER_NAME'), compress=text_bundle)
    write(ROOT/'build/transport-pointers'/ (name+'.json'), pointer)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(value('GITHUB_STEP_SUMMARY')).open('a',encoding='utf-8') as stream:
            stream.write('Verified CI bundle pointer: `'+json.dumps(pointer,sort_keys=True)+'`\n')
    if os.environ.get('GITHUB_OUTPUT'): output('bundle_pointer',pointer)


def fetch_bundle(name, output, *, allow_failed=False):
    result=ci.restore_run_bundle(**storage_context(), name=name, output=Path(output), allow_failed=allow_failed)
    write(ROOT/'build/transport-receipts'/(name+'.json'),result)
    return result


def fetch_bundles(requests):
    if len(requests) == 1:
        request = requests[0]
        return [fetch_bundle(request['name'], request['output'], allow_failed=request.get('allow_failed', False))]
    results = ci.restore_run_bundles(**storage_context(), requests=requests)
    for request, result in zip(requests, results):
        write(ROOT/'build/transport-receipts'/(request['name']+'.json'),result)
    return results


def sdk_recipe(target, profile):
    if profile not in ('core', 'all-gui'): raise ValueError('unknown SDK capability profile')
    if profile == 'all-gui' and target.startswith('linux-'):
        return ROOT / ('third_party/sdk/gui-aarch64/recipe.json' if target.endswith('aarch64') else 'third_party/sdk/gui-x86_64/recipe.json')
    if profile == 'all-gui' and target == 'windows-x86_64':
        return ROOT / 'third_party/sdk/windows-gui/windows-base.json'
    if target.startswith('linux-'):
        return ROOT / ('third_party/sdk/aarch64/recipe.json' if target.endswith('aarch64') else 'third_party/sdk/recipe.json')
    return ROOT / ('third_party/sdk/windows-base.json' if target.startswith('windows-') else 'third_party/sdk/wasm.json')


def sdk_identity(target, profile):
    if target not in (*ci.STANDARD, 'browser-wasm32'):
        raise ValueError('unknown SDK target')
    recipe = sdk_recipe(target, profile)
    if target.startswith('linux-'):
        import distro_sdk
        return distro_sdk.recipe_id(recipe)
    if target == 'windows-x86_64':
        import sdk_windows
        return sdk_windows.recipe_identity(recipe)
    import sdk_wasm
    return sdk_wasm.recipe_identity(recipe)


def ordinary_directory(path):
    """Do not follow links or Windows reparse points in an owned directory."""
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
        raise ValueError('SDK isolation requires ordinary directories: ' + str(path))
    return info.st_dev, info.st_ino


def absent(path):
    try: path.lstat()
    except FileNotFoundError: return True
    return False


@contextmanager
def isolated_sdk_producer(target, profile, recipe, origin, files, *,
                          input_name='sdk-inputs', receipt_name='sdk-isolation.json'):
    """Exclude original producer paths during all synchronous consumer work.

    The caller owns this build tree exclusively and must stop producer writers
    first. This is relocation qualification, not a hostile-process sandbox.
    Never delete or overwrite an unexpected entry during recovery.
    """
    if input_name not in ('sdk-inputs', 'rust-sdk-inputs') or receipt_name not in ('sdk-isolation.json', 'rust-sdk-isolation.json'):
        raise ValueError('unknown isolated SDK producer tree')
    parent = ROOT / 'build'; original = parent / input_name
    receipt_path = parent / receipt_name
    if not absent(receipt_path): raise FileExistsError('SDK isolation receipt must be new')
    parent_id = ordinary_directory(parent)
    receipt = dict(schema_version=1, status='started', target=target, profile=profile,
        recipe_id=recipe, group_files=files, origin=origin,
        source_commit=value('GITHUB_SHA'), run_id=value('GITHUB_RUN_ID'),
        attempt=int(value('GITHUB_RUN_ATTEMPT')), original=str(original),
        initial_state='unchecked', quarantine=None, disposition='unchanged',
        checkpoints=[], consumers='not-completed')
    holder = moved = original_id = holder_id = failure = None

    def check_absent(label):
        if ordinary_directory(parent) != parent_id:
            raise ValueError('SDK isolation parent identity changed; preserve trees')
        if not absent(original):
            raise ValueError('SDK producer path was recreated; preserve both trees')
        if moved is not None and (ordinary_directory(holder) != holder_id or
                                  ordinary_directory(moved) != original_id):
            raise ValueError('SDK quarantine identity changed; preserve trees')
        receipt['checkpoints'].append(label)

    try:
        if absent(original):
            receipt['initial_state'] = 'absent'
        else:
            original_id = ordinary_directory(original)
            receipt['initial_state'] = 'present'
            holder = Path(tempfile.mkdtemp(prefix='sdk-producer-quarantine-', dir=parent))
            holder_id = ordinary_directory(holder); moved = holder / input_name
            receipt['quarantine'] = str(moved)
            receipt['disposition'] = 'preserved'
            # The private holder is new. Any rename error has an unknown outcome;
            # retain both spellings for explicit inspection instead of retrying.
            original.rename(moved)
        check_absent('before-install-and-core')
        yield check_absent
        check_absent('after-all-consumers')
        receipt['consumers'] = 'completed'
        if moved is not None:
            moved.rename(original)
            if (ordinary_directory(parent) != parent_id or ordinary_directory(original) != original_id or
                    not absent(moved) or ordinary_directory(holder) != holder_id):
                raise ValueError('SDK restoration identity differs; preserve trees')
            holder.rmdir()  # Only the exact now-empty owned holder may be removed.
            receipt['disposition'] = 'restored'
        else:
            receipt['disposition'] = 'remained-absent'
        receipt['status'] = 'passed'
    except BaseException as error:
        failure = error
        receipt['status'] = 'failed'
        receipt['error_type'] = type(error).__name__
        # Incomplete consumers or uncertain filesystem operations never trigger
        # restoration, recursive deletion, success receipts or publication.
        raise
    finally:
        try:
            if ordinary_directory(parent) != parent_id:
                raise ValueError('SDK isolation parent changed; preserve trees and receipt destination')
            write(receipt_path, receipt)
        except BaseException as publication_error:
            if failure is not None: raise publication_error from failure
            raise


def retain_sdk_group(target, profile):
    """Retain checked bytes for diagnosis/retry, without consumer approval."""
    identity = sdk_identity(target, profile)
    origin = evidence.load(ROOT / 'build/sdk-origin.json')
    if origin.get('recipe') != identity:
        raise ValueError('retained SDK identity differs from the selected current recipe')
    files = dependency_store.verify_group(ROOT / 'build/sdk-group', identity)
    receipt = dict(schema_version=1, status='verified', qualification='unqualified',
        publication_approved=False, target=target, profile=profile, recipe_id=identity,
        source_commit=value('GITHUB_SHA'), run_id=value('GITHUB_RUN_ID'),
        attempt=int(value('GITHUB_RUN_ATTEMPT')), files=files)
    write(ROOT / 'build/sdk-retention.json', receipt)
    return receipt


def retained_request(target, profile, *, producer_host=False):
    raw = os.environ.get('SDK_RETAINED_INPUT', '')
    if value('SDK_SOURCE') != 'retained':
        if raw.strip(): raise ValueError('retained SDK input requires explicit source=retained')
        return None
    if len(raw.encode('utf-8')) > 16384: raise ValueError('retained SDK input exceeds supported size')
    request = delivery.parse(raw)
    # Planning runs on Linux for every target; enforce recipe bytes on the selected producer host.
    identity = sdk_identity(target, profile) if producer_host else request.get('recipe_id') if isinstance(request, dict) else None
    return ci.retained_sdk_request(request, value('GITHUB_REPOSITORY'), target, profile, identity)


def selected_runners():
    return ci.runner_selection(os.environ.get('LINUX_POOL', 'standard'),
        os.environ.get('FOUNDATION_FASTER_LINUX_RUNNER', ''), os.environ.get('FOUNDATION_FASTER_ARM_RUNNER', ''),
        os.environ.get('FOUNDATION_FASTER_WINDOWS_RUNNER', ''))


def core_provider():
    provider = os.environ.get('CORE_PROVIDER', 'rust')
    if provider not in ('rust', 'cpp'):
        raise ValueError('unknown core provider')
    return provider


def rust_input(target):
    if core_provider() == 'cpp':
        if os.environ.get('FOUNDATION_PROVIDER_RECIPE', ''):
            raise ValueError('C++ selection must omit Rust SDK inputs')
        return dict(core_provider='cpp')
    recipe = ci.rust_recipe(target)
    if os.environ.get('FOUNDATION_PROVIDER_RECIPE', recipe) != recipe:
        raise ValueError('workflow Rust recipe differs from exact checked-in target inputs')
    return dict(core_provider='rust', rust_recipe=recipe, rust_group=ROOT / 'build/rust-base' / recipe)


def prepare_rust_maintenance(target):
    import rust_sdk
    recipe = ROOT / ci.RUST_RECIPES[target]
    identity = ci.rust_recipe(target)
    cpp_sdk = None
    if target == 'browser-wasm32':
        cpp_identity = sdk_identity(target, value('SDK_PROFILE'))
        if rust_sdk.checked_recipe(recipe)['cpp_sdk_recipe_id'] != cpp_identity:
            raise ValueError('Rust maintenance requires its exact matched C++ SDK recipe')
        cpp_sdk = ROOT / 'build/rust-paired-sdk'
        ci.module('sdk').install(ROOT / 'build/sdk-group', cpp_identity, cpp_sdk, production=True)
    # This named maintenance operation is the explicit supplier-acquisition boundary.
    rust_sdk.fetch(recipe, ROOT / 'build/rust-sdk-inputs', network=True)
    rust_sdk.prepare(recipe, ROOT / 'build/rust-sdk-inputs', ROOT / 'build/rust-sdk-group', cpp_sdk=cpp_sdk)
    files = rust_sdk.verify_group(ROOT / 'build/rust-sdk-group', identity)
    write('build/rust-sdk-origin.json', dict(origin='rebuild', recipe=identity, files=files))
    return identity, files


def compile_jobs():
    from build_capacity import compile_jobs as resolve
    return resolve(os.environ.get('JOBS', 'auto'))


def certification_job_limit():
    """Zero schedules all planned batches; a positive repository setting caps them."""
    raw = os.environ.get('CERTIFICATION_JOBS', '0')
    if not ci.re.fullmatch(r'0|[1-9][0-9]{0,2}', raw) or int(raw) > 256:
        raise ValueError('FOUNDATION_CERTIFICATION_JOBS must be 0 (all batches) or an integer from 1 to 256')
    return int(raw)


def parallel_operations(operations):
    """Join every independent writer, including after an earlier failure."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(operation) for operation in operations]
        return [future.result() for future in futures]


def store_application_bundles():
    """Publish a successful producer and its diagnostics with shared identity reads."""
    if not boolean('APPLICATION_SUCCEEDED'):
        store_bundle()
        return
    import ci_transport
    target = value('TARGET')
    if target not in (*ci.STANDARD, 'browser-wasm32'): raise ValueError('unknown application target')
    base, paths = bundle_inputs('build/produced/*.tar.gz\nbuild/produced/*.zip\nbuild/produced/*.json')
    proof_base, proof_paths = bundle_inputs(value('BUNDLE_PATHS'))
    if not paths or not proof_paths: raise ValueError('application and evidence must both be nonempty')
    names = ['application-' + target + '-' + value('GITHUB_RUN_ATTEMPT'), value('BUNDLE_NAME')]
    expected = 'application-evidence-' + target + '-' + value('GITHUB_RUN_ATTEMPT')
    if names[1] != expected: raise ValueError('application evidence bundle differs from producer')
    requests = [dict(name=names[0], root=base, paths=paths),
                dict(name=names[1], root=proof_base, paths=proof_paths, compress=True)]
    pointers = ci_transport.publish_bundles(**storage_context(), requests=requests, runner_name=value('RUNNER_NAME'))
    for name, pointer in zip(names, pointers):
        write(ROOT/'build/transport-pointers'/(name+'.json'), pointer)


def qualification_metadata(*, prepare_only=False):
    """Retain controls only; selected consumers read the original published assets."""
    import ci_transport
    plan = evidence.validate(evidence.load(ROOT / 'build/check-plan.json'))
    evidence.check_inputs(plan, ROOT, metadata_only=True)
    if prepare_only:
        return
    names = ['candidate/release.json', 'delivery.json', 'candidate-remote.json', 'check-plan.json']
    ci_transport.publish_bundle(**storage_context(), name='qualification-inputs-' + value('GITHUB_RUN_ATTEMPT'),
        root=ROOT / 'build', paths=names, runner_name=value('RUNNER_NAME'), compress=True)
    evidence.check_inputs(plan, ROOT, metadata_only=True)


def control_attempt():
    context = storage_context()
    return ci_retry.origin_attempt(os.environ.get('CONTROL_ATTEMPT', str(context['attempt'])), context['attempt'])


def restore_controls(reader=None):
    context = storage_context(); attempt = control_attempt()
    name = 'qualification-inputs-' + str(attempt)
    if attempt == context['attempt']:
        return fetch_bundle(name, ROOT / 'build')
    reader = reader or ci_retry.EarlierAttempts(context)
    result = reader.restore(attempt, name, 'qualification-inputs', ROOT / 'build', role='prepare')
    write(ROOT / 'build/transport-receipts' / (name + '.json'), result)
    return result


def fetch_published_check_inputs():
    """Authenticate frozen controls before deriving the exact original-asset subset."""
    raw = value('CHECK_PAYLOADS')
    if len(raw) > 8192: raise ValueError('qualification payload selector exceeds bound')
    names = delivery.parse(raw); attempt = str(control_attempt())
    if not isinstance(names, list) or not 2 <= len(names) <= 20 or names[0] != 'qualification-inputs-' + attempt:
        raise ValueError('bounded qualification input names required')
    restore_controls()
    plan = evidence.validate(evidence.load(ROOT / 'build/check-plan.json'))
    evidence.check_inputs(plan, ROOT, metadata_only=True)
    batch, expected = check_payload_selection(plan)
    if names != expected: raise ValueError('payload selector differs from complete frozen qualification scope')
    result = ci.fetch_candidate_payloads(value('GITHUB_REPOSITORY'), value('TAG'), value('INVENTORY'),
        ROOT / 'build/candidate', evidence.load(ROOT / 'build/delivery.json'),
        evidence.load(ROOT / 'build/candidate-remote.json'), plan, batch['checks'],
        trusted_context=storage_context() if control_attempt() == int(value('GITHUB_RUN_ATTEMPT')) else None)
    evidence.check_inputs(plan, ROOT, check_ids=batch['checks'])
    write(ROOT / 'build/transport-receipts/candidate-payloads.json', result)


def fetch_certification_evidence():
    """Collect the exact latest execution of every frozen physical batch."""
    raw = value('CHECK_BATCHES')
    if len(raw) > 131072: raise ValueError('qualification batch selector exceeds bound')
    matrix = delivery.parse(raw)
    if not isinstance(matrix, dict) or set(matrix) != {'include'} or not isinstance(matrix['include'], list):
        raise ValueError('complete qualification batch matrix required')
    rows = matrix['include']
    if not 1 <= len(rows) <= 48 or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or
            not ci.re.fullmatch(r'batch-[a-z0-9_-]{1,20}-[0-9a-f]{12}', row['id']) for row in rows):
        raise ValueError('bounded exact qualification batches required')
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)): raise ValueError('duplicate qualification batch')
    context = storage_context(); attempt = context['attempt']
    reader = ci_retry.EarlierAttempts(context) if attempt > 1 else None
    restore_controls(reader)
    plan = evidence.validate(evidence.load(ROOT / 'build/check-plan.json'))
    evidence.check_inputs(plan, ROOT, metadata_only=True)
    expected = ci.qualification_batches(plan, runners=selected_runners(),
        manifest=ci.module('release').verify_metadata(ROOT / 'build/candidate'), attempt=str(control_attempt()))
    if matrix != expected: raise ValueError('evidence batches differ from complete frozen qualification scope')
    current, prior = [], []
    for index, row in enumerate(rows):
        slot = 'evidence-' + str(index).zfill(2)
        name = 'evidence-' + row['id'] + '-' + str(attempt)
        if attempt == 1 or ci_retry.local_present(context, name, slot):
            current.append(dict(name=name, output=ROOT / 'build', allow_failed=True))
        else:
            original = reader.select_batch(row['id'])
            name = 'evidence-' + row['id'] + '-' + str(original)
            result = reader.restore(original, name, slot, ROOT / 'build', role='check', batch=row['id'])
            write(ROOT / 'build/transport-receipts' / (name + '.json'), result)
            prior.extend(row['checks'])
    if current: fetch_bundles(current)
    if prior:
        # Local adoption independently verifies selected frozen inputs as well as
        # every original nested receipt. Reuse saves execution, not these checks.
        ci.fetch_candidate_payloads(value('GITHUB_REPOSITORY'), value('TAG'), value('INVENTORY'),
            ROOT / 'build/candidate', evidence.load(ROOT / 'build/delivery.json'),
            evidence.load(ROOT / 'build/candidate-remote.json'), plan, prior,
            trusted_context=context if control_attempt() == attempt else None)
        checks = [item for leader in evidence.executions(plan) if leader['id'] in prior
                  for item in evidence.execution_members(plan, leader)]
        reports = [evidence.result_path(plan, item['id'], ROOT / 'build/evidence') for item in checks]
        write(ROOT / 'build/adoption.json', evidence.adopt(plan, reports, ROOT, str(context['run_id']), attempt))


def fetch_certificate():
    context = storage_context()
    attempt = ci_retry.origin_attempt(value('CERTIFICATE_ATTEMPT'), context['attempt'])
    name = 'certificate-' + str(attempt)
    if attempt == context['attempt']:
        fetch_bundle(name, ROOT / 'build')
    else:
        result = ci_retry.EarlierAttempts(context).restore(attempt, name, 'certificate', ROOT / 'build', role='record')
        write(ROOT / 'build/transport-receipts' / (name + '.json'), result)
    if evidence.sha(ROOT / 'build/certificate.json') != value('CERTIFICATE_SHA256'):
        raise ValueError('restored certificate differs from exact successful record output')


def qualification_payloads():
    """Publish each immutable source, target and dependency payload once."""
    import ci_transport
    candidate = ROOT / 'build/candidate'; manifest = ci.module('release').verify_metadata(candidate)
    plan = evidence.validate(evidence.load(ROOT / 'build/check-plan.json'))
    evidence.check_inputs(plan, ROOT)
    context = storage_context(); attempt = value('GITHUB_RUN_ATTEMPT')
    selections = [('source', [manifest['source']['archive']])]
    selections += [(entry['target'], [entry['archive'], entry['manifest']]) for entry in manifest['artifacts']]
    for index, group in enumerate(manifest['dependencies']):
        selections.append(('sdk-' + str(index), ['dependencies/' + group['recipe_id'] + '/' + name for name in group['files'] if not name.endswith('-sources.tar.gz')]))
        selections.append(('sdk-source-' + str(index), ['dependencies/' + group['recipe_id'] + '/' + name for name in group['files'] if name.endswith('-sources.tar.gz')]))
    ci_transport.publish_bundles(**context, requests=[dict(name='qualification-' + label + '-' + attempt,
        root=ROOT / 'build', paths=['candidate/' + name for name in names]) for label, names in selections] +
        [dict(name='qualification-inputs-' + attempt, root=ROOT / 'build',
              paths=['candidate/release.json', 'delivery.json', 'check-plan.json'], compress=True)],
        runner_name=value('RUNNER_NAME'))
    evidence.check_inputs(plan, ROOT)


def check_payload_selection(plan):
    batches = [row for row in ci.qualification_batches(plan, runners=selected_runners())['include'] if row['id'] == value('BATCH')]
    if len(batches) != 1: raise ValueError('unknown physical qualification batch')
    manifest = ci.module('release').verify_metadata(ROOT / 'build/candidate')
    names = ci.qualification_payload_names(plan, batches[0], manifest, str(control_attempt()))
    return batches[0], names


def fetch_check_payloads():
    plan = evidence.validate(evidence.load(ROOT / 'build/check-plan.json'))
    evidence.check_inputs(plan, ROOT, metadata_only=True)
    batch, names = check_payload_selection(plan)
    fetch_bundles([dict(name=name, output=ROOT / 'build') for name in names[1:]])
    evidence.check_inputs(plan, ROOT, check_ids=batch['checks'])


def fetch_check_inputs():
    """One grouped transfer, then reconcile the exact frozen scope before tests."""
    raw = value('CHECK_PAYLOADS')
    if len(raw) > 8192: raise ValueError('qualification payload selector exceeds bound')
    names = delivery.parse(raw); attempt = value('GITHUB_RUN_ATTEMPT')
    pattern = r'qualification-(?:inputs|source|linux-x86_64|linux-aarch64|windows-x86_64|browser-wasm32|sdk-[0-9]+|sdk-source-[0-9]+)-' + ci.re.escape(attempt)
    if (not isinstance(names, list) or not 2 <= len(names) <= 20 or
            any(not isinstance(name, str) or not ci.re.fullmatch(pattern, name) for name in names) or
            len(names) != len(set(names)) or names[0] != 'qualification-inputs-' + attempt):
        raise ValueError('bounded distinct qualification input names required')
    fetch_bundles([dict(name=name, output=ROOT / 'build') for name in names])
    plan = evidence.validate(evidence.load(ROOT / 'build/check-plan.json'))
    evidence.check_inputs(plan, ROOT, metadata_only=True)
    batch, expected = check_payload_selection(plan)
    if names != expected: raise ValueError('payload selector differs from complete frozen qualification scope')
    evidence.check_inputs(plan, ROOT, check_ids=batch['checks'])


def container_bootstrap(root, image, items, environment):
    import importlib.util
    spec = importlib.util.spec_from_file_location('batch_container_job', Path(__file__).with_name('container_job.py'))
    containers = importlib.util.module_from_spec(spec); spec.loader.exec_module(containers)
    return containers.prepared_checks(root, image, items, environment)


def check_batch():
    """Run isolated Linux cases concurrently and join every case before cleanup."""
    plan = evidence.load(ROOT / 'build/check-plan.json')
    evidence.validate(plan)
    selected = [batch for batch in ci.qualification_batches(plan, runners=selected_runners())['include'] if batch['id'] == value('BATCH')]
    if len(selected) != 1 or os.environ.get('CHECK_IMAGE') != selected[0]['image']:
        raise ValueError('batch or execution image differs from frozen inventory')
    batch = selected[0]
    evidence.check_inputs(plan, ROOT, check_ids=batch['checks'])
    expected_system = 'Windows' if batch['target'].startswith('windows-') else 'Linux'
    if ci.platform.system() != expected_system:
        raise ValueError('batch requires its selected native host')
    checks = {item['id']: item for item in evidence.executions(plan)}
    # Native Windows graphics and host browser resources remain ordered. Package
    # manager scopes remain ordered even when their host is disposable.
    isolated = bool(batch['image']) and all(checks[name]['scope'] in ('archive', 'source', 'recovery', 'abi')
                                           for name in batch['checks'])
    workers = min(len(batch['checks']), build_capacity.test_jobs(os.environ.get('FOUNDATION_CHECK_JOBS', 'auto'))) if isolated else 1
    child_environment = build_capacity.worker_environment(os.environ, workers)
    if batch['image']:
        bootstrap = container_bootstrap(ROOT, batch['image'], [checks[name] for name in batch['checks']], os.environ)
    else:
        bootstrap = nullcontext(None)
    with bootstrap as prepared:
        def execute(check_id):
            item = checks[check_id]
            browser = ci.needs_browser_prerequisite(item['backend'], item['scope'])
            environment = dict(child_environment, CHECK=check_id, CHECK_IMAGE=batch['image'],
                               CHECK_BROWSER='yes' if browser else 'no')
            # Transport attempts select retained inputs, not source-test execution.
            environment.pop('CONTROL_ATTEMPT', None)
            lifecycle = [sys.executable, str(ROOT / '.github/scripts/lifecycle.py')]
            commands = ([[sys.executable, str(ROOT / '.github/scripts/container_job.py'), 'check', '--prepared-image', prepared]]
                        if batch['image'] else
                        [lifecycle + [operation] for operation in
                         (('check-prerequisites', 'check') if expected_system == 'Linux' else ('check',))])
            try:
                for command in commands:
                    subprocess.run(command, cwd=ROOT, env=environment, check=True)
            except (OSError, subprocess.SubprocessError) as error:
                print('Qualification execution failed: ' + check_id + ': ' + str(error), file=sys.stderr)
                return check_id
            return None
        if workers == 1:
            outcomes = [execute(check_id) for check_id in batch['checks']]
        else:
            # The executor joins all writers on success and after any exception;
            # only then may the prepared image and its setup container be removed.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(execute, check_id) for check_id in batch['checks']]
                outcomes = [future.result() for future in futures]
    evidence.check_inputs(plan, ROOT, check_ids=batch['checks'])
    failures = [name for name in outcomes if name is not None]
    if failures:
        raise ValueError('required batch executions failed: ' + ', '.join(failures))


def main(command):
    os.chdir(ROOT)
    (ROOT / 'build').mkdir(exist_ok=True)
    if command == 'bundle-store':
        store_bundle()
    elif command == 'bundle-fetch':
        fetch_bundle(value('BUNDLE_NAME'),value('BUNDLE_OUTPUT'),
                     allow_failed=os.environ.get('BUNDLE_ALLOW_FAILED')=='true')
    elif command == 'application-bundles':
        store_application_bundles()
    elif command == 'qualification-metadata':
        qualification_metadata()
    elif command == 'qualification-metadata-check':
        qualification_metadata(prepare_only=True)
    elif command == 'fetch-published-check-inputs':
        fetch_published_check_inputs()
    elif command == 'fetch-certification-evidence':
        fetch_certification_evidence()
    elif command == 'qualification-payloads':
        qualification_payloads()
    elif command == 'fetch-check-payloads':
        fetch_check_payloads()
    elif command == 'fetch-check-inputs':
        fetch_check_inputs()
    elif command == 'fetch-sdk-bundles':
        targets=[*ci.STANDARD,'browser-wasm32'] if value('SDK_TARGET')=='all' else [value('SDK_TARGET')]
        if any(target not in (*ci.STANDARD,'browser-wasm32') for target in targets): raise ValueError('unknown SDK target')
        fetch_bundles([dict(name='sdk-group-'+target+'-'+value('GITHUB_RUN_ATTEMPT'), output='build/sdk-groups/'+target) for target in targets])
        if core_provider() == 'rust':
            fetch_bundles([dict(name='rust-sdk-group-'+target+'-'+value('GITHUB_RUN_ATTEMPT'),
                               output='build/rust-sdk-groups/'+target) for target in targets])
    elif command == 'fetch-assembly-inputs':
        recipes = delivery.parse(value('RECIPES'))
        rows = ci.release_matrix(recipes, value('PROFILE'), core_provider=core_provider())['include']
        fetch_bundles([dict(name='source-' + value('GITHUB_RUN_ATTEMPT'), output='build/source')] +
            [dict(name='application-' + target + '-' + value('GITHUB_RUN_ATTEMPT'), output='build/packages/' + target) for target in recipes])
        if evidence.load(Path('build/source/recipes.json')) != recipes:
            raise ValueError('assembly recipe selection differs from frozen source')
        frozen_rust = {row['target']: row['rust_recipe'] for row in rows if row['core_provider'] == 'rust'}
        if evidence.load(Path('build/source/rust-recipes.json')) != frozen_rust:
            raise ValueError('assembly Rust recipe selection differs from frozen source')
    elif command == 'fetch-application-bundles':
        fetch_bundles([dict(name='application-'+target+'-'+value('GITHUB_RUN_ATTEMPT'), output='build/packages/'+target) for target in evidence.load(Path('build/source/recipes.json'))])
    elif command == 'fetch-evidence-bundles':
        plan = evidence.load(Path('build/check-plan.json'))
        evidence.check_inputs(evidence.validate(plan), ROOT, metadata_only=True)
        fetch_bundles([dict(name='evidence-'+batch['id']+'-'+value('GITHUB_RUN_ATTEMPT'),
                         output='build',allow_failed=True) for batch in ci.qualification_batches(plan, runners=selected_runners())['include']])
    elif command == 'candidate-aggregate':
        import test_plan
        selected = delivery.parse(value('CANDIDATE_TARGETS'))
        if not isinstance(selected, dict) or set(selected) != {'include'} or not isinstance(selected['include'], list):
            raise ValueError('complete candidate target matrix required')
        rows = selected['include']
        if any(not isinstance(row, dict) or set(row) != {'target', 'runner'} or row['target'] not in ci.STANDARD for row in rows):
            raise ValueError('unknown candidate target')
        targets = [row['target'] for row in rows]
        if not targets or len(set(targets)) != len(targets):
            raise ValueError('missing or duplicate candidate targets')
        diagnostic = boolean('DEVFAST')
        scopes = ['core'] if diagnostic else ['core', 'tools', 'integration']
        fetch_bundles([dict(name='source-' + target + '-' + scope + '-' + value('GITHUB_RUN_ATTEMPT'),
            output=Path('build/candidate-results') / target / scope) for target in targets for scope in scopes])
        for target in targets:
            reports = [Path('build/candidate-results') / target / scope / ('candidate-' + scope + '.json') for scope in scopes]
            write(Path('build/candidate-results') / target / 'coverage.json',
                  test_plan.candidate_merge(reports, diagnostic=diagnostic))
    elif command == 'sdk-import-legacy':
        raw=value('LEGACY_INPUT')
        if len(raw.encode('utf-8'))>16384: raise ValueError('legacy import request exceeds supported size')
        target,profile=value('TARGET'),value('SDK_PROFILE')
        identity=sdk_identity(target,profile)
        request=delivery.parse(raw)
        imported=ci.import_legacy_sdk(value('GITHUB_REPOSITORY'),request,target,profile,identity,
            ROOT/'build/sdk-group',proof_output=ROOT/'build/legacy-proof')
        write(ROOT/'build/sdk-import.json',imported)
        write(ROOT/'build/sdk-origin.json',dict(origin='retained',recipe=identity,
            qualification='unqualified',publication_approved=False,legacy_import=imported))
        retain_sdk_group(target,profile)
    elif command == 'sdk-import-request':
        context=storage_context();target,profile=value('TARGET'),value('SDK_PROFILE')
        if context['workflow']!='sdk-import.yml': raise ValueError('import request requires explicit import workflow')
        pointers={kind:evidence.load(ROOT/'build/transport-pointers'/
            (f'sdk-{kind}-{target}-{context["attempt"]}.json')) for kind in ('group','proof')}
        for kind,pointer in pointers.items():
            if (any(pointer.get(key)!=item for key,item in context.items()) or
                pointer.get('name')!=f'sdk-{kind}-{target}-{context["attempt"]}' or
                pointer.get('job_id')!=pointers['group'].get('job_id')):
                raise ValueError('import bundle pointers do not identify one exact producer')
        request=dict(schema_version=2,**context,target=target,profile=profile,
            recipe_id=sdk_identity(target,profile),job_id=pointers['group']['job_id'],
            **{kind:dict(manifest_id=pointer['manifest']['id'],manifest_sha256=pointer['manifest']['sha256'])
               for kind,pointer in pointers.items()})
        ci.retained_sdk_request(request,context['repository'],target,profile,request['recipe_id'])
        write(ROOT/'build/import-retained-input.json',request)
        output('retained_input',request)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(value('GITHUB_STEP_SUMMARY')).open('a',encoding='utf-8') as stream:
                stream.write('Exact unqualified retained SDK request (no publication approval):\n```json\n'+
                    json.dumps(request,indent=2,sort_keys=True)+'\n```\n')
    elif command == 'sdk-plan':
        if value('SDK_SOURCE') == 'retained' and value('TARGET') == 'all':
            raise ValueError('retained SDK reuse selects one exact target per dispatch')
        retained_request(value('TARGET'), value('SDK_PROFILE'))
        if value('SDK_PROFILE') == 'all-gui':
            import screenshots
            screenshots.gui_input_selection(value('GITHUB_REPOSITORY'), delivery.parse(value('GUI_INPUT')))
        targets = [*ci.STANDARD, 'browser-wasm32']
        if value('TARGET') != 'all': targets = [value('TARGET')]
        if any(t not in (*ci.STANDARD, 'browser-wasm32') for t in targets): raise ValueError('unknown SDK target')
        runners = selected_runners()
        output('matrix', {'include': [{'target': t, 'runner': runners.get(t, runners['linux-x86_64'])} for t in targets]})
    elif command == 'runner-plan':
        target = os.environ.get('TARGET', 'linux-x86_64')
        if 'SDK_DEVELOPMENT' in os.environ and boolean('SDK_DEVELOPMENT') and not target.startswith('linux-'):
            raise ValueError('ordinary SDK development qualification requires a Linux target')
        runners = selected_runners()
        if target not in (*ci.STANDARD, 'browser-wasm32'): raise ValueError('unknown runner target')
        scalar_output('runner', runners.get(target, runners['linux-x86_64']))
    elif command == 'sdk-inputs':
        identity = sdk_identity(value('TARGET'), value('SDK_PROFILE'))
        request = retained_request(value('TARGET'), value('SDK_PROFILE'), producer_host=True)
        origin = (ci.retained_sdk(value('GITHUB_REPOSITORY'), request, value('TARGET'), value('SDK_PROFILE'),
                  identity, Path('build/sdk-group')) if request is not None else
                  ci.maintenance_base(value('GITHUB_REPOSITORY'), identity, Path('build/sdk-group'), source=value('SDK_SOURCE')))
        write('build/sdk-origin.json', origin)
    elif command == 'sdk-retain':
        retain_sdk_group(value('TARGET'), value('SDK_PROFILE'))
        output('retained', True)
    elif command in ('graphics-maintain', 'graphics-input'):
        ci.assert_host('windows-x86_64')
        import windows_graphics
        archive = ROOT / 'build/host-graphics/mesa-windows.7z'
        archive.parent.mkdir(parents=True, exist_ok=True)
        receipt = (windows_graphics.fetch(archive, network=True) if command == 'graphics-maintain' else
                   retained_graphics(value('GRAPHICS_ARCHIVE_URL'), archive))
        write('build/host-graphics/acquisition.json', receipt)
    elif command == 'sdk-produce':
        target = value('TARGET'); recipe = sdk_recipe(target, value('SDK_PROFILE'));  jobs = compile_jobs()
        if target != 'browser-wasm32': ci.assert_host(target)
        origin = evidence.load(Path('build/sdk-origin.json'))
        if origin['origin'] in ('base', 'retained'):
            result = {'recipe_id': origin['recipe']}
        elif target.startswith('linux-'):
            import distro_sdk
            distro_sdk.fetch(recipe, ROOT / 'build/sdk-inputs', jobs)
            result = distro_sdk.build(recipe, ROOT / 'build/sdk-inputs', ROOT / 'build/sdk-group', jobs)
        elif target == 'windows-x86_64':
            import sdk_windows
            provenance = evidence.load(recipe)
            selected = evidence.load(ROOT / 'build/windows-toolchain.json')
            provenance.update(linker_version=selected['LinkerVersion'], windows_sdk=selected['WindowsSdk'],
                              tools_version=selected['ToolsVersion'], installation_path=selected['InstallationPath'])
            write('build/windows-provenance.json', provenance)
            for action in ('fetch', 'build'):
                argv = [sys.executable, 'tools/sdk_windows.py', action, '--recipe-file', str(recipe),
                        '--provenance', 'build/windows-provenance.json', '--cache', 'build/sdk-inputs', '--jobs', str(jobs)]
                if action == 'build': argv += ['--output', 'build/sdk-group']
                subprocess.run(argv, check=True)
            result = {'recipe_id': sdk_windows.recipe_identity(recipe)}
        else:
            import sdk_wasm
            sdk_wasm.fetch(recipe, ROOT / 'build/sdk-inputs', network=True)
            result = sdk_wasm.prepare(recipe, ROOT / 'build/sdk-inputs', ROOT / 'build/sdk-group')
        checksums = list(Path('build/sdk-group').glob('sdk-*-SHA256SUMS'))
        if len(checksums) != 1: raise ValueError('producer did not return one complete SDK group')
        recipe_id = checksums[0].name[4:-len('-SHA256SUMS')]
        files = dependency_store.verify_group(Path('build/sdk-group'), recipe_id)
        if recipe_id != origin['recipe']: raise ValueError('produced SDK identity differs from selected recipe')
        rust_id, rust_files = prepare_rust_maintenance(target) if core_provider() == 'rust' else (None, None)
        provider = (dict(core_provider='rust', rust_group=ROOT / 'build/rust-sdk-group', rust_recipe=rust_id)
                    if rust_id is not None else dict(core_provider='cpp'))
        pending = []
        rust_isolation = (isolated_sdk_producer(target, value('SDK_PROFILE'), rust_id, 'rebuild', rust_files,
                          input_name='rust-sdk-inputs', receipt_name='rust-sdk-isolation.json')
                          if rust_id is not None else nullcontext(lambda label: None))
        with isolated_sdk_producer(target, value('SDK_PROFILE'), recipe_id, origin['origin'], files) as isolated, rust_isolation as isolated_rust:
            consumer = ROOT / 'build/sdk-consumer'
            pending.append((consumer, ci.prepared_check(target, recipe_id, Path('build/sdk-group'), consumer,
                                                       jobs, defer_qualification=True, **provider)))
            isolated('after-core'); isolated_rust('after-core')
            if value('SDK_PROFILE') == 'all-gui':
                ci.gui_group_module().verify(ROOT / 'build/gui-group')
                isolated('before-gui-install'); isolated_rust('before-gui-install')
                consumer = ROOT / 'build/sdk-gui-consumer'
                pending.append((consumer, ci.prepared_check(target, recipe_id, Path('build/sdk-group'), consumer,
                    jobs, ROOT / 'build/gui-group', defer_qualification=True,
                    graphics_archive=ROOT / 'build/host-graphics/mesa-windows.7z' if target == 'windows-x86_64' else None,
                    **provider)))
        isolation = evidence.sha(ROOT / 'build/sdk-isolation.json')
        for consumer, receipt in pending:
            receipt['producer_isolation'] = {'file': '../sdk-isolation.json', 'sha256': isolation}
            if rust_id is not None:
                receipt['rust_producer_isolation'] = {'file': '../rust-sdk-isolation.json',
                    'sha256': evidence.sha(ROOT / 'build/rust-sdk-isolation.json')}
            write(consumer / 'qualification.json', receipt)
        request = dict(repository=value('GITHUB_REPOSITORY'), recipe=recipe_id, group='build/sdk-group', source_commit=value('GITHUB_SHA'))
        write('build/sdk-publication-plan.json', delivery.publish_base(**request))
        if rust_id is not None:
            write('build/rust-sdk-publication-plan.json', ci.publish_rust_base(value('GITHUB_REPOSITORY'),
                  rust_id, ROOT / 'build/rust-sdk-group', value('GITHUB_SHA')))
    elif command == 'publish-bases':
        selected_groups = []
        for group in sorted(Path('build/sdk-groups').iterdir()):
            if not group.is_dir(): raise ValueError('unexpected SDK transport entry')
            files = list(group.glob('sdk-*-SHA256SUMS'))
            if len(files) != 1: raise ValueError('missing complete SDK output')
            recipe = files[0].name[4:-len('-SHA256SUMS')]
            delivery.publish_base(value('GITHUB_REPOSITORY'), recipe, group, value('GITHUB_SHA'))
            selected_groups.append((group, recipe))
        selected_rust_groups = []
        if core_provider() == 'rust':
            for group in sorted(Path('build/rust-sdk-groups').iterdir()):
                if not group.is_dir(): raise ValueError('unexpected Rust SDK transport entry')
                files = list(group.glob('rust-sdk-*-SHA256SUMS'))
                if len(files) != 1: raise ValueError('missing complete Rust SDK output')
                recipe = files[0].name[len('rust-sdk-'):-len('-SHA256SUMS')]
                if recipe != ci.rust_recipe(group.name):
                    raise ValueError('Rust SDK publication differs from current exact target recipe')
                ci.publish_rust_base(value('GITHUB_REPOSITORY'), recipe, group, value('GITHUB_SHA'))
                selected_rust_groups.append((group, recipe))
            if {group.name for group, _ in selected_groups} != {group.name for group, _ in selected_rust_groups}:
                raise ValueError('SDK publication requires both complete language groups for every selected target')
        for group, recipe in selected_groups:
            result = delivery.publish_base(value('GITHUB_REPOSITORY'), recipe, group, value('GITHUB_SHA'), execute=True)
            write('build/receipts/base-' + recipe + '.json', result)
        for group, recipe in selected_rust_groups:
            result = ci.publish_rust_base(value('GITHUB_REPOSITORY'), recipe, group, value('GITHUB_SHA'), execute=True)
            write('build/receipts/rust-base-' + recipe + '.json', result)
    elif command == 'apt-native-smoke':
        import artifact, release_check
        release_check.apt_preflight('linux-x86_64')
        write('build/apt-evidence/started.json', dict(operation=command, target='linux-x86_64',
              backend='core', status='started', source_commit=os.environ.get('GITHUB_SHA')))
        subprocess.run([sys.executable, 'tools/build.py', 'package', 'release', '--portable', '--jobs', '2',
                        '--build-dir', 'build/apt-smoke', '--core-provider', core_provider(),
                        *(['--rust-sdk', str(ROOT / 'build/native-rust-sdk')] if core_provider() == 'rust' else [])], check=True)
        packages = ROOT / 'build/apt-smoke/packages'
        archives = list(packages.glob('*.tar.gz'))
        if len(archives) != 1: raise ValueError('one native archive required for APT mechanism check')
        archive = archives[0]; manifest = archive.with_name(archive.name + '.json')
        write(manifest, artifact.describe(archive))
        entry = dict(archive=archive.name, manifest=manifest.name, sha256=evidence.sha(archive), target='linux-x86_64')
        result = release_check.run_apt(packages, entry, 'core', ROOT / 'build/apt-smoke/work', ROOT / 'build/apt-evidence')
        write('build/apt-evidence/result.json', result)
    elif command == 'checkout-gui-input':
        # Explicit checkout source, never a fallback after a failed remote selector.
        source, destination = ROOT / 'third_party/gui-inputs', ROOT / 'build/gui-group'
        verifier = ci.gui_group_module()
        before = verifier.verify(source)
        shutil.copytree(source, destination)
        if verifier.verify(destination) != before or verifier.verify(source) != before:
            raise ValueError('checkout GUI input changed during copying')
        write(ROOT / 'build/gui-origin.json', {'origin': 'checkout',
              'group_sha256': evidence.sha(destination / 'manifest.json')})
    elif command == 'gui-input':
        import screenshots
        raw = value('GUI_INPUT')
        if len(raw.encode('utf-8')) > 16384:
            raise ValueError('GUI input selector exceeds supported size')
        result = screenshots.fetch_gui_input(value('GITHUB_REPOSITORY'),
            delivery.parse(raw), ROOT / 'build/gui-group')
        write(ROOT / 'build/gui-origin.json', result)
    elif command == 'gui-maintain':
        lock = evidence.load(ROOT / 'third_party/gui-boundary.lock.json')
        source = ROOT / 'build/gui-upstream'
        subprocess.run(['git', 'clone', '--config', 'core.autocrlf=false', '--config', 'core.eol=lf', '--no-checkout', lock['upstream'], str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'checkout', '--detach', lock['revision']], check=True)
        ci.gui_group_module().export(source, Path('build/gui-group'))
        plan = ci.publish_gui_group(value('GITHUB_REPOSITORY'), Path('build/gui-group'), value('GITHUB_SHA'))
        write('build/gui-publication-plan.json', plan)
        if os.environ.get('GITHUB_OUTPUT'): output('redistributable', plan['redistributable'])
    elif command == 'native-gui-check':
        ci.prepared_check(value('TARGET'), value('RECIPE'), ROOT / 'build/base' / value('RECIPE'),
                          ROOT / 'build/native-gui', compile_jobs(), ROOT / 'build/gui-group',
                          graphics_archive=ROOT / 'build/host-graphics/mesa-windows.7z' if value('TARGET') == 'windows-x86_64' else None,
                          development=boolean('SDK_DEVELOPMENT') if 'SDK_DEVELOPMENT' in os.environ else False,
                          **rust_input(value('TARGET')))
    elif command == 'publish-gui':
        write('build/receipts/gui-publication.json', ci.publish_gui_group(value('GITHUB_REPOSITORY'), Path('build/gui-group'), value('GITHUB_SHA'), execute=True))
    elif command == 'application-plan':
        if os.environ.get('PACKAGE_REPOSITORY') == 'true':
            if (not re.fullmatch(r'[1-9][0-9]{0,5}', os.environ.get('PACKAGE_RELEASE', '')) or
                    not 1 <= int(value('GITHUB_RUN_ATTEMPT')) < 1000 or os.environ.get('TAG', '').lower() == 'latest'):
                raise ValueError('signed repositories need a package revision 1..999999, attempt below 1000 and an exact release tag')
        recipes = delivery.parse(value('RECIPES').encode())
        matrix = ci.release_matrix(recipes, value('PROFILE'), runners=selected_runners(), core_provider=core_provider())
        write('build/recipes.json', recipes)
        write('build/rust-recipes.json', {row['target']: row['rust_recipe'] for row in matrix['include']
              if row['core_provider'] == 'rust'})
        output('matrix', matrix)
        gui = None
        if value('PROFILE') == 'all-gui':
            ci.fetch_gui_group(value('GITHUB_REPOSITORY'), value('GUI_GROUP'), Path('build/gui-group'))
            restored = ci.gui_group_module().restore(Path('build/gui-group'), Path('build/gui-restored'))
            gui = Path(restored['source'])
        ci.source_archive(ROOT / 'build/source.tar.gz', gui)
    elif command in ('fetch-sdk', 'fetch-sdk-binary'):
        origin = delivery.fetch_base(value('GITHUB_REPOSITORY'), value('RECIPE'), Path('build/base') / value('RECIPE'),
                                     binary_only=command == 'fetch-sdk-binary')
        write('build/application-sdk.json', origin)
    elif command == 'fetch-rust-sdk':
        selected = rust_input(value('TARGET'))
        if selected['core_provider'] == 'rust':
            origin = ci.fetch_rust_base(value('GITHUB_REPOSITORY'), selected['rust_recipe'], selected['rust_group'])
            write('build/application-rust-sdk.json', origin)
    elif command == 'application-build':
        ci.prepared_package(value('TARGET'), value('RECIPE'), (ROOT / 'build/base' / value('RECIPE')),
                            ROOT / 'build/source/source.tar.gz', ROOT / 'build/produced', compile_jobs(),
                            graphics_archive=ROOT / 'build/host-graphics/mesa-windows.7z'
                            if value('TARGET') == 'windows-x86_64' and value('PROFILE') == 'all-gui' else None,
                            expected_files=evidence.load(ROOT / 'build/application-sdk.json')['files']
                            if evidence.load(ROOT / 'build/application-sdk.json').get('payload') == 'binary' else None,
                            **rust_input(value('TARGET')))
    elif command == 'assemble':
        recipes = evidence.load(Path('build/source/recipes.json'))
        delivery.fetch_bases(value('GITHUB_REPOSITORY'), sorted(set(recipes.values())), Path('build/base'))
        rust_recipes = evidence.load(Path('build/source/rust-recipes.json'))
        expected_rust = {row['target']: row['rust_recipe'] for row in ci.release_matrix(recipes, value('PROFILE'),
            core_provider=core_provider())['include'] if row['core_provider'] == 'rust'}
        if rust_recipes != expected_rust:
            raise ValueError('assembled Rust dependencies differ from frozen current recipes')
        if rust_recipes:
            delivery.fetch_rust_bases(value('GITHUB_REPOSITORY'), sorted(set(rust_recipes.values())), Path('build/rust-base'))
            for recipe in sorted(set(rust_recipes.values())):
                (Path('build/rust-base') / recipe).rename(Path('build/base') / recipe)
        ci.assemble_release(Path('build/source/source.tar.gz'), Path('build/packages'), Path('build/base'), Path('build/candidate'), value('PROFILE'))
        tag = os.environ.get('TAG') or 'candidate-' + value('GITHUB_RUN_ID') + '-attempt-' + value('GITHUB_RUN_ATTEMPT')
        if os.environ.get('PACKAGE_REPOSITORY') == 'true':
            import release_packages
            candidate = Path('build/candidate')
            manifest = ci.module('release').verify_release(candidate)
            if manifest.get('packages') is not None:
                raise ValueError('package repositories must be assembled exactly once before publication')
            if not 1 <= int(value('GITHUB_RUN_ATTEMPT')) < 1000:
                raise ValueError('package sequence requires a bounded positive workflow attempt')
            release_packages.build(candidate, value('GITHUB_REPOSITORY'), tag, value('GITHUB_SHA'),
                ROOT / 'docs/release-policy.json', Path(value('PACKAGE_SIGNING_KEY')), value('TRUSTED_FINGERPRINT'),
                sequence=int(value('GITHUB_RUN_ID')) * 1000 + int(value('GITHUB_RUN_ATTEMPT')),
                package_release=int(value('PACKAGE_RELEASE')))
            files = ci.module('dependency_archive').file_inventory(candidate, exclude=('release.json',))
            manifest['packages'] = dict(manifest='packages.json', files=sorted(set(files) - set(manifest['files'])))
            manifest['files'] = files
            ci.module('dependency_archive').write_json(candidate / 'release.json', manifest)
            ci.module('release').verify_release(candidate)
        request = dict(repository=value('GITHUB_REPOSITORY'), tag=tag, directory='build/candidate',
                       source_commit=value('GITHUB_SHA'), packager_commit=value('GITHUB_SHA'),
                       publication_id='run-' + value('GITHUB_RUN_ID') + '-attempt-' + value('GITHUB_RUN_ATTEMPT'),
                       experiment=boolean('EXPERIMENT'))
        write('build/publication-request.json', request)
        plan = delivery.publish_candidate(**request)
        write('build/publication-plan.json', plan)
        write('build/delivery.json', plan['delivery'])
        for name,item in dict(tag=tag,inventory_sha256=plan['delivery']['inventory_sha256'],
                              source_commit=value('GITHUB_SHA'),delivery_sha256=evidence.sha(Path('build/delivery.json'))).items():
            scalar_output(name,item)
    elif command == 'publish-candidate':
        request = evidence.load(Path('build/publication-request.json'))
        if request['source_commit'] != value('GITHUB_SHA') or request['packager_commit'] != value('GITHUB_SHA'):
            raise ValueError('publication input differs from checked-out workflow revision')
        write('build/receipts/publication.json', delivery.publish_candidate(**request, execute=True))
        scalar_output('published',True)
    elif command == 'certification-plan':
        limit = certification_job_limit()  # Reject invalid configuration before remote work.
        ci.fetch_candidate(value('GITHUB_REPOSITORY'), value('TAG'), value('INVENTORY'), Path('build/fetched'), metadata_only=True, planning=True, workflow_context=storage_context())
        shutil.move('build/fetched/candidate', 'build/candidate')
        shutil.move('build/fetched/delivery.json', 'build/delivery.json')
        shutil.move('build/fetched/candidate-remote.json', 'build/candidate-remote.json')
        ci.qualification_plan(ROOT / 'build/candidate', value('PROFILE'), ROOT / 'build/check-plan.json', runners=selected_runners(), metadata_only=True)
        matrix = ci.qualification_batches(evidence.load(ROOT / 'build/check-plan.json'), runners=selected_runners(),
            manifest=ci.module('release').verify_metadata(ROOT / 'build/candidate'), attempt=value('GITHUB_RUN_ATTEMPT'))
        count = len(matrix['include'])
        if not 1 <= count <= 256:
            raise ValueError('qualification matrix requires 1 to 256 batches')
        output('matrix', matrix)
        scalar_output('max_parallel', min(limit or count, count))
    elif command == 'fetch-certificate':
        fetch_certificate()
    elif command == 'check-batch':
        check_batch()
    elif command in ('check-prerequisites', 'check'):
        # Native workflow identity is translated only at this provider boundary.
        operation = qualification_tasks.prepare if command == 'check-prerequisites' else qualification_tasks.run
        result = operation(ROOT, value('CHECK'), value('GITHUB_RUN_ID'), int(value('GITHUB_RUN_ATTEMPT')))
        if command == 'check' and result['status'] != 'passed':
            raise ValueError('required qualification did not pass')
    elif command in ('certificate', 'attach-certificate'):
        identity = evidence.load(Path('build/delivery.json'))
        plan = evidence.load(Path('build/check-plan.json'))
        reports = [evidence.result_path(plan, x['id'], Path('build/evidence')) for x in plan['checks']]
        policy = ROOT / 'docs/release-policy.json'; directory = ROOT / 'build/candidate'
        if ci.module('release').verify_metadata(directory).get('packages') is not None:
            reports.append(Path('build/package-evidence/native-packages.result.json'))
        if command == 'certificate':
            import certify_release
            result = certify_release.certify(directory, ci.module('release').verify_metadata(directory), plan, reports,
                       evidence.load(policy), value('PROFILE'), identity['experiment'],
                       adoption=evidence.load(ROOT / 'build/adoption.json') if (ROOT / 'build/adoption.json').exists() else None)
            write('build/certificate.json', result)
            for name,item in dict(certificate_sha256=evidence.sha(Path('build/certificate.json')),
                certification_run=value('GITHUB_RUN_ID'),certification_attempt=value('GITHUB_RUN_ATTEMPT'),
                inventory_sha256=identity['inventory_sha256'],eligible_for_promotion=result['eligible_for_promotion']).items():
                scalar_output(name,item)
            write('build/attachment-plan.json', delivery.attach_certificate(value('GITHUB_REPOSITORY'), value('TAG'), directory,
                    identity, Path('build/certificate.json'), Path('build/check-plan.json'), policy, value('PROFILE'),
                    reports, int(value('GITHUB_RUN_ATTEMPT')), metadata_only=True))
        else:
            write('build/receipts/attachment.json', delivery.attach_certificate(value('GITHUB_REPOSITORY'), value('TAG'), directory,
                    identity, Path('build/certificate.json'), Path('build/check-plan.json'), policy, value('PROFILE'),
                    reports, ci_retry.origin_attempt(value('CERTIFICATE_ATTEMPT'), int(value('GITHUB_RUN_ATTEMPT'))),
                    execute=True, metadata_only=True))
            scalar_output('attached',True)
    elif command in ('promotion-plan', 'promote'):
        if command == 'promotion-plan':
            ci.fetch_candidate(value('GITHUB_REPOSITORY'), value('TAG'), value('INVENTORY'), Path('build/fetched'), metadata_only=True)
            shutil.move('build/fetched/candidate', 'build/candidate')
            shutil.move('build/fetched/delivery.json', 'build/delivery.json')
        request = dict(repository=value('GITHUB_REPOSITORY'), tag=value('TAG'), directory=Path('build/candidate'),
                       delivery=evidence.load(Path('build/delivery.json')), policy=Path('docs/release-policy.json'), profile=value('PROFILE'),
                       run_id=value('CERTIFICATION_RUN'), attempt=int(value('CERTIFICATION_ATTEMPT')), certificate_sha256=value('CERTIFICATE'), metadata_only=True)
        write('build/receipts/' + command + '.json', delivery.promote(**request, execute=command == 'promote'))
        if command=='promote': scalar_output('promoted',True)
    else: raise ValueError('unknown workflow operation')


def cli(command):
    try: main(command)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError,
            ProcessTreeError, subprocess.TimeoutExpired) as error:
        uncertain = command in ('bundle-store', 'application-bundles', 'qualification-metadata', 'qualification-payloads', 'publish-bases', 'publish-gui', 'publish-candidate', 'attach-certificate', 'promote')
        receipt = {'ok': False, 'uncertain': uncertain or bool(getattr(error, 'uncertain', False)),
                   'operation': command, 'error': str(error),
                   'action': 'reconcile remote state before retry' if uncertain else 'repair prerequisites and inspect retained evidence'}
        try: write('build/receipts/failure.json', receipt)
        except OSError: pass
        if isinstance(error, (ProcessTreeError, subprocess.TimeoutExpired)):
            # Retain the owner's original traceback and chained diagnostics.
            raise
        raise SystemExit(json.dumps(receipt))


if __name__ == '__main__':
    delivery.enable_metrics()
    cli(sys.argv[1])
