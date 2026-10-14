// Board results: the CBSE gazette, kept separate from school tests.
import * as engine from "../engine.js";
import { S } from "../state.js";
import { $, esc, fmt, toast, chart, countUp, download, XLSX, table, cssVar, PALETTE } from "../ui.js";

const rerender = () => window.__render();
let busy = false;
const GRADE_COL = { A1: "#0B3C5D", A2: "#1F5F8B", B1: "#06A7E7", B2: "#5CC4EF", C1: "#9FDCF5", C2: "#CBEBF9", D1: "#F7C873", D2: "#F2A93B", E: "#C0392B" };

export function html() {
  if (!S.engineReady) return `<div class="page-head"><div><h1>Board results</h1><p>Getting ready…</p></div></div>`;
  const b = S.board;
  return `<div class="page-head"><div><h1>Board results</h1>
      <p>Upload the CBSE result gazette (the .TXT file CBSE sends the school). Marks and grades are shown exactly as CBSE printed them.</p></div>
      ${b ? `<button class="btn btn-primary btn-lg" id="b-dl">Download board workbook</button>` : ""}</div>
    <label class="drop" id="bdrop" style="padding:${b ? "18px" : "38px"} 20px">
      <input type="file" id="b-in" multiple accept=".txt,.TXT,.pdf">
      ${b ? `<div class="row" style="justify-content:center"><b>Add another year's gazette</b><span class="muted small">to compare years</span></div>` :
      `<div class="drop-icon"><svg viewBox="0 0 24 24"><path d="M12 3l9 4-9 4-9-4 9-4zm-6 6v5c0 2 3 4 6 4s6-2 6-4V9"/></svg></div>
       <h3>Drop the CBSE gazette here</h3><div class="muted">e.g. “12345.TXT” (named after the school code) · several years can be added</div>`}
    </label>
    ${b ? "" : `<div class="row" style="justify-content:center;margin-top:12px"><button class="btn btn-soft" id="b-sample">Try a made-up sample gazette</button></div>`}
    ${busy ? `<div class="card" style="margin-top:14px"><span class="spinner" style="color:var(--blue)"></span> Reading the gazette…</div>` : ""}
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
      · ${esc(m.title)} · School ${esc(m.school_code)} ${esc(m.school_name)}</div>
    <div class="grid g5">${k(a.candidates, "Candidates", 0)}${k(a.pass_pct, "Pass %")}${k(a.comp, "Compartment", 0)}${k(a.avg_best5, "Average best-5 %")}${k(a.school_pi, "School PI")}</div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>Average marks by subject</h3><div class="chart-box tall"><canvas id="bc-avg"></canvas></div></div>
      <div class="card"><h3>CBSE grades in each subject</h3><div class="chart-box tall"><canvas id="bc-gr"></canvas></div></div>
      <div class="card"><h3>Students by best-5 %</h3><div class="chart-box"><canvas id="bc-dist"></canvas></div></div>
      <div class="card"><h3>Performance Index (PI) by subject</h3><div class="chart-box"><canvas id="bc-pi"></canvas></div>
        <p class="tiny muted" style="margin:6px 0 0">PI = (8×A1 + 7×A2 + … + 1×D2) × 100 ÷ (8 × candidates).</p></div>
      <div class="card"><h3>🏆 Top 10 (best 5)</h3>${table(["Rank", "Name", "Best 5 %", "All %"], a.ranked.slice(0, 10).map((r) => [r.rank, r.name, r.best5, r.pct_all]), { numeric: [0, 2, 3] })}</div>
      <div class="card"><h3>Compartment (${a.comp_list.length})</h3>${a.comp_list.length ? table(["Name", "Roll", "Subject"], a.comp_list.map((c) => [c.name, c.roll, c.comp.join(", ")])) : `<p class="muted">None.</p>`}
        ${a.gender && a.gender.length > 1 ? `<h3 style="margin-top:16px">Girls and boys</h3>${table(["Group", "Students", "Pass %", "Avg best 5 %"], a.gender.map((g) => [g.gender, g.n, g.pass_pct, g.avg_best5]), { numeric: [1, 2, 3] })}` : ""}</div>
      <div class="card span2"><h3>Subjects</h3>${table(["Code", "Subject", "Candidates", "Average", "Highest", "Lowest", "Grade E", "90+", "PI"],
        a.subjects.map((s) => [s.code, s.name, s.candidates, s.avg, s.max, s.min, s.failed, s.above90, s.pi]), { numeric: [2, 3, 4, 5, 6, 7, 8] })}</div>
      ${b.years ? `<div class="card span2"><h3>Year on year</h3>${table(["Year", "Pass %", "Avg best 5 %", "School PI", "Candidates"], b.years.summary.map((y) => [y[0], y[1], y[2], y[3], y[4]]), { numeric: [1, 2, 3, 4] })}</div>` : ""}
      ${b.link ? `<div class="card span2"><h3>School tests vs Boards</h3><p class="muted small">${b.link.linked_students} students linked by Board Roll No${b.link.by_name ? ` (${b.link.by_name} by name - please check)` : ""}. Gap = board marks − school %.</p>
        ${table(["Subject", "Students", "Average gap (points)"], b.link.by_subject.map((x) => [x.name, x.n, x.avg_gap]), { numeric: [1, 2] })}</div>` : ""}
      <div class="card span2"><h3>Checks</h3>${a.issues.length ? table(["Type", "Details"], a.issues.map((i) => [i.severity, i.message]), { wrap: [1] }) : `<p class="muted">Nothing to report.</p>`}</div>
    </div>`;
}

async function addFiles(files) {
  busy = true; rerender();
  for (const f of files) {
    try {
      const data = new Uint8Array(await f.arrayBuffer());
      const info = await engine.call("add_file", f.name, data);
      if (info.kind !== "gazette") toast(`${esc(f.name)} is not a CBSE gazette - it was added to School results instead.`, "warn", 7000);
      else toast(`Read ${info.students} candidates (${info.year}).`, "ok");
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
    try { await engine.call("add_sample_gazette"); S.board = await engine.call("board_summary"); toast("Made-up sample gazette loaded (fake school, fake names).", "ok"); }
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
  const grades = ["A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E"];
  chart($("#bc-gr"), "bar", subs.map((s) => s.short), grades.map((g) => ({ label: g, data: subs.map((s) => (s.grades[g] || 0) * 100 / Math.max(1, s.candidates)), backgroundColor: GRADE_COL[g] })),
    { indexAxis: "y", extra: { scales: { x: { stacked: true, max: 100, grid: { color: cssVar("--line") } }, y: { stacked: true, grid: { display: false } } } },
      tooltip: { label: (c) => ` ${c.dataset.label}: ${c.parsed.x.toFixed(0)}%` } });
  chart($("#bc-dist"), "bar", a.distribution.map((d) => d[0]), [{ data: a.distribution.map((d) => d[1]), backgroundColor: "#0B3C5D", borderRadius: 6 }]);
  chart($("#bc-pi"), "bar", subs.map((s) => s.short), [{ data: subs.map((s) => s.pi), backgroundColor: PALETTE()[3], borderRadius: 6 }], { y: { max: 100 } });
}
