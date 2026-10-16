"""Board (CBSE gazette) analysis - kept separate from the school tests.

Board marks are final, official marks out of 100 per subject. We never change
them; we only add up, compare and summarise. CBSE's own grades are shown
exactly as printed (they are position-based, so they are not worked out again)."""
from decimal import Decimal

from .textutil import r6, norm_name

BEST5_BINS = [(95, 101, "95-100"), (90, 95, "90-95"), (80, 90, "80-90"), (70, 80, "70-80"),
              (60, 70, "60-70"), (0, 60, "Below 60")]
GRADE_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E"]


def _passed_grade(grade, cfg):
    return grade not in cfg.rules["board"]["fail_grades"]


PASS_MARK = 33
MARK_BANDS = [(90, 101, "90-100"), (80, 90, "80-89"), (70, 80, "70-79"), (60, 70, "60-69"), (50, 60, "50-59"),
              (33, 50, "33-49"), (0, 33, "Below 33")]


def entry_passed(x, cfg):
    """True / False / None (no mark and no grade). CBSE's grade decides; without grades, 33 marks."""
    if x.get("grade"):
        return _passed_grade(x["grade"], cfg)
    if x.get("marks") is None:
        return None
    return x["marks"] >= PASS_MARK


def bands(marks):
    """Marks -> [[label, count]] in the bands above (highest first)."""
    return [[lab, sum(1 for m in marks if lo <= m < hi)] for lo, hi, lab in MARK_BANDS]


def student_totals(s, cfg):
    marks = [(x["code"], x["marks"]) for x in s.subjects if x["marks"] is not None]
    if not marks:
        return {"total": None, "count": 0, "pct_all": None, "best5": None, "best5_subjects": []}
    total = sum(m for _, m in marks)
    pct_all = Decimal(total) / Decimal(len(marks))
    langs = set(cfg.rules["board"]["language_codes"])
    lang = [x for x in marks if x[0] in langs]
    best = []
    if len(marks) >= 5:
        if lang:
            first = max(lang, key=lambda x: x[1])
            rest = sorted([x for x in marks if x is not first], key=lambda x: -x[1])[:4]
            best = [first] + rest
        else:
            best = sorted(marks, key=lambda x: -x[1])[:5]
    best5 = Decimal(sum(m for _, m in best)) / Decimal(5) if best else None
    return {"total": total, "count": len(marks), "pct_all": pct_all, "best5": best5,
            "best5_subjects": [c for c, _ in best]}


def analyse(g, cfg):
    """-> dict with everything the board report shows."""
    studs = g.students
    rows = []
    for s in studs:
        t = student_totals(s, cfg)
        rows.append({"s": s, **t})
    n = len(studs)
    passed = sum(1 for s in studs if s.result == "PASS")
    comp = [s for s in studs if s.result in ("COMP", "COMPTT")]
    others = [s for s in studs if s.result not in ("PASS", "COMP", "COMPTT")]
    # subjects
    codes = []
    for s in studs:
        for x in s.subjects:
            if x["code"] not in codes:
                codes.append(x["code"])
    codes = cfg.order_subjects(codes)
    weights = cfg.rules["board"]["pi_weights"]
    subj = []
    for c in codes:
        entries = [x for s in studs for x in s.subjects if x["code"] == c]
        marks = [x["marks"] for x in entries if x["marks"] is not None]
        grades = {}
        for x in entries:
            if x["grade"]:
                grades[x["grade"]] = grades.get(x["grade"], 0) + 1
        graded = sum(grades.values())
        pi = (Decimal(sum(weights.get(gr, 0) * k for gr, k in grades.items())) * 100 / (Decimal(8) * graded)) if graded else None
        subj.append({
            "code": c, "name": cfg.board_name(c, g.cls), "short": cfg.board_short(c, g.cls),
            "known": c in cfg.subjects or c in cfg.rules.get("board", {}).get("x_names", {}),
            "candidates": len(entries), "avg": Decimal(sum(marks)) / len(marks) if marks else None,
            "max": max(marks) if marks else None, "min": min(marks) if marks else None,
            "passed": sum(1 for x in entries if entry_passed(x, cfg) is True),
            "failed": sum(1 for x in entries if entry_passed(x, cfg) is False),
            "grades": grades, "pi": pi, "bands": bands(marks),
            "above90": sum(1 for m in marks if m >= 90), "centums": sum(1 for m in marks if m == 100),
            "toppers": [s.name for s in studs for x in s.subjects if x["code"] == c and marks and x["marks"] == max(marks)],
        })
    # whole-school PI over all subjects
    all_grades = {}
    for x in subj:
        for gr, k in x["grades"].items():
            all_grades[gr] = all_grades.get(gr, 0) + k
    tg = sum(all_grades.values())
    school_pi = (Decimal(sum(weights.get(gr, 0) * k for gr, k in all_grades.items())) * 100 / (Decimal(8) * tg)) if tg else None
    best = [r for r in rows if r["best5"] is not None]
    ranked = sorted(best, key=lambda r: (-r["best5"], norm_name(r["s"].name)))
    for r in rows:
        r["rank"] = 1 + sum(1 for o in best if r["best5"] is not None and o["best5"] > r["best5"]) if r["best5"] is not None else None
    dist = []
    for lo, hi, lab in BEST5_BINS:
        dist.append((lab, sum(1 for r in best if Decimal(lo) <= r["best5"] < Decimal(hi))))
    genders = {}
    for r in rows:
        gnd = r["s"].gender or "?"
        d = genders.setdefault(gnd, {"n": 0, "pass": 0, "sum": Decimal(0), "k": 0})
        d["n"] += 1
        d["pass"] += 1 if r["s"].result == "PASS" else 0
        if r["best5"] is not None:
            d["sum"] += r["best5"]
            d["k"] += 1
    gender = [{"gender": {"F": "Girls", "M": "Boys", "T": "Transgender"}.get(k, k), "n": v["n"],
               "pass_pct": Decimal(v["pass"]) * 100 / v["n"] if v["n"] else None,
               "avg_best5": v["sum"] / v["k"] if v["k"] else None} for k, v in sorted(genders.items())]
    internal = {}
    for s in studs:
        for i, gr in enumerate(s.internal):
            internal.setdefault(i, {}).setdefault(gr, 0)
            internal[i][gr] += 1
    return {
        "meta": {"title": g.title, "year": g.year, "cls": g.cls, "exam_type": g.exam_type, "region": g.region,
                 "school_code": g.school_code, "school_name": g.school_name, "date": g.date, "file": g.file,
                 "kind": getattr(g, "kind", "gazette"), "graded": tg > 0},
        "candidates": n, "passed": passed, "comp": len(comp), "others": len(others),
        "pass_pct": Decimal(passed) * 100 / n if n else None,
        "avg_best5": sum((r["best5"] for r in best), Decimal(0)) / len(best) if best else None,
        "avg_all": sum((r["pct_all"] for r in rows if r["pct_all"] is not None), Decimal(0)) /
                   len([r for r in rows if r["pct_all"] is not None]) if any(r["pct_all"] is not None for r in rows) else None,
        "above90": sum(1 for r in best if r["best5"] >= 90), "above95": sum(1 for r in best if r["best5"] >= 95),
        "school_pi": school_pi, "rows": rows, "ranked": ranked, "subjects": subj, "distribution": dist,
        "gender": gender, "comp_list": comp, "others_list": others, "internal": internal, "codes": codes,
        "totals": g.totals, "issues": g.issues,
    }


