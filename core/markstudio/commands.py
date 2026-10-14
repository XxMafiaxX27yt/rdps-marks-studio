"""'Change the Excel with words': turns a typed or spoken instruction into one
safe recipe change (add a chart, highlight, change a setting, add a sheet,
hide a sheet, undo). Nothing here can change a mark."""
import re

from .nlu import Understander, _has
from .textutil import norm

SETTING_WORDS = [
    ("pass_percent", ["pass mark", "passing mark", "pass marks", "pass percentage", "pass percent", "passing percentage",
                      "pass %", "minimum to pass"]),
    ("weak_gap", ["weak threshold", "weak gap", "weak", "weak points"]),
    ("strong_gap", ["strong threshold", "strong gap", "strong", "strong points"]),
    ("attention_class_gap", ["attention threshold", "attention gap", "needs attention", "attention"]),
    ("drop_alert_gap", ["drop alert", "drop threshold", "drop", "alert"]),
]
SETTING_LIMITS = {"pass_percent": (1, 99), "weak_gap": (0.5, 50), "strong_gap": (0.5, 50),
                  "attention_class_gap": (0.5, 50), "drop_alert_gap": (0.5, 50)}
SETTING_NAMES = {"pass_percent": "pass mark (%)", "weak_gap": "weak threshold (points below own average)",
                 "strong_gap": "strong threshold (points above own average)",
                 "attention_class_gap": "needs-attention threshold (points below class average)",
                 "drop_alert_gap": "progress drop alert (points)"}
COLOR_WORDS = ["red", "green", "amber", "orange", "yellow", "blue"]
KIND_WORDS = [("doughnut", ["doughnut", "donut", "ring"]), ("pie", ["pie"]), ("line", ["line", "trend"]),
              ("bar", ["bar", "horizontal"]), ("radar", ["radar", "spider"]), ("column", ["column", "vertical"])]
BASE_SHEETS = ["Dashboard", "Report Card", "Subject Analysis", "Marks Analysis", "Progress", "Marks Matrix",
               "Subject Results", "Student Master", "Validation Report", "Config", "Source Data", "My Charts"]


