"""Things added to the workbook with word commands ("add a chart of Physics
averages by section", "highlight students below 40% in red", "add a sheet with
the top 10 in Group A"). They are stored in the workbook's recipe and rebuilt
every time, so they never corrupt the file and can be undone."""
from decimal import Decimal

from xlsxwriter.utility import xl_rowcol_to_cell as rc

from . import theme
from ..calc import STATUS_OK
from ..textutil import r6

COLORS = {"red": (theme.RED, theme.RED_BG), "green": (theme.GREEN, theme.GREEN_BG),
          "amber": (theme.AMBER, theme.AMBER_BG), "orange": (theme.AMBER, theme.AMBER_BG),
          "yellow": ("#7A5C00", "#FFF3B0"), "blue": (theme.NAVY, theme.TINT)}
METRIC_NAMES = {"average": "Average %", "pass_rate": "Pass %", "highest": "Highest %", "lowest": "Lowest %",
                "count": "Students"}


def categories(sw, by, filters):
    cfg, ds = sw.cfg, sw.ds
    if by == "subject":
        return [(s, cfg.subject_name(s), cfg.subject_short(s)) for s in sw.subjects]
    if by == "section":
        return [(s, s, s) for s in sw.sections]
    if by == "exam":
        cls = filters.get("cls")
        ex = ds.exams_for(cls) if cls else sw.exams
        return [(e, cfg.exam_name(e), cfg.exam_name(e)) for e in ex]
    if by == "group":
        present = sorted({s.group for s in ds.students.values() if s.group})
        return [(g, g, f"Group {g}") for g in present]
    if by == "class":
        return [(c, c, cfg.class_label(c)) for c in sw.classes]
    return []


def _crit_and_cond(sw, filters, by, cat_cell):
    cfg = sw.cfg
    crit, cond = [], []
    fields = {"cls": "SR_Class", "exam": "SR_Exam", "subject": "SR_Subject", "section": "SR_Section", "group": "SR_Group"}
    for k, rng in fields.items():
        v = filters.get(k)
        if v and k != by.replace("class", "cls"):
            if k == "exam":
                v = cfg.exam_name(v)
            elif k == "subject":
                v = cfg.subject_name(v)
            crit.append(f'{rng},"{v}"')
            cond.append(f'({rng}="{v}")')
    byrng = {"subject": "SR_Subject", "section": "SR_Section", "exam": "SR_Exam", "group": "SR_Group",
             "class": "SR_Class"}[by]
    crit.append(f"{byrng},{cat_cell}")
    cond.append(f"({byrng}={cat_cell})")
    return ",".join(crit), "*".join(cond)


def py_value(sw, metric, by, cat, filters):
    rows = []
    for r in sw.res.rows:
        st = sw.ds.students[r.sid]
        vals = {"cls": st.cls, "exam": r.exam, "subject": r.subject, "section": st.section, "group": st.group}
        okf = all(not filters.get(k) or vals[k] == filters[k] for k in vals if k != by.replace("class", "cls"))
        key = {"subject": r.subject, "section": st.section, "exam": r.exam, "group": st.group, "class": st.cls}[by]
        if okf and key == cat:
            rows.append(r)
    ok = [r for r in rows if r.status == STATUS_OK]
    if metric == "average":
        return sum((r.pct for r in ok), Decimal(0)) / len(ok) if ok else None
    if metric == "highest":
        return max((r.pct for r in ok), default=None)
    if metric == "lowest":
        return min((r.pct for r in ok), default=None)
    if metric == "count":
        return len(ok)
    if metric == "pass_rate":
        y = sum(1 for r in rows if r.passed == "Yes")
        n = sum(1 for r in rows if r.passed == "No")
        return Decimal(y) / Decimal(y + n) * 100 if y + n else None
    return None


def chart_title(sw, it):
    cfg = sw.cfg
    f = it.get("filters", {})
    bits = [METRIC_NAMES.get(it["metric"], it["metric"]), "by", it["by"]]
    ctx = []
    if f.get("subject"):
        ctx.append(cfg.subject_name(f["subject"]))
    if f.get("cls"):
        ctx.append(cfg.class_label(f["cls"]))
    if f.get("section"):
        ctx.append("Section " + f["section"])
    if f.get("group"):
        ctx.append("Group " + f["group"])
    if f.get("exam"):
        ctx.append(cfg.exam_name(f["exam"]))
    return it.get("title") or (" ".join(bits) + (" - " + ", ".join(ctx) if ctx else ""))


