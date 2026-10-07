"""Read a build graph from supplied text without configuring or executing it.

This is a lexical map: CMake variables, conditionals, functions, includes and
generator expressions remain visible. It never evaluates the project's scripts.
"""

import json
import re

try:
    import tomllib
except ImportError:  # Python before 3.11 still supports the CMake/JSON map.
    tomllib = None


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_BRACKET = re.compile(r"\[(=*)\[")
_LIBRARY_FLAGS = {"STATIC", "SHARED", "MODULE", "OBJECT", "INTERFACE", "UNKNOWN",
                  "IMPORTED", "ALIAS", "GLOBAL", "EXCLUDE_FROM_ALL"}
_EXECUTABLE_FLAGS = {"WIN32", "MACOSX_BUNDLE", "EXCLUDE_FROM_ALL", "IMPORTED",
                     "GLOBAL", "ALIAS"}
_VISIBILITY = {"PRIVATE", "PUBLIC", "INTERFACE"}
_BLOCKS = {"if", "foreach", "while", "function", "macro", "block"}
_END_BLOCKS = {"endif": "if", "endforeach": "foreach", "endwhile": "while",
               "endfunction": "function", "endmacro": "macro", "endblock": "block"}


def _bracket_end(text, index):
    """Return (end, content) for a bracket argument, or None for ordinary text."""
    match = _BRACKET.match(text, index)
    if not match:
        return None
    closing = "]" + match.group(1) + "]"
    stop = text.find(closing, match.end())
    if stop < 0:
        raise ValueError("unterminated bracket argument/comment")
    return stop + len(closing), text[match.end():stop]


def _skip_comment(text, index):
    bracket = _bracket_end(text, index + 1)
    if bracket:
        return bracket[0]
    stop = text.find("\n", index)
    return len(text) if stop < 0 else stop + 1


def _skip_space(text, index):
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text[index] == "#":
            index = _skip_comment(text, index)
        else:
            break
    return index


def _command_end(text, opening):
    """Match parentheses while respecting quoted/bracket arguments and comments."""
    depth, index = 1, opening + 1
    quoted = False
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if quoted:
            if char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
        elif char == "#":
            index = _skip_comment(text, index)
            continue
        elif char == "[":
            bracket = _bracket_end(text, index)
            if bracket:
                index = bracket[0]
                continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unterminated command or quoted argument")


def _arguments(body):
    """Tokenize arguments, retaining escapes and symbolic CMake expressions.

    Quoting delimiters are omitted for display. Escapes are deliberately retained;
    list expansion, escape interpretation and variable expansion are not performed.
    """
    result, index = [], 0
    while index < len(body):
        index = _skip_space(body, index)
        if index >= len(body):
            break
        bracket = _bracket_end(body, index) if body[index] == "[" else None
        if bracket:
            index, content = bracket
            result.append(content)
            continue
        if body[index] in "()":
            result.append(body[index])
            index += 1
            continue
        token = []
        quoted = False
        while index < len(body):
            char = body[index]
            if char == "\\" and index + 1 < len(body):
                token.append(body[index:index + 2])
                index += 2
                continue
            if char == '"':
                quoted = not quoted
                index += 1
                continue
            if not quoted and (char.isspace() or char in "()#"):
                break
            token.append(char)
            index += 1
        result.append("".join(token))
    return result


def _read_commands(source, path):
    commands, warnings, stack = [], [], []
    index = 0
    while index < len(source):
        try:
            index = _skip_space(source, index)
            if index >= len(source):
                break
            match = _IDENTIFIER.match(source, index)
            if not match:
                index += 1
                continue
            opening = _skip_space(source, match.end())
            if opening >= len(source) or source[opening] != "(":
                index = match.end()
                continue
            stop = _command_end(source, opening)
            name = match.group(0).lower()
            args = _arguments(source[opening + 1:stop])
            line = source.count("\n", 0, index) + 1
            if name in _END_BLOCKS:
                expected = _END_BLOCKS[name]
                if stack and stack[-1]["kind"] == expected:
                    stack.pop()
                else:
                    warnings.append(f"{path}:{line}: unmatched {name}; context may be incomplete")
            elif name in ("else", "elseif"):
                if stack and stack[-1]["kind"] == "if":
                    stack[-1]["branch"] = stack[-1]["expression"] + " -> " + name + "(" + " ".join(args) + ")"
                else:
                    warnings.append(f"{path}:{line}: unmatched {name}; context may be incomplete")
            context = [item.get("branch", item["expression"]) for item in stack]
            command = {"command": name, "args": args, "line": line, "path": path,
                       "raw": source[index:stop + 1], "end_line": source.count("\n", 0, stop) + 1}
            if context:
                command["context"] = context
            commands.append(command)
            if name in _BLOCKS:
                stack.append({"kind": name, "expression": name + "(" + " ".join(args) + ")"})
            index = stop + 1
        except ValueError as error:
            line = source.count("\n", 0, index) + 1
            warnings.append(f"{path}:{line}: {error}; remaining commands were not parsed")
            break
    if stack:
        warnings.append(f"{path}: unclosed CMake blocks; context may be incomplete")
    return commands, warnings


def _symbolic(value):
    return bool(re.search(r"\$\{|\$ENV\{|\$CACHE\{|\$<", value))


