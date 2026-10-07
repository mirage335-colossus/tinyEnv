#include "project_files.hpp"
#include "content_digest.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <limits>
#include <utility>
#include <iomanip>
#include <sstream>
#include <set>
#include <chrono>

#if defined(__unix__) && !defined(__EMSCRIPTEN__)
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#elif defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#endif

namespace foundation::editor {
namespace {
std::filesystem::path checked_path(const std::filesystem::path& path) {
    if (path.empty() || path.is_absolute() || path.has_root_name() || path.has_root_directory())
        throw FileError(FileFailure::invalid_path, "Use a nonempty project-relative file path");
    for (const auto& part : path) {
        const auto name = part.string();
        if (name.empty() || name == "." || name == ".." || name.find('\0') != std::string::npos || name.find('\\') != std::string::npos || name.find(':') != std::string::npos)
            throw FileError(FileFailure::invalid_path, "Project file paths cannot contain empty, dot, parent, backslash or colon components");
#if defined(_WIN32)
        if (name.back() == '.' || name.back() == ' ' || name.find_first_of("<>\"|?*") != std::string::npos)
            throw FileError(FileFailure::invalid_path, "Project file path contains a Windows alias or reserved character");
        auto base=name.substr(0,name.find('.'));
        for(auto& c:base) if(c>='a' && c<='z') c=static_cast<char>(c-'a'+'A');
        if(base=="CON" || base=="PRN" || base=="AUX" || base=="NUL" || (base.size()==4 && (base.starts_with("COM") || base.starts_with("LPT")) && base[3]>='1' && base[3]<='9'))
            throw FileError(FileFailure::invalid_path, "Project file path contains a Windows device name");
#endif
    }
    return path;
}
void check_text(std::string_view text, std::size_t limit) {
    if (text.size() > limit) throw FileError(FileFailure::limit, "File exceeds the configured editing byte limit");
    if (!ProjectFiles::valid_utf8(text)) throw FileError(FileFailure::encoding, "File is not valid UTF-8; no bytes were converted");
}
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
struct Descriptor {
    int value{-1};
    explicit Descriptor(int fd = -1) : value(fd) {}
    ~Descriptor() { if (value >= 0) ::close(value); }
    Descriptor(const Descriptor&) = delete;
    Descriptor& operator=(const Descriptor&) = delete;
    Descriptor(Descriptor&& other) noexcept : value(std::exchange(other.value, -1)) {}
    Descriptor& operator=(Descriptor&& other) noexcept { if (this != &other) { if (value >= 0) ::close(value); value = std::exchange(other.value, -1); } return *this; }
};
[[noreturn]] void os_error(std::string_view operation, int error = errno) {
    auto code = FileFailure::io;
    if (error == ENOENT) code = FileFailure::missing;
    else if (error == EACCES || error == EPERM || error == EROFS) code = FileFailure::permission;
    else if (error == ELOOP || error == ENOTDIR) code = FileFailure::invalid_path;
    throw FileError(code, std::string(operation) + ": " + std::strerror(error));
}
struct Parent {
    Descriptor fd;
    std::string leaf;
};
Parent open_parent(int root, const std::filesystem::path& relative) {
    auto path = checked_path(relative);
    Descriptor current(::fcntl(root, F_DUPFD_CLOEXEC, 0));
    if (current.value < 0) os_error("Cannot duplicate project directory");
    for (const auto& part : path.parent_path()) {
        Descriptor next(::openat(current.value, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        if (next.value < 0) os_error("Cannot open project parent directory");
        current = std::move(next);
    }
    return {std::move(current), path.filename().string()};
}
FileIdentity identity(const struct stat& st) {
    FileIdentity result;
    result.exists = true;
    result.device = static_cast<std::uint64_t>(st.st_dev);
    result.object = static_cast<std::uint64_t>(st.st_ino);
    result.size = static_cast<std::uint64_t>(st.st_size);
#if defined(__APPLE__)
    result.modified_seconds = st.st_mtimespec.tv_sec;
    result.modified_nanoseconds = st.st_mtimespec.tv_nsec;
#else
    result.modified_seconds = st.st_mtim.tv_sec;
    result.modified_nanoseconds = st.st_mtim.tv_nsec;
#endif
    result.permissions = static_cast<std::uint32_t>(st.st_mode & 07777);
    return result;
}
FileSnapshot read_from_parent(const Parent& parent, const std::filesystem::path& path, std::size_t limit, bool missing) {
    Descriptor file(::openat(parent.fd.value, parent.leaf.c_str(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
    if (file.value < 0) {
        if (missing && errno == ENOENT) return {path, {}, {}};
        os_error("Cannot open project file");
    }
    struct stat before{}, after{};
    if (::fstat(file.value, &before) != 0) os_error("Cannot inspect project file");
    if (!S_ISREG(before.st_mode)) throw FileError(FileFailure::invalid_path, "Only ordinary regular files may be edited");
    if (before.st_size < 0 || static_cast<std::uint64_t>(before.st_size) > limit)
        throw FileError(FileFailure::limit, "File exceeds the configured editing byte limit");
    std::string bytes;
    bytes.reserve(static_cast<std::size_t>(before.st_size));
    char chunk[16384];
    for (;;) {
        const auto count = ::read(file.value, chunk, sizeof chunk);
        if (count == 0) break;
        if (count < 0) { if (errno == EINTR) continue; os_error("Cannot read project file"); }
        if (static_cast<std::size_t>(count) > limit - bytes.size()) throw FileError(FileFailure::limit, "File grew beyond the configured editing byte limit");
        bytes.append(chunk, static_cast<std::size_t>(count));
    }
    if (::fstat(file.value, &after) != 0) os_error("Cannot recheck project file");
    if (identity(before) != identity(after) || bytes.size() != static_cast<std::size_t>(after.st_size))
        throw FileError(FileFailure::conflict, "Project file changed while being read; reload it");
    check_text(bytes, limit);
    return {path, std::move(bytes), identity(after)};
}
#elif defined(_WIN32)
struct Descriptor {
    HANDLE value{INVALID_HANDLE_VALUE};
    explicit Descriptor(HANDLE h = INVALID_HANDLE_VALUE) : value(h) {}
    ~Descriptor() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Descriptor(const Descriptor&) = delete;
    Descriptor& operator=(const Descriptor&) = delete;
    Descriptor(Descriptor&& other) noexcept : value(std::exchange(other.value, INVALID_HANDLE_VALUE)) {}
};
[[noreturn]] void os_error(std::string_view operation, DWORD error = GetLastError()) {
    auto code = FileFailure::io;
    if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) code = FileFailure::missing;
    else if (error == ERROR_ACCESS_DENIED || error == ERROR_WRITE_PROTECT || error == ERROR_SHARING_VIOLATION) code = FileFailure::permission;
    throw FileError(code, std::string(operation) + " (Windows error " + std::to_string(error) + ")");
}
void ordinary(HANDLE handle, bool directory) {
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(handle, &info)) os_error("Cannot inspect project path");
    if ((info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) || bool(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != directory || GetFileType(handle) != FILE_TYPE_DISK)
        throw FileError(FileFailure::invalid_path, "Project paths must contain ordinary directories and files without reparse points");
}
struct Parent { std::filesystem::path path; std::vector<Descriptor> pins; };
Parent open_parent(const std::filesystem::path& root, const std::filesystem::path& relative) {
    auto path = checked_path(relative);
    Parent result{root,{}};
    for (const auto& part : path.parent_path()) {
        result.path /= part;
        Descriptor dir(CreateFileW(result.path.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        if (dir.value == INVALID_HANDLE_VALUE) os_error("Cannot pin project parent directory");
        ordinary(dir.value, true); result.pins.push_back(std::move(dir));
    }
    return result;
}
FileIdentity identity(const BY_HANDLE_FILE_INFORMATION& info) {
    ULARGE_INTEGER size{}, modified{}; size.LowPart = info.nFileSizeLow; size.HighPart = info.nFileSizeHigh;
    modified.LowPart = info.ftLastWriteTime.dwLowDateTime; modified.HighPart = info.ftLastWriteTime.dwHighDateTime;
    return {true, info.dwVolumeSerialNumber, (static_cast<std::uint64_t>(info.nFileIndexHigh) << 32) | info.nFileIndexLow,
            size.QuadPart, static_cast<std::int64_t>(modified.QuadPart / 10000000), static_cast<std::int64_t>((modified.QuadPart % 10000000) * 100),
            info.dwFileAttributes & FILE_ATTRIBUTE_READONLY ? 0444u : 0644u};
}
FileSnapshot read_from_parent(const Parent& parent, const std::filesystem::path& path, std::size_t limit, bool missing) {
    const auto target = parent.path / path.filename();
    Descriptor file(CreateFileW(target.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) {
        if (missing && GetLastError() == ERROR_FILE_NOT_FOUND) return {path,{}, {}};
        os_error("Cannot open project file");
    }
    ordinary(file.value, false); BY_HANDLE_FILE_INFORMATION before{}, after{};
    if (!GetFileInformationByHandle(file.value, &before)) os_error("Cannot inspect project file");
    if (identity(before).size > limit) throw FileError(FileFailure::limit, "File exceeds configured editing byte limit");
    std::string text; text.reserve(static_cast<std::size_t>(identity(before).size)); char chunk[16384];
    for (;;) {
        DWORD bytes{}; if (!ReadFile(file.value, chunk, sizeof chunk, &bytes, nullptr)) os_error("Cannot read project file");
        if (!bytes) break;
        if (bytes > limit - text.size()) throw FileError(FileFailure::limit, "File grew beyond configured editing byte limit");
        text.append(chunk, bytes);
    }
    if (!GetFileInformationByHandle(file.value, &after)) os_error("Cannot recheck project file");
    if (identity(before) != identity(after) || text.size() != identity(after).size) throw FileError(FileFailure::conflict, "Project file changed while being read");
    check_text(text, limit); return {path,std::move(text),identity(after)};
}
#endif
} // namespace

bool ProjectFiles::valid_utf8(std::string_view text) noexcept {
    std::size_t i = 0;
    while (i < text.size()) {
        const auto first = static_cast<unsigned char>(text[i++]);
        if (first < 0x80) continue;
        unsigned count{}, value{}, minimum{};
        if (first >= 0xc2 && first <= 0xdf) { count = 1; value = first & 0x1f; minimum = 0x80; }
        else if (first >= 0xe0 && first <= 0xef) { count = 2; value = first & 0x0f; minimum = 0x800; }
        else if (first >= 0xf0 && first <= 0xf4) { count = 3; value = first & 0x07; minimum = 0x10000; }
        else return false;
        if (count > text.size() - i) return false;
        for (unsigned j = 0; j < count; ++j) {
            const auto next = static_cast<unsigned char>(text[i++]);
            if ((next & 0xc0) != 0x80) return false;
            value = (value << 6) | (next & 0x3f);
        }
        if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) return false;
    }
    return true;
}
ProjectFiles::ProjectFiles(std::filesystem::path root, std::size_t max_bytes) : max_bytes_(max_bytes) {
    if (!max_bytes || max_bytes > static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max()))
        throw FileError(FileFailure::limit, "Editing byte limit must be positive and representable");
    std::error_code ec;
    root_ = std::filesystem::canonical(root, ec);
    if (ec) throw FileError(FileFailure::invalid_path, "Cannot resolve project directory: " + ec.message());
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    native_root_ = ::open(root_.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (native_root_ < 0) os_error("Cannot open project directory");
#elif defined(_WIN32)
    const auto root_handle = CreateFileW(root_.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (root_handle == INVALID_HANDLE_VALUE) os_error("Cannot pin project directory");
    try { ordinary(root_handle, true); } catch (...) { CloseHandle(root_handle); throw; }
    native_root_ = reinterpret_cast<std::intptr_t>(root_handle);
#else
    throw FileError(FileFailure::unavailable, "Safe rooted project file operations are not implemented on this platform");
#endif
}
ProjectFiles::~ProjectFiles() {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    if (native_root_ >= 0) ::close(static_cast<int>(native_root_));
#elif defined(_WIN32)
    if (native_root_ != -1) CloseHandle(reinterpret_cast<HANDLE>(native_root_));
#endif
}
ProjectFiles::ProjectFiles(ProjectFiles&& other) noexcept : root_(std::move(other.root_)), max_bytes_(other.max_bytes_), native_root_(std::exchange(other.native_root_, -1)) {}
ProjectFiles& ProjectFiles::operator=(ProjectFiles&& other) noexcept {
    if (this != &other) {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
        if (native_root_ >= 0) ::close(static_cast<int>(native_root_));
#elif defined(_WIN32)
    if (native_root_ != -1) CloseHandle(reinterpret_cast<HANDLE>(native_root_));
#endif
        root_ = std::move(other.root_); max_bytes_ = other.max_bytes_; native_root_ = std::exchange(other.native_root_, -1);
    }
    return *this;
}
FileSnapshot ProjectFiles::read(const std::filesystem::path& relative) const {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    return read_from_parent(open_parent(static_cast<int>(native_root_), relative), relative, max_bytes_, false);
#elif defined(_WIN32)
    return read_from_parent(open_parent(root_, relative), relative, max_bytes_, false);
#else
    (void)relative; throw FileError(FileFailure::unavailable, "Project files are unavailable on this platform");
#endif
}
FileSnapshot ProjectFiles::inspect(const std::filesystem::path& relative) const {
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    return read_from_parent(open_parent(static_cast<int>(native_root_), relative), relative, max_bytes_, true);
#elif defined(_WIN32)
    return read_from_parent(open_parent(root_, relative), relative, max_bytes_, true);
#else
    (void)relative; throw FileError(FileFailure::unavailable, "Project files are unavailable on this platform");
#endif
}
std::filesystem::path ProjectFiles::absolute(const std::filesystem::path& relative) const {
    // Validate every existing parent and leaf before giving an external editor a path.
    (void)inspect(relative);
    return root_ / checked_path(relative);
}
FileSnapshot ProjectFiles::save(const FileSnapshot& original, std::string_view text) const { return save(original.path, original, text); }
FileSnapshot ProjectFiles::save(const std::filesystem::path& relative, const FileSnapshot& original, std::string_view text) const {
    const auto path = checked_path(relative);
    if (path != original.path) throw FileError(FileFailure::invalid_path, "Save snapshot belongs to a different project file");
    check_text(text, max_bytes_);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    auto parent = open_parent(static_cast<int>(native_root_), path);
    auto matches = [&] {
        const auto now = read_from_parent(parent, path, max_bytes_, true);
        if (now.identity != original.identity || now.text != original.text)
            throw FileError(FileFailure::conflict, "Project file changed externally; reload or save to another file");
    };
    matches();
    struct stat directory{};
    if (::fstat(parent.fd.value, &directory) != 0) os_error("Cannot inspect save directory");
    if (!(directory.st_mode & 0222) || (original.identity.exists && !(original.identity.permissions & 0222)))
        throw FileError(FileFailure::permission, "Project file or its directory is read-only");
    Descriptor temporary;
    std::string staged;
    for (unsigned attempt = 0; attempt < 1000; ++attempt) {
        staged = ".foundation-editor-save-" + std::to_string(::getpid()) + "-" + std::to_string(attempt);
        temporary.value = ::openat(parent.fd.value, staged.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (temporary.value >= 0) break;
        if (errno != EEXIST) os_error("Cannot stage save in destination directory");
    }
    if (temporary.value < 0) throw FileError(FileFailure::io, "No free save staging name in destination directory");
    bool published = false;
    try {
        std::size_t offset = 0;
        while (offset < text.size()) {
            const auto written = ::write(temporary.value, text.data() + offset, text.size() - offset);
            if (written < 0) { if (errno == EINTR) continue; os_error("Cannot write staged project file"); }
            if (written == 0) throw FileError(FileFailure::io, "Short write while saving project file");
            offset += static_cast<std::size_t>(written);
        }
        if (::fchmod(temporary.value, original.identity.exists ? original.identity.permissions & 0777 : 0644) != 0) os_error("Cannot retain project file permissions");
        if (::fsync(temporary.value) != 0) os_error("Cannot flush staged project file");
        const auto closed = ::close(std::exchange(temporary.value, -1));
        if (closed != 0) os_error("Cannot close staged project file");
        // Ordinary shared editors are cooperative: a final identity-and-byte
        // comparison precedes publication. No claim of cross-process CAS is made.
        matches();
        if (original.identity.exists) {
            if (::renameat(parent.fd.value, staged.c_str(), parent.fd.value, parent.leaf.c_str()) != 0) os_error("Cannot publish project file");
        } else {
            // linkat publishes a previously nonexistent leaf without clobbering a
            // file created by another editor after the final comparison.
            if (::linkat(parent.fd.value, staged.c_str(), parent.fd.value, parent.leaf.c_str(), 0) != 0) {
                if (errno == EEXIST) throw FileError(FileFailure::conflict, "Project file was created by another editor during save");
                os_error("Cannot publish new project file");
            }
            if (::unlinkat(parent.fd.value, staged.c_str(), 0) != 0) os_error("New file saved but staging cleanup failed");
        }
        published = true;
        if (::fsync(parent.fd.value) != 0) os_error("File was saved but directory durability could not be confirmed");
        return read_from_parent(parent, path, max_bytes_, false);
    } catch (...) {
        if (!published) ::unlinkat(parent.fd.value, staged.c_str(), 0);
        throw;
    }
#elif defined(_WIN32)
    auto parent = open_parent(root_, path);
    auto matches = [&] {
        const auto now = read_from_parent(parent,path,max_bytes_,true);
        if (now.identity != original.identity || now.text != original.text) throw FileError(FileFailure::conflict,"Project file changed externally; reload or save to another file");
    };
    matches();
    if (original.identity.exists && !(original.identity.permissions & 0222)) throw FileError(FileFailure::permission,"Project file is read-only");
    Descriptor temporary; std::filesystem::path staged;
    for (unsigned attempt=0; attempt<1000; ++attempt) {
        staged = parent.path / (L".foundation-editor-save-" + std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(attempt));
        temporary.value = CreateFileW(staged.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
        if (temporary.value != INVALID_HANDLE_VALUE) break;
        if (GetLastError()!=ERROR_FILE_EXISTS) os_error("Cannot stage project save");
    }
    if (temporary.value == INVALID_HANDLE_VALUE) throw FileError(FileFailure::io,"No free save staging name");
    bool published=false;
    try {
        std::size_t offset=0;
        while(offset<text.size()) {
            DWORD written{}; const auto count=static_cast<DWORD>(std::min<std::size_t>(text.size()-offset,1024*1024));
            if(!WriteFile(temporary.value,text.data()+offset,count,&written,nullptr) || !written) os_error("Cannot write staged file");
            offset+=written;
        }
        if(!FlushFileBuffers(temporary.value)) os_error("Cannot flush staged file");
        if(!CloseHandle(std::exchange(temporary.value,INVALID_HANDLE_VALUE))) os_error("Cannot close staged file");
        matches(); const auto target=parent.path/path.filename();
        if(!MoveFileExW(staged.c_str(),target.c_str(),MOVEFILE_WRITE_THROUGH | (original.identity.exists ? MOVEFILE_REPLACE_EXISTING : 0))) {
            if(GetLastError()==ERROR_ALREADY_EXISTS || GetLastError()==ERROR_FILE_EXISTS) throw FileError(FileFailure::conflict,"Project file was created during save");
            os_error("Cannot publish project save");
        }
        published=true; return read_from_parent(parent,path,max_bytes_,false);
    } catch (...) { if(!published) { if(temporary.value!=INVALID_HANDLE_VALUE) CloseHandle(std::exchange(temporary.value,INVALID_HANDLE_VALUE)); DeleteFileW(staged.c_str()); } throw; }
#else
    (void)original; (void)text; throw FileError(FileFailure::unavailable, "Project saves are unavailable on this platform");
#endif
}

void ProjectFiles::ensure_directory(const std::filesystem::path& relative) const {
    const auto path = checked_path(relative);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    Descriptor current(::fcntl(static_cast<int>(native_root_), F_DUPFD_CLOEXEC, 0));
    if (current.value < 0) os_error("Cannot pin project directory");
    for (const auto& part : path) {
        if (::mkdirat(current.value, part.c_str(), 0755) != 0 && errno != EEXIST) os_error("Cannot create project directory");
        Descriptor next(::openat(current.value, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        if (next.value < 0) os_error("Cannot pin created project directory");
        if (::fsync(current.value) != 0) os_error("Cannot confirm created directory durability");
        current = std::move(next);
    }
#elif defined(_WIN32)
    std::filesystem::path current = root_; std::vector<Descriptor> pins;
    for (const auto& part : path) {
        current /= part;
        if (!CreateDirectoryW(current.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) os_error("Cannot create project directory");
        Descriptor dir(CreateFileW(current.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        if (dir.value == INVALID_HANDLE_VALUE) os_error("Cannot pin created project directory");
        ordinary(dir.value, true); pins.push_back(std::move(dir));
    }
#else
    (void)path; throw FileError(FileFailure::unavailable, "Project directory creation is unavailable on this platform");
#endif
}
std::filesystem::path ProjectFiles::directory(const std::filesystem::path& relative) const {
    if (relative == ".") return root_;
    const auto path = checked_path(relative);
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
    Descriptor current(::fcntl(static_cast<int>(native_root_), F_DUPFD_CLOEXEC, 0));
    if (current.value < 0) os_error("Cannot pin project working directory");
    for (const auto& part : path) {
        Descriptor next(::openat(current.value, part.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
        if (next.value < 0) os_error("Cannot open project working directory");
        current = std::move(next);
    }
#elif defined(_WIN32)
    // The unused leaf lets the ordinary parent walker pin every requested
    // directory component, including the final working-directory component.
    auto parent = open_parent(root_, path / ".foundation-editor-directory-probe");
    (void)parent;
#else
    throw FileError(FileFailure::unavailable, "Project directory resolution is unavailable on this platform");
#endif
    return root_ / path;
}

namespace {
constexpr const char* journal_path = ".foundation-editor-journal";
struct JournalEntry {
    FileSnapshot original;
    std::filesystem::path old_path, new_path;
    std::string old_hash, new_hash;
};
std::string journal_bytes(const std::vector<JournalEntry>& entries) {
    std::ostringstream output; output << "foundation-editor-batch 1 " << entries.size() << '\n';
    for (const auto& entry : entries) {
        const auto& id = entry.original.identity;
        output << std::quoted(entry.original.path.generic_string()) << ' '
               << std::quoted(entry.old_path.generic_string()) << ' ' << std::quoted(entry.new_path.generic_string()) << ' '
               << id.exists << ' ' << id.device << ' ' << id.object << ' ' << id.size << ' '
               << id.modified_seconds << ' ' << id.modified_nanoseconds << ' ' << id.permissions << ' ' << entry.old_hash << ' ' << entry.new_hash << '\n';
    }
    return output.str();
}
std::vector<JournalEntry> parse_journal(std::string_view bytes) {
    std::istringstream input{std::string(bytes)}; std::string magic; unsigned version{}; std::size_t count{};
    if (!(input >> magic >> version >> count) || magic != "foundation-editor-batch" || version != 1 || !count || count > 4096)
        throw FileError(FileFailure::io, "Invalid editor save journal; preserve files and inspect it");
    std::vector<JournalEntry> entries; entries.reserve(count); std::set<std::filesystem::path> paths;
    for (std::size_t i=0; i<count; ++i) {
        JournalEntry entry; std::string path, old_path, new_path; auto& id=entry.original.identity;
        if (!(input >> std::quoted(path) >> std::quoted(old_path) >> std::quoted(new_path)
              >> id.exists >> id.device >> id.object >> id.size >> id.modified_seconds >> id.modified_nanoseconds >> id.permissions >> entry.old_hash >> entry.new_hash))
            throw FileError(FileFailure::io, "Incomplete editor save journal; preserve files and inspect it");
        entry.original.path=checked_path(path); entry.old_path=checked_path(old_path); entry.new_path=checked_path(new_path);
        auto valid_hash=[](const std::string& hash) { return hash.size()==64 && hash.find_first_not_of("0123456789abcdef")==std::string::npos; };
        if(!valid_hash(entry.old_hash) || !valid_hash(entry.new_hash)) throw FileError(FileFailure::io,"Invalid digest in editor save journal");
        if (path.starts_with(".foundation-editor-") || !old_path.starts_with(".foundation-editor-batch-") || !new_path.starts_with(".foundation-editor-batch-")
            || entry.old_path.has_parent_path() || entry.new_path.has_parent_path() || !paths.insert(entry.original.path).second
            || !paths.insert(entry.old_path).second || !paths.insert(entry.new_path).second)
            throw FileError(FileFailure::invalid_path, "Unsafe paths in editor save journal");
        entries.push_back(std::move(entry));
    }
    input >> std::ws; if (!input.eof()) throw FileError(FileFailure::io, "Unexpected data in editor save journal");
    return entries;
}
}
bool ProjectFiles::recovery_pending() const { return inspect(journal_path).identity.exists; }
std::vector<FileSnapshot> ProjectFiles::save_batch(const std::vector<Write>& writes, const Write& marker) const {
    if (recovery_pending()) throw FileError(FileFailure::conflict, "An interrupted generated-file save needs explicit recovery before generation or build");
    if (writes.size() >= 4096) throw FileError(FileFailure::limit, "Generated save exceeds 4096 files");
    std::vector<Write> all = writes; all.push_back(marker); std::set<std::filesystem::path> targets;
    std::size_t total=0;
    for (const auto& entry : all) {
        checked_path(entry.original.path); check_text(entry.text,max_bytes_);
        if (entry.original.path.generic_string().starts_with(".foundation-editor-") || !targets.insert(entry.original.path).second)
            throw FileError(FileFailure::invalid_path, "Generated batch targets must be unique ordinary project paths");
        if (entry.text.size() > 64*1024*1024-total || entry.original.text.size() > 64*1024*1024-total-entry.text.size())
            throw FileError(FileFailure::limit, "Generated save exceeds the 64 MiB journal byte budget");
        total += entry.text.size()+entry.original.text.size();
        const auto current=inspect(entry.original.path);
        if (current.identity != entry.original.identity || current.text != entry.original.text) throw FileError(FileFailure::conflict,"Generated batch input changed externally");
    }
    std::vector<JournalEntry> entries; std::vector<FileSnapshot> stages;
    const auto serial = std::chrono::steady_clock::now().time_since_epoch().count();
    for (std::size_t i=0; i<all.size(); ++i) {
        const auto prefix=".foundation-editor-batch-"+std::to_string(serial)+"-"+std::to_string(i);
        JournalEntry entry{all[i].original,prefix+".old",prefix+".new",detail::content_digest(all[i].original.text),detail::content_digest(all[i].text)};
        auto old_file=inspect(entry.old_path), new_file=inspect(entry.new_path);
        if (old_file.identity.exists || new_file.identity.exists) throw FileError(FileFailure::conflict,"Generated staging filename is occupied");
        stages.push_back(save(old_file,all[i].original.text)); stages.push_back(save(new_file,all[i].text)); entries.push_back(std::move(entry));
    }
    (void)save(inspect(journal_path),journal_bytes(entries));
    // After publication of the journal every failure leaves a recoverable record.
    recover_batch();
    std::vector<FileSnapshot> result; for (const auto& entry : all) result.push_back(read(entry.original.path)); return result;
}
void ProjectFiles::recover_batch() const {
    const auto journal=inspect(journal_path); if (!journal.identity.exists) return;
    auto entries=parse_journal(journal.text);
    // Validate every backup and target before publishing any additional bytes.
    std::vector<FileSnapshot> targets, backups; std::vector<std::string> next;
    for (auto& entry : entries) {
        auto old_file=read(entry.old_path), new_file=read(entry.new_path); entry.original.text=old_file.text;
        if(detail::content_digest(old_file.text)!=entry.old_hash || detail::content_digest(new_file.text)!=entry.new_hash)
            throw FileError(FileFailure::io,"Save journal backup digest mismatch; preserve files and inspect them");
        if (entry.original.identity.exists && entry.original.identity.size != old_file.text.size()) throw FileError(FileFailure::io,"Save journal old-file size mismatch");
        auto target=inspect(entry.original.path);
        if (target.text != new_file.text || !target.identity.exists) {
            if (target.identity != entry.original.identity || target.text != old_file.text) throw FileError(FileFailure::conflict,"A file changed outside an interrupted editor save; preserve it and resolve before recovery");
        }
        targets.push_back(std::move(target)); next.push_back(new_file.text); backups.push_back(std::move(old_file)); backups.push_back(std::move(new_file));
    }
    for (std::size_t i=0; i<targets.size(); ++i) if (!targets[i].identity.exists || targets[i].text != next[i]) (void)save(targets[i],next[i]);
    auto remove_checked = [&](const FileSnapshot& original) {
        const auto current=read(original.path);
        if (current.identity != original.identity || current.text != original.text) throw FileError(FileFailure::conflict,"Editor save journal or staging changed during cleanup");
#if defined(__unix__) && !defined(__EMSCRIPTEN__)
        auto parent=open_parent(static_cast<int>(native_root_),original.path);
        if (::unlinkat(parent.fd.value,parent.leaf.c_str(),0) != 0) os_error("Cannot remove completed save journal or staging");
        if (::fsync(parent.fd.value) != 0) os_error("Cannot confirm journal cleanup durability");
#elif defined(_WIN32)
        auto parent=open_parent(root_,original.path);
        if (!DeleteFileW((parent.path/original.path.filename()).c_str())) os_error("Cannot remove completed save journal or staging");
#else
        throw FileError(FileFailure::unavailable,"Journal cleanup is unavailable on this platform");
#endif
    };
    // Remove the journal before backups: a crash never leaves a pending journal
    // referring to a backup already removed. Orphan backups may be removed manually.
    remove_checked(journal);
    for (const auto& backup : backups) remove_checked(backup);
}

CodeBuffer::CodeBuffer(FileSnapshot original, std::size_t history_bytes) : original_(std::move(original)), text_(original_.text), history_limit_(history_bytes) {
    if (!ProjectFiles::valid_utf8(text_)) throw FileError(FileFailure::encoding, "Code buffer is not valid UTF-8");
}
void CodeBuffer::clear(std::vector<std::string>& destination) noexcept {
    for (const auto& item : destination) history_used_ -= item.size();
    destination.clear();
}
void CodeBuffer::retain(std::vector<std::string>& destination, std::string text) {
    if (text.size() > history_limit_) throw FileError(FileFailure::limit, "Edit exceeds the code history byte limit");
    while (history_used_ > history_limit_ - text.size()) {
        auto& victim = !undo_.empty() ? undo_ : redo_;
        if (victim.empty()) break;
        history_used_ -= victim.front().size(); victim.erase(victim.begin());
    }
    history_used_ += text.size(); destination.push_back(std::move(text));
}
void CodeBuffer::set_text(std::string text) {
    if (!ProjectFiles::valid_utf8(text)) throw FileError(FileFailure::encoding, "Edited source is not valid UTF-8");
    if (text == text_) return;
    if (text.size() > history_limit_ || text_.size() > history_limit_) throw FileError(FileFailure::limit, "Edit exceeds the code history byte limit");
    clear(redo_); retain(undo_, text_); text_ = std::move(text);
}
void CodeBuffer::replace(std::size_t offset, std::size_t count, std::string_view text) {
    if (offset > text_.size() || count > text_.size() - offset) throw std::out_of_range("Source replacement is outside the buffer");
    auto next = text_; next.replace(offset, count, text); set_text(std::move(next));
}
bool CodeBuffer::undo() {
    if (undo_.empty()) return false;
    auto previous = std::move(undo_.back()); history_used_ -= previous.size(); undo_.pop_back();
    retain(redo_, std::move(text_)); text_ = std::move(previous); return true;
}
bool CodeBuffer::redo() {
    if (redo_.empty()) return false;
    auto next = std::move(redo_.back()); history_used_ -= next.size(); redo_.pop_back();
    retain(undo_, std::move(text_)); text_ = std::move(next); return true;
}
std::size_t CodeBuffer::find(std::string_view needle, std::size_t from) const noexcept { return text_.find(needle, from); }
void CodeBuffer::reload(FileSnapshot snapshot) {
    if (snapshot.path != original_.path) throw FileError(FileFailure::invalid_path, "Reload snapshot belongs to another file");
    if (!ProjectFiles::valid_utf8(snapshot.text)) throw FileError(FileFailure::encoding, "Reload source is not valid UTF-8");
    original_ = std::move(snapshot); text_ = original_.text; clear(undo_); clear(redo_);
}
void CodeBuffer::save(const ProjectFiles& files) { original_ = files.save(original_, text_); }
} // namespace foundation::editor
