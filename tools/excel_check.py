"""Full check in real Excel (needs desktop Excel on this PC):
1. builds a workbook from the sample data (with macros, a word-command chart, a highlight and a saved sheet),
2. lets Excel recalculate every formula and compares each answer with Python's,
3. runs the macros (recalculate, reset, save a report card as PDF),
4. does the same for the board workbook, using the made-up sample gazette.
Run: double-click tools\\check_excel.bat"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
OUT = os.path.join(ROOT, "out")
os.makedirs(OUT, exist_ok=True)

from markstudio.config import Config  # noqa: E402
from markstudio import sample, build, calc, verify, gazette, board  # noqa: E402
from markstudio.excel.school import write_workbook  # noqa: E402
from markstudio.excel.board_book import write_board_workbook  # noqa: E402


def ps(script, *args):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "tools", script)] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        print(r.stderr.strip())
    return r


def compare(a, b):
    r = subprocess.run([sys.executable, "-W", "ignore", os.path.join(ROOT, "tools", "compare_cached.py"), a, b],
                       capture_output=True, text=True)
    print(r.stdout.strip()[-3000:])
    return " 0 differ" in r.stdout


def main():
    cfg = Config()
    p = build.Project(cfg)
    for n, d in sample.sample_files(cfg, mistakes=True):
        p.add_file(n, d)
    ds = p.build()
    res = calc.compute(ds)
    print("Two independent calculations:", verify.check(ds, res))
    recipe = {"items": [
        {"type": "chart", "metric": "average", "by": "section", "filters": {"cls": "XI", "subject": "042", "exam": "YE"},
         "kind": "column", "title": "Physics average by section"},
        {"type": "highlight", "op": "<", "value": 40, "color": "red", "subject": None, "exam": None},
        {"type": "query_sheet", "sheet": "Top Ten", "title": "Top ten", "explanation": "test", "columns": ["Name", "%"],
         "rows": [["A", 90.5], ["B", 88]]}]}
    ours = os.path.join(OUT, "check_school.xlsm")
    with open(ours, "wb") as fh:
        from markstudio.teachers import normalise
        teachers = normalise(p.file_teachers, cfg, p.vocab)
        fh.write(write_workbook(ds, res, recipe=recipe, vba=True, teachers=teachers))
    excel = os.path.join(OUT, "check_school_excel.xlsm")
    ps("excel_recalc.ps1", "-In", ours, "-Out", excel)
    ok1 = compare(ours, excel)
    r = ps("excel_macro_test.ps1", "-In", ours)
    ok2 = "export ok" in r.stdout
    ok3 = True
    if True:
        t = sample.sample_gazette(cfg)
        an = board.analyse(gazette.parse(t, "gazette.txt"), cfg)
        b1 = os.path.join(OUT, "check_board.xlsx")
        with open(b1, "wb") as fh:
            fh.write(write_board_workbook([an], cfg, raw_texts=[("gazette.txt", t)]))
        b2 = os.path.join(OUT, "check_board_excel.xlsx")
        ps("excel_recalc.ps1", "-In", b1, "-Out", b2)
        ok3 = compare(b1, b2)
    print("\nRESULT:", "ALL GOOD" if ok1 and ok2 and ok3 else "PROBLEM - see above")
    return 0 if ok1 and ok2 and ok3 else 1


if __name__ == "__main__":
    sys.exit(main())
