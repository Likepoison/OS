#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static int probe_pids(void) {
    pid_t children[32];
    size_t count = 0;
    int blocked = 0;

    while (count < sizeof children / sizeof children[0]) {
        pid_t child = fork();
        if (child < 0) {
            blocked = (errno == EAGAIN);
            break;
        }
        if (child == 0) {
            for (;;) pause();
        }
        children[count++] = child;
    }
    for (size_t i = 0; i < count; i++) {
        kill(children[i], SIGKILL);
        if (waitpid(children[i], NULL, 0) != children[i]) return 1;
    }
    printf("pids: started=%zu, blocked=%d\n", count, blocked);
    return !(count > 0 && blocked);
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "pids") == 0) return probe_pids();
    if (argc > 1 && strcmp(argv[1], "memory") == 0) {
        size_t length = 64 * 1024 * 1024;
        volatile char *memory = malloc(length);
        if (!memory) return 2;
        for (size_t i = 0; i < length; i += 4096) memory[i] = 1;
        return 3;
    }

    pid_t child = fork();
    if (child < 0) return 1;
    if (argc > 1 && strcmp(argv[1], "hang") == 0) {
        if (child == 0) {
            if (setsid() == -1) _exit(2);
            if (write(STDOUT_FILENO, "detached\n", 9) != 9) _exit(3);
        }
        for (;;) pause();
    }
    if (child == 0) _exit(write(STDOUT_FILENO, "child-ok\n", 9) == 9 ? 0 : 1);
    int status;
    return waitpid(child, &status, 0) == child && WIFEXITED(status)
        ? WEXITSTATUS(status)
        : 1;
}
