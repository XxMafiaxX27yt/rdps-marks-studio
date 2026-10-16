"""Teacher analysis: how the students a teacher teaches do in that teacher's subject.

A teacher is entered once (name, subject, classes like "XI-A, XII-A"), on the website
or in a 'Teachers' sheet of any uploaded file. Everything here is worked out from
the same subject results as the rest of the tool, so the numbers always agree.

The fair check: a weak section scores low in every subject, so a raw average would
blame the teacher for the section. "vs own average" compares each student's mark in
this subject with that same student's average over all their subjects in the same
exam - only the part that belongs to this subject is left."""
import re
from decimal import Decimal

from .calc import STATUS_OK
from .textutil import clean, norm, r6
from .layout import class_token_match, to_class, CLASS_TOKEN

TEACHER_SHEETS = {"teachers", "teacher", "teacher list", "teachers list", "staff", "staff list", "faculty",
                  "subject teachers", "teacher details"}
HUNDRED = Decimal(100)


# ---------------------------------------------------------------- reading teachers
def parse_classes(text, cfg=None):
    """'XI-A, XII A & B; 9C' -> [('XI','A'), ('XII','A'), ('XII','B'), ('IX','C')]; 'XI' -> [('XI','')]."""
    out = []
    last = None
    for part in re.split(r"[,;&+/]| and |\n", clean(text).lower()):
        p = part.strip()
        if not p:
            continue
        if re.fullmatch(r"[a-h]", p) and last:
            item = (last, p.upper())
        else:
            m = class_token_match(norm(p))
            if not m:
                mm = re.search(r"\b(?:class|std|grade)?\s*" + CLASS_TOKEN + r"(?:st|nd|rd|th)?\s*[- ]?\s*([a-h])?\b", norm(p))
                m = (to_class(mm.group(1)), (mm.group(2) or "").upper()) if mm and to_class(mm.group(1)) else None
            if not m:
                continue
            item = m
            last = m[0]
        if item not in out:
            out.append(item)
    return out


def class_label(cls, sec):
    return f"{cls}-{sec}" if sec else cls


def normalise(teachers, cfg, vocab=None):
    """Teachers as typed (dicts with name, subject (code or words), classes (text or list)) -> clean list."""
    from .layout import Vocab
    vocab = vocab or Vocab(cfg)
    out = []
    for i, t in enumerate(teachers or []):
        name = clean(t.get("name", ""))
        if not name:
            continue
        subj = t.get("subject", "")
        code = subj if subj in cfg.subjects else (vocab.find_subject(subj) or vocab.find_subject_fuzzy(subj) or "")
        cl = t.get("classes", "")
        pairs = parse_classes(cl if isinstance(cl, str) else ", ".join(cl), cfg)
        out.append({"id": t.get("id") or f"T{i + 1}", "name": name, "subject": code,
                    "subject_text": subj if not code else cfg.subject_name(code),
                    "classes": [class_label(c, s) for c, s in pairs], "pairs": pairs,
                    "source": t.get("source", "typed")})
    return out


def read_sheet(rows, cfg, vocab, file_name="", sheet=""):
    """A 'Teachers' sheet: columns like Name | Subject | Classes. -> list of teacher dicts."""
    head_at, cols = None, {}
    for r, row in enumerate(rows[:15]):
        found = {}
        for c, v in enumerate(row):
            n = norm(v)
            if not n:
                continue
            if "subject" in n or n in ("sub",):
                found.setdefault("subject", c)
            elif "class" in n or "section" in n or n in ("std", "classes taught", "sections"):
                found.setdefault("classes", c)
            elif "name" in n or "teacher" in n:
                found.setdefault("name", c)
        if "name" in found and "subject" in found:
            head_at, cols = r, found
            break
    if head_at is None:
        return []
    out = []
    for r in range(head_at + 1, len(rows)):
        row = rows[r]
        get = lambda k: clean(row[cols[k]]) if k in cols and cols[k] < len(row) else ""
        if not get("name"):
            continue
        out.append({"name": get("name"), "subject": get("subject"), "classes": get("classes"),
                    "source": f"{file_name} › {sheet} row {r + 1}"})
    return out


# ---------------------------------------------------------------- analysis
def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals, Decimal(0)) / len(vals) if vals else None


def _stats(rows):
    ok = [r for r in rows if r.status == STATUS_OK]
    yes = sum(1 for r in rows if r.passed == "Yes")
    no = sum(1 for r in rows if r.passed == "No")
    grades = {}
    for r in ok:
        grades[r.grade] = grades.get(r.grade, 0) + 1
    return {"n": len(ok), "avg": _mean([r.pct for r in ok]),
            "pass_pct": Decimal(yes) * HUNDRED / Decimal(yes + no) if yes + no else None,
            "not_passed": no, "vs_own": _mean([r.vs_own for r in ok]),
            "grades": grades, "top": max((r.pct for r in ok), default=None)}


