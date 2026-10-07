"""Render the explicitly AI-authored GUI guide as a portable, offline HTML file.

The prose and conceptual relationships are supplied by the static guide model.
This renderer performs no inference, repository operations, network calls, or AI use.
"""
from __future__ import annotations

import heapq
from html import escape
from pathlib import Path
from urllib.parse import quote

HTML_FILENAME = "AI-AUTHORED__GUI-MENTAL-MODEL.html"
PDF_FILENAME = "AI-AUTHORED__GUI-MENTAL-MODEL.pdf"


def _esc(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _wrap(value: object, width: int) -> list[str]:
    words: list[str] = []
    for word in str(value or "").split():
        words.extend(word[i:i + width] for i in range(0, len(word), width))
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines


def _detail_href(node: dict, code_maps: dict[str, dict]) -> str | None:
    detail = node.get("detail") or {}
    target = code_maps.get(str(detail.get("map", "")))
    if not target:
        return None
    node_id = detail.get("node")
    if node_id and not any(str(item.get("id")) == str(node_id) for item in target.get("nodes", [])):
        return None
    return "index.html#code/" + quote(str(target["id"]), safe="") + ("/" + quote(str(node_id), safe="") if node_id else "")


def _source_href(node: dict, files: dict[str, dict]) -> str | None:
    reference = node.get("source_ref") or {}
    source = files.get(str(reference.get("file_id", "")))
    line = reference.get("line")
    if reference.get("status") != "verified" or not source or isinstance(line, bool) or not isinstance(line, int):
        return None
    if not 1 <= line <= int(source.get("line_count", 0)):
        return None
    return "index.html#source/" + quote(str(source["id"]), safe="") + "/" + str(line)


def _pdf_href(model: dict, diagram_id: str | None = None) -> str | None:
    if not any(item.get("name") in (PDF_FILENAME, "pdf/" + PDF_FILENAME) for item in model.get("pdfs", [])):
        return None
    if diagram_id is None:
        return "pdf/" + PDF_FILENAME
    reference = (model.get("print_references", {}).get("concept_diagrams", {}) or {}).get(diagram_id) or {}
    page = reference.get("page")
    if reference.get("pdf") == PDF_FILENAME and isinstance(page, int) and not isinstance(page, bool) and page > 0:
        return "pdf/" + PDF_FILENAME + "#page=" + str(page)
    return None


def _source_review(node: dict, files: dict[str, dict]) -> bool:
    reference = node.get("source_ref") or {}
    return bool(node.get("source") or reference) and _source_href(node, files) is None


def _route(from_box: dict, to_box: dict, boxes: list[dict], width: int, height: int,
           box_width: int, box_height: int, column_pitch: int, row_pitch: int) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    """Route through the diagram's gutters, including backward and branch edges."""
    same_row = from_box["y"] == to_box["y"]
    right = to_box["x"] > from_box["x"]
    down = to_box["y"] > from_box["y"]
    horizontal_gap = (column_pitch - box_width) / 2
    vertical_gap = (row_pitch - box_height) / 2
    if same_row:
        start = (from_box["x"] + (box_width if right else 0), from_box["y"] + box_height / 2)
        finish = (to_box["x"] + (0 if right else box_width), to_box["y"] + box_height / 2)
        entry = (start[0] + (horizontal_gap if right else -horizontal_gap), start[1])
        end = (finish[0] - (horizontal_gap if right else -horizontal_gap), finish[1])
    else:
        start = (from_box["x"] + box_width / 2, from_box["y"] + (box_height if down else 0))
        finish = (to_box["x"] + box_width / 2, to_box["y"] + (0 if down else box_height))
        entry = (start[0], start[1] + (vertical_gap if down else -vertical_gap))
        end = (finish[0], finish[1] - (vertical_gap if down else -vertical_gap))
    xs = sorted({16.0, float(width - 16), entry[0], end[0], *(value for box in boxes for value in (box["x"] + box_width / 2, box["x"] + box_width + horizontal_gap))})
    ys = sorted({16.0, float(height - 16), entry[1], end[1], *(value for box in boxes for value in (box["y"] + box_height / 2, box["y"] + box_height + vertical_gap))})
    xs = [value for value in xs if 0 <= value <= width]
    ys = [value for value in ys if 0 <= value <= height]

    def clear(a: tuple[float, float], b: tuple[float, float]) -> bool:
        for box in boxes:
            left, top = box["x"] - 5, box["y"] - 5
            right_edge, bottom = box["x"] + box_width + 5, box["y"] + box_height + 5
            if a[0] == b[0]:
                if left < a[0] < right_edge and max(a[1], b[1]) > top and min(a[1], b[1]) < bottom:
                    return False
            elif top < a[1] < bottom and max(a[0], b[0]) > left and min(a[0], b[0]) < right_edge:
                return False
        return True

    begin = (xs.index(entry[0]), ys.index(entry[1]), "")
    queue = [(0.0, begin)]
    best = {begin: 0.0}
    previous: dict[tuple, tuple] = {}
    found = None
    while queue:
        cost, current = heapq.heappop(queue)
        if cost != best[current]:
            continue
        xi, yi, direction = current
        point = (xs[xi], ys[yi])
        if point == end:
            found = current
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = xi + dx, yi + dy
            if not 0 <= nx < len(xs) or not 0 <= ny < len(ys):
                continue
            next_point = (xs[nx], ys[ny])
            if not clear(point, next_point):
                continue
            next_direction = "x" if dx else "y"
            next_cost = cost + abs(next_point[0] - point[0]) + abs(next_point[1] - point[1]) + (15 if direction and direction != next_direction else 0)
            next_state = (nx, ny, next_direction)
            if next_cost < best.get(next_state, float("inf")):
                best[next_state] = next_cost
                previous[next_state] = current
                heapq.heappush(queue, (next_cost, next_state))
    if found is None:
        raise ValueError("Concept diagram edge has no route through its gutters")
    points: list[tuple[float, float]] = []
    current = found
    while True:
        points.append((xs[current[0]], ys[current[1]]))
        if current == begin:
            break
        current = previous[current]
    points = [start, *reversed(points), finish]
    deduped = [point for i, point in enumerate(points) if not i or point != points[i - 1]]
    points = [point for i, point in enumerate(deduped) if i in (0, len(deduped) - 1) or not ((point[0] == deduped[i - 1][0] == deduped[i + 1][0]) or (point[1] == deduped[i - 1][1] == deduped[i + 1][1]))]
    a, b = max(zip(points, points[1:]), key=lambda pair: abs(pair[0][0] - pair[1][0]) + abs(pair[0][1] - pair[1][1]))
    return points, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _diagram_svg(diagram: dict, index: int, files: dict[str, dict], code_maps: dict[str, dict]) -> str:
    nodes = diagram.get("nodes", [])
    if not nodes:
        return '<p class="empty">No diagram nodes are available.</p>'
    titles = {str(node["id"]): _wrap(node.get("title"), 29) for node in nodes}
    subtitles = {str(node["id"]): _wrap(node.get("subtitle"), 35) for node in nodes}
    box_width = 264
    # Reserve a separate footer band below every subtitle and its descenders.
    box_height = max(110, 76 + max(len(titles[str(node["id"])]) * 19 + len(subtitles[str(node["id"])]) * 15 for node in nodes))
    edge_lines = [_wrap(edge.get("label"), 19) for edge in diagram.get("edges", [])]
    column_pitch = box_width + max(138, max((max(map(len, lines), default=0) * 6 + 36 for lines in edge_lines), default=0))
    row_pitch = box_height + max(60, max((len(lines) * 14 + 10 for lines in edge_lines), default=10) * 2 + 12)
    columns = max(int(node.get("column", 0)) for node in nodes) + 1
    rows = max(int(node.get("row", 0)) for node in nodes) + 1
    width = columns * column_pitch - (column_pitch - box_width) + 64
    height = rows * row_pitch - (row_pitch - box_height) + 64
    positions = {str(node["id"]): {"x": 32 + int(node.get("column", 0)) * column_pitch, "y": 32 + int(node.get("row", 0)) * row_pitch} for node in nodes}
    kinds = ("call", "data", "event", "return", "step")
    marker = f"concept-arrow-{index}"
    parts = [f'<svg class="concept-svg" id="concept-svg-{index}" role="group" aria-label="{_esc(diagram.get("title"))}: AI-authored conceptual diagram" viewBox="0 0 {width} {height}" data-width="{width}" data-height="{height}"><defs>']
    parts.extend(f'<marker id="{marker}-{kind}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path class="marker-{kind}" d="M 0 0 L 8 4 L 0 8 z"></path></marker>' for kind in kinds)
    parts.append("</defs>")
    for edge in diagram.get("edges", []):
        from_box, to_box = positions.get(str(edge.get("from"))), positions.get(str(edge.get("to")))
        if from_box is None or to_box is None:
            raise ValueError(f"Unknown node in concept diagram {diagram.get('id')}")
        points, label_position = _route(from_box, to_box, list(positions.values()), width, height, box_width, box_height, column_pitch, row_pitch)
        path = " ".join(f'{"M" if i == 0 else "L"} {x:g} {y:g}' for i, (x, y) in enumerate(points))
        kind = str(edge.get("kind", "step"))
        if kind not in kinds:
            kind = "step"
        labels = _wrap(edge.get("label"), 19)
        x, y = label_position
        parts.append(f'<g class="concept-edge edge-{kind}"><path d="{path}" marker-end="url(#{marker}-{kind})"><title>{_esc(edge.get("label"))}</title></path>')
        if labels:
            label_width = max(42, max(map(len, labels)) * 6 + 12)
            parts.append(f'<g class="edge-label"><rect x="{x - label_width / 2:g}" y="{y - 9:g}" width="{label_width}" height="{len(labels) * 14 + 6}" rx="4"></rect>')
            parts.extend(f'<text x="{x:g}" y="{y + 2 + i * 14:g}" text-anchor="middle">{_esc(line)}</text>' for i, line in enumerate(labels))
            parts.append("</g>")
        parts.append("</g>")
    for node in nodes:
        node_id = str(node["id"])
        x, y = positions[node_id]["x"], positions[node_id]["y"]
        kind = str(node.get("kind", "call"))
        if kind not in ("call", "data", "application", "boundary", "backend", "core"):
            kind = "call"
        detail = _detail_href(node, code_maps)
        evidence = _source_href(node, files)
        parts.append(f'<g class="concept-node node-{kind}" data-node="{_esc(node_id)}">')
        tag = "a" if detail else "g"
        parts.append(f'<a class="node-main" href="{_esc(detail)}" aria-label="{_esc(node.get("title"))}: open detailed code diagram">' if detail else '<g class="node-main">')
        parts.append(f'<title>{_esc(node.get("title"))}{": open detailed code diagram" if detail else ""}</title><rect class="node-box" x="{x}" y="{y}" width="{box_width}" height="{box_height}" rx="9"></rect>')
        parts.append(f'<text class="node-kind" x="{x + 15}" y="{y + 21}">{_esc(kind.upper())}</text>')
        title_top = y + 44
        parts.extend(f'<text class="node-title" x="{x + 15}" y="{title_top + i * 19}">{_esc(line)}</text>' for i, line in enumerate(titles[node_id]))
        subtitle_top = title_top + len(titles[node_id]) * 19
        parts.extend(f'<text class="node-subtitle" x="{x + 15}" y="{subtitle_top + i * 15}">{_esc(line)}</text>' for i, line in enumerate(subtitles[node_id]))
        parts.append(f'<text class="node-detail" x="{x + 15}" y="{y + box_height - 12}">{"Detailed code diagram →" if detail else "Conceptual context"}</text></{tag}>')
        if evidence:
            ref = node["source_ref"]
            parts.append(f'<a class="node-evidence" href="{_esc(evidence)}" aria-label="{_esc(ref.get("path", "Captured source"))} line {_esc(ref["line"])}"><rect x="{x + box_width - 96}" y="{y + box_height - 27}" width="82" height="19" rx="4"></rect><text x="{x + box_width - 87}" y="{y + box_height - 13}">Source L{_esc(ref["line"])} ↗</text></a>')
        elif _source_review(node, files):
            parts.append(f'<text class="node-source-missing" x="{x + box_width - 96}" y="{y + box_height - 13}"><title>Source anchor changed; review required</title>Source needs review</text>')
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


STYLE = r"""
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1c3544;background:#f5f7f9;line-height:1.6}*{box-sizing:border-box}body{margin:0}a{color:#276a82;text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,button:focus-visible{outline:3px solid #65a8dd;outline-offset:4px}button{font:inherit;cursor:pointer}h1,h2,p{margin-top:0}.guide-header{background:#102e40;color:#eff7fc;border-bottom:4px solid #c79a47}.header-inner,main,.guide-footer{max-width:1200px;margin:auto;padding-left:34px;padding-right:34px}.header-inner{padding-top:24px;padding-bottom:26px}.header-links{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:22px;font-size:12px}.header-links a{color:#c2e5f2}.ai-label{display:inline-block;background:#ffe6ac;color:#744c12;border:1px solid #e3c47b;border-radius:5px;padding:4px 9px;font-size:10px;line-height:1.6;font-weight:800;letter-spacing:1px}.guide-header h1{font-size:clamp(27px,3.4vw,40px);line-height:1.22;letter-spacing:-.8px;margin:12px 0}.filename{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px;color:#f0d694;overflow-wrap:anywhere}.authorship{font-size:11px;color:#a8c2d0;margin:12px 0 0}.authorship span{margin-left:14px}main{padding-top:22px;padding-bottom:20px}.intro{font-size:13px;color:#57717f;max-width:1040px;margin-bottom:18px}.guide-tabs{display:flex;gap:8px;flex-wrap:wrap;padding:12px 0;margin-bottom:20px;border-bottom:1px solid #dbe5ec}.guide-tab{background:white;border:1px solid #c8d9e5;color:#31576d;padding:9px 13px;border-radius:6px;font-size:11px;font-weight:600}.guide-tab:hover{text-decoration:none;background:#edf5fa}.guide-tab[aria-selected=true]{background:#225d79;border-color:#225d79;color:white}.guide-diagram{scroll-margin-top:18px}.diagram-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:12px}.diagram-heading h2{font-size:24px;line-height:1.35;letter-spacing:-.4px;margin:7px 0}.diagram-eyebrow{font-size:9px;color:#937033;letter-spacing:1px;text-transform:uppercase;font-weight:700}.question{font-size:13px;color:#365b70;font-weight:600;margin-bottom:7px}.summary{font-size:12px;color:#6c8391;max-width:980px;margin-bottom:15px}.diagram-pdf{flex-shrink:0;font-size:11px;padding:7px 10px;border:1px solid #c6d8e4;border-radius:6px;background:white;margin-top:12px}.chart{background:white;border:1px solid #d2dfe7;border-radius:12px;overflow:hidden;box-shadow:0 3px 16px #15344a08}.chart-canvas{background:linear-gradient(#f5f8fa 1px,transparent 1px),linear-gradient(90deg,#f5f8fa 1px,transparent 1px),white;background-size:24px 24px;overflow:auto}.concept-svg{display:block;width:100%;height:auto;max-height:820px;min-height:330px;touch-action:none;cursor:grab}.concept-svg.dragging{cursor:grabbing}.concept-svg text{font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;pointer-events:none}.node-box{fill:#f4f9fc;stroke:#80a8bc;stroke-width:1.7}.node-kind{fill:#678ba0;font-size:9px;font-weight:700;letter-spacing:1px}.node-title{fill:#25495d;font-size:15px;font-weight:650}.node-subtitle{fill:#658293;font-size:11px}.node-detail{fill:#4d7b91;font-size:9px;font-weight:600}.node-application .node-box{fill:#edf6fb;stroke:#4e96b9;stroke-width:2}.node-core .node-box{fill:#eff8f1;stroke:#78a77d}.node-core .node-kind{fill:#628a66}.node-data .node-box{fill:#f0faf7;stroke:#61a594;stroke-dasharray:5 3}.node-data .node-kind{fill:#4b8a79}.node-boundary .node-box{fill:#f6f1fc;stroke:#a28bbc}.node-boundary .node-kind{fill:#8970a4}.node-backend .node-box{fill:#f4f6f8;stroke:#a1b2bc}.node-main[href]:hover .node-box,.node-main[href]:focus .node-box{stroke:#227896;stroke-width:3;fill:#e8f5fb}.node-evidence rect{fill:white;stroke:#d6e2e9;stroke-width:1}.node-evidence text{fill:#8299a6;font-size:8.5px}.node-evidence:hover rect{fill:#edf5fa;stroke:#8cb0c7}.concept-edge path{fill:none;stroke:#608fa8;stroke-width:2}.edge-data path{stroke:#479680;stroke-dasharray:5 4}.edge-event path{stroke:#b18c49;stroke-dasharray:2 4;stroke-linecap:round}.edge-return path{stroke:#899aa4;stroke-dasharray:8 3 2 3}.edge-step path{stroke:#899aa4;stroke-width:1.5}.marker-call{fill:#608fa8}.marker-data{fill:#479680}.marker-event{fill:#b18c49}.marker-return,.marker-step{fill:#899aa4}.edge-label rect{fill:white;stroke:#e3ebef;stroke-width:.7}.edge-label text{fill:#637f91;font-size:10px}.edge-data .edge-label text{fill:#468875}.chart-controls{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:12px 17px;border-top:1px solid #e1e9ef;color:#728b99;font-size:10px}.zoom-controls{display:flex;gap:5px;flex-shrink:0}.zoom-controls button{border:1px solid #cadbe5;border-radius:4px;background:white;color:#365e73;font-size:11px;min-width:29px;padding:3px 8px}.legend{display:flex;gap:9px 19px;flex-wrap:wrap;border-top:1px solid #e7eef2;padding:11px 17px;font-size:10px;color:#6c8695}.key{display:inline-block;width:21px;border-top:2px solid #608fa8;margin-right:6px;vertical-align:middle}.key.data{border-color:#479680;border-top-style:dashed}.key.event{border-color:#b18c49;border-top-style:dotted}.key.return{border-color:#899aa4;border-top-style:dashed}.key.step{border-color:#899aa4;border-top-width:1px}.diagram-notes{margin:16px 0 22px;padding:14px 18px;background:#edf3f7;border:1px solid #d5e2ea;border-radius:8px;font-size:11px;color:#587487;line-height:1.75}.diagram-notes ul{margin:0;padding-left:16px}.diagram-notes li+li{margin-top:6px}.limits{font-size:10px;color:#85703f;padding:14px 18px;background:#fff8e8;border:1px solid #ecdcb5;border-radius:8px;margin:20px 0}.limits strong{display:block;color:#795f2d;font-size:11px;margin-bottom:5px}.limits ul{margin:0;padding-left:16px;line-height:1.8}.source-status{font-size:10px;color:#7c6840;margin:10px 0 0}.source-warnings{margin-top:7px;font-size:10px}.source-warnings summary{cursor:pointer}.diagram-source-warning{padding:10px 14px;background:#fff8e8;border:1px solid #e8d6ab;border-radius:6px;font-size:10px;color:#8a6a30;margin-bottom:12px}.diagram-source-warning details{margin-top:5px}.diagram-source-warning summary{cursor:pointer}.diagram-source-warning ul{margin:7px 0 0;padding-left:18px}.node-source-missing{font-size:8px;fill:#9b7328}.empty{padding:30px;color:#6d8390}.guide-footer{padding-top:16px;padding-bottom:24px;border-top:1px solid #dce6ed;display:flex;justify-content:space-between;gap:14px;font-size:10px;color:#7b919f}.guide-footer code{font-size:10px;overflow-wrap:anywhere}[hidden]{display:none!important}@media(max-width:650px){.header-inner,main,.guide-footer{padding-left:19px;padding-right:19px}.guide-header h1{font-size:26px}.header-links{font-size:10px;align-items:flex-start}.guide-tabs{gap:7px}.guide-tab{font-size:10px;padding:7px 10px}.diagram-heading{display:block}.diagram-heading h2{font-size:21px}.diagram-pdf{display:inline-block;margin:0 0 10px}.concept-svg{min-width:580px;max-height:none}.chart-controls{font-size:9px;flex-wrap:wrap;gap:8px}.legend{font-size:9px}.guide-footer{display:block}.guide-footer span{display:block;margin-top:7px}.authorship span{display:block;margin:4px 0 0}}@media print{@page{size:A4 portrait;margin:14mm}body{background:white;color:#111}.guide-header{background:white;color:#111;border-bottom:1px solid #999}.header-inner,main,.guide-footer{padding-left:0;padding-right:0;max-width:none}.header-inner{padding-top:0;padding-bottom:12pt}.header-links,.guide-tabs,.zoom-controls,.chart-controls,.diagram-pdf{display:none!important}.guide-header h1{font-size:22pt;color:#111;margin:9pt 0}.ai-label{background:#fff5dd!important;color:#4e3917;border-color:#ad9770;font-size:7pt}.filename{font-size:8pt;color:#4f3d18}.authorship{color:#444;font-size:8pt}.intro{font-size:9pt;color:#222;line-height:1.65}.limits{font-size:8pt;color:#333;background:white;border-color:#bbb;break-inside:avoid}.limits strong{color:#222;font-size:9pt}.guide-diagram{display:block!important;break-before:page;padding-top:6pt}.diagram-heading h2{font-size:17pt;color:#111}.diagram-eyebrow{color:#555;font-size:7pt}.question{font-size:10pt;color:#222}.summary{font-size:8pt;color:#333}.chart{border-color:#999;border-radius:0;box-shadow:none;break-inside:avoid}.chart-canvas{background:white;overflow:visible}.concept-svg{min-width:0!important;min-height:0;max-height:210mm;width:100%;height:auto;cursor:default}.node-box{fill:white!important;stroke:#666!important}.node-kind,.node-title,.node-subtitle,.node-detail,.node-evidence text{fill:#222!important}.node-evidence rect{fill:white!important;stroke:#bbb!important}.concept-edge path{stroke:#555!important}[class^=marker-]{fill:#555!important}.edge-label rect{fill:white;stroke:#ddd}.edge-label text{fill:#333!important}.legend{font-size:7pt;color:#222;padding:6pt}.key{border-color:#555!important}.diagram-notes{font-size:8pt;color:#222;background:white;border-color:#bbb;padding:9pt;break-inside:avoid;line-height:1.6}.guide-footer{font-size:7pt;color:#444;margin-top:12pt}.guide-footer code{font-size:7pt}.source-status{font-size:7pt;color:#333}.source-warnings{font-size:7pt}}
"""

SCRIPT = r"""
(() => {
  'use strict';
  const sections = Array.from(document.querySelectorAll('.guide-diagram'));
  const tabs = Array.from(document.querySelectorAll('.guide-tab'));
  function activate() {
    let id = ''; try {id = decodeURIComponent(location.hash.slice(1));} catch (_) {}
    const current = sections.find(section => section.id === id) || sections[0];
    sections.forEach(section => {section.hidden = section !== current;});
    tabs.forEach(tab => {const selected = tab.dataset.diagram === current?.id; tab.setAttribute('aria-selected', String(selected));});
  }
  window.addEventListener('hashchange', activate);
  activate();
  const reset = [];
  document.querySelectorAll('.concept-svg').forEach(svg => {
    const base = {x:0,y:0,width:Number(svg.dataset.width),height:Number(svg.dataset.height)};
    let view = {...base}, drag = null;
    const update = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
    svg._zoom = action => {if(action==='reset')view={...base};else{const width=Math.min(base.width*3,Math.max(base.width*.25,view.width*(action==='in'?.8:1.25))),height=width*base.height/base.width;view={x:view.x+(view.width-width)/2,y:view.y+(view.height-height)/2,width,height};}update();};
    reset.push(() => svg._zoom('reset'));
    svg.addEventListener('pointerdown', event => {if(event.button!==0||event.target.closest('a'))return;drag={x:event.clientX,y:event.clientY,vx:view.x,vy:view.y};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging');});
    svg.addEventListener('pointermove', event => {if(!drag)return;const rect=svg.getBoundingClientRect(),scale=Math.max(view.width/rect.width,view.height/rect.height);view.x=drag.vx-(event.clientX-drag.x)*scale;view.y=drag.vy-(event.clientY-drag.y)*scale;update();});
    const end=()=>{drag=null;svg.classList.remove('dragging');};svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);
  });
  document.querySelectorAll('[data-zoom]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.graph)?._zoom(button.dataset.zoom)));
  window.addEventListener('beforeprint', () => {sections.forEach(section => {section.hidden=false;});reset.forEach(fn=>fn());});
  window.addEventListener('afterprint', activate);
})();
"""


def render_concept_html(model: dict, output: Path) -> str:
    """Write the standalone guide and return its absolute path."""
    guide = model.get("conceptual_guide")
    if not isinstance(guide, dict) or not guide.get("diagrams"):
        raise ValueError("No conceptual guide diagrams were supplied")
    files = {str(file["id"]): file for file in model.get("files", [])}
    code_maps = {str(diagram["id"]): diagram for diagram in model.get("code_maps", [])}
    diagrams = guide["diagrams"]
    tabs = "".join(f'<a class="guide-tab" role="tab" id="tab-{_esc(diagram["id"])}" data-diagram="{_esc(diagram["id"])}" href="#{quote(str(diagram["id"]), safe="")}" aria-controls="{_esc(diagram["id"])}" aria-selected="false">{_esc(diagram["title"])}</a>' for diagram in diagrams)
    sections = []
    for index, diagram in enumerate(diagrams):
        pdf = _pdf_href(model, str(diagram["id"]))
        notes = diagram.get("notes", [])
        missing = [node for node in diagram.get("nodes", []) if _source_review(node, files)]
        source_notice = ('<aside class="diagram-source-warning"><strong>Source anchor changed; review required.</strong> <details><summary>' + str(len(missing)) + ' source locations in this diagram</summary><ul>' + "".join('<li>' + _esc(node.get("title")) + ' · ' + _esc((node.get("source_ref") or node.get("source") or {}).get("path")) + '</li>' for node in missing) + '</ul></details></aside>') if missing else ""
        sections.append(f'<section class="guide-diagram" id="{_esc(diagram["id"])}" role="tabpanel" aria-labelledby="tab-{_esc(diagram["id"])}"><div class="diagram-heading"><div><div class="diagram-eyebrow">AI-authored conceptual diagram</div><h2>{_esc(diagram["title"])}</h2></div>{f"<a class=\"diagram-pdf\" href=\"{_esc(pdf)}\">This diagram in PDF ↗</a>" if pdf else ""}</div><p class="question">{_esc(diagram.get("question"))}</p><p class="summary">{_esc(diagram.get("summary"))}</p>{source_notice}<div class="chart"><div class="chart-canvas">{_diagram_svg(diagram, index, files, code_maps)}</div><div class="chart-controls"><span>Click a card for the detailed code diagram. Source evidence is a separate link.</span><div class="zoom-controls"><button type="button" data-graph="concept-svg-{index}" data-zoom="in" aria-label="Zoom diagram in">+</button><button type="button" data-graph="concept-svg-{index}" data-zoom="out" aria-label="Zoom diagram out">−</button><button type="button" data-graph="concept-svg-{index}" data-zoom="reset">Fit</button></div></div><div class="legend"><span><i class="key"></i>Call / construction</span><span><i class="key data"></i>Data / declaration input</span><span><i class="key event"></i>Event delivery</span><span><i class="key return"></i>Return</span><span><i class="key step"></i>Local sequence</span></div></div>{"<aside class=\"diagram-notes\"><ul>" + "".join("<li>" + _esc(note) + "</li>" for note in notes) + "</ul></aside>" if notes else ""}</section>')
    limits = '<aside class="limits"><strong>How to use this AI-authored guide</strong><ul>' + "".join(f'<li>{_esc(item)}</li>' for item in guide.get("limits", [])) + '</ul><p class="source-status">' + ("Source anchors were checked against this captured snapshot; that check does not prove the conceptual explanation." if guide.get("source_status") == "verified" and not any(_source_review(node, files) for diagram in diagrams for node in diagram.get("nodes", [])) else "Some source anchors need review; use the linked code diagrams and source to confirm the explanation.") + '</p>' + ('<details class="source-warnings"><summary>' + str(len(guide.get("source_warnings", []))) + ' source anchor notes</summary><ul>' + "".join(f'<li>{_esc(item)}</li>' for item in guide.get("source_warnings", [])) + '</ul></details>' if guide.get("source_warnings") else '') + '</aside>'
    pdf = _pdf_href(model)
    title = str(guide.get("title") or "GUI mental model")
    document = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(HTML_FILENAME)} · {_esc(title)}</title><style>{STYLE}</style></head><body><header class="guide-header"><div class="header-inner"><div class="header-links"><a href="index.html#home">↑ Code explorer</a>{f"<a href=\"{_esc(pdf)}\">Open the AI-authored PDF ↗</a>" if pdf else ""}</div><span class="ai-label">AI-AUTHORED · CONCEPTUAL GUIDE</span><h1>{_esc(title)}</h1><div class="filename">{HTML_FILENAME}</div><p class="authorship">{_esc(guide.get("authorship"))}<span>Authored: {_esc(guide.get("authored_at"))}</span><span>Source snapshot: {_esc(model.get("generated_at"))}</span></p></div></header><main><p class="intro">{_esc(guide.get("intro"))}</p><nav class="guide-tabs" role="tablist" aria-label="Conceptual diagrams">{tabs}</nav>{"".join(sections)}{limits}</main><footer class="guide-footer"><a href="index.html#flows">↑ Execution & code diagrams</a><span><code>{HTML_FILENAME}</code> · Local documentation snapshot</span></footer><script>{SCRIPT}</script></body></html>'
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output / HTML_FILENAME
    path.write_text(document, encoding="utf-8")
    return str(path.resolve())
