#!/usr/bin/env python3
"""Explicit pinned source SDK producer, with retained-input offline replay."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from dependency_archive import sdk_temporary_directory, digest, encoded, file_inventory, read_json, relative, verify_inventory, write_json
from sdk import export_group, materialize, seal

TOOLS = ('distro_sdk.py', 'sdk.py', 'sdk_environment.py', 'sdk_manifest.py', 'dependency_archive.py', 'dependency_store.py', 'verify_abi.py')


def recipe_id(recipe):
    recipe = Path(recipe)
    inputs = {'recipe.json': digest(recipe)}
    for name in ('config', 'Config.in', 'external.desc', 'external.mk'):
        inputs[name] = digest(recipe.parent / name)
    for name in TOOLS:
        inputs['tools/' + name] = digest(Path(__file__).parent / name)
    return hashlib.sha256(encoded(inputs)).hexdigest()


def fetch_file(item, path, network):
    path = Path(path)
    if path.is_file():
        if digest(path) != item['sha256']: raise ValueError('changed pinned input: ' + path.name)
        return
    if not network: raise ValueError('missing pinned input; explicit fetch required: ' + path.name)
    if not item['url'].startswith('https://'): raise ValueError('source URL must use HTTPS')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream: temporary = Path(stream.name)
    try:
        with urllib.request.urlopen(item['url'], timeout=60) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        if digest(temporary) != item['sha256']: raise ValueError('pinned source checksum mismatch')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def unpack_source(archive, output):
    """Upstream source links remain inert; no extraction can traverse any link."""
    if output.exists(): raise ValueError('source extraction destination must be new')
    with tarfile.open(archive) as source:
        members = source.getmembers()
        names, links = {}, set()
        for member in members:
            name = str(relative(member.name.rstrip('/')))
            if name in names:
                if member.isdir() and names[name]: continue
                raise ValueError('duplicate upstream source entry')
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError('unsupported upstream source entry')
            names[name] = member.isdir()
            if member.issym(): links.add(name)
            if member.mode & 0o7000: raise ValueError('privileged upstream source mode')
        for name in names:
            if any(str(parent) in links for parent in PurePosixPath(name).parents):
                raise ValueError('upstream source entry traverses a link')
        output.mkdir(parents=True)
        for member in members:
            path = output / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir(): path.mkdir(exist_ok=True)
            elif member.issym():
                # Buildroot contains target skeleton links to OS locations. They
                # are stored as inert entries; build commands never use skeletons
                # as their host source/build/output roots.
                path.symlink_to(member.linkname)
            else:
                with source.extractfile(member) as stream, path.open('xb') as target: shutil.copyfileobj(stream, target)
                path.chmod(member.mode & 0o777)


def overlay(source, manifest):
    if manifest['architecture'] == 'aarch64':
        architecture = source / 'arch/Config.in.arm'
        before = architecture.read_text()
        after, count = re.subn(r'default \"cortex-a53\"(\s+if BR2_cortex_a53)', r'default "generic"\1', before)
        if count != 1: raise ValueError('upstream generic ARM CPU context changed')
        architecture.write_text(after)
    item = manifest['glibc_source']
    path = source / 'package/glibc/glibc.mk'
    text = path.read_text()
    for name, value in {'VERSION': item['version'], 'SITE': item['site'], 'SITE_METHOD': 'wget'}.items():
        text, count = re.subn(r'^GLIBC_' + name + r' = .*$', 'GLIBC_' + name + ' = ' + value, text, flags=re.M)
        if count != 1: raise ValueError('upstream SDK overlay context changed')
    text = re.sub(r'^GLIBC_SOURCE = .*\n', '', text, flags=re.M)
    text, count = re.subn(r'^GLIBC_LICENSE = .*?\nGLIBC_LICENSE_FILES = .*?\n',
        'GLIBC_LICENSE = LGPL-2.1+, GPL-2.0+, BSD-3-Clause\nGLIBC_LICENSE_FILES = COPYING COPYING.LIB LICENSES\n', text, flags=re.M | re.S)
    if count != 1: raise ValueError('upstream license context changed')
    text = re.sub(r'^GLIBC_IGNORE_CVES.*\n', '', text, flags=re.M)
    marker = '$(eval $('
    if marker not in text: raise ValueError('upstream package evaluation context changed')
    text = text.replace(marker, 'GLIBC_SOURCE = ' + item['file'] + '\nGLIBC_EXTRA_CFLAGS += -std=gnu11\n' + marker, 1)
    path.write_text(text)
    (path.parent / 'glibc.hash').write_text('sha256  ' + item['sha256'] + '  ' + item['file'] + '\n' +
        ''.join('sha256  ' + value + '  ' + name + '\n' for name, value in item['licenses'].items()))


def host_check(recipe):
    target = read_json(recipe)['architecture']
    if target not in ('x86_64', 'aarch64'):
        raise ValueError('unsupported native SDK architecture')
    if platform.system() != 'Linux' or platform.machine() != target:
        raise ValueError('the source SDK recipe requires a native ' + target + ' Linux builder')
    info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if info.get('ID', '').strip('"') != 'debian' or info.get('VERSION_ID', '').strip('"') != '12':
        raise ValueError('production source SDK must be built on the declared Debian 12 host baseline')
    for name in ('make', 'gcc', 'g++', 'patch', 'tar', 'gzip', 'bzip2', 'xz', 'cpio', 'rsync', 'gawk', 'wget', 'python3'):
        if not shutil.which(name): raise ValueError('missing bootstrap tool: ' + name)
    return {'host': 'debian-12-' + target, 'status': 'passed'}


def prepare(recipe, cache, jobs, network):
    recipe, cache = Path(recipe).resolve(strict=True), Path(cache).absolute()
    manifest = read_json(recipe)
    if manifest['architecture'] not in ('x86_64', 'aarch64') or manifest['target'] != manifest['architecture'] + '-buildroot-linux-gnu':
        raise ValueError('unsupported native SDK target identity')
    identity = recipe_id(recipe)
    if any(not re.fullmatch(r'[A-Za-z0-9_./+-]+', str(path)) for path in (recipe, cache)):
        raise ValueError('upstream source preparation requires simple paths without spaces')
    bootstrap = cache / 'bootstrap' / manifest['buildroot']['file']
    fetch_file(manifest['buildroot'], bootstrap, network)
    fetch_file(manifest['glibc_source'], cache / 'downloads/glibc' / manifest['glibc_source']['file'], network)
    work = cache / 'work' / identity
    source = work / ('buildroot-' + manifest['buildroot']['version'])
    if not source.exists():
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            extraction = Path(temporary) / 'source'
            unpack_source(bootstrap, extraction)
            candidate = extraction / source.name
            overlay(candidate, manifest)
            candidate.rename(source)
    output = work / 'output'
    command = ['make', '-C', str(source), 'O=' + str(output), 'BR2_DL_DIR=' + str(cache / 'downloads'), 'BR2_EXTERNAL=' + str(recipe.parent), 'BR2_JLEVEL=' + str(jobs)]
    if not network:
        command += ['BR2_' + name + '=/bin/false' for name in ('WGET', 'GIT', 'SVN', 'HG', 'CVS', 'BZR', 'SCP', 'SFTP')]
    else:
        command += ['BR2_WGET=wget --timeout=30 --tries=2 -nv']
    subprocess.run(command + ['BR2_DEFCONFIG=' + str(recipe.parent / 'config'), 'defconfig'], check=True)
    text = (output / '.config').read_text().splitlines()
    for required in ('BR2_GCC_VERSION_15_X=y', 'BR2_TOOLCHAIN_BUILDROOT_GLIBC=y', 'BR2_DOWNLOAD_FORCE_CHECK_HASHES=y', 'BR2_PACKAGE_HOST_CMAKE=y', 'BR2_' + manifest['architecture'] + '=y') + tuple(key + '=y' for key in manifest.get('required_packages', [])):
        if required not in text: raise ValueError('required source SDK configuration disappeared')
    return manifest, identity, command, output


def fetch(recipe, cache, jobs):
    manifest, identity, command, output = prepare(recipe, cache, jobs, True)
    subprocess.run(command + ['source'], check=True)
    resolution = subprocess.check_output(command + ['--no-print-directory', 'show-info'], text=True)
    packages = __import__('json').loads(resolution)
    files = {}
    for package in packages.values():
        for item in package.get('downloads', []):
            name = str(relative('downloads/' + package['dl_dir'] + '/' + item['source']))
            path = Path(cache) / name
            actual = path.resolve(strict=True)
            if Path(cache).resolve() not in actual.parents: raise ValueError('source download escapes cache')
            files[name] = digest(actual)
    bootstrap = 'bootstrap/' + manifest['buildroot']['file']
    files[bootstrap] = digest(Path(cache) / bootstrap)
    if len(files) < 2: raise ValueError('incomplete resolved source closure')
    write_json(Path(cache) / 'resolution.json', packages)
    write_json(Path(cache) / 'source-inputs.json', {'schema_version': 1, 'recipe_id': identity, 'files': files,
               'resolution_sha256': digest(Path(cache) / 'resolution.json')})
    return {'recipe_id': identity, 'input_count': len(files)}


def verify_inputs(recipe, cache):
    state = read_json(Path(cache) / 'source-inputs.json')
    if state.get('recipe_id') != recipe_id(recipe): raise ValueError('source cache belongs to another complete recipe')
    cache = Path(cache).resolve(strict=True)
    if state.get('schema_version') != 1 or not isinstance(state.get('files'), dict) or not state['files']:
        raise ValueError('missing complete offline source inventory')
    for name, value in state['files'].items():
        path = cache.joinpath(*relative(name).parts)
        if path.is_symlink() or not path.is_file() or cache not in path.resolve().parents or digest(path) != value:
            raise ValueError('missing or changed offline source input: ' + name)
    resolution = cache / 'resolution.json'
    if not resolution.is_file() or digest(resolution) != state.get('resolution_sha256'):
        raise ValueError('missing or changed retained dependency resolution')
    manifest = read_json(recipe)
    expected = {'bootstrap/' + manifest['buildroot']['file']}
    for package in read_json(resolution).values():
        for item in package.get('downloads', []):
            expected.add(str(relative('downloads/' + package['dl_dir'] + '/' + item['source'])))
    if set(state['files']) != expected or 'downloads/glibc/' + manifest['glibc_source']['file'] not in expected:
        raise ValueError('offline source inventory does not cover the complete resolved inputs')
    for item, name in ((manifest['buildroot'], 'bootstrap/' + manifest['buildroot']['file']),
                       (manifest['glibc_source'], 'downloads/glibc/' + manifest['glibc_source']['file'])):
        if state['files'].get(name) != item['sha256']:
            raise ValueError('offline source inventory differs from pinned bootstrap inputs')
    return state


def preserve_sources(recipe, cache, output):
    state = verify_inputs(recipe, cache)
    output = Path(output)
    if output.exists(): raise ValueError('source export destination must be new')
    (output / 'recipe').mkdir(parents=True)
    shutil.copyfile(recipe, output / 'recipe/recipe.json')
    for name in ('config', 'Config.in', 'external.desc', 'external.mk'):
        shutil.copyfile(Path(recipe).parent / name, output / 'recipe' / name)
    for name in TOOLS:
        (output / 'tools').mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).parent / name, output / 'tools' / name)
    for name in state['files']:
        target = output / 'cache' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(cache) / name, target)
    for name in ('source-inputs.json', 'resolution.json'):
        shutil.copyfile(Path(cache) / name, output / 'cache' / name)
    license_path = Path(__file__).resolve().parents[1] / 'LICENSE'
    if license_path.is_file(): shutil.copyfile(license_path, output / 'LICENSE')
    write_json(output / 'sources.json', {'schema_version': 1, 'recipe_id': state['recipe_id'], 'files': file_inventory(output)})
    return state['recipe_id']


def remove_host_compatibility_alias(host):
    """Omit Buildroot's exact historical host/usr -> . ancestor alias."""
    host = Path(host)
    if host.is_symlink() or not host.is_dir():
        raise ValueError('supplier host root must be an ordinary directory')
    alias = host / 'usr'
    if not alias.is_symlink():
        if alias.exists():
            raise ValueError("unexpected supplier host alias entry: usr (expected link '.')")
        return
    if os.readlink(alias) != '.' or alias.resolve(strict=True) != host.resolve(strict=True):
        raise ValueError("unexpected supplier host alias target: usr (expected '.')")
    # package/skeleton/skeleton.mk creates this build-time compatibility alias.
    # Tools now live directly in host; target sysroot/usr remains untouched.
    alias.unlink()


