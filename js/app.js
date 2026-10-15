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
const minSplash = new Promise((r) => setTimeout(r, 1700));
engine.on("progress", (m) => {
  const bar = $("#splash-progress"), note = $("#splash-note");   // the splash may already be gone
  if (bar) bar.style.width = m.value + "%";
  if (note) note.textContent = m.text;
  chip.querySelector("span").textContent = m.value < 100 ? `Loading ${m.value}%` : "Ready";
});
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
  // the splash hides after a short moment; the engine keeps loading in the background
  Promise.race([Promise.all([ready, minSplash]), new Promise((r) => setTimeout(r, 4500))]).then(() => {
    splash.classList.add("gone");
    setTimeout(() => splash.remove(), 800);       // fully gone even if the fade-out was skipped
  });
  const info = await ready;
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
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}
boot();

// handy for checking things from the browser console (no data leaves the page)
window.__rdps = { engine, S };

export { engine };
