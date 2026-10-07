#include "canvas.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <map>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace foundation::editor {
namespace {
using Color = std::array<std::uint8_t, 3>;
constexpr Color background{247, 249, 252}, grid{228, 233, 240};
constexpr Color ink{97, 114, 139}, paper{255, 255, 255}, accent{40, 93, 164};
constexpr Color selection{214, 230, 250}, muted{235, 238, 243}, error{175, 46, 57};
constexpr std::size_t max_pixels = 4 * 1024 * 1024;
constexpr double port_row = 25, block_header = 34;

bool finite(gui::Point p) { return std::isfinite(p.x) && std::isfinite(p.y); }
double distance(gui::Point a, gui::Point b) { return std::hypot(a.x - b.x, a.y - b.y); }
double line_distance(gui::Point point, gui::Point a, gui::Point b) {
    const auto dx = b.x-a.x, dy = b.y-a.y;
    const auto denominator = dx*dx+dy*dy;
    const auto fraction = denominator > 0 ? std::clamp(((point.x-a.x)*dx+(point.y-a.y)*dy)/denominator, 0.0, 1.0) : 0;
    return distance(point, {a.x+fraction*dx, a.y+fraction*dy});
}

// Raster storage is independent of backing scale and capped at 12 MiB. All
// drawing clips before iteration; a far-offscreen coordinate cannot cause an
// unbounded line walk. Backend sample grids are generated one row at a time.
class Raster {
public:
    explicit Raster(gui::Rect viewport) : viewport_(viewport) {
        double scale = std::min(1.0, 2048.0 / std::max({1.0, viewport.width, viewport.height}));
        if (viewport.width*viewport.height*scale*scale > max_pixels)
            scale = std::sqrt(double(max_pixels)/(viewport.width*viewport.height));
        width_ = std::max(1u, static_cast<unsigned>(std::ceil(viewport.width*scale)));
        height_ = std::max(1u, static_cast<unsigned>(std::ceil(viewport.height*scale)));
        pixels_.resize(std::size_t(width_)*height_*3);
        for (std::size_t i=0; i<pixels_.size(); i+=3) std::copy(background.begin(), background.end(), pixels_.begin()+i);
    }
    void pixel(int x, int y, Color color) {
        if(x<0||y<0||x>=int(width_)||y>=int(height_)) return;
        const auto i = (std::size_t(y)*width_+unsigned(x))*3;
        std::copy(color.begin(), color.end(), pixels_.begin()+i);
    }
    gui::Point local(gui::Point p) const {
        return {(p.x-viewport_.x)*width_/std::max(1.0,viewport_.width),
                (p.y-viewport_.y)*height_/std::max(1.0,viewport_.height)};
    }
    void fill(gui::Rect area, Color color) {
        area=gui::intersect(area,viewport_);
        if(!gui::has_area(area)) return;
        const auto a=local({area.x,area.y}), b=local({area.x+area.width,area.y+area.height});
        const int left=std::max(0,int(std::floor(a.x))), right=std::min(int(width_),int(std::ceil(b.x)));
        const int top=std::max(0,int(std::floor(a.y))), bottom=std::min(int(height_),int(std::ceil(b.y)));
        for(int y=top;y<bottom;++y)for(int x=left;x<right;++x)pixel(x,y,color);
    }
    void line(gui::Point a, gui::Point b, Color color, int thickness=1) {
        a=local(a);b=local(b);
        // Liang-Barsky clips the continuous segment to the raster bounds.
        const double dx=b.x-a.x,dy=b.y-a.y;
        double first=0,last=1;
        const auto clip=[&](double p,double q) {
            if(p==0)return q>=0;
            const double t=q/p;
            if(p<0){if(t>last)return false;first=std::max(first,t);}
            else{if(t<first)return false;last=std::min(last,t);}
            return true;
        };
        if(!clip(-dx,a.x)||!clip(dx,width_-1-a.x)||!clip(-dy,a.y)||!clip(dy,height_-1-a.y))return;
        int x=int(std::round(a.x+first*dx)),y=int(std::round(a.y+first*dy));
        const int x1=int(std::round(a.x+last*dx)),y1=int(std::round(a.y+last*dy));
        const int sx=x<x1?1:-1,sy=y<y1?1:-1;
        const int ax=std::abs(x1-x),ay=-std::abs(y1-y);
        int residual=ax+ay;
        for(;;){
            for(int yy=0;yy<thickness;++yy)for(int xx=0;xx<thickness;++xx)pixel(x+xx,y+yy,color);
            if(x==x1&&y==y1)break;
            const int twice=2*residual;
            if(twice>=ay){residual+=ay;x+=sx;}
            if(twice<=ax){residual+=ax;y+=sy;}
        }
    }
    void frame(gui::Rect area,Color color,int thickness=1) {
        line({area.x,area.y},{area.x+area.width,area.y},color,thickness);
        line({area.x+area.width,area.y},{area.x+area.width,area.y+area.height},color,thickness);
        line({area.x+area.width,area.y+area.height},{area.x,area.y+area.height},color,thickness);
        line({area.x,area.y+area.height},{area.x,area.y},color,thickness);
    }
    gui::BitmapSource source() && {
        const auto width=width_,height=height_;
        auto bytes=std::make_shared<const std::vector<std::uint8_t>>(std::move(pixels_));
        return gui::BitmapSource([bytes,width,height](const gui::BitmapRequest& request,const gui::BitmapSink& sink){
            // This bounds work and scratch allocation even for malicious or
            // erroneous public-surface consumers. Normal native scales fit.
            if(request.width>32768||request.height>32768||std::size_t(request.width)*request.height>128*1024*1024)
                throw std::length_error("Editor canvas sample grid exceeds limits");
            std::vector<std::uint8_t> row(gui::pixel_row_bytes(request.damage.width,request.format));
            for(unsigned y=0;y<request.damage.height;++y){
                std::fill(row.begin(),row.end(),0);
                const auto sy=std::min(height-1,static_cast<unsigned>((double(request.damage.y+y)+.5)*height/request.height));
                for(unsigned x=0;x<request.damage.width;++x){
                    const auto sx=std::min(width-1,static_cast<unsigned>((double(request.damage.x+x)+.5)*width/request.width));
                    const auto i=(std::size_t(sy)*width+sx)*3;
                    if(request.format==gui::PixelFormat::rgb24)
                        std::copy_n(bytes->data()+i,3,row.data()+std::size_t(x)*3);
                    else{
                        const auto gray=std::uint8_t((77u*(*bytes)[i]+150u*(*bytes)[i+1]+29u*(*bytes)[i+2]+128u)/256u);
                        if(request.format==gui::PixelFormat::gray8)row[x]=gray;
                        else if(gray>=128)row[x/8]|=std::uint8_t(0x80u>>(x%8));
                    }
                }
                sink(request.damage.x,request.damage.y+y,{request.damage.width,1,row.size(),request.format,row});
            }
        });
    }
private:
    gui::Rect viewport_;
    unsigned width_=1,height_=1;
    std::vector<std::uint8_t> pixels_;
};

gui::Kind kind(std::string_view name) {
    if(name=="group")return gui::Kind::group;
    if(name=="label")return gui::Kind::label;
    if(name=="toggle")return gui::Kind::toggle;
    if(name=="choice")return gui::Kind::choice;
    if(name=="text")return gui::Kind::text;
    if(name=="list")return gui::Kind::list;
    if(name=="bitmap")return gui::Kind::bitmap;
    if(name=="menu")return gui::Kind::menu;
    return gui::Kind::button;
}
gui::Widget label(std::string id,std::string text,gui::Rect bounds,gui::Rect clip,double zoom,bool bold=false,gui::Tone tone=gui::Tone::normal) {
    gui::Widget w;
    w.spec.key={std::move(id),1};w.spec.kind=gui::Kind::label;
    // The stable bitmap owns gestures. Moving a label must not revoke a drag's
    // captured target, and labels retain their normal accessible text role.
    w.spec.parent="canvas.viewport";
    w.state.bounds=gui::intersect(bounds,clip);w.state.text=std::move(text);
    w.state.accessible_name=w.state.text;
    w.state.font={std::clamp(13.0*zoom,8.0,28.0),bold,tone};
    return w;
}
std::string short_text(std::string text,std::size_t bytes=180) {
    if(text.size()<=bytes)return text;
    while(bytes>0&&(static_cast<unsigned char>(text[bytes])&0xc0)==0x80)--bytes;
    text.resize(bytes);text+="...";return text;
}
}

