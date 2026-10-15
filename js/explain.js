// "?" explainers: a short animated walk-through for every part of the tool, with the same
// explanation written out below it. The "How it works" page lists all of them in one place.
import { $, $$, esc, modal, countUp } from "./ui.js";

// ---------------------------------------------------------------- little building blocks for the visuals
const chip = (t, cls = "") => `<span class="ex-chip ${cls}">${t}</span>`;
const box = (t, cls = "") => `<div class="ex-box ${cls}">${t}</div>`;
const arrow = () => `<span class="ex-arrow">→</span>`;
const num = (v, places = 0, suf = "") => `<b class="ex-num" data-count="${v}" data-places="${places}">0</b>${suf}`;
const bar = (label, v, cls = "") => `<div class="ex-bar ${cls}"><span>${label}</span><i style="--w:${v}%"></i><b>${v}%</b></div>`;
const flow = (...items) => `<div class="ex-flow">${items.join("")}</div>`;
const grid = (rows, hl = -1) => `<table class="ex-table">${rows.map((r, i) => `<tr class="${i === 0 ? "h" : ""} ${i === hl ? "hl" : ""}">${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>`;

// ---------------------------------------------------------------- the explainers
export const EXPLAINERS = [
  // ---- getting the marks in
  { id: "upload", area: "Getting marks in", title: "Uploading marks", steps: [
    { text: "Drop one file or many - Excel, old .xls, CSV, PDF, even a photo of a printed sheet. One file per exam or one file for the whole class, both work.",
      visual: flow(chip("XLSX"), chip("CSV"), chip("PDF"), chip("Photo"), arrow(), box("Marks Studio", "pop")) },
    { text: "Everything is read inside this browser. Nothing is sent anywhere - the page is locked so it cannot upload marks.",
      visual: flow(box("🔒 This computer", "pop big"), `<span class="ex-cross">✕ internet</span>`) },
    { text: "The CBSE result gazette (.TXT) is recognised by itself and goes to Board results - it is kept separate from school exams.",
      visual: flow(chip("CBSE .TXT"), arrow(), box("Board results", "pop")) },
  ] },
  { id: "check", area: "Getting marks in", title: "Checking the columns", steps: [
    { text: "The tool reads the headings and proposes what each column is: a name, a roll number, or the marks of a subject in an exam.",
      visual: grid([["Name", "Eng", "Maths", "Sci"], ["Riya", "62", "71", "58"]]) + flow(chip("Name ✓", "ok"), chip("English ✓", "ok"), chip("Maths ✓", "ok")) },
    { text: "Anything it is not sure about is shown in amber. It never guesses - you pick the right meaning from the list.",
      visual: flow(chip("“Phy. Pr”", "warn pulse"), arrow(), chip("Physics · practical", "ok")) },
    { text: "Your choices are remembered. Next time a file with the same headings comes in, it is understood straight away.",
      visual: flow(box("Same layout as last time ✓", "pop")) },
  ] },
  { id: "classes", area: "Getting marks in", title: "Classes, sections and streams", steps: [
    { text: "Classes I to XII all work. Classes can be written any way: “Class 6”, “VI”, “6th”, “VI-A”, “6 A”.",
      say: "Classes one to twelve all work, and a class can be written in many ways: Class 6, the Roman numeral six, sixth, six dash A, or 6 A.",
      visual: flow(chip("Class 6"), chip("VI"), chip("6th"), chip("VI-A"), arrow(), box("Class VI · Section A", "pop")) },
    { text: "Classes XI and XII have streams. Section A is PCM, B is PCM / PCB / PCMB, C is Commerce with Maths, D is Commerce without Maths, E is Humanities.",
      visual: flow(chip("A · PCM"), chip("B · PCM / PCB / PCMB"), chip("C · Commerce + Maths"), chip("D · Commerce"), chip("E · Humanities")) },
    { text: "Each student's stream is worked out from the subjects they take, so a PCB student in section B is shown with the PCB students.",
      visual: flow(chip("Eng + Phy + Chem + Bio + PE"), arrow(), box("PCB", "pop")) },
  ] },
  { id: "languages", area: "Getting marks in", title: "The Language column", steps: [
    { text: "Every student takes one language - Sanskrit, French, German or Spanish (in Class X: Hindi or one of these). Instead of four half-empty columns, there is one column: Language.",
      visual: grid([["Name", "Language", "Lang marks"], ["Riya", "French", "64"], ["Kabir", "Sanskrit", "71"]], 1) },
    { text: "The Students sheet says which language each student takes. Marks typed under “Language” are counted in that student's own language.",
      visual: flow(chip("Riya → French"), arrow(), chip("Language 64 = French 64", "ok")) },
  ] },
  { id: "duplicates", area: "Getting marks in", title: "Same marks? Never a problem", steps: [
    { text: "Students are told apart by admission number and roll number - never by their marks. Two students with exactly the same marks are two students, and both count.",
      visual: grid([["Roll", "Name", "Eng", "Maths"], ["4", "Aarav", "72", "65"], ["9", "Diya", "72", "65"]]) + flow(chip("2 students ✓", "ok")) },
    { text: "A real duplicate is the same roll or admission number typed twice in one sheet - that is shown as an error so it can be fixed. The same mark pasted twice for one student is simply used once.",
      visual: flow(chip("Roll 4 … Roll 4", "warn pulse"), arrow(), box("Please check", "pop")) },
  ] },
  // ---- how marks are counted
  { id: "schemes", area: "How marks are counted", title: "Maximum marks in each class", steps: [
    { text: "Classes I-VIII: periodic tests are out of 20. Half Yearly and Yearly are 80 written + 20 internal.",
      visual: flow(box("PT1 / PT2<br>" + num(20), "pop"), box("Half Yearly / Yearly<br>80 + 20", "pop")) },
    { text: "Classes IX and X: periodic tests are out of 40; big exams 80 + 20. Class X also has a Preboard. ICT (Classes VII-IX) has a written exam of 30. AI (IX-X) is 50 theory + 50 practical.",
      visual: flow(chip("PT /40"), chip("80 + 20"), chip("ICT 30"), chip("AI 50 + 50")) },
    { text: "Classes XI and XII: periodic tests 40; big exams 80, or 70 theory + 30 practical in Physics, Chemistry, Biology and Computer Science. Class XII has a Preboard.",
      visual: flow(chip("PT /40"), chip("80"), chip("70 + 30 practical")) },
    { text: "ICT in Classes I-VI is only a notebook mark, so it is not counted anywhere. All of this can be changed in Settings.",
      visual: flow(chip("ICT I-VI", "muted"), arrow(), box("not counted", "pop")) },
  ] },
  { id: "internals", area: "How marks are counted", title: "Internal marks (20)", steps: [
    { text: "Internal marks are 20: the periodic test scaled to 5, portfolio 5, project 5 and notebook 5.",
      visual: flow(chip("PT 5"), chip("+ Portfolio 5"), chip("+ Project 5"), chip("+ Notebook 5"), arrow(), box("= 20", "pop")) },
    { text: "The PT part is worked out by itself: PT1 goes into the Half Yearly, PT2 into the Yearly. 17 out of 20 in PT1 becomes 17 ÷ 20 × 5 = 4.25.",
      visual: flow(box("PT1: 17 / 20", ""), arrow(), box(num(4.25, 2) + " / 5", "pop")) },
    { text: "Internal marks are optional. If a file has only the written marks, the subject is worked out of the written paper alone - nothing is marked missing.",
      visual: flow(chip("English 62 / 80 only"), arrow(), box(num(77.5, 1, "%"), "pop")) },
    { text: "If they are given (as one mark out of 20, or as the parts), they are added: 62 + 17 = 79 out of 100.",
      visual: flow(chip("62 / 80"), chip("+ 17 / 20"), arrow(), box(num(79, 0, "%"), "pop")) },
  ] },
  { id: "percent", area: "How marks are counted", title: "Subject % and overall %", steps: [
    { text: "Subject % = marks ÷ maximum × 100. Physics 52 + 24 out of 70 + 30 = 76%.",
      visual: flow(chip("52 / 70"), chip("+ 24 / 30"), arrow(), box(num(76, 0, "%"), "pop")) },
    { text: "Overall % = all the marks added ÷ all the maximums added (not an average of percentages).",
      visual: flow(chip("380 marks"), chip("÷ 500"), arrow(), box(num(76, 0, "%"), "pop")) },
    { text: "Decimals are kept exactly (37.5 stays 37.5). Every result is worked out twice in two different ways; if they ever disagree, nothing is made.",
      visual: flow(box("Way 1: 76.000000"), box("Way 2: 76.000000"), chip("✓ same", "ok")) },
  ] },
  { id: "pass", area: "How marks are counted", title: "Pass or not passed", steps: [
    { text: "A subject is passed with 33% - in each part separately: the written paper and the practical / internal each need 33%.",
      visual: bar("Written", 41) + bar("Internal", 70) + flow(chip("Pass ✓", "ok")) },
    { text: "Absent (AB) counts as not passed. Medical leave, duty leave and exemptions are left out instead.",
      visual: flow(chip("AB → not passed", "warn"), chip("ML / DL / EX → left out", "muted")) },
    { text: "A blank mark in a subject the student takes means absent. A column with nothing typed in it at all (an exam not written yet) is simply left out.",
      visual: flow(chip("one blank → AB"), chip("whole column empty → ignored", "muted")) },
  ] },
  { id: "labels", area: "How marks are counted", title: "Doing well, Focus area, Needs support", steps: [
    { text: "Each subject is compared with the student's own average. 5 or more points above it: Doing well (Strong). 5 or more below: Focus area (Weak).",
      visual: bar("Own average", 70) + bar("Maths", 78, "good") + bar("Hindi", 61, "weak") },
    { text: "Needs support (Needs attention): below the pass mark, or 10+ points below the class average.",
      visual: bar("Class average", 68) + bar("Science", 55, "bad") },
    { text: "A student who is below the pass mark somewhere only gets “Needs support” in the subjects actually below the pass mark - not in every subject. All gaps can be changed in Settings.",
      visual: flow(chip("Chemistry 28% → Needs support", "warn"), chip("English 52% → own-average check", "muted")) },
  ] },
  { id: "grades", area: "How marks are counted", title: "Grades and ranks", steps: [
    { text: "Grades come from the school's bands: A1 from 91%, A2 81, B1 71, B2 61, C1 51, C2 41, D 33, E below 33.",
      visual: flow(chip("91+ A1"), chip("81 A2"), chip("71 B1"), chip("61 B2"), chip("51 C1"), chip("41 C2"), chip("33 D"), chip("E")) },
    { text: "Rank = 1 + the number of students in the class with a higher overall %. Equal marks share the same rank.",
      visual: grid([["Rank", "Name", "%"], ["1", "Ira", "94.5"], ["2", "Om", "92.0"], ["2", "Sara", "92.0"], ["4", "Yash", "90.1"]], 2) },
  ] },
  // ---- the results screens
  { id: "dashboard", area: "Results", title: "The overview", steps: [
    { text: "Pick a class, an exam and a section. The cards show the number of students, the class average, the highest %, the pass rate and the topper.",
      visual: flow(box(num(48) + "<br><small>students</small>"), box(num(71.4, 1) + "<br><small>average %</small>"), box(num(93.8, 1) + "<br><small>pass %</small>")) },
    { text: "The charts show each subject's average, how many subjects are going well or need support, how many students are in each % range, and each section's average.",
      visual: bar("English", 74) + bar("Maths", 66) + bar("Science", 70) },
  ] },
  { id: "students", area: "Results", title: "The students table", steps: [
    { text: "One row per student. Each subject shows the % - green = doing well, amber = focus area, red = needs support. Hover a mark for the reason in words.",
      visual: grid([["Name", "Eng", "Maths", "Lang"], ["Riya", "<span style='color:var(--green)'>81</span>", "<span style='color:var(--amber)'>62</span>", "70 Fre"]]) },
    { text: "Only the subjects of the chosen class (or stream) are shown, and each student's language shares one column - no empty columns.",
      visual: flow(chip("Class XI · PCM"), arrow(), chip("Eng · Maths · Phy · Chem · Elective")) },
  ] },
  { id: "subjects", area: "Results", title: "Subjects and the hardest subject", steps: [
    { text: "For every subject: average, highest, lowest, pass % and absentees. The hardest subject is the one with the lowest average.",
      visual: bar("Physics", 62, "weak") + bar("English", 75) + bar("Economics", 79, "good") },
    { text: "“Across exams” shows how one subject's average and pass % changed from PT1 to the last exam.",
      visual: flow(chip("PT1 64"), arrow(), chip("HY 67"), arrow(), chip("PT2 70"), arrow(), chip("YE 72", "ok")) },
  ] },
  { id: "progress", area: "Results", title: "Progress and the watch list", steps: [
    { text: "Change = overall % in the latest exam minus the exam before it. Most improved = the biggest rises.",
      visual: flow(chip("HY 61%"), arrow(), chip("YE 69%"), box("+8", "pop good")) },
    { text: "Watch list: dropped 5+ points in two exams in a row, or not passed in the latest exam.",
      visual: flow(chip("−6"), chip("−7"), arrow(), box("👀 watch", "pop")) },
  ] },
  { id: "report-card", area: "Results", title: "Report cards and remarks", steps: [
    { text: "A report card shows each subject's written and internal (or practical) marks, total, %, the class average and the grade.",
      visual: grid([["Subject", "Written", "Internal", "%"], ["English", "62", "17", "79"], ["Maths", "58", "15.5", "73.5"]]) },
    { text: "Remarks are written by fixed rules from the marks - nothing is guessed: the best subject, subjects going well, and focus areas.",
      visual: flow(chip("Best subject: English (79%)", "ok"), chip("Focus area: Maths", "warn")) },
    { text: "The best subject is never also listed as a focus area. Bars show one decimal, exactly like the table.",
      visual: bar("English", 79) + bar("Computer Sc.", 40.5) },
  ] },
  // ---- teachers
  { id: "teachers", area: "Teachers", title: "Teacher analysis", steps: [
    { text: "Add a teacher once: name, subject and the classes they teach - for example Physics, XI-A and XII-A. A 'Teachers' sheet in the template works too.",
      visual: flow(box("Mr. Verma · Physics<br>XI-A, XII-A", "pop")) },
    { text: "The tool then looks only at Physics marks of the students in XI-A and XII-A: average, pass %, grades, and the change from the first exam to the latest.",
      visual: bar("XI-A Physics", 71) + bar("XII-A Physics", 68) },
    { text: "The fair check: a weak section scores lower in every subject. So each student's Physics % is compared with that student's own average over all subjects - only the part that belongs to Physics is left.",
      visual: flow(chip("Physics 72%"), chip("− own average 68%"), arrow(), box("+4 for Physics", "pop good")) },
    { text: "If the school gives internal marks in parts, the card also shows average portfolio, project and notebook marks.",
      visual: bar("Portfolio", 84) + bar("Project", 78) + bar("Notebook", 90) },
  ] },
  { id: "teacher-compare", area: "Teachers", title: "Comparing teachers of a subject", steps: [
    { text: "Every teacher of the same subject side by side: classes, students, average %, pass %, the fair check and the change since the first exam (latest exam of each class).",
      visual: grid([["Teacher", "Avg %", "Pass %", "vs own"], ["Ms. Rao", "74.2", "97.7", "+2.1"], ["Mr. Sethi", "69.8", "93.0", "−0.4"]], 1) },
    { text: "Use it as a conversation starter, not a verdict - classes differ. The same table is in the Excel file (Teachers sheet) with live formulas.",
      visual: flow(box("Teachers sheet in Excel ✓", "pop")) },
  ] },
  // ---- asking + Excel
  { id: "ask", area: "Ask and Excel", title: "Asking questions in your own words", steps: [
    { text: "Type or speak a question in English or Hinglish: “Top 5 in class 9”, “Result of class 6”, “Who failed in more than one subject in class 11?”, “Physics mein kaun kamzor hai?”.",
      visual: flow(chip("“section toppers of class 12”"), arrow(), box("Section A: Ira · B: Om · …", "pop")) },
    { text: "Every answer says how it understood the question and how it worked the answer out. Unclear? It asks back with buttons instead of guessing.",
      visual: flow(chip("“top 10 students”"), arrow(), box("Which class? [VI] [IX] [XI]", "pop")) },
    { text: "It also answers about teachers (“how are the Physics teachers doing?”), streams (“PCM toppers”), grades (“how many got A1?”) and distinctions.",
      visual: flow(chip("teachers"), chip("streams"), chip("grades"), chip("distinction")) },
  ] },
  { id: "excel", area: "Ask and Excel", title: "The Excel workbook", steps: [
    { text: "One “Marks” sheet per class (and per stream in XI-XII) with only that class's subjects. Correct a mark there and every total, label, report card and chart updates.",
      visual: flow(chip("Marks VI"), chip("Marks IX"), chip("Marks XI PCM"), chip("Marks XI Commerce")) },
    { text: "Internal marks typed in parts get their own “Internals” sheet; the PT part is a formula from the periodic test. Overview has every student's total, %, result and rank.",
      visual: flow(chip("Internals VI"), chip("Overview"), chip("Teachers"), chip("Report Card")) },
    { text: "Every number is a real Excel formula, checked in Excel itself against the website's answers.",
      visual: flow(box("Excel = website ✓", "pop")) },
  ] },
  { id: "commands", area: "Ask and Excel", title: "Changing the Excel with words", steps: [
    { text: "Under Download, type a change: “add a chart of Physics averages by section”, “highlight students below 40% in red”, “change the weak threshold to 8”.",
      visual: flow(chip("“highlight below 40% in red”"), arrow(), box("Preview", "pop")) },
    { text: "Each change is previewed first and can be undone. Marks are never changed this way.",
      visual: flow(chip("Apply"), chip("Undo"), chip("marks untouched", "ok")) },
  ] },
  { id: "boards", area: "Board results", title: "Board results (X and XII)", steps: [
    { text: "Upload the CBSE gazette (.TXT). Every candidate is read and the count is checked against CBSE's own total line.",
      visual: flow(chip("TOTAL CANDIDATES 60"), arrow(), box("60 read ✓", "pop")) },
    { text: "Best 5 = English (a language) + the four best other subjects. Also: pass %, compartments, toppers, subject averages and the performance index (PI).",
      visual: flow(chip("Eng 92"), chip("+ best 4"), arrow(), box("Best 5: " + num(91.6, 1, "%"), "pop")) },
    { text: "Board results stay separate from school exams. With Board Roll Nos in the student list, each student's Preboard is compared with their board marks.",
      visual: flow(chip("Preboard 78"), chip("Board 85"), box("+7", "pop good")) },
  ] },
  { id: "privacy", area: "Board results", title: "Privacy", steps: [
    { text: "The whole tool runs in this browser. Marks, names and parents' names never leave this computer.",
      visual: flow(box("🔒 Nothing is uploaded", "pop big")) },
    { text: "Only settings, teacher names and remembered column layouts are kept in this browser, so they are there next time.",
      visual: flow(chip("settings"), chip("teachers"), chip("layouts")) },
  ] },
];

const BY_ID = Object.fromEntries(EXPLAINERS.map((e) => [e.id, e]));

// ---------------------------------------------------------------- the "?" button
export function qmark(id, label) {
  const e = BY_ID[id];
  if (!e) return "";
  return `<button class="qmark" type="button" data-explain="${id}" title="How this works: ${esc(e.title)}" aria-label="Explain ${esc(label || e.title)}">?</button>`;
}

// ---------------------------------------------------------------- voice + video files
// (made by tools/make_explainer_media.py: a recorded voice for every step, and one MP4 per explainer)
let media = null;
async function loadMedia() {
  if (media) return media;
  const get = async (u) => { try { const r = await fetch(u); return r.ok ? r.json() : null; } catch { return null; } };
  const [voice, video] = await Promise.all([get("assets/voice/manifest.json"), get("assets/video/manifest.json")]);
  media = { voice: (voice && voice.explainers) || {}, video: video || {} };
  return media;
}
const VOICE_KEY = "rdps.explainVoice";
const voiceOn = () => { try { return localStorage.getItem(VOICE_KEY) !== "off"; } catch { return true; } };
const setVoice = (on) => { try { localStorage.setItem(VOICE_KEY, on ? "on" : "off"); } catch { /* private mode */ } };

// ---------------------------------------------------------------- the player
export async function play(id, startWith = "steps") {
  const e = BY_ID[id];
  if (!e) return;
  const md = await loadMedia();
  const clips = md.voice[id] || [];         // [title, step 1, step 2, ...]
  const vid = md.video[id];
  let i = 0, timer = null, playing = true, mode = startWith === "video" && vid ? "video" : "steps", voice = voiceOn();
  const audio = new Audio();
  audio.preload = "auto";
  const stopAudio = () => { audio.pause(); audio.onended = null; };
  const m = modal(`<div class="ex-player">
      <div class="ex-head"><div><div class="tiny muted">${esc(e.area)}</div><h2>${esc(e.title)}</h2></div>
        <div class="row" style="gap:6px">
          ${vid ? `<div class="seg ex-mode"><button data-mode="steps">Step by step</button><button data-mode="video">🎬 Video</button></div>` : ""}
          <button class="icon-btn" data-close aria-label="Close">✕</button></div></div>
      <div class="ex-stage" aria-live="polite"><div class="ex-visual"></div><p class="ex-caption"></p></div>
      <div class="ex-videobox hidden">${vid ? `<video class="ex-video" controls playsinline preload="metadata" src="assets/video/${esc(vid.file)}"></video>
        <div class="row between" style="margin-top:8px"><span class="tiny muted">${Math.round(vid.dur)} seconds · with voice and the text on screen · works full screen</span>
        <a class="btn btn-ghost btn-sm" href="assets/video/${esc(vid.file)}" download="RDPS Marks Studio - ${esc(e.title)}.mp4">⬇ Download video</a></div>` : ""}</div>
      <div class="ex-controls">
        <button class="btn btn-ghost btn-sm" data-ex="prev" aria-label="Previous step">◀</button>
        <button class="btn btn-primary btn-sm" data-ex="play">❚❚ Pause</button>
        <button class="btn btn-ghost btn-sm" data-ex="next" aria-label="Next step">▶</button>
        ${clips.length ? `<button class="btn btn-ghost btn-sm ex-voice" data-ex="voice" title="Voice on / off">${voice ? "🔊 Voice on" : "🔇 Voice off"}</button>` : ""}
        <div class="ex-dots">${e.steps.map((_, k) => `<button data-ex-dot="${k}" aria-label="Step ${k + 1}"></button>`).join("")}</div>
        <span class="ex-progress"><i></i></span></div>
      <details class="ex-text" open><summary>Read it as text</summary><ol>${e.steps.map((st) => `<li>${esc(st.text)}</li>`).join("")}</ol></details>
    </div>`, { onClose: () => { clearTimeout(timer); stopAudio(); const v = $(".ex-video", m.el); v && v.pause(); } });
  const root = m.el;
  const words = (t) => t.split(/\s+/).length;
  const stepMs = (k) => {
    const c = clips[k + 1];
    return voice && c ? (c.dur + 0.9) * 1000 : Math.max(5200, words(e.steps[k].text) * 330);
  };
  const next = () => { if (i < e.steps.length - 1) { i++; show(); } else { setPlaying(false); } };
  const show = () => {
    const st = e.steps[i];
    const vis = $(".ex-visual", root), cap = $(".ex-caption", root);
    vis.classList.remove("in"); cap.classList.remove("in");
    void vis.offsetWidth;
    vis.innerHTML = st.visual;
    cap.textContent = st.text;
    vis.classList.add("in"); cap.classList.add("in");
    countUp(vis);
    $$(".ex-dots button", root).forEach((b, k) => b.classList.toggle("on", k === i));
    $$(".ex-text li", root).forEach((li, k) => li.classList.toggle("now", k === i));
    const ms = stepMs(i);
    const prog = $(".ex-progress i", root);
    prog.style.transition = "none"; prog.style.width = "0";
    void prog.offsetWidth;
    if (playing) { prog.style.transition = `width ${ms}ms linear`; prog.style.width = "100%"; }
    clearTimeout(timer);
    stopAudio();
    if (!playing) return;
    const c = clips[i + 1];
    if (voice && c) {
      audio.src = "assets/voice/" + c.file;
      audio.currentTime = 0;
      // the next step starts when the voice has finished (or after the time it should take, if audio is blocked)
      let done = false;
      const go = () => { if (!done) { done = true; clearTimeout(timer); timer = setTimeout(next, 900); } };
      audio.onended = go;
      audio.play().catch(() => {});
      timer = setTimeout(go, (c.dur + 1.5) * 1000);
    } else {
      timer = setTimeout(next, ms);
    }
  };
  const setPlaying = (on) => {
    playing = on;
    $("[data-ex=play]", root).textContent = on ? "❚❚ Pause" : "▶ Play";
    if (on && i === e.steps.length - 1 && !timer) i = 0;
    show();
  };
  const setMode = (mo) => {
    mode = mo;
    $$("[data-mode]", root).forEach((b) => b.classList.toggle("on", b.dataset.mode === mo));
    $(".ex-stage", root).classList.toggle("hidden", mo === "video");
    $(".ex-controls", root).classList.toggle("hidden", mo === "video");
    $(".ex-videobox", root).classList.toggle("hidden", mo !== "video");
    const v = $(".ex-video", root);
    if (mo === "video") {
      clearTimeout(timer); timer = null; stopAudio(); playing = false;
      $("[data-ex=play]", root).textContent = "▶ Play";
      v && v.play().catch(() => {});
    } else {
      v && v.pause();
      setPlaying(true);
    }
  };
  root.addEventListener("click", (ev) => {
    const mb = ev.target.closest("[data-mode]");
    if (mb) { setMode(mb.dataset.mode); return; }
    const b = ev.target.closest("[data-ex], [data-ex-dot]");
    if (!b) return;
    if (b.dataset.exDot !== undefined) { i = +b.dataset.exDot; show(); return; }
    const a = b.dataset.ex;
    if (a === "prev") { i = Math.max(0, i - 1); show(); }
    if (a === "next") { i = Math.min(e.steps.length - 1, i + 1); show(); }
    if (a === "play") { timer = null; setPlaying(!playing); }
    if (a === "voice") {
      voice = !voice; setVoice(voice);
      b.textContent = voice ? "🔊 Voice on" : "🔇 Voice off";
      show();
    }
  });
  if (mode === "video") setMode("video");
  else { $$("[data-mode]", root).forEach((x) => x.classList.toggle("on", x.dataset.mode === "steps")); show(); }
}

document.addEventListener("click", (ev) => {
  const q = ev.target.closest("[data-explain]");
  if (q) { ev.preventDefault(); play(q.dataset.explain, q.dataset.explainMode || "steps"); }
});

// ---------------------------------------------------------------- "How it works" page
export const page = {
  html() {
    const areas = [...new Set(EXPLAINERS.map((e) => e.area))];
    return `<div class="page-head"><div><h1>How it works</h1>
        <p>Every part of RDPS Marks Studio explained - press ▶ for a short walk-through with a voice, 🎬 for the video (it can be downloaded and shared), or read the text. The same explanations open from the <span class="qmark static">?</span> buttons next to each chart and number.</p></div>
      <div class="row"><input type="search" id="ex-search" placeholder="Search, e.g. internal, rank, teacher…" style="width:260px">
        <button class="btn btn-primary" id="tour">▶ Guided tour</button></div></div>
      ${areas.map((a) => `<section class="ex-area" data-area="${esc(a)}"><h2>${esc(a)}</h2><div class="grid g2">
        ${EXPLAINERS.filter((e) => e.area === a).map((e) => `<div class="card ex-card" data-q="${esc((e.title + " " + e.steps.map((s) => s.text).join(" ")).toLowerCase())}">
          <div class="card-head"><h3>${esc(e.title)}</h3><div class="row" style="gap:6px">
            <button class="btn btn-soft btn-sm" data-explain="${e.id}">▶ Play</button>
            <button class="btn btn-ghost btn-sm ex-vidbtn" data-explain="${e.id}" data-explain-mode="video" data-vid="${e.id}">🎬 Video</button></div></div>
          <ol class="small ex-list">${e.steps.map((s) => `<li>${esc(s.text)}</li>`).join("")}</ol></div>`).join("")}
      </div></section>`).join("")}`;
  },
  mount(root) {
    // hide the video buttons of explainers that have no video yet
    loadMedia().then((md) => $$(".ex-vidbtn", root).forEach((b) => { if (!md.video[b.dataset.vid]) b.remove(); }));
    const s = $("#ex-search", root);
    s && s.addEventListener("input", () => {
      const q = s.value.trim().toLowerCase();
      $$(".ex-card", root).forEach((c) => { c.style.display = !q || c.dataset.q.includes(q) ? "" : "none"; });
      $$(".ex-area", root).forEach((a) => { a.style.display = [...$$(".ex-card", a)].some((c) => c.style.display !== "none") ? "" : "none"; });
    });
    const t = $("#tour", root);
    t && t.addEventListener("click", async () => {
      const { startTour } = await import("./tour.js");
      location.hash = "#/school";
      setTimeout(() => startTour("school"), 500);
    });
  },
};
