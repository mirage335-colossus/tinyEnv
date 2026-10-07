"""Print curated execution scenarios as linked graphical flowcharts.

Only the captured documentation model is consumed. No application source is
read, changed, built, tested, or executed by this renderer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape
import re
import unicodedata


PDF_NAME = "03-execution-flows.pdf"


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
    return "flow-" + kind + "-" + re.sub(r"[^A-Za-z0-9_-]", "_", map_id + ("-" + node_id if node_id else ""))


def _source_url(reference: dict[str, Any]) -> str:
    return "../index.html#source/" + quote(str(reference.get("file_id") or reference.get("path", "")), safe="") + "/" + str(reference.get("line") or 1)


def _flow_url(map_id: str, node_id: str = "") -> str:
    return "../index.html#flow/" + quote(map_id, safe="") + ("/" + quote(node_id, safe="") if node_id else "")


def render_flow_pdf(model: dict[str, Any], output: Path) -> str:
    """Write the execution handbook and publish chart/detail first-page refs."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.platypus import (
            BaseDocTemplate, Flowable, Frame, KeepTogether, NextPageTemplate,
            PageBreak, PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise ImportError("Execution-flow PDF output needs ReportLab. Install the documentation "
                          "tool's requirements or run with --no-pdf.") from exc

    maps = model.get("flow_maps", [])
    if not maps:
        raise ValueError("No flow_maps are available for the execution-flow PDF.")
    output = Path(output)
    (output / "pdf").mkdir(parents=True, exist_ok=True)
    filename = output / "pdf" / PDF_NAME
    page_w, page_h = landscape(letter)
    margin = 26
    body_w, body_h = page_w - 2 * margin, page_h - 91
    ink, muted, rule = (colors.HexColor(x) for x in ("#173849", "#526773", "#cad8df"))
    role_colors = {
        "ENTRY": ("#e3edf8", "#356aa0"), "CALL": ("#e6f2fa", "#347d9e"),
        "PROCESS": ("#e7f2eb", "#3a805a"), "DECISION": ("#fff0d5", "#a87623"),
        "EVENT": ("#f0eafa", "#8063a5"), "OUTPUT": ("#eef3f5", "#6a8591"),
    }
    edge_colors = {
        "call": "#2f719b", "process": "#3f7a58", "conditional": "#a37123",
        "return": "#627987", "event": "#8063a5", "step": "#627987",
    }
    edge_labels = {"call": "call", "process": "subprocess/command", "conditional": "condition",
                   "return": "return", "event": "event/completion", "step": "local step/order"}
    styles = {
        "title": ParagraphStyle("flow-title", fontName="Helvetica-Bold", fontSize=17, leading=20,
                                textColor=ink, spaceAfter=9, keepWithNext=True),
        "chapter": ParagraphStyle("flow-chapter", fontName="Helvetica-Bold", fontSize=15, leading=18,
                                  textColor=ink, spaceAfter=8, keepWithNext=True),
        "heading": ParagraphStyle("flow-heading", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                                  textColor=ink, spaceBefore=7, spaceAfter=5, keepWithNext=True),
        "body": ParagraphStyle("flow-body", fontName="Helvetica", fontSize=9.6, leading=12.3,
                               textColor=ink, spaceAfter=5),
        "small": ParagraphStyle("flow-small", fontName="Helvetica", fontSize=9, leading=11.4,
                                textColor=muted, spaceAfter=4),
        "table": ParagraphStyle("flow-table", fontName="Helvetica", fontSize=9.3, leading=12,
                                textColor=ink),
        "tablehead": ParagraphStyle("flow-tablehead", fontName="Helvetica-Bold", fontSize=9.3,
                                    leading=12, textColor=ink),
        "node-title": ParagraphStyle("flow-node-title", fontName="Helvetica-Bold", fontSize=9.8,
                                     leading=11.8, textColor=ink),
        "node-body": ParagraphStyle("flow-node-body", fontName="Helvetica", fontSize=9.1,
                                    leading=10.9, textColor=ink),
        "node-source": ParagraphStyle("flow-node-source", fontName="Helvetica", fontSize=9,
                                      leading=10.7, textColor=muted),
        "edge-key": ParagraphStyle("flow-edge-key", fontName="Helvetica", fontSize=9,
                                   leading=11.1, textColor=ink, spaceAfter=4),
        "question": ParagraphStyle("flow-question", fontName="Helvetica", fontSize=10,
                                   leading=12, textColor=muted),
        "code": ParagraphStyle("flow-code", fontName="Courier", fontSize=9, leading=11.3,
                               textColor=ink, leftIndent=5, rightIndent=5,
                               backColor=colors.HexColor("#edf3f6"), borderPadding=5,
                               spaceBefore=3, spaceAfter=5),
    }
    for style in styles.values():
        style.splitLongWords = True

    def link(label: Any, target: str) -> str:
        return '<link href="' + _esc(target) + '" color="#256b91">' + _esc(label) + "</link>"

    def p(value: Any, style: str = "body", raw: bool = False) -> Any:
        return Paragraph(str(value) if raw else _esc(value), styles[style])

    def printed_link(reference: dict[str, Any]) -> str:
        printed = model.get("print_references", {})
        record = printed.get("symbols", {}).get(str(reference.get("symbol_id", "")))
        if not record:
            record = printed.get("locations", {}).get(f"{reference.get('file_id', '')}:{reference.get('line') or 1}")
        if not record or not record.get("pdf") or not record.get("page"):
            return ""
        return link(f"Read in PDF, p{record['page']}", record["pdf"] + "#page=" + str(record["page"]))

    def child_link(node: dict[str, Any]) -> str:
        child = node.get("child") or {}
        if not child.get("map"):
            return ""
        printed = model.get("print_references", {})
        record = printed.get("code_nodes", {}).get(child["map"] + "/" + child["node"]) if child.get("node") else None
        record = record or printed.get("code_maps", {}).get(child["map"])
        # The first overview pass establishes parent pages before the code
        # book is paginated. Its second pass fills these exact child pages.
        return (record["pdf"] + "#page=" + str(record["page"])) if record else "04-code-flowcharts.pdf"

    def ref_text(reference: dict[str, Any]) -> str:
        path, line = reference.get("path", ""), reference.get("line")
        label = reference.get("label", "")
        prefix = ("<b>" + _esc(label) + ":</b> ") if label else ""
        if reference.get("status") == "missing" or not path:
            return prefix + "<b>Review required:</b> " + _esc(f"{path}:{line}" if path else "source anchor not captured")
        if str(path).startswith("@"):
            prefix += "<b>Read-only supplier evidence:</b> "
        text = prefix + link(f"{path}:{line or 1}", _source_url(reference))
        if reference.get("symbol_id"):
            text += " | " + link("Interactive function/type", "../index.html#symbol/" + quote(str(reference["symbol_id"]), safe=""))
        book_link = printed_link(reference)
        if book_link:
            text += " | " + book_link
        return text

    class Heading(Paragraph):
        def __init__(self, text: str, destination: str, level: int, style: str = "heading",
                     map_id: str = "", node_id: str = "") -> None:
            super().__init__(_esc(text), styles[style])
            self.label, self.destination, self.level = _plain(text), destination, level
            self.map_id, self.node_id = map_id, node_id

    class FlowDoc(BaseDocTemplate):
        def __init__(self) -> None:
            super().__init__(str(filename), pagesize=(page_w, page_h), leftMargin=margin,
                             rightMargin=margin, topMargin=54, bottomMargin=37,
                             title=f"{model.get('title', 'Software foundation')}: execution flows",
                             author="Local source-map generator", subject="Curated, source-linked execution scenarios")
            self.current_map: dict[str, Any] | None = None
            self.map_pages: dict[str, dict[str, Any]] = {}
            self.node_pages: dict[str, dict[str, Any]] = {}
            full = Frame(margin, 37, body_w, body_h, leftPadding=0, rightPadding=0,
                         topPadding=0, bottomPadding=0)
            gap, col_w = 24, (body_w - 24) / 2
            left = Frame(margin, 37, col_w, body_h, leftPadding=0, rightPadding=0,
                         topPadding=0, bottomPadding=0)
            right = Frame(margin + col_w + gap, 37, col_w, body_h, leftPadding=0,
                          rightPadding=0, topPadding=0, bottomPadding=0)
            self.addPageTemplates([
                PageTemplate("full", frames=[full], onPage=self.decorate),
                PageTemplate("details", frames=[left, right], onPage=self.decorate),
            ])

        def decorate(self, c: Any, doc: Any) -> None:
            c.saveState()
            header = _plain((self.current_map or {}).get("title", "Execution-flow chooser"))
            header_size = min(15, max(10, (body_w - 115) / max(1, stringWidth(header, "Helvetica-Bold", 1))))
            c.setFont("Helvetica-Bold", header_size)
            c.setFillColor(ink)
            c.drawString(margin, page_h - 27, header)
            c.setFont("Helvetica", 8)
            c.setFillColor(muted)
            c.drawRightString(page_w - margin, page_h - 27, f"Execution flows | {doc.page}")
            c.setStrokeColor(rule)
            c.line(margin, page_h - 38, page_w - margin, page_h - 38)
            c.line(margin, 28, page_w - margin, 28)
            c.setFillColor(colors.HexColor("#256b91"))
            c.drawString(margin, 16, "Scenario index")
            c.linkRect("", "flow-index", (margin, 13, margin + 55, 24), relative=0)
            x = margin + 72
            if self.current_map:
                c.drawString(x, 16, "Up to chart")
                c.linkRect("", _dest("chart", self.current_map["id"]), (x, 13, x + 45, 24), relative=0)
                x += 61
            c.drawString(x, 16, "Offline explorer")
            c.linkURL(_flow_url(self.current_map["id"]) if self.current_map else "../index.html#flows",
                      (x, 13, x + 62, 24), relative=0)
            c.setFillColor(muted)
            c.drawRightString(page_w - margin, 16,
                              _plain(model.get("generated_at", "")) + " | On-request snapshot; may be stale")
            c.restoreState()

        def afterFlowable(self, item: Any) -> None:
            if isinstance(item, Heading):
                self.canv.bookmarkPage(item.destination)
                self.canv.addOutlineEntry(item.label, item.destination, level=item.level, closed=item.level > 0)
                if item.map_id and item.node_id:
                    self.node_pages[item.map_id + "/" + item.node_id] = {"pdf": PDF_NAME, "page": self.page}
            elif isinstance(item, Chart):
                self.canv.bookmarkPage(_dest("chart", item.map["id"]))
                self.canv.addOutlineEntry(_plain(item.map.get("title", "Execution scenario")),
                                          _dest("chart", item.map["id"]), level=0)
                self.map_pages[item.map["id"]] = {"pdf": PDF_NAME, "page": self.page}

    class SetMap(Flowable):
        def __init__(self, map_value: dict[str, Any]) -> None:
            super().__init__()
            self.map, self.width, self.height = map_value, 0, 0

        def draw(self) -> None:
            self._doctemplate.current_map = self.map

    class Chart(Flowable):
        def __init__(self, map_value: dict[str, Any]) -> None:
            super().__init__()
            self.map, self.width, self.height = map_value, body_w, body_h

        def wrap(self, aw: float, ah: float) -> tuple[float, float]:
            return self.width, self.height

        def text(self, value: str, x: float, top: float, width: float,
                 style: str, raw: bool = False) -> float:
            para = p(value, style, raw)
            _, height = para.wrap(width, self.height)
            para.drawOn(self.canv, x, top - height)
            return height

        def route(self, source: dict[str, Any], target: dict[str, Any], lane: int,
                  cell_w: float, cell_h: float, grid_top: float) -> tuple[Any, Any]:
            sx, sy, sw, sh = source["box"]
            tx, ty, tw, th = target["box"]
            sc, sr, tc, tr = source["column"], source["row"], target["column"], target["row"]
            smx, smy, tmx, tmy = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
            if sr == tr and abs(sc - tc) == 1:
                start, end = ((sx + sw, smy), (tx, tmy)) if tc > sc else ((sx, smy), (tx + tw, tmy))
                return [start, end], ((start[0] + end[0]) / 2, smy)
            if sc == tc and abs(sr - tr) == 1:
                port = -6 if tr > sr else 6
                start, end = ((smx + port, sy), (tmx + port, ty + th)) if tr > sr else ((smx + port, sy + sh), (tmx + port, ty))
                badge_x = smx + port + (14 if tr < sr else -14)
                return [start, end], (badge_x, max(start[1], end[1]) - 7)
            if sr == tr or abs(sr - tr) == 1:
                # Long branches use the empty row corridor. Separate the
                # incoming and outgoing top ports so a return does not cover
                # the arrowhead or numbered badge of another connection.
                if tr > sr:
                    start, end = (smx - 6, sy), (tmx - 6, ty + th)
                    corridor_y = grid_top - tr * cell_h
                elif tr < sr:
                    start, end = (smx + 6, sy + sh), (tmx + 6, ty)
                    corridor_y = grid_top - sr * cell_h
                else:
                    start, end = (smx + 6, sy + sh), (tmx - 6, ty + th)
                    corridor_y = grid_top - sr * cell_h
                points = [start, (start[0], corridor_y), (end[0], corridor_y), end]
                return points, ((start[0] + end[0]) / 2, corridor_y)
            # Long edges leave through a side gutter, follow the corridor
            # above the target row, then enter its top. Node text stays clear.
            going_right = tc >= sc
            gutter_x = (sc + 1) * cell_w - 4 if going_right else sc * cell_w + 4
            corridor_y = grid_top - tr * cell_h
            start = (sx + sw, smy) if going_right else (sx, smy)
            end = (tmx, ty + th)
            points = [start, (gutter_x, smy), (gutter_x, corridor_y), (tmx, corridor_y), end]
            return points, (gutter_x * .7 + tmx * .3, corridor_y)

        def arrow(self, points: list[Any], edge: dict[str, Any], number: int, badge: Any) -> None:
            c = self.canv
            color = colors.HexColor(edge_colors.get(edge.get("kind", "call"), "#627987"))
            c.setStrokeColor(color)
            c.setFillColor(color)
            c.setLineWidth(1.2)
            kind = edge.get("kind", "call")
            c.setDash(4, 2) if kind in {"conditional", "event"} else c.setDash(1, 2) if kind == "return" else c.setDash()
            path = c.beginPath()
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)
            c.drawPath(path)
            c.setDash()
            end, previous = points[-1], points[-2]
            dx, dy = end[0] - previous[0], end[1] - previous[1]
            if abs(dx) > abs(dy):
                sign = 1 if dx > 0 else -1
                arms = [(end[0] - sign * 5, end[1] + 3), (end[0] - sign * 5, end[1] - 3)]
            else:
                sign = 1 if dy > 0 else -1
                arms = [(end[0] + 3, end[1] - sign * 5), (end[0] - 3, end[1] - sign * 5)]
            for arm in arms:
                c.line(*end, *arm)
            bx, by = badge
            c.setFillColor(colors.white)
            c.roundRect(bx - 7, by - 6, 14, 12, 3, fill=1, stroke=1)
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(bx, by - 3, str(number))

        def draw(self) -> None:
            self.text(self.map.get("question", "Follow this captured execution scenario."),
                      0, self.height - 2, self.width, "question")
            key_w, gap = 174, 15
            grid_w, key_x = self.width - key_w - gap, self.width - key_w
            nodes = self.map.get("nodes", [])
            numbers = {n["id"]: f"N{i}" for i, n in enumerate(nodes, 1)}
            min_c = min((int(n.get("column", 0)) for n in nodes), default=0)
            min_r = min((int(n.get("row", 0)) for n in nodes), default=0)
            cols = max((int(n.get("column", 0)) - min_c for n in nodes), default=0) + 1
            rows = max((int(n.get("row", 0)) - min_r for n in nodes), default=0) + 1
            grid_top, grid_bottom = self.height - 43, 33
            cell_w, cell_h = grid_w / cols, (grid_top - grid_bottom) / rows
            gap_x, gap_y = 24, 30 if rows == 2 else 24
            box_w, box_h = cell_w - gap_x, cell_h - gap_y
            placed = {}
            for node in nodes:
                column, row = int(node.get("column", 0)) - min_c, int(node.get("row", 0)) - min_r
                x, y = column * cell_w + gap_x / 2, grid_top - (row + 1) * cell_h + gap_y / 2
                placed[node["id"]] = {"node": node, "column": column, "row": row, "box": (x, y, box_w, box_h)}
            badges = []
            for index, edge in enumerate(self.map.get("edges", []), 1):
                if edge.get("from") not in placed or edge.get("to") not in placed:
                    raise ValueError(f"Execution map {self.map['id']} contains an edge to an absent node.")
                points, badge = self.route(placed[edge["from"]], placed[edge["to"]], index, cell_w, cell_h, grid_top)
                candidates = [badge]
                if len(points) > 2:
                    lo, hi = sorted([points[-3][0], points[-2][0]])
                    for delta in (20, -20, 40, -40, 60, -60):
                        candidate = (badge[0] + delta, badge[1])
                        if lo + 7 <= candidate[0] <= hi - 7:
                            candidates.append(candidate)
                elif abs(points[0][0] - points[-1][0]) < 1:
                    # All sides of a vertical segment lie in an empty row
                    # gutter. Try both sides, including for short returns.
                    px = points[0][0]
                    for offset in (14, -14, 23, -23):
                        candidates.append((px + offset, badge[1]))
                        candidates.append((px + offset, (points[0][1] + points[-1][1]) / 2))
                else:
                    # A horizontal badge can move up/down within its empty
                    # column gutter without covering a neighboring card.
                    candidates.extend((badge[0], badge[1] + offset) for offset in (14, -14, 24, -24))
                clear = next((candidate for candidate in candidates if all(
                    abs(candidate[0] - bx) >= 18 or abs(candidate[1] - by) >= 14
                    for bx, by in badges)), None)
                if clear is None:
                    raise ValueError(f"Execution map {self.map['id']} needs more spacing for numbered edge badges.")
                badge = clear
                badges.append(badge)
                self.arrow(points, edge, index, badge)
            for data in placed.values():
                node = data["node"]
                x, y, w, h = data["box"]
                role = node.get("role", "CALL")
                fill, border = (colors.HexColor(value) for value in role_colors.get(role, role_colors["CALL"]))
                c = self.canv
                c.setFillColor(fill)
                c.setStrokeColor(border)
                c.setLineWidth(.95)
                c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
                child_target = child_link(node)
                if child_target:
                    c.linkURL(child_target, (x, y, x + w, y + h), relative=1)
                else:
                    c.linkRect("", _dest("node", self.map["id"], node["id"]), (x, y, x + w, y + h), relative=1)
                top = y + h - 8
                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(border)
                c.drawString(x + 7, top - 7, numbers[node["id"]] + " | " + _plain(role))
                top -= 19
                title = _esc(node.get("title", "")).replace("::", "::<br/>")
                title = re.sub(r"([A-Za-z_][A-Za-z_0-9]*)\.([A-Za-z_][A-Za-z_0-9]*)",
                               lambda match: match.group(0) if match.group(2) in {
                                   "sh", "py", "cpp", "hpp", "h", "c", "json", "yaml", "yml", "txt", "cmake", "toml"
                               } else match.group(1) + ".<br/>" + match.group(2), title)
                top -= self.text(title, x + 7, top, w - 14, "node-title", True) + 5
                path = node.get("path", "")
                if node.get("status") == "missing" or not path:
                    location = "REVIEW REQUIRED:<br/>source anchor not captured"
                else:
                    path_label = _esc(path)
                    if "/" in str(path):
                        prefix, basename = str(path).rsplit("/", 1)
                        path_label = _esc(prefix + "/") + "<br/>" + _esc(basename)
                    location = '<link href="' + _esc(_source_url(node)) + '" color="#256b91">' + path_label + "</link><br/><b>L" + _esc(node.get("line") or 1) + "</b>"
                    if str(path).startswith("@"):
                        location = "Read-only evidence:<br/>" + location
                if child_target:
                    location += "<br/>" + link("Evidence notes", "#" + _dest("node", self.map["id"], node["id"]))
                loc = p(location, "node-source", True)
                _, loc_h = loc.wrap(w - 14, h)
                summary = node.get("summary") or node.get("action", "")
                summary_para = p(summary, "node-body")
                _, summary_h = summary_para.wrap(w - 14, h)
                if summary_h + loc_h + 14 > top - y:
                    raise ValueError(f"Execution card {self.map['id']}/{node['id']} is too tall for readable print; shorten its chart summary or adjust its grid.")
                summary_para.drawOn(c, x + 7, top - summary_h)
                loc.drawOn(c, x + 7, y + 7)
            key_top = grid_top - 3
            key_top -= self.text("<b>Directed edge key</b>", key_x, key_top, key_w, "edge-key", True) + 6
            for number, edge in enumerate(self.map.get("edges", []), 1):
                kind = edge_labels.get(edge.get("kind", "call"), edge.get("kind", "call"))
                label = "<b>" + _esc(f"{number}. {numbers.get(edge['from'], '?')} -> {numbers.get(edge['to'], '?')}") + "</b> <font color='#526773'>[" + _esc(kind) + "]</font><br/>" + _esc(edge.get("label", ""))
                key_top -= self.text(label, key_x, key_top, key_w, "edge-key", True) + 5
            if self.map.get("edge_meaning"):
                key_top -= 6
                key_top -= self.text(self.map["edge_meaning"], key_x, key_top, key_w, "edge-key")
            if key_top < 35:
                raise ValueError(f"Execution map {self.map['id']} has too much edge-key text for one readable chart page.")
            legend_y = 12
            legend_x = 0
            c = self.canv
            for role, (fill, border) in role_colors.items():
                c.setFillColor(colors.HexColor(fill))
                c.setStrokeColor(colors.HexColor(border))
                c.roundRect(legend_x, legend_y - 1, 10, 9, 2, fill=1, stroke=1)
                c.setFont("Helvetica", 9)
                c.setFillColor(ink)
                c.drawString(legend_x + 14, legend_y, role)
                legend_x += 76 if role not in {"PROCESS", "DECISION"} else 93
            c.setFillColor(muted)
            c.setFont("Helvetica", 9)
            c.drawRightString(self.width, legend_y,
                              "Click a box for its code diagram" if any(n.get("child") for n in nodes)
                              else "Click a box for captured behavior")

    def node_details(map_value: dict[str, Any], node: dict[str, Any], number: int) -> list[Any]:
        parts = [Heading(f"N{number} | {node.get('role', 'CALL')} | {node.get('title', '')}",
                         _dest("node", map_value["id"], node["id"]), 2,
                         map_id=map_value["id"], node_id=node["id"])]
        behavior = node.get("action") or node.get("summary", "")
        if behavior:
            parts.append(p("<b>Captured behavior:</b> " + _esc(behavior), raw=True))
        if node.get("why"):
            parts.append(p("<b>Path context:</b> " + _esc(node["why"]), "small", True))
        references = {}
        for ref in [node] + list(node.get("references", [])):
            if ref.get("path") or ref.get("status") == "missing":
                references.setdefault((ref.get("path"), ref.get("line")), ref)
        if references:
            parts.append(p("<br/>".join(ref_text(ref) for ref in references.values()), "small", True))
        if child_link(node):
            parts.append(p(link("Open the code-level flowchart", child_link(node)), "small", True))
        snippet = str(node.get("snippet", ""))
        if snippet and (node.get("role") == "DECISION" or node.get("print_excerpt")):
            lines = snippet.splitlines()
            excerpt = "\n".join(lines[:4]).encode("ascii", "backslashreplace").decode("ascii")
            parts.append(p("Captured source excerpt", "small"))
            parts.append(Preformatted(excerpt, styles["code"], maxLineLength=63, splitChars=" ,", newLineChars="  "))
            if len(lines) > 4:
                parts.append(p(f"Print excerpt: 4 of {len(lines)} captured snippet lines; {len(lines) - 4} omitted here. Follow the source/PDF links for surrounding implementation.", "small"))
        parts.append(p(link("Up to chart", "#" + _dest("chart", map_value["id"])) + " | " +
                       link("Interactive scenario step", _flow_url(map_value["id"], node["id"])) +
                       " | " + _esc(node["id"]), "small", True))
        return [KeepTogether(parts), Spacer(1, 3)]

    story: list[Any] = [Heading("Choose an execution scenario", "flow-index", 0, "title"),
                        p("Follow these graphical paths to see how selected build tools and runtime functions lead to the next step. Each box links to its captured behavior and exact source anchors; implementation and compiler PDFs provide the deeper listings."),
                        p("These are curated scenarios reconstructed from source, not recorded dynamic traces or exact compiler control-flow graphs. Conditional branches, subprocess phases, asynchronous completions, and normal returns have distinct edge labels. Other platform paths and failure paths may exist.", "small"),
                        p("Snapshot: " + str(model.get("generated_at", "")) + ". Generated only on explicit request; this navigation snapshot may be stale.", "small")]
    rows = [["Execution flowchart", "Question / scope", "Captured steps"]]
    for map_value in maps:
        rows.append([link(map_value.get("title", map_value["id"]), "#" + _dest("chart", map_value["id"])),
                     _esc(map_value.get("question") or map_value.get("summary", "")),
                     str(len(map_value.get("nodes", [])))])
    chooser = Table([[p(cell, "tablehead" if i == 0 else "table", True) for cell in row]
                     for i, row in enumerate(rows)], colWidths=[238, 410, body_w - 648],
                    repeatRows=1, hAlign="LEFT", splitByRow=True)
    chooser.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3f6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafb")]),
        ("LINEBELOW", (0, 0), (-1, -1), .4, rule),
    ]))
    story += [chooser, Spacer(1, 8),
              p(link("Graphical edit paths", "00-edit-paths.pdf") + " | " + link("Implementation walkthroughs", "01-code-walkthroughs.pdf") + " | " + link("Compiler reference", "02-compiler-reference.pdf") + " | " + link("Interactive execution chooser", "../index.html#flows"), "small", True)]
    for map_value in maps:
        story += [SetMap(map_value), NextPageTemplate("full"), PageBreak(), Chart(map_value),
                  NextPageTemplate("details"), PageBreak(),
                  Heading("Captured behavior behind this scenario", _dest("details", map_value["id"]), 1, "chapter"),
                  p(map_value.get("summary", ""), "small"),
                  p(link("Up to flowchart", "#" + _dest("chart", map_value["id"])) + " | " +
                    link("Scenario in explorer", _flow_url(map_value["id"])), "small", True)]
        for number, node in enumerate(map_value.get("nodes", []), 1):
            story += node_details(map_value, node, number)
    doc = FlowDoc()
    doc.build(story)
    references = model.setdefault("print_references", {})
    references.setdefault("flow_maps", {}).update(doc.map_pages)
    references.setdefault("flow_nodes", {}).update(doc.node_pages)
    references.setdefault("volumes", {})["execution-flows"] = {"pdf": PDF_NAME, "pages": doc.page,
                                                              "maps": len(maps), "nodes": len(doc.node_pages)}
    return "pdf/" + PDF_NAME
