// Ask: questions in plain English / Hinglish, typed or spoken. Answers come only from the checked marks.
import * as engine from "../engine.js";
import { S, prefs, savePrefs } from "../state.js";
import { $, $$, esc, toast, chart, table, cssVar } from "../ui.js";
import * as ai from "../ai.js";
import { qmark } from "../explain.js";

const rerender = () => window.__render();
let recorder = null;
let unsub = null;

export function html() {
  const ready = S.engineReady && S.summary;
  const sugg = (S.summary && S.summary.suggestions) || [];
  const aiState = ai.status;
  const aiTxt = !prefs.aiUnderstanding ? "Smart understanding is off (Settings)" :
    aiState.embed === "ready" ? "✨ Smart understanding on (on-device AI)" :
    aiState.embed === "loading" ? `✨ Loading smart understanding… ${aiState.embedPct || 0}% (one time)` :
    aiState.embed === "error" ? "Smart understanding could not load - keyword understanding is used" : "Keyword understanding";
  return `<div class="page-head"><div><h1>Ask about the marks ${qmark("ask")}</h1>
      <p>Type or speak a question in your own words - English or Hinglish. Every number comes from the checked marks, and each answer says how it was worked out.</p></div>
      <span class="badge b-info" id="ai-state">${esc(aiTxt)}</span></div>
    ${!ready ? `<div class="card empty"><svg viewBox="0 0 24 24"><path d="M4 5h16v11H8l-4 4V5z"/></svg>
        <h3>Upload marks first</h3><p>Go to <a href="#/school">School results</a>, add files (or the sample data) and make the results.</p>
        ${S.board ? `<p>Board results are loaded - you can ask board questions like “board toppers”.</p>` : ""}</div>` : ""}
    <div class="chat ${ready || S.board ? "" : "hidden"}">
      <div class="chat-log" id="log">${S.chat.length ? S.chat.map(msgHtml).join("") : welcome(sugg)}</div>
      <div>
        <div class="chips" style="margin-bottom:10px">${sugg.slice(0, 6).map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
        <div class="chat-input">
          <button class="mic" id="mic" title="Ask by voice" aria-label="Ask by voice"><svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>
          <span class="wave hidden" id="wave">${"<i></i>".repeat(14)}</span>
          <input type="text" id="ask-input" placeholder="e.g. Who is weak in Maths but strong in Science in class 9?" autocomplete="off">
          <div class="seg" title="Language you will speak in"><button class="${prefs.voiceLang === "en" ? "on" : ""}" data-lang="en">EN</button><button class="${prefs.voiceLang === "hi" ? "on" : ""}" data-lang="hi">हिं</button></div>
          <button class="btn btn-primary" id="ask-go">Ask</button>
        </div>
      </div>
    </div>`;
}

function welcome(sugg) {
  return `<div class="msg bot"><b>Hi! Ask me about the uploaded marks.</b><p class="muted small" style="margin:6px 0 0">For example: “${esc(sugg[0] || "Top 5 in Class XI")}”, “Result of class 6”, “Section toppers of class 12”, “Who failed in more than one subject?”, “How are the Physics teachers doing?”, “Physics mein kaun kamzor hai?”.
    If I'm not sure, I'll ask you instead of guessing.</p></div>`;
}

