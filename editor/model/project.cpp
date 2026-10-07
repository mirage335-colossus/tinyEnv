#include "project.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <functional>
#include <limits>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <variant>

namespace foundation::editor {
namespace {
bool ascii_letter(char ch) { return (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z'); }
bool ascii_digit(char ch) { return ch >= '0' && ch <= '9'; }
bool word_start(char ch) { return ascii_letter(ch) || ch == '_'; }
bool word_continue(char ch) { return word_start(ch) || ascii_digit(ch); }
bool bad_text(std::string_view text) { return text.find('\0') != std::string_view::npos || !valid_utf8(text); }
bool valid_type(std::string_view value) {
    if (value.empty() || value.size() > 512 || !word_start(value.front())) return false;
    int depth = 0;
    for (const char ch : value) {
        if (word_continue(ch) || ch == ':' || ch == ',' || ch == '*' || ch == '&' || ch == ' ') continue;
        if (ch == '<') { ++depth; continue; }
        if (ch == '>' && depth > 0) { --depth; continue; }
        return false;
    }
    return depth == 0;
}
struct IssueList {
    std::vector<Diagnostic> data;
    void add(std::string path, std::string message, Severity severity = Severity::error) {
        if (data.size() < 256) data.push_back({severity, std::move(path), std::move(message), 0, 0});
        else if (severity == Severity::error && !has_errors(data)) data.back() = {severity, std::move(path), std::move(message), 0, 0};
    }
};

struct Value {
    using Array = std::vector<Value>;
    using Object = std::map<std::string, Value>;
    std::variant<std::monostate, bool, double, std::string, Array, Object> data;
};
struct ParseError : std::runtime_error {
    std::size_t position;
    ParseError(std::size_t pos, std::string text) : std::runtime_error(std::move(text)), position(pos) {}
};
class Reader {
public:
    Reader(std::string_view bytes, const Limits& limits) : bytes_(bytes), limits_(limits) {}
    Value read() {
        if (bytes_.size() > limits_.file_bytes) fail("document exceeds file byte limit");
        if (!valid_utf8(bytes_)) fail("document is not valid UTF-8");
        Value value = item(0);
        space();
        if (pos_ != bytes_.size()) fail("unexpected bytes after JSON value");
        return value;
    }
private:
    std::string_view bytes_;
    const Limits& limits_;
    std::size_t pos_ = 0, values_ = 0;
    [[noreturn]] void fail(std::string text) const { throw ParseError(pos_, std::move(text)); }
    void space() { while (pos_ < bytes_.size() && (bytes_[pos_] == ' ' || bytes_[pos_] == '\r' || bytes_[pos_] == '\n' || bytes_[pos_] == '\t')) ++pos_; }
    bool take(char ch) { space(); if (pos_ < bytes_.size() && bytes_[pos_] == ch) { ++pos_; return true; } return false; }
    void expect(char ch) { if (!take(ch)) fail(std::string("expected '") + ch + "'"); }
    unsigned hex4() {
        unsigned result = 0;
        for (unsigned i = 0; i < 4; ++i) {
            if (pos_ == bytes_.size()) fail("incomplete Unicode escape");
            const char ch = bytes_[pos_++];
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
            out.push_back(static_cast<char>(0x80 | (codepoint & 63)));
        } else if (codepoint <= 0xffff) {
            out.push_back(static_cast<char>(0xe0 | (codepoint >> 12)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 63)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 63)));
        } else {
            out.push_back(static_cast<char>(0xf0 | (codepoint >> 18)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 63)));
            out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 63)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 63)));
        }
    }
    std::string string() {
        expect('"');
        std::string out;
        while (pos_ < bytes_.size()) {
            const unsigned char ch = static_cast<unsigned char>(bytes_[pos_++]);
            if (ch == '"') return out;
            if (ch < 0x20) fail("unescaped control byte in JSON string");
            if (ch != '\\') out.push_back(static_cast<char>(ch));
            else {
                if (pos_ == bytes_.size()) fail("incomplete escape");
                const char escaped = bytes_[pos_++];
                switch (escaped) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case '/': out += '/'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                case 'u': {
                    unsigned codepoint = hex4();
                    if (codepoint >= 0xd800 && codepoint <= 0xdbff) {
                        if (bytes_.size() - pos_ < 2 || bytes_[pos_] != '\\' || bytes_[pos_ + 1] != 'u') fail("high surrogate lacks low surrogate");
                        pos_ += 2;
                        const unsigned low = hex4();
                        if (low < 0xdc00 || low > 0xdfff) fail("invalid low surrogate");
                        codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + low - 0xdc00;
                    } else if (codepoint >= 0xdc00 && codepoint <= 0xdfff) fail("unpaired low surrogate");
                    if (codepoint == 0) fail("NUL is not allowed in project text");
                    append_codepoint(out, codepoint);
                    break;
                }
                default: fail("invalid JSON escape");
                }
            }
            if (out.size() > limits_.string_bytes) fail("string exceeds byte limit");
        }
        fail("unterminated JSON string");
    }
    Value number() {
        const std::size_t start = pos_;
        if (pos_ < bytes_.size() && bytes_[pos_] == '-') ++pos_;
        if (pos_ == bytes_.size() || !ascii_digit(bytes_[pos_])) fail("expected a number");
        if (bytes_[pos_] == '0') ++pos_;
        else while (pos_ < bytes_.size() && ascii_digit(bytes_[pos_])) ++pos_;
        if (pos_ < bytes_.size() && bytes_[pos_] == '.') {
            ++pos_;
            if (pos_ == bytes_.size() || !ascii_digit(bytes_[pos_])) fail("fraction lacks digits");
            while (pos_ < bytes_.size() && ascii_digit(bytes_[pos_])) ++pos_;
        }
        if (pos_ < bytes_.size() && (bytes_[pos_] == 'e' || bytes_[pos_] == 'E')) {
            ++pos_;
            if (pos_ < bytes_.size() && (bytes_[pos_] == '+' || bytes_[pos_] == '-')) ++pos_;
            if (pos_ == bytes_.size() || !ascii_digit(bytes_[pos_])) fail("exponent lacks digits");
            while (pos_ < bytes_.size() && ascii_digit(bytes_[pos_])) ++pos_;
        }
        double result = 0;
        const auto conversion = std::from_chars(bytes_.data() + start, bytes_.data() + pos_, result);
        if (conversion.ec != std::errc{} || !std::isfinite(result)) fail("number is outside supported finite range");
        return Value{result};
    }
    Value item(std::size_t depth) {
        space();
        if (depth > limits_.nesting) fail("JSON nesting exceeds limit");
        if (++values_ > limits_.json_values) fail("JSON value count exceeds limit");
        if (pos_ == bytes_.size()) fail("expected a JSON value");
        const char ch = bytes_[pos_];
        if (ch == '"') return Value{string()};
        if (ch == '{') {
            ++pos_; Value::Object out;
            if (take('}')) return Value{std::move(out)};
            do {
                auto key = string(); expect(':');
                auto value = item(depth + 1);
                if (!out.emplace(std::move(key), std::move(value)).second) fail("duplicate JSON object key");
                if (take('}')) return Value{std::move(out)};
            } while (take(','));
            fail("expected ',' or '}'");
        }
        if (ch == '[') {
            ++pos_; Value::Array out;
            if (take(']')) return Value{std::move(out)};
            do {
                out.push_back(item(depth + 1));
                if (take(']')) return Value{std::move(out)};
            } while (take(','));
            fail("expected ',' or ']'");
        }
        for (const auto& [word, value] : std::vector<std::pair<std::string_view, Value>>{{"true", Value{true}}, {"false", Value{false}}, {"null", Value{}}}) {
            if (bytes_.substr(pos_, word.size()) == word) { pos_ += word.size(); return value; }
        }
        if (ch == '-' || ascii_digit(ch)) return number();
        fail("expected a JSON value");
    }
};

