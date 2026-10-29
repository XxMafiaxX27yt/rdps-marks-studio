"""RDPS colours and fonts - defined once and used by every sheet and chart
(the website uses the same values in web/css/theme.css)."""

BLUE = "#06A7E7"        # logo globe blue
NAVY = "#0B3C5D"        # headers, dark panels
TINT = "#E6F5FC"        # banding, card backgrounds
TINT2 = "#F3FAFE"
TEXT = "#1F2933"
MUTED = "#5B6B79"
LINE = "#C9E3F2"
WHITE = "#FFFFFF"
GREEN = "#1E8E5A"       # strong
GREEN_BG = "#E3F4EC"
AMBER = "#B7791F"       # weak
AMBER_BG = "#FDF3DC"
RED = "#C0392B"         # needs attention (used sparingly)
RED_BG = "#FBE5E2"
GREY_BG = "#EEF1F4"

# chart series colours (blue family first, status colours only for status)
SERIES = ["#06A7E7", "#0B3C5D", "#7FD0F2", "#3E7CA6", "#9DB4C7", "#F2A93B", "#5B6B79"]

FONT = "Calibri"
TITLE_FONT = "Segoe UI Semibold"
TITLE_FONT_LIGHT = "Segoe UI"

LABEL_COLORS = {
    "Strong": (GREEN, GREEN_BG),
    "On track": (TEXT, WHITE),
    "Weak": (AMBER, AMBER_BG),
    "Needs attention": (RED, RED_BG),
}


def gap_text(v, unit="marks"):
    """A difference in words, as on the website: '▼ 5.2 marks lower', '▲ 3.0% higher', '≈ about the same'."""
    if v is None:
        return "-"
    v = float(v)
    u = "%" if unit == "%" else " " + unit
    if abs(v) < 1:
        return "≈ about the same"
    return f"{'▲' if v > 0 else '▼'} {abs(v):.1f}{u} {'higher' if v > 0 else 'lower'}"


def range_text(lo, hi, unit="marks"):
    """'likely 1.0 to 6.0 marks higher' / 'likely between 2.0 lower and 6.0 higher'."""
    lo, hi = float(lo), float(hi)
    u = "%" if unit == "%" else " " + unit
    if lo >= 0:
        return f"likely {lo:.1f} to {hi:.1f}{u} higher"
    if hi <= 0:
        return f"likely {-hi:.1f} to {-lo:.1f}{u} lower"
    return f"likely between {-lo:.1f}{u} lower and {hi:.1f}{u} higher"


class Formats:
    """All cell formats of one workbook, created lazily."""

    def __init__(self, wb):
        self.wb = wb
        self._cache = {}

    def get(self, **kw):
        key = tuple(sorted(kw.items()))
        if key not in self._cache:
            base = {"font_name": FONT, "font_size": 10, "font_color": TEXT, "valign": "vcenter"}
            base.update(kw)
            self._cache[key] = self.wb.add_format(base)
        return self._cache[key]

    # common ones
    def title(self):
        return self.get(font_name=TITLE_FONT, font_size=18, font_color=NAVY)

    def subtitle(self):
        return self.get(font_name=TITLE_FONT_LIGHT, font_size=10, font_color=MUTED)

    def header(self, align="center"):
        return self.get(bold=True, font_color=WHITE, bg_color=NAVY, align=align, text_wrap=True,
                        border=1, border_color=NAVY)

    def cell(self, **kw):
        d = dict(border=1, border_color=LINE)
        d.update(kw)
        return self.get(**d)

    def num(self, places=1, **kw):
        d = dict(border=1, border_color=LINE, num_format="0." + "0" * places if places else "0", align="center")
        d.update(kw)
        return self.get(**d)

    def gap(self, unit="marks", **kw):
        """A difference shown in words while the cell keeps its number (formulas and charts still work):
        '▲ 5.0 marks higher' / '▼ 3.0 marks lower'; add about_same() for '≈ about the same' under 1."""
        u = "%" if unit == "%" else " " + unit
        d = dict(border=1, border_color=LINE, align="center",
                 num_format=f'"▲ "0.0"{u} higher";"▼ "0.0"{u} lower";"≈ about the same"')
        d.update(kw)
        return self.get(**d)

    def about_same(self, ws, r1, c1, r2, c2):
        """Anything under 1 either way reads '≈ about the same' (Excel shows a minus sign in a plain format)."""
        if "_same" not in self._cache:
            self._cache["_same"] = self.wb.add_format({"num_format": '"≈ about the same";"≈ about the same";"≈ about the same"',
                                                       "font_color": MUTED, "bold": False})
        ws.conditional_format(r1, c1, r2, c2, {"type": "cell", "criteria": "between", "minimum": -0.9999,
                                               "maximum": 0.9999, "format": self._cache["_same"]})

    def section(self):
        return self.get(font_name=TITLE_FONT, font_size=12, font_color=NAVY, bottom=2, bottom_color=BLUE)

    def note(self):
        """Small grey note on one line (no wrapping, so rows keep their height)."""
        return self.get(font_size=9, font_color=MUTED, italic=True)

    def note_wrap(self):
        return self.get(font_size=9, font_color=MUTED, italic=True, text_wrap=True, valign="top")

    def kpi_value(self):
        return self.get(font_name=TITLE_FONT, font_size=24, font_color=NAVY, align="center", bg_color=TINT,
                        num_format="General")

    def kpi_label(self):
        return self.get(font_size=9, font_color=MUTED, align="center", bg_color=TINT, bold=True)
