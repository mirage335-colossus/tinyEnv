#include "workbench/ui/flow_view.hpp"
#include <gui/bitmap.hpp>

#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
gui::BitmapImage sample(const gui::BitmapSource& source, unsigned width, unsigned height,
                        gui::PixelFormat format = gui::PixelFormat::rgb24) {
    gui::BitmapImage image(width, height, format);
    source.paint(gui::full_bitmap_request(width, height, format),
                 [&](unsigned x, unsigned y, gui::PixelBlock block) { image.blit(x, y, block); });
    return image;
}
tinyenv::FlowGraph graph() {
    tinyenv::FlowGraph result;
    result.nodes = {{1, tinyenv::FlowKind::agent, 1, "Write", 0, 0, 160, 55},
                    {2, tinyenv::FlowKind::branch, 2, "Approved?", 0, 95, 160, 90},
                    {3, tinyenv::FlowKind::conclude, 3, "Return", 0, 225, 160, 55}};
    result.edges = {{1, 2, "next", false}, {2, 3, "yes", false}, {3, 1, "retry", true}};
    return result;
}
const gui::Widget& node_label(const std::vector<gui::Widget>& widgets) {
    for (const auto& widget : widgets) if (widget.spec.key.id == "wb.flow.node.1") return widget;
    throw std::runtime_error("Missing node label");
}
void frames() {
    auto model = graph();
    tinyenv::FlowView view;
    const gui::Rect viewport{10, 20, 400, 350};
    auto first = view.render(model, viewport);
    auto repeated = view.render(model, viewport);
    check(repeated.front().state.bitmap.revision == first.front().state.bitmap.revision,
          "Unchanged flow frame received a new bitmap identity");
    check(view.hit_test({50, 50}) == 1, "Cached frame lost hit regions");
    view.set_view(view.zoom(), view.pan());
    check(view.hit_test({50, 50}) == 1, "Unchanged transform discarded valid hit regions");
    auto prior_revision = first.front().state.bitmap.revision;
    auto changed = [&](const char* message) {
        auto next = view.render(model, viewport);
        check(next.front().state.bitmap.revision > prior_revision, message);
        prior_revision = next.front().state.bitmap.revision;
        return next;
    };
    model.nodes[0].label = "Changed text";
    auto text = changed("Changed label reused an obsolete flow frame");
    check(node_label(text).state.text.find("Changed text") != std::string::npos,
          "Cached flow frame retained stale label text");
    model.nodes[0].line = 8;
    check(node_label(changed("Changed source line reused obsolete accessibility")).state.accessible_name.find("line 8") != std::string::npos,
          "Changed source line did not reach accessibility text");
    model.nodes[0].kind = tinyenv::FlowKind::critique;
    changed("Changed kind reused obsolete fill");
    model.nodes[0].width += 10;
    changed("Changed geometry reused obsolete pixels");
    model.edges[0].label = "new edge";
    changed("Changed edge label reused obsolete labels");
    model.edges[0].loop = true;
    changed("Changed loop reused obsolete routing");
    auto selected = view.render(model, viewport, 1);
    check(selected.front().state.bitmap.revision > prior_revision, "Changed selection reused obsolete pixels");
    auto diagnostic = view.render(model, viewport, 1, {{9, 2, "Diagnostic"}});
    check(diagnostic.front().state.bitmap.revision > selected.front().state.bitmap.revision,
          "Changed diagnostics reused obsolete labels");
    const auto original_pixels = sample(first.front().state.bitmap.source, 400, 350).pixels();
    check(sample(first.front().state.bitmap.source, 400, 350).pixels() == original_pixels,
          "Later renders mutated a retained bitmap snapshot");
    view.set_view(1, {15, 25});
    auto panned = view.render(model, viewport);
    tinyenv::FlowView fresh;
    fresh.set_view(1, {15, 25});
    auto expected = fresh.render(model, viewport);
    check(sample(panned.front().state.bitmap.source, 400, 350).pixels() ==
          sample(expected.front().state.bitmap.source, 400, 350).pixels(),
          "Cached renderer changed panned frame pixels");
    view.set_view(1, {});
    view.render(model, viewport);
    check(view.begin_drag(1, {50, 50}), "Flow drag did not start");
    check(!view.drag_to(1, {52, 51}), "Sub-threshold motion changed the view");
    check(view.drag_to(1, {65, 60}), "Drag did not change the view");
    check(!view.drag_to(1, {65, 60}), "Duplicate drag coordinates changed the view");
    check(view.cancel_drag(1), "Flow drag did not cancel");
    view.render(model, viewport);
    model.nodes[0].width = std::numeric_limits<double>::quiet_NaN();
    bool rejected = false;
    try { view.render(model, viewport); } catch (const std::invalid_argument&) { rejected = true; }
    check(rejected, "Cached renderer bypassed invalid geometry validation");
}
void formats_and_damage() {
    gui::BitmapSource retained;
    {
        tinyenv::FlowView view;
        retained = view.render(graph(), {0, 0, 400, 350}).front().state.bitmap.source;
    }
    for (const auto format : {gui::PixelFormat::rgb24, gui::PixelFormat::gray8, gui::PixelFormat::mono1}) {
        for (const auto dimensions : {gui::Size{400, 350}, gui::Size{157, 113}}) {
            const auto width = unsigned(dimensions.width), height = unsigned(dimensions.height);
            auto full = sample(retained, width, height, format);
            gui::BitmapImage tiled(width, height, format);
            const unsigned split = width / 2;
            for (const gui::PixelRect damage : {gui::PixelRect{0, 0, split, height},
                                                gui::PixelRect{split, 0, width - split, height}})
                retained.paint({width, height, damage, format}, [&](unsigned x, unsigned y, gui::PixelBlock block) {
                    tiled.blit(x, y, block);
                });
            check(tiled.pixels() == full.pixels(), "Flow damage sampling changed pixels or packed tails");
            if (format != gui::PixelFormat::rgb24) {
                const auto rgb = sample(retained, width, height);
                gui::BitmapImage expected(width, height, format);
                expected.blit(0, 0, rgb.block());
                check(full.pixels() == expected.pixels(), "Flow format conversion changed grayscale or mono thresholds");
            }
        }
    }
}
void wheel_zoom() {
    tinyenv::FlowView view;
    const auto model = graph();
    const gui::Rect viewport{40, 65, 640, 440};
    const gui::Point anchor{238, 251};
    check(!view.zoom_at(1, anchor), "Unrendered canvas accepted wheel zoom");
    view.render(model, viewport);
    view.set_view(.8, {31, -19});
    view.render(model, viewport);
    const auto before = view.view_to_model(anchor);
    const auto near = [](double a, double b) { return std::abs(a-b) < 1e-9; };
    check(view.zoom_at(1, anchor) && near(view.zoom(), 1.0), "Upward wheel failed to zoom in");
    const auto retained = view.view_to_model(anchor);
    check(near(retained.x, before.x) && near(retained.y, before.y), "Wheel zoom moved the point under the cursor");
    check(view.zoom_at(-1, anchor) && near(view.zoom(), .8), "Downward wheel failed to zoom out");
    check(near(view.pan().x, 31) && near(view.pan().y, -19), "Wheel inverse did not restore the view");
    const auto pan = view.pan();
    check(!view.zoom_at(0, anchor) && !view.zoom_at(1, {10, 10}) &&
          !view.zoom_at(std::numeric_limits<double>::infinity(), anchor) &&
          !view.zoom_at(1, {std::numeric_limits<double>::quiet_NaN(), 100}) && view.pan() == pan,
          "Invalid or outside wheel input changed the view");
    check(view.zoom_at(.5, anchor) && view.zoom() > .8 && view.zoom() < 1.0,
          "Fractional wheel input lost smooth zoom");
    check(view.zoom_at(1e9, anchor) && view.zoom() == 2 && !view.zoom_at(1, anchor), "Upper wheel zoom bound failed");
    check(view.zoom_at(-1e9, anchor) && view.zoom() == .2 && !view.zoom_at(-1, anchor), "Lower wheel zoom bound failed");
    view.reset_view(); view.render(model, viewport);
    check(view.begin_drag(9, anchor) && view.zoom_at(1, anchor) && !view.dragging(),
          "Wheel zoom retained an obsolete drag transform");
    check(!view.hit_test(anchor), "Zoom retained stale hit regions before redraw");
    const auto rendered = view.render(model, viewport);
    const auto repeated = view.render(model, viewport);
    check(rendered.front().state.bitmap.revision == repeated.front().state.bitmap.revision,
          "Idle view after wheel zoom rerendered its bitmap");
}
void filtered_labels() {
    auto model = graph();
    model.nodes[0].label = "Safe\xe2\x80\x8d\\u202E[U+200D]&#x202E;%0A text";
    model.edges[0].label = "Edge\x1b\\n";
    const auto original = model.nodes[0].label;
    tinyenv::FlowView view;
    const auto widgets = view.render(model, {0,0,650,650}, 0, {{1, 1, "Issue\xe2\x80\xae[U+200D]"}});
    for (const auto& item : widgets) {
        for (const auto* field : {&item.state.text, &item.state.accessible_name}) {
            for (const unsigned char ch : *field) check(ch >= 32 && ch <= 126, "Unsafe diagram character reached presentation");
            check(field->find('\\') == std::string::npos && field->find("[U+") == std::string::npos &&
                  field->find("&#") == std::string::npos && field->find("%0A") == std::string::npos,
                  "An encoded escape reached flow label rendering");
        }
    }
    check(node_label(widgets).state.text.find('_') != std::string::npos && model.nodes[0].label == original,
          "Flow filtering failed to replace unsafe display text or changed the workflow source");
}
}
int main() {
    try { frames(); formats_and_damage(); wheel_zoom(); filtered_labels(); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
