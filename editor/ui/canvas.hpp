#pragma once

#include "../model/project.hpp"
#include <gui/contract.hpp>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace foundation::editor {

enum class CanvasMode { forms, flows };
enum class PortDirection { input, output };

// Model identities, never toolkit controls. Empty port means the object's body.
// Resize identifies the selected object's lower-right handle. Edge identities
// are returned with edge=true so a selected wire can be disconnected.
struct Hit {
    std::string object, port;
    std::optional<PortDirection> direction;
    bool resize = false, edge = false;
    bool operator==(const Hit&) const = default;
};
struct CanvasOptions {
    CanvasMode mode = CanvasMode::forms;
    std::string document, selected;
    gui::Rect viewport;
    double zoom = 1;
    // Pan is in logical model units. Increasing pan moves the view right/down
    // through the document, so objects move left/up on the screen.
    gui::Point pan;
    bool preview = false;
    std::optional<Hit> pending_port;
    // Native text metrics size port columns without toolkit-specific guesses.
    // A conservative character estimate is available to standalone callers.
    gui::TextMeasure measure_text = {};
};

// One UI-thread-owned scene. Every returned bitmap captures immutable owned
// bytes, so a retained snapshot remains valid after another render or deletion.
// Rendering is bounded to the viewport; offscreen blocks/ports remain hit-test
// geometry only. The editor owns gestures and semantic edits.
class Canvas {
public:
    std::vector<gui::Widget> render(const Project&, const CanvasOptions&);
    std::optional<Hit> hit_test(gui::Point) const;
    gui::Point model_to_view(gui::Point) const;
    gui::Point view_to_model(gui::Point) const;
    std::optional<gui::Rect> object_bounds(std::string_view id) const;
    std::optional<gui::Point> port_position(std::string_view block,
                                          std::string_view port,
                                          PortDirection) const;
    gui::Rect bounds() const { return options_.viewport; }
private:
    struct Object { std::string id; gui::Rect area; bool resizable = false, group = false; };
    struct Endpoint { Hit hit; gui::Point point; gui::Rect label; };
    struct Wire { std::string id; std::vector<gui::Point> points; };
    CanvasOptions options_;
    std::vector<Object> objects_;
    std::vector<Endpoint> endpoints_;
    std::vector<Wire> wires_;
    std::uint64_t revision_ = 0;
};

} // namespace foundation::editor
