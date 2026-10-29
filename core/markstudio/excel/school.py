"""Writes the school-tests workbook (.xlsm with macros, or .xlsx).

Design rules
* Teachers type/fix marks in the 'Marks ...' sheets (one per class / stream). Everything else is formulas, so a
  corrected mark flows into results, labels, reasons, dashboards and charts.
* Every formula also stores the value Python worked out (cached value), so the
  file shows correct numbers even in viewers that do not recalculate.
* Only functions that exist in Excel 2010+ are used (no FILTER/SORT/TEXTJOIN/
  MAXIFS); comparisons use ROUND(...,6) exactly like calc.py.
* Uploaded text is always written with write_string (never as a formula)."""
import io
import json
import datetime
from decimal import Decimal

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell as rc, xl_col_to_name as colname

from . import theme
from .theme import Formats
from .. import views
from ..calc import STATUS_OK, progress
from ..textutil import fmt_num, fmt_mark, formula_like, r6

LOGO_PATH = __file__.replace("school.py", "rdps_logo.png")


def _fast_prepare_formula(self, formula, expand_future_functions=False):
    """XlsxWriter scans every formula with ~30 regexes looking for Excel 365
    functions. We never use those (only Excel 2010+ functions, and AGGREGATE is
    written with its _xlfn. prefix already), so skipping the scan makes the
    workbook about 4x faster to build - important on school PCs."""
    if formula.startswith("{"):
        formula = formula[1:]
    if formula.startswith("="):
        formula = formula[1:]
    if formula.endswith("}"):
        formula = formula[:-1]
    return formula


xlsxwriter.worksheet.Worksheet._prepare_formula = _fast_prepare_formula

# Subject Results columns
SR_COLS = ["Key", "Student ID", "Name", "Class", "Section", "Group", "Exam", "Exam No", "Subject",
           "Theory / Written", "Theory Max", "Practical / Internal", "Pr / Int Max", "Status", "Obtained", "Max", "%", "Grade",
           "Passed", "Student Avg %", "Class Avg %", "vs Own Avg", "vs Class Avg", "Label", "Reason",
           "Theory %", "Practical %"]
(SR_KEY, SR_ID, SR_NAME, SR_CLASS, SR_SEC, SR_GROUP, SR_EXAM, SR_EXNO, SR_SUBJ, SR_TH, SR_THMAX, SR_PR, SR_PRMAX,
 SR_STATUS, SR_OBT, SR_MAX, SR_PCT, SR_GRADE, SR_PASSED, SR_OWN, SR_CAVG, SR_VOWN, SR_VCLS, SR_LABEL, SR_REASON,
 SR_THP, SR_PRP) = range(27)

MX_HEADER_ROW = 3
MX_FIRST = 4


def _num(d):
    return float(d) if d is not None else ""


def _txt(v):
    return "" if v is None else v


def _q(sheet):
    return "'" + sheet.replace("'", "''") + "'"


def _rng(sheet, r1, c, r2, c2=None):
    c2 = c if c2 is None else c2
    return f"{_q(sheet)}!{rc(r1, c, True, True)}:{rc(r2, c2, True, True)}"


OV = "Overview"
COMBO_SHORT = {"Commerce with Maths": "Comm+Maths", "Other subjects": "Other"}


def _n(d):
    """A number for a formula: 80 -> '80', 37.5 -> '37.5'."""
    return f"{float(d):g}"


def _sheet_name(base, used):
    base = "".join(ch for ch in base if ch not in "[]:*?/\'")[:31].strip()
    name, k = base, 2
    while name in used:
        name = f"{base[:28]} {k}"
        k += 1
    return name


def _slot_plan(cfg, cls, students, subjects):
    """Subjects shared by (nearly) everybody get their own column; the rest - each student's language or
    elective - go into 'Language' / 'Elective' columns. -> (core subjects, slots)"""
    n = max(1, len(students))
    langs = set(cfg.languages_for(cls))
    takers = {s: sum(1 for st in students if s in st.subjects) for s in subjects}
    core = [s for s in subjects if s not in langs and takers[s] >= max(1, n * 0.6)]
    slot_of, rests = {}, []
    for st in students:
        rest = [x for x in cfg.order_subjects(set(st.subjects) & set(subjects)) if x not in core]
        slot_of[st.sid] = {x: i for i, x in enumerate(rest)}
        rests.append(rest)
    n_slots = max((len(r) for r in rests), default=0)
    slots = []
    for i in range(n_slots):
        subs = {r[i] for r in rests if len(r) > i}
        is_lang = subs <= langs
        title = ("Language" if is_lang else "Elective") + (f" {i + 1}" if n_slots > 1 and not is_lang else "")
        slots.append({"title": title, "short": "Lang" if is_lang else ("Elect" + (f" {i + 1}" if n_slots > 1 else "")),
                      "subjects": subs})
    return core, slots, slot_of


def _slot_index(spec, st, subject):
    return spec["slot_of"].get(st.sid, {}).get(subject)


