// Teachers: who teaches what, the class lists (which section each student is in), and how each teacher's own
// students did - in the school exams and in the board results - with charts.
import * as engine from "../engine.js";
import { S, LS } from "../state.js";
import { $, $$, esc, fmt, toast, chart, cssVar, table } from "../ui.js";
import { qmark } from "../explain.js";
import { addAny } from "../intake.js";

const rerender = () => window.__render();
let analysis = null;       // school-exam teacher analysis
let analysisFor = null;
let boardAn = null;        // board-results teacher analysis
let boardAnCls = "";       // ...for the class picked on the Board page
let editing = null;        // index of the teacher being edited
let busy = "";

export function loadSaved() { return LS.get("rdps.teachers", []); }

export async function syncTeachers() {
  if (!S.engineReady) return;
  const out = await engine.call("set_teachers", JSON.stringify(loadSaved()));
  S.teacherLists = out;
  S.board = null;                         // the board page shows teachers too
  boardAn = null;
}

function save(list) {
  LS.set("rdps.teachers", list);
  analysis = null;
  return syncTeachers();
}

export function resetAnalysis() { analysis = null; boardAn = null; }

function classOptions() {
  // classes + sections from the uploaded marks and the class lists, else the classes in settings
  const map = new Map();
  if (S.summary) S.summary.classes.forEach((c) => map.set(c.cls, new Set(c.sections)));
  (S.classLists || []).forEach((l) => l.sections.forEach((k) => {
    const [c, s] = k.split("-");
    if (!map.has(c)) map.set(c, new Set());
    if (s) map.get(c).add(s);
  }));
  for (const c of Object.keys(S.settings.rules.classes)) if (!map.has(c)) map.set(c, new Set());
  const order = Object.keys(S.settings.rules.classes);
  return [...map.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([cls, secs]) => ({ cls, sections: [...secs].sort() }));
}

const initials = (n) => (n.replace(/^(mr|mrs|ms|miss|dr)\.?\s+/i, "").trim()[0] || "?").toUpperCase();

