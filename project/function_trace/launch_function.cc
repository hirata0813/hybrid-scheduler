#include <iostream>
#include <unistd.h>
#include <cstdlib>
#include <sys/syscall.h>

unsigned long long fibonacci(int n) {
    if (n <= 1) {
        return 1;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

int main(int argc, char *argv[]) {
    int arg = atoi(argv[1]);
    int idx = atoi(argv[2]);

    pid_t tid = syscall(SYS_gettid);

    unsigned long long n = fibonacci(arg);

    std::cout
        << "idx=" << idx
        << " tid=" << tid
        << " n=" << arg
        << std::endl;

    return 0;
}
