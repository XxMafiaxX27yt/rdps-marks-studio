// Talks to the engine worker. call("fn", ...args) -> parsed result.
let worker = null;
let seq = 0;
const waiting = new Map();
const listeners = { progress: [], ready: [], fatal: [] };
let readyPromise = null;

export function on(type, fn) { listeners[type].push(fn); }

export function start() {
  if (readyPromise) return readyPromise;
  readyPromise = new Promise((resolve, reject) => {
    worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === "progress") return listeners.progress.forEach((f) => f(m));
      if (m.type === "ready") { listeners.ready.forEach((f) => f(m)); return resolve(m); }
      if (m.type === "fatal") { listeners.fatal.forEach((f) => f(m)); return reject(new Error(m.error)); }
      const w = waiting.get(m.id);
      if (!w) return;
      waiting.delete(m.id);
      if (!m.ok) return w.reject(new Error(m.error));
      if (m.bytes) return w.resolve(m.bytes);
      w.resolve(m.value);
    };
    worker.onerror = (e) => { listeners.fatal.forEach((f) => f({ error: e.message })); reject(e); };
  });
  return readyPromise;
}

function raw(fn, args) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    waiting.set(id, { resolve, reject });
    const transfer = [];
    worker.postMessage({ id, fn, args }, transfer);
  });
}

// JSON-returning API functions: {ok, data} | {ok:false, error}
export async function call(fn, ...args) {
  await readyPromise;
  const out = await raw(fn, args);
  const j = typeof out === "string" ? JSON.parse(out) : out;
  if (j && j.ok === false) { const e = new Error(j.error); e.detail = j.detail; throw e; }
  return j && "data" in j ? j.data : j;
}

// Byte-returning functions (workbooks, templates)
export async function bytes(fn, ...args) {
  await readyPromise;
  return raw(fn, args);
}

// Plain-value functions (e.g. workbook_name)
export async function value(fn, ...args) {
  await readyPromise;
  return raw(fn, args);
}
