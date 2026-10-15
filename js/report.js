// Printable report cards (one A4 page each) - the browser's "Save as PDF" makes the PDF.
// Charts are drawn as SVG so they print sharp.
import { esc, fmt, fmtMark } from "./ui.js";

const GENTLE_COL = { "Doing well": "#1E8E5A", "Focus area": "#B7791F", "Needs support": "#C0392B" };

function barSvg(rows) {
  const r = rows.filter((x) => x.pct !== null && x.pct !== undefined);
  const H = 22, W = 360, L = 118, top = 8;
  const h = top + r.length * H + 26;
  let s = `<svg viewBox="0 0 ${W} ${h}" xmlns="http://www.w3.org/2000/svg" font-family="Inter, sans-serif" font-size="9">`;
  for (let g = 0; g <= 100; g += 25) {
    const x = L + (W - L - 30) * g / 100;
    s += `<line x1="${x}" y1="${top}" x2="${x}" y2="${h - 18}" stroke="#E2ECF3" stroke-width="1"/><text x="${x}" y="${h - 6}" text-anchor="middle" fill="#5B6B79">${g}</text>`;
  }
  r.forEach((x, i) => {
    const y = top + i * H;
    const w = (W - L - 30) * Math.max(0, x.pct) / 100;
    const cw = (W - L - 30) * Math.max(0, x.class_avg || 0) / 100;
    s += `<text x="${L - 6}" y="${y + 13}" text-anchor="end" fill="#1F2933">${esc(x.name.length > 20 ? x.name.slice(0, 19) + "…" : x.name)}</text>`;
    s += `<rect x="${L}" y="${y + 3}" width="${cw}" height="15" rx="3" fill="#CFE6F3"/>`;
    s += `<rect x="${L}" y="${y + 6}" width="${w}" height="9" rx="3" fill="#06A7E7"/>`;
    s += `<text x="${L + w + 4}" y="${y + 14}" fill="#0B3C5D" font-weight="700">${fmt(x.pct, 1)}</text>`;
  });
  s += `<rect x="${L}" y="${h - 32 + 30}" width="0" height="0"/></svg>`;
  return s;
}

function trendSvg(trend, names) {
  const pts = trend.map((t, i) => ({ i, v: t[1], name: names[t[0]] || t[0] }));
  const W = 260, H = 150, L = 26, R = 16, T = 16, B = 30;
  const n = Math.max(1, pts.length - 1);
  const X = (i) => L + (W - L - R) * (pts.length === 1 ? 0.5 : i / n);
  const Y = (v) => T + (H - T - B) * (1 - v / 100);
  let s = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" font-family="Inter, sans-serif" font-size="8.5">`;
  for (let g = 0; g <= 100; g += 25) s += `<line x1="${L}" y1="${Y(g)}" x2="${W - R}" y2="${Y(g)}" stroke="#E2ECF3"/><text x="${L - 4}" y="${Y(g) + 3}" text-anchor="end" fill="#5B6B79">${g}</text>`;
  const have = pts.filter((p) => p.v !== null && p.v !== undefined);
  if (have.length > 1) s += `<polyline fill="none" stroke="#0B3C5D" stroke-width="2" points="${have.map((p) => `${X(p.i)},${Y(p.v)}`).join(" ")}"/>`;
  const last = pts.length - 1;
  for (const p of pts) {
    s += `<text x="${X(p.i)}" y="${H - 12}" text-anchor="middle" fill="#5B6B79">${esc(p.name.replace("Periodic Test ", "PT").replace("Half Yearly", "HY"))}</text>`;
    if (p.v !== null && p.v !== undefined) {
      const anchor = pts.length > 1 && p.i === 0 ? "start" : (pts.length > 1 && p.i === last ? "end" : "middle");
      const dx = anchor === "start" ? 3 : anchor === "end" ? -3 : 0;
      s += `<circle cx="${X(p.i)}" cy="${Y(p.v)}" r="4" fill="#06A7E7" stroke="#0B3C5D"/><text x="${X(p.i) + dx}" y="${Y(p.v) - 8}" text-anchor="${anchor}" fill="#0B3C5D" font-weight="700" paint-order="stroke" stroke="#fff" stroke-width="3">${fmt(p.v)}</text>`;
    }
  }
  return s + `</svg>`;
}

