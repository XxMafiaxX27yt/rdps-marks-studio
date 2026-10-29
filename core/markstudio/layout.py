"""Works out what each column of an uploaded table means ("this is the student's
name", "this is Physics theory in the Half Yearly", ...).

It only *proposes* a mapping. Anything it is not sure about is marked
sure=False and the teacher must confirm it on the check screen before any
workbook is made. The teacher's choices are saved, so the same file layout is
recognised automatically next time."""
import re

from .textutil import norm, clean, parse_number

# ---------------------------------------------------------------- vocabulary
# "Language" column: numbers = the marks of each student's own language (French / German / ...),
# text = which language the student takes
LANG_WORDS = ["language", "2nd language", "second language", "3rd language", "third language", "optional language",
              "foreign language", "language subject", "language opted", "language chosen", "hindi or language",
              "hindi language", "hindi or other language", "lang", "ii language", "iii language", "2nd lang", "3rd lang"]
LANG_MARK = "@LANG"
LANG_PHRASES = {" ".join(p.split()) for p in LANG_WORDS}

FIELD_WORDS = [
    # (role, phrases) - checked in this order, first match wins
    ("sno", ["s no", "sno", "sr no", "srno", "sl no", "slno", "serial", "serial no", "s n", "sr", "s r no", "no"]),
    ("board_roll", ["board roll", "board roll no", "board roll number", "cbse roll", "cbse roll no", "roll no board",
                    "board no", "brn", "board r no"]),
    ("adm_no", ["adm no", "admission no", "admission number", "adm", "admission", "admn no", "admn", "adm number",
                "scholar no", "enrolment no", "enrollment no", "enrol no", "registration no", "reg no", "student id", "id"]),
    ("roll", ["roll no", "roll number", "roll", "r no", "class roll", "class roll no", "rollno"]),
    ("father", ["father name", "father s name", "fathers name", "father", "f name", "father s nm", "fname", "f s name"]),
    ("mother", ["mother name", "mother s name", "mothers name", "mother", "m name", "mname", "m s name"]),
    ("name", ["name", "student name", "name of student", "name of the student", "student s name", "students name",
              "candidate", "candidate name", "name of candidate", "student", "pupil", "full name"]),
    ("class_section", ["class section", "class sec", "class and section", "class & section", "cls sec", "class div",
                       "class division", "std div"]),
    ("class", ["class", "std", "standard", "cls"]),
    ("section", ["section", "sec", "div", "division"]),
    ("group", ["group", "stream", "grp", "subject group"]),
    ("gender", ["gender", "sex", "m f", "boy girl"]),
    ("lang_slot", LANG_WORDS),
    ("choice", ["subject 1", "subject 2", "subject 3", "subject 4", "subject 5", "subject 6", "subject 7",
                "sub 1", "sub 2", "sub 3", "sub 4", "sub 5", "sub 6", "optional", "optional subject", "elective",
                "elective subject", "additional subject", "subjects", "subjects taken", "subject combination"]),
    ("row_subject", ["subject", "sub", "subject name", "subject code"]),
    ("row_exam", ["exam", "test", "examination", "exam name", "test name", "assessment"]),
    ("file_total", ["total", "grand total", "gt", "total marks", "marks total", "aggregate", "agg", "total obtained"]),
    ("file_percent", ["percentage", "percent", "per", "%", "perc", "pct", "perc %", "percentage %", "aggregate %"]),
    ("file_grade", ["grade", "grd", "overall grade", "final grade", "grades", "cgpa", "gpa", "division"]),
    ("file_result", ["result", "results", "pass fail", "pass or fail", "final result", "status", "promoted",
                     "promotion", "remarks result"]),
    ("ignore", ["rank", "position", "remarks", "remark", "attendance", "signature", "sign",
                "max", "max marks", "mm", "date", "dob", "date of birth", "phone", "mobile", "address", "house"]),
]

THEORY_WORDS = {"th", "theory", "thy", "theo", "written", "wr", "theor", "thry", "w", "wt", "writ"}
PRACTICAL_WORDS = {"pr", "prac", "practical", "practicals", "pract", "lab", "prc", "prctl"}
INTERNAL_WORDS = {"internal", "internals", "int", "ia", "i a", "internal assessment", "int assessment", "int ass",
                  "internal marks", "ia marks"}
