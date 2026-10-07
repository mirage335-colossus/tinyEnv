#!/usr/bin/env python3
"""Build/package the application inside a prepared, disconnected Bookworm boundary.

No input acquisition or compiler reconstruction is performed. A plan contains
structured paths and exact recipes, never shell fragments. Each native target
uses one tree for core/CLI and all six native GUI hosts; Wasm uses its own tree.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from dependency_archive import digest, encoded, inspect_manifest_archive, read_json
from dependency_store import names, verify_group
from sdk_environment import require_clean

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = Path(__file__).with_name('offline_inputs.json')
SHA = re.compile(r'[0-9a-f]{64}')


def write_new(path, value):
    with Path(path).open('xb') as output:
        output.write(encoded(value))


def processor(value=None):
    value = platform.machine() if value is None else value
    return {'AMD64': 'x86_64', 'amd64': 'x86_64', 'arm64': 'aarch64', 'ARM64': 'aarch64'}.get(value, value)


def inventory(path=INVENTORY):
    value = read_json(path)
    native = ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']
    if (value.get('schema_version') != 1 or value.get('native_backends') != native
            or not isinstance(value.get('targets'), list)):
        raise ValueError('unsupported offline input inventory')
    targets = {item.get('target'): item for item in value['targets']}
    if (len(targets) != len(value['targets']) or set(targets) !=
            {'linux-x86_64', 'linux-aarch64', 'browser-wasm32', 'windows-x86_64'}):
        raise ValueError('offline inventory must preserve the complete supported matrix')
    for name, item in targets.items():
        if item.get('backends') != (['wasm'] if name == 'browser-wasm32' else native) or item.get('core_cli') is not True:
            raise ValueError('offline inventory must preserve core/CLI and every GUI backend')
    return value


def absolute(value, *, exists=True):
    if not isinstance(value, str) or not value or not Path(value).is_absolute() or '\n' in value or '\0' in value:
        raise ValueError('offline input/output paths must be absolute ordinary paths')
    path = Path(value)
    if path.is_symlink():
        raise ValueError('offline input/output root cannot be a symlink')
    try:
        resolved = path.resolve(strict=exists)
    except FileNotFoundError as error:
        raise ValueError('missing declared offline input: ' + str(path)) from error
    if resolved != path:
        raise ValueError('offline input/output paths must be canonical')
    return path


def validate_plan(value, *, system=None, machine=None):
    contract = inventory()
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'isolation', 'cases'}
            or type(value['schema_version']) is not int or value['schema_version'] not in (1, 2)):
        raise ValueError('exact schema-2 offline plan or explicit-provider schema-1 plan required')
    boundary = value['isolation']
    if not isinstance(boundary, dict):
        raise ValueError('an explicit prepared isolation boundary is required')
    if boundary.get('kind') == 'docker':
        if set(boundary) != {'kind', 'image'} or not re.fullmatch(r'sha256:[0-9a-f]{64}', boundary.get('image', '')):
            raise ValueError('Docker acceptance requires an immutable locally prepared image ID')
    elif boundary.get('kind') == 'namespace':
        if set(boundary) != {'kind', 'rootfs', 'manifest', 'manifest_sha256'} or not SHA.fullmatch(boundary.get('manifest_sha256', '')):
            raise ValueError('namespace acceptance requires an exact prepared rootfs inventory')
        absolute(boundary['rootfs']); absolute(boundary['manifest'])
    else:
        raise ValueError('unsupported isolation; no online or unisolated fallback')
    cases = value['cases']
    if not isinstance(cases, list) or not cases:
        raise ValueError('offline plan needs explicit retained groups')
    supported = {item['target']: item for item in contract['targets']}
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('offline cases need structured provider and retained group fields')
        if value['schema_version'] == 1 and 'core_provider' not in case:
            raise ValueError('schema-1 offline plans require an explicit core_provider; select cpp to preserve '
                             'the historical request, or migrate to schema 2 with complete retained Rust inputs')
        provider = case.get('core_provider', 'rust')
        required = {'target', 'group', 'recipe'}
        allowed = required | {'core_provider'}
        if provider == 'rust':
            if not {'rust_group', 'rust_recipe'} <= set(case):
                raise ValueError('Rust offline cases need their complete retained Rust group and recipe identity')
            required |= {'rust_group', 'rust_recipe'}
            allowed = required | {'core_provider'}
        if (provider not in ('cpp', 'rust') or not required <= set(case) or not set(case) <= allowed
                or case['target'] not in supported or case['target'] in seen or not SHA.fullmatch(case.get('recipe', ''))):
            raise ValueError('offline cases need unique supported targets and complete recipe identities')
        seen.add(case['target']); absolute(case['group'])
        if provider == 'rust':
            if not SHA.fullmatch(case.get('rust_recipe', '')):
                raise ValueError('Rust offline cases need a complete paired Rust recipe identity')
            absolute(case['rust_group'])
    current_system = platform.system() if system is None else system
    current_machine = processor(machine)
    applicable = [item['target'] for item in contract['targets']
                  if item['host_system'] == current_system and item['host_processor'] == current_machine]
    if not applicable or current_system != 'Linux':
        raise ValueError('this Bookworm launcher requires a supported native Linux host; Windows acceptance remains separate')
    foreign = seen - set(applicable)
    if foreign:
        raise ValueError('offline plan requests unavailable/foreign host targets: ' + ', '.join(sorted(foreign)))
    return applicable


def verify_case(case):
    provider = case.get('core_provider', 'rust')
    if provider not in ('cpp', 'rust'):
        raise ValueError('unsupported explicit core provider')
    if provider == 'rust' and (not isinstance(case.get('rust_group'), str)
                               or not isinstance(case.get('rust_recipe'), str)
                               or not SHA.fullmatch(case['rust_recipe'])):
        raise ValueError('Rust offline cases need their complete retained Rust group and recipe identity')
    target = next(item for item in inventory()['targets'] if item['target'] == case['target'])
    group = absolute(case['group'])
    hashes = verify_group(group, case['recipe'])
    metadata, _ = inspect_manifest_archive(group / names(case['recipe'])[0], 'sdk.json', sdk_archive=True)
    if (metadata['target']['system'] != target['sdk_target_system']
            or metadata['target']['processor'] != target['sdk_processor']):
        raise ValueError('retained SDK target/architecture differs from requested application target')
    host = metadata.get('host', {})
    if (host.get('system') != target['host_system'] or not isinstance(host.get('processor'), str)
            or not host['processor'] or processor(host['processor']) != target['host_processor']):
        raise ValueError('retained SDK host tools require a different native host')
    capabilities = metadata.get('capabilities', ['wasm'] if case['target'] == 'browser-wasm32' else ['core', 'terminal', 'framebuffer', 'hosted-web'])
    if not set(target['backends']) <= set(capabilities):
        raise ValueError('retained SDK lacks required GUI capabilities; select a complete matching all-GUI group')
    result = {'files': hashes, 'recipe': case['recipe'], 'target': case['target'], 'metadata': metadata,
              'core_provider': provider}
    if result['core_provider'] == 'rust':
        from rust_sdk import names as rust_names, verify_group as verify_rust_group, verify_pair
        rust_group = absolute(case['rust_group'])
        rust_hashes = verify_rust_group(rust_group, case['rust_recipe'])
        rust_metadata, _ = inspect_manifest_archive(rust_group / rust_names(case['rust_recipe'])[0], 'rust-sdk.json')
        verify_pair(rust_metadata, metadata)
        if (rust_metadata['host']['system'] != target['host_system']
                or processor(rust_metadata['host']['processor']) != target['host_processor']):
            raise ValueError('retained Rust SDK host tools require a different native host')
        result['rust'] = {'files': rust_hashes, 'recipe': case['rust_recipe'], 'metadata': rust_metadata}
    return result


def snapshot(root, destination):
    from source_identity import selected_files, source_tree
    before = source_tree(root)
    destination.mkdir()
    for name, path in selected_files(root).items():
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)
        output.chmod(0o755 if name in before['executables'] else 0o644)
    write_new(destination / 'source.json', before)
    if source_tree(destination) != before or source_tree(root) != before:
        raise ValueError('source changed while freezing offline acceptance inputs')
    return before


def os_release(path=Path('/etc/os-release')):
    result = {}
    for line in path.read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            result[key] = value.strip('"')
    if result.get('ID') != 'debian' or result.get('VERSION_ID') != '12':
        raise ValueError('offline acceptance requires the prepared Debian 12 Bookworm runtime')
    return result


def isolation_probe(*, child=False):
    interfaces = sorted(path.name for path in Path('/sys/class/net').iterdir()) if Path('/sys/class/net').is_dir() else sorted(name for _, name in socket.if_nameindex())
    if interfaces != ['lo']:
        raise ValueError('offline boundary has a non-loopback interface')
    if Path('/sys/class/net/lo/flags').is_file() and not int(Path('/sys/class/net/lo/flags').read_text().strip(), 16) & 1:
        raise ValueError('offline network namespace loopback is not enabled')
    readonly = {}
    for name, path in (('rootfs', Path('/')), ('source', ROOT), ('retained_group', Path('/inputs/group'))):
        readonly[name] = bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    if Path('/inputs/rust-group').is_dir() and any(Path('/inputs/rust-group').iterdir()):
        readonly['retained_rust_group'] = bool(os.statvfs('/inputs/rust-group').f_flag & os.ST_RDONLY)
    if not all(readonly.values()):
        raise ValueError('offline rootfs/source/retained inputs must be read-only mounts')
    # A numeric TEST-NET address avoids DNS and must be unreachable in this netns.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        try:
            probe.connect(('198.51.100.1', 9))
        except OSError as error:
            if error.errno not in (errno.ENETUNREACH, errno.EHOSTUNREACH):
                raise ValueError('network rejection does not establish a disconnected route') from error
            rejection = error.errno
        else:
            raise ValueError('offline boundary unexpectedly reached a non-loopback address')
    capabilities = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('CapEff:', 'CapBnd:')):
            key, value = line.split(':', 1); capabilities[key] = int(value.strip(), 16)
    if capabilities != {'CapEff': 0, 'CapBnd': 0}:
        raise ValueError('offline application processes must have no effective/bounding capabilities')
    mapping = Path('/proc/self/uid_map').read_text().strip()
    if os.getuid() == 0:
        rows = [tuple(map(int, row.split())) for row in mapping.splitlines()]
        if rows != [(0, os.environ.get('FOUNDATION_OUTER_UID') and int(os.environ['FOUNDATION_OUTER_UID']), 1)] or rows[0][1] == 0:
            raise ValueError('offline application must run as an ordinary host user')
    result = {'interfaces': interfaces, 'external_connect_errno': rejection,
              'network_namespace': os.readlink('/proc/self/ns/net'), 'capabilities': capabilities,
              'uid': os.getuid(), 'uid_map': mapping, 'readonly_mounts': readonly,
              'host_home_present': Path('/home/user').exists()}
    if not child:
        completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--probe'],
                                   check=True, text=True, capture_output=True, env=os.environ.copy())
        result['child'] = json.loads(completed.stdout)
        if result['child']['network_namespace'] != result['network_namespace']:
            raise ValueError('build child did not inherit the verified network boundary')
    return result


def tool_identity(name, executable, version_args=('--version',)):
    lexical = Path(shutil.which(executable) or executable).absolute()
    try:
        path = lexical.resolve(strict=True)
    except OSError as error:
        raise ValueError('missing declared offline host tool: ' + name + ' (' + executable + ')') from error
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('missing declared offline host tool: ' + name)
    completed = subprocess.run([str(path), *version_args], check=True, text=True, capture_output=True, timeout=30)
    value = {'selected_path': str(lexical), 'path': str(path), 'sha256': digest(path),
             'version': (completed.stdout + completed.stderr)[:4096].strip()}
    if str(path).startswith(('/usr/', '/bin/')):
        ownership = distribution_owner(path, lexical)
        value['distribution_owner_path'] = ownership.args[-1]
        packages = sorted(set(line.split(': ', 1)[0] for line in ownership.stdout.splitlines()))
        versions = subprocess.run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\n', *packages],
                                  check=True, text=True, capture_output=True)
        value['distribution_packages'] = versions.stdout.splitlines()
    return value


def distribution_owner(physical, lexical):
    """Bookworm usrmerge may retain /bin package names for /usr/bin bytes."""
    candidates = [physical]
    if lexical != physical:
        candidates.append(lexical)
    for first, second in (('/usr/bin/', '/bin/'), ('/usr/sbin/', '/sbin/'), ('/bin/', '/usr/bin/'), ('/sbin/', '/usr/sbin/')):
        if str(physical).startswith(first):
            candidates.append(Path(second + str(physical)[len(first):]))
    for candidate in dict.fromkeys(candidates):
        if not candidate.exists() or not candidate.samefile(physical):
            continue
        completed = subprocess.run(['dpkg-query', '-S', str(candidate)], text=True, capture_output=True)
        if completed.returncode == 0:
            return completed
        if completed.returncode != 1:
            raise ValueError('distribution package ownership lookup failed for declared host tool: ' + str(candidate))
    raise ValueError('declared host tool lacks distribution package ownership: ' + str(physical))


def host_tools(sdk, target):
    from build import host_programs
    programs = host_programs(sdk)
    metadata = read_json(sdk / 'sdk.json')
    selected = {'python3': sys.executable, 'git': 'git', 'cmake': programs['cmake'], 'ninja': programs['ninja'],
                'ctest': programs['ctest'], 'cpack': programs['cpack'],
                'retained-cxx': str(sdk / metadata['target']['cxx_compiler'])}
    if 'python' in programs:
        selected['retained-python'] = programs['python']
    if target.startswith('linux-'):
        selected['readelf'] = 'readelf'
        selected['pkg-config'] = str(sdk / 'bin/pkg-config') if (sdk / 'bin/pkg-config').is_file() else 'pkg-config'
    tools = {name: tool_identity(name, path) for name, path in selected.items()}
    minimum = (3, 10) if target == 'browser-wasm32' else (3, 9)
    if sys.version_info[:2] < minimum:
        raise ValueError('host Python is older than the declared offline prerequisite')
    if target == 'browser-wasm32':
        tools['node'] = tool_identity('node', str(sdk / 'node/bin/node'))
    return tools


def rust_host_tools(rust_sdk, cpp_sdk):
    from rust_sdk import verify_rust_sdk
    metadata = verify_rust_sdk(rust_sdk, cpp_sdk=cpp_sdk, execute=True)
    return {name: tool_identity('retained-' + name, str(rust_sdk / metadata['compiler'][name]))
            for name in ('rustc', 'cargo')}


def rust_environment(output, environment=None):
    result = dict(os.environ if environment is None else environment)
    for name in list(result):
        if name.startswith(('CARGO_', 'RUST')):
            del result[name]
    result.update(CARGO_HOME=str(output / 'cargo-home'), CARGO_NET_OFFLINE='true',
                  RUSTUP_HOME=str(output / 'rustup-home'))
    return result


def readonly_sdk(root):
    import uuid
    root = Path(root)
    if not os.statvfs(root).f_flag & os.ST_RDONLY:
        raise ValueError('execution must consume the restored Rust SDK through a read-only mount')
    path = root / ('.offline-write-probe-' + uuid.uuid4().hex)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        if error.errno != errno.EROFS:
            raise ValueError('restored Rust SDK did not reject writing as a read-only filesystem') from error
        return {'mount_readonly': True, 'write_rejection_errno': error.errno}
    else:
        os.close(descriptor)
        path.unlink()
        raise ValueError('restored Rust SDK unexpectedly allowed writing')


def checked_command(argv, commands, *, cwd=ROOT, environment=None):
    row = {'argv': [str(value) for value in argv], 'status': 'running'}
    commands.append(row)
    print('+ ' + subprocess.list2cmdline(row['argv']), flush=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(row['argv'], cwd=cwd, env=environment, check=True)
        row.update(status='passed', returncode=completed.returncode)
    except subprocess.CalledProcessError as error:
        row.update(status='failed', returncode=error.returncode)
        raise
    finally:
        row['seconds'] = time.monotonic() - started


def build_arguments(target, sdk, output, jobs, action, *, core_provider='rust', rust_sdk=None):
    contract = next(item for item in inventory()['targets'] if item['target'] == target)
    arguments = [sys.executable, '-B', str(ROOT / 'tools/build.py'), action, 'release',
                 '--sdk', str(sdk), '--gui', '--gui-backends', ','.join(contract['backends']),
                 '--build-dir', str(output / 'build'), '--build-jobs', str(jobs), '--test-jobs', '2']
    if core_provider not in ('cpp', 'rust') or (core_provider == 'rust') != (rust_sdk is not None):
        raise ValueError('offline Rust commands require their exact retained SDK')
    arguments += ['--core-provider', core_provider]
    if core_provider == 'rust':
        arguments += ['--rust-sdk', str(rust_sdk)]
    if target.startswith('linux-'):
        arguments.append('--portable')
    if action == 'test':
        arguments += ['--label', 'core', '--junit', str(output / 'core.junit.xml')]
    return arguments


def verify_core_junit(path, required=('core.store', 'core.cli')):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('missing or invalid offline core JUnit evidence')
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError('invalid offline core JUnit XML') from error
    cases = list(root.iter('testcase'))
    names = [case.get('name') for case in cases]
    if len(names) != len(required) or set(names) != set(required):
        raise ValueError('offline core evidence must execute the complete required core inventory')
    for case in cases:
        if (case.get('status') not in (None, 'run', 'passed', 'pass')
                or any(case.find(name) is not None for name in ('skipped', 'failure', 'error'))):
            raise ValueError('offline core evidence contains skipped/unexecuted/failed assertions')
    for suite in root.iter('testsuite'):
        for name in ('failures', 'errors', 'skipped', 'disabled'):
            if suite.get(name) not in (None, '0'):
                raise ValueError('offline core evidence declares incomplete/failed tests')
    return {'status': 'passed', 'tests': sorted(names), 'count': len(names), 'sha256': digest(path)}


def inside(phase, request_path):
    request = read_json(request_path)
    output = Path('/output')
    case = {**request['case'], 'group': '/inputs/group'}
    sdk = output / 'sdk'
    if 'core_provider' not in case:
        raise ValueError('projected offline requests require an explicit core_provider; recreate the request '
                         'from a migrated plan')
    provider = case['core_provider']
    rust_sdk = output / 'rust-sdk' if provider == 'rust' else None
    if rust_sdk:
        case['rust_group'] = '/inputs/rust-group'
    result = {'schema_version': 1, 'phase': phase, 'target': case['target'], 'status': 'failed', 'commands': [],
              'core_provider': provider,
              'source_tree_sha256': request['source_tree_sha256'], 'inventory_sha256': digest(INVENTORY),
              'requested_backends': next(item['backends'] for item in inventory()['targets'] if item['target'] == case['target']),
              'browser_security': 'separate real-browser qualification required'}
    try:
        from source_identity import source_tree
        result['os'] = os_release()
        result['isolation'] = isolation_probe()
        require_clean()
        if source_tree(ROOT)['tree_sha256'] != request['source_tree_sha256']:
            raise ValueError('offline source differs from the frozen request')
        verified = verify_case(case)
        if verified['files'] != request['group_files']:
            raise ValueError('retained group changed across the isolated boundary')
        result['group'] = {key: verified[key] for key in ('files', 'recipe', 'target')}
        if rust_sdk:
            if verified['rust']['files'] != request.get('rust_group_files'):
                raise ValueError('retained Rust group changed across the isolated boundary')
            if not os.statvfs('/inputs/rust-group').f_flag & os.ST_RDONLY:
                raise ValueError('retained Rust inputs must be a read-only mount')
            result['rust_group'] = {key: verified['rust'][key] for key in ('files', 'recipe')}
        if phase == 'stage':
            required = ['sh', 'bash', 'git', 'sed', 'find', 'grep', 'xargs', 'dirname', 'readlink', 'dpkg-query']
            if case['target'].startswith('linux-'):
                required += ['readelf', 'xvfb-run', 'xauth']
                if 'bin/pkg-config' not in verified['metadata']['files']:
                    required.append('pkg-config')
            for name in required:
                if not shutil.which(name):
                    raise ValueError('missing declared offline host prerequisite: ' + name)
            result['restoration_tools'] = {name: tool_identity(name, name, ('-c', ':') if name == 'sh' else ('--version',))
                                           for name in required if name not in ('xvfb-run', 'xauth')}
            if case['target'].startswith('linux-'):
                result['display_tools'] = {name: tool_identity(name, name, ('-h',) if name == 'xvfb-run' else ('-V',))
                                           for name in ('xvfb-run', 'xauth')}
            directories = ['home', 'tmp', 'cache', 'stage-home', 'stage-tmp', 'stage-cache']
            if rust_sdk:
                directories += ['cargo-home', 'rustup-home']
            for name in directories:
                directory = output / name
                if directory.exists() and any(directory.iterdir()):
                    raise ValueError('offline HOME/temp/cache must start empty')
                directory.mkdir(exist_ok=True)
            from sdk import install
            result['restoration'] = {'status': 'running', 'source': 'complete retained group',
                                     'helper': 'tools/sdk.py', 'operation': 'install', 'production': True,
                                     'group': case['group'], 'recipe': case['recipe'], 'output': str(sdk)}
            metadata = install(Path(case['group']), case['recipe'], sdk, production=True)
            result['restoration']['status'] = 'passed'
            result['sdk_manifest_sha256'] = digest(sdk / 'sdk.json')
            result['host_tools'] = host_tools(sdk, case['target'])
            if rust_sdk:
                from rust_sdk import restore
                result['rust_restoration'] = {'status': 'running', 'source': 'complete retained Rust group',
                                             'helper': 'tools/rust_sdk.py', 'operation': 'restore',
                                             'group': case['rust_group'], 'recipe': case['rust_recipe'], 'output': str(rust_sdk)}
                restore(Path(case['rust_group']), case['rust_recipe'], rust_sdk, cpp_sdk=sdk, execute=True)
                result['rust_restoration']['status'] = 'passed'
                result['rust_sdk_manifest_sha256'] = digest(rust_sdk / 'rust-sdk.json')
                result['rust_host_tools'] = rust_host_tools(rust_sdk, sdk)
            if case['target'] == 'browser-wasm32':
                if not (sdk / 'cache').is_dir() or not any((sdk / 'cache').iterdir()) or not (sdk / '.emscripten').is_file():
                    raise ValueError('prepared Wasm cache/configuration is missing; preparation must be explicit')
                result['wasm_cache'] = {'root': str(sdk / 'cache'), 'frozen': True,
                                        'files': {name: value for name, value in metadata['files'].items() if name.startswith('cache/')}}
        elif phase == 'execute':
            from sdk_manifest import verify_sdk
            if not os.statvfs(sdk).f_flag & os.ST_RDONLY:
                raise ValueError('execution must consume the restored SDK through a read-only mount')
            fresh_directories = ['home', 'tmp', 'cache'] + (['cargo-home', 'rustup-home'] if rust_sdk else [])
            for name in fresh_directories:
                if any((output / name).iterdir()):
                    raise ValueError('application acceptance HOME/temp/cache must be fresh after SDK restoration')
            result['fresh_outputs'] = {'home': True, 'temporary': True, 'cache': True, 'build': not (output / 'build').exists()}
            before = verify_sdk(sdk, release=True)
            stage = read_json(output / 'stage.json')
            if stage['status'] != 'passed' or stage['sdk_manifest_sha256'] != before:
                raise ValueError('installed SDK differs from its isolated restoration receipt')
            result['host_tools'] = host_tools(sdk, case['target'])
            if result['host_tools'] != stage['host_tools']:
                raise ValueError('selected host tools differ from their isolated restoration receipt')
            result['sdk_manifest_sha256'] = before
            if rust_sdk:
                from rust_sdk import verify_rust_sdk
                result['rust_sdk_readonly'] = readonly_sdk(rust_sdk)
                verify_rust_sdk(rust_sdk, cpp_sdk=sdk, execute=True)
                rust_before = digest(rust_sdk / 'rust-sdk.json')
                if stage.get('rust_sdk_manifest_sha256') != rust_before:
                    raise ValueError('installed Rust SDK differs from its isolated restoration receipt')
                result['rust_sdk_manifest_sha256'] = rust_before
                result['rust_host_tools'] = rust_host_tools(rust_sdk, sdk)
                if result['rust_host_tools'] != stage.get('rust_host_tools'):
                    raise ValueError('selected Rust tools differ from their isolated restoration receipt')
                result['fresh_outputs'].update(cargo_home=True, rustup_home=True)
            if (output / 'build').exists():
                raise ValueError('offline application build directory must be fresh')
            environment = os.environ.copy()
            environment.update(CCACHE_DISABLE='1', CCACHE_DIR='/output/cache/ccache', EM_FROZEN_CACHE='1')
            if rust_sdk:
                environment = rust_environment(output, environment)
                result['cargo_environment'] = {name: environment[name] for name in ('CARGO_HOME', 'RUSTUP_HOME', 'CARGO_NET_OFFLINE')}
            if case['target'] == 'browser-wasm32':
                environment['EM_CACHE'] = str(sdk / 'cache')
            for action in ('build', 'test', 'package'):
                checked_command(build_arguments(case['target'], sdk, output, request['jobs'], action,
                                                core_provider=provider, rust_sdk=rust_sdk), result['commands'], environment=environment)
                if action == 'test':
                    result['core_tests'] = verify_core_junit(output / 'core.junit.xml',
                        ('core.store', 'core.cli', 'core.text_validation', 'core.text_status'))
            choices = sorted((output / 'build/packages').glob('*.tar.gz'))
            if len(choices) != 1:
                raise ValueError('offline acceptance needs one exact platform application archive')
            archive = choices[0]
            manifest = archive.with_name(archive.name + '.json')
            base = [sys.executable, '-B', str(ROOT / 'tools/artifact.py')]
            checked_command([*base, 'create', str(archive), '--manifest', str(manifest)], result['commands'], environment=environment)
            verify = [*base, 'verify', str(archive), '--manifest', str(manifest), '--sdk', str(sdk)]
            if case['target'].startswith('linux-'):
                verify += ['--abi', '--processor', case['target'].split('-', 1)[1]]
            checked_command(verify, result['commands'], environment=environment)
            result['package'] = {'path': str(archive.relative_to(output)), 'sha256': digest(archive),
                                 'manifest_sha256': digest(manifest), 'installed_consumer': 'passed',
                                 'bookworm_abi': 'passed' if case['target'].startswith('linux-') else 'not-applicable'}
            if case['target'].startswith('linux-'):
                for backend in result['requested_backends']:
                    checked_command([*base, 'verify', str(archive), '--manifest', str(manifest), '--sdk', str(sdk),
                                     '--runtime-only', '--backend', backend], result['commands'], environment=environment)
                result['native_gui_package_smoke'] = 'passed'
            else:
                result['wasm_cache'] = stage['wasm_cache']
            if verify_sdk(sdk, release=True) != before or verify_group(case['group'], case['recipe']) != request['group_files']:
                raise ValueError('prepared SDK/retained group changed during offline acceptance')
            result['host_tools_after'] = host_tools(sdk, case['target'])
            if result['host_tools_after'] != result['host_tools']:
                raise ValueError('selected host tools changed during offline acceptance')
            if rust_sdk:
                from rust_sdk import verify_group as verify_rust_group
                verify_rust_sdk(rust_sdk, cpp_sdk=sdk, execute=True)
                if (digest(rust_sdk / 'rust-sdk.json') != rust_before
                        or verify_rust_group(case['rust_group'], case['rust_recipe']) != request['rust_group_files']):
                    raise ValueError('prepared Rust SDK/retained group changed during offline acceptance')
                result['rust_host_tools_after'] = rust_host_tools(rust_sdk, sdk)
                if result['rust_host_tools_after'] != result['rust_host_tools']:
                    raise ValueError('selected Rust tools changed during offline acceptance')
            if source_tree(ROOT)['tree_sha256'] != request['source_tree_sha256']:
                raise ValueError('source changed during offline acceptance')
        else:
            raise ValueError('unsupported offline phase')
        result['status'] = 'passed'
    except BaseException as error:
        result['error'] = str(error)[:4096]
        raise
    finally:
        write_new(output / (phase + '.json'), result)


def docker_phase(boundary, source, output, group, uid, gid, phase, *, rust_group=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location('offline_container_adapter', ROOT / '.github/scripts/container_job.py')
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    optional = {'rust_group': rust_group} if rust_group is not None else {}
    return adapter.offline_command(source, output, group, uid, gid, boundary['image'], phase,
                                   target=read_json(output / 'request.json')['case']['target'], **optional)


def run(plan_path, output, cases=None, jobs=2, root=ROOT):
    plan_path = absolute(str(plan_path))
    plan = read_json(plan_path)
    applicable = validate_plan(plan)
    selected = list(cases) if cases else applicable
    if len(selected) != len(set(selected)) or not set(selected) <= set(applicable):
        raise ValueError('focused selection must name unique host-applicable targets')
    planned = {case['target']: {**case, 'core_provider': case.get('core_provider', 'rust')}
               for case in plan['cases']}
    missing = set(selected) - set(planned)
    if missing:
        raise ValueError('missing retained inputs for required offline targets: ' + ', '.join(sorted(missing)))
    if type(jobs) is not int or jobs < 1:
        raise ValueError('offline build concurrency must be positive')
    output = absolute(str(output), exists=False)
    if output.exists() or output.is_symlink():
        raise ValueError('offline acceptance output must be new')
    root = Path(root).resolve(strict=True)
    if root in output.parents and output.relative_to(root).parts[0] not in ('build', '.agent-work'):
        raise ValueError('offline output must not enter nonignored application source inputs')
    boundary = plan['isolation']
    if boundary['kind'] == 'namespace':
        rootfs = Path(boundary['rootfs'])
        if output == rootfs or rootfs in output.parents or output in rootfs.parents:
            raise ValueError('offline output and prepared rootfs must be disjoint')
    for target in selected:
        groups = [planned[target]['group']]
        if planned[target]['core_provider'] == 'rust':
            groups.append(planned[target]['rust_group'])
        for retained in groups:
            group = Path(retained)
            if group == output or group in output.parents or output in group.parents:
                raise ValueError('offline output and retained input roots must be disjoint')
    # Freeze inputs before launching any expensive work.
    verified = {target: verify_case(planned[target]) for target in selected}
    rust_groups = [Path(planned[target]['rust_group']) for target in selected
                   if planned[target]['core_provider'] == 'rust']
    rootfs_options = {'rust_group': rust_groups[0]} if rust_groups else {}
    if boundary['kind'] == 'docker':
        completed = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', boundary['image']],
                                   check=True, text=True, capture_output=True)
        if completed.stdout.strip() != boundary['image']:
            raise ValueError('prepared Docker image identity differs; pulling is forbidden')
    else:
        from offline_namespace import verify_rootfs
        prepared_rootfs = verify_rootfs(boundary, **rootfs_options)
    output.mkdir(parents=True)
    summary = {'schema_version': 1, 'status': 'failed', 'plan_sha256': digest(plan_path), 'isolation': boundary,
               'inventory_sha256': digest(INVENTORY), 'requested_targets': selected,
               'requested_providers': {target: planned[target]['core_provider'] for target in selected},
               'required_host_targets': applicable, 'complete_host_inventory': set(selected) == set(applicable),
               'unavailable_targets': sorted({item['target'] for item in inventory()['targets']} - set(applicable)),
               'cases': [], 'coverage': 'offline application build, core tests, package/installed consumer and native GUI smoke; browser security and full regressions separate'}
    try:
        if boundary['kind'] == 'namespace':
            write_new(output / 'prepared-rootfs.json', prepared_rootfs)
            shutil.copyfile(Path(boundary['manifest']).parent / prepared_rootfs['inventory'], output / 'prepared-rootfs-inventory.json')
            from offline_namespace import setup_program
            summary['namespace_setup_tools'] = {name: tool_identity(name, setup_program(name),
                                                                    ('-Version',) if name == 'ip' else ('--version',))
                                                 for name in ('unshare', 'mount', 'chroot', 'ip')}
            summary['namespace_setup_tools']['python'] = tool_identity('python', sys.executable)
        source = output / 'source'
        source_identity = snapshot(root, source)
        summary['source_tree_sha256'] = source_identity['tree_sha256']
        if (Path(root) / '.git').exists():
            summary['source_commit'] = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            summary['source_diff_sha256'] = hashlib.sha256(subprocess.check_output(['git', '-C', str(root), 'diff', '--binary', 'HEAD'])).hexdigest()
        write_new(output / 'plan.json', plan)
        for target in selected:
            case_output = output / target
            case_output.mkdir()
            request = {'schema_version': 1, 'case': planned[target], 'group_files': verified[target]['files'],
                       'source_tree_sha256': source_identity['tree_sha256'], 'jobs': jobs}
            rust_group = None
            if 'rust' in verified[target]:
                request['rust_group_files'] = verified[target]['rust']['files']
                rust_group = Path(planned[target]['rust_group'])
            write_new(case_output / 'request.json', request)
            row = {'target': target, 'core_provider': planned[target]['core_provider'], 'status': 'failed'}
            summary['cases'].append(row)
            with (case_output / 'acceptance.log').open('xb') as log:
                if boundary['kind'] == 'docker':
                    for phase in ('stage', 'execute'):
                        argv = docker_phase(boundary, source, case_output, Path(planned[target]['group']), os.getuid(), os.getgid(), phase,
                                            **({'rust_group': rust_group} if rust_group is not None else {}))
                        subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT)
                else:
                    from offline_namespace import command, setup_environment
                    argv = command(boundary, source, case_output, Path(planned[target]['group']),
                                   **({'rust_group': rust_group} if rust_group is not None else {}))
                    subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT, env=setup_environment())
            result = read_json(case_output / 'execute.json')
            if result['status'] != 'passed':
                raise ValueError('isolated offline acceptance did not pass')
            row.update(status='passed', evidence=str((case_output / 'execute.json').relative_to(output)))
        if boundary['kind'] == 'namespace':
            # A read-only bind protects the child, not a separate host writer.
            # Refuse success if prepared bytes changed outside the namespace.
            verify_rootfs(boundary, **rootfs_options)
            summary['rootfs_recheck'] = 'passed'
        for target in selected:
            retained_groups = [(Path(planned[target]['group']), verified[target]['files'])]
            if 'rust' in verified[target]:
                retained_groups.append((Path(planned[target]['rust_group']), verified[target]['rust']['files']))
            for group, expected in retained_groups:
                if (group.is_symlink() or not group.is_dir() or {path.name for path in group.iterdir()} != set(expected)
                        or any((group / name).is_symlink() or not (group / name).is_file() for name in expected)
                        or {name: digest(group / name) for name in expected} != expected):
                    raise ValueError('retained group changed outside the boundary before acceptance completion')
        from source_identity import source_tree
        if source_tree(source) != source_identity:
            raise ValueError('frozen source changed before acceptance completion')
        summary['input_recheck'] = 'passed'
        summary['status'] = 'passed'
        return summary
    except BaseException as error:
        summary['error'] = str(error)[:4096]
        raise
    finally:
        write_new(output / 'acceptance.json', summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('run',), default='run')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', action='append', dest='cases')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--inside', choices=('stage', 'execute'), help=argparse.SUPPRESS)
    parser.add_argument('--request', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--probe', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe:
        print(json.dumps(isolation_probe(child=True)))
    elif args.inside:
        if args.request != Path('/output/request.json'):
            raise ValueError('isolated acceptance needs its explicit projected request')
        inside(args.inside, args.request)
    else:
        if not args.plan or not args.output:
            parser.error('run requires --plan and --output absolute paths')
        print(json.dumps(run(args.plan, args.output, args.cases, args.jobs), indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print('offline acceptance: ' + str(error), file=sys.stderr)
        sys.exit(1)
