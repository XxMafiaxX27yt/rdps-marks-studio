// Board results: CBSE's result file (or the school's own board list), kept separate from school tests.
// Same layout as the School results review: pick the class, then tabs.
import * as engine from "../engine.js";
import { S } from "../state.js";
import { $, $$, esc, fmt, toast, chart, countUp, download, XLSX, table, cssVar } from "../ui.js";
import { qmark } from "../explain.js";
import { addAny } from "../intake.js";

const rerender = () => window.__render();
let busy = false;
// CBSE grades: green (top) -> blue -> grey -> amber -> red, readable on light and dark backgrounds
const GRADE_COL = { A1: "#1E9E63", A2: "#5CC98F", B1: "#06A7E7", B2: "#5CC4EF", C1: "#8FA9BE", C2: "#BFCCD8", D1: "#F7C873", D2: "#F2A93B", E: "#E0533F" };
const GRADES = ["A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E"];
const BAND_RAMP = ["#1E8E5A", "#4CB782", "#06A7E7", "#5CC4EF", "#F7C873", "#F2A93B", "#C0392B"];
const MEDAL = { 1: "🥇", 2: "🥈", 3: "🥉" };
const BARS = () => [cssVar("--blue"), "#3E7CA6", "#7FD0F2", "#9DB4C7", "#F2A93B", "#5CC4EF", "#1E8E5A"];   // readable on light and dark
const V = { key: null, tab: "overview", stu: null, q: "", stream: "", result: "", sort: "rank" };

const cur = () => {
  const bs = (S.board && S.board.boards) || [];
  return bs.find((x) => x.key === V.key) || bs[bs.length - 1] || null;
};
const pct = (v, p = 1) => (v === null || v === undefined ? "–" : fmt(v, p));
const resultBadge = (r) => r === "PASS" ? `<span class="badge b-ok">Pass</span>`
  : /^COMP/.test(r || "") ? `<span class="badge b-att">Compartment</span>` : `<span class="badge b-warn">${esc(r || "–")}</span>`;

// ================================================================== page frame
export function html() {
  if (!S.engineReady) return `<div class="page-head"><div><h1>Board results</h1><p>Getting ready…</p></div></div>`;
  const b = cur();
  const head = `<div class="page-head"><div><h1>Board results</h1>
      <p>CBSE's result file (“85xxx.TXT”) or the school's own list of board marks. Read on this computer only - nothing is uploaded.</p></div>
      ${b ? `<div class="row"><label class="btn btn-ghost" title="Another class or another year">＋ Add a file<input type="file" id="b-in" multiple hidden accept=".txt,.TXT,.pdf,.xlsx,.xlsm,.xls,.csv,.png,.jpg,.jpeg,.webp"></label>
        <button class="btn btn-primary" id="b-dl">Download Excel · Class ${esc(b.meta.cls || "XII")}</button></div>` : ""}</div>`;
  if (!b) {
    return `${head}<label class="drop" id="bdrop">
        <input type="file" id="b-in" multiple accept=".txt,.TXT,.pdf,.xlsx,.xlsm,.xls,.csv,.png,.jpg,.jpeg,.webp">
        <div class="drop-icon"><svg viewBox="0 0 24 24"><path d="M12 3l9 4-9 4-9-4 9-4zm-6 6v5c0 2 3 4 6 4s6-2 6-4V9"/></svg></div>
        <h3>Drop the board results here</h3><div class="muted">CBSE's “12345.TXT” or your own marks list · Class XII or X is found by itself · several years can be added</div>
      </label>
      <div class="row" style="justify-content:center;margin-top:12px"><button class="btn btn-soft" id="b-sample">Try made-up board results</button></div>
      ${busy ? `<div class="card" style="margin-top:14px"><span class="spinner" style="color:var(--blue)"></span> Reading the board results…</div>` : ""}`;
  }
  return `${head}${busy ? `<div class="card" style="margin-bottom:14px"><span class="spinner" style="color:var(--blue)"></span> Reading the board results…</div>` : ""}
    ${bar(b)}
    <div class="tabs" id="b-tabs">${tabs(b).map(([k, l]) => `<button class="${V.tab === k ? "on" : ""}" data-btab="${k}">${l}</button>`).join("")}</div>
    <div id="b-body"></div>`;
}

function bar(b) {
  const bs = S.board.boards;
  const m = b.meta;
  const probs = b.issues.filter((i) => i.severity !== "info").length;
  const ok = b.issues.find((i) => i.code === "gazette_count_ok");
  return `<div class="card bbar"><div class="row between">
      <div class="row">
        ${bs.length > 1 ? `<div class="seg">${bs.map((x) => `<button class="${x.key === b.key ? "on" : ""}" data-bkey="${x.key}">${esc(x.label)}</button>`).join("")}</div>`
          : `<b class="bbar-title">${esc(b.label)}</b>`}
        <span class="muted small">${m.school_code ? `School ${esc(m.school_code)} · ` : ""}${esc(titleCase(m.school_name || ""))}${m.date ? ` · result ${esc(m.date)}` : ""}</span>
      </div>
      ${probs ? `<button class="chip-s warn" data-btab="checks">⚠ ${probs} thing${probs > 1 ? "s" : ""} to check</button>`
        : `<span class="chip-s ok">✔ ${ok ? `All ${b.candidates} students read` : "No problems found"}</span>`}
    </div></div>`;
}

function tabs(b) {
  const t = [["overview", "Overview"], ["toppers", "Toppers"], ["students", "Students"], ["subjects", "Subjects"]];
  if (b.streams && b.streams.length) t.push(["streams", "Streams"]);
  t.push(["teachers", "Teachers"]);
  if (b.years) t.push(["years", "Year on year"]);
  if (b.link) t.push(["link", "School vs board"]);
  t.push(["checks", "Checks"]);
  return t;
}

