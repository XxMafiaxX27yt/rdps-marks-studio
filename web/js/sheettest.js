// Developer test for sheetscan.js (not part of the site's pages): draws a filled sheet with made-up names and marks in
// handwriting-like fonts the digit reader never saw, turns it into a "photo" (tilted, uneven light, noise, a little
// blur) and reads it back. From the browser console:
//   const T = await import("./js/sheettest.js"); await T.run({ seed: 1 })
import { G, layout, sheetHash, readSheetCanvas } from "./sheetscan.js";

function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }

export function fakeSheet(seed = 1, n = 25, parts = [{ part: "theory", label: "Written", max: 80 }]) {
  const r = rng(seed);
  const rows = [...Array(n)].map((_, i) => ({ roll: String(i + 1), adm_no: "", name: `Test Student ${i + 1}`, section: "A", values: {} }));
  const t = { cls: "VI", section: "A", exam: "HY", subject: "301", rows };
  const truth = rows.map(() => {
    const v = {};
    const absent = r() < 0.06;
    for (const p of parts) {
      const half = r() < 0.12;
      const whole = Math.floor(r() * (+p.max + (half ? 0 : 1) - (half ? 1 : 0)));
      v[p.part] = absent ? "AB" : String(whole) + (half ? ".5" : "");
    }
    return v;
  });
  return { t, parts, truth, r };
}

/** The filled page as the printer + the teacher's pen would make it, at k px per mm. */
export function drawPage(t, parts, truth, r, k = 7, fonts = ["Segoe Print", "bold italic Comic Sans MS"]) {
  const L = layout(parts);
  const c = document.createElement("canvas");
  const M = 12;                                     // the printer's margin of white paper around the sheet
  c.width = Math.round((G.W + 2 * M) * k); c.height = Math.round((G.H + 2 * M) * k);
  const x = c.getContext("2d");
  x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height);
  x.translate(M * k, M * k);
  const R = (a, b, w, h, col) => { x.fillStyle = col; x.fillRect(a * k, b * k, w * k, h * k); };
  const box = (a, b, w, h) => { x.strokeStyle = "#C5CED6"; x.lineWidth = 0.25 * k; x.strokeRect(a * k, b * k, w * k, h * k); };
  G.markers.forEach(([a, b], i) => { R(a, b, G.marker, G.marker, "#000"); if (i === 0) R(a + 2.4, b + 2.4, 3.2, 3.2, "#fff"); });
  x.fillStyle = "#1F2933"; x.font = `bold ${4 * k}px Arial`; x.fillText("Rukmini Devi Public School · Marks sheet", 40 * k, 6 * k);
  const ink = () => (r() < 0.5 ? "#1C2F8F" : "#111");
  const pen = (ch, a, b, w, h) => {
    const f = fonts[Math.floor(r() * fonts.length)];
    const size = h * (0.75 + r() * 0.3) * k;
    x.save();
    x.translate((a + w / 2 + (r() - 0.5) * 1.2) * k, (b + h / 2 + (r() - 0.5) * 1.0) * k);
    x.rotate((r() - 0.5) * 0.35);
    x.fillStyle = ink(); x.font = `${f.startsWith("bold") ? "" : ""}${size}px ${f.replace(/^bold italic /, "")}`;
    if (f.startsWith("bold")) x.font = `bold italic ${size}px ${f.replace(/^bold italic /, "")}`;
    x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText(ch, 0, 0);
    x.restore();
  };
  const tickMark = (a, b) => {
    x.strokeStyle = ink(); x.lineWidth = 0.45 * k; x.beginPath();
    x.moveTo((a + 0.8) * k, (b + G.tick * 0.55) * k); x.lineTo((a + G.tick * 0.42) * k, (b + G.tick - 0.7) * k); x.lineTo((a + G.tick - 0.5) * k, (b + 0.6) * k);
    x.stroke();
  };
  const sums = {};
  t.rows.slice(0, G.rows).forEach((row, i) => {
    const y = G.rowTop + i * G.rowH, by = y + (G.rowH - G.boxH) / 2;
    if (i % 2) R(0, y, G.W, G.rowH, "#F6F9FB");
    x.fillStyle = "#1F2933"; x.font = `${3.2 * k}px Arial`; x.fillText(row.name, 21 * k, (y + 5.6) * k);
    const v = truth[i];
    for (const c of L.cols) {
      c.boxes.forEach((b) => box(b.x, by, b.w, G.boxH));
      box(c.half.x, by + (G.boxH - G.tick) / 2, G.tick, G.tick);
      const val = v[c.part];
      if (val === "AB") continue;
      const [whole, half] = val.split(".");
      const ds = whole.split("");
      const pad = r() < 0.4 && ds.length < c.boxes.length;          // sometimes "07", mostly "7" in the last box
      const digits = pad ? [...Array(c.boxes.length - ds.length).fill("0"), ...ds] : ds;
      digits.forEach((d, j) => { const b = c.boxes[c.boxes.length - digits.length + j]; pen(d, b.x, by, b.w, G.boxH); });
      if (half) tickMark(c.half.x, by + (G.boxH - G.tick) / 2);
      sums[c.part] = (sums[c.part] || 0) + +val;
    }
    box(L.absent.x, by + (G.boxH - G.tick) / 2, G.tick, G.tick);
    if (Object.values(v).includes("AB")) tickMark(L.absent.x, by + (G.boxH - G.tick) / 2);
  });
  for (const tt of L.totals) {
    const by = G.totalTop + (G.rowH - G.boxH) / 2;
    tt.boxes.forEach((b) => box(b.x, by, b.w, G.boxH));
    box(tt.half.x, by + (G.boxH - G.tick) / 2, G.tick, G.tick);
    const s = sums[tt.part] || 0;
    const [whole, half] = String(s).split(".");
    whole.split("").forEach((d, j) => { const b = tt.boxes[tt.boxes.length - whole.length + j]; pen(d, b.x, by, b.w, G.boxH); });
    if (half) tickMark(tt.half.x, by + (G.boxH - G.tick) / 2);
  }
  const hash = sheetHash(t, parts);
  const bits = [...Array(12)].map((_, i) => (i < 4 ? (1 >> (3 - i)) & 1 : (hash >> (11 - i)) & 1));
  bits.forEach((b, i) => { if (b) R(G.codeX + i * (G.codeCell + G.codeGap), G.codeTop, G.codeCell, G.codeCell, "#000"); });
  return c;
}

