"""Makes the voice and the videos for the "?" explainers (run after changing web/js/explain.js).

1. Reads every explainer from the website's own code (web/js/explain.js) with plain Node - no browser.
2. Voice: each step is read aloud by Piper, an offline text-to-speech voice, and saved as a small MP3 in
   web/assets/voice/ (+ manifest.json with the lengths, so the player waits for the voice).
3. Video: every explainer becomes an MP4 in web/assets/video/: a title card, then each step drawn frame by
   frame with Pillow (explainer_frames.py, 25 fps, 1280x720) and joined with the narration by ffmpeg.
   Nothing else is opened or controlled - only Python, Node and ffmpeg run.

Only what changed is made again (the file names carry a fingerprint of the text).
Needs: pip install piper-tts pillow ; Node ; ffmpeg on the PATH ; a Piper voice in
%USERPROFILE%\\.piper\\models.
Run: python tools\\make_explainer_media.py            (everything)
     python tools\\make_explainer_media.py --only internals --no-video"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
VOICE_DIR = os.path.join(WEB, "assets", "voice")
VIDEO_DIR = os.path.join(WEB, "assets", "video")
MODEL = os.path.join(os.path.expanduser("~"), ".piper", "models", "en_US-lessac-medium.onnx")
FPS = 25
ANIM_S = 1.4            # the moving part of every scene; after that the frame stays still
LEAD_S = 0.35           # a short pause before the voice starts
TAIL_S = 0.8            # and after it ends

# ---------------------------------------------------------------- how the text is said
ROMAN = {"I": "one", "II": "two", "III": "three", "IV": "four", "V": "five", "VI": "six", "VII": "seven",
         "VIII": "eight", "IX": "nine", "X": "ten", "XI": "eleven", "XII": "twelve"}


def speech(text):
    """Turn the written explanation into words that read well aloud."""
    t = text
    t = t.replace("“", "").replace("”", "").replace("‘", "").replace("’", "'")
    # class ranges and class names: "Classes I-VIII" -> "classes one to eight", "XI-A" -> "eleven A"
    t = re.sub(r"\b(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\s*-\s*(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\b",
               lambda m: f"{ROMAN[m.group(1)]} to {ROMAN[m.group(2)]}", t)
    t = re.sub(r"\b(XII|XI|IX|X|VIII|VII|VI|IV|V|III|II)-([A-H])\b", lambda m: f"{ROMAN[m.group(1)]} {m.group(2)}", t)
    t = re.sub(r"\b(Class(?:es)?)\s+(XII|XI|IX|X|VIII|VII|VI|IV|V|III|II|I)\b", lambda m: f"{m.group(1)} {ROMAN[m.group(2)]}", t)
    t = re.sub(r"\b(XII|XI|IX|VIII|VII|VI|IV|III)\b", lambda m: ROMAN[m.group(1)], t)
    t = re.sub(r"\b(and|or|in)\s+X\b", r"\1 ten", t)
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s*/\s*(\d+)\b", r"\1 out of \2", t)
    t = t.replace(" / ", " or ")
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1 to \2", t)
    t = t.replace("÷", " divided by ").replace("×", " times ").replace("→", " becomes ").replace("−", " minus ")
    t = re.sub(r"(\d)\s=\s", r"\1 equals ", t).replace(" = ", " means ")
    t = t.replace(" + ", " plus ").replace("+5", "plus 5").replace("+4", "plus 4").replace(".xls", "x l s")
    t = re.sub(r"(\d+(?:\.\d+)?)\+", r"\1 or more", t)
    t = re.sub(r"\bPT\s?(\d)\b", r"P T \1", t)
    t = re.sub(r"\bPT\b", "P T", t)
    t = re.sub(r"\b(A|B|C|D)(1|2)\b", r"\1 \2", t)
    words = {"PCMB": "P C M B", "PCM": "P C M", "PCB": "P C B", "ICT": "I C T", "AI": "A I", "CBSE": "C B S E",
             "AB": "A B", "ML": "M L", "DL": "D L", "EX": "E X", "PI": "P I", "MP4": "M P 4", ".TXT": "text",
             "XLSX": "X L S X", "CSV": "C S V", "PDF": "P D F", "e.g.": "for example", "vs": "versus", "%": " percent",
             "Hinglish": "Hing-lish", "Mein": "mein", "kamzor": "kum-zor", "hai": "hay", "bachhe": "butch-ay"}
    for k, v in words.items():
        t = re.sub(r"(?<![A-Za-z])" + re.escape(k) + r"(?![A-Za-z])", v, t) if k[0].isalpha() else t.replace(k, v)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fp(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode("utf-8") if isinstance(p, str) else p)
    return h.hexdigest()[:10]


# ---------------------------------------------------------------- making the files
def ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)


def wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def read_explainers():
    """The explainers exactly as the website has them (read with plain Node - no browser is opened)."""
    r = subprocess.run(["node", os.path.join(ROOT, "tools", "dump_explainers.mjs")], capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="explainer ids")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    from piper import PiperVoice
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import explainer_frames as EF

    os.makedirs(VOICE_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)
    vman_path, mman_path = os.path.join(VOICE_DIR, "manifest.json"), os.path.join(VIDEO_DIR, "manifest.json")
    vman = json.load(open(vman_path)) if os.path.exists(vman_path) else {"explainers": {}}
    mman = json.load(open(mman_path)) if os.path.exists(mman_path) else {}
    voice = PiperVoice.load(MODEL)
    vname = os.path.basename(MODEL).replace(".onnx", "")
    tmp = tempfile.mkdtemp(prefix="rdps-media-")
    draw_fp = fp(open(os.path.join(ROOT, "tools", "explainer_frames.py"), encoding="utf-8").read())
    data = read_explainers()
    keep_files = set()
    try:
        for e in data:
            if args.only and e["id"] not in args.only:
                for c in vman["explainers"].get(e["id"], []):
                    keep_files.add(c["file"])
                continue
            # ---- voice: the title, then every step
            lines = [f"{e['title']}."] + [s["say"] or s["text"] for s in e["steps"]]
            clips = []
            for k, text in enumerate(lines):
                said = speech(text)
                name = f"{e['id']}-{k}-{fp(vname, said)}.mp3"
                out = os.path.join(VOICE_DIR, name)
                wav = os.path.join(tmp, name.replace(".mp3", ".wav"))
                if not os.path.exists(out) or args.force:
                    with wave.open(wav, "wb") as w:
                        voice.synthesize_wav(said, w)
                    ffmpeg("-i", wav, "-ac", "1", "-ar", "22050", "-b:a", "48k", out)
                else:
                    ffmpeg("-i", out, "-ac", "1", "-ar", "22050", wav)
                clips.append({"file": name, "dur": round(wav_seconds(wav), 3), "wav": wav})
                keep_files.add(name)
            vman["explainers"][e["id"]] = [{"file": c["file"], "dur": c["dur"]} for c in clips]
            print(f"voice  {e['id']}: {len(clips)} clips, {sum(c['dur'] for c in clips):.1f} s", flush=True)
            if args.no_video:
                continue
            # ---- video: frames drawn by explainer_frames.py, joined with the voice by ffmpeg
            vfp = fp(draw_fp, json.dumps(e), *[c["file"] for c in clips])
            out_mp4 = os.path.join(VIDEO_DIR, f"{e['id']}.mp4")
            if not args.force and mman.get(e["id"], {}).get("fp") == vfp and os.path.exists(out_mp4):
                print(f"video  {e['id']}: unchanged", flush=True)
                continue
            fdir = os.path.join(tmp, e["id"])
            os.makedirs(fdir, exist_ok=True)
            listing, n, rate, audio = [], 0, 22050, []
            for seg_i, clip in enumerate(clips):
                is_title = seg_i == 0
                seg_s = max(2.6 if is_title else 3.0, LEAD_S + clip["dur"] + TAIL_S)
                scene = None if is_title else EF.StepScene(e, seg_i - 1)
                draw = (lambda t: EF.title_frame(e, t)) if is_title else scene.frame
                frames = int(min(ANIM_S if not is_title else 1.4, seg_s) * FPS)
                for f in range(frames):
                    n += 1
                    png = os.path.join(fdir, f"f{n:05d}.png")
                    draw(f / FPS).save(png, compress_level=1)
                    listing.append((png, 1 / FPS))
                n += 1
                png = os.path.join(fdir, f"f{n:05d}.png")
                draw(4.0).save(png, compress_level=1)
                listing.append((png, seg_s - frames / FPS))
                with wave.open(clip["wav"]) as w:
                    rate = w.getframerate()
                    pcm = w.readframes(w.getnframes())
                lead = int(LEAD_S * rate) * 2
                total = int(round(seg_s * rate)) * 2
                seg = b"\x00" * lead + pcm
                audio.append(seg[:total] + b"\x00" * max(0, total - len(seg)))
            lst = os.path.join(fdir, "list.txt")
            with open(lst, "w", encoding="utf-8") as fh:
                for png, d in listing:
                    fh.write(f"file '{png.replace(os.sep, '/')}'\nduration {d:.4f}\n")
                fh.write(f"file '{listing[-1][0].replace(os.sep, '/')}'\n")
            awav = os.path.join(fdir, "audio.wav")
            with wave.open(awav, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(b"".join(audio))
            ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-i", awav, "-vf", f"fps={FPS},format=yuv420p",
                   "-c:v", "libx264", "-preset", "slow", "-tune", "stillimage", "-crf", "26", "-c:a", "aac", "-b:a", "64k",
                   "-movflags", "+faststart", "-shortest", out_mp4)
            dur = wav_seconds(awav)
            mman[e["id"]] = {"file": f"{e['id']}.mp4", "dur": round(dur, 2), "fp": vfp, "size": os.path.getsize(out_mp4)}
            print(f"video  {e['id']}: {dur:.1f} s, {os.path.getsize(out_mp4) / 1e3:.0f} KB, {n} frames", flush=True)
            shutil.rmtree(fdir, ignore_errors=True)
        if not args.only:
            for f in os.listdir(VOICE_DIR):
                if f.endswith(".mp3") and f not in keep_files:
                    os.remove(os.path.join(VOICE_DIR, f))
            ids = {e["id"] for e in data}
            for f in os.listdir(VIDEO_DIR):
                if f.endswith(".mp4") and f[:-4] not in ids:
                    os.remove(os.path.join(VIDEO_DIR, f))
                    mman.pop(f[:-4], None)
        vman["voice"] = vname
        json.dump(vman, open(vman_path, "w"), indent=1)
        json.dump(mman, open(mman_path, "w"), indent=1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("done")


if __name__ == "__main__":
    sys.exit(main())
