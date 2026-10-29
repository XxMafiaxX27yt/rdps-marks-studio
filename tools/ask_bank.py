"""The Ask question bank: a local AI model (Ollama on THIS PC - nothing leaves it, and the school never runs it)
writes many ways a teacher might type each kind of question, with blanks like {subject} and {cls}. The blanks are
then filled with many real ways of writing them ("class 9", "9th", "IX"; "maths", "math"; a misspelled name...),
and every filled question must give EXACTLY the same engine query as the clear question with the same values.
So the model never decides an answer: a rewrite that changes the meaning simply fails and is looked at by hand.

Made-up data only (the sample school files + the made-up board example).

  python tools/ask_bank.py gen [model] [rounds]   the model writes phrasings -> tools/ask_bank/phrasings.json
  python tools/ask_bank.py run [fills]            every phrasing x fills through the rules -> tools/ask_bank/report.txt
  python tools/ask_bank.py save                   phrasings that pass (minus rejected ones) -> tests/ask_bank.json
"""
import json
import os
import random
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
from markstudio import api  # noqa: E402

HERE = os.path.join(ROOT, "tools", "ask_bank")
PHRASINGS = os.path.join(HERE, "phrasings.json")
REJECTED = os.path.join(HERE, "rejected.json")      # {template id: [phrasings whose meaning differs]} - by hand
REPORT = os.path.join(HERE, "report.txt")
BANK = os.path.join(ROOT, "tests", "ask_bank.json")

# (id, the clear question with blanks). Blanks: {cls} {section} {section2} {subject} {subject2} {n} {mark} {exam}
# {student}; board questions use {bsubject} (a subject in the board results).
TEMPLATES = [
    ("top_n", "top {n} in {cls}"),
    ("top_n_subject", "top {n} in {subject} in {cls}"),
    ("top_n_section", "top {n} in {cls} {section}"),
    ("top_n_exam", "top {n} in {cls} in {exam}"),
    ("top_1", "top 1 in {cls}"),
    ("top_1_subject", "top 1 in {subject} in {cls}"),
    ("bottom_n", "lowest {n} in {cls}"),
    ("bottom_n_subject", "lowest {n} in {subject} in {cls}"),
    ("bottom_1_subject", "lowest 1 in {subject} in {cls}"),
    ("weak_subject", "who is weak in {subject} in {cls}"),
    ("strong_subject", "who is strong in {subject} in {cls}"),
    ("failed_subject", "who failed in {subject} in {cls}"),
    ("failed_two", "who failed in more than one subject in {cls}"),
    ("above_mark", "who scored more than {mark} in {subject} in {cls}"),
    ("below_mark", "who scored less than {mark} in {subject} in {cls}"),
    ("absent_exam", "who was absent in {exam} in {cls}"),
    ("count_failed", "how many failed in {cls}"),
    ("count_weak", "how many are weak in {subject} in {cls}"),
    ("count_above", "how many scored more than {mark} in {subject} in {cls}"),
    ("avg_subject", "average in {subject} in {cls}"),
    ("avg_class", "average of {cls}"),
    ("avg_subject_section", "average in {subject} in {cls} {section}"),
    ("avg_by_section", "average of each section in {cls}"),
    ("avg_by_subject", "average of each subject in {cls}"),
    ("avg_subject_exam", "average in {subject} in {cls} in {exam}"),
    ("highest_subject", "highest marks in {subject} in {cls}"),
    ("lowest_subject", "lowest marks in {subject} in {cls}"),
    ("hardest", "hardest subject in {cls}"),
    ("easiest", "easiest subject in {cls}"),
    ("compare_sections", "compare {section} and {section2} in {cls}"),
    ("compare_subjects", "compare {subject} and {subject2} in {cls}"),
    ("compare_gender", "compare girls and boys in {cls}"),
    ("student", "marks of {student}"),
    ("student_weak", "weakest subjects of {student}"),
    ("student_strong", "strongest subjects of {student}"),
    ("student_rank", "rank of {student}"),
    ("pass_class", "pass percentage of {cls}"),
    ("pass_subject", "pass percentage in {subject} in {cls}"),
    ("pass_by_section", "pass percentage of each section in {cls}"),
    ("grades_subject", "grade distribution in {subject} in {cls}"),
    ("improved", "who improved in {cls}"),
    ("dropped", "who dropped in {cls}"),
    ("summary", "result of {cls}"),
    ("summary_section", "result of {cls} {section}"),
    ("toppers_sections", "toppers of each section in {cls}"),
    ("toppers_subjects", "toppers of each subject in {cls}"),
    ("board_top", "board toppers"),
    ("board_top_n", "top {n} in boards"),
    ("board_top_subject", "top {n} in {bsubject} in boards"),
    ("board_hardest", "hardest subject in boards"),
    ("board_easiest", "easiest subject in boards"),
    ("board_comp", "compartment in boards"),
    ("board_summary", "board results summary"),
    ("board_90_all", "who scored 90 in every subject in boards"),
]

