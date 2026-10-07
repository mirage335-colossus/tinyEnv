#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace foundation {

using RecordId = std::uint64_t;

struct Record {
    RecordId id;
    std::string text;
    bool operator==(const Record&) const = default;
};

// An owning, bounded collection. Callers serialize access to each instance.
// IDs never change or get reused. Returned values cannot mutate stored state.
class Store {
public:
    static constexpr std::size_t max_text_bytes = 256;
    static constexpr std::size_t max_capacity = 4096;

    explicit Store(std::size_t capacity = 64);
    // Text is 1..256 printable ASCII bytes; duplicates are allowed.
    // Invalid input throws invalid_argument; a full store throws length_error.
    // A failed operation leaves the collection and next ID unchanged.
    RecordId add(std::string_view text);
    bool update(RecordId id, std::string_view text);
    bool erase(RecordId id);
    [[nodiscard]] std::optional<Record> get(RecordId id) const;
    [[nodiscard]] std::vector<Record> snapshot() const;
    [[nodiscard]] std::size_t size() const noexcept;

private:
    static void validate(std::string_view text);
    std::size_t capacity_;
    RecordId next_id_ = 1;
    std::vector<Record> records_;
};

} // namespace foundation
