"""All the arithmetic: totals, percentages, pass checks, averages, ranks and the
strong / weak / needs-attention labels.

Every rule here is written to give exactly the same answer as the Excel formulas
the workbook uses (excel/school.py). Comparisons are made on values rounded to
6 decimals in both places, so borderline cases (exactly 5 points, exactly 33%)
never come out differently on the website and in Excel."""
from decimal import Decimal, getcontext

from .textutil import r6, fmt_num

getcontext().prec = 34
HUNDRED = Decimal(100)

STATUS_OK = "OK"


class Row:
    """One subject of one student in one exam (a row of the 'Subject Results' sheet)."""
    __slots__ = ("sid", "exam", "subject", "th", "th_kind", "th_raw", "th_max", "pr", "pr_kind", "pr_raw", "pr_max",
                 "is_total", "status", "obtained", "max", "pct", "th_pct", "pr_pct", "passed", "own_avg", "class_avg",
                 "vs_own", "vs_class", "label", "reason", "grade", "marks")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class ExamResult:
    __slots__ = ("sid", "exam", "rows", "obtained", "max", "overall", "result", "rank", "section_rank",
                 "counted", "n_ok")

    def __init__(self, sid, exam):
        self.sid, self.exam = sid, exam
        self.rows = []
        self.obtained = self.max = None
        self.overall = None
        self.result = ""
        self.rank = self.section_rank = None
        self.counted = False
        self.n_ok = 0


class Results:
    def __init__(self, ds):
        self.ds = ds
        self.cfg = ds.cfg
        self.rows = []                 # all Row objects
        self.exam_results = {}         # (sid, exam) -> ExamResult
        self.class_avg = {}            # (cls, exam, subject) -> Decimal
        self.subject_stats = {}        # (cls, exam, subject) -> dict


def _mean(vals):
    return sum(vals, Decimal(0)) / len(vals) if vals else None


def status_of(th_kind, th_code, pr_kind, pr_code, pr_max, cfg):
    """Same order of checks as the Excel 'Status' formula."""
    has_pr = pr_max and pr_max > 0
    if th_kind == "number" and (not has_pr or pr_kind == "number"):
        return STATUS_OK
    if th_kind == "blank" and (not has_pr or pr_kind == "blank"):
        return cfg.rules.get("blank_means", "AB")
    if th_kind == "leave":
        return th_code
    if has_pr and pr_kind == "leave":
        return pr_code
    if th_kind == "invalid" or (has_pr and pr_kind == "invalid"):
        return "INVALID"
    return "INCOMPLETE"


def status_label(status, cfg):
    if status == "INVALID":
        return "Check marks"
    if status == "INCOMPLETE":
        return "Incomplete"
    return cfg.leave_label(status)


