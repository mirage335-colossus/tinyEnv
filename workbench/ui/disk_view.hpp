#pragma once

#include <gui/contract.hpp>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace tinyenv {

struct DiskSector {
    std::string path;
    std::uint64_t bytes{};
    bool directory{};
};

// The application supplies a directory's entries and owns navigation. Each
// bitmap captures immutable pixels; retaining it never retains this view.
class DiskView {
public:
    std::vector<gui::Widget> render(const std::vector<DiskSector>& entries,
                                  gui::Rect viewport,
                                  const std::string& selected = {});
    [[nodiscard]] std::optional<std::string> hit_test(gui::Point point) const;

private:
    struct Sector {
        std::string path;
        double start{}, end{};
    };
    struct LegendHit {
        std::string path;
        gui::Rect bounds;
    };
    gui::Rect viewport_;
    gui::Point center_;
    double inner_radius_{}, outer_radius_{};
    std::vector<Sector> sectors_;
    std::vector<LegendHit> legend_;
    std::uint64_t revision_{};
};

} // namespace tinyenv
