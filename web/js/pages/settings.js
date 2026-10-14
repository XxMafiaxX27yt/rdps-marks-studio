// Settings: the school's rules (saved in this browser, can be exported to share with other PCs).
import * as engine from "../engine.js";
import { S, LS, prefs, savePrefs } from "../state.js";
import { $, $$, esc, toast, download } from "../ui.js";

const rerender = () => window.__render();
let draft = null;

export function html() {
  if (!S.engineReady || !S.settings) return `<div class="page-head"><div><h1>Settings</h1><p>Getting ready…</p></div></div>`;
  draft = draft || JSON.parse(JSON.stringify(S.settings));
  const r = draft.rules;
  const num = (k, label, help, step = 1) => `<label class="field"><span>${label}</span><input type="number" step="${step}" data-rule="${k}" value="${esc(r[k])}"><span class="tiny muted" style="text-transform:none;letter-spacing:0;font-weight:400">${help}</span></label>`;
  return `<div class="page-head"><div><h1>Settings</h1><p>The school's rules. They are editable defaults, not official CBSE rules unless the school says so. Saved in this browser - export them to use on other computers.</p></div>
    <div class="row"><button class="btn btn-ghost" id="s-export">Export</button><label class="btn btn-ghost"><input type="file" id="s-import" accept=".json" hidden>Import</label>
      <button class="btn btn-ghost" id="s-reset">Defaults</button><button class="btn btn-primary" id="s-save">Save settings</button></div></div>
  <div class="grid g2">
    <div class="card"><h3>School</h3><div class="grid g2">
      <label class="field"><span>School name</span><input type="text" data-rule="school_name" value="${esc(r.school_name)}"></label>
      <label class="field"><span>Place</span><input type="text" data-rule="school_place" value="${esc(r.school_place)}"></label>
      <label class="field"><span>Academic year</span><input type="text" data-rule="academic_year" value="${esc(r.academic_year)}"></label>
    </div></div>
    <div class="card"><h3>Labels</h3><div class="grid g2">
      ${num("strong_gap", "Strong", "points above the student's own average", 0.5)}
      ${num("weak_gap", "Weak", "points below the student's own average", 0.5)}
      ${num("attention_class_gap", "Needs attention", "points below the class average (or below the pass mark)", 0.5)}
      ${num("drop_alert_gap", "Progress alert", "points dropped in two exams in a row", 0.5)}
    </div></div>
    <div class="card"><h3>Passing</h3><div class="grid g2">
      ${num("pass_percent", "Pass mark (%)", "in each subject")}
      <label class="field"><span>Pass each part separately</span><select data-rule="pass_each_part"><option value="true" ${r.pass_each_part ? "selected" : ""}>Yes - theory and practical each</option><option value="false" ${!r.pass_each_part ? "selected" : ""}>No - the total only</option></select></label>
      <label class="field"><span>A blank mark means</span><select data-rule="blank_means">${r.leave_codes.map((l) => `<option ${l.code === r.blank_means ? "selected" : ""} value="${l.code}">${l.code} - ${esc(l.label)}</option>`).join("")}</select></label>
    </div></div>
    <div class="card"><h3>Maximum marks</h3><div class="grid g2">
      <label class="field"><span>Periodic tests</span><input type="number" data-max="pt.theory_only.theory|pt.with_practical.theory" value="${r.max_marks.pt.theory_only.theory}"></label>
      <label class="field"><span>Big exams - theory-only subjects</span><input type="number" data-max="major.theory_only.theory" value="${r.max_marks.major.theory_only.theory}"></label>
      <label class="field"><span>Big exams - practical subjects: theory</span><input type="number" data-max="major.with_practical.theory" value="${r.max_marks.major.with_practical.theory}"></label>
      <label class="field"><span>Big exams - practical subjects: practical</span><input type="number" data-max="major.with_practical.practical" value="${r.max_marks.major.with_practical.practical}"></label>
    </div></div>
    <div class="card"><h3>Subjects with a practical</h3><div class="chips">${draft.subjects.map((s, i) => `<label class="chip"><input type="checkbox" data-prac="${i}" ${s.practical ? "checked" : ""}> ${esc(s.name)}</label>`).join("")}</div></div>
    <div class="card"><h3>Grades (lowest % for each)</h3><div class="grid g4">${r.grades.map((g, i) => `<label class="field"><span>${esc(g.grade)}</span><input type="number" data-grade="${i}" value="${g.min}"></label>`).join("")}</div></div>
    <div class="card"><h3>Leave codes</h3>${r.leave_codes.map((l, i) => `<div class="row" style="margin-bottom:6px"><b style="width:40px">${esc(l.code)}</b><span style="flex:1">${esc(l.label)}</span>
      <label class="toggle small"><input type="checkbox" data-leave="${i}" ${l.counts_as_fail ? "checked" : ""}><i></i>counts as not passed</label></div>`).join("")}</div>
    <div class="card"><h3>Exams</h3>${Object.entries(r.classes).map(([c, v]) => `<p><b>${esc(v.label)}:</b> ${v.exams.map((e) => esc(r.exams[e].name)).join(" → ")}</p>`).join("")}
      <p class="tiny muted">To add or rename exams or subjects, edit the settings file (Export → change → Import).</p></div>
    <div class="card span2"><h3>On-device AI</h3>
      <label class="toggle"><input type="checkbox" id="p-ai" ${prefs.aiUnderstanding ? "checked" : ""}><i></i>Smart question understanding (about 120 MB, downloaded once, runs on this computer)</label>
      <p class="tiny muted" style="margin-top:8px">Voice questions download their model (about 75 MB) the first time you press the microphone. Questions and recordings are never sent anywhere - only the model files are downloaded.</p></div>
  </div>`;
}

