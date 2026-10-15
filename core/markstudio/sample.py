"""Realistic made-up students and marks (no real child is in here). Used for the
website's "Try sample data" button, for the demo and for the tests."""
import random
from decimal import Decimal

from .excel.template import template_bytes

FIRST_F = ["Aanya", "Ishita", "Diya", "Saanvi", "Myra", "Kavya", "Riya", "Anika", "Tanvi", "Navya", "Aditi", "Sara",
           "Meher", "Nandini", "Prisha", "Khushi", "Vanshika", "Avni", "Pari", "Jiya", "Mahika", "Siya", "Ira", "Kiara",
           "Shreya", "Muskan", "Simran", "Tanya", "Ritika", "Naina"]
FIRST_M = ["Aarav", "Vivaan", "Aditya", "Arjun", "Reyansh", "Krish", "Ishaan", "Kabir", "Vihaan", "Ayaan", "Dhruv",
           "Rohan", "Kartik", "Yash", "Aryan", "Pranav", "Rudra", "Shaurya", "Atharv", "Laksh", "Arnav", "Daksh",
           "Parth", "Om", "Rishabh", "Sahil", "Tanish", "Harsh", "Manan", "Veer"]
LAST = ["Agarwal", "Kapoor", "Malhotra", "Sethi", "Tandon", "Ahuja", "Chopra", "Rastogi", "Sinha", "Mishra", "Pandey", "Tiwari", "Kulkarni", "Iyer", "Menon", "Nair", "Rao", "Reddy", "Pillai", "Desai", "Bose", "Sen", "Das", "Chatterjee", "Banerjee", "Ghosh", "Mukherjee", "Patil", "Shetty", "Hegde"]
FATHER = ["Rajesh", "Sanjay", "Amit", "Sunil", "Vikas", "Manoj", "Rakesh", "Ajay", "Deepak", "Anil", "Pankaj", "Vinod",
          "Ashok", "Naveen", "Sandeep", "Rahul", "Alok", "Mukesh", "Hemant", "Pradeep"]
MOTHER = ["Sunita", "Neha", "Pooja", "Anjali", "Rekha", "Seema", "Kavita", "Ritu", "Meenakshi", "Shalini", "Priya",
          "Monika", "Nidhi", "Swati", "Archana", "Geeta", "Shweta", "Jyoti", "Payal", "Vandana"]

# section -> group mix, like the school: A = PCM, B = PCM / PCB / PCMB, C = Commerce with Maths,
# D = Commerce without Maths, E = Humanities
SECTIONS = {"A": ["A"], "B": ["B"] * 4 + ["A"], "C": ["C"], "D": ["D"], "E": ["E"]}
JUNIOR_SECTIONS = ["A", "B"]
SAMPLE_CLASSES = ["VI", "IX", "X", "XI", "XII"]
# which sample classes come with internal marks (the others show "marks only")
WITH_INTERNALS = {"VI", "IX"}


def _subjects_for(group, rnd, cfg):
    g = next(x for x in cfg.groups if x["id"] == group)
    subs = list(g["core"])
    for ch in g.get("choices", []):
        opts = [c for c in ch if c not in subs]
        subs.append(rnd.choice(opts))
    return cfg.order_subjects(subs)


def _level(v):
    # soft ceiling: very strong students get high marks, but rarely a perfect score
    if v > 0.85:
        v = 0.85 + (v - 0.85) * 0.5
    return max(0.08, min(0.99, v))