class Decoder {
public:
    IssueList issues;
    Project decode(const Value& root) {
        Project project;
        const auto* obj = object(root, "$", {"schema_version", "name", "generated_directory", "cpp_namespace", "forms", "bindings", "flows", "blocks", "edges", "recipes"});
        if (!obj) return project;
        const auto version = integer(*obj, "schema_version", "$", 0);
        if (version != 1) issues.add("$.schema_version", "unsupported design schema; expected 1");
        project.schema_version = static_cast<std::uint32_t>(version);
        project.name = text(*obj, "name", "$", "Untitled");
        project.generated_directory = text(*obj, "generated_directory", "$", "generated/visual");
        project.cpp_namespace = text(*obj, "cpp_namespace", "$", "foundation::generated");
        each(*obj, "forms", "$", [&](const Value& value, const std::string& path) {
            Form form;
            if (const auto* item = object(value, path, {"id", "label", "width", "height", "controls"})) {
                form.id = text(*item, "id", path); form.label = text(*item, "label", path);
                form.width = real(*item, "width", path, 640); form.height = real(*item, "height", path, 480);
                each(*item, "controls", path, [&](const Value& child, const std::string& child_path) { form.controls.push_back(control(child, child_path)); });
            }
            project.forms.push_back(std::move(form));
        });
        each(*obj, "bindings", "$", [&](const Value& value, const std::string& path) {
            Binding binding;
            if (const auto* item = object(value, path, {"id", "event", "file", "symbol", "anchor", "header"})) {
                binding.id = text(*item, "id", path); binding.event = text(*item, "event", path, "activate");
                binding.file = text(*item, "file", path); binding.symbol = text(*item, "symbol", path);
                binding.anchor = text(*item, "anchor", path); binding.header = text(*item, "header", path);
            }
            project.bindings.push_back(std::move(binding));
        });
        each(*obj, "flows", "$", [&](const Value& value, const std::string& path) {
            Flow flow;
            if (const auto* item = object(value, path, {"id", "label"})) { flow.id = text(*item, "id", path); flow.label = text(*item, "label", path); }
            project.flows.push_back(std::move(flow));
        });
        each(*obj, "blocks", "$", [&](const Value& value, const std::string& path) {
            Block block;
            if (const auto* item = object(value, path, {"id", "label", "factory", "binding", "file", "symbol", "header", "flow", "x", "y", "inputs", "outputs", "params", "breaks_cycle"})) {
                block.id = text(*item, "id", path); block.label = text(*item, "label", path);
                block.factory = text(*item, "factory", path); block.binding = text(*item, "binding", path);
                block.file = text(*item, "file", path); block.symbol = text(*item, "symbol", path); block.header = text(*item, "header", path);
                block.flow = text(*item, "flow", path, "main"); block.x = real(*item, "x", path, 0); block.y = real(*item, "y", path, 0);
                each(*item, "inputs", path, [&](const Value& port, const std::string& p) { block.inputs.push_back(decode_port(port, p)); });
                each(*item, "outputs", path, [&](const Value& port, const std::string& p) { block.outputs.push_back(decode_port(port, p)); });
                block.params = string_map(*item, "params", path);
                block.breaks_cycle = flag(*item, "breaks_cycle", path, false);
            }
            project.blocks.push_back(std::move(block));
        });
        each(*obj, "edges", "$", [&](const Value& value, const std::string& path) {
            Edge edge;
            if (const auto* item = object(value, path, {"id", "from_block", "from_port", "to_block", "to_port", "capacity", "initial_tokens"})) {
                edge.id = text(*item, "id", path); edge.from_block = text(*item, "from_block", path); edge.from_port = text(*item, "from_port", path);
                edge.to_block = text(*item, "to_block", path); edge.to_port = text(*item, "to_port", path);
                edge.capacity = integer(*item, "capacity", path, 256); edge.initial_tokens = integer(*item, "initial_tokens", path, 0);
            }
            project.edges.push_back(std::move(edge));
        });
        each(*obj, "recipes", "$", [&](const Value& value, const std::string& path) {
            Recipe recipe;
            if (const auto* item = object(value, path, {"id", "label", "argv", "working_directory"})) {
                recipe.id = text(*item, "id", path); recipe.label = text(*item, "label", path);
                recipe.working_directory = text(*item, "working_directory", path, ".");
                each(*item, "argv", path, [&](const Value& argument, const std::string& argument_path) {
                    if (const auto* str = std::get_if<std::string>(&argument.data)) recipe.argv.push_back(*str);
                    else issues.add(argument_path, "expected a string argument");
                });
            }
            project.recipes.push_back(std::move(recipe));
        });
        return project;
    }
private:
    const Value::Object* object(const Value& value, const std::string& path, std::initializer_list<std::string_view> allowed) {
        const auto* out = std::get_if<Value::Object>(&value.data);
        if (!out) { issues.add(path, "expected an object"); return nullptr; }
        for (const auto& [key, unused] : *out) {
            (void)unused;
            if (std::find(allowed.begin(), allowed.end(), key) == allowed.end()) issues.add(path + "." + key, "unknown schema member");
        }
        return out;
    }
    const Value* lookup(const Value::Object& obj, std::string_view key) {
        const auto found = obj.find(std::string(key)); return found == obj.end() ? nullptr : &found->second;
    }
    std::string text(const Value::Object& obj, std::string_view key, const std::string& path, std::string fallback = {}) {
        const auto* value = lookup(obj, key); if (!value) return fallback;
        if (const auto* out = std::get_if<std::string>(&value->data)) return *out;
        issues.add(path + "." + std::string(key), "expected a string"); return fallback;
    }
    double real(const Value::Object& obj, std::string_view key, const std::string& path, double fallback) {
        const auto* value = lookup(obj, key); if (!value) return fallback;
        if (const auto* out = std::get_if<double>(&value->data)) return *out;
        issues.add(path + "." + std::string(key), "expected a number"); return fallback;
    }
    std::size_t integer(const Value::Object& obj, std::string_view key, const std::string& path, std::size_t fallback) {
        const double out = real(obj, key, path, static_cast<double>(fallback));
        if (out < 0 || std::floor(out) != out || out > 9007199254740991.0 || out >= static_cast<double>(std::numeric_limits<std::size_t>::max())) {
            issues.add(path + "." + std::string(key), "expected a bounded nonnegative integer"); return fallback;
        }
        return static_cast<std::size_t>(out);
    }
    bool flag(const Value::Object& obj, std::string_view key, const std::string& path, bool fallback) {
        const auto* value = lookup(obj, key); if (!value) return fallback;
        if (const auto* out = std::get_if<bool>(&value->data)) return *out;
        issues.add(path + "." + std::string(key), "expected a boolean"); return fallback;
    }
    template<class Function> void each(const Value::Object& obj, std::string_view key, const std::string& path, Function function) {
        const auto* value = lookup(obj, key); if (!value) return;
        const std::string child_path = path + "." + std::string(key);
        if (const auto* items = std::get_if<Value::Array>(&value->data)) {
            for (std::size_t i = 0; i < items->size(); ++i) function((*items)[i], child_path + "[" + std::to_string(i) + "]");
        } else issues.add(child_path, "expected an array");
    }
    std::map<std::string, std::string> string_map(const Value::Object& obj, std::string_view key, const std::string& path) {
        std::map<std::string, std::string> result;
        const auto* value = lookup(obj, key); if (!value) return result;
        const std::string child_path = path + "." + std::string(key);
        if (const auto* map = std::get_if<Value::Object>(&value->data)) {
            for (const auto& [name, child] : *map) {
                if (const auto* str = std::get_if<std::string>(&child.data)) result.emplace(name, *str);
                else issues.add(child_path + "." + name, "expected a string value");
            }
        } else issues.add(child_path, "expected an object");
        return result;
    }
    Control control(const Value& value, const std::string& path) {
        Control result;
        const auto* item = object(value, path, {"id", "kind", "parent", "label", "text", "layout", "options", "binding", "event_bindings", "enabled", "visible", "checked", "multiline", "read_only", "text_limit"});
        if (!item) return result;
        result.id = text(*item, "id", path); result.kind = text(*item, "kind", path, "button"); result.parent = text(*item, "parent", path);
        result.label = text(*item, "label", path); result.text = text(*item, "text", path); result.binding = text(*item, "binding", path);
        result.event_bindings = string_map(*item, "event_bindings", path);
        result.enabled = flag(*item, "enabled", path, true); result.visible = flag(*item, "visible", path, true); result.checked = flag(*item, "checked", path, false);
        result.multiline = flag(*item, "multiline", path, false); result.read_only = flag(*item, "read_only", path, false);
        result.text_limit = integer(*item, "text_limit", path, 1024 * 1024);
        if (const auto* rectangle = lookup(*item, "layout")) {
            if (const auto* obj = object(*rectangle, path + ".layout", {"x", "y", "width", "height"})) {
                result.layout.x = real(*obj, "x", path + ".layout", 0); result.layout.y = real(*obj, "y", path + ".layout", 0);
                result.layout.width = real(*obj, "width", path + ".layout", 120); result.layout.height = real(*obj, "height", path + ".layout", 32);
            }
        }
        each(*item, "options", path, [&](const Value& option, const std::string& option_path) {
            Option out;
            if (const auto* obj = object(option, option_path, {"id", "label", "value", "enabled"})) {
                out.id = text(*obj, "id", option_path); out.label = text(*obj, "label", option_path); out.value = text(*obj, "value", option_path);
                out.enabled = flag(*obj, "enabled", option_path, true);
            }
            result.options.push_back(std::move(out));
        });
        return result;
    }
    Port decode_port(const Value& value, const std::string& path) {
        Port result;
        if (const auto* obj = object(value, path, {"id", "type", "required"})) {
            result.id = text(*obj, "id", path); result.type = text(*obj, "type", path, "float"); result.required = flag(*obj, "required", path, true);
        }
        return result;
    }
};

