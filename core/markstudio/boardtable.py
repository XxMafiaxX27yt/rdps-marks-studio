"""Board results typed or exported as a simple table (TXT, Excel, CSV or a PDF table), one row per student:

    Roll | Admn No | Student Name | Eng | Phy | Chem | Math | CS | Total | Perc% | Grd | Result

Used when the school has its board results in its own layout instead of CBSE's gazette. The result is a
gazette.Gazette, so everything on the Board page works the same. Nothing is guessed silently: a row that
cannot be read becomes an error in Checks, and the file's own Total / % are only used to double-check."""
import datetime
import re
from decimal import Decimal

from .gazette import Gazette, BoardStudent
from .model import Issue, Ref
from .textutil import clean, norm, parse_number
from .layout import CLASS_TOKEN, to_class

PASS_MARK = 33
_GRADE = re.compile(r"^(A1|A2|B1|B2|C1|C2|D1|D2|D|E|E1|E2)$")
_RESULT_WORDS = {"pass": "PASS", "passed": "PASS", "p": "PASS", "comp": "COMP", "comptt": "COMP", "compartment": "COMP",
                 "fail": "FAIL", "failed": "FAIL", "f": "FAIL", "essential repeat": "ESSENTIAL REPEAT", "er": "ESSENTIAL REPEAT",
                 "absent": "ABST", "abst": "ABST", "ab": "ABST", "rw": "RW", "rl": "RL"}
_LEAVE = {"ab", "abs", "absent", "ml", "na", "-", "--", "x", "xx", "xxx"}
GRADE_WORDS = {"grade", "grd", "gr", "overall grade", "final grade", "grades"}
RESULT_WORDS = {"result", "res", "status", "pass fail", "final result"}


def _field(text, vocab):
    """One heading -> ('subject', code) / ('subject_grade', code) / (role, None) / (None, None)."""
    n = norm(text)
    if not n:
        return None, None
    if n in GRADE_WORDS:
        return "grade", None
    if n in RESULT_WORDS:
        return "result", None
    words = n.split()
    if len(words) >= 2 and words[-1] in ("gr", "grd", "grade"):
        code = vocab.find_subject(" ".join(words[:-1]))
        if code:
            return "subject_grade", code
    f = vocab.find_field(text)
    if f in ("file_grade", "file_result"):
        return ("grade" if f == "file_grade" else "result"), None
    if f in ("sno", "roll", "adm_no", "board_roll", "name", "gender", "class", "section", "class_section",
             "file_total", "file_percent"):
        return f, None
    code = vocab.find_subject(text) or (vocab.find_subject_fuzzy(text) if len(n) > 3 else None)
    if code:
        return "subject", code
    if f == "ignore" and n in ("result", "results"):
        return "result", None
    return None, None


