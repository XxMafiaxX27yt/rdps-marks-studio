"""Writes the separate Board Results workbook (one class: Class XII or Class X) from one or more CBSE gazettes.
Several years of the same class are compared; the latest year is the main one."""
import io
import datetime
from itertools import groupby

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell as rc, xl_col_to_name as col_name

from . import theme
from .theme import Formats
from .school import _fast_prepare_formula  # noqa: F401  (installs the fast formula path)
from ..board import GRADE_ORDER, BEST5_BINS
from ..textutil import formula_like

GRADE_COLORS = {"A1": "#0B3C5D", "A2": "#1F5F8B", "B1": "#06A7E7", "B2": "#5CC4EF", "C1": "#9FDCF5",
                "C2": "#CBEBF9", "D1": "#F7C873", "D2": "#F2A93B", "E": "#C0392B"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _n(d):
    return "" if d is None else float(d)


class BoardNames:
    """The settings, but subject names follow the gazette's class (Class X codes like 184 = English)."""

    def __init__(self, cfg, cls):
        self._cfg, self._cls = cfg, cls

    def __getattr__(self, k):
        return getattr(self._cfg, k)

    def subject_name(self, code):
        return self._cfg.board_name(code, self._cls)

    def subject_short(self, code):
        return self._cfg.board_short(code, self._cls)


class BoardWorkbook:
    def __init__(self, analyses, cfg, years=None, link=None, raw_texts=None, generated=None, logo=None, teachers=None,
                 highlights=None):
        self.an = analyses[-1]                     # latest year is the main one
        self.teachers = teachers
        self.analyses = analyses
        self.cfg = BoardNames(cfg, self.an["meta"].get("cls") or "")
        self.years = years
        self.link = link
        self.raw = raw_texts or []
        self.highlights = highlights or []
        self.generated = generated or datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
        self.logo = logo
        self.buf = io.BytesIO()
        self.wb = xlsxwriter.Workbook(self.buf, {"in_memory": True, "strings_to_numbers": False,
                                                 "strings_to_formulas": False, "strings_to_urls": False})
        self.f = Formats(self.wb)
        from .school import SchoolWorkbook
        self._sw = SchoolWorkbook.__new__(SchoolWorkbook)   # reuse banner/chart helpers
        self._sw.wb, self._sw.f, self._sw.logo, self._sw.cfg = self.wb, self.f, logo, cfg

    def build(self):
        cfg, an = self.cfg, self.an
        m = an["meta"]
        self.wb.set_properties({"title": f"Board results {m['year']} Class {m.get('cls') or 'XII'}",
                                "author": cfg.rules["school_name"],
                                "comments": "Made by RDPS Marks Studio from the CBSE result gazette."})
        names = ["Board Dashboard", "Results", "Subjects", "Toppers"]
        if an["streams"]:
            names.append("Streams")
        if self.years and len(self.years["years"]) > 1:
            names.append("Year on Year")
        if self.link and self.link["links"]:
            names.append("School vs Boards")
        if self.teachers and self.teachers["cards"]:
            names.append("Teachers")
            if self.teachers["placement"]["placed"] or self.teachers["placement"]["unplaced"]:
                names.append("Students & Sections")
        names += ["Checks", "Gazette Text"]
        self.ws = {n: self.wb.add_worksheet(n) for n in names}
        self.results()
        self.subjects()
        if "Streams" in self.ws:
            self.streams()
        self.dashboard()
        self.toppers()
        if "Year on Year" in self.ws:
            self.year_on_year()
        if "School vs Boards" in self.ws:
            self.school_vs_board()
        if "Teachers" in self.ws:
            self.teacher_sheet()
        if "Students & Sections" in self.ws:
            self.sections_sheet()
        self.checks()
        self.source()
        self.ws["Board Dashboard"].activate()
        self.wb.close()
        return self.buf.getvalue()

    # -------------------------------------------------------------- helpers
    def _res(self, key):
        """An absolute range on the Results sheet: a subject code, or 'best5' / 'result' / 'stream' / 'roll'."""
        c = self.mark_col[key] if key in self.mark_col else self.res_col[key]
        L = col_name(c)
        a, b = self.res_rows
        return f"'Results'!${L}${a + 1}:${L}${b + 1}"

    def _table_head(self, ws, r, c0, heads, height=None):
        for c, h in enumerate(heads):
            ws.write(r, c0 + c, h, self.f.header())
        if height:
            ws.set_row(r, height)

    # -------------------------------------------------------------- Results (one row per student, in merit order)
    def results(self):
        ws, f, cfg, an = self.ws["Results"], self.f, self.cfg, self.an
        codes = an["codes"]
        has_stream = bool(an["streams"])
        heads = ["Rank (best 5)", "Roll No", "Name", "Sex"] + (["Stream"] if has_stream else [])
        first_mark = len(heads)
        for c in codes:
            heads += [cfg.subject_short(c) + (f" ({c})" if c not in cfg.subjects and cfg.subject_short(c) == c else ""), "Gr"]
        base = first_mark + 2 * len(codes)
        heads += ["Total", "Subjects", "All subjects %", "Best 5 %", "Result", "Compartment", "GR1", "GR2", "GR3"]
        self._sw.banner(ws, f"Board Results {an['meta']['year']} - Class {an['meta'].get('cls') or 'XII'}, every student",
                        "In merit order (best 5 %). Marks and grades exactly as in the CBSE file. Grey italic marks = the "
                        "subject not counted in the best 5. Total, All subjects %, Best 5 % and Rank are formulas.",
                        len(heads) - 1, logo=False)
        hr = 4
        self._table_head(ws, hr, 0, heads, 32)
        ws.set_column(0, 1, 10)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 3, 5)
        if has_stream:
            ws.set_column(4, 4, 12)
        ws.set_column(first_mark, base - 1, 6)
        ws.set_column(base, base + 3, 10)
        ws.set_column(base + 4, base + 5, 12)
        ws.set_column(base + 6, base + 8, 5)
        ws.freeze_panes(hr + 1, 3)
        rows = sorted(an["rows"], key=lambda r: (r["rank"] is None, r["rank"] or 0, r["s"].roll))
        first, last = hr + 1, hr + len(rows)
        self.res_rows = (first, max(first, last))
        self.mark_col = {c: first_mark + 2 * j for j, c in enumerate(codes)}
        self.res_col = {"roll": 1, "stream": 4, "best5": base + 3, "result": base + 4, "all": base + 2}
        b5_range = f"${col_name(base + 3)}${first + 1}:${col_name(base + 3)}${max(first, last) + 1}"
        fails = cfg.rules["board"]["fail_grades"]
        for i, r in enumerate(rows):
            rr = hr + 1 + i
            s = r["s"]
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write_string(rr, 1, s.roll, f.cell(**band))
            ws.write_string(rr, 2, s.name, f.cell(bold=True, quote_prefix=formula_like(s.name), **band))
            ws.write_string(rr, 3, s.gender, f.cell(align="center", **band))
            if has_stream:
                ws.write_string(rr, 4, r["stream"], f.cell(**band))
            bycode = {x["code"]: x for x in s.subjects}
            mark_cells, counted = [], []
            for j, c in enumerate(codes):
                x = bycode.get(c)
                col = first_mark + 2 * j
                if x is None:
                    ws.write_blank(rr, col, None, f.cell(bg_color=theme.GREY_BG))
                    ws.write_blank(rr, col + 1, None, f.cell(bg_color=theme.GREY_BG))
                    continue
                fail = x["grade"] in fails
                if x["marks"] is not None:
                    dropped = r["best5"] is not None and c not in r["best5_subjects"]
                    color = theme.RED if fail else (theme.MUTED if dropped else theme.TEXT)
                    ws.write_number(rr, col, x["marks"], f.cell(align="center", bold=fail, italic=dropped,
                                                                 font_color=color, **band))
                    mark_cells.append(rc(rr, col))
                    if c in r["best5_subjects"]:
                        counted.append(rc(rr, col))
                else:
                    ws.write_string(rr, col, x["raw"], f.cell(align="center", font_color=theme.AMBER, **band))
                ws.write_string(rr, col + 1, x["grade"], f.cell(align="center", font_color=theme.RED if fail else theme.MUTED, **band))
            rng = ",".join(mark_cells)
            ws.write_formula(rr, base, f"=SUM({rng})" if mark_cells else '=""', f.cell(align="center", bold=True, **band),
                             r["total"] if r["total"] is not None else "")
            ws.write_formula(rr, base + 1, f"=COUNT({rng})" if mark_cells else "=0", f.cell(align="center", **band), r["count"])
            T, N = rc(rr, base), rc(rr, base + 1)
            ws.write_formula(rr, base + 2, f'=IF(N({N})=0,"",{T}/{N})', f.num(2, **band), _n(r["pct_all"]))
            B5 = rc(rr, base + 3)
            if r["best5"] is not None and len(counted) == 5:
                ws.write_formula(rr, base + 3, f"=SUM({','.join(counted)})/5", f.num(2, bold=True, font_color=theme.NAVY, **band),
                                 _n(r["best5"]))
            else:
                ws.write(rr, base + 3, _n(r["best5"]), f.num(2, bold=True, font_color=theme.NAVY, **band))
            ws.write_formula(rr, 0, f'=IF(N({B5})=0,"",RANK({B5},{b5_range}))', f.cell(align="center", bold=True, **band),
                             r["rank"] if r["rank"] else "")
            res_fmt = f.cell(align="center", bold=True, font_color=theme.GREEN if s.result == "PASS" else theme.RED, **band)
            ws.write_string(rr, base + 4, s.result, res_fmt)
            ws.write_string(rr, base + 5, ", ".join(cfg.subject_name(c) for c in s.comp), f.cell(font_color=theme.RED, **band))
            for k in range(3):
                ws.write_string(rr, base + 6 + k, s.internal[k] if k < len(s.internal) else "", f.cell(align="center", **band))
        ws.autofilter(hr, 0, max(hr + 1, last), len(heads) - 1)
        ws.conditional_format(hr + 1, base + 3, last, base + 3, {"type": "data_bar", "bar_color": "#9FDCF5",
                                                               "bar_solid": True, "min_type": "num", "min_value": 0,
                                                               "max_type": "num", "max_value": 100})
        ws.write(last + 2, 0, "Best 5 % = one language (English) + the best four other subjects, as CBSE schools usually "
                              "quote it. All subjects % = every subject with marks, including the 6th (additional) subject.",
                 f.note())
        ws.write(last + 3, 0, "Rank: equal best 5 % = equal rank. Grades (Gr) are CBSE's own - they are given by position "
                              "among all CBSE students, so the same mark can get different grades in different subjects.",
                 f.note())
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(hr)
        self.base = base

    # -------------------------------------------------------------- Subjects
    SUBJ_HEADS = ["Code", "Subject", "Students", "Average", "Middle mark (median)", "Highest", "Lowest", "Passed",
                  "Did not pass", "90 or more", "100s", "PI (grade score)", "vs own other subjects"]

    def subjects(self):
        ws, f, cfg, an = self.ws["Subjects"], self.f, self.cfg, self.an
        heads = self.SUBJ_HEADS + GRADE_ORDER
        g0 = len(self.SUBJ_HEADS)
        self._sw.banner(ws, f"Subject-wise results {an['meta']['year']}",
                        "Average, middle mark, highest and lowest are formulas on the Results sheet. "
                        "PI = CBSE's grade score. 'vs own other subjects' = how the same students did here compared "
                        "with their other subjects.", len(heads) - 1)
        hr = 4
        self._table_head(ws, hr, 0, heads, 44)
        ws.set_column(0, 0, 7)
        ws.set_column(1, 1, 22)
        ws.set_column(2, g0 - 1, 9.5)
        ws.set_column(g0, g0 + len(GRADE_ORDER), 5.5)
        ws.freeze_panes(hr + 1, 2)
        subj = an["subjects"]
        w = cfg.rules["board"]["pi_weights"]
        for i, x in enumerate(subj):
            rr = hr + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            cell = f.cell(align="center", **band)
            ws.write_string(rr, 0, x["code"], f.cell(**band))
            ws.write_string(rr, 1, x["name"] + ("" if x["known"] else " (not in subject list)"), f.cell(bold=True, **band))
            ws.write(rr, 2, x["candidates"], cell)
            R = self._res(x["code"])
            ws.write_formula(rr, 3, f'=IFERROR(AVERAGE({R}),"")', f.num(2, bold=True, **band), _n(x["avg"]))
            ws.write_formula(rr, 4, f'=IFERROR(MEDIAN({R}),"")', f.num(1, **band), _n(x["median"]))
            ws.write_formula(rr, 5, f'=IF(COUNT({R})=0,"",MAX({R}))', cell, x["max"] if x["max"] is not None else "")
            ws.write_formula(rr, 6, f'=IF(COUNT({R})=0,"",MIN({R}))', cell, x["min"] if x["min"] is not None else "")
            ws.write(rr, 7, x["passed"], cell)
            ws.write(rr, 8, x["failed"], f.cell(align="center", bold=bool(x["failed"]),
                                                font_color=theme.RED if x["failed"] else theme.TEXT, **band))
            ws.write_formula(rr, 9, f'=COUNTIF({R},">=90")', cell, x["above90"])
            ws.write_formula(rr, 10, f"=COUNTIF({R},100)", cell, x["centums"])
            ws.write(rr, 12, _n(x["vs_own"]) if x["vs_own_n"] >= 3 else "", f.num(1, bold=True, **band))
            for j, gname in enumerate(GRADE_ORDER):
                ws.write(rr, g0 + j, x["grades"].get(gname, 0), cell)
            # PI written as a formula from the grade counts, so it can be checked
            g = {gname: rc(rr, g0 + j) for j, gname in enumerate(GRADE_ORDER)}
            num = "+".join(f"{w.get(gname, 0)}*{g[gname]}" for gname in GRADE_ORDER)
            den = "+".join(g[gname] for gname in GRADE_ORDER)
            ws.write_formula(rr, 11, f'=IF(({den})=0,"",({num})*100/(8*({den})))', f.num(1, bold=True, **band), _n(x["pi"]))
        n = len(subj)
        last = hr + n
        self.subj_rows = (hr + 1, last)
        self.grade_col0 = g0
        ws.conditional_format(hr + 1, 3, last, 3, {"type": "data_bar", "bar_color": "#9FDCF5", "bar_solid": True,
                                                   "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 100})
        ws.conditional_format(hr + 1, 12, last, 12, {"type": "cell", "criteria": "<", "value": 0,
                                                     "format": f.get(font_color=theme.RED)})
        ws.conditional_format(hr + 1, 12, last, 12, {"type": "cell", "criteria": ">", "value": 0,
                                                     "format": f.get(font_color=theme.GREEN)})
        notes = ["PI (Performance Index) = (8×A1 + 7×A2 + 6×B1 + 5×B2 + 4×C1 + 3×C2 + 2×D1 + 1×D2 + 0×E) × 100 ÷ "
                 "(8 × number of students). Weights are in Settings.",
                 "vs own other subjects: for each student, mark in this subject minus their average in their other subjects, "
                 "then averaged. +5 = the same students scored 5 marks more here than elsewhere (an easier paper or better "
                 "results); −5 = 5 marks less. Fairer than comparing plain averages, because each subject has different students.",
                 "Did not pass = CBSE grade E (theory and practical must each be passed, so a total above 33 can still be E)."]
        for k, t in enumerate(notes):
            ws.write(last + 2 + k, 1, t, f.note())
        ch_row = last + 2 + len(notes) + 1
        cats = f"='Subjects'!$B${hr + 2}:$B${last + 1}"
        ch = self._sw.chart("column", "Average marks by subject")
        ch.add_series({"categories": cats, "values": f"='Subjects'!$D${hr + 2}:$D${last + 1}", "fill": {"color": theme.BLUE},
                       "gap": 50, "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        self._sw.axis_style(ch, y_max=100)
        ws.insert_chart(ch_row, 1, ch, {"x_scale": 1.35, "y_scale": 1.1})
        ch = self._sw.chart("bar", "Grades in each subject (CBSE grades)", "percent_stacked")
        for j, gname in enumerate(GRADE_ORDER):
            L = col_name(g0 + j)
            ch.add_series({"name": gname, "categories": cats, "values": f"='Subjects'!${L}${hr + 2}:${L}${last + 1}",
                           "fill": {"color": GRADE_COLORS[gname]}, "gap": 40})
        ch.set_legend({"position": "bottom", "font": {"size": 8}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}})
        ch.set_x_axis({"num_font": {"size": 8, "color": theme.MUTED}, "num_format": "0%"})
        ws.insert_chart(ch_row, 9, ch, {"x_scale": 1.3, "y_scale": 1.1})
        ch = self._sw.chart("bar", "Harder or easier than the students' other subjects (marks)")
        ch.add_series({"categories": cats, "values": f"='Subjects'!$M${hr + 2}:$M${last + 1}", "fill": {"color": theme.BLUE},
                       "invert_if_negative": True, "invert_if_negative_color": theme.AMBER, "gap": 40,
                       "data_labels": {"value": True, "num_format": "+0.0;-0.0;0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}, "label_position": "low"})
        ch.set_x_axis({"num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ws.insert_chart(ch_row + 17, 1, ch, {"x_scale": 1.35, "y_scale": 1.1})
        ch = self._sw.chart("bar", "Performance Index (PI) by subject")
        ch.add_series({"categories": cats, "values": f"='Subjects'!$L${hr + 2}:$L${last + 1}", "fill": {"color": theme.NAVY},
                       "gap": 40, "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}})
        ch.set_x_axis({"min": 0, "max": 100, "num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ws.insert_chart(ch_row + 17, 9, ch, {"x_scale": 1.3, "y_scale": 1.1})
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)

    # -------------------------------------------------------------- Streams (Class XII)
    def streams(self):
        ws, f, an = self.ws["Streams"], self.f, self.an
        self._sw.banner(ws, "Streams", "Science, Commerce and Humanities - found from the subjects each student took. "
                        "Counts and averages are formulas on the Results sheet.", 9)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 6, 12)
        ws.set_column(7, 7, 26)
        ws.set_column(8, 9, 12)
        hr = 4
        self._table_head(ws, hr, 1, ["Stream", "Students", "Passed", "Pass %", "Average best 5 %", "90% or more",
                                     "Topper", "Topper's best 5 %"], 32)
        S, B, R = self._res("stream"), self._res("best5"), self._res("result")
        st = an["streams"]
        for i, x in enumerate(st):
            rr = hr + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            name = rc(rr, 1)
            ws.write_string(rr, 1, x["stream"], f.cell(bold=True, **band))
            ws.write_formula(rr, 2, f"=COUNTIF({S},{name})", f.cell(align="center", **band), x["n"])
            ws.write_formula(rr, 3, f'=COUNTIFS({S},{name},{R},"PASS")', f.cell(align="center", **band), x["passed"])
            ws.write_formula(rr, 4, f'=IF({rc(rr, 2)}=0,"",{rc(rr, 3)}*100/{rc(rr, 2)})', f.num(1, **band), _n(x["pass_pct"]))
            ws.write_formula(rr, 5, f'=IFERROR(AVERAGEIF({S},{name},{B}),"")', f.num(2, bold=True, **band), _n(x["avg_best5"]))
            ws.write_formula(rr, 6, f'=COUNTIFS({S},{name},{B},">=90")', f.cell(align="center", **band), x["above90"])
            top = x["top"][0] if x["top"] else None
            ws.write_string(rr, 7, top["name"] if top else "", f.cell(**band))
            ws.write(rr, 8, _n(top["best5"]) if top else "", f.num(1, **band))
        last = hr + len(st)
        r = last + 2
        ws.write(r, 1, "Top 3 in each stream", f.section())
        r += 1
        self._table_head(ws, r, 1, ["Stream", "Place", "Name", "", "Roll No", "Best 5 %", "Subjects"])
        ws.merge_range(r, 3, r, 4, "Name", f.header())
        k = 0
        for x in st:
            for p, t in enumerate(x["top"], 1):
                r += 1
                band = {"bg_color": theme.TINT2} if k % 2 else {}
                k += 1
                ws.write_string(r, 1, x["stream"] if p == 1 else "", f.cell(bold=True, **band))
                ws.write_string(r, 2, f"{MEDALS.get(p, '')} {p}", f.cell(align="center", **band))
                ws.merge_range(r, 3, r, 4, t["name"], f.cell(bold=p == 1, **band))
                ws.write_string(r, 5, t["roll"], f.cell(align="center", **band))
                ws.write(r, 6, _n(t["best5"]), f.num(1, bold=True, **band))
                ws.write_string(r, 7, t["combo"], f.cell(**band))
        r += 2
        ws.write(r, 1, "Subject combinations", f.section())
        r += 1
        self._table_head(ws, r, 1, ["Stream", "Combination", "", "Students"])
        ws.merge_range(r, 2, r, 3, "Combination", f.header())
        for x in st:
            for combo, cnt in x["combos"]:
                r += 1
                ws.write_string(r, 1, x["stream"], f.cell())
                ws.merge_range(r, 2, r, 3, combo, f.cell())
                ws.write_number(r, 4, cnt, f.cell(align="center"))
        cats = f"='Streams'!$B${hr + 2}:$B${last + 1}"
        ch = self._sw.chart("column", "Average best 5 % by stream")
        ch.add_series({"categories": cats, "values": f"='Streams'!$F${hr + 2}:$F${last + 1}", "fill": {"color": theme.BLUE},
                       "gap": 60, "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 9, "color": theme.NAVY}}})
        self._sw.axis_style(ch, y_max=100)
        ws.insert_chart(hr, 11, ch, {"x_scale": 1.0, "y_scale": 1.0})
        ch = self.wb.add_chart({"type": "doughnut"})
        ch.add_series({"name": "Students", "categories": cats, "values": f"='Streams'!$C${hr + 2}:$C${last + 1}",
                       "points": [{"fill": {"color": theme.SERIES[i % len(theme.SERIES)]}} for i in range(len(st))],
                       "data_labels": {"value": True, "font": {"size": 9}}})
        ch.set_title({"name": "Students in each stream", "name_font": {"name": theme.TITLE_FONT, "size": 11,
                                                                         "color": theme.NAVY, "bold": False}})
        ch.set_legend({"position": "bottom"})
        ch.set_hole_size(55)
        ws.insert_chart(hr + 16, 11, ch, {"x_scale": 1.0, "y_scale": 1.0})
        self.stream_rows = (hr + 1, last)

    # -------------------------------------------------------------- Dashboard
    def dashboard(self):
        ws, f, cfg, an = self.ws["Board Dashboard"], self.f, self.cfg, self.an
        m = an["meta"]
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 18, 8.6)
        self._sw.banner(ws, f"Board Results {m['year']} - Class {m['cls'] or 'XII'}",
                        f"{m['title']} · School {m['school_code']} · {(m['region'] or '').title()} · result date {m['date']}", 18)
        B, R, roll = self._res("best5"), self._res("result"), self._res("roll")
        s0, s1 = self.subj_rows
        g0 = self.grade_col0
        w = cfg.rules["board"]["pi_weights"]
        pi_num = "+".join(f"{w.get(gn, 0)}*SUM('Subjects'!${col_name(g0 + j)}${s0 + 1}:${col_name(g0 + j)}${s1 + 1})"
                          for j, gn in enumerate(GRADE_ORDER))
        pi_den = (f"SUM('Subjects'!${col_name(g0)}${s0 + 1}:${col_name(g0 + len(GRADE_ORDER) - 1)}${s1 + 1})")
        kp = [("Students", f"=COUNTA({roll})", an["candidates"], "0"),
              ("Pass %", f'=IF(COUNTA({roll})=0,"",COUNTIF({R},"PASS")*100/COUNTA({roll}))', _n(an["pass_pct"]), "0.0"),
              ("Average (best 5) %", f'=IFERROR(AVERAGE({B}),"")', _n(an["avg_best5"]), "0.0"),
              ("90% and above", f'=COUNTIF({B},">=90")', an["above90"], "0"),
              ("School PI", f'=IF({pi_den}=0,"",({pi_num})*100/(8*{pi_den}))', _n(an["school_pi"]), "0.0")
              if m.get("graded") else ("95% and above", f'=COUNTIF({B},">=95")', an["above95"], "0"),
              ("Compartment", f'=COUNTIF({R},"COMP*")', an["comp"], "0")]
        for i, (lab, formula, v, nf) in enumerate(kp):
            c0 = 1 + i * 3
            ws.merge_range(5, c0, 5, c0 + 2, "", f.get(bg_color=theme.TINT, top=2, top_color=theme.BLUE))
            vf = f.get(font_name=theme.TITLE_FONT, font_size=24, font_color=theme.RED if lab == "Compartment" and v else theme.NAVY,
                       align="center", bg_color=theme.TINT, num_format=nf)
            ws.merge_range(6, c0, 6, c0 + 2, "", vf)
            ws.write_formula(6, c0, formula, vf, v)
            ws.merge_range(7, c0, 7, c0 + 2, lab, f.kpi_label())
        ws.set_row(5, 6)
        ws.set_row(6, 38)
        ws.set_row(7, 18)
        # highlights
        r = 9
        ws.merge_range(r, 1, r, 18, "Highlights", f.section())
        for t in self.highlights:
            r += 1
            ws.merge_range(r, 1, r, 18, "•  " + t, f.get(text_wrap=True, valign="top", font_size=10))
            ws.set_row(r, 15 * max(1, 1 + len(t) // 150))
        # chart data (formulas on the Results sheet), far right so it does not print
        dr, dc = 9, 21
        ws.write(dr, dc, "Best 5 % range", f.header())
        ws.write(dr, dc + 1, "Students", f.header())
        ws.set_column(dc, dc, 14)
        for i, (lo, hi, lab) in enumerate(BEST5_BINS):
            cnt = next((c for l, c in an["distribution"] if l == lab), 0)
            ws.write_string(dr + 1 + i, dc, lab, f.cell())
            cond = f'{B},">={lo}"' + (f',{B},"<{hi}"' if hi <= 100 else "")
            ws.write_formula(dr + 1 + i, dc + 1, f"=COUNTIFS({cond})", f.cell(align="center"), cnt)
        nd = len(BEST5_BINS)
        ws.write(dr + nd + 2, dc, "Used by the charts on this sheet.", f.note())
        r += 2
        ch = self._sw.chart("column", "Students by best-5 percentage")
        ch.add_series({"categories": ["Board Dashboard", dr + 1, dc, dr + nd, dc],
                       "values": ["Board Dashboard", dr + 1, dc + 1, dr + nd, dc + 1], "fill": {"color": theme.NAVY},
                       "gap": 30, "data_labels": {"value": True, "font": {"size": 9, "color": theme.NAVY}}})
        self._sw.axis_style(ch)
        ch.set_size({"width": 560, "height": 300})
        ws.insert_chart(r, 1, ch)
        ch = self._sw.chart("bar", "Average marks by subject")
        ch.add_series({"categories": f"='Subjects'!$B${s0 + 1}:$B${s1 + 1}", "values": f"='Subjects'!$D${s0 + 1}:$D${s1 + 1}",
                       "fill": {"color": theme.BLUE}, "gap": 35,
                       "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}})
        ch.set_x_axis({"min": 0, "max": 100, "num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ch.set_size({"width": 590, "height": 300})
        ws.insert_chart(r, 10, ch)
        # top 10 + girls/boys + streams
        r += 16
        ws.merge_range(r, 1, r, 8, "Top 10 (best 5 %)", f.section())
        ws.merge_range(r, 10, r, 18, "Groups", f.section())
        r += 1
        ws.write(r, 1, "Rank", f.header())
        ws.merge_range(r, 2, r, 4, "Name", f.header())
        ws.merge_range(r, 5, r, 6, "Stream" if an["streams"] else "Roll No", f.header())
        ws.write(r, 7, "Best 5 %", f.header())
        ws.write(r, 8, "Result", f.header())
        for i, x in enumerate(an["ranked"][:10]):
            rr = r + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write_string(rr, 1, f"{MEDALS.get(x['rank'], '')} {x['rank']}".strip(), f.cell(align="center", bold=True, **band))
            ws.merge_range(rr, 2, rr, 4, x["s"].name, f.cell(bold=x["rank"] <= 3, **band))
            ws.merge_range(rr, 5, rr, 6, x["stream"] if an["streams"] else x["s"].roll, f.cell(**band))
            ws.write(rr, 7, float(x["best5"]), f.num(1, bold=True, **band))
            ws.write_string(rr, 8, x["s"].result, f.cell(align="center", **band))
        g = [x for x in an["gender"] if x["gender"] != "?"]
        gr = r
        ws.merge_range(gr, 10, gr, 12, "Group", f.header())
        for c, h in enumerate(["Students", "Pass %", "Avg best 5 %"]):
            ws.merge_range(gr, 13 + 2 * c, gr, 14 + 2 * c, h, f.header())
        lines = [(x["gender"], x["n"], x["pass_pct"], x["avg_best5"]) for x in g] if len(g) > 1 else []
        lines += [(x["stream"], x["n"], x["pass_pct"], x["avg_best5"]) for x in an["streams"]]
        for i, (lab, n, pp, b5) in enumerate(lines):
            rr = gr + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.merge_range(rr, 10, rr, 12, lab, f.cell(bold=True, **band))
            ws.merge_range(rr, 13, rr, 14, n, f.cell(align="center", **band))
            ws.merge_range(rr, 15, rr, 16, _n(pp), f.num(1, **band))
            ws.merge_range(rr, 17, rr, 18, _n(b5), f.num(1, **band))
        end = max(r + 11, gr + len(lines) + 1)
        ws.write(end + 1, 1, "Grades and results are CBSE's own (copied from the CBSE file). Best 5 % = English + best four others. "
                             "The numbers at the top are formulas on the Results sheet.", f.note())
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 1)
        ws.print_area(0, 0, end + 1, 18)

    # -------------------------------------------------------------- Toppers & compartment
    def toppers(self):
        ws, f, cfg, an = self.ws["Toppers"], self.f, self.cfg, self.an
        self._sw.banner(ws, "Toppers", "The top three, the top 25, stream toppers, subject toppers and the students "
                        "with a compartment.", 8)
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 9)
        ws.set_column(2, 2, 28)
        ws.set_column(3, 8, 13)
        r = 4
        # the podium: the first three places (equal marks share a place)
        places = [(rk, [x for x in grp]) for rk, grp in groupby(an["ranked"], key=lambda x: x["rank"])][:3]
        if places:
            ws.merge_range(r, 1, r, 8, "Top three", f.section())
            r += 1
            order = [1, 0, 2] if len(places) >= 2 else [0]
            spans = [(1, 2), (3, 5), (6, 8)]
            for slot, pi in enumerate(order):
                if pi >= len(places):
                    continue
                rk, who = places[pi]
                c0, c1 = spans[slot]
                gold = pi == 0
                bg = "#FFF4D6" if gold else theme.TINT
                top = r + (0 if gold else 1)
                ws.merge_range(top, c0, top, c1, f"{MEDALS.get(pi + 1, '')}  Rank {rk}",
                               f.get(bold=True, font_size=12, font_color=theme.NAVY, align="center", bg_color=bg,
                                     top=2, top_color="#E0A800" if gold else theme.BLUE))
                ws.merge_range(top + 1, c0, top + 1, c1, " · ".join(x["s"].name for x in who),
                               f.get(font_name=theme.TITLE_FONT, font_size=13 if gold else 12, font_color=theme.NAVY,
                                     align="center", bg_color=bg, text_wrap=True))
                ws.merge_range(top + 2, c0, top + 2, c1, f"{float(who[0]['best5']):.1f}% (best 5)",
                               f.get(bold=True, font_size=16 if gold else 13, font_color=theme.BLUE, align="center", bg_color=bg))
                sub = " · ".join(sorted({x["stream"] for x in who if x["stream"]}))
                ws.merge_range(top + 3, c0, top + 3, c1, sub, f.get(font_size=9, font_color=theme.MUTED, align="center",
                                                                    bg_color=bg))
            ws.set_row(r + 1, 30)
            ws.set_row(r + 2, 30)
            r += 6
        ws.merge_range(r, 1, r, 8, "Top 25 (best 5 %)", f.section())
        r += 1
        self._table_head(ws, r, 1, ["Rank", "Name", "Roll No", "Stream", "Best 5 %", "All subjects %", "Result"])
        for i, x in enumerate(an["ranked"][:25]):
            rr = r + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write_string(rr, 1, f"{MEDALS.get(x['rank'], '')} {x['rank']}".strip(), f.cell(align="center", bold=True, **band))
            ws.write_string(rr, 2, x["s"].name, f.cell(bold=x["rank"] <= 3, **band))
            ws.write_string(rr, 3, x["s"].roll, f.cell(align="center", **band))
            ws.write_string(rr, 4, x["stream"] or "-", f.cell(align="center", **band))
            ws.write(rr, 5, float(x["best5"]), f.num(2, bold=True, **band))
            ws.write(rr, 6, _n(x["pct_all"]), f.num(2, **band))
            ws.write_string(rr, 7, x["s"].result, f.cell(align="center", **band))
        r += min(25, len(an["ranked"])) + 3
        if an["streams"]:
            ws.merge_range(r, 1, r, 8, "Stream toppers", f.section())
            r += 1
            self._table_head(ws, r, 1, ["Place", "Name", "Stream", "Subjects", "Best 5 %"])
            k = 0
            for s in an["streams"]:
                for p, t in enumerate(s["top"], 1):
                    r += 1
                    band = {"bg_color": theme.TINT2} if k % 2 else {}
                    k += 1
                    ws.write_string(r, 1, f"{MEDALS.get(p, '')} {p}".strip(), f.cell(align="center", **band))
                    ws.write_string(r, 2, t["name"], f.cell(bold=p == 1, **band))
                    ws.write_string(r, 3, s["stream"], f.cell(align="center", **band))
                    ws.write_string(r, 4, t["combo"], f.cell(align="center", **band))
                    ws.write(r, 5, _n(t["best5"]), f.num(1, bold=True, **band))
            r += 3
        ws.merge_range(r, 1, r, 8, "Subject toppers", f.section())
        r += 1
        self._table_head(ws, r, 1, ["Code", "Subject", "Highest", "100s"])
        ws.merge_range(r, 5, r, 8, "Scored by", f.header())
        for i, x in enumerate(an["subjects"]):
            rr = r + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write_string(rr, 1, x["code"], f.cell(align="center", **band))
            ws.write_string(rr, 2, x["name"], f.cell(bold=True, **band))
            ws.write(rr, 3, x["max"] if x["max"] is not None else "", f.cell(align="center", bold=True,
                                                                             font_color=theme.GREEN if x["max"] == 100 else theme.TEXT, **band))
            ws.write(rr, 4, x["centums"] or "", f.cell(align="center", **band))
            ws.merge_range(rr, 5, rr, 8, ", ".join(x["toppers"]), f.cell(text_wrap=True, **band))
        r += len(an["subjects"]) + 3
        if an["all_rounders"]:
            ws.merge_range(r, 1, r, 8, f"90 or more in every subject ({len(an['all_rounders'])})", f.section())
            r += 1
            names = ", ".join(x["s"].name for x in an["all_rounders"])
            ws.merge_range(r, 1, r, 8, names, f.cell(text_wrap=True, valign="top"))
            ws.set_row(r, 15 * max(1, 1 + len(names) // 110))
            r += 3
        ws.merge_range(r, 1, r, 8, f"Compartment ({len(an['comp_list'])})", f.section())
        r += 1
        self._table_head(ws, r, 1, ["Roll No", "Name", "Compartment in", "Marks there"])
        for i, s in enumerate(an["comp_list"]):
            rr = r + 1 + i
            ws.write_string(rr, 1, s.roll, f.cell())
            ws.write_string(rr, 2, s.name, f.cell(bold=True))
            ws.write_string(rr, 3, ", ".join(cfg.subject_name(c) for c in s.comp), f.cell(font_color=theme.RED))
            mk = [str(x["marks"]) for x in s.subjects if x["code"] in s.comp and x["marks"] is not None]
            ws.write_string(rr, 4, ", ".join(mk), f.cell(align="center"))
        if not an["comp_list"]:
            ws.write_string(r + 1, 2, "None.", f.cell(font_color=theme.GREEN))
        if an["others_list"]:
            r += max(1, len(an["comp_list"])) + 3
            ws.merge_range(r, 1, r, 8, "Other results (not PASS / COMP)", f.section())
            for i, s in enumerate(an["others_list"]):
                ws.write_string(r + 1 + i, 2, f"{s.name} ({s.roll}): {s.result}", f.cell())
        ws.set_portrait()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)

    # -------------------------------------------------------------- Year on year
    def year_on_year(self):
        ws, f, cfg, y = self.ws["Year on Year"], self.f, self.cfg, self.years
        years = y["years"]
        self._sw.banner(ws, "Year on year", f"Board results compared across {', '.join(years)}.", 3 + 2 * len(years))
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 22)
        ws.set_column(2, 2 + 2 * len(years), 11)
        r = 4
        ws.write(r, 1, "School", f.header())
        for i, h in enumerate(["Candidates", "Pass %", "Avg best 5 %", "School PI"]):
            ws.write(r, 2 + i, h, f.header())
        for i, (yr, pp, b5, pi, n) in enumerate(y["summary"]):
            ws.write_string(r + 1 + i, 1, yr, f.cell(bold=True))
            ws.write(r + 1 + i, 2, n, f.cell(align="center"))
            ws.write(r + 1 + i, 3, _n(pp), f.num(1))
            ws.write(r + 1 + i, 4, _n(b5), f.num(1))
            ws.write(r + 1 + i, 5, _n(pi), f.num(1))
        r += len(years) + 3
        ws.write(r, 1, "Subject", f.header())
        for i, yr in enumerate(years):
            ws.write(r, 2 + i, f"Avg {yr}", f.header())
            ws.write(r, 2 + len(years) + i, f"PI {yr}", f.header())
        first = r + 1
        for i, row in enumerate(y["subjects"]):
            rr = r + 1 + i
            ws.write_string(rr, 1, cfg.subject_name(row["code"]), f.cell(bold=True))
            for j, (yr, avg, pi) in enumerate(row["values"]):
                ws.write(rr, 2 + j, _n(avg), f.num(1))
                ws.write(rr, 2 + len(years) + j, _n(pi), f.num(1))
        last = r + len(y["subjects"])
        ch = self._sw.chart("column", "Average marks by subject, year by year")
        for j, yr in enumerate(years):
            letter = xlsxwriter.utility.xl_col_to_name(2 + j)
            ch.add_series({"name": yr, "categories": f"='Year on Year'!$B${first + 1}:$B${last + 1}",
                           "values": f"='Year on Year'!${letter}${first + 1}:${letter}${last + 1}",
                           "fill": {"color": theme.SERIES[j % len(theme.SERIES)]}})
        ch.set_legend({"position": "bottom"})
        self._sw.axis_style(ch, y_max=100)
        ws.insert_chart(last + 2, 1, ch, {"x_scale": 1.6, "y_scale": 1.1})

    # -------------------------------------------------------------- School vs Boards
    def school_vs_board(self):
        ws, f, cfg, lk = self.ws["School vs Boards"], self.f, self.cfg, self.link
        self._sw.banner(ws, "School tests vs Boards", f"{lk['linked_students']} students linked "
                        f"({lk['by_name']} by name - please check those). Gap = board marks − school %.", 8)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 22)
        ws.set_column(2, 8, 12)
        r = 4
        for c, h in enumerate(["Subject", "Students", "Average gap (points)"], 1):
            ws.write(r, c, h, f.header())
        for i, x in enumerate(lk["by_subject"]):
            ws.write_string(r + 1 + i, 1, x["name"], f.cell(bold=True))
            ws.write(r + 1 + i, 2, x["n"], f.cell(align="center"))
            ws.write(r + 1 + i, 3, float(x["avg_gap"]), f.num(1))
        r += len(lk["by_subject"]) + 3
        heads = ["Name", "Board roll", "Subject", "School exam", "School %", "Board marks", "Gap", "Linked by"]
        for c, h in enumerate(heads, 1):
            ws.write(r, c, h, f.header())
        for i, l in enumerate(lk["links"]):
            rr = r + 1 + i
            ws.write_string(rr, 1, l["name"], f.cell())
            ws.write_string(rr, 2, l["roll"], f.cell())
            ws.write_string(rr, 3, cfg.subject_name(l["subject"]), f.cell())
            ws.write_string(rr, 4, cfg.exam_name(l["school_exam"]), f.cell())
            ws.write(rr, 5, float(l["school_pct"]), f.num(1))
            ws.write(rr, 6, float(l["board"]), f.num(0))
            ws.write_formula(rr, 7, f"={rc(rr, 6)}-{rc(rr, 5)}", f.num(1, bold=True), float(l["gap"]))
            ws.write_string(rr, 8, l["how"], f.cell(font_color=theme.AMBER if l["how"] != "board roll" else theme.MUTED))
        if lk["links"]:
            ws.autofilter(r, 1, r + len(lk["links"]), 8)

    # -------------------------------------------------------------- teachers on the board results
    def teacher_sheet(self):
        ws, f, bt = self.ws["Teachers"], self.f, self.teachers
        wb_name = "Teachers"
        self._sw.banner(ws, f"Teachers - Board Results {bt['year'] or ''}".strip(),
                        "Each teacher's own students: their board mark in the subject compared with their other subjects, "
                        "and with the other teachers of the same subject.", 13)
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 2, 24)
        ws.set_column(3, 3, 14)
        ws.set_column(4, 10, 10)
        ws.set_column(11, 11, 16)
        ws.set_column(12, 12, 26)
        ws.merge_range(3, 1, 3, 12, bt["caution"], f.cell(italic=True, font_color=theme.MUTED, text_wrap=True, valign="top"))
        ws.set_row(3, 48)
        pl = bt["placement"]
        if pl["lists"] or pl["placed"]:
            how = ", ".join(f"{v} by {k}" for k, v in pl["by"].items())
            line = (f"{pl['placed']} of {pl['total']} students were found in a section ({how}). "
                    + (f"{len(pl['check'])} matched by a similar name - please check (see Students & Sections). "
                       if pl["check"] else "")
                    + (f"{len(pl['unplaced'])} could not be placed. " if pl["unplaced"] else ""))
            if pl["other_class"]:
                line += ("Note: the class lists are for Class " + ", ".join(pl["other_class"]) +
                         f", the board results are Class {bt['cls']} - only the sections were used.")
            ws.merge_range(4, 1, 4, 12, line, f.cell(font_color=theme.NAVY, text_wrap=True, valign="top"))
            ws.set_row(4, 32)
        r = 6
        heads = ["Subject", "Teacher", "Sections", "Students", "Average", "Highest", "90+", "Did not pass",
                 "vs own other subjects", "vs other teachers", "Likely range", "Fair check"]
        for c, h in enumerate(heads, 1):
            ws.write(r, c, h, f.header())
        ws.set_row(r, 32)
        cards = bt["cards"]
        first = r + 1
        for i, c in enumerate(cards):
            rr = r + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            fx = c["fair"]
            ws.write_string(rr, 1, c["subject_name"], f.cell(bold=True, **band))
            ws.write_string(rr, 2, c["name"], f.cell(quote_prefix=formula_like(c["name"]), **band))
            ws.write_string(rr, 3, ", ".join(c["sections"]) or bt["cls"], f.cell(**band))
            ws.write(rr, 4, c["candidates"], f.cell(align="center", **band))
            ws.write(rr, 5, _n(c["avg"]), f.num(1, **band))
            ws.write(rr, 6, _n(c["max"]), f.num(0, **band))
            ws.write(rr, 7, c["above90"], f.cell(align="center", **band))
            ws.write(rr, 8, c["grade_e"], f.cell(align="center", font_color=theme.RED if c["grade_e"] else theme.TEXT, **band))
            ws.write(rr, 9, _n(fx["vs_own"]), f.num(1, **band))
            e = fx["effect"]
            ws.write(rr, 10, _n(e), f.num(1, bold=True, **band))
            ws.write_string(rr, 11, f"{float(fx['low']):.1f} to {float(fx['high']):.1f}" if e is not None else "-",
                            f.cell(align="center", **band))
            vcol = {"Clear positive impact": theme.GREEN, "Worth a conversation": theme.AMBER}.get(fx["verdict"], theme.TEXT)
            ws.write_string(rr, 12, fx["verdict"], f.cell(bold=True, font_color=vcol, **band))
        last = r + len(cards)
        for col in (9, 10):
            ws.conditional_format(first, col, last, col, {"type": "cell", "criteria": "<", "value": 0,
                                                          "format": f.get(font_color=theme.RED)})
            ws.conditional_format(first, col, last, col, {"type": "cell", "criteria": ">", "value": 0,
                                                          "format": f.get(font_color=theme.GREEN)})
        r = last + 2
        # chart data: better / same / worse, and the bands
        ws.write_string(r, 1, "Compared with their own other subjects", f.cell(bold=True, font_color=theme.NAVY))
        r += 1
        for c, h in enumerate(["Teacher", "Subject", "Better", "About the same", "Worse"], 1):
            ws.write(r, c, h, f.header())
        sf = r + 1
        for c in cards:
            r += 1
            sp = c["viz"]["split"]
            ws.write_string(r, 1, c["name"], f.cell(bold=True))
            ws.write_string(r, 2, c["subject_name"], f.cell())
            for k, key in enumerate(("better", "same", "worse")):
                ws.write(r, 3 + k, sp[key], f.cell(align="center"))
        sl = r
        r += 2
        bands = cards[0]["viz"]["bands"] if cards else []
        are = cards[0]["viz"]["bands_are"] if cards else "marks"
        ws.write_string(r, 1, "CBSE grades" if are == "grades" else "Marks", f.cell(bold=True, font_color=theme.NAVY))
        r += 1
        ws.write(r, 1, "Teacher", f.header())
        ws.write(r, 2, "Subject", f.header())
        for k, (lab, _) in enumerate(bands):
            ws.write(r, 3 + k, lab, f.header())
        for c in cards:
            r += 1
            ws.write_string(r, 1, c["name"], f.cell(bold=True))
            ws.write_string(r, 2, c["subject_name"], f.cell())
            for k, (_, v) in enumerate(c["viz"]["bands"]):
                ws.write(r, 3 + k, v, f.cell(align="center"))
        r += 2
        ws.write_string(r, 1, "Notes", f.cell(bold=True, font_color=theme.NAVY))
        for c in cards:
            r += 1
            ws.write_string(r, 1, c["subject_name"], f.cell(bold=True))
            ws.write_string(r, 2, c["name"], f.cell())
            txt = "  ".join(c["notes"])
            ws.merge_range(r, 3, r, 12, txt, f.cell(text_wrap=True, valign="top"))
            ws.set_row(r, 15 * max(2, 1 + len(txt) // 110))
        if bt["untaught"]:
            r += 2
            ws.write_string(r, 1, "No teacher added for", f.cell(bold=True, font_color=theme.NAVY))
            for u in bt["untaught"]:
                r += 1
                ws.write_string(r, 1, u["name"], f.cell())
                ws.write(r, 2, f"{u['candidates']} students", f.cell())
        if cards:
            ch = self.wb.add_chart({"type": "bar"})
            ch.add_series({"name": "vs own other subjects", "categories": [wb_name, first, 2, last, 2],
                           "values": [wb_name, first, 9, last, 9], "fill": {"color": theme.BLUE},
                           "data_labels": {"value": True, "num_format": "0.0"}})
            ch.set_title({"name": "Marks above / below the students' own other subjects", "name_font": {"size": 11}})
            ch.set_legend({"none": True})
            ch.set_y_axis({"reverse": True})
            ch.set_size({"width": 620, "height": 100 + 28 * len(cards)})
            ws.insert_chart(6, 14, ch)
            st = self.wb.add_chart({"type": "bar", "subtype": "percent_stacked"})
            for k, (lab, color) in enumerate([("Better", theme.GREEN), ("About the same", "#9FB3C4"), ("Worse", theme.RED)]):
                st.add_series({"name": lab, "categories": [wb_name, sf, 1, sl, 1], "values": [wb_name, sf, 3 + k, sl, 3 + k],
                               "fill": {"color": color}, "gap": 60})
            st.set_title({"name": "Did better / same / worse than in their other subjects", "name_font": {"size": 11}})
            st.set_legend({"position": "bottom"})
            st.set_y_axis({"reverse": True})
            st.set_size({"width": 620, "height": 120 + 28 * len(cards)})
            ws.insert_chart(6 + 7 + int((100 + 28 * len(cards)) / 20), 14, st)

    def sections_sheet(self):
        """Every board student: the section found for them and how (to check the matching)."""
        ws, f, bt, an = self.ws["Students & Sections"], self.f, self.teachers, self.an
        self._sw.banner(ws, "Students & Sections", "Which section each student was found in (from the class lists), and how.", 6,
                        logo=False)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 28)
        ws.set_column(2, 3, 14)
        ws.set_column(4, 4, 18)
        ws.set_column(5, 5, 30)
        pl = bt["placement"]
        r = 3
        if pl["check"]:
            ws.write_string(r, 1, "Please check - matched by a similar name", f.cell(bold=True, font_color=theme.AMBER))
            r += 1
            for c, h in enumerate(["Name in the board results", "Section", "Name in the class list"], 1):
                ws.write(r, c, h, f.header())
            for x in pl["check"]:
                r += 1
                ws.write_string(r, 1, x["name"], f.cell())
                ws.write_string(r, 2, x["section"], f.cell(align="center"))
                ws.write_string(r, 3, x["list_name"], f.cell())
            r += 2
        if pl["unplaced"]:
            ws.write_string(r, 1, "Not placed in a section", f.cell(bold=True, font_color=theme.RED))
            r += 1
            for c, h in enumerate(["Name", "Why"], 1):
                ws.write(r, c, h, f.header())
            for x in pl["unplaced"]:
                r += 1
                ws.write_string(r, 1, x["name"], f.cell())
                ws.write_string(r, 2, x["why"], f.cell())
            r += 2
        ws.write_string(r, 1, f"{pl['placed']} of {pl['total']} students placed in a section.",
                        f.cell(bold=True, font_color=theme.NAVY))

    # -------------------------------------------------------------- checks + source
    def checks(self):
        ws, f, an = self.ws["Checks"], self.f, self.an
        self._sw.banner(ws, "Checks", "How the gazette was read. Every line is accounted for.", 6, logo=False)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 10)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 3, 100)
        r = 4
        t = an["totals"]
        rows = [("Candidates read", an["candidates"], t.get("candidates")), ("PASS read", an["passed"], t.get("pass")),
                ("Compartment read", an["comp"], t.get("comp"))]
        for c, h in enumerate(["What", "Read", "Gazette says", "Match"], 1):
            ws.write(r, c, h, f.header())
        for i, (k, v, g) in enumerate(rows):
            rr = r + 1 + i
            ws.write_string(rr, 1, k, f.cell())
            ws.write_number(rr, 2, v, f.cell(align="center"))
            ws.write(rr, 3, g if g is not None else "not given", f.cell(align="center"))
            ok = g is None or g == v
            ws.write_string(rr, 4, "✓" if ok else "✗ CHECK", f.cell(bold=True, font_color=theme.GREEN if ok else theme.RED))
        ws.set_column(4, 4, 10)
        r += 6
        for c, h in enumerate(["Severity", "Problem", "Details"], 1):
            ws.write(r, c, h, f.header())
        for a in self.analyses:
            for it in a["issues"]:
                r += 1
                ws.write_string(r, 1, it.severity.title(), f.cell(bold=True, font_color={"error": theme.RED, "warning": theme.AMBER}.get(it.severity, theme.MUTED)))
                ws.write_string(r, 2, it.code.replace("_", " "), f.cell())
                ws.write_string(r, 3, f"[{a['meta']['year']}] " + it.message, f.cell())

    def source(self):
        ws, f = self.ws["Gazette Text"], self.f
        ws.set_column(0, 0, 160)
        ws.write(0, 0, "Exact text of the uploaded gazette file(s). Protected so it is not changed by accident.", f.note())
        r = 2
        mono = f.get(font_name="Consolas", font_size=9)
        for name, text in self.raw:
            ws.write_string(r, 0, name, f.get(bold=True, font_color=theme.WHITE, bg_color=theme.NAVY))
            r += 1
            for line in text.replace("\r\n", "\n").split("\n"):
                ws.write_string(r, 0, line, f.get(font_name="Consolas", font_size=9, quote_prefix=True) if formula_like(line) else mono)
                r += 1
            r += 1
        ws.protect("", {"select_locked_cells": True})


def write_board_workbook(analyses, cfg, years=None, link=None, raw_texts=None, logo=None, teachers=None, highlights=None):
    return BoardWorkbook(analyses, cfg, years=years, link=link, raw_texts=raw_texts, logo=logo, teachers=teachers,
                         highlights=highlights).build()
