#!/usr/bin/env python3
"""Check application sources and concrete GUI/domain dependencies before compiling.

This is an architectural tripwire, not a C++ parser or a security boundary. Keep
executable conformance and public-interface review alongside it.
"""
from pathlib import Path
import argparse
import posixpath
import re
import sys

PUBLIC_GUI = {'gui/contract.hpp', 'gui/layout.hpp', 'gui/runtime.hpp'}
SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx',
                   '.ipp', '.tpp', '.inc', '.ixx', '.cppm', '.rs'}
# Keep string contents while removing comments, so includes and widget IDs remain
# visible and an explanatory comment cannot create a false dependency.
TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*', re.S)
RUST_LITERAL = re.compile(
    r'(?:br|r)(?P<hashes>\#*)".*?"(?P=hashes)|'
    r'b?"(?:\\.|[^"\\])*"|'
    r"b?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\])'", re.S)
RUST_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|::|[^\s]')
RUST_BACKENDS = {'gui', 'fl', 'fltk', 'sdl', 'sdl2', 'rev', 'backends', 'host', 'hosts'}


def rust_code(source):
    """Keep Rust identifiers and attribute literals without comments or lifetimes loss."""
    tokens, literals, index = [], {}, 0
    while index < len(source):
        if source.startswith('//', index):
            end = source.find('\n', index)
            index = len(source) if end < 0 else end
            continue
        if source.startswith('/*', index):
            index += 2
            depth = 1
            while index < len(source) and depth:
                if source.startswith('/*', index): depth += 1; index += 2
                elif source.startswith('*/', index): depth -= 1; index += 2
                else: index += 1
            continue
        literal = RUST_LITERAL.match(source, index)
        if literal:
            value = literal[0]
            name = 'RUST_LITERAL_' + str(len(literals))
            if '"' in value:
                begin, end = value.find('"') + 1, value.rfind('"')
                contents = value[begin:end]
                if literal['hashes'] is None:
                    contents = re.sub(r'\\u\{([0-9a-fA-F_]+)\}',
                                      lambda m: chr(int(m[1].replace('_', ''), 16)), contents)
                    contents = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), contents)
                    contents = re.sub(r'\\([\\"nrt0])',
                                      lambda m: {'n':'\n', 'r':'\r', 't':'\t', '0':'\0'}.get(m[1], m[1]), contents)
                literals[name] = contents
            else:
                literals[name] = ''
            tokens.append(name)
            index = literal.end()
            continue
        token = RUST_TOKEN.match(source, index)
        if token:
            tokens.append(token[0]); index = token.end()
        else:
            index += 1
    return ' '.join(tokens), literals


def rust_violations(source):
    code, literals = rust_code(source)
    result = []
    imports = re.findall(r'\b(?:use|extern\s+crate)\s+([^;]+);', code)
    if any(RUST_BACKENDS.intersection(name.lower() for name in re.findall(r'\b\w+\b', entry))
           for entry in imports):
        result.append('concrete Rust GUI/backend import')
    if re.search(r'\b(?:gui|fltk|sdl2?|rev|backends|hosts?)\s*::', code, re.I) or re.search(
            r'\b(?:SDL_\w+|Fl_\w+|Rev_\w+|foundation_gui_\w+|gui_\w+|fltk_\w+|'
            r'(?:Terminal|Framebuffer|Web|Memory|Interactive|Retained)Adapter)\b', code):
        result.append('concrete Rust backend dependency')
    for block in re.findall(r'\bextern\s+RUST_LITERAL_\d+\s*\{([^}]+)\}', code):
        if any(re.match(r'(?:sdl_|sdl2_|rev_|Rev|fltk_|Fl_)', name)
               for name in re.findall(r'\bfn\s+(\w+)', block)):
            result.append('concrete Rust backend foreign symbol')
    for attribute in re.findall(r'#\s*!?\s*\[([^\]]+)\]', code):
        for field in ('name', 'link_name'):
            if field == 'name' and not re.match(r'\s*link\s*\(', attribute):
                continue
            match = re.search(r'\b' + field + r'\s*=\s*(\w+)', attribute)
            if not match:
                continue
            if match[1] not in literals:
                result.append('computed Rust native linkage hides dependency boundary')
                continue
            name = literals[match[1]]
            if re.search(r'^(?:lib)?(?:gui|foundation_gui|fltk|fl|sdl2?(?:main)?|rev)(?:\b|[_0-9.-])', name, re.I):
                result.append('concrete Rust backend linkage: ' + name)
        path = re.search(r'\bpath\s*=\s*(RUST_LITERAL_\d+)', attribute)
        if path and any(part.lower() in RUST_BACKENDS for part in Path(literals[path[1]]).parts):
            result.append('concrete Rust backend module path')
    return result


def uncomment(source):
    return TOKENS.sub(lambda m: ('\n' * m[0].count('\n') if m[0].startswith(('/',)) else m[0]),
                      source.replace('\\\n', ''))


def include_entries(source):
    for directive, body in re.findall(r'^\s*#\s*(include|include_next)\b\s*([^\n]+)', uncomment(source), re.M):
        match = re.fullmatch(r'\s*(?:<([^>]+)>|"([^"]+)")\s*', body)
        if directive == 'include_next' or not match:
            yield None, False
        else:
            yield match[1] or match[2], match[2] is not None


def includes(source):
    return (name for name, _ in include_entries(source))


