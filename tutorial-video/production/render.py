#!/usr/bin/env python3
"""Render independently authored, narrated editorial films from a JSON story.

Static slides are drawn once. FFmpeg composites fresh native footage, burns
sentence captions, encodes each scene, and joins the scenes without re-encoding.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import subprocess
import sys
import wave
from pathlib import Path

sys.dont_write_bytecode = True

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from file_visuals import draw_delivery, draw_filefocus, draw_filemap

W, H = 1920, 1080
BG = "#101b2d"
PANEL = "#19283e"
PANEL_ALT = "#1e3048"
INK = "#f4f1e7"
MUTED = "#b3c2ce"
CYAN = "#65dddf"
LINE = "#344b62"
AMBER = "#ffcd89"
PROJECT = Path(__file__).resolve().parents[1]
FONT_DIR = PROJECT / "assets/fonts"
MEDIA_ROOT = PROJECT


def run(args: list[str], **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def probe(binary: Path, path: Path) -> dict:
    return json.loads(subprocess.check_output([
        str(binary), "-v", "error", "-show_format", "-show_streams", "-show_chapters",
        "-of", "json", str(path),
    ]))


def font(size: int, bold=False, mono=False):
    stem = "DejaVuSansMono" if mono else "DejaVuSans"
    return ImageFont.truetype(str(FONT_DIR / (stem + ("-Bold" if bold else "") + ".ttf")), size)


def fit_lines(draw, value: str, face, width: int) -> list[str]:
    result = []
    for paragraph in str(value).split("\n"):
        if not paragraph:
            result.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = (current + " " + word).strip()
            if current and draw.textlength(candidate, font=face) > width:
                result.append(current)
                current = word
            else:
                current = candidate
        result.append(current)
    return result


def paragraph(draw, value, xy, width, size=32, color=INK, bold=False, spacing=12):
    face = font(size, bold=bold)
    x, y = xy
    for line in fit_lines(draw, str(value), face, width):
        draw.text((x, y), line, font=face, fill=color)
        y += size + spacing
    return y


def item_text(item):
    if isinstance(item, dict):
        return item.get("label", item.get("title", "")), item.get("detail", "")
    parts = str(item).split(" | ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def media_path(scene: dict) -> Path | None:
    value = scene.get("native", scene.get("file"))
    if isinstance(value, dict):
        value = value["file"]
    return (MEDIA_ROOT / value).resolve() if value else None


def native_options(scene: dict) -> dict:
    value = scene.get("native", scene.get("file"))
    options = dict(value) if isinstance(value, dict) else {}
    for name in ("trim_start", "trim_end", "rate", "crop", "pad_seconds"):
        if name in scene:
            options[name] = scene[name]
    return options


def header(image, scene, index, count, story_title):
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, 12, H), fill=CYAN)
    eyebrow = scene.get("eyebrow", "SOFTWARE FOUNDATION")
    d.text((48, 23), eyebrow.upper(), font=font(19, True), fill=CYAN)
    title = scene["title"]
    title_size = 46
    while d.textlength(title, font=font(title_size, True)) > 1590 and title_size > 32:
        title_size -= 2
    d.text((48, 55), title, font=font(title_size, True), fill=INK)
    d.text((1874, 44), f"{index + 1:02d} / {count:02d}", font=font(20, mono=True), fill=MUTED, anchor="ra")
    d.line((48, 127, 1872, 127), fill=LINE, width=2)
    d.rectangle((0, 990, W, H), fill="#0a1423")
    d.line((48, 990, 1872, 990), fill=LINE, width=2)
    d.text((48, 952), story_title, font=font(16), fill=MUTED)
    d.text((1872, 952), "software-foundation", font=font(16, mono=True), fill=MUTED, anchor="ra")


def draw_title(d, scene):
    tag = scene.get("tag", "A REUSABLE STARTING POINT")
    d.rounded_rectangle((70, 198, 768, 247), radius=14, fill=PANEL_ALT)
    d.text((94, 207), tag.upper(), font=font(20, True), fill=CYAN)
    hero = scene.get("headline", scene["title"])
    end = paragraph(d, hero, (70, 296), 1620, size=77, bold=True, spacing=17)
    subtitle = scene.get("subtitle", "")
    if subtitle:
        end = paragraph(d, subtitle, (74, end + 20), 1530, size=33, color=MUTED, spacing=13)
    items = scene.get("lines", scene.get("callouts", []))[:4]
    if items:
        box_y = max(694, end + 28)
        box_y = min(box_y, 802)
        gap = 24
        width = (1778 - gap * (len(items) - 1)) // len(items)
        for n, item in enumerate(items):
            x = 70 + n * (width + gap)
            d.rounded_rectangle((x, box_y, x + width, 913), radius=17, fill=PANEL)
            label, detail = item_text(item)
            paragraph(d, label, (x + 24, box_y + 18), width - 48, size=26, color=CYAN, bold=True, spacing=7)
            if detail:
                paragraph(d, detail, (x + 24, box_y + 61), width - 48, size=21, color=MUTED, spacing=6)


def draw_card(d, scene):
    lines = scene.get("lines", scene.get("callouts", []))
    if not lines:
        lines = [scene.get("subtitle", "")]
    n = len(lines)
    if n > 6:
        raise ValueError(f"{scene['id']}: cards support at most six items")
    if n <= 3:
        y = 189
        step = 230 if n == 3 else 310
        height = step - 30
        for i, item in enumerate(lines):
            d.rounded_rectangle((70, y, 1848, y + height), radius=20, fill=PANEL)
            d.text((100, y + 34), f"{i + 1:02d}", font=font(33, True, True), fill=CYAN)
            label, detail = item_text(item)
            bottom = paragraph(d, label, (196, y + 25), 1590, size=38, bold=True, spacing=10)
            if detail:
                paragraph(d, detail, (198, bottom + 15), 1578, size=29, color=MUTED, spacing=10)
            y += step
    else:
        rows = math.ceil(n / 2)
        row_h = 728 // rows
        for i, item in enumerate(lines):
            x = 70 + (i % 2) * 904
            y = 181 + (i // 2) * row_h
            d.rounded_rectangle((x, y, x + 878, y + row_h - 26), radius=18, fill=PANEL)
            d.text((x + 26, y + 19), f"{i + 1:02d}", font=font(22, True, True), fill=CYAN)
            label, detail = item_text(item)
            bottom = paragraph(d, label, (x + 26, y + 59), 826, size=32, bold=True, spacing=10)
            if detail:
                paragraph(d, detail, (x + 26, bottom + 11), 826, size=26, color=MUTED, spacing=8)


def syntax_line(draw, line, x, y, face):
    """Small language-independent token palette for honest, readable snippets."""
    tokens = re.split(r'(//.*$|#[^\n]*$|"[^"\n]*"|\b(?:fn|pub|extern|unsafe|return|void|int|float|double|const|let|use|struct|class|if|for|true|false|include)\b|\b\d+(?:\.\d+)?\b)', line)
    for token in tokens:
        if not token:
            continue
        color = INK
        if token.startswith("//") or token.startswith("#"):
            color = MUTED
        elif token.startswith('"'):
            color = AMBER
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            color = AMBER
        elif re.fullmatch(r"[a-z]+", token):
            color = CYAN
        draw.text((x, y), token, font=face, fill=color)
        x += draw.textlength(token, font=face)


def draw_code(d, scene):
    code = scene.get("code", [])
    if isinstance(code, str):
        code = code.strip("\n").splitlines()
    side = scene.get("lines", scene.get("callouts", []))
    panel_w = 1322 if side else 1778
    d.rounded_rectangle((70, 172, 70 + panel_w, 926), radius=20, fill="#0c1524", outline=LINE, width=2)
    d.text((99, 192), scene.get("filename", scene.get("language", "SOURCE EXCERPT")), font=font(22, mono=True), fill=CYAN)
    d.line((96, 237, 70 + panel_w - 26, 237), fill=LINE, width=2)
    max_line = max((len(s) for s in code), default=1)
    text_size = min(30, int((panel_w - 145) / max(1, max_line) / .61))
    text_size = max(19, min(text_size, int(644 / max(1, len(code))) - 8))
    face = font(text_size, mono=True)
    y = 260
    line_start = int(scene.get("line_start", 1))
    highlighted = set(int(value) for value in scene.get("highlight_lines", []))
    for n, line in enumerate(code):
        if d.textlength(line, font=face) > panel_w - 145:
            raise ValueError(f"{scene['id']}: code line {n + 1} is too long")
        number = line_start + n
        if number in highlighted:
            d.rounded_rectangle((91, y - 3, 70 + panel_w - 20, y + text_size + 7), radius=4, fill="#193940")
        d.text((100, y + 2), f"{number:02d}", font=font(text_size - 3, mono=True), fill=CYAN if number in highlighted else "#657c93")
        syntax_line(d, line, 157, y, face)
        y += text_size + 13
    if y > 932:
        raise ValueError(f"{scene['id']}: code has too many lines")
    if side:
        sidebar(d, side, 1440, 204, 408, label=scene.get("sidebar_title", "WHAT CHANGES"))


def sidebar(d, items, x, y, width, label="ON SCREEN"):
    d.text((x, y), label, font=font(18, True), fill=CYAN)
    y += 56
    for item in items:
        label_text, detail = item_text(item)
        d.ellipse((x, y + 10, x + 9, y + 19), fill=CYAN)
        y = paragraph(d, label_text, (x + 27, y), width - 27, size=28, bold=True, spacing=8)
        if detail:
            y = paragraph(d, detail, (x + 27, y + 11), width - 27, size=23, color=MUTED, spacing=7)
        y += 45
    if y > 968:
        raise ValueError("Sidebar text exceeds the available height; shorten its bullets")


def native_geometry(scene, info):
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    width, height = int(stream["width"]), int(stream["height"])
    crop = native_options(scene).get("crop")
    if crop:
        if isinstance(crop, dict):
            crop = [crop["x"], crop["y"], crop["width"], crop["height"]]
        if len(crop) != 4:
            raise ValueError(f"{scene['id']}: crop is [x,y,width,height]")
        x, y, crop_width, crop_height = map(int, crop)
        if min(x, y) < 0 or min(crop_width, crop_height) <= 0 or x + crop_width > width or y + crop_height > height:
            raise ValueError(f"{scene['id']}: crop exceeds the native source")
        width, height = crop_width, crop_height
    max_w = 1410 if scene.get("callouts", scene.get("lines")) else 1824
    max_h = 804
    ratio = min(max_w / width, max_h / height)
    target_w = int(width * ratio) // 2 * 2
    target_h = int(height * ratio) // 2 * 2
    x = 48 + (max_w - target_w) // 2
    y = 148 + (max_h - target_h) // 2
    return x, y, target_w, target_h


def crop_filter(scene):
    crop = native_options(scene).get("crop")
    if not crop:
        return ""
    if isinstance(crop, dict):
        crop = [crop["x"], crop["y"], crop["width"], crop["height"]]
    x, y, width, height = map(int, crop)
    return f"crop={width}:{height}:{x}:{y},"


def draw_flow(d, scene):
    nodes = scene.get("nodes")
    if not nodes:
        nodes = [dict(id=str(i), label=item_text(item)[0], detail=item_text(item)[1]) for i, item in enumerate(scene.get("lines", []))]
    if not nodes or len(nodes) > 6:
        raise ValueError(f"{scene['id']}: flow requires one to six nodes")
    count = len(nodes)
    cols = count if count <= 4 else 3
    rows = math.ceil(count / cols)
    box_w = 390 if cols == 4 else 510
    box_h = 228
    gap = 54 if cols == 4 else 85
    left = (W - (cols * box_w + (cols - 1) * gap)) // 2
    top = 278 if rows == 1 else 205
    positions = {}
    for n, node in enumerate(nodes):
        x = left + (n % cols) * (box_w + gap)
        y = top + (n // cols) * 355
        positions[node["id"]] = (x, y)
    edges = scene.get("edges", [[nodes[n]["id"], nodes[n + 1]["id"]] for n in range(count - 1)])
    for source, target in edges:
        ax, ay = positions[source]
        bx, by = positions[target]
        if ay == by:
            a, b = (ax + box_w, ay + box_h // 2), (bx - 12, by + box_h // 2)
            d.line((a, b), fill=CYAN, width=5)
            d.polygon([(b[0], b[1]), (b[0] - 17, b[1] - 11), (b[0] - 17, b[1] + 11)], fill=CYAN)
        else:
            a, b = (ax + box_w // 2, ay + box_h), (bx + box_w // 2, by - 12)
            midway = (a[1] + b[1]) // 2
            d.line((a, (a[0], midway), (b[0], midway), b), fill=CYAN, width=4)
            d.polygon([(b[0], b[1]), (b[0] - 11, b[1] - 17), (b[0] + 11, b[1] - 17)], fill=CYAN)
    for n, node in enumerate(nodes):
        x, y = positions[node["id"]]
        d.rounded_rectangle((x, y, x + box_w, y + box_h), radius=20, fill=PANEL, outline=LINE, width=2)
        d.text((x + 24, y + 18), f"{n + 1:02d}", font=font(19, True, True), fill=CYAN)
        bottom = paragraph(d, node["label"], (x + 24, y + 55), box_w - 48, size=31, bold=True, spacing=10)
        if node.get("detail"):
            paragraph(d, node["detail"], (x + 24, bottom + 11), box_w - 48, size=24, color=MUTED, spacing=8)
    if scene.get("note"):
        paragraph(d, scene["note"], (85, 830), 1750, size=28, color=MUTED)
    elif scene.get("nodes") and scene.get("lines"):
        paragraph(d, "\n".join(str(line) for line in scene["lines"]), (85, 810), 1750, size=28, color=MUTED)


def base_image(scene, index, count, story_title, native_info=None):
    image = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(image)
    header(image, scene, index, count, story_title)
    kind = scene["kind"]
    if kind == "title":
        draw_title(d, scene)
    elif kind == "code":
        draw_code(d, scene)
    elif kind == "flow":
        draw_flow(d, scene)
    elif kind in ("filemap", "filefocus", "delivery"):
        draw = {"filemap": draw_filemap, "filefocus": draw_filefocus, "delivery": draw_delivery}[kind]
        draw(d, scene, font=font, paragraph=paragraph, syntax_line=syntax_line)
    elif kind == "native":
        if native_info is None:
            raise ValueError(f"{scene['id']}: native scene requires a video")
        x, y, width, height = native_geometry(scene, native_info)
        d.rectangle((x - 2, y - 2, x + width + 2, y + height + 2), outline=LINE, width=2)
        items = scene.get("callouts", scene.get("lines", []))
        if items:
            d.line((1477, 169, 1477, 924), fill=LINE, width=2)
            sidebar(d, items, 1507, 174, 342, scene.get("sidebar_title", "ON SCREEN"))
    else:
        draw_card(d, scene)
    return image


def stamp(seconds, srt=False):
    millis = round(seconds * 1000)
    separator = "," if srt else "."
    return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02}{separator}{millis % 1000:03}"


def ass_stamp(seconds):
    centis = round(seconds * 100)
    return f"{centis // 360000}:{centis // 6000 % 60:02}:{centis // 100 % 60:02}.{centis % 100:02}"


def ass_text(value):
    return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def captions_ass(path, scene):
    result = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,28,&H00E7F1F4,&H00E7F1F4,&H0023140A,&H0023140A,0,0,0,0,100,100,0,0,1,1,0,2,110,110,25,1
Style: Cue,DejaVu Sans,23,&H00DFDD65,&H00DFDD65,&H002D1B10,&H002D1B10,-1,0,0,0,100,100,0,0,1,1,0,7,1510,45,840,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for caption in scene["captions"]:
        result += f"Dialogue: 0,{ass_stamp(caption['start'])},{ass_stamp(caption['end'])},Caption,,0,0,0,,{ass_text(caption['text'])}\n"
    cues = scene.get("cues", [])
    for index, cue in enumerate(cues):
        end = cues[index + 1]["at"] if index + 1 < len(cues) else scene["duration"]
        result += f"Dialogue: 1,{ass_stamp(cue['at'])},{ass_stamp(end)},Cue,,0,0,0,,{ass_text(cue['text'])}\n"
    path.write_text(result)


def filter_path(path):
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")


def prepare_speech(story, model, out, fps, length_scale):
    from piper import PiperVoice, SynthesisConfig
    import onnxruntime

    onnxruntime.disable_telemetry_events()
    voice = PiperVoice.load(str(model))
    rate = voice.config.sample_rate
    config = SynthesisConfig(length_scale=length_scale)
    model_config = model.with_name(model.name + ".json")
    model_hash = sha(model)
    voice_identity = model_hash + sha(model_config)
    voice_identity += importlib.metadata.version("piper-tts")
    speech_dir = out / "speech"
    speech_dir.mkdir(exist_ok=True)
    cursor = 0.0
    audio = bytearray()
    timeline, all_captions = [], []
    for original in story["scenes"]:
        scene = dict(original)
        segment = bytearray(round(rate * .28) * 2)
        captions = []
        for index, sentence in enumerate(scene["sentences"]):
            cues = scene.get("cue_times", [])
            if index < len(cues):
                segment.extend(bytes(max(0, round(cues[index] * rate) * 2 - len(segment))))
            digest = hashlib.sha256(f"{voice_identity}|{length_scale}|{sentence}".encode()).hexdigest()
            sentence_path = speech_dir / (digest[:24] + ".wav")
            if not sentence_path.exists():
                pending_speech = sentence_path.with_suffix(".encoding.wav")
                with wave.open(str(pending_speech), "wb") as writer:
                    voice.synthesize_wav(sentence, writer, syn_config=config)
                pending_speech.replace(sentence_path)
            with wave.open(str(sentence_path), "rb") as reader:
                if reader.getnchannels() != 1 or reader.getframerate() != rate or reader.getsampwidth() != 2:
                    raise ValueError("Cached speech has an incompatible audio format")
                data = reader.readframes(reader.getnframes())
            start = len(segment) / (rate * 2)
            segment.extend(data)
            end = len(segment) / (rate * 2)
            captions.append(dict(start=start, end=end, text=sentence))
            segment.extend(bytes(round(rate * .36) * 2))
        duration = math.ceil(max(scene.get("minimum", 0), len(segment) / (rate * 2) + .48) * fps) / fps
        scene.update(start=cursor, duration=duration, captions=captions)
        segment.extend(bytes(max(0, round((cursor + duration) * rate) * 2 - len(audio) - len(segment))))
        audio.extend(segment)
        timeline.append(scene)
        all_captions.extend(dict(c, start=c["start"] + cursor, end=c["end"] + cursor) for c in captions)
        cursor += duration
        print(f"Prepared {scene['id']}: {duration:.2f} seconds", flush=True)
    with wave.open(str(out / "narration.wav"), "wb") as writer:
        writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(audio)
    return timeline, all_captions, cursor, model_hash


def write_text_outputs(story, timeline, captions, out):
    (out / "timeline.json").write_text(json.dumps(timeline, indent=2) + "\n")
    (out / "captions.vtt").write_text("WEBVTT\n\n" + "".join(f"{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}\n\n" for c in captions))
    (out / "captions.srt").write_text("".join(f"{n + 1}\n{stamp(c['start'], True)} --> {stamp(c['end'], True)}\n{c['text']}\n\n" for n, c in enumerate(captions)))
    script = story["title"] + "\n\n"
    for scene in timeline:
        script += f"{stamp(scene['start'])} — {scene['title']}\n" + "\n".join(scene["sentences"]) + "\n\n"
    (out / "script.txt").write_text(script)
    metadata = ";FFMETADATA1\ntitle=" + story["title"].replace("=", "\\=").replace("\n", " ") + "\n"
    for scene in timeline:
        title = scene["title"].replace("=", "\\=").replace("\n", " ")
        metadata += f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(scene['start'] * 1000)}\nEND={round((scene['start'] + scene['duration']) * 1000)}\ntitle={title}\n"
    (out / "chapters.txt").write_text(metadata)


def preview_scene(ffmpeg, scene, base, info, path):
    image = base.copy()
    native = media_path(scene)
    if native:
        x, y, width, height = native_geometry(scene, info)
        source_duration = float(info["format"]["duration"])
        options = native_options(scene)
        rate = float(options.get("rate", 1))
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError(f"{scene['id']}: native rate must be positive and finite")
        stop = min(float(options.get("trim_end", source_duration)), source_duration)
        seek = min(float(options.get("trim_start", 0)) + scene["duration"] * rate / 2, max(0, stop - .15))
        frame = subprocess.check_output([str(ffmpeg), "-v", "error", "-ss", str(seek), "-i", str(native), "-frames:v", "1", "-vf", crop_filter(scene) + f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        if len(frame) != width * height * 3:
            raise RuntimeError(f"Could not obtain a preview frame from {native}")
        image.paste(Image.frombytes("RGB", (width, height), frame), (x, y))
    if scene.get("captions"):
        caption = scene["captions"][len(scene["captions"]) // 2]["text"]
        d = ImageDraw.Draw(image)
        face = font(28)
        lines = fit_lines(d, caption, face, 1700)
        if len(lines) > 2:
            face = font(25)
            lines = fit_lines(d, caption, face, 1700)
        y = 1012 if len(lines) > 1 else 1024
        for line in lines[:2]:
            d.text((W // 2, y), line, font=face, fill=INK, anchor="mt")
            y += 32
    image.save(path)


def encode_scene(args, scene, base_path, ass_path, segment, info):
    command = [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(args.fps), "-i", base_path]
    native = media_path(scene)
    if native:
        options = native_options(scene)
        start = float(options.get("trim_start", 0))
        source_duration = float(info["format"]["duration"])
        stop = min(float(options.get("trim_end", source_duration)), source_duration)
        rate = float(options.get("rate", 1))
        pad_seconds = float(options.get("pad_seconds", scene["duration"]))
        if not all(math.isfinite(x) for x in (start, stop, rate, pad_seconds)) or start < 0 or stop <= start or rate <= 0 or pad_seconds < 0:
            raise ValueError(f"{scene['id']}: native trim is empty")
        command += ["-ss", str(start), "-t", str(stop - start), "-i", native]
        x, y, width, height = native_geometry(scene, info)
        filters = f"[1:v]{crop_filter(scene)}setpts=(PTS-STARTPTS)/{rate},fps={args.fps},scale={width}:{height}:flags=lanczos,tpad=stop_mode=clone:stop_duration={pad_seconds}[footage];[0:v][footage]overlay={x}:{y}:eof_action=repeat,ass=filename='{filter_path(ass_path)}':fontsdir='{filter_path(FONT_DIR)}'[picture]"
    else:
        filters = f"[0:v]ass=filename='{filter_path(ass_path)}':fontsdir='{filter_path(FONT_DIR)}'[picture]"
    command += ["-filter_complex", filters, "-map", "[picture]", "-an", "-t", str(scene["duration"]), "-r", str(args.fps), "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf), "-maxrate", args.maxrate, "-bufsize", "3600k", "-threads", "4", "-pix_fmt", "yuv420p", "-video_track_timescale", "20000", segment]
    run(command)


def main():
    global FONT_DIR, MEDIA_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=PROJECT / "assets/voices/en_US-ljspeech-medium.onnx")
    parser.add_argument("--font-dir", type=Path, default=FONT_DIR)
    parser.add_argument("--media-root", type=Path, default=PROJECT)
    parser.add_argument("--ffmpeg", type=Path, default=Path("ffmpeg"))
    parser.add_argument("--ffprobe", type=Path, default=Path("ffprobe"))
    parser.add_argument("--length-scale", type=float, default=.98)
    parser.add_argument("--crf", type=int, default=24)
    parser.add_argument("--maxrate", default="1800k")
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--size-limit-mb", type=float, default=80)
    parser.add_argument("--previews-only", action="store_true")
    parser.add_argument("--narration-only", action="store_true")
    args = parser.parse_args()
    FONT_DIR = args.font_dir.resolve()
    MEDIA_ROOT = args.media_root.resolve()
    story_bytes = args.story.read_bytes()
    story_digest = hashlib.sha256(story_bytes).hexdigest()
    story = json.loads(story_bytes)
    args.fps = int(story.get("fps", 20))
    if args.fps <= 0 or not story.get("scenes"):
        parser.error("A story requires positive fps and at least one scene")
    ids = [scene["id"] for scene in story["scenes"]]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in ids):
        parser.error("Scene IDs must be unique and contain only letters, numbers, underscore or hyphen")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "previews").mkdir(exist_ok=True)
    work = out / "work"
    work.mkdir(exist_ok=True)
    if args.previews_only:
        timeline = [dict(s, duration=s.get("minimum", 20), captions=[dict(text=s.get("sentences", [""])[0])]) for s in story["scenes"]]
        captions, duration, model_hash = [], 0, ""
    else:
        timeline, captions, duration, model_hash = prepare_speech(story, args.model, out, args.fps, args.length_scale)
        write_text_outputs(story, timeline, captions, out)
    if args.narration_only:
        return
    segments = []
    # Freeze the exact renderer and retained font bytes used by this run. A
    # scene cache may survive edits, but cannot reuse a previous visual layout.
    renderer_inputs = [Path(__file__), Path(__file__).with_name("file_visuals.py")]
    renderer_inputs += sorted(FONT_DIR.glob("*.ttf"))
    renderer_hash = hashlib.sha256("".join(path.name + sha(path) for path in renderer_inputs).encode()).hexdigest()
    encoder_identity = "" if args.previews_only else hashlib.sha256(subprocess.check_output([str(args.ffmpeg), "-version"])).hexdigest()
    native_records = []
    for index, scene in enumerate(timeline):
        native = media_path(scene)
        info = probe(args.ffprobe, native) if native else None
        native_hash = sha(native) if native else ""
        if native:
            source_name = str(native.relative_to(MEDIA_ROOT)) if native.is_relative_to(MEDIA_ROOT) else native.name
            native_records.append(dict(scene=scene["id"], file=source_name, sha256=native_hash))
        image = base_image(scene, index, len(timeline), story["title"], info)
        base_path = work / (scene["id"] + "-base.png")
        image.save(base_path)
        preview_scene(args.ffmpeg, scene, image, info, out / "previews" / (f"{index + 1:02}-" + scene["id"] + ".png"))
        if args.previews_only:
            continue
        ass_path = work / (scene["id"] + ".ass")
        captions_ass(ass_path, scene)
        segment = work / (scene["id"] + ".mp4")
        key = hashlib.sha256((json.dumps(scene, sort_keys=True) + sha(base_path) + sha(ass_path) + native_hash + renderer_hash + encoder_identity + str(args.crf) + args.maxrate + args.preset + str(args.fps)).encode()).hexdigest()
        key_path = work / (scene["id"] + ".key")
        if not segment.exists() or not key_path.exists() or key_path.read_text() != key:
            # An interrupted encode never replaces a known-complete cached
            # segment, even if a prior key survives from a missing segment.
            pending_segment = work / (scene["id"] + ".encoding.mp4")
            encode_scene(args, scene, base_path, ass_path, pending_segment, info)
            pending_segment.replace(segment)
            pending_key = key_path.with_suffix(".pending-key")
            pending_key.write_text(key)
            pending_key.replace(key_path)
        segments.append(segment)
        print(f"Rendered {scene['id']}", flush=True)
    if args.previews_only:
        print(f"Previews saved to {out / 'previews'}", flush=True)
        return
    normalized = out / "narration-normalized.wav"
    audio_process = subprocess.run([str(args.ffmpeg), "-hide_banner", "-y", "-i", str(out / "narration.wav"), "-af", "loudnorm=I=-18:TP=-3:LRA=11:print_format=json", "-ar", "48000", "-ac", "1", str(normalized)], text=True, capture_output=True)
    (out / "audio-report.txt").write_text(audio_process.stderr)
    audio_process.check_returncode()
    concat = work / "segments.ffconcat"
    concat.write_text("ffconcat version 1.0\n" + "".join("file '" + str(path).replace("'", "'\\''") + "'\n" for path in segments))
    final = out / "film.encoding.mp4"
    run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-i", normalized, "-i", out / "chapters.txt", "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "2", "-map_chapters", "2", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "1", "-t", str(duration), "-movflags", "+faststart", final])
    decode = subprocess.run([str(args.ffmpeg), "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode", "-i", str(final), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], capture_output=True, text=True)
    (out / "decode-report.txt").write_text(decode.stderr or ("Complete audio and video decode passed.\n" if decode.returncode == 0 else f"Decode failed with exit {decode.returncode}.\n"))
    decode.check_returncode()
    info = probe(args.ffprobe, final)
    chapters = info.get("chapters", [])
    if len(chapters) != len(timeline):
        raise RuntimeError("The final video does not contain all scene chapters")
    for chapter, scene in zip(chapters, timeline):
        if chapter.get("tags", {}).get("title") != scene["title"] or abs(float(chapter["start_time"]) - scene["start"]) > .002 or abs(float(chapter["end_time"]) - scene["start"] - scene["duration"]) > .002:
            raise RuntimeError(f"The final chapter disagrees with scene {scene['id']}")
    final = final.replace(out / "film.mp4")
    info["format"]["filename"] = str(final)
    (out / "probe.json").write_text(json.dumps(info, indent=2) + "\n")
    with wave.open(str(normalized), "rb") as reader:
        samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32) / 32768
    delivery = dict(title=story["title"], duration_seconds=duration, bytes=final.stat().st_size, sha256=sha(final), voice_model_sha256=model_hash, story_sha256=story_digest, renderer_sha256=renderer_hash, encoder_sha256=encoder_identity, resolution=[W, H], frames_per_second=args.fps, captions=len(captions), chapters=len(timeline), audio_peak_dbfs=float(20 * np.log10(max(1e-9, np.max(np.abs(samples))))), complete_decode_passed=True)
    if native_records:
        delivery["native_sources"] = native_records
    (out / "delivery.json").write_text(json.dumps(delivery, indent=2) + "\n")
    digest_paths = [final, out / "captions.vtt", out / "captions.srt", out / "chapters.txt", out / "script.txt", out / "timeline.json", out / "delivery.json"]
    (out / "SHA256SUMS").write_text("".join(sha(path) + "  " + path.name + "\n" for path in digest_paths))
    print("Finished " + json.dumps(delivery), flush=True)
    if delivery["bytes"] > args.size_limit_mb * 1_000_000:
        raise RuntimeError(f"Film exceeds the configured {args.size_limit_mb:g} MB size budget; it remains available for review")


if __name__ == "__main__":
    main()