/** Turns the clean page into a phone photo: the page tilted in a bigger picture, light from one side, grain, blur. */
export function photograph(page, r, { tilt = 0.08, blur = 0.6, turn = 0 } = {}) {
  const W = 1500, H = 2000;
  const out = document.createElement("canvas");
  out.width = W; out.height = H;
  const o = out.getContext("2d");
  const src = page.getContext("2d").getImageData(0, 0, page.width, page.height);
  // where the page corners land (a random quadrilateral), then the inverse map photo -> page
  const j = (s) => (r() - 0.5) * s;
  let quad = [[180 + j(140), 170 + j(140)], [1320 + j(140), 200 + j(140)], [1350 + j(140), 1830 + j(140)], [150 + j(140), 1800 + j(140)]];
  quad = quad.map(([a, b]) => [a + tilt * j(800), b + tilt * j(800)]);
  for (let k = 0; k < turn; k++) quad = [quad[3], quad[0], quad[1], quad[2]];
  const pw = page.width, ph = page.height;
  const Hinv = homog([[0, 0], [pw, 0], [pw, ph], [0, ph]], quad, true);
  const img = o.createImageData(W, H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const [u, v] = Hinv(x, y);
    const k4 = (y * W + x) * 4;
    const light = 0.78 + 0.25 * (x / W) - 0.1 * (y / H);
    let R0 = 70, G1 = 60, B2 = 55;                                   // a wooden table
    if (u >= 0 && v >= 0 && u < pw - 1 && v < ph - 1) {
      const p = (Math.floor(v) * pw + Math.floor(u)) * 4;
      R0 = src.data[p]; G1 = src.data[p + 1]; B2 = src.data[p + 2];
    }
    const n = (r() - 0.5) * 18;
    img.data[k4] = Math.max(0, Math.min(255, R0 * light + n));
    img.data[k4 + 1] = Math.max(0, Math.min(255, G1 * light + n));
    img.data[k4 + 2] = Math.max(0, Math.min(255, B2 * light * 0.95 + n));
    img.data[k4 + 3] = 255;
  }
  o.putImageData(img, 0, 0);
  if (blur) { const b = document.createElement("canvas"); b.width = W; b.height = H; const bc = b.getContext("2d"); bc.filter = `blur(${blur}px)`; bc.drawImage(out, 0, 0); return b; }
  return out;
}

function homog(src, dst, inverse) {
  // reuse the same maths as sheetscan (solve 8x8); inverse=true gives dst -> src
  const [a, b] = inverse ? [dst, src] : [src, dst];
  const A = [], v = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = a[i], [u, w] = b[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); v.push(u);
    A.push([0, 0, 0, x, y, 1, -w * x, -w * y]); v.push(w);
  }
  for (let c = 0; c < 8; c++) {
    let p = c; for (let q = c + 1; q < 8; q++) if (Math.abs(A[q][c]) > Math.abs(A[p][c])) p = q;
    [A[c], A[p]] = [A[p], A[c]]; [v[c], v[p]] = [v[p], v[c]];
    for (let q = 0; q < 8; q++) { if (q === c) continue; const f = A[q][c] / A[c][c]; for (let k = c; k < 8; k++) A[q][k] -= f * A[c][k]; v[q] -= f * v[c]; }
  }
  const h = v.map((x, i) => x / A[i][i]);
  return (x, y) => { const d = h[6] * x + h[7] * y + 1; return [(h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d]; };
}

/** One full round: -> {right, wrongSure, unsure, blankWrong, total, details} */
export async function run({ seed = 1, parts, tilt = 0.08, blur = 0.6, turn = 0, show = false } = {}) {
  const f = fakeSheet(seed, 25, parts);
  const page = drawPage(f.t, f.parts, f.truth, f.r);
  const photo = photograph(page, f.r, { tilt, blur, turn });
  if (show) { photo.style.cssText = "position:fixed;right:8px;top:8px;height:90vh;z-index:9999;border:2px solid red"; document.body.appendChild(photo); }
  const res = await readSheetCanvas(photo, f.t, f.parts);
  if (res.error) return { error: res.error };
  let right = 0, wrongSure = 0, unsure = 0, total = 0;
  const details = [];
  res.rows.forEach((row) => {
    for (const p of f.parts) {
      total++;
      const want = f.truth[row.i][p.part];
      const got = row.absent ? "AB" : row.marks[p.part].value;
      const sure = row.absent || row.marks[p.part].sure;
      if (got === want) right++;
      else if (sure) { wrongSure++; details.push(`row ${row.i + 1}: wrote ${want}, read ${got} (sure)`); }
      if (!sure) { unsure++; if (got !== want) details.push(`row ${row.i + 1}: wrote ${want}, read ${got || "–"} (asked)`); }
    }
  });
  return { right, wrongSure, unsure, total, page: res.page, warnings: res.warnings, totals: res.totals, sharp: res.sharp, details };
}
