"""The ready-made marks template teachers can fill in (optionally pre-filled with
the student list). Every mark cell only accepts 0..maximum or a leave code, so
typing mistakes are stopped while typing."""
import io

import xlsxwriter

from . import theme
from .theme import Formats


def class_subjects(cfg, cls):
    """Subjects offered in a class = every subject in the group table."""
    codes = set()
    for g in cfg.groups:
        codes.update(g["core"])
        for ch in g.get("choices", []):
            codes.update(ch)
    return cfg.order_subjects(codes)


def exam_columns(cfg, exam, subjects):
    """[(heading, subject, component, max)] for one exam sheet."""
    out = []
    for s in subjects:
        comps = cfg.components(s, exam)
        name = cfg.subject_name(s)
        if len(comps) == 1:
            out.append((name, s, "theory", comps["theory"]))
        else:
            out.append((f"{name} Th", s, "theory", comps["theory"]))
            out.append((f"{name} Pr", s, "practical", comps["practical"]))
    return out


def template_bytes(cfg, cls, students=None, marks=None, exams=None, title_note=""):
    """students: list of dicts (adm_no, roll, board_roll, name, father, mother, section, group, subjects[codes])
    marks: {(adm_no, exam, subject, component): text}"""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_formulas": False})
    wb.set_properties({"title": f"{cfg.rules['school_short']} marks template - {cfg.class_label(cls)}",
                       "author": cfg.rules["school_name"], "comments": "Made by RDPS Marks Studio"})
    f = Formats(wb)
    students = students or []
    subjects = class_subjects(cfg, cls)
    exams = exams or cfg.class_exams(cls)
    codes = [x["code"] for x in cfg.rules["leave_codes"]]

    # ---- instructions
    ws = wb.add_worksheet("How to fill")
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 3)
    ws.set_column(1, 1, 30)
    ws.set_column(2, 4, 16)
    ws.write(1, 1, f"{cfg.rules['school_name']} - marks template", f.title())
    ws.write(2, 1, f"{cfg.class_label(cls)} · Academic year {cfg.rules['academic_year']} {title_note}", f.subtitle())
    steps = [
        "1. Fill the Students sheet once (one row per student). Admission No must be unique.",
        "2. Pick each student's subjects in Subject 1-6 (the dropdown lists every subject).",
        "3. Type marks in each exam sheet. Leave a subject blank if the student does not take it.",
        f"4. Absent or on leave? Type a code instead of marks: {', '.join(codes)} (see the table below).",
        "5. A blank cell in a subject the student takes is treated as Absent (AB).",
        "6. Do not type totals or percentages - the website works them out.",
        "7. Upload this file on the website. It is read automatically.",
    ]
    for i, s in enumerate(steps):
        ws.write(4 + i, 1, s, f.get(font_size=11))
    r = 13
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
    ws.set_column(5, 5 + len(exams), 16)
    for s in subjects:
        r += 1
        ws.write(r, 1, cfg.subject_name(s), f.cell())
        for c, e in enumerate(exams, 2):
            comps = cfg.components(s, e)
            txt = " + ".join(f"{int(v)} {k[:2].title()}" if len(comps) > 1 else str(int(v)) for k, v in comps.items())
            ws.write(r, c, txt, f.cell(align="center"))

    # ---- lists (hidden) for dropdowns
    lst = wb.add_worksheet("Lists")
    names = [cfg.subject_name(s) for s in subjects]
    for i, n in enumerate(names):
        lst.write(i, 0, n)
    for i, g in enumerate(cfg.groups):
        lst.write(i, 1, g["id"])
    lst.hide()

    # ---- students
    ws = wb.add_worksheet("Students")
    ws.freeze_panes(1, 0)
    heads = ["S.No", "Admission No", "Roll No", "Board Roll No", "Student Name", "Father's Name", "Mother's Name",
             "Class", "Section", "Group", "Subject 1", "Subject 2", "Subject 3", "Subject 4", "Subject 5", "Subject 6"]
    widths = [6, 13, 9, 14, 26, 24, 24, 7, 8, 7, 18, 18, 18, 18, 18, 18]
    for c, (h, w) in enumerate(zip(heads, widths)):
        ws.write(0, c, h, f.header())
        ws.set_column(c, c, w)
    ws.set_row(0, 30)
    n_rows = max(len(students), 60)
    ws.data_validation(1, 10, n_rows + 100, 15, {"validate": "list", "source": f"=Lists!$A$1:$A${len(names)}",
                                                 "error_title": "Subject", "error_message": "Pick a subject from the list."})
    ws.data_validation(1, 9, n_rows + 100, 9, {"validate": "list", "source": f"=Lists!$B$1:$B${len(cfg.groups)}"})
    band = f.cell(bg_color=theme.TINT2)
    for i, s in enumerate(students):
        rr = i + 1
        fmt = band if i % 2 else f.cell()
        vals = [i + 1, s.get("adm_no", ""), s.get("roll", ""), s.get("board_roll", ""), s.get("name", ""),
                s.get("father", ""), s.get("mother", ""), cls, s.get("section", ""), s.get("group", "")]
        vals += [cfg.subject_name(x) for x in s.get("subjects", [])][:6]
        for c, v in enumerate(vals):
            if isinstance(v, int):
                ws.write_number(rr, c, v, fmt)
            else:
                ws.write_string(rr, c, str(v), fmt)
    ws.autofilter(0, 0, max(1, len(students)), len(heads) - 1)

    # ---- one sheet per exam
    for e in exams:
        ws = wb.add_worksheet(cfg.exam_name(e)[:31])
        cols = exam_columns(cfg, e, subjects)
        ws.merge_range(0, 0, 0, 3 + len(cols), f"{cfg.class_label(cls)} - {cfg.exam_name(e)} - marks", f.get(
            font_name=theme.TITLE_FONT, font_size=13, font_color=theme.WHITE, bg_color=theme.NAVY, align="left"))
        ws.set_row(0, 24)
        fixed = ["Admission No", "Roll No", "Student Name", "Section"]
        for c, h in enumerate(fixed):
            ws.write(1, c, h, f.header())
        ws.set_column(0, 1, 11)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 3, 8)
        for i, (h, s, comp, mx) in enumerate(cols):
            c = 4 + i
            ws.write(1, c, h, f.header())
            ws.write_comment(1, c, f"Out of {int(mx)}. Or a leave code: {', '.join(codes)}",
                             {"x_scale": 1.4, "y_scale": 0.6})
            ws.set_column(c, c, 11 if comp == "theory" else 10)
            letter = xlsxwriter.utility.xl_col_to_name(c)
            rule = f"=OR(AND(ISNUMBER({letter}3),{letter}3>=0,{letter}3<={int(mx)})," + \
                   ",".join(f'UPPER({letter}3)="{x}"' for x in codes) + ")"
            ws.data_validation(2, c, n_rows + 300, c, {
                "validate": "custom", "value": rule, "ignore_blank": True,
                "input_title": h, "input_message": f"Marks out of {int(mx)}, or {', '.join(codes)}",
                "error_title": "Check this mark",
                "error_message": f"{h} must be a number from 0 to {int(mx)}, or a leave code ({', '.join(codes)})."})
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
                c = 4 + j
                cfmt = f.cell(align="center", bg_color=theme.TINT2) if i % 2 else f.cell(align="center")
                if marks is not None:
                    v = marks.get((str(s.get("adm_no", "")), e, sub, comp))
                    if v is None or v == "":
                        ws.write_blank(rr, c, None, cfmt)
                    else:
                        try:
                            num = float(v)
                            ws.write_number(rr, c, int(num) if num == int(num) else num, cfmt)
                        except ValueError:
                            ws.write_string(rr, c, v, cfmt)
                else:
                    ws.write_blank(rr, c, None, cfmt)
    wb.close()
    return buf.getvalue()
