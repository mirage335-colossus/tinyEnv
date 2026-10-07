#!/usr/bin/env python3
"""Real child-process failures must have bounded deadlines and release pipes."""
import importlib.util
import sys
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('server',sys.argv[1]);server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
original=server.subprocess.Popen
server.Session.timeout=.3

def launch(code):
    return patch.object(server.subprocess,'Popen',lambda command,**kwargs:original([sys.executable,'-u','-c',code],**kwargs))

for code in ('print("invalid JSON")','import time;time.sleep(10)','print("x"*256)'):
    previous=server.boundary.MAX_OUTPUT;server.boundary.MAX_OUTPUT=128
    try:
        with launch(code):
            try:server.Session('ignored')
            except (RuntimeError,TimeoutError):pass
            else:raise AssertionError('Invalid startup response accepted')
    finally:server.boundary.MAX_OUTPUT=previous
with launch('import time;print("{}");time.sleep(10)'):
    session=server.Session('ignored')
    try:
        try:session.exchange(b'x'*server.boundary.MAX_INPUT)
        except (RuntimeError,TimeoutError):pass
        else:raise AssertionError('Blocked pipe did not time out')
        assert session.process.poll() is not None and not session.worker.is_alive()
        assert session.process.stdin.closed and session.process.stdout.closed
    finally:session.close()
print('Malformed, oversized, unresponsive and blocked child cleanup passed')
