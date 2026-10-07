#!/usr/bin/env python3
"""Explicit optional-provider qualification; never publishes an application release."""
import argparse
from contextlib import contextmanager
import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import artifact
import build_capacity
import ci_plan
import dependency_store
import github_release
import release
import rust_sdk
import sdk
from dependency_archive import digest, extract, read_json, write_json
from source_identity import source_tree, verify_source_archive


def lifecycle():
    spec = importlib.util.spec_from_file_location('rust_lifecycle', ROOT / '.github/scripts/lifecycle.py')
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def required(name):
    value = os.environ.get(name)
    if not value: raise ValueError('missing explicit qualification input: ' + name)
    return value


@contextmanager
def phase(name):
    print('Rust qualification phase start: ' + name, flush=True)
    try:
        yield
    except BaseException:
        print('Rust qualification phase failed: ' + name, flush=True)
        raise
    else:
        print('Rust qualification phase end: ' + name, flush=True)


def selection():
    target, recipe, rust_recipe = (required(name) for name in ('TARGET', 'RECIPE', 'FOUNDATION_OPTIONAL_PROVIDER_RECIPE'))
    if target not in ci_plan.RUST_RECIPES or not all(re.fullmatch(r'[0-9a-f]{64}', item) for item in (recipe, rust_recipe)):
        raise ValueError('qualification needs an exact native/browser and paired recipe selection')
    recipe_file = ROOT / ci_plan.RUST_RECIPES[target]
    if rust_sdk.recipe_identity(recipe_file) != rust_recipe:
        raise ValueError('Rust producer recipe differs from frozen workflow matrix')
    return target, recipe, rust_recipe, recipe_file


def plan():
    adapter = lifecycle()
    supplied = os.environ.get('RECIPES', '')
    recipes = json.loads(supplied) if supplied else {target: adapter.sdk_identity(target, 'all-gui')
                                                  for target in ci_plan.RUST_RECIPES}
    runners = ci_plan.runner_selection(os.environ.get('LINUX_POOL', 'standard'),
        os.environ.get('FOUNDATION_FASTER_LINUX_RUNNER', ''), os.environ.get('FOUNDATION_FASTER_ARM_RUNNER', ''),
        os.environ.get('FOUNDATION_FASTER_WINDOWS_RUNNER', ''))
    result = ci_plan.rust_qualification_matrix(recipes, runners=runners)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with Path(output).open('a', encoding='utf-8') as stream:
            stream.write('matrix=' + json.dumps(result, separators=(',', ':')) + '\n')
    print(json.dumps(result, indent=2))


def install_cpp(target, group, recipe, output):
    if target == 'windows-x86_64':
        import sdk_windows
        from windows_toolchain import inspect_selected_linker
        return sdk_windows.install(group, recipe, output, inspect_selected_linker()['version'])
    return sdk.install(group, recipe, output, production=True)


def prepare():
    target, recipe, rust_recipe, recipe_file = selection()
    if target != 'browser-wasm32': ci_plan.assert_host(target)
    retained = ROOT / 'build/retained'
    github_release.fetch_base(required('GITHUB_REPOSITORY'), recipe, retained / recipe)
    cpp = ROOT / 'build/preparation-cpp-sdk'
    install_cpp(target, retained / recipe, recipe, cpp)
    # This is the sole online Rust acquisition phase. Every later producer uses
    # retained supplier archives and fails when one is absent or changed.
    rust_sdk.fetch(recipe_file, ROOT / 'build/rust-inputs', network=True)
    rust_sdk.prepare(recipe_file, ROOT / 'build/rust-inputs', retained / rust_recipe, cpp_sdk=cpp)
    adapter = lifecycle(); verifier = ci_plan.gui_group_module()
    gui_group = ROOT / 'third_party/gui-inputs'
    verifier.verify(gui_group)
    restored = verifier.restore(gui_group, ROOT / 'build/gui-source')
    ci_plan.source_archive(ROOT / 'build/source.tar.gz', Path(restored['source']))
    if target == 'windows-x86_64':
        archive = ROOT / 'build/host-graphics/mesa-windows.7z'
        archive.parent.mkdir(parents=True)
        receipt = adapter.retained_graphics(required('GRAPHICS_ARCHIVE_URL'), archive)
        write_json(archive.parent / 'acquisition.json', receipt)
    write_json(ROOT / 'build/rust-preparation.json', {'schema_version': 1, 'target': target,
        'source_commit': required('GITHUB_SHA'), 'cpp_recipe': recipe, 'rust_recipe': rust_recipe,
        'cpp_files': dependency_store.verify_group(retained / recipe, recipe),
        'rust_files': rust_sdk.verify_group(retained / rust_recipe, rust_recipe)})


