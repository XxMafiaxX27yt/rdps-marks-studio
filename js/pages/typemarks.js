// Type marks: pick the class, section, exam and subject - the names are already there, the teacher types only
// the marks of their own subject. Saved like an uploaded file (School results); nothing is stored in the browser.
import * as engine from "../engine.js";
import { S, LS, prefs, savePrefs } from "../state.js";
import { $, $$, esc, toast, modal, download } from "../ui.js";
import { syncTeachers } from "./teachers.js";
import { sheetsHtml, readSheetPhoto } from "../sheetscan.js";
import { qmark } from "../explain.js";

const rerender = () => window.__render();
let loading = "";

// S.type = { cls, section, exam, subject, parts: [], rows: [{roll, adm_no, name, section, values, added}],
//            teacher, setup (from the engine), editId, dirty, saved }
function st() {
  if (!S.type) S.type = { cls: prefs.uploadClass || "", section: "", exam: "", subject: "", parts: [], rows: [], teacher: prefs.typeTeacher || "", setup: null, dirty: false };
  return S.type;
}

window.addEventListener("beforeunload", (e) => {
  if (S.type && S.type.dirty) { e.preventDefault(); e.returnValue = ""; }
});

const label = (c) => (S.settings && S.settings.rules.classes[c] || {}).label || "Class " + c;
const columnsNow = (t) => (t.setup && t.exam && t.subject && t.setup.columns[`${t.exam}|${t.subject}`]) || null;
const rowKey = (r) => r.adm_no ? "a" + r.adm_no : "n" + (r.name || "").trim().toLowerCase();

