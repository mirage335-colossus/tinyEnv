#include "adapter.hpp"
#include <iostream>
#include <stdexcept>
namespace {
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Events {int x=Fl::e_x,y=Fl::e_y,dx=Fl::e_dx,dy=Fl::e_dy;~Events(){Fl::e_x=x;Fl::e_y=y;Fl::e_dx=dx;Fl::e_dy=dy;}};
void exact_current_layout(bool readonly,bool caret_at_end,bool wrapped,bool trailing_lf,int height,int text_case){
    gui::fltk::Adapter adapter;gui::Snapshot view;view.client_size={800,500};
    gui::Widget editor;editor.spec.key={"editor",1};editor.spec.kind=gui::Kind::text;
    editor.spec.text_policy.multiline=true;editor.spec.text_policy.read_only=readonly;
    editor.state.bounds={20,20,614,double(height)};editor.state.font.size=13;editor.state.wrap=wrapped?gui::TextWrap::word:gui::TextWrap::none;
    if(text_case==2)for(int i=0;i<1800;++i)editor.state.text+="\xe7\x95\x8c";
    else for(int stage=1;stage<=(text_case?3:2);++stage){
        editor.state.text+="Native row "+std::to_string(stage)+": ";
        for(int word=0;word<7;++word)editor.state.text+="ordinary reply words confirm natural painting and wrapped rows. ";
        editor.state.text+="ROW_TAIL_0"+std::to_string(stage)+"Z";
    }
    if(trailing_lf)editor.state.text+='\n';
    view.widgets={editor};
    adapter.present(view);adapter.show();adapter.sync();Fl::check();Fl::handle(FL_FOCUS,&adapter.window());adapter.focus(editor.spec.key);
    const auto caret=caret_at_end?editor.state.text.size():0;adapter.text_selection(editor.spec.key,{caret,caret});Fl::flush();
    // A native width recount can advertise a blank row that resize() removes
    // after applying scroll(). Test the same final width with that recount.
    view.widgets[0].state.bounds.width-=1;adapter.present(view);adapter.sync();Fl::flush();
    view.widgets[0].state.bounds.width+=1;adapter.present(view);adapter.sync();Fl::flush();
    auto* native=dynamic_cast<Fl_Text_Editor*>(adapter.native_widget(editor.spec.key));check(native,"Exact native editor missing");
    const auto selected=adapter.text_selection(editor.spec.key);const auto focused=adapter.focused();const auto* native_focus=Fl::focus();
    adapter.scroll(editor.spec.key,{});adapter.sync();Fl::flush();
    adapter.scroll(editor.spec.key,{1e300,1e300});const auto reported=adapter.scroll_offset(editor.spec.key);
    for(int child=0;child<native->children();++child)if(const auto* bar=dynamic_cast<const Fl_Scrollbar*>(native->child(child));bar&&bar->type()==FL_VERTICAL)
        check(reported.y==double(std::max(0,bar->value()-1))*std::max(1,fl_height(native->textfont(),native->textsize())),
              "Current-layout scroll getter preceded the applied native position");
    adapter.sync();Fl::flush();
    check(adapter.scroll_offset(editor.spec.key)==reported,"Current-layout scroll reported an unreachable queued native clamp");
    check(adapter.text_selection(editor.spec.key)==selected&&adapter.focused()==focused&&Fl::focus()==native_focus&&std::size_t(native->buffer()->length())==editor.state.text.size(),
          "Current-layout scroll changed text, selection or focus");
    for(auto* control=static_cast<Fl_Widget*>(native);control;control=control->parent())control->clear_damage();
    adapter.scroll(editor.spec.key,{1e300,1e300});adapter.sync();
    check(adapter.scroll_offset(editor.spec.key)==reported&&!adapter.window().damage()&&!native->damage(),
          "Repeated saturated native scroll changed the viewport or scheduled a redraw");
    std::vector<std::pair<Fl_Widget*,unsigned char>> prior_damage;
    for(auto* control=static_cast<Fl_Widget*>(native);control;control=control->parent())
        check(!control->damage(),"No-op scroll left a native ancestor damaged");
    for(auto* control=static_cast<Fl_Widget*>(native);control;control=control->parent())control->damage(FL_DAMAGE_USER1);
    for(auto* control=static_cast<Fl_Widget*>(native);control;control=control->parent())prior_damage.emplace_back(control,control->damage());
    adapter.scroll(editor.spec.key,{1e300,1e300});adapter.sync();
    for(const auto& [control,damage]:prior_damage)check(control->damage()==damage,"No-op scroll erased existing native ancestor damage");
    check(adapter.text_selection(editor.spec.key)==selected&&adapter.focused()==focused&&Fl::focus()==native_focus,"No-op scroll changed native or retained selection/focus");Fl::flush();
    // Content of equal byte length can have a completely different row range.
    view.widgets[0].state.text.assign(editor.state.text.size(),'x');
    adapter.present(view);adapter.scroll(editor.spec.key,{0,1e300});adapter.sync();Fl::flush();
    adapter.scroll(editor.spec.key,{0,1e300});const auto replacement=adapter.scroll_offset(editor.spec.key);adapter.sync();Fl::flush();
    check(adapter.scroll_offset(editor.spec.key)==replacement,"Same-length replacement retained an obsolete native clamp");
    adapter.close();adapter.sync();check(adapter.error().empty(),"Exact native scroll callback failed");
}
void staged_unbroken_request(){
    gui::fltk::Adapter adapter;gui::Snapshot view;view.client_size={640,480};
    gui::Widget editor;editor.spec.key={"editor",1};editor.spec.kind=gui::Kind::text;editor.spec.text_policy.multiline=true;
    editor.state.bounds={20,20,360,150};editor.state.wrap=gui::TextWrap::word;view.widgets={editor};
    adapter.present(view);adapter.show();adapter.sync();Fl::check();Fl::flush();
    view.widgets[0].state.text.assign(24000,'x');adapter.present(view);adapter.scroll(editor.spec.key,{0,1e300});adapter.scroll(editor.spec.key,{});adapter.sync();Fl::flush();
    check(adapter.scroll_offset(editor.spec.key)==gui::Point{},"An older staged native request replaced the latest offset");
    view.widgets[0].state.text+='x';adapter.present(view);adapter.scroll(editor.spec.key,{});adapter.scroll(editor.spec.key,{0,1e300});adapter.sync();Fl::flush();
    check(adapter.scroll_offset(editor.spec.key).y>500,"Staged native request was clamped by generic unbroken-word measurement");
    adapter.close();adapter.sync();check(adapter.error().empty(),"Staged native scroll callback failed");
}
void exercise(bool readonly,bool caret_at_end,int text_case){
    gui::fltk::Adapter adapter;gui::Snapshot view;view.client_size={640,480};
    gui::Widget group;group.spec.key={"pane",1};group.spec.kind=gui::Kind::group;group.state.bounds={0,0,640,480};group.state.content_size={640,480};
    gui::Widget editor;editor.spec.key={"editor",1};editor.spec.parent="pane";editor.spec.kind=gui::Kind::text;
    editor.spec.text_policy.multiline=true;editor.spec.text_policy.read_only=readonly;editor.state.bounds={20,20,360,150};editor.state.wrap=gui::TextWrap::word;
    if(text_case==1)editor.state.text=std::string(24000,'x');
    else if(text_case==2)for(int i=0;i<6000;++i)editor.state.text+="\xe7\x95\x8c";
    else if(text_case==3)for(int i=0;i<50;++i)editor.state.text+="value={\"token\":\""+std::string(300,'x')+"\"};\r\n";
    else for(int i=0;i<60;++i)editor.state.text+="Line "+std::to_string(i)+" retains native wrapped wheel scrolling through repeated unrelated presentation.\n";
    gui::Widget status;status.spec.key={"status",1};status.spec.kind=gui::Kind::label;status.state.bounds={20,190,400,30};view.widgets={group,editor,status};
    adapter.present(view);adapter.show();adapter.sync();Fl::check();Fl::handle(FL_FOCUS,&adapter.window());adapter.focus(editor.spec.key);
    const auto caret=caret_at_end?editor.state.text.size():0;adapter.text_selection(editor.spec.key,{caret,caret});Fl::flush();
    adapter.scroll(editor.spec.key,{});adapter.sync();Fl::flush();
    auto* native=dynamic_cast<Fl_Text_Editor*>(adapter.native_widget(editor.spec.key));check(native,"Native long editor missing");
    Fl::belowmouse(native);Events restore;double last=0;bool moved=false,clamped=false;
    for(int tick=0;tick<80;++tick){
        Fl::e_x=native->x()+native->w()/2;Fl::e_y=native->y()+native->h()/2;Fl::e_dx=0;Fl::e_dy=1;
        Fl::handle(FL_MOUSEWHEEL,&adapter.window());adapter.sync();Fl::check();Fl::flush();
        const auto offset=adapter.scroll_offset(editor.spec.key).y;check(offset>=last,"Native wheel cycled a long text editor back upward");
        moved=moved||offset>0;clamped=clamped||(tick>20&&offset==last);last=offset;
        // Periodic application ticks can publish unrelated status while caret
        // visibility stays with the user's wheel viewport.
        view.widgets[2].state.text=std::to_string(tick);adapter.present(view);adapter.sync();Fl::flush();
        check(adapter.scroll_offset(editor.spec.key).y==last,"Periodic native presentation reset the user's text viewport");
        check(adapter.text_selection(editor.spec.key)==gui::TextSelection{caret,caret}&&std::size_t(native->buffer()->length())==editor.state.text.size(),
              "Native wheel changed text or the retained caret");
    }
    check(moved&&last>500,"Native wheel fixture did not scroll long wrapped text");
    adapter.scroll(editor.spec.key,{0,1e9});adapter.sync();Fl::flush();last=adapter.scroll_offset(editor.spec.key).y;
    Fl::e_dy=1;Fl::handle(FL_MOUSEWHEEL,&adapter.window());adapter.sync();Fl::flush();
    clamped=adapter.scroll_offset(editor.spec.key).y==last;
    check(clamped,"Native wheel escaped the editor's actual lower bound");
    for(int tick=0;tick<20;++tick){
        Fl::e_dy=-1;Fl::handle(FL_MOUSEWHEEL,&adapter.window());adapter.sync();Fl::flush();const auto offset=adapter.scroll_offset(editor.spec.key).y;
        check(offset<=last,"Native reverse wheel moved the viewport down");last=offset;
    }
    adapter.close();adapter.sync();check(adapter.error().empty(),"Native scrolling callback failed");
}
}
int main(){try{
    staged_unbroken_request();
    for(bool readonly:{false,true})for(bool end:{false,true})for(bool wrapped:{false,true})for(bool lf:{false,true})
        for(int height:{18,240})for(int text_case=0;text_case<3;++text_case)exact_current_layout(readonly,end,wrapped,lf,height,text_case);
    for(bool readonly:{false,true})for(bool end:{false,true})for(int text_case=0;text_case<4;++text_case)exercise(readonly,end,text_case);
    std::cout<<"Exact applied native clamps and long editable/readonly wheel views retain caret, focus and periodic presentation\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
