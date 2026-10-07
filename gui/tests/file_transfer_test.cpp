#include <gui/web.hpp>
#include <iostream>
using namespace gui::web_detail;
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
int main(){try{
    gui::WebAdapter adapter;gui::Snapshot view;view.client_size={40,40};adapter.present(view);
    std::optional<gui::ServiceRequest> next=gui::ServiceRequest{1,gui::ServiceKind::read_text,"Import","",12};
    std::vector<gui::ServiceResult> complete;
    gui::WebSession session(adapter,"epoch",[&]{auto value=next;next.reset();return value;},[&](gui::ServiceResult result){complete.push_back(std::move(result));return true;});
    session.initial();std::uint64_t seq=0;
    const auto send=[&](Json::Object op){return Parser(session.receive(encode(Json::Object{{"epoch","epoch"},{"seq",std::to_string(++seq)},{"operation",std::move(op)}}))).parse();};
    const auto valid=[](const Json& value){check(value.at("error").str().empty(),"Valid chunk rejected");};
    valid(send({{"type","fileBegin"},{"id","1"},{"total","3"}}));
    check(!send({{"type","fileChunk"},{"id","1"},{"offset","1"},{"hex","61"}}).at("error").str().empty(),"Out-of-order chunk accepted");
    valid(send({{"type","fileChunk"},{"id","1"},{"offset","0"},{"hex","610a"}}));
    // An uncertain transport repeats the same envelope/sequence. Bytes must
    // remain at offset 2 rather than being appended twice.
    const auto duplicate=Parser(session.receive(encode(Json::Object{{"epoch","epoch"},{"seq",std::to_string(seq)},{"operation",Json::Object{{"type","fileChunk"},{"id","1"},{"offset","0"},{"hex","610a"}}}}))).parse();
    check(duplicate.at("error").str()=="Duplicate operation ignored","Retry was not recognized");
    check(!send({{"type","fileFinish"},{"id","1"}}).at("error").str().empty()&&complete.empty(),"Truncated import committed");
    valid(send({{"type","fileChunk"},{"id","1"},{"offset","2"},{"hex","62"}}));
    valid(send({{"type","fileFinish"},{"id","1"}}));check(complete.size()==1&&complete.back().value=="a\nb","Import assembled incorrectly");
    check(!send({{"type","fileFinish"},{"id","1"}}).at("error").str().empty()&&complete.size()==1,"Stale import committed twice");
    next=gui::ServiceRequest{2,gui::ServiceKind::write_text,"Export",std::string(5000,'a'),6000};
    const auto offer=Parser(session.initial()).parse();check(offer.at("service").at("value").str().empty(),"Export sent entire content in snapshot");
    auto part=send({{"type","fileRead"},{"id","2"},{"offset","0"}});valid(part);check(part.at("transfer").at("hex").str().size()==8192,"Export chunk is unbounded");
    part=send({{"type","fileRead"},{"id","2"},{"offset","4096"}});valid(part);check(part.at("transfer").at("hex").str().size()==1808,"Export tail differs");
    check(complete.size()==1,"Offering export claimed durable completion");
    check(!session.complete_host_service({1,gui::ServiceStatus::success,{},{}}),"Trusted completion accepted stale service");
    check(session.complete_host_service({2,gui::ServiceStatus::success,{},{}}),"Trusted completion rejected matching service");
    next=gui::ServiceRequest{3,gui::ServiceKind::read_text,"Import","",2};session.initial();
    check(!send({{"type","fileBegin"},{"id","3"},{"total","3"}}).at("error").str().empty(),"Oversize import accepted");
    valid(send({{"type","fileBegin"},{"id","3"},{"total","1"}}));valid(send({{"type","fileChunk"},{"id","3"},{"offset","0"},{"hex","ff"}}));
    check(!send({{"type","fileFinish"},{"id","3"}}).at("error").str().empty(),"Invalid UTF-8 committed");
    valid(send({{"type","service"},{"id","3"},{"status","cancelled"},{"value",""},{"error",""}}));
    check(complete.back().status==gui::ServiceStatus::cancelled,"Cancellation lost");adapter.close();
    check(!session.complete_host_service({3,gui::ServiceStatus::success,"late",{}}),"Close accepted late contents");
    std::cout<<"Bounded ordered file chunks, truncation, stale identity, UTF-8, cancellation, export and trusted completion passed\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
