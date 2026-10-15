"""Ready-to-show numbers for the website preview and for the cached values the
workbook stores next to its formulas. Each function mirrors one Excel sheet, so
the website and the downloaded workbook always show the same answer."""
from decimal import Decimal

from .calc import STATUS_OK, progress, remarks
from .textutil import r6, norm_name

GENTLE = {"Strong": "Doing well", "On track": "On track", "Weak": "Focus area", "Needs attention": "Needs support"}
LABELS = ["Strong", "On track", "Weak", "Needs attention"]


def _f(d, places=2):
    return None if d is None else float(round(Decimal(d), places))


def matrix_order(res):
    """Order of rows in the Marks Matrix: class, exam, section, roll."""
    ds, cfg = res.ds, res.cfg
    pos = {s.sid: i for i, s in enumerate(ds.ordered_students())}
    cls_order = {c: i for i, c in enumerate(cfg.classes)}
    def key(k):
        sid, exam = k
        st = ds.students[sid]
        return (cls_order.get(st.cls, 9), cfg.exam_order(st.cls, exam), exam, pos[sid])
    return sorted(res.exam_results, key=key)


def _in(st, cls, section):
    return st.cls == cls and (not section or section == "All" or st.section == section)


def dashboard(res, cls, exam, section="All"):
    ds, cfg = res.ds, res.cfg
    ers = [res.exam_results[k] for k in matrix_order(res)
           if k[1] == exam and _in(ds.students[k[0]], cls, section)]
    counted = [er for er in ers if er.overall is not None]
    out = {"cls": cls, "exam": exam, "section": section, "students": len(counted)}
    out["average"] = sum((er.overall for er in counted), Decimal(0)) / len(counted) if counted else None
    out["highest"] = max((er.overall for er in counted), default=None)
    out["topper"] = ""
    if out["highest"] is not None:
        top = next(er for er in counted if er.overall == out["highest"])
        out["topper"] = ds.students[top.sid].name
        out["topper_sid"] = top.sid
    p = sum(1 for er in ers if er.result == "Pass")
    n = sum(1 for er in ers if er.result == "Not passed")
    out["pass_rate"] = Decimal(p) / Decimal(p + n) * 100 if p + n else None
    out["passed"], out["not_passed"] = p, n
    rows = [r for r in res.rows if r.exam == exam and _in(ds.students[r.sid], cls, section)]
    subs = all_subjects(res)
    by_sub = []
    for s in subs:
        ok = [r for r in rows if r.subject == s and r.status == STATUS_OK]
        by_sub.append((s, sum((r.pct for r in ok), Decimal(0)) / len(ok) if ok else None))
    out["by_subject"] = by_sub
    out["labels"] = [(l, sum(1 for r in rows if r.label == l)) for l in LABELS]
    bins = cfg.rules["score_bins"]
    dist = []
    for i in range(len(bins) - 1):
        lo, hi = Decimal(bins[i]), Decimal(bins[i + 1])
        last = i == len(bins) - 2
        dist.append((f"{bins[i]}-{bins[i + 1]}", sum(1 for er in counted if er.overall >= lo and
                                                    (er.overall <= hi if last else er.overall < hi))))
    out["distribution"] = dist
    secs = all_sections(res)
    by_sec = []
    for sec in secs:
        cs = [er for er in res.exam_results.values() if er.exam == exam and er.overall is not None
              and ds.students[er.sid].cls == cls and ds.students[er.sid].section == sec]
        by_sec.append((sec, sum((er.overall for er in cs), Decimal(0)) / len(cs) if cs else None))
    out["by_section"] = by_sec
    return out


def all_subjects(res):
    present = {r.subject for r in res.rows}
    return res.cfg.order_subjects(present)


def all_sections(res):
    return sorted({s.section for s in res.ds.students.values() if s.section})


def all_exams(res):
    """Exam codes present, in a sensible order (class order of XI then XII)."""
    cfg = res.cfg
    present = {k[1] for k in res.exam_results}
    out = []
    for c in cfg.classes:
        for e in cfg.class_exams(c):
            if e in present and e not in out:
                out.append(e)
    return out + sorted(present - set(out))


