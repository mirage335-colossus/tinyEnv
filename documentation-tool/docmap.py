#!/usr/bin/env python3
"""Manually build offline what-to-edit flow charts and their source reference.

This program never imports target code, invokes target scripts, configures a
build, restores dependencies, or writes within the source tree.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat

TOOL_ROOT = Path(__file__).resolve().parent
EXCLUDED_DIRS = {'.git', '.agent-work', '.agent-pending', '.codex', '.agents', '.aws',
                 '.venv', 'venv', '__pycache__', 'build', 'third_party',
                 'node_modules', 'target', 'dist', '.cache', 'documentation-tool'}
SOURCE_LANGUAGES = {
    '.c': 'cpp', '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.h': 'cpp',
    '.hh': 'cpp', '.hpp': 'cpp', '.hxx': 'cpp', '.rs': 'rust',
    '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
    '.py': 'python', '.sh': 'bash', '.bash': 'bash', '.cmake': 'cmake',
}
TEXT_EXTENSIONS = {'.md', '.txt', '.toml', '.json', '.yml', '.yaml', '.in',
                   '.patch', '.ps1', '.html', '.css', '.lock', '.1', '.7',
                   '.manifest', '.rc'}
TEXT_NAMES = {'COMPILE', 'COMPILE-gui', 'COMPILE-web', 'RELEASE', 'SCREENSHOTS',
              'LICENSE', 'Makefile', 'Dockerfile', '.gitignore', '.gitattributes',
              '.editorconfig'}
PARSER_PACKAGES = ['tree-sitter', 'tree-sitter-cpp', 'tree-sitter-rust',
                   'tree-sitter-python', 'tree-sitter-javascript', 'tree-sitter-bash']
PDFS = [
    {'name': '00-edit-paths.pdf', 'title': 'What to edit: practical development paths', 'category': 'changes'},
    {'name': '01-code-walkthroughs.pdf', 'title': 'Code walkthroughs: ownership, control, and full source', 'category': 'walkthroughs'},
    {'name': '02-compiler-reference.pdf', 'title': 'Compiler and configuration reference', 'category': 'build'},
    {'name': '03-execution-flows.pdf', 'title': 'What runs when: calls, commands, and event handoffs', 'category': 'flows'},
    {'name': '04-code-flowcharts.pdf', 'title': 'Inside the steps: actual code and configuration flowcharts', 'category': 'code-flows'},
    {'name': 'AI-AUTHORED__GUI-MENTAL-MODEL.pdf', 'title': 'AI-authored: the GUI mental model', 'category': 'concepts'},
]
REFERENCE_PDFS = [
    {'name': '00-start-here.pdf', 'title': 'Start here', 'category': 'overview'},
    {'name': '01-toolchain.pdf', 'title': 'Toolchain and configuration', 'category': 'build'},
    {'name': '02-core.pdf', 'title': 'Core and CLI', 'category': 'core'},
    {'name': '03-gui.pdf', 'title': 'GUI and browser hosts', 'category': 'gui'},
    {'name': '04-tools.pdf', 'title': 'Developer tooling', 'category': 'tools'},
    {'name': '05-tests.pdf', 'title': 'Tests and examples', 'category': 'tests'},
]


def identity(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def default_source() -> Path:
    return TOOL_ROOT.parent if TOOL_ROOT.name == 'documentation-tool' else TOOL_ROOT.parent / 'software-foundation'


def default_output(source: Path, stamp: str) -> Path:
    if TOOL_ROOT == source / 'documentation-tool':
        return source.parent / (source.name + '-documentation') / 'snapshots' / stamp
    return TOOL_ROOT / 'snapshots' / stamp


def category(path: str, language: str) -> str:
    parts = Path(path).parts
    if 'tests' in parts or parts[0] == 'examples':
        return 'tests'
    if parts[0] in {'src', 'include', 'rust'}:
        return 'core'
    if parts[0] == 'gui':
        return 'build' if language == 'cmake' else 'gui'
    if parts[0] == 'tools':
        return 'tools'
    if parts[0] in {'cmake', '.github'} or language == 'cmake' or parts[0] in {
            'build.sh', 'CMakePresets.json', 'COMPILE', 'COMPILE-gui', 'COMPILE-web'}:
        return 'build'
    return 'other'


def read_regular(path: Path, max_bytes: int) -> tuple[bytes, os.stat_result]:
    # Refuse a final-component symlink even if a concurrent writer replaces it
    # after inventory. Directory symlinks are pruned by collect_files.
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('not a regular file')
        if before.st_size > max_bytes:
            raise ValueError(f'exceeds file-size limit ({max_bytes} bytes)')
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > max_bytes:
        raise ValueError(f'exceeds file-size limit ({max_bytes} bytes)')
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('changed while reading; retry a later snapshot')
    return raw, after


def collect_files(source: Path, max_bytes: int, extra_excludes: list[str]) -> tuple[list, list]:
    files, skipped = [], []
    def skip(path: str, reason: str) -> None:
        skipped.append({'path': path, 'reason': reason})
    def error(exc: OSError) -> None:
        skip(str(exc.filename), str(exc))
    for root, dirs, names in os.walk(source, topdown=True, followlinks=False, onerror=error):
        base = Path(root)
        keep = []
        for name in sorted(dirs):
            p = base / name
            rel = p.relative_to(source).as_posix()
            if name in EXCLUDED_DIRS or rel in extra_excludes:
                skip(rel + '/', 'excluded directory (contents not traversed)')
            elif p.is_symlink():
                skip(rel + '/', 'symlink directory (not followed)')
            else:
                keep.append(name)
        dirs[:] = keep
        for name in sorted(names):
            path = base / name
            rel = path.relative_to(source).as_posix()
            if rel in extra_excludes:
                skip(rel, 'user exclusion')
                continue
            if path.is_symlink():
                skip(rel, 'symlink file (not followed)')
                continue
            language = 'cmake' if name == 'CMakeLists.txt' else SOURCE_LANGUAGES.get(path.suffix, 'text')
            if language == 'text' and path.suffix not in TEXT_EXTENSIONS and name not in TEXT_NAMES:
                skip(rel, 'binary or unrecognized file type')
                continue
            try:
                if not within(path.resolve(strict=True), source):
                    raise ValueError('resolved path is outside source root')
                raw, info = read_regular(path, max_bytes)
                if b'\x00' in raw:
                    raise ValueError('binary file (NUL bytes)')
                text = raw.decode('utf-8-sig')
            except (OSError, ValueError, UnicodeError) as exc:
                skip(rel, str(exc))
                continue
            files.append({'id': 'f-' + identity(rel), 'path': rel,
                          'category': category(rel, language), 'language': language,
                          'text': text, 'sha256': hashlib.sha256(raw).hexdigest(),
                          'line_count': len(text.splitlines()), 'size': len(raw),
                          'symbols': [], 'imports': [],
                          'mtime_ns': info.st_mtime_ns})
    return sorted(files, key=lambda item: item['path']), skipped


def resolve_calls(files: list[dict]) -> None:
    """Suggest source-name candidates, without pretending to perform type analysis."""
    functions = []
    for file in files:
        for symbol in file['symbols']:
            symbol['file_id'] = file['id']
            symbol['path'] = file['path']
            symbol['language'] = file['language']
            if symbol['kind'] not in {'module', 'namespace', 'impl', 'trait', 'enum'}:
                functions.append(symbol)
    by_exact, by_short = defaultdict(list), defaultdict(list)
    for symbol in functions:
        by_exact[(symbol['qualified_name'], symbol['file_id'])].append(symbol)
        short = re.split(r'::|\.|->', symbol['name'])[-1]
        by_short[short].append(symbol)
    for file in files:
        for symbol in file['symbols']:
            for call in symbol.get('calls', []):
                name = call['name'].strip()
                short = re.split(r'::|\.|->', name)[-1]
                # Any dotted/member/qualified call could refer to another type or
                # language. Never erase that ambiguity by selecting one arbitrarily.
                candidates = by_exact.get((name, file['id']), [])
                if not candidates:
                    candidates = by_short.get(short, [])
                allowed_languages = ({'cpp', 'rust'} if file['language'] in {'cpp', 'rust'}
                                     else {file['language']})
                candidates = [s for s in candidates if s['language'] in allowed_languages]
                candidates = sorted(candidates, key=lambda s: (s['file_id'] != file['id'], s['path'], s['line']))
                call['targets'] = list(dict.fromkeys(s['id'] for s in candidates))
                call['resolution'] = ('name-candidate' if len(candidates) == 1 else
                                      'ambiguous-name' if candidates else 'unresolved')


def recheck_files(source: Path, files: list[dict], max_bytes: int) -> list[str]:
    changed = []
    for file in files:
        if file.get('origin') == 'supplier-reference':
            continue  # Virtual member paths are rechecked through their retained inputs.
        try:
            raw, _ = read_regular(source / file['path'], max_bytes)
            if hashlib.sha256(raw).hexdigest() != file['sha256']:
                changed.append(file['path'])
        except (OSError, ValueError):
            changed.append(file['path'])
    return changed


def make_model(source: Path, max_bytes: int, excludes: list[str], pdfs: bool,
               reference_handbooks: bool = False) -> dict:
    from syntax_scan import scan_source
    from build_map import analyze_build
    from navigation_guide import make_guide
    from change_maps import make_change_maps
    from flow_maps import make_flow_maps
    from code_maps import make_code_maps
    from conceptual_guide import make_conceptual_guide
    from supplier_reference import capture_supplier_references, recheck_supplier_references
    files, skipped = collect_files(source, max_bytes, excludes)
    supplier_files, supplier_provenance, warnings = capture_supplier_references(source, max_bytes, read_regular)
    files = sorted(files + supplier_files, key=lambda item: item['path'])
    for index, file in enumerate(files):
        if file['language'] == 'text':
            continue
        scanned = scan_source(file['path'], file['text'], file['language'])
        file['symbols'] = scanned['symbols']
        file['imports'] = scanned.get('imports', [])
        file['parse_warnings'] = scanned.get('warnings', [])
        warnings.extend(f"{file['path']}: {message}" for message in scanned.get('warnings', []))
        if (index + 1) % 40 == 0:
            print(f"  Read {index + 1}/{len(files)} files", file=sys.stderr)
    resolve_calls(files)
    build = analyze_build(files)
    warnings.extend(build.get('warnings', []))
    changed = recheck_files(source, files, max_bytes)
    changed.extend(recheck_supplier_references(source, supplier_provenance, read_regular))
    changed = sorted(set(changed))
    if changed:
        warnings.append('Some inputs changed during capture. This is a mixed-time navigation snapshot: ' + ', '.join(changed))
    fingerprint = hashlib.sha256(''.join(f"{f['path']}\0{f['sha256']}\n" for f in files).encode()).hexdigest()
    languages = Counter(f['language'] for f in files)
    flows = make_flow_maps(files)
    code_maps = make_code_maps(files, flows)
    return {
        'schema_version': 2, 'title': 'software-foundation | What to edit',
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'source_root': str(source), 'fingerprint': fingerprint,
        'warnings': warnings, 'skipped': skipped, 'changed_during_scan': changed,
        'supplier_references': supplier_provenance,
        'files': files, 'build': build, 'guide': make_guide(files),
        'change_maps': make_change_maps(files),
        'flow_maps': flows,
        'code_maps': code_maps,
        'conceptual_guide': make_conceptual_guide(files, code_maps),
        'pdfs': (PDFS + (REFERENCE_PDFS if reference_handbooks else [])) if pdfs else [],
        'coverage': {'files': len(files), 'languages': dict(languages),
                     'symbols': sum(len(f['symbols']) for f in files),
                     'scope': 'Owned source, scripts, declarations and documentation, plus four checked pinned GUI supplier references read into memory; other excluded directory contents are not traversed.',
                     'limitations': [
                         'Navigation snapshot generated only on explicit request; it may be out of date.',
                         'Syntax trees expose control structure, not compiler-validated execution paths.',
                         'Call links are name-based candidates, not proven dispatch or a whole-program call graph.',
                         'Macros, preprocessor selections, virtual dispatch, callbacks, overloads and generated code may remain ambiguous.',
                         'CMake is read as declarations. Conditions, variables and generator expressions are not evaluated.',
                         'Build output and third-party contents are excluded except four regular GUI contract/example members checked against retained pins; no inputs are restored or generated.',
                         'Supplier reference bytes are unpatched upstream source from the retained archive. Their provenance and capture status are recorded; missing or inconsistent pins remain visible.',
                         'CMake control outlines are lexical and unevaluated; other configuration/text-only files have source views.',
                         'Per-file captured bytes are embedded. Concurrent edits or newly added files may prevent a single atomic snapshot.',
                     ]},
        'generator': {'name': 'software-foundation-docmap', 'version': '2.5',
                      'packages': {name: importlib.metadata.version(name) for name in PARSER_PACKAGES}},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=default_source(), help='Source tree to read (never written); defaults to the containing checkout when installed as documentation-tool')
    parser.add_argument('--output', type=Path, help='New output directory outside source; existing paths are refused')
    parser.add_argument('--no-pdf', action='store_true', help='Generate offline HTML/JSON only, without ReportLab')
    parser.add_argument('--reference-handbooks', action='store_true', help='Also print six broad reference inventories in addition to the default development handbooks and AI-authored conceptual guide')
    parser.add_argument('--exclude', action='append', default=[], metavar='RELATIVE_PATH', help='Additional source-relative file/directory to skip; repeatable')
    parser.add_argument('--max-file-mb', type=int, default=4, help='Per-file read limit; skipped files are reported (default 4 MiB)')
    args = parser.parse_args(argv)
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f'Source directory does not exist: {source}')
    if args.max_file_mb < 1:
        parser.error('--max-file-mb must be positive')
    if TOOL_ROOT == source:
        parser.error('The generator directory cannot be the source root')
    if within(TOOL_ROOT, source) and TOOL_ROOT != source / 'documentation-tool':
        parser.error('An in-checkout generator must be the excluded documentation-tool directory directly below the source root')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output = (args.output or default_output(source, stamp)).expanduser().resolve()
    if within(output, source) or within(source, output):
        parser.error('Output must be outside, and must not contain, the source tree')
    if output.exists():
        parser.error(f'Output already exists; choose a fresh directory: {output}')
    for exclusion in args.exclude:
        if Path(exclusion).is_absolute() or '..' in Path(exclusion).parts:
            parser.error('--exclude values must be relative paths without ..')
    try:
        for package in PARSER_PACKAGES:
            importlib.metadata.version(package)
        if not args.no_pdf:
            importlib.metadata.version('reportlab')
    except importlib.metadata.PackageNotFoundError as exc:
        parser.error(f'Missing documentation dependency: {exc}. Install requirements.txt in a separate virtual environment; see README.md.')
    print(f'Reading source only: {source}', file=sys.stderr)
    model = make_model(source, args.max_file_mb * 1024 * 1024,
                       [Path(p).as_posix().rstrip('/') for p in args.exclude], not args.no_pdf,
                       args.reference_handbooks)
    # Deliberately no deletion or overwrite mode. Every invocation produces a
    # distinct snapshot; a failed rendering stays inspectable at its output path.
    output.mkdir(parents=True, exist_ok=False)
    if not args.no_pdf:
        # Render references first so the charts and explorer can link to exact
        # printable pages. These modules only consume the captured model.
        from render_walkthrough_pdf import render_walkthrough_pdf
        from render_compiler_pdf import render_compiler_pdf
        from render_change_pdf import render_change_pdfs
        from render_flow_pdf import render_flow_pdf
        from render_code_pdf import render_code_pdf
        from render_concept_pdf import render_concept_pdf
        render_walkthrough_pdf(model, output)
        render_compiler_pdf(model, output)
        render_flow_pdf(model, output)
        parent_pages = {group: dict(model['print_references'][group])
                        for group in ('flow_maps', 'flow_nodes')}
        render_code_pdf(model, output)
        render_concept_pdf(model, output)
        # The first overview pass establishes exact parent pages. The code
        # book establishes child pages; this final pass resolves both ways.
        render_flow_pdf(model, output)
        if any(model['print_references'][group] != pages
               for group, pages in parent_pages.items()):
            raise ValueError('Execution PDF pagination changed while linking code diagrams; parent links need review')
        render_change_pdfs(model, output)
        if args.reference_handbooks:
            from render_pdf import render_pdfs
            render_pdfs(model, output)
    (output / 'atlas.json').write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding='utf-8')
    from render_html import render_html
    render_html(model, output)
    from render_concept_html import render_concept_html
    render_concept_html(model, output)
    print(f"Created {model['coverage']['files']} files / {model['coverage']['symbols']} symbols")
    print(f"Open: {output / 'index.html'}")
    print(f"AI-authored conceptual guide: {output / model['conceptual_guide']['html_file']}")
    if not args.no_pdf:
        for pdf in model['pdfs']:
            print(f"Print: {output / 'pdf' / pdf['name']}")
    print(f"Capture SHA256: {model['fingerprint']}")
    if model['warnings']:
        print(f"{len(model['warnings'])} analysis warnings are recorded in the snapshot.")
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f'docmap: {exc}', file=sys.stderr)
        raise SystemExit(1)
