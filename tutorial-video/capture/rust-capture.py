#!/usr/bin/env python3
"""Capture fresh Rust DSP editor footage from a disposable example copy.

Running this file without a command records both clips. The source files used
by the editor come from this repository; no previously recorded media is input.
The helpers can also be imported by a production runner.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


TUTORIAL = Path(__file__).resolve().parents[1]
REPOSITORY = TUTORIAL.parent


@dataclass
class CaptureOptions:
    repo: Path = REPOSITORY
    tools: Path | None = None
    editor: Path | None = None
    output_dir: Path = TUTORIAL / ".work/capture"
    workspace: Path | None = None
    display: int = 96
    library_path: str | None = None
    executables: dict[str, Path] | None = None


class RustCapture:
    """One owned X display, editor, and fresh copy of the Rust example."""

    def __init__(self, options: CaptureOptions):
        self.options = options
        self.repo = options.repo.resolve()
        self.source = self.repo / "editor/examples/rust-dsp"
        self.editor = (options.editor or self.repo / "build/editor-fltk-sdk/foundation-editor-fltk").resolve()
        self.output = options.output_dir.resolve()
        self.workspace = options.workspace.resolve() if options.workspace else None
        self.tools = options.tools.resolve() if options.tools else None
        self.env = os.environ.copy()
        self.env["DISPLAY"] = f":{options.display}"
        if options.library_path:
            self.env["LD_LIBRARY_PATH"] = options.library_path
        elif self.tools and (self.tools / "usr/lib/x86_64-linux-gnu").is_dir():
            previous = self.env.get("LD_LIBRARY_PATH", "")
            self.env["LD_LIBRARY_PATH"] = str(self.tools / "usr/lib/x86_64-linux-gnu") + (":" + previous if previous else "")
        self.processes: list[subprocess.Popen] = []
        self.handles = []
        self.editor_process: subprocess.Popen | None = None
        self.receipt: dict = {}

    def executable(self, name: str) -> str:
        override = (self.options.executables or {}).get(name)
        if override is not None:
            # Preserve the executable basename: ImageMagick uses it to select
            # the import command when /usr/bin/import is a multicall symlink.
            override = override.absolute()
            if not override.is_file() or not os.access(override, os.X_OK):
                raise RuntimeError(f"Tool override is not executable: {override}")
            return str(override)
        found = shutil.which(name)
        if found:
            return found
        if self.tools:
            for candidate in (self.tools / name, self.tools / "usr/bin" / name):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
        raise RuntimeError(f"Missing {name}; install it in PATH or supply --tools DIRECTORY")

    def tool(self, name: str, *arguments) -> str:
        return subprocess.check_output([self.executable(name), *map(str, arguments)], env=self.env, text=True)

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def prepare(self) -> dict:
        if not (self.source / "project.json").is_file():
            raise RuntimeError(f"Missing repository Rust example: {self.source}")
        if not self.editor.is_file():
            raise RuntimeError(f"Missing native editor: {self.editor}; supply --editor PATH")
        if self.workspace is None:
            self.workspace = Path(tempfile.mkdtemp(prefix="software-foundation-video-rust-")) / "rust-dsp"
        elif self.workspace.exists():
            raise RuntimeError(f"Workspace already exists; choose a fresh --workspace: {self.workspace}")
        self.output.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.source, self.workspace)
        inputs = []
        for path in sorted(self.source.rglob("*")):
            if path.is_file():
                relative = path.relative_to(self.source)
                inputs.append({"path": str(relative), "sha256": self.sha256(path)})
        self.receipt = {
            "source_directory": str(self.source), "workspace": str(self.workspace),
            "editor": str(self.editor), "editor_sha256": self.sha256(self.editor),
            "display": self.env["DISPLAY"], "inputs": inputs, "media": [],
        }
        self.save_receipt()
        return self.receipt

    def save_receipt(self):
        (self.output / "rust-capture-receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")

    def spawn(self, argv, log_name: str, *, cwd: Path | None = None, stdin=None):
        log = open(self.output / log_name, "w")
        self.handles.append(log)
        process = subprocess.Popen(argv, cwd=cwd, env=self.env, stdin=stdin, stdout=log,
                                   stderr=log, start_new_session=True)
        self.processes.append(process)
        return process

    def start_display(self):
        number = self.options.display
        if Path(f"/tmp/.X{number}-lock").exists() or Path(f"/tmp/.X11-unix/X{number}").exists():
            raise RuntimeError(f"Display {self.env['DISPLAY']} is already owned")
        for name in ("Xvfb", "xdotool", "ffmpeg", "ffprobe", "import"):
            self.executable(name)
        display = self.spawn([self.executable("Xvfb"), self.env["DISPLAY"], "-screen", "0",
                              "1440x900x24", "-nolisten", "tcp"], "rust-xvfb.log")
        time.sleep(1)
        if display.poll() is not None:
            raise RuntimeError("Private display failed; see rust-xvfb.log")

    def stop_editor(self):
        if self.editor_process is not None:
            self.stop_process(self.editor_process)
            self.editor_process = None

    def start_editor(self):
        self.stop_editor()
        self.editor_process = self.spawn([str(self.editor), "--project", "project.json"],
                                         "rust-editor.log", cwd=self.workspace)
        window = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.editor_process.poll() is not None:
                raise RuntimeError("Native editor exited; see rust-editor.log")
            try:
                windows = self.tool("xdotool", "search", "--onlyvisible", "--pid", self.editor_process.pid).splitlines()
                if windows:
                    window = windows[0]
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(.2)
        if window is None:
            raise RuntimeError("Native editor did not present a window")
        self.tool("xdotool", "windowmove", window, 0, 0)
        self.tool("xdotool", "windowsize", window, 1440, 900)
        self.tool("xdotool", "windowfocus", window)
        time.sleep(1.5)

    def mouse(self, x: int, y: int, clicks: int = 0):
        self.tool("xdotool", "mousemove", "--sync", x, y)
        time.sleep(.3)
        if clicks:
            self.tool("xdotool", "click", "--repeat", clicks, "--delay", 180, 1)
            time.sleep(.7)

    def key(self, *keys):
        self.tool("xdotool", "key", "--clearmodifiers", *keys)
        time.sleep(.5)

    def screenshot(self, name: str) -> Path:
        path = self.output / (name + ".png")
        subprocess.run([self.executable("import"), "-display", self.env["DISPLAY"],
                        "-window", "root", str(path)], env=self.env, check=True)
        return path

    def flow_action(self):
        time.sleep(3)
        self.mouse(530, 151, 1)
        time.sleep(4)
        self.mouse(770, 151, 1)
        time.sleep(3)
        self.mouse(530, 151, 1)
        self.mouse(1400, 850)
        self.screenshot("rust-flow")
        time.sleep(5)

    def source_action(self):
        time.sleep(2)
        self.mouse(530, 151, 2)
        time.sleep(3)
        # Source navigation opens the ordinary dsp.rs file at process_samples.
        # Twelve single-line wheel steps bring the complete short algorithm into view.
        self.mouse(1040, 430)
        self.tool("xdotool", "click", "--repeat", 12, "--delay", 120, 5)
        self.mouse(1395, 855)
        time.sleep(2)
        self.screenshot("rust-source")
        time.sleep(12)

    def record(self, name: str, action, minimum_seconds: float = 25) -> dict:
        target = self.output / (name + ".mp4")
        recording = self.spawn([
            self.executable("ffmpeg"), "-y", "-f", "x11grab", "-framerate", "30",
            "-video_size", "1440x900", "-i", self.env["DISPLAY"] + ".0", "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt",
            "yuv420p", str(target)
        ], name + "-ffmpeg.log", stdin=subprocess.PIPE)
        started = time.monotonic()
        time.sleep(1)
        try:
            action()
            time.sleep(max(0, minimum_seconds - (time.monotonic() - started)))
        finally:
            if recording.poll() is None:
                recording.communicate(b"q", timeout=15)
        if recording.returncode:
            raise RuntimeError(f"Recording failed; see {name}-ffmpeg.log")
        probe = json.loads(self.tool("ffprobe", "-v", "error", "-select_streams", "v:0",
                                     "-show_entries", "format=duration:stream=width,height",
                                     "-of", "json", target))
        result = {"file": str(target), "bytes": target.stat().st_size, "sha256": self.sha256(target),
                  "duration": float(probe["format"]["duration"]), **probe["streams"][0]}
        self.receipt["media"].append(result)
        self.save_receipt()
        print(json.dumps(result), flush=True)
        return result

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def cleanup(self):
        for process in reversed(self.processes):
            self.stop_process(process)
        for handle in self.handles:
            handle.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("all", "source", "flow", "probe", "prepare"), default="all")
    parser.add_argument("--repo", type=Path, default=REPOSITORY)
    parser.add_argument("--tools", "--tools-root", type=Path, default=os.environ.get("FOUNDATION_VIDEO_TOOLS_ROOT"))
    parser.add_argument("--editor", type=Path, default=os.environ.get("FOUNDATION_VIDEO_EDITOR"))
    parser.add_argument("--output-dir", type=Path, default=TUTORIAL / ".work/capture")
    parser.add_argument("--workspace", type=Path, help="Fresh disposable example directory; defaults to a unique /tmp path")
    parser.add_argument("--display", type=int, default=96)
    parser.add_argument("--library-path", default=os.environ.get("FOUNDATION_VIDEO_LIBRARY_PATH"))
    parser.add_argument("--xvfb", type=Path, help="Explicit Xvfb executable")
    parser.add_argument("--xdotool", type=Path, help="Explicit xdotool executable")
    parser.add_argument("--ffmpeg", type=Path, help="Explicit ffmpeg executable")
    parser.add_argument("--ffprobe", type=Path, help="Explicit ffprobe executable")
    parser.add_argument("--imagemagick", type=Path, help="Explicit ImageMagick import executable")
    parser.add_argument("--keep-workspace", action="store_true", help="Retain the disposable example copy after recording")
    args = parser.parse_args(argv)
    executables = {name: value for name, value in {
        "Xvfb": args.xvfb, "xdotool": args.xdotool, "ffmpeg": args.ffmpeg,
        "ffprobe": args.ffprobe, "import": args.imagemagick,
    }.items() if value is not None}
    capture = RustCapture(CaptureOptions(args.repo, args.tools, args.editor, args.output_dir,
                                       args.workspace, args.display, args.library_path, executables))
    completed = False
    try:
        receipt = capture.prepare()
        print(json.dumps({"source_directory": receipt["source_directory"], "workspace": receipt["workspace"]}), flush=True)
        if args.command == "prepare":
            return
        capture.start_display()
        if args.command in ("all", "flow"):
            capture.start_editor()
            capture.record("rust-flow", capture.flow_action)
        if args.command in ("all", "source"):
            capture.start_editor()
            capture.record("rust-source", capture.source_action)
        if args.command == "probe":
            capture.start_editor()
            print(str(capture.screenshot("rust-probe")), flush=True)
        completed = True
    finally:
        capture.cleanup()
        if completed and args.command != "prepare" and not args.keep_workspace:
            shutil.rmtree(capture.workspace)
            if args.workspace is None:
                capture.workspace.parent.rmdir()
            capture.receipt["workspace_retained"] = False
            capture.save_receipt()


if __name__ == "__main__":
    main()
