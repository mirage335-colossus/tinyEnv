"""Printable navigation handbooks for the manually generated source map.

This renderer reads an already collected model. It never invokes a compiler,
loads project code, or writes to the source tree. ReportLab is an optional
dependency until ``render_pdfs`` is explicitly called.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape
import re
import unicodedata


VOLUMES = (
    ("00-start-here.pdf", "Start here", "overview"),
    ("01-toolchain.pdf", "Compiler and toolchain", "build"),
    ("02-core.pdf", "Core and runtime", "core"),
    ("03-gui.pdf", "Graphical interface", "gui"),
    ("04-tools.pdf", "Developer tools", "tools"),
    ("05-tests.pdf", "Tests and examples", "tests"),
)


def _plain(value: Any) -> str:
    """Keep built-in PDF fonts reliable, including for unusual identifiers."""
    text = str(value if value is not None else "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return unicodedata.normalize("NFKD", text).encode("ascii", "backslashreplace").decode("ascii")


def _escape(value: Any) -> str:
    return escape(_plain(value), {'"': "&quot;"})


def _clip(value: Any, size: int) -> str:
    value = _plain(value)
    if len(value) <= size:
        return value
    return value[:size].rstrip() + f" ... (+{len(value) - size} chars)"


def _url(kind: str, item_id: Any, line: int | None = None) -> str:
    suffix = f"/{line}" if line is not None else ""
    return "../index.html#" + kind + "/" + quote(str(item_id), safe="") + suffix


def _anchor(prefix: str, value: Any) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9_-]", "_", str(value))


def _line(symbol: dict[str, Any]) -> str:
    first = symbol.get("line", 1)
    last = symbol.get("end_line", first)
    return str(first) if first == last else f"{first}-{last}"


def _flow_rows(flow: list[dict[str, Any]], limit: int = 12) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    rows: list[tuple[int, dict[str, Any]]] = []

    def walk(nodes: Any, depth: int = 0) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            rows.append((depth, node))
            walk(node.get("children", []), depth + 1)

    walk(flow)
    return rows[:limit], max(0, len(rows) - limit)


def render_pdfs(model: dict[str, Any], output: Path) -> list[str]:
    """Write six linked PDFs under ``output/pdf`` and return relative paths.

    Collection and analysis happen elsewhere. Only declared build information
    and syntax-derived source information are rendered here. The output folder
    must be separate from the application source tree, as enforced by the CLI.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import (
            BaseDocTemplate, Flowable, Frame, KeepTogether, PageBreak,
            PageTemplate, Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise ImportError(
            "PDF output needs ReportLab in the documentation tool's Python "
            "environment. Install its requirements or run with --no-pdf."
        ) from exc

    output = Path(output)
    pdf_dir = output / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(model.get("files", []), key=lambda f: f.get("path", ""))
    generated = _plain(model.get("generated_at", "Unknown snapshot date"))
    date = generated.split("T", 1)[0].split(" ", 1)[0]
    title = _plain(model.get("title", "Software foundation"))
    page_width, page_height = letter
    margin = 48
    width = page_width - margin * 2
    ink = colors.HexColor("#18394b")
    accent = colors.HexColor("#176584")
    muted = colors.HexColor("#52616c")
    pale = colors.HexColor("#edf3f6")
    rule = colors.HexColor("#d3dee4")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BookTitle", fontName="Helvetica-Bold", fontSize=25,
                              leading=29, textColor=ink, spaceAfter=12))
    styles.add(ParagraphStyle("BookDeck", fontSize=11, leading=15, textColor=muted,
                              spaceAfter=12))
    styles.add(ParagraphStyle("Chapter", fontName="Helvetica-Bold", fontSize=16,
                              leading=20, textColor=ink, spaceBefore=14,
                              spaceAfter=9, keepWithNext=True))
    styles.add(ParagraphStyle("FileHeading", fontName="Helvetica-Bold", fontSize=11,
                              leading=14, textColor=ink, spaceBefore=13,
                              spaceAfter=6, keepWithNext=True))
    styles.add(ParagraphStyle("BookBody", fontSize=9, leading=12.5, textColor=ink,
                              spaceAfter=7, splitLongWords=True))
    styles.add(ParagraphStyle("SmallBody", fontSize=7.8, leading=10.4, textColor=muted,
                              spaceAfter=5, splitLongWords=True))
    styles.add(ParagraphStyle("Cell", fontSize=7.6, leading=10.1, textColor=ink,
                              spaceAfter=0, splitLongWords=True))
    styles.add(ParagraphStyle("CellSmall", fontSize=7, leading=9.1, textColor=muted,
                              spaceAfter=0, splitLongWords=True))
    styles.add(ParagraphStyle("CellHeader", fontName="Helvetica-Bold", fontSize=7.8,
                              leading=10, textColor=ink))
    styles.add(ParagraphStyle("Caption", fontSize=8, leading=10.5, textColor=muted,
                              spaceBefore=5, spaceAfter=9))
    styles.add(ParagraphStyle("CardTitle", fontName="Helvetica-Bold", fontSize=10,
                              leading=13, textColor=ink, spaceAfter=5))
    for style in styles.byName.values():
        style.alignment = TA_LEFT

    def p(value: Any, style: str = "BookBody", raw: bool = False) -> Any:
        return Paragraph(str(value) if raw else _escape(value), styles[style])

    def link(label: Any, destination: str) -> str:
        return f'<link href="{_escape(destination)}" color="#176584">{_escape(label)}</link>'

    styles.add(ParagraphStyle("InventoryCell", fontSize=7.2, leading=9.2, textColor=ink,
                              spaceAfter=0, splitLongWords=True))

    def table(rows: list[list[Any]], widths: list[float], headers: bool = True,
              dense: bool = False) -> Any:
        converted = []
        for index, row in enumerate(rows):
            converted.append([
                cell if not isinstance(cell, str) else p(cell, "CellHeader" if headers and index == 0 else "InventoryCell" if dense else "Cell", raw=True)
                for cell in row
            ])
        result = Table(converted, colWidths=widths, repeatRows=1 if headers else 0,
                       hAlign="LEFT", splitByRow=True)
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3 if dense else 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if dense else 5),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, rule),
        ]
        if headers:
            commands += [("BACKGROUND", (0, 0), (-1, 0), pale),
                         ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafb")])]
        result.setStyle(TableStyle(commands))
        return result

    class Heading(Paragraph):
        def __init__(self, text: str, destination: str, level: int, style: str) -> None:
            super().__init__(_escape(text), styles[style])
            self.destination = destination
            self.level = level
            self.outline_label = _plain(text)

    class BookDoc(BaseDocTemplate):
        def __init__(self, filename: Path, volume_title: str) -> None:
            super().__init__(str(filename), pagesize=letter, leftMargin=margin,
                             rightMargin=margin, topMargin=59, bottomMargin=53,
                             title=f"{title}: {volume_title}", author="Local source-map generator",
                             subject="Manually generated source-navigation snapshot")
            self.volume_title = volume_title
            self.filename_label = filename.name
            frame = Frame(margin, 53, width, page_height - 112,
                          leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
            self.addPageTemplates(PageTemplate(id="book", frames=[frame], onPage=self.decorate))

        def decorate(self, canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setStrokeColor(rule)
            canvas.setLineWidth(0.6)
            canvas.line(margin, page_height - 41, page_width - margin, page_height - 41)
            canvas.line(margin, 40, page_width - margin, 40)
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(ink)
            canvas.drawString(margin, page_height - 30, _clip(title, 52))
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(muted)
            canvas.drawRightString(page_width - margin, page_height - 30,
                                   f"{self.volume_title} | {date}")
            canvas.setFillColor(accent)
            canvas.drawString(margin, 27, "Up: Start here")
            canvas.linkURL("00-start-here.pdf", (margin, 24, margin + 70, 36), relative=1)
            canvas.drawString(margin + 94, 27, "Offline explorer")
            canvas.linkURL("../index.html", (margin + 94, 24, margin + 167, 36), relative=1)
            canvas.setFillColor(muted)
            canvas.drawRightString(page_width - margin, 27,
                                   f"{self.filename_label}  |  {doc.page}")
            canvas.restoreState()

        def afterFlowable(self, flowable: Any) -> None:
            if isinstance(flowable, Heading):
                self.canv.bookmarkPage(flowable.destination)
                self.canv.addOutlineEntry(flowable.outline_label, flowable.destination,
                                          level=flowable.level, closed=flowable.level > 0)

    class Diagram(Flowable):
        """A compact linked vector diagram, with no raster or network assets."""
        def __init__(self, nodes: list[dict[str, Any]], mode: str = "cards") -> None:
            super().__init__()
            self.nodes = nodes
            self.mode = mode
            self.width = width
            if mode == "flow":
                self.height = len(nodes) * 35 + 8
            elif mode == "build":
                self.height = max(1, len(nodes)) * 48 + 12
            else:
                self.height = 220

        def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
            return self.width, self.height

        def label(self, label: str, x: float, y: float, box_width: float,
                  size: float = 8.5, max_chars: int = 72) -> None:
            para = Paragraph(_escape(_clip(label, max_chars)), ParagraphStyle(
                "diagram-label", fontName="Helvetica", fontSize=size,
                leading=size + 2.1, textColor=ink, splitLongWords=True,
            ))
            _, height = para.wrap(box_width - 18, 44)
            para.drawOn(self.canv, x + 9, y + 7 + max(0, (26 - height) / 2))

        def draw(self) -> None:
            c = self.canv
            c.setStrokeColor(rule)
            c.setFillColor(pale)
            if self.mode == "cards":
                # Use the gaps between cards as routing corridors. A diagonal
                # root-to-second-row connector would cross first-row text.
                upper_bus = self.height - 49
                lower_bus = self.height - 126
                c.setStrokeColor(rule)
                c.line(258, self.height - 42, 258, upper_bus)
                c.line(82, upper_bus, 434, upper_bus)
                if len(self.nodes) > 3:
                    c.line(170, upper_bus, 170, lower_bus)
                    c.line(82, lower_bus, 434, lower_bus)
                c.roundRect(159, self.height - 42, 198, 35, 5, fill=1, stroke=1)
                self.label("Source navigation snapshot", 159, self.height - 42, 198, 9, 40)
                for i, node in enumerate(self.nodes):
                    col, row = i % 3, i // 3
                    x, y = col * 176, self.height - 113 - row * 82
                    box_width = 164
                    c.setStrokeColor(rule)
                    c.line(x + box_width / 2, upper_bus if row == 0 else lower_bus,
                           x + box_width / 2, y + 56)
                    c.setFillColor(colors.white)
                    c.roundRect(x, y, box_width, 56, 4, fill=1, stroke=1)
                    self.label(node["label"], x, y + 15, box_width, 8.5, 52)
                    c.setFont("Helvetica", 7.5)
                    c.setFillColor(muted)
                    c.drawString(x + 9, y + 10, _clip(node.get("detail", ""), 31))
                    if node.get("url"):
                        c.linkURL(node["url"], (x, y, x + box_width, y + 56), relative=1)
            elif self.mode == "build":
                for i, node in enumerate(self.nodes):
                    y = self.height - (i + 1) * 48
                    c.setFillColor(pale)
                    c.roundRect(0, y, 167, 36, 4, fill=1, stroke=1)
                    c.setFillColor(colors.white)
                    c.roundRect(211, y, 305, 36, 4, fill=1, stroke=1)
                    c.setStrokeColor(accent)
                    c.line(167, y + 18, 208, y + 18)
                    c.line(204, y + 22, 208, y + 18)
                    c.line(204, y + 14, 208, y + 18)
                    c.setStrokeColor(rule)
                    self.label(node["label"], 0, y - 2, 167, 7.7, 30)
                    self.label(node.get("detail", "Declared source files"), 211, y - 2, 305, 7.7, 58)
                    if node.get("url"):
                        c.linkURL(node["url"], (0, y, 167, y + 36), relative=1)
            else:
                last_x = None
                for i, node in enumerate(self.nodes):
                    depth = min(int(node.get("depth", 0)), 5)
                    x = depth * 15
                    y = self.height - (i + 1) * 35
                    box_width = width - x
                    c.setFillColor(pale if node.get("kind") in {"if", "for", "while", "switch", "condition"} else colors.white)
                    c.setStrokeColor(rule)
                    c.roundRect(x, y, box_width, 29, 3, fill=1, stroke=1)
                    if i:
                        c.setStrokeColor(accent)
                        c.line(last_x + 10, y + 35, x + 10, y + 29)
                    self.label(node["label"], x, y - 2, box_width, 7.5, max(30, 83 - depth * 3))
                    if node.get("url"):
                        c.linkURL(node["url"], (x, y, x + box_width, y + 29), relative=1)
                    last_x = x

    def heading(text: str, destination: str, level: int = 1, file: bool = False) -> Any:
        return Heading(text, destination, level, "FileHeading" if file else "Chapter")

    def opening(volume_title: str, description: str) -> list[Any]:
        fingerprint = model.get("fingerprint", "unavailable")
        if isinstance(fingerprint, dict):
            fingerprint = "; ".join(f"{key}: {value}" for key, value in sorted(fingerprint.items()))
        return [
            Heading(volume_title, "start", 0, "BookTitle"),
            p(description, "BookDeck"),
            p(f"Source: {model.get('source_root', '')}", "SmallBody"),
            p(f"Generated: {generated}. Snapshot fingerprint: {_clip(fingerprint, 90)}.", "SmallBody"),
            p("This is a manually generated navigation snapshot and may lag behind current code. "
              "Regenerate it explicitly when a newer map is useful; it is not part of any application build.", "SmallBody"),
        ]

    def source_link(path: str, line_number: Any = 1, file_id: str | None = None) -> str:
        item = next((f for f in files if f.get("path") == path), None)
        destination = _url("source", file_id or (item or {}).get("id", path), int(line_number or 1))
        return link(f"{path}:{line_number or 1}", destination)

    def reference_links(items: list[dict[str, Any]]) -> str:
        return "<br/>".join(source_link(item.get("path", ""), item.get("line", 1))
                            for item in items)

    def overview() -> list[Any]:
        story = opening("Start here", "A compact route through the toolchain, source organization, "
                        "entry points, and places to make a change.")
        story += [heading("1. Choose a route", "routes")]
        descriptions = {
            "build": "Compiler declarations, target source lists, options, and presets.",
            "core": "Runtime entry points, core functions, classes, and call clues.",
            "gui": "Interface entry points, objects, callbacks, and presentation code.",
            "tools": "Standalone developer utilities and support programs.",
            "tests": "Tests and examples that can illustrate expected behavior.",
        }
        rows = [["Handbook", "Use it to find"]]
        for filename, volume_title, category in VOLUMES[1:]:
            rows.append([link(volume_title, filename), _escape(descriptions[category])])
        story += [table(rows, [176, 340]),
                  p(link("Open the offline explorer", "../index.html") +
                    " for search, caller/callee navigation, source-line links, and every function's "
                    "structural control flow. Browser print gives additional function details.", raw=True),
                  p("PDF links to other PDFs are relative. Links to the offline HTML explorer may "
                    "require opening index.html separately in a browser, depending on the PDF viewer.", "SmallBody")]
        story += [heading("2. Source architecture", "architecture"),
                  p("Figure 1 groups the collected files by navigation chapter. These groupings "
                    "describe source locations, rather than inferred runtime ownership.")]
        category_counts = Counter(f.get("category", "other") for f in files)
        symbol_counts = Counter(f.get("category", "other") for f in files for _ in f.get("symbols", []))
        cards = [{"label": volume_title, "detail": f"{category_counts[category]} files | {symbol_counts[category]} symbols",
                  "url": filename} for filename, volume_title, category in VOLUMES[1:]]
        cards.append({"label": "Offline explorer", "detail": f"{len(files)} collected files", "url": "../index.html"})
        story += [Diagram(cards), p("Figure 1. Follow a box down to its handbook. " + link("Up to routes", "#routes"), "Caption", raw=True)]
        directories: dict[str, Counter[str]] = {}
        for f in files:
            path = Path(f.get("path", ""))
            parent = str(path.parent)
            directories.setdefault(f.get("category", "other"), Counter())[parent] += 1
        rows = [["Chapter", "Source directories (file counts)"]]
        for _, volume_title, category in VOLUMES[1:]:
            entries = directories.get(category, Counter())
            shown = sorted(entries.items())[:12]
            label = "; ".join(f"{path} ({count})" for path, count in shown) or "No files collected."
            if len(entries) > len(shown):
                label += f"; +{len(entries) - len(shown)} more directories in explorer"
            rows.append([_escape(volume_title), _escape(label)])
        story.append(table(rows, [133, 383]))
        story += [heading("3. Make a focused change", "change-guide")]
        guide = model.get("guide", [])
        if guide:
            for item in guide:
                card = [p(item.get("title", "Navigation tip"), "CardTitle"), p(item.get("body", ""))]
                if item.get("links"):
                    card.append(p(reference_links(item["links"]), "SmallBody", raw=True))
                story.append(KeepTogether(card))
        else:
            story += [p("Start from an entry point or a relevant class/function. Follow calls and callers "
                        "in the explorer, then confirm the source at the linked line before editing."),
                      p("To add a code file, identify the owning target's source list in the toolchain "
                        "handbook. Follow existing nearby files and target declarations when choosing "
                        "a location for a new function or class.")]
        story += [heading("4. Entry points", "entry-points")]
        entries = [(f, s) for f in files for s in f.get("symbols", []) if s.get("entry_reason")]
        if entries:
            rows = [["Entry / source", "Why it is a starting point"]]
            for f, s in entries[:42]:
                rows.append([link(s.get("qualified_name", s.get("name", "")), _url("symbol", s.get("id", ""))) +
                             "<br/>" + source_link(f["path"], s.get("line", 1), f["id"]),
                             _escape(s["entry_reason"])])
            story.append(table(rows, [286, 230]))
            if len(entries) > 42:
                story.append(p(f"{len(entries) - 42} additional entry candidates appear in their file chapters and the explorer.", "SmallBody"))
        else:
            story.append(p("No entry points were identified automatically. Use target declarations and the symbol index to locate startup code."))
        story += [heading("5. What this map can tell you", "limits"),
                  p("Symbols and control-flow structures are extracted from source syntax. Call "
                    "targets are navigation candidates: overloads, virtual dispatch, macros, "
                    "function pointers, generated code, and conditional compilation can leave "
                    "targets uncertain. Confirm behavior in source before making a change."),
                  p("Build information comes from configuration text. This generator does not "
                    "configure, compile, execute, or test the application.")]
        coverage = model.get("coverage", {})
        if coverage:
            story.append(p(f"Coverage: {coverage.get('files', len(files))} files; "
                           f"{coverage.get('symbols', sum(len(f.get('symbols', [])) for f in files))} symbols. "
                           f"{coverage.get('scope', '')}", "SmallBody"))
        if model.get("changed_during_scan"):
            story.append(p("Some inputs changed during collection. The explorer uses each file's captured "
                           "bytes, and the complete snapshot records which files changed.", "SmallBody"))
        story.append(p("The full captured inventory, configuration declarations, and collection notes " +
                       link("are saved in atlas.json", "../atlas.json") + ".", "SmallBody", raw=True))
        warnings = model.get("warnings", [])
        if warnings:
            story.append(p(f"Collection notes ({len(warnings)}):", "CardTitle"))
            for warning in warnings[:30]:
                story.append(p("- " + _clip(warning, 600), "SmallBody"))
            if len(warnings) > 30:
                story.append(p(f"{len(warnings) - 30} more collection notes are recorded in atlas.json.", "SmallBody"))
        skipped = model.get("skipped", [])
        if skipped:
            story.append(p(f"{len(skipped)} files or paths were deliberately excluded or could not be read. "
                           "Their reasons are recorded with the snapshot in atlas.json.", "SmallBody"))
        return story

    def build_book() -> list[Any]:
        story = opening("Compiler and toolchain", "Locate configuration declarations and identify "
                        "where a code file becomes part of a target.")
        build = model.get("build", {})
        targets = build.get("targets", [])
        options = build.get("options", [])
        story += [heading("1. Navigate compiler configuration", "configuration"),
                  p("Use the declarations below to find the target that owns a nearby source file. "
                    "When adding a file, inspect that target's source list and adjacent declarations "
                    "at the linked source line. Presets and option defaults describe configuration "
                    "choices; this handbook reports their text without evaluating CMake."),
                  p(link("Jump to target/source illustration", "#declared-build-dependencies") + " | " +
                    link("Jump to configuration file inventory", "#build-files"), raw=True)]
        story += [heading("2. Declared targets and source dependencies", "declared-build-dependencies")]
        if targets:
            selected = targets[:9]
            nodes = []
            for target in selected:
                sources = target.get("sources", [])
                dependencies = target.get("links", [])
                detail = f"{len(sources)} source arguments; links: " + (", ".join(dependencies[:3]) or "none collected")
                if len(dependencies) > 3:
                    detail += f"; +{len(dependencies) - 3} more link arguments"
                nodes.append({"label": f"{target.get('name', '')} ({target.get('kind', '')})",
                              "detail": detail,
                              "url": _url("source", next((f["id"] for f in files if f["path"] == target.get("path")), target.get("path", "")), int(target.get("line", 1)))})
            story.append(Diagram(nodes, "build"))
            story.append(p("Figure 2. Each arrow points from a declared target to a summary of its "
                           "collected source and link arguments. Variables and generator expressions remain unevaluated. " +
                           (f"{len(targets) - 9} additional targets are listed below. " if len(targets) > 9 else "") +
                           link("Up to compiler configuration", "#configuration"), "Caption", raw=True))
            rows = [["Target / declaration", "Source and link arguments"]]
            for target in targets:
                sources, dependencies = target.get("sources", []), target.get("links", [])
                details = "Sources: " + (", ".join(sources[:12]) or "none collected")
                if len(sources) > 12:
                    details += f"; +{len(sources) - 12} more source arguments in explorer"
                details += "<br/>Links: " + _escape(", ".join(dependencies[:12]) or "none collected")
                if len(dependencies) > 12:
                    details += f"; +{len(dependencies) - 12} more link arguments in explorer"
                # Escape source text separately: target arguments often contain '<' expressions.
                source_part, link_part = details.split("<br/>", 1)
                rows.append([f"<b>{_escape(target.get('name', ''))}</b> ({_escape(target.get('kind', ''))})<br/>" +
                             source_link(target.get("path", ""), target.get("line", 1)),
                             _escape(source_part) + "<br/>" + link_part])
            story.append(table(rows, [201, 315]))
        else:
            story.append(p("No literal target declarations were collected. Consult the configuration file inventory."))
        story += [heading("3. Configuration options", "options")]
        if options:
            rows = [["Option / default", "Meaning / declaration"]]
            for option in options:
                rows.append([f"<b>{_escape(option.get('name', ''))}</b><br/>Default: {_escape(option.get('default', ''))}",
                             _escape(option.get("description", "")) + "<br/>" +
                             source_link(option.get("path", ""), option.get("line", 1))])
            story.append(table(rows, [176, 340]))
        else:
            story.append(p("No option() declarations were collected."))
        story += [heading("4. Presets", "presets")]
        presets = build.get("presets", {})
        preset_rows = [["Preset collection", "Configuration values"]]
        if isinstance(presets, dict):
            for key, values in presets.items():
                if isinstance(values, dict):
                    collections = list(values.items())
                    for group, group_value in collections:
                        if isinstance(group_value, list):
                            for item in group_value:
                                if isinstance(item, dict):
                                    shown = {k: item[k] for k in ("name", "displayName", "inherits", "generator", "binaryDir", "configurePreset", "cacheVariables") if k in item}
                                    preset_rows.append([_escape(f"{key}: {group}"), _escape(_clip(shown, 650))])
                        elif group in {"version", "cmakeMinimumRequired"}:
                            preset_rows.append([_escape(f"{key}: {group}"), _escape(group_value)])
                elif isinstance(values, list):
                    for item in values:
                        preset_rows.append([_escape(key), _escape(_clip(item, 650))])
                else:
                    preset_rows.append([_escape(key), _escape(_clip(values, 650))])
        if len(preset_rows) > 1:
            story.append(table(preset_rows, [151, 365]))
        else:
            story.append(p("No preset files were collected."))
        commands = build.get("commands", [])
        salient = {"cmake_minimum_required", "project", "enable_language", "find_package", "add_subdirectory", "include", "set", "target_compile_options", "target_compile_definitions", "target_include_directories"}
        chosen = [c for c in commands if str(c.get("command", "")).lower() in salient]
        story += [heading("5. Toolchain declaration clues", "declarations")]
        if chosen:
            rows = [["Command / declaration", "Collected arguments"]]
            for command in chosen[:45]:
                rows.append([_escape(command.get("command", "")) + "<br/>" + source_link(command.get("path", ""), command.get("line", 1)),
                             _escape(_clip(" ".join(command.get("args", [])), 350))])
            story.append(table(rows, [211, 305]))
        omitted = len(commands) - min(45, len(chosen))
        if omitted:
            story.append(p(f"{omitted} other command declarations are omitted from this print excerpt; "
                           "configuration source remains available through the explorer.", "SmallBody"))
        elif not chosen:
            story.append(p("No additional compiler configuration declarations were collected."))
        story += [heading("6. Configuration file inventory", "build-files")]
        chosen_files = [f for f in files if f.get("category") == "build"]
        story.extend(file_chapters(chosen_files, level=2, include_flows=False))
        return story

    def calls_text(symbol: dict[str, Any]) -> str:
        calls = symbol.get("calls", [])
        if not calls:
            return "0 / 0 / 0"
        targets = {target for call in calls for target in call.get("targets", [])}
        unresolved = sum(1 for call in calls if not call.get("targets"))
        return f"{len(calls)} / {len(targets)} / {unresolved}"

    def printed_symbols(f: dict[str, Any]) -> list[dict[str, Any]]:
        """Choose a readable print directory; the explorer retains all symbols."""
        all_symbols = f.get("symbols", [])
        namespace_owners = {s.get("qualified_name", s.get("name")) for s in all_symbols if s.get("kind") == "namespace"}
        result = []
        for symbol in all_symbols:
            kind = symbol.get("kind", "")
            if symbol.get("entry_reason"):
                result.append(symbol)
            elif f.get("category") in {"tools", "tests"}:
                if kind in {"function", "class", "struct", "enum"} and (
                    not symbol.get("owner") or symbol.get("owner") in namespace_owners
                ):
                    result.append(symbol)
            elif kind not in {"lambda", "module", "namespace"}:
                result.append(symbol)
        return sorted(result, key=lambda s: (s.get("line", 0), s.get("name", "")))

    def file_chapters(chosen_files: list[dict[str, Any]], level: int = 1,
                      include_flows: bool = True) -> list[Any]:
        story: list[Any] = []
        if not chosen_files:
            return [p("No files were collected for this chapter.")]
        rows = [["File (linked to its section)", "Inventory"]]
        for f in chosen_files:
            rows.append([link(f.get("path", ""), "#" + _anchor("file-", f.get("id", ""))),
                         _escape(f"{f.get('language', '')} | {f.get('line_count', 0)} lines | {len(printed_symbols(f))} printed / {len(f.get('symbols', []))} symbols")])
        story.append(table(rows, [363, 153]))
        flow_count = 0
        for f in chosen_files:
            destination = _anchor("file-", f.get("id", ""))
            all_symbols = f.get("symbols", [])
            symbols = printed_symbols(f)
            selected_flows = []
            if include_flows and flow_count < 8:
                selected_flows = [s for s in symbols if s.get("flow") and (
                    s.get("entry_reason") or s.get("name", "").split("::")[-1] in
                    {"main", "run", "start", "exec", "application_main", "event_loop"})][:min(2, 8 - flow_count)]
            story.append(heading(f.get("path", ""), destination, level=level, file=True))
            intro = f"{f.get('language', '')}; {f.get('line_count', 0)} source lines; {len(symbols)} printed / {len(all_symbols)} collected symbols. "
            intro += link("Source and file explorer", _url("file", f.get("id", "")))
            intro += " | " + link("Up to chapter index", "#build-files" if f.get("category") == "build" else "#files")
            story.append(p(intro, "SmallBody", raw=True))
            if selected_flows:
                story.append(p("Printed flow illustrations: " + " | ".join(
                    link(s.get("name", ""), "#" + _anchor("flow-", s.get("id", "")))
                    for s in selected_flows), "SmallBody", raw=True))
            if len(symbols) < len(all_symbols):
                shown_ids = {s.get("id") for s in symbols}
                omitted = Counter(s.get("kind", "symbol") for s in all_symbols if s.get("id") not in shown_ids)
                counts = ", ".join(f"{count} {kind}" for kind, count in sorted(omitted.items()))
                story.append(p(f"{len(all_symbols) - len(symbols)} additional symbols are retained in the explorer "
                               f"({counts}).", "SmallBody"))
            if not symbols:
                story.append(p("No printed function or object symbols in this file. Use the linked source "
                               "to inspect declarations, resources, scripts, or configuration.", "SmallBody"))
                continue
            rows = [["Symbol / exact source line", "Kind / owner", "Calls<br/>sites / targets / ?"]]
            for symbol in symbols:
                symbol_cell = link(symbol.get("name", ""), _url("symbol", symbol.get("id", "")))
                symbol_cell += "  " + link("[L" + _line(symbol) + "]", _url("source", f.get("id", ""), int(symbol.get("line", 1))))
                if symbol.get("entry_reason"):
                    symbol_cell += " <b>[entry]</b>"
                kind = _escape(symbol.get("kind", "symbol"))
                if symbol.get("owner"):
                    kind += "<br/>" + _escape(symbol["owner"])
                if symbol.get("bases"):
                    kind += "<br/>Bases: " + _escape(", ".join(symbol["bases"]))
                rows.append([symbol_cell, kind, calls_text(symbol)])
            story.append(table(rows, [285, 147, 84], dense=True))
            if selected_flows:
                for symbol in selected_flows:
                    if flow_count >= 8:
                        break
                    flow_count += 1
                    rows, omitted = _flow_rows(symbol.get("flow", []))
                    if not rows:
                        continue
                    flow_heading = heading(f"Structural flow example: {symbol.get('qualified_name', symbol.get('name', ''))}",
                                           _anchor("flow-", symbol.get("id", "")), level=level + 1, file=True)
                    nodes = [{"depth": depth, "kind": node.get("kind", ""),
                              "label": f"L{node.get('line', symbol.get('line', 1))} | {node.get('kind', 'step')}: {node.get('label', '')}",
                              "url": _url("source", f.get("id", ""), int(node.get("line", symbol.get("line", 1))))}
                             for depth, node in rows]
                    caption = "Ordered structural landmarks; indentation follows collected nesting. "
                    caption += "Connectors indicate reading order, not proven execution edges. "
                    if omitted:
                        caption += f"{omitted} additional landmarks are omitted from this print excerpt. "
                    caption += link("Full function flow", _url("symbol", symbol.get("id", ""))) + " | " + link("Up to file", "#" + destination)
                    story.append(KeepTogether([flow_heading, Diagram(nodes, "flow"),
                                               p(caption, "Caption", raw=True)]))
        return story

    def code_book(category: str, volume_title: str) -> list[Any]:
        descriptions = {
            "core": "Navigate runtime functions and objects from source entry points into their immediate call neighborhoods.",
            "gui": "Locate interface objects, event entry points, and nearby presentation functions.",
            "tools": "Find independently invoked utilities and the support functions they use.",
            "tests": "Locate test cases and examples that may show how the source is intended to behave.",
        }
        chosen_files = [f for f in files if f.get("category") == category]
        symbols = [s for f in chosen_files for s in f.get("symbols", [])]
        story = opening(volume_title, descriptions[category])
        story += [p(f"This chapter contains {len(chosen_files)} files and {len(symbols)} collected symbols. "
                    "Each symbol name opens its function/object explorer; its line range opens the "
                    "source at that location."),
                  p(("Printed tables include top-level named functions/classes and entry candidates. "
                     "Methods and nested/anonymous callbacks are counted per file and remain in the explorer. "
                     if category in {"tools", "tests"} else
                     "Printed tables include named functions, classes, and members, plus entry candidates. "
                     "Anonymous callbacks and namespace/module wrappers are counted per file and remain in the explorer. ") +
                    "The calls column shows call sites / distinct candidate targets / sites without targets (?); "
                    "it counts source syntax, not runtime executions.", "SmallBody"),
                  p("Call counts describe syntactic call sites and candidate targets. Targets can be "
                    "ambiguous or absent for overloads, macros, callbacks, virtual dispatch, and "
                    "external libraries. Use the explorer to follow callers, callees, inheritance, "
                    "and every function's full structural flow.", "SmallBody"),
                  heading("File index and symbol chapters", "files")]
        story.extend(file_chapters(chosen_files, level=2, include_flows=category in {"core", "gui", "tools"}))
        return story

    rendered = []
    for filename, volume_title, category in VOLUMES:
        if category == "overview":
            story = overview()
        elif category == "build":
            story = build_book()
        else:
            story = code_book(category, volume_title)
        document = BookDoc(pdf_dir / filename, volume_title)
        document.build(story)
        rendered.append("pdf/" + filename)
    return rendered
