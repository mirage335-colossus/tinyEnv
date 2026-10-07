#!/usr/bin/env python3
"""Pinned host-only Windows graphics inputs; offline selective staging by default."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import process_tree

LOCK_PATH = Path(__file__).resolve().parents[1] / 'third_party/host-graphics/mesa-windows.json'
FORBIDDEN_ENV = ('MESA_GL_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE', 'MESA_EXTENSION_OVERRIDE')
SELECTED = ('opengl32.dll', 'libgallium_wgl.dll')


class GraphicsError(ValueError):
    pass


def retain_required(error):
    """Whether outer extraction/output cleanup must preserve uncertain writers."""
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        receipt = getattr(current, 'graphics_receipt', None)
        if (isinstance(current, process_tree.ProcessTreeError)
                or (isinstance(receipt, dict) and receipt.get('cleanup') != 'removed')):
            return True
        pending.extend((getattr(current, '__cause__', None), getattr(current, '__context__', None)))
    return False


class Staging:
    def __init__(self, environment, receipt):
        self.environment, self.receipt = environment, receipt
        self.writers_uncertain = False

    def mark_writers_uncertain(self):
        """Preserve staging if the caller cannot prove descendant completion."""
        self.writers_uncertain = True


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GraphicsError('duplicate JSON field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def lock():
    value = _json(LOCK_PATH.read_bytes())
    if (value.get('schema_version') != 1 or value.get('scope') != 'host-qualification-only'
            or value.get('architecture') != 'x86_64' or value.get('redistribution', {}).get('approved') is not False
            or set(value.get('files', {})) != set(SELECTED)):
        raise GraphicsError('unsupported host graphics lock')
    for item in [value['archive'], *value['files'].values()]:
        if (type(item.get('size')) is not int or not 0 < item['size'] < 256 * 1024 * 1024
                or not re.fullmatch('[0-9a-f]{64}', item.get('sha256', ''))):
            raise GraphicsError('invalid locked file identity')
    for name in SELECTED:
        if value['files'][name].get('member') != 'x64/' + name:
            raise GraphicsError('unexpected selected archive member')
    _https(value['archive']['url'])
    return value


def _plain(info):
    return not (getattr(info, 'st_file_attributes', 0) & 0x400)  # Windows reparse point.


def _directory(value):
    path = Path(os.path.abspath(value))
    if '..' in Path(value).parts:
        raise GraphicsError('dot-dot destination is unsupported')
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if not stat.S_ISDIR(info.st_mode) or not _plain(info):
            raise GraphicsError('directory must not contain links or reparse points')
    return path


def _identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not _plain(info) or info.st_nlink != 1:
        raise GraphicsError('input must be a singly linked regular file')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _protected_root(value):
    path = Path(os.path.abspath(value))
    if '..' in Path(value).parts:
        raise GraphicsError('dot-dot protected root is unsupported')
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or not _plain(info):
            raise GraphicsError('protected root contains a link, reparse point or non-directory')
    return path


def _checked_file(path, expected):
    path = _directory(Path(path).parent) / Path(path).name
    before = _identity(path)
    if before[2] != expected['size']:
        raise GraphicsError('file size differs from locked identity')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != before:
            raise GraphicsError('file changed before reading')
        remaining = expected['size']
        while remaining:
            data = stream.read(min(1024 * 1024, remaining))
            if not data:
                raise GraphicsError('file changed while reading')
            remaining -= len(data)
            digest.update(data)
        if stream.read(1):
            raise GraphicsError('file exceeded locked size')
    if _identity(path) != before or digest.hexdigest() != expected['sha256']:
        raise GraphicsError('file bytes differ from locked identity')
    return before


def verify_archive(path):
    metadata = lock()
    _checked_file(Path(path), metadata['archive'])
    return {'schema_version': 1, 'scope': metadata['scope'], 'architecture': metadata['architecture'],
            'archive': {key: metadata['archive'][key] for key in ('name', 'size', 'sha256')},
            'redistribution_approved': False}


def _https(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or any(ord(c) <= 32 for c in url)):
            raise ValueError('invalid transport URL')
        parsed.port
    except (TypeError, ValueError) as error:
        raise GraphicsError('a credential-free HTTPS URL is required') from error
    return url


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        _https(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def _publish(temporary, target):
    # Atomic no-replace publication, supported on the qualified NTFS and POSIX
    # fixtures. Unsupported filesystems fail without a direct-write fallback.
    if any(path.name.casefold() == target.name.casefold() for path in target.parent.iterdir()):
        raise GraphicsError('destination already exists; nothing replaced')
    try:
        os.link(temporary, target, follow_symlinks=False)
    except OSError as error:
        raise GraphicsError('atomic no-replace publication failed') from error
    temporary.unlink()


def _download(url, archive_path, acquisition):
    _https(url)
    target = _directory(Path(archive_path).parent) / Path(archive_path).name
    if target.exists() or target.is_symlink():
        receipt = verify_archive(target)
        receipt['acquisition'] = 'verified-cache'
        return receipt
    metadata = lock()['archive']
    # The URL may contain an operator access query; never include it or exception
    # text from urllib in diagnostics or receipts.
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.graphics-fetch-', dir=target.parent)
        temporary = Path(name)
        opener = urllib.request.build_opener(_HTTPSRedirect())
        started = time.monotonic()
        with os.fdopen(fd, 'wb') as output:
            with opener.open(urllib.request.Request(url, headers={'User-Agent': 'Foundation-host-input/1'}),
                             timeout=30) as response:
                _https(response.geturl())
                length = response.headers.get('Content-Length')
                if length is not None and length != str(metadata['size']):
                    raise GraphicsError('download size differs from locked archive')
                remaining = metadata['size']
                while remaining:
                    if time.monotonic() - started > 300:
                        raise GraphicsError('archive download exceeded its time bound')
                    data = response.read(min(1024 * 1024, remaining))
                    if not data:
                        raise GraphicsError('incomplete host archive download')
                    output.write(data)
                    remaining -= len(data)
                if response.read(1):
                    raise GraphicsError('download exceeded locked archive size')
            output.flush()
            os.fsync(output.fileno())
        _checked_file(temporary, metadata)
        _publish(temporary, target)
        temporary = None
        receipt = verify_archive(target)
        receipt['acquisition'] = acquisition
        return receipt
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GraphicsError('host archive acquisition failed; retained inputs remain unchanged') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fetch(archive_path, *, network=False):
    if Path(archive_path).exists() or Path(archive_path).is_symlink():
        receipt = verify_archive(archive_path)
        receipt['acquisition'] = 'verified-cache'
        return receipt
    if not network:
        raise GraphicsError('archive is absent; explicit maintenance network acquisition is required')
    return _download(lock()['archive']['url'], archive_path, 'supplier-maintenance')


def fetch_retained(url, archive_path):
    """Explicit operator HTTPS transfer of exactly the already pinned archive."""
    return _download(url, archive_path, 'operator-retained-https')


def child_environment(environment=None):
    result = dict(os.environ if environment is None else environment)
    if any(key.upper() in FORBIDDEN_ENV for key in result):
        raise GraphicsError('graphics capability override variables are prohibited')
    # Environment names are case-insensitive on Windows, including in fixtures
    # prepared on another system.
    result = {key: value for key, value in result.items() if key.upper() != 'GALLIUM_DRIVER'}
    result['GALLIUM_DRIVER'] = 'llvmpipe'
    return result


class _MsvcTelemetry:
    """The selected MSVC toolkit's optional VCTIP, never a basename allowlist.

    Microsoft documents this as a non-output telemetry child of cl.exe:
    https://github.com/microsoft/BuildXL/blob/main/Public/Sdk/Experimental/Msvc/VisualCpp/visualCpp.dsc
    Keep it contained and join it; do not grant it breakaway or a grace period.
    """
    def __init__(self, compiler, helper):
        self.compiler = Path(compiler).resolve(strict=True)
        self.helper = Path(helper).resolve(strict=True)
        if self.helper != self.compiler.with_name('vctip.exe'):
            raise GraphicsError('MSVC telemetry helper differs from the exact selected toolkit')
        self.identities = {path: self._identity(path) for path in (self.compiler, self.helper)}
        self.stopped_pids = []
        self.completed = False

    @staticmethod
    def _identity(path):
        before = _identity(path)
        value = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if _identity(path) != before:
            raise GraphicsError('MSVC toolkit input changed while being identified')
        return before, value

    def unchanged(self):
        if any(self._identity(path) != expected for path, expected in self.identities.items()):
            raise GraphicsError('MSVC compiler or telemetry helper changed during compilation')

    def validate(self, pid, image):
        self.unchanged()
        if Path(image).resolve(strict=True) != self.helper:
            raise process_tree.ProcessTreeError('live compiler descendant is not the exact selected VCTIP: ' +
                                               json.dumps({'pid': pid, 'image': image}))
        # The supervisor pinned and verified this identity, and queried its image
        # through that handle. The prelaunch file identity and bytes still match.
        self.stopped_pids.append(pid)
        return True

    def finish(self, owner):
        self.unchanged()
        owner.terminate(validate_live=self.validate)
        self.unchanged()
        owner.finish()
        self.completed = True

    def receipt(self):
        if not self.completed:
            raise GraphicsError('MSVC helper completion has not been established')
        return {'policy': 'exact-msvc-vctip',
                'outcome': 'verified-helper-terminated-and-joined' if self.stopped_pids else 'no-surviving-helper',
                'compiler': self.identities[self.compiler][1], 'helper': self.identities[self.helper][1],
                'stopped_pids': list(self.stopped_pids)}


def _msvc_telemetry(compiler):
    if os.name != 'nt':
        return None
    selected = Path(compiler).resolve(strict=True)
    helper = selected.with_name('vctip.exe')
    # A toolkit without this optional helper needs ordinary strict completion.
    try:
        helper.lstat()
    except FileNotFoundError:
        return None
    return _MsvcTelemetry(selected, helper)


def _command(argv, *, directory, environment, limit, timeout, record=None, compiler_helper=None):
    if record is not None:
        record = _directory(Path(record).parent) / Path(record).name
        if any(path.name.casefold() == record.name.casefold() for path in record.parent.iterdir()):
            raise GraphicsError('command log already exists; nothing replaced')
    with tempfile.TemporaryFile(dir=directory) as output:
        owner = process_tree.launch(argv, cwd=directory, stream=output, env=environment)
        try:
            deadline = time.monotonic() + timeout
            while owner.poll() is None:
                if os.fstat(output.fileno()).st_size > limit or time.monotonic() > deadline:
                    owner.terminate()
                    raise GraphicsError('host input command exceeded its output or time bound')
                time.sleep(0.01)
            if compiler_helper is not None and owner.process.returncode == 0:
                compiler_helper.finish(owner)
            else:
                owner.finish()
            if os.fstat(output.fileno()).st_size > limit:
                raise GraphicsError('host input command failed or exceeded its output bound')
            output.seek(0)
            raw = output.read(limit + 1)
            if owner.process.returncode != 0:
                raise GraphicsError('host input command failed; inspect its bounded log when supplied')
            return raw
        finally:
            try:
                owner.close()
            except BaseException as error:
                raise process_tree.ProcessTreeError('host command writer cleanup remains uncertain') from error
            if record is not None:
                output.seek(0)
                with record.open('xb') as log:
                    log.write(output.read(limit))


def run_owned(argv, cwd, log_path, *, environment=None, timeout=1800, max_bytes=16 * 1024 * 1024):
    """Run a bounded supervised command; retain a bounded log after all writers stop.

    Failures raise GraphicsError. ProcessTreeError means supervision was invalid
    or completion is uncertain; a surrounding stage preserves its DLLs. Never
    suppress that error and continue packaging.
    """
    if type(max_bytes) is not int or max_bytes <= 0 or timeout <= 0:
        raise GraphicsError('positive output and time bounds are required')
    directory = _directory(cwd)
    _command(argv, directory=directory, environment=child_environment(environment),
             limit=max_bytes, timeout=timeout, record=log_path)
    return {'schema_version': 1, 'returncode': 0, 'log_path': str(Path(log_path).absolute()),
            'log_sha256': hashlib.sha256(Path(log_path).read_bytes()).hexdigest()}


def _listing(raw, metadata):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise GraphicsError('archive listing must be UTF-8') from error
    entries = {}
    separator = None
    for block in re.split(r'\r?\n\s*\r?\n', text.strip()):
        fields = {}
        for line in block.splitlines():
            if ' = ' not in line:
                raise GraphicsError('unexpected archive listing output')
            key, value = line.split(' = ', 1)
            if key in fields:
                raise GraphicsError('duplicate archive metadata')
            fields[key] = value
        displayed = fields.get('Path', '')
        # 7-Zip displays archive names with the host's separator. Interpret one
        # consistent form, then apply the same canonical member checks below.
        style = '\\' if '\\' in displayed else '/' if '/' in displayed else None
        if ('\\' in displayed and '/' in displayed or
                style is not None and separator is not None and style != separator):
            raise GraphicsError('mixed archive entry path separators: ' + repr(displayed[:240]))
        if style is not None:
            separator = style
        path = displayed.replace('\\', '/')
        posix = PurePosixPath(path)
        if (not path or ':' in path or posix.is_absolute() or '..' in posix.parts
                or str(posix) != path or any(ord(char) < 32 for char in path)):
            raise GraphicsError('unsafe archive entry path: ' + repr(displayed[:240]))
        fields['Path'] = path
        key = path.casefold()
        if key in entries:
            raise GraphicsError('duplicate archive entry')
        entries[key] = fields
    for name, expected in metadata['files'].items():
        entry = entries.get(expected['member'].casefold())
        if (not entry or entry.get('Path') != expected['member'] or entry.get('Size') != str(expected['size'])
                or entry.get('Folder', '-') != '-' or any('link' in key.lower() for key in entry)
                or 'D' in entry.get('Attributes', '') or 'l' in entry.get('Mode', '')):
            raise GraphicsError('selected archive member is absent, unsafe or has unexpected size')


def _directory_identity(path):
    _directory(path)
    info = path.stat()
    return info.st_dev, info.st_ino


@contextmanager
def stage(archive_path, directories, *, environment=None, extractor='7z', protected_roots=()):
    """Temporarily place only two verified DLLs beside owned test executables.

    Callers must finish all children before leaving this context. Cooperative
    exclusive ownership of the directories is required through cleanup.
    """
    metadata = lock()
    receipt = verify_archive(archive_path)
    archive_path = _directory(Path(archive_path).parent) / Path(archive_path).name
    archive_identity = _identity(archive_path)
    environment = child_environment(environment)
    roots = [_protected_root(value) for value in protected_roots]
    destinations = [_directory(value) for value in directories]
    if not destinations or len({str(value).casefold() for value in destinations}) != len(destinations):
        raise GraphicsError('unique existing staging directories are required')
    directory_ids = {}
    for destination in destinations:
        if any(destination == root or root in destination.parents or destination in root.parents for root in roots):
            raise GraphicsError('staging overlaps a protected SDK, dependency or install root')
        directory_ids[destination] = _directory_identity(destination)
        for name in SELECTED:
            if any(item.name.casefold() == name for item in destination.iterdir()):
                raise GraphicsError('driver destination already exists; nothing replaced')
    receipt.update({'driver': 'llvmpipe', 'files': [], 'cleanup': 'pending'})
    result = Staging(environment, receipt)
    owned = []
    try:
        listing = _command([extractor, 'l', '-slt', '-ba', '-sccUTF-8', str(archive_path)],
                           directory=destinations[0], environment=environment, limit=128 * 1024, timeout=30)
        _listing(listing, metadata)
        for name in SELECTED:
            item = metadata['files'][name]
            content = _command([extractor, 'x', '-so', '-spd', '-y', '-bso0', '-bsp0', '-bse2',
                                str(archive_path), item['member']], directory=destinations[0],
                               environment=environment, limit=item['size'], timeout=120)
            if len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                raise GraphicsError('selected driver bytes differ from pinned identity')
            if _identity(archive_path) != archive_identity:
                raise GraphicsError('retained archive changed during extraction')
            for directory in destinations:
                if _directory_identity(directory) != directory_ids[directory]:
                    raise GraphicsError('staging directory changed')
                fd, temporary_name = tempfile.mkstemp(prefix='.graphics-stage-', dir=directory)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(content)
                        output.flush()
                        os.fsync(output.fileno())
                    destination = directory / name
                    _publish(temporary, destination)
                    owned.append((destination, _identity(destination), item))
                    receipt['files'].append({'path': str(destination), 'size': item['size'],
                                             'sha256': item['sha256'], 'member': item['member']})
                finally:
                    temporary.unlink(missing_ok=True)
        verify_archive(archive_path)
        yield result
    except BaseException as error:
        if retain_required(error):
            result.mark_writers_uncertain()
        raise
    finally:
        failure = sys.exc_info()[1]
        preserved = []
        for path, identity, item in reversed(owned):
            if result.writers_uncertain:
                preserved.append(str(path))
                continue
            try:
                if _directory_identity(path.parent) != directory_ids[path.parent] or _identity(path) != identity:
                    raise GraphicsError('staged driver identity changed')
                _checked_file(path, item)
                path.unlink()
            except (OSError, GraphicsError):
                preserved.append(str(path))
        receipt['cleanup'] = ('retained-uncertain' if result.writers_uncertain else
                              'preserved-changed-files' if preserved else 'removed')
        if preserved:
            receipt['preserved_files'] = preserved
            error = GraphicsError('cleanup preserved uncertain, changed or inaccessible staged files; inspect owned output')
            error.graphics_receipt = receipt
            raise error from failure
        if failure is not None:
            failure.graphics_receipt = receipt


def run_probe(executable, *, environment, expected_directory):
    directory = _directory(expected_directory)
    executable = Path(os.path.abspath(executable))
    if executable.parent != directory:
        raise GraphicsError('probe executable must be beside the staged driver files')
    _identity(executable)
    metadata = lock()
    identities = {name: _checked_file(directory / name, metadata['files'][name]) for name in SELECTED}
    raw = _command([str(executable)], directory=directory, environment=child_environment(environment),
                   limit=65536, timeout=30)
    try:
        result = _json(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise GraphicsError('invalid native graphics probe receipt') from error
    if (not isinstance(result, dict) or result.get('schema_version') != 1 or result.get('status') != 'passed'
            or any(type(result.get(key)) is not int for key in ('major', 'minor'))
            or result.get('wgl_create_context_attribs_arb') is not True
            or result.get('wgl_choose_pixel_format_arb') is not True
            or result.get('gl_buffer_storage') is not True
            or type(result.get('arb_buffer_storage')) is not bool
            or not ((result['major'], result['minor']) >= (4, 4)
                    or ((result['major'], result['minor']) >= (4, 3) and result['arb_buffer_storage']))
            or any(not isinstance(result.get(key), str) or not result[key] or len(result[key]) > 4096
                   for key in ('version', 'vendor', 'renderer'))
            or 'llvmpipe' not in result['renderer'].lower() or result.get('error') != ''):
        raise GraphicsError('native driver capabilities did not satisfy the required profile')
    for name, field in (('opengl32.dll', 'opengl32_path'), ('libgallium_wgl.dll', 'libgallium_wgl_path')):
        path = result.get(field)
        if not isinstance(path, str) or not Path(path).is_absolute() or Path(path) != directory / name:
            raise GraphicsError('probe loaded a driver outside the staged directory')
        if _checked_file(directory / name, metadata['files'][name]) != identities[name]:
            raise GraphicsError('staged driver changed during native probe')
    return {'schema_version': 1, 'scope': 'host-qualification-only', 'probe': result,
            'archive_sha256': metadata['archive']['sha256'],
            'driver_files': {name: metadata['files'][name]['sha256'] for name in SELECTED}}


def compile_probe(probe_directory, compile_log, *, environment=None, protected_roots=(), strict_completion=False):
    """Compile the exact host probe with selected MSVC, without acquiring a driver.

    A fresh owned directory and log are required; supervisor completion, source
    stability and output identity checks are shared with graphics qualification.
    """
    environment = child_environment(environment)
    directory = _directory(probe_directory)
    protected = [_protected_root(root) for root in protected_roots]
    if any(directory == root or root in directory.parents or directory in root.parents for root in protected):
        raise GraphicsError('probe output overlaps a protected SDK, dependency or install root')
    compile_log = _directory(Path(compile_log).parent) / Path(compile_log).name
    executable, object_file = directory / 'windows-gl-probe.exe', directory / 'windows-gl-probe.obj'
    for target in (executable, object_file, compile_log):
        if any(path.name.casefold() == target.name.casefold() for path in target.parent.iterdir()):
            raise GraphicsError('probe output already exists; use a fresh owned directory')
    compiler = shutil.which('cl.exe', path=environment.get('PATH', environment.get('Path', '')))
    if compiler is None:
        raise GraphicsError('selected MSVC cl.exe is unavailable in the supplied environment')
    if type(strict_completion) is not bool:
        raise GraphicsError('strict compiler completion must be an explicit boolean')
    compiler_helper = None if strict_completion else _msvc_telemetry(compiler)
    source = Path(__file__).with_name('windows_gl_probe.cpp')
    before = source.read_bytes()
    _command([compiler, '/nologo', '/std:c++20', '/EHsc', str(source), '/Fo:' + str(object_file),
              '/Fe:' + str(executable), '/link', '/INCREMENTAL:NO', 'opengl32.lib', 'gdi32.lib', 'user32.lib'],
             directory=directory, environment=environment, limit=1024 * 1024, timeout=300, record=compile_log,
             compiler_helper=compiler_helper)
    if source.read_bytes() != before:
        raise GraphicsError('native probe source changed during compilation')
    _identity(executable)
    completion = (compiler_helper.receipt() if compiler_helper is not None else
                  {'policy': 'strict', 'outcome': 'no-surviving-descendants', 'stopped_pids': []})
    return executable, {'completion': completion, 'source_sha256': hashlib.sha256(before).hexdigest(),
                        'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                        'log_sha256': hashlib.sha256(compile_log.read_bytes()).hexdigest(),
                        'compiler': str(Path(compiler).absolute())}


@contextmanager
def _qualified_stage(archive_path, directories, *, probe_directory, compile_log,
                     environment=None, protected_roots=(), extractor='7z'):
    """Compile with the caller's selected MSVC, probe, then expose owned staging.

    Probe executable, object and bounded compiler log are retained as evidence;
    the two host DLLs are temporary. This requires a fresh owned probe directory.
    """
    environment = child_environment(environment)
    directory = _directory(probe_directory)
    protected = [_protected_root(root) for root in protected_roots]
    executable, compilation = compile_probe(directory, compile_log, environment=environment,
                                             protected_roots=protected)
    with stage(archive_path, [directory, *directories], environment=environment,
               extractor=extractor, protected_roots=protected) as staged:
        staged.receipt['compile'] = compilation
        staged.probe_receipt = run_probe(executable, environment=staged.environment, expected_directory=directory)
        staged.receipt['native_probe'] = staged.probe_receipt
        yield staged


@contextmanager
def qualified_stage(archive_path, directories, *, probe_directory, compile_log,
                    environment=None, protected_roots=(), extractor='7z'):
    """Expose shared native qualification and attach cleanup evidence on failure."""
    try:
        with _qualified_stage(archive_path, directories, probe_directory=probe_directory,
                              compile_log=compile_log, environment=environment,
                              protected_roots=protected_roots, extractor=extractor) as staged:
            yield staged
    except BaseException as error:
        if not hasattr(error, 'graphics_receipt'):
            error.graphics_receipt = {'schema_version': 1, 'scope': 'host-qualification-only',
                                      'files': [], 'native_probe': None,
                                      'cleanup': ('retained-uncertain' if retain_required(error)
                                                  else 'removed')}
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for name in ('verify', 'fetch'):
        item = sub.add_parser(name)
        item.add_argument('archive', type=Path)
        if name == 'fetch':
            item.add_argument('--network', action='store_true')
    args = parser.parse_args()
    try:
        result = fetch(args.archive, network=args.network) if args.operation == 'fetch' else verify_archive(args.archive)
        print(json.dumps(result, sort_keys=True))
    except (GraphicsError, OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
