"""Local-only transcription fixtures; no model downloads or network calls."""

from contextlib import redirect_stdout
import io
import json
import math
import os
from pathlib import Path
import signal
import socket
import tempfile
import textwrap
import time
import unittest
from unittest import mock
import wave

from workbench.services import transcription
from workbench.services.transcription import TranscriptionConfig, TranscriptionError, transcribe


_network_guards = []


def _deny_network(*args, **kwargs):
    raise AssertionError("transcription tests must not use the network")


def setUpModule():
    for name in ("create_connection", "getaddrinfo"):
        guard = mock.patch.object(socket, name, side_effect=_deny_network)
        guard.start()
        _network_guards.append(guard)
    for name in ("connect", "connect_ex", "sendto"):
        guard = mock.patch.object(socket.socket, name, side_effect=_deny_network)
        guard.start()
        _network_guards.append(guard)


def tearDownModule():
    while _network_guards:
        _network_guards.pop().stop()


def process_identity(pid):
    try:
        fields = Path("/proc", str(pid), "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return {"state": fields[0], "start": fields[19]}


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tinyenv-transcription-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.executable = self.directory / "recognizer $(literal); tool"
        self.model = self.directory / "model $(literal); file.bin"
        self.media = self.directory / "voice $(literal); sample.wav"
        self.model.write_bytes(b"ggml" + b"\x00" * 128)
        with wave.open(str(self.media), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 160)
        self.original_model = self.model.read_bytes()
        self.original_media = self.media.read_bytes()
        self.script("output.write_text('Recognized café\\n', encoding='utf-8')")

    def script(self, body):
        self.executable.write_text(
            "#!/usr/bin/python3\n"
            "import json, os, resource, signal, sys, time\n"
            "from pathlib import Path\n"
            "prefix = sys.argv[sys.argv.index('-of') + 1]\n"
            "output = Path(prefix + '.txt')\n" + textwrap.dedent(body) + "\n", encoding="utf-8")
        self.executable.chmod(0o755)

    def config(self, **changes):
        values = {"executable": str(self.executable), "model_path": str(self.model)}
        values.update(changes)
        return TranscriptionConfig(**values)

    def assert_sources_unchanged(self):
        self.assertEqual(self.model.read_bytes(), self.original_model)
        self.assertEqual(self.media.read_bytes(), self.original_media)

    def assert_preflight_error(self, media=None, **changes):
        with mock.patch.object(transcription, "_supervisor") as launch:
            with self.assertRaises(TranscriptionError):
                transcribe(str(self.media if media is None else media), self.config(**changes))
        launch.assert_not_called()

    def test_success_returns_serializable_local_result_and_preserves_sources(self):
        result = transcribe(str(self.media), self.config())
        self.assertEqual(result.text.strip(), "Recognized café")
        self.assertIsInstance(result.metadata, dict)
        data = result.to_dict()
        self.assertEqual(data["text"], result.text)
        self.assertEqual(data["metadata"], result.metadata)
        self.assertEqual(result.metadata["engine"], "whisper.cpp")
        self.assertIs(result.metadata["local_only"], True)
        self.assertIs(result.metadata["network_enabled"], False)
        self.assertIs(result.metadata["subprocess_joined"], True)
        self.assertIs(result.metadata["temporary_files_removed"], True)
        json.dumps(data, allow_nan=False)
        self.assert_sources_unchanged()

    def test_runtime_bridge_returns_local_sources_without_provider_or_research(self):
        from workbench.services.runtime import execute_request

        request = {"schema_version": 1, "operation": "transcribe", "root": str(self.directory),
                   "media_path": str(self.media),
                   "transcription": {"executable": str(self.executable), "model_path": str(self.model)}}
        provider = mock.Mock(side_effect=AssertionError("local transcription reached a provider"))
        research = mock.Mock(side_effect=AssertionError("local transcription reached research"))
        response = execute_request(request, provider_factory=provider, research_factory=research)
        self.assertIs(response["ok"], True, response["error"])
        self.assertEqual(response["text"].strip(), "Recognized café")
        self.assertEqual(response["usage"]["model_calls"], 0)
        self.assertEqual(response["sources"][0]["kind"], "local-media")
        self.assertEqual(response["sources"][0]["path"], str(self.media))
        self.assertIs(response["sources"][0]["metadata"]["untrusted"], True)
        self.assertIs(response["sources"][0]["metadata"]["instruction_authority"], False)
        self.assertEqual(response["provenance"][0]["provider"], "local")
        self.assertIs(response["provenance"][0]["local_only"], True)
        self.assertIn("local_transcription", [event["kind"] for event in response["events"]])
        provider.assert_not_called()
        research.assert_not_called()
        json.dumps(response, allow_nan=False)
        self.assert_sources_unchanged()

    def test_literal_arguments_private_output_and_environment_allowlist(self):
        self.script("""
            payload = {'argv': sys.argv, 'environment': dict(os.environ),
                       'cwd': os.getcwd(), 'prefix': prefix}
            output.write_text(json.dumps(payload), encoding='utf-8')
        """)
        hostile = {"OPENAI_API_KEY": "DO_NOT_PROPAGATE_OPENAI", "OPENROUTER_API_KEY": "DO_NOT_PROPAGATE_ROUTER",
                   "AWS_SECRET_ACCESS_KEY": "DO_NOT_PROPAGATE_AWS", "PYTHONPATH": str(self.directory),
                   "LD_PRELOAD": str(self.directory / "missing.so"), "PATH": str(self.directory),
                   "HOME": str(self.directory), "BASH_ENV": str(self.directory / "startup.sh")}
        with mock.patch.dict(os.environ, hostile):
            result = transcribe(str(self.media), self.config(threads=3))
        payload = json.loads(result.text)
        prefix = payload["prefix"]
        expected = [str(self.executable), "-m", str(self.model), "-f", str(self.media),
                    "-t", "3", "-otxt", "-of", prefix, "-np", "-ng"]
        self.assertEqual(payload["argv"], expected)
        self.assertEqual(payload["environment"]["PATH"], "/usr/bin:/bin")
        for name in hostile:
            if name not in ("PATH", "HOME"):
                self.assertNotIn(name, payload["environment"])
        self.assertIn(payload["environment"]["LANG"], ("C.UTF-8", "C.utf8", "C.UTF8"))
        temporary_output = Path(prefix).parent
        self.assertTrue(temporary_output.is_absolute())
        self.assertEqual(payload["cwd"], str(temporary_output))
        self.assertEqual(payload["environment"]["HOME"], str(temporary_output))
        for name in ("TMPDIR", "TMP", "TEMP"):
            self.assertEqual(payload["environment"][name], str(temporary_output))
        self.assertFalse(temporary_output.exists())
        self.assertNotIn("DO_NOT_PROPAGATE", json.dumps(result.to_dict()))
        self.assert_sources_unchanged()

    def test_explicit_owner_only_parent_contains_and_removes_private_child(self):
        parent = self.directory / "owned-scratch"
        parent.mkdir(mode=0o700)
        sentinel = parent / "owner-note"
        sentinel.write_text("Preserve the caller's file", encoding="utf-8")
        self.script("""
            output.write_text(json.dumps({'prefix': prefix, 'cwd': os.getcwd(),
                                          'mode': Path(prefix).parent.stat().st_mode & 0o777}), encoding='utf-8')
        """)
        result = transcribe(str(self.media), self.config(), temporary_parent=parent)
        child = json.loads(result.text)
        private_directory = Path(child["prefix"]).parent
        self.assertEqual(private_directory.parent, parent)
        self.assertEqual(child["cwd"], str(private_directory))
        self.assertEqual(child["mode"], 0o700)
        self.assertFalse(private_directory.exists())
        self.assertEqual(list(parent.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "Preserve the caller's file")
        self.assert_sources_unchanged()

    def test_unsafe_temporary_parents_fail_before_launch(self):
        private = self.directory / "private-parent"
        private.mkdir(mode=0o700)
        public = self.directory / "public-parent"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        group_readable = self.directory / "group-readable-parent"
        group_readable.mkdir(mode=0o750)
        group_readable.chmod(0o750)
        linked = self.directory / "linked-parent"
        linked.symlink_to(private, target_is_directory=True)
        marker = self.directory / "executable-started"
        self.script("Path(" + repr(str(marker)) + ").write_text('started')\noutput.write_text('Transcript')")
        config = self.config()
        for parent in ("relative-parent", public, group_readable, linked,
                       self.directory / "missing-parent", self.model):
            with self.subTest(parent=str(parent)), mock.patch.object(transcription, "_supervisor") as launch:
                with self.assertRaises(TranscriptionError):
                    transcribe(str(self.media), config, temporary_parent=parent)
                launch.assert_not_called()
                self.assertFalse(marker.exists())
        self.assertEqual(list(private.iterdir()), [])
        self.assert_sources_unchanged()

    def test_runtime_cli_derives_existing_private_scratch_from_request_parent(self):
        from workbench.services.runtime import main

        scratch = self.directory / "scratch"
        scratch.mkdir(mode=0o700)
        self.script("output.write_text(json.dumps({'prefix': prefix}), encoding='utf-8')")
        request_path = self.directory / "request.json"
        request = {"schema_version": 1, "operation": "transcribe", "root": str(self.directory),
                   "media_path": str(self.media),
                   "transcription": {"executable": str(self.executable), "model_path": str(self.model)}}
        request_path.write_text(json.dumps(request), encoding="utf-8")
        request_path.chmod(0o600)
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = main(["--request", str(request_path)])
        response = json.loads(stream.getvalue())
        self.assertEqual(status, 0, response["error"])
        self.assertIs(response["ok"], True)
        private_directory = Path(json.loads(response["text"])["prefix"]).parent
        self.assertEqual(private_directory.parent, scratch)
        self.assertFalse(private_directory.exists())
        self.assertTrue(scratch.is_dir())
        self.assertEqual(scratch.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        self.assert_sources_unchanged()

    def test_child_receives_memory_cpu_file_and_core_limits(self):
        self.script("""
            payload = {name: resource.getrlimit(getattr(resource, name))
                       for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_FSIZE', 'RLIMIT_CORE')}
            output.write_text(json.dumps(payload), encoding='utf-8')
        """)
        memory = 512 * 1024 * 1024
        result = transcribe(str(self.media), self.config(max_memory_bytes=memory, max_cpu_seconds=1,
                                                       max_output_bytes=4096))
        limits = json.loads(result.text)
        self.assertEqual(limits["RLIMIT_AS"], [memory, memory])
        self.assertEqual(limits["RLIMIT_FSIZE"], [4096, 4096])
        self.assertEqual(limits["RLIMIT_CORE"], [0, 0])
        self.assertLessEqual(limits["RLIMIT_CPU"][0], 1)
        self.assertGreaterEqual(limits["RLIMIT_CPU"][1], limits["RLIMIT_CPU"][0])

    def test_child_socket_creation_is_denied_without_attempting_connection(self):
        self.script("""
            import socket
            try:
                connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            except OSError as error:
                payload = {'denied': True, 'errno': error.errno}
            else:
                connection.close()
                payload = {'denied': False}
            output.write_text(json.dumps(payload), encoding='utf-8')
        """)
        result = transcribe(str(self.media), self.config())
        self.assertEqual(json.loads(result.text), {"denied": True, "errno": 1})

    def test_unqualified_hosts_fail_closed_before_supervision(self):
        config = self.config()
        with mock.patch.object(transcription.sys, "platform", "darwin"), \
                mock.patch.object(transcription, "_supervisor") as launch:
            with self.assertRaises(TranscriptionError):
                transcribe(str(self.media), config)
        launch.assert_not_called()
        with mock.patch.object(transcription.platform, "machine", return_value="riscv64"), \
                mock.patch.object(transcription, "_supervisor") as launch:
            with self.assertRaises(TranscriptionError):
                transcribe(str(self.media), config)
        launch.assert_not_called()

    def test_invalid_paths_and_unsupported_media_fail_before_launch(self):
        directory_media = self.directory / "directory.wav"
        directory_media.mkdir()
        wrong_media = self.directory / "sample.mp3"
        wrong_media.write_bytes(self.original_media)
        for media in ("relative.wav", self.directory / "missing.wav", directory_media, wrong_media):
            with self.subTest(media=str(media)):
                self.assert_preflight_error(media=media)
        for changes in ({"executable": "recognizer"}, {"model_path": "model.bin"},
                        {"executable": str(self.directory / "missing-tool")},
                        {"model_path": str(self.directory / "missing-model.bin")},
                        {"executable": str(self.directory)}, {"model_path": str(self.directory)}):
            with self.subTest(changes=changes):
                self.assert_preflight_error(**changes)

    def test_nonexecutable_tool_fails_before_launch(self):
        self.executable.chmod(0o644)
        self.assert_preflight_error()

    def test_media_and_model_byte_limits_fail_before_launch(self):
        self.assert_preflight_error(max_media_bytes=len(self.original_media) - 1)
        self.assert_preflight_error(max_model_bytes=len(self.original_model) - 1)
        self.assert_sources_unchanged()

    def test_invalid_resource_options_fail_before_launch(self):
        options = ({"timeout_seconds": 0}, {"timeout_seconds": 601}, {"timeout_seconds": True},
                   {"timeout_seconds": math.nan}, {"timeout_seconds": math.inf}, {"threads": 0},
                   {"threads": True}, {"max_output_bytes": 0}, {"max_output_bytes": True},
                   {"max_media_bytes": -1}, {"max_model_bytes": 1.5}, {"max_memory_bytes": True},
                   {"max_cpu_seconds": 0}, {"max_cpu_seconds": 1.5})
        for changes in options:
            with self.subTest(changes=changes):
                self.assert_preflight_error(**changes)

    def test_nonzero_exit_does_not_return_transcript_or_echo_diagnostics(self):
        self.script("""
            output.write_text('Never return this failed transcript', encoding='utf-8')
            sys.stderr.write('DO_NOT_ECHO_FAILURE_BODY')
            sys.exit(7)
        """)
        with self.assertRaises(TranscriptionError) as caught:
            transcribe(str(self.media), self.config())
        self.assertNotIn("DO_NOT_ECHO_FAILURE_BODY", str(caught.exception))
        self.assertNotIn("Never return", str(caught.exception))
        self.assert_sources_unchanged()

    def test_aggregate_stdout_stderr_budget_is_enforced(self):
        self.script("""
            os.write(1, b'a' * 70)
            os.write(2, b'b' * 70)
            output.write_text('Within transcript cap', encoding='utf-8')
        """)
        with self.assertRaises(TranscriptionError):
            transcribe(str(self.media), self.config(max_output_bytes=128))
        self.assert_sources_unchanged()

    def test_exact_transcript_byte_cap_including_utf8_is_accepted(self):
        self.script("output.write_text('é' * 32, encoding='utf-8')")
        result = transcribe(str(self.media), self.config(max_output_bytes=64))
        self.assertEqual(result.text, "é" * 32)
        self.assertEqual(len(result.text.encode("utf-8")), 64)

    def test_oversized_transcript_is_rejected(self):
        self.script("output.write_text('x' * 65, encoding='utf-8')")
        with self.assertRaises(TranscriptionError):
            transcribe(str(self.media), self.config(max_output_bytes=64))
        self.assert_sources_unchanged()

    def test_invalid_utf8_transcript_is_rejected_without_replacement(self):
        self.script("output.write_bytes(b'bad utf8 \\xff')")
        with self.assertRaises(TranscriptionError):
            transcribe(str(self.media), self.config())

    def test_missing_and_empty_transcripts_are_rejected(self):
        for body in ("pass", "output.write_text('   \\n', encoding='utf-8')"):
            with self.subTest(body=body):
                self.script(body)
                with self.assertRaises(TranscriptionError):
                    transcribe(str(self.media), self.config())

    def test_symlink_directory_and_fifo_transcripts_are_rejected(self):
        target = self.directory / "outside-transcript.txt"
        target.write_text("OUTSIDE TRANSCRIPT TARGET", encoding="utf-8")
        bodies = ("output.symlink_to(" + repr(str(target)) + ")", "output.mkdir()", "os.mkfifo(output)")
        for body in bodies:
            with self.subTest(body=body):
                self.script(body)
                with self.assertRaises(TranscriptionError):
                    transcribe(str(self.media), self.config(timeout_seconds=0.5))
        self.assertEqual(target.read_text(encoding="utf-8"), "OUTSIDE TRANSCRIPT TARGET")
        self.assert_sources_unchanged()

    def test_timeout_is_bounded_and_does_not_echo_child_output(self):
        self.script("""
            sys.stderr.write('DO_NOT_ECHO_TIMEOUT_BODY')
            sys.stderr.flush()
            time.sleep(30)
        """)
        started = time.monotonic()
        with self.assertRaises(TranscriptionError) as caught:
            transcribe(str(self.media), self.config(timeout_seconds=0.1))
        self.assertLess(time.monotonic() - started, 3)
        self.assertNotIn("DO_NOT_ECHO_TIMEOUT_BODY", str(caught.exception))
        self.assert_sources_unchanged()

    def cleanup_child(self, marker):
        if not marker.exists():
            return
        child = json.loads(marker.read_text(encoding="utf-8"))
        identity = process_identity(child["pid"])
        if identity is None or identity["start"] != child["start"] or identity["state"] in ("Z", "X"):
            return
        descriptor = os.pidfd_open(child["pid"], 0)
        try:
            identity = process_identity(child["pid"])
            if identity is not None and identity["start"] == child["start"]:
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        finally:
            os.close(descriptor)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            identity = process_identity(child["pid"])
            if identity is None or identity["start"] != child["start"] or identity["state"] in ("Z", "X"):
                return
            time.sleep(0.01)
        self.fail("emergency cleanup could not stop the owned fixture child")

    def check_descendant_cleanup(self, *, primary_exits, escape):
        marker = self.directory / "owned-child.json"
        self.addCleanup(self.cleanup_child, marker)
        self.script("""
            marker = Path(MARKER)
            child = os.fork()
            if child == 0:
                if ESCAPE:
                    os.setsid()
                fields = Path('/proc/self/stat').read_text(encoding='ascii').rsplit(')', 1)[1].split()
                marker.write_text(json.dumps({'pid': os.getpid(), 'start': fields[19],
                                              'prefix': prefix}), encoding='utf-8')
                with open(prefix + '.child-log', 'a', encoding='utf-8') as stream:
                    while True:
                        stream.write('still writing\\n')
                        stream.flush()
                        time.sleep(0.01)
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            if not marker.exists():
                sys.exit(9)
            if PRIMARY_EXITS:
                output.write_text('Valid primary transcript', encoding='utf-8')
                sys.exit(0)
            time.sleep(30)
        """.replace("MARKER", repr(str(marker))).replace("ESCAPE", repr(escape)).replace(
            "PRIMARY_EXITS", repr(primary_exits)))
        started = time.monotonic()
        with self.assertRaises(TranscriptionError):
            transcribe(str(self.media), self.config(timeout_seconds=0.5))
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(marker.exists(), "fixture child must actually start before cleanup is assessed")
        child = json.loads(marker.read_text(encoding="utf-8"))
        identity = process_identity(child["pid"])
        self.assertTrue(identity is None or identity["start"] != child["start"] or identity["state"] in ("Z", "X"),
                        "service returned while its exact child was still active")
        self.assertFalse(Path(child["prefix"]).parent.exists())
        self.assert_sources_unchanged()

    def test_timeout_joins_ready_descendant_before_removing_private_output(self):
        self.check_descendant_cleanup(primary_exits=False, escape=False)

    def test_successful_primary_with_escaped_writer_fails_and_joins_child(self):
        self.check_descendant_cleanup(primary_exits=True, escape=True)


if __name__ == "__main__":
    unittest.main()
