#include "host/browser.hpp"
#include "shared/application.hpp"
#include "host/qualification.hpp"
#include <iostream>
#include "host/no_socket.hpp"
#include "host/file_services.hpp"
#include <charconv>
#ifdef __linux__
#include <poll.h>
#endif

int main(int argc, char** argv) {
    try {
        if (foundation::host::smoke_requested(argc, argv)) {
            foundation::host::Browser<foundation::ui::Application> runtime("qualification");
            std::uint64_t sequence = 0;
            runtime.application().qualify([&] {
                using namespace gui::web_detail;
                const auto response = Parser(runtime.receive(encode(Json::Object{
                    {"epoch", "qualification"}, {"seq", std::to_string(++sequence)},
                    {"operation", Json::Object{{"type", "poll"}}}}))).parse();
                if (!response.at("error").str().empty() || response.at("ack").str() != std::to_string(sequence) ||
                    response.at("snapshot").at("revision").str() != std::to_string(runtime.adapter.snapshot().revision))
                    throw std::runtime_error("Browser transport lost presentation");
            });
            return foundation::host::finish_smoke(runtime.application(), runtime.adapter);
        }
        bool isolated=false;int file_fd=-1;std::string epoch="stdio-session";bool epoch_set=false;
        for(int i=1;i<argc;++i) {
            const std::string_view option=argv[i];
            if(option=="--isolated")isolated=true;
            else if(option=="--file-events-fd"&&i+1<argc) {
                const std::string_view value=argv[++i];const auto parsed=std::from_chars(value.data(),value.data()+value.size(),file_fd);
                if(parsed.ec!=std::errc{}||parsed.ptr!=value.data()+value.size()||file_fd<3)throw std::invalid_argument("Invalid trusted file pipe");
            } else if(!epoch_set&&!option.starts_with("--")){epoch=option;epoch_set=true;}
            else throw std::invalid_argument("Usage: foundation-gui-web [SESSION] [--isolated] [--file-events-fd N]");
        }
        if(file_fd>=0&&!isolated)throw std::invalid_argument("Trusted file pipe requires the isolated Linux worker");
        if(isolated) {
            std::vector<int> retained{0,1,2};if(file_fd>=0)retained.push_back(file_fd);
            foundation::host::restrict_descriptors(retained);
            foundation::host::verify_anonymous_pipe(0,true);foundation::host::verify_anonymous_pipe(1,false);
            if(file_fd>=0)foundation::host::verify_anonymous_pipe(file_fd,true);
            foundation::host::install_no_socket_boundary(); // Before App or executor threads.
        }
        foundation::host::Browser<foundation::ui::Application> runtime(epoch);
        std::cout << runtime.initial() << '\n' << std::flush;
        const auto receive=[&](std::string_view line,bool trusted) {
            if(!trusted)return runtime.receive(line);
            using namespace gui::web_detail;
            const auto input=Parser(line).parse();const auto& request=runtime.session.pending_service();
            if(!request||integer(input.at("id"))!=request->id||
                (request->kind!=gui::ServiceKind::read_text&&request->kind!=gui::ServiceKind::write_text))
                throw std::invalid_argument("No matching trusted file request");
            gui::ServiceResult result;std::atomic_bool stop{false};
            try { const auto path=input.at("path").str();
                if(path.empty()||path.find('\0')!=std::string::npos||path.size()>32768)throw std::invalid_argument("Invalid trusted path");
                result=foundation::host::file_detail::transfer(*request,std::filesystem::path(std::u8string(path.begin(),path.end())),stop);
            } catch(const std::exception& error){result={request->id,gui::ServiceStatus::error,{},error.what()};}
            if(!runtime.session.complete_host_service(std::move(result)))throw std::invalid_argument("Trusted file completion rejected");
            return runtime.session.initial();
        };
#ifdef __linux__
        if(file_fd>=0) {
            std::array<std::string,2> pending;bool file_open=true;
            for(;;) {
                pollfd descriptors[2]{{0,POLLIN,0},{file_open?file_fd:-1,POLLIN,0}};
                if(::poll(descriptors,2,-1)<0){if(errno==EINTR)continue;throw std::runtime_error("Worker pipe poll failed");}
                for(unsigned i=0;i<2;++i)if(descriptors[i].revents) {
                    if(descriptors[i].revents&(POLLERR|POLLNVAL))throw std::runtime_error("Worker pipe failed");
                    char buffer[4096];const auto count=::read(descriptors[i].fd,buffer,sizeof buffer);
                    if(count<0){if(errno==EINTR)continue;throw std::runtime_error("Worker pipe read failed");}
                    if(count==0){if(!pending[i].empty())throw std::runtime_error("Truncated worker frame");if(i==0)return 0;file_open=false;continue;}
                    for(int j=0;j<count;++j) {
                        if(buffer[j]=='\n'){std::cout<<receive(pending[i],i==1)<<'\n'<<std::flush;pending[i].clear();}
                        else {if(pending[i].size()>=1024*1024)throw std::length_error("Worker frame limit");pending[i]+=buffer[j];}
                    }
                }
            }
        }
#endif
        std::string line;char byte;bool oversized=false;
        while(std::cin.get(byte)) {
            if(byte=='\n'){std::cout<<receive(oversized?std::string_view{}:std::string_view{line},false)<<'\n'<<std::flush;line.clear();oversized=false;}
            else if(line.size()<1024*1024)line+=byte;else oversized=true;
        }
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
