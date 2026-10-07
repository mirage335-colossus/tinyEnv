#include <gui/terminal.hpp>
#include <iostream>
#include <stdexcept>

namespace {
const gui::WidgetKey editor_key{"generic/editor",1};
void check(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
std::string style(gui::Color foreground,gui::Color background) {
    const auto rgb=[](gui::Color color) {
        return std::to_string(color.red)+';'+std::to_string(color.green)+';'+std::to_string(color.blue);
    };
    return "\x1b[38;2;"+rgb(foreground)+";48;2;"+rgb(background)+'m';
}
std::string style_at(const std::string& line,std::size_t column) {
    std::string current;std::size_t cell=0;
    for(std::size_t offset=0;offset<line.size();) {
        if(line[offset]=='\x1b') {
            const auto end=line.find('m',offset);
            check(end!=std::string::npos,"Malformed terminal style");
            current=line.substr(offset,end-offset+1);offset=end+1;
        } else {
            if(cell++==column)return current;
            ++offset;
        }
    }
    throw std::runtime_error("Missing terminal cell");
}
std::string literal_cells(const std::string& line) {
    std::string result;
    for(std::size_t offset=0;offset<line.size();) {
        if(line[offset]=='\x1b') {
            const auto end=line.find('m',offset);
            check(end!=std::string::npos,"Malformed terminal style");offset=end+1;
        } else result+=line[offset++];
    }
    return result;
}
gui::Snapshot view(std::string text={}) {
    gui::Snapshot result;
    result.palette.text={11,22,33};result.palette.surface={201,202,203};result.palette.selection={91,92,93};
    gui::Widget editor;editor.spec.key=editor_key;editor.spec.kind=gui::Kind::text;
    editor.state.bounds={16,32,240,32};editor.state.text=std::move(text);editor.state.placeholder="Type an entry";
    result.widgets.push_back(std::move(editor));return result;
}
void assert_no_caret(gui::TerminalAdapter& adapter,const gui::Palette& palette) {
    const auto inverted=style(palette.surface,palette.text);
    for(const auto& row:adapter.ansi_rows())
        check(row.find(inverted)==std::string::npos,"Caret appeared outside an editable visible cell");
}
void placeholder_and_text() {
    gui::TerminalAdapter adapter;auto scene=view();adapter.present(scene);
    const auto ordinary=style(scene.palette.text,scene.palette.surface);
    const auto inverted=style(scene.palette.surface,scene.palette.text);
    assert_no_caret(adapter,scene.palette);
    check(adapter.focus(editor_key),"Could not focus generic editor");
    auto plain=adapter.render();auto ansi=adapter.ansi_rows();
    check(plain[2].substr(3,13)=="Type an entry","Focused caret replaced a placeholder character");
    check(style_at(ansi[2],3)==inverted&&style_at(ansi[2],4)==ordinary,"Placeholder caret was not one visible styled cell");
    check(literal_cells(ansi[2])==plain[2],"ANSI presentation changed literal cells");
    scene.widgets[0].state.text="ABCD";adapter.present(scene);
    for(const std::size_t caret:{0u,2u,4u}) {
        adapter.text_selection(editor_key,{caret,caret});plain=adapter.render();ansi=adapter.ansi_rows();
        check(plain[2].substr(3,5)=="ABCD ","Caret changed text at beginning, middle or end");
        for(std::size_t column=3;column<=7;++column)
            check(style_at(ansi[2],column)==(column==3+caret?inverted:ordinary),"Caret style was misplaced or covered multiple cells");
    }
    adapter.text_selection(editor_key,{0,2});ansi=adapter.ansi_rows();
    check(style_at(ansi[2],3)==style(scene.palette.text,scene.palette.selection)&&
          style_at(ansi[2],4)==style(scene.palette.text,scene.palette.selection)&&
          style_at(ansi[2],5)==inverted,"Caret erased retained selection styling");
    adapter.text_selection(editor_key,{2,0});ansi=adapter.ansi_rows();
    check(style_at(ansi[2],3)==style(scene.palette.selection,scene.palette.text)&&
          style_at(ansi[2],4)==style(scene.palette.text,scene.palette.selection),"Caret did not retain the underlying selected-cell colors");
    adapter.focus(std::nullopt);assert_no_caret(adapter,scene.palette);
    gui::TerminalAdapter read_only;scene.widgets[0].spec.text_policy.read_only=true;read_only.present(scene);
    check(read_only.focus(editor_key),"Could not focus read-only editor");assert_no_caret(read_only,scene.palette);
}
void escaped_text_and_wrapping() {
    gui::TerminalAdapter adapter;auto scene=view("A\xf0\x9f\x99\x82\x1b");adapter.present(scene);adapter.focus(editor_key);
    const auto inverted=style(scene.palette.surface,scene.palette.text);
    const std::string escaped="A\\u{1f642}\\x1b";
    for(const auto& [caret,column]:{std::pair<std::size_t,std::size_t>{1,4},{5,13},{6,17}}) {
        adapter.text_selection(editor_key,{caret,caret});const auto plain=adapter.render(),ansi=adapter.ansi_rows();
        check(plain[2].substr(3,escaped.size())==escaped,"Caret corrupted escaped Unicode or control text");
        check(style_at(ansi[2],column)==inverted,"Caret lost escaped text width mapping");
    }
    scene.widgets[0].state.text="alpha beta gamma";scene.widgets[0].state.bounds={16,32,84,80};
    scene.widgets[0].spec.text_policy.multiline=true;scene.widgets[0].state.wrap=gui::TextWrap::word;
    gui::TerminalAdapter wrapped;wrapped.present(scene);wrapped.focus(editor_key);wrapped.text_selection(editor_key,{6,6});
    const auto plain=wrapped.render(),ansi=wrapped.ansi_rows();
    check(plain[2].substr(3,5)=="alpha"&&plain[3].substr(3,4)=="beta"&&plain[4].substr(3,5)=="gamma",
          "Wrapped caret changed displayed text");
    check(style_at(ansi[3],3)==inverted,"Wrapped caret was on the wrong visual line");
}
void clipping_and_panning() {
    gui::TerminalAdapter adapter;auto scene=view("AB");scene.widgets[0].state.bounds.width=32;
    adapter.present(scene);adapter.focus(editor_key);adapter.text_selection(editor_key,{2,2});
    check(adapter.render()[2].substr(3,3)=="AB ","Caret wrote into editor padding");
    assert_no_caret(adapter,scene.palette);
    scene.widgets[0].state.text.clear();scene.widgets[0].state.bounds.width=13;adapter.present(scene);
    assert_no_caret(adapter,scene.palette); // No complete cell center fits the text box.
    scene=view("ABCD");gui::Widget group;group.spec.key={"generic/clip",1};group.spec.kind=gui::Kind::group;
    group.state.bounds={0,0,320,160};group.state.content_clip=gui::Rect{32,0,288,160};
    scene.widgets[0].spec.parent=group.spec.key.id;scene.widgets.insert(scene.widgets.begin(),group);
    gui::TerminalAdapter clipped;clipped.present(scene);clipped.focus(editor_key);clipped.text_selection(editor_key,{0,0});
    assert_no_caret(clipped,scene.palette); // First text cell is outside the parent clip.
    gui::TerminalAdapter panned;scene=view("ABCD");scene.widgets[0].state.bounds={440,32,160,32};panned.present(scene);
    panned.terminal_size(20,8);panned.focus(editor_key);panned.text_selection(editor_key,{0,0});
    auto plain=panned.render();auto ansi=panned.ansi_rows();
    const auto inverted=style(scene.palette.surface,scene.palette.text);
    check(panned.viewport_origin().x>0&&plain[2][19]=='A'&&style_at(ansi[2],19)==inverted,
          "Panned viewport lost the first text cell or caret");
    panned.text_selection(editor_key,{2,2});panned.input("");plain=panned.render();ansi=panned.ansi_rows();
    check(plain[2].substr(17,3)=="ABC"&&style_at(ansi[2],19)==inverted,"Panned middle caret changed visible text");
}
}
int main() {
    try {placeholder_and_text();escaped_text_and_wrapping();clipping_and_panning();
        std::cout<<"Terminal caret preserves literal text, style, clipping and viewport mapping\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
