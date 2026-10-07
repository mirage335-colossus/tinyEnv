#include "../ui/canvas.hpp"
#include <gui/framebuffer.hpp>

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace foundation::editor;
namespace {
void require(bool condition,const char* explanation) {
    if(!condition)throw std::runtime_error(explanation);
}
gui::Snapshot snapshot(std::vector<gui::Widget> widgets) {
    gui::Snapshot view;view.client_size={1000,700};view.widgets=std::move(widgets);
    gui::validate_snapshot(view);return view;
}
std::vector<std::uint8_t> paint(gui::BitmapSource source,gui::BitmapRequest request) {
    gui::BitmapImage image(request.width,request.height,request.format);
    source.paint(request,[&](unsigned x,unsigned y,gui::PixelBlock block){image.blit(x,y,block);});
    return image.pixels();
}
const gui::Widget& surface(const gui::Snapshot& view) {
    for(const auto& w:view.widgets)if(w.spec.key.id=="canvas.surface")return w;
    throw std::runtime_error("missing canvas surface");
}
void forms() {
    Project project;
    Form form;form.id="main";form.width=640;form.height=480;
    Control button;button.id="start";button.label="Start";button.layout={30,40,100,32};button.enabled=false;
    Control group;group.id="group";group.kind="group";group.layout={10,20,220,160};
    button.parent="group";
    Control text;text.id="status";text.kind="text";text.parent="group";text.multiline=true;text.read_only=true;
    text.text="Ready\nSecond line";text.layout={30,85,120,70};text.text_limit=64;
    // A group may be declared after its child; preview must still be valid.
    form.controls={button,text,group};project.forms={form};
    Canvas canvas;CanvasOptions options;options.document="main";options.viewport={100,50,640,480};options.selected="start";
    auto view=snapshot(canvas.render(project,options));
    const auto selected=canvas.hit_test({150,110});
    // Parent groups declared later must not obscure children in design mode.
    require(selected&&selected->object=="start","child selected through later parent");
    const auto rect=*canvas.object_bounds("start");
    const auto resize=canvas.hit_test({rect.x+rect.width-2,rect.y+rect.height-2});
    require(resize&&resize->object=="start"&&resize->resize,"selected resize handle");
    require(!canvas.hit_test({99,60}),"viewport clips hits");
    const auto original=paint(surface(view).state.bitmap.source,gui::full_bitmap_request(640,480));
    options.zoom=2;options.pan={25,30};
    (void)canvas.render(project,options);
    require(canvas.view_to_model(canvas.model_to_view({48,72}))==gui::Point{48,72},"pan zoom round trip");
    require(original==paint(surface(view).state.bitmap.source,gui::full_bitmap_request(640,480)),"old bitmap owns its unchanged bytes");
    options.preview=true;options.zoom=1;options.pan={};
    view=snapshot(canvas.render(project,options));
    require(!canvas.hit_test({150,110}),"preview has no design gestures");
    bool saw_button=false;
    for(const auto& widget:view.widgets)if(widget.spec.key.id=="canvas.preview.start"){
        saw_button=widget.spec.kind==gui::Kind::button&&!widget.state.enabled&&widget.spec.parent=="canvas.preview.group";
    }
    require(saw_button,"inert standard-widget preview");
    const auto* preview_text=gui::find_widget(view,{"canvas.preview.status",1});
    require(preview_text&&preview_text->spec.text_policy.multiline&&preview_text->spec.text_policy.read_only&&
        preview_text->spec.text_policy.max_bytes==64&&preview_text->state.text==text.text,"preview preserves declared multiline text policy");
    gui::FramebufferAdapter adapter;adapter.present(view);const auto frame=adapter.frame();
    require(frame.width==1000&&frame.height==700&&frame.pixels,"real public framebuffer presentation");
}
void port_label_columns() {
    Project project;project.flows={{"main","Main"}};
    Block source;source.id="source";source.label="Source";source.x=20;source.y=30;
    source.inputs={{"sample","float",true},{"mode","int",true},{"extra","double",true}};
    source.outputs={{"out","float",true},{"phase","int",true}};
    project.blocks={source};
    Canvas canvas;CanvasOptions options;options.mode=CanvasMode::flows;options.document="main";options.viewport={20,20,950,600};
    gui::FramebufferAdapter adapter;
    options.measure_text=[&](const gui::TextMeasureRequest& request){return adapter.measure_text(request);};
    for(const double zoom:{.8,1.0,2.0}){
        options.zoom=zoom;
        const auto view=snapshot(canvas.render(project,options));
        std::vector<const gui::Widget*> inputs,outputs;
        for(const auto& widget:view.widgets)if(widget.spec.key.id.starts_with("canvas.port.")){
            const auto size=adapter.measure_text({widget.state.text,widget.state.font,gui::coordinate_limit,1,gui::TextWrap::none});
            require(size.width<=widget.state.bounds.width+.0001,"actual rendered port text fits its column");
            (widget.spec.key.id.find(".in.")!=std::string::npos?inputs:outputs).push_back(&widget);
        }
        require(inputs.size()==3&&outputs.size()==2,"asymmetric three-input two-output labels remain visible");
        for(const auto* input:inputs)for(const auto* output:outputs){
            require(!gui::has_area(gui::intersect(input->state.bounds,output->state.bounds)),"opposite port columns never overlap");
            require(output->state.bounds.x-(input->state.bounds.x+input->state.bounds.width)>=8*zoom,"visible space separates port columns");
        }
        adapter.present(view);require(adapter.frame().pixels!=nullptr,"measured asymmetric ports render on framebuffer");
    }
    project.blocks[0].inputs[0].type="custom::"+std::string(300,'x');
    options.zoom=1;
    auto view=snapshot(canvas.render(project,options));
    bool elided=false,kept_short_output=false;
    for(const auto& widget:view.widgets)if(widget.spec.key.id.starts_with("canvas.port.")){
        const auto size=adapter.measure_text({widget.state.text,widget.state.font,gui::coordinate_limit,1,gui::TextWrap::none});
        require(size.width<=widget.state.bounds.width+.0001,"elided long port types fit bounded columns");
        if(widget.spec.key.id.find(".in.sample")!=std::string::npos)
            elided=widget.state.text.ends_with("...")&&widget.state.accessible_name=="> sample : "+project.blocks[0].inputs[0].type;
        if(widget.spec.key.id.find(".out.out")!=std::string::npos)kept_short_output=widget.state.text=="out : float >";
    }
    require(elided,"long type display elides while full accessible metadata remains");
    require(kept_short_output,"long input type cannot squeeze short output label");
}
void flows() {
    Project project;project.flows={{"main","Main"},{"other","Other"}};
    Block source;source.id="source";source.label="Source";source.flow="main";source.x=40;source.y=30;
    source.outputs={{"signal","float",true},{"status","int",false}};
    Block sink;sink.id="sink";sink.label="Sink";sink.flow="main";sink.x=380;sink.y=70;
    sink.inputs={{"signal","float",true},{"control","int",false},{"extra","double",true}};
    Block hidden=source;hidden.id="hidden";hidden.flow="other";
    project.blocks={source,sink,hidden};project.edges={{"wire","source","signal","sink","signal",256,0}};
    Canvas canvas;CanvasOptions options;options.mode=CanvasMode::flows;options.document="main";options.viewport={20,20,850,550};
    const auto view=snapshot(canvas.render(project,options));
    require(!canvas.object_bounds("hidden"),"only chosen flow is rendered");
    const auto out=*canvas.port_position("source","signal",PortDirection::output);
    const auto in=*canvas.port_position("sink","signal",PortDirection::input);
    const auto hit=canvas.hit_test(out);
    require(hit&&hit->object=="source"&&hit->port=="signal"&&hit->direction==PortDirection::output,"named output port hit");
    const auto input_hit=canvas.hit_test(in);
    require(input_hit&&input_hit->direction==PortDirection::input,"named input port hit");
    for(const auto& widget:view.widgets)if(widget.spec.key.id.starts_with("canvas.port.")) {
        const auto area=widget.state.bounds;
        const auto label_hit=canvas.hit_test({area.x+area.width*.5,area.y+area.height*.5});
        require(label_hit&&label_hit->direction.has_value(),"port text is a wiring target");
        require(!widget.spec.pointer_input,"port labels leave pointer capture on the stable canvas surface");
    }
    require(canvas.port_position("sink","extra",PortDirection::input).has_value(),"arbitrary MIMO extra input");
    const auto wire=canvas.hit_test({(out.x+in.x)*.5,(out.y+in.y)*.5});
    require(wire&&wire->edge&&wire->object=="wire","wire selection");
    bool required=false;
    for(const auto& w:view.widgets)if(w.spec.key.id.find(".in.extra")!=std::string::npos)
        required=w.state.font.tone==gui::Tone::error;
    require(required,"unconnected required port diagnostic");
    options.pending_port=Hit{"sink","extra",PortDirection::input};
    const auto pending=snapshot(canvas.render(project,options));
    bool accented=false;
    for(const auto& w:pending.widgets)if(w.spec.key.id.find(".in.extra")!=std::string::npos)
        accented=w.state.font.tone==gui::Tone::accent;
    require(accented,"pending required port is visibly selected");
    gui::FramebufferAdapter adapter;adapter.present(view);
    require(adapter.frame().pixels!=nullptr,"flow raster and labels present together");
    // Partial repaint uses the original sample mapping, independent of damage.
    const auto bitmap=surface(view).state.bitmap.source;
    const auto full=paint(bitmap,gui::full_bitmap_request(170,110));
    const auto part=paint(bitmap,{170,110,{40,30,20,10},gui::PixelFormat::rgb24});
    for(unsigned y=30;y<40;++y)for(unsigned x=40;x<60;++x)for(unsigned c=0;c<3;++c)
        require(part[(std::size_t(y)*170+x)*3+c]==full[(std::size_t(y)*170+x)*3+c],"damage-independent bitmap coordinates");
    for(const auto format:{gui::PixelFormat::gray8,gui::PixelFormat::mono1})
        require(!paint(bitmap,gui::full_bitmap_request(170,110,format)).empty(),"non-RGB surface format");
}
void bounds() {
    Project project;Canvas canvas;CanvasOptions options;options.viewport={0,0,900000,900000};
    auto view=canvas.render(project,options);
    require(!paint(view.at(1).state.bitmap.source,gui::full_bitmap_request(32,32)).empty(),"huge logical viewport has bounded raster");
    bool caught=false;
    try{(void)paint(view.at(1).state.bitmap.source,gui::full_bitmap_request(32769,1));}
    catch(const std::length_error&){caught=true;}
    require(caught,"sample grid limit");
    options.zoom=0;caught=false;
    try{(void)canvas.render(project,options);}catch(const std::invalid_argument&){caught=true;}
    require(caught,"invalid zoom rejected");
    options.zoom=1;options.pan.x=std::numeric_limits<double>::quiet_NaN();caught=false;
    try{(void)canvas.render(project,options);}catch(const std::invalid_argument&){caught=true;}
    require(caught,"invalid pan rejected");
}
}
int main() {
    try{forms();flows();port_label_columns();bounds();std::cout<<"editor canvas: ok\n";return EXIT_SUCCESS;}
    catch(const std::exception& failure){std::cerr<<failure.what()<<'\n';return EXIT_FAILURE;}
}
