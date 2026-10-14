"""Tests for reading, checking and calculating (spec section 14).
Run: double-click tools\\run_tests.bat  (or: python -m pytest tests)"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from markstudio.config import Config
from markstudio import build, calc, verify, views, gazette, board
from markstudio.textutil import r6

CSV = """Roll,Name,Father's Name,Class,Section,Physics Th,Physics Pr,Maths,English
1,Asha Rao,Ravi Rao,XI,A,56,25,60,70
2,Bilal Khan,Imran Khan,XI,A,20,10,32,40
3,Asha Rao,Mohan Rao,XI,A,63,28,0,
4,Chirag Jain,Anil Jain,XI,A,49.5,22,ML,66
"""


def project(text=CSV, name="Half Yearly XI.csv", cfg=None):
    cfg = cfg or Config()
    p = build.Project(cfg)
    p.add_file(name, text.encode())
    return p


def run(text=CSV, name="Half Yearly XI.csv"):
    p = project(text, name)
    assert p.pending() == [], p.pending()
    ds = p.build()
    res = calc.compute(ds)
    verify.check(ds, res)
    return p, ds, res


def by_name(ds, name, father=None):
    return [s for s in ds.students.values() if s.name == name and (father is None or s.father == father)][0]


def row(res, sid, subject, exam="HY"):
    er = res.exam_results[(sid, exam)]
    return next(r for r in er.rows if r.subject == subject)


# ---------------------------------------------------------------- reading
def test_normal_record_imports_correctly():
    p, ds, res = run()
    asha = by_name(ds, "Asha Rao", "Ravi Rao")
    assert asha.cls == "XI" and asha.section == "A" and asha.roll == "1"
    assert set(asha.subjects) == {"042", "041", "301"}
    r = row(res, asha.sid, "042")
    assert r.th == 56 and r.pr == 25 and r.obtained == 81 and r.max == 100 and r.pct == 81


def test_hand_calculated_values():
    p, ds, res = run()
    asha = by_name(ds, "Asha Rao", "Ravi Rao")
    er = res.exam_results[(asha.sid, "HY")]
    # Physics 81/100, Maths 60/80 = 75%, English 70/80 = 87.5%
    assert row(res, asha.sid, "041").pct == 75
    assert row(res, asha.sid, "301").pct == Decimal("87.5")
    own = (Decimal(81) + 75 + Decimal("87.5")) / 3
    assert row(res, asha.sid, "042").own_avg == own
    assert er.overall == r6(Decimal(211) / Decimal(260) * 100)      # 81.153846%
    # class average of Maths: Asha 75, Bilal 40, other Asha 0 (Chirag on ML) -> (75+40+0)/3
    assert row(res, asha.sid, "041").class_avg == (Decimal(75) + 40 + 0) / 3


def test_blank_and_zero_are_different():
    p = project()
    # the second Asha took English in PT1, so her blank English in the Half Yearly means absent
    p.add_file("PT1 XI.csv", b"Roll,Name,Father's Name,Class,Section,English\n3,Asha Rao,Mohan Rao,XI,A,30\n")
    ds = p.build()
    res = calc.compute(ds)
    verify.check(ds, res)
    asha2 = by_name(ds, "Asha Rao", "Mohan Rao")
    maths = row(res, asha2.sid, "041")
    assert maths.status == "OK" and maths.pct == 0 and maths.passed == "No"      # real zero
    eng = row(res, asha2.sid, "301")
    assert eng.status == "AB" and eng.pct is None and eng.passed == "No"           # blank = absent
    assert any(i.code == "blank_absent" and i.sid == asha2.sid for i in ds.issues)


def test_blank_in_subject_not_taken_is_ignored():
    p, ds, res = run()
    bilal = by_name(ds, "Bilal Khan")
    asha2 = by_name(ds, "Asha Rao", "Mohan Rao")
    assert "301" not in asha2.subjects                     # never has English marks -> does not take it
    assert len(res.exam_results[(asha2.sid, "HY")].rows) == 2


def test_same_name_students_stay_distinct():
    p, ds, res = run()
    ashas = [s for s in ds.students.values() if s.name == "Asha Rao"]
    assert len(ashas) == 2 and ashas[0].sid != ashas[1].sid
    assert any(i.code == "same_name" for i in ds.issues)


def test_medical_leave_is_not_absent():
    p, ds, res = run()
    ch = by_name(ds, "Chirag Jain")
    m = row(res, ch.sid, "041")
    assert m.status == "ML" and m.passed == "" and m.label == "Medical leave"
    er = res.exam_results[(ch.sid, "HY")]
    assert er.result == "Pass"                                 # ML does not count as not passed
    a2 = by_name(ds, "Asha Rao", "Mohan Rao")
    assert res.exam_results[(a2.sid, "HY")].result == "Not passed"


def test_decimal_marks_exact():
    p, ds, res = run()
    ch = by_name(ds, "Chirag Jain")
    r = row(res, ch.sid, "042")
    assert r.obtained == Decimal("71.5") and r.pct == Decimal("71.5")


def test_marks_above_maximum_flagged_and_not_used():
    text = CSV.replace("2,Bilal Khan,Imran Khan,XI,A,20,10,", "2,Bilal Khan,Imran Khan,XI,A,20,65,")
    p, ds, res = run(text)
    b = by_name(ds, "Bilal Khan")
    assert row(res, b.sid, "042").status == "INVALID"
    assert any(i.code == "invalid_mark" and "more than the maximum 30" in i.message for i in ds.issues)


def test_text_in_marks_is_flagged_not_guessed():
    text = CSV.replace(",60,70", ",6O,70")       # letter O typed instead of zero
    p, ds, res = run(text)
    a = by_name(ds, "Asha Rao", "Ravi Rao")
    r = row(res, a.sid, "041")
    assert r.status == "INVALID" and r.pct is None
    assert any(i.code == "invalid_mark" and "6O" in i.message for i in ds.issues)


def test_missing_practical_is_flagged():
    text = CSV.replace("1,Asha Rao,Ravi Rao,XI,A,56,25,", "1,Asha Rao,Ravi Rao,XI,A,56,,")
    p, ds, res = run(text)
    a = by_name(ds, "Asha Rao", "Ravi Rao")
    assert row(res, a.sid, "042").status == "INCOMPLETE"
    assert any(i.code == "missing_component" and i.sid == a.sid for i in ds.issues)


def test_missing_practical_column_is_flagged():
    text = "Roll,Name,Class,Section,Physics Th,Maths\n1,Asha Rao,XI,A,56,60\n"
    p, ds, res = run(text)
    assert any(i.code == "missing_component_column" for i in ds.issues)


def test_no_practical_needed_for_theory_only_subject():
    p, ds, res = run()
    a = by_name(ds, "Asha Rao", "Ravi Rao")
    r = row(res, a.sid, "041")
    assert r.pr_max == 0 and r.status == "OK"
    assert not any(i.code.startswith("missing") and i.subject == "041" for i in ds.issues)


def test_practical_for_subject_without_practical_is_an_error():
    text = "Roll,Name,Class,Section,Maths Th,Maths Pr\n1,Asha Rao,XI,A,56,20\n"
    p = project(text)
    for (sid, sh), lay in p.layouts.items():
        for c in lay["columns"]:
            c["sure"] = True
    ds = p.build()
    assert any(i.code == "practical_not_allowed" for i in ds.issues)


def test_periodic_test_has_no_practical():
    text = "Roll,Name,Class,Section,Physics,Maths\n1,Asha Rao,XI,A,38,40\n2,Bilal Khan,XI,A,41,12\n"
    p, ds, res = run(text, "PT1 class 11.csv")
    a = by_name(ds, "Asha Rao")
    r = row(res, a.sid, "042", "PT1")
    assert r.max == 40 and r.pct == 95
    b = by_name(ds, "Bilal Khan")
    assert row(res, b.sid, "042", "PT1").status == "INVALID"          # 41 > 40


def test_duplicate_roll_reported():
    text = CSV + "1,Dev Mehta,Ravi Mehta,XI,A,50,20,50,50\n"
    p, ds, res = run(text)
    assert any(i.code == "duplicate_id" for i in ds.issues)
    assert any(s.name == "Dev Mehta" for s in ds.students.values())       # not merged into Asha


def test_correction_updates_totals_and_keeps_original():
    p = project()
    ds = p.build()
    res = calc.compute(ds)
    a = by_name(ds, "Asha Rao", "Ravi Rao")
    before = res.exam_results[(a.sid, "HY")].overall
    m = next(m for m in ds.marks if m.sid == a.sid and m.subject == "041")
    key = build.ref_key(m.ref)
    p.correct(key, "70")
    ds2 = p.build()
    res2 = calc.compute(ds2)
    verify.check(ds2, res2)
    a2 = by_name(ds2, "Asha Rao", "Ravi Rao")
    after = res2.exam_results[(a2.sid, "HY")].overall
    assert after == r6(Decimal(221) / Decimal(260) * 100) and after != before
    m2 = next(m for m in ds2.marks if m.sid == a2.sid and m.subject == "041")
    assert m2.original == "60" and m2.raw == "70"
    assert any(i.code == "corrected" for i in ds2.issues)
    # the uploaded file itself is untouched
    assert p.sources[0].sheets[0].rows[1][7] == "60"


def test_different_subject_combinations_produce_correct_columns():
    text = ("Roll,Name,Class,Section,English,Accountancy,Business Studies,Economics,Physics Th,Physics Pr\n"
            "1,Asha Rao,XI,A,70,60,60,60,,\n2,Bilal Khan,XI,A,60,,,,50,20\n")
    p, ds, res = run(text)
    a, b = by_name(ds, "Asha Rao"), by_name(ds, "Bilal Khan")
    assert set(a.subjects) == {"301", "055", "054", "030"}
    assert set(b.subjects) == {"301", "042"}
    assert len(res.exam_results[(a.sid, "HY")].rows) == 4 and len(res.exam_results[(b.sid, "HY")].rows) == 2
    # Eng + Accts + BSt + Eco is Group D's core, but D also needs AI or PE -> no group, and it is reported
    assert a.group == "" and a.group_note


def test_swapped_columns_detected():
    text = ("Roll,Name,Class,Section,Physics Th,Physics Pr\n1,A One,XI,A,25,62\n2,B Two,XI,A,28,55\n3,C Three,XI,A,20,48\n")
    p, ds, res = run(text)
    sw = [i for i in ds.issues if i.code == "swapped_columns"]
    assert sw and sw[0].fix["type"] == "swap"
    p.swap_columns(sw[0].fix["source"], sw[0].fix["sheet"], *sw[0].fix["cols"])
    ds2 = p.build()
    res2 = calc.compute(ds2)
    a = by_name(ds2, "A One")
    assert row(res2, a.sid, "042").pct == 87


def test_file_total_mismatch_warned():
    text = "Roll,Name,Class,Section,Maths,English,Total\n1,Asha Rao,XI,A,60,70,140\n"
    p, ds, res = run(text)
    assert any(i.code == "file_total_mismatch" for i in ds.issues)


def test_labels_and_reasons():
    text = ("Roll,Name,Class,Section,English,Maths,Economics\n"
            "1,P One,XI,A,80,40,60\n2,P Two,XI,A,60,60,60\n3,P Three,XI,A,60,60,60\n")
    p, ds, res = run(text)
    s = by_name(ds, "P One")
    eng, maths, eco = row(res, s.sid, "301"), row(res, s.sid, "041"), row(res, s.sid, "030")
    # P One: English 100%, Maths 50%, Economics 75% -> own average 75
    # Maths class average = (50 + 75 + 75) / 3 = 66.67 -> 16.67 below = needs attention (beats "weak")
    assert eng.label == "Strong"
    assert maths.label == "Needs attention"
    assert maths.reason == "Mathematics: 25.0 points below your average and 16.7 below the class average."
    assert eco.label == "On track"
    s2 = by_name(ds, "P Two")
    # English 75% vs class average 83.33 -> 8.3 below (less than 10), own average 75 -> on track
    assert row(res, s2.sid, "301").label == "On track"


def test_label_rules_follow_settings():
    cfg = Config()
    cfg.rules["attention_class_gap"] = 20
    text = ("Roll,Name,Class,Section,English,Maths,Economics\n"
            "1,P One,XI,A,80,40,60\n2,P Two,XI,A,60,60,60\n3,P Three,XI,A,60,60,60\n")
    p = project(text, cfg=cfg)
    ds = p.build()
    res = calc.compute(ds)
    s = by_name(ds, "P One")
    assert row(res, s.sid, "041").label == "Weak"          # 16.7 below class is no longer enough for attention


def test_pass_each_part_separately():
    text = "Roll,Name,Class,Section,Physics Th,Physics Pr\n1,A One,XI,A,20,30\n"
    p, ds, res = run(text)
    a = by_name(ds, "A One")
    r = row(res, a.sid, "042")
    # 50/100 overall, but theory 20/70 = 28.6% is below 33% -> not passed
    assert r.pct == 50 and r.passed == "No" and r.label == "Needs attention"


def test_gazette_parses_and_checks_counts():
    text = """DATE:- 13-05-2025    C.B.S.E. - SENIOR SCHOOL CERTIFICATE EXAMINATION (MAIN)-2025      REGION: SAMPLE         PAGE:-       1
                                                ***** (SCHOOL / ROLL NO WISE GAZETTE) *****