def compare_years(analyses):
    """Several gazettes (different years) -> per-subject averages and PI by year."""
    years = sorted({a["meta"]["year"] for a in analyses})
    by_year = {a["meta"]["year"]: a for a in analyses}
    codes = []
    for a in analyses:
        for c in a["codes"]:
            if c not in codes:
                codes.append(c)
    out = []
    for c in codes:
        row = {"code": c, "values": []}
        for y in years:
            s = next((x for x in by_year[y]["subjects"] if x["code"] == c), None)
            row["values"].append((y, s["avg"] if s else None, s["pi"] if s else None))
        out.append(row)
    summary = [(y, by_year[y]["pass_pct"], by_year[y]["avg_best5"], by_year[y]["school_pi"], by_year[y]["candidates"])
               for y in years]
    return {"years": years, "subjects": out, "summary": summary}


def school_vs_board(an, ds, res, cfg):
    """Link board students to school students by Board Roll No (then by exact name, flagged)."""
    if ds is None or res is None:
        return None
    gcls = an["meta"].get("cls") or "XII"
    code_map = {k: v for k, v in cfg.rules.get("board", {}).get("school_code_map", {}).items() if not k.startswith("_")}
    by_roll = {s.board_roll: s for s in ds.students.values() if s.board_roll}
    by_adm = {s.adm_no.upper(): s for s in ds.students.values() if s.adm_no}
    by_name = {}
    for s in ds.students.values():
        if s.cls == gcls:
            by_name.setdefault(norm_name(s.name), []).append(s)
    links, notes = [], []
    for r in an["rows"]:
        b = r["s"]
        st = by_roll.get(getattr(b, "board_roll", "") or b.roll)
        how = "board roll"
        if st is None and getattr(b, "adm_no", ""):
            st, how = by_adm.get(b.adm_no.upper()), "admission no"
        if st is None:
            cands = by_name.get(norm_name(b.name), [])
            if len(cands) == 1:
                st, how = cands[0], "name (please check)"
        if st is None:
            continue
        exams = ds.exams_for(st.cls)
        pre = "PB" if "PB" in exams else (exams[-1] if exams else None)
        if not pre:
            continue
        for x in b.subjects:
            if x["marks"] is None:
                continue
            er = res.exam_results.get((st.sid, pre))
            school_code = x["code"] if x["code"] in cfg.subjects and x["code"] not in code_map else code_map.get(x["code"], x["code"])
            if gcls == "X" and x["code"] == "241":
                school_code = "041"                      # Class X Maths Basic is the school's Maths
            row = next((y for y in er.rows if y.subject == school_code), None) if er else None
            if row is None or row.pct is None:
                continue
            links.append({"name": b.name, "roll": b.roll, "sid": st.sid, "how": how, "subject": x["code"],
                          "school_exam": pre, "school_pct": row.pct, "board": Decimal(x["marks"]),
                          "gap": Decimal(x["marks"]) - row.pct})
    subj = {}
    for l in links:
        d = subj.setdefault(l["subject"], [])
        d.append(l["gap"])
    by_subject = [{"code": c, "name": cfg.board_name(c, gcls), "n": len(v), "avg_gap": sum(v, Decimal(0)) / len(v)}
                  for c, v in subj.items()]
    by_subject.sort(key=lambda x: cfg.subject_order.index(x["code"]) if x["code"] in cfg.subject_order else 99)
    return {"links": links, "by_subject": by_subject,
            "linked_students": len({l["roll"] for l in links}),
            "by_name": len({l["roll"] for l in links if l["how"].startswith("name")})}
