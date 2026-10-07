"""Read-only, syntactic source indexing for the standalone documentation tool.

The flow output is a structural outline of source statements, not an exact
control-flow graph. No target code, configuration, or build command is run.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from typing import Any, Iterable


_GRAMMARS = {
    "cpp": "tree_sitter_cpp",
    "rust": "tree_sitter_rust",
    "javascript": "tree_sitter_javascript",
    "python": "tree_sitter_python",
    "bash": "tree_sitter_bash",
}
_PARSERS: dict[str, Any] = {}
_DEFINITIONS = {
    "cpp": {
        "function_definition": "function", "lambda_expression": "lambda",
        "class_specifier": "class", "struct_specifier": "struct",
        "union_specifier": "union", "enum_specifier": "enum",
        "namespace_definition": "namespace",
    },
    "rust": {
        "function_item": "function", "closure_expression": "lambda",
        "struct_item": "struct", "enum_item": "enum", "trait_item": "trait",
        "impl_item": "impl", "mod_item": "namespace",
    },
    "python": {
        "function_definition": "function", "class_definition": "class",
        "lambda": "lambda",
    },
    "javascript": {
        "function_declaration": "function", "generator_function_declaration": "function",
        "function_expression": "function", "generator_function": "function",
        "arrow_function": "lambda", "method_definition": "method",
        "class_declaration": "class", "class": "class",
    },
    "bash": {"function_definition": "function"},
}
_CONTAINERS = {
    "translation_unit", "program", "module", "source_file", "block", "compound_statement",
    "statement_block", "declaration_list", "class_body", "field_declaration_list",
    "switch_body", "match_block", "body", "list", "do_group",
}
_BRANCHES = {"if_statement", "if_expression", "conditional_expression", "ternary_expression"}
_LOOPS = {
    "for_statement", "for_in_statement", "for_expression", "for_range_loop",
    "while_statement", "while_expression", "do_statement", "loop_expression",
    "for_each_statement", "until_statement", "c_style_for_statement",
}
_EXITS = {
    "return_statement": "return", "return_expression": "return",
    "throw_statement": "throw", "throw_expression": "throw", "raise_statement": "throw",
    "break_statement": "break", "break_expression": "break",
    "continue_statement": "continue", "continue_expression": "continue",
    "yield": "yield", "yield_expression": "yield", "yield_statement": "yield",
}
_CONTROL_TYPES = _BRANCHES | _LOOPS | set(_EXITS) | {
    "switch_statement", "switch_expression", "match_expression", "try_statement",
    "case_statement", "case_item", "case_clause", "switch_case", "switch_default", "match_arm",
    "elif_clause", "else_clause", "catch_clause", "except_clause", "finally_clause",
    "with_statement", "async_statement", "labeled_statement",
}
_NON_EXECUTABLE = {
    "comment", "line_comment", "block_comment", "attribute_item", "inner_attribute_item",
    "preproc_include", "preproc_def", "preproc_function_def", "preproc_call",
    "import_statement", "import_from_statement", "use_declaration", "extern_crate_declaration",
}


def _parser(language: str) -> Any:
    if language not in _PARSERS:
        tree_sitter = importlib.import_module("tree_sitter")
        grammar = importlib.import_module(_GRAMMARS[language])
        lang = tree_sitter.Language(grammar.language())
        try:
            parser = tree_sitter.Parser(lang)
        except TypeError:  # Compatibility with earlier tree-sitter bindings.
            parser = tree_sitter.Parser()
            parser.language = lang
        _PARSERS[language] = parser
    return _PARSERS[language]


def _id(path: str, name: str, line: int, kind: str, offset: int = 0) -> str:
    # Multiple anonymous callbacks (or macro-recovered definitions) can start on
    # the same line; byte offset keeps their stable anchors distinct.
    return hashlib.sha256(f"{path}\0{name}\0{line}\0{kind}\0{offset}".encode()).hexdigest()[:20]


def _compact(value: str, limit: int | None = 180) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if limit is None or len(value) <= limit:
        return value
    return value[:limit - 1].rstrip() + "…"


class _Scanner:
    def __init__(self, path: str, text: str, language: str):
        self.path, self.text, self.language = path, text, language
        self.data = text.encode("utf-8")
        self.definitions = _DEFINITIONS[language]
        self.separator = "::" if language in {"cpp", "rust"} else "."
        self.symbols: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []
        self.warnings: list[str] = []

    def source(self, node: Any | None) -> str:
        return "" if node is None else self.data[node.start_byte:node.end_byte].decode("utf-8", "replace")

    @staticmethod
    def field(node: Any, *names: str) -> Any | None:
        for name in names:
            child = node.child_by_field_name(name)
            if child is not None:
                return child
        return None

    @staticmethod
    def line(node: Any) -> int:
        return node.start_point[0] + 1

    def walk(self, node: Any, exclude_definitions: bool = False) -> Iterable[Any]:
        yield node
        for child in node.named_children:
            if exclude_definitions and child.type in self.definitions:
                continue
            yield from self.walk(child, exclude_definitions)

    def definition_name(self, node: Any, kind: str) -> str:
        name = self.field(node, "name")
        if name is not None:
            return self.source(name).strip()
        if kind == "impl":
            return self.source(self.field(node, "type")).strip() or f"anonymous impl @{self.line(node)}"
        if self.language == "cpp" and kind == "function":
            declarator = self.field(node, "declarator")
            while declarator is not None:
                nested = self.field(declarator, "declarator")
                if nested is None and declarator.type in {"reference_declarator", "pointer_declarator", "parenthesized_declarator", "attributed_declarator"}:
                    nested = next((child for child in declarator.named_children if child.type not in {"type_qualifier", "attribute_declaration"}), None)
                if nested is None:
                    break
                declarator = nested
            if declarator is not None:
                return self.source(declarator).strip()
        # Give anonymous functions their nearby binding where the syntax supplies one.
        parent = node.parent
        if parent is not None and parent.type in {
            "variable_declarator", "init_declarator", "assignment", "assignment_expression",
            "let_declaration", "pair", "property_assignment", "named_expression",
        }:
            binding = self.field(parent, "name", "declarator", "left", "pattern", "key")
            if binding is not None:
                return self.source(binding).strip()
        return f"anonymous {kind} @{self.line(node)}"

    def body(self, node: Any) -> Any | None:
        body = self.field(node, "body")
        if body is not None:
            return body
        for child in node.named_children:
            if child.type in {"compound_statement", "block", "statement_block", "class_body", "declaration_list", "field_declaration_list", "do_group"}:
                return child
        if node.type in {"lambda", "lambda_expression", "closure_expression", "arrow_function"}:
            return self.field(node, "value")
        return None

    def signature(self, node: Any) -> str:
        body = self.body(node)
        end = body.start_byte if body is not None else node.end_byte
        value = self.data[node.start_byte:end].decode("utf-8", "replace").strip()
        # Expression-bodied arrows/lambdas should show their declaration, not just a blank header.
        if not value:
            value = self.source(node)
        return _compact(value, None)

    def bases(self, node: Any) -> list[str]:
        out: list[str] = []
        bases = self.field(node, "superclasses", "superclass", "interfaces")
        if bases is not None:
            out = [self.source(child).strip() for child in bases.named_children]
            if not out:
                out = [self.source(bases).strip()]
        for child in node.named_children:
            if child.type == "base_class_clause":
                out.extend(self.source(base).strip() for base in child.named_children if base.type not in {"access_specifier", "virtual"})
            elif child.type == "class_heritage":
                out.extend(self.source(base).strip() for base in child.named_children)
            elif child.type == "trait_bounds":
                out.extend(self.source(base).strip() for base in child.named_children)
        trait = self.field(node, "trait") if node.type == "impl_item" else None
        if trait is not None:
            out.append(self.source(trait).strip())
        return list(dict.fromkeys(value for value in out if value))

    def call(self, node: Any) -> dict[str, Any] | None:
        if node.type in {"call_expression", "call", "new_expression", "method_call_expression"}:
            target = self.field(node, "function", "constructor", "method")
            if target is not None:
                name = _compact(self.source(target), None)
                return {"name": name, "line": self.line(node), "kind": "constructor" if node.type == "new_expression" else "call"}
        if self.language == "bash" and node.type == "command":
            target = self.field(node, "name")
            if target is None:
                target = next((child for child in node.named_children if child.type == "command_name"), None)
            if target is not None:
                return {"name": self.source(target).strip(), "line": self.line(node), "kind": "command"}
        # Macro invocations are explicitly distinguished from normal calls.
        if self.language == "rust" and node.type == "macro_invocation":
            target = self.field(node, "macro")
            if target is not None:
                return {"name": self.source(target).strip() + "!", "line": self.line(node), "kind": "macro"}
        return None

    def calls(self, node: Any | None) -> list[dict[str, Any]]:
        if node is None:
            return []
        calls = []
        for child in self.walk(node, exclude_definitions=True):
            result = self.call(child)
            if result:
                calls.append(result)
        return calls

    def event(self, kind: str, label: str, node: Any, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "kind": kind, "label": _compact(label), "line": self.line(node),
            "end_line": node.end_point[0] + 1, "children": children or [],
            "calls": self.calls(node),
        }

    def condition(self, node: Any) -> str:
        condition = self.field(node, "condition", "value", "subject")
        if condition is not None:
            return self.source(condition)
        body = self.body(node)
        if body is not None:
            return self.data[node.start_byte:body.start_byte].decode("utf-8", "replace")
        return self.source(node).split("\n", 1)[0]

    def header(self, node: Any) -> str:
        """Preserve loop initialization/update, not just its condition."""
        body = self.body(node)
        if body is not None:
            return self.data[node.start_byte:body.start_byte].decode("utf-8", "replace").strip()
        return self.condition(node)

    def flow(self, node: Any | None, allow_definition: bool = False) -> list[dict[str, Any]]:
        if node is None or node.type in _NON_EXECUTABLE:
            return []
        typ = node.type
        if typ in self.definitions and not allow_definition:
            return []
        if typ in _CONTAINERS:
            out = []
            for child in node.named_children:
                out.extend(self.flow(child))
            return out
        if typ in _BRANCHES:
            consequence = self.field(node, "consequence", "body")
            alternative = self.field(node, "alternative")
            children = []
            if consequence is not None:
                children.append(self.event("then", "then", consequence, self.flow(consequence)))
            if alternative is not None:
                if alternative.type in {"elif_clause", "else_clause"}:
                    children.extend(self.flow(alternative))
                else:
                    children.append(self.event("else", "else", alternative, self.flow(alternative)))
            if self.language == "bash" and consequence is None:
                # Shell's then statements are direct children between the condition
                # and elif/else nodes, rather than a field named consequence.
                then_nodes = [child for child in node.named_children if child.type not in {"elif_clause", "else_clause"} and node.field_name_for_named_child(node.named_children.index(child)) != "condition"]
                if then_nodes:
                    then_flow = [event for child in then_nodes for event in self.flow(child)]
                    children.insert(0, self.event("then", "then", then_nodes[0], then_flow))
            # Python and shell grammars expose additional elif/else nodes rather than fields.
            used = {child.id for child in (consequence, alternative) if child is not None}
            for child in node.named_children:
                if child.id not in used and child.type in {"elif_clause", "else_clause"}:
                    children.extend(self.flow(child))
            return [self.event("branch", self.condition(node), node, children)]
        if typ in {"elif_clause", "else_clause"}:
            body = self.body(node)
            children = self.flow(body) if body is not None else [event for child in node.named_children for event in self.flow(child)]
            label = self.condition(node) if typ == "elif_clause" else "else"
            if self.language == "bash" and typ == "elif_clause":
                # There is no named body/condition field in this grammar. Tokens
                # supply an unambiguous boundary at the `then` keyword.
                then_token = next((child for child in node.children if child.type == "then"), None)
                if then_token is not None:
                    condition_nodes = [child for child in node.named_children if child.end_byte <= then_token.start_byte]
                    label = " ".join(self.source(child) for child in condition_nodes)
                    children = [event for child in node.named_children if child.start_byte >= then_token.end_byte for event in self.flow(child)]
            return [self.event("elif" if typ == "elif_clause" else "else", label, node, children)]
        if typ in _LOOPS:
            body = self.body(node)
            children = self.flow(body)
            for child in node.named_children:
                if child.type == "else_clause":
                    children.extend(self.flow(child))
            label = self.header(node)
            if typ == "do_statement":
                label = "do … while " + self.condition(node)
            return [self.event("loop", label, node, children)]
        if self.language == "bash" and typ == "case_statement":
            arms = [event for child in node.named_children if child.type == "case_item" for event in self.flow(child)]
            return [self.event("switch", self.condition(node), node, arms)]
        if typ in {"switch_statement", "switch_expression", "match_expression"}:
            body = self.body(node)
            if body is None:
                body = next((child for child in node.named_children if child.type in {"switch_body", "match_block"}), None)
            return [self.event("match" if typ == "match_expression" else "switch", self.condition(node), node, self.flow(body))]
        if typ in {"case_statement", "case_item", "case_clause", "switch_case", "switch_default", "match_arm"}:
            pattern = self.field(node, "pattern", "value")
            body = self.field(node, "body")
            if typ == "match_arm":
                label = self.source(pattern) if pattern is not None else self.source(node).split("=>", 1)[0]
                children = self.flow(self.field(node, "value"))
            else:
                label = self.source(pattern) if pattern is not None else self.source(node).split(":", 1)[0]
                children = self.flow(body) if body is not None else [event for child in node.named_children if child != pattern for event in self.flow(child)]
            return [self.event("case", label, node, children)]
        if typ == "try_statement":
            children = []
            body = self.body(node)
            if body is not None:
                children.append(self.event("try_body", "try body", body, self.flow(body)))
            for child in node.named_children:
                if child.type in {"catch_clause", "except_clause", "finally_clause", "else_clause"}:
                    children.extend(self.flow(child))
            return [self.event("try", "try", node, children)]
        if typ in {"catch_clause", "except_clause", "finally_clause"}:
            body = self.body(node)
            label = self.data[node.start_byte:body.start_byte].decode("utf-8", "replace") if body is not None else typ.replace("_clause", "")
            children = self.flow(body) if body is not None else [event for child in node.named_children for event in self.flow(child)]
            return [self.event(typ.replace("_clause", ""), label, node, children)]
        if typ in _EXITS:
            return [self.event(_EXITS[typ], self.source(node), node, self.nested_control(node))]
        if typ in {"with_statement", "async_statement", "labeled_statement"}:
            body = self.body(node)
            return [self.event("scope", self.condition(node), node, self.flow(body))]
        if typ.startswith("preproc_"):
            # Retain conditionally compiled structure without interpreting defines.
            children = [event for child in node.named_children for event in self.flow(child)]
            return [self.event("preprocessor", self.source(node).split("\n", 1)[0], node, children)]
        if typ == "decorated_definition" or typ == "export_statement":
            out = []
            for child in node.named_children:
                if child.type not in self.definitions and child.type != "decorator":
                    out.extend(self.flow(child))
            return out
        # A single source statement is one outline item; control expressions inside
        # it (Rust match/if, JS ternary, etc.) retain their actual AST nesting.
        return [self.event("statement", self.source(node), node, self.nested_control(node))]

    def nested_control(self, node: Any) -> list[dict[str, Any]]:
        out = []
        for child in node.named_children:
            if child.type in self.definitions:
                continue
            if child.type in _CONTROL_TYPES:
                out.extend(self.flow(child))
            else:
                out.extend(self.nested_control(child))
        return out

    def entry_reason(self, node: Any, name: str, signature: str) -> str | None:
        leaf = re.split(r"::|\.", name)[-1]
        if self.language in {"cpp", "rust"} and leaf in {"main", "wmain", "WinMain", "wWinMain", "DllMain"}:
            return "Named platform/program entry point candidate."
        if self.language == "cpp":
            if "EMSCRIPTEN_KEEPALIVE" in signature:
                return "Declared with EMSCRIPTEN_KEEPALIVE; Wasm export entry candidate."
            ancestor = node.parent
            while ancestor is not None:
                if ancestor.type == "linkage_specification" and re.match(r'\s*extern\s*"C"', self.source(ancestor)):
                    return "Declared with C linkage; foreign-call/export entry candidate."
                if ancestor.type in self.definitions:
                    break
                ancestor = ancestor.parent
        if self.language == "rust":
            preceding = self.data[max(0, node.start_byte - 600):node.start_byte].decode("utf-8", "replace")
            if re.search(r"\bextern\b", signature):
                return "Declared extern function; foreign-call entry candidate."
            if re.search(r"#\[\s*(?:unsafe\s*\(\s*)?(?:no_mangle|export_name|wasm_bindgen)", preceding):
                return "Nearby export/wasm attribute; exported entry candidate."
        if self.language == "javascript":
            parent = node.parent
            while parent is not None and parent.start_byte >= max(0, node.start_byte - 500):
                if parent.type == "export_statement":
                    return "Exported declaration; module API entry candidate."
                if parent.type == "call_expression":
                    target = self.source(self.field(parent, "function"))
                    if re.search(r"(?:addEventListener|\.on|\.once|setTimeout|setInterval|requestAnimationFrame)$", target):
                        return f"Callback passed to {target}; event/timer entry candidate."
                    break
                if parent.type in self.definitions:
                    break
                parent = parent.parent
        return None

    def discover(self, node: Any, owner: str | None = None, owner_kind: str | None = None) -> None:
        current_owner, current_kind = owner, owner_kind
        kind = self.definitions.get(node.type)
        if kind is not None:
            name = self.definition_name(node, kind)
            if kind == "function" and owner_kind in {"class", "struct", "union", "impl", "trait"}:
                kind = "method"
            qualified = name if owner is None or name.startswith(owner + self.separator) else owner + self.separator + name
            signature = self.signature(node)
            body = self.body(node)
            flow = self.flow(body)
            for child in node.named_children:
                if child.type == "field_initializer_list":
                    flow.insert(0, self.event("initialization", self.source(child), child))
            # C++ qualified out-of-class methods expose their owner in the name.
            inferred_owner = owner
            if self.language == "cpp" and "::" in name:
                inferred_owner = qualified.rsplit("::", 1)[0]
                if kind == "function":
                    kind = "method"
            symbol = {
                "id": _id(self.path, qualified, self.line(node), kind, node.start_byte),
                "name": name, "qualified_name": qualified, "kind": kind,
                "line": self.line(node), "end_line": node.end_point[0] + 1,
                "signature": signature, "owner": inferred_owner, "bases": self.bases(node),
                "calls": self.calls(node), "flow": flow,
                "start_byte": node.start_byte, "end_byte": node.end_byte,
                "entry_reason": self.entry_reason(node, name, signature),
            }
            symbol["entry"] = bool(symbol["entry_reason"])
            self.symbols.append(symbol)
            current_owner, current_kind = qualified, kind
        for child in node.named_children:
            self.discover(child, current_owner, current_kind)

    def collect_import(self, node: Any) -> None:
        typ = node.type
        if typ == "preproc_include":
            target = self.field(node, "path")
            self.imports.append({"name": self.source(target).strip() or _compact(self.source(node), None), "line": self.line(node), "kind": "include"})
        elif typ in {"import_statement", "import_from_statement", "use_declaration", "extern_crate_declaration"}:
            target = self.field(node, "source", "argument", "module_name", "name")
            self.imports.append({"name": self.source(target).strip() if target is not None else _compact(self.source(node), None), "line": self.line(node), "kind": "import", "statement": _compact(self.source(node), None)})
        elif self.language == "javascript" and typ == "export_statement":
            target = self.field(node, "source")
            if target is not None:
                self.imports.append({"name": self.source(target).strip(), "line": self.line(node), "kind": "reexport"})
        elif self.language == "bash" and typ == "command":
            result = self.call(node)
            if result and result["name"] in {"source", "."}:
                self.imports.append({"name": _compact(self.source(node), None), "line": self.line(node), "kind": "source"})

    def scan(self) -> dict[str, Any]:
        tree = _parser(self.language).parse(self.data)
        root = tree.root_node
        errors: list[str] = []
        for node in self.walk(root):
            if node.type == "ERROR" or node.is_missing:
                errors.append(f"line {self.line(node)} ({'missing ' if node.is_missing else ''}{node.type})")
            self.collect_import(node)
        if errors:
            self.warnings.append("Syntax parser recovered from errors: " + ", ".join(errors) + ". Recovered structure may be incomplete.")
        self.discover(root)
        flow = self.flow(root)
        calls = self.calls(root)
        if flow or calls or self.language in {"python", "javascript", "bash"}:
            entry_reason = None
            if self.language == "python" and re.search(r"\bif\s+__name__\s*==\s*['\"]__main__['\"]", self.text):
                entry_reason = "Contains Python __main__ guard."
            elif self.language in {"javascript", "bash"} and flow:
                entry_reason = "Top-level statements execute when this module/script is loaded."
            self.symbols.insert(0, {
                "id": _id(self.path, "<module>", 1, "module"), "name": "<module>",
                "qualified_name": "<module>", "kind": "module", "line": 1,
                "end_line": max(1, len(self.text.splitlines())), "signature": self.path,
                "owner": None, "bases": [], "calls": calls, "flow": flow,
                "entry": bool(entry_reason), "entry_reason": entry_reason,
            })
        return {"symbols": self.symbols, "warnings": self.warnings, "imports": self.imports}


def _cmake_scan(path: str, text: str) -> dict[str, Any]:
    """Outline CMake commands without evaluating variables or includes."""
    # Share the local build-map lexer so bracket comments, quoted arguments and
    # multiple commands on one line receive the same read-only interpretation.
    from build_map import _read_commands
    parsed, warnings = _read_commands(text, path)
    warnings = ["CMake is indexed as a lexical command outline; variables, generated files, and included scripts are not evaluated."] + warnings
    commands = [{"name": item["command"], "lower": item["command"],
                 "args": " ".join(item["args"]), "arguments": item["args"],
                 "raw": item.get("raw", item["command"] + "(" + " ".join(item["args"]) + ")"),
                 "line": item["line"], "end_line": item.get("end_line", item["line"]),
                 "offset": index} for index, item in enumerate(parsed)]
    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    module_flow: list[dict[str, Any]] = []
    module_calls: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = [{"kind": "module", "flow": module_flow, "calls": module_calls, "symbol": None}]
    for command in commands:
        name, line = command["lower"], command["line"]
        if name in {"include", "add_subdirectory", "find_package"}:
            imports.append({"name": _compact(command["args"], None), "line": line, "kind": name})
        if name in {"function", "macro"}:
            symbol_name = command["arguments"][0] if command["arguments"] else f"anonymous {name} @{line}"
            symbol = {"id": _id(path, symbol_name, line, name, command["offset"]), "name": symbol_name, "qualified_name": symbol_name,
                      "kind": "function" if name == "function" else "macro", "line": line, "end_line": command["end_line"],
                      "signature": _compact(command["raw"], None), "owner": None, "bases": [], "calls": [], "flow": [], "entry": False, "entry_reason": None}
            symbols.append(symbol)
            stack.append({"kind": name, "flow": symbol["flow"], "calls": symbol["calls"], "symbol": symbol})
            continue
        if name in {"endfunction", "endmacro", "endif", "endforeach", "endwhile", "endblock"}:
            expected = name[3:]
            if len(stack) > 1 and stack[-1]["kind"] == expected:
                current = stack.pop()
                if current["symbol"]:
                    current["symbol"]["end_line"] = command["end_line"]
                if current.get("parent_event"):
                    current["parent_event"]["end_line"] = command["end_line"]
            else:
                warnings.append(f"Unmatched {name} at line {line}; remaining outline follows lexical nesting.")
            continue
        event = {"kind": "statement", "label": _compact(command["raw"]), "line": line, "end_line": command["end_line"], "children": [], "calls": [{"name": command["name"], "line": line, "kind": "command"}]}
        # Calls belong to the nearest function/macro/module, including control bodies.
        for scope in reversed(stack):
            if scope["kind"] in {"module", "function", "macro"}:
                scope["calls"].extend(event["calls"])
                break
        if name in {"else", "elseif"}:
            if stack[-1]["kind"] == "if":
                branch = stack[-1]["parent_event"]
                event["kind"] = name
                branch["children"].append(event)
                stack[-1]["flow"] = event["children"]
            else:
                warnings.append(f"Unmatched {name} at line {line}.")
                stack[-1]["flow"].append(event)
            continue
        if name in {"if", "foreach", "while", "block"}:
            event["kind"] = "branch" if name == "if" else "loop" if name in {"foreach", "while"} else "scope"
            stack[-1]["flow"].append(event)
            stack.append({"kind": name, "flow": event["children"], "calls": [], "symbol": None, "parent_event": event})
        else:
            if name in {"return", "break", "continue"}:
                event["kind"] = name
            stack[-1]["flow"].append(event)
    for scope in stack[1:]:
        warnings.append(f"Unclosed CMake {scope['kind']} scope.")
    symbols.insert(0, {"id": _id(path, "<module>", 1, "module"), "name": "<module>", "qualified_name": "<module>", "kind": "module", "line": 1, "end_line": max(1, len(text.splitlines())), "signature": path, "owner": None, "bases": [], "calls": module_calls, "flow": module_flow, "entry": True, "entry_reason": "Top-level configuration commands are read when this CMake file is included."})
    return {"symbols": symbols, "warnings": warnings, "imports": imports}


def scan_source(path: str, text: str, language: str) -> dict[str, Any]:
    """Index definitions, call spellings, imports, and structural flow from text.

    Source locations are one-based. Names/calls are syntactic observations; symbol
    resolution, compiler preprocessing, dynamic dispatch, and runtime order are
    intentionally not inferred here. All source statements remain in the data.
    """
    if language == "cmake":
        return _cmake_scan(path, text)
    if language not in _GRAMMARS:
        return {"symbols": [], "imports": [], "warnings": [f"No syntax adapter for {language!r}; this file is available in the source browser."]}
    try:
        return _Scanner(path, text, language).scan()
    except (ImportError, AttributeError, TypeError) as exc:
        return {"symbols": [], "imports": [], "warnings": [f"Could not load/use {language} syntax parser: {exc}"]}
