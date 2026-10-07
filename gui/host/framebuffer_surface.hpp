#pragma once
#include <gui/framebuffer.hpp>
#include <cstddef>
#include <limits>
#include <span>
#include <stdexcept>

namespace foundation::host {
enum class PixelFormat { rgb24, rgba8888, bgra8888, rgb565le };
struct Surface {
    std::span<unsigned char> pixels;
    std::size_t width = 0, height = 0, stride = 0;
    PixelFormat format = PixelFormat::rgb24;
};
// Device-owned memory never enters the application. Validate the whole source,
// destination and damage rectangle before the first write, including padding.
inline void copy_frame(const gui::Frame& frame, Surface surface) {
    const std::size_t bytes = surface.format == PixelFormat::rgb24 ? 3 :
        surface.format == PixelFormat::rgb565le ? 2 : 4;
    if (surface.format != PixelFormat::rgb24 && surface.format != PixelFormat::rgba8888 &&
        surface.format != PixelFormat::bgra8888 && surface.format != PixelFormat::rgb565le)
        throw std::invalid_argument("Unknown framebuffer pixel format");
    const auto maximum = std::numeric_limits<std::size_t>::max();
    if (!frame.pixels || !frame.width || !frame.height || frame.width != surface.width ||
        frame.height != surface.height || surface.width > maximum / bytes ||
        surface.width > maximum / 3 || surface.height > maximum / (surface.width * 3) ||
        frame.stride_bytes != surface.width * 3 ||
        frame.pixels->size() != surface.width * surface.height * 3 ||
        surface.stride < surface.width * bytes ||
        surface.height > maximum / surface.stride || surface.pixels.size() < surface.stride * surface.height)
        throw std::invalid_argument("Invalid framebuffer surface extent or stride");
    const auto d = frame.damage;
    // Frame damage uses integer device coordinates. Subtraction avoids overflow.
    if (d.x > frame.width || d.y > frame.height || d.width > frame.width - d.x ||
        d.height > frame.height - d.y)
        throw std::invalid_argument("Framebuffer damage escapes the frame");
    for (std::size_t y = d.y; y < d.y + d.height; ++y)
        for (std::size_t x = d.x; x < d.x + d.width; ++x) {
            const auto* in = frame.pixels->data() + (y * frame.width + x) * 3;
            auto* out = surface.pixels.data() + y * surface.stride + x * bytes;
            if (surface.format == PixelFormat::rgb565le) {
                const unsigned packed = (unsigned(in[0] >> 3) << 11) | (unsigned(in[1] >> 2) << 5) | (in[2] >> 3);
                out[0] = static_cast<unsigned char>(packed & 255); out[1] = static_cast<unsigned char>(packed >> 8);
            } else {
                out[0] = in[surface.format == PixelFormat::bgra8888 ? 2 : 0];
                out[1] = in[1]; out[2] = in[surface.format == PixelFormat::bgra8888 ? 0 : 2];
                if (bytes == 4) out[3] = 255;
            }
        }
}
} // namespace foundation::host
