#include "host/no_socket.hpp"
#include <sys/socket.h>
#include <sys/wait.h>
#include <iostream>
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
int main(){try{
    int pipes[2];check(pipe(pipes)==0,"pipe failed");
    foundation::host::verify_anonymous_pipe(pipes[0],true);
    foundation::host::verify_anonymous_pipe(pipes[1],false);
    bool rejected=false;try{foundation::host::verify_anonymous_pipe(pipes[0],false);}catch(const std::runtime_error&){rejected=true;}check(rejected,"Wrong pipe direction accepted");
    int sockets[2];check(socketpair(AF_UNIX,SOCK_STREAM,0,sockets)==0,"fixture socket failed");
    rejected=false;try{foundation::host::verify_anonymous_pipe(sockets[0],true);}catch(const std::runtime_error&){rejected=true;}check(rejected,"Socket accepted as pipe");
    const auto socket_error_child=fork();check(socket_error_child>=0,"fork failed");
    if(socket_error_child==0) {
        if(dup2(sockets[0],2)!=2)_exit(2);
        try{const int retained[]{0,1,2};foundation::host::restrict_descriptors(retained);_exit(3);}
        catch(const std::runtime_error&){_exit(fcntl(2,F_GETFD)==-1&&errno==EBADF?0:4);}
    }
    int socket_error_status=0;
    check(waitpid(socket_error_child,&socket_error_status,0)==socket_error_child&&WIFEXITED(socket_error_status)&&WEXITSTATUS(socket_error_status)==0,"Socket retained as stderr was accepted");
    const auto child=fork();check(child>=0,"fork failed");
    if(child==0)try{
        const int retained[]{pipes[0],pipes[1]};foundation::host::restrict_descriptors(retained);
        check(fcntl(sockets[0],F_GETFD)==-1&&errno==EBADF,"Inherited socket survived");
        foundation::host::install_no_socket_boundary();
        for(int domain:{AF_UNIX,AF_INET,AF_INET6})check(socket(domain,SOCK_STREAM,0)==-1&&errno==EPERM,"Socket creation escaped filter");
        int pair[2];check(socketpair(AF_UNIX,SOCK_STREAM,0,pair)==-1&&errno==EPERM,"Socket pair escaped filter");
#ifdef SYS_io_uring_setup
        check(syscall(SYS_io_uring_setup,0,nullptr)==-1&&errno==EPERM,"io_uring escaped filter");
#endif
#ifdef SYS_pidfd_getfd
        check(syscall(SYS_pidfd_getfd,-1,0,0)==-1&&errno==EPERM,"External descriptor acquisition escaped filter");
#endif
#if defined(__x86_64__)
        check(syscall(0x40000000U|SYS_getpid)==-1&&errno==EPERM,"x32 namespace escaped filter");
#endif
        char value='x';check(write(pipes[1],&value,1)==1,"Pipe write denied");check(read(pipes[0],&value,1)==1&&value=='x',"Pipe read denied");_exit(0);
    }catch(...){_exit(1);}
    int status=0;check(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0,"Isolated child boundary checks failed");
    for(int fd:{pipes[0],pipes[1],sockets[0],sockets[1]})close(fd);
    std::cout<<"Anonymous pipe identity, inherited descriptor closure, no socket families, alternative acquisition denial and pipe I/O passed\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
