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
