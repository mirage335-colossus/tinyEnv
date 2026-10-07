#!/usr/bin/env python3
"""Compose complete, verified application screenshots into comparison footage."""
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

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
WIDTH, HEIGHT, FPS = 1824, 804, 20
SHOT_SECONDS = 11
BG, PANEL, INK, MUTED, CYAN, LINE = (
    "#101b2d", "#19283e", "#f4f1e7", "#b3c2ce", "#65dddf", "#344b62")
FONT_NAMES = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono.ttf")
GALLERY_NAMES = tuple(sorted(("fltk.png", "rev.png", "sdl.png", "framebuffer.png",
    "hosted-web.png", "wasm.png", "terminal.png", "BUILD.txt", "screenshots.json", "SHA256SUMS")))
# The committed gallery's reviewed source date is retained with its exact
# commit, so clean or depth-one checkouts need no historical Git objects.
SOURCE_DATES = {"2e33720a73f0686dc1ffe72992dfb52e472cd059": "2026-10-05"}
SHOTS = (
    ("01-fltk-rev.png", "FLTK", "fltk.png", "Rev", "rev.png", "Native desktop adapters"),
    ("02-sdl-framebuffer.png", "SDL", "sdl.png", "Framebuffer", "framebuffer.png", "Window and direct framebuffer adapters"),
    ("03-browser-modes.png", "Hosted browser", "hosted-web.png", "Browser Wasm", "wasm.png", "Same visual renderer · different execution"),
    ("04-fltk-terminal.png", "FLTK", "fltk.png", "Terminal TUI", "terminal.png", "Graphical and terminal interfaces · shared application"),
)


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def gallery_inventory(repository: Path, python: Path | str = sys.executable, environment=None) -> dict:
    directory = repository / "docs/screenshots"
    if directory.is_symlink() or not directory.resolve().is_relative_to(repository.resolve()):
        raise RuntimeError("Screenshot gallery must be retained inside the containing repository")
    subprocess.run([str(python), "-B", str(repository / "tools/screenshots.py"), "verify", str(directory)],
                   cwd=WORK, env=environment, check=True)
    if {path.name for path in directory.iterdir()} != set(GALLERY_NAMES):
        raise RuntimeError("The comparison needs the complete seven-image, three-companion gallery")
    manifest = json.loads((directory / "screenshots.json").read_text())
    source_date = SOURCE_DATES.get(manifest["source_commit"])
    if source_date is None:
        result = subprocess.run(["git", "-C", str(repository), "show", "-s", "--format=%cs",
                                 manifest["source_commit"]], cwd=WORK, env=environment,
                                capture_output=True, text=True)
        if result.returncode or not result.stdout.strip():
            raise RuntimeError("Gallery source date is unavailable; retain its reviewed commit/date mapping "
                               "in backend_comparison.py or use a checkout containing that source commit")
        source_date = result.stdout.strip()
    return {"files": {"docs/screenshots/" + name: sha(directory / name) for name in GALLERY_NAMES},
            "source_commit": manifest["source_commit"], "capture_run": manifest["run_id"],
            "capture_attempt": manifest["attempt"], "snapshot_source_date": source_date,
            "verifier_sha256": sha(repository / "tools/screenshots.py")}


def generation_identity(repository: Path, python: Path | str = sys.executable, environment=None) -> dict:
    return {"gallery": gallery_inventory(repository, python, environment),
            "generator_sha256": sha(Path(__file__)),
            "fonts": {name: sha(ROOT / "assets/fonts" / name) for name in FONT_NAMES}}


def verify_receipt(repository: Path, folder: Path, python: Path | str = sys.executable, environment=None) -> dict:
    receipt = json.loads((folder / "comparison-receipt.json").read_text())
    if receipt["inputs"] != generation_identity(repository, python, environment):
        raise RuntimeError("Screenshot comparison inputs or generator changed; render capabilities again")
    if receipt["clip_sha256"] != sha(folder / "backend-comparison.mp4"):
        raise RuntimeError("Screenshot comparison clip differs from its verified receipt")
    for name, digest in receipt["previews"].items():
        if name not in {shot[0] for shot in SHOTS} or sha(folder / name) != digest:
            raise RuntimeError("Screenshot comparison preview changed: " + name)
    return receipt


