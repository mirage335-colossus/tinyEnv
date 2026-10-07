#!/usr/bin/env python3
"""Prepare an offline native development prefix from explicit retained Debian inputs."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def run(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8').strip()


def relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or str(p) != name or any(x in ('', '.', '..') for x in p.parts) or '\\' in name:
        raise ValueError('invalid retained development path')
    return p


def runtimes(data):
    if run('dpkg', '--print-architecture') != data['architecture']:
        raise ValueError('native development prefix architecture differs from host')
    versions = {p['package']: p['version'] for p in data['packages']}
    found = {}
    for item in data['runtime_libraries']:
        package = item['package'] + ':' + data['architecture']
        version = run('dpkg-query', '-W', '-f=${Version}', package)
        if version != versions[item['development']]: raise ValueError('installed runtime and development package versions differ')
        candidates = [Path(p).resolve(strict=True) for p in run('dpkg-query', '-L', package).splitlines()
                      if Path(p).name == item['soname'] and Path(p).is_file()]
        if len(set(candidates)) != 1: raise ValueError('runtime provider is absent or ambiguous')
        link = str(relative(item['link']));source = candidates[0]
        if link in found: raise ValueError('duplicate runtime link')
        found[link] = {'package': package, 'version': version, 'path': str(source), 'sha256': digest(source)}
    return found


def inventory(root, runtime):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        name = path.relative_to(root).as_posix()
        if name == 'prepared.json': continue
        if path.is_symlink():
            actual = path.resolve(strict=True)
            if name in runtime:
                if str(actual) != runtime[name]['path'] or digest(actual) != runtime[name]['sha256']:
                    raise ValueError('prepared runtime alias changed')
            elif Path(root).resolve() not in actual.parents:
                raise ValueError('development alias escapes its prepared tree')
            result[name] = {'link': os.readlink(path)}
        elif path.is_file(): result[name] = {'sha256': digest(path)}
        elif not path.is_dir(): raise ValueError('unsupported development prefix entry')
    return result


def extract_deb(archive, stage):
    # Read metadata before extraction; never ask dpkg to follow archive paths.
    raw = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(archive)])
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        members, entries = [], {}
        for member in tar:
            name = member.name.removeprefix('./').rstrip('/')
            if not name: continue
            name = str(relative(name)); member.name = name
            if name.split('/',1)[0] in ('prepared.json','inputs.json','retained-packages'):
                raise ValueError('development archive collides with preparation metadata')
            if member.mode & 0o7000 or not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError('unsupported development archive entry')
            if name in entries and not (member.isdir() and entries[name].isdir()):
                raise ValueError('duplicate development archive member')
            entries[name] = member; members.append(member)
        for name, member in entries.items():
            for parent in PurePosixPath(name).parents:
                if str(parent) in entries and not entries[str(parent)].isdir():
                    raise ValueError('development archive traverses a non-directory')
            target = stage / name
            if any(p.is_symlink() for p in (target,*target.parents) if p != stage and stage in p.parents):
                raise ValueError('development archive traverses a previous alias')
            if target.exists() and not (target.is_dir() and member.isdir()):
                if member.isfile() and target.is_file() and target.read_bytes() == tar.extractfile(member).read(): continue
                raise ValueError('development archives conflict')
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir(): target.mkdir(exist_ok=True)
            elif member.issym(): target.symlink_to(member.linkname)
            else:
                with tar.extractfile(member) as source, target.open('xb') as out: shutil.copyfileobj(source, out)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def prepare(manifest, packages, output, download=False):
    manifest, packages, output = Path(manifest).resolve(strict=True), Path(packages).absolute(), Path(output).absolute()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not data.get('packages') or not re.fullmatch('[a-z0-9]+', data.get('architecture','')):
        raise ValueError('invalid pinned development manifest')
    if output.exists() or output.is_symlink(): raise ValueError('prepared development destination must be new')
    runtime = runtimes(data)
    packages.mkdir(parents=True, exist_ok=True)
    names, identities = set(), set()
    for item in data['packages']:
        name = item['file']
        if Path(name).name != name or not name.endswith('.deb') or name in names or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise ValueError('invalid pinned development archive')
        if item['package'] in identities or not re.fullmatch('[a-z0-9][a-z0-9+.-]*',item['package']):
            raise ValueError('duplicate or invalid development package identity')
        identities.add(item['package'])
        if item.get('architecture',data['architecture']) not in ('all',data['architecture']):
            raise ValueError('development package architecture differs from selected host')
        names.add(name);archive = packages / name
        if not archive.exists() and download:
            if not item['url'].startswith('https://deb.debian.org/debian/'):
                raise ValueError('unapproved development archive origin')
            with tempfile.NamedTemporaryFile(dir=packages, delete=False) as f: partial = Path(f.name)
            try:
                with urllib.request.urlopen(item['url'], timeout=60) as source, partial.open('wb') as out: shutil.copyfileobj(source,out)
                if digest(partial) != item['sha256']: raise ValueError('downloaded development checksum differs')
                if archive.exists(): raise ValueError('development archive appeared during fetch')
                partial.rename(archive)
            finally: partial.unlink(missing_ok=True)
        if not archive.is_file() or digest(archive) != item['sha256']: raise ValueError('missing or changed retained development archive')
        for field, expected in [('Package',item['package']),('Version',item['version']),('Architecture',item.get('architecture',data['architecture']))]:
            if run('dpkg-deb','-f',str(archive),field) != expected: raise ValueError('development package metadata differs: '+field)
        source = run('dpkg-deb','-f',str(archive),'Source').split(' ',1)[0] or item['package']
        if source != item['source_package']: raise ValueError('development source package identity differs')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.development-',dir=output.parent) as temporary:
        stage=Path(temporary)/'prefix';stage.mkdir()
        for item in data['packages']: extract_deb(packages/item['file'],stage)
        if not (stage/'usr/include').is_dir(): raise ValueError('development prefix has no headers')
        for name, provider in runtime.items():
            path=stage/name
            if not path.is_symlink(): raise ValueError('declared runtime linker alias is missing')
            if any(parent.is_symlink() for parent in path.parents if stage in parent.parents): raise ValueError('runtime alias parent is a link')
            path.unlink();path.symlink_to(provider['path'])
        retained=stage/'retained-packages';retained.mkdir()
        for item in data['packages']: shutil.copyfile(packages/item['file'],retained/item['file'])
        shutil.copyfile(manifest,stage/'inputs.json')
        state={'schema_version':1,'manifest_sha256':digest(stage/'inputs.json'),'runtime_libraries':runtime,'files':inventory(stage,runtime)}
        (stage/'prepared.json').write_text(json.dumps(state,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        verify(stage)
        stage.rename(output)
    return state


def verify(root, expected=None):
    root=Path(root).resolve(strict=True)
    if expected is not None and digest(root/'prepared.json') != expected:
        raise ValueError('configured development prefix identity changed')
    state=json.loads((root/'prepared.json').read_text(encoding='utf-8'))
    data=json.loads((root/'inputs.json').read_text(encoding='utf-8'))
    if state.get('schema_version')!=1 or state['manifest_sha256']!=digest(root/'inputs.json'):
        raise ValueError('prepared development manifest changed')
    if runtimes(data)!=state['runtime_libraries'] or inventory(root,state['runtime_libraries'])!=state['files']:
        raise ValueError('prepared development inputs or host runtime changed')
    return {'sha256':digest(root/'prepared.json'),'prefix':str(root/'usr')}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--manifest',type=Path,required=True);a.add_argument('--packages',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--download',action='store_true')
    a=sub.add_parser('verify');a.add_argument('root',type=Path);a.add_argument('--expected-sha256')
    a=p.parse_args();print(json.dumps(verify(a.root,a.expected_sha256) if a.action=='verify' else prepare(a.manifest,a.packages,a.output,a.download),sort_keys=True))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:raise SystemExit(str(error))
