"""The 'Board analysis' template: one Excel file the school office fills once a year -
Students (CBSE roll no, admission no, name, class, section) and Teachers (name, subject, sections).
Dropped back on any page, the Students sheet is read as a class list and the Teachers sheet as the teachers,
so every board-result student is placed in a section and every teacher is judged on their own sections."""
import io

import xlsxwriter

from . import theme
from .theme import Formats

STUDENT_HEADS = ["CBSE Roll No", "Admission No", "Name", "Class", "Section"]
TEACHER_HEADS = ["Name", "Subject", "Classes"]


def board_template_bytes(cfg, rows=400, example=False):
    """example=True: filled with the made-up students and teachers that go with the made-up CBSE results."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    f = Formats(wb)
    info = wb.add_worksheet("How to fill")
    st = wb.add_worksheet("Students")
    te = wb.add_worksheet("Teachers")
    # --- how to fill
    info.hide_gridlines(2)
    info.set_column(0, 0, 2)
    info.set_column(1, 1, 100)
    info.write(1, 1, "Board analysis template - RDPS Marks Studio" + (" - MADE-UP EXAMPLE" if example else ""), f.title())
    lines = [
        ("1. Students sheet", "One row per Class X and Class XII student: CBSE roll no (from the CBSE roll-number list / "
                              "Pariksha Sangam), admission no, name, class (X or XII) and section (A, B, C ...)."),
        ("2. Teachers sheet", "One row per teacher and subject: name, subject (as in the list below) and the classes they "
                              "taught, like  XII-A, XII-B  or  X-C."),
        ("3. Then", "Drop this file on the Board results page together with the CBSE result file. Students are matched by "
                    "CBSE roll no (then admission no, then name), and each teacher is judged only on their own sections."),
        ("Example student", "99100001 | 4512 | Asha Rao | XII | A        (made-up)"),
        ("Example teacher", "Ms. Example | Physics | XII-A, XII-B        (made-up)"),
        ("Keep it private", "The file is read on this computer only. Do not share it outside the school."),
    ]
    r = 3
    for head, text in lines:
        info.write(r, 1, head, f.get(bold=True, font_color=theme.NAVY))
        info.write(r + 1, 1, text, f.get(text_wrap=True, valign="top"))
        info.set_row(r + 1, 30)
        r += 3
    info.write(r, 1, "Subjects (write them like this)", f.get(bold=True, font_color=theme.NAVY))
    names = sorted({cfg.subject_name(c) for c in cfg.subject_order if cfg.subject_name(c)})
    for i, n in enumerate(names):
        info.write(r + 1 + i, 1, n)
    first, last = r + 1, r + len(names)
    # --- students
    for c, h in enumerate(STUDENT_HEADS):
        st.write(0, c, h, f.header())
    st.set_row(0, 24)
    st.set_column(0, 1, 15)
    st.set_column(2, 2, 30)
    st.set_column(3, 4, 10)
    st.freeze_panes(1, 0)
    st.data_validation(1, 3, rows, 3, {"validate": "list", "source": ["X", "XII"],
                                        "error_message": "Write X or XII"})
    st.data_validation(1, 4, rows, 4, {"validate": "list", "source": list("ABCDEFGH")})
    st.set_column(0, 1, 15, f.get(num_format="@"))          # roll / admission numbers stay as typed
    if example:
        from ..sample import sample_board_analysis
        studs, teach = sample_board_analysis(cfg)
        for r, row in enumerate(studs, 1):
            for c, v in enumerate(row):
                st.write_string(r, c, v)
        for r, row in enumerate(teach, 1):
            for c, v in enumerate(row):
                te.write_string(r, c, v)
    # --- teachers (filled above when this is the example)
    for c, h in enumerate(TEACHER_HEADS):
        te.write(0, c, h, f.header())
    te.set_row(0, 24)
    te.set_column(0, 0, 28)
    te.set_column(1, 1, 24)
    te.set_column(2, 2, 34)
    te.freeze_panes(1, 0)
    te.data_validation(1, 1, rows, 1, {"validate": "list", "source": f"='How to fill'!$B${first + 1}:$B${last + 1}",
                                       "error_type": "warning", "error_message": "Pick a subject from the list"})
    st.activate()
    wb.close()
    return buf.getvalue()
