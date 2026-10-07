#!/usr/bin/env python3
"""Own explicitly selected MSVC build commands and their private compiler services.

Microsoft BuildXL sets _MSPDBSRV_ENDPOINT_ per invocation because a reused PDB
server can perform another invocation's I/O outside its process tree:
https://github.com/microsoft/BuildXL/blob/main/Public/Sdk/Experimental/Msvc/Native/Tools/Link/Link.dsc
This implementation keeps the server inside its no-breakaway Job and joins it.
The endpoint behavior must be qualified on the selected native MSVC toolset.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

import process_tree
import windows_toolchain

ENDPOINT = '_MSPDBSRV_ENDPOINT_'
HELPERS = ('vctip.exe', 'mspdbsrv.exe')


def _environment_value(environment, name):
    matches = [value for key, value in environment.items() if key.upper() == name.upper()]
    if len(matches) != 1 or not matches[0]:
        raise ValueError('one selected MSVC environment value required: ' + name)
    return matches[0]


def _snapshot(path):
    path = Path(path)
    before = os.stat(path, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
            getattr(before, 'st_file_attributes', 0) & 0x400):
        raise ValueError('MSVC toolkit input must be an ordinary singly linked file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if identity(os.stat(path, follow_symlinks=False)) != identity(before):
        raise ValueError('MSVC toolkit input changed while being identified')
    return identity(before), {'path': str(path), 'sha256': digest.hexdigest()}


def _select_toolkit(environment):
    directory = Path(_environment_value(environment, 'VCToolsInstallDir')) / 'bin/Hostx64/x64'
    directory = directory.resolve(strict=True)
    selected = {}
    for name in ('cl.exe', 'link.exe'):
        found = shutil.which(name, path=_environment_value(environment, 'PATH'))
        expected = directory / name
        if found is None or not Path(found).samefile(expected):
            raise ValueError('selected MSVC executable differs from its toolkit: ' + name)
        selected[name] = expected
    for name in HELPERS:
        path = directory / name
        if name == 'vctip.exe' and not path.exists():
            continue
        selected[name] = path
    for path in selected.values():
        _snapshot(path)
        windows_toolchain.pe_identity(path)
    return selected


class BuildSession:
    """A fresh endpoint belongs to this Job only, including for nested owners."""
    def __init__(self, environment):
        self.paths = _select_toolkit(environment)
        self.identities = {name: _snapshot(path) for name, path in self.paths.items()}
        self.endpoint = 'foundation-' + uuid.uuid4().hex
        self.environment = {key: value for key, value in environment.items() if key.upper() != ENDPOINT}
        self.environment[ENDPOINT] = self.endpoint
        self.observed = []
        self.completed = False

    def unchanged(self):
        if any(_snapshot(self.paths[name]) != identity for name, identity in self.identities.items()):
            raise ValueError('selected MSVC toolkit changed during its owned build')

    def validate(self, pid, image):
        # ProcessTree queried this image through its already pinned, verified Job
        # member handle. Canonical file identity also accepts Windows 8.3 aliases.
        self.unchanged()
        image = Path(image).resolve(strict=True)
        matches = [name for name in HELPERS if name in self.paths and image.samefile(self.paths[name])]
        if len(matches) != 1:
            raise process_tree.ProcessTreeError('unknown live MSVC build descendant: ' +
                                               json.dumps({'pid': pid, 'image': str(image)}))
        name = matches[0]
        self.observed.append(dict(self.identities[name][1], name=name, pid=pid))
        return True

    def finish(self, owner):
        if self.completed:
            raise ValueError('MSVC build session already completed')
        self.unchanged()
        # Every live member must pass validation before stopping; new assignments
        # and uncertain images fail closed. Generic finish still rejects writers.
        owner.terminate(validate_live=self.validate)
        self.unchanged()
        owner.finish()
        self.completed = True
        return self.receipt()

    def receipt(self):
        if not self.completed:
            raise ValueError('MSVC build session completion is unconfirmed')
        return {'policy': 'private-msvc-build-session', 'endpoint': self.endpoint,
                'toolkit': {name: item[1] for name, item in self.identities.items()},
                'outcome': 'verified-helpers-terminated-and-joined' if self.observed else 'no-surviving-helper',
                'helpers': list(self.observed)}



@contextmanager
def workspace(prefix):
    """Preserve consumer outputs when writer cleanup could not be confirmed."""
    directory = Path(tempfile.mkdtemp(prefix=prefix))
    safe = True
    try:
        yield directory
    except BaseException as error:
        pending, seen = [error], set()
        while pending:
            current = pending.pop()
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            if isinstance(current, process_tree.ProcessTreeError):
                safe = False
                break
            pending.extend((current.__cause__, current.__context__))
        raise
    finally:
        if safe:
            shutil.rmtree(directory)


def run(command, *, cwd=None, env=None, timeout=3600):
    """Run a compiler-capable region; other platforms retain subprocess semantics.

    This is explicit build ownership, not a generic successful-command exception.
    The caller keeps its output stream and work tree owned until this returns.
    Each invocation, even nested inside another owner, gets its own PDB endpoint.
    """
    if os.name != 'nt':
        return subprocess.run(command, cwd=cwd, env=env, check=True)
    session = BuildSession(dict(os.environ if env is None else env))
    owner = process_tree.launch(command, Path.cwd() if cwd is None else cwd, sys.stdout, env=session.environment)
    receipt = None
    try:
        code = owner.wait(timeout=timeout)
        if code == 0:
            receipt = session.finish(owner)
        else:
            owner.terminate()
            owner.finish()
            raise subprocess.CalledProcessError(code, command)
    finally:
        owner.close()
    print('MSVC_BUILD_COMPLETION ' + json.dumps(receipt, sort_keys=True), flush=True)
    return subprocess.CompletedProcess(command, code)
