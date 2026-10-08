#include <gui/bitmap.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Format = gui::PixelFormat;
using Rgb = std::array<std::uint8_t, 3>;
constexpr std::array formats{Format::mono1, Format::gray8, Format::rgb24};

void check(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}

// A deliberately simple pixel oracle, independent of the bulk-copy helpers.
std::size_t row_bytes(unsigned width, Format format) {
    if (format == Format::rgb24) return std::size_t(width) * 3;
    if (format == Format::gray8) return width;
    return (width + 7u) / 8u;
}

Rgb read_pixel(std::span<const std::uint8_t> bytes, std::size_t stride,
               unsigned x, unsigned y, Format format) {
    const auto row = std::size_t(y) * stride;
    if (format == Format::rgb24) {
        const auto offset = row + std::size_t(x) * 3;
        return {bytes[offset], bytes[offset + 1], bytes[offset + 2]};
    }
    const auto gray = format == Format::gray8 ? bytes[row + x] :
        std::uint8_t((bytes[row + x / 8] & (0x80u >> (x % 8))) ? 255 : 0);
    return {gray, gray, gray};
}

void write_pixel(std::vector<std::uint8_t>& bytes, std::size_t stride,
                 unsigned x, unsigned y, Format format, Rgb rgb) {
    const auto row = std::size_t(y) * stride;
    if (format == Format::rgb24) {
        for (unsigned channel = 0; channel < 3; ++channel)
            bytes[row + std::size_t(x) * 3 + channel] = rgb[channel];
        return;
    }
    const auto gray = std::uint8_t((77u * rgb[0] + 150u * rgb[1] +
                                  29u * rgb[2] + 128u) / 256u);
    if (format == Format::gray8) bytes[row + x] = gray;
    else {
        auto& byte = bytes[row + x / 8];
        const auto bit = std::uint8_t(0x80u >> (x % 8));
        if (gray >= 128) byte |= bit;
        else byte &= std::uint8_t(~bit);
    }
}

void oracle_blit(std::vector<std::uint8_t>& destination, std::size_t stride,
                 Format format, unsigned x, unsigned y, gui::PixelBlock input) {
    // Snapshot every source pixel before writing, including same-image overlap.
    std::vector<Rgb> pixels;
    for (unsigned row = 0; row < input.height; ++row)
        for (unsigned column = 0; column < input.width; ++column)
            pixels.push_back(read_pixel(input.bytes, input.stride_bytes,
                                        column, row, input.format));
    std::size_t index = 0;
    for (unsigned row = 0; row < input.height; ++row)
        for (unsigned column = 0; column < input.width; ++column)
            write_pixel(destination, stride, x + column, y + row, format, pixels[index++]);
}

void oracle_clear(std::vector<std::uint8_t>& bytes, std::size_t stride,
                  Format format, gui::PixelRect area) {
    for (unsigned y = area.y; y < area.y + area.height; ++y)
        for (unsigned x = area.x; x < area.x + area.width; ++x)
            write_pixel(bytes, stride, x, y, format, {0, 0, 0});
}

void equal_bytes(const gui::BitmapImage& image,
                 const std::vector<std::uint8_t>& expected, const std::string& context) {
    check(image.pixels().size() == expected.size(), context + ": storage length changed");
    for (std::size_t i = 0; i < expected.size(); ++i)
        check(image.pixels()[i] == expected[i], context + ": byte " + std::to_string(i) + " differs");
}

Rgb pattern(unsigned x, unsigned y, unsigned salt) {
    return {std::uint8_t(x * 71 + y * 29 + salt * 17),
            std::uint8_t(x * 23 + y * 97 + salt * 43),
            std::uint8_t(x * 53 + y * 11 + salt * 61)};
}

struct Storage {
    unsigned width, height;
    std::size_t stride;
    Format format;
    std::vector<std::uint8_t> bytes;
    gui::PixelBlock block() const { return {width, height, stride, format, bytes}; }
};

Storage patterned(unsigned width, unsigned height, Format format, unsigned padding,
                  unsigned salt, unsigned origin_x = 0, unsigned origin_y = 0) {
    const auto row = row_bytes(width, format), stride = row + padding;
    // The final row has no padding: the minimum valid readable byte span.
    Storage result{width, height, stride, format,
                   std::vector<std::uint8_t>(height ? (height - 1) * stride + row : 0, 0xd3)};
    for (unsigned y = 0; y < height; ++y)
        for (unsigned x = 0; x < width; ++x)
            write_pixel(result.bytes, stride, x, y, format,
                        pattern(origin_x + x, origin_y + y, salt));
    return result;
}

