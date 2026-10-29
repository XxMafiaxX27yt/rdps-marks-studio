"""Understands a question typed (or spoken) in plain English or Hinglish and
turns it into a structured query for query.py.

How it works (no internet, no AI needed):
1. find the things the question talks about - students (typos allowed), roll
   numbers, subjects (and short forms like "phy", "maths"), class, section,
   group, exam, numbers like "top 5" or "below 40";
2. find what is being asked (top / who / how many / average / compare ...)
   from keywords. If the small on-device AI model is loaded, the website also
   sends its best guesses ("hints") and they are used when keywords are unclear;
3. build the query. If something is missing or ambiguous it asks back with
   buttons instead of guessing. If it does not understand, it says so and
   suggests questions it can answer."""
import json
import os
import re

from .textutil import norm, similar, norm_name
from .layout import Vocab

_HERE = os.path.dirname(os.path.abspath(__file__))

STOP = set("""a an the is are was were be been of in on at to for and or but with by from as it its this that these those
who whom whose which what when where how why do does did done show tell me give list find get all any some my our your
their there here than then please can could would should will shall may might much many more most less least very also
student students bachhe bacche bache kids child children class section sec group stream exam test marks mark score scores
percentage percent per cent number count total average avg mean top bottom best worst highest lowest high low weak strong
good bad poor kaun kis kya hai hain ka ki ke ko mein me se aur ya bhi tha the thi ho hua hue got get scored score in out
than vs versus compare between subject subjects paper result results rank position name names roll no only each every
who's whats what's who is did does have has had not no yes""".split())

# "week"/"weekest" are how speech-to-text often writes "weak"/"weakest"
WEAK = ["weak", "weakest", "week", "weekest", "poor", "struggling", "struggle", "bad at", "kamzor", "kamjor", "not good",
        "needs improvement", "peeche", "pichhe", "piche", "behind", "lagging", "low scorers", "low scoring", "scoring low",
        "low marks", "less marks", "kam marks", "extra classes", "extra help", "remedial", "slow learners", "weak students"]
STRONG = ["strong", "good at", "good in", "better in", "achha in", "accha in", "excellent", "best at", "achha", "acha", "accha",
          "great at", "strongest", "achhe", "acche", "high scorers", "high marks", "scoring high", "bright students", "aage"]
ATTENTION = ["needs attention", "need attention", "attention", "needs help", "need help", "at risk", "concern", "critical",
             "needs support", "need support", "help needed"]
FAIL = ["fail", "failed", "failing", "not passed", "did not pass", "didn't pass", "didnt pass", "not pass", "could not pass",
        "couldn't pass", "pass nahi", "pass nhi", "pass nahin", "nahi pass", "nhi pass", "below pass", "below the pass", "flunk",
        "flunked", "flunking", "fail hue", "fail hua", "fail ho"]
PASSW = ["passed"]
ABSENT = ["absent", "missed", "gair hazir", "did not appear", "didn't appear"]
LEAVE = ["medical", "leave", "on leave", "ml", "duty leave"]


_CT = r"(?P<c>xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i|12|11|10|[1-9])"
CLASS_PATTERNS = [
    # class 6 / class xii b / std 9-c / grade 10 / class-6 (the class must end there: "class is", "standard in" are not class I)
    r"\b(?:class|std|standard|cls|grade|kaksha)\s*[-.:]?\s*" + _CT + r"(?:st|nd|rd|th)?(?![a-z0-9])(?:\s*[-/ ]?\s*(?P<s>[a-h])\b)?",
    # 6 class, 12th class, x class
    r"\b(?P<c>12|11|10|[1-9]|xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii)(?:st|nd|rd|th)?\s*-?\s*(?:class|std|kaksha)\b(?:\s*[-/ ]?\s*(?P<s>[a-h])\b)?",
    # 10th, 6th-b, 12th c
    r"\b(?P<c>12|11|10|[1-9])(?:st|nd|rd|th)\b(?:\s*[-/ ]?\s*(?P<s>[a-h])\b)?",
    # 11a, 6-b, 10/c, xi-a, vi b
    r"\b(?P<c>12|11|10|[1-9]|xii|xi|ix|viii|vii|vi|iv)\s*[-/]\s*(?P<s>[a-h])\b",
    r"\b(?P<c>12|11|10|[1-9]|xii|xi|ix|viii|vii|vi|iv)(?P<s>[a-h])\b",
    # 11 a, 12 b (a space and one letter - only for 6 to 12 so "top 5 a" stays a number)
    r"\b(?P<c>12|11|10|[6-9]|xii|xi|ix|viii|vii|vi)\s+(?P<s>[a-h])\b(?!\s*(?:\d|grade))",
    # a roman class on its own: xi, xii, ix, viii, vii, vi, iv
    r"\b(?P<c>xii|xi|ix|viii|vii|vi|iv)\b",
]
_ROMANS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "ek": 1, "teen": 3, "char": 4, "chaar": 4,
             "paanch": 5, "panch": 5, "das": 10}
_NUM = r"(\d{1,3}|" + "|".join(NUM_WORDS) + r")"


_NOT_CLASS = r"(?<!class )(?<!class-)(?<!std )(?<!grade )(?<!kaksha )\b"
# short misspellings the general typo check (5+ letters) does not catch
SHORT_TYPOS = {"thn": "than", "abv": "above", "blw": "below", "avrg": "average", "avg": "average", "ave": "average",
               "avr": "average", "aver": "average", "avre": "average", "pct": "percentage", "sect": "section",
               "sctn": "section", "secs": "sections", "ech": "each", "eech": "each", "subj": "subject", "subjs": "subjects",
               "sub": "subject", "subs": "subjects"}


def to_class(tok):
    t = tok.lower()
    if t.isdigit():
        n = int(t)
        return _ROMANS[n - 1] if 1 <= n <= 12 else None
    return t.upper() if t.upper() in _ROMANS else None


COMBO_WORDS = [("pcmb", "PCMB"), ("pcm", "PCM"), ("non medical", "PCM"), ("non-medical", "PCM"), ("pcb", "PCB"),
               ("commerce with maths", "Commerce with Maths"), ("commerce maths", "Commerce with Maths"),
               ("commerce without maths", "Commerce"), ("commerce", "*Commerce"), ("humanities", "Humanities"),
               ("arts", "Humanities"), ("science stream", "*Science"), ("science students", "*Science")]
GRADES_RE = r"\b(a1|a2|b1|b2|c1|c2|d1|d2)\b"
SUMMARY = ["result of", "results of", "summary", "overview", "performance of", "how is", "how are", "how did", "performing",
           "doing", "report of class", "class report", "overall result", "kaisa", "kaise", "kaisi", "ka result", "ki result",
           "result kya", "perform"]