TOTAL_WORDS = {"total", "tot", "ttl"}
# parts of the internal assessment / AI practical (more specific phrases first)
PART_WORDS = [
    ("viva", ["viva voce", "viva", "oral"]),
    ("file", ["practical file", "prac file", "pr file", "lab file", "record file", "file", "record"]),
    ("ptest", ["practical test", "prac test", "pr test", "lab test", "practical exam"]),
    ("notebook", ["notebook submission", "note book", "notebook", "nbk", "nb", "notebooks", "copy", "nb submission"]),
    ("portfolio", ["portfolio", "portfolios", "port folio", "pf", "port"]),
    ("project", ["subject enrichment", "project", "projects", "proj", "prj", "activity"]),
    ("pt5", ["pt part", "pt 5", "pt5", "periodic test part", "pt scaled", "pt out of 5", "pt in internal"]),
]
PART_KEYS = {"notebook": ("i_notebook", "p_notebook"), "portfolio": ("i_portfolio",), "project": ("i_project",),
             "viva": ("p_viva",), "file": ("p_file",), "ptest": ("p_test",), "pt5": ("i_pt",)}
LONG_MARK_WORDS = {"marks", "marks obtained", "mark", "score", "obtained", "mo", "marks obt"}

# ---------------------------------------------------------------- classes I-XII
ROMANS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
CLASS_TOKEN = r"(xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i|12|11|10|9|8|7|6|5|4|3|2|1)"
_SAFE_LONE = {"xii", "xi", "ix", "viii", "vii", "vi", "iv", "6th", "7th", "8th", "9th", "10th", "11th", "12th",
              "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "sixth", "seventh", "eighth", "ninth", "tenth",
              "eleventh", "twelfth"}


def to_class(tok):
    """'12' / 'xii' -> 'XII', '6' / 'vi' -> 'VI'."""
    t = tok.lower()
    if t.isdigit():
        n = int(t)
        return ROMANS[n - 1] if 1 <= n <= 12 else None
    return t.upper() if t.upper() in ROMANS else None