def subject_analysis(res, cls, exam):
    cfg = res.cfg
    rows = []
    for s in all_subjects(res):
        st = res.subject_stats.get((cls, exam, s))
        rows.append({"subject": s, "name": cfg.subject_name(s), **(st or {"count": 0})})
    return rows


def subject_trend(res, cls, subject):
    out = []
    for e in res.ds.exams_for(cls):
        st = res.subject_stats.get((cls, e, subject))
        out.append((e, st["avg"] if st else None, st["pass_pct"] if st else None))
    return out


def report_card(res, sid, exam):
    ds, cfg = res.ds, res.cfg
    st = ds.students[sid]
    er = res.exam_results.get((sid, exam))
    rows = []
    if er:
        for r in er.rows:
            rows.append({
                "subject": r.subject, "name": cfg.subject_name(r.subject),
                "theory": r.th if r.th is not None else (r.th_raw if r.th_kind != "blank" else ""),
                "practical": (r.pr if r.pr is not None else (r.pr_raw if r.pr_kind != "blank" else "")) if r.pr_max else None,
                "obtained": r.obtained, "max": r.max, "pct": r.pct, "class_avg": r.class_avg, "grade": r.grade,
                "status": r.status, "label": r.label, "gentle": GENTLE.get(r.label, r.label), "reason": r.reason,
                "passed": r.passed, "th_max": r.th_max, "pr_max": r.pr_max, "pr_label": r.pr_label or "",
                "written_only": bool(r.written_only),
                "parts": [{"key": k, "label": cfg.part_label(k), "value": v, "max": m} for k, (v, m) in (r.parts or {}).items()],
            })
    pg = progress(res, sid)
    return {
        "student": st.to_dict(), "exam": exam, "exam_name": cfg.exam_name(exam), "rows": rows,
        "obtained": er.obtained if er else None, "max": er.max if er else None,
        "overall": er.overall if er else None, "grade": cfg.grade(er.overall) if er and er.overall is not None else "",
        "result": er.result if er else "", "rank": er.rank if er else None, "section_rank": er.section_rank if er else None,
        "class_size": sum(1 for o in res.exam_results.values() if o.exam == exam and o.overall is not None
                          and ds.students[o.sid].cls == st.cls),
        "remarks": remarks(res, sid, exam), "trend": pg["series"],
        "streams": cfg.has_streams(st.cls),
        "th_head": "Theory" if cfg.has_streams(st.cls) else "Written",
        "pr_head": _pr_head([x["pr_label"] for x in rows if x["pr_max"]]),
    }


def _pr_head(labels):
    labels = set(labels)
    if not labels:
        return "Practical"
    if labels == {"Internal"}:
        return "Internal"
    if labels == {"Practical"}:
        return "Practical"
    return "Int / Prac"


def progress_rows(res, cls):
    ds = res.ds
    out = []
    for st in ds.ordered_students():
        if st.cls != cls:
            continue
        pg = progress(res, st.sid)
        latest_res = ""
        for e, v in pg["series"]:
            er = res.exam_results.get((st.sid, e))
            if er and er.result:
                latest_res = er.result
        out.append({"sid": st.sid, "name": st.name, "section": st.section, "series": pg["series"],
                    "deltas": pg["deltas"], "latest_change": pg["latest_change"][2] if pg["latest_change"] else None,
                    "dropped_twice": pg["dropped_twice"], "latest_result": latest_res,
                    "watch": pg["dropped_twice"] or latest_res == "Not passed"})
    return out


def student_label(st):
    sec = f"-{st.section}" if st.section and st.section != "-" else ""
    roll = f", Roll {st.roll}" if st.roll else ""
    return f"{st.name} ({st.cls}{sec}{roll})"


def student_labels(ds):
    """Unique dropdown labels for every student (ID added if two would look the same)."""
    labels = {}
    seen = {}
    for st in ds.ordered_students():
        lab = student_label(st)
        seen[lab] = seen.get(lab, 0) + 1
    for st in ds.ordered_students():
        lab = student_label(st)
        labels[st.sid] = lab if seen[lab] == 1 else f"{lab} [{st.sid}]"
    return labels


def to_json(obj):
    """Decimals -> floats (2 dp) for the website."""
    if isinstance(obj, Decimal):
        return float(round(obj, 4))
    if isinstance(obj, dict):
        return {k: to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    return obj
