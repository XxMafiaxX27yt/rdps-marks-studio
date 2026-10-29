"""Small text helpers: cleaning words, fuzzy matching, reading numbers safely."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache

_SPACES = re.compile(r"\s+")


def clean(text):
    """Trim and squash spaces. None -> ''."""
    if text is None:
        return ""
    return _SPACES.sub(" ", str(text).replace(" ", " ")).strip()


def norm(text):
    """Lower-case, keep letters/digits, single spaces: 'Phy. (Th)' -> 'phy th'."""
    t = clean(text).lower()
    t = re.sub(r"[^0-9a-zऀ-ॿ]+", " ", t)
    return _SPACES.sub(" ", t).strip()


def norm_name(text):
    """Person names compared without dots, case or extra spaces."""
    return norm(text)


def tokens(text):
    return norm(text).split()


# ---------------------------------------------------------------- fuzzy
def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def jaro_winkler(a, b):
    """Similarity 0..1 that forgives small typos (good for names)."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    rng = max(la, lb) // 2 - 1
    am = [False] * la
    bm = [False] * lb
    matches = 0
    for i in range(la):
        lo, hi = max(0, i - rng), min(i + rng + 1, lb)
        for j in range(lo, hi):
            if not bm[j] and a[i] == b[j]:
                am[i] = bm[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t = 0
    k = 0
    for i in range(la):
        if am[i]:
            while not bm[k]:
                k += 1
            if a[i] != b[k]:
                t += 1
            k += 1
    t /= 2
    jaro = (matches / la + matches / lb + (matches - t) / matches) / 3
    prefix = 0
    for i in range(min(4, la, lb)):
        if a[i] == b[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)


@lru_cache(maxsize=300000)          # the same word pairs come up again and again (every name, every question)
def similar(a, b):
    """Typo-tolerant word equality. Short words must match exactly."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    if len(a) >= 5 and levenshtein(a, b) <= 1:
        return True
    return jaro_winkler(a, b) >= 0.92


# ---------------------------------------------------------------- numbers
_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def parse_number(raw):
    """Read a mark exactly. Returns Decimal or None if it is not a plain number.
    '38' -> 38, '37.5' -> 37.5, '038' -> 38, '38 ' -> 38, '3 8' -> None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        # Excel stores numbers as floats; 37.5 is exact, 37.1 becomes 37.1000000001.
        # repr() gives the shortest text that round-trips, so it is the number the teacher typed.
        return Decimal(repr(raw))
    if isinstance(raw, Decimal):
        return raw
    t = clean(raw)
    if not _NUM.match(t):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def fmt_num(d, places=1):
    """Decimal -> '12.5' style text, rounding half away from zero like Excel."""
    if d is None:
        return ""
    q = Decimal(1).scaleb(-places) if places else Decimal(1)
    v = Decimal(d).quantize(q, rounding=ROUND_HALF_UP)
    if v == 0:
        v = abs(v)
    return format(v, "f")


def fmt_mark(d):
    """Marks print without useless '.0': 38 -> '38', 37.5 -> '37.5'."""
    if d is None:
        return ""
    d = Decimal(d)
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def r6(d):
    """Round to 6 decimals (half away from zero) - used for every comparison so the
    website and Excel's formulas always agree on borderline values."""
    if d is None:
        return None
    return Decimal(d).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- excel safety
def formula_like(text):
    """Text from an uploaded file must never run as an Excel formula.
    The workbook writer stores every uploaded text with write_string (never as a
    formula) and gives cells starting with = + - @ Excel's hidden quote prefix,
    so they stay plain text even if someone re-types or exports them."""
    t = "" if text is None else str(text)
    return bool(t) and t[0] in "=+-@\t\r"


def col_letter(index):
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    s = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