gui::BitmapImage initial_image(unsigned width, unsigned height, Format format,
                               std::vector<std::uint8_t>& expected) {
    gui::BitmapImage image(width, height, format);
    expected.assign(row_bytes(width, format) * height, 0);
    const auto source = patterned(width, height, format, 3, 5);
    oracle_blit(expected, row_bytes(width, format), format, 0, 0, source.block());
    image.blit(0, 0, source.block());
    equal_bytes(image, expected, "Initial image");
    return image;
}

void copies_and_clears() {
    unsigned scenario = 0;
    for (const unsigned width : {1u, 2u, 7u, 8u, 9u, 13u})
        for (const unsigned height : {1u, 3u, 5u})
            for (const auto target_format : formats)
                for (const auto source_format : formats)
                    for (const unsigned padding : {0u, 1u, 4u}) {
                        const auto context = "Copy/clear scenario " + std::to_string(++scenario);
                        std::vector<std::uint8_t> expected;
                        auto image = initial_image(width, height, target_format, expected);
                        const unsigned copied_width = 1 + scenario % width;
                        const unsigned copied_height = 1 + (scenario / 3) % height;
                        const unsigned x = (width - copied_width) / 2;
                        const unsigned y = (height - copied_height) / 2;
                        const auto input = patterned(copied_width, copied_height, source_format,
                                                     padding, scenario);
                        const auto original_input = input.bytes;
                        oracle_blit(expected, row_bytes(width, target_format), target_format,
                                    x, y, input.block());
                        image.blit(x, y, input.block());
                        equal_bytes(image, expected, context + " copy");
                        check(input.bytes == original_input, context + ": source padding was modified");
                        const std::array clears{
                            gui::PixelRect{x, y, copied_width, copied_height},
                            gui::PixelRect{width - 1, height - 1, 1, 1},
                            gui::PixelRect{width, height, 0, 0},
                            gui::PixelRect{0, 0, width, height}};
                        for (const auto area : clears) {
                            oracle_clear(expected, row_bytes(width, target_format), target_format, area);
                            image.clear(area);
                            equal_bytes(image, expected, context + " clear");
                        }
                    }
    check(scenario == 486, "Deterministic copy/clear matrix did not execute completely");
}

void overlapping_copies() {
    struct Copy { unsigned from_x, from_y, to_x, to_y, width, height; };
    for (const auto format : formats) {
        std::vector<Copy> copies{{0, 0, 2, 0, 11, 5}, {0, 0, 0, 1, 13, 4},
                                 {0, 1, 0, 0, 13, 4}, {0, 0, 2, 1, 11, 4}};
        // Mono1 input starts on a byte boundary; destination need not do so.
        copies.push_back(format == Format::mono1 ? Copy{8, 0, 0, 0, 5, 5} :
                                                  Copy{2, 0, 0, 0, 11, 5});
        for (const auto copy : copies) {
            std::vector<std::uint8_t> expected;
            auto image = initial_image(13, 5, format, expected);
            const auto stride = image.block().stride_bytes;
            const auto column = format == Format::mono1 ? copy.from_x / 8 :
                std::size_t(copy.from_x) * (format == Format::rgb24 ? 3 : 1);
            const auto offset = std::size_t(copy.from_y) * stride + column;
            const gui::PixelBlock input{copy.width, copy.height, stride, format,
                std::span<const std::uint8_t>(image.pixels()).subspan(offset)};
            oracle_blit(expected, stride, format, copy.to_x, copy.to_y, input);
            image.blit(copy.to_x, copy.to_y, input);
            equal_bytes(image, expected, "Overlapping horizontal/vertical copy");
        }
    }
}

void mono_tail_bits() {
    for (const unsigned width : {1u, 7u, 9u, 13u}) {
        std::vector<std::uint8_t> expected;
        auto image = initial_image(width, 3, Format::mono1, expected);
        const auto stride = image.block().stride_bytes;
        const auto mask = std::uint8_t((1u << (8u - width % 8u)) - 1u);
        // Fixture-only storage access seeds unused bits which public blit never
        // writes. The original image/storage is non-const; this is not a cast
        // away from a const object. Logical writes must preserve these sentinels.
        auto& storage = const_cast<std::vector<std::uint8_t>&>(image.pixels());
        for (unsigned y = 0; y < 3; ++y) {
            storage[(y + 1) * stride - 1] |= mask;
            expected[(y + 1) * stride - 1] |= mask;
        }
        const auto input = patterned(width, 2, Format::mono1, 2, 41);
        oracle_blit(expected, stride, Format::mono1, 0, 1, input.block());
        image.blit(0, 1, input.block());
        equal_bytes(image, expected, "Mono1 copy preserved neighboring/tail bits");
        for (const auto area : {gui::PixelRect{0, 1, width - 1, 1},
                               gui::PixelRect{0, 0, width, 3}}) {
            oracle_clear(expected, stride, Format::mono1, area);
            image.clear(area);
            equal_bytes(image, expected, "Mono1 clear preserved neighboring/tail bits");
        }
    }
}