def compute(ds):
    cfg = ds.cfg
    res = Results(ds)
    pass_pct = cfg.d("pass_percent")
    each = bool(cfg.rules.get("pass_each_part", True))
    strong, weak, att = cfg.d("strong_gap"), cfg.d("weak_gap"), cfg.d("attention_class_gap")

    # group records into (sid, exam, subject)
    groups = {}
    for m in ds.marks:
        groups.setdefault((m.sid, m.exam, m.subject), {})[m.component] = m
    order = {s.sid: i for i, s in enumerate(ds.ordered_students())}

    def key(k):
        sid, exam, subject = k
        st = ds.students[sid]
        return (order[sid], cfg.exam_order(st.cls, exam), cfg.subject_order.index(subject)
                if subject in cfg.subject_order else 999)

    for k in sorted(groups, key=key):
        sid, exam, subject = k
        parts = groups[k]
        comps = cfg.components(subject, exam)
        if "total" in parts:
            th_m, pr_m = parts["total"], None
            th_max, pr_max, is_total = cfg.subject_max(subject, exam), Decimal(0), True
        else:
            th_m, pr_m = parts.get("theory"), parts.get("practical")
            th_max, pr_max, is_total = comps.get("theory", Decimal(0)), comps.get("practical", Decimal(0)), False
        th_kind = th_m.kind if th_m else "blank"
        pr_kind = pr_m.kind if pr_m else "blank"
        row = Row(sid=sid, exam=exam, subject=subject,
                  th=th_m.value if th_m and th_m.kind == "number" else None, th_kind=th_kind,
                  th_raw=th_m.raw if th_m else "", th_max=th_max,
                  pr=pr_m.value if pr_m and pr_m.kind == "number" else None, pr_kind=pr_kind,
                  pr_raw=pr_m.raw if pr_m else "", pr_max=pr_max, is_total=is_total,
                  marks=[x for x in (th_m, pr_m) if x])
        row.status = status_of(th_kind, th_m.code if th_m else "", pr_kind, pr_m.code if pr_m else "", pr_max, cfg)
        row.max = th_max + pr_max
        if row.status == STATUS_OK:
            row.obtained = row.th + (row.pr if pr_max else Decimal(0))
            row.pct = row.obtained / row.max * HUNDRED
            row.th_pct = row.th / th_max * HUNDRED
            row.pr_pct = row.pr / pr_max * HUNDRED if pr_max else None
            if each:
                ok = r6(row.th_pct) >= pass_pct and (not pr_max or r6(row.pr_pct) >= pass_pct)
            else:
                ok = r6(row.pct) >= pass_pct
            row.passed = "Yes" if ok else "No"
            row.grade = cfg.grade(r6(row.pct))
        else:
            row.passed = "No" if cfg.counts_as_fail(row.status) else ""
            row.grade = ""
        res.rows.append(row)
        er = res.exam_results.get((sid, exam))
        if er is None:
            er = res.exam_results[(sid, exam)] = ExamResult(sid, exam)
        er.rows.append(row)

    # student's own average per exam, overall %, result
    for er in res.exam_results.values():
        ok = [r for r in er.rows if r.status == STATUS_OK]
        er.n_ok = len(ok)
        own = sum((r.pct for r in ok), Decimal(0)) / len(ok) if ok else None
        for r in er.rows:
            r.own_avg = own if r.status == STATUS_OK else None
        if ok:
            er.obtained = sum((r.obtained for r in ok), Decimal(0))
            er.max = sum((r.max for r in ok), Decimal(0))
            er.overall = r6(er.obtained / er.max * HUNDRED)
            er.counted = True
        if any(r.passed == "No" for r in er.rows):
            er.result = "Not passed"
        elif ok:
            er.result = "Pass"

    # class averages and subject statistics
    buckets = {}
    for r in res.rows:
        cls = ds.students[r.sid].cls
        buckets.setdefault((cls, r.exam, r.subject), []).append(r)
    for k, rows in buckets.items():
        ok = [r for r in rows if r.status == STATUS_OK]
        avg = sum((r.pct for r in ok), Decimal(0)) / len(ok) if ok else None
        res.class_avg[k] = avg
        yes = sum(1 for r in rows if r.passed == "Yes")
        no = sum(1 for r in rows if r.passed == "No")
        res.subject_stats[k] = {
            "count": len(ok), "avg": avg,
            "max": max((r.pct for r in ok), default=None), "min": min((r.pct for r in ok), default=None),
            "pass_pct": Decimal(yes) / Decimal(yes + no) * HUNDRED if (yes + no) else None,
            "yes": yes, "no": no,
            "avg_th": sum((r.th for r in ok), Decimal(0)) / len(ok) if ok else None,
            "avg_pr": _mean([r.pr for r in ok if r.pr is not None]),
            "absent": sum(1 for r in rows if r.status == "AB"),
            "leave": sum(1 for r in rows if r.status not in (STATUS_OK, "AB", "INVALID", "INCOMPLETE")),
        }

    # labels and reasons
    for r in res.rows:
        cls = ds.students[r.sid].cls
        r.class_avg = res.class_avg.get((cls, r.exam, r.subject))
        name = cfg.subject_name(r.subject)
        if r.status != STATUS_OK:
            r.label = status_label(r.status, cfg)
            r.reason = f"{name}: {r.label}"
            continue
        r.vs_own = r.pct - r.own_avg
        r.vs_class = r.pct - r.class_avg
        if r.passed == "No" or r6(r.vs_class) <= -att:
            r.label = "Needs attention"
        elif r6(r.vs_own) >= strong:
            r.label = "Strong"
        elif r6(r.vs_own) <= -weak:
            r.label = "Weak"
        else:
            r.label = "On track"
        r.reason = (f"{name}: " + ("below the pass mark; " if r.passed == "No" else "")
                    + f"{fmt_num(abs(r6(r.vs_own)))} points {'above' if r6(r.vs_own) >= 0 else 'below'} your average and "
                    + f"{fmt_num(abs(r6(r.vs_class)))} {'above' if r6(r.vs_class) >= 0 else 'below'} the class average.")

    # ranks (class and section), on the 6-decimal overall %
    by_ce = {}
    for er in res.exam_results.values():
        if er.overall is None:
            continue
        st = ds.students[er.sid]
        by_ce.setdefault((st.cls, er.exam), []).append(er)
    for (cls, exam), lst in by_ce.items():
        for er in lst:
            er.rank = 1 + sum(1 for o in lst if o.overall > er.overall)
            sec = ds.students[er.sid].section
            er.section_rank = 1 + sum(1 for o in lst if ds.students[o.sid].section == sec and o.overall > er.overall)
    return res


