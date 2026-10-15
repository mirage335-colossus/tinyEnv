#include "services.hpp"
#include "editor/platform/process_runner.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <set>
#include <stdexcept>
#include <thread>
#include <utility>

#if defined(__linux__)
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>
extern char** environ;
#elif defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#include <aclapi.h>
#endif

#ifndef TINYENV_RUNTIME_PATH
#define TINYENV_RUNTIME_PATH ""
#endif
#ifndef TINYENV_PYTHON_EXECUTABLE
#define TINYENV_PYTHON_EXECUTABLE "python3"
#endif

namespace tinyenv {
namespace {
using foundation::editor::ProcessRunner;
using foundation::editor::ProcessState;

ServiceState service_state(ProcessState state) {
    switch (state) {
    case ProcessState::idle: return ServiceState::idle;
    case ProcessState::running: return ServiceState::running;
    case ProcessState::succeeded: return ServiceState::succeeded;
    case ProcessState::failed: return ServiceState::failed;
    case ProcessState::cancelled: return ServiceState::cancelled;
    }
    return ServiceState::failed;
}

bool joined_tree(const foundation::editor::ProcessStatus& status) noexcept {
    return status.finished() && (status.error.empty() ||
        status.error == "Command left running descendants; they were terminated and joined" ||
        (status.exit_code == 127 && status.error == "Executable was not found in PATH"));
}

std::filesystem::path directory(const std::filesystem::path& path) {
    if (path.empty() || !std::filesystem::is_directory(path))
        throw std::invalid_argument("An existing service working directory is required");
    return std::filesystem::canonical(path);
}

std::string path_text(const std::filesystem::path& path) {
    const auto text = path.u8string();
    return {reinterpret_cast<const char*>(text.data()), text.size()};
}

std::filesystem::path text_path(std::string_view text) {
    return std::filesystem::path(std::u8string_view(reinterpret_cast<const char8_t*>(text.data()), text.size()));
}

bool inside(const std::filesystem::path& root, const std::filesystem::path& path) {
    auto candidate = path.begin();
    for (auto parent = root.begin(); parent != root.end(); ++parent, ++candidate)
        if (candidate == path.end() || *candidate != *parent) return false;
    return true;
}

std::string trusted_git_path(const std::filesystem::path& root) {
#if defined(_WIN32)
    constexpr char separator = ';';
    constexpr auto executable = "git.exe";
#else
    constexpr char separator = ':';
    constexpr auto executable = "git";
#endif
    std::vector<std::filesystem::path> candidates;
#if defined(__linux__)
    candidates.emplace_back("/usr/bin/git"); candidates.emplace_back("/bin/git");
#endif
    if (const auto* environment = std::getenv("PATH")) {
        const std::string paths = environment;
        for (std::size_t begin = 0; begin <= paths.size();) {
            const auto end = paths.find(separator, begin);
            auto entry = paths.substr(begin, end == std::string::npos ? end : end - begin);
#if defined(_WIN32)
            if (entry.size() >= 2 && entry.front() == '"' && entry.back() == '"') entry = entry.substr(1, entry.size() - 2);
#endif
            const auto parent = std::filesystem::path(entry);
            if (parent.is_absolute()) candidates.push_back(parent / executable);
            if (end == std::string::npos) break;
            begin = end + 1;
        }
    }
    for (const auto& candidate : candidates) {
        std::error_code error;
        const auto resolved = std::filesystem::canonical(candidate, error);
        if (error || inside(root, resolved) || !std::filesystem::is_regular_file(resolved, error) || error) continue;
#if defined(__linux__)
        if (::access(resolved.c_str(), X_OK)) continue;
#endif
        return path_text(resolved);
    }
    throw std::runtime_error("Git was not found outside the current project in an absolute system PATH entry");
}

void check_credentials(const json::Value& value) {
    if (const auto* object = std::get_if<json::Value::Object>(&value.data)) {
        for (const auto& [key, child] : *object) {
            std::string lower = key;
            for (auto& c : lower) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
            if (lower == "api_key" || lower == "apikey" || lower == "api-key" ||
                lower == "authorization" || lower == "password" || lower == "credential" ||
                lower == "credentials" || lower == "access_token" || lower == "bearer_token" ||
                lower == "secret" || lower == "token" || lower == "credential_directory" ||
                lower == "credential-directory")
                throw std::invalid_argument("Credentials must be configured privately, never passed in a runtime request");
            check_credentials(child);
        }
    } else if (const auto* array = std::get_if<json::Value::Array>(&value.data)) {
        for (const auto& child : *array) check_credentials(child);
    }
}

// External command output enters a plain text widget, never an escape-capable
// terminal renderer. Preserve printable Unicode and replace invalid encoding.
std::string printable(std::string_view input) {
    std::string out;
    out.reserve(input.size());
    for (std::size_t i = 0; i < input.size();) {
        const auto c = static_cast<unsigned char>(input[i]);
        if (c == 27) {
            ++i;
            if (i < input.size() && input[i] == '[') {
                ++i;
                while (i < input.size()) { const auto p = static_cast<unsigned char>(input[i++]); if (p >= 0x40 && p <= 0x7e) break; }
            } else if (i < input.size() && input[i] == ']') {
                ++i;
                while (i < input.size()) {
                    if (input[i++] == '\a') break;
                    if (i >= 2 && input[i - 2] == 27 && input[i - 1] == '\\') break;
                }
            } else if (i < input.size()) ++i;
            continue;
        }
        if (c < 32 || c == 127) {
            ++i;
            if (c == '\n' || c == '\t') out += static_cast<char>(c);
            continue;
        }
        if (c < 0x80) { out += input[i++]; continue; }
        const std::size_t width = c >= 0xc2 && c <= 0xdf ? 2 : c >= 0xe0 && c <= 0xef ? 3 : c >= 0xf0 && c <= 0xf4 ? 4 : 0;
        bool valid = width && i + width <= input.size();
        std::uint32_t code = width ? c & ((1u << (7u - static_cast<unsigned>(width))) - 1u) : 0;
        for (std::size_t j = 1; valid && j < width; ++j) {
            const auto next = static_cast<unsigned char>(input[i + j]);
            valid = (next & 0xc0) == 0x80;
            code = (code << 6u) | (next & 0x3fu);
        }
        valid = valid && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) &&
                !(width == 2 && code < 0x80) && !(width == 3 && code < 0x800) && !(width == 4 && code < 0x10000);
        if (valid) { out.append(input.substr(i, width)); i += width; }
        else { out += "\xef\xbf\xbd"; ++i; }
    }
    return out;
}

void keep_tail(std::string& text, std::size_t limit) {
    if (text.size() <= limit) return;
    auto begin = text.size() - limit;
    while (begin < text.size() && (static_cast<unsigned char>(text[begin]) & 0xc0) == 0x80) ++begin;
    text.erase(0, begin);
}

#if defined(__linux__)
void close_fd(int& fd) noexcept { if (fd >= 0) ::close(std::exchange(fd, -1)); }
struct TerminalReceipt { int magic{}, code{-1}, cancelled{}, error{}; };

void close_other_fds(int a, int b, int c, long limit) noexcept {
    int keep[3]{a, b, c};
    if (keep[0] > keep[1]) std::swap(keep[0], keep[1]);
    if (keep[1] > keep[2]) std::swap(keep[1], keep[2]);
    if (keep[0] > keep[1]) std::swap(keep[0], keep[1]);
    bool ranges = true;
#ifdef SYS_close_range
    unsigned first = 3;
    for (const auto fd : keep) {
        if (first < static_cast<unsigned>(fd) && ::syscall(SYS_close_range, first, static_cast<unsigned>(fd - 1), 0) != 0) ranges = false;
        first = static_cast<unsigned>(fd + 1);
    }
    if (::syscall(SYS_close_range, first, ~0u, 0) != 0) ranges = false;
#else
    ranges = false;
#endif
    if (!ranges) for (int fd = 3; fd < limit; ++fd) if (fd != a && fd != b && fd != c) ::close(fd);
}

// A dedicated subreaper owns every descendant without changing the GUI's child
// handling. Only native operations run after fork; allocated argv/env are ready.
void supervise_terminal(pid_t owner, int slave, int report, int control,
                        const char* cwd, char* const* env, long close_limit) noexcept {
    close_other_fds(slave, report, control, close_limit);
    ::signal(SIGCHLD, SIG_DFL);
    TerminalReceipt receipt{0x54454e56, -1, 0, 0};
    if (::prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0) receipt.error = errno;
    if (::fcntl(control, F_SETFL, O_NONBLOCK) < 0) receipt.error = errno;
    if (::getppid() != owner) receipt.cancelled = 1;
    char children_path[128];
    const char prefix[] = "/proc/self/task/";
    std::size_t length = sizeof(prefix) - 1;
    std::memcpy(children_path, prefix, length);
    char digits[24]; int digits_count = 0; auto number = ::getpid();
    do { digits[digits_count++] = static_cast<char>('0' + number % 10); number /= 10; } while (number);
    while (digits_count) children_path[length++] = digits[--digits_count];
    const char suffix[] = "/children";
    std::memcpy(children_path + length, suffix, sizeof suffix);
    int inventory = ::open(children_path, O_RDONLY | O_CLOEXEC);
    if (inventory < 0) receipt.error = errno;
    else ::close(inventory);
    char request;
    if (::read(control, &request, 1) >= 0) receipt.cancelled = 1;
    pid_t primary = -1;
    if (!receipt.error && !receipt.cancelled) {
        primary = ::fork();
        if (primary < 0) receipt.error = errno;
        else if (primary == 0) {
            ::close(report); ::close(control);
            ::signal(SIGINT, SIG_DFL); ::signal(SIGQUIT, SIG_DFL);
            ::signal(SIGHUP, SIG_DFL); ::signal(SIGTERM, SIG_DFL);
            ::signal(SIGTSTP, SIG_DFL); ::signal(SIGTTIN, SIG_DFL); ::signal(SIGTTOU, SIG_DFL);
            sigset_t signals; ::sigemptyset(&signals); ::sigprocmask(SIG_SETMASK, &signals, nullptr);
            if (::setsid() < 0 || ::ioctl(slave, TIOCSCTTY, 0) < 0) ::_exit(126);
            if (::dup2(slave, STDIN_FILENO) < 0 || ::dup2(slave, STDOUT_FILENO) < 0 || ::dup2(slave, STDERR_FILENO) < 0) ::_exit(126);
            if (slave > 2) ::close(slave);
            if (::chdir(cwd) != 0) ::_exit(126);
            char executable[] = "/bin/bash", no_profile[] = "--noprofile", no_rc[] = "--norc", interactive[] = "-i";
            char* arguments[]{executable, no_profile, no_rc, interactive, nullptr};
            ::execve(executable, arguments, env);
            ::_exit(127);
        }
    }
    ::close(slave);
    for (;;) {
        if (::getppid() != owner) receipt.cancelled = 1;
        if (::read(control, &request, 1) >= 0) receipt.cancelled = 1;
        bool empty = false;
        for (;;) {
            int status;
            const auto child = ::waitpid(-1, &status, WNOHANG);
            if (child < 0 && errno == EINTR) continue;
            if (child < 0 && errno == ECHILD) { empty = true; break; }
            if (child < 0) { receipt.error = errno; break; }
            if (!child) break;
            if (child == primary) receipt.code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
        }
        if (empty) break;
        if (receipt.cancelled || receipt.error || receipt.code >= 0) {
            inventory = ::open(children_path, O_RDONLY | O_CLOEXEC);
            if (inventory < 0) receipt.error = errno;
            else {
                char children[65536];
                const auto count = ::read(inventory, children, sizeof children);
                ::close(inventory);
                if (count < 0 || count == static_cast<ssize_t>(sizeof children)) receipt.error = EOVERFLOW;
                else {
                    pid_t child = 0;
                    for (ssize_t i = 0; i <= count; ++i) {
                        const char c = i == count ? ' ' : children[i];
                        if (c >= '0' && c <= '9') child = child * 10 + c - '0';
                        else if (child > 0) { if (::kill(child, SIGKILL) && errno != ESRCH) receipt.error = errno; child = 0; }
                    }
                }
            }
        }
        ::poll(nullptr, 0, 10);
    }
    if (receipt.code < 0 && !receipt.cancelled && !receipt.error) receipt.error = ECHILD;
    const auto count = ::write(report, &receipt, sizeof receipt);
    ::close(report); ::close(control);
    ::_exit(count == sizeof receipt ? 0 : 125);
}
#elif defined(_WIN32)
// Restrict a new request directory and file to the current Windows token user.
class PrivateSecurity {
public:
    PrivateSecurity() {
        HANDLE token{};
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) throw std::runtime_error("Cannot inspect private request permissions");
        DWORD bytes{};
        GetTokenInformation(token, TokenUser, nullptr, 0, &bytes);
        token_user_.resize(bytes);
        const auto okay = GetTokenInformation(token, TokenUser, token_user_.data(), bytes, &bytes);
        CloseHandle(token);
        if (!okay) throw std::runtime_error("Cannot inspect private request owner");
        const auto* user = reinterpret_cast<const TOKEN_USER*>(token_user_.data());
        acl_.resize(sizeof(ACL) + sizeof(ACCESS_ALLOWED_ACE) - sizeof(DWORD) + GetLengthSid(user->User.Sid));
        auto* acl = reinterpret_cast<PACL>(acl_.data());
        if (!InitializeAcl(acl, static_cast<DWORD>(acl_.size()), ACL_REVISION) ||
            !AddAccessAllowedAce(acl, ACL_REVISION, FILE_ALL_ACCESS, user->User.Sid) ||
            !InitializeSecurityDescriptor(&descriptor_, SECURITY_DESCRIPTOR_REVISION) ||
            !SetSecurityDescriptorDacl(&descriptor_, TRUE, acl, FALSE) ||
            !SetSecurityDescriptorControl(&descriptor_, SE_DACL_PROTECTED, SE_DACL_PROTECTED))
            throw std::runtime_error("Cannot prepare private request permissions");
        attributes_ = {sizeof(attributes_), &descriptor_, FALSE};
    }
    SECURITY_ATTRIBUTES* attributes() { return &attributes_; }
private:
    std::vector<unsigned char> token_user_, acl_;
    SECURITY_DESCRIPTOR descriptor_{};
    SECURITY_ATTRIBUTES attributes_{};
};
#endif
} // namespace

