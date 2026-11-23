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
const recallQuestion = /回顾|上次问|刚才问|上一问|记得.*问题|本轮小结/;

function setupPetVoice(input, message, resize, setVoicePose, caption) {
  const mic = byId("pet-mic"), read = byId("pet-read"), status = byId("pet-voice-status");
  const autoRead = byId("pet-autoread");
  const voiceStyle = byId("pet-voice-style"), voiceChoice = byId("pet-voice-choice");
  const devices = byId("pet-mic-devices"), device = byId("pet-mic-device");
  const level = byId("pet-mic-level"), meter = byId("pet-mic-meter");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const Recorder = window.MediaRecorder;
  const format = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
    .find(type => Recorder?.isTypeSupported(type));
  const canRecord = Boolean(window.isSecureContext && format && navigator.mediaDevices?.getUserMedia);
  let listener, timeout, recording, playback, pendingReply, speechReady = false, useServer = false;
  function note(text = "") {
    status.hidden = !text;
    status.textContent = text;
    resize();
  }
  function micState(label = "语音输入", pose = null) {
    mic.setAttribute("aria-pressed", String(label !== "语音输入"));
    mic.textContent = label;
    setVoicePose(pose);
    resize();
  }

  function clearListener() {
    clearTimeout(timeout);
    listener = undefined;
    micState();
  }
  function stopListening() {
    if (!listener) return false;
    const active = listener;
    clearListener();
    active.abort();
    return true;
  }
  function enableServer(configuration) {
    speechReady = configuration !== undefined;
    const voices = configuration?.voices ?? [];
    for (const option of voiceStyle.options) option.disabled = !voices.includes(option.value);
    if (!voices.includes(voiceStyle.value)) voiceStyle.value = voices[0] ?? "xiaoya";
    voiceChoice.hidden = voices.length === 0;
    read.disabled = autoRead.disabled = voices.length === 0;
    read.title = read.disabled ? "当前环境的鲸鱼娘专用语音尚未就绪" : "用鲸鱼娘的声音朗读当前回复";
    if (configuration === undefined) {
      mic.disabled = true;
      mic.title = "正在检查语音服务";
      note("语音服务正在准备。");
      return;
    }
    useServer = configuration.record && canRecord;
    devices.hidden = true;
    if (useServer) refreshInputs();
    mic.disabled = !useServer && !Recognition;
    mic.title = useServer ? "按住 T 录音，松开转写。普通话在当前演示服务内转写"
      : Recognition ? "按住 T 录音，松开转写。使用浏览器语音识别" : "当前浏览器无法使用语音输入";
    if (mic.disabled) note("当前浏览器可使用文字输入。也可以用 Chrome 或 Edge 打开演示页后重试。");
    else note();
    const waiting = pendingReply;
    pendingReply = undefined;
    if (waiting && waiting === message.textContent) readReply(true);
  }

  function showTranscript(text) {
    if (!text) return note("没有识别到话语。请检查浏览器选用的麦克风，靠近后说完整一句再结束。");
    input.value = text.slice(0, input.maxLength);
    note("已转写。确认文字后发送。");
    input.focus();
  }

  function finishNative() {
    if (!listener || mic.textContent !== "停止聆听") return;
    listener.stop();
    if (listener) micState("取消转写", "focus");
  }

  function startNative(held) {
    const active = new Recognition();
    listener = active;
    let text = "", ended = false, released = !held;
    active.lang = "zh-CN";
    active.interimResults = false;
    active.continuous = held;
    function complete() {
      clearListener();
      showTranscript(text);
    }
    function release() {
      if (listener !== active || released) return;
      released = true;
      clearTimeout(timeout);
      if (ended) return complete();
      finishNative();
      if (listener === active) timeout = setTimeout(() => {
        if (stopListening()) note("语音转写超时，请再试一次。");
      }, 2500);
    }
    active.onresult = event => {
      if (listener !== active) return;
      text = Array.from(event.results, result => result[0].transcript).join("").trim();
      if (!held) complete();
    };
    active.onerror = event => {
      if (listener !== active) return;
      clearListener();
      const failure = {
        "not-allowed": "浏览器没有拿到麦克风权限。请检查本站权限和系统的麦克风访问设置，也可以继续打字。",
        "service-not-allowed": "浏览器语音识别不可用，可以继续打字。",
        "audio-capture": "找不到可用的麦克风，请连接设备后重试。",
        network: "浏览器语音识别服务连接失败，可以重试或打字。"
      };
      note(failure[event.error] || "语音识别暂未成功，可以重试或打字。");
    };
    active.onend = () => {
      if (listener !== active) return;
      ended = true;
      if (released) complete();
    };
    try {
      active.start();
      micState("停止聆听", "listen");
      note(held ? "正在听。说完松开 T，最多 12 秒。" : "浏览器正在识别普通话。转写后请确认发送。");
      timeout = setTimeout(() => {
        if (held && !released) release();
        else if (stopListening()) note("本轮语音输入已结束，可以重试或打字。");
      }, 12000);
    } catch {
      clearListener();
      note("无法启动浏览器语音识别，可以继续打字。");
    }
    if (held && listener === active) return release;
  }

  async function refreshInputs() {
    if (!navigator.mediaDevices.enumerateDevices) return;
    try {
      const entries = await navigator.mediaDevices.enumerateDevices();
      if (!useServer) return;
      const inputs = entries.filter(entry => entry.kind === "audioinput" && entry.label &&
        entry.deviceId && entry.deviceId !== "default" && entry.deviceId !== "communications");
      const chosen = device.value;
      device.replaceChildren(new Option("浏览器默认设备", ""), ...inputs.map(entry => new Option(entry.label, entry.deviceId)));
      if (inputs.some(entry => entry.deviceId === chosen)) device.value = chosen;
      devices.hidden = inputs.length === 0;
      resize();
    } catch (error) {
      console.debug("Microphone list unavailable", error);
    }
  }

  function monitorInput(session) {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    try {
      const context = session.monitor = new Audio();
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(session.stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      level.hidden = false;
      meter.value = 0;
      session.meterTimer = setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
        meter.value = Math.min(1, rms * 8);
      }, 100);
      context.resume().catch(error => console.debug("Microphone level unavailable", error));
    } catch (error) {
      console.debug("Microphone level unavailable", error);
    }
  }

  function releaseAudio(session) {
    clearInterval(session.meterTimer);
    if (session.monitor && session.monitor.state !== "closed") {
      session.monitor.close().catch(error => console.debug("Microphone monitor cleanup", error));
      session.monitor = undefined;
    }
    if (session.recorder && session.recorder.state !== "inactive") session.recorder.stop();
    session.stream?.getTracks().forEach(track => track.stop());
    if (!recording || recording === session) {
      level.hidden = true;
      meter.value = 0;
    }
  }

  function closeRecording() {
    if (!recording) return false;
    const session = recording;
    recording = null;
    clearTimeout(session.timer);
    session.request.abort();
    releaseAudio(session);
    device.disabled = false;
    micState();
    return true;
  }

  function finishRecording(session) {
    if (recording !== session || session.phase !== "listening") return;
    session.phase = "stopping";
    clearTimeout(session.timer);
    micState("取消转写", "focus");
    session.timer = setTimeout(() => {
      if (recording !== session) return;
      closeRecording();
      note("录音没有返回，请再试一次。");
    }, 2500);
    if (session.recorder.state !== "inactive") session.recorder.stop();
  }

  async function transcribe(session, audio) {
    if (recording !== session) return;
    clearTimeout(session.timer);
    releaseAudio(session);
    if (audio.size < 100) {
      closeRecording();
      note("这段录音太短。请说完后再点结束。");
      return;
    }
    session.phase = "recognizing";
    micState("取消转写", "focus");
    note("正在把录音转成文字。");
    session.timer = setTimeout(() => session.request.abort(), 35000);
    try {
      const result = await api("/api/pet/voice", {method: "POST", signal: session.request.signal,
        headers: {"Content-Type": audio.type}, body: audio});
      if (recording !== session) return;
      closeRecording();
      if (result.reason === "no_signal") {
        return note("已从「" + session.deviceName + "」录音，但几乎没有收到声音。请切换到实际麦克风，检查静音和输入音量。");
      }
      showTranscript(result.text);
    } catch (error) {
      if (recording !== session) return;
      closeRecording();
      note(error.name === "AbortError" ? "语音转写超时，请再试一次。" : error.message);
    }
  }

  async function startServerRecording(held) {
    const session = recording = {request: new AbortController(), phase: "permission"};
    try {
      device.disabled = true;
      micState("取消录音", "listen");
      note("正在打开麦克风。若浏览器询问权限，请选择允许。");
      session.stream = await navigator.mediaDevices.getUserMedia({audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true,
        ...(device.value ? {deviceId: {exact: device.value}} : {})
      }});
      if (recording !== session) return releaseAudio(session);
      session.deviceName = session.stream.getAudioTracks()[0]?.label || "当前麦克风";
      refreshInputs();
      const recorder = session.recorder = new Recorder(session.stream, {
        mimeType: format, audioBitsPerSecond: 24000
      });
      const fragments = [];
      recorder.ondataavailable = event => { if (event.data.size) fragments.push(event.data); };
      recorder.onstop = () => transcribe(session, new Blob(fragments, {type: recorder.mimeType}));
      recorder.onerror = () => {
        if (recording === session) {
          closeRecording();
          note("录音中断，请重新点击语音输入。");
        }
      };
      recorder.start();
      session.phase = "listening";
      micState("结束并转写", "listen");
      monitorInput(session);
      const instruction = held ? "说完松开 T" : "说完点「结束并转写」";
      note("正在用「" + session.deviceName + "」录音。" + instruction + "，最多 12 秒。");
      session.timer = setTimeout(() => finishRecording(session), 12000);
    } catch (error) {
      if (recording !== session) return;
      closeRecording();
      const failure = {
        NotAllowedError: "浏览器没有拿到麦克风权限。请检查地址栏的本站权限，以及 Windows 的麦克风和桌面应用访问权限。",
        NotFoundError: "找不到选定的麦克风，请重新选择或连接设备。",
        OverconstrainedError: "选定的麦克风已不可用，请重新选择。",
        NotReadableError: "暂时无法打开麦克风。请检查设备是否被占用。"
      };
      if (error.name === "NotFoundError" || error.name === "OverconstrainedError") refreshInputs();
      note(failure[error.name] || "当前无法录音，请重试或使用文字。");
    }
  }

  mic.addEventListener("click", () => {
    if (recording?.phase === "listening") return finishRecording(recording);
    if (closeRecording()) return note("已取消语音输入。");
    if (listener) {
      if (mic.textContent === "停止聆听") finishNative();
      else if (stopListening()) note("已取消语音输入。");
      return;
    }
    startInput(false);
  });

  function startInput(held) {
    if (mic.disabled || recording || listener) return;
    stopPlayback();
    if (!useServer) return startNative(held);
    startServerRecording(held);
    const session = recording;
    if (!held || !session) return;
    return () => {
      if (recording !== session) return;
      if (session.phase === "permission") {
        closeRecording();
        note("麦克风还在开启。允许麦克风后，再按住 T 说话。");
      } else finishRecording(session);
    };
  }

  function releaseClip(narration) {
    cancelAnimationFrame(narration.captionFrame);
    narration.audio?.pause();
    if (narration.url) URL.revokeObjectURL(narration.url);
    narration.audio = narration.url = undefined;
  }

  function stopPlayback(keepCaption = false) {
    if (!playback) return false;
    const current = playback;
    playback = undefined;
    if (!keepCaption) caption();
    current.request.abort();
    releaseClip(current);
    read.textContent = "朗读回复";
    setVoicePose(null);
    resize();
    return true;
  }

  async function fetchClip(text, voice, request) {
    const response = await fetch("/api/pet/speech", {
      method: "POST", signal: AbortSignal.any([request.signal, AbortSignal.timeout(18000)]),
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({text, voice})
    });
    if (response.redirected || !response.ok || !response.headers.get("content-type")?.startsWith("audio/mpeg")) {
      const failure = await response.json().catch(() => null);
      throw new Error(failure?.error || "鲸鱼娘的专用语音暂时连不上，请再点一次朗读。");
    }
    return {clip: await response.blob(), voice: response.headers.get("X-TraceTutor-Voice") || voice};
  }

  async function playClip(narration, clip, prefix, part) {
    const characters = Array.from(part);
    narration.url = URL.createObjectURL(clip);
    const audio = narration.audio = new window.Audio(narration.url), signal = narration.request.signal;
    let shown = 0, finish;
    function reveal() {
      if (playback !== narration || audio.paused || narration.audio !== audio) return;
      const count = Number.isFinite(audio.duration) && audio.duration > 0
        ? Math.min(characters.length, 1 + Math.floor(audio.currentTime / audio.duration * characters.length))
        : 1;
      if (count > shown) {
        shown = count;
        caption(prefix + characters.slice(0, shown).join(""));
      }
      if (shown < characters.length) narration.captionFrame = requestAnimationFrame(reveal);
    }
    audio.onplaying = () => {
      if (playback !== narration || narration.audio !== audio) return;
      note(narration.fallback ? "Xiaoyi 暂不可用，正用小雅继续朗读。" : "");
      setVoicePose("talk");
      cancelAnimationFrame(narration.captionFrame);
      reveal();
    };
    try {
      await new Promise((resolve, reject) => {
        finish = resolve;
        signal.addEventListener("abort", finish, {once: true});
        audio.onended = resolve;
        audio.onerror = () => reject(new Error("音频未能播放，请再试一次。"));
        audio.play().catch(reject);
      });
    } finally {
      signal.removeEventListener("abort", finish);
      if (narration.audio === audio) releaseClip(narration);
    }
  }

  async function readReply(automatic = false) {
    if ((automatic && !autoRead.checked) || !message.textContent || recording || listener) return;
    if (!speechReady) {
      if (automatic) pendingReply = message.textContent;
      return;
    }
    if (read.disabled) return;
    if (stopPlayback() && !automatic) return note("已停止朗读。");
    const text = Array.from(message.textContent).slice(0, 260).join("").trim();
    if (!text) return;
    const sentences = text.match(/[^。！？!?]+[。！？!?]*|[。！？!?]+/gu);
    const request = new AbortController();
    const narration = playback = {request};
    caption();
    read.textContent = "停止朗读";
    note("鲸鱼娘正在准备语音。");
    setVoicePose("focus");
    let voice = voiceStyle.value, completed = "";
    const prepare = part => fetchClip(part, voice, request).catch(error => ({error}));
    try {
      let pending = prepare(sentences[0]);
      for (let i = 0; i < sentences.length; i++) {
        const result = await pending;
        if (playback !== narration) return;
        if (result.error) throw result.error;
        narration.fallback ||= voice === "xiaoyi" && result.voice === "xiaoya";
        voice = result.voice;
        if (i + 1 < sentences.length) pending = prepare(sentences[i + 1]);
        await playClip(narration, result.clip, completed, sentences[i]);
        if (playback !== narration) return;
        completed += sentences[i];
        caption(completed);
        setVoicePose("focus");
      }
      stopPlayback(true);
      caption(completed, true);
    } catch (error) {
      if (playback !== narration) return;
      stopPlayback();
      note(error.name === "NotAllowedError" ? "请点击「朗读回复」，允许浏览器播放声音。"
        : error.name === "TimeoutError" ? "生成语音超时，请再点一次朗读。"
        : error.message || "暂时无法播放，请重试。");
    }
  }
  read.addEventListener("click", () => readReply());
  voiceStyle.addEventListener("change", () => {
    if (stopPlayback()) note();
  });
  function stop() {
    pendingReply = undefined;
    const hadRecording = closeRecording();
    if (stopListening() || hadRecording) note();
    if (stopPlayback()) note();
    caption();
    setVoicePose(null);
  }
  window.addEventListener("pagehide", stop);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  enableServer();
  return {stop, readReply, enableServer, startInput};
}

