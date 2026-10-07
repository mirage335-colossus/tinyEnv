// Native Windows host qualification only. Keep the executable beside the exact
// staged OpenGL DLLs. The caller must bound its process tree lifetime: a driver
// call can block inside foreign code. This probe never changes driver overrides.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <GL/gl.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
constexpr std::size_t max_gl_string = 1024;
constexpr std::size_t max_report = 512 * 1024;
constexpr GLenum gl_major_version = 0x821b;
constexpr GLenum gl_minor_version = 0x821c;
constexpr GLenum gl_num_extensions = 0x821d;
using CreateContext = HGLRC (WINAPI *)(HDC, HGLRC, const int*);
using ChooseFormat = BOOL (WINAPI *)(HDC, const int*, const FLOAT*, UINT, int*, UINT*);
using GetStringIndex = const GLubyte* (APIENTRY *)(GLenum, GLuint);

struct Report {
    bool passed = false;
    std::string error, opengl32_path, libgallium_wgl_path, version, vendor, renderer;
    GLint major = 0, minor = 0;
    bool create_context = false, choose_format = false;
    bool arb_buffer_storage = false, gl_buffer_storage = false;
};

std::string escaped(std::string_view value) {
    // Inputs are validated UTF-8. Escape every JSON control character explicitly.
    constexpr char hex[] = "0123456789abcdef";
    std::string result = "\"";
    for (const unsigned char c : value) {
        if (c == '"' || c == '\\') {
            result += '\\'; result += static_cast<char>(c);
        } else if (c < 0x20) {
            result += "\\u00"; result += hex[c >> 4]; result += hex[c & 15];
        } else {
            result += static_cast<char>(c);
        }
    }
    result += '"';
    return result;
}

std::string json(const Report& r) {
    std::ostringstream out;
    out << std::boolalpha << "{\"schema_version\":1,\"status\":"
        << escaped(r.passed ? "passed" : "failed")
        << ",\"error\":" << escaped(r.error)
        << ",\"opengl32_path\":" << escaped(r.opengl32_path)
        << ",\"libgallium_wgl_path\":" << escaped(r.libgallium_wgl_path)
        << ",\"version\":" << escaped(r.version)
        << ",\"vendor\":" << escaped(r.vendor)
        << ",\"renderer\":" << escaped(r.renderer)
        << ",\"major\":" << r.major << ",\"minor\":" << r.minor
        << ",\"wgl_create_context_attribs_arb\":" << r.create_context
        << ",\"wgl_choose_pixel_format_arb\":" << r.choose_format
        << ",\"arb_buffer_storage\":" << r.arb_buffer_storage
        << ",\"gl_buffer_storage\":" << r.gl_buffer_storage << "}\n";
    return out.str();
}

[[noreturn]] void failed(const char* operation) {
    throw std::runtime_error(std::string(operation) + " failed (Win32 " +
                             std::to_string(GetLastError()) + ")");
}

std::string module_path(const wchar_t* name) {
    const HMODULE module = GetModuleHandleW(name);
    if (!module) failed("loaded module lookup");
    std::array<wchar_t, 32768> path{};
    const DWORD length = GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) failed("bounded loaded module path");
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path.data(),
        static_cast<int>(length), nullptr, 0, nullptr, nullptr);
    if (size <= 0) failed("module path UTF-8 conversion");
    std::string result(static_cast<std::size_t>(size), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path.data(), static_cast<int>(length),
                           result.data(), size, nullptr, nullptr) != size) failed("module path UTF-8 conversion");
    return result;
}

std::string gl_text(const GLubyte* value) {
    if (!value) throw std::runtime_error("missing OpenGL string");
    std::size_t length = 0;
    while (length < max_gl_string && value[length]) ++length;
    if (length == max_gl_string) throw std::runtime_error("OpenGL string exceeds byte limit");
    const auto* bytes = reinterpret_cast<const char*>(value);
    if (length && !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes,
                                     static_cast<int>(length), nullptr, 0))
        throw std::runtime_error("OpenGL string is not valid UTF-8");
    return std::string(bytes, length);
}

bool present(PROC function) {
    const auto value = reinterpret_cast<std::intptr_t>(function);
    return value != 0 && value != 1 && value != 2 && value != 3 && value != -1;
}

