#!/usr/bin/env python3
"""Inspect ELF files without executing them; enforce the declared runtime floor."""
import argparse
from pathlib import Path
import re
import subprocess
from dependency_archive import digest, encoded, write_json

BOOKWORM = {'GLIBC': '2.36', 'GLIBCXX': '3.4.30', 'CXXABI': '1.3.13', 'GCC': '12.0.0'}
# Explicit capability-to-runtime floors; unknown names still fail version().
# glibc 2.36 NEWS and elf/Versions establish this loader capability.
NAMED_ABI_FLOORS = {('GLIBC', 'ABI_DT_RELR'): '2.36'}
MACHINES = {'x86_64': 'Advanced Micro Devices X86-64', 'aarch64': 'AArch64'}
HOST_LIBRARIES = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1',
                  'libresolv.so.2', 'libutil.so.1', 'ld-linux-x86-64.so.2', 'ld-linux-aarch64.so.1'}

SDK_RUNTIME_ALIASES = {
    'libc_malloc_debug.so': 'libc_malloc_debug.so.0', 'libcrypt.so': 'libcrypt.so.1',
    'libmvec.so': 'libmvec.so.1', 'libresolv.so': 'libresolv.so.2',
    'libBrokenLocale.so': 'libBrokenLocale.so.1', 'libnss_compat.so': 'libnss_compat.so.2',
    'libnss_db.so': 'libnss_db.so.2', 'libnss_hesiod.so': 'libnss_hesiod.so.2', 'libnsl.so': 'libnsl.so.1',
}
SDK_RUNTIME_NAMES = HOST_LIBRARIES | {'libanl.so.1', 'libBrokenLocale.so.1', 'libnss_compat.so.2',
    'libnss_dns.so.2', 'libnss_files.so.2', 'libnss_hesiod.so.2', 'libnss_db.so.2',
    'libnsl.so.1', 'libmvec.so.1', 'libmemusage.so', 'libpcprofile.so', 'libc_malloc_debug.so.0', 'libcrypt.so.1'} | set(SDK_RUNTIME_ALIASES)


def version(value):
    if not re.fullmatch(r'\d+(?:\.\d+)*', value):
        raise ValueError('unsupported named ABI requirement: ' + value)
    return tuple(int(x) for x in value.split('.'))


def elf(path):
    with Path(path).open('rb') as stream:
        return stream.read(4) == b'\x7fELF'


def run(readelf, *args):
    return subprocess.check_output([str(readelf), '--wide', *map(str, args)], text=True,
                                   env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, stderr=subprocess.STDOUT)


def inspect(path, readelf='readelf', sdk_private=False):
    path = Path(path)
    header = run(readelf, '--file-header', path)
    machine = re.search(r'^\s*Machine:\s*(.+)$', header, re.M)
    if not machine or not re.search(r'^\s*Class:\s*ELF64$', header, re.M):
        raise ValueError('expected a supported 64-bit ELF file')
    dynamic = run(readelf, '--dynamic', path)
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', dynamic)
    rpath = re.findall(r'\(RPATH\).*?\[([^\]]*)\]', dynamic)
    runpath = re.findall(r'\(RUNPATH\).*?\[([^\]]*)\]', dynamic)
    headers = run(readelf, '--program-headers', path)
    loader = re.findall(r'Requesting program interpreter:\s*([^\]]+)', headers)
    info = run(readelf, '--version-info', path)
    requirements = {}
    named_requirements = {}
    # Only dependency imports matter; version definitions in an exported library
    # describe its capabilities rather than its own runtime requirements.
    needs = info.split('Version needs section', 1)
    if len(needs) == 2:
        for family, value in re.findall(r'Name:\s*(GLIBCXX|GLIBC|CXXABI|GCC)_([^\s]+)', needs[1]):
            if sdk_private and family == 'GLIBC' and value == 'PRIVATE':
                continue
            floor = NAMED_ABI_FLOORS.get((family, value))
            if floor is not None:
                named_requirements[family + '_' + value] = floor
                value = floor
            parsed = version(value)
            if parsed > version(requirements.get(family, '0')):
                requirements[family] = value
    result = {'sha256': digest(path), 'machine': machine.group(1).strip(), 'needed': sorted(needed),
            'rpaths': rpath + runpath, 'rpath': rpath, 'runpath': runpath,
            'loader': loader, 'requirements': requirements, 'named_requirements': named_requirements}
    if sdk_private:
        definitions = needs[0].split('Version definition section', 1)
        definition_text = definitions[1] if len(definitions) == 2 else ''
        result['glibc_definitions'] = sorted(set(re.findall(r'Name:\s*GLIBC_([0-9.]+)\b', definition_text)), key=version)
        result['defines_private'] = bool(re.search(r'Name:\s*GLIBC_PRIVATE\b', definition_text))
        private = []
        if len(needs) == 2:
            provider = None
            for line in needs[1].splitlines():
                match = re.search(r'File:\s*(\S+)', line)
                if match: provider = match[1]
                if re.search(r'Name:\s*GLIBC_PRIVATE\b', line):
                    if provider is None: raise ValueError('missing SDK private provider identity')
                    private.append(provider)
        result['private_requirements'] = sorted(set(private))
    return result


