// Small UI helpers shared by every page: escaping, toasts, modals, charts,
// count-up numbers, click ripples, downloads.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function fmt(v, places = 1) {
  if (v === null || v === undefined || v === "" || Number.isNaN(v)) return "–";
  if (typeof v !== "number") return esc(v);
  return v.toLocaleString("en-IN", { minimumFractionDigits: places, maximumFractionDigits: places });
}
// ---------------------------------------------------------------- differences in plain words
// Teachers found "-5", "+3", "-0.4" confusing: a difference is written "▼ 5 marks lower", "▲ 3% higher" or
// "≈ about the same" (under 1 either way - too small to mean anything).
const size = (a) => { const r = Math.round(a * 10) / 10; return r >= 3 ? String(Math.round(r)) : fmt(r); };   // 5, 12, 1.6
const howMuch = (a, unit) => `${size(a)}${unit === "%" ? "%" : " " + unit}`;
export function gapText(v, { unit = "marks", higher = "higher", lower = "lower", than = "", arrow = false } = {}) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  const mark = !arrow ? "" : a < 1 ? "≈ " : v > 0 ? "▲ " : "▼ ";
  if (a < 1) return mark + "about the same" + (than ? " as " + than : "");
  return `${mark}${howMuch(a, unit)} ${v > 0 ? higher : lower}${than ? " than " + than : ""}`;
}
export function gapWords(v, opts = {}) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  return `<span class="gap ${a < 1 ? "same" : v > 0 ? "up" : "down"}">${esc(gapText(v, { ...opts, arrow: true }))}</span>`;
}
/** A likely range in words: "likely 1 to 6 marks higher", "likely between 2 lower and 6 higher". */
export function rangeText(lo, hi, unit = "marks") {
  if (lo === null || lo === undefined || hi === null || hi === undefined) return "";
  const n = size;
  const u = unit === "%" ? "%" : " " + unit;
  if (lo >= 0) return `likely ${n(lo)} to ${n(hi)}${u} higher`;
  if (hi <= 0) return `likely ${n(-hi)} to ${n(-lo)}${u} lower`;
  return `likely between ${n(-lo)}${u} lower and ${n(hi)}${u} higher`;
}

export function fmtMark(v) {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  return esc(v);
}

// ---------------------------------------------------------------- toasts
export function toast(text, kind = "info", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = text;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, ms);
}

// ---------------------------------------------------------------- modal
export function modal(html, { onClose } = {}) {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { bg.remove(); onClose && onClose(); document.removeEventListener("keydown", key); };
  const key = (e) => { if (e.key === "Escape") close(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", key);
  $("#modal-root").appendChild(bg);
  return { el: bg, close };
}

// ---------------------------------------------------------------- charts (Chart.js, themed)
const charts = new Map();
export function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

export function chart(canvas, type, labels, datasets, opts = {}) {
  if (!canvas || !window.Chart) return null;
  const old = charts.get(canvas);
  if (old) old.destroy();
  const C = window.Chart;
  const text = cssVar("--muted"), grid = cssVar("--line"), navy = cssVar("--navy");
  C.defaults.font.family = "Inter, Mukta, system-ui, sans-serif";
  C.defaults.color = text;
  const isRound = type === "doughnut" || type === "pie";
  const cfg = {
    type,
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 900, easing: "easeOutQuart" },
      plugins: {
        legend: { display: isRound || datasets.length > 1, position: isRound ? "right" : "bottom",
                  labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true, color: text } },
        tooltip: { backgroundColor: navy === "#0B3C5D" ? "#0B3C5D" : "#163E5C", padding: 10, cornerRadius: 8,
                   titleFont: { weight: "600" }, callbacks: opts.tooltip || {} },
      },
      scales: isRound || type === "radar" ? undefined : {
        x: { grid: { display: false }, ticks: { color: text, font: { size: 11 } }, ...(opts.x || {}) },
        y: { grid: { color: grid }, border: { display: false }, ticks: { color: text, font: { size: 11 } }, beginAtZero: true, ...(opts.y || {}) },
      },
      indexAxis: opts.indexAxis || "x",
      onClick: opts.onClick,
      ...(opts.extra || {}),
    },
  };
  if (type === "radar") {
    cfg.options.scales = { r: { min: 0, max: 100, ticks: { display: false, stepSize: 20 }, grid: { color: grid }, angleLines: { color: grid },
                                pointLabels: { color: text, font: { size: 11 } } } };
  }
  const c = new C(canvas, cfg);
  charts.set(canvas, c);
  return c;
}
export function destroyCharts() { charts.forEach((c) => c.destroy()); charts.clear(); }

