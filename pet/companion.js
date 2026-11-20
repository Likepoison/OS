// The companion speaks authored text. Typed questions select a topic locally.
const petLessons = {
  pipe: ["管道缓冲区已经空了，读端什么时候能收到 EOF？",
    ["最后一个写端被关闭后", "任意一个写端被关闭后", "读端第一次读取后"], 0,
    "管道的 EOF 取决于全部写端。复制或继承的描述符也可能让写端继续存在。"],
  file: ["文件描述符关闭后，再用它读取且它还未被重用，会怎样？",
    ["从文件开头再读一次", "调用返回 EBADF", "自动重新打开文件"], 1,
    "描述符离开进程的描述符表后就不可再用。读到文件末尾时，read 返回的是 0。"],
  mutex: ["主线程的 join 迟迟没有返回，能从中确认什么？",
    ["一定发生了死锁", "工作线程一定在忙循环", "主线程还在等待目标线程结束"], 2,
    "join 只能说明主线程在等。要解释目标线程为什么没有结束，还需要它的轨迹。"],
  memory: ["mmap 成功返回时，可以确认哪一件事？",
    ["已经建立了虚拟地址映射", "每个页面都已写入", "已经释放了相同大小的内存"], 0,
    "映射建立后，实际访问可能才触发缺页。系统调用轨迹无法逐条证明用户态写入。"],
  schedule: ["某个任务已经完成，下一轮轮转时怎样处理它？",
    ["保留它的全部时间片", "跳过它，让可运行任务继续", "重启这个任务"], 1,
    "轮转给可运行任务分配时间片。已经完成的任务可以从候选队列移出。"],
  deadlock: ["从一条 futex 等待记录，能直接判断多个线程存在死锁吗？",
    ["只能判断系统已经崩溃", "只要等待就能确认", "还需要检查线程间的等待关系"], 2,
    "正常同步和死锁都可能出现等待。多线程死锁需要结合锁持有情况和等待关系。"]
};
const petClues = {
  pipe_wait: "读端还在等，轨迹里也有写端仍可能打开的线索。先看关联事件里是哪一个进程和描述符。",
  sync_wait: "一条工作线程的等待调用还没有返回。先找这条调用，想想谁有机会结束这次等待。",
  file_error: "实验文件的调用返回了错误。看一眼 errno，再往前找同一文件或描述符的状态。",
  memory_limit: "这次触发了内存限额。对照用例输入和程序请求的字节数，从分配和实际访问的区别想起。",
  signal_exit: "轨迹确认了使主进程退出的信号。先看退出事件，再向前找最后一次正常调用。"
};
const callClues = {
  pipe: "pipe 建立一对读端、写端，父子进程可能各自持有这两个描述符。",
  read: "read 试着读取数据。返回大于 0 表示读到了数据，返回 0 通常表示文件或管道到了末尾。",
  write: "write 返回实际写入的字节数。它可能少于请求写入的字节数。",
  close: "close 关闭当前进程里的这个描述符。其他进程持有的同一端仍可能有效。",
  futex: "futex 用于线程间等待或唤醒。要先区分它的操作类型，再判断哪个线程可能改变等待条件。",
  mmap: "mmap 建立虚拟地址映射。调用成功时，仍需结合后续访问与解除映射查看生命周期。",
  munmap: "munmap 解除指定地址范围的映射。检查它的起始地址和长度是否与分配对应。",
  lseek: "lseek 调整打开文件的偏移量。回卷后才会从前面的字节读起。",
  openat: "openat 尝试打开文件。成功时返回新的文件描述符，可跟踪后续读写。",
  clone: "clone 创建一个任务。参数可以帮助区分是共享地址空间的线程，还是子进程。",
  wait4: "wait4 等待子进程状态发生变化，并可读取其退出状态。"
};
const callAliases = {pipe2:"pipe", clone3:"clone", open:"openat", openat2:"openat", readv:"read", writev:"write", waitid:"wait4"};

