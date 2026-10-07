#pragma once
#include <gui/interaction.hpp>
#include <limits>
#include <optional>

namespace foundation::host {
// A driver decodes/calibrates its device coordinates into logical client units.
// Device/contact IDs are opaque host identities, never application widget IDs.
enum class ContactPhase { press, move, release, cancel };
struct Contact {
    enum class Source { mouse, touch, pen };
    Source source=Source::touch;
    std::uint64_t device=0,id=0;
    bool operator==(const Contact&) const = default;
};
class FramebufferTouch {
public:
    bool input(gui::InteractiveAdapter& adapter,Contact contact,ContactPhase phase,gui::Point position,
               bool control=false,bool shift=false,bool alt=false,unsigned clicks=1) {
        if(phase!=ContactPhase::press&&phase!=ContactPhase::move&&phase!=ContactPhase::release&&phase!=ContactPhase::cancel)return false;
        if(adapter.closed()||!std::isfinite(position.x)||!std::isfinite(position.y))return false;
        if(phase==ContactPhase::press) {
            if(owner_)return false; // Extra fingers and synthetic duplicate sources.
            if(serial_==std::numeric_limits<std::uint64_t>::max())throw std::overflow_error("Pointer identity exhausted");
            owner_=contact;++serial_;
        } else if(!owner_||*owner_!=contact)return false;
        const auto kind=phase==ContactPhase::press?gui::PointerKind::press:
            phase==ContactPhase::move?gui::PointerKind::move:
            phase==ContactPhase::release?gui::PointerKind::release:gui::PointerKind::cancel;
        last_=position;
        if(phase==ContactPhase::release||phase==ContactPhase::cancel)owner_.reset();
        adapter.pointer({kind,position,0,0,control,shift,alt,serial_,clicks});
        return true;
    }
    void cancel(gui::InteractiveAdapter& adapter) {
        if(owner_)input(adapter,*owner_,ContactPhase::cancel,last_);
        owner_.reset();
    }
    bool active() const noexcept {return owner_.has_value();}
private:
    std::optional<Contact> owner_;
    std::uint64_t serial_=0;
    gui::Point last_;
};
} // namespace foundation::host
