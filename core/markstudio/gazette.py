"""Reads the CBSE result gazette (the fixed-width TXT file CBSE sends schools,
"SCHOOL / ROLL NO WISE GAZETTE").

Each student takes two lines (made-up example):
    99000001   F RIYA SAMPLE     301     041     042     043     048     A1 A1 A1    PASS
                                 081  B1 066  B2 072  B1 069  B2 088  A2
Line 1: roll number, sex, name, subject codes, 3 internal grades, result (+ compartment subject).
Line 2: marks and CBSE grade for each subject, in the same order.

Every line is accounted for: a line that looks like a student but cannot be read
becomes an error in the report - nothing is skipped silently."""
import re
from dataclasses import dataclass, field

from .model import Issue, Ref

_ROLL = re.compile(r"^\d{7,9}$")
_CODE = re.compile(r"^\d{3}$")
_GRADE = re.compile(r"^(A1|A2|B1|B2|C1|C2|D1|D2|D|E|E1|E2)$")
_INT_GRADE = re.compile(r"^[A-E][12]?$")
_RESULTS = ["ESSENTIAL REPEAT", "PASS", "COMP", "COMPTT", "FAIL", "ABST", "ABSENT", "RW", "RL", "XXXX", "ER", "UFM"]


@dataclass
class BoardStudent:
    roll: str
    gender: str
    name: str
    subjects: list = field(default_factory=list)   # [{'code','raw','marks','grade'}]
    internal: list = field(default_factory=list)   # internal grades GR1..GR3
    result: str = ""
    comp: list = field(default_factory=list)       # compartment subject codes
    ref: Ref = None
    flag: str = ""
    adm_no: str = ""        # only in the school's own board tables (boardtable.py)
    board_roll: str = ""
    class_roll: str = ""
    section: str = ""

    def to_dict(self):
        return {"roll": self.roll, "gender": self.gender, "name": self.name,
                "subjects": [dict(s, marks=s["marks"]) for s in self.subjects],
                "internal": self.internal, "result": self.result, "comp": self.comp, "adm_no": self.adm_no,
                "section": self.section,
                "ref": self.ref.to_dict() if self.ref else None}


@dataclass
class Gazette:
    file: str
    title: str = ""
    year: str = ""
    cls: str = ""          # 'XII' or 'X'
    exam_type: str = ""    # MAIN / COMPARTMENT ...
    region: str = ""
    school_code: str = ""
    school_name: str = ""
    date: str = ""
    students: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    lines_read: int = 0
    kind: str = "gazette"  # 'gazette' (CBSE's own file) or 'table' (the school's own board table)


def looks_like_gazette(text):
    t = text[:5000].upper()
    return ("GAZETTE" in t and ("C.B.S.E" in t or "CBSE" in t)) or \
           ("SENIOR SCHOOL CERTIFICATE" in t and "ROLL" in t) or \
           ("SECONDARY SCHOOL EXAMINATION" in t and "ROLL" in t)


def _header_line(u):
    return (u.startswith("DATE") or "GAZETTE" in u or u.startswith("ROLL") or u.startswith("NO ")
            or u.startswith("---") or "SUB CD" in u or "MKS GR" in u or u.startswith("SCHOOL")
            or u.startswith("TOTAL CANDIDATES") or "C.B.S.E" in u)


def parse(text, file="gazette.txt"):
    g = Gazette(file=file)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    pending = None   # student waiting for its marks line
    while i < n:
        raw = lines[i]
        line = raw.strip()
        u = line.upper()
        lineno = i + 1
        i += 1
        if not line:
            continue
        g.lines_read += 1

        # ---- page headers / meta
        if u.startswith("DATE") and ("C.B.S.E" in u or "CBSE" in u):
            m = re.search(r"DATE:?-?\s*([\d\-/\.]+)", u)
            if m and not g.date:
                g.date = m.group(1)
            m = re.search(r"(C\.B\.S\.E\..*?EXAMINATION\s*\(([A-Z ]+)\)\s*-?\s*(\d{4}))", u)
            if m and not g.title:
                g.title = re.sub(r"\s+", " ", m.group(1)).title().replace("C.B.S.E.", "C.B.S.E.")
                g.exam_type = m.group(2).strip()
                g.year = m.group(3)
            if not g.cls:
                g.cls = "XII" if "SENIOR SCHOOL" in u else ("X" if "SECONDARY SCHOOL" in u else "")
            m = re.search(r"REGION:?\s*([A-Z\-\s]+?)\s+PAGE", u)
            if m and not g.region:
                g.region = m.group(1).strip()
            continue
        if u.startswith("SCHOOL") and ":" in u:
            m = re.search(r"SCHOOL\s*:\s*-?\s*(\d{4,6})\s+(.*)$", line, re.I)
            if m and not g.school_code:
                g.school_code = m.group(1)
                g.school_name = re.sub(r"\s+", " ", m.group(2)).strip()
            continue
        if u.startswith("TOTAL CANDIDATES"):
            for key, pat in [("candidates", r"TOTAL CANDIDATES\s*:\s*(\d+)"), ("pass", r"TOTAL PASS\s*:\s*(\d+)"),
                             ("comp", r"TOTAL COMPTT\.?\s*:\s*(\d+)"), ("repeat", r"TOTAL ESSENTIAL REPEAT\s*:\s*(\d+)"),
                             ("absent", r"TOTAL ABSENT\s*:\s*(\d+)")]:
                m = re.search(pat, u)
                if m:
                    g.totals[key] = int(m.group(1))
            continue
        if _header_line(u):
            continue

        toks = line.split()
        # ---- a student line
        if _ROLL.match(toks[0]):
            if pending is not None:
                g.issues.append(Issue("error", "gazette_no_marks",
                                      f"Roll {pending.roll} ({pending.name}): the marks line is missing.", pending.ref))
                g.students.append(pending)
            pending = _student_line(toks, Ref(file, "", lineno), g)
            continue
        # ---- the marks line of the pending student
        if pending is not None and (re.match(r"^(\d{1,3}|AB|ABS|XXX|---)$", toks[0], re.I)):
            _marks_line(pending, toks, Ref(file, "", lineno), g)
            g.students.append(pending)
            pending = None
            continue
        g.issues.append(Issue("warning", "gazette_unknown_line",
                              f"Line {lineno} was not understood and was not used: “{line[:80]}”", Ref(file, "", lineno)))
    if pending is not None:
        g.issues.append(Issue("error", "gazette_no_marks",
                              f"Roll {pending.roll} ({pending.name}): the marks line is missing.", pending.ref))
        g.students.append(pending)
    _check_totals(g)
    return g


