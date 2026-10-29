// Paper mark sheets: print a boxed sheet with the names already on it, the teacher writes the marks by hand (one
// digit per box), takes a photo, and the marks are read here - in this browser, nothing is uploaded.
// The four black squares in the corners tell where everything is: the photo is straightened with them (a homography)
// and every box is cut out and read by a small digit reader (assets/sheet/digits.json, made by
// tools/digits_train.py). Every mark is shown next to its picture so the teacher checks it before saving.
import { esc } from "./ui.js";

// ---------------------------------------------------------------- the sheet, in mm (inside the 12 mm print margin)
export const G = {
  W: 186, H: 270, marker: 8,
  markers: [[0, 0], [178, 0], [178, 262], [0, 262]],          // TL (a ring: tells which way up), TR, BR, BL
  headTop: 22, headH: 6, rowTop: 28, rowH: 8.5, rows: 25,       // 25 students a page
  totalTop: 243, codeTop: 255.5, codeX: 16, codeCell: 3.4, codeGap: 1.2,
  boxW: 6.6, boxH: 6.6, gap: 0.9, tick: 4.6, right: 184,
};
const CODE_BITS = 12;                                            // 4 bits page number + 8 bits check of the roster

const digitsOf = (mx) => String(Math.floor(+mx)).length;

/** Where everything is on a page: parts = [{part, label, max}] (what is typed: Written /80, Portfolio /5 ...). */
export function layout(parts) {
  let x = G.right;
  const absent = { x: x - G.tick, w: G.tick };
  x = absent.x - 4;
  const cols = [];
  for (const p of [...parts].reverse()) {
    const half = { x: x - G.tick, w: G.tick };
    x = half.x - 1.6;
    const boxes = [];
    for (let i = 0; i < digitsOf(p.max); i++) {
      boxes.unshift({ x: x - G.boxW, w: G.boxW });
      x -= G.boxW + G.gap;
    }
    x -= 3.2;
    cols.unshift({ ...p, boxes, half, x0: boxes[0].x - 0.6, x1: half.x + G.tick + 0.6 });
  }
  // the page totals row: per part, enough boxes for 25 students' marks
  let tx = 46;
  const totals = parts.map((p) => {
    const n = digitsOf(p.max * G.rows);
    const t = { part: p.part, label: p.label, lx: tx, boxes: [] };
    tx += Math.max(16, p.label.length * 1.9 + 4);
    for (let i = 0; i < n; i++) { t.boxes.push({ x: tx, w: G.boxW }); tx += G.boxW + G.gap; }
    t.half = { x: tx + 1, w: G.tick };
    tx += G.tick + 8;
    return t;
  });
  return { cols, absent, totals, nameX1: x };
}
const rowY = (i) => G.rowTop + i * G.rowH + (G.rowH - G.boxH) / 2;

/** 8 bits from everything that must match between the printed sheet and the screen (names, class, exam, subject). */
export function sheetHash(t, parts) {
  const s = [t.cls, t.section, t.exam, t.subject, parts.map((p) => p.part).join(","),
    ...t.rows.map((r) => `${r.roll}|${(r.name || "").trim().toLowerCase()}`)].join("\n");
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return (h ^ (h >>> 8) ^ (h >>> 16) ^ (h >>> 24)) & 0xff;
}
const codeBits = (page, hash) => [...Array(CODE_BITS)].map((_, i) => (i < 4 ? (page >> (3 - i)) & 1 : (hash >> (11 - i)) & 1));

