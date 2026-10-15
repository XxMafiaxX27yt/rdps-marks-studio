// School results: 1 Upload -> 2 Check -> 3 Review -> 4 Download
import * as engine from "../engine.js";
import { S, LS, prefs, savePrefs } from "../state.js";
import { $, $$, esc, fmt, fmtMark, toast, modal, chart, countUp, download, XLSX, XLSM, successTick, labelBadge,
         sevBadge, pctCell, table, PALETTE, LABEL_COLORS, cssVar } from "../ui.js";
import { readPdf, readImage } from "../files.js";
import * as ai from "../ai.js";
import { printCards } from "../report.js";
import { qmark } from "../explain.js";

const rerender = () => window.__render();
const STEPS = ["Upload", "Check", "Review", "Download"];
const ROLES = [["ignore", "Not used"], ["name", "Student name"], ["roll", "Roll no"], ["adm_no", "Admission no"],
  ["board_roll", "Board roll no"], ["father", "Father's name"], ["mother", "Mother's name"], ["class", "Class"],
  ["section", "Section"], ["class_section", "Class + section"], ["group", "Group / stream"], ["gender", "Gender"],
  ["choice", "Subject choice"], ["mark", "Marks"], ["file_total", "Total (to double-check)"], ["sno", "Serial no"],
  ["row_subject", "Subject name (per row)"], ["row_exam", "Exam name (per row)"]];
let busy = null;      // text while working
const PARTS = [["theory", "Theory / written"], ["practical", "Practical / internal (total)"], ["total", "Total (out of 100)"],
  ["pt5", "Internal: PT part"], ["portfolio", "Internal: portfolio"], ["project", "Internal: project"], ["notebook", "Notebook"],
  ["viva", "Practical: viva"], ["file", "Practical: file"], ["ptest", "Practical: test"]];

export function html() {
  if (!S.engineReady) return loadingHtml();
  return `
  <div class="page-head">
    <div><h1>School results</h1>
      <p>Upload the marks, check what the tool understood, review the results and download the Excel report. Everything stays on this computer.</p></div>
  </div>
  ${stepper()}
  <div id="step-body">${[upload, check, review, downloads][S.step - 1]()}</div>`;
}

function loadingHtml() {
  return `<div class="page-head"><div><h1>School results</h1><p>Getting the engine ready - this takes a few seconds the first time, then it is instant and works offline.</p></div></div>
  <div class="grid g3">${[1, 2, 3].map(() => `<div class="card"><div class="skeleton" style="height:18px;width:60%"></div><div class="skeleton" style="height:110px;margin-top:14px"></div></div>`).join("")}</div>`;
}

function stepper() {
  const has = (S.files && (S.files.files.length || S.files.restored)) || S.summary;
  return `<div class="stepper">${STEPS.map((s, i) => {
    const n = i + 1;
    const done = n < S.step;
    const can = n === 1 || (n === 2 && has) || (n >= 3 && S.summary);
    return `<div class="step ${done ? "done" : ""} ${n === S.step ? "now" : ""} ${can ? "clickable" : ""}" data-step="${can ? n : ""}">
      <span class="dot">${done ? "✓" : n}</span><span class="lbl">${s}</span></div>`;
  }).join("")}</div>`;
}

// ================================================================== 1. upload
function upload() {
  const f = S.files || { files: [], gazettes: [] };
  const list = f.files.map((x) => `
    <div class="file-row"><span class="ficon">${esc(ext(x.name))}</span>
      <div style="flex:1;min-width:0"><div class="fname">${esc(x.name)}</div>
      <div class="tiny muted">${x.sheets.length} sheet${x.sheets.length !== 1 ? "s" : ""}${x.kind === "scan" ? " · read from a scan - please check carefully" : ""}</div></div>
      <button class="btn btn-ghost btn-sm" data-remove="${x.id}">Remove</button></div>`).join("");
  const gz = f.gazettes.map((g) => `
    <div class="file-row"><span class="ficon">CBSE</span>
      <div style="flex:1;min-width:0"><div class="fname">${esc(g.name)}</div>
      <div class="tiny muted">Board gazette ${esc(g.year)} · ${g.students} students → shown under <a href="#/board">Board results</a></div></div>
      <button class="btn btn-ghost btn-sm" data-remove="${g.id}">Remove</button></div>`).join("");
  return `
  <div class="grid g3">
    <div class="span2 stack">
      <label class="drop" id="drop">
        <input type="file" id="file-in" multiple accept=".xlsx,.xlsm,.xls,.csv,.txt,.tsv,.pdf,.png,.jpg,.jpeg,.webp">
        <div class="drop-icon"><svg viewBox="0 0 24 24"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg></div>
        <h3>Drop marks files here ${qmark("upload")}</h3>
        <div class="muted">or click to choose · you can add several files (one per exam, one per class…)</div>
        <div class="formats"><span>EXCEL</span><span>XLS</span><span>CSV</span><span>CBSE TXT</span><span>PDF</span><span>SCAN / PHOTO</span></div>
      </label>
      ${busy ? `<div class="card"><div class="row"><span class="spinner" style="color:var(--blue)"></span><b>${esc(busy)}</b></div><div class="progress" style="margin-top:10px"><i id="busy-bar" style="width:5%"></i></div></div>` : ""}
      ${list || gz ? `<div class="stack">${list}${gz}</div>` : ""}
      ${f.files.length ? `<div class="row between"><span class="muted small">Next: check that every column was understood.</span>
          <button class="btn btn-primary btn-lg" data-go="2">Check the columns →</button></div>` : ""}
    </div>
    <div class="stack">
      <div class="card lift">
        <h3>Try it now</h3>
        <p class="muted small">Made-up students (no real names) in the school's template: Classes VI, IX, X, XI and XII, every exam, with internal marks in VI and IX and marks only in X.</p>
        <div class="row"><button class="btn btn-soft" id="sample">Sample data</button><button class="btn btn-ghost" id="sample-bad">Sample with mistakes</button></div>
      </div>
      <div class="card lift">
        <h3>Continue an earlier workbook</h3>
        <p class="muted small">Open an Excel file made by this tool - marks you corrected in Excel are picked up.</p>
        <label class="btn btn-ghost"><input type="file" id="wb-in" accept=".xlsx,.xlsm" hidden>Open workbook…</label>
      </div>
      <div class="card lift">
        <h3>Need a clean format?</h3>
        <p class="muted small">The ready-made template only accepts valid marks while typing.</p>
        <a class="btn btn-ghost" href="#/template">Get the template</a>
      </div>
      ${f.files.length >= 2 ? `<div class="card lift"><h3>Typed twice?</h3><p class="muted small">If two people typed the same marks, compare their files cell by cell.</p>
        <button class="btn btn-ghost" id="compare">Compare two files</button></div>` : ""}
    </div>
  </div>`;
}

function ext(n) { return (n.split(".").pop() || "").slice(0, 4).toUpperCase(); }

async function refreshState() { S.files = await engine.call("state"); }

