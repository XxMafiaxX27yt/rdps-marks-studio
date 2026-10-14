// Guided tour for presenting the tool (highlights one thing at a time).
import { $ } from "./ui.js";

const TOURS = {
  school: [
    [".brand", "RDPS Marks Studio", "A website that turns any marks file into a complete Excel report. It runs inside the browser - marks never leave this computer."],
    [".stepper", "Four simple steps", "Upload → Check → Review → Download. The tool shows exactly what it understood before it makes anything."],
    ["#drop", "Any format", "Excel, old .xls, CSV, the CBSE result gazette, PDFs - even scanned printed sheets. Several files at once."],
    ["#sample", "Try it instantly", "Sample data with made-up students shows everything in seconds."],
    ["#engine-chip", "Works offline", "Once loaded, everything works without internet - and nothing is uploaded."],
  ],
  ask: [
    ["#ask-input", "Ask in your own words", "English or Hinglish: “Who is weak in Maths but strong in Physics?”, “Physics mein kaun kamzor hai?”"],
    ["#mic", "Or just speak", "The voice model runs on this computer - the recording never leaves it."],
    [".chips", "Suggested questions", "Built from the real subjects and names in the uploaded marks."],
  ],
  board: [
    ["#bdrop", "CBSE gazette", "Upload the TXT file CBSE sends - every candidate is read and the count is checked against CBSE's own total."],
  ],
};

export function startTour(route) {
  const steps = (TOURS[route] || TOURS.school).filter(([sel]) => $(sel));
  if (!steps.length) return;
  let i = 0;
  const hole = document.createElement("div");
  hole.className = "tour-hole";
  const tip = document.createElement("div");
  tip.className = "tour-tip";
  document.body.append(hole, tip);
  const end = () => { hole.remove(); tip.remove(); document.removeEventListener("keydown", key); };
  const key = (e) => { if (e.key === "Escape") end(); if (e.key === "ArrowRight") next(); if (e.key === "ArrowLeft") prev(); };
  document.addEventListener("keydown", key);
  const show = () => {
    const [sel, title, text] = steps[i];
    const el = $(sel);
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    setTimeout(() => {
      const r = el.getBoundingClientRect();
      const pad = 8;
      Object.assign(hole.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
      tip.innerHTML = `<h3>${title}</h3><p class="muted" style="margin:0 0 12px">${text}</p>
        <div class="row" style="justify-content:space-between"><span class="tiny muted">${i + 1} / ${steps.length}</span>
        <div class="row"><button class="btn btn-ghost btn-sm" id="t-end">Close</button>${i ? `<button class="btn btn-ghost btn-sm" id="t-prev">Back</button>` : ""}
        <button class="btn btn-primary btn-sm" id="t-next">${i === steps.length - 1 ? "Finish" : "Next"}</button></div></div>`;
      const below = r.bottom + 220 < innerHeight;
      tip.style.left = Math.max(12, Math.min(innerWidth - 360, r.left)) + "px";
      tip.style.top = (below ? r.bottom + 18 : Math.max(12, r.top - 200)) + "px";
      $("#t-next").onclick = next;
      $("#t-end").onclick = end;
      const p = $("#t-prev"); if (p) p.onclick = prev;
    }, 350);
  };
  const next = () => { if (i < steps.length - 1) { i++; show(); } else end(); };
  const prev = () => { if (i > 0) { i--; show(); } };
  show();
}