def _text_grid(text, vocab):
    """Fixed-width text -> (title lines, header fields, data rows as token lists with line numbers)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    head_at, fields = None, None
    for i, line in enumerate(lines[:60]):
        toks = line.split()
        if len(toks) < 3:
            continue
        fl = _merge_heading(toks, vocab)
        if any(r == "name" for r, _, _ in fl) and sum(1 for r, _, _ in fl if r == "subject") >= 2:
            head_at, fields = i, fl
            break
    if head_at is None:
        return None
    title = [clean(l) for l in lines[:head_at] if clean(l)]
    rows = []
    for i in range(head_at + 1, len(lines)):
        line = lines[i].strip()
        if not line or set(line) <= set("-=_* "):
            continue
        rows.append((i + 1, line))
    return title, fields, rows


def _merge_heading(toks, vocab):
    """['Roll','Admn','No','Student','Name','Eng',...] -> [(role, code, label)]: two-word headings first."""
    out, i = [], 0
    while i < len(toks):
        done = False
        for k in (3, 2):
            if i + k <= len(toks):
                lab = " ".join(toks[i:i + k])
                r, c = _field(lab, vocab)
                exact = norm(lab) in GRADE_WORDS | RESULT_WORDS or any(norm(lab) in ph for _, ph in vocab.field_phrases)                     or (r == "subject" and vocab.find_subject(lab) and not vocab.find_subject(toks[i]))
                if r and exact:
                    out.append((r, c, lab))
                    i += k
                    done = True
                    break
        if done:
            continue
        r, c = _field(toks[i], vocab)
        out.append((r, c, toks[i]))
        i += 1
    return out


def _split_text_row(line, fields):
    """Tokens of one data line -> one value per heading. The name is whatever is left between the columns
    before it and the columns after it (names have spaces, the other columns do not)."""
    toks = line.split()
    ni = next((k for k, f in enumerate(fields) if f[0] == "name"), None)
    if ni is None:
        return None
    before, after = ni, len(fields) - ni - 1
    if len(toks) < before + after + 1:
        # a missing value at the end (e.g. no result written) - try without the trailing text columns
        return None
    name = toks[before:len(toks) - after] if after else toks[before:]
    if any(re.fullmatch(r"[\d.]+", t) for t in name):
        return None
    vals = toks[:before] + [" ".join(name)] + (toks[len(toks) - after:] if after else [])
    return vals


def _grid_header(rows, vocab):
    for r, row in enumerate(rows[:30]):
        fl = [(*_field(v, vocab), clean(v)) for v in row]
        if any(f[0] == "name" for f in fl) and sum(1 for f in fl if f[0] == "subject") >= 2:
            return r, fl
    return None, None


def _find_class(texts, vocab):
    for t in texts:
        n = norm(t)
        m = re.search(r"\b(?:class|std|standard)\s+" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\b", n) or \
            re.search(r"(?:^| )(xii|xi|x|12th|10th)(?: |$)", n)
        if m:
            tok = m.group(1).replace("th", "")
            c = to_class(tok)
            if c in ("X", "XII"):
                return c
    return ""


def _find_year(texts):
    for t in texts:
        m = re.search(r"\b(20\d\d)\b", t)
        if m:
            return m.group(1)
    return str(datetime.date.today().year)


def looks_like_board(name, sheets):
    """Board results typed by the school - 'XII_Board_Dummy_Marks.txt', 'Class XII Board Examination ...'.
    Not a school file with a 'Board Roll No' column, not 'Pre Board' (a school exam), not a workbook with many sheets."""
    used = [sh for sh in sheets if any(any(clean(c) for c in r) for r in sh.rows[:50])]
    if len(used) != 1:
        return False
    texts = [name] + [" ".join(clean(c) for c in r) for r in used[0].rows[:4]]
    exam_words = r"\b(pre board|preboard|half yearly|halfyearly|yearly|annual|periodic|pt ?[1-4]|term ?[12]|unit test)\b"
    for t in texts:
        n = norm(t)
        if re.search(exam_words, n):
            return False
    for t in texts:
        n = norm(t)
        if re.search(r"(?<!pre )\bboard (exam|exams|examination|result|results|marks|dummy)\b", n) or \
                re.search(r"\b(aissce|aisse)\b", n) or re.search(r"\bcbse (result|results)\b", n):
            return True
    return False


def parse(name, sheets, cfg, vocab):
    """-> Gazette (kind 'table') or None when no heading row with names and subjects is found."""
    g = Gazette(file=name)
    g.kind = "table"
    title, fields, data = [], None, []
    sh0 = sheets[0] if sheets else None
    if sh0 is not None and getattr(sh0, "text", None):
        tg = _text_grid(sh0.text, vocab)
        if tg:
            title, fields, rows = tg
            sheet_name = sh0.name
            for lineno, line in rows:
                vals = _split_text_row(line, fields)
                data.append((lineno, vals, line))
    if fields is None:
        for sh in sheets:
            hr, fl = _grid_header(sh.rows, vocab)
            if hr is None:
                continue
            fields = [(r, c, lab) for r, c, lab in fl]
            title = [" ".join(clean(x) for x in row if clean(x)) for row in sh.rows[:hr]]
            title = [t for t in title if t]
            sheet_name = sh.name
            for r in range(hr + 1, len(sh.rows)):
                row = sh.rows[r]
                if not any(clean(x) for x in row):
                    continue
                vals = [clean(row[k]) if k < len(row) else "" for k in range(len(fields))]
                data.append((r + 1, vals, " ".join(clean(x) for x in row)))
            break
    if fields is None:
        return None
    g.title = title[0] if title else f"Board results ({name})"
    g.cls = _find_class(title + [name, sheet_name], vocab)
    codes = [c for r, c, _ in fields if r == "subject"]
    if not g.cls:
        senior = {"042", "043", "044", "054", "055", "030", "083", "048", "065", "028", "037", "049", "027", "029"}
        g.cls = "XII" if senior & set(codes) else "X"
        g.issues.append(Issue("info", "board_class_guess",
                              f"The file does not say the class; taken as Class {g.cls} from its subjects."))
    g.year = _find_year(title + [name])
    g.exam_type = "MAIN"
    g.lines_read = len(data)
    no_result_col = not any(r == "result" for r, _, _ in fields)
    for lineno, vals, line in data:
        ref = Ref(name, sheet_name, lineno)
        if vals is None:
            if re.match(r"^\s*(total|average|avg|note|pass|candidates|school)", line, re.I):
                g.issues.append(Issue("info", "board_row_skipped", f"Line {lineno} is not a student: “{line[:60]}”", ref))
            else:
                g.issues.append(Issue("error", "board_row_unread",
                                      f"Line {lineno} could not be split into the columns of the heading: “{line[:70]}”. "
                                      f"Please check it - this student is not counted.", ref))
            continue
        get = {}
        for (role, code, lab), v in zip(fields, vals):
            get.setdefault(role, []).append((code, v, lab))
        name_v = next((v for _, v, _ in get.get("name", []) if v), "")
        if not name_v:
            if any(v for v in vals):
                g.issues.append(Issue("info", "board_row_skipped", f"Row {lineno} has no student name - skipped.", ref))
            continue
        if norm(name_v) in ("total", "average", "class average", "max", "highest"):
            continue
        one = lambda role: next((v for _, v, _ in get.get(role, []) if v), "")
        adm = one("adm_no")
        brd = one("board_roll")
        roll = one("roll")
        s = BoardStudent(roll=brd or adm or roll or str(lineno), gender=(one("gender")[:1] or "").upper(),
                         name=clean(name_v).title() if clean(name_v).isupper() else clean(name_v), ref=ref)
        s.adm_no = _id(adm)
        s.board_roll = _id(brd)
        s.class_roll = _id(roll)
        cs = one("class_section") or one("class")
        sec = one("section")
        if cs:
            cc, ss = vocab.class_section(cs)
            sec = sec or ss
        s.section = (sec or "").upper()[:3]
        grades = {c: v.upper() for c, v, _ in get.get("subject_grade", []) if v}
        total = Decimal(0)
        n_num = 0
        for code, v, lab in get.get("subject", []):
            entry = {"code": code, "raw": v, "marks": None, "grade": grades.get(code, "") if _GRADE.match(grades.get(code, "")) else ""}
            if not v:
                continue                                      # subject not taken
            d = parse_number(v)
            if d is None:
                if norm(v) in _LEAVE:
                    g.issues.append(Issue("info", "gazette_no_number", f"{s.name}: {lab} shows “{v}” instead of marks.",
                                          ref, subject=code))
                else:
                    g.issues.append(Issue("error", "board_bad_mark", f"{s.name}: {lab} “{v}” is not a mark - not counted.",
                                          ref, subject=code))
                s.subjects.append(entry)
                continue
            if d < 0 or d > 100:
                g.issues.append(Issue("error", "gazette_over_max", f"{s.name}: {lab} shows {v} (marks are out of 100) - not counted.",
                                      ref, subject=code))
                s.subjects.append(entry)
                continue
            entry["marks"] = int(d) if d == d.to_integral_value() else d
            total += d
            n_num += 1
            s.subjects.append(entry)
        res = norm(one("result"))
        s.result = _RESULT_WORDS.get(res, res.upper()) if res else ""
        fails = [x["code"] for x in s.subjects if x["marks"] is not None and x["marks"] < PASS_MARK]
        if not s.result:
            s.result = "PASS" if not fails else "COMP"
        if s.result == "COMP":
            s.comp = fails
        ft = parse_number(one("file_total"))
        if ft is not None and n_num and ft != total:
            g.issues.append(Issue("warning", "file_total_mismatch",
                                  f"{s.name}: the file's total is {ft} but the marks add up to {total}. The marks are used.", ref))
        g.students.append(s)
    if no_result_col:
        g.issues.append(Issue("info", "board_result_worked_out",
                              f"No Result column - pass worked out as {PASS_MARK} or more in every subject."))
    if not any(x["grade"] for s in g.students for x in s.subjects):
        g.issues.append(Issue("info", "board_no_grades",
                              "The file has no CBSE grade for each subject, so mark bands (90+, 80-89, ...) are shown instead "
                              "of grades, and there is no Performance Index."))
    g.issues.append(Issue("info", "gazette_count_ok", f"Read {len(g.students)} students from the table."))
    g.totals = {"candidates": len(g.students), "pass": sum(1 for s in g.students if s.result == "PASS")}
    return g if g.students else None


def _id(v):
    d = parse_number(v) if v else None
    if d is not None and d == d.to_integral_value():
        return str(int(d))
    return clean(v).upper()
