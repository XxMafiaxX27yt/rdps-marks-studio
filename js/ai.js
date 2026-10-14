// On-device AI (runs on this computer's processor - no GPU needed, no data sent anywhere).
// 1. A small "understanding" model turns sentences into numbers that capture their meaning,
//    so questions in your own words (English or Hinglish) match the right kind of question.
// 2. Whisper turns speech into text for voice questions.
// The models run in a background worker (ai-worker.js); model files are downloaded once and kept.

let worker = null;
let seq = 0;
const waiting = new Map();
const listeners = new Set();
export const status = { embed: "off", embedPct: 0, speech: "off", speechPct: 0 };
let embedLoading = null, speechLoading = null;

export function onStatus(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { listeners.forEach((f) => f(status)); }

function w() {
  if (worker) return worker;
  worker = new Worker(new URL("./ai-worker.js", import.meta.url), { type: "module" });
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === "progress") { status[m.kind + "Pct"] = m.pct; emit(); return; }
    const p = waiting.get(m.id);
    if (!p) return;
    waiting.delete(m.id);
    m.ok ? p.resolve(m.value) : p.reject(new Error(m.error));
  };
  worker.onerror = (e) => {
    waiting.forEach((p) => p.reject(new Error(e.message || "AI worker failed")));
    waiting.clear();
  };
  return worker;
}

function call(fn, args, transfer) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    waiting.set(id, { resolve, reject });
    w().postMessage({ id, fn, args }, transfer || []);
  });
}

export function loadEmbedder(examples, headers) {
  if (status.embed === "ready") return Promise.resolve(true);
  if (embedLoading) return embedLoading;
  status.embed = "loading"; emit();
  embedLoading = call("loadEmbedder", { examples, headers })
    .then(() => { status.embed = "ready"; emit(); return true; })
    .catch((e) => { status.embed = "error"; status.embedError = e.message; embedLoading = null; emit(); throw e; });
  return embedLoading;
}

export async function intentHints(text, kind = "question") {
  if (status.embed !== "ready") return null;
  return call("hints", { text, kind });
}

export async function suggestHeader(text) {
  if (status.embed !== "ready" || !text) return null;
  return call("header", { text });
}

export function loadSpeech() {
  if (status.speech === "ready") return Promise.resolve(true);
  if (speechLoading) return speechLoading;
  status.speech = "loading"; emit();
  speechLoading = call("loadSpeech", {})
    .then(() => { status.speech = "ready"; emit(); return true; })
    .catch((e) => { status.speech = "error"; status.speechError = e.message; speechLoading = null; emit(); throw e; });
  return speechLoading;
}

export async function transcribe(audio, lang = "en") {
  await loadSpeech();
  return call("transcribe", { audio, lang }, [audio.buffer]);
}

// Microphone -> 16 kHz mono samples (stays on this computer)
export class Recorder {
  constructor(onLevel) { this.onLevel = onLevel; }
  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    this.ctx = new AudioContext();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.an = this.ctx.createAnalyser();
    this.an.fftSize = 256;
    src.connect(this.an);
    this.rec = new MediaRecorder(this.stream);
    this.chunks = [];
    this.rec.ondataavailable = (e) => this.chunks.push(e.data);
    this.rec.start();
    const data = new Uint8Array(this.an.frequencyBinCount);
    const tick = () => {
      if (!this.rec || this.rec.state !== "recording") return;
      this.an.getByteFrequencyData(data);
      this.onLevel && this.onLevel(0, data);
      this.raf = requestAnimationFrame(tick);
    };
    tick();
  }
  async stop() {
    const done = new Promise((r) => (this.rec.onstop = r));
    this.rec.stop();
    await done;
    cancelAnimationFrame(this.raf);
    this.stream.getTracks().forEach((t) => t.stop());
    const blob = new Blob(this.chunks, { type: this.rec.mimeType });
    const decoded = await this.ctx.decodeAudioData(await blob.arrayBuffer());
    await this.ctx.close();
    const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000);
    const s = off.createBufferSource();
    s.buffer = decoded;
    s.connect(off.destination);
    s.start();
    const rendered = await off.startRendering();
    return new Float32Array(rendered.getChannelData(0));
  }
}
