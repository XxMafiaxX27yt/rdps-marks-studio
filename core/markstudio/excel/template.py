"""The ready-made marks template teachers can fill in (optionally pre-filled with
the student list). Every mark cell only accepts 0..maximum or a leave code, so
typing mistakes are stopped while typing.

One file per class. Each exam sheet has only that class's subjects:
* Classes I-X: the fixed subjects + one 'Language' column (each student's own
  language, picked once on the Students sheet). Internal marks (portfolio,
  project, notebook - and the AI practical parts) are on their own '... Internals'
  sheets, which can simply be left empty: then only the written marks count.
* Classes XI-XII: the subjects of every stream; cells of subjects a student does
  not take turn grey once the Students sheet lists their subjects."""
import io

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from . import theme
from .theme import Formats


def class_subjects(cfg, cls):
    """Subjects offered in a class: the fixed list of a junior class, or every subject in the group table."""
    off = cfg.class_offer(cls)
    if off:
        return cfg.order_subjects(set(off.get("subjects", [])))
    codes = set()
    for g in cfg.groups:
        codes.update(g["core"])
        for ch in g.get("choices", []):
            codes.update(ch)
    return cfg.order_subjects(codes)


LANG = "@LANG"


def _slots(cfg, cls):
    """Subjects shown as columns, with the language slot in its place (after Hindi / English)."""
    subs = class_subjects(cfg, cls)
    langs = cfg.languages_for(cls)
    if not langs:
        return subs
    out = [s for s in subs if s not in langs]
    pos = next((i + 1 for i, s in enumerate(out) if s in ("302",)), 1 if out and out[0] == "301" else 0)
    return out[:pos] + [LANG] + out[pos:]


def _rep(cfg, cls, slot):
    return (cfg.languages_for(cls) or ["302"])[0] if slot == LANG else slot


def _name(cfg, slot):
    return "Language" if slot == LANG else cfg.subject_name(slot)


def exam_columns(cfg, cls, exam, slots):
    """[(heading, slot, component, max)] for one exam sheet (written / theory and practical only)."""
    out = []
    for s in slots:
        comps = cfg.components(cls, _rep(cfg, cls, s), exam)
        if not comps:
            continue
        name = _name(cfg, s)
        second = cfg.scheme(cls, _rep(cfg, cls, s), exam)["second"]
        if second and not second["optional"]:
            out.append((f"{name} Th", s, "theory", comps["theory"]))
            out.append((f"{name} Pr", s, "practical", comps["practical"]))
        else:
            out.append((name, s, "theory", comps["theory"]))
    return out


def internal_columns(cfg, cls, exam, slots):
    """[(subject heading, part heading, slot, part key, max)] for an internals sheet (parts typed by teachers;
    the PT part is worked out from the periodic test, so it is not typed)."""
    out = []
    for s in slots:
        for key, mx in cfg.subparts(cls, _rep(cfg, cls, s), exam):
            if key == "i_pt":
                continue
            out.append((_name(cfg, s), cfg.part_label(key), s, key, mx))
    return out


