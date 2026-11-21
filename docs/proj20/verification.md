# 验证记录

项目在租赁服务器 `/hy-tmp/proj20` 构建和运行。环境为 Rust 1.100.0、目标 `riscv64gc-unknown-none-elf`、QEMU 6.2.0 的 TCG 模式。日志路径以租赁服务器为准，仓库内保留重跑命令和代表性串口摘录。

## 五章系统检查

| 章节 | 基础检查 | 练习检查 |
|---|---:|---:|
| ch3 系统调用计数 | 4/4 | 7/7 |
| ch4 地址空间 | 6/6 | 16/16 |
| ch5 进程创建与调度 | 14/14 | 17/17 |
| ch6 硬链接 | 15/15 | 33/33 |
| ch8 死锁检测 | 22/22 | 25/25 |

从项目根目录运行 `bash scripts/test_proj20.sh all`，脚本打印日志目录。基础 61 项、练习 98 项均由官方检查器统计。QEMU 的代表性行为见 [ch4 页表串口证据](ch4-page-permissions.md) 和 [ch8 同步串口证据](ch8-deadlock-detection.md)。

第一次完整系统检查于北京时间 2026-11-21 04:10 开始，代码版本为 `001c810`，日志在 `/hy-tmp/proj20-evidence/run-gMrS8F`。11:02 从 `bc408e4` 的干净检出复跑，十组均通过，日志在 `release-repro-CjMCOu/run-2pmnH5`。最终内核代码 `773344e9574f339609ba891bca3d65df8e7581c2` 再次从干净检出复跑，时间为北京时间 2026-11-21 11:17:16–11:23:57，159 项全部通过，日志位于 `/hy-tmp/proj20-evidence/final-18ryD6/run-N4mZWW`。两次干净检出均重新构建项目，复用服务器安装的工具链和依赖缓存。

## 组件定向检查

在 Linux 宿主机运行 `bash scripts/test_proj20_units.sh`。本次准备分发的 11 个包共运行 13 个定向用例。表格范围为本项目的发布包，系统覆盖指对应内核在 QEMU 跑过该组件所在的流程。

| 包后缀 | 定向用例数 | 验证内容 | 系统覆盖 |
|---|---:|---|---|
| ch3 | 1 | trace 计数包含调用自身、任务间隔离 | ch3 |
| ch4 | 1 | 撤销范围有空洞就拒绝，已有映射保留到合法撤销 | ch4 |
| ch5 | 1 | 调度器选择最小 stride，平局按进队顺序 | ch5 |
| ch6 | 1 | 文件名长度、NUL 结尾和 UTF-8 检查 | ch6 |
| ch8 | 2 | 重复请求、交叉等待及安全序列 | ch8 |
| kernel-vm | 1 | 页表分配失败回滚与重试 | ch4、ch5、ch6 |
| kernel-alloc | 1 | 耗尽返回空指针，释放后重新分配 | ch4、ch5、ch6、ch8 |
| task-manage | 2 | 调度机会比例、优先级边界及进度 | ch5、ch6、ch8 |
| syscall | 1 | `Stat` 的字段偏移与长度 | ch6 的 `fstat`，其余章节也执行系统调用 |
| easy-fs | 1 | 链接与打开句柄的生命周期及空间复用 | ch6 |
| sync | 1 | 中断保护状态初始化 | ch8 的互斥锁和信号量 |

组件验证在北京时间 2026-11-21 11:17 开始，提交为 `773344e9574f339609ba891bca3d65df8e7581c2`，原始终端日志在 `/hy-tmp/proj20-evidence/final-components.log`。

## 检查分发包

本项目的发布包命名为 `likepoison-proj20-*`，各版本暂定 `0.1.0`。北京时间 2026-11-21 11:17 对 11 个名称逐一查询 crates.io 索引，均返回 404。打包验证生成了 11 个 `.crate`，随后用同组解包后的依赖完成 RISC-V64 构建。各归档均含与上游根目录一致的 GPL-3.0 许可证。验收提交 `0829f0e22a0c9f19bc8b8a8991d5ab794e450d11`，原始记录为 `/hy-tmp/proj20-evidence/licensed-package.log` 与 `package-name-check.log`。

从仓库根目录复跑，依赖已缓存时可加 `--offline`。

```bash
scratch=$(mktemp -d)
git archive HEAD | tar -x -C "$scratch"
printf '\n[workspace]\nmembers = ["tg-rcore-tutorial-*"]\nresolver = "3"\n' >>"$scratch/Cargo.toml"
cd "$scratch"
export RUSTUP_TOOLCHAIN=1.100.0
packages=()
for name in ch3 ch4 ch5 ch6 ch8 task-manage kernel-vm kernel-alloc syscall easy-fs sync; do
    packages+=(-p "likepoison-proj20-$name")
done
cargo package --target riscv64gc-unknown-none-elf "${packages[@]}"
```

公共 registry 的实际提交仍需发布账户。组件发布顺序为先发 `kernel-alloc`、`kernel-vm`、`task-manage`、`syscall`、`easy-fs`，再发依赖任务组件的 `sync`，最后发五个章节。系统测试使用 Git 仓库随附的完整用户态测例。

## 参考环境对照

`d6330a6db1f81c8c1cfba5ec3db9923199398f24` 原版构建失败日志为 `/hy-tmp/proj20-evidence/reference-suites.log`。同工具链核对时，单独应用 `42bd3e8` 对用户态内联汇编的兼容修补，重新运行官方检查。兼容对照从北京时间 2026-11-21 11:13:08 跑到 11:20:12。原始输出在 `reference-compat.log` 和同目录下的 `reference-compat-1mCEan`，结果表见[设计总结](design-summary.md)。

```bash
reference=$(mktemp -d)
git archive d6330a6db1f81c8c1cfba5ec3db9923199398f24 | tar -x -C "$reference"
git show --format= 42bd3e8 -- tg-rcore-tutorial-syscall/src/user.rs |
    (cd "$reference" && patch -p1)
export TG_USER_DIR="$reference/tg-rcore-tutorial-user"
export RUSTUP_TOOLCHAIN=1.100.0 CARGO_BUILD_JOBS=4 TIMEOUT_SEC=180
for chapter in 3 4 5 6 8; do
    for suite in base exercise; do
        (
            cd "$reference/tg-rcore-tutorial-ch$chapter" &&
            timeout -k 5s 240s bash test.sh "$suite" </dev/null
        ) >"$reference/ch$chapter-$suite.log" 2>&1
        printf 'ch%s %s exit=%s\n' "$chapter" "$suite" "$?"
    done
done
```

协作问答、学习提示与未计时的样本见[学习复盘](learning-review.md)。
