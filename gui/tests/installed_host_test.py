#!/usr/bin/env python3
"""Bounded qualification of the actual deliverable executable, without test linkage."""
from pathlib import Path
import subprocess
import sys
import tempfile

executable = Path(sys.argv[1]).resolve(strict=True)
with tempfile.TemporaryDirectory(prefix='installed gui ') as directory:
    result = subprocess.run([str(executable), '--smoke-test'], cwd=directory,
                            capture_output=True, text=True, timeout=30)
    if result.returncode or result.stdout != 'software-foundation gui smoke: ok\n':
        raise RuntimeError('Installed GUI qualification failed: ' + result.stdout + result.stderr)
print('Installed GUI shared scenario, native presentation and closure passed')