def replay(root, group, recipe, cpp):
    restored = root / 'rust-producer-inputs'
    rust_sdk.restore_sources(group, recipe, restored)
    rebuilt = root / 'rust-replayed-group'
    rust_sdk.prepare(restored / 'recipe/rust.json', restored / 'inputs', rebuilt, cpp_sdk=cpp)
    if rust_sdk.verify_group(rebuilt, recipe) != rust_sdk.verify_group(group, recipe):
        raise ValueError('retained Rust producer replay differs from frozen binary/source group')
    return {'status': 'passed', 'scope': 'retained-compiler-package-reassembly',
            'compiler_reconstructed_from_source': False, 'files': rust_sdk.verify_group(rebuilt, recipe)}


def windows_debug_pe(build, consumer):
    from verify_pe import audit
    names = ('foundation-cli', 'foundation_core_test', 'foundation_windows_arguments_test',
             'foundation_rust_component_test', 'foundation_text_status_test')
    paths = [*(build / (name + '.exe') for name in names), consumer]
    # Compiler-ID and try-compile probes are not produced application binaries.
    return {path.name: audit(path, static_crt=True) for path in paths}


def windows_debug(group, recipe, cpp, rust, source):
    import windows_compiler
    output = ROOT / 'build/rust-windows-debug'; output.mkdir()
    tests = ('core.store', 'core.cli', 'core.text_validation', 'core.text_status',
             'core.windows_arguments', 'rust.unit', 'integration.install')
    command = [sys.executable, '-B', str(source / 'tools/build.py'), 'test', 'dev', '--portable',
        '--build-dir', str(output / 'build'), '--build-jobs', str(build_capacity.compile_jobs(required('JOBS'))),
        '--test-jobs', '2', '--windows-dependencies', str(cpp), '--dependency-group', str(group),
        '--core-provider', 'rust', '--rust-sdk', str(rust), '--junit', str(output / 'source.junit.xml')]
    for name in tests: command += ['--test', name]
    windows_compiler.run(command, cwd=source)
    import test_plan
    results = test_plan.junit_results(output / 'source.junit.xml', list(tests))
    if set(results.values()) != {'passed'}: raise ValueError('Windows Debug core/Rust/consumer execution is incomplete')
    prefix = output / 'original-prefix'
    windows_compiler.run(['cmake', '--install', str(output / 'build'), '--config', 'Debug',
                          '--prefix', str(prefix)], cwd=source)
    relocated = output / 'relocated-prefix'; prefix.rename(relocated)
    configurations = list(relocated.rglob('FoundationConfig.cmake'))
    if len(configurations) != 1: raise ValueError('one relocated Debug Foundation configuration required')
    consumer = output / 'consumer-build'
    windows_compiler.run(['cmake', '-S', str(source / 'examples/consumer'), '-B', str(consumer), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Debug', '-DFoundation_DIR=' + str(configurations[0].parent),
        '-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF', '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF'], cwd=source)
    windows_compiler.run(['cmake', '--build', str(consumer), '--parallel', '2'], cwd=source)
    windows_compiler.run([str(consumer / 'consumer.exe')], cwd=relocated)
    pe = windows_debug_pe(output / 'build', consumer / 'consumer.exe')
    write_json(output / 'qualification.json', {'schema_version': 1, 'status': 'passed',
        'configuration': 'Debug', 'core_provider': 'rust', 'cpp_recipe': recipe,
        'source_tree_sha256': source_tree(source)['tree_sha256'], 'scope': 'core-rust-unit-installed-consumer-static-crt',
        'tests': list(tests), 'junit_sha256': digest(output / 'source.junit.xml'), 'pe': pe})


