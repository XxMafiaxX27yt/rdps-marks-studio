"""Writes the separate Board Results workbook from one or more CBSE gazettes."""
import io
import datetime
from decimal import Decimal

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell as rc

from . import theme
from .theme import Formats
from .school import _fast_prepare_formula  # noqa: F401  (installs the fast formula path)
from ..board import GRADE_ORDER
from ..textutil import formula_like

GRADE_COLORS = {"A1": "#0B3C5D", "A2": "#1F5F8B", "B1": "#06A7E7", "B2": "#5CC4EF", "C1": "#9FDCF5",
                "C2": "#CBEBF9", "D1": "#F7C873", "D2": "#F2A93B", "E": "#C0392B"}


def _n(d):
    return "" if d is None else float(d)


class BoardWorkbook:
    def __init__(self, analyses, cfg, years=None, link=None, raw_texts=None, generated=None, logo=None):
        self.an = analyses[-1]                     # latest year is the main one
        self.analyses = analyses
        self.cfg = cfg
        self.years = years
        self.link = link
        self.raw = raw_texts or []
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
        self.wb.set_properties({"title": f"Board results {m['year']}", "author": cfg.rules["school_name"],
                                "comments": "Made by RDPS Marks Studio from the CBSE result gazette."})
        names = ["Board Dashboard", "Results", "Subjects", "Toppers"]
        if self.years and len(self.years["years"]) > 1:
            names.append("Year on Year")
        if self.link and self.link["links"]:
            names.append("School vs Boards")
        names += ["Checks", "Gazette Text"]
        self.ws = {n: self.wb.add_worksheet(n) for n in names}
        self.results()
        self.subjects()
        self.dashboard()
        self.toppers()
        if "Year on Year" in self.ws:
            self.year_on_year()
        if "School vs Boards" in self.ws:
            self.school_vs_board()
        self.checks()
        self.source()
        self.ws["Board Dashboard"].activate()
        self.wb.close()
        return self.buf.getvalue()

    # -------------------------------------------------------------- Results (one row per student)
    def results(self):
        ws, f, cfg, an = self.ws["Results"], self.f, self.cfg, self.an
        codes = an["codes"]
        self._sw.banner(ws, f"Board Results {an['meta']['year']} - every candidate",
                        "Marks and grades exactly as in the CBSE gazette. Totals and All-subjects % are formulas.",
                        8 + 2 * len(codes) + 6, logo=False)
        hr = 4
        heads = ["Rank (best 5)", "Roll No", "Name", "Sex"]
        for c in codes:
            heads += [cfg.subject_short(c) + (f" ({c})" if c not in cfg.subjects else ""), "Gr"]
        heads += ["Total", "Subjects", "All subjects %", "Best 5 %", "Result", "Compartment", "GR1", "GR2", "GR3"]
        for c, h in enumerate(heads):
            ws.write(hr, c, h, f.header())
        ws.set_row(hr, 32)
        ws.set_column(0, 1, 10)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 3, 5)
        ws.set_column(4, 4 + 2 * len(codes), 6)
        base = 4 + 2 * len(codes)
        ws.set_column(base, base + 3, 10)
        ws.set_column(base + 4, base + 5, 11)
        ws.set_column(base + 6, base + 8, 5)
        ws.freeze_panes(hr + 1, 3)
        rows = sorted(an["rows"], key=lambda r: r["s"].roll)
        self.row_of = {}
        for i, r in enumerate(rows):
            rr = hr + 1 + i
            s = r["s"]
            self.row_of[s.roll] = rr
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write(rr, 0, r["rank"] if r["rank"] else "", f.cell(align="center", **band))
            ws.write_string(rr, 1, s.roll, f.cell(**band))
            ws.write_string(rr, 2, s.name, f.cell(bold=True, quote_prefix=formula_like(s.name), **band))
            ws.write_string(rr, 3, s.gender, f.cell(align="center", **band))
            bycode = {x["code"]: x for x in s.subjects}
            mark_cells = []
            for j, c in enumerate(codes):
                x = bycode.get(c)
                col = 4 + 2 * j
                if x is None:
                    ws.write_blank(rr, col, None, f.cell(bg_color=theme.GREY_BG))
                    ws.write_blank(rr, col + 1, None, f.cell(bg_color=theme.GREY_BG))
                    continue
                fail = x["grade"] in cfg.rules["board"]["fail_grades"]
                if x["marks"] is not None:
                    ws.write_number(rr, col, x["marks"], f.cell(align="center", bold=fail, font_color=theme.RED if fail else theme.TEXT, **band))
                    mark_cells.append(rc(rr, col))
                else:
                    ws.write_string(rr, col, x["raw"], f.cell(align="center", font_color=theme.AMBER, **band))
                ws.write_string(rr, col + 1, x["grade"], f.cell(align="center", font_color=theme.RED if fail else theme.MUTED, **band))
            rng = ",".join(mark_cells) if mark_cells else '""'
            ws.write_formula(rr, base, f"=SUM({rng})" if mark_cells else '=""', f.cell(align="center", bold=True, **band),
                             r["total"] if r["total"] is not None else "")
            ws.write_formula(rr, base + 1, f"=COUNT({rng})" if mark_cells else "=0", f.cell(align="center", **band), r["count"])
            T, N = rc(rr, base), rc(rr, base + 1)
            ws.write_formula(rr, base + 2, f'=IF(N({N})=0,"",{T}/{N})', f.num(2, **band), _n(r["pct_all"]))
            ws.write(rr, base + 3, _n(r["best5"]), f.num(2, bold=True, font_color=theme.NAVY, **band))
            res_fmt = f.cell(align="center", bold=True, font_color=theme.GREEN if s.result == "PASS" else theme.RED, **band)
            ws.write_string(rr, base + 4, s.result, res_fmt)
            ws.write_string(rr, base + 5, ", ".join(cfg.subject_name(c) for c in s.comp), f.cell(font_color=theme.RED, **band))
            for k in range(3):
                ws.write_string(rr, base + 6 + k, s.internal[k] if k < len(s.internal) else "", f.cell(align="center", **band))
        last = hr + len(rows)
        ws.autofilter(hr, 0, max(hr + 1, last), len(heads) - 1)
        ws.conditional_format(hr + 1, base + 3, last, base + 3, {"type": "data_bar", "bar_color": "#9FDCF5",
                                                               "bar_solid": True, "min_type": "num", "min_value": 0,
                                                               "max_type": "num", "max_value": 100})
        ws.write(last + 2, 0, "Best 5 % = one language (English) + the best four other subjects, as CBSE schools usually "
                              "quote it. All subjects % = every subject with marks, including the 6th (additional) subject.",
                 f.note())
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(hr)
        self.base = base

    # -------------------------------------------------------------- Subjects
    def subjects(self):
        ws, f, cfg, an = self.ws["Subjects"], self.f, self.cfg, self.an
        self._sw.banner(ws, f"Subject-wise results {an['meta']['year']}",
                        "Averages, pass counts, CBSE grades and the Performance Index (PI) for every subject.", 21)
        hr = 4
        heads = ["Code", "Subject", "Candidates", "Average", "Highest", "Lowest", "Passed", "Failed (E)", "90+",
                 "100s", "PI"] + GRADE_ORDER
        for c, h in enumerate(heads):
            ws.write(hr, c, h, f.header())
        ws.set_row(hr, 30)
        ws.set_column(0, 0, 7)
        ws.set_column(1, 1, 22)
        ws.set_column(2, 10, 9)
        ws.set_column(11, 11 + len(GRADE_ORDER), 5.5)
        ws.freeze_panes(hr + 1, 2)
        subj = an["subjects"]
        for i, x in enumerate(subj):
            rr = hr + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            vals = [x["code"], x["name"] + ("" if x["known"] else " (not in subject list)"), x["candidates"],
                    _n(x["avg"]), x["max"] if x["max"] is not None else "", x["min"] if x["min"] is not None else "",
                    x["passed"], x["failed"], x["above90"], x["centums"], _n(x["pi"])]
            for c, v in enumerate(vals):
                fmt = f.num(2, **band) if c in (3, 10) else f.cell(align="center" if c != 1 else "left", bold=c == 1, **band)
                if isinstance(v, str):
                    ws.write_string(rr, c, v, fmt)
                else:
                    ws.write(rr, c, v, fmt)
            for j, gname in enumerate(GRADE_ORDER):
                ws.write(rr, 11 + j, x["grades"].get(gname, 0), f.cell(align="center", **band))
            # PI written as a formula from the grade counts, so it can be checked
            g = {gname: rc(rr, 11 + j) for j, gname in enumerate(GRADE_ORDER)}
            w = cfg.rules["board"]["pi_weights"]
            num = "+".join(f"{w.get(gname, 0)}*{g[gname]}" for gname in GRADE_ORDER)
            den = "+".join(g[gname] for gname in GRADE_ORDER)
            ws.write_formula(rr, 10, f'=IF(({den})=0,"",({num})*100/(8*({den})))', f.num(2, bold=True, **band), _n(x["pi"]))
        n = len(subj)
        last = hr + n
        ws.conditional_format(hr + 1, 3, last, 3, {"type": "data_bar", "bar_color": "#9FDCF5", "bar_solid": True,
                                                   "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 100})
        ws.write(last + 2, 1, "PI (Performance Index) = (8×A1 + 7×A2 + 6×B1 + 5×B2 + 4×C1 + 3×C2 + 2×D1 + 1×D2 + 0×E) "
                              "× 100 ÷ (8 × number of candidates). Weights are in Settings.", f.note())
        # charts
        ch = self._sw.chart("column", "Average marks by subject")
        ch.add_series({"categories": f"='Subjects'!$B${hr + 2}:$B${last + 1}",
                       "values": f"='Subjects'!$D${hr + 2}:$D${last + 1}", "fill": {"color": theme.BLUE}, "gap": 50,
                       "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        self._sw.axis_style(ch, y_max=100)
        ws.insert_chart(last + 4, 1, ch, {"x_scale": 1.35, "y_scale": 1.1})
        ch = self._sw.chart("bar", "Grades in each subject (CBSE grades)", "percent_stacked")
        for j, gname in enumerate(GRADE_ORDER):
            col = 11 + j
            letter = xlsxwriter.utility.xl_col_to_name(col)
            ch.add_series({"name": gname, "categories": f"='Subjects'!$B${hr + 2}:$B${last + 1}",
                           "values": f"='Subjects'!${letter}${hr + 2}:${letter}${last + 1}",
                           "fill": {"color": GRADE_COLORS[gname]}, "gap": 40})
        ch.set_legend({"position": "bottom", "font": {"size": 8}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}})
        ch.set_x_axis({"num_font": {"size": 8, "color": theme.MUTED}, "num_format": "0%"})
        ws.insert_chart(last + 4, 9, ch, {"x_scale": 1.3, "y_scale": 1.1})
        ch = self._sw.chart("bar", "Performance Index (PI) by subject")
        ch.add_series({"categories": f"='Subjects'!$B${hr + 2}:$B${last + 1}",
                       "values": f"='Subjects'!$K${hr + 2}:$K${last + 1}", "fill": {"color": theme.NAVY}, "gap": 40,
                       "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}})
        ch.set_x_axis({"min": 0, "max": 100, "num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ws.insert_chart(last + 21, 1, ch, {"x_scale": 1.35, "y_scale": 1.1})
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 0)
        self.subj_rows = (hr + 1, last)

    # -------------------------------------------------------------- Dashboard
    def dashboard(self):
        ws, f, cfg, an = self.ws["Board Dashboard"], self.f, self.cfg, self.an
        m = an["meta"]
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 18, 8.6)
        self._sw.banner(ws, f"Board Results {m['year']} - Class {m['cls'] or 'XII'}",
                        f"{m['title']} · School {m['school_code']} · {m['region'].title()} · result date {m['date']}", 18)
        kp = [("Candidates", an["candidates"], "0"), ("Pass %", _n(an["pass_pct"]), "0.0"),
              ("Compartment", an["comp"], "0"), ("Average (best 5) %", _n(an["avg_best5"]), "0.0"),
              ("90% and above", an["above90"], "0"), ("School PI", _n(an["school_pi"]), "0.0")]
        for i, (lab, v, nf) in enumerate(kp):
            c0 = 1 + i * 3
            ws.merge_range(5, c0, 5, c0 + 2, "", f.get(bg_color=theme.TINT, top=2, top_color=theme.BLUE))
            ws.merge_range(6, c0, 6, c0 + 2, v, f.get(font_name=theme.TITLE_FONT, font_size=24, font_color=theme.NAVY,
                                                      align="center", bg_color=theme.TINT, num_format=nf))
            ws.merge_range(7, c0, 7, c0 + 2, lab, f.kpi_label())
        ws.set_row(5, 6)
        ws.set_row(6, 38)
        ws.set_row(7, 18)
        # best-5 distribution data (on the dashboard, right side, small)
        dr = 40
        ws.write(dr, 1, "Best 5 % range", f.header())
        ws.write(dr, 2, "Students", f.header())
        for i, (lab, cnt) in enumerate(an["distribution"]):
            ws.write_string(dr + 1 + i, 1, lab, f.cell())
            ws.write_number(dr + 1 + i, 2, cnt, f.cell(align="center"))
        ch = self._sw.chart("column", "Students by best-5 percentage")
        nd = len(an["distribution"])
        ch.add_series({"categories": f"='Board Dashboard'!$B${dr + 2}:$B${dr + 1 + nd}",
                       "values": f"='Board Dashboard'!$C${dr + 2}:$C${dr + 1 + nd}", "fill": {"color": theme.NAVY},
                       "gap": 30, "data_labels": {"value": True, "font": {"size": 9, "color": theme.NAVY}}})
        self._sw.axis_style(ch)
        ws.insert_chart(9, 1, ch, {"x_scale": 1.15, "y_scale": 1.05})
        s0, s1 = self.subj_rows
        ch = self._sw.chart("bar", "Average marks by subject")
        ch.add_series({"categories": f"='Subjects'!$B${s0 + 1}:$B${s1 + 1}", "values": f"='Subjects'!$D${s0 + 1}:$D${s1 + 1}",
                       "fill": {"color": theme.BLUE}, "gap": 35,
                       "data_labels": {"value": True, "num_format": "0.0", "font": {"size": 8, "color": theme.NAVY}}})
        ch.set_y_axis({"reverse": True, "num_font": {"size": 8}})
        ch.set_x_axis({"min": 0, "max": 100, "num_format": "0", "num_font": {"size": 8, "color": theme.MUTED},
                       "major_gridlines": {"visible": True, "line": {"color": "#E8EEF3"}}})
        ws.insert_chart(9, 9, ch, {"x_scale": 1.2, "y_scale": 1.6})
        # toppers mini table
        tr = 25
        ws.merge_range(tr, 1, tr, 7, "Top 10 (best 5 %)", f.section())
        for c, h in enumerate(["#", "Name", "", "", "Best 5 %", "Result"], 1):
            if h:
                ws.write(tr + 1, c, h, f.header())
        ws.merge_range(tr + 1, 2, tr + 1, 4, "Name", f.header())
        for i, r in enumerate(an["ranked"][:10]):
            rr = tr + 2 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write(rr, 1, r["rank"], f.cell(align="center", bold=True, **band))
            ws.merge_range(rr, 2, rr, 4, r["s"].name, f.cell(**band))
            ws.write(rr, 5, float(r["best5"]), f.num(1, bold=True, **band))
            ws.write_string(rr, 6, r["s"].result, f.cell(align="center", **band))
        if an["gender"] and len([g for g in an["gender"] if g["gender"] != "?"]) > 1:
            gr = 38
            ws.write(gr, 9, "Group", f.header())
            ws.write(gr, 10, "Students", f.header())
            ws.write(gr, 11, "Pass %", f.header())
            ws.write(gr, 12, "Avg best 5 %", f.header())
            for i, g in enumerate(an["gender"]):
                ws.write_string(gr + 1 + i, 9, g["gender"], f.cell())
                ws.write_number(gr + 1 + i, 10, g["n"], f.cell(align="center"))
                ws.write(gr + 1 + i, 11, _n(g["pass_pct"]), f.num(1))
                ws.write(gr + 1 + i, 12, _n(g["avg_best5"]), f.num(1))
        ws.write(37, 1, "Grades and results are CBSE's own (copied from the gazette). Best 5 % = English + best four others.",
                 f.note())
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 1)
        ws.print_area(0, 0, 37, 18)

    # -------------------------------------------------------------- Toppers & compartment
    def toppers(self):
        ws, f, cfg, an = self.ws["Toppers"], self.f, self.cfg, self.an
        self._sw.banner(ws, "Toppers and compartment", "Overall toppers, subject toppers and students with a compartment.", 9)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 6)
        ws.set_column(2, 2, 26)
        ws.set_column(3, 9, 12)
        r = 4
        ws.write(r, 1, "Top 25 (best 5 %)", f.section())
        r += 1
        for c, h in enumerate(["Rank", "Name", "Roll No", "Best 5 %", "All subjects %", "Result"], 1):
            ws.write(r, c, h, f.header())
        for i, x in enumerate(an["ranked"][:25]):
            rr = r + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write(rr, 1, x["rank"], f.cell(align="center", bold=True, **band))
            ws.write_string(rr, 2, x["s"].name, f.cell(**band))
            ws.write_string(rr, 3, x["s"].roll, f.cell(align="center", **band))
            ws.write(rr, 4, float(x["best5"]), f.num(2, bold=True, **band))
            ws.write(rr, 5, _n(x["pct_all"]), f.num(2, **band))
            ws.write_string(rr, 6, x["s"].result, f.cell(align="center", **band))
        r += 28
        ws.write(r, 1, "Subject toppers", f.section())
        r += 1
        for c, h in enumerate(["Code", "Subject", "Highest", "Scored by"], 1):
            ws.write(r, c, h, f.header())
        ws.set_column(4, 4, 60)
        for i, x in enumerate(an["subjects"]):
            rr = r + 1 + i
            band = {"bg_color": theme.TINT2} if i % 2 else {}
            ws.write_string(rr, 1, x["code"], f.cell(**band))
            ws.write_string(rr, 2, x["name"], f.cell(bold=True, **band))
            ws.write(rr, 3, x["max"] if x["max"] is not None else "", f.cell(align="center", **band))
            ws.write_string(rr, 4, ", ".join(x["toppers"]), f.cell(**band))
        r += len(an["subjects"]) + 3
        ws.write(r, 1, f"Compartment ({len(an['comp_list'])})", f.section())
        r += 1
        for c, h in enumerate(["Roll No", "Name", "Compartment in", "Marks there"], 1):
            ws.write(r, c, h, f.header())
        for i, s in enumerate(an["comp_list"]):
            rr = r + 1 + i
            ws.write_string(rr, 1, s.roll, f.cell())
            ws.write_string(rr, 2, s.name, f.cell(bold=True))
            ws.write_string(rr, 3, ", ".join(cfg.subject_name(c) for c in s.comp), f.cell(font_color=theme.RED))
            mk = [str(x["marks"]) for x in s.subjects if x["code"] in s.comp and x["marks"] is not None]
            ws.write_string(rr, 4, ", ".join(mk), f.cell())
        if an["others_list"]:
            r += len(an["comp_list"]) + 3
            ws.write(r, 1, "Other results (not PASS / COMP)", f.section())
            for i, s in enumerate(an["others_list"]):
                ws.write_string(r + 1 + i, 2, f"{s.name} ({s.roll}): {s.result}", f.cell())

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


def write_board_workbook(analyses, cfg, years=None, link=None, raw_texts=None, logo=None):
    return BoardWorkbook(analyses, cfg, years=years, link=link, raw_texts=raw_texts, logo=logo).build()
