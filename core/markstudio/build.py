"""Turns uploaded files + the confirmed column mapping into the clean data set:
students (one each, even if they appear in several files) and mark records.

Rules that matter for accuracy:
* the uploaded file is never changed - a teacher's correction is stored separately
  and the original value is kept and shown in the Validation Report;
* blank, zero and leave codes (AB/ML/...) are always kept apart;
* anything doubtful becomes an Issue, it is never guessed silently."""
import re
from decimal import Decimal

from .model import Student, Mark, Issue, Ref
from .textutil import clean, norm, norm_name, parse_number, similar, fmt_mark
from .layout import Vocab, detect, signature, LANG_MARK, PART_KEYS
from .groups import infer_group, combo_of
from .teachers import TEACHER_SHEETS, read_sheet as read_teachers
from . import readers, gazette, boardtable, classlist

INFO_SHEETS = {"how to fill", "instructions", "instruction", "read me", "readme", "lists", "help", "notes",
               "guide", "legend", "info"}
SUMMARY_NAMES = {"total", "average", "avg", "class average", "max", "maximum", "highest", "lowest", "mean",
                 "grand total", "maximum marks", "max marks", "mm", "full marks", "out of", "minimum"}


class Source:
    def __init__(self, sid, name, sheets, kind="table", note=""):
        self.id = sid
        self.name = name
        self.sheets = sheets
        self.kind = kind
        self.note = note


