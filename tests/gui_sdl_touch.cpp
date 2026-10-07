#include "sdl_runner.hpp"
#include <stdexcept>

namespace {
void check(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
struct Session {
    std::vector<gui::Event> events;
    gui::FramebufferAdapter adapter{[this](const gui::Event& value){events.push_back(value);}};
    Session() {
        gui::Snapshot view;view.client_size={200,100};view.display_scale=2;
        gui::Widget button;button.spec.key={"button",1};button.spec.kind=gui::Kind::button;button.state.bounds={0,0,60,40};
        gui::Widget raw;raw.spec.key={"raw",1};raw.spec.pointer_input=true;raw.state.bounds={80,0,60,40};
        view.widgets={button,raw};adapter.present(view);
    }
    void tick() {}
};
}
int main(int, char**) {try {
    // A nonempty SDL queue yields to presentation after one bounded batch.
    check(SDL_Init(SDL_INIT_EVENTS)==0,"SDL event subsystem unavailable");
    for(unsigned i=0;i<512;++i) {SDL_Event queued{};queued.type=SDL_USEREVENT;check(SDL_PushEvent(&queued)==1,"Queue injection failed");}
    foundation::host::EventBudget budget;SDL_Event queued{};unsigned consumed=0;
    while(budget.take()&&SDL_PollEvent(&queued))++consumed;
    check(consumed<=127&&SDL_HasEvent(SDL_USEREVENT),"Input flood consumed presentation opportunity");
    SDL_Quit();
    Session session;foundation::host::FramebufferTouch pointer;
    auto finger=[&](Uint32 type,SDL_FingerID id,float x,float y) {
        SDL_Event input{};input.type=type;input.tfinger.touchId=17;input.tfinger.fingerId=id;input.tfinger.x=x;input.tfinger.y=y;
        event(session,nullptr,nullptr,pointer,input);
    };
    finger(SDL_FINGERDOWN,31,.1f,.2f);finger(SDL_FINGERDOWN,32,.1f,.2f);
    SDL_Event synthetic{};synthetic.type=SDL_MOUSEBUTTONDOWN;synthetic.button.which=SDL_TOUCH_MOUSEID;
    synthetic.button.button=SDL_BUTTON_LEFT;synthetic.button.x=20;synthetic.button.y=20;
    event(session,nullptr,nullptr,pointer,synthetic);
    finger(SDL_FINGERUP,32,.1f,.2f);check(session.events.empty(),"Extra finger or synthetic mouse activated");
    finger(SDL_FINGERUP,31,.1f,.2f);check(session.events.size()==1,"SDL touch release failed logical scale mapping");
    finger(SDL_FINGERDOWN,31,.1f,.2f);
    SDL_Event lost{};lost.type=SDL_WINDOWEVENT;lost.window.event=SDL_WINDOWEVENT_FOCUS_LOST;
    event(session,nullptr,nullptr,pointer,lost);finger(SDL_FINGERUP,31,.1f,.2f);
    check(session.events.size()==1,"SDL focus loss activated touch");
    finger(SDL_FINGERDOWN,31,.5f,.2f);finger(SDL_FINGERMOTION,31,1.4f,.2f);finger(SDL_FINGERUP,31,1.5f,.2f);
    check(session.events.size()==4,"SDL raw capture lost outside motion/release");
    const auto input=std::get<gui::PointerInput>(std::get<gui::WidgetEvent>(session.events.back()).input);
    check(input.kind==gui::PointerKind::release&&input.position.x==300,"SDL normalized coordinate conversion differs");
    std::cout<<"SDL touch translation, extra contact rejection and focus cancellation passed\n";return 0;
}catch(const std::exception& failure){std::cerr<<failure.what()<<'\n';return 1;}}