def face(size: int, *, bold=False, mono=False):
    from PIL import ImageFont

    name = "DejaVuSansMono.ttf" if mono else "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(ROOT / "assets/fonts" / name), size)


def diagram(draw: ImageDraw.ImageDraw):
    boxes = ((28, 8, 798, 94), (858, 8, 1214, 94), (1274, 8, 1796, 94))
    for box in boxes:
        draw.rounded_rectangle(box, radius=12, fill=PANEL, outline=LINE, width=2)
    draw.text((413, 25), "Shared application", font=face(30, bold=True), fill=INK, anchor="mt")
    draw.text((413, 62), "State · behavior · layout", font=face(21), fill=MUTED, anchor="mt")
    draw.text((1036, 26), "GUI abstraction", font=face(29, bold=True), fill=CYAN, anchor="mt")
    draw.text((1036, 62), "Common interface", font=face(20), fill=MUTED, anchor="mt")
    draw.text((1535, 25), "Host", font=face(30, bold=True), fill=INK, anchor="mt")
    draw.text((1535, 62), "Rendering · input · platform", font=face(21), fill=MUTED, anchor="mt")
    for start, end in ((808, 846), (1224, 1262)):
        draw.line((start, 51, end, 51), fill=CYAN, width=3)
        draw.polygon(((end, 51), (end - 9, 45), (end - 9, 57)), fill=CYAN)


