#pragma once
#include "shared/application.hpp"
#include <gui/web.hpp>
#include <stdexcept>
#include <cstdlib>
#include <filesystem>
#include <fstream>

namespace fixture {
inline void capture(const unsigned char* data, unsigned width, unsigned height, const char* name) {
    const auto* directory=std::getenv("FOUNDATION_GUI_CAPTURE_DIR");if(!directory)return;
    const auto path=std::filesystem::path(directory)/(std::string(name)+".ppm");
    std::ofstream file(path,std::ios::binary);file<<"P6\n"<<width<<' '<<height<<"\n255\n";
    file.write(reinterpret_cast<const char*>(data),static_cast<std::streamsize>(width)*height*3);
    if(!file)throw std::runtime_error("Cannot save native fixture capture");
}

inline void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
inline const gui::Widget& widget(const gui::Snapshot& view, std::string id) {
    const auto* result = gui::find_widget(view, {std::move(id), 1});
    if (!result) throw std::runtime_error("Missing fixture control");
    return *result;
}
template<class Adapter> void unavailable_service(Adapter& adapter) {
    unsigned replies=0;
    adapter.service({900,gui::ServiceKind::open_file,"Select a file","",256},[&](gui::ServiceResult result){
        ++replies;check(result.id==900&&result.status==gui::ServiceStatus::error&&!result.error.empty(),
            "Unavailable service did not return an explicit error");
    });
    check(replies==1,"Unavailable service did not complete exactly once");
}
// Canonical serialization includes keys, geometry, labels, states and actions.
// No concrete adapter is allowed to reinterpret the declarations.
inline std::string declarations(const gui::Snapshot& view) {
    gui::WebAdapter recorder; recorder.present(view); return gui::web_detail::encode(recorder.presentation());
}
inline void capture_declarations(gui::Snapshot view, const std::string& name) {
    const auto* directory=std::getenv("FOUNDATION_GUI_CAPTURE_DIR");if(!directory)return;
    view.revision=1;
    std::ofstream output(std::filesystem::path(directory)/(name+".json"));
    output<<declarations(view)<<'\n';
    if(!output)throw std::runtime_error("Cannot save native fixture declarations");
}
template<class Adapter, class Sync, class Capture>
void visual_sizes(foundation::ui::Application& app, Adapter& adapter, const std::string& name, Sync sync, Capture capture) {
    for(const gui::Size size : {gui::Size{800,640},gui::Size{480,360}}) {
        app.handle(gui::ResizeEvent{size,1});
        adapter.focus(std::nullopt);sync();
        // Native resize delivery can acquire focus; clear it after that delivery.
        adapter.focus(std::nullopt);
        const auto stem=name+"-"+std::to_string(int(size.width));
        capture_declarations(app.view(),stem);capture(stem);
    }
    app.handle(gui::ResizeEvent{{800,640},1});sync();
}
template<class Edit, class Activate, class Select, class Sync>
void feature(foundation::ui::Application& app, Edit edit, Activate activate, Select select, Sync sync) {
    edit("Rejected \xc3\xa9"); sync(); activate("entries.add"); sync();
    check(widget(app.view(), "entries.list").state.records.empty(), "Core rejection differs");
    check(widget(app.view(), "entries.status").state.font.tone == gui::Tone::error, "Missing shared error");
    edit("First entry"); sync(); activate("entries.add"); sync();
    edit("Second entry"); sync(); activate("entries.add"); sync();
    app.enable_remove_feature(); sync();
    select(widget(app.view(), "entries.list").state.records.front().id); sync();
    activate("entries.remove"); sync();
    check(widget(app.view(), "entries.list").state.records.size() == 1, "Shared feature failed");
    check(widget(app.view(), "entries.list").state.records.front().accessible_text == "Second entry", "Wrong stable entry removed");
    app.handle(gui::ResizeEvent{{800, 640}, 1}); sync();
}
inline std::string reference() {
    gui::WebAdapter adapter;
    foundation::ui::Application app(adapter);
    feature(app, [&](std::string text) { app.handle(gui::WidgetEvent{{"entries.editor",1},gui::EditText{std::move(text),widget(app.view(),"entries.editor").state.text}}); },
        [&](std::string id) { app.handle(gui::WidgetEvent{{std::move(id),1},gui::Activate{}}); },
        [&](std::string id) { app.handle(gui::WidgetEvent{{"entries.list",1},gui::SelectRecord{std::move(id)}}); }, []{});
    auto view=app.view();view.revision=1;return declarations(view);
}
inline void parity(gui::Snapshot view) {
    view.revision=1;
    check(declarations(view)==reference(), "Backend changed serializable shared declarations");
}
}