export function html() {
  if (!S.engineReady) return `<div class="page-head"><div><h1>Type marks</h1><p>Getting ready…</p></div></div>`;
  const t = st();
  const classes = Object.entries(S.settings.rules.classes);
  const set = t.setup && t.setup.cls === t.cls ? t.setup : null;
  const cols = columnsNow(t);
  const head = `<div class="page-head"><div><h1>Type marks ${qmark("type-marks")}</h1>
      <p>No file? Type the marks here. Pick the class, section, exam and your subject - the names are already filled in, you type only the marks.</p></div></div>`;
  const picks = `<div class="card type-picks"><div class="type-grid">
      <label class="field"><span>Class</span><select class="sel-sm" id="ty-cls"><option value="">Pick…</option>
        ${classes.map(([c, v]) => `<option value="${esc(c)}" ${c === t.cls ? "selected" : ""}>${esc(v.label)}</option>`).join("")}</select></label>
      <label class="field"><span>Section</span><input class="sel-sm" id="ty-sec" list="ty-secs" maxlength="3" placeholder="All" value="${esc(t.section)}" ${t.cls ? "" : "disabled"}>
        <datalist id="ty-secs">${(set ? set.sections : []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist></label>
      <label class="field"><span>Exam</span><select class="sel-sm" id="ty-exam" ${set ? "" : "disabled"}><option value="">Pick…</option>
        ${(set ? set.exams : []).map((e) => `<option value="${esc(e.code)}" ${e.code === t.exam ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select></label>
      <label class="field"><span>Subject</span><select class="sel-sm" id="ty-sub" ${set ? "" : "disabled"}><option value="">Pick…</option>
        ${(set ? set.subjects : []).map((x) => `<option value="${esc(x.code)}" ${x.code === t.subject ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
      <label class="field"><span>Your name <span class="muted">(optional)</span></span><input class="sel-sm" id="ty-teacher" value="${esc(t.teacher)}" placeholder="for the Teachers page"></label>
    </div>
    ${cols && cols.length ? `<div class="rd-line" style="margin-top:12px"><b>Typing</b>${cols.map((c) => `<label class="toggle small"><input type="checkbox" data-part="${esc(c.part)}" ${t.parts.includes(c.part) ? "checked" : ""}><i></i>${esc(c.label)} <span class="muted">/ ${fmtMax(c.max)}</span></label>`).join("")}</div>
      ${cols.length > 1 ? `<p class="tiny muted" style="margin:6px 0 0">Tick only what you are typing now${t.cls && !S.settings.rules.classes[t.cls].streams ? " - internal marks are optional, and the PT part is worked out from the periodic test by itself" : ""}.</p>` : ""}` : ""}
    ${cols && !cols.length ? `<div class="note" style="margin-top:12px">${esc(subjectName(t))} is not counted in ${esc(label(t.cls))} ${esc(examName(t))} - nothing to type.</div>` : ""}
  </div>`;
  if (!t.cls) return head + picks + `<div class="empty">Pick the class to start.</div>`;
  if (loading || !set) return head + picks + `<div class="card"><div class="row"><span class="spinner" style="color:var(--blue)"></span><b>${esc(loading || "Finding the students…")}</b></div></div>`;
  if (!t.exam || !t.subject) return head + picks + rosterPreview(t);
  if (!cols || !cols.length || !t.parts.length) return head + picks;
  return head + picks + grid(t, cols);
}

function fmtMax(v) { return Number.isInteger(+v) ? String(+v) : String(v); }
function subjectName(t) { const x = t.setup && t.setup.subjects.find((s) => s.code === t.subject); return x ? x.name : t.subject; }
function examName(t) { const x = t.setup && t.setup.exams.find((e) => e.code === t.exam); return x ? x.name : t.exam; }

function rosterPreview(t) {
  const n = t.rows.length;
  return `<div class="card"><h3>${n ? `${n} student${n > 1 ? "s" : ""} in ${esc(label(t.cls))}${t.section ? "-" + esc(t.section) : ""}` : `No names for ${esc(label(t.cls))}${t.section ? "-" + esc(t.section) : ""} yet`}</h3>
    <p class="muted small">${n ? "Now pick the exam and your subject." : "Add the class list file on School results (it is sorted by itself), or paste the names here once."}</p>
    ${n ? "" : `<div class="row"><button class="btn btn-soft" id="ty-paste">Paste names</button></div>`}</div>`;
}

// ---------------------------------------------------------------- the grid
function grid(t, cols) {
  const parts = cols.filter((c) => t.parts.includes(c.part));
  const showSec = !t.section;
  const body = t.rows.map((r, i) => `<tr data-row="${i}">
      <td class="muted">${i + 1}</td>
      <td>${r.added ? `<input class="ty-id" data-r="${i}" data-k="roll" value="${esc(r.roll)}" placeholder="Roll" style="width:64px">` : esc(r.roll || "–")}</td>
      <td>${r.added ? `<input class="ty-id" data-r="${i}" data-k="name" value="${esc(r.name)}" placeholder="Student's name" style="width:100%">` : `<b>${esc(r.name)}</b>`}</td>
      ${showSec ? `<td>${r.added ? `<input class="ty-id" data-r="${i}" data-k="section" value="${esc(r.section)}" maxlength="3" style="width:46px">` : esc(r.section || "")}</td>` : ""}
      ${parts.map((c) => { const v = r.values[c.part] || ""; const ph = r.photo && r.photo[c.part];
        return `<td class="${ph ? "ty-photo" : ""}">${ph ? `<img class="ty-ph ${ph.sure ? "" : "unsure"}" src="${ph.img}" alt="handwritten mark" title="${esc(ph.sure ? "Read from the photo - check it" : "Not clear: " + ph.why)}">` : ""}<input class="mk ${cellState(v, c.max)} ${ph && !ph.sure && !ph.checked ? "unsure" : ""}" data-r="${i}" data-p="${esc(c.part)}" data-max="${c.max}" value="${esc(v)}" inputmode="decimal" autocomplete="off" aria-label="${esc(r.name)} ${esc(c.label)}"></td>`; }).join("")}
    </tr>`).join("");
  return `<div class="card"><div class="card-head"><h3>${esc(subjectName(t))} · ${esc(examName(t))} · ${esc(label(t.cls))}${t.section ? "-" + esc(t.section) : ""}</h3>
      <div class="row"><button class="btn btn-ghost btn-sm" id="ty-paste">Paste names</button><button class="btn btn-ghost btn-sm" id="ty-add">+ Add a student</button></div></div>
    <div class="ty-paper"><span>📄 <b>Marks on paper?</b> ${qmark("paper-sheet")} Print this sheet with the names on it, write the marks by hand, then take a photo of it.</span>
      <div class="row"><button class="btn btn-soft btn-sm" id="ty-print">🖨 Print the sheet</button>
        <label class="btn btn-soft btn-sm"><input type="file" id="ty-photo" accept="image/*" capture="environment" multiple hidden>📷 Read a photo of it</label></div></div>
    ${photoSummary(t)}
    <p class="tiny muted" style="margin:0 0 10px">Type a number up to the maximum, or ${esc((t.setup.leave_codes || []).join(" / "))} (absent, medical leave…). Enter goes down. You can paste a whole column from Excel into the first box.
      Leave a student empty if they don't take this subject.</p>
    <div class="table-wrap" style="max-height:62vh"><table class="t ty-table"><thead><tr><th>#</th><th>Roll</th><th>Name</th>${showSec ? "<th>Sec</th>" : ""}
      ${parts.map((c) => `<th class="num">${esc(c.label)} / ${fmtMax(c.max)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="row between" style="margin-top:12px">
      <span class="small" id="ty-count">${countText(t, parts)}</span>
      <div class="row"><button class="btn btn-ghost" id="ty-csv">Download a copy</button><button class="btn btn-primary btn-lg" id="ty-save">Save these marks ✓</button></div></div>
    ${t.saved ? `<div class="note" style="margin-top:12px">✓ Saved for School results. <a href="#/school">See the results →</a> or pick another subject above.</div>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- paper sheets (sheetscan.js)
function typedParts(t) {
  return columnsNow(t).filter((c) => t.parts.includes(c.part)).map((c) => ({ part: c.part, label: c.label, max: c.max }));
}

function photoSummary(t) {
  if (!t.photoPages || !t.photoPages.length) return "";
  const lines = t.photoPages.map((p) => {
    const marks = t.rows.filter((r) => r.photo && r.photoPage === p.page);
    const unclear = marks.reduce((a, r) => a + Object.values(r.photo).filter((x) => !x.sure && !x.checked).length, 0);
    const tot = Object.entries(p.totals).map(([part, x]) => {
      const lab = (columnsNow(t).find((c) => c.part === part) || {}).label || part;
      if (x.written === "") return `${esc(lab)}: no page total written`;
      const ok = Math.abs(+x.written - x.sum) < 0.01;
      return `${esc(lab)} total on the sheet <b>${esc(x.written)}</b>, marks read add up to <b>${x.sum}</b> ${ok ? `<span style="color:var(--green)">✓</span>` : `<span style="color:var(--red)">✗ - a mark (or the total) was read wrong</span>`}`;
    }).join(" · ");
    return `<div>Page ${p.page}: <b>${marks.length}</b> students read${unclear ? ` · <span style="color:var(--amber)"><b>${unclear}</b> not clear (amber) - type them</span>` : ""}. ${tot}
      ${p.warnings.map((w) => `<div style="color:var(--red)">⚠ ${esc(w)}</div>`).join("")}</div>`;
  }).join("");
  return `<div class="note ty-read">📷 <b>Read from the photo - check every mark against its picture before saving.</b>${lines}</div>`;
}

function printSheet(t) {
  const parts = typedParts(t);
  if (!parts.length) return toast("Tick what to write on the sheet first (Written, Practical …).", "warn");
  if (!t.rows.length) return toast("There are no names yet - add the class list first.", "warn");
  const root = document.getElementById("print-root");
  root.innerHTML = sheetsHtml(t, parts, { school: S.settings.rules.school_name, cls: label(t.cls) + (t.section ? "-" + t.section : ""),
    exam: examName(t), subject: subjectName(t) });
  setTimeout(() => window.print(), 100);
}

async function readPhotos(files) {
  const t = st();
  const parts = typedParts(t);
  if (!parts.length) return toast("Tick the same parts that were printed on the sheet first.", "warn");
  t.photoPages = t.photoPages || [];
  for (const f of files) {
    toast(`Reading ${esc(f.name)}…`, "info", 2500);
    try {
      const r = await readSheetPhoto(f, t, parts);
      if (r.error) { toast(`${esc(f.name)}: ${esc(r.error)}`, "err", 9000); continue; }
      for (const row of r.rows) {
        const tr = t.rows[row.i];
        tr.photo = {};
        tr.photoPage = r.page;
        for (const p of parts) {
          const m = row.marks[p.part];
          tr.values[p.part] = row.absent ? "AB" : m.value;
          tr.photo[p.part] = { img: m.img, sure: row.absent ? true : m.sure, why: m.why };
        }
      }
      t.photoPages = [...t.photoPages.filter((p) => p.page !== r.page), { page: r.page, totals: r.totals, warnings: r.warnings }]
        .sort((a, b) => a.page - b.page);
      t.dirty = true; t.saved = false;
    } catch (e) {
      toast(`${esc(f.name)}: could not read it (${esc(e.message)})`, "err", 9000);
    }
  }
  rerender();
}

function cellState(v, max) {
  const s = String(v || "").trim();
  if (!s) return "";
  return valid(s, max) ? "ok" : "bad";
}

function valid(s, max) {
  if ((S.type.setup.leave_codes || []).includes(s.toUpperCase())) return true;
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return false;
  return +s >= 0 && +s <= +max;
}

function tally(t, parts) {
  let done = 0, part = 0, bad = 0, empty = 0;
  for (const r of t.rows) {
    const vals = parts.map((c) => String(r.values[c.part] || "").trim());
    const filled = vals.filter(Boolean).length;
    bad += parts.filter((c, k) => vals[k] && !valid(vals[k], c.max)).length;
    if (!filled) empty++; else if (filled < parts.length) part++; else done++;
  }
  return { done, part, bad, empty };
}

function countText(t, parts) {
  const c = tally(t, parts);
  return [`<b>${c.done}</b> of ${t.rows.length} typed`,
    c.part ? `<span style="color:var(--amber)">${c.part} with empty boxes</span>` : "",
    c.bad ? `<span style="color:var(--red)">${c.bad} mistake${c.bad > 1 ? "s" : ""}</span>` : "",
    c.empty && c.done ? `<span class="muted">${c.empty} left empty</span>` : ""].filter(Boolean).join(" · ");
}

// ---------------------------------------------------------------- loading the class
async function loadSetup(keepValues = true) {
  const t = st();
  if (!t.cls) return;
  loading = "Finding the students…";
  rerender();
  try {
    t.setup = await engine.call("type_setup", t.cls, t.section);
    const old = new Map(keepValues ? t.rows.map((r) => [rowKey(r), r]) : []);
    const rows = t.setup.students.map((s) => ({ roll: s.roll, adm_no: s.adm_no, name: s.name, section: s.section || t.section, values: {} }));
    for (const r of rows) { const o = old.get(rowKey(r)); if (o) { r.values = o.values; old.delete(rowKey(r)); } }
    for (const o of old.values()) if (o.added || Object.values(o.values).some((v) => String(v).trim())) rows.push(o);
    t.rows = rows;
    if (t.exam && !t.setup.exams.find((e) => e.code === t.exam)) t.exam = "";
    if (t.subject && !t.setup.subjects.find((x) => x.code === t.subject)) t.subject = "";
    pickParts(t);
  } catch (e) {
    toast(esc(e.message), "err", 8000);
  }
  loading = "";
  rerender();
}

function pickParts(t) {
  const cols = columnsNow(t);
  if (!cols) { t.parts = []; return; }
  const keep = t.parts.filter((p) => cols.find((c) => c.part === p));
  t.parts = keep.length ? keep : cols.filter((c) => c.on).map((c) => c.part);
}

/** Open the screen with marks typed earlier (from the School page's file list). */
export async function editTyped(sourceId) {
  const d = await engine.call("typed_get", sourceId);
  S.type = { cls: d.cls, section: d.section, exam: d.exam, subject: d.subject, parts: d.parts, teacher: d.teacher || prefs.typeTeacher || "",
    rows: d.rows.map((r) => ({ ...r, values: { ...r.values } })), setup: null, dirty: false };
  location.hash = "#/type";
}

// ---------------------------------------------------------------- saving
async function save() {
  const t = st();
  const parts = columnsNow(t).filter((c) => t.parts.includes(c.part));
  const c = tally(t, parts);
  if (c.bad) { focusFirst((r) => parts.some((p) => r.values[p.part] && !valid(String(r.values[p.part]).trim(), p.max))); return toast("Some marks are not right (red boxes) - a number up to the maximum, or a leave code.", "err", 6000); }
  if (c.part) { focusFirst((r) => { const f = parts.filter((p) => String(r.values[p.part] || "").trim()).length; return f && f < parts.length; }); return toast("Some students have empty boxes - type the marks, or AB if they were absent.", "warn", 6000); }
  if (!c.done) return toast("No marks typed yet.", "warn");
  const unclear = t.rows.filter((r) => r.photo && parts.some((p) => r.photo[p.part] && !r.photo[p.part].sure && !r.photo[p.part].checked));
  if (unclear.length) { focusFirst((r) => unclear.includes(r)); return toast(`${unclear.length} mark${unclear.length > 1 ? "s were" : " was"} not clear in the photo (amber) - type ${unclear.length > 1 ? "them" : "it"} from the paper first.`, "warn", 7000); }
  if (t.rows.some((r) => r.added && !r.name.trim() && Object.values(r.values).some((v) => String(v).trim()))) return toast("A student you added has no name.", "warn");
  if (c.empty) {
    const names = t.rows.filter((r) => !parts.some((p) => String(r.values[p.part] || "").trim())).map((r) => r.name || "(no name)");
    const ok = await new Promise((res) => {
      const m = modal(`<h2>${c.empty} student${c.empty > 1 ? "s have" : " has"} no marks</h2>
        <p class="muted">${esc(names.slice(0, 12).join(", "))}${names.length > 12 ? " …" : ""}</p>
        <p class="small">They will be left out of ${esc(subjectName(t))} - fine if they don't take it. <b>If someone was absent, type AB</b> instead.</p>
        <div class="row" style="justify-content:flex-end"><button class="btn btn-ghost" data-close>Go back</button><button class="btn btn-primary" id="m-yes">Leave them out and save</button></div>`, { onClose: () => res(false) });
      $("#m-yes", m.el).addEventListener("click", () => { res(true); m.el.remove(); });
    });
    if (!ok) return;
  }
  const rows = t.rows.map((r) => ({ roll: r.roll, adm_no: r.adm_no, name: r.name, section: r.section,
    values: Object.fromEntries(parts.map((p) => { const v = String(r.values[p.part] || "").trim(); return [p.part, /^[a-z]+$/i.test(v) ? v.toUpperCase() : v]; })) }));
  try {
    const out = await engine.call("add_typed", JSON.stringify({ cls: t.cls, section: t.section, exam: t.exam, subject: t.subject, parts: t.parts, rows, teacher: t.teacher }));
    if (t.teacher.trim()) await rememberTeacher(t);
    t.dirty = false;
    t.saved = true;
    S.files = null; S.summary = null;
    toast(`Saved ✓ ${esc(subjectName(t))} marks of ${out.students} students → <a href="#/school">School results</a>`, "ok", 6000);
    rerender();
  } catch (e) { toast(esc(e.message), "err", 8000); }
}

// the teacher who typed the marks goes on the Teachers page (subject + this class-section)
async function rememberTeacher(t) {
  const list = LS.get("rdps.teachers", []);
  const cs = t.section ? `${t.cls}-${t.section}` : t.cls;
  const me = list.find((x) => (x.name || "").trim().toLowerCase() === t.teacher.trim().toLowerCase() && x.subject === t.subject);
  if (me) {
    const have = String(me.classes || "").split(",").map((x) => x.trim()).filter(Boolean);
    if (!have.includes(cs)) me.classes = [...have, cs].join(", ");
  } else {
    list.push({ name: t.teacher.trim(), subject: t.subject, classes: cs });
  }
  LS.set("rdps.teachers", list);
  await syncTeachers();
}

function focusFirst(test) {
  const i = S.type.rows.findIndex(test);
  const el = i >= 0 && $(`tr[data-row="${i}"] input.mk`);
  if (el) { el.focus(); el.scrollIntoView({ block: "center" }); }
}

function csvCopy() {
  const t = st();
  const parts = columnsNow(t).filter((c) => t.parts.includes(c.part));
  const q = (v) => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  const lines = [["Roll No", "Admission No", "Name", "Section", ...parts.map((p) => `${subjectName(t)} ${p.label}`)].map(q).join(",")];
  for (const r of t.rows) {
    const vals = parts.map((p) => String(r.values[p.part] || "").trim());
    if (vals.some(Boolean)) lines.push([r.roll, r.adm_no, r.name, r.section || t.section, ...vals].map(q).join(","));
  }
  const name = `${label(t.cls)}${t.section ? "-" + t.section : ""} ${examName(t)} ${subjectName(t)} (typed).csv`;
  download(new TextEncoder().encode("﻿" + lines.join("\r\n")), name, "text/csv");
  toast("Saved a copy - you can upload it on School results any time.", "ok");
}

// ---------------------------------------------------------------- names
function pasteNames() {
  const m = modal(`<h2>Paste the names</h2><p class="muted small">One student per line - copy them from Excel: <b>roll number and name</b>, or just the name.</p>
    <textarea id="ty-names" rows="10" style="width:100%" placeholder="1&#9;Student name&#10;2&#9;Student name"></textarea>
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" id="ty-names-go">Add them</button></div>`);
  $("#ty-names-go", m.el).addEventListener("click", () => {
    const t = st();
    const have = new Set(t.rows.map((r) => r.name.trim().toLowerCase()));
    let n = 0;
    for (const line of $("#ty-names", m.el).value.split(/\r?\n/)) {
      const cells = line.split(/\t|,|\s{2,}/).map((x) => x.trim()).filter(Boolean);
      if (!cells.length) continue;
      const roll = /^\d+$/.test(cells[0]) && cells.length > 1 ? cells.shift() : "";
      const name = cells.join(" ");
      if (!name || have.has(name.toLowerCase())) continue;
      have.add(name.toLowerCase());
      t.rows.push({ roll, adm_no: "", name, section: t.section, values: {}, added: true });
      n++;
    }
    m.el.remove();
    t.dirty = true;
    toast(`${n} name${n !== 1 ? "s" : ""} added.`, "ok");
    rerender();
  });
}

// ---------------------------------------------------------------- events
export function mount(root) {
  if (!S.engineReady) return;
  const t = st();
  if (t.cls && (!t.setup || t.setup.cls !== t.cls) && !loading) { loadSetup(); return; }
  root.addEventListener("change", async (e) => {
    const el = e.target;
    if (el.id === "ty-cls") {
      if (t.dirty && !(await sure())) { el.value = t.cls; return; }
      Object.assign(t, { cls: el.value, section: "", exam: "", subject: "", parts: [], rows: [], setup: null, dirty: false, saved: false });
      prefs.uploadClass = el.value; savePrefs();
      return el.value ? loadSetup(false) : rerender();
    }
    if (el.id === "ty-sec") {
      const v = el.value.trim().toUpperCase();
      if (v === t.section) return;
      if (t.dirty && !(await sure())) { el.value = t.section; return; }
      t.section = v; t.saved = false; t.dirty = false; t.rows = [];
      return loadSetup(false);
    }
    if (el.id === "ty-exam" || el.id === "ty-sub") {
      if (t.dirty && !(await sure())) { el.value = el.id === "ty-exam" ? t.exam : t.subject; return; }
      t[el.id === "ty-exam" ? "exam" : "subject"] = el.value;
      t.rows.forEach((r) => { r.values = {}; });
      t.dirty = false; t.saved = false;
      pickParts(t); rerender(); return;
    }
    if (el.id === "ty-teacher") { t.teacher = el.value.trim(); prefs.typeTeacher = t.teacher; savePrefs(); return; }
    if (el.id === "ty-photo") { const fs = [...el.files]; el.value = ""; return fs.length && readPhotos(fs); }
    if (el.dataset.part) {
      t.parts = columnsNow(t).filter((c) => c.part === el.dataset.part ? el.checked : t.parts.includes(c.part)).map((c) => c.part);
      rerender(); return;
    }
  });
  root.addEventListener("input", (e) => {
    const el = e.target;
    if (el.classList.contains("mk")) {
      const row = t.rows[+el.dataset.r];
      row.values[el.dataset.p] = el.value;
      if (row.photo && row.photo[el.dataset.p]) row.photo[el.dataset.p].checked = true;     // the teacher typed it
      el.className = "mk " + cellState(el.value, el.dataset.max);
      t.dirty = true; t.saved = false;
      updateCount();
    } else if (el.classList.contains("ty-id")) {
      t.rows[+el.dataset.r][el.dataset.k] = el.dataset.k === "section" ? el.value.toUpperCase() : el.value;
      t.dirty = true;
    }
  });
  root.addEventListener("keydown", (e) => {
    const el = e.target;
    if (!el.classList.contains("mk") || !["Enter", "ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const next = $(`input.mk[data-r="${+el.dataset.r + (e.key === "ArrowUp" ? -1 : 1)}"][data-p="${CSS.escape(el.dataset.p)}"]`, root);
    if (next) { next.focus(); next.select(); }
  });
  // a column copied from Excel goes down from the box it was pasted into
  root.addEventListener("paste", (e) => {
    const el = e.target;
    if (!el.classList.contains("mk")) return;
    const lines = (e.clipboardData.getData("text") || "").split(/\r?\n/).map((x) => x.split("\t")[0].trim());
    while (lines.length && !lines[lines.length - 1]) lines.pop();
    if (lines.length < 2) return;
    e.preventDefault();
    let r = +el.dataset.r;
    for (const v of lines) {
      if (r >= t.rows.length) break;
      t.rows[r].values[el.dataset.p] = v;
      r++;
    }
    t.dirty = true; t.saved = false;
    rerender();
    toast(`${Math.min(lines.length, t.rows.length - +el.dataset.r)} marks pasted - check the red boxes, if any.`, "info");
  });
  root.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.id === "ty-save") return save();
    if (b.id === "ty-csv") return csvCopy();
    if (b.id === "ty-print") return printSheet(t);
    if (b.id === "ty-paste") return pasteNames();
    if (b.id === "ty-add") {
      t.rows.push({ roll: "", adm_no: "", name: "", section: t.section, values: {}, added: true });
      rerender();
      const ins = $$("input.ty-id[data-k='name']", root);
      ins.length && ins[ins.length - 1].focus();
    }
  });
}

function updateCount() {
  const t = st();
  const el = $("#ty-count");
  if (el) el.innerHTML = countText(t, columnsNow(t).filter((c) => t.parts.includes(c.part)));
}

function sure() {
  return new Promise((res) => {
    const m = modal(`<h2>Leave the marks you typed?</h2><p class="muted">They are not saved yet. Press <b>Save these marks</b> first to keep them.</p>
      <div class="row" style="justify-content:flex-end"><button class="btn btn-ghost" data-close>Stay</button><button class="btn btn-danger" id="m-yes">Leave them</button></div>`, { onClose: () => res(false) });
    $("#m-yes", m.el).addEventListener("click", () => { res(true); m.el.remove(); });
  });
}
