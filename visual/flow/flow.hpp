#pragma once

// Optional, GUI-independent C++20 stream composition. No application target links
// this module unless its composition root chooses to do so.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <mutex>
#include <span>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <typeindex>
#include <utility>
#include <vector>

namespace foundation::visual::flow {

using NodeId = std::size_t;
using Generation = std::uint64_t;

namespace detail {
class Channel {
public:
    virtual ~Channel() = default;
    virtual std::type_index type() const noexcept = 0;
    virtual const void* read_data() const noexcept = 0;
    virtual void* write_data() noexcept = 0;
    virtual void compact() = 0;
    virtual void consume(std::size_t) = 0;
    virtual void publish(std::size_t) = 0;
    virtual void rollback() noexcept = 0;
    virtual void discard() noexcept = 0;
    virtual bool trivial() const noexcept = 0;
    std::size_t capacity{}, head{}, count{}, staged{};
    std::uint64_t revision{};
    bool producer_closed{}, consumer_closed{};
    std::size_t available() const noexcept { return consumer_closed ? 0 : capacity - head - count; }
};

template<class T> inline constexpr bool span_output =
    std::is_trivially_copyable_v<T> && std::is_default_constructible_v<T> && std::is_copy_assignable_v<T>;

template<class T> class TypedChannel final : public Channel {
public:
    explicit TypedChannel(std::size_t n) {
        static_assert(std::is_object_v<T> && !std::is_const_v<T> && !std::is_volatile_v<T>,
                      "stream types are unqualified object types");
        static_assert(std::is_move_constructible_v<T>, "stream items must be move constructible");
        static_assert(std::is_nothrow_destructible_v<T>, "stream items require non-throwing destruction");
        capacity = n;
        data_ = allocator_.allocate(n);
        try {
            if constexpr (span_output<T>) {
                for (; initialized_ < n; ++initialized_) std::construct_at(data_ + initialized_);
            } else {
                live_.resize(n, 0);
            }
        } catch (...) {
            for (std::size_t i = 0; i < initialized_; ++i) std::destroy_at(data_ + i);
            allocator_.deallocate(data_, n);
            throw;
        }
    }
    ~TypedChannel() override {
        if constexpr (span_output<T>) {
            for (std::size_t i = 0; i < initialized_; ++i) std::destroy_at(data_ + i);
        } else {
            for (std::size_t i = 0; i < capacity; ++i) if (live_[i]) std::destroy_at(data_ + i);
        }
        allocator_.deallocate(data_, capacity);
    }
    std::type_index type() const noexcept override { return typeid(T); }
    const void* read_data() const noexcept override { return data_ + head; }
    void* write_data() noexcept override { return data_ + head + count; }
    bool trivial() const noexcept override { return span_output<T>; }
    void compact() override {
        if (!head) return;
        if constexpr (span_output<T>) {
            // Forward copy is safe: the destination precedes the source.
            for (std::size_t i = 0; i < count; ++i) data_[i] = data_[head + i];
        } else {
            for (std::size_t i = 0; i < count; ++i) {
                std::construct_at(data_ + i, std::move(data_[head + i]));
                live_[i] = 1;
                std::destroy_at(data_ + head + i);
                live_[head + i] = 0;
            }
        }
        head = 0;
    }
    void consume(std::size_t n) override {
        if constexpr (!span_output<T>) {
            for (std::size_t i = 0; i < n; ++i) {
                std::destroy_at(data_ + head + i);
                live_[head + i] = 0;
            }
        }
        head += n;
        count -= n;
        if (!count && !staged) head = 0;
        if (n) ++revision;
    }
    void publish(std::size_t n) override {
        count += n;
        staged = 0;
        if (n) ++revision;
    }
    template<class... Args> T& emplace(Args&&... args) {
        if (staged >= available()) throw std::out_of_range("output lease exhausted");
        const auto index = head + count + staged;
        if constexpr (span_output<T>) {
            data_[index] = T(std::forward<Args>(args)...);
        } else {
            std::construct_at(data_ + index, std::forward<Args>(args)...);
            live_[index] = 1;
        }
        ++staged;
        return data_[index];
    }
    T take(std::size_t index) {
        if (index >= count) throw std::out_of_range("input lease exhausted");
        return T(std::move(data_[head + index]));
    }
    void rollback() noexcept override {
        if constexpr (!span_output<T>) {
            for (std::size_t i = 0; i < staged; ++i) {
                const auto index = head + count + i;
                if (live_[index]) { std::destroy_at(data_ + index); live_[index] = 0; }
            }
        }
        staged = 0;
    }
    void discard() noexcept override {
        rollback();
        if constexpr (!span_output<T>) {
            for (std::size_t i = 0; i < capacity; ++i) {
                if (live_[i]) { std::destroy_at(data_ + i); live_[i] = 0; }
            }
        }
        count = head = 0;
        ++revision;
    }
private:
    std::allocator<T> allocator_;
    T* data_{};
    std::size_t initialized_{};
    std::vector<unsigned char> live_;
};
} // namespace detail

struct PortSpec {
    std::string id;
    std::type_index type{typeid(void)};
    std::size_t item_bytes{}, minimum_batch{1};
    bool optional{};
    std::function<std::unique_ptr<detail::Channel>(std::size_t)> make_channel;

