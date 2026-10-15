#include "application.hpp"
#include "disk_view.hpp"
#include "flow_view.hpp"
#include "passive_markdown.hpp"
#include "theme.hpp"
#include "workbench/core/launch.hpp"
#include "workbench/core/workspace.hpp"
#include "workbench/core/pseudocode.hpp"
#include "workbench/core/preferences.hpp"
#include "workbench/core/credentials.hpp"
#include "workbench/core/services.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cmath>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace tinyenv {
namespace {
std::filesystem::path launch_root, launch_chat, launch_executable, launch_config_directory, launch_runtime_path;
// The native host ticks every 20 ms; batch fast fragments without skipping its
// ordinary low-cost ticks. Idle and invisible streams still avoid publishing.
constexpr auto stream_display_interval=std::chrono::milliseconds(16);
std::string trim(std::string value) {
    const auto begin=value.find_first_not_of(" \t\r\n");
    return begin==std::string::npos?std::string{}:value.substr(begin,value.find_last_not_of(" \t\r\n")-begin+1);
}
std::string model_search_text(std::string value) {
    for(auto& ch:value)if(ch>='A'&&ch<='Z')ch=static_cast<char>(ch-'A'+'a');
    return value;
}
void validate_submission_model(const AiSettings& ai) {
    if(ai.model.empty())throw std::runtime_error("Choose a model in AI before sending. Enter or select a Model ID.");
    if(ai.provider!="openrouter"&&ai.provider!="openai"&&ai.provider!="ollama")throw std::runtime_error("Choose OpenRouter, OpenAI Responses or Ollama in AI before sending.");
    const auto alphanumeric=[](char ch){return (ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z')||(ch>='0'&&ch<='9');};
    if(ai.model.size()>200||!alphanumeric(ai.model.front())||std::any_of(ai.model.begin(),ai.model.end(),[&](char ch){return !alphanumeric(ch)&&ch!='.'&&ch!='_'&&ch!=':'&&ch!='/'&&ch!='-';}))throw std::runtime_error("Model ID is invalid. Enter or select a provider model in AI before sending.");
    for(std::size_t start=0;start<=ai.model.size();) {
        const auto end=ai.model.find('/',start);const auto part=ai.model.substr(start,end==std::string::npos?std::string::npos:end-start);
        if(part.empty()||part=="."||part=="..")throw std::runtime_error("Model ID has an invalid path. Enter or select a provider model in AI before sending.");
        if(end==std::string::npos)break;
        start=end+1;
    }
    if(ai.provider=="openrouter"&&(ai.model.find('/')==std::string::npos||ai.model.starts_with("openrouter/")))throw std::runtime_error("Choose an explicit publisher/model ID in AI; automatic routers are unavailable.");
    const auto folded=model_search_text(ai.model);
    if(folded.find(":online")!=std::string::npos||folded.find(":extended")!=std::string::npos||folded.find(":floor")!=std::string::npos)throw std::runtime_error("Choose a supported model ID in AI; this routing variant is unavailable.");
    if(ai.provider!="openrouter"&&ai.model.find(":nitro")!=std::string::npos)throw std::runtime_error("Nitro model IDs require OpenRouter. Select the matching provider or model in AI.");
}
std::string presentation_text(std::string_view raw,bool multiline=false) {
    std::string out;out.reserve(raw.size());constexpr char hex[]="0123456789abcdef";
    for(std::size_t i=0;i<raw.size();) {
        const auto ch=static_cast<unsigned char>(raw[i]);
        const std::size_t count=ch<128?1:ch>=0xc2&&ch<=0xdf?2:ch>=0xe0&&ch<=0xef?3:ch>=0xf0&&ch<=0xf4?4:0;
        if(count&&count<=raw.size()-i&&gui::valid_utf8(raw.substr(i,count))&&((ch>=32&&ch!=127)||(multiline&&(ch=='\n'||ch=='\r'||ch=='\t')))) {out.append(raw.substr(i,count));i+=count;}
        else {out+="\\x";out+=hex[ch>>4];out+=hex[ch&15];++i;}
    }
    return out;
}
constexpr std::string_view encoded_record_prefix="tinyenv.bytes:";
std::string record_id(const std::string& raw) {
    if(!raw.starts_with(encoded_record_prefix)&&presentation_text(raw)==raw)return raw;
    std::string out(encoded_record_prefix);constexpr char hex[]="0123456789abcdef";
    for(const unsigned char ch:raw){out+=hex[ch>>4];out+=hex[ch&15];}return out;
}
std::string record_value(const std::string& id) {
    if(!id.starts_with(encoded_record_prefix))return id;
    const auto hex=id.substr(encoded_record_prefix.size());std::string out;out.reserve(hex.size()/2);
    const auto digit=[](char ch){return ch>='0'&&ch<='9'?ch-'0':ch>='a'&&ch<='f'?ch-'a'+10:-1;};
    if(hex.size()%2)throw std::runtime_error("Invalid file record identity.");
    for(std::size_t i=0;i<hex.size();i+=2){const auto hi=digit(hex[i]),lo=digit(hex[i+1]);if(hi<0||lo<0)throw std::runtime_error("Invalid file record identity.");out+=static_cast<char>((hi<<4)|lo);}return out;
}
std::vector<std::string> lines(const std::string& value) {
    std::vector<std::string> out;std::istringstream stream(value);std::string line;
    while(std::getline(stream,line))if(!(line=trim(line)).empty())out.push_back(std::move(line));
    return out;
}
std::string numeric(double value) {std::ostringstream out;out<<value;return out.str();}
template<class T> std::string numeric(const std::optional<T>& value) {return value?numeric(static_cast<double>(*value)):std::string{};}
double real(const std::string& value,double lo,double hi) {
    double out{};const auto parsed=std::from_chars(value.data(),value.data()+value.size(),out);
    if(parsed.ec!=std::errc{}||parsed.ptr!=value.data()+value.size()||!std::isfinite(out)||out<lo||out>hi)
        throw std::runtime_error("Parameter must be a number between "+numeric(lo)+" and "+numeric(hi)+".");
    return out;
}
std::size_t integer(const std::string& value,std::size_t lo,std::size_t hi) {
    std::size_t out{};const auto parsed=std::from_chars(value.data(),value.data()+value.size(),out);
    if(parsed.ec!=std::errc{}||parsed.ptr!=value.data()+value.size()||out<lo||out>hi)
        throw std::runtime_error("Parameter must be an integer between "+std::to_string(lo)+" and "+std::to_string(hi)+".");
    return out;
}
std::string string_field(const json::Value& value,std::string_view key) {
    if(const auto* field=value.find(key))if(const auto* text=std::get_if<std::string>(&field->data))return *text;
    return {};
}
std::string service_name(ServiceState state) {
    switch(state){case ServiceState::idle:return "Ready";case ServiceState::running:return "Running";case ServiceState::succeeded:return "Completed";case ServiceState::failed:return "Failed";case ServiceState::cancelled:return "Cancelled";}
    return {};
}
std::string quote_shell(const std::string& value) {
    std::string out="'";for(char ch:value)out+=ch=='\''?"'\\''":std::string(1,ch);return out+"'";
}
bool within_path(const std::filesystem::path& path,const std::filesystem::path& ancestor) {
    const auto child=path.lexically_normal(),parent=ancestor.lexically_normal();
    auto a=parent.begin(),b=child.begin();
    for(;a!=parent.end();++a,++b)if(b==child.end()||*a!=*b)return false;
    return true;
}
std::string chat_title(const std::filesystem::path& path) {
    const auto name=path.filename().string();return Workspace::is_chat_path(path)?name.substr(0,name.size()-8):path.stem().string();
}
const FlowNode* find_node(const std::vector<FlowNode>& nodes,std::uint64_t id) {
    for(const auto& node:nodes){if(node.id==id)return &node;if(auto* found=find_node(node.children,id))return found;if(auto* found=find_node(node.otherwise,id))return found;}return nullptr;
}
struct Location {std::uint64_t parent{};std::size_t index{};bool otherwise{};};
std::optional<Location> locate(const std::vector<FlowNode>& nodes,std::uint64_t id,std::uint64_t parent=0,bool otherwise=false) {
    for(std::size_t i=0;i<nodes.size();++i){if(nodes[i].id==id)return Location{parent,i,otherwise};if(auto value=locate(nodes[i].children,id,nodes[i].id))return value;if(auto value=locate(nodes[i].otherwise,id,nodes[i].id,true))return value;}return std::nullopt;
}
json::Value toggles_json(const std::vector<PathToggle>& values) {
    json::Value::Array out;for(const auto& value:values)out.push_back(json::Value::Object{{"path",value.path},{"enabled",value.enabled}});return out;
}
json::Value settings_json(const AiSettings& ai) {
    json::Value::Object out{{"provider",ai.provider},{"model",ai.model}};
    if(ai.num_predict)out["num_predict"]=*ai.num_predict;
    if(ai.temperature)out["temperature"]=*ai.temperature;
    if(ai.top_p)out["top_p"]=*ai.top_p;
    if(!ai.endpoint.empty())out["endpoint"]=ai.endpoint;
    if(ai.provider=="ollama"){if(ai.num_keep)out["num_keep"]=*ai.num_keep;if(ai.num_ctx)out["num_ctx"]=*ai.num_ctx;}
    else {if(!ai.service_tier.empty())out["service_tier"]=ai.service_tier;if(!ai.reasoning_effort.empty())out["reasoning_effort"]=ai.reasoning_effort;}
    if(ai.provider=="openrouter"&&ai.nitro)out["nitro"]=true;
    if(ai.provider=="openrouter"&&!ai.routing_providers.empty()){json::Value::Array routes;for(const auto& route:ai.routing_providers)routes.emplace_back(route);out["routing_providers"]=std::move(routes);}
    return out;
}
struct Fence {std::size_t start{},content{},end{};std::string text;bool closed{};};
// Read only top-level Markdown fences. Other fenced languages protect their
// contents, so a quoted example cannot silently become an executable draft.
std::vector<Fence> pseudocode_fences(const std::string& text) {
    std::vector<Fence> result;char marker{};std::size_t count{};bool recognized{};Fence active;
    for(std::size_t position=0;position<text.size();) {
        const auto newline=text.find('\n',position),end=newline==std::string::npos?text.size():newline;
        auto line=std::string_view(text).substr(position,end-position);if(line.ends_with('\r'))line.remove_suffix(1);
        std::size_t indent{};while(indent<line.size()&&line[indent]==' ')++indent;
        if(indent<=3) {
            auto body=line.substr(indent);std::size_t run{};while(run<body.size()&&(body[run]=='`'||body[run]=='~')&&body[run]==body[0])++run;
            if(marker) {
                if(!body.empty()&&body[0]==marker&&run>=count&&body.substr(run).find_first_not_of(" \t")==std::string_view::npos) {
                    if(recognized){active.end=newline==std::string::npos?text.size():newline+1;active.text=text.substr(active.content,position-active.content);active.closed=true;result.push_back(std::move(active));}
                    marker=0;count=0;recognized=false;
                }
            }else if(run>=3) {
                const auto info=trim(std::string(body.substr(run)));
                if(body[0]!='`'||info.find('`')==std::string::npos) {
                    marker=body[0];count=run;recognized=info=="pseudocode"||info=="tinyenv"||info=="flow";
                    active={position,newline==std::string::npos?text.size():newline+1,text.size(),{},false};
                }
            }
        }
        if(newline==std::string::npos)break;
        position=newline+1;
    }
    if(marker&&recognized){active.text=text.substr(active.content);result.push_back(std::move(active));}
    return result;
}
std::optional<Fence> pseudocode_fence(const std::string& text) {
    const auto fences=pseudocode_fences(text);return fences.size()==1?std::optional<Fence>{fences.front()}:std::nullopt;
}
std::string submitted_pseudocode(const std::string& draft) {
    const auto fences=pseudocode_fences(draft);
    if(fences.empty())throw std::runtime_error("Agentic mode needs a fenced pseudocode block in the current message. Insert or write one before sending.");
    if(fences.size()!=1)throw std::runtime_error("Keep exactly one pseudocode block in the current message before sending.");
    if(!fences.front().closed)throw std::runtime_error("Close the pseudocode fence in the current message before sending.");
    return fences.front().text;
}
std::string replace_pseudocode(std::string draft,const std::string& source) {
    const auto fences=pseudocode_fences(draft);
    if(fences.size()>1)throw std::runtime_error("Keep one pseudocode block in the current message before editing its flow.");
    // Choose a fence longer than any marker run in source so literal Markdown
    // inside a prompt cannot terminate the block prematurely.
    std::size_t maximum{};for(std::size_t i=0;i<source.size();){if(source[i]!='`'){++i;continue;}const auto start=i;while(i<source.size()&&source[i]=='`')++i;maximum=std::max(maximum,i-start);}
    const std::string marker(std::max(std::size_t(3),maximum+1),'`');
    std::string block=marker+"pseudocode\n"+source;if(block.back()!='\n')block+='\n';block+=marker+"\n";
    if(!fences.empty())draft.replace(fences.front().start,fences.front().end-fences.front().start,block);
    else {if(!draft.empty()&&draft.back()!='\n')draft+='\n';if(!draft.empty())draft+='\n';draft+=block;}
    return draft;
}
std::string quote_reply(const std::string& text) {std::string out="> ";for(std::size_t i=0;i<text.size();++i){out+=text[i];if(text[i]=='\n'&&i+1<text.size())out+="> ";}return out;}
gui::BitmapSource reply_busy_icon() {
    static const gui::BitmapSource source([](const gui::BitmapRequest& request,const gui::BitmapSink& sink){
        if(request.width>512||request.height>512)throw std::length_error("Reply indicator exceeds its sample bound");
        const auto palette=theme::dark_palette();std::vector<std::uint8_t> row(gui::pixel_row_bytes(request.damage.width,request.format));
        for(unsigned y=0;y<request.damage.height;++y){std::fill(row.begin(),row.end(),0);for(unsigned x=0;x<request.damage.width;++x){
            const auto px=(double(request.damage.x+x)+.5)/request.width-.5,py=(double(request.damage.y+y)+.5)/request.height-.5;
            const auto radius=px*px+py*py;const auto ink=radius>=.085&&radius<=.155&&!(px>.04&&py<-.04);const auto color=ink?palette.muted:palette.background;
            if(request.format==gui::PixelFormat::rgb24){const auto at=std::size_t(x)*3;row[at]=color.red;row[at+1]=color.green;row[at+2]=color.blue;}
            else{const auto gray=static_cast<std::uint8_t>((77u*color.red+150u*color.green+29u*color.blue+128u)/256u);if(request.format==gui::PixelFormat::gray8)row[x]=gray;else if(gray>=128)row[x/8]|=std::uint8_t(0x80u>>(x%8));}
        }sink(request.damage.x,request.damage.y+y,{request.damage.width,1,row.size(),request.format,row});}
    });return source;
}
gui::BitmapSource idle_boundary_line() {
    static const gui::BitmapSource source([](const gui::BitmapRequest& request,const gui::BitmapSink& sink){
        const auto color=theme::dark_palette().border;std::vector<std::uint8_t> row(gui::pixel_row_bytes(request.damage.width,request.format));
        for(unsigned x=0;x<request.damage.width;++x){
            if(request.format==gui::PixelFormat::rgb24){const auto at=std::size_t(x)*3;row[at]=color.red;row[at+1]=color.green;row[at+2]=color.blue;}
            else if(request.format==gui::PixelFormat::gray8)row[x]=static_cast<std::uint8_t>((77u*color.red+150u*color.green+29u*color.blue+128u)/256u);
            else row[x/8]|=std::uint8_t(0x80u>>(x%8));
        }
        for(unsigned y=0;y<request.damage.height;++y)sink(request.damage.x,request.damage.y+y,{request.damage.width,1,row.size(),request.format,row});
    });return source;
}
json::Value source_metadata(const json::Value& value) {
    json::Value::Array result;const auto* sources=std::get_if<json::Value::Array>(&value.data);if(!sources)return result;
    static const std::set<std::string> fields{"id","title","url","path","kind","query"};
    static const std::set<std::string> metadata_fields{"untrusted","instruction_authority","no_links_followed","sha256","bytes_loaded","truncated","source_path","source_sha256","index_sha256","ranked","local_path","article","index_path","query","search_excerpt","search_provider"};
    const auto bounded=[](const std::string& text,std::size_t maximum){auto out=text.substr(0,maximum);while(!out.empty()&&!foundation::editor::ProjectFiles::valid_utf8(out))out.pop_back();return out;};
    std::size_t used=2;
    for(const auto& source:*sources) {
        const auto* values=std::get_if<json::Value::Object>(&source.data);if(!values)continue;
        json::Value::Object out,metadata;
        const auto retain=[&](const std::string& name,const json::Value& item){const auto key=name=="bytes"?"bytes_loaded":name=="context_truncated"?"truncated":name;if(!metadata_fields.contains(key))return;if(const auto* text=std::get_if<std::string>(&item.data))metadata[key]=bounded(*text,4096);else if(std::holds_alternative<bool>(item.data)||std::holds_alternative<double>(item.data))metadata[key]=item;};
        for(const auto& [key,item]:*values) {
            if(fields.contains(key)){if(const auto* text=std::get_if<std::string>(&item.data))out[key]=bounded(*text,4096);}
            else if(key=="metadata"){if(const auto* entries=std::get_if<json::Value::Object>(&item.data))for(const auto& [name,detail]:*entries){if(name=="keywords"){if(const auto* words=std::get_if<json::Value::Array>(&detail.data)){json::Value::Array keywords;for(const auto& word:*words){if(const auto* text=std::get_if<std::string>(&word.data))keywords.emplace_back(bounded(*text,512));if(keywords.size()==128)break;}metadata[name]=std::move(keywords);}}else retain(name,detail);}}
            else retain(key,item);
        }
        if(!metadata.empty())out["metadata"]=std::move(metadata);
        const auto size=json::stringify(out).size();if(result.size()==4095||size+used+1>1024*1024-1024)break;used+=size+1;result.emplace_back(std::move(out));
    }
    if(result.size()<sources->size())result.emplace_back(json::Value::Object{{"id","tinyenv.sources.truncated"},{"title",std::to_string(sources->size()-result.size())+" source record(s) omitted from persisted metadata"},{"kind","metadata"},{"metadata",json::Value::Object{{"truncated",true},{"instruction_authority",false}}}});
    return result;
}
}
void configure_launch(std::filesystem::path root,std::filesystem::path chat,std::filesystem::path executable,std::filesystem::path config_directory,std::filesystem::path runtime_path) {
    launch_root=std::move(root);launch_chat=std::move(chat);launch_executable=std::move(executable);launch_config_directory=std::move(config_directory);launch_runtime_path=std::move(runtime_path);
}

struct Application::Impl {
    gui::Adapter& adapter;gui::Snapshot view;
    std::unique_ptr<Workspace> workspace;
    std::unique_ptr<AiPreferences> preferences;
    std::unique_ptr<AiCredentials> credentials;
    CredentialStatus credential_status=CredentialStatus::unsupported;
    std::string key_draft,key_provider,key_status_error;
    std::uint64_t key_input_revision{};
    struct Session {
        Chat chat;PseudocodeDocument flow;Terminal terminal;TerminalStatus terminal_status;
        PassiveMarkdownView markdown,split_markdown;
        std::string split_source_path,split_source_text;
        std::uint64_t split_source_revision{},split_edit_revision{};
        bool split_source_dirty=true;
        struct TranscriptScroll {
            gui::Point offset,tail_maximum;gui::WidgetKey group_key,tail_key;
            bool following=true,force_tail=true,initialized=false;
            unsigned tail_probe_ticks{};
            std::string tail_text,pause_body;gui::Point pause_maximum;gui::Rect tail_bounds;gui::Font tail_font;gui::TextWrap tail_wrap=gui::TextWrap::none;
            std::map<std::string,gui::Point> body_offsets;
            struct BodyVersion {gui::WidgetKey key;std::string text;gui::Rect bounds;gui::Font font;gui::TextWrap wrap;};
            std::map<std::string,BodyVersion> body_versions;
        };
        TranscriptScroll main_scroll;
        std::map<std::string,TranscriptScroll> split_scroll;
        FlowGraph cached_graph;std::uint64_t graph_revision{};
        Job job;JobStatus job_status;GitStatusJob git;GitStatus git_status;
        std::string operation,source_report,terminal_command,selected_snippet,selector_kind="scribbles",builder_job_id;
        std::uint64_t builder_action_revision{},builder_setup_revision{};
        struct DraftEdit {std::string draft,source;gui::TextSelection composer_selection,flow_selection;std::vector<ImageAttachment> images;};
        struct ChatEdit {std::string text;gui::TextSelection selection;};
        std::vector<DraftEdit> undo_draft,redo_draft;std::vector<ChatEdit> undo_chat,redo_chat;
        std::uint64_t selected_node{},job_identity{},terminal_identity{},save_serial{},edit_revision{},send_revision{},transcript_revision=1;bool save_due{},save_conflict{};
        std::chrono::steady_clock::time_point changed_at{};std::string save_error,last_edit="wb.composer",typing_field;std::chrono::steady_clock::time_point typed_at{};
        // A reply owns only this suffix. Candidate replacements and final output
        // cannot rewrite the submitted message or any earlier history.
        std::string stream_baseline,stream_suffix;
        bool stream_owned{},stream_conflict{},reply_remembered{};
        std::size_t displayed_stream_revision{};
        std::chrono::steady_clock::time_point last_stream_display{},last_stream_save{};
        explicit Session(Chat document,std::filesystem::path credential_directory):chat(std::move(document)),flow(pseudocode_fence(chat.state.draft)?pseudocode_fence(chat.state.draft)->text:std::string{}),job(8*1024*1024,launch_runtime_path,{},std::move(credential_directory)){chat.state.pseudocode=flow.text();source_report=chat.state.sources_json=="[]"?std::string{}:chat.state.sources_json;for(auto& task:chat.state.builder.tasks)if(task.status=="running"){task.status="interrupted";save_due=true;changed_at=std::chrono::steady_clock::now();}}
        const FlowGraph& graph() {if(graph_revision!=flow.revision()){cached_graph=flow.graph();graph_revision=flow.revision();}return cached_graph;}
    };
    std::map<std::string,std::unique_ptr<Session>> sessions;std::string current;
    std::string presented_chat,presented_split;
    ChatState empty_state;
    std::vector<std::filesystem::path> chat_paths;
    std::map<std::string,std::string> fields;
    std::filesystem::path directory=".";std::vector<std::filesystem::path> back;
    std::set<std::string> expanded;std::vector<TreeEntry> tree;
    std::vector<std::pair<std::string,std::size_t>> tree_rows;std::string selected_file;
    DiskUsage usage;DiskView disk;FlowView graph;std::optional<std::pair<std::uint64_t,std::string>> disk_press;
    std::vector<Snippet> prompt_snippets,flow_snippets;std::string snippet_kind="Prompts",snippet_id;
    std::vector<Snippet> tutorial_snippets;
    std::unique_ptr<Job> model_job;Job guardrail_job;JobStatus model_status,guardrail_status;
    std::vector<std::pair<std::string,std::string>> available_models;
    std::string catalog_provider,catalog_endpoint,model_provider,model_endpoint,selected_model,selected_model_provider,selected_model_endpoint,configured_model;
    std::string guardrail_loaded_id,guardrail_fingerprint,guardrail_action;
    bool guardrail_enabled{},guardrail_desired{};
    std::string selector_kind="scribbles",selector_selected;
    std::unique_ptr<foundation::editor::CodeBuffer> file_buffer;
    std::filesystem::path operation_path;
    enum class TaskKind {job,terminal,models,guardrail};
    struct TaskTarget {TaskKind kind{};std::string path;std::uint64_t identity{};};
    std::map<std::string,TaskTarget> task_targets;std::string selected_task;std::optional<TaskTarget> context_task;
    std::uint64_t task_identity{},model_identity{},guardrail_identity{},task_action_revision{},catalog_input_revision{};
    std::string modal,prompt_action,status="Choose a .chat.md conversation, or create one to begin.";
    bool error{},pending{},stopped{};
    std::uint64_t epoch=1,revision=1,widget_generation{},flow_input_revision{};
    std::map<std::string,gui::TextSelection> restored_selection;
    bool right_sidebar_visible=true,restore_sidebar=false;
    std::map<std::string,gui::Point> sidebar_scroll;
    std::map<std::string,gui::TextSelection> sidebar_selection;
    std::string sidebar_owner;
    std::string sidebar_preference_error;
    struct Life {gui::WidgetSpec spec;bool active{};std::uint64_t scene{},semantic{},source_revision{};};std::map<std::string,Life> lives;
    struct CommandLife {gui::Command command;bool active{};std::uint64_t scene{},semantic{};};std::map<std::string,CommandLife> command_lives;
    std::uint64_t file_edit_revision{};
    gui::ServiceQueue image_services;
    struct ImageChoice {std::string chat;std::uint64_t scene{},send_revision{};};
    std::optional<ImageChoice> image_choice;
    std::uint64_t image_service_id{};

    explicit Impl(gui::Adapter& a):adapter(a),guardrail_job(8*1024*1024,launch_runtime_path) {
        view.client_size={1440,860};view.title="tinyEnv AI Workbench";view.palette=theme::dark_palette();view.widgets.reserve(128);
        std::string preferences_error;
        try {preferences=std::make_unique<AiPreferences>(launch_config_directory);preferences->inherit(empty_state);right_sidebar_visible=preferences->right_sidebar_visible();}
        catch(const std::exception& e){preferences_error="AI defaults could not be loaded: "+std::string(e.what());}
        if(preferences)try {credentials=std::make_unique<AiCredentials>(preferences->directory());}
        catch(const std::exception& e){key_status_error=e.what();}
        model_job=std::make_unique<Job>(8*1024*1024,launch_runtime_path,std::string{},credential_directory());
        sync_fields();
        try {
            workspace=std::make_unique<Workspace>(resolve_launch_root(launch_root));
            refresh();
            if(!launch_chat.empty())open_chat(launch_chat);
            prompt_snippets=workspace->snippets(SnippetKind::prompts);
            flow_snippets=workspace->snippets(SnippetKind::pseudocode);
            std::size_t i=0;for(auto& text:pseudocode_snippets())tutorial_snippets.push_back({"builtin."+std::to_string(++i),"Tutorial example "+std::to_string(i),text});
            if(preferences)fields["ai.guardrail.id"]=preferences->openrouter_guardrail_id();
        }catch(const std::exception& e){failure(e.what());}
        if(!preferences_error.empty())failure(std::move(preferences_error));
        publish();
    }
    Session* session() {const auto it=sessions.find(current);return it==sessions.end()?nullptr:it->second.get();}
    ChatState& state() {if(auto* s=session())return s->chat.state;return empty_state;}
    bool dirty() {auto* s=session();return s&&(s->save_due||s->chat.text!=s->chat.original.text);}
    static gui::Point transcript_maximum(const gui::Widget& group) {
        auto viewport=gui::Rect{0,0,group.state.bounds.width,group.state.bounds.height};if(group.state.content_clip)viewport=gui::intersect(viewport,*group.state.content_clip);
        return {std::max(0.0,group.state.content_size.width-viewport.width),std::max(0.0,group.state.content_size.height-viewport.height)};
    }
    gui::Point text_maximum(const gui::Widget& body,gui::Point restore) {
        // Text wrapping is adapter-owned. Query its actual clamp only when the
        // bounded final block changes, then restore the reader's viewport.
        adapter.scroll(body.spec.key,{restore.x,gui::coordinate_limit});const auto maximum=adapter.scroll_offset(body.spec.key);adapter.scroll(body.spec.key,restore);return maximum;
    }
    void observe_transcript(Session::TranscriptScroll& scroll,const std::string& id,bool tick) {
        if(!scroll.initialized)return;
        const auto found=std::find_if(view.widgets.begin(),view.widgets.end(),[&](const auto& widget){return widget.spec.key.id==id&&widget.spec.key==scroll.group_key;});if(found==view.widgets.end())return;
        const auto offset=adapter.scroll_offset(found->spec.key);const auto maximum=transcript_maximum(*found);bool moved_up=offset.y<scroll.offset.y-2&&offset.y<maximum.y-2;
        if(moved_up)scroll.pause_body.clear();
        for(const auto& body:view.widgets)if(body.spec.kind==gui::Kind::text&&body.spec.parent==id) {
            const auto position=adapter.scroll_offset(body.spec.key);const auto previous=scroll.body_offsets.find(body.spec.key.id);
            auto observed=position;
            bool body_up=previous!=scroll.body_offsets.end()&&position.y<previous->second.y-2;
            if(body.spec.key==scroll.tail_key&&scroll.tail_probe_ticks){
                const auto previous_maximum=scroll.tail_maximum;
                adapter.scroll(body.spec.key,{position.x,gui::coordinate_limit});scroll.tail_maximum=adapter.scroll_offset(body.spec.key);body_up=body_up&&position.y<scroll.tail_maximum.y-2;
                // A larger wrapped range with a stationary old end is layout
                // growth, not a reader scrolling up. A smaller range can also
                // clamp an old end downward without changing follow intent.
                // Retain the saturated intent until native synchronization.
                // An approximate pre-sync clamp must not replace that intent.
                if(!scroll.following){
                    // Keep a queued reader position authoritative while a new
                    // native buffer/range is staged. A movement within a valid
                    // range is real user input and replaces the cached target.
                    const auto target=previous==scroll.body_offsets.end()?position:previous->second;
                    const bool staged=position.y<target.y-2&&scroll.tail_maximum.y<target.y-2;
                    observed=staged?target:position;body_up=!staged&&position.y<target.y-2;adapter.scroll(body.spec.key,observed);
                }else if(moved_up||body_up)adapter.scroll(body.spec.key,position);else observed=scroll.tail_maximum;
                if(tick){if(scroll.following&&!moved_up&&!body_up&&scroll.tail_maximum!=previous_maximum)scroll.tail_probe_ticks=2;else --scroll.tail_probe_ticks;}
            }else if(body_up&&scroll.tail_probe_ticks&&!scroll.following){
                const auto actual_maximum=text_maximum(body,position);
                if(actual_maximum.y<previous->second.y-2){observed=previous->second;body_up=false;adapter.scroll(body.spec.key,observed);}
            }
            if(!scroll.force_tail&&body_up){moved_up=true;scroll.pause_body=body.spec.key.id;scroll.pause_maximum=body.spec.key==scroll.tail_key?scroll.tail_maximum:text_maximum(body,position);}
            scroll.body_offsets[body.spec.key.id]=observed;
        }
        const auto tail=scroll.body_offsets.find(scroll.tail_key.id);const bool tail_end=tail==scroll.body_offsets.end()||tail->second.y>=scroll.tail_maximum.y-2;
        const auto paused=scroll.body_offsets.find(scroll.pause_body);const bool pause_end=scroll.pause_body.empty()||paused==scroll.body_offsets.end()||paused->second.y>=scroll.pause_maximum.y-2;
        if(!scroll.force_tail){if(moved_up)scroll.following=false;else if(offset.y>=maximum.y-2&&tail_end&&pause_end){scroll.following=true;scroll.pause_body.clear();}}
        scroll.offset=offset;
    }
    void observe_transcript_scroll(bool tick=false) {
        const auto owner=sessions.find(presented_chat);if(owner==sessions.end())return;
        try {observe_transcript(owner->second->main_scroll,"wb.chat.rendered",tick);if(!presented_split.empty())observe_transcript(owner->second->split_scroll[presented_split],"wb.split.rendered",tick);}catch(const std::exception&){}
    }
    void restore_transcript(Session::TranscriptScroll& scroll,const std::string& id) {
        const auto found=std::find_if(view.widgets.begin(),view.widgets.end(),[&](const auto& widget){return widget.spec.key.id==id;});if(found==view.widgets.end())return;
        const auto maximum=transcript_maximum(*found);const auto follow=scroll.following||scroll.force_tail;
        const gui::Point desired{scroll.offset.x,follow?maximum.y:scroll.offset.y};if(adapter.scroll_offset(found->spec.key)!=desired)adapter.scroll(found->spec.key,desired);
        const gui::Widget* tail=nullptr;std::map<std::string,gui::Point> positions;std::map<std::string,Session::TranscriptScroll::BodyVersion> versions;
        for(const auto& body:view.widgets)if(body.spec.kind==gui::Kind::text&&body.spec.parent==id)tail=&body;
        const bool same_tail=tail&&scroll.tail_text==tail->state.text&&scroll.tail_bounds.width==tail->state.bounds.width&&scroll.tail_bounds.height==tail->state.bounds.height&&scroll.tail_font==tail->state.font&&scroll.tail_wrap==tail->state.wrap;
        // Canonicalizing Streaming to Incomplete result shifts source offsets.
        // Transfer a reader position only for exactly the same bounded body.
        if(!follow&&same_tail&&!scroll.body_offsets.contains(tail->spec.key.id))if(const auto previous=scroll.body_offsets.find(scroll.tail_key.id);previous!=scroll.body_offsets.end()){scroll.body_offsets[tail->spec.key.id]=previous->second;if(scroll.pause_body==scroll.tail_key.id)scroll.pause_body=tail->spec.key.id;}
        for(const auto& body:view.widgets)if(body.spec.kind==gui::Kind::text&&body.spec.parent==id){const auto prior=scroll.body_offsets.find(body.spec.key.id);const auto offset=prior==scroll.body_offsets.end()?adapter.scroll_offset(body.spec.key):prior->second;
            // A staged native text replacement can reset its viewport despite
            // the old editor still reporting this exact offset before sync.
            const auto previous=scroll.body_versions.find(body.spec.key.id);
            const bool changed=previous==scroll.body_versions.end()||previous->second.key!=body.spec.key||previous->second.text!=body.state.text||previous->second.bounds!=body.state.bounds||previous->second.font!=body.state.font||previous->second.wrap!=body.state.wrap;
            if(!follow&&prior!=scroll.body_offsets.end()) {if(changed)adapter.scroll(body.spec.key,offset);positions[body.spec.key.id]=offset;}
            else {if(adapter.scroll_offset(body.spec.key)!=offset)adapter.scroll(body.spec.key,offset);positions[body.spec.key.id]=adapter.scroll_offset(body.spec.key);}
            if(!changed)versions.emplace(body.spec.key.id,std::move(previous->second));else versions.emplace(body.spec.key.id,Session::TranscriptScroll::BodyVersion{body.spec.key,body.state.text,body.state.bounds,body.state.font,body.state.wrap});
        }
        if(tail) {
            const auto position=positions.at(tail->spec.key.id);
            const bool changed=scroll.tail_key!=tail->spec.key||scroll.tail_text!=tail->state.text||scroll.tail_bounds.width!=tail->state.bounds.width||scroll.tail_bounds.height!=tail->state.bounds.height||scroll.tail_font!=tail->state.font||scroll.tail_wrap!=tail->state.wrap;
            // Native text scrolling may be staged until the host's sync after
            // tick. Saturate the request itself, then reconcile the actual
            // wrapped range until two stable ticks without publishing a frame.
            if(changed)scroll.tail_probe_ticks=2;
            if(follow&&(changed||position.y!=scroll.tail_maximum.y)){adapter.scroll(tail->spec.key,{position.x,gui::coordinate_limit});scroll.tail_maximum=adapter.scroll_offset(tail->spec.key);}
            if(follow)positions[tail->spec.key.id]=adapter.scroll_offset(tail->spec.key);
            scroll.tail_key=tail->spec.key;scroll.tail_text=tail->state.text;scroll.tail_bounds=tail->state.bounds;scroll.tail_font=tail->state.font;scroll.tail_wrap=tail->state.wrap;
        }else{scroll.tail_key={};scroll.tail_text.clear();scroll.tail_maximum={};}
        scroll.offset=adapter.scroll_offset(found->spec.key);scroll.group_key=found->spec.key;scroll.body_offsets=std::move(positions);scroll.body_versions=std::move(versions);scroll.initialized=true;scroll.following=follow;scroll.force_tail=false;
    }
    void restore_transcript_scroll() {
        presented_chat=current;presented_split.clear();if(auto* s=session()){restore_transcript(s->main_scroll,"wb.chat.rendered");if(s->chat.state.split_chat){presented_split=fields["wb.split.path"];restore_transcript(s->split_scroll[presented_split],"wb.split.rendered");}}
    }
    bool transcript_visible(const Session& s) {
        if(!session()||state().builder.active||state().center_tab!="Chat Markdown")return false;
        return &s==session()||(state().split_chat&&fields["wb.split.path"]==s.chat.path.generic_string());
    }
    bool dirty_visible(const Session& s) {return &s==session()||state().left_tab=="Chats";}
    void follow_submission(Session& s) {
        s.main_scroll.following=true;s.main_scroll.force_tail=true;s.main_scroll.pause_body.clear();
    }
    std::filesystem::path credential_directory() const {return preferences&&AiCredentials::storage_available()?preferences->directory():std::filesystem::path{};}
    void failure(std::string text){status=std::move(text);error=true;}
    void success(std::string text){status=std::move(text);error=false;}
    void set_sidebar_visible(bool visible,bool reveal=false) {
        if(visible==right_sidebar_visible)return;
        if(!visible) {
            sidebar_scroll.clear();sidebar_selection.clear();sidebar_owner=current;
            for(const auto& widget:view.widgets)if(widget.spec.key.id=="wb.right"||widget.spec.parent=="wb.right") {
                if(widget.spec.kind==gui::Kind::group||widget.spec.kind==gui::Kind::list||widget.spec.kind==gui::Kind::text)sidebar_scroll[widget.spec.key.id]=adapter.scroll_offset(widget.spec.key);
                if(widget.spec.kind==gui::Kind::text)sidebar_selection[widget.spec.key.id]=adapter.text_selection(widget.spec.key);
            }
        }
        if(reveal)right_sidebar_visible=true;
        try {if(preferences)preferences->set_right_sidebar_visible(visible);else if(!reveal)throw std::runtime_error("Sidebar preferences are unavailable.");sidebar_preference_error.clear();}
        catch(const std::exception& e){if(!reveal)throw;sidebar_preference_error="Sidebar shown; could not remember its visibility: "+std::string(e.what());}
        right_sidebar_visible=visible;restore_sidebar=visible;
    }
    void show_ai() {
        set_sidebar_visible(true,true);
        if(state().right_tab!="AI"){state().right_tab="AI";if(auto* s=session())modified(*s);}
        // AI can be taller than the pane. Start at its repair controls rather
        // than restoring another tab's off-screen position.
        sidebar_scroll.clear();sidebar_scroll["wb.right"]={};if(sidebar_owner!=current)sidebar_selection.clear();sidebar_owner=current;restore_sidebar=true;
    }
    void cancel_flow_drag(std::uint64_t owner=0) {
        const bool cancelled=owner?graph.cancel_drag(owner):graph.dragging();
        if(!owner)graph.cancel_drag();
        // Revoking this surface generation makes every adapter release any
        // capture when a keyboard action or scene change ends the gesture.
        if(cancelled)++flow_input_revision;
    }
    void refresh(){if(!workspace)return;chat_paths=workspace->chats();refresh_tree();}
    void refresh_tree() {
        tree.clear();tree_rows.clear();if(!workspace)return;
        std::size_t visits{};
        const auto walk=[&](auto&& self,const std::filesystem::path& path,std::size_t depth)->void {
            if(depth>16||visits>=2000)return;
            for(const auto& entry:workspace->children(path,2000-visits)) {
                if(++visits>2000)break;
                tree.push_back(entry);tree_rows.push_back({entry.path.generic_string(),depth});
                if(entry.directory&&!entry.symlink&&expanded.contains(entry.path.generic_string()))self(self,entry.path,depth+1);
            }
        };walk(walk,directory,0);fields["wb.path"]=directory.generic_string();
    }
    void sync_fields() {
        auto* s=session();auto& ai=state().ai;
        key_draft.clear();++key_input_revision;refresh_key_status();
        fields["ai.endpoint"]=ai.endpoint;fields["ai.model"]=ai.model;fields["ai.num_predict"]=numeric(ai.num_predict);
        fields["ai.num_keep"]=numeric(ai.num_keep);fields["ai.num_ctx"]=numeric(ai.num_ctx);
        fields["ai.temperature"]=numeric(ai.temperature);fields["ai.top_p"]=numeric(ai.top_p);fields["ai.service_tier"]=ai.service_tier;
        fields["ai.reasoning_effort"]=ai.reasoning_effort;
        fields["ai.routing_providers"].clear();for(const auto& route:ai.routing_providers){if(!fields["ai.routing_providers"].empty())fields["ai.routing_providers"]+=", ";fields["ai.routing_providers"]+=route;}
        fields["research.max_queries"]=std::to_string(state().selector.research_max_queries);fields["research.max_results"]=std::to_string(state().selector.research_max_results);fields["research.kiwix_index"]=state().selector.kiwix_index;fields["selector.context_kib"]=std::to_string(state().selector.context_max_kib);
        if(!s){fields["wb.chat.text"].clear();fields["wb.composer"].clear();fields["wb.flow.text"].clear();fields["wb.terminal.command"].clear();return;}
        fields["wb.chat.text"]=s->chat.text;fields["wb.composer"]=s->chat.state.draft;fields["wb.flow.text"]=s->flow.text();
        fields["wb.terminal.command"]=s->terminal_command;
        selector_kind=s->selector_kind;
        for(auto it=fields.begin();it!=fields.end();)if(it->first.starts_with("builder."))it=fields.erase(it);else ++it;
        for(const auto& [key,value]:s->chat.state.builder.fields)fields[key]=value;
        reset_node_fields();
    }
    void refresh_key_status() {
        const auto& provider=state().ai.provider;
        if(key_provider!=provider){key_draft.clear();key_provider=provider;++key_input_revision;}
        credential_status=CredentialStatus::unsupported;
        if(!credentials){if(key_status_error.empty())key_status_error="Private key storage is unavailable.";return;}
        key_status_error.clear();
        try {credential_status=credentials->status(provider);}
        catch(const std::exception& e){key_status_error=e.what();}
    }
    void save_key() {
        ++key_input_revision;
        if(!credentials||!AiCredentials::supports(state().ai.provider))throw std::runtime_error("Private API-key storage is unavailable for this provider.");
        try {credentials->save(state().ai.provider,key_draft);}
        catch(...){key_draft.clear();refresh_key_status();throw;}
        key_draft.clear();refresh_key_status();success("API key saved in private provider configuration.");
    }
    void remove_key() {
        key_draft.clear();++key_input_revision;
        if(!credentials||!AiCredentials::supports(state().ai.provider))throw std::runtime_error("Private API-key storage is unavailable for this provider.");
        try {credentials->remove(state().ai.provider);}
        catch(...){refresh_key_status();throw;}
        refresh_key_status();success("Saved API key removed. Existing provider configuration applies.");
    }
    void reset_node_fields() {
        if(auto* s=session())s->selected_node=0;
        fields["node.kind"]="agent";for(const auto* id:{"node.role","node.text","node.iterations","node.parent","node.index"})fields[id].clear();fields["node.condition"]="approved";fields["node.otherwise"]="false";
    }
    void modified(Session& s) {s.save_due=true;s.changed_at=std::chrono::steady_clock::now();++s.edit_revision;++s.send_revision;}
    void save_state(Session& s) {
        s.chat.state.pseudocode=s.flow.text();
        try {workspace->save(s.chat);s.save_due=false;s.save_conflict=false;s.save_error.clear();++s.save_serial;if(s.stream_owned)s.last_stream_save=std::chrono::steady_clock::now();}
        catch(const std::exception& e){s.save_due=true;s.save_conflict=true;s.save_error=e.what();throw;}
    }
    static std::size_t edit_bytes(const Session::ChatEdit& value) {return value.text.size();}
    static std::size_t edit_bytes(const Session::DraftEdit& value) {return value.draft.size()+value.source.size();}
    template<class T> static void remember(std::vector<T>& history,T value) {
        constexpr std::size_t limit=8*1024*1024;std::size_t bytes=edit_bytes(value);for(const auto& edit:history)bytes+=edit_bytes(edit);
        while(!history.empty()&&(history.size()>=100||bytes>limit)){bytes-=edit_bytes(history.front());history.erase(history.begin());}
        if(edit_bytes(value)<=limit)history.push_back(std::move(value));
    }
    gui::TextSelection selection(const Session& s,const std::string& id) const {
        if(s.chat.path.generic_string()!=current)return {};
        const auto found=lives.find(id);return found!=lives.end()&&found->second.active?adapter.text_selection(found->second.spec.key):gui::TextSelection{};
    }
    Session::DraftEdit draft_edit(const Session& s) const {return {s.chat.state.draft,s.flow.text(),selection(s,"wb.composer"),selection(s,"wb.flow.text"),s.chat.state.draft_images};}
    void remember_chat(Session& s) {remember(s.undo_chat,Session::ChatEdit{s.chat.text,selection(s,"wb.chat.text")});s.redo_chat.clear();}
    bool typing_step(Session& s,const std::string& id,const std::string& before,const std::string& after) {
        std::size_t prefix{};while(prefix<before.size()&&prefix<after.size()&&before[prefix]==after[prefix])++prefix;
        std::size_t suffix{};while(suffix<before.size()-prefix&&suffix<after.size()-prefix&&before[before.size()-suffix-1]==after[after.size()-suffix-1])++suffix;
        const auto removed=before.size()-prefix-suffix,added=after.size()-prefix-suffix;
        const bool character=(removed==0&&added>0&&added<=4)||(added==0&&removed>0&&removed<=4);
        const auto now=std::chrono::steady_clock::now();const bool coalesce=character&&s.typing_field==id&&now-s.typed_at<std::chrono::milliseconds(600);
        s.typing_field=character?id:std::string{};s.typed_at=now;s.last_edit=id;return !coalesce;
    }
    void remember_draft(Session& s) {remember(s.undo_draft,draft_edit(s));s.redo_draft.clear();}
    void set_draft(Session& s,std::string draft,bool remember_change=true) {
        if(s.chat.state.draft==draft)return;
        if(remember_change)remember_draft(s);
        s.last_edit="wb.composer";s.chat.state.draft=std::move(draft);const auto fence=pseudocode_fence(s.chat.state.draft);
        s.flow.set_text(fence?fence->text:std::string{});s.chat.state.pseudocode=s.flow.text();
        if(&s==session()){fields["wb.composer"]=s.chat.state.draft;fields["wb.flow.text"]=s.flow.text();reset_node_fields();}modified(s);
    }
    void set_flow(Session& s,std::string source,bool remember_change=true) {
        auto draft=replace_pseudocode(s.chat.state.draft,source);const auto fence=pseudocode_fence(draft);
        if(!fence||!fence->closed)throw std::runtime_error("Close the other Markdown code fence in the current message before inserting pseudocode.");
        if(remember_change)remember_draft(s);
        s.last_edit="wb.flow.text";
        s.chat.state.draft=std::move(draft);s.flow.set_text(source);s.chat.state.pseudocode=s.flow.text();
        fields["wb.composer"]=s.chat.state.draft;fields["wb.flow.text"]=s.flow.text();reset_node_fields();modified(s);
    }
    bool developer_enabled() const {return preferences&&preferences->developer_mode();}
    bool history_locked(const Session& s) const {return s.stream_owned&&s.job.running();}
    void undo_text(std::string_view id,bool redo=false) {
        auto* s=session();if(!s)return;s->typing_field.clear();s->last_edit=std::string(id);
        if(id=="wb.chat.text") {
            if(!developer_enabled()||history_locked(*s))return;
            auto& from=redo?s->redo_chat:s->undo_chat;auto& to=redo?s->undo_chat:s->redo_chat;if(from.empty())return;
            remember(to,Session::ChatEdit{s->chat.text,selection(*s,"wb.chat.text")});auto edit=std::move(from.back());from.pop_back();s->chat.text=std::move(edit.text);++s->transcript_revision;restored_selection["wb.chat.text"]=edit.selection;fields["wb.chat.text"]=s->chat.text;modified(*s);
        }else if(id=="wb.composer"||id=="wb.flow.text") {
            auto& from=redo?s->redo_draft:s->undo_draft;auto& to=redo?s->undo_draft:s->redo_draft;if(from.empty())return;
            remember(to,draft_edit(*s));auto edit=std::move(from.back());from.pop_back();
            s->chat.state.draft=std::move(edit.draft);s->chat.state.draft_images=std::move(edit.images);s->flow.set_text(edit.source);s->chat.state.pseudocode=s->flow.text();restored_selection["wb.composer"]=edit.composer_selection;restored_selection["wb.flow.text"]=edit.flow_selection;
            fields["wb.composer"]=s->chat.state.draft;fields["wb.flow.text"]=s->flow.text();reset_node_fields();modified(*s);
        }
    }
    void open_chat(std::filesystem::path path) {
        cancel_flow_drag();restored_selection.clear();
        if(path.is_absolute())path=path.lexically_relative(workspace->root());
        std::string warning;
        if(auto* old=session();old&&old->save_due)try{save_state(*old);}catch(const std::exception& e){warning="Autosave conflict in "+old->chat.path.generic_string()+"; changes remain in memory: "+std::string(e.what());}
        const auto key=path.generic_string();
        if(!sessions.contains(key))sessions.emplace(key,std::make_unique<Session>(workspace->open_chat(path),credential_directory()));
        if(preferences)preferences->inherit(sessions.at(key)->chat.state);
        current=key;++revision;sync_fields();snippet_id.clear();selector_selected.clear();fields["wb.split.path"].clear();fields["wb.split.text"].clear();directory=state().cwd;back.clear();refresh_tree();
        if(sessions.at(key)->save_conflict)failure("Autosave conflict in "+key+"; changes remain in memory: "+sessions.at(key)->save_error);else if(warning.empty())success("Opened "+key+".");else failure("Opened "+key+". "+warning);
        if(state().left_tab=="Files")refresh_tree();
        if(state().left_tab=="Filelight")usage=workspace->disk_usage(directory);
        if(state().right_tab=="Git")refresh_git();
    }
    void prompt(std::string action,std::string title,std::string value={}) {modal="prompt";prompt_action=std::move(action);fields["prompt.title"]=std::move(title);fields["prompt.value"]=std::move(value);}
    void accept_prompt() {
        const auto value=trim(fields["prompt.value"]);if(value.empty())throw std::runtime_error("Enter a project-relative file path.");
        if(prompt_action=="new") {
            auto chat=workspace->new_chat(value,"# "+chat_title(value)+"\n\n");
            const auto key=chat.path.generic_string();sessions.emplace(key,std::make_unique<Session>(std::move(chat),credential_directory()));refresh();open_chat(value);
        }else if(prompt_action=="copy-retained") {
            const auto found=sessions.find(operation_path.generic_string());if(found==sessions.end()||!found->second->save_conflict)throw std::runtime_error("The retained chat is no longer available. Select it again.");
            auto& original=*found->second;if(!Workspace::is_chat_path(value))throw std::runtime_error("A retained chat copy must end with .chat.md.");
            (void)workspace->files().directory(std::filesystem::path(value).parent_path().empty()?std::filesystem::path("."):std::filesystem::path(value).parent_path());
            workspace->create_file(value,original.chat.text);auto copy=workspace->open_chat(value);copy.state=original.chat.state;copy.state.pseudocode=original.flow.text();
            try{workspace->save_state(copy);}catch(const std::exception& e){throw std::runtime_error("Copied retained chat text to "+value+", but its state was not confirmed: "+std::string(e.what())+" Original changes remain in memory.");}
            refresh();selected_file=operation_path.generic_string();operation_path.clear();success("Copied retained chat and draft to "+value+".");
        }else if(prompt_action=="copy-file") {
            workspace->copy_entry(operation_path,value);refresh();selected_file=value;operation_path.clear();success("Copied file to "+value+".");
        }else if(prompt_action=="open")open_chat(value);
        else if(prompt_action=="create-file") {workspace->create_file(value);refresh();selected_file=value;success("Created "+value+".");}
        else if(prompt_action=="create-directory") {workspace->create_directory(value);refresh();selected_file=value;success("Created folder "+value+".");}
        else if(prompt_action=="rename")mutate_entry(value);
        modal.clear();
    }
    void browse(std::filesystem::path path,bool remember=true) {
        (void)workspace->files().directory(path);
        if(remember)back.push_back(directory);
        directory=std::move(path);selected_file.clear();refresh_tree();
        if(state().left_tab=="Filelight")usage=workspace->disk_usage(directory);
    }
    void disk_select(const std::string& path) {
        selected_file=path;const auto entry=std::find_if(usage.entries.begin(),usage.entries.end(),[&](const auto& item){return item.path.generic_string()==path;});
        if(entry!=usage.entries.end()&&entry->directory)browse(entry->path);
    }
    const TreeEntry* selected_entry() const {for(const auto& entry:tree)if(entry.path.generic_string()==selected_file)return &entry;return nullptr;}
    void attach_image(const std::filesystem::path& path) {
        auto* s=session();if(!s)throw std::runtime_error("Create or open a chat before attaching an image.");
        auto& images=s->chat.state.draft_images;
        if(images.size()>=Workspace::maximum_images)throw std::runtime_error("Keep at most four images in the current message.");
        const auto image=workspace->attach_image(path);
        std::size_t bytes=image.bytes;
        for(const auto& pending:images){if(pending.sha256==image.sha256)throw std::runtime_error("This image is already attached to the current message.");bytes+=pending.bytes;}
        if(bytes>Workspace::maximum_images_bytes)throw std::runtime_error("Keep attached images within 8 MiB total.");
        remember_draft(*s);s->typing_field.clear();s->last_edit="wb.composer";images.push_back(image);modified(*s);
        success("Attached "+presentation_text(image.name)+"; select Send to submit it.");
    }
    void choose_image() {
        auto* s=session();if(!s)throw std::runtime_error("Create or open a chat before attaching an image.");
        if(image_choice)throw std::runtime_error("Finish the current image selection first.");
        if(s->chat.state.draft_images.size()>=Workspace::maximum_images)throw std::runtime_error("Keep at most four images in the current message.");
        if(!image_services.enqueue({++image_service_id,gui::ServiceKind::prompt,"Local PNG/JPEG image path (absolute or project-relative)",{},4096}))throw std::runtime_error("Image selection is unavailable.");
        image_choice=ImageChoice{current,revision,s->send_revision};
    }
    void remove_image(std::string_view identity) {
        auto* s=session();if(!s)return;auto& images=s->chat.state.draft_images;
        const auto image=std::find_if(images.begin(),images.end(),[&](const auto& item){return item.sha256==identity;});
        if(image==images.end())throw std::runtime_error("This image is no longer attached.");
        remember_draft(*s);s->typing_field.clear();s->last_edit="wb.composer";images.erase(image);modified(*s);success("Image removed from the current message.");
    }
    void open_file() {
        const auto* entry=selected_entry();if(!entry)throw std::runtime_error("Select a file first.");
        if(entry->symlink)throw std::runtime_error("Symbolic links are not opened by the project file browser.");
        if(entry->directory){browse(entry->path);return;}
        if(file_buffer&&file_buffer->dirty())throw std::runtime_error("Save or discard the open file before opening another.");
        if(Workspace::is_chat_path(entry->path)){file_buffer.reset();open_chat(entry->path);modal.clear();return;}
        file_buffer=std::make_unique<foundation::editor::CodeBuffer>(workspace->files().read(entry->path));
        fields["file.text"]=file_buffer->text();modal="file";
    }
    std::filesystem::path creation_directory() const {
        if(const auto* entry=selected_entry())return entry->directory?entry->path:entry->path.parent_path();
        return directory;
    }
    void entry_operation(bool remove) {
        const auto* entry=selected_entry();if(!entry)throw std::runtime_error("Select a file or folder first.");
        if(entry->symlink)throw std::runtime_error("Symbolic links are not changed by the project file browser.");
        operation_path=entry->path;
        if(remove)modal="delete";
        else prompt("rename","Rename file or folder",entry->path.generic_string());
    }
    void mutate_entry(std::optional<std::filesystem::path> destination={}) {
        if(operation_path.empty())throw std::runtime_error("Select a file or folder first.");
        if(file_buffer&&within_path(file_buffer->path(),operation_path))throw std::runtime_error("Close the open file editor before renaming or deleting this path.");
        const auto entries=workspace->children(operation_path.parent_path().empty()?std::filesystem::path("."):operation_path.parent_path());
        const auto found=std::find_if(entries.begin(),entries.end(),[&](const auto& entry){return entry.path==operation_path;});
        if(found==entries.end())throw std::runtime_error("The selected file or folder no longer exists. Refresh the browser.");
        std::vector<std::string> retire;std::string renamed_current;
        for(const auto& [path,s]:sessions) {
            if(s->job.running()||s->git.running())throw std::runtime_error("Wait for running tasks or cancel them before renaming or deleting project files.");
            if(found->directory&&s->terminal.running())throw std::runtime_error("Stop the workbench's terminals before renaming or deleting folders; a shell may have changed directory.");
            if(!within_path(s->chat.path,operation_path))continue;
            if(s->save_due||s->chat.text!=s->chat.original.text)save_state(*s);
            std::string saved_draft;if(s->chat.state_original.identity.exists)saved_draft=string_field(json::parse(s->chat.state_original.text),"draft");
            if(s->chat.state.draft!=saved_draft||!s->terminal_command.empty())throw std::runtime_error("Save or clear the chat's draft before renaming or deleting this path.");
            if(s->terminal.running())throw std::runtime_error("Stop this chat's terminal before renaming or deleting its file.");
            if(destination&&path==current)renamed_current=(s->chat.path==operation_path?*destination:(*destination/s->chat.path.lexically_relative(operation_path))).lexically_normal().generic_string();
            retire.push_back(path);
        }
        for(const auto& path:retire)if(auto& s=*sessions.at(path);s.save_due)save_state(s);
        try {if(destination)workspace->rename_entry(operation_path,*destination);else workspace->remove_entry(operation_path);}
        catch(...) {refresh();throw;}
        for(const auto& path:retire){if(path==current)current.clear();sessions.erase(path);}
        if(found->directory)for(auto& [path,s]:sessions)if(within_path(s->chat.state.cwd,operation_path)) {
            const auto cwd=std::filesystem::path(s->chat.state.cwd);const auto updated=destination?(cwd==operation_path?*destination:(*destination/cwd.lexically_relative(operation_path))):operation_path.parent_path();
            s->chat.state.cwd=updated.empty()?".":updated.lexically_normal().generic_string();modified(*s);(void)path;
        }
        if(current.empty()) {empty_state=ChatState{};if(preferences)preferences->inherit(empty_state);empty_state.left_tab="Files";sync_fields();fields["wb.split.path"].clear();fields["wb.split.text"].clear();}
        if(within_path(directory,operation_path))directory=destination?(*destination/directory.lexically_relative(operation_path)).lexically_normal():operation_path.parent_path();
        if(directory.empty())directory=".";
        back.clear();expanded.clear();selected_file.clear();refresh();
        const auto changed=operation_path.generic_string();operation_path.clear();modal.clear();
        if(!renamed_current.empty())open_chat(renamed_current);
        success(destination?"Renamed "+changed+" to "+destination->generic_string()+".":"Deleted "+changed+".");
    }
    void discard_retained_chat() {
        const auto found=sessions.find(operation_path.generic_string());if(found==sessions.end()||!found->second->save_conflict)throw std::runtime_error("The retained chat is no longer available. Select it again.");
        auto& s=*found->second;if(s.job.running()||s.terminal.running())throw std::runtime_error("Cancel this chat's task and stop its terminal before discarding retained changes.");
        auto document=workspace->open_chat(s.chat.path);if(preferences)preferences->inherit(document.state);
        const auto fence=pseudocode_fence(document.state.draft);s.chat=std::move(document);++s.transcript_revision;s.flow.set_text(fence?fence->text:std::string{});s.chat.state.pseudocode=s.flow.text();
        s.undo_chat.clear();s.redo_chat.clear();s.undo_draft.clear();s.redo_draft.clear();s.save_due=false;s.save_conflict=false;s.save_error.clear();s.typing_field.clear();
        s.source_report=s.chat.state.sources_json=="[]"?std::string{}:s.chat.state.sources_json;if(s.chat.path.generic_string()==current)sync_fields();
        operation_path.clear();modal.clear();success("Retained changes discarded; chat and draft reloaded from disk.");
    }
    std::vector<PathToggle>& path_list() {auto& selector=state().selector;return selector_kind=="refs"?selector.refs:selector_kind=="tools"?selector.tools:selector.scribbles;}
    AiSettings edited_ai_settings() {
        AiSettings updated=state().ai;
        updated.endpoint=trim(fields["ai.endpoint"]);updated.model=trim(fields["ai.model"]);
        if(updated.provider!="ollama"){updated.service_tier=trim(fields["ai.service_tier"]);updated.reasoning_effort=trim(fields["ai.reasoning_effort"]);}
        if(updated.provider=="openrouter"){auto routes=fields["ai.routing_providers"];std::replace(routes.begin(),routes.end(),',','\n');updated.routing_providers=lines(routes);if(updated.routing_providers.size()>8)throw std::runtime_error("Use at most eight trusted provider routes.");}
        const auto optional_integer=[&](const char* id,std::size_t lo,std::size_t hi)->std::optional<int>{const auto value=trim(fields[id]);return value.empty()?std::nullopt:std::optional<int>{static_cast<int>(integer(value,lo,hi))};};
        const auto optional_real=[&](const char* id,double lo,double hi)->std::optional<double>{const auto value=trim(fields[id]);return value.empty()?std::nullopt:std::optional<double>{real(value,lo,hi)};};
        updated.num_predict=optional_integer("ai.num_predict",updated.provider=="openai"?16:1,65536);
        if(updated.provider=="ollama"){updated.num_keep=optional_integer("ai.num_keep",0,4000000);updated.num_ctx=optional_integer("ai.num_ctx",128,4000000);if(updated.num_keep&&updated.num_ctx&&*updated.num_keep>*updated.num_ctx)throw std::runtime_error("Tokens kept cannot exceed context tokens.");}
        updated.temperature=optional_real("ai.temperature",0,2);updated.top_p=optional_real("ai.top_p",0,1);if(updated.top_p&&*updated.top_p<=0)throw std::runtime_error("Top-p must be greater than zero and at most 1.");
        validate_ai_settings(updated);return updated;
    }
    void apply_ai() {
        auto& ai=state().ai;auto updated=edited_ai_settings();
        if(!preferences)throw std::runtime_error("AI defaults are unavailable. Repair the reported configuration problem and restart before saving AI settings.");
        preferences->save(updated);ai=std::move(updated);state().ai_configured=true;
        if(auto* s=session()){modified(*s);try{save_state(*s);}catch(const std::exception& e){throw std::runtime_error("AI defaults saved, but this chat's settings could not be saved: "+std::string(e.what()));}}
        success(session()?"AI settings saved for this chat and as defaults for new chats.":"AI defaults saved for new chats.");
    }
    void add_configured_model() {
        if(!preferences)throw std::runtime_error("AI preferences are unavailable.");
        auto models=preferences->configured_models();
        const ConfiguredModel model{state().ai.provider,trim(fields["ai.endpoint"]),trim(fields["ai.model"]),trim(fields["ai.models.label"])};
        if(model.model.empty())throw std::runtime_error("Enter or select a model before adding it.");
        if(std::any_of(models.begin(),models.end(),[&](const auto& entry){return entry.provider==model.provider&&entry.endpoint==model.endpoint&&entry.model==model.model;}))throw std::runtime_error("This provider, endpoint and model are already configured.");
        models.push_back(model);preferences->save_configured_models(models);configured_model=std::to_string(models.size()-1);success("Model added to the application list.");
    }
    void select_configured_model(const std::string& id) {
        if(!preferences)throw std::runtime_error("AI preferences are unavailable.");
        const auto index=integer(id,0,127);const auto& models=preferences->configured_models();
        if(index>=models.size())throw std::runtime_error("The configured model no longer exists.");
        const auto& model=models[index];state().ai.provider=model.provider;state().ai.endpoint=model.endpoint;state().ai.model=model.model;
        fields["ai.endpoint"]=model.endpoint;fields["ai.model"]=model.model;fields["ai.models.label"]=model.label;configured_model=id;selected_model.clear();
        refresh_key_status();
        success("Selected configured model. Apply to remember it as the default.");
    }
    void remove_configured_model() {
        if(!preferences||configured_model.empty())throw std::runtime_error("Select a configured model to remove.");
        auto models=preferences->configured_models();const auto index=integer(configured_model,0,127);
        if(index>=models.size())throw std::runtime_error("The configured model no longer exists.");
        models.erase(models.begin()+static_cast<std::ptrdiff_t>(index));preferences->save_configured_models(models);configured_model.clear();success("Model removed from the application list.");
    }
    void refresh_models() {
        if(!workspace)throw std::runtime_error("Open a valid workspace before refreshing models.");
        if(model_job->running())throw std::runtime_error("The model list is already refreshing.");
        const auto provider=state().ai.provider,endpoint=trim(fields["ai.endpoint"]);
        json::Value input=json::Value::Object{{"schema_version",1},{"operation","models"},{"root",workspace->root().string()},
            {"settings",json::Value::Object{{"provider",provider},{"endpoint",endpoint}}}};
        model_job->start(input,workspace->root());model_identity=++task_identity;model_status={ServiceState::running,-1,{}, {},{},false,0};model_provider=provider;model_endpoint=endpoint;success("Refreshing available models…");
    }
    bool guardrail_ready() const {return !guardrail_fingerprint.empty()&&guardrail_loaded_id==trim(fields.at("ai.guardrail.id"))&&!guardrail_job.running();}
    void run_guardrail(bool apply) {
        if(!workspace||!preferences)throw std::runtime_error("Open a valid workspace with available preferences first.");
        if(guardrail_job.running())throw std::runtime_error("A guardrail request is already running.");
        const auto id=trim(fields["ai.guardrail.id"]);if(id.empty())throw std::runtime_error("Enter an existing OpenRouter guardrail ID.");
        if(apply&&!guardrail_ready())throw std::runtime_error("Load this guardrail's current status before applying a change.");
        preferences->save_guardrail_id(id);
        json::Value::Object guardrail{{"id",id},{"action",apply?"set":"get"}};
        if(apply){guardrail["enabled"]=guardrail_desired;guardrail["fingerprint"]=guardrail_fingerprint;}
        json::Value input=json::Value::Object{{"schema_version",1},{"operation","guardrail"},{"root",workspace->root().string()},
            {"settings",json::Value::Object{{"provider","openrouter"},{"network_enabled",true},{"timeout",30}}},{"guardrail",std::move(guardrail)}};
        guardrail_loaded_id.clear();guardrail_fingerprint.clear();guardrail_job.start(input,workspace->root());guardrail_identity=++task_identity;guardrail_status={ServiceState::running,-1,{}, {},{},false,0};
        success(apply?"Applying the shared OpenRouter guardrail…":"Loading the OpenRouter guardrail…");
    }
    bool poll_models() {
        if(!model_job->running()&&model_status.state!=ServiceState::running)return false;
        auto next=model_job->poll();if(next.state==model_status.state)return false;model_status=std::move(next);
        if(model_status.state!=ServiceState::succeeded){failure("Model refresh: "+(model_status.error.empty()?service_name(model_status.state):model_status.error));return true;}
        try {
            if(!model_status.response)throw std::runtime_error("No model catalog was returned.");
            const auto* models=model_status.response->find("models");if(!models)throw std::runtime_error("The response has no model catalog.");
            if(models->array().size()>4096)throw std::runtime_error("The model catalog exceeds its display limit.");
            std::vector<std::pair<std::string,std::string>> rows;std::set<std::string> ids;
            for(const auto& model:models->array()) {
                const auto id=string_field(model,"id"),name=string_field(model,"name"),provider=string_field(model,"provider");
                if(id.empty()||id.size()>4096||name.size()>4096||provider!=model_provider||!ids.insert(id).second)throw std::runtime_error("The model catalog contains an invalid entry.");
                rows.push_back({id,name.empty()?id:name});
            }
            const auto* truncated=model_status.response->find("models_truncated");const bool is_truncated=truncated&&truncated->boolean();
            available_models=std::move(rows);catalog_provider=model_provider;catalog_endpoint=model_endpoint;++catalog_input_revision;
            success("Available models refreshed: "+std::to_string(available_models.size())+(is_truncated?" (catalog truncated).":"."));
        }catch(const std::exception& e){model_status.state=ServiceState::failed;failure("Model refresh: "+std::string(e.what()));}
        return true;
    }
    bool poll_guardrail() {
        if(!guardrail_job.running()&&guardrail_status.state!=ServiceState::running)return false;
        auto next=guardrail_job.poll();if(next.state==guardrail_status.state)return false;guardrail_status=std::move(next);
        if(guardrail_status.state!=ServiceState::succeeded){failure("Guardrail: "+(guardrail_status.error.empty()?service_name(guardrail_status.state):guardrail_status.error));return true;}
        try {
            if(!guardrail_status.response)throw std::runtime_error("No guardrail status was returned.");
            const auto* guardrail=guardrail_status.response->find("guardrail");if(!guardrail)throw std::runtime_error("The response has no guardrail status.");
            const auto id=string_field(*guardrail,"id"),fingerprint=string_field(*guardrail,"fingerprint"),action=string_field(*guardrail,"action");
            const auto* enabled=guardrail->find("enabled");
            if(id.empty()||id!=trim(fields["ai.guardrail.id"]))throw std::runtime_error("Guardrail ID changed during the request. Load status again.");
            if(!enabled||!std::holds_alternative<bool>(enabled->data)||fingerprint.size()!=64||fingerprint.find_first_not_of("0123456789abcdef")!=std::string::npos)throw std::runtime_error("The response contains an invalid guardrail status.");
            if(enabled->boolean()&&action!="block"&&action!="flag"&&action!="redact")throw std::runtime_error("The guardrail has an unsupported injection action.");
            guardrail_loaded_id=id;guardrail_fingerprint=fingerprint;guardrail_action=action;guardrail_enabled=enabled->boolean();guardrail_desired=guardrail_enabled;
            success("OpenRouter guardrail status loaded. Current injection action: "+(guardrail_enabled?action:std::string("off"))+".");
        }catch(const std::exception& e){guardrail_loaded_id.clear();guardrail_fingerprint.clear();guardrail_enabled=false;guardrail_desired=false;guardrail_status.state=ServiceState::failed;failure("Guardrail: "+std::string(e.what()));}
        return true;
    }
    json::Value request(std::string operation,const std::string& prompt,const std::string& history,const AiSettings& ai) {
        auto* s=session();if(!s)throw std::runtime_error("Create or open a chat first.");
        const auto& selector=s->chat.state.selector;
        const bool calculations=(operation=="chat"||operation=="agent")&&selector.calculations;
        json::Value::Object out{{"schema_version",1},{"operation",std::move(operation)},{"root",workspace->root().string()},
            {"chat_path",s->chat.path.generic_string()},{"prompt",prompt},{"settings",settings_json(ai)},
            {"selector",json::Value::Object{{"deep_research",selector.deep_research||ai.web_search},{"calculations",calculations},{"scribbles",toggles_json(selector.scribbles)},{"refs",toggles_json(selector.refs)},{"tools",toggles_json(selector.tools)}}},
            {"pseudocode",std::string{}}};
        if(out.at("operation").string()=="agent")out["pseudocode"]=submitted_pseudocode(prompt);
        const auto context_bytes=static_cast<std::size_t>(selector.context_max_kib)*1024;out["context_limits"]=json::Value::Object{{"max_total_bytes",context_bytes},{"max_file_bytes",std::min(context_bytes,std::size_t(4*1024*1024))},{"max_files",128}};
        out["research_limits"]=json::Value::Object{{"max_queries",selector.research_max_queries},{"max_results",selector.research_max_results},{"max_context_bytes",context_bytes}};out["research_source"]=selector.research_source;
        if(!selector.kiwix_index.empty())out["kiwix_index"]=selector.kiwix_index;
        if(selector.research_source=="local"){json::Value::Array paths;for(const auto* list:{&selector.scribbles,&selector.refs})for(const auto& value:*list)if(value.enabled)paths.emplace_back(value.path);out["research_paths"]=std::move(paths);}
        if(!history.empty())out["history"]=json::Value::Array{json::Value::Object{{"role","user"},{"content",history}}};
        json::Value::Array external;
        for(const auto* list:{&selector.scribbles,&selector.refs,&selector.tools})for(const auto& path:*list)if(path.enabled&&std::filesystem::path(path.path).is_absolute())external.emplace_back(path.path);
        if(!selector.kiwix_index.empty()&&std::filesystem::path(selector.kiwix_index).is_absolute())external.emplace_back(selector.kiwix_index);
        out["allowed_context_paths"]=std::move(external);return out;
    }
    void send(bool retry=false) {
        auto* s=session();if(!s)throw std::runtime_error("Create or open a chat first.");
        if(s->job.running())throw std::runtime_error("This chat already has a running task.");
        if(retry&&!s->chat.state.submission)throw std::runtime_error("This chat has no recorded submission to retry. Send a message first.");
        const auto prompt=retry?s->chat.state.submission->prompt:s->chat.state.draft;const auto agentic=retry?s->chat.state.submission->agentic:s->chat.state.agentic;
        const auto& images=retry?s->chat.state.submission->images:s->chat.state.draft_images;
        if(trim(prompt).empty()&&images.empty())throw std::runtime_error("Write a message or attach an image first.");
        if(prompt.size()>64*1024)throw std::runtime_error("Keep the current message within 64 KiB before sending.");
        AiSettings ai;
        try {ai=edited_ai_settings();validate_submission_model(ai);}
        catch(...){show_ai();throw;}
        if(agentic){const auto source=submitted_pseudocode(prompt);PseudocodeDocument submitted(source);if(!submitted.parsed())throw std::runtime_error("Repair the pseudocode syntax in the current message before running agents.");}
        const auto history=retry?submission_history(s->chat):s->chat.text;const auto submission=retry?s->chat.state.submission:std::optional<SubmittedMessage>{make_submission(prompt,agentic,history,images)};
        auto input=request(agentic?"agent":"chat",prompt,history,ai);input.object()["stream"]=true;if(!images.empty())input.object()["images"]=workspace->image_payloads(images);
        // Flush pending settings/history before launching; a conflict keeps the
        // current message in memory and prevents an accidental duplicate send.
        s->chat.state.ai=std::move(ai);s->chat.state.ai_configured=true;save_state(*s);s->job.start(input,workspace->root());s->job_identity=++task_identity;++s->send_revision;s->operation=agentic?"agent":"chat";s->job_status={ServiceState::running,-1,{}, {},{},false,0};
        if(!retry)s->chat.state.submission=submission;
        remember_chat(*s);s->chat.text+=retry?std::string("\n## Retry\n\nRetrying the previous ")+(agentic?"agentic":"chat")+" message using the current AI settings.\n":"\n## User\n\n"+prompt+"\n";if(!retry&&!images.empty()) {
            s->chat.text+="\nAttached images:\n";
            for(const auto& image:images){std::string name;for(const char ch:presentation_text(image.name)){if(std::string_view("\\`*_{}[]<>#|~").find(ch)!=std::string_view::npos)name+='\\';name+=ch;}s->chat.text+="\n- "+name+" ("+std::to_string(image.bytes)+" bytes)";}
            s->chat.text+='\n';
        }
        ++s->transcript_revision;fields["wb.chat.text"]=s->chat.text;
        if(retry)modified(*s);else {remember_draft(*s);set_draft(*s,{},false);s->chat.state.draft_images.clear();modified(*s);}
        s->stream_baseline=s->chat.text;s->stream_suffix.clear();s->stream_owned=true;s->stream_conflict=false;s->reply_remembered=false;s->displayed_stream_revision=0;s->last_stream_display=s->last_stream_save=std::chrono::steady_clock::now();
        follow_submission(*s);
        try{save_state(*s);success(retry?"Previous message retry started; current draft retained.":"AI task started.");}catch(const std::exception& e){failure("AI task started; autosave conflict. Current message and history remain in memory: "+std::string(e.what()));}
    }
    bool replace_reply(Session& s,const std::string& text,std::string_view heading) {
        const auto suffix=text.empty()?std::string{}:"\n## "+std::string(heading)+"\n\n"+quote_reply(text)+"\n";
        if(s.stream_owned) {
            if(s.stream_conflict||s.chat.text.size()!=s.stream_baseline.size()+s.stream_suffix.size()||!s.chat.text.starts_with(s.stream_baseline)||std::string_view(s.chat.text).substr(s.stream_baseline.size())!=s.stream_suffix)throw std::runtime_error("The live reply's transcript section changed; its validated output remains in memory.");
            if(s.stream_suffix==suffix)return false;
            if(!s.reply_remembered){remember_chat(s);s.reply_remembered=true;}
            s.chat.text.resize(s.stream_baseline.size());s.chat.text+=suffix;s.stream_suffix=suffix;
        }else {
            if(suffix.empty())return false;
            remember_chat(s);s.chat.text+=suffix;
        }
        ++s.transcript_revision;modified(s);
        // Streaming uses the passive projection. Keep the raw editor current
        // when it can be shown, avoiding a complete history copy every delta.
        if(s.chat.path.generic_string()==current&&(!s.stream_owned||s.job_status.finished()))fields["wb.chat.text"]=s.chat.text;
        return true;
    }
    BuilderTask* builder_task(Session& s,const std::string& id) {
        const auto found=std::find_if(s.chat.state.builder.tasks.begin(),s.chat.state.builder.tasks.end(),[&](const auto& task){return task.id==id;});
        return found==s.chat.state.builder.tasks.end()?nullptr:&*found;
    }
    BuilderTask& builder_task_candidate(BuilderState& builder,const std::string& id) {
        const auto found=std::find_if(builder.tasks.begin(),builder.tasks.end(),[&](const auto& task){return task.id==id;});if(found==builder.tasks.end())throw std::runtime_error("Builder task record disappeared.");return *found;
    }
    BuilderTask* selected_builder_task() {auto* s=session();return s?builder_task(*s,s->chat.state.builder.selected_task):nullptr;}
    std::size_t builder_size(const BuilderState& builder) {
        json::Value::Object saved;for(const auto& [key,value]:builder.fields)saved[key]=value;json::Value::Array tasks;
        for(const auto& task:builder.tasks)tasks.emplace_back(json::Value::Object{{"id",task.id},{"operation",task.operation},{"status",task.status},{"label",task.label},{"request_json",task.request_json},{"result_json",task.result_json},{"error",task.error},{"phase",task.phase},{"completed_chunks",task.completed_chunks},{"total_chunks",task.total_chunks},{"resumed_chunks",task.resumed_chunks}});
        return json::stringify(json::Value::Object{{"active",builder.active},{"tab",builder.tab},{"selected_task",builder.selected_task},{"fields",std::move(saved)},{"tasks",std::move(tasks)},{"next_task_id",static_cast<std::size_t>(builder.next_task_id)}},8*1024*1024).size();
    }
    void compact_builder_results(BuilderState& builder,std::size_t maximum=1024*1024) {
        for(auto& task:builder.tasks){if(builder_size(builder)<=maximum)return;if(task.result_json=="{}")continue;const auto old=json::parse(task.result_json);auto text=string_field(old,"text");text.resize(std::min(text.size(),std::size_t(1024)));while(!text.empty()&&!foundation::editor::ProjectFiles::valid_utf8(text))text.pop_back();task.result_json=json::stringify(json::Value::Object{{"text",std::move(text)},{"omitted",true}});}
        for(auto& task:builder.tasks){if(builder_size(builder)<=maximum)return;if(task.result_json!="{}")task.result_json="{\"omitted\":true}";}
    }
    void retain_builder_fields() {
        if(auto* s=session()){
            auto candidate=s->chat.state.builder;for(const auto& [key,value]:fields)if(key.starts_with("builder.")&&!key.starts_with("builder.result"))candidate.fields[key]=value;
            try{validate_builder_state(candidate);if(builder_size(candidate)>896*1024)throw std::runtime_error("Setup metadata exceeds the reserved space for builder tasks. Shorten the input or remove an older task record.");}catch(...){for(auto it=fields.begin();it!=fields.end();)if(it->first.starts_with("builder.")&&!it->first.starts_with("builder.result"))it=fields.erase(it);else ++it;for(const auto& [key,value]:s->chat.state.builder.fields)fields[key]=value;throw;}
            s->chat.state.builder.fields=std::move(candidate.fields);modified(*s);
        }
    }
    void builder_progress(Session& s) {
        if(s.job_status.progress_revision)if(auto* task=builder_task(s,s.builder_job_id)){task->phase=s.job_status.progress_phase;task->completed_chunks=s.job_status.completed_chunks;task->total_chunks=s.job_status.total_chunks;task->resumed_chunks=s.job_status.resumed_chunks;modified(s);}
    }
    std::string builder_error(std::string text) {
        text=presentation_text(text,true);text.resize(std::min(text.size(),std::size_t(4096)));while(!text.empty()&&!foundation::editor::ProjectFiles::valid_utf8(text))text.pop_back();return text;
    }
    std::string bounded_builder_result(const JobStatus& job,bool omitted) {
        auto text=job.response?presentation_text(string_field(*job.response,"text"),true):std::string{};text.resize(std::min(text.size(),std::size_t(48*1024)));
        const auto trim_utf8=[&]{while(!text.empty()&&!foundation::editor::ProjectFiles::valid_utf8(text))text.pop_back();};trim_utf8();
        for(;;){const auto encoded=json::stringify(json::Value::Object{{"ok",job.state==ServiceState::succeeded},{"text",text},{"omitted",omitted}});if(encoded.size()<=128*1024)return encoded;text.resize(text.size()/2);trim_utf8();}
    }
    void finish_builder(Session& s) {
        auto* task=builder_task(s,s.builder_job_id);if(!task){s.builder_job_id.clear();return;}
        builder_progress(s);const auto& job=s.job_status;
        if(task->status=="running")task->status=job.state==ServiceState::succeeded?"completed":job.state==ServiceState::cancelled?"cancelled":"failed";
        task->error=builder_error(job.error);
        // A finished worker never retains live task ownership, even when a
        // malformed/oversized metadata envelope or checked save is rejected.
        ++s.builder_action_revision;s.builder_job_id.clear();modified(s);
        try {
            if(job.response){
                const auto fallback=bounded_builder_result(job,true);task->result_json=fallback;
                try{json::Value::Object result;for(const auto* name:{"ok","text","sources","provenance","events","usage","error","error_code","scribble","evaluation"})if(const auto* value=job.response->find(name))result[name]=std::string_view(name)=="sources"?source_metadata(*value):*value;
                    const auto encoded=json::stringify(result,128*1024);const auto task_id=task->id;auto candidate=s.chat.state.builder;builder_task_candidate(candidate,task_id).result_json=encoded;compact_builder_results(candidate);validate_builder_state(candidate);s.chat.state.builder=std::move(candidate);task=builder_task(s,task_id);
                }catch(const std::exception&){task->result_json=fallback;}
            }
            compact_builder_results(s.chat.state.builder);validate_builder_state(s.chat.state.builder);save_state(s);
            if(job.state==ServiceState::failed)failure(s.chat.path.generic_string()+": "+(task->error.empty()?std::string("Builder task failed."):task->error));else success(s.chat.path.generic_string()+": builder task "+task->status+"; settings and results retained.");
        }catch(const std::exception& e){failure(s.chat.path.generic_string()+": "+e.what()+" Builder task retained in memory.");}
    }
    void finish_job(Session& s) {
        if(!s.builder_job_id.empty()){finish_builder(s);return;}
        const auto path=s.chat.path.generic_string();const auto& job=s.job_status;
        const auto* response=job.response?&*job.response:nullptr;
        auto text=response?string_field(*response,"text"):std::string{};
        if(job.state!=ServiceState::succeeded&&text.empty())text=job.partial_text;
        const auto heading=job.state!=ServiceState::succeeded?"Incomplete result":s.operation=="transcribe"?"Transcription":s.operation=="chat"||s.operation=="agent"?"Assistant":"Builder";
        try {replace_reply(s,text,heading);}
        catch(const std::exception& e){failure(path+": "+e.what());s.stream_owned=false;s.stream_conflict=true;s.save_conflict=true;s.save_error=e.what();return;}
        s.stream_owned=false;s.stream_baseline.clear();s.stream_suffix.clear();
        if(response) {
            s.source_report.clear();for(const auto* name:{"sources","provenance","events","usage","transcription"})if(const auto* value=response->find(name)){auto report=json::stringify(std::string_view(name)=="sources"?source_metadata(*value):*value);if(report.size()>512*1024){report.resize(512*1024);while(!report.empty()&&!foundation::editor::ProjectFiles::valid_utf8(report))report.pop_back();report+="\n[Display truncated]";}s.source_report+=std::string(name)+":\n"+report+"\n\n";}
            if(const auto* sources=response->find("sources"))if(std::holds_alternative<json::Value::Array>(sources->data))s.chat.state.sources_json=json::stringify(source_metadata(*sources),1024*1024);
        }
        auto message=path+": "+(job.error.empty()?service_name(job.state):job.error);
        if(!text.empty())message+=" Incomplete output and provenance retained.";
        else if((s.operation=="chat"||s.operation=="agent")&&s.chat.state.submission)message+=" Use Retry previous message to try again.";
        try {
            save_state(s);
            if(job.state==ServiceState::succeeded){
                success(path+": task completed and chat saved.");
            }else if(job.state==ServiceState::cancelled)success(std::move(message));else failure(std::move(message));
        }
        catch(const std::exception& e){failure(path+": "+e.what()+(!text.empty()?" Response retained in the chat buffer.":" Current changes retained in memory."));}
    }
    void cancel_job(Session& s,const std::string& builder_status="cancelled") {if(auto* task=builder_task(s,s.builder_job_id))task->status=builder_status;s.job_status=s.job.cancel();finish_job(s);}
    void refresh_git() {if(auto* s=session())if(!s->git.running())s->git.start(workspace->files().directory(s->chat.path.parent_path().empty()?std::filesystem::path("."):s->chat.path.parent_path()),workspace->root());}
    void start_terminal() {
        auto* s=session();if(!s)throw std::runtime_error("Open a chat before starting its terminal.");
        if(!s->terminal.running()){s->terminal.start(workspace->files().directory(s->chat.state.cwd));s->terminal_identity=++task_identity;s->terminal_status=s->terminal.drain();if(!s->terminal_status.error.empty())throw std::runtime_error(s->terminal_status.error);}
    }
    std::string builder_default_output() const {
        const auto paths=lines(fields.at("builder.paths"));
        const auto path=paths.size()==1?std::filesystem::path(paths.front()).lexically_normal():std::filesystem::path{};
        const auto name=paths.size()==1&&!path.filename().empty()&&path!="."?path.filename().string():paths.size()==1?std::string("project"):std::string("sources");
        return ".zzz_compendium/"+fields.at("builder.kind")+"/"+name;
    }
    void new_builder_setup(bool from_selector=false) {
        auto* s=session();if(!s)throw std::runtime_error("Open a chat to own the builder task.");
        auto path=from_selector?std::filesystem::path("."):directory;if(!from_selector)if(const auto* entry=selected_entry())path=entry->path;
        fields["builder.paths"]=path.generic_string();fields["builder.kind"]=from_selector&&selector_kind=="refs"?"refs":"scribbles";
        fields["builder.default_output"]=fields["builder.output"]=builder_default_output();
        fields["builder.label"]=path=="."?workspace->root().filename().string():path.filename().string();fields["builder.model"].clear();fields["builder.model_choice"].clear();
        fields["builder.small_model"].clear();fields["builder.ai"]="false";fields["builder.web"]="false";fields["builder.evaluation"]="false";fields["builder.kimi_ceiling"]="false";fields["builder.max_calls"]="32";fields["builder.questions"]="What are the main responsibilities of this project?";
        s->chat.state.builder.tab="Setup";retain_builder_fields();++s->builder_setup_revision;++s->builder_action_revision;
    }
    void build_dialog(bool from_selector=false) {
        auto* s=session();if(!s)throw std::runtime_error("Open a chat to own the builder task.");
        if(s->chat.state.builder.fields.empty())new_builder_setup(from_selector);
        s->chat.state.builder.active=true;modal.clear();error=false;modified(*s);save_state(*s);success("Scribble builder opened. Setup and tasks are retained until you explicitly change them.");
    }
    void launch_builder(Session& s,BuilderTask& task,bool resume=false) {
        if(s.job.running())throw std::runtime_error("This chat already has a running task. Pause or finish it before starting another.");
        auto input=json::parse(task.request_json);auto& out=input.object();
        const auto saved_root=std::filesystem::path(string_field(input,"root")).lexically_normal();
        if(string_field(input,"operation")!=task.operation||saved_root!=workspace->root().lexically_normal()||std::filesystem::path(string_field(input,"chat_path")).lexically_normal()!=s.chat.path.lexically_normal())
            throw std::runtime_error("This saved task belongs to another root or chat. Choose New task and build explicitly for this chat.");
        if(task.operation=="scribble"){out["stream"]=true;if(resume)out["scribble"].object()["resume"]=true;}
        auto bounded=s.chat.state.builder;compact_builder_results(bounded,896*1024);if(builder_size(bounded)>896*1024)throw std::runtime_error("Saved task metadata is full. Remove a task record before starting or resuming work.");validate_builder_state(bounded);for(auto& retained:s.chat.state.builder.tasks)retained.result_json=builder_task_candidate(bounded,retained.id).result_json;
        // Flush the immutable snapshot and edited setup before any worker can run.
        const auto previous_status=task.status;task.status="running";task.error.clear();if(!resume){task.phase.clear();task.completed_chunks=task.total_chunks=task.resumed_chunks=0;task.result_json="{}";}s.chat.state.builder.selected_task=task.id;s.chat.state.builder.tab="Tasks";modified(s);
        try{save_state(s);}catch(const std::exception& e){task.status=previous_status;task.error=builder_error("Task did not start: "+std::string(e.what()));++s.builder_action_revision;modified(s);throw;}
        try{s.job.start(input,workspace->root());}catch(const std::exception& e){task.status="failed";task.error=builder_error(e.what());++s.builder_action_revision;modified(s);try{save_state(s);}catch(...){}throw;}
        s.builder_job_id=task.id;s.job_identity=++task_identity;++s.send_revision;++s.builder_action_revision;s.job_status={ServiceState::running,-1,{}, {},{},false,0};s.operation=task.operation;
        success(resume?"Resume requested; Tasks shows progress after the saved checkpoint is validated.":task.operation=="evaluate"?"Comprehension evaluation started.":"Scribble builder started. Tasks shows progress; Exit keeps it running.");
    }
    std::string next_builder_task_id(Session& s) {
        constexpr std::uint64_t maximum=9007199254740991ULL;
        auto& next=s.chat.state.builder.next_task_id;
        if(!next||next>maximum)throw std::runtime_error("Builder task ID limit reached. Open another chat for new tasks.");
        while(builder_task(s,"builder-"+std::to_string(next))){if(next==maximum)throw std::runtime_error("Builder task ID limit reached. Open another chat for new tasks.");++next;}
        const auto id="builder-"+std::to_string(next);if(next<maximum)++next;return id;
    }
    void run_builder(bool evaluate=false) {
        auto* s=session();if(!s||s->job.running())throw std::runtime_error("Wait for the chat's running task, or pause it first.");
        if(s->chat.state.builder.tasks.size()>=32)throw std::runtime_error("This chat retains 32 builder tasks. Remove a task record or open another chat for additional tasks.");
        const bool ai_enabled=fields["builder.ai"]=="true",uses_ai=evaluate||ai_enabled,uses_research=ai_enabled&&!evaluate&&fields["builder.web"]=="true";
        const auto& selector=s->chat.state.selector;const auto context_bytes=static_cast<std::size_t>(selector.context_max_kib)*1024;
        json::Value input=json::Value::Object{{"schema_version",1},{"operation",evaluate?"evaluate":"scribble"},{"root",workspace->root().string()},{"chat_path",s->chat.path.generic_string()},{"prompt",std::string{}},
            {"selector",json::Value::Object{{"deep_research",uses_research},{"calculations",false},{"scribbles",json::Value::Array{}},{"refs",json::Value::Array{}},{"tools",json::Value::Array{}}}},
            {"allowed_context_paths",json::Value::Array{}},{"context_limits",json::Value::Object{{"max_total_bytes",context_bytes},{"max_file_bytes",std::min(context_bytes,std::size_t(4*1024*1024))},{"max_files",128}}},{"research_source",selector.research_source}};
        auto& out=input.object();
        if(uses_research&&selector.research_source=="local"){json::Value::Array paths;for(const auto* list:{&selector.scribbles,&selector.refs})for(const auto& value:*list)if(value.enabled){paths.emplace_back(value.path);if(std::filesystem::path(value.path).is_absolute())out["allowed_context_paths"].array().emplace_back(value.path);}out["research_paths"]=std::move(paths);}
        if(uses_research&&selector.research_source=="kiwix"&&!selector.kiwix_index.empty()){out["kiwix_index"]=selector.kiwix_index;if(std::filesystem::path(selector.kiwix_index).is_absolute())out["allowed_context_paths"].array().emplace_back(selector.kiwix_index);}
        json::Value::Array paths;if(!evaluate)for(const auto& path:lines(fields["builder.paths"])){paths.emplace_back(path);if(std::filesystem::path(path).is_absolute())out["allowed_context_paths"].array().emplace_back(path);}
        if(!evaluate&&paths.empty())throw std::runtime_error("Add at least one input path.");
        if(!evaluate)out["input_paths"]=std::move(paths);
        out["output_dir"]=trim(fields["builder.output"]);
        auto settings=s->chat.state.ai;if(settings.provider!="openrouter"||(!settings.endpoint.empty()&&settings.endpoint!="https://openrouter.ai/api/v1"))settings.endpoint.clear();settings.provider="openrouter";settings.routing_providers.clear();settings.model=uses_ai?trim(fields[evaluate?"builder.small_model":"builder.model"]):std::string{};settings.web_search=false;
        if(uses_ai){if(settings.model.empty())throw std::runtime_error(evaluate?"Choose a small model for comprehension evaluation.":"Choose a Scribble model before building AI annotations.");validate_submission_model(settings);if(model_search_text(settings.model).starts_with("openai/"))throw std::runtime_error("OpenAI models are not allowed for Scribble generation or evaluation.");}
        out["settings"]=settings_json(settings);if(!uses_ai)out["settings"].object()["network_enabled"]=false;
        if(uses_ai&&settings.model=="moonshotai/kimi-k3"){if(fields["builder.kimi_ceiling"]!="true")throw std::runtime_error("Kimi K3 needs the explicit higher price ceiling. Choose a lower cost model or enable the $20/M ceiling.");out["settings"].object()["max_price_per_million"]=20.0;}
        out["scribble"]=json::Value::Object{{"ai_enabled",ai_enabled},{"label",fields["builder.label"]},{"max_provider_calls",ai_enabled&&!evaluate?integer(fields["builder.max_calls"],1,4096):32}};
        out["research_limits"]=json::Value::Object{{"max_queries",2},{"max_results",3}};
        if(uses_research)out["research_queries"]=json::Value::Array{fields["builder.label"].empty()?std::string("Linux manual documentation"):fields["builder.label"]};
        if(evaluate){json::Value::Array questions;for(auto& question:lines(fields["builder.questions"]))questions.emplace_back(std::move(question));out["questions"]=std::move(questions);}
        retain_builder_fields();BuilderTask task;task.id=next_builder_task_id(*s);task.operation=evaluate?"evaluate":"scribble";task.label=fields["builder.label"].empty()?fields["builder.output"]:fields["builder.label"];task.request_json=json::stringify(input,64*1024);auto candidate=s->chat.state.builder;candidate.tasks.push_back(std::move(task));compact_builder_results(candidate,896*1024);if(builder_size(candidate)>896*1024)throw std::runtime_error("Saved task metadata is full. Remove a task record or open another chat before building.");validate_builder_state(candidate);s->chat.state.builder=std::move(candidate);
        launch_builder(*s,s->chat.state.builder.tasks.back());
    }
    void builder_task_action(std::string_view action) {
        auto* s=session();auto* task=selected_builder_task();if(!s||!task)throw std::runtime_error("Select a builder task first.");
        if(action=="remove"){if(task->status=="running"||s->builder_job_id==task->id)throw std::runtime_error("Pause or finish this task before removing its record.");const auto id=task->id;auto& builder=s->chat.state.builder;builder.tasks.erase(std::remove_if(builder.tasks.begin(),builder.tasks.end(),[&](const auto& value){return value.id==id;}),builder.tasks.end());builder.selected_task=builder.tasks.empty()?std::string{}:builder.tasks.back().id;++s->builder_action_revision;modified(*s);save_state(*s);success("Task record removed; output and checkpoint files retained.");return;}
        if(action=="show"){s->chat.state.builder.tab="Results";modified(*s);++s->builder_action_revision;return;}
        if(action=="pause"||action=="cancel"){if(s->builder_job_id!=task->id||!s->job.running())throw std::runtime_error("This task is not running.");cancel_job(*s,action=="pause"&&task->operation=="scribble"?"paused":"cancelled");return;}
        if(action=="resume"){
#if defined(_WIN32)
            if(task->status!="ready")throw std::runtime_error("Durable Scribble Resume is unavailable on Windows; create a new task with a fresh output directory.");
#endif
            if(task->operation!="scribble"||(task->status!="ready"&&task->status!="paused"&&task->status!="interrupted"&&task->status!="failed"))throw std::runtime_error("Select a paused or interrupted Scribble build to resume.");
            launch_builder(*s,*task,task->status!="ready");return;}
        if(action=="retry"){if(task->operation!="evaluate"||task->status=="running")throw std::runtime_error("Select a completed or interrupted evaluation to retry explicitly.");if(s->chat.state.builder.tasks.size()>=32)throw std::runtime_error("This chat retains 32 builder tasks.");auto retry=*task;retry.id=next_builder_task_id(*s);retry.status="ready";auto candidate=s->chat.state.builder;candidate.tasks.push_back(std::move(retry));compact_builder_results(candidate,896*1024);if(builder_size(candidate)>896*1024)throw std::runtime_error("Saved task metadata is full. Remove a task record or open another chat before retrying.");validate_builder_state(candidate);s->chat.state.builder=std::move(candidate);launch_builder(*s,s->chat.state.builder.tasks.back());return;}
        if(task->operation!="scribble"||task->status!="completed")throw std::runtime_error("Select a completed Scribble build first.");
        const auto request=json::parse(task->request_json);const auto path=string_field(request,"output_dir");if(path.empty())throw std::runtime_error("This retained task has no output directory.");
        if(action=="open"){file_buffer=std::make_unique<foundation::editor::CodeBuffer>(workspace->files().read((std::filesystem::path(path).is_absolute()?std::filesystem::path(path).lexically_relative(workspace->root()):std::filesystem::path(path)).lexically_normal()/"scribbles.md"));fields["file.text"]=file_buffer->text();++file_edit_revision;modal="file";return;}
        auto& list=action=="refs"?s->chat.state.selector.refs:s->chat.state.selector.scribbles;auto found=std::find_if(list.begin(),list.end(),[&](const auto& value){return value.path==path;});if(found==list.end())list.push_back({path,true});else found->enabled=true;modified(*s);save_state(*s);success("Output directory enabled in Selector's "+std::string(action=="refs"?"Refs":"Scribbles")+" list.");
    }
    void transcription_dialog() {
        const auto* entry=selected_entry();if(!entry||entry->directory||entry->symlink)throw std::runtime_error("Select an ordinary WAV audio file first.");
        if(!session())throw std::runtime_error("Open a chat to own the transcription task.");
        const auto parent=entry->path.parent_path();
        fields["transcription.media"]=(workspace->files().directory(parent.empty()?std::filesystem::path("."):parent)/entry->path.filename()).string();fields["transcription.executable"]="";fields["transcription.model"]="";fields["transcription.threads"]="2";fields["transcription.timeout"]="120";modal="transcription";
    }
    void transcribe() {
        auto* s=session();if(!s||s->job.running())throw std::runtime_error("Wait for the chat's task or cancel it first.");
        for(const auto* field:{"transcription.media","transcription.executable","transcription.model"})if(!std::filesystem::path(trim(fields[field])).is_absolute())throw std::runtime_error("Enter absolute paths for the WAV file, whisper-cli executable and model.");
        json::Value input=json::Value::Object{{"schema_version",1},{"operation","transcribe"},{"root",workspace->root().string()},{"chat_path",s->chat.path.generic_string()},
            {"media_path",trim(fields["transcription.media"])},{"transcription",json::Value::Object{{"executable",trim(fields["transcription.executable"])},{"model_path",trim(fields["transcription.model"])},{"timeout_seconds",integer(fields["transcription.timeout"],1,600)},{"threads",integer(fields["transcription.threads"],1,32)}}}};
        s->job.start(input,workspace->root());s->job_identity=++task_identity;++s->send_revision;s->job_status={ServiceState::running,-1,{}, {},{},false,0};s->operation="transcribe";modal.clear();success("Local WAV transcription started.");
    }
    void select_node(std::uint64_t id) {
        auto* s=session();if(!s||!s->flow.parsed().program)return;
        const auto* node=find_node(s->flow.parsed().program->nodes,id);if(!node)return;s->selected_node=id;
        fields["node.kind"]=node->kind==FlowKind::branch?"branch":flow_kind_name(node->kind);fields["node.role"]=node->role;fields["node.text"]=node->text;
        fields["node.iterations"]=std::to_string(node->iterations);fields["node.condition"]=flow_condition_name(node->condition);
        if(auto location=locate(s->flow.parsed().program->nodes,id)){fields["node.parent"]=std::to_string(location->parent);fields["node.index"]=std::to_string(location->index);fields["node.otherwise"]=location->otherwise?"true":"false";}
    }
    FlowNode edited_node() {
        FlowNode node;const auto kind=fields["node.kind"];
        node.kind=kind=="critique"?FlowKind::critique:kind=="repeat"?FlowKind::repeat:kind=="branch"?FlowKind::branch:kind=="conclude"?FlowKind::conclude:FlowKind::agent;
        if(node.kind==FlowKind::agent||node.kind==FlowKind::critique){node.role=trim(fields["node.role"]);if(node.role.empty())node.role=node.kind==FlowKind::critique?"reviewer":"writer";node.text=fields["node.text"];}
        else if(node.kind==FlowKind::conclude)node.text=fields["node.text"];
        if(node.kind==FlowKind::repeat)node.iterations=integer(trim(fields["node.iterations"]).empty()?"3":trim(fields["node.iterations"]),1,1000);
        if(node.kind==FlowKind::repeat||node.kind==FlowKind::branch)node.condition=fields["node.condition"]=="supported"?FlowCondition::supported:fields["node.condition"]=="rejected"?FlowCondition::rejected:FlowCondition::approved;
        return node;
    }
    void flow_edit(std::string_view action) {
        auto* s=session();if(!s||!s->flow.parsed())throw std::runtime_error("Repair the pseudocode text before graphical editing.");
        const auto previous_source=s->flow.text(),edited_kind=fields["node.kind"];const auto selected=s->selected_node;
        FlowEdit edit;edit.node_id=s->selected_node;
        if(action=="add") {
            edit.kind=FlowEditKind::insert;edit.node=edited_node();edit.parent_id=integer(fields["node.parent"].empty()?"0":fields["node.parent"],0,1000000);
            edit.index=integer(fields["node.index"].empty()?std::to_string(s->flow.parsed().program->nodes.size()):fields["node.index"],0,2048);edit.otherwise=fields["node.otherwise"]=="true";
        }else if(action=="delete")edit.kind=FlowEditKind::erase;
        else if(action=="move"){edit.kind=FlowEditKind::move;edit.parent_id=integer(fields["node.parent"],0,1000000);edit.index=integer(fields["node.index"],0,2048);edit.otherwise=fields["node.otherwise"]=="true";}
        else {edit.kind=FlowEditKind::update;edit.node=edited_node();if(auto* old=find_node(s->flow.parsed().program->nodes,s->selected_node)){edit.node.children=old->children;edit.node.otherwise=old->otherwise;}}
        std::string failure_text;if(!s->flow.apply(edit,s->flow.revision(),failure_text))throw std::runtime_error(failure_text);
        // Preserve one composer/source undo step for graphical commands.
        const auto updated=s->flow.text();s->flow.set_text(previous_source);set_flow(*s,updated);
        if(action=="delete"||action=="move"||action=="add"){reset_node_fields();fields["node.kind"]=edited_kind;}else select_node(selected);
        success("Pseudocode updated.");
    }
    std::vector<Snippet>& snippets() {return snippet_kind=="Prompts"?prompt_snippets:flow_snippets;}
    bool tutorial_enabled() const {return preferences&&preferences->tutorial_mode();}
    void load_snippet(const std::string& id) {const auto load=[&](const auto& items){for(const auto& snippet:items)if(snippet.id==id){snippet_id=id;fields["snippet.title"]=snippet.title;fields["snippet.text"]=snippet.text;return true;}return false;};if(load(snippets()))return;if(snippet_kind=="Pseudocode"&&tutorial_enabled())load(tutorial_snippets);}
    void save_snippet() {
        auto& items=snippets();if(trim(fields["snippet.title"]).empty())throw std::runtime_error("Give the snippet a title.");
        if(snippet_id.empty()||std::none_of(items.begin(),items.end(),[&](const auto& item){return item.id==snippet_id;})){std::size_t serial=items.size()+1;do{snippet_id="snippet."+std::to_string(serial++);}while(std::any_of(items.begin(),items.end(),[&](const auto& item){return item.id==snippet_id;}));items.push_back({snippet_id,fields["snippet.title"],fields["snippet.text"]});}
        else for(auto& item:items)if(item.id==snippet_id){item.title=fields["snippet.title"];item.text=fields["snippet.text"];}
        workspace->save_snippets(snippet_kind,items);success("Snippet saved.");
    }
    void insert_snippet() {
        auto* s=session();if(!s)throw std::runtime_error("Open a chat to insert a snippet.");
        const auto text=fields["snippet.text"];if(text.empty())throw std::runtime_error("Choose or write a snippet first.");
        const auto insert=[&](std::string source,const std::string& widget_id){if(auto it=lives.find(widget_id);it!=lives.end()&&it->second.active){const auto selection=adapter.text_selection(it->second.spec.key).clamped(source);const auto begin=std::min(selection.anchor,selection.caret),end=std::max(selection.anchor,selection.caret);source.replace(begin,end-begin,text);}else {if(!source.empty()&&source.back()!='\n')source+='\n';source+=text;}return source;};
        if(snippet_kind=="Pseudocode")set_flow(*s,insert(s->flow.text(),"wb.flow.text"));
        else set_draft(*s,insert(s->chat.state.draft,"wb.composer"));
        success("Snippet inserted.");
    }
    bool task_exists(const TaskTarget& task) const {
        if(task.kind==TaskKind::models)return task.identity==model_identity&&model_status.state!=ServiceState::idle;
        if(task.kind==TaskKind::guardrail)return task.identity==guardrail_identity&&guardrail_status.state!=ServiceState::idle;
        const auto found=sessions.find(task.path);if(found==sessions.end())return false;const auto& s=*found->second;
        return task.kind==TaskKind::job?task.identity==s.job_identity&&s.job_status.state!=ServiceState::idle:task.identity==s.terminal_identity&&s.terminal.running();
    }
    bool task_running(const TaskTarget& task) const {
        if(!task_exists(task))return false;
        if(task.kind==TaskKind::models)return model_job->running();
        if(task.kind==TaskKind::guardrail)return guardrail_job.running();
        const auto& s=*sessions.at(task.path);return task.kind==TaskKind::job?s.job.running():s.terminal.running();
    }
    std::optional<TaskTarget> selected_task_target() const {const auto found=task_targets.find(selected_task);return found==task_targets.end()?std::nullopt:std::optional<TaskTarget>{found->second};}
    void task_action(bool cancel,bool context) {
        const auto target=context?context_task:selected_task_target();if(!target||!task_exists(*target))throw std::runtime_error("This task is no longer available. Select a current task.");
        if(cancel) {
            if(!task_running(*target))throw std::runtime_error("This task has already finished.");
            if(target->kind==TaskKind::models){model_status=model_job->cancel();success("Model refresh cancelled.");}
            else if(target->kind==TaskKind::guardrail){guardrail_status=guardrail_job.cancel();success("Guardrail request cancelled. Load status before changing it.");}
            else {auto& s=*sessions.at(target->path);if(target->kind==TaskKind::job)cancel_job(s);else {s.terminal.shutdown();s.terminal_status=s.terminal.drain();success(target->path+": terminal stopped.");}}
        }else {
            if(target->kind==TaskKind::models||target->kind==TaskKind::guardrail)show_ai();
            else {open_chat(target->path);state().left_tab="Running Tasks";state().center_tab=target->kind==TaskKind::terminal?"Bash Terminal":"Chat Markdown";if(auto* s=session()){if(target->kind==TaskKind::job&&(s->operation=="scribble"||s->operation=="evaluate")){s->chat.state.builder.active=true;s->chat.state.builder.tab="Tasks";}modified(*s);}}
        }
        modal.clear();context_task.reset();++task_action_revision;
    }
    void task_context(gui::Point position,const gui::WidgetKey& key) {
        const auto* widget=gui::find_widget(view,key);if(!widget)return;const auto offset=adapter.scroll_offset(key);
        const auto row=static_cast<std::size_t>(std::max(0.0,position.y-widget->state.bounds.y+offset.y)/28);
        if(row>=widget->state.records.size())return;
        const auto id=widget->state.records[row].id;
        const auto found=task_targets.find(id);if(found==task_targets.end())return;
        selected_task=id;context_task=found->second;modal="task-actions";++task_action_revision;
    }
    void action(std::string_view id) {
        auto* owner=session();const auto before=state();const auto saves=owner?owner->save_serial:0;
        if(id.starts_with("tab.left.")){state().left_tab=std::string(id.substr(9));if(state().left_tab=="Files")refresh_tree();if(state().left_tab=="Filelight")usage=workspace->disk_usage(directory);}
        else if(id.starts_with("tab.center.")){state().center_tab=std::string(id.substr(11));if(state().center_tab=="Bash Terminal")start_terminal();}
        else if(id.starts_with("tab.right.")){state().right_tab=std::string(id.substr(10));if(state().right_tab=="Git")refresh_git();snippet_kind=state().right_tab=="Pseudocode"?"Pseudocode":"Prompts";snippet_id.clear();}
        else if(id=="wb.new")prompt("new","New .chat.md conversation","new-chat.chat.md");
        else if(id=="wb.open")prompt("open","Open .chat.md conversation");
        else if(id=="wb.refresh")refresh();
        else if(id=="wb.up"){const auto parent=directory.parent_path();browse(parent.empty()?std::filesystem::path("."):parent);}
        else if(id=="wb.back"){if(!back.empty()){const auto path=back.back();back.pop_back();browse(path,false);}}
        else if(id=="wb.file.open"||id=="actions.open"){open_file();if(modal=="actions")modal.clear();}
        else if(id=="wb.file.actions")modal="actions";
        else if(id=="wb.image.attach")choose_image();
        else if(id=="actions.attach-image"){const auto* entry=selected_entry();if(!entry||entry->directory||entry->symlink)throw std::runtime_error("Select a local PNG or JPEG file first.");attach_image(entry->path);modal.clear();}
        else if(id.starts_with("wb.image.remove."))remove_image(id.substr(16));
        else if(id=="actions.create-file")prompt("create-file","Create a file",(creation_directory()/"new-file.txt").lexically_normal().generic_string());
        else if(id=="actions.create-directory")prompt("create-directory","Create an empty folder",(creation_directory()/"new-folder").lexically_normal().generic_string());
        else if(id=="actions.copy"||id=="actions.copy-retained") {
            const auto* entry=selected_entry();if(!entry||entry->directory||entry->symlink)throw std::runtime_error("Select an ordinary file to copy.");
            const auto found=sessions.find(entry->path.generic_string());
            if(id=="actions.copy-retained"&&(found==sessions.end()||!found->second->save_conflict))throw std::runtime_error("This chat has no retained autosave conflict.");
            if(id=="actions.copy"&&found!=sessions.end()&&(found->second->save_due||found->second->chat.text!=found->second->chat.original.text))save_state(*found->second);
            operation_path=entry->path;auto name=entry->path.filename().string();if(Workspace::is_chat_path(entry->path))name=name.substr(0,name.size()-8)+"-copy.chat.md";else name=entry->path.stem().string()+"-copy"+entry->path.extension().string();
            prompt(id=="actions.copy-retained"?"copy-retained":"copy-file",id=="actions.copy-retained"?"Copy retained chat and draft":"Copy text file",(entry->path.parent_path()/name).generic_string());
        }
        else if(id=="actions.discard-retained"){operation_path=std::filesystem::path(selected_file);modal="discard-retained";error=false;}
        else if(id=="discard-retained.accept")discard_retained_chat();
        else if(id=="actions.rename")entry_operation(false);
        else if(id=="actions.delete")entry_operation(true);
        else if(id=="delete.accept")mutate_entry();
        else if(id=="wb.file.cd"){const auto* entry=selected_entry();const auto path=entry?(entry->directory?entry->path:entry->path.parent_path()):directory;state().cwd=path.empty()?".":path.generic_string();start_terminal();session()->terminal.send("cd -- "+quote_shell(workspace->files().directory(state().cwd).string()));state().center_tab="Bash Terminal";modal.clear();}
        else if(id=="wb.file.scribble"||id=="wb.files.builder")build_dialog();
        else if(id=="selector.builder")build_dialog(true);
        else if(id=="wb.file.transcribe")transcription_dialog();
        else if(id=="wb.send")send();
        else if(id=="wb.retry")send(true);
        else if(id=="wb.task.cancel"||id=="task.cancel")task_action(true,id=="task.cancel");
        else if(id=="wb.task.show"||id=="task.show")task_action(false,id=="task.show");
        else if(id=="wb.cancel"){if(auto* s=session())if(s->job.running())cancel_job(*s);}
        else if(id=="wb.terminal.start")start_terminal();
        else if(id=="wb.terminal.send"){start_terminal();auto* s=session();s->terminal.send(s->terminal_command);s->terminal_command.clear();fields["wb.terminal.command"].clear();}
        else if(id=="wb.terminal.interrupt"){if(auto* s=session())s->terminal.interrupt();}
        else if(id=="wb.terminal.stop"){if(auto* s=session()){s->terminal.shutdown();s->terminal_status=s->terminal.drain();success("Chat terminal stopped.");}}
        else if(id=="wb.git.refresh")refresh_git();
        else if(id=="ai.apply")apply_ai();
        else if(id=="ai.key.save")save_key();
        else if(id=="ai.key.remove")remove_key();
        else if(id=="ai.models.add")add_configured_model();
        else if(id=="ai.models.remove")remove_configured_model();
        else if(id=="ai.models.refresh")refresh_models();
        else if(id=="ai.models.filter.clear")fields["ai.models.filter"].clear();
        else if(id=="ai.models.cancel"){if(model_job->running()){model_status=model_job->cancel();success("Model refresh cancelled.");}}
        else if(id=="ai.guardrail.load")run_guardrail(false);
        else if(id=="ai.guardrail.apply")run_guardrail(true);
        else if(id=="ai.guardrail.cancel"){if(guardrail_job.running()){guardrail_status=guardrail_job.cancel();success("Guardrail request cancelled. Load status before making another change.");}}
        else if(id=="selector.add") {const auto path=trim(fields["selector.path"]);if(path.empty())throw std::runtime_error("Enter a path.");auto& list=path_list();if(std::any_of(list.begin(),list.end(),[&](const auto& value){return value.path==path;}))throw std::runtime_error("This path is already in the list.");list.push_back({path,true});fields["selector.path"].clear();}
        else if(id=="selector.toggle"){for(auto& value:path_list())if(value.path==selector_selected)value.enabled=!value.enabled;}
        else if(id=="selector.remove"){auto& list=path_list();list.erase(std::remove_if(list.begin(),list.end(),[&](const auto& value){return value.path==selector_selected;}),list.end());selector_selected.clear();}
        else if(id=="selector.save"){auto updated=state().selector;updated.research_max_queries=static_cast<int>(integer(fields["research.max_queries"],1,1000));updated.research_max_results=static_cast<int>(integer(fields["research.max_results"],1,3000));updated.kiwix_index=trim(fields["research.kiwix_index"]);updated.context_max_kib=static_cast<int>(integer(fields["selector.context_kib"],1,16384));state().selector=std::move(updated);if(auto* s=session())save_state(*s);success("Selector settings saved.");}
        else if(id=="flow.add"||id=="flow.apply"||id=="flow.delete"||id=="flow.move")flow_edit(id.substr(5));
        else if(id=="flow.zoom.in")graph.set_view(std::min(2.0,graph.zoom()*1.25),graph.pan());
        else if(id=="flow.zoom.out")graph.set_view(std::max(.2,graph.zoom()/1.25),graph.pan());
        else if(id=="flow.pan.down"){auto point=graph.pan();point.y=std::clamp(point.y+160,-gui::coordinate_limit,gui::coordinate_limit);graph.set_view(graph.zoom(),point);}
        else if(id=="flow.pan.up"){auto point=graph.pan();point.y=std::clamp(point.y-160,-gui::coordinate_limit,gui::coordinate_limit);graph.set_view(graph.zoom(),point);}
        else if(id=="flow.pan.left"){auto point=graph.pan();point.x=std::clamp(point.x-160,-gui::coordinate_limit,gui::coordinate_limit);graph.set_view(graph.zoom(),point);}
        else if(id=="flow.pan.right"){auto point=graph.pan();point.x=std::clamp(point.x+160,-gui::coordinate_limit,gui::coordinate_limit);graph.set_view(graph.zoom(),point);}
        else if(id=="flow.reset")graph.reset_view();
        else if(id=="flow.drag.cancel"){cancel_flow_drag();return;}
        else if(id=="snippet.new"){snippet_id.clear();fields["snippet.title"].clear();fields["snippet.text"].clear();}
        else if(id=="snippet.save")save_snippet();
        else if(id=="snippet.insert")insert_snippet();
        else if(id=="snippet.delete"){auto& items=snippets();items.erase(std::remove_if(items.begin(),items.end(),[&](const auto& item){return item.id==snippet_id;}),items.end());workspace->save_snippets(snippet_kind,items);snippet_id.clear();fields["snippet.title"].clear();fields["snippet.text"].clear();}
        else if(id=="prompt.accept")accept_prompt();
        else if(id=="modal.cancel"||id=="prompt.cancel"){modal.clear();context_task.reset();}
        else if(id.starts_with("tab.builder.")){state().builder.tab=std::string(id.substr(12));if(owner)++owner->builder_action_revision;}
        else if(id=="builder.exit"){state().builder.active=false;if(owner){++owner->builder_action_revision;modified(*owner);save_state(*owner);}success("Exited Scribble builder; setup, task records and running work retained.");}
        else if(id=="builder.new"){new_builder_setup();success("New task setup opened. Retained tasks are available in Tasks.");}
        else if(id.starts_with("builder.task."))builder_task_action(id.substr(13));
        else if(id=="builder.run")run_builder();
        else if(id=="builder.evaluate")run_builder(true);
        else if(id=="transcription.run")transcribe();
        else if(id=="file.save"){file_buffer->save(workspace->files());success("File saved.");}
        else if(id=="file.close"){if(file_buffer->dirty())throw std::runtime_error("Save changes or choose Discard before closing.");file_buffer.reset();modal.clear();}
        else if(id=="file.discard"){file_buffer.reset();modal.clear();success("File buffer discarded.");}
        else if(id=="file.undo"){(void)file_buffer->undo();fields["file.text"]=file_buffer->text();++file_edit_revision;}
        else if(id=="file.redo"){(void)file_buffer->redo();fields["file.text"]=file_buffer->text();++file_edit_revision;}
        if(auto* s=session()){if(s==owner&&s->save_serial==saves&&s->chat.state!=before)modified(*s);s->typing_field.clear();}
        ++epoch;
    }

    gui::Widget& add(gui::Kind kind,std::string id,std::string text,gui::Rect bounds,std::string parent="wb.root") {
        gui::Widget widget;widget.spec.key={std::move(id),revision};widget.spec.kind=kind;widget.spec.parent=std::move(parent);
        widget.state.bounds=bounds;widget.state.label=presentation_text(text);widget.state.accessible_name=widget.state.label;widget.state.font.size=13;
        if(kind==gui::Kind::label)widget.state.text=presentation_text(text,true);
        view.widgets.push_back(std::move(widget));return view.widgets.back();
    }
    gui::Widget& button(std::string id,std::string text,gui::Rect area,std::string parent="wb.root") {return add(gui::Kind::button,std::move(id),std::move(text),area,std::move(parent));}
    gui::Widget& label(std::string id,std::string text,gui::Rect area,std::string parent="wb.root") {auto& widget=add(gui::Kind::label,std::move(id),std::move(text),area,std::move(parent));widget.state.wrap=gui::TextWrap::word;return widget;}
    gui::Widget& input(std::string id,std::string name,gui::Rect area,bool multi=false,bool read_only=false,std::string parent="wb.root") {
        auto& widget=add(gui::Kind::text,id,std::move(name),area,std::move(parent));widget.state.text=presentation_text(fields[id],multi);widget.spec.text_policy={multi,read_only,multi?8U*1024U*1024U:4096U,multi?gui::SubmitKey::none:gui::SubmitKey::enter};widget.state.wrap=multi?gui::TextWrap::word:gui::TextWrap::none;return widget;
    }
    gui::Widget& choice(std::string id,std::string title,gui::Rect area,const std::vector<std::pair<std::string,std::string>>& values,const std::string& selected,std::string parent="wb.root") {
        auto& widget=add(gui::Kind::choice,std::move(id),std::move(title),area,std::move(parent));for(const auto& [key,text]:values)widget.state.options.push_back({record_id(key),presentation_text(text),record_id(key),true});if(!selected.empty()&&std::any_of(values.begin(),values.end(),[&](const auto& value){return value.first==selected;}))widget.state.selected=record_id(selected);return widget;
    }
    void bool_choice(std::string id,std::string name,gui::Rect area,bool value,std::string parent="wb.root") {choice(std::move(id),std::move(name),area,{{"false","Off"},{"true","On"}},value?"true":"false",std::move(parent));}
    gui::Widget& checkbox(std::string id,std::string name,gui::Rect area,bool value,std::string parent="wb.root") {auto& widget=add(gui::Kind::toggle,std::move(id),std::move(name),area,std::move(parent));widget.state.checked=value;return widget;}
    gui::Widget& list(std::string id,std::string title,gui::Rect area,const std::vector<std::pair<std::string,std::string>>& rows,std::string selected={},std::string parent="wb.root") {
        auto& widget=add(gui::Kind::list,std::move(id),std::move(title),area,std::move(parent));for(const auto& [key,text]:rows){gui::Record record;record.id=record_id(key);record.accessible_text=presentation_text(text);record.activatable=true;record.cells={{record.accessible_text,{5,0,std::max(1.0,area.width-10),28},{}}};widget.state.records.push_back(std::move(record));}
        widget.state.content_size={area.width,rows.size()*28.0};if(!selected.empty())widget.state.selected=record_id(selected);return widget;
    }
    void tabs(std::string prefix,const std::vector<std::string>& names,gui::Rect area,const std::string& selected,std::string parent) {
        double total{};for(const auto& name:names)total+=name.size()+4;
        double x=area.x;for(const auto& name:names){const auto width=area.width*(name.size()+4)/total;auto& tab=button(prefix+name,name,{x,area.y,width,31},parent);if(name==selected)tab.state.font.tone=gui::Tone::accent;x+=width;}
    }
    void pane(std::string id,gui::Rect area) {auto& widget=add(gui::Kind::group,std::move(id),"",area);widget.state.content_size={area.width,area.height};}
    void draw_left(gui::Rect area) {
        pane("wb.left",area);tabs("tab.left.",{"Chats","Files","Filelight","Running Tasks"},{area.x,area.y,area.width,31},state().left_tab,"wb.left");
        const auto x=area.x+8,w=area.width-16;double y=area.y+40;const auto bottom=area.y+area.height-8;
        if(state().left_tab=="Chats") {
            button("wb.new","New",{x,y,58,28},"wb.left");button("wb.open","Open",{x+62,y,58,28},"wb.left");button("wb.refresh","Refresh",{x+124,y,w-124,28},"wb.left");y+=36;
            std::vector<std::pair<std::string,std::string>> rows;for(const auto& path:chat_paths){const auto key=path.generic_string();auto text=key;if(auto it=sessions.find(key);it!=sessions.end()){if(it->second->job.running())text="● "+text;if(it->second->chat.text!=it->second->chat.original.text)text+=" *";}rows.push_back({key,text});}
            list("wb.chats","Project chats",{x,y,w,bottom-y},rows,current,"wb.left");
        }else if(state().left_tab=="Files"||state().left_tab=="Filelight") {
            button("wb.up","Up",{x,y,48,28},"wb.left");button("wb.back","Back",{x+52,y,52,28},"wb.left");input("wb.path","Project directory",{x+110,y,w-110,28},false,false,"wb.left");y+=36;
            if(state().left_tab=="Files") {
                std::vector<std::pair<std::string,std::string>> rows;for(std::size_t i=0;i<tree.size();++i){const auto& entry=tree[i];rows.push_back({entry.path.generic_string(),std::string(tree_rows[i].second*2,' ')+(entry.directory?(expanded.contains(entry.path.generic_string())?"▾ ":"▸ "):"  ")+entry.name+(entry.symlink?" [link]":"")});}
                auto& files=list("wb.files","Folder tree",{x,y,w,std::max(32.0,bottom-y-71)},rows,selected_file,"wb.left");files.spec.context_input=true;
                auto& builder=button("wb.files.builder","Build Scribble / Ref…",{x,bottom-63,w,28},"wb.left");builder.state.enabled=session()&&(!selected_entry()||!selected_entry()->symlink);builder.state.help=session()?"Build from the selected file or folder, or this directory. Enter the Scribble builder workspace; choose local indexing or AI explicitly.":"Choose or open a chat to own the builder task.";
                button("wb.file.open","Open",{x,bottom-28,w*.45,28},"wb.left");button("wb.file.actions","Actions…",{x+w*.45+4,bottom-28,w*.55-4,28},"wb.left");
            }else {std::vector<DiskSector> entries;for(const auto& entry:usage.entries)entries.push_back({entry.path.generic_string(),entry.bytes,entry.directory});auto rendered=disk.render(entries,{x,y,w,std::max(32.0,bottom-y)},selected_file);view.widgets.insert(view.widgets.end(),std::make_move_iterator(rendered.begin()),std::make_move_iterator(rendered.end()));}
        }else {
            std::vector<std::pair<std::string,std::string>> rows;task_targets.clear();
            const auto row=[&](TaskTarget task,std::string title){const auto id="task."+std::to_string(task.identity);task_targets.emplace(id,task);rows.push_back({id,std::move(title)});};
            for(const auto& [path,s]:sessions){if(s->job_status.state!=ServiceState::idle)row({TaskKind::job,path,s->job_identity},path+" · "+s->operation+" · "+service_name(s->job_status.state));if(s->terminal.running())row({TaskKind::terminal,path,s->terminal_identity},path+" · Bash terminal");}
            if(model_status.state!=ServiceState::idle)row({TaskKind::models,{},model_identity},"Model catalog · "+model_provider+" · "+service_name(model_status.state));
            if(guardrail_status.state!=ServiceState::idle)row({TaskKind::guardrail,{},guardrail_identity},"OpenRouter guardrail · "+service_name(guardrail_status.state));
            if(!task_targets.contains(selected_task))selected_task.clear();
            auto& tasks=list("wb.tasks","Running and completed tasks",{x,y,w,bottom-y-37},rows,selected_task,"wb.left");tasks.spec.context_input=true;
            const auto target=selected_task_target();button("wb.task.show","Show",{x,bottom-29,w*.4,29},"wb.left").state.enabled=target&&task_exists(*target);
            button("wb.task.cancel",target&&target->kind==TaskKind::terminal?"Stop terminal":"Cancel task",{x+w*.4+4,bottom-29,w*.6-4,29},"wb.left").state.enabled=target&&task_running(*target);
        }
    }
    void idle_boundary(const Session* owner,const std::string& source,const std::string& id,gui::Rect viewport) {
        const bool chat_active=owner&&(owner->operation=="chat"||owner->operation=="agent")&&(owner->job.running()||owner->job_status.state==ServiceState::running);
        if(chat_active||(owner&&(owner->save_conflict||source!=owner->chat.original.text))||source.find_first_not_of(" \t\r\n")==std::string::npos)return;
        auto group=std::find_if(view.widgets.begin(),view.widgets.end(),[&](const auto& item){return item.spec.key.id==id;});if(group==view.widgets.end())return;
        double bottom=viewport.y+4;
        for(const auto& item:view.widgets)if(item.spec.parent==id)bottom=std::max(bottom,item.state.bounds.y+item.state.bounds.height+6);
        if(bottom+8>gui::coordinate_limit)return;
        group->state.content_size.height=std::max(group->state.content_size.height,bottom-viewport.y+8);
        auto& line=add(gui::Kind::bitmap,id+".boundary","",{viewport.x+4,bottom,viewport.width-8,1},id);
        line.state.bitmap={"tinyenv.chat.boundary",1,idle_boundary_line()};
        line.state.accessible_name="End of saved conversation";
    }
    void draw_center(gui::Rect area) {
        pane("wb.center",area);tabs("tab.center.",{"Chat Markdown","Pseudocode Editor","Bash Terminal"},{area.x,area.y,area.width-100,31},state().center_tab,"wb.center");
        button("wb.split","Split Chat",{area.x+area.width-96,area.y,96,31},"wb.center");
        const auto x=area.x+8,w=area.width-16;double y=area.y+40;const auto bottom=area.y+area.height-8;
        if(!session()){label("wb.empty","Chat files hold your conversation. Create or open one from the Chats pane.",{x,y,w,90},"wb.center");return;}
        auto* s=session();
        if(state().center_tab=="Chat Markdown") {
            const auto transcript_height=std::max(60.0,bottom-y-169-s->chat.state.draft_images.size()*28.0);const auto transcript_width=state().split_chat?(w-8)*.5:w;
            const auto measure=[&](const gui::TextMeasureRequest& request){return adapter.measure_text(request);};
            const auto preview=[&](PassiveMarkdownView& renderer,const std::string& source,gui::Rect bounds,const std::string& id,std::uint64_t source_revision){auto widgets=renderer.render(source,bounds,id,"wb.center",measure,view.display_scale,source_revision);view.widgets.insert(view.widgets.end(),std::make_move_iterator(widgets.begin()),std::make_move_iterator(widgets.end()));};
            if(developer_enabled()&&!history_locked(*s)) {
                input("wb.chat.text","Chat Markdown source",{x,y,transcript_width,transcript_height},true,false,"wb.center").state.help="Developer mode edits the original Markdown source.";
            }else {
                preview(s->markdown,s->chat.text,{x,y,transcript_width,transcript_height},"wb.chat.rendered",s->transcript_revision);
                idle_boundary(s,s->chat.text,"wb.chat.rendered",{x,y,transcript_width,transcript_height});
                if(history_locked(*s))for(auto& widget:view.widgets)if(widget.spec.key.id=="wb.chat.rendered")widget.state.help="History editing is paused while this chat's reply is streaming.";
            }
            if(state().split_chat) {
                std::vector<std::pair<std::string,std::string>> rows;for(const auto& path:chat_paths)if(path.generic_string()!=current)rows.push_back({path.generic_string(),path.generic_string()});
                const auto selected=fields["wb.split.path"];choice("wb.split.path","Second chat",{x+transcript_width+8,y,transcript_width,28},rows,selected,"wb.center");
                const auto selected_session=sessions.find(selected);const auto edit_revision=selected_session==sessions.end()?0:selected_session->second->transcript_revision;
                if(s->split_source_dirty||s->split_source_path!=selected||s->split_edit_revision!=edit_revision){s->split_source_dirty=false;s->split_source_path=selected;s->split_edit_revision=edit_revision;s->split_source_text=selected_session==sessions.end()?fields["wb.split.text"]:selected_session->second->chat.text;++s->split_source_revision;}
                preview(s->split_markdown,s->split_source_text,{x+transcript_width+8,y+34,transcript_width,transcript_height-34},"wb.split.rendered",s->split_source_revision+1);
                idle_boundary(selected_session==sessions.end()?nullptr:selected_session->second.get(),s->split_source_text,"wb.split.rendered",{x+transcript_width+8,y+34,transcript_width,transcript_height-34});
            }
            if((s->operation=="chat"||s->operation=="agent")&&(s->job.running()||s->job_status.state==ServiceState::running)) {
                auto& busy=add(gui::Kind::bitmap,"wb.chat.busy","",{x+transcript_width-25,y+5,18,18},"wb.center");busy.state.bitmap={"tinyenv.chat.busy",1,reply_busy_icon()};busy.state.accessible_name=busy.state.help=s->job_status.partial_text.empty()?"Waiting for reply":"Reply in progress";
            }
            y+=transcript_height+8;input("wb.composer","Message",{x,y,w,114},true,false,"wb.center");y+=121;
            for(const auto& image:s->chat.state.draft_images) {
                auto& name=label("wb.image.name."+image.sha256,std::to_string(image.bytes)+" bytes · "+image.name,{x,y,w-77,24},"wb.center");name.state.wrap=gui::TextWrap::none;name.state.help=image.name+" · "+image.mime_type;
                button("wb.image.remove."+image.sha256,"Remove",{x+w-73,y,73,24},"wb.center");y+=28;
            }
            choice("wb.agentic","Agentic",{x,y,94,29},{{"false","Chat"},{"true","Agentic"}},state().agentic?"true":"false","wb.center");view.widgets.back().state.help=state().agentic?"Agentic mode runs the current message's fenced pseudocode.":"Chat mode requests one response.";
            auto& attach=button("wb.image.attach","Attach image",{x+100,y,94,29},"wb.center");attach.state.enabled=!image_choice&&s->chat.state.draft_images.size()<Workspace::maximum_images;attach.state.help="Choose an image from Files, or enter an absolute/project-relative path. Up to four PNG/JPEG images, 4 MiB each and 8 MiB total; sent only with Send or Retry.";
            const bool compact=w<520;const auto action_width=compact?178.0:225.0;
            if(w>=640)label("wb.agentic.label",state().agentic?"Agentic · run pseudocode":"Chat · one response",{x+200,y,w-429,29},"wb.center");
            auto& retry=button("wb.retry","Retry",{x+w-action_width,y,compact?50.0:63.0,29},"wb.center");retry.state.accessible_name="Retry previous message";retry.state.enabled=s->chat.state.submission.has_value()&&!s->job.running();retry.state.help="Resubmits the previous message and its images with current AI settings; preserves this draft and its images.";
            button("wb.cancel","Cancel",{x+w-(compact?124.0:158.0),y,compact?60.0:75.0,29},"wb.center").state.enabled=s->job.running();button("wb.send","Send",{x+w-(compact?60.0:79.0),y,compact?60.0:79.0,29},"wb.center").state.enabled=!s->job.running();
        }else if(state().center_tab=="Bash Terminal") {
            button("wb.terminal.start","Start",{x,y,72,28},"wb.center");button("wb.terminal.interrupt","Interrupt",{x+78,y,83,28},"wb.center");button("wb.terminal.stop","Stop",{x+167,y,65,28},"wb.center").state.enabled=s->terminal.running();label("wb.terminal.cwd","Chat shell · "+state().cwd,{x+239,y,w-239,28},"wb.center");y+=36;
            fields["wb.terminal.output"]=s->terminal_status.output+(s->terminal_status.error.empty()?std::string{}:"\nTerminal error: "+s->terminal_status.error);input("wb.terminal.output","Bash output",{x,y,w,std::max(40.0,bottom-y-38)},true,true,"wb.center");
            input("wb.terminal.command","Bash command",{x,bottom-30,w-73,30},false,false,"wb.center");button("wb.terminal.send","Run",{x+w-67,bottom-30,67,30},"wb.center");
        }else {
            button("flow.zoom.in","+",{x,y,31,28},"wb.center");button("flow.zoom.out","-",{x+35,y,31,28},"wb.center");button("flow.reset","Reset",{x+70,y,58,28},"wb.center");button("flow.pan.up","^",{x+132,y,31,28},"wb.center");button("flow.pan.down","v",{x+167,y,31,28},"wb.center");
            button("flow.pan.left","<",{x+202,y,31,28},"wb.center");button("flow.pan.right",">",{x+237,y,31,28},"wb.center");
            y+=36;
            // Gesture controls must not move the canvas while a pointer owns it.
            // Reserve the same row for the idle hint and active cancellation.
            if(graph.dragging())button("flow.drag.cancel","Stop drag (Esc)",{x,y,w,28},"wb.center");
            else label("flow.help","Drag to pan. Click a block to edit it.",{x,y,w,28},"wb.center").state.font.tone=gui::Tone::muted;
            y+=34;
            const double graph_height=std::max(95.0,(bottom-y)*.47);auto rendered=graph.render(s->graph(),{x,y,w,graph_height},s->selected_node,s->flow.parsed().diagnostics);view.widgets.insert(view.widgets.end(),std::make_move_iterator(rendered.begin()),std::make_move_iterator(rendered.end()));y+=graph_height+5;
            fields["flow.diagnostics"].clear();for(const auto& diagnostic:s->flow.parsed().diagnostics)fields["flow.diagnostics"]+="Line "+std::to_string(diagnostic.line)+":"+std::to_string(diagnostic.column)+" "+diagnostic.message+"\n";
            label("flow.diagnostics",fields["flow.diagnostics"].empty()?"Edits update the current message. Invalid source remains editable.":fields["flow.diagnostics"],{x,y,w,38},"wb.center").state.font.tone=s->flow.parsed().diagnostics.empty()?gui::Tone::muted:gui::Tone::error;y+=42;
            input("wb.flow.text","Pseudocode source",{x,y,w,std::max(60.0,bottom-y-119)},true,false,"wb.center").state.font.tone=s->flow.parsed()?gui::Tone::normal:gui::Tone::error;y=bottom-111;
            choice("node.kind","Block kind",{x,y,w*.27,28},{{"agent","Agent"},{"critique","Critique"},{"repeat","Repeat"},{"branch","Branch"},{"conclude","Conclude"}},fields["node.kind"].empty()?"agent":fields["node.kind"],"wb.center");
            const auto kind=fields["node.kind"].empty()?std::string("agent"):fields["node.kind"];
            if(kind=="agent"||kind=="critique")input("node.role",kind=="agent"?"Agent role":"Critique role",{x+w*.27+4,y,w*.73-4,28},false,false,"wb.center").state.placeholder=kind=="agent"?"writer":"reviewer";
            else if(kind=="repeat"){input("node.iterations","Loop limit",{x+w*.27+4,y,w*.23-4,28},false,false,"wb.center").state.placeholder="3";choice("node.condition","Repeat until",{x+w*.5+4,y,w*.5-4,28},{{"approved","Approved"},{"supported","Supported"}},fields["node.condition"].empty()?"approved":fields["node.condition"],"wb.center").state.help="Approved: the critique approved the answer, marked it supported, and reported no unresolved doubts. Supported: the critique marked claims supported by evidence; doubts may remain.";}
            else if(kind=="branch")choice("node.condition","Branch condition",{x+w*.27+4,y,w*.73-4,28},{{"approved","Approved"},{"supported","Supported"},{"rejected","Rejected"}},fields["node.condition"].empty()?"approved":fields["node.condition"],"wb.center").state.help="Approved: the critique approved the answer, marked it supported, and reported no unresolved doubts. Supported: the critique marked claims supported by evidence; doubts may remain. Rejected: a critique rejected the result.";
            y+=33;
            if(kind=="agent"||kind=="critique"||kind=="conclude")input("node.text",kind=="conclude"?"Conclusion text":"Block prompt",{x,y,w,34},false,false,"wb.center").state.placeholder=kind=="agent"?"Meet the request’s requirements, support factual claims with evidence, and state unresolved doubts.":kind=="critique"?"Assess approval against requirements and support against evidence; state unresolved doubts.":"Summarize requirements met and claims supported by evidence; state unresolved doubts and limits.";
            else label("node.hint","Approved = approved, supported, no doubts. Supported = evidence sufficient; doubts may remain.",{x,y,w,34},"wb.center").state.font.tone=gui::Tone::muted;
            y+=39;
            input("node.parent","Parent ID (0=root)",{x,y,67,28},false,false,"wb.center").state.placeholder="0=root";input("node.index","Sibling position",{x+71,y,50,28},false,false,"wb.center").state.placeholder="Next";bool_choice("node.otherwise","Else branch",{x+125,y,57,28},fields["node.otherwise"]=="true","wb.center");
            double bx=x+188;for(const auto& pair:std::array<std::pair<const char*,const char*>,4>{{{"flow.add","Add"},{"flow.apply","Apply"},{"flow.move","Move"},{"flow.delete","Delete"}}}){button(pair.first,pair.second,{bx,y,(w-188)/4-3,28},"wb.center").state.enabled=bool(s->flow.parsed())&&(pair.first==std::string_view("flow.add")||s->selected_node);bx+=(w-188)/4;}
        }
    }
    void draw_right(gui::Rect area) {
        pane("wb.right",area);tabs("tab.right.",{"Git","Sources","Selector","Pseudocode","Prompts","AI"},{area.x,area.y,area.width,31},state().right_tab,"wb.right");
        const auto x=area.x+8,w=area.width-16;double y=area.y+40;const auto bottom=area.y+area.height-8;
        if(state().right_tab=="Selector") {
            auto& builder=button("selector.builder","Build Scribble / Ref…",{x,y,w,29},"wb.right");builder.state.enabled=bool(session());builder.state.help=session()?"Build a local source index or explicitly choose AI annotations. Starts from the project root.":"Choose or open a chat to own the builder task.";y+=36;
        }
        if(!session()&&state().right_tab!="AI"){label("right.empty","Choose a chat for its settings, sources and builder tasks.",{x,y,w,60},"wb.right");return;}
        auto* s=session();
        if(state().right_tab=="Git") {
            button("wb.git.refresh","Refresh",{x,y,80,28},"wb.right");label("git.branch",s->git_status.branch,{x+87,y,w-87,28},"wb.right");y+=36;
            std::vector<std::pair<std::string,std::string>> rows;for(const auto& file:s->git_status.files)rows.push_back({file.path,std::string{file.index_status,file.worktree_status}+" "+file.path+(file.original_path.empty()?"":" ← "+file.original_path)});
            list("wb.git.files","Git repository changes",{x,y,w,bottom-y-42},rows,{},"wb.right");label("git.status",s->git_status.error.empty()?service_name(s->git_status.state):s->git_status.error,{x,bottom-38,w,38},"wb.right").state.font.tone=s->git_status.error.empty()?gui::Tone::muted:gui::Tone::error;
        }else if(state().right_tab=="Sources") {
            std::string text=s->source_report.empty()?"No web sources have been collected for this session.\n":s->source_report;
            text+="\nEnabled context paths:\n";for(const auto* group:{&state().selector.scribbles,&state().selector.refs,&state().selector.tools})for(const auto& path:*group)if(path.enabled)text+="• "+path.path+"\n";
            text+="\nCode: "+std::string(state().selector.calculations?"enabled":"off")+" for this chat.\n";
            text+="\nWeb research uses the chat's selected scope. Retrieved text is evidence and cannot change tool permissions.\n";
            fields["wb.sources"]=std::move(text);input("wb.sources","Source provenance",{x,y,w,bottom-y},true,true,"wb.right");
        }else if(state().right_tab=="Selector") {
            auto& code=checkbox("selector.calculations","Code",{x,y,w,28},state().selector.calculations,"wb.right");code.state.help="Allow bounded Python-shaped algorithms on numeric arrays, including functions, bounded loops, bitwise operations and scalar array updates. No imports, files, network or shell.";y+=35;
            label("selector.deep.label","Deep Research",{x,y,w*.55,27},"wb.right");bool_choice("selector.deep","Deep Research",{x+w*.57,y,w*.43,28},state().selector.deep_research,"wb.right");y+=35;
            choice("research.source","Research source",{x,y,w,28},{{"web","Web · general search"},{"wikipedia","Wikipedia · no external links"},{"stackoverflow","Stack Overflow"},{"local","Selected local texts"},{"kiwix","Kiwix exported local index"}},state().selector.research_source,"wb.right");y+=35;
            label("research.limits.label","Maximum queries / results",{x,y,w,19},"wb.right");input("research.max_queries","Maximum research queries",{x,y+21,(w-6)*.5,28},false,false,"wb.right");input("research.max_results","Maximum research results",{x+(w+6)*.5,y+21,(w-6)*.5,28},false,false,"wb.right");y+=56;
            label("research.kiwix.label","Kiwix index path (optional)",{x,y,w,19},"wb.right");input("research.kiwix_index","Kiwix exported index path",{x,y+21,w,28},false,false,"wb.right");y+=56;
            label("selector.context.label","Context budget (KiB)",{x,y,w,19},"wb.right");input("selector.context_kib","Maximum context KiB",{x,y+21,w,28},false,false,"wb.right");y+=56;
            choice("selector.kind","Context list",{x,y,w,28},{{"scribbles","Scribbles · expertise"},{"refs","Refs · examples"},{"tools","Tools"}},selector_kind,"wb.right");y+=34;
            std::vector<std::pair<std::string,std::string>> rows;for(const auto& path:path_list())rows.push_back({path.path,(path.enabled?"☑ ":"☐ ")+path.path});
            const auto list_height=std::max(50.0,bottom-y-143);list("selector.paths","Enabled context paths",{x,y,w,list_height},rows,selector_selected,"wb.right");y+=list_height+7;
            input("selector.path","Context path",{x,y,w,29},false,false,"wb.right");y+=35;
            button("selector.add","Add",{x,y,w*.3,28},"wb.right");button("selector.toggle","Enable / disable",{x+w*.3+4,y,w*.43-4,28},"wb.right");button("selector.remove","Remove",{x+w*.73+4,y,w*.27-4,28},"wb.right");y+=36;
            button("selector.save","Save selectors",{x,y,w,29},"wb.right");label("selector.hint","Each chat retains its own enabled paths and research setting.",{x,y+34,w,33},"wb.right").state.font.tone=gui::Tone::muted;
            for(auto& widget:view.widgets)if(widget.spec.key.id=="wb.right")widget.state.content_size.height=std::max(area.height,y+75-area.y);
        }else if(state().right_tab=="Pseudocode"||state().right_tab=="Prompts") {

            snippet_kind=state().right_tab;std::vector<std::pair<std::string,std::string>> rows;for(const auto& snippet:snippets())rows.push_back({snippet.id,snippet.title});
            if(snippet_kind=="Pseudocode"&&tutorial_enabled())for(const auto& snippet:tutorial_snippets)if(std::none_of(rows.begin(),rows.end(),[&](const auto& row){return row.first==snippet.id;}))rows.push_back({snippet.id,snippet.title});
            list("snippet.list","Saved snippets",{x,y,w,std::max(70.0,(bottom-y)*.3)},rows,snippet_id,"wb.right");y+=std::max(70.0,(bottom-y)*.3)+8;
            input("snippet.title","Snippet title",{x,y,w,29},false,false,"wb.right");y+=36;input("snippet.text","Snippet text",{x,y,w,std::max(50.0,bottom-y-78)},true,false,"wb.right");
            const auto button_y=bottom-68;button("snippet.new","New",{x,button_y,w*.3,28},"wb.right");button("snippet.save","Save",{x+w*.3+4,button_y,w*.35-4,28},"wb.right");button("snippet.delete","Delete",{x+w*.65+4,button_y,w*.35-4,28},"wb.right").state.enabled=std::any_of(snippets().begin(),snippets().end(),[&](const auto& snippet){return snippet.id==snippet_id;});button("snippet.insert","Insert into message",{x,bottom-32,w,30},"wb.right");
        }else {
            choice("ai.provider","API provider",{x,y,w,29},{{"openrouter","OpenRouter"},{"openai","OpenAI Responses"},{"ollama","Ollama"}},state().ai.provider,"wb.right");y+=37;
            const auto field=[&](const char* id,const char* title,const char* placeholder=""){label(std::string(id)+".label",title,{x,y,w,19},"wb.right");input(id,title,{x,y+21,w,28},false,false,"wb.right").state.placeholder=placeholder;y+=56;};
            const bool key_enabled=credentials&&AiCredentials::supports(state().ai.provider)&&key_status_error.empty();
            label("ai.key.label","Provider API key",{x,y,w,19},"wb.right");auto& key=input("ai.key","Provider API key",{x,y+21,w,28},false,false,"wb.right");key.state.text=key_draft;key.state.placeholder="Enter a new key";key.spec.text_policy.masked=true;key.spec.text_policy.max_bytes=AiCredentials::maximum_key_bytes;key.state.enabled=key_enabled;y+=56;
            button("ai.key.save","Save key",{x,y,w*.5-2,28},"wb.right").state.enabled=key_enabled&&!key_draft.empty();button("ai.key.remove","Remove saved key",{x+w*.5+2,y,w*.5-2,28},"wb.right").state.enabled=key_enabled&&credential_status==CredentialStatus::saved;y+=35;
            const auto key_status=!key_status_error.empty()?key_status_error:credential_status==CredentialStatus::saved?std::string("Saved private key present"):credential_status==CredentialStatus::absent?std::string("No saved private key; existing provider configuration applies."):state().ai.provider=="ollama"?std::string("This provider does not need an API key."):std::string("Private key saving is unavailable on this platform; existing provider configuration applies.");label("ai.key.status",key_status,{x,y,w,55},"wb.right").state.font.tone=key_status_error.empty()?gui::Tone::muted:gui::Tone::error;y+=62;
            field("ai.endpoint","Endpoint","Provider default");
            std::vector<std::pair<std::string,std::string>> configured;if(preferences){std::size_t index{};for(const auto& model:preferences->configured_models())configured.push_back({std::to_string(index++),model.label+" · "+model.provider});}
            label("ai.models.configured.label","Configured models",{x,y,w,19},"wb.right");choice("ai.models.configured","Configured models",{x,y+21,w,28},configured,configured_model,"wb.right");y+=56;
            field("ai.model","Model ID","Enter a model or choose from a list");field("ai.models.label","Saved model name (optional)","Model ID");
            button("ai.models.add","Add model",{x,y,w*.53,28},"wb.right").state.enabled=bool(preferences);button("ai.models.remove","Remove",{x+w*.53+4,y,w*.47-4,28},"wb.right").state.enabled=preferences&&!configured_model.empty();y+=36;
            label("ai.models.available.label","Available models",{x,y,w-84,24},"wb.right");button("ai.models.refresh","Refresh",{x+w-80,y,80,28},"wb.right").state.enabled=!model_job->running();y+=33;
            input("ai.models.filter","Filter available models",{x,y,w-68,28},false,false,"wb.right").state.placeholder="Model ID or display name";button("ai.models.filter.clear","Clear",{x+w-62,y,62,28},"wb.right").state.enabled=!fields["ai.models.filter"].empty();y+=35;
            const bool catalog_current=catalog_provider==state().ai.provider&&catalog_endpoint==trim(fields["ai.endpoint"]);
            const auto filter=model_search_text(trim(fields["ai.models.filter"]));std::vector<std::pair<std::string,std::string>> filtered_models;
            if(catalog_current)for(const auto& model:available_models)if(filter.empty()||model_search_text(model.first).find(filter)!=std::string::npos||model_search_text(model.second).find(filter)!=std::string::npos)filtered_models.push_back(model);
            const auto visible_selection=catalog_provider==selected_model_provider&&catalog_endpoint==selected_model_endpoint&&std::any_of(filtered_models.begin(),filtered_models.end(),[&](const auto& model){return model.first==selected_model;})?selected_model:std::string{};
            auto& available=list("ai.models.available","Available models",{x,y,w,84},filtered_models,visible_selection,"wb.right");available.state.placeholder=model_job->running()?"Refreshing…":!catalog_current?"Refresh to load models":filtered_models.empty()&&!filter.empty()?"No matching models":"No models returned";available.state.enabled=catalog_current&&!model_job->running();y+=91;
            label("ai.models.count",catalog_current?std::to_string(filtered_models.size())+" of "+std::to_string(available_models.size())+" models":std::string("No catalog loaded"),{x,y,w-84,24},"wb.right").state.font.tone=gui::Tone::muted;button("ai.models.cancel","Cancel",{x+w-80,y,80,28},"wb.right").state.enabled=model_job->running();y+=35;
            const auto half=(w-6)*.5;
            const auto paired=[&](const char* a,const char* at,const char* b,const char* bt){label(std::string(a)+".label",at,{x,y,half,19},"wb.right");label(std::string(b)+".label",bt,{x+half+6,y,half,19},"wb.right");input(a,at,{x,y+21,half,28},false,false,"wb.right").state.placeholder="Provider default";input(b,bt,{x+half+6,y+21,half,28},false,false,"wb.right").state.placeholder="Provider default";y+=56;};
            field("ai.num_predict","Maximum output tokens","Provider default");paired("ai.temperature","Temperature","ai.top_p","Top-p");
            if(state().ai.provider=="ollama")paired("ai.num_ctx","Context tokens","ai.num_keep","Tokens kept");
            else {field("ai.service_tier","Service tier","Provider default");field("ai.reasoning_effort","Reasoning effort","Provider default");}
            if(state().ai.provider=="openrouter")field("ai.routing_providers","Trusted routes (comma separated)","Reviewed route selected automatically");
            label("ai.web.label","Web search",{x,y,w*.58,28},"wb.right");bool_choice("ai.web","Web search",{x+w*.6,y,w*.4,28},state().ai.web_search,"wb.right");y+=35;
            if(state().ai.provider=="openrouter") {
                label("ai.nitro.label","Nitro routing",{x,y,w*.58,28},"wb.right");bool_choice("ai.nitro","Nitro routing",{x+w*.6,y,w*.4,28},state().ai.nitro,"wb.right");y+=35;
            }
            button("ai.apply","Apply and remember defaults",{x,y,w,30},"wb.right");label("ai.hint","Apply saves this chat and defaults for new chats. Credentials stay in private configuration.",{x,y+38,w,60},"wb.right").state.font.tone=gui::Tone::muted;
            y+=106;
            if(state().ai.provider=="openrouter") {label("ai.injection.status","OpenRouter's documented API has no request-only prompt-injection block using a normal API key.",{x,y,w,85},"wb.right").state.font.tone=gui::Tone::muted;y+=92;}
            for(auto& widget:view.widgets)if(widget.spec.key.id=="wb.right")widget.state.content_size.height=std::max(area.height,y-area.y);
        }
    }
    void draw_builder(gui::Rect area) {
        pane("builder.workspace",area);
        const auto top=area.y+8;const auto controls=std::min(470.0,area.width*.48);
        label("builder.title","Scribble builder · "+current,{area.x+16,top,area.width-controls-24,29},"builder.workspace").state.font.size=17;
        button("builder.new","New task",{area.x+area.width-340,top,114,29},"builder.workspace");
        button("builder.exit","Exit Scribble builder",{area.x+area.width-220,top,204,29},"builder.workspace").state.help="Return to the workbench. Running tasks continue; setup and results stay saved with this chat.";
        tabs("tab.builder.",{"Setup","Tasks","Results"},{area.x+16,top+37,area.width-32,31},state().builder.tab,"builder.workspace");
        const gui::Rect body{area.x+8,top+76,area.width-16,area.height-92};pane("builder.body",body);view.widgets.back().spec.parent="builder.workspace";
        const auto x=body.x,w=body.width,y=body.y,h=body.height;
        if(state().builder.tab=="Setup") {
            double fy=y;
            const auto field=[&](const char* id,const char* name,double fh=28){label(std::string(id)+".label",name,{x+14,fy,w-28,19},"builder.body");input(id,name,{x+14,fy+21,w-28,fh},fh>28,false,"builder.body").spec.text_policy.max_bytes=fh>28?64U*1024U:4096U;fy+=fh+28;};
            label("builder.source_help","Project root: "+workspace->root().string()+"\nSource paths are relative to this root ('.' means the project), or explicit absolute paths.",{x+14,fy,w-28,62},"builder.body").state.font.tone=gui::Tone::muted;fy+=69;
            field("builder.paths","Source files or folders (one per line)",50);
            label("builder.kind.label","Use as",{x+14,fy,90,28},"builder.body");choice("builder.kind","Context destination kind",{x+110,fy,w-124,28},{{"scribbles","Scribble · expertise"},{"refs","Ref · examples"}},fields["builder.kind"],"builder.body");fy+=35;
            field("builder.output","Fresh output directory inside this project");view.widgets.back().state.help=presentation_text("Output: "+(std::filesystem::path(fields["builder.output"]).is_absolute()?std::filesystem::path(fields["builder.output"]):workspace->root()/fields["builder.output"]).lexically_normal().string());field("builder.label","Knowledgebase label");view.widgets.back().spec.text_policy.max_bytes=256;
            label("builder.mode.label","Build mode",{x+14,fy,w-28,19},"builder.body");choice("builder.ai","Build mode",{x+14,fy+21,w-28,29},{{"false","Local source index · no AI or network"},{"true","AI annotations · OpenRouter"}},fields["builder.ai"],"builder.body");fy+=57;
            const bool ai_enabled=fields["builder.ai"]=="true",evaluation=fields["builder.evaluation"]=="true";
            if(ai_enabled) {
                field("builder.model","OpenRouter annotation model ID");view.widgets.back().state.placeholder="Enter an explicit publisher/model ID";
                std::vector<std::pair<std::string,std::string>> models;std::set<std::string> model_ids;
                if(preferences)for(const auto& model:preferences->configured_models())if(model.provider=="openrouter"&&model.endpoint==(state().ai.provider=="openrouter"?state().ai.endpoint:std::string{})&&model_ids.insert(model.model).second)models.push_back({model.model,"Configured: "+model.label});
                if(tutorial_enabled())for(const auto& model:std::array<std::pair<const char*,const char*>,4>{{{"nvidia/nemotron-3-ultra-550b-a55b","NVIDIA Nemotron 3 Ultra"},{"deepseek/deepseek-r1-0528","DeepSeek R1 0528"},{"mistralai/mistral-large-4-0","Mistral Large 4"},{"moonshotai/kimi-k3","Kimi K3 · higher output cost"}}})if(model_ids.insert(model.first).second)models.push_back({model.first,"Example: "+std::string(model.second)});
                if(!models.empty()){label("builder.models","Configured models / Tutorial examples (optional)",{x+14,fy,w-28,19},"builder.body");choice("builder.model_choice","Choose an annotation model",{x+14,fy+21,w-28,29},models,fields["builder.model"],"builder.body").state.placeholder="Choose explicitly, or enter an ID above";fy+=57;}
                field("builder.max_calls","Maximum annotation model calls per attempt (1–4096)");
                label("builder.web.label","Limited research for Build",{x+14,fy,w*.66,28},"builder.body");bool_choice("builder.web","Limited research for Build",{x+w*.7,fy,w*.27,28},fields["builder.web"]=="true","builder.body");fy+=35;
            }
            checkbox("builder.evaluation","Comprehension evaluation (uses OpenRouter)",{x+14,fy,w-28,28},evaluation,"builder.body").state.help="Show evaluation fields for an existing output index. Evaluation requires an explicit model and starts only with Evaluate existing.";fy+=35;
            if(evaluation){field("builder.small_model","OpenRouter evaluation model ID");view.widgets.back().state.placeholder="Enter an explicit publisher/model ID";field("builder.questions","Evaluation questions (one per line)",50);}
            if((ai_enabled&&fields["builder.model"]=="moonshotai/kimi-k3")||(evaluation&&fields["builder.small_model"]=="moonshotai/kimi-k3")){label("builder.kimi.label","Allow higher Kimi ceiling ($20/M)",{x+14,fy,w*.67,28},"builder.body");bool_choice("builder.kimi_ceiling","Allow higher Kimi price ceiling",{x+w*.7,fy,w*.27,28},fields["builder.kimi_ceiling"]=="true","builder.body");fy+=35;}
            label("builder.hint",error?status:ai_enabled?"AI annotations use your OpenRouter configuration and reviewed model policy; model availability is not checked here. OpenAI models are excluded. Build starts the request.":"Local indexing retains source anchors and keywords without AI enrichment. No model or credentials needed. Build starts only when clicked.",{x+14,fy,w-28,47},"builder.body").state.font.tone=error?gui::Tone::error:gui::Tone::muted;fy+=54;
            label("builder.output_help","Writes scribbles.md, index.json and evidence.json in a fresh directory. Existing artifacts are refused. Add the output DIRECTORY to Selector's Scribbles or Refs list and enable it to use the verified index.",{x+14,fy,w-28,62},"builder.body").state.font.tone=gui::Tone::muted;fy+=69;
            const auto button_y=std::max(y+h-43,fy+7);button("builder.run",ai_enabled?"Build with AI":"Build local index",{x+14,button_y,143,30},"builder.body").state.enabled=!session()->job.running();double bx=x+165;if(evaluation){button("builder.evaluate","Evaluate existing",{bx,button_y,153,30},"builder.body").state.enabled=!session()->job.running();bx+=161;}for(auto& widget:view.widgets)if(widget.spec.key.id=="builder.body")widget.state.content_size.height=std::max(h,button_y+43-y);
        }
        else if(state().builder.tab=="Tasks") {
            std::vector<std::pair<std::string,std::string>> rows;
            for(const auto& task:state().builder.tasks){auto title=task.label+" · "+(task.operation=="evaluate"?std::string("evaluation"):std::string("Scribble"))+" · "+task.status;if(task.total_chunks)title+=" · "+std::to_string(task.completed_chunks)+"/"+std::to_string(task.total_chunks)+" chunks";if(task.resumed_chunks)title+=" ("+std::to_string(task.resumed_chunks)+" reused)";rows.emplace_back(task.id,std::move(title));}
            auto& tasks=list("builder.tasks","Saved build and evaluation tasks",{x+14,y+8,w-28,std::max(60.0,h-175)},rows,state().builder.selected_task,"builder.body");tasks.spec.context_input=true;
            const auto* task=selected_builder_task();const bool running=task&&session()->builder_job_id==task->id&&session()->job.running(),resumable=task&&task->operation=="scribble"&&(task->status=="ready"||task->status=="paused"||task->status=="interrupted"||task->status=="failed");
            std::string hint=task?(task->phase.empty()?task->status:task->status+" · "+task->phase):"Build and evaluation records stay with this chat. Select a task to manage it.";if(task&&!task->error.empty())hint+="\n"+task->error;
            label("builder.task.status",hint,{x+14,y+h-158,w-28,68},"builder.body").state.font.tone=task&&task->status=="failed"?gui::Tone::error:gui::Tone::muted;
            const auto bw=(w-58)/6;double bx=x+14;const auto row=[&](const char* id,const char* name,bool enabled){button(id,name,{bx,y+h-81,bw,30},"builder.body").state.enabled=enabled;bx+=bw+6;};
            row("builder.task.pause",task&&task->operation=="evaluate"?"Cancel evaluation":"Pause",running);row("builder.task.resume",task&&task->status=="ready"?"Start saved Scribble":"Resume Scribble",resumable&&!session()->job.running());view.widgets.back().state.help="Resume uses this task's saved request and completed annotations. An unfinished interrupted provider request may run again; the call limit applies per attempt.";
#if defined(_WIN32)
            if(task&&task->status!="ready"){view.widgets.back().state.enabled=false;view.widgets.back().state.help="Durable Scribble Resume requires qualified POSIX filesystem operations and is unavailable on Windows. Create a new task with a fresh output directory.";}
#endif
            row("builder.task.retry","Retry evaluation",task&&task->operation=="evaluate"&&!running&&!session()->job.running());row("builder.task.show","Show Results",bool(task));row("builder.task.cancel","Cancel task",running);row("builder.task.remove","Remove record",task&&task->status!="running");view.widgets.back().state.help="Remove only this saved task record. Output directories and durable checkpoint files remain on disk.";
            label("builder.tasks.help","Scribble Pause keeps completed chunks for explicit Resume. Evaluation retry starts a new retained task. Closing the app interrupts work; reopening starts no tasks.",{x+14,y+h-43,w-28,40},"builder.body").state.font.tone=gui::Tone::muted;
        }else {
            const auto* task=selected_builder_task();
            if(!task){label("builder.results.empty","Select a task in Tasks, then choose Show Results.",{x+14,y+14,w-28,60},"builder.body");return;}
            std::string text=task->label+" · "+task->operation+" · "+task->status+"\n";
            if(!task->phase.empty())text+="Phase: "+task->phase+"\n";
            if(task->total_chunks)text+="Chunks: "+std::to_string(task->completed_chunks)+" / "+std::to_string(task->total_chunks)+"; reused: "+std::to_string(task->resumed_chunks)+"\n";
            const auto request=json::parse(task->request_json),result=json::parse(task->result_json);const auto output=string_field(request,"output_dir");text+="Output directory: "+output+"\n\n"+string_field(result,"text");if(!task->error.empty())text+="\n\n"+task->error;
            if(const auto* omitted=result.find("omitted");omitted&&omitted->boolean())text+="\n\n[Additional result metadata omitted from the saved task; output artifacts remain in the directory above.]";
            fields["builder.result.text"]=std::move(text);input("builder.result.text","Retained builder result",{x+14,y+8,w-28,std::max(60.0,h-96)},true,true,"builder.body");
            const bool completed=task->operation=="scribble"&&task->status=="completed";const auto bw=(w-40)/3;
            button("builder.task.open","View generated Scribble",{x+14,y+h-79,bw,30},"builder.body").state.enabled=completed;button("builder.task.scribbles","Use as Scribble",{x+20+bw,y+h-79,bw,30},"builder.body").state.enabled=completed;button("builder.task.refs","Use as Ref",{x+26+bw*2,y+h-79,bw,30},"builder.body").state.enabled=completed;
            label("builder.results.help","Use output explicitly enables its DIRECTORY in this chat's Selector. Task requests and result records stay retained.",{x+14,y+h-41,w-28,38},"builder.body").state.font.tone=gui::Tone::muted;
        }
    }
    void draw_modal(double width,double height) {
        const bool file=modal=="file";
        const double w=std::min(width-32,file?1050.0:650.0),h=std::min(height-80,file?height-110:modal=="transcription"?440.0:modal=="actions"?592.0:modal=="task-actions"?275.0:modal=="discard-retained"?285.0:220.0),x=(width-w)/2,y=(height-h)/2;
        pane("modal.root",{x,y,w,h});view.modal_root=view.widgets.back().spec.key;
        auto title=[&](const std::string& text){label("modal.title",text,{x+14,y+12,w-28,27},"modal.root");};
        if(modal=="prompt") {title(fields["prompt.title"]);input("prompt.value","Project-relative path",{x+14,y+49,w-28,32},false,false,"modal.root");label("modal.message",error?status:prompt_action=="copy-retained"?"Copies the retained in-memory chat and draft to a new .chat.md file. The original conflict remains until its retained changes are explicitly discarded.":prompt_action=="new"||prompt_action=="open"?"Chat filenames end with .chat.md. Other Markdown files open in the file editor.":"Paths are relative to the workspace. Existing destinations are never overwritten.",{x+14,y+90,w-28,60},"modal.root");button("prompt.accept",prompt_action=="open"?"Open":prompt_action=="rename"?"Rename":prompt_action=="copy-file"||prompt_action=="copy-retained"?"Copy":"Create",{x+14,y+h-44,105,30},"modal.root");button("prompt.cancel","Cancel",{x+125,y+h-44,105,30},"modal.root");}
        else if(modal=="actions") {
            title(selected_file.empty()?directory.generic_string():selected_file);const auto* entry=selected_entry();const auto retained=sessions.find(selected_file);const bool conflict=retained!=sessions.end()&&retained->second->save_conflict;double fy=y+47;
            const auto row=[&](const char* id,const char* text){auto& item=button(id,text,{x+14,fy,w-28,30},"modal.root");fy+=37;return &item;};
            row("actions.open","Open file or folder");
            row("actions.attach-image","Attach image to message")->state.enabled=session()&&entry&&!entry->directory&&!entry->symlink&&!image_choice&&state().draft_images.size()<Workspace::maximum_images&&(model_search_text(entry->path.extension().string())==".png"||model_search_text(entry->path.extension().string())==".jpg"||model_search_text(entry->path.extension().string())==".jpeg");
            row("actions.create-file","Create file…");row("actions.create-directory","Create folder…");
            row("actions.copy","Copy text file…")->state.enabled=entry&&!entry->directory&&!entry->symlink&&!conflict;
            if(conflict){row("actions.copy-retained","Copy retained chat and draft…");row("actions.discard-retained","Discard retained changes…");}
            row("actions.rename","Rename…")->state.enabled=entry&&!entry->symlink;row("actions.delete","Delete file / empty folder…")->state.enabled=entry&&!entry->symlink;
            row("wb.file.cd","Bash cd here");auto* builder=row("wb.file.scribble","Build Scribble / Ref…");builder->state.enabled=session()&&(!entry||!entry->symlink);builder->state.help=session()?"Use this selected path or current directory as source.":"Choose or open a chat to own the builder task.";row("wb.file.transcribe","Media transcribe…")->state.enabled=entry&&!entry->directory&&!entry->symlink;
            label("actions.hint",error?status:"Folder deletion only removes an empty folder.",{x+14,fy,w-28,28},"modal.root").state.font.tone=error?gui::Tone::error:gui::Tone::muted;
            const auto button_y=std::max(y+h-43,fy+36);button("modal.cancel","Close",{x+14,button_y,100,30},"modal.root");for(auto& widget:view.widgets)if(widget.spec.key.id=="modal.root")widget.state.content_size.height=std::max(h,button_y+43-y);
        }
        else if(modal=="discard-retained") {
            title("Discard retained changes to "+presentation_text(operation_path.generic_string())+"?");
            label("discard-retained.message",error?status:"This discards unsaved in-memory chat, draft and flow changes, then reloads the file and state from disk. Copy the retained chat first to keep them.",{x+14,y+53,w-28,135},"modal.root").state.font.tone=error?gui::Tone::error:gui::Tone::normal;
            button("discard-retained.accept","Discard and reload",{x+14,y+h-44,170,30},"modal.root");button("modal.cancel","Cancel",{x+192,y+h-44,105,30},"modal.root");
        }
        else if(modal=="task-actions"&&context_task) {
            const auto& target=*context_task;title(target.kind==TaskKind::models?"Model catalog":target.kind==TaskKind::guardrail?"OpenRouter guardrail":presentation_text(target.path));
            button("task.show",target.kind==TaskKind::terminal?"Show terminal":target.kind==TaskKind::models||target.kind==TaskKind::guardrail?"Show AI settings":"Show chat",{x+14,y+49,w-28,30},"modal.root").state.enabled=task_exists(target);
            button("task.cancel",target.kind==TaskKind::terminal?"Stop terminal":"Cancel task",{x+14,y+87,w-28,30},"modal.root").state.enabled=task_running(target);
            label("task.hint",error?status:task_running(target)?"Actions apply to this selected task.":"This task has finished; its result remains available.",{x+14,y+130,w-28,70},"modal.root").state.font.tone=error?gui::Tone::error:gui::Tone::muted;
            button("modal.cancel","Close",{x+14,y+h-43,100,30},"modal.root");
        }
        else if(modal=="delete") {
            title("Delete "+presentation_text(operation_path.generic_string())+"?");
            label("delete.message",error?status:"This permanently removes the selected file or empty folder. A non-empty folder is refused; its contents are never recursively deleted.",{x+14,y+53,w-28,95},"modal.root").state.font.tone=error?gui::Tone::error:gui::Tone::normal;
            button("delete.accept","Delete",{x+14,y+h-44,105,30},"modal.root");button("modal.cancel","Cancel",{x+125,y+h-44,105,30},"modal.root");
        }
        else if(modal=="transcription") {
            title("Transcribe WAV audio with local whisper.cpp");double fy=y+46;
            const auto field=[&](const char* id,const char* text){label(std::string(id)+".label",text,{x+14,fy,w-28,19},"modal.root");input(id,text,{x+14,fy+21,w-28,29},false,false,"modal.root");fy+=57;};
            field("transcription.media","Absolute WAV audio path");field("transcription.executable","Absolute whisper-cli executable path");field("transcription.model","Absolute GGML / GGUF model path");
            label("transcription.limits.label","Threads / timeout in seconds",{x+14,fy,w-28,19},"modal.root");input("transcription.threads","Transcription threads",{x+14,fy+21,(w-34)*.5,29},false,false,"modal.root");input("transcription.timeout","Timeout seconds",{x+(w+6)*.5,fy+21,(w-34)*.5,29},false,false,"modal.root");
            label("transcription.hint",error?status:"Uses your existing executable and model locally. The transcript is appended to this chat.",{x+14,fy+64,w-28,53},"modal.root").state.font.tone=error?gui::Tone::error:gui::Tone::muted;
            button("transcription.run","Transcribe",{x+14,y+h-43,110,30},"modal.root");button("modal.cancel","Cancel",{x+130,y+h-43,100,30},"modal.root");
        }
        else if(file&&file_buffer) {title(file_buffer->path().generic_string()+(file_buffer->dirty()?" *":""));double bx=x+14;for(const auto& [id,text]:std::array<std::pair<const char*,const char*>,3>{{{"file.save","Save"},{"file.close","Close"},{"file.discard","Discard"}}}){button(id,text,{bx,y+45,79,28},"modal.root");bx+=85;}input("file.text","File text",{x+14,y+81,w-28,h-131},true,false,"modal.root");label("file.hint",error?status:"Checked saves preserve changed files on disk. Save or discard before closing.",{x+14,y+h-43,w-28,32},"modal.root").state.font.tone=error?gui::Tone::error:gui::Tone::muted;}

    }
    void publish() {
        if(stopped||adapter.closed())return;
        observe_transcript_scroll();
        if(!session()||state().builder.active||state().center_tab!="Pseudocode Editor"||!modal.empty())cancel_flow_drag();
        pending=true;view.widgets.clear();view.pages.clear();view.active_page.reset();view.key_bindings.clear();view.commands.clear();view.modal_root.reset();
        view.palette=theme::dark_palette();
        const auto width=std::max(900.0,view.client_size.width),height=std::max(640.0,view.client_size.height);
        view.title="tinyEnv — "+(current.empty()?std::string("AI Workbench"):presentation_text(current))+(dirty()?" *":"");
        auto& root=add(gui::Kind::group,"wb.root","",{0,0,width,height},"");root.state.content_size={width,height};
        const auto left=std::clamp(width*.23,220.0,340.0),right=right_sidebar_visible?std::clamp(width*.26,270.0,390.0):0.0,middle=width-left-right-(right_sidebar_visible?16:8);
        if(session()&&state().builder.active)draw_builder({0,0,width,height-37});
        else {draw_left({0,0,left,height-37});draw_center({left+8,0,middle,height-37});if(right_sidebar_visible)draw_right({left+middle+16,0,right,height-37});}
        auto& sidebar=checkbox("wb.sidebar","Sidebar",{width-320,height-32,88,28},right_sidebar_visible);sidebar.state.enabled=bool(preferences)&&!state().builder.active;sidebar.state.help=sidebar_preference_error.empty()?"Show or hide the right settings and sources pane. Remembered across projects and restarts.":sidebar_preference_error;
        checkbox("wb.tutorial","Tutorial",{width-228,height-32,98,28},tutorial_enabled()).state.enabled=bool(preferences);
        checkbox("wb.developer","Developer",{width-126,height-32,118,28},developer_enabled()).state.enabled=bool(preferences);
        std::string visible_status=status;bool visible_error=error;
        if(!sidebar_preference_error.empty()){visible_status+=" "+sidebar_preference_error;visible_error=true;}
        for(const auto& [path,s]:sessions)if(s->save_conflict){visible_status=(!error&&!status.empty()?status+" ":std::string{})+"Autosave conflict in "+path+"; edits retained in memory. "+s->save_error;visible_error=true;if(path==current)break;}
        label("wb.status",visible_status,{8,height-31,width-338,26}).state.font.tone=visible_error?gui::Tone::error:gui::Tone::muted;
        if(!modal.empty())draw_modal(width,height);
        const auto command=[&](const char* id,const char* scope){view.commands.push_back({{id,revision},true,gui::WidgetKey{scope,revision}});};
        if(modal=="file"&&file_buffer){command("file.undo","file.text");command("file.redo","file.text");}
        else if(modal.empty()&&session()&&!state().builder.active){command("wb.undo","wb.center");command("wb.redo","wb.center");}
        const auto binding=[&](gui::ShortcutKey key,const std::string& target){if(std::any_of(view.widgets.begin(),view.widgets.end(),[&](const auto& widget){return widget.spec.key.id==target;}))view.key_bindings.push_back({key,{target,revision}});};
        if(modal=="file")binding(gui::ShortcutKey::f3,"file.save");
        const auto scoped=[&](gui::ShortcutKey key,const std::string& target,const std::string& focus,bool shift=false){
            const auto* from=gui::find_widget(view,{focus,revision});const auto* to=gui::find_widget(view,{target,revision});const auto cmd=std::find_if(view.commands.begin(),view.commands.end(),[&](const auto& command){return command.key.id==target;});
            if(from&&!from->spec.text_policy.read_only&&(to||cmd!=view.commands.end()))view.key_bindings.push_back({key,to?to->spec.key:cmd->key,true,shift,false,from->spec.key});
        };
        if(modal=="file"){scoped(gui::ShortcutKey::z,"file.undo","file.text");scoped(gui::ShortcutKey::z,"file.redo","file.text",true);scoped(gui::ShortcutKey::y,"file.redo","file.text");}
        else if(modal.empty()) {
            for(const auto* id:{"wb.composer","wb.flow.text","wb.chat.text"}){scoped(gui::ShortcutKey::z,"wb.undo",id);scoped(gui::ShortcutKey::z,"wb.redo",id,true);scoped(gui::ShortcutKey::y,"wb.redo",id);}
            scoped(gui::ShortcutKey::enter,"wb.send","wb.composer");
        }
        if(!modal.empty())binding(gui::ShortcutKey::escape,modal=="file"?"file.close":modal=="prompt"?"prompt.cancel":"modal.cancel");
        else if(graph.dragging())binding(gui::ShortcutKey::escape,"flow.drag.cancel");
        const auto builder_semantic=[&](const gui::Widget& widget)->std::uint64_t {
            const auto* s=session();if(!s)return 0;
            if(widget.spec.kind==gui::Kind::button||widget.spec.key.id=="builder.tasks"||widget.spec.key.id=="builder.result.text")return s->builder_action_revision;
            // Typing keeps native inputs and their parent groups alive; New task replaces setup input ownership.
            if(widget.spec.kind==gui::Kind::text||widget.spec.kind==gui::Kind::choice||widget.spec.kind==gui::Kind::toggle)return s->builder_setup_revision;
            return 0;
        };
        std::set<std::string> active;for(auto& widget:view.widgets){auto& life=lives[widget.spec.key.id];auto compare=widget.spec;compare.key.generation=life.spec.key.generation;const auto* s=session();const auto semantic=widget.spec.key.id=="wb.flow.canvas"?flow_input_revision:widget.spec.key.id=="ai.key"||widget.spec.key.id.starts_with("ai.key.")?key_input_revision:widget.spec.key.id=="ai.models.available"?catalog_input_revision:widget.spec.key.id=="ai.models.cancel"?model_identity:s&&widget.spec.key.id=="wb.send"?s->send_revision:s&&(widget.spec.key.id=="wb.cancel"||widget.spec.key.id=="wb.retry")?s->job_identity:s&&(widget.spec.key.id.starts_with("builder.")||widget.spec.key.id.starts_with("tab.builder."))?builder_semantic(widget):widget.spec.key.id.starts_with("wb.task.")||widget.spec.key.id.starts_with("task.")?task_action_revision:s&&widget.spec.key.id.starts_with("flow.")?s->flow.revision()*4096+s->selected_node:0;const auto source_revision=s&&widget.spec.key.id=="wb.flow.canvas"?s->flow.revision():0;if(life.active&&life.scene==revision&&life.semantic==semantic&&life.source_revision==source_revision&&compare==life.spec)widget.spec.key.generation=life.spec.key.generation;else widget.spec.key.generation=++widget_generation;life={widget.spec,true,revision,semantic,source_revision};active.insert(widget.spec.key.id);}
        for(auto& [id,life]:lives)if(!active.contains(id))life.active=false;
        std::set<std::string> active_commands;for(auto& command:view.commands){if(command.scope)command.scope=lives.at(command.scope->id).spec.key;auto& life=command_lives[command.key.id];const auto* s=session();const auto semantic=command.key.id.starts_with("file.")?file_edit_revision:s?s->edit_revision:0;if(life.active&&life.scene==revision&&life.semantic==semantic&&life.command.scope==command.scope)command.key.generation=life.command.key.generation;else command.key.generation=++widget_generation;life={command,true,revision,semantic};active_commands.insert(command.key.id);}
        for(auto& [id,life]:command_lives)if(!active_commands.contains(id))life.active=false;
        if(view.modal_root)view.modal_root=lives.at(view.modal_root->id).spec.key;
        for(auto& binding:view.key_bindings){if(auto it=lives.find(binding.target.id);it!=lives.end()&&it->second.active)binding.target=it->second.spec.key;else if(auto cmd=command_lives.find(binding.target.id);cmd!=command_lives.end()&&cmd->second.active)binding.target=cmd->second.command.key;if(binding.focus)if(auto it=lives.find(binding.focus->id);it!=lives.end()&&it->second.active)binding.focus=it->second.spec.key;}
        ++view.revision;adapter.present(view);restore_transcript_scroll();
        if(restore_sidebar&&right_sidebar_visible){if(sidebar_owner==current){for(const auto& [id,offset]:sidebar_scroll)if(const auto found=lives.find(id);found!=lives.end()&&found->second.active)adapter.scroll(found->second.spec.key,offset);for(const auto& [id,selection]:sidebar_selection)if(const auto found=lives.find(id);found!=lives.end()&&found->second.active)adapter.text_selection(found->second.spec.key,selection);}restore_sidebar=false;}
        for(auto it=restored_selection.begin();it!=restored_selection.end();){const auto found=lives.find(it->first);if(found!=lives.end()&&found->second.active){adapter.text_selection(found->second.spec.key,it->second);it=restored_selection.erase(it);}else ++it;}pending=false;
    }
};

Application::Application(gui::Adapter& adapter):impl_(std::make_unique<Impl>(adapter)){}
Application::~Application(){shutdown();}
const gui::Snapshot& Application::view()const noexcept{return impl_->view;}
std::string_view Application::chat_text()const noexcept{const auto* s=impl_->session();return s?std::string_view(s->chat.text):std::string_view{};}
bool Application::presentation_pending()const noexcept{return impl_->pending;}
std::uint64_t Application::input_epoch()const noexcept{return impl_->epoch;}
void Application::retry_presentation(){if(impl_->pending)impl_->publish();}
std::optional<gui::ServiceRequest> Application::next_service(){if(impl_->stopped||impl_->adapter.closed())return std::nullopt;return impl_->image_services.begin_next();}
bool Application::complete_service(gui::ServiceResult result){
    auto& p=*impl_;if(p.stopped||p.adapter.closed()||!p.image_services.complete(result))return false;
    const auto owner=p.image_choice;p.image_choice.reset();
    try {
        if(result.status==gui::ServiceStatus::error)throw std::runtime_error("Image selection: "+result.error);
        if(result.status==gui::ServiceStatus::cancelled)p.success("Image selection canceled; current draft retained.");
        else {auto* s=p.session();if(!owner||!s||p.current!=owner->chat||p.revision!=owner->scene||s->send_revision!=owner->send_revision)throw std::runtime_error("Image selection expired after this chat changed. Select Attach image again.");if(result.value.empty())throw std::runtime_error("Select a local PNG or JPEG image.");p.attach_image(std::filesystem::path(result.value));}
    }catch(const std::exception& e){p.failure(e.what());}
    ++p.epoch;try{p.publish();}catch(...){p.pending=true;}return true;
}
void Application::shutdown()noexcept {
    if(!impl_||impl_->stopped)return;
    for(auto& [path,s]:impl_->sessions){(void)path;try{if(s->job.running())impl_->cancel_job(*s,"interrupted");}catch(...){}if(s->save_due||s->chat.text!=s->chat.original.text)try{impl_->save_state(*s);}catch(...) {}}
    impl_->stopped=true;impl_->image_services.shutdown();impl_->image_choice.reset();
    impl_->key_draft.clear();
    impl_->graph.cancel_drag();
    try{if(impl_->model_job->running())impl_->model_status=impl_->model_job->cancel();}catch(...){}
    try{if(impl_->guardrail_job.running())impl_->guardrail_status=impl_->guardrail_job.cancel();}catch(...){}
    for(auto& [path,s]:impl_->sessions){(void)path;try{if(s->git.running())s->git_status=s->git.cancel();}catch(...){}try{s->terminal.shutdown();}catch(...){}}
}
void Application::handle(gui::Event event) {
    auto& p=*impl_;if(p.stopped||p.adapter.closed())return;
    p.observe_transcript_scroll();
    if(std::holds_alternative<gui::CloseEvent>(event)) {
        p.cancel_flow_drag();
        try{if(p.file_buffer&&p.file_buffer->dirty())throw std::runtime_error("Save or discard the open file before closing.");for(auto& [path,s]:p.sessions){(void)path;if(s->job.running())p.cancel_job(*s,"interrupted");if(s->save_due||s->chat.text!=s->chat.original.text)p.save_state(*s);}shutdown();p.adapter.close();}
        catch(const std::exception& e){p.failure(e.what());p.publish();}return;
    }
    if(!gui::normalize_event(p.view,event,[&](const auto& key){return p.adapter.scroll_offset(key);}))return;
    try {
        bool publish_needed=true;
        if(const auto* resize=std::get_if<gui::ResizeEvent>(&event)){p.cancel_flow_drag();p.view.client_size=resize->client_size;p.view.display_scale=resize->display_scale;}
        else if(const auto* widget=std::get_if<gui::WidgetEvent>(&event)) {
            const auto& id=widget->target.id;
            if(id!="wb.flow.canvas"||!std::holds_alternative<gui::PointerInput>(widget->input))p.cancel_flow_drag();
            std::visit([&](const auto& input){using T=std::decay_t<decltype(input)>;
                if constexpr(std::is_same_v<T,gui::EditText>) {
                    auto* s=p.session();if(id=="ai.key")p.key_draft=input.value;else if(id!="wb.chat.text"&&id!="wb.composer"&&id!="wb.flow.text")p.fields[id]=input.value;
                    if(id=="wb.chat.text"&&s&&p.developer_enabled()&&!p.history_locked(*s)){if(p.typing_step(*s,id,s->chat.text,input.value))p.remember_chat(*s);s->redo_chat.clear();s->chat.text=input.value;++s->transcript_revision;p.fields[id]=input.value;p.modified(*s);}
                    else if(id=="wb.composer"&&s){const auto step=p.typing_step(*s,id,s->chat.state.draft,input.value);p.set_draft(*s,input.value,step);s->redo_draft.clear();}
                    else if(id=="wb.terminal.command"&&s)s->terminal_command=input.value;
                    else if(id=="wb.flow.text"&&s){const auto step=p.typing_step(*s,id,s->flow.text(),input.value);p.set_flow(*s,input.value,step);s->redo_draft.clear();}
                    else if(id=="file.text"&&p.file_buffer){p.file_buffer->set_text(input.value);++p.file_edit_revision;}
                    else if(id.starts_with("builder.")&&s){p.retain_builder_fields();++s->builder_action_revision;}
                    else if(id=="ai.guardrail.id"){p.guardrail_loaded_id.clear();p.guardrail_fingerprint.clear();p.guardrail_action.clear();p.guardrail_enabled=false;p.guardrail_desired=false;}
                }else if constexpr(std::is_same_v<T,gui::SubmitText>) {
                    if(id=="prompt.value")p.action("prompt.accept");else if(id=="wb.path")p.browse(p.fields[id]);else if(id=="wb.terminal.command")p.action("wb.terminal.send");else if(id=="selector.path")p.action("selector.add");
                }else if constexpr(std::is_same_v<T,gui::ChooseOption>) {
                    const auto before=p.state();const auto value=record_value(input.id);p.fields[id]=value;
                    if(id=="selector.kind"){p.selector_kind=value;if(auto* s=p.session())s->selector_kind=value;p.selector_selected.clear();}
                    else if(id=="builder.model_choice")p.fields["builder.model"]=value;
                    else if(id=="builder.kind"){const auto output=p.builder_default_output();if(p.fields["builder.output"]==p.fields["builder.default_output"])p.fields["builder.output"]=output;p.fields["builder.default_output"]=output;}
                    else if(id=="research.source")p.state().selector.research_source=value;
                    else if(id=="selector.deep")p.state().selector.deep_research=value=="true";
                    else if(id=="ai.provider"){auto& ai=p.state().ai;if(ai.provider!=value){ai.provider=value;ai.model.clear();ai.endpoint.clear();p.fields["ai.model"].clear();p.fields["ai.endpoint"].clear();p.fields["ai.models.label"].clear();p.selected_model.clear();p.selected_model_provider.clear();p.selected_model_endpoint.clear();p.configured_model.clear();p.state().ai_configured=true;}p.refresh_key_status();}
                    else if(id=="ai.models.configured")p.select_configured_model(value);
                    else if(id=="node.kind"&&value=="repeat"&&p.fields["node.condition"]=="rejected")p.fields["node.condition"]="approved";
                    else if(id=="ai.web")p.state().ai.web_search=value=="true";
                    else if(id=="ai.nitro")p.state().ai.nitro=value=="true";
                    else if(id=="wb.agentic")p.state().agentic=value=="true";
                    else if(id=="wb.split.path"){if(auto it=p.sessions.find(value);it!=p.sessions.end())p.fields["wb.split.text"]=it->second->chat.text;else p.fields["wb.split.text"]=p.workspace->open_chat(value).text;if(auto* s=p.session())s->split_source_dirty=true;}
                    if(id.starts_with("builder.")){p.retain_builder_fields();if(auto* s=p.session())++s->builder_action_revision;}
                    if(auto* s=p.session();s&&s->chat.state!=before)p.modified(*s);
                }else if constexpr(std::is_same_v<T,gui::SetChecked>) {
                    if(id=="wb.sidebar"){p.set_sidebar_visible(input.value);p.success(input.value?"Sidebar shown.":"Sidebar hidden. Use Sidebar below to show it again.");}
                    else if(id=="selector.calculations"){p.state().selector.calculations=input.value;if(auto* s=p.session())p.modified(*s);p.success(input.value?"Code enabled for this chat.":"Code disabled for this chat.");}
                    else if(id=="builder.evaluation"){p.fields[id]=input.value?"true":"false";p.retain_builder_fields();if(auto* s=p.session())++s->builder_action_revision;}
                    else if(id=="wb.tutorial") {
                        if(!p.preferences)throw std::runtime_error("Tutorial preferences are unavailable.");
                        p.preferences->set_tutorial_mode(input.value);
                        if(!input.value&&p.snippet_id.starts_with("builtin.")&&std::none_of(p.snippets().begin(),p.snippets().end(),[&](const auto& snippet){return snippet.id==p.snippet_id;})){p.snippet_id.clear();p.fields["snippet.title"].clear();p.fields["snippet.text"].clear();}
                        p.success(input.value?"Tutorial examples shown.":"Tutorial examples hidden.");
                    }else if(id=="wb.developer"){if(!p.preferences)throw std::runtime_error("Developer preferences are unavailable.");if(!input.value)for(auto& [path,s]:p.sessions){(void)path;if(s->chat.text!=s->chat.original.text)p.save_state(*s);}p.preferences->set_developer_mode(input.value);p.success(input.value?"Developer enabled: chat history is editable.":"Developer disabled: chat history is read-only.");}
                    else if(id=="ai.guardrail.enabled"&&p.guardrail_ready())p.guardrail_desired=input.value;
                }else if constexpr(std::is_same_v<T,gui::SelectRecord>||std::is_same_v<T,gui::ActivateRecord>) {
                    const auto value=record_value(input.id);
                    if(id=="wb.chats")p.open_chat(value);
                    else if(id=="wb.files") {p.selected_file=value;if constexpr(std::is_same_v<T,gui::ActivateRecord>){if(const auto* entry=p.selected_entry();entry&&entry->directory){if(p.expanded.contains(value))p.expanded.erase(value);else p.expanded.insert(value);p.refresh_tree();}else p.open_file();}}
                    else if(id=="selector.paths"){p.selector_selected=value;if constexpr(std::is_same_v<T,gui::ActivateRecord>)p.action("selector.toggle");}
                    else if(id=="snippet.list")p.load_snippet(value);
                    else if(id=="ai.models.available"){const auto found=std::find_if(p.available_models.begin(),p.available_models.end(),[&](const auto& model){return model.first==value;});if(found!=p.available_models.end()){p.selected_model=value;p.selected_model_provider=p.catalog_provider;p.selected_model_endpoint=p.catalog_endpoint;p.fields["ai.model"]=value;p.fields["ai.models.label"]=found->second;p.configured_model.clear();}}
                    else if(id=="builder.tasks"){if(auto* s=p.session();s&&p.builder_task(*s,value)){s->chat.state.builder.selected_task=value;++s->builder_action_revision;p.modified(*s);if constexpr(std::is_same_v<T,gui::ActivateRecord>)p.builder_task_action("show");}}
                    else if(id=="wb.tasks"){if(p.task_targets.contains(value)){p.selected_task=value;++p.task_action_revision;if constexpr(std::is_same_v<T,gui::ActivateRecord>)p.task_action(false,false);}}
                }else if constexpr(std::is_same_v<T,gui::Activate>) {
                    if(id=="wb.undo"||id=="wb.redo"){if(auto* s=p.session())p.undo_text(input.source?input.source->id:s->last_edit,id=="wb.redo");}
                    else if(id=="wb.split"){p.state().split_chat=!p.state().split_chat;if(auto* s=p.session())p.modified(*s);}else p.action(id);
                }else if constexpr(std::is_same_v<T,gui::PointerInput>) {
                    if(id=="wb.flow.canvas") {
                        publish_needed=false;
                        if(input.kind==gui::PointerKind::press)publish_needed=p.graph.begin_drag(input.pointer_id,input.position);
                        else if(input.kind==gui::PointerKind::move)publish_needed=p.graph.drag_to(input.pointer_id,input.position);
                        else if(input.kind==gui::PointerKind::release){const auto was_dragging=p.graph.dragging();const auto before_pan=p.graph.pan();if(auto hit=p.graph.end_drag(input.pointer_id,input.position)){p.select_node(*hit);publish_needed=true;}publish_needed=publish_needed||was_dragging!=p.graph.dragging()||before_pan!=p.graph.pan();}
                        else if(input.kind==gui::PointerKind::cancel&&input.pointer_id){const auto before=p.flow_input_revision;p.cancel_flow_drag(input.pointer_id);publish_needed=before!=p.flow_input_revision;}
                        else if(input.kind==gui::PointerKind::wheel){const auto before=p.flow_input_revision;p.cancel_flow_drag();publish_needed=p.graph.zoom_at(input.wheel_y,input.position)||before!=p.flow_input_revision;}
                        else if(input.kind==gui::PointerKind::click||input.kind==gui::PointerKind::double_click){const auto before=p.flow_input_revision;p.cancel_flow_drag();publish_needed=before!=p.flow_input_revision;if(auto hit=p.graph.hit_test(input.position)){p.select_node(*hit);publish_needed=true;}}
                    }
                    else if(id=="wb.disk.canvas") {
                        if(input.kind==gui::PointerKind::press){if(auto path=p.disk.hit_test(input.position))p.disk_press=std::pair{input.pointer_id,*path};else p.disk_press.reset();}
                        else if(input.kind==gui::PointerKind::cancel)p.disk_press.reset();
                        else if(input.kind==gui::PointerKind::release){if(p.disk_press&&p.disk_press->first==input.pointer_id){const auto path=p.disk.hit_test(input.position);if(path&&*path==p.disk_press->second)p.disk_select(*path);}p.disk_press.reset();}
                        else if(input.kind==gui::PointerKind::click){if(auto path=p.disk.hit_test(input.position))p.disk_select(*path);}
                    }
                    else if(id=="builder.tasks"&&input.kind==gui::PointerKind::context_menu){if(const auto* list=gui::find_widget(p.view,widget->target)){const auto offset=p.adapter.scroll_offset(widget->target);const auto row=static_cast<std::size_t>(std::max(0.0,input.position.y-list->state.bounds.y+offset.y)/28);if(row<list->state.records.size())if(auto* s=p.session()){s->chat.state.builder.selected_task=record_value(list->state.records[row].id);++s->builder_action_revision;p.modified(*s);}}}
                    else if(id=="wb.tasks"&&input.kind==gui::PointerKind::context_menu)p.task_context(input.position,widget->target);
                    else if(id=="wb.files"&&input.kind==gui::PointerKind::context_menu){const auto found=std::find_if(p.view.widgets.begin(),p.view.widgets.end(),[&](const auto& item){return item.spec.key.id==id;});if(found!=p.view.widgets.end()){const auto offset=p.adapter.scroll_offset(found->spec.key);const auto row=static_cast<std::size_t>(std::max(0.0,input.position.y-found->state.bounds.y+offset.y)/28);p.selected_file=row<p.tree.size()?p.tree[row].path.generic_string():std::string{};p.modal="actions";}}
                }
            },widget->input);
        }
        ++p.epoch;if(publish_needed)p.publish();
    }catch(const std::exception& e){p.cancel_flow_drag();p.failure(e.what());try{p.publish();}catch(...){p.pending=true;}}
}
void Application::tick() {
    auto& p=*impl_;if(p.stopped)return;if(p.adapter.closed()){shutdown();return;}bool update=false;
    p.observe_transcript_scroll(true);
    update=p.poll_models()||update;update=p.poll_guardrail()||update;
    for(auto& [path,s]:p.sessions) {
        if(s->job.running()||s->job_status.state==ServiceState::running) {
            auto next=s->job.poll();const auto state_changed=next.state!=s->job_status.state,progress_changed=next.progress_revision!=s->job_status.progress_revision;s->job_status=std::move(next);
            if(progress_changed&&!s->builder_job_id.empty()){p.builder_progress(*s);update=true;}
            if(s->job_status.finished()){p.finish_job(*s);update=true;}
            else if(s->stream_owned&&!s->stream_conflict&&s->job_status.streaming&&s->job_status.stream_revision!=s->displayed_stream_revision&&std::chrono::steady_clock::now()-s->last_stream_display>=stream_display_interval) {
                try {const auto dirty=s->chat.text!=s->chat.original.text;const auto changed=p.replace_reply(*s,s->job_status.partial_text,"Streaming");update=(changed&&(p.transcript_visible(*s)||(!dirty&&p.dirty_visible(*s))))||update;s->displayed_stream_revision=s->job_status.stream_revision;s->last_stream_display=std::chrono::steady_clock::now();}
                catch(const std::exception& e){p.failure(path+": "+e.what());s->stream_conflict=true;s->save_conflict=true;s->save_error=e.what();update=true;}
            }
            update=state_changed||update;
        }
        const auto now=std::chrono::steady_clock::now();
        const auto save_ready=s->stream_owned?now-s->last_stream_save>=std::chrono::milliseconds(500):now-s->changed_at>=std::chrono::milliseconds(300);
        if(s->save_due&&!s->save_conflict&&save_ready) {
            const auto dirty=s.get()==p.session()?p.dirty():s->chat.text!=s->chat.original.text;const auto was_error=p.error;const auto previous_status=p.status;
            try{p.save_state(*s);s->last_stream_save=now;if(!p.error&&!s->stream_owned)p.success("Autosaved "+path+".");}catch(const std::exception& e){p.failure("Autosave conflict in "+path+"; changes remain in memory: "+std::string(e.what()));}
            const auto now_dirty=s.get()==p.session()?p.dirty():s->chat.text!=s->chat.original.text;
            update=(p.dirty_visible(*s)&&dirty!=now_dirty)||p.error!=was_error||p.status!=previous_status||update;
        }
        if(s->terminal.running()||s->terminal_status.running) {auto next=s->terminal.drain();if(next.output!=s->terminal_status.output||next.running!=s->terminal_status.running||next.error!=s->terminal_status.error){s->terminal_status=std::move(next);if(!s->terminal_status.error.empty())p.failure(path+": "+s->terminal_status.error);update=true;}}
        if(s->git.running()||s->git_status.state==ServiceState::running) {auto next=s->git.poll();if(next.state!=s->git_status.state){s->git_status=std::move(next);update=true;}}
    }
    if(update)try{p.publish();}catch(...){p.pending=true;}
    retry_presentation();
}
void Application::qualify(const std::function<void()>& present) {
    auto& p=*impl_;const auto require=[](bool value,const char* message){if(!value)throw std::runtime_error(message);};
    present();require(!p.pending&&!p.view.widgets.empty(),"Workbench did not present.");
    const auto activate=[&](const std::string& id){const auto found=std::find_if(p.view.widgets.begin(),p.view.widgets.end(),[&](const auto& widget){return widget.spec.key.id==id;});require(found!=p.view.widgets.end(),"Workbench action missing.");handle(gui::WidgetEvent{found->spec.key,gui::Activate{}});present();};
    activate("tab.left.Files");require(p.state().left_tab=="Files","File browser tab failed.");activate("wb.file.actions");require(p.modal=="actions","File actions did not open.");activate("modal.cancel");
    activate("tab.left.Chats");activate("wb.new");require(p.modal=="prompt","Chat file prompt failed.");activate("prompt.cancel");require(p.modal.empty(),"Chat file prompt did not close.");
    // Smoke does not launch shells, AI services, search or write project files.
    p.success("Workbench local presentation check completed.");p.publish();present();
}
} // namespace tinyenv
