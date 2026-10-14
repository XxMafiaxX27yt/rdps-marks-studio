// Reading PDFs and scanned sheets in the browser.
// PDFs with real text: pdf.js gives every word and its position.
// Scans / photos of PRINTED sheets: Tesseract (offline text recognition) reads the words.
// The words (with positions) go to the Python engine, which rebuilds the table.

let pdfjsReady = null;
let tess = null;

function loadScript(src) {
  return new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = src; s.onload = res; s.onerror = () => rej(new Error("Could not load " + src));
    document.head.appendChild(s);
  });
}

async function pdfjs() {
  if (!pdfjsReady) {
    pdfjsReady = loadScript("vendor/pdfjs/pdf.min.js").then(() => {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js";
      return window.pdfjsLib;
    });
  }
  return pdfjsReady;
}

async function ocrWorker(onProgress) {
  if (!tess) {
    await loadScript("vendor/tesseract/tesseract.min.js");
    const base = new URL("../", import.meta.url).href;
    tess = await window.Tesseract.createWorker("eng", 1, {
      workerPath: base + "vendor/tesseract/worker.min.js",
      corePath: base + "vendor/tesseract-core/",
      langPath: base + "vendor/tessdata/",
      workerBlobURL: false,
      gzip: true,
      logger: (m) => { if (m.status === "recognizing text" && onProgress) onProgress(m.progress); },
    });
    // tables read best as one block of text with the spaces kept
    await tess.setParameters({ tessedit_pageseg_mode: "6", preserve_interword_spaces: "1" });
  }
  return tess;
}

// Scans are rarely perfectly straight. Find the tilt (the angle at which the rows of ink
// line up best) and turn the page back, so table lines become straight and can be removed.
function deskew(canvas) {
  const W = canvas.width, H = canvas.height;
  const scale = Math.min(1, 900 / W);
  const sw = Math.round(W * scale), sh = Math.round(H * scale);
  const small = document.createElement("canvas");
  small.width = sw; small.height = sh;
  const sctx = small.getContext("2d", { willReadFrequently: true });
  sctx.drawImage(canvas, 0, 0, sw, sh);
  const d = sctx.getImageData(0, 0, sw, sh).data;
  const pts = [];
  for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) {
    const i = (y * sw + x) * 4;
    if ((d[i] + d[i + 1] + d[i + 2]) / 3 < 140) pts.push(x, y);
  }
  if (pts.length < 200) return canvas;
  let best = 0, bestScore = -1;
  for (let a = -4; a <= 4.001; a += 0.1) {
    const t = Math.tan(a * Math.PI / 180);
    const bins = new Float64Array(sh + sw + 2);
    for (let k = 0; k < pts.length; k += 2) {
      const b = Math.round(pts[k + 1] - pts[k] * t + sw);
      if (b >= 0 && b < bins.length) bins[b]++;
    }
    let score = 0;
    for (let i = 0; i < bins.length; i++) score += bins[i] * bins[i];
    if (score > bestScore) { bestScore = score; best = a; }
  }
  if (Math.abs(best) < 0.05) return canvas;
  const out = document.createElement("canvas");
  out.width = W; out.height = H;
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, W, H);
  ctx.translate(W / 2, H / 2);
  ctx.rotate(-best * Math.PI / 180);
  ctx.drawImage(canvas, -W / 2, -H / 2);
  return out;
}