def remove_runtime_aliases(sysroot):
    """Omit exact target OS service links that have no meaning in a compiler SDK."""
    sysroot = Path(sysroot)
    expected = {'etc/mtab': '../proc/self/mounts', 'etc/resolv.conf': '../run/resolv.conf'}
    candidates = []
    for name, target in expected.items():
        path = sysroot / name
        if path.parent.is_symlink():
            raise ValueError('runtime alias parent must be an ordinary directory: ' + name)
        if not path.is_symlink():
            if path.exists():
                raise ValueError('unexpected runtime alias entry: ' + name)
            continue
        if os.readlink(path) != target:
            raise ValueError('unexpected runtime alias target: ' + name)
        candidates.append(path)
    # Validate both entries before removing either. Other dangling links still
    # fail the ordinary confined materialization check below.
    for path in candidates:
        path.unlink()


# Reviewed glibc install inventory: catgets, iconv, locale, posix, nss, nscd, elf and
# sysdeps/unix/sysv/linux Makefiles; iconvdata installs the gconv directory.
# These are target OS programs/modules, not host tools or linker inputs.
GLIBC_RUNTIME_SOURCE = '42458698e0f9956cf0a8529aa39c318b5130d15a20a40c87fa5cc0054ba19939'
GLIBC_TARGET_PROGRAMS = (
    'usr/bin/gencat', 'usr/bin/iconv', 'usr/bin/locale', 'usr/bin/localedef', 'usr/bin/getconf',
    'usr/bin/getent', 'usr/bin/makedb', 'usr/bin/pldd', 'usr/bin/sprof',
    'usr/sbin/iconvconfig', 'usr/sbin/nscd',
)
GLIBC_TARGET_DIRECTORIES = ('usr/lib/gconv', 'usr/lib64/gconv', 'usr/libexec/getconf')