function titleCase(s) { return s.toLowerCase().replace(/\b([a-z])/g, (c) => c.toUpperCase()); }

// ================================================================== tabs
function body(b) {
  switch (V.tab) {
    case "toppers": return toppersHtml(b);
    case "students": return studentsHtml(b);
    case "subjects": return subjectsHtml(b);
    case "streams": return streamsHtml(b);
    case "teachers": return teachersHtml(b);
    case "years": return yearsHtml(b);
    case "link": return linkHtml(b);
    case "checks": return checksHtml(b);
    default: return overviewHtml(b);
  }
}

const kpi = (v, l, p = 1, s = "", cls = "") => `<div class="kpi ${cls}"><div class="v" ${v !== null && v !== undefined ? `data-count="${v}" data-places="${p}"` : ""}>${v === null || v === undefined ? "–" : fmt(0, p)}</div>
  <div class="l">${l}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;

function overviewHtml(b) {
  const top = places(b)[0];
  const g = (b.gender || []).filter((x) => x.gender !== "?");
  return `<div class="grid g5">
      ${kpi(b.candidates, "Students", 0, g.length > 1 ? g.map((x) => `${x.n} ${esc(x.gender.toLowerCase())}`).join(" · ") : "")}
      ${kpi(b.pass_pct, "Pass %", 1, `${b.passed} passed · ${b.comp} compartment`, b.comp ? "" : "good")}
      ${kpi(b.avg_best5, "Average · best 5 %", 1, b.avg_all !== null ? `${fmt(b.avg_all)}% with every subject` : "")}
      ${kpi(b.above90, "90% and above", 0, `${b.above95} at 95% or more`)}
      ${b.meta.graded ? kpi(b.school_pi, "School PI " + qmark("board-pi"), 1, "CBSE grade score, 0-100") : kpi(b.subjects.length, "Subjects", 0)}
    </div>
    <div class="grid b-ov">
      <div class="card"><div class="card-head"><h3>Highlights</h3><span class="tiny muted">worked out from the marks</span></div>
        <ul class="hl">${b.highlights.map((h) => `<li>${esc(h)}</li>`).join("")}</ul></div>
      ${top ? `<div class="card hero"><div class="hero-medal">🏆</div><div class="tiny muted">TOP SCORER</div>
        <div class="hero-name">${top.who.map((x) => esc(x.name)).join("<br>")}</div>
        <div class="hero-v">${fmt(top.who[0].best5)}<small>%</small></div><div class="muted small">best 5${top.who[0].stream ? ` · ${esc(top.who[0].stream)}` : ""}</div>
        <button class="btn btn-soft btn-sm" data-btab="toppers" style="margin-top:12px">All toppers →</button></div>` : ""}
    </div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>Students by best-5 %</h3><div class="chart-box"><canvas id="bc-dist"></canvas></div></div>
      <div class="card"><h3>Average marks by subject</h3><div class="chart-box"><canvas id="bc-avg"></canvas></div></div>
      <div class="card"><div class="card-head"><h3>Result</h3>${b.comp_list.length ? `<span class="badge b-att">${b.comp_list.length} compartment</span>` : `<span class="badge b-ok">everyone passed</span>`}</div>
        <div class="res-split"><div class="chart-box sm"><canvas id="bc-res"></canvas></div>
          <div>${b.comp_list.length ? `<div class="tiny muted" style="margin-bottom:6px">COMPARTMENT</div>${b.comp_list.map((c) =>
            `<div class="comp-line" data-roll="${esc(c.roll)}"><b>${esc(c.name)}</b><span>${esc(c.comp.join(", "))}${c.marks.length ? ` · ${c.marks.join(", ")} marks` : ""}</span></div>`).join("")}`
            : `<p class="muted small">No compartments.</p>`}
            ${b.others_list.length ? `<div class="tiny muted" style="margin:10px 0 6px">OTHER RESULTS</div>${b.others_list.map((o) => `<div class="comp-line"><b>${esc(o.name)}</b><span>${esc(o.result)}</span></div>`).join("")}` : ""}</div></div></div>
      <div class="card"><h3>${b.streams.length > 1 ? "Streams, girls and boys" : "Girls and boys"}</h3><div class="chart-box sm"><canvas id="bc-grp"></canvas></div>
        <p class="tiny muted" style="margin:8px 0 0">Average best-5 % of each group (the number of students is in brackets).</p></div>
    </div>`;
}

// ---------------------------------------------------------------- toppers
function places(b) {
  const out = [];
  for (const r of b.ranked) {
    const last = out[out.length - 1];
    if (last && last.rank === r.rank) last.who.push(r);
    else if (out.length < 3) out.push({ rank: r.rank, who: [r] });
    else break;
  }
  return out;
}

function toppersHtml(b) {
  const pl = places(b);
  const pod = (p, i) => p ? `<div class="pod p${i + 1}"><div class="medal">${MEDAL[i + 1]}</div>
      <div class="pn">${p.who.map((x) => esc(x.name)).join("<br>")}</div>
      <div class="pv">${fmt(p.who[0].best5)}%</div><div class="ps">${esc([...new Set(p.who.map((x) => x.stream).filter(Boolean))].join(" · ") || "best 5")}</div>
      <div class="pstep">${p.rank}</div></div>` : `<div class="pod p${i + 1} empty-pod"></div>`;
  const top10 = b.ranked.slice(0, 10);
  const studs = b.students;
  const club = studs.filter((s) => s.best5 !== null && s.best5 >= 90).sort((a, c) => c.best5 - a.best5);
  return `<div class="card podium-card"><div class="podium">${pod(pl[1], 1)}${pod(pl[0], 0)}${pod(pl[2], 2)}</div>
      <p class="tiny muted center" style="margin:10px 0 0">Best 5 % = English + the best four other subjects. Equal marks share a place.</p></div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>Top 10</h3><ol class="toplist">${top10.map((r) => `<li data-roll="${esc(r.roll)}"><span class="rk">${MEDAL[r.rank] || r.rank}</span>
          <span class="nm"><b>${esc(r.name)}</b>${r.stream ? `<small>${esc(r.stream)}</small>` : ""}</span>
          <span class="barwrap"><i style="width:${Math.max(0, (r.best5 - 50) * 2)}%"></i></span><span class="pv">${fmt(r.best5)}</span></li>`).join("")}</ol></div>
      ${b.streams.length ? `<div class="card"><h3>Stream toppers</h3><div class="stream-tops">${b.streams.map((s) => `<div class="st-box"><div class="st-name">${esc(s.stream)} <span class="muted tiny">${s.n} students</span></div>
          ${s.top.map((t, i) => `<div class="st-row" data-roll="${esc(t.roll)}"><span>${MEDAL[i + 1]}</span><b>${esc(t.name)}</b><span class="muted tiny">${esc(t.combo)}</span><span class="pv">${fmt(t.best5)}</span></div>`).join("")}</div>`).join("")}</div></div>`
        : `<div class="card"><h3>90 or more in every subject (${b.all_rounders.length})</h3>${namesChips(b.all_rounders)}</div>`}
    </div>
    <div class="card" style="margin-top:18px"><h3>Subject toppers</h3><div class="sub-tops">${b.subjects.filter((s) => s.max !== null).map((s) => `<div class="sub-top ${s.max === 100 ? "full" : ""}">
        <div class="tiny muted">${esc(s.name)}</div><div class="sv">${s.max}${s.max === 100 ? `<span class="badge b-ok">full marks</span>` : ""}</div>
        <div class="small">${s.toppers.map(esc).join(", ")}</div></div>`).join("")}</div></div>
    <div class="grid g2" style="margin-top:18px">
      ${b.streams.length ? `<div class="card"><h3>90 or more in every subject (${b.all_rounders.length})</h3>${namesChips(b.all_rounders)}</div>` : ""}
      <div class="card ${b.streams.length ? "" : "span2"}"><h3>90% club · ${club.length} student${club.length === 1 ? "" : "s"}</h3>
        <div class="name-chips">${club.map((s) => `<span class="nchip" data-roll="${esc(s.roll)}">${esc(s.name)} <b>${fmt(s.best5)}</b></span>`).join("") || `<span class="muted">Nobody yet.</span>`}</div></div>
    </div>`;
}
const namesChips = (names) => names.length ? `<div class="name-chips">${names.map((n) => `<span class="nchip">${esc(n)}</span>`).join("")}</div>` : `<p class="muted">Nobody.</p>`;

// ---------------------------------------------------------------- students
function studentsHtml(b) {
  const streams = [...new Set(b.students.map((s) => s.stream).filter(Boolean))];
  return `<div id="stu-detail"></div>
    <div class="card"><div class="card-head"><h3>Students <span class="muted small" id="stu-count"></span></h3>
      <div class="row">
        <input type="search" id="stu-q" placeholder="Search a name or roll no…" value="${esc(V.q)}" style="max-width:240px">
        ${streams.length ? `<select class="sel-sm" id="stu-stream" style="width:auto"><option value="">All streams</option>${streams.map((s) => `<option ${s === V.stream ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>` : ""}
        <select class="sel-sm" id="stu-res" style="width:auto"><option value="">Every result</option><option value="PASS" ${V.result === "PASS" ? "selected" : ""}>Passed</option><option value="COMP" ${V.result === "COMP" ? "selected" : ""}>Compartment</option></select>
        <select class="sel-sm" id="stu-sort" style="width:auto">${[["rank", "Rank"], ["roll", "Roll no"], ["name", "Name"]].map(([k, l]) => `<option value="${k}" ${V.sort === k ? "selected" : ""}>Sort: ${l}</option>`).join("")}</select>
      </div></div>
      <div class="table-wrap" style="max-height:640px"><table class="t stu-t"><thead><tr><th class="num">Rank</th><th>Name</th>${streams.length ? "<th>Stream</th>" : ""}<th>Marks (grade)</th><th class="num">Best 5 %</th><th class="num">All %</th><th>Result</th></tr></thead>
        <tbody id="stu-body"></tbody></table></div>
      <div class="t-scroll-note">Click a student for their card. Faded mark = not counted in the best 5. Red = did not pass (CBSE grade E).</div></div>`;
}

const markTone = (x) => x.grade === "E" ? "fail" : x.marks === null ? "" : x.marks >= 90 ? "hi" : x.marks >= 75 ? "good" : x.marks >= 60 ? "mid" : "low";

function stuRows(b) {
  const q = V.q.trim().toLowerCase();
  let rows = b.students.filter((s) => (!q || s.name.toLowerCase().includes(q) || s.roll.includes(q))
    && (!V.stream || s.stream === V.stream) && (!V.result || (V.result === "COMP" ? /^COMP/.test(s.result) : s.result === V.result)));
  const by = { rank: (a, c) => (a.rank ?? 1e9) - (c.rank ?? 1e9) || a.roll.localeCompare(c.roll), roll: (a, c) => a.roll.localeCompare(c.roll),
    name: (a, c) => a.name.localeCompare(c.name) }[V.sort];
  rows = rows.sort(by);
  const hasStream = b.students.some((s) => s.stream);
  $("#stu-count").textContent = `(${rows.length}${rows.length !== b.students.length ? ` of ${b.students.length}` : ""})`;
  $("#stu-body").innerHTML = rows.map((s) => `<tr data-roll="${esc(s.roll)}" tabindex="0" class="${s.roll === V.stu ? "sel" : ""}">
      <td class="num"><b>${s.rank ? (MEDAL[s.rank] || s.rank) : "–"}</b></td>
      <td><b>${esc(s.name)}</b><div class="tiny muted">${esc(s.roll)}${s.gender ? ` · ${s.gender === "F" ? "Girl" : s.gender === "M" ? "Boy" : esc(s.gender)}` : ""}</div></td>
      ${hasStream ? `<td><span class="small">${esc(s.stream)}</span><div class="tiny muted">${esc(s.combo)}</div></td>` : ""}
      <td><div class="mchips">${s.subjects.map((x) => `<span class="mchip ${markTone(x)} ${s.best5 !== null && x.marks !== null && !s.best5_subjects.includes(x.code) ? "dropped" : ""}"
          title="${esc(x.name)}: ${x.marks ?? "–"} · grade ${esc(x.grade || "–")}">${esc(x.name)} <b>${x.marks ?? "–"}</b><i>${esc(x.grade || "")}</i></span>`).join("")}</div></td>
      <td class="num"><b>${pct(s.best5)}</b></td><td class="num">${pct(s.pct_all)}</td><td>${resultBadge(s.result)}</td></tr>`).join("")
    || `<tr><td colspan="7" class="muted center">Nobody matches.</td></tr>`;
}

function stuCard(b, roll) {
  const s = b.students.find((x) => x.roll === roll);
  const box = $("#stu-detail");
  if (!s || !box) { if (box) box.innerHTML = ""; return; }
  const avg = Object.fromEntries(b.subjects.map((x) => [x.code, x.avg]));
  const rows = s.subjects.filter((x) => x.marks !== null).map((x) => ({ ...x, avg: avg[x.code], diff: avg[x.code] === null ? null : x.marks - avg[x.code] }));
  const best = rows.filter((r) => r.diff !== null).sort((a, c) => c.diff - a.diff);
  const ranked = b.students.filter((x) => x.rank).length;
  const above = s.rank ? Math.round(((ranked - s.rank) / Math.max(1, ranked - 1)) * 100) : null;
  box.innerHTML = `<div class="card stu-card"><div class="card-head"><div><h2 style="margin:0">${esc(s.name)}</h2>
        <div class="muted small">Roll ${esc(s.roll)}${s.gender ? ` · ${s.gender === "F" ? "Girl" : "Boy"}` : ""}${s.stream ? ` · ${esc(s.stream)} (${esc(s.combo)})` : ""}${s.section ? ` · Section ${esc(s.section)}` : ""}</div></div>
      <button class="btn btn-ghost btn-sm" id="stu-close">✕ Close</button></div>
    <div class="stu-kpis"><div><b>${s.rank ? `${MEDAL[s.rank] || ""} ${s.rank}` : "–"}</b><span>Rank of ${ranked}</span></div>
      <div><b>${pct(s.best5)}</b><span>Best 5 %</span></div><div><b>${pct(s.pct_all)}</b><span>All subjects %</span></div>
      <div><b>${above === null ? "–" : above + "%"}</b><span>of students below</span></div><div>${resultBadge(s.result)}<span>Result</span></div></div>
    <div class="grid g2" style="margin-top:14px"><div class="chart-box" style="height:${80 + rows.length * 34}px"><canvas id="stu-chart"></canvas></div>
      <div>${table(["Subject", "Marks", "Grade", "School avg", "vs avg", "Best 5"], rows.map((r) => [r.name, r.marks, r.grade || "–", r.avg === null ? "–" : fmt(r.avg),
        { html: r.diff === null ? "–" : `<b style="color:${r.diff >= 0 ? "var(--green)" : "var(--amber)"}">${r.diff >= 0 ? "+" : ""}${fmt(r.diff)}</b>` },
        s.best5_subjects.includes(r.code) ? "✓" : ""]), { numeric: [1, 3, 4] })}
      ${best.length > 1 ? `<p class="small" style="margin:10px 0 0">Strongest compared with the school: <b>${esc(best[0].name)}</b> (${best[0].diff >= 0 ? "+" : ""}${fmt(best[0].diff)}). Weakest: <b>${esc(best[best.length - 1].name)}</b> (${best[best.length - 1].diff >= 0 ? "+" : ""}${fmt(best[best.length - 1].diff)}).</p>` : ""}</div></div></div>`;
  chart($("#stu-chart"), "bar", rows.map((r) => r.name), [
    { label: s.name, data: rows.map((r) => r.marks), backgroundColor: cssVar("--blue"), borderRadius: 5 },
    { label: "School average", data: rows.map((r) => r.avg), backgroundColor: "#9DB4C7", borderRadius: 5 }],
    { indexAxis: "y", x: { max: 100 }, y: { grid: { display: false } } });
  $("#stu-close").addEventListener("click", () => { V.stu = null; stuCard(b, null); $$("#stu-body tr.sel").forEach((t) => t.classList.remove("sel")); });
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- subjects
function subjectsHtml(b) {
  const rows = b.subjects.map((s) => [s.name, s.candidates, { html: `<b>${pct(s.avg)}</b>` }, pct(s.median), s.q1 === null ? "–" : `${fmt(s.q1, 0)}–${fmt(s.q3, 0)}`,
    s.max ?? "–", s.min ?? "–", s.above90, s.centums || "", { html: s.failed ? `<b style="color:var(--red)">${s.failed}</b>` : "0" },
    b.meta.graded ? pct(s.pi) : "–", { html: s.vs_own === null ? "–" : `<b style="color:${s.vs_own >= 0 ? "var(--green)" : "var(--amber)"}">${s.vs_own >= 0 ? "+" : ""}${fmt(s.vs_own)}</b>` }]);
  return `<div class="grid g2">
    <div class="card span2"><div class="card-head"><h3>Every student's mark</h3><span class="tiny muted">one dot = one student · colour = CBSE grade · hover a dot for the name</span></div>
      <div class="chart-box" style="height:${110 + b.subjects.length * 38}px"><canvas id="bs-strip"></canvas></div></div>
    <div class="card"><h3>Harder or easier for the same students ${qmark("board-vs-own")}</h3><div class="chart-box"><canvas id="bs-own"></canvas></div>
      <p class="tiny muted" style="margin:8px 0 0">Each student's mark in the subject minus their own average in their other subjects, averaged. Plus = they scored more here than elsewhere. Fairer than plain averages, because every subject has different students.</p></div>
    <div class="card"><h3>${b.meta.graded ? "CBSE grades in each subject" : "Marks in each subject"}</h3><div class="chart-box"><canvas id="bs-gr"></canvas></div>
      ${b.meta.graded ? `<p class="tiny muted" style="margin:8px 0 0">CBSE gives grades by position among all its students in that subject, so the same mark can be a different grade in another subject.</p>` : ""}</div>
    <div class="card span2"><h3>Subjects</h3>${table(["Subject", "Students", "Average", "Middle mark", "Middle half", "Highest", "Lowest", "90+", "100s", "Did not pass", "PI", "vs own other subjects"], rows, { numeric: [1, 2, 3, 5, 6, 7, 8, 9, 10, 11] })}
      <p class="tiny muted" style="margin:8px 0 0">Middle mark = half the students scored more, half less. Middle half = the marks of the middle 50% of students. PI = (8×A1 + 7×A2 + … + 1×D2) × 100 ÷ (8 × students), CBSE's grade score.</p></div>
  </div>`;
}

// ---------------------------------------------------------------- streams
function streamsHtml(b) {
  return `<div class="grid g3">${b.streams.map((s) => `<div class="card stream-card"><div class="card-head"><h3>${esc(s.stream)}</h3><span class="chip-s">${s.n} students</span></div>
      <div class="stu-kpis three"><div><b>${pct(s.avg_best5)}</b><span>Avg best 5 %</span></div><div><b>${pct(s.pass_pct)}</b><span>Pass %</span></div><div><b>${s.above90}</b><span>90% or more</span></div></div>
      <div class="tiny muted" style="margin:12px 0 6px">TOP 3</div>
      ${s.top.map((t, i) => `<div class="st-row" data-roll="${esc(t.roll)}"><span>${MEDAL[i + 1]}</span><b>${esc(t.name)}</b><span class="muted tiny">${esc(t.combo)}</span><span class="pv">${fmt(t.best5)}</span></div>`).join("")}
      <div class="tiny muted" style="margin:12px 0 6px">SUBJECT GROUPS</div><div class="name-chips">${s.combos.map(([c, n]) => `<span class="nchip">${esc(c)} <b>${n}</b></span>`).join("")}</div></div>`).join("")}</div>
    <div class="grid g2" style="margin-top:18px">
      <div class="card"><h3>Average best-5 % by stream</h3><div class="chart-box"><canvas id="bst-avg"></canvas></div></div>
      <div class="card"><h3>Best-5 % ranges in each stream</h3><div class="chart-box"><canvas id="bst-dist"></canvas></div></div></div>`;
}

// ---------------------------------------------------------------- teachers
function teachersHtml(b) {
  const t = b.teachers;
  if (!t || !t.cards.length) {
    return `<div class="card"><h3>Teachers ${qmark("teachers")}</h3><p class="muted">Add the teachers (name, subject, class ${esc((t && t.cls) || b.meta.cls || "")} and sections)
      and the class lists on the <a href="#/teachers">Teachers page</a> to see how each teacher's own students did in the boards.</p>
      <p class="small">The comparison is fair: each student's board mark in the subject is compared with <b>their own</b> other subjects, so a strong or weak section does not count for or against the teacher.</p></div>`;
  }
  const good = t.cards.filter((c) => c.fair.verdict === "Clear positive impact").length;
  const talk = t.cards.filter((c) => c.fair.verdict === "Worth a conversation").length;
  const p = t.placement || { placed: 0, total: 0 };
  const vcol = (v) => ({ "Clear positive impact": "b-ok", "Worth a conversation": "b-warn" })[v] || "b-info";
  return `<div class="grid g4">${kpi(t.cards.length, "Teacher cards", 0)}${kpi(good, "Clearly better", 0, "", "good")}${kpi(talk, "Worth a conversation", 0, "", "warn")}
      <div class="kpi"><div class="v">${p.placed}/${p.total}</div><div class="l">Students placed in a section</div></div></div>
    <div class="card" style="margin-top:18px"><div class="card-head"><h3>Each teacher's own students ${qmark("teachers")}</h3>
      <a class="btn btn-primary btn-sm" href="#/teachers" data-boardtab>Charts for every teacher →</a></div>
      ${table(["Subject", "Teacher", "Sections", "Students", "Average", "vs own other subjects", "vs other teachers", "Fair check"],
        t.cards.map((c) => [c.subject_name, c.name, (c.sections || []).join(", ") || t.cls, c.candidates, pct(c.avg),
          c.fair.vs_own === null ? "–" : fmt(c.fair.vs_own), c.fair.effect === null ? "–" : fmt(c.fair.effect),
          { html: `<span class="badge ${vcol(c.fair.verdict)}">${esc(c.fair.verdict)}</span>` }]), { numeric: [3, 4, 5, 6] })}
      ${!t.split ? `<p class="small muted" style="margin:10px 0 0">💡 Add the class lists on the Teachers page to see each teacher on their own sections.</p>` : ""}
      <p class="tiny muted" style="margin:8px 0 0">${esc(t.caution || "")}</p></div>`;
}

// ---------------------------------------------------------------- years, school vs board, checks
function yearsHtml(b) {
  const y = b.years;
  const name = Object.fromEntries(b.subjects.map((s) => [s.code, s.name]));
  return `<div class="grid g2"><div class="card"><h3>Pass % and average best 5 %</h3><div class="chart-box"><canvas id="by-line"></canvas></div></div>
      <div class="card"><h3>School</h3>${table(["Year", "Students", "Pass %", "Avg best 5 %", "School PI"], y.summary.map((r) => [r[0], r[4], pct(r[1]), pct(r[2]), pct(r[3])]), { numeric: [1, 2, 3, 4] })}</div>
      <div class="card span2"><h3>Average marks by subject</h3>${table(["Subject", ...y.years], y.subjects.map((s) => [name[s.code] || s.code, ...s.values.map((v) => pct(v[1]))]), { numeric: y.years.map((_, i) => i + 1) })}</div></div>`;
}

function linkHtml(b) {
  const l = b.link;
  return `<div class="card"><h3>School exams vs board</h3><p class="muted small">${l.linked_students} students linked by board roll no / admission no${l.by_name ? ` (${l.by_name} by name - please check)` : ""}. Gap = board marks − school exam %.</p>
    ${table(["Subject", "Students", "Average gap (marks)"], l.by_subject.map((x) => [x.name, x.n, { html: `<b style="color:${x.avg_gap >= 0 ? "var(--green)" : "var(--amber)"}">${x.avg_gap >= 0 ? "+" : ""}${fmt(x.avg_gap)}</b>` }]), { numeric: [1, 2] })}</div>`;
}

function checksHtml(b) {
  const t = b.totals || {};
  const line = (what, read, says) => [what, read, says ?? "not given", { html: says === undefined || says === null || says === read ? `<b style="color:var(--green)">✔ matches</b>` : `<b style="color:var(--red)">✗ check</b>` }];
  const intern = Object.entries(b.internal || {});
  return `<div class="grid g2">
    <div class="card"><h3>Every student accounted for</h3>${table(["What", "Read", "The file says", ""], [line("Students", b.candidates, t.candidates), line("Passed", b.passed, t.pass), line("Compartment", b.comp, t.comp)], { numeric: [1, 2] })}</div>
    <div class="card"><h3>From the file</h3>${table(["", ""], [["Exam", b.meta.title], ["School", `${b.meta.school_code || ""} ${titleCase(b.meta.school_name || "")}`], ["Region", b.meta.region || "–"], ["Result date", b.meta.date || "–"], ["File", b.meta.file]], { wrap: [1] })}</div>
    <div class="card span2"><h3>Notes and checks</h3>${b.issues.length ? table(["", "Details"], b.issues.map((i) => [{ html: `<span class="badge ${i.severity === "info" ? "b-info" : i.severity === "warning" ? "b-warn" : "b-err"}">${({ error: "Problem", warning: "Check", info: "Note" })[i.severity] || esc(i.severity)}</span>` }, i.message]), { wrap: [1] }) : `<p class="muted">Nothing to report.</p>`}</div>
    ${intern.length ? `<div class="card span2"><h3>Internal grades (GR1, GR2, GR3 as printed)</h3>${table(["", ...GRADES.slice(0, 8)], intern.map(([k, g]) => [`GR${+k + 1}`, ...GRADES.slice(0, 8).map((x) => g[x] || 0)]), { numeric: [1, 2, 3, 4, 5, 6, 7, 8] })}</div>` : ""}
  </div>`;
}

// ================================================================== charts for the open tab
function drawTab(b) {
  const box = $("#b-body");
  if (!box) return;
  box.innerHTML = body(b);
  countUp(box);
  const subs = b.subjects;
  const blue = cssVar("--blue");
  if (V.tab === "overview") {
    chart($("#bc-dist"), "bar", b.distribution.map((d) => d[0]), [{ data: b.distribution.map((d) => d[1]), backgroundColor: cssVar("--blue-2"), borderRadius: 6 }],
      { tooltip: { label: (c) => ` ${c.parsed.y} students` } });
    const sorted = [...subs].filter((s) => s.avg !== null).sort((a, c) => c.avg - a.avg);
    chart($("#bc-avg"), "bar", sorted.map((s) => s.short), [{ data: sorted.map((s) => s.avg), backgroundColor: blue, borderRadius: 6 }],
      { indexAxis: "y", x: { max: 100 }, y: { grid: { display: false } }, tooltip: { label: (c) => ` average ${c.parsed.x.toFixed(1)} · ${sorted[c.dataIndex].candidates} students` } });
    const others = b.candidates - b.passed - b.comp;
    chart($("#bc-res"), "doughnut", ["Passed", "Compartment", ...(others ? ["Other"] : [])], [{ data: [b.passed, b.comp, ...(others ? [others] : [])],
      backgroundColor: [cssVar("--green"), cssVar("--red"), "#9DB4C7"], borderWidth: 0 }], { extra: { cutout: "68%", plugins: { legend: { position: "bottom" } } } });
    const g = (b.gender || []).filter((x) => x.gender !== "?");
    const grp = [...(b.streams.length > 1 ? b.streams.map((s) => ({ l: s.stream, n: s.n, v: s.avg_best5 })) : []), ...(g.length > 1 ? g.map((x) => ({ l: x.gender, n: x.n, v: x.avg_best5 })) : [])];
    chart($("#bc-grp"), "bar", grp.map((x) => `${x.l} (${x.n})`), [{ data: grp.map((x) => x.v), backgroundColor: grp.map((_, i) => BARS()[i % 7]), borderRadius: 6 }],
      { indexAxis: "y", x: { min: Math.max(0, Math.floor(Math.min(...grp.map((x) => x.v ?? 100)) / 10) * 10 - 10), max: 100 }, y: { grid: { display: false } } });
  } else if (V.tab === "subjects") {
    strip(b);
    const own = subs.filter((s) => s.vs_own !== null && s.vs_own_n >= 3).sort((a, c) => c.vs_own - a.vs_own);
    chart($("#bs-own"), "bar", own.map((s) => s.short), [{ data: own.map((s) => s.vs_own), backgroundColor: own.map((s) => s.vs_own >= 0 ? blue : "#F2A93B"), borderRadius: 5 }],
      { indexAxis: "y", x: { grid: { color: cssVar("--line") } }, y: { grid: { display: false } },
        tooltip: { label: (c) => ` ${c.parsed.x >= 0 ? "+" : ""}${c.parsed.x.toFixed(1)} marks vs their other subjects (${own[c.dataIndex].vs_own_n} students)` } });
    const graded = b.meta.graded;
    const cats = graded ? GRADES : (subs[0] ? subs[0].bands.map((x) => x[0]) : []);
    const val = (s, g) => graded ? (s.grades[g] || 0) : ((s.bands.find((x) => x[0] === g) || [0, 0])[1]);
    chart($("#bs-gr"), "bar", subs.map((s) => s.short), cats.map((g, i) => ({ label: g, data: subs.map((s) => val(s, g) * 100 / Math.max(1, s.candidates)), backgroundColor: graded ? GRADE_COL[g] : BAND_RAMP[i % 7] })),
      { indexAxis: "y", extra: { scales: { x: { stacked: true, max: 100, grid: { color: cssVar("--line") } }, y: { stacked: true, grid: { display: false } } } },
        tooltip: { label: (c) => ` ${c.dataset.label}: ${c.parsed.x.toFixed(0)}%` } });
  } else if (V.tab === "streams") {
    const st = b.streams;
    chart($("#bst-avg"), "bar", st.map((s) => `${s.stream} (${s.n})`), [{ data: st.map((s) => s.avg_best5), backgroundColor: st.map((_, i) => BARS()[i % 7]), borderRadius: 6 }], { y: { max: 100 } });
    const bins = b.distribution.map((d) => d[0]);
    const edges = { "95-100": [95, 101], "90-95": [90, 95], "80-90": [80, 90], "70-80": [70, 80], "60-70": [60, 70], "Below 60": [0, 60] };
    chart($("#bst-dist"), "bar", st.map((s) => s.stream), bins.map((lab, i) => ({ label: lab, backgroundColor: BAND_RAMP[i % 7],
      data: st.map((s) => { const ss = b.students.filter((x) => x.stream === s.stream && x.best5 !== null); const [lo, hi] = edges[lab] || [0, 0];
        return ss.length ? ss.filter((x) => x.best5 >= lo && x.best5 < hi).length * 100 / ss.length : 0; }) })),
      { extra: { scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, max: 100, grid: { color: cssVar("--line") } } } },
        tooltip: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y.toFixed(0)}% of the stream` } });
  } else if (V.tab === "years") {
    const y = b.years;
    chart($("#by-line"), "line", y.summary.map((r) => r[0]), [
      { label: "Pass %", data: y.summary.map((r) => r[1]), borderColor: cssVar("--green"), backgroundColor: cssVar("--green"), tension: .3, pointRadius: 5 },
      { label: "Avg best 5 %", data: y.summary.map((r) => r[2]), borderColor: blue, backgroundColor: blue, tension: .3, pointRadius: 5 }], { y: { max: 100 } });
  } else if (V.tab === "students") {
    stuRows(b);
    if (V.stu) stuCard(b, V.stu);
  }
}

// every student's mark in every subject: one row per subject, one dot per student, coloured by CBSE grade
function strip(b) {
  const subs = b.subjects;
  const idx = Object.fromEntries(subs.map((s, i) => [s.code, i]));
  const jitter = (roll, code) => { let h = 0; for (const ch of roll + code) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return ((h % 1000) / 1000 - .5) * .62; };
  const graded = b.meta.graded;
  const groups = graded ? GRADES : ["90+", "75-89", "60-74", "33-59", "Below 33"];
  const groupOf = (x) => graded ? x.grade : x.marks >= 90 ? "90+" : x.marks >= 75 ? "75-89" : x.marks >= 60 ? "60-74" : x.marks >= 33 ? "33-59" : "Below 33";
  const colors = graded ? GRADE_COL : { "90+": "#1E8E5A", "75-89": "#06A7E7", "60-74": "#9FDCF5", "33-59": "#F2A93B", "Below 33": "#C0392B" };
  const data = {};
  for (const s of b.students) for (const x of s.subjects) {
    if (x.marks === null || !(x.code in idx)) continue;
    (data[groupOf(x)] = data[groupOf(x)] || []).push({ x: x.marks, y: idx[x.code] + jitter(s.roll, x.code), n: s.name, sub: x.name, g: x.grade });
  }
  const sets = groups.filter((g) => data[g]).map((g) => ({ label: g, data: data[g], backgroundColor: colors[g] || "#9DB4C7", borderColor: "rgba(0,0,0,.12)", borderWidth: .5, pointRadius: 4.2, pointHoverRadius: 7 }));
  const avgs = subs.map((s, i) => s.avg === null ? null : { x: s.avg, y: i });
  sets.push({ label: "Average", type: "scatter", data: avgs.filter(Boolean), pointStyle: "line", rotation: 90, pointRadius: 13, borderWidth: 3, borderColor: cssVar("--navy"), backgroundColor: cssVar("--navy") });
  chart($("#bs-strip"), "scatter", [], sets, {
    x: { min: Math.max(0, Math.floor(Math.min(...subs.map((s) => s.min ?? 100)) / 10) * 10 - 5), max: 100, grid: { color: cssVar("--line") }, title: { display: true, text: "Marks" } },
    y: { reverse: true, min: -.6, max: subs.length - .4, beginAtZero: false, grid: { display: false }, afterBuildTicks: (ax) => { ax.ticks = subs.map((_, i) => ({ value: i })); },
         ticks: { autoSkip: false, callback: (v) => (subs[v] ? subs[v].short : "") } },
    tooltip: { label: (c) => c.raw.n ? ` ${c.raw.n}: ${c.raw.sub} ${c.raw.x}${c.raw.g ? ` (${c.raw.g})` : ""}` : ` average ${c.raw.x.toFixed(1)}` },
    extra: { plugins: { legend: { display: true, position: "bottom", labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } } } } });
}

// ================================================================== files + events
async function addFiles(files) {
  busy = true; rerender();
  const before = new Set(((S.board && S.board.boards) || []).map((x) => x.label));
  for (const f of files) {
    try {
      await addAny(f, { hint: "board" });
    } catch (e) { toast(`Could not read ${esc(f.name)}: ${esc(e.message)}`, "err", 8000); }
  }
  S.files = null;
  try { S.board = await engine.call("board_summary"); } catch (e) { S.board = null; }
  const fresh = S.board && S.board.boards.find((x) => !before.has(x.label));
  if (fresh) { V.key = fresh.key; V.tab = "overview"; V.stu = null; }
  busy = false; rerender();
}

function openStudent(b, roll) {
  V.stu = roll; V.q = ""; V.tab = "students";
  rerender();
}

export function mount(root) {
  if (!S.engineReady) return;
  if (!S.board) { engine.call("board_summary").then((b) => { S.board = b; rerender(); }).catch(() => {}); }
  const inp = $("#b-in");
  inp && inp.addEventListener("change", () => inp.files.length && addFiles([...inp.files]));
  const drop = $("#bdrop") || root;
  if (drop) {
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { if (!e.dataTransfer || ![...e.dataTransfer.types].includes("Files")) return; e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { if (ev === "dragleave" && drop.contains(e.relatedTarget)) return; e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => e.dataTransfer.files.length && addFiles([...e.dataTransfer.files]));
  }
  const sm = $("#b-sample");
  sm && sm.addEventListener("click", async () => {
    busy = true; rerender();
    try { await engine.call("add_sample_gazette"); S.board = await engine.call("board_summary"); V.key = null; V.tab = "overview"; toast("Made-up board results loaded (fake school, fake names).", "ok"); }
    catch (e) { toast(esc(e.message), "err"); }
    busy = false; rerender();
  });
  const b = cur();
  if (!b) return;
  V.key = b.key;
  S.bCls = b.meta.cls || "";
  if (!tabs(b).some(([k]) => k === V.tab)) V.tab = "overview";
  const dl = $("#b-dl");
  dl && dl.addEventListener("click", async () => {
    const label = dl.textContent;
    dl.disabled = true; dl.innerHTML = `<span class="spinner"></span> Building…`;
    try {
      const cls = b.meta.cls || "";
      const bytes = await engine.bytes("board_workbook_bytes", cls, b.key);
      const name = await engine.value("board_workbook_name", cls, b.key);
      download(bytes, name, XLSX);
      toast("Board workbook downloaded ✓", "ok");
    } catch (e) { toast(esc(e.message), "err", 9000); }
    dl.disabled = false; dl.textContent = label;
  });
  drawTab(b);
  root.addEventListener("click", (e) => {
    const t = e.target.closest("[data-btab],[data-bkey],[data-roll],[data-boardtab]");
    if (!t || !root.contains(t)) return;
    if (t.dataset.bkey) { V.key = t.dataset.bkey; V.stu = null; rerender(); return; }
    if (t.dataset.btab) {
      V.tab = t.dataset.btab;
      $$("#b-tabs button").forEach((x) => x.classList.toggle("on", x.dataset.btab === V.tab));
      drawTab(b);
      return;
    }
    if (t.hasAttribute("data-boardtab")) { S.tTab = "board"; return; }
    if (t.dataset.roll) {
      if (V.tab === "students") {
        V.stu = t.dataset.roll;
        $$("#stu-body tr").forEach((x) => x.classList.toggle("sel", x.dataset.roll === V.stu));
        stuCard(b, V.stu);
      } else openStudent(b, t.dataset.roll);
    }
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches && e.target.matches("#stu-body tr[data-roll]")) e.target.click();
  });
  root.addEventListener("input", (e) => {
    if (e.target.id === "stu-q") { V.q = e.target.value; stuRows(b); }
  });
  root.addEventListener("change", (e) => {
    const id = e.target.id;
    if (id === "stu-stream") V.stream = e.target.value;
    else if (id === "stu-res") V.result = e.target.value;
    else if (id === "stu-sort") V.sort = e.target.value;
    else return;
    stuRows(b);
  });
}
