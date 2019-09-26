#include <sys/time.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h> // mkdir
#include <time.h>
#include <emmintrin.h>

void _create_and_wait_connection(void);
void _get_batsky_time(struct timeval *tv);
int _gettimeofday (struct timeval *tv);


#define BATSKY_SOCK_DIR "/tmp/batsky"

int batsky_init = 0;

int batsky_server_sockfd, batsky_client_sockfd;
socklen_t batsky_client_len;
struct sockaddr_un batsky_server_address;
struct sockaddr_un  batsky_client_address;

//static pthread_mutex_t batsky_mutex = PTHREAD_MUTEX_INITIALIZER;
static int batsky_lock = 0;
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


void ___spin_lock(int volatile *p)
{
    while(!__sync_bool_compare_and_swap(p, 0, 1))
    {
        // spin read-only until a cmpxchg might succeed
        while(*p) _mm_pause();  // or maybe do{}while(*p) to pause first
    }
}

void ___spin_unlock(int volatile *p)
{
    asm volatile ("":::"memory"); // acts as a memory barrier.
    *p = 0;
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

    int n = write(batsky_client_sockfd, &pid, 4);
    if (n != 4) perror("Write incomplete");
}

void _get_batsky_time(struct timeval *tv) {
    int n;
    // Ask batsky
    n = write(batsky_client_sockfd, &tv->tv_sec, 8);
    if (n != 8) perror("Write incomplete");
    n = write(batsky_client_sockfd, &tv->tv_usec, 8);
    if (n != 8) perror("Write incomplete");
    // Receive simulated time
    n = read(batsky_client_sockfd, &tv->tv_sec, 8);
    if (n != 8) perror("Read incomplete");
    n = read(batsky_client_sockfd, &tv->tv_usec, 8);
    if (n != 8) perror("Read incomplete");
}

int _gettimeofday (struct timeval *tv) {

    int ret = gettimeofday(tv, 0);

    //pthread_mutex_lock(&batsky_mutex);
    ___spin_lock(&batsky_lock);
     /* if BATSKY_SOCK_DIR does not exist return the orginal gettimeofday's result */
    if( access( BATSKY_SOCK_DIR, F_OK ) != -1 ) {
        if (batsky_init == 0) {
            _create_and_wait_connection();
            batsky_init = 1;
        }  
        _get_batsky_time(tv);
    }
    ___spin_unlock(&batsky_lock);
    //pthread_mutex_unlock(&batsky_mutex);
    return ret;
}


int main(void) {

    int i;
    struct timeval tv;
 
    for (i=0; i<1000; i++) {
        if (_gettimeofday(&tv))
            perror("gtod");
        printf("%d: %lu.%06lu\n", i, tv.tv_sec, tv.tv_usec);
        //nanosleep((const struct timespec[]){{0, 1 * 1000000L}}, NULL);
    }
    return 0;
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