// ---------------------------------------------------------------- printing
/** HTML for the sheets (one A4 page per 25 students), for #print-root. */
export function sheetsHtml(t, parts, info) {
  const L = layout(parts);
  const hash = sheetHash(t, parts);
  const pages = [];
  for (let s = 0, pg = 1; s < Math.max(1, t.rows.length); s += G.rows, pg++) pages.push({ pg, rows: t.rows.slice(s, s + G.rows), start: s });
  const abs = (x, y, w, h, extra = "") => `position:absolute;left:${x}mm;top:${y}mm;width:${w}mm;height:${h}mm;${extra}`;
  const box = (x, y, w = G.boxW, h = G.boxH) => `<div style="${abs(x, y, w, h, "border:0.25mm solid #C5CED6;border-radius:0.6mm;box-sizing:border-box")}"></div>`;
  const tick = (x, y) => `<div style="${abs(x, y + (G.boxH - G.tick) / 2, G.tick, G.tick, "border:0.25mm solid #C5CED6;box-sizing:border-box")}"></div>`;
  return pages.map(({ pg, rows, start }) => {
    const bits = codeBits(pg, hash);
    let h = `<section class="ms-page" style="position:relative;width:${G.W}mm;height:${G.H}mm;overflow:hidden;font-family:Arial,sans-serif;color:#1F2933">`;
    G.markers.forEach(([x, y], k) => {
      h += `<div style="${abs(x, y, G.marker, G.marker, "background:#000")}">${k === 0 ? `<div style="${abs(2.4, 2.4, 3.2, 3.2, "background:#fff")}"></div>` : ""}</div>`;
    });
    h += `<div style="${abs(12, 0.5, 162, 8, "font-size:12pt;font-weight:700;text-align:center")}">${esc(info.school)} · Marks sheet</div>
      <div style="${abs(12, 7.5, 162, 6, "font-size:10.5pt;text-align:center")}"><b>${esc(info.cls)}</b> · ${esc(info.exam)} · <b>${esc(info.subject)}</b> · page ${pg} of ${pages.length}</div>
      <div style="${abs(12, 14, 162, 6, "font-size:7.5pt;text-align:center;color:#5B6B79")}">Write <b>one digit in each box</b> with a dark pen (e.g. 0 7 or 7 alone in the last box). Tick ½ for a half mark, tick A if absent.
        Keep the black squares clean; photograph the whole page flat, in good light.</div>`;
    // column headings
    h += `<div style="${abs(2, G.headTop, 7, G.headH, "font-size:7.5pt;font-weight:700")}">#</div>
      <div style="${abs(9, G.headTop, 12, G.headH, "font-size:7.5pt;font-weight:700")}">Roll</div>
      <div style="${abs(21, G.headTop, 60, G.headH, "font-size:7.5pt;font-weight:700")}">Name</div>`;
    for (const c of L.cols) h += `<div style="${abs(c.x0, G.headTop, c.x1 - c.x0, G.headH, "font-size:7pt;font-weight:700;text-align:center;white-space:nowrap")}">${esc(c.label)} /${esc(String(c.max))} · ½</div>`;
    h += `<div style="${abs(L.absent.x - 1, G.headTop, G.tick + 2, G.headH, "font-size:7pt;font-weight:700;text-align:center")}">A</div>`;
    rows.forEach((r, i) => {
      const y = G.rowTop + i * G.rowH;
      h += `<div style="${abs(0, y, G.W, G.rowH, `border-top:0.2mm solid #DCE3EA;${i % 2 ? "background:#F6F9FB" : ""}`)}"></div>
        <div style="${abs(2, y + 2, 7, 5, "font-size:8pt;color:#5B6B79")}">${start + i + 1}</div>
        <div style="${abs(9, y + 2, 12, 5, "font-size:8.5pt")}">${esc(r.roll || "")}</div>
        <div style="${abs(21, y + 1.9, L.nameX1 - 22, 5, "font-size:9pt;white-space:nowrap;overflow:hidden")}">${esc(r.name || "")}</div>`;
      for (const c of L.cols) {
        for (const b of c.boxes) h += box(b.x, rowY(i));
        h += tick(c.half.x, rowY(i));
      }
      h += tick(L.absent.x, rowY(i));
    });
    // page total (to check the reading) and the code strip
    h += `<div style="${abs(0, G.totalTop - 1, G.W, G.rowH + 2, "border-top:0.4mm solid #0B3C5D")}"></div>
      <div style="${abs(2, G.totalTop + 1.5, 44, 6, "font-size:8pt;font-weight:700")}">Total of this page →</div>`;
    for (const tt of L.totals) {
      h += `<div style="${abs(tt.lx, G.totalTop + 1.8, 16, 5, "font-size:7pt;white-space:nowrap")}">${esc(tt.label)}</div>`;
      for (const b of tt.boxes) h += box(b.x, G.totalTop + (G.rowH - G.boxH) / 2);
      h += tick(tt.half.x, G.totalTop + (G.rowH - G.boxH) / 2);
    }
    bits.forEach((b, i) => {
      h += `<div style="${abs(G.codeX + i * (G.codeCell + G.codeGap), G.codeTop, G.codeCell, G.codeCell, b ? "background:#000" : "border:0.2mm solid #C5CED6;box-sizing:border-box")}"></div>`;
    });
    h += `<div style="${abs(G.codeX + CODE_BITS * (G.codeCell + G.codeGap) + 3, G.codeTop - 0.3, 120, 5, "font-size:7pt;color:#5B6B79")}">Sheet ${pg}/${pages.length} · check ${hash.toString(16).toUpperCase().padStart(2, "0")} · RDPS Marks Studio</div>`;
    return h + `</section>`;
  }).join("");
}

