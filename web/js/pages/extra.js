// Template and Help pages.
import * as engine from "../engine.js";
import { S } from "../state.js";
import { $, esc, toast, download, XLSX } from "../ui.js";
import { startTour } from "../tour.js";
import { qmark } from "../explain.js";

export const template = {
  html() {
    const classes = S.settings ? Object.entries(S.settings.rules.classes) : [];
    return `<div class="page-head"><div><h1>Marks template ${qmark("upload")}</h1>
      <p>A ready-made Excel file for teachers. Every mark cell only accepts 0 to the maximum or a leave code, so typing mistakes are stopped as they happen.</p></div></div>
    <div class="grid g4">
      ${classes.map(([c, v]) => `<div class="card lift"><h3>${esc(v.label)}</h3>
        <p class="muted small">Students${v.exams.map((e) => ", " + esc(S.settings.rules.exams[e].name)).join("")}${v.streams ? "" : ", internal marks (optional)"}, Teachers.</p>
        <div class="row"><button class="btn btn-primary" data-tpl="${c}">Blank template</button>
        ${S.summary ? `<button class="btn btn-ghost" data-tplf="${c}">With uploaded students</button>` : ""}</div></div>`).join("")}
      <div class="card span2"><h3>How to fill it</h3><div class="stack small">
        <div class="hint-step"><span class="n">1</span><span>Fill the <b>Students</b> sheet once: admission no, name, parents, section - and each student's <b>Language</b> (Classes I-X) or <b>subjects</b> (XI-XII).</span></div>
        <div class="hint-step"><span class="n">2</span><span>Type marks in each exam sheet - only the class's own subjects are there, and one <b>Language</b> column for everybody's language. In XI-XII, cells of subjects a student doesn't take turn grey.</span></div>
        <div class="hint-step"><span class="n">3</span><span>Internal marks (portfolio, project, notebook) go on the <b>Internals</b> sheets - optional. The PT part is worked out from PT1 / PT2 by itself.</span></div>
        <div class="hint-step"><span class="n">4</span><span>Absent or on leave? Type AB, ML, DL, EX or NA instead of marks. Upload the file under School results - it is read automatically.</span></div></div></div>
    </div>`;
  },
  mount(root) {
    root.addEventListener("click", async (e) => {
      const t = e.target.closest("button");
      if (!t || !S.engineReady) return;
      const cls = t.dataset.tpl || t.dataset.tplf;
      if (!cls) return;
      try {
        const bytes = await engine.bytes("template_bytes", cls, !!t.dataset.tplf);
        download(bytes, `RDPS marks template - Class ${cls}${t.dataset.tplf ? " (with students)" : ""}.xlsx`, XLSX);
        toast("Template downloaded ✓", "ok");
      } catch (err) { toast(esc(err.message), "err"); }
    });
  },
};

export const help = {
  html() {
    return `<div class="page-head"><div><h1>Help</h1><p>Everything you need to use RDPS Marks Studio.</p></div>
      <button class="btn btn-primary" id="tour">▶ Guided tour</button></div>
    <div class="grid g2">
      <div class="card"><h3>🔒 Privacy</h3><p>The whole tool runs <b>inside this browser</b>. Marks, names and parents' names are processed on this computer and are <b>never uploaded</b> - the page is technically locked so it cannot send data anywhere.</p>
        <p class="small muted">Only the optional on-device AI downloads its model files (not your data). Nothing is stored after you close the page, except your settings and remembered column layouts.</p></div>
      <div class="card"><h3>📂 What files work</h3><ul class="small">
        <li>Excel (.xlsx, .xlsm, old .xls) and CSV - any layout; the check screen shows what each column means.</li>
        <li>The CBSE result gazette (.TXT) - read automatically into Board results.</li>
        <li>PDFs with text, and scanned or photographed <b>printed</b> sheets (read offline - check carefully). Handwriting is not supported.</li>
        <li>The tool's own template (recommended) and its own workbooks (to continue later).</li></ul></div>
      <div class="card"><h3>🧮 How results are worked out</h3><ul class="small">
        <li>Subject % = marks ÷ maximum × 100. Overall % = all marks ÷ all maximums.</li>
        <li><b>Strong / Weak</b>: 5+ points above / below the student's own average. <b>Needs attention</b>: below the pass mark, or 10+ points below the class average. (Change in Settings.)</li>
        <li>Absent (AB) counts as not passed; medical/duty leave and exemptions are left out.</li>
        <li>Every result is worked out <b>twice, in two independent ways</b>; if they ever disagree nothing is produced.</li></ul></div>
      <div class="card"><h3>📊 Opening the Excel file</h3><ul class="small">
        <li>Use desktop Excel for the buttons (macros). Everything else also works in Excel Online and on phones.</li>
        <li>If Excel blocks macros: right-click the file → Properties → tick <b>Unblock</b> → OK.</li>
        <li>Correct marks in the <b>Marks Matrix</b> sheet - every total, label, report card and chart updates.</li>
        <li>Upload the workbook again later to continue, ask questions or add charts.</li></ul></div>
      <div class="card"><h3>💬 Asking questions</h3><p class="small">Type or speak in English or Hinglish. The tool only answers from the uploaded marks, shows how it worked each answer out, and asks you when a question is unclear - it never guesses.</p></div>
      <div class="card"><h3>✍️ Changing the Excel with words</h3><p class="small">Under Download: “add a chart of Physics averages by section”, “highlight students below 40% in red”, “change the weak threshold to 8”, “add a sheet with the top 10 in Group A”. Each change is previewed and can be undone. Marks are never changed this way.</p></div>
    </div>`;
  },
  mount() { const t = $("#tour"); t && t.addEventListener("click", () => { location.hash = "#/school"; setTimeout(() => startTour("school"), 500); }); },
};