class WindowClass {
public:
    HINSTANCE instance = GetModuleHandleW(nullptr);
    std::wstring name = L"FoundationGraphicsProbe-" + std::to_wstring(GetCurrentProcessId());
    WindowClass() {
        WNDCLASSEXW type{};
        type.cbSize = static_cast<UINT>(sizeof(type));
        type.style = CS_OWNDC;
        type.lpfnWndProc = DefWindowProcW;
        type.hInstance = instance;
        type.lpszClassName = name.c_str();
        if (!RegisterClassExW(&type)) failed("private window class registration");
    }
    ~WindowClass() { UnregisterClassW(name.c_str(), instance); }
    WindowClass(const WindowClass&) = delete;
    WindowClass& operator=(const WindowClass&) = delete;
};

class Context {
public:
    HWND window = nullptr;
    HDC dc = nullptr;
    HGLRC context = nullptr;
    Context() = default;
    ~Context() { close(); }
    Context(const Context&) = delete;
    Context& operator=(const Context&) = delete;
    void create(const WindowClass& type) {
        // No ShowWindow or visible style: host qualification has no user UI.
        window = CreateWindowExW(0, type.name.c_str(), L"", WS_OVERLAPPEDWINDOW,
                                 0, 0, 8, 8, nullptr, nullptr, type.instance, nullptr);
        if (!window) failed("private hidden window creation");
        dc = GetDC(window);
        if (!dc) failed("private window DC acquisition");
    }
    bool close() noexcept {
        bool clean = true;
        if (context) {
            if (wglGetCurrentContext() == context && !wglMakeCurrent(nullptr, nullptr)) clean = false;
            if (!wglDeleteContext(context)) clean = false;
            context = nullptr;
        }
        if (dc && window) ReleaseDC(window, dc);
        dc = nullptr;
        // Destroying a CS_OWNDC window also releases its private DC.
        if (window && !DestroyWindow(window)) clean = false;
        window = nullptr;
        return clean;
    }
};

void set_format(HDC dc, int format, const PIXELFORMATDESCRIPTOR& descriptor) {
    if (!format || !SetPixelFormat(dc, format, &descriptor)) failed("pixel format selection");
}

bool extension(GetStringIndex get, const char* required) {
    GLint count = 0;
    glGetIntegerv(gl_num_extensions, &count);
    if (glGetError() != GL_NO_ERROR || count < 0 || count > 4096)
        throw std::runtime_error("invalid or excessive OpenGL extension count");
    for (GLint index = 0; index < count; ++index) {
        if (gl_text(get(GL_EXTENSIONS, static_cast<GLuint>(index))) == required) return true;
    }
    return false;
}

