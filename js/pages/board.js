// Board results: the CBSE gazette, kept separate from school tests.
import * as engine from "../engine.js";
import { S } from "../state.js";
import { $, esc, fmt, toast, chart, countUp, download, XLSX, table, cssVar, PALETTE } from "../ui.js";
import { qmark } from "../explain.js";
import { addAny } from "../intake.js";

const rerender = () => window.__render();
let busy = false;
const GRADE_COL = { A1: "#0B3C5D", A2: "#1F5F8B", B1: "#06A7E7", B2: "#5CC4EF", C1: "#9FDCF5", C2: "#CBEBF9", D1: "#F7C873", D2: "#F2A93B", E: "#C0392B" };

export function html() {
  if (!S.engineReady) return `<div class="page-head"><div><h1>Board results</h1><p>Getting ready…</p></div></div>`;
  const b = S.board;
  return `<div class="page-head"><div><h1>Board results</h1>
      <p>Add the board results: the result file CBSE sends the school (.TXT), or your own list of board marks (Excel, CSV, TXT or PDF - one row per student with the marks of each subject). Marks are shown exactly as in the file.</p></div>
      ${b ? `<button class="btn btn-primary btn-lg" id="b-dl">Download board workbook</button>` : ""}</div>
    <label class="drop" id="bdrop" style="padding:${b ? "18px" : "38px"} 20px">
      <input type="file" id="b-in" multiple accept=".txt,.TXT,.pdf,.xlsx,.xlsm,.xls,.csv,.png,.jpg,.jpeg,.webp">
      ${b ? `<div class="row" style="justify-content:center"><b>Add another year's board results</b><span class="muted small">to compare years</span></div>` :
      `<div class="drop-icon"><svg viewBox="0 0 24 24"><path d="M12 3l9 4-9 4-9-4 9-4zm-6 6v5c0 2 3 4 6 4s6-2 6-4V9"/></svg></div>
       <h3>Drop the board results here</h3><div class="muted">CBSE's “12345.TXT” or your own marks list · Class XII or X is found by itself · several years can be added</div>`}
    </label>
    ${b ? "" : `<div class="row" style="justify-content:center;margin-top:12px"><button class="btn btn-soft" id="b-sample">Try made-up board results</button></div>`}
    ${busy ? `<div class="card" style="margin-top:14px"><span class="spinner" style="color:var(--blue)"></span> Reading the board results…</div>` : ""}
    <div id="b-body" style="margin-top:18px">${b ? body(b) : ""}</div>`;
}

function body(b) {
  const a = b.boards[b.boards.length - 1];
  const m = a.meta;
  const k = (v, l, p = 1) => `<div class="kpi"><div class="v" data-count="${v ?? 0}" data-places="${p}">0</div><div class="l">${l}</div></div>`;
  const checks = a.issues.filter((i) => i.severity !== "info");
  const ok = a.issues.find((i) => i.code === "gazette_count_ok");
  return `
    <div class="note" style="margin-bottom:16px">${ok ? "✔ " + esc(ok.message) : ""} ${checks.length ? `<b>${checks.length} thing(s) to check</b> - see Checks below.` : "No problems found."}
      · ${esc(m.title)}${m.school_code ? ` · School ${esc(m.school_code)} ${esc(m.school_name)}` : ""}</div>
    <div class="grid g5">${k(a.candidates, "Students", 0)}${k(a.pass_pct, "Pass %")}${k(a.comp, "Compartment", 0)}${k(a.avg_best5, "Average of best 5 subjects %")}${m.graded ? k(a.school_pi, "School PI (grade score)") : k(a.above90, "Best 5 at 90% or more", 0)}</div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>Average marks by subject</h3><div class="chart-box tall"><canvas id="bc-avg"></canvas></div></div>
      <div class="card"><h3>${m.graded ? "CBSE grades in each subject" : "Marks in each subject"}</h3><div class="chart-box tall"><canvas id="bc-gr"></canvas></div></div>
      <div class="card"><h3>Students by best-5 %</h3><div class="chart-box"><canvas id="bc-dist"></canvas></div></div>
      <div class="card"><h3>${m.graded ? "Performance Index (PI) by subject" : "Students with 90 or more, by subject"}</h3><div class="chart-box"><canvas id="bc-pi"></canvas></div>
        ${m.graded ? `<p class="tiny muted" style="margin:6px 0 0">PI = (8×A1 + 7×A2 + … + 1×D2) × 100 ÷ (8 × candidates) - a single grade score from 0 to 100.</p>` : ""}</div>
      <div class="card"><h3>🏆 Top 10 (best 5)</h3>${table(["Rank", "Name", "Best 5 %", "All %"], a.ranked.slice(0, 10).map((r) => [r.rank, r.name, r.best5, r.pct_all]), { numeric: [0, 2, 3] })}</div>
      <div class="card"><h3>Compartment (${a.comp_list.length})</h3>${a.comp_list.length ? table(["Name", "Roll", "Subject"], a.comp_list.map((c) => [c.name, c.roll, c.comp.join(", ")])) : `<p class="muted">None.</p>`}
        ${a.gender && a.gender.length > 1 ? `<h3 style="margin-top:16px">Girls and boys</h3>${table(["Group", "Students", "Pass %", "Avg best 5 %"], a.gender.map((g) => [g.gender, g.n, g.pass_pct, g.avg_best5]), { numeric: [1, 2, 3] })}` : ""}</div>
      <div class="card span2"><h3>Subjects</h3>${table(["Code", "Subject", "Students", "Average", "Highest", "Lowest", "Did not pass", "90 or more", "PI (grade score)"],
        a.subjects.map((s) => [s.code, s.name, s.candidates, s.avg, s.max, s.min, s.failed, s.above90, s.pi]), { numeric: [2, 3, 4, 5, 6, 7, 8] })}</div>
      ${b.years ? `<div class="card span2"><h3>Year on year</h3>${table(["Year", "Pass %", "Avg best 5 %", "School PI", "Candidates"], b.years.summary.map((y) => [y[0], y[1], y[2], y[3], y[4]]), { numeric: [1, 2, 3, 4] })}</div>` : ""}
      ${b.link ? `<div class="card span2"><h3>School tests vs Boards</h3><p class="muted small">${b.link.linked_students} students linked by Board Roll No${b.link.by_name ? ` (${b.link.by_name} by name - please check)` : ""}. Gap = board marks − school %.</p>
        ${table(["Subject", "Students", "Average gap (points)"], b.link.by_subject.map((x) => [x.name, x.n, x.avg_gap]), { numeric: [1, 2] })}</div>` : ""}
      ${teachersCard(b.teachers)}
      <div class="card span2"><h3>Checks</h3>${a.issues.length ? table(["", "Details"], a.issues.map((i) => [({ error: "Problem", warning: "Check", info: "Note" })[i.severity] || i.severity, i.message]), { wrap: [1] }) : `<p class="muted">Nothing to report.</p>`}</div>
    </div>`;
}

function teachersCard(t) {
  if (!t) return "";
  if (!t.cards.length) {
    return `<div class="card span2"><h3>Teachers ${qmark("teachers")}</h3><p class="muted">Add the teachers (name, subject, class ${esc(t.cls)} and sections) and the class lists on the
      <a href="#/teachers">Teachers page</a> to see how each teacher's own students did.</p></div>`;
  }
  const good = t.cards.filter((c) => c.fair.verdict === "Clear positive impact").length;
  const talk = t.cards.filter((c) => c.fair.verdict === "Worth a conversation").length;
  const p = t.placement || { placed: 0, total: 0 };
  return `<div class="card span2 t-board-sum"><div class="card-head"><h3>Teachers ${qmark("teachers")}</h3>
      <a class="btn btn-primary btn-sm" href="#/teachers" data-boardtab>See each teacher with charts →</a></div>
    <div class="grid g4"><div class="kpi"><div class="v">${t.cards.length}</div><div class="l">teacher cards</div></div>
      <div class="kpi good"><div class="v">${good}</div><div class="l">clearly better</div></div>
      <div class="kpi warn"><div class="v">${talk}</div><div class="l">worth a conversation</div></div>
      <div class="kpi"><div class="v">${p.placed}/${p.total}</div><div class="l">students placed in a section</div></div></div>
    ${!t.split ? `<p class="small muted" style="margin:10px 0 0">💡 Add the class lists on the Teachers page to see each teacher on their own sections.</p>` : ""}</div>`;
}

