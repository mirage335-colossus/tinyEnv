"""Render literal, source-linked code diagrams beneath execution overviews.

The supplied captured model is the only application input. This renderer does
not modify source, configure a build, run tests, or execute project commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape
import re
import unicodedata


PDF_NAME = "04-code-flowcharts.pdf"


def _plain(value: Any) -> str:
    value = str(value if value is not None else "")
    for old, new in (("\u2013", "-"), ("\u2014", "-"), ("\u2018", "'"),
                     ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                     ("\u2192", " -> "), ("\u2190", " <- "), ("\u00b7", " | ")):
        value = value.replace(old, new)
    return unicodedata.normalize("NFKD", value).encode("ascii", "backslashreplace").decode("ascii")


def _esc(value: Any) -> str:
    return escape(_plain(value), {'"': "&quot;"})


def _dest(kind: str, map_id: str, node_id: str = "") -> str:
    return "code-" + kind + "-" + re.sub(r"[^A-Za-z0-9_-]", "_", map_id + ("-" + node_id if node_id else ""))


def _source_url(node: dict[str, Any], line: int | None = None) -> str:
    return "../index.html#source/" + quote(str(node.get("file_id") or node.get("path", "")), safe="") + "/" + str(line or node.get("line") or 1)


def _diagram_url(map_id: str, node_id: str = "") -> str:
    return "../index.html#code/" + quote(map_id, safe="") + ("/" + quote(node_id, safe="") if node_id else "")


def render_code_pdf(model: dict[str, Any], output: Path) -> str:
    """Write graphical code excerpts and publish exact diagram/node pages."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError as exc:
        raise ImportError("Code-flowchart PDF output needs ReportLab. Install the documentation "
                          "tool's requirements or run with --no-pdf.") from exc

    maps = list(model.get("code_maps", []))
    if not maps:
        raise ValueError("No code_maps are available for the code-flowchart PDF.")
    # Put the direct startup-to-declaration route at the front of the
    # printed collection without altering the captured model's ordering.
    entry_order = {"main-to-widgets": 0, "widget-definitions": 1}
    maps.sort(key=lambda item: entry_order.get(item.get("id", ""), 2))
    output = Path(output)
    (output / "pdf").mkdir(parents=True, exist_ok=True)
    filename = output / "pdf" / PDF_NAME
    page_w, page_h = landscape(letter)
    margin, body_h = 26, page_h - 91
    body_w = page_w - margin * 2
    ink, muted, rule = (colors.HexColor(x) for x in ("#173849", "#526773", "#cad8df"))
    blue = colors.HexColor("#256b91")
    edge_colors = {"call": "#2f719b", "process": "#3f7a58", "conditional": "#a37123",
                   "return": "#627987", "event": "#8063a5", "step": "#526773", "dependency": "#768995"}
    # A standard PDF font keeps layout independent of installed system fonts.
    # Unsupported source glyphs retain the explicit escapes used below.
    mono_font = "Courier"
    mono_glyphs: set[int] = set(range(128))
    code_size, code_leading = 9.2, 11.6
    char_w = pdfmetrics.stringWidth("M", mono_font, code_size)
    styles = {
        "title": ParagraphStyle("code-title", fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=ink, spaceAfter=9, keepWithNext=True),
        "body": ParagraphStyle("code-body", fontName="Helvetica", fontSize=9.6, leading=12.3, textColor=ink, spaceAfter=5),
        "small": ParagraphStyle("code-small", fontName="Helvetica", fontSize=9, leading=11.4, textColor=muted, spaceAfter=4),
        "card-title": ParagraphStyle("code-card-title", fontName="Helvetica-Bold", fontSize=10.2, leading=12.5, textColor=ink),
        "card-note": ParagraphStyle("code-card-note", fontName="Helvetica", fontSize=9.1, leading=11.4, textColor=ink),
        "card-source": ParagraphStyle("code-card-source", fontName="Helvetica", fontSize=9, leading=11.4, textColor=muted),
        "key": ParagraphStyle("code-key", fontName="Helvetica", fontSize=9, leading=11.3, textColor=ink),
        "table": ParagraphStyle("code-table", fontName="Helvetica", fontSize=9.2, leading=11.6, textColor=ink),
        "tablehead": ParagraphStyle("code-tablehead", fontName="Helvetica-Bold", fontSize=9.2, leading=11.6, textColor=ink),
        "evidence-title": ParagraphStyle("code-evidence-title", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=ink, spaceBefore=9, spaceAfter=5, keepWithNext=True),
    }
    for style in styles.values():
        style.splitLongWords = True

    def link(label: Any, target: str) -> str:
        return '<link href="' + _esc(target) + '" color="#256b91">' + _esc(label) + "</link>"

    def p(value: Any, style: str = "body", raw: bool = False) -> Any:
        return Paragraph(str(value) if raw else _esc(value), styles[style])

    def paragraph_height(value: Any, width: float, style: str, raw: bool = False) -> float:
        return p(value, style, raw).wrap(width, body_h)[1]

    def literal(value: Any) -> str:
        # Source text does not pass through the prose normalizer. Preserve
        # available glyphs verbatim and explicitly escape unsupported ones.
        return "".join(character if ord(character) in mono_glyphs else character.encode("ascii", "backslashreplace").decode("ascii")
                       for character in str(value)).expandtabs(4)

    def code_fragments(node: dict[str, Any], width: float, compact: bool = False) -> list[tuple[int, str, bool]]:
        limit = max(12, int((width - (36 if compact else 48)) / char_w))
        fragments = []
        for record in node.get("code_lines", []):
            text, continuation = literal(record.get("text", "")), False
            while len(text) > limit:
                # Keep every character, including spaces at the wrap point.
                minimum = int(limit * .8) if compact else limit // 2
                cut = text.rfind(" ", minimum, limit + 1)
                if cut < minimum:
                    cut = limit
                fragments.append((int(record.get("line") or node.get("line") or 1), text[:cut], continuation))
                text, continuation = text[cut:], True
            fragments.append((int(record.get("line") or node.get("line") or 1), text, continuation))
        return fragments

    def printed_source(node: dict[str, Any]) -> str:
        refs = model.get("print_references", {})
        record = refs.get("symbols", {}).get(str(node.get("symbol_id", "")))
        record = record or refs.get("locations", {}).get(f"{node.get('file_id', '')}:{node.get('line') or 1}")
        if record:
            return link(f"Implementation PDF p{record['page']}", record["pdf"] + "#page=" + str(record["page"]))
        return ""

    def parent_links(map_value: dict[str, Any]) -> str:
        links = []
        refs = model.get("print_references", {})
        seen = set()
        for parent in map_value.get("parents", []):
            map_id, node_id = str(parent.get("map", "")), str(parent.get("node", ""))
            identity = (parent.get("kind"), map_id, node_id if parent.get("kind") == "code" else "")
            if identity in seen:
                continue
            seen.add(identity)
            label = map_id + (" / " + node_id if node_id and parent.get("kind") == "code" else "")
            if parent.get("kind") == "code":
                links.append(link("Up: " + label, "#" + _dest("node" if node_id else "map", map_id, node_id)))
            elif parent.get("kind") == "flow":
                record = refs.get("flow_maps", {}).get(map_id)
                target = record["pdf"] + "#page=" + str(record["page"]) if record else "03-execution-flows.pdf"
                links.append(link("Up: " + label, target))
        return " | ".join(links) or link("Up: execution scenarios", "03-execution-flows.pdf")

    def node_metrics(node: dict[str, Any], width: float, compact: bool = False) -> dict[str, Any]:
        title = _esc(node.get("title", "Code excerpt"))
        if not compact:
            title = title.replace("::", "::<br/>")
        title_h = paragraph_height(title, width - 18, "card-title", True)
        source = link(f"{node.get('path', '')}:{node.get('line') or 1}" +
                      (f"-{node['end_line']}" if node.get("end_line") and node.get("end_line") != node.get("line") else ""), _source_url(node))
        if node.get("status") == "missing":
            source = "<b>Review required: source anchor not captured.</b> " + source
        elif str(node.get("path", "")).startswith("@"):
            source = "<b>Read-only supplier source.</b> " + source
        source_h = paragraph_height(source, width - 18, "card-source", True)
        # Context is collected once in the linked evidence section; the
        # graphical cards reserve their space for literal source statements.
        note = ""
        note_h = 0
        child = node.get("child") or {}
        footer = ""
        if child.get("map") and not compact:
            footer = link("Open deeper diagram", "#" + _dest("node" if child.get("node") else "map", child["map"], child.get("node", "")))
        footer_h = paragraph_height(footer, width - 18, "card-source", True) + 3 if footer else 0
        fragments = code_fragments(node, width, compact)
        leading = 10.8 if compact else code_leading
        code_h = len(fragments) * leading if fragments else paragraph_height(
            "No literal source lines were captured; review the linked location.", width - 51, "card-note")
        height = ((19 + title_h + 3 + source_h + 4 + code_h + 4 + 6) if compact else
                  (22 + title_h + 4 + source_h + 5 + code_h + 4 + note_h + footer_h + 8))
        return {"height": max(86, height), "title": title, "source": source, "fragments": fragments,
                "note": note, "footer": footer, "code_height": code_h, "compact": compact,
                "code_leading": leading}

    # Node rows are pagination units. A genuinely wide/long source block gets
    # full width rather than an illegibly small font or a clipped command.
    card_gap, outside = 44, 18
    half_w = (body_w - outside * 2 - card_gap) / 2
    full_w = body_w - outside * 2
    plans: list[dict[str, Any]] = []
    for map_value in maps:
        compact = map_value.get("id") == "main-to-widgets"
        nodes = map_value.get("nodes", [])
        numbers = {node["id"]: i for i, node in enumerate(nodes, 1)}
        by_row: dict[int, list[dict[str, Any]]] = {}
        for node in nodes:
            by_row.setdefault(int(node.get("row", 0)), []).append(node)
        units = []
        for row_nodes in by_row.values():
            row_nodes = sorted(row_nodes, key=lambda n: int(n.get("column", 0)))
            metrics = [node_metrics(node, half_w, compact) for node in row_nodes]
            if len(row_nodes) > 2 or any(item["height"] > 315 for item in metrics):
                for node in row_nodes:
                    units.append({"nodes": [node], "wide": True, "metrics": [node_metrics(node, full_w, compact)]})
            else:
                units.append({"nodes": row_nodes, "wide": False, "metrics": metrics})
        for unit in units:
            unit["height"] = max(item["height"] for item in unit["metrics"])

        parents = parent_links(map_value).split(" | ")
        header_values = [(parents[0] + " | " + link("Evidence and other parents", "#" + _dest("evidence", map_value["id"]))
                          + " | " + link("Interactive diagram", _diagram_url(map_value["id"])), "small", True)]
        header_h = sum(paragraph_height(value, body_w, style, raw) + 5 for value, style, raw in header_values if value)
        edges = map_value.get("edges", [])

        def page_parts(chosen: list[dict[str, Any]]) -> dict[str, Any]:
            ids = {node["id"] for unit in chosen for node in unit["nodes"]}
            internal, incoming, outgoing = [], [], []
            for number, edge in enumerate(edges, 1):
                if edge.get("from") in ids and edge.get("to") in ids:
                    internal.append((number, edge))
                elif edge.get("to") in ids:
                    incoming.append((number, edge))
                elif edge.get("from") in ids:
                    outgoing.append((number, edge))
            def caption(number: int, edge: dict[str, Any], direction: str) -> str:
                target = edge["from"] if direction == "From" else edge["to"]
                return link(f"{direction} N{numbers.get(target, '?')} on another part of this diagram", "#" + _dest("node", map_value["id"], target)) + " | " + _esc(f"{number}: {edge.get('label', '')} [{edge.get('kind', 'step')}]")
            incoming_rows = [(number, edge, caption(number, edge, "From")) for number, edge in incoming]
            outgoing_rows = [(number, edge, caption(number, edge, "Continue to")) for number, edge in outgoing]
            key_rows = ["<b>" + _esc(f"{number}. N{numbers.get(edge['from'], '?')} -> N{numbers.get(edge['to'], '?')}") + "</b> " + _esc(f"[{edge.get('kind', 'step')}] {edge.get('label', '')}") for number, edge in internal]
            incoming_h = sum(paragraph_height(text, body_w - 30, "key", True) + 6 for _, _, text in incoming_rows)
            outgoing_h = sum(paragraph_height(text, body_w - 30, "key", True) + 6 for _, _, text in outgoing_rows)
            key_grid = [key_rows[i:i + 2] for i in range(0, len(key_rows), 2)] if compact else []
            key_h = (sum(max(paragraph_height(text, (body_w - 16) / 2, "key", True) for text in row) + 3
                         for row in key_grid) if compact else
                     sum(paragraph_height(text, body_w, "key", True) + 3 for text in key_rows))
            # Reserve the part-navigation line as well as graph/legend gaps.
            # Even a one-part diagram keeps this slack, so splitting does not
            # invalidate an earlier page-height calculation.
            used = header_h + incoming_h + outgoing_h + key_h + 51 + sum(u["height"] for u in chosen) + max(0, len(chosen) - 1) * 20
            return {"units": chosen, "internal": internal, "incoming": incoming_rows,
                    "outgoing": outgoing_rows, "key": key_rows, "key_grid": key_grid,
                    "header": header_values, "height": used}
        chunks = []
        current = []
        for unit in units:
            candidate = page_parts(current + [unit])
            if current and candidate["height"] > body_h:
                chunks.append(page_parts(current))
                current = [unit]
            else:
                current.append(unit)
            if page_parts(current)["height"] > body_h and not unit["wide"]:
                # Reflow just this row at full width, keeping literal source.
                current.pop()
                if current:
                    chunks.append(page_parts(current))
                current = []
                for node in unit["nodes"]:
                    metric = node_metrics(node, full_w)
                    wide = {"nodes": [node], "wide": True, "metrics": [metric], "height": metric["height"]}
                    if page_parts([wide])["height"] > body_h:
                        raise ValueError(f"Code card {map_value['id']}/{node['id']} exceeds a readable page even at full width.")
                    chunks.append(page_parts([wide]))
        if current:
            chunks.append(page_parts(current))
        whole = page_parts(units)
        # A single-page entry path has no continuation-navigation line.
        # Recover that reserved space only when the complete six-card map fits.
        if compact and whole["height"] - 16 <= body_h:
            whole["height"] -= 16
            chunks = [whole]
        if not chunks:
            chunks = [page_parts([])]
        if any(chunk["height"] > body_h for chunk in chunks):
            raise ValueError(f"Code diagram {map_value['id']} contains too much complete source/metadata for one row; refine its literal node boundaries.")
        plans.append({"map": map_value, "chunks": chunks, "numbers": numbers, "compact": compact})

    class Heading(Paragraph):
        def __init__(self, text: str, destination: str) -> None:
            super().__init__(_esc(text), styles["title"])
            self.label, self.destination = _plain(text), destination

    class EvidenceHeading(Paragraph):
        def __init__(self, text: str, destination: str) -> None:
            super().__init__(_esc(text), styles["evidence-title"])
            self.label, self.destination = _plain(text), destination

    class CodeDoc(BaseDocTemplate):
        def __init__(self) -> None:
            super().__init__(str(filename), pagesize=(page_w, page_h), leftMargin=margin, rightMargin=margin,
                             topMargin=54, bottomMargin=37, title=f"{model.get('title', 'Software foundation')}: literal code flowcharts",
                             author="Local source-map generator", subject="Hierarchical diagrams of selected captured source statements")
            self.current_map: dict[str, Any] | None = None
            self.map_pages: dict[str, Any] = {}
            self.node_pages: dict[str, Any] = {}
            frame = Frame(margin, 37, body_w, body_h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
            # SetMap is a page-local flowable. Decorate after it has run,
            # so each first diagram page gets its own heading and URL.
            self.addPageTemplates(PageTemplate("code", frames=[frame], onPageEnd=self.decorate))

        def decorate(self, c: Any, doc: Any) -> None:
            c.saveState()
            title = _plain((self.current_map or {}).get("title", "Literal code diagrams"))
            size = min(15, max(10, (body_w - 95) / max(1, pdfmetrics.stringWidth(title, "Helvetica-Bold", 1))))
            c.setFont("Helvetica-Bold", size)
            c.setFillColor(ink)
            c.drawString(margin, page_h - 27, title)
            c.setFont("Helvetica", 8)
            c.setFillColor(muted)
            c.drawRightString(page_w - margin, page_h - 27, f"Code diagrams | {doc.page}")
            c.setStrokeColor(rule)
            c.line(margin, page_h - 38, page_w - margin, page_h - 38)
            c.line(margin, 28, page_w - margin, 28)
            c.setFillColor(blue)
            c.drawString(margin, 16, "Code index")
            c.linkRect("", "code-index", (margin, 13, margin + 43, 24), relative=0)
            c.drawString(margin + 59, 16, "Execution scenarios")
            c.linkURL("03-execution-flows.pdf", (margin + 59, 13, margin + 132, 24), relative=0)
            c.drawString(margin + 148, 16, "Offline diagram")
            c.linkURL(_diagram_url(self.current_map["id"]) if self.current_map else "../index.html#flows",
                      (margin + 148, 13, margin + 206, 24), relative=0)
            c.setFillColor(muted)
            c.drawRightString(page_w - margin, 16, _plain(model.get("generated_at", "")) + " | On-request snapshot; may be stale")
            c.restoreState()

        def afterFlowable(self, item: Any) -> None:
            if isinstance(item, Heading):
                self.canv.bookmarkPage(item.destination)
                self.canv.addOutlineEntry(item.label, item.destination, level=0)
            elif isinstance(item, EvidenceHeading):
                self.canv.bookmarkPage(item.destination)
                self.canv.addOutlineEntry(item.label, item.destination, level=1)
            elif isinstance(item, CodeChart):
                map_id = item.plan["map"]["id"]
                if item.part == 0:
                    self.canv.bookmarkPage(_dest("map", map_id))
                    self.canv.addOutlineEntry(_plain(item.plan["map"].get("title", map_id)), _dest("map", map_id), level=0)
                    self.map_pages[map_id] = {"pdf": PDF_NAME, "page": self.page}
                self.canv.bookmarkPage(_dest("part", map_id, str(item.part + 1)))
                if len(item.plan["chunks"]) > 1:
                    self.canv.addOutlineEntry(f"Diagram part {item.part + 1}", _dest("part", map_id, str(item.part + 1)), level=1)
                for unit in item.chunk["units"]:
                    for node in unit["nodes"]:
                        self.canv.bookmarkPage(_dest("node", map_id, node["id"]))
                        self.node_pages[map_id + "/" + node["id"]] = {"pdf": PDF_NAME, "page": self.page}

    class SetMap(Flowable):
        def __init__(self, map_value: dict[str, Any] | None) -> None:
            super().__init__()
            self.map, self.width, self.height = map_value, 0, 0

        def draw(self) -> None:
            self._doctemplate.current_map = self.map

    class CodeChart(Flowable):
        def __init__(self, plan: dict[str, Any], part: int) -> None:
            super().__init__()
            self.plan, self.part, self.chunk = plan, part, plan["chunks"][part]
            self.width, self.height = body_w, body_h

        def wrap(self, aw: float, ah: float) -> tuple[float, float]:
            return self.width, self.height

        def text(self, value: Any, x: float, top: float, width: float, style: str, raw: bool = False) -> float:
            para = p(value, style, raw)
            height = para.wrap(width, body_h)[1]
            para.drawOn(self.canv, x, top - height)
            return height

        def arrow(self, points: list[tuple[float, float]], edge: dict[str, Any], number: int | None = None,
                  badge: tuple[float, float] | None = None,
                  badge_anchor: tuple[float, float] | None = None) -> None:
            c = self.canv
            supporting = edge.get("emphasis") == "supporting" or edge.get("kind") == "dependency"
            color = colors.HexColor(edge_colors.get(edge.get("kind", "step"), "#526773"))
            c.setStrokeColor(color)
            c.setFillColor(color)
            c.setLineWidth(.95 if supporting else 1.7)
            c.setDash(3, 2) if supporting or edge.get("kind") in {"conditional", "event"} else c.setDash(1, 2) if edge.get("kind") == "return" else c.setDash()
            path = c.beginPath()
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)
            c.drawPath(path)
            c.setDash()
            end, prior = points[-1], points[-2]
            dx, dy = end[0] - prior[0], end[1] - prior[1]
            if abs(dx) > abs(dy):
                sign = 1 if dx > 0 else -1
                arms = [(end[0] - sign * 5, end[1] + 3), (end[0] - sign * 5, end[1] - 3)]
            else:
                sign = 1 if dy > 0 else -1
                arms = [(end[0] + 3, end[1] - sign * 5), (end[0] - 3, end[1] - sign * 5)]
            for arm in arms:
                c.line(*end, *arm)
            if number is not None and badge:
                bx, by = badge
                if badge_anchor and badge_anchor != badge:
                    c.setLineWidth(.5)
                    c.line(*badge_anchor, bx, by)
                c.setFillColor(colors.white)
                c.roundRect(bx - 7, by - 6, 14, 12, 3, fill=1, stroke=1)
                c.setFillColor(color)
                c.setFont("Helvetica-Bold", 9)
                c.drawCentredString(bx, by - 3, str(number))

        def draw_node(self, node: dict[str, Any], metric: dict[str, Any], box: tuple[float, float, float, float]) -> None:
            c = self.canv
            x, y, width, height = box
            primary = node.get("emphasis", "primary") == "primary"
            border = colors.HexColor("#3b718b" if primary else "#879aa5")
            c.setFillColor(colors.HexColor("#f1f7fa" if primary else "#f7f9fa"))
            c.setStrokeColor(border)
            c.setLineWidth(1.45 if primary else .85)
            c.roundRect(x, y, width, height, 5, fill=1, stroke=1)
            child = node.get("child") or {}
            if child.get("map"):
                c.linkRect("", _dest("node" if child.get("node") else "map", child["map"], child.get("node", "")), (x, y, x + width, y + height), relative=1)
            compact = metric.get("compact", False)
            top = y + height - (7 if compact else 8)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(border)
            role_label = f"N{self.plan['numbers'][node['id']]} | {node.get('role', 'CODE')} | {'MAIN' if primary else 'SUPPORT'}"
            if compact:
                role_label += " | callback runs later" if node.get("id") == "session" else " | Deeper diagram" if child.get("map") else ""
            c.drawString(x + 9, top - 5, role_label)
            top -= 12 if compact else 14
            top -= self.text(metric["title"], x + 9, top, width - 18, "card-title", True) + (3 if compact else 4)
            top -= self.text(metric["source"], x + 9, top, width - 18, "card-source", True) + (4 if compact else 5)
            fragments = metric["fragments"]
            code_top = top
            c.setStrokeColor(rule)
            gutter, text_x = (24, 30) if compact else (35, 42)
            c.line(x + gutter, code_top + 1, x + gutter, code_top - metric["code_height"])
            # Draw source consecutively before gutter labels. PDF extraction
            # then keeps wrapped physical source lines contiguous as well.
            for index, (_, text, _) in enumerate(fragments):
                baseline = code_top - code_size - index * metric["code_leading"]
                c.setFont(mono_font, code_size)
                c.setFillColor(ink)
                c.drawString(x + text_x, baseline, text)
            for index, (line, _, continuation) in enumerate(fragments):
                baseline = code_top - code_size - index * metric["code_leading"]
                c.setFont("Helvetica", 9)
                c.setFillColor(blue)
                c.drawRightString(x + gutter - 4, baseline, "+" if continuation else str(line))
                if not continuation:
                    c.linkURL(_source_url(node, line), (x + 3, baseline - 2, x + gutter - 1, baseline + 10), relative=1)
            if not fragments:
                top -= self.text("No literal source lines were captured; review the linked location.", x + 42, top, width - 51, "card-note")
            else:
                top -= metric["code_height"]
            top -= 4
            if metric["note"]:
                top -= self.text(metric["note"], x + 9, top, width - 18, "card-note") + 5
            if metric["footer"]:
                top -= self.text(metric["footer"], x + 9, top, width - 18, "card-source", True) + 3
            if top < y + 4:
                raise ValueError(f"Code diagram {self.plan['map']['id']}/{node['id']} clipped its complete card content.")

        def draw(self) -> None:
            c, map_value = self.canv, self.plan["map"]
            top = body_h - 1
            for value, style, raw in self.chunk["header"]:
                if value:
                    top -= self.text(value, 0, top, body_w, style, raw) + 5
            if len(self.plan["chunks"]) > 1:
                navigation = f"Diagram part {self.part + 1} of {len(self.plan['chunks'])}"
                if self.part:
                    navigation += " | " + link("Previous part", "#" + _dest("part", map_value["id"], str(self.part)))
                if self.part + 1 < len(self.plan["chunks"]):
                    navigation += " | " + link("Next part", "#" + _dest("part", map_value["id"], str(self.part + 2)))
                top -= self.text(navigation, 0, top, body_w, "small", True) + 5
            incoming_positions = []
            for number, edge, text in self.chunk["incoming"]:
                caption_top = top
                top -= self.text(text, 22, top, body_w - 30, "key", True) + 6
                incoming_positions.append((number, edge, caption_top - 6))
            row_top, boxes = top - 4, {}
            for row_number, unit in enumerate(self.chunk["units"]):
                for node, metric in zip(unit["nodes"], unit["metrics"]):
                    if unit["wide"]:
                        x, width = outside, full_w
                    else:
                        # Preserve the original two-column placement even
                        # when a row has only its supporting/right card.
                        column = int(node.get("column", 0))
                        min_column = min(int(n.get("column", 0)) for n in map_value.get("nodes", []))
                        x = outside + (0 if column == min_column else half_w + card_gap)
                        width = half_w
                    box = (x, row_top - unit["height"], width, unit["height"])
                    boxes[node["id"]] = {"box": box, "row": row_number, "wide": unit["wide"], "node": node, "metric": metric}
                row_top -= unit["height"] + 20
            graph_bottom = row_top + 20
            badge_positions: list[tuple[float, float]] = []

            def clear_badge(position: tuple[float, float]) -> tuple[float, float]:
                bx, by = position
                # Opposing loop edges can share a row gap. Give each badge
                # its own free position without moving it over source text.
                candidates = [(bx + dx, by + dy) for dx, dy in
                              [(0, 0), (18, 0), (-18, 0), (36, 0), (-36, 0),
                               (0, 16), (0, -16), (0, 32), (0, -32), (0, 48), (0, -48),
                               (54, 0), (-54, 0), (0, 64), (0, -64)]]
                for cx, cy in candidates:
                    if not (8 <= cx <= body_w - 8 and graph_bottom + 6 <= cy <= top - 6):
                        continue
                    if any(abs(cx - px) < 18 and abs(cy - py) < 15 for px, py in badge_positions):
                        continue
                    if any(x - 8 < cx < x + width + 8 and y - 7 < cy < y + height + 7
                           for data in boxes.values() for x, y, width, height in [data["box"]]):
                        continue
                    badge_positions.append((cx, cy))
                    return cx, cy
                raise ValueError(f"Code diagram {map_value['id']} has no clear edge-badge position; refine the diagram geometry.")

            for number, edge in self.chunk["internal"]:
                source, target = boxes[edge["from"]], boxes[edge["to"]]
                sx, sy, sw, sh = source["box"]
                tx, ty, tw, th = target["box"]
                smx, smy, tmx, tmy = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
                if source["row"] == target["row"]:
                    start, end = ((sx + sw, smy), (tx, tmy)) if tx > sx else ((sx, smy), (tx + tw, tmy))
                    points, badge = [start, end], ((start[0] + end[0]) / 2, smy)
                elif abs(smx - tmx) < 1 and abs(source["row"] - target["row"]) == 1:
                    start, end = ((smx - 5, sy), (tmx - 5, ty + th)) if target["row"] > source["row"] else ((smx + 5, sy + sh), (tmx + 5, ty))
                    points, badge = [start, end], (start[0] + 13, (start[1] + end[1]) / 2)
                else:
                    spine = 7 if source["wide"] or target["wide"] else body_w / 2
                    start = (sx, smy) if source["wide"] or sx > spine else (sx + sw, smy)
                    end = (tx, tmy) if target["wide"] or tx > spine else (tx + tw, tmy)
                    points = [start, (spine, smy), (spine, tmy), end]
                    badge = (spine, (smy + tmy) / 2)
                self.arrow(points, edge, number, clear_badge(badge), badge)
            for number, edge, caption_y in incoming_positions:
                target = boxes[edge["to"]]
                tx, ty, tw, th = target["box"]
                right = tx > body_w / 2
                spine = body_w - 6 if right else 6
                end = (tx + tw, ty + th / 2) if right else (tx, ty + th / 2)
                self.arrow([(spine, caption_y), (spine, end[1]), end], edge)
            footer_top = graph_bottom - 9
            for number, edge, text in self.chunk["outgoing"]:
                caption_height = paragraph_height(text, body_w - 30, "key", True)
                source = boxes[edge["from"]]
                sx, sy, sw, sh = source["box"]
                right = sx > body_w / 2
                spine = body_w - 6 if right else 6
                start = (sx + sw, sy + sh / 2) if right else (sx, sy + sh / 2)
                end = (spine, footer_top - caption_height / 2)
                self.arrow([start, (spine, start[1]), end], edge)
                footer_top -= self.text(text, 22, footer_top, body_w - 30, "key", True) + 6
            if self.chunk["key_grid"]:
                for row in self.chunk["key_grid"]:
                    heights = [self.text(text, column * (body_w + 16) / 2, footer_top,
                                         (body_w - 16) / 2, "key", True)
                               for column, text in enumerate(row)]
                    footer_top -= max(heights) + 3
            else:
                for text in self.chunk["key"]:
                    footer_top -= self.text(text, 0, footer_top, body_w, "key", True) + 3
            for data in boxes.values():
                self.draw_node(data["node"], data["metric"], data["box"])
            legend = ("Calls follow startup; DATA is a declaration dependency. Session callback runs later. '+' wraps source; click cards for deeper diagrams."
                      if self.plan["compact"] else
                      "MAIN = emphasized path; SUPPORT / dashed dependency = supporting work. '+' = wrapped source continuation. Literal excerpts; surrounding code remains linked.")
            self.text(legend, 0, 13, body_w, "small")
            if footer_top < 24:
                raise ValueError(f"Code diagram {map_value['id']} part {self.part + 1} overlaps its legend.")

    story: list[Any] = [Heading("Code-flowchart drill-downs", "code-index"),
                        p("Open a scenario box in the execution handbook to reach these deeper graphical diagrams. Each code card contains numbered literal source lines; bold main paths and lighter supporting paths distinguish the selected behavior from prerequisites. Called helpers can link to another diagram."),
                        p("These are selected captured statements, not full function bodies or recorded traces. Complete implementations remain in the source explorer and implementation PDF. Long diagrams continue through explicit linked arrows across parts; no source line is shortened or replaced with an ellipsis.", "small"),
                        p(f"Source font: {mono_font}, {code_size} pt. Tabs expand to four spaces; unsupported source glyphs use explicit Unicode escapes. Snapshot {model.get('generated_at', '')}; generated on request and may be stale.", "small")]
    if any(map_value.get("id") == "main-to-widgets" for map_value in maps):
        story += [p("<b>Start here:</b> " + link("main() to widget definitions", "#" + _dest("map", "main-to-widgets"))
                    + ". Follow the startup calls into the application constructor, widget declarations, and widget-creation loop.", "body", True)]
    rows = [["Detailed code diagram", "Scope", "Parts"]]
    for plan in plans:
        map_value = plan["map"]
        rows.append([link(map_value.get("title", map_value["id"]), "#" + _dest("map", map_value["id"])),
                     _esc(map_value.get("scope") or map_value.get("summary", "")), str(len(plan["chunks"]))])
    index = Table([[p(cell, "tablehead" if i == 0 else "table", True) for cell in row]
                   for i, row in enumerate(rows)], colWidths=[300, 388, body_w - 688], repeatRows=1,
                  hAlign="LEFT", splitByRow=True)
    index.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafb")]),
        ("LINEBELOW", (0, 0), (-1, -1), .4, rule),
    ]))
    story += [index, Spacer(1, 8), p(link("Up: execution scenario chooser", "03-execution-flows.pdf") + " | " + link("Implementation listings", "01-code-walkthroughs.pdf") + " | " + link("Compiler declarations", "02-compiler-reference.pdf"), "small", True)]
    for plan in plans:
        for part in range(len(plan["chunks"])):
            story += [PageBreak(), SetMap(plan["map"]), CodeChart(plan, part)]
    story += [PageBreak(), SetMap(None), Heading("Diagram evidence and scope", "code-evidence"),
              p("These notes preserve the selected-path boundaries and source context. Use the return link to resume the graphical diagram; complete source bodies remain in the implementation handbook and explorer.", "small")]
    for plan in plans:
        map_value = plan["map"]
        story += [EvidenceHeading(map_value.get("title", map_value["id"]), _dest("evidence", map_value["id"])),
                  p(link("Return to code diagram", "#" + _dest("map", map_value["id"])) + " | " + parent_links(map_value), "small", True),
                  p(map_value.get("summary", ""), "small"),
                  p("<b>Scope:</b> " + _esc(map_value.get("scope", "Selected captured source statements.")), "small", True)]
        evidence_rows = []
        for node in map_value.get("nodes", []):
            implementation = printed_source(node)
            if not node.get("note") and not implementation:
                continue
            title = link(f"N{plan['numbers'][node['id']]}: {node.get('title', node['id'])}", "#" + _dest("node", map_value["id"], node["id"]))
            context = _esc(node.get("note", ""))
            if implementation:
                context += ("<br/>" if context else "") + implementation
            evidence_rows.append([p(title, "table", True), p(context, "table", True)])
        if evidence_rows:
            table = Table(evidence_rows, colWidths=[260, body_w - 260], hAlign="LEFT", splitByRow=True)
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), .3, rule),
            ]))
            story += [table]
    doc = CodeDoc()
    doc.build(story)
    refs = model.setdefault("print_references", {})
    refs.setdefault("code_maps", {}).update(doc.map_pages)
    refs.setdefault("code_nodes", {}).update(doc.node_pages)
    refs.setdefault("volumes", {})["code-flowcharts"] = {"pdf": PDF_NAME, "pages": doc.page,
                                                       "maps": len(maps), "nodes": len(doc.node_pages)}
    return "pdf/" + PDF_NAME
