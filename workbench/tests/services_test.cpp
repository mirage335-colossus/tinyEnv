#include "core/services.hpp"
#include "editor/platform/process_runner.hpp"

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#if defined(__linux__)
#include <signal.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

using namespace tinyenv;
namespace {
void check(bool okay, const char* message) { if (!okay) throw std::runtime_error(message); }
void write(const std::filesystem::path& path, std::string_view text) {
    std::ofstream stream(path, std::ios::binary);
    stream.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!stream) throw std::runtime_error("Cannot write local service fixture");
}
template<class F> void throws(F&& function, const char* message) {
    try { function(); } catch (const std::exception&) { return; }
    throw std::runtime_error(message);
}
template<class T> auto finish(T& service) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (std::chrono::steady_clock::now() < deadline) {
        const auto status = service.poll();
        if (status.finished()) return status;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    (void)service.cancel();
    throw std::runtime_error("Local service fixture timed out");
}
JobStatus partial_until(Job& job, std::string_view expected) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (std::chrono::steady_clock::now() < deadline) {
        const auto status = job.poll();
        if (status.streaming && status.partial_text == expected) {
            check(status.state == ServiceState::running && !status.response,
                  "Streaming preview became visible only after completion");
            return status;
        }
        if (status.finished()) throw std::runtime_error("Local stream finished before its expected preview");
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    (void)job.cancel();
    throw std::runtime_error("Local streaming preview timed out");
}
void local_command(const std::vector<std::string>& args, const std::filesystem::path& cwd) {
    foundation::editor::ProcessRunner process;
    process.start(args, cwd);
    check(finish(process).state == foundation::editor::ProcessState::succeeded, "Local Git fixture failed");
}
#if defined(__linux__)
TerminalStatus output_until(Terminal& terminal, std::string_view expected) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (std::chrono::steady_clock::now() < deadline) {
        auto status = terminal.drain();
        if (status.output.find(expected) != std::string::npos) return status;
        if (!status.running) throw std::runtime_error("Bash fixture exited before producing output: " + status.error);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    terminal.shutdown();
    throw std::runtime_error("Bash fixture output timed out");
}
#endif
struct Environment {
    std::string key;
    std::optional<std::string> old;
    Environment(std::string name, const std::string& value) : key(std::move(name)) {
        if (const auto* before = std::getenv(key.c_str())) old = before;
#if defined(_WIN32)
        if (_putenv_s(key.c_str(), value.c_str())) throw std::runtime_error("Cannot set fixture environment");
#else
        if (::setenv(key.c_str(), value.c_str(), 1)) throw std::runtime_error("Cannot set fixture environment");
#endif
    }
    ~Environment() {
#if defined(_WIN32)
        _putenv_s(key.c_str(), old ? old->c_str() : "");
#else
        if (old) ::setenv(key.c_str(), old->c_str(), 1); else ::unsetenv(key.c_str());
#endif
    }
};
}

int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() /
            ("tinyenv native services " + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(root);
        struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ignored; std::filesystem::remove_all(path, ignored); } } cleanup{root};