SCHOOL : - 99999   TEST SCHOOL DELHI
11111111   F ANYA ROY                                            301     041     042     043     048              A1 A1 B1    PASS
                                                                 081  B1 062  B2 058  C1 066  B2 077  B1
11111112   M KARAN DEV                                           301     030     041     054     055     048      A1 A1 A1    COMP               041
                                                                 091  A2 082  B1 028  E  067  B1 064  C1 070  C1
TOTAL CANDIDATES :     2 TOTAL PASS :     1 TOTAL COMPTT. :     1 TOTAL ESSENTIAL REPEAT :     0 TOTAL ABSENT :     0
"""
    g = gazette.parse(text, "g.txt")
    assert len(g.students) == 2 and g.year == "2025" and g.cls == "XII"
    assert any(i.code == "gazette_count_ok" for i in g.issues)
    k = g.students[1]
    assert k.gender == "M" and k.result == "COMP" and k.comp == ["041"] and len(k.subjects) == 6
    an = board.analyse(g, Config())
    r = next(x for x in an["rows"] if x["s"].roll == "11111111")
    assert r["best5"] == Decimal(81 + 62 + 58 + 66 + 77) / 5
    r2 = next(x for x in an["rows"] if x["s"].roll == "11111112")
    # English 91 + best four of 82, 28, 67, 64, 70 -> 82 + 70 + 67 + 64
    assert r2["best5"] == Decimal(91 + 82 + 70 + 67 + 64) / 5


def test_gazette_missing_student_detected():
    text = """C.B.S.E. - SENIOR SCHOOL CERTIFICATE EXAMINATION (MAIN)-2025 GAZETTE