# ---------------------------------------------------------------- progress
def progress(res, sid):
    """Overall % per exam (in the class's exam order) and the changes between them."""
    ds, cfg = res.ds, res.cfg
    st = ds.students[sid]
    exams = ds.exams_for(st.cls)
    series = []
    for e in exams:
        er = res.exam_results.get((sid, e))
        series.append((e, er.overall if er and er.overall is not None else None))
    # change between neighbouring exams (both must have marks) - same as the Progress sheet
    deltas = []
    for (e1, v1), (e2, v2) in zip(series, series[1:]):
        if v1 is not None and v2 is not None:
            deltas.append((e1, e2, v2 - v1))
    gap = cfg.d("drop_alert_gap")
    dropped_twice = any(r6(a[2]) <= -gap and r6(b[2]) <= -gap for a, b in zip(deltas, deltas[1:])
                        if a[1] == b[0])
    return {"series": series, "deltas": deltas, "latest_change": deltas[-1] if deltas else None,
            "dropped_twice": dropped_twice}


def remarks(res, sid, exam):
    """Short, always-true remarks for a report card (fixed wording, no AI)."""
    cfg = res.cfg
    er = res.exam_results.get((sid, exam))
    if not er:
        return []
    out = []
    ok = [r for r in er.rows if r.status == STATUS_OK]
    if ok:
        best = max(ok, key=lambda r: (r6(r.pct), -cfg.subject_order.index(r.subject) if r.subject in cfg.subject_order else 0))
        out.append(f"Best subject: {cfg.subject_name(best.subject)} ({fmt_num(r6(best.pct))}%).")
    good = [cfg.subject_name(r.subject) for r in er.rows if r.label == "Strong"]
    if good:
        out.append("Doing well in: " + ", ".join(good) + ".")
    focus = [r for r in er.rows if r.label in ("Weak", "Needs attention")]
    for r in focus:
        bits = []
        if r.passed == "No":
            bits.append("below the pass mark")
        if r6(r.vs_own) < 0:
            bits.append(f"{fmt_num(abs(r6(r.vs_own)))} points below own average")
        if r6(r.vs_class) < 0:
            bits.append(f"{fmt_num(abs(r6(r.vs_class)))} below the class average")
        out.append(f"Focus area: {cfg.subject_name(r.subject)} ({'; '.join(bits)}).")
    for r in er.rows:
        if r.status not in (STATUS_OK,):
            out.append(f"{cfg.subject_name(r.subject)}: {r.label}.")
    pg = progress(res, sid)
    lc = pg["latest_change"]
    if lc and lc[1] == exam:
        d = lc[2]
        word = "up" if r6(d) > 0 else ("down" if r6(d) < 0 else "no change")
        if word == "no change":
            out.append(f"Overall: same as {cfg.exam_name(lc[0])}.")
        else:
            out.append(f"Overall: {word} {fmt_num(abs(r6(d)))} points since {cfg.exam_name(lc[0])}.")
    return out
