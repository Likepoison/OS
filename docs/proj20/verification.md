# 验证记录

租赁服务器工作区为 `/hy-tmp/proj20`。本轮验收代码版本为 `001c81080ba79ff3111dc134e06df5d4beb35f69`，使用 Rust 1.100.0、裸机目标 `riscv64gc-unknown-none-elf` 和 QEMU 6.2.0 的 TCG 模式。

## 官方章测试

| 章节 | 基础检查 | 练习检查 |
|---|---:|---:|
| ch3 系统调用计数 | 4/4 | 7/7 |
| ch4 地址空间 | 6/6 | 16/16 |
| ch5 进程创建与调度 | 14/14 | 17/17 |
| ch6 硬链接 | 15/15 | 33/33 |
| ch8 死锁检测 | 22/22 | 25/25 |

这些数字是官方检查器报告的通过项。可用 `bash scripts/test_proj20.sh all` 重跑，脚本会给出日志目录。2026-11-21 04:10（北京时间）启动的一次完整运行退出码为 0，十组通过项合计 159/159。串口日志与环境记录在 `/hy-tmp/proj20-evidence/run-gMrS8F`。

四组宿主机定向测试共六例，覆盖页表分配失败回滚、stride 的优先级边界与比例、最后一个硬链接与文件句柄关闭后的复用，以及重复加锁、交叉等待和安全顺序。汇总在 `final-unit.log`。ch4 和 ch8 的带调试日志运行分别示范页表拒绝与死锁拒绝，原始日志为 `rental-ch4-trace.log`、`rental-ch8-fixed-exercise.log`。

## 打包与解包构建

用 Git 归档在服务器上生成临时 Cargo workspace。圈定五个内核 crate 以及 `kernel-vm`、`kernel-alloc`、`task-manage`、`syscall`、`easy-fs`，对同一组包运行 `cargo package --target riscv64gc-unknown-none-elf`。十个包都通过归档和解包后的构建检查。日志为 `package-workspace.log`。

```bash
root=$(mktemp -d)
git archive HEAD | tar -x -C "$root"
printf '\n[workspace]\nmembers = ["tg-rcore-tutorial-*"]\nresolver = "3"\n' >>"$root/Cargo.toml"
cd "$root"
export RUSTUP_TOOLCHAIN=1.100.0
packages=()
for name in ch3 ch4 ch5 ch6 ch8 task-manage kernel-vm kernel-alloc syscall easy-fs; do
    packages+=(-p "tg-rcore-tutorial-$name")
done
cargo package --target riscv64gc-unknown-none-elf "${packages[@]}"
```

单独验证 ch4 时，目前 crates.io 上的上游版本缺少本项目新增的 `sv39` 与 `try_allocate` 接口。分发时需要将同组依赖随版本一起交付。以上命令是打包构建验证，公开 registry 的命名与版本发布尚未执行。

## 从故障到复验

- ch4 最初把计数数组内联到进程结构，调度时触发内核栈边界页故障。将计数放到堆上恢复了执行，页表分配回滚通过注入失败测试。
- ch5 连续 `spawn` 曾耗尽物理页。补齐进程退出与 `exec` 的地址空间回收后，保留原测例并通过回归。
- ch6 最后一个目录项删除后，已打开的句柄继续读取文件，最后一个句柄关闭后再回收。使用内存块设备实际检查了 inode 和数据块复用。
- ch8 原参考练习停在重复加锁。内核在真实入队前返回 `-0xDEAD` 后，同一用例能解锁并结束，官方安全序列也能继续。

教学效率和本校对照需要实际完成记录，采集方法见 [学习复盘与对照](learning-review.md)。