def omit_target_runtime(root, sysroot_name, source_sha256):
    """Project a reviewed libc install into a compiler SDK after materialization."""
    if source_sha256 != GLIBC_RUNTIME_SOURCE:
        raise ValueError('target runtime omission needs a reviewed glibc source identity')
    root = Path(root).resolve(strict=True)
    sysroot = root.joinpath(*relative(sysroot_name).parts)
    if sysroot.is_symlink() or not sysroot.is_dir() or root not in sysroot.resolve().parents:
        raise ValueError('target runtime omission needs a contained ordinary sysroot')
    selected = []
    for name in GLIBC_TARGET_PROGRAMS + GLIBC_TARGET_DIRECTORIES:
        path = sysroot / name
        if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            raise ValueError('target runtime omission parent must be an ordinary directory')
        if path.is_symlink():
            raise ValueError('target runtime omission requires materialized inputs')
        if not path.exists():
            continue
        directory = name in GLIBC_TARGET_DIRECTORIES
        if (directory and not path.is_dir()) or (not directory and not path.is_file()):
            raise ValueError('unexpected target runtime input type: ' + name)
        if directory:
            for child in path.rglob('*'):
                if child.is_symlink() or not (child.is_file() or child.is_dir()):
                    raise ValueError('target runtime directory contains an unsupported entry')
        selected.append(path)
    omitted = sorted(path.relative_to(root).as_posix() for path in selected)
    # Supplier relocation lists may name generated text inside an omitted tree.
    # Preserve every other entry and reject malformed paths before any removal.
    relocations = root / 'share/buildroot/sdk-relocs'
    if relocations.is_symlink() or not relocations.is_file():
        raise ValueError('target runtime omission requires its supplier relocation list')
    lines = relocations.read_text(encoding='utf-8').splitlines()
    normalized = []
    for name in lines:
        # Buildroot prepare-sdk emits './relative/path'. Accept that exact
        # prefix, validate the remainder, and preserve original retained text.
        item = name[2:] if name.startswith('./') else name
        if relative(item).as_posix() != item:
            raise ValueError('noncanonical supplier relocation entry')
        normalized.append(item)
    retained = [name for name, item in zip(lines, normalized)
                if not any(item == removed or item.startswith(removed + '/') for removed in omitted)]
    for path in selected:
        if path.is_dir(): shutil.rmtree(path)
        else: path.unlink()
    if retained != lines:
        relocations.write_text(''.join(name + '\n' for name in retained), encoding='utf-8')
    return {'source_sha256': source_sha256, 'paths': omitted}