void probe(Report& report) {
    for (const wchar_t* name : {L"MESA_GL_VERSION_OVERRIDE", L"MESA_GLSL_VERSION_OVERRIDE", L"MESA_EXTENSION_OVERRIDE"}) {
        if (GetEnvironmentVariableW(name, nullptr, 0))
            throw std::runtime_error("version or extension overrides are forbidden");
    }
    report.opengl32_path = module_path(L"opengl32.dll");
    WindowClass type;
    Context bootstrap;
    bootstrap.create(type);
    PIXELFORMATDESCRIPTOR descriptor{};
    descriptor.nSize = static_cast<WORD>(sizeof(descriptor));
    descriptor.nVersion = 1;
    descriptor.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    descriptor.iPixelType = PFD_TYPE_RGBA;
    descriptor.cColorBits = 32; descriptor.cAlphaBits = 8;
    descriptor.cDepthBits = 24; descriptor.cStencilBits = 8;
    set_format(bootstrap.dc, ChoosePixelFormat(bootstrap.dc, &descriptor), descriptor);
    bootstrap.context = wglCreateContext(bootstrap.dc);
    if (!bootstrap.context || !wglMakeCurrent(bootstrap.dc, bootstrap.context)) failed("bootstrap WGL context");
    const PROC create_proc = wglGetProcAddress("wglCreateContextAttribsARB");
    const PROC choose_proc = wglGetProcAddress("wglChoosePixelFormatARB");
    report.create_context = present(create_proc); report.choose_format = present(choose_proc);
    if (!report.create_context || !report.choose_format)
        throw std::runtime_error("required WGL context or pixel format entrypoint is absent");
    const auto create = reinterpret_cast<CreateContext>(create_proc);
    const auto choose = reinterpret_cast<ChooseFormat>(choose_proc);
    Context modern;
    modern.create(type);
    // WGL_DRAW_TO_WINDOW_ARB, SUPPORT_OPENGL, DOUBLE_BUFFER, PIXEL_TYPE/RGBA,
    // COLOR_BITS, ALPHA_BITS, DEPTH_BITS and STENCIL_BITS.
    const int attributes[] = {0x2001, 1, 0x2010, 1, 0x2011, 1, 0x2013, 0x202b,
                              0x2014, 32, 0x201b, 8, 0x2022, 24, 0x2023, 8, 0};
    int format = 0; UINT count = 0;
    if (!choose(modern.dc, attributes, nullptr, 1, &format, &count) || count != 1 || !format)
        failed("WGL attributed pixel format query");
    if (!DescribePixelFormat(modern.dc, format, static_cast<UINT>(sizeof(descriptor)), &descriptor))
        failed("attributed pixel format description");
    set_format(modern.dc, format, descriptor);
    for (const int minor : {4, 3}) {
        const int requested[] = {0x2091, 4, 0x2092, minor, 0x9126, 1, 0};
        modern.context = create(modern.dc, nullptr, requested);
        if (modern.context) break;
    }
    if (!modern.context || !wglMakeCurrent(modern.dc, modern.context)) failed("OpenGL 4.4 or 4.3 core context");
    // Query entrypoints for this actual context/pixel format, not only bootstrap.
    report.create_context = present(wglGetProcAddress("wglCreateContextAttribsARB"));
    report.choose_format = present(wglGetProcAddress("wglChoosePixelFormatARB"));
    report.version = gl_text(glGetString(GL_VERSION));
    report.vendor = gl_text(glGetString(GL_VENDOR));
    report.renderer = gl_text(glGetString(GL_RENDERER));
    report.libgallium_wgl_path = module_path(L"libgallium_wgl.dll");
    glGetIntegerv(gl_major_version, &report.major);
    glGetIntegerv(gl_minor_version, &report.minor);
    if (glGetError() != GL_NO_ERROR || report.major < 0 || report.major > 99 || report.minor < 0 || report.minor > 99)
        throw std::runtime_error("invalid OpenGL version query");
    const PROC get_proc = wglGetProcAddress("glGetStringi");
    if (!present(get_proc)) throw std::runtime_error("indexed OpenGL extension query unavailable");
    report.arb_buffer_storage = extension(reinterpret_cast<GetStringIndex>(get_proc), "GL_ARB_buffer_storage");
    report.gl_buffer_storage = present(wglGetProcAddress("glBufferStorage"));
    std::string renderer = report.renderer;
    std::transform(renderer.begin(), renderer.end(), renderer.begin(), [](unsigned char c) {
        return static_cast<char>(c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c);
    });
    if (renderer.find("llvmpipe") == std::string::npos)
        throw std::runtime_error("host input profile requires llvmpipe");
    const bool core = report.major > 4 || (report.major == 4 && report.minor >= 4);
    const bool extended = report.major == 4 && report.minor >= 3 && report.arb_buffer_storage;
    if (!report.create_context || !report.choose_format || !report.gl_buffer_storage || !(core || extended))
        throw std::runtime_error("required OpenGL buffer storage capabilities are absent");
    const bool modern_clean = modern.close();
    const bool bootstrap_clean = bootstrap.close();
    if (!modern_clean || !bootstrap_clean) throw std::runtime_error("WGL context cleanup failed");
    report.passed = true;
}
} // namespace

int main(int argc, char**) {
    Report report;
    try {
        if (argc != 1) throw std::runtime_error("this probe accepts no arguments");
        probe(report);
    } catch (const std::exception& error) {
        // Error diagnostics remain bounded ASCII even for foreign exceptions.
        for (std::size_t i = 0; i < 256 && error.what()[i]; ++i) {
            const unsigned char c = static_cast<unsigned char>(error.what()[i]);
            report.error += static_cast<char>(c >= 0x20 && c <= 0x7e ? c : '?');
        }
        report.passed = false;
    } catch (...) {
        report.error = "unexpected probe failure";
        report.passed = false;
    }
    const std::string result = json(report);
    if (result.size() > max_report) {
        std::fputs("{\"schema_version\":1,\"status\":\"failed\",\"error\":\"report exceeds byte limit\"}\n", stdout);
        return 1;
    }
    const bool written = std::fwrite(result.data(), 1, result.size(), stdout) == result.size();
    return written && std::fflush(stdout) == 0 && report.passed ? 0 : 1;
}