def make_class(cfg, cls, seed=7, per_section=None, mistakes=False, internals=None):
    """-> (students, marks) in the template's shape."""
    rnd = random.Random(seed + cfg.class_level(cls) * 11)
    streams = cfg.has_streams(cls)
    per_section = per_section or (22 if streams else 24)
    internals = (cls in WITH_INTERNALS) if internals is None else internals
    students, marks = [], {}
    adm = 1000 + cfg.class_level(cls) * 300
    used = set()
    langs = cfg.languages_for(cls)
    offer = cfg.class_offer(cls)
    for sec, groups in (SECTIONS.items() if streams else [(s, None) for s in JUNIOR_SECTIONS]):
        for i in range(per_section):
            girl = rnd.random() < 0.48
            while True:
                first = rnd.choice(FIRST_F if girl else FIRST_M)
                last = rnd.choice(LAST)
                if (first, last) not in used:
                    used.add((first, last))
                    break
            adm += rnd.randint(1, 4)
            if streams:
                group = rnd.choice(groups)
                subs = _subjects_for(group, rnd, cfg)
                lang = ""
            else:
                group = ""
                lang = rnd.choice(langs) if langs else ""
                if cls == "X" and rnd.random() < 0.6:
                    lang = "302"                                         # Hindi or a foreign language
                subs = cfg.order_subjects(set(offer["subjects"]) | ({lang} if lang else set()))
            st = {"adm_no": str(adm), "roll": str(i + 1), "name": f"{first} {last}",
                  "father": f"{rnd.choice(FATHER)} {last}", "mother": f"{rnd.choice(MOTHER)} {last}",
                  "section": sec, "group": group, "subjects": subs, "gender": "F" if girl else "M", "language": lang}
            if cls in ("X", "XII"):
                st["board_roll"] = str(99100000 + cfg.class_level(cls) * 1000 + len(students) * 3 + rnd.randint(0, 2))
            students.append(st)
            ability = rnd.gauss(0.70, 0.12)
            trend = rnd.gauss(0.0, 0.025)
            flair = {s: rnd.gauss(0, 0.07) for s in subs}
            for ei, ex in enumerate(cfg.class_exams(cls)):
                for s in subs:
                    sc = cfg.scheme(cls, s, ex)
                    if not sc:
                        continue
                    level = ability + flair[s] + trend * ei + rnd.gauss(0, 0.05)
                    mx = float(sc["theory"])
                    lv = _level(level)
                    val = round(mx * lv * 2) / 2 if mx >= 70 else round(mx * lv)
                    marks[(st["adm_no"], ex, s, "theory")] = _txt(max(0, min(mx, val)))
                    second = sc["second"]
                    if second and not second["parts"]:
                        pm = float(second["max"])
                        marks[(st["adm_no"], ex, s, "practical")] = _txt(max(0, min(pm, round(pm * _level(level + 0.10)))))
                    elif second and internals:
                        for key, pmx in second["parts"]:
                            if key == "i_pt":
                                continue
                            pm = float(pmx)
                            marks[(st["adm_no"], ex, s, key)] = _txt(max(0, min(pm, round(pm * _level(level + 0.12)))))
                # a few absences / leaves
                if rnd.random() < 0.03:
                    s = rnd.choice(subs)
                    for comp in cfg.components(cls, s, ex):
                        marks[(st["adm_no"], ex, s, comp)] = "AB"
                if rnd.random() < 0.015:
                    s = rnd.choice(subs)
                    for comp in cfg.components(cls, s, ex):
                        marks[(st["adm_no"], ex, s, comp)] = "ML"
    if mistakes and streams:
        _plant_mistakes(cfg, cls, students, marks, rnd)
    return students, marks


def sample_teachers(cfg, cls):
    """Made-up teachers for the sample classes (names are invented)."""
    T = {
        "VI": [("Ms. Kavita Anand", "301", "VI-A, VI-B"), ("Mr. Rohit Bhalla", "041", "VI-A"), ("Ms. Neha Gupta", "041", "VI-B"),
               ("Ms. Ritu Saxena", "086", "VI-A, VI-B"), ("Mr. Ajay Kohli", "087", "VI-A, VI-B"), ("Ms. Pooja Arora", "302", "VI-A, VI-B")],
        "IX": [("Ms. Shalini Batra", "301", "IX-A, IX-B"), ("Mr. Vinod Chawla", "041", "IX-A, IX-B"),
               ("Ms. Anjali Dua", "086", "IX-A"), ("Mr. Sanjay Garg", "086", "IX-B"), ("Ms. Monika Jain", "843", "IX-A, IX-B")],
        "X": [("Ms. Shalini Batra", "301", "X-A, X-B"), ("Mr. Vinod Chawla", "041", "X-A"), ("Mr. Manoj Khanna", "041", "X-B"),
              ("Mr. Sanjay Garg", "086", "X-A, X-B"), ("Ms. Rekha Luthra", "087", "X-A, X-B")],
        "XI": [("Mr. Amit Verma", "042", "XI-A, XI-B"), ("Ms. Sunita Rao", "043", "XI-A"), ("Mr. Deepak Sethi", "043", "XI-B"),
               ("Ms. Nidhi Kapoor", "041", "XI-A, XI-B, XI-C"), ("Ms. Swati Menon", "301", "XI-A, XI-B, XI-C, XI-D, XI-E"),
               ("Mr. Alok Tandon", "055", "XI-C, XI-D"), ("Ms. Geeta Pillai", "030", "XI-C, XI-D, XI-E")],
        "XII": [("Mr. Amit Verma", "042", "XII-A"), ("Ms. Priya Desai", "042", "XII-B"), ("Ms. Sunita Rao", "043", "XII-A, XII-B"),
                ("Mr. Rahul Nair", "041", "XII-A, XII-B, XII-C"), ("Ms. Archana Iyer", "301", "XII-A, XII-B, XII-C, XII-D, XII-E"),
                ("Mr. Alok Tandon", "055", "XII-C, XII-D"), ("Ms. Vandana Shetty", "028", "XII-E")],
    }
    return [{"name": n, "subject": s, "classes": c} for n, s, c in T.get(cls, [])]