def analyze_build(files):
    """Return a serializable, unevaluated build map from file records.

    Each input record needs only ``path`` and ``text``; files are never opened here.
    Targets retain their declaration/conditional context, and additional source or
    link statements retain their own context in ``source_statements`` and
    ``link_statements``. A union of declarations is not an active configuration.
    """
    output = {"commands": [], "targets": [], "options": [], "presets": {},
              "cargo": {}, "toolchain": [], "declarations": [], "warnings": []}
    for record in files:
        path = str(record.get("path", "")).replace("\\", "/")
        source = record.get("text", "")
        if not isinstance(source, str):
            continue
        basename = path.rsplit("/", 1)[-1]
        if basename in ("CMakePresets.json", "CMakeUserPresets.json"):
            try:
                output["presets"][path] = json.loads(source)
            except (ValueError, TypeError) as error:
                output["warnings"].append(f"{path}: invalid preset JSON: {error}")
        elif basename == "Cargo.toml":
            if tomllib is None:
                output["warnings"].append(f"{path}: Cargo TOML needs Python 3.11 tomllib; metadata omitted")
            else:
                try:
                    output["cargo"][path] = tomllib.loads(source)
                except ValueError as error:
                    output["warnings"].append(f"{path}: invalid Cargo TOML: {error}")
        if (basename != "CMakeLists.txt" and not path.lower().endswith((".cmake", ".cmake.in"))
                and str(record.get("language", "")).lower() != "cmake"):
            continue
        commands, warnings = _read_commands(source, path)
        output["commands"].extend(commands)
        output["warnings"].extend(warnings)

    declarations = []
    for command in output["commands"]:
        name, args = command["command"], command["args"]
        evidence = {key: command[key] for key in ("path", "line", "context") if key in command}
        if name in ("function", "macro") and args:
            output["declarations"].append({"name": args[0], "kind": name,
                                           "parameters": args[1:], **evidence})
        if name == "option" and args:
            output["options"].append({"name": args[0], "description": args[1] if len(args) > 1 else "",
                                      "default": args[2] if len(args) > 2 else "OFF", **evidence})
        elif name == "set" and args:
            if "CACHE" in args:
                cache = args.index("CACHE")
                if cache >= 1:
                    output["options"].append({"name": args[0], "default": ";".join(args[1:cache]),
                                              "description": args[cache + 2] if len(args) > cache + 2 else "",
                                              "cache_type": args[cache + 1] if len(args) > cache + 1 else "",
                                              **evidence})
            if args[0].startswith("CMAKE_") or "TOOLCHAIN" in args[0] or "COMPILER" in args[0]:
                output["toolchain"].append({"name": args[0], "values": args[1:], **evidence})
        if name in ("add_library", "add_executable", "foundation_gui_executable") and args:
            flags = _LIBRARY_FLAGS if name == "add_library" else _EXECUTABLE_FLAGS
            if name == "foundation_gui_executable":
                kind, sources = "executable (foundation_gui_executable helper)", args[1:]
            elif name == "add_library":
                library_type = next((arg.lower() for arg in args[1:] if arg in
                                     {"STATIC", "SHARED", "MODULE", "OBJECT", "INTERFACE", "UNKNOWN"}), "unspecified")
                kind = library_type + " library"
                sources = [arg for arg in args[1:] if arg not in flags]
            else:
                kind, sources = "executable", [arg for arg in args[1:] if arg not in flags]
            target = {"name": args[0], "kind": kind, "sources": sources, "links": [], **evidence}
            if "IMPORTED" in args[1:]:
                target["kind"] = "imported " + kind
                target["sources"] = []
            if "ALIAS" in args[1:]:
                position = args.index("ALIAS")
                target["kind"] = "alias"
                target["sources"] = []
                target["alias_of"] = args[position + 1] if len(args) > position + 1 else ""
                target["links"] = [target["alias_of"]] if target["alias_of"] else []
            target["symbolic"] = any(_symbolic(arg) for arg in [target["name"], *target["sources"]])
            declarations.append(target)
    output["targets"] = declarations
    by_name = {}
    for target in declarations:
        by_name.setdefault(target["name"], []).append(target)
    for command in output["commands"]:
        if command["command"] not in ("target_sources", "target_link_libraries") or not command["args"]:
            continue
        args = command["args"]
        field = "sources" if command["command"] == "target_sources" else "links"
        qualifiers = _VISIBILITY | {"BEFORE"}
        if field == "links":
            qualifiers |= {"LINK_PUBLIC", "LINK_PRIVATE", "LINK_INTERFACE_LIBRARIES", "debug", "optimized", "general"}
        values = [arg for arg in args[1:] if arg not in qualifiers]
        matches = by_name.get(args[0], [])
        for target in matches:
            for value in values:
                if value not in target[field]:
                    target[field].append(value)
            target.setdefault("source_statements" if field == "sources" else "link_statements", []).append(command)
            target["symbolic"] = target["symbolic"] or any(_symbolic(value) for value in values)
        if not matches:
            output["warnings"].append(f"{command['path']}:{command['line']}: {command['command']} references "
                                      f"{args[0]}, whose declaration is absent or supplied elsewhere")
    if output["commands"]:
        output["warnings"].append("CMake is mapped lexically, never executed: targets show a union of declarations, "
                                  "not one selected configuration. Conditions and helper/loop contexts remain explicit.")
        if any(any(_symbolic(arg) for arg in command["args"]) for command in output["commands"]):
            output["warnings"].append("Variables, environment/cache references and generator expressions are unresolved; "
                                      "symbolic source and link entries are preserved verbatim.")
        if any(command["command"] in {"include", "add_subdirectory", "file", "execute_process", "find_package"}
               for command in output["commands"]):
            output["warnings"].append("Includes, subdirectories, globbing, package discovery, generated files, retained-input "
                                      "restoration and external commands are not evaluated or invoked.")
        if any(command["command"] in {"if", "foreach", "while", "function", "macro"}
               for command in output["commands"]):
            output["warnings"].append("Conditional providers/backends, loops and function bodies may describe mutually exclusive "
                                      "or template targets. Source and link statements retain their separate conditions.")
    return output