function makeStudyMemory() {
  const collection = "/api/pet/sessions";
  const json = {"Content-Type": "application/json"};
  let path, generation = 0, queue = Promise.resolve();
  function closePath(url) {
    if (!navigator.sendBeacon(url + "/close")) {
      fetch(url + "/close", {method: "POST", keepalive: true}).catch(() => {});
    }
  }
  function request(action) {
    const version = generation;
    const signal = AbortSignal.timeout(8000);
    const scopedApi = (url, options) => api(url, {...options, signal});
    async function withSession() {
      if (version !== generation) return null;
      signal.throwIfAborted();
      if (!path) {
        const {id} = await scopedApi(collection, {method: "POST", headers: json});
        const started = collection + "/" + id;
        if (version !== generation) {
          closePath(started);
          return null;
        }
        path = started;
      }
      return action(path, scopedApi);
    }
    const next = queue.then(withSession).catch(error => {
      if (error.status !== 404 || !path || version !== generation) throw error;
      path = undefined;
      return withSession();
    }).catch(error => {
      if (signal.aborted) throw new Error("本轮学习记录连接超时，请重试。");
      throw error;
    });
    queue = next.catch(() => null);
    return next;
  }
  const write = event => request((url, send) => send(url, {method: "POST", headers: json, body: JSON.stringify(event)}));
  const read = lab => request((url, send) => send(url + "?" + new URLSearchParams({lab})));
  setInterval(() => {
    if (path) request((url, send) => send(url + "/touch", {method: "POST", headers: json})).catch(() => {});
  }, 90000);
  function close() {
    generation++;
    if (path) closePath(path);
    path = undefined;
    queue = Promise.resolve();
  }
  return {write, read, close};
}

