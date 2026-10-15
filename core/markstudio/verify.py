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


class _Piece:
    __slots__ = ("kind", "value", "code", "max", "derived")

    def __init__(self, kind, value, code, mx, derived=False):
        self.kind = kind
        self.value = Fraction(str(value)) if kind == "number" and value is not None else None
        self.code = code or ""
        self.max = Fraction(str(mx))
        self.derived = derived


def _second_half(by, cfg, cls, subject, exam, pt_marks):
    """The practical / internal half, worked out on its own: a typed total, or the sum of its parts
    (the PT part from the periodic test: PT / PT max x part max; absent = 0). None = not given and
    optional (only the written paper counts)."""
    mx = cfg.components(cls, subject, exam)["practical"]
    if "practical" in by:
        m = by["practical"]
        return _Piece(m.kind, m.value, m.code, mx)
    subs = cfg.subparts(cls, subject, exam)
    if not subs or not any(k in by for k, _ in subs):
        return None if cfg.second_optional(cls, subject, exam) else _Piece("blank", None, "", mx)
    pieces = []
    for k, pmx in subs:
        if k == "i_pt" and k not in by:
            pt = {m.component: m for m in pt_marks}
            src = pt.get("theory") or pt.get("total")
            pt_exam = cfg.pt_source(exam)
            full = None
            if src is not None and pt_exam:
                full = (cfg.subject_max(cls, subject, pt_exam) if src.component == "total"
                        else cfg.components(cls, subject, pt_exam).get("theory"))
            if src is None or not full:
                pieces.append(_Piece("blank", None, "", pmx, True))
            elif src.kind == "number":
                p = _Piece("number", 0, "", pmx, True)
                p.value = Fraction(str(src.value)) / Fraction(str(full)) * Fraction(str(pmx))
                pieces.append(p)
            elif src.kind in ("blank", "leave"):
                pieces.append(_Piece("number", 0, "", pmx, True))
            else:
                pieces.append(_Piece("invalid", None, "", pmx, True))
            continue
        m = by.get(k)
        pieces.append(_Piece(m.kind, m.value, m.code, pmx) if m else _Piece("blank", None, "", pmx))
    if all(p.kind == "number" for p in pieces):
        out = _Piece("number", 0, "", mx)
        out.value = sum(p.value for p in pieces)
        return out
    if all(p.kind == "blank" for p in pieces if not p.derived):
        return _Piece("blank", None, "", mx)
    lv = next((p for p in pieces if p.kind == "leave"), None)
    if lv:
        return _Piece("leave", None, lv.code, mx)
    if any(p.kind == "invalid" for p in pieces):
        return _Piece("invalid", None, "", mx)
    return _Piece("partial", None, "", mx)


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
    got_of = {}
    for (sid, exam, subject), ms in parts.items():
        cls = ds.students[sid].cls
        by = {m.component: m for m in ms}
        total = by.get("total")
        maxes = cfg.components(cls, subject, exam)
        if total is not None:
            pieces = [_Piece(total.kind, total.value, total.code, cfg.subject_max(cls, subject, exam))]
        else:
            th = by.get("theory")
            pieces = [_Piece(th.kind, th.value, th.code, maxes.get("theory", 0)) if th
                      else _Piece("blank", None, "", maxes.get("theory", 0))]
            if "practical" in maxes:
                second = _second_half(by, cfg, cls, subject, exam, parts.get((sid, cfg.pt_source(exam), subject), []))
                if second is not None:
                    pieces.append(second)
        kinds = [p.kind for p in pieces]
        if all(k == "number" for k in kinds):
            got = sum(p.value for p in pieces)
            mx = sum(p.max for p in pieces)
            pct_of[(sid, exam, subject)] = got / mx * 100
            got_of[(sid, exam, subject)] = (got, mx)
            if each:
                ok = all(_r6(p.value / p.max * 100) >= _r6(pass_pct) for p in pieces)
            else:
                ok = _r6(got / mx * 100) >= _r6(pass_pct)
            passed_of[(sid, exam, subject)] = "Yes" if ok else "No"
        else:
            if all(k == "blank" for k in kinds):
                code = blank_means
            else:
                code = next((p.code for p in pieces if p.kind == "leave"), None)
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
    for key3, (got, mx) in got_of.items():
        s = sums.setdefault((key3[0], key3[1]), [Fraction(0), Fraction(0)])
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
