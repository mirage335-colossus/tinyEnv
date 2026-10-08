#pragma once

#include "editor/platform/project_files.hpp"

#include <charconv>
#include <cmath>
#include <cstddef>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <variant>
#include <vector>

namespace tinyenv::json {

inline constexpr std::size_t default_max_bytes = 8 * 1024 * 1024;
inline constexpr std::size_t default_max_depth = 64;
inline constexpr std::size_t default_max_values = 100000;
inline constexpr std::size_t hard_max_depth = 256;

struct Value {
    using Object = std::map<std::string, Value>;
    using Array = std::vector<Value>;
    std::variant<std::nullptr_t, bool, double, std::string, Array, Object> data;

    Value() noexcept : data(nullptr) {}
    Value(std::nullptr_t) noexcept : data(nullptr) {}
    Value(bool value) : data(value) {}
    Value(int value) : data(static_cast<double>(value)) {}
    Value(std::size_t value) : data(static_cast<double>(value)) {}
    Value(double value) : data(value) {}
    Value(std::string value) : data(std::move(value)) {}
    Value(std::string_view value) : data(std::string(value)) {}
    Value(const char* value) : data(value ? std::string(value) : null_string()) {}
    Value(Array value) : data(std::move(value)) {}
    Value(Object value) : data(std::move(value)) {}

    [[nodiscard]] const Object& object() const { return get<Object>("object"); }
    [[nodiscard]] Object& object() { return get<Object>("object"); }
    [[nodiscard]] const Array& array() const { return get<Array>("array"); }
    [[nodiscard]] Array& array() { return get<Array>("array"); }
    [[nodiscard]] const std::string& string() const { return get<std::string>("string"); }
    [[nodiscard]] std::string& string() { return get<std::string>("string"); }
    [[nodiscard]] double number() const { return get<double>("number"); }
    [[nodiscard]] bool boolean() const { return get<bool>("boolean"); }

    [[nodiscard]] const Value* find(std::string_view key) const {
        const auto* values = std::get_if<Object>(&data);
        if (!values) return nullptr;
        const auto found = values->find(std::string(key));
        return found == values->end() ? nullptr : &found->second;
    }
    [[nodiscard]] Value* find(std::string_view key) {
        auto* values = std::get_if<Object>(&data);
        if (!values) return nullptr;
        const auto found = values->find(std::string(key));
        return found == values->end() ? nullptr : &found->second;
    }

private:
    [[noreturn]] static std::string null_string() {
        throw std::runtime_error("JSON string pointer is null");
    }
    template<class T> [[nodiscard]] const T& get(const char* name) const {
        const auto* value = std::get_if<T>(&data);
        if (!value) throw std::runtime_error(std::string("JSON value is not a ") + name);
        return *value;
    }
    template<class T> [[nodiscard]] T& get(const char* name) {
        auto* value = std::get_if<T>(&data);
        if (!value) throw std::runtime_error(std::string("JSON value is not a ") + name);
        return *value;
    }
};

namespace detail {

[[nodiscard]] inline bool digit(char ch) noexcept { return ch >= '0' && ch <= '9'; }

class Reader {
public:
    Reader(std::string_view text, std::size_t max_bytes, std::size_t max_depth,
           std::size_t max_values)
        : text_(text), max_bytes_(max_bytes), max_depth_(max_depth), max_values_(max_values) {}

    [[nodiscard]] Value read() {
        if (text_.size() > max_bytes_) fail("document exceeds byte limit");
        if (!foundation::editor::ProjectFiles::valid_utf8(text_)) fail("document is not valid UTF-8");
        auto result = value(0);
        space();
        if (position_ != text_.size()) fail("unexpected bytes after JSON value");
        return result;
    }

private:
    std::string_view text_;
    std::size_t max_bytes_, max_depth_, max_values_;
    std::size_t position_{}, values_{};

