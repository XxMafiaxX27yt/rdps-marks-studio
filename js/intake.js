// One way in for every file, from any page: the engine works out what it is (board results Class XII / X,
// a class list, or school exam marks) and puts it in the right place. It only asks when a file could be
// either school marks or board results.
import * as engine from "./engine.js";
import { S } from "./state.js";
import { esc, toast, modal } from "./ui.js";
import { readPdf, readImage } from "./files.js";

const KIND_WORDS = { school: "School marks", board: "Board results", class_list: "Class list" };

function askKind(name, why, hint) {
  return new Promise((resolve) => {
    const m = modal(`<h2>What is this file?</h2><p class="muted"><b>${esc(name)}</b><br>${esc(why)}</p>
      <div class="stack ask-kind" data-hint="${esc(hint)}">
        <button class="btn btn-ghost" data-k="school">📝 School exam marks <span class="muted small">(PT, Half Yearly, Yearly, Pre Board…)</span></button>
        <button class="btn btn-ghost" data-k="board_XII">🎓 Board results - Class XII</button>
        <button class="btn btn-ghost" data-k="board_X">🎓 Board results - Class X</button>
        <button class="btn btn-ghost" data-k="class_list">👥 Class list <span class="muted small">(who is in which section)</span></button>
      </div>`, { onClose: () => resolve("") });
    const pre = m.el.querySelector(`[data-k="${hint}"]`);
    if (pre) { pre.classList.add("likely"); pre.insertAdjacentHTML("beforeend", ` <span class="badge b-track">likely</span>`); }
    m.el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-k]");
      if (!b) return;
      resolve(b.dataset.k);
      m.el.remove();
    });
  });
}

/** Adds one file. hint = the page it was dropped on ("school" / "board" / "class_list"), used only when the
 *  file itself could be either. cls = the class picked on the School page ("" = the file says).
 *  onProgress(0..1) for PDFs and photos. -> the engine's answer, or null. */
export async function addAny(file, { hint = "", cls = "", onProgress } = {}) {
  const low = file.name.toLowerCase();
  let pages = null, bytes = null;
  if (low.endsWith(".pdf")) pages = await readPdf(file, onProgress);
  else if (/\.(png|jpe?g|webp)$/.test(low)) pages = await readImage(file, onProgress);
  else bytes = new Uint8Array(await file.arrayBuffer());
  // the page it was dropped on is only shown as the likely answer - a file that could be either is always asked about
  const send = (prefer) => pages ? engine.call("add_any_pages", file.name, JSON.stringify(pages), prefer, "", cls)
    : engine.call("add_any", file.name, bytes, prefer, "", cls);
  let info = await send("");
  if (info.kind === "ask") {
    const choice = await askKind(file.name, info.why, hint === "board" ? "board_XII" : hint);
    if (!choice) { toast(`${esc(file.name)} was not added.`, "warn"); return null; }
    info = await send(choice);
  }
  if (!(info.kind === "our_workbook" && hint === "school")) announce(file.name, info, pages && pages.some((p) => p.ocr));
  if (info.kind === "board") S.board = null;
  if (info.kind === "class_list") S.classLists = info.class_lists;
  if (info.kind === "school") S.summary = null;
  S.files = null;                     // the School page's file list changes with every kind
  return info;
}

function announce(name, info, ocr) {
  if (info.kind === "board") {
    toast(`<b>${esc(name)}</b>: board results, Class ${esc(info.cls || "?")}${info.year ? " " + esc(info.year) : ""} · ${info.students} students → <a href="#/board">Board results</a>`, "ok", 7000);
  } else if (info.kind === "class_list") {
    const l = info.lists.map((x) => `${x.cls || "?"}${x.section ? "-" + x.section : ""} (${x.count})`).join(", ");
    const need = info.lists.some((x) => x.needs);
    toast(`<b>${esc(name)}</b>: class list ${esc(l)} → <a href="#/teachers">Teachers · Class lists</a>${need ? " - please type which class and section it is there." : ""}`, need ? "warn" : "ok", 7000);
  } else if (info.kind === "school") {
    toast(`<b>${esc(name)}</b>: school marks${ocr ? " (read from a scan - please check carefully)" : ""} → <a href="#/school">School results</a>`, ocr ? "warn" : "ok", 4500);
  } else if (info.kind === "our_workbook") {
    toast(`<b>${esc(name)}</b> is a workbook made by this tool - open it on <a href="#/school">School results</a> (“Open workbook…”).`, "info", 7000);
  }
}

export { KIND_WORDS };
