#!/usr/bin/env python3
"""Prepare an offline browser-target SDK from exact retained supplier archives."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from dependency_archive import digest, encoded, file_inventory, read_json, write_json
from distro_sdk import fetch_file, unpack_source
from sdk import clean_environment, export_group, materialize
from verify_abi import audit

TOOLS = ('sdk_wasm.py', 'distro_sdk.py', 'sdk.py', 'sdk_environment.py', 'sdk_manifest.py', 'dependency_archive.py', 'dependency_store.py', 'verify_abi.py')
PROBE = '#include <string>\n#include <vector>\n#include <stdexcept>\nint main(){std::vector<std::string> v{"entry"}; try { throw std::runtime_error(v.at(0)); } catch(const std::exception& e) { return std::string(e.what())=="entry" ? 0 : 1; }}\n'


def recipe_identity(recipe):
    inputs = {'wasm.json': digest(recipe)}
    inputs.update({'tools/' + name: digest(Path(__file__).parent / name) for name in TOOLS})
    return hashlib.sha256(encoded(inputs)).hexdigest()


def prepare_launchers(directory):
    """Keep the pinned supplier's Python entry points read-only during use."""
    expected = b'exec "$_EM_PY" -E "$0.py" "$@"'
    replacement = b'exec "$_EM_PY" -B -E "$0.py" "$@"'
    changed = set()
    for path in Path(directory).iterdir():
        if not path.is_file(): continue
        data = path.read_bytes()
        if data.startswith(b'#!/bin/sh\n') and expected in data:
            if data.count(expected) != 1:
                raise ValueError('supplier launcher differs from pinned patch contract')
            path.write_bytes(data.replace(expected, replacement))
            changed.add(path.name)
    if not {'emcc', 'em++', 'emar', 'emranlib'} <= changed:
        raise ValueError('supplier launcher inventory differs from pinned patch contract')
    return sorted(changed)


def fetch(recipe, inputs, network=False):
    data = read_json(recipe)
    if data['target'] != 'wasm32-emscripten' or data['host'] != 'linux-x86_64':
        raise ValueError('unsupported browser-target SDK recipe')
    for item in data['inputs']:
        fetch_file(item, Path(inputs) / item['file'], network)
    return data


def environment(root, frozen=True):
    root = Path(root).resolve()
    env = clean_environment(root)
    env['EM_CONFIG'] = str(root / '.emscripten')
    env['EM_CACHE'] = str(root / 'cache')
    if frozen: env['EM_FROZEN_CACHE'] = '1'
    else: env.pop('EM_FROZEN_CACHE', None)
    env['PATH'] = str(root / 'node/bin') + os.pathsep + env['PATH']
    return env


def smoke(root, work):
    root, work = Path(root).resolve(strict=True), Path(work).absolute()
    if work.exists(): raise ValueError('browser SDK smoke output must be new')
    work.mkdir(parents=True)
    source = work / 'check.cpp'
    source.write_text(PROBE)
    data = read_json(root / 'sdk.json')
    subprocess.run([str(root / 'bin/em++'), str(source), *data['cache_options'], '-o', str(work / 'check.js')], env=environment(root), check=True)
    subprocess.run([str(root / 'node/bin/node'), str(work / 'check.js')], cwd=work, env=environment(root), check=True)
    return {'status': 'passed', 'executor': 'retained-node', 'cache': 'frozen'}


