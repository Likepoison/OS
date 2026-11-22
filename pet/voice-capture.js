class VoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Int16Array(sampleRate * 12);
    this.offset = 0;
    this.finished = false;
    this.port.onmessage = () => this.finish();
  }

  finish() {
    if (this.finished) return;
    this.finished = true;
    const audio = this.samples.slice(0, this.offset).buffer;
    this.port.postMessage(audio, [audio]);
  }

  process(inputs) {
    if (this.finished) return false;
    const channel = inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length && this.offset < this.samples.length; i++) {
      const sample = Math.max(-1, Math.min(1, channel[i]));
      this.samples[this.offset++] = sample * (sample < 0 ? 32768 : 32767);
    }
    if (this.offset === this.samples.length) this.finish();
    return !this.finished;
  }
}

registerProcessor("trace-voice-capture", VoiceCapture);
