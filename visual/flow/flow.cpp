#include "visual/flow/flow.hpp"

#include <deque>
#include <sstream>
#include <unordered_set>

namespace foundation::visual::flow {

namespace {
class FunctionBlock final : public Block {
public:
    explicit FunctionBlock(std::function<void(WorkContext&, WorkResult&)> f) : function_(std::move(f)) {}
    void work(WorkContext& c, WorkResult& r) override { function_(c, r); }
private:
    std::function<void(WorkContext&, WorkResult&)> function_;
};
void check_ports(const std::vector<PortSpec>& ports, const std::string& block) {
    std::unordered_set<std::string> names;
    for (const auto& p : ports) {
        if (p.id.empty() || !names.insert(p.id).second)
            throw std::invalid_argument(block + ": empty or duplicate port ID");
        if (p.type == typeid(void) || !p.make_channel || !p.item_bytes || !p.minimum_batch)
            throw std::invalid_argument(block + "/" + p.id + ": invalid port contract");
    }
}
std::string current_exception() {
    try { throw; }
    catch (const std::exception& e) { return e.what(); }
    catch (...) { return "non-standard exception"; }
}
} // namespace

std::unique_ptr<Block> make_block(std::function<void(WorkContext&, WorkResult&)> f) {
    if (!f) throw std::invalid_argument("empty Work function");
    return std::make_unique<FunctionBlock>(std::move(f));
}

bool WorkContext::input_finished(std::size_t i) const {
    const auto* p = inputs_.at(i);
    return !p || (p->producer_closed && !p->count);
}
bool WorkContext::input_closed(std::size_t i) const {
    const auto* p = inputs_.at(i);
    return !p || p->producer_closed;
}
bool WorkContext::output_closed(std::size_t i) const {
    const auto* p = outputs_.at(i);
    return !p || p->producer_closed || p->consumer_closed;
}

struct Graph::Edge {
    NodeId from{}, to{};
    std::size_t output{}, input{}, capacity{};
    std::unique_ptr<detail::Channel> channel;
};
struct Graph::Instance {
    NodeId id{};
    std::unique_ptr<Block> block;
    WorkContext context;
    WorkResult result;
    bool finished{}, waiting{};
    std::vector<std::uint64_t> input_revisions, output_revisions;
    std::uint64_t wake_epoch{};
};

Graph::Graph(GraphOptions options) : options_(options) {}
Graph::~Graph() {
    request_stop();
    join();
}

void Graph::editable() const {
    std::lock_guard lock(mutex_);
    if (snapshot_.state == GraphState::running || snapshot_.state == GraphState::starting ||
        snapshot_.state == GraphState::stopping || worker_.joinable())
        throw std::logic_error("graph topology requires stop and join");
}

NodeId Graph::add(BlockSpec spec) {
    editable();
    if (specs_.size() >= options_.max_nodes) throw std::length_error("graph node limit exceeded");
    const auto index = specs_.size();
    specs_.push_back(std::move(spec));
    return index;
}

void Graph::connect(NodeId from, std::size_t output, NodeId to, std::size_t input,
                    std::size_t capacity) {
    editable();
    const auto& out = specs_.at(from).outputs.at(output);
    const auto& in = specs_.at(to).inputs.at(input);
    if (out.type != in.type) throw std::invalid_argument("connected stream C++ types differ");
    for (const auto& e : edges_) {
        if ((e->from == from && e->output == output) || (e->to == to && e->input == input))
            throw std::invalid_argument("one producer and one consumer per edge; use explicit split/merge");
    }
    if (!capacity || capacity < out.minimum_batch || capacity < in.minimum_batch)
        throw std::invalid_argument("queue capacity is below a port's minimum batch");
    auto edge = std::make_unique<Edge>();
    edge->from = from; edge->output = output; edge->to = to;
    edge->input = input; edge->capacity = capacity;
    edges_.push_back(std::move(edge));
}

void Graph::validate() const {
    if (specs_.empty()) throw std::invalid_argument("empty graph");
    if (specs_.size() > options_.max_nodes) throw std::length_error("graph node limit exceeded");
    std::unordered_set<std::string> ids;
    std::size_t ports = 0, bytes = 0;
    for (const auto& spec : specs_) {
        if (spec.id.empty() || !ids.insert(spec.id).second)
            throw std::invalid_argument("empty or duplicate block ID");
        if (!spec.factory) throw std::invalid_argument(spec.id + ": missing factory");
        check_ports(spec.inputs, spec.id);
        check_ports(spec.outputs, spec.id);
        if (spec.inputs.size() > options_.max_ports - ports)
            throw std::length_error("graph port limit exceeded");
        ports += spec.inputs.size();
        if (spec.outputs.size() > options_.max_ports - ports)
            throw std::length_error("graph port limit exceeded");
        ports += spec.outputs.size();
    }
    for (const auto& e : edges_) {
        const auto& from = specs_.at(e->from).outputs.at(e->output);
        const auto& to = specs_.at(e->to).inputs.at(e->input);
        if (from.type != to.type) throw std::invalid_argument("connected stream C++ types differ");
        if (!e->capacity || e->capacity < from.minimum_batch || e->capacity < to.minimum_batch)
            throw std::invalid_argument("queue capacity is below a port's minimum batch");
        if (e->capacity > options_.max_queue_bytes / from.item_bytes ||
            e->capacity * from.item_bytes > options_.max_queue_bytes - bytes)
            throw std::length_error("graph queue byte limit exceeded");
        bytes += e->capacity * from.item_bytes;
    }
    for (NodeId n = 0; n < specs_.size(); ++n) {
        for (std::size_t p = 0; p < specs_[n].inputs.size(); ++p) {
            if (specs_[n].inputs[p].optional) continue;
            const auto found = std::find_if(edges_.begin(), edges_.end(), [=](const auto& e) {
                return e->to == n && e->input == p;
            });
            if (found == edges_.end()) throw std::invalid_argument(specs_[n].id + "/" +
                specs_[n].inputs[p].id + ": required input is disconnected");
        }
        for (std::size_t p = 0; p < specs_[n].outputs.size(); ++p) {
            if (specs_[n].outputs[p].optional) continue;
            const auto found = std::find_if(edges_.begin(), edges_.end(), [=](const auto& e) {
                return e->from == n && e->output == p;
            });
            if (found == edges_.end()) throw std::invalid_argument(specs_[n].id + "/" +
                specs_[n].outputs[p].id + ": required output is disconnected");
        }
    }
    // Removing explicitly initialized state elements must leave an acyclic graph.
    std::vector<std::size_t> indegree(specs_.size());
    for (const auto& e : edges_)
        if (!specs_[e->from].breaks_cycle && !specs_[e->to].breaks_cycle) ++indegree[e->to];
    std::deque<NodeId> queue;
    std::size_t expected = 0, visited = 0;
    for (NodeId n = 0; n < specs_.size(); ++n) {
        if (!specs_[n].breaks_cycle) { ++expected; if (!indegree[n]) queue.push_back(n); }
    }
    while (!queue.empty()) {
        const auto n = queue.front(); queue.pop_front(); ++visited;
        for (const auto& e : edges_) {
            if (e->from == n && !specs_[e->to].breaks_cycle && !--indegree[e->to]) queue.push_back(e->to);
        }
    }
    if (visited != expected) throw std::invalid_argument("feedback cycle requires an initialized delay/state block");
}

void Graph::destroy_runtime() noexcept {
    // All blocks go first, in reverse factory order; services captured by the
    // composition owner must outlive join(). Channels then destroy owned items.
    for (auto i = instances_.rbegin(); i != instances_.rend(); ++i) (*i)->block.reset();
    instances_.clear();
    for (auto& e : edges_) e->channel.reset();
}

void Graph::setup() {
    validate();
    destroy_runtime();
    for (auto& e : edges_) {
        const auto& port = specs_[e->from].outputs[e->output];
        e->channel = port.make_channel(e->capacity);
        if (!e->channel || e->channel->type() != port.type || e->channel->capacity != e->capacity)
            throw std::runtime_error(specs_[e->from].id + "/" + port.id + ": invalid typed queue factory");
    }
    for (NodeId n = 0; n < specs_.size(); ++n) {
        auto instance = std::make_unique<Instance>();
        instance->id = n;
        auto& ctx = instance->context;
        ctx.inputs_.resize(specs_[n].inputs.size());
        ctx.outputs_.resize(specs_[n].outputs.size());
        ctx.taken_.resize(ctx.inputs_.size());
        ctx.cancel_ = &cancel_;
        ctx.generation_ = generation();
        for (auto& e : edges_) {
            if (e->to == n) ctx.inputs_[e->input] = e->channel.get();
            if (e->from == n) ctx.outputs_[e->output] = e->channel.get();
        }
        instance->result.consumed.resize(ctx.inputs_.size());
        instance->result.produced.resize(ctx.outputs_.size());
        instance->result.close_outputs.resize(ctx.outputs_.size());
        instance->result.waits.reserve(ctx.inputs_.size() + ctx.outputs_.size() + 1);
        instance->input_revisions.resize(ctx.inputs_.size());
        instance->output_revisions.resize(ctx.outputs_.size());
        try {
            instance->block = specs_[n].factory();
            if (!instance->block) throw std::runtime_error("factory returned null");
        } catch (...) {
            throw std::runtime_error(specs_[n].id + " factory: " + current_exception());
        }
        instances_.push_back(std::move(instance));
    }
    cursor_ = 0;
}

void Graph::start(RunMode mode) {
    editable();
    std::lock_guard execution(execution_mutex_);
    {
        std::lock_guard lock(mutex_);
        snapshot_.state = GraphState::starting;
        ++snapshot_.generation;
        snapshot_.error.clear();
        snapshot_.work_calls = snapshot_.items_consumed = snapshot_.items_produced = 0;
        cancel_.store(false);
        commands_.clear();
        mode_ = mode;
    }
    try {
        setup();
        {
            std::lock_guard lock(mutex_);
            if (cancel_.load()) {
                snapshot_.state = GraphState::stopping;
            } else snapshot_.state = GraphState::running;
        }
        if (mode == RunMode::worker) worker_ = std::thread([this] { worker_loop(); });
        else if (cancel_.load()) terminal(GraphState::stopped);
    } catch (...) {
        const auto message = "graph setup: " + current_exception();
        fail(message);
        throw std::runtime_error(message);
    }
}

bool Graph::ready(const Instance& instance) const {
    if (instance.finished) return false;
    if (!instance.waiting) return true;
    const auto& c = instance.context;
    const auto changed_input = [&](std::size_t i) {
        const auto* p = c.inputs_.at(i);
        return p && p->revision != instance.input_revisions[i];
    };
    const auto changed_output = [&](std::size_t i) {
        const auto* p = c.outputs_.at(i);
        return p && p->revision != instance.output_revisions[i];
    };
    if (instance.result.waits.empty()) {
        for (std::size_t i = 0; i < c.inputs_.size(); ++i) if (changed_input(i)) return true;
        for (std::size_t i = 0; i < c.outputs_.size(); ++i) if (changed_output(i)) return true;
        return false;
    }
    for (const auto& w : instance.result.waits) {
        switch (w.kind) {
        case WaitCondition::Kind::input: if (changed_input(w.port)) return true; break;
        case WaitCondition::Kind::output: if (changed_output(w.port)) return true; break;
        case WaitCondition::Kind::external: {
            std::lock_guard lock(mutex_);
            if (wake_epoch_ != instance.wake_epoch) return true;
            break;
        }
        case WaitCondition::Kind::timer:
            if (std::chrono::steady_clock::now() >= w.deadline) return true;
            break;
        }
    }
    return false;
}

void Graph::finish(Instance& instance) {
    if (instance.finished) return;
    instance.finished = true;
    for (auto* p : instance.context.outputs_) {
        if (p && !p->producer_closed) { p->producer_closed = true; ++p->revision; }
    }
    for (auto* p : instance.context.inputs_) {
        if (p && !p->consumer_closed) {
            p->consumer_closed = true;
            p->discard();
        }
    }
}

void Graph::terminal(GraphState state) {
    destroy_runtime();
    std::lock_guard lock(mutex_);
    if (state == GraphState::completed && cancel_.load()) state = GraphState::stopped;
    snapshot_.state = state;
    ++snapshot_.generation;
    commands_.clear();
    cv_.notify_all();
}
void Graph::fail(std::string message) {
    cancel_.store(true);
    {
        std::lock_guard lock(mutex_);
        snapshot_.error = std::move(message);
    }
    terminal(GraphState::failed);
}

std::size_t Graph::turn(std::size_t max_calls) {
    if (cancel_.load()) { terminal(GraphState::stopped); return 0; }
    std::size_t calls = 0;
    while (calls < max_calls) {
        // No command executes concurrently with Work. Move one closure out so
        // command reentrancy can enqueue another without holding the state lock.
        std::function<void()> command;
        {
            std::lock_guard lock(mutex_);
            if (!commands_.empty()) {
                command = std::move(commands_.front());
                commands_.erase(commands_.begin());
                ++wake_epoch_;
            }
        }
        if (command) {
            try { command(); }
            catch (...) { fail("graph command: " + current_exception()); return calls; }
        }
        if (cancel_.load()) { terminal(GraphState::stopped); return calls; }
        std::uint64_t observed_epoch;
        {
            std::lock_guard lock(mutex_);
            observed_epoch = wake_epoch_;
        }
        Instance* chosen = nullptr;
        // Propagate abandoned subscriptions to a fixed point before deciding
        // whether the closed graph is stalled. A finish late in one traversal
        // can release a producer inspected near its beginning.
        bool propagated;
        do {
            propagated = false;
            for (auto& node : instances_) {
                const auto& outputs = node->context.outputs_;
                const bool connected = std::any_of(outputs.begin(), outputs.end(), [](const auto* p) { return p; });
                if (!node->finished && connected &&
                    std::all_of(outputs.begin(), outputs.end(), [](const auto* p) { return !p || p->consumer_closed; })) {
                    finish(*node);
                    propagated = true;
                }
            }
        } while (propagated);
        for (std::size_t searched = 0; searched < instances_.size(); ++searched) {
            auto& candidate = *instances_[cursor_];
            cursor_ = (cursor_ + 1) % instances_.size();
            if (ready(candidate)) { chosen = &candidate; break; }
        }
        if (!chosen) {
            idle_epoch_ = observed_epoch;
            if (std::all_of(instances_.begin(), instances_.end(), [](const auto& p) { return p->finished; })) {
                terminal(GraphState::completed);
            } else {
                bool asynchronous = false;
                std::ostringstream blocked;
                for (const auto& p : instances_) {
                    if (p->finished) continue;
                    blocked << ' ' << specs_[p->id].id << '[';
                    for (std::size_t i = 0; i < p->context.inputs_.size(); ++i) {
                        const auto* c = p->context.inputs_[i];
                        blocked << " in:" << specs_[p->id].inputs[i].id << '=' << (c ? c->count : 0);
                    }
                    for (std::size_t i = 0; i < p->context.outputs_.size(); ++i) {
                        const auto* c = p->context.outputs_[i];
                        blocked << " out:" << specs_[p->id].outputs[i].id << '=' << (c ? c->available() : 0);
                    }
                    blocked << ']';
                    for (const auto& w : p->result.waits)
                        asynchronous |= w.kind == WaitCondition::Kind::external || w.kind == WaitCondition::Kind::timer;
                }
                {
                    std::lock_guard lock(mutex_);
                    asynchronous |= !commands_.empty();
                }
                if (!asynchronous) fail("graph stalled; blocking ports:" + blocked.str());
            }
            return calls;
        }
        auto& instance = *chosen;
        auto& ctx = instance.context;
        auto& result = instance.result;
        std::fill(result.consumed.begin(), result.consumed.end(), 0);
        std::fill(result.produced.begin(), result.produced.end(), 0);
        std::fill(result.close_outputs.begin(), result.close_outputs.end(), false);
        std::fill(ctx.taken_.begin(), ctx.taken_.end(), 0);
        result.waits.clear(); result.error.clear(); result.state_changed = false;
        result.status = WorkStatus::waiting;
        {
            std::lock_guard lock(mutex_);
            instance.wake_epoch = wake_epoch_;
        }
        for (std::size_t i = 0; i < ctx.inputs_.size(); ++i)
            instance.input_revisions[i] = ctx.inputs_[i] ? ctx.inputs_[i]->revision : 0;
        for (std::size_t i = 0; i < ctx.outputs_.size(); ++i)
            instance.output_revisions[i] = ctx.outputs_[i] ? ctx.outputs_[i]->revision : 0;
        try {
            for (auto* p : ctx.inputs_) if (p) p->compact();
            for (auto* p : ctx.outputs_) if (p) p->compact();
            instance.block->work(ctx, result);
            ++calls;
            if (cancel_.load()) {
                for (auto* p : ctx.outputs_) if (p) p->rollback();
                terminal(GraphState::stopped);
                return calls;
            }
            if (result.consumed.size() != ctx.inputs_.size() || result.produced.size() != ctx.outputs_.size() ||
                result.close_outputs.size() != ctx.outputs_.size())
                throw std::runtime_error("Work resized port count arrays");
            if (result.status == WorkStatus::error)
                throw std::runtime_error(result.error.empty() ? "Work reported error" : result.error);
            if (result.status != WorkStatus::progress && result.status != WorkStatus::waiting &&
                result.status != WorkStatus::finished)
                throw std::runtime_error("Work returned an invalid status");
            std::uint64_t consumed = 0, produced = 0;
            bool progress = result.state_changed || result.status == WorkStatus::finished;
            for (std::size_t i = 0; i < ctx.inputs_.size(); ++i) {
                const auto* p = ctx.inputs_[i];
                if (result.consumed[i] > (p ? p->count : 0) || result.consumed[i] < ctx.taken_[i])
                    throw std::runtime_error("input " + specs_[instance.id].inputs[i].id + ": invalid consumed prefix");
                consumed += result.consumed[i];
            }
            for (std::size_t i = 0; i < ctx.outputs_.size(); ++i) {
                const auto* p = ctx.outputs_[i];
                const auto offered = p && !p->producer_closed && !p->consumer_closed ? p->available() : 0;
                if (result.produced[i] > offered || (p && !p->trivial() && result.produced[i] != p->staged) ||
                    (p && p->staged > result.produced[i]))
                    throw std::runtime_error("output " + specs_[instance.id].outputs[i].id + ": invalid produced/constructed count");
                produced += result.produced[i];
                progress |= result.close_outputs[i] && p && !p->producer_closed;
            }
            for (const auto& w : result.waits) {
                if (w.kind != WaitCondition::Kind::input && w.kind != WaitCondition::Kind::output &&
                    w.kind != WaitCondition::Kind::external && w.kind != WaitCondition::Kind::timer)
                    throw std::runtime_error("waiting condition has an invalid kind");
                if ((w.kind == WaitCondition::Kind::input && w.port >= ctx.inputs_.size()) ||
                    (w.kind == WaitCondition::Kind::output && w.port >= ctx.outputs_.size()))
                    throw std::runtime_error("waiting condition names invalid port");
            }
            progress |= consumed || produced;
            if (result.status == WorkStatus::progress && !progress)
                throw std::runtime_error("Work reported progress without items or state change");
            // Publish before consuming: a seeded self-edge can offer both leases
            // in one Work call, and its original tail must stay correctly based.
            for (std::size_t i = 0; i < ctx.outputs_.size(); ++i) {
                if (auto* p = ctx.outputs_[i]) {
                    p->publish(result.produced[i]);
                    if (result.close_outputs[i] && !p->producer_closed) { p->producer_closed = true; ++p->revision; }
                }
            }
            for (std::size_t i = 0; i < ctx.inputs_.size(); ++i)
                if (auto* p = ctx.inputs_[i]) p->consume(result.consumed[i]);
            {
                std::lock_guard lock(mutex_);
                ++snapshot_.work_calls;
                snapshot_.items_consumed += consumed;
                snapshot_.items_produced += produced;
            }
            if (result.status == WorkStatus::finished) finish(instance);
            else {
                instance.waiting = result.status == WorkStatus::waiting;
            }
        } catch (...) {
            for (auto* p : ctx.outputs_) if (p) p->rollback();
            fail(specs_[instance.id].id + " Work: " + current_exception());
            return calls;
        }
    }
    return calls;
}

std::size_t Graph::step(std::size_t max_calls) {
    std::lock_guard execution(execution_mutex_);
    {
        std::lock_guard lock(mutex_);
        if (mode_ != RunMode::cooperative || worker_.joinable())
            throw std::logic_error("step requires a cooperative graph");
        if (snapshot_.state != GraphState::running && snapshot_.state != GraphState::stopping) return 0;
    }
    return turn(max_calls);
}

void Graph::worker_loop() {
    for (;;) {
        std::size_t calls;
        {
            std::lock_guard execution(execution_mutex_);
            {
                std::lock_guard lock(mutex_);
                if (snapshot_.state != GraphState::running && snapshot_.state != GraphState::stopping) return;
            }
            calls = turn(1);
        }
        if (calls) continue;
        std::unique_lock lock(mutex_);
        if (snapshot_.state != GraphState::running && snapshot_.state != GraphState::stopping) return;
        const auto epoch = idle_epoch_;
        auto deadline = std::chrono::steady_clock::time_point::max();
        for (const auto& p : instances_)
            if (!p->finished) for (const auto& w : p->result.waits)
                if (w.kind == WaitCondition::Kind::timer) deadline = std::min(deadline, w.deadline);
        const auto wake = [&] { return cancel_.load() || wake_epoch_ != epoch || !commands_.empty(); };
        if (deadline == std::chrono::steady_clock::time_point::max()) cv_.wait(lock, wake);
        else cv_.wait_until(lock, deadline, wake);
    }
}

void Graph::request_stop() noexcept {
    std::lock_guard lock(mutex_);
    if (snapshot_.state == GraphState::running || snapshot_.state == GraphState::starting) {
        cancel_.store(true);
        snapshot_.state = GraphState::stopping;
        ++snapshot_.generation;
        cv_.notify_all();
    }
}

void Graph::join() {
    if (worker_.joinable()) {
        if (worker_.get_id() == std::this_thread::get_id())
            throw std::logic_error("a graph cannot join/destroy itself from its Work callback");
        worker_.join();
    } else {
        std::lock_guard execution(execution_mutex_);
        bool stopping;
        {
            std::lock_guard lock(mutex_);
            stopping = snapshot_.state == GraphState::stopping;
        }
        if (stopping) terminal(GraphState::stopped);
    }
}

Snapshot Graph::snapshot() const { std::lock_guard lock(mutex_); return snapshot_; }
Generation Graph::generation() const { std::lock_guard lock(mutex_); return snapshot_.generation; }
bool Graph::wake(Generation generation) {
    std::lock_guard lock(mutex_);
    if (snapshot_.state != GraphState::running || snapshot_.generation != generation) return false;
    ++wake_epoch_; cv_.notify_all(); return true;
}
bool Graph::post(Generation generation, std::function<void()> command) {
    if (!command) return false;
    std::lock_guard lock(mutex_);
    if (snapshot_.state != GraphState::running || snapshot_.generation != generation ||
        commands_.size() >= options_.max_pending_commands) return false;
    commands_.push_back(std::move(command)); cv_.notify_all(); return true;
}

} // namespace foundation::visual::flow