def resolve_closure(root, results):
    """Prove private edges using contained loader paths, without environment help."""
    base = root if root.is_dir() else root.parent
    paths = {name: base / name for name in results}
    by_path = {path.resolve(): name for name, path in paths.items()}
    for name in results:
        if Path(name).name in HOST_LIBRARIES:
            raise ValueError('package must not bundle the target libc or loader: ' + name)
    reached = set()
    resolutions = {}

    def directories(name, key):
        return tuple(dict.fromkeys((paths[name].parent / item.removeprefix('$ORIGIN').lstrip('/')).resolve()
                                   for value in results[name][key] for item in value.split(':')))

    def visit(name, inherited, active):
        context = (name, inherited)
        if context in active:
            return
        active = active | {context}
        reached.add(name)
        entry = results[name]
        own = directories(name, 'rpath') if not entry['runpath'] else ()
        chain = tuple(dict.fromkeys(own + inherited))
        # RUNPATH applies to direct edges only. RPATH may be inherited by
        # descendants; a requesting object's RUNPATH overrides that search.
        search = directories(name, 'runpath') if entry['runpath'] else chain
        for needed in entry['needed']:
            if not needed or '/' in needed or '\\' in needed:
                raise ValueError('target dependency must use a bare library name')
            if needed in HOST_LIBRARIES:
                continue
            candidates = set()
            for directory in search:
                provider = directory / needed
                if provider.exists():
                    resolved = provider.resolve(strict=True)
                    if resolved not in by_path:
                        raise ValueError('runtime provider is outside the inspected ELF inventory: ' + needed)
                    candidates.add(by_path[resolved])
            if not candidates:
                raise ValueError('package runtime closure is incomplete: loader cannot resolve ' + needed + ' from ' + name)
            if len(candidates) != 1:
                raise ValueError('ambiguous runtime loader providers: ' + needed + ' from ' + name)
            provider = next(iter(candidates))
            previous = resolutions.setdefault((name, needed), provider)
            if previous != provider:
                raise ValueError('runtime provider changes between executable contexts: ' + needed)
            visit(provider, chain, active)

    for name, entry in results.items():
        if entry['loader']:
            visit(name, (), set())
    # A library outside an executable's closure needs its own usable paths;
    # dynamically selected modules cannot silently borrow an unknown context.
    for name in results:
        if name not in reached:
            visit(name, (), set())
    return [{'from': name, 'needed': needed, 'provider': provider}
            for (name, needed), provider in sorted(resolutions.items())]


def sdk_runtime_context(root, processor, declaration):
    """Validate the declared, retained libc/loader cohort inside one target root."""
    if not root.is_dir() or declaration.get('glibc') != '2.36' or declaration.get('processor') != processor:
        raise ValueError('SDK runtime audit needs the exact Bookworm target sysroot')
    for key in ('recipe_id', 'source_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', declaration.get(key, '')):
            raise ValueError('SDK runtime audit needs retained recipe and source identities')
    files = declaration.get('files')
    if not isinstance(files, dict) or not files: raise ValueError('missing SDK runtime cohort inventory')
    approved = set()
    for name, value in files.items():
        path = root / name
        if (str(Path(name)) != name or Path(name).is_absolute() or '..' in Path(name).parts
                or Path(name).parent.as_posix() not in ('lib', 'lib64', 'usr/lib', 'usr/lib64')
                or path.name not in SDK_RUNTIME_NAMES or path.is_symlink() or not path.is_file()
                or root not in path.resolve().parents or digest(path) != value):
            raise ValueError('SDK runtime cohort path or digest differs from retained input')
        approved.add(name)
    loader = 'ld-linux-x86-64.so.2' if processor == 'x86_64' else 'ld-linux-aarch64.so.1'
    if not {'libc.so.6', loader} <= {Path(name).name for name in approved}:
        raise ValueError('SDK runtime cohort must contain its matched libc and loader')
    by_name = {}
    for name in approved:
        by_name.setdefault(Path(name).name, set()).add(files[name])
    if any(len(values) != 1 for values in by_name.values()):
        raise ValueError('SDK runtime cohort has conflicting providers')
    # Materialization turns supplier development links into ordinary files.
    # An exact alias is eligible only with the identical retained SONAME file.
    for alias, provider in SDK_RUNTIME_ALIASES.items():
        if alias in by_name and by_name[alias] != by_name.get(provider):
            raise ValueError('SDK development alias lacks its identical runtime provider')
    return approved