function setPath(obj, path, val) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]];
  o[ks[ks.length - 1]] = val;
}

export function mount(root) {
  if (!S.engineReady) return;
  root.addEventListener("change", (e) => {
    const t = e.target, d = t.dataset;
    const r = draft.rules;
    if (d.rule) {
      let v = t.value;
      if (t.type === "number") v = parseFloat(v);
      if (d.rule === "pass_each_part") v = v === "true";
      r[d.rule] = v;
    }
    if (d.max) d.max.split("|").forEach((p) => setPath(r.max_marks, p, parseFloat(t.value)));
    if (d.prac !== undefined) draft.subjects[+d.prac].practical = t.checked;
    if (d.grade !== undefined) r.grades[+d.grade].min = parseFloat(t.value);
    if (d.leave !== undefined) r.leave_codes[+d.leave].counts_as_fail = t.checked;
    if (t.id === "p-ai") { prefs.aiUnderstanding = t.checked; savePrefs(); }
  });
  root.addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.id === "s-save") {
      try {
        const out = await engine.call("set_settings", JSON.stringify(draft));
        S.settings = out.settings; LS.set("rdps.settings", out.settings);
        S.files = null; S.summary = null; S.step = Math.min(S.step, 2);
        draft = null;
        toast("Settings saved. Make the results again to use them.", "ok", 5000);
        rerender();
      } catch (err) { toast(esc(err.message), "err"); }
    }
    if (t.id === "s-reset") { draft = await engine.call("default_settings_json"); rerender(); toast("Defaults loaded - press Save to use them.", "info"); }
    if (t.id === "s-export") download(new TextEncoder().encode(JSON.stringify(draft, null, 2)), "rdps-settings.json", "application/json");
  });
  const imp = $("#s-import");
  imp && imp.addEventListener("change", async () => {
    try { draft = JSON.parse(await imp.files[0].text()); rerender(); toast("Imported - press Save to use them.", "info"); }
    catch (e) { toast("That is not a settings file.", "err"); }
  });
}
