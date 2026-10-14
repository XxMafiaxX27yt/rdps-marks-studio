// Runs the on-device AI models in the background (so the page never freezes).
// Models are downloaded once from Hugging Face and kept by the browser; no student data is sent anywhere.
import * as T from "../vendor/transformers/transformers.min.js";

const EMBED_MODEL = "Xenova/paraphrase-multilingual-MiniLM-L12-v2";
const SPEECH_MODEL = "onnx-community/whisper-base";
T.env.allowLocalModels = false;
T.env.useBrowserCache = true;
T.env.backends.onnx.wasm.wasmPaths = new URL("../vendor/transformers/", import.meta.url).href;
T.env.backends.onnx.wasm.numThreads = 1;

let embedder = null, speech = null;
let examples = [], headers = [];

function progress(kind) {
  const files = {};
  return (p) => {
    if (p.status === "progress" && p.file) {
      files[p.file] = p.progress || 0;
      const v = Object.values(files);
      self.postMessage({ type: "progress", kind, pct: Math.round(v.reduce((a, b) => a + b, 0) / v.length) });
    }
  };
}

async function embed(texts) {
  const out = [];
  for (let i = 0; i < texts.length; i += 32) {
    const r = await embedder(texts.slice(i, i + 32), { pooling: "mean", normalize: true });
    out.push(...r.tolist());
  }
  return out;
}
function dot(a, b) { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }

const handlers = {
  async loadEmbedder({ examples: ex, headers: hd }) {
    embedder = embedder || await T.pipeline("feature-extraction", EMBED_MODEL, { dtype: "q8", progress_callback: progress("embed") });
    const ev = await embed(ex.map((e) => e.text));
    examples = ex.map((e, i) => ({ ...e, vec: ev[i] }));
    if (hd) {
      const hv = await embed(hd.map((h) => h.label));
      headers = hd.map((h, i) => ({ ...h, vec: hv[i] }));
    }
    return true;
  },
  async hints({ text, kind }) {
    const [v] = await embed([text]);
    const best = {};
    for (const e of examples) {
      if (e.kind !== kind) continue;
      const s = dot(v, e.vec);
      if (!best[e.intent] || s > best[e.intent].score) best[e.intent] = { intent: e.intent, score: s, example: e.text };
    }
    return Object.values(best).sort((a, b) => b.score - a.score).slice(0, 3);
  },
  async header({ text }) {
    const [v] = await embed([text]);
    let best = null;
    for (const h of headers) {
      const s = dot(v, h.vec);
      if (!best || s > best.score) best = { label: h.label, role: h.role, subject: h.subject, component: h.component, score: s };
    }
    return best && best.score >= 0.5 ? best : null;
  },
  async loadSpeech() {
    speech = speech || await T.pipeline("automatic-speech-recognition", SPEECH_MODEL,
      { dtype: { encoder_model: "fp32", decoder_model_merged: "q8" }, progress_callback: progress("speech") });
    return true;
  },
  async transcribe({ audio, lang }) {
    await handlers.loadSpeech();
    const opts = lang === "hi" ? { language: "hindi", task: "translate" } : { language: "english", task: "transcribe" };
    const out = await speech(audio, { ...opts, chunk_length_s: 30 });
    return (out.text || "").trim();
  },
};

self.onmessage = async (ev) => {
  const { id, fn, args } = ev.data;
  try {
    const value = await handlers[fn](args || {});
    self.postMessage({ id, ok: true, value });
  } catch (e) {
    self.postMessage({ id, ok: false, error: String(e && e.message ? e.message : e) });
  }
};
