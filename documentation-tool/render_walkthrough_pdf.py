"""Print source-linked walkthroughs for the implementation behind edit maps.

This renderer consumes a captured model only. It neither reads application
files nor runs their build. Complete captured symbol bodies and structural
outlines are printed; broad syntax-only call matches are explicitly bounded.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape
import re
import unicodedata


PDF_NAME = "01-code-walkthroughs.pdf"
INCOMING_LIMIT = 8
OUTGOING_LIMIT = 8
TARGET_LIMIT = 3
CONTEXT_BEFORE = 4
CONTEXT_AFTER = 12
PRINTED_KINDS = {"function", "method", "class", "struct", "enum", "trait", "impl"}


def _plain(value: Any) -> str:
    value = str(value if value is not None else "")
    for old, new in (("\u2013", "-"), ("\u2014", "-"), ("\u2018", "'"),
                     ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                     ("\u2192", " -> "), ("\u2190", " <- "), ("\u00b7", " | ")):
        value = value.replace(old, new)
    return unicodedata.normalize("NFKD", value).encode("ascii", "backslashreplace").decode("ascii")


def _esc(value: Any) -> str:
    return escape(_plain(value), {'"': "&quot;"})


def _bookmark(prefix: str, value: Any) -> str:
    return prefix + "-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(value))


def _source_url(file: dict[str, Any], line: int) -> str:
    return "../index.html#source/" + quote(str(file.get("id") or file.get("path", "")), safe="") + "/" + str(line)


def _symbol_url(symbol: dict[str, Any]) -> str:
    return "../index.html#symbol/" + quote(str(symbol.get("id", "")), safe="")


def _step_url(map_id: str, node_id: str) -> str:
    return "../index.html#change/" + quote(map_id, safe="") + "/" + quote(node_id, safe="")


def _flow_rows(nodes: list[dict[str, Any]], depth: int = 0) -> list[tuple[int, dict[str, Any]]]:
    result = []
    for node in nodes:
        result.append((depth, node))
        result.extend(_flow_rows(node.get("children", []), depth + 1))
    return result


def _lines(file: dict[str, Any]) -> list[str]:
    lines = str(file.get("text", "")).replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _selection(model: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Deduplicate anchored symbols and source-only contexts in task order."""
    files = {str(f["id"]): f for f in model.get("files", [])}
    paths = {f["path"]: f for f in files.values()}
    symbols = {str(s["id"]): {**s, "file": f} for f in files.values() for s in f.get("symbols", [])}
    selected: dict[str, dict[str, Any]] = {}
    contexts: dict[tuple[str, int], dict[str, Any]] = {}
    for map_value in model.get("change_maps", []):
        for number, node in enumerate(map_value.get("nodes", []), 1):
            usage = {"map_id": map_value["id"], "map_title": map_value.get("title", map_value["id"]),
                     "node_id": node["id"], "number": number, "title": node.get("title", ""),
                     "role": node.get("role", "EDIT"), "why": node.get("why", ""),
                     "action": node.get("action") or node.get("summary", "")}
            refs = [node] + list(node.get("references", []))
            for guide in node.get("parameter_guides", []):
                refs.extend(guide.get("references", []))
            for ref in refs:
                file = files.get(str(ref.get("file_id", ""))) or paths.get(ref.get("path", ""))
                if not file or file.get("language") == "cmake" or file.get("category") == "build":
                    continue
                line = int(ref.get("line") or 1)
                symbol = symbols.get(str(ref.get("symbol_id", "")))
                if not symbol:
                    enclosing = [s for s in file.get("symbols", []) if s.get("kind") in PRINTED_KINDS
                                 and s.get("line", 0) <= line <= s.get("end_line", s.get("line", 0))]
                    if enclosing:
                        closest = min(enclosing, key=lambda s: (s.get("end_line", s["line"]) - s["line"], -s["line"]))
                        symbol = symbols[str(closest["id"])]
                if symbol and symbol.get("kind") in PRINTED_KINDS:
                    item = selected.setdefault(str(symbol["id"]), {"symbol": symbol, "uses": {}, "locations": set()})
                else:
                    item = contexts.setdefault((str(file["id"]), line), {"file": file, "line": line, "uses": {}, "locations": set()})
                item["uses"].setdefault((usage["map_id"], usage["node_id"]), usage)
                item["locations"].add((str(file["id"]), line))
    # Adjacent anchors in an unindexed initializer often request almost the
    # same context. Merge overlapping windows, retaining every exact anchor
    # and edit-step rationale, rather than printing that source repeatedly.
    merged_contexts: list[dict[str, Any]] = []
    for item in contexts.values():
        item["start"] = max(1, item["line"] - CONTEXT_BEFORE)
        item["end"] = min(len(_lines(item["file"])), item["line"] + CONTEXT_AFTER)
        prior = next((other for other in merged_contexts if other["file"]["id"] == item["file"]["id"]
                      and other["start"] <= item["end"] and item["start"] <= other["end"]
                      and max(other["end"], item["end"]) - min(other["start"], item["start"]) < 40), None)
        if prior:
            prior["start"], prior["end"] = min(prior["start"], item["start"]), max(prior["end"], item["end"])
            prior["uses"].update(item["uses"])
            prior["locations"].update(item["locations"])
        else:
            merged_contexts.append(item)
    return list(selected.values()), merged_contexts, symbols, files