class SchoolWorkbook:
    def __init__(self, ds, res, recipe=None, vba=None, generated=None, logo=None, teachers=None):
        self.ds, self.res, self.cfg = ds, res, ds.cfg
        self.teachers = teachers or []
        self.recipe = recipe or {"items": []}
        self.vba = vba
        self.generated = generated or datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
        self.logo = logo
        self.buf = io.BytesIO()
        self.wb = xlsxwriter.Workbook(self.buf, {"in_memory": True, "strings_to_numbers": False,
                                                 "strings_to_formulas": False, "strings_to_urls": False})
        self.f = Formats(self.wb)
        self.labels = views.student_labels(ds)
        self.order = views.matrix_order(res)
        self.subjects = views.all_subjects(res)
        self.exams = views.all_exams(res)
        self.classes = ds.classes()
        self.sections = views.all_sections(res)
        self.sheets = {}
        self._calc_next = 2

    def calc_alloc(self, n):
        """Reserve n+1 rows on the hidden _calc sheet for one chart's data table."""
        start = self._calc_next
        self._calc_next += n + 3
        return start

    # ------------------------------------------------------------------ helpers
    def logo_image(self, ws, row, col, scale=0.32):
        data = self.logo
        if data is None:
            try:
                with open(LOGO_PATH, "rb") as fh:
                    data = fh.read()
            except OSError:
                return
        ws.insert_image(row, col, "rdps_logo.png", {"image_data": io.BytesIO(data), "x_scale": scale,
                                                    "y_scale": scale, "x_offset": 4, "y_offset": 4,
                                                    "object_position": 3})

    def banner(self, ws, title, sub, last_col, logo=True):
        f = self.f
        band = f.get(bg_color=theme.NAVY)
        for r in range(0, 3):
            ws.set_row(r, 22 if r != 1 else 26)
            for c in range(0, last_col + 1):
                ws.write_blank(r, c, None, band)
        start = 2 if logo else 1
        ws.merge_range(0, start, 1, last_col, title, f.get(font_name=theme.TITLE_FONT, font_size=18,
                                                           font_color=theme.WHITE, bg_color=theme.NAVY,
                                                           valign="bottom", align="left", indent=1))
        ws.merge_range(2, start, 2, last_col, sub, f.get(font_name=theme.TITLE_FONT_LIGHT, font_size=10,
                                                         font_color="#BFE6F8", bg_color=theme.NAVY,
                                                         align="left", indent=1, valign="top"))
        if logo:
            self.logo_image(ws, 0, 0, 0.30)

    def selector(self, ws, row, col, label, source, value, width_cols=1, name=None):
        f = self.f
        ws.write(row, col, label, f.get(bold=True, font_color=theme.MUTED, align="right"))
        fmt = f.get(bold=True, font_color=theme.NAVY, bg_color=theme.TINT, border=1, border_color=theme.BLUE,
                    align="center")
        if width_cols > 1:
            ws.merge_range(row, col + 1, row, col + width_cols, value, fmt)
        else:
            ws.write_string(row, col + 1, value, fmt)
        ws.data_validation(row, col + 1, row, col + 1, {"validate": "list", "source": source,
                                                        "input_title": label, "input_message": "Pick from the list"})
        cell = rc(row, col + 1, True, True)
        if name:
            self.wb.define_name(name, f"={_q(ws.name)}!{cell}")
        return f"{_q(ws.name)}!{cell}"

    def chart(self, kind, title, subtype=None):
        opts = {"type": kind}
        if subtype:
            opts["subtype"] = subtype
        ch = self.wb.add_chart(opts)
        ch.set_title({"name": title, "name_font": {"name": theme.TITLE_FONT, "size": 11, "color": theme.NAVY,
                                                   "bold": False}})
        ch.set_chartarea({"border": {"color": theme.LINE}, "fill": {"color": theme.WHITE}})
        ch.set_plotarea({"fill": {"none": True}, "border": {"none": True}})
        ch.set_legend({"none": True})
        return ch

    def axis_style(self, ch, y_title=None, y_max=None, num="0"):
        ch.set_x_axis({"num_font": {"size": 8, "color": theme.MUTED}, "line": {"color": theme.LINE},
                       "major_gridlines": {"visible": False}})
        y = {"num_font": {"size": 8, "color": theme.MUTED}, "line": {"none": True}, "num_format": num,
             "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3", "width": 0.75}}}
        if y_title:
            y["name"] = y_title
            y["name_font"] = {"size": 8, "color": theme.MUTED, "bold": False}
        if y_max is not None:
            y["min"], y["max"] = 0, y_max
        ch.set_y_axis(y)

    # ------------------------------------------------------------------ build
    def build(self):
        wb = self.wb
        cfg = self.cfg
        wb.set_properties({"title": f"{cfg.rules['school_short']} results {cfg.rules['academic_year']}",
                           "author": cfg.rules["school_name"], "company": cfg.rules["school_name"],
                           "comments": "Made by RDPS Marks Studio. Marks are processed on the school PC only."})
        wb.set_calc_mode("auto")
        # create sheets in display order (formulas may refer to later sheets)
        order = ["Dashboard", "Report Card", "Subject Analysis", "Marks Analysis", "Progress"]
        extras = [it for it in self.recipe.get("items", []) if it.get("type") in ("query_sheet", "chart")]
        if any(it["type"] == "chart" for it in extras):
            order.append("My Charts")
        for it in extras:
            if it["type"] == "query_sheet":
                order.append(it["sheet"])
        if self.teachers:
            order.append("Teachers")
        order += [OV] + self.plan_entry_sheets()
        order += ["Subject Results", "Student Master", "Validation Report", "Config",
                  "Source Data", "_lists", "_calc", "_stats", "_meta"]
        for i, name in enumerate(order):
            ws = wb.add_worksheet(name)
            self.sheets[name] = ws
            if self.vba:
                ws.set_vba_name(f"Sheet{i + 1}")
        if self.vba:
            from .vba import build_vba_project
            wb.add_vba_project(io.BytesIO(build_vba_project([f"Sheet{i + 1}" for i in range(len(order))])),
                               is_stream=True)
            wb.set_vba_name("ThisWorkbook")
        self.write_config()
        self.write_lists()
        self.write_master()
        self.write_matrix_and_results()
        self.write_stats()
        self.write_dashboard()
        self.write_report_card()
        self.write_subject_analysis()
        self.write_marks_analysis()
        self.write_progress()
        if self.teachers:
            self.write_teachers()
        self.write_validation()
        self.write_source()
        self.write_extras()
        self.write_meta()
        for name in ("_lists", "_calc", "_stats", "_meta"):
            self.sheets[name].hide()
        # printing: A4 landscape, fit to the page width, headings repeated on every page
        for name, repeat in (("Subject Analysis", None), ("Marks Analysis", None), ("Progress", None),
                             (OV, MX_HEADER_ROW), ("Subject Results", 0), ("Student Master", 0),
                             ("Validation Report", None), ("Config", None)):
            ws = self.sheets[name]
            ws.set_landscape()
            ws.set_paper(9)
            ws.fit_to_pages(1, 0)
            ws.set_margins(0.4, 0.4, 0.5, 0.5)
            if repeat is not None:
                ws.repeat_rows(repeat)
            ws.set_footer(f"&L&8{cfg.rules['school_short']} · {name}&R&8Page &P of &N")
        self.sheets["Dashboard"].set_footer(f"&L&8{cfg.rules['school_short']} · Dashboard&R&8Made {self.generated}")
        self.sheets["Dashboard"].activate()
        self.sheets["Dashboard"].set_first_sheet()
        wb.close()
        return self.buf.getvalue()

    # ------------------------------------------------------------------ Config
    def write_config(self):
        ws, f, cfg = self.sheets["Config"], self.f, self.cfg
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 30)
        ws.set_column(2, 2, 16)
        ws.set_column(3, 8, 15)
        self.banner(ws, "Settings", "Change the yellow cells - labels, grades and pass checks update everywhere.", 8)
        inp = f.get(bg_color="#FFF6D5", border=1, border_color="#E5C96B", bold=True, align="center")
        r = 4
        ws.write(r, 1, "Rules used for labels and results", f.section())
        rules = [
            ("Pass mark (%)", "PassPct", cfg.rules["pass_percent"], "Below this = not passed."),
            ("Pass each part separately", "PassEachPart", "Yes" if cfg.rules.get("pass_each_part", True) else "No",
             "Yes = theory and practical each need the pass mark."),
            ("Strong: points above own average", "StrongGap", cfg.rules["strong_gap"], ""),
            ("Weak: points below own average", "WeakGap", cfg.rules["weak_gap"], ""),
            ("Needs attention: points below class average", "AttGap", cfg.rules["attention_class_gap"],
             "Also: anything below the pass mark."),
            ("Progress alert: drop of (points)", "DropGap", cfg.rules["drop_alert_gap"],
             "Two drops in a row of at least this many points puts a student on the watch list."),
            ("A blank mark means", "BlankMeans", cfg.rules.get("blank_means", "AB"), "For a subject the student takes."),
        ]
        for i, (label, name, val, note) in enumerate(rules):
            rr = r + 1 + i
            ws.write(rr, 1, label, f.cell())
            if isinstance(val, str):
                ws.write_string(rr, 2, val, inp)
            else:
                ws.write_number(rr, 2, val, inp)
            ws.write(rr, 3, note, f.note())
            self.wb.define_name(name, f"=Config!{rc(rr, 2, True, True)}")
        ws.data_validation(r + 2, 2, r + 2, 2, {"validate": "list", "source": ["Yes", "No"]})
        r = r + len(rules) + 2
        ws.write(r, 1, "Leave codes", f.section())
        r += 1
        for c, h in enumerate(["Code", "Meaning", "Counts as not passed"], 1):
            ws.write(r, c, h, f.header())
        first = r + 1
        for x in cfg.rules["leave_codes"]:
            r += 1
            ws.write_string(r, 1, x["code"], f.cell(bold=True))
            ws.write_string(r, 2, x["label"], f.cell())
            ws.write_string(r, 3, "Yes" if x["counts_as_fail"] else "No", inp)
        self.wb.define_name("LeaveCodes", f"=Config!{rc(first, 1, True, True)}:{rc(r, 1, True, True)}")
        self.wb.define_name("LeaveTable", f"=Config!{rc(first, 1, True, True)}:{rc(r, 3, True, True)}")
        r += 2
        ws.write(r, 1, "Grades (lowest % for each grade)", f.section())
        r += 1
        ws.write(r, 1, "Grade", f.header())
        ws.write(r, 2, "From %", f.header())
        first = r + 1
        for g in sorted(cfg.rules["grades"], key=lambda g: g["min"]):
            r += 1
            ws.write_string(r, 1, g["grade"], f.cell(bold=True))
            ws.write_number(r, 2, g["min"], inp)
        self.wb.define_name("GradeName", f"=Config!{rc(first, 1, True, True)}:{rc(r, 1, True, True)}")
        self.wb.define_name("GradeMin", f"=Config!{rc(first, 2, True, True)}:{rc(r, 2, True, True)}")
        r += 2
        ws.write(r, 1, "Maximum marks (settings on the website)", f.section())
        r += 1
        heads = ["Class", "Subject", "Periodic test", "Big exams"]
        for c, h in enumerate(heads, 1):
            ws.write(r, c, h, f.header())
        ws.merge_range(r, 4, r, 6, "Big exams", f.header())

        def txt(sc):
            if not sc:
                return "not counted"
            t = f"{float(sc['theory']):g}"
            if sc["second"]:
                parts = sc["second"]["parts"]
                t += f" + {float(sc['second']['max']):g} {sc['second']['label'].lower()}"
                if parts:
                    t += " (" + ", ".join(f"{cfg.part_label(k).lower()} {float(m):g}" for k, m in parts) + ")"
                if sc["second"]["optional"]:
                    t += " - optional"
            return t
        for cls in self.classes:
            ex = self.ds.exams_for(cls) or cfg.class_exams(cls)
            pt = next((e for e in ex if cfg.exam_kind(e) == "pt"), None)
            mj = next((e for e in ex if cfg.exam_kind(e) == "major"), None)
            for s in self.ds.subjects_for(cls):
                r += 1
                ws.write_string(r, 1, cfg.class_label(cls), f.cell())
                ws.write_string(r, 2, cfg.subject_name(s), f.cell())
                ws.write_string(r, 3, txt(cfg.scheme(cls, s, pt)) if pt else "-", f.cell(align="center"))
                ws.merge_range(r, 4, r, 6, txt(cfg.scheme(cls, s, mj)) if mj else "-", f.cell())
        r += 2
        ws.write(r, 1, "Exams", f.section())
        r += 1
        ws.write(r, 1, "Class", f.header())
        ws.write(r, 2, "Exams in order", f.header())
        ws.merge_range(r, 3, r, 6, "", f.header())
        for c in cfg.classes:
            r += 1
            ws.write_string(r, 1, cfg.class_label(c), f.cell())
            ws.merge_range(r, 2, r, 6, "  →  ".join(cfg.exam_name(e) for e in cfg.class_exams(c)), f.cell())
        r += 2
        ws.write(r, 1, "About this workbook", f.section())
        info = [("School", cfg.rules["school_name"]), ("Academic year", cfg.rules["academic_year"]),
                ("Made on", self.generated), ("Last recalculated", "")]
        for i, (k, v) in enumerate(info):
            ws.write(r + 1 + i, 1, k, f.cell(bold=True))
            ws.write_string(r + 1 + i, 2, v, f.cell())
            if k == "Last recalculated":
                self.wb.define_name("LastCalc", f"=Config!{rc(r + 1 + i, 2, True, True)}")
        ws.write(r + 6, 1, "These are the school's editable defaults, not official CBSE rules unless the school says so.",
                 f.note())

    # ------------------------------------------------------------------ lists
    def write_lists(self):
        ws, cfg, ds = self.sheets["_lists"], self.cfg, self.ds
        cols = {}

        def column(c, head, values, name=None):
            ws.write_string(0, c, head)
            for i, v in enumerate(values):
                ws.write_string(i + 1, c, str(v))
            cols[head] = (c, len(values))
            if name and values:
                self.wb.define_name(name, f"={_rng('_lists', 1, c, len(values))}")
            return c

        column(0, "Classes", self.classes, "L_Classes")
        column(1, "Exams", [cfg.exam_name(e) for e in self.exams], "L_Exams")
        column(2, "Sections", ["All"] + self.sections, "L_Sections")
        studs = ds.ordered_students()
        column(3, "StudentLabel", [self.labels[s.sid] for s in studs], "L_StudentLabels")
        column(4, "StudentID", [s.sid for s in studs], "L_StudentIDs")
        column(5, "Subjects", [cfg.subject_name(s) for s in self.subjects], "L_Subjects")
        column(6, "SubjectsAll", ["All subjects"] + [cfg.subject_name(s) for s in self.subjects], "L_SubjectsAll")
        # exam list per class (for report card trend)
        for i, c in enumerate(self.classes):
            col = 8 + i
            ws.write_string(0, col, c)
            ex = ds.exams_for(c)
            for j, e in enumerate(ex):
                ws.write_string(j + 1, col, cfg.exam_name(e))
        self.class_exam_cols = {c: 8 + i for i, c in enumerate(self.classes)}
        self.wb.define_name("L_ClassHeads", f"={_rng('_lists', 0, 8, 0, 8 + max(0, len(self.classes) - 1))}")
        self.max_exams = max((len(ds.exams_for(c)) for c in self.classes), default=1)
        self.wb.define_name("L_ClassExams", f"={_rng('_lists', 1, 8, self.max_exams, 8 + max(0, len(self.classes) - 1))}")

    # ------------------------------------------------------------------ Student Master
    def write_master(self):
        ws, f, cfg, ds = self.sheets["Student Master"], self.f, self.cfg, self.ds
        studs = ds.ordered_students()
        self.max_subjects = max([len(s.subjects) for s in studs] + [5])
        heads = ["Student ID", "Admission No", "Roll No", "Board Roll No", "Name", "Father's Name", "Mother's Name",
                 "Class", "Section", "Group", "Group note"] + [f"Subject {i + 1}" for i in range(self.max_subjects)]
        if any(s.gender for s in studs):
            heads.append("Gender")
        widths = [10, 12, 8, 13, 24, 22, 22, 7, 8, 7, 28] + [17] * self.max_subjects + [8]
        ws.freeze_panes(1, 5)
        ws.set_row(0, 30)
        for c, h in enumerate(heads):
            ws.write(0, c, h, f.header())
            ws.set_column(c, c, widths[c] if c < len(widths) else 12)
        for i, s in enumerate(studs):
            r = i + 1
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            vals = [s.sid, s.adm_no, s.roll, s.board_roll, s.name, s.father, s.mother, s.cls, s.section, s.group,
                    s.group_note] + [cfg.subject_name(x) for x in s.subjects] + [""] * (self.max_subjects - len(s.subjects))
            if "Gender" in heads:
                vals.append(s.gender)
            for c, v in enumerate(vals):
                fmt = f.cell(quote_prefix=True, **band) if formula_like(v) else f.cell(**band)
                ws.write_string(r, c, str(v), fmt)
        n = len(studs)
        ws.autofilter(0, 0, max(1, n), len(heads) - 1)
        self.wb.define_name("SM_ID", f"={_rng('Student Master', 1, 0, n)}")
        self.wb.define_name("SM_Table", f"={_rng('Student Master', 1, 0, n, len(heads) - 1)}")
        self.sm_cols = {h: i for i, h in enumerate(heads)}

    # ------------------------------------------------------------------ marks sheets + Subject Results
    def plan_entry_sheets(self):
        """One marks sheet per class (and per subject combination in XI-XII), so every sheet only has
        the subjects its students take. Subjects not shared by everybody (a language, an elective)
        go into one 'Language' / 'Elective' column whose subject is named on each row."""
        cfg, ds, res = self.cfg, self.ds, self.res
        groups = {}
        for k in self.order:
            st = ds.students[k[0]]
            groups.setdefault((st.cls, st.combo), []).append(k)
        cls_rank = {c: i for i, c in enumerate(cfg.classes)}
        specs = []
        used_names = set(self.sheets) | {OV, "Dashboard", "Report Card", "Subject Analysis", "Marks Analysis", "Progress",
                                         "Subject Results", "Student Master", "Validation Report", "Config", "Source Data",
                                         "Teachers", "My Charts"}
        for (cls, combo), keys in sorted(groups.items(), key=lambda x: (cls_rank.get(x[0][0], 99), x[0][1])):
            sids = list(dict.fromkeys(k[0] for k in keys))
            rows = [r for k in keys for r in res.exam_results[k].rows]
            subjects = cfg.order_subjects({r.subject for r in rows})
            core, slots, slot_of = _slot_plan(cfg, cls, [ds.students[s] for s in sids], subjects)
            name = _sheet_name(f"Marks {cls or '(no class)'}" + (f" {COMBO_SHORT.get(combo, combo)}" if combo else ""),
                               used_names)
            used_names.add(name)
            spec = {"name": name, "cls": cls, "combo": combo, "keys": keys, "core": core, "slots": slots, "slot_of": slot_of}
            # which subject / slot needs a column for a typed second part (practical, or a single internal mark)
            direct = set()
            for r in rows:
                if r.pr_max and not r.is_total and not r.parts:
                    direct.add(r.subject)
            spec["direct"] = direct
            specs.append(spec)
            # internal marks typed in parts -> a separate Internals sheet for this class (one per class)
        int_specs = []
        by_cls = {}
        for k in self.order:
            st = ds.students[k[0]]
            if any(r.parts for r in res.exam_results[k].rows):
                by_cls.setdefault(st.cls, []).append(k)
        for cls in sorted(by_cls, key=lambda c: cls_rank.get(c, 99)):
            keys = by_cls[cls]
            sids = list(dict.fromkeys(k[0] for k in keys))
            rows = [r for k in keys for r in res.exam_results[k].rows if r.parts]
            subjects = cfg.order_subjects({r.subject for r in rows})
            core, slots, slot_of = _slot_plan(cfg, cls, [ds.students[s] for s in sids], subjects)
            # parts per subject (the scheme's order); one set of part columns per subject / slot
            parts_of = {}
            for r in rows:
                keys_ = [kk for kk, _ in cfg.subparts(cls, r.subject, r.exam)]
                parts_of.setdefault(r.subject, [])
                for kk in keys_:
                    if kk not in parts_of[r.subject]:
                        parts_of[r.subject].append(kk)
            name = _sheet_name(f"Internals {cls}", used_names)
            used_names.add(name)
            int_specs.append({"name": name, "cls": cls, "keys": keys, "core": core, "slots": slots, "parts_of": parts_of,
                              "slot_of": slot_of})
        self.entry_specs, self.int_specs = specs, int_specs
        return [s["name"] for s in specs] + [s["name"] for s in int_specs]

    def write_matrix_and_results(self):
        cfg, ds, res, f = self.cfg, self.ds, self.res, self.f
        ov, sr = self.sheets[OV], self.sheets["Subject Results"]
        c_obt, c_max, c_ov, c_res, c_rank, c_sheet = 8, 9, 10, 11, 12, 13
        self.mx_cols = {"obt": c_obt, "max": c_max, "overall": c_ov, "result": c_res, "rank": c_rank}
        last_col = c_sheet
        self.banner(ov, "Overview",
                    "One row per student per exam: totals, overall %, result and rank. Type or correct marks in the "
                    "'Marks ...' sheets - everything here updates.", last_col, logo=False)
        heads = ["Key", "Student ID", "Roll", "Name", "Class", "Section", "Group", "Exam", "Total", "Max", "Overall %",
                 "Result", "Class Rank", "Marks are in"]
        hr = MX_HEADER_ROW
        ov.set_row(hr, 30)
        for c, h in enumerate(heads):
            ov.write(hr, c, h, f.header())
        ov.set_column(0, 0, 18, None, {"hidden": True})
        ov.set_column(1, 1, 9)
        ov.set_column(2, 2, 5)
        ov.set_column(3, 3, 24)
        ov.set_column(4, 6, 6.5)
        ov.set_column(7, 7, 14)
        ov.set_column(c_obt, c_max, 7)
        ov.set_column(c_ov, c_ov, 10)
        ov.set_column(c_res, c_res, 11)
        ov.set_column(c_rank, c_rank, 7)
        ov.set_column(c_sheet, c_sheet, 20)
        ov.freeze_panes(MX_FIRST, 4)

        # Subject Results header
        sr.freeze_panes(1, 3)
        sr.set_row(0, 30)
        for c, h in enumerate(SR_COLS):
            sr.write(0, c, h, f.header())
        widths = [24, 9, 22, 6, 7, 6, 13, 6, 18, 7, 7, 9, 9, 10, 8, 6, 7, 6, 7, 9, 9, 9, 9, 14, 70, 8, 9]
        for c, w in enumerate(widths):
            sr.set_column(c, c, w)
        sr.set_column(SR_KEY, SR_KEY, 24, None, {"hidden": True})

        n_sr = sum(len(res.exam_results[k].rows) for k in self.order)
        self.n_sr = n_sr
        S = "Subject Results"
        for name, c in [("SR_Key", SR_KEY), ("SR_ID", SR_ID), ("SR_Class", SR_CLASS), ("SR_Section", SR_SEC),
                        ("SR_Group", SR_GROUP), ("SR_Exam", SR_EXAM), ("SR_Subject", SR_SUBJ), ("SR_Th", SR_TH),
                        ("SR_Pr", SR_PR), ("SR_Status", SR_STATUS), ("SR_Obt", SR_OBT), ("SR_Max", SR_MAX),
                        ("SR_Pct", SR_PCT), ("SR_Grade", SR_GRADE), ("SR_Passed", SR_PASSED), ("SR_Label", SR_LABEL),
                        ("SR_ClassAvg", SR_CAVG), ("SR_Reason", SR_REASON), ("SR_ThPct", SR_THP), ("SR_PrPct", SR_PRP),
                        ("SR_VOwn", SR_VOWN)]:
            self.wb.define_name(name, f"={_rng(S, 1, c, max(1, n_sr))}")
        n_mx = len(self.order)
        self.n_mx = n_mx
        for name, c in [("MX_Key", 0), ("MX_ID", 1), ("MX_Name", 3), ("MX_Class", 4), ("MX_Section", 5),
                        ("MX_Group", 6), ("MX_Exam", 7), ("MX_Obt", c_obt), ("MX_Max", c_max), ("MX_Overall", c_ov),
                        ("MX_Result", c_res), ("MX_Rank", c_rank)]:
            self.wb.define_name(name, f"={_rng(OV, MX_FIRST, c, MX_FIRST + max(1, n_mx) - 1)}")

        # class averages are on the hidden _stats sheet; index them so SR rows can point at them
        self.stats_index = {}
        keys = sorted(res.class_avg.keys(), key=lambda k: (self.classes.index(k[0]) if k[0] in self.classes else 99,
                                                            cfg.exam_order(k[0], k[1]), self.subjects.index(k[2])
                                                            if k[2] in self.subjects else 99))
        for i, k in enumerate(keys):
            self.stats_index[k] = i + 1
        self.stats_keys = keys

        self.mx_row_of = {k: MX_FIRST + i for i, k in enumerate(self.order)}
        self.sr_row_of = {}
        self.cells = []              # [sheet, row, col, sid, exam, subject, component] of every typed mark
        self.validations = {}        # (sheet, col, max) -> rows
        refs = {}                    # (sid, exam, subject) -> {"th": ref, "pr": ref}
        sheet_of = {}
        for spec in self.entry_specs:
            self.write_entry_sheet(spec, refs)
            for k in spec["keys"]:
                sheet_of[k] = spec["name"]
        for spec in self.int_specs:
            self.write_internals_sheet(spec, refs)

        # Overview rows + Subject Results rows
        cell_c = f.cell(align="center")
        txt = f.cell()
        ce_first = {}
        for i, k in enumerate(self.order):
            st = ds.students[k[0]]
            ce_first.setdefault((st.cls, k[1]), [i, i])[1] = i
        sr_row = 1
        for i, k in enumerate(self.order):
            sid, exam = k
            st = ds.students[sid]
            er = res.exam_results[k]
            r = MX_FIRST + i
            band = i % 2 == 1
            ex_name = cfg.exam_name(exam)
            ov.write_string(r, 0, f"{sid}|{ex_name}", txt)
            for c, v in [(1, sid), (2, st.roll), (3, st.name), (4, st.cls), (5, st.section), (6, st.group), (7, ex_name)]:
                fmt = f.cell(bg_color=theme.TINT2, quote_prefix=formula_like(v)) if band else \
                    f.cell(quote_prefix=formula_like(v))
                ov.write_string(r, c, str(v), fmt)
            first = sr_row
            last = sr_row + len(er.rows) - 1
            for row in er.rows:
                self.sr_row_of[(sid, exam, row.subject)] = sr_row
                self.write_sr_row(sr, sr_row, row, st, ex_name, i, refs.get((sid, exam, row.subject), {}), first, last)
                sr_row += 1
            stat = _rng(S, first, SR_STATUS, last).replace("$", "")
            obt = _rng(S, first, SR_OBT, last).replace("$", "")
            mxr = _rng(S, first, SR_MAX, last).replace("$", "")
            pas = _rng(S, first, SR_PASSED, last).replace("$", "")
            ov.write_formula(r, c_obt, f'=IF(COUNTIF({stat},"OK")=0,"",SUMIF({stat},"OK",{obt}))',
                             f.num(2 if er.obtained is not None and er.obtained % 1 else 0, bold=True), _num(er.obtained))
            ov.write_formula(r, c_max, f'=IF(COUNTIF({stat},"OK")=0,"",SUMIF({stat},"OK",{mxr}))', f.num(0), _num(er.max))
            o, m_ = rc(r, c_obt), rc(r, c_max)
            ov.write_formula(r, c_ov, f'=IF(N({m_})=0,"",ROUND({o}/{m_}*100,6))',
                             f.num(2, bold=True, font_color=theme.NAVY), _num(er.overall))
            ov.write_formula(r, c_res, f'=IF(COUNTIF({pas},"No")>0,"Not passed",IF(COUNTIF({stat},"OK")>0,"Pass",""))',
                             cell_c, er.result)
            a, b = ce_first[(st.cls, exam)]
            ovc = rc(r, c_ov)
            blockr = f"{rc(MX_FIRST + a, c_ov, True, True)}:{rc(MX_FIRST + b, c_ov, True, True)}"
            ov.write_formula(r, c_rank, f'=IF({ovc}="","",COUNTIF({blockr},">"&{ovc})+1)', cell_c,
                             er.rank if er.rank is not None else "")
            sh = sheet_of.get(k, "")
            if sh:
                ov.write_url(r, c_sheet, f"internal:{_q(sh)}!A1", f.cell(font_color=theme.BLUE, underline=1), sh)
        # entry validation: number 0..max or a leave code
        for (sheet, c, mxv), rows in self.validations.items():
            ws = self.sheets[sheet]
            rows.sort()
            runs = []
            for rr in rows:
                if runs and rr == runs[-1][1] + 1:
                    runs[-1][1] = rr
                else:
                    runs.append([rr, rr])
            for a, b in runs:
                top = rc(a, c)
                ws.data_validation(a, c, b, c, {
                    "validate": "custom", "value": f"=OR(AND(ISNUMBER({top}),{top}>=0,{top}<={mxv}),COUNTIF(LeaveCodes,{top})>0)",
                    "ignore_blank": True, "error_title": "Check this mark",
                    "error_message": f"Type a number from 0 to {mxv}, or a leave code (AB, ML, DL, EX, NA).",
                    "input_title": "Marks", "input_message": f"Out of {mxv}, or AB / ML / DL / EX / NA"})
        last_r = MX_FIRST + max(1, n_mx) - 1
        ov.autofilter(MX_HEADER_ROW, 0, last_r, last_col)
        ov.conditional_format(MX_FIRST, c_ov, last_r, c_ov, {"type": "data_bar", "bar_color": "#9FDCF5", "bar_solid": True,
                                                            "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 100})
        ov.conditional_format(MX_FIRST, c_res, last_r, c_res, {"type": "cell", "criteria": "==", "value": '"Not passed"',
                                                              "format": f.get(font_color=theme.RED, bold=True)})
        sl = max(1, n_sr)
        sr.autofilter(0, 0, sl, len(SR_COLS) - 1)
        for label, (fg, bg) in theme.LABEL_COLORS.items():
            if label == "On track":
                continue
            sr.conditional_format(1, SR_LABEL, sl, SR_LABEL, {"type": "cell", "criteria": "==", "value": f'"{label}"',
                                                              "format": self.wb.add_format({"font_color": fg, "bg_color": bg,
                                                                                            "bold": True})})

    # ---- one marks sheet --------------------------------------------------------------------------
    def _mark_cell(self, ws, sheet, r, c, kind, value, raw, code, mx, fmt, sid, exam, subject, comp, total_note=False):
        f = self.f
        if kind == "number":
            ws.write_number(r, c, float(value), fmt)
        elif kind == "leave":
            ws.write_string(r, c, code, f.cell(align="center", font_color=theme.AMBER, bold=True))
        elif kind == "invalid":
            ws.write_string(r, c, f"{raw} ⚠", f.cell(align="center", bg_color=theme.RED_BG, font_color=theme.RED, bold=True))
        else:
            ws.write_blank(r, c, None, fmt)
        if total_note:
            ws.write_comment(r, c, "Total (both parts were not given separately).")
        self.validations.setdefault((sheet, c, float(mx) if float(mx) % 1 else int(mx)), []).append(r)
        self.cells.append([sheet, r, c, sid, exam, subject, comp])
        return f"{_q(sheet)}!{rc(r, c)}"

    def write_entry_sheet(self, spec, refs):
        cfg, ds, res, f = self.cfg, self.ds, self.res, self.f
        name = spec["name"]
        ws = self.sheets[name]
        cls = spec["cls"]
        streams = cfg.has_streams(cls)
        # columns: (kind, subject or slot index, component, heading)
        cols = []
        for s in spec["core"]:
            if s in spec["direct"]:
                lab = cfg.second_label(cls, s, next((k[1] for k in spec["keys"] if cfg.exam_kind(k[1]) == "major"), "HY")) or "Practical"
                cols.append(("mark", s, "theory", f"{cfg.subject_short(s)} {'Th' if streams else 'W'}"))
                cols.append(("mark", s, "practical", f"{cfg.subject_short(s)} {'Pr' if lab == 'Practical' else 'Int'}"))
            else:
                cols.append(("mark", s, "theory", cfg.subject_short(s)))
        for i, slot in enumerate(spec["slots"]):
            cols.append(("slotname", i, None, slot["title"]))
            if slot["subjects"] & spec["direct"]:
                cols.append(("slot", i, "theory", f"{slot['short']} {'Th' if streams else 'W'}"))
                cols.append(("slot", i, "practical", f"{slot['short']} {'Pr' if streams else 'Int'}"))
            else:
                cols.append(("slot", i, "theory", f"{slot['short']} marks"))
        base = 6
        c_ov = base + len(cols)
        c_res = c_ov + 1
        self.banner(ws, name, f"{cfg.class_label(cls)}{' · ' + spec['combo'] if spec['combo'] else ''}: one row per "
                              f"student per exam. Type or correct marks here (numbers, or AB / ML / DL / EX / NA) - "
                              f"everything else updates. Grey = not part of this exam.", c_res, logo=False)
        heads = ["Key", "Student ID", "Roll", "Name", "Section", "Exam"] + [h for _, _, _, h in cols] + ["Overall %", "Result"]
        hr = MX_HEADER_ROW
        ws.set_row(hr, 34)
        for c, h in enumerate(heads):
            fmt = f.header()
            if base <= c < c_ov:
                kind, s, comp, _ = cols[c - base]
                fmt = f.get(bold=True, font_color=theme.WHITE, align="center", text_wrap=True, border=1,
                            border_color=theme.NAVY, bg_color=theme.BLUE if comp in ("theory", None) and kind != "slotname"
                            else ("#5B7A93" if kind == "slotname" else "#3E7CA6"))
                if kind == "mark":
                    ws.write_comment(hr, c, f"{cfg.subject_name(s)} - {'written' if comp == 'theory' and not streams else comp}",
                                     {"x_scale": 1.2, "y_scale": 0.5})
                elif kind == "slotname":
                    ws.write_comment(hr, c, "Each student's own " + spec["slots"][s]["title"].lower() +
                                     " (the marks next to it are in this subject)", {"x_scale": 1.6, "y_scale": 0.6})
            ws.write(hr, c, h, fmt)
        ws.set_column(0, 0, 18, None, {"hidden": True})
        ws.set_column(1, 1, 9)
        ws.set_column(2, 2, 5)
        ws.set_column(3, 3, 24)
        ws.set_column(4, 4, 7)
        ws.set_column(5, 5, 14)
        for i, (kind, s, comp, h) in enumerate(cols):
            ws.set_column(base + i, base + i, 11 if kind == "slotname" else 7)
        ws.set_column(c_ov, c_ov, 10)
        ws.set_column(c_res, c_res, 11)
        ws.freeze_panes(MX_FIRST, 4)
        na_fmt = f.cell(bg_color=theme.GREY_BG)
        for i, k in enumerate(spec["keys"]):
            sid, exam = k
            st = ds.students[sid]
            er = res.exam_results[k]
            r = MX_FIRST + i
            band = i % 2 == 1
            idf = f.cell(bg_color=theme.TINT2) if band else f.cell()
            ex_name = cfg.exam_name(exam)
            ws.write_string(r, 0, f"{sid}|{ex_name}", idf)
            for c, v in [(1, sid), (2, st.roll), (3, st.name), (4, st.section), (5, ex_name)]:
                ws.write_string(r, c, str(v), f.cell(quote_prefix=formula_like(v), **({"bg_color": theme.TINT2} if band else {})))
            by = {row.subject: row for row in er.rows}
            slot_subj = {i2: next((x for x in st.subjects if x in sl["subjects"] and x not in spec["core"]
                                   and _slot_index(spec, st, x) == i2), None) for i2, sl in enumerate(spec["slots"])}
            cfmt = f.cell(align="center", bg_color=theme.TINT2) if band else f.cell(align="center")
            for j, (kind, s, comp, h) in enumerate(cols):
                c = base + j
                if kind == "slotname":
                    sub = slot_subj.get(s)
                    ws.write_string(r, c, cfg.subject_name(sub) if sub else "", f.cell(font_color="#5B7A93", italic=True,
                                                                                    **({"bg_color": theme.TINT2} if band else {})))
                    continue
                subject = s if kind == "mark" else slot_subj.get(s)
                row = by.get(subject) if subject else None
                if row is None or (comp == "practical" and (row.is_total or not row.pr_max or row.parts)):
                    ws.write_blank(r, c, None, na_fmt)
                    continue
                if comp == "theory":
                    m = next((x for x in row.marks if x.component in ("theory", "total")), None)
                    ref = self._mark_cell(ws, name, r, c, row.th_kind, row.th, row.th_raw, m.code if m else "",
                                          row.th_max, cfmt, sid, exam, subject, "total" if row.is_total else "theory",
                                          total_note=row.is_total)
                    refs.setdefault((sid, exam, subject), {})["th"] = ref
                else:
                    m = next((x for x in row.marks if x.component == "practical"), None)
                    ref = self._mark_cell(ws, name, r, c, row.pr_kind, row.pr, row.pr_raw, m.code if m else "",
                                          row.pr_max, cfmt, sid, exam, subject, "practical")
                    refs.setdefault((sid, exam, subject), {})["pr"] = ref
            orow = self.mx_row_of[k]
            ws.write_formula(r, c_ov, f"={_q(OV)}!{rc(orow, self.mx_cols['overall'])}",
                             f.num(2, bold=True, font_color=theme.NAVY, **({"bg_color": theme.TINT2} if band else {})),
                             _num(er.overall))
            ws.write_formula(r, c_res, f"={_q(OV)}!{rc(orow, self.mx_cols['result'])}",
                             f.cell(align="center", **({"bg_color": theme.TINT2} if band else {})), er.result)
        last_r = MX_FIRST + max(1, len(spec["keys"])) - 1
        ws.autofilter(MX_HEADER_ROW, 0, last_r, c_res)
        ws.conditional_format(MX_FIRST, c_res, last_r, c_res, {"type": "cell", "criteria": "==", "value": '"Not passed"',
                                                              "format": f.get(font_color=theme.RED, bold=True)})
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(MX_HEADER_ROW)

    def write_internals_sheet(self, spec, refs):
        """Internal assessment typed in parts (portfolio / project / notebook, AI practical parts). The PT part is a
        formula from the periodic test on the marks sheet; 'Total' adds the parts (or says what is missing)."""
        cfg, ds, res, f = self.cfg, self.ds, self.res, self.f
        name = spec["name"]
        ws = self.sheets[name]
        cls = spec["cls"]
        groups = []                  # (title, kind, subject or slot index, [part keys])
        for s in spec["core"]:
            if spec["parts_of"].get(s):
                groups.append((cfg.subject_short(s), "mark", s, spec["parts_of"][s]))
        for i, slot in enumerate(spec["slots"]):
            keys = []
            for s in slot["subjects"]:
                for kk in spec["parts_of"].get(s, []):
                    if kk not in keys:
                        keys.append(kk)
            groups.append((slot["short"], "slot", i, keys))
        base = 6
        cols = []                    # (group index, part key | 'slotname' | 'total')
        for gi, (title, kind, s, keys) in enumerate(groups):
            if kind == "slot":
                cols.append((gi, "slotname"))
            for kk in keys:
                cols.append((gi, kk))
            cols.append((gi, "total"))
        self.banner(ws, name, f"{cfg.class_label(cls)}: internal assessment (and AI practical) in parts. Type the "
                              f"parts; the PT part comes from the periodic test by itself, and Total adds them up "
                              f"(INC = a part is missing).", base + len(cols), logo=False)
        hr = MX_HEADER_ROW + 1          # subject names on the row above the part names
        ws.set_row(hr - 1, 18)
        ws.set_row(hr, 32)
        for c, h in enumerate(["Key", "Student ID", "Roll", "Name", "Section", "Exam"]):
            ws.write(hr, c, h, f.header())
        # subject names over their parts
        gi_cols = {}
        for j, (gi, kk) in enumerate(cols):
            gi_cols.setdefault(gi, []).append(base + j)
        for gi, cs in gi_cols.items():
            fmt = f.get(bold=True, font_color=theme.WHITE, bg_color=theme.BLUE if gi % 2 == 0 else theme.NAVY,
                        align="center", border=1, border_color=theme.NAVY)
            if len(cs) > 1:
                ws.merge_range(hr - 1, cs[0], hr - 1, cs[-1], groups[gi][0], fmt)
            else:
                ws.write(hr - 1, cs[0], groups[gi][0], fmt)
        short = {"i_pt": "PT", "i_portfolio": "Portfolio", "i_project": "Project", "i_notebook": "Notebook",
                 "p_viva": "Viva", "p_notebook": "Notebook", "p_file": "File", "p_test": "Test"}
        for j, (gi, kk) in enumerate(cols):
            c = base + j
            h = {"slotname": groups[gi][0], "total": "Total"}.get(kk, short.get(kk, cfg.part_label(kk)))
            ws.write(hr, c, h, f.header() if kk not in ("total", "i_pt") else
                     f.get(bold=True, font_color=theme.WHITE, bg_color="#5B7A93", align="center", text_wrap=True, border=1,
                           border_color=theme.NAVY))
            if kk == "i_pt":
                ws.write_comment(hr, c, "Worked out from the periodic test: PT marks ÷ PT maximum × 5 (absent = 0).",
                                 {"x_scale": 1.6, "y_scale": 0.6})
            ws.set_column(c, c, 11 if kk == "slotname" else (7 if kk == "total" else 8.5))
        ws.set_column(0, 0, 18, None, {"hidden": True})
        ws.set_column(1, 1, 9)
        ws.set_column(2, 2, 5)
        ws.set_column(3, 3, 24)
        ws.set_column(4, 4, 7)
        ws.set_column(5, 5, 14)
        ws.freeze_panes(hr + 1, 4)
        na_fmt = f.cell(bg_color=theme.GREY_BG)
        r = hr
        for k in spec["keys"]:
            sid, exam = k
            st = ds.students[sid]
            er = res.exam_results[k]
            r += 1
            band = (r - hr - 1) % 2 == 1
            bg = {"bg_color": theme.TINT2} if band else {}
            ex_name = cfg.exam_name(exam)
            ws.write_string(r, 0, f"{sid}|{ex_name}", f.cell(**bg))
            for c, v in [(1, sid), (2, st.roll), (3, st.name), (4, st.section), (5, ex_name)]:
                ws.write_string(r, c, str(v), f.cell(quote_prefix=formula_like(v), **bg))
            by = {row.subject: row for row in er.rows}
            cfmt = f.cell(align="center", **bg)
            for gi, (title, kind, s, keys) in enumerate(groups):
                cs = gi_cols[gi]
                if kind == "slot":
                    subject = next((x for x in st.subjects if x in spec["slots"][s]["subjects"] and x not in spec["core"]
                                    and _slot_index(spec, st, x) == s), None)
                else:
                    subject = s
                row = by.get(subject) if subject else None
                j0 = 0
                if kind == "slot":
                    ws.write_string(r, cs[0], cfg.subject_name(subject) if subject else "",
                                    f.cell(font_color="#5B7A93", italic=True, **bg))
                    j0 = 1
                if row is None or not row.parts:
                    for c in cs[j0:]:
                        ws.write_blank(r, c, None, na_fmt)
                    continue
                part_refs, entered = [], []
                scheme_keys = dict(cfg.subparts(cls, subject, exam))
                for kk, c in zip(keys, cs[j0:-1]):
                    if kk not in scheme_keys:
                        ws.write_blank(r, c, None, na_fmt)
                        continue
                    cell = rc(r, c)
                    if kk == "i_pt" and kk not in {m.component for m in row.marks}:
                        val = row.parts.get(kk, (None, None))[0]
                        pt_ref = refs.get((sid, row.pt_from, subject), {}).get("th")
                        pt_row = res.exam_results.get((sid, row.pt_from))
                        pt_r = next((x for x in pt_row.rows if x.subject == subject), None) if pt_row else None
                        if pt_ref and pt_r is not None:
                            full = pt_r.th_max
                            pm = scheme_keys[kk]
                            ws.write_formula(r, c, f'=IF(ISNUMBER({pt_ref}),{pt_ref}/{_n(full)}*{_n(pm)},'
                                                   f'IF(OR({pt_ref}="",AND(ISTEXT({pt_ref}),COUNTIF(LeaveCodes,{pt_ref})>0)),0,"⚠"))',
                                             f.num(2, font_color="#5B7A93", **bg),
                                             float(val) if val is not None else "⚠")
                        else:
                            ws.write_blank(r, c, None, f.cell(**bg))
                        part_refs.append((cell, True))
                        continue
                    m = next((x for x in row.marks if x.component == kk), None)
                    self._mark_cell(ws, name, r, c, m.kind if m else "blank", m.value if m else None, m.raw if m else "",
                                    m.code if m else "", scheme_keys[kk], cfmt, sid, exam, subject, kk)
                    part_refs.append((cell, False))
                    entered.append(cell)
                # Total = the parts combined, exactly like calc.combine
                allnum = ",".join(f"ISNUMBER({p})" for p, _ in part_refs)
                summ = "+".join(p for p, _ in part_refs)
                blank = ",".join(f'{p}=""' for p in entered) or "FALSE"
                leave = "".join(f'IF(AND(ISTEXT({p}),COUNTIF(LeaveCodes,{p})>0),UPPER({p}),' for p, d in part_refs if not d)
                close = ")" * sum(1 for p, d in part_refs if not d)
                bad = ",".join(f'AND(ISTEXT({p}),{p}<>"")' for p, _ in part_refs)
                formula = (f'=IF(AND({allnum}),{summ},IF(AND({blank}),"",{leave}IF(OR({bad}),"⚠","INC"){close}))')
                cached = {"number": _num(row.pr), "blank": "", "leave": row.pr_code, "invalid": "⚠",
                          "partial": "INC"}[row.pr_kind]
                tc = cs[-1]
                ws.write_formula(r, tc, formula, f.num(2, bold=True, font_color=theme.NAVY, **bg), cached)
                refs.setdefault((sid, exam, subject), {})["pr"] = f"{_q(name)}!{rc(r, tc)}"
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(hr - 1, hr)

    def write_sr_row(self, sr, r, row, st, ex_name, band_i, refs, first, last):
        f, cfg = self.f, self.cfg
        c = rc
        band = {"bg_color": theme.TINT2} if band_i % 2 else {}
        tf = f.cell(**band)
        cf = f.cell(align="center", **band)
        n1, n2 = f.num(2, **band), f.num(2, **band)
        subj = cfg.subject_name(row.subject)
        sr.write_string(r, SR_KEY, f"{st.sid}|{ex_name}|{subj}", tf)
        sr.write_string(r, SR_ID, st.sid, tf)
        sr.write_string(r, SR_NAME, st.name, f.cell(quote_prefix=formula_like(st.name), **band))
        sr.write_string(r, SR_CLASS, st.cls, cf)
        sr.write_string(r, SR_SEC, st.section, cf)
        sr.write_string(r, SR_GROUP, st.group, cf)
        sr.write_string(r, SR_EXAM, ex_name, tf)
        sr.write_number(r, SR_EXNO, cfg.exam_order(st.cls, row.exam), cf)
        sr.write_string(r, SR_SUBJ, subj, tf)
        thc = refs.get("th")
        th_val = float(row.th) if row.th is not None else ("" if row.th_kind == "blank" else
                                                            (next((m.code for m in row.marks if m.component in ("theory", "total")), "")
                                                             if row.th_kind == "leave" else f"{row.th_raw} ⚠"))
        if thc:
            sr.write_formula(r, SR_TH, f'=IF(ISBLANK({thc}),"",{thc})', cf, th_val)
        else:
            sr.write_string(r, SR_TH, "", cf)
        sr.write_number(r, SR_THMAX, float(row.th_max), cf)
        if row.pr_max:
            prc = refs.get("pr")
            if row.parts:
                pr_val = {"number": _num(row.pr), "blank": "", "leave": row.pr_code, "invalid": "⚠", "partial": "INC"}[row.pr_kind]
            else:
                pr_val = float(row.pr) if row.pr is not None else ("" if row.pr_kind == "blank" else
                                                                    (row.pr_code if row.pr_kind == "leave" else f"{row.pr_raw} ⚠"))
            if prc:
                sr.write_formula(r, SR_PR, f'=IF(ISBLANK({prc}),"",{prc})', cf, pr_val)
            else:
                sr.write_string(r, SR_PR, "", cf)
        else:
            sr.write_string(r, SR_PR, "", cf)
        sr.write_number(r, SR_PRMAX, float(row.pr_max), cf)
        J, K, L, Mx = c(r, SR_TH), c(r, SR_THMAX), c(r, SR_PR), c(r, SR_PRMAX)
        N, O, P, Q = c(r, SR_STATUS), c(r, SR_OBT), c(r, SR_MAX), c(r, SR_PCT)
        S, T, U, V, W, X = c(r, SR_PASSED), c(r, SR_OWN), c(r, SR_CAVG), c(r, SR_VOWN), c(r, SR_VCLS), c(r, SR_LABEL)
        I = c(r, SR_SUBJ)
        sr.write_formula(r, SR_STATUS,
                         f'=IF(AND(ISNUMBER({J}),OR({Mx}=0,ISNUMBER({L}))),"OK",'
                         f'IF(AND({J}="",OR({Mx}=0,{L}="")),BlankMeans,'
                         f'IF(AND(ISTEXT({J}),{J}<>"",COUNTIF(LeaveCodes,{J})>0),UPPER({J}),'
                         f'IF(AND({Mx}>0,ISTEXT({L}),{L}<>"",COUNTIF(LeaveCodes,{L})>0),UPPER({L}),'
                         f'IF(OR(AND(ISTEXT({J}),{J}<>""),AND({Mx}>0,ISTEXT({L}),{L}<>"",{L}<>"INC")),"INVALID","INCOMPLETE")))))',
                         cf, row.status)
        sr.write_formula(r, SR_OBT, f'=IF({N}="OK",{J}+IF({Mx}=0,0,{L}),"")',
                         n1 if row.obtained is not None and row.obtained % 1 else cf, _num(row.obtained))
        sr.write_formula(r, SR_MAX, f"={K}+{Mx}", cf, float(row.max))
        sr.write_formula(r, SR_PCT, f'=IF({N}="OK",{O}/{P}*100,"")', n2, _num(row.pct))
        sr.write_formula(r, SR_GRADE, f'=IF({Q}="","",LOOKUP(ROUND({Q},6),GradeMin,GradeName))', cf, row.grade or "")
        sr.write_formula(r, SR_PASSED,
                         f'=IF({N}="OK",IF(IF(PassEachPart="Yes",AND(ROUND({J}/{K}*100,6)>=PassPct,'
                         f'IF({Mx}=0,TRUE,ROUND({L}/{Mx}*100,6)>=PassPct)),ROUND({Q},6)>=PassPct),"Yes","No"),'
                         f'IF(IFERROR(VLOOKUP({N},LeaveTable,3,FALSE),"No")="Yes","No",""))', cf, row.passed or "")
        blk = f"{c(first, SR_STATUS, True, False)}:{c(last, SR_STATUS, True, False)}"
        blkq = f"{c(first, SR_PCT, True, False)}:{c(last, SR_PCT, True, False)}"
        blkp = f"{c(first, SR_PASSED, True, False)}:{c(last, SR_PASSED, True, False)}"
        sr.write_formula(r, SR_OWN, f'=IF({N}="OK",AVERAGEIF({blk},"OK",{blkq}),"")', n2, _num(row.own_avg))
        si = self.stats_index.get((st.cls, row.exam, row.subject))
        sr.write_formula(r, SR_CAVG, f"=_stats!{c(si, 3)}" if si else '=""', n2, _num(row.class_avg))
        sr.write_formula(r, SR_VOWN, f'=IF({N}="OK",{Q}-{T},"")', n2, _num(row.vs_own))
        sr.write_formula(r, SR_VCLS, f'=IF(AND({N}="OK",ISNUMBER({U})),{Q}-{U},"")', n2, _num(row.vs_class))
        # below the pass mark somewhere in this exam -> only the subjects below the pass mark are "Needs attention"
        sr.write_formula(r, SR_LABEL,
                         f'=IF({N}<>"OK",IF({N}="INVALID","Check marks",IF({N}="INCOMPLETE","Incomplete",'
                         f'IFERROR(VLOOKUP({N},LeaveTable,2,FALSE),{N}))),'
                         f'IF(OR({S}="No",AND(COUNTIF({blkp},"No")=0,ROUND({W},6)<=-AttGap)),"Needs attention",'
                         f'IF(ROUND({V},6)>=StrongGap,"Strong",IF(ROUND({V},6)<=-WeakGap,"Weak","On track"))))',
                         cf, row.label)
        sr.write_formula(r, SR_REASON,
                         f'=IF({N}<>"OK",{I}&": "&{X},{I}&": "&IF({S}="No","below the pass mark; ","")'
                         f'&TEXT(ROUND(ABS({V}),6),"0.0")&" points "&IF(ROUND({V},6)>=0,"above","below")&" your average and "'
                         f'&TEXT(ROUND(ABS({W}),6),"0.0")&" "&IF(ROUND({W},6)>=0,"above","below")&" the class average.")',
                         tf, row.reason)
        sr.write_formula(r, SR_THP, f'=IF({N}="OK",{J}/{K}*100,"")', n2, _num(row.th_pct))
        sr.write_formula(r, SR_PRP, f'=IF(AND({N}="OK",{Mx}>0),{L}/{Mx}*100,"")', n2, _num(row.pr_pct))

    # ------------------------------------------------------------------ class averages
    def write_stats(self):
        ws, cfg, res = self.sheets["_stats"], self.cfg, self.res
        for c, h in enumerate(["Class", "Exam", "Subject", "Class Avg %"]):
            ws.write_string(0, c, h)
        for k in self.stats_keys:
            r = self.stats_index[k]
            cls, exam, subj = k
            ws.write_string(r, 0, cls)
            ws.write_string(r, 1, cfg.exam_name(exam))
            ws.write_string(r, 2, cfg.subject_name(subj))
            A, B, C = rc(r, 0), rc(r, 1), rc(r, 2)
            ws.write_formula(r, 3, f'=IFERROR(AVERAGEIFS(SR_Pct,SR_Class,{A},SR_Exam,{B},SR_Subject,{C},SR_Status,"OK"),"")',
                             None, _num(res.class_avg.get(k)))

    # ------------------------------------------------------------------ Dashboard
    def write_dashboard(self):
        ws, f, cfg, res = self.sheets["Dashboard"], self.f, self.cfg, self.res
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 16, 8.6)
        self.banner(ws, "Results Dashboard",
                    f"{cfg.rules['school_name']}, {cfg.rules['school_place']} · Academic year {cfg.rules['academic_year']}",
                    16)
        cls0 = self.classes[0] if self.classes else ""
        ex_list = self.ds.exams_for(cls0)
        ex0 = ex_list[-1] if ex_list else (self.exams[0] if self.exams else "")
        sel_c = self.selector(ws, 4, 1, "Class", "=L_Classes", cls0, name="D_Class")
        sel_e = self.selector(ws, 4, 4, "Exam", "=L_Exams", cfg.exam_name(ex0), 2, name="D_Exam")
        sel_s = self.selector(ws, 4, 8, "Section", "=L_Sections", "All", name="D_Section")
        ws.write(4, 11, "Pick a class, exam and section - everything below updates.", f.note())
        self.wb.define_name("D_Default", '="' + cls0 + "|" + cfg.exam_name(ex0) + '"')
        calc = self.sheets["_calc"]
        calc.write_string(0, 0, "Section criterion")
        calc.write_formula(0, 1, '=IF(D_Section="All","*",D_Section)', None, "*")
        self.wb.define_name("D_SecCrit", "=_calc!$B$1")
        v = views.dashboard(res, cls0, ex0, "All")
        crit = "MX_Class,D_Class,MX_Exam,D_Exam,MX_Section,D_SecCrit"
        cards = [
            ("Students", f'=COUNTIFS({crit},MX_Overall,">=0")', v["students"], "0"),
            ("Class average %", f'=IFERROR(AVERAGEIFS(MX_Overall,{crit}),"-")', _num(v["average"]), "0.0"),
            ("Highest %", f'=IFERROR(_xlfn.AGGREGATE(14,6,MX_Overall/((MX_Class=D_Class)*(MX_Exam=D_Exam)*'
                          f'(((D_Section="All")+(MX_Section=D_Section))>0)),1),"-")', _num(v["highest"]), "0.0"),
            ("Pass rate %", f'=IFERROR(COUNTIFS({crit},MX_Result,"Pass")/(COUNTIFS({crit},MX_Result,"Pass")+'
                            f'COUNTIFS({crit},MX_Result,"Not passed"))*100,"-")', _num(v["pass_rate"]), "0.0"),
        ]
        for i, (label, formula, val, nf) in enumerate(cards):
            c0 = 1 + i * 3
            self.kpi(ws, 6, c0, label, formula, val, nf)
        hi = rc(7, 7, True, True)
        top_f = (f'=IFERROR(INDEX(MX_Name,MATCH(1,INDEX((MX_Class=D_Class)*(MX_Exam=D_Exam)*'
                 f'(((D_Section="All")+(MX_Section=D_Section))>0)*(MX_Overall={hi}),0),0)),"-")')
        self.kpi(ws, 6, 13, "Top scorer", top_f, v["topper"] or "-", "@", size=13)
        # chart data on _calc
        r0 = self.calc_alloc(len(v["by_subject"]))
        calc.write_string(r0, 0, "Subject")
        calc.write_string(r0, 1, "Average %")
        for i, (s, avg) in enumerate(v["by_subject"]):
            r = r0 + 1 + i
            calc.write_string(r, 0, cfg.subject_short(s))
            calc.write_string(r, 5, cfg.subject_name(s))
            calc.write_formula(r, 1, f'=IFERROR(AVERAGEIFS(SR_Pct,SR_Class,D_Class,SR_Exam,D_Exam,SR_Section,D_SecCrit,'
                                     f'SR_Subject,{rc(r, 5)},SR_Status,"OK"),NA())', None,
                               _num(avg) if avg is not None else "#N/A")
        n = len(v["by_subject"])
        ch = self.chart("column", "Average % by subject")
        ch.add_series({"categories": _rng("_calc", r0 + 1, 0, r0 + n), "values": _rng("_calc", r0 + 1, 1, r0 + n),
                       "fill": {"color": theme.BLUE}, "gap": 60,
                       "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        self.axis_style(ch, y_max=100)
        ws.insert_chart(9, 1, ch, {"x_scale": 1.24, "y_scale": 1.1})
        # labels doughnut
        r1 = self.calc_alloc(4)
        calc.write_string(r1, 0, "Label")
        calc.write_string(r1, 1, "Count")
        for i, (lab, cnt) in enumerate(v["labels"]):
            r = r1 + 1 + i
            calc.write_string(r, 0, lab)
            calc.write_formula(r, 1, f'=COUNTIFS(SR_Label,{rc(r, 0)},SR_Class,D_Class,SR_Exam,D_Exam,SR_Section,D_SecCrit)',
                               None, cnt)
        ch = self.chart("doughnut", "How subjects are going")
        ch.add_series({"categories": _rng("_calc", r1 + 1, 0, r1 + 4), "values": _rng("_calc", r1 + 1, 1, r1 + 4),
                       "points": [{"fill": {"color": theme.GREEN}}, {"fill": {"color": "#7FD0F2"}},
                                  {"fill": {"color": "#F2A93B"}}, {"fill": {"color": theme.RED}}],
                       "data_labels": {"value": True, "font": {"size": 9, "color": theme.WHITE, "bold": True}}})
        ch.set_hole_size(55)
        ch.set_legend({"position": "right", "font": {"size": 9, "color": theme.TEXT}})
        ws.insert_chart(9, 10, ch, {"x_scale": 0.92, "y_scale": 1.1})
        # distribution
        r2 = self.calc_alloc(len(v["distribution"]))
        calc.write_string(r2, 0, "Overall % range")
        calc.write_string(r2, 1, "Students")
        bins = cfg.rules["score_bins"]
        for i, (lab, cnt) in enumerate(v["distribution"]):
            r = r2 + 1 + i
            lo, hi_ = bins[i], bins[i + 1]
            last = i == len(bins) - 2
            calc.write_string(r, 0, lab)
            calc.write_formula(r, 1, f'=COUNTIFS({crit},MX_Overall,">={lo}",MX_Overall,"{"<=" if last else "<"}{hi_}")',
                               None, cnt)
        nb = len(v["distribution"])
        ch = self.chart("column", "How many students in each overall % range")
        ch.add_series({"categories": _rng("_calc", r2 + 1, 0, r2 + nb), "values": _rng("_calc", r2 + 1, 1, r2 + nb),
                       "fill": {"color": theme.NAVY}, "gap": 30,
                       "data_labels": {"value": True, "font": {"size": 8, "color": theme.NAVY}}})
        self.axis_style(ch)
        ws.insert_chart(26, 1, ch, {"x_scale": 1.24, "y_scale": 1.0})
        # by section
        r3 = self.calc_alloc(max(1, len(v["by_section"])))
        calc.write_string(r3, 0, "Section")
        calc.write_string(r3, 1, "Average %")
        for i, (sec, avg) in enumerate(v["by_section"]):
            r = r3 + 1 + i
            calc.write_string(r, 0, sec)
            calc.write_formula(r, 1, f'=IFERROR(AVERAGEIFS(MX_Overall,MX_Class,D_Class,MX_Exam,D_Exam,MX_Section,{rc(r, 0)}),NA())',
                               None, _num(avg) if avg is not None else "#N/A")
        ns = max(1, len(v["by_section"]))
        ch = self.chart("bar", "Average overall % by section")
        ch.add_series({"categories": _rng("_calc", r3 + 1, 0, r3 + ns), "values": _rng("_calc", r3 + 1, 1, r3 + ns),
                       "fill": {"color": theme.BLUE}, "gap": 50,
                       "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.set_x_axis({"min": 0, "max": 100, "num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ch.set_y_axis({"num_font": {"size": 9, "color": theme.TEXT}, "reverse": True})
        ws.insert_chart(26, 10, ch, {"x_scale": 0.92, "y_scale": 1.0})
        ws.write(42, 1, "Labels compare each subject with the student's own average and with the class average "
                        "(rules on the Settings sheet). They are school guidance, not official CBSE results.", f.note())
        if self.vba:
            ws.insert_button(4, 13, {"macro": "RDPS_Recalculate", "caption": "Recalculate", "width": 100, "height": 24})
            ws.insert_button(4, 15, {"macro": "RDPS_ResetDashboard", "caption": "Reset view", "width": 90, "height": 24})
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 1)
        ws.print_area(0, 0, 43, 16)
        self.dash_defaults = (cls0, cfg.exam_name(ex0))

    def kpi(self, ws, row, col, label, formula, value, nf, size=24):
        f = self.f
        vfmt = f.get(font_name=theme.TITLE_FONT, font_size=size, font_color=theme.NAVY, align="center",
                     bg_color=theme.TINT, num_format=nf if nf != "@" else "General", top=2, top_color=theme.BLUE,
                     shrink=True)
        ws.merge_range(row, col, row, col + 2, "", f.get(bg_color=theme.TINT, top=2, top_color=theme.BLUE))
        ws.merge_range(row + 1, col, row + 1, col + 2, "", vfmt)
        ws.write_formula(row + 1, col, formula, vfmt, value)
        ws.merge_range(row + 2, col, row + 2, col + 2, label, f.kpi_label())
        ws.set_row(row, 6)
        ws.set_row(row + 1, 38)
        ws.set_row(row + 2, 18)

    # ------------------------------------------------------------------ Report card
    def write_report_card(self):
        ws, f, cfg, res, ds = self.sheets["Report Card"], self.f, self.cfg, self.res, self.ds
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 20)
        ws.set_column(2, 4, 9)
        ws.set_column(5, 5, 12)
        ws.set_column(6, 8, 9)
        ws.set_column(9, 9, 13)
        ws.set_column(10, 10, 2)
        ws.set_column(20, 40, 10, None, {"hidden": True})
        self.banner(ws, "Report Card", f"{cfg.rules['school_name']}, {cfg.rules['school_place']} · "
                                       f"Academic year {cfg.rules['academic_year']}", 9)
        studs = ds.ordered_students()
        if not studs:
            return
        st0 = studs[0]
        ex_list = ds.exams_for(st0.cls)
        ex0 = ex_list[-1] if ex_list else self.exams[0]
        sel_st = self.selector(ws, 4, 1, "Student", "=L_StudentLabels", self.labels[st0.sid], 5, name="RC_Student")
        sel_ex = self.selector(ws, 5, 1, "Exam", "=L_Exams", cfg.exam_name(ex0), 2, name="RC_Exam")
        H = 20  # hidden helper column start
        ws.write_string(3, H, "ID")
        ws.write_formula(4, H, "=IFERROR(INDEX(L_StudentIDs,MATCH(RC_Student,L_StudentLabels,0)),\"\")", None, st0.sid)
        self.wb.define_name("RC_ID", f"='Report Card'!{rc(4, H, True, True)}")
        smrow = f"MATCH(RC_ID,SM_ID,0)"
        card = views.report_card(res, st0.sid, ex0)
        # student info
        info = [("Name", "Name", st0.name), ("Class", None, f"{st0.cls}{('-' + st0.section) if st0.section else ''}"),
                ("Roll No", "Roll No", st0.roll), ("Admission No", "Admission No", st0.adm_no),
                ("Father's Name", "Father's Name", st0.father), ("Mother's Name", "Mother's Name", st0.mother),
                ("Group", "Group", st0.group)]
        lab = f.get(font_color=theme.MUTED, font_size=9, bold=True)
        val = f.get(font_color=theme.TEXT, font_size=11, bottom=1, bottom_color=theme.LINE)
        for i, (label, col, v0) in enumerate(info):
            r = 7 + i // 2
            c0 = 1 if i % 2 == 0 else 5
            ws.write(r, c0, label, lab)
            if col:
                ci = self.sm_cols[col] + 1
                fml = f'=IFERROR(INDEX(SM_Table,{smrow},{ci})&"","")'
            else:
                fml = (f'=IFERROR(INDEX(SM_Table,{smrow},{self.sm_cols["Class"] + 1})&IF(INDEX(SM_Table,{smrow},'
                       f'{self.sm_cols["Section"] + 1})="","","-"&INDEX(SM_Table,{smrow},{self.sm_cols["Section"] + 1})),"")')
            ws.merge_range(r, c0 + 1, r, c0 + 3, "", val)
            ws.write_formula(r, c0 + 1, fml, val, v0)
        # subject table
        hr = 12
        junior = any(not cfg.has_streams(c) for c in self.classes)
        heads = ["Subject", "Written" if junior else "Theory", "Int / Prac" if junior else "Practical", "Total", "Max", "%",
                 "Class avg %", "Grade", "Status"]
        for c, h in enumerate(heads, 1):
            ws.write(hr, c, h, f.header())
        ws.set_row(hr, 22)
        nrows = self.max_subjects
        by_sub = {x["subject"]: x for x in card["rows"]}
        subj_names = [cfg.subject_name(s) for s in st0.subjects]
        first_sub_col = self.sm_cols["Subject 1"] + 1
        for i in range(nrows):
            r = hr + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            sname = subj_names[i] if i < len(subj_names) else ""
            x = next((y for y in card["rows"] if y["name"] == sname), None)
            ws.write_formula(r, 1, f'=IFERROR(INDEX(SM_Table,{smrow},{first_sub_col + i})&"","")',
                             f.cell(bold=True, **band), sname)
            S = rc(r, 1)
            idx = rc(r, H + 1)
            ws.write_formula(r, H + 1, f'=IF({S}="","",IFERROR(MATCH(RC_ID&"|"&RC_Exam&"|"&{S},SR_Key,0),""))', None,
                             (self.sr_row_of.get((st0.sid, ex0, x["subject"])) if x else "") or "")
            def g(name, v, fmt):
                ws.write_formula(r, cidx, f'=IF({idx}="","",INDEX({name},{idx}))', fmt, v)
            cf = f.cell(align="center", **band)
            for cidx, name, key, fmt in [(2, "SR_Th", "theory", cf), (3, "SR_Pr", "practical", cf),
                                         (4, "SR_Obt", "obtained", cf), (5, "SR_Max", "max", cf),
                                         (6, "SR_Pct", "pct", f.num(1, bold=True, **band)),
                                         (7, "SR_ClassAvg", "class_avg", f.num(1, font_color=theme.MUTED, **band)),
                                         (8, "SR_Grade", "grade", cf)]:
                v = ""
                if x:
                    v = x.get(key)
                    if isinstance(v, Decimal):
                        v = float(v)
                    if v is None:
                        v = ""
                    if key == "practical" and not x.get("pr_max"):
                        v = ""
                    if key == "max":
                        v = float(x["max"])
                g(name, v, fmt)
            gentle = (f'=IF({idx}="","",IF(INDEX(SR_Label,{idx})="Strong","Doing well",IF(INDEX(SR_Label,{idx})="Weak",'
                      f'"Focus area",IF(INDEX(SR_Label,{idx})="Needs attention","Needs support",INDEX(SR_Label,{idx})))))')
            ws.write_formula(r, 9, gentle, f.cell(align="center", **band), x["gentle"] if x else "")
            ws.write_formula(r, H + 2, f'=IF({idx}="",NA(),IF(ISNUMBER(INDEX(SR_Pct,{idx})),INDEX(SR_Pct,{idx}),NA()))',
                             None, float(x["pct"]) if x and x["pct"] is not None else "#N/A")
            ws.write_formula(r, H + 3, f'=IF({idx}="",NA(),IF(ISNUMBER(INDEX(SR_ClassAvg,{idx})),INDEX(SR_ClassAvg,{idx}),NA()))',
                             None, float(x["class_avg"]) if x and x["class_avg"] is not None else "#N/A")
            ws.write_formula(r, H + 4, f'=IF({S}="","",{S})', None, sname)
        for lab_, (fg, bg) in [("Doing well", theme.LABEL_COLORS["Strong"]), ("Focus area", theme.LABEL_COLORS["Weak"]),
                               ("Needs support", theme.LABEL_COLORS["Needs attention"])]:
            ws.conditional_format(hr + 1, 9, hr + nrows, 9, {"type": "cell", "criteria": "==", "value": f'"{lab_}"',
                                                             "format": self.wb.add_format({"font_color": fg, "bg_color": bg,
                                                                                           "bold": True})})
        # overall
        r = hr + nrows + 2
        mxidx = rc(r, H + 1)
        ws.write_formula(r, H + 1, '=IFERROR(MATCH(RC_ID&"|"&RC_Exam,MX_Key,0),"")', None,
                         (self.order.index((st0.sid, ex0)) + 1) if (st0.sid, ex0) in self.order else "")
        ov = [("Total", "MX_Obt", _num(card["obtained"]), "0.##"), ("Out of", "MX_Max", _num(card["max"]), "0"),
              ("Overall %", "MX_Overall", _num(card["overall"]), "0.00"), ("Result", "MX_Result", card["result"], "@"),
              ("Class rank", "MX_Rank", card["rank"] if card["rank"] is not None else "", "0")]
        for i, (label, name, v, nf) in enumerate(ov):
            c0 = [1, 3, 5, 7, 9][i]
            ws.write(r, c0, label, f.get(font_color=theme.MUTED, font_size=9, bold=True, align="center",
                                         bg_color=theme.TINT, top=2, top_color=theme.BLUE))
            ws.write_formula(r + 1, c0, f'=IF({mxidx}="","",INDEX({name},{mxidx}))',
                             f.get(font_name=theme.TITLE_FONT, font_size=15, font_color=theme.NAVY, align="center",
                                   bg_color=theme.TINT, num_format=nf if nf != "@" else "General"), v)
            if c0 + 1 <= 9 and i < 4:
                ws.write_blank(r, c0 + 1, None, f.get(bg_color=theme.TINT, top=2, top_color=theme.BLUE))
                ws.write_blank(r + 1, c0 + 1, None, f.get(bg_color=theme.TINT))
        ws.set_row(r + 1, 28)
        ws.write_formula(r + 2, 7, '=IF(N(' + rc(r + 1, 9) + ')=0,"","of "&COUNTIFS(MX_Class,INDEX(MX_Class,'
                         + mxidx + '),MX_Exam,RC_Exam,MX_Overall,">=0")&" in class")', f.note(),
                         f"of {card['class_size']} in class" if card["rank"] else "")
        # remarks (rule-based, always true)
        rr = r + 4
        ws.write(rr, 1, "Remarks", f.section())
        rem = card["remarks"]
        pct_rng = f"{rc(hr + 1, H + 2, True, True)}:{rc(hr + nrows, H + 2, True, True)}"
        name_rng = f"{rc(hr + 1, 1, True, True)}:{rc(hr + nrows, 1, True, True)}"
        idxs = [rc(hr + 1 + i, H + 1) for i in range(nrows)]
        def concat(cond_label_list):
            parts = []
            for i in range(nrows):
                idx, nm = idxs[i], rc(hr + 1 + i, 1)
                conds = ",".join(f'INDEX(SR_Label,{idx})="{l}"' for l in cond_label_list)
                parts.append(f'IF({idx}="","",IF(OR({conds}),{nm}&", ",""))')
            return "&".join(parts)
        good = concat(["Strong"])
        gnames = [y["name"] for y in card["rows"] if y["label"] == "Strong"]
        ws.write_formula(rr + 1, 1, f'=IFERROR("Best subject: "&INDEX({name_rng},MATCH(_xlfn.AGGREGATE(14,6,{pct_rng},1),'
                                    f'{pct_rng},0))&" ("&TEXT(ROUND(_xlfn.AGGREGATE(14,6,{pct_rng},1),6),"0.0")&"%).","")',
                         f.get(font_size=10), next((x for x in rem if x.startswith("Best subject")), ""))
        gtxt = ("Doing well in: " + ", ".join(gnames) + ".") if gnames else ""
        ws.write_formula(rr + 2, 1, f'=IF(LEN({good})=0,"","Doing well in: "&LEFT({good},LEN({good})-2)&".")',
                         f.get(font_size=10, font_color=theme.GREEN), gtxt)
        best_cell = rc(hr, H + 5)
        ws.write_formula(hr, H + 5, f'=IFERROR(INDEX({name_rng},MATCH(_xlfn.AGGREGATE(14,6,{pct_rng},1),{pct_rng},0)),"")',
                         None, next((y["name"] for y in card["rows"] if rem and rem[0].startswith("Best subject: " + y["name"] + " (")), ""))
        fparts = []
        for i in range(nrows):
            idx, nm = idxs[i], rc(hr + 1 + i, 1)
            fparts.append(f'IF({idx}="","",IF(AND(OR(INDEX(SR_Label,{idx})="Weak",INDEX(SR_Label,{idx})="Needs attention"),'
                          f'OR({nm}<>{best_cell},INDEX(SR_Passed,{idx})="No")),{nm}&", ",""))')
        focus = "&".join(fparts)
        best_name = next((y["name"] for y in card["rows"] if rem and rem[0].startswith("Best subject: " + y["name"] + " (")), "")
        fnames = [y["name"] for y in card["rows"] if y["label"] in ("Weak", "Needs attention")
                  and (y["name"] != best_name or y["passed"] == "No")]
        ws.write_formula(rr + 3, 1, f'=IF(LEN({focus})=0,"","Focus area: "&LEFT({focus},LEN({focus})-2)&". See the subject notes below.")',
                         f.get(font_size=10, font_color=theme.AMBER),
                         ("Focus area: " + ", ".join(fnames) + ". See the subject notes below.") if fnames else "")
        # trend
        tr = hr + 1
        ws.write_string(tr - 1, H + 6, "Exam")
        ws.write_string(tr - 1, H + 7, "Overall %")
        cls_col = f"MATCH(INDEX(SM_Table,{smrow},{self.sm_cols['Class'] + 1}),L_ClassHeads,0)"
        series = card["trend"]
        for j in range(self.max_exams):
            ename = cfg.exam_name(series[j][0]) if j < len(series) else ""
            ws.write_formula(tr + j, H + 6, f'=IFERROR(INDEX(L_ClassExams,{j + 1},{cls_col})&"","")', None, ename)
            e = rc(tr + j, H + 6)
            v = series[j][1] if j < len(series) else None
            ws.write_formula(tr + j, H + 7, f'=IF({e}="",NA(),IFERROR(INDEX(MX_Overall,MATCH(RC_ID&"|"&{e},MX_Key,0))+0,NA()))',
                             None, float(v) if v is not None else "#N/A")
        rlast = rr + 4
        ws.write(rlast, 1, "Subject notes", f.section())
        for i in range(nrows):
            idx = idxs[i]
            x = card["rows"][i] if i < len(card["rows"]) else None
            ws.merge_range(rlast + 1 + i, 1, rlast + 1 + i, 9, "", f.get(font_size=9, font_color=theme.TEXT))
            ws.write_formula(rlast + 1 + i, 1, f'=IF({idx}="","",INDEX(SR_Reason,{idx}))',
                             f.get(font_size=9, font_color=theme.TEXT), x["reason"] if x else "")
        cr = rlast + nrows + 2
        ch = self.chart("bar", "Subject % vs class average")
        cats = f"{_q('Report Card')}!{rc(hr + 1, H + 4, True, True)}:{rc(hr + nrows, H + 4, True, True)}"
        ch.add_series({"name": "Student", "categories": cats,
                       "values": f"{_q('Report Card')}!{rc(hr + 1, H + 2, True, True)}:{rc(hr + nrows, H + 2, True, True)}",
                       "fill": {"color": theme.BLUE}, "gap": 40,
                       "data_labels": {"value": True, "num_format": "0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.add_series({"name": "Class average", "categories": cats,
                       "values": f"{_q('Report Card')}!{rc(hr + 1, H + 3, True, True)}:{rc(hr + nrows, H + 3, True, True)}",
                       "fill": {"color": "#BFD9EA"}})
        ch.set_x_axis({"min": 0, "max": 100, "num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 9}})
        ch.set_legend({"position": "bottom", "font": {"size": 8}})
        ch.show_hidden_data()
        ws.insert_chart(cr, 1, ch, {"x_scale": 0.82, "y_scale": 1.05})
        ch = self.chart("radar", "Subject profile", "filled")
        ch.add_series({"name": "Student", "categories": cats,
                       "values": f"{_q('Report Card')}!{rc(hr + 1, H + 2, True, True)}:{rc(hr + nrows, H + 2, True, True)}",
                       "fill": {"color": theme.BLUE, "transparency": 45}, "border": {"color": theme.BLUE}})
        ch.set_y_axis({"min": 0, "max": 100, "num_font": {"size": 7, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ch.set_x_axis({"num_font": {"size": 8}})
        ch.show_hidden_data()
        ws.insert_chart(cr, 5, ch, {"x_scale": 0.82, "y_scale": 1.05})
        ch = self.chart("line", "Overall % across exams")
        ch.add_series({"categories": f"{_q('Report Card')}!{rc(tr, H + 6, True, True)}:{rc(tr + self.max_exams - 1, H + 6, True, True)}",
                       "values": f"{_q('Report Card')}!{rc(tr, H + 7, True, True)}:{rc(tr + self.max_exams - 1, H + 7, True, True)}",
                       "line": {"color": theme.NAVY, "width": 2.25},
                       "marker": {"type": "circle", "size": 7, "fill": {"color": theme.BLUE}, "border": {"color": theme.NAVY}},
                       "data_labels": {"value": True, "num_format": "0.0", "position": "above",
                                       "font": {"size": 8, "color": theme.NAVY}}})
        self.axis_style(ch, y_max=100)
        ch.show_na_as_empty_cell()
        ch.show_hidden_data()
        ws.insert_chart(cr + 16, 1, ch, {"x_scale": 1.62, "y_scale": 0.8})
        ws.write(cr + 29, 1, "Teachers' view. Remarks are written by fixed rules from the marks above - nothing is guessed.",
                 f.note())
        if self.vba:
            ws.insert_button(4, 8, {"macro": "RDPS_ExportReportCard", "caption": "Save this card as PDF",
                                    "width": 140, "height": 22})
            ws.insert_button(5, 8, {"macro": "RDPS_ExportAllReportCards", "caption": "Save all cards as PDF",
                                    "width": 140, "height": 22})
        ws.set_portrait()
        ws.set_paper(9)
        ws.set_margins(0.4, 0.4, 0.5, 0.5)
        ws.fit_to_pages(1, 1)
        ws.print_area(0, 0, cr + 30, 10)
        self.wb.define_name("RC_PrintArea", f"='Report Card'!$A$1:{rc(cr + 30, 10, True, True)}")

    # ------------------------------------------------------------------ Subject analysis
    def write_subject_analysis(self):
        ws, f, cfg, res = self.sheets["Subject Analysis"], self.f, self.cfg, self.res
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 22)
        ws.set_column(2, 10, 11)
        self.banner(ws, "Subject Analysis", "How each subject went for a class in one exam.", 14)
        cls0, ex0n = self.dash_defaults
        ex0 = next((e for e in self.exams if cfg.exam_name(e) == ex0n), self.exams[0] if self.exams else "")
        self.selector(ws, 4, 1, "Class", "=L_Classes", cls0, name="SA_Class")
        self.selector(ws, 4, 3, "Exam", "=L_Exams", ex0n, 2, name="SA_Exam")
        hr = 6
        heads = ["Subject", "Students", "Average %", "Highest %", "Lowest %", "Pass %", "Absent", "Avg theory",
                 "Avg practical"]
        for c, h in enumerate(heads, 1):
            ws.write(hr, c, h, f.header())
        ws.set_row(hr, 30)
        rows = views.subject_analysis(res, cls0, ex0)
        calc = self.sheets["_calc"]
        base = self.calc_alloc(len(rows))
        calc.write_string(base, 0, "SA subject")
        calc.write_string(base, 1, "SA avg")
        for i, x in enumerate(rows):
            r = hr + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            sname = x["name"]
            ws.write_string(r, 1, sname, f.cell(bold=True, **band))
            S = rc(r, 1)
            crit = f'SR_Class,SA_Class,SR_Exam,SA_Exam,SR_Subject,{S}'
            cond = f"(SR_Class=SA_Class)*(SR_Exam=SA_Exam)*(SR_Subject={S})*(SR_Status=\"OK\")"
            vals = [
                (f'=COUNTIFS({crit},SR_Status,"OK")', x.get("count", 0), f.cell(align="center", **band)),
                (f'=IFERROR(AVERAGEIFS(SR_Pct,{crit},SR_Status,"OK"),"-")', _num(x.get("avg")) if x.get("avg") is not None else "-",
                 f.num(1, bold=True, **band)),
                (f'=IFERROR(_xlfn.AGGREGATE(14,6,SR_Pct/({cond}),1),"-")', _num(x.get("max")) if x.get("max") is not None else "-",
                 f.num(1, **band)),
                (f'=IFERROR(_xlfn.AGGREGATE(15,6,SR_Pct/({cond}),1),"-")', _num(x.get("min")) if x.get("min") is not None else "-",
                 f.num(1, **band)),
                (f'=IFERROR(COUNTIFS({crit},SR_Passed,"Yes")/(COUNTIFS({crit},SR_Passed,"Yes")+COUNTIFS({crit},SR_Passed,"No"))*100,"-")',
                 _num(x.get("pass_pct")) if x.get("pass_pct") is not None else "-", f.num(1, **band)),
                (f'=COUNTIFS({crit},SR_Status,"AB")', x.get("absent", 0), f.cell(align="center", **band)),
                (f'=IFERROR(AVERAGEIFS(SR_Th,{crit},SR_Status,"OK"),"-")', _num(x.get("avg_th")) if x.get("avg_th") is not None else "-",
                 f.num(1, **band)),
                (f'=IFERROR(AVERAGEIFS(SR_Pr,{crit},SR_Status,"OK"),"-")',
                 _num(x.get("avg_pr")) if x.get("avg_pr") is not None else "-", f.num(1, **band)),
            ]
            for j, (fml, v, fmt) in enumerate(vals):
                if j == 7 and not cfg.has_practical(x["subject"]):
                    ws.write_string(r, 2 + j, "-", f.cell(align="center", font_color=theme.MUTED, **band))
                    continue
                ws.write_formula(r, 2 + j, fml, fmt, v)
            calc.write_string(base + 1 + i, 0, cfg.subject_short(x["subject"]))
            calc.write_formula(base + 1 + i, 1, f"=IF(ISNUMBER('Subject Analysis'!{rc(r, 3)}),'Subject Analysis'!{rc(r, 3)},NA())",
                               None, _num(x.get("avg")) if x.get("avg") is not None else "#N/A")
        n = len(rows)
        ws.conditional_format(hr + 1, 3, hr + n, 3, {"type": "data_bar", "bar_color": "#9FDCF5", "bar_solid": True,
                                                    "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 100})
        ch = self.chart("column", "Average % by subject")
        ch.add_series({"categories": _rng("_calc", base + 1, 0, base + n), "values": _rng("_calc", base + 1, 1, base + n),
                       "fill": {"color": theme.BLUE}, "gap": 60,
                       "data_labels": {"value": True, "num_format": "0", "font": {"size": 8, "color": theme.NAVY}}})
        self.axis_style(ch, y_max=100)
        cr = hr + n + 2
        ws.insert_chart(cr, 1, ch, {"x_scale": 1.0, "y_scale": 1.0})
        # theory vs practical (practical subjects)
        prs = [x for x in rows if cfg.has_practical(x["subject"])]
        b2 = self.calc_alloc(len([x for x in rows if cfg.has_practical(x["subject"])]))
        calc.write_string(b2, 0, "Subject")
        calc.write_string(b2, 1, "Avg theory")
        calc.write_string(b2, 2, "Avg practical")
        for i, x in enumerate(prs):
            r = hr + 1 + rows.index(x)
            calc.write_string(b2 + 1 + i, 0, cfg.subject_short(x["subject"]))
            calc.write_formula(b2 + 1 + i, 1, f"=IF(ISNUMBER('Subject Analysis'!{rc(r, 8)}),'Subject Analysis'!{rc(r, 8)},NA())",
                               None, _num(x.get("avg_th")) if x.get("avg_th") is not None else "#N/A")
            calc.write_formula(b2 + 1 + i, 2, f"=IF(ISNUMBER('Subject Analysis'!{rc(r, 9)}),'Subject Analysis'!{rc(r, 9)},NA())",
                               None, _num(x.get("avg_pr")) if x.get("avg_pr") is not None else "#N/A")
        if prs:
            ch = self.chart("column", "Theory + practical (average marks)", "stacked")
            np_ = len(prs)
            ch.add_series({"name": "Theory", "categories": _rng("_calc", b2 + 1, 0, b2 + np_),
                           "values": _rng("_calc", b2 + 1, 1, b2 + np_), "fill": {"color": theme.BLUE}, "gap": 70,
                           "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.WHITE}}})
            ch.add_series({"name": "Practical", "categories": _rng("_calc", b2 + 1, 0, b2 + np_),
                           "values": _rng("_calc", b2 + 1, 2, b2 + np_), "fill": {"color": theme.NAVY},
                           "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.WHITE}}})
            self.axis_style(ch, y_title="Marks")
            ch.set_legend({"position": "bottom", "font": {"size": 8}})
            ws.insert_chart(cr, 7, ch, {"x_scale": 0.9, "y_scale": 1.0})
        # trend for one subject
        tr = cr + 16
        ws.write(tr, 1, "Subject trend across exams", f.section())
        s0 = cfg.subject_name(self.subjects[0]) if self.subjects else ""
        self.selector(ws, tr + 1, 1, "Subject", "=L_Subjects", s0, 1, name="SA_TrendSubject")
        b3 = self.calc_alloc(self.max_exams)
        calc.write_string(b3, 0, "Exam")
        calc.write_string(b3, 1, "Average %")
        calc.write_string(b3, 2, "Pass %")
        tser = views.subject_trend(res, cls0, self.subjects[0]) if self.subjects else []
        cls_col = "MATCH(SA_Class,L_ClassHeads,0)"
        for j in range(self.max_exams):
            r = b3 + 1 + j
            ename = cfg.exam_name(tser[j][0]) if j < len(tser) else ""
            calc.write_formula(r, 0, f'=IFERROR(INDEX(L_ClassExams,{j + 1},{cls_col})&"","")', None, ename)
            e = rc(r, 0)
            calc.write_formula(r, 1, f'=IF({e}="",NA(),IFERROR(AVERAGEIFS(SR_Pct,SR_Class,SA_Class,SR_Exam,{e},'
                                     f'SR_Subject,SA_TrendSubject,SR_Status,"OK"),NA()))', None,
                               _num(tser[j][1]) if j < len(tser) and tser[j][1] is not None else "#N/A")
            calc.write_formula(r, 2, f'=IF({e}="",NA(),IFERROR(COUNTIFS(SR_Class,SA_Class,SR_Exam,{e},SR_Subject,'
                                     f'SA_TrendSubject,SR_Passed,"Yes")/(COUNTIFS(SR_Class,SA_Class,SR_Exam,{e},'
                                     f'SR_Subject,SA_TrendSubject,SR_Passed,"Yes")+COUNTIFS(SR_Class,SA_Class,SR_Exam,{e},'
                                     f'SR_Subject,SA_TrendSubject,SR_Passed,"No"))*100,NA()))', None,
                               _num(tser[j][2]) if j < len(tser) and tser[j][2] is not None else "#N/A")
        ch = self.chart("line", "Average % and pass % across exams")
        for col, name, color in [(1, "Average %", theme.BLUE), (2, "Pass %", theme.NAVY)]:
            ch.add_series({"name": name, "categories": _rng("_calc", b3 + 1, 0, b3 + self.max_exams),
                           "values": _rng("_calc", b3 + 1, col, b3 + self.max_exams),
                           "line": {"color": color, "width": 2.25},
                           "marker": {"type": "circle", "size": 6, "fill": {"color": color}, "border": {"color": color}},
                           "data_labels": {"value": True, "num_format": "0", "position": "above",
                                           "font": {"size": 8, "color": color}}})
        self.axis_style(ch, y_max=100)
        ch.set_legend({"position": "bottom", "font": {"size": 8}})
        ch.show_na_as_empty_cell()
        ws.insert_chart(tr + 3, 1, ch, {"x_scale": 1.5, "y_scale": 0.95})

    # ------------------------------------------------------------------ Marks analysis
    def write_marks_analysis(self):
        ws, f, cfg, res, ds = self.sheets["Marks Analysis"], self.f, self.cfg, self.res, self.ds
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 14, 9)
        self.banner(ws, "Marks Analysis", "Compare two exams, see how marks are spread and which grades students got.", 14)
        cls0, ex0n = self.dash_defaults
        exs = ds.exams_for(cls0)
        exA = cfg.exam_name(exs[-2]) if len(exs) >= 2 else ex0n
        exB = cfg.exam_name(exs[-1]) if exs else ex0n
        self.selector(ws, 4, 1, "Class", "=L_Classes", cls0, name="MA_Class")
        self.selector(ws, 4, 3, "From", "=L_Exams", exA, 2, name="MA_ExamX")
        self.selector(ws, 4, 7, "To", "=L_Exams", exB, 2, name="MA_ExamY")
        self.selector(ws, 5, 1, "Subject", "=L_SubjectsAll", "All subjects", 2, name="MA_Subject")
        self.selector(ws, 5, 7, "Exam", "=L_Exams", exB, 2, name="MA_Exam")
        calc = self.sheets["_calc"]
        base = self.calc_alloc(len(ds.students))
        calc.write_string(base, 0, "Student")
        calc.write_string(base, 1, "X")
        calc.write_string(base, 2, "Y")
        studs = ds.ordered_students()
        exAc = next((e for e in self.exams if cfg.exam_name(e) == exA), None)
        exBc = next((e for e in self.exams if cfg.exam_name(e) == exB), None)
        for i, st in enumerate(studs):
            r = base + 1 + i
            calc.write_string(r, 0, st.sid)
            calc.write_string(r, 3, st.cls)
            for col, sel, ec in [(1, "MA_ExamX", exAc), (2, "MA_ExamY", exBc)]:
                er = res.exam_results.get((st.sid, ec))
                v = float(er.overall) if er and er.overall is not None and st.cls == cls0 else "#N/A"
                calc.write_formula(r, col, f'=IF({rc(r, 3)}<>MA_Class,NA(),IFERROR(INDEX(MX_Overall,MATCH({rc(r, 0)}&"|"&{sel},'
                                           f'MX_Key,0))+0,NA()))', None, v)
        ns = max(1, len(studs))
        ch = self.wb.add_chart({"type": "scatter"})
        ch.set_title({"name": "Each dot is a student: 'From' exam (across) vs 'To' exam (up)",
                      "name_font": {"name": theme.TITLE_FONT, "size": 11, "color": theme.NAVY, "bold": False}})
        ch.add_series({"categories": _rng("_calc", base + 1, 1, base + ns), "values": _rng("_calc", base + 1, 2, base + ns),
                       "marker": {"type": "circle", "size": 5, "fill": {"color": theme.BLUE, "transparency": 25},
                                  "border": {"color": theme.NAVY, "transparency": 40}}})
        ch.set_x_axis({"min": 0, "max": 100, "name": "Overall % in 'From' exam", "name_font": {"size": 8, "bold": False},
                       "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#EEF2F5"}}})
        ch.set_y_axis({"min": 0, "max": 100, "name": "Overall % in 'To' exam", "name_font": {"size": 8, "bold": False},
                       "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#EEF2F5"}}})
        ch.set_legend({"none": True})
        ch.set_chartarea({"border": {"color": theme.LINE}})
        ws.insert_chart(7, 1, ch, {"x_scale": 1.15, "y_scale": 1.25})
        # histogram of subject %
        bins = cfg.rules["score_bins"]
        b2 = self.calc_alloc(len(bins))
        calc.write_string(b2, 0, "Subject criterion")
        calc.write_formula(b2, 1, '=IF(MA_Subject="All subjects","*",MA_Subject)', None, "*")
        subj_crit = rc(b2, 1, True, True)
        crit = f"SR_Class,MA_Class,SR_Exam,MA_Exam,SR_Subject,_calc!{subj_crit},SR_Status,\"OK\""
        exBcode = exBc
        rows_sel = [r for r in res.rows if r.exam == exBcode and ds.students[r.sid].cls == cls0 and r.status == STATUS_OK]
        for i in range(len(bins) - 1):
            r = b2 + 1 + i
            lo, hi = bins[i], bins[i + 1]
            last = i == len(bins) - 2
            calc.write_string(r, 0, f"{lo}-{hi}")
            cnt = sum(1 for x in rows_sel if r6(x.pct) >= lo and (r6(x.pct) <= hi if last else r6(x.pct) < hi))
            calc.write_formula(r, 1, f'=COUNTIFS({crit},SR_Pct,">={lo}",SR_Pct,"{"<=" if last else "<"}{hi}")', None, cnt)
        nb = len(bins) - 1
        ch = self.chart("column", "Spread of subject marks (%)")
        ch.add_series({"categories": _rng("_calc", b2 + 1, 0, b2 + nb), "values": _rng("_calc", b2 + 1, 1, b2 + nb),
                       "fill": {"color": theme.BLUE}, "gap": 15,
                       "data_labels": {"value": True, "font": {"size": 8, "color": theme.NAVY}}})
        self.axis_style(ch, y_title="Results")
        ws.insert_chart(7, 9, ch, {"x_scale": 0.95, "y_scale": 1.25})
        # grades pie
        b3 = self.calc_alloc(len(cfg.rules["grades"]))
        grades = [g["grade"] for g in sorted(cfg.rules["grades"], key=lambda g: -g["min"])]
        calc.write_string(b3, 0, "Grade")
        calc.write_string(b3, 1, "Count")
        for i, g in enumerate(grades):
            r = b3 + 1 + i
            calc.write_string(r, 0, g)
            calc.write_formula(r, 1, f'=COUNTIFS({crit},SR_Grade,{rc(r, 0)})', None, sum(1 for x in rows_sel if x.grade == g))
        ch = self.chart("pie", "Grades")
        palette = ["#0B3C5D", "#1F5F8B", "#06A7E7", "#5CC4EF", "#9FDCF5", "#CBEBF9", "#F2A93B", "#C0392B"]
        ch.add_series({"categories": _rng("_calc", b3 + 1, 0, b3 + len(grades)),
                       "values": _rng("_calc", b3 + 1, 1, b3 + len(grades)),
                       "points": [{"fill": {"color": palette[i % len(palette)]}} for i in range(len(grades))],
                       "data_labels": {"value": True, "category": True, "separator": "\n", "position": "best_fit",
                                       "font": {"size": 8}}})
        ch.set_legend({"none": True})
        ws.insert_chart(27, 1, ch, {"x_scale": 1.15, "y_scale": 1.1})
        # result types doughnut
        b4 = self.calc_alloc(4)
        crit2 = f"SR_Class,MA_Class,SR_Exam,MA_Exam,SR_Subject,_calc!{subj_crit}"
        kinds = [("Passed", f'=COUNTIFS({crit2},SR_Passed,"Yes")'), ("Below pass mark", f'=COUNTIFS({crit2},SR_Status,"OK",SR_Passed,"No")'),
                 ("Absent", f'=COUNTIFS({crit2},SR_Status,"AB")'),
                 ("On leave / exempt", f'=COUNTIFS({crit2},SR_Status,"<>OK",SR_Status,"<>AB",SR_Status,"<>INVALID",SR_Status,"<>INCOMPLETE")')]
        allr = [r for r in res.rows if r.exam == exBcode and ds.students[r.sid].cls == cls0]
        vals = [sum(1 for x in allr if x.passed == "Yes"), sum(1 for x in allr if x.status == STATUS_OK and x.passed == "No"),
                sum(1 for x in allr if x.status == "AB"),
                sum(1 for x in allr if x.status not in (STATUS_OK, "AB", "INVALID", "INCOMPLETE"))]
        for i, (lab, fml) in enumerate(kinds):
            calc.write_string(b4 + 1 + i, 0, lab)
            calc.write_formula(b4 + 1 + i, 1, fml, None, vals[i])
        ch = self.chart("doughnut", "Results in this exam")
        ch.add_series({"categories": _rng("_calc", b4 + 1, 0, b4 + 4), "values": _rng("_calc", b4 + 1, 1, b4 + 4),
                       "points": [{"fill": {"color": theme.BLUE}}, {"fill": {"color": theme.RED}},
                                  {"fill": {"color": "#F2A93B"}}, {"fill": {"color": "#9DB4C7"}}],
                       "data_labels": {"value": True, "font": {"size": 9, "color": theme.WHITE, "bold": True}}})
        ch.set_hole_size(55)
        ch.set_legend({"position": "right", "font": {"size": 9}})
        ws.insert_chart(27, 9, ch, {"x_scale": 0.95, "y_scale": 1.1})

    # ------------------------------------------------------------------ Progress
    def write_progress(self):
        ws, f, cfg, res, ds = self.sheets["Progress"], self.f, self.cfg, self.res, self.ds
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 24)
        ws.set_column(2, 2, 7)
        ws.set_column(3, 30, 9.5)
        self.banner(ws, "Progress", "Overall % in each exam, the change between exams, and who to keep an eye on.", 16)
        r = 4
        for cls in self.classes:
            exams = ds.exams_for(cls)
            rows = views.progress_rows(res, cls)
            if not exams or not rows:
                continue
            ws.write(r, 1, f"{cfg.class_label(cls)}", f.section())
            r += 1
            heads = ["Student", "Sec"] + [cfg.exam_name(e) for e in exams] + \
                    [f"{cfg.exam_name(a)[:3]}→{cfg.exam_name(b)[:3]}" for a, b in zip(exams, exams[1:])] + \
                    ["Latest change", "Dropped twice", "Latest result", "Watch"]
            for c, h in enumerate(heads, 1):
                ws.write(r, c, h, f.header())
            ws.set_row(r, 30)
            ne = len(exams)
            c_ex0 = 3
            c_d0 = c_ex0 + ne
            c_latest = c_d0 + ne - 1
            c_drop, c_lres, c_watch = c_latest + 1, c_latest + 2, c_latest + 3
            first = r + 1
            for i, x in enumerate(rows):
                rr = r + 1 + i
                band = {"bg_color": theme.TINT2} if i % 2 else {}
                ws.write_string(rr, 1, x["name"], f.cell(**band))
                ws.write_string(rr, 2, x["section"], f.cell(align="center", **band))
                for j, (e, v) in enumerate(x["series"]):
                    mr = self.mx_row_of.get((x["sid"], e))
                    if mr is None:
                        ws.write_blank(rr, c_ex0 + j, None, f.cell(**band))
                    else:
                        ref = f"'Overview'!{rc(mr, self.mx_cols['overall'])}"
                        ws.write_formula(rr, c_ex0 + j, f"=IF({ref}=\"\",\"\",{ref})", f.num(1, **band), _num(v))
                dmap = {(a, b): d for a, b, d in x["deltas"]}
                for j, (a, b) in enumerate(zip(exams, exams[1:])):
                    A, B = rc(rr, c_ex0 + j), rc(rr, c_ex0 + j + 1)
                    d = dmap.get((a, b))
                    ws.write_formula(rr, c_d0 + j, f'=IF(OR({A}="",{B}=""),"",{B}-{A})', f.num(1, **band), _num(d))
                drng = f"{rc(rr, c_d0)}:{rc(rr, c_d0 + ne - 2)}" if ne > 1 else None
                if drng:
                    ws.write_formula(rr, c_latest, f'=IFERROR(LOOKUP(2,1/({drng}<>""),{drng}),"")', f.num(1, bold=True, **band),
                                     _num(x["latest_change"]))
                    pairs = []
                    for j in range(ne - 2):
                        d1, d2 = rc(rr, c_d0 + j), rc(rr, c_d0 + j + 1)
                        pairs.append(f'AND({d1}<>"",{d2}<>"",ROUND(N({d1}),6)<=-DropGap,ROUND(N({d2}),6)<=-DropGap)')
                    fml = f'=IF(OR({",".join(pairs)}),"Yes","")' if pairs else '=""'
                    ws.write_formula(rr, c_drop, fml, f.cell(align="center", **band), "Yes" if x["dropped_twice"] else "")
                else:
                    ws.write_string(rr, c_latest, "", f.cell(**band))
                    ws.write_string(rr, c_drop, "", f.cell(**band))
                res_refs = []
                for j, e in enumerate(exams):
                    mr = self.mx_row_of.get((x["sid"], e))
                    if mr is not None:
                        res_refs.append(f"'Overview'!{rc(mr, self.mx_cols['result'])}")
                if res_refs:
                    fml = '=""'
                    for ref in res_refs:
                        fml = f'=IF({ref}<>"",{ref},{fml[1:]})'
                    ws.write_formula(rr, c_lres, fml, f.cell(align="center", **band), x["latest_result"])
                else:
                    ws.write_string(rr, c_lres, "", f.cell(**band))
                ws.write_formula(rr, c_watch, f'=IF(OR({rc(rr, c_drop)}="Yes",{rc(rr, c_lres)}="Not passed"),"Yes","")',
                                 f.cell(align="center", bold=True, font_color=theme.RED, **band), "Yes" if x["watch"] else "")
            last = r + len(rows)
            if ne > 1:
                ws.conditional_format(first, c_d0, last, c_latest, {"type": "icon_set", "icon_style": "3_arrows",
                                                                    "icons": [{"criteria": ">=", "type": "number", "value": 2},
                                                                              {"criteria": ">", "type": "number", "value": -2}]})
            # lists: most improved + watch list (helper columns far right)
            hc = c_watch + 3
            ws.set_column(hc, hc + 1, None, None, {"hidden": True})
            for i in range(len(rows)):
                rr = first + i
                L = rc(rr, c_latest)
                ws.write_formula(rr, hc, f'=IF(ISNUMBER({L}),{L}-ROW()/1000000000,"")', None,
                                 float(rows[i]["latest_change"]) - (rr + 1) / 1e9 if rows[i]["latest_change"] is not None else "")
            # fix running count to ignore blanks above (use MAX of above)
            for i in range(len(rows)):
                rr = first + i
                Wc = rc(rr, c_watch)
                fml = f'=IF({Wc}="Yes",{("MAX(" + rc(first, hc + 1, True, False) + ":" + rc(rr - 1, hc + 1) + ")+1") if i else "1"},"")'
                cnt = sum(1 for y in rows[:i + 1] if y["watch"])
                ws.write_formula(rr, hc + 1, fml, None, cnt if rows[i]["watch"] else "")
            lr = last + 2
            ws.write(lr, 1, "Most improved (latest change)", f.section())
            ws.write(lr, 6, "Watch list (dropped twice in a row, or not passed in the latest exam)", f.section())
            namer = f"{rc(first, 1, True, True)}:{rc(last, 1, True, True)}"
            hrng = f"{rc(first, hc, True, True)}:{rc(last, hc, True, True)}"
            wrng = f"{rc(first, hc + 1, True, True)}:{rc(last, hc + 1, True, True)}"
            lrng = f"{rc(first, c_latest, True, True)}:{rc(last, c_latest, True, True)}"
            improved = sorted([y for y in rows if y["latest_change"] is not None],
                              key=lambda y: -(float(y["latest_change"])))
            watch = [y for y in rows if y["watch"]]
            for k in range(10):
                rr = lr + 1 + k
                ws.write_formula(rr, 1, f'=IFERROR(INDEX({namer},MATCH(LARGE({hrng},{k + 1}),{hrng},0)),"")', f.cell(),
                                 improved[k]["name"] if k < len(improved) else "")
                ws.write_formula(rr, 2, f'=IFERROR(INDEX({lrng},MATCH(LARGE({hrng},{k + 1}),{hrng},0)),"")', f.num(1),
                                 _num(improved[k]["latest_change"]) if k < len(improved) else "")
                ws.write_formula(rr, 6, f'=IFERROR(INDEX({namer},MATCH({k + 1},{wrng},0)),"")', f.cell(),
                                 watch[k]["name"] if k < len(watch) else "")
            ws.write(lr + 12, 6, "Only the first 10 are listed - filter the Watch column to see everyone.", f.note())
            r = lr + 14

    # ------------------------------------------------------------------ Teachers
    def write_teachers(self):
        """Teacher analysis with formulas over Subject Results: per teacher, per class-section, per exam;
        and every teacher of a subject side by side (latest exam of each section)."""
        from ..teachers import analyse
        ws, f, cfg = self.sheets["Teachers"], self.f, self.cfg
        an = analyse(self.res, self.teachers)
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 24)
        ws.set_column(2, 2, 24)
        ws.set_column(3, 9, 12)
        self.banner(ws, "Teachers", "How the students each teacher teaches do in that teacher's subject. 'vs own average' "
                                    "is the fair check: each student's mark in the subject minus that student's average over "
                                    "all their subjects - it does not depend on how strong the section is.", 9)
        heads = ["Class", "Exam", "Students", "Average %", "Pass %", "vs own average", "vs class average", "Not passed"]
        num1 = f.num(1)
        gap = f.gap("%")
        # the detail goes below the comparison tables, which point at it
        n_cmp = sum(len(c["rows"]) + 3 for c in an["comparison"])
        rr = 4 + 2 + n_cmp + 1
        ws.write(rr, 1, "Teacher by teacher", f.section())
        rr += 1
        detail = {}
        for card in an["cards"]:
            rr += 1
            ws.write_string(rr, 1, card["name"], f.get(bold=True, font_size=12, font_color=theme.NAVY))
            ws.write_string(rr, 2, card["subject_name"] + " · " + ", ".join(card["classes"]), f.note())
            rr += 1
            for c, h in enumerate(heads, 1):
                ws.write(rr, c, h, f.header())
            latest_rows, change_cells = [], []
            subj = cfg.subject_name(card["subject"]) if card["subject"] else ""
            for sec in card["sections"]:
                if sec["missing"]:
                    rr += 1
                    ws.write_string(rr, 1, sec["label"], f.cell())
                    ws.write_string(rr, 2, "no marks uploaded", f.note())
                    continue
                first_row = None
                for e in sec["by_exam"]:
                    rr += 1
                    if first_row is None:
                        first_row = rr
                    ws.write_string(rr, 1, sec["label"], f.cell(bold=True))
                    ws.write_string(rr, 2, e["name"], f.cell())
                    crit = 'SR_Class,"%s",SR_Section,"%s",SR_Subject,"%s",SR_Exam,"%s"' % (
                        sec["cls"], sec["section"], subj, e["name"])
                    yes = 'COUNTIFS(%s,SR_Passed,"Yes")' % crit
                    no = 'COUNTIFS(%s,SR_Passed,"No")' % crit
                    ws.write_formula(rr, 3, '=COUNTIFS(%s,SR_Status,"OK")' % crit, f.cell(align="center"), e["n"])
                    ws.write_formula(rr, 4, '=IFERROR(AVERAGEIFS(SR_Pct,%s,SR_Status,"OK"),"")' % crit, num1, _num(e["avg"]))
                    ws.write_formula(rr, 5, '=IFERROR(%s/(%s+%s)*100,"")' % (yes, yes, no), num1, _num(e["pass_pct"]))
                    ws.write_formula(rr, 6, '=IFERROR(AVERAGEIFS(SR_VOwn,%s,SR_Status,"OK"),"")' % crit, gap,
                                     _num(e["vs_own"]))
                    si = self.stats_index.get((sec["cls"], e["exam"], card["subject"]))
                    ws.write_formula(rr, 7, ('=IFERROR(%s-_stats!%s,"")' % (rc(rr, 4), rc(si, 3))) if si else '=""', gap,
                                     _num(e["vs_class"]))
                    f.about_same(ws, rr, 6, rr, 7)
                    ws.write_formula(rr, 8, "=" + no, f.cell(align="center"), e["not_passed"])
                latest_rows.append((rr, sec))
                if len(sec["by_exam"]) > 1:
                    change_cells.append("%s-%s" % (rc(rr, 4), rc(first_row, 4)))
            detail[card["id"]] = (latest_rows, change_cells)
            for line in card["notes"]:
                rr += 1
                ws.write_string(rr, 1, "• " + line, f.note())
            rr += 1
        # comparison: every teacher of a subject side by side (latest exam of each of their sections)
        r = 4
        ws.write(r, 1, "Teachers of the same subject, side by side (latest exam)", f.section())
        r += 2
        cmp_heads = ["Teacher", "Classes", "Students", "Average %", "Pass %", "vs own average", "Change since first exam",
                     "Not passed", "Fair check", "Likely range"]
        ws.set_column(9, 9, 24)
        ws.set_column(10, 10, 16)
        for block in an["comparison"]:
            ws.write_string(r, 1, block["name"], f.get(bold=True, font_color=theme.NAVY))
            r += 1
            for c, h in enumerate(cmp_heads, 1):
                ws.write(r, c, h, f.header())
            for row in block["rows"]:
                r += 1
                lat, chg = detail.get(row["id"], ([], []))
                ws.write_string(r, 1, row["name"], f.cell(bold=True))
                ws.write_string(r, 2, row["classes"], f.cell())
                fx = row["fair"] or {}
                vcol = {"Clear positive impact": theme.GREEN, "Worth a conversation": theme.AMBER}.get(fx.get("verdict"), theme.TEXT)
                ws.write_string(r, 9, fx.get("verdict", ""), f.cell(bold=True, font_color=vcol))
                ws.write_string(r, 10, ("%s (%s)" % (theme.gap_text(fx["effect"], "%"), theme.range_text(fx["low"], fx["high"], "%")))
                                if fx.get("effect") is not None else "-", f.cell(align="center"))
                if not lat:
                    continue
                cnt = "+".join(rc(x, 3) for x, _ in lat)
                ws.write_formula(r, 3, "=" + cnt, f.cell(align="center"), row["students_latest"])
                wsum = "+".join("N(%s)*N(%s)" % (rc(x, 3), rc(x, 4)) for x, _ in lat)
                ws.write_formula(r, 4, '=IFERROR((%s)/(%s),"")' % (wsum, cnt), num1, _num(row["avg"]))
                subj = cfg.subject_name(block["subject"])
                yes = "+".join('COUNTIFS(SR_Class,"%s",SR_Section,"%s",SR_Subject,"%s",SR_Exam,"%s",SR_Passed,"Yes")'
                               % (s["cls"], s["section"], subj, s["latest"]["name"]) for _, s in lat)
                no = "+".join(rc(x, 8) for x, _ in lat)
                ws.write_formula(r, 5, '=IFERROR((%s)/((%s)+(%s))*100,"")' % (yes, yes, no), num1, _num(row["pass_pct"]))
                vsum = "+".join("N(%s)*N(%s)" % (rc(x, 3), rc(x, 6)) for x, _ in lat)
                ws.write_formula(r, 6, '=IFERROR((%s)/(%s),"")' % (vsum, cnt), f.gap("%"), _num(row["vs_own"]))
                f.about_same(ws, r, 6, r, 6)
                ws.write_formula(r, 7, ('=IFERROR(AVERAGE(%s),"")' % ",".join(chg)) if chg else '=""', num1,
                                 _num(row["change"]))
                ws.write_formula(r, 8, "=" + no, f.cell(align="center"), row["not_passed"])
            r += 2
        for c in (6, 7):
            ws.conditional_format(4, c, rr, c, {"type": "cell", "criteria": "<", "value": 0,
                                                "format": f.get(font_color=theme.RED)})
            ws.conditional_format(4, c, rr, c, {"type": "cell", "criteria": ">", "value": 0,
                                                "format": f.get(font_color=theme.GREEN)})
        self._teacher_charts(ws, an["cards"], rr + 2, 12)

    def _teacher_charts(self, ws, cards, r, col):
        """A small table (for the charts) and two charts: each teacher's 'vs own average', and how many students
        did better / about the same / worse in the teacher's subject than in their other subjects."""
        f = self.f
        cards = [c for c in cards if c.get("viz") and sum(c["viz"]["split"].values())]
        if not cards:
            return
        ws.write(r, 1, "For the charts", f.section())
        r += 1
        heads = ["Teacher", "Subject", "Better", "About the same", "Worse", "vs own average"]
        for c, h in enumerate(heads, 1):
            ws.write(r, c, h, f.header())
        first = r + 1
        for c in cards:
            r += 1
            sp = c["viz"]["split"]
            o = c.get("overall") or {}
            ws.write_string(r, 1, c["name"], f.cell(bold=True))
            ws.write_string(r, 2, c["subject_name"], f.cell())
            ws.write(r, 3, sp["better"], f.cell(align="center"))
            ws.write(r, 4, sp["same"], f.cell(align="center"))
            ws.write(r, 5, sp["worse"], f.cell(align="center"))
            ws.write(r, 6, _num(o.get("vs_own")), f.gap("%"))
        last = r
        f.about_same(ws, first, 6, last, 6)
        name = ws.get_name()
        ch = self.wb.add_chart({"type": "bar"})
        ch.add_series({"name": "vs own average (points)", "categories": [name, first, 1, last, 1],
                       "values": [name, first, 6, last, 6], "fill": {"color": theme.BLUE},
                       "invert_if_negative": False, "data_labels": {"value": True, "num_format": "0.0"}})
        ch.set_title({"name": "Students vs their own average, by teacher", "name_font": {"size": 11}})
        ch.set_legend({"none": True})
        ch.set_y_axis({"reverse": True})
        ch.set_size({"width": 560, "height": 90 + 26 * len(cards)})
        ws.insert_chart(4, col, ch)
        st = self.wb.add_chart({"type": "bar", "subtype": "percent_stacked"})
        for k, (lab, color) in enumerate([("Better", theme.GREEN), ("About the same", "#9FB3C4"), ("Worse", theme.RED)]):
            st.add_series({"name": lab, "categories": [name, first, 1, last, 1], "values": [name, first, 3 + k, last, 3 + k],
                           "fill": {"color": color}, "gap": 60})
        st.set_title({"name": "Did better / same / worse than in their other subjects", "name_font": {"size": 11}})
        st.set_legend({"position": "bottom"})
        st.set_y_axis({"reverse": True})
        st.set_size({"width": 560, "height": 110 + 26 * len(cards)})
        ws.insert_chart(4 + 6 + int((90 + 26 * len(cards)) / 20), col, st)

    # ------------------------------------------------------------------ Validation report
    def write_validation(self):
        ws, f, ds = self.sheets["Validation Report"], self.f, self.ds
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 10)
        ws.set_column(2, 2, 22)
        ws.set_column(3, 3, 24)
        ws.set_column(4, 5, 14)
        ws.set_column(6, 6, 34)
        ws.set_column(7, 7, 80)
        self.banner(ws, "Validation Report", "Everything that was checked. Errors are marks left out until corrected.", 7)
        sev_order = {"error": 0, "warning": 1, "info": 2}
        issues = sorted(ds.issues, key=lambda i: (sev_order.get(i.severity, 3), i.code))
        cnt = {s: sum(1 for i in issues if i.severity == s) for s in sev_order}
        r = 4
        summary = [("Students", len(ds.students)), ("Mark records read", len(ds.marks)),
                   ("Subject results", len(self.res.rows)), ("Errors", cnt["error"]), ("Warnings", cnt["warning"]),
                   ("Notes", cnt["info"])]
        for i, (k, v) in enumerate(summary):
            ws.write(r, 1 + i, k, f.get(font_color=theme.MUTED, font_size=9, bold=True, align="center", bg_color=theme.TINT))
            ws.write_number(r + 1, 1 + i, v, f.get(font_name=theme.TITLE_FONT, font_size=16, font_color=theme.NAVY,
                                                   align="center", bg_color=theme.TINT))
        r += 3
        ws.write(r, 1, "Files read", f.section())
        for name, sheet, rows, skipped in ds.raw_sheets:
            r += 1
            ws.write_string(r, 1, "skipped" if skipped else "read", f.cell(font_color=theme.MUTED if skipped else theme.GREEN))
            ws.write_string(r, 2, name, f.cell())
            ws.write_string(r, 3, sheet, f.cell())
            ws.write_string(r, 4, f"{len(rows)} rows", f.cell())
        r += 2
        heads = ["Severity", "Problem", "Student", "Subject", "Exam", "Where", "Details"]
        for c, h in enumerate(heads, 1):
            ws.write(r, c, h, f.header())
        hr = r
        sev_fmt = {"error": f.cell(bold=True, font_color=theme.RED, bg_color=theme.RED_BG),
                   "warning": f.cell(bold=True, font_color=theme.AMBER, bg_color=theme.AMBER_BG),
                   "info": f.cell(font_color=theme.MUTED)}
        cfg = self.cfg
        for it in issues:
            r += 1
            st = ds.students.get(it.sid)
            vals = [it.severity.title(), it.code.replace("_", " "), st.name if st else "",
                    cfg.subject_name(it.subject) if it.subject else "", cfg.exam_name(it.exam) if it.exam else "",
                    it.ref.text() if it.ref else "", it.message]
            for c, v in enumerate(vals, 1):
                fmt = sev_fmt.get(it.severity) if c == 1 else f.cell(text_wrap=(c == 7), quote_prefix=formula_like(v))
                ws.write_string(r, c, v, fmt)
        if issues:
            ws.autofilter(hr, 1, r, 7)
        else:
            ws.write(hr + 1, 1, "No problems found.", f.cell())
        ws.freeze_panes(hr + 1, 0)

    # ------------------------------------------------------------------ Source data
    def write_source(self):
        ws, f = self.sheets["Source Data"], self.f
        ws.set_column(0, 60, 12)
        ws.write(0, 0, "Exact copy of everything that was uploaded (as text). This sheet is protected so it is not "
                       "changed by accident - the original files are never modified.", f.note())
        r = 2
        title = f.get(bold=True, font_color=theme.WHITE, bg_color=theme.NAVY)
        plain = f.get(font_size=9)
        for name, sheet, rows, skipped in self.ds.raw_sheets:
            ws.write_string(r, 0, f"{name} › {sheet}" + ("  (not used)" if skipped else ""), title)
            r += 1
            for row in rows:
                for c, v in enumerate(row[:200]):
                    if v != "":
                        ws.write_string(r, c, v, f.get(font_size=9, quote_prefix=True) if formula_like(v) else plain)
                r += 1
                if r > 1000000:
                    break
            r += 1
        ws.protect("", {"autofilter": True, "sort": False, "select_locked_cells": True})

    # ------------------------------------------------------------------ extras from word commands
    def write_extras(self):
        from .extras import write_extras
        write_extras(self)

    # ------------------------------------------------------------------ meta (for re-upload)
    def write_meta(self):
        ws = self.sheets["_meta"]
        from ..snapshot import dump
        text = json.dumps(dump(self), separators=(",", ":"))
        ws.write_string(0, 0, "RDPS-MARKS-STUDIO")
        ws.write_string(0, 1, "1")
        chunk = 30000
        for i in range(0, len(text), chunk):
            ws.write_string(1 + i // chunk, 0, text[i:i + chunk])


def write_workbook(ds, res, recipe=None, vba=None, logo=None, generated=None, teachers=None):
    return SchoolWorkbook(ds, res, recipe=recipe, vba=vba, logo=logo, generated=generated, teachers=teachers).build()