struct Job::Impl {
    ProcessRunner process;
    JobStatus status;
    std::size_t limit;
    std::filesystem::path runtime, request_directory, request_file, request_scratch, credential_directory;
    bool cleanup_permitted{true};
    enum class OutputFormat { undecided, legacy, stream };
    OutputFormat output_format{OutputFormat::undecided};
    bool stream_requested{};
    std::string operation;
    std::size_t output_offset{}, next_sequence{}, delta_count{}, progress_count{};
    std::optional<json::Value> final_response;
    std::string python;
    Impl(std::size_t bytes, std::filesystem::path script, std::string executable, std::filesystem::path credentials)
        : process(bytes), limit(bytes), runtime(std::move(script)), credential_directory(std::move(credentials)),
          python(std::move(executable)) {}
    void reset_output(const json::Value& request) {
        output_format = OutputFormat::undecided;
        stream_requested = false;
        operation.clear(); output_offset = next_sequence = delta_count = progress_count = 0;
        final_response.reset();
        if (const auto* stream = request.find("stream")) {
            if (!std::holds_alternative<bool>(stream->data))
                throw std::invalid_argument("Runtime streaming must be a boolean");
            stream_requested = stream->boolean();
            if (stream_requested) {
                const auto* selected = request.find("operation");
                if (!selected || !std::holds_alternative<std::string>(selected->data) ||
                    (selected->string() != "chat" && selected->string() != "agent" && selected->string() != "scribble"))
                    throw std::invalid_argument("Runtime streaming supports only chat, agent and Scribble operations");
                operation = selected->string();
            }
        }
    }
    static void require(bool condition) {
        if (!condition) throw std::runtime_error("Invalid runtime stream");
    }
    static const json::Value& field(const json::Value& frame, std::string_view name) {
        const auto* found = frame.find(name); require(found != nullptr); return *found;
    }
    static void check_result(const json::Value& response) {
        require(std::holds_alternative<json::Value::Object>(response.data));
        require(std::holds_alternative<bool>(field(response, "ok").data));
    }
    void set_partial(std::string text) {
        require(text.size() <= limit);
        if (text != status.partial_text) {
            status.partial_text = std::move(text);
            ++status.stream_revision;
        }
    }
    void consume_frame(const json::Value& frame, std::size_t encoded_bytes) {
        require(!final_response && std::holds_alternative<json::Value::Object>(frame.data));
        require(field(frame, "stream_version").number() == 1);
        require(field(frame, "sequence").number() == static_cast<double>(next_sequence));
        const auto& event = field(frame, "event").string();
        if (!next_sequence) {
            require(event == "start" && frame.object().size() == 4 &&
                    field(frame, "operation").string() == operation);
            status.streaming = true;
        } else if (event == "delta") {
            require(operation != "scribble" && frame.object().size() == 5 && delta_count < 4096 && encoded_bytes <= 16 * 1024);
            const auto& text = field(frame, "text").string();
            const auto replace = field(frame, "replace").boolean();
            require(text.size() <= 16 * 1024);
            if (replace) set_partial(text);
            else {
                require(text.size() <= limit - status.partial_text.size());
                if (!text.empty()) { status.partial_text += text; ++status.stream_revision; }
            }
            ++delta_count;
        } else if (event == "progress") {
            require(operation == "scribble" && frame.object().size() == 7 && progress_count < 4096 && encoded_bytes <= 1024);
            const auto& phase = field(frame, "phase").string();
            require(phase == "preparing" || phase == "indexing" || phase == "enriching" ||
                    phase == "publishing" || phase == "completed");
            const auto count = [&](std::string_view key) {
                const auto value = field(frame, key).number();
                require(std::isfinite(value) && value >= 0 && value <= 4096 && std::floor(value) == value);
                return static_cast<std::size_t>(value);
            };
            const auto completed = count("completed_chunks"), total = count("total_chunks"), resumed = count("resumed_chunks");
            require(resumed <= completed && completed <= total);
            if (phase != status.progress_phase || completed != status.completed_chunks ||
                total != status.total_chunks || resumed != status.resumed_chunks) {
                status.progress_phase = phase; status.completed_chunks = completed;
                status.total_chunks = total; status.resumed_chunks = resumed;
                ++status.progress_revision;
            }
            ++progress_count;
        } else if (event == "final") {
            require(frame.object().size() == 4);
            auto response = field(frame, "result");
            check_result(response);
            const auto* text = response.find("text");
            if (field(response, "ok").boolean()) {
                require(text && std::holds_alternative<std::string>(text->data));
                if (operation != "scribble") set_partial(text->string());
            } else if (text) {
                require(std::holds_alternative<std::string>(text->data));
                if (operation != "scribble" && !text->string().empty()) set_partial(text->string());
            }
            final_response = std::move(response);
        } else require(false);
        ++next_sequence;
    }
    bool consume_output(std::string_view output) noexcept {
        try {
            if (!stream_requested || output_format == OutputFormat::legacy) return true;
            if (output_format == OutputFormat::undecided) {
                const auto end = output.find('\n');
                if (end == std::string_view::npos) return true;
                json::Value first;
                try { first = json::parse(output.substr(0, end), limit); }
                catch (const std::exception&) { return true; } // Pretty legacy JSON may span lines.
                const auto* okay = first.find("ok");
                if ((okay && std::holds_alternative<bool>(okay->data)) ||
                    (!first.find("event") && !first.find("stream_version"))) {
                    output_format = OutputFormat::legacy; return true;
                }
                output_format = OutputFormat::stream;
            }
            require(output_offset <= output.size());
            for (;;) {
                const auto end = output.find('\n', output_offset);
                if (end == std::string_view::npos) return true;
                require(end > output_offset);
                const auto frame = json::parse(output.substr(output_offset, end - output_offset), limit);
                consume_frame(frame, end - output_offset + 1);
                output_offset = end + 1;
            }
        } catch (const std::exception&) { return false; }
    }
    bool cleanup() noexcept {
        if (!cleanup_permitted) return false;
        std::error_code error;
        if (!request_scratch.empty()) {
            // Only the exact owned scratch child is recursive. remove_all
            // removes symlinks themselves and never traverses their targets.
            // The private parent is always removed nonrecursively below.
            std::filesystem::remove_all(request_scratch, error);
            if (error) return false;
            request_scratch.clear();
        }
        if (!request_file.empty()) {
            std::filesystem::remove(request_file, error);
            if (error) return false;
            request_file.clear();
        }
        if (!request_directory.empty()) {
            std::filesystem::remove(request_directory, error);
            if (error) return false;
            request_directory.clear();
        }
        return true;
    }
    void save_request(const std::filesystem::path& root, std::string_view bytes) {
        const auto state = root / ".tinyenv";
#if defined(__linux__)
        if (::mkdir(state.c_str(), 0700) && errno != EEXIST) throw std::runtime_error("Cannot create private runtime state directory");
        const int state_fd = ::open(state.c_str(), O_DIRECTORY | O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        struct StateFd { int fd; ~StateFd() { if (fd >= 0) ::close(fd); } } guard{state_fd};
        struct stat identity{};
        if (state_fd < 0 || ::fstat(state_fd, &identity) || identity.st_uid != ::geteuid())
            throw std::runtime_error("Runtime state directory must be a real directory owned by the current user");
        std::string pattern = (state / "request-XXXXXX").string();
        std::vector<char> name(pattern.begin(), pattern.end()); name.push_back('\0');
        if (!::mkdtemp(name.data())) throw std::runtime_error("Cannot create private runtime request directory");
        request_directory = name.data(); request_file = request_directory / "request.json";
        const auto scratch = request_directory / "scratch";
        if (::mkdir(scratch.c_str(), 0700)) { (void)cleanup(); throw std::runtime_error("Cannot create private runtime scratch directory"); }
        request_scratch = scratch;
        const int file = ::open(request_file.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (file < 0) { cleanup(); throw std::runtime_error("Cannot create private runtime request"); }
        std::size_t offset = 0;
        bool okay = true;
        while (offset < bytes.size()) {
            const auto wrote = ::write(file, bytes.data() + offset, bytes.size() - offset);
            if (wrote < 0 && errno == EINTR) continue;
            if (wrote <= 0) { okay = false; break; }
            offset += static_cast<std::size_t>(wrote);
        }
        if (::close(file)) okay = false;
        if (!okay) { cleanup(); throw std::runtime_error("Cannot save private runtime request"); }
#elif defined(_WIN32)
        PrivateSecurity security;
        if (!CreateDirectoryW(state.c_str(), security.attributes()) && GetLastError() != ERROR_ALREADY_EXISTS)
            throw std::runtime_error("Cannot create private runtime state directory");
        const auto attributes = GetFileAttributesW(state.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY) || (attributes & FILE_ATTRIBUTE_REPARSE_POINT))
            throw std::runtime_error("Runtime state directory must be a real directory");
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        request_directory = state / ("request-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(nonce));
        if (!CreateDirectoryW(request_directory.c_str(), security.attributes())) { request_directory.clear(); throw std::runtime_error("Cannot create private runtime request directory"); }
        const auto scratch = request_directory / "scratch";
        if (!CreateDirectoryW(scratch.c_str(), security.attributes())) { (void)cleanup(); throw std::runtime_error("Cannot create private runtime scratch directory"); }
        request_scratch = scratch;
        request_file = request_directory / "request.json";
        const auto file = CreateFileW(request_file.c_str(), GENERIC_WRITE, 0, security.attributes(), CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY, nullptr);
        if (file == INVALID_HANDLE_VALUE) { cleanup(); throw std::runtime_error("Cannot create private runtime request"); }
        DWORD wrote{};
        const auto okay = bytes.size() <= MAXDWORD && WriteFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &wrote, nullptr) && wrote == bytes.size();
        CloseHandle(file);
        if (!okay) { cleanup(); throw std::runtime_error("Cannot save private runtime request"); }
#else
        (void)bytes;
        throw std::runtime_error("Owned runtime requests are unavailable on this platform");
#endif
    }
};

Job::Job(std::size_t bytes, std::filesystem::path runtime, std::string python, std::filesystem::path credential_directory)
    : impl_(std::make_unique<Impl>(bytes, runtime.empty() ? std::filesystem::path(TINYENV_RUNTIME_PATH) : std::move(runtime),
                                  python.empty() ? std::string(TINYENV_PYTHON_EXECUTABLE) : std::move(python),
                                  std::move(credential_directory))) {
    if (!bytes) throw std::invalid_argument("Runtime response byte limit must be positive");
    if (!impl_->credential_directory.empty() && !impl_->credential_directory.is_absolute())
        throw std::invalid_argument("Private provider configuration requires an absolute directory");
}
Job::~Job() { if (running()) (void)cancel(); (void)impl_->cleanup(); }
bool Job::running() const noexcept { return impl_->status.state == ServiceState::running; }
void Job::start(const json::Value& request, const std::filesystem::path& root) {
    if (running()) throw std::logic_error("A runtime job is already running");
    const auto cwd = directory(root);
    if (!std::filesystem::is_regular_file(impl_->runtime) || !impl_->runtime.is_absolute())
        throw std::runtime_error("The configured Python runtime must be an existing absolute file path");
    check_credentials(request);
    impl_->reset_output(request);
    auto normalized = request;
    normalized.object()["root"] = path_text(cwd);
    // Bounded image inputs can contain 8 MiB of raw PNG/JPEG data, expanded by
    // base64 alongside ordinary text. Keep this envelope in sync with runtime.
    const auto bytes = json::stringify(normalized, 16 * 1024 * 1024);
    if (!impl_->cleanup()) throw std::runtime_error("A retained private runtime request could not be removed");
    impl_->status = {};
    impl_->save_request(cwd, bytes);
    try {
        impl_->cleanup_permitted = false;
        std::vector<std::string> arguments{impl_->python, "-I", "-B", path_text(impl_->runtime), "--request", path_text(impl_->request_file)};
        // The trusted startup path is separate from project/request data. Key
        // bytes never enter argv or the transient request file.
        if (!impl_->credential_directory.empty()) {
            arguments.emplace_back("--credential-directory");
            arguments.push_back(path_text(impl_->credential_directory));
        }
        impl_->process.start(arguments, cwd);
        impl_->status.state = ServiceState::running;
    } catch (...) {
        impl_->cleanup_permitted = !impl_->process.running();
        if (!impl_->cleanup()) throw std::runtime_error("Launch failed and its private runtime request could not be removed");
        throw;
    }
}
JobStatus Job::poll() {
    if (!running()) return impl_->status;
    auto process = impl_->process.poll();
    const auto valid_progress = impl_->consume_output(process.output);
    if (!valid_progress || process.output_truncated) {
        const auto error = process.output_truncated ? "Runtime response exceeded its byte limit" :
                                                    "Runtime returned invalid streaming progress";
        if (!process.finished()) process = impl_->process.cancel();
        impl_->cleanup_permitted = joined_tree(process);
        impl_->status.state = ServiceState::failed;
        impl_->status.exit_code = process.exit_code;
        impl_->status.response.reset();
        impl_->status.error = error;
        if (!impl_->cleanup()) impl_->status.error = "Private runtime request cleanup failed; its private state is retained";
        return impl_->status;
    }
    if (!process.finished()) return impl_->status;
    impl_->cleanup_permitted = joined_tree(process);
    impl_->status.state = service_state(process.state);
    impl_->status.exit_code = process.exit_code;
    if (process.state != ProcessState::cancelled) {
        try {
            auto response = [&] {
                if (impl_->output_format == Impl::OutputFormat::stream) {
                    Impl::require(impl_->final_response.has_value() && impl_->output_offset == process.output.size());
                    return *impl_->final_response;
                }
                return json::parse(process.output, impl_->limit);
            }();
            const auto* okay = response.find("ok");
            if (!okay || !std::holds_alternative<bool>(okay->data)) throw std::runtime_error("Invalid runtime response");
            if (!okay->boolean()) impl_->status.state = ServiceState::failed;
            if (const auto* error = response.find("error"); error && std::holds_alternative<std::string>(error->data))
                impl_->status.error = printable(error->string().substr(0, 4096));
            impl_->status.response = std::move(response);
        } catch (const std::exception&) {
            impl_->status.state = ServiceState::failed;
            impl_->status.error = impl_->output_format == Impl::OutputFormat::stream ?
                "Runtime returned an incomplete or invalid streaming response" : "Runtime returned an invalid JSON response";
        }
        if (impl_->status.state == ServiceState::failed && impl_->status.error.empty())
            impl_->status.error = process.error.empty() ? "Runtime request failed" : printable(process.error.substr(0, 4096));
    }
    if (!impl_->cleanup()) {
        impl_->status.state = ServiceState::failed;
        impl_->status.error = "Private runtime request cleanup failed; its private state is retained";
    }
    return impl_->status;
}
JobStatus Job::cancel() {
    if (!running()) return impl_->status;
    const auto process = impl_->process.cancel();
    const auto valid_progress = impl_->consume_output(process.output);
    impl_->cleanup_permitted = joined_tree(process);
    impl_->status.state = process.state == ProcessState::failed ? ServiceState::failed : ServiceState::cancelled;
    impl_->status.exit_code = process.exit_code;
    if (process.state == ProcessState::failed) impl_->status.error = "Runtime cancellation cleanup could not be confirmed";
    else if (!valid_progress) {
        impl_->status.state = ServiceState::failed;
        impl_->status.error = "Runtime returned invalid streaming progress";
    }
    if (!impl_->cleanup()) {
        impl_->status.state = ServiceState::failed;
        impl_->status.error = "Private runtime request cleanup failed; its private state is retained";
    }
    return impl_->status;
}

struct Terminal::Impl {
    TerminalStatus status;
    std::string raw_output, pending_input;
    std::size_t limit;
    unsigned columns{80}, rows{24};
#if defined(__linux__)
    pid_t supervisor{-1};
    int master{-1}, report{-1}, control{-1};
    TerminalReceipt receipt{};
    std::size_t receipt_bytes{};
    void read_output() {
        char bytes[16384];
        for (std::size_t total = 0; total < 128 * 1024;) {
            const auto count = ::read(master, bytes, sizeof bytes);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) break;
            total += static_cast<std::size_t>(count);
            raw_output.append(bytes, static_cast<std::size_t>(count));
            if (raw_output.size() > limit) { status.output_truncated = true; keep_tail(raw_output, limit); }
        }
    }
    void flush_input() {
        while (!pending_input.empty()) {
            const auto wrote = ::write(master, pending_input.data(), pending_input.size());
            if (wrote < 0 && errno == EINTR) continue;
            if (wrote < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
            if (wrote <= 0) { status.error = "Cannot send terminal input"; pending_input.clear(); break; }
            pending_input.erase(0, static_cast<std::size_t>(wrote));
        }
    }
#endif
    explicit Impl(std::size_t bytes) : limit(bytes) {}
};

Terminal::Terminal(std::size_t bytes) : impl_(std::make_unique<Impl>(bytes)) {
    if (!bytes) throw std::invalid_argument("Terminal scrollback byte limit must be positive");
}
Terminal::~Terminal() { shutdown(); }
bool Terminal::running() const noexcept { return impl_->status.running; }
void Terminal::start(const std::filesystem::path& cwd) {
    if (running()) throw std::logic_error("The chat terminal is already running");
    const auto root = directory(cwd);
    impl_->status = {}; impl_->raw_output.clear(); impl_->pending_input.clear();
#if defined(__linux__)
    // Allocate before acquiring native resources or forking. Child paths never
    // allocate and exceptions cannot abandon an open PTY or a running shell.
    std::vector<std::string> environment;
    for (char** entry = environ; entry && *entry; ++entry) {
        const std::string_view value(*entry);
        const auto end = value.find('=');
        const auto key = value.substr(0, end);
        if (key == "BASH_ENV" || key == "ENV" || key == "PROMPT_COMMAND" || key == "PS0" || key == "PS1" || key == "PS2" || key == "PS4" ||
            key == "SHELLOPTS" || key == "BASHOPTS" || key == "HISTFILE" || key == "TERM" || key == "CDPATH" ||
            key.starts_with("BASH_FUNC_")) continue;
        environment.emplace_back(value);
    }
    environment.emplace_back("HISTFILE=/dev/null"); environment.emplace_back("TERM=dumb");
    environment.emplace_back("PS1=tinyEnv$ "); environment.emplace_back("PS2=> ");
    std::vector<char*> env; env.reserve(environment.size() + 1);
    for (auto& value : environment) env.push_back(value.data());
    env.push_back(nullptr);
    const auto path = root.string();
    auto close_limit = ::sysconf(_SC_OPEN_MAX); if (close_limit < 0) close_limit = 65536;
    const int master = ::posix_openpt(O_RDWR | O_NOCTTY | O_CLOEXEC | O_NONBLOCK);
    int slave = -1, report[2]{-1, -1}, control[2]{-1, -1};
    auto failed = [&]() {
        if (master >= 0) ::close(master);
        if (slave >= 0) ::close(slave);
        for (const auto fd : {report[0], report[1], control[0], control[1]}) if (fd >= 0) ::close(fd);
        impl_->status.error = "Cannot create an owned Bash pseudoterminal";
    };
    if (master < 0 || ::grantpt(master) || ::unlockpt(master)) { failed(); return; }
    char name[4096];
    if (::ptsname_r(master, name, sizeof name) || (slave = ::open(name, O_RDWR | O_NOCTTY | O_CLOEXEC)) < 0 ||
        ::pipe2(report, O_CLOEXEC) || ::pipe2(control, O_CLOEXEC)) { failed(); return; }
    winsize size{}; size.ws_col = static_cast<unsigned short>(impl_->columns); size.ws_row = static_cast<unsigned short>(impl_->rows);
    if (::ioctl(slave, TIOCSWINSZ, &size) < 0) { failed(); return; }
    const auto owner = ::getpid();
    const auto supervisor = ::fork();
    if (supervisor < 0) { failed(); return; }
    if (!supervisor) supervise_terminal(owner, slave, report[1], control[0], path.c_str(), env.data(), close_limit);
    ::close(slave); ::close(report[1]); ::close(control[0]);
    impl_->master = master; impl_->report = report[0]; impl_->control = control[1]; impl_->supervisor = supervisor;
    impl_->receipt = {}; impl_->receipt_bytes = 0;
    ::fcntl(impl_->report, F_SETFL, O_NONBLOCK);
    impl_->status.running = true;
#else
    (void)root;
    impl_->status.error = "Persistent Bash pseudoterminals are currently supported on Linux";
#endif
}
void Terminal::send(std::string_view command) {
    if (!running()) throw std::logic_error("Start the chat terminal before sending a command");
    if (command.find('\0') != std::string_view::npos) throw std::invalid_argument("Terminal commands cannot contain NUL");
    if (command.size() >= 65536 || impl_->pending_input.size() + command.size() + 1 > 65536)
        throw std::invalid_argument("Terminal input queue exceeded 64 KiB");
    impl_->pending_input.append(command); impl_->pending_input += '\n';
#if defined(__linux__)
    impl_->flush_input();
#endif
}
TerminalStatus Terminal::drain() {
#if defined(__linux__)
    if (running()) {
        impl_->flush_input(); impl_->read_output();
        while (impl_->receipt_bytes < sizeof impl_->receipt) {
            const auto count = ::read(impl_->report, reinterpret_cast<char*>(&impl_->receipt) + impl_->receipt_bytes, sizeof impl_->receipt - impl_->receipt_bytes);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) break;
            impl_->receipt_bytes += static_cast<std::size_t>(count);
        }
        int native_status{};
        const auto done = ::waitpid(impl_->supervisor, &native_status, WNOHANG);
        if (done == impl_->supervisor || (done < 0 && errno == ECHILD)) {
            // Receipt can arrive between the first read and waitpid. An exited
            // supervisor has closed its writer, so collect its final bytes.
            while (impl_->receipt_bytes < sizeof impl_->receipt) {
                const auto count = ::read(impl_->report, reinterpret_cast<char*>(&impl_->receipt) + impl_->receipt_bytes, sizeof impl_->receipt - impl_->receipt_bytes);
                if (count < 0 && errno == EINTR) continue;
                if (count <= 0) break;
                impl_->receipt_bytes += static_cast<std::size_t>(count);
            }
            impl_->read_output();
            impl_->status.running = false; impl_->status.exit_code = impl_->receipt.code;
            if (done < 0 || !WIFEXITED(native_status) || WEXITSTATUS(native_status) ||
                impl_->receipt_bytes != sizeof impl_->receipt || impl_->receipt.magic != 0x54454e56)
                impl_->status.error = "Terminal descendant cleanup could not be confirmed";
            else if (impl_->receipt.error) impl_->status.error = "Terminal descendant cleanup failed";
            else if (!impl_->receipt.cancelled && impl_->receipt.code != 0)
                impl_->status.error = "Bash exited with code " + std::to_string(impl_->receipt.code);
            close_fd(impl_->master); close_fd(impl_->report); close_fd(impl_->control); impl_->supervisor = -1;
            impl_->pending_input.clear();
        }
    }
#endif
    impl_->status.output = printable(impl_->raw_output);
    if (impl_->status.output.size() > impl_->limit) { impl_->status.output_truncated = true; keep_tail(impl_->status.output, impl_->limit); }
    return impl_->status;
}
void Terminal::resize(unsigned columns, unsigned rows) {
    if (!columns || !rows || columns > 65535 || rows > 65535)
        throw std::invalid_argument("Terminal dimensions must be between 1 and 65535");
    impl_->columns = columns; impl_->rows = rows;
#if defined(__linux__)
    if (running()) {
        winsize size{}; size.ws_col = static_cast<unsigned short>(columns); size.ws_row = static_cast<unsigned short>(rows);
        if (::ioctl(impl_->master, TIOCSWINSZ, &size)) impl_->status.error = "Cannot resize the Bash terminal";
    }
#endif
}
void Terminal::interrupt() {
    if (!running()) return;
    if (impl_->pending_input.size() >= 65536) throw std::runtime_error("Terminal input queue is full");
    impl_->pending_input += '\3';
#if defined(__linux__)
    impl_->flush_input();
#endif
}
void Terminal::shutdown() {
    if (!running()) return;
#if defined(__linux__)
    // EOF is a cancellation request without a SIGPIPE race if Bash just exited.
    close_fd(impl_->control);
    impl_->pending_input.clear();
    while (running()) { (void)drain(); if (running()) std::this_thread::sleep_for(std::chrono::milliseconds(5)); }
#endif
}