// ---------------------------------------------------------------- the digit reader (same network as tools/digits_train.py)
let NET = null;
async function net() {
  if (NET) return NET;
  const d = await (await fetch(new URL("../assets/sheet/digits.json", import.meta.url))).json();
  const L = {};
  for (const [k, v] of Object.entries(d.layers)) {
    const bin = atob(v.data);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    L[k] = { shape: v.shape, w: new Float32Array(u8.buffer) };
  }
  NET = L;
  return L;
}

function conv(x, C, H, W, k, b) {                  // 3x3, padding 1, then ReLU
  const O = k.shape[0], out = new Float32Array(O * H * W);
  for (let o = 0; o < O; o++) {
    for (let y = 0; y < H; y++) for (let xx = 0; xx < W; xx++) {
      let s = b.w[o];
      for (let c = 0; c < C; c++) {
        const kb = ((o * C + c) * 3) * 3, xb = c * H * W;
        for (let dy = -1; dy <= 1; dy++) {
          const yy = y + dy;
          if (yy < 0 || yy >= H) continue;
          for (let dx = -1; dx <= 1; dx++) {
            const x2 = xx + dx;
            if (x2 < 0 || x2 >= W) continue;
            s += k.w[kb + (dy + 1) * 3 + (dx + 1)] * x[xb + yy * W + x2];
          }
        }
      }
      out[(o * H + y) * W + xx] = s > 0 ? s : 0;
    }
  }
  return out;
}
function pool(x, C, H, W) {                        // 2x2 max pool (floor)
  const h = Math.floor(H / 2), w = Math.floor(W / 2), out = new Float32Array(C * h * w);
  for (let c = 0; c < C; c++) for (let y = 0; y < h; y++) for (let xx = 0; xx < w; xx++) {
    const b = c * H * W + 2 * y * W + 2 * xx;
    out[(c * h + y) * w + xx] = Math.max(x[b], x[b + 1], x[b + W], x[b + W + 1]);
  }
  return out;
}
function dense(x, k, b, relu) {
  const [O, I] = k.shape, out = new Float32Array(O);
  for (let o = 0; o < O; o++) {
    let s = b.w[o];
    for (let i = 0; i < I; i++) s += k.w[o * I + i] * x[i];
    out[o] = relu && s < 0 ? 0 : s;
  }
  return out;
}
/** 28x28 (1 = ink) -> probabilities of 0-9 and "not a digit". */
export function classify(L, img) {
  let x = conv(img, 1, 28, 28, L["c1.weight"], L["c1.bias"]);
  x = pool(x, 16, 28, 28);
  x = pool(conv(x, 16, 14, 14, L["c2.weight"], L["c2.bias"]), 32, 14, 14);
  x = pool(conv(x, 32, 7, 7, L["c3.weight"], L["c3.bias"]), 48, 7, 7);
  x = dense(x, L["f1.weight"], L["f1.bias"], true);
  const z = dense(x, L["f2.weight"], L["f2.bias"], false);
  const m = Math.max(...z), e = z.map((v) => Math.exp(v - m)), s = e.reduce((a, b) => a + b, 0);
  return e.map((v) => v / s);
}

