"""Version 2: Classes I-XII, internal marks, the Language column, teachers, and the wider Ask."""
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from markstudio.config import Config
from markstudio import build, calc, verify, api
from markstudio.layout import Vocab


def run_csv(*files):
    cfg = Config()
    p = build.Project(cfg)
    for name, text in files:
        p.add_file(name, text.encode())
    ds = p.build()
    res = calc.compute(ds)
    verify.check(ds, res)
    return ds, res


def row(res, ds, name, exam, subject):
    for r in res.rows:
        if ds.students[r.sid].name == name and r.exam == exam and r.subject == subject:
            return r
    return None


def test_class_names_every_way():
    v = Vocab(Config())
    for text, want in [("VI-A", ("VI", "A")), ("6th B", ("VI", "B")), ("Class 9 C", ("IX", "C")), ("X", ("X", "")),
                       ("11a", ("XI", "A")), ("xii-b", ("XII", "B")), ("Class 3", ("III", "")), ("10", ("X", ""))]:
        assert v.class_section(text) == want, text
    assert v.find_class("Sheet 1") is None and v.find_class("Term I") is None


def test_marks_only_counts_out_of_written_paper():
    ds, res = run_csv(("Class VI Half Yearly.csv", "Roll,Name,Section,English,Maths\n1,Riya Sen,A,62,40\n"))
    r = row(res, ds, "Riya Sen", "HY", "301")
    assert r.status == "OK" and r.written_only and r.max == Decimal(80) and r.pct == Decimal("77.5")
    assert not any(i.severity == "error" for i in ds.issues)


def test_internal_parts_and_pt_part_from_pt1():
    pt1 = "Roll,Name,Section,English\n1,Riya Sen,A,17\n"
    hy = "Roll,Name,Section,English Written,English Portfolio,English Project,English Notebook\n1,Riya Sen,A,62,4,5,3\n"
    ds, res = run_csv(("Class VI PT1.csv", pt1), ("Class VI Half Yearly.csv", hy))
    r = row(res, ds, "Riya Sen", "HY", "301")
    # PT part = 17/20 x 5 = 4.25; internal = 4.25 + 4 + 5 + 3 = 16.25
    assert r.pr == Decimal("16.25") and r.pr_max == 20 and r.obtained == Decimal("78.25") and r.pct == Decimal("78.25")


def test_one_internal_total_column():
    hy = "Roll,Name,Section,Maths,Maths Internal\n1,Riya Sen,A,50,15\n"
    ds, res = run_csv(("Class IX Half Yearly.csv", hy))
    r = row(res, ds, "Riya Sen", "HY", "041")
    assert r.th == 50 and r.pr == 15 and r.max == 100 and r.pct == Decimal(65)


def test_pt_maximum_depends_on_class():
    ds, res = run_csv(("Class VIII PT1.csv", "Roll,Name,Section,Maths\n1,Om Rao,A,25\n"),
                      ("Class IX PT1.csv", "Roll,Name,Section,Maths\n1,Ira Das,A,25\n"))
    assert row(res, ds, "Om Rao", "PT1", "041").status == "INVALID"           # 25 > 20 in Class VIII
    assert row(res, ds, "Ira Das", "PT1", "041").pct == Decimal("62.5")       # 25 / 40 in Class IX


def test_language_column_uses_each_students_language():
    students = "Roll,Name,Section,Language\n1,Riya Sen,A,French\n2,Om Rao,A,Sanskrit\n"
    hy = "Roll,Name,Section,English,Language\n1,Riya Sen,A,60,64\n2,Om Rao,A,55,71\n"
    ds, res = run_csv(("Class VI Students.csv", students), ("Class VI Half Yearly.csv", hy))
    assert row(res, ds, "Riya Sen", "HY", "018").th == 64
    assert row(res, ds, "Om Rao", "HY", "122").th == 71


def test_same_marks_are_never_duplicates():
    hy = "Roll,Name,Section,English,Maths\n4,Aarav Jain,A,72,65\n9,Diya Roy,A,72,65\n"
    ds, res = run_csv(("Class VII Half Yearly.csv", hy))
    assert len(ds.students) == 2
    assert not any(i.code in ("duplicate_id", "conflict") for i in ds.issues)