function setupPetVoice(input, message, resize) {
  const mic = byId("pet-mic"), read = byId("pet-read"), status = byId("pet-voice-status");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let listener, timeout;
  function note(text = "") {
    status.hidden = !text;
    status.textContent = text;
    resize();
  }
  function clearListener() {
    clearTimeout(timeout);
    listener = undefined;
    mic.setAttribute("aria-pressed", "false");
    mic.textContent = "语音输入";
  }
  function stopListening() {
    if (!listener) return false;
    const active = listener;
    clearListener();
    active.abort();
    return true;
  }
  mic.disabled = !Recognition;
  read.disabled = !window.speechSynthesis || !window.SpeechSynthesisUtterance;
  mic.title = Recognition ? "浏览器识别普通话，转写后可确认发送" : "当前浏览器不支持语音输入";
  if (!Recognition) note("当前浏览器可使用文字输入。");
  mic.addEventListener("click", () => {
    if (stopListening()) return note("已取消语音输入。");
    const active = new Recognition();
    listener = active;
    active.lang = "zh-CN";
    active.interimResults = false;
    active.continuous = false;
    active.onresult = event => {
      if (listener !== active) return;
      const text = event.results[event.resultIndex]?.[0]?.transcript.trim();
      clearListener();
      if (!text) return note("没有听清，可以再说一次或直接输入文字。");
      input.value = text.slice(0, input.maxLength);
      note("已转写。确认文字后发送。");
      input.focus();
    };
    active.onerror = event => {
      if (listener !== active) return;
      clearListener();
      note(event.error === "not-allowed" || event.error === "service-not-allowed"
        ? "麦克风或识别服务不可用，可以继续打字。"
        : "语音识别暂未成功，可以重试或打字。");
    };
    active.onend = () => {
      if (listener !== active) return;
      clearListener();
      note("没有收到转写，可以重试或打字。");
    };
    try {
      active.start();
      mic.setAttribute("aria-pressed", "true");
      mic.textContent = "停止聆听";
      note("浏览器正在识别普通话。转写后请确认发送。");
      timeout = setTimeout(() => {
        if (stopListening()) note("本轮语音输入已结束，可以重试或打字。");
      }, 12000);
    } catch {
      clearListener();
      note("无法启动浏览器语音识别，可以继续打字。");
    }
  });
  read.addEventListener("click", () => {
    const reply = new SpeechSynthesisUtterance(message.textContent);
    reply.lang = "zh-CN";
    speechSynthesis.cancel();
    speechSynthesis.speak(reply);
  });
  function stop() {
    if (stopListening()) note();
    if (!read.disabled) speechSynthesis.cancel();
  }
  window.addEventListener("pagehide", stop);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  return stop;
}

