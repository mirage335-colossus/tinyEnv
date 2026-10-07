#pragma once
#include <gui/runtime.hpp>
#include <atomic>
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <thread>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace foundation::host {
namespace file_detail {
struct File {
    int fd = -1;
    File(const std::filesystem::path& path, bool write) {
#ifdef _WIN32
        fd = _wopen(path.c_str(), _O_BINARY | _O_NOINHERIT |
            (write ? _O_WRONLY | _O_CREAT | _O_EXCL : _O_RDONLY), _S_IREAD | _S_IWRITE);
#else
        fd = ::open(path.c_str(), O_CLOEXEC | O_NONBLOCK |
            (write ? O_WRONLY | O_CREAT | O_EXCL : O_RDONLY), 0600);
#endif
    }
    File(const File&) = delete;
    ~File() { close(); }
    bool close() noexcept {
        if (fd < 0) return true;
#ifdef _WIN32
        const int result = _close(fd);
#else
        const int result = ::close(fd);
#endif
        fd = -1; return result == 0;
    }
    bool regular() const {
#ifdef _WIN32
        struct _stat64 info{};
        return _fstat64(fd, &info) == 0 && (info.st_mode & _S_IFMT) == _S_IFREG;
#else
        struct stat info{}; return ::fstat(fd, &info) == 0 && S_ISREG(info.st_mode);
#endif
    }
    int read(char* buffer, unsigned count) const {
#ifdef _WIN32
        return _read(fd, buffer, count);
#else
        return static_cast<int>(::read(fd, buffer, count));
#endif
    }
    int write(const char* buffer, unsigned count) const {
#ifdef _WIN32
        return _write(fd, buffer, count);
#else
        return static_cast<int>(::write(fd, buffer, count));
#endif
    }
};
inline gui::ServiceResult transfer(const gui::ServiceRequest& request,
                                   const std::filesystem::path& path, const std::atomic_bool& stop) {
    gui::ServiceResult result{request.id, gui::ServiceStatus::success, {}, {}};
    bool committed = false;
    if (request.byte_limit > 65536 || request.value.size() > request.byte_limit)
        throw std::length_error("File content exceeds its byte limit");
    if (request.kind == gui::ServiceKind::read_text) {
        File file(path, false);
        if (file.fd < 0 || !file.regular()) throw std::runtime_error("Select a readable regular file");
        char buffer[4096];
        while (!stop) {
            const int count = file.read(buffer, sizeof buffer);
            if (count < 0) { if (errno == EINTR) continue; throw std::runtime_error("Cannot read selected file"); }
            if (count == 0) break;
            if (static_cast<std::size_t>(count) > request.byte_limit - result.value.size())
                throw std::length_error("Selected file exceeds the byte limit");
            result.value.append(buffer, static_cast<std::size_t>(count));
        }
    } else if (request.kind == gui::ServiceKind::write_text) {
        // Exclusive temporary creation avoids truncating the chosen destination
        // on cancellation or a failed write. Rename replaces it only on success.
        static std::atomic_uint64_t serial{0};
        auto temporary = path;
        temporary += ".foundation-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
                     "-" + std::to_string(++serial) + ".tmp";
        File file(temporary, true);
        if (file.fd < 0) throw std::runtime_error("Cannot create export beside selected destination");
        struct Cleanup {
            File& file; std::filesystem::path path;
            ~Cleanup() { file.close(); std::error_code error; std::filesystem::remove(path, error); }
        } cleanup{file, temporary};
        std::size_t offset = 0;
        while (offset < request.value.size() && !stop) {
            const int count = file.write(request.value.data() + offset,
                static_cast<unsigned>(std::min<std::size_t>(4096, request.value.size() - offset)));
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) throw std::runtime_error("Cannot write selected file");
            offset += static_cast<std::size_t>(count);
        }
        if (!file.close()) throw std::runtime_error("Cannot close exported file");
        if (!stop) {
#ifdef _WIN32
            if (!MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING))
                throw std::runtime_error("Cannot replace selected destination");
#else
            std::error_code error; std::filesystem::rename(temporary, path, error);
            if (error) throw std::runtime_error("Cannot replace selected destination");
#endif
            committed = true;
        }
    } else throw std::invalid_argument("Unknown content service");
    if (stop && !committed) { result.status = gui::ServiceStatus::cancelled; result.value.clear(); }
    return result;
}
}
// One bounded content operation per session. No worker touches application,
// adapter, dialog, or callback state. Poll and shutdown run on the UI owner.
class FileServices {
    std::thread worker_;
    std::atomic_bool stop_{false};
    std::mutex mutex_;
    std::optional<gui::ServiceResult> result_;
public:
    ~FileServices() { shutdown(); }
    template<class Adapter, class Reply> void service(Adapter& adapter, gui::ServiceRequest request, Reply reply) {
        if (request.kind != gui::ServiceKind::read_text && request.kind != gui::ServiceKind::write_text) {
            adapter.service(std::move(request), std::move(reply)); return;
        }
        auto selection = request;
        // The retained adapters all offer a path prompt. A platform may replace
        // this generic selector with a native chooser without changing App.
        selection.kind = gui::ServiceKind::prompt;
        selection.title += " - file path";
        selection.value.clear(); selection.byte_limit = 32768;
        adapter.service(std::move(selection), [this, &adapter, request = std::move(request), reply = std::move(reply)](gui::ServiceResult result) {
            if (adapter.closed()) return;
            if (result.status != gui::ServiceStatus::success) { reply(std::move(result)); return; }
            try { start(request, std::filesystem::path(std::u8string(result.value.begin(), result.value.end()))); }
            catch (const std::exception& error) { reply({request.id, gui::ServiceStatus::error, {}, error.what()}); }
        });
    }
    bool active() const noexcept { return worker_.joinable(); }
    void start(gui::ServiceRequest request, std::filesystem::path path) {
        if (active()) throw std::logic_error("File service already active");
        stop_ = false;
        worker_ = std::thread([this, request = std::move(request), path = std::move(path)] {
            gui::ServiceResult result;
            try { result = file_detail::transfer(request, path, stop_); }
            catch (const std::exception& error) { result = {request.id, gui::ServiceStatus::error, {}, error.what()}; }
            std::lock_guard lock(mutex_); result_ = std::move(result);
        });
    }
    std::optional<gui::ServiceResult> poll() {
        std::optional<gui::ServiceResult> result;
        { std::lock_guard lock(mutex_); result.swap(result_); }
        if (result && worker_.joinable()) worker_.join();
        return result;
    }
    void shutdown() noexcept {
        stop_ = true;
        if (worker_.joinable()) worker_.join();
        std::lock_guard lock(mutex_); result_.reset();
    }
};
} // namespace foundation::host