async function addFiles(files) {
  busy = true; rerender();
  for (const f of files) {
    try {
      await addAny(f, { hint: "board" });
    } catch (e) { toast(`Could not read ${esc(f.name)}: ${esc(e.message)}`, "err", 8000); }
  }
  S.files = null;
  try { S.board = await engine.call("board_summary"); } catch (e) { S.board = null; }
  busy = false; rerender();
}

export function mount() {
  if (!S.engineReady) return;
  if (!S.board) engine.call("board_summary").then((b) => { S.board = b; rerender(); }).catch(() => {});
  const inp = $("#b-in"), drop = $("#bdrop");
  inp && inp.addEventListener("change", () => inp.files.length && addFiles([...inp.files]));
  if (drop) {
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => e.dataTransfer.files.length && addFiles([...e.dataTransfer.files]));
  }
  const sm = $("#b-sample");
  sm && sm.addEventListener("click", async () => {
    busy = true; rerender();
    try { await engine.call("add_sample_gazette"); S.board = await engine.call("board_summary"); toast("Made-up board results loaded (fake school, fake names).", "ok"); }
    catch (e) { toast(esc(e.message), "err"); }
    busy = false; rerender();
  });
  const dl = $("#b-dl");
  dl && dl.addEventListener("click", async () => {
    dl.disabled = true; dl.innerHTML = `<span class="spinner"></span> Building…`;
    try {
      const bytes = await engine.bytes("board_workbook_bytes");
      const name = await engine.value("board_workbook_name");
      download(bytes, name, XLSX);
      toast("Board workbook downloaded ✓", "ok");
    } catch (e) { toast(esc(e.message), "err", 9000); }
    dl.disabled = false; dl.textContent = "Download board workbook";
  });
  const b = S.board;
  if (!b) return;
  const a = b.boards[b.boards.length - 1];
  countUp(document);
  const subs = a.subjects;
  chart($("#bc-avg"), "bar", subs.map((s) => s.short), [{ data: subs.map((s) => s.avg), backgroundColor: cssVar("--blue"), borderRadius: 6 }], { indexAxis: "y", x: { max: 100 }, y: { grid: { display: false } } });
  const graded = a.meta.graded;
  const grades = graded ? ["A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E"] : (subs[0] ? subs[0].bands.map((x) => x[0]) : []);
  const ramp = ["#1E8E5A", "#4CB782", "#06A7E7", "#5CC4EF", "#F7C873", "#F2A93B", "#C0392B"];
  const val = (s, g) => graded ? (s.grades[g] || 0) : ((s.bands.find((x) => x[0] === g) || [0, 0])[1]);
  chart($("#bc-gr"), "bar", subs.map((s) => s.short), grades.map((g, i) => ({ label: g, data: subs.map((s) => val(s, g) * 100 / Math.max(1, s.candidates)), backgroundColor: graded ? GRADE_COL[g] : ramp[i % ramp.length] })),
    { indexAxis: "y", extra: { scales: { x: { stacked: true, max: 100, grid: { color: cssVar("--line") } }, y: { stacked: true, grid: { display: false } } } },
      tooltip: { label: (c) => ` ${c.dataset.label}: ${c.parsed.x.toFixed(0)}%` } });
  chart($("#bc-dist"), "bar", a.distribution.map((d) => d[0]), [{ data: a.distribution.map((d) => d[1]), backgroundColor: "#0B3C5D", borderRadius: 6 }]);
  if (graded) chart($("#bc-pi"), "bar", subs.map((s) => s.short), [{ data: subs.map((s) => s.pi), backgroundColor: PALETTE()[3], borderRadius: 6 }], { y: { max: 100 } });
  else chart($("#bc-pi"), "bar", subs.map((s) => s.short), [{ data: subs.map((s) => s.above90), backgroundColor: PALETTE()[3], borderRadius: 6 }]);
  const bt = $("[data-boardtab]");
  bt && bt.addEventListener("click", () => { S.tTab = "board"; });
}
