#!/usr/bin/env python3
"""Bounded real-host editing and terminal restoration on a private POSIX PTY."""

import fcntl
import os
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time


def run(executable, stop_with_signal=False):
    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    flags = fcntl.fcntl(slave, fcntl.F_GETFL)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 31, 80, 0, 0))
    process = None
    raw = bytearray()
    try:
        process = subprocess.Popen([executable], stdin=slave, stdout=slave, stderr=slave,
                                   close_fds=True, start_new_session=True)

        def until(value):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    raw.extend(os.read(master, 65536))
                plain = re.sub(rb"\x1b\[[0-9;?]*[@-~]", b"", raw)
                if value in plain:
                    return
                if process.poll() is not None:
                    break
            raise AssertionError("Expected terminal text did not appear: " + repr(value))

        until(b"0 entries")
        until(b"Type an entry")
        if stop_with_signal:
            process.send_signal(signal.SIGTERM)
        else:
            os.write(master, b"PTY entry\r")
            until(b"1 entries")
            until(b"PTY entry")
            os.write(master, b"\x11")
        deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .05)[0]:
                raw.extend(os.read(master, 65536))
        if process.poll() != 0:
            raise AssertionError("Host did not exit successfully")
        if termios.tcgetattr(slave) != original or fcntl.fcntl(slave, fcntl.F_GETFL) != flags:
            raise AssertionError("Host did not restore terminal state")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: terminal_host_test.py EXECUTABLE")
    run(sys.argv[1])
    run(sys.argv[1], stop_with_signal=True)
    print("Real terminal editing, close, and interrupted restoration passed")
