"""Works out a student's group (A-E) from the subjects they take, using the
subject-combination table in config/groups.json."""


def match_groups(subjects, groups):
    """Return [(group_id, score, extra_subjects)] for every group the subjects fit.
    A fit = all core subjects present + one subject from each choice list
    (+ at most one additional subject)."""
    s = set(subjects)
    fits = []
    for g in groups:
        core = set(g["core"])
        if not core <= s:
            continue
        left = s - core
        used = set()
        ok = True
        for choice in g.get("choices", []):
            pick = [c for c in choice if c in left and c not in used]
            if not pick:
                ok = False
                break
            used.add(pick[0])
        if not ok:
            continue
        extra = left - used
        if len(extra) > 1:
            continue
        fits.append((g["id"], len(core), sorted(extra)))
    return fits


def infer_group(subjects, groups, given=""):
    """-> (group_id, note). given = the group written in the file (checked, not trusted blindly)."""
    fits = match_groups(subjects, groups)
    ids = [f[0] for f in fits]
    names = {g["id"]: g["name"] for g in groups}
    if given:
        if given in ids:
            return given, ""
        if not subjects:
            return given, ""
        return given, (f"The file says Group {given} but the subjects fit "
                       f"{'Group ' + ' / '.join(ids) if ids else 'no group in the subject table'}")
    if not fits:
        return "", "Subject combination does not match any group in the table" if subjects else ""
    if len(fits) == 1:
        return fits[0][0], ""
    # several fit (e.g. Eng+Maths+Phy+Chem+PE fits A and B): prefer the group whose
    # core list explains more of the subjects
    fits.sort(key=lambda f: (-f[1], len(f[2]), f[0]))
    if fits[0][1] > fits[1][1]:
        return fits[0][0], f"Also fits Group {', '.join(f[0] for f in fits[1:])}; chose {names.get(fits[0][0], fits[0][0])}"
    return fits[0][0], f"Fits groups {' / '.join(ids)} equally - chose {fits[0][0]}; add a Group column to be exact"