// ------------------------------------------------------------------ page
export function html() {
  if (!S.engineReady || !S.settings) return `<div class="page-head"><div><h1>Teachers</h1><p>Getting ready…</p></div></div>`;
  const typed = loadSaved();
  const fromFiles = (S.teacherLists && S.teacherLists.from_files) || [];
  const subjects = S.settings.subjects;
  const cur = editing !== null ? typed[editing] : { name: "", subject: "", classes: "" };
  const picked = new Set(String(cur.classes || "").split(/[,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean));
  const opts = classOptions();
  const subjName = (code) => (subjects.find((s) => s.code === code) || {}).name || code;
  const person = (name, sub, extra, btns) => `<div class="file-row t-row"><span class="t-ava">${esc(initials(name))}</span>
      <div style="flex:1;min-width:0"><div class="fname">${esc(name)}</div><div class="tiny muted">${esc(sub)} · ${esc(extra)}</div></div>${btns}</div>`;
  const list = typed.map((t, i) => person(t.name, subjName(t.subject), t.classes,
    `<button class="btn btn-ghost btn-sm" data-edit="${i}">Edit</button><button class="btn btn-ghost btn-sm" data-del="${i}">Remove</button>`)).join("");
  const filesList = fromFiles.map((t) => person(t.name, t.subject_text || subjName(t.subject), `${t.classes.join(", ") || "no classes"} · from ${t.source || "a file"}`,
    `<button class="btn btn-ghost btn-sm" data-delfile="${esc(t.name)}" data-subj="${esc(t.subject || t.subject_text)}">Remove</button>`)).join("");
  const lists = S.classLists || [];
  const listRows = lists.map((l) => `<div class="file-row"><span class="ficon">${esc((l.file.split(".").pop() || "").toUpperCase().slice(0, 4))}</span>
      <div style="flex:1;min-width:0"><div class="fname">${esc(l.file)}</div>
        <div class="tiny muted">${l.count} students · ${l.sections.length ? esc(l.sections.join(", ")) : "class not known"}</div></div>
      ${l.needs ? `<span class="badge b-weak">Which class?</span>` : `<span class="badge b-strong">✓ ${esc(l.sections.join(", "))}</span>`}
      <input class="sel-sm" style="width:84px" value="${esc(l.cls)}${l.section ? "-" + esc(l.section) : ""}" data-clfix="${l.id}" placeholder="e.g. XII-A" title="Class and section of this list">
      <button class="btn btn-ghost btn-sm" data-cldel="${l.id}">Remove</button></div>`).join("");
  return `<div class="page-head"><div><h1>Teachers ${qmark("teachers")}</h1>
      <p>Tell the tool who teaches which subject in which sections. It then shows how each teacher's own students did - compared fairly with the same students' other subjects - for the school exams and the board results. It all goes into the Excel files too.</p></div></div>
    <div class="t-steps">
      <div class="t-step ${typed.length + fromFiles.length ? "done" : ""}"><b>1</b><div><h4>Add the teachers</h4><span>name · subject · sections</span></div></div>
      <div class="t-step ${lists.length ? "done" : ""}"><b>2</b><div><h4>Add the class lists</h4><span>for board results: who is in which section</span></div></div>
      <div class="t-step ${S.summary || boardAn ? "done" : ""}"><b>3</b><div><h4>See each teacher</h4><span>charts below · Excel file</span></div></div>
    </div>
    <div class="grid g3">
      <div class="card"><h3>${editing !== null ? "Change teacher" : "Add a teacher"}</h3>
        <div class="stack">
          <label class="field"><span>Name</span><input type="text" id="t-name" value="${esc(cur.name)}" placeholder="e.g. Mrs. Kavita Sharma"></label>
          <label class="field"><span>Subject</span><select id="t-subj"><option value="">Pick the subject…</option>
            ${subjects.map((s) => `<option value="${s.code}" ${s.code === cur.subject ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
          <div class="field"><span>Classes and sections they teach</span>
            <div class="class-pick">${opts.map((c) => {
              const secs = c.sections.length ? c.sections : [""];
              return `<div class="cp-row"><b>${esc(c.cls)}</b>${secs.map((s) => {
                const key = s ? `${c.cls}-${s}` : c.cls;
                return `<label class="cp"><input type="checkbox" data-cp="${key}" ${picked.has(key) ? "checked" : ""}><span>${esc(s || "all")}</span></label>`;
              }).join("")}</div>`;
            }).join("")}</div>
            <input type="text" id="t-classes" value="${esc(cur.classes)}" placeholder="or type: XII-A, XII-B" style="margin-top:8px"></div>
          <div class="row"><button class="btn btn-primary" id="t-save">${editing !== null ? "Save" : "Add teacher"}</button>
            ${editing !== null ? `<button class="btn btn-ghost" id="t-cancel">Cancel</button>` : ""}</div>
        </div></div>
      <div class="card span2"><div class="card-head"><h3>Teachers (${typed.length + fromFiles.length})</h3>
          <div class="row"><span class="muted small">Kept in this browser. A “Teachers” sheet in an uploaded file is read too.</span>
          ${typed.length + fromFiles.length ? `<button class="btn btn-danger btn-sm" id="t-clear">Remove all</button>` : ""}</div></div>
        ${list || filesList ? `<div class="stack t-list">${list}${filesList}</div>` : `<div class="empty muted">No teachers yet. Add one on the left - for example Physics, XII-A and XII-B.</div>`}
      </div>
    </div>
    <div class="card" style="margin-top:18px"><div class="card-head"><div><h3>Class lists ${qmark("class-lists")}</h3>
        <div class="muted small">A roll-number list for each section (PDF or Excel). The board results don't say who was in which section - the class list does, so every teacher gets only their own students. Students are matched by admission number, or by name.</div></div>
        <div class="row"><label class="btn btn-primary btn-sm" style="cursor:pointer">Add class lists<input type="file" id="cl-in" multiple accept=".pdf,.xlsx,.xlsm,.xls,.csv,.txt" hidden></label>
          <button class="btn btn-soft btn-sm" id="t-demo">Try a made-up example</button></div></div>
      ${busy ? `<div class="note"><span class="spinner" style="color:var(--blue)"></span> ${esc(busy)}</div>` : ""}
      ${lists.length ? `<div class="stack">${listRows}</div>` : `<div class="empty muted small">No class lists yet. Not needed for the school exams if their files already have a Section column.</div>`}
    </div>
    <div id="t-analysis" style="margin-top:22px"><div class="card"><div class="skeleton" style="height:120px"></div></div></div>`;
}

// ------------------------------------------------------------------ analysis (both kinds)
const VERDICT_CLS = { "Clear positive impact": "b-strong", "Worth a conversation": "b-weak", "No clear difference": "b-track" };
function verdict(v) { return `<span class="badge ${VERDICT_CLS[v] || "b-leave"}">${esc(v || "–")}</span>`; }
function signed(v, unit = "") {
  if (v === null || v === undefined) return "–";
  const col = v > 0.05 ? "var(--green)" : v < -0.05 ? "var(--red)" : "inherit";
  return `<b style="color:${col}">${v > 0 ? "+" : ""}${fmt(v)}${unit}</b>`;
}
const verdictColor = (v) => ({ "Clear positive impact": cssVar("--green"), "Worth a conversation": cssVar("--amber"), "No clear difference": cssVar("--blue") }[v] || "#9DB4C7");

/** One line anyone can read. */
function headline(c, kind) {
  const f = c.fair || {};
  const subj = esc(c.subject_name);
  const unit = kind === "board" ? "marks" : "points";
  const vsOwn = kind === "board" ? f.vs_own : (c.overall || {}).vs_own;
  if (f.effect !== null && f.effect !== undefined) {
    const e = Math.abs(f.effect);
    if (f.verdict === "No clear difference") return `Students did about as well as with the other ${subj} teachers (a difference of ${fmt(e)} ${unit} could be chance).`;
    return `Students did <b>${fmt(e)} ${unit} ${f.effect > 0 ? "better" : "lower"}</b> in ${subj} than with the other ${subj} teachers, compared with their own other subjects.`;
  }
  if (f.verdict === "Only teacher of this subject" && vsOwn !== null && vsOwn !== undefined)
    return `The only ${subj} teacher here. Students scored ${fmt(Math.abs(vsOwn))} ${unit} ${vsOwn >= 0 ? "more" : "less"} in ${subj} than in their other subjects (the paper and the teaching together).`;
  if (f.verdict === "Not enough data") return `Too few students (${f.n}) for a fair comparison yet.`;
  return "";
}

function kpis(c, kind) {
  const k = (v, l, p = 1) => `<div class="t-kpi"><b>${v === null || v === undefined ? "–" : fmt(v, p)}</b><span>${l}</span></div>`;
  if (kind === "board") return k(c.candidates, "students", 0) + k(c.avg, "average") + k(c.max, "highest", 0) + k(c.above90, "90 or more", 0) + k(c.grade_e, "did not pass", 0);
  const o = c.overall || {};
  return k(c.students, "students", 0) + k(o.avg, "average %") + k(o.pass_pct, "pass %") + k(o.top, "highest %") + k(o.not_passed, "not passed", 0);
}

function cardHtml(c, k, kind) {
  const v = c.viz || { split: { better: 0, same: 0, worse: 0 }, points: [], bands: [], sections: [] };
  const secs = kind === "board" ? (c.sections.join(", ") || "whole class") : c.classes.join(", ");
  const hasPts = v.points && v.points.length;
  const school = kind !== "board" ? c.sections.filter((x) => !x.missing) : [];
  return `<div class="card t-card">
    <div class="t-head"><span class="t-ava big">${esc(initials(c.name))}</span>
      <div style="flex:1;min-width:0"><h3>${esc(c.name)}</h3><div class="muted small">${esc(c.subject_name)} · ${esc(secs)}${kind !== "board" && v.exam ? " · " + esc(v.exam) : ""}</div></div>
      ${verdict((c.fair || {}).verdict)}</div>
    <p class="t-line">${headline(c, kind)}</p>
    <div class="t-kpis">${kpis(c, kind)}</div>
    ${hasPts ? `<div class="t-charts">
      <div><h4>${v.bands_are === "grades" ? "Grades" : "Marks"}</h4><div class="chart-box sm"><canvas id="tb-${kind}-${k}"></canvas></div></div>
      <div><h4>Compared with their other subjects</h4><div class="chart-box sm"><canvas id="ts-${kind}-${k}"></canvas></div></div>
      <div class="wide"><h4>Every student</h4><div class="chart-box"><canvas id="tp-${kind}-${k}"></canvas></div>
        <div class="tiny muted">Each dot is a student. Dots above the dashed line did better in ${esc(c.subject_name)} than in their other subjects.</div></div>
    </div>` : ""}
    ${v.sections && v.sections.length > 1 ? `<div class="t-secs">${v.sections.map((s) => `<div><b>${esc(s[0])}</b><span>${s[1]} students · average ${fmt(s[2])}${s[3] !== null && s[3] !== undefined ? ` · ${signed(s[3])} vs other subjects` : ""}</span></div>`).join("")}</div>` : ""}
    ${school.length && school.some((x) => x.by_exam.length > 1) ? `<h4 style="margin-top:12px">Across the exams</h4><div class="chart-box sm"><canvas id="tl-${k}"></canvas></div>` : ""}
    <details class="t-more"><summary>More details</summary>
      ${kind !== "board" ? table(["Class", "Exam", "Students", "Average %", "Pass %", "vs their other subjects", "vs the whole class"],
        school.flatMap((x) => x.by_exam.map((e) => [x.label, e.name, e.n, e.avg, e.pass_pct, { html: signed(e.vs_own) }, { html: signed(e.vs_class) }])),
        { numeric: [2, 3, 4, 5, 6], max: 60 }) : ""}
      <ul class="remarks small">${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></details>
  </div>`;
}

function overviewHtml(cards, kind, extra = "") {
  const clear = cards.filter((c) => (c.fair || {}).verdict === "Clear positive impact").length;
  const talk = cards.filter((c) => (c.fair || {}).verdict === "Worth a conversation").length;
  const studs = kind === "board" ? cards.reduce((s, c) => s + c.candidates, 0) : cards.reduce((s, c) => s + (c.students || 0), 0);
  const t = (v, l, cls = "") => `<div class="kpi ${cls}"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  return `<div class="grid g4">${t(cards.length, "teachers")}${t(studs, "students (counted for each teacher)")}${t(clear, "clearly better", "good")}${t(talk, "worth a conversation", "warn")}</div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>All teachers at a glance</h3>
      <span class="muted small">bar to the right = better than expected · to the left = lower</span></div>
      <div class="chart-box" style="height:${Math.max(180, 40 + cards.length * 34)}px"><canvas id="t-all-${kind}"></canvas></div>
      <div class="t-legend"><span><i style="background:${cssVar("--green")}"></i>Clearly better</span><span><i style="background:${cssVar("--blue")}"></i>About the same</span>
        <span><i style="background:${cssVar("--amber")}"></i>Worth a conversation</span><span><i style="background:#9DB4C7"></i>Only teacher of the subject (vs the students' other subjects)</span></div>
    </div>${extra}`;
}

function placementHtml(b) {
  const p = b.placement;
  if (!p) return "";
  if (!p.lists && !p.placed) return `<div class="note" style="margin-top:14px">💡 Add the <b>class lists</b> above to see each teacher on their own. The board results don't say which section a student was in.</div>`;
  const by = Object.entries(p.by).map(([k, v]) => `${v} by ${k}`).join(", ");
  const other = Object.keys(p.other_class || {});
  return `<div class="card" style="margin-top:16px"><h3>Who was in which section</h3>
    <p class="small"><b>${p.placed} of ${p.total}</b> students found in a section (${esc(by)}).
      ${other.length ? `<span class="muted">The class lists are for Class ${esc(other.join(", "))} and the results are Class ${esc(b.cls)} - only the sections were used.</span>` : ""}</p>
    ${p.check.length ? `<div class="note small"><b>Please check ${p.check.length} name${p.check.length > 1 ? "s" : ""}</b> matched by a similar spelling:
      ${p.check.map((x) => `“${esc(x.name)}” = “${esc(x.list_name)}” (${esc(x.section)})`).join("; ")}</div>` : ""}
    ${p.unplaced.length ? `<div class="note small" style="margin-top:8px"><b>${p.unplaced.length} not found</b> in the class lists: ${p.unplaced.slice(0, 30).map((x) => esc(x.name)).join(", ")}${p.unplaced.length > 30 ? "…" : ""}</div>` : ""}
  </div>`;
}

function analysisHtml() {
  const hasSchool = !!S.summary, hasBoard = !!boardAn;
  if (!hasSchool && !hasBoard) {
    return `<div class="note">The teacher results appear here once there are marks: make the results under <a href="#/school">School results</a>, or add the board results on the <a href="#/board">Board results</a> page.</div>`;
  }
  const tab = S.tTab && ((S.tTab === "board" && hasBoard) || (S.tTab === "school" && hasSchool)) ? S.tTab : (hasSchool ? "school" : "board");
  S.tTab = tab;
  const tabs = `<div class="seg t-tabs">${hasSchool ? `<button class="${tab === "school" ? "on" : ""}" data-ttab="school">School exams</button>` : ""}
    ${hasBoard ? `<button class="${tab === "board" ? "on" : ""}" data-ttab="board">Board results ${esc(boardAn.year || "")}</button>` : ""}</div>`;
  if (tab === "board") {
    const b = boardAn;
    const cards = b.cards;
    if (!cards.length) return tabs + `<div class="note" style="margin-top:14px">No teacher is set up for the board subjects yet. Add teachers above with class ${esc(b.cls)} (and their sections).</div>` + placementHtml(b);
    const bySubj = groupBy(cards, (c) => c.subject_name);
    return tabs + `<div class="note" style="margin:14px 0">⚖️ ${esc(b.caution)}</div>` + overviewHtml(cards, "board", placementHtml(b)) +
      Object.entries(bySubj).map(([s, cs]) => `<h2 class="t-subj">${esc(s)}</h2><div class="grid g2">${cs.map((c) => cardHtml(c, cards.indexOf(c), "board")).join("")}</div>`).join("") +
      (b.untaught.length ? `<p class="muted small" style="margin-top:14px">No teacher added for: ${b.untaught.map((u) => `${esc(u.name)} (${u.candidates})`).join(", ")}.</p>` : "");
  }
  const a = analysis;
  if (!a) return tabs + `<div class="card" style="margin-top:14px"><div class="skeleton" style="height:120px"></div></div>`;
  if (!a.cards.length) return tabs + `<div class="note" style="margin-top:14px">Add a teacher above to see their results.</div>`;
  const bySubj = groupBy(a.cards, (c) => c.subject_name);
  const cmp = a.comparison.filter((b) => b.rows.length > 1).map((b) => `<div class="card"><div class="card-head"><h3>${esc(b.name)}: side by side ${qmark("teacher-compare")}</h3>
      <span class="muted small">latest exam</span></div>
      <div class="chart-box sm"><canvas id="tcmp-${esc(b.subject)}"></canvas></div>
      ${table(["Teacher", "Classes", "Students", "Average %", "Pass %", "Fair check", "Difference (likely range)"],
        b.rows.map((r) => [r.name, r.classes, r.students_latest, r.avg, r.pass_pct, { html: verdict(r.fair.verdict) },
          { html: r.fair.effect !== null && r.fair.effect !== undefined ? `${signed(r.fair.effect)} <span class="muted small">(${fmt(r.fair.low)} to ${fmt(r.fair.high)})</span>` : "–" }]), { numeric: [2, 3, 4] })}</div>`).join("");
  return tabs + `<div class="note" style="margin:14px 0">⚖️ <b>Marks show only part of teaching.</b> Each student is compared with what the same student gets in their other subjects, students low in every subject are left out, and a teacher is only called “clearly” better or lower when the whole likely range agrees. Use it to start a conversation, not to decide.</div>` +
    overviewHtml(a.cards, "school") +
    (cmp ? `<h2 class="t-subj">Teachers of the same subject</h2><div class="grid g2">${cmp}</div>` : "") +
    Object.entries(bySubj).map(([s, cs]) => `<h2 class="t-subj">${esc(s)}</h2><div class="grid g2">${cs.map((c) => cardHtml(c, a.cards.indexOf(c), "school")).join("")}</div>`).join("");
}

function groupBy(xs, f) { const o = {}; xs.forEach((x) => { (o[f(x)] = o[f(x)] || []).push(x); }); return o; }

function drawCharts(kind) {
  const cards = kind === "board" ? boardAn.cards : analysis.cards;
  const green = cssVar("--green"), red = cssVar("--red"), blue = cssVar("--blue"), navy = cssVar("--navy");
  // all teachers at a glance
  const cv = $(`#t-all-${kind}`);
  if (cv) {
    const val = (c) => { const f = c.fair || {}; return f.effect ?? (kind === "board" ? f.vs_own : (c.overall || {}).vs_own) ?? 0; };
    chart(cv, "bar", cards.map((c) => `${c.name} · ${c.subject_name}`), [{
      label: "marks above / below expected", data: cards.map(val), borderRadius: 6, barThickness: 18,
      backgroundColor: cards.map((c) => verdictColor((c.fair || {}).verdict)),
    }], { indexAxis: "y", y: { beginAtZero: false, grid: { display: false } }, x: { grid: { display: true, color: cssVar("--line") } },
      tooltip: { label: (ctx) => { const c = cards[ctx.dataIndex]; const f = c.fair || {};
        return f.effect !== null && f.effect !== undefined ? ` ${fmt(f.effect)} (likely ${fmt(f.low)} to ${fmt(f.high)}) - ${f.verdict}` : ` ${fmt(ctx.raw)} vs their other subjects - ${f.verdict}`; } } });
  }
  cards.forEach((c, k) => {
    const v = c.viz;
    if (!v) return;
    const b = $(`#tb-${kind}-${k}`);
    if (b) {
      const ramp = ["#1E8E5A", "#4CB782", "#06A7E7", "#5CC4EF", "#9FDCF5", "#F7C873", "#F2A93B", "#E07B39", "#C0392B"];
      const items = v.bands.filter((x) => x[1] > 0);
      const idx = (lab) => v.bands.findIndex((x) => x[0] === lab);
      chart(b, "doughnut", items.map((x) => x[0]), [{ data: items.map((x) => x[1]), borderWidth: 2, borderColor: cssVar("--card"),
        backgroundColor: items.map((x) => ramp[Math.round(idx(x[0]) * (ramp.length - 1) / Math.max(1, v.bands.length - 1))]) }],
        { extra: { cutout: "58%" } });
    }
    const s = $(`#ts-${kind}-${k}`);
    if (s) chart(s, "pie", ["Better", "About the same", "Worse"], [{ data: [v.split.better, v.split.same, v.split.worse],
      backgroundColor: [green, "#9DB4C7", red], borderWidth: 2, borderColor: cssVar("--card") }]);
    const p = $(`#tp-${kind}-${k}`);
    if (p && v.points.length) {
      const lo = Math.max(0, Math.floor(Math.min(...v.points.flatMap((q) => [q[0], q[1]])) / 10) * 10);
      chart(p, "scatter", undefined, [
        { label: "Students", data: v.points.map((q) => ({ x: q[0], y: q[1], n: q[2] })), pointRadius: 4.5, pointHoverRadius: 7,
          backgroundColor: v.points.map((q) => q[1] - q[0] >= 3 ? green : q[1] - q[0] <= -3 ? red : "#9DB4C7") },
        { type: "line", label: "Same as other subjects", data: [{ x: lo, y: lo }, { x: 100, y: 100 }], borderColor: navy, borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0 },
      ], { x: { type: "linear", min: lo, max: 100, title: { display: true, text: "average in their other subjects" }, grid: { display: true, color: cssVar("--line") } },
        y: { min: lo, max: 100, beginAtZero: false, title: { display: true, text: c.subject_name } },
        tooltip: { label: (ctx) => ctx.raw.n ? ` ${ctx.raw.n}: ${fmt(ctx.raw.y)} (other subjects ${fmt(ctx.raw.x)})` : "" },
        extra: { plugins: { legend: { display: false } } } });
    }
    const l = kind === "school" ? $(`#tl-${k}`) : null;
    if (l) {
      const secs = c.sections.filter((x) => !x.missing);
      const exams = [...new Set(secs.flatMap((x) => x.by_exam.map((e) => e.name)))];
      const pal = [blue, navy, "#7FD0F2", "#3E7CA6", "#F2A93B", "#5B6B79"];
      chart(l, "line", exams, secs.map((x, i) => ({ label: x.label, data: exams.map((n) => (x.by_exam.find((e) => e.name === n) || {}).avg ?? null),
        borderColor: pal[i % pal.length], backgroundColor: pal[i % pal.length], tension: .3, pointRadius: 4, spanGaps: true })), { y: { max: 100 } });
    }
  });
  if (kind === "school") {
    analysis.comparison.filter((b) => b.rows.length > 1).forEach((b) => {
      const cv2 = $(`#tcmp-${CSS.escape(b.subject)}`);
      if (cv2) chart(cv2, "bar", b.rows.map((r) => r.name), [
        { label: "Average %", data: b.rows.map((r) => r.avg), backgroundColor: blue, borderRadius: 6 },
        { label: "Pass %", data: b.rows.map((r) => r.pass_pct), backgroundColor: navy, borderRadius: 6 }], { y: { max: 100 } });
    });
  }
}

async function loadAnalysis() {
  const box = $("#t-analysis");
  if (!box) return;
  try {
    if (S.summary) {
      if (analysisFor !== S.summary) analysis = null;
      analysis = analysis || await engine.call("teacher_analysis");
      analysisFor = S.summary;
    }
    if (boardAn && boardAnCls !== (S.bCls || "")) boardAn = null;   // another class picked on the Board page
    if (!boardAn) { try { boardAnCls = S.bCls || ""; boardAn = await engine.call("board_teachers", boardAnCls); } catch (e) { boardAn = null; } }
    box.innerHTML = analysisHtml();
    if (S.tTab === "board" && boardAn && boardAn.cards.length) drawCharts("board");
    if (S.tTab === "school" && analysis && analysis.cards.length) drawCharts("school");
  } catch (e) { box.innerHTML = `<div class="card"><b>Something went wrong:</b> ${esc(e.message)}</div>`; }
}

async function addClassLists(files) {
  for (const f of files) {
    busy = `Reading ${f.name}…`; rerender();
    try {
      await addAny(f, { hint: "class_list" });           // a board file or school marks dropped here go to their place
      S.classLists = await engine.call("class_lists");
    } catch (e) { toast(esc(e.message), "err", 9000); }
  }
  busy = "";
  boardAn = null; S.board = null;
  rerender();
}

export function mount(root) {
  if (!S.engineReady) return;
  // the list of teachers read from files changes when files are added or removed
  if (!S.teacherLists || S.teacherListsFor !== S.files) {
    syncTeachers().then(() => { S.teacherListsFor = S.files; rerender(); });
    return;
  }
  if (!S.classLists) { engine.call("class_lists").then((l) => { S.classLists = l; rerender(); }).catch(() => { S.classLists = []; }); return; }
  root.addEventListener("change", async (e) => {
    const cp = e.target.closest("[data-cp]");
    if (cp) {
      const keys = $$("[data-cp]", root).filter((x) => x.checked).map((x) => x.dataset.cp);
      $("#t-classes").value = keys.join(", ");
    }
    if (e.target.id === "cl-in" && e.target.files.length) addClassLists([...e.target.files]);
    const fix = e.target.closest("[data-clfix]");
    if (fix) {
      const m = fix.value.trim().toUpperCase().match(/^(XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I|\d{1,2})\s*[- ]?\s*([A-H])?$/);
      if (!m) { toast("Type the class and section like XII-A", "warn"); return; }
      const roman = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
      const cls = /^\d+$/.test(m[1]) ? roman[+m[1]] || "" : m[1];
      S.classLists = await engine.call("set_class_list", fix.dataset.clfix, cls, m[2] || "");
      boardAn = null; S.board = null; rerender();
    }
  });
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const list = loadSaved();
    if (b.dataset.ttab) { S.tTab = b.dataset.ttab; loadAnalysis(); return; }
    if (b.id === "t-save") {
      const name = $("#t-name").value.trim(), subject = $("#t-subj").value, classes = $("#t-classes").value.trim();
      if (!name || !subject || !classes) { toast("Please fill in the name, the subject and at least one class.", "warn"); return; }
      const t = { name, subject, classes };
      if (editing !== null) list[editing] = t; else list.push(t);
      editing = null;
      await save(list);
      toast("Saved ✓", "ok");
      rerender();
    }
    if (b.id === "t-cancel") { editing = null; rerender(); }
    if (b.dataset.edit !== undefined) { editing = +b.dataset.edit; rerender(); window.scrollTo({ top: 0, behavior: "smooth" }); }
    if (b.dataset.cldel) {
      S.classLists = await engine.call("remove_class_list", b.dataset.cldel);
      boardAn = null; S.board = null; rerender();
      return;
    }
    if (b.id === "t-demo") {
      busy = "Loading the made-up example…"; rerender();
      try {
        const out = await engine.call("add_sample_board_demo");
        S.classLists = out.class_lists;
        S.teacherLists = await engine.call("teachers_list");
        S.tTab = "board"; boardAn = null; S.board = null;
        toast("Made-up example loaded: board results, 3 class lists and 8 teachers (all invented).", "ok", 7000);
      } catch (err) { toast(esc(err.message), "err"); }
      busy = ""; rerender();
      return;
    }
    if (b.dataset.delfile !== undefined) {
      S.teacherLists = await engine.call("remove_file_teacher", b.dataset.delfile, b.dataset.subj);
      analysis = null; boardAn = null; S.board = null;
      toast(`${esc(b.dataset.delfile)} removed.`, "ok");
      rerender();
      return;
    }
    if (b.id === "t-clear") {
      if (!confirm("Remove ALL teachers - the ones typed here and the ones read from uploaded files?")) return;
      LS.set("rdps.teachers", []);
      editing = null;
      S.teacherLists = await engine.call("remove_all_teachers");
      analysis = null; boardAn = null; S.board = null;
      toast("All teachers removed.", "ok");
      rerender();
      return;
    }
    if (b.dataset.del !== undefined) {
      list.splice(+b.dataset.del, 1);
      editing = null;
      await save(list);
      rerender();
    }
  });
  loadAnalysis();
}
