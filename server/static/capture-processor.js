// AudioWorklet: microphone audio at the context's rate -> 24 kHz mono PCM16 for the Voice Agent API.
class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.step = options.processorOptions.inputRate / 24000;
    this.phase = 0;
  }

  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    const out = [];
    while (this.phase < ch.length) {
      const s = Math.max(-1, Math.min(1, ch[Math.floor(this.phase)]));
      out.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      this.phase += this.step;
    }
    this.phase -= ch.length;
    if (out.length) {
      const pcm = Int16Array.from(out);
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