def parse_command(text, ds, res, recipe, cfg):
    """-> {'item': {...}, 'description': '...'} or {'error': '...', 'suggestions': [...]}"""
    low = text.lower().strip()
    if not low:
        return {"error": "Type what you want to change."}
    U = Understander(ds, res, cfg=cfg)
    if re.match(r"^(undo|undo that|go back|remove the last( chart| change| thing)?|delete the last( chart| change)?)\b", low):
        return {"item": {"type": "undo"}, "description": "Undo the last change."}
    # settings
    m = re.search(r"\b(?:change|set|make|update|put)\b.*?\bto\s+(\d+(?:\.\d+)?)", low) or \
        re.search(r"\b(?:change|set|make|update|put)\b.*?(\d+(?:\.\d+)?)", low)
    if m and not _has(low, ["chart", "graph", "highlight", "colour", "color", "sheet"]):
        if "academic year" in low or re.search(r"\byear\b", low):
            ym = re.search(r"(20\d\d\s*-\s*\d{2,4})", text)
            if ym:
                return {"item": {"type": "setting", "key": "academic_year", "value": ym.group(1).replace(" ", "")},
                        "description": f"Set the academic year to {ym.group(1)}."}
        for key, words in SETTING_WORDS:
            if _has(low, words):
                val = float(m.group(1))
                lo, hi = SETTING_LIMITS[key]
                if not lo <= val <= hi:
                    return {"error": f"The {SETTING_NAMES[key]} must be between {lo} and {hi}."}
                val = int(val) if val == int(val) else val
                return {"item": {"type": "setting", "key": key, "value": val},
                        "description": f"Change the {SETTING_NAMES[key]} from {cfg.rules[key]} to {val}. "
                                       f"All labels and results are worked out again."}
    # hide a sheet
    m = re.search(r"\bhide\b(?: the)?\s+(.+?)(?: sheet| tab)?$", low)
    if m:
        target = norm(m.group(1)).replace(" sheet", "")
        names = BASE_SHEETS + [it["sheet"] for it in recipe.get("items", []) if it.get("type") == "query_sheet"]
        hit = next((n for n in names if norm(n) == target or norm(n).startswith(target)), None)
        if not hit:
            return {"error": f"There is no sheet called “{m.group(1)}”.", "suggestions": ["hide source data"]}
        if hit == "Dashboard":
            return {"error": "The Dashboard can't be hidden."}
        return {"item": {"type": "hide_sheet", "sheet": hit}, "description": f"Hide the “{hit}” sheet (it is still in the file)."}
    e = U.entities(text)
    # highlight
    if _has(low, ["highlight", "colour", "color", "shade", "mark in", "paint"]):
        thr = e["thresholds"]
        if not thr:
            return {"error": "Tell me which marks to highlight, e.g. “highlight students below 40% in red”."}
        op, val, _ = thr[0]
        color = next((c for c in COLOR_WORDS if re.search(r"\b" + c + r"\b", low)), "red" if op in ("<", "<=") else "green")
        item = {"type": "highlight", "op": op, "value": val, "color": color,
                "subject": e["subjects"][0] if e["subjects"] else None, "exam": e["exams"][0] if e["exams"] else None}
        word = {"<": "below", "<=": "at or below", ">": "above", ">=": "at or above"}[op]
        what = f"{cfg.subject_name(item['subject'])} marks" if item["subject"] else "students' overall %"
        return {"item": item, "description": f"Highlight {what} {word} {fmt(val)}% in {color}"
                + (f" ({cfg.exam_name(item['exam'])})" if item["exam"] else "") + " on the Marks Matrix and Subject Results."}
    # chart
    if _has(low, ["chart", "graph", "plot", "diagram", "visual"]):
        metric = "average"
        if _has(low, ["pass", "passing"]):
            metric = "pass_rate"
        elif _has(low, ["highest", "max", "maximum", "top score"]):
            metric = "highest"
        elif _has(low, ["lowest", "min", "minimum"]):
            metric = "lowest"
        elif _has(low, ["how many", "number of", "count", "students"]) and not _has(low, ["average"]):
            metric = "count"
        kind = next((k for k, words in KIND_WORDS if _has(low, words)), None)
        by = e["by"]
        m = re.search(r"\b(?:by|per|for each|across|over)\s+(subject|section|exam|test|group|stream|class)s?\b", low)
        if m:
            by = {"test": "exam", "stream": "group"}.get(m.group(1), m.group(1))
        if not by:
            if e["subjects"]:
                by = "exam" if _has(low, ["trend", "over time", "progress", "across exams"]) else "section"
            else:
                by = "subject"
        filters = {}
        if e["subjects"] and by != "subject":
            filters["subject"] = e["subjects"][0]
        if e["classes"]:
            filters["cls"] = e["classes"][0]
        if e["sections"] and by != "section":
            filters["section"] = e["sections"][0]
        if e["groups"] and by != "group":
            filters["group"] = e["groups"][0]
        if e["exams"] and by != "exam":
            filters["exam"] = e["exams"][0]
        if by != "class" and not filters.get("cls") and len(ds.classes()) > 1:
            filters["cls"] = ds.classes()[0]
            cls_note = f" (Class {filters['cls']} - say 'class XII' for the other class)"
        else:
            cls_note = ""
        if by == "exam" and not filters.get("cls") and ds.classes():
            filters["cls"] = ds.classes()[0]
        if not filters.get("exam") and by != "exam":
            cls = filters.get("cls") or (ds.classes()[0] if ds.classes() else None)
            ex = ds.exams_for(cls) if cls else []
            if ex:
                filters["exam"] = ex[-1]
        kind = kind or ("line" if by == "exam" else "column")
        item = {"type": "chart", "metric": metric, "by": by, "filters": filters, "kind": kind}
        from .excel.extras import chart_title, METRIC_NAMES
        class _S:  # tiny stand-in so chart_title can be used without a workbook
            pass
        s = _S()
        s.cfg = cfg
        title = chart_title(s, item)
        item["title"] = title
        return {"item": item, "description": f"Add a {kind} chart: {title}{cls_note}. It is added to a 'My Charts' sheet and "
                                              f"updates when marks change."}
    # sheet from a question
    m = re.search(r"\b(?:add|make|create|new|save)\b.*?\b(?:sheet|tab)\b\s*(?:with|of|for|showing|listing|that shows)?\s*(.*)$", low)
    if m and m.group(1).strip():
        return {"sheet_question": m.group(1).strip()}
    return {"error": "I can't make that change yet. I can add charts, highlight marks, change the label settings, "
                     "add a sheet from a question, hide a sheet, or undo.",
            "suggestions": ["Add a chart of Physics averages by section", "Highlight students below 40% in red",
                            "Change the weak threshold to 8", "Add a sheet with the top 10 in Group A",
                            "Hide the Source Data sheet", "Undo"]}


def fmt(v):
    return str(int(v)) if float(v) == int(v) else str(v)