std::vector<Diagnostic> storage_issues(const Project& project, const Limits& limits) {
    IssueList out;
    std::unordered_set<std::string> all_ids;
    auto text = [&](const std::string& value, const std::string& path) {
        if (value.size() > limits.string_bytes) out.add(path, "text exceeds byte limit");
        if (bad_text(value)) out.add(path, "text must be valid UTF-8 without NUL");
    };
    auto id = [&](const std::string& value, const std::string& path, bool global = true) {
        text(value, path);
        if (!safe_id(value)) out.add(path, "expected a stable identifier: letter/underscore followed by letters, digits, underscore, dot or hyphen");
        else if (global && !all_ids.insert(value).second) out.add(path, "duplicate project object identifier '" + value + "'");
    };
    auto reference = [&](const std::string& value, const std::string& path) {
        if (!value.empty()) id(value, path, false);
    };
    auto path = [&](const std::string& value, const std::string& field, bool dot = false) {
        text(value, field);
        if (!value.empty() && !safe_relative_path(value, dot)) out.add(field, "expected a portable project-relative path without '..', absolute roots or backslashes");
    };
    auto coordinate = [&](double value, const std::string& field, bool positive = false) {
        if (!std::isfinite(value) || std::abs(value) > 10000000 || (positive && value <= 0)) out.add(field, "expected a finite logical-pixel value within 10000000, with positive dimensions");
    };
    auto count = [&](std::size_t size, std::size_t maximum, const std::string& field) { if (size > maximum) out.add(field, "item count exceeds configured limit"); };
    if (project.schema_version != 1) out.add("$.schema_version", "unsupported design schema; expected 1");
    text(project.name, "$.name");
    text(project.generated_directory, "$.generated_directory");
    text(project.cpp_namespace, "$.cpp_namespace");
    if (!safe_relative_path(project.generated_directory)) out.add("$.generated_directory", "expected a portable nonempty project-relative output directory");
    if (!valid_cpp_symbol(project.cpp_namespace) || project.cpp_namespace.substr(0, 2) == "::") out.add("$.cpp_namespace", "expected a C++ namespace path without leading '::'");
    count(project.forms.size(), limits.forms, "$.forms"); count(project.bindings.size(), limits.bindings, "$.bindings");
    count(project.flows.size(), limits.flows, "$.flows"); count(project.blocks.size(), limits.blocks, "$.blocks");
    count(project.edges.size(), limits.edges, "$.edges"); count(project.recipes.size(), limits.recipes, "$.recipes");
    std::size_t controls = 0, ports = 0, options = 0, parameters = 0;
    const std::set<std::string> kinds{"group", "label", "button", "toggle", "choice", "text", "list", "bitmap", "menu"};
    for (std::size_t f = 0; f < project.forms.size(); ++f) {
        const auto& form = project.forms[f]; const auto base = "$.forms[" + std::to_string(f) + "]";
        id(form.id, base + ".id"); text(form.label, base + ".label"); coordinate(form.width, base + ".width", true); coordinate(form.height, base + ".height", true);
        controls += form.controls.size();
        for (std::size_t c = 0; c < form.controls.size(); ++c) {
            const auto& control = form.controls[c]; const auto field = base + ".controls[" + std::to_string(c) + "]";
            id(control.id, field + ".id");
            if (!kinds.contains(control.kind)) out.add(field + ".kind", "unknown GUI widget kind");
            reference(control.parent, field + ".parent"); reference(control.binding, field + ".binding");
            text(control.label, field + ".label"); text(control.text, field + ".text");
            if (!control.text_limit || control.text_limit > limits.string_bytes) out.add(field + ".text_limit", "text limit must be positive and within the configured string byte limit");
            coordinate(control.layout.x, field + ".layout.x"); coordinate(control.layout.y, field + ".layout.y");
            coordinate(control.layout.width, field + ".layout.width", true); coordinate(control.layout.height, field + ".layout.height", true);
            parameters += control.event_bindings.size();
            for (const auto& [event, binding] : control.event_bindings) { id(event, field + ".event_bindings.event", false); id(binding, field + ".event_bindings." + event, false); }
            std::unordered_set<std::string> option_ids;
            options += control.options.size();
            for (std::size_t o = 0; o < control.options.size(); ++o) {
                const auto& option = control.options[o]; const auto option_field = field + ".options[" + std::to_string(o) + "]";
                id(option.id, option_field + ".id", false);
                if (!option_ids.insert(option.id).second) out.add(option_field + ".id", "duplicate option identifier within control");
                text(option.label, option_field + ".label"); text(option.value, option_field + ".value");
            }
        }
    }
    for (std::size_t b = 0; b < project.bindings.size(); ++b) {
        const auto& binding = project.bindings[b]; const auto field = "$.bindings[" + std::to_string(b) + "]";
        id(binding.id, field + ".id"); id(binding.event, field + ".event", false);
        path(binding.file, field + ".file"); path(binding.header, field + ".header"); text(binding.anchor, field + ".anchor");
        if (!binding.symbol.empty() && !valid_cpp_symbol(binding.symbol)) out.add(field + ".symbol", "expected a C++ qualified adapter symbol");
    }
    for (std::size_t f = 0; f < project.flows.size(); ++f) {
        const auto& flow = project.flows[f]; const auto field = "$.flows[" + std::to_string(f) + "]";
        id(flow.id, field + ".id"); text(flow.label, field + ".label");
    }
    for (std::size_t b = 0; b < project.blocks.size(); ++b) {
        const auto& block = project.blocks[b]; const auto field = "$.blocks[" + std::to_string(b) + "]";
        id(block.id, field + ".id"); text(block.label, field + ".label"); id(block.flow, field + ".flow", false); reference(block.binding, field + ".binding");
        path(block.file, field + ".file"); path(block.header, field + ".header");
        if (!block.factory.empty() && !valid_cpp_symbol(block.factory)) out.add(field + ".factory", "expected a C++ qualified factory symbol");
        if (!block.symbol.empty() && !valid_cpp_symbol(block.symbol)) out.add(field + ".symbol", "expected a C++ qualified source symbol");
        coordinate(block.x, field + ".x"); coordinate(block.y, field + ".y");
        auto check_ports = [&](const std::vector<Port>& list, const std::string& direction) {
            ports += list.size(); std::unordered_set<std::string> port_ids;
            for (std::size_t p = 0; p < list.size(); ++p) {
                const auto& port = list[p]; const auto port_field = field + "." + direction + "[" + std::to_string(p) + "]";
                id(port.id, port_field + ".id", false);
                if (!port_ids.insert(port.id).second) out.add(port_field + ".id", "duplicate port identifier within direction");
                if (!valid_type(port.type)) out.add(port_field + ".type", "expected a C++ type name or simple template type");
            }
        };
        check_ports(block.inputs, "inputs"); check_ports(block.outputs, "outputs"); parameters += block.params.size();
        for (const auto& [key, value] : block.params) { id(key, field + ".params.key", false); text(value, field + ".params." + key); }
    }
    for (std::size_t e = 0; e < project.edges.size(); ++e) {
        const auto& edge = project.edges[e]; const auto field = "$.edges[" + std::to_string(e) + "]";
        id(edge.id, field + ".id"); id(edge.from_block, field + ".from_block", false); id(edge.to_block, field + ".to_block", false);
        id(edge.from_port, field + ".from_port", false); id(edge.to_port, field + ".to_port", false);
        if (!edge.capacity || edge.capacity > limits.edge_capacity) out.add(field + ".capacity", "queue capacity must be positive and within configured limit");
        if (edge.initial_tokens > edge.capacity) out.add(field + ".initial_tokens", "initial token count exceeds capacity");
    }
    for (std::size_t r = 0; r < project.recipes.size(); ++r) {
        const auto& recipe = project.recipes[r]; const auto field = "$.recipes[" + std::to_string(r) + "]";
        id(recipe.id, field + ".id"); text(recipe.label, field + ".label"); path(recipe.working_directory, field + ".working_directory", true);
        count(recipe.argv.size(), 256, field + ".argv");
        for (std::size_t a = 0; a < recipe.argv.size(); ++a) text(recipe.argv[a], field + ".argv[" + std::to_string(a) + "]");
    }
    count(controls, limits.controls, "$.forms.controls"); count(ports, limits.ports, "$.blocks.ports");
    count(options, limits.options, "$.forms.options"); count(parameters, limits.parameters, "$.parameters");
    return out.data;
}

