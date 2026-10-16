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
        # for the charts: each student (other subjects vs this subject), better / same / worse, grades, sections
        pts = []
        for r in latest_rows:
            k = (r.sid, r.exam, r.subject)
            if r.status == STATUS_OK and k in resid:
                pts.append((r.pct, resid[k][1], ds.students[r.sid].name))
        order = [g["grade"] for g in sorted(cfg.rules["grades"], key=lambda g: -g["min"])]
        og = (overall or {}).get("grades", {})
        viz = {"bands": [[g, og.get(g, 0)] for g in order], "bands_are": "grades",
               "split": split_counts([(p_, o_) for p_, o_, _ in pts]),
               "points": [[float(round(o_, 1)), float(round(p_, 1)), nm] for p_, o_, nm in pts],
               "sections": [[x["label"], x["latest"]["n"], x["latest"]["avg"], x["latest"]["vs_own"]] for x in have],
               "exam": cfg.exam_name(have[-1]["latest"]["exam"]) if have else ""}
        card = {"id": t["id"], "name": t["name"], "subject": subj, "subject_name": cfg.subject_name(subj) if subj else t.get("subject_text", ""),
                "classes": t["classes"], "sections": secs, "overall": overall,
                "change": _mean(changes), "students": sum(x["students"] for x in have),
                "source": t.get("source", ""), "fair": fair, "viz": viz}
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
SAME_BAND = 3          # within 3 marks of the student's other subjects = "about the same"


def _ci(vals):
    """mean and 95% range of a list of floats (None when fewer than MIN_STUDENTS)."""
    n = len(vals)
    if n < MIN_STUDENTS:
        return None, None, None
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5
    se = sd / n ** 0.5
    return m, m - 1.96 * se, m + 1.96 * se


def _dec(v):
    return Decimal(str(round(v, 4))) if v is not None else None


def split_counts(pairs):
    """[(mark, other_avg)] -> how many did better / about the same / worse than in their other subjects."""
    out = {"better": 0, "same": 0, "worse": 0}
    for mark, other in pairs:
        d = Decimal(mark) - other
        out["better" if d >= SAME_BAND else "worse" if d <= -SAME_BAND else "same"] += 1
    return out


