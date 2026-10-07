#pragma once
#include <gui/interaction.hpp>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace foundation::host {
// A three/five physical-key projection of declared, eligible actions. A press
// belongs to an explicitly committed presentation, never to a refreshed fallback.
class Bezel {
    struct Identity {};
    enum class Operation { activate, checked, choose, action };
    struct Action {
        gui::WidgetKey target;
        std::string id, label, value;
        Operation operation;
        bool checked=false;
        bool operator==(const Action&) const = default;
        gui::Input input() const {
            switch(operation) {
                case Operation::activate:return gui::Activate{};
                case Operation::checked:return gui::SetChecked{checked};
                case Operation::choose:return gui::ChooseOption{id};
                case Operation::action:return gui::InvokeAction{id};
            }
            throw std::logic_error("Unknown bezel operation");
        }
    };
    struct Binding {
        gui::ShortcutKey key;gui::WidgetKey target;bool control,shift,alt;
        bool operator==(const Binding&) const = default;
    };
    struct Context {
        enum class Mode { closed, ordinary, prompt, popup } mode=Mode::closed;
        std::vector<gui::Page> pages;
        std::optional<std::string> page;
        std::optional<gui::WidgetKey> modal;
        std::vector<Binding> bindings;
        std::vector<Action> actions;
        std::size_t selected=0;
        std::uint64_t prompt_id=0;
        gui::ServiceKind prompt_kind=gui::ServiceKind::prompt;
        std::string title,value;
        std::size_t limit=0;
        gui::WidgetKey popup_target;
        gui::Kind popup_kind=gui::Kind::label;
        std::vector<gui::Option> popup_options,declared_options;
        std::optional<std::string> declared_selection;
        bool popup_agrees=false;
        bool operator==(const Context&) const = default;
    };
public:
    // Owned, immutable through the public interface; copies retain one identity.
    class Token {
        friend class Bezel;
        std::shared_ptr<const Identity> owner_;
        std::uint64_t serial_=0,epoch_=0;
        Context context_;
        std::vector<std::string> labels_;
        Token(std::shared_ptr<const Identity> owner,std::uint64_t serial,std::uint64_t epoch,
              Context context,std::vector<std::string> labels)
            :owner_(owner),serial_(serial),epoch_(epoch),context_(std::move(context)),labels_(std::move(labels)) {}
    public:
        Token()=default;
        const std::vector<std::string>& labels() const noexcept {return labels_;}
        std::uint64_t input_epoch() const noexcept {return epoch_;}
    };
    explicit Bezel(unsigned buttons=3):buttons_(buttons) {
        if(buttons!=3&&buttons!=5)throw std::invalid_argument("Bezel requires three or five buttons");
    }
    Bezel(const Bezel&)=delete;
    Bezel& operator=(const Bezel&)=delete;
    template<class Adapter> std::vector<std::string> labels(Adapter& adapter) {
        return labels_for(capture(adapter,true)); // Observation cannot arm input.
    }
    template<class Adapter> Token prepare(Adapter& adapter,std::uint64_t epoch) {
        if(serial_==std::numeric_limits<std::uint64_t>::max())throw std::overflow_error("Bezel identity exhausted");
        auto context=capture(adapter,true);
        return Token(identity_,++serial_,epoch,context,labels_for(context));
    }
    bool candidate(const Token& token) const noexcept {
        return token.owner_==identity_&&token.serial_!=0&&token.serial_==serial_&&token.serial_!=consumed_;
    }
    template<class Adapter> bool commit(Adapter& adapter,std::uint64_t epoch,const Token& token) {
        if(!candidate(token)||!valid(adapter,epoch,token))return false;
        committed_=token;return true;
    }
    // Consume before settling touch/ticks/services: any nested press sees no
    // committed opportunity. Exceptions propagate and cannot retry this press.
    template<class Adapter,class Settle,class Epoch,class Pending>
    bool activate(Adapter& adapter,const Token& token,unsigned button,Settle settle,Epoch epoch,Pending pending) {
        if(!committed_||token.owner_!=identity_||token.serial_!=committed_->serial_)return false;
        auto shown=std::move(*committed_);committed_.reset();consumed_=serial_;
        settle();
        if(button<1||button>buttons_||pending()||!valid(adapter,epoch(),shown))return false;
        const auto& context=shown.context_;
        if(context.mode==Context::Mode::prompt) {
            if(button>2)return false;
            adapter.key(button==1?gui::Key::escape:gui::Key::enter);return true;
        }
        if(context.mode==Context::Mode::popup) {
            if(button==5)return false;
            adapter.key(button==1?gui::Key::up:button==2?gui::Key::down:button==3?gui::Key::enter:gui::Key::escape);return true;
        }
        if(button==4){adapter.key(gui::Key::escape);return true;}
        if(button==5){adapter.key(gui::Key::next_page);return true;}
        if(context.actions.empty())return false;
        if(button==1)selected_=(selected_+context.actions.size()-1)%context.actions.size();
        else if(button==2)selected_=(selected_+1)%context.actions.size();
        else {
            const auto action=context.actions[context.selected];
            return adapter.policy().send(gui::WidgetEvent{action.target,action.input()})==gui::Delivery::delivered;
        }
        return true;
    }
private:
    unsigned buttons_;
    const std::shared_ptr<const Identity> identity_=std::make_shared<const Identity>();
    std::size_t selected_=0;
    std::uint64_t serial_=0,consumed_=0;
    std::vector<Action> actions_;
    std::optional<Token> committed_;
    template<class Adapter> Context capture(Adapter& adapter,bool refresh) {
        Context context;
        if(adapter.closed())return context;
        const auto& view=adapter.snapshot();
        context.pages=view.pages;
        context.page=view.active_page;context.modal=view.modal_root;
        for(const auto& binding:view.key_bindings)
            context.bindings.push_back({binding.key,binding.target,binding.control,binding.shift,binding.alt});
        if(const auto& prompt=adapter.prompt()) {
            context.mode=Context::Mode::prompt;context.prompt_id=prompt->id;context.prompt_kind=prompt->kind;
            context.title=prompt->title;context.value=prompt->value;context.limit=prompt->byte_limit;
            return context;
        }
        if(const auto& popup=adapter.popup()) {
            context.mode=Context::Mode::popup;context.selected=popup->index;context.popup_options=popup->options;
            if(const auto* widget=gui::find_widget(view,popup->key)) {
                context.popup_target=widget->spec.key;context.popup_kind=widget->spec.kind;context.declared_selection=widget->state.selected;
                context.declared_options=widget->spec.kind==gui::Kind::bitmap?widget->state.actions:widget->state.options;
                const auto available=adapter.resolved_availability(popup->key);
                context.popup_agrees=available.visible&&available.enabled&&gui::in_modal_scope(view,popup->key)&&
                    context.popup_options==context.declared_options;
            }
            return context;
        }
        context.mode=Context::Mode::ordinary;
        for(const auto& widget:view.widgets) {
            const auto& key=widget.spec.key;const auto available=adapter.resolved_availability(key);
            if(!available.visible||!available.enabled||!gui::in_modal_scope(view,key))continue;
            const auto add=[&](Operation operation,std::string id,std::string label,std::string value={},bool checked=false) {
                context.actions.push_back({widget.spec.key,std::move(id),std::move(label),std::move(value),operation,checked});
            };
            if(widget.spec.kind==gui::Kind::button)add(Operation::activate,"",widget.state.label);
            else if(widget.spec.kind==gui::Kind::toggle)add(Operation::checked,"",widget.state.label,"",!widget.state.checked);
            else if(widget.spec.kind==gui::Kind::choice||widget.spec.kind==gui::Kind::menu) {
                for(const auto& option:widget.state.options)if(option.enabled)add(Operation::choose,option.id,option.label,option.value);
            } else if(widget.spec.kind==gui::Kind::bitmap) {
                for(const auto& action:widget.state.actions)if(action.enabled)add(Operation::action,action.id,action.label,action.value);
            }
        }
        if(refresh) {
            std::optional<std::pair<gui::WidgetKey,std::string>> old;
            if(selected_<actions_.size())old={{actions_[selected_].target,actions_[selected_].id}};
            selected_=0;
            if(old)for(std::size_t i=0;i<context.actions.size();++i)
                if(context.actions[i].target==old->first&&context.actions[i].id==old->second){selected_=i;break;}
            actions_=context.actions;
        }
        context.selected=selected_;
        return context;
    }
    std::vector<std::string> labels_for(const Context& context) const {
        if(context.mode==Context::Mode::closed)return std::vector<std::string>(buttons_);
        std::vector<std::string> result;
        if(context.mode==Context::Mode::prompt)result={"Cancel","Accept",""};
        else if(context.mode==Context::Mode::popup)result={"Previous","Next","Choose"};
        else result={context.actions.empty()?"":"Previous",context.actions.empty()?"":"Next",
            context.selected<context.actions.size()?context.actions[context.selected].label:""};
        if(buttons_==5){result.push_back(context.mode==Context::Mode::prompt?"":"Back");result.push_back(context.mode==Context::Mode::ordinary?"Next page":"");}
        return result;
    }
    template<class Adapter> bool valid(Adapter& adapter,std::uint64_t epoch,const Token& token) {
        if(token.owner_!=identity_||epoch==0||epoch==std::numeric_limits<std::uint64_t>::max()||epoch!=token.epoch_)return false;
        const auto current=capture(adapter,false);
        return current.mode!=Context::Mode::closed&&current==token.context_&&
            (current.mode!=Context::Mode::popup||current.popup_agrees);
    }
};
}