def write_extras(sw):
    items = sw.recipe.get("items", [])
    charts = [it for it in items if it.get("type") == "chart"]
    if charts:
        ws = sw.sheets["My Charts"]
        f = sw.f
        ws.hide_gridlines(2)
        ws.set_column(0, 0, 2)
        ws.set_column(1, 1, 22)
        ws.set_column(2, 2, 12)
        ws.set_column(3, 16, 9)
        sw.banner(ws, "My Charts", "Charts you added with words. They update when marks change.", 16)
        r = 4
        for it in charts:
            filters = it.get("filters", {})
            title = chart_title(sw, it)
            ws.write(r, 1, title, f.section())
            ws.write(r + 1, 1, it["by"].title(), f.header())
            ws.write(r + 1, 2, METRIC_NAMES.get(it["metric"], it["metric"]), f.header())
            cats = categories(sw, it["by"], filters)
            for i, (code, name, short) in enumerate(cats):
                rr = r + 2 + i
                ws.write_string(rr, 1, name, f.cell())
                cell = rc(rr, 1)
                crit, cond = _crit_and_cond(sw, filters, it["by"], cell)
                m = it["metric"]
                if m == "average":
                    fml = f'=IFERROR(AVERAGEIFS(SR_Pct,{crit},SR_Status,"OK"),NA())'
                elif m == "highest":
                    fml = f'=IFERROR(_xlfn.AGGREGATE(14,6,SR_Pct/({cond}*(SR_Status="OK")),1),NA())'
                elif m == "lowest":
                    fml = f'=IFERROR(_xlfn.AGGREGATE(15,6,SR_Pct/({cond}*(SR_Status="OK")),1),NA())'
                elif m == "count":
                    fml = f'=COUNTIFS({crit},SR_Status,"OK")'
                else:
                    fml = (f'=IFERROR(COUNTIFS({crit},SR_Passed,"Yes")/(COUNTIFS({crit},SR_Passed,"Yes")+'
                           f'COUNTIFS({crit},SR_Passed,"No"))*100,NA())')
                v = py_value(sw, m, it["by"], code, filters)
                ws.write_formula(rr, 2, fml, f.num(1 if m != "count" else 0),
                                 float(v) if v is not None else "#N/A")
            n = max(1, len(cats))
            kind = it.get("kind", "column")
            ch = sw.chart(kind if kind in ("column", "bar", "line", "pie", "doughnut", "radar") else "column", title)
            ser = {"categories": f"='My Charts'!{rc(r + 2, 1, True, True)}:{rc(r + 1 + n, 1, True, True)}",
                   "values": f"='My Charts'!{rc(r + 2, 2, True, True)}:{rc(r + 1 + n, 2, True, True)}",
                   "data_labels": {"value": True, "num_format": "0" if it["metric"] == "count" else "0.0",
                                   "font": {"size": 8}}}
            if kind in ("pie", "doughnut"):
                ser["points"] = [{"fill": {"color": theme.SERIES[i % len(theme.SERIES)]}} for i in range(n)]
                ch.set_legend({"position": "right", "font": {"size": 8}})
            elif kind == "line":
                ser["line"] = {"color": theme.NAVY, "width": 2.25}
                ser["marker"] = {"type": "circle", "size": 6, "fill": {"color": theme.BLUE}}
            else:
                ser["fill"] = {"color": theme.BLUE}
            ch.add_series(ser)
            if kind in ("column", "line"):
                sw.axis_style(ch, y_max=100 if it["metric"] != "count" else None)
            ws.insert_chart(r + 1, 4, ch, {"x_scale": 1.25, "y_scale": 1.0})
            r += max(n + 4, 18)
    for it in items:
        if it.get("type") == "query_sheet":
            ws = sw.sheets[it["sheet"]]
            f = sw.f
            ws.hide_gridlines(2)
            ws.set_column(0, 0, 2)
            cols = it.get("columns", [])
            ws.set_column(1, max(1, len(cols)), 16)
            sw.banner(ws, it.get("title", it["sheet"]), it.get("explanation", ""), max(6, len(cols)))
            ws.write(4, 1, "Saved answer (values as of when it was made). Ask again on the website for fresh numbers.",
                     f.note())
            for c, h in enumerate(cols, 1):
                ws.write(6, c, h, f.header())
            for i, row in enumerate(it.get("rows", [])):
                for c, v in enumerate(row, 1):
                    fmt = f.cell(bg_color=theme.TINT2) if i % 2 else f.cell()
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        ws.write_number(7 + i, c, v, f.num(1 if isinstance(v, float) else 0,
                                                            **({"bg_color": theme.TINT2} if i % 2 else {})))
                    else:
                        ws.write_string(7 + i, c, "" if v is None else str(v), fmt)
        elif it.get("type") == "highlight":
            fg, bg = COLORS.get(it.get("color", "red"), COLORS["red"])
            fmt = sw.wb.add_format({"font_color": fg, "bg_color": bg, "bold": True})
            op, val = it.get("op", "<"), it.get("value", 40)
            sr = sw.sheets["Subject Results"]
            from .school import SR_PCT, SR_SUBJ, SR_EXAM, MX_FIRST
            conds = [f'ISNUMBER($Q2)', f'ROUND($Q2,6){op}{val}']
            if it.get("subject"):
                conds.append(f'$I2="{sw.cfg.subject_name(it["subject"])}"')
            if it.get("exam"):
                conds.append(f'$G2="{sw.cfg.exam_name(it["exam"])}"')
            sr.conditional_format(1, 0, max(1, sw.n_sr), 26, {"type": "formula", "criteria": "=AND(" + ",".join(conds) + ")",
                                                              "format": fmt})
            if not it.get("subject"):
                mx = sw.sheets["Overview"]
                c = sw.mx_cols["overall"]
                col = rc(MX_FIRST, c, False, True).rstrip("0123456789")
                mconds = [f"ISNUMBER({col}{MX_FIRST + 1})", f"ROUND({col}{MX_FIRST + 1},6){op}{val}"]
                if it.get("exam"):
                    mconds.append(f'$H{MX_FIRST + 1}="{sw.cfg.exam_name(it["exam"])}"')
                mx.conditional_format(MX_FIRST, 1, MX_FIRST + max(1, sw.n_mx) - 1, 3,
                                      {"type": "formula", "criteria": "=AND(" + ",".join(mconds) + ")", "format": fmt})
                mx.conditional_format(MX_FIRST, c, MX_FIRST + max(1, sw.n_mx) - 1, c,
                                      {"type": "formula", "criteria": "=AND(" + ",".join(mconds) + ")", "format": fmt})
        elif it.get("type") == "hide_sheet":
            ws = sw.sheets.get(it.get("sheet"))
            if ws is not None and it.get("sheet") not in ("Dashboard",):
                ws.hide()
