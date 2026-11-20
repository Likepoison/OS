# 云端启动验收

2026-11-20 22:53–22:54（Asia/Shanghai），GitHub Codespaces。原租赁服务器的 SSH 在认证前拒绝连接，未取得其运行权限结论。

- 代码目录 `/workspaces/proj20`，分支 `proj20`，参考提交 `d6330a6db1f81c8c1cfba5ec3db9923199398f24`，GPL-3.0。
- Codespace 为 2 vCPU，约 7.8 GiB 内存，首次测量时工作区约有 27 GiB 可用，限制编译任务数为 2。
- 实测 Rust/Cargo 1.100.0，已安装 `riscv64gc-unknown-none-elf`、`rust-src`、`llvm-tools-preview`。QEMU 7.2.22。
- 参考 ch1 从源码构建成功，两次启动都输出 `Hello, world!` 并以状态 0 退出。
- 使用 `-machine virt,accel=tcg -S` 模拟挂起，2 秒超时返回 124。日志记录收到 SIGTERM，同时用 `pgrep` 检查对应 QEMU 命令无残留。
- 同一个 Codespace 的独立 SSH 会话可读取源码和日志。保留期届满后的恢复未验证。

## 重跑

```bash
cd /workspaces/proj20/tg-rcore-tutorial-ch1
CARGO_BUILD_JOBS=2 cargo build
for run in 1 2; do
    timeout --kill-after=3s 45s cargo run || exit
done
```

原始文件在 `/workspaces/proj20-evidence`，包括 `ch1-build.log`、`ch1-run-1.log`、`ch1-run-2.log` 和 `qemu-timeout.log`。ch1 结果是环境证据。五个练习分别以各章运行结果验收。

## 租赁服务器复验

复验日志写入时间 2026-11-20 23:17:27 +0800。工作区为 `/hy-tmp/proj20`，迁移提交为 `bfa0ae37bed8cbe42b1a987154d8fe0ac82f0f54`，Git 对象检查通过。

实例配额为 9 vCPU、约 30 GiB 内存，`/hy-tmp` 初次检查约有 50 GiB 可用。Rust 1.100.0 的裸机目标、`rust-src` 和 `llvm-tools-preview` 已安装。Ubuntu 提供 QEMU 6.2.0，低于参考教程推荐的 7.0，本实例已用它通过 ch1 启动验收。每个后续实验仍以实测结果为准。

使用 QEMU TCG 运行两次，串口分别输出 `Hello, world!`，退出码均为 0。挂起场景在 2 秒后返回 124，检查无残留对应 QEMU 进程。在嵌套 SSH 终端重跑 ch1 时，给命令加 `</dev/null`，以便 QEMU 无交互运行。日志在 `/hy-tmp/proj20-evidence/rental-ch1-noninteractive.log`。

从当前客户端直连公开 SSH 端口会在握手前重置。JupyterLab 可登录同一实例，从 Codespace 中转到同一实例的 SSH 握手、主机指纹核对和密码验证也已通过。历史 ch3/ch4 验收日志在 `/hy-tmp/proj20-evidence/codespace-baseline`。

ch3 已在同一台租赁服务器重新运行，官方检查器报告基础 4/4、练习 7/7。日志文件为 `rental-ch3-base.log` 和 `rental-ch3-exercise.log`，均保存在 `/hy-tmp/proj20-evidence`。