ROMAN = {"VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
WORD_N = {3: "three", 5: "five", 10: "ten"}


# ---------------------------------------------------------------- data + ways of writing each blank
class World:
    def __init__(self):
        api.init()
        api.add_sample(False)
        api.analyze()
        api.add_sample_board_full()
        S = api.S
        self.cfg = S.cfg
        summ = json.loads(api.summary())["data"]
        self.classes = {c["cls"]: c for c in summ["classes"]}
        names = Counter(s.name for s in S.ds.students.values())
        self.students = sorted(n for n, k in names.items() if k == 1)
        self.bsubjects = sorted({x["code"] for g in S.project.gazettes for st in g.students for x in st.subjects
                                 if x["code"] in self.cfg.subjects})
        self.subjects = {c["cls"]: [s["code"] for s in c["subjects"]] for c in summ["classes"]}

    def pick(self, rnd, slots):
        """Values for the blanks of one question, all from the made-up data (subject of that class, ...)."""
        v = {}
        cls = rnd.choice(sorted(self.classes))
        c = self.classes[cls]
        v["cls"] = cls
        secs = rnd.sample(c["sections"], 2) if len(c["sections"]) >= 2 else c["sections"] * 2
        v["section"], v["section2"] = secs[0], secs[1]
        subs = [s for s in self.subjects[cls] if s not in ("122", "018", "020", "096")] or self.subjects[cls]
        two = rnd.sample(subs, 2)
        v["subject"], v["subject2"] = two
        v["n"] = rnd.choice([3, 5, 10])
        v["mark"] = rnd.choice([33, 40, 75, 90])
        v["exam"] = rnd.choice([e["code"] for e in c["exams"]])
        v["student"] = rnd.choice(self.students)
        v["bsubject"] = rnd.choice(self.bsubjects) if self.bsubjects else "301"
        return {k: v[k] for k in slots}

    # the clear way
    def canon(self, slot, val):
        cfg = self.cfg
        if slot == "cls":
            return f"class {ROMAN[val]}"
        if slot in ("section", "section2"):
            return f"section {val}"
        if slot in ("subject", "subject2", "bsubject"):
            return cfg.subject_name(val).lower()
        if slot == "exam":
            return cfg.exam_name(val).lower()
        return str(val)

    # the many ways a teacher writes it
    def messy(self, rnd, slot, val):
        cfg = self.cfg
        if slot == "cls":
            n = ROMAN[val]
            return rnd.choice([f"class {n}", f"{n}th", f"class {val.lower()}", val, f"class {val}", f"{n}th class",
                               f"std {n}", f"class-{n}", f"{n} class"])
        if slot in ("section", "section2"):
            return rnd.choice([f"section {val}", f"section {val.lower()}", f"sec {val}", f"{val} section", f"sec-{val.lower()}"])
        if slot in ("subject", "subject2", "bsubject"):
            s = cfg.subjects[val]
            forms = [s["name"].lower(), s["short"].lower()] + [x for x in s.get("synonyms", []) if len(x) >= 3]
            word = rnd.choice(forms)
            if len(word) >= 7 and " " not in word and rnd.random() < 0.3:
                i = rnd.randrange(1, len(word) - 2)
                word = word[:i] + word[i + 1] + word[i] + word[i + 2:]          # two letters swapped
            return word
        if slot == "exam":
            e = cfg.exams[val]
            return rnd.choice([e["name"].lower()] + e.get("aliases", []))
        if slot == "n":
            return rnd.choice([str(val), str(val), WORD_N[val]])
        if slot == "mark":
            return rnd.choice([str(val), f"{val}%", f"{val} marks", f"{val} percent"])
        if slot == "student":
            first, *rest = val.split()
            last = " ".join(rest)
            typo = last[:-2] + last[-1] if len(last) >= 6 else last
            return rnd.choice([val, val.lower(), val.upper(), f"{first} {typo}".lower()])
        return str(val)


def slots_of(text):
    return re.findall(r"\{(\w+)\}", text)


def fill(text, values, form):
    return re.sub(r"\{(\w+)\}", lambda m: form(m.group(1), values[m.group(1)]), text)


def key(question):
    """What Ask makes of a question: its query, the question it asks back, or nothing (the answer itself is not
    worked out - only what was understood)."""
    d = api.understander().parse(question)
    if "query" in d:
        return json.dumps(d["query"], sort_keys=True)
    if d.get("clarify"):
        return "ASK:" + (d.get("question") or "")[:80]
    return "NONE"


# ---------------------------------------------------------------- 1. the model writes phrasings
SYSTEM = ("You write realistic questions that teachers in an Indian CBSE school type into a marks app, in natural English "
          "or in natural Hinglish (Hindi in English letters), the way they really talk.")
# the style, shown with a different question (a word list alone made the model throw Hindi words in at random)
STYLE = [("top {n} in {cls}", ["{cls} ke top {n} bacche", "top {n} students of {cls}", "{cls} mein top {n} kaun hain",
                               "show the {n} best students of {cls}", "best {n} in {cls}"]),
         ("average in {subject} in {cls}", ["{cls} ka {subject} average", "what is the average of {subject} in {cls}",
                                            "{subject} mein {cls} ka average kitna hai", "avg marks of {cls} in {subject}",
                                            "{cls} {subject} avg"])]
COUNT_WORDS = re.compile(r"\b(kitne|kitni|kitna|how many|number of|count)\b")


def ask_model(model, template, k, seed):
    ex_q, ex = STYLE[1] if template == STYLE[0][0] else STYLE[0]
    user = (f"Question: {template}\n\nWrite {k} other ways a real teacher would type this SAME question. "
            f"For example, for the question \"{ex_q}\" teachers type:\n" + "\n".join(ex) + "\n\n"
            "Rules: exactly the same meaning (do not turn 'who' into 'how many', do not add or drop any class, subject, "
            "section, number, exam or condition); copy every blank like {cls} or {subject} as it is, with its curly "
            "brackets; natural English or natural Hinglish only; some short, some with small spelling mistakes; "
            "no question marks; one per line, no numbering.")
    body = json.dumps({"model": model, "stream": False, "options": {"temperature": 0.8, "seed": seed, "num_predict": 400},
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.load(r)["message"]["content"]
    out = []
    want = sorted(slots_of(template))
    counting = bool(COUNT_WORDS.search(template)) or template.startswith(("average", "pass percentage"))
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip().strip('"').strip("'").rstrip("?.").strip()
        if not line or len(line) > 140 or sorted(slots_of(line)) != want:
            continue
        if line in ex or re.search(r"\b(\w+) \1\b", line.lower()):             # copied the example / "mein mein"
            continue
        if not counting and COUNT_WORDS.search(line.lower()):                   # "who" turned into "how many"
            continue
        out.append(line)
    return out


def generate(model="rdps-qwen3b", rounds=5, k=8):
    os.makedirs(HERE, exist_ok=True)
    have = json.load(open(PHRASINGS, encoding="utf-8")) if os.path.exists(PHRASINGS) else {}
    t0 = time.time()
    for tid, tpl in TEMPLATES:
        seen = {norm(x) for x in have.get(tid, [])} | {norm(tpl)}
        got = list(have.get(tid, []))
        for r in range(rounds):
            try:
                for line in ask_model(model, tpl, k, seed=1000 * r + len(got)):
                    if norm(line) not in seen:
                        seen.add(norm(line))
                        got.append(line)
            except Exception as e:
                print("  model error:", e)
        have[tid] = got
        json.dump(have, open(PHRASINGS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{tid:22} {len(got):4} phrasings   ({time.time() - t0:.0f} s)")
    print(f"\n{sum(len(v) for v in have.values())} phrasings for {len(have)} kinds of question -> {PHRASINGS}")


def norm(s):
    return " ".join(re.sub(r"[^\w{} ]", " ", s.lower()).split())


# ---------------------------------------------------------------- 2. run them through the rules
def run(fills=4, only=None, quiet=False):
    w = World()
    phr = json.load(open(PHRASINGS, encoding="utf-8"))
    rejected = json.load(open(REJECTED, encoding="utf-8")) if os.path.exists(REJECTED) else {}
    lines, total, good = [], 0, 0
    per = {}
    for tid, tpl in TEMPLATES:
        if only and tid not in only:
            continue
        rnd = random.Random(tid)
        slots = sorted(set(slots_of(tpl)))
        bad_tpl = 0
        fails = defaultdict(list)
        n = 0
        for ph in [tpl] + [p for p in phr.get(tid, []) if p not in rejected.get(tid, [])]:
            for f in range(fills):
                vals = w.pick(rnd, slots)
                want = key(fill(tpl, vals, w.canon))
                if want.startswith(("NONE", "ASK")):
                    bad_tpl += 1
                    continue
                q = fill(ph, vals, lambda s, v: w.messy(rnd, s, v))
                got = key(q)
                n += 1
                if got != want:
                    fails[ph].append((q, want, got))
        ok = n - sum(len(v) for v in fails.values())
        total += n
        good += ok
        per[tid] = (ok, n)
        lines.append(f"\n=== {tid}: {ok}/{n} right   (clear: {tpl!r}){'   !! clear question not understood x' + str(bad_tpl) if bad_tpl else ''}")
        for ph, ex in sorted(fails.items(), key=lambda x: -len(x[1])):
            q, want, got = ex[0]
            lines.append(f"  {len(ex)}x  {ph!r}\n       e.g. {q!r}\n       want {short(want)}\n       got  {short(got)}")
    head = f"{good}/{total} questions right ({100 * good / max(total, 1):.1f}%)"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(head + "\n" + "\n".join(lines) + "\n")
    if not quiet:
        print(head)
        for tid, (ok, n) in per.items():
            if ok < n:
                print(f"  {tid:22} {ok}/{n}")
        print("details ->", REPORT)
    return good, total


def short(k):
    if k.startswith(("ASK", "NONE")):
        return k
    q = json.loads(k)
    return " ".join(f"{a}={json.dumps(b, separators=(',', ':'))}" for a, b in q.items())


# ---------------------------------------------------------------- 3. the permanent test
def cases(w, tid, tpl, ph, fills=2):
    """The same filled questions every time for one phrasing: [(question, clear question)]. The first uses the clear
    ways of writing the blanks, the others messy ones."""
    rnd = random.Random(f"bank|{tid}|{ph}")
    slots = sorted(set(slots_of(tpl)))
    out = []
    for f in range(fills):
        vals = w.pick(rnd, slots)
        form = w.canon if f == 0 else (lambda s, v: w.messy(rnd, s, v))
        out.append((fill(ph, vals, form), fill(tpl, vals, w.canon)))
    return out


def check_bank(bank, w=None):
    """-> the questions of the saved bank that no longer give the clear question's query (used by the tests)."""
    w = w or World()
    bad = []
    for tid, phs in bank["phrasings"].items():
        tpl = bank["templates"][tid]
        for ph in phs:
            for q, clear in cases(w, tid, tpl, ph):
                if key(q) != key(clear):
                    bad.append((tid, q, clear))
    return bad


def save():
    """Keeps every phrasing that passes now (and was not rejected by hand) as a test the rules must keep passing."""
    w = World()
    phr = json.load(open(PHRASINGS, encoding="utf-8"))
    rejected = json.load(open(REJECTED, encoding="utf-8")) if os.path.exists(REJECTED) else {}
    bank = {"_help": "Made-up questions for Ask, written by a local AI model from the clear question with blanks; each one "
                     "must give the same engine query as the clear question. Made by tools/ask_bank.py save.",
            "templates": dict(TEMPLATES), "phrasings": {}}
    kept = dropped = 0
    for tid, tpl in TEMPLATES:
        keep = [tpl] + [ph for ph in phr.get(tid, []) if ph not in rejected.get(tid, [])
                        and all(key(q) == key(clear) for q, clear in cases(w, tid, tpl, ph))]
        dropped += len(phr.get(tid, [])) - len(keep) + 1
        kept += len(keep)
        bank["phrasings"][tid] = keep
    json.dump(bank, open(BANK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{kept} phrasings kept in {BANK} ({dropped} not kept: nonsense, a changed meaning, or not understood yet)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "gen":
        generate(sys.argv[2] if len(sys.argv) > 2 else "rdps-qwen3b", int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    elif cmd == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 4, set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None)
    elif cmd == "save":
        save()