def qualify():
    target, recipe, rust_recipe, _ = selection()
    group, rust_group = (ROOT / 'build/retained' / value for value in (recipe, rust_recipe))
    output = ROOT / 'build/produced'
    entry = ci_plan.prepared_package(target, recipe, group, ROOT / 'build/source.tar.gz', output,
        build_capacity.compile_jobs(required('JOBS')),
        graphics_archive=ROOT / 'build/host-graphics/mesa-windows.7z' if target == 'windows-x86_64' else None,
        core_provider='rust', rust_group=rust_group, rust_recipe=rust_recipe)
    delivered = output / entry['path']; descriptor = output / entry['manifest_path']
    cpp = output / 'work' / ('dependencies' if target == 'windows-x86_64' else 'sdk')
    if target != 'browser-wasm32':
        package_backends = {}
        for backend in entry['backends']:
            options = {}
            if target == 'windows-x86_64' and backend == 'rev':
                options.update(windows_graphics_archive=ROOT / 'build/host-graphics/mesa-windows.7z',
                               windows_graphics_evidence=ROOT / 'build/rust-package-rev')
            result = artifact.verify(delivered, descriptor, runtime_only=True,
                sdk=cpp if target.startswith('linux-') else None, backend=backend, **options)
            package_backends[backend] = {'status': 'passed', 'details': result}
        write_json(ROOT / 'build/rust-package-backends.json', {'schema_version': 1, 'status': 'passed',
            'archive_sha256': entry['sha256'], 'target': target, 'backends': package_backends})
    if target == 'windows-x86_64':
        windows_debug(group, recipe, cpp, output / 'work/rust-sdk', output / 'work/source')
    source = ROOT / 'build/source.tar.gz'
    entry['path'] = str(output / entry['path']); entry['manifest_path'] = str(output / entry['manifest_path'])
    spec = {'schema_version': 1, 'source': {'path': str(source), 'sha256': digest(source)},
            'artifacts': [entry], 'required_scopes': ['source', 'archive', 'recovery']}
    write_json(ROOT / 'build/rust-candidate-spec.json', spec)
    candidate = ROOT / 'build/rust-candidate'
    release.assemble(ROOT / 'build/rust-candidate-spec.json', ROOT / 'build/retained', candidate)
    kit = ROOT / 'build/rust-recovery'
    release.recover(candidate, kit)
    recovery = release.verify_recovery(kit, digest(candidate / 'release.json'))
    write_json(ROOT / 'build/rust-recovery-inputs.json', recovery)
    installed = ROOT / 'build/rust-delivered'; installed.mkdir()
    if artifact.describe(delivered, installed) != read_json(descriptor):
        raise ValueError('delivered browser package differs during extraction')
    servers = list(installed.rglob('serve.py'))
    if len(servers) != 1: raise ValueError('delivered package needs one browser server')
    hosts = list(installed.rglob('foundation-gui-web.exe' if target == 'windows-x86_64' else 'foundation-gui-web'))
    wasm_modules = list(installed.rglob('gui_web_wasm.js'))
    if ((target == 'browser-wasm32' and len(wasm_modules) != 1)
            or (target != 'browser-wasm32' and len(hosts) != 1)):
        raise ValueError('delivered package needs one exact browser engine')
    if platform.system() == 'Linux':
        import release_check
        work = output / 'work'
        for engine in ('firefox',):
            evidence = ROOT / 'build' / ('rust-browser-' + engine); evidence.mkdir()
            options = {'browser': engine, 'firefox': '/usr/bin/firefox-esr'}
            result = release_check.browser_check(work / 'source', servers[0], evidence, options,
                wasm=wasm_modules[0].parent if target == 'browser-wasm32' else None,
                executable=None if target == 'browser-wasm32' else hosts[0])
            write_json(evidence / 'result.json', result)
    else:
        import release_check
        candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Mozilla Firefox/firefox.exe',
                      Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Mozilla Firefox/firefox.exe']
        installed = [path for path in candidates if path.is_file()]
        if len(installed) != 1: raise ValueError('native Windows browser qualification needs one preinstalled Firefox')
        evidence = ROOT / 'build/rust-browser-firefox'; evidence.mkdir()
        result = release_check.browser_check(output / 'work/source', servers[0], evidence,
                                             {'browser': 'firefox', 'firefox': str(installed[0])}, executable=hosts[0])
        write_json(evidence / 'result.json', result)
    write_json(ROOT / 'build/rust-qualification.json', {'schema_version': 1, 'status': 'passed',
        'scope': 'optional-provider-source-package-and-retained-recovery-inputs', 'target': target,
        'source_commit': required('GITHUB_SHA'), 'release_sha256': digest(candidate / 'release.json'),
        'artifact': entry, 'stable_publication': False})