void producer_rollback_and_retry() {
    for (const auto format : formats) {
        gui::BitmapSurface surface;
        check(surface.resize(13, 5, format), "Initial surface resize was ignored");
        surface.set_source("before", 1, gui::solid_bitmap(37, 163, 211));
        check(surface.repaint(), "Initial surface did not repaint");
        auto expected = surface.image().pixels();
        bool fail = true;
        unsigned attempts = 0;
        gui::PixelRect last_damage;
        surface.set_source("after", 2, gui::BitmapSource(
            [&](const gui::BitmapRequest& request, const gui::BitmapSink& sink) {
                ++attempts; last_damage = request.damage;
                const auto input = patterned(request.damage.width, request.damage.height,
                    request.format, 2, 29, request.damage.x, request.damage.y);
                sink(request.damage.x, request.damage.y,
                     {input.width, 1, input.stride, input.format, input.bytes});
                if (fail) throw std::runtime_error("Fixture producer failure after first row");
                sink(request.damage.x, request.damage.y, input.block());
            }));
        bool threw = false;
        try { surface.repaint(); } catch (const std::runtime_error&) { threw = true; }
        check(threw && attempts == 1 && surface.dirty(), "Producer failure lost pending repaint");
        equal_bytes(surface.image(), expected, "Failed producer committed partial pixels");
        fail = false;
        const auto after = patterned(13, 5, format, 2, 29);
        oracle_clear(expected, row_bytes(13, format), format, {0, 0, 13, 5});
        oracle_blit(expected, row_bytes(13, format), format, 0, 0, after.block());
        check(surface.repaint() && attempts == 2 && !surface.dirty(), "Producer retry did not commit");
        equal_bytes(surface.image(), expected, "Retried producer pixels");
        check(!surface.repaint() && attempts == 2, "Clean surface repainted again");
        const gui::PixelRect damage{2, 1, 4, 2};
        surface.invalidate(damage);
        check(surface.repaint() && attempts == 3 && last_damage == damage,
              "Partial invalidation did not retain exact damage");
        equal_bytes(surface.image(), expected, "Partial repaint erased pixels outside damage");
    }
}

void blank_and_sparse_producers() {
    for (const auto format : formats) {
        gui::BitmapSurface surface;
        surface.resize(13, 5, format);
        surface.set_source("filled", 1, gui::solid_bitmap(255, 255, 255));
        check(surface.repaint(), "Filled surface did not repaint");
        surface.set_source("blank", 2, {});
        check(surface.repaint(), "Blank replacement did not clear its full grid");
        std::vector<std::uint8_t> expected(row_bytes(13, format) * 5, 0);
        equal_bytes(surface.image(), expected, "Blank replacement retained old pixels");
        const gui::PixelRect tile{2, 1, 4, 2};
        surface.set_source("sparse", 3, gui::BitmapSource(
            [tile](const gui::BitmapRequest& request, const gui::BitmapSink& sink) {
                const auto left = std::max(tile.x, request.damage.x);
                const auto top = std::max(tile.y, request.damage.y);
                const auto right = std::min(tile.x + tile.width,
                                            request.damage.x + request.damage.width);
                const auto bottom = std::min(tile.y + tile.height,
                                             request.damage.y + request.damage.height);
                if (left >= right || top >= bottom) return;
                const auto input = patterned(right - left, bottom - top, request.format,
                                             1, 73, left, top);
                sink(left, top, input.block());
            }));
        const auto input = patterned(tile.width, tile.height, format, 1, 73, tile.x, tile.y);
        oracle_blit(expected, row_bytes(13, format), format, tile.x, tile.y, input.block());
        check(surface.repaint(), "Sparse full repaint was ignored");
        equal_bytes(surface.image(), expected, "Sparse full repaint left nonblack omitted pixels");
        surface.invalidate({0, 0, 4, 3});
        check(surface.repaint(), "Sparse partial repaint was ignored");
        equal_bytes(surface.image(), expected, "Sparse partial repaint altered outside pixels");
        surface.resize(0, 0, format);
        check(surface.image().pixels().empty() && !surface.repaint(),
              "Empty surface retained storage or painted an empty grid");
    }
}
} // namespace

int main() {
    try {
        copies_and_clears(); overlapping_copies(); mono_tail_bits(); producer_rollback_and_retry();
        blank_and_sparse_producers();
        std::cout << "Bitmap copies, overlap, padding, conversions, partial clears and producer rollback passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
