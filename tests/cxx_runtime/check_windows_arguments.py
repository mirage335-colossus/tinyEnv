#!/usr/bin/env python3
"""Native Windows wide-argument conversion using the production helper."""
import os
import subprocess
import sys

if os.name != 'nt':
    raise RuntimeError('Windows argument fixture requires native Windows execution')
command = sys.argv[1:]
if len(command) != 1:
    raise ValueError('provide the native Windows argument fixture executable')
values = ['ASCII', '', 'caf\u00e9 \u65e5\u672c\u8a9e \U0001f30d "quoted" \\path']
result = subprocess.run([*command, *values], capture_output=True)
expected = ''.join(value + '\r\n' for value in values).encode('utf-8')
if result.returncode != 0 or result.stdout != expected:
    raise RuntimeError(f'Windows wide arguments did not preserve exact UTF-8 bytes: {result!r}')
for invalid in ('\ud800', '\udfff', 'prefix\ud800suffix'):
    result = subprocess.run([*command, 'valid', invalid], capture_output=True)
    if result.returncode != 1 or result.stdout:
        raise RuntimeError('Malformed UTF-16 produced successful or partial output')
print('Native Windows UTF-16 arguments, redirected UTF-8 bytes and invalid surrogate rejection passed')
