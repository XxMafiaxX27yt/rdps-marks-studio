"""Class lists: which class and section each student is in (a roll-number list per section, or one list for
the whole school with Class / Section columns). Read from Excel, CSV, TXT or a PDF list.

They are used to
* put each board-result student in a section (matched by admission no, board roll no, or name), so every
  teacher is judged only on their own sections, and
* fill in the section of school-exam students whose files have no section column."""
import re

from .layout import detect, CLASS_TOKEN, to_class
from .textutil import clean, norm, norm_name, parse_number, similar


def find_class_section(texts, vocab):
    """'Class & Sec: XI A (2026-27)' / 'XII-B Roll List' / 'XI_A_Roll_Number_List.xlsx' -> ('XI', 'A')."""
    cls, sec = "", ""
    for t in texts:
        n = norm(t)
        if not n:
            continue
        m = re.search(r"\b(?:class|std|standard|cls)\b(?: and| sec| section| div)*\s+" + CLASS_TOKEN +
                      r"(?:st|nd|rd|th)?(?:\s+(?:sec|section|div)?\s*([a-h]))?\b", n)
        if not m:
            m = re.search(r"(?:^| )(xii|xi|x|ix|viii|vii|vi|iv|12th|11th|10th|9th|8th|7th|6th|12|11|10)(?:\s+(?:sec|section)?\s*([a-h]))?(?= |$)", n)
        if m:
            c = to_class(re.sub(r"(st|nd|rd|th)$", "", m.group(1)))
            if c and not cls:
                cls = c
            if m.group(2) and not sec and (not cls or c == cls):
                sec = m.group(2).upper()
        if cls and sec:
            break
    return cls, sec


def _id(v):
    d = parse_number(v) if v else None
    if d is not None and d == d.to_integral_value():
        return str(int(d))
    return clean(v).upper()


def read(file_name, sheets, cfg, vocab):
    """-> list of {'file', 'sheet', 'cls', 'section', 'students': [{name, adm_no, roll, board_roll, cls, section}],
    'needs': ''|'class'|'section'}. Sheets without a name column are skipped."""
    out = []
    for sh in sheets:
        if not sh.rows:
            continue
        lay = detect(sh, file_name, cfg, vocab)
        cols = {}
        for c in lay["columns"]:
            cols.setdefault(c["role"], c["col"])
        if "name" not in cols:
            continue
        title = [" ".join(clean(x) for x in r if clean(x)) for r in sh.rows[:lay["data_start"]]]
        cls, sec = find_class_section([t for t in title if t] + [sh.name, re.sub(r"[_\-]+", " ", file_name)], vocab)
        cls = cls or lay.get("cls") or ""
        sec = sec or lay.get("section") or ""
        studs = []
        for r in range(lay["data_start"], len(sh.rows)):
            row = sh.rows[r]
            get = lambda role: clean(row[cols[role]]) if role in cols and cols[role] < len(row) else ""
            name = get("name")
            if not name or norm(name) in ("total", "name", "student name"):
                continue
            if re.search(r"\d", name):
                continue                                          # page footers ("Page 1 of 2"), totals
            ids = [get(k) for k in ("adm_no", "roll", "board_roll", "sno")]
            if studs and not any(ids) and any(k in cols for k in ("adm_no", "roll", "board_roll", "sno")) and                     not any(clean(x) for k, x in enumerate(row) if k != cols["name"]):
                studs[-1]["name"] = clean(studs[-1]["name"] + " " + name)     # a long name wrapped onto the next line
                continue
            c2, s2 = cls, sec
            for role in ("class_section", "class"):
                if get(role):
                    cc, ss = vocab.class_section(get(role))
                    c2, s2 = cc or c2, ss or s2
            if get("section"):
                s2 = get("section").upper()
            studs.append({"name": name, "adm_no": _id(get("adm_no")), "roll": _id(get("roll")),
                          "board_roll": _id(get("board_roll")), "cls": c2 or "", "section": (s2 or "").upper()[:3]})
        if not studs:
            continue
        needs = "class" if any(not s["cls"] for s in studs) else ("section" if any(not s["section"] for s in studs) else "")
        out.append({"file": file_name, "sheet": sh.name, "cls": cls, "section": sec, "students": studs, "needs": needs})
    return out


def set_class(cl, cls, section):
    """The teacher says which class / section a list is (only fills students without their own)."""
    old_cls, old_sec = cl["cls"], cl["section"]
    cl["cls"], cl["section"] = cls or "", (section or "").upper()
    for s in cl["students"]:
        if not s["cls"] or s["cls"] == old_cls:
            s["cls"] = cl["cls"]
        if not s["section"] or s["section"] == old_sec:
            s["section"] = cl["section"]
    cl["needs"] = "class" if any(not s["cls"] for s in cl["students"]) else \
        ("section" if any(not s["section"] for s in cl["students"]) else "")


class Placer:
    """Finds a student's class + section in the class lists (and the school's own students) by
    admission no -> board roll no -> exact name -> a close spelling of the name."""

    def __init__(self, class_lists, ds=None):
        self.entries = []
        for cl in class_lists or []:
            for s in cl["students"]:
                if s["cls"] or s["section"]:
                    self.entries.append(dict(s, src=cl["file"]))
        if ds is not None:
            for st in ds.students.values():
                if st.section:
                    self.entries.append({"name": st.name, "adm_no": (st.adm_no or "").upper(), "roll": st.roll,
                                         "board_roll": st.board_roll, "cls": st.cls, "section": st.section,
                                         "src": "school marks"})
        self.by_adm, self.by_brd, self.by_name = {}, {}, {}
        for e in self.entries:
            if e["adm_no"]:
                self.by_adm.setdefault(e["adm_no"], []).append(e)
            if e["board_roll"]:
                self.by_brd.setdefault(e["board_roll"], []).append(e)
            self.by_name.setdefault(norm_name(e["name"]), []).append(e)

    @staticmethod
    def _one(cands, cls):
        """Several entries can be the same student (class list + school marks) - fine if they agree."""
        if not cands:
            return None
        same = [c for c in cands if c["cls"] == cls] or cands
        places = {(c["cls"], c["section"]) for c in same}
        return same[0] if len(places) == 1 else "many"

    def place(self, name, cls, adm_no="", board_roll=""):
        """-> (entry or None, how). how: 'admission no' / 'board roll no' / 'name' / 'close name' / 'same name twice' / ''."""
        if adm_no:
            e = self._one(self.by_adm.get(adm_no.upper()), cls)
            if e and e != "many":
                return e, "admission no"
        if board_roll:
            e = self._one(self.by_brd.get(board_roll), cls)
            if e and e != "many":
                return e, "board roll no"
        n = norm_name(name)
        e = self._one(self.by_name.get(n), cls)
        if e == "many":
            return None, "same name twice"
        if e:
            return e, "name"
        # a close spelling: every word matches (typos allowed), or one list leaves out a surname
        words = n.split()
        best = []
        for key, es in self.by_name.items():
            kw = key.split()
            if not kw:
                continue
            if len(kw) == len(words) and all(similar(a, b) for a, b in zip(words, kw)):
                best.append(es)
            elif min(len(kw), len(words)) >= 1 and (kw[:len(words)] == words or words[:len(kw)] == kw) and \
                    len(kw[0]) >= 3 and abs(len(kw) - len(words)) == 1:
                best.append(es)
        flat = [x for es in best for x in es]
        e = self._one(flat, cls)
        if e and e != "many":
            return e, "close name"
        return None, "same name twice" if e == "many" else ""
