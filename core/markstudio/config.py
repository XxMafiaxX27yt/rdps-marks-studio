"""Loads the editable settings (subjects, rules, groups) and answers simple
questions about them, e.g. "what is the maximum theory mark for Physics in
the Half Yearly?".

Everything the rest of the code needs to know about the school's rules goes
through the Config object, so nothing is hard-coded anywhere else.
"""
import copy
import json
import os
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.join(_HERE, "config")


def _load(name):
    with open(os.path.join(_CONFIG_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def default_settings():
    """The three settings files as one dictionary (a fresh copy every time)."""
    return {
        "subjects": _load("subjects.json")["subjects"],
        "rules": _load("rules.json"),
        "groups": _load("groups.json")["groups"],
    }


class Config:
    """Read-only view of the settings with handy lookups."""

    def __init__(self, settings=None):
        s = copy.deepcopy(settings) if settings else default_settings()
        self.settings = s
        self.rules = s["rules"]
        self.subjects = {x["code"]: x for x in s["subjects"]}
        self.subject_order = [x["code"] for x in s["subjects"]]
        self.groups = s["groups"]
        self.exams = self.rules["exams"]
        self.classes = self.rules["classes"]
        self.leaves = {x["code"]: x for x in self.rules["leave_codes"]}
        self._leave_alias = {}
        for x in self.rules["leave_codes"]:
            self._leave_alias[x["code"].lower()] = x["code"]
            for a in x.get("aliases", []):
                self._leave_alias[a.lower()] = x["code"]

    # ---- numbers -------------------------------------------------------
    def d(self, key):
        """A rule value as an exact Decimal (e.g. pass_percent -> Decimal('33'))."""
        return Decimal(str(self.rules[key]))

    # ---- subjects -------------------------------------------------------
    def subject_name(self, code):
        s = self.subjects.get(code)
        return s["name"] if s else "Subject " + str(code)

    def subject_short(self, code):
        s = self.subjects.get(code)
        return s["short"] if s else str(code)

    def has_practical(self, code):
        s = self.subjects.get(code)
        return bool(s and s.get("practical"))

    def order_subjects(self, codes):
        known = [c for c in self.subject_order if c in codes]
        return known + sorted(c for c in codes if c not in self.subjects)

    # ---- exams ----------------------------------------------------------
    def exam_kind(self, exam):
        return self.exams[exam]["kind"]

    def exam_name(self, exam):
        e = self.exams.get(exam)
        return e["name"] if e else exam

    def class_exams(self, cls):
        c = self.classes.get(cls)
        return list(c["exams"]) if c else []

    def exam_order(self, cls, exam):
        ex = self.class_exams(cls)
        return ex.index(exam) + 1 if exam in ex else 99

    def components(self, subject, exam):
        """Which parts a subject has in an exam, with their maximum marks.
        Returns an ordered dict like {'theory': Decimal('70'), 'practical': Decimal('30')}."""
        kind = self.exam_kind(exam)
        table = self.rules["max_marks"][kind]
        part = table["with_practical"] if self.has_practical(subject) else table["theory_only"]
        out = {}
        for comp in ("theory", "practical"):
            if comp in part and part[comp]:
                out[comp] = Decimal(str(part[comp]))
        return out

    def subject_max(self, subject, exam):
        return sum(self.components(subject, exam).values(), Decimal(0))

    # ---- leave codes ----------------------------------------------------
    def leave_code(self, text):
        """'Abs' -> 'AB', 'M.L.' -> 'ML', anything else -> None."""
        if text is None:
            return None
        t = str(text).strip().lower()
        return self._leave_alias.get(t)

    def leave_label(self, code):
        x = self.leaves.get(code)
        return x["label"] if x else code

    def counts_as_fail(self, code):
        x = self.leaves.get(code)
        return bool(x and x.get("counts_as_fail"))

    # ---- grades ---------------------------------------------------------
    def grade(self, percent):
        """School grade for a percentage (bands from rules.json, highest first)."""
        if percent is None:
            return ""
        p = Decimal(percent)
        for g in sorted(self.rules["grades"], key=lambda x: -x["min"]):
            if p >= Decimal(str(g["min"])):
                return g["grade"]
        return self.rules["grades"][-1]["grade"]

    def class_label(self, cls):
        c = self.classes.get(cls)
        return c["label"] if c else "Class " + str(cls)
