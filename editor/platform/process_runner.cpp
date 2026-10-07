#include "process_runner.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <utility>

#if defined(__linux__)
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#elif defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#endif

namespace foundation::editor {
#if defined(__linux__)
struct LinuxReceipt { int magic{}, code{}, cancelled{}, outlived{}, error{}; };
#endif
struct ProcessRunner::Impl {
    ProcessStatus status;
    std::size_t limit;
#if defined(__linux__)
    pid_t supervisor{-1};
    int output{-1}, report{-1}, control{-1};
    LinuxReceipt receipt;
    std::size_t receipt_bytes{};
#elif defined(_WIN32)
    HANDLE job{}, process{}, output{};
#endif
    explicit Impl(std::size_t bytes) : limit(bytes) {}
    void append(const char* data, std::size_t bytes) {
        const auto keep = std::min(bytes, limit - status.output.size());
        status.output.append(data, keep);
        if (keep < bytes) status.output_truncated = true;
    }
};
namespace {
#if defined(__linux__)
void close_fd(int& fd) noexcept { if (fd >= 0) ::close(std::exchange(fd, -1)); }
// The supervisor remains single-threaded and uses only native/async-signal-safe
// operations after fork. Direct children cannot reuse their PID before we reap.
// Killing direct children causes escaped groups/sessions to be adopted, so every
// descendant is joined before the final receipt. This is cooperative ownership,
// not confinement against programs transferring writers to an external service.
void supervise(pid_t owner, int output, int report, int control, const char* executable,
               char* const* argv, const char* cwd, long close_limit) noexcept {
    int keep[3]{output,report,control};
    if(keep[0]>keep[1]) std::swap(keep[0],keep[1]);
    if(keep[1]>keep[2]) std::swap(keep[1],keep[2]);
    if(keep[0]>keep[1]) std::swap(keep[0],keep[1]);
    bool ranges=true; unsigned first=3;
#ifdef SYS_close_range
    for(int i=0;i<3;++i) {
        if(first<static_cast<unsigned>(keep[i]) && ::syscall(SYS_close_range,first,static_cast<unsigned>(keep[i]-1),0)!=0) ranges=false;
        first=static_cast<unsigned>(keep[i]+1);
    }
    if(::syscall(SYS_close_range,first,~0u,0)!=0) ranges=false;
#else
    ranges=false;
#endif
    if(!ranges) for (int fd = 3; fd < close_limit; ++fd) if (fd != output && fd != report && fd != control) ::close(fd);
    LinuxReceipt receipt{0x45444954, -1, 0, 0, 0};
    if (::prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0) receipt.error = errno;
    if (::fcntl(control, F_SETFL, O_NONBLOCK) < 0) receipt.error = errno;
    if (::getppid() != owner) receipt.cancelled = 1;
    char child_path[128];
    // /proc/self/task/<tid>/children is needed before any command may run.
    const auto number = ::getpid();
    char digits[24]; int n = 0; auto value = number;
    do { digits[n++] = static_cast<char>('0' + value % 10); value /= 10; } while (value);
    const char prefix[] = "/proc/self/task/";
    std::size_t length = sizeof(prefix) - 1;
    std::memcpy(child_path, prefix, length);
    while (n) child_path[length++] = digits[--n];
    const char suffix[] = "/children";
    std::memcpy(child_path + length, suffix, sizeof suffix);
    int inventory = ::open(child_path, O_RDONLY | O_CLOEXEC);
    if (inventory < 0) receipt.error = errno;
    else ::close(inventory);
    char request;
    const auto requested = ::read(control, &request, 1);
    if (requested >= 0) receipt.cancelled = 1;
    pid_t primary = -1;
    if (!receipt.error && !receipt.cancelled) {
        primary = ::fork();
        if (primary < 0) receipt.error = errno;
        else if (primary == 0) {
            ::close(report); ::close(control);
            int null = ::open("/dev/null", O_RDONLY);
            if (null < 0) ::_exit(126);
            ::dup2(null, STDIN_FILENO); if (null > 2) ::close(null);
            ::dup2(output, STDOUT_FILENO); ::dup2(output, STDERR_FILENO);
            if (output > 2) ::close(output);
            if (::chdir(cwd) != 0) { const char message[] = "Cannot enter process working directory\n"; ::write(STDERR_FILENO, message, sizeof(message)-1); ::_exit(126); }
            ::execv(executable, argv);
            const char message[] = "Cannot execute configured command\n";
            ::write(STDERR_FILENO, message, sizeof(message)-1); ::_exit(127);
        }
    }
    ::close(output);
    for (;;) {
        if (::getppid() != owner) receipt.cancelled = 1;
        const auto got = ::read(control, &request, 1);
        if (got >= 0) receipt.cancelled = 1; // EOF also means owner disappeared.
        bool empty = false;
        for (;;) {
            int status;
            const auto reaped = ::waitpid(-1, &status, WNOHANG);
            if (reaped < 0 && errno == EINTR) continue;
            if (reaped < 0 && errno == ECHILD) { empty = true; break; }
            if (reaped < 0) { receipt.error = errno; break; }
            if (reaped == 0) break;
            if (reaped == primary) receipt.code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
        }
        if (empty) break;
        if (receipt.code >= 0 && !receipt.cancelled) receipt.outlived = 1;
        if (receipt.cancelled || receipt.outlived || receipt.error) {
            inventory = ::open(child_path, O_RDONLY | O_CLOEXEC);
            if (inventory >= 0) {
                char children[65536];
                const auto count = ::read(inventory, children, sizeof(children)); ::close(inventory);
                if (count < 0 || count == static_cast<ssize_t>(sizeof(children))) receipt.error = EOVERFLOW;
                else {
                    pid_t child = 0;
                    for (ssize_t i = 0; i <= count; ++i) {
                        const char c = i == count ? ' ' : children[i];
                        if (c >= '0' && c <= '9') child = child * 10 + (c - '0');
                        else if (child > 0) { if (::kill(child, SIGKILL) != 0 && errno != ESRCH) receipt.error = errno; child = 0; }
                    }
                }
            } else receipt.error = errno;
        }
        // poll provides an interruptible small wait without allocating or locks.
        ::poll(nullptr, 0, 10);
    }
    if (receipt.code < 0 && !receipt.cancelled && !receipt.error) receipt.error = ECHILD;
    const auto bytes = ::write(report, &receipt, sizeof receipt);
    ::close(report); ::close(control); ::_exit(bytes == sizeof receipt ? 0 : 125);
}
std::string executable_path(const std::string& command, const std::filesystem::path& cwd) {
    if (command.find('/') != std::string::npos) {
        auto p = std::filesystem::path(command);
        if (p.is_relative()) p = cwd / p;
        return p.string();
    }
    const char* env = ::getenv("PATH");
    const std::string path = env ? env : "/usr/bin:/bin";
    std::size_t begin = 0;
    for (;;) {
        const auto end = path.find(':', begin);
        auto directory = path.substr(begin, end == std::string::npos ? end : end - begin);
        auto p = directory.empty() ? cwd / command : std::filesystem::path(directory) / command;
        if (p.is_relative()) p = cwd / p;
        if (::access(p.c_str(), X_OK) == 0) return p.string();
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    return {};
}
#elif defined(_WIN32)
std::wstring wide(const std::string& text) {
    const auto n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (!n && !text.empty()) throw std::invalid_argument("Command arguments must be UTF-8");
    std::wstring result(n, L'\0'); MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), result.data(), n); return result;
}
std::wstring quoted(const std::string& argument) {
    const auto input = wide(argument); std::wstring result = L"\""; unsigned slashes = 0;
    for (const wchar_t c : input) {
        if (c == L'\\') { ++slashes; continue; }
        if (c == L'\"') { result.append(slashes * 2 + 1, L'\\'); result += c; }
        else { result.append(slashes, L'\\'); result += c; }
        slashes = 0;
    }
    result.append(slashes * 2, L'\\'); result += L'\"'; return result;
}
void close_handle(HANDLE& h) noexcept { if (h) CloseHandle(std::exchange(h, nullptr)); }
#endif
} // namespace