async function addFiles(fileList) {
  const files = [...fileList];
  let i = 0;
  for (const file of files) {
    i++;
    busy = `Reading ${file.name} (${i} of ${files.length})…`;
    rerender();
    const bar = (p) => { const b = $("#busy-bar"); if (b) b.style.width = Math.round(5 + p * 95) + "%"; };
    try {
      const low = file.name.toLowerCase();
      let info;
      if (low.endsWith(".pdf")) {
        const pages = await readPdf(file, bar);
        info = await engine.call("add_pages", file.name, JSON.stringify(pages));
        if (pages.some((p) => p.ocr)) toast(`${esc(file.name)} was read from a scan. Please check every column and a few marks carefully.`, "warn", 7000);
      } else if (/\.(png|jpe?g|webp)$/.test(low)) {
        const pages = await readImage(file, bar);
        info = await engine.call("add_pages", file.name, JSON.stringify(pages));
        toast("Photo read with offline text recognition. Printed sheets work best - please check carefully.", "warn", 7000);
      } else {
        const data = new Uint8Array(await file.arrayBuffer());
        info = await engine.call("add_file", file.name, data);
        if (info.kind === "our_workbook") {
          busy = null;
          const ok = await confirmModal("This is a workbook made by RDPS Marks Studio",
            "Open it to continue where you left off? Marks corrected in Excel will be picked up. (Files added so far will be cleared.)", "Open it");
          if (ok) await openWorkbook(file);
          continue;
        }
      }
      if (info.kind === "gazette") toast(`CBSE gazette found (${info.students} students, ${info.year}). See <a href="#/board">Board results</a>.`, "ok", 6000);
      else toast(`Added ${esc(file.name)}`, "ok", 2200);
    } catch (e) {
      toast(`Could not read ${esc(file.name)}: ${esc(e.message)}`, "err", 9000);
    }
  }
  busy = null;
  await refreshState();
  S.summary = null;
  rerender();
}

async function openWorkbook(file) {
  busy = "Opening the workbook…";
  rerender();
  try {
    const data = new Uint8Array(await file.arrayBuffer());
    const sum = await engine.call("load_workbook", file.name, data);
    S.summary = sum;
    await refreshState();
    pickView();
    S.step = 3;
    toast(sum.changes_in_excel ? `Opened. ${sum.changes_in_excel} mark(s) changed in Excel were picked up (see Problems/Notes).` : "Opened - nothing was changed in Excel.", "ok", 6000);
  } catch (e) {
    toast("Could not open that workbook: " + esc(e.message), "err", 8000);
  }
  busy = null;
  rerender();
}

function confirmModal(title, text, yes = "Yes") {
  return new Promise((res) => {
    const m = modal(`<h2>${esc(title)}</h2><p class="muted">${esc(text)}</p><div class="row" style="justify-content:flex-end">
      <button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" id="m-yes">${esc(yes)}</button></div>`,
      { onClose: () => res(false) });
    $("#m-yes", m.el).addEventListener("click", () => { res(true); m.el.remove(); });
  });
}

// ================================================================== 2. check
function check() {
  const st = S.files;
  if (!st) return "";
  if (st.restored) return `<div class="card"><h3>Workbook opened</h3><p class="muted">The columns were already checked when this workbook was made.</p>
    <button class="btn btn-primary" data-go="3">Review the results →</button></div>`;
  const settings = S.settings;
  const exams = Object.entries(settings.rules.exams).map(([k, v]) => [k, v.name]);
  const classes = Object.keys(settings.rules.classes);
  const subjects = settings.subjects.map((s) => [s.code, s.name]);
  const pend = st.pending;
  const pendHtml = pend.length ? `<div class="pending stack"><b>${pend.length} thing${pend.length > 1 ? "s" : ""} to confirm before results can be made:</b>
      <ul style="margin:6px 0 0;padding-left:18px">${pend.slice(0, 12).map((p) => `<li class="small">${esc(p.text)}</li>`).join("")}</ul>
      ${pend.length > 12 ? `<div class="small">…and ${pend.length - 12} more below (amber boxes).</div>` : ""}</div>` :
    `<div class="note"><b>Everything is mapped.</b> Have a quick look, then make the results.</div>`;
  const cards = [];
  for (const f of st.files) {
    for (const sh of f.sheets) {
      cards.push(sheetCard(f, sh, exams, classes, subjects));
    }
  }
  const issues = S.summary ? issuesPanel() : "";
  return `<div class="stack">${pendHtml}
    ${S.summary ? issues : ""}
    <div class="card"><div class="card-head"><h3>What each column means ${qmark("check")}</h3>
      <span class="muted small">Amber = please confirm. Your choices are remembered for files with the same layout.</span></div>
      ${cards.join("")}</div>
    <div class="row between">
      <button class="btn btn-ghost" data-go="1">← Back</button>
      <div class="row">${S.summary ? `<button class="btn btn-ghost" id="analyze">Re-check</button><button class="btn btn-primary btn-lg" data-go="3">Review results →</button>`
        : `<button class="btn btn-primary btn-lg" id="analyze" ${pend.length ? "disabled" : ""}>Make results ✓</button>`}</div>
    </div></div>`;
}

function opt(list, val, blank) {
  return (blank !== undefined ? `<option value="">${esc(blank)}</option>` : "") +
    list.map(([k, v]) => `<option value="${esc(k)}" ${k === val ? "selected" : ""}>${esc(v)}</option>`).join("");
}

function sheetCard(f, sh, exams, classes, subjects) {
  const kind = sh.skip ? `<span class="badge b-leave">Not used</span>` :
    sh.kind === "roster" ? `<span class="badge b-info">Student list</span>` : `<span class="badge b-ok">Marks</span>`;
  const head = `<div class="sheet-head"><div><div class="t">${esc(f.name)} › ${esc(sh.name)}</div>
      <div class="tiny muted">${sh.rows} rows · data from row ${sh.data_start}${sh.title ? " · “" + esc(sh.title.slice(0, 70)) + "”" : ""}${sh.remembered ? " · remembered layout ✓" : ""}</div></div>
    <div class="row">${kind}
      ${sh.kind !== "info" ? `<label class="toggle small"><input type="checkbox" data-skip="${f.id}|${esc(sh.name)}" ${sh.skip ? "" : "checked"}><i></i>Use</label>` : ""}
    </div></div>`;
  if (sh.skip || sh.kind === "info") return `<div class="sheet-card">${head}${sh.note ? `<div class="sheet-body small muted">${esc(sh.note)}</div>` : ""}</div>`;
  const key = `${f.id}|${sh.name}`;
  const sheetSel = `<div class="row" style="margin-bottom:12px">
    ${sh.kind !== "roster" ? `<label class="field" style="width:200px"><span>Exam ${sh.needs_exam ? "⚠" : ""}</span>
      <select class="sel-sm" data-sheet="${esc(key)}" data-k="exam">${opt(exams, sh.exam, "— from the columns —")}</select>
      ${sh.exam_from ? `<span class="tiny muted">found in ${esc(sh.exam_from)}</span>` : ""}</label>` : ""}
    <label class="field" style="width:150px"><span>Class ${sh.needs_class ? "⚠" : ""}</span>
      <select class="sel-sm" data-sheet="${esc(key)}" data-k="cls">${opt(classes.map((c) => [c, c]), sh.cls, "— from a column —")}</select>
      ${sh.cls_from ? `<span class="tiny muted">found in ${esc(sh.cls_from)}</span>` : ""}</label>
    <label class="field" style="width:120px"><span>Section</span>
      <input class="sel-sm" type="text" maxlength="3" value="${esc(sh.section || "")}" data-sheet="${esc(key)}" data-k="section" placeholder="column"></label>
    <div style="flex:1"></div>
    <button class="btn btn-soft btn-sm" data-confirm="${esc(key)}">Looks right ✓</button></div>`;
  const cols = sh.columns.filter((c) => !(c.role === "ignore" && !c.header && !(c.sample || []).length));
  const grid = cols.map((c) => colBox(key, c, exams, subjects)).join("");
  return `<div class="sheet-card">${head}<div class="sheet-body">${sheetSel}<div class="map-grid">${grid}</div>
    <details style="margin-top:10px"><summary class="small muted" style="cursor:pointer">Show the first rows of this sheet</summary>${previewGrid(sh)}</details></div></div>`;
}

