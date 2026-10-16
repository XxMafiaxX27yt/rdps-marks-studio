// Teachers: who teaches what (name, subject, classes) and how their students do in that subject.
import * as engine from "../engine.js";
import { S, LS } from "../state.js";
import { $, $$, esc, fmt, toast, chart, cssVar, table, PALETTE } from "../ui.js";
import { qmark } from "../explain.js";

const rerender = () => window.__render();
let analysis = null;       // last teacher_analysis result
let editing = null;        // index of the teacher being edited
let analysisFor = null;    // the results the analysis was made from

export function loadSaved() { return LS.get("rdps.teachers", []); }

export async function syncTeachers() {
  if (!S.engineReady) return;
  const out = await engine.call("set_teachers", JSON.stringify(loadSaved()));
  S.teacherLists = out;
}

function save(list) {
  LS.set("rdps.teachers", list);
  analysis = null;
  return syncTeachers();
}

function classOptions() {
  // classes and sections from the uploaded marks, else the classes in settings
  if (S.summary) return S.summary.classes.map((c) => ({ cls: c.cls, label: c.label, sections: c.sections }));
  return Object.entries(S.settings.rules.classes).map(([c, v]) => ({ cls: c, label: v.label, sections: [] }));
}

export function html() {
  if (!S.engineReady || !S.settings) return `<div class="page-head"><div><h1>Teachers</h1><p>Getting ready…</p></div></div>`;
  const typed = loadSaved();
  const fromFiles = (S.teacherLists && S.teacherLists.from_files) || [];
  const subjects = S.settings.subjects;
  const cur = editing !== null ? typed[editing] : { name: "", subject: "", classes: "" };
  const opts = classOptions();
  const picked = new Set(String(cur.classes || "").split(/[,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean));
  const list = typed.map((t, i) => `<div class="file-row"><span class="ficon">${esc((t.name.replace(/^(mr|mrs|ms|dr)\.?\s+/i, "")[0] || "?").toUpperCase())}</span>
      <div style="flex:1;min-width:0"><div class="fname">${esc(t.name)}</div>
      <div class="tiny muted">${esc((subjects.find((s) => s.code === t.subject) || {}).name || t.subject)} · ${esc(t.classes)}</div></div>
      <button class="btn btn-ghost btn-sm" data-edit="${i}">Edit</button><button class="btn btn-ghost btn-sm" data-del="${i}">Remove</button></div>`).join("");
  const filesList = fromFiles.map((t) => `<div class="file-row"><span class="ficon">XLS</span>
      <div style="flex:1;min-width:0"><div class="fname">${esc(t.name)}</div>
      <div class="tiny muted">${esc(t.subject_text || t.subject)} · ${esc(t.classes.join(", ") || "no classes")} · from ${esc(t.source || "a file")}</div></div>
      <button class="btn btn-ghost btn-sm" data-delfile="${esc(t.name)}" data-subj="${esc(t.subject || t.subject_text)}">Remove</button></div>`).join("");
  return `<div class="page-head"><div><h1>Teachers ${qmark("teachers")}</h1>
      <p>Add each teacher once with the subject and classes they teach. The tool then shows how those students do in that subject - and puts the same analysis in the Excel file.</p></div></div>
    <div class="grid g3">
      <div class="card"><h3>${editing !== null ? "Edit teacher" : "Add a teacher"}</h3>
        <div class="stack">
          <label class="field"><span>Name</span><input type="text" id="t-name" value="${esc(cur.name)}" placeholder="e.g. Ms. Kavita Sharma"></label>
          <label class="field"><span>Subject</span><select id="t-subj"><option value="">Pick the subject…</option>
            ${subjects.map((s) => `<option value="${s.code}" ${s.code === cur.subject ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
          <div class="field"><span>Classes</span>
            <div class="class-pick">${opts.map((c) => {
              const secs = c.sections.length ? c.sections : [""];
              return `<div class="cp-row"><b>${esc(c.cls)}</b>${secs.map((s) => {
                const key = s ? `${c.cls}-${s}` : c.cls;
                return `<label class="cp"><input type="checkbox" data-cp="${key}" ${picked.has(key) ? "checked" : ""}><span>${esc(s || "all")}</span></label>`;
              }).join("")}</div>`;
            }).join("")}</div>
            <input type="text" id="t-classes" value="${esc(cur.classes)}" placeholder="or type: XI-A, XII-A" style="margin-top:8px"></div>
          <div class="row"><button class="btn btn-primary" id="t-save">${editing !== null ? "Save changes" : "Add teacher"}</button>
            ${editing !== null ? `<button class="btn btn-ghost" id="t-cancel">Cancel</button>` : ""}</div>
        </div></div>
      <div class="card span2"><div class="card-head"><h3>Teachers (${typed.length + fromFiles.length})</h3>
          <div class="row"><span class="muted small">Saved in this browser. A “Teachers” sheet in an uploaded file is read too.</span>
          ${typed.length + fromFiles.length ? `<button class="btn btn-danger btn-sm" id="t-clear">Remove all</button>` : ""}</div></div>
        ${list || filesList ? `<div class="stack">${list}${filesList}</div>` : `<div class="empty muted">No teachers yet. Add one on the left - for example Physics, XI-A and XII-A.</div>`}
      </div>
    </div>
    <div id="t-analysis" style="margin-top:22px">${S.summary ? `<div class="card"><div class="skeleton" style="height:120px"></div></div>` :
      `<div class="note">Make the results under <a href="#/school">School results</a> first - then each teacher's analysis appears here.</div>`}</div>`;
}

function analysisHtml(a) {
  if (!a.cards.length) return `<div class="note">Add a teacher above to see their analysis.</div>`;
  const cmp = a.comparison.filter((b) => b.rows.length).map((b) => `<div class="card"><div class="card-head"><h3>${esc(b.name)} ${qmark("teacher-compare")}</h3>
      <span class="muted small">latest exam of each class</span></div>
      ${table(["Teacher", "Classes", "Students", "Average %", "Pass %", "Fair check", "Effect (likely range)", "Change since first exam"],
        b.rows.map((r) => [r.name, r.classes, r.students_latest, r.avg, r.pass_pct, { html: verdict(r.fair) }, { html: range(r.fair) },
          { html: signed(r.change) }]), { numeric: [2, 3, 4, 7] })}</div>`).join("");
  const cards = a.cards.map((c, k) => {
    const o = c.overall;
    const secs = c.sections.filter((x) => !x.missing);
    const internals = secs.flatMap((x) => x.internals || []);
    const intAgg = {};
    internals.forEach((p) => { (intAgg[p.label] = intAgg[p.label] || []).push(p.avg); });
    return `<div class="card t-card">
      <div class="card-head"><div><h3>${esc(c.name)}</h3><div class="muted small">${esc(c.subject_name)} · ${esc(c.classes.join(", "))}</div></div>
        <div class="row">${o ? `<div class="mini-kpi"><b>${fmt(o.avg)}</b><span>avg %</span></div><div class="mini-kpi"><b>${fmt(o.pass_pct)}</b><span>pass %</span></div>
          <div class="mini-kpi"><b style="font-size:.9rem">${verdict(c.fair)}</b><span>fair check ${qmark("teachers")}</span></div>` : ""}</div></div>
      ${secs.length ? `<div class="chart-box" style="height:220px"><canvas id="tc-${k}"></canvas></div>` : ""}
      ${table(["Class", "Exam", "Students", "Average %", "Pass %", "vs own avg", "vs class avg"],
        secs.flatMap((x) => x.by_exam.map((e) => [x.label, e.name, e.n, e.avg, e.pass_pct, { html: signed(e.vs_own) }, { html: signed(e.vs_class) }])),
        { numeric: [2, 3, 4, 5, 6], max: 60 })}
      ${Object.keys(intAgg).length ? `<div class="int-bars"><b class="small">Internal marks (average %)</b>${Object.entries(intAgg).map(([l, v]) => {
        const avg = v.reduce((s, x) => s + x, 0) / v.length;
        return `<div class="ex-bar"><span>${esc(l)}</span><i style="--w:${Math.max(0, Math.min(100, avg))}%"></i><b>${fmt(avg)}%</b></div>`;
      }).join("")}</div>` : ""}
      <ul class="remarks small">${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`;
  }).join("");
  return `<div class="note" style="margin-bottom:16px">⚖️ <b>Marks show only part of teaching.</b> The fair check compares each student with what that same student usually gets in their other subjects, leaves out students who are low in every subject, and only says “clear” when the whole likely range is above or below zero. Use it to start a conversation, not to decide.</div>
    <h2 style="margin:6px 0 14px">Side by side</h2><div class="grid g2">${cmp || `<div class="note">Each subject has one teacher so far.</div>`}</div>
    <h2 style="margin:26px 0 14px">Teacher by teacher</h2><div class="grid g2">${cards}</div>`;
}

function verdict(f) {
  if (!f) return "–";
  const cls = { "Clear positive impact": "b-strong", "Worth a conversation": "b-weak", "No clear difference": "b-track" }[f.verdict] || "b-leave";
  return `<span class="badge ${cls}">${esc(f.verdict)}</span>`;
}

function range(f) {
  if (!f || f.effect === null || f.effect === undefined) return "–";
  return `${signed(f.effect)} <span class="muted small">(${fmt(f.low)} to ${fmt(f.high)})</span>`;
}

function signed(v) {
  if (v === null || v === undefined) return "–";
  const col = v > 0.05 ? "var(--green)" : v < -0.05 ? "var(--red)" : "inherit";
  return `<b style="color:${col}">${v > 0 ? "+" : ""}${fmt(v)}</b>`;
}

async function loadAnalysis() {
  const box = $("#t-analysis");
  if (!box || !S.summary) return;
  try {
    if (analysisFor !== S.summary) analysis = null;
    analysis = analysis || await engine.call("teacher_analysis");
    analysisFor = S.summary;
    box.innerHTML = analysisHtml(analysis);
    analysis.cards.forEach((c, k) => {
      const secs = c.sections.filter((x) => !x.missing);
      const cv = $(`#tc-${k}`);
      if (!cv || !secs.length) return;
      const exams = [...new Set(secs.flatMap((x) => x.by_exam.map((e) => e.name)))];
      chart(cv, "line", exams, secs.map((x, i) => ({ label: x.label, data: exams.map((n) => (x.by_exam.find((e) => e.name === n) || {}).avg ?? null),
        borderColor: PALETTE()[i % 7], backgroundColor: PALETTE()[i % 7], tension: .3, pointRadius: 4, spanGaps: true })), { y: { max: 100 } });
    });
  } catch (e) { box.innerHTML = `<div class="card"><b>Something went wrong:</b> ${esc(e.message)}</div>`; }
}