def test_ict_rules():
    six = "Roll,Name,Section,English,ICT\n1,Riya Sen,A,60,4\n"
    seven = "Roll,Name,Section,English,ICT\n1,Om Rao,A,60,24\n"
    ds, res = run_csv(("Class VI Half Yearly.csv", six), ("Class VII Half Yearly.csv", seven))
    assert row(res, ds, "Riya Sen", "HY", "402") is None                          # not counted in I-VI
    assert row(res, ds, "Om Rao", "HY", "402").pct == Decimal(80)                 # 24 / 30 from VII


def test_weak_student_needs_support_only_where_below_pass():
    hy = "Roll,Name,Section,English,Maths,Science\n1,A One,A,70,70,70\n2,B Two,A,70,72,74\n3,C Three,A,20,40,42\n"  # English 20/80 = 25%
    ds, res = run_csv(("Class VIII Half Yearly.csv", hy))
    labels = {r.subject: r.label for r in res.rows if ds.students[r.sid].name == "C Three"}
    assert labels["301"] == "Needs attention" and labels["041"] != "Needs attention" and labels["086"] != "Needs attention"


def test_best_subject_is_not_a_focus_area():
    hy = "Roll,Name,Section,English,Maths,Science\n1,A One,A,78,79,77\n2,B Two,A,79,78,80\n3,C Three,A,60,48,47\n"
    ds, res = run_csv(("Class VIII Half Yearly.csv", hy))
    sid = next(s.sid for s in ds.students.values() if s.name == "C Three")
    rem = calc.remarks(res, sid, "HY")
    best = rem[0]
    assert best.startswith("Best subject: English")
    assert not any(x.startswith("Focus area: English") for x in rem)


def test_teacher_analysis_and_fair_check():
    from markstudio.teachers import analyse, normalise
    hy = ("Roll,Name,Section,English,Maths\n1,A One,A,80,60\n2,B Two,A,70,50\n"
          "1,C Three,B,60,62\n2,D Four,B,50,52\n")
    ds, res = run_csv(("Class X Half Yearly.csv", hy))
    cfg = ds.cfg
    ts = normalise([{"name": "Ms. Maths A", "subject": "Maths", "classes": "X-A"},
                    {"name": "Mr. Maths B", "subject": "041", "classes": "X-B"}], cfg)
    an = analyse(res, ts)
    a, b = an["cards"]
    assert a["classes"] == ["X-A"] and b["classes"] == ["X-B"]
    # marks out of 80: section A Maths is 12.5 below the students' own averages; section B 1.25 above
    assert a["overall"]["vs_own"] == Decimal("-12.5") and b["overall"]["vs_own"] == Decimal("1.25")
    # side by side, higher average first (B: 71.25% vs A: 68.75%) - even though A's students are stronger overall
    assert [r["name"] for r in an["comparison"][0]["rows"]] == ["Mr. Maths B", "Ms. Maths A"]


def test_ask_understands_every_class_and_new_questions():
    api.init()
    api.add_sample(False)
    api.analyze()
    cases = {
        "result of class 10": ("summary", "X"),
        "who topped class 6": ("top", "VI"),
        "section toppers class 12": ("toppers_by", "XII"),
        "weakest subject of class 9": ("hardest", "IX"),
        "who failed in class 10": ("list", "X"),
        "class 9 mein top 5 bachhe": ("top", "IX"),
        "students with distinction class 12": ("list", "XII"),
        "how many got A1 in class 11": ("count", "XI"),
        "which section is best in class 12": ("average", "XII"),
        "teacher wise result": ("teacher", None),
    }
    for q, (op, cls) in cases.items():
        out = json.loads(api.ask(q))
        assert out["ok"], q
        d = out["data"]
        assert "query" in d, (q, d)
        assert d["query"]["op"] == op, (q, d["query"])
        if cls:
            assert d["query"]["scope"].get("cls") == cls, (q, d["query"])