gui::Point Canvas::model_to_view(gui::Point point) const {
    return {options_.viewport.x+(point.x-options_.pan.x)*options_.zoom,
            options_.viewport.y+(point.y-options_.pan.y)*options_.zoom};
}
gui::Point Canvas::view_to_model(gui::Point point) const {
    return {(point.x-options_.viewport.x)/options_.zoom+options_.pan.x,
            (point.y-options_.viewport.y)/options_.zoom+options_.pan.y};
}
std::optional<gui::Rect> Canvas::object_bounds(std::string_view id) const {
    for(const auto& object:objects_)if(object.id==id)return object.area;
    return {};
}
std::optional<gui::Point> Canvas::port_position(std::string_view block,std::string_view port,PortDirection direction) const {
    for(const auto& endpoint:endpoints_)
        if(endpoint.hit.object==block&&endpoint.hit.port==port&&endpoint.hit.direction==direction)return endpoint.point;
    return {};
}
std::optional<Hit> Canvas::hit_test(gui::Point point) const {
    if(options_.preview||!finite(point)||!gui::contains(options_.viewport,point))return {};
    // Ports take precedence over their parent block and nearby wires.
    for(auto it=endpoints_.rbegin();it!=endpoints_.rend();++it)
        if(distance(point,it->point)<=std::max(7.0,6.0*options_.zoom)||gui::contains(it->label,point))return it->hit;
    for(auto it=objects_.rbegin();it!=objects_.rend();++it){
        if(it->resizable&&it->id==options_.selected){
            const auto r=it->area;
            if(gui::contains({r.x+r.width-9,r.y+r.height-9,13,13},point))return Hit{it->id,{}, {},true,false};
        }
    }
    for(auto it=objects_.rbegin();it!=objects_.rend();++it)
        if(!it->group&&gui::contains(it->area,point))return Hit{it->id,{}, {},false,false};
    // Group declaration order is not a stacking order. A containing group
    // cannot steal the click from a child declared before that group.
    const Object* group=nullptr;
    for(auto it=objects_.rbegin();it!=objects_.rend();++it)
        if(it->group&&gui::contains(it->area,point)&&(!group||it->area.width*it->area.height<group->area.width*group->area.height))group=&*it;
    if(group)return Hit{group->id,{}, {},false,false};
    for(auto it=wires_.rbegin();it!=wires_.rend();++it)
        for(std::size_t i=1;i<it->points.size();++i)
            if(line_distance(point,it->points[i-1],it->points[i])<=5)return Hit{it->id,{}, {},false,true};
    return {};
}

