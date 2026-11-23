# TraceTutor

参赛全称为《TraceTutor——操作系统实验评测与智能诊断平台》。

面向 proj56 的操作系统实验工作台。提交 C 源码后，Python 服务安排独立 Docker 容器编译运行，使用 strace 跟踪进程树，并按固定用例评分。页面提供调用证据、三层提示和实验记录。

## 赛题

- **赛题编号** `proj56`
- **官方题名** 《基于云原生架构与 AI 协同的操作系统在线学习平台设计与实现》

赛题要求搭建操作系统实验在线评测与 AI 辅助诊断平台。平台在隔离环境中运行学生提交的程序，采集系统调用并执行测试，再结合判定和轨迹提供分层排查提示，并支持查询实验记录。

[官方赛题列表（西北区域赛，查看 proj56）](https://os.educg.net/#/sList?TYPE=26OS_XB)

## 按需演示

[用 GitHub Codespaces 打开](https://codespaces.new/Likepoison/OS?quickstart=1)，创建或恢复双核 Codespace，等待实验镜像构建。终端运行：

```bash
python app.py
```

在 **Ports** 中打开 8000 端口的私有预览。建议运行「进程与管道」故障样例，查看关联事件和分层提示，再切换正确样例重跑。在实验记录点击「对比最近两次」，逐用例核对变化，并从对比页直接打开相关轨迹。证据不足时可以跳到轨迹末页继续排查。演示结束后停止 Codespace。

「外观设置」可独立切换主题、背景和桌宠活动，可选一张图片在当前页面预览。「代码样式」可调整等宽字体、字号、制表符宽度、换行和底色。编辑器内按 Ctrl + Enter 可运行实验。工作台顶部可直接打开助教、概念小测或学习进度。

「鲸鱼娘助教」会在进入页面时挥手问好。空闲时会沿页面底部散步，也会张望、坐下、吃饼干、跳跃和打盹。收听语音、等候转写和回答问题时会切换相应动作。鼠标悬停会轮换挥手、循着指针看、蹦跳和坐下。拖动或用方向键可移动她，按 Esc 收起面板。「外观设置」可单独关闭活动和主动气泡。「隐藏桌宠」可收起角色，从页头「显示助教」恢复。

切换到系统调用、分层提示或实验记录时，助教会根据当前页面给出导览。点击某条轨迹的「问助教」，可追问该调用与已观察到的返回状态。「学习进度」按实验汇总本页会话内的评测和小测。「本轮回顾」串起这次看过的轨迹和问答。助教记忆暂存于 Codespace 服务进程内存，每个网页独立。关闭或重载页面会请求删除会话。意外断线后，闲置约 10 分钟会回收。实验记录由评测系统单独保留。

焦点在输入框外时，按住 `T` 录音，松开即转写。也可以点「语音提问」录音，讲完点「结束并转写」。确认文字后点击「发送」或在助教输入框按回车。代码编辑器内的回车用于换行。录音最长 12 秒，经浏览器压缩后由 Codespace 中的 [SenseVoice](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html) 转写，录音只在处理期间留在内存。录音需要 HTTPS 或本机回环地址。

授权后可在助教面板选择本机麦克风，并在录音时查看设备名称和输入音量。若当前设备是「立体声混音」或虚拟输入，请切换到实际使用的内置或耳麦麦克风。

助教回复默认用 [Piper 小雅](https://k2-fsa.github.io/sherpa/onnx/tts/all/Chinese/vits-piper-zh_CN-xiao_ya-medium.html) 自动朗读。面板的「朗读音色」可切换到 Xiaoyi，按「朗读回复」可用新音色重听同一句。每句合成后立即播放，气泡随该句的音频进度显示。Xiaoyi 经 [edge-tts](https://github.com/rany2/edge-tts) 在线合成，只发送助教朗读文本。遇到服务超时会提示改用小雅。

新建演示环境时，在 Linux 终端执行一次 `bash .devcontainer/setup-voice.sh`，再启动或重启 `python app.py`。两个语音模型保存在被 Git 忽略的运行目录。尚未安装模型时，支持 Web Speech API 的浏览器可以尝试内置识别，音频可能由浏览器提供方处理。桌宠话术基于当前页提供的结构化实验信息和已发送的提问，DeepSeek 分层反馈仍可从实验结果进入。

如果网页 IDE 连接缓慢，在 [Your Codespaces](https://github.com/codespaces) 选择同一个 Codespace，使用 **Open in → Visual Studio Code**。桌面 VS Code 需安装 GitHub Codespaces 扩展并登录，终端依然运行在远端。

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

内存实验同时检查指定长度的匿名可读写映射、同地址同长度释放和预期输出。普通用例无法仅凭系统调用证明每次用户态写入。线程同步和死锁实验检查两个不同工作线程各自的 `write` 事件及最终输出，线程标记的顺序不限。这些用例无法单独证明所有锁路径都正确。

文件实验核对同一临时文件描述符的写入、回卷和读回，空输入只要求回卷和读回。运行超时且只观察到主线程等待时，页面保留「证据不足」并提供末尾轨迹。采集服务没有观测到程序启动时，本次不计分。

运行 `python3 -m unittest discover -s tests -p test_system.py -k independent -v` 可检查独立的诊断回归样例，覆盖 14 段轨迹和 5 个实际容器程序。测试核对诊断、置信度与原始证据，包括无关描述符、只有主线程等待、子进程收到信号以及主进程因信号退出。

使用 [Actions](https://github.com/Likepoison/OS/actions) 查看自动验收。运行记录与日志按用例限长，保存在运行环境本地的 SQLite，提交的源码与凭据不写入记录库。部署面向受控、私有演示。

## 赛题参考

- [Docker 资源约束](https://docs.docker.com/engine/containers/resource_constraints/)用于配置和实测 CPU、内存、交换空间及进程数上限。
- [strace 手册](https://man7.org/linux/man-pages/man1/strace.1.html)与 [ptrace 手册](https://man7.org/linux/man-pages/man2/ptrace.2.html)用于跟踪进程树、解码描述符并判定采集和权限边界。
- 题目提供的 [Go](https://go.dev/doc/)、[PostgreSQL](https://www.postgresql.org/docs/current/installation.html)、[MinIO](https://docs.min.io/aistor/installation/linux/install/) 是参考选项。按需演示使用 Python 和 SQLite。
- 桌宠交互参考 [Coopanion](https://github.com/Pal-AI-Lab/Coopanion) 和 [dsh-pet-indesktop](https://github.com/MerZlin/dsh-pet-indesktop) 的活动方式。站立、坐下、移动等全身帧来自 [Coopanion v0.1.10 的 DeepSeek 模型](https://github.com/Pal-AI-Lab/Coopanion/tree/78a46f83d779836c182d8176234c93c26c02d539/packages/cortico-world-desktop-pet/web/whale)，经透明裁剪、动作编排和 WebP 压缩，添加了饼干与玩耍特效。网页图标使用同版 [DeepSeek 预览图](https://github.com/Pal-AI-Lab/Coopanion/blob/78a46f83d779836c182d8176234c93c26c02d539/packages/cortico-world-desktop-pet/web/whale/thumbs/deepseek.png)。附[同版 MIT 许可](pet/LICENSE-Coopanion.txt)与[上游素材声明](https://github.com/Pal-AI-Lab/Coopanion/blob/78a46f83d779836c182d8176234c93c26c02d539/packages/cortico-world-desktop-pet/THIRD_PARTY_NOTICES.md)。署名 Phantivia、角色「溟月」原作者上善无形及女仆版设计者 [ZipZipPipe](https://www.pixiv.net/artworks/148186519)。角色二创沿用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，用于非商业教学演示。图中标志归相应权利方所有。