export function printCards(cards, settings) {
  const r = settings.rules;
  const names = Object.fromEntries(Object.entries(r.exams).map(([k, v]) => [k, v.name]));
  const root = document.getElementById("print-root");
  root.innerHTML = cards.map((c) => {
    const st = c.student;
    const rows = c.rows.map((x) => `<tr><td><b>${esc(x.name)}</b></td><td>${fmtMark(x.theory)}</td><td>${x.practical === null ? "" : fmtMark(x.practical)}</td>
      <td>${x.obtained === null ? "–" : fmtMark(x.obtained)}</td><td>${fmtMark(x.max)}</td><td><b>${x.pct === null ? esc(x.label) : fmt(x.pct)}</b></td>
      <td>${x.class_avg === null ? "–" : fmt(x.class_avg)}</td><td>${esc(x.grade || "–")}</td>
      <td style="color:${GENTLE_COL[x.gentle] || "#1F2933"};font-weight:700">${esc(x.gentle || "")}</td></tr>`).join("");
    return `<section class="pc">
      <div class="pc-top"><img src="assets/img/rdps-logo-white.png" alt=""><div><h1>${esc(r.school_name)}</h1>
        <p>${esc(r.school_place)} · Report card · ${esc(c.exam_name)} · Academic year ${esc(r.academic_year)}</p></div></div>
      <div class="pc-info">
        <div><span>Name</span>${esc(st.name)}</div><div><span>Class</span>${esc(st.cls)}${st.section ? "-" + esc(st.section) : ""}</div>
        <div><span>Roll no</span>${esc(st.roll || "–")}</div><div><span>Admission no</span>${esc(st.adm_no || "–")}</div>
        <div><span>Father's name</span>${esc(st.father || "–")}</div><div><span>Mother's name</span>${esc(st.mother || "–")}</div>
        <div><span>Group</span>${esc(st.group || "–")}</div><div><span>Exam</span>${esc(c.exam_name)}</div></div>
      <table><thead><tr><th>Subject</th><th>${esc(c.th_head || "Theory")}</th><th>${esc(c.pr_head || "Practical")}</th><th>Total</th><th>Max</th><th>%</th><th>Class avg</th><th>Grade</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="ov"><div><b>${fmtMark(c.obtained) || "–"}</b><span>Total</span></div><div><b>${fmtMark(c.max) || "–"}</b><span>Out of</span></div>
        <div><b>${fmt(c.overall, 2)}</b><span>Overall %</span></div><div><b style="font-size:11pt">${esc(c.result || "–")}</b><span>Result</span></div>
        <div><b>${c.rank ?? "–"}</b><span>Rank of ${c.class_size}</span></div></div>
      <div class="charts"><div>${barSvg(c.rows)}<div style="font-size:7.5pt;color:#5B6B79">Blue bar = student, light band = class average</div></div><div>${trendSvg(c.trend, names)}</div></div>
      <div class="rem"><b>Remarks</b><ul>${c.remarks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="sign"><span>Class teacher</span><span>Parent</span><span>Principal</span></div>
      <div class="foot-note"><span>Remarks are written by fixed rules from the marks above.</span><span>RDPS Marks Studio</span></div>
    </section>`;
  }).join("");
  const imgs = [...root.querySelectorAll("img")];
  Promise.all(imgs.map((i) => (i.complete ? 1 : new Promise((r) => { i.onload = i.onerror = r; })))).then(() => {
    setTimeout(() => { window.print(); }, 150);
  });
}