function colBox(key, c, exams, subjects) {
  const role = c.role === "unknown" ? "" : c.role;
  const markSel = c.role === "mark" ? `
    <select class="sel-sm" data-col="${esc(key)}|${c.col}" data-k="subject">${opt(subjects, c.subject, "Which subject?")}</select>
    <div class="row" style="gap:6px;margin-top:5px">
      <select class="sel-sm" style="flex:1" data-col="${esc(key)}|${c.col}" data-k="component">${opt(PARTS, c.component || "theory")}</select>
      <select class="sel-sm" style="flex:1" data-col="${esc(key)}|${c.col}" data-k="exam">${opt(exams, c.exam, "Sheet's exam")}</select></div>` : "";
  return `<div class="map-col ${c.sure ? "" : "unsure"} ${c.role === "ignore" ? "ign" : ""}" data-colbox="${esc(key)}|${c.col}">
    <div class="h" title="${esc(c.header)}">${esc(c.header || "(no heading)")}</div>
    <div class="sam" title="${esc((c.sample || []).join(" · "))}">${esc((c.sample || []).slice(0, 4).join(" · ")) || "&nbsp;"}</div>
    <select class="sel-sm" data-col="${esc(key)}|${c.col}" data-k="role">${opt(ROLES, role, role ? undefined : "What is this column?")}</select>
    ${markSel}
    ${!c.sure ? `<div class="why">${esc(c.why)}</div><div class="ai-sug" data-aisug="${esc(c.header)}"></div>` : ""}
  </div>`;
}

function previewGrid(sh) {
  const rows = sh.preview.map((r) => `<tr class="${r.header ? "hdr" : ""}"><td class="rn">${r.row}</td>${r.cells.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("");
  return `<div class="preview-grid"><table>${rows}</table></div>`;
}

// ---------------------------------------------------------------- problems
function issuesPanel() {
  const s = S.summary;
  const c = s.counts;
  const filt = S.issuesFilter;
  const list = s.issues.filter((i) => filt === "all" || i.severity === filt);
  const items = list.slice(0, 300).map((i, n) => {
    let fix = "";
    if (i.fix && i.fix.type === "cell") {
      fix = `<div class="fix"><input type="text" value="${esc(i.fix.current || "")}" data-fixval="${n}" aria-label="New value">
        <button class="btn btn-soft btn-sm" data-fixcell="${esc(i.fix.key)}" data-n="${n}">Correct</button></div>`;
    } else if (i.fix && i.fix.type === "swap") {
      fix = `<div class="fix"><button class="btn btn-soft btn-sm" data-swap="${esc(i.fix.source)}|${esc(i.fix.sheet)}|${i.fix.cols.join("|")}">Swap Theory ↔ Practical</button></div>`;
    } else if (i.fix && i.fix.type === "choose") {
      fix = `<div class="fix">${i.fix.options.map((o, k) => `<button class="btn btn-ghost btn-sm" data-choose="${encodeURIComponent(JSON.stringify(i.fix.options))}" data-k="${k}">Use ${esc(o.value)}</button>`).join("")}</div>`;
    } else if (i.fix && i.fix.type === "undo") {
      fix = `<div class="fix"><button class="btn btn-ghost btn-sm" data-undo="${esc(i.fix.key)}">Undo</button></div>`;
    }
    return `<div class="issue">${sevBadge(i.severity)}<div><div>${esc(i.message)}</div>${i.ref ? `<div class="where">${esc(i.ref.text)}</div>` : ""}</div>${fix}</div>`;
  }).join("");
  const v = s.verify;
  return `<div class="card"><div class="card-head"><h3>Checks</h3>
      <div class="seg">${[["error", `Errors ${c.error}`], ["warning", `Checks ${c.warning}`], ["info", `Notes ${c.info}`], ["all", "All"]].map(([k, l]) =>
        `<button class="${filt === k ? "on" : ""}" data-filter="${k}">${l}</button>`).join("")}</div></div>
    <div class="note" style="margin-bottom:10px">✔ <b>${s.students} students</b>, ${s.records} marks read, ${s.results} subject results.
      ${v && v.ok ? "Both independent calculations agree." : ""} ${c.error ? `<b>${c.error} error${c.error > 1 ? "s" : ""}</b>: those marks are left out until corrected (the original file is never changed).` : "No errors."}</div>
    <div style="max-height:420px;overflow:auto">${items || `<div class="empty">Nothing here.</div>`}</div></div>`;
}

async function analyze() {
  busy = "Working out the results…";
  const btn = $("#analyze");
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Working…`; }
  try {
    const out = await engine.call("analyze");
    if (out.blocked) {
      toast("Some columns still need confirming.", "warn");
      await refreshState();
    } else {
      S.summary = out;
      pickView();
      LS.set("rdps.remembered", await engine.call("remember_json"));
      if (out.counts.error) {
        S.issuesFilter = "error";
        toast(`Results made. ${out.counts.error} error(s) to look at - those marks are left out until fixed.`, "warn", 6000);
      } else {
        toast(`Results ready ✓ ${out.students} students. Both independent calculations agree.`, "ok");
        S.step = 3;
      }
    }
  } catch (e) {
    toast(esc(e.message), "err", 10000);
    console.error(e.detail || e);
  }
  busy = null;
  rerender();
}

function pickView() {
  const s = S.summary;
  if (!s || !s.classes.length) return;
  const c = s.classes.find((x) => x.cls === S.view.cls) || s.classes[0];
  S.view.cls = c.cls;
  if (!c.exams.find((e) => e.code === S.view.exam)) S.view.exam = c.exams.length ? c.exams[c.exams.length - 1].code : null;
  if (S.view.section !== "All" && !c.sections.includes(S.view.section)) S.view.section = "All";
}