def analyse_board(an, teachers, cfg, ds=None, class_lists=None):
    """Teacher cards for board results.

    Where is each student? The board file has no sections, so each student is found in the class lists (or the
    school's own marks) by admission no, board roll no or name. Then every teacher gets only their own sections.

    The fair check: all sections wrote the same board paper. For each student: mark in the subject minus their
    average in their other subjects (so a strong or weak section does not count for or against the teacher),
    minus the same figure for all the school's students in that subject (so a hard paper does not either).
    What is left is what the teacher's sections did differently from the other teachers' sections."""
    from .classlist import Placer
    from .board import bands, entry_passed
    gcls = an["meta"].get("cls") or "XII"
    graded = an["meta"].get("graded", True)
    code_map = {k: v for k, v in cfg.rules.get("board", {}).get("school_code_map", {}).items() if not k.startswith("_")}

    def school_code(c):
        if gcls == "X" and c == "241":
            return "041"                     # Class X Maths Basic is taught as the school's Maths
        return code_map.get(c, c)

    # 1. where is each student
    placer = Placer(class_lists, ds) if (class_lists or ds is not None) else None
    where, how_count, check, unplaced, other_cls = {}, {}, [], [], {}
    for i, r in enumerate(an["rows"]):
        b = r["s"]
        if getattr(b, "section", ""):
            where[i] = b.section
            how_count["board file"] = how_count.get("board file", 0) + 1
            continue
        if placer is None:
            continue
        brd = getattr(b, "board_roll", "") or (b.roll if an["meta"].get("kind", "gazette") == "gazette" else "")
        e, how = placer.place(b.name, gcls, getattr(b, "adm_no", ""), brd)
        if e and e["section"]:
            where[i] = e["section"]
            how_count[how] = how_count.get(how, 0) + 1
            if e["cls"] and e["cls"] != gcls:
                other_cls[e["cls"]] = other_cls.get(e["cls"], 0) + 1
            if how == "close name":
                check.append({"name": b.name, "list_name": e["name"], "section": e["section"], "from": e.get("src", "")})
        else:
            unplaced.append({"name": b.name, "why": "the same name is in two sections" if how == "same name twice"
                             else "not found in the class lists"})
    placed = len(where)

    cards, untaught = [], []
    lowp = Decimal(str(cfg.rules.get("low_percent", 50)))
    weights = cfg.rules["board"]["pi_weights"]
    for s in an["subjects"]:
        code = s["code"]
        sc = school_code(code)
        teach = [t for t in teachers if t["subject"] == sc and any(c == gcls for c, _ in t["pairs"])]
        if not teach:
            untaught.append({"code": code, "name": s["name"], "candidates": s["candidates"]})
            continue
        rows = []
        for i, r in enumerate(an["rows"]):
            x = next((y for y in r["s"].subjects if y["code"] == code and y["marks"] is not None), None)
            if x is None:
                continue
            others = [y["marks"] for y in r["s"].subjects if y["code"] != code and y["marks"] is not None]
            rows.append({"i": i, "s": r["s"], "mark": Decimal(x["marks"]), "grade": x["grade"], "x": x,
                         "other": Decimal(sum(Decimal(o) for o in others)) / len(others) if others else None,
                         "sec": where.get(i, "")})
        usable = [x for x in rows if x["other"] is not None and x["other"] >= STRUGGLING]
        offset = sum(float(x["mark"] - x["other"]) for x in usable) / len(usable) if usable else 0.0
        secs_known = any(x["sec"] for x in rows)
        groups = []
        whole = [t for t in teach if any(c == gcls and not sec for c, sec in t["pairs"])]
        if secs_known or len(teach) == 1 or len(whole) == len(teach):
            for t in teach:
                mine_secs = {sec for c, sec in t["pairs"] if c == gcls}
                if "" in mine_secs:
                    groups.append((t, rows, ""))
                elif secs_known:
                    groups.append((t, [x for x in rows if x["sec"] in mine_secs], ""))
                else:
                    groups.append((t, rows, f"The board file does not say which section each student was in, so all "
                                            f"{s['name']} students are counted. Upload the class lists on the Teachers "
                                            f"page to count only {', '.join(gcls + '-' + x for x in sorted(mine_secs))}."))
        else:
            note = ("These teachers are shown together because the board file does not say which section each student "
                    "was in. Upload the class lists on the Teachers page to see each teacher on their own.")
            groups.append((None, rows, note))
        claimed = {}
        for t, mine, _ in groups:
            for x in mine:
                claimed.setdefault(x["i"], []).append(t["name"] if t else "")
        not_linked = [x for x in rows if x["i"] not in claimed]
        for t, mine, note in groups:
            names = [t["name"]] if t else [tt["name"] for tt in teach]
            n = len(mine)
            marks = [x["mark"] for x in mine]
            grades = {}
            for x in mine:
                if x["grade"]:
                    grades[x["grade"]] = grades.get(x["grade"], 0) + 1
            gsum = sum(grades.values())
            pi = (Decimal(sum(weights.get(g, 0) * k for g, k in grades.items())) * 100 / (Decimal(8) * gsum)) if gsum else None
            use = [x for x in mine if x["other"] is not None and x["other"] >= STRUGGLING]
            left_out = sum(1 for x in mine if x["other"] is not None and x["other"] < STRUGGLING)
            raw = [float(x["mark"] - x["other"]) for x in use]
            vm, vlo, vhi = _ci(raw)
            alone = n > 0 and len(mine) == len(rows)
            em, elo, ehi = _ci([v - offset for v in raw]) if not alone else (None, None, None)
            if n == 0:
                verdict = "No students found"
            elif alone and vm is not None:
                verdict = "Only teacher of this subject"
            elif em is None:
                verdict = "Not enough data"
            else:
                verdict = "Clear positive impact" if elo > 0 else ("Worth a conversation" if ehi < 0 else "No clear difference")
            weak = sorted(use, key=lambda x: x["other"])
            third = weak[:max(1, len(weak) // 3)] if len(weak) >= 6 else []
            fx = {"n": len(use), "left_out": left_out, "effect": _dec(em), "low": _dec(elo), "high": _dec(ehi),
                  "vs_own": _dec(vm), "vs_own_low": _dec(vlo), "vs_own_high": _dec(vhi), "verdict": verdict,
                  "weakest_third": _mean([x["mark"] - x["other"] for x in third]) if third else None,
                  "subject_vs_own": _dec(offset) if usable else None}
            by_sec = {}
            for x in mine:
                by_sec.setdefault(x["sec"] or "?", []).append(x)
            sec_rows = []
            for sec in sorted(by_sec):
                xs = by_sec[sec]
                d = [float(x["mark"] - x["other"]) for x in xs if x["other"] is not None and x["other"] >= STRUGGLING]
                sec_rows.append([f"{gcls}-{sec}" if sec != "?" else "Section not known", len(xs),
                                 sum(x["mark"] for x in xs) / len(xs), _dec(sum(d) / len(d)) if d else None])
            failed = sum(1 for x in mine if entry_passed(x["x"], cfg) is False)
            shared = sorted({nm for x in mine for nm in claimed.get(x["i"], []) if nm and t and nm != t["name"]})
            if graded and grades:
                band_list = [[g, grades.get(g, 0)] for g in ("A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E")]
            else:
                band_list = bands(marks)
            card = {"id": t["id"] if t else "", "name": " / ".join(names), "names": names, "subject": code,
                    "school_subject": sc, "subject_name": s["name"],
                    "sections": sorted({f"{gcls}-{sec}" if sec else gcls for c, sec in (t["pairs"] if t else [])
                                        if c == gcls}) if t else [],
                    "candidates": n, "avg": sum(marks, Decimal(0)) / n if n else None,
                    "max": max(marks) if marks else None, "min": min(marks) if marks else None,
                    "a1": grades.get("A1", 0), "above90": sum(1 for v in marks if v >= 90), "grade_e": failed,
                    "below_low": sum(1 for v in marks if v < lowp), "pi": pi, "grades": grades, "fair": fx,
                    "note": note, "shared_with": shared, "not_linked": len(not_linked) if t else 0,
                    "viz": {"bands": band_list, "bands_are": "grades" if graded and grades else "marks",
                            "split": split_counts([(x["mark"], x["other"]) for x in mine if x["other"] is not None]),
                            "points": [[float(round(x["other"], 1)), float(x["mark"]), x["s"].name]
                                       for x in mine if x["other"] is not None],
                            "sections": sec_rows}}
            card["notes"] = _board_notes(card, gcls)
            cards.append(card)
    split = any(c["sections"] for c in cards) and placed > 0
    caution = ("Every section wrote the same board paper. Each teacher's students are compared with what the same "
               "students got in their other subjects, and then with the other teachers of the same subject - so a "
               "strong or weak section, or a hard paper, does not count for or against the teacher. Marks show only "
               "part of teaching: use this to start a conversation, not to decide.") if split else (
               "Board papers differ in difficulty from subject to subject, and without class lists one teacher (or "
               "group) is shown for the whole subject, so this shows the paper and the teaching together. Use it to "
               "start a conversation, not to decide.")
    return {"cards": cards, "untaught": untaught, "cls": gcls, "year": an["meta"].get("year"), "caution": caution,
            "split": split,
            "placement": {"total": len(an["rows"]), "placed": placed, "by": how_count, "check": check,
                          "unplaced": unplaced, "lists": len(class_lists or []), "other_class": other_cls}}


def _board_notes(c, gcls):
    """Plain sentences - always true, never a judgement of the person."""
    out = []
    fx = c["fair"]
    subj = c["subject_name"]
    if not c["candidates"]:
        return [f"No students of {', '.join(c['sections']) or gcls} were found in the {subj} results. "
                f"Check the classes typed for this teacher and the class lists."]
    out.append(f"{c['candidates']} students; average {_f(c['avg'])}, highest {_f(c['max'])}, "
               f"{c['above90']} scored 90 or more" + (f", {c['a1']} got A1." if c["grades"] else "."))
    if c["grade_e"]:
        out.append(f"{c['grade_e']} student{'s' if c['grade_e'] != 1 else ''} did not pass {subj}.")
    sp = c["viz"]["split"]
    tot = sum(sp.values())
    if tot:
        out.append(f"Compared with their own other subjects: {sp['better']} did better in {subj}, {sp['same']} about "
                   f"the same, {sp['worse']} worse.")
    if fx["vs_own"] is not None:
        v = fx["vs_own"]
        out.append(f"On average the students scored {_f(abs(v))} marks {'more' if v >= 0 else 'less'} in {subj} than in "
                   f"their other subjects (all the school's {subj} students: "
                   f"{_f(abs(fx['subject_vs_own'] or 0))} {'more' if (fx['subject_vs_own'] or 0) >= 0 else 'less'}).")
    if fx["verdict"] == "Only teacher of this subject":
        out.append(f"This teacher taught every {subj} student here, so there is no other teacher to compare with - "
                   f"the line above shows the paper and the teaching together.")
    elif fx["effect"] is not None:
        e = fx["effect"]
        out.append(f"Compared with the other {subj} teachers' sections: {_f(abs(e))} marks "
                   f"{'better' if e >= 0 else 'lower'} (likely range {_f(fx['low'])} to {_f(fx['high'])}) - "
                   f"{fx['verdict'].lower()}.")
    elif fx["verdict"] == "Not enough data":
        out.append(f"Only {fx['n']} students could be used for the fair check - not enough to say anything.")
    if fx.get("weakest_third") is not None:
        w = fx["weakest_third"]
        out.append(f"The weakest third of these students (by their other subjects) scored {_f(abs(w))} marks "
                   f"{'more' if w >= 0 else 'less'} in {subj} than in their other subjects.")
    if fx["left_out"]:
        out.append(f"{fx['left_out']} student{'s' if fx['left_out'] != 1 else ''} low in every subject "
                   f"{'are' if fx['left_out'] != 1 else 'is'} left out of the fair check.")
    if c["shared_with"]:
        out.append(f"Shares some sections with {', '.join(c['shared_with'])} - those students count for both.")
    if c["not_linked"]:
        out.append(f"{c['not_linked']} {subj} student{'s are' if c['not_linked'] != 1 else ' is'} in a section no "
                   f"{subj} teacher was entered for, or their section is not known.")
    if c["note"]:
        out.append(c["note"])
    return out
