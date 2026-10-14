"""Second, independent check of the arithmetic.

calc.py works with Decimals. This file works everything out again a different
way - straight from the mark records, with exact fractions - and compares. If
the two ever disagree, the workbook is NOT produced and the problem is shown.
(This is the "computed twice" safety net.)"""
from fractions import Fraction
from decimal import Decimal, ROUND_HALF_UP


class VerificationError(Exception):
    pass


def _r6(fr):
    """Round a fraction to 6 decimals, half away from zero."""
    d = Decimal(fr.numerator) / Decimal(fr.denominator)
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def check(ds, res):
    cfg = ds.cfg
    problems = []
    blank_means = cfg.rules.get("blank_means", "AB")
    pass_pct = Fraction(str(cfg.rules["pass_percent"]))
    each = bool(cfg.rules.get("pass_each_part", True))

    # rebuild per (student, exam, subject) without using calc.py
    parts = {}
    for m in ds.marks:
        parts.setdefault((m.sid, m.exam, m.subject), []).append(m)
    pct_of = {}
    passed_of = {}
    for (sid, exam, subject), ms in parts.items():
        by = {m.component: m for m in ms}
        total = by.get("total")
        maxes = cfg.components(subject, exam)
        if total is not None:
            pieces = [(total, Fraction(str(cfg.subject_max(subject, exam))))]
        else:
            pieces = []
            for comp, mx in maxes.items():
                pieces.append((by.get(comp), Fraction(str(mx))))
        kinds = [p[0].kind if p[0] is not None else "blank" for p in pieces]
        if all(k == "number" for k in kinds):
            got = sum(Fraction(str(p[0].value)) for p in pieces)
            mx = sum(p[1] for p in pieces)
            pct_of[(sid, exam, subject)] = got / mx * 100
            if each:
                ok = all(_r6(Fraction(str(p[0].value)) / p[1] * 100) >= _r6(pass_pct) for p in pieces)
            else:
                ok = _r6(got / mx * 100) >= _r6(pass_pct)
            passed_of[(sid, exam, subject)] = "Yes" if ok else "No"
        else:
            if all(k == "blank" for k in kinds):
                code = blank_means
            else:
                code = next((p[0].code for p in pieces if p[0] is not None and p[0].kind == "leave"), None)
                if code is None:
                    code = "INVALID" if "invalid" in kinds else "INCOMPLETE"
            passed_of[(sid, exam, subject)] = "No" if cfg.counts_as_fail(code) else ""

    # compare row by row
    seen = set()
    for r in res.rows:
        k = (r.sid, r.exam, r.subject)
        seen.add(k)
        a = pct_of.get(k)
        if (a is None) != (r.pct is None):
            problems.append(f"{k}: percentage present in one calculation only")
        elif a is not None and abs(Fraction(str(r.pct)) - a) > Fraction(1, 10 ** 20):
            problems.append(f"{k}: percentage {r.pct} vs {float(a)}")
        if passed_of.get(k) != r.passed:
            problems.append(f"{k}: pass check {r.passed!r} vs {passed_of.get(k)!r}")
    if seen != set(parts):
        problems.append(f"{len(set(parts) - seen)} subject results missing, {len(seen - set(parts))} extra")

    # overall % per student per exam
    sums = {}
    for (sid, exam, subject), p in pct_of.items():
        ms = parts[(sid, exam, subject)]
        by = {m.component: m for m in ms}
        if "total" in by:
            got, mx = Fraction(str(by["total"].value)), Fraction(str(cfg.subject_max(subject, exam)))
        else:
            got = sum(Fraction(str(by[c].value)) for c in cfg.components(subject, exam))
            mx = Fraction(str(cfg.subject_max(subject, exam)))
        s = sums.setdefault((sid, exam), [Fraction(0), Fraction(0)])
        s[0] += got
        s[1] += mx
    for key, er in res.exam_results.items():
        if key in sums:
            want = _r6(sums[key][0] / sums[key][1] * 100)
            if er.overall != want:
                problems.append(f"{key}: overall {er.overall} vs {want}")
        elif er.overall is not None:
            problems.append(f"{key}: overall present in one calculation only")

    # class averages
    groups = {}
    for (sid, exam, subject), p in pct_of.items():
        groups.setdefault((ds.students[sid].cls, exam, subject), []).append(p)
    for k, lst in groups.items():
        want = sum(lst) / len(lst)
        got = res.class_avg.get(k)
        if got is None or abs(Fraction(str(got)) - want) > Fraction(1, 10 ** 20):
            problems.append(f"{k}: class average {got} vs {float(want)}")

    # every record used exactly once
    used = sum(len(r.marks) for r in res.rows)
    if used != len(ds.marks):
        problems.append(f"{len(ds.marks)} mark records but {used} used")

    if problems:
        raise VerificationError("The two independent calculations disagree:\n" + "\n".join(problems[:20]))
    return {"rows": len(res.rows), "records": len(ds.marks), "exam_results": len(res.exam_results), "ok": True}