# "above / below the class average": not a condition the engine has (Ask says so rather than guess)
VS_AVERAGE = ["above average", "below average", "above the average", "below the average", "average se upar",
              "average se neeche", "average se zyada", "average se kam", "avg se upar", "avg se kam", "than average",
              "than the average"]
# the words that decide what kind of question it is; a misspelling of one of these is read as the word
CORE_WORDS = ["average", "percentage", "percent", "highest", "lowest", "toppers", "topper", "compare", "improved",
              "dropped", "absent", "distribution", "hardest", "easiest", "toughest", "weakest", "strongest", "failed",
              "summary", "result", "results", "section", "students", "subject", "subjects", "marks", "maximum",
              "minimum", "attention", "struggling"]
# "who is the best" / "kaun hai" / "kiske": one student; "students", "kaun hain", "toppers": a list
SINGLE = ["kaun hai", "kon hai", "kaun h", "kiske", "kiska", "kiski", "kisne", "who is the", "who has the", "who got the",
          "which student", "who scored the", "who is first"]
PLURAL = ["students", "bacche", "bachhe", "bache", "kids", "toppers", "kaun hain", "kon hain", "who are", "list", "names",
          "log", "wale"]
TEACHER_WORDS = ["teacher", "teachers", "teacher wise", "teacherwise", "sir", "maam", "ma'am", "madam", "mr", "mrs", "ms",
                 "faculty", "teaching", "taught", "teaches"]