const auto worker = root / "local worker.py";
        write(worker, R"PY(import json, os, stat, sys, time
assert sys.flags.isolated and sys.flags.no_user_site
assert sys.argv[1] == '--request'
with open(sys.argv[2], encoding='utf-8') as stream:
    request = json.load(stream)
operation = request['operation']
if operation in ('chat', 'agent'):
    fixture = request.get('fixture', 'complete')
    def frame(event, sequence, **fields):
        value = dict(stream_version=1, event=event, sequence=sequence, **fields)
        print(json.dumps(value, ensure_ascii=False), flush=True)
    if fixture in ('legacy', 'pretty-legacy'):
        print(json.dumps({'ok': True, 'text': 'Legacy completed text'},
                         indent=2 if fixture == 'pretty-legacy' else None), flush=True)
        sys.exit(0)
    if fixture == 'wrong-start-operation':
        frame('start', 0, operation='evaluate')
        time.sleep(60)
        sys.exit(0)
    frame('start', 0, operation=operation)
    if fixture == 'empty':
        frame('final', 1, result={'ok': True, 'text': ''})
        sys.exit(0)
    if fixture == 'fragmented':
        raw = json.dumps(dict(stream_version=1, event='delta', sequence=1,
                              text='First café λ', replace=False), ensure_ascii=False).encode('utf-8')
        split = raw.index('é'.encode('utf-8')) + 1
        sys.stdout.buffer.write(raw[:split]); sys.stdout.buffer.flush()
        time.sleep(0.05)
        sys.stdout.buffer.write(raw[split:] + b'\n'); sys.stdout.buffer.flush()
    else:
        frame('delta', 1, text='First café λ', replace=False)
    if fixture in ('complete', 'fragmented'):
        time.sleep(0.2)
        frame('final', 2, result={'ok': True, 'text': 'First café λ + final reconciliation'})
    elif fixture == 'replace':
        time.sleep(0.1)
        frame('delta', 2, text='', replace=True)
        frame('delta', 3, text='New candidate', replace=False)
        time.sleep(0.2)
        frame('final', 4, result={'ok': True, 'text': 'New candidate'})
    elif fixture == 'hold-stream':
        sys.stdout.write('{"stream_version":1,"event":"delta","sequence":2,"text":"unfinished')
        sys.stdout.flush()
        time.sleep(60)
    elif fixture == 'no-final':
        pass
    elif fixture == 'failed-final':
        frame('final', 2, result={'ok': False, 'text': '', 'error': 'Expected streamed failure'})
        sys.exit(7)
    elif fixture == 'nonzero':
        frame('final', 2, result={'ok': True, 'text': 'First café λ'})
        sys.exit(7)
    elif fixture == 'truncated':
        print('x' * 10000, flush=True)
        time.sleep(60)
    elif fixture in ('frame-limit', 'too-many-frames'):
        maximum = 4096 if fixture == 'frame-limit' else 4097
        for sequence in range(2, maximum + 1):
            frame('delta', sequence, text='', replace=False)
        frame('final', maximum + 1, result={'ok': True, 'text': 'First café λ'})
    elif fixture in ('exact-delta-limit', 'oversized-delta', 'escaped-exact', 'escaped-oversized'):
        empty = dict(stream_version=1, event='delta', sequence=2, text='', replace=True)
        allowance = 16384 - len(json.dumps(empty, ensure_ascii=False).encode('utf-8')) - 1
        if fixture in ('escaped-exact', 'escaped-oversized'):
            count, remainder = divmod(allowance, 6)
            text = '\x01' * count + 'x' * remainder
        else:
            text = 'x' * allowance
        if fixture in ('oversized-delta', 'escaped-oversized'): text += 'x'
        frame('delta', 2, text=text, replace=True)
        frame('final', 3, result={'ok': True, 'text': text})
    elif fixture == 'duplicate-final':
        frame('final', 2, result={'ok': True, 'text': 'First café λ'})
        frame('final', 3, result={'ok': True, 'text': 'First café λ'})
        time.sleep(60)
    elif fixture == 'unterminated-final':
        sys.stdout.write(json.dumps(dict(stream_version=1, event='final', sequence=2,
                                        result={'ok': True, 'text': 'First café λ'})))
    elif fixture == 'wrong-operation':
        frame('start', 2, operation='evaluate')
        time.sleep(60)
    else:
        value = dict(stream_version=1, event='delta', sequence=2, text='sensitive malformed progress', replace=False)
        if fixture == 'sequence-gap': value['sequence'] = 3
        elif fixture == 'duplicate-sequence': value['sequence'] = 1
        elif fixture == 'wrong-version': value['stream_version'] = 2
        elif fixture == 'wrong-text': value['text'] = 42
        elif fixture == 'wrong-replace': value['replace'] = 'yes'
        elif fixture == 'unknown-field': value['unexpected'] = 'sensitive malformed progress'
        elif fixture == 'missing-replace': del value['replace']
        elif fixture == 'unknown-event': value['event'] = 'provider-secret'
        elif fixture == 'nul-text': value['text'] = 'sensitive\x00malformed'
        elif fixture == 'duplicate-key':
            print('{"stream_version":1,"event":"delta","sequence":2,"sequence":3,"text":"sensitive","replace":false}', flush=True)
            time.sleep(60)
            sys.exit(0)
        print(json.dumps(value), flush=True)
        time.sleep(60)
elif operation == 'hold':
    time.sleep(60)
elif operation == 'scratch-hold':
    import subprocess
    scratch = os.path.join(os.path.dirname(sys.argv[2]), 'scratch')
    code = "import os,sys,time\nwith open(sys.argv[1], 'w') as stream:\n stream.write(str(os.getpid()));stream.flush()\n while True:\n  stream.write('.');stream.flush();time.sleep(0.01)\n"
    subprocess.Popen([sys.executable, '-I', '-B', '-c', code, os.path.join(scratch, 'writer.log')])
    time.sleep(60)
elif operation == 'invalid':
    print('sensitive diagnostic must never reach the UI')
elif operation == 'noisy':
    print('x' * 10000)
elif operation == 'fail':
    print(json.dumps({'ok': False, 'error': 'Expected local failure'}))
    sys.exit(7)
elif operation == 'image-envelope':
    payload = request['images'][0]['data_base64']
    assert len(payload) == 9 * 1024 * 1024 and payload == 'A' * (len(payload) - 1) + 'Z'
    print(json.dumps({'ok': True, 'text': 'Bounded image envelope received.'}))
else:
    if operation == 'retain':
        with open(os.path.join(os.path.dirname(sys.argv[2]), 'retained-fixture'), 'w') as stream:
            stream.write('owned local cleanup fixture')
    if operation == 'scratch-link':
        scratch = os.path.join(os.path.dirname(sys.argv[2]), 'scratch')
        os.rmdir(scratch)
        os.symlink(request['target'], scratch, target_is_directory=True)
    print(json.dumps({'ok': True, 'text': request['prompt'], 'root': request['root'],
                      'startup_arguments': sys.argv[3:],
                      'request_mode': stat.S_IMODE(os.stat(sys.argv[2]).st_mode),
                      'directory_mode': stat.S_IMODE(os.stat(os.path.dirname(sys.argv[2])).st_mode)}))
)PY");
#if defined(__linux__) || defined(_WIN32)
        Job job(65536, worker);
        check(!job.running() && job.poll().state == ServiceState::idle, "Constructing a job launched a process");
        json::Value request(json::Value::Object{{"operation", "echo"}, {"prompt", "literal $(never shell); café λ"}, {"root", "incorrect"}});
        job.start(request, root);
        auto status = finish(job);
        check(status.state == ServiceState::succeeded && status.response, "Local worker request failed");
        check(status.response->find("text")->string() == "literal $(never shell); café λ", "Request text changed or was evaluated as shell");
        check(status.response->find("root")->string() == std::filesystem::canonical(root).string(), "Worker cwd root was not bound to the selected project");
