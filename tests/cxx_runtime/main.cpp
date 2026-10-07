#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <exception>
#include <stdexcept>
#include <string>
#include <typeinfo>
#ifdef FOUNDATION_CONSUMER
#include <foundation/store.hpp>
#endif

extern "C" const void* application_exception_type() { return &typeid(std::exception); }

int main(int argc, char** argv) {
    if (argc != 2 && argc != 3) return 1;
    try {
        throw std::runtime_error(std::string(256, 'x'));
    } catch (const std::exception& error) {
        if (std::strlen(error.what()) != 256) return 2;
    }
#ifdef FOUNDATION_CONSUMER
    foundation::Store records;
    const auto id = records.add("installed consumer");
    if (records.get(id)->text != "installed consumer") return 6;
#endif
    void* plugin = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!plugin) { std::fprintf(stderr, "dlopen: %s\n", dlerror()); return 3; }
    auto probe = reinterpret_cast<const void* (*)()>(dlsym(plugin, "plugin_exception_type"));
    Dl_info provider{};
    // A dynamic executable can use a copy relocation for RTTI. Inspect a runtime
    // function for the shared-library baseline and RTTI for static isolation.
    const void* symbol = argc == 3 ? dlsym(RTLD_DEFAULT, "__cxa_throw") : (probe ? probe() : nullptr);
    if (!symbol || !dladdr(symbol, &provider) || !provider.dli_fname) return 4;
    std::printf("plugin C++ runtime: %s\n", provider.dli_fname);
    // No C++ objects/exceptions cross the plugin boundary. Its RTTI must come
    // from its own dynamic runtime rather than the executable's private copy.
    const bool separate = std::strstr(provider.dli_fname, "libstdc++.so") != nullptr;
    dlclose(plugin);
    return separate ? 0 : 5;
}