Value text_value(const std::string& text) { return Value{text}; }
Value number_value(std::size_t number) { return Value{static_cast<double>(number)}; }
Value map_value(const std::map<std::string, std::string>& map) {
    Value::Object out; for (const auto& [key, value] : map) out.emplace(key, text_value(value)); return Value{std::move(out)};
}
Value encode(const Project& project) {
    Value::Array forms, bindings, flows, blocks, edges, recipes;
    for (const auto& form : project.forms) {
        Value::Array controls;
        for (const auto& control : form.controls) {
            Value::Array options;
            for (const auto& option : control.options) options.push_back(Value{Value::Object{{"id", text_value(option.id)}, {"label", text_value(option.label)}, {"value", text_value(option.value)}, {"enabled", Value{option.enabled}}}});
            Value::Object layout{{"x", Value{control.layout.x}}, {"y", Value{control.layout.y}}, {"width", Value{control.layout.width}}, {"height", Value{control.layout.height}}};
            controls.push_back(Value{Value::Object{{"id", text_value(control.id)}, {"kind", text_value(control.kind)}, {"parent", text_value(control.parent)}, {"label", text_value(control.label)}, {"text", text_value(control.text)}, {"layout", Value{std::move(layout)}}, {"options", Value{std::move(options)}}, {"binding", text_value(control.binding)}, {"event_bindings", map_value(control.event_bindings)}, {"enabled", Value{control.enabled}}, {"visible", Value{control.visible}}, {"checked", Value{control.checked}}, {"multiline", Value{control.multiline}}, {"read_only", Value{control.read_only}}, {"text_limit", number_value(control.text_limit)}}});
        }
        forms.push_back(Value{Value::Object{{"id", text_value(form.id)}, {"label", text_value(form.label)}, {"width", Value{form.width}}, {"height", Value{form.height}}, {"controls", Value{std::move(controls)}}}});
    }
    for (const auto& binding : project.bindings) bindings.push_back(Value{Value::Object{{"id", text_value(binding.id)}, {"event", text_value(binding.event)}, {"file", text_value(binding.file)}, {"symbol", text_value(binding.symbol)}, {"anchor", text_value(binding.anchor)}, {"header", text_value(binding.header)}}});
    for (const auto& flow : project.flows) flows.push_back(Value{Value::Object{{"id", text_value(flow.id)}, {"label", text_value(flow.label)}}});
    for (const auto& block : project.blocks) {
        auto encode_ports = [](const std::vector<Port>& ports) {
            Value::Array out;
            for (const auto& port : ports) out.push_back(Value{Value::Object{{"id", text_value(port.id)}, {"type", text_value(port.type)}, {"required", Value{port.required}}}});
            return Value{std::move(out)};
        };
        blocks.push_back(Value{Value::Object{{"id", text_value(block.id)}, {"label", text_value(block.label)}, {"factory", text_value(block.factory)}, {"binding", text_value(block.binding)}, {"file", text_value(block.file)}, {"symbol", text_value(block.symbol)}, {"header", text_value(block.header)}, {"flow", text_value(block.flow)}, {"x", Value{block.x}}, {"y", Value{block.y}}, {"inputs", encode_ports(block.inputs)}, {"outputs", encode_ports(block.outputs)}, {"params", map_value(block.params)}, {"breaks_cycle", Value{block.breaks_cycle}}}});
    }
    for (const auto& edge : project.edges) edges.push_back(Value{Value::Object{{"id", text_value(edge.id)}, {"from_block", text_value(edge.from_block)}, {"from_port", text_value(edge.from_port)}, {"to_block", text_value(edge.to_block)}, {"to_port", text_value(edge.to_port)}, {"capacity", number_value(edge.capacity)}, {"initial_tokens", number_value(edge.initial_tokens)}}});
    for (const auto& recipe : project.recipes) {
        Value::Array args; for (const auto& arg : recipe.argv) args.push_back(text_value(arg));
        recipes.push_back(Value{Value::Object{{"id", text_value(recipe.id)}, {"label", text_value(recipe.label)}, {"argv", Value{std::move(args)}}, {"working_directory", text_value(recipe.working_directory)}}});
    }
    return Value{Value::Object{{"schema_version", number_value(project.schema_version)}, {"name", text_value(project.name)}, {"generated_directory", text_value(project.generated_directory)}, {"cpp_namespace", text_value(project.cpp_namespace)}, {"forms", Value{std::move(forms)}}, {"bindings", Value{std::move(bindings)}}, {"flows", Value{std::move(flows)}}, {"blocks", Value{std::move(blocks)}}, {"edges", Value{std::move(edges)}}, {"recipes", Value{std::move(recipes)}}}};
}
class Writer {
public:
    explicit Writer(const Limits& limits) : limits_(limits) {}
    std::string write(const Value& value) { item(value, 0); out_ += '\n'; check(); return std::move(out_); }
private:
    const Limits& limits_;
    std::string out_;
    std::size_t count_ = 0;
    void check() { if (out_.size() > limits_.file_bytes) throw std::length_error("serialized document exceeds file byte limit"); }
    void indent(std::size_t depth) { out_.append(depth * 2, ' '); }
    void string(const std::string& str) {
        if (str.size() > limits_.string_bytes) throw std::length_error("serialized string exceeds byte limit");
        out_ += '"';
        constexpr char hex[] = "0123456789abcdef";
        for (const unsigned char ch : str) {
            if (ch == '"' || ch == '\\') { out_ += '\\'; out_ += static_cast<char>(ch); }
            else if (ch < 0x20) { out_ += "\\u00"; out_ += hex[ch >> 4]; out_ += hex[ch & 15]; }
            else out_ += static_cast<char>(ch);
            check();
        }
        out_ += '"';
    }
    void item(const Value& value, std::size_t depth) {
        if (depth > limits_.nesting || ++count_ > limits_.json_values) throw std::length_error("serialized JSON exceeds nesting/value limit");
        if (std::holds_alternative<std::monostate>(value.data)) out_ += "null";
        else if (const auto* flag = std::get_if<bool>(&value.data)) out_ += *flag ? "true" : "false";
        else if (const auto* number = std::get_if<double>(&value.data)) {
            char buffer[64]; const auto result = std::to_chars(buffer, buffer + sizeof(buffer), *number == 0 ? 0.0 : *number, std::chars_format::general, std::numeric_limits<double>::max_digits10);
            if (result.ec != std::errc{}) throw std::invalid_argument("cannot serialize numeric value");
            out_.append(buffer, result.ptr);
        } else if (const auto* str = std::get_if<std::string>(&value.data)) string(*str);
        else if (const auto* array = std::get_if<Value::Array>(&value.data)) {
            out_ += '[';
            for (std::size_t i = 0; i < array->size(); ++i) {
                out_ += i ? ",\n" : "\n"; indent(depth + 1); item((*array)[i], depth + 1);
            }
            if (!array->empty()) { out_ += '\n'; indent(depth); }
            out_ += ']';
        } else {
            const auto& obj = std::get<Value::Object>(value.data); out_ += '{'; bool first = true;
            for (const auto& [key, child] : obj) {
                out_ += first ? "\n" : ",\n"; first = false; indent(depth + 1); string(key); out_ += ": "; item(child, depth + 1);
            }
            if (!obj.empty()) { out_ += '\n'; indent(depth); }
            out_ += '}';
        }
        check();
    }
};
} // namespace