def prepare(recipe, inputs, output):
    data = fetch(recipe, inputs, network=False)
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('this browser SDK recipe runs on Linux x86_64')
    output = Path(output).absolute()
    if output.exists(): raise ValueError('browser SDK group output must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = recipe_identity(recipe)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='browser-sdk-') as temporary:
        work = Path(temporary)
        raw = work / 'raw'
        raw.mkdir()
        locations = {}
        for item in data['inputs']:
            location = work / ('unpack-' + item['name'])
            unpack_source(Path(inputs) / item['file'], location)
            locations[item['name']] = location
        materialize(locations['emsdk'] / ('emsdk-' + data['emscripten_version']), raw / 'emsdk')
        materialize(locations['compiler'] / 'install', raw / 'upstream')
        materialize(locations['node'] / ('node-v' + data['node_version'] + '-linux-x64'), raw / 'node')
        launchers = prepare_launchers(raw / 'upstream/emscripten')
        (raw / '.emscripten').write_text("import os\nROOT = os.path.dirname(os.path.abspath(__file__))\nLLVM_ROOT = os.path.join(ROOT, 'upstream/bin')\nBINARYEN_ROOT = os.path.join(ROOT, 'upstream')\nNODE_JS = [os.path.join(ROOT, 'node/bin/node')]\nCACHE = os.path.join(ROOT, 'cache')\n")
        (raw / 'bin').mkdir()
        for name in ('emcc', 'em++', 'emar', 'emranlib'):
            wrapper = raw / 'bin' / name
            wrapper.write_text('#!/usr/bin/env python3\nimport os, pathlib, sys\nroot = pathlib.Path(__file__).resolve().parents[1]\nos.environ["EM_CONFIG"] = str(root / ".emscripten")\nos.environ["EM_CACHE"] = str(root / "cache")\nos.environ["EM_FROZEN_CACHE"] = "1"\nos.environ["PYTHONDONTWRITEBYTECODE"] = "1"\nprogram = str(root / "upstream/emscripten" / pathlib.Path(__file__).name)\nos.execv(program, [program, *sys.argv[1:]])\n')
            wrapper.chmod(0o755)
        probe = work / 'probe.cpp'
        probe.write_text(PROBE)
        compiler = raw / 'upstream/emscripten/em++'
        subprocess.run([str(compiler), str(probe), *data['cache_options'], '-o', str(work / 'probe.js')], env=environment(raw, False), check=True)
        subprocess.run([str(raw / 'node/bin/node'), str(work / 'probe.js')], env=environment(raw), check=True)
        for bytecode in raw.rglob('*.pyc'):
            bytecode.unlink()
        for cache_directory in sorted(raw.rglob('__pycache__'), reverse=True):
            if not any(cache_directory.iterdir()): cache_directory.rmdir()
        sources = work / 'sources'
        sources.mkdir()
        (sources / 'inputs').mkdir()
        for item in data['inputs']: shutil.copyfile(Path(inputs) / item['file'], sources / 'inputs' / item['file'])
        (sources / 'recipe').mkdir()
        shutil.copyfile(recipe, sources / 'recipe/wasm.json')
        (sources / 'tools').mkdir()
        for name in TOOLS: shutil.copyfile(Path(__file__).parent / name, sources / 'tools' / name)
        write_json(sources / 'sources.json', {'schema_version': 1, 'recipe_id': identity, 'files': file_inventory(sources),
                   'recovery_scope': data['source_recovery_scope']})
        host = {'status': 'passed', 'compiler': audit(raw / 'upstream/bin', host=True), 'node': audit(raw / 'node/bin', host=True)}
        metadata = {'schema_version': 1, 'recipe_id': identity, 'kind': 'retained-upstream',
                    'target': {'system': 'Emscripten', 'processor': 'wasm32', 'triple': 'wasm32-emscripten',
                               'sysroot': 'cache/sysroot', 'cxx_compiler': 'bin/em++', 'toolchain': 'upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake'},
                    'host': {'system': 'Linux', 'processor': 'x86_64', 'glibc': '2.36', 'python': '3.10+'},
                    'prepared_launcher_patch': {'purpose': 'disable Python bytecode writes', 'files': launchers},
                    'sources_sha256': digest(sources / 'sources.json'), 'relocation': 'relative-paths',
                    'licenses': ['upstream/emscripten/LICENSE', 'node/LICENSE'], 'cache_options': data['cache_options'],
                    'audits': {'host': host, 'target': {'status': 'passed', 'executor': 'retained-node'}}, 'files': file_inventory(raw)}
        write_json(raw / 'sdk.json', metadata)
        # A fresh wrapper-based compile must reuse the frozen cache; a missing
        # variant is a preparation error, never an ordinary-build download.
        smoke(raw, work / 'frozen-probe')
        metadata['files'] = file_inventory(raw, exclude=('sdk.json',))
        write_json(raw / 'sdk.json', metadata)
        return export_group(raw, sources, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('recipe-id', 'fetch', 'prepare', 'smoke'))
    parser.add_argument('--recipe', type=Path, default=Path(__file__).resolve().parents[1] / 'third_party/sdk/wasm.json')
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.action == 'recipe-id': result = {'recipe_id': recipe_identity(args.recipe)}
    elif args.action == 'fetch':
        if not args.inputs: parser.error('fetch requires --inputs')
        result = fetch(args.recipe, args.inputs, True)
    elif args.action == 'prepare':
        if not args.inputs or not args.output: parser.error('prepare requires --inputs and --output')
        result = prepare(args.recipe, args.inputs, args.output)
    else:
        if not args.root or not args.output: parser.error('smoke requires --root and --output')
        result = smoke(args.root, args.output)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