export const PALETTE = () => [cssVar("--blue"), "#0B3C5D", "#7FD0F2", "#3E7CA6", "#9DB4C7", "#F2A93B", "#5B6B79"];
export const LABEL_COLORS = () => ({ "Strong": cssVar("--green"), "On track": "#7FD0F2", "Weak": "#F2A93B", "Needs attention": cssVar("--red") });

// ---------------------------------------------------------------- numbers that count up
export function countUp(root = document) {
  $$("[data-count]", root).forEach((el) => {
    const end = parseFloat(el.dataset.count);
    const places = parseInt(el.dataset.places || "0", 10);
    if (Number.isNaN(end)) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(end, places); return; }
    const t0 = performance.now(), dur = 900;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(k === 1 ? end : end * e, places);   // always lands on the exact value
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// ---------------------------------------------------------------- ripple on every button
document.addEventListener("pointerdown", (e) => {
  const b = e.target.closest(".btn");
  if (!b || b.disabled) return;
  const r = b.getBoundingClientRect();
  const d = Math.max(r.width, r.height);
  const s = document.createElement("span");
  s.className = "ripple";
  s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
  b.appendChild(s);
  setTimeout(() => s.remove(), 600);
});

// ---------------------------------------------------------------- downloads
export function download(bytes, name, type) {
  const blob = new Blob([bytes], { type: type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
export const XLSM = "application/vnd.ms-excel.sheet.macroEnabled.12";

export function successTick() {
  return `<svg class="success" viewBox="0 0 52 52"><circle cx="26" cy="26" r="24"/><path d="M15 27l7 7 15-16" fill="none"/></svg>`;
}

export function labelBadge(label) {
  const cls = { "Strong": "b-strong", "Weak": "b-weak", "Needs attention": "b-att", "On track": "b-track",
                "Doing well": "b-strong", "Focus area": "b-weak", "Needs support": "b-att" }[label] || "b-leave";
  return `<span class="badge ${cls}">${esc(label || "–")}</span>`;
}

export function sevBadge(s) {
  return `<span class="badge ${{ error: "b-err", warning: "b-warn", info: "b-info" }[s] || "b-info"}">${esc({ error: "Error", warning: "Check", info: "Note" }[s] || s)}</span>`;
}

export function pctCell(v) {
  if (v === null || v === undefined) return "–";
  const w = Math.max(0, Math.min(100, v));
  return `<div class="pct-cell"><b>${fmt(v)}</b><span class="pct-bar"><i style="width:${w}%"></i></span></div>`;
}

export function table(columns, rows, { numeric = [], wrap = [], max = 400 } = {}) {
  const head = columns.map((c, i) => `<th class="${numeric.includes(i) ? "num" : ""}">${esc(c)}</th>`).join("");
  const body = rows.slice(0, max).map((r) => "<tr>" + r.map((v, i) => {
    const cls = [numeric.includes(i) ? "num" : "", wrap.includes(i) ? "wrap" : ""].join(" ");
    const val = typeof v === "number" ? fmt(v, Number.isInteger(v) ? 0 : 2) : (v && typeof v === "object" && "html" in v ? v.html : esc(v));
    return `<td class="${cls}">${val}</td>`;
  }).join("") + "</tr>").join("");
  const more = rows.length > max ? `<div class="t-scroll-note">Showing ${max} of ${rows.length} rows - the Excel file has all of them.</div>` : "";
  return `<div class="table-wrap"><table class="t"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`;
}