function makeCompanion(activeLab, openResult) {
  const avatar = byId("pet-launch"), panel = byId("pet-panel");
  const bubble = byId("pet-bubble"), reset = byId("pet-reset");
  const message = byId("pet-reply");
  const actions = byId("pet-actions"), quiz = byId("pet-quiz"), choices = byId("pet-choices");
  const form = byId("pet-form"), input = byId("pet-input");
  const send = form.querySelector('button[type="submit"]');
  let holdTimer, releaseVoice;
  const quickStudy = byId("quick-study"), restore = byId("pet-restore");
  const quickVoice = quickStudy.querySelector('[data-study="voice"]');
  const motion = byId("pet-motion"), proactive = byId("pet-proactive");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const greeting = bubble.textContent;
  const figure = avatar.querySelector(".pet-figure");
  const readyArtwork = new Map(), artworkFailures = new Map();
  let loadingArtwork, shownArtwork;
  let activeRun, lastUpdate, mood = "idle", drag, moved = false, position;
  let manuallyPlaced = false, roamingLeft = false, patrolTimer, roamTimeout;
  let poseTimer, voicePose, greeted = false, pendingBubble, activityIndex = 0, hoverIndex = 0;
  let hoverActive = false;
  let lastInteraction = performance.now();
  let view = "grade", visibleEvents, selectedEvent;
  const memory = makeStudyMemory(), memoryStatus = byId("pet-memory-status");
  let lastVisit;
  let bubbleTimer;
  const voice = setupPetVoice(input, message, () => place(panel), pose => {
    voicePose = pose;
    if (voicePose && voicePose !== "talk") cancelArtwork();
    updateAppearance();
  }, showSpokenCaption);

  function cancelArtwork() {
    if (!loadingArtwork) return;
    loadingArtwork.onload = loadingArtwork.onerror = null;
    loadingArtwork.removeAttribute("src");
    loadingArtwork = undefined;
  }

  function showArtwork() {
    const pose = avatar.dataset.pose;
    const prepared = readyArtwork.get(pose);
    if (prepared) {
      if (shownArtwork !== prepared) {
        shownArtwork?.remove();
        figure.append(prepared);
        shownArtwork = prepared;
      }
      avatar.dataset.art = pose;
      return;
    }
    delete avatar.dataset.art;
    shownArtwork?.remove();
    shownArtwork = undefined;
    if (pose === "stand" || (voicePose && voicePose !== "talk") || loadingArtwork || avatar.hidden || document.hidden ||
        !motion.checked || reducedMotion.matches || (artworkFailures.get(pose) || 0) >= 2) return;
    const image = loadingArtwork = new Image();
    image.className = "pet-strip";
    image.alt = "";
    image.draggable = false;
    image.fetchPriority = "low";
    function failed() {
      if (loadingArtwork !== image) return;
      artworkFailures.set(pose, (artworkFailures.get(pose) || 0) + 1);
      loadingArtwork = undefined;
    }
    image.onload = async () => {
      try {
        await image.decode();
      } catch {
        return failed();
      }
      if (loadingArtwork !== image) return;
      if (!image.naturalHeight || image.naturalWidth !== 8 * image.naturalHeight) return failed();
      readyArtwork.set(pose, image);
      loadingArtwork = undefined;
      showArtwork();
    };
    image.onerror = failed;
    image.src = "/pet/whale-" + pose + ".webp";
  }

  function updateAppearance() {
    avatar.dataset.mood = mood;
    avatar.classList.toggle("dragging", Boolean(drag?.active));
    const pose = drag?.active ? "drag" : voicePose || (mood === "working" || mood === "review" ? "focus" : "stand");
    setPose(pose);
  }

  function setPose(pose, duration = 0) {
    clearTimeout(poseTimer);
    if (pose !== "look") clearHoverGaze();
    avatar.dataset.pose = pose;
    showArtwork();
    if (duration) poseTimer = setTimeout(updateAppearance, duration);
  }

  function celebrate() {
    if (!avatar.hidden && motion.checked && !reducedMotion.matches) setPose("play", 1050);
  }

  function speak(text) {
    message.textContent = text;
    place(panel);
    if (!panel.hidden && !voicePose) setPose("talk", 1150);
    return text;
  }

  function hideBubble() {
    clearTimeout(bubbleTimer);
    bubble.hidden = true;
  }

  function showSpokenCaption(text, finished = false) {
    if (!text) {
      if (bubble.dataset.kind === "spoken") {
        hideBubble();
        place(panel);
      }
      return;
    }
    if (avatar.hidden || document.hidden || panel.hidden) return;
    if (bubble.hidden || bubble.dataset.kind !== "spoken") {
      hideBubble();
      bubble.dataset.kind = "spoken";
      bubble.setAttribute("aria-live", "off");
      bubble.hidden = false;
    }
    bubble.textContent = text;
    place(bubble);
    place(panel);
    if (finished) bubbleTimer = setTimeout(() => { hideBubble(); place(panel); }, 3200);
  }

  function announce(text = message.textContent, kind = "reply") {
    if (!text || !proactive.checked || avatar.hidden || !panel.hidden) return false;
    if (document.hidden || byId("appearance").open || byId("editor-settings").open) {
      pendingBubble = text;
      return false;
    }
    pendingBubble = undefined;
    lastInteraction = performance.now();
    stopRoaming();
    hideBubble();
    bubble.hidden = false;
    bubble.textContent = text;
    bubble.dataset.kind = kind;
    bubble.removeAttribute("aria-live");
    place(bubble);
    bubbleTimer = setTimeout(hideBubble, kind === "welcome" ? 8500 : 6200);
    return true;
  }

  function greet() {
    if (!greeted && announce(greeting, "welcome")) {
      greeted = true;
      setPose("greet", 1450);
    }
  }

  function place(floating) {
    if (floating.hidden) return;
    const {left, top, right, bottom} = avatar.getBoundingClientRect();
    const gap = 12, width = floating.offsetWidth;
    const x = Math.max(gap, Math.min(innerWidth - width - gap, right - width));
    if (floating === panel) {
      panel.style.removeProperty("max-height");
      if (!bubble.hidden && bubble.dataset.kind === "spoken") {
        const caption = bubble.getBoundingClientRect();
        const side = Math.min(caption.left, left) - width - gap;
        if (side >= gap) {
          panel.style.left = side + "px";
          panel.style.top = Math.max(gap, Math.min(caption.top, innerHeight - panel.offsetHeight - gap)) + "px";
          return;
        }
        if (caption.top >= 2 * gap + 120) {
          panel.style.maxHeight = (caption.top - 2 * gap) + "px";
          panel.style.left = x + "px";
          panel.style.top = (caption.top - gap - panel.offsetHeight) + "px";
          return;
        }
      }
    }
    const height = floating.offsetHeight;
    const above = top - height - gap;
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
    reset.hidden = false;
    place(bubble);
    place(panel);
  }

  function stopRoaming() {
    if (avatar.dataset.roaming !== "true") return;
    const {left, top} = avatar.getBoundingClientRect();
    clearTimeout(roamTimeout);
    delete avatar.dataset.roaming;
    move(left, top);
    updateAppearance();
  }

  function goHome() {
    stopRoaming();
    position = undefined;
    manuallyPlaced = roamingLeft = false;
    avatar.dataset.facing = "left";
    for (const side of ["left", "top"]) avatar.style.removeProperty(side);
    reset.hidden = true;
    place(panel);
    place(bubble);
  }

  function patrol() {
    if (document.hidden || avatar.hidden || !panel.hidden || drag || hoverActive ||
      byId("appearance").open || byId("editor-settings").open) return;
    if (!greeted) greet();
    if (pendingBubble && greeted) announce(pendingBubble);
    const idle = performance.now() - lastInteraction;
    if (proactive.checked && idle > 38000 && mood !== "working") {
      const lab = activeLab();
      if (lab) {
        speak(mood === "success" ? "做道概念小测，把刚通过的实验再想一遍吧。"
          : mood === "review" ? "还在排查吗？可以先比较失败用例的输出，再到轨迹找对应事件。"
          : "如果不确定从哪儿入手，可以先跑一个样例，然后问我怎么看结果。");
        announce();
      }
      return;
    }
    if (!motion.checked || reducedMotion.matches || mood === "working" ||
      (!bubble.hidden && bubble.dataset.kind !== "welcome")) return;
    const activities = [["walk", 1900], ["look", 2000], ["sit", 4300], ["snack", 2150], ["play", 1050], ["sleep", 4050]];
    const [action, duration] = activities[activityIndex++ % activities.length];
    const canWalk = !manuallyPlaced && !avatar.matches(":hover, :focus-visible") && idle > 1100;
    if (action !== "walk" || !canWalk) {
      setPose(action === "walk" ? "look" : action, duration);
      return;
    }
    if (!bubble.hidden) hideBubble();
    const style = getComputedStyle(avatar);
    const homeX = innerWidth - avatar.offsetWidth - parseFloat(style.getPropertyValue("--pet-edge"));
    const homeY = innerHeight - avatar.offsetHeight - parseFloat(style.getPropertyValue("--pet-bottom"));
    roamingLeft = !roamingLeft;
    avatar.dataset.facing = roamingLeft ? "left" : "right";
    avatar.dataset.roaming = "true";
    setPose("walk", duration);
    move(homeX - (roamingLeft ? Math.min(330, innerWidth * .26) : 0), homeY);
    roamTimeout = setTimeout(() => { delete avatar.dataset.roaming; }, 1900);
  }
  function startPatrol() {
    clearInterval(patrolTimer);
    patrolTimer = setInterval(patrol, 5200);
  }

  function setOpen(open, focus = true) {
    stopRoaming();
    updateAppearance();
    panel.hidden = !open;
    avatar.setAttribute("aria-expanded", String(open));
    if (open) {
      hideBubble();
      place(panel);
      if (focus) byId("pet-title").focus();
    } else {
      clearVoiceHold();
      voice.stop();
      if (focus && !avatar.hidden) avatar.focus();
    }
  }

  function reveal(kind) {
    setOpen(false, false);
    openResult(activeRun.id, kind);
  }

  async function showQuiz() {
    const lab = activeLab();
    const lesson = petLessons[lab];
    if (!lesson) return speak("选择一个实验，我就能给你出一道相关的小题。");
    const status = (await readMemory(lab))?.study;
    if (panel.hidden || lab !== activeLab()) return;
    const [question, options, correct, explanation] = lesson;
    const reply = speak(status && status.answers > status.correct
      ? "再用一道概念题确认刚才的知识点。可以回看系统调用后再答。"
      : "来做一道概念题。答错了也可以再试。");
    byId("pet-question").textContent = question;
    choices.replaceChildren(...options.map((option, i) => button(option, () => {
      const isCorrect = i === correct;
      remember({type: "answer", lab, choice: i, correct: isCorrect});
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
    return reply;
  }

  function showMemoryStatus(text = "") {
    memoryStatus.textContent = text;
    memoryStatus.hidden = !text;
    place(panel);
  }

  function remember(event) {
    memory.write(event).then(() => showMemoryStatus()).catch(error => showMemoryStatus(error.message));
  }

  async function readMemory(lab = activeLab()) {
    try {
      return await memory.read(lab);
    } catch (error) {
      showMemoryStatus(error.message);
      return null;
    }
  }

  function recordRun(run) {
    if (run?.lab && run.score) remember({type: "run", lab: run.lab, score: run.score, run_id: run.id});
  }

  async function reportProgress() {
    const snapshot = await readMemory();
    if (!snapshot) return speak("当前无法读取本轮学习进度。");
    const {runs, answers, correct, score} = snapshot.study;
    const recent = score ? "最近一次通过 " + score.join("/") + " 个用例。" : "";
    const next = score && score[0] < score[1]
      ? "下一步可以查看失败用例和对应轨迹。"
      : answers > correct ? "下一步可回看刚才的概念，再试一次。"
      : "可以做一道概念题来检验理解。";
    return speak("当前实验评测 " + runs + " 次。" + recent +
      "概念题答对 " + correct + "/" + answers + " 次。" + next);
  }

  async function recap() {
    const snapshot = await readMemory();
    if (!snapshot) return speak("当前无法读取本轮回顾。");
    const {views, runs, answers, questions, last_event: event, previous_reply: previous} = snapshot;
    return speak("本轮看过 " + views + " 个页面区域，完成 " + runs + " 次评测、" + answers +
      " 次小测作答，提出 " + questions + " 个问题。" +
      (event ? "最近关注的是事件 #" + event.id + " 的 " + event.call + "。" : "") +
      (previous ? "上一问的建议是：" + previous : ""));
  }

  function observe(next, total) {
    const changed = view !== next;
    view = next;
    visibleEvents = total;
    selectedEvent = undefined;
    const runId = activeRun?.id;
    const previous = lastVisit;
    if (!previous || previous.view !== view || previous.total !== total || previous.runId !== runId) {
      lastVisit = {view, total, runId};
      if (previous) remember({type: "view", view, total, run_id: runId});
    }
    if (changed && (view === "history" || ((view === "trace" || view === "hints") && activeRun?.hasResult))) {
      explainView();
      announce();
    }
  }

  function explain(event) {
    selectedEvent = event;
    remember({type: "event", ...event});
    if (avatar.hidden) {
      avatar.hidden = false;
      restore.hidden = true;
      quickStudy.hidden = false;
    }
    setOpen(true);
    explainSelected();
  }

  function explainSelected(event = selectedEvent) {
    const {id, call, kind, errno} = event;
    const clue = callClues[callAliases[call] || call];
    const observation = errno ? "返回 " + errno + "。"
      : kind === "pending" ? "采集结束时尚未观察到返回。"
      : kind === "partial" ? "这条记录只有调用的一部分。"
      : "";
    return speak("事件 #" + id + " 的 " + call + "。" + observation +
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

  async function respond(text) {
    if (recallQuestion.test(text)) return recap();
    if (/进度|学得|学到哪|答了几|小结|掌握/.test(text)) return reportProgress();
    if (/刚才.*(那条|事件|调用)|之前.*(那条|事件|调用)/.test(text)) {
      const event = (await readMemory())?.last_event;
      return event ? explainSelected(event) : explainView();
    }
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
    const contextButtons = [button("来道小测", showQuiz), button("学习进度", reportProgress), button("本轮回顾", recap)];
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
    } else if (run?.hasResult) {
      mood = "review";
      speak(run.confidence === "insufficient"
        ? "这次线索还不够。我们可以从最后几条调用开始找。"
        : "先歇一口气。我们有运行线索，可以打开结果一步一步看。");
    } else if (run) {
      mood = "working";
      speak(run.state === "analyzing" ? "运行结束了，正在核对判定和证据。" : "实验在运行队列中，我在这里陪你等结果。");
    } else {
      speak(greeting);
    }
    updateAppearance();
    if (run) announce();
    else if (!greeted) greet();
    if (mood === "success") celebrate();
  }

  avatar.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0) return;
    stopRoaming();
    const {left, top} = avatar.getBoundingClientRect();
    moved = false;
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, left, top, active: false};
  });
  function clearHoverGaze() {
    delete avatar.dataset.gaze;
    avatar.style.removeProperty("--gaze-frame");
  }

  function followPointer(event) {
    if (avatar.dataset.gaze !== "pointer" || drag) return;
    const {left, width} = avatar.getBoundingClientRect();
    const ratio = (event.clientX - left) / width;
    const facing = avatar.dataset.facing === "left" ? 1 - ratio : ratio;
    const frame = facing < .37 ? 6 : facing > .63 ? 2 : 0;
    avatar.style.setProperty("--gaze-frame", (-frame * 12.5) + "%");
  }

  avatar.addEventListener("pointerenter", event => {
    if (event.pointerType !== "mouse" || drag || !panel.hidden || !motion.checked ||
        reducedMotion.matches || avatar.dataset.roaming) return;
    const reactions = [["greet", 1450], ["look", 2400], ["play", 1050], ["sit", 2300]];
    const [pose, duration] = reactions[hoverIndex++ % reactions.length];
    hoverActive = true;
    setPose(pose, duration);
    if (pose === "look") {
      avatar.dataset.gaze = "pointer";
      followPointer(event);
    }
  });
  avatar.addEventListener("pointerleave", () => {
    hoverActive = false;
    clearHoverGaze();
  });
  avatar.addEventListener("pointermove", followPointer);
  window.addEventListener("pointermove", event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.active && Math.hypot(dx, dy) < 6) return;
    if (!drag.active) {
      drag.active = moved = true;
      manuallyPlaced = true;
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
    stopRoaming();
    manuallyPlaced = true;
    const {left, top} = avatar.getBoundingClientRect();
    const distance = event.shiftKey ? 48 : 16;
    move(left + direction[0] * distance, top + direction[1] * distance);
  });
  window.addEventListener("resize", () => {
    stopRoaming();
    if (manuallyPlaced && position) move(position.x, position.y);
    else goHome();
  });
  function clearVoiceHold() {
    clearTimeout(holdTimer);
    holdTimer = undefined;
    const end = releaseVoice;
    releaseVoice = undefined;
    return end;
  }

  function cancelVoiceHold() {
    if (clearVoiceHold()) voice.stop();
  }

  function canHoldVoice() {
    const focused = document.activeElement;
    return !avatar.hidden && !quickVoice.disabled && !document.hidden &&
      !document.querySelector("dialog[open]") &&
      !focused?.isContentEditable && !focused?.closest("input:not([type=checkbox], [type=radio]), textarea, select, [role=textbox]");
  }

  document.addEventListener("keydown", event => {
    lastInteraction = performance.now();
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229 || document.querySelector("dialog[open]")) return;
    if (event.key === "Escape") {
      if (!panel.hidden) setOpen(false);
      else cancelVoiceHold();
      return;
    }
    if (event.code !== "KeyT" || event.ctrlKey || event.altKey || event.shiftKey || event.metaKey || !canHoldVoice()) return;
    event.preventDefault();
    if (event.repeat || holdTimer !== undefined || releaseVoice) return;
    holdTimer = setTimeout(() => {
      holdTimer = undefined;
      if (!canHoldVoice()) return;
      if (panel.hidden) setOpen(true, false);
      releaseVoice = voice.startInput(true);
    }, 300);
  });
  document.addEventListener("keyup", event => {
    if (event.code !== "KeyT" || (holdTimer === undefined && !releaseVoice)) return;
    event.preventDefault();
    const finish = clearVoiceHold();
    finish?.();
  });
  window.addEventListener("blur", cancelVoiceHold);
  document.addEventListener("pointerdown", () => { lastInteraction = performance.now(); }, {passive: true});
  motion.addEventListener("change", () => {
    avatar.dataset.motion = String(motion.checked);
    if (!motion.checked) {
      cancelArtwork();
      if (!manuallyPlaced) goHome();
      updateAppearance();
    }
  });
  proactive.addEventListener("change", () => {
    if (!proactive.checked) hideBubble();
    else if (!greeted) greet();
  });
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches && !manuallyPlaced) goHome();
  });
  quickStudy.addEventListener("click", event => {
    const action = event.target.closest("[data-study]")?.dataset.study;
    if (!action) return;
    setOpen(true);
    if (action === "chat") input.focus();
    else if (action === "voice") byId("pet-mic").click();
    else if (action === "quiz") showQuiz();
    else reportProgress();
  });
  byId("pet-close").addEventListener("click", () => setOpen(false));
  byId("pet-hide").addEventListener("click", () => {
    setOpen(false, false);
    hideBubble();
    avatar.hidden = true;
    cancelArtwork();
    restore.hidden = false;
    quickStudy.hidden = true;
    updateAppearance();
    restore.focus();
  });
  restore.addEventListener("click", () => {
    restore.hidden = true;
    avatar.hidden = false;
    quickStudy.hidden = false;
    if (!greeted) greet();
    else announce();
    avatar.focus();
  });
  reset.addEventListener("click", () => {
    goHome();
    byId("pet-close").focus();
  });
  input.addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!event.repeat && !send.disabled) form.requestSubmit(send);
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
    voice.stop();
    send.disabled = true;
    input.value = "";
    message.textContent = "正在回复…";
    try {
      const reply = await respond(text);
      if (!panel.hidden) voice.readReply(true);
      remember({type: "question", question: text, reply: reply || message.textContent, recap: recallQuestion.test(text)});
    } catch (error) {
      if (!input.value) input.value = text;
      speak("这次没能回复，请再试一次。");
      showMemoryStatus(error.message);
    } finally {
      send.disabled = false;
    }
  });
  select.addEventListener("change", () => { quiz.hidden = true; place(panel); });
  window.addEventListener("pagehide", () => {
    cancelVoiceHold();
    clearInterval(patrolTimer);
    cancelArtwork();
    stopRoaming();
    clearTimeout(poseTimer);
    memory.close();
    lastVisit = undefined;
    activeRun = undefined;
    lastUpdate = undefined;
    greeted = false;
    pendingBubble = undefined;
    input.value = "";
    selectedEvent = undefined;
    visibleEvents = undefined;
    message.textContent = "";
    choices.replaceChildren();
    quiz.hidden = true;
    hideBubble();
  });
  window.addEventListener("pageshow", event => {
    if (event.persisted) {
      lastInteraction = performance.now();
      startPatrol();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      cancelVoiceHold();
      clearInterval(patrolTimer);
      cancelArtwork();
      stopRoaming();
      hideBubble();
    } else {
      if (!greeted) greet();
      else if (pendingBubble) announce(pendingBubble);
      startPatrol();
    }
  });
  startPatrol();
  function enableVoice(available) {
    voice.enableServer(available);
    quickVoice.disabled = byId("pet-mic").disabled;
    quickVoice.title = byId("pet-mic").title;
  }
  avatar.disabled = false;
  for (const control of quickStudy.querySelectorAll('button:not([data-study="voice"])')) control.disabled = false;
  return {update, observe, explain, recordRun, enableVoice};
}

companion = makeCompanion(() => select.value, openPetResult);
companion.enableVoice(voiceConfig);
companion.update(petSnapshot(record));
companion.observe("grade");
window.addEventListener("pageshow", event => {
  if (!event.persisted) return;
  companion.update(petSnapshot(record));
  companion.observe(byId("workspace").hidden ? "history" : tab);
});
