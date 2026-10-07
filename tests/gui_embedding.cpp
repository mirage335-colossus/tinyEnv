#include "host/framebuffer.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
// An application satisfying the normal composition contract; the fake device
// knows only coordinates/frames and cannot invoke the application action.
struct App {
    gui::Adapter& adapter;gui::Snapshot view;unsigned activations=0;
    explicit App(gui::Adapter& target):adapter(target) {
        view.client_size={80,48};gui::Widget widget;widget.spec.key={"action",1};widget.spec.kind=gui::Kind::button;
        widget.state.bounds={8,8,48,28};widget.state.label="Tap";view.widgets.push_back(widget);adapter.present(view);
    }
    void handle(gui::Event event) {
        if(const auto* w=std::get_if<gui::WidgetEvent>(&event);w&&std::holds_alternative<gui::Activate>(w->input)) {
            ++activations;view.widgets[0].state.label="Done";adapter.present(view);
        } else if(const auto* size=std::get_if<gui::ResizeEvent>(&event)) {view.client_size=size->client_size;view.display_scale=size->display_scale;adapter.present(view);}
    }
    void tick() {}void shutdown() {}void retry_presentation() {adapter.present(view);}
    std::optional<gui::ServiceRequest> next_service(){return std::nullopt;}
    bool complete_service(gui::ServiceResult){return false;}
    void qualify(const std::function<void()>& present){present();}
};
struct Display {
    std::vector<gui::Frame> frames;bool fail=false;
    void present(const gui::Frame& frame) {if(fail)throw std::runtime_error("display unavailable");frames.push_back(frame);}
};
}
void surface_formats() {
    using namespace foundation::host;
    gui::Frame frame{2,2,6,1,0,{1,0,1,2},std::make_shared<const std::vector<std::uint8_t>>(
        std::vector<std::uint8_t>{1,2,3,255,128,0,4,5,6,0,255,255})};
    std::vector<unsigned char> output(24,42);
    copy_frame(frame,{output,2,2,12,PixelFormat::bgra8888});
    check(output[0]==42&&output[4]==0&&output[5]==128&&output[6]==255&&output[7]==255&&
          output[8]==42&&output[16]==255&&output[17]==255&&output[18]==0,"BGRA damage or stride copy differs");
    std::fill(output.begin(),output.end(),42);
    copy_frame(frame,{output,2,2,12,PixelFormat::rgb565le});
    check(output[0]==42&&output[2]==0&&output[3]==252&&output[14]==255&&output[15]==7,
          "RGB565 byte order or channel reduction differs");
    auto before=output;frame.damage={2,0,1,1};bool rejected=false;
    try {copy_frame(frame,{output,2,2,12,PixelFormat::rgba8888});}catch(const std::invalid_argument&){rejected=true;}
    check(rejected&&output==before,"Invalid damage wrote destination before validation");
    frame.damage={0,0,2,2};rejected=false;
    try {copy_frame(frame,{output,2,2,3,PixelFormat::rgb24});}catch(const std::invalid_argument&){rejected=true;}
    check(rejected&&output==before,"Invalid stride wrote destination");
    copy_frame(frame,{output,2,2,12,PixelFormat::rgba8888});
    check(output[0]==1&&output[1]==2&&output[2]==3&&output[3]==255,"RGBA channels differ");
}
int main() {try {
    surface_formats();
    foundation::host::FramebufferHost<App> host;Display display;
    using C=foundation::host::Contact;using P=foundation::host::ContactPhase;const C finger{C::Source::touch,0,1};
    check(host.present(display)&&display.frames.size()==1,"First frame missing");
    const auto first=display.frames.front();check(!host.present(display),"Unchanged frame re-presented");
    host.contact(finger,P::press,{20,20});check(host.application().activations==0,"Embedding bypassed release policy");
    host.contact(finger,P::release,{20,20});check(host.application().activations==1,"Touch did not reach application");
    display.fail=true;try{host.present(display);}catch(const std::runtime_error&){}display.fail=false;
    check(host.present(display)&&display.frames.size()==2,"Failed presentation consumed frame revision");
    check(first.pixels&&first.width==80&&first.height==48,"Retained prior frame changed");
    host.contact(finger,P::press,{20,20});host.resize({100,60},2);host.contact(finger,P::release,{20,20});
    check(host.application().activations==1,"Resize kept stale touch capture");
    check(host.present(display)&&display.frames.back().width==200&&display.frames.back().height==120,"Logical/device scale mismatch");
    std::cout<<"Embedded fake touch/display driver passed\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