// ================================================================== 3. review
function review() {
  const s = S.summary;
  if (!s) return "";
  const c = s.classes.find((x) => x.cls === S.view.cls);
  const tabs = [["overview", "Overview"], ["students", "Students"], ["subjects", "Subjects"], ["progress", "Progress"], ["card", "Report card"]];
  return `<div class="card" style="margin-bottom:18px"><div class="row between">
      <div class="row">
        ${s.classes.length > 4 ? `<select class="sel-sm" id="v-cls" style="width:auto;font-weight:600">${s.classes.map((x) => `<option value="${x.cls}" ${x.cls === S.view.cls ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select>`
          : `<div class="seg">${s.classes.map((x) => `<button class="${x.cls === S.view.cls ? "on" : ""}" data-cls="${x.cls}">${esc(x.label)}</button>`).join("")}</div>`}
        <select class="sel-sm" id="v-exam" style="width:auto">${c.exams.map((e) => `<option value="${e.code}" ${e.code === S.view.exam ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select>
        <select class="sel-sm" id="v-sec" style="width:auto"><option value="All">All sections</option>${c.sections.map((x) => `<option ${x === S.view.section ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        ${(c.combos || []).length > 1 && S.tab === "students" ? `<select class="sel-sm" id="v-combo" style="width:auto"><option value="">All streams</option>${c.combos.map((x) => `<option ${x === S.view.combo ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : ""}
      </div>
      <button class="btn btn-primary" data-go="4">Download →</button></div></div>
    <div class="tabs">${tabs.map(([k, l]) => `<button class="${S.tab === k ? "on" : ""}" data-tab="${k}">${l}</button>`).join("")}</div>
    <div id="tab-body"><div class="grid g5">${[1, 2, 3, 4, 5].map(() => `<div class="kpi"><div class="skeleton" style="height:34px"></div></div>`).join("")}</div></div>`;
}

async function loadTab() {
  const body = $("#tab-body");
  if (!body) return;
  const { cls, exam, section } = S.view;
  try {
    if (S.tab === "overview") {
      const d = await engine.call("dashboard", cls, exam, section);
      body.innerHTML = overviewHtml(d);
      countUp(body);
      chart($("#c-sub"), "bar", d.by_subject.map((x) => x.name), [{ data: d.by_subject.map((x) => x.avg), backgroundColor: cssVar("--blue"), borderRadius: 6, maxBarThickness: 38 }],
        { y: { max: 100 }, tooltip: { label: (ctx) => ` ${ctx.parsed.y?.toFixed(1)}% average` } });
      const lc = LABEL_COLORS();
      chart($("#c-lab"), "doughnut", d.labels.map((x) => x[0]), [{ data: d.labels.map((x) => x[1]), backgroundColor: d.labels.map((x) => lc[x[0]]), borderWidth: 2, borderColor: cssVar("--card") }],
        { extra: { cutout: "62%" } });
      chart($("#c-dist"), "bar", d.distribution.map((x) => x[0]), [{ data: d.distribution.map((x) => x[1]), backgroundColor: "#0B3C5D", borderRadius: 6 }],
        { tooltip: { label: (ctx) => ` ${ctx.parsed.y} students` } });
      chart($("#c-sec"), "bar", d.by_section.map((x) => "Section " + x[0]), [{ data: d.by_section.map((x) => x[1]), backgroundColor: PALETTE(), borderRadius: 6 }],
        { indexAxis: "y", x: { max: 100 }, y: { grid: { display: false } } });
    } else if (S.tab === "students") {
      const m = await engine.call("matrix", cls, exam, section, S.view.combo || "");
      body.innerHTML = studentsHtml(m);
      const search = $("#stu-search");
      search.addEventListener("input", () => {
        const q = search.value.toLowerCase();
        $$("#stu-table tbody tr").forEach((tr) => { tr.style.display = tr.dataset.n.includes(q) ? "" : "none"; });
      });
    } else if (S.tab === "subjects") {
      const d = await engine.call("subject_analysis", cls, exam);
      const c = S.summary.classes.find((x) => x.cls === cls);
      const subj = S.trendSubject && c.subjects.find((x) => x.code === S.trendSubject) ? S.trendSubject : (c.subjects[0] || {}).code;
      const tr = await engine.call("subject_trend", cls, subj);
      body.innerHTML = subjectsHtml(d, c, subj);
      const rows = d.rows.filter((r) => r.count);
      chart($("#c-savg"), "bar", rows.map((r) => r.name), [{ label: "Average %", data: rows.map((r) => r.avg), backgroundColor: cssVar("--blue"), borderRadius: 6 },
        { label: "Pass %", data: rows.map((r) => r.pass_pct), backgroundColor: "#0B3C5D", borderRadius: 6 }], { y: { max: 100 } });
      const pr = rows.filter((r) => d.practical.includes(r.subject) && r.avg_pr !== null && r.avg_pr !== undefined);
      if (pr.length) chart($("#c-thpr"), "bar", pr.map((r) => r.name), [{ label: "Theory (avg marks)", data: pr.map((r) => r.avg_th), backgroundColor: cssVar("--blue"), borderRadius: 4 },
        { label: "Practical (avg marks)", data: pr.map((r) => r.avg_pr), backgroundColor: "#0B3C5D", borderRadius: 4 }], { extra: { scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: cssVar("--line") } } } } });
      chart($("#c-trend"), "line", tr.map((x) => x.name), [{ label: "Average %", data: tr.map((x) => x.avg), borderColor: cssVar("--blue"), backgroundColor: cssVar("--blue"), tension: .3, pointRadius: 5 },
        { label: "Pass %", data: tr.map((x) => x.pass), borderColor: "#0B3C5D", backgroundColor: "#0B3C5D", tension: .3, pointRadius: 5 }], { y: { max: 100 } });
    } else if (S.tab === "progress") {
      const d = await engine.call("progress", cls);
      body.innerHTML = progressHtml(d);
    } else if (S.tab === "card") {
      await loadCard(body);
    }
  } catch (e) {
    body.innerHTML = `<div class="card"><b>Something went wrong:</b> ${esc(e.message)}</div>`;
  }
}

function overviewHtml(d) {
  const k = (v, l, places = 1, s = "") => `<div class="kpi"><div class="v" ${v !== null && v !== undefined ? `data-count="${v}" data-places="${places}"` : ""}>${v === null || v === undefined ? "–" : fmt(0, places)}</div><div class="l">${l}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  return `<div class="grid g5">
      ${k(d.students, "Students", 0)}${k(d.average, "Class average %")}${k(d.highest, "Highest %")}${k(d.pass_rate, "Pass rate % " + qmark("pass"), 1, `${d.passed} passed · ${d.not_passed} not`)}
      <div class="kpi"><div class="v" style="font-size:1.25rem;padding-top:8px">${esc(d.topper || "–")}</div><div class="l">Top scorer</div></div>
    </div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>Average % by subject ${qmark("dashboard")}</h3><div class="chart-box"><canvas id="c-sub"></canvas></div></div>
      <div class="card"><h3>How subjects are going ${qmark("labels")}</h3><div class="chart-box"><canvas id="c-lab"></canvas></div>
        <p class="tiny muted" style="margin:8px 0 0">Compared with each student's own average and the class average (rules in Settings).</p></div>
      <div class="card"><h3>Students in each overall % range ${qmark("percent")}</h3><div class="chart-box"><canvas id="c-dist"></canvas></div></div>
      <div class="card"><h3>Average overall % by section ${qmark("classes")}</h3><div class="chart-box"><canvas id="c-sec"></canvas></div></div>
    </div>`;
}

function studentsHtml(m) {
  const head = ["#", "Name", "Sec", ...m.subjects.map((s) => s.short), "Overall %", "Result", "Rank"];
  const titles = ["", "", "", ...m.subjects.map((s) => s.name), "", "", ""];
  const rows = m.rows.map((r, i) => {
    const cells = r.cells.map((c) => {
      if (!c) return `<td class="muted center">·</td>`;
      const tag = c.slot_subject ? ` <span class="slot-tag">${esc(c.slot_subject)}</span>` : "";
      if (c.pct === null || c.pct === undefined) return `<td class="center" title="${esc(c.reason)}"><span class="badge b-leave">${esc(c.status)}</span>${tag}</td>`;
      const col = { "Strong": "var(--green)", "Weak": "var(--amber)", "Needs attention": "var(--red)" }[c.label] || "inherit";
      return `<td class="num" title="${esc(c.reason)}" style="color:${col};font-weight:${col === "inherit" ? 400 : 700}">${fmt(c.pct)}${tag}</td>`;
    }).join("");
    return `<tr data-n="${esc(r.name.toLowerCase())}" data-sid="${r.sid}" style="cursor:pointer"><td class="muted">${esc(r.roll)}</td><td><b>${esc(r.name)}</b></td><td>${esc(r.section)}</td>${cells}
      <td>${pctCell(r.overall)}</td><td>${r.result === "Not passed" ? `<span class="badge b-att">Not passed</span>` : `<span class="badge b-ok">${esc(r.result || "–")}</span>`}</td><td class="num">${r.rank ?? "–"}</td></tr>`;
  }).join("");
  return `<div class="card"><div class="card-head"><h3>Students (${m.rows.length}) ${qmark("students")}</h3>
      <input type="search" id="stu-search" placeholder="Search a name…" style="max-width:260px"></div>
    <div class="table-wrap" style="max-height:620px"><table class="t" id="stu-table"><thead><tr>${head.map((h, i) => `<th title="${esc(titles[i])}">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="t-scroll-note">Subject columns show % (green = strong, amber = weak, red = needs attention). Hover for the reason. Click a student for the report card.</div></div>`;
}

function subjectsHtml(d, c, subj) {
  const rows = d.rows.filter((r) => r.count).map((r) => [r.name, r.count, { html: pctCell(r.avg) }, r.max, r.min, r.pass_pct, r.absent,
    r.avg_th, r.avg_pr ?? "–"]);
  return `<div class="grid g2">
    <div class="card span2"><h3>Subjects ${qmark("subjects")}</h3>${table(["Subject", "Students", "Average %", "Highest %", "Lowest %", "Pass %", "Absent", "Avg written", "Avg practical / internal"], rows, { numeric: [1, 3, 4, 5, 6, 7, 8] })}</div>
    <div class="card"><h3>Average and pass % by subject</h3><div class="chart-box"><canvas id="c-savg"></canvas></div></div>
    <div class="card"><h3>Theory + practical (average marks)</h3><div class="chart-box"><canvas id="c-thpr"></canvas></div></div>
    <div class="card span2"><div class="card-head"><h3>Across exams</h3>
      <select class="sel-sm" id="trend-sub" style="width:auto">${c.subjects.map((s) => `<option value="${s.code}" ${s.code === subj ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></div>
      <div class="chart-box"><canvas id="c-trend"></canvas></div></div></div>`;
}

function progressHtml(d) {
  const ex = d.exams;
  const head = ["Student", "Sec", ...ex.map((e) => e.name), "Latest change", "Watch"];
  const watch = d.rows.filter((r) => r.watch);
  const improved = d.rows.filter((r) => r.latest_change > 0).sort((a, b) => b.latest_change - a.latest_change).slice(0, 8);
  const rows = d.rows.map((r) => [r.name, r.section, ...r.series.map((s) => s[1]),
    { html: r.latest_change === null ? "–" : `<b style="color:${r.latest_change >= 0 ? "var(--green)" : "var(--red)"}">${r.latest_change >= 0 ? "▲" : "▼"} ${fmt(Math.abs(r.latest_change))}</b>` },
    { html: r.watch ? `<span class="badge b-att">${r.dropped_twice ? "Dropped twice" : "Not passed"}</span>` : "" }]);
  return `<div class="grid g2">
    <div class="card"><h3>📈 Most improved ${qmark("progress")}</h3>${improved.length ? `<ol>${improved.map((r) => `<li><b>${esc(r.name)}</b> (${esc(r.section)}) <span style="color:var(--green)">+${fmt(r.latest_change)}</span></li>`).join("")}</ol>` : `<p class="muted">Needs at least two exams.</p>`}</div>
    <div class="card"><h3>👀 Watch list (${watch.length})</h3><p class="tiny muted">Dropped ${S.settings.rules.drop_alert_gap}+ points in two exams in a row, or not passed in the latest exam.</p>
      ${watch.length ? `<ul>${watch.slice(0, 12).map((r) => `<li><b>${esc(r.name)}</b> (${esc(r.section)}) - ${r.dropped_twice ? "dropped twice in a row" : "not passed in the latest exam"}</li>`).join("")}</ul>` : `<p class="muted">Nobody - good news.</p>`}</div>
    <div class="card span2"><h3>Overall % in each exam</h3>${table(head, rows, { numeric: ex.map((_, i) => i + 2) })}</div></div>`;
}

// ---------------------------------------------------------------- report card (screen)
async function loadCard(body) {
  const s = S.summary;
  const studs = s.student_list.filter((x) => x.cls === S.view.cls && (S.view.section === "All" || x.section === S.view.section));
  if (!S.rcStudent || !studs.find((x) => x.sid === S.rcStudent)) S.rcStudent = studs.length ? studs[0].sid : null;
  if (!S.rcStudent) { body.innerHTML = `<div class="empty">No students.</div>`; return; }
  const card = await engine.call("report_card", S.rcStudent, S.view.exam);
  body.innerHTML = `<div class="card" style="margin-bottom:14px"><div class="row">
      <label class="field" style="flex:1;min-width:240px"><span>Student</span><select id="rc-st">${studs.map((x) => `<option value="${x.sid}" ${x.sid === S.rcStudent ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
      <button class="btn btn-ghost" id="rc-prev">←</button><button class="btn btn-ghost" id="rc-next">→</button>
      <button class="btn btn-primary" id="rc-print">Print / save as PDF</button></div></div>
    ${cardHtml(card)}`;
  const rows = card.rows.filter((r) => r.pct !== null && r.pct !== undefined);
  chart($("#rc-bar"), "bar", rows.map((r) => r.name), [{ label: "Student", data: rows.map((r) => r.pct), backgroundColor: cssVar("--blue"), borderRadius: 5 },
    { label: "Class average", data: rows.map((r) => r.class_avg), backgroundColor: "#BFD9EA", borderRadius: 5 }], { indexAxis: "y", x: { max: 100 }, y: { grid: { display: false } } });
  chart($("#rc-radar"), "radar", rows.map((r) => r.name), [{ label: "%", data: rows.map((r) => r.pct), backgroundColor: "rgba(6,167,231,.25)", borderColor: cssVar("--blue"), pointBackgroundColor: cssVar("--blue") }]);
  const tr = card.trend.filter((t) => t[1] !== null);
  chart($("#rc-trend"), "line", card.trend.map((t) => S.summary.classes.find((c) => c.cls === S.view.cls).exams.find((e) => e.code === t[0])?.name || t[0]),
    [{ label: "Overall %", data: card.trend.map((t) => t[1]), borderColor: "#0B3C5D", backgroundColor: cssVar("--blue"), tension: .3, pointRadius: 6, spanGaps: true }], { y: { max: 100 } });
  const sel = $("#rc-st");
  sel.addEventListener("change", () => { S.rcStudent = sel.value; loadTab(); });
  const move = (d) => { const i = studs.findIndex((x) => x.sid === S.rcStudent); const n = studs[(i + d + studs.length) % studs.length]; S.rcStudent = n.sid; loadTab(); };
  $("#rc-prev").addEventListener("click", () => move(-1));
  $("#rc-next").addEventListener("click", () => move(1));
  $("#rc-print").addEventListener("click", () => printCards([card], S.settings));
}

function cardHtml(c) {
  const st = c.student;
  const info = [["Name", st.name], ["Class", st.cls + (st.section ? "-" + st.section : "")], ["Roll no", st.roll], ["Admission no", st.adm_no],
    ["Father's name", st.father], ["Mother's name", st.mother], ["Group", st.group], ["Exam", c.exam_name]];
  const rows = c.rows.map((r) => [r.name, fmtMark(r.theory),
    r.practical === null ? "" : (r.parts && r.parts.length ? { html: `<span title="${esc(r.parts.map((p) => p.label + ": " + (p.value === null ? "–" : fmtMark(p.value)) + "/" + fmtMark(p.max)).join(" · "))}" style="border-bottom:1px dotted var(--muted)">${fmtMark(r.practical)}</span>` } : fmtMark(r.practical)), r.obtained === null ? "–" : fmtMark(r.obtained),
    fmtMark(r.max), r.pct, r.class_avg, r.grade || "–", { html: labelBadge(r.gentle) }]);
  return `<div class="rc"><div class="rc-top"><span class="brand-badge"><img src="assets/img/rdps-logo.png" alt=""></span>
      <div><h2>Report Card · ${esc(c.exam_name)} ${qmark("report-card")}</h2><p>${esc(S.settings.rules.school_name)}, ${esc(S.settings.rules.school_place)} · ${esc(S.settings.rules.academic_year)}</p></div></div>
    <div class="rc-info">${info.map(([k, v]) => `<div><span>${k}</span><b>${esc(v || "–")}</b></div>`).join("")}</div>
    <div class="rc-body">
      ${table(["Subject", c.th_head || "Theory", c.pr_head || "Practical", "Total", "Max", "%", "Class avg %", "Grade", "Status"], rows, { numeric: [1, 2, 3, 4, 5, 6] })}
      ${c.rows.some((r) => r.written_only) ? `<p class="tiny muted" style="margin:6px 0 0">No internal marks were given for some subjects - they are worked out of the written paper alone.</p>` : ""}
      <div class="rc-overall">
        <div><b>${fmtMark(c.obtained) || "–"}</b><span>Total</span></div><div><b>${fmtMark(c.max) || "–"}</b><span>Out of</span></div>
        <div><b>${fmt(c.overall, 2)}</b><span>Overall %</span></div><div><b style="font-size:1rem;padding:5px 0">${esc(c.result || "–")}</b><span>Result</span></div>
        <div><b>${c.rank ?? "–"}</b><span>Rank of ${c.class_size}</span></div></div>
      <div class="grid g2"><div><h3>Remarks</h3><ul class="remarks">${c.remarks.map((r) => `<li>${esc(r)}</li>`).join("") || "<li class='muted'>–</li>"}</ul>
        <h3 style="margin-top:12px">Subject notes</h3><ul class="remarks small">${c.rows.map((r) => `<li>${esc(r.reason)}</li>`).join("")}</ul></div>
        <div><div class="chart-box" style="height:250px"><canvas id="rc-bar"></canvas></div></div></div>
      <div class="grid g2" style="margin-top:12px"><div class="chart-box" style="height:260px"><canvas id="rc-radar"></canvas></div>
        <div class="chart-box" style="height:260px"><canvas id="rc-trend"></canvas></div></div>
    </div></div>`;
}

// ================================================================== 4. download
function downloads() {
  const s = S.summary;
  if (!s) return "";
  const c = s.classes.find((x) => x.cls === S.view.cls) || s.classes[0];
  const recipe = s.recipe || { items: [] };
  return `<div class="grid g2">
    <div class="card"><h3>📊 Excel workbook ${qmark("excel")}</h3>
      <p class="muted small">Dashboard, report cards, subject and marks analysis, progress, teachers, one marks sheet per class (and per stream in XI-XII), internal marks, validation report, settings and the untouched source data - with real Excel charts and formulas.</p>
      <label class="toggle" style="margin:6px 0 12px"><input type="checkbox" id="macros" ${prefs.macros ? "checked" : ""}><i></i>Include buttons (macros) - <span class="muted small">recalculate, reset, save report cards as PDF</span></label>
      <div class="row"><button class="btn btn-primary btn-lg" id="dl-wb">Download Excel</button><span id="dl-state" class="muted small"></span></div>
      <div class="note" style="margin-top:14px">💡 <b>First time opening a file with buttons?</b> Windows blocks macros in downloaded files. Right-click the file → <b>Properties</b> → tick <b>Unblock</b> → OK. The workbook also works without the buttons.</div>
    </div>
    <div class="card"><h3>🖨️ Report cards as PDF</h3>
      <p class="muted small">One page per student, in the school colours. Opens your browser's print window - choose “Save as PDF”.</p>
      <div class="row">
        <select class="sel-sm" id="pc-exam" style="width:auto">${c.exams.map((e) => `<option value="${e.code}" ${e.code === S.view.exam ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select>
        <select class="sel-sm" id="pc-sec" style="width:auto"><option value="All">All sections</option>${c.sections.map((x) => `<option ${x === S.view.section ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <button class="btn btn-navy" id="pc-go">Make ${esc(c.label)} report cards</button></div>
    </div>
    <div class="card span2"><div class="card-head"><h3>✍️ Change the Excel with words ${qmark("commands")}</h3><span class="muted small">Previewed first · undo any time · marks are never changed</span></div>
      <div class="chat-input"><input type="text" id="cmd" placeholder="e.g. add a chart of Physics averages by section" autocomplete="off">
        <button class="btn btn-primary" id="cmd-go">Preview</button></div>
      <div class="chips" style="margin-top:10px">${["Add a chart of Physics averages by section", "Highlight students below 40% in red", "Add a sheet with the top 10 in class " + c.cls,
        "Change the weak threshold to 8", "Add a pie chart of pass percentage by section", "Hide the Source Data sheet"].map((t) => `<button class="chip" data-cmd="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      <div id="cmd-out" style="margin-top:12px"></div>
      ${recipe.items.length ? `<div class="divider"></div><h3>Changes in this workbook (${recipe.items.length})</h3>
        <div class="stack">${recipe.items.map((it, i) => `<div class="file-row"><span class="ficon">${{ chart: "📈", highlight: "🖍", query_sheet: "📄", hide_sheet: "🙈" }[it.type] || "•"}</span>
          <div style="flex:1">${esc(describeItem(it))}</div><button class="btn btn-ghost btn-sm" data-rmitem="${i}">Remove</button></div>`).join("")}</div>` : ""}
    </div>
    <div class="card"><h3>📄 Template with these students</h3><p class="muted small">Names and roll numbers already filled in - teachers only type marks.</p>
      <div class="row">${s.classes.map((x) => `<button class="btn btn-ghost" data-tpl="${x.cls}">${esc(x.label)}</button>`).join("")}</div></div>
    <div class="card"><h3>🔁 Start again</h3><p class="muted small">Clears the uploaded files from this page (nothing is stored anywhere).</p>
      <button class="btn btn-danger" id="clear-all">Clear everything</button></div>
  </div>`;
}

function describeItem(it) {
  if (it.type === "chart") return "Chart: " + it.title;
  if (it.type === "highlight") return `Highlight ${it.subject ? "a subject" : "overall %"} ${it.op} ${it.value}% in ${it.color}`;
  if (it.type === "query_sheet") return `Sheet “${it.sheet}”: ${it.title}`;
  if (it.type === "hide_sheet") return `Hide “${it.sheet}”`;
  return it.type;
}

async function previewCommand(text) {
  const out = $("#cmd-out");
  out.innerHTML = `<div class="typing"><span></span><span></span><span></span></div>`;
  try {
    const r = await engine.call("command", text);
    if (r.error) {
      out.innerHTML = `<div class="note">🤔 ${esc(r.error)}${r.suggestions ? `<div class="chips" style="margin-top:8px">${r.suggestions.map((t) => `<button class="chip" data-cmd="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}</div>`;
      return;
    }
    S.pendingCommand = r.item;
    out.innerHTML = `<div class="card" style="box-shadow:none"><div class="row between"><div><b>Preview:</b> ${esc(r.description)}</div>
      <div class="row"><button class="btn btn-ghost btn-sm" id="cmd-cancel">Cancel</button><button class="btn btn-primary btn-sm" id="cmd-apply">Apply</button></div></div>
      ${r.preview && r.preview.chart ? `<div class="chart-box" style="height:240px;margin-top:10px"><canvas id="cmd-chart"></canvas></div>` : ""}
      ${r.preview && r.preview.table ? `<div style="margin-top:10px">${table(r.preview.table.columns, r.preview.table.rows, { max: 15 })}</div>` : ""}</div>`;
    if (r.preview && r.preview.chart) {
      const ch = r.preview.chart;
      const t = { column: "bar", bar: "bar", line: "line", pie: "pie", doughnut: "doughnut", radar: "radar" }[ch.type] || "bar";
      chart($("#cmd-chart"), t, ch.labels, [{ label: ch.label, data: ch.values, backgroundColor: t === "pie" || t === "doughnut" ? PALETTE() : cssVar("--blue"),
        borderColor: t === "line" ? "#0B3C5D" : undefined, borderRadius: 5 }], { indexAxis: ch.type === "bar" ? "y" : "x" });
    }
    $("#cmd-cancel").addEventListener("click", () => { out.innerHTML = ""; S.pendingCommand = null; });
    $("#cmd-apply").addEventListener("click", async () => {
      const res = await engine.call("apply_command", JSON.stringify(S.pendingCommand));
      S.summary.recipe = res.recipe;
      if (res.settings) { S.settings = res.settings; LS.set("rdps.settings", res.settings); S.summary = await engine.call("summary"); }
      toast(res.undone ? esc(res.message) : "Added ✓ It will be in the next Excel download.", "ok");
      rerender();
    });
  } catch (e) {
    out.innerHTML = `<div class="note">${esc(e.message)}</div>`;
  }
}

// ================================================================== events
export function mount(root) {
  if (!S.engineReady) return;
  if (S.files === null) { refreshState().then(rerender); return; }
  root.addEventListener("click", onClick);
  root.addEventListener("change", onChange);
  const drop = $("#drop");
  if (drop) {
    const fin = $("#file-in");
    fin.addEventListener("change", () => fin.files.length && addFiles(fin.files));
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => e.dataTransfer.files.length && addFiles(e.dataTransfer.files));
  }
  const wbIn = $("#wb-in");
  wbIn && wbIn.addEventListener("change", () => wbIn.files.length && openWorkbook(wbIn.files[0]));
  const cmd = $("#cmd");
  cmd && cmd.addEventListener("keydown", (e) => { if (e.key === "Enter" && cmd.value.trim()) previewCommand(cmd.value.trim()); });
  if (S.step === 3) loadTab();
  if (S.step === 2) aiSuggestions();
}

async function aiSuggestions() {
  if (ai.status.embed !== "ready") return;
  for (const el of $$("[data-aisug]")) {
    const h = el.dataset.aisug;
    const s = await ai.suggestHeader(h);
    if (s && s.role !== "ignore") {
      const box = el.closest("[data-colbox]").dataset.colbox;
      el.innerHTML = `<button class="link-btn tiny" data-aiapply="${esc(box)}" data-sug='${esc(JSON.stringify({ role: s.role, subject: s.subject || null, component: s.component || null }))}'>
        ✨ AI suggests: ${esc(s.label)} (${Math.round(s.score * 100)}%) - use it</button>`;
    }
  }
}

async function onClick(e) {
  const t = e.target.closest("button, [data-step], [data-go], tr[data-sid]");
  if (!t) return;
  const d = t.dataset;
  try {
    if (d.step) { S.step = +d.step; rerender(); return; }
    if (d.go) { S.step = +d.go; rerender(); window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    if (t.id === "sample" || t.id === "sample-bad") {
      busy = "Making sample marks…"; rerender();
      await engine.call("add_sample", t.id === "sample-bad");
      busy = null; await refreshState(); S.summary = null;
      toast(t.id === "sample-bad" ? "Sample added - it contains a few typical mistakes for the checks to catch." : "Sample data added (made-up students).", "ok");
      rerender(); return;
    }
    if (d.remove) { S.files = await engine.call("remove_file", d.remove); S.summary = null; rerender(); return; }
    if (t.id === "compare") return compareModal();
    if (d.confirm) { const [src, sheet] = splitKey(d.confirm); S.files = await engine.call("confirm_sheet", src, sheet); LS.set("rdps.remembered", await engine.call("remember_json")); toast("Confirmed ✓ - remembered for next time", "ok", 2000); rerender(); return; }
    if (t.id === "analyze") return analyze();
    if (d.filter) { S.issuesFilter = d.filter; rerender(); return; }
    if (d.fixcell) {
      const inp = $(`[data-fixval="${d.n}"]`);
      await engine.call("correct", d.fixcell, inp.value.trim());
      toast("Corrected - the original file is not changed. Re-checking…", "ok", 2500);
      return analyze();
    }
    if (d.undo) { await engine.call("correct", d.undo, null); return analyze(); }
    if (d.swap) { const [src, sheet, a, b] = d.swap.split("|"); await engine.call("swap_columns", src, sheet, +a, +b); return analyze(); }
    if (d.choose) {
      const opts = JSON.parse(decodeURIComponent(d.choose));
      const chosen = opts[+d.k].value;
      for (const o of opts) if (o.value !== chosen) await engine.call("correct", `${o.ref.file}|${o.ref.sheet}|${o.ref.row}|${o.ref.col}`, chosen);
      return analyze();
    }
    if (d.aiapply) {
      const [src, sheet, col] = splitKey(d.aiapply, 3);
      const sug = JSON.parse(d.sug);
      S.files = await engine.call("set_column", src, sheet, +col, JSON.stringify(sug));
      rerender(); return;
    }
    if (d.cls) { S.view.cls = d.cls; S.view.combo = ""; pickView(); rerender(); return; }
    if (d.tab) { S.tab = d.tab; rerender(); return; }
    if (t.matches("tr[data-sid]")) { S.rcStudent = d.sid; S.tab = "card"; rerender(); return; }
    if (t.id === "dl-wb") return downloadWorkbook(t);
    if (t.id === "pc-go") {
      t.disabled = true; t.innerHTML = `<span class="spinner"></span> Preparing…`;
      const r = await engine.call("report_cards", S.view.cls, $("#pc-exam").value, $("#pc-sec").value);
      t.disabled = false; t.textContent = "Make report cards";
      if (!r.cards.length) return toast("No students with marks for that choice.", "warn");
      printCards(r.cards, S.settings);
      return;
    }
    if (d.cmd) { $("#cmd").value = d.cmd; return previewCommand(d.cmd); }
    if (t.id === "cmd-go") { const v = $("#cmd").value.trim(); if (v) previewCommand(v); return; }
    if (d.rmitem !== undefined) { const r = await engine.call("remove_recipe_item", +d.rmitem); S.summary.recipe = r.recipe; rerender(); return; }
    if (d.tpl) {
      const bytes = await engine.bytes("template_bytes", d.tpl, true);
      download(bytes, `RDPS marks template - Class ${d.tpl} (with students).xlsx`, XLSX);
      return;
    }
    if (t.id === "clear-all") {
      if (!(await confirmModal("Clear everything?", "This removes the uploaded files and results from this page.", "Clear"))) return;
      await engine.call("clear_all");
      S.files = null; S.summary = null; S.step = 1; S.chat = [];
      await refreshState(); rerender(); return;
    }
  } catch (err) {
    toast(esc(err.message), "err", 9000);
    console.error(err.detail || err);
  }
}

async function onChange(e) {
  const t = e.target;
  const d = t.dataset;
  try {
    if (d.sheet) {
      const [src, sheet] = splitKey(d.sheet);
      const v = t.value.trim();
      S.files = await engine.call("set_sheet", src, sheet, JSON.stringify({ [d.k]: d.k === "section" ? v.toUpperCase() : v || null }));
      S.summary = null; rerender(); return;
    }
    if (d.skip) {
      const [src, sheet] = splitKey(d.skip);
      S.files = await engine.call("set_sheet", src, sheet, JSON.stringify({ skip: !t.checked }));
      S.summary = null; rerender(); return;
    }
    if (d.col) {
      const [src, sheet, col] = splitKey(d.col, 3);
      const box = t.closest("[data-colbox]");
      const get = (k) => { const el = $(`[data-col="${CSS.escape(d.col)}"][data-k="${k}"]`, box); return el ? el.value || null : null; };
      const role = get("role") || "ignore";
      const payload = { role, subject: get("subject"), component: get("component") || "theory", exam: get("exam") };
      S.files = await engine.call("set_column", src, sheet, +col, JSON.stringify(payload));
      S.summary = null; rerender(); return;
    }
    if (t.id === "v-cls") { S.view.cls = t.value; S.view.combo = ""; pickView(); rerender(); return; }
    if (t.id === "v-combo") { S.view.combo = t.value; rerender(); return; }
    if (t.id === "v-exam") { S.view.exam = t.value; rerender(); return; }
    if (t.id === "v-sec") { S.view.section = t.value; rerender(); return; }
    if (t.id === "trend-sub") { S.trendSubject = t.value; loadTab(); return; }
    if (t.id === "macros") { prefs.macros = t.checked; savePrefs(); return; }
  } catch (err) {
    toast(esc(err.message), "err", 8000);
  }
}

function splitKey(k, n = 2) {
  const parts = k.split("|");
  if (n === 2) return [parts[0], parts.slice(1).join("|")];
  return [parts[0], parts.slice(1, -1).join("|"), parts[parts.length - 1]];
}

async function downloadWorkbook(btn) {
  const macros = $("#macros").checked;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Building the workbook…`;
  $("#dl-state").textContent = "This takes a few seconds.";
  const t0 = performance.now();
  try {
    const bytes = await engine.bytes("build_workbook_bytes", macros);
    const name = await engine.value("workbook_name", macros);
    download(bytes, name, macros ? XLSM : XLSX);
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    modal(`<div class="center">${successTick()}<h2>Workbook ready</h2><p class="muted">${esc(name)}<br>${(bytes.length / 1e6).toFixed(1)} MB · built in ${secs} s</p>
      ${macros ? `<div class="note" style="text-align:left">If Excel shows a red bar about macros: close the file, right-click it → <b>Properties</b> → tick <b>Unblock</b> → OK, then open it again.</div>` : ""}
      <button class="btn btn-primary" data-close style="margin-top:14px">Done</button></div>`);
  } catch (e) {
    toast("Could not build the workbook: " + esc(e.message), "err", 10000);
  }
  btn.disabled = false;
  btn.textContent = "Download Excel";
  $("#dl-state").textContent = "";
}

// ---------------------------------------------------------------- double-entry compare
function compareModal() {
  const f = S.files.files;
  const m = modal(`<h2>Compare two files</h2><p class="muted small">Pick the two files that should have the same marks. Every cell that differs is listed.</p>
    <div class="grid g2"><label class="field"><span>File A</span><select id="ca">${f.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
    <label class="field"><span>File B</span><select id="cb">${f.map((x, i) => `<option value="${x.id}" ${i === 1 ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label></div>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-ghost" data-close>Close</button><button class="btn btn-primary" id="cgo">Compare</button></div>
    <div id="cout" style="margin-top:14px"></div>`);
  $("#cgo", m.el).addEventListener("click", async () => {
    const out = $("#cout", m.el);
    out.innerHTML = `<div class="typing"><span></span><span></span><span></span></div>`;
    try {
      const r = await engine.call("compare_entries", $("#ca", m.el).value, $("#cb", m.el).value);
      out.innerHTML = r.differences.length ? `<p><b>${r.differences.length} difference${r.differences.length > 1 ? "s" : ""}</b> in ${r.checked} marks.</p>` +
        table(["Student", "Exam", "Subject", "Part", "File A", "File B"], r.differences.map((x) => [x.student, x.exam, x.subject, x.part, x.a, x.b]), { max: 200 })
        : `<div class="center">${successTick()}<b>No differences</b> in ${r.checked} marks.</div>`;
    } catch (e) { out.innerHTML = `<div class="note">${esc(e.message)}</div>`; }
  });
}
