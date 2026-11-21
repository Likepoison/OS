# 云端复现实验

所有命令在 Linux 云端终端运行。在本次验收服务器上，代码位于 `/hy-tmp/proj20`。下面以 Ubuntu 的管理员终端为例。

```bash
apt-get update
apt-get install -y qemu-system-misc build-essential curl git
curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o /tmp/proj20-rustup.sh
sh /tmp/proj20-rustup.sh -y --profile minimal --default-toolchain none
. "$HOME/.cargo/env"
rustup toolchain install 1.100.0 --profile minimal \
  --component rust-src --component llvm-tools-preview \
  --target riscv64gc-unknown-none-elf
export RUSTUP_TOOLCHAIN=1.100.0
cargo install --locked cargo-binutils --version 0.4.0
```

进入项目根目录，安装项目内锁定的检查器，再运行第一章和一组练习：

```bash
cargo install --path tg-rcore-tutorial-checker
(cd tg-rcore-tutorial-ch1 && timeout -k 3s 45s cargo run </dev/null)
bash scripts/test_proj20.sh ch3
bash scripts/test_proj20_units.sh
```

第一章应打印 `Hello, world!` 并正常退出。脚本会打印日志目录，里面包含 Rust/QEMU 版本、Git 提交和两个串口检查日志。五章连跑用 `bash scripts/test_proj20.sh all`。仓库已包含用户态测例，脚本直接使用同一份测例源码。

租赁服务器实测使用 Rust 1.100.0 和 QEMU 6.2.0 的 TCG 模式。此前 Codespace 的参考内核使用 QEMU 7.2.22 验证。可写目录、进程执行权限和依赖下载也需要在相应云环境验证。
