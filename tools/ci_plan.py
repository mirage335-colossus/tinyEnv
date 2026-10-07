#!/usr/bin/env python3
"""Checked CI scheduling and package operations shared with local development."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STANDARD = {"linux-x86_64": "ubuntu-24.04", "linux-aarch64": "ubuntu-24.04-arm",
            "windows-x86_64": "windows-2022"}
RUST_RECIPES = {'linux-x86_64': 'third_party/rust/linux-x86_64.json',
                'linux-aarch64': 'third_party/rust/linux-aarch64.json',
                'windows-x86_64': 'third_party/rust/windows-x86_64.json',
                'browser-wasm32': 'third_party/rust/wasm32-emscripten.json'}


def plan(devfast=False, include_arm=True, pool="standard", configured="", configured_arm="", configured_windows=""):
    if pool not in ("standard", "faster"):
        raise ValueError("unknown runner pool")
    chosen = {"linux-x86_64": configured, "linux-aarch64": configured_arm, "windows-x86_64": configured_windows}
    prefixes = {"linux-x86_64": "linux", "linux-aarch64": "arm", "windows-x86_64": "windows"}
    if pool == "faster" and (not any(chosen.values()) or any(value and not re.fullmatch("foundation-" + prefixes[target] + "-[a-z0-9-]+", value) for target,value in chosen.items())):
        raise ValueError("explicit authorized larger-runner label required")
    targets = [x for x in STANDARD if include_arm or x != "linux-aarch64"]
    packages, checks = [], []
    for target in targets:
        runner = chosen[target] if pool == "faster" and chosen[target] else STANDARD[target]
        packages.append({"target": target, "runner": runner})
        for scope in (["core"] if devfast else ["core", "tools", "integration"]):
            checks.append({"target": target, "runner": runner, "scope": scope})
    return {"checks": {"include": checks}, "packages": {"include": packages}}


def assert_host(target):
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    system = platform.system().lower()
    if target != system + "-" + machine:
        raise ValueError("actual host differs from selected execution target")
    return {"target": target, "system": system, "machine": machine, "release": platform.release(),
            "python": platform.python_version()}


def run(args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def archives(directory, recursive=True):
    find = directory.rglob if recursive else directory.glob
    values = sorted(list(find("*.tar.gz")) + list(find("*.zip")))
    if not values:
        raise ValueError("no application archives found")
    names = [x.name for x in values]
    if len(names) != len(set(names)):
        raise ValueError("duplicate application archive names")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--devfast", action="store_true")
    p.add_argument("--no-arm", action="store_true")
    p.add_argument("--pool", choices=("standard", "faster"), default="standard")
    p.add_argument("--configured", default="")
    p.add_argument("--configured-arm", default="")
    p.add_argument("--configured-windows", default="")
    p.add_argument("--github-output", type=Path)
    p = sub.add_parser("host")
    p.add_argument("target", choices=tuple(STANDARD))
    p = sub.add_parser("package")
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--jobs", type=module("build_capacity").compile_jobs, default="auto")
    p.add_argument("--core-provider", choices=("rust", "cpp"), default="rust")
    p.add_argument("--rust-sdk", type=Path)
    p = sub.add_parser("check-archives")
    p.add_argument("directory", type=Path)
    p.add_argument("--runtime-only", action="store_true")
    p = sub.add_parser("workflow-lint")
    p.add_argument("--retained-url", default="")
    p.add_argument("--executable", default="")
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = plan(args.devfast, not args.no_arm, args.pool, args.configured, args.configured_arm, args.configured_windows)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as out:
                for key, value in result.items():
                    out.write(key + "=" + json.dumps(value, separators=(",", ":")) + "\n")
        print(json.dumps(result, indent=2))
    elif args.command == "workflow-lint":
        workflow_lint(args.output, retained_url=args.retained_url, executable=args.executable)
    elif args.command == "host":
        print(json.dumps(assert_host(args.target)))
    elif args.command == "package":
        if args.jobs < 1:
            raise ValueError("positive compile concurrency required")
        run([sys.executable, "tools/build.py", "package", "release", "--portable", "--build-dir", args.build,
             "--jobs", str(args.jobs), "--core-provider", args.core_provider,
             *(["--rust-sdk", str(args.rust_sdk)] if args.rust_sdk is not None else [])])
        for archive in archives(args.build / "packages", recursive=False):
            manifest = archive.with_name(archive.name + ".json")
            for operation in ("create", "verify"):
                run([sys.executable, "tools/artifact.py", operation, archive, "--manifest", manifest])
    else:
        for archive in archives(args.directory):
            run([sys.executable, "tools/artifact.py", "verify", archive,
                 "--manifest", archive.with_name(archive.name + ".json"),
                 *(["--runtime-only"] if args.runtime_only else [])])



# Lifecycle operations use the same validators as local release preparation.

ACTIONLINT_SHA256 = '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8'


def workflow_lint(output, *, retained_url='', executable=''):
    """Require an installed validator or explicitly retained exact archive; no upstream fallback."""
    import io
    import shutil
    import tarfile
    import urllib.parse
    import urllib.request
    c = module('coverage')
    output = Path(output)
    tool = executable or shutil.which('actionlint')
    origin = 'installed'
    if not tool:
        def checked_url(url):
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('retained validator requires credential-free HTTPS')
            return url
        checked_url(retained_url)
        class SecureRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                checked_url(newurl)
                return super().redirect_request(request, fp, code, msg, headers, newurl)
        try:
            with urllib.request.build_opener(SecureRedirect()).open(retained_url, timeout=60) as response:
                data = response.read(32*1024*1024+1)
        except Exception as error:
            raise ValueError('retained validator transfer failed; inspect configured prerequisite') from error
        if len(data)>32*1024*1024 or __import__('hashlib').sha256(data).hexdigest()!=ACTIONLINT_SHA256:
            raise ValueError('retained validator archive differs from pinned identity')
        output.mkdir(parents=True,exist_ok=False)
        tool=output/'actionlint'
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members=[member for member in archive.getmembers() if member.name=='actionlint']
            if len(members)!=1 or not members[0].isfile() or members[0].size>32*1024*1024:
                raise ValueError('retained validator archive has invalid executable')
            with tool.open('xb') as stream: stream.write(archive.extractfile(members[0]).read())
        tool.chmod(0o755);origin='retained-exact-archive'
    else:
        tool=Path(tool).resolve(strict=True)
        output.mkdir(parents=True,exist_ok=False)
    version=subprocess.run([str(tool),'-version'],check=True,capture_output=True,text=True).stdout.splitlines()
    if not version or version[0].strip()!='1.7.12':
        raise ValueError('installed validator version differs from qualified prerequisite')
    files=sorted((ROOT/'.github/workflows').glob('*.yml'))
    if not files: raise ValueError('no workflow files')
    before = {'tool':c.sha(tool), 'workflows':{p.name:c.sha(p) for p in files}}
    subprocess.run([str(tool),'-shellcheck=','-pyflakes=',*map(str,files)],check=True)
    if before != {'tool':c.sha(tool), 'workflows':{p.name:c.sha(p) for p in files}}:
        raise ValueError('validator or workflow inputs changed during validation')
    result=dict(schema_version=1,status='passed',version=version[0],origin=origin,
                executable_sha256=c.sha(tool),workflows={p.name:c.sha(p) for p in files})
    c.write_new(output/'qualification.json',result)
    return result


def module(name):
    import importlib.util
    if str(ROOT / 'tools') not in sys.path: sys.path.insert(0, str(ROOT / 'tools'))
    spec = importlib.util.spec_from_file_location('ci_' + name, ROOT / 'tools' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def exact_commit(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise ValueError('complete source commit required')
    return value


def runner_selection(pool='standard', configured='', configured_arm='', configured_windows=''):
    return {row['target']: row['runner'] for row in plan(pool=pool, configured=configured, configured_arm=configured_arm, configured_windows=configured_windows)['packages']['include']}


def rust_recipe(target):
    if target not in RUST_RECIPES:
        raise ValueError('no qualified Rust recipe for target')
    rust = module('rust_sdk'); path = ROOT / RUST_RECIPES[target]
    rust.checked_recipe(path)
    return rust.recipe_identity(path)


def rust_base_names(recipe):
    return module('rust_sdk').group_names(recipe)


def release_matrix(recipes, profile='core', policy=None, *, runners=None, core_provider='rust'):
    if core_provider not in ('rust', 'cpp'):
        raise ValueError('unknown core provider')
    policy = policy or module('coverage').load(ROOT / 'docs/release-policy.json')
    selected, _ = module('certify_release').requirements(policy, profile)
    if not isinstance(recipes, dict) or set(recipes) != set(selected['targets']):
        raise ValueError('recipe map must cover exactly the selected target inventory')
    if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in recipes.values()):
        raise ValueError('every target requires its complete prepared recipe')
    if profile == 'all-gui':
        lock = module('coverage').load(ROOT / 'third_party/gui-boundary.lock.json')
        if lock.get('redistribution', {}).get('approved') is not True:
            raise ValueError('GUI redistribution licensing must be resolved before producing release assets')
    runners = STANDARD if runners is None else runners
    if set(runners) != set(STANDARD): raise ValueError('complete runner selection required')
    rows = []
    for target, backends in selected['targets'].items():
        if target not in (*STANDARD, 'browser-wasm32'):
            raise ValueError('no qualified runner adapter for target')
        if core_provider == 'rust' and target == 'browser-wasm32':
            paired = module('rust_sdk').checked_recipe(ROOT / RUST_RECIPES[target])
            if paired['cpp_sdk_recipe_id'] != recipes[target]:
                raise ValueError('browser Rust recipe requires its exact matched C++ SDK recipe')
        rows.append({'target': target, 'runner': runners.get(target, runners['linux-x86_64']),
                     'recipe': recipes[target], 'backends': backends,
                     'container': 'debian:bookworm' if target.startswith('linux-') else '',
                     'core_provider': core_provider,
                     'rust_recipe': rust_recipe(target) if core_provider == 'rust' else ''})
    return {'include': rows}


def rust_qualification_matrix(recipes, *, runners=None):
    """An explicit complete optional-provider lane, with no publication adapter."""
    if not isinstance(recipes, dict) or set(recipes) != set(RUST_RECIPES):
        raise ValueError('Rust qualification requires every native and browser target')
    rows = release_matrix(recipes, 'all-gui', runners=runners)['include']
    rust = module('rust_sdk')
    for row in rows:
        path = ROOT / RUST_RECIPES[row['target']]
        rust.checked_recipe(path)
        row.update(core_provider='rust', rust_recipe=rust.recipe_identity(path),
                   rust_recipe_file=RUST_RECIPES[row['target']])
    return {'include': rows}


def source_archive(output, gui_source=None):
    module('source_identity').archive_source(ROOT, output, gui_source)
    return {'archive': str(output), 'sha256': module('coverage').sha(output)}


def rust_selection(core_provider, rust_group, rust_recipe):
    if core_provider not in ('cpp', 'rust'):
        raise ValueError('unknown core provider')
    if core_provider == 'cpp':
        if rust_group is not None or rust_recipe is not None:
            raise ValueError('C++ selection must omit Rust SDK inputs')
        return None
    if rust_group is None or not isinstance(rust_recipe, str) or not re.fullmatch(r'[0-9a-f]{64}', rust_recipe):
        raise ValueError('Rust selection requires one exact retained SDK group')
    return module('rust_sdk').verify_group(Path(rust_group), rust_recipe)


def install_rust_input(core_provider, rust_group, rust_recipe, output, cpp_sdk):
    if core_provider == 'cpp':
        return ['--core-provider', 'cpp'], {'core_provider': 'cpp'}
    rust = module('rust_sdk')
    rust.install(Path(rust_group), rust_recipe, output)
    metadata = rust.verify_rust_sdk(output, cpp_sdk=cpp_sdk, execute=True)
    identity = {'core_provider': 'rust', 'rust_sdk_recipe_id': rust_recipe,
                'rust_compiler_version': metadata['compiler']['version'],
                'rust_target': metadata['target']['triple'],
                'rust_sdk_manifest_sha256': module('coverage').sha(output / 'rust-sdk.json'),
                'rust_compiler_sha256': module('coverage').sha(output / metadata['compiler']['rustc'])}
    return ['--core-provider', 'rust', '--rust-sdk', str(output)], identity


def prepared_package(target, recipe, group, source, output, jobs=2, *, graphics_archive=None, expected_files=None,
                     core_provider='rust', rust_group=None, rust_recipe=None):
    import shutil
    from dependency_archive import extract
    from dependency_store import verify_group
    if target != 'browser-wasm32':
        assert_host(target)
    elif platform.system() != 'Linux':
        raise ValueError('prepared browser producer requires its declared Linux host')
    if graphics_archive is not None and target != 'windows-x86_64':
        raise ValueError('retained host graphics input applies only to Windows GUI production')
    if jobs < 1 or output.exists():
        raise ValueError('positive concurrency and new package output required')
    rust_files = rust_selection(core_provider, rust_group, rust_recipe)
    if expected_files is None: verify_group(group, recipe)
    else: module('dependency_store').verify_binary_group(group, recipe, expected_files)
    manifest = module('source_identity').verify_source_archive(source)
    output.mkdir(parents=True)
    work = output / 'work'
    extract(source, work / 'source')
    root = work / 'source'
    build = work / 'build'
    command = [sys.executable, str(root / 'tools/build.py'), 'test', 'release', '--full',
               '--portable', '--build-dir', str(build), '--build-jobs', str(jobs), '--test-jobs', '2', '--junit', str(output / 'source.junit.xml')]
    if target == 'windows-x86_64':
        version = module('windows_toolchain').inspect_selected_linker()['version']
        options = {} if expected_files is None else {'expected_files': expected_files}
        sdk_metadata = module('sdk_windows').install(group, recipe, work / 'dependencies', version, **options)
        command += ['--binary-dependency-group' if expected_files is not None else '--dependency-group',
                    str(group), '--windows-dependencies', str(work / 'dependencies')]
    else:
        options = {} if expected_files is None else {'expected_files': expected_files}
        sdk_metadata = module('sdk').install(group, recipe, work / 'sdk', production=True, **options)
        command += ['--sdk', str(work / 'sdk')]
    rust_flags, provider = install_rust_input(core_provider, rust_group, rust_recipe, work / 'rust-sdk',
                                            work / 'dependencies' if target == 'windows-x86_64' else work / 'sdk')
    command += rust_flags
    gui = root / 'third_party/retained/gui'
    if gui.is_dir():
        backends = ['wasm'] if target == 'browser-wasm32' else ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']
        capabilities = sdk_metadata.get('capabilities', ['wasm'] if target == 'browser-wasm32' else ['core', 'terminal', 'framebuffer', 'hosted-web'])
        if not set(backends) <= set(capabilities):
            raise ValueError('prepared SDK lacks required GUI capabilities; select the explicit GUI recipe')
        command += ['--gui-source', str(gui), '--gui-backends', ','.join(backends)]
        if target != 'browser-wasm32': command += ['--host-tests']
    else:
        backends = []
        if target == 'browser-wasm32': raise ValueError('browser target requires retained GUI source')
    graphics_needed = target == 'windows-x86_64' and 'rev' in backends
    if graphics_needed != (graphics_archive is not None):
        raise ValueError('Windows GUI production requires one explicit retained host graphics archive; core must omit it')
    graphics_evidence = None
    if graphics_needed:
        module('windows_graphics').verify_archive(Path(graphics_archive))
        graphics_evidence = windows_gui_qualification(command, Path(graphics_archive), build, output, jobs,
            protected_roots=(Path(group).resolve(), root, work / 'dependencies'), cwd=root)
    else:
        subprocess.run(command, cwd=root, check=True)
    # Host DLLs must already be removed before installation or package creation.
    package_command = command.copy()
    package_command[2] = 'package'
    package_command.remove('--full')
    index = package_command.index('--junit')
    del package_command[index:index + 2]
    subprocess.run(package_command, cwd=root, check=True)
    choices = sorted((build / 'packages').glob('*.zip' if target.startswith('windows-') else '*.tar.gz'))
    if len(choices) != 1:
        raise ValueError('producer needs one exact platform archive')
    archive = output / (target + ('.tar.gz' if choices[0].name.endswith('.tar.gz') else '.zip'))
    shutil.copyfile(choices[0], archive)
    a = module('artifact')
    descriptor = archive.with_name(archive.name + '.json')
    module('coverage').write_new(descriptor, a.describe(archive))
    a.verify(archive, descriptor, sdk=work / 'sdk' if (work / 'sdk/sdk.json').is_file() else None,
             abi=target.startswith('linux-'), processor=target.split('-', 1)[1])
    if module('source_identity').source_tree(root) != manifest:
        raise ValueError('source changed during prepared application production')
    entry = {'path': archive.name, 'sha256': module('coverage').sha(archive),
             'manifest_path': descriptor.name, 'target': target, 'backends': backends,
             'sdk_recipe': recipe, 'dependency_recipes': [recipe]}
    entry.update(provider)
    if rust_recipe:
        entry['dependency_recipes'].append(rust_recipe)
        if module('rust_sdk').verify_group(Path(rust_group), rust_recipe) != rust_files:
            raise ValueError('Rust SDK group changed during application production')
    if core_provider == 'rust':
        module('release').validate_package(archive, entry, manifest['tree_sha256'], module('coverage').load(descriptor))
    if graphics_evidence is not None:
        module('coverage').write_new(output / 'graphics-qualification.json',
            {'schema_version': 1, 'status': 'passed', 'target': target, 'backends': backends,
             'archive_sha256': entry['sha256'], 'evidence': graphics_evidence})
    module('coverage').write_new(output / 'artifact.json', entry)
    return entry


def assemble_release(source, packages, base, output, profile):
    c = module('coverage')
    selected, _ = module('certify_release').requirements(c.load(ROOT / 'docs/release-policy.json'), profile)
    entries = []
    for path in sorted(packages.glob('*/artifact.json')):
        value = c.load(path)
        for field in ('path', 'manifest_path'):
            # Transport descriptors contain names, never producer-host paths.
            # Validate instead of sanitizing a foreign path into a trusted name.
            name = module('github_release').valid_name(value[field])
            value[field] = str(module('dependency_archive').checked_file(path.parent, name).resolve())
        entries.append(value)
    observed = {x['target']: x['backends'] or ['core'] for x in entries}
    if len(entries) != len(observed) or observed != selected['targets']:
        raise ValueError('missing, duplicate or unexpected producer target/backend inventory')
    spec = {'schema_version': 1, 'source': {'path': str(source.resolve()), 'sha256': c.sha(source)},
            'artifacts': entries, 'required_scopes': sorted({x['scope'] for x in selected['checks']})}
    spec_path = output.parent / 'assembly.json'
    c.write_new(spec_path, spec)
    return module('release').assemble(spec_path, base, output)


def fetch_candidate(repository, tag, inventory, output, transport=None, *, metadata_only=False, planning=False, workflow_context=None):
    import tempfile
    g = module('github_release')
    c = module('coverage')
    g.location(repository, tag)
    if type(planning) is not bool or planning and not metadata_only:
        raise ValueError('planning requires metadata-only acquisition')
    if workflow_context is not None and (not planning or not g.workflow_context_matches(workflow_context) or workflow_context['repository'] != repository):
        raise ValueError('snapshot context must identify this exact planning workflow')
    if not re.fullmatch(r'[0-9a-f]{64}', inventory) or output.exists() or output.is_symlink():
        raise ValueError('exact inventory digest and new candidate destination required')
    remote = g.Remote(repository, transport)
    remote.visible()
    before = remote.published(tag)
    assets = remote.assets(before)
    if 'delivery.json' not in assets:
        raise ValueError('published delivery descriptor is absent')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp)
        remote.download(assets['delivery.json'], staged / 'delivery.json')
        delivery = c.load(staged / 'delivery.json')
        if delivery.get('repository') != repository or delivery.get('tag') != tag or delivery.get('inventory_sha256') != inventory:
            raise ValueError('candidate differs from requested identity')
        if not isinstance(delivery.get('files'), dict) or not delivery['files']:
            raise ValueError('missing complete delivery file map')
        candidate = staged / 'candidate'; candidate.mkdir()
        selections = []
        for name, entry in delivery['files'].items():
            if metadata_only and name != 'release.json': continue
            path = c.local(candidate, name); path.parent.mkdir(parents=True, exist_ok=True)
            selections.append((entry['asset'], path, entry['sha256']))
        g.download_files(remote, assets, selections)
        # The descriptor and selected bytes above already came from this exact
        # observed inventory. Validate it locally, then reconcile once after all
        # optional planning payloads finish; do not download the descriptor again.
        g.validate_delivery(delivery,candidate,metadata_only=metadata_only)
        g.validate_remote_inventory(delivery,before,assets)
        if remote.reference(tag) != delivery['tag_commit']:
            raise ValueError('tag commit differs from frozen delivery')
        info, verified_assets = before, assets
        if planning:
            manifest = module('release').verify_metadata(candidate)
            source = manifest['source']['archive']; item = delivery['files'][source]
            remote.download(verified_assets[item['asset']], candidate / source, item['sha256'])
            retained = module('source_identity').verify_source_archive(candidate / source)
            if retained['tree_sha256'] != manifest['source']['tree_sha256']:
                raise ValueError('retained source tree differs from frozen inventory')
            snapshot = dict(schema_version=1, repository=repository, tag=tag,
                inventory_sha256=inventory, delivery_sha256=g.sha(module('dependency_archive').encoded(delivery)),
                release={key: info[key] for key in ('id', 'tag_name', 'name', 'draft', 'prerelease')}, assets=verified_assets)
            if workflow_context is not None:
                snapshot.update(schema_version=2, workflow_context=dict(workflow_context), repository_private=remote.private)
            c.write_new(staged / 'candidate-remote.json', snapshot)
        remote.unchanged(tag, before, assets, delivery['tag_commit'])
        staged.rename(output)
    return delivery




def fetch_candidate_payloads(repository, tag, inventory, candidate, identity, frozen, plan, check_ids, *, transport=None, trusted_context=None):
    """Restore pinned bytes; authenticated same-run controls avoid remote rescans.

    Only pass trusted_context after restoring producer-validated workflow controls.
    Final attachment/promotion still reconciles the complete live release identity.
    """
    import tempfile
    g = module('github_release'); c = module('coverage'); a = module('dependency_archive')
    candidate = Path(candidate).absolute()
    g.location(repository, tag); g.validate_delivery(identity, candidate, metadata_only=True)
    version = frozen.get('schema_version') if isinstance(frozen,dict) else None
    fields = {'schema_version', 'repository', 'tag', 'inventory_sha256', 'delivery_sha256', 'release', 'assets'}
    if version == 2: fields |= {'workflow_context','repository_private'}
    c.fields(frozen,fields)
    trusted = trusted_context is not None
    if (version == 2 and type(frozen['repository_private']) is not bool or trusted and
            (version != 2 or not g.workflow_context_matches(trusted_context) or
             trusted_context != frozen['workflow_context'] or trusted_context['repository'] != repository or
             plan['inputs'].get('build/candidate-remote.json') != g.sha(a.encoded(frozen)) or
             plan['inputs'].get('build/delivery.json') != g.sha(a.encoded(identity)))):
        raise ValueError('trusted candidate snapshot differs from authenticated workflow controls')
    if (type(version) is not int or version not in (1,2) or frozen['repository'] != repository or frozen['tag'] != tag or
            frozen['inventory_sha256'] != inventory or identity['repository'] != repository or
            identity['tag'] != tag or identity['inventory_sha256'] != inventory or
            frozen['delivery_sha256'] != g.sha(a.encoded(identity)) or
            plan['subject']['inventory_sha256'] != inventory):
        raise ValueError('published qualification inputs differ from frozen candidate')
    c.validate(plan)
    g.Remote.info(frozen['release'], tag)
    if frozen['release']['draft'] or frozen['release']['name'] != ('experiment' if identity['experiment'] else tag):
        raise ValueError('qualification requires the frozen published candidate')
    manifest = module('release').verify_metadata(candidate)
    declared = {'build/candidate/' + name: digest for name, digest in manifest['files'].items()}
    if (any(plan['inputs'].get(name) != digest for name, digest in declared.items()) or
            {name for name in plan['inputs'] if name.startswith('build/candidate/')} != set(declared) | {'build/candidate/release.json'} or
            plan['inputs']['build/candidate/release.json'] != inventory):
        raise ValueError('frozen qualification inventory is incomplete')
    checks = {item['id']: item for item in c.executions(plan)}
    if not check_ids or len(set(check_ids)) != len(check_ids) or any(name not in checks for name in check_ids):
        raise ValueError('unknown or duplicate qualification execution')
    names = sorted({name for check in check_ids for name in module('release').required_files(manifest,
        checks[check]['target'], checks[check]['backend'], checks[check]['scope'],
        binary_source=checks[check].get('sdk_payload') == 'binary')})
    assets = frozen['assets']
    expected = {item['asset'] for item in identity['files'].values()} | {'delivery.json'}
    if not isinstance(assets, dict) or not expected <= assets.keys():
        raise ValueError('frozen candidate asset inventory is incomplete')
    g.evidence_pairs(set(assets) - expected)
    for item in identity['files'].values():
        row = assets[item['asset']]
        if row['digest'] != 'sha256:' + item['sha256'] or row['size'] != item['size']:
            raise ValueError('frozen asset differs from complete delivery')
    if assets['delivery.json']['digest'] != 'sha256:' + frozen['delivery_sha256']:
        raise ValueError('frozen delivery asset differs')
    for name in names:
        destination = candidate / a.relative(name)
        if destination.exists() or destination.is_symlink():
            raise ValueError('candidate payload restore refuses an existing file: ' + name)
        for parent in destination.parents:
            _bundle_directory(parent)
            if parent == candidate.parent: break
    remote = g.Remote(repository, transport)
    if trusted:
        remote.pin_published(frozen['release'],assets,frozen['repository_private'])
    else:
        remote.visible()
        remote.unchanged(tag, frozen['release'], assets, identity['tag_commit'])
    with tempfile.TemporaryDirectory(prefix='.qualification-payload-', dir=candidate.parent) as temporary:
        staged = Path(temporary); selections = []
        for name in names:
            path = staged / a.relative(name); path.parent.mkdir(parents=True, exist_ok=True)
            item = identity['files'][name]
            selections.append((item['asset'], path, item['sha256']))
        g.download_files(remote, assets, selections)
        if not trusted: remote.unchanged(tag, frozen['release'], assets, identity['tag_commit'])
        # Recheck all outputs after network work, then use exclusive creation so
        # an intervening writer cannot be replaced by a POSIX rename.
        for name in names:
            destination = candidate / a.relative(name)
            if destination.exists() or destination.is_symlink():
                raise ValueError('candidate payload restore refuses an existing file: ' + name)
            for parent in destination.parents:
                _bundle_directory(parent)
                if parent == candidate.parent: break
        # Publish only after every pinned byte passes; strict callers also recheck remote snapshots.
        import shutil
        for name in names:
            destination = candidate / a.relative(name); destination.parent.mkdir(parents=True, exist_ok=True)
            for parent in destination.parents:
                _bundle_directory(parent)
                if parent == candidate.parent: break
            with (staged / a.relative(name)).open('rb') as incoming, destination.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
    return {'schema_version': 1, 'repository': repository, 'tag': tag, 'inventory_sha256': inventory,
            'release_id': frozen['release']['id'], 'files': {name: identity['files'][name] for name in names}}


def needs_browser_prerequisite(backend, scope):
    return backend == 'hosted-web' and scope == 'archive' or backend == 'wasm' and scope in ('source', 'recovery', 'archive')


def browser_prerequisite(target, environment, backend):
    """Select external browser test prerequisites without changing the SDK."""
    if backend not in ('hosted-web', 'wasm'):
        raise ValueError('browser setup requires a browser backend')
    systems = {'debian-12': ('debian', '12', 'debian:bookworm'),
               'debian-13': ('debian', '13', 'debian:trixie'),
               'ubuntu-24.04': ('ubuntu', '24.04', 'ubuntu:24.04')}
    if target == 'browser-wasm32' and backend == 'wasm' and environment == 'chromium':
        # Use the maintained host installation and its namespace/AppArmor policy.
        # The browser remains an external prerequisite, never an SDK payload.
        return dict(distribution='ubuntu', version='24.04', image='', architecture='amd64',
                    engine='chromium', packages=['google-chrome', 'chromedriver'],
                    executable='/usr/bin/google-chrome', driver='/usr/bin/chromedriver',
                    repository='host-preinstalled')
    if target == 'browser-wasm32' and backend == 'wasm' and environment == 'firefox':
        distro, version, image = systems['debian-12']; architecture = 'amd64'; engine = environment
    elif target in ('linux-x86_64', 'linux-aarch64') and backend == 'hosted-web' and environment in systems:
        distro, version, image = systems[environment]
        architecture = 'amd64' if target == 'linux-x86_64' else 'arm64'; engine = 'firefox'
    else:
        raise ValueError('unsupported browser qualification environment')
    packages = ['firefox'] if distro == 'ubuntu' else ['firefox-esr'] if engine == 'firefox' else ['chromium', 'chromium-driver']
    return dict(distribution=distro, version=version, image=image, architecture=architecture,
                engine=engine, packages=packages, executable='/usr/bin/' + packages[0],
                repository='host-preinstalled' if distro == 'ubuntu' else 'distribution')


def browser_setup_preflight(selection):
    """No package/configuration writes before positive disposable-host checks."""
    if (platform.system() != 'Linux' or not hasattr(os, 'geteuid') or os.geteuid() != 0 or
            os.environ.get('FOUNDATION_DISPOSABLE_CHECK') != '1' or not Path('/.dockerenv').is_file()):
        raise ValueError('browser setup requires an explicitly disposable root Docker runtime')
    actual = platform.freedesktop_os_release()
    if (actual.get('ID'), actual.get('VERSION_ID')) != (selection['distribution'], selection['version']):
        raise ValueError('actual browser runtime distribution differs from selected environment')
    if os.environ.get('CHECK_IMAGE') != selection['image']:
        raise ValueError('browser runtime image differs from selected environment')
    expected = 'linux-x86_64' if selection['architecture'] == 'amd64' else 'linux-aarch64'
    assert_host(expected)
    architecture = subprocess.run(['dpkg', '--print-architecture'], check=True, capture_output=True, text=True).stdout.strip()
    if architecture != selection['architecture']:
        raise ValueError('actual package architecture differs from selected environment')


def inspect_host_firefox(selection):
    """Inspect an existing native host browser; never install or edit package sources."""
    if selection['repository'] != 'host-preinstalled' or platform.system() != 'Linux':
        raise ValueError('native hosted browser requires the selected Linux environment')
    actual = platform.freedesktop_os_release()
    if (actual.get('ID'), actual.get('VERSION_ID')) != (selection['distribution'], selection['version']):
        raise ValueError('host browser distribution differs')
    assert_host('linux-x86_64' if selection['architecture'] == 'amd64' else 'linux-aarch64')
    def version(path):
        result = subprocess.run([str(path), '--version'], check=True, capture_output=True, text=True,
                                timeout=30, env=dict(os.environ, LC_ALL='C', LANG='C'))
        if not re.fullmatch(r'Mozilla Firefox [0-9]+(?:\.[0-9]+){1,3}(?:esr)?', result.stdout.strip()):
            raise ValueError('unrecognized installed Firefox version')
        return result.stdout.strip()
    command = Path(selection['executable']).resolve(strict=True)
    with command.open('rb') as stream: header = stream.read(131072)
    native = command
    if not header.startswith(b'\x7fELF'):
        # Recognized distribution wrappers only. Execute the inspected real binary
        # for qualification so an unrelated same-version installation cannot satisfy it.
        choices = []
        if b'/usr/lib/firefox' in header: choices.append(Path('/usr/lib/firefox/firefox'))
        if b'snap' in header: choices.append(Path('/snap/firefox/current/usr/lib/firefox/firefox'))
        choices = [x.resolve(strict=True) for x in choices if x.is_file()]
        if len(choices) != 1:
            raise ValueError('installed Firefox wrapper has no unambiguous native executable')
        native = choices[0]
        with native.open('rb') as stream: header = stream.read(64)
    machine = 62 if selection['architecture'] == 'amd64' else 183
    if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != machine:
        raise ValueError('installed Firefox executable architecture differs')
    observed = version(native)
    if version(command) != observed:
        raise ValueError('Firefox wrapper and native executable versions differ')
    c = module('coverage')
    files = {str(path): c.sha(path) for path in {command,native}}
    return dict(package='firefox', version=observed, architecture=selection['architecture'],
                policy='preinstalled native host prerequisite; no package configuration changed',
                executable=str(native), files=files)


def inspect_host_chromium(selection):
    """Bind the installed Chromium-family browser and matching local driver."""
    if (selection['repository'] != 'host-preinstalled' or selection['engine'] != 'chromium' or
            platform.system() != 'Linux'):
        raise ValueError('native Chromium requires the selected Linux host')
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise ValueError('native Chromium qualification requires an unprivileged host account')
    actual = platform.freedesktop_os_release()
    if (actual.get('ID'), actual.get('VERSION_ID')) != (selection['distribution'], selection['version']):
        raise ValueError('host browser distribution differs')
    assert_host('linux-x86_64')
    records = []
    versions = []
    for package, selected in zip(selection['packages'], (selection['executable'], selection['driver'])):
        command = Path(selected).resolve(strict=True)
        with command.open('rb') as stream: header = stream.read(131072)
        native = command
        if package == 'google-chrome' and not header.startswith(b'\x7fELF'):
            if b'"$HERE/chrome"' not in header or not (command.parent / 'chrome').is_file():
                raise ValueError('installed Chrome wrapper has no recognized native executable')
            native = (command.parent / 'chrome').resolve(strict=True)
            with native.open('rb') as stream: header = stream.read(64)
        if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 62:
            raise ValueError('installed Chromium prerequisite architecture differs')
        def version(path):
            result = subprocess.run([str(path), '--version'], check=True, capture_output=True,
                                    text=True, timeout=30, env=dict(os.environ, LC_ALL='C', LANG='C'))
            value = result.stdout.strip()
            expression = (r'(?:Google Chrome(?: for Testing)?|Chromium) ([0-9]+(?:\.[0-9]+){3})' if package == 'google-chrome'
                          else r'ChromeDriver ([0-9]+(?:\.[0-9]+){3})(?: \([^\r\n]*\))?')
            match = re.fullmatch(expression, value)
            if not match: raise ValueError('unrecognized installed Chromium prerequisite version')
            return value, match[1]
        observed, number = version(native)
        if command != native and version(command)[0] != observed:
            raise ValueError('Chrome wrapper and native executable versions differ')
        versions.append(number)
        records.append(dict(package=package, version=observed, architecture=selection['architecture'],
            policy='preinstalled native host prerequisite; no package configuration changed',
            executable=str(native), files={str(path): module('coverage').sha(path) for path in {command,native}}))
    if versions[0].split('.')[0] != versions[1].split('.')[0]:
        raise ValueError('installed Chromium browser and driver major versions differ')
    return records


def install_browser_prerequisite(target, environment, backend, output):
    """Mutate only an explicitly disposable supported container, retaining facts."""
    selection = browser_prerequisite(target, environment, backend)
    if selection['repository'] == 'host-preinstalled':
        records = inspect_host_chromium(selection) if selection['engine'] == 'chromium' else [inspect_host_firefox(selection)]
        Path(output).mkdir(parents=True, exist_ok=False)
        return dict(schema_version=1, selection=selection, signing_key_fingerprint=None,
                    installed=records, browser_version=records[0]['version'])
    browser_setup_preflight(selection)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    def capture(argv):
        return subprocess.run(argv, check=True, capture_output=True, text=True,
                              env=dict(os.environ, LC_ALL='C', LANG='C')).stdout.strip()
    subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', *selection['packages']], check=True)
    installed = []
    for package in selection['packages']:
        fields = capture(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n', package]).split('\t')
        if len(fields) != 4 or fields[0] != package or fields[2] != selection['architecture'] or fields[3] != 'installed':
            raise ValueError('installed browser package differs from selected prerequisite')
        installed.append(dict(package=fields[0], version=fields[1], architecture=fields[2],
                              policy=capture(['apt-cache', 'policy', package])))
    return dict(schema_version=1, selection=selection, signing_key_fingerprint=None,
                installed=installed, browser_version=capture([selection['executable'], '--version']))


def needs_windows_graphics(target, backends, backend, scope):
    return target == 'windows-x86_64' and 'rev' in backends and (scope in ('source', 'recovery') or backend == 'rev' and scope == 'archive')


def qualification_row(item, runners=None):
    """Keep execution routing identical for individual checks and CI batches."""
    runners = STANDARD if runners is None else runners
    if set(runners) != set(STANDARD) or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', value) for value in runners.values()):
        raise ValueError('explicit complete runner selection required')
    target, environment, backend, scope = (item[key] for key in ('target', 'environment', 'backend', 'scope'))
    images = {'debian-12': 'debian:bookworm', 'debian-13': 'debian:trixie', 'ubuntu-24.04': 'ubuntu:24.04'}
    image = '' if (environment == 'ubuntu-24.04' and backend == 'hosted-web' and scope == 'archive' or
                   target == 'browser-wasm32' and backend == 'wasm' and environment == 'chromium') else images.get(environment, 'debian:bookworm' if environment in ('firefox', 'chromium') else '')
    return dict(id=item['id'], target=target, runner=runners.get(target, runners['linux-x86_64']),
                image=image, environment=environment, scope=scope, backend=backend,
                graphics='--windows-graphics-archive' in item['argv'])


def qualification_batches(plan, *, runners=None, manifest=None, attempt=None):
    """Keep independent scopes parallel and backend receipts complete.

    Whole-artifact source/recovery/ABI executions remain coalesced across
    backends; archive/client checks share only one same-scope transport batch.
    The 90-minute case and 240-minute hosted job limits are independent safety
    caps, not a promise that every member can exhaust its case allowance. Split
    future longer workloads here; this code is itself bound by the frozen plan.
    """
    c = module('coverage')
    rows = [qualification_row(item, runners) for item in c.executions(plan)]
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[key] for key in ('runner', 'image', 'target', 'environment', 'scope')), []).append(row)
    batches, identities = [], set()
    for members in groups.values():
        # Bound future policy growth without changing logical or execution IDs.
        for start in range(0, len(members), 16):
            selected = members[start:start + 16]
            first = selected[0]
            batch = {key: first[key] for key in ('runner', 'image', 'target', 'environment')}
            batch.update(checks=[row['id'] for row in selected],
                         graphics=any(row['graphics'] for row in selected),
                         browser=any(row['target'] != 'windows-x86_64' and needs_browser_prerequisite(row['backend'], row['scope']) for row in selected))
            # Transport labels have stricter characters and length than frozen
            # check IDs. Leave room for browser-prerequisite- and a 19-digit
            # attempt within ci_transport's 80-character bundle-name bound.
            slug = re.sub(r'[^a-z0-9_-]', '-', first['id'].lower())[:20]
            identity = 'batch-' + slug + '-' + c.digest(batch)[:12]
            if identity in identities:raise ValueError('colliding batch transport identity')
            identities.add(identity); batch['id'] = identity
            if manifest is not None:
                batch['payloads'] = qualification_payload_names(plan, batch, manifest, attempt)
            batches.append(batch)
    return {'include': batches}


def qualification_payload_names(plan, batch, manifest, attempt, *, include_inputs=True):
    """Derive a bounded exact projection from complete frozen qualification data."""
    if not isinstance(attempt, str) or not re.fullmatch(r'[1-9][0-9]*', attempt):
        raise ValueError('positive qualification attempt required')
    checks = {item['id']: item for item in module('coverage').executions(plan)}
    if not batch['checks'] or any(name not in checks for name in batch['checks']):
        raise ValueError('unknown qualification execution')
    items = [checks[name] for name in batch['checks']]
    if len({(item['target'], item['scope']) for item in items}) != 1:
        raise ValueError('one independent qualification scope required')
    item = items[0]
    entries = [entry for entry in manifest['artifacts'] if entry['target'] == item['target']]
    if len(entries) != 1: raise ValueError('selected target is absent or duplicate')
    names = ['qualification-inputs-' + attempt] if include_inputs else []
    names.append('qualification-' + item['target'] + '-' + attempt)
    if item['scope'] in ('source', 'recovery') or item['scope'] == 'archive' and any(row['backend'] in ('wasm', 'hosted-web') for row in items):
        names.append('qualification-source-' + attempt)
    if item['scope'] in ('source', 'recovery'):
        required = set(module('release').dependency_recipes(entries[0]))
        found = set()
        for index, group in enumerate(manifest['dependencies']):
            if group['recipe_id'] in required:
                found.add(group['recipe_id'])
                names.append('qualification-sdk-' + str(index) + '-' + attempt)
                if item['scope'] == 'recovery' or group.get('kind') == 'rust' or item.get('sdk_payload') != 'binary':
                    names.append('qualification-sdk-source-' + str(index) + '-' + attempt)
        if found != required: raise ValueError('qualification SDK closure is incomplete')
    if len(names) > 20 or len(names) != len(set(names)):
        raise ValueError('bounded distinct qualification payloads required')
    return names


def archived_binary_group_support(candidate, manifest):
    """Inspect the exact retained builder; old candidates keep complete SDKs."""
    import ast, tarfile
    source = candidate / manifest['source']['archive']
    with tarfile.open(source, 'r:*') as archive:
        members = [item for item in archive.getmembers() if item.name == 'tools/build.py']
        if not members: return False
        if len(members) != 1 or not members[0].isfile() or members[0].size > 8*1024**2:
            raise ValueError('invalid retained builder capability input')
        tree = ast.parse(archive.extractfile(members[0]).read().decode('utf-8'))
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
               node.func.attr == 'add_argument' and any(isinstance(arg, ast.Constant) and
               arg.value == '--binary-dependency-group' for arg in node.args) for node in ast.walk(tree))


def qualification_plan(candidate, profile, output, policy=None, *, runners=None, metadata_only=False):
    """Add hosted input bindings and runner routing to the local frozen plan."""
    from types import SimpleNamespace
    additional = {name: ROOT / name for name in
        ('.github/scripts/lifecycle.py', '.github/scripts/container_job.py', '.github/workflows/certify.yml')}
    # Select the extra input here; build_plan verifies the complete manifest below.
    if 'packages' in module('coverage').load(Path(candidate) / 'release.json'):
        additional['build/package-plan.json'] = ROOT / 'build/package-plan.json'
    if metadata_only:
        additional.update({'build/' + name: candidate.parent / name
                           for name in ('delivery.json', 'candidate-remote.json')})
    helpers = SimpleNamespace(module=module, needs_browser_prerequisite=needs_browser_prerequisite,
        browser_prerequisite=browser_prerequisite, needs_windows_graphics=needs_windows_graphics,
        archived_binary_group_support=archived_binary_group_support)
    value = module('qualification_plan').build_plan(ROOT, candidate, profile, policy,
        additional_inputs=additional, metadata_only=metadata_only, _helpers=helpers)
    c = module('coverage')
    matrix = [qualification_row(item, runners) for item in c.executions(value)]
    c.write_new(output, value)
    return {'include': matrix}


def _bundle_directory(path):
    import stat
    try: info=path.lstat()
    except FileNotFoundError: return
    if not stat.S_ISDIR(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
        raise ValueError('bundle destination requires ordinary directories without links or reparse points')


def restore_run_bundle(repository, run_id, attempt, source_commit, workflow, name, output, *, allow_failed=False):
    """Verify into new staging before merging only absent files into an owned output."""
    import tempfile
    import shutil
    a=module('dependency_archive'); transport=module('ci_transport')
    output=Path(output).absolute()
    for parent in (output,*output.parents):
        _bundle_directory(parent)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ci-bundle-',dir=output.parent) as temporary:
        staged=Path(temporary)/'payload'
        result=transport.fetch_bundle(repository,run_id,attempt,source_commit,workflow,name,staged,
                                      allow_failed=allow_failed)
        entries=result['manifest']['files']
        for relative in entries:
            destination=output/a.relative(relative)
            if destination.exists() or destination.is_symlink():
                raise ValueError('bundle restore refuses an existing file: '+relative)
            for parent in destination.parents:
                if parent==output.parent: break
                _bundle_directory(parent)
        output.mkdir(exist_ok=True)
        for relative,info in entries.items():
            source=staged/a.relative(relative);destination=output/a.relative(relative)
            destination.parent.mkdir(parents=True,exist_ok=True)
            with source.open('rb') as incoming,destination.open('xb') as outgoing:
                shutil.copyfileobj(incoming,outgoing)
            destination.chmod(info['mode'])
    return result


def restore_run_bundles(repository, run_id, attempt, source_commit, workflow, requests):
    """Fetch one authenticated batch before merging any selected payload files."""
    import tempfile, shutil
    a = module('dependency_archive'); transport = module('ci_transport')
    if not isinstance(requests, list) or not requests:
        raise ValueError('nonempty bundle restore batch required')
    outputs = []
    for request in requests:
        if not isinstance(request, dict) or not {'name', 'output'} <= request.keys():
            raise ValueError('bundle request requires exact name and output')
        output = Path(request['output']).absolute()
        for parent in (output, *output.parents): _bundle_directory(parent)
        outputs.append(output)
    outputs[0].parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ci-batch-', dir=outputs[0].parent) as temporary:
        stages = [Path(temporary) / str(index) / 'payload' for index in range(len(requests))]
        selected = [dict(request, output=stage) for request, stage in zip(requests, stages)]
        results = transport.fetch_bundles(repository, run_id, attempt, source_commit, workflow, selected)
        if len(results) != len(requests): raise ValueError('bundle batch result inventory differs')
        files = []; destinations = set()
        for request, result, output, stage in zip(requests, results, outputs, stages):
            if result['manifest']['name'] != request['name']:
                raise ValueError('bundle batch result name differs')
            for relative, info in result['manifest']['files'].items():
                destination = output / a.relative(relative)
                key = str(destination).casefold()
                if key in destinations or destination.exists() or destination.is_symlink():
                    raise ValueError('bundle restore refuses an existing or colliding file: ' + relative)
                destinations.add(key)
                for parent in destination.parents: _bundle_directory(parent)
                files.append((stage / a.relative(relative), destination, info['mode']))
        if any(str(parent).casefold() in destinations for _, destination, _ in files for parent in destination.parents):
            raise ValueError('bundle restore file collides with another parent directory')
        # Complete collision/type checks precede every final write. Exclusive
        # creation rechecks later changes and never replaces an existing file.
        for source, destination, mode in files:
            for parent in destination.parents: _bundle_directory(parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as incoming, destination.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            destination.chmod(mode)
    return results


def download_run(repository, run_id, source_commit, workflow, name, output):
    g=module('github_release'); remote=g.Remote(repository);remote.visible()
    observed=remote.transport.json(remote.base+'/actions/runs/'+str(run_id))
    if observed.get('status')!='completed' or observed.get('conclusion')!='success':
        raise ValueError('bundle producer run must complete successfully')
    return restore_run_bundle(repository,run_id,observed['run_attempt'],source_commit,workflow,name,output)


def retained_sdk_request(request, repository, target, profile, recipe):
    fields={'schema_version','repository','target','profile','recipe_id','run_id','source_commit',
            'attempt','job_id','workflow','group','proof'}
    if not isinstance(request,dict) or set(request)!=fields or type(request['schema_version']) is not int or request['schema_version']!=2:
        raise ValueError('exact version-2 retained bundle request required; legacy storage requires explicit import')
    if request['workflow'] not in ('sdk-maintenance.yml','sdk-import.yml'):
        raise ValueError('retained SDK requires an allowed explicit producer workflow')
    legacy={key:value for key,value in request.items() if key!='workflow'}
    legacy['schema_version']=1
    for kind in ('group','proof'):
        entry=request[kind]
        if not isinstance(entry,dict) or set(entry)!={'manifest_id','manifest_sha256'}:
            raise ValueError('exact bundle manifest identity required')
        legacy[kind]={'id':entry['manifest_id'],'sha256':entry['manifest_sha256']}
    legacy_sdk_request(legacy,repository,target,profile,recipe)
    return request


def retained_sdk(repository,request,target,profile,recipe,output,*,transport=None):
    """Ordinary reuse accepts only complete run-scoped draft-release bundles."""
    import tempfile
    store=module('dependency_store');g=module('github_release');bundles=module('ci_transport')
    retained_sdk_request(request,repository,target,profile,recipe)
    output=Path(output).absolute()
    if output.exists() or output.is_symlink(): raise ValueError('retained SDK output must be new')
    output.parent.mkdir(parents=True,exist_ok=True)
    observed={}
    with tempfile.TemporaryDirectory(prefix='.retained-bundles-',dir=output.parent) as temporary:
        stage=Path(temporary)
        for kind in ('proof','group'):
            reference=request[kind]
            observed[kind]=bundles.fetch_bundle(repository,request['run_id'],request['attempt'],request['source_commit'],
                request['workflow'],f'sdk-{kind}-{target}-{request["attempt"]}',stage/kind,
                job_id=request['job_id'],manifest_id=reference['manifest_id'],
                manifest_sha256=reference['manifest_sha256'],allow_failed=True,transport=transport)
        proof=stage/'proof'
        for name in ('sdk-retention.json','sdk-origin.json'):
            path=proof/name
            if not path.is_file() or path.is_symlink() or path.stat().st_size>128*1024:
                raise ValueError('retained proof requires bounded retention and origin records')
        receipt=g.parse((proof/'sdk-retention.json').read_bytes());origin=g.parse((proof/'sdk-origin.json').read_bytes())
        expected=dict(schema_version=1,status='verified',qualification='unqualified',publication_approved=False,
            target=target,profile=profile,recipe_id=recipe,source_commit=request['source_commit'],
            run_id=str(request['run_id']),attempt=request['attempt'])
        if (not isinstance(receipt,dict) or set(receipt)!=set(expected)|{'files'} or
            any(type(receipt.get(k)) is not type(v) or receipt[k]!=v for k,v in expected.items()) or
            not isinstance(origin,dict) or origin.get('recipe')!=recipe or
            origin.get('origin') not in ('base','rebuild','absent-base','absent-recipe','retained')):
            raise ValueError('retained bundle receipt or origin differs from exact request')
        files=store.verify_group(stage/'group',recipe)
        if files!=receipt['files']: raise ValueError('retained SDK triplet differs from verified receipt')
        store.copy_group(stage/'group',output,recipe)
    return dict(origin='retained',recipe=recipe,qualification='unqualified',publication_approved=False,
                repository=repository,request=request,bundles=observed,retention=receipt,previous_origin=origin)


def retained_rust_request(request, repository, target, recipe):
    fields = {'schema_version', 'repository', 'target', 'recipe_id', 'run_id',
              'source_commit', 'attempt', 'job_id', 'workflow', 'group'}
    if (not isinstance(request, dict) or set(request) != fields or
            type(request['schema_version']) is not int or request['schema_version'] != 1):
        raise ValueError('exact retained Rust bundle request required')
    module('github_release').location(repository); exact_commit(request['source_commit'])
    if (target not in RUST_RECIPES or request['repository'] != repository or
            request['target'] != target or request['recipe_id'] != recipe or
            not isinstance(recipe, str) or not re.fullmatch(r'[0-9a-f]{64}', recipe) or
            request['workflow'] != 'sdk-maintenance.yml'):
        raise ValueError('retained Rust repository, target, recipe or producer workflow differs')
    for key in ('run_id', 'attempt', 'job_id'):
        if type(request[key]) is not int or request[key] < 1:
            raise ValueError('retained Rust producer identifiers must be positive integers')
    entry = request['group']
    if (not isinstance(entry, dict) or set(entry) != {'manifest_id', 'manifest_sha256'} or
            type(entry['manifest_id']) is not int or entry['manifest_id'] < 1 or
            not isinstance(entry['manifest_sha256'], str) or
            not re.fullmatch(r'[0-9a-f]{64}', entry['manifest_sha256'])):
        raise ValueError('exact retained Rust manifest identity required')
    return request


def retained_rust_sdk(repository, request, target, recipe, output, *, transport=None):
    import shutil
    import tempfile
    retained_rust_request(request, repository, target, recipe)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('retained Rust output must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    rust = module('rust_sdk'); reference = request['group']
    with tempfile.TemporaryDirectory(prefix='.retained-rust-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'group'
        observed = module('ci_transport').fetch_bundle(repository, request['run_id'], request['attempt'],
            request['source_commit'], request['workflow'], f'rust-sdk-group-{target}-{request["attempt"]}', stage,
            job_id=request['job_id'], manifest_id=reference['manifest_id'],
            manifest_sha256=reference['manifest_sha256'], allow_failed=True, transport=transport)
        files = rust.verify_group(stage, recipe)
        shutil.copytree(stage, output)
        if rust.verify_group(output, recipe) != files or rust.verify_group(stage, recipe) != files:
            raise ValueError('retained Rust group changed during copying')
    return dict(origin='retained', recipe=recipe, files=files, qualification='unqualified',
                publication_approved=False, repository=repository, request=request, bundle=observed)


def fetch_rust_base(repository, recipe, output, *, transport=None):
    return dict(module('github_release').fetch_rust_base(repository, recipe, output, transport=transport),
                origin='base')


def publish_rust_base(repository, recipe, group, source_commit, *, execute=False, transport=None):
    return module('github_release').publish_rust_base(repository, recipe, group, source_commit,
                                                     execute=execute, transport=transport)


def legacy_sdk_request(request, repository, target, profile, recipe):
    """One explicit producer and two immutable transport objects; no selection fallback."""
    g = module('github_release')
    fields = {'schema_version', 'repository', 'target', 'profile', 'recipe_id',
              'run_id', 'source_commit', 'attempt', 'job_id', 'group', 'proof'}
    if not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('exact retained SDK request schema required')
    g.location(repository); exact_commit(request['source_commit'])
    if (target not in (*STANDARD, 'browser-wasm32') or profile not in ('core', 'all-gui') or
        request['repository'] != repository or request['target'] != target or
        request['profile'] != profile or request['recipe_id'] != recipe or
        not isinstance(recipe, str) or not re.fullmatch(r'[0-9a-f]{64}', recipe)):
        raise ValueError('retained SDK repository, target, profile or current recipe differs')
    for field in ('run_id', 'attempt', 'job_id'):
        if type(request[field]) is not int or request[field] < 1:
            raise ValueError('retained producer identifiers must be positive integers')
    for field in ('group', 'proof'):
        item = request[field]
        if (not isinstance(item, dict) or set(item) != {'id', 'sha256'} or
            type(item['id']) is not int or item['id'] < 1 or
            not isinstance(item['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
            raise ValueError('exact retained artifact ID and SHA256 required')
    if request['group']['id'] == request['proof']['id']:
        raise ValueError('group and proof must be distinct artifacts')
    return request


def _retained_zip(path, *, max_bytes):
    """Validate every member; callers read selected proof files without extraction."""
    import stat
    import zipfile
    a = module('dependency_archive')
    entries, folded, kinds, spelling, total = {}, set(), {}, {}, 0
    with zipfile.ZipFile(path) as source:
        members = source.infolist()
        if len(members) > 10000:
            raise ValueError('retained ZIP inventory exceeds supported limit')
        for item in members:
            # ZipInfo truncates NUL bytes and normalizes host separators. Validate
            # the stored spelling before consulting its cleaned lookup name.
            original = item.orig_filename
            name = str(a.relative(original[:-1] if original.endswith('/') else original))
            if original != item.filename:
                raise ValueError('retained ZIP member name changes during decoding')
            key = name.casefold(); mode = item.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (key in folded or kind not in (0, stat.S_IFDIR if item.is_dir() else stat.S_IFREG) or
                mode & 0o7000 or item.flag_bits & 1 or item.file_size < 0):
                raise ValueError('unsafe, linked or duplicate retained ZIP member')
            total += item.file_size
            if total > max_bytes:
                raise ValueError('retained ZIP expands beyond supported limit')
            folded.add(key); kinds[key] = item.is_dir()
            parts = name.split('/')
            for index in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:index]); prior = spelling.setdefault(prefix.casefold(), prefix)
                if prior != prefix:
                    raise ValueError('ambiguous retained ZIP path spelling')
            if not item.is_dir(): entries[name] = item
        for name in entries:
            for parent in a.relative(name).parents:
                if str(parent) != '.' and kinds.get(str(parent).casefold()) is False:
                    raise ValueError('retained ZIP file is also an entry parent')
    return entries


def _download_legacy_artifact(repository, artifact_id, path):
    with Path(path).open('xb') as stream:
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com',
            f'repos/{repository}/actions/artifacts/{artifact_id}/zip'], stdout=stream,
            stderr=subprocess.PIPE, check=False, timeout=1800)
    if result.returncode:
        raise ValueError('retained artifact download failed; no fallback is permitted')


def import_legacy_sdk(repository, request, target, profile, recipe, output, *, proof_output=None, transport=None, download=None):
    """Reuse checked bytes from one finished producer, regardless of sibling status."""
    import datetime
    import shutil
    import tempfile
    import zipfile
    g = module('github_release'); a = module('dependency_archive'); store = module('dependency_store')
    legacy_sdk_request(request, repository, target, profile, recipe)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise ValueError('retained SDK output must be new')
    remote = g.Remote(repository, transport); remote.visible()
    base = remote.base; run_id = request['run_id']; attempt = request['attempt']; commit = request['source_commit']
    repository_info = remote.transport.json(base)
    repository_id = repository_info.get('id')
    if type(repository_id) is not int or repository_id < 1:
        raise ValueError('repository numeric identity is unavailable')
    run_endpoint = f'{base}/actions/runs/{run_id}/attempts/{attempt}'
    job_endpoint = f'{base}/actions/jobs/{request["job_id"]}'
    standard = STANDARD.get(target, 'ubuntu-24.04')
    prefix = 'arm' if target == 'linux-aarch64' else 'windows' if target.startswith('windows-') else 'linux'

    def producer():
        observed = remote.transport.json(run_endpoint)
        job = remote.transport.json(job_endpoint)
        name = job.get('name', '')
        match = re.fullmatch(r'produce \(' + re.escape(target) + r', ([A-Za-z0-9.-]+)\)', name) if isinstance(name, str) else None
        runner = match[1] if match else ''
        if runner != standard and not re.fullmatch('foundation-' + prefix + '-[a-z0-9-]+', runner):
            raise ValueError('retained producer runner is outside the explicit target allowlist')
        if (observed.get('id') != run_id or observed.get('run_attempt') != attempt or
            observed.get('head_sha') != commit or observed.get('event') != 'workflow_dispatch' or
            observed.get('path') != '.github/workflows/sdk-maintenance.yml' or
            observed.get('repository', {}).get('id') != repository_id or
            observed.get('repository', {}).get('full_name', '').casefold() != repository.casefold() or
            observed.get('head_repository', {}).get('id') != repository_id or
            observed.get('head_repository', {}).get('full_name', '').casefold() != repository.casefold() or
            job.get('id') != request['job_id'] or job.get('run_id') != run_id or
            job.get('run_attempt') != attempt or job.get('head_sha') != commit or
            job.get('name') != f'produce ({target}, {runner})' or job.get('status') != 'completed' or
            job.get('conclusion') not in ('success', 'failure')):
            raise ValueError('retained producer job, attempt or workflow identity differs')
        try:
            started = datetime.datetime.fromisoformat(job['started_at'].replace('Z', '+00:00'))
            completed = datetime.datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00'))
            if started.utcoffset() is None or completed.utcoffset() is None or completed < started:
                raise ValueError('invalid producer time interval')
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError('completed producer time interval is unavailable') from error
        return job, started, completed

    job, started, completed = producer()
    observed_artifacts = {}
    for kind in ('group', 'proof'):
        item = request[kind]
        row = remote.transport.json(f'{base}/actions/artifacts/{item["id"]}')
        run = row.get('workflow_run', {})
        expected_name = f'sdk-{kind}-{target}-{attempt}'
        if (row.get('id') != item['id'] or row.get('name') != expected_name or row.get('expired') is not False or
            row.get('digest') != 'sha256:' + item['sha256'] or type(row.get('size_in_bytes')) is not int or
            not 0 < row['size_in_bytes'] <= (16 * 1024**3 if kind == 'group' else 64 * 1024**2) or
            run.get('id') != run_id or run.get('head_sha') != commit or
            run.get('repository_id') != repository_id or run.get('head_repository_id') != repository_id):
            raise ValueError('retained artifact immutable identity or producer differs')
        created = datetime.datetime.fromisoformat(row.get('created_at', '').replace('Z', '+00:00'))
        if created.utcoffset() is None or not started <= created <= completed:
            raise ValueError('retained artifact was not created within the exact producer job')
        observed_artifacts[kind] = row
    if proof_output is not None:
        proof_output=Path(proof_output).absolute()
        if proof_output.exists() or proof_output.is_symlink(): raise ValueError('legacy proof output must be new')
        for parent in proof_output.parents:
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise ValueError('legacy proof output requires ordinary parents')
        if proof_output==output or proof_output in output.parents or output in proof_output.parents:
            raise ValueError('legacy import output trees must be disjoint')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.retained-sdk-') as temporary:
        stage = Path(temporary)
        for kind, row in observed_artifacts.items():
            path = stage / (kind + '.zip')
            (download or _download_legacy_artifact)(repository, row['id'], path)
            if path.stat().st_size != row['size_in_bytes'] or a.digest(path) != request[kind]['sha256']:
                raise ValueError('downloaded retained ZIP differs from pinned bytes')
        proof_entries = _retained_zip(stage / 'proof.zip', max_bytes=64 * 1024**2)
        if any(name not in proof_entries or proof_entries[name].file_size > 128 * 1024
               for name in ('sdk-retention.json', 'sdk-origin.json')):
            raise ValueError('retained proof requires bounded retention and origin records')
        with zipfile.ZipFile(stage / 'proof.zip') as source:
            receipt = g.parse(source.read('sdk-retention.json'))
            origin = g.parse(source.read('sdk-origin.json'))
        expected = dict(schema_version=1, status='verified', qualification='unqualified',
            publication_approved=False, target=target, profile=profile, recipe_id=recipe,
            source_commit=commit, run_id=str(run_id), attempt=attempt)
        if (not isinstance(receipt, dict) or set(receipt) != set(expected) | {'files'} or
            any(type(receipt.get(k)) is not type(v) or receipt[k] != v for k, v in expected.items()) or
            not isinstance(origin, dict) or origin.get('recipe') != recipe or
            origin.get('origin') not in ('base', 'rebuild', 'absent-base', 'absent-recipe', 'retained')):
            raise ValueError('retained SDK receipt or origin does not bind the exact request')
        entries = _retained_zip(stage / 'group.zip', max_bytes=16 * 1024**3)
        with zipfile.ZipFile(stage / 'group.zip') as source:
            if set(entries) != set(store.names(recipe)) or len(source.infolist()) != 3:
                raise ValueError('retained group must contain exactly the SDK triplet')
            group = stage / 'group'; group.mkdir()
            for name in entries:
                with source.open(name) as stream, (group / name).open('xb') as destination:
                    shutil.copyfileobj(stream, destination)
        files = store.verify_group(group, recipe)
        if files != receipt['files']:
            raise ValueError('retained SDK triplet differs from the verified receipt')
        if producer()[0] != job or any(remote.transport.json(f'{base}/actions/artifacts/{row["id"]}') != row
                                      for row in observed_artifacts.values()):
            raise ValueError('retained producer or artifacts changed during verification')
        store.copy_group(group, output, recipe)
        if proof_output is not None:
            proof_output=Path(proof_output)
            if proof_output.exists() or proof_output.is_symlink(): raise ValueError('legacy proof output must be new')
            proof_output.mkdir(parents=True)
            with zipfile.ZipFile(stage/'proof.zip') as source:
                for name in proof_entries:
                    path=proof_output/a.relative(name);path.parent.mkdir(parents=True,exist_ok=True)
                    with source.open(name) as incoming,path.open('xb') as outgoing: shutil.copyfileobj(incoming,outgoing)
    return dict(origin='retained', recipe=recipe, qualification='unqualified', publication_approved=False,
                repository=repository, request=request, producer=job, artifacts=observed_artifacts,
                retention=receipt, previous_origin=origin)


def maintenance_base(repository, recipe, output, source='auto', transport=None):
    """Cold production is allowed only after positively observing complete absence."""
    g = module('github_release'); store = module('dependency_store')
    expected = set(store.names(recipe)); g.location(repository)
    if source not in ('auto', 'base', 'rebuild'):
        raise ValueError('maintenance source must be auto, base or rebuild')
    if source == 'rebuild': return {'origin': 'rebuild', 'recipe': recipe}
    if source == 'base':
        return dict(g.fetch_base(repository, recipe, output, transport=transport), origin='base')
    remote = g.Remote(repository, transport); remote.visible()
    info = remote.find('base', False)
    if info is None:
        if remote.reference('base', True) is not None:
            raise ValueError('orphan base tag requires reconciliation')
        return {'origin': 'absent-base', 'recipe': recipe}
    if info['draft'] or not info['prerelease'] or info['name'] != 'base':
        raise ValueError('base lifecycle requires reconciliation')
    assets = remote.assets(info); reference = remote.reference('base')
    present = expected & assets.keys()
    if present and present != expected:
        raise ValueError('partial dependency group requires reconciliation')
    if not present:
        remote.unchanged('base', info, assets, reference)
        return {'origin': 'absent-recipe', 'recipe': recipe}
    return dict(g.fetch_base(repository, recipe, output, transport=transport), origin='base')


def graphics_test(command, output, staged):
    """Use the shared bounded owner before leaving temporary runtime staging."""
    return module('windows_graphics').run_owned(command, output, output / 'graphics-test.log',
             environment=staged.environment, timeout=3600, max_bytes=16 * 1024 * 1024)


def windows_gui_qualification(command, archive, build, output, jobs, *, protected_roots, cwd):
    """One build, actual host probe and complete GUI tests; cleanup precedes packaging."""
    if command[2:4] != ['test', 'release'] or '--full' not in command or '--host-tests' not in command:
        raise ValueError('Windows GUI qualification requires the complete release host test command')
    prepare = command.copy(); prepare[2] = 'build'; prepare.remove('--full')
    index = prepare.index('--junit'); del prepare[index:index + 2]
    compiler = module('windows_compiler')
    compiler.run(prepare, cwd=cwd)
    compiler.run(['cmake', '--build', str(build), '--target', 'foundation-gui-tests',
                  '--parallel', str(jobs)], cwd=cwd)
    probe = output / 'graphics-probe'; probe.mkdir()
    graphics = None; setup_receipt = None
    try:
        with module('windows_graphics').qualified_stage(archive, [build / 'gui'],
                probe_directory=probe, compile_log=output / 'graphics-compile.log',
                protected_roots=protected_roots) as graphics:
            module('coverage').write_new(output / 'graphics-probe.json', graphics.probe_receipt)
            graphics_test(command, output, graphics)
    except BaseException as error:
        setup_receipt = getattr(error, 'graphics_receipt', None)
        raise
    finally:
        module('coverage').write_new(output / 'graphics.json', graphics.receipt if graphics else setup_receipt or
            {'status': 'incomplete', 'detail': 'graphics setup did not reach the supervised test context'})
    if graphics.receipt.get('cleanup') != 'removed':
        error = ValueError('Windows GUI host input cleanup did not complete; packaging is prohibited')
        error.graphics_receipt = graphics.receipt
        raise error
    visual = build / 'gui/visual-evidence'
    captures = list(visual.rglob('*')) if visual.is_dir() else []
    files = [p for p in captures if p.is_file()]
    if (any(p.is_symlink() for p in captures) or not any(p.name == 'qualification.json' for p in files) or
            not any(p.suffix == '.png' for p in files) or not any(p.suffix == '.ppm' for p in files) or
            any(p.suffix not in ('.json', '.png', '.ppm', '.log') for p in files)):
        raise ValueError('complete real native GUI capture evidence is required')
    return {p.relative_to(output).as_posix(): module('coverage').sha(p)
            for p in [output / 'graphics.json', output / 'graphics-probe.json', *files]}


def prepared_check(target, recipe, group, output, jobs=2, gui_group=None, graphics_archive=None, *, defer_qualification=False, development=False,
                   core_provider='rust', rust_group=None, rust_recipe=None):
    """Consume a relocated SDK; GUI qualification retains no distributable output."""
    from dependency_store import verify_group
    if target not in (*STANDARD, 'browser-wasm32') or jobs < 1:
        raise ValueError('supported target and positive concurrency required')
    rust_files = rust_selection(core_provider, rust_group, rust_recipe)
    if type(development) is not bool or development and (not target.startswith('linux-') or gui_group is None):
        raise ValueError('development qualification requires a native Linux all-GUI SDK')
    graphics_needed = target == 'windows-x86_64' and gui_group is not None
    if graphics_needed != (graphics_archive is not None):
        raise ValueError('Windows GUI qualification requires one explicit retained host graphics archive; other probes must omit it')
    if graphics_needed: module('windows_graphics').verify_archive(Path(graphics_archive))
    if target != 'browser-wasm32': assert_host(target)
    elif platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('browser SDK requires its declared Linux x64 host')
    output = Path(output).absolute(); group = Path(group).resolve(strict=True)
    if output.exists(): raise ValueError('prepared check output must be new')
    before = verify_group(group, recipe); output.mkdir(parents=True)
    command = [sys.executable, str(ROOT / 'tools/build.py'), 'test',
               'dev' if development else 'release', *([] if development else ['--portable']),
               '--build-jobs', str(jobs), '--test-jobs', '2', '--build-dir', str(output / 'build'), '--junit', str(output / 'source.junit.xml')]
    if target == 'windows-x86_64':
        version = module('windows_toolchain').inspect_selected_linker()['version']
        metadata = module('sdk_windows').install(group, recipe, output / 'dependencies', version)
        command += ['--dependency-group', str(group), '--windows-dependencies', str(output / 'dependencies')]
    else:
        metadata = module('sdk').install(group, recipe, output / 'sdk', production=True)
        command += ['--sdk', str(output / 'sdk')]
    rust_flags, provider = install_rust_input(core_provider, rust_group, rust_recipe, output / 'rust-sdk',
                                            output / 'dependencies' if target == 'windows-x86_64' else output / 'sdk')
    command += rust_flags
    if gui_group is not None:
        backends = ['wasm'] if target == 'browser-wasm32' else ['terminal', 'framebuffer', 'fltk', 'rev', 'sdl', 'hosted-web']
        if not set(backends) <= set(metadata.get('capabilities', ['wasm'] if target == 'browser-wasm32' else [])):
            raise ValueError('prepared SDK lacks required GUI capabilities')
        command += ['--gui-input-group', str(Path(gui_group).resolve(strict=True)), '--gui-backends', ','.join(backends), '--full']
        if target != 'browser-wasm32': command += ['--host-tests']
    if gui_group is None:
        command += ['--label', 'core']
        if core_provider == 'rust':
            command.remove('--label'); command.remove('core'); command.append('--full')
        if target == 'browser-wasm32': command += ['--gui-backends', 'wasm']
    if development:
        # Exercise both documented commands in one graph. This opt-in qualification
        # is separate from ordinary development and does not create a release.
        prepare = command.copy(); prepare[2] = 'build'; prepare.remove('--full')
        index = prepare.index('--junit'); del prepare[index:index + 2]
        subprocess.run(prepare, cwd=ROOT, check=True)
    graphics_evidence = None
    if graphics_needed:
        graphics_evidence = windows_gui_qualification(command, Path(graphics_archive), output / 'build', output, jobs,
            protected_roots=(group, Path(gui_group).resolve(), output / 'dependencies', output / 'build/inputs'), cwd=ROOT)
    else:
        subprocess.run(command, cwd=ROOT, check=True)
    if gui_group is None:
        packaging = command.copy(); packaging[2] = 'package'
        for option in ('--junit', '--label'):
            if option in packaging:
                index = packaging.index(option); del packaging[index:index + 2]
        if '--full' in packaging: packaging.remove('--full')
        subprocess.run(packaging, cwd=ROOT, check=True)
        choices = list((output / 'build/packages').glob('*.zip' if target.startswith('windows-') else '*.tar.gz'))
        if len(choices) != 1: raise ValueError('prepared check needs one complete archive')
        a = module('artifact'); descriptor = choices[0].with_name(choices[0].name + '.json')
        module('coverage').write_new(descriptor, a.describe(choices[0]))
        a.verify(choices[0], descriptor, sdk=output / 'sdk' if target != 'windows-x86_64' else None,
                 abi=target.startswith('linux-'), processor=target.split('-', 1)[1])
    if verify_group(group, recipe) != before: raise ValueError('SDK group changed during qualification')
    if rust_recipe and module('rust_sdk').verify_group(Path(rust_group), rust_recipe) != rust_files:
        raise ValueError('Rust SDK group changed during qualification')
    receipt = {'status': 'passed', 'target': target, 'recipe': recipe, 'group_files': before,
               'checks': ['relocated-sdk', 'compile', 'execute', 'installed-consumer'] if gui_group is None
                         else ['relocated-sdk', 'all-native-gui' if target != 'browser-wasm32' else 'wasm-gui', 'full-source-tests'],
               'redistribution': False, 'source_junit': 'source.junit.xml'}
    receipt.update(provider)
    if rust_files is not None: receipt['rust_group_files'] = rust_files
    if development:
        receipt['checks'] += ['ordinary-dev-build', 'ordinary-dev-test', 'without-portable-mode']
        receipt['configuration'] = 'dev'
    if graphics_evidence is not None: receipt['graphics_evidence'] = graphics_evidence
    if not defer_qualification: module('coverage').write_new(output / 'qualification.json', receipt)
    return receipt


def gui_group_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ci_gui_group', ROOT / 'gui/source_group.py')
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def gui_group_names(identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('exact GUI group identity required')
    return {name: 'gui-' + identity + '-' + suffix for name, suffix in
            [('gui-inputs.tar.gz', 'inputs.tar.gz'), ('manifest.json', 'manifest.json'), ('SHA256SUMS', 'SHA256SUMS')]}


def fetch_gui_group(repository, identity, output, transport=None):
    import tempfile
    g = module('github_release'); c = module('coverage'); verifier = gui_group_module()
    names = gui_group_names(identity); remote = g.Remote(repository, transport); remote.visible()
    info = remote.find('base'); assets = remote.assets(info); reference = remote.reference('base')
    if info['draft'] or not info['prerelease'] or info['name'] != 'base':
        raise ValueError('GUI inputs require the published prerelease base')
    if not set(names.values()) <= assets.keys():
        raise ValueError('exact complete GUI input group is absent; run explicit maintenance')
    output = Path(output)
    if output.exists() or output.is_symlink(): raise ValueError('GUI input destination must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / 'group'; stage.mkdir()
        for local, remote_name in names.items(): remote.download(assets[remote_name], stage / local)
        if c.sha(stage / 'manifest.json') != identity: raise ValueError('GUI group identity differs')
        verifier.verify(stage)
        remote.unchanged('base', info, assets, reference)
        stage.rename(output)
    return {'group_sha256': identity, 'fetched': True}


def _retire_gui_groups(remote, info, assets, reference, identity, manifest, verifier):
    import tempfile
    import tarfile
    g = module('github_release'); a = module('dependency_archive')
    fields = ('kind', 'upstream', 'license')
    if any(not isinstance(manifest.get(key), str) or not manifest[key] for key in fields): return {}
    slot = {key: manifest[key] for key in fields}
    identities = sorted({match[1] for name in assets if
        (match := re.fullmatch(r'gui-([0-9a-f]{64})-(?:inputs\.tar\.gz|manifest\.json|SHA256SUMS)', name)) and match[1] != identity})
    if len(identities) > g.BASE_CLEANUP_GROUP_LIMIT: raise ValueError('GUI base cleanup exceeds bounded group inventory')
    removed = {}
    for old in identities:
        names = gui_group_names(old)
        if not set(names.values()) <= assets.keys(): continue
        with tempfile.TemporaryDirectory(prefix='gui-base-retire-') as temporary:
            root = Path(temporary); group = root / 'group'; group.mkdir()
            remote.download(assets[names['manifest.json']], group / 'manifest.json')
            try:
                data = a.read_json(group / 'manifest.json')
                if a.digest(group / 'manifest.json') != old or not isinstance(data, dict): continue
                if {key: data.get(key) for key in fields} != slot: continue
            except ValueError:
                continue
            g.download_files(remote, assets, [(names[name], group / name, None) for name in ('gui-inputs.tar.gz', 'SHA256SUMS')])
            try:
                # Previous groups bind their own retained lock and patches.
                frozen = a.extract(group / 'gui-inputs.tar.gz', root / 'frozen', max_bytes=getattr(verifier, 'MAX_TOTAL', 2 * 1024**3))
                verifier.verify(group, redistribution=True, foundation_root=frozen / 'foundation')
            except (ValueError, OSError, tarfile.TarError):
                continue
        removed.update((names[name], assets[names[name]]) for name in ('SHA256SUMS', 'manifest.json', 'gui-inputs.tar.gz'))
    return g.retire_base_assets(remote, info, assets, reference, removed)


def publish_gui_group(repository, group, source_commit, execute=False, transport=None):
    import shutil
    import tempfile
    g = module('github_release'); c = module('coverage'); verifier = gui_group_module()
    group = Path(group); manifest = verifier.verify(group, redistribution=execute)
    exact_commit(source_commit)
    identity = c.sha(group / 'manifest.json'); names = gui_group_names(identity)
    files = {remote_name: c.sha(group / local) for local, remote_name in names.items()}
    result = g.plan('publish-gui-inputs', repository, group_sha256=identity, files=files,
                    source_commit=source_commit, redistributable=manifest['redistributable'],
                    lifecycle='immutable complete GUI input group; base prerelease; never Latest; retire superseded matching GUI inputs')
    if not execute: return result
    remote = g.Remote(repository, transport)
    def act():
        remote.visible(); info = remote.find('base', False)
        before = remote.assets(info) if info else {}; reference = remote.reference('base') if info else source_commit
        present = set(files) & before.keys()
        if info and (info['draft'] or not info['prerelease'] or info['name'] != 'base'):
            raise ValueError('existing base lifecycle differs')
        if present and present != set(files): raise ValueError('partial GUI group requires reconciliation')
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            def confirm(assets):
                dest = work / 'confirm'; dest.mkdir()
                for local, remote_name in names.items(): remote.download(assets[remote_name], dest / local, files[remote_name])
                if verifier.verify(dest, redistribution=True) != manifest: raise ValueError('remote GUI group differs')
            if present:
                confirm(before); remote.unchanged('base', info, before, reference); remote.not_latest(info)
                return dict(result, execute=True, reused=True)
            if not info:
                if remote.reference('base', True) is not None: raise ValueError('orphan base tag requires reconciliation')
                remote.change('/git/refs', body={'ref': 'refs/tags/base', 'sha': source_commit})
                info = remote.info(remote.change('/releases', body={'tag_name': 'base', 'target_commitish': source_commit,
                          'name': 'base', 'body': 'Complete retained dependency inputs.', 'draft': True,
                          'prerelease': True, 'make_latest': 'false'}), 'base')
                if not info['draft'] or not info['prerelease'] or info['name'] != 'base': raise ValueError('base draft differs')
            for local, remote_name in names.items():
                path = work / remote_name; shutil.copyfile(group / local, path)
                if c.sha(path) != files[remote_name]: raise ValueError('GUI inputs changed before publication')
                remote.upload('base', path)
            current = remote.find('base'); assets = remote.assets(current)
            if any(current[k] != info[k] for k in ('id', 'name', 'draft', 'prerelease')):
                raise ValueError('base identity changed')
            if set(assets) != set(before) | set(files) or any(assets[n] != v for n, v in before.items()):
                raise ValueError('base assets changed unexpectedly')
            confirm(assets)
            if verifier.verify(group, redistribution=True) != manifest or any(c.sha(group / n) != files[v] for n, v in names.items()):
                raise ValueError('local GUI group changed during publication')
            remote.unchanged('base', current, assets, reference)
            if current['draft']:
                remote.change('/releases/' + str(current['id']), method='PATCH', body={'draft': False, 'prerelease': True, 'make_latest': 'false'})
            final = remote.find('base')
            if final['id'] != info['id'] or final['draft'] or not final['prerelease'] or final['name'] != 'base' or remote.assets(final) != assets:
                raise ValueError('base finalization unconfirmed')
            remote.not_latest(final)
            if remote.reference('base') != reference: raise ValueError('base reference changed')
            removed = _retire_gui_groups(remote, final, assets, reference, identity, manifest, verifier)
            return dict(result, execute=True, reused=False, release_id=final['id'], removed_assets=removed)
    return g.run_mutation(remote, act)


def lifecycle_main(argv):
    p = argparse.ArgumentParser(description='Frozen SDK and release lifecycle operations')
    p.add_argument('operation', choices=('release-matrix', 'source', 'prepared-package', 'assemble', 'fetch-candidate',
                                       'qualification-plan', 'download-run', 'delivery-request', 'certify'))
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--github-output', type=Path)
    a = p.parse_args(argv)
    c = module('coverage'); data = c.load(a.input)
    op = a.operation
    if op == 'release-matrix': result = release_matrix(**data)
    elif op == 'source': result = source_archive(Path(data['output']), Path(data['gui_source']) if data.get('gui_source') else None)
    elif op == 'prepared-package':
        result = prepared_package(data['target'], data['recipe'], Path(data['group']).resolve(), Path(data['source']).resolve(),
            Path(data['output']).resolve(), data.get('jobs', 2), core_provider=data.get('core_provider', 'rust'),
            rust_group=Path(data['rust_group']).resolve() if data.get('rust_group') else None,
            rust_recipe=data.get('rust_recipe'))
    elif op == 'assemble': result = assemble_release(*(Path(data[k]) for k in ('source', 'packages', 'base', 'output')), data['profile'])
    elif op == 'fetch-candidate': result = fetch_candidate(data['repository'], data['tag'], data['inventory'], Path(data['output']))
    elif op == 'qualification-plan': result = qualification_plan(Path(data['candidate']).resolve(), data['profile'], Path(data['plan']))
    elif op == 'download-run': result = download_run(data['repository'], data['run_id'], data['source_commit'], data['workflow'], data['name'], Path(data['output']))
    elif op == 'certify':
        manifest = module('release').verify_release(Path(data['directory']))
        plan = c.load(Path(data['check_plan'])); reports = [Path(data['reports']) / x['id'] / 'result.json' for x in plan['checks']]
        result = module('certify_release').certify(Path(data['directory']), manifest, plan, reports,
                  c.load(Path(data['policy'])), data['profile'], data.get('experiment', False))
    else:
        operation = data.pop('operation')
        if operation not in ('publish-candidate', 'attach-certificate', 'promote', 'publish-base'):
            raise ValueError('unknown delivery operation')
        if 'delivery_file' in data: data['delivery'] = c.load(Path(data.pop('delivery_file')))
        if operation == 'attach-certificate':
            frozen = c.load(Path(data['check_plan']))
            data['reports'] = [str(Path(data['reports']) / x['id'] / 'result.json') for x in frozen['checks']]
        result = data
    if a.output: c.write_new(a.output, result)
    if a.github_output:
        with a.github_output.open('a', encoding='utf-8') as out:
            out.write('matrix=' + json.dumps(result, separators=(',', ':')) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "lifecycle":
            lifecycle_main(sys.argv[2:])
        else:
            main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("CI: " + str(error), file=sys.stderr)
        sys.exit(1)