/** The same as digits_train.normalise: the ink fitted into 20x20 and centred by its centre of mass in 28x28. */
export function normalise(ink, S) {
  let y0 = S, y1 = -1, x0 = S, x1 = -1, n = 0;
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) if (ink[y * S + x] > 0.25) {
    n++; if (y < y0) y0 = y; if (y > y1) y1 = y; if (x < x0) x0 = x; if (x > x1) x1 = x;
  }
  if (n < 6) return null;
  const h = y1 - y0 + 1, w = x1 - x0 + 1, s = 20 / Math.max(h, w);
  const nh = Math.max(1, Math.round(h * s)), nw = Math.max(1, Math.round(w * s));
  const small = new Float32Array(nh * nw);
  for (let y = 0; y < nh; y++) for (let x = 0; x < nw; x++) {       // area average (like INTER_AREA)
    const sy0 = y0 + y / s, sy1 = y0 + (y + 1) / s, sx0 = x0 + x / s, sx1 = x0 + (x + 1) / s;
    let acc = 0, wsum = 0;
    for (let yy = Math.floor(sy0); yy < Math.ceil(sy1); yy++) {
      const wy = Math.min(yy + 1, sy1) - Math.max(yy, sy0);
      for (let xx = Math.floor(sx0); xx < Math.ceil(sx1); xx++) {
        const wx = Math.min(xx + 1, sx1) - Math.max(xx, sx0);
        if (wy > 0 && wx > 0 && yy < S && xx < S) { acc += ink[yy * S + xx] * wy * wx; wsum += wy * wx; }
      }
    }
    small[y * nw + x] = wsum ? acc / wsum : 0;
  }
  let tot = 0, cy = 0, cx = 0;
  for (let y = 0; y < nh; y++) for (let x = 0; x < nw; x++) { const v = small[y * nw + x]; tot += v; cy += v * y; cx += v * x; }
  let oy = Math.round(14 - cy / tot), ox = Math.round(14 - cx / tot);
  oy = Math.min(Math.max(oy, 0), 28 - nh); ox = Math.min(Math.max(ox, 0), 28 - nw);
  const out = new Float32Array(784);
  let mx = 1e-6;
  for (let y = 0; y < nh; y++) for (let x = 0; x < nw; x++) { const v = small[y * nw + x]; out[(oy + y) * 28 + ox + x] = v; if (v > mx) mx = v; }
  for (let i = 0; i < 784; i++) out[i] = Math.min(1, out[i] / mx);
  return out;
}

// ---------------------------------------------------------------- the photo
function grayOf(canvas) {
  const { width: w, height: h } = canvas;
  const d = canvas.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, w, h).data;
  const g = new Float32Array(w * h);
  for (let i = 0, j = 0; i < g.length; i++, j += 4) g[i] = 0.299 * d[j] + 0.587 * d[j + 1] + 0.114 * d[j + 2];
  return { g, w, h };
}

/** How sharp the photo is (variance of the Laplacian, on a 900 px wide copy). */
function sharpness(G0) {
  const s = Math.max(1, Math.floor(G0.w / 900)), w = Math.floor(G0.w / s), h = Math.floor(G0.h / s);
  const g = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) g[y * w + x] = G0.g[(y * s) * G0.w + x * s];
  let n = 0, m = 0, m2 = 0;
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x, l = g[i - 1] + g[i + 1] + g[i - w] + g[i + w] - 4 * g[i];
    n++; m += l; m2 += l * l;
  }
  return m2 / n - (m / n) ** 2;
}

