#!/usr/bin/env python3
"""Exercise actual static-runtime isolation, its negative control and consumers."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import process_tree


def run(command, *, code=0, cwd=None, env=None):
    command = [str(arg) for arg in command]
    # Join compiler descendants before temporary build trees and captured output
    # are released, including an assertion, timeout or setup failure.
    with tempfile.TemporaryFile() as stream:
        owner = process_tree.launch(command, Path.cwd() if cwd is None else cwd, stream, env=env)
        try:
            actual = owner.wait(timeout=180)
            owner.finish()
        except BaseException:
            owner.terminate()
            raise
        finally:
            owner.close()
        stream.seek(0)
        output = stream.read().decode('utf-8', errors='replace')
    if actual != code:
        raise RuntimeError(f"{command!r}: expected {code}, got {actual}\n{output}")
    return output


def verify(source, cmake, compiler, parent):
    environment = dict(os.environ)
    for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT'):
        environment.pop(name, None)
    environment['LC_ALL'] = 'C'
    with tempfile.TemporaryDirectory(prefix='runtime-fixture-', dir=parent) as temporary:
        root = Path(temporary)
        prefix = root / 'installed foundation with spaces'
        for mode in ('package', 'dynamic', 'unprotected', 'protected', 'installed'):
            build = root / mode
            run([cmake, '-S', source / 'tests/cxx_runtime', '-B', build, '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER=' + compiler,
                 '-DFOUNDATION_SOURCE=' + str(source), '-DMODE=' + mode,
                 '-DCMAKE_PREFIX_PATH=' + str(prefix)], env=environment)
            run([cmake, '--build', build, '--parallel', '2'], env=environment)
            stage = prefix if mode == 'package' else root / (mode + ' stage')
            run([cmake, '--install', build, '--prefix', stage], env=environment)
            if mode == 'package':
                continue
            destination = root / (mode + ' relocated with spaces')
            stage.rename(destination)
            executable = destination / 'bin/runtime_probe'
            needed = run(['readelf', '--dynamic', executable], env=environment)
            if '(RPATH)' not in needed or '$ORIGIN/../lib' not in needed:
                raise RuntimeError('fixture lost production inherited runtime search path')
            if mode == 'dynamic':
                if 'Shared library: [libstdc++.so' not in needed:
                    raise RuntimeError('baseline did not reproduce a shared C++ dependency')
                runtime = Path(run([compiler, '-print-file-name=libstdc++.so.6'], env=environment).strip()).resolve(strict=True)
                private = destination / 'lib'; private.mkdir()
                shutil.copy2(runtime, private / 'libstdc++.so.6')
            elif 'Shared library: [libstdc++.so' in needed or 'Shared library: [libgcc_s.so' in needed:
                raise RuntimeError('portable application still requires a shared language runtime')
            command = [executable, build / 'libhost_plugin.so']
            if mode == 'dynamic': command.append('shared-runtime')
            output = run(command, env=environment,
                         cwd=root, code=5 if mode == 'unprotected' else 0)
            provider = Path(output.split('plugin C++ runtime: ', 1)[1].strip()).resolve(strict=True)
            if mode == 'dynamic' and destination not in provider.parents:
                raise RuntimeError('baseline did not resolve its bundled C++ runtime')
            if mode in ('protected', 'installed') and root in provider.parents:
                raise RuntimeError('plugin resolved the application private C++ runtime')
        # Reconfiguration must not reuse a successful header probe. This controlled
        # header overlay models another selected standard library without requiring
        # libc++ to be installed; the production compile probe must reject it.
        alternate = root / 'alternate'; alternate.mkdir()
        (alternate / 'cstddef').write_text('#undef __GLIBCXX__\n')
        rejected = run([cmake, '-S', source / 'tests/cxx_runtime',
            '-B', root / 'protected', '-DCMAKE_CXX_FLAGS=-I' + str(alternate)],
            code=1, env=environment)
        if 'selected libstdc++ headers' not in rejected:
            raise RuntimeError('changed standard-library selection reused stale runtime detection')
    print('C++ runtime: bundled and exported-symbol negative controls, relocated application, installed consumer and changed-header rejection passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--temporary-root', type=Path)
    args = parser.parse_args()
    verify(args.source.resolve(), args.cmake, args.compiler, args.temporary_root)