    template<class T> static PortSpec typed(std::string id, std::size_t minimum_batch = 1,
                                           bool optional = false) {
        return {std::move(id), typeid(T), sizeof(T) + (detail::span_output<T> ? 0 : 1),
                minimum_batch, optional, [](std::size_t n) {
                    return std::make_unique<detail::TypedChannel<T>>(n);
                }};
    }
};

enum class WorkStatus { progress, waiting, finished, error };
struct WaitCondition {
    enum class Kind { input, output, external, timer };
    Kind kind{Kind::external};
    std::size_t port{};
    std::chrono::steady_clock::time_point deadline{};
    static WaitCondition input(std::size_t i) { return {Kind::input, i, {}}; }
    static WaitCondition output(std::size_t i) { return {Kind::output, i, {}}; }
    static WaitCondition external() { return {}; }
    static WaitCondition timer(std::chrono::steady_clock::time_point t) { return {Kind::timer, 0, t}; }
};

// Runtime initializes every count to zero before Work. Never resize these lists.
// A nontrivial output's produced count must equal writer().size(). Taken input
// items must be covered by the consumed prefix. Exceptions fail the whole graph.
struct WorkResult {
    std::vector<std::size_t> consumed, produced;
    std::vector<bool> close_outputs;
    WorkStatus status{WorkStatus::waiting};
    std::vector<WaitCondition> waits;
    std::string error;
    bool state_changed{}; // Explicit progress in block-owned state, without items.
};

template<class T> class OutputWriter {
public:
    template<class... Args> T& emplace(Args&&... args) {
        if (!channel_) throw std::out_of_range("output is closed or disconnected");
        return channel_->emplace(std::forward<Args>(args)...);
    }
    std::size_t size() const noexcept { return channel_ ? channel_->staged : 0; }
    std::size_t capacity() const noexcept { return channel_ ? channel_->available() : 0; }
private:
    explicit OutputWriter(detail::TypedChannel<T>* p) : channel_(p) {}
    detail::TypedChannel<T>* channel_{};
    friend class WorkContext;
};

class WorkContext {
public:
    template<class T> std::span<const T> input(std::size_t port) const {
        auto* p = checked<T>(inputs_, port);
        return p ? std::span<const T>(static_cast<const T*>(p->read_data()), p->count)
                 : std::span<const T>{};
    }
    template<class T> std::span<T> output(std::size_t port) {
        static_assert(detail::span_output<T>, "object streams use writer<T>().emplace()");
        auto* p = checked<T>(outputs_, port);
        return p && !p->producer_closed && !p->consumer_closed
             ? std::span<T>(static_cast<T*>(p->write_data()), p->available()) : std::span<T>{};
    }
    template<class T> OutputWriter<T> writer(std::size_t port) {
        auto* p = checked<T>(outputs_, port);
        return OutputWriter<T>(p && !p->producer_closed && !p->consumer_closed
                               ? static_cast<detail::TypedChannel<T>*>(p) : nullptr);
    }
    template<class T> T take_next(std::size_t port) {
        auto* p = checked<T>(inputs_, port);
        if (!p) throw std::out_of_range("input is disconnected");
        auto value = static_cast<detail::TypedChannel<T>*>(p)->take(taken_.at(port));
        ++taken_[port];
        return value;
    }
    bool input_finished(std::size_t port) const;
    bool input_closed(std::size_t port) const;
    bool output_closed(std::size_t port) const;
    bool cancelled() const noexcept { return cancel_ && cancel_->load(); }
    Generation generation() const noexcept { return generation_; }
    std::size_t input_count() const noexcept { return inputs_.size(); }
    std::size_t output_count() const noexcept { return outputs_.size(); }
private:
    template<class T> static detail::Channel* checked(const std::vector<detail::Channel*>& ports,
                                                     std::size_t index) {
        auto* p = ports.at(index);
        if (p && p->type() != typeid(T)) throw std::invalid_argument("Work port C++ type mismatch");
        return p;
    }
    std::vector<detail::Channel*> inputs_, outputs_;
    std::vector<std::size_t> taken_;
    const std::atomic<bool>* cancel_{};
    Generation generation_{};
    friend class Graph;
};

class Block {
public:
    virtual ~Block() = default;
    virtual void work(WorkContext&, WorkResult&) = 0;
};
std::unique_ptr<Block> make_block(std::function<void(WorkContext&, WorkResult&)>);
template<class Function> std::unique_ptr<Block> make_block(Function&& function) {
    using Callable = std::decay_t<Function>;
    static_assert(std::is_invocable_r_v<void, Callable&, WorkContext&, WorkResult&>, "invalid Work callable");
    class CallableBlock final : public Block {
    public:
        explicit CallableBlock(Callable value) : callable_(std::move(value)) {}
        void work(WorkContext& context, WorkResult& result) override { std::invoke(callable_, context, result); }
    private:
        Callable callable_;
    };
    if constexpr (std::is_pointer_v<Callable>)
        if (!function) throw std::invalid_argument("empty Work function");
    return std::make_unique<CallableBlock>(std::forward<Function>(function));
}

struct BlockSpec {
    std::string id;
    std::vector<PortSpec> inputs, outputs;
    std::function<std::unique_ptr<Block>()> factory;
    // The factory owns initialized delay/state. Every cycle must cross such a
    // block; declaring one does not guarantee that an algorithm cannot deadlock.
    bool breaks_cycle{};
};

enum class RunMode { worker, cooperative };
enum class GraphState { stopped, starting, running, stopping, completed, failed };
struct GraphOptions {
    std::size_t max_nodes{1024}, max_ports{8192}, max_queue_bytes{64 * 1024 * 1024};
    std::size_t max_pending_commands{256};
};
struct Snapshot {
    GraphState state{GraphState::stopped};
    Generation generation{};
    std::string error;
    std::uint64_t work_calls{}, items_consumed{}, items_produced{};
};

// Only setup/add/connect may be called by the composition owner, after join().
// request_stop(), snapshot(), generation(), wake() and post() are thread-safe.
// Work borrows spans only until it returns. Work must return cooperatively; stop
// never detaches an executing block. Factories recreate state on each start.
class Graph {
public:
    explicit Graph(GraphOptions = {});
    ~Graph();
    Graph(const Graph&) = delete;
    Graph& operator=(const Graph&) = delete;
    NodeId add(BlockSpec);
    void connect(NodeId from, std::size_t output, NodeId to, std::size_t input,
                 std::size_t capacity = 256);
    void validate() const;
    void start(RunMode = RunMode::worker);
    std::size_t step(std::size_t max_calls = 1); // Cooperative mode only.
    void request_stop() noexcept;
    void join();
    Snapshot snapshot() const;
    Generation generation() const;
    bool wake(Generation); // Signals an external wait; rejects stale generations.
    // Owned commands run between Work calls on the graph executor. Rejection is
    // explicit (stale/stopping/full). An accepted command exception fails graph.
    bool post(Generation, std::function<void()>);
private:
    struct Edge;
    struct Instance;
    GraphOptions options_;
    std::vector<BlockSpec> specs_;
    std::vector<std::unique_ptr<Edge>> edges_;
    std::vector<std::unique_ptr<Instance>> instances_;
    mutable std::mutex mutex_;
    std::mutex execution_mutex_;
    std::condition_variable cv_;
    Snapshot snapshot_;
    std::atomic<bool> cancel_{};
    std::thread worker_;
    RunMode mode_{RunMode::cooperative};
    std::size_t cursor_{};
    std::uint64_t wake_epoch_{};
    std::uint64_t idle_epoch_{};
    std::vector<std::function<void()>> commands_;
    void editable() const;
    void setup();
    bool ready(const Instance&) const;
    std::size_t turn(std::size_t);
    void finish(Instance&);
    void fail(std::string);
    void terminal(GraphState);
    void destroy_runtime() noexcept;
    void worker_loop();
};

} // namespace foundation::visual::flow
