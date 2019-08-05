#include <sys/time.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h> // mkdir

void _create_socket_directory(void);
void _create_and_wait_connection(void);
void _get_batsky_time(struct timeval *batsky_tv, struct timeval *real_tv);

#define BATSKY_SOCK_DIR "/tmp/batsky"

int batsky_init = 0;

int batsky_server_sockfd, batsky_client_sockfd;
socklen_t batsky_client_len;
struct sockaddr_un batsky_server_address;
struct sockaddr_un  batsky_client_address;


/*
  0) Test if already connected: no goto 0) yes goto 5) 
  1) Create /tmp/batsky
  2) Create socket /tmp/batsky/<pid>_batsky.sock
  3) Wait for connecttion
  4) Send pid
  5) Send time
  6) Wait time
  7) Return
 */

void _create_socket_directory(void) {
    int status = mkdir(BATSKY_SOCK_DIR, S_IRWXU | S_IRWXG | S_IROTH | S_IXOTH);
    if (status) {
        perror("Create batsky sockets directory");
    }
}

void _create_and_wait_connection(void) {
    char batsky_sock_name[256];
    pid_t pid = getpid();

    /* create socket */
    snprintf(batsky_sock_name, sizeof batsky_sock_name, "%s/%d_batsky.sock", BATSKY_SOCK_DIR, pid);
    unlink(batsky_sock_name);
    batsky_server_sockfd = socket(AF_UNIX, SOCK_STREAM, 0);

    batsky_server_address.sun_family = AF_UNIX;
    strcpy(batsky_server_address.sun_path, batsky_sock_name);

    int ret = bind(batsky_server_sockfd, (struct sockaddr *)&batsky_server_address, sizeof(batsky_server_address));
    if (ret) {
        perror("Bind for batsky_socket failed");
    }
    
    listen(batsky_server_sockfd, 1);

    /*  Accept a connection.  */
    batsky_client_len = sizeof(batsky_client_address);
    batsky_client_sockfd = accept(batsky_server_sockfd, (struct sockaddr *)&batsky_client_address, &batsky_client_len);

    write(batsky_client_sockfd, &pid, 4);
}


void _get_batsky_time(struct timeval *batsky_tv, struct timeval *real_tv) {
    write(batsky_client_sockfd, &real_tv->tv_sec, 8);
    write(batsky_client_sockfd, &real_tv->tv_usec, 8);

    read(batsky_client_sockfd, &batsky_tv->tv_sec, 8);
    read(batsky_client_sockfd, &batsky_tv->tv_usec, 8);
}


void main(void) {

    struct timeval real_tv;
    struct timeval batsky_tv;

    if (batsky_init == 0) {
        _create_socket_directory();
        _create_and_wait_connection();
        batsky_init = 1;
    }
    if (gettimeofday(&real_tv, 0))
        perror("gtod");

    printf("Real time: %lu.%lu\n", real_tv.tv_sec, real_tv.tv_usec);

    
    _get_batsky_time(&batsky_tv, &real_tv);

    printf("Batsky time: %lu.%lu\n", batsky_tv.tv_sec, batsky_tv.tv_usec);

}
    /*
    FILE *cmdline = fopen("/proc/self/cmdline", "rb");
    char *arg = 0;
    size_t size = 0;
    while(getdelim(&arg, &size, 0, cmdline) != -1)
        {
            puts(arg);
        }
    free(arg);
    fclose(cmdline);

    
    printf ( "Parent : Parent’s PID: %d\n", getpid());    
    for (i=100;i>0;i--)
        if (gettimeofday(&tv, 0))
            perror("gtod");
    */
