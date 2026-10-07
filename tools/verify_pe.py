#!/usr/bin/env python3
"""Inspect PE architecture and ordinary/delayed DLL closure without loading code."""
import argparse
from pathlib import Path
import struct
from dependency_archive import digest, write_json

MACHINES = {'x86_64': 0x8664, 'aarch64': 0xaa64}
SYSTEM_DLLS = {'kernel32.dll', 'kernelbase.dll', 'ntdll.dll', 'user32.dll', 'gdi32.dll',
              'advapi32.dll', 'shell32.dll', 'shlwapi.dll', 'ole32.dll', 'oleaut32.dll',
              'comdlg32.dll', 'comctl32.dll', 'ws2_32.dll', 'rpcrt4.dll', 'version.dll',
              'imm32.dll', 'dwmapi.dll', 'uxtheme.dll', 'setupapi.dll', 'winmm.dll',
              'normaliz.dll', 'msimg32.dll', 'opengl32.dll', 'glu32.dll'}


def inspect(path):
    data = Path(path).read_bytes()
    def unpack(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data): raise ValueError('truncated PE structure')
        return struct.unpack_from(fmt, data, offset)
    if len(data) < 64 or data[:2] != b'MZ': raise ValueError('not a PE file')
    pe, = unpack('<I', 60)
    if data[pe:pe + 4] != b'PE\0\0': raise ValueError('invalid PE signature')
    machine, count = unpack('<HH', pe + 4)
    optional_size, = unpack('<H', pe + 20)
    optional = pe + 24
    magic, = unpack('<H', optional)
    if magic != 0x20b or optional_size < 112: raise ValueError('expected 64-bit PE optional header')
    os_major, os_minor = unpack('<HH', optional + 40)
    subsystem_major, subsystem_minor = unpack('<HH', optional + 48)
    directory_count, = unpack('<I', optional + 108)
    if directory_count > 16 or optional_size < 112 + directory_count * 8: raise ValueError('invalid PE directory count')
    headers_size, = unpack('<I', optional + 60)
    sections = []
    for index in range(count):
        position = optional + optional_size + index * 40
        virtual_size, virtual_start, raw_size, raw_start = unpack('<IIII', position + 8)
        if raw_start + raw_size > len(data): raise ValueError('PE section exceeds file')
        sections.append((virtual_start, virtual_size, raw_start, raw_size))
    def offset(rva, length=1):
        matches = []
        if rva < headers_size and rva + length <= len(data): matches.append(rva)
        for start, size, raw, raw_size in sections:
            if start <= rva and rva + length <= start + min(max(size, raw_size), raw_size):
                matches.append(raw + rva - start)
        if len(matches) != 1: raise ValueError('unmapped or ambiguous PE address')
        return matches[0]
    def name(rva):
        start = offset(rva)
        end = data.find(b'\0', start, min(start + 260, len(data)))
        if end < 0: raise ValueError('unterminated PE dependency name')
        result = data[start:end].decode('ascii').lower()
        if not result.endswith('.dll') or any(c in result for c in '/\\:'):
            raise ValueError('invalid PE dependency filename')
        return result
    imports = set()
    for index, width in ((1, 20), (13, 32)):
        if index >= directory_count: continue
        rva, size = unpack('<II', optional + 112 + index * 8)
        if not rva and not size: continue
        if not rva or size < width: raise ValueError('invalid PE import directory')
        terminated = False
        for displacement in range(0, size - width + 1, width):
            values = unpack('<' + 'I' * (width // 4), offset(rva + displacement, width))
            if not any(values):
                terminated = True
                break
            if index == 13 and values[0] != 1: raise ValueError('unsupported delayed-import address mode')
            imports.add(name(values[3] if index == 1 else values[1]))
        if not terminated: raise ValueError('unterminated PE import directory')
    return {'sha256': digest(path), 'machine': machine, 'minimum_os': [os_major, os_minor], 'minimum_subsystem': [subsystem_major, subsystem_minor], 'imports': sorted(imports)}


def audit(root, processor='x86_64', static_crt=True):
    root = Path(root).resolve(strict=True)
    if processor not in MACHINES: raise ValueError('unsupported PE processor')
    paths = sorted(root.rglob('*')) if root.is_dir() else [root]
    files, providers = {}, {}
    for path in paths:
        if path.is_symlink(): raise ValueError('linked Windows package entry')
        if not path.is_file() or path.suffix.lower() not in ('.exe', '.dll'): continue
        data = inspect(path)
        if data['machine'] != MACHINES[processor]: raise ValueError('PE architecture mismatch')
        if data['minimum_os'] > [10, 0] or data['minimum_subsystem'] > [10, 0]: raise ValueError('PE minimum OS exceeds the declared Windows 10 baseline')
        key = path.name.lower()
        if key in providers: raise ValueError('ambiguous DLL/executable basename')
        providers[key] = path
        files[path.relative_to(root).as_posix() if root.is_dir() else path.name] = data
    if not files: raise ValueError('no PE files inspected')
    for relative_name, data in files.items():
        dependent = root / relative_name if root.is_dir() else root
        for name in data['imports']:
            runtime = name.startswith(('vcruntime', 'msvcp', 'api-ms-win-crt-')) or name in ('ucrtbase.dll', 'msvcr120.dll')
            if static_crt and runtime: raise ValueError('shared compiler runtime violates static CRT policy: ' + name)
            # Do not exempt arbitrary files merely because they were found in
            # System32. API-set extensions require an explicitly reviewed rule.
            if name in providers and providers[name].parent != dependent.parent:
                raise ValueError('private Windows DLL is not beside its dependent image: ' + name)
            if name not in providers and name not in SYSTEM_DLLS:
                raise ValueError('Windows package dependency closure is incomplete: ' + name)
    return {'schema_version': 1, 'status': 'passed', 'processor': processor, 'static_crt': static_crt, 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--processor', choices=tuple(MACHINES), default='x86_64')
    parser.add_argument('--shared-crt', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): args.output.unlink()
    write_json(args.output, audit(args.root, args.processor, not args.shared_crt))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, UnicodeError, struct.error) as error: raise SystemExit(str(error))