// Table gridlines confuse text recognition: turn long dark lines white first.
function removeLines(canvas) {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const { width: W, height: H } = canvas;
  const img = ctx.getImageData(0, 0, W, H);
  const d = img.data;
  const lum = (i) => (d[i] + d[i + 1] + d[i + 2]) / 3;
  // a line = one long dark run with only tiny gaps (text has gaps between letters and words)
  const longestRun = (n, at) => {
    let run = 0, gap = 0, best = 0;
    for (let k = 0; k < n; k++) {
      if (lum(at(k)) < 200) { run += gap + 1; gap = 0; if (run > best) best = run; }
      else if (run && gap < 3) gap++;
      else { run = 0; gap = 0; }
    }
    return best;
  };
  // the darkest of 3 neighbouring pixels, so a line that drifts by a pixel still counts as one run
  const darkest3 = (a, b, c) => (lum(a) <= lum(b) ? (lum(a) <= lum(c) ? a : c) : (lum(b) <= lum(c) ? b : c));
  const rowsToClear = new Set(), colsToClear = new Set();
  for (let y = 1; y < H - 1; y++) {
    const at = (x) => darkest3(((y - 1) * W + x) * 4, (y * W + x) * 4, ((y + 1) * W + x) * 4);
    if (longestRun(W, at) > W * 0.3) for (let k = -2; k <= 2; k++) rowsToClear.add(y + k);  // + soft edges
  }
  for (let x = 1; x < W - 1; x++) {
    const at = (y) => darkest3((y * W + x - 1) * 4, (y * W + x) * 4, (y * W + x + 1) * 4);
    if (longestRun(H, at) > H * 0.3) for (let k = -2; k <= 2; k++) colsToClear.add(x + k);
  }
  const clear = (i) => { d[i] = d[i + 1] = d[i + 2] = 255; };
  for (const y of rowsToClear) if (y >= 0 && y < H) for (let x = 0; x < W; x++) clear((y * W + x) * 4);
  for (const x of colsToClear) if (x >= 0 && x < W) for (let y = 0; y < H; y++) clear((y * W + x) * 4);
  ctx.putImageData(img, 0, 0);
}

async function ocrCanvas(input, onProgress) {
  const canvas = deskew(input);
  removeLines(canvas);
  const w = await ocrWorker(onProgress);
  const { data } = await w.recognize(canvas, {}, { blocks: true });
  const words = [];
  for (const b of data.blocks || []) for (const p of b.paragraphs || []) for (const l of p.lines || []) for (const wd of l.words || []) {
    if (!wd.text.trim()) continue;
    words.push({ text: wd.text, x0: wd.bbox.x0, x1: wd.bbox.x1, y0: wd.bbox.y0, y1: wd.bbox.y1, conf: wd.confidence });
  }
  return words;
}

// -> [{page, words:[{text,x0,x1,y0,y1}], ocr}]
export async function readPdf(file, onProgress) {
  const lib = await pdfjs();
  const doc = await lib.getDocument({ data: new Uint8Array(await file.arrayBuffer()), isEvalSupported: false }).promise;
  const pages = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const vp = page.getViewport({ scale: 1 });
    const tc = await page.getTextContent();
    let words = [];
    for (const it of tc.items) {
      const str = (it.str || "").trim();
      if (!str) continue;
      const [a, b, c, d, e, f] = it.transform;
      const h = Math.hypot(c, d) || 10;
      const x0 = e, y1 = vp.height - f, y0 = y1 - h;
      // split runs on 2+ spaces so table cells stay separate
      const parts = it.str.split(/(\s{2,})/);
      const cw = (it.width || str.length * h * 0.5) / Math.max(1, it.str.length);
      let pos = 0;
      for (const p of parts) {
        if (p.trim() && !/^\s+$/.test(p)) words.push({ text: p.trim(), x0: x0 + pos * cw, x1: x0 + (pos + p.length) * cw, y0, y1 });
        pos += p.length;
      }
    }
    let ocr = false;
    if (words.length < 8) {
      // looks like a scan: render the page and read it
      const scale = 2.2;
      const v2 = page.getViewport({ scale });
      const canvas = document.createElement("canvas");
      canvas.width = v2.width; canvas.height = v2.height;
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: v2 }).promise;
      words = await ocrCanvas(canvas, (p) => onProgress && onProgress((i - 1 + p) / doc.numPages));
      ocr = true;
    }
    pages.push({ page: i, words, ocr });
    onProgress && onProgress(i / doc.numPages);
  }
  return pages;
}

export async function readImage(file, onProgress) {
  const img = await createImageBitmap(file);
  const scale = Math.min(2, 2400 / Math.max(img.width, img.height)) || 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
  const ctx = canvas.getContext("2d");
  ctx.filter = "grayscale(1)";
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  const words = await ocrCanvas(canvas, onProgress);
  return [{ page: 1, words, ocr: true }];
}
