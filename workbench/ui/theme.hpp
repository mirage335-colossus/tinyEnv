#pragma once

#include <gui/contract.hpp>
#include <array>
#include <cstdint>

namespace tinyenv::theme {

// The application supplies one palette to every adapter, including prompts and
// menus. Text tones retain readable contrast on both node and selection fills.
inline constexpr gui::Palette dark_palette() {
    gui::Palette palette;
    palette.background = {22, 27, 35};
    palette.surface = {31, 37, 47};
    palette.text = {225, 230, 238};
    palette.muted = {160, 174, 193};
    palette.accent = {136, 183, 239};
    palette.error = {246, 143, 151};
    palette.border = {80, 96, 116};
    palette.selection = {44, 66, 95};
    palette.disabled = {37, 43, 53};
    return palette;
}

using RasterColor = std::array<std::uint8_t, 3>;
inline constexpr RasterColor rgb(gui::Color color) {
    return {color.red, color.green, color.blue};
}

} // namespace tinyenv::theme
