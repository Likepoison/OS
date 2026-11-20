# ch3 追踪当前任务的系统调用

系统调用是用户程序向内核请求服务的入口。ch3 中每个任务都有自己的任务控制块，里面记录了寄存器上下文、栈和计数。本练习只查询当前任务的记录。

## 先预测，再验证

在项目根目录运行：

```bash
bash scripts/test_proj20.sh ch3
```

打开脚本打印的 `ch3-exercise.log`，找到 `Test trace OK!`。阅读 `tg-rcore-tutorial-user/src/bin/ch3_trace.rs`，比较它两次查询 `SYS_TRACE` 时的断言。

1. 先数清楚前一次查询前发生了哪些 `trace` 调用。考虑查询本身是否也属于一次调用。
2. 在 `tg-rcore-tutorial-ch3/src/task.rs` 找到从 a7 取得 syscall 编号的位置。
3. 从计数、处理、写回返回值三个动作中，判断在哪里增加计数才能得到测例要求的结果。

<details>
<summary>完成后核对</summary>

计数要发生在分发前。第一次查询 `SYS_TRACE` 时，读取时钟计数的那次查询和现在这次查询都已发生，因此返回 2。已有测试在参考实现上曾因取不到时钟调用次数而报断言失败，改动后同一用例输出 `Test trace OK!`。租赁服务器官方基础 4/4、练习 7/7。

</details>