def linux():
    if platform.system() != 'Linux' or not hasattr(os, 'getuid') or os.getuid() == 0:
        raise ValueError('Linux qualification needs an ordinary native hosted runner')
    spec = importlib.util.spec_from_file_location('rust_container', ROOT / '.github/scripts/container_job.py')
    container = importlib.util.module_from_spec(spec); spec.loader.exec_module(container)
    packages = tuple(dict.fromkeys((*container.COMMON, *container.BUILD, *container.GUI_RUNTIME,
                                    'pkg-config', 'firefox-esr', 'iproute2')))
    name = 'foundation-rust-setup-' + uuid.uuid4().hex
    image = None
    try:
        with phase('linux.docker-create'):
            subprocess.run(['docker', 'create', '--name', name, '-v', str(ROOT) + ':/work:ro', '-w', '/work',
                'debian:bookworm', 'bash', '-euc', container.bootstrap_script(packages)], check=True)
        with phase('linux.docker-start-attach'):
            subprocess.run(['docker', 'start', '--attach', name], check=True)
        with phase('linux.docker-commit'):
            image = subprocess.check_output(['docker', 'commit', name], text=True).strip()
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image): raise ValueError('invalid prepared Bookworm image identity')
        # Xvfb does not send its readiness signal to a PID1 xvfb-run parent.
        command = ['docker', 'run', '--init', '--rm', '--pull=never', '--user', f'{os.getuid()}:{os.getgid()}',
                   '-v', str(ROOT) + ':/work', '-w', '/work', '--tmpfs', '/tmp:rw,exec,nosuid,nodev,mode=1777']
        for key in ('TARGET', 'RECIPE', 'FOUNDATION_OPTIONAL_PROVIDER_RECIPE', 'JOBS', 'GITHUB_SHA'):
            command += ['-e', key]
        command += ['-e', 'HOME=/tmp/rust-qualification-home', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                    '-e', 'LIBGL_ALWAYS_SOFTWARE=1', image, 'xvfb-run', '-a', 'python3', '-u', '-B',
                    '.github/scripts/rust_qualification.py', 'qualify']
        with phase('linux.docker-qualify'):
            subprocess.run(command, cwd=ROOT, check=True)
        if selection()[0] == 'browser-wasm32': host_chromium()
        replay_output = ROOT / 'build/rust-replay'; replay_output.mkdir()
        replay_command = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user', f'{os.getuid()}:{os.getgid()}',
            '--tmpfs', '/tmp:rw,mode=1777', '-v', str(ROOT) + ':/work:ro',
            '-v', str(replay_output) + ':/output', '-w', '/work']
        for key in ('TARGET', 'RECIPE', 'FOUNDATION_OPTIONAL_PROVIDER_RECIPE', 'JOBS', 'GITHUB_SHA'): replay_command += ['-e', key]
        replay_command += ['-e', 'HOME=/tmp/rust-replay-home', '-e', 'PYTHONDONTWRITEBYTECODE=1', image,
                          'python3', '-u', '-B', '.github/scripts/rust_qualification.py', 'linux-replay']
        with phase('linux.docker-replay'):
            subprocess.run(replay_command, cwd=ROOT, check=True)
        with phase('linux.offline'):
            offline(image)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], check=True)
        if image and re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            subprocess.run(['docker', 'image', 'rm', image], check=True)