ProcessRunner::ProcessRunner(std::size_t max_log_bytes) : impl_(std::make_unique<Impl>(max_log_bytes)) {
    if (!max_log_bytes) throw std::invalid_argument("Process log byte limit must be positive");
}
ProcessRunner::~ProcessRunner() { if (running()) (void)cancel(); }
bool ProcessRunner::running() const noexcept { return impl_->status.state == ProcessState::running; }
void ProcessRunner::start(const std::vector<std::string>& argv, const std::filesystem::path& cwd) {
    if (running()) throw std::logic_error("A command is already running");
    if (argv.empty() || argv.front().empty()) throw std::invalid_argument("An executable argument is required");
    for (const auto& arg : argv) if (arg.find('\0') != std::string::npos) throw std::invalid_argument("Command arguments cannot contain NUL");
    if (cwd.empty() || !std::filesystem::is_directory(cwd)) throw std::invalid_argument("An existing process working directory is required");
    impl_->status = {}; impl_->status.state = ProcessState::running;
#if defined(__linux__)
    const auto directory = std::filesystem::absolute(cwd).string();
    const auto executable = executable_path(argv[0], directory);
    if(executable.empty()) { impl_->status.state=ProcessState::failed; impl_->status.exit_code=127; impl_->status.error="Executable was not found in PATH"; return; }
    std::vector<char*> arguments; arguments.reserve(argv.size() + 1);
    for (const auto& arg : argv) arguments.push_back(const_cast<char*>(arg.c_str()));
    arguments.push_back(nullptr);
    int out[2]{-1,-1}, receipt[2]{-1,-1}, control[2]{-1,-1};
    auto failure = [&](const char* operation) {
        const auto error = errno;
        for (auto* pair : {out, receipt, control}) { if (pair[0] >= 0) ::close(pair[0]); if (pair[1] >= 0) ::close(pair[1]); }
        impl_->status.state = ProcessState::failed; impl_->status.error = std::string(operation) + ": " + std::strerror(error);
    };
    if (::pipe2(out, O_CLOEXEC) || ::pipe2(receipt, O_CLOEXEC) || ::pipe2(control, O_CLOEXEC)) { failure("Cannot create command pipes"); return; }
    auto descriptor_limit = ::sysconf(_SC_OPEN_MAX); if (descriptor_limit < 0) descriptor_limit = 65536;
    const auto owner = ::getpid();
    const auto supervisor = ::fork();
    if (supervisor < 0) { failure("Cannot launch command supervisor"); return; }
    if (supervisor == 0) supervise(owner, out[1], receipt[1], control[0], executable.c_str(), arguments.data(), directory.c_str(), descriptor_limit);
    ::close(out[1]); ::close(receipt[1]); ::close(control[0]);
    impl_->supervisor = supervisor; impl_->output = out[0]; impl_->report = receipt[0]; impl_->control = control[1];
    impl_->receipt = {}; impl_->receipt_bytes = 0;
    ::fcntl(impl_->output, F_SETFL, O_NONBLOCK); ::fcntl(impl_->report, F_SETFL, O_NONBLOCK);
#elif defined(_WIN32)
    HANDLE outgoing{}, input{}; SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
    auto fail = [&](std::string message) {
        if (outgoing) CloseHandle(outgoing); if (input && input != INVALID_HANDLE_VALUE) CloseHandle(input);
        if (impl_->job) TerminateJobObject(impl_->job, 125);
        if (impl_->process) WaitForSingleObject(impl_->process, INFINITE);
        if (impl_->job) {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
            while (QueryInformationJobObject(impl_->job, JobObjectBasicAccountingInformation, &accounting, sizeof accounting, nullptr) && accounting.ActiveProcesses) Sleep(5);
        }
        close_handle(impl_->output); close_handle(impl_->process); close_handle(impl_->job);
        impl_->status.state = ProcessState::failed; impl_->status.error = std::move(message);
    };
    if (!CreatePipe(&impl_->output, &outgoing, &security, 0) || !SetHandleInformation(impl_->output, HANDLE_FLAG_INHERIT, 0)) { fail("Cannot create command output pipe"); return; }
    input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    impl_->job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{}; limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (input == INVALID_HANDLE_VALUE || !impl_->job || !SetInformationJobObject(impl_->job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) { fail("Cannot prepare owned command job"); return; }
    std::wstring command;
    for (const auto& arg : argv) { if (!command.empty()) command += L' '; command += quoted(arg); }
    STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES; startup.StartupInfo.hStdInput = input; startup.StartupInfo.hStdOutput = outgoing; startup.StartupInfo.hStdError = outgoing;
    SIZE_T attributes_size = 0; InitializeProcThreadAttributeList(nullptr, 1, 0, &attributes_size);
    std::vector<unsigned char> attributes(attributes_size);
    startup.lpAttributeList = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes.data());
    HANDLE inherited[2]{input,outgoing};
    if (!InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &attributes_size) || !UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited, sizeof(inherited), nullptr, nullptr)) { fail("Cannot restrict command handle inheritance"); return; }
    PROCESS_INFORMATION process{};
    const auto made = CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE, CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT, nullptr, std::filesystem::absolute(cwd).c_str(), &startup.StartupInfo, &process);
    DeleteProcThreadAttributeList(startup.lpAttributeList);
    if (!made) { fail("Cannot execute configured command (Windows error " + std::to_string(GetLastError()) + ")"); return; }
    impl_->process = process.hProcess;
    if (!AssignProcessToJobObject(impl_->job, impl_->process)) { TerminateProcess(process.hProcess, 125); WaitForSingleObject(process.hProcess, INFINITE); CloseHandle(process.hThread); fail("Cannot assign command to an owned non-breakaway job"); return; }
    if (ResumeThread(process.hThread) == static_cast<DWORD>(-1)) { CloseHandle(process.hThread); fail("Cannot resume owned command"); return; }
    CloseHandle(process.hThread); CloseHandle(outgoing); CloseHandle(input);
