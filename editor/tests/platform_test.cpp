#include "platform/project_files.hpp"
#include "platform/process_runner.hpp"
#include "platform/content_digest.hpp"

#include <chrono>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>
#if defined(__linux__)
#include <signal.h>
#include <sys/types.h>
#include <unistd.h>
#endif

using namespace foundation::editor;
namespace {
void check(bool value,const char* message) { if(!value) throw std::runtime_error(message); }
template<class F> void fails(FileFailure expected,F&& function) {
    try { function(); } catch(const FileError& failure) { check(failure.code()==expected,"Unexpected file error category"); return; }
    throw std::runtime_error("Expected file operation failure");
}
void raw_write(const std::filesystem::path& path,std::string_view text) {
    std::ofstream file(path,std::ios::binary); file.write(text.data(),static_cast<std::streamsize>(text.size())); if(!file) throw std::runtime_error("Fixture write failed");
}
ProcessStatus finish(ProcessRunner& process) {
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    while(std::chrono::steady_clock::now()<deadline) {
        auto status=process.poll(); if(status.finished()) return status;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    (void)process.cancel(); throw std::runtime_error("Owned child completion timed out");
}
}
int main(int argc,char** argv) {
#if defined(__linux__)
    if(argc>=2 && std::string_view(argv[1])=="--child") {
        const std::string_view mode=argc>=3?argv[2]:"";
        if(mode=="ok") { std::cout << (argc>=4?argv[3]:""); return 0; }
        if(mode=="fail") { std::cerr << "expected failure"; return 7; }
        if(mode=="noisy") { const std::string chunk(4096,'x'); for(int i=0;i<700;++i) std::cout << chunk; return 0; }
        if(mode=="wait") { ::signal(SIGTERM,SIG_IGN); for(;;) ::pause(); }
        if(mode=="tree") {
            const auto child=::fork(); if(child<0) return 9;
            if(!child) { ::setsid(); ::signal(SIGTERM,SIG_IGN); for(;;) ::pause(); }
            std::cout << "ready" << std::flush; for(;;) ::pause();
        }
        if(mode=="outlive") {
            const auto child=::fork(); if(child<0) return 9;
            if(!child) { ::setsid(); for(;;) ::pause(); }
            return 0;
        }
        return 8;
    }
#endif
    try {
        const auto root=std::filesystem::temp_directory_path()/ ("foundation editor platform fixture "+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code error; std::filesystem::permissions(path,std::filesystem::perms::owner_all,error); std::filesystem::remove_all(path,error); } } cleanup{root};
        ProjectFiles files(root);
        check(detail::content_digest("")=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","SHA-256 empty vector failed");
        check(detail::content_digest("abc")=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad","SHA-256 abc vector failed");
        check(detail::content_digest(std::string(1000000,'a'))=="cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0","SHA-256 multiblock vector failed");
        files.ensure_directory("source/deep");
        check(files.directory(".")==std::filesystem::canonical(root),"Root process directory did not resolve");
        check(files.directory("source/deep")==std::filesystem::canonical(root)/"source/deep","Nested process directory did not resolve");
        fails(FileFailure::missing,[&]{(void)files.directory("missing-directory");});
        fails(FileFailure::invalid_path,[&]{(void)files.directory("../outside");});
        fails(FileFailure::invalid_path,[&]{(void)files.directory("source/../outside");});
        fails(FileFailure::invalid_path,[&]{(void)files.directory("/absolute");});
        fails(FileFailure::invalid_path,[&]{(void)files.directory("");});
        const std::string text="\xef\xbb\xbf"+std::string(100000,'a')+" café λ 😀\r\n";
        auto empty=files.inspect("source/deep/example.cpp"); check(!empty.identity.exists,"Inspect created missing leaf");
        auto original=files.save(empty,text); check(files.read(original.path).text==text,"Save altered UTF-8/CRLF/BOM bytes");
        fails(FileFailure::invalid_path,[&]{(void)files.directory(original.path);});
        CodeBuffer buffer(original); buffer.replace(text.size()-2,2,"\n"); check(buffer.dirty(),"Code edit did not set dirty");
        check(buffer.undo() && buffer.text()==text && !buffer.dirty(),"Undo did not restore original");
        check(buffer.redo() && buffer.dirty(),"Redo failed"); check(buffer.find("café")!=std::string::npos,"UTF-8 find failed");
        buffer.save(files); check(!buffer.dirty(),"Successful save did not reset dirty");
        buffer.set_text("unsaved text"); raw_write(root/original.path,"foreign text");
        fails(FileFailure::conflict,[&]{buffer.save(files);}); check(buffer.text()=="unsaved text" && buffer.dirty(),"Conflict lost unsaved source");
        check(files.read(original.path).text=="foreign text","Conflict overwrote foreign source");
        auto before_replace=files.read(original.path); std::filesystem::rename(root/original.path,root/"moved.cpp"); raw_write(root/original.path,before_replace.text);
        fails(FileFailure::conflict,[&]{(void)files.save(before_replace,"new");});
        auto before_delete=files.read(original.path); std::filesystem::remove(root/original.path);
        fails(FileFailure::conflict,[&]{(void)files.save(before_delete,"new");});
        fails(FileFailure::missing,[&]{(void)files.read("missing.cpp");});
        for(const auto* path:{"../outside","/absolute","source/../outside","source/./file","bad\\name"}) fails(FileFailure::invalid_path,[&]{(void)files.inspect(path);});
        fails(FileFailure::encoding,[&]{(void)files.save(files.inspect("invalid.cpp"),"\xc0\xaf");});
        fails(FileFailure::encoding,[&]{(void)files.save(files.inspect("invalid.cpp"),"\xed\xa0\x80");});
        ProjectFiles small(root,10); fails(FileFailure::limit,[&]{(void)small.save(small.inspect("big.cpp"),std::string(11,'a'));});
        auto readonly=files.save(files.inspect("readonly.cpp"),"original");
        std::filesystem::permissions(root/readonly.path,std::filesystem::perms::owner_read);
        readonly=files.read(readonly.path); fails(FileFailure::permission,[&]{(void)files.save(readonly,"replacement");});
        std::filesystem::permissions(root/readonly.path,std::filesystem::perms::owner_all);
        files.ensure_directory("read-only-directory");
        auto blocked=files.inspect("read-only-directory/new.cpp");
        std::filesystem::permissions(root/"read-only-directory",std::filesystem::perms::owner_read | std::filesystem::perms::owner_exec);
        fails(FileFailure::permission,[&]{(void)files.save(blocked,"new");});
        std::filesystem::permissions(root/"read-only-directory",std::filesystem::perms::owner_all);
        std::filesystem::create_directory_symlink(root/"source",root/"alias");
        fails(FileFailure::invalid_path,[&]{(void)files.inspect("alias/deep/example.cpp");});
        fails(FileFailure::invalid_path,[&]{(void)files.directory("alias");});
        fails(FileFailure::invalid_path,[&]{(void)files.directory("alias/deep");});
        std::filesystem::create_symlink(root/"readonly.cpp",root/"link.cpp");
        fails(FileFailure::invalid_path,[&]{(void)files.read("link.cpp");});
        fails(FileFailure::invalid_path,[&]{files.ensure_directory("alias/new");});
        auto design=files.inspect("design.json"),output=files.inspect("generated.cpp");
        auto results=files.save_batch({{output,"generated 1\n"}},{design,"revision 1\n"});
        check(results.size()==2 && files.read(design.path).text=="revision 1\n" && !files.recovery_pending(),"Batch failed to finish marker/journal");
        output=files.read(output.path); design=files.read(design.path);
        raw_write(root/output.path,"foreign generated");
        fails(FileFailure::conflict,[&]{(void)files.save_batch({{output,"generated 2\n"}},{design,"revision 2\n"});});
        check(files.read(design.path).text=="revision 1\n" && !files.recovery_pending(),"Failed preflight changed marker");
        // Reproduce an interrupted journal after an output was published, before
        // its final marker. Recovery verifies backups and finishes the revision.
        auto next_design=files.read(design.path); const auto old_output=files.read(output.path);
        auto old_stage=files.save(files.inspect(".foundation-editor-batch-fixture-0.old"),old_output.text);
        auto new_stage=files.save(files.inspect(".foundation-editor-batch-fixture-0.new"),"generated recovered\n");
        (void)files.save(files.inspect(".foundation-editor-batch-fixture-1.old"),next_design.text);
        (void)files.save(files.inspect(".foundation-editor-batch-fixture-1.new"),"revision recovered\n");
        std::ostringstream journal; journal<<"foundation-editor-batch 1 2\n";
        auto record=[&](const FileSnapshot& snapshot,int i,std::string_view new_bytes) {
            const auto& id=snapshot.identity;
            journal<<'"'<<snapshot.path.generic_string()<<"\" \".foundation-editor-batch-fixture-"<<i<<".old\" \".foundation-editor-batch-fixture-"<<i<<".new\" "
                   <<id.exists<<' '<<id.device<<' '<<id.object<<' '<<id.size<<' '<<id.modified_seconds<<' '<<id.modified_nanoseconds<<' '<<id.permissions<<' '
                   <<detail::content_digest(snapshot.text)<<' '<<detail::content_digest(new_bytes)<<'\n';
        };
        record(old_output,0,new_stage.text); record(next_design,1,"revision recovered\n");
        (void)files.save(files.inspect(".foundation-editor-journal"),journal.str());
        (void)files.save(old_output,new_stage.text); check(files.recovery_pending(),"Interrupted journal not detected");
        files.recover_batch(); check(!files.recovery_pending() && files.read(design.path).text=="revision recovered\n","Recovery did not finish final marker");
        (void)old_stage;
#if defined(__linux__)
        const auto executable=std::filesystem::canonical(argv[0]); ProcessRunner process(65536);
        process.start({executable.string(),"--child","ok","literal $(no shell); café"},files.directory("."));
        auto status=finish(process); check(status.state==ProcessState::succeeded && status.output=="literal $(no shell); café","Argument-array child failed");
        process.start({executable.string(),"--child","fail"},root); status=finish(process); check(status.state==ProcessState::failed && status.exit_code==7 && status.output=="expected failure","Failed command lost diagnostics");
        process.start({executable.string(),"--child","noisy"},root); status=finish(process); check(status.state==ProcessState::succeeded && status.output_truncated && status.output.size()==65536,"Noisy command blocked or escaped log bound");
        process.start({"definitely-no-such-foundation-editor-executable"},root); status=finish(process); check(status.state==ProcessState::failed && status.exit_code==127,"Missing executable reported success");
        process.start({executable.string(),"--child","wait"},root); status=process.cancel(); check(status.state==ProcessState::cancelled && !process.running(),"Immediate cancel did not join child ownership");
        process.start({executable.string(),"--child","tree"},root);
        const auto tree_deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        while(process.poll().output!="ready" && std::chrono::steady_clock::now()<tree_deadline) std::this_thread::sleep_for(std::chrono::milliseconds(2));
        check(process.poll().output=="ready","Owned descendant fixture never started");
        status=process.cancel(); check(status.state==ProcessState::cancelled && !process.running(),"Cancellation did not join escaped-session descendant");
        process.start({executable.string(),"--child","outlive"},root); status=finish(process); check(status.state==ProcessState::failed && status.error.find("descendants")!=std::string::npos,"Escaped-session grandchild ownership was missed");
        for(int i=0;i<5;++i) { process.start({executable.string(),"--child","ok","repeat"},root); check(finish(process).state==ProcessState::succeeded,"Repeated process ownership failed"); }
#endif
        std::cout<<"editor platform checks passed\n"; return 0;
    } catch(const std::exception& failure) { std::cerr<<failure.what()<<'\n'; return 1; }
}
