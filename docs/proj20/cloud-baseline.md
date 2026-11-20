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