# ---------------------------------------------------------------- the fair check
STRUGGLING = Decimal(40)     # a student whose OTHER subjects average below this is struggling everywhere
MIN_STUDENTS = 8


def residuals(res):
    """For every (student, exam, subject) with marks: how far the mark is from what that student usually gets
    in their other subjects, after taking away how hard the subject is for the whole class.
    -> {(sid, exam, subject): (residual, other_avg)}"""
    ds = res.ds
    other = {}
    for er in res.exam_results.values():
        ok = [r for r in er.rows if r.status == STATUS_OK]
        tot = sum((r.pct for r in ok), Decimal(0))
        for r in ok:
            if len(ok) > 1:
                other[(r.sid, r.exam, r.subject)] = (r.pct, (tot - r.pct) / (len(ok) - 1))
    gaps = {}
    for (sid, exam, subj), (pct, oth) in other.items():
        gaps.setdefault((ds.students[sid].cls, exam, subj), []).append(pct - oth)
    offset = {k: sum(v, Decimal(0)) / len(v) for k, v in gaps.items()}
    out = {}
    for (sid, exam, subj), (pct, oth) in other.items():
        out[(sid, exam, subj)] = (pct - oth - offset[(ds.students[sid].cls, exam, subj)], oth)
    return out


def fair_check(rows, resid):
    """The teacher's effect = average of their students' residuals (students struggling in every subject are
    left out), with a 95% range. Clear only when the whole range is above / below zero."""
    vals, left_out = [], 0
    for r in rows:
        k = (r.sid, r.exam, r.subject)
        if k not in resid:
            continue
        v, oth = resid[k]
        if oth < STRUGGLING:
            left_out += 1
            continue
        vals.append(float(v))
    n = len(vals)
    if n < MIN_STUDENTS:
        return {"n": n, "left_out": left_out, "effect": None, "low": None, "high": None, "verdict": "Not enough data"}
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5
    se = sd / n ** 0.5
    lo, hi = m - 1.96 * se, m + 1.96 * se
    verdict = "Clear positive impact" if lo > 0 else ("Worth a conversation" if hi < 0 else "No clear difference")
    return {"n": n, "left_out": left_out, "effect": Decimal(str(round(m, 4))), "low": Decimal(str(round(lo, 4))),
            "high": Decimal(str(round(hi, 4))), "verdict": verdict}


