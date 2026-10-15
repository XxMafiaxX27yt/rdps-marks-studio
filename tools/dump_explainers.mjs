// Prints the "?" explainers (title, steps, text, visuals) as JSON, read straight from web/js/explain.js.
// Plain Node - no browser. Used by make_explainer_media.py.
import { pathToFileURL } from "node:url";
import path from "node:path";

const noop = () => {};
globalThis.document = { addEventListener: noop, documentElement: { dataset: {}, classList: { toggle: noop } },
  querySelector: () => null, querySelectorAll: () => [] };
globalThis.matchMedia = () => ({ matches: false });
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });

const file = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..", "web", "js", "explain.js");
const m = await import(pathToFileURL(file).href);
process.stdout.write(JSON.stringify(m.EXPLAINERS.map((e) => ({
  id: e.id, title: e.title, area: e.area,
  steps: e.steps.map((s) => ({ text: s.text, say: s.say || "", visual: s.visual })),
}))));
