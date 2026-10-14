"""Copies everything the website needs into web/ so it is fully self-hosted:
the Python engine (Pyodide), the core code, Excel libraries, PDF/OCR readers,
charts, fonts and the AI runtime. Run: double-click tools\\build_web.bat"""
import hashlib
import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NM = os.path.join(ROOT, "_vendor_src", "node_modules")
WEB = os.path.join(ROOT, "web")
VENDOR = os.path.join(WEB, "vendor")


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def copy_files(src_dir, names, dst_dir):
    for n in names:
        copy(os.path.join(src_dir, n), os.path.join(dst_dir, n))


def main():
    os.makedirs(VENDOR, exist_ok=True)
    # Pyodide (Python in the browser)
    copy_files(os.path.join(NM, "pyodide"),
               ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json", "pyodide.js"],
               os.path.join(VENDOR, "pyodide"))
    # transformers.js + onnx runtime (on-device AI)
    tdir = os.path.join(NM, "@huggingface", "transformers", "dist")
    copy_files(tdir, ["transformers.min.js", "ort-wasm-simd-threaded.jsep.mjs", "ort-wasm-simd-threaded.jsep.wasm"],
               os.path.join(VENDOR, "transformers"))
    # tesseract (reading scanned printed sheets)
    copy_files(os.path.join(NM, "tesseract.js", "dist"), ["tesseract.min.js", "worker.min.js"], os.path.join(VENDOR, "tesseract"))
    core = os.path.join(NM, "tesseract.js-core")
    # only the LSTM engine builds are used (with and without SIMD)
    copy_files(core, ["tesseract-core-simd-lstm.wasm.js", "tesseract-core-lstm.wasm.js",
                      "tesseract-core-simd-lstm.js", "tesseract-core-lstm.js",
                      "tesseract-core-simd-lstm.wasm", "tesseract-core-lstm.wasm"],
               os.path.join(VENDOR, "tesseract-core"))
    copy(os.path.join(NM, "@tesseract.js-data", "eng", "4.0.0_best_int", "eng.traineddata.gz"),
         os.path.join(VENDOR, "tessdata", "eng.traineddata.gz"))
    # pdf.js
    copy_files(os.path.join(NM, "pdfjs-dist", "build"), ["pdf.min.js", "pdf.worker.min.js"], os.path.join(VENDOR, "pdfjs"))
    # Chart.js
    copy(os.path.join(NM, "chart.js", "dist", "chart.umd.js"), os.path.join(VENDOR, "chartjs", "chart.umd.js"))
    # fonts (latin + devanagari subsets, woff2)
    fonts = {"poppins": ["latin-500-normal", "latin-600-normal", "latin-700-normal"],
             "inter": ["latin-400-normal", "latin-500-normal", "latin-600-normal", "latin-700-normal"],
             "mukta": ["devanagari-400-normal", "devanagari-600-normal", "latin-400-normal"]}
    for fam, variants in fonts.items():
        for v in variants:
            src = os.path.join(NM, "@fontsource", fam, "files", f"{fam}-{v}.woff2")
            copy(src, os.path.join(VENDOR, "fonts", f"{fam}-{v}.woff2"))
    # Python: our code + pure-Python wheels
    pydir = os.path.join(WEB, "py")
    os.makedirs(pydir, exist_ok=True)
    zpath = os.path.join(pydir, "markstudio.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        base = os.path.join(ROOT, "core")
        for dirpath, _, files in os.walk(os.path.join(base, "markstudio")):
            if "__pycache__" in dirpath:
                continue
            for f in files:
                if f.endswith((".py", ".json", ".bas", ".png")):
                    full = os.path.join(dirpath, f)
                    z.write(full, os.path.relpath(full, base))
    wdir = os.path.join(ROOT, "_vendor_src", "wheels")
    wheels = sorted(f for f in os.listdir(wdir) if f.endswith(".whl"))
    for w in wheels:
        copy(os.path.join(wdir, w), os.path.join(pydir, "wheels", w))
    # version stamp (used to refresh the offline cache when anything changes)
    h = hashlib.sha256()
    for dirpath, _, files in os.walk(WEB):
        for f in sorted(files):
            if f in ("build.json",):
                continue
            p = os.path.join(dirpath, f)
            h.update(os.path.relpath(p, WEB).encode())
            h.update(str(os.path.getsize(p)).encode())
            h.update(str(int(os.path.getmtime(p))).encode())
    files = []
    for dirpath, _, fs in os.walk(WEB):
        for f in fs:
            rel = os.path.relpath(os.path.join(dirpath, f), WEB).replace("\\", "/")
            if rel in ("build.json", "sw.js") or rel.startswith("samples/"):
                continue
            files.append(rel)
    with open(os.path.join(WEB, "build.json"), "w") as fh:
        json.dump({"version": h.hexdigest()[:12], "wheels": wheels, "files": sorted(files)}, fh, indent=1)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(WEB) for f in fs)
    print(f"web/ ready: {len(files)} files, {size / 1e6:.1f} MB, version {h.hexdigest()[:12]}")


if __name__ == "__main__":
    sys.exit(main())
