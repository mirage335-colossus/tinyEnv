#!/usr/bin/env python3
"""Build the private dependency-free Rust archive with identified offline inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

import package_notices
import process_tree
import sdk_environment
import windows_compiler


TARGETS = {
    'x86_64-unknown-linux-gnu': 'Linux',
    'aarch64-unknown-linux-gnu': 'Linux',
    'x86_64-pc-windows-msvc': 'Windows',
    'wasm32-unknown-emscripten': 'Emscripten',
}
NATIVE_LIBRARIES = {
    'Linux': {'gcc_s', 'gcc', 'util', 'rt', 'pthread', 'm', 'dl', 'c'},
    'Windows': {'advapi32', 'bcrypt', 'comdlg32', 'dbghelp', 'gdi32', 'kernel32',
                'ntdll', 'ole32', 'oleaut32', 'shell32', 'user32', 'userenv',
                'uuid', 'ws2_32', 'legacy_stdio_definitions', 'libcmt',
                'libvcruntime', 'libucrt', 'libcmtd', 'libvcruntimed', 'libucrtd'},
    'Emscripten': set(),
}
MAX_OUTPUT = 16 * 1024 * 1024
DISTRO_USR = Path('/usr')
DISTRO_TARGETS = {'x86_64-unknown-linux-gnu': ('x86_64-linux-gnu', 'amd64'),
                  'aarch64-unknown-linux-gnu': ('aarch64-linux-gnu', 'arm64')}
CONFIG_FIELDS = {'schema_version', 'source_root', 'build_dir', 'target', 'system',
                 'profile', 'tools', 'sysroot', 'target_libdir', 'target_libraries',
                 'source_inputs', 'sources', 'flags', 'artifact_path', 'receipt_path',
                 'native_static_libs', 'notice_files', 'notices', 'sdk_root',
                 'cpp_sdk_root', 'sdk_manifest', 'cpp_sdk_manifest', 'metadata'}


def _file_identity(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def _snapshot(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Rust inputs require absolute paths: ' + str(path))
    path = path.resolve(strict=True)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('Rust input must be a regular file: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if _file_identity(path.stat()) != _file_identity(before):
        raise ValueError('Rust input changed while identified: ' + str(path))
    return {'path': str(path), 'sha256': digest.hexdigest(), 'identity': _file_identity(before)}


def native_tool_identity(cargo, rustc):
    """Bind explicitly selected tools without executing them or discovering Rust."""
    result = {'cargo': _snapshot(cargo), 'rustc': _snapshot(rustc)}
    if (result['cargo']['identity'][:2] == result['rustc']['identity'][:2]
            or result['cargo']['sha256'] == result['rustc']['sha256']):
        raise ValueError('Rust proxies are unsupported; Cargo and rustc must be distinct actual tools')
    for name, row in result.items():
        if Path(row['path']).stem.lower() == 'rustup':
            raise ValueError('Rust proxies are unsupported; select the actual ' + name + ' executable')
        if os.name != 'nt' and not os.access(row['path'], os.X_OK):
            raise ValueError('selected Rust tool is not executable: ' + row['path'])
        for proxy_name in ('rustup', 'rustup.exe'):
            proxy = Path(row['path']).parent / proxy_name
            if proxy.is_file():
                identity = _snapshot(proxy)
                if identity['identity'][:2] == row['identity'][:2] or identity['sha256'] == row['sha256']:
                    raise ValueError('Rust proxies are unsupported; select the actual ' + name + ' executable')
    return result


def select_native_tools():
    if not sys.platform.startswith('linux'):
        raise ValueError('native Rust discovery requires Linux; prepare a retained Rust SDK')
    result = {}
    for name in ('cargo', 'rustc'):
        selected = shutil.which(name)
        if not selected:
            raise ValueError('missing ' + name + '; explicitly prepare Rust tools before building')
        result[name] = str(Path(selected).resolve(strict=True))
    native_tool_identity(**result)
    return result


def _absolute(value, label, *, existing=False):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(label + ' must be an absolute path')
    if path.is_symlink():
        raise ValueError(label + ' must not be a symlink')
    return path.resolve(strict=existing)


def _configs_absent(*directories):
    checked = set()
    for directory in directories:
        directory = Path(directory)
        for ancestor in (directory, *directory.parents):
            if ancestor in checked:
                continue
            checked.add(ancestor)
            for name in ('config', 'config.toml'):
                candidate = ancestor / '.cargo' / name
                if candidate.exists() or candidate.is_symlink():
                    raise ValueError('ambient Cargo configuration is unsupported: ' + str(candidate))


def child_environment(build_dir, cargo, rustc, flags, environment=None):
    inherited = dict(os.environ if environment is None else environment)
    sdk_environment.require_clean({name: inherited.get(name) for name in sdk_environment.HOST_OVERRIDES
                                   if name.startswith('LD_')})
    for key, value in inherited.items():
        upper = key.upper()
        permitted = upper in ('CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_MAKEFLAGS', 'RUSTUP_HOME',
                              'RUST_LOG', 'RUST_BACKTRACE', 'RUST_LIB_BACKTRACE')
        permitted = permitted or (upper == 'CARGO_NET_OFFLINE' and value == 'true')
        if (upper.startswith(('RUST', 'CARGO_')) and not permitted) or upper == 'LD_PRELOAD':
            if value:
                raise ValueError('ambient Rust setting is unsupported: ' + key)
    home = Path(build_dir) / 'cargo-home'
    target = Path(build_dir) / 'target'
    _configs_absent(build_dir, home)
    if home.is_symlink() or target.is_symlink():
        raise ValueError('private Cargo home and output must not be symlinks')
    for name in ('config', 'config.toml'):
        if (home / name).exists() or (home / name).is_symlink():
            raise ValueError('private Cargo home contains unapproved configuration')
    home.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    result = {key: value for key, value in inherited.items()
              if not key.upper().startswith(('RUST', 'CARGO_'))
              and key.upper() not in ('MAKEFLAGS', 'MFLAGS', 'MAKELEVEL', 'JOBSERVERS', 'JOBSERVER_FDS')}
    result.update({'CARGO_HOME': str(home), 'CARGO_TARGET_DIR': str(target),
                   'RUSTC': str(rustc), 'CARGO_ENCODED_RUSTFLAGS': '\x1f'.join(flags),
                   'CARGO_NET_OFFLINE': 'true', 'CARGO_BUILD_JOBS': '1',
                   'CARGO_INCREMENTAL': '0', 'CARGO_TERM_COLOR': 'never',
                   'CARGO_PROFILE_DEV_PANIC': 'abort', 'CARGO_PROFILE_RELEASE_PANIC': 'abort',
                   'CARGO_PROFILE_DEV_LTO': 'false', 'CARGO_PROFILE_RELEASE_LTO': 'false',
                   'CARGO_PROFILE_DEV_CODEGEN_UNITS': '1', 'CARGO_PROFILE_RELEASE_CODEGEN_UNITS': '1'})
    # Rust tools are absolute; PATH still supplies the selected native C++ tools.
    result['PATH'] = os.pathsep.join(dict.fromkeys((str(Path(cargo).parent), str(Path(rustc).parent),
                                                  inherited.get('PATH', ''))))
    return result


def _run(argv, *, cwd, environment, compiler=False, timeout=180):
    session = windows_compiler.BuildSession(environment) if compiler and os.name == 'nt' else None
    environment = session.environment if session else environment
    with tempfile.TemporaryFile(dir=cwd) as output:
        owner = process_tree.launch(argv, cwd=cwd, stream=output, env=environment)
        try:
            deadline = time.monotonic() + timeout
            while owner.poll() is None:
                if time.monotonic() >= deadline or os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                    owner.terminate()
                    raise ValueError('Rust command exceeded its time or output bound')
                time.sleep(0.01)
            code = owner.process.returncode
            if code:
                owner.terminate()
                owner.finish()
            elif session:
                session.finish(owner)
            else:
                owner.finish()
            if os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                raise ValueError('Rust command exceeded its output bound')
            output.seek(0)
            raw = output.read(MAX_OUTPUT + 1).decode('utf-8', errors='strict')
            if code:
                raise ValueError('Rust command failed (' + str(code) + '): ' + raw[-8192:])
            return raw
        finally:
            owner.close()


def _flags(target, sysroot):
    result = ['--sysroot', str(sysroot), '-Cpanic=abort', '-Ccodegen-units=1',
              '-Clto=no', '-Cembed-bitcode=no', '-Crelocation-model=pic']
    if TARGETS[target] == 'Windows':
        result += ['-Ctarget-feature=+crt-static']
    return result


def _sources(root, sdk=False):
    rust = root / 'rust'
    paths = []
    if not rust.is_dir() or rust.is_symlink():
        raise ValueError('missing Rust workspace; expected rust/Cargo.toml')
    for path in sorted(rust.rglob('*')):
        if path.is_symlink():
            raise ValueError('Rust source tree must not contain links: ' + str(path))
        if path.is_file():
            if path.suffix in ('.rs', '.toml') or path.name == 'Cargo.lock':
                paths.append(path)
            elif path.name == 'build.rs':
                raise ValueError('Rust build scripts are unsupported')
        elif not path.is_dir():
            raise ValueError('Rust source tree contains a special entry')
    required = (rust / 'Cargo.toml', rust / 'Cargo.lock',
                rust / 'text_validation/Cargo.toml', rust / 'text_validation/src/lib.rs')
    if any(path not in paths for path in required):
        raise ValueError('missing Rust workspace manifest, frozen lockfile or component source')
    lock = (rust / 'Cargo.lock').read_text(encoding='utf-8').split('[[package]]', 1)[0]
    if not re.search(r'^version\s*=\s*3\s*$', lock, re.MULTILINE):
        raise ValueError('Rust requires Cargo.lock format 3 readable by baseline Cargo 1.63')
    if any(path.name == 'build.rs' for path in paths):
        raise ValueError('Rust build scripts are unsupported')
    producers = [Path(__file__), Path(process_tree.__file__), Path(windows_compiler.__file__),
                 Path(windows_compiler.windows_toolchain.__file__), Path(package_notices.__file__),
                 Path(sdk_environment.__file__)]
    if sdk:
        producers.extend(Path(__file__).parent / name for name in
                         ('rust_sdk.py', 'dependency_archive.py', 'sdk_manifest.py'))
    paths.extend(path.resolve(strict=True) for path in producers)
    return {str(path): _snapshot(path) for path in paths}


def _distro_package(path):
    query = str(DISTRO_USR / 'bin/dpkg-query')
    try:
        rows = package_notices.command(query, '-S', str(path)).splitlines()
        if len(rows) != 1 or ': ' not in rows[0]:
            raise ValueError('ambiguous package ownership')
        package, owned = rows[0].rsplit(': ', 1)
        if (not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?', package)
                or owned != str(path)):
            raise ValueError('package ownership names a different input')
        status = package_notices.command(query, '-W', '-f=${db:Status-Abbrev}\n${Version}', package)
        lines = status.splitlines()
        if len(lines) != 2 or lines[0] != 'ii ' or not lines[1] or lines[1].strip() != lines[1]:
            raise ValueError('package is not installed with one identified version')
        return {'package': package, 'version': lines[1]}
    except (ValueError, subprocess.SubprocessError, OSError) as error:
        raise ValueError('native Rust package ownership is unavailable: ' + str(path)
                         + '; prepare a retained Rust SDK (' + str(error) + ')') from error


def _distro_library_link(path, directory, target, rustc, compiler_version):
    if target not in DISTRO_TARGETS:
        raise ValueError('unsupported native Rust library link layout; prepare a retained Rust SDK')
    multiarch, architecture = DISTRO_TARGETS[target]
    expected_directory = DISTRO_USR / 'lib/rustlib' / target / 'lib'
    if (directory != expected_directory or path.parent != directory
            or expected_directory.resolve(strict=True) != expected_directory
            or Path(rustc) != DISTRO_USR / 'bin/rustc'
            or not re.fullmatch(r'lib(?:std|test)-[0-9a-f]+\.so', path.name)):
        raise ValueError('unsupported native Rust library link layout; prepare a retained Rust SDK')
    before = path.lstat()
    if not stat.S_ISLNK(before.st_mode):
        raise ValueError('native Rust library input stopped being a link')
    text = os.readlink(path)
    expected = DISTRO_USR / 'lib' / multiarch / path.name
    try:
        target_before = expected.lstat()
        if (text not in ('../../../' + multiarch + '/' + path.name, str(expected))
                or path.resolve(strict=True) != expected or expected.resolve(strict=True) != expected
                or not stat.S_ISREG(target_before.st_mode)):
            raise ValueError('link must name the matched ordinary distro runtime file')
    except (ValueError, OSError, RuntimeError) as error:
        raise ValueError('invalid native Rust library link: ' + str(path)
                         + '; prepare a retained Rust SDK (' + str(error) + ')') from error
    ownership_tool = _snapshot(_absolute(DISTRO_USR / 'bin/dpkg-query',
                                        'native Rust package ownership tool', existing=True))
    compiler = _distro_package(Path(rustc))
    link = _distro_package(path)
    runtime = _distro_package(expected)
    runtime_name = 'libstd-rust-' + '.'.join(compiler_version.split('.')[:2])
    if (compiler['package'] not in ('rustc', 'rustc:' + architecture)
            or link['package'] != 'libstd-rust-dev:' + architecture
            or runtime['package'] != runtime_name + ':' + architecture
            or compiler['version'] != link['version'] or compiler['version'] != runtime['version']):
        raise ValueError('native Rust compiler and library package owners or versions differ; '
                         'prepare a retained Rust SDK')
    result = {'path': str(path), 'link': text, 'identity': _file_identity(before),
              'target': _snapshot(expected), 'compiler_package': compiler,
              'link_package': link, 'target_package': runtime,
              'ownership_tool': ownership_tool}
    link_after, target_after = path.lstat(), expected.lstat()
    if (not stat.S_ISLNK(link_after.st_mode) or _file_identity(link_after) != result['identity']
            or os.readlink(path) != text or path.resolve(strict=True) != expected
            or not stat.S_ISREG(target_after.st_mode)
            or expected.resolve(strict=True) != expected or result['target']['path'] != str(expected)
            or _file_identity(target_after) != _file_identity(target_before)
            or _file_identity(target_after) != result['target']['identity']
            or _snapshot(ownership_tool['path']) != ownership_tool):
        raise ValueError('native Rust library link or target changed while identified')
    return result


def _target_libraries(directory, native_target=None, native_rustc=None, compiler_version=None):
    directory = _absolute(directory, 'Rust target library directory', existing=True)
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            if native_target is None:
                raise ValueError('Rust target libraries must not contain symlinks')
            result[str(path)] = _distro_library_link(path, directory, native_target,
                                                    native_rustc, compiler_version)
        elif path.is_file():
            result[str(path)] = _snapshot(path)
        elif not path.is_dir():
            raise ValueError('Rust target libraries contain a special entry')
    required = ('libcore-', 'libcompiler_builtins-')
    if native_target:
        required += ('libstd-', 'libtest-')
    for prefix in required:
        if not any(Path(path).name.startswith(prefix) and path.endswith('.rlib') for path in result):
            raise ValueError('missing matched ' + prefix[:-1] + ' target library; prepare the exact target')
    links = [row for row in result.values() if 'link' in row]
    if links:
        families = [Path(row['path']).name.split('-', 1)[0] for row in links]
        if sorted(families) != ['libstd', 'libtest'] or any(
                str(Path(row['path']).with_suffix('.rlib')) not in result for row in links):
            raise ValueError('incomplete native Rust distro runtime library family; prepare a retained Rust SDK')
    return result


def _metadata(root, cargo, environment, build):
    raw = _run([cargo, 'metadata', '--frozen', '--no-deps', '--format-version', '1',
                '--manifest-path', str(root / 'rust/Cargo.toml')],
               cwd=build, environment=environment)
    data = json.loads(raw)
    packages = data.get('packages', [])
    if (len(packages) != 1 or len(data.get('workspace_members', [])) != 1
            or Path(data.get('workspace_root', '')).resolve() != root / 'rust'):
        raise ValueError('Rust pilot requires its one dependency-free workspace member')
    package = packages[0]
    expected = root / 'rust/text_validation/Cargo.toml'
    if (package.get('name') != 'foundation-text-validation'
            or Path(package.get('manifest_path', '')).resolve() != expected or package.get('source') is not None
            or package.get('dependencies') or package.get('edition') != '2021'
            or package.get('rust_version') != '1.63'):
        raise ValueError('Rust pilot requires edition 2021, Rust 1.63 and zero external crates')
    targets = package.get('targets', [])
    if (len(targets) != 1 or targets[0].get('name') != 'foundation_rust'
            or set(targets[0].get('crate_types', [])) != {'staticlib', 'rlib'}
            or set(targets[0].get('kind', [])) != {'staticlib', 'rlib'}):
        raise ValueError('Rust pilot requires only the foundation_rust staticlib and rlib; no build scripts or macros')
    return {'package_id': package['id'], 'workspace_root': data['workspace_root'],
            'manifest_path': str(expected)}


def parse_native_static_libs(raw, system):
    lines = [line.split('native-static-libs:', 1)[1].strip() for line in raw.splitlines()
             if 'native-static-libs:' in line]
    if len(lines) > 1:
        raise ValueError('ambiguous Rust native-static-libs receipt')
    tokens = lines[0].split() if lines else []
    result = []
    for token in tokens:
        if system == 'Windows' and token.lower().endswith('.lib') and re.fullmatch(r'[A-Za-z0-9_]+\.lib', token):
            name = token[:-4].lower()
        elif token.startswith('-l') and re.fullmatch(r'-l[A-Za-z0-9_]+', token):
            name = token[2:]
        else:
            raise ValueError('unapproved Rust native linkage argument: ' + token)
        if name not in NATIVE_LIBRARIES[system]:
            raise ValueError('unapproved Rust native library: ' + name)
        if name not in result:
            result.append(name)
    return result


def _probe_native_libs(build, rustc, target, flags, environment):
    probe = build / 'link-probe'
    if probe.is_symlink():
        raise ValueError('Rust probe output must not be a symlink')
    probe.mkdir(exist_ok=True)
    source = probe / 'probe.rs'
    _save_bytes(source, b'#![no_std]\n#[panic_handler]\nfn panic(_: &core::panic::PanicInfo) -> ! { loop {} }\n#[no_mangle]\npub extern "C" fn foundation_link_probe() -> u32 { 1 }\n')
    artifact = probe / ('probe.lib' if TARGETS[target] == 'Windows' else 'libprobe.a')
    raw = _run([rustc, '--crate-name', 'foundation_link_probe', '--crate-type', 'staticlib',
                '--edition', '2021', '--target', target, '--print', 'native-static-libs',
                *flags, str(source), '-o', str(artifact)], cwd=build, environment=environment,
               compiler=True)
    if not artifact.is_file():
        raise ValueError('Rust target probe produced no static archive')
    return parse_native_static_libs(raw, TARGETS[target])


def _notices(sdk, tools, libraries, metadata=None):
    paths = set()
    if sdk:
        from rust_sdk import verify_rust_sdk
        data = metadata if metadata is not None else verify_rust_sdk(sdk, execute=False)
        for relative in data.get('licenses', []):
            paths.update(package_notices.notice_files(Path(sdk) / relative))
        if not paths:
            raise ValueError('Rust SDK has no retained target notices')
    else:
        for path in [row['path'] for row in tools.values()] + [path for path in libraries
                     if Path(path).name.startswith(('libcore-', 'libcompiler_builtins-'))]:
            _, notice = package_notices.distro_notice(path)
            paths.add(notice)
        for row in libraries.values():
            if 'link' in row:
                for provider in ('link_package', 'target_package'):
                    package = row[provider]['package'].split(':', 1)[0]
                    paths.add(package_notices.regular(DISTRO_USR / 'share/doc' / package / 'copyright'))
    notices = {str(path): _snapshot(path) for path in sorted(paths)}
    # Distro notices can reference separately installed complete license texts.
    for path in list(notices):
        for name in re.findall(r'/usr/share/common-licenses/([A-Za-z0-9.+_-]+)', Path(path).read_text(encoding='utf-8')):
            license_path = Path('/usr/share/common-licenses') / name
            if license_path.is_file():
                notices[str(license_path.resolve())] = _snapshot(license_path.resolve())
            else:
                raise ValueError('Rust notice references a missing complete license: ' + name)
    return notices


def _sdk_identity(sdk, cpp_sdk, target):
    if sdk:
        from rust_sdk import verify_rust_sdk
        identity = _snapshot(Path(sdk) / 'rust-sdk.json')
        verify_rust_sdk(sdk, cpp_sdk=cpp_sdk, target=target, execute=False)
        if _snapshot(Path(sdk) / 'rust-sdk.json') != identity:
            raise ValueError('Rust SDK metadata changed while verifying')
        return identity
    return None


def describe(source_root, build_dir, target, cargo, rustc, profile='debug', sdk_root=None,
             cpp_sdk_root=None):
    if target not in TARGETS or profile not in ('debug', 'release'):
        raise ValueError('unsupported Rust target or profile')
    root = _absolute(source_root, 'Rust source root', existing=True)
    build = _absolute(build_dir, 'Rust build directory')
    if build == root or root / 'rust' == build or root / 'rust' in build.parents:
        raise ValueError('Cargo outputs must be outside the Rust source tree')
    sdk = str(_absolute(sdk_root, 'Rust SDK root', existing=True)) if sdk_root else None
    cpp_sdk = str(_absolute(cpp_sdk_root, 'C++ SDK root', existing=True)) if cpp_sdk_root else None
    if not sdk and (TARGETS[target] != 'Linux' or cpp_sdk):
        raise ValueError('this Rust profile requires a prepared retained Rust SDK')
    build.mkdir(parents=True, exist_ok=True)
    _configs_absent(root / 'rust', root / 'rust/text_validation', build)
    tools = native_tool_identity(cargo, rustc)
    sdk_identity = _snapshot(Path(sdk) / 'rust-sdk.json') if sdk else None
    cpp_identity = _snapshot(Path(cpp_sdk) / 'sdk.json') if cpp_sdk else None
    if sdk:
        from rust_sdk import verify_rust_sdk
        manifest = verify_rust_sdk(sdk, cpp_sdk=cpp_sdk, target=target, execute=False)
        if _snapshot(Path(sdk) / 'rust-sdk.json') != sdk_identity:
            raise ValueError('Rust SDK metadata changed while describing')
        for name in ('cargo', 'rustc'):
            if Path(tools[name]['path']) != (Path(sdk) / manifest['compiler'][name]).resolve(strict=True):
                raise ValueError('selected Rust tool differs from its retained SDK')
    initial = _sources(root, bool(sdk))
    environment = child_environment(build, tools['cargo']['path'], tools['rustc']['path'], [])
    raw = _run([tools['rustc']['path'], '-vV'], cwd=build, environment=environment)
    fields = dict(line.split(': ', 1) for line in raw.splitlines() if ': ' in line)
    version = fields.get('release', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or tuple(map(int, version.split('.'))) < (1, 63, 0):
        raise ValueError('Rust requires a stable compiler at least version 1.63.0')
    if not sdk and fields.get('host') != target:
        raise ValueError('unprepared native Rust must use its exact host target')
    tools['rustc'].update({'version': version, 'host': fields.get('host'), 'verbose_version': raw.strip()})
    tools['cargo']['version'] = _run([tools['cargo']['path'], '--version'], cwd=build, environment=environment).strip()
    cargo_version = re.match(r'^cargo (\d+\.\d+\.\d+)(?:\s|$)', tools['cargo']['version'])
    if not cargo_version or tuple(map(int, cargo_version.group(1).split('.'))) < (1, 63, 0):
        raise ValueError('Rust requires Cargo version 1.63.0 or newer')
    if sdk and (version != manifest['compiler']['version']
                or fields.get('host') != manifest['compiler']['host']
                or cargo_version.group(1) != manifest['compiler']['cargo_version']):
        raise ValueError('Rust executable versions differ from retained SDK metadata')
    sysroot = _run([tools['rustc']['path'], '--print', 'sysroot'], cwd=build, environment=environment).strip()
    libdir = _run([tools['rustc']['path'], '--print', 'target-libdir', '--target', target],
                  cwd=build, environment=environment).strip()
    sysroot = str(_absolute(sysroot, 'Rust sysroot', existing=True))
    libdir = str(_absolute(libdir, 'Rust target library directory', existing=True))
    if sdk and (Path(sysroot) != (Path(sdk) / manifest['compiler']['sysroot']).resolve(strict=True)
                or Path(libdir) != (Path(sdk) / manifest['target']['library_directory']).resolve(strict=True)):
        raise ValueError('Rust compiler target libraries differ from its retained SDK')
    libraries = _target_libraries(libdir, None if sdk else target,
                                 tools['rustc']['path'], version)
    flags = _flags(target, sysroot)
    environment = child_environment(build, tools['cargo']['path'], tools['rustc']['path'], flags)
    metadata = _metadata(root, tools['cargo']['path'], environment, build)
    libs = _probe_native_libs(build, tools['rustc']['path'], target, flags, environment)
    notices = _notices(sdk, tools, libraries, manifest if sdk else None)
    suffix = 'foundation_rust.lib' if TARGETS[target] == 'Windows' else 'libfoundation_rust.a'
    result = {'schema_version': 1, 'source_root': str(root), 'build_dir': str(build),
              'target': target, 'system': TARGETS[target], 'profile': profile, 'tools': tools,
              'sysroot': sysroot, 'target_libdir': libdir, 'target_libraries': libraries,
              'source_inputs': sorted(initial), 'sources': initial, 'flags': flags,
              'artifact_path': str(build / 'target' / target / profile / suffix),
              'receipt_path': str(build / 'receipt.json'), 'native_static_libs': libs,
              'notice_files': sorted(notices), 'notices': notices, 'sdk_root': sdk,
              'cpp_sdk_root': cpp_sdk, 'sdk_manifest': sdk_identity,
              'cpp_sdk_manifest': cpp_identity, 'metadata': metadata}
    _unchanged(result)
    return result


def _unchanged(config):
    _configs_absent(Path(config['source_root']) / 'rust',
                    Path(config['source_root']) / 'rust/text_validation', Path(config['build_dir']))
    if _sources(Path(config['source_root']), bool(config['sdk_root'])) != config['sources']:
        raise ValueError('Rust source inputs changed; reconfigure before building')
    for name, row in config['tools'].items():
        if _snapshot(row['path']) != {key: row[key] for key in ('path', 'sha256', 'identity')}:
            raise ValueError('selected Rust tool changed; use a fresh configured build tree')
    if _target_libraries(config['target_libdir'], None if config['sdk_root'] else config['target'],
                         config['tools']['rustc']['path'], config['tools']['rustc']['version']) != config['target_libraries']:
        raise ValueError('Rust target library inputs changed; reconfigure with the verified SDK')
    if any(_snapshot(path) != row for path, row in config['notices'].items()):
        raise ValueError('Rust dependency notice inputs changed')
    if _sdk_identity(config['sdk_root'], config['cpp_sdk_root'], config['target']) != config['sdk_manifest']:
        raise ValueError('Rust SDK identity changed')
    if config['cpp_sdk_root'] and _snapshot(Path(config['cpp_sdk_root']) / 'sdk.json') != config['cpp_sdk_manifest']:
        raise ValueError('paired C++ SDK identity changed')


def _save_bytes(path, raw):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Rust output must not be a symlink: ' + str(path))
    if path.exists() and path.read_bytes() == raw:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_config(path, data):
    path = Path(path)
    if set(data) == CONFIG_FIELDS and path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        fields = CONFIG_FIELDS - {'source_inputs', 'sources', 'metadata'}
        if set(previous) != CONFIG_FIELDS or any(previous[name] != data[name] for name in fields):
            raise ValueError('Rust toolchain or configuration changed; use a fresh build tree')
    _save_bytes(path, (json.dumps(data, indent=2, sort_keys=True) + '\n').encode('utf-8'))


def _load_config(path):
    path = _absolute(path, 'Rust configuration', existing=True)
    data = json.loads(path.read_text(encoding='utf-8'))
    if set(data) != CONFIG_FIELDS or data['schema_version'] != 1:
        raise ValueError('invalid Rust build configuration schema')
    build = _absolute(data['build_dir'], 'Rust build directory', existing=True)
    if path.parent != build:
        raise ValueError('Rust configuration must be inside its private build directory')
    if data['target'] not in TARGETS or data['system'] != TARGETS[data['target']] or data['profile'] not in ('debug', 'release'):
        raise ValueError('invalid Rust configuration target or profile')
    suffix = 'foundation_rust.lib' if data['system'] == 'Windows' else 'libfoundation_rust.a'
    if (data['flags'] != _flags(data['target'], data['sysroot'])
            or data['artifact_path'] != str(build / 'target' / data['target'] / data['profile'] / suffix)
            or data['receipt_path'] != str(build / 'receipt.json')
            or data['source_inputs'] != sorted(data['sources'])
            or data['notice_files'] != sorted(data['notices'])):
        raise ValueError('Rust configuration contains uncontrolled flags, inputs or outputs')
    for name in data['native_static_libs']:
        if name not in NATIVE_LIBRARIES[data['system']]:
            raise ValueError('Rust configuration contains unapproved native linkage')
    _unchanged(data)
    return data, _snapshot(path)


def _output_directories(data, tree='target'):
    build = Path(data['build_dir'])
    for path in (build / tree, build / tree / data['target'],
                 build / tree / data['target'] / data['profile']):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError('Rust output directory must be an ordinary directory: ' + str(path))
        if path.resolve() != path:
            raise ValueError('Rust output directory escapes its private build tree')


def _artifact(data):
    _output_directories(data)
    path = _absolute(data['artifact_path'], 'Rust generated archive', existing=True)
    if str(path) != data['artifact_path']:
        raise ValueError('Rust generated archive escapes its private build tree')
    return _snapshot(path)


def _clean_package(data, environment, target_dir):
    _run([data['tools']['cargo']['path'], 'clean', '--frozen', '--package', 'foundation-text-validation',
          '--manifest-path', str(Path(data['source_root']) / 'rust/Cargo.toml'),
          '--target', data['target'], '--target-dir', str(target_dir)],
         cwd=data['build_dir'], environment=environment)


def build(config_path):
    data, config_identity = _load_config(config_path)
    _output_directories(data)
    receipt_path = Path(data['receipt_path'])
    prior = None
    prior_identity = None
    if receipt_path.exists():
        prior_identity = _snapshot(receipt_path)
        prior = json.loads(receipt_path.read_text(encoding='utf-8'))
        if (set(prior) != {'schema_version', 'config', 'artifact', 'native_static_libs', 'target', 'profile', 'policy'}
                or prior['schema_version'] != 1 or prior['target'] != data['target']
                or prior['profile'] != data['profile'] or prior['native_static_libs'] != data['native_static_libs']
                or prior['policy'] != 'frozen-dependency-free-staticlib'
                or prior['artifact'].get('path') != data['artifact_path']):
            raise ValueError('invalid previous Rust build receipt')
    environment = child_environment(data['build_dir'], data['tools']['cargo']['path'],
                                    data['tools']['rustc']['path'], data['flags'])
    # Cargo 1.63 uses source mtimes for freshness. Changed identified inputs must
    # invalidate its private package cache even when source timestamps went back.
    rebound = prior is None or prior['config'] != config_identity
    if rebound:
        _clean_package(data, environment, Path(data['build_dir']) / 'target')
    argv = [data['tools']['cargo']['path'], 'build', '--frozen', '--jobs', '1',
            '--manifest-path', str(Path(data['source_root']) / 'rust/Cargo.toml'),
            '--target', data['target'], '--target-dir', str(Path(data['build_dir']) / 'target'),
            '--message-format', 'json-render-diagnostics']
    if data['profile'] == 'release':
        argv.append('--release')
    raw = _run(argv, cwd=data['build_dir'], environment=environment, compiler=True, timeout=600)
    artifacts = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get('reason') == 'compiler-artifact':
            if item.get('package_id') != data['metadata']['package_id']:
                raise ValueError('Cargo produced an unapproved package artifact')
            artifacts.append(item)
        if item.get('reason') == 'compiler-message':
            rendered = item.get('message', {}).get('rendered')
            if rendered:
                print(rendered, end='', file=sys.stderr)
    if len(artifacts) != 1 or data['artifact_path'] not in artifacts[0].get('filenames', []):
        raise ValueError('Cargo did not identify the expected Rust static archive')
    if any(Path(name).suffix.lower() in ('.so', '.dylib', '.dll') for item in artifacts for name in item.get('filenames', [])):
        raise ValueError('Rust dynamic libraries are unsupported')
    _unchanged(data)
    if _snapshot(config_path) != config_identity:
        raise ValueError('Rust configuration changed during build')
    artifact = _artifact(data)
    if prior_identity is not None and _snapshot(receipt_path) != prior_identity:
        raise ValueError('Rust build receipt changed during compilation')
    if artifacts[0].get('fresh') and (rebound or prior['artifact'] != artifact):
        raise ValueError('Cargo reused an unbound or changed Rust archive; remove the archive and rebuild')
    receipt = {'schema_version': 1, 'config': config_identity, 'artifact': artifact,
               'native_static_libs': data['native_static_libs'], 'target': data['target'],
               'profile': data['profile'], 'policy': 'frozen-dependency-free-staticlib'}
    save_config(data['receipt_path'], receipt)
    print('RUST_BUILD_COMPLETION ' + json.dumps({'artifact': artifact['path'], 'sha256': artifact['sha256'],
                                               'fresh': bool(artifacts[0].get('fresh'))}, sort_keys=True))
    return receipt


def verify(config_path):
    data, config_identity = _load_config(config_path)
    receipt_path = _absolute(data['receipt_path'], 'Rust build receipt', existing=True)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    expected = {'schema_version': 1, 'config': config_identity, 'artifact': _artifact(data),
                'native_static_libs': data['native_static_libs'], 'target': data['target'],
                'profile': data['profile'], 'policy': 'frozen-dependency-free-staticlib'}
    if receipt != expected:
        raise ValueError('Rust generated archive differs from its bound build receipt')
    _unchanged(data)
    if _snapshot(config_path) != config_identity:
        raise ValueError('Rust configuration changed during receipt verification')
    return receipt


def test(config_path):
    data, config_identity = _load_config(config_path)
    if data['target'] != data['tools']['rustc']['host'] or data['system'] == 'Emscripten':
        raise ValueError('Rust unit tests require an executable exact-host native target')
    _output_directories(data, 'unit-target')
    flags = [flag for flag in data['flags'] if flag != '-Cpanic=abort']
    environment = child_environment(data['build_dir'], data['tools']['cargo']['path'],
                                    data['tools']['rustc']['path'], flags)
    for name in ('CARGO_PROFILE_DEV_PANIC', 'CARGO_PROFILE_RELEASE_PANIC'):
        environment.pop(name)
    target_dir = str(Path(data['build_dir']) / 'unit-target')
    environment['CARGO_TARGET_DIR'] = target_dir
    state_path = Path(data['build_dir']) / 'unit-state.json'
    state = {'schema_version': 1, 'config': config_identity, 'target': data['target'], 'profile': data['profile']}
    previous_identity = None
    previous = None
    if state_path.exists():
        _absolute(state_path, 'Rust unit cache binding', existing=True)
        previous_identity = _snapshot(state_path)
        previous = json.loads(state_path.read_text(encoding='utf-8'))
    if previous != state:
        _clean_package(data, environment, target_dir)
    argv = [data['tools']['cargo']['path'], 'test', '--frozen', '--jobs', '1', '--lib',
            '--manifest-path', str(Path(data['source_root']) / 'rust/Cargo.toml'),
            '--target', data['target'], '--target-dir', target_dir]
    if data['profile'] == 'release':
        argv.append('--release')
    raw = _run(argv, cwd=data['build_dir'], environment=environment, compiler=True, timeout=600)
    summary = re.search(r'test result: ok\. (\d+) passed; (\d+) failed', raw)
    if summary is None or int(summary.group(1)) == 0 or int(summary.group(2)) != 0:
        raise ValueError('Rust unit test command executed no passing assertions')
    _unchanged(data)
    if _snapshot(config_path) != config_identity:
        raise ValueError('Rust configuration changed during unit tests')
    if previous_identity is not None and _snapshot(state_path) != previous_identity:
        raise ValueError('Rust unit cache binding changed during tests')
    save_config(state_path, state)
    print(raw, end='')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    describe_parser = commands.add_parser('describe')
    for name in ('source-root', 'build-dir', 'target', 'cargo', 'rustc', 'output'):
        describe_parser.add_argument('--' + name, required=True)
    describe_parser.add_argument('--profile', choices=('debug', 'release'), default='debug')
    describe_parser.add_argument('--sdk-root')
    describe_parser.add_argument('--cpp-sdk-root')
    for name in ('build', 'verify', 'test'):
        commands.add_parser(name).add_argument('--config', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'describe':
            data = describe(args.source_root, args.build_dir, args.target, args.cargo, args.rustc,
                            args.profile, args.sdk_root, args.cpp_sdk_root)
            output = _absolute(args.output, 'Rust configuration output')
            if output.parent != Path(data['build_dir']):
                raise ValueError('Rust configuration output must be in its private build directory')
            save_config(output, data)
        elif args.command == 'build':
            build(args.config)
        elif args.command == 'test':
            test(args.config)
        else:
            verify(args.config)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, process_tree.ProcessTreeError) as error:
        parser.exit(1, 'rust_build: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
