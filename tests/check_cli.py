#!/usr/bin/env python3
import os
import subprocess
import sys

command = sys.argv[1:]
if not command:
    raise ValueError("provide an executable, optionally preceded by its target runtime")


def check(args, code, stdout=None):
    result = subprocess.run([*command, *args], capture_output=True)
    if result.returncode != code or (stdout is not None and result.stdout.replace(b"\r\n", b"\n") != stdout.encode("utf-8")):
        raise RuntimeError(f"CLI contract failed: {args!r}: {result}")


check(["--version"], 0, "software-foundation 0.1.0\n")
check(["--self-check"], 0, "")
check(["--", "Alpha", "Beta"], 0, "1\tAlpha\n2\tBeta\n")
check(["--", "Valid", "bad\ntext"], 1, "")
check(["--unknown"], 2, "")
check(["--"], 2, "")

# Capture bytes so a developer's Python/console code page cannot hide corruption.
# The ASCII application must reject Unicode atomically, rather than accepting
# replacement question marks from lossy Windows narrow argv conversion.
unicode_text = "caf\u00e9 \u65e5\u672c\u8a9e \U0001f30d \"quoted\" \\path"
check(["--", "Valid", unicode_text], 1, "")
check(["--", "\u65e5\u672c\u8a9e \U0001f30d"], 1, "")
if os.name == "nt":
    check(["--", "invalid\ud800"], 1, "")
elif len(command) == 1:
    # Native POSIX argv remains a byte interface; non-ASCII bytes are rejected.
    raw = subprocess.run([os.fsencode(command[0]), b"--", b"raw-\xff"], capture_output=True)
    if raw.returncode != 1 or raw.stdout != b"":
        raise RuntimeError("POSIX non-ASCII argument was accepted or emitted partial output")


# Exercise actual write failure on hosts providing the standard full device.
from pathlib import Path
if Path("/dev/full").exists():
    for args in (["--version"], ["--help"], ["--", "Entry"]):
        with open("/dev/full", "wb") as destination:
            result = subprocess.run([*command, *args], stdout=destination, stderr=subprocess.PIPE)
        if result.returncode != 1:
            raise RuntimeError("CLI reported success after output failure")
