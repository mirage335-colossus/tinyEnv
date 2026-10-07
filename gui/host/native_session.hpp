#pragma once
#include "contract.hpp"
#include "file_services.hpp"
namespace foundation::host {
// Native file selectors yield paths only to this host-side content provider.
// Embedders may keep Session's adapter-only provider or inject their own.
template<Application App, class Adapter> using NativeSession = Session<App, Adapter, FileServices>;
}
