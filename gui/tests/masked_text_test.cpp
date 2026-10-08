#include <gui/framebuffer.hpp>
#include <gui/terminal.hpp>
#include <algorithm>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
const gui::WidgetKey editor_key{"generic/masked-editor",1};
const std::string secret="A\xc3\xa9\xf0\x9f\x99\x82Z";
void check(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
template<class F> void rejects(F action) {
    bool rejected=false;
    try {action();}catch(const std::invalid_argument&){rejected=true;}
    check(rejected,"Invalid masked declaration was accepted");
}
gui::Snapshot view(std::string text=secret,bool masked=true) {
    gui::Snapshot scene;scene.client_size={320,120};
    gui::Widget editor;editor.spec.key=editor_key;editor.spec.kind=gui::Kind::text;
    editor.spec.text_policy={false,false,128,gui::SubmitKey::enter,masked};
    editor.state.bounds={16,32,240,32};editor.state.text=std::move(text);
    editor.state.accessible_name="Secret entry";editor.state.placeholder="Type an entry";
    scene.widgets.push_back(std::move(editor));return scene;
}
void display_mapping_and_policy() {
    gui::TextPolicy legacy{false,false,128,gui::SubmitKey::enter};
    check(!legacy.masked&&gui::text_display(secret,legacy)==secret,"Existing text policy changed its display");
    auto masked=legacy;masked.masked=true;
    check(gui::text_display(secret,masked)=="****","Masked display retained a secret codepoint");
    check(gui::text_display("e\xcc\x81\t",masked)=="***","Combining mark or tab was not masked as a codepoint");
    const std::size_t source[]={0,1,3,7,8};
    for(std::size_t display=0;display<5;++display) {
        check(gui::text_display_offset(secret,masked,source[display])==display,"Source bytes did not map to masked display offsets");
        check(gui::text_source_offset(secret,masked,display)==source[display],"Masked display offsets did not map to source bytes");
    }
    check(gui::text_display_offset(secret,masked,2)==1&&gui::text_display_offset(secret,masked,6)==2,
          "Masked offset mapping split a Unicode codepoint");
    const auto oversized=std::numeric_limits<std::size_t>::max();
    check(gui::text_display_offset(secret,masked,oversized)==4&&gui::text_source_offset(secret,masked,oversized)==8,
          "Masked offsets did not clamp to the source end");
    check(gui::text_display_offset(secret,legacy,2)==1&&gui::text_source_offset(secret,legacy,6)==3,
          "Plain offset mapping lost UTF-8 byte boundaries");
    auto scene=view();gui::validate_snapshot(scene);
    check(gui::visible_text(scene.widgets[0])=="****","Shared visible text exposed the secret");
    scene.widgets[0].state.text.clear();
    check(gui::visible_text(scene.widgets[0])==scene.widgets[0].state.placeholder,"Shared masked text lost its empty placeholder");
    scene=view();
    scene.widgets[0].spec.text_policy.read_only=true;gui::validate_snapshot(scene);
    check(!gui::replace_text(secret,{0,8},"replacement",scene.widgets[0].spec.text_policy).changed,
          "Masking bypassed read-only text policy");
    scene=view();scene.widgets[0].spec.kind=gui::Kind::label;
    rejects([&]{gui::validate_snapshot(scene);});
    scene=view();scene.widgets[0].spec.text_policy.multiline=true;
    rejects([&]{gui::validate_snapshot(scene);});
    check(!gui::text_error("",scene.widgets[0].spec.text_policy).empty(),"Standalone text policy allowed masked multiline input");
    scene=view();scene.widgets[0].state.options={{"suggestion","Suggestion","candidate",true}};
    rejects([&]{gui::validate_snapshot(scene);});
}
void terminal_display_and_geometry() {
    gui::TerminalAdapter masked,plain;auto scene=view();masked.present(scene);plain.present(view("****",false));
    check(masked.render()==plain.render(),"Terminal rendered a secret or its clear-text width");
    masked.focus(editor_key);plain.focus(editor_key);
    for(const auto selection:{gui::TextSelection{0,0},gui::TextSelection{3,3},gui::TextSelection{7,1},gui::TextSelection{1,7},gui::TextSelection{8,8}}) {
        masked.text_selection(editor_key,selection);
        plain.text_selection(editor_key,{gui::text_display_offset(secret,scene.widgets[0].spec.text_policy,selection.anchor),
            gui::text_display_offset(secret,scene.widgets[0].spec.text_policy,selection.caret)});
        check(masked.render()==plain.render()&&masked.ansi_rows()==plain.ansi_rows(),
              "Terminal masked caret or reversed selection used clear-text geometry");
    }
    const auto box=masked.text_bounds(masked.snapshot().widgets[0]);
    masked.pointer({gui::PointerKind::click,{box.x+14,box.y+8}});
    check(masked.text_selection(editor_key)==gui::TextSelection{3,3},"Masked pointer hit split source bytes or followed clear-text width");
    masked.key(gui::Key::left);check(masked.text_selection(editor_key)==gui::TextSelection{1,1},"Masked navigation lost authoritative UTF-8 offsets");
    scene.widgets[0].state.bounds.width=32;masked.present(scene);
    auto ordinary=view("****",false);ordinary.widgets[0].state.bounds.width=32;plain.present(ordinary);
    masked.text_selection(editor_key,{8,8});plain.text_selection(editor_key,{4,4});
    masked.scroll(editor_key,{1000,0});plain.scroll(editor_key,{1000,0});
    check(masked.scroll_offset(editor_key)==plain.scroll_offset(editor_key),"Masked horizontal scroll limit measured the secret");
    scene.widgets[0].spec.text_policy.masked=false;
    rejects([&]{masked.present(scene);});
    check(masked.snapshot().widgets[0].spec.text_policy.masked,"Rejected mask toggle changed the retained declaration");
    scene.widgets[0].spec.key.generation=2;const auto plain_key=scene.widgets[0].spec.key;
    masked.present(scene);masked.focus(plain_key);masked.text_selection(plain_key,{8,8});
    gui::TerminalAdapter fresh_plain;fresh_plain.present(scene);fresh_plain.focus(plain_key);fresh_plain.text_selection(plain_key,{8,8});
    check(masked.scroll_offset(plain_key)==fresh_plain.scroll_offset(plain_key),"Replacing a masked editor lost the clear-text caret geometry");
    scene.widgets[0].spec.text_policy.masked=true;scene.widgets[0].spec.key.generation=3;const auto masked_key=scene.widgets[0].spec.key;
    masked.present(scene);masked.focus(masked_key);masked.text_selection(masked_key,{8,8});
    check(masked.scroll_offset(masked_key)==plain.scroll_offset(editor_key),"Replacing an editor lost its masked display geometry");
    gui::TerminalAdapter empty_masked,empty_plain;empty_masked.present(view("",true));empty_plain.present(view("",false));
    empty_masked.focus(editor_key);empty_plain.focus(editor_key);
    check(empty_masked.render()==empty_plain.render()&&empty_masked.ansi_rows()==empty_plain.ansi_rows(),
          "Masking changed empty placeholder or caret behavior");
    gui::TerminalAdapter controls;controls.present(view("Q\t\x1bR",true));plain.present(view("****",false));
    controls.focus(editor_key);controls.text_selection(editor_key,{0,0});plain.text_selection(editor_key,{0,0});
    check(controls.render()==plain.render(),"Terminal escaped a clear control character from a masked value");
}
void authoritative_editing() {
    auto scene=view();std::vector<gui::EditText> edits;gui::TerminalAdapter* active=nullptr;
    gui::TerminalAdapter adapter([&](const gui::Event& event) {
        const auto* widget=std::get_if<gui::WidgetEvent>(&event);if(!widget)return;
        const auto* edit=std::get_if<gui::EditText>(&widget->input);if(!edit)return;
        check(edit->base_text==scene.widgets[0].state.text,"Masked edit changed its authoritative base text");
        edits.push_back(*edit);scene.widgets[0].state.text=edit->value;active->present(scene);
    });active=&adapter;adapter.present(scene);adapter.focus(editor_key);
    adapter.text_selection(editor_key,{7,1});adapter.text("\xc3\xb1");
    check(edits.size()==1&&edits.back().value=="A\xc3\xb1Z"&&adapter.text_selection(editor_key)==gui::TextSelection{3,3},
          "Masked insertion replaced display placeholders instead of the selected secret bytes");
    adapter.key(gui::Key::backspace);
    check(edits.size()==2&&edits.back().value=="AZ"&&adapter.text_selection(editor_key)==gui::TextSelection{1,1},
          "Masked backspace split a codepoint or changed the display value only");
    adapter.key(gui::Key::select_all);adapter.text("paste\xc3\xa9");
    check(edits.size()==3&&edits.back().value=="paste\xc3\xa9"&&gui::text_display(edits.back().value,scene.widgets[0].spec.text_policy)=="******",
          "Masked select-all/insertion did not preserve clear authoritative text");
    const auto count=edits.size();adapter.text("\n");
    check(edits.size()==count&&scene.widgets[0].state.text=="paste\xc3\xa9","Masked editor accepted a newline");
}
void framebuffer_display_and_geometry() {
    gui::FramebufferAdapter masked,plain;const auto scene=view();masked.present(scene);plain.present(view("****",false));
    check(*masked.frame().pixels==*plain.frame().pixels,"Framebuffer painted the secret or used its clear-text geometry");
    masked.focus(editor_key);plain.focus(editor_key);masked.text_selection(editor_key,{7,1});plain.text_selection(editor_key,{3,1});
    check(*masked.frame().pixels==*plain.frame().pixels,"Framebuffer selection used secret bytes as display offsets");
    std::vector<std::string> measured,painted;gui::FramebufferTextRenderer font;
    font.measure=[&](const gui::TextMeasureRequest& request) {
        measured.push_back(request.text);return gui::Size{double(request.text.size())*10,18};
    };
    font.paint=[&](const gui::FramebufferTextRequest& request,const gui::FramebufferTextSink& sink) {
        painted.emplace_back(request.text);sink({request.bounds.x,request.bounds.y,2,5},request.color);
    };
    gui::FramebufferAdapter custom({},1024*1024,std::move(font));custom.present(scene);custom.focus(editor_key);
    custom.text_selection(editor_key,{3,7});(void)custom.frame();
    const auto allowed=[](const std::string& value) {return value=="M"||value.find_first_not_of('*')==std::string::npos;};
    check(std::all_of(measured.begin(),measured.end(),allowed)&&std::all_of(painted.begin(),painted.end(),allowed),
          "A framebuffer font callback received clear secret text");
    check(std::find(painted.begin(),painted.end(),"****")!=painted.end(),"Custom font did not paint masked codepoints");
    const auto box=custom.text_bounds(custom.snapshot().widgets[0]);
    custom.pointer({gui::PointerKind::click,{box.x+17,box.y+8}});
    check(custom.text_selection(editor_key)==gui::TextSelection{3,3},"Custom masked font metrics did not control pointer selection");
}
}
int main() {
    try {
        display_mapping_and_policy();terminal_display_and_geometry();authoritative_editing();framebuffer_display_and_geometry();
        std::cout<<"Masked text preserves source edits and byte offsets while obscuring shared rendering and geometry\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
