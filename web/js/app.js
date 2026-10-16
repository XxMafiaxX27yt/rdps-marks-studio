// RDPS Marks Studio - app shell: splash, navigation, theme, presentation mode, engine start.
import * as engine from "./engine.js";
import { S, LS, prefs, savePrefs } from "./state.js";
import { $, $$, toast, destroyCharts } from "./ui.js";
import * as school from "./pages/school.js";
import * as boardPage from "./pages/board.js";
import * as ask from "./pages/ask.js";
import * as settingsPage from "./pages/settings.js";
import * as extra from "./pages/extra.js";
import * as teachersPage from "./pages/teachers.js";
import * as explain from "./explain.js";
import { startTour } from "./tour.js";
import * as ai from "./ai.js";

const PAGES = { school, board: boardPage, ask, teachers: teachersPage, template: extra.template, settings: settingsPage, help: explain.page };

// ---------------------------------------------------------------- theme
function applyTheme() {
  const t = prefs.theme;
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
applyTheme();
$("#btn-theme").addEventListener("click", () => {
  const dark = prefs.theme ? prefs.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  prefs.theme = dark ? "light" : "dark";
  savePrefs();
  applyTheme();
  render();          // charts pick up the new colours
});

// ---------------------------------------------------------------- presentation mode
const halo = $("#pointer-halo");
let present = false;
function setPresent(on) {
  present = on;
  document.documentElement.classList.toggle("present", on);
  $("#btn-present").classList.toggle("on", on);
  if (on) {
    toast("Presentation mode: bigger text and a pointer highlight. <button class='link-btn' id='tour-go'>Start the guided tour →</button>", "info", 6000);
    setTimeout(() => { const b = $("#tour-go"); b && b.addEventListener("click", () => startTour(S.route)); }, 50);
  }
  render();
}
$("#btn-present").addEventListener("click", () => setPresent(!present));
document.addEventListener("pointermove", (e) => { if (present) halo.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`; });
document.addEventListener("pointerdown", () => { if (present) { halo.classList.add("click"); setTimeout(() => halo.classList.remove("click"), 160); } });

// mobile menu
$("#btn-menu").addEventListener("click", () => $("#nav").classList.toggle("open"));
$("#nav").addEventListener("click", () => $("#nav").classList.remove("open"));

// ---------------------------------------------------------------- routing
function route() {
  const r = (location.hash.replace(/^#\/?/, "") || "school").split("/")[0];
  S.route = PAGES[r] ? r : "school";
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === S.route));
  render();
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
}
window.addEventListener("hashchange", route);

export function render() {
  destroyCharts();
  const page = PAGES[S.route];
  const main = $("#app");
  main.innerHTML = `<div class="page">${page.html()}</div>`;
  // listeners go on the fresh page element, so they disappear with it on the next render
  page.mount && page.mount(main.firstElementChild);
}
window.__render = render;

// ---------------------------------------------------------------- engine start
const chip = $("#engine-chip");
const splash = $("#splash");

// ---------------------------------------------------------------- intro: chalk marks fly into the globe (first visit),
// the motto writes itself, and the ring around the logo shows what has REALLY loaded
const fullIntro = document.documentElement.classList.contains("intro-first");   // set by intro-flag.js
const firstVisit = !LS.get("rdps.introSeen", false);
const minSplash = new Promise((r) => setTimeout(r, fullIntro ? 4800 : 1500));
const SEG = { engine: 0, excel: 1, ask: 2, voice: 3 };
const CIRC = 2 * Math.PI * 92, GAP = 14, LEN = CIRC / 4 - GAP;
const parts = { engine: 0, excel: 0, ask: 0, voice: 0 };
function part(name, value) {
  parts[name] = Math.max(parts[name], Math.min(1, value));
  const c = splash && splash.querySelector(`[data-seg="${name}"]`);
  if (c) {
    const len = LEN * parts[name];
    c.style.strokeDasharray = `${len} ${CIRC}`;
    c.style.strokeDashoffset = `${-(SEG[name] * (CIRC / 4) + GAP / 2)}`;
    c.classList.toggle("done", parts[name] >= 1);
  }
  const chipEl = splash && splash.querySelector(`[data-part="${name}"]`);
  if (chipEl) { chipEl.classList.toggle("busy", parts[name] > 0 && parts[name] < 1); chipEl.classList.toggle("done", parts[name] >= 1); }
}
Object.keys(SEG).forEach((k) => part(k, 0));
if (fullIntro) {
  // at the end of the chalk scene the numbers fly into the logo, and the logo "takes them in"
  setTimeout(() => {
    const badge = splash.querySelector(".splash-badge").getBoundingClientRect();
    const cx = badge.left + badge.width / 2, cy = badge.top + badge.height / 2;
    splash.querySelectorAll(".chalk-row b").forEach((b, i) => {
      const r = b.getBoundingClientRect();
      b.style.transitionDelay = `${i * 0.08}s`;
      b.style.transform = `translate(${cx - (r.left + r.width / 2)}px, ${cy - (r.top + r.height / 2)}px) scale(.3)`;
      b.classList.add("fly");
    });
    setTimeout(() => splash.classList.add("got"), 800);
  }, 2350);
}
let skipped = false;
const skipBtn = $("#splash-skip");
skipBtn && skipBtn.addEventListener("click", () => { skipped = true; hideSplash(); });
function hideSplash() {
  if (!splash || splash.classList.contains("gone")) return;
  splash.classList.add("gone");
  LS.set("rdps.introSeen", true);
  setTimeout(() => { splash.remove(); welcome(); }, 650);
}
// welcome card: greeting, where you left off, and three ways to start
function welcome() {
  const el = $("#welcome");
  if (!el) return;
  const h = new Date().getHours();
  const hi = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const day = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
  const last = LS.get("rdps.last", null);
  const lastTxt = last ? `Last time: ${last.label} · ${last.exam} (${last.when}). Upload the files again, or open the Excel you saved, to continue.`
    : "Upload a marks file to begin - or try the sample data to see everything first.";
  el.innerHTML = `<button class="x" aria-label="Close">✕</button><h3>${hi} 👋</h3><p>${day}. ${lastTxt}</p>
    <div class="row"><a class="btn btn-primary btn-sm" href="#/school" data-w="1">Upload marks</a>
    <a class="btn btn-ghost btn-sm" href="#/help" data-w="1">How it works</a><a class="btn btn-ghost btn-sm" href="#/ask" data-w="1">Ask a question</a></div>`;
  el.classList.remove("hidden", "out");
  const close = () => { el.classList.add("out"); setTimeout(() => el.classList.add("hidden"), 380); };
  el.onclick = (e) => { if (e.target.closest(".x, [data-w]")) close(); };
  setTimeout(close, 9000);
}
engine.on("progress", (m) => {
  const bar = $("#splash-progress"), note = $("#splash-note");   // the splash may already be gone
  if (bar) bar.style.width = m.value + "%";
  if (note) note.textContent = m.text;
  part("engine", m.value / 70);
  if (m.value >= 70) part("excel", (m.value - 70) / 30);
  chip.querySelector("span").textContent = m.value < 100 ? `Loading ${m.value}%` : "Ready";
});
// voice for the explainers: a tiny file list, so it is ready almost at once
fetch("assets/voice/manifest.json").then((r) => { if (r.ok) part("voice", 1); }).catch(() => part("voice", 1));
engine.on("fatal", (m) => {
  chip.className = "engine-chip error";
  chip.querySelector("span").textContent = "Engine error";
  const note = $("#splash-note");
  if (note) note.textContent = "Could not start: " + m.error;
  toast("The engine could not start in this browser. Please use a recent Chrome or Edge.<br><small>" + m.error + "</small>", "err", 12000);
});

async function boot() {
  route();
  const ready = engine.start();
  // the intro ends when the engine is ready (and the animation has played), or after a while at the most -
  // the engine keeps loading in the background and the page shows its own "getting ready" state
  const askReady = new Promise((r) => {
    const tick = () => (parts.ask >= 1 ? r() : setTimeout(tick, 150));
    tick();
  });
  Promise.race([
    Promise.all([ready, minSplash, Promise.race([askReady, new Promise((r) => setTimeout(r, 2500))])]),
    new Promise((r) => setTimeout(r, firstVisit ? 9000 : 6000)),
  ]).then(() => { if (!skipped) hideSplash(); });
  const info = await ready;
  part("engine", 1); part("excel", 1);
  S.engineReady = true;
  S.version = info.version;
  chip.className = "engine-chip ready";
  chip.querySelector("span").textContent = "Ready · offline";
  chip.title = `Engine ready in ${(info.ms / 1000).toFixed(1)} s. Everything now works without internet.`;
  $("#foot-version").textContent = "Version " + info.version;
  const saved = LS.get("rdps.settings", null);
  try {
    const out = await engine.call("init", saved ? JSON.stringify(saved) : "");
    S.settings = out.settings;
  } catch (e) {
    toast("Saved settings could not be used, so the defaults are loaded. (" + e.message + ")", "warn", 8000);
    LS.del("rdps.settings");
    const out = await engine.call("init", "");
    S.settings = out.settings;
  }
  const rem = LS.get("rdps.remembered", null);
  if (rem) await engine.call("load_remembered", JSON.stringify(rem));
  try { await teachersPage.syncTeachers(); } catch { /* teachers are optional */ }
  render();
  // Smart Ask: the small on-device understanding model. Loads from the browser's own copy in a few seconds; the first
  // time it downloads once (~120 MB) in the background while the site is already usable.
  if (prefs.aiUnderstanding) {
    const note = () => part("ask", ai.status.embed === "ready" ? 1 : (ai.status.embedPct || 0) / 100);
    ai.onStatus(note);
    ask.ensureAI().then(note).catch(() => part("ask", 1));
  } else {
    part("ask", 1);
  }
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}
boot();

// handy for checking things from the browser console (no data leaves the page)
window.__rdps = { engine, S };

export { engine };
