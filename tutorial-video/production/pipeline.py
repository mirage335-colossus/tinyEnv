#!/usr/bin/env python3
"""Regenerate the tutorial and capabilities films from repository content."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from backend_comparison import gallery_inventory, verify_receipt

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
OUTPUT = ROOT / "output"
FILMS = ("tutorial", "capabilities")
TOOL_NAMES = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "xvfb": "Xvfb",
              "xdotool": "xdotool", "imagemagick": "import"}
BROWSER_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
DOCUMENTATION_PDFS = ("00-edit-paths.pdf", "01-code-walkthroughs.pdf", "02-compiler-reference.pdf",
                     "03-execution-flows.pdf", "04-code-flowcharts.pdf", "AI-AUTHORED__GUI-MENTAL-MODEL.pdf")


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json_atomic(path: Path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="." + path.name + "-",
                                     suffix=".pending", dir=path.parent, delete=False) as handle:
        pending = Path(handle.name)
        json.dump(value, handle, indent=2)
        handle.write("\n")
    try:
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def executable(value: str | Path) -> Path:
    selected = shutil.which(str(value))
    if selected is None:
        candidate = Path(value).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise RuntimeError(f"Missing executable {value}; install it or supply its CLI override")
        selected = str(candidate)
    return Path(selected).absolute()


def checked_output_path(path: Path, repository: Path, explicit=False) -> Path:
    expanded = path.expanduser().absolute()
    resolved = expanded.resolve()
    if OUTPUT.is_symlink() and expanded.is_relative_to(OUTPUT.absolute()):
        raise RuntimeError("tutorial-video/output must not be a symlink; select the intended external path explicitly instead")
    if expanded.is_relative_to(repository) and not resolved.is_relative_to(repository):
        raise RuntimeError("An in-repository output path must not escape through a symlink; select the intended external path explicitly instead")
    if resolved.is_relative_to(OUTPUT.resolve()) and OUTPUT.resolve().is_relative_to(ROOT):
        return resolved
    if explicit and not resolved.is_relative_to(repository) and not repository.is_relative_to(resolved):
        return resolved
    raise RuntimeError("Output must remain under tutorial-video/output, or use an explicit --output-dir outside the repository")


def work_path(relative: str) -> Path:
    path = WORK / relative
    if not path.resolve().is_relative_to(WORK.resolve()):
        raise RuntimeError("Generated work path escapes through a symlink: " + relative)
    return path


def reject_escaping_links(folder: Path, boundary: Path):
    if folder.exists():
        for path in folder.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(boundary.resolve()):
                raise RuntimeError("Generated path escapes through a symlink: " + str(path))


def verify_assets() -> list[dict]:
    inventory = json.loads((ROOT / "assets/inventory.json").read_text())
    for item in inventory["files"]:
        path = (ROOT / "assets" / item["path"]).resolve()
        if not path.is_relative_to((ROOT / "assets").resolve()):
            raise RuntimeError("Asset inventory contains an escaping path")
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise RuntimeError(f"Retained asset is absent or changed: {item['path']}")
    return inventory["files"]


def source_inventory() -> dict[str, str]:
    ignored = {".work", "output", ".venv", "__pycache__"}
    return {str(path.relative_to(ROOT)): sha(path)
            for path in sorted(ROOT.rglob("*"))
            if path.is_file() and not set(path.relative_to(ROOT).parts).intersection(ignored)
            and path.suffix != ".pyc"}


class Pipeline:
    def __init__(self, args):
        self.args = args
        self.repository = args.repo.expanduser().resolve()
        if self.repository != ROOT.parent.resolve():
            raise RuntimeError("--repo must name the checkout containing this tutorial-video project; build, examples and capture must use the same source")
        if not (self.repository / "build.sh").is_file() or not (self.repository / "editor/examples").is_dir():
            raise RuntimeError("--repo must name a software-foundation checkout with its retained editor examples")
        if WORK.is_symlink() or not WORK.resolve().is_relative_to(ROOT):
            raise RuntimeError("tutorial-video/.work must be an ordinary directory inside this project")
        self.output = checked_output_path(args.output_dir or OUTPUT, self.repository, args.output_dir is not None)
        WORK.mkdir(parents=True, exist_ok=True)
        work_path("logs").mkdir(exist_ok=True)
        for name in ("editor", "capture", "gallery", "projects", "capture-projects", "examples", "event-check", "preparation.json"):
            reject_escaping_links(work_path(name), WORK)
        reject_escaping_links(work_path("logs"), WORK)
        for film in FILMS:
            folder = self.output / film
            if folder.is_symlink() or not folder.resolve().is_relative_to(self.output):
                raise RuntimeError("Film output escapes through a symlink: " + film)
            if folder.exists() and any(path.is_symlink() for path in folder.rglob("*")):
                raise RuntimeError("Generated film directories must not contain symlinks: " + film)
        self.environment = dict(os.environ)
        # Host-installed tools are prerequisites; content never comes from an
        # ambient Python import path or an earlier production project.
        self.environment.pop("PYTHONPATH", None)
        self.environment.pop("PYTHONHOME", None)
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if args.library_path:
            self.environment["LD_LIBRARY_PATH"] = args.library_path
        elif args.tools_root:
            self.environment["LD_LIBRARY_PATH"] = str(args.tools_root.resolve() / "usr/lib/x86_64-linux-gnu")
        runtime = WORK / "venv/bin/python"
        self.python = executable(args.python or (runtime if runtime.is_file() else sys.executable))
        self.tools = {}
        for option, name in TOOL_NAMES.items():
            override = getattr(args, option)
            if override:
                candidate = override
            elif args.tools_root:
                candidates = (args.tools_root / name, args.tools_root / "usr/bin" / name)
                candidate = next((path for path in candidates if path.is_file()), name)
            else:
                candidate = name
            # Rendering and verification require only the media tools.
            if args.command in ("render", "verify") and option not in ("ffmpeg", "ffprobe"):
                continue
            self.tools[option] = executable(candidate)
        self.browser = None
        self.browser_version = None
        if args.command in ("prepare", "capture", "all"):
            browser = args.browser or os.environ.get("FOUNDATION_VIDEO_BROWSER")
            if not browser:
                browser = next((name for name in BROWSER_NAMES if shutil.which(name)), None)
            if browser is None:
                raise RuntimeError("Documentation capture needs an installed Chromium or Chrome with its native PDF viewer; supply --browser")
            self.browser = executable(browser)
            self.browser_version = subprocess.check_output(
                [str(self.browser), "--version"], cwd=WORK, env=self.environment,
                stderr=subprocess.STDOUT, text=True).strip()
            if not any(name in self.browser_version.lower() for name in ("chromium", "chrome")):
                raise RuntimeError("The documentation PDF capture uses Chromium/Chrome controls; select a Chromium-family --browser")
        self.editor = executable(args.editor) if args.editor else WORK / "editor/foundation-editor-fltk"
        self.films = list(dict.fromkeys(args.film or FILMS))

    def documentation_inventory(self) -> dict:
        directory = self.repository / "documentation-tool/published"
        if not directory.resolve().is_relative_to(self.repository):
            raise RuntimeError("Documentation reader bundle must remain inside the containing repository")
        for relative in ("index.html", "explorer.js", "explorer.css", "data.js",
                         "AI-AUTHORED__GUI-MENTAL-MODEL.html", "atlas.json", *["pdf/" + name for name in DOCUMENTATION_PDFS]):
            if not (directory / relative).is_file():
                raise RuntimeError("Retained documentation input is missing: " + relative)
        files = {}
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise RuntimeError("Documentation inputs must be retained files, not symlinks: " + str(path))
            if path.is_file():
                files[str(path.relative_to(self.repository))] = sha(path)
        metadata = json.loads((directory / "atlas.json").read_text())
        return {"reader_files": files, "atlas_sha256": sha(directory / "atlas.json"),
                "snapshot_generated_at": metadata.get("generated_at"),
                "snapshot_fingerprint": metadata.get("fingerprint")}

    def run(self, name: str, command: list[str | Path], cwd=WORK):
        print("Running " + name, flush=True)
        log = work_path("logs/" + name + ".log")
        with log.open("w") as writer:
            process = subprocess.Popen([str(value) for value in command], cwd=cwd,
                                       env=self.environment, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                for line in process.stdout:
                    writer.write(line)
                    writer.flush()
                    print(line, end="", flush=True)
                code = process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if code:
                raise RuntimeError(f"{name} failed ({code}); see {log}")

    def prepare(self):
        assets = verify_assets()
        documentation = self.documentation_inventory()
        gallery = gallery_inventory(self.repository, self.python, self.environment)
        for film in self.films:
            story = ROOT / "stories" / (film + ".json")
            document = json.loads(story.read_text())
            if not document.get("title") or not document.get("scenes"):
                raise RuntimeError("Empty or incomplete story: " + str(story))
        query = "import json,sys; from importlib.metadata import version; import piper,numpy,onnxruntime,PIL; print(json.dumps({'python':sys.version,'packages':{n:version(n) for n in ('piper-tts','onnxruntime','numpy','Pillow','flatbuffers','packaging','pathvalidate','protobuf')}}))"
        result = subprocess.run([str(self.python), "-c", query], cwd=WORK, env=self.environment,
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Production Python dependencies are missing. Install tutorial-video/requirements.txt into .work/venv; " + result.stderr.strip())
        runtime = json.loads(result.stdout)
        required = {}
        for line in (ROOT / "requirements.txt").read_text().splitlines():
            if "==" in line and not line.lstrip().startswith("#"):
                package, version = line.strip().split("==", 1)
                required[package] = version
        if any(runtime["packages"].get(name) != version for name, version in required.items()):
            raise RuntimeError("Installed Python dependency versions differ from requirements.txt; prepare the declared environment")
        if not self.editor.is_file():
            command = [self.repository / "build.sh", "editor", "build", "dev", "--backend", "fltk",
                       "--build-dir", WORK / "editor", "--build-jobs", str(self.args.build_jobs)]
            if self.args.sdk:
                command += ["--sdk", self.args.sdk.expanduser().resolve()]
            self.run("editor-build", command, self.repository)
        if not self.editor.is_file() or not os.access(self.editor, os.X_OK):
            raise RuntimeError("Editor build did not produce the expected executable; supply --editor")
        receipt = {"repository_head": subprocess.check_output(["git", "-C", str(self.repository), "rev-parse", "HEAD"], cwd=WORK, text=True).strip(),
                   "python": str(self.python), "runtime": runtime, "editor": str(self.editor),
                   "editor_sha256": sha(self.editor), "tools": {name: {"path": str(path), "sha256": sha(path)} for name, path in self.tools.items()},
                   "browser": {"path": str(self.browser), "sha256": sha(self.browser), "version": self.browser_version},
                   "retained_assets": assets, "documentation": documentation, "screenshot_gallery": gallery,
                   "source_files": source_inventory()}
        write_json_atomic(work_path("preparation.json"), receipt)
        print("Retained assets, Python dependencies, media tools and editor are ready.", flush=True)

    def capture(self):
        verify_assets()
        if not self.args.documentation_only:
            if not self.editor.is_file():
                raise RuntimeError("Run prepare first, or supply --editor")
            command = [self.python, ROOT / "capture/run.py", "all", "--repo", self.repository,
                       "--editor", self.editor, "--output-dir", WORK / "capture",
                       "--workspace", WORK / "projects", "--display", str(self.args.display)]
            self.capture_tools(command)
            self.run("capture", command)
        self.documentation()

    def capture_tools(self, command):
        for option, path in self.tools.items():
            command += ["--" + option, path]
        if self.args.tools_root:
            command += ["--tools", self.args.tools_root.resolve()]
        if self.environment.get("LD_LIBRARY_PATH"):
            command += ["--library-path", self.environment["LD_LIBRARY_PATH"]]

    def documentation(self):
        self.documentation_inventory()
        command = [self.python, ROOT / "capture/documentation.py", "all", "--repo", self.repository,
                   "--browser", self.browser, "--output-dir", WORK / "capture",
                   "--display", str(self.args.display + 2)]
        self.capture_tools(command)
        self.run("capture-documentation", command)

    def render(self):
        verify_assets()
        if "capabilities" in self.films:
            command = [self.python, ROOT / "production/backend_comparison.py", "--repo", self.repository,
                       "--output-dir", WORK / "gallery", "--ffmpeg", self.tools["ffmpeg"],
                       "--ffprobe", self.tools["ffprobe"]]
            if self.environment.get("LD_LIBRARY_PATH"):
                command += ["--library-path", self.environment["LD_LIBRARY_PATH"]]
            self.run("render-backend-comparison", command)
        for film in self.films:
            command = [self.python, ROOT / "production/render.py", ROOT / "stories" / (film + ".json"),
                       "--output", self.output / film, "--media-root", ROOT,
                       "--model", ROOT / "assets/voices/en_US-ljspeech-medium.onnx",
                       "--font-dir", ROOT / "assets/fonts", "--ffmpeg", self.tools["ffmpeg"],
                       "--ffprobe", self.tools["ffprobe"], "--size-limit-mb", str(self.args.size_limit_mb)]
            if self.args.previews_only:
                command.append("--previews-only")
            if self.args.narration_only:
                command.append("--narration-only")
            self.run("render-" + film, command)

    def examples(self):
        command = [self.python, ROOT / "examples/check_examples.py", "--only", "all",
                   "--work-dir", WORK / "examples"]
        if self.args.rustc:
            command += ["--rustc", executable(self.args.rustc)]
        self.run("examples", command)

    def event(self):
        self.run("event-check", [self.python, ROOT / "examples/language-integration/event-check/run_check.py",
                 "--project", WORK / "projects/simple-c", "--foundation", self.repository,
                 "--work-dir", WORK / "event-check"])

    def verify(self):
        verify_assets()
        renderer_inputs = [ROOT / "production/render.py", ROOT / "production/file_visuals.py"]
        renderer_inputs += sorted((ROOT / "assets/fonts").glob("*.ttf"))
        renderer_hash = hashlib.sha256("".join(path.name + sha(path) for path in renderer_inputs).encode()).hexdigest()
        reports = []
        for film in self.films:
            folder = self.output / film
            for line in (folder / "SHA256SUMS").read_text().splitlines():
                digest, name = line.split("  ", 1)
                path = (folder / name).resolve()
                if not path.is_relative_to(folder.resolve()) or sha(path) != digest:
                    raise RuntimeError("Delivery checksum differs: " + name)
            delivery = json.loads((folder / "delivery.json").read_text())
            if delivery["story_sha256"] != sha(ROOT / "stories" / (film + ".json")):
                raise RuntimeError(f"{film} was rendered from a different story; regenerate it")
            if delivery["voice_model_sha256"] != sha(ROOT / "assets/voices/en_US-ljspeech-medium.onnx"):
                raise RuntimeError(f"{film} voice identity differs")
            if delivery["renderer_sha256"] != renderer_hash:
                raise RuntimeError(f"{film} was rendered with different renderer or font bytes; regenerate it")
            for source in delivery.get("native_sources", []):
                if sha(ROOT / source["file"]) != source["sha256"]:
                    raise RuntimeError("Native source changed since render: " + source["file"])
            comparison = None
            if any(source["file"] == ".work/gallery/backend-comparison.mp4"
                   for source in delivery.get("native_sources", [])):
                comparison = verify_receipt(self.repository, WORK / "gallery", self.python, self.environment)
            self.run("decode-" + film, [self.tools["ffmpeg"], "-hide_banner", "-v", "error", "-xerror",
                     "-err_detect", "explode", "-i", folder / "film.mp4", "-map", "0:v:0",
                     "-map", "0:a:0", "-f", "null", "-"])
            info = json.loads(subprocess.check_output([str(self.tools["ffprobe"]), "-v", "error",
                "-show_streams", "-show_format", "-show_chapters", "-of", "json", str(folder / "film.mp4")],
                cwd=WORK, env=self.environment, text=True))
            if not any(stream["codec_type"] == "video" for stream in info["streams"]) or not any(stream["codec_type"] == "audio" for stream in info["streams"]):
                raise RuntimeError(f"{film} requires both audio and video")
            if len(info["chapters"]) != delivery["chapters"]:
                raise RuntimeError(f"{film} embedded chapter count differs")
            reports.append({"film": film, "sha256": sha(folder / "film.mp4"), "duration_seconds": float(info["format"]["duration"]),
                            "complete_decode_passed": True, "delivery_checksums_passed": True})
            if comparison:
                reports[-1]["screenshot_comparison"] = {"clip_sha256": comparison["clip_sha256"],
                                                        "inputs": comparison["inputs"]}
        self.output.mkdir(parents=True, exist_ok=True)
        for report in reports:
            source = self.output / report["film"] / "film.mp4"
            name = "software-foundation-" + report["film"] + ".mp4"
            destination = self.output / name
            with tempfile.NamedTemporaryFile(prefix="." + name + "-", suffix=".pending", dir=self.output, delete=False) as handle:
                pending = Path(handle.name)
            try:
                if sha(source) != report["sha256"]:
                    raise RuntimeError("Film changed before named delivery publication: " + report["film"])
                shutil.copy2(source, pending)
                if sha(pending) != report["sha256"]:
                    raise RuntimeError("Named delivery copy differs: " + name)
                pending.replace(destination)
            finally:
                pending.unlink(missing_ok=True)
            report["delivery_file"] = name
            report["delivery_sha256"] = sha(destination)
        write_json_atomic(self.output / "verification.json", {"films": reports})
        print("Verified film streams and source identities; published named MP4 copies with matching hashes.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "capture", "render", "all", "verify"))
    parser.add_argument("--repo", type=Path, default=ROOT.parent, help="Containing checkout; defaults to this tutorial-video directory's parent")
    parser.add_argument("--output-dir", type=Path, help="Explicit delivery location; default tutorial-video/output")
    parser.add_argument("--python", type=Path, help="Production Python; default .work/venv/bin/python if available, otherwise this interpreter")
    parser.add_argument("--editor", type=Path, help="Existing editor; otherwise prepare builds .work/editor")
    parser.add_argument("--browser", type=Path, help="Installed Chromium or Chrome with its native PDF viewer for local documentation capture")
    parser.add_argument("--sdk", type=Path, help="Optional retained native C++ SDK for the editor build")
    parser.add_argument("--rustc", type=Path, help="Rust compiler for the compiled examples; default PATH")
    parser.add_argument("--tools-root", type=Path, help="Optional extracted host-tool prefix, with root or usr/bin executables")
    parser.add_argument("--library-path", help="Explicit runtime library search path for selected host tools")
    for name in TOOL_NAMES:
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--film", action="append", choices=FILMS, help="Select one film; repeat for both")
    parser.add_argument("--display", type=int, default=95)
    parser.add_argument("--build-jobs", type=int, default=2)
    parser.add_argument("--size-limit-mb", type=float, default=120)
    parser.add_argument("--documentation-only", action="store_true", help="With capture, regenerate only the HTML/PDF documentation footage")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--previews-only", action="store_true")
    modes.add_argument("--narration-only", action="store_true")
    args = parser.parse_args()
    if args.build_jobs <= 0 or args.display < 1 or args.size_limit_mb <= 0:
        parser.error("Jobs, display number and film size limit must be positive")
    if (args.previews_only or args.narration_only) and args.command != "render":
        parser.error("Preview and narration modes apply only to render")
    if args.documentation_only and args.command != "capture":
        parser.error("--documentation-only applies only to capture")
    try:
        pipeline = Pipeline(args)
        if args.command == "all":
            pipeline.prepare()
            pipeline.examples()
            pipeline.capture()
            pipeline.event()
            pipeline.render()
            pipeline.verify()
        else:
            getattr(pipeline, args.command)()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("Video pipeline: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