function msgHtml(m, idx) {
  if (m.me) return `<div class="msg me">${esc(m.text)}</div>`;
  if (m.typing) return `<div class="msg bot"><span class="typing"><span></span><span></span><span></span></span></div>`;
  const a = m.ans;
  if (a.clarify) return `<div class="msg bot"><b>${esc(a.question)}</b><div class="chips" style="margin-top:8px">${a.options.map((o, k) =>
    `<button class="chip" data-clar="${idx}|${k}">${esc(o.label)}</button>`).join("")}</div></div>`;
  if (a.unknown || a.error) return `<div class="msg bot">🤔 ${esc(a.message || a.error)}${a.suggestions ? `<div class="chips" style="margin-top:8px">${a.suggestions.map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}</div>`;
  return `<div class="msg bot">
    ${a.understood ? `<div class="understood">${esc(a.understood)}${a.matched_by && a.matched_by.startsWith("AI") ? " · ✨ " + esc(a.matched_by) : ""}</div>` : ""}
    <div style="font-weight:600">${esc(a.text)}</div>
    ${a.remarks && a.remarks.length ? `<ul class="small" style="margin:8px 0 0">${a.remarks.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    ${a.chart && a.chart.labels && a.chart.labels.length > 1 ? `<div class="chart-box" style="height:${Math.min(320, 70 + a.chart.labels.length * 22)}px;margin-top:10px"><canvas data-chart="${idx}"></canvas></div>` : ""}
    ${a.table && a.table.rows.length ? `<div style="margin-top:10px">${table(a.table.columns, a.table.rows, { numeric: numericCols(a.table), wrap: wrapCols(a.table), max: 60 })}</div>` : ""}
    <div class="how">How: ${esc(a.how || "")}</div>
    ${a.table && a.table.rows.length && S.summary ? `<div class="row" style="margin-top:8px"><button class="btn btn-ghost btn-sm" data-save="${idx}">Save as a sheet in the workbook</button></div>` : ""}
  </div>`;
}

function numericCols(t) { return t.columns.map((c, i) => (t.rows.length && typeof t.rows[0][i] === "number" ? i : -1)).filter((i) => i >= 0); }
function wrapCols(t) { return t.columns.map((c, i) => (/why|reason|details/i.test(c) ? i : -1)).filter((i) => i >= 0); }

async function send(text, force) {
  if (!text) return;
  S.chat.push({ me: true, text });
  S.chat.push({ typing: true });
  draw();
  let hints = null;
  try { if (prefs.aiUnderstanding) hints = await ai.intentHints(text); } catch { /* keyword understanding still works */ }
  let ans;
  try {
    ans = await engine.call("ask", text, hints ? JSON.stringify(hints) : "", force ? JSON.stringify(force) : "");
  } catch (e) { ans = { error: e.message }; }
  S.chat.pop();
  S.chat.push({ ans, q: text });
  draw();
}

function draw() {
  const log = $("#log");
  if (!log) return;
  log.innerHTML = S.chat.map(msgHtml).join("");
  S.chat.forEach((m, i) => {
    if (m.ans && m.ans.chart && m.ans.chart.labels && m.ans.chart.labels.length > 1) {
      const c = m.ans.chart;
      const horizontal = c.labels.length > 6;
      chart($(`[data-chart="${i}"]`), "bar", c.labels, [{ label: c.label, data: c.values, backgroundColor: cssVar("--blue"), borderRadius: 5 }],
        { indexAxis: horizontal ? "y" : "x", ...(horizontal ? { y: { grid: { display: false } } } : {}) });
    }
  });
  log.scrollTop = log.scrollHeight;
}

export async function ensureAI() {
  if (!prefs.aiUnderstanding || ai.status.embed !== "off") return;
  try {
    const ex = await engine.call("intent_examples");
    const hd = await engine.call("header_labels");
    ai.loadEmbedder(ex, hd).catch(() => {});
  } catch { /* ignore */ }
}

export function mount(root) {
  if (unsub) unsub();
  unsub = ai.onStatus(() => {
    const el = $("#ai-state");
    if (!el) return;
    const st = ai.status;
    el.textContent = st.embed === "ready" ? "✨ Smart understanding on (on-device AI)" :
      st.embed === "loading" ? `✨ Loading smart understanding… ${st.embedPct || 0}% (one time)` :
      st.embed === "error" ? "Keyword understanding (AI model could not load)" : el.textContent;
    const mic = $("#mic");
    if (mic && st.speech === "loading") mic.title = `Loading voice model… ${st.speechPct || 0}%`;
  });
  if (!S.engineReady) return;
  ensureAI();
  draw();
  const input = $("#ask-input");
  if (!input) return;
  input.focus();
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) { const v = input.value.trim(); input.value = ""; send(v); } });
  root.addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    const d = t.dataset;
    if (t.id === "ask-go" && input.value.trim()) { const v = input.value.trim(); input.value = ""; return send(v); }
    if (d.q) return send(d.q);
    if (d.clar) {
      const [i, k] = d.clar.split("|").map(Number);
      const m = S.chat[i];
      const o = m.ans.options[k];
      return send(o.text, o.force || null);
    }
    if (d.lang) { prefs.voiceLang = d.lang; savePrefs(); $$("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === d.lang)); return; }
    if (d.save !== undefined) return saveSheet(+d.save, t);
    if (t.id === "mic") return toggleMic(t);
  });
}

async function saveSheet(i, btn) {
  const m = S.chat[i];
  const q = m.q;
  try {
    const r = await engine.call("command", "add a sheet with " + q);
    if (r.error) return toast(esc(r.error), "warn");
    const out = await engine.call("apply_command", JSON.stringify(r.item));
    if (S.summary) S.summary.recipe = out.recipe;
    btn.disabled = true; btn.textContent = "Saved ✓ (in the next Excel download)";
    toast(`Sheet “${esc(r.item.sheet)}” will be in the workbook.`, "ok");
  } catch (e) { toast(esc(e.message), "err"); }
}

async function toggleMic(btn) {
  const wave = $("#wave");
  if (recorder) {
    const r = recorder; recorder = null;
    btn.classList.remove("rec"); wave.classList.add("hidden");
    const input = $("#ask-input");
    input.placeholder = "Listening done - turning speech into text on this computer…";
    try {
      const audio = await r.stop();
      if (audio.length < 16000 * 0.4) { input.placeholder = "That was too short - try again."; return; }
      const text = await ai.transcribe(audio, prefs.voiceLang);
      input.value = text;
      input.placeholder = "Check the text, then press Enter";
      input.focus();
      if (!text) toast("I couldn't hear any words - please try again.", "warn");
    } catch (e) { toast("Voice could not be used: " + esc(e.message), "err", 8000); input.placeholder = "Type your question"; }
    return;
  }
  try {
    if (ai.status.speech === "off") { toast("Loading the voice model once (about 75 MB). After that voice works offline.", "info", 6000); ai.loadSpeech().catch((e) => toast("Voice model could not load: " + esc(e.message), "err", 8000)); }
    recorder = new ai.Recorder((lv, data) => {
      const bars = wave.children;
      for (let i = 0; i < bars.length; i++) bars[i].style.height = 4 + Math.min(22, (data[i * 3] || 0) / 255 * 26) + "px";
    });
    await recorder.start();
    btn.classList.add("rec"); wave.classList.remove("hidden");
    setTimeout(() => { if (recorder && btn.classList.contains("rec")) toggleMic(btn); }, 15000);
  } catch (e) {
    recorder = null;
    toast("Microphone not available: " + esc(e.message), "err", 7000);
  }
}
