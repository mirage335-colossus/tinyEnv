#!/usr/bin/env python3
"""Portable bounded subprocess transport for the verified loopback browser host.

The colocated host.py and browser assets are copied from pinned sources by CMake.
One worker owns each pair of pipes; Windows pipes need no select() support.
"""
import importlib.util
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time

_spec = importlib.util.spec_from_file_location('boundary_host', Path(__file__).with_name('host.py'))
boundary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boundary)


class Session:
    timeout = 15

    def __init__(self, executable, *, native_files=False, isolated=None):
        self.epoch = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.used = time.monotonic()
        self.closed = threading.Event()
        self.requests, self.responses = queue.Queue(1), queue.Queue(1)
        # Only an embedding's trusted code receives complete_file(). HTTP
        # request handlers never receive the descriptor or a pathname operation.
        if isolated is None:
            isolated = os.environ.get('FOUNDATION_WEB_ISOLATE') == '1'
        if native_files:
            isolated = True
        if isolated and not sys.platform.startswith('linux'):
            raise RuntimeError('Worker isolation is qualified only on Linux')
        self.file_pipe = None
        read_pipe = None
        command = [str(executable), self.epoch]
        if isolated:
            command.append('--isolated')
        options = {}
        if native_files:
            read_pipe, self.file_pipe = os.pipe()
            command += ['--file-events-fd', str(read_pipe)]
            options['pass_fds'] = (read_pipe,)
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            close_fds=True, bufsize=0, **options)
        except BaseException:
            if self.file_pipe is not None:
                os.close(self.file_pipe)
            raise
        finally:
            if read_pipe is not None:
                os.close(read_pipe)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        try:
            self.state = self._response()
        except Exception:
            self.close()
            raise

    def _work(self):
        pending = bytearray()
        try:
            while not self.closed.is_set():
                while b'\n' not in pending:
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError('Backend exited')
                    pending.extend(chunk)
                    if len(pending) > boundary.MAX_OUTPUT:
                        raise ValueError('Backend response exceeds output limit')
                line, _, pending = pending.partition(b'\n')
                json.loads(line)
                self.responses.put_nowait(bytes(line))
                payload = self.requests.get()
                if payload is None:
                    return
                payload, trusted = payload
                payload = memoryview(payload + b'\n')
                while payload and not self.closed.is_set():
                    written = os.write(self.file_pipe, payload) if trusted else self.process.stdin.write(payload)
                    if not written:
                        raise RuntimeError('Backend input pipe closed')
                    payload = payload[written:]
        except Exception as error:
            try:
                self.responses.put_nowait(error)
            except queue.Full:
                pass

    def _response(self):
        try:
            result = self.responses.get(timeout=self.timeout)
        except queue.Empty as error:
            raise TimeoutError('Backend response timed out') from error
        if isinstance(result, Exception):
            raise RuntimeError(str(result)) from result
        return result

    def exchange(self, data):
        return self._exchange(data, False)

    def complete_file(self, service_id, path):
        """Trusted native chooser completion; never call with an HTTP pathname."""
        if self.file_pipe is None:
            raise RuntimeError('Native file capability was not granted')
        data = json.dumps({'id': str(service_id), 'path': os.fspath(path)}, ensure_ascii=False).encode('utf-8')
        return self._exchange(data, True)

    def _exchange(self, data, trusted):
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError('Session closed')
            if len(data) > boundary.MAX_INPUT:
                raise ValueError('Message exceeds input limit')
            self.used = time.monotonic()
            try:
                self.requests.put_nowait((data, trusted))
                self.state = self._response()
                return self.state
            except Exception:
                self.close()
                raise

    def close(self):
        with self.close_lock:
            if self.closed.is_set():
                return
            self.closed.set()
            try:
                self.requests.put_nowait(None)
            except queue.Full:
                pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.worker.join(timeout=2)
            self.process.stdin.close()
            self.process.stdout.close()
            if self.file_pipe is not None:
                os.close(self.file_pipe)
                self.file_pipe = None
            if self.worker.is_alive():
                raise RuntimeError('Backend worker did not stop')


boundary.Session = Session
if __name__ == '__main__':
    boundary.main()
