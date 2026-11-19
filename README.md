# TraceTutor

面向 proj56 的操作系统实验工作台。提交 C 源码后，Python 服务安排独立 Docker 容器编译运行，使用 strace 跟踪进程树，并按固定用例评分。页面提供调用证据、三层提示和实验记录。

## 按需演示

在 GitHub 仓库的 **Code → Codespaces** 选择含本项目代码的分支，创建或恢复双核 Codespace，等待实验镜像构建。终端运行：

```bash
python app.py
```

在 **Ports** 中打开 8000 端口的私有预览。建议演示「进程与管道」故障样例，运行后打开关联事件与分层提示，再切换正确样例重跑并查看实验记录。演示结束后停止 Codespace。

有 Docker 的 Linux 虚拟机也可运行。要求 Docker 支持 cgroup v2，Python 3.10 或更新版本。

```bash
docker build -t tracetutor-sandbox .
python3 app.py
```

只有显式勾选「请求 AI 提示」时才尝试调用模型。真实 AI 需要在 Codespaces Secret 或演示终端环境中设置 `DEEPSEEK_API_KEY`。模型收到实验名称、诊断及结构化证据编号，原始代码、参数和日志留在演示环境。未配置、请求失败或引用校验失败时显示规则提示。

## 验收

| 赛题评分项 | 可复现检查 |
| --- | --- |
| 核心功能 40 | 进程管道、线程同步、内存、文件 I/O、轮转调度、死锁六类实验。每类正确与故障源码分别跑常规和边界用例 |
| 系统观测 20 | strace 事件回溯原始日志，覆盖子进程、合并 unfinished/resumed、区分已确认与疑似结论。调度实验在用户态模拟策略 |
| AI 教学 20 | 观察方向、相关原理、证据定位三层提示。CI 测试证据校验和规则降级，真实模型需另行联调 |
| 稳定性 10 | Actions 实测容器 CPU／内存／PID 限额、超时和子进程清理，两任务并行。单实例演示最多两个任务同时运行，队列总容量八个 |
| 文档演示 10 | 本页启动步骤、预置样例、浏览器端到端测试。报告与录屏按赛制单独准备 |

使用 [Actions](https://github.com/Likepoison/OS/actions) 查看自动验收。运行记录与日志按用例限长，保存在运行环境本地的 SQLite，未提交源码和凭据不会写入记录库。部署面向受控、私有演示。

## 赛题参考

- [Docker 资源约束](https://docs.docker.com/engine/containers/resource_constraints/)用于配置和实测 CPU、内存、交换空间及进程数上限。
- [strace 手册](https://man7.org/linux/man-pages/man1/strace.1.html)与 [ptrace 手册](https://man7.org/linux/man-pages/man2/ptrace.2.html)用于跟踪进程树、解码描述符并判定采集和权限边界。
- 题目提供的 [Go](https://go.dev/doc/)、[PostgreSQL](https://www.postgresql.org/docs/current/installation.html)、[MinIO](https://docs.min.io/aistor/installation/linux/install/) 是参考选项。按需演示使用 Python 和 SQLite。