def shared_violations(source):
    result = []
    source = uncomment(source)
    for include in includes(source):
        if include is None:
            result.append('computed include hides the application dependency boundary')
            continue
        name = posixpath.normpath(include.replace('\\', '/'))
        gui = re.search(r'(?:^|/)(gui/.*)$', name)
        if gui and gui[1] not in PUBLIC_GUI:
            result.append(include)
        if any(part.lower() in ('fl', 'sdl', 'sdl2', 'backends', 'hosts', 'host')
               for part in name.split('/')) or re.search(r'(?:^|/)(?:windows\.h|SDL[^/]*)$', name, re.I):
            result.append(include)
    code = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', source)
    if re.search(r'\b(?:import\s+Rev|Rev\s*::|Fl_\w+|Fl\s*::|SDL_\w+|'
                 r'(?:Terminal|Framebuffer|Web|Memory|Interactive|Retained)Adapter|'
                 r'gui\s*::\s*(?:fltk|rev)\b)', code):
        result.append('concrete backend dependency')
    return result


def without_includes(source):
    return re.sub(r'^\s*#\s*include\b[^\n]*', '', source, flags=re.M)


def composition_root(root, path):
    return path.parent == root / 'hosts' and path.name.endswith(('_main.cpp', '_main.rs'))


def sources(directory):
    return sorted(path for path in directory.rglob('*')
                  if path.is_file() and path.suffix in SOURCE_SUFFIXES)


def resolve_include(root, path, name, quoted=True):
    if name is None:
        return None
    candidates = ([path.parent / name] if quoted else []) + [root / name, root.parent / 'include' / name]
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve()
            if root.parent != resolved and root.parent not in resolved.parents:
                raise ValueError('local include escapes project: ' + name)
            return resolved
    return None  # External public/standard headers are checked by name/compiler.


def analyze(root):
    root = Path(root).resolve()
    failures, dependencies, visited = [], set(), set()
    shared_paths = sources(root / 'shared')
    identities = {'entries.'}
    for path in shared_paths:
        if path.suffix == '.rs':
            identities.update(value for value in rust_code(path.read_text())[1].values()
                              if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_.-]+', value))
        else:
            identities.update(re.findall(r'"([A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_.-]+)"', without_includes(uncomment(path.read_text()))))

    def walk(path, layer):
        key = (path, layer)
        if key in visited:
            return
        visited.add(key); dependencies.add(path)
        if path.suffix == '.rs':
            source = path.read_text()
            issues = rust_violations(source) if layer == 'shared' else []
            if layer == 'host':
                code, literals = rust_code(source)
                if any(value.startswith('entries.') or value in identities for value in literals.values()):
                    issues.append('application identity in Rust host')
                if re.search(r'\bfoundation\s*::\s*(?:Store|Record|InsertResult|InsertError)\b', code) or re.search(
                        r'\buse\s+foundation\s*::\s*\{[^;]*(?:Store|Record|InsertResult|InsertError)\b', code):
                    issues.append('application domain dependency in Rust host')
                app_types = re.findall(r'\bfoundation\s*::\s*ui\s*::\s*(\w+)', code)
                if any(name != 'Application' or not composition_root(root, path) for name in app_types):
                    issues.append('application implementation in Rust host')
            failures.extend(str(path) + ': ' + issue for issue in issues)
            return
        text = uncomment(path.read_text())
        issues = shared_violations(text) if layer == 'shared' else []
        if layer == 'host':
            literals = re.findall(r'"((?:\\.|[^"\\])*)"', without_includes(text))
            if any(value.startswith('entries.') or value in identities for value in literals):
                issues.append('application identity in host')
            if re.search(r'\bfoundation\s*::\s*(?:Store|Record|InsertResult|InsertError)\b', text):
                issues.append('application domain dependency in host')
            app_types = re.findall(r'\bfoundation\s*::\s*ui\s*::\s*(\w+)', text)
            if any(name != 'Application' or not composition_root(root, path) for name in app_types):
                issues.append('application implementation in host')
        for name, quoted in include_entries(text):
            if name is None:
                if layer == 'host': issues.append('computed include hides host dependency boundary')
                continue
            try:
                target = resolve_include(root, path, name, quoted)
            except ValueError as error:
                issues.append(str(error)); continue
            if target is None:
                continue
            if layer == 'shared' and any(directory in target.parents for directory in (root/'host', root/'hosts')):
                issues.append('host dependency through ' + name); continue
            if layer == 'host' and root.parent / 'include/foundation' in target.parents:
                issues.append('application domain header through ' + name); continue
            if layer == 'host' and root / 'shared' in target.parents:
                # Composition roots may name the public application type. A
                # helper cannot smuggle feature code into generic host services.
                if target != root/'shared/application.hpp' or not composition_root(root, path):
                    issues.append('shared application implementation through ' + name)
                dependencies.add(target)
                continue
            walk(target, layer)
        failures.extend(str(path) + ': ' + issue for issue in issues)

    for path in shared_paths:
        walk(path.resolve(), 'shared')
    for path in sources(root.parent / 'rust'):
        if path.suffix == '.rs':
            walk(path.resolve(), 'shared')
    for directory in ('host', 'hosts'):
        for path in sources(root / directory):
            walk(path.resolve(), 'host')
    return sorted(set(failures)), sorted(dependencies)


def tree_violations(root):
    return analyze(root)[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies', action='store_true')
    args = parser.parse_args()
    failures, dependencies = analyze(Path(__file__).resolve().parent)
    if args.dependencies:
        print(';'.join(str(path) for path in dependencies), end='')
    elif failures:
        print('\n'.join(failures), file=sys.stderr)
        sys.exit(1)
