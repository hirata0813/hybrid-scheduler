#include <iostream>
#include <unistd.h>
#include <cstdlib>
#include <sys/syscall.h>
#include <time.h>
#include <cstdint>
#include <linux/sched.h>

unsigned long long fibonacci(int n) {
    if (n <= 1) {
        return 1;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

static inline uint64_t timespec_to_ns(const struct timespec& ts)
{
    return (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}

int main(int argc, char *argv[]) {
    //struct sched_param param = {0};
    //if (sched_setscheduler(0, SCHED_EXT, &param) != 0) {
    //    perror("sched_setscheduler(SCHED_EXT) failed");
    //    return -1;
    //}
    int arg = atoi(argv[1]);
    int idx = atoi(argv[2]);


    //struct timespec start, end;

    //clock_gettime(CLOCK_MONOTONIC_RAW, &start);

    unsigned long long result = fibonacci(arg);

    //clock_gettime(CLOCK_MONOTONIC_RAW, &end);

    //uint64_t tasknew = timespec_to_ns(start);
    //uint64_t taskdead = timespec_to_ns(end);

    pid_t tid = syscall(SYS_gettid);
   std::cout
       << "idx=" << idx
       << " tid=" << tid
       << " n=" << arg
       << " result=" << result
        //<< " tasknew=" << tasknew // これは，純粋な CFS で計測するときに必要な処理
        //<< " taskdead=" << taskdead // これは，純粋な CFS で計測するときに必要な処理
       << std::endl;

    return 0;
}