struct GitStatusJob::Impl {
    enum class Stage { repository, objects, filters, files, attributes, status };
    ProcessRunner process{2 * 1024 * 1024};
    GitStatus status;
    std::filesystem::path root, trust_root;
    std::vector<std::string> arguments;
    std::set<std::string> drivers;
    std::vector<std::string> tracked_paths;
    std::size_t checked_paths{}, batch_end{};
    Stage stage{Stage::repository};
    void launch(Stage next, const std::vector<std::string>& command) {
        auto argv = arguments; argv.insert(argv.end(), command.begin(), command.end());
        // GIT_CONFIG redirects the config builtin but is ignored by status.
        // Remove it only in the owned child; never mutate the GUI environment.
        // The interpreter and this fixed code are configured application inputs,
        // and isolated mode excludes project/PYTHONPATH/user-site imports.
        const auto python = text_path(TINYENV_PYTHON_EXECUTABLE);
        if (!python.is_absolute() || !std::filesystem::is_regular_file(python))
            throw std::runtime_error("A configured absolute Python executable is required for local Git inspection");
        std::vector<std::string> child{path_text(python), "-I", "-B", "-c",
            "import os, subprocess, sys\nenvironment = dict(os.environ)\nenvironment.pop('GIT_CONFIG', None)\n"
            "for key in ('GIT_TRACE', 'GIT_TRACE_SETUP', 'GIT_TRACE_PERFORMANCE', 'GIT_TRACE_PACK_ACCESS', 'GIT_TRACE_PACKFILE', 'GIT_TRACE_PACKET', 'GIT_TRACE_CURL', 'GIT_TRACE2', 'GIT_TRACE2_PERF', 'GIT_TRACE2_EVENT', 'GIT_CURL_VERBOSE'):\n    environment[key] = '0'\n"
            "environment['GIT_NO_LAZY_FETCH'] = '1'\nsys.exit(subprocess.call(sys.argv[1:], env=environment, shell=False))\n"};
        child.insert(child.end(), argv.begin(), argv.end());
        process.start(child, root); stage = next;
    }
    void launch_status() {
        std::vector<std::string> command;
        std::size_t bytes = 0;
        for (const auto& driver : drivers) {
            for (const auto* setting : {"clean=", "process=", "required=false"}) {
                auto key = "filter." + driver + "." + setting;
                bytes += key.size() + 8;
                if (bytes > 16 * 1024) throw std::runtime_error("Git filter override limit exceeded");
                command.emplace_back("-c"); command.push_back(std::move(key));
            }
        }
        command.insert(command.end(), {"status", "--porcelain=v1", "-z", "--branch", "--untracked-files=normal", "--ignore-submodules=all"});
        launch(Stage::status, command);
    }
    void launch_attributes() {
        if (checked_paths == tracked_paths.size()) { launch_status(); return; }
        std::vector<std::string> command{"check-attr", "-z", "filter", "--"};
        std::size_t bytes = 0; batch_end = checked_paths;
        while (batch_end < tracked_paths.size() && batch_end - checked_paths < 128) {
            const auto cost = tracked_paths[batch_end].size() + 4;
            if (cost > 16 * 1024) throw std::runtime_error("Git path exceeds safe argument bounds");
            if (bytes + cost > 16 * 1024) break;
            bytes += cost; command.push_back(tracked_paths[batch_end++]);
        }
        launch(Stage::attributes, command);
    }
};
GitStatusJob::GitStatusJob() : impl_(std::make_unique<Impl>()) {}
GitStatusJob::~GitStatusJob() { if (running()) (void)cancel(); }
bool GitStatusJob::running() const noexcept { return impl_->status.state == ServiceState::running; }
void GitStatusJob::start(const std::filesystem::path& cwd, const std::filesystem::path& project_root) {
    if (running()) throw std::logic_error("Git status is already running");
    impl_->root = directory(cwd);
    impl_->trust_root = project_root.empty() ? impl_->root : directory(project_root);
    if (!inside(impl_->trust_root, impl_->root)) throw std::invalid_argument("Git working directory must belong to the selected project");
    impl_->status = {};
    impl_->drivers.clear(); impl_->tracked_paths.clear(); impl_->checked_paths = 0;
#if defined(_WIN32)
    const std::string null_hooks = "NUL";
#else
    const std::string null_hooks = "/dev/null";
#endif
    impl_->arguments = {trusted_git_path(impl_->trust_root), "--no-optional-locks", "--no-pager", "-c", "core.fsmonitor=",
                        "-c", "core.untrackedCache=false", "-c", "core.hooksPath=" + null_hooks, "-C", path_text(impl_->root)};
    impl_->launch(Impl::Stage::repository, {"rev-parse", "--show-toplevel"});
    impl_->status.state = ServiceState::running;
}
GitStatus GitStatusJob::poll() {
    if (!running()) return impl_->status;
    const auto process = impl_->process.poll();
    if (!process.finished()) return impl_->status;
    if (impl_->stage != Impl::Stage::status) {
        try {
            const bool empty_filters = impl_->stage == Impl::Stage::filters && process.exit_code == 1 && process.output.empty();
            if (process.output_truncated || (process.state != ProcessState::succeeded && !empty_filters))
                throw std::runtime_error("Git preflight failed");
            if (impl_->stage == Impl::Stage::repository) {
                auto path = process.output;
                if (path.empty() || path.size() > 16384 || path.back() != '\n') throw std::runtime_error("Invalid Git repository root");
                path.pop_back(); if (!path.empty() && path.back() == '\r') path.pop_back();
                const auto resolved = directory(text_path(path));
                if (!inside(resolved, impl_->root)) throw std::runtime_error("Git repository does not contain the selected chat directory");
                impl_->root = resolved;
                if (inside(impl_->root, impl_->trust_root)) impl_->trust_root = impl_->root;
                impl_->arguments.front() = trusted_git_path(impl_->trust_root);
                impl_->arguments.back() = path_text(impl_->root);
                impl_->launch(Impl::Stage::objects, {"rev-parse", "--git-path", "objects"});
            } else if (impl_->stage == Impl::Stage::objects) {
                auto path = process.output;
                if (path.empty() || path.size() > 16384 || path.back() != '\n') throw std::runtime_error("Invalid Git object directory");
                path.pop_back(); if (!path.empty() && path.back() == '\r') path.pop_back();
                auto objects = text_path(path);
                if (objects.is_relative()) objects = impl_->root / objects;
                objects = directory(objects);
                bool unavailable = false;
                std::size_t entries = 0;
                const auto packs = objects / "pack";
                if (std::filesystem::exists(packs)) for (const auto& entry : std::filesystem::directory_iterator(packs)) {
                    if (++entries > 10000) throw std::runtime_error("Git object inventory limit exceeded");
                    if (entry.path().extension() == ".promisor") unavailable = true;
                }
                const auto alternates = objects / "info" / "alternates";
                if (std::filesystem::exists(alternates) && std::filesystem::file_size(alternates)) unavailable = true;
                if (const auto* inherited = std::getenv("GIT_ALTERNATE_OBJECT_DIRECTORIES"); inherited && *inherited) unavailable = true;
                if (unavailable) {
                    impl_->status.state = ServiceState::failed;
                    impl_->status.error = "Git status requires a complete local object store without promisor or alternate object dependencies";
                    return impl_->status;
                }
                impl_->launch(Impl::Stage::filters, {"config", "--null", "--get-regexp",
                    "^(filter\\..*\\.(clean|process)|extensions\\.partialclone|remote\\..*\\.promisor)$"});
            } else if (impl_->stage == Impl::Stage::filters) {
                std::size_t begin = 0;
                std::map<std::string, std::string> definitions;
                while (begin < process.output.size()) {
                    const auto end = process.output.find('\0', begin);
                    const auto value = process.output.find('\n', begin);
                    if (end == std::string::npos || value == std::string::npos || value >= end) throw std::runtime_error("Invalid Git filter record");
                    const auto key = process.output.substr(begin, value - begin);
                    if (key.starts_with("filter.")) {
                        const auto suffix = key.rfind('.');
                        if (suffix == std::string::npos || suffix <= 7) throw std::runtime_error("Invalid Git filter key");
                        const auto driver = key.substr(7, suffix - 7);
                        if (!std::all_of(driver.begin(), driver.end(), [](unsigned char c) {
                            return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-';
                        })) throw std::runtime_error("Unsupported Git filter driver name");
                    } else if (key != "extensions.partialclone" && !(key.starts_with("remote.") && key.ends_with(".promisor")))
                        throw std::runtime_error("Unexpected Git safety configuration");
                    // Git applies the last definition of each setting. An
                    // earlier command followed by an empty value is disabled.
                    definitions[key] = process.output.substr(value + 1, end - value - 1);
                    if (definitions.size() > 2048) throw std::runtime_error("Git filter limit exceeded");
                    begin = end + 1;
                }
                for (const auto& [key, definition] : definitions) {
                    if (key.starts_with("filter.")) {
                        if (!definition.empty()) impl_->drivers.insert(key.substr(7, key.rfind('.') - 7));
                    } else {
                        auto boolean = definition;
                        for (auto& c : boolean) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
                        const bool disabled = boolean == "false" || boolean == "no" || boolean == "off" || boolean == "0";
                        if ((key == "extensions.partialclone" && !definition.empty()) || (key != "extensions.partialclone" && !disabled)) {
                            impl_->status.state = ServiceState::failed;
                            impl_->status.error = "Git status is unavailable for partial clones or promisor remotes";
                            return impl_->status;
                        }
                    }
                }
                if (impl_->drivers.empty()) impl_->launch_status();
                else impl_->launch(Impl::Stage::files, {"ls-files", "--cached", "-z"});
            } else if (impl_->stage == Impl::Stage::files) {
                if (process.output.size() > 512 * 1024) throw std::runtime_error("Git path inventory limit exceeded");
                std::size_t begin = 0;
                while (begin < process.output.size()) {
                    const auto end = process.output.find('\0', begin);
                    if (end == std::string::npos || end == begin) throw std::runtime_error("Invalid Git tracked path");
                    impl_->tracked_paths.push_back(process.output.substr(begin, end - begin));
                    if (impl_->tracked_paths.size() > 10000) throw std::runtime_error("Git path count limit exceeded");
                    begin = end + 1;
                }
                impl_->launch_attributes();
            } else {
                std::size_t begin = 0;
                auto next = [&]() {
                    const auto end = process.output.find('\0', begin);
                    if (end == std::string::npos) throw std::runtime_error("Incomplete Git attribute record");
                    auto value = process.output.substr(begin, end - begin); begin = end + 1; return value;
                };
                for (auto index = impl_->checked_paths; index < impl_->batch_end; ++index) {
                    const auto path = next(), attribute = next(), value = next();
                    if (path != impl_->tracked_paths[index] || attribute != "filter") throw std::runtime_error("Invalid Git attribute identity");
                    if (impl_->drivers.contains(value)) {
                        impl_->status.state = ServiceState::failed;
                        impl_->status.error = "Git status is unavailable because tracked files use external content filters";
                        return impl_->status;
                    }
                }
                if (begin != process.output.size()) throw std::runtime_error("Unexpected Git attribute record");
                impl_->checked_paths = impl_->batch_end; impl_->launch_attributes();
            }
        } catch (const std::exception&) {
            impl_->status.state = ServiceState::failed;
            impl_->status.error = "Cannot complete the bounded local Git safety preflight";
        }
        return impl_->status;
    }
    impl_->status.state = service_state(process.state);
    if (process.state != ProcessState::succeeded || process.output_truncated) {
        impl_->status.error = process.output_truncated ? "Git status exceeded its byte limit" : "Cannot read Git status for this directory";
        return impl_->status;
    }
    std::size_t begin = 0;
    auto next = [&]() -> std::optional<std::string> {
        if (begin == process.output.size()) return std::nullopt;
        const auto end = process.output.find('\0', begin);
        if (end == std::string::npos) throw std::runtime_error("Incomplete Git status record");
        auto record = process.output.substr(begin, end - begin); begin = end + 1; return record;
    };
    try {
        while (auto record = next()) {
            if (record->starts_with("## ")) { impl_->status.branch = printable(record->substr(3)); continue; }
            if (record->size() < 4 || (*record)[2] != ' ') throw std::runtime_error("Invalid Git status record");
            GitFile file{(*record)[0], (*record)[1], record->substr(3), {}};
            if (file.index_status == 'R' || file.index_status == 'C' || file.worktree_status == 'R' || file.worktree_status == 'C') {
                const auto original = next();
                if (!original) throw std::runtime_error("Missing Git rename origin");
                file.original_path = *original;
            }
            impl_->status.files.push_back(std::move(file));
        }
    } catch (const std::exception&) {
        impl_->status.state = ServiceState::failed; impl_->status.files.clear();
        impl_->status.error = "Git returned an invalid status response";
    }
    return impl_->status;
}
GitStatus GitStatusJob::cancel() {
    if (!running()) return impl_->status;
    const auto process = impl_->process.cancel(); impl_->status.state = process.state == ProcessState::failed ? ServiceState::failed : ServiceState::cancelled;
    if (process.state == ProcessState::failed) impl_->status.error = "Git cancellation cleanup could not be confirmed";
    return impl_->status;
}
} // namespace tinyenv