#if defined(__linux__)
        check(status.response->find("request_mode")->number() == 0600 && status.response->find("directory_mode")->number() == 0700,
              "Runtime request was not private");
#endif
        check(std::filesystem::is_empty(root / ".tinyenv"), "Completed runtime request was retained");
        {
            // Exercise the native transport above its old 8 MiB limit without
            // providers or an image decoder. Content validation belongs to the
            // core/provider fixtures; this worker verifies all bytes arrived.
            std::string payload(9 * 1024 * 1024, 'A'); payload.back() = 'Z';
            json::Value image_request(json::Value::Object{{"operation", "image-envelope"},
                {"images", json::Value::Array{json::Value::Object{{"mime_type", "image/png"},
                    {"data_base64", std::move(payload)}}}}});
            job.start(image_request, root);
            const auto received = finish(job);
            check(received.state == ServiceState::succeeded && received.response &&
                  received.response->find("text")->string() == "Bounded image envelope received.",
                  "Native runtime transport truncated or rejected the image request envelope");
            check(std::filesystem::is_empty(root / ".tinyenv"), "Completed image request retained its private bytes");
            image_request.object()["images"] = json::Value::Array{json::Value::Object{{"mime_type", "image/png"},
                {"data_base64", std::string(16 * 1024 * 1024, 'A')}}};
            throws([&] { job.start(image_request, root); }, "Oversized image request bypassed the native envelope cap");
            check(!job.running() && std::filesystem::is_empty(root / ".tinyenv"),
                  "Rejected oversized image request launched a worker or retained private bytes");
        }
        auto credentials = request;
        credentials.object()["settings"] = json::Value::Object{{"provider", "fixture"}, {"api_key", "private-token"}};
        throws([&] { job.start(credentials, root); }, "Credential-bearing runtime request was accepted");
        check(std::filesystem::is_empty(root / ".tinyenv"), "Rejected credentials created a request file");
        auto redirected_credentials = request;
        redirected_credentials.object()["settings"] = json::Value::Object{{"credential_directory", "untrusted-path"}};
        throws([&] { job.start(redirected_credentials, root); }, "Request data selected a credential store");
        throws([&] { Job relative(65536, worker, {}, "relative-config"); }, "Relative credential directory was accepted");
        const auto private_config = root / "configuration with spaces";
        Job private_job(65536, worker, {}, private_config);
        private_job.start(request, root);
        const auto private_status = finish(private_job);
        check(private_status.state == ServiceState::succeeded && private_status.response, "Trusted private configuration launch failed");
        const auto& startup_arguments = private_status.response->find("startup_arguments")->array();
        check(startup_arguments.size() == 2 && startup_arguments[0].string() == "--credential-directory" &&
              startup_arguments[1].string() == private_config.string(), "Credential directory was not an exact separate startup argument");
        check(!std::filesystem::exists(private_config), "Job eagerly created or read a credential store");
        request.object()["operation"] = "retain";
        job.start(request, root); status = finish(job);
        check(status.state == ServiceState::failed && status.error.find("cleanup failed") != std::string::npos,
              "Retained private request state was silently reported as success");
        const auto retained_directory = std::filesystem::directory_iterator(root / ".tinyenv")->path();
        check(std::filesystem::exists(retained_directory / "retained-fixture"), "Cleanup erased unrecognized worker output");
        std::filesystem::remove(retained_directory / "retained-fixture");
        request.object()["operation"] = "invalid";
        job.start(request, root); status = finish(job);
        check(status.state == ServiceState::failed && status.error.find("sensitive") == std::string::npos && !status.response,
              "Invalid worker output leaked into the error message");
        request.object()["operation"] = "fail";
        job.start(request, root); status = finish(job);
        check(status.state == ServiceState::failed && status.exit_code == 7 && status.error == "Expected local failure", "Worker failure was not preserved");
        request.object()["operation"] = "hold";
        job.start(request, root);
        throws([&] { job.start(request, root); }, "Running runtime job was replaced");
        status = job.cancel();
        check(status.state == ServiceState::cancelled && !job.running() && std::filesystem::is_empty(root / ".tinyenv"),
              "Runtime cancellation did not join and remove its request");
        request.object()["operation"] = "scratch-hold";
        job.start(request, root);
        const auto scratch_directory = std::filesystem::directory_iterator(root / ".tinyenv")->path() / "scratch";
        const auto scratch_log = scratch_directory / "writer.log";
        const auto scratch_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while ((!std::filesystem::exists(scratch_log) || !std::filesystem::file_size(scratch_log)) && std::chrono::steady_clock::now() < scratch_deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        check(std::filesystem::exists(scratch_log) && std::filesystem::file_size(scratch_log) > 0, "Scratch writer fixture never started");
#if defined(__linux__)
        std::ifstream scratch_pid_file(scratch_log); int scratch_pid = 0; scratch_pid_file >> scratch_pid;
        check(scratch_pid > 0 && ::kill(scratch_pid, 0) == 0, "Scratch child writer was not running");
#endif
        status = job.cancel();
        check(status.state == ServiceState::cancelled && !std::filesystem::exists(scratch_directory) && std::filesystem::is_empty(root / ".tinyenv"),
              "Cancellation left owned transcription scratch outputs");
#if defined(__linux__)
        check(::kill(scratch_pid, 0) != 0 && errno == ESRCH, "Scratch cleanup preceded descendant joining");
#endif
        Job small(100, worker);
        request.object()["operation"] = "noisy";
        small.start(request, root); status = finish(small);
        check(status.state == ServiceState::failed && status.error.find("byte limit") != std::string::npos, "Noisy runtime output exceeded its bound");
        json::Value streamed(json::Value::Object{{"operation", "chat"}, {"stream", true}, {"fixture", "complete"}});
        for (const auto* fixture : {"complete", "fragmented"}) {
            streamed.object()["fixture"] = fixture;
            job.start(streamed, root);
            const auto preview = partial_until(job, "First café λ");
            check(preview.stream_revision > 0, "Streaming content had no revision identity");
            status = finish(job);
            check(status.state == ServiceState::succeeded && status.response && status.streaming &&
                  status.partial_text == "First café λ + final reconciliation" && status.stream_revision > preview.stream_revision,
                  "Validated streaming final content did not reconcile the running preview");
            check(std::filesystem::is_empty(root / ".tinyenv"), "Completed stream retained its private request");
        }
        streamed.object()["operation"] = "agent";
        streamed.object()["fixture"] = "replace";
        job.start(streamed, root);
        const auto first_candidate = partial_until(job, "First café λ");
        const auto replacement_candidate = partial_until(job, "New candidate");
        check(replacement_candidate.stream_revision > first_candidate.stream_revision,
              "New agent candidate lacked a new preview revision");
        status = finish(job);
        check(status.state == ServiceState::succeeded && status.partial_text == "New candidate",
              "Agent replacement concatenated an obsolete candidate");
        streamed.object()["operation"] = "chat";
        for (const auto* fixture : {"legacy", "pretty-legacy"}) {
            streamed.object()["fixture"] = fixture;
            job.start(streamed, root); status = finish(job);
            check(status.state == ServiceState::succeeded && status.response && !status.streaming &&
                  status.partial_text.empty() && status.stream_revision == 0 && status.response->find("text")->string() == "Legacy completed text",
                  "Requested streaming rejected a legacy single-JSON worker");
        }
        streamed.object()["fixture"] = "failed-final";
        job.start(streamed, root); status = finish(job);
        check(status.state == ServiceState::failed && status.exit_code == 7 && status.response &&
              status.error == "Expected streamed failure" && status.partial_text == "First café λ",
              "Failed final discarded the accepted assistant preview");
        streamed.object()["fixture"] = "nonzero";
        job.start(streamed, root); status = finish(job);
        check(status.state == ServiceState::failed && status.exit_code == 7 && status.partial_text == "First café λ",
              "Successful final incorrectly hid a failed worker exit");
        for (const auto* fixture : {"no-final", "unterminated-final", "duplicate-final", "wrong-operation", "sequence-gap",
                                   "duplicate-sequence", "wrong-version", "wrong-text", "wrong-replace", "unknown-field",
                                   "missing-replace", "unknown-event", "nul-text", "duplicate-key", "oversized-delta", "escaped-oversized"}) {
            streamed.object()["fixture"] = fixture;
            job.start(streamed, root); status = finish(job);
            check(status.state == ServiceState::failed && !status.response && status.streaming &&
                  status.partial_text == "First café λ" && status.error.find("sensitive") == std::string::npos &&
                  std::filesystem::is_empty(root / ".tinyenv"),
                  "Malformed stream leaked data, lost valid partial content or failed to join/clean its worker");
        }
        streamed.object()["fixture"] = "hold-stream";
        job.start(streamed, root);
        (void)partial_until(job, "First café λ");
        status = job.cancel();
        check(status.state == ServiceState::cancelled && status.streaming && status.partial_text == "First café λ" &&
              !job.running() && std::filesystem::is_empty(root / ".tinyenv"),
              "Cancelled stream lost valid partial content or retained its worker/request");
        Job stream_small(512, worker);
        streamed.object()["fixture"] = "truncated";
        stream_small.start(streamed, root); status = finish(stream_small);
        check(status.state == ServiceState::failed && status.error.find("byte limit") != std::string::npos &&
              status.partial_text == "First café λ" && std::filesystem::is_empty(root / ".tinyenv"),
              "Truncated stream escaped bounds, lost valid progress or failed cleanup");
        for (const auto* fixture : {"exact-delta-limit", "escaped-exact"}) {
            streamed.object()["fixture"] = fixture;
            job.start(streamed, root); status = finish(job);
            check(status.state == ServiceState::succeeded && !status.partial_text.empty() && status.partial_text.size() < 16384,
                  "The supported maximum encoded delta frame size was rejected");
        }
        streamed.object()["fixture"] = "wrong-start-operation";
        job.start(streamed, root); status = finish(job);
        check(status.state == ServiceState::failed && !status.streaming && status.partial_text.empty() && !status.response &&
              std::filesystem::is_empty(root / ".tinyenv"), "Streaming start did not match the requested operation");
        streamed.object()["fixture"] = "empty";
        job.start(streamed, root); status = finish(job);
        check(status.state == ServiceState::succeeded && status.streaming && status.partial_text.empty() && status.stream_revision == 0,
              "An empty successful stream did not remain distinct from a legacy worker");
        Job many_frames(1024 * 1024, worker);
        streamed.object()["fixture"] = "frame-limit";
        many_frames.start(streamed, root); status = finish(many_frames);
        check(status.state == ServiceState::succeeded, "The supported maximum stream delta count was rejected");
        streamed.object()["fixture"] = "too-many-frames";
        many_frames.start(streamed, root); status = finish(many_frames);
        check(status.state == ServiceState::failed && !status.response && status.partial_text == "First café λ" &&
              std::filesystem::is_empty(root / ".tinyenv"), "Unbounded stream frame count was accepted");
        streamed.object()["stream"] = false;
        streamed.object()["fixture"] = "no-final";
        job.start(streamed, root); status = finish(job);
        check(status.state == ServiceState::failed && !status.streaming && status.partial_text.empty(),
              "A worker enabled streaming without an explicit streaming request");
        streamed.object()["stream"] = "true";
        throws([&] { job.start(streamed, root); }, "A nonboolean native streaming request was accepted");
        streamed.object()["stream"] = true;
        streamed.object()["operation"] = "evaluate";
        throws([&] { job.start(streamed, root); }, "An unsupported operation enabled native streaming");
#if defined(__linux__)
        const auto outside_scratch = root / "outside scratch";
        std::filesystem::create_directory(outside_scratch);
        write(outside_scratch / "keep.txt", "must remain\n");
        request.object()["operation"] = "scratch-link";
        request.object()["target"] = outside_scratch.string();
        job.start(request, root); status = finish(job);
        check(status.state == ServiceState::succeeded && std::filesystem::exists(outside_scratch / "keep.txt") && std::filesystem::is_empty(root / ".tinyenv"),
              "Runtime scratch cleanup followed a symlink target");
        const auto linked_root = root / "linked";
        std::filesystem::create_directory(linked_root);
        std::filesystem::create_directory_symlink(root / ".tinyenv", linked_root / ".tinyenv");
        throws([&] { job.start(request, linked_root); }, "Runtime state symlink was accepted");
#endif

        const auto repo = root / "local repository";
#if defined(_WIN32)
        Environment global_config("GIT_CONFIG_GLOBAL", "NUL");
#else
        Environment global_config("GIT_CONFIG_GLOBAL", "/dev/null");
#endif
        Environment system_config("GIT_CONFIG_NOSYSTEM", "1");
        Environment injected_config("GIT_CONFIG_COUNT", "0");
        std::filesystem::create_directory(repo);
        local_command({"git", "init", "--quiet", repo.string()}, root);
        write(repo / "original name.txt", "original\n");
        local_command({"git", "-c", "core.fsmonitor=false", "-C", repo.string(), "add", "--", "original name.txt"}, root);
        local_command({"git", "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                       "-C", repo.string(), "commit", "--quiet", "-m", "Local fixture"}, root);
        std::filesystem::rename(repo / "original name.txt", repo / "renamed name.txt");
        local_command({"git", "-c", "core.fsmonitor=false", "-C", repo.string(), "add", "--all"}, root);
        write(repo / "untracked.txt", "untracked\n");
        const auto monitor = repo / "fsmonitor.sh";
        write(monitor, "#!/bin/sh\nprintf invoked > fsmonitor-was-run\n");
        std::filesystem::permissions(monitor, std::filesystem::perms::owner_all);
        local_command({"git", "-C", repo.string(), "config", "core.fsmonitor", monitor.string()}, root);
        const auto filter = repo / "clean-filter.sh";
        write(filter, "#!/bin/sh\nprintf invoked > filter-was-run\ncat\n");
        std::filesystem::permissions(filter, std::filesystem::perms::owner_all);
        local_command({"git", "-C", repo.string(), "config", "filter.fixture.clean", filter.string()}, root);
        const auto trace_log = repo / "unrequested-trace.json";
        local_command({"git", "-C", repo.string(), "config", "trace2.eventTarget", trace_log.string()}, root);
        GitStatusJob git;
        check(git.poll().state == ServiceState::idle, "Constructing Git status launched a process");
        git.start(repo);
        auto git_status = finish(git);
        check(git_status.state == ServiceState::succeeded && !git_status.branch.empty(), "Unused configured Git filter prevented read-only status");
        bool renamed = false, untracked = false;
        for (const auto& file : git_status.files) {
            if (file.path == "renamed name.txt") renamed = file.index_status == 'R' && file.original_path == "original name.txt";
            if (file.path == "untracked.txt") untracked = file.index_status == '?' && file.worktree_status == '?';
        }
        check(renamed && untracked, "Git status lost rename or untracked paths");
        check(!std::filesystem::exists(repo / "fsmonitor-was-run"), "Git status ran a configured filesystem monitor");
        check(!std::filesystem::exists(trace_log), "Git inspection wrote a configured tracing file");
        local_command({"git", "-C", repo.string(), "config", "--unset", "trace2.eventTarget"}, root);
        local_command({"git", "-C", repo.string(), "config", "remote.fixture.promisor", "true"}, root);
        git.start(repo); git_status = finish(git);
        check(git_status.state == ServiceState::failed && git_status.error.find("promisor") != std::string::npos,
              "Git status did not refuse a promisor remote before possible lazy fetch");
        local_command({"git", "-C", repo.string(), "config", "--unset", "remote.fixture.promisor"}, root);
        local_command({"git", "-C", repo.string(), "config", "extensions.partialClone", "fixture"}, root);
        git.start(repo); git_status = finish(git);
        check(git_status.state == ServiceState::failed && git_status.error.find("partial clones") != std::string::npos,
              "Git status did not refuse partial-clone configuration");
        local_command({"git", "-C", repo.string(), "config", "--unset", "extensions.partialClone"}, root);
        const auto promisor_marker = repo / ".git" / "objects" / "pack" / "fixture.promisor";
        write(promisor_marker, "");
        git.start(repo); git_status = finish(git);
        check(git_status.state == ServiceState::failed && git_status.error.find("local object store") != std::string::npos,
              "Git status ignored a promisor object inventory marker");
        std::filesystem::remove(promisor_marker);
        write(repo / ".gitattributes", "*.txt filter=fixture\n");
        write(repo / "renamed name.txt", "modified\n");
        git.start(repo); git_status = finish(git);
        check(git_status.state == ServiceState::failed && git_status.error.find("content filters") != std::string::npos &&
              !std::filesystem::exists(repo / "filter-was-run"), "Git status executed a repository-configured content filter");
        {
#if defined(_WIN32)
            Environment redirected_config("GIT_CONFIG", "NUL");
#else
            Environment redirected_config("GIT_CONFIG", "/dev/null");
#endif
            git.start(repo); git_status = finish(git);
            check(git_status.state == ServiceState::failed && git_status.error.find("content filters") != std::string::npos &&
                  !std::filesystem::exists(repo / "filter-was-run"), "Ambient GIT_CONFIG hid an active Git content filter");
            check(std::getenv("GIT_CONFIG") != nullptr, "Git child sanitization changed the parent environment");
        }
        local_command({"git", "-C", repo.string(), "config", "--add", "filter.fixture.clean", ""}, root);
        git.start(repo); git_status = finish(git);
        check(git_status.state == ServiceState::succeeded && !std::filesystem::exists(repo / "filter-was-run"),
              "A final empty Git filter definition was treated as an active command");
        local_command({"git", "-C", repo.string(), "config", "--add", "filter.fixture.clean", filter.string()}, root);
        for (const auto* ambiguous_driver : {"unset", "unspecified"}) {
            local_command({"git", "-C", repo.string(), "config", std::string("filter.") + ambiguous_driver + ".clean", filter.string()}, root);
            write(repo / ".gitattributes", std::string("*.txt filter=") + ambiguous_driver + "\n");
            git.start(repo); git_status = finish(git);
            check(git_status.state == ServiceState::failed && git_status.error.find("content filters") != std::string::npos &&
                  !std::filesystem::exists(repo / "filter-was-run"), "A literal Git filter name bypassed the attribute safety check");
        }
#if defined(__linux__)
        write(root / "git", "#!/bin/sh\nprintf invoked > git-was-run\nexit 0\n");
        std::filesystem::permissions(root / "git", std::filesystem::perms::owner_all);
        {
            const auto* inherited_path = ::getenv("PATH");
            Environment untrusted_path("PATH", ":" + root.string() + ":" + (inherited_path ? inherited_path : "/usr/bin:/bin"));
            git.start(root); git_status = finish(git);
            check(git_status.state == ServiceState::failed && !std::filesystem::exists(root / "git-was-run"),
                  "Git status executed a project-local PATH program");
            std::filesystem::create_directory(repo / "chats");
            git.start(repo / "chats", root); git_status = finish(git);
            check(git_status.state == ServiceState::failed && git_status.error.find("content filters") != std::string::npos &&
                  !std::filesystem::exists(root / "git-was-run") && !std::filesystem::exists(repo / "filter-was-run"),
                  "Nested chat Git preflight missed the project trust anchor or parent attributes");
        }
#endif
        git.start(root); git_status = finish(git);
        check(git_status.state == ServiceState::failed && !git_status.error.empty(), "Nonrepository Git status reported success");
#endif

#if defined(__linux__)
        const auto bash_env = root / "untrusted-startup.sh";
        write(bash_env, "printf startup > '" + (root / "startup-was-run").string() + "'\n");
        Environment env("BASH_ENV", bash_env.string());
        Environment prompt("PROMPT_COMMAND", "printf prompt > '" + (root / "prompt-was-run").string() + "'");
        Environment before_command("PS0", "$(printf before > '" + (root / "ps0-was-run").string() + "')");
        Terminal terminal(4096), other(4096);
        check(!terminal.running() && terminal.drain().output.empty(), "Constructing a terminal launched Bash");
        throws([&] { terminal.send("echo no"); }, "Inert terminal accepted a command");
        terminal.resize(91, 33); terminal.start(root);
        check(terminal.running(), "Bash PTY could not start");
        terminal.send("TINYNATIVE_VALUE=chosen; printf '<%s>\\n' \"$TINYNATIVE_VALUE\"");
        auto terminal_status = output_until(terminal, "<chosen>");
        check(!std::filesystem::exists(root / "startup-was-run") && !std::filesystem::exists(root / "prompt-was-run") &&
              !std::filesystem::exists(root / "ps0-was-run"), "Bash executed startup environment commands");
        terminal.send("printf 'saved=<%s>\\n' \"$TINYNATIVE_VALUE\"");
        output_until(terminal, "saved=<chosen>");
        other.start(root / "local repository");
        other.send("printf 'other=<%s>\\n' \"${TINYNATIVE_VALUE-unset}\"");
        output_until(other, "other=<unset>");
        terminal.send("stty size");
        output_until(terminal, "33 91");
        terminal.resize(102, 38); terminal.send("stty size");
        output_until(terminal, "38 102");
        terminal.send("printf '\\033[31m%s%s\\033[0m\\n' 'color' 'safe'");
        terminal_status = output_until(terminal, "colorsafe");
        check(terminal_status.output.find('\33') == std::string::npos, "Terminal exposed escape sequences to the text widget");
        terminal.send("printf '%05000d\\n' 0; printf '%s%s\\n' 'bound' 'done'");
        terminal_status = output_until(terminal, "bounddone");
        check(terminal_status.output_truncated && terminal_status.output.size() <= 4096, "Terminal scrollback escaped its byte bound");
        terminal.send("sleep 60");
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        terminal.interrupt(); terminal.send("printf '%s%s\\n' 'interrupted' 'done'");
        output_until(terminal, "interrupteddone");
        terminal.send("setsid /bin/sh -c 'echo $$ > escaped.pid; exec sleep 60' >/dev/null 2>&1 < /dev/null &");
        const auto child_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!std::filesystem::exists(root / "escaped.pid") && std::chrono::steady_clock::now() < child_deadline) {
            (void)terminal.drain(); std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        std::ifstream child_file(root / "escaped.pid"); int escaped = 0; child_file >> escaped;
        check(escaped > 0 && ::kill(escaped, 0) == 0, "Escaped-session terminal fixture did not start");
        terminal.shutdown();
        check(!terminal.running() && terminal.drain().error.empty(), "Terminal shutdown failed to join descendants");
        check(::kill(escaped, 0) != 0 && errno == ESRCH, "Terminal shutdown left an escaped descendant running");
        check(other.running(), "Closing one chat terminal stopped another chat");
        other.send("printf '%s%s\\n' 'still' 'running'"); output_until(other, "stillrunning"); other.shutdown();
        terminal.start(root); terminal.send("exit 0");
        const auto exit_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (terminal.running() && std::chrono::steady_clock::now() < exit_deadline) { (void)terminal.drain(); std::this_thread::sleep_for(std::chrono::milliseconds(2)); }
        check(!terminal.running() && terminal.drain().exit_code == 0, "Terminal restart or natural exit failed");
#else
        Terminal terminal;
        terminal.start(root);
        check(!terminal.running() && !terminal.drain().error.empty(), "Unsupported terminal platform was silently accepted");
#endif
        std::cout << "native service checks passed (local fixtures only)\n";
        return 0;
    } catch (const std::exception& failure) {
        std::cerr << failure.what() << '\n';
        return 1;
    }
}