export function mount(root) {
  if (!S.engineReady) return;
  // the list of teachers read from files changes when files are added or removed
  if (!S.teacherLists || S.teacherListsFor !== S.files) {
    syncTeachers().then(() => { S.teacherListsFor = S.files; rerender(); });
    return;
  }
  root.addEventListener("change", (e) => {
    const cp = e.target.closest("[data-cp]");
    if (cp) {
      const keys = $$("[data-cp]", root).filter((x) => x.checked).map((x) => x.dataset.cp);
      $("#t-classes").value = keys.join(", ");
    }
  });
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const list = loadSaved();
    if (b.id === "t-save") {
      const name = $("#t-name").value.trim(), subject = $("#t-subj").value, classes = $("#t-classes").value.trim();
      if (!name || !subject || !classes) { toast("Please fill the name, the subject and at least one class.", "warn"); return; }
      const t = { name, subject, classes };
      if (editing !== null) list[editing] = t; else list.push(t);
      editing = null;
      await save(list);
      toast("Saved ✓", "ok");
      rerender();
    }
    if (b.id === "t-cancel") { editing = null; rerender(); }
    if (b.dataset.edit !== undefined) { editing = +b.dataset.edit; rerender(); window.scrollTo({ top: 0, behavior: "smooth" }); }
    if (b.dataset.delfile !== undefined) {
      S.teacherLists = await engine.call("remove_file_teacher", b.dataset.delfile, b.dataset.subj);
      analysis = null;
      toast(`${esc(b.dataset.delfile)} removed.`, "ok");
      rerender();
      return;
    }
    if (b.id === "t-clear") {
      if (!confirm("Remove ALL teachers - the ones typed here and the ones read from uploaded files?")) return;
      LS.set("rdps.teachers", []);
      editing = null;
      S.teacherLists = await engine.call("remove_all_teachers");
      analysis = null;
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

export function resetAnalysis() { analysis = null; }
