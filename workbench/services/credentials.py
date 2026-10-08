"""Read private workbench provider keys without exposing them in public state.

Import is inert. Only an explicit ``load_saved_key`` call opens a key store.
The application config directory is trusted startup configuration, never a
provider setting or request field. Missing storage returns ``None``; unsafe or
malformed storage fails closed with a diagnostic containing no input or path.
"""

import errno
import os
from pathlib import Path
import stat
import sys


MAX_KEY_BYTES = 8192
PROVIDERS = frozenset(('openrouter', 'openai'))


class CredentialError(RuntimeError):
    """A fixed local diagnostic, without secret bytes or selected paths."""


def default_config_directory():
    """Match native AiPreferences defaults without inspecting the filesystem."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA')
        if base:
            return _absolute_base(base) / 'tinyEnv'
        return _absolute_base(os.environ.get('USERPROFILE')) / 'AppData' / 'Roaming' / 'tinyEnv'
    if sys.platform == 'darwin':
        return _absolute_base(os.environ.get('HOME')) / 'Library' / 'Application Support' / 'tinyEnv'
    xdg = os.environ.get('XDG_CONFIG_HOME')
    return (_absolute_base(xdg) if xdg else _absolute_base(os.environ.get('HOME')) / '.config') / 'tinyEnv'


def _absolute_base(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise CredentialError('Private provider configuration has no valid user location.')
    return Path(value)


def _directory_parts(config_directory):
    try:
        value = os.fspath(default_config_directory() if config_directory is None else config_directory)
        if not isinstance(value, str) or not value or '\0' in value:
            raise ValueError
        path = Path(value)
        raw_parts = value.split('/')
        if (not path.is_absolute() or not path.name or len(value.encode('utf-8')) > 4096
                or any(part in ('.', '..') for part in raw_parts)):
            raise ValueError
        parts = path.parts[1:]
        if any(not part or ':' in part or '\\' in part or len(part.encode('utf-8')) > 255
               for part in parts):
            raise ValueError
        return parts
    except (TypeError, ValueError, UnicodeError, OSError):
        raise CredentialError('Invalid private provider configuration location.') from None


def _qualified_posix():
    return (os.name == 'posix' and hasattr(os, 'geteuid')
            and all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_CLOEXEC', 'O_NONBLOCK'))
            and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
            and os.stat in os.supports_follow_symlinks)


def _directory_identity(info):
    return info.st_dev, info.st_ino


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)


def _check_directory(info, role):
    if not stat.S_ISDIR(info.st_mode):
        raise CredentialError('Unsafe private provider configuration.')
    if role in ('config', 'credentials'):
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid != os.geteuid() or mode & 0o022 or role == 'credentials' and mode != 0o700:
            raise CredentialError('Unsafe private provider configuration.')


def _check_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise CredentialError('Unsafe saved provider API key.')
    if not 2 <= info.st_size <= MAX_KEY_BYTES + 1:
        raise CredentialError('Malformed saved provider API key.')


def _verify_directories(opened):
    # Recheck every name against its pinned parent. An opened descriptor alone
    # would continue to name a directory after its visible subtree was replaced.
    for index, (descriptor, name, role) in enumerate(opened):
        info = os.fstat(descriptor)
        _check_directory(info, role)
        if index:
            current = os.stat(name, dir_fd=opened[index - 1][0], follow_symlinks=False)
            _check_directory(current, role)
            if _directory_identity(current) != _directory_identity(info):
                raise CredentialError('Private provider configuration changed during the read.')


def load_saved_key(provider, config_directory=None):
    """Return one safely read saved key, or ``None`` when its store is absent.

    The config directory itself must be owned by the current user and not
    writable by group/others. All path components refuse symlinks. The private
    ``credentials`` child is 0700; its single-link regular key file is 0600 and
    contains 1..8192 ASCII characters in 0x21..0x7e followed by exactly one LF.
    The qualified POSIX reader creates no files, directories or bytecode.
    """
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise CredentialError('Unsupported saved provider authentication.')
    if not _qualified_posix():
        # Native storage controls are unavailable on these hosts. Preserve the
        # existing environment-only provider path unless startup explicitly
        # selected a store whose protection cannot be established here.
        if config_directory is None:
            return None
        raise CredentialError('Private provider storage is unavailable on this host.')
    parts = _directory_parts(config_directory)
    opened = []
    key_descriptor = None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        root = os.open('/', directory_flags)
        opened.append((root, None, 'ancestor'))
        for index, name in enumerate(parts + ('credentials',)):
            role = ('credentials' if index == len(parts) else
                    'config' if index == len(parts) - 1 else 'ancestor')
            try:
                descriptor = os.open(name, directory_flags, dir_fd=opened[-1][0])
            except OSError as error:
                if error.errno == errno.ENOENT:
                    _verify_directories(opened)
                    return None
                raise
            opened.append((descriptor, name, role))
            _check_directory(os.fstat(descriptor), role)
        filename = provider + '.key'
        try:
            key_descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                     dir_fd=opened[-1][0])
        except OSError as error:
            if error.errno == errno.ENOENT:
                _verify_directories(opened)
                return None
            raise
        before = os.fstat(key_descriptor)
        _check_file(before)
        remaining = MAX_KEY_BYTES + 2
        chunks = []
        while remaining:
            chunk = os.read(key_descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        after = os.fstat(key_descriptor)
        _check_file(after)
        current = os.stat(filename, dir_fd=opened[-1][0], follow_symlinks=False)
        _check_file(current)
        if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(current):
            raise CredentialError('Saved provider API key changed during the read.')
        _verify_directories(opened)
        if (len(raw) != before.st_size or not 2 <= len(raw) <= MAX_KEY_BYTES + 1
                or raw[-1:] != b'\n' or any(byte < 0x21 or byte > 0x7e for byte in raw[:-1])):
            raise CredentialError('Malformed saved provider API key.')
        return raw[:-1].decode('ascii')
    except CredentialError:
        raise
    except (OSError, ValueError, OverflowError):
        raise CredentialError('Cannot read private provider authentication.') from None
    finally:
        if key_descriptor is not None:
            os.close(key_descriptor)
        for descriptor, _, _ in reversed(opened):
            os.close(descriptor)