def offline(image):
    import offline_acceptance
    target, recipe, rust_recipe, _ = selection()
    kit = ROOT / 'build/rust-recovery'
    release.verify_recovery(kit, digest(ROOT / 'build/rust-candidate/release.json'))
    metadata = read_json(kit / 'release.json')
    source = ROOT / 'build/recovered-source'; extract(kit / metadata['source']['archive'], source)
    if source_tree(source) != verify_source_archive(kit / metadata['source']['archive']):
        raise ValueError('recovered source differs from retained source inventory')
    plan = {'schema_version': 1, 'isolation': {'kind': 'docker', 'image': image}, 'cases': [
        {'target': target, 'core_provider': 'rust', 'group': str(kit / 'dependencies' / recipe), 'recipe': recipe,
         'rust_group': str(kit / 'dependencies' / rust_recipe), 'rust_recipe': rust_recipe}]}
    path = ROOT / 'build/rust-offline-plan.json'; write_json(path, plan)
    offline_acceptance.run(path, ROOT / 'build/rust-offline', cases=[target],
                           jobs=build_capacity.compile_jobs(required('JOBS')), root=source)


def denial_probe():
    denied = []
    for address in ('1.1.1.1', '8.8.8.8'):
        try:
            with socket.create_connection((address, 443), timeout=3):
                raise ValueError('offline firewall allowed an external TCP connection')
        except OSError as error:
            denied.append({'address': address, 'port': 443, 'error': type(error).__name__})
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=3):
            connection, _ = listener.accept(); connection.close()
    return {'external_tcp_denied': denied, 'loopback': 'passed'}


def windows_online_probe():
    successes = []
    for address in ('1.1.1.1', '8.8.8.8'):
        try:
            with socket.create_connection((address, 443), timeout=5):
                successes.append({'address': address, 'port': 443})
        except OSError:
            pass
    if not successes: raise ValueError('no positive external TCP control before the Windows firewall boundary')
    write_json(ROOT / 'build/rust-windows-online.json', {'schema_version': 1, 'external_tcp_succeeded': successes})


def linux_replay():
    target, recipe, rust_recipe, _ = selection()
    output = Path('/output')
    probe = denial_probe()
    kit = ROOT / 'build/rust-recovery'
    release.verify_recovery(kit, digest(ROOT / 'build/rust-candidate/release.json'))
    cpp = output / 'cpp-sdk'; install_cpp(target, kit / 'dependencies' / recipe, recipe, cpp)
    result = replay(output, kit / 'dependencies' / rust_recipe, rust_recipe, cpp)
    result.update(isolation='docker-network-none-read-only-rootfs', network_probe=probe,
                  source_commit=required('GITHUB_SHA'), target=target)
    write_json(output / 'qualification.json', result)


def host_chromium():
    import release_check
    selected = ci_plan.browser_prerequisite('browser-wasm32', 'chromium', 'wasm')
    before = ci_plan.inspect_host_chromium(selected)
    installed = ROOT / 'build/rust-delivered'
    servers = list(installed.rglob('serve.py')); modules = list(installed.rglob('gui_web_wasm.js'))
    if len(servers) != 1 or len(modules) != 1:
        raise ValueError('host browser needs one exact delivered Emscripten package')
    evidence = ROOT / 'build/rust-browser-chromium'; evidence.mkdir()
    result = release_check.browser_check(ROOT / 'build/produced/work/source', servers[0], evidence,
        {'browser': 'chromium', 'browser_executable': before[0]['executable'], 'driver': before[1]['executable']},
        wasm=modules[0].parent)
    if ci_plan.inspect_host_chromium(selected) != before:
        raise ValueError('actual hosted browser or driver changed during qualification')
    result['prerequisites'] = before
    write_json(evidence / 'result.json', result)


