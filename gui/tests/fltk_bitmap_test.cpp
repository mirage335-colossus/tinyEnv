#include "adapter.hpp"
#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
void flush() { Fl::check(); Fl::flush(); }
void pixel(gui::fltk::Adapter& adapter, std::array<unsigned char, 3> expected) {
    adapter.window().make_current();
    const std::unique_ptr<unsigned char[]> bytes(fl_read_image(nullptr, 40, 40, 1, 1));
    check(bytes && bytes[0] == expected[0] && bytes[1] == expected[1] && bytes[2] == expected[2],
          "Native bitmap did not display the committed pixels");
}
}
int main() {
    try {
        gui::fltk::Adapter adapter;
        unsigned calls = 0;
        std::array<unsigned char, 3> color{19, 71, 133};
        gui::Snapshot view; view.client_size = {240, 180};
        gui::Widget bitmap; bitmap.spec.key = {"bitmap", 1}; bitmap.spec.kind = gui::Kind::bitmap;
        bitmap.state.bounds = {20, 20, 120, 100};
        bitmap.state.bitmap = {"fixture", 1, gui::BitmapSource([&](const gui::BitmapRequest& request, const gui::BitmapSink& sink) {
            ++calls;
            gui::solid_bitmap(color[0], color[1], color[2]).paint(request, sink);
        })};
        view.widgets = {bitmap}; adapter.present(view); adapter.show();
        for (int i = 0; i < 10 && !calls; ++i) { Fl::wait(.01); flush(); }
        check(calls == 1 && adapter.error().empty(), "Initial native bitmap did not paint exactly once");
        pixel(adapter, color);
        // An unchanged polling tick must not schedule another native upload or
        // repaint the entire window. Checking native damage is deterministic.
        for (int i = 0; i < 8; ++i) {
            adapter.sync();
            check(!adapter.window().damage() && !adapter.native_widget(bitmap.spec.key)->damage(),
                  "Idle synchronization scheduled a redundant native redraw");
            flush();
        }
        check(calls == 1, "Idle synchronization sampled unchanged bitmap content");
        color = {101, 29, 77};
        adapter.invalidate(bitmap.spec.key, {0, 0, 120, 100}); adapter.sync(); flush();
        check(calls == 2, "Explicit bitmap invalidation did not reach native presentation");
        pixel(adapter, color);
        // Same content identity still rebuilds geometry/representation storage.
        view.bitmap_format = gui::PixelFormat::gray8;
        adapter.present(view); adapter.sync(); flush();
        const auto gray = static_cast<unsigned char>((77u * color[0] + 150u * color[1] + 29u * color[2] + 128u) / 256u);
        pixel(adapter, {gray, gray, gray});
        view.bitmap_format = gui::PixelFormat::mono1;
        adapter.present(view); adapter.sync(); flush();
        const auto bit = static_cast<unsigned char>(gray >= 128 ? 255 : 0);
        pixel(adapter, {bit, bit, bit});
        view.bitmap_format = gui::PixelFormat::rgb24;
        view.widgets.front().state.bounds = {20, 20, 130, 105};
        adapter.present(view); adapter.sync(); flush(); pixel(adapter, color);
        // Fractional logical bounds exercise the retained backing-grid scaling
        // fallback; exact RGB drawing and conversion retain the same colors.
        view.widgets.front().state.bounds = {20, 20, 130.5, 105.5};
        adapter.present(view); adapter.sync(); flush(); pixel(adapter, color);
        view.widgets.clear(); adapter.present(view); adapter.sync(); flush();
        check(!adapter.native_widget(bitmap.spec.key), "Removed native bitmap retained a live control");
        bitmap.spec.key.generation = 2; bitmap.state.bitmap.revision = 2;
        color = {7, 151, 41}; view.widgets = {bitmap};
        adapter.present(view); adapter.sync(); flush(); pixel(adapter, color);
        // Prompt completion remains live even with no new application snapshot.
        bool completed = false;
        adapter.service({1, gui::ServiceKind::prompt, "Fixture", ""}, [&](gui::ServiceResult) { completed = true; });
        flush(); check(Fl::modal(), "Native prompt did not open");
        Fl::modal()->do_callback(); adapter.sync(); flush();
        check(completed && !adapter.service_active(), "Idle sync deferred native prompt completion");
        check(adapter.error().empty(), "Native bitmap fixture encountered an adapter failure");
        adapter.close(); flush();
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
