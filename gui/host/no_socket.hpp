#pragma once
#include <span>
#include <stdexcept>
#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <string>
#include <string_view>
#include <vector>

#if defined(__linux__)
#include <cstddef>
#include <dirent.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace foundation::host {
inline bool no_socket_boundary_active() {
#if defined(__linux__)
    return prctl(PR_GET_SECCOMP)==SECCOMP_MODE_FILTER && prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)==1;
#else
    return false;
#endif
}
inline void verify_anonymous_pipe(int fd,bool input) {
#if defined(__linux__)
    struct stat st{};if(fstat(fd,&st)!=0 || !S_ISFIFO(st.st_mode))throw std::runtime_error("worker transport requires actual anonymous pipes");
    const auto path="/proc/self/fd/"+std::to_string(fd);char target[128]{};const auto n=readlink(path.c_str(),target,sizeof(target)-1);
    if(n<=6 || std::string_view(target,static_cast<std::size_t>(n)).substr(0,6)!="pipe:[")throw std::runtime_error("named pipes are not worker transports");
    const auto flags=fcntl(fd,F_GETFL);if(flags<0 || (flags&O_ACCMODE)!=(input?O_RDONLY:O_WRONLY))throw std::runtime_error("worker pipe has incorrect access mode");
#else
    (void)fd;(void)input;throw std::runtime_error("no-socket worker is not qualified for this platform");
#endif
}
inline void restrict_descriptors(std::span<const int> retained) {
#if defined(__linux__)
    // /proc enumerates inherited descriptors without opening or probing them.
    // In particular no socket operation is needed to detect a socket handle.
    DIR* directory=opendir("/proc/self/fd");if(!directory)throw std::runtime_error("cannot enumerate inherited worker descriptors");
    const int listing=dirfd(directory);std::vector<int> close_list;
    errno=0;
    while(auto* item=readdir(directory)) {
        char* end=nullptr;const auto value=std::strtol(item->d_name,&end,10);
        if(!end||*end||value<0||value>2147483647)continue;
        const auto fd=static_cast<int>(value);
        if(fd!=listing && std::find(retained.begin(),retained.end(),fd)==retained.end())close_list.push_back(fd);
    }
    const auto error=errno;closedir(directory);if(error)throw std::runtime_error("cannot enumerate inherited worker descriptors");
    for(int fd:close_list)if(close(fd)!=0 && errno!=EBADF)throw std::runtime_error("cannot close inherited worker descriptor");
    bool invalid=false;
    for(int fd:retained) {
        struct stat st{};
        if(fstat(fd,&st)!=0){invalid=true;continue;}
        if(S_ISSOCK(st.st_mode)) {
            // Close every retained socket before throwing: stderr itself may
            // be a socket and exception handling must not write into it.
            ::close(fd);invalid=true;
        }
    }
    if(invalid)throw std::runtime_error("invalid or socket descriptor retained by worker");
#else
    (void)retained;throw std::runtime_error("no-socket worker is not qualified for this platform");
#endif
}
#if defined(__linux__)
inline std::vector<sock_filter> no_socket_filter() {
#if defined(__x86_64__)
    constexpr auto architecture=AUDIT_ARCH_X86_64;
#elif defined(__aarch64__)
    constexpr auto architecture=AUDIT_ARCH_AARCH64;
#elif defined(__arm__)
    constexpr auto architecture=AUDIT_ARCH_ARM;
#elif defined(__i386__)
    constexpr auto architecture=AUDIT_ARCH_I386;
#else
    throw std::runtime_error("worker no-socket filter has no qualified architecture");
    return {};
#endif
#if defined(__x86_64__) || defined(__aarch64__) || defined(__arm__) || defined(__i386__)
    std::vector<sock_filter> filters{
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(seccomp_data,arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,architecture,1,0),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(seccomp_data,nr)),
    };
    const auto deny=[&](int syscall){filters.push_back(BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,static_cast<unsigned>(syscall),0,1));filters.push_back(BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM));};
#if defined(__x86_64__)
    // x32 shares AUDIT_ARCH_X86_64 but uses a different syscall namespace.
    filters.push_back(BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K,0x40000000,0,1));
    filters.push_back(BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM));
#endif
#ifdef SYS_socket
    deny(SYS_socket);
#endif
#ifdef SYS_socketpair
    deny(SYS_socketpair);
#endif
#ifdef SYS_socketcall
    deny(SYS_socketcall);
#endif
#ifdef SYS_bind
    deny(SYS_bind);
#endif
#ifdef SYS_connect
    deny(SYS_connect);
#endif
#ifdef SYS_listen
    deny(SYS_listen);
#endif
#ifdef SYS_accept
    deny(SYS_accept);
#endif
#ifdef SYS_accept4
    deny(SYS_accept4);
#endif
#ifdef SYS_sendto
    deny(SYS_sendto);
#endif
#ifdef SYS_sendmsg
    deny(SYS_sendmsg);
#endif
#ifdef SYS_sendmmsg
    deny(SYS_sendmmsg);
#endif
#ifdef SYS_recvfrom
    deny(SYS_recvfrom);
#endif
#ifdef SYS_recvmsg
    deny(SYS_recvmsg);
#endif
#ifdef SYS_recvmmsg
    deny(SYS_recvmmsg);
#endif
#ifdef SYS_shutdown
    deny(SYS_shutdown);
#endif
#ifdef SYS_getsockname
    deny(SYS_getsockname);
#endif
#ifdef SYS_getpeername
    deny(SYS_getpeername);
#endif
#ifdef SYS_getsockopt
    deny(SYS_getsockopt);
#endif
#ifdef SYS_setsockopt
    deny(SYS_setsockopt);
#endif
#ifdef SYS_io_uring_setup
    deny(SYS_io_uring_setup);deny(SYS_io_uring_enter);deny(SYS_io_uring_register);
#endif
#ifdef SYS_pidfd_getfd
    deny(SYS_pidfd_getfd);
#endif
#ifdef SYS_ptrace
    deny(SYS_ptrace);
#endif
#ifdef SYS_bpf
    deny(SYS_bpf);
#endif
    filters.push_back(BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW));
    return filters;
#endif
}
#endif
inline void install_no_socket_boundary() {
#if defined(__linux__)
    auto filters=no_socket_filter();
    sock_fprog program{static_cast<unsigned short>(filters.size()),filters.data()};
    if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)!=0 || prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program)!=0 || !no_socket_boundary_active())throw std::runtime_error("cannot install required no-socket worker boundary");
#else
    throw std::runtime_error("no-socket worker is not qualified for this platform");
#endif
}
}