def class_token_match(n):
    """Whole text is a class with an optional section: 'xi', '6', 'via', '11 a', 'class 9-c', '10th b' -> ('IX', 'C')."""
    t = n.strip()
    m = re.match(r"^(?:class|std|grade|standard)?\s*" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\s*[-/ ]?\s*([a-h])?$", t)
    if not m:
        return None
    cls = to_class(m.group(1))
    return (cls, (m.group(2) or "").upper()) if cls else None


def _safe_lone_class(tok):
    return tok in _SAFE_LONE


class Vocab:
    """Fast lookups built from the settings."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.subject_phrases = {}
        for code, s in cfg.subjects.items():
            for p in [s["name"], s["short"]] + s.get("synonyms", []):
                self.subject_phrases.setdefault(norm(p), code)
            self.subject_phrases.setdefault(code, code)
            self.subject_phrases.setdefault(str(int(code)), code) if code.isdigit() and int(code) >= 100 else None
        self.exam_phrases = {}
        for ex, e in cfg.exams.items():
            for p in [ex, e["name"]] + e.get("aliases", []):
                n = norm(p)
                self.exam_phrases.setdefault(n, ex)
                self.exam_phrases.setdefault(n.replace(" ", ""), ex)
        self.class_phrases = {}
        for c, info in cfg.classes.items():
            for p in [c, info["label"]] + info.get("aliases", []):
                self.class_phrases.setdefault(norm(p), c)
        self.group_phrases = {}
        for g in cfg.groups:
            for p in ["group " + g["id"].lower(), g["name"]] + g.get("aliases", []):
                self.group_phrases.setdefault(norm(p), g["id"])
        self.field_phrases = [(role, {norm(p) for p in ps}) for role, ps in FIELD_WORDS]

    # -- finders return (value, how) where how in {'exact','partial',None}
    def find_subject(self, text):
        toks = norm(text).split()
        best = None
        for n in range(min(4, len(toks)), 0, -1):
            for i in range(len(toks) - n + 1):
                ph = " ".join(toks[i:i + n])
                if ph in self.subject_phrases:
                    code = self.subject_phrases[ph]
                    if best is None or n > best[1]:
                        best = (code, n, i)
            if best:
                break
        return best[0] if best else None

    def find_subject_fuzzy(self, text):
        from .textutil import similar
        toks = norm(text).split()
        for t in toks:
            if len(t) < 5:
                continue
            for ph, code in self.subject_phrases.items():
                if " " not in ph and len(ph) >= 5 and similar(t, ph):
                    return code
        return None

    def find_exam(self, text):
        n = norm(text)
        toks = n.split()
        found = None
        for k in range(min(5, len(toks)), 0, -1):
            for i in range(len(toks) - k + 1):
                ph = " ".join(toks[i:i + k])
                for cand in (ph, ph.replace(" ", "")):
                    if cand in self.exam_phrases:
                        return self.exam_phrases[cand]
        return found

    def find_class(self, text):
        n = norm(text)
        # the whole text is a class (+ section): "XI", "6", "via", "11a", "xii-b", "class 9 c"
        cs = class_token_match(n)
        if cs:
            return cs[0]
        toks = n.split()
        for k in range(min(3, len(toks)), 0, -1):
            for i in range(len(toks) - k + 1):
                ph = " ".join(toks[i:i + k])
                if ph not in self.class_phrases:
                    continue
                # a lone "1", "i", "v", "x" or "2nd" inside longer text ("Sheet 1", "Term I", "2nd term")
                # is not a class; "class 1" / "XI" / "eleventh" are
                if k == 1 and not _safe_lone_class(ph):
                    continue
                return self.class_phrases[ph]
        return None

    def find_component(self, text, bottom_cell=None):
        n = norm(text)
        for key, phrases in PART_WORDS:
            for p in phrases:
                if re.search(r"(^| )" + re.escape(p) + r"( |$)", n):
                    return key
        toks = set(n.split())
        if n in INTERNAL_WORDS or toks & {"internal", "internals", "ia", "int"} or "internal assessment" in n:
            return "practical"
        if toks & PRACTICAL_WORDS:
            return "practical"
        if toks & THEORY_WORDS:
            return "theory"
        if toks & TOTAL_WORDS:
            return "total"
        b = norm(bottom_cell or "")
        if b in ("t",):
            return "theory"
        if b in ("p",):
            return "practical"
        return None

    def find_field(self, text):
        n = norm(text)
        if not n:
            return None
        if n in ("%",) or clean(text) == "%":
            return "file_percent"
        for role, phrases in self.field_phrases:
            if n in phrases:
                return role
        # partial: phrase contained as whole words (e.g. "name of the student (in capitals)")
        for role, phrases in self.field_phrases:
            if role in ("sno", "ignore", "row_subject", "row_exam", "file_percent", "file_grade", "file_result"):
                continue
            for p in phrases:
                if len(p) >= 4 and re.search(r"(^| )" + re.escape(p) + r"( |$)", n):
                    if role == "name" and ("father" in n or "mother" in n or "school" in n):
                        continue
                    return role
        return None

    def class_section(self, text):
        """'XI-A' -> ('XI','A'); 'XII Sci B' -> ('XII','B'); '11' -> ('XI',''); '6th C' -> ('VI','C')"""
        t = clean(text)
        n = norm(t)
        if not n:
            return None, ""
        m = re.match(r"^(?:class\s+|std\s+|grade\s+|standard\s+)?" + CLASS_TOKEN + r"(?:st|nd|rd|th)?(?![0-9a-z])\s*[-/ ]?\s*(.*)$", n) \
            or re.match(r"^(?:class\s+|std\s+|grade\s+|standard\s+)?" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\s*[-/ ]?\s*([a-h])$", n)
        if not m:
            return self.find_class(t), ""
        cls = to_class(m.group(1))
        rest = m.group(2).strip().split()
        sec = ""
        if rest:
            last = rest[-1]
            if len(last) <= 2 and last.isalpha():
                sec = last.upper()
            elif len(rest) == 1:
                sec = rest[0].upper()
        return cls, sec


# ---------------------------------------------------------------- helpers
def _profile(rows, col, cfg):
    vals = [clean(r[col]) for r in rows if col < len(r) and clean(r[col])]
    nums = [parse_number(v) for v in vals]
    numeric = [x for x in nums if x is not None]
    leaves = [v for v in vals if parse_number(v) is None and cfg.leave_code(v)]
    texty = [v for v in vals if parse_number(v) is None and not cfg.leave_code(v)]
    alpha_long = [v for v in texty if len(v) >= 3 and re.search(r"[A-Za-z]{2}", v)]
    return {
        "count": len(vals), "numeric": len(numeric), "leaves": len(leaves), "text": len(texty),
        "alpha_long": len(alpha_long),
        "max": max(numeric) if numeric else None, "min": min(numeric) if numeric else None,
        "sample": vals[:5],
        "all_int": all(x == x.to_integral_value() for x in numeric) if numeric else False,
        "digits": [len(v) for v in vals if v.isdigit()][:20],
    }


def _row_score(row, vocab):
    score = 0
    # distinct values only: a merged title copied across 20 cells counts once
    for c in dict.fromkeys(clean(x) for x in row):
        if not c:
            continue
        if parse_number(c) is not None:
            score -= 1
            continue
        if vocab.find_field(c) or vocab.find_subject(c) or vocab.find_exam(c) or vocab.find_component(c, c):
            score += 2
        elif len(c) <= 40:
            score += 0.2
    return score


def _distinct(row):
    return len({clean(c) for c in row if clean(c)})


# ---------------------------------------------------------------- main
def class_parts(cfg, cls):
    """The kinds of marks column a class can have: written, total, and the practical / internal parts its
    marks schemes use (none of the internal parts in XI-XII, no practical at all in a theory-only class)."""
    found = {"theory", "total"}
    for subj in cfg.class_subject_codes(cls):
        for exam in cfg.class_exams(cls):
            sc = cfg.scheme(cls, subj, exam)
            if sc and sc["second"]:
                found.add("practical")
                for key, _ in sc["second"]["parts"]:
                    found.update(p for p, real in PART_KEYS.items() if key in real)
    return found


def detect(sheet, file_name, cfg, vocab=None, default_cls=None, force_cls=None):
    """Propose a layout for one sheet. default_cls = the class the teacher picked before uploading, used
    when the sheet itself does not say its class; force_cls = the class the teacher said it is."""
    vocab = vocab or Vocab(cfg)
    rows = sheet.rows
    lay = {"sheet": sheet.name, "header_rows": [], "data_start": 0, "format": "wide",
           "exam": None, "exam_from": "", "cls": None, "cls_from": "", "section": "",
           "columns": [], "skip": False, "note": "", "max_row": None, "title": ""}
    if not rows or not any(any(clean(c) for c in r) for r in rows):
        lay["skip"] = True
        lay["note"] = "Empty sheet"
        return lay

    scan = rows[:25]
    scores = [_row_score(r, vocab) for r in scan]
    best = max(range(len(scan)), key=lambda i: (scores[i], -i))
    if scores[best] < 2:
        header = []
        data_start = 0
    else:
        header = [best]
        # rows just above that are column-group headings (Physics spanning Th/Pr, or exam names)
        r = best - 1
        while r >= 0 and len(header) < 3:
            if _distinct(rows[r]) >= 2 and scores[r] > 0:
                header.insert(0, r)
                r -= 1
            else:
                break
        # a row just below made of part names (Th / Pr, Written / Portfolio / Notebook ...) belongs to the headings
        r = best + 1
        while r < len(rows) and len(header) < 3:
            cells = [clean(x) for x in rows[r] if clean(x)]
            if cells and not any(parse_number(x) is not None for x in cells) and \
                    sum(1 for x in cells if vocab.find_component(x, x)) >= max(1, len(cells) * 0.6):
                header.append(r)
                r += 1
            else:
                break
        data_start = header[-1] + 1
    title_rows = rows[:header[0]] if header else []
    title_text = " ".join(clean(c) for r in title_rows for c in r if clean(c))
    lay["title"] = title_text[:200]

    width = max((len(r) for r in rows), default=0)
    # build one heading string per column (upper heading rows are filled to the right
    # across empty cells, because merged headings only fill their first cell in CSV files)
    filled = []
    for hi, r in enumerate(header):
        row = list(rows[r]) + [""] * (width - len(rows[r]))
        if hi < len(header) - 1:
            last = ""
            for c in range(width):
                if clean(row[c]):
                    last = row[c]
                else:
                    bottom = clean(rows[header[-1]][c]) if c < len(rows[header[-1]]) else ""
                    if (last and bottom and not vocab.find_field(bottom)
                            and (vocab.find_component(bottom, bottom) or vocab.find_subject(bottom))):
                        row[c] = last
                    else:
                        last = ""
        filled.append(row)
    headings = []
    for c in range(width):
        parts = []
        for row in filled:
            v = clean(row[c])
            if v and v not in parts:
                parts.append(v)
        headings.append(" ".join(parts))

    # sheet-level exam / class from sheet name, title rows, file name
    for src, text in (("sheet name", sheet.name), ("title", title_text), ("file name", file_name)):
        if not lay["exam"]:
            ex = vocab.find_exam(text)
            if ex:
                lay["exam"], lay["exam_from"] = ex, src
        if not lay["cls"]:
            # sheet names like "XI A" may be short; titles and file names must say
            # "Class 11"/"XI" so that dates like 12-08-2025 are not read as a class
            cl = vocab.find_class(text) if src == "sheet name" else _class_in_title(text, vocab)
            if cl:
                lay["cls"], lay["cls_from"] = cl, src
    if force_cls:
        lay["cls"], lay["cls_from"] = force_cls, "you"
    elif not lay["cls"] and default_cls:
        lay["cls"], lay["cls_from"] = default_cls, "picked"
    if not lay["section"]:
        # "XI-A", "6th / B" (a dash or slash is needed), or "Class 9 C"
        low = (clean(title_text) + " " + clean(sheet.name)).lower()
        m = re.search(r"\b" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\s*[-/]\s*([a-h])\b", low) \
            or re.search(r"\b(?:class|std|grade)\s*" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\s*[-/ ]?\s*([a-h])\b", low)
        cs = class_token_match(norm(sheet.name))
        if m and to_class(m.group(1)):
            lay["section"] = m.group(2).upper()
        elif cs and cs[1]:
            lay["section"] = cs[1]

    body = rows[data_start:]
    # a "maximum marks" row right under the headings
    if body:
        first = body[0]
        name_cells = [clean(x).lower() for x in first[:4]]
        nums = [x for x in first if parse_number(clean(x)) is not None]
        if (any(n in ("max", "max marks", "mm", "maximum marks", "m.m.", "maximum", "full marks", "fm") for n in name_cells)
                or (nums and not any(re.search(r"[A-Za-z]{3}", clean(x)) for x in first))):
            if nums and len(nums) >= 2 and len(body) > 1:
                lay["max_row"] = data_start
                data_start += 1
                body = rows[data_start:]
    lay["header_rows"] = header
    lay["data_start"] = data_start

    cols = []
    for c in range(width):
        h = headings[c]
        prof = _profile(body, c, cfg)
        col = {"col": c, "header": h, "role": "ignore", "subject": None, "component": None, "exam": None,
               "sure": True, "why": "", "sample": prof["sample"]}
        if prof["count"] == 0 and not h:
            col["why"] = "Empty column"
            cols.append(col)
            continue
        bottom = clean(rows[header[-1]][c]) if header and c < len(rows[header[-1]]) else ""
        field = vocab.find_field(h) if h else None
        subj = vocab.find_subject(h) if h else None
        comp = vocab.find_component(h, bottom) if h else None
        exam = vocab.find_exam(h) if h else None
        if field == "lang_slot" and subj and norm(h) not in LANG_PHRASES:
            field = None                      # "English Language and Literature" is English, not a language slot
        if field == "lang_slot":
            if (prof["numeric"] + prof["leaves"]) >= max(1, prof["count"] * 0.5) and prof["count"]:
                col.update(role="mark", subject=LANG_MARK, component=comp, exam=exam,
                           why="Marks of each student's own language (from the Language column of the student list)")
            else:
                col.update(role="lang_choice", why="Which language each student takes")
            cols.append(col)
            continue
        # "English Grade" / "Phy Gr" is a grade column, not marks
        if subj and norm(h).split()[-1:] in (["gr"], ["grd"], ["grade"]):
            col.update(role="file_grade", why="Grade written in the file (kept for reference, not used)")
        # a heading like "Physics" wins over the generic word "total"/"marks"
        elif subj and field in (None, "file_total", "file_percent", "file_grade", "file_result", "ignore", "row_subject",
                                "choice", "group", "class"):
            if field == "choice":
                col.update(role="choice", why="Subject choice column")
            elif field in ("file_percent",):
                col.update(role="file_percent", why="Percentage written in the file (worked out again, not read)")
            else:
                col.update(role="mark", subject=subj, component=comp, exam=exam)
        elif field:
            col["role"] = field
            col["why"] = {"file_percent": "Percentage written in the file (worked out again, not read)",
                          "file_grade": "Grade written in the file (worked out again, not read)",
                          "file_result": "Result written in the file (worked out again, not read)",
                          "file_total": "Total written in the file (only used to double-check)"}.get(field, "Recognised heading")
            if field == "row_subject" and prof["alpha_long"] < prof["count"] * 0.5 and prof["numeric"] > prof["count"] * 0.5:
                # "Sub" column full of numbers is probably a subject *code* column - still a subject column
                pass
        elif h and (prof["numeric"] + prof["leaves"]) >= max(1, prof["count"] * 0.6):
            fz = vocab.find_subject_fuzzy(h)
            if fz:
                col.update(role="mark", subject=fz, component=comp, exam=exam, sure=False,
                           why=f"Heading “{h}” looks like {cfg.subject_name(fz)} (spelling differs) - please confirm")
            elif comp and not subj:
                col.update(role="mark", component=comp, exam=exam)   # long format "Theory" column
            else:
                col.update(role="unknown", sure=False, why=f"Numbers under an unknown heading “{h}” - what is it?")
        elif not h:
            if prof["alpha_long"] >= prof["count"] * 0.6 and prof["count"]:
                col.update(role="unknown", sure=False, why="Column without a heading containing names/text")
            elif prof["numeric"]:
                col.update(role="unknown", sure=False, why="Column without a heading containing numbers")
            else:
                col.update(role="ignore", why="Column without a heading")
        else:
            col.update(role="ignore", why=f"Heading “{h}” is not used")
        cols.append(col)

    # long format: a 'subject' column with subject names in the rows
    has_row_subject = any(c["role"] == "row_subject" for c in cols)
    if has_row_subject:
        lay["format"] = "long"
        for c in cols:
            if c["role"] == "mark" and c["subject"] is None and not c["component"]:
                c["component"] = "theory"
            if c["role"] in ("file_total",) or norm(c["header"]) in LONG_MARK_WORDS:
                if not any(x["role"] == "mark" for x in cols):
                    c.update(role="mark", component="total" if c["role"] == "file_total" else "theory")
    else:
        for c in cols:
            if c["role"] == "mark" and c["subject"] is None:
                c.update(role="unknown", sure=False, why=f"“{c['header']}” has marks but no subject - which subject?")

    _settle_components(cols, lay, cfg, body)
    _check_required(cols, lay, cfg)
    lay["columns"] = cols
    return lay


def _class_in_title(text, vocab):
    n = norm(text)
    m = re.search(r"\b(?:class|std|grade|standard)\s*" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\b", n) \
        or re.search(r"\b(xii|xi|ix|viii|vii|vi|iv)\b", n) \
        or re.search(r"\b(12|11|10|[6-9])th\b", n)
    if m:
        return to_class(m.group(1))
    return None


def _settle_components(cols, lay, cfg, body):
    """Decide theory / practical / total for every mark column, and flag anything uncertain.
    Columns for parts of the internal assessment (portfolio, notebook, ...) are left as they are."""
    cls = lay.get("cls") or "XI"
    groups = {}
    for c in cols:
        if c["role"] == "mark" and c["subject"] and c["component"] not in PART_KEYS:
            groups.setdefault((c["subject"], c["exam"] or lay["exam"]), []).append(c)
    for (subj, exam), cs in groups.items():
        kind = cfg.exam_kind(exam) if exam in cfg.exams else None
        rep = subj if subj != LANG_MARK else ((cfg.languages_for(cls) or ["302"])[0])
        name = cfg.subject_name(subj) if subj != LANG_MARK else "Language"
        sc = cfg.scheme(cls, rep, exam) if kind else None
        second = sc["second"] if sc else None
        prac = cfg.has_practical(rep) if not kind else bool(second and not second["optional"])
        if not prac or kind == "pt":
            th_max = sc["theory"] if sc else None
            for c in cs:
                if c["component"] in (None, "theory"):
                    c["component"] = "theory"
                elif c["component"] == "practical":
                    if not second:
                        c["sure"] = False
                        c["why"] = (f"{name} has no practical in "
                                    f"{'periodic tests' if kind == 'pt' else 'this school'}, but this column says practical - please check")
                elif c["component"] == "total":
                    if not second:
                        c["component"] = "theory"
                        c["why"] = "Total of a theory-only subject = its marks"
            if second and len(cs) == 1 and cs[0]["component"] == "theory" and th_max is not None:
                prof = _profile(body, cs[0]["col"], cfg)
                if prof["max"] is not None and prof["max"] > th_max:
                    cs[0]["component"] = "total"
                    cs[0]["sure"] = False
                    cs[0]["why"] = (f"One column for {name} with marks above {th_max}: read as the total out of "
                                    f"{th_max + second['max']} ({cfg.part_label('theory').lower()} + {second['label'].lower()}) - please confirm")
            for comp in ("theory", "practical", "total"):
                same = [c for c in cs if c["component"] == comp]
                if len(same) > 1:
                    for c in same:
                        c["sure"] = False
                        c["why"] = f"More than one column for {name} - please choose which one to use"
            continue
        # practical subject in a big exam (or exam not known yet)
        unlabeled = [c for c in cs if c["component"] is None]
        labeled = {c["component"] for c in cs if c["component"]}
        if len(cs) == 2 and len(unlabeled) == 2:
            unlabeled[0]["component"], unlabeled[1]["component"] = "theory", "practical"
            for c in unlabeled:
                c["sure"] = False
                c["why"] = "Two columns for this subject without Th/Pr labels: first taken as theory, second as practical - please confirm"
        elif len(cs) == 2 and len(unlabeled) == 1:
            unlabeled[0]["component"] = "practical" if "theory" in labeled else "theory"
            unlabeled[0]["sure"] = False
            unlabeled[0]["why"] = f"Taken as {unlabeled[0]['component']} - please confirm"
        elif len(cs) == 1 and unlabeled:
            c = cs[0]
            prof = _profile(body, c["col"], cfg)
            th_max = cfg.components(cls, rep, exam)["theory"] if kind else None
            if kind and prof["max"] is not None and prof["max"] > th_max:
                c["component"] = "total"
                c["why"] = f"One column for {name} with marks above {th_max}: read as the total out of 100 (theory + practical)"
                c["sure"] = False
            else:
                c["component"] = "theory"
                c["sure"] = False
                c["why"] = (f"Only one column for {name}. Is it theory only (out of "
                            f"{th_max if th_max else '70'}) or the total (out of 100)? Please confirm")
        if sum(1 for c in cs if c["component"] == "theory") > 1 or sum(1 for c in cs if c["component"] == "practical") > 1:
            for c in cs:
                c["sure"] = False
                c["why"] = f"Several columns for {name} {c['component']} - please choose which to use"


def _check_required(cols, lay, cfg):
    roles = {c["role"] for c in cols}
    needs = []
    if not (roles & {"name", "roll", "adm_no", "board_roll"}):
        needs.append("No column with student names or roll numbers was found")
    if not any(c["role"] == "mark" for c in cols):
        needs.append("No marks columns were found")
    lay["needs_exam"] = (any(c["role"] == "mark" and not c["exam"] for c in cols)
                         and not lay["exam"] and "row_exam" not in roles)
    lay["needs_class"] = not lay["cls"] and not (roles & {"class", "class_section"})
    lay["problems"] = needs
    has_id = bool(roles & {"name", "roll", "adm_no", "board_roll"})
    has_marks = any(c["role"] == "mark" for c in cols)
    lay["kind"] = "marks" if has_marks else ("roster" if has_id else "unknown")
    if lay["kind"] == "roster":
        # a student list (names, parents, subjects) without marks is still useful
        lay["needs_exam"] = False
        lay["problems"] = []
        lay["note"] = "Student list (no marks) - used for names, parents' names, sections and subject choices"
    elif not has_marks:
        lay["skip"] = True
        lay["note"] = "; ".join(needs) + " - this sheet is skipped unless you map it."


def signature(sheet, lay):
    """Fingerprint of a layout (the headings), used to remember the teacher's choices."""
    hs = [norm(c["header"]) for c in lay["columns"]]
    return "|".join(hs) + "#" + str(len(lay["header_rows"]))
