# Deterministic source generation

`generate(project)` returns project-relative files and diagnostics without reading,
writing or executing anything. Empty `GenerationOptions` overrides inherit the
project's `generated_directory` and `cpp_namespace`. Failed generation returns no
publishable files. The CLI and editor use the same emitter.

The retained C++ headers are ordinary application inputs:

- `forms.hpp` provides `snapshot(form_id, generation)` and
  `all_forms_snapshot(generation)`, using the public GUI contract.
- `events.hpp` provides binding descriptions and
  `bind_handlers(visual::Ui&, Services&)`. A linked handler wrapper receives
  `(Services&, visual::Ui&, const gui::Activate&)`, or the appropriate typed
  GUI input for its event. The services object must outlive registered callbacks.
- `flows.hpp` provides `make_flow(flow_id, Services&, GraphOptions = {})` and
  individual encoded flow factory names. Factories receive `(Services&)` or
  `(Services&, const std::map<std::string, std::string>& parameters)` and return
  `std::unique_ptr<visual::flow::Block>`. Graph construction does not start work.
  Services must outlive the graph, including shutdown and join.

`dispatch_handler(UiContext&, Services&, const gui::WidgetEvent&)` supports an
application-owned GUI model, including the editor itself. Its caller validates
the widget generation, availability and event ownership before dispatch. Its
wrappers may use a generic `UiContext` instead of `visual::Ui`.

Binding and block `file` fields navigate to handwritten source. Their `header`
fields include ordinary declaration headers for compiler checking. A header
navigation file can also serve as the declaration header. `.cpp` and Rust files
are never included in generated C++. With no header, the emitter warns; include
the wrapper's declaration before the generated header. Arbitrary implementation
signatures, state, Rust C ABI calls and algorithms belong beneath these small
project-owned wrappers.

The emitter validates qualified symbols, include paths and a bounded set of C++
value-type tokens. More complicated stream types use an alias in an ordinary
header. Port declarations preserve order, names, types and required status;
compiled graph wiring uses the corresponding port indices. Split and merge
blocks make ownership explicit. Feedback uses a typed stateful `breaks_cycle`
factory; a numeric `initial_tokens` count cannot initialize arbitrary objects.

Outputs omit time and machine paths. Source strings use fixed-width byte escapes,
and generated names encode punctuation injectively. Flow positions do not change
semantic output. Forms-only projects receive no graph header; headless projects
receive no GUI header. The exact canonical semantic `design.json` is the final
publication marker. The separate exact ownership guard identifies the generated
directory. `may_replace_generated` performs a pure ownership preflight; rooted
files, conflict checks, save journaling and checked replacement remain the
platform layer's responsibilities.

`handler_stub` and `block_stub` return skeleton text only. Explicit new-code
actions create those files exclusively, once. Regeneration never invokes these
helpers or modifies handwritten files. Consumers compile retained headers without
running the editor or generator; external semantic design edits require an
explicit generation step before adopting the changed composition.
