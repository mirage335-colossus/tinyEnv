"""Explicit local whisper.cpp transcription with owned, bounded Linux processes.

There are no downloads, provider calls, shell evaluation, or executable discovery.
Linux x86_64 and aarch64 use seccomp network denial and the project's qualified
descendant supervisor. Other hosts fail closed until equivalent native policy is
qualified. The selected executable must be an already trusted local whisper-cli.
"""

import ctypes
from dataclasses import dataclass
import errno
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time


class TranscriptionError(ValueError):
    """A safe local diagnostic, never external executable output."""


def _number(value, name, low, high, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or not low <= value <= high or
            integer and not isinstance(value, int)):
        raise TranscriptionError(name + ' is outside its supported bounds.')
    return value


def _path(value, name, *, executable=False, maximum=None):
    try:
        path = Path(value)
        if not path.is_absolute() or '\x00' in str(path):
            raise TranscriptionError(name + ' must be an explicit absolute local path.')
        str(path).encode('utf-8')
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise TranscriptionError(name + ' cannot contain symbolic links.')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise TranscriptionError(name + ' must be an existing regular file.')
        if maximum is not None and not 0 < info.st_size <= maximum:
            raise TranscriptionError(name + ' exceeds its supported byte limit or is empty.')
        if executable and not os.access(path, os.X_OK):
            raise TranscriptionError('Selected whisper-cli is not executable.')
        return path, info
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        if isinstance(error, TranscriptionError):
            raise
        raise TranscriptionError(name + ' is unavailable or invalid.') from None


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class TranscriptionConfig:
    executable: str
    model_path: str
    timeout_seconds: float = 120
    threads: int = 2
    max_output_bytes: int = 1048576
    max_media_bytes: int = 67108864
    max_model_bytes: int = 4294967296
    max_memory_bytes: int = 4294967296
    max_cpu_seconds: int = 120

    def __post_init__(self):
        _number(self.timeout_seconds, 'Timeout seconds', .05, 600)
        for name, low, high in (('threads', 1, 32), ('max_output_bytes', 1, 4194304),
                                ('max_media_bytes', 1, 536870912), ('max_model_bytes', 1, 8589934592),
                                ('max_memory_bytes', 67108864, 34359738368), ('max_cpu_seconds', 1, 19200)):
            _number(getattr(self, name), name, low, high, integer=True)
        _path(self.executable, 'Whisper executable', executable=True)
        _path(self.model_path, 'Local model', maximum=self.max_model_bytes)

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise TranscriptionError('Transcription settings must contain only supported local options.')
        try:
            return cls(**values)
        except TypeError:
            raise TranscriptionError('Select an absolute whisper-cli executable and local model file.') from None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    metadata: dict

    def to_dict(self):
        return {'text': self.text, 'metadata': dict(self.metadata)}


def _supervisor():
    adjacent = Path(__file__).resolve().parent / '_process_tree.py'
    source = Path(__file__).resolve().parents[2] / 'tools' / 'process_tree.py'
    selected = adjacent if adjacent.is_file() else source
    if not selected.is_file() or selected.is_symlink():
        raise TranscriptionError('The qualified local process supervisor is unavailable.')
    specification = importlib.util.spec_from_file_location('_tinyenv_transcription_process_tree', selected)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _platform():
    if os.name != 'posix' or not sys.platform.startswith('linux') or platform.machine().lower() not in ('x86_64', 'amd64', 'aarch64', 'arm64'):
        raise TranscriptionError('Local transcription currently requires Linux x86_64 or aarch64.')


def _sandbox(config):
    """Set Linux resource and syscall limits in a dedicated interpreter only."""
    _platform()
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (config['max_memory_bytes'], config['max_memory_bytes']))
    resource.setrlimit(resource.RLIMIT_CPU, (config['max_cpu_seconds'], config['max_cpu_seconds']))
    resource.setrlimit(resource.RLIMIT_FSIZE, (config['max_output_bytes'], config['max_output_bytes']))
    # No inherited sockets exist. Refuse socket creation and io_uring (which can
    # otherwise create sockets without the socket syscall); exec retains filters.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]
    x86 = platform.machine().lower() in ('x86_64', 'amd64')
    architecture = 0xc000003e if x86 else 0xc00000b7
    denied = (41, 53, 425) if x86 else (198, 199, 425)
    instructions = [Filter(0x20, 0, 0, 4), Filter(0x15, 1, 0, architecture), Filter(0x06, 0, 0, 0x80000000),
                    Filter(0x20, 0, 0, 0), Filter(0x35, 0, 1, 0x40000000), Filter(0x06, 0, 0, 0x80000000)]
    for number in denied:
        instructions.extend((Filter(0x15, 0, 1, number), Filter(0x06, 0, 0, 0x00050000 | errno.EPERM)))
    instructions.append(Filter(0x06, 0, 0, 0x7fff0000))
    array = (Filter * len(instructions))(*instructions)
    program = Program(len(instructions), array)
    api = ctypes.CDLL(None, use_errno=True)
    api.prctl.restype = ctypes.c_int
    if api.prctl(38, 1, 0, 0, 0) != 0 or api.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise TranscriptionError('Required local network confinement could not be enabled.')


def _sandbox_main(argv):
    """Private supervised child: validates limits, installs them, then execs."""
    try:
        values = json.loads(argv[0])
        config = TranscriptionConfig.from_dict(values['config'])
        _sandbox({name: getattr(config, name) for name in config.__dataclass_fields__})
        command = values['command']
        os.execve(command[0], command, os.environ)
    except BaseException:
        os.write(2, b'Local transcription sandbox or executable failed.\n')
        return 125