/** The four corner squares: dark blobs that are square-ish and solid, the ones nearest the corners of the page. */
function findMarkers(G0) {
  const s = Math.max(1, Math.round(G0.w / 1000)), w = Math.floor(G0.w / s), h = Math.floor(G0.h / s);
  const g = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) g[y * w + x] = G0.g[(y * s) * G0.w + x * s];
  // dark = clearly darker than the neighbourhood (works with uneven light); integral image for the local mean
  const R = Math.max(8, Math.round(w / 20)), I = new Float64Array((w + 1) * (h + 1));
  for (let y = 0; y < h; y++) { let row = 0; for (let x = 0; x < w; x++) { row += g[y * w + x]; I[(y + 1) * (w + 1) + x + 1] = I[y * (w + 1) + x + 1] + row; } }
  const dark = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const xa = Math.max(0, x - R), xb = Math.min(w, x + R + 1), ya = Math.max(0, y - R), yb = Math.min(h, y + R + 1);
    const mean = (I[yb * (w + 1) + xb] - I[ya * (w + 1) + xb] - I[yb * (w + 1) + xa] + I[ya * (w + 1) + xa]) / ((xb - xa) * (yb - ya));
    dark[y * w + x] = g[y * w + x] < Math.min(mean * 0.62, 110) ? 1 : 0;
  }
  // connected blobs
  const lab = new Int32Array(w * h), blobs = [];
  const stack = [];
  for (let i = 0; i < w * h; i++) {
    if (!dark[i] || lab[i]) continue;
    const id = blobs.length + 1;
    let n = 0, sx = 0, sy = 0, x0 = w, x1 = 0, y0 = h, y1 = 0;
    stack.push(i); lab[i] = id;
    while (stack.length) {
      const p = stack.pop(), px = p % w, py = (p - px) / w;
      n++; sx += px; sy += py;
      if (px < x0) x0 = px; if (px > x1) x1 = px; if (py < y0) y0 = py; if (py > y1) y1 = py;
      for (const q of [p - 1, p + 1, p - w, p + w]) {
        if (q < 0 || q >= w * h || lab[q] || !dark[q]) continue;
        if ((q === p - 1 && px === 0) || (q === p + 1 && px === w - 1)) continue;
        lab[q] = id; stack.push(q);
      }
    }
    blobs.push({ n, cx: sx / n, cy: sy / n, bw: x1 - x0 + 1, bh: y1 - y0 + 1, x0, y0 });
  }
  const minS = w * 0.012, maxS = w * 0.09;
  const cand = blobs.filter((b) => b.bw >= minS && b.bh >= minS && b.bw <= maxS && b.bh <= maxS &&
    b.bw / b.bh > 0.55 && b.bw / b.bh < 1.8 && b.n / (b.bw * b.bh) > 0.45);
  if (cand.length < 4) return null;
  // biggest similar-sized ones first, then the four outermost
  const area = cand.map((b) => b.n).sort((a, b) => b - a)[Math.min(3, cand.length - 1)];
  const big = cand.filter((b) => b.n > area * 0.35);
  const pick = (f) => big.reduce((a, b) => (f(b) > f(a) ? b : a));
  const tl = pick((b) => -(b.cx + b.cy)), br = pick((b) => b.cx + b.cy), tr = pick((b) => b.cx - b.cy), bl = pick((b) => b.cy - b.cx);
  const four = [tl, tr, br, bl];
  if (new Set(four).size < 4) return null;
  // the ring (white hole in the middle) is the sheet's top-left: turn the order until it comes first
  const hole = four.map((b) => {
    const cx = Math.round(b.cx), cy = Math.round(b.cy);
    return dark[cy * w + cx] ? 0 : 1;
  });
  const k = hole.indexOf(1);
  if (k < 0 || hole.filter(Boolean).length !== 1) return null;
  const ordered = [...four.slice(k), ...four.slice(0, k)];
  return ordered.map((b) => [(b.cx + 0.5) * s, (b.cy + 0.5) * s]);
}

/** Homography from 4 point pairs (sheet mm -> photo px): solve the 8x8 system. */
function homography(src, dst) {
  const A = [], bv = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); bv.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); bv.push(v);
  }
  for (let c = 0; c < 8; c++) {                       // Gaussian elimination with pivoting
    let p = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]]; [bv[c], bv[p]] = [bv[p], bv[c]];
    for (let r = 0; r < 8; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      for (let k = c; k < 8; k++) A[r][k] -= f * A[c][k];
      bv[r] -= f * bv[c];
    }
  }
  const h = bv.map((v, i) => v / A[i][i]);
  return (x, y) => { const d = h[6] * x + h[7] * y + 1; return [(h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d]; };
}

function sampleAt(G0, x, y) {                         // bilinear
  const x0 = Math.floor(x), y0 = Math.floor(y);
  if (x0 < 0 || y0 < 0 || x0 >= G0.w - 1 || y0 >= G0.h - 1) return 255;
  const fx = x - x0, fy = y - y0, i = y0 * G0.w + x0, g = G0.g;
  return g[i] * (1 - fx) * (1 - fy) + g[i + 1] * fx * (1 - fy) + g[i + G0.w] * (1 - fx) * fy + g[i + G0.w + 1] * fx * fy;
}

/** A box of the sheet as ink (1 = ink): S x S samples of it, a little inside its printed edge (so big digits are not
 *  cut), with any straight line along the edges (the printed box, seen slightly off) taken out. */