bool valid_utf8(std::string_view value) {
    for (std::size_t i = 0; i < value.size();) {
        const auto start = static_cast<unsigned char>(value[i++]);
        if (start < 0x80) continue;
        unsigned codepoint = 0, remaining = 0, minimum = 0;
        if (start >= 0xc2 && start <= 0xdf) { codepoint = start & 31; remaining = 1; minimum = 0x80; }
        else if (start >= 0xe0 && start <= 0xef) { codepoint = start & 15; remaining = 2; minimum = 0x800; }
        else if (start >= 0xf0 && start <= 0xf4) { codepoint = start & 7; remaining = 3; minimum = 0x10000; }
        else return false;
        if (remaining > value.size() - i) return false;
        while (remaining--) {
            const auto next = static_cast<unsigned char>(value[i++]);
            if ((next & 0xc0) != 0x80) return false;
            codepoint = (codepoint << 6) | (next & 63);
        }
        if (codepoint < minimum || codepoint > 0x10ffff || (codepoint >= 0xd800 && codepoint <= 0xdfff)) return false;
    }
    return true;
}
bool safe_id(std::string_view value) {
    if (value.empty() || value.size() > 128 || !word_start(value.front())) return false;
    return std::all_of(value.begin() + 1, value.end(), [](char ch) { return word_continue(ch) || ch == '.' || ch == '-'; });
}
bool valid_cpp_symbol(std::string_view value) {
    if (value.empty() || value.size() > 512) return false;
    std::size_t at = value.substr(0, 2) == "::" ? 2 : 0;
    while (at < value.size()) {
        if (!word_start(value[at++])) return false;
        while (at < value.size() && word_continue(value[at])) ++at;
        if (at == value.size()) return true;
        if (value.substr(at, 2) != "::") return false;
        at += 2;
    }
    return false;
}
bool safe_relative_path(std::string_view value, bool allow_dot) {
    if (allow_dot && value == ".") return true;
    if (value.empty() || value.size() > 4096 || value.front() == '/' || bad_text(value)) return false;
    if (value.find('\\') != std::string_view::npos || value.find(':') != std::string_view::npos) return false;
    for (const auto ch : value) if (static_cast<unsigned char>(ch) < 0x20 || ch == '\x7f') return false;
    std::size_t from = 0;
    while (from < value.size()) {
        const auto slash = value.find('/', from); const auto end = slash == std::string_view::npos ? value.size() : slash;
        const auto part = value.substr(from, end - from);
        if (part.empty() || part == "." || part == "..") return false;
        if (slash == std::string_view::npos) return true;
        from = slash + 1;
    }
    return false;
}
bool has_errors(const std::vector<Diagnostic>& diagnostics) {
    return std::any_of(diagnostics.begin(), diagnostics.end(), [](const auto& issue) { return issue.severity == Severity::error; });
}