def template_bytes(cfg, cls, students=None, marks=None, exams=None, title_note="", teachers=None):
    """students: list of dicts (adm_no, roll, board_roll, name, father, mother, section, group, subjects[codes], language)
    marks: {(adm_no, exam, subject, component): text}"""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_formulas": False})
    wb.set_properties({"title": f"{cfg.rules['school_short']} marks template - {cfg.class_label(cls)}",
                       "author": cfg.rules["school_name"], "comments": "Made by RDPS Marks Studio"})
    f = Formats(wb)
    students = students or []
    streams = cfg.has_streams(cls)
    subjects = class_subjects(cfg, cls)
    slots = _slots(cfg, cls)
    langs = cfg.languages_for(cls)
    exams = exams or cfg.class_exams(cls)
    codes = [x["code"] for x in cfg.rules["leave_codes"]]
    band = f.cell(bg_color=theme.TINT2)

    # ---- instructions
    ws = wb.add_worksheet("How to fill")
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 3)
    ws.set_column(1, 1, 30)
    ws.set_column(2, 8, 16)
    ws.write(1, 1, f"{cfg.rules['school_name']} - marks template", f.title())
    ws.write(2, 1, f"{cfg.class_label(cls)} · Academic year {cfg.rules['academic_year']} {title_note}", f.subtitle())
    if streams:
        steps = ["1. Fill the Students sheet once (one row per student). Admission No must be unique.",
                 "2. Pick each student's subjects in Subject 1-6 (the dropdown lists every subject).",
                 "3. Type marks in each exam sheet. Cells of subjects a student does not take turn grey.",
                 f"4. Absent or on leave? Type a code instead of marks: {', '.join(codes)} (see the table below).",
                 "5. A blank cell in a subject the student takes is treated as Absent (AB).",
                 "6. Do not type totals or percentages - the website works them out.",
                 "7. Upload this file on the website. It is read automatically."]
    else:
        steps = ["1. Fill the Students sheet once (one row per student). Admission No must be unique.",
                 f"2. Pick each student's language in the Language column ({', '.join(cfg.subject_name(x) for x in langs)}).",
                 "3. Type the written marks in each exam sheet. The 'Language' column is each student's own language.",
                 "4. Internal marks (portfolio, project, notebook) go on the '... Internals' sheets - OPTIONAL:",
                 "    leave them empty and the subject is worked out of the written paper alone.",
                 "    The PT part of the internals is worked out from PT1 / PT2 automatically - do not type it.",
                 f"5. Absent or on leave? Type a code instead of marks: {', '.join(codes)}. A blank mark = Absent (AB).",
                 "6. Do not type totals or percentages - the website works them out. Upload this file on the website."]
    for i, s in enumerate(steps):
        ws.write(4 + i, 1, s, f.get(font_size=11))
    r = 5 + len(steps)
    ws.write(r, 1, "Leave codes", f.section())
    r += 1
    for h, c in zip(["Code", "Meaning", "Counts as not passed?"], range(1, 4)):
        ws.write(r, c, h, f.header())
    for x in cfg.rules["leave_codes"]:
        r += 1
        ws.write(r, 1, x["code"], f.cell(bold=True))
        ws.write(r, 2, x["label"], f.cell())
        ws.write(r, 3, "Yes" if x["counts_as_fail"] else "No", f.cell(align="center"))
    r += 2
    ws.write(r, 1, "Maximum marks", f.section())
    r += 1
    for c, h in enumerate(["Subject"] + [cfg.exam_name(e) for e in exams], 1):
        ws.write(r, c, h, f.header())
    for s in slots:
        r += 1
        ws.write(r, 1, _name(cfg, s) + (f" ({' / '.join(cfg.subject_name(x) for x in langs)})" if s == LANG else ""), f.cell())
        for c, e in enumerate(exams, 2):
            sc = cfg.scheme(cls, _rep(cfg, cls, s), e)
            if not sc:
                txt = "-"
            elif sc["second"]:
                txt = f"{int(sc['theory'])} + {int(sc['second']['max'])} {sc['second']['label'].lower()}"
            else:
                txt = str(int(sc["theory"]))
            ws.write(r, c, txt, f.cell(align="center"))

    # ---- lists (hidden) for dropdowns
    lst = wb.add_worksheet("Lists")
    names = [cfg.subject_name(s) for s in subjects]
    for i, n in enumerate(names):
        lst.write(i, 0, n)
    for i, g in enumerate(cfg.groups):
        lst.write(i, 1, g["id"])
    for i, x in enumerate(langs):
        lst.write(i, 2, cfg.subject_name(x))
    lst.hide()

    # ---- students
    ws = wb.add_worksheet("Students")
    ws.freeze_panes(1, 0)
    heads = ["S.No", "Admission No", "Roll No"] + (["Board Roll No"] if cls in ("X", "XII") else []) + \
            ["Student Name", "Father's Name", "Mother's Name", "Class", "Section"]
    widths = [6, 13, 9] + ([14] if cls in ("X", "XII") else []) + [26, 24, 24, 7, 8]
    if streams:
        heads += ["Group", "Subject 1", "Subject 2", "Subject 3", "Subject 4", "Subject 5", "Subject 6"]
        widths += [7, 18, 18, 18, 18, 18, 18]
    elif langs:
        heads += ["Language"]
        widths += [16]
    for c, (h, w) in enumerate(zip(heads, widths)):
        ws.write(0, c, h, f.header())
        ws.set_column(c, c, w)
    ws.set_row(0, 30)
    n_rows = max(len(students), 60)
    c_first_extra = heads.index("Section") + 1
    if streams:
        ws.data_validation(1, c_first_extra + 1, n_rows + 100, c_first_extra + 6,
                           {"validate": "list", "source": f"=Lists!$A$1:$A${len(names)}",
                            "error_title": "Subject", "error_message": "Pick a subject from the list."})
        ws.data_validation(1, c_first_extra, n_rows + 100, c_first_extra,
                           {"validate": "list", "source": f"=Lists!$B$1:$B${len(cfg.groups)}"})
    elif langs:
        ws.data_validation(1, c_first_extra, n_rows + 100, c_first_extra,
                           {"validate": "list", "source": f"=Lists!$C$1:$C${len(langs)}",
                            "error_title": "Language", "error_message": "Pick the student's language from the list."})
    for i, s in enumerate(students):
        rr = i + 1
        fmt = band if i % 2 else f.cell()
        vals = [i + 1, s.get("adm_no", ""), s.get("roll", "")] + ([s.get("board_roll", "")] if cls in ("X", "XII") else []) + \
               [s.get("name", ""), s.get("father", ""), s.get("mother", ""), cls, s.get("section", "")]
        if streams:
            vals += [s.get("group", "")] + [cfg.subject_name(x) for x in s.get("subjects", [])][:6]
        elif langs:
            lang = s.get("language") or next((x for x in s.get("subjects", []) if x in langs), "")
            vals += [cfg.subject_name(lang) if lang else ""]
        for c, v in enumerate(vals):
            if isinstance(v, int):
                ws.write_number(rr, c, v, fmt)
            else:
                ws.write_string(rr, c, str(v), fmt)
    ws.autofilter(0, 0, max(1, len(students)), len(heads) - 1)
    stu_rows = max(len(students), 60) + 100
    subj_cols = (xl_col_to_name(c_first_extra + 1), xl_col_to_name(c_first_extra + 6)) if streams else None

    def lang_of(s):
        return s.get("language") or next((x for x in s.get("subjects", []) if x in langs), "")

    def mark_text(s, e, slot, comp):
        if marks is None:
            return None
        sub = lang_of(s) if slot == LANG else slot
        if not sub:
            return None
        return marks.get((str(s.get("adm_no", "")), e, sub, comp))

    def write_mark(ws, rr, c, v, fmt):
        if v is None or v == "":
            ws.write_blank(rr, c, None, fmt)
            return
        try:
            num = float(v)
            ws.write_number(rr, c, int(num) if num == int(num) else num, fmt)
        except ValueError:
            ws.write_string(rr, c, v, fmt)

    def validation(ws, c, mx, h, first_row):
        letter = xl_col_to_name(c)
        top = f"{letter}{first_row + 1}"
        rule = f"=OR(AND(ISNUMBER({top}),{top}>=0,{top}<={float(mx):g})," + \
               ",".join(f'UPPER({top})="{x}"' for x in codes) + ")"
        ws.data_validation(first_row, c, first_row + n_rows + 300, c, {
            "validate": "custom", "value": rule, "ignore_blank": True,
            "input_title": h[:32], "input_message": f"Marks out of {float(mx):g}, or {', '.join(codes)}",
            "error_title": "Check this mark",
            "error_message": f"{h} must be a number from 0 to {float(mx):g}, or a leave code ({', '.join(codes)})."})

    title_fmt = f.get(font_name=theme.TITLE_FONT, font_size=13, font_color=theme.WHITE, bg_color=theme.NAVY, align="left")
    fixed = ["Admission No", "Roll No", "Student Name", "Section"]

    # ---- one sheet per exam (written / theory + practical)
    for e in exams:
        ws = wb.add_worksheet(cfg.exam_name(e)[:31])
        cols = exam_columns(cfg, cls, e, slots)
        ws.merge_range(0, 0, 0, 3 + max(1, len(cols)), f"{cfg.class_label(cls)} - {cfg.exam_name(e)} - marks", title_fmt)
        ws.set_row(0, 24)
        for c, h in enumerate(fixed):
            ws.write(1, c, h, f.header())
        ws.set_column(0, 1, 11)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 3, 8)
        for i, (h, s, comp, mx) in enumerate(cols):
            c = 4 + i
            ws.write(1, c, h, f.header())
            note = f"Out of {float(mx):g}. Or a leave code: {', '.join(codes)}"
            if s == LANG:
                note = "Each student's own language (from the Students sheet). " + note
            ws.write_comment(1, c, note, {"x_scale": 1.4, "y_scale": 0.6})
            ws.set_column(c, c, 11 if comp == "theory" else 10)
            validation(ws, c, mx, h, 2)
            if streams and s != LANG:
                # grey = this student does not take the subject (from the Students sheet)
                L = xl_col_to_name(c)
                nm = cfg.subject_name(s).replace('"', '""')
                ws.conditional_format(2, c, n_rows + 300, c, {
                    "type": "formula",
                    "criteria": f'=AND($A3<>"",COUNTIF(Students!$B:$B,$A3)>0,'
                                f'COUNTIF(INDEX(Students!${subj_cols[0]}$1:${subj_cols[1]}${stu_rows},'
                                f'MATCH($A3,Students!$B$1:$B${stu_rows},0),0),"{nm}")=0)',
                    "format": wb.add_format({"bg_color": theme.GREY_BG, "font_color": "#9AA5B1"})})
        ws.set_row(1, 32)
        ws.freeze_panes(2, 3)
        for i, s in enumerate(students):
            rr = i + 2
            fmt = band if i % 2 else f.cell()
            ws.write_string(rr, 0, str(s.get("adm_no", "")), fmt)
            ws.write_string(rr, 1, str(s.get("roll", "")), fmt)
            ws.write_string(rr, 2, s.get("name", ""), fmt)
            ws.write_string(rr, 3, s.get("section", ""), fmt)
            for j, (h, sub, comp, mx) in enumerate(cols):
                cfmt = f.cell(align="center", bg_color=theme.TINT2) if i % 2 else f.cell(align="center")
                taken = sub == LANG or not streams or sub in s.get("subjects", [])
                write_mark(ws, rr, 4 + j, mark_text(s, e, sub, comp) if taken else None, cfmt)

    # ---- internal marks (optional), one sheet per big exam that has parts
    for e in exams:
        cols = internal_columns(cfg, cls, e, slots)
        if not cols:
            continue
        ws = wb.add_worksheet(f"{cfg.exam_name(e)} Internals"[:31])
        ws.merge_range(0, 0, 0, 3 + len(cols),
                       f"{cfg.class_label(cls)} - {cfg.exam_name(e)} - internal marks (optional: leave empty if not given)",
                       title_fmt)
        ws.set_row(0, 24)
        for c, h in enumerate(fixed):
            ws.merge_range(1, c, 2, c, h, f.header())
        ws.set_column(0, 1, 11)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 3, 8)
        # subject names over their parts (row 2), part names below (row 3)
        i = 0
        while i < len(cols):
            j = i
            while j + 1 < len(cols) and cols[j + 1][2] == cols[i][2]:
                j += 1
            subj_fmt = f.get(bold=True, font_color=theme.WHITE, bg_color=theme.BLUE if (i // 3) % 2 == 0 else theme.NAVY,
                             align="center", border=1, border_color=theme.NAVY)
            if j > i:
                ws.merge_range(1, 4 + i, 1, 4 + j, cols[i][0], subj_fmt)
            else:
                ws.write(1, 4 + i, cols[i][0], subj_fmt)
            i = j + 1
        for k, (sname, ph, s, key, mx) in enumerate(cols):
            c = 4 + k
            ws.write(2, c, ph, f.header())
            ws.write_comment(2, c, f"{sname} {ph.lower()}: out of {float(mx):g}. Or a leave code.", {"x_scale": 1.3, "y_scale": 0.5})
            ws.set_column(c, c, 10)
            validation(ws, c, mx, f"{sname} {ph}", 3)
        ws.set_row(2, 30)
        ws.freeze_panes(3, 3)
        for i, s in enumerate(students):
            rr = i + 3
            fmt = band if i % 2 else f.cell()
            ws.write_string(rr, 0, str(s.get("adm_no", "")), fmt)
            ws.write_string(rr, 1, str(s.get("roll", "")), fmt)
            ws.write_string(rr, 2, s.get("name", ""), fmt)
            ws.write_string(rr, 3, s.get("section", ""), fmt)
            for k, (sname, ph, sub, key, mx) in enumerate(cols):
                cfmt = f.cell(align="center", bg_color=theme.TINT2) if i % 2 else f.cell(align="center")
                write_mark(ws, rr, 4 + k, mark_text(s, e, sub, key), cfmt)

    # ---- teachers (optional): who teaches what, for the teacher analysis
    ws = wb.add_worksheet("Teachers")
    ws.merge_range(0, 0, 0, 2, "Teachers (optional) - one row per teacher and subject", title_fmt)
    for c, (h, w) in enumerate([("Teacher Name", 26), ("Subject", 20), ("Classes (e.g. VI-A, VI-B)", 34)]):
        ws.write(1, c, h, f.header())
        ws.set_column(c, c, w)
    ws.data_validation(2, 1, 400, 1, {"validate": "list", "source": f"=Lists!$A$1:$A${len(names)}",
                                      "ignore_blank": True, "error_type": "warning",
                                      "error_title": "Subject", "error_message": "Pick a subject from the list."})
    for i, t in enumerate(teachers or []):
        ws.write_string(2 + i, 0, t.get("name", ""))
        ws.write_string(2 + i, 1, cfg.subject_name(t["subject"]) if t.get("subject") in cfg.subjects else t.get("subject", ""))
        ws.write_string(2 + i, 2, ", ".join(t["classes"]) if isinstance(t.get("classes"), list) else t.get("classes", ""))
    wb.close()
    return buf.getvalue()
