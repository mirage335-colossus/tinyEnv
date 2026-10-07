#!/usr/bin/env python3
"""Inspect the selected native Microsoft linker without executing a help command."""
import ctypes
import hashlib
import os
from pathlib import Path
import platform
import shutil
import struct


def pe_identity(path):
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('selected linker is not a PE executable')
        offset = struct.unpack_from('<I', header, 60)[0]
        if not 64 <= offset <= 1024 * 1024:
            raise ValueError('selected linker has an invalid PE header offset')
        stream.seek(offset); header = stream.read(26)
    if (len(header) != 26 or header[:4] != b'PE\0\0'
            or struct.unpack_from('<H', header, 4)[0] != 0x8664
            or struct.unpack_from('<H', header, 24)[0] != 0x20b
            or not struct.unpack_from('<H', header, 22)[0] & 2
            or struct.unpack_from('<H', header, 22)[0] & 0x2000):
        raise ValueError('selected linker must be a native x64 PE executable')


def file_version(path):
    # Win32 fixed file version matches the selector's FileVersionInfo semantics.
    # https://learn.microsoft.com/windows/win32/api/winver/nf-winver-verqueryvaluew
    if platform.system() != 'Windows':
        raise ValueError('native Windows version-resource inspection is required')
    from ctypes import wintypes
    api = ctypes.WinDLL('version.dll', use_last_error=True, winmode=0x800)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype = wintypes.BOOL
    handle = wintypes.DWORD()
    size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not 0 < size <= 8 * 1024 * 1024:
        raise ValueError('selected linker version resource is missing or oversized')
    block = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, block):
        raise OSError(ctypes.get_last_error(), 'cannot read selected linker version resource')

    def query(name, text=False):
        address = ctypes.c_void_p(); count = wintypes.UINT()
        if not api.VerQueryValueW(block, name, ctypes.byref(address), ctypes.byref(count)):
            raise ValueError('missing selected linker version field: ' + name)
        length = count.value * (2 if text else 1)
        start = ctypes.addressof(block)
        if not address.value or length < 1 or address.value < start or address.value + length > start + size:
            raise ValueError('selected linker version field exceeds its resource')
        value = ctypes.string_at(address, length)
        if not text:
            return value
        value = value.decode('utf-16-le')
        if not value.endswith('\0') or '\0' in value[:-1]:
            raise ValueError('malformed selected linker version text')
        return value[:-1]

    fixed = query('\\')
    if len(fixed) != 52:
        raise ValueError('malformed fixed linker version resource')
    fields = struct.unpack('<13I', fixed)
    if fields[0] != 0xfeef04bd or fields[9] != 1:
        raise ValueError('invalid application version resource')
    ms, ls = fields[2:4]
    version = '.'.join(str(value) for value in (ms >> 16, ms & 65535, ls >> 16, ls & 65535))
    translations = query('\\VarFileInfo\\Translation')
    if len(translations) % 4 or len(translations) > 1024:
        raise ValueError('invalid linker version translations')
    identities = []
    for language, codepage in struct.iter_unpack('<HH', translations):
        prefix = '\\StringFileInfo\\%04x%04x\\' % (language, codepage)
        identities.append({'company': query(prefix + 'CompanyName', True),
                           'original_filename': query(prefix + 'OriginalFilename', True)})
    if not identities:
        raise ValueError('missing linker version identity')
    return {'version': version, 'identities': identities}


def inspect_selected_linker():
    """Bind the selected toolset path, x64 PE identity and unchanged file version."""
    if platform.system() != 'Windows':
        raise ValueError('selected linker inspection requires native Windows')
    directory = os.environ.get('VCToolsInstallDir')
    found = shutil.which('link.exe')
    if not directory or not found:
        raise ValueError('select the supported Windows developer environment first')
    expected = Path(directory) / 'bin/Hostx64/x64/link.exe'
    path = Path(found).resolve(strict=True)
    if not expected.is_file() or not path.samefile(expected):
        raise ValueError('PATH linker differs from the selected Windows toolset')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    pe_identity(path)
    info = file_version(path)
    parts = info['version'].split('.')
    if len(parts) != 4 or any(not x.isdecimal() for x in parts) or not (int(parts[0]) == 14 and 30 <= int(parts[1]) <= 49):
        raise ValueError('selected linker is not a supported v143 version')
    if not info['identities'] or any(item.get('company', '').casefold() != 'microsoft corporation'
            or item.get('original_filename', '').casefold() != 'link.exe' for item in info['identities']):
        raise ValueError('selected PE version identity is not the Microsoft linker')
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError('selected linker changed during version inspection')
    return {'path': str(path), 'sha256': before, 'version': info['version'], 'architecture': 'x86_64'}
