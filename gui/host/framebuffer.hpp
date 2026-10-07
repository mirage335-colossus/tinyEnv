#pragma once
#include "contract.hpp"
#include "bezel.hpp"
#include "framebuffer_touch.hpp"
#include "framebuffer_surface.hpp"
#include <gui/framebuffer.hpp>

namespace foundation::host {
// A board/display driver receives immutable RGB24 frames and damage metadata.
// It may retain a frame while DMA or another asynchronous consumer finishes.
// It must copy no borrowed adapter state and must call this host on one thread.
template<class T> concept FramebufferDisplay = requires(T& display,const gui::Frame& frame) {
    { display.present(frame) } -> std::same_as<void>;
};
template<class T> concept BezelDisplay = requires(T& display,const gui::Frame& frame,
                                                const std::vector<std::string>& labels) {
    { display.present(frame,labels) } -> std::same_as<void>;
};

// No window system, timer thread, device path or allocation policy is imposed.
// The embedding event loop owns timing; input and ticks use the same application
// contract and shared interaction engine as the desktop framebuffer runner.
template<Application App, class Services = AdapterServices> class FramebufferHost {
public:
    class BezelPresentation;
    class BezelToken {
        friend class FramebufferHost;
        friend class BezelPresentation;
        const FramebufferHost* owner_=nullptr;
        gui::Frame frame_;
        Bezel::Token intent_;
        BezelToken(const FramebufferHost* owner,gui::Frame frame,Bezel::Token intent)
            :owner_(owner),frame_(std::move(frame)),intent_(std::move(intent)) {}
    public:
        BezelToken()=default;
    };
    class BezelPresentation {
        friend class FramebufferHost;
        BezelToken token_;
        explicit BezelPresentation(BezelToken token):token_(std::move(token)) {}
    public:
        BezelPresentation()=default;
        explicit operator bool() const noexcept {return token_.owner_!=nullptr;}
        const gui::Frame& frame() const noexcept {return token_.frame_;}
        const std::vector<std::string>& labels() const noexcept {return token_.intent_.labels();}
        const BezelToken& token() const noexcept {return token_;}
    };
    explicit FramebufferHost(unsigned bezel_buttons=3) : bezel_(bezel_buttons) {}
    auto bezel_labels() requires BezelApplication<App> { return bezel_.labels(session_.adapter); }
    BezelPresentation prepare_bezel() requires BezelApplication<App> {
        if(session_.adapter.closed())return {};
        session_.tick();
        if(session_.adapter.closed()||session_.application.presentation_pending())return {};
        const auto epoch=session_.application.input_epoch();
        const auto frame=session_.adapter.frame(displayed_);
        if(session_.adapter.closed()||session_.application.presentation_pending()||
           epoch!=session_.application.input_epoch()||epoch==0||epoch==std::numeric_limits<std::uint64_t>::max())return {};
        return BezelPresentation(BezelToken(this,frame,bezel_.prepare(session_.adapter,epoch)));
    }
    // The driver calls this only after both frame and labels are interactive.
    // In an asynchronous display that acknowledgment may arrive much later.
    bool commit_bezel(const BezelToken& token) requires BezelApplication<App> {
        if(token.owner_!=this||!bezel_.candidate(token.intent_)||session_.adapter.closed()||
           session_.application.presentation_pending()||token.frame_.revision<displayed_)return false;
        const auto current=session_.adapter.frame(displayed_);
        if(current.revision!=token.frame_.revision||current.pixels!=token.frame_.pixels||
           session_.application.presentation_pending()||
           !bezel_.commit(session_.adapter,session_.application.input_epoch(),token.intent_))return false;
        displayed_=token.frame_.revision;return true;
    }
    bool bezel_button(const BezelToken& token,unsigned number) requires BezelApplication<App> {
        if(token.owner_!=this)return false;
        return bezel_.activate(session_.adapter,token.intent_,number,[this] {
            input_.cancel(session_.adapter);
            session_.tick();
        },[this] {return session_.application.input_epoch();},
          [this] {return session_.application.presentation_pending();});
    }
    template<BezelDisplay Display> bool present_bezel(Display& display) requires BezelApplication<App> {
        const auto shown=prepare_bezel();
        if(!shown)return false;
        // Zero pixel damage still presents changed labels and a new opportunity.
        display.present(shown.frame(),shown.labels());
        return commit_bezel(shown.token());
    }
    App& application() noexcept {return session_.application;}
    gui::FramebufferAdapter& adapter() noexcept {return session_.adapter;}
    void resize(gui::Size logical_size,double scale=1) {
        input_.cancel(session_.adapter);session_.adapter.resize(logical_size,scale);session_.tick();
    }
    bool contact(Contact source,ContactPhase phase,gui::Point logical_position) {
        const bool accepted=input_.input(session_.adapter,source,phase,logical_position);
        if(accepted)session_.tick();
        return accepted;
    }
    void cancel() {input_.cancel(session_.adapter);session_.tick();}
    template<FramebufferDisplay Display> bool present(Display& display) {
        if(session_.adapter.closed())return false;
        session_.tick();
        if(session_.adapter.closed())return false;
        const auto frame=session_.adapter.frame(displayed_);
        if(frame.damage.width==0||frame.damage.height==0)return false;
        display.present(frame); // A failing driver must not advance its revision.
        displayed_=frame.revision;return true;
    }
private:
    Session<App,gui::FramebufferAdapter,Services> session_;
    Bezel bezel_;
    FramebufferTouch input_;
    std::uint64_t displayed_=0;
};
} // namespace foundation::host
