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
from .layout import Vocab, detect, signature
from .groups import infer_group
from . import readers, gazette

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
        self._n = 0

    # ------------------------------------------------------------ files
    def add_file(self, name, data):
        """Read a file. A CBSE gazette goes to the Board section, anything else is a marks table."""
        sheets = readers.read_file(name, data)
        if len(sheets) == 1 and sheets[0].text and gazette.looks_like_gazette(sheets[0].text):
            g = gazette.parse(sheets[0].text, name)
            g.raw_text = sheets[0].text
            self.gazettes.append(g)
            return {"kind": "gazette", "name": name, "students": len(g.students), "year": g.year}
        return self._add_table(name, sheets)

    def add_pages(self, name, pages):
        sheets, text = readers.read_pages(name, pages)
        if gazette.looks_like_gazette(text):
            g = gazette.parse(text, name)
            g.raw_text = text
            self.gazettes.append(g)
            return {"kind": "gazette", "name": name, "students": len(g.students), "year": g.year}
        return self._add_table(name, sheets, ocr=any(getattr(s, "ocr", False) for s in sheets))

    def _add_table(self, name, sheets, ocr=False):
        self._n += 1
        src = Source(f"F{self._n}", name, sheets, "scan" if ocr else "table")
        self.sources.append(src)
        for sh in sheets:
            if norm(sh.name) in INFO_SHEETS:
                lay = {"sheet": sh.name, "skip": True, "note": "Instructions sheet - not read", "columns": [],
                       "header_rows": [], "data_start": 0, "format": "wide", "exam": None, "cls": None,
                       "section": "", "kind": "info", "signature": "", "needs_exam": False, "needs_class": False,
                       "problems": [], "title": "", "exam_from": "", "cls_from": "", "max_row": None}
                self.layouts[(src.id, sh.name)] = lay
                continue
            lay = detect(sh, name, self.cfg, self.vocab)
            sig = signature(sh, lay)
            lay["signature"] = sig
            if sig in self.remembered:
                self._apply_saved(lay, self.remembered[sig])
            if ocr:
                for c in lay["columns"]:
                    if c["role"] not in ("ignore",):
                        c["sure"] = False
                        c["why"] = (c["why"] + " " if c["why"] else "") + "(read from a scan - please check)"
            self.layouts[(src.id, sh.name)] = lay
        return {"kind": "table", "id": src.id, "name": name, "sheets": [s.name for s in sheets]}

    def remove_source(self, source_id):
        self.sources = [s for s in self.sources if s.id != source_id]
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
        for k, v in kw.items():
            if k in ("exam", "cls", "section", "skip"):
                lay[k] = v or ("" if k == "section" else None if k != "skip" else False)
        lay["needs_exam"] = (any(c["role"] == "mark" and not c["exam"] for c in lay["columns"])
                             and not lay["exam"] and not any(c["role"] == "row_exam" for c in lay["columns"]))
        lay["needs_class"] = not lay["cls"] and not any(c["role"] in ("class", "class_section") for c in lay["columns"])

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
        self.choices = {}            # sid -> list of subject codes from 'subject choice' columns
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
        self._finish()
        return self.ds

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
        # column-level checks
        for c in mark_cols:
            exam = c["exam"] or lay["exam"]
            if c["subject"] and c["component"] == "practical" and exam in cfg.exams:
                if not cfg.components(c["subject"], exam).get("practical"):
                    self.ds.issue("error", "practical_not_allowed",
                                  f"{sh.name}: column “{c['header']}” is practical marks for {cfg.subject_name(c['subject'])}, "
                                  f"which has no practical in {cfg.exam_name(exam)}. These marks are not used.",
                                  Ref(src.name, sh.name, (lay['header_rows'][-1] + 1) if lay['header_rows'] else 0, c["col"]),
                                  subject=c["subject"], exam=exam)

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
        cfg = self.cfg
        m = Mark(sid=st.sid, exam=exam, subject=subject, component=component, raw=raw, kind="blank",
                 ref=ref, original=original)
        comps = cfg.components(subject, exam) if exam in cfg.exams else {}
        mx = cfg.subject_max(subject, exam) if component == "total" else comps.get(component)
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
            elif mx is None:
                m.kind, m.problem = "invalid", f"{cfg.subject_name(subject)} has no {component} part in {cfg.exam_name(exam)}"
                m.value = val
            elif val > mx:
                m.kind, m.problem = "invalid", f"{fmt_mark(val)} is more than the maximum {fmt_mark(mx)}"
                m.value = val
            else:
                m.kind, m.value = "number", val
        self.cells.setdefault(m.key(), []).append(m)
        return m

    # ---------------------------------------------------------------- after reading
    def _finish(self):
        cfg, ds = self.cfg, self.ds
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
        for (sid, exam, subject), parts in present.items():
            if exam not in cfg.exams or "total" in parts:
                continue
            for comp in cfg.components(subject, exam):
                if comp not in parts:
                    any_m = next(iter(parts.values()))
                    mm = Mark(sid=sid, exam=exam, subject=subject, component=comp, raw="", kind="blank",
                              ref=Ref(any_m.ref.file, any_m.ref.sheet, any_m.ref.row), problem="no column")
                    marks.append(mm)
                    parts[comp] = mm
        # 4. validation messages for every record
        sheet_missing = set()
        for m in marks:
            st = ds.students[m.sid]
            subj, exn = cfg.subject_name(m.subject), cfg.exam_name(m.exam)
            if m.kind == "invalid":
                fix = {"type": "cell", "ref": m.ref.to_dict(), "key": ref_key(m.ref), "current": m.raw}
                ds.issue("error", "invalid_mark",
                         f"{st.name}: {subj} {m.component} ({exn}) - {m.problem}. Not used until corrected.",
                         m.ref, sid=m.sid, subject=m.subject, exam=m.exam, fix=fix)
            elif m.kind == "blank" and m.problem == "no column":
                k = (m.ref.file, m.ref.sheet, m.subject, m.exam, m.component)
                if k not in sheet_missing:
                    sheet_missing.add(k)
                    ds.issue("error", "missing_component_column",
                             f"{m.ref.file} › {m.ref.sheet}: {subj} has no {m.component} column for {exn}, so "
                             f"{subj} cannot be totalled there.", Ref(m.ref.file, m.ref.sheet), subject=m.subject, exam=m.exam)
            elif m.kind == "blank":
                other = [x for x in marks if x.sid == m.sid and x.exam == m.exam and x.subject == m.subject and x is not m]
                if any(x.kind == "number" for x in other):
                    ds.issue("warning", "missing_component",
                             f"{st.name}: {subj} {m.component} ({exn}) is blank while the other part has marks - "
                             f"{subj} is left incomplete.", m.ref, sid=m.sid, subject=m.subject, exam=m.exam,
                             fix={"type": "cell", "ref": m.ref.to_dict(), "key": ref_key(m.ref), "current": ""}
                             if m.ref.col is not None else {})
            if m.original is not None:
                ds.issue("info", "corrected",
                         f"{st.name}: {subj} {m.component} ({exn}) corrected by you from “{m.original}” to “{m.raw}”.",
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
                ds.issue("error", "no_class", f"{st.name}: class is not known (XI or XII).", st.refs[0], sid=sid)
            grp, note = infer_group(st.subjects, cfg.groups, st.group_given)
            st.group, st.group_note = grp, note
            if note and st.subjects:
                ds.issue("warning" if st.group_given else "info", "group_check", f"{st.name}: {note}.", st.refs[0], sid=sid)
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
                if "theory" not in parts or "practical" not in parts or ex not in cfg.exams:
                    continue
                comps = cfg.components(subj, ex)
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