def check_sdk_runtime(results, approved, declaration):
    providers = {Path(name).name: value for name, value in results.items() if name in approved}
    if set(approved) - set(results): raise ValueError('SDK runtime cohort contains a non-ELF input')
    for name in approved:
        entry = results[name]
        for defined in entry.get('glibc_definitions', []):
            if version(defined) > version(declaration['glibc']):
                raise ValueError('SDK libc definition exceeds its pinned runtime version')
        if Path(name).name == 'libc.so.6' and declaration['glibc'] not in entry.get('glibc_definitions', []):
            raise ValueError('SDK libc does not expose the pinned runtime version')
        for provider in entry.get('private_requirements', []):
            if provider not in providers or not providers[provider].get('defines_private'):
                raise ValueError('SDK private requirement lacks its matched runtime provider')


def requires_extended_x86_isa(notes):
    # Wide readelf may place NEEDED and USED properties on the same line.
    # USED describes optional dispatched code; only NEEDED raises the CPU floor.
    return bool(re.search(r'\bx86 ISA needed:[^:\r\n]*\bx86-64-v[234]\b', notes))


def audit(root, processor='x86_64', ceilings=None, readelf='readelf', host=False, runtime_resolution=True, sdk_sysroot=None):
    root = Path(root).resolve(strict=True)
    ceilings = BOOKWORM if ceilings is None else ceilings
    if processor not in MACHINES:
        raise ValueError('unsupported processor')
    if sdk_sysroot is not None and not host:
        raise ValueError('SDK runtime allowance cannot be used for application packages')
    approved = sdk_runtime_context(root, processor, sdk_sysroot) if sdk_sysroot is not None else set()
    results = {}
    for path in sorted(root.rglob('*')) if root.is_dir() else [root]:
        if path.is_symlink():
            if root.is_dir() and root not in path.resolve(strict=True).parents:
                raise ValueError('runtime path escapes the inspected tree')
            continue
        if not path.is_file() or not elf(path):
            continue
        name = path.relative_to(root).as_posix() if root.is_dir() else path.name
        entry = inspect(path, readelf, sdk_private=True) if name in approved else inspect(path, readelf)
        notes = run(readelf, '--notes', path)
        if not host and requires_extended_x86_isa(notes):
            raise ValueError('ELF requires instructions above the generic x86_64 baseline')
        if entry['machine'] != MACHINES[processor]:
            raise ValueError('wrong ELF architecture: ' + str(path))
        for family, required in entry['requirements'].items():
            if family not in ceilings or version(required) > version(ceilings[family]):
                raise ValueError('runtime requirement above ceiling: ' + family + '_' + required + ': ' + str(path))
        if not host:
            allowed_loader = '/lib64/ld-linux-x86-64.so.2' if processor == 'x86_64' else '/lib/ld-linux-aarch64.so.1'
            if any(item != allowed_loader for item in entry['loader']):
                raise ValueError('unexpected target loader path')
            for rpath in entry['rpaths']:
                for item in rpath.split(':'):
                    if not item or not (item == '$ORIGIN' or item.startswith('$ORIGIN/')):
                        raise ValueError('target runtime search path must be relative to its executable')
                    resolved = (path.parent / item.removeprefix('$ORIGIN').lstrip('/')).resolve()
                    if root.is_dir() and resolved != root and root not in resolved.parents:
                        raise ValueError('target runtime search path escapes package')
        name = path.relative_to(root).as_posix() if root.is_dir() else path.name
        results[name] = entry
    if not results:
        raise ValueError('no ELF files inspected')
    if sdk_sysroot is not None:
        check_sdk_runtime(results, approved, sdk_sysroot)
    resolution = []
    if not host:
        provided = {Path(name).name for name in results}
        for entry in results.values():
            absent = set(entry['needed']) - provided - HOST_LIBRARIES
            if absent:
                raise ValueError('package runtime closure is incomplete: ' + ', '.join(sorted(absent)))
        if runtime_resolution:
            resolution = resolve_closure(root, results)
    return {'schema_version': 1, 'processor': processor, 'ceilings': ceilings,
            'scope': 'sdk-sysroot' if sdk_sysroot is not None else ('host' if host else ('target' if runtime_resolution else 'staged-requirements')),
            'sdk_runtime': sdk_sysroot,
            'runtime_resolution': 'passed' if not host and runtime_resolution else 'not_checked',
            'resolution': resolution, 'files': results, 'status': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--processor', choices=tuple(MACHINES), default='x86_64')
    parser.add_argument('--readelf', default='readelf')
    parser.add_argument('--host', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): args.output.unlink()
    write_json(args.output, audit(args.root, args.processor, readelf=args.readelf, host=args.host))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
