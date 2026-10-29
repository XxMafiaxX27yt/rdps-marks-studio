"""Prints the failing phrasings of tools/ask_bank.py compactly, to review them by hand:
    python tools/ask_bank_review.py top_1,top_1_subject
Each line: the phrasing (blanks filled with the clear values) -> what the rules made of it."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ask_bank as ab  # noqa: E402


def main(ids):
    w = ab.World()
    phr = json.load(open(ab.PHRASINGS, encoding="utf-8"))
    rejected = json.load(open(ab.REJECTED, encoding="utf-8")) if os.path.exists(ab.REJECTED) else {}
    for tid, tpl in ab.TEMPLATES:
        if ids and tid not in ids:
            continue
        rnd = random.Random("review" + tid)
        slots = sorted(set(ab.slots_of(tpl)))
        vals = w.pick(rnd, slots)
        want = ab.key(ab.fill(tpl, vals, w.canon))
        bad = []
        for i, ph in enumerate(phr.get(tid, [])):
            if ph in rejected.get(tid, []):
                continue
            q = ab.fill(ph, vals, w.canon)
            got = ab.key(q)
            if got != want:
                bad.append((i, q, got))
        print(f"=== {tid}  want {ab.short(want)}   ({len(bad)} failing)")
        for i, q, got in bad:
            print(f"  {i:3} {q!r:70} -> {ab.short(got)[:90]}")


if __name__ == "__main__":
    main(set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None)
