# Optional typed stream runtime

`flow.hpp` and `flow.cpp` are a small C++20 module independent of the GUI,
editor, document format, Rust and the example application's default build.
Link `flow.cpp` explicitly from an application's own composition root. The
editor generator emits this ordinary API; constructing a graph by hand works
equally well. Objects and functions captured by factories are ordinary C++:
they can wrap arbitrary libraries or explicit Rust C ABI functions.

```cpp
using namespace foundation::visual::flow;
Graph graph;
const auto source = graph.add({"source", {}, {PortSpec::typed<float>("samples")}, [] {
    return make_block([remaining = 100](WorkContext& ctx, WorkResult& result) mutable {
        auto out = ctx.output<float>(0);
        const auto count = std::min(out.size(), static_cast<std::size_t>(remaining));
        std::fill_n(out.begin(), count, 1.0f);
        remaining -= static_cast<int>(count);
        result.produced[0] = count;
        result.status = remaining == 0 ? WorkStatus::finished
                      : count ? WorkStatus::progress : WorkStatus::waiting;
    });
}});
const auto sink = graph.add({"sink", {PortSpec::typed<float>("samples")}, {}, [] {
    return make_block([](WorkContext& ctx, WorkResult& result) {
        auto in = ctx.input<float>(0);
        // Call any application function here, with owned/injected state.
        result.consumed[0] = in.size();
        result.status = ctx.input_finished(0) ? WorkStatus::finished
                      : in.empty() ? WorkStatus::waiting : WorkStatus::progress;
    });
}});
graph.connect(source, 0, sink, 0, 256);
graph.start();
graph.join();
if (graph.snapshot().state == GraphState::failed)
    throw std::runtime_error(graph.snapshot().error);
```

Every input and output has its own type, capacity and consumed/produced count.
Sources have no inputs, sinks have no outputs, and neither common rates nor
equal arity are required. Factories create fresh instances on every start.
One edge has one producer and consumer: insert ordinary explicit split/merge
blocks for fan-out/in and declare their ordering and ownership policy. Required
ports must connect; optional disconnected ports offer no items/capacity and are
closed. An entirely disconnected optional output does not suppress Work.

Each Work call receives full contiguous live input spans and available output
capacity. Numeric/trivially copyable default-constructible assignable types use writable
`output<T>()` spans. Other types use `writer<T>().emplace(...)`, which constructs
actual aligned objects. Its constructed prefix must exactly equal the returned
produced count. `take_next<T>()` moves input ownership, and the returned consumed
prefix must cover all taken items. Read spans are otherwise const. No span or
writer survives the Work call. Queues compact between calls; nontrivial queued
objects can therefore be moved even if a block only reads them. Types must be
move-constructible with non-throwing destructors. A throwing move, factory, Work
or command fails the whole graph and destroys all live/staged objects; there is
no rollback guarantee for moved objects or application side effects.

WorkResult arrays are preallocated and reset to zero by the runtime; do not
resize them. Fill counts, optional `close_outputs[i]`, and a status. `progress`
requires item movement, output closure, or explicit `state_changed = true` for
private-state progress. `finished` closes all remaining outputs and abandons
inputs, discarding their unread items. Producers whose connected consumers have
all abandoned their inputs quiesce transitively. `input_closed()` observes EOF;
`input_finished()` observes EOF after draining. Unequal-length handling is the
block's explicit choice. Closing one output leaves other outputs usable.

The scheduler offers one Work call per round-robin turn. The default owns one
worker; `start(RunMode::cooperative)` with `step(max_calls)` uses a project-owned
executor. There are no concurrent Work invocations within a graph. Queue buffers
and runtime count arrays allocate during setup. Ordinary numeric scheduling
allocates no per-call runtime storage. Nontrivial object moves and user callbacks
may have their own costs; this is not a hard real-time scheduler. Buffer capacity
must satisfy both ports' minimum batch and the graph's total item-byte budget.
All leases are contiguous because compaction occurs before Work. Capacity is a
maximum; neither minimum batch nor port declarations guarantee data is present.

A waiting block may name input/output revision changes, an explicit external
`wake(generation)`, or a steady-clock timer. With no named conditions, any of
its connected port revisions can wake it. Timers/external waits sleep the owned
worker; cooperative execution returns zero until useful work is available.
Closed graphs with no possible wake fail with block/port diagnostics instead of
spinning. Every feedback cycle must cross a block marked `breaks_cycle`, whose
factory owns initialized delay/state; this declaration validates intent rather
than proving freedom from all algorithmic deadlocks.

`request_stop()` is thread-safe, invalidates the running generation immediately
and requests cooperative cancellation. It discards queues after Work returns;
`join()` waits for the owned worker or completes cooperative stop. It never
detaches a block. Work/device calls must have a bounded or cancellable lifetime.
Destroy/join a graph from its composition owner, never from its own Work. Service
references borrowed by a factory/block must outlive join. Rebuild topology only
after join. Natural completion, requested stop and failure are distinct states.

`post(generation, owned_closure)` is a bounded command endpoint, executed between
Work calls on the graph executor. Its bool return acknowledges admission or
rejects a stale generation, stopped graph or full mailbox. Capture owned values
or services with explicit lifetime/synchronization. A command may invoke an
application-owned typed parameter setter and send its own required acceptance
or rejection response. It must not mutate topology or borrow GUI objects. Use
the optional UI mailbox for worker-to-owner GUI effects. Natural completion,
failure and stop invalidate pending generations and discard unexecuted commands.

Focused runtime checks live in `editor/tests/flow_test.cpp`, selected explicitly
by the standalone editor's local test operation. They are absent from the
application's default test inventory and require no GUI dependencies.
