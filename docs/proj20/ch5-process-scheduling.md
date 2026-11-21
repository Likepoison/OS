# ch5 创建进程和按优先级调度

`spawn` 从已登记的 ELF 程序创建新的进程。父进程得到新 PID，可以等待子进程结束。子进程从程序入口开始运行。处理路径参数时，内核检查涉及的每个用户页，跨页字符串也能正确读取。

Stride 调度让优先级较高的进程累加更小的步长。调度器每次选择累计值最小的就绪进程，同值时按进队顺序。课程在可协作切换的内核中观察调度次数与优先级的关系。[原始 stride 调度论文](https://waldspurger.org/carl/papers/stride-mit-tm528.pdf)

## 练习与参考答案

两个进程都处于就绪状态，优先级分别为 4 和 16。先预测 500 次调度中两者约各获得多少次机会，再运行宿主机测试和内核练习：

```bash
export RUSTUP_TOOLCHAIN=1.100.0
export TG_USER_DIR="$(pwd)/tg-rcore-tutorial-user"
cargo test --manifest-path tg-rcore-tutorial-task-manage/Cargo.toml --test test_stride
cd tg-rcore-tutorial-ch5
timeout -k 5s 180s bash test.sh exercise </dev/null
```

<details>
<summary>完成预测后查看</summary>

优先级 16 的步长是优先级 4 的四分之一。同样的累计 stride 内，前者获得四倍的调度机会。测试用整数步长得到 100 次和 400 次。真实核内调度还受运行、让出和退出时机影响。

</details>

官方基础测试 14/14、练习 17/17。最初 `ch5_spawn0` 反复创建进程时耗尽物理页。复盘时对照进程退出和 `exec` 两条路径，确认旧进程持有的物理块、各级页表和根页表必须回收。修复后原测例通过，共享传送门仍由内核地址空间持有。
