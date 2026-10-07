# Editor design model

`project.hpp` is an editor-private C++20 interface with no GUI or third-party
library dependency. `parse_project` reads schema-1 UTF-8 JSON, rejecting duplicate
keys, unknown fields, unsupported versions, malformed Unicode, unsafe paths and
resource-limit violations. Diagnostic paths identify the affected object; syntax
errors also identify a one-based line and byte column. At most 256 diagnostics
are retained, with an error preserved even when warnings fill that budget.

A readable, safe design is returned even when composition errors remain. This
lets the editor open and save incomplete work. Call `validate` and reject
`has_errors` before generation or execution. Required but unconnected ports are
composition errors; unfinished code bindings are warnings and generation applies
its own readiness checks. Persistence never executes recipes or project source.

`write_project` preserves declaration order, writes object keys consistently and
retains Unicode bytes. It can save incomplete safe designs. `semantic_project`
removes block positions from the deterministic generation input. Control layout
coordinates are absolute form-space logical pixels; parent names express group
ownership and do not change the coordinate origin. Form layouts are semantic.
Text controls declare `multiline`, `read_only` and `text_limit` (UTF-8 bytes).
Initial text and suggestion values must fit that policy.

Object IDs are unique across forms, controls, bindings, explicit flows, blocks,
edges and recipes. Port IDs are unique within one block direction; option IDs are
unique within one control. If no explicit flow list exists, blocks may use the
implicit `main` flow. Edges join matching named input/output types within a flow,
with one producer per input and one consumer per output. Split, broadcast and
merge semantics belong to explicit arbitrary-MIMO blocks. State-bearing
factories mark `breaks_cycle`, and the graph after removing their outgoing edges
must be acyclic. Numeric `initial_tokens` cannot express typed state and are
rejected for generation; ordinary factories own their actual initial values.

Source bindings refer to portable project-relative `file` navigation paths and
optional declaration `header` paths. Files can be ordinary C++ or Rust text;
`symbol` names an explicitly written C++ adapter. `generated_directory` and
`cpp_namespace` select the generated C++ destination without application-specific
rules. Paths are lexical validation only: filesystem services still check
workspace ownership and symlink traversal before I/O. Recipe arguments remain
argument arrays and are never parsed as shell text by this model.

Default limits cover an 8 MiB document, 2 MiB per string, 32 JSON nesting levels,
200,000 values, 8,192 controls/blocks/bindings, 32,768 ports/edges/options and
1,048,576 elements per queue. `Limits` can reduce these bounds. Coordinates and
dimensions are finite and bounded to 10,000,000 logical pixels.

`History` stores deterministic snapshots with 16 MiB of payload and 128 entries
by default. Undo/redo affects design objects only, never handwritten source.
Oversized edits leave the existing history unchanged; callers decide whether to
apply such an edit without undo or report the configured bound.
