"""Render a source-linked compiler reference from an already captured model.

The renderer performs no source collection, CMake evaluation, configuration,
compiler invocation, dependency restoration, or application execution.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path, PurePosixPath
import textwrap
from typing import Any
import unicodedata
from urllib.parse import quote
from xml.sax.saxutils import escape


PDF_NAME = '02-compiler-reference.pdf'
CONFIGURATION_COMMANDS = {
    'cmake_minimum_required', 'project', 'enable_language',
    'target_compile_options', 'target_compile_definitions', 'target_compile_features',
    'target_include_directories', 'target_link_options', 'set_target_properties',
    'set_property', 'include_directories', 'link_directories', 'link_libraries',
    'add_compile_options', 'add_compile_definitions', 'add_link_options',
    'find_package', 'find_program', 'include', 'add_subdirectory',
    'check_cxx_source_compiles', 'add_dependencies', 'add_custom_command',
}


def _plain(value: Any) -> str:
    value = str(value if value is not None else '')
    for old, new in {'\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'",
                     '\u201c': '"', '\u201d': '"', '\u2192': ' -> ', '\u00b7': ' | '}.items():
        value = value.replace(old, new)
    return unicodedata.normalize('NFKD', value).encode('ascii', 'backslashreplace').decode('ascii')


def _esc(value: Any) -> str:
    return escape(_plain(value), {'"': '&quot;'})


def _leaves(value: Any, prefix: str = '') -> list[tuple[str, str]]:
    """Print every JSON/TOML field, including empty objects/arrays and unknown keys."""
    if isinstance(value, dict) and value:
        return [entry for key, item in value.items() for entry in _leaves(item, f'{prefix}.{key}' if prefix else str(key))]
    if isinstance(value, list) and value:
        return [entry for index, item in enumerate(value) for entry in _leaves(item, f'{prefix}[{index}]')]
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return [(prefix or '(value)', encoded)]


def render_compiler_pdf(model: dict[str, Any], output: Path) -> str:
    """Write the printable compiler reference and register target page locations."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        BaseDocTemplate, CondPageBreak, Flowable, Frame, PageBreak, PageTemplate,
        Paragraph, Spacer, Table, TableStyle,
    )

    output = Path(output)
    (output / 'pdf').mkdir(parents=True, exist_ok=True)
    build = model.get('build', {})
    targets = build.get('targets', [])
    commands = build.get('commands', [])
    files = {file['path']: file for file in model.get('files', [])}
    reference = model.setdefault('print_references', {})
    target_refs = reference.setdefault('build_targets', {})
    location_refs = reference.setdefault('compiler_locations', {})
    shared_location_refs = reference.setdefault('locations', {})
    width, height = letter
    margin, body_width = 44, width - 88
    ink = colors.HexColor('#173849')
    muted = colors.HexColor('#51626d')
    accent = colors.HexColor('#24658b')
    rule = colors.HexColor('#cbd9e2')
    pale = colors.HexColor('#edf3f6')
    styles = {
        'title': ParagraphStyle('compiler-title', fontName='Helvetica-Bold', fontSize=26, leading=30, textColor=ink, spaceAfter=13),
        'chapter': ParagraphStyle('compiler-chapter', fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=ink, spaceAfter=10, keepWithNext=True),
        'heading': ParagraphStyle('compiler-heading', fontName='Helvetica-Bold', fontSize=11.5, leading=15, textColor=ink, spaceBefore=10, spaceAfter=6, keepWithNext=True),
        'body': ParagraphStyle('compiler-body', fontName='Helvetica', fontSize=9.4, leading=13, textColor=ink, spaceAfter=7, splitLongWords=True),
        'small': ParagraphStyle('compiler-small', fontName='Helvetica', fontSize=8.3, leading=11.2, textColor=muted, spaceAfter=5, splitLongWords=True),
        'cell': ParagraphStyle('compiler-cell', fontName='Helvetica', fontSize=8.3, leading=11.1, textColor=ink, splitLongWords=True),
        'cellhead': ParagraphStyle('compiler-cellhead', fontName='Helvetica-Bold', fontSize=8.3, leading=11.1, textColor=ink, splitLongWords=True),
        'code': ParagraphStyle('compiler-code', fontName='Courier', fontSize=8, leading=10.5, textColor=ink, spaceAfter=2, leftIndent=8, rightIndent=8, splitLongWords=True),
    }

    def p(value: Any, style: str = 'body', raw: bool = False) -> Paragraph:
        return Paragraph(str(value) if raw else _esc(value), styles[style])

    def link(label: Any, destination: str) -> str:
        return f'<link href="{_esc(destination)}" color="#24658b">{_esc(label)}</link>'

    def source_link(item: dict, label: str | None = None) -> str:
        path, line = item.get('path', ''), item.get('line', 1)
        file = files.get(path)
        display = label if label is not None else f'{path}:{line}'
        if file:
            return link(display, '../index.html#source/' + quote(file['id'], safe='') + '/' + str(line))
        return _esc(display) + ' (source not captured)'

    def context_flow(item: dict) -> list[Any]:
        context = item.get('context', [])
        if not context:
            return [p('Context: no enclosing condition/helper recorded.', 'small')]
        result = [p('Enclosing context (unevaluated):', 'small')]
        result.extend(p(f'{number}. {value}', 'small') for number, value in enumerate(context, 1))
        return result

    def table(rows: list[list[Any]], widths: list[float], headers: bool = True) -> Table:
        data = [[cell if not isinstance(cell, str) else p(cell, 'cellhead' if headers and index == 0 else 'cell', raw=True)
                 for cell in row] for index, row in enumerate(rows)]
        result = Table(data, colWidths=widths, repeatRows=1 if headers else 0, hAlign='LEFT', splitByRow=True)
        commands_style = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
                          ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                          ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                          ('LINEBELOW', (0, 0), (-1, -1), .35, rule)]
        if headers:
            commands_style += [('BACKGROUND', (0, 0), (-1, 0), pale),
                               ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafb')])]
        result.setStyle(TableStyle(commands_style))
        return result

    def property_table(entries: list[tuple[str, str]], headers: tuple[str, str] = ('Field', 'Captured value')) -> Table:
        rows = [[_esc(headers[0]), _esc(headers[1])]]
        for key, value in entries:
            # A large value becomes multiple table rows, never one oversized cell.
            # Characters are retained; line wrapping only adds print layout breaks.
            chunks = [value[index:index + 700] for index in range(0, len(value), 700)] or ['']
            for index, chunk in enumerate(chunks):
                rows.append([_esc(key if index == 0 else key + ' (continued)'), _esc(chunk)])
        return table(rows, [166, body_width - 166])

    class Heading(Paragraph):
        def __init__(self, text: str, destination: str, level: int = 0, target_index: int | None = None, location: str | None = None):
            super().__init__(_esc(text), styles['chapter' if level == 0 else 'heading'])
            self.destination, self.level, self.label = destination, level, _plain(text)
            self.target_index, self.location = target_index, location

    class Book(BaseDocTemplate):
        def __init__(self):
            super().__init__(str(output / 'pdf' / PDF_NAME), pagesize=letter,
                             title='Software foundation: Compiler and toolchain reference',
                             author='Local documentation generator', leftMargin=margin, rightMargin=margin,
                             topMargin=57, bottomMargin=52)
            frame = Frame(margin, 52, body_width, height - 109, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
            self.addPageTemplates(PageTemplate(id='compiler', frames=frame, onPage=self.decorate))

        def decorate(self, canvas, document):
            canvas.saveState()
            canvas.setStrokeColor(rule)
            canvas.line(margin, height - 40, width - margin, height - 40)
            canvas.line(margin, 38, width - margin, 38)
            canvas.setFont('Helvetica-Bold', 8)
            canvas.setFillColor(ink)
            canvas.drawString(margin, height - 28, 'SOFTWARE FOUNDATION / COMPILER REFERENCE')
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColor(muted)
            canvas.drawRightString(width - margin, height - 28, _plain(model.get('generated_at', '')).split('T')[0])
            canvas.setFillColor(accent)
            canvas.drawString(margin, 25, 'Up: What to edit')
            canvas.linkURL('00-edit-paths.pdf', (margin, 21, margin + 74, 35), relative=1)
            canvas.drawString(margin + 94, 25, 'Compiler index')
            canvas.linkRect('', 'compiler', (margin + 94, 21, margin + 164, 35), relative=1, thickness=0)
            canvas.drawString(margin + 184, 25, 'HTML compiler')
            canvas.linkURL('../index.html#build', (margin + 184, 21, margin + 266, 35), relative=1)
            canvas.setFillColor(muted)
            canvas.drawRightString(width - margin, 25, f'{PDF_NAME} | {document.page}')
            canvas.restoreState()

        def afterFlowable(self, item):
            if isinstance(item, Heading):
                self.canv.bookmarkPage(item.destination)
                self.canv.addOutlineEntry(item.label, item.destination, level=item.level, closed=item.level > 0)
                record = {'pdf': PDF_NAME, 'page': self.page}
                if item.target_index is not None:
                    target_refs[str(item.target_index)] = record
                if item.location:
                    location_refs[item.location] = record
                    shared_location_refs.setdefault(item.location, record)

    def location(item: dict) -> str | None:
        file = files.get(item.get('path'))
        return f"{file['id']}:{item.get('line', 1)}" if file else None

    def code(raw: str) -> list[Any]:
        result = []
        for source_line in _plain(raw).expandtabs(4).splitlines() or ['']:
            wrapped = textwrap.wrap(source_line, width=98, break_long_words=True, break_on_hyphens=False,
                                    replace_whitespace=False, drop_whitespace=False) or ['']
            result.extend(p(line or ' ', 'code') for line in wrapped)
        return result

    def statement(item: dict, prefix: str = '') -> list[Any]:
        result = [p((('<b>' + _esc(prefix) + '</b> | ') if prefix else '') + source_link(item), 'small', raw=True)]
        result.extend(context_flow(item))
        raw = item.get('raw') or item.get('command', '') + '(' + ' '.join(map(str, item.get('args', []))) + ')'
        result.extend(code(raw))
        result.append(Spacer(1, 6))
        return result

    def source_token(target: dict, value: str) -> str:
        if not any(token in value for token in ('${', '$ENV{', '$CACHE{', '$<')):
            candidate = str(PurePosixPath(target.get('path', '')).parent / value)
            if candidate.startswith('./'):
                candidate = candidate[2:]
            if candidate in files:
                return source_link({'path': candidate, 'line': 1}, value)
        return _esc(value)

    class Diagram(Flowable):
        """Selected literal dependency evidence, never a configured build graph."""
        def __init__(self):
            super().__init__()
            self.width, self.height = body_width, 272
            positions = {'foundation-cli': (0, 201), 'foundation_gui_application': (350, 201),
                         'foundation::core': (175, 118), 'foundation_gui_boundary': (350, 118),
                         'foundation_core': (175, 35), 'foundation::rust_component': (0, 35)}
            self.nodes = {}
            for name, position in positions.items():
                choices = [(i, t) for i, t in enumerate(targets) if t.get('name') == name]
                if choices:
                    choices.sort(key=lambda pair: (pair[1].get('path', '').startswith('tests/'), pair[1].get('path') == 'cmake/FoundationConfig.cmake.in'))
                    index, target = choices[0]
                    self.nodes[name] = (position, index, target)
            self.edge_count = 0

        def wrap(self, available_width, available_height):
            return self.width, self.height

        def draw(self):
            canvas = self.canv
            def arrow(a, b, dotted=False):
                start, end = self.nodes[a][0], self.nodes[b][0]
                x1, y1 = start[0] + 83, start[1] + 25
                x2, y2 = end[0] + 83, end[1] + 25
                dx, dy = x2 - x1, y2 - y1
                length = (dx * dx + dy * dy) ** .5
                if not length:
                    return
                ux, uy = dx / length, dy / length
                edge_distance = min(83 / abs(ux) if ux else float('inf'),
                                    25.5 / abs(uy) if uy else float('inf')) + 2
                x1 += ux * edge_distance; y1 += uy * edge_distance
                x2 -= ux * edge_distance; y2 -= uy * edge_distance
                canvas.setStrokeColor(accent)
                canvas.setLineWidth(1)
                canvas.setDash(3, 3) if dotted else canvas.setDash()
                canvas.line(x1, y1, x2, y2)
                canvas.setDash()
                triangle = canvas.beginPath()
                triangle.moveTo(x2, y2)
                triangle.lineTo(x2 - ux * 7 - uy * 3, y2 - uy * 7 + ux * 3)
                triangle.lineTo(x2 - ux * 7 + uy * 3, y2 - uy * 7 - ux * 3)
                triangle.close()
                canvas.setFillColor(accent)
                canvas.drawPath(triangle, stroke=0, fill=1)
                self.edge_count += 1
            for name, (_, _, target) in self.nodes.items():
                for target_name in target.get('links', []):
                    if target_name in self.nodes and target_name != name:
                        arrow(name, target_name)
            rust_call = next((item for item in commands if item.get('command') == 'foundation_rust_component'
                              and item.get('args') and item['args'][0] == 'foundation_core'), None)
            if rust_call and 'foundation_core' in self.nodes and 'foundation::rust_component' in self.nodes:
                # A bottom route leaves enough length for a visible dashed helper
                # relationship between adjacent boxes.
                start = self.nodes['foundation_core'][0]
                end = self.nodes['foundation::rust_component'][0]
                x1, x2 = start[0] + 83, end[0] + 83
                canvas.setStrokeColor(accent)
                canvas.setDash(3, 3)
                path = canvas.beginPath()
                path.moveTo(x1, start[1] - 2)
                path.lineTo(x1, 18)
                path.lineTo(x2, 18)
                path.lineTo(x2, end[1] - 2)
                canvas.drawPath(path, stroke=1, fill=0)
                canvas.setDash()
                triangle = canvas.beginPath()
                triangle.moveTo(x2, end[1] - 2)
                triangle.lineTo(x2 - 3, end[1] - 9)
                triangle.lineTo(x2 + 3, end[1] - 9)
                triangle.close()
                canvas.setFillColor(accent)
                canvas.drawPath(triangle, stroke=0, fill=1)
                canvas.setFont('Helvetica', 7)
                canvas.drawCentredString((x1 + x2) / 2, 5, 'conditional helper call')
            for name, ((x, y), index, target) in self.nodes.items():
                canvas.setFillColor(pale)
                canvas.setStrokeColor(rule)
                canvas.roundRect(x, y, 166, 51, 5, stroke=1, fill=1)
                caption = p(_esc(name) + '<br/>' + '<font color="#51626d">' + _esc(target.get('kind', 'target')) + '</font>', 'cell', raw=True)
                _, caption_height = caption.wrap(152, 47)
                caption.drawOn(canvas, x + 7, y + 45 - caption_height)
                canvas.linkRect('', 'target-' + str(index), (x, y, x + 166, y + 51), relative=1, thickness=0)

    story: list[Any] = [Heading('Compiler and toolchain reference', 'compiler'),
                        p('Source registration, link dependencies, configuration defaults, and the declarations behind them.'),
                        p(f"Captured {len(targets)} target records, {len(build.get('options', []))} options/cache defaults, "
                          f"{len(build.get('toolchain', []))} toolchain assignments, and {len(commands)} CMake commands.", 'small'),
                        p('This is a lexical navigation snapshot. CMake conditions, variables, helper bodies, and generator expressions are preserved as source text. '
                          'The generator did not configure or compile the application. Target lists combine declarations across conditions and are not one selected configuration.'),
                        p('The snapshot is regenerated only on explicit request and may be out of date. Source links open the captured HTML explorer; every page links back to the edit-path guide.', 'small')]
    sections = [('targets', '1. Target directory and complete source/link details'),
                ('options', '2. Options and cache defaults'), ('toolchain', '3. Compiler/toolchain assignments'),
                ('configuration', '4. Compiler, link, and dependency configuration commands'),
                ('presets', '5. CMake presets and Cargo manifests'),
                ('helpers', '6. Build helpers and command inventory'), ('warnings', '7. Recorded limitations and warnings')]
    story += [p(link(label, '#' + anchor), raw=True) for anchor, label in sections]
    diagram = Diagram()
    if diagram.nodes:
        story.extend([Spacer(1, 8), diagram,
                      p(f'Selected map: {len(diagram.nodes)} of {len(targets)} target records. Solid arrows follow captured literal link/alias declarations. '
                        'A dashed Rust arrow, when present, marks the observed conditional foundation_rust_component(core) helper call. '
                        'Click a box for its complete target record.', 'small')])

    story += [PageBreak(), Heading('1. Target directory', 'targets'),
              p('Every captured target record is listed below, including aliases, imported targets, helper declarations, and context-dependent duplicates. '
                'Click its name to inspect the complete source/link arguments and declaration context.')]
    rows = [['Target / kind', 'Declaration', 'Source / link entries']]
    for index, target in enumerate(targets):
        rows.append([link(target.get('name', '(unnamed)'), '#target-' + str(index)) + '<br/>' + _esc(target.get('kind', '')),
                     source_link(target), _esc(f"{len(target.get('sources', []))} sources / {len(target.get('links', []))} links")])
    story.append(table(rows, [242, 173, body_width - 415]))
    if not targets:
        story.append(p('No target declarations were captured.'))
    statement_index = {(item.get('path'), item.get('line')): item for item in commands}
    for index, target in enumerate(targets):
        story.extend([CondPageBreak(126), Heading(f"Target {index + 1}: {target.get('name', '(unnamed)')}", 'target-' + str(index), 1, index, location(target)),
                      p(_esc(target.get('kind', 'target')) + ' | ' + source_link(target) + ' | ' + link('HTML target view', '../index.html#build/target/' + str(index)), 'small', raw=True)])
        story.extend(context_flow(target))
        if target.get('symbolic'):
            story.append(p('This record contains symbolic values. Resolve its variables and enclosing context in the source before registering another file.', 'small'))
        if target.get('alias_of'):
            story.append(p('Alias of: ' + str(target['alias_of'])))
        declaration = statement_index.get((target.get('path'), target.get('line')))
        if declaration:
            story.extend(code(declaration.get('raw', '')))
        entries = [['Source arguments (all)', 'Link arguments (all)']]
        sources, links = target.get('sources', []), target.get('links', [])
        for number in range(max(len(sources), len(links), 1)):
            entries.append([source_token(target, str(sources[number])) if number < len(sources) else '',
                            _esc(links[number]) if number < len(links) else ''])
        story.append(table(entries, [body_width * .57, body_width * .43]))
        if not sources and not links:
            story.append(p('No source or link arguments were recorded for this target. Imported/interface declarations may acquire them through settings or helpers shown in the source.', 'small'))
        for field, label in [('source_statements', 'Additional source statement'), ('link_statements', 'Link statement')]:
            for command in target.get(field, []):
                story.extend(statement(command, label))

    story += [PageBreak(), Heading('2. Options and cache defaults', 'options'),
              p('Defaults are values written in option()/set(... CACHE ...) declarations. They are not the effective values of a configured build.')]
    for index, option in enumerate(build.get('options', [])):
        story.extend([CondPageBreak(85), Heading(option.get('name', '(unnamed)'), 'option-' + str(index), 1, location=location(option)),
                      p(source_link(option), 'small', raw=True),
                      property_table([(key, '(empty string)' if option[key] == '' else str(option[key]))
                                      for key in ('default', 'cache_type', 'description') if key in option])])
        story.extend(context_flow(option))
    if not build.get('options'):
        story.append(p('No option/cache default declarations were captured.'))

    story += [PageBreak(), Heading('3. Compiler/toolchain assignments', 'toolchain'),
              p('All captured compiler/toolchain assignments are printed with their complete value tokens and enclosing source context. '
                'The selection includes CMAKE_* names and names containing COMPILER or TOOLCHAIN. '
                'Assignments in a toolchain/helper are declarations; no SDK or compiler is discovered or invoked here.')]
    for index, setting in enumerate(build.get('toolchain', [])):
        story.extend([CondPageBreak(86), Heading(setting.get('name', '(unnamed)'), 'setting-' + str(index), 1, location=location(setting)),
                      p(source_link(setting), 'small', raw=True),
                      property_table([(f'Value token {n + 1}', str(value)) for n, value in enumerate(setting.get('values', []))])])
        story.extend(context_flow(setting))
    if not build.get('toolchain'):
        story.append(p('No toolchain assignments were captured.'))

    selected = [item for item in commands if item.get('command') in CONFIGURATION_COMMANDS]
    story += [PageBreak(), Heading('4. Configuration command reference', 'configuration'),
              p(f'All {len(selected)} commands in the compiler/link/dependency command selection below are printed with full arguments and context. '
                f'The other {len(commands) - len(selected)} of {len(commands)} captured commands remain in the complete HTML/JSON inventory. '
                'Target source/link declarations already have full detail in section 1; option defaults and CMAKE_* assignments are in sections 2-3.'),
              p('Selection: ' + ', '.join(sorted(CONFIGURATION_COMMANDS)), 'small'),
              p(link('Open the complete compiler explorer', '../index.html#build') + ' | ' + link('Captured JSON inventory', '../atlas.json'), 'small', raw=True)]
    previous_path = None
    for index, command in enumerate(selected):
        if command.get('path') != previous_path:
            story.extend([CondPageBreak(105), Heading(command.get('path', '(unknown source)'), 'config-file-' + str(index), 1)])
            previous_path = command.get('path')
        story.extend([CondPageBreak(64)] + statement(command, command.get('command', 'command')))

    story += [PageBreak(), Heading('5. Presets and Cargo manifests', 'presets'),
              p('Every parsed manifest field is printed, including inherited preset names and symbolic paths. '
                'Preset inheritance, cache expansion, Cargo dependency selection, and target-specific conditions are not evaluated.')]
    manifest_number = 0
    for family, documents in [('CMake presets', build.get('presets', {})), ('Cargo', build.get('cargo', {}))]:
        for path, data in documents.items():
            story.extend([CondPageBreak(100), Heading(f'{family}: {path}', 'manifest-' + str(manifest_number), 1),
                          p(source_link({'path': path, 'line': 1}), 'small', raw=True), property_table(_leaves(data))])
            manifest_number += 1
    if not manifest_number:
        story.append(p('No parsed CMake preset or Cargo manifests were captured.'))

    story += [PageBreak(), Heading('6. Helpers and command inventory', 'helpers'),
              p('Helper parameters are declared names; the documentation does not execute helper calls or expand loop-generated targets.')]
    rows = [['Helper / kind', 'Declared parameters', 'Source']]
    for declaration in build.get('declarations', []):
        rows.append([_esc(declaration.get('name', '')) + '<br/>' + _esc(declaration.get('kind', '')),
                     _esc(' '.join(map(str, declaration.get('parameters', [])))), source_link(declaration)])
    story.append(table(rows, [177, 168, body_width - 345]))
    story.append(Heading('Complete command inventory counts', 'command-counts', 1))
    story.append(p(f'{len(commands)} captured CMake commands. Counts include control statements and declarations in every recorded branch/helper; '
                   'they do not describe a single configured execution. Raw commands and source contexts are retained in atlas.json and the HTML explorer.'))
    counts = Counter(item.get('command', '(unknown)') for item in commands)
    rows = [['Command', 'Count', 'Printed configuration selection']]
    rows.extend([_esc(name), str(count), 'Full detail in section 4' if name in CONFIGURATION_COMMANDS else 'Full inventory in HTML / JSON']
                for name, count in sorted(counts.items()))
    story.append(table(rows, [224, 54, body_width - 278]))
    story += [p(link('Complete build inventory', '../index.html#build') + ' | ' + link('All captured command records', '../atlas.json'), raw=True),
              PageBreak(), Heading('7. Recorded limitations and warnings', 'warnings')]
    warning_values = build.get('warnings', [])
    if warning_values:
        story += [p(f'{index + 1}. {warning}') for index, warning in enumerate(warning_values)]
    else:
        story.append(p('No build-map warnings were recorded.'))
    story += [p('This PDF is a printable view of captured evidence. File registration, compiler flags, conditions, and provider ownership must be checked in the linked source before editing. '
                'The retained GUI supplier references, where included elsewhere in this snapshot, are unpatched archive members and do not represent a configured dependency.'),
              p(link('Up: What to edit', '00-edit-paths.pdf') + ' | ' + link('Compiler explorer', '../index.html#build'), raw=True)]
    Book().build(story)
    return 'pdf/' + PDF_NAME
