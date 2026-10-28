"""Tests a local AI model (llama.cpp's llama-server, run on this PC - nothing leaves it) as the Smart Ask helper:
the model only REWRITES a teacher's messy question into one clear English question; the rule engine then turns
that into a query and works out the answer. The model never sees any marks.

A question counts as right only when the engine's query for the model's rewrite is EXACTLY the same as the
query for a clear question written by hand (so a rewrite that changes the meaning fails).

Made-up data only (the sample school files + the made-up board example).
Run:  python tools/ask_llm_test.py ollama <model name>          (Ollama running on this PC, signed by its maker)
      python tools/ask_llm_test.py <llama-server.exe> <model.gguf> [threads]
      python tools/ask_llm_test.py --check     (no model: checks the hand-written questions and the rules alone)"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
from markstudio import api  # noqa: E402

PROMPT_FILE = os.path.join(ROOT, "web", "assets", "ask", "rewrite_prompt.json")
PORT = 8089

# (teacher's messy question, the same question written clearly) - none of these are in the prompt's examples
CASES = [
    ("who all r weak in chemestry class 11", "who is weak in chemistry in class 11"),
    ("which teachers are not working good", "which teachers are not doing well"),
    ("who might need extra classes in maths in class 9", "who is weak in maths in class 9"),
    ("show me kids who flunked physics in class 12", "who failed in physics in class 12"),
    ("phyiscs average of class 11", "average in physics in class 11"),
    ("who got more than 90 in maths class 10", "who scored more than 90 in maths in class 10"),
    ("which subject class 9 finds toughest", "hardest subject in class 9"),
    ("best section in class 12", "which section is best in class 12"),
    ("students failing 2 or more subjects in 11th", "who failed in more than one subject in class 11"),
    ("who improved a lot in class 9", "who improved in class 9"),
    ("english me sabse best kaun hai class 9", "top 1 in english in class 9"),
    ("girls vs boys result class 12", "compare girls and boys in class 12"),
    ("list the students who are struggling in science class 6", "who is weak in science in class 6"),
    ("top 3 of 11 A", "top 3 in class 11 section A"),
    ("9th class ka pass percent batao", "pass percentage of class 9"),
    ("show the toppers of each section of class 12", "toppers of each section in class 12"),
    ("low scorers in sst class 10", "who is weak in social science in class 10"),
    ("who fell down in marks in class 6", "who dropped in class 6"),
    ("class 10 me kitne bacche fail hue", "how many failed in class 10"),
    ("avrage marks of class 12 in english", "average in english in class 12"),
    ("kaun sa subject sabse aasan hai class 11 me", "easiest subject in class 11"),
    ("10th ke top 5 bacche", "top 5 in class 10"),
    ("compare section a and b of class 9 in maths", "compare section A and B in maths in class 9"),
    ("how is 12 C doing", "result of class 12 section C"),
    ("bio me kon kamzor hai 12th", "who is weak in biology in class 12"),
    ("toppers of every subject class 11", "toppers of each subject in class 11"),
    ("economics me top 3 class 12", "top 3 in economics in class 12"),
    ("absent students in yearly exam class 9", "who was absent in yearly in class 9"),
    ("lowest 5 in class 11", "lowest 5 in class 11"),
    ("chemistry me sabse kam marks kiske hai class 12", "lowest 1 in chemistry in class 12"),
    ("boards mein commerce wale toppers kaun hain", "commerce stream toppers in boards"),
    ("who got 90+ in all subjects in board exam", "who scored 90 in every subject in boards"),
    ("cbse result me sabse tough subject", "hardest subject in boards"),
    ("board toppers list", "board toppers"),
    ("kitne bachon ki compartment aayi boards me", "compartment in boards"),
    ("humanities top 3 in board", "humanities stream top 3 in boards"),
    ("boards ka result kaisa raha", "board results summary"),
    ("phy me board ke top 5", "top 5 in physics in boards"),
    ("board me easiest subject kaunsa tha", "easiest subject in boards"),
    ("which teachers did good in boards", "which teachers are doing well in boards"),
]


def setup():
    api.init()
    api.add_sample(False)
    api.analyze()
    api.add_sample_board_full()


def key(question):
    """What the engine makes of a question: its query (or the question it asks back)."""
    d = json.loads(api.ask(question)).get("data") or {}
    if "query" in d:
        return json.dumps(d["query"], sort_keys=True)
    if d.get("clarify"):
        return "ASK:" + d.get("question", "")
    return "NONE"


def check():
    setup()
    bad, rules = 0, 0
    for messy, clear in CASES:
        k = key(clear)
        ok = not k.startswith(("NONE", "ASK"))
        bad += not ok
        same = key(messy) == k
        rules += same
        print(f"{'  ' if ok else '!!'} {'=' if same else ' '} {clear!r:52} -> {k[:110]}")
    print(f"\nclear questions the engine understands: {len(CASES) - bad}/{len(CASES)}; "
          f"messy questions the rules alone already get right: {rules}/{len(CASES)}")


MODEL = ""


def chat(messages, max_tokens=40):
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0, "max_tokens": max_tokens, "stop": ["\n"],
                       "cache_prompt": True}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    return out["choices"][0]["message"]["content"].strip().strip('"')


def main(server, model, threads=None):
    global PORT, MODEL
    proc = None
    t0 = time.time()
    if server == "ollama":
        PORT, MODEL = 11434, model
    else:
        args = [server, "-m", model, "-c", "2048", "--port", str(PORT), "--host", "127.0.0.1", "-np", "1"]
        if threads:
            args += ["-t", str(threads)]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while proc is not None:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2).read()
                break
            except Exception:
                if time.time() - t0 > 180 or proc.poll() is not None:
                    raise SystemExit("llama-server did not start")
                time.sleep(1)
        setup()
        prompt = json.load(open(PROMPT_FILE, encoding="utf-8"))
        base = [{"role": "system", "content": prompt["system"]}]
        for q, a in prompt["examples"]:
            base += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        chat(base + [{"role": "user", "content": "warm up"}])
        load = time.time() - t0
        ok = rules = 0
        times = []
        for messy, clear in CASES:
            want = key(clear)
            t = time.time()
            rew = chat(base + [{"role": "user", "content": messy}])
            times.append(time.time() - t)
            got = key(rew)
            good = got == want
            ok += good
            rules += key(messy) == want
            print(f"{'OK' if good else 'XX'} {times[-1]:4.1f}s  {messy!r:48} -> {rew!r}")
        mem = ""
        try:
            flt = f"PID eq {proc.pid}" if proc else "IMAGENAME eq ollama*"
            out = subprocess.run(["tasklist", "/fi", flt, "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
            mem = " + ".join(line.split('","')[-1].strip('"') for line in out.strip().splitlines() if line)
        except Exception:
            pass
        print(f"\n{os.path.basename(model)}: {ok}/{len(CASES)} right (rules alone: {rules}/{len(CASES)}); "
              f"avg {sum(times) / len(times):.1f} s, slowest {max(times):.1f} s; ready in {load:.0f} s; memory {mem}")
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--check"]:
        check()
    else:
        main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
