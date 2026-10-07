"""Readable maps from a development task to its ordinary source file.

These diagrams intentionally show a small, useful working set. Every displayed
path is kept verbatim, including when wrapped across two lines.
"""
from __future__ import annotations

import re


BG = "#101b2d"
PANEL = "#19283e"
INK = "#f4f1e7"
MUTED = "#b3c2ce"
CYAN = "#65dddf"
LINE = "#344b62"
AMBER = "#ffcd89"
VIOLET = "#beb2ef"


def _label(d, value, xy, *, font, size=20, color=CYAN):
    d.text(xy, str(value).upper(), font=font(size, True), fill=color)


def _path_lines(d, value, face, width):
    """Wrap paths at separators without losing or abbreviating their bytes."""
    parts = re.findall(r"[^/]+/?", str(value))
    lines, current = [], ""
    for part in parts:
        candidate = current + part
        if current and d.textlength(candidate, font=face) > width:
            lines.append(current)
            current = part
        else:
            current = candidate
        if d.textlength(current, font=face) > width:
            raise ValueError(f"Path component is too wide to display: {part}")
    if current:
        lines.append(current)
    return lines or [""]


def path_text(d, value, xy, width, *, font, size=25, color=INK, max_lines=2):
    face = font(size, mono=True)
    lines = _path_lines(d, value, face, width)
    if len(lines) > max_lines:
        raise ValueError(f"Path needs more than {max_lines} lines: {value}")
    x, y = xy
    for line in lines:
        d.text((x, y), line, font=face, fill=color)
        y += size + 8
    return y


def _bounded_paragraph(d, value, xy, width, bottom, *, paragraph, **kwargs):
    end = paragraph(d, value, xy, width, **kwargs)
    if end > bottom:
        raise ValueError(f"Text exceeds its visual card: {value}")
    return end


def draw_filemap(d, scene, *, font, paragraph, syntax_line=None):
    rows = scene.get("rows", scene.get("files", []))
    if not rows or len(rows) > 4:
        raise ValueError(f"{scene['id']}: filemap requires one to four rows")
    if scene.get("subtitle"):
        _bounded_paragraph(d, scene["subtitle"], (72, 150), 1765, 191 if scene.get("path_prefix") else 214,
                           paragraph=paragraph, size=28, color=MUTED, spacing=7)
    if scene.get("path_prefix"):
        _label(d, "Project folder", (73, 203), font=font, size=17)
        path_text(d, scene["path_prefix"], (256, 196), 1592, font=font,
                  size=25, color=AMBER, max_lines=1)
    columns = (100, 575, 1310)
    _label(d, "What you want to change", (columns[0], 237), font=font, size=18)
    _label(d, "Open this file", (columns[1], 237), font=font, size=18)
    _label(d, "Its responsibility", (columns[2], 237), font=font, size=18)
    row_h = 126 if len(rows) == 4 else 158
    for index, row in enumerate(rows):
        y = 276 + index * (row_h + 14)
        bottom = y + row_h
        color = row.get("color", {"algorithm": CYAN, "application": CYAN,
                    "events": AMBER, "generated": VIOLET, "visual": VIOLET,
                    "retained": MUTED, "infrastructure": MUTED}.get(row.get("layer"), CYAN))
        d.rounded_rectangle((72, y, 1848, bottom), radius=18, fill=PANEL)
        d.rounded_rectangle((72, y, 81, bottom), radius=4, fill=color)
        _bounded_paragraph(d, row.get("task", row.get("label", "")),
                           (100, y + 22), 414, bottom - 12, paragraph=paragraph,
                           size=29, bold=True, spacing=8)
        d.line((536, y + 28, 558, y + 28), fill=color, width=3)
        d.polygon(((558, y + 28), (550, y + 22), (550, y + 34)), fill=color)
        path_text(d, row.get("path", row.get("filename", "")),
                  (575, y + 23), 693, font=font, size=24, color=color,
                  max_lines=3 if len(rows) < 4 else 2)
        _bounded_paragraph(d, row.get("role", row.get("detail", "")),
                           (1310, y + 24), 500, bottom - 12, paragraph=paragraph,
                           size=25, color=MUTED, spacing=7)
    y = 276 + len(rows) * (row_h + 14) + 7
    layers = scene.get("layers", [])
    if layers:
        if len(layers) > 4:
            raise ValueError(f"{scene['id']}: filemap supports at most four layers")
        gap = 18
        width = (1776 - gap * (len(layers) - 1)) // len(layers)
        for index, layer in enumerate(layers):
            x = 72 + index * (width + gap)
            color = layer.get("color", (CYAN, AMBER, VIOLET, MUTED)[index]) if isinstance(layer, dict) else (CYAN, AMBER, VIOLET, MUTED)[index]
            d.rounded_rectangle((x, y, x + width, min(y + 95, 928)), radius=15,
                                fill="#132136", outline=LINE, width=1)
            label = layer.get("label", "") if isinstance(layer, dict) else layer
            detail = layer.get("detail", "") if isinstance(layer, dict) else ""
            _bounded_paragraph(d, label, (x + 17, y + 13), width - 34, y + 50,
                               paragraph=paragraph, size=21, bold=True, spacing=6, color=color)
            if detail:
                _bounded_paragraph(d, detail, (x + 17, y + 49), width - 34, 929,
                                   paragraph=paragraph, size=17, color=MUTED, spacing=5)
    elif scene.get("note"):
        _bounded_paragraph(d, scene["note"], (88, max(y + 15, 868)), 1730, 939,
                           paragraph=paragraph, size=26, color=MUTED, spacing=8)


