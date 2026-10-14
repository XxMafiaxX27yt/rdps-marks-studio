"""The data model. Marks are kept as one record per (student, exam, subject, part)
- a "normalized" list - and only turned into a student x subject grid when the
workbook is written. Every record remembers exactly where it came from."""
from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal

from .textutil import col_letter


@dataclass
class Ref:
    """Where a value came from: file, sheet (or page), row number (1-based) and column (0-based)."""
    file: str
    sheet: str = ""
    row: int = 0
    col: Optional[int] = None

    def cell(self):
        c = col_letter(self.col) if self.col is not None else ""
        return f"{c}{self.row}" if self.row else c

    def text(self):
        parts = [self.file]
        if self.sheet:
            parts.append(self.sheet)
        if self.row:
            if self.col is not None:
                parts.append(f"cell {self.cell()}")
            else:
                parts.append(f"row {self.row}")
        return " › ".join(parts)

    def to_dict(self):
        return {"file": self.file, "sheet": self.sheet, "row": self.row, "col": self.col, "text": self.text()}


@dataclass
class Student:
    sid: str
    name: str
    cls: str = ""                 # 'XI' / 'XII'
    section: str = ""
    roll: str = ""                # school roll number
    adm_no: str = ""              # admission number
    board_roll: str = ""
    father: str = ""
    mother: str = ""
    gender: str = ""
    group: str = ""               # A-E (worked out from subjects unless the file says)
    group_given: str = ""         # group written in the file, if any
    group_note: str = ""
    subjects: list = field(default_factory=list)     # subject codes the student takes
    choices_given: bool = False   # True when the file listed the student's subjects
    refs: list = field(default_factory=list)

    def label(self):
        bits = [self.name]
        if self.cls:
            bits.append(f"{self.cls}{('-' + self.section) if self.section and self.section != '-' else ''}")
        if self.roll:
            bits.append(f"Roll {self.roll}")
        return " · ".join(bits)

    def to_dict(self):
        return {
            "sid": self.sid, "name": self.name, "cls": self.cls, "section": self.section,
            "roll": self.roll, "adm_no": self.adm_no, "board_roll": self.board_roll,
            "father": self.father, "mother": self.mother, "gender": self.gender,
            "group": self.group, "group_given": self.group_given, "group_note": self.group_note,
            "subjects": list(self.subjects), "choices_given": self.choices_given,
            "refs": [r.to_dict() for r in self.refs],
        }


@dataclass
class Mark:
    """One part of one subject in one exam for one student."""
    sid: str
    exam: str
    subject: str
    component: str                # 'theory' / 'practical'
    raw: str                      # exactly what the file had (after any teacher correction)
    kind: str                     # 'number' | 'leave' | 'blank' | 'invalid'
    value: Optional[Decimal] = None
    code: str = ""                # leave code when kind == 'leave'
    ref: Optional[Ref] = None
    original: Optional[str] = None  # set when a teacher corrected the value
    problem: str = ""             # why it is invalid

    def key(self):
        return (self.sid, self.exam, self.subject, self.component)


@dataclass
class Issue:
    severity: str                 # 'error' | 'warning' | 'info'
    code: str
    message: str
    ref: Optional[Ref] = None
    sid: str = ""
    subject: str = ""
    exam: str = ""
    fix: dict = field(default_factory=dict)

    def to_dict(self, students=None):
        d = {
            "severity": self.severity, "code": self.code, "message": self.message,
            "ref": self.ref.to_dict() if self.ref else None, "sid": self.sid,
            "subject": self.subject, "exam": self.exam, "fix": self.fix,
        }
        if students is not None and self.sid in students:
            d["student"] = students[self.sid].label()
        return d