def compose(repository: Path, shot, source_date: str) -> Image.Image:
    from PIL import Image, ImageDraw

    result = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(result)
    diagram(draw)
    _, left_label, left_file, right_label, right_file, note = shot
    for left, label, filename in ((28, left_label, left_file), (930, right_label, right_file)):
        draw.rounded_rectangle((left, 112, left + 866, 716), radius=14,
                               fill=PANEL, outline=LINE, width=2)
        draw.text((left + 433, 129), label, font=face(36, bold=True), fill=INK, anchor="mt")
        with Image.open(repository / "docs/screenshots" / filename) as source:
            image = source.convert("RGB")
            if image.width > 800 or image.height > 531:
                raise RuntimeError("Source screenshot exceeds the complete-image comparison area: " + filename)
            # Paste every original pixel once. In particular the terminal border
            # and status row remain visible; no source is cropped or resampled.
            x, y = left + (866 - image.width) // 2, 174 + (531 - image.height) // 2
            result.paste(image, (x, y))
    draw.text((WIDTH // 2, 729), note, font=face(26), fill=CYAN, anchor="mt")
    draw.text((WIDTH // 2, 770), "Application snapshot · " + source_date, font=face(19, mono=True),
              fill=MUTED, anchor="mt")
    return result


def executable(value) -> Path:
    selected = shutil.which(str(value))
    if selected is None:
        candidate = Path(value).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise RuntimeError("Missing media executable: " + str(value))
        selected = str(candidate)
    return Path(selected).absolute()


def checked_folder(folder: Path) -> Path:
    candidate = folder.expanduser().absolute()
    if WORK.is_symlink() or not WORK.resolve().is_relative_to(ROOT):
        raise RuntimeError("tutorial-video/.work must be an ordinary local directory")
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(WORK.resolve()):
        raise RuntimeError("Comparison output must remain within tutorial-video/.work")
    if candidate.exists() and any(path.is_symlink() for path in candidate.rglob("*")):
        raise RuntimeError("Comparison output must contain ordinary generated files")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate.resolve()


def generate(repository: Path, folder: Path, ffmpeg: Path, ffprobe: Path, environment):
    inputs = generation_identity(repository, environment=environment)
    previews = {}
    for shot in SHOTS:
        path = folder / shot[0]
        compose(repository, shot, inputs["gallery"]["snapshot_source_date"]).save(path)
        previews[shot[0]] = sha(path)
    with tempfile.NamedTemporaryFile(prefix=".backend-comparison-", suffix=".mp4", dir=folder, delete=False) as handle:
        pending = Path(handle.name)
    try:
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y"]
        for shot in SHOTS:
            command += ["-loop", "1", "-framerate", str(FPS), "-t", str(SHOT_SECONDS), "-i", str(folder / shot[0])]
        command += ["-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[picture]", "-map", "[picture]",
                    "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-r", str(FPS), "-threads", "2", "-movflags", "+faststart", str(pending)]
        subprocess.run(command, cwd=folder, env=environment, check=True)
        subprocess.run([str(ffmpeg), "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
                        "-i", str(pending), "-map", "0:v:0", "-f", "null", "-"],
                       cwd=folder, env=environment, check=True)
        metadata = json.loads(subprocess.check_output([str(ffprobe), "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", str(pending)], cwd=folder, env=environment, text=True))
        streams = metadata["streams"]
        if (len(streams) != 1 or streams[0]["codec_type"] != "video" or
            (streams[0]["width"], streams[0]["height"]) != (WIDTH, HEIGHT) or
            streams[0]["avg_frame_rate"] != "20/1" or streams[0].get("nb_frames") != "880" or
            abs(float(metadata["format"]["duration"]) - 44) > .001):
            raise RuntimeError("Comparison media geometry, timing or stream inventory differs")
        if generation_identity(repository, environment=environment) != inputs:
            raise RuntimeError("Screenshot comparison inputs changed during generation")
        clip_hash = sha(pending)
        pending.replace(folder / "backend-comparison.mp4")
    finally:
        pending.unlink(missing_ok=True)
    receipt = {"inputs": inputs, "clip_sha256": clip_hash, "dimensions": [WIDTH, HEIGHT],
               "fps": FPS, "duration_seconds": 44.0, "complete_decode_passed": True,
               "source_images_cropped": False, "source_images_resampled": False,
               "previews": previews, "shots": [{"preview": shot[0], "start_seconds": i * SHOT_SECONDS,
                    "end_seconds": (i + 1) * SHOT_SECONDS, "source_images": [shot[2], shot[4]]}
                    for i, shot in enumerate(SHOTS)]}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".comparison-receipt-",
                                     suffix=".pending", dir=folder, delete=False) as handle:
        pending_receipt = Path(handle.name)
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    try:
        pending_receipt.replace(folder / "comparison-receipt.json")
    finally:
        pending_receipt.unlink(missing_ok=True)
    print(f"Verified screenshot comparison: 1824x804, 20 fps, 44.0 seconds, SHA256 {clip_hash}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT.parent)
    parser.add_argument("--output-dir", type=Path, default=WORK / "gallery")
    parser.add_argument("--tools-root", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--library-path")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        repository = args.repo.expanduser().resolve()
        if repository != ROOT.parent.resolve():
            raise RuntimeError("--repo must identify the containing software-foundation checkout")
        folder = checked_folder(args.output_dir)
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if args.library_path:
            environment["LD_LIBRARY_PATH"] = args.library_path
        elif args.tools_root:
            environment["LD_LIBRARY_PATH"] = str(args.tools_root.resolve() / "usr/lib/x86_64-linux-gnu")
        if args.verify_only:
            verify_receipt(repository, folder, environment=environment)
            print("Screenshot comparison inputs and clip receipt match.", flush=True)
        else:
            tools = {}
            for name in ("ffmpeg", "ffprobe"):
                selected = getattr(args, name)
                if not selected and args.tools_root:
                    selected = next((path for path in (args.tools_root / name, args.tools_root / "usr/bin" / name)
                                     if path.is_file()), name)
                tools[name] = executable(selected or name)
            generate(repository, folder, tools["ffmpeg"], tools["ffprobe"], environment)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("Backend comparison: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