def render_walkthrough_pdf(model: dict[str, Any], output: Path) -> str:
    """Render one PDF and publish symbol/location first-page links in model."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.platypus import (
            BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, PageBreak, PageTemplate,
            Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise ImportError("Code walkthrough PDF output needs ReportLab. Install the documentation "
                          "tool's requirements or run with --no-pdf.") from exc

    selected, contexts, symbols, files = _selection(model)
    selected_ids = {str(item["symbol"]["id"]) for item in selected}
    output = Path(output)
    (output / "pdf").mkdir(parents=True, exist_ok=True)
    filename = output / "pdf" / PDF_NAME
    page_w, page_h = landscape(letter)
    margin = 30
    width, height = page_w - 2 * margin, page_h - 92
    ink, muted, blue = (colors.HexColor(x) for x in ("#173849", "#536773", "#256b91"))
    rule, wash = (colors.HexColor(x) for x in ("#cad8df", "#edf3f6"))
    styles = {
        "title": ParagraphStyle("walk-title", fontName="Helvetica-Bold", fontSize=17, leading=20,
                                textColor=ink, spaceAfter=9, keepWithNext=True),
        "chapter": ParagraphStyle("walk-chapter", fontName="Helvetica-Bold", fontSize=14, leading=17,
                                  textColor=ink, spaceAfter=8, keepWithNext=True),
        "heading": ParagraphStyle("walk-heading", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                                  textColor=ink, spaceBefore=8, spaceAfter=5, keepWithNext=True),
        "body": ParagraphStyle("walk-body", fontName="Helvetica", fontSize=9.6, leading=12.3,
                               textColor=ink, spaceAfter=5),
        "small": ParagraphStyle("walk-small", fontName="Helvetica", fontSize=9, leading=11.4,
                                textColor=muted, spaceAfter=4),
        "table": ParagraphStyle("walk-table", fontName="Helvetica", fontSize=9, leading=11.4,
                                textColor=ink),
        "tablehead": ParagraphStyle("walk-tablehead", fontName="Helvetica-Bold", fontSize=9, leading=11.4,
                                    textColor=ink),
        "mono": ParagraphStyle("walk-mono", fontName="Courier", fontSize=9.1, leading=11.5,
                               textColor=ink, spaceBefore=3, spaceAfter=6),
    }
    for style in styles.values():
        style.splitLongWords = True

    def link(label: Any, url: str) -> str:
        return '<link href="' + _esc(url) + '" color="#256b91">' + _esc(label) + "</link>"

    def p(value: Any, style: str = "body", raw: bool = False) -> Any:
        return Paragraph(str(value) if raw else _esc(value), styles[style])

    def source_link(file: dict[str, Any], line: int, label: str = "") -> str:
        return link(label or f"{file['path']}:{line}", _source_url(file, line))

    def symbol_name_link(symbol: dict[str, Any]) -> str:
        destination = ("#" + _bookmark("symbol", symbol["id"])) if str(symbol["id"]) in selected_ids else _symbol_url(symbol)
        return link(symbol.get("qualified_name") or symbol["name"], destination)

    def table(rows: list[list[Any]], widths: list[float]) -> Any:
        result = Table([[p(cell, "tablehead" if i == 0 else "table", raw=True) for cell in row]
                        for i, row in enumerate(rows)], colWidths=widths, repeatRows=1,
                       hAlign="LEFT", splitByRow=True)
        result.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (0, 0), (-1, 0), wash),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafb")]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.35, rule),
        ]))
        return result

    class Heading(Paragraph):
        def __init__(self, label: str, destination: str, level: int, style: str = "heading",
                     symbol_id: str = "", locations: set[tuple[str, int]] | None = None) -> None:
            super().__init__(_esc(label), styles[style])
            self.label, self.destination, self.level = _plain(label), destination, level
            self.symbol_id, self.locations = symbol_id, locations or set()

    class WalkDoc(BaseDocTemplate):
        def __init__(self) -> None:
            super().__init__(str(filename), pagesize=(page_w, page_h), leftMargin=margin,
                             rightMargin=margin, topMargin=56, bottomMargin=36,
                             title=f"{model.get('title', 'Software foundation')}: code walkthroughs",
                             author="Local source-map generator", subject="Captured implementation behind edit paths")
            self.current = "Code walkthroughs"
            self.symbol_pages: dict[str, dict[str, Any]] = {}
            self.location_pages: dict[str, dict[str, Any]] = {}
            frame = Frame(margin, 36, width, height, leftPadding=0, rightPadding=0,
                          topPadding=0, bottomPadding=0)
            self.addPageTemplates(PageTemplate("walkthrough", frames=[frame], onPage=self.decorate))

        def decorate(self, canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setStrokeColor(rule)
            canvas.line(margin, page_h - 43, page_w - margin, page_h - 43)
            canvas.line(margin, 27, page_w - margin, 27)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(ink)
            canvas.drawString(margin, page_h - 29, "CODE WALKTHROUGHS")
            canvas.setFont("Helvetica", 8.5)
            canvas.setFillColor(muted)
            # Long names remain complete in headings; the running header is
            # intentionally a short generic label for consistent pagination.
            canvas.drawRightString(page_w - margin, page_h - 29, "Captured implementation | syntax-derived relationships")
            footer = "Up to edit paths"
            canvas.setFillColor(blue)
            canvas.drawString(margin, 14, footer)
            canvas.linkURL("00-edit-paths.pdf", (margin, 11, margin + stringWidth(footer, "Helvetica", 8.5), 22), relative=0)
            middle = "Walkthrough index"
            canvas.drawString(margin + 116, 14, middle)
            canvas.linkRect("", "walkthrough-index", (margin + 116, 11, margin + 116 + stringWidth(middle, "Helvetica", 8.5), 22), relative=0)
            canvas.setFillColor(muted)
            canvas.drawRightString(page_w - margin, 14, f"{_plain(model.get('generated_at', ''))} | Page {doc.page}")
            canvas.restoreState()

        def afterFlowable(self, item: Any) -> None:
            if isinstance(item, Heading):
                self.canv.bookmarkPage(item.destination)
                self.canv.addOutlineEntry(item.label, item.destination, level=item.level, closed=item.level > 0)
                data = {"pdf": PDF_NAME, "page": self.page}
                if item.symbol_id:
                    self.symbol_pages[item.symbol_id] = data.copy()
                for file_id, line in item.locations:
                    self.location_pages[f"{file_id}:{line}"] = data.copy()

    class CodeLine(Flowable):
        """One logical source line, with visual continuations and exact number."""
        def __init__(self, text: str, line: int, file: dict[str, Any]) -> None:
            super().__init__()
            self.file, self.line = file, line
            # Keep source characters recoverable. Prose punctuation may be
            # normalized, but source uses explicit Unicode escapes instead.
            text = str(text).encode("ascii", "backslashreplace").decode("ascii").expandtabs(4)
            char_w = stringWidth("M", "Courier", 9.1)
            limit = max(20, int((width - 57) / char_w))
            self.fragments = []
            while len(text) > limit:
                # Splitting preserves every character, including whitespace.
                cut = text.rfind(" ", limit // 2, limit + 1)
                if cut < limit // 2:
                    cut = limit
                self.fragments.append(text[:cut])
                text = text[cut:]
            self.fragments.append(text)
            self.width, self.height = width, 11.5 * len(self.fragments)

        def draw(self) -> None:
            c = self.canv
            c.saveState()
            c.setStrokeColor(rule)
            c.line(44, 0, 44, self.height)
            for i, fragment in enumerate(self.fragments):
                y = self.height - 9.1 - i * 11.5
                c.setFont("Helvetica", 8.4)
                c.setFillColor(blue)
                c.drawRightString(37, y, str(self.line) if i == 0 else "+")
                if i == 0:
                    c.linkURL(_source_url(self.file, self.line), (0, y - 2, 40, y + 10), relative=1)
                c.setFont("Courier", 9.1)
                c.setFillColor(ink)
                c.drawString(52, y, fragment)
            c.restoreState()

    def listing(file: dict[str, Any], start: int, end: int) -> list[Any]:
        lines = _lines(file)
        start, end = max(1, start), min(len(lines), max(start, end))
        return [CodeLine(lines[number - 1], number, file) for number in range(start, end + 1)]

    def origin(file: dict[str, Any]) -> list[Any]:
        if file.get("origin") != "supplier-reference" and not str(file.get("path", "")).startswith("@"):
            return []
        provenance = file.get("provenance", {}) or file.get("supplier", {})
        parts = [p("<b>Read-only supplier reference.</b> This captured upstream definition is evidence for the supplier contract; follow the edit map for application changes.", "small", raw=True)]
        if provenance:
            values = [f"{key}: {provenance[key]}" for key in ("archive", "member", "revision") if provenance.get(key)]
            if values:
                parts.append(p(" | ".join(values), "small"))
        return parts

    def uses_story(item: dict[str, Any]) -> list[Any]:
        result = [p("Why this implementation is on an edit path", "heading")]
        for usage in item["uses"].values():
            label = f"{usage['map_id']} / N{usage['number']}: {usage['title']} ({usage['role']})"
            text = link(label, _step_url(usage["map_id"], usage["node_id"]))
            if usage["role"] == "NEW":
                text += "<br/><b>Existing pattern for a planned addition.</b> The proposed code is not a definition in this listing."
            if usage.get("why"):
                text += "<br/><b>Why:</b> " + _esc(usage["why"])
            result.append(p(text, "small", raw=True))
        return result

    incoming: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for caller in symbols.values():
        for call in caller.get("calls", []):
            for target in call.get("targets", []):
                group = incoming[str(target)].setdefault(str(caller["id"]), {"symbol": caller, "calls": []})
                group["calls"].append(call)

    def relevance(candidate: dict[str, Any], current: dict[str, Any]) -> tuple[Any, ...]:
        file = candidate["file"]
        return (str(candidate["id"]) not in selected_ids, file["id"] != current["file"]["id"],
                file.get("category") == "tests", file["path"], candidate.get("line", 0))

    def call_site_links(file: dict[str, Any], calls: list[dict[str, Any]]) -> str:
        return ", ".join(source_link(file, line, f"L{line}") for line in sorted({int(c.get("line") or 1) for c in calls}))

    def relation_stories(symbol: dict[str, Any], dest: str) -> list[Any]:
        story = [Heading("Named call neighborhood", dest + "-calls", 2),
                 p("These are syntax-derived name candidates, not type-checked runtime edges. A dotted/member call can match unrelated types; unresolved calls may be external, dynamic, macros, or outside the snapshot. Empty caller lists do not rule out callbacks.", "small")]
        grouped_in = sorted(incoming.get(str(symbol["id"]), {}).values(), key=lambda group: relevance(group["symbol"], symbol))
        site_count = sum(len(group["calls"]) for group in grouped_in)
        story.append(p(f"Incoming: {site_count} indexed candidate call sites across {len(grouped_in)} unique caller symbols.", "small"))
        if grouped_in:
            rows = [["Caller / captured location", "Call-site lines", "Analysis"]]
            for group in grouped_in[:INCOMING_LIMIT]:
                caller = group["symbol"]
                rows.append([symbol_name_link(caller) + " (" + source_link(caller["file"], caller["line"]) + ")",
                             call_site_links(caller["file"], group["calls"]),
                             _esc(", ".join(sorted({c.get("resolution", "unspecified") for c in group["calls"]})))])
            story.append(table(rows, [width * .51, width * .24, width * .25]))
            if len(grouped_in) > INCOMING_LIMIT:
                omitted = grouped_in[INCOMING_LIMIT:]
                story.append(p(f"Print scope: {len(omitted)} additional caller symbols containing {sum(len(x['calls']) for x in omitted)} candidate call sites are omitted. Map-linked and same-file callers are listed first. " + link("All callers in explorer", _symbol_url(symbol)), "small", raw=True))
        else:
            story.append(p("No indexed incoming name candidates.", "small"))
        grouped_out: dict[tuple[str, str, tuple[str, ...]], list[dict[str, Any]]] = {}
        for call in symbol.get("calls", []):
            key = (str(call.get("name", "")), str(call.get("resolution", "unspecified")), tuple(sorted(set(str(t) for t in call.get("targets", [])))))
            grouped_out.setdefault(key, []).append(call)
        story.append(p(f"Outgoing: {len(symbol.get('calls', []))} detected call sites grouped into {len(grouped_out)} distinct name / analysis / target-set rows.", "small"))
        if grouped_out:
            rows = [["Call name / call sites", "Candidate target names / captured locations", "Analysis"]]
            def group_relevance(item: tuple[Any, Any]) -> tuple[Any, ...]:
                (_, _, target_ids), calls = item
                known = [symbols[t] for t in target_ids if t in symbols]
                return (not any(str(t["id"]) in selected_ids for t in known),
                        not any(t["file"]["id"] == symbol["file"]["id"] for t in known),
                        min(int(c.get("line") or 1) for c in calls))
            groups = sorted(grouped_out.items(), key=group_relevance)
            for (name, resolution, target_ids), calls in groups[:OUTGOING_LIMIT]:
                targets = sorted((symbols[t] for t in target_ids if t in symbols), key=lambda s: relevance(s, symbol))
                target_text = []
                for target in targets[:TARGET_LIMIT]:
                    target_text.append(symbol_name_link(target) + " (" + source_link(target["file"], target["line"]) + ")")
                if len(targets) > TARGET_LIMIT:
                    target_text.append(f"<b>+{len(targets) - TARGET_LIMIT} additional candidate targets omitted;</b> " + link("all targets", _symbol_url(symbol)))
                unknown = len(target_ids) - len(targets)
                if unknown:
                    target_text.append(f"{unknown} target IDs are absent from the captured symbol directory.")
                rows.append(["<b>" + _esc(name) + "</b><br/>" + call_site_links(symbol["file"], calls),
                             "<br/>".join(target_text) if target_text else "No indexed target; external / unresolved.", _esc(resolution)])
            story.append(table(rows, [width * .31, width * .50, width * .19]))
            if len(groups) > OUTGOING_LIMIT:
                omitted = groups[OUTGOING_LIMIT:]
                story.append(p(f"Print scope: {len(omitted)} additional outgoing groups containing {sum(len(calls) for _, calls in omitted)} call sites are omitted. Groups containing map-linked or same-file candidates are listed first. " + link("All outgoing calls in explorer", _symbol_url(symbol)), "small", raw=True))
        else:
            story.append(p("No calls detected in this captured symbol.", "small"))
        return story

    def type_story(symbol: dict[str, Any]) -> list[Any]:
        members = [s for s in symbols.values() if s["file"]["id"] == symbol["file"]["id"]
                   and s.get("owner") in {symbol.get("qualified_name"), symbol.get("name")}
                   and str(s["id"]) != str(symbol["id"])]
        if not members:
            return []
        rows = [["Indexed member", "Kind / line", "Signature"]]
        for member in sorted(members, key=lambda s: (s["line"], s["name"])):
            rows.append([symbol_name_link(member),
                         _esc(member.get("kind", "")) + "<br/>" + source_link(member["file"], member["line"], f"L{member['line']}"),
                         _esc(member.get("signature", ""))])
        return [p(f"Owning type: {len(members)} indexed members in this declaration file. Members not recognized by the syntax scanner remain visible in the complete source below.", "small"), table(rows, [width * .35, width * .12, width * .53])]

    story: list[Any] = [Heading("Code walkthroughs behind the edit maps", "walkthrough-index", 0, "title"),
                        p("Use this volume after choosing an edit path. Each section prints an existing implementation or contract linked from an edit step, its complete captured declaration/body, and the indexed call and control structure. Proposed additions remain editing plans; their source links show existing patterns."),
                        p(f"Snapshot: {model.get('generated_at', '')}. {len(selected)} deduplicated symbols and {len(contexts)} source-only anchor contexts selected from {len(model.get('change_maps', []))} edit maps; {len(symbols)} symbols are indexed in the complete explorer.", "small"),
                        p("This snapshot is generated only on explicit request and may lag current code. The collector parses syntax; it does not configure or execute the application build. Complete means the source and structure captured by this scanner, not complete runtime behavior.", "small"),
                        p("Compiler/configuration anchors are covered by the compiler reference. References absent from the captured model remain review items in the edit paths; they cannot supply a source listing here.", "small"),
                        p(link("Up to graphical edit paths", "00-edit-paths.pdf") + " | " + link("Interactive symbol directory", "../index.html#symbols") + " | " + link("Compiler reference", "02-compiler-reference.pdf"), "small", raw=True),
                        p(f"Print limits apply only to broad call relationships: at most {INCOMING_LIMIT} unique incoming callers, {OUTGOING_LIMIT} outgoing name/analysis groups, and {TARGET_LIMIT} candidate targets per outgoing group, each with exact omission counts. Signatures, selected symbol source, edit-step rationale, indexed members, and structural outlines are not truncated.", "small")]
    index_rows = [["Implementation / contract", "Captured source", "Linked edit steps"]]
    for item in selected:
        symbol = item["symbol"]
        index_rows.append([link(symbol.get("qualified_name") or symbol["name"], "#" + _bookmark("symbol", symbol["id"])),
                           source_link(symbol["file"], symbol["line"]),
                           _esc(" | ".join(f"{u['map_id']} / N{u['number']}" for u in item["uses"].values()))])
    for item in contexts:
        index_rows.append([link("Source-only anchor context", "#" + _bookmark("context", f"{item['file']['id']}-{item['line']}")),
                           source_link(item["file"], item["line"]),
                           _esc(" | ".join(f"{u['map_id']} / N{u['number']}" for u in item["uses"].values()))])
    story += [table(index_rows, [width * .38, width * .35, width * .27])]
    for item_number, item in enumerate(selected):
        symbol, file = item["symbol"], item["symbol"]["file"]
        dest = _bookmark("symbol", symbol["id"])
        start, end = int(symbol.get("line") or 1), int(symbol.get("end_line") or symbol.get("line") or 1)
        item["locations"].add((str(file["id"]), start))
        story += ([PageBreak()] if item_number == 0 else [Spacer(1, 16), CondPageBreak(150)])
        story += [Heading(symbol.get("qualified_name") or symbol["name"], dest, 1, "chapter", str(symbol["id"]), item["locations"]),
                  p("<b>" + _esc(symbol.get("kind", "symbol")) + "</b> | " + source_link(file, start) + f" | Lines {start}-{end} | " + link("Interactive symbol / full call lists", _symbol_url(symbol)), "small", raw=True)]
        if symbol.get("owner"):
            story.append(p("Owner: " + symbol["owner"], "small"))
        if symbol.get("bases"):
            story.append(p("Declared bases: " + ", ".join(symbol["bases"]), "small"))
        if symbol.get("entry_reason"):
            story.append(p("Entry-point clue: " + symbol["entry_reason"], "small"))
        story += origin(file)
        if file.get("parse_warnings"):
            story.append(p("<b>Scanner caveats for this file:</b><br/>" + "<br/>".join(_esc(w) for w in file["parse_warnings"]), "small", raw=True))
        if symbol.get("signature"):
            story += [Heading("Captured signature", dest + "-signature", 2),
                      p(_esc(symbol["signature"]).replace("\n", "<br/>"), "mono", raw=True)]
        story += uses_story(item)
        if symbol.get("kind") in {"class", "struct", "enum", "trait", "impl"}:
            story += type_story(symbol)
        story += [Heading("Complete captured source", dest + "-source", 2),
                  p(f"{file['path']} | Lines {start}-{end} | SHA-256 {file.get('sha256', 'not supplied')}", "small"),
                  p("Line numbers link to the offline source explorer. A '+' marks a wrapped continuation of the same logical line. Tabs are expanded to four spaces; non-ASCII characters are shown as escapes for portable PDF fonts.", "small")]
        actual_lines = _lines(file)
        if start < 1 or end > len(actual_lines):
            story.append(p(f"Review required: symbol range {start}-{end} extends outside the {len(actual_lines)} captured source lines. All available lines in the requested range follow.", "small"))
        story += listing(file, start, end)
        story += [Spacer(1, 6)] + relation_stories(symbol, dest)
        flow = _flow_rows(symbol.get("flow", []))
        story += [Heading("Complete indexed structural outline", dest + "-flow", 2),
                  p(f"{len(flow)} captured landmarks. Read top to bottom; indentation follows lexical source nesting. Branches, loops, calls and exits are syntax landmarks, not an exact execution control-flow graph.", "small")]
        if flow:
            rows = [["Depth / structure", "Captured label", "Source"]]
            for depth, node in flow:
                label = _esc(node.get("label") or node.get("kind", "statement")).replace("\n", "<br/>")
                indent = "&nbsp;" * min(depth * 2, 18)
                rows.append([_esc(f"{depth}: {node.get('kind', 'statement')}"), indent + label,
                             source_link(file, int(node.get("line") or start), f"L{node.get('line') or start}")])
            story.append(table(rows, [width * .18, width * .72, width * .10]))
        else:
            story.append(p("No control landmarks were indexed. The complete captured source above remains the primary evidence.", "small"))
        story.append(p(link("Up to walkthrough index", "#walkthrough-index") + " | " + link("Up to edit paths", "00-edit-paths.pdf") + " | " + link("Explore this symbol", _symbol_url(symbol)), "small", raw=True))
    for item in contexts:
        file, line = item["file"], item["line"]
        lines = _lines(file)
        start, end = item["start"], item["end"]
        dest = _bookmark("context", f"{file['id']}-{line}")
        context_story = [Heading(f"Source-only anchor: {file['path']}:{line}", dest, 1, "chapter", locations=item["locations"])]
        context_story += origin(file) + uses_story(item)
        anchors = sorted(line_number for file_id, line_number in item["locations"] if file_id == str(file["id"]))
        context_source = [Heading("Captured context excerpt", dest + "-source", 2),
                          p(f"Bounded source context: lines {start}-{end} of {len(lines)} for anchors " + ", ".join(f"L{number}" for number in anchors) + f". {max(0, start - 1)} preceding and {max(0, len(lines) - end)} following file lines are outside this excerpt. No containing callable/type was indexed for these anchors.", "small"),
                          p(f"SHA-256 {file.get('sha256', 'not supplied')} | Snapshot {model.get('generated_at', '')}", "small")]
        context_source += listing(file, start, end)
        context_source.append(p(source_link(file, line, "Complete source in explorer") + " | " + link("Up to walkthrough index", "#walkthrough-index") + " | " + link("Up to edit paths", "00-edit-paths.pdf"), "small", raw=True))
        # A long group of rationales can exceed one frame. Keep the bounded
        # source window and return links together, independently of that prose.
        story += [Spacer(1, 16), CondPageBreak(120)] + context_story + [KeepTogether(context_source)]
    doc = WalkDoc()
    doc.build(story)
    references = model.setdefault("print_references", {})
    references.setdefault("symbols", {}).update(doc.symbol_pages)
    references.setdefault("locations", {}).update(doc.location_pages)
    references.setdefault("volumes", {})["walkthroughs"] = {"pdf": PDF_NAME, "pages": doc.page,
                                                           "symbols": len(selected), "contexts": len(contexts)}
    return "pdf/" + PDF_NAME
