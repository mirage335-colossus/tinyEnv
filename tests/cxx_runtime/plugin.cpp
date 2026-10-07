#include <exception>
#include <stdexcept>
#include <string>
#include <typeinfo>

extern "C" const void* plugin_exception_type() {
    try {
        throw std::runtime_error(std::string(256, 'y'));
    } catch (const std::exception& error) {
        if (std::string(error.what()) != std::string(256, 'y')) return nullptr;
    }
    return &typeid(std::exception);
}