    [[noreturn]] void fail(const char* message) const {
        throw std::runtime_error(std::string("JSON at byte ") + std::to_string(position_) + ": " + message);
    }
    void space() noexcept {
        while (position_ < text_.size()) {
            const char ch = text_[position_];
            if (ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n') break;
            ++position_;
        }
    }
    [[nodiscard]] bool take(char ch) noexcept {
        space();
        if (position_ == text_.size() || text_[position_] != ch) return false;
        ++position_;
        return true;
    }
    void expect(char ch) {
        if (!take(ch)) fail("unexpected JSON punctuation");
    }
    [[nodiscard]] unsigned hex4() {
        unsigned result = 0;
        for (unsigned i = 0; i < 4; ++i) {
            if (position_ == text_.size()) fail("incomplete Unicode escape");
            const char ch = text_[position_++];
            unsigned part = 0;
            if (ch >= '0' && ch <= '9') part = static_cast<unsigned>(ch - '0');
            else if (ch >= 'a' && ch <= 'f') part = static_cast<unsigned>(ch - 'a' + 10);
            else if (ch >= 'A' && ch <= 'F') part = static_cast<unsigned>(ch - 'A' + 10);
            else fail("invalid Unicode escape");
            result = (result << 4) | part;
        }
        return result;
    }
    static void append_codepoint(std::string& out, unsigned codepoint) {
        if (codepoint <= 0x7f) out.push_back(static_cast<char>(codepoint));
        else if (codepoint <= 0x7ff) {
            out.push_back(static_cast<char>(0xc0 | (codepoint >> 6)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
        } else if (codepoint <= 0xffff) {
            out.push_back(static_cast<char>(0xe0 | (codepoint >> 12)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
        } else {
            out.push_back(static_cast<char>(0xf0 | (codepoint >> 18)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3f)));
        }
    }
    [[nodiscard]] std::string string() {
        expect('"');
        std::string out;
        while (position_ < text_.size()) {
            const auto ch = static_cast<unsigned char>(text_[position_++]);
            if (ch == '"') return out;
            if (ch < 0x20) fail("unescaped control byte in JSON string");
            if (ch != '\\') {
                out.push_back(static_cast<char>(ch));
                continue;
            }
            if (position_ == text_.size()) fail("incomplete JSON escape");
            switch (text_[position_++]) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'b': out.push_back('\b'); break;
            case 'f': out.push_back('\f'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            case 'u': {
                unsigned codepoint = hex4();
                if (codepoint >= 0xd800 && codepoint <= 0xdbff) {
                    if (text_.size() - position_ < 2 || text_[position_] != '\\' || text_[position_ + 1] != 'u')
                        fail("high surrogate lacks low surrogate");
                    position_ += 2;
                    const unsigned low = hex4();
                    if (low < 0xdc00 || low > 0xdfff) fail("invalid low surrogate");
                    codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + (low - 0xdc00);
                } else if (codepoint >= 0xdc00 && codepoint <= 0xdfff) {
                    fail("unpaired low surrogate");
                }
                if (codepoint == 0) fail("NUL is not allowed in application text");
                append_codepoint(out, codepoint);
                break;
            }
            default: fail("invalid JSON escape");
            }
        }
        fail("unterminated JSON string");
    }
    [[nodiscard]] Value number() {
        const std::size_t start = position_;
        if (text_[position_] == '-') ++position_;
        if (position_ == text_.size() || !digit(text_[position_])) fail("expected a number");
        if (text_[position_] == '0') {
            ++position_;
            if (position_ < text_.size() && digit(text_[position_])) fail("number has a leading zero");
        } else {
            while (position_ < text_.size() && digit(text_[position_])) ++position_;
        }
        if (position_ < text_.size() && text_[position_] == '.') {
            ++position_;
            if (position_ == text_.size() || !digit(text_[position_])) fail("fraction lacks digits");
            while (position_ < text_.size() && digit(text_[position_])) ++position_;
        }
        if (position_ < text_.size() && (text_[position_] == 'e' || text_[position_] == 'E')) {
            ++position_;
            if (position_ < text_.size() && (text_[position_] == '+' || text_[position_] == '-')) ++position_;
            if (position_ == text_.size() || !digit(text_[position_])) fail("exponent lacks digits");
            while (position_ < text_.size() && digit(text_[position_])) ++position_;
        }
        double out = 0;
        const char* const end = text_.data() + position_;
        const auto parsed = std::from_chars(text_.data() + start, end, out, std::chars_format::general);
        if (parsed.ec != std::errc{} || parsed.ptr != end || !std::isfinite(out))
            fail("number is outside supported finite range");
        return Value(out);
    }
    [[nodiscard]] Value value(std::size_t depth) {
        space();
        if (depth > max_depth_) fail("JSON nesting exceeds limit");
        if (values_ == max_values_) fail("JSON value count exceeds limit");
        ++values_;
        if (position_ == text_.size()) fail("expected a JSON value");
        const char ch = text_[position_];
        if (ch == '"') return Value(string());
        if (ch == '{') {
            ++position_;
            Value::Object out;
            if (take('}')) return Value(std::move(out));
            do {
                auto key = string();
                if (out.find(key) != out.end()) fail("duplicate JSON object key");
                expect(':');
                out.emplace(std::move(key), child(depth));
                if (take('}')) return Value(std::move(out));
            } while (take(','));
            fail("expected ',' or '}'");
        }
        if (ch == '[') {
            ++position_;
            Value::Array out;
            if (take(']')) return Value(std::move(out));
            do {
                out.push_back(child(depth));
                if (take(']')) return Value(std::move(out));
            } while (take(','));
            fail("expected ',' or ']'");
        }
        if (ch == '-' || digit(ch)) return number();
        if (text_.substr(position_, 4) == "true") { position_ += 4; return Value(true); }
        if (text_.substr(position_, 5) == "false") { position_ += 5; return Value(false); }
        if (text_.substr(position_, 4) == "null") { position_ += 4; return Value(nullptr); }
        fail("expected a JSON value");
    }
    [[nodiscard]] Value child(std::size_t depth) {
        // Check before incrementing, including a caller-supplied SIZE_MAX limit.
        if (depth == max_depth_) fail("JSON nesting exceeds limit");
        return value(depth + 1);
    }
};

class Writer {
public:
    Writer(std::size_t max_bytes, std::size_t max_depth, std::size_t max_values)
        : max_bytes_(max_bytes), max_depth_(max_depth), max_values_(max_values) {}

    [[nodiscard]] std::string write(const Value& input) {
        value(input, 0);
        return std::move(out_);
    }

private:
    std::string out_;
    std::size_t max_bytes_, max_depth_, max_values_;
    std::size_t values_{};

    [[noreturn]] static void fail(const char* message) { throw std::runtime_error(message); }
    void append(std::string_view text) {
        if (text.size() > max_bytes_ - out_.size()) fail("JSON output exceeds byte limit");
        out_.append(text);
    }
    void append(char ch) {
        if (out_.size() == max_bytes_) fail("JSON output exceeds byte limit");
        out_.push_back(ch);
    }
    void string(std::string_view text) {
        if (text.size() > max_bytes_ - out_.size()) fail("JSON output exceeds byte limit");
        if (text.find('\0') != std::string_view::npos) fail("NUL is not allowed in application text");
        if (!foundation::editor::ProjectFiles::valid_utf8(text)) fail("JSON string is not valid UTF-8");
        append('"');
        static constexpr char hex[] = "0123456789abcdef";
        for (const auto byte : text) {
            const auto ch = static_cast<unsigned char>(byte);
            switch (ch) {
            case '"': append("\\\""); break;
            case '\\': append("\\\\"); break;
            case '\b': append("\\b"); break;
            case '\f': append("\\f"); break;
            case '\n': append("\\n"); break;
            case '\r': append("\\r"); break;
            case '\t': append("\\t"); break;
            default:
                if (ch < 0x20) {
                    const char escaped[] = {'\\', 'u', '0', '0', hex[ch >> 4], hex[ch & 0xf]};
                    append(std::string_view(escaped, sizeof(escaped)));
                } else append(static_cast<char>(ch));
            }
        }
        append('"');
    }
    void number(double input) {
        if (!std::isfinite(input)) fail("JSON number is not finite");
        char buffer[128];
        // Canonicalize negative zero and keep every finite double round-trippable.
        const auto written = std::to_chars(buffer, buffer + sizeof(buffer), input == 0 ? 0.0 : input,
                                           std::chars_format::general, std::numeric_limits<double>::max_digits10);
        if (written.ec != std::errc{}) fail("cannot format JSON number");
        append(std::string_view(buffer, static_cast<std::size_t>(written.ptr - buffer)));
    }
    void value(const Value& input, std::size_t depth) {
        if (depth > max_depth_) fail("JSON nesting exceeds limit");
        if (values_ == max_values_) fail("JSON value count exceeds limit");
        ++values_;
        if (std::holds_alternative<std::nullptr_t>(input.data)) append("null");
        else if (const auto* boolean = std::get_if<bool>(&input.data)) append(*boolean ? "true" : "false");
        else if (const auto* numeric = std::get_if<double>(&input.data)) number(*numeric);
        else if (const auto* text = std::get_if<std::string>(&input.data)) string(*text);
        else if (const auto* array = std::get_if<Value::Array>(&input.data)) {
            append('[');
            bool first = true;
            for (const auto& element : *array) {
                if (!first) append(',');
                first = false;
                child(element, depth);
            }
            append(']');
        } else if (const auto* object = std::get_if<Value::Object>(&input.data)) {
            append('{');
            bool first = true;
            for (const auto& [key, element] : *object) {
                if (!first) append(',');
                first = false;
                string(key);
                append(':');
                child(element, depth);
            }
            append('}');
        } else fail("JSON value has no active type");
    }
    void child(const Value& input, std::size_t depth) {
        if (depth == max_depth_) fail("JSON nesting exceeds limit");
        value(input, depth + 1);
    }
};

} // namespace detail

// The root has depth zero; arrays, objects and scalar children each count as a
// value, while object keys do not. Strings are UTF-8 application text without
// NUL. Numbers must fit a finite double (overflow and underflow fail).
// Custom depth limits cannot exceed hard_max_depth, bounding recursive stack use.
[[nodiscard]] inline Value parse(std::string_view text,
                                 std::size_t max_bytes = default_max_bytes,
                                 std::size_t max_depth = default_max_depth,
                                 std::size_t max_values = default_max_values) {
    if (max_depth > hard_max_depth) throw std::runtime_error("JSON depth limit exceeds supported maximum");
    return detail::Reader(text, max_bytes, max_depth, max_values).read();
}

// Object keys follow std::map order. Output has no optional whitespace, escapes
// control bytes, and uses the same limits/text policy as parse.
[[nodiscard]] inline std::string stringify(const Value& value,
                                           std::size_t max_bytes = default_max_bytes,
                                           std::size_t max_depth = default_max_depth,
                                           std::size_t max_values = default_max_values) {
    if (max_depth > hard_max_depth) throw std::runtime_error("JSON depth limit exceeds supported maximum");
    return detail::Writer(max_bytes, max_depth, max_values).write(value);
}

} // namespace tinyenv::json