def _read_transcript(path, limit):
    _path(path, 'Generated transcript', maximum=limit)
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise TranscriptionError('Generated transcript must be a regular file.')
        raw = source.read(limit + 1)
        if len(raw) > limit or _identity(before) != _identity(os.fstat(source.fileno())):
            raise TranscriptionError('Generated transcript changed or exceeded its byte limit.')
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise TranscriptionError('Local transcript must contain UTF-8 text.') from None
    if not text.strip() or '\x00' in text:
        raise TranscriptionError('Local transcription produced no valid text.')
    return text, raw


def transcribe(media_path, config, *, temporary_parent=None):
    """Transcribe one explicit WAV using a trusted executable and local model."""
    _platform()
    if not isinstance(config, TranscriptionConfig):
        raise TranscriptionError('A validated local transcription configuration is required.')
    executable, executable_info = _path(config.executable, 'Whisper executable', executable=True)
    model, model_info = _path(config.model_path, 'Local model', maximum=config.max_model_bytes)
    media, media_info = _path(media_path, 'Media input', maximum=config.max_media_bytes)
    if media.suffix.lower() != '.wav':
        raise TranscriptionError('Select a WAV audio file; media conversion is an explicit separate local step.')
    if media == model or media == executable or model == executable:
        raise TranscriptionError('Executable, model, and media must be separate files.')
    if temporary_parent is not None:
        try:
            temporary_parent = Path(temporary_parent)
            if not temporary_parent.is_absolute():
                raise TranscriptionError('Local scratch directory must be absolute.')
            current = Path(temporary_parent.anchor)
            for part in temporary_parent.parts[1:]:
                current = current / part
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise TranscriptionError('Local scratch directory cannot contain symbolic links.')
            info = temporary_parent.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise TranscriptionError('Local scratch directory must be an existing owner-only directory.')
        except (OSError, TypeError, ValueError) as error:
            if isinstance(error, TranscriptionError):
                raise
            raise TranscriptionError('Local scratch directory is unavailable.') from None
    owner = _supervisor()
    directory = Path(tempfile.mkdtemp(prefix='tinyenv-transcription-', dir=temporary_parent))
    directory.chmod(0o700)
    log_path, prefix = directory / 'process.log', directory / 'transcript'
    command = [str(executable), '-m', str(model), '-f', str(media), '-t', str(config.threads),
               '-otxt', '-of', str(prefix), '-np', '-ng']
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'HOME': str(directory), 'TMPDIR': str(directory), 'TEMP': str(directory), 'TMP': str(directory),
                   'XDG_CONFIG_HOME': str(directory), 'XDG_CACHE_HOME': str(directory),
                   'OMP_NUM_THREADS': str(config.threads), 'OPENBLAS_NUM_THREADS': str(config.threads)}
    values = {'config': {name: str(getattr(config, name)) if name in ('executable', 'model_path') else getattr(config, name)
                         for name in config.__dataclass_fields__}, 'command': command}
    wrapper = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--sandbox-whisper', json.dumps(values)]
    tree, joined = None, True
    started = time.monotonic()
    result = None
    try:
        with log_path.open('xb') as log:
            tree = owner.launch(wrapper, directory, log, env=environment)
            joined = False
            try:
                code = tree.wait(timeout=config.timeout_seconds)
            except subprocess.TimeoutExpired:
                tree.terminate(timeout=5)
                joined = True
                raise TranscriptionError('Local transcription timed out; its process tree was stopped and joined.') from None
            tree.finish()
            joined = True
            if log_path.stat().st_size >= config.max_output_bytes:
                raise TranscriptionError('Local transcription diagnostic output exceeded its byte limit.')
            if code != 0:
                raise TranscriptionError('Local whisper-cli failed; check the executable, model, and WAV format.')
        for path, original in ((executable, executable_info), (model, model_info), (media, media_info)):
            if _identity(path.stat()) != _identity(original):
                raise TranscriptionError('A selected input changed during transcription.')
        text, raw = _read_transcript(prefix.with_suffix('.txt'), config.max_output_bytes)
        result = TranscriptionResult(text, {'engine': 'whisper.cpp', 'local_only': True, 'network_enabled': False,
                    'media_path': str(media), 'model_path': str(model), 'executable': str(executable),
                    'media_bytes': media_info.st_size, 'model_bytes': model_info.st_size,
                    'threads': config.threads, 'exit_code': code, 'transcript_bytes': len(raw),
                    'transcript_sha256': hashlib.sha256(raw).hexdigest(),
                    'subprocess_joined': True, 'temporary_files_removed': True,
                    'elapsed_seconds': round(time.monotonic() - started, 3)})
    except TranscriptionError:
        raise
    except Exception:
        raise TranscriptionError('Local transcription failed; no external service or fallback was used.') from None
    finally:
        if tree is not None:
            try:
                tree.close()
                joined = True
            except Exception:
                joined = False
        if joined:
            shutil.rmtree(directory)
        else:
            raise TranscriptionError('Local process cleanup remains uncertain; private temporary files were retained.')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--sandbox-whisper':
        raise SystemExit('Private local transcription wrapper requires its complete invocation.')
    raise SystemExit(_sandbox_main(sys.argv[2:]))