function boxInk(G0, H, x, y, w, h, S = 40, inset = 0.05) {
  const raw = new Float32Array(S * S);
  for (let j = 0; j < S; j++) for (let i = 0; i < S; i++) {
    const mx = x + w * (inset + (1 - 2 * inset) * (i + 0.5) / S), my = y + h * (inset + (1 - 2 * inset) * (j + 0.5) / S);
    const [px, py] = H(mx, my);
    raw[j * S + i] = sampleAt(G0, px, py);
  }
  // paper brightness = a bright value of the box itself (its paper), ink = darker than that by a clear margin
  const sorted = Float32Array.from(raw).sort();
  const paper = sorted[Math.floor(S * S * 0.85)];
  const ink = new Float32Array(S * S);
  let n = 0;
  for (let k = 0; k < S * S; k++) {
    const v = (paper - raw[k]) / Math.max(40, paper * 0.55);
    ink[k] = v < 0.38 ? 0 : Math.min(1, v);              // the light grey printed box edge stays out
  }
  // a row or column near the edge that is ink almost end to end is the box's own edge (a "1" is never that long)
  const band = Math.round(S * 0.15);
  for (let j = 0; j < S; j++) {
    if (j >= band && j < S - band) continue;
    let c = 0;
    for (let i = 0; i < S; i++) if (ink[j * S + i] > 0.3) c++;
    if (c > S * 0.8) for (let i = 0; i < S; i++) ink[j * S + i] = 0;
  }
  for (let i = 0; i < S; i++) {
    if (i >= band && i < S - band) continue;
    let c = 0;
    for (let j = 0; j < S; j++) if (ink[j * S + i] > 0.3) c++;
    if (c > S * 0.8) for (let j = 0; j < S; j++) ink[j * S + i] = 0;
  }
  for (let k = 0; k < S * S; k++) if (ink[k] > 0.35) n++;
  return { ink, S, share: n / (S * S) };
}

function patchUrl(G0, H, x, y, w, h, pxPerMm = 6) {
  const W = Math.round(w * pxPerMm), Hh = Math.round(h * pxPerMm);
  const c = document.createElement("canvas");
  c.width = W; c.height = Hh;
  const ctx = c.getContext("2d"), im = ctx.createImageData(W, Hh);
  for (let j = 0; j < Hh; j++) for (let i = 0; i < W; i++) {
    const [px, py] = H(x + (i + 0.5) / pxPerMm, y + (j + 0.5) / pxPerMm);
    const v = sampleAt(G0, px, py), k = (j * W + i) * 4;
    im.data[k] = im.data[k + 1] = im.data[k + 2] = v; im.data[k + 3] = 255;
  }
  ctx.putImageData(im, 0, 0);
  return c.toDataURL("image/png");
}

/** Reads one number from its digit boxes (+ the ½ tick). -> {value, sure, why, digits} */
function readNumber(G0, H, L, boxes, half, y) {
  const digits = [];
  let sure = true, why = "", empty = 0;
  for (const b of boxes) {
    const { ink, S, share } = boxInk(G0, H, b.x, y, b.w, G.boxH);
    if (share < 0.015) { digits.push(null); empty++; continue; }
    const img = normalise(ink, S);
    if (!img) { digits.push(null); empty++; continue; }
    const p = classify(L, img);
    let best = 0;
    for (let k = 1; k < 11; k++) if (p[k] > p[best]) best = k;
    if (best === 10) { sure = false; why = "something that is not a digit"; digits.push("?"); continue; }
    if (p[best] < 0.9) { sure = false; why = "a digit that is not clear"; }
    digits.push(String(best));
  }
  const halfInk = boxInk(G0, H, half.x, y + (G.boxH - G.tick) / 2, half.w, G.tick, 24, 0.18).share;
  const ticked = halfInk > 0.06;
  if (empty === boxes.length) return { value: "", sure: !ticked, why: ticked ? "only ½ ticked" : "", blank: !ticked };
  // a gap between digits ("7 _ 5") is not a number the teacher would write
  const s = digits.map((d) => d ?? " ").join("").trim();
  if (s.includes(" ")) { sure = false; why = why || "a box in the middle is empty"; }
  const v = s.replace(/\s/g, "");
  if (v.includes("?")) return { value: "", sure, why };
  const whole = v ? String(parseInt(v, 10)) : "0";                 // "07" is 7
  return { value: ticked ? whole + ".5" : whole, sure, why };
}

