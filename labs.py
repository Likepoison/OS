"""Six exercises with fixed output contracts and editable C samples."""
from textwrap import dedent


def lab(title, summary, source, fault, normal, boundary, required):
    return {
        "title": title, "summary": summary, "required": required,
        "sample": dedent(source).strip() + "\n",
        "fault": fault,
        "cases": [
            {"name": "常规用例", "stdin": normal[0], "expected": normal[1]},
            {"name": "边界用例", "stdin": boundary[0], "expected": boundary[1]},
        ],
    }


LABS = {
    "pipe": lab(
        "进程与管道", "父进程从子进程的管道逐段读取，收到 EOF 后退出。输出应与输入一致。",
        r"""
        #include <stdio.h>
        #include <stdlib.h>
        #include <sys/wait.h>
        #include <unistd.h>

        int main(void) {
            char input[96], buffer[32];
            if (!fgets(input, sizeof input, stdin)) input[0] = '\0';
            int fd[2];
            if (pipe(fd) == -1) return 1;
            pid_t child = fork();
            if (child == -1) return 1;
            if (child == 0) {
                close(fd[0]);
                for (char *p = input; *p; ++p)
                    if (write(fd[1], p, 1) != 1) _exit(2);
                close(fd[1]);
                _exit(0);
            }
            close(fd[1]);  /* Parent write end */
            ssize_t n;
            while ((n = read(fd[0], buffer, sizeof buffer)) > 0)
                if (write(STDOUT_FILENO, buffer, (size_t)n) != n) return 2;
            close(fd[0]);
            int status;
            if (waitpid(child, &status, 0) == -1) return 2;
            return n < 0 || !WIFEXITED(status) || WEXITSTATUS(status) != 0;
        }
        """,
        ("close(fd[1]);  /* Parent write end */", "/* Parent write end left open */"),
        ("kernel lab\n", "kernel lab\n"), ("", ""),
        (("pipe", "pipe2"), ("clone", "fork", "vfork"), ("wait4", "waitid")),
    ),
    "file": lab(
        "文件读写", "将一行输入写入临时文件，再通过文件描述符读回并输出。空输入也要正确处理。",
        r"""
        #define _POSIX_C_SOURCE 200809L
        #include <fcntl.h>
        #include <stdio.h>
        #include <unistd.h>

        int main(void) {
            unsigned char value;
            int fd = open("/tmp/job/data.txt", O_CREAT | O_RDWR | O_TRUNC, 0600);
            if (fd < 0) return 1;
            while (read(STDIN_FILENO, &value, 1) == 1)
                if (write(fd, &value, 1) != 1) return 2;
            if (lseek(fd, 0, SEEK_SET) < 0) return 3;
            ssize_t size;
            while ((size = read(fd, &value, 1)) > 0)
                if (write(STDOUT_FILENO, &value, 1) != 1) return 4;
            return close(fd) != 0 || size < 0;
        }
        """,
        ("if (lseek(fd, 0, SEEK_SET) < 0) return 3;", "close(fd);\n    if (lseek(fd, 0, SEEK_SET) < 0) return 3;"),
        ("file demo\n", "file demo\n"), ("", ""),
        (("openat", "open"), ("lseek",), ("read",)),
    ),
    "mutex": lab(
        "线程同步", "两个线程各增加共享计数 N 次，主线程等待两者结束并输出 2N。",
        r"""
        #include <pthread.h>
        #include <stdio.h>

        static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
        static int count, iterations;

        static void *worker(void *arg) {
            (void)arg;
            for (int i = 0; i < iterations; ++i) {
                pthread_mutex_lock(&lock);
                ++count;
                pthread_mutex_unlock(&lock);
            }
            return NULL;
        }

        int main(void) {
            if (scanf("%d", &iterations) != 1 || iterations < 0) return 1;
            pthread_t first, second;
            if (pthread_create(&first, NULL, worker, NULL)) return 2;
            if (pthread_create(&second, NULL, worker, NULL)) return 2;
            if (pthread_join(first, NULL) || pthread_join(second, NULL)) return 3;
            printf("%d\n", count);
            return 0;
        }
        """,
        ("pthread_mutex_unlock(&lock);", "/* Lock remains held */"),
        ("8\n", "16\n"), ("0\n", "0\n"), (("clone", "clone3"),),
    ),
    "memory": lab(
        "内存分配", "输入指定申请的字节数，每页写入一次后释放，输出实际处理的字节数。",
        r"""
        #include <stdio.h>
        #include <stdlib.h>

        int main(void) {
            size_t bytes;
            if (scanf("%zu", &bytes) != 1) return 1;
            volatile unsigned char *area = malloc(bytes ? bytes : 1);
            if (!area) return 2;
            for (size_t offset = 0; offset < bytes; offset += 4096) area[offset] = 1;
            free((void *)area);
            printf("%zu\n", bytes);
            return 0;
        }
        """,
        ("volatile unsigned char *area = malloc(bytes ? bytes : 1);",
         "bytes = 256 * 1024 * 1024;\n    volatile unsigned char *area = malloc(bytes);"),
        ("16384\n", "16384\n"), ("0\n", "0\n"), (),
    ),
    "schedule": lab(
        "轮转调度", "在用户态模拟两个任务的轮转，每轮每个未完成任务执行一个时间片，按顺序输出任务字母。",
        r"""
        #include <sched.h>
        #include <stdio.h>

        int main(void) {
            int remaining[2];
            if (scanf("%d%d", &remaining[0], &remaining[1]) != 2) return 1;
            if (remaining[0] < 0 || remaining[1] < 0) return 1;
            while (remaining[0] || remaining[1]) {
                for (int i = 0; i < 2; ++i) {
                    if (remaining[i] == 0) continue;
                    putchar('A' + i);
                    --remaining[i];
                    sched_yield();
                }
            }
            putchar('\n');
            return 0;
        }
        """,
        ("for (int i = 0; i < 2; ++i)", "for (int i = 1; i >= 0; --i)"),
        ("3 2\n", "ABABA\n"), ("0 2\n", "BB\n"), (),
    ),
    "deadlock": lab(
        "死锁与锁顺序", "两个线程使用相同的加锁顺序更新共享值。主线程输出两次更新的总和。",
        r"""
        #include <pthread.h>
        #include <stdio.h>

        static pthread_mutex_t first = PTHREAD_MUTEX_INITIALIZER;
        static pthread_mutex_t second = PTHREAD_MUTEX_INITIALIZER;
        static int value, increment;

        static void *worker(void *arg) {
            (void)arg;
            pthread_mutex_lock(&first);
            pthread_mutex_lock(&second);
            value += increment;
            pthread_mutex_unlock(&second);
            pthread_mutex_unlock(&first);
            return NULL;
        }

        int main(void) {
            if (scanf("%d", &increment) != 1) return 1;
            pthread_t a, b;
            if (pthread_create(&a, NULL, worker, NULL)) return 2;
            if (pthread_create(&b, NULL, worker, NULL)) return 2;
            if (pthread_join(a, NULL) || pthread_join(b, NULL)) return 3;
            printf("%d\n", value);
            return 0;
        }
        """,
        ("pthread_mutex_lock(&second);", "pthread_mutex_lock(&first);  /* Self-deadlock */"),
        ("7\n", "14\n"), ("0\n", "0\n"), (("clone", "clone3"),),
    ),
}


def sample(lab, broken=False):
    return lab["sample"].replace(*lab["fault"], 1) if broken else lab["sample"]
