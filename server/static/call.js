// A live outbound call over AssemblyAI's Voice Agent API, from the browser.
// The server hands out a one-time token, so the API key never reaches this page.

const WS_URL = "wss://agents.assemblyai.com/v1/ws";
const RATE = 24000;

function bytesToB64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function joinB64(chunks) {
  const parts = chunks.map(b64ToBytes);
  const all = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { all.set(p, at); at += p.length; }
  return bytesToB64(all);
}

export class Call {
  /**
   * handlers: getToken() -> token, runTool(name, args) -> result object,
   * onStatus(text, kind), onTranscript(role, text, isGreeting),
   * onReplyAudio({ audio: b64 | null, text, isGreeting, interrupted }), onError(text)
   */
  constructor(handlers) {
    this.h = handlers;
    this.pending = [];
    this.last = null;
    this.ready = false;
    this.closed = false;
    this.sources = new Set();
    this.nextTime = 0;
    this.replies = 0; // replies started so far; the first one is the opening line
    this.cur = null;  // the reply being spoken: its audio, its text, and whether it's finished
  }

  async start(session) {
    this.h.onStatus?.("Starting microphone…");
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("capture-processor.js");
    await this.ctx.resume();
    this.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false } });

    this.h.onStatus?.("Dialling…");
    const token = await this.h.getToken();
    const node = new AudioWorkletNode(this.ctx, "capture-processor", { processorOptions: { inputRate: this.ctx.sampleRate } });
    this.ctx.createMediaStreamSource(this.mic).connect(node);
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    node.connect(mute).connect(this.ctx.destination); // keeps the worklet running without echoing the mic

    const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);
    this.ws = ws;
    node.port.onmessage = ({ data }) => {
      if (this.ready && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input.audio", audio: bytesToB64(new Uint8Array(data)) }));
      }
    };
    ws.onopen = () => ws.send(JSON.stringify({ type: "session.update", session }));
    ws.onmessage = (e) => this.onEvent(JSON.parse(e.data));
    ws.onerror = () => this.h.onError?.("Couldn't connect to AssemblyAI.");
    ws.onclose = () => {
      if (!this.closed) this.h.onStatus?.("Call ended.", "ended");
      this.cleanup();
    };
    this.onPageHide = () => this.hangup();
    addEventListener("pagehide", this.onPageHide);
  }

  onEvent(ev) {
    switch (ev.type) {
      case "session.ready":
        this.ready = true;
        this.h.onStatus?.("Connected. The agent is reading the reminder.", "live");
        break;
      case "reply.started":
        this.last = ev.type;
        this.cur = { chunks: [], text: null, done: false, interrupted: false, isGreeting: this.replies === 0 };
        this.replies += 1;
        break;
      case "input.speech.started":
        this.last = ev.type;
        break;
      case "reply.audio":
        this.play(ev.data);
        if (!this.cur || this.cur.done) { // in case audio arrives without a reply.started first
          this.cur = { chunks: [], text: null, done: false, interrupted: false, isGreeting: this.replies === 0 };
          this.replies += 1;
        }
        this.cur.chunks.push(ev.data);
        break;
      case "transcript.agent":
        if (this.cur) this.cur.text = ev.text;
        this.h.onTranscript?.("agent", ev.text, this.cur?.isGreeting ?? false);
        this.reportReply();
        break;
      case "transcript.user":
        this.h.onTranscript?.("user", ev.text, false);
        break;
      case "reply.done":
        this.last = "reply.done";
        if (ev.status === "interrupted") {
          this.stopPlayback();
          this.pending = [];
        }
        if (this.cur) {
          this.cur.done = true;
          this.cur.interrupted = ev.status === "interrupted";
          if (this.cur.isGreeting) this.h.onStatus?.("Your turn: ask the agent anything.", "live");
          this.reportReply();
        }
        this.flush();
        break;
      case "tool.call":
        Promise.resolve(this.h.runTool(ev.name, ev.arguments || {}))
          .then((result) => this.pending.push({ call_id: ev.call_id, result: JSON.stringify(result) }))
          .catch((err) => this.pending.push({ call_id: ev.call_id, result: JSON.stringify({ error: String(err) }), is_error: true }))
          .finally(() => this.flush());
        break;
      case "session.ended":
        this.closed = true;
        this.h.onStatus?.("Call ended.", "ended");
        break;
      case "session.error":
      case "error":
        this.h.onError?.(ev.message || ev.code || "The call hit an error.");
        break;
    }
  }

  // Hand a finished reply (its audio and what the agent meant to say) to the page, once both have arrived.
  reportReply() {
    const r = this.cur;
    if (!r || !r.done || r.text === null || r.reported) return;
    r.reported = true;
    if (!r.text.trim()) return; // a silent reply, e.g. while a tool runs
    this.h.onReplyAudio?.({ audio: r.interrupted || !r.chunks.length ? null : joinB64(r.chunks), text: r.text, isGreeting: r.isGreeting, interrupted: r.interrupted });
  }

  // Tool results go back only when the agent has finished speaking (AssemblyAI's timing rule).
  flush() {
    if (this.last !== "reply.done" || !this.pending.length || this.ws?.readyState !== WebSocket.OPEN) return;
    for (const p of this.pending) this.ws.send(JSON.stringify({ type: "tool.result", ...p }));
    this.pending = [];
  }

  play(b64) {
    const bytes = b64ToBytes(b64);
    const view = new DataView(bytes.buffer);
    const samples = new Float32Array(bytes.length / 2);
    for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
    const buffer = this.ctx.createBuffer(1, samples.length, RATE);
    buffer.getChannelData(0).set(samples);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.ctx.destination);
    this.nextTime = Math.max(this.nextTime, this.ctx.currentTime);
    src.start(this.nextTime);
    this.nextTime += buffer.duration;
    this.sources.add(src);
    src.onended = () => this.sources.delete(src);
  }

  stopPlayback() {
    for (const s of this.sources) { try { s.stop(); } catch {} }
    this.sources.clear();
    this.nextTime = this.ctx?.currentTime || 0;
  }

  async hangup() {
    this.closed = true;
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "session.end" })); // closing without this keeps the session billable for 30 s
      await new Promise((resolve) => { ws.addEventListener("close", resolve, { once: true }); setTimeout(resolve, 1500); });
      try { ws.close(); } catch {}
    }
    this.cleanup();
  }

  cleanup() {
    this.ready = false;
    this.stopPlayback();
    this.mic?.getTracks().forEach((t) => t.stop());
    if (this.ctx && this.ctx.state !== "closed") this.ctx.close();
    if (this.onPageHide) removeEventListener("pagehide", this.onPageHide);
  }
}
