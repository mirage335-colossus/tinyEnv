#!/usr/bin/env python3
"""Compile and execute a small actual Rev module diagnostic using retained inputs.

No acquisition, dependency build, display or release qualification is performed.
Every attempt owns a new output directory and retains failures and joined writers.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

import build_capacity
import coverage as evidence
import process_tree
import run_tests
import windows_compiler

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path('tests/rev_style_probe')
CASES = ('foundation.rev-probe.equality', 'foundation.rev-probe.layout')
MAX_LOG = 8 * 1024 * 1024
PHASE_SECONDS = 600
INPUTS = ('tools/rev_probe.py', 'tools/build_capacity.py', 'tools/coverage.py',
          'tools/process_tree.py', 'tools/run_tests.py', 'tools/windows_compiler.py',
          'tools/windows_toolchain.py', 'gui/source_group.py', 'tools/dependency_archive.py',
          'tests/rev_style_probe/CMakeLists.txt', 'tests/rev_style_probe/style.cpp',
          'tests/rev_style_probe/COPYING', 'tests/rev_style_probe/README.md')


def source_group():
    spec = importlib.util.spec_from_file_location('rev_probe_gui_group', ROOT / 'gui/source_group.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executable(name):
    selected = shutil.which(str(name))
    if selected is None:
        raise ValueError('required installed executable is unavailable: ' + str(name))
    # argv[0] is semantic: clang++ is often a symlink to clang, but selects
    # C++ runtime linking. Hash its target without changing its invocation name.
    return Path(selected).absolute()


def file_identity(path):
    path = Path(path).absolute()
    resolved = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError('tool identity is not a regular file: ' + str(path))
    return {'path': str(path), 'resolved_path': str(resolved), 'sha256': evidence.sha(path)}


def run_command(command, cwd, log, environment, *, compiler=False, timeout=PHASE_SECONDS):
    """Do not accept a successful parent until its complete owned tree is joined."""
    started = time.monotonic()
    row = {'command': command, 'status': 'failed', 'returncode': None, 'writers_stopped': True}
    owner = None
    try:
        session = windows_compiler.BuildSession(environment) if compiler and os.name == 'nt' else None
        with log.open('xb') as stream:
            try:
                row['writers_stopped'] = False
                owner = process_tree.launch(command, cwd, stream,
                    env=session.environment if session else environment)
                while owner.poll() is None:
                    if time.monotonic() - started > timeout or log.stat().st_size > MAX_LOG:
                        raise TimeoutError('diagnostic command exhausted its time or output limit')
                    time.sleep(.05)
                row['returncode'] = owner.wait(timeout=5)
                if row['returncode'] == 0 and session:
                    row['compiler_completion'] = session.finish(owner)
                else:
                    owner.finish()
                if time.monotonic() - started > timeout or log.stat().st_size > MAX_LOG:
                    raise TimeoutError('diagnostic command exhausted its time or output limit')
                if row['returncode'] != 0:
                    raise ValueError('diagnostic command exited with status ' + str(row['returncode']))
                row['status'] = 'passed'
            finally:
                # Close joins failed commands too; keep streams open until closure.
                if owner is not None:
                    owner.close()
                    row['writers_stopped'] = True
    except (OSError, ValueError, process_tree.ProcessTreeError, subprocess.SubprocessError) as error:
        row['status'], row['error'] = 'failed', str(error)
    row['seconds'] = time.monotonic() - started
    return row


def verify_compiler(path, selected):
    info = evidence.load(path)
    if Path(info['CMAKE_CXX_COMPILER']).resolve(strict=True) != selected.resolve(strict=True):
        raise ValueError('CMake selected a different compiler')
    programs = {}
    for key in ('CMAKE_CXX_COMPILER', 'CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS',
                'CMAKE_LINKER', 'CMAKE_AR', 'CMAKE_MAKE_PROGRAM'):
        if info.get(key):
            programs[key] = file_identity(info[key])
    return {'configuration': info, 'programs': programs}


def execute(group, output, compiler, *, jobs='auto', cmake='cmake', ninja='ninja'):
    output = Path(output).absolute()
    source_group().ordinary(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'kind': 'rev-module-diagnostic', 'release_qualification': False,
              'status': 'incomplete', 'writers_stopped': True, 'cases': list(CASES), 'phases': [],
              'host': evidence.host_identity(), 'omitted': ['native GUI and graphics', 'application', 'SDK and release qualification']}
    destination = output / 'result.json'
    run_tests.publish(destination, report)
    started = time.monotonic()
    try:
        if platform.system() not in ('Linux', 'Windows'):
            raise ValueError('this diagnostic requires a qualified Linux or Windows process supervisor')
        if os.environ.get('CMAKE_TOOLCHAIN_FILE'):
            raise ValueError('unset CMAKE_TOOLCHAIN_FILE; this diagnostic executes a native compiler')
        selected = executable(compiler)
        programs = {name: executable(value) for name, value in
                    [('cmake', cmake), ('ninja', ninja), ('ctest', str(executable(cmake).with_name('ctest.exe' if os.name == 'nt' else 'ctest')))]}
        report['tools'] = {name: file_identity(value) for name, value in dict(programs, compiler=selected).items()}
        report['source_files'] = {name: evidence.sha(ROOT / name) for name in INPUTS}
        report['jobs'] = build_capacity.compile_jobs(jobs)
        verifier = source_group()
        restored = verifier.restore(Path(group), output / 'inputs')
        report['gui_input'] = restored
        fixture = output / 'fixture'
        fixture.mkdir()
        for name in ('CMakeLists.txt', 'style.cpp', 'COPYING', 'README.md'):
            shutil.copyfile(ROOT / FIXTURE / name, fixture / name)
        build = output / 'build'
        scratch = output / 'scratch'; scratch.mkdir()
        environment = dict(os.environ, TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch), PYTHONDONTWRITEBYTECODE='1')
        report['compiler_environment'] = {name: environment.get(name, '') for name in
            ('CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CL', '_CL_', 'CPATH', 'LIBRARY_PATH', 'CPLUS_INCLUDE_PATH')}
        commands = [
            ('configure', [str(programs['cmake']), '-S', str(fixture), '-B', str(build), '-G', 'Ninja',
                '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER=' + str(selected),
                '-DCMAKE_MAKE_PROGRAM=' + str(programs['ninja']),
                '-DFOUNDATION_REV_SOURCE=' + str(Path(restored['source']) / 'third_party/rev')], True),
            ('build', [str(programs['cmake']), '--build', str(build), '--parallel', str(report['jobs'])], True),
            ('test', [str(programs['ctest']), '--test-dir', str(build), '--output-on-failure',
                '--no-tests=error', '--parallel', '1', '--output-junit', str(output / 'tests.xml')], False),
        ]
        for name, command, owns_compiler in commands:
            report['writers_stopped'] = False
            run_tests.publish(destination, report)
            row = run_command(command, output, output / (name + '.log'), environment, compiler=owns_compiler)
            report['phases'].append(dict(row, name=name))
            report['writers_stopped'] = row['writers_stopped']
            run_tests.publish(destination, report)
            if row['status'] != 'passed' or not row['writers_stopped']:
                raise ValueError(name + ' failed: ' + row.get('error', 'writer completion unconfirmed'))
            if name == 'configure':
                report['compiler'] = verify_compiler(build / 'compiler.json', selected)
        evidence.junit(output / 'tests.xml', list(CASES))
        if verifier.restore(Path(group), output / 'inputs') != restored:
            raise ValueError('retained GUI identity changed during the diagnostic')
        if report['source_files'] != {name: evidence.sha(ROOT / name) for name in INPUTS}:
            raise ValueError('diagnostic source changed during execution')
        if any(file_identity(value['path']) != value for value in report['tools'].values()):
            raise ValueError('selected build tool changed during execution')
        if report['compiler'] != verify_compiler(build / 'compiler.json', selected):
            raise ValueError('configured compiler or scanner changed during execution')
        report['status'] = 'passed'
    except (OSError, ValueError, KeyError, TypeError, EOFError, tarfile.TarError, ET.ParseError,
            process_tree.ProcessTreeError, subprocess.SubprocessError) as error:
        report['status'], report['error'] = 'failed', str(error)
    report['seconds'] = time.monotonic() - started
    # Never read/hash outputs that might still have a writer.
    report['evidence'] = ({path.name: evidence.sha(path) for name in ('configure.log', 'build.log', 'test.log', 'tests.xml')
                          if (path := output / name).is_file()} if report['writers_stopped'] else {})
    run_tests.publish(destination, report)
    return report


def retained_paths(output):
    """Transport only the owner summary until every descendant writer is joined."""
    output = Path(output)
    summary = output / 'result.json'
    report = evidence.load(summary)
    paths = [summary.as_posix()]
    if report.get('writers_stopped') is True:
        paths.extend((output / name).as_posix() for name in
                     ('configure.log', 'build.log', 'test.log', 'tests.xml')
                     if (output / name).is_file() and (output / name).stat().st_size <= MAX_LOG)
    return '\n'.join(paths)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui-input-group', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new owned directory for this attempt')
    parser.add_argument('--compiler', required=True, help='installed native C++ module compiler')
    parser.add_argument('--jobs', default='auto')
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--ninja', default='ninja')
    args = parser.parse_args(argv)
    result = execute(args.gui_input_group, args.output, args.compiler, jobs=args.jobs, cmake=args.cmake, ninja=args.ninja)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit('Rev diagnostic: ' + str(error))
