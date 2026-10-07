#!/usr/bin/env python3
"""Bounded host diagnostics; these receipts never qualify a release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import process_tree
import run_tests
import source_identity
import windows_compiler

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'windows-x86_64': ('Windows', 'x64'), 'linux-x86_64': ('Linux', 'x64'),
           'linux-aarch64': ('Linux', 'arm64')}
BUILD_SUITES = ('test_plan', 'ci_retry', 'package_wasm', 'import_wasm')
SUITES = ('process_tree', 'windows_graphics', 'ci_plan', 'github_release', 'ci_transport', 'latest_release', 'windows_hosts', 'agent_board') + BUILD_SUITES
INTERPRETERS = ('runner-default', '3.12', '3.14')
REPETITIONS = (1, 5, 20)
CASE_SECONDS = 120
TOTAL_SECONDS = 50 * 60
PROBE = """import json,platform,struct,sys
print(json.dumps(dict(executable=sys.executable,version=sys.version,
 version_info=list(sys.version_info[:3]),implementation=sys.implementation.name,
 system=platform.system(),machine=platform.machine(),bits=struct.calcsize('P')*8,
 optimize=sys.flags.optimize)))
"""


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def architecture(machine):
    return {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine.lower())


def interpreter(selection, target, environ):
    """Use the current runner Python or its highest complete stable cache patch."""
    if selection not in INTERPRETERS or target not in TARGETS:
        raise ValueError('unknown diagnostic runtime or target')
    system, arch = TARGETS[target]
    if platform.system() != system or architecture(platform.machine()) != arch:
        raise ValueError('selected target differs from the native host')
    if selection == 'runner-default':
        return Path(sys.executable).resolve(strict=True)
    raw = environ.get('RUNNER_TOOL_CACHE')
    if not raw:
        raise ValueError('explicit interpreter requires RUNNER_TOOL_CACHE')
    cache = Path(raw).resolve(strict=True) / 'Python'
    candidates = []
    for version in cache.iterdir():
        if not re.fullmatch(re.escape(selection) + r'\.\d+', version.name):
            continue
        folder = version / arch
        path = folder / ('python.exe' if system == 'Windows' else 'bin/python')
        if not (version / (arch + '.complete')).is_file() or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if cache.resolve() not in resolved.parents or folder.resolve() not in resolved.parents:
            raise ValueError('installed interpreter escapes its cache entry')
        candidates.append((tuple(map(int, version.name.split('.'))), resolved))
    if not candidates:
        raise ValueError('requested Python ' + selection + ' is not completely installed in the runner cache')
    return max(candidates)[1]


def inspect_runtime(executable, selection, target):
    raw = subprocess.run([str(executable), '-I', '-B', '-c', PROBE], check=True,
                         capture_output=True, text=True, timeout=15)
    value = json.loads(raw.stdout)
    system, arch = TARGETS[target]
    if (value['system'] != system or architecture(value['machine']) != arch or value['bits'] != 64 or
            value['implementation'] != 'cpython' or value['optimize'] != 0 or
            Path(value['executable']).resolve(strict=True) != executable):
        raise ValueError('installed interpreter identity differs from the requested native runtime')
    if selection != 'runner-default' and value['version_info'][:2] != list(map(int, selection.split('.'))):
        raise ValueError('installed interpreter version differs from its selected cache entry')
    value['sha256'] = digest(executable)
    value['selected_path'] = str(executable)
    return value


def complete_report(path, system):
    value = json.loads(path.read_text(encoding='utf-8'))
    inventory, excluded, results = value['inventory'], value['excluded'], value['results']
    return (value['schema_version'] == 1 and value['system'] == system and value['status'] == 'passed' and
            isinstance(inventory, list) and bool(inventory) and len(set(inventory)) == len(inventory) and
            isinstance(excluded, dict) and set(excluded) <= set(inventory) and
            isinstance(results, dict) and bool(results) and set(results) == set(inventory) - set(excluded) and
            all(item['status'] == 'passed' for item in results.values()))


def repetition(executable, suite, folder, timeout, environment):
    """Join every supervised writer before returning or raising a cleanup failure."""
    folder.mkdir()
    scratch = folder / 'scratch'
    scratch.mkdir()
    environment = dict(environment, TMPDIR=str(scratch), TEMP=str(scratch), TMP=str(scratch))
    command = [str(executable), '-B', str(ROOT / 'tools/run_tests.py'), '--suite', suite,
               '--output', str(folder / 'cases.json')]
    result = {'command': command, 'status': 'failed'}
    compiler = (windows_compiler.BuildSession(environment)
                if platform.system() == 'Windows' and suite in BUILD_SUITES else None)
    if compiler is not None:
        environment = compiler.environment
    with (folder / 'console.log').open('wb') as stream:
        owner = process_tree.launch(command, ROOT, stream, env=environment)
        try:
            result['returncode'] = owner.wait(timeout=timeout)
            if compiler is not None and result['returncode'] == 0:
                result['compiler_completion'] = compiler.finish(owner)
            else:
                owner.finish()
        except subprocess.TimeoutExpired:
            result['error'] = 'suite exceeded its bounded execution time'
            owner.terminate()
        except process_tree.ProcessTreeError as error:
            result['error'] = str(error)
            owner.terminate()
        finally:
            owner.close()
    if 'error' not in result and result['returncode'] == 0:
        try:
            if complete_report(folder / 'cases.json', platform.system()):
                result['status'] = 'passed'
            else:
                result['error'] = 'case inventory is failed or incomplete'
        except (OSError, ValueError, KeyError, TypeError) as error:
            result['error'] = 'missing or invalid case inventory: ' + str(error)
    return result


def source_files(suite, target):
    """Name every maintained input consumed by the optional native host probes."""
    _, case_file = run_tests.suite_source(suite, TARGETS[target][0])
    if suite in BUILD_SUITES or suite == 'latest_release':
        # These fixtures configure, package, hash or inspect maintained source inputs. Bind their complete
        # maintained input inventory without adding a GUI build to the diagnostic.
        return sorted(source_identity.snapshot_paths(ROOT))
    paths = ['tools/host_contracts.py', 'tools/run_tests.py', 'tools/process_tree.py',
             case_file.relative_to(ROOT).as_posix()]
    if suite == 'agent_board':
        paths += ['tools/agent_board.py', '.github/workflows/host-contracts.yml']
    if suite == 'windows_hosts':
        paths += ['tools/windows_graphics.py', 'tools/windows_gl_probe.cpp', 'tools/windows_toolchain.py',
                  'tools/windows_compiler.py',
                  'gui/tests/browser_test.py', 'tools/ci_windows.ps1',
                  'tools/select-windows-toolchain.ps1', 'third_party/sdk/windows-toolchain.json',
                  '.github/workflows/host-contracts.yml']
    return paths


def execute(target, suite, selection, count, output, environ=None):
    if target not in TARGETS or suite not in SUITES or selection not in INTERPRETERS or count not in REPETITIONS:
        raise ValueError('unsupported diagnostic selection')
    if suite == 'windows_hosts' and target != 'windows-x86_64':
        raise ValueError('windows_hosts requires its native Windows host')
    environ = dict(os.environ if environ is None else environ)
    # Windows normalizes environment keys; a plain snapshot loses that lookup behavior.
    windows = platform.system() == 'Windows'
    metadata = {key.upper(): value for key, value in environ.items()} if windows else environ
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'kind': 'host-contract-diagnostic', 'release_qualification': False,
              'target': target, 'suite': suite, 'interpreter': selection, 'requested_repetitions': count,
              'status': 'incomplete', 'repetitions': [], 'writers_stopped': True,
              'host': {'system': platform.system(), 'machine': platform.machine(), 'platform': platform.platform()},
              'workflow': {key: metadata.get(key.upper() if windows else key, '') for key in ('GITHUB_SHA', 'GITHUB_RUN_ID',
                  'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKFLOW_REF', 'ImageOS', 'ImageVersion')},
              'limits': {'repetition_seconds': CASE_SECONDS, 'total_seconds': TOTAL_SECONDS}}
    destination = output / 'result.json'
    run_tests.publish(destination, report)
    started = time.monotonic()
    try:
        report['source_files'] = {name: digest(ROOT / name) for name in source_files(suite, target)}
        executable = interpreter(selection, target, environ)
        report['runtime'] = inspect_runtime(executable, selection, target)
        (output / 'repetitions').mkdir()
        for index in range(1, count + 1):
            remaining = TOTAL_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError('overall diagnostic time limit exhausted; remaining repetitions incomplete')
            report['writers_stopped'] = False
            run_tests.publish(destination, report)
            row = repetition(executable, suite, output / 'repetitions' / f'{index:02d}',
                             min(CASE_SECONDS, remaining), environ)
            report['writers_stopped'] = True
            report['repetitions'].append(dict(row, repetition=index))
            run_tests.publish(destination, report)
        if digest(executable) != report['runtime']['sha256']:
            raise ValueError('interpreter changed during diagnostics')
        if {name: digest(ROOT / name) for name in source_files(suite, target)} != report['source_files']:
            raise ValueError('diagnostic source changed during execution')
        report['status'] = 'passed' if all(row['status'] == 'passed' for row in report['repetitions']) else 'failed'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, process_tree.ProcessTreeError) as error:
        report['status'] = 'failed'
        report['error'] = str(error)
    report['elapsed_seconds'] = time.monotonic() - started
    run_tests.publish(destination, report)
    return report


def retained_paths(output):
    """Unconfirmed writers permit retaining only the diagnostic owner's summary."""
    output = Path(output)
    summary = output / 'result.json'
    paths = [summary.as_posix()]
    if json.loads(summary.read_text(encoding='utf-8')).get('writers_stopped') is True:
        paths.extend((output / 'repetitions' / '*' / name).as_posix() for name in ('cases.json', 'console.log'))
    return '\n'.join(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=TARGETS, required=True)
    parser.add_argument('--suite', choices=SUITES, required=True)
    parser.add_argument('--interpreter', choices=INTERPRETERS, required=True)
    parser.add_argument('--repetitions', type=int, choices=REPETITIONS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.target, args.suite, args.interpreter, args.repetitions, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