function makeCompanion(activeLab, openResult) {
  const avatar = byId("pet-launch"), panel = byId("pet-panel");
  const bubble = byId("pet-bubble"), reset = byId("pet-reset");
  const message = byId("pet-reply");
  const actions = byId("pet-actions"), quiz = byId("pet-quiz"), choices = byId("pet-choices");
  const input = byId("pet-input");
  let activeRun, lastUpdate, mood = "idle", drag, moved = false, position;
  let view = "grade", visibleEvents, selectedEvent;
  const learning = new Map(), counted = new Set();
  let celebration, bubbleTimer;
  const stopVoice = setupPetVoice(input, message, () => place(panel));

  function updateAppearance() {
    avatar.dataset.mood = mood;
    avatar.classList.toggle("dragging", Boolean(drag?.active));
  }

  function celebrate() {
    if (avatar.hidden) return;
    clearTimeout(celebration);
    avatar.classList.add("cheering");
    celebration = setTimeout(() => { avatar.classList.remove("cheering"); }, 480);
  }

  function speak(text) {
    message.textContent = text;
    place(panel);
  }

  function hideBubble() {
    clearTimeout(bubbleTimer);
    bubble.hidden = true;
  }

  function announce() {
    if (avatar.hidden || !panel.hidden) return;
    hideBubble();
    bubble.hidden = false;
    bubble.textContent = message.textContent;
    place(bubble);
    bubbleTimer = setTimeout(hideBubble, 5300);
  }

  function place(floating) {
    if (floating.hidden) return;
    const {left, top, right, bottom} = avatar.getBoundingClientRect();
    const gap = 12, width = floating.offsetWidth, height = floating.offsetHeight;
    const above = top - height - gap;
    const x = Math.max(gap, Math.min(innerWidth - width - gap, right - width));
    if (above >= gap || bottom + gap + height <= innerHeight - gap) {
      floating.style.left = x + "px";
      floating.style.top = (above >= gap ? above : bottom + gap) + "px";
      return;
    }
    const beside = left - width - gap;
    floating.style.left = (beside >= gap ? beside : x) + "px";
    floating.style.top = Math.max(gap, innerHeight - height - gap) + "px";
  }

  function move(x, y) {
    position = {
      x: Math.max(8, Math.min(innerWidth - avatar.offsetWidth - 8, x)),
      y: Math.max(8, Math.min(innerHeight - avatar.offsetHeight - 8, y))
    };
    avatar.style.left = position.x + "px";
    avatar.style.top = position.y + "px";
    avatar.style.right = "auto";
    avatar.style.bottom = "auto";
    reset.hidden = false;
    place(panel);
    place(bubble);
  }

  function setOpen(open, focus = true) {
    panel.hidden = !open;
    avatar.setAttribute("aria-expanded", String(open));
    if (open) {
      hideBubble();
      place(panel);
      if (focus) byId("pet-title").focus();
    } else {
      stopVoice();
      if (focus) avatar.focus();
    }
  }

  function reveal(kind) {
    setOpen(false, false);
    openResult(activeRun.id, kind);
  }

  function showQuiz() {
    const lab = activeLab();
    const lesson = petLessons[lab];
    if (!lesson) return speak("选择一个实验，我就能给你出一道相关的小题。");
    const status = study(lab);
    const [question, options, correct, explanation] = lesson;
    speak(status.answers > status.correct
      ? "再用一道概念题确认刚才的知识点。可以回看系统调用后再答。"
      : "来做一道概念题。答错了也可以再试。");
    byId("pet-question").textContent = question;
    choices.replaceChildren(...options.map((option, i) => button(option, () => {
      const isCorrect = i === correct;
      status.answers++;
      if (isCorrect) status.correct++;
      speak(isCorrect ? "答对啦！" + explanation : "再想一步。先分清轨迹里看到的事实和推断，再选一次。");
      if (isCorrect) {
        quiz.hidden = true;
        byId("pet-quiz-start").focus();
        celebrate();
        place(panel);
      }
    })));
    quiz.hidden = false;
    choices.firstElementChild.focus();
    place(panel);
  }

  function study(lab) {
    if (!learning.has(lab)) learning.set(lab, {runs: 0, answers: 0, correct: 0});
    return learning.get(lab);
  }

  function recordRun(run) {
    if (!run?.lab || !run.score || counted.has(run.id)) return;
    counted.add(run.id);
    const status = study(run.lab);
    status.runs++;
    status.score = run.score;
  }

  function reportProgress() {
    const status = study(activeLab());
    const recent = status.score ? "最近一次通过 " + status.score.join("/") + " 个用例。" : "";
    const next = status.score && status.score[0] < status.score[1]
      ? "下一步可以查看失败用例和对应轨迹。"
      : status.answers > status.correct ? "下一步可回看刚才的概念，再试一次。"
      : "可以做一道概念题来检验理解。";
    speak("当前实验评测 " + status.runs + " 次。" + recent +
      "概念题答对 " + status.correct + "/" + status.answers + " 次。" + next);
  }

  function observe(next, total) {
    const changed = view !== next;
    view = next;
    visibleEvents = total;
    selectedEvent = undefined;
    if (changed && (view === "history" || ((view === "trace" || view === "hints") && activeRun?.hasResult))) {
      explainView();
      announce();
    }
  }

  function explain(event) {
    selectedEvent = event;
    if (avatar.hidden) {
      avatar.hidden = false;
      byId("pet-restore").hidden = true;
    }
    setOpen(true);
    explainSelected();
  }

  function explainSelected() {
    const {id, call, kind, errno} = selectedEvent;
    const clue = callClues[callAliases[call] || call];
    const observation = errno ? "返回 " + errno + "。"
      : kind === "pending" ? "采集结束时尚未观察到返回。"
      : kind === "partial" ? "这条记录只有调用的一部分。"
      : "";
    speak("事件 #" + id + " 的 " + call + "。" + observation +
      (clue || "可以沿着对应的原始日志行，检查参数和返回值。"));
  }

  function explainView() {
    if (selectedEvent) return explainSelected();
    if (view === "history") return speak("当前是实验记录。选择同一个实验的两次结果，可以对照调整前后的判定和证据。");
    if (view === "trace") return speak("当前是系统调用轨迹" +
      (visibleEvents === undefined ? "。" : "，当前筛选匹配 " + visibleEvents + " 条记录。") +
      "用「问助教」查看一条调用的含义，再结合原始日志判断。");
    if (view === "hints") return speak("当前是分层提示。先读观察方向，再打开相关原理或证据定位。");
    speak("当前是测试判定。先对照用例输入和输出，再看与失败相关的调用。");
  }

  function respond(text) {
    if (/进度|学得|学到哪|答了几|小结|掌握/.test(text)) return reportProgress();
    if (/正在看|在看什么|当前页面|这页|这条|这个调用|刚才那条/.test(text)) return explainView();
    if (/小测|测试题|练习|出.*题|quiz/i.test(text)) return showQuiz();
    if (/deepseek|\bai\b|提示|线索/i.test(text)) {
      if (activeRun?.ai) return speak("这次有 DeepSeek 的分层提问。可以打开提示，沿着引用回看系统调用。");
      return speak("先试试分层提示。勾选「请求 AI 提示」运行后，有可用证据时会尝试请 DeepSeek 帮你提问。");
    }
    if (/错误|失败|超时|证据|轨迹|结果|通过/.test(text)) {
      if (!activeRun?.hasResult) return speak("运行一次实验，我再陪你看判定和系统调用。");
      return speak(petClues[activeRun.code] || (activeRun.confidence === "insufficient"
        ? "目前能确认的线索有限。先看末尾轨迹，找找最后哪条调用返回了。"
        : "先打开运行分析，看看用例结果和系统调用能否互相印证。"));
    }
    const mentioned = text.toLowerCase().match(/\b(pipe2?|readv?|writev?|close|futex|mmap|munmap|lseek|openat2?|clone3?|wait4|waitid)\b/);
    if (mentioned) return speak(callClues[callAliases[mentioned[0]] || mentioned[0]]);
    if (/管道|eof|描述符|死锁|内存|线程|调度/i.test(text)) {
      return speak("我们可以从当前实验的一道概念题开始。也可打开轨迹，点一条调用的「问助教」。");
    }
    if (/你好|谢谢|嗨|hello|hi\b/i.test(text)) return speak("你好呀！我在这儿。你可以问我怎么看线索，或者做一道小测。");
    speak("我可以陪你看本次结果、找轨迹、读提示，或者做一道操作系统小测。想先试哪个？");
  }

  function update(run) {
    const key = [run?.id || "", run?.state || ""].join("/");
    if (key === lastUpdate) return;
    lastUpdate = key;
    activeRun = run;
    const contextButtons = [button("来道小测", showQuiz), button("学习进度", reportProgress)];
    contextButtons[0].id = "pet-quiz-start";
    if (run?.hasResult) {
      if (run.traceLabel) contextButtons.push(button(run.traceLabel, () => reveal("trace")));
      contextButtons.push(button(run.ai ? "打开 DeepSeek 提示" : "打开分层提示", () => reveal("hints")));
    }
    actions.replaceChildren(...contextButtons);
    mood = "idle";
    if (run?.state === "platform_error") {
      mood = "review";
      speak("这次平台没能完成观测。可以查看运行记录，等环境正常后再试。");
    } else if (run?.passed) {
      mood = "success";
      speak("全部用例通过啦！要不要用一道概念题复习刚才的操作？");
      celebrate();
    } else if (run?.hasResult) {
      mood = "review";
      speak(run.confidence === "insufficient"
        ? "这次线索还不够。我们可以从最后几条调用开始找。"
        : "先歇一口气。我们有运行线索，可以打开结果一步一步看。");
    } else if (run) {
      mood = "working";
      speak(run.state === "analyzing" ? "运行结束了，正在核对判定和证据。" : "实验在运行队列中，我在这里陪你等结果。");
    } else {
      speak("嗨，我是鲸鱼娘助教。一起看实验线索，或者做道小测吧。");
    }
    updateAppearance();
    announce();
  }

  avatar.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0) return;
    const {left, top} = avatar.getBoundingClientRect();
    moved = false;
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, left, top, active: false};
  });
  window.addEventListener("pointermove", event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.active && Math.hypot(dx, dy) < 6) return;
    if (!drag.active) {
      drag.active = moved = true;
      avatar.setPointerCapture(event.pointerId);
      updateAppearance();
    }
    move(drag.left + dx, drag.top + dy);
  });
  function finishDrag(event) {
    if (drag?.id !== event.pointerId) return;
    drag = undefined;
    updateAppearance();
  }
  window.addEventListener("pointerup", finishDrag);
  window.addEventListener("pointercancel", finishDrag);
  avatar.addEventListener("lostpointercapture", finishDrag);
  avatar.addEventListener("click", event => {
    if (moved && event.detail !== 0) { moved = false; return; }
    setOpen(panel.hidden);
  });
  avatar.addEventListener("keydown", event => {
    const direction = {ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0]}[event.key];
    if (!direction) return;
    event.preventDefault();
    const {left, top} = avatar.getBoundingClientRect();
    const distance = event.shiftKey ? 48 : 16;
    move(left + direction[0] * distance, top + direction[1] * distance);
  });
  window.addEventListener("resize", () => {
    if (position) move(position.x, position.y);
    else {
      place(panel);
      place(bubble);
    }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !panel.hidden) setOpen(false);
  });
  byId("pet-close").addEventListener("click", () => setOpen(false));
  const restore = byId("pet-restore");
  byId("pet-hide").addEventListener("click", () => {
    setOpen(false, false);
    hideBubble();
    avatar.hidden = true;
    restore.hidden = false;
    clearTimeout(celebration);
    avatar.classList.remove("cheering");
    restore.focus();
  });
  restore.addEventListener("click", () => {
    restore.hidden = true;
    avatar.hidden = false;
    announce();
    avatar.focus();
  });
  reset.addEventListener("click", () => {
    position = undefined;
    for (const side of ["left", "top", "right", "bottom"]) avatar.style.removeProperty(side);
    reset.hidden = true;
    place(panel);
    byId("pet-close").focus();
  });
  byId("pet-form").addEventListener("submit", event => {
    event.preventDefault();
    const text = input.value.trim();
    input.value = "";
    if (text) respond(text);
  });
  select.addEventListener("change", () => { quiz.hidden = true; place(panel); });
  return {update, observe, explain, recordRun};
}

companion = makeCompanion(() => select.value, openPetResult);
companion.update(petSnapshot(record));