def draw_filefocus(d, scene, *, font, paragraph, syntax_line):
    filename = scene.get("filename", scene.get("path", ""))
    if not filename:
        raise ValueError(f"{scene['id']}: filefocus requires a filename")
    _label(d, "Open this file", (72, 158), font=font, size=18)
    end = path_text(d, filename, (72, 191), 1745, font=font, size=28,
                    color=CYAN, max_lines=2)
    code = scene.get("code", [])
    if isinstance(code, str):
        code = code.strip("\n").splitlines()
    if not code or len(code) > 13:
        raise ValueError(f"{scene['id']}: filefocus requires one to thirteen source lines")
    top = max(248, end + 12)
    code_bottom = 794
    d.rounded_rectangle((72, top, 1367, code_bottom), radius=19, fill="#0c1524",
                        outline=LINE, width=2)
    focus = scene.get("function", scene.get("focus", "Selected source excerpt"))
    _bounded_paragraph(d, focus, (98, top + 17), 1210, top + 65,
                       paragraph=paragraph, size=23, color=MUTED, spacing=5)
    d.line((98, top + 65, 1341, top + 65), fill=LINE, width=1)
    start = int(scene.get("line_start", 1))
    highlighted = set(int(value) for value in scene.get("highlight_lines", []))
    code_top = top + 89
    size = min(33, int((code_bottom - code_top - 18) / len(code)) - 9)
    while size >= 23:
        face = font(size, mono=True)
        if max(d.textlength(line, font=face) for line in code) <= 1154:
            break
        size -= 1
    if size < 23:
        raise ValueError(f"{scene['id']}: source is too dense; use a shorter excerpt")
    face = font(size, mono=True)
    spacing = size + 9
    for index, line in enumerate(code):
        y = code_top + index * spacing
        line_number = start + index
        if line_number in highlighted:
            d.rounded_rectangle((89, y - 3, 1350, y + size + 6), radius=5,
                                fill="#193940")
            d.rectangle((76, y - 3, 79, y + size + 6), fill=CYAN)
        d.text((114, y + 2), str(line_number), font=font(size - 5, mono=True),
               fill=CYAN if line_number in highlighted else "#657c93", anchor="ra")
        syntax_line(d, line, 144, y, face)
    x = 1410
    _label(d, scene.get("sidebar_title", "Neighboring files"), (x, top + 7),
           font=font, size=18)
    siblings = scene.get("siblings", [])
    if len(siblings) > 3:
        raise ValueError(f"{scene['id']}: filefocus supports at most three neighboring files")
    y = top + 45
    for item in siblings:
        path = item.get("path", item.get("filename", ""))
        y = path_text(d, path, (x, y), 438, font=font, size=20,
                      color=AMBER, max_lines=3)
        y = _bounded_paragraph(d, item.get("role", item.get("detail", "")),
                               (x, y + 8), 432, 802, paragraph=paragraph,
                               size=22, color=MUTED, spacing=7)
        d.line((x, y + 14, 1847, y + 14), fill=LINE, width=1)
        y += 40
    if not siblings and scene.get("lines"):
        for item in scene["lines"][:3]:
            label, _, detail = str(item).partition(" | ")
            y = _bounded_paragraph(d, label, (x, y), 432, 802,
                                   paragraph=paragraph, size=25, bold=True, spacing=7)
            if detail:
                y = _bounded_paragraph(d, detail, (x, y + 9), 432, 802,
                                       paragraph=paragraph, size=22, color=MUTED, spacing=7)
            y += 35
    io = scene.get("io")
    if io:
        y = 817
        d.rounded_rectangle((72, y, 1848, 884), radius=15, fill=PANEL)
        _label(d, "Input", (94, y + 20), font=font, size=17)
        _bounded_paragraph(d, io.get("input", ""), (173, y + 16), 697, 878,
                           paragraph=paragraph, size=24, spacing=6)
        d.line((888, y + 32, 960, y + 32), fill=CYAN, width=4)
        d.polygon(((960, y + 32), (947, y + 24), (947, y + 40)), fill=CYAN)
        _label(d, "Output", (990, y + 20), font=font, size=17)
        _bounded_paragraph(d, io.get("output", ""), (1092, y + 16), 722, 878,
                           paragraph=paragraph, size=24, spacing=6)
    if scene.get("change", scene.get("note")):
        _bounded_paragraph(d, scene.get("change", scene.get("note")), (88, 903),
                           1740, 942, paragraph=paragraph, size=23, color=MUTED, spacing=7)