class Project:
    """Everything the teacher has uploaded and decided in this session."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.vocab = Vocab(cfg)
        self.sources = []
        self.layouts = {}            # (source_id, sheet_name) -> layout dict
        self.corrections = {}        # "file|sheet|row|col" -> new text
        self.remembered = {}         # layout signature -> saved column choices
        self.gazettes = []           # parsed board gazettes (kept separate)
        self.file_teachers = []      # teachers read from 'Teachers' sheets
        self.class_lists = []        # which class + section each student is in (classlist.py)
        self._n = 0
        self._cl = 0

    # ------------------------------------------------------------ files
    def add_file(self, name, data):
        """Read a file. A CBSE gazette (or the school's own board-results table) goes to the Board section,
        anything else is a marks table."""
        sheets = readers.read_file(name, data)
        if len(sheets) == 1 and sheets[0].text and gazette.looks_like_gazette(sheets[0].text):
            g = gazette.parse(sheets[0].text, name)
            g.raw_text = sheets[0].text
            self._add_gazette(g)
            return {"kind": "gazette", "name": name, "students": len(g.students), "year": g.year}
        if boardtable.looks_like_board(name, sheets):
            info = self._board_table(name, sheets)
            if info:
                info["moved"] = True
                return info
        return self._add_table(name, sheets)

    # ------------------------------------------------------------ board results (Board page)
    def _add_gazette(self, g):
        """The same board results added twice (same class, year, roll numbers and names) replace the first copy."""
        key = lambda x: (x.cls, x.year, sorted(f"{st.roll}|{norm_name(st.name)}" for st in x.students))
        self.gazettes = [o for o in self.gazettes if key(o) != key(g)]
        self.gazettes.append(g)

    def add_board_file(self, name, data):
        sheets = readers.read_file(name, data)
        if len(sheets) == 1 and getattr(sheets[0], "text", None) and gazette.looks_like_gazette(sheets[0].text):
            g = gazette.parse(sheets[0].text, name)
            g.raw_text = sheets[0].text
            self._add_gazette(g)
            return {"kind": "gazette", "name": name, "students": len(g.students), "year": g.year}
        info = self._board_table(name, sheets)
        if not info:
            raise ValueError(f"{name}: no row of headings with the students' names and subjects (like “Name | English | "
                             f"Physics | ...”) was found, so it could not be read as board results.")
        return info

    def add_board_pages(self, name, pages):
        sheets, text = readers.read_pages(name, pages)
        if gazette.looks_like_gazette(text):
            g = gazette.parse(text, name)
            g.raw_text = text
            self._add_gazette(g)
            return {"kind": "gazette", "name": name, "students": len(g.students), "year": g.year}
        info = self._board_table(name, sheets)
        if not info:
            raise ValueError(f"{name}: no row of headings with the students' names and subjects was found.")
        return info

    def _board_table(self, name, sheets):
        g = boardtable.parse(name, sheets, self.cfg, self.vocab)
        if g is None:
            return None
        txt = getattr(sheets[0], "text", None) if sheets else None
        g.raw_text = txt or "\n".join("\t".join(r) for sh in sheets for r in sh.rows)
        self._add_gazette(g)
        return {"kind": "gazette", "table": True, "name": name, "students": len(g.students), "year": g.year, "cls": g.cls}

    # ------------------------------------------------------------ any file: work out what it is
    KINDS = ("school", "board", "board_XII", "board_X", "class_list")

    def add_any(self, name, data, prefer="", hint="", cls=""):
        """Any file, from any page. It is sorted into: board results (Class XII or X - CBSE's own file or the
        school's own list), a class list (names + sections, no marks) or school exam marks.
        prefer = the teacher's answer when the tool asked; hint = the page the file was dropped on (used only
        when the file itself could be either); cls = the class picked on the School page before uploading."""
        sheets = readers.read_file(name, data)
        text = sheets[0].text if len(sheets) == 1 and getattr(sheets[0], "text", None) else ""
        return self._add_any(name, sheets, text, prefer, hint, cls=cls)

    def add_any_pages(self, name, pages, prefer="", hint="", cls=""):
        sheets, text = readers.read_pages(name, pages)
        info = self._add_any(name, sheets, text, prefer, hint, ocr=any(getattr(s, "ocr", False) for s in sheets),
                             cls=cls)
        return info

    def _add_any(self, name, sheets, text, prefer, hint, ocr=False, cls=""):
        if text and gazette.looks_like_gazette(text):
            g = gazette.parse(text, name)
            g.raw_text = text
            self._add_gazette(g)
            return {"kind": "board", "what": "cbse", "name": name, "students": len(g.students), "year": g.year,
                    "cls": g.cls}
        kind = prefer or self.classify(name, sheets)
        if kind == "ask":
            kind = hint if hint in self.KINDS else "ask"
        if kind == "ask":
            return {"kind": "ask", "name": name,
                    "why": "This file has students and marks of each subject, but it does not say whether they are school "
                           "exam marks or board results."}
        if kind.startswith("board"):
            info = self._board_table(name, sheets)
            if not info:
                raise ValueError(f"{name}: no row of headings with the students' names and subjects was found, so it "
                                 f"could not be read as board results.")
            if kind in ("board_XII", "board_X"):
                g = self.gazettes[-1]
                g.cls = kind.split("_")[1]
                g.issues = [i for i in g.issues if i.code != "board_class_guess"]
                info["cls"] = g.cls
            info["kind"], info["what"] = "board", "table"
            return info
        if kind == "class_list":
            found = self._class_lists(name, sheets)
            for c in found:
                if cls and not c["cls"]:
                    classlist.set_class(c, cls, c["section"])
            return {"kind": "class_list", "name": name, "lists": [{"cls": c["cls"], "section": c["section"],
                    "count": len(c["students"]), "needs": c["needs"]} for c in found]}
        info = self._add_table(name, sheets, ocr=ocr, cls=cls)
        info["kind"] = "school"
        return info

    def classify(self, name, sheets):
        """-> 'board' / 'class_list' / 'school' / 'ask' (could be school marks or board results)."""
        if boardtable.looks_like_board(name, sheets):
            return "board"
        lays = []
        for sh in sheets:
            if norm(sh.name) in TEACHER_SHEETS or norm(sh.name) in INFO_SHEETS or not sh.rows:
                continue
            lays.append((sh, detect(sh, name, self.cfg, self.vocab)))
        if not lays:
            return "school"
        marks = [(sh, lay) for sh, lay in lays if any(c["role"] == "mark" for c in lay["columns"])]
        named = [(sh, lay) for sh, lay in lays if any(c["role"] == "name" for c in lay["columns"])]
        if not marks:
            if not named:
                return "school"
            rich = {"gender", "lang_choice", "lang_slot", "choice", "group", "father", "mother"}
            if any(c["role"] in rich for _, lay in named for c in lay["columns"]):
                return "school"            # a full student list (gender, language, subjects) belongs with the marks
            return "class_list"
        # school signs: an exam named anywhere, several marks sheets, internal / practical parts
        if len(marks) > 1 or any(lay.get("exam") or any(c.get("exam") for c in lay["columns"]) for _, lay in marks):
            return "school"
        if any(c["role"] == "mark" and c.get("component") not in (None, "theory", "total")
               for _, lay in marks for c in lay["columns"]):
            return "school"
        if boardtable.parse(name, sheets, self.cfg, self.vocab) is None:
            return "school"
        return "ask"

    # ------------------------------------------------------------ class lists
    def add_class_list(self, name, data):
        return self._class_lists(name, readers.read_file(name, data))

    def add_class_list_pages(self, name, pages):
        sheets, _ = readers.read_pages(name, pages)
        return self._class_lists(name, sheets)

    def _class_lists(self, name, sheets):
        # a Teachers sheet in the same file (the Board analysis template) is the teachers, not more students
        teachers = []
        for sh in sheets:
            if norm(sh.name) in TEACHER_SHEETS:
                teachers += read_teachers(sh.rows, self.cfg, self.vocab, name, sh.name)
        sheets = [sh for sh in sheets if norm(sh.name) not in TEACHER_SHEETS and norm(sh.name) not in INFO_SHEETS]
        have = {(t["name"], t["subject"]) for t in self.file_teachers}
        self.file_teachers += [dict(t, source=name) for t in teachers if (t["name"], t["subject"]) not in have]
        found = classlist.read(name, sheets, self.cfg, self.vocab)
        if not found:
            if teachers:
                return []
            raise ValueError(f"{name}: no column of student names was found, so it could not be read as a class list.")
        for cl in found:
            self._cl += 1
            cl["id"] = f"L{self._cl}"
            self.class_lists.append(cl)
        return found

    def add_pages(self, name, pages):
        sheets, text = readers.read_pages(name, pages)
        if gazette.looks_like_gazette(text):
            g = gazette.parse(text, name)
            g.raw_text = text
            self._add_gazette(g)
            return {"kind": "gazette", "name": name, "students": len(g.students), "year": g.year}
        return self._add_table(name, sheets, ocr=any(getattr(s, "ocr", False) for s in sheets))

    def _add_table(self, name, sheets, ocr=False, cls=""):
        self._n += 1
        src = Source(f"F{self._n}", name, sheets, "scan" if ocr else "table")
        self.sources.append(src)
        for sh in sheets:
            if norm(sh.name) in TEACHER_SHEETS:
                found = read_teachers(sh.rows, self.cfg, self.vocab, name, sh.name)
                for t in found:
                    t["source_id"] = src.id
                self.file_teachers += found
                lay = {"sheet": sh.name, "skip": True, "note": f"Teacher list - {len(found)} teachers read (see Teachers)",
                       "columns": [], "header_rows": [], "data_start": 0, "format": "wide", "exam": None, "cls": None,
                       "section": "", "kind": "info", "signature": "", "needs_exam": False, "needs_class": False,
                       "problems": [], "title": "", "exam_from": "", "cls_from": "", "max_row": None}
                self.layouts[(src.id, sh.name)] = lay
                continue
            if norm(sh.name) in INFO_SHEETS:
                lay = {"sheet": sh.name, "skip": True, "note": "Instructions sheet - not read", "columns": [],
                       "header_rows": [], "data_start": 0, "format": "wide", "exam": None, "cls": None,
                       "section": "", "kind": "info", "signature": "", "needs_exam": False, "needs_class": False,
                       "problems": [], "title": "", "exam_from": "", "cls_from": "", "max_row": None}
                self.layouts[(src.id, sh.name)] = lay
                continue
            lay = detect(sh, name, self.cfg, self.vocab, default_cls=cls or None)
            sig = signature(sh, lay)
            lay["signature"] = sig
            if sig in self.remembered:
                own = (lay["cls"], lay["cls_from"])
                self._apply_saved(lay, self.remembered[sig])
                if own[1] == "picked":
                    lay["cls"], lay["cls_from"] = own      # the class picked for this upload beats last time's
            if ocr:
                for c in lay["columns"]:
                    if c["role"] not in ("ignore",):
                        c["sure"] = False
                        c["why"] = (c["why"] + " " if c["why"] else "") + "(read from a scan - please check)"
            if cls:
                self._check_picked(sh, lay, cls)
            self.layouts[(src.id, sh.name)] = lay
        return {"kind": "table", "id": src.id, "name": name, "sheets": [s.name for s in sheets],
                "clashes": [dict(self.layouts[(src.id, s.name)]["clash"], sheet=s.name) for s in sheets
                            if self.layouts[(src.id, s.name)].get("clash")]}

    def _check_picked(self, sh, lay, cls):
        """The teacher picked the class before uploading. A sheet that looks like another class - its name or
        title says so, its Class column has other classes, or it has subjects that class does not have - gets
        a question on the check screen instead of being read as the picked class."""
        lay["picked"] = cls
        lay.pop("clash", None)
        if lay["skip"] or lay.get("kind") == "info":
            return
        label = self.cfg.class_label
        clash = None
        if lay["cls"] and lay["cls"] != cls and lay.get("cls_from") != "picked":
            clash = {"found": lay["cls"], "source": "title",
                     "why": f"the {lay.get('cls_from') or 'file'} says {label(lay['cls'])}"}
        if not clash:
            seen = []
            for c in lay["columns"]:
                if c["role"] in ("class", "class_section"):
                    for row in sh.rows[lay["data_start"]:]:
                        cc = self.vocab.class_section(row[c["col"]] if c["col"] < len(row) else "")[0]
                        if cc and cc not in seen:
                            seen.append(cc)
            if seen and cls not in seen:
                clash = {"found": seen[0] if len(seen) == 1 else None, "source": "column", "seen": seen,
                         "why": f"its class column says {', '.join(label(x) for x in seen)}"}
        if not clash:
            have = set(self.cfg.class_subject_codes(cls))
            subs, odd = set(), []
            for c in lay["columns"]:
                s = self.cfg.resolve_subject(cls, c["subject"]) if c["role"] == "mark" and c["subject"] else None
                if s and s != LANG_MARK:
                    subs.add(s)
                    if s not in have and s not in odd:
                        odd.append(s)
            if odd:
                names = [self.cfg.subject_name(s) for s in odd]
                fits = [k for k in self.cfg.classes if k != cls and subs <= set(self.cfg.class_subject_codes(k))]
                clash = {"found": fits[0] if len(fits) == 1 else None, "source": "subjects", "fits": fits[:3],
                         "why": f"{_words(names)} {'is not a' if len(odd) == 1 else 'are not'} {label(cls)} "
                                f"subject{'' if len(odd) == 1 else 's'}"}
        if clash:
            clash["picked"] = cls
            lay["clash"] = clash

    # ------------------------------------------------------------ marks typed on the website
    TYPED_ROLES = (("roll", "Roll No"), ("adm_no", "Admission No"), ("name", "Name"), ("section", "Section"))

    def add_typed(self, d):
        """Marks typed on the Type marks screen: one class and section, one exam, one subject (the parts the
        teacher typed: written, practical, portfolio ...). Kept like an uploaded sheet whose columns are all known.
        Students with nothing typed are left out (e.g. not taking this language); typing the same class, section,
        exam and subject again replaces the earlier copy."""
        cfg = self.cfg
        cls, sec, exam, subj = d["cls"], (d.get("section") or "").strip().upper()[:3], d["exam"], d["subject"]
        if cls not in cfg.classes or exam not in cfg.exams or subj not in cfg.subjects:
            raise ValueError("Pick the class, exam and subject first.")
        parts = [p for p in d["parts"] if p]
        rows = [dict(r, section=clean(r.get("section", "")).upper() or sec) for r in d["rows"]
                if any(clean(r.get("values", {}).get(p, "")) for p in parts)]
        if not rows:
            raise ValueError("No marks were typed.")
        if any(not clean(r.get("name", "")) and not clean(r.get("roll", "")) and not clean(r.get("adm_no", "")) for r in rows):
            raise ValueError("Every student with marks needs a name or a roll number.")
        key = (cls, sec, exam, subj)
        for old in [s for s in self.sources if getattr(s, "typed", None) and s.typed["key"] == key]:
            self.remove_source(old.id)
        heads = [h for _, h in self.TYPED_ROLES] + [f"{cfg.subject_name(subj)} {self.typed_part_label(p)}" for p in parts]
        table = [heads] + [[clean(r.get(k, "")) for k, _ in self.TYPED_ROLES] + [clean(r["values"].get(p, "")) for p in parts]
                           for r in rows]
        sheet = readers.Sheet(cfg.exam_name(exam), table)
        self._n += 1
        title = f"{cfg.class_label(cls)}{'-' + sec if sec else ''} · {cfg.exam_name(exam)} · {cfg.subject_name(subj)}"
        src = Source(f"F{self._n}", f"Typed: {title}", [sheet], "typed")
        src.typed = {"key": key, "cls": cls, "section": sec, "exam": exam, "subject": subj, "parts": parts,
                     "rows": [{k: clean(r.get(k, "")) for k, _ in self.TYPED_ROLES} | {"values": dict(r["values"])}
                              for r in d["rows"]], "teacher": clean(d.get("teacher", ""))}
        self.sources.append(src)
        cols = [{"col": i, "header": h, "role": role, "subject": None, "component": None, "exam": None, "sure": True,
                 "why": "Typed on the website", "sample": []} for i, (role, h) in enumerate(self.TYPED_ROLES)]
        for i, p in enumerate(parts):
            cols.append({"col": len(self.TYPED_ROLES) + i, "header": heads[len(self.TYPED_ROLES) + i], "role": "mark",
                         "subject": subj, "component": p, "exam": exam, "sure": True, "why": "Typed on the website",
                         "sample": []})
        self.layouts[(src.id, sheet.name)] = {
            "sheet": sheet.name, "header_rows": [0], "data_start": 1, "format": "wide", "exam": exam, "exam_from": "typed",
            "cls": cls, "cls_from": "typed", "section": sec, "columns": cols, "skip": False, "note": "", "max_row": None,
            "title": title, "kind": "marks", "signature": "", "needs_exam": False, "needs_class": False, "problems": []}
        return {"kind": "school", "id": src.id, "name": src.name, "students": len(rows)}

    def typed_part_label(self, part):
        return {"theory": "Written", "practical": "Practical", "total": "Total", "pt5": "PT part", "portfolio": "Portfolio",
                "project": "Project", "notebook": "Notebook", "viva": "Viva", "file": "Practical file",
                "ptest": "Practical test"}.get(part, part)

    def typed_columns(self, cls, exam, subject):
        """What the Type marks screen offers for one subject in one exam: [(part, max, label, typed by default)]."""
        cfg = self.cfg
        sc = cfg.scheme(cls, subject, exam)
        if not sc:
            return []
        out = [("theory", sc["theory"], "Written" if sc["second"] or cfg.exam_kind(exam) != "pt" else "Marks", True)]
        sec = sc["second"]
        if sec:
            if sec["parts"]:
                for key, mx in sec["parts"]:
                    part = next((p for p, real in PART_KEYS.items() if key in real), None)
                    if part and part != "pt5":            # the PT part is worked out from the periodic test
                        out.append((part, mx, cfg.part_label(key), not sec["optional"]))
            else:
                out.append(("practical", sec["max"], sec["label"], not sec["optional"]))
        return out

    def roster(self, cls, section="", ds=None):
        """Students of a class (and section) for the Type marks screen: from class lists, from marks typed or
        uploaded so far (ds = the results already made, if any), in roll-number order."""
        sec = (section or "").strip().upper()
        found = {}

        def put(name, roll="", adm="", s_cls="", s_sec=""):
            if s_cls != cls or (sec and s_sec and s_sec != sec) or not clean(name):
                return
            key = ("a", adm) if adm else ("r", roll, norm_name(name)) if roll else ("n", norm_name(name))
            for k, v in list(found.items()):
                if (adm and v["adm_no"] == adm) or (not adm and norm_name(v["name"]) == norm_name(name)):
                    key = k
            have = found.setdefault(key, {"roll": "", "adm_no": "", "name": clean(name), "section": s_sec})
            have["roll"] = have["roll"] or roll
            have["adm_no"] = have["adm_no"] or adm
            have["section"] = have["section"] or s_sec

        for cl in self.class_lists:
            for s in cl["students"]:
                put(s["name"], s.get("roll") or "", s.get("adm_no") or "", s.get("cls") or "", s.get("section") or "")
        for src in self.sources:
            t = getattr(src, "typed", None)
            if t:
                for r in t["rows"]:
                    put(r["name"], r["roll"], r["adm_no"], t["cls"], r.get("section") or t["section"])
        if ds is None and any(not getattr(src, "typed", None) for src in self.sources):
            try:
                ds = self.build()
            except Exception:
                ds = None                           # files still waiting for answers on the check screen
        for s in (ds.students.values() if ds else []):
            put(s.name, s.roll or "", s.adm_no or "", s.cls or "", s.section or "")
        def order(r):
            n = parse_number(r["roll"])
            return (r["section"], 0 if n is not None else 1, n or 0, norm_name(r["name"]))
        return sorted(found.values(), key=order)

    def remove_source(self, source_id):
        self.sources = [s for s in self.sources if s.id != source_id]
        self.file_teachers = [t for t in self.file_teachers if t.get("source_id") != source_id]
        for k in [k for k in self.layouts if k[0] == source_id]:
            del self.layouts[k]

    def _apply_saved(self, lay, saved):
        for k in ("exam", "cls", "section", "skip"):
            if k in saved:
                lay[k] = saved[k]
        bycol = {c["col"]: c for c in lay["columns"]}
        for cs in saved.get("columns", []):
            c = bycol.get(cs["col"])
            if c:
                for k in ("role", "subject", "component", "exam"):
                    c[k] = cs.get(k)
                c["sure"] = True
                c["why"] = "Same as last time (remembered)"
        lay["remembered"] = True
        lay["needs_exam"] = lay["needs_exam"] and not lay["exam"]
        lay["needs_class"] = lay["needs_class"] and not lay["cls"]

    def remember(self, source_id, sheet):
        lay = self.layouts[(source_id, sheet)]
        saved = {"exam": lay["exam"], "cls": lay["cls"], "section": lay["section"], "skip": lay["skip"],
                 "columns": [{k: c[k] for k in ("col", "role", "subject", "component", "exam")} for c in lay["columns"]]}
        self.remembered[lay["signature"]] = saved
        return saved

    # ------------------------------------------------------------ edits from the check screen
    def set_sheet(self, source_id, sheet, **kw):
        lay = self.layouts[(source_id, sheet)]
        if kw.get("cls") and kw["cls"] != lay.get("cls") and lay.get("kind") != "info":
            lay = self._reread_for_class(source_id, sheet, kw["cls"])
        for k, v in kw.items():
            if k in ("exam", "cls", "section", "skip"):
                lay[k] = v or ("" if k == "section" else None if k != "skip" else False)
            if k == "cls" and v:
                lay.pop("clash", None)            # the teacher answered which class it is
                lay["cls_from"] = "you"
        lay["needs_exam"] = (any(c["role"] == "mark" and not c["exam"] for c in lay["columns"])
                             and not lay["exam"] and not any(c["role"] == "row_exam" for c in lay["columns"]))
        lay["needs_class"] = not lay["cls"] and not any(c["role"] in ("class", "class_section") for c in lay["columns"])

    def _reread_for_class(self, source_id, sheet, cls):
        """The teacher said a sheet is another class: its columns are worked out again for that class (which
        parts a subject has - written, practical, internal - depends on the class). Every column the teacher
        set by hand, and the sheet's exam and section, are kept."""
        src = next(s for s in self.sources if s.id == source_id)
        sh = next(x for x in src.sheets if x.name == sheet)
        old = self.layouts[(source_id, sheet)]
        lay = detect(sh, src.name, self.cfg, self.vocab, force_cls=cls)
        mine = {c["col"]: c for c in old["columns"] if c.get("why") in ("Set by you", "Swapped by you")
                or (old.get("remembered") and c.get("why") == "Same as last time (remembered)")}
        for c in lay["columns"]:
            if c["col"] in mine:
                c.update({k: mine[c["col"]][k] for k in ("role", "subject", "component", "exam", "sure", "why")})
            elif src.kind == "scan" and c["role"] != "ignore":
                c["sure"] = False
                c["why"] = (c["why"] + " " if c["why"] else "") + "(read from a scan - please check)"
        for k in ("exam", "exam_from", "section", "skip", "signature", "remembered", "picked"):
            if k in old:
                lay[k] = old[k]
        self.layouts[(source_id, sheet)] = lay
        return lay

    def set_column(self, source_id, sheet, col, role, subject=None, component=None, exam=None):
        lay = self.layouts[(source_id, sheet)]
        for c in lay["columns"]:
            if c["col"] == col:
                c.update(role=role, subject=subject if role == "mark" else None,
                         component=component if role == "mark" else None,
                         exam=exam if role == "mark" else None, sure=True, why="Set by you")
        self.set_sheet(source_id, sheet)

    def confirm_sheet(self, source_id, sheet):
        lay = self.layouts[(source_id, sheet)]
        for c in lay["columns"]:
            c["sure"] = True
        self.remember(source_id, sheet)

    def swap_columns(self, source_id, sheet, a, b):
        lay = self.layouts[(source_id, sheet)]
        ca = next(c for c in lay["columns"] if c["col"] == a)
        cb = next(c for c in lay["columns"] if c["col"] == b)
        for k in ("role", "subject", "component", "exam"):
            ca[k], cb[k] = cb[k], ca[k]
        ca["sure"] = cb["sure"] = True
        ca["why"] = cb["why"] = "Swapped by you"

    def correct(self, ref_key, value):
        if value is None:
            self.corrections.pop(ref_key, None)
        else:
            self.corrections[ref_key] = str(value)

    def pending(self):
        """What still has to be confirmed before results can be made."""
        out = []
        for src in self.sources:
            for sh in src.sheets:
                lay = self.layouts[(src.id, sh.name)]
                if lay["skip"]:
                    continue
                if lay.get("needs_exam"):
                    out.append({"source": src.id, "sheet": sh.name, "what": "exam",
                                "text": f"{src.name} › {sh.name}: which exam are these marks from?"})
                if lay.get("needs_class"):
                    out.append({"source": src.id, "sheet": sh.name, "what": "class",
                                "text": f"{src.name} › {sh.name}: which class is this?"})
                if lay.get("clash"):
                    cl = lay["clash"]
                    out.append({"source": src.id, "sheet": sh.name, "what": "class_clash",
                                "text": f"{src.name} › {sh.name}: you picked {self.cfg.class_label(cl['picked'])}, "
                                        f"but {cl['why']} - which class is it?"})
                for c in lay["columns"]:
                    if not c["sure"]:
                        out.append({"source": src.id, "sheet": sh.name, "what": "column", "col": c["col"],
                                    "text": f"{src.name} › {sh.name} › column “{c['header'] or c['col'] + 1}”: {c['why']}"})
        return out

    # ------------------------------------------------------------ build
    def build(self):
        return Builder(self).run()


def ref_key(ref):
    return f"{ref.file}|{ref.sheet}|{ref.row}|{ref.col}"


class Dataset:
    def __init__(self, cfg):
        self.cfg = cfg
        self.students = {}           # sid -> Student
        self.marks = []
        self.issues = []
        self.raw_sheets = []         # (file, sheet, rows) for the Source Data sheet
        self.row_totals = []

    def issue(self, *a, **kw):
        self.issues.append(Issue(*a, **kw))

    def ordered_students(self):
        def rollkey(s):
            r = s.roll or s.adm_no or s.board_roll
            return (0, int(r), "") if r.isdigit() else (1, 0, r)
        cls_order = {c: i for i, c in enumerate(self.cfg.classes)}
        return sorted(self.students.values(),
                      key=lambda s: (cls_order.get(s.cls, 9), s.section or "", rollkey(s), norm_name(s.name)))

    def classes(self):
        present = {s.cls for s in self.students.values() if s.cls}
        return [c for c in self.cfg.classes if c in present] + sorted(present - set(self.cfg.classes))

    def exams_for(self, cls):
        present = {m.exam for m in self.marks if self.students[m.sid].cls == cls}
        order = self.cfg.class_exams(cls)
        return [e for e in order if e in present] + sorted(present - set(order))

    def subjects_for(self, cls):
        present = set()
        for s in self.students.values():
            if s.cls == cls:
                present.update(s.subjects)
        return self.cfg.order_subjects(present)

    def sections_for(self, cls):
        return sorted({s.section for s in self.students.values() if s.cls == cls and s.section})


class Builder:
    def __init__(self, project):
        self.p = project
        self.cfg = project.cfg
        self.v = project.vocab
        self.ds = Dataset(self.cfg)
        self.by_key = {}             # identity key -> sid
        self.seen_in = {}            # sid -> set of (source, sheet)
        self.cells = {}              # mark key -> list of Mark (to find duplicates)
        self.all_marks = []          # every mark read, before subjects/parts are settled
        self.choices = {}            # sid -> list of subject codes from 'subject choice' columns
        self.lang_choice = {}        # sid -> (language subject code, ref) from 'Language' text columns
        self.col_info = []           # (src, sheet, lay)
        self.n = 0

    # ---------------------------------------------------------------- students
    def _new_student(self, ident, ref):
        self.n += 1
        sid = f"S{self.n:04d}"
        st = Student(sid=sid, name=ident.get("name", ""), cls=ident.get("cls", ""), section=ident.get("section", ""),
                     roll=ident.get("roll", ""), adm_no=ident.get("adm_no", ""), board_roll=ident.get("board_roll", ""),
                     father=ident.get("father", ""), mother=ident.get("mother", ""), gender=ident.get("gender", ""),
                     group_given=ident.get("group", ""))
        st.refs.append(ref)
        self.ds.students[sid] = st
        self.seen_in[sid] = set()
        return st

    def _keys(self, ident):
        cls = ident.get("cls", "")
        strong, weak = [], []
        if ident.get("adm_no"):
            strong.append(("adm", ident["adm_no"].upper()))
        if ident.get("board_roll"):
            strong.append(("brd", ident["board_roll"]))
        if ident.get("roll") and cls:
            strong.append(("roll", cls, ident.get("section", ""), ident["roll"].upper()))
        if ident.get("name"):
            n = norm_name(ident["name"])
            if ident.get("father"):
                weak.append(("namef", cls, n, norm_name(ident["father"])))
            weak.append(("name", cls, n))
        return strong, weak

    def _resolve(self, ident, ref, here):
        """Find the student this row belongs to, or create a new one."""
        strong, weak = self._keys(ident)
        cand = []
        for k in strong:
            if k in self.by_key and self.by_key[k] not in cand:
                cand.append(self.by_key[k])
        st = None
        if cand:
            st = self.ds.students[cand[0]]
            if len(cand) > 1:
                self.ds.issue("warning", "id_conflict",
                              f"Row {ref.row}: the IDs on this row belong to different students "
                              f"({', '.join(self.ds.students[c].name for c in cand)}). Linked to {st.name}.", ref, sid=st.sid)
            if here in self.seen_in[st.sid]:
                # same ID twice in the same sheet
                self.ds.issue("error", "duplicate_id",
                              f"{self._id_text(ident)} appears more than once in this sheet "
                              f"({st.name} and {ident.get('name') or '?'}). Kept as separate students - please check.",
                              ref, sid=st.sid)
                st = None
            elif ident.get("name") and st.name and not _same_name(ident["name"], st.name):
                self.ds.issue("warning", "id_name_mismatch",
                              f"{self._id_text(ident)} is “{st.name}” in one place and “{ident['name']}” here. "
                              f"Treated as different students - if they are the same, correct the name or ID.",
                              ref, sid=st.sid)
                st = None
        if st is None and not cand:
            # no ID match: try the name, but never merge two rows of the same sheet
            matches = []
            for k in weak:
                if k in self.by_key:
                    sid = self.by_key[k]
                    if sid not in matches:
                        matches.append(sid)
                    break
            matches = [m for m in matches if here not in self.seen_in[m]
                       and not _ids_clash(self.ds.students[m], ident)]
            if len(matches) == 1:
                st = self.ds.students[matches[0]]
        if st is None:
            st = self._new_student(ident, ref)
        else:
            st.refs.append(ref)
            for f in ("roll", "adm_no", "board_roll", "father", "mother", "gender", "section"):
                if ident.get(f) and not getattr(st, f):
                    setattr(st, f, ident[f])
            if ident.get("group") and not st.group_given:
                st.group_given = ident["group"]
            if not st.cls and ident.get("cls"):
                st.cls = ident["cls"]
        self.seen_in[st.sid].add(here)
        for k in strong + weak:
            self.by_key.setdefault(k, st.sid)
        return st

    @staticmethod
    def _id_text(ident):
        for f, label in (("adm_no", "Admission no"), ("board_roll", "Board roll no"), ("roll", "Roll no")):
            if ident.get(f):
                return f"{label} {ident[f]}"
        return ident.get("name", "?")

    # ---------------------------------------------------------------- main
    def run(self):
        for src in self.p.sources:
            for sh in src.sheets:
                lay = self.p.layouts[(src.id, sh.name)]
                self.ds.raw_sheets.append((src.name, sh.name, sh.rows, lay["skip"]))
                if lay["skip"]:
                    continue
                self._read_sheet(src, sh, lay)
        self._sections_from_class_lists()
        self._finish()
        return self.ds

    def _sections_from_class_lists(self):
        """Students whose files give no section get it from the uploaded class lists (same class only)."""
        if not self.p.class_lists:
            return
        placer = classlist.Placer(self.p.class_lists)
        n = 0
        for st in self.ds.students.values():
            if st.section:
                continue
            e, how = placer.place(st.name, st.cls, st.adm_no, st.board_roll)
            if e and e["section"] and (not st.cls or e["cls"] == st.cls):
                st.section = e["section"]
                st.cls = st.cls or e["cls"]
                n += 1
                if how == "close name":
                    self.ds.issue("warning", "section_by_close_name",
                                  f"{st.name}: section {e['section']} taken from the class list, where the name is "
                                  f"written “{e['name']}”. Please check it is the same student.", st.refs[0] if st.refs else None,
                                  sid=st.sid)
        if n:
            self.ds.issue("info", "sections_from_class_lists",
                          f"{n} student{'s' if n != 1 else ''} got their section from the class lists.")

    def _read_sheet(self, src, sh, lay):
        cfg, v = self.cfg, self.v
        cols = lay["columns"]
        by_role = {}
        for c in cols:
            by_role.setdefault(c["role"], []).append(c)
        here = (src.id, sh.name)
        mark_cols = [c for c in by_role.get("mark", [])]
        sheet_info = {"src": src, "sheet": sh.name, "lay": lay, "students": []}
        self.col_info.append(sheet_info)
        # (whether a column's part exists - practical, internal, notebook... - depends on the
        #  student's class, so it is checked mark by mark in _finish)

        for r in range(lay["data_start"], len(sh.rows)):
            row = sh.rows[r]
            if not any(clean(x) for x in row):
                continue
            get = lambda col: clean(row[col]) if col < len(row) else ""
            ref_row = Ref(src.name, sh.name, r + 1)
            ident = {}
            for role in ("name", "father", "mother", "roll", "adm_no", "board_roll", "gender"):
                for c in by_role.get(role, []):
                    val = get(c["col"])
                    if val:
                        ident[role] = val
                        break
            for k in ("roll", "adm_no", "board_roll"):
                if k in ident:
                    d = parse_number(ident[k])
                    if d is not None and d == d.to_integral_value():
                        ident[k] = str(int(d))
            if "gender" in ident:
                g = ident["gender"].strip().upper()[:1]
                ident["gender"] = g if g in "MFT" else ""
            cls, sec = lay.get("cls") or "", lay.get("section") or ""
            for c in by_role.get("class_section", []):
                cc, ss = v.class_section(get(c["col"]))
                cls = cc or cls
                sec = ss or sec
            for c in by_role.get("class", []):
                cc, ss = v.class_section(get(c["col"]))
                cls = cc or cls
                sec = ss or sec
            for c in by_role.get("section", []):
                if get(c["col"]):
                    sec = get(c["col"]).upper()
            ident["cls"], ident["section"] = cls or "", sec or ""
            for c in by_role.get("group", []):
                gv = get(c["col"])
                if gv:
                    gid = self._group_id(gv)
                    if gid:
                        ident["group"] = gid
            nm = norm(ident.get("name", ""))
            if nm in SUMMARY_NAMES and not any(ident.get(k) for k in ("roll", "adm_no", "board_roll")):
                continue
            has_marks = any(get(c["col"]) for c in mark_cols)
            if not any(ident.get(k) for k in ("name", "roll", "adm_no", "board_roll")):
                if has_marks:
                    self.ds.issue("error", "no_student",
                                  f"{sh.name} row {r + 1} has marks but no student name or roll number - not used.", ref_row)
                continue
            if not ident.get("name"):
                self.ds.issue("info", "no_name", f"{sh.name} row {r + 1}: no name, identified by {self._id_text(ident)}.", ref_row)
            st = self._resolve(ident, ref_row, here)
            sheet_info["students"].append((st.sid, r))
            # subject choices
            for c in by_role.get("choice", []):
                for part in re.split(r"[,/;+&]| and ", get(c["col"])):
                    code = v.find_subject(part) or v.find_subject_fuzzy(part)
                    if code:
                        self.choices.setdefault(st.sid, [])
                        if code not in self.choices[st.sid]:
                            self.choices[st.sid].append(code)
                    elif clean(part):
                        self.ds.issue("warning", "unknown_choice",
                                      f"{st.name}: subject “{clean(part)}” in the subject list is not in the subject table.",
                                      Ref(src.name, sh.name, r + 1, c["col"]), sid=st.sid)
            # which language the student takes (text under a 'Language' heading)
            for c in by_role.get("lang_choice", []):
                t = get(c["col"])
                if not t:
                    continue
                code = v.find_subject(t) or v.find_subject_fuzzy(t)
                if code:
                    self.lang_choice[st.sid] = (code, Ref(src.name, sh.name, r + 1, c["col"]))
                else:
                    self.ds.issue("warning", "unknown_language",
                                  f"{st.name}: language “{t}” is not in the subject table.",
                                  Ref(src.name, sh.name, r + 1, c["col"]), sid=st.sid)
            # long format: subject (and exam) come from the row
            row_subject = None
            if lay["format"] == "long":
                for c in by_role.get("row_subject", []):
                    t = get(c["col"])
                    row_subject = v.find_subject(t) or v.find_subject_fuzzy(t)
                    if not row_subject and t:
                        self.ds.issue("error", "unknown_subject",
                                      f"{st.name}: subject “{t}” is not in the subject table - marks not used.",
                                      Ref(src.name, sh.name, r + 1, c["col"]), sid=st.sid)
            row_exam = None
            for c in by_role.get("row_exam", []):
                row_exam = v.find_exam(get(c["col"]))
                if not row_exam and get(c["col"]):
                    self.ds.issue("error", "unknown_exam",
                                  f"{st.name}: exam “{get(c['col'])}” is not one of the exams in settings - marks not used.",
                                  Ref(src.name, sh.name, r + 1, c["col"]), sid=st.sid)
            row_sum = Decimal(0)
            row_has_num = False
            for c in mark_cols:
                subject = c["subject"] or row_subject
                exam = c["exam"] or row_exam or lay["exam"]
                if not subject or not exam:
                    continue
                ref = Ref(src.name, sh.name, r + 1, c["col"])
                raw = get(c["col"])
                key = ref_key(ref)
                original = None
                if key in self.p.corrections:
                    original = raw
                    raw = self.p.corrections[key]
                m = self._make_mark(st, exam, subject, c["component"] or "theory", raw, ref, original)
                if m.kind == "number":
                    row_sum += m.value
                    row_has_num = True
            for c in by_role.get("file_total", []):
                t = parse_number(get(c["col"]))
                if t is not None and row_has_num and lay["format"] == "wide" and t != row_sum:
                    self.ds.issue("warning", "file_total_mismatch",
                                  f"{st.name}: the file's own total is {fmt_mark(t)} but the marks in this row add up to "
                                  f"{fmt_mark(row_sum)}. The tool uses the individual marks - please check the row.",
                                  Ref(src.name, sh.name, r + 1, c["col"]), sid=st.sid)

    def _group_id(self, text):
        n = norm(text)
        if n in self.v.group_phrases:
            return self.v.group_phrases[n]
        m = re.match(r"^(group\s*)?([a-e])$", n)
        if m:
            return m.group(2).upper()
        for ph, gid in self.v.group_phrases.items():
            if len(ph) > 4 and ph in n:
                return gid
        return None

    def _make_mark(self, st, exam, subject, component, raw, ref, original):
        """Read one cell. Whether the value fits the maximum is checked later (_settle), when the
        student's class - and so the marks scheme - is known for sure."""
        cfg = self.cfg
        m = Mark(sid=st.sid, exam=exam, subject=subject, component=component, raw=raw, kind="blank",
                 ref=ref, original=original)
        if raw == "":
            m.kind = "blank"
        elif cfg.leave_code(raw):
            m.kind, m.code = "leave", cfg.leave_code(raw)
        else:
            val = parse_number(raw)
            if val is None:
                m.kind, m.problem = "invalid", f"“{raw}” is not a number or a leave code"
            elif val < 0:
                m.kind, m.problem = "invalid", f"{raw} is negative"
            else:
                m.kind, m.value = "number", val
        self.all_marks.append(m)
        return m

    # ---------------------------------------------------------------- after reading
    def _language_of(self, st):
        """The language a student takes (Classes I-X): from a 'Language' column, the subject list,
        or a column of that language's own marks."""
        langs = self.cfg.languages_for(st.cls)
        if st.sid in self.lang_choice:
            return self.lang_choice[st.sid][0]
        picked = [c for c in self.choices.get(st.sid, []) if c in langs]
        if len(picked) == 1:
            return picked[0]
        own = {m.subject for m in self.all_marks if m.sid == st.sid and m.subject in langs and m.kind != "blank"}
        if st.cls == "X":
            own.discard("302")
        return own.pop() if len(own) == 1 else None

    def _settle(self):
        """Every mark gets its real subject and part, and is checked against the maximum of the
        student's class. Marks of subjects/parts that are not assessed are set aside with a note."""
        cfg, ds = self.cfg, self.ds
        kept, notes, no_lang, bad_cols = [], {}, set(), set()
        # a marks column with nothing typed in it at all (an exam not written yet, internals not
        # given) is left out - its blanks do not mean "absent"
        filled = {(m.ref.file, m.ref.sheet, m.ref.col) for m in self.all_marks if m.kind != "blank"}
        empty = {}
        for m in self.all_marks:
            k = (m.ref.file, m.ref.sheet, m.ref.col)
            if m.ref.col is not None and k not in filled:
                empty.setdefault((m.ref.file, m.ref.sheet), set()).add(m.ref.col)
        for (fname, sheet), cols in empty.items():
            ds.issue("info", "empty_columns",
                     f"{fname} › {sheet}: {len(cols)} marks column{'s have' if len(cols) != 1 else ' has'} nothing typed "
                     f"in {'them' if len(cols) != 1 else 'it'} - left out (not counted as absent).", Ref(fname, sheet))
        for m in self.all_marks:
            if m.ref.col is not None and (m.ref.file, m.ref.sheet, m.ref.col) not in filled:
                continue
            st = ds.students[m.sid]
            if m.subject == LANG_MARK:
                code = self._language_of(st)
                if not code:
                    if m.kind != "blank" and st.sid not in no_lang:
                        no_lang.add(st.sid)
                        ds.issue("error", "no_language",
                                 f"{st.name}: has marks under “Language” but it is not known which language "
                                 f"they take. Add a Language column (French / German / ...) to the student list.",
                                 m.ref, sid=st.sid)
                    continue
                m.subject = code
            m.subject = cfg.resolve_subject(st.cls, m.subject)
            if m.exam not in cfg.exams:
                kept.append(m)
                continue
            sc = cfg.scheme(st.cls, m.subject, m.exam)
            if sc is None:
                if m.kind != "blank":
                    k = (st.cls, m.subject, m.exam)
                    notes.setdefault(k, 0)
                    notes[k] += 1
                continue
            # a generic part name from the heading ('notebook') -> this scheme's part ('i_notebook' / 'p_notebook')
            if m.component in PART_KEYS:
                keys = [k for k, _ in cfg.subparts(st.cls, m.subject, m.exam)]
                real = next((k for k in PART_KEYS[m.component] if k in keys), None)
                if real is None:
                    ck = (m.ref.file, m.ref.sheet, m.ref.col, st.cls)
                    if ck not in bad_cols:
                        bad_cols.add(ck)
                        ds.issue("error", "part_not_allowed",
                                 f"{m.ref.sheet}: a “{m.component}” column for {cfg.subject_name(m.subject)} - Class {st.cls} "
                                 f"has no such part in {cfg.exam_name(m.exam)}. These marks are not used.",
                                 Ref(m.ref.file, m.ref.sheet, 0, m.ref.col), subject=m.subject, exam=m.exam)
                    continue
                m.component = real
            comps = cfg.components(st.cls, m.subject, m.exam)
            parts = dict(cfg.subparts(st.cls, m.subject, m.exam))
            if m.component == "total":
                mx = cfg.subject_max(st.cls, m.subject, m.exam)
            elif m.component in parts:
                mx = parts[m.component]
            else:
                mx = comps.get(m.component)
            if mx is None:
                ck = (m.ref.file, m.ref.sheet, m.ref.col, st.cls)
                if ck not in bad_cols:
                    bad_cols.add(ck)
                    what = "practical" if m.component == "practical" else m.component
                    ds.issue("error", "practical_not_allowed",
                             f"{m.ref.sheet}: column {m.ref.cell().rstrip('0123456789') or '?'} has {what} marks for "
                             f"{cfg.subject_name(m.subject)}, which has no {what} part in Class {st.cls or '?'} "
                             f"{cfg.exam_name(m.exam)}. These marks are not used.",
                             Ref(m.ref.file, m.ref.sheet, 0, m.ref.col), subject=m.subject, exam=m.exam)
                continue
            if m.kind == "number" and m.value > mx:
                m.kind, m.problem = "invalid", f"{fmt_mark(m.value)} is more than the maximum {fmt_mark(mx)}"
            kept.append(m)
        for (cls, subj, exam), n in notes.items():
            ds.issue("info", "not_assessed",
                     f"Class {cls}: {cfg.subject_name(subj)} is not counted in {cfg.exam_name(exam)} (school rule in "
                     f"settings), so {n} mark{'s' if n != 1 else ''} there {'are' if n != 1 else 'is'} not used.",
                     None, subject=subj, exam=exam)
        self.cells = {}
        for m in kept:
            self.cells.setdefault(m.key(), []).append(m)

    def _finish(self):
        cfg, ds = self.cfg, self.ds
        self._settle()
        # 1. one record per key: duplicates and conflicts
        marks = []
        for key, lst in self.cells.items():
            if len(lst) == 1:
                marks.append(lst[0])
                continue
            vals = {(m.kind, m.value, m.code) for m in lst if m.kind != "blank"}
            st = ds.students[key[0]]
            where = "; ".join(m.ref.text() for m in lst)
            nonblank = [m for m in lst if m.kind != "blank"]
            if len(vals) <= 1:
                keep = nonblank[0] if nonblank else lst[0]
                if nonblank and len(nonblank) > 1:
                    ds.issue("info", "duplicate_same",
                             f"{st.name}: {cfg.subject_name(key[2])} {key[3]} ({cfg.exam_name(key[1])}) is given "
                             f"{len(nonblank)} times with the same value - used once.", keep.ref, sid=st.sid,
                             subject=key[2], exam=key[1])
                marks.append(keep)
            else:
                keep = nonblank[0]
                shown = ", ".join(m.raw for m in nonblank)
                keep.kind, keep.problem = "invalid", f"different values in two places ({shown})"
                ds.issue("error", "conflict",
                         f"{st.name}: {cfg.subject_name(key[2])} {key[3]} ({cfg.exam_name(key[1])}) has different values "
                         f"in two places: {shown} ({where}). Not used until corrected.", keep.ref, sid=st.sid,
                         subject=key[2], exam=key[1],
                         fix={"type": "choose", "options": [{"value": m.raw, "ref": m.ref.to_dict()} for m in nonblank]})
                marks.append(keep)
        # 2. which subjects each student takes
        has_data = {}
        for m in marks:
            if m.kind != "blank":
                has_data.setdefault(m.sid, set()).add(m.subject)
        for sid, st in ds.students.items():
            if sid in self.choices:
                st.subjects = cfg.order_subjects(set(self.choices[sid]))
                st.choices_given = True
                extra = has_data.get(sid, set()) - set(st.subjects)
                for sub in cfg.order_subjects(extra):
                    ds.issue("warning", "marks_not_in_choices",
                             f"{st.name} has marks in {cfg.subject_name(sub)}, which is not in their subject list. "
                             f"Those marks are still used.", st.refs[0], sid=sid, subject=sub)
                    st.subjects.append(sub)
            else:
                st.subjects = cfg.order_subjects(has_data.get(sid, set()))
        # 3. drop blanks of subjects not taken; add missing parts
        kept = []
        for m in marks:
            st = ds.students[m.sid]
            if m.subject not in st.subjects:
                continue
            kept.append(m)
        marks = kept
        present = {}
        for m in marks:
            present.setdefault((m.sid, m.exam, m.subject), {})[m.component] = m
        drop = set()
        both_noted = set()
        written_only = {}
        for (sid, exam, subject), parts in present.items():
            if exam not in cfg.exams or "total" in parts:
                continue
            st = ds.students[sid]
            comps = cfg.components(st.cls, subject, exam)
            any_m = next(iter(parts.values()))

            def add_blank(comp):
                mm = Mark(sid=sid, exam=exam, subject=subject, component=comp, raw="", kind="blank",
                          ref=Ref(any_m.ref.file, any_m.ref.sheet, any_m.ref.row), problem="no column")
                marks.append(mm)
                parts[comp] = mm
            if "theory" in comps and "theory" not in parts:
                add_blank("theory")
            if "practical" not in comps:
                continue
            subs = [k for k, _ in cfg.subparts(st.cls, subject, exam)]
            given = [k for k in subs if k in parts]
            if subs and given:
                if "practical" in parts:
                    # the internal marks were given both as one total and as parts: the parts win
                    # (unless they are all blank)
                    if any(parts[k].kind != "blank" for k in given):
                        direct = parts.pop("practical")
                        drop.add(id(direct))
                        kk = (direct.ref.file, direct.ref.sheet, subject, exam)
                        if direct.kind != "blank" and kk not in both_noted:
                            both_noted.add(kk)
                            ds.issue("info", "internal_both",
                                     f"{direct.ref.sheet}: {cfg.subject_name(subject)} ({cfg.exam_name(exam)}) has the "
                                     f"{cfg.second_label(st.cls, subject, exam).lower()} marks both as one total and as "
                                     f"parts - the parts are used.", Ref(direct.ref.file, direct.ref.sheet),
                                     subject=subject, exam=exam)
                        for k in subs:
                            if k not in parts and k != "i_pt":
                                add_blank(k)
                    else:
                        for k in given:
                            drop.add(id(parts.pop(k)))
                else:
                    for k in subs:
                        if k not in parts and k != "i_pt":
                            add_blank(k)
            elif "practical" not in parts:
                if cfg.second_optional(st.cls, subject, exam):
                    written_only.setdefault((st.cls, exam), set()).add(subject)
                else:
                    add_blank("practical")
        if drop:
            marks = [m for m in marks if id(m) not in drop]
        for (cls, exam), subs in sorted(written_only.items(), key=lambda x: (cfg.class_level(x[0][0]), x[0][1])):
            ds.issue("info", "written_only",
                     f"Class {cls} {cfg.exam_name(exam)}: no internal / practical marks were given for "
                     f"{', '.join(cfg.subject_name(s) for s in cfg.order_subjects(subs))} - worked out of the written "
                     f"paper alone. Add them any time (one internal mark, or portfolio / project / notebook).",
                     None, exam=exam)
        # 4. validation messages for every record
        sheet_missing = set()
        for m in marks:
            st = ds.students[m.sid]
            subj, exn = cfg.subject_name(m.subject), cfg.exam_name(m.exam)
            part = part_word(cfg, st.cls, m)
            if m.kind == "invalid":
                fix = {"type": "cell", "ref": m.ref.to_dict(), "key": ref_key(m.ref), "current": m.raw}
                ds.issue("error", "invalid_mark",
                         f"{st.name}: {subj} {part} ({exn}) - {m.problem}. Not used until corrected.",
                         m.ref, sid=m.sid, subject=m.subject, exam=m.exam, fix=fix)
            elif m.kind == "blank" and m.problem == "no column":
                k = (m.ref.file, m.ref.sheet, m.subject, m.exam, m.component)
                if k not in sheet_missing:
                    sheet_missing.add(k)
                    ds.issue("error", "missing_component_column",
                             f"{m.ref.file} › {m.ref.sheet}: {subj} has no {part} column for {exn}, so "
                             f"{subj} cannot be totalled there.", Ref(m.ref.file, m.ref.sheet), subject=m.subject, exam=m.exam)
            elif m.kind == "blank":
                other = present.get((m.sid, m.exam, m.subject), {})
                if any(x.kind == "number" for x in other.values() if x is not m):
                    ds.issue("warning", "missing_component",
                             f"{st.name}: {subj} {part} ({exn}) is blank while another part has marks - "
                             f"{subj} is left incomplete.", m.ref, sid=m.sid, subject=m.subject, exam=m.exam,
                             fix={"type": "cell", "ref": m.ref.to_dict(), "key": ref_key(m.ref), "current": ""}
                             if m.ref.col is not None else {})
            if m.original is not None:
                ds.issue("info", "corrected",
                         f"{st.name}: {subj} {part} ({exn}) corrected by you from “{m.original}” to “{m.raw}”.",
                         m.ref, sid=m.sid, subject=m.subject, exam=m.exam,
                         fix={"type": "undo", "key": ref_key(m.ref)})
        blanks = {}
        for m in marks:
            if m.kind == "blank" and not m.problem:
                parts = present.get((m.sid, m.exam, m.subject), {})
                if all(p.kind == "blank" for p in parts.values()):
                    blanks.setdefault((m.sid, m.exam), set()).add(m.subject)
        for (sid, exam), subs in blanks.items():
            st = ds.students[sid]
            ds.issue("info", "blank_absent",
                     f"{st.name}: blank in {', '.join(cfg.subject_name(s) for s in cfg.order_subjects(subs))} "
                     f"({cfg.exam_name(exam)}) - treated as Absent (blank means absent for a subject the student takes).",
                     None, sid=sid, exam=exam)
        ds.marks = marks
        # 5. swapped theory/practical columns
        self._check_swaps()
        # 6. class, group, same names
        for sid, st in ds.students.items():
            if not st.cls:
                ds.issue("error", "no_class", f"{st.name}: class is not known (I to XII).", st.refs[0], sid=sid)
            if cfg.has_streams(st.cls) or not st.cls:
                grp, note = infer_group(st.subjects, cfg.groups, st.group_given)
                st.group, st.group_note = grp, note
                if note and st.subjects:
                    ds.issue("warning" if st.group_given else "info", "group_check", f"{st.name}: {note}.", st.refs[0], sid=sid)
            else:
                st.group, st.group_note = "", ""
            st.combo = combo_of(cfg, st.cls, st.subjects)
            for e in {m.exam for m in marks if m.sid == sid}:
                if st.cls and e not in cfg.class_exams(st.cls):
                    ds.issue("warning", "exam_not_in_class",
                             f"{st.name}: has {cfg.exam_name(e)} marks, but Class {st.cls} does not have that exam in settings.",
                             st.refs[0], sid=sid, exam=e)
        names = {}
        for st in ds.students.values():
            names.setdefault((st.cls, norm_name(st.name)), []).append(st)
        for (cls, n), lst in names.items():
            if n and len(lst) > 1:
                ds.issue("info", "same_name",
                         f"{len(lst)} students named “{lst[0].name}” in Class {cls or '?'} - kept separate "
                         f"({', '.join(s.label() for s in lst)}).", lst[0].refs[0], sid=lst[0].sid)

    def _check_swaps(self):
        cfg, ds = self.cfg, self.ds
        for info in self.col_info:
            lay, src = info["lay"], info["src"]
            groups = {}
            for c in lay["columns"]:
                if c["role"] == "mark" and c["subject"]:
                    ex = c["exam"] or lay["exam"]
                    groups.setdefault((c["subject"], ex), {})[c["component"]] = c
            for (subj, ex), parts in groups.items():
                if "theory" not in parts or "practical" not in parts or ex not in cfg.exams or subj == LANG_MARK:
                    continue
                comps = cfg.components(lay.get("cls") or "XI", subj, ex)
                pr_max = comps.get("practical")
                th_max = comps.get("theory")
                if not pr_max:
                    continue
                sheet = next(s for s in src.sheets if s.name == lay["sheet"])
                rows = sheet.rows[lay["data_start"]:]
                def nums(col):
                    out = []
                    for r in rows:
                        d = parse_number(clean(r[col])) if col < len(r) else None
                        if d is not None:
                            out.append(d)
                    return out
                th, pr = nums(parts["theory"]["col"]), nums(parts["practical"]["col"])
                if not th or not pr:
                    continue
                pr_over = sum(1 for x in pr if x > pr_max)
                if pr_over and max(th) <= pr_max and max(pr) <= th_max:
                    ds.issue("error", "swapped_columns",
                             f"{src.name} › {lay['sheet']}: {cfg.subject_name(subj)} ({cfg.exam_name(ex)}) - the practical "
                             f"column has marks above {fmt_mark(pr_max)} and the theory column has none above "
                             f"{fmt_mark(pr_max)}. The Theory and Practical columns look swapped.",
                             Ref(src.name, lay["sheet"]), subject=subj, exam=ex,
                             fix={"type": "swap", "source": src.id, "sheet": lay["sheet"],
                                  "cols": [parts["theory"]["col"], parts["practical"]["col"]]})


def part_word(cfg, cls, m):
    """How a part is called in messages: 'theory' (XI-XII) / 'written', 'practical' / 'internal', 'notebook', ..."""
    c = m.component
    if c == "theory":
        return "theory" if cfg.has_streams(cls) else "written"
    if c == "practical":
        return (cfg.second_label(cls, m.subject, m.exam) or "practical").lower()
    if c == "total":
        return "total"
    return cfg.part_label(c).lower()


def _words(items):
    """['Physics', 'Chemistry', 'Biology'] -> 'Physics, Chemistry and Biology'."""
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _same_name(a, b):
    na, nb = norm_name(a), norm_name(b)
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    if ta and tb and similar(ta[0], tb[0]):
        return True
    return similar(na.replace(" ", ""), nb.replace(" ", ""))


def _ids_clash(st, ident):
    for f in ("adm_no", "board_roll"):
        if ident.get(f) and getattr(st, f) and ident[f].upper() != getattr(st, f).upper():
            return True
    if ident.get("roll") and st.roll and ident.get("section", "") == st.section and ident["roll"] != st.roll:
        return True
    return False
