# ch6 从两个文件名认识 inode

目录项把文件名关联到 inode 编号。两个硬链接可以有不同的名字，同时引用同一个 inode 和数据块。通过任一个名字打开文件，`fstat` 都会返回同一个 inode 编号及当前链接数。

本章参考 xv6 的回收条件。文件的最后一个目录项删除后，已打开的文件句柄可以继续读写。最后一个句柄关闭时才释放数据块并回收 inode 编号。EasyFS 从根目录项计算链接数，沿用已有磁盘布局。[MIT xv6 的 inode 回收实现](https://github.com/mit-pdos/xv6-riscv/blob/riscv/kernel/fs.c)

## 实验操作

在项目根目录用官方练习走一遍内核路径，再用内存块设备检查 inode 生命周期：

```bash
export RUSTUP_TOOLCHAIN=1.100.0
export TG_USER_DIR="$(pwd)/tg-rcore-tutorial-user"
cargo test --manifest-path tg-rcore-tutorial-easy-fs/Cargo.toml --target x86_64-unknown-linux-gnu --test test_hard_links
cd tg-rcore-tutorial-ch6
timeout -k 5s 180s bash test.sh exercise </dev/null
```

先预测下面四步的链接数。文件创建，建立第二个名字，删除第一个名字，删除最后一个名字但保留已打开的文件描述符。再阅读 `tg-rcore-tutorial-easy-fs/tests/test_hard_links.rs`，找到验证数据仍可读以及 inode 和数据块可复用的断言。

<details>
<summary>完成预测后查看</summary>

四步的链接数分别是 1、2、1、0。最后一个名字被删后，目录查找不到该文件，原文件描述符仍可读取其内容。最后一个句柄关闭后，新文件才可以复用该 inode。单元测试还重新打开同一块磁盘，核对已经保存的目录项与链接数。

</details>

租赁服务器实测官方基础 15/15、练习 33/33，EasyFS 硬链接测试 1/1。当前是单级目录教学文件系统，未验证断电或崩溃时的孤儿 inode 恢复。
