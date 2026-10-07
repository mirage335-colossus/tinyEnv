#pragma once
#include "framebuffer.hpp"
#include "file_services.hpp"
namespace foundation::host {
// Desktop/OS framebuffer composition; bare device drivers can retain the
// filesystem-free FramebufferHost<App, AdapterServices> or supply a provider.
template<Application App> using NativeFramebufferHost = FramebufferHost<App, FileServices>;
}