def build(recipe, cache, destination, jobs):
    host_check(recipe)
    verify_inputs(recipe, cache)
    manifest, identity, command, output = prepare(recipe, cache, jobs, False)
    subprocess.run(command + ['sdk', 'legal-info'], check=True)
    verify_inputs(recipe, cache)
    destination = Path(destination).absolute()
    if destination.exists(): raise ValueError('SDK group destination must be new')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sdk_temporary_directory(dir=destination.parent, prefix='sdk-build-') as temporary:
        work = Path(temporary)
        supplier = output / 'host'
        remove_host_compatibility_alias(supplier)
        # Remove virtual filesystem aliases from the target sysroot. They are
        # runtime host services, never compiler inputs or application libraries.
        sysroot = supplier / manifest['target'] / 'sysroot'
        remove_runtime_aliases(sysroot)
        for name in ('dev', 'proc', 'sys', 'run', 'tmp', 'var'):
            path = sysroot / name
            if path.is_symlink(): path.unlink()
            elif path.is_dir(): shutil.rmtree(path)
        # Normalize SDK absolute aliases to their corresponding contained paths.
        for path in supplier.rglob('*'):
            if path.is_symlink() and os.readlink(path).startswith('/'):
                candidate = sysroot / os.readlink(path).lstrip('/')
                if candidate.exists():
                    path.unlink()
                    path.symlink_to(os.path.relpath(candidate, path.parent))
                else: raise ValueError('unresolved absolute SDK link: ' + str(path))
        tree = work / 'sdk'
        materialize(supplier, tree, path_policy='linux-case-sensitive-v1')
        omitted = omit_target_runtime(tree, manifest['target'] + '/sysroot', manifest['glibc_source']['sha256'])
        licenses = tree / 'share/sdk-licenses'
        shutil.copytree(output / 'legal-info', licenses, ignore=lambda directory, entries: set(entries) & {'sources', 'host-sources'})
        # Buildroot relocates selected generated text files on installation.
        sources = work / 'sources'
        preserve_sources(recipe, cache, sources)
        target = {'system': 'Linux', 'processor': manifest['architecture'], 'triple': manifest['target'],
                  'sysroot': manifest['target'] + '/sysroot', 'cxx_compiler': 'bin/' + manifest['target'] + '-g++',
                  'c_compiler': 'bin/' + manifest['target'] + '-gcc'}
        metadata = seal(tree, identity, target, digest(sources / 'sources.json'), licenses=['share/sdk-licenses'],
                        runtime_source_sha256=manifest['glibc_source']['sha256'], path_policy='linux-case-sensitive-v1',
                        host_tools={'cmake': 'bin/cmake', 'ctest': 'bin/ctest', 'cpack': 'bin/cpack', 'ninja': 'bin/ninja', 'python': 'bin/python3'})
        metadata['relocation'] = 'buildroot'
        metadata['omitted_target_runtime'] = omitted
        metadata['capabilities'] = manifest.get('capabilities', ['core', 'terminal', 'framebuffer', 'hosted-web'])
        metadata['runtime_host_services'] = manifest.get('runtime_host_services', [])
        write_json(tree / 'sdk.json', metadata)
        return export_group(tree, sources, destination, manifest['source_date_epoch'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('recipe-id', 'bootstrap', 'fetch', 'build', 'export-sources', 'verify-inputs'))
    parser.add_argument('--recipe', type=Path, default=Path(__file__).resolve().parents[1] / 'third_party/sdk/recipe.json')
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1: parser.error('jobs must be positive')
    if args.action == 'recipe-id': result = {'recipe_id': recipe_id(args.recipe)}
    elif args.action == 'bootstrap': result = {'distribution': 'Debian 12 Bookworm', 'packages': read_json(args.recipe)['bootstrap_packages'], 'install': 'apt-get install <listed packages>', 'check': host_check(args.recipe)}
    else:
        if not args.cache: parser.error('--cache is required')
        if args.action in ('build', 'export-sources') and not args.output: parser.error('--output is required')
        if args.action == 'fetch': result = fetch(args.recipe, args.cache.resolve(), args.jobs)
        elif args.action == 'build': result = build(args.recipe, args.cache.resolve(), args.output, args.jobs)
        elif args.action == 'export-sources': result = {'recipe_id': preserve_sources(args.recipe, args.cache.resolve(), args.output)}
        else: result = verify_inputs(args.recipe, args.cache.resolve())
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
