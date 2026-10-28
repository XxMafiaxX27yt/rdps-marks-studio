// The engine: runs the Python core (markstudio) inside the browser with Pyodide,
// in a background worker so the page stays smooth. Nothing leaves this computer.
import { loadPyodide } from "../vendor/pyodide/pyodide.mjs";

let py = null;
let bridge = null;
const BYTES_FNS = new Set(["build_workbook_bytes", "template_bytes", "board_workbook_bytes", "board_template_bytes"]);

const BRIDGE = `
import json, sys
sys.path.insert(0, "/home/pyodide/app")
from pyodide.ffi import to_js
from markstudio import api

def _arg(a):
    if isinstance(a, memoryview):
        return bytes(a)
    return a

def call(fn, args):
    args = [_arg(a) for a in (args.to_py() if hasattr(args, "to_py") else args)]
    f = getattr(api, fn)
    out = f(*args)
    if isinstance(out, (bytes, bytearray)):
        return to_js(memoryview(out))
    return out
`;

async function boot() {
  const t0 = performance.now();
  post({ type: "progress", value: 12, text: "Starting the Python engine…" });
  py = await loadPyodide({ indexURL: new URL("../vendor/pyodide/", import.meta.url).href, fullStdLib: false });
  post({ type: "progress", value: 60, text: "Loading the Excel tools…" });
  const build = await (await fetch(new URL("../build.json", import.meta.url))).json();
  for (const w of build.wheels) {
    const buf = await (await fetch(new URL(`../py/wheels/${w}`, import.meta.url))).arrayBuffer();
    py.unpackArchive(buf, "wheel");
  }
  post({ type: "progress", value: 80, text: "Loading the RDPS rules…" });
  const z = await (await fetch(new URL(`../py/markstudio.zip?v=${build.version}`, import.meta.url))).arrayBuffer();
  py.unpackArchive(z, "zip", { extractDir: "/home/pyodide/app" });
  py.runPython(BRIDGE);
  bridge = py.globals.get("call");
  post({ type: "progress", value: 100, text: "Ready" });
  post({ type: "ready", version: build.version, ms: Math.round(performance.now() - t0) });
}

function post(m, transfer) { self.postMessage(m, transfer || []); }

self.onmessage = async (ev) => {
  const { id, fn, args } = ev.data;
  if (fn === "__boot") return;
  try {
    if (!bridge) throw new Error("Engine is still starting");
    const out = bridge(fn, args || []);
    if (BYTES_FNS.has(fn)) {
      let jsv = out;
      if (jsv && typeof jsv.toJs === "function") { const t = jsv.toJs(); if (jsv.destroy) jsv.destroy(); jsv = t; }
      const u8 = jsv instanceof Uint8Array ? jsv : new Uint8Array(jsv);
      const copy = u8.slice();
      post({ id, ok: true, bytes: copy }, [copy.buffer]);
    } else {
      let val = out;
      if (val && typeof val === "object" && val.toJs) { const j = val.toJs(); val.destroy(); val = j; }
      post({ id, ok: true, value: val });
    }
  } catch (e) {
    post({ id, ok: false, error: String(e && e.message ? e.message : e).split("\n").slice(-3).join(" ") });
  }
};

boot().catch((e) => post({ type: "fatal", error: String(e && e.message ? e.message : e) }));