def _student_line(toks, ref, g):
    roll = toks[0]
    j = 1
    flag, gender = "", ""
    # the single letter after the roll number is the sex (M/F/T); a second single
    # letter is kept as the first initial of the name (e.g. "F M SHARMA")
    if j < len(toks) and len(toks[j]) == 1 and toks[j].upper() in "MFT":
        gender = toks[j].upper()
        j += 1
    name_parts = []
    while j < len(toks) and not _CODE.match(toks[j]):
        name_parts.append(toks[j])
        j += 1
    codes = []
    while j < len(toks) and _CODE.match(toks[j]):
        codes.append(toks[j])
        j += 1
    internal = []
    while j < len(toks) and _INT_GRADE.match(toks[j]) and len(internal) < 3:
        internal.append(toks[j])
        j += 1
    rest = " ".join(toks[j:]).upper()
    result, comp = "", []
    for r in _RESULTS:
        if rest.startswith(r):
            result = r
            comp = [t for t in rest[len(r):].split() if _CODE.match(t)]
            break
    if not result and rest:
        result = rest.split()[0]
    s = BoardStudent(roll=roll, gender=gender, name=" ".join(name_parts).title(),
                     subjects=[{"code": c, "raw": "", "marks": None, "grade": ""} for c in codes],
                     internal=internal, result=result, comp=comp, ref=ref, flag=flag)
    if not name_parts:
        g.issues.append(Issue("error", "gazette_no_name", f"Roll {roll}: no name found.", ref))
    if not codes:
        g.issues.append(Issue("error", "gazette_no_subjects", f"Roll {roll} ({s.name}): no subject codes found.", ref))
    if not result:
        g.issues.append(Issue("warning", "gazette_no_result", f"Roll {roll} ({s.name}): result (PASS/COMP) not found.", ref))
    return s


def _marks_line(s, toks, ref, g):
    pairs = []
    k = 0
    while k < len(toks):
        mark = toks[k]
        grade = toks[k + 1] if k + 1 < len(toks) and _GRADE.match(toks[k + 1].upper()) else ""
        pairs.append((mark, grade.upper()))
        k += 2 if grade else 1
    if len(pairs) != len(s.subjects):
        g.issues.append(Issue("error", "gazette_marks_count",
                              f"Roll {s.roll} ({s.name}): {len(s.subjects)} subjects but {len(pairs)} marks on the next line. "
                              f"Marks were matched in order; please check this student.", ref))
    for idx, sub in enumerate(s.subjects):
        if idx >= len(pairs):
            break
        mark, grade = pairs[idx]
        sub["raw"] = mark
        sub["grade"] = grade
        if mark.isdigit():
            v = int(mark)
            sub["marks"] = v
            if v > 100:
                g.issues.append(Issue("error", "gazette_over_max",
                                      f"Roll {s.roll} ({s.name}): subject {sub['code']} shows {v} marks (more than 100).",
                                      ref, subject=sub["code"]))
                sub["marks"] = None
        else:
            g.issues.append(Issue("info", "gazette_no_number",
                                  f"Roll {s.roll} ({s.name}): subject {sub['code']} has “{mark}” instead of marks.",
                                  ref, subject=sub["code"]))


def _check_totals(g):
    n = len(g.students)
    rolls = {}
    for s in g.students:
        rolls.setdefault(s.roll, []).append(s)
    for roll, lst in rolls.items():
        if len(lst) > 1:
            g.issues.append(Issue("error", "gazette_duplicate_roll",
                                  f"Roll {roll} appears {len(lst)} times.", lst[1].ref))
    t = g.totals
    if "candidates" in t:
        if t["candidates"] == n:
            g.issues.append(Issue("info", "gazette_count_ok",
                                  f"All {n} candidates read (matches “TOTAL CANDIDATES : {t['candidates']}”)."))
        else:
            g.issues.append(Issue("error", "gazette_count_mismatch",
                                  f"The file says {t['candidates']} candidates but {n} were read. Please check the file."))
    else:
        g.issues.append(Issue("warning", "gazette_no_totals",
                              f"{n} candidates read. The TOTAL CANDIDATES line was not found, so the count could not be double-checked."))
    if "pass" in t:
        p = sum(1 for s in g.students if s.result == "PASS")
        if p != t["pass"]:
            g.issues.append(Issue("error", "gazette_pass_mismatch", f"The file says {t['pass']} passed but {p} PASS results were read."))
    if "comp" in t:
        c = sum(1 for s in g.students if s.result in ("COMP", "COMPTT"))
        if c != t["comp"]:
            g.issues.append(Issue("error", "gazette_comp_mismatch", f"The file says {t['comp']} compartments but {c} were read."))