#else
    impl_->status.state = ProcessState::failed; impl_->status.error = "Owned command execution is unavailable on this platform";
#endif
}
ProcessStatus ProcessRunner::poll() {
    if (!running()) return impl_->status;
#if defined(__linux__)
    char bytes[16384];
    for (;;) {
        const auto got = ::read(impl_->output, bytes, sizeof bytes);
        if (got > 0) impl_->append(bytes, static_cast<std::size_t>(got));
        else if (got < 0 && errno == EINTR) continue;
        else break;
    }
    while (impl_->receipt_bytes < sizeof impl_->receipt) {
        const auto got = ::read(impl_->report, reinterpret_cast<char*>(&impl_->receipt) + impl_->receipt_bytes, sizeof impl_->receipt - impl_->receipt_bytes);
        if (got > 0) impl_->receipt_bytes += static_cast<std::size_t>(got);
        else if (got < 0 && errno == EINTR) continue;
        else break;
    }
    int status{}; const auto done = ::waitpid(impl_->supervisor, &status, WNOHANG);
    if (done == impl_->supervisor) {
        // Receipt is sent only after ECHILD; all inherited writers have closed.
        while (impl_->receipt_bytes < sizeof impl_->receipt) {
            const auto got=::read(impl_->report,reinterpret_cast<char*>(&impl_->receipt)+impl_->receipt_bytes,sizeof impl_->receipt-impl_->receipt_bytes);
            if(got>0) impl_->receipt_bytes+=static_cast<std::size_t>(got); else if(got<0 && errno==EINTR) continue; else break;
        }
        for (;;) { const auto got = ::read(impl_->output, bytes, sizeof bytes); if (got <= 0) break; impl_->append(bytes, static_cast<std::size_t>(got)); }
        impl_->status.exit_code = impl_->receipt.code;
        if (!WIFEXITED(status) || WEXITSTATUS(status) || impl_->receipt_bytes != sizeof impl_->receipt || impl_->receipt.magic != 0x45444954) {
            impl_->status.state = ProcessState::failed; impl_->status.error = "Command supervisor completion could not be confirmed";
        } else if (impl_->receipt.error) {
            impl_->status.state = ProcessState::failed; impl_->status.error = std::string("Owned command cleanup failed: ") + std::strerror(impl_->receipt.error);
        } else if (impl_->receipt.cancelled) impl_->status.state = ProcessState::cancelled;
        else if (impl_->receipt.outlived) { impl_->status.state = ProcessState::failed; impl_->status.error = "Command left running descendants; they were terminated and joined"; }
        else impl_->status.state = impl_->receipt.code == 0 ? ProcessState::succeeded : ProcessState::failed;
        close_fd(impl_->output); close_fd(impl_->report); close_fd(impl_->control); impl_->supervisor = -1;
    }
#elif defined(_WIN32)
    char bytes[16384]; DWORD available{};
    while (PeekNamedPipe(impl_->output, nullptr, 0, nullptr, &available, nullptr) && available) {
        DWORD got{}; if (!ReadFile(impl_->output, bytes, std::min<DWORD>(available, sizeof bytes), &got, nullptr) || !got) break;
        impl_->append(bytes, got);
    }
    DWORD code{};
    if (GetExitCodeProcess(impl_->process, &code) && code != STILL_ACTIVE) {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
        if (!QueryInformationJobObject(impl_->job, JobObjectBasicAccountingInformation, &accounting, sizeof accounting, nullptr)) return impl_->status;
        if (accounting.ActiveProcesses) { TerminateJobObject(impl_->job, 125); impl_->status.error = "Command left running descendants; terminating owned job"; return impl_->status; }
        while (PeekNamedPipe(impl_->output, nullptr, 0, nullptr, &available, nullptr) && available) {
            DWORD got{}; if (!ReadFile(impl_->output, bytes, std::min<DWORD>(available, sizeof bytes), &got, nullptr) || !got) break;
            impl_->append(bytes, got);
        }
        impl_->status.exit_code = static_cast<int>(code);
        impl_->status.state = code == 0 && impl_->status.error.empty() ? ProcessState::succeeded : ProcessState::failed;
        close_handle(impl_->output); close_handle(impl_->process); close_handle(impl_->job);
    }
#endif
    return impl_->status;
}
ProcessStatus ProcessRunner::cancel() {
    if (!running()) return impl_->status;
#if defined(__linux__)
    // Avoid SIGPIPE if the supervisor completed before receiving this request.
    // Closing the control pipe is also an unambiguous stop request (EOF).
    close_fd(impl_->control);
#elif defined(_WIN32)
    TerminateJobObject(impl_->job, 125);
#endif
    while (running()) { (void)poll(); if (running()) std::this_thread::sleep_for(std::chrono::milliseconds(5)); }
    if (impl_->status.error.empty()) impl_->status.state = ProcessState::cancelled;
    return impl_->status;
}
} // namespace foundation::editor