def _txt(v):
    return str(int(v)) if float(v) == int(v) else str(v)


def _plant_mistakes(cfg, cls, students, marks, rnd):
    """Typical real-world slips, so the check screen has something to show."""
    hy = "HY"
    sci = [s for s in students if "042" in s["subjects"]]
    if sci:
        s = sci[0]
        marks[(s["adm_no"], hy, "042", "practical")] = "65"           # 65 in a /30 practical
        s2 = sci[3]
        marks[(s2["adm_no"], "PT1", "043", "theory")] = "4O"           # letter O instead of zero
    s3 = students[5]
    sub = s3["subjects"][1]
    marks[(s3["adm_no"], "PT2", sub, "theory")] = "45"                 # over 40 in a PT
    s4 = students[9]
    sub = s4["subjects"][0]
    marks[(s4["adm_no"], hy, sub, "theory")] = ""                      # blank -> absent


def sample_files(cfg, mistakes=False):
    """-> list of (file name, bytes): one workbook per class in the template layout."""
    out = []
    for cls in SAMPLE_CLASSES:
        students, marks = make_class(cfg, cls, mistakes=mistakes)
        data = template_bytes(cfg, cls, students, marks, exams=cfg.class_exams(cls),
                              title_note="(sample data - made-up students)", teachers=sample_teachers(cfg, cls))
        out.append((f"Sample {cfg.class_label(cls)} marks{' (with mistakes)' if mistakes else ''}.xlsx", data))
    return out


def sample_gazette(cfg, seed=5, n=60):
    """A made-up CBSE-style result gazette (fake school 99999, fake names, fake roll numbers 99xxxxxx)
    for trying the Board results page and for the tests."""
    rnd = random.Random(seed)
    combos = {"A": ["301", "041", "042", "043", "048"], "B": ["301", "042", "043", "044", "048"],
              "C": ["301", "030", "041", "054", "055"], "D": ["301", "030", "048", "054", "055"],
              "E": ["301", "028", "030", "037", "048"]}
    head = ("DATE:- 01-05-2025    C.B.S.E. - SENIOR SCHOOL CERTIFICATE EXAMINATION (MAIN)-2025      "
            "REGION: SAMPLE         PAGE:-       1\n"
            "                                                ***** (SCHOOL / ROLL NO WISE GAZETTE) *****\n\n"
            "SCHOOL : - 99999   SAMPLE PUBLIC SCHOOL (MADE-UP DATA)\n")
    lines, used, passed, comp = [head], set(), 0, 0
    grades = ["A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2"]
    for i in range(n):
        girl = rnd.random() < 0.5
        while True:
            name = f"{rnd.choice(FIRST_F if girl else FIRST_M)} {rnd.choice(LAST)}".upper()
            if name not in used:
                used.add(name)
                break
        codes = list(combos[rnd.choice("AABCCDE")])
        if rnd.random() < 0.25:
            codes.append("083" if "083" not in codes else "065")
        ability = rnd.gauss(0.78, 0.11)
        marks = [max(18, min(99, int(round(100 * (ability + rnd.gauss(0, 0.07)))))) for _ in codes]
        res = "PASS"
        if i in (17, 41):
            marks[2] = rnd.randint(20, 31)
            res = "COMP"
        gr = ["E" if m < 33 else grades[min(7, max(0, (95 - m) // 6))] for m in marks]
        comp_code = codes[2] if res == "COMP" else ""
        passed += res == "PASS"
        comp += res == "COMP"
        roll = str(99000001 + i)
        l1 = (f"{roll}   {'F' if girl else 'M'} {name:<52}" + "".join(f"{c:<8}" for c in codes).ljust(48)
              + "A1 A1 A2    " + f"{res:<19}{comp_code}")
        l2 = " " * 65 + "".join(f"{m:03d}  {g:<3}" for m, g in zip(marks, gr))
        lines += [l1.rstrip(), l2.rstrip()]
    lines.append(f"\nTOTAL CANDIDATES :   {n} TOTAL PASS :   {passed} TOTAL COMPTT. :     {comp} "
                 f"TOTAL ESSENTIAL REPEAT :     0 TOTAL ABSENT :     0")
    return "\n".join(lines) + "\n"
