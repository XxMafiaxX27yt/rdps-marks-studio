"""Loads the editable settings (subjects, rules, groups) and answers simple
questions about them, e.g. "what is the maximum written mark for Physics in
the Class XI Half Yearly?".

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
        s = upgrade_settings(s)
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
        self._schemes = {}
        self.part_labels = dict(self.rules.get("part_labels", {}))

    # ---- numbers -------------------------------------------------------
    def d(self, key):
        """A rule value as an exact Decimal (e.g. pass_percent -> Decimal('33'))."""
        return Decimal(str(self.rules[key]))

    # ---- classes --------------------------------------------------------
    def class_level(self, cls):
        c = self.classes.get(cls)
        return c.get("level", 99) if c else 99

    def has_streams(self, cls):
        c = self.classes.get(cls)
        return bool(c and c.get("streams"))

    def class_offer(self, cls):
        """Fixed subjects + language choices of a junior class (None for classes with streams)."""
        for k, v in self.rules.get("class_subjects", {}).items():
            if isinstance(v, dict) and cls in v.get("classes", []):
                return v
        return None

    def languages_for(self, cls):
        off = self.class_offer(cls)
        return list(off.get("language", [])) if off else []

    def class_subject_codes(self, cls):
        """The subjects one class has, in the usual order. A junior class: its fixed subjects and languages
        (rules.class_subjects). XI-XII: every subject of a stream, and any subject no junior class has
        (an additional 6th subject)."""
        off = self.class_offer(cls)
        if off:
            codes = set(off.get("subjects", [])) | set(off.get("language", []))
        else:
            junior = set()
            for v in self.rules.get("class_subjects", {}).values():
                if isinstance(v, dict):
                    junior |= set(v.get("subjects", [])) | set(v.get("language", []))
            codes = {c for g in self.groups for c in g.get("core", []) + [x for ch in g.get("choices", []) for x in ch]}
            codes |= {c for c in self.subjects if c not in junior}
        return self.order_subjects(codes)

    def resolve_subject(self, cls, code):
        """In junior classes a heading like 'Computer' means ICT (see junior_subject_alias)."""
        if code and cls in self.classes and not self.has_streams(cls):
            alias = self.rules.get("junior_subject_alias", {})
            if code in alias and not code.startswith("_"):
                return alias[code]
        return code

    # ---- subjects -------------------------------------------------------
    def subject_name(self, code):
        s = self.subjects.get(code)
        return s["name"] if s else "Subject " + str(code)

    def subject_short(self, code):
        s = self.subjects.get(code)
        return s["short"] if s else str(code)

    def board_name(self, code, cls=""):
        """Subject name for a board gazette code (Class X codes can differ from the school's)."""
        if cls == "X":
            x = self.rules.get("board", {}).get("x_names", {})
            if code in x:
                return x[code]
        return self.subject_name(code)

    def board_short(self, code, cls=""):
        if cls == "X" and code in self.rules.get("board", {}).get("x_names", {}):
            return self.board_name(code, cls)
        return self.subject_short(code)

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

    def pt_source(self, exam):
        """The periodic test whose marks become the 'PT' part of this big exam's internal marks."""
        return self.rules.get("internal_pt_from", {}).get(exam)

    # ---- marks schemes --------------------------------------------------
    def scheme(self, cls, subject, exam):
        """How a subject is marked in one exam of one class:
        None = not assessed (not counted), else
        {'theory': Decimal, 'second': None | {'label', 'max': Decimal, 'parts': [(key, Decimal), ...]}}"""
        key = (cls, subject, exam)
        if key in self._schemes:
            return self._schemes[key]
        out = None
        if exam in self.exams:
            kind = self.exam_kind(exam)
            c = cls if cls in self.classes else "XI"
            for rule in self.rules.get("mark_schemes", []):
                if "classes" not in rule or c not in rule["classes"]:
                    continue
                if rule.get("subjects") and subject not in rule["subjects"]:
                    continue
                if rule.get("exams") and rule["exams"] != kind:
                    continue
                if rule.get("practical_subjects") and not self.has_practical(subject):
                    continue
                if rule.get("assessed", True) is False:
                    break
                out = {"theory": Decimal(str(rule["theory"])), "second": None}
                sec = rule.get("second")
                if sec:
                    parts = [(p[0], Decimal(str(p[1]))) for p in sec.get("parts", [])]
                    mx = Decimal(str(sec["max"])) if sec.get("max") is not None else sum((p[1] for p in parts), Decimal(0))
                    out["second"] = {"label": sec.get("label", "Practical"), "max": mx, "parts": parts,
                                     "optional": bool(sec.get("optional"))}
                break
        self._schemes[key] = out
        return out

    def assessed(self, cls, subject, exam):
        return self.scheme(cls, subject, exam) is not None

    def components(self, cls, subject, exam):
        """Which halves a subject has in an exam, with their maximum marks, e.g.
        {'theory': Decimal('80'), 'practical': Decimal('20')}. 'practical' is the second half
        (practical, or internal assessment in Classes I-X)."""
        sc = self.scheme(cls, subject, exam)
        if not sc:
            return {}
        out = {"theory": sc["theory"]}
        if sc["second"]:
            out["practical"] = sc["second"]["max"]
        return out

    def subparts(self, cls, subject, exam):
        """[(key, max)] when the second half is made of parts (internal assessment, AI practical)."""
        sc = self.scheme(cls, subject, exam)
        return list(sc["second"]["parts"]) if sc and sc["second"] else []

    def second_optional(self, cls, subject, exam):
        """True when the second part may be left out of a file (then only the written paper counts)."""
        sc = self.scheme(cls, subject, exam)
        return bool(sc and sc["second"] and sc["second"]["optional"])

    def second_label(self, cls, subject, exam):
        sc = self.scheme(cls, subject, exam)
        return sc["second"]["label"] if sc and sc["second"] else ""

    def part_label(self, key):
        if key == "theory":
            return self.part_labels.get("theory", "Written")
        return self.part_labels.get(key, key.replace("_", " ").title())

    def subject_max(self, cls, subject, exam):
        return sum(self.components(cls, subject, exam).values(), Decimal(0))

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


def upgrade_settings(s):
    """Settings saved by version 1 (Classes XI and XII only) get the new classes, exams, marks
    schemes and subjects; the school's own choices (names, pass mark, grades, labels, leave codes,
    practical subjects) are kept."""
    rules = s.get("rules", {})
    if rules.get("settings_version", 1) >= 2:
        return s
    d = default_settings()
    keep = {k: v for k, v in rules.items() if k in (
        "school_name", "school_short", "school_place", "academic_year", "pass_percent", "pass_each_part", "strong_gap",
        "weak_gap", "attention_class_gap", "drop_alert_gap", "leave_codes", "blank_means", "grades", "score_bins")}
    d["rules"].update(keep)
    old_subjects = {x["code"]: x for x in s.get("subjects", [])}
    for x in d["subjects"]:
        if x["code"] in old_subjects:
            x["practical"] = old_subjects[x["code"]].get("practical", x["practical"])
    known = {y["code"] for y in d["subjects"]}
    for code, x in old_subjects.items():
        if code not in known:
            d["subjects"].append(x)
    if s.get("groups"):
        d["groups"] = s["groups"]
    return d
