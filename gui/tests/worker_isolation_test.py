#!/usr/bin/env python3
"""Real isolated hosted worker, capability pipe and ordinary browser negative control."""
import importlib.util
import json
from pathlib import Path
import subprocess
import socket
import sys
import tempfile

executable, host_path = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('foundation_host_fixture', host_path)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
with tempfile.TemporaryDirectory(prefix='foundation-worker-') as temporary:
    path = Path(temporary) / 'selected.txt'
    path.write_text('first\nsecond\n')
    session = host.Session(executable, native_files=True)
    sequence = 0
    def send(operation):
        global sequence
        sequence += 1
        result = json.loads(session.exchange(json.dumps({'epoch': session.epoch, 'seq': str(sequence), 'operation': operation}).encode()))
        assert not result['error'], result['error']
        return result
    def menu(option):
        return send({'type': 'choose', 'key': {'id': 'entries.options', 'generation': '1'}, 'id': option})
    def rows(state):
        return next(widget['records'] for widget in state['snapshot']['widgets'] if widget['key']['id'] == 'entries.list')
    try:
        state = menu('import'); identity = state['service']['id']
        # Browser control bytes cannot acquire native path authority, even with
        # a current service ID and a real readable path.
        state = send({'type': 'filePath', 'id': identity, 'path': str(path)})
        assert state['service']['id'] == identity and rows(state) == []
        state = json.loads(session.complete_file(identity, path))
        assert not state['error'] and len(rows(state)) == 2
        state = menu('export'); identity = state['service']['id']
        output = Path(temporary) / 'export.txt'
        state = json.loads(session.complete_file(identity, output))
        assert output.read_bytes() == b'first\nsecond\n' and state['service'] is None
        state = menu('import'); identity = state['service']['id']
        send({'type': 'fileBegin', 'id': identity, 'total': '5'})
        send({'type': 'fileChunk', 'id': identity, 'offset': '0', 'hex': b'third'.hex()})
        state = send({'type': 'fileFinish', 'id': identity})
        assert [record['text'] for record in rows(state)] == ['third']
        send({'type': 'close'})
    finally:
        session.close()
    assert session.process.poll() is not None and not session.worker.is_alive()
# A normal stdin device cannot stand in for verified anonymous pipes.
rejected = subprocess.run([str(executable), '--isolated'], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
assert rejected.returncode != 0 and b'anonymous pipes' in rejected.stderr
# Retained stderr must be rejected and closed before an exception handler can
# accidentally write the diagnostic through an inherited network/IPC socket.
left, right = socket.socketpair()
try:
    process = subprocess.Popen([str(executable), '--isolated'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=right, close_fds=True)
    right.close()
    output, _ = process.communicate(timeout=5)
    assert process.returncode != 0 and output == b''
    left.settimeout(2)
    assert left.recv(256) == b'', 'Startup diagnostic escaped through socket stderr'
finally:
    left.close()
    right.close()
print('Isolated actual worker: native import/export only through trusted pipe; browser chunks and pathname denial; joined shutdown passed')