11111111   F ANYA ROY                                            301     041     042     043     048              A1 A1 B1    PASS
                                                                 081  B1 062  B2 058  C1 066  B2 077  B1
TOTAL CANDIDATES :     2 TOTAL PASS :     2 TOTAL COMPTT. :     0
"""
    g = gazette.parse(text, "g.txt")
    assert any(i.code == "gazette_count_mismatch" for i in g.issues)


def test_made_up_gazette_full_size():
    """A full made-up gazette (fake school, fake names) reads completely and matches its own totals."""
    from markstudio import sample
    g = gazette.parse(sample.sample_gazette(Config()), "sample.txt")
    assert len(g.students) == 60 == g.totals["candidates"]
    assert not [i for i in g.issues if i.severity == "error"]
    an = board.analyse(g, Config())
    assert an["passed"] == g.totals["pass"] and an["comp"] == g.totals["comp"] == 2


def test_pdf_table_with_left_headings_and_right_numbers():
    """Excel-made PDFs put headings on the left of a cell and numbers on the right."""
    from markstudio.readers import grid_from_words
    W = lambda t, x0, x1, y: {"text": t, "x0": x0, "x1": x1, "y0": y, "y1": y + 11}
    words = [W("Roll", 52.8, 69.7, 83), W("Student Name", 103, 167.5, 83), W("English", 208.2, 239.7, 83),
             W("Maths", 258.4, 287, 83), W("Physics Th", 308.6, 354.7, 83), W("Physics Pr", 358.7, 403.2, 83)]
    for i, (n, a, b, c, d) in enumerate([("Asha Rao", "55", "72", "64", "20"), ("Bilal Khan", "70", "75", "67", "19")]):
        y = 98 + i * 14.5
        words += [W(str(i + 1), 93.5, 99.1, y), W(n, 103, 147, y), W(a, 243.3, 254.5, y), W(b, 293.5, 304.7, y),
                  W(c, 343.6, 354.8, y), W(d, 393.8, 405, y)]
    grid = grid_from_words(words, join_words=False)
    assert grid[0] == ["Roll", "Student Name", "English", "Maths", "Physics Th", "Physics Pr"]
    assert grid[1] == ["1", "Asha Rao", "55", "72", "64", "20"]


def test_sample_data_full_pipeline_verifies():
    from markstudio import sample
    cfg = Config()
    p = build.Project(cfg)
    for n, d in sample.sample_files(cfg, mistakes=True):
        p.add_file(n, d)
    assert p.pending() == []
    ds = p.build()
    res = calc.compute(ds)
    out = verify.check(ds, res)
    assert out["ok"] and len(ds.students) == 224
    codes = {i.code for i in ds.issues if i.severity == "error"}
    assert codes == {"invalid_mark"}