def _load_intents():
    with open(os.path.join(_HERE, "config", "intents.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _has(text, phrases):
    return any(re.search(r"(^|[^a-z0-9])" + re.escape(p) + r"($|[^a-z0-9])", text) for p in phrases)


class Understander:
    def __init__(self, ds=None, res=None, boards=None, cfg=None, teachers=None):
        self.ds, self.res, self.boards = ds, res, boards or []
        self.cfg = cfg or (ds.cfg if ds else None)
        self.teachers = teachers or []
        self.vocab = Vocab(self.cfg)
        self.intents = _load_intents()
        self.kw = {i["id"]: [k.lower() for k in i["keywords"]] for i in self.intents["intents"]}
        self._names = []
        if ds:
            for st in ds.students.values():
                toks = [t for t in norm_name(st.name).split() if t]
                if toks:
                    self._names.append((st.sid, toks))
        self.subject_words = set()
        for ph in self.vocab.subject_phrases:
            self.subject_words.update(ph.split())
        # words never "corrected": names, subjects, and every word of the keywords and examples
        self._known = set(STOP) | self.subject_words | {t for _, toks in self._names for t in toks}
        for i in self.intents["intents"]:
            for ph in i["keywords"] + i["examples"]:
                self._known.update(re.findall(r"[a-z]+", ph.lower()))
        for words in (WEAK, STRONG, ATTENTION, FAIL, ABSENT, SUMMARY, TEACHER_WORDS):
            for ph in words:
                self._known.update(re.findall(r"[a-z]+", ph))

    def _fix_typos(self, low):
        out = []
        for tok in re.findall(r"[a-z]+|[^a-z]+", low):
            if tok in SHORT_TYPOS and tok not in self._known:
                tok = SHORT_TYPOS[tok]
            elif tok.isalpha() and len(tok) >= 5 and tok not in self._known:
                tok = next((w for w in CORE_WORDS if similar(tok, w)), tok)
            out.append(tok)
        return "".join(out)

    # ============================================================ entities
    def entities(self, text):
        raw = text.strip()
        low = self._fix_typos(raw.lower().replace("’", "'"))
        e = {"raw": raw, "low": low, "n": None, "conds": [], "subjects": [], "students": [], "student_amb": [],
             "classes": [], "sections": [], "groups": [], "exams": [], "genders": [], "by": None, "rolls": [],
             "board_rolls": [], "used": set(), "combos": [], "teachers": [], "grades": []}
        work = low
        # numbers for "top 5", "best 10", "5 toppers"
        # ("top five", "paanch toppers": numbers in words too)
        m = re.search(r"\b(top|best|first|highest|bottom|lowest|last|worst|least)\s+" + _NUM + r"\b", work) or \
            re.search(r"(?<!class )(?<!std )(?<!grade )(?<!kaksha )\b" + _NUM + r"\s+(toppers|top|best|students|bachhe|bacche|kids|names|"
                      r"worst|lowest|bottom|weakest|last|highest|scorers)\b", work)
        if m:
            numg = 2 if m.group(2).isdigit() or m.group(2) in NUM_WORDS else 1
            num = m.group(numg)
            e["n"] = int(num) if num.isdigit() else NUM_WORDS[num]
            work = work.replace(m.group(0), " " + m.group(3 - numg) + " ")
        # thresholds
        thr = [(r"\bbetween\s+(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:and|to|-)\s*(\d{1,3}(?:\.\d+)?)", "between"),
               (r"(?:at most|not more than|up to|upto|<=)\s*(\d{1,3}(?:\.\d+)?)\s*%?", "<="),
               (r"(?:at least|not less than|minimum of|>=)\s*(\d{1,3}(?:\.\d+)?)\s*%?", ">="),
               (r"(?:below|under|less than|lower than|beneath|<|kam|neeche|se kam|\bless)\s*(\d{1,3}(?:\.\d+)?)\s*%?", "<"),
               (r"(?:above|over|more than|greater than|higher than|>|zyada|upar|se zyada|se jyada|\bmore)\s*(\d{1,3}(?:\.\d+)?)\s*%?", ">"),
               (_NOT_CLASS + r"(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:se kam|se kum|se neeche|se niche)\b", "<"),
               (_NOT_CLASS + r"(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:se zyada|se jyada|se ziada|se zada|se upar|se adhik|se badi|se bada)\b", ">"),
               (_NOT_CLASS + r"(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:or less|and below|or below)", "<="),
               (_NOT_CLASS + r"(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:or more|and above|or above|plus|\+)", ">=")]
        self._thresholds = []
        # "2 or more subjects" is a number of subjects, not a mark
        work = re.sub(r"\b(\d+|two|three|four)\s*(?:or more|\+|or above)?\s+subjects?\b", " ", work)
        for pat, op in thr:
            for mm in re.finditer(pat, work):
                if op == "between":
                    a, b = float(mm.group(1)), float(mm.group(2))
                    self._thresholds += [(">=", min(a, b), mm.start()), ("<=", max(a, b), mm.start())]
                else:
                    self._thresholds.append((op, float(mm.group(1)), mm.start()))
                work = work[:mm.start()] + " " * (mm.end() - mm.start()) + work[mm.end():]
        for sp_ in self._special_thresholds(low):
            if not any(t[0] == sp_[0] and t[1] == sp_[1] for t in self._thresholds):
                self._thresholds.append(sp_)
        # roll / admission / board roll numbers
        for mm in re.finditer(r"\broll\s*(?:no\.?|number|num)?\s*[:#]?\s*(\d{1,4})\b", work):
            e["rolls"].append(mm.group(1))
            work = work.replace(mm.group(0), " ")
        for mm in re.finditer(r"\b(\d{7,9})\b", work):
            e["board_rolls"].append(mm.group(1))
            work = work.replace(mm.group(0), " ")
        for mm in re.finditer(r"\b(?:adm(?:ission)?|admn)\s*(?:no\.?|number)?\s*[:#]?\s*(\d{2,7})\b", work):
            e["rolls"].append("adm:" + mm.group(1))
            work = work.replace(mm.group(0), " ")
        # class + section
        # "section a and b", "sections A & B"
        for mm in list(re.finditer(r"\bsections?\s*([a-h])\s*(?:and|&|vs|versus|aur|or|,)\s*(?:section\s*)?([a-h])\b", work)):
            e["sections"] += [mm.group(1).upper(), mm.group(2).upper()]
            work = work.replace(mm.group(0), " ", 1)
        # classes I-XII (+ section): "class 6", "class 12 b", "10th", "9th-c", "11a", "XI-A", "vi b", "class x"
        # (a bare number is only a class when the word class/std/grade is there or it carries a section/ordinal)
        for pat in CLASS_PATTERNS:
            while True:
                mm = re.search(pat, work)
                if not mm:
                    break
                cls = to_class(mm.group("c"))
                if not cls:
                    work = work[:mm.start()] + " " * (mm.end() - mm.start()) + work[mm.end():]
                    continue
                e["classes"].append(cls)
                if mm.groupdict().get("s"):
                    e["sections"].append(mm.group("s").upper())
                work = work[:mm.start()] + " " * (mm.end() - mm.start()) + work[mm.end():]
        # a lone capital X or V is Class X / V ("result of X") - small x / v are too common to be a class
        if not e["classes"]:
            for c in ("X", "V"):
                mm = re.search(r"\b" + c.lower() + r"\b", work)
                if mm and re.search(r"(?<![A-Za-z0-9])" + c + r"(?![A-Za-z0-9])", raw):
                    e["classes"].append(c)
                    work = work[:mm.start()] + " " + work[mm.end():]
                    break
        for mm in re.finditer(r"\b(?:section|sec)\.?\s*[-:]?\s*([a-h])\b|\b([a-h])\s*-?\s*(?:section|sec)\b", work):
            e["sections"].append((mm.group(1) or mm.group(2)).upper())
            work = work.replace(mm.group(0), " ", 1)
        for mm in re.finditer(r"\bgroup\s*([a-e])\b", work):
            e["groups"].append(mm.group(1).upper())
            work = work.replace(mm.group(0), " ", 1)
        # streams of XI-XII: PCM / PCB / PCMB / commerce (with maths) / humanities
        for ph, combo in COMBO_WORDS:
            if _has(work, [ph]):
                e["combos"].append(combo)
                work = re.sub(r"(^|[^a-z])" + re.escape(ph) + r"($|[^a-z])", r"\1 \2", work)
                break
        if _has(work, ["girls", "girl", "ladkiyan", "female"]):
            e["genders"].append("F")
        if _has(work, ["boys", "boy", "ladke", "male"]):
            e["genders"].append("M")
        # exams (all of them, in order)
        n = norm(work)
        toks = n.split()
        i = 0
        while i < len(toks):
            hit = None
            for k in range(min(4, len(toks) - i), 0, -1):
                ph = " ".join(toks[i:i + k])
                for cand in (ph, ph.replace(" ", "")):
                    if cand in self.vocab.exam_phrases and cand not in ("test", "final") and \
                            not (cand == "ye" and not re.search(r"\bYE\b", raw)):
                        hit = (self.vocab.exam_phrases[cand], k)
                        break
                if hit:
                    break
            if hit:
                if hit[0] not in e["exams"]:
                    e["exams"].append(hit[0])
                for j in range(i, i + hit[1]):
                    toks[j] = ""
                i += hit[1]
            else:
                i += 1
        if _has(low, ["final exam", "finals"]):
            e["exams"].append("YE") if "YE" not in e["exams"] else None
        toks = [t for t in toks if t]
        # subjects (positions in the remaining token list)
        subj_pos = []
        i = 0
        used_tok = set()
        while i < len(toks):
            hit = None
            for k in range(min(4, len(toks) - i), 0, -1):
                ph = " ".join(toks[i:i + k])
                if ph in self.vocab.subject_phrases:
                    code = self.vocab.subject_phrases[ph]
                    if ph == "pe" and not (re.search(r"\bPE\b|p\.e\b", raw)):
                        continue
                    if ph in ("ab", "a"):
                        continue
                    hit = (code, k)
                    break
            if not hit and len(toks[i]) >= 5 and toks[i] not in STOP:
                for ph, code in self.vocab.subject_phrases.items():
                    if " " not in ph and len(ph) >= 5 and similar(toks[i], ph):
                        hit = (code, 1)
                        break
            if hit:
                subj_pos.append((i, hit[0]))
                for j in range(i, i + hit[1]):
                    used_tok.add(j)
                i += hit[1]
            else:
                i += 1
        e["subj_pos"] = subj_pos
        for _, c in subj_pos:
            if c not in e["subjects"]:
                e["subjects"].append(c)
        # teachers (by name; before students, so "Mr Verma" is not read as a student)
        rest = [t if j not in used_tok else "" for j, t in enumerate(toks)]
        teacherish = _has(low, TEACHER_WORDS)
        for t in self.teachers:
            tt = [x for x in norm_name(t["name"]).split() if x not in ("mr", "mrs", "ms", "dr", "sir", "maam", "madam", "miss")]
            hit = [j for j, w in enumerate(rest) if w and len(w) >= 3 and w in tt]
            if hit and (teacherish or len(set(rest[j] for j in hit)) >= 2):
                if t["id"] not in e["teachers"]:
                    e["teachers"].append(t["id"])
                for j in hit:
                    rest[j] = ""
        # grades: "how many got A1"
        for mm in re.finditer(GRADES_RE, low):
            e["grades"].append(mm.group(1).upper())
        rest = [w if not re.fullmatch(GRADES_RE, w or "") else "" for w in rest]
        # students (full names first, then first names)
        self._find_students(rest, e)
        # labels with positions
        e["toks"] = toks
        e["label_pos"] = []
        joined = " ".join(toks)
        for label, words in (("Weak", WEAK), ("Strong", STRONG), ("Needs attention", ATTENTION)):
            for w in words:
                for mm in re.finditer(r"(^| )" + re.escape(w) + r"( |$)", joined):
                    pos = len(joined[:mm.start() + len(mm.group(1))].split())
                    e["label_pos"].append((pos, label, w))
        # "needs attention" also contains "attention": keep only the longest overlapping match
        kept = []
        for pos, label, w in sorted(e["label_pos"], key=lambda x: -len(x[2])):
            if not any(k[1] == label and abs(k[0] - pos) <= 2 for k in kept):
                kept.append((pos, label, w))
        e["label_pos"] = sorted(kept)
        # grouping words
        for by, words in (("section", ["by section", "section wise", "sectionwise", "each section", "per section", "every section",
                                       "all sections", "each sec", "per sec", "sec wise", "har section", "har sec"]),
                          ("subject", ["by subject", "subject wise", "subjectwise", "each subject", "per subject", "every subject",
                                       "all subjects"]),
                          ("exam", ["by exam", "exam wise", "each exam", "over time", "across exams", "per exam", "every exam",
                                    "trend"]),
                          ("group", ["by group", "group wise", "stream wise", "each group", "by stream", "each stream"]),
                          ("class", ["by class", "class wise", "each class"])):
            if _has(low, words):
                e["by"] = by
                break
        e["thresholds"] = self._thresholds
        return e

    def _find_students(self, toks, e):
        if not self._names:
            return
        idx = [(j, t) for j, t in enumerate(toks) if t]
        found = []
        # full names (2+ tokens)
        for sid, name in self._names:
            if len(name) < 2:
                continue
            for a in range(len(toks) - len(name) + 1):
                window = toks[a:a + len(name)]
                if all(w and (w == n or similar(w, n)) for w, n in zip(window, name)):
                    found.append(("full", sid, a, a + len(name)))
        taken = set()
        for kind, sid, a, b in found:
            taken.update(range(a, b))
        if found:
            sids = []
            for _, sid, a, b in found:
                if sid not in sids:
                    sids.append(sid)
            groups = {}
            for _, sid, a, b in found:
                groups.setdefault((a, b), []).append(sid)
            for (a, b), lst in groups.items():
                if len(lst) == 1:
                    e["students"].append(lst[0])
                else:
                    e["student_amb"].append({"text": " ".join(toks[a:b]), "sids": lst})
        # single words: first names (or surnames) - only if not a common word
        for j, t in idx:
            if j in taken or len(t) < 3 or t in STOP or t in self.subject_words:
                continue
            cands = [sid for sid, name in self._names if name[0] == t or (len(t) >= 5 and similar(name[0], t))]
            if not cands:
                continue
            if len(cands) == 1:
                if cands[0] not in e["students"]:
                    e["students"].append(cands[0])
            else:
                e["student_amb"].append({"text": t, "sids": cands})

    # ============================================================ intent
    def intent(self, e, hints=None):
        low = e["low"]
        kw = self.kw
        has_student = bool(e["students"] or e["student_amb"] or e["rolls"])
        if _has(low, kw["help"]) and len(low.split()) <= 6 and not _has(low, ATTENTION) and not (
                e["classes"] or e["subjects"] or has_student):
            return "help", "keyword"
        if self.boards and (e["teachers"] or _has(low, ["teacher", "teachers", "faculty"])) and \
                (not self.ds or _has(low, kw["board"])):
            return "teacher", "keyword"
        if self.boards and (_has(low, kw["board"]) or not self.ds):     # only board results loaded: every question is about them
            return "board", "keyword"
        if e["teachers"] or _has(low, ["teacher", "teachers", "teacher wise", "teacherwise", "faculty", "teaching",
                                       "who teaches", "taught by"]):
            return "teacher", "keyword"
        if not has_student and _has(low, ["internal", "internals", "portfolio", "portfolios", "project", "projects",
                                          "notebook", "notebooks", "nbk", "viva", "practical file", "internal assessment"]):
            return "internals", "keyword"
        # the class's weakest / strongest subject (no student named)
        if not has_student and _has(low, ["subject", "subjects"]) and not e["thresholds"] and not _has(low, kw["count"]):
            if _has(low, ["weakest", "weekest", "weak", "worst", "poorest", "lowest", "kamzor", "toughest", "tough", "hard",
                          "hardest", "difficult", "mushkil", "kathin", "sabse kam"]) and \
                    not _has(low, ["students weak", "who is weak", "who are weak", "students who"]):
                return "hardest", "keyword"
            if _has(low, ["strongest", "best", "strong", "highest", "easiest", "easy", "good", "acha", "achha", "accha",
                          "aasan", "asaan", "scoring"]) and \
                    not _has(low, ["each subject", "every subject", "subject toppers", "subject wise", "per subject",
                                   "all subjects", "subject topper", "sabhi subject", "har subject", "average", "students",
                                   "bacche"]) and not _has(low, ["who", "kaun"]):
                return "easiest", "keyword"
        topword = _has(low, ["top", "topper", "toppers", "topped", "first", "highest", "best", "rank 1", "number one",
                             "no 1", "number 1", "first position", "sabse achhe", "sabse zyada"])
        if topword and not has_student and _has(low, ["each section", "every section", "per section", "section wise",
                                                      "sectionwise", "section toppers", "section topper", "all sections",
                                                      "in each section", "har section", "each sec", "every sec", "har sec",
                                                      "sec wise", "secwise", "each sections"]):
            return "toppers_by_section", "keyword"
        if topword and not has_student and _has(low, ["each subject", "every subject", "per subject", "subject wise",
                                                      "subjectwise", "subject toppers", "subject topper", "all subjects",
                                                      "har subject"]):
            return "toppers_by_subject", "keyword"
        if not has_student and _has(low, ["which section", "what section", "kaun sa section", "konsa section", "best section",
                                          "worst section", "top section", "weakest section", "strongest section",
                                          "section wise result", "sabse achha section"]):
            e["by"] = "section"
            return "average", "keyword"
        if not has_student and _has(low, ["which class", "what class", "kaun si class", "konsi class"]) and \
                not _has(low, ["is in which class", "in which class is"]):
            e["by"] = "class"
            return "average", "keyword"
        if has_student:
            if _has(low, ["weakest", "weekest", "strongest", "best subject", "worst subject", "weak subject", "strong subject",
                          "kamzor subject", "which subject", "weak in which", "best subjects", "worst subjects", "top subject",
                          "top subjects", "toughest subject", "toughest subjects", "hardest subject", "hardest subjects",
                          "good subjects", "achhe subject", "scored well", "did well in", "weak subjects", "strong subjects",
                          "kamzor subjects", "kamjor subject"]):
                return "student_subjects", "keyword"
            if _has(low, kw["rank"]):
                return "rank", "keyword"
            if _has(low, kw["compare"]) and len(e["students"]) >= 2:
                return "compare_students", "keyword"
            return "student", "keyword"
        if not self._compare_groups(e) and not _has(low, ["compare", "vs", "versus", "tulna"]):
            if _has(low, kw["improved"]) and not _has(low, kw["dropped"]):
                return "improved", "keyword"
            if _has(low, kw["dropped"]):
                return "dropped", "keyword"
        if _has(low, kw["compare"]) or (len(e["sections"]) >= 2 or len(set(e["classes"])) >= 2 or len(e["groups"]) >= 2
                                       or len(e["genders"]) >= 2 or (len(e["exams"]) >= 2 and not e["thresholds"])) \
                and not _has(low, kw["count"]):
            if _has(low, kw["compare"]) or " vs " in f" {low} " or " and " in low or " aur " in low:
                return "compare", "keyword"
        if _has(low, kw["hardest"]):
            return "hardest", "keyword"
        if _has(low, kw["easiest"]) and not e["label_pos"]:
            return "easiest", "keyword"
        if _has(low, kw["improved"]) and not _has(low, kw["dropped"]):
            return "improved", "keyword"
        if _has(low, kw["dropped"]):
            return "dropped", "keyword"
        if _has(low, kw["pass_rate"]) or (re.search(r"\bpass", low) and re.search(r"percent|%|\bratio\b|\brate\b", low)
                                           and not e["thresholds"] and not _has(low, ["who", "kaun", "students who"])):
            return "pass_rate", "keyword"
        has_cond = bool(e["label_pos"] or e["thresholds"] or e["grades"] or _has(low, FAIL) or _has(low, ABSENT) or
                        _has(low, ["medical", "on leave", "duty leave"]))
        if _has(low, kw["distribution"]) and not e["label_pos"] and not (e["grades"] and _has(low, kw["count"] + ["who"])):
            return "distribution", "keyword"
        if _has(low, VS_AVERAGE):
            return ("count" if _has(low, kw["count"]) else "list"), "keyword"     # answered with "can't do that yet"
        if _has(low, ["average", "avg", "ausat"]) and not _has(low, ["students", "bacche", "bachhe", "kids", "se upar",
                                                                  "se neeche", "se zyada", "se kam"]) \
                and not e["label_pos"] and not e["thresholds"] and not _has(low, FAIL):
            return "average", "keyword"
        if _has(low, kw["count"]) or _has(low, ["what percentage of students", "what percent of students",
                                                "percentage of students", "kitne percent"]):
            return "count", "keyword"
        if _has(low, ["absent", "leave", "medical", "missed"]) and not e["label_pos"] and not e["thresholds"]:
            return "absent", "keyword"
        if e["n"] is not None or _has(low, ["toppers", "topper", "top", "topped", "rank list", "merit list", "merit",
                                            "rank 1", "number one", "first position", "came first", "is first",
                                            "stood first"]):
            if _has(low, ["bottom", "lowest", "last", "worst", "least", "sabse kam"]):
                return "bottom", "keyword"
            return "top", "keyword"
        if _has(low, ["sabse kam", "sabse kum"]) and not e["thresholds"] and \
                _has(low, ["who", "kaun", "kon", "kis", "kiske", "kiska", "kiski", "kisne", "students", "bacche"]):
            return "bottom", "keyword"
        if has_cond or (re.search(r"\bpass(?:ed)?\b", low) and _has(low, ["kaun", "who", "kis"])):
            return "list", "keyword"
        if (_has(low, SUMMARY) or re.search(r"\bresults?\b", low)) and not _has(low, ["average", "avg", "mean", "ausat"]):
            return "summary", "keyword"
        if _has(low, kw["average"]):
            return "average", "keyword"
        if _has(low, ["highest", "maximum", "max", "most marks", "sabse zyada", "best score"]):
            if _has(low, ["who", "kaun", "kis", "students", "scorers"]) and not e["subjects"]:
                return "top", "keyword"
            return "highest", "keyword"
        if _has(low, ["lowest", "minimum", "min", "least marks", "least", "worst score", "sabse kam", "sabse kum"]):
            if _has(low, ["who", "kaun", "kis", "kiske", "students", "scorers"]) and not e["subjects"]:
                return "bottom", "keyword"
            return "lowest", "keyword"
        if _has(low, ["best", "who scored the most", "achhe", "acche"]):
            return "top", "keyword"
        if _has(low, ["worst", "bottom"]):
            return "bottom", "keyword"
        if _has(low, ["list", "names", "show students", "students of", "student list", "all students", "students in",
                      "name list", "show all"]) or (e["classes"] and _has(low, ["students"])):
            return "list", "keyword"
        # no clear keyword: use the on-device AI's guess when it is confident
        if hints:
            best = max(hints, key=lambda h: h.get("score", 0))
            if best.get("score", 0) >= 0.55 and best["intent"] in self.kw:
                return best["intent"], f"AI match ({best['score']:.2f})"
        return None, ""

    # ============================================================ build query
    def parse(self, text, hints=None, force=None):
        """force: choices made by clicking a clarify button, e.g. {"student": "S0004"} or {"cls": "XI"}."""
        force = force or {}
        if not text or not text.strip():
            return {"unknown": True, "message": "Type a question first.", "suggestions": self.suggestions()}
        e = self.entities(text)
        if force.get("student"):
            e["students"], e["student_amb"] = [force["student"]], []
        if force.get("cls"):
            e["classes"] = [force["cls"]] + [c for c in e["classes"] if c != force["cls"]]
        intent, how = self.intent(e, hints)
        if intent is None:
            return {"unknown": True, "message": "Sorry, I did not understand that question, so I won't guess. "
                                                "Try one of these:", "suggestions": self.suggestions(e)}
        if e["student_amb"] and intent in ("student", "student_subjects", "rank"):
            amb = e["student_amb"][0]
            return {"clarify": True, "question": f"Which “{amb['text'].title()}” do you mean?",
                    "options": [{"label": self.ds.students[s].label(), "text": text, "force": dict(force, student=s)}
                                for s in amb["sids"][:8]]}
        if intent == "board":
            return self._board_query(e)
        q = {"op": intent, "scope": {}}
        sc = q["scope"]
        if e["classes"]:
            sc["cls"] = e["classes"][0]
        if e["sections"] and intent != "compare":
            sc["section"] = e["sections"][0]
        if e["groups"] and intent != "compare":
            sc["group"] = e["groups"][0]
        if e["genders"] and intent != "compare":
            sc["gender"] = e["genders"][0]
        if e["exams"] and not (intent == "compare" and len(e["exams"]) >= 2):
            sc["exam"] = e["exams"][0]
        if e["combos"] and intent != "compare":
            sc["combo"] = e["combos"][0]
        if e["n"] is not None:
            q["n"] = e["n"]
        elif intent == "top" and _has(e["low"], ["topped", "rank 1", "number one", "no 1", "number 1", "first position",
                                                  "came first", "is first", "stood first", "who is first", "who came first"]):
            q["n"] = 1
        elif intent in ("top", "bottom") and _has(e["low"], SINGLE) and not _has(e["low"], PLURAL):
            q["n"] = 1
        if e["by"] == "class" and len(set(e["classes"])) == 1:
            e["by"] = None                     # "each class 10" - one class cannot be split by class
        if not e["by"] and intent in ("average", "pass_rate") and not _has(e["low"], ["any subject", "one subject"]):
            if re.search(r"\bsec(?:tion)?s?\b|\bsectionwise\b", e["low"]) and not e["sections"]:
                e["by"] = "section"
            elif re.search(r"\bsubjects?\b", e["low"]) and not e["subjects"]:
                e["by"] = "subject"
        if e["by"] and intent in ("average", "pass_rate", "count"):
            q["by"] = e["by"]
        if intent == "teacher" and self.boards and (not self.ds or _has(e["low"], self.kw["board"])):
            q = {"op": "board_teachers"}
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
            if _has(e["low"], ["not doing well", "not working", "not good", "worst", "weak", "poor", "bad", "lowest", "low",
                               "kharab", "kamzor", "below"]):
                q["order"] = "low"
            elif _has(e["low"], ["best", "good", "top", "strong", "highest", "doing well", "excellent", "achha"]):
                q["order"] = "high"
            return {"query": q, "matched_by": how, "understood": "Understood as: teachers on the board results"
                    + (" (lowest first)" if q.get("order") == "low" else " (best first)" if q.get("order") == "high" else "")}
        if intent == "teacher":
            q["teachers"] = e["teachers"]
            if _has(e["low"], ["not doing well", "not working", "not good", "not performing", "worst", "weak", "poor",
                               "bad", "lowest", "low", "kharab", "kamzor", "need help", "needs help", "need support",
                               "struggling", "underperform", "not up to", "below"]):
                q["order"] = "low"
            elif _has(e["low"], ["best", "good", "top", "strong", "highest", "doing well", "excellent", "achha", "acha"]):
                q["order"] = "high"
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
            return self._done(q, how, e)
        if intent in ("toppers_by_section", "toppers_by_subject"):
            q["op"] = "toppers_by"
            q["by"] = "section" if intent == "toppers_by_section" else "subject"
            if e["subjects"] and q["by"] == "section":
                q["subject"] = e["subjects"][0]
            intent = "toppers_by"
        if intent == "internals":
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
            if _has(e["low"], WEAK + FAIL + ["low", "less", "kam", "below", "not submitted", "didn't submit", "did not submit",
                                             "missing", "incomplete"]):
                q["level"] = "low"
            for part, words in (("notebook", ["notebook", "nbk", "notebooks"]), ("portfolio", ["portfolio", "portfolios"]),
                                ("project", ["project", "projects"]), ("viva", ["viva"]), ("file", ["practical file"])):
                if _has(e["low"], words):
                    q["part"] = part
            return self._done(q, how, e)
        if intent == "summary":
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
            return self._done(q, how, e)
        # students
        if intent in ("student", "student_subjects", "rank"):
            sid = self._student_from(e)
            if isinstance(sid, dict):
                return sid
            if sid is None:
                return {"unknown": True, "message": "I could not find that student in the uploaded marks.",
                        "suggestions": self.suggestions(e)}
            q["students"] = [sid]
            st = self.ds.students[sid]
            sc["cls"] = st.cls
            sc.pop("section", None)
            if intent == "student_subjects":
                q["order"] = "strongest" if _has(e["low"], ["strongest", "best", "strong", "achha", "achhe", "good", "top",
                                                            "scored well", "did well"]) else "weakest"
            return self._done(q, how, e)
        if intent == "compare_students":
            return self._compare_students(e)
        # subjects / conditions
        if intent in ("top", "bottom", "average", "highest", "lowest", "pass_rate", "distribution", "absent"):
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
        if intent in ("list", "count"):
            q["conds"] = self._conds(e)
            # "above / below the class average" is not a condition the engine has - say so instead of counting everybody
            if _has(e["low"], VS_AVERAGE) and all(c.get("op") == ">=" and c.get("value") == 0 for c in q["conds"]):
                return {"unknown": True, "message": "I can't compare with the class average yet, so I won't guess. "
                                                    "Ask with a mark instead (e.g. “who scored above 60 in maths”), or ask "
                                                    "for the average first.", "suggestions": self.suggestions(e)}
        if intent == "count" and not q.get("conds"):
            q["conds"] = []
        if intent == "absent":
            q["status"] = "LEAVE" if _has(e["low"], ["medical", "leave", "duty"]) and not _has(e["low"], ["absent"]) else "AB"
        if intent == "dropped":
            q["twice"] = _has(e["low"], ["twice", "two times", "in a row", "2 times", "two exams", "consecutive"])
        if intent == "compare":
            groups = self._compare_groups(e)
            if groups.get("subjects"):
                q["subjects"] = groups["subjects"]
            elif groups.get("groups"):
                q["groups"] = groups["groups"]
                if e["subjects"]:
                    q["subject"] = e["subjects"][0]
            else:
                return {"clarify": True, "question": "What should I compare?",
                        "options": [{"label": "Section A vs Section B", "text": "compare section A and B"},
                                    {"label": "Class XI vs Class XII", "text": "compare class XI and XII"},
                                    {"label": "Two subjects", "text": "compare physics and chemistry"}]}
        if intent in ("hardest", "easiest") and e["subjects"]:
            pass
        # which class? (ranking-type questions need one class)
        needs_class = intent in ("top", "bottom", "highest", "lowest", "hardest", "easiest", "toppers_by",
                                 "distribution") or (intent in ("average", "pass_rate") and q.get("by") != "class") or \
            (intent == "compare" and not any("cls" in g for g in q.get("groups", [])))
        classes = self.ds.classes()
        if needs_class and not sc.get("cls") and len(classes) > 1:
            return {"clarify": True, "question": "Which class?",
                    "options": [{"label": self.cfg.class_label(c), "text": text, "force": dict(force, cls=c)} for c in classes]}
        if not sc.get("cls") and len(classes) == 1:
            sc["cls"] = classes[0]
        return self._done(q, how, e)

    def _done(self, q, how, e):
        return {"query": q, "matched_by": how, "understood": self.describe(q)}

    def _rewrite(self, text, part, sid):
        st = self.ds.students[sid]
        return re.sub(re.escape(part), st.name, text, flags=re.I) + (f" roll {st.roll}" if st.roll else "") + \
               f" class {st.cls}" + (f" section {st.section}" if st.section else "")

    def _student_from(self, e):
        if e["students"]:
            sid = e["students"][0]
            # if class/section/roll given, make sure it fits
            return sid
        if e["rolls"]:
            r = e["rolls"][0]
            if r.startswith("adm:"):
                lst = [s for s in self.ds.students.values() if s.adm_no == r[4:]]
            else:
                lst = [s for s in self.ds.students.values() if s.roll == r
                       and (not e["classes"] or s.cls == e["classes"][0])
                       and (not e["sections"] or s.section == e["sections"][0])]
            if len(lst) == 1:
                return lst[0].sid
            if len(lst) > 1:
                return {"clarify": True, "question": f"Roll {r} is in more than one class/section. Which one?",
                        "options": [{"label": s.label(), "text": e["raw"], "force": {"student": s.sid}} for s in lst[:8]]}
        if e["board_rolls"]:
            lst = [s for s in self.ds.students.values() if s.board_roll == e["board_rolls"][0]]
            if lst:
                return lst[0].sid
        return None

    def _conds(self, e):
        conds = []
        sp = list(e["subj_pos"])
        used = set()
        low = e["low"]
        for pos, label, word in e["label_pos"]:
            best = None
            for k, (p, code) in enumerate(sp):
                if k in used:
                    continue
                d = p - pos
                score = d if d > 0 else (-d + 3)        # prefer a subject after the word ("weak in maths")
                # Hinglish puts the subject first: "maths me kamzor", "science mein achhe"
                if d < 0 and p + 1 < len(e["toks"]) and e["toks"][p + 1] in ("me", "mein", "main", "mai", "mei"):
                    score = -d - 1
                if abs(d) <= 6 and (best is None or score < best[0]):
                    best = (score, k, code)
            subj = best[2] if best else None
            if best:
                used.add(best[1])
            # what teachers mean by "weak in Chemistry" is low marks in Chemistry (not "below their own average"),
            # unless the question says so ("compared to their own average", "weaker than usual")
            relative = _has(low, ["own average", "their average", "his average", "her average", "than usual",
                                  "compared to", "relative", "other subjects", "than other"])
            if label in ("Weak", "Strong") and not relative:
                conds.append({"level": "low" if label == "Weak" else "high", "subject": subj})
            else:
                conds.append({"label": label, "subject": subj})
        left = [code for k, (p, code) in enumerate(sp) if k not in used]
        any_subject = _has(low, ["any subject", "in any", "kisi bhi subject", "kisi subject", "at least one subject",
                                 "one or more subjects", "some subject"])
        for op, val, _ in e["thresholds"]:
            c = {"op": op, "value": val, "subject": left[0] if left else (sp[0][1] if sp and not conds else None)}
            if any_subject and not c["subject"]:
                c["any"] = True
            conds.append(c)
        for g in e["grades"]:
            conds.append({"grade": g, "subject": left[0] if left else None})
        if _has(low, FAIL):
            c = {"result": "not_passed", "subject": left[0] if left and not e["thresholds"] else None}
            more = re.search(r"(?:\bmore than|>)\s*(\d|one|two|three|four)\s+subjects?\b", low)
            m = re.search(r"\b(?:more than one|more than 1|two or more|2 or more|at least two|at least 2|multiple|"
                          r"many|several|(\d|two|three|four))\s+subjects?\b", low)
            words = {"one": 1, "two": 2, "three": 3, "four": 4}
            if more:
                g = more.group(1)
                c["min"] = (int(g) if g.isdigit() else words[g]) + 1
                c["subject"] = None
            elif m:
                g = m.group(1)
                c["min"] = int(g) if g and g.isdigit() else words.get(g, 2)
                c["subject"] = None
            conds.append(c)
        elif _has(low, ["who passed", "students passed", "have passed", "has passed", "passed", "how many pass",
                        "kitne pass", "kitne bacche pass", "kaun pass", "who pass", "pass hue", "pass hua", "pass ho",
                        "pass kiya", "pass huye", "pass kaun"]):
            conds.append({"result": "passed", "subject": left[0] if left else None})
        if _has(low, ABSENT):
            conds.append({"status": "AB", "subject": left[0] if left else None})
        elif _has(low, ["medical", "on leave", "duty leave"]):
            conds.append({"status": "LEAVE", "subject": left[0] if left else None})
        if not conds and e["subjects"]:
            conds.append({"op": ">=", "value": 0, "subject": e["subjects"][0]})
        return conds

    def _special_thresholds(self, low):
        """Words that mean a mark: distinction (75%+), full marks / centum (100)."""
        out = []
        if _has(low, ["distinction", "distinctions"]):
            out.append((">=", float(self.cfg.rules.get("distinction_percent", 75)), 0))
        if _has(low, ["full marks", "centum", "cent percent", "100 out of 100", "perfect score", "100 marks"]) or \
                re.search(r"\b(?:got|scored|with|get)\s+100\b(?!\s*%?\s*(?:students|bachhe))", low):
            out.append((">=", 100.0, 0))
        return out

    def _compare_groups(self, e):
        if len(e["subjects"]) >= 2 and not (len(e["sections"]) >= 2 or len(set(e["classes"])) >= 2):
            return {"subjects": e["subjects"][:4]}
        if len(e["sections"]) >= 2:
            return {"groups": [{"section": s} for s in e["sections"][:2]]}
        if len(set(e["classes"])) >= 2:
            cl = []
            for c in e["classes"]:
                if c not in cl:
                    cl.append(c)
            return {"groups": [{"cls": c} for c in cl[:2]]}
        if len(e["groups"]) >= 2:
            return {"groups": [{"group": g} for g in e["groups"][:2]]}
        if len(e["genders"]) >= 2:
            return {"groups": [{"gender": "F"}, {"gender": "M"}]}
        if len(e["exams"]) >= 2:
            return {"groups": [{"exam": x} for x in e["exams"][:2]]}
        return {}

    def _compare_students(self, e):
        rows = []
        cfg = self.cfg
        q = {"op": "student", "scope": {}, "students": e["students"][:1]}
        return {"query": q, "matched_by": "keyword", "understood": "Showing the first student - compare students one at a time.",
                "note": "Comparing two named students is shown one by one."}

    def _board_query(self, e):
        low = e["low"]
        if e["board_rolls"]:
            q = {"op": "board_student", "roll": e["board_rolls"][0]}
        elif e["students"] or e["student_amb"]:
            names = [self.ds.students[s].name for s in e["students"]] if e["students"] else []
            an = self.boards[-1]
            hit = [r for r in an["rows"] if norm_name(r["s"].name) in [norm_name(n) for n in names]]
            if not hit:
                toks = set(e["toks"])
                hit = [r for r in an["rows"] if set(norm_name(r["s"].name).split()) & toks - STOP]
            if len(hit) == 1:
                q = {"op": "board_student", "roll": hit[0]["s"].roll}
            elif hit:
                return {"clarify": True, "question": "Which student?",
                        "options": [{"label": f"{r['s'].name} ({r['s'].roll})", "text": f"board result of {r['s'].roll}"}
                                    for r in hit[:8]]}
            else:
                q = {"op": "board_summary"}
        elif _has(low, ["compartment", "comp", "comptt", "supplementary"]):
            q = {"op": "board_comp"}
        elif _has(low, ["every subject", "all subjects", "each subject", "all rounder", "allrounder", "all-rounder",
                        "har subject", "sab subject", "sabhi subject", "all the subjects"]) and \
                not _has(low, ["topper of each", "toppers of each", "top in each", "subject toppers", "subject wise"]):
            nums = [int(x) for x in re.findall(r"\b(\d{2,3})\b", low) if 33 <= int(x) <= 100]
            q = {"op": "board_allround", "value": nums[0] if nums else 90}
        elif _has(low, ["hardest", "toughest", "difficult", "easiest", "tough", "mushkil", "kathin", "aasan", "easy"]):
            q = {"op": "board_hardest", "order": "easy" if _has(low, ["easiest", "easy", "aasan"]) else "hard"}
        elif _has(low, ["stream", "streams", "science", "commerce", "humanities", "arts", "medical", "non medical",
                        "pcm", "pcb"]):
            q = {"op": "board_streams"}
            for words, name in ((["science", "medical", "non medical", "pcm", "pcb", "pcmb"], "Science"),
                                (["commerce"], "Commerce"), (["humanities", "arts"], "Humanities")):
                if _has(low, words):
                    q["stream"] = name
                    break
            if e["n"]:
                q["n"] = e["n"]
        elif _has(low, self.kw["top"] + ["topper", "toppers", "rank"]) or e["n"]:
            q = {"op": "board_top", "n": e["n"] or 10}
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
        elif e["subjects"] or _has(low, ["subject", "subjects", "average", "pi", "performance index"]):
            q = {"op": "board_subject"}
            if e["subjects"]:
                q["subject"] = e["subjects"][0]
        else:
            q = {"op": "board_summary"}
        if e["classes"] and any((a["meta"].get("cls") or "") == e["classes"][0] for a in self.boards):
            q["cls"] = e["classes"][0]                  # "class 10 board toppers" -> the Class X results
        return {"query": q, "matched_by": "keyword", "understood": self.describe(q)}

    # ============================================================ words
    def describe(self, q):
        cfg = self.cfg
        op = q["op"]
        sc = q.get("scope", {})
        bits = {"top": "top students", "bottom": "lowest students", "list": "students who are", "count": "count students who are",
                "average": "average %", "highest": "highest %", "lowest": "lowest %", "hardest": "hardest subject",
                "easiest": "easiest subject", "compare": "compare", "student": "student's marks",
                "student_subjects": "student's subjects in order", "rank": "student's rank", "pass_rate": "pass rate",
                "distribution": "grade distribution", "improved": "most improved", "dropped": "students who dropped",
                "absent": "absent / on leave", "help": "help", "summary": "summary of results",
                "toppers_by": "toppers", "teacher": "teacher results", "internals": "internal marks",
                "board_streams": "board results by stream", "board_allround": "board: high marks in every subject",
                "board_hardest": "board: harder / easier subjects for the same students"}.get(op, op.replace("_", " "))
        parts = [bits]
        if q.get("n"):
            parts.append(f"(n = {q['n']})")
        if q.get("stream"):
            parts.append(q["stream"])
        if op == "board_allround":
            parts.append(f"({q.get('value', 90)} or more)")
        if op == "board_hardest":
            parts.append("(easiest first)" if q.get("order") == "easy" else "(hardest first)")
        if q.get("cls") and op.startswith("board"):
            parts.append(f"Class {q['cls']}")
        if q.get("subject"):
            parts.append(f"in {cfg.subject_name(q['subject'])}")
        for c in q.get("conds", []):
            s = cfg.subject_name(c["subject"]) if c.get("subject") else "any subject"
            if c.get("label"):
                parts.append(f"[{c['label']} in {s}]")
            elif c.get("op"):
                parts.append(f"[{s if c.get('subject') else ('any subject' if c.get('any') else 'overall')} {c['op']} {c['value']}%]")
            elif c.get("grade"):
                parts.append(f"[grade {c['grade']}{' in ' + s if c.get('subject') else ''}]")
            elif c.get("level"):
                parts.append(f"[{'low' if c['level'] == 'low' else 'high'} marks in {s if c.get('subject') else 'overall %'}]")
            elif c.get("result"):
                parts.append(f"[{c['result'].replace('_', ' ')}{' in ' + s if c.get('subject') else ''}"
                             f"{' in ' + str(c['min']) + '+ subjects' if c.get('min') else ''}]")
            elif c.get("status"):
                parts.append(f"[{c['status']}{' in ' + s if c.get('subject') else ''}]")
        if q.get("subjects"):
            parts.append(" vs ".join(cfg.subject_name(s) for s in q["subjects"]))
        if q.get("groups"):
            parts.append(" vs ".join(", ".join(f"{k}={v}" for k, v in g.items()) for g in q["groups"]))
        if q.get("by"):
            parts.append(f"by {q['by']}")
        if q.get("students") and self.ds:
            parts.append(self.ds.students[q["students"][0]].name)
        if q.get("order") and op == "teacher":
            parts.append("(lowest results first)" if q["order"] == "low" else "(best results first)")
        if q.get("teachers"):
            names = {t["id"]: t["name"] for t in self.teachers}
            parts.append(", ".join(names.get(t, t) for t in q["teachers"]))
        scope = []
        if sc.get("cls"):
            scope.append(f"Class {sc['cls']}")
        if sc.get("section"):
            scope.append(f"Section {sc['section']}")
        if sc.get("group"):
            scope.append(f"Group {sc['group']}")
        if sc.get("combo"):
            scope.append(sc["combo"].lstrip("*"))
        if sc.get("gender"):
            scope.append({"F": "girls", "M": "boys"}[sc["gender"]])
        if sc.get("exam"):
            scope.append(cfg.exam_name(sc["exam"]))
        if scope:
            parts.append("- " + ", ".join(scope))
        return "Understood as: " + " ".join(parts)

    def suggestions(self, e=None):
        """Example questions that use real names from the uploaded data."""
        out = []
        if self.ds and self.ds.students:
            classes = self.ds.classes()
            cls = classes[0]
            subs = self.ds.subjects_for(cls)
            sub1 = self.cfg.subject_name(subs[1] if len(subs) > 1 else subs[0]) if subs else "Maths"
            sub2 = self.cfg.subject_name(subs[2] if len(subs) > 2 else subs[0]) if subs else "Physics"
            secs = self.ds.sections_for(cls)
            st = self.ds.ordered_students()[min(3, len(self.ds.students) - 1)]
            out = [f"Top 5 in Class {cls}",
                   f"Who is weak in {sub1} but strong in {sub2}?",
                   f"Which subject is hardest in Class {cls}?",
                   f"Show {st.name.split()[0]}'s weakest subjects",
                   f"How many students are below 40% in {sub2}?",
                   "Who improved the most?"]
            if len(secs) >= 2:
                out.insert(4, f"Compare section {secs[0]} and {secs[1]} in class {cls}")
            out.append(f"Average by section in class {cls}")
        if self.boards:
            out += ["Board toppers", "Board compartment list"]
        return out[:8]
