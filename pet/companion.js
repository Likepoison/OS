// The duck only speaks authored text. Typed questions select a topic locally.
const duckLessons = {
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

function makeCompanion() {
  const avatar = byId("pet-launch"), panel = byId("pet-panel");
  const sprite = avatar.querySelector("img"), message = byId("pet-reply");
  const actions = byId("pet-actions"), quiz = byId("pet-quiz"), choices = byId("pet-choices");
  const input = byId("pet-input"), reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let activeRun, lastUpdate, mood = "idle", hover = false, drag, moved = false, position;
  let celebration;

  function updateSprite() {
    const file = reducedMotion.matches ? "duck.png"
      : drag?.active || mood === "working" ? "duck-walk.gif"
      : hover || celebration ? "duck-wave.gif" : "duck.png";
    if (sprite.getAttribute("src") !== "/pet/" + file) sprite.src = "/pet/" + file;
    avatar.dataset.mood = mood;
    avatar.classList.toggle("dragging", Boolean(drag?.active));
  }

  function celebrate() {
    clearTimeout(celebration);
    celebration = setTimeout(() => { celebration = undefined; updateSprite(); }, 1050);
    updateSprite();
  }

  function speak(text) {
    message.textContent = text;
    placePanel();
  }

  function placePanel() {
    if (panel.hidden) return;
    const {left, top, right, bottom} = avatar.getBoundingClientRect();
    const gap = 12, width = panel.offsetWidth, height = panel.offsetHeight;
    const above = top - height - gap;
    const x = Math.max(gap, Math.min(innerWidth - width - gap, right - width));
    if (above >= gap || bottom + gap + height <= innerHeight - gap) {
      panel.style.left = x + "px";
      panel.style.top = (above >= gap ? above : bottom + gap) + "px";
      return;
    }
    const beside = left - width - gap;
    panel.style.left = (beside >= gap ? beside : x) + "px";
    panel.style.top = Math.max(gap, innerHeight - height - gap) + "px";
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
    placePanel();
  }

  function setOpen(open, focus = true) {
    panel.hidden = !open;
    avatar.setAttribute("aria-expanded", String(open));
    if (open) {
      placePanel();
      if (focus) byId("pet-title").focus();
    } else if (focus) avatar.focus();
  }

  function openResult(kind) {
    const result = activeRun?.result;
    if (!result || activeRun.id !== record?.id) return;
    setOpen(false, false);
    navigate(false);
    if (kind === "trace") showFindingTrace(result);
    else showTab(kind);
    document.querySelector('[data-tab="' + (kind === "hints" ? "hints" : "trace") + '"]').focus();
  }

  function showQuiz() {
    const lesson = duckLessons[select.value];
    if (!lesson) return speak("选择一个实验，我就能给你出一道相关的小题。");
    const [question, options, correct, explanation] = lesson;
    speak("来做一道概念题。答错了也可以再试。");
    byId("pet-question").textContent = question;
    choices.replaceChildren(...options.map((option, i) => button(option, () => {
      const isCorrect = i === correct;
      speak(isCorrect ? "答对啦！" + explanation : "再想一步。先分清轨迹里看到的事实和推断，再选一次。");
      if (isCorrect) {
        quiz.hidden = true;
        byId("pet-quiz-start").focus();
        celebrate();
        placePanel();
      }
    })));
    quiz.hidden = false;
    choices.firstElementChild.focus();
    placePanel();
  }

  function respond(text) {
    if (/小测|测试题|练习|出.*题|quiz/i.test(text)) return showQuiz();
    if (/deepseek|\bai\b|提示|线索/i.test(text)) {
      if (activeRun?.result?.feedback.source === "ai") return speak("这次有 DeepSeek 的分层提问。可以打开提示，沿着引用回看系统调用。");
      return speak("先试试分层提示。勾选「请求 AI 提示」运行后，有可用证据时会尝试请 DeepSeek 帮你提问。");
    }
    if (/错误|失败|超时|证据|轨迹|结果|通过/.test(text)) {
      if (!activeRun?.result) return speak("运行一次实验，我再陪你看判定和系统调用。");
      return speak(activeRun.result.diagnosis.confidence === "insufficient"
        ? "目前能确认的线索有限。先看末尾轨迹，找找最后哪条调用返回了。"
        : "先打开运行分析，看看用例结果和系统调用能否互相印证。");
    }
    if (/管道|eof|描述符|死锁|内存|线程|调度|futex|mmap/i.test(text)) {
      return speak("我们可以从当前实验的一道概念题开始，再用轨迹验证你的判断。");
    }
    if (/你好|谢谢|嗨|hello|hi\b/i.test(text)) return speak("你好呀！我在这儿。你可以问我怎么看线索，或者做一道小测。");
    speak("我可以陪你看本次结果、找轨迹、读提示，或者做一道操作系统小测。想先试哪个？");
  }

  function update(run) {
    const key = [run?.id || "", run?.state || ""].join("/");
    if (key === lastUpdate) return;
    lastUpdate = key;
    activeRun = run;
    const result = run?.result;
    const contextButtons = [button("来道小测", showQuiz)];
    contextButtons[0].id = "pet-quiz-start";
    if (result) {
      if (traceActionLabel(result)) contextButtons.push(button(traceActionLabel(result), () => openResult("trace")));
      contextButtons.push(button(result.feedback.source === "ai" ? "打开 DeepSeek 提示" : "打开分层提示",
                                 () => openResult("hints")));
    }
    actions.replaceChildren(...contextButtons);
    mood = "idle";
    if (run?.state === "platform_error") {
      mood = "review";
      speak("这次平台没能完成观测。可以查看运行记录，等环境正常后再试。");
    } else if (result && result.passed === result.total) {
      mood = "success";
      speak("全部用例通过啦！要不要用一道概念题复习刚才的操作？");
      celebrate();
    } else if (result) {
      mood = "review";
      speak(result.diagnosis.confidence === "insufficient"
        ? "这次线索还不够。我们可以从最后几条调用开始找。"
        : "先歇一口气。我们有运行线索，可以打开结果一步一步看。");
    } else if (run) {
      mood = "working";
      speak(run.state === "analyzing" ? "运行结束了，正在核对判定和证据。" : "实验在运行队列中，我在这里陪你等结果。");
    } else {
      speak("嗨，我是排错鸭。可以陪你看实验线索，也可以带你做一道小测。");
    }
    updateSprite();
  }

  avatar.addEventListener("pointerenter", () => { hover = true; updateSprite(); });
  avatar.addEventListener("pointerleave", () => { hover = false; updateSprite(); });
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
      updateSprite();
    }
    move(drag.left + dx, drag.top + dy);
  });
  function finishDrag(event) {
    if (drag?.id !== event.pointerId) return;
    drag = undefined;
    updateSprite();
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
    else placePanel();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !panel.hidden) setOpen(false);
  });
  byId("pet-close").addEventListener("click", () => setOpen(false));
  byId("pet-form").addEventListener("submit", event => {
    event.preventDefault();
    const text = input.value.trim();
    input.value = "";
    if (text) respond(text);
  });
  select.addEventListener("change", () => { quiz.hidden = true; placePanel(); });
  reducedMotion.addEventListener("change", updateSprite);
  update(record);
  return {update};
}

companion = makeCompanion();
