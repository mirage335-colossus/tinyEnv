"""Print the separately authored GUI mental model with source-backed links.

Only the supplied captured model is read. Rendering these static explanations
does not invoke AI, application builds, tests, or project commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape
import re
import unicodedata


PDF_NAME = "AI-AUTHORED__GUI-MENTAL-MODEL.pdf"
HTML_NAME = "AI-AUTHORED__GUI-MENTAL-MODEL.html"


def _plain(value: Any) -> str:
    value = str(value if value is not None else "")
    for old, new in (("\u2013", "-"), ("\u2014", "-"), ("\u2018", "'"),
                     ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                     ("\u2192", " -> "), ("\u2190", " <- ")):
        value = value.replace(old, new)
    return unicodedata.normalize("NFKD", value).encode("ascii", "backslashreplace").decode("ascii")


def _esc(value: Any) -> str:
    return escape(_plain(value), {'"': "&quot;"})


def _bookmark(diagram_id: str) -> str:
    return "concept-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(diagram_id))


def render_concept_pdf(model: dict[str, Any], output: Path) -> str:
    """Write the AI-authored guide and record each conceptual diagram page."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Paragraph
    except ImportError as exc:
        raise ImportError("Conceptual-guide PDF output needs ReportLab. Install the documentation "
                          "tool's requirements or run with --no-pdf.") from exc

    guide = model.get("conceptual_guide") or {}
    diagrams = guide.get("diagrams", [])
    if not diagrams:
        raise ValueError("The conceptual GUI guide does not contain diagrams.")
    output = Path(output)
    (output / "pdf").mkdir(parents=True, exist_ok=True)
    filename = output / "pdf" / PDF_NAME
    html_name = Path(str(guide.get("html_file") or HTML_NAME)).name
    ink, muted, blue, rule = [colors.HexColor(x) for x in ("#173849", "#526773", "#256b91", "#cad8df")]
    palettes = {
        "call": ("#f4f9fc", "#80a8bc"), "data": ("#f0faf7", "#61a594"),
        "application": ("#edf6fb", "#4e96b9"), "boundary": ("#f6f1fc", "#a28bbc"),
        "backend": ("#f4f6f8", "#a1b2bc"), "core": ("#eff8f1", "#78a77d"),
    }
    edge_colors = {"call": "#608fa8", "data": "#479680", "event": "#b18c49",
                   "return": "#899aa4", "step": "#899aa4"}
    styles = {
        "cover": ParagraphStyle("concept-cover", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=ink),
        "title": ParagraphStyle("concept-title", fontName="Helvetica-Bold", fontSize=19, leading=22, textColor=ink),
        "heading": ParagraphStyle("concept-heading", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=ink),
        "question": ParagraphStyle("concept-question", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=ink),
        "body": ParagraphStyle("concept-body", fontName="Helvetica", fontSize=11, leading=14, textColor=ink),
        "small": ParagraphStyle("concept-small", fontName="Helvetica", fontSize=9.5, leading=12, textColor=muted),
        "card-title": ParagraphStyle("concept-card-title", fontName="Helvetica-Bold", fontSize=14, leading=16, textColor=ink),
        "card-subtitle": ParagraphStyle("concept-card-subtitle", fontName="Helvetica", fontSize=11, leading=13, textColor=ink),
        "card-link": ParagraphStyle("concept-card-link", fontName="Helvetica", fontSize=9, leading=11, textColor=blue),
        "edge": ParagraphStyle("concept-edge", fontName="Helvetica", fontSize=9.5, leading=12, textColor=ink),
    }
    c = canvas.Canvas(str(filename), pagesize=letter)
    c.setTitle(_plain(guide.get("title", "GUI mental model")) + " - AI-AUTHORED")
    c.setAuthor(_plain(guide.get("authorship", "AI-authored conceptual explanation")))
    c.setSubject("A simplified GUI mental model with links into captured source diagrams")

    def link(label: Any, target: str) -> str:
        return '<link href="' + _esc(target) + '" color="#256b91">' + _esc(label) + "</link>"

    def para(value: Any, width: float, style: str = "body", raw: bool = False) -> tuple[Any, float]:
        p = Paragraph(str(value) if raw else _esc(value), styles[style])
        return p, p.wrap(width, 2000)[1]

    def text(value: Any, x: float, top: float, width: float, style: str = "body", raw: bool = False) -> float:
        p, h = para(value, width, style, raw)
        p.drawOn(c, x, top - h)
        return h

    def source_target(node: dict[str, Any]) -> str:
        ref = node.get("source_ref") or {}
        if ref.get("file_id"):
            return "../index.html#source/" + quote(str(ref["file_id"]), safe="") + "/" + str(ref.get("line") or 1)
        return ""

    def detail_target(node: dict[str, Any]) -> tuple[str, str]:
        detail = node.get("detail") or {}
        refs = model.get("print_references", {})
        if detail.get("map"):
            record = refs.get("code_nodes", {}).get(str(detail["map"]) + "/" + str(detail.get("node", ""))) if detail.get("node") else None
            record = record or refs.get("code_maps", {}).get(str(detail["map"]))
            if record:
                return record["pdf"] + "#page=" + str(record["page"]), "Source-backed diagram p" + str(record["page"])
            return "../index.html#code/" + quote(str(detail["map"]), safe="") + ("/" + quote(str(detail["node"]), safe="") if detail.get("node") else ""), "Source-backed diagram in explorer"
        source = source_target(node)
        return (source, "Captured source") if source else ("", "")

    def decorate(page_w: float, page_h: float, diagram: dict[str, Any] | None = None) -> None:
        c.setFillColor(colors.HexColor("#e8bd57"))
        c.roundRect(32, page_h - 28, 212, 16, 3, fill=1, stroke=0)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, page_h - 23, "AI-AUTHORED / CONCEPTUAL GUIDE")
        c.setFillColor(muted)
        c.setFont("Helvetica", 8)
        c.drawRightString(page_w - 32, page_h - 23, f"GUI mental model | {c.getPageNumber()}")
        c.setStrokeColor(rule)
        c.line(32, 31, page_w - 32, 31)
        c.setFillColor(blue)
        c.drawString(32, 18, "Up: guide contents")
        c.linkRect("", "concept-index", (32, 15, 104, 26), relative=0)
        c.drawString(119, 18, "Interactive guide")
        url = "../" + html_name + ("#" + quote(str(diagram["id"]), safe="") if diagram else "")
        c.linkURL(url, (119, 15, 187, 26), relative=0)
        c.setFillColor(muted)
        c.drawRightString(page_w - 32, 18, _plain(model.get("generated_at", "")) + " | On-request snapshot")

    # A separate cover makes the authorship and simplified scope explicit.
    page_w, page_h = letter
    c.bookmarkPage("concept-index")
    c.addOutlineEntry("AI-authored GUI mental model", "concept-index", 0)
    decorate(page_w, page_h)
    top, width = page_h - 55, page_w - 64
    top -= text(guide.get("title", "GUI mental model"), 32, top, width, "cover") + 14
    top -= text(guide.get("intro", "A simplified map of the example GUI and its source-backed implementation."), 32, top, width) + 10
    top -= text("This separately labeled guide contains static AI-authored explanations. The local documentation builder renders it without calling AI. Follow its boxes into the captured code diagrams for implementation details.", 32, top, width, "small") + 9
    top -= text(PDF_NAME, 32, top, width, "small") + 6
    if guide.get("authorship"):
        top -= text("<b>Authorship:</b> " + _esc(guide["authorship"]), 32, top, width, "small", True) + 3
    if guide.get("authored_at"):
        top -= text("Authored: " + _plain(guide["authored_at"]), 32, top, width, "small") + 10
    if guide.get("source_status") == "verified":
        top -= text(f"Source links checked: {guide.get('source_anchor_count', 0)} anchors. The explanation remains separately authored conceptual guidance.", 32, top, width, "small") + 8
    elif guide.get("source_status"):
        warning_count = len(guide.get("source_warnings", []))
        top -= text(f"<b>Review required:</b> {warning_count} source links could not be matched in this capture. "
                    "Affected cards show SOURCE REVIEW. " + link("See source-link details in the interactive guide", "../" + html_name)
                    + ".", 32, top, width, "small", True) + 6
    for diagram in diagrams:
        heading = link(diagram.get("title", diagram["id"]), "#" + _bookmark(diagram["id"]))
        top -= text(heading, 32, top, width, "heading", True) + 3
        top -= text(diagram.get("question", ""), 32, top, width, "body") + 10
    if guide.get("limits"):
        top -= text("Reading this guide", 32, top, width, "heading") + 4
        for limit in guide["limits"]:
            top -= text("- " + _plain(limit), 32, top, width, "small") + 3
    if top < 42:
        raise ValueError("The conceptual guide cover exceeds one readable page; shorten the authored introduction/limits.")
    c.showPage()

    diagram_pages: dict[str, Any] = {}
    for diagram in diagrams:
        nodes, edges = diagram.get("nodes", []), diagram.get("edges", [])
        if not nodes:
            raise ValueError(f"Conceptual diagram {diagram['id']} has no nodes.")
        columns = sorted({int(n.get("column", 0)) for n in nodes})
        rows = sorted({int(n.get("row", 0)) for n in nodes})
        page_w, page_h = letter if len(rows) >= 4 else landscape(letter)
        c.setPageSize((page_w, page_h))
        c.bookmarkPage(_bookmark(diagram["id"]))
        c.addOutlineEntry(_plain(diagram.get("title", diagram["id"])), _bookmark(diagram["id"]), 1)
        diagram_pages[diagram["id"]] = {"pdf": PDF_NAME, "page": c.getPageNumber()}
        decorate(page_w, page_h, diagram)
        width, top = page_w - 64, page_h - 48
        top -= text(diagram.get("title", diagram["id"]), 32, top, width, "title") + 8
        if diagram.get("question"):
            top -= text(diagram["question"], 32, top, width, "question") + 6
        if diagram.get("summary"):
            top -= text(diagram["summary"], 32, top, width, "small") + 8

        numbers = {node["id"]: i for i, node in enumerate(nodes, 1)}
        edge_key = ["<b>" + _esc(f"{i}. N{numbers[edge['from']]} -> N{numbers[edge['to']]}") + "</b> "
                    + _esc(f"[{edge.get('kind', 'step')}] {edge.get('label', '')}")
                    for i, edge in enumerate(edges, 1)]
        key_width = (width - 18) / 2
        key_rows = [edge_key[i:i + 2] for i in range(0, len(edge_key), 2)]
        key_h = sum(max(para(value, key_width, "edge", True)[1] for value in row) + 4 for row in key_rows)
        notes = diagram.get("notes", [])
        notes_h = sum(para("- " + _plain(note), width, "small")[1] + 3 for note in notes)
        bottom = 54 + key_h + notes_h + (7 if notes else 0)
        gap_x, outer = 44, 12
        card_w = (width - 2 * outer - gap_x * (len(columns) - 1)) / len(columns)
        node_info = {}
        row_heights: dict[int, float] = {}
        for node in nodes:
            target, target_label = detail_target(node)
            title_h = para(node.get("title", "Concept"), card_w - 18, "card-title")[1]
            subtitle_h = para(node.get("subtitle", ""), card_w - 18, "card-subtitle")[1] if node.get("subtitle") else 0
            h = 29 + title_h + (subtitle_h + 4 if subtitle_h else 0)
            node_info[node["id"]] = {"node": node, "target": target, "target_label": target_label,
                                      "height": max(57, h)}
            row = int(node.get("row", 0))
            row_heights[row] = max(row_heights.get(row, 0), h, 57)
        row_gap = 22
        graph_h = sum(row_heights.values()) + row_gap * (len(rows) - 1)
        if top - bottom < graph_h:
            # Keep concept labels at 14 pt; only reduce the empty row gap.
            row_gap = max(16, (top - bottom - sum(row_heights.values())) / max(1, len(rows) - 1))
            graph_h = sum(row_heights.values()) + row_gap * (len(rows) - 1)
        if top - bottom < graph_h - .1:
            raise ValueError(f"Conceptual diagram {diagram['id']} exceeds a readable one-page layout. Shorten its subtitles or explanatory notes.")
        row_top = top - max(0, (top - bottom - graph_h) / 2)
        row_ys = {}
        for row in rows:
            row_ys[row] = row_top - row_heights[row]
            row_top -= row_heights[row] + row_gap
        boxes = {}
        for node_id, info in node_info.items():
            node = info["node"]
            column, row = columns.index(int(node.get("column", 0))), int(node.get("row", 0))
            x = 32 + outer + column * (card_w + gap_x)
            y, h = row_ys[row], row_heights[row]
            boxes[node_id] = (x, y, card_w, h)

        badges = []
        for number, edge in enumerate(edges, 1):
            sx, sy, sw, sh = boxes[edge["from"]]
            tx, ty, tw, th = boxes[edge["to"]]
            smx, smy, tmx, tmy = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
            sr, tr = int(node_info[edge["from"]]["node"].get("row", 0)), int(node_info[edge["to"]]["node"].get("row", 0))
            if sr == tr:
                start, end = ((sx + sw, smy), (tx, tmy)) if tx > sx else ((sx, smy), (tx + tw, tmy))
                points, badge = [start, end], ((start[0] + end[0]) / 2, smy)
            elif abs(smx - tmx) < 1 and abs(rows.index(sr) - rows.index(tr)) == 1:
                start, end = ((smx - 4, sy), (tmx - 4, ty + th)) if tr > sr else ((smx + 4, sy + sh), (tmx + 4, ty))
                points, badge = [start, end], (start[0] + 12, (start[1] + end[1]) / 2)
            else:
                if abs(smx - tmx) < 1:
                    spine = sx - 8 if sx <= page_w / 2 else sx + sw + 8
                else:
                    spine = (min(sx, tx) + card_w + max(sx, tx)) / 2
                start = (sx, smy) if spine < sx else (sx + sw, smy)
                end = (tx, tmy) if spine < tx else (tx + tw, tmy)
                points = [start, (spine, smy), (spine, tmy), end]
                badge = (spine, (smy + tmy) / 2)
            color = colors.HexColor(edge_colors.get(edge.get("kind", "step"), "#526773"))
            c.setStrokeColor(color)
            c.setFillColor(color)
            c.setLineWidth(1.5 if edge.get("kind") == "call" else 1.1)
            c.setDash(3, 2) if edge.get("kind") in {"data", "event"} else c.setDash(1, 2) if edge.get("kind") == "return" else c.setDash()
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
                arms = [(end[0] - sign * 5, end[1] - 3), (end[0] - sign * 5, end[1] + 3)]
            else:
                sign = 1 if dy > 0 else -1
                arms = [(end[0] - 3, end[1] - sign * 5), (end[0] + 3, end[1] - sign * 5)]
            for arm in arms:
                c.line(*end, *arm)
            bx, by = badge
            for offset in (0, 18, -18, 36, -36):
                candidate = (bx + offset, by)
                if not any(abs(candidate[0] - px) < 17 and abs(candidate[1] - py) < 15 for px, py in badges):
                    bx, by = candidate
                    break
            badges.append((bx, by))
            if (bx, by) != badge:
                c.setLineWidth(.5)
                c.line(*badge, bx, by)
            c.setFillColor(colors.white)
            c.roundRect(bx - 7, by - 6, 14, 12, 3, stroke=1, fill=1)
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(bx, by - 3, str(number))

        for node_id, info in node_info.items():
            node, box = info["node"], boxes[node_id]
            x, y, w, h = box
            fill, border = palettes.get(node.get("kind", "call"), palettes["call"])
            c.setFillColor(colors.HexColor(fill))
            c.setStrokeColor(colors.HexColor(border))
            c.setLineWidth(1.3)
            c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
            if info["target"]:
                c.linkURL(info["target"], (x, y, x + w, y + h), relative=0)
            missing = (node.get("source_ref") or {}).get("status") == "missing"
            c.setFillColor(colors.HexColor("#946613") if missing else ink)
            c.setFont("Helvetica-Bold", 8.5)
            caption = f"N{numbers[node_id]} | {_plain(node.get('kind', 'call')).upper()}"
            if missing:
                caption += " | SOURCE REVIEW"
            elif "#page=" in info["target"]:
                caption += " | Code p" + info["target"].split("#page=", 1)[1]
            elif info["target"]:
                caption += " | Source in explorer"
            c.drawString(x + 9, y + h - 13, caption)
            exact_source = source_target(node)
            if exact_source:
                c.setFillColor(blue)
                c.drawRightString(x + w - 9, y + h - 13, "Source")
                c.linkURL(exact_source, (x + w - 44, y + h - 15, x + w - 7, y + h - 4), relative=0)
            cursor = y + h - 20
            cursor -= text(node.get("title", "Concept"), x + 9, cursor, w - 18, "card-title")
            if node.get("subtitle"):
                cursor -= 4
                cursor -= text(node["subtitle"], x + 9, cursor, w - 18, "card-subtitle")
            if cursor < y + 6:
                raise ValueError(f"Conceptual card {diagram['id']}/{node_id} clipped its label.")
        cursor = bottom - 10
        for row in key_rows:
            heights = [text(value, 32 + column * (key_width + 18), cursor, key_width, "edge", True)
                       for column, value in enumerate(row)]
            cursor -= max(heights) + 4
        if notes:
            cursor -= 7
            for note in notes:
                cursor -= text("- " + _plain(note), 32, cursor, width, "small") + 3
        if cursor < 38:
            raise ValueError(f"Conceptual diagram {diagram['id']} evidence notes overlap its footer.")
        c.showPage()

    c.save()
    refs = model.setdefault("print_references", {})
    refs.setdefault("concept_diagrams", {}).update(diagram_pages)
    refs.setdefault("volumes", {})["conceptual-gui"] = {"pdf": PDF_NAME, "pages": len(diagrams) + 1,
                                                       "maps": len(diagrams), "nodes": sum(len(d.get("nodes", [])) for d in diagrams)}
    return "pdf/" + PDF_NAME
