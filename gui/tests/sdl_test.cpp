#include "tests/fixture.hpp"
#include "sdl_runner.hpp"

namespace {
void key(SDL_Keycode value, SDL_Keymod modifiers=KMOD_NONE) {
    SDL_Event event{};event.type=SDL_KEYDOWN;event.key.keysym.sym=value;event.key.keysym.mod=modifiers;
    fixture::check(SDL_PushEvent(&event)==1,"Cannot queue SDL key");
}
void text(const char* value) {
    SDL_Event event{};event.type=SDL_TEXTINPUT;SDL_strlcpy(event.text.text,value,sizeof(event.text.text));
    fixture::check(SDL_PushEvent(&event)==1,"Cannot queue SDL text");
}
struct Scenario {
    static constexpr bool testing=true;
    int step=0;
    template<class Session> void start(Session& session) {
        const auto* driver=SDL_GetCurrentVideoDriver();
        fixture::check(driver&&*driver,"SDL native video driver was not initialized");
        std::cout<<"SDL native video driver: "<<driver<<'\n';
        session.adapter.focus(gui::WidgetKey{"entries.editor",1});
        text("First entry");key(SDLK_RETURN);text("Second entry");key(SDLK_RETURN);
    }
    template<class Session> void frame(Session& session,SDL_Window* window,const gui::Frame& frame) {
        auto& app=session.application;
        if(step==0) {
            fixture::check(fixture::widget(app.view(),"entries.list").state.records.size()==2,"SDL events lost entry input");
            app.enable_remove_feature();
            session.adapter.focus(gui::WidgetKey{"entries.list",1});key(SDLK_DOWN);
            ++step;
        } else if(step==1) {
            session.adapter.focus(gui::WidgetKey{"entries.remove",1});key(SDLK_RETURN);++step;
        } else if(step==2) {
            fixture::check(fixture::widget(app.view(),"entries.list").state.records.size()==1,"SDL shared extension failed");
            SDL_SetWindowSize(window,800,640);SDL_Event event{};event.type=SDL_WINDOWEVENT;event.window.event=SDL_WINDOWEVENT_SIZE_CHANGED;
            fixture::check(SDL_PushEvent(&event)==1,"Cannot queue resize");++step;
        } else if(step==3) {
            fixture::check(frame.width==800&&frame.height==640,"SDL resize/upload failed");
            // Align the final shared status with the full canonical scenario.
            fixture::parity(app.view());
            fixture::capture(frame.pixels->data(),frame.width,frame.height,"sdl");
            SDL_Event event{};event.type=SDL_QUIT;fixture::check(SDL_PushEvent(&event)==1,"Cannot queue close");++step;
        }
    }
};
}
int main(int argc,char** argv){return foundation::host::run_sdl<foundation::ui::Application>(argc,argv,Scenario{});}
