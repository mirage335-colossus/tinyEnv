# Optional GUI model support

`ui.hpp` and `ui.cpp` use only C++20 and the public GUI boundary. An adopting
application explicitly compiles `ui.cpp`, supplies its existing `gui::Adapter`,
and constructs `foundation::visual::Ui` from its generated or handwritten
`gui::Snapshot`. No editor or toolkit header is needed by the application code.

The composition root owns services and their lifetimes. Ordinary lambdas adapt
arbitrary functions to GUI input; helpers may update the same explicitly passed
`Ui` facade from any level of application code:

```cpp
Ui ui(adapter, generated::make_form());
ui.bind<gui::Activate>("receiver.start", [&services](Ui& ui,
                                                    const gui::Activate&) {
    auto changes = ui.batch();
    ui.set_enabled("receiver.start", false);
    ui.replace_options("receiver.device", services.devices(),
                       SelectionPolicy::keep_if_present);
    ui.set_text("receiver.status", services.start_receiver());
});
```

Generated `EventBinding` descriptors identify widget IDs, event kinds and
project adapter IDs. Registration is explicit; descriptors do not execute code.
`bind<Input>` provides typed event payloads, while `bind(id, kind, handler)`
receives the complete public `gui::WidgetEvent`. Neither interface limits the
functions, objects or Rust C ABI wrappers called beneath the adapter.
Typed binding also supports callables owning move-only C++ objects.

The model validates stable widget keys, kinds, UTF-8, selection IDs and input
availability. `UiResult` reports invalid/stale updates. Replacing options or
records retains a selected stable ID only while present; `SelectionPolicy::clear`
always clears it. Programmatic updates synthesize no user input. Native input
updates the model before handlers run. Disabled/hidden controls and stale text
bases reject user input, including retained events delivered after lockout.
Callbacks dispatch in order without reentrancy. Hosts call `handle(event)` and
may call `dispatch_pending()` on a tick to process bounded callback-generated
event chains. `restart(snapshot)` invalidates old widget keys and clears bindings;
register the new view's handlers explicitly.

All direct model access belongs to the constructing UI thread. Use `batch()` to
publish multiple changes together. Presentation failure retains authoritative
state and reports `presentation_pending()`/`presentation_error()`; the host may
retry `publish()`. The host owns geometry recomputation and the adapter lifecycle.
`invalidate_layout()` republishes the current geometry after an application-owned
layout operation; it does not supply a new constraint solver. `close()` closes
the model/mailbox; the host separately closes its native adapter/event loop.

Workers capture an owned `UiPost` from `begin_request()` and stable keys captured
on the UI thread, then post owned typed `UiCommand` values. Mailbox capacity is
configurable by command count (default 128); retained payload capacity is bounded
to 16 MiB, including reserved string/vector capacities, excluding allocator
overhead. `Delivery::progress` requires a coalescing key and may replace earlier
progress with that key. Reliable messages remain FIFO and never silently
disappear to make room. Inspect every `PostResult`: `full` requires an explicit
retry or application-level failure path for completion/control updates.
`accepted` acknowledges enqueueing, not execution. `drain()` reports command
results/errors and batches presentation. Beginning another request, replacing a
view, closing or destroying the UI discards pending old work and rejects later
posts from that generation. Join workers before borrowed application services
are destroyed; mailbox ownership does not extend service lifetime.

The focused tests are local under `editor/tests/ui_support_test.cpp`. This support
is optional application runtime source when adopted; it remains outside the
editor-only CI exclusion.