def analyse(res, teachers):
    """-> {'cards': [...], 'comparison': [{subject, name, rows: [...]}], 'exams': ...}"""
    ds, cfg = res.ds, res.cfg
    resid = residuals(res)
    by_key = {}
    for r in res.rows:
        st = ds.students[r.sid]
        by_key.setdefault((st.cls, st.section, r.subject, r.exam), []).append(r)
    cards = []
    for t in teachers:
        subj = t["subject"]
        secs = []
        for cls, sec in t["pairs"]:
            sections = [sec] if sec else ds.sections_for(cls) or [""]
            for s in sections:
                exams = [e for e in ds.exams_for(cls) if by_key.get((cls, s, subj, e))]
                if not exams:
                    secs.append({"cls": cls, "section": s, "label": class_label(cls, s), "missing": True,
                                 "by_exam": [], "students": 0})
                    continue
                by_exam = []
                for e in exams:
                    rows = by_key[(cls, s, subj, e)]
                    stt = _stats(rows)
                    stt.update(exam=e, name=cfg.exam_name(e), class_avg=res.class_avg.get((cls, e, subj)))
                    stt["vs_class"] = (stt["avg"] - stt["class_avg"]) if stt["avg"] is not None and stt["class_avg"] is not None else None
                    by_exam.append(stt)
                first, last = by_exam[0], by_exam[-1]
                change = (last["avg"] - first["avg"]) if len(by_exam) > 1 and first["avg"] is not None and last["avg"] is not None else None
                students = len({r.sid for e in exams for r in by_key[(cls, s, subj, e)]})
                internals = _internals(cfg, cls, subj, [r for e in exams for r in by_key[(cls, s, subj, e)]])
                secs.append({"cls": cls, "section": s, "label": class_label(cls, s), "missing": False,
                             "students": students, "by_exam": by_exam, "latest": last, "first": first,
                             "change": change, "internals": internals})
        have = [x for x in secs if not x["missing"]]
        latest_rows = []
        for x in have:
            latest_rows += by_key[(x["cls"], x["section"], subj, x["latest"]["exam"])]
        overall = _stats(latest_rows) if latest_rows else None
        changes = [x["change"] for x in have if x["change"] is not None]
        fair = fair_check(latest_rows, resid)
        # the fair check compares with the OTHER sections of the same subject - if this teacher teaches every one
        # of them, there is nothing to compare with
        alone = bool(have) and all(
            {x["section"] for x in have if x["cls"] == c} >= {st.section for st in ds.students.values()
                                                              if st.cls == c and subj in st.subjects}
            for c in {x["cls"] for x in have})
        if alone and fair["effect"] is not None:
            fair.update(effect=None, low=None, high=None, verdict="Only teacher of this subject")
        # growth: did the students move up compared with their other subjects from the first to the latest exam?
        first_rows = []
        for x in have:
            if len(x["by_exam"]) > 1:
                first_rows += by_key[(x["cls"], x["section"], subj, x["first"]["exam"])]
        g0, g1 = fair_check(first_rows, resid), fair if first_rows else None
        growth = (g1["effect"] - g0["effect"]) if g1 and g0["effect"] is not None and g1["effect"] is not None else None
        # the weakest third of the class (by their other subjects): did they do better or worse than expected?
        weak = []
        for r in latest_rows:
            k = (r.sid, r.exam, r.subject)
            if k in resid and resid[k][1] >= STRUGGLING:
                weak.append((resid[k][1], resid[k][0]))
        weak.sort()
        third = weak[:max(1, len(weak) // 3)] if len(weak) >= 6 else []
        fair["weakest_third"] = _mean([v for _, v in third]) if third else None
        fair["growth"] = growth
        card = {"id": t["id"], "name": t["name"], "subject": subj, "subject_name": cfg.subject_name(subj) if subj else t.get("subject_text", ""),
                "classes": t["classes"], "sections": secs, "overall": overall,
                "change": _mean(changes), "students": sum(x["students"] for x in have),
                "source": t.get("source", ""), "fair": fair}
        card["notes"] = _notes(card, cfg)
        cards.append(card)
    # comparison table: every teacher of the same subject side by side
    comp = []
    for subj in cfg.order_subjects({c["subject"] for c in cards if c["subject"]}):
        rows = []
        for c in cards:
            if c["subject"] != subj or not c["overall"]:
                continue
            o = c["overall"]
            rows.append({"id": c["id"], "name": c["name"], "classes": ", ".join(c["classes"]), "students": c["students"],
                         "students_latest": o["n"],
                         "avg": o["avg"], "pass_pct": o["pass_pct"], "vs_own": o["vs_own"], "not_passed": o["not_passed"],
                         "change": c["change"], "fair": c["fair"]})
        rows.sort(key=lambda x: -(x["avg"] if x["avg"] is not None else Decimal(-1)))
        comp.append({"subject": subj, "name": cfg.subject_name(subj), "rows": rows})
    return {"cards": cards, "comparison": comp}


def _internals(cfg, cls, subj, rows):
    """Average % in each part of the internal assessment (only when the school gave the parts)."""
    sums = {}
    for r in rows:
        for key, (val, mx) in (r.parts or {}).items():
            if val is None or not mx:
                continue
            d = sums.setdefault(key, [])
            d.append(val / mx * HUNDRED)
    if not sums:
        return []
    order = [k for k, _ in cfg.subparts(cls, subj, next((r.exam for r in rows if r.parts), "HY"))] or sorted(sums)
    return [{"key": k, "label": cfg.part_label(k), "avg": _mean(sums[k]), "n": len(sums[k])} for k in order if k in sums]


def _f(d):
    return f"{r6(d):.1f}".rstrip("0").rstrip(".") if d is not None else "-"


def _notes(card, cfg):
    """Plain sentences - always true, never a judgement of the person."""
    out = []
    have = [x for x in card["sections"] if not x["missing"]]
    for x in card["sections"]:
        if x["missing"]:
            out.append(f"No {card['subject_name']} marks for {x['label']} in the uploaded files.")
    if not have:
        return out
    fx = card.get("fair") or {}
    if fx.get("verdict") == "Only teacher of this subject":
        out.append("Fair check: this teacher teaches every section of the subject in these classes, so there is no other "
                   "section to compare with. Look at the change across exams and the weakest students instead.")
    if fx.get("verdict") == "Not enough data":
        out.append(f"Fair check: not enough students yet ({fx['n']}) to say anything about the teaching.")
    elif fx.get("effect") is not None:
        e, lo, hi = fx["effect"], fx["low"], fx["high"]
        out.append(f"Fair check: {fx['verdict']}. Students score {_f(abs(e))} points {'above' if e >= 0 else 'below'} what they "
                   f"usually get in their other subjects (likely range {_f(lo)} to {_f(hi)}), compared with the same subject "
                   f"in the other sections.")
        if fx.get("left_out"):
            out.append(f"{fx['left_out']} student{'s' if fx['left_out'] != 1 else ''} who are low in every subject "
                       f"{'are' if fx['left_out'] != 1 else 'is'} left out of the fair check - not the subject teacher's alone.")
        if fx.get("weakest_third") is not None:
            w = fx["weakest_third"]
            out.append(f"Weakest third of the students: {_f(abs(w))} points {'above' if w >= 0 else 'below'} expected.")
        if fx.get("growth") is not None and abs(fx["growth"]) >= 1:
            out.append(f"Since the first exam the students moved {'up' if fx['growth'] > 0 else 'down'} "
                       f"{_f(abs(fx['growth']))} points compared with their other subjects.")
    o = card["overall"]
    if o and o["avg"] is not None:
        out.append(f"{card['subject_name']} average in the latest exam: {_f(o['avg'])}% over {o['n']} students"
                   + (f"; {o['not_passed']} below the pass mark." if o["not_passed"] else "; everyone passed."))
    if o and o["vs_own"] is not None:
        v = r6(o["vs_own"])
        if abs(v) < 1:
            out.append(f"Students do about as well in {card['subject_name']} as in their other subjects.")
        else:
            out.append(f"Students score {_f(abs(v))} points {'above' if v > 0 else 'below'} their own average in "
                       f"{card['subject_name']} (the fair check - it does not depend on how strong the section is).")
    for x in have:
        if x["change"] is not None and abs(r6(x["change"])) >= 1:
            out.append(f"{x['label']}: {'up' if x['change'] > 0 else 'down'} {_f(abs(x['change']))} points from "
                       f"{x['first']['name']} to {x['latest']['name']}.")
        vc = x["latest"].get("vs_class")
        if vc is not None and abs(r6(vc)) >= 1 and len(have) + 1 > 1:
            out.append(f"{x['label']} is {_f(abs(vc))} points {'above' if vc > 0 else 'below'} the Class {x['cls']} "
                       f"{card['subject_name']} average in {x['latest']['name']}.")
    return out


# ---------------------------------------------------------------- teachers on BOARD results
def analyse_board(an, teachers, cfg, ds=None):
    """Teacher cards for a CBSE gazette. The gazette has no sections, so a subject taught by two teachers is shown
    for both together - unless school marks with Board Roll Nos say which section each student is in.
    The check: each student's mark in the subject minus that student's average in their other subjects."""
    gcls = an["meta"].get("cls") or "XII"
    code_map = {k: v for k, v in cfg.rules.get("board", {}).get("school_code_map", {}).items() if not k.startswith("_")}
    section_of = {}
    if ds is not None:
        for st in ds.students.values():
            if st.board_roll and st.cls == gcls:
                section_of[st.board_roll] = st.section
    def school_code(c):
        if gcls == "X" and c == "241":
            return "041"                     # Class X Maths Basic is taught as the school's Maths
        return code_map.get(c, c)
    cards, untaught = [], []
    lowp = Decimal(str(cfg.rules.get("low_percent", 50)))
    for s in an["subjects"]:
        code = s["code"]
        sc = school_code(code)
        teach = [t for t in teachers if t["subject"] == sc and any(c == gcls for c, _ in t["pairs"])]
        rows = []
        for r in an["rows"]:
            x = next((y for y in r["s"].subjects if y["code"] == code and y["marks"] is not None), None)
            if x is None:
                continue
            others = [y["marks"] for y in r["s"].subjects if y["code"] != code and y["marks"] is not None]
            rows.append({"s": r["s"], "mark": x["marks"], "grade": x["grade"],
                         "other": Decimal(sum(others)) / len(others) if others else None})
        if not teach:
            untaught.append({"code": code, "name": s["name"], "candidates": s["candidates"]})
            continue
        # who taught whom: by section when the school marks tell us, otherwise all together
        groups = []
        by_sec = all(any(sec for _, sec in t["pairs"]) for t in teach) and section_of
        if by_sec:
            for t in teach:
                secs = {sec for c, sec in t["pairs"] if c == gcls}
                mine = [x for x in rows if section_of.get(x["s"].roll) in secs]
                if mine:
                    groups.append(([t], mine, ""))
            covered = {id(x) for g in groups for x in g[1]}
            rest = [x for x in rows if id(x) not in covered]
            if rest:
                groups.append((teach, rest, "Students whose section is not known (no Board Roll No in the school marks)."))
        else:
            note = "" if len(teach) == 1 else ("The gazette does not say which section each student was in, so these "
                                               "teachers are shown together. Upload the school marks with Board Roll Nos "
                                               "and sections to see each teacher separately.")
            groups.append((teach, rows, note))
        for tl, rs, note in groups:
            marks = [Decimal(x["mark"]) for x in rs]
            n = len(rs)
            grades = {}
            for x in rs:
                if x["grade"]:
                    grades[x["grade"]] = grades.get(x["grade"], 0) + 1
            weights = cfg.rules["board"]["pi_weights"]
            graded = sum(grades.values())
            pi = (Decimal(sum(weights.get(g, 0) * k for g, k in grades.items())) * 100 / (Decimal(8) * graded)) if graded else None
            diffs = [float(Decimal(x["mark"]) - x["other"]) for x in rs if x["other"] is not None and x["other"] >= STRUGGLING]
            left_out = sum(1 for x in rs if x["other"] is not None and x["other"] < STRUGGLING)
            fx = {"n": len(diffs), "left_out": left_out, "effect": None, "low": None, "high": None, "verdict": "Not enough data"}
            if len(diffs) >= MIN_STUDENTS:
                m = sum(diffs) / len(diffs)
                sd = (sum((v - m) ** 2 for v in diffs) / (len(diffs) - 1)) ** 0.5
                se = sd / len(diffs) ** 0.5
                lo, hi = m - 1.96 * se, m + 1.96 * se
                fx.update(effect=Decimal(str(round(m, 4))), low=Decimal(str(round(lo, 4))), high=Decimal(str(round(hi, 4))),
                          verdict="Above their other subjects" if lo > 0 else ("Below their other subjects" if hi < 0 else
                                                                               "About the same as their other subjects"))
            weak = sorted((x for x in rs if x["other"] is not None and x["other"] >= STRUGGLING), key=lambda x: x["other"])
            third = weak[:max(1, len(weak) // 3)] if len(weak) >= 6 else []
            fx["weakest_third"] = _mean([Decimal(x["mark"]) - x["other"] for x in third]) if third else None
            card = {"names": [t["name"] for t in tl], "name": " / ".join(t["name"] for t in tl), "subject": code,
                    "subject_name": s["name"], "candidates": n, "avg": sum(marks, Decimal(0)) / n if n else None,
                    "max": max(marks) if marks else None, "min": min(marks) if marks else None,
                    "a1": grades.get("A1", 0), "above90": sum(1 for v in marks if v >= 90),
                    "grade_e": grades.get("E", 0), "below_low": sum(1 for v in marks if v < lowp), "pi": pi,
                    "grades": grades, "fair": fx, "note": note}
            card["notes"] = _board_notes(card)
            cards.append(card)
    # where each subject stands among all the school's subjects (same students, other subjects)
    ranked = sorted((c for c in cards if c["fair"]["effect"] is not None), key=lambda c: -c["fair"]["effect"])
    for i, c in enumerate(ranked):
        c["rank"] = i + 1
        c["of"] = len(ranked)
    return {"cards": cards, "untaught": untaught, "cls": gcls, "year": an["meta"].get("year"),
            "caution": "Board papers differ in difficulty from subject to subject, and here one teacher (or pair) taught the "
                       "whole subject, so this shows the paper and the teaching together. Use it to start a conversation, "
                       "not to decide."}


def _board_notes(c):
    out = []
    fx = c["fair"]
    out.append(f"{c['candidates']} students; average {_f(c['avg'])}, highest {_f(c['max'])}; {c['a1']} A1, "
               f"{c['above90']} scored 90+; PI {_f(c['pi'])}.")
    if c["grade_e"]:
        out.append(f"{c['grade_e']} student{'s' if c['grade_e'] != 1 else ''} got grade E (compartment) in {c['subject_name']}.")
    if fx["effect"] is not None:
        e = fx["effect"]
        out.append(f"Compared with the same students' other subjects: {_f(abs(e))} marks {'above' if e >= 0 else 'below'} "
                   f"(likely range {_f(fx['low'])} to {_f(fx['high'])}) - {fx['verdict'].lower()}.")
        if fx.get("weakest_third") is not None:
            w = fx["weakest_third"]
            out.append(f"Weakest third of the students: {_f(abs(w))} marks {'above' if w >= 0 else 'below'} their other subjects.")
        if fx["left_out"]:
            out.append(f"{fx['left_out']} student{'s' if fx['left_out'] != 1 else ''} low in every subject left out of this check.")
    if c["note"]:
        out.append(c["note"])
    return out