std::vector<Diagnostic> validate(const Project& project, const Limits& limits) {
    IssueList out;
    out.data = storage_issues(project, limits);
    if (has_errors(out.data)) return out.data;
    std::unordered_map<std::string, const Binding*> bindings;
    for (const auto& binding : project.bindings) {
        bindings.emplace(binding.id, &binding);
        if (binding.symbol.empty()) out.add("binding:" + binding.id, "binding has no adapter symbol yet", Severity::warning);
        if (binding.file.empty() && binding.header.empty()) out.add("binding:" + binding.id, "binding has no source navigation path yet", Severity::warning);
    }
    auto binding_reference = [&](const std::string& id, const std::string& path) {
        if (!id.empty() && !bindings.contains(id)) out.add(path, "unknown binding '" + id + "'");
    };
    for (const auto& form : project.forms) {
        std::unordered_map<std::string, const Control*> controls;
        for (const auto& control : form.controls) controls.emplace(control.id, &control);
        std::unordered_map<std::string, std::vector<std::string>> children;
        std::unordered_map<std::string, std::size_t> degree;
        for (const auto& control : form.controls) {
            degree.emplace(control.id, 0);
            binding_reference(control.binding, "control:" + control.id + ".binding");
            if (!control.options.empty() && control.kind != "choice" && control.kind != "menu" && control.kind != "text") out.add("control:" + control.id + ".options", "options are supported only by choice, menu and text controls");
            if (control.kind == "text") {
                if (control.text.size() > control.text_limit) out.add("control:" + control.id + ".text", "initial text exceeds the text policy byte limit");
                if (!control.multiline && control.text.find_first_of("\r\n") != std::string::npos) out.add("control:" + control.id + ".text", "single-line text contains a line break; enable multiline");
                for (const auto& option : control.options) {
                    if (option.value.size() > control.text_limit) out.add("control:" + control.id + ".options." + option.id, "suggested text exceeds the text policy byte limit");
                    if (!control.multiline && option.value.find_first_of("\r\n") != std::string::npos) out.add("control:" + control.id + ".options." + option.id, "single-line suggested text contains a line break; enable multiline");
                }
            }
            for (const auto& [event, binding] : control.event_bindings) {
                binding_reference(binding, "control:" + control.id + ".event_bindings." + event);
                if (!control.binding.empty() && bindings.contains(control.binding) && bindings.at(control.binding)->event == event)
                    out.add("control:" + control.id + ".event_bindings." + event, "default binding and event map both handle the same event");
            }
            if (control.parent.empty() || control.parent == form.id) continue;
            const auto found = controls.find(control.parent);
            if (found == controls.end()) out.add("control:" + control.id + ".parent", "parent must belong to the same form");
            else if (found->second->kind != "group") out.add("control:" + control.id + ".parent", "parent control must be a group");
            else { children[control.parent].push_back(control.id); degree[control.id] = 1; }
        }
        std::vector<std::string> ready;
        for (const auto& [id, count] : degree) if (!count) ready.push_back(id);
        std::size_t at = 0;
        while (at < ready.size()) {
            for (const auto& id : children[ready[at++]]) if (--degree[id] == 0) ready.push_back(id);
        }
        if (ready.size() != controls.size()) out.add("form:" + form.id, "control parent cycle; group ownership must be acyclic");
    }
    std::unordered_set<std::string> flows;
    for (const auto& flow : project.flows) flows.insert(flow.id);
    // The absent list represents one implicit main flow for compact headless
    // projects. Once explicit flows exist, every block references one of them.
    if (flows.empty()) flows.insert("main");
    std::unordered_map<std::string, const Block*> blocks;
    std::unordered_map<std::string, std::size_t> block_index;
    using PortMap = std::unordered_map<std::string, const Port*>;
    std::unordered_map<std::string, PortMap> input_ports, output_ports;
    for (std::size_t i = 0; i < project.blocks.size(); ++i) {
        const auto& block = project.blocks[i]; blocks.emplace(block.id, &block); block_index.emplace(block.id, i);
        for (const auto& port : block.inputs) input_ports[block.id].emplace(port.id, &port);
        for (const auto& port : block.outputs) output_ports[block.id].emplace(port.id, &port);
        if (!flows.contains(block.flow)) out.add("block:" + block.id + ".flow", "unknown flow '" + block.flow + "'");
        binding_reference(block.binding, "block:" + block.id + ".binding");
        if (block.factory.empty()) out.add("block:" + block.id + ".factory", "block has no factory yet", Severity::warning);
    }
    auto find_port = [](const PortMap& ports, const std::string& id) -> const Port* {
        const auto found = ports.find(id);
        return found == ports.end() ? nullptr : found->second;
    };
    std::set<std::pair<std::string, std::string>> connected_inputs, connected_outputs;
    std::vector<std::vector<std::size_t>> graph(project.blocks.size());
    std::vector<std::size_t> indegree(project.blocks.size(), 0);
    for (const auto& edge : project.edges) {
        const auto path = "edge:" + edge.id;
        if (edge.initial_tokens) out.add(path + ".initial_tokens", "numeric initial tokens lack typed values; use a stateful factory and block.breaks_cycle");
        const auto from = blocks.find(edge.from_block), to = blocks.find(edge.to_block);
        if (from == blocks.end()) out.add(path + ".from_block", "unknown source block '" + edge.from_block + "'");
        if (to == blocks.end()) out.add(path + ".to_block", "unknown destination block '" + edge.to_block + "'");
        if (from == blocks.end() || to == blocks.end()) continue;
        const Port* output = find_port(output_ports[edge.from_block], edge.from_port);
        const Port* input = find_port(input_ports[edge.to_block], edge.to_port);
        if (!output) out.add(path + ".from_port", "unknown output port '" + edge.from_port + "'");
        if (!input) out.add(path + ".to_port", "unknown input port '" + edge.to_port + "'");
        if (from->second->flow != to->second->flow) out.add(path, "edge cannot connect different flow instances");
        if (!output || !input) continue;
        if (input->type != output->type) out.add(path, "stream type mismatch: '" + output->type + "' to '" + input->type + "'");
        if (!connected_inputs.emplace(edge.to_block, edge.to_port).second) out.add(path + ".to_port", "input already has a producer; use an explicit combining block");
        if (!connected_outputs.emplace(edge.from_block, edge.from_port).second) out.add(path + ".from_port", "output already has a consumer; use an explicit split/broadcast block");
        if (!from->second->breaks_cycle) {
            const auto src = block_index.at(edge.from_block), dst = block_index.at(edge.to_block);
            graph[src].push_back(dst); ++indegree[dst];
        }
    }
    for (const auto& block : project.blocks) {
        for (const auto& port : block.inputs) if (port.required && !connected_inputs.contains({block.id, port.id})) out.add("block:" + block.id + ".inputs." + port.id, "required input is unconnected");
        for (const auto& port : block.outputs) if (port.required && !connected_outputs.contains({block.id, port.id})) out.add("block:" + block.id + ".outputs." + port.id, "required output is unconnected");
    }
    std::vector<std::size_t> ready;
    for (std::size_t i = 0; i < indegree.size(); ++i) if (indegree[i] == 0) ready.push_back(i);
    std::size_t at = 0;
    while (at < ready.size()) for (const auto dst : graph[ready[at++]]) if (--indegree[dst] == 0) ready.push_back(dst);
    if (ready.size() != project.blocks.size()) {
        std::string cycle;
        for (std::size_t i = 0; i < indegree.size(); ++i) if (indegree[i]) { if (!cycle.empty()) cycle += ", "; cycle += project.blocks[i].id; if (cycle.size() > 400) { cycle += ", ..."; break; } }
        out.add("$.blocks", "feedback cycle requires an explicit stateful/delay block with breaks_cycle: " + cycle);
    }
    for (const auto& recipe : project.recipes) if (recipe.argv.empty()) out.add("recipe:" + recipe.id, "recipe has no command arguments yet", Severity::warning);
    return out.data;
}
ParseResult parse_project(std::string_view bytes, const Limits& limits) {
    ParseResult result;
    try {
        const auto root = Reader(bytes, limits).read(); Decoder decoder;
        auto project = decoder.decode(root);
        result.diagnostics = std::move(decoder.issues.data);
        if (has_errors(result.diagnostics)) return result;
        const auto storage = storage_issues(project, limits);
        if (has_errors(storage)) { result.diagnostics = storage; return result; }
        result.diagnostics = validate(project, limits);
        result.project = std::move(project);
    } catch (const ParseError& error) {
        std::size_t line = 1, column = 1;
        for (std::size_t i = 0; i < std::min(error.position, bytes.size()); ++i) {
            if (bytes[i] == '\n') { ++line; column = 1; } else ++column;
        }
        result.diagnostics.push_back({Severity::error, "$", error.what(), line, column});
    }
    return result;
}
std::string write_project(const Project& project, const Limits& limits) {
    const auto issues = storage_issues(project, limits);
    if (has_errors(issues)) throw std::invalid_argument(issues.front().path + ": " + issues.front().message);
    return Writer(limits).write(encode(project));
}
std::string semantic_project(const Project& project, const Limits& limits) {
    Project semantics = project;
    for (auto& block : semantics.blocks) { block.x = 0; block.y = 0; }
    return write_project(semantics, limits);
}
Project empty_project(std::string name) {
    Project project; project.name = std::move(name); return project;
}
Project demo_project() {
    Project project = empty_project("Visual composition example");
    Form form; form.id = "main_form"; form.label = "Main panel";
    Control device; device.id = "device"; device.kind = "choice"; device.label = "Device"; device.layout = {24, 24, 260, 32};
    device.options = {{"loopback", "Loopback", "loopback", true}, {"receiver", "Receiver", "receiver", true}};
    Control start; start.id = "start"; start.label = "Start"; start.layout = {24, 72, 120, 32}; start.binding = "on_start";
    Control stop; stop.id = "stop"; stop.label = "Stop"; stop.layout = {160, 72, 120, 32}; stop.binding = "on_stop"; stop.enabled = false;
    Control status; status.id = "status"; status.kind = "text"; status.text = "Ready"; status.layout = {24, 120, 540, 120}; status.multiline = true;
    form.controls = {device, start, stop, status}; project.forms.push_back(form);
    project.bindings = {{"on_start", "activate", "src/handlers.cpp", "example::on_start", "visual:on_start", "src/handlers.hpp"}, {"on_stop", "activate", "src/handlers.cpp", "example::on_stop", "visual:on_stop", "src/handlers.hpp"}};
    project.flows.push_back({"main", "Receive chain"});
    Block source; source.id = "source"; source.label = "Source"; source.factory = "example::make_source"; source.file = "src/blocks.cpp"; source.header = "src/blocks.hpp"; source.x = 24; source.y = 24; source.outputs = {{"out", "float", true}};
    Block gain; gain.id = "gain"; gain.label = "Gain"; gain.factory = "example::make_gain"; gain.file = "src/blocks.cpp"; gain.header = "src/blocks.hpp"; gain.x = 220; gain.y = 24; gain.inputs = {{"in", "float", true}}; gain.outputs = {{"out", "float", true}}; gain.params = {{"gain", "2"}};
    Block sink; sink.id = "sink"; sink.label = "Display"; sink.factory = "example::make_sink"; sink.file = "src/blocks.cpp"; sink.header = "src/blocks.hpp"; sink.x = 416; sink.y = 24; sink.inputs = {{"in", "float", true}};
    project.blocks = {source, gain, sink};
    project.edges = {{"source_gain", "source", "out", "gain", "in", 256, 0}, {"gain_sink", "gain", "out", "sink", "in", 256, 0}};
    return project;
}
History::History(std::size_t bytes, std::size_t entries) : limit_bytes_(bytes), limit_entries_(entries) {
    if (!bytes || !entries) throw std::invalid_argument("history limits must be positive");
}
void History::reset(const Project& project) {
    auto snapshot = write_project(project);
    if (snapshot.size() > limit_bytes_) throw std::length_error("project exceeds undo memory limit");
    snapshots_.clear(); snapshots_.push_back(std::move(snapshot)); bytes_ = snapshots_.front().size(); cursor_ = 0;
}
bool History::commit(const Project& project) {
    auto snapshot = write_project(project);
    if (snapshot.size() > limit_bytes_) return false;
    if (snapshots_.empty()) { reset(project); return true; }
    if (snapshots_[cursor_] == snapshot) return false;
    while (snapshots_.size() > cursor_ + 1) { bytes_ -= snapshots_.back().size(); snapshots_.pop_back(); }
    bytes_ += snapshot.size(); snapshots_.push_back(std::move(snapshot)); cursor_ = snapshots_.size() - 1;
    while (snapshots_.size() > limit_entries_ || bytes_ > limit_bytes_) {
        bytes_ -= snapshots_.front().size(); snapshots_.erase(snapshots_.begin()); --cursor_;
    }
    return true;
}
std::optional<Project> History::undo() {
    if (!can_undo()) return std::nullopt;
    auto parsed = parse_project(snapshots_[cursor_ - 1]);
    if (!parsed.project) throw std::logic_error("invalid undo snapshot");
    --cursor_; return std::move(parsed.project);
}
std::optional<Project> History::redo() {
    if (!can_redo()) return std::nullopt;
    auto parsed = parse_project(snapshots_[cursor_ + 1]);
    if (!parsed.project) throw std::logic_error("invalid redo snapshot");
    ++cursor_; return std::move(parsed.project);
}
bool History::can_undo() const { return !snapshots_.empty() && cursor_ > 0; }
bool History::can_redo() const { return !snapshots_.empty() && cursor_ + 1 < snapshots_.size(); }
std::size_t History::bytes() const { return bytes_; }

} // namespace foundation::editor
