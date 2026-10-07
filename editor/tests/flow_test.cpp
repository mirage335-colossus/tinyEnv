#include "visual/flow/flow.hpp"

#include <array>
#include <cassert>
#include <future>
#include <iostream>
#include <numeric>

using namespace foundation::visual::flow;

namespace {
void complete(Graph& graph) {
    for (int i = 0; i != 20000 && graph.snapshot().state == GraphState::running; ++i) graph.step(8);
    const auto status = graph.snapshot();
    if (status.state != GraphState::completed) throw std::runtime_error(status.error.empty() ? "graph did not complete" : status.error);
    graph.join();
}
template<class Function> void rejects(Function f) {
    bool rejected = false;
    try { f(); } catch (const std::exception&) { rejected = true; }
    assert(rejected);
}
NodeId source(Graph& graph, const std::string& id, int limit) {
    return graph.add({id, {}, {PortSpec::typed<int>("out")}, [limit] {
        return make_block([next = 0, limit](WorkContext& c, WorkResult& r) mutable {
            auto out = c.output<int>(0);
            const auto n = std::min(out.size(), static_cast<std::size_t>(limit - next));
            for (std::size_t i = 0; i < n; ++i) out[i] = next++;
            r.produced[0] = n;
            r.status = next == limit ? WorkStatus::finished : n ? WorkStatus::progress : WorkStatus::waiting;
        });
    }});
}
NodeId sink(Graph& graph, const std::string& id, std::vector<int>& data, int limit = -1) {
    return graph.add({id, {PortSpec::typed<int>("in")}, {}, [&data, limit] {
        return make_block([&data, limit](WorkContext& c, WorkResult& r) {
            const auto in = c.input<int>(0);
            const auto remaining = limit < 0 ? in.size() : static_cast<std::size_t>(limit) - data.size();
            // Deliberately consume one per Work, exercising compacted small queues.
            const auto n = std::min({in.size(), remaining, std::size_t{1}});
            data.insert(data.end(), in.begin(), in.begin() + static_cast<std::ptrdiff_t>(n));
            r.consumed[0] = n;
            r.status = (limit >= 0 && data.size() == static_cast<std::size_t>(limit)) || c.input_finished(0)
                     ? WorkStatus::finished : n ? WorkStatus::progress : WorkStatus::waiting;
        });
    }});
}

void mimo() {
    Graph graph;
    const auto a = source(graph, "a", 19), b = source(graph, "b", 7);
    const auto block = graph.add({"mimo", {PortSpec::typed<int>("a"), PortSpec::typed<int>("b")},
        {PortSpec::typed<int>("each-a"), PortSpec::typed<int>("each-b"),
         PortSpec::typed<double>("half-a"), PortSpec::typed<std::string>("odd-b")}, [] {
            return make_block([](WorkContext& c, WorkResult& r) {
                const auto a = c.input<int>(0), b = c.input<int>(1);
                auto oa = c.output<int>(0), ob = c.output<int>(1);
                auto half = c.output<double>(2);
                auto text = c.writer<std::string>(3);
                const auto na = std::min(a.size(), oa.size());
                const auto nb = std::min(b.size(), ob.size());
                std::size_t ca = 0, cb = 0, halves = 0;
                for (; ca < na; ++ca) {
                    if (!(a[ca] % 2) && halves == half.size()) break;
                    oa[ca] = a[ca] * 2;
                    if (!(a[ca] % 2)) half[halves++] = a[ca] / 2.0;
                }
                for (; cb < nb; ++cb) {
                    if (b[cb] % 2 && text.size() == text.capacity()) break;
                    ob[cb] = b[cb] * 3;
                    if (b[cb] % 2) text.emplace(std::to_string(b[cb]));
                }
                r.consumed = {ca, cb}; r.produced = {ca, cb, halves, text.size()};
                if (c.input_finished(0)) { r.close_outputs[0] = true; r.close_outputs[2] = true; }
                if (c.input_finished(1)) { r.close_outputs[1] = true; r.close_outputs[3] = true; }
                r.status = c.input_finished(0) && c.input_finished(1) ? WorkStatus::finished
                         : ca || cb ? WorkStatus::progress : WorkStatus::waiting;
            });
        }});
    std::vector<int> output_a, output_b;
    std::vector<double> output_half;
    std::vector<std::string> output_text;
    const auto sa = sink(graph, "sa", output_a), sb = sink(graph, "sb", output_b);
    const auto sc = graph.add({"sc", {PortSpec::typed<double>("in")}, {}, [&] {
        return make_block([&](WorkContext& c, WorkResult& r) {
            const auto in = c.input<double>(0);
            output_half.insert(output_half.end(), in.begin(), in.end());
            r.consumed[0] = in.size();
            r.status = c.input_finished(0) ? WorkStatus::finished : in.empty() ? WorkStatus::waiting : WorkStatus::progress;
        });
    }});
    const auto sd = graph.add({"sd", {PortSpec::typed<std::string>("in")}, {}, [&] {
        return make_block([&](WorkContext& c, WorkResult& r) {
            const auto in = c.input<std::string>(0);
            if (!in.empty()) { output_text.push_back(c.take_next<std::string>(0)); r.consumed[0] = 1; }
            r.status = c.input_finished(0) ? WorkStatus::finished : in.empty() ? WorkStatus::waiting : WorkStatus::progress;
        });
    }});
    graph.connect(a, 0, block, 0, 3); graph.connect(b, 0, block, 1, 2);
    graph.connect(block, 0, sa, 0, 2); graph.connect(block, 1, sb, 0, 1);
    graph.connect(block, 2, sc, 0, 1); graph.connect(block, 3, sd, 0, 1);
    graph.start(RunMode::cooperative);
    complete(graph);
    assert(output_a.size() == 19 && output_b.size() == 7 && output_half.size() == 10 && output_text.size() == 3);
    for (int i = 0; i < 19; ++i) assert(output_a[i] == 2 * i);
    for (int i = 0; i < 7; ++i) assert(output_b[i] == 3 * i);
    assert(output_text == std::vector<std::string>({"1", "3", "5"}));
}

void early_close_and_restart() {
    Graph graph;
    std::vector<int> data;
    const auto a = source(graph, "unbounded-enough", 100000);
    const auto b = sink(graph, "early", data, 3);
    graph.connect(a, 0, b, 0, 2);
    graph.start(RunMode::cooperative);
    const auto generation = graph.generation();
    complete(graph);
    assert(data == std::vector<int>({0, 1, 2}));
    assert(!graph.wake(generation));
    assert(!graph.post(generation, [] {}));
    data.clear(); graph.start(RunMode::cooperative); complete(graph);
    assert(data == std::vector<int>({0, 1, 2}));

    Graph chain;
    std::vector<int> early;
    const auto x = source(chain, "upstream", 10000);
    const auto y = chain.add({"middle", {PortSpec::typed<int>("in")}, {PortSpec::typed<int>("out")}, [] {
        return make_block([](WorkContext& c, WorkResult& r) {
            const auto in = c.input<int>(0); auto out = c.output<int>(0);
            const auto n = std::min(in.size(), out.size());
            std::copy_n(in.begin(), n, out.begin()); r.consumed[0] = r.produced[0] = n;
            r.status = c.input_finished(0) ? WorkStatus::finished : n ? WorkStatus::progress : WorkStatus::waiting;
        });
    }});
    const auto z = sink(chain, "early-downstream", early, 1);
    chain.connect(x, 0, y, 0, 1); chain.connect(y, 0, z, 0, 1);
    chain.start(RunMode::cooperative); complete(chain);
    assert(early == std::vector<int>({0}));
}

struct Owned {
    static inline int alive = 0;
    std::unique_ptr<int> value;
    explicit Owned(int i) : value(std::make_unique<int>(i)) { ++alive; }
    Owned(Owned&& other) noexcept : value(std::move(other.value)) { ++alive; }
    Owned& operator=(Owned&&) = delete;
    ~Owned() { --alive; }
};

void object_lifetime(bool throw_work, bool bad_count) {
    Graph graph;
    int sum = 0;
    const auto a = graph.add({"owned-source", {}, {PortSpec::typed<Owned>("owned")}, [=] {
        return make_block([next = 0, throw_work, bad_count](WorkContext& c, WorkResult& r) mutable {
            auto writer = c.writer<Owned>(0);
            const auto n = std::min(writer.capacity(), static_cast<std::size_t>(9 - next));
            for (std::size_t i = 0; i < n; ++i) writer.emplace(next++);
            if (throw_work) throw std::runtime_error("injected object failure");
            r.produced[0] = bad_count ? 0 : writer.size();
            r.status = next == 9 ? WorkStatus::finished : n ? WorkStatus::progress : WorkStatus::waiting;
        });
    }});
    const auto b = graph.add({"owned-sink", {PortSpec::typed<Owned>("owned")}, {}, [&] {
        return make_block([&](WorkContext& c, WorkResult& r) {
            if (!c.input<Owned>(0).empty()) {
                auto owned = c.take_next<Owned>(0);
                sum += *owned.value;
                r.consumed[0] = 1;
                r.status = WorkStatus::progress;
            } else r.status = c.input_finished(0) ? WorkStatus::finished : WorkStatus::waiting;
        });
    }});
    graph.connect(a, 0, b, 0, 3); graph.start(RunMode::cooperative);
    for (int i = 0; i < 1000 && graph.snapshot().state == GraphState::running; ++i) graph.step(3);
    assert(graph.snapshot().state == (throw_work || bad_count ? GraphState::failed : GraphState::completed));
    assert(Owned::alive == 0);
    if (!throw_work && !bad_count) assert(sum == 36);
}

struct ThrowMove {
    static inline int alive{}, moves_before_throw{};
    int value;
    explicit ThrowMove(int i) : value(i) { ++alive; }
    ThrowMove(ThrowMove&& other) : value(other.value) {
        if (!moves_before_throw--) throw std::runtime_error("move failed during compaction");
        ++alive;
    }
    ~ThrowMove() { --alive; }
};

void compact_exception_and_optional_side_effect() {
    Graph graph;
    ThrowMove::moves_before_throw = 1;
    const auto a = graph.add({"throw-source", {}, {PortSpec::typed<ThrowMove>("out")}, [] {
        return make_block([](WorkContext& c, WorkResult& r) {
            auto out = c.writer<ThrowMove>(0);
            while (out.size() < out.capacity()) out.emplace(7);
            r.produced[0] = out.size(); r.status = WorkStatus::progress;
        });
    }});
    const auto b = graph.add({"throw-sink", {PortSpec::typed<ThrowMove>("in")}, {}, [] {
        return make_block([](WorkContext& c, WorkResult& r) {
            if (!c.input<ThrowMove>(0).empty()) { r.consumed[0] = 1; r.status = WorkStatus::progress; }
        });
    }});
    graph.connect(a, 0, b, 0, 3); graph.start(RunMode::cooperative); graph.step(3);
    assert(graph.snapshot().state == GraphState::failed && ThrowMove::alive == 0);
    assert(graph.snapshot().error.find("compaction") != std::string::npos);

    Graph optional;
    bool called = false;
    optional.add({"optional-side-effect", {}, {PortSpec::typed<int>("out", 1, true)}, [&] {
        return make_block([&](WorkContext& c, WorkResult& r) {
            called = true; assert(c.output_closed(0)); assert(c.output<int>(0).empty());
            r.status = WorkStatus::finished;
        });
    }});
    optional.start(RunMode::cooperative); complete(optional); assert(called);

    Graph move_only_callback;
    int received = 0;
    move_only_callback.add({"owned-lambda", {}, {}, [&] {
        return make_block([owned = std::make_unique<int>(41), &received](WorkContext&, WorkResult& r) {
            received = *owned; r.status = WorkStatus::finished;
        });
    }});
    move_only_callback.start(RunMode::cooperative); complete(move_only_callback);
    assert(received == 41);
}

void move_count_and_type_errors() {
    Graph graph;
    const auto a = source(graph, "a", 2);
    const auto b = graph.add({"bad-take", {PortSpec::typed<int>("in")}, {}, [] {
        return make_block([](WorkContext& c, WorkResult& r) {
            if (!c.input<int>(0).empty()) { (void)c.take_next<int>(0); r.status = WorkStatus::finished; }
        });
    }});
    graph.connect(a, 0, b, 0, 2); graph.start(RunMode::cooperative); graph.step(3);
    assert(graph.snapshot().state == GraphState::failed);
    assert(graph.snapshot().error.find("consumed prefix") != std::string::npos);

    Graph types;
    const auto x = source(types, "x", 2);
    const auto y = types.add({"bad-type", {PortSpec::typed<int>("in")}, {}, [] {
        return make_block([](WorkContext& c, WorkResult&) { (void)c.input<double>(0); });
    }});
    types.connect(x, 0, y, 0, 2); types.start(RunMode::cooperative); types.step(3);
    assert(types.snapshot().state == GraphState::failed);
    assert(types.snapshot().error.find("type mismatch") != std::string::npos);
}

void validation_and_setup() {
    Graph empty; rejects([&] { empty.start(RunMode::cooperative); });
    assert(empty.snapshot().state == GraphState::failed);
    Graph missing; source(missing, "source", 1); rejects([&] { missing.validate(); });
    Graph mismatch;
    const auto a = source(mismatch, "source", 2);
    const auto b = mismatch.add({"sink", {PortSpec::typed<float>("in")}, {}, [] { return make_block([](auto&, auto&) {}); }});
    rejects([&] { mismatch.connect(a, 0, b, 0); });
    Graph duplicate;
    std::vector<int> data;
    const auto x = source(duplicate, "x", 1), y = sink(duplicate, "y", data), z = sink(duplicate, "z", data);
    duplicate.connect(x, 0, y, 0);
    rejects([&] { duplicate.connect(x, 0, z, 0); });
    Graph bounded(GraphOptions{1024, 8192, 3});
    const auto p = source(bounded, "p", 1), q = sink(bounded, "q", data);
    bounded.connect(p, 0, q, 0, 1); rejects([&] { bounded.validate(); });
    Graph batch;
    const auto i = batch.add({"i", {}, {PortSpec::typed<int>("out", 4)}, [] { return make_block([](auto&, auto&) {}); }});
    const auto j = sink(batch, "j", data);
    rejects([&] { batch.connect(i, 0, j, 0, 3); });

    std::vector<int> destruction;
    struct Tracked : Block {
        std::vector<int>& log; int id;
        Tracked(std::vector<int>& l, int i) : log(l), id(i) {}
        ~Tracked() override { log.push_back(id); }
        void work(WorkContext&, WorkResult&) override {}
    };
    Graph factories;
    factories.add({"first", {}, {}, [&] { return std::make_unique<Tracked>(destruction, 1); }});
    factories.add({"second", {}, {}, [&] { return std::make_unique<Tracked>(destruction, 2); }});
    factories.add({"third", {}, {}, []() -> std::unique_ptr<Block> { throw std::runtime_error("factory failed"); }});
    rejects([&] { factories.start(RunMode::cooperative); });
    assert(destruction == std::vector<int>({2, 1}));
    assert(factories.snapshot().error.find("third factory") != std::string::npos);
}

void cycle_and_stall() {
    Graph cycle;
    const auto block = cycle.add({"delay", {PortSpec::typed<int>("in")}, {PortSpec::typed<int>("out")}, [] {
        return make_block([](WorkContext&, WorkResult&) {});
    }});
    cycle.connect(block, 0, block, 0, 2);
    rejects([&] { cycle.validate(); });
    Graph seeded;
    std::vector<int> observed;
    const auto delayed = seeded.add({"delay", {PortSpec::typed<int>("in")}, {PortSpec::typed<int>("out")}, [&] {
        return make_block([seed = true, &observed](WorkContext& c, WorkResult& r) mutable {
            auto in = c.input<int>(0); auto out = c.output<int>(0);
            if (seed) {
                out[0] = 1; r.produced[0] = 1; r.status = WorkStatus::waiting;
                r.waits.push_back(WaitCondition::input(0)); seed = false;
            }
            else if (!in.empty() && !out.empty()) {
                observed.push_back(in[0]); out[0] = in[0] + 1;
                r.consumed[0] = 1; r.produced[0] = 1;
                r.status = in[0] == 5 ? WorkStatus::finished : WorkStatus::progress;
            }
        });
    }, true});
    seeded.connect(delayed, 0, delayed, 0, 2); seeded.start(RunMode::cooperative); complete(seeded);
    assert(observed == std::vector<int>({1, 2, 3, 4, 5}));

    Graph stalled;
    stalled.add({"wait", {}, {}, [] { return make_block([](WorkContext&, WorkResult&) {}); }});
    stalled.start(RunMode::cooperative); stalled.step(2);
    assert(stalled.snapshot().state == GraphState::failed);
    assert(stalled.snapshot().error.find("stalled") != std::string::npos);
}

void stop_wake_command_and_worker() {
    Graph waiting(GraphOptions{1024, 8192, 64 * 1024 * 1024, 1});
    bool finish = false;
    waiting.add({"external", {}, {}, [&] {
        return make_block([&](WorkContext&, WorkResult& r) {
            r.status = finish ? WorkStatus::finished : WorkStatus::waiting;
            if (!finish) r.waits.push_back(WaitCondition::external());
        });
    }});
    waiting.start(RunMode::cooperative); waiting.step(1);
    auto generation = waiting.generation();
    assert(waiting.step(1) == 0 && waiting.snapshot().state == GraphState::running);
    assert(waiting.post(generation, [&] { finish = true; }));
    assert(!waiting.post(generation, [] {}));
    complete(waiting);

    finish = false; waiting.start(RunMode::cooperative); waiting.step(1);
    generation = waiting.generation(); waiting.request_stop();
    assert(waiting.snapshot().state == GraphState::stopping);
    assert(!waiting.wake(generation)); waiting.join();
    assert(waiting.snapshot().state == GraphState::stopped);

    Graph timer;
    timer.add({"timer", {}, {}, [] {
        return make_block([initial = true](WorkContext&, WorkResult& r) mutable {
            if (initial) {
                r.waits.push_back(WaitCondition::timer(std::chrono::steady_clock::now() + std::chrono::milliseconds(2)));
                initial = false;
            } else r.status = WorkStatus::finished;
        });
    }});
    timer.start(); timer.join(); assert(timer.snapshot().state == GraphState::completed);

    Graph worker;
    std::vector<int> data;
    const auto a = source(worker, "source", 100), b = sink(worker, "sink", data);
    worker.connect(a, 0, b, 0, 7); worker.start(); worker.join();
    assert(worker.snapshot().state == GraphState::completed && data.size() == 100);

    std::promise<void> checking, let_return;
    auto returned = let_return.get_future().share();
    std::atomic<bool> signalled{};
    Graph wake_during_work;
    wake_during_work.add({"external-race", {}, {}, [&] {
        return make_block([first = true, &checking, &returned, &signalled](WorkContext&, WorkResult& r) mutable {
            if (first) {
                first = false; checking.set_value(); returned.wait();
                r.waits.push_back(WaitCondition::external());
            } else r.status = signalled.load() ? WorkStatus::finished : WorkStatus::error;
        });
    }});
    wake_during_work.start(); checking.get_future().wait();
    signalled.store(true); assert(wake_during_work.wake(wake_during_work.generation()));
    let_return.set_value(); wake_during_work.join();
    assert(wake_during_work.snapshot().state == GraphState::completed);

    std::promise<void> entered, release;
    auto released = release.get_future().share();
    Graph cooperative_call;
    cooperative_call.add({"bounded-call", {}, {}, [&] {
        return make_block([&](WorkContext& c, WorkResult& r) {
            entered.set_value(); released.wait();
            assert(c.cancelled()); r.status = WorkStatus::finished;
        });
    }});
    cooperative_call.start(); entered.get_future().wait();
    cooperative_call.request_stop();
    assert(cooperative_call.snapshot().state == GraphState::stopping);
    release.set_value(); cooperative_call.join();
    assert(cooperative_call.snapshot().state == GraphState::stopped);
}

void output_close_independent() {
    Graph graph;
    std::vector<int> short_stream, long_stream;
    const auto a = graph.add({"split-rate-source", {}, {PortSpec::typed<int>("short"), PortSpec::typed<int>("long")}, [] {
        return make_block([next = 0](WorkContext& c, WorkResult& r) mutable {
            const auto short_out = c.output<int>(0), long_out = c.output<int>(1);
            if (!next && !short_out.empty()) { short_out[0] = 77; r.produced[0] = 1; r.close_outputs[0] = true; }
            if (!long_out.empty()) { long_out[0] = next++; r.produced[1] = 1; }
            r.status = next == 8 ? WorkStatus::finished : r.produced[1] ? WorkStatus::progress : WorkStatus::waiting;
        });
    }});
    const auto b = sink(graph, "short", short_stream), c = sink(graph, "long", long_stream);
    graph.connect(a, 0, b, 0, 1); graph.connect(a, 1, c, 0, 2);
    graph.start(RunMode::cooperative); complete(graph);
    assert(short_stream == std::vector<int>({77}) && long_stream.size() == 8);
}
} // namespace

int main() {
    mimo(); early_close_and_restart(); object_lifetime(false, false);
    object_lifetime(true, false); object_lifetime(false, true);
    compact_exception_and_optional_side_effect();
    move_count_and_type_errors(); validation_and_setup(); cycle_and_stall();
    stop_wake_command_and_worker(); output_close_independent();
    std::cout << "flow runtime checks passed\n";
}
