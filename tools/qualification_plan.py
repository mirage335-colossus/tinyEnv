#!/usr/bin/env python3
"""Provider-neutral frozen qualification plans from verified local release files."""
from collections.abc import Mapping
from pathlib import Path


def build_plan(root, candidate, profile, policy=None, *, additional_inputs=(),
               metadata_only=False, _helpers=None):
    """Freeze logical coverage without scheduling, network calls or provider inputs.

    ``candidate`` is the verified source of release files. Workers project those
    bytes under ``root/build/candidate`` and put this plan at
    ``root/build/check-plan.json`` before execution. Additional inputs map portable
    execution-relative names to existing source files; they cannot replace core
    inputs. Their bytes become ordinary frozen inputs, never trusted assertions.
    """
    if type(metadata_only) is not bool:
        raise ValueError('metadata-only selection must be boolean')
    root = Path(root).resolve(strict=True)
    candidate = Path(candidate)
    if not root.is_dir():
        raise ValueError('qualification root must be an existing directory')
    if _helpers is None:
        # These helpers describe local browser/graphics and archived-builder
        # capabilities. No hosted routing or transport function is invoked.
        import ci_plan as _helpers
    module = _helpers.module
    needs_browser_prerequisite = _helpers.needs_browser_prerequisite
    browser_prerequisite = _helpers.browser_prerequisite
    needs_windows_graphics = _helpers.needs_windows_graphics
    archived_binary_group_support = _helpers.archived_binary_group_support
    c = module('coverage')
    policy = policy or c.load(root / 'docs/release-policy.json')
    selected, _ = module('certify_release').requirements(policy, profile)
    manifest = (module('release').verify_metadata(candidate) if metadata_only else module('release').verify_release(candidate))
    if metadata_only:
        source = candidate / manifest['source']['archive']
        if c.sha(source) != manifest['source']['sha256'] or module('source_identity').verify_source_archive(source)['tree_sha256'] != manifest['source']['tree_sha256']:
            raise ValueError('retained source differs from frozen inventory')
    actual = {x['target']: x['backends'] or ['core'] for x in manifest['artifacts']}
    if len(actual) != len(manifest['artifacts']) or actual != selected['targets']:
        raise ValueError('candidate does not match complete support profile')
    binary_groups = archived_binary_group_support(candidate, manifest)
    checks = []
    for item in selected['checks']:
        target, backend, environment, scope = (item[x] for x in ('target', 'backend', 'environment', 'scope'))
        check_id = '-'.join((target, backend, environment, scope))
        argv = ['{python}', '{root}/tools/release_check.py', scope, '--release', '{root}/build/candidate',
                '--target', target, '--backend', backend, '--evidence', '{evidence}', '--jobs', 'auto']
        if (target.startswith('linux-') or target == 'browser-wasm32') and needs_browser_prerequisite(backend, scope):
            browser = browser_prerequisite(target, environment, backend)
            argv += ['--browser-prerequisite', '{root}/build/prerequisites/' + check_id + '/browser.json',
                     '--browser-prerequisite-plan', '{root}/build/check-plan.json']
            if browser['engine'] == 'firefox': argv += ['--firefox', browser['executable']]
        if environment in ('chromium', 'firefox'):
            argv += ['--browser', environment]
            if environment == 'chromium': argv += ['--browser-executable', browser['executable'], '--driver', browser['driver']]
        graphics = needs_windows_graphics(target, selected['targets'][target], backend, scope)
        if graphics:
            argv += ['--windows-graphics-archive', '{root}/build/host-graphics/mesa-windows.7z']
        if target == 'windows-x86_64' and backend == 'hosted-web' and scope == 'archive':
            argv += ['--firefox', 'C:/Program Files/Mozilla Firefox/firefox.exe']
        checks.append(dict(item, id=check_id, required=True, argv=argv, timeout_seconds=5400,
                           warning_seconds=4500, expected_tests=[], qualification='qualification.json'))
        if scope == 'source':
            entry = next(row for row in manifest['artifacts'] if row['target'] == target)
            needs_group_flag = target == 'windows-x86_64' or len(module('release').dependency_recipes(entry)) > 1
            checks[-1]['sdk_payload'] = 'binary' if not needs_group_flag or binary_groups else 'complete'
    # Logical requirements remain intact; group only identical whole-artifact work.
    groups = {}
    for item in checks:
        if item['scope'] in ('source', 'recovery', 'abi') and item['target'] != 'browser-wasm32':
            groups.setdefault(tuple(item[x] for x in ('target', 'environment', 'scope')), []).append(item)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        leader = rows[0]
        command = leader['argv'] + ['--execution-plan', '{root}/build/check-plan.json',
            '--execution-id', leader['id'], '--run-id', '{run_id}', '--attempt', '{attempt}',
            '--receipt', leader['id'] + '.qualification.json']
        for item in rows:
            item.update(execution=leader['id'], argv=command.copy(), qualification=item['id'] + '.qualification.json')
    inputs = {str(p.relative_to(root)).replace('\\', '/'): c.sha(p) for p in (root / 'tools').glob('*.py')}
    for name in ('tools/ci-apt.sh', 'docs/release-policy.json'):
        inputs[name] = c.sha(root / name)
    if any('--windows-graphics-archive' in item['argv'] for item in checks):
        for name in ('tools/windows_gl_probe.cpp', 'third_party/host-graphics/mesa-windows.json'):
            inputs[name] = c.sha(root / name)
    inputs.update({'build/candidate/' + name: digest for name, digest in manifest['files'].items()})
    inputs['build/candidate/release.json'] = c.sha(candidate / 'release.json')
    try:
        extras = list(additional_inputs.items() if isinstance(additional_inputs, Mapping) else additional_inputs)
    except TypeError:
        raise ValueError('additional inputs require relative-name/source-file pairs') from None
    for entry in extras:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('additional inputs require relative-name/source-file pairs')
        name, path = entry
        c.relative(name)
        if name in inputs or name.startswith('build/candidate/'):
            raise ValueError('additional input duplicates or replaces a frozen input')
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError('additional input requires an ordinary source file')
        inputs[name] = c.sha(path)
    value = c.freeze({'schema_version': 1, 'mode': 'release',
                      'subject': {'source_sha256': manifest['source']['sha256'], 'inventory_sha256': c.sha(candidate / 'release.json'),
                                  'configuration_sha256': c.digest({'policy': policy, 'profile': profile})},
                      'inputs': inputs, 'checks': checks})
    return value



def create_plan(root, candidate, profile, output, policy=None, *, additional_inputs=(), metadata_only=False):
    """Write a new frozen plan and return it; never overwrite an earlier plan.

    Execution uses the fixed ``build/candidate`` and ``build/check-plan.json``
    workspace paths documented by ``build_plan``. Planning may happen elsewhere
    before the exact frozen inputs are copied to a worker's private workspace.
    """
    value = build_plan(root, candidate, profile, policy, additional_inputs=additional_inputs,
                       metadata_only=metadata_only)
    import ci_plan
    ci_plan.module('coverage').write_new(output, value)
    return value
