#!/usr/bin/env python3
"""Assemble the reviewed renderer graph without a general JavaScript bundler.

The generated module contains data only. Its script is executed exclusively in
the opaque renderer document, under an exact hash and allow-scripts sandbox.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

CHILD_PROTOCOL = 'foundation-renderer-v1'
CHILD_SANDBOX = 'allow-scripts'
BUNDLE_NAME = 'renderer_child_bundle.mjs'
CHILD_MODULES = ('browser_limits.mjs', 'browser_presenter.mjs',
                 'renderer_channel.mjs', 'renderer_dom.mjs', 'renderer_frame.mjs')
CHILD_GRAPH = {
    'browser_limits.mjs': (),
    'browser_presenter.mjs': (),
    'renderer_channel.mjs': ('browser_limits.mjs',),
    'renderer_dom.mjs': ('browser_limits.mjs',),
    'renderer_frame.mjs': ('renderer_dom.mjs', 'browser_presenter.mjs',
                           'renderer_channel.mjs', 'browser_limits.mjs'),
}
CHILD_EXPORTS = {
    'browser_limits.mjs': ('MAX_OPERATION_BYTES', 'MAX_QUEUED_BYTES',
                           'MAX_CHANNEL_REQUESTS', 'MAX_STATE_BYTES', 'CHANNEL_PROTOCOL'),
    'browser_presenter.mjs': ('createBrowserPresenter',),
    'renderer_channel.mjs': ('clonePacket', 'validateRendererOperation',
                            'publicSnapshot', 'createRendererRequests', 'createHostChannel'),
    'renderer_dom.mjs': ('identity', 'byteOffset', 'utf16Offset', 'Renderer'),
    'renderer_frame.mjs': ('startRendererFrame',),
}
IDENTIFIER = r'[A-Za-z_$][A-Za-z0-9_$]*'
IMPORT = re.compile(r'import\s*\{([^{}]*)\}\s*from\s*([\'"])(\./[A-Za-z0-9_.-]+)\2\s*;')
EXPORT = re.compile(r'export\s+(?:(?:async\s+)?function|class|const|let)\s+(' + IDENTIFIER + r')\b')
DYNAMIC_IMPORT = re.compile(r'\bimport(?:\s|/\*[\s\S]*?\*/|//[^\r\n]*(?:\r?\n|$))*\(')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def child_csp(script):
    hash_value = base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii')
    return ("default-src 'none'; script-src 'sha256-" + hash_value + "'; "
            "connect-src 'none'; worker-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:; object-src 'none'; base-uri 'none'; form-action 'none'; "
            "frame-src 'none'; child-src 'none'")


def _keywords(source, all_tokens=False):
    """Find executable import/export tokens, including template expressions.

    This is deliberately a bounded lexical scanner, not a JavaScript parser.
    Unknown syntax is rejected by the reviewed declaration recognizers below.
    Regex literals are data; declaration recognition remains intentionally narrow.
    """
    size = len(source)
    found = []

    def quoted(index, quote):
        index += 1
        while index < size:
            if source[index] == '\\':
                index += 2
            elif source[index] == quote:
                return index + 1
            elif source[index] in '\r\n' and quote != '`':
                raise ValueError('Unterminated JavaScript string')
            else:
                index += 1
        raise ValueError('Unterminated JavaScript string')

    def template(index):
        index += 1
        while index < size:
            if source[index] == '\\':
                index += 2
            elif source[index] == '`':
                return index + 1
            elif source.startswith('${', index):
                index = code(index + 2, True)
            else:
                index += 1
        raise ValueError('Unterminated JavaScript template')

    def regexp(index):
        index += 1
        character_class = False
        while index < size:
            character = source[index]
            if character == '\\':
                index += 2
            elif character in '\r\n':
                raise ValueError('Unterminated JavaScript regular expression')
            elif character == '[':
                character_class = True
                index += 1
            elif character == ']':
                character_class = False
                index += 1
            elif character == '/' and not character_class:
                index += 1
                while index < size and source[index].isascii() and source[index].isalpha():
                    index += 1
                return index
            else:
                index += 1
        raise ValueError('Unterminated JavaScript regular expression')

    def code(index, expression=False):
        braces = 0
        can_regexp = True
        while index < size:
            character = source[index]
            if source.startswith('//', index):
                end = source.find('\n', index + 2)
                index = size if end < 0 else end + 1
            elif source.startswith('/*', index):
                end = source.find('*/', index + 2)
                if end < 0:
                    raise ValueError('Unterminated JavaScript comment')
                index = end + 2
            elif character in ('"', "'"):
                index = quoted(index, character)
                can_regexp = False
            elif character == '`':
                index = template(index)
                can_regexp = False
            elif character == '/' and can_regexp:
                index = regexp(index)
                can_regexp = False
            elif source.startswith(('++', '--'), index):
                if all_tokens:
                    found.append((index, source[index:index + 2]))
                # A prefix retains expression-start context; a postfix retains
                # operand context, so a subsequent division cannot hide code.
                index += 2
            elif character == '{':
                if all_tokens:
                    found.append((index, character))
                braces += 1
                index += 1
                can_regexp = True
            elif character == '}':
                if expression and braces == 0:
                    return index + 1
                if all_tokens:
                    found.append((index, character))
                braces -= 1
                index += 1
                can_regexp = False
            elif character.isascii() and (character.isalpha() or character in '_$'):
                match = re.match(IDENTIFIER, source[index:])
                word = match.group(0)
                if word in ('import', 'export') and (expression or braces != 0):
                    raise ValueError('Nested child module syntax is unsupported')
                if all_tokens or word in ('import', 'export'):
                    found.append((index, word))
                index += len(word)
                can_regexp = word in ('return', 'throw', 'case', 'delete', 'void', 'typeof', 'new', 'in', 'of', 'yield', 'await')
            else:
                if all_tokens and not character.isspace():
                    found.append((index, character))
                if not character.isspace():
                    can_regexp = character not in ')]' and not character.isdigit() and character != '.'
                index += 1
        if expression:
            raise ValueError('Unterminated JavaScript template expression')
        return index

    code(0)
    return found


def _single_binding(source, offset):
    depth = 0
    for _, token in _keywords(source[offset:], all_tokens=True):
        if token in ('(', '[', '{'):
            depth += 1
        elif token in (')', ']', '}'):
            depth -= 1
        elif depth == 0 and token == ',':
            raise ValueError('Unsupported multiple child export bindings')
        elif depth == 0 and token == ';':
            return
    raise ValueError('Child constant export requires a semicolon')


def _module(name, source, graph, exports):
    # The lexical scanner is deliberately smaller than JavaScript's grammar.
    # Conservatively reject dynamic-import spellings even in comments/data, so
    # slash ambiguity or an unfamiliar identifier can never admit such an edge.
    if DYNAMIC_IMPORT.search(source):
        raise ValueError('Unexpected or dynamic child import: ' + name)
    replacements = []
    actual_dependencies = []
    actual_exports = []
    for offset, kind in _keywords(source):
        if kind == 'import':
            match = IMPORT.match(source, offset)
            if not match:
                raise ValueError('Unexpected or dynamic child import: ' + name)
            dependency = match[3][2:]
            if dependency not in graph[name] or dependency in actual_dependencies:
                raise ValueError('Unexpected child dependency: ' + name + ' -> ' + dependency)
            bindings = []
            for binding in match[1].split(','):
                fields = binding.strip().split()
                if len(fields) == 1 and re.fullmatch(IDENTIFIER, fields[0]):
                    original = local = fields[0]
                elif len(fields) == 3 and fields[1] == 'as' and all(re.fullmatch(IDENTIFIER, field) for field in (fields[0], fields[2])):
                    original, local = fields[0], fields[2]
                else:
                    raise ValueError('Unexpected child import binding: ' + name)
                if original not in exports[dependency]:
                    raise ValueError('Unknown child export: ' + dependency + ' -> ' + original)
                bindings.append(original if local == original else original + ':' + local)
            if not bindings:
                raise ValueError('Empty child import: ' + name)
            actual_dependencies.append(dependency)
            replacements.append((offset, match.end(), 'const {' + ','.join(bindings) + '}=__modules[' + json.dumps(dependency) + '];'))
        else:
            match = EXPORT.match(source, offset)
            if not match or match[1] not in exports[name] or match[1] in actual_exports:
                raise ValueError('Unexpected child export or reexport: ' + name)
            if re.match(r'export\s+(?:const|let)\b', match[0]):
                _single_binding(source, match.end())
            actual_exports.append(match[1])
            replacements.append((offset, offset + len('export'), ''))
    if set(actual_dependencies) != set(graph[name]):
        raise ValueError('Child dependency inventory differs: ' + name)
    if set(actual_exports) != set(exports[name]):
        raise ValueError('Child export inventory differs: ' + name)
    for start, end, replacement in reversed(replacements):
        source = source[:start] + replacement + source[end:]
    return source


def assemble(blobs, graph=None, exports=None):
    """Return exact canonical data for the fixed, reviewed module closure."""
    graph = CHILD_GRAPH if graph is None else graph
    exports = CHILD_EXPORTS if exports is None else exports
    if set(graph) != set(exports) or set(blobs) != set(graph) | {'style.css'}:
        raise ValueError('Child bundle inventory differs')
    if any(name not in graph for dependencies in graph.values() for name in dependencies):
        raise ValueError('Unknown child dependency')
    state, ordered = {}, []

    def visit(name):
        if state.get(name) == 'active':
            raise ValueError('Cyclic child module graph')
        if state.get(name) == 'done':
            return
        state[name] = 'active'
        for dependency in graph[name]:
            visit(dependency)
        state[name] = 'done'
        ordered.append(name)

    for name in graph:
        visit(name)
    chunks = ['"use strict";\n(() => {\nconst __modules=Object.create(null);\n']
    for name in ordered:
        # HTML normalizes CR/CRLF in script text before applying a CSP hash.
        # Canonical LF script bytes keep the same policy on Windows checkouts.
        source = blobs[name].decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        if any(terminator in source.lower() for terminator in ('</script', '<!--', '-->')) or '\x00' in source:
            raise ValueError('Unsafe child script terminator: ' + name)
        source = _module(name, source, graph, exports)
        chunks.append('__modules[' + json.dumps(name) + ']=(() => {\n' + source + '\nreturn Object.freeze({' + ','.join(exports[name]) + '});\n})();\n')
    chunks.append('})();\n')
    script = ''.join(chunks)
    style = blobs['style.css'].decode('utf-8')
    if '</style' in style.lower() or '</script' in style.lower() or '\x00' in style:
        raise ValueError('Unsafe child style terminator')
    return {'CHILD_SCRIPT': script, 'CHILD_SCRIPT_SHA256': base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii'),
            'CHILD_CSP': child_csp(script), 'CHILD_SANDBOX': CHILD_SANDBOX,
            'CHILD_PROTOCOL': CHILD_PROTOCOL, 'CHILD_STYLE': style,
            'CHILD_INPUTS': {name: digest(data) for name, data in sorted(blobs.items())}}


def module_bytes(metadata):
    return ('// Generated renderer data; never evaluate this script in the parent.\n' +
            ''.join('export const ' + name + '=' + json.dumps(value, ensure_ascii=True, separators=(',', ':')) + ';\n'
                    for name, value in metadata.items())).encode('utf-8')


def parse_module(data):
    """Read only canonical pure-data output and verify its exact script policy."""
    names = ('CHILD_SCRIPT', 'CHILD_SCRIPT_SHA256', 'CHILD_CSP', 'CHILD_SANDBOX',
             'CHILD_PROTOCOL', 'CHILD_STYLE', 'CHILD_INPUTS')
    lines = data.decode('utf-8').splitlines()
    if len(lines) != len(names) + 1 or lines[0] != '// Generated renderer data; never evaluate this script in the parent.':
        raise ValueError('Invalid generated child data module')
    metadata = {}
    for name, line in zip(names, lines[1:]):
        prefix = 'export const ' + name + '='
        if not line.startswith(prefix) or not line.endswith(';'):
            raise ValueError('Invalid generated child data export')
        metadata[name] = json.loads(line[len(prefix):-1])
    if data != module_bytes(metadata) or any(not isinstance(metadata[name], str) for name in names[:-1]):
        raise ValueError('Noncanonical generated child data module')
    script = metadata['CHILD_SCRIPT']
    if (any(terminator in script.lower() for terminator in ('</script', '<!--', '-->')) or '\x00' in script or
            '</style' in metadata['CHILD_STYLE'].lower() or '</script' in metadata['CHILD_STYLE'].lower() or '\x00' in metadata['CHILD_STYLE']):
        raise ValueError('Unsafe generated child data terminator')
    if (metadata['CHILD_SCRIPT_SHA256'] != base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii') or
            metadata['CHILD_CSP'] != child_csp(script) or metadata['CHILD_SANDBOX'] != CHILD_SANDBOX or
            metadata['CHILD_PROTOCOL'] != CHILD_PROTOCOL):
        raise ValueError('Generated child script policy mismatch')
    inputs = metadata['CHILD_INPUTS']
    if (not isinstance(inputs, dict) or set(inputs) != set(CHILD_MODULES + ('style.css',)) or
            any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in inputs.values())):
        raise ValueError('Generated child input metadata differs')
    if inputs['style.css'] != digest(metadata['CHILD_STYLE'].encode('utf-8')):
        raise ValueError('Generated child style metadata differs')
    return metadata


def generate(assets, output):
    root = Path(assets)
    blobs = {}
    for name in CHILD_MODULES + ('style.css',):
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Expected ordinary bounded child input: ' + str(path))
        blobs[name] = path.read_bytes()
    data = module_bytes(assemble(blobs))
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Child bundle output must be ordinary')
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists() or output.read_bytes() != data:
        output.write_bytes(data)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    arguments = parser.parse_args(argv)
    generate(arguments.assets, arguments.output)


if __name__ == '__main__':
    main()
