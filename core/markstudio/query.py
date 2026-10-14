"""Runs a structured question (a "query") on the checked data.

Only the operations listed in OPS exist. A query is plain data (a dict), it is
checked field by field before it runs, and every number in an answer comes from
the calculation results - never from anything else. Each answer also says in
plain words how it was worked out."""
from decimal import Decimal

from .calc import STATUS_OK, progress
from .textutil import fmt_num, r6, norm_name
from . import views

OPS = {"top", "bottom", "list", "count", "average", "highest", "lowest", "hardest", "easiest", "compare",
       "student", "student_subjects", "rank", "pass_rate", "distribution", "improved", "dropped", "absent",
       "help", "board_top", "board_subject", "board_summary", "board_comp", "board_student"}
LABELS = {"Strong", "Weak", "Needs attention", "On track"}


class QueryError(Exception):
    pass


def _p(d):
    return fmt_num(r6(d)) if d is not None else "-"


class Engine:
    def __init__(self, ds=None, res=None, board=None):
        self.ds, self.res, self.board = ds, res, board
        self.cfg = ds.cfg if ds else None

    # ------------------------------------------------------------ checking
    def validate(self, q):
        if not isinstance(q, dict) or q.get("op") not in OPS:
            raise QueryError("Unknown operation")
        if q["op"].startswith("board"):
            if not self.board:
                raise QueryError("No board gazette has been uploaded yet.")
            return
        if self.ds is None:
            raise QueryError("Upload marks first.")
        sc = q.setdefault("scope", {})
        cfg = self.cfg
        if sc.get("cls") and sc["cls"] not in self.ds.classes():
            raise QueryError(f"There is no Class {sc['cls']} in the uploaded marks.")
        if sc.get("section") and sc["section"] not in views.all_sections(self.res):
            raise QueryError(f"There is no Section {sc['section']} in the uploaded marks.")
        if sc.get("exam") and sc["exam"] not in cfg.exams:
            raise QueryError("Unknown exam.")
        if sc.get("gender") and not any(s.gender for s in self.ds.students.values()):
            raise QueryError("The uploaded marks do not say which students are girls or boys, so I can't split by that.")
        for s in [q.get("subject")] + [c.get("subject") for c in q.get("conds", [])] + (q.get("subjects") or []):
            if s and s not in cfg.subjects:
                raise QueryError("Unknown subject.")
        for c in q.get("conds", []):
            if c.get("label") and c["label"] not in LABELS:
                raise QueryError("Unknown label.")
            if c.get("op") and c["op"] not in ("<", "<=", ">", ">="):
                raise QueryError("Unknown comparison.")
        for sid in q.get("students", []):
            if sid not in self.ds.students:
                raise QueryError("Unknown student.")
        n = q.get("n")
        if n is not None and (not isinstance(n, int) or n < 1 or n > 500):
            raise QueryError("Number of students must be 1-500.")

    # ------------------------------------------------------------ helpers
    def exam_for(self, cls, exam=None):
        if exam:
            return exam
        ex = self.ds.exams_for(cls)
        return ex[-1] if ex else None

    def in_scope(self, st, sc):
        if sc.get("cls") and st.cls != sc["cls"]:
            return False
        if sc.get("section") and st.section != sc["section"]:
            return False
        if sc.get("group") and st.group != sc["group"]:
            return False
        if sc.get("gender") and st.gender != sc["gender"]:
            return False
        return True

    def scope_text(self, sc, exam=None):
        bits = []
        if sc.get("cls"):
            bits.append(self.cfg.class_label(sc["cls"]) + (f"-{sc['section']}" if sc.get("section") else ""))
        elif sc.get("section"):
            bits.append(f"Section {sc['section']}")
        if sc.get("group"):
            g = next((x for x in self.cfg.groups if x["id"] == sc["group"]), None)
            bits.append(f"Group {sc['group']}" + (f" ({g['name']})" if g else ""))
        if sc.get("gender"):
            bits.append({"F": "girls", "M": "boys"}.get(sc["gender"], sc["gender"]))
        if exam:
            bits.append(self.cfg.exam_name(exam))
        return ", ".join(bits) if bits else "all classes"

    def classes_in(self, sc):
        return [sc["cls"]] if sc.get("cls") else self.ds.classes()

    def rows_for(self, sc, exam_by_cls, subject=None):
        out = []
        for r in self.res.rows:
            st = self.ds.students[r.sid]
            if not self.in_scope(st, sc) or exam_by_cls.get(st.cls) != r.exam:
                continue
            if subject and r.subject != subject:
                continue
            out.append(r)
        return out

    def exams_map(self, sc):
        return {c: self.exam_for(c, sc.get("exam")) for c in self.classes_in(sc)}

    def exam_note(self, sc, em):
        if sc.get("exam"):
            return ""
        parts = [f"{self.cfg.exam_name(e)} for {self.cfg.class_label(c)}" for c, e in em.items() if e]
        return " Used the latest exam with marks (" + "; ".join(parts) + "). Name an exam to choose another."

    def student_cols(self, st):
        return [st.name, f"{st.cls}{('-' + st.section) if st.section else ''}", st.roll]

    # ------------------------------------------------------------ run
    def run(self, q):
        self.validate(q)
        op = q["op"]
        return getattr(self, "op_" + op)(q)

    # ---- ranking
    def _ranked(self, q, reverse):
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        n = q.get("n") or 5
        subj = q.get("subject")
        items = []
        if subj:
            for r in self.rows_for(sc, em, subj):
                if r.status == STATUS_OK:
                    items.append((r6(r.pct), self.ds.students[r.sid], r))
        else:
            for (sid, exam), er in self.res.exam_results.items():
                st = self.ds.students[sid]
                if self.in_scope(st, sc) and em.get(st.cls) == exam and er.overall is not None:
                    items.append((er.overall, st, er))
        items.sort(key=lambda x: (-x[0] if reverse else x[0], norm_name(x[1].name)))
        # keep ties at the cut-off
        cut = items[:n]
        if cut and len(items) > n:
            last = cut[-1][0]
            cut += [x for x in items[n:] if x[0] == last]
        what = f"{self.cfg.subject_name(subj)} %" if subj else "overall %"
        rows = []
        for i, (v, st, _) in enumerate(cut):
            rank = 1 + sum(1 for x in items if (x[0] > v if reverse else x[0] < v))
            rows.append([rank] + self.student_cols(st) + [float(round(v, 2))])
        word = "Top" if reverse else "Bottom"
        text = f"{word} {len(cut)} by {what} - {self.scope_text(sc, sc.get('exam'))}."
        if len(cut) > n:
            text += f" ({len(cut) - n} more included because of equal marks.)"
        if not cut:
            text = "No students with marks match that."
        how = (f"Took every student in {self.scope_text(sc)}, sorted by {what} "
               f"({'highest' if reverse else 'lowest'} first) and kept the first {n}.") + self.exam_note(sc, em)
        return {"text": text, "how": how,
                "table": {"columns": ["Rank", "Name", "Class", "Roll", what.capitalize()], "rows": rows},
                "chart": {"type": "bar", "labels": [r[1] for r in rows], "values": [r[4] for r in rows],
                          "label": what} if rows else None}

    def op_top(self, q):
        return self._ranked(q, True)

    def op_bottom(self, q):
        return self._ranked(q, False)

    # ---- filtering by labels / thresholds / results
    def _match(self, q):
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        conds = q.get("conds", [])
        by_sid = {}
        for r in self.res.rows:
            st = self.ds.students[r.sid]
            if self.in_scope(st, sc) and em.get(st.cls) == r.exam:
                by_sid.setdefault(r.sid, []).append(r)
        out = []
        for sid, rows in by_sid.items():
            st = self.ds.students[sid]
            er = self.res.exam_results.get((sid, em[st.cls]))
            details = []
            ok_all = True
            for c in conds:
                hit = self._cond(c, rows, er)
                if hit is None:
                    ok_all = False
                    break
                details.append(hit)
            if ok_all:
                out.append((st, details))
        out.sort(key=lambda x: (x[0].cls, x[0].section, int(x[0].roll) if x[0].roll.isdigit() else 9999, x[0].name))
        return out, sc, em

    def _cond(self, c, rows, er):
        cfg = self.cfg
        subj = c.get("subject")
        cand = [r for r in rows if not subj or r.subject == subj]
        if c.get("label"):
            hit = [r for r in cand if r.label == c["label"]]
            if not hit:
                return None
            return "; ".join(r.reason for r in hit)
        if c.get("op"):
            v = Decimal(str(c["value"]))
            cmp = {"<": lambda a: a < v, "<=": lambda a: a <= v, ">": lambda a: a > v, ">=": lambda a: a >= v}[c["op"]]
            if subj:
                hit = [r for r in cand if r.status == STATUS_OK and cmp(r6(r.pct))]
                return "; ".join(f"{cfg.subject_name(r.subject)} {_p(r.pct)}%" for r in hit) if hit else None
            if er and er.overall is not None and cmp(er.overall):
                return f"overall {_p(er.overall)}%"
            return None
        if c.get("result") == "not_passed":
            hit = [r for r in cand if r.passed == "No"]
            return "; ".join(f"{cfg.subject_name(r.subject)} ({r.label if r.status != STATUS_OK else _p(r.pct) + '%'})"
                             for r in hit) if hit else None
        if c.get("result") == "passed":
            if subj:
                hit = [r for r in cand if r.passed == "Yes"]
                return "; ".join(cfg.subject_name(r.subject) for r in hit) if hit else None
            return "passed all subjects" if er and er.result == "Pass" else None
        if c.get("status"):
            want = c["status"]
            hit = [r for r in cand if (r.status == want if want != "LEAVE" else r.status not in (STATUS_OK, "AB", "INVALID", "INCOMPLETE"))]
            return "; ".join(f"{cfg.subject_name(r.subject)}: {r.label}" for r in hit) if hit else None
        return None

    def _cond_text(self, conds):
        cfg = self.cfg
        out = []
        for c in conds:
            s = cfg.subject_name(c["subject"]) if c.get("subject") else None
            if c.get("label"):
                out.append(f"{c['label'].lower()} in {s}" if s else f"{c['label'].lower()} in any subject")
            elif c.get("op"):
                word = {"<": "below", "<=": "at or below", ">": "above", ">=": "at or above"}[c["op"]]
                val = int(c["value"]) if float(c["value"]) == int(c["value"]) else c["value"]
                out.append(f"{s if s else 'overall'} {word} {val}%")
            elif c.get("result") == "not_passed":
                out.append(f"below the pass mark{' in ' + s if s else ''}")
            elif c.get("result") == "passed":
                out.append(f"passed{' ' + s if s else ' everything'}")
            elif c.get("status"):
                lab = {"AB": "absent", "LEAVE": "on leave"}.get(c["status"], c["status"])
                out.append(f"{lab}{' in ' + s if s else ''}")
        return " AND ".join(out)

    def op_list(self, q):
        hits, sc, em = self._match(q)
        ctext = self._cond_text(q.get("conds", []))
        rows = [self.student_cols(st) + ["; ".join(d)] for st, d in hits]
        text = (f"{len(hits)} student{'s' if len(hits) != 1 else ''} {ctext} - {self.scope_text(sc, sc.get('exam'))}."
                if hits else f"No students are {ctext} in {self.scope_text(sc, sc.get('exam'))}.")
        how = f"Filtered {self.scope_text(sc)}: {ctext}." + self.exam_note(sc, em)
        return {"text": text, "how": how, "table": {"columns": ["Name", "Class", "Roll", "Why"], "rows": rows}}

    def op_count(self, q):
        if not q.get("conds"):
            sc = q.get("scope", {})
            em = self.exams_map(sc)
            n = sum(1 for (sid, e), er in self.res.exam_results.items()
                    if self.in_scope(self.ds.students[sid], sc) and em.get(self.ds.students[sid].cls) == e and er.overall is not None)
            return {"text": f"{n} students have marks in {self.scope_text(sc, sc.get('exam'))}.",
                    "how": f"Counted students in {self.scope_text(sc)} with marks." + self.exam_note(sc, em)}
        res = self.op_list(q)
        hits, sc, em = self._match(q)
        n = len(hits)
        res["text"] = (f"{n} student{'s' if n != 1 else ''} - {self._cond_text(q.get('conds', []))} "
                       f"({self.scope_text(sc, sc.get('exam'))}).")
        res["how"] = "Counted: " + res["how"]
        return res

    # ---- averages / highs / lows
    def op_average(self, q):
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        by = q.get("by")
        subj = q.get("subject")
        if by:
            return self._grouped(q, sc, em, by, subj, "average")
        if subj:
            ok = [r for r in self.rows_for(sc, em, subj) if r.status == STATUS_OK]
            avg = sum((r.pct for r in ok), Decimal(0)) / len(ok) if ok else None
            what = f"{self.cfg.subject_name(subj)}"
        else:
            ers = [er for (sid, e), er in self.res.exam_results.items()
                   if self.in_scope(self.ds.students[sid], sc) and em.get(self.ds.students[sid].cls) == e and er.overall is not None]
            ok = ers
            avg = sum((er.overall for er in ers), Decimal(0)) / len(ers) if ers else None
            what = "overall"
        if avg is None:
            return {"text": "There are no marks for that.", "how": "No matching marks."}
        return {"text": f"Average {what} % in {self.scope_text(sc, sc.get('exam'))}: {_p(avg)}% ({len(ok)} students).",
                "how": f"Added the {what} % of every student with marks and divided by {len(ok)}." + self.exam_note(sc, em)}

    def _grouped(self, q, sc, em, by, subj, metric):
        cfg = self.cfg
        groups = []
        if by == "subject":
            groups = [(s, cfg.subject_name(s), {"subject": s}) for s in views.all_subjects(self.res)]
        elif by == "section":
            groups = [(s, f"Section {s}", {"section": s}) for s in views.all_sections(self.res)]
        elif by == "group":
            groups = [(g["id"], f"Group {g['id']}", {"group": g["id"]}) for g in cfg.groups]
        elif by == "class":
            groups = [(c, cfg.class_label(c), {"cls": c}) for c in self.ds.classes()]
        elif by == "exam":
            cls = sc.get("cls") or (self.ds.classes()[0] if self.ds.classes() else None)
            groups = [(e, cfg.exam_name(e), {"exam": e, "cls": cls}) for e in self.ds.exams_for(cls)]
        rows = []
        for key, label, extra in groups:
            sc2 = dict(sc)
            s2 = subj
            if "subject" in extra:
                s2 = extra["subject"]
            for k in ("section", "group", "cls"):
                if k in extra:
                    sc2[k] = extra[k]
            em2 = {c: extra.get("exam") or em.get(c) or self.exam_for(c) for c in self.classes_in(sc2)}
            rs = self.rows_for(sc2, em2, s2) if s2 else None
            if s2:
                ok = [r for r in rs if r.status == STATUS_OK]
                vals = [r.pct for r in ok]
                yes = sum(1 for r in rs if r.passed == "Yes")
                no = sum(1 for r in rs if r.passed == "No")
            else:
                ers = [er for (sid, e), er in self.res.exam_results.items()
                       if self.in_scope(self.ds.students[sid], sc2) and em2.get(self.ds.students[sid].cls) == e and er.overall is not None]
                vals = [er.overall for er in ers]
                yes = sum(1 for er in ers if er.result == "Pass")
                no = sum(1 for er in ers if er.result == "Not passed")
            if not vals:
                continue
            avg = sum(vals, Decimal(0)) / len(vals)
            rows.append([label, len(vals), float(round(avg, 2)), float(round(max(vals), 2)), float(round(min(vals), 2)),
                         float(round(Decimal(yes) * 100 / (yes + no), 1)) if yes + no else None])
        what = (cfg.subject_name(subj) + " " if subj else "") + "average %"
        best = max(rows, key=lambda r: r[2]) if rows else None
        text = f"{what.capitalize()} by {by} - {self.scope_text(sc, sc.get('exam'))}." + \
               (f" Highest: {best[0]} ({best[2]}%)." if best else "")
        return {"text": text, "how": f"Grouped by {by} and averaged the % of students with marks." + self.exam_note(sc, em),
                "table": {"columns": [by.capitalize(), "Students", "Average %", "Highest %", "Lowest %", "Pass %"], "rows": rows},
                "chart": {"type": "bar", "labels": [r[0] for r in rows], "values": [r[2] for r in rows], "label": "Average %"}}

    def _extreme(self, q, highest):
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        subj = q.get("subject")
        if subj:
            items = [(r6(r.pct), self.ds.students[r.sid], r) for r in self.rows_for(sc, em, subj) if r.status == STATUS_OK]
            what = f"{self.cfg.subject_name(subj)} %"
        else:
            items = [(er.overall, self.ds.students[sid], er) for (sid, e), er in self.res.exam_results.items()
                     if self.in_scope(self.ds.students[sid], sc) and em.get(self.ds.students[sid].cls) == e and er.overall is not None]
            what = "overall %"
        if not items:
            return {"text": "There are no marks for that.", "how": "No matching marks."}
        v = max(i[0] for i in items) if highest else min(i[0] for i in items)
        who = [i for i in items if i[0] == v]
        names = ", ".join(f"{i[1].name} ({i[1].cls}{'-' + i[1].section if i[1].section else ''})" for i in who)
        return {"text": f"{'Highest' if highest else 'Lowest'} {what} in {self.scope_text(sc, sc.get('exam'))}: {_p(v)}% - {names}.",
                "how": f"Looked at the {what} of {len(items)} students and took the {'largest' if highest else 'smallest'}." +
                       self.exam_note(sc, em),
                "table": {"columns": ["Name", "Class", "Roll", what.capitalize()],
                          "rows": [self.student_cols(i[1]) + [float(round(i[0], 2))] for i in who]}}

    def op_highest(self, q):
        return self._extreme(q, True)

    def op_lowest(self, q):
        return self._extreme(q, False)

    def _hard_easy(self, q, hardest):
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        res = self._grouped(q, sc, em, "subject", None, "average")
        rows = res["table"]["rows"]
        if not rows:
            return {"text": "There are no marks for that.", "how": "No matching marks."}
        rows.sort(key=lambda r: r[2], reverse=not hardest)
        top = rows[0]
        res["text"] = (f"{'Hardest' if hardest else 'Easiest'} subject in {self.scope_text(sc, sc.get('exam'))}: "
                       f"{top[0]} (average {top[2]}%, pass {top[5]}%).")
        res["how"] = ("Worked out the average % of every subject and picked the "
                      f"{'lowest' if hardest else 'highest'} one." + self.exam_note(sc, em))
        res["chart"] = {"type": "bar", "labels": [r[0] for r in rows], "values": [r[2] for r in rows], "label": "Average %"}
        return res

    def op_hardest(self, q):
        return self._hard_easy(q, True)

    def op_easiest(self, q):
        return self._hard_easy(q, False)

    def op_pass_rate(self, q):
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        subj = q.get("subject")
        if q.get("by"):
            res = self._grouped(q, sc, em, q["by"], subj, "pass")
            rows = res["table"]["rows"]
            res["chart"] = {"type": "bar", "labels": [r[0] for r in rows], "values": [r[5] for r in rows], "label": "Pass %"}
            best = max((r for r in rows if r[5] is not None), key=lambda r: r[5], default=None)
            res["text"] = (f"Pass % by {q['by']}{' in ' + self.cfg.subject_name(subj) if subj else ''} - "
                           f"{self.scope_text(sc, sc.get('exam'))}." + (f" Highest: {best[0]} ({best[5]}%)." if best else ""))
            return res
        if subj:
            rs = self.rows_for(sc, em, subj)
            yes = sum(1 for r in rs if r.passed == "Yes")
            no = sum(1 for r in rs if r.passed == "No")
            what = self.cfg.subject_name(subj)
        else:
            ers = [er for (sid, e), er in self.res.exam_results.items()
                   if self.in_scope(self.ds.students[sid], sc) and em.get(self.ds.students[sid].cls) == e]
            yes = sum(1 for er in ers if er.result == "Pass")
            no = sum(1 for er in ers if er.result == "Not passed")
            what = "all subjects"
        if not yes + no:
            return {"text": "There are no results for that.", "how": "No matching marks."}
        pct = Decimal(yes) * 100 / (yes + no)
        return {"text": f"Pass rate ({what}) in {self.scope_text(sc, sc.get('exam'))}: {_p(pct)}% - {yes} passed, {no} did not.",
                "how": f"Passed = at least {self.cfg.rules['pass_percent']}%"
                       f"{' in each part' if self.cfg.rules.get('pass_each_part', True) else ''}; absent counts as not passed, "
                       f"medical/duty leave is left out." + self.exam_note(sc, em)}

    def op_compare(self, q):
        cfg = self.cfg
        sc = q.get("scope", {})
        a, b = q.get("groups", [{}, {}])[:2] if q.get("groups") else ({}, {})
        if q.get("subjects") and len(q["subjects"]) >= 2:
            em = self.exams_map(sc)
            rows = []
            for s in q["subjects"][:4]:
                rs = self.rows_for(sc, em, s)
                ok = [r for r in rs if r.status == STATUS_OK]
                if not ok:
                    continue
                yes = sum(1 for r in rs if r.passed == "Yes")
                no = sum(1 for r in rs if r.passed == "No")
                avg = sum((r.pct for r in ok), Decimal(0)) / len(ok)
                rows.append([cfg.subject_name(s), len(ok), float(round(avg, 2)), float(round(max(r.pct for r in ok), 2)),
                             float(round(min(r.pct for r in ok), 2)), float(round(Decimal(yes) * 100 / (yes + no), 1)) if yes + no else None])
            text = " vs ".join(f"{r[0]} {r[2]}%" for r in rows)
            return {"text": f"Average %: {text} ({self.scope_text(sc, sc.get('exam'))}).",
                    "how": "Averaged each subject's % over the students who take it." + self.exam_note(sc, em),
                    "table": {"columns": ["Subject", "Students", "Average %", "Highest %", "Lowest %", "Pass %"], "rows": rows},
                    "chart": {"type": "bar", "labels": [r[0] for r in rows], "values": [r[2] for r in rows], "label": "Average %"}}
        rows = []
        for g in (a, b):
            sc2 = dict(sc)
            sc2.update({k: v for k, v in g.items() if k in ("cls", "section", "group", "gender")})
            exam = g.get("exam") or sc.get("exam")
            em2 = {c: exam or self.exam_for(c) for c in self.classes_in(sc2)}
            subj = q.get("subject")
            if subj:
                rs = self.rows_for(sc2, em2, subj)
                vals = [r.pct for r in rs if r.status == STATUS_OK]
                yes = sum(1 for r in rs if r.passed == "Yes")
                no = sum(1 for r in rs if r.passed == "No")
            else:
                ers = [er for (sid, e), er in self.res.exam_results.items()
                       if self.in_scope(self.ds.students[sid], sc2) and em2.get(self.ds.students[sid].cls) == e and er.overall is not None]
                vals = [er.overall for er in ers]
                yes = sum(1 for er in ers if er.result == "Pass")
                no = sum(1 for er in ers if er.result == "Not passed")
            label = self.scope_text(sc2, exam if g.get("exam") else None)
            if vals:
                rows.append([label, len(vals), float(round(sum(vals, Decimal(0)) / len(vals), 2)),
                             float(round(max(vals), 2)), float(round(min(vals), 2)),
                             float(round(Decimal(yes) * 100 / (yes + no), 1)) if yes + no else None])
            else:
                rows.append([label, 0, None, None, None, None])
        what = cfg.subject_name(q["subject"]) + " " if q.get("subject") else "overall "
        if all(r[2] is not None for r in rows):
            diff = Decimal(str(rows[0][2])) - Decimal(str(rows[1][2]))
            lead = rows[0][0] if diff > 0 else rows[1][0]
            text = (f"{rows[0][0]}: {rows[0][2]}% vs {rows[1][0]}: {rows[1][2]}% ({what}average). "
                    + (f"{lead} is ahead by {fmt_num(abs(diff))} points." if diff else "They are equal."))
        else:
            text = "One of the two groups has no marks."
        return {"text": text, "how": f"Averaged the {what}% of each group's students.",
                "table": {"columns": ["Group", "Students", "Average %", "Highest %", "Lowest %", "Pass %"], "rows": rows},
                "chart": {"type": "bar", "labels": [r[0] for r in rows], "values": [r[2] for r in rows], "label": "Average %"}}

    # ---- one student
    def op_student(self, q):
        cfg = self.cfg
        sid = q["students"][0]
        st = self.ds.students[sid]
        exam = self.exam_for(st.cls, q.get("scope", {}).get("exam"))
        card = views.report_card(self.res, sid, exam)
        rows = [[x["name"], _fmt_part(x["theory"]), _fmt_part(x["practical"]), float(round(x["pct"], 2)) if x["pct"] is not None else None,
                 x["grade"], x["label"]] for x in card["rows"]]
        text = (f"{st.name} ({st.cls}{'-' + st.section if st.section else ''}) - {cfg.exam_name(exam)}: overall "
                f"{_p(card['overall'])}%, rank {card['rank'] or '-'} of {card['class_size']}, {card['result'] or 'no result'}.")
        return {"text": text, "how": "Looked up the student's marks; % and labels come from the Subject Results.",
                "table": {"columns": ["Subject", "Theory", "Practical", "%", "Grade", "Label"], "rows": rows},
                "chart": {"type": "bar", "labels": [r[0] for r in rows], "values": [r[3] for r in rows], "label": "%"},
                "remarks": card["remarks"], "student": sid}

    def op_student_subjects(self, q):
        cfg = self.cfg
        sid = q["students"][0]
        st = self.ds.students[sid]
        exam = self.exam_for(st.cls, q.get("scope", {}).get("exam"))
        er = self.res.exam_results.get((sid, exam))
        ok = [r for r in er.rows if r.status == STATUS_OK] if er else []
        weakest = q.get("order", "weakest") == "weakest"
        ok.sort(key=lambda r: (r6(r.pct), r.subject) if weakest else (-r6(r.pct), r.subject))
        n = q.get("n") or 3
        pick = ok[:n]
        names = ", ".join(f"{cfg.subject_name(r.subject)} ({_p(r.pct)}%)" for r in pick)
        return {"text": f"{st.name}'s {'weakest' if weakest else 'strongest'} subjects in {cfg.exam_name(exam)}: {names}.",
                "how": "Sorted the student's subjects by % " + ("(lowest first)." if weakest else "(highest first)."),
                "table": {"columns": ["Subject", "%", "Label", "Why"],
                          "rows": [[cfg.subject_name(r.subject), float(round(r.pct, 2)), r.label, r.reason] for r in ok]}}

    def op_rank(self, q):
        sid = q["students"][0]
        st = self.ds.students[sid]
        exam = self.exam_for(st.cls, q.get("scope", {}).get("exam"))
        er = self.res.exam_results.get((sid, exam))
        if not er or er.rank is None:
            return {"text": f"{st.name} has no overall % in {self.cfg.exam_name(exam)}.", "how": "No marks."}
        size = sum(1 for o in self.res.exam_results.values() if o.exam == exam and o.overall is not None
                   and self.ds.students[o.sid].cls == st.cls)
        return {"text": f"{st.name}: rank {er.rank} of {size} in {self.cfg.class_label(st.cls)} and "
                        f"{er.section_rank} in Section {st.section or '-'} ({self.cfg.exam_name(exam)}, overall {_p(er.overall)}%).",
                "how": "Rank = 1 + number of students in the class with a higher overall %. Equal marks share a rank."}

    def op_distribution(self, q):
        cfg = self.cfg
        sc = q.get("scope", {})
        em = self.exams_map(sc)
        subj = q.get("subject")
        grades = [g["grade"] for g in sorted(cfg.rules["grades"], key=lambda g: -g["min"])]
        if subj:
            vals = [r6(r.pct) for r in self.rows_for(sc, em, subj) if r.status == STATUS_OK]
        else:
            vals = [er.overall for (sid, e), er in self.res.exam_results.items()
                    if self.in_scope(self.ds.students[sid], sc) and em.get(self.ds.students[sid].cls) == e and er.overall is not None]
        counts = [(g, sum(1 for v in vals if cfg.grade(v) == g)) for g in grades]
        what = cfg.subject_name(subj) if subj else "overall %"
        return {"text": f"Grades for {what} in {self.scope_text(sc, sc.get('exam'))} ({len(vals)} students): " +
                        ", ".join(f"{g} {c}" for g, c in counts if c) + ".",
                "how": "Turned each % into the school grade (bands in Settings) and counted.",
                "table": {"columns": ["Grade", "Students"], "rows": [[g, c] for g, c in counts]},
                "chart": {"type": "bar", "labels": [g for g, _ in counts], "values": [c for _, c in counts], "label": "Students"}}

    def _changes(self, q):
        sc = q.get("scope", {})
        out = []
        for st in self.ds.ordered_students():
            if not self.in_scope(st, sc):
                continue
            pg = progress(self.res, st.sid)
            if pg["latest_change"]:
                a, b, d = pg["latest_change"]
                out.append((d, st, a, b, pg["dropped_twice"]))
        return out, sc

    def op_improved(self, q):
        items, sc = self._changes(q)
        items.sort(key=lambda x: -x[0])
        n = q.get("n") or 10
        pick = [x for x in items if x[0] > 0][:n]
        return {"text": f"Most improved in {self.scope_text(sc)}: " + (", ".join(f"{x[1].name} (+{_p(x[0])})" for x in pick[:5]) or "nobody improved") + ".",
                "how": "Change = overall % in the latest exam minus the exam before it.",
                "table": {"columns": ["Name", "Class", "Roll", "From", "To", "Change"],
                          "rows": [self.student_cols(x[1]) + [self.cfg.exam_name(x[2]), self.cfg.exam_name(x[3]), float(round(x[0], 2))]
                                   for x in pick]}}

    def op_dropped(self, q):
        items, sc = self._changes(q)
        twice = q.get("twice")
        items = [x for x in items if (x[4] if twice else x[0] < 0)]
        items.sort(key=lambda x: x[0])
        n = q.get("n") or 50
        pick = items[:n]
        what = "dropped in two exams in a row" if twice else "went down in the latest exam"
        return {"text": f"{len(pick)} student{'s' if len(pick) != 1 else ''} {what} ({self.scope_text(sc)}).",
                "how": f"Change = overall % in an exam minus the one before it"
                       + (f"; a drop counts when it is at least {self.cfg.rules['drop_alert_gap']} points." if twice else "."),
                "table": {"columns": ["Name", "Class", "Roll", "From", "To", "Change"],
                          "rows": [self.student_cols(x[1]) + [self.cfg.exam_name(x[2]), self.cfg.exam_name(x[3]), float(round(x[0], 2))]
                                   for x in pick]}}

    def op_absent(self, q):
        q = dict(q)
        q["conds"] = [{"status": q.get("status", "AB"), "subject": q.get("subject")}]
        return self.op_list(q)

    def op_help(self, q):
        return {"text": "Ask about the uploaded marks in your own words. For example: \"Top 5 in Class XI\", "
                        "\"Who is weak in Maths but strong in Physics?\", \"Which subject is hardest?\", "
                        "\"Compare section A and B\", \"Show Aarav's weakest subjects\", \"How many failed in Chemistry?\".",
                "how": "Questions are matched to fixed, checked operations - nothing is guessed."}

    # ---- board
    def _an(self):
        return self.board[-1]

    def op_board_top(self, q):
        an = self._an()
        n = q.get("n") or 10
        subj = q.get("subject")
        if subj:
            items = []
            for r in an["rows"]:
                x = next((y for y in r["s"].subjects if y["code"] == subj and y["marks"] is not None), None)
                if x:
                    items.append((x["marks"], r["s"]))
            items.sort(key=lambda t: (-t[0], t[1].name))
            cut = items[:n]
            if cut and len(items) > n:
                cut += [t for t in items[n:] if t[0] == cut[-1][0]]
            rows = [[1 + sum(1 for t in items if t[0] > v), s.name, s.roll, v] for v, s in cut]
            name = self.cfg.subject_name(subj) if self.cfg else subj
            tie = f" ({len(cut) - n} more shown because of equal marks.)" if len(cut) > n else ""
            return {"text": f"Board {an['meta']['year']} - top {n} in {name}.{tie}",
                    "how": "Sorted board marks in that subject (highest first).",
                    "table": {"columns": ["Rank", "Name", "Roll", "Marks"], "rows": rows}}
        cut = an["ranked"][:n]
        if cut and len(an["ranked"]) > n:
            cut += [r for r in an["ranked"][n:] if r["best5"] == cut[-1]["best5"]]
        rows = [[r["rank"], r["s"].name, r["s"].roll, float(r["best5"])] for r in cut]
        tie = f" ({len(cut) - n} more shown because of equal marks.)" if len(cut) > n else ""
        return {"text": f"Board {an['meta']['year']} - top {n} by best-5 %.{tie}",
                "how": "Best 5 = English + the four best other subjects, divided by 5.",
                "table": {"columns": ["Rank", "Name", "Roll", "Best 5 %"], "rows": rows},
                "chart": {"type": "bar", "labels": [r[1] for r in rows], "values": [r[3] for r in rows], "label": "Best 5 %"}}

    def op_board_subject(self, q):
        an = self._an()
        rows = [[x["name"], x["candidates"], float(round(x["avg"], 2)) if x["avg"] is not None else None, x["max"],
                 x["failed"], float(round(x["pi"], 2)) if x["pi"] is not None else None] for x in an["subjects"]]
        subj = q.get("subject")
        if subj:
            x = next((y for y in an["subjects"] if y["code"] == subj), None)
            if not x:
                return {"text": "That subject is not in the board results.", "how": "-"}
            return {"text": f"Board {an['meta']['year']} - {x['name']}: {x['candidates']} candidates, average {_p(x['avg'])}, "
                            f"highest {x['max']}, PI {_p(x['pi'])}, {x['failed']} with grade E.",
                    "how": "From the gazette marks and CBSE grades."}
        return {"text": f"Board {an['meta']['year']} - subject results.", "how": "From the gazette marks and CBSE grades.",
                "table": {"columns": ["Subject", "Candidates", "Average", "Highest", "Grade E", "PI"], "rows": rows},
                "chart": {"type": "bar", "labels": [r[0] for r in rows], "values": [r[2] for r in rows], "label": "Average"}}

    def op_board_summary(self, q):
        an = self._an()
        return {"text": f"Board {an['meta']['year']}: {an['candidates']} candidates, {an['passed']} passed ({_p(an['pass_pct'])}%), "
                        f"{an['comp']} compartment, average best-5 {_p(an['avg_best5'])}%, {an['above90']} scored 90%+, "
                        f"school PI {_p(an['school_pi'])}.",
                "how": "Counted from the gazette; pass/compartment exactly as CBSE printed."}

    def op_board_comp(self, q):
        an = self._an()
        cfg = self.cfg
        rows = [[s.name, s.roll, ", ".join(cfg.subject_name(c) if cfg else c for c in s.comp)] for s in an["comp_list"]]
        return {"text": f"{len(rows)} compartment{'s' if len(rows) != 1 else ''} in the {an['meta']['year']} boards.",
                "how": "Students whose result is COMP in the gazette.",
                "table": {"columns": ["Name", "Roll", "Compartment in"], "rows": rows}}

    def op_board_student(self, q):
        an = self._an()
        roll = q.get("roll")
        r = next((x for x in an["rows"] if x["s"].roll == roll), None)
        if not r:
            return {"text": "That student is not in the board results.", "how": "-"}
        s = r["s"]
        cfg = self.cfg
        rows = [[cfg.subject_name(x["code"]) if cfg else x["code"], x["marks"], x["grade"]] for x in s.subjects]
        return {"text": f"{s.name} ({s.roll}) - boards {an['meta']['year']}: best 5 {_p(r['best5'])}%, rank {r['rank']}, {s.result}.",
                "how": "From the gazette.", "table": {"columns": ["Subject", "Marks", "Grade"], "rows": rows}}


def _fmt_part(v):
    if v is None or v == "":
        return ""
    if isinstance(v, Decimal):
        return float(v)
    return v