/** A printed code square: 1 when its middle is much darker than the paper just around it. */
function solidCell(G0, H, x, y, s) {
  let inside = 0, around = 0, ni = 0, na = 0;
  for (let j = 0; j < 5; j++) for (let i = 0; i < 5; i++) {
    const [px, py] = H(x + s * (0.3 + 0.1 * i), y + s * (0.3 + 0.1 * j));
    inside += sampleAt(G0, px, py); ni++;
  }
  // the paper in the gaps left and right of it, and just above and below
  for (const [dx, dy] of [[-0.55, s / 2], [s + 0.55, s / 2], [s / 2, -0.9], [s / 2, s + 0.9]]) {
    const [px, py] = H(x + dx, y + dy);
    around += sampleAt(G0, px, py); na++;
  }
  return inside / ni < (around / na) * 0.55 ? 1 : 0;
}

/** Reads a photo of a filled sheet. t = the Type marks state (names in the same order as printed), parts = what was
 *  printed. -> {page, rows: [{i, marks: {part: {value, sure, why, img}}, absent}], totals, warnings} or {error}. */
export async function readSheetPhoto(file, t, parts) {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, 2200 / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bmp.width * scale); canvas.height = Math.round(bmp.height * scale);
  canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return readSheetCanvas(canvas, t, parts);
}

export async function readSheetCanvas(canvas, t, parts, { minSharp = 4 } = {}) {
  const G0 = grayOf(canvas);
  const sharp = sharpness(G0);
  if (sharp < minSharp) return { error: "The photo is too blurry to read the marks. Hold the phone still (or tap to focus) and take it again." };
  const m = findMarkers(G0);
  if (!m) return { error: "The four black squares in the corners were not found. Take the photo again with the whole page inside, flat and in good light." };
  const centres = G.markers.map(([x, y]) => [x + G.marker / 2, y + G.marker / 2]);
  const H = homography(centres, m);
  // which page, and is it the sheet printed for these names?
  const bits = [...Array(CODE_BITS)].map((_, i) => solidCell(G0, H, G.codeX + i * (G.codeCell + G.codeGap), G.codeTop, G.codeCell));
  const page = parseInt(bits.slice(0, 4).join(""), 2);
  const hash = parseInt(bits.slice(4).join(""), 2);
  const warnings = [];
  if (sharp < 12) warnings.push("The photo is a little blurry, so more marks than usual are marked not clear. A sharper photo saves typing.");
  if (hash !== sheetHash(t, parts)) warnings.push("This sheet does not match the names, exam or subject picked here (it may be for another section or subject, or the class list changed). Check every mark carefully.");
  const first = (Math.max(1, page) - 1) * G.rows;
  if (page < 1 || first >= Math.max(1, t.rows.length)) return { error: "The page number on the sheet could not be read." };
  const L = layout(parts);
  const W = await net();
  const rows = [];
  for (let i = 0; i < G.rows && first + i < t.rows.length; i++) {
    const y = rowY(i);
    const marks = {};
    for (const c of L.cols) {
      const r = readNumber(G0, H, W, c.boxes, c.half, y);
      if (r.value !== "" && +r.value > +c.max) { r.sure = false; r.why = `more than ${c.max}`; }
      r.img = patchUrl(G0, H, c.x0, y - 0.6, c.x1 - c.x0, G.boxH + 1.2);
      marks[c.part] = r;
    }
    const absent = boxInk(G0, H, L.absent.x, y + (G.boxH - G.tick) / 2, G.tick, G.tick, 24, 0.18).share > 0.06;
    rows.push({ i: first + i, marks, absent });
  }
  const totals = {};
  for (const tt of L.totals) {
    const r = readNumber(G0, H, W, tt.boxes, tt.half, G.totalTop + (G.rowH - G.boxH) / 2);
    const sum = rows.reduce((a, r2) => a + (r2.absent ? 0 : +(r2.marks[tt.part].value || 0)), 0);
    totals[tt.part] = { written: r.value, sure: r.sure, sum, img: patchUrl(G0, H, tt.boxes[0].x - 0.6, G.totalTop + 0.2, tt.half.x + G.tick + 1.2 - tt.boxes[0].x, G.boxH + 1.2) };
  }
  return { page, rows, totals, warnings, sharp: Math.round(sharp) };
}

// for tools/tests only
export const _parts = { grayOf, sharpness, findMarkers, homography, solidCell, sampleAt, boxInk };