def windows_offline():
    if (platform.system() != 'Windows' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('FOUNDATION_WINDOWS_OFFLINE_RULE') is None):
        raise ValueError('native offline probe requires its active disposable hosted firewall boundary')
    target, recipe, rust_recipe, _ = selection()
    if target != 'windows-x86_64': raise ValueError('native Windows offline probe needs the Windows target')
    probe = denial_probe()
    kit = ROOT / 'build/rust-recovery'
    release.verify_recovery(kit, digest(ROOT / 'build/rust-candidate/release.json'))
    metadata = read_json(kit / 'release.json')
    output = ROOT / 'build/rust-windows-offline'; output.mkdir()
    source = output / 'source'; extract(kit / metadata['source']['archive'], source)
    if source_tree(source) != verify_source_archive(kit / metadata['source']['archive']):
        raise ValueError('recovered Windows source differs from retained source inventory')
    cpp = output / 'cpp-sdk'; install_cpp(target, kit / 'dependencies' / recipe, recipe, cpp)
    replay_receipt = replay(output, kit / 'dependencies' / rust_recipe, rust_recipe, cpp)
    rust = output / 'rust-sdk'; rust_sdk.install(kit / 'dependencies' / rust_recipe, rust_recipe, rust, cpp_sdk=cpp, execute=True)
    build = output / 'build'
    base = [sys.executable, '-B', str(source / 'tools/build.py')]
    flags = ['release', '--portable', '--build-dir', str(build), '--build-jobs', str(build_capacity.compile_jobs(required('JOBS'))),
             '--windows-dependencies', str(cpp), '--dependency-group', str(kit / 'dependencies' / recipe),
             '--core-provider', 'rust', '--rust-sdk', str(rust)]
    environment = dict(os.environ, HOME=str(output / 'home'), CARGO_HOME=str(output / 'cargo-home'),
                       RUSTUP_HOME=str(output / 'rustup-home'), CARGO_NET_OFFLINE='true')
    subprocess.run([*base, 'test', *flags, '--label', 'core', '--junit', str(output / 'core.junit.xml')],
                   cwd=source, env=environment, check=True)
    subprocess.run([sys.executable, '-B', str(source / 'tests/check_install.py'), '--build', str(build),
                    '--source', str(source), '--config', 'Release'], cwd=source, env=environment, check=True)
    subprocess.run([*base, 'package', *flags], cwd=source, env=environment, check=True)
    choices = ci_plan.archives(build / 'packages', recursive=False)
    if len(choices) != 1: raise ValueError('one native Windows offline package required')
    descriptor = choices[0].with_name(choices[0].name + '.json'); write_json(descriptor, artifact.describe(choices[0]))
    artifact.verify(choices[0], descriptor)
    if source_tree(source) != verify_source_archive(kit / metadata['source']['archive']):
        raise ValueError('Windows retained source changed during disconnected build')
    write_json(output / 'qualification.json', {'schema_version': 1, 'status': 'passed', 'target': target,
        'core_provider': 'rust', 'scope': 'native-disconnected-core-installed-consumer-package',
        'full_gui_regression_offline': False, 'firewall_rule': required('FOUNDATION_WINDOWS_OFFLINE_RULE'),
        'probe': probe, 'probe_after': denial_probe(), 'rust_replay': replay_receipt,
        'source_tree_sha256': metadata['source']['tree_sha256'], 'release_sha256': digest(kit / 'release.json')})


def supervise_windows_offline():
    from process_tree import launch
    log = ROOT / 'build/rust-windows-offline.log'
    with log.open('xb') as stream:
        owner = launch([sys.executable, '-B', str(Path(__file__).resolve()), 'windows-offline'], ROOT, stream)
        try:
            owner.wait(timeout=600)
            code = owner.finish()
        finally:
            owner.close()
    if code:
        print(log.read_text(encoding='utf-8', errors='replace')[-16000:])
        raise ValueError('native disconnected Windows qualification failed; inspect retained log')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'prepare', 'qualify', 'linux', 'linux-replay', 'windows-online-probe',
                                         'windows-offline', 'supervise-windows-offline'))
    args = parser.parse_args()
    action = globals()[args.action.replace('-', '_')]
    if platform.system() == 'Linux' and args.action in ('linux', 'qualify', 'linux-replay'):
        print('Rust qualification diagnostic snapshots every 300 seconds: faulthandler timer dumps '
              'are observations, not command timeouts or qualification failures.', flush=True)
        faulthandler.dump_traceback_later(300, repeat=True)
        try:
            action()
        finally:
            faulthandler.cancel_dump_traceback_later()
    else:
        action()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Rust qualification: ' + str(error), file=sys.stderr)
        sys.exit(1)