std::vector<gui::Widget> Canvas::render(const Project& project,const CanvasOptions& options) {
    if(!gui::valid_rect(options.viewport)||!std::isfinite(options.zoom)||options.zoom<.2||options.zoom>4||!finite(options.pan)||
       std::abs(options.pan.x)>gui::coordinate_limit||std::abs(options.pan.y)>gui::coordinate_limit)
        throw std::invalid_argument("Invalid editor canvas view");
    options_=options;objects_.clear();endpoints_.clear();wires_.clear();
    std::vector<gui::Widget> result,labels;
    if(!gui::has_area(options_.viewport))return result;
    Raster raster(options_.viewport);
    const auto transform=[&](gui::Rect area){
        if(!finite({area.x,area.y})||!std::isfinite(area.width)||!std::isfinite(area.height)||area.width<0||area.height<0||
           std::abs(area.x)>gui::coordinate_limit||std::abs(area.y)>gui::coordinate_limit||area.width>gui::coordinate_limit||area.height>gui::coordinate_limit)
            throw std::invalid_argument("Invalid editor canvas model geometry");
        const auto p=model_to_view({area.x,area.y});return gui::Rect{p.x,p.y,area.width*options_.zoom,area.height*options_.zoom};
    };
    const auto measure_label=[&](const std::string& text,bool bold=false){
        const gui::Font font{std::clamp(13.0*options_.zoom,8.0,28.0),bold};
        if(options_.measure_text){
            const auto size=options_.measure_text({text,font,gui::coordinate_limit,1,gui::TextWrap::none});
            if(!std::isfinite(size.width)||!std::isfinite(size.height)||size.width<0||size.height<0)
                throw std::invalid_argument("Invalid editor canvas text measurement");
            return size.width;
        }
        std::size_t characters=0;
        for(const unsigned char c:text)if((c&0xc0)!=0x80)++characters;
        return double(characters)*font.size*(bold?.9:.8);
    };
    const auto fit_label=[&](const std::string& value,double width,bool bold){
        auto text=short_text(value);
        if(measure_label(text,bold)<=width)return text;
        if(measure_label("...",bold)>width)return std::string{};
        // Prefix boundaries retain exact UTF-8 characters. Only display text is
        // elided; the full port identity/type remains in its accessible name.
        std::vector<std::size_t> boundaries{0};
        for(std::size_t i=0;i<text.size();++i)
            if(i+1==text.size()||(static_cast<unsigned char>(text[i+1])&0xc0)!=0x80)boundaries.push_back(i+1);
        std::size_t first=0,last=boundaries.size();
        while(first+1<last){
            const auto middle=first+(last-first)/2;
            if(measure_label(text.substr(0,boundaries[middle])+"...",bold)<=width)first=middle;
            else last=middle;
        }
        return text.substr(0,boundaries[first])+"...";
    };
    const auto add_label=[&](std::string id,std::string text,gui::Rect area,bool bold=false,gui::Tone tone=gui::Tone::normal){
        if(gui::has_area(gui::intersect(area,options_.viewport))){
            auto widget=label(std::move(id),fit_label(text,area.width,bold),area,options_.viewport,options_.zoom,bold,tone);
            widget.state.accessible_name=std::move(text);labels.push_back(std::move(widget));
        }
    };
    // Keep dot spacing readable at every supported zoom; pan never changes the
    // model grid origin, and dimensions cannot make this loop exceed 1M dots.
    double step=20*options_.zoom;
    while(step<12)step*=2;
    const auto origin=model_to_view({0,0});
    double first_x=options_.viewport.x+std::fmod(origin.x-options_.viewport.x,step);
    double first_y=options_.viewport.y+std::fmod(origin.y-options_.viewport.y,step);
    if(first_x<options_.viewport.x)first_x+=step;
    if(first_y<options_.viewport.y)first_y+=step;
    // Extremely large logical viewports are supported at a coarser dot grid.
    while((options_.viewport.width/step)*(options_.viewport.height/step)>100000)step*=2;
    for(double y=first_y;y<options_.viewport.y+options_.viewport.height;y+=step)
        for(double x=first_x;x<options_.viewport.x+options_.viewport.width;x+=step){
            const auto p=raster.local({x,y});raster.pixel(int(p.x),int(p.y),grid);
        }

    if(options_.mode==CanvasMode::forms){
        const Form* form=nullptr;
        for(const auto& candidate:project.forms)if(candidate.id==options_.document){form=&candidate;break;}
        if(form){
            const auto frame=transform({0,0,form->width,form->height});
            raster.fill(frame,paper);raster.frame(frame,ink);
            for(const auto& control:form->controls){
                const auto area=transform({control.layout.x,control.layout.y,control.layout.width,control.layout.height});
                objects_.push_back({control.id,area,true,control.kind=="group"});
                if(options_.preview)continue;
                const bool selected=control.id==options_.selected;
                if(control.kind!="group")raster.fill(area,selected?selection:(!control.enabled||!control.visible?muted:paper));
                raster.frame(area,selected?accent:ink,selected?2:1);
                std::string text=control.label.empty()?control.id:control.label;
                if(control.kind=="toggle")text=(control.checked?"[x] ":"[ ] ")+text;
                if(control.kind=="choice"||control.kind=="menu")text+="  v";
                if(control.kind=="text")text=control.text.empty()?text:control.text;
                if(control.kind=="list")text="List: "+text;
                if(control.kind=="bitmap"){
                    text="Bitmap: "+text;
                    raster.line({area.x+4,area.y+4},{area.x+area.width-4,area.y+area.height-4},grid);
                    raster.line({area.x+area.width-4,area.y+4},{area.x+4,area.y+area.height-4},grid);
                }
                const auto text_area=gui::Rect{area.x+5,area.y+3,std::max(0.0,area.width-10),std::min(std::max(0.0,area.height-6),24.0*options_.zoom)};
                add_label("canvas.control."+control.id,std::move(text),text_area,selected,(!control.enabled||!control.visible)?gui::Tone::muted:gui::Tone::normal);
                if(selected)raster.fill({area.x+area.width-6,area.y+area.height-6,8,8},accent);
            }
        }
    }else{
        using PortKey=std::tuple<std::string,std::string,PortDirection>;
        struct PortState { gui::Point point; std::string type; bool connected=false,compatible=true; };
        struct BlockLayout { gui::Rect area; double input_width=0,output_width=0,padding=0,gap=0; };
        std::map<PortKey,PortState> ports_by_id;
        std::map<std::string,BlockLayout,std::less<>> block_layouts;
        // All declared ports participate, including offscreen ones and ports
        // without an edge. Arbitrary arity needs no fixed toolkit port limit.
        for(const auto& block:project.blocks){
            if(block.flow!=options_.document)continue;
            const auto count=std::max(block.inputs.size(),block.outputs.size());
            double input_width=0,output_width=0;
            for(const auto& port:block.inputs)input_width=std::max(input_width,measure_label(short_text("> "+port.id+" : "+port.type)));
            for(const auto& port:block.outputs)output_width=std::max(output_width,measure_label(short_text(port.id+" : "+port.type+" >")));
            const double padding=std::max(6.0,12.0*options_.zoom);
            const double gap=input_width>0&&output_width>0?std::max(8.0,16.0*options_.zoom):0;
            const double natural_width=std::max(input_width+output_width+2*padding+gap,
                measure_label(short_text(block.label.empty()?block.id:block.label),true)+2*padding);
            const double width=std::clamp(natural_width/options_.zoom,220.0,640.0);
            const auto area=transform({block.x,block.y,width,block_header+std::max<std::size_t>(count,1)*port_row+8});
            objects_.push_back({block.id,area,false});
            const auto column_space=std::max(0.0,area.width-2*padding-gap);
            const auto total=input_width+output_width;
            double input_allocation=total>0?column_space*input_width/total:0;
            if(total>column_space){
                // A very long input type must not squeeze a short output label.
                // Keep the smaller column readable, then elide the larger one.
                if(input_width<=column_space/2)input_allocation=input_width;
                else if(output_width<=column_space/2)input_allocation=column_space-output_width;
                else input_allocation=column_space/2;
            }
            block_layouts.emplace(block.id,BlockLayout{area,input_allocation,
                total>0?column_space-input_allocation:0,padding,gap});
            for(const auto direction:{PortDirection::input,PortDirection::output}){
                const auto& ports=direction==PortDirection::input?block.inputs:block.outputs;
                for(std::size_t i=0;i<ports.size();++i){
                    const auto point=model_to_view({block.x+(direction==PortDirection::input?0:width),block.y+block_header+port_row*(i+.5)});
                    const auto& layout=block_layouts.at(block.id);
                    const auto label_area=gui::Rect{direction==PortDirection::input?area.x+layout.padding:area.x+layout.padding+layout.input_width+layout.gap,
                        point.y-10*options_.zoom,direction==PortDirection::input?layout.input_width:layout.output_width,20*options_.zoom};
                    endpoints_.push_back({Hit{block.id,ports[i].id,direction},point,gui::intersect(label_area,options_.viewport)});
                    ports_by_id.emplace(PortKey{block.id,ports[i].id,direction},PortState{point,ports[i].type});
                }
            }
        }
        // Wires precede blocks, so intersecting wires never cover block text.
        for(const auto& edge:project.edges){
            const auto from_state=ports_by_id.find({edge.from_block,edge.from_port,PortDirection::output});
            const auto to_state=ports_by_id.find({edge.to_block,edge.to_port,PortDirection::input});
            if(from_state==ports_by_id.end()||to_state==ports_by_id.end())continue;
            from_state->second.connected=true;to_state->second.connected=true;
            const bool compatible=from_state->second.type==to_state->second.type;
            from_state->second.compatible=from_state->second.compatible&&compatible;
            to_state->second.compatible=to_state->second.compatible&&compatible;
            const auto from=from_state->second.point,to=to_state->second.point;
            const double stub=std::max(14.0,24*options_.zoom);
            const double mid=(from.x+to.x)*.5;
            std::vector<gui::Point> points;
            if(to.x>=from.x+stub*2)points={from,{mid,from.y},{mid,to.y},to};
            else{
                const double route=std::max(from.y,to.y)+stub;
                points={from,{from.x+stub,from.y},{from.x+stub,route},{to.x-stub,route},{to.x-stub,to.y},to};
            }
            const bool selected=edge.id==options_.selected;
            const auto wire_color=!compatible?error:selected?accent:ink;
            for(std::size_t i=1;i<points.size();++i)raster.line(points[i-1],points[i],wire_color,selected?2:1);
            const auto end=points.back();
            raster.line({end.x-6,end.y-4},end,wire_color);
            raster.line({end.x-6,end.y+4},end,wire_color);
            wires_.push_back({edge.id,std::move(points)});
        }
        for(const auto& block:project.blocks){
            if(block.flow!=options_.document)continue;
            const auto& layout=block_layouts.at(block.id);
            const auto area=layout.area;
            const bool selected=block.id==options_.selected;
            raster.fill(area,selected?selection:paper);raster.frame(area,selected?accent:ink,selected?2:1);
            const double header=block_header*options_.zoom;
            raster.line({area.x,area.y+header},{area.x+area.width,area.y+header},grid);
            add_label("canvas.block."+block.id,block.label.empty()?block.id:block.label,{area.x+8,area.y+3,area.width-16,header-6},true);
            for(const auto direction:{PortDirection::input,PortDirection::output}){
                const auto& ports=direction==PortDirection::input?block.inputs:block.outputs;
                for(const auto& port:ports){
                    const auto& port_state=ports_by_id.at({block.id,port.id,direction});
                    const auto point=port_state.point;
                    const bool pending=options_.pending_port&&options_.pending_port->object==block.id&&options_.pending_port->port==port.id&&options_.pending_port->direction==direction;
                    const auto color=pending?accent:(!port_state.compatible||(!port_state.connected&&port.required))?error:ink;
                    raster.fill({point.x-4,point.y-4,8,8},color);
                    if(pending)raster.frame({point.x-7,point.y-7,14,14},accent,2);
                    const auto text_area=gui::Rect{direction==PortDirection::input?area.x+layout.padding:area.x+layout.padding+layout.input_width+layout.gap,
                        point.y-10*options_.zoom,direction==PortDirection::input?layout.input_width:layout.output_width,20*options_.zoom};
                    add_label("canvas.port."+std::to_string(block.id.size())+":"+block.id+"."+(direction==PortDirection::input?"in.":"out.")+port.id,
                              direction==PortDirection::input?"> "+port.id+" : "+port.type:port.id+" : "+port.type+" >",text_area,false,
                              color==error?gui::Tone::error:pending?gui::Tone::accent:gui::Tone::normal);
                }
            }
        }
    }
    gui::Widget viewport;
    viewport.spec.key={"canvas.viewport",1};viewport.spec.kind=gui::Kind::group;
    viewport.state.bounds=options_.viewport;viewport.state.content_clip=gui::Rect{0,0,options_.viewport.width,options_.viewport.height};
    result.push_back(std::move(viewport));
    gui::Widget surface;
    surface.spec.key={"canvas.surface",1};surface.spec.kind=gui::Kind::bitmap;surface.spec.parent="canvas.viewport";surface.spec.pointer_input=!options_.preview;
    surface.state.bounds=options_.viewport;surface.state.accessible_name=options_.mode==CanvasMode::forms?"Form layout canvas":"Signal processing canvas";
    surface.state.bitmap={"editor.canvas",++revision_,std::move(raster).source()};
    result.push_back(std::move(surface));
    if(options_.preview&&options_.mode==CanvasMode::forms){
        for(const auto& form:project.forms)if(form.id==options_.document){
            // Public parents must precede their descendants. Absolute model
            // coordinates are retained; groups provide clipping only.
            std::vector<const Control*> pending;
            for(const auto& control:form.controls)pending.push_back(&control);
            std::vector<std::string> emitted;
            while(!pending.empty()){
                bool progress=false;
                for(auto it=pending.begin();it!=pending.end();){
                    const auto& control=**it;
                    if(!control.parent.empty()&&std::find(emitted.begin(),emitted.end(),control.parent)==emitted.end()){++it;continue;}
                    gui::Widget w;w.spec.key={"canvas.preview."+control.id,1};w.spec.kind=kind(control.kind);
                    w.spec.parent=control.parent.empty()?"canvas.viewport":"canvas.preview."+control.parent;
                    w.state.bounds=transform({control.layout.x,control.layout.y,control.layout.width,control.layout.height});
                    if(!gui::valid_rect(w.state.bounds))w.state.bounds=gui::intersect(w.state.bounds,options_.viewport);
                    w.state.label=control.label;w.state.text=control.text;
                    if(w.spec.kind==gui::Kind::label)w.state.text=control.label;
                    w.state.accessible_name=control.label.empty()?control.id:control.label;
                    w.state.enabled=false;w.state.visible=control.visible;w.state.checked=control.checked;
                    w.state.font.size=std::clamp(13.0*options_.zoom,8.0,28.0);
                    if(w.spec.kind==gui::Kind::text){w.spec.text_policy.multiline=control.multiline;w.spec.text_policy.read_only=true;w.spec.text_policy.max_bytes=control.text_limit;}
                    if(w.spec.kind==gui::Kind::choice||w.spec.kind==gui::Kind::menu)
                        for(const auto& option:control.options)w.state.options.push_back({option.id,option.label,option.value,option.enabled});
                    if(w.spec.kind==gui::Kind::choice&&!w.state.options.empty())w.state.selected=w.state.options.front().id;
                    if(w.spec.kind==gui::Kind::bitmap)w.state.bitmap={"editor.preview."+control.id,1,gui::solid_bitmap(235,238,243)};
                    result.push_back(std::move(w));emitted.push_back(control.id);it=pending.erase(it);progress=true;
                }
                if(!progress)break; // Invalid/cyclic parents are diagnosed by the model.
            }
        }
    }else result.insert(result.end(),std::make_move_iterator(labels.begin()),std::make_move_iterator(labels.end()));
    return result;
}
} // namespace foundation::editor