def draw_delivery(d, scene, *, font, paragraph, syntax_line=None):
    steps = scene.get("steps", scene.get("nodes", []))
    if not 2 <= len(steps) <= 4:
        raise ValueError(f"{scene['id']}: delivery requires two to four steps")
    subtitle = scene.get("subtitle", "One project. A release your package manager can use.")
    _bounded_paragraph(d, subtitle, (72, 164), 1740, 232,
                       paragraph=paragraph, size=32, color=MUTED, spacing=9)
    gap = 47
    width = (1776 - gap * (len(steps) - 1)) // len(steps)
    for index, step in enumerate(steps):
        x, y = 72 + index * (width + gap), 289
        d.rounded_rectangle((x, y, x + width, 693), radius=22, fill=PANEL,
                            outline=LINE, width=2)
        d.text((x + 24, y + 22), f"{index + 1:02d}", font=font(21, True, True), fill=CYAN)
        end = _bounded_paragraph(d, step.get("label", step.get("title", "")),
                                 (x + 24, y + 70), width - 48, y + 183,
                                 paragraph=paragraph, size=31, bold=True, spacing=10)
        if step.get("path"):
            end = path_text(d, step["path"], (x + 24, end + 20), width - 48,
                            font=font, size=20, color=AMBER, max_lines=4)
        _bounded_paragraph(d, step.get("detail", ""), (x + 24, end + 24),
                           width - 48, 683, paragraph=paragraph, size=23,
                           color=MUTED, spacing=8)
        if index + 1 < len(steps):
            mid = y + 202
            d.line((x + width + 8, mid, x + width + gap - 8, mid), fill=CYAN, width=4)
            d.polygon(((x + width + gap - 8, mid), (x + width + gap - 19, mid - 8),
                       (x + width + gap - 19, mid + 8)), fill=CYAN)
    managers = scene.get("package_managers", [])
    if managers:
        _label(d, "The user's OS fetches the CI-built packages", (88, 743), font=font, size=22)
        paragraph(d, "  •  ".join(managers), (88, 786), 1735, size=31, color=INK,
                  bold=True, spacing=9)
    if scene.get("note"):
        _bounded_paragraph(d, scene["note"], (88, 863), 1735, 941,
                           paragraph=paragraph, size=27, color=MUTED, spacing=9)
