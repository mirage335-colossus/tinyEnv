#pragma once

#include <gui/contract.hpp>

// Ordinary editable C++ handlers for the editor's own generated toolbar. The
// composition root injects its application as Services; no native toolkit or
// editor singleton is part of the handler contract.
namespace foundation::editor::self {

template<class Services, class UiContext>
void on_open(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.open"); }
template<class Services, class UiContext>
void on_new(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.new"); }
template<class Services, class UiContext>
void on_save(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.save"); }
template<class Services, class UiContext>
void on_undo(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.undo"); }
template<class Services, class UiContext>
void on_redo(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.redo"); }
template<class Services, class UiContext>
void on_preview(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.preview"); }
template<class Services, class UiContext>
void on_build(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.build"); }
template<class Services, class UiContext>
void on_run(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.run"); }
template<class Services, class UiContext>
void on_stop(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.stop"); }
template<class Services, class UiContext>
void on_details(Services& app, UiContext&, const gui::Activate&) { app.invoke("editor.details"); }

} // namespace foundation::editor::self
