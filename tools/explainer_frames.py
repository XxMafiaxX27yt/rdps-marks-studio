"""Draws the frames of the explainer videos with Pillow (no browser): the same pieces the website uses -
chips, boxes, arrows, bars, little tables and counting numbers - in the school colours, 1280x720.

Used by make_explainer_media.py. Everything is drawn at 2x and scaled down, so edges are smooth."""
import math
import os
import re
from html.parser import HTMLParser

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, SS = 1280, 720, 2
FONTS = r"C:\Windows\Fonts"

C = {"navy": (11, 60, 93), "blue": (6, 167, 231), "blue2": (5, 144, 200), "tint": (230, 245, 252), "tint2": (243, 250, 254),
     "line": (220, 234, 243), "line2": (201, 227, 242), "text": (31, 41, 51), "muted": (91, 107, 121), "card": (255, 255, 255),
     "green": (30, 142, 90), "greenbg": (227, 244, 236), "amber": (183, 121, 31), "amberbg": (253, 243, 220),
     "red": (192, 57, 43), "light": (127, 216, 250)}
CSSVAR = {"var(--green)": C["green"], "var(--amber)": C["amber"], "var(--red)": C["red"]}


def px(v):
    return int(round(v * SS))


_fc = {}


def font(kind, size):
    key = (kind, size)
    if key not in _fc:
        name = {"reg": "segoeui.ttf", "semi": "seguisb.ttf", "bold": "segoeuib.ttf", "sym": "seguisym.ttf",
                "emoji": "seguiemj.ttf"}[kind]
        _fc[key] = ImageFont.truetype(os.path.join(FONTS, name), px(size))
    return _fc[key]


SYMBOLS = set("→✓✕✗·…▲▼❚▶◀←↑↓×÷−✔")


def runs(text, kind, size):
    """Split text into pieces that each use one font (letters / symbols / emoji)."""
    out, cur, cf = [], "", None
    for ch in text:
        if ord(ch) >= 0x1F000 or ch in "⭐":
            f = ("emoji", size)
        elif ch in SYMBOLS:
            f = ("sym", size)
        else:
            f = (kind, size)
        if f != cf and cur:
            out.append((cur, cf))
            cur = ""
        cf = f
        cur += ch
    if cur:
        out.append((cur, cf))
    return out


def text_w(text, kind, size):
    return sum(font(*f).getlength(t) for t, f in runs(text, kind, size)) / SS


def draw_text(d, x, y, text, kind, size, fill):
    """x, y = top-left in 1x units; y is the top of the line box."""
    asc = font(kind, size).getmetrics()[0]
    cx = px(x)
    for t, f in runs(text, kind, size):
        fo = font(*f)
        off = asc - fo.getmetrics()[0]
        if f[0] == "emoji":
            d.text((cx, px(y) + off), t, font=fo, embedded_color=True)
        else:
            d.text((cx, px(y) + off), t, font=fo, fill=fill)
        cx += fo.getlength(t)


def line_h(size):
    a, b = font("reg", size).getmetrics()
    return (a + b) / SS


def rrect(d, box, r, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = box
    d.rounded_rectangle([px(x0), px(y0), px(x1), px(y1)], radius=px(r), fill=fill, outline=outline,
                        width=max(1, px(width)) if outline else 0)


def mix(a, b, k):
    return tuple(int(round(a[i] * (1 - k) + b[i] * k)) for i in range(3))


def ease_out(k):
    return 1 - (1 - k) ** 3


def ease_back(k):
    s = 0.9
    k -= 1
    return k * k * ((s + 1) * k + s) + 1


# ---------------------------------------------------------------- reading the visuals (tiny HTML)
class Node:
    def __init__(self, tag, attrs):
        self.tag, self.cls = tag, (attrs.get("class") or "").split()
        self.style, self.data = attrs.get("style") or "", {k: v for k, v in attrs.items() if k.startswith("data-")}
        self.kids = []

    def text(self):
        return "".join(k if isinstance(k, str) else k.text() for k in self.kids)


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = Node(tag, dict(attrs))
        self.stack[-1].kids.append(n)
        if tag != "br":
            self.stack.append(n)

    def handle_endtag(self, tag):
        if tag == "br":
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data:
            self.stack[-1].kids.append(data)


def parse(html):
    p = Parser()
    p.feed(html)
    return p.root


# ---------------------------------------------------------------- pieces
class Piece:
    delay = 0.0
    anim = True

    def size(self):
        return self.w, self.h


class Chip(Piece):
    def __init__(self, text, cls, F):
        self.t, self.cls, self.F = text.strip(), cls, F
        self.fs = 14 * F
        self.w = text_w(self.t, "semi", self.fs) + 24 * F
        self.h = line_h(self.fs) + 8 * F

    def draw(self, d, x, y, t, layer):
        F, cls = self.F, self.cls
        bg, fg, bd = C["card"], C["navy"], C["line2"]
        if "ok" in cls:
            bg, fg, bd = C["greenbg"], C["green"], None
        elif "warn" in cls:
            bg, fg, bd = C["amberbg"], C["amber"], None
        elif "muted" in cls:
            fg, bd = C["muted"], C["line2"]
        if "pulse" in cls:
            k = (math.sin((t % 1.4) / 1.4 * 2 * math.pi - math.pi / 2) + 1) / 2
            g = int(6 * F * k)
            if g:
                rrect(layer, (x - g, y - g, x + self.w + g, y + self.h + g), self.h / 2 + g,
                      fill=mix(C["card"], C["amber"], 0.25) + (int(255 * 0.6),))
        rrect(d, (x, y, x + self.w, y + self.h), self.h / 2, fill=bg, outline=bd, width=1)
        draw_text(d, x + 12 * F, y + 4 * F, self.t, "semi", self.fs, fg)


class Arrow(Piece):
    def __init__(self, F):
        self.F, self.fs = F, 21 * F
        self.w, self.h = text_w("→", "sym", self.fs), line_h(self.fs)

    def draw(self, d, x, y, t, layer):
        draw_text(d, x, y, "→", "bold", self.fs, C["blue"])


class Cross(Piece):
    def __init__(self, text, F):
        self.t, self.F, self.fs = text.strip(), F, 15 * F
        self.w, self.h = text_w(self.t, "bold", self.fs), line_h(self.fs)

    def draw(self, d, x, y, t, layer):
        draw_text(d, x, y, self.t, "bold", self.fs, C["red"])
        d.line([px(x), px(y + self.h * 0.55), px(x + self.w), px(y + self.h * 0.55)], fill=C["red"], width=px(2))


class Box(Piece):
    """Rounded card with lines of text; <b class=ex-num> counts up, <small> is a small caption."""
    def __init__(self, node, F):
        self.F, self.cls = F, node.cls
        big = "big" in node.cls
        self.base = (20 if big else 15) * F
        lines, cur = [], []
        for k in node.kids:
            if isinstance(k, str):
                if k.strip() or cur:
                    cur.append(("t", k))
            elif k.tag == "br":
                lines.append(cur)
                cur = []
            elif "ex-num" in k.cls:
                cur.append(("num", (float(k.data.get("data-count", "0")), int(k.data.get("data-places", "0")))))
            elif k.tag == "small":
                cur.append(("small", k.text()))
            else:
                cur.append(("t", k.text()))
        lines.append(cur)
        self.lines = [ln for ln in lines if ln]
        self.metrics = []
        for ln in self.lines:
            w = sum(self._w(r) for r in ln)
            h = max(self._h(r) for r in ln)
            self.metrics.append((w, h))
        self.w = max(m[0] for m in self.metrics) + 32 * F
        self.h = sum(m[1] for m in self.metrics) + 24 * F

    def _fmt(self, v, p):
        return f"{v:,.{p}f}"

    def _w(self, r):
        k, v = r
        if k == "num":
            return text_w(self._fmt(v[0], v[1]), "bold", 21.6 * self.F)
        if k == "small":
            return text_w(v.upper(), "bold", 11.5 * self.F)
        return text_w(v, "semi", self.base)

    def _h(self, r):
        k = r[0]
        return line_h(21.6 * self.F) if k == "num" else (line_h(11.5 * self.F) if k == "small" else line_h(self.base))

    def draw(self, d, x, y, t, layer):
        F = self.F
        bd, fg = C["line"], C["navy"]
        if "pop" in self.cls:
            bd = C["blue"]
            rrect(layer, (x - 4 * F, y - 4 * F, x + self.w + 4 * F, y + self.h + 4 * F), 18 * F,
                  fill=mix(C["card"], C["blue"], 0.16) + (255,))
        if "good" in self.cls:
            fg, bd = C["green"], C["green"]
        rrect(d, (x, y, x + self.w, y + self.h), 14 * F, fill=C["card"], outline=bd, width=1.2)
        cy = y + 12 * F
        k = min(1.0, t / 0.9)
        e = 1 - (1 - k) ** 3
        for ln, (lw, lh) in zip(self.lines, self.metrics):
            cx = x + (self.w - lw) / 2
            for kind, v in ln:
                if kind == "num":
                    val = v[0] if k >= 1 else v[0] * e
                    s = self._fmt(val, v[1])
                    fs = 21.6 * F
                    draw_text(d, cx, cy + (lh - line_h(fs)) / 2, s, "bold", fs, fg)
                    cx += text_w(self._fmt(v[0], v[1]), "bold", fs)
                elif kind == "small":
                    fs = 11.5 * F
                    draw_text(d, cx, cy + (lh - line_h(fs)) / 2, v.upper(), "bold", fs, C["muted"])
                    cx += text_w(v.upper(), "bold", fs)
                else:
                    draw_text(d, cx, cy + (lh - line_h(self.base)) / 2, v, "semi", self.base, fg)
                    cx += text_w(v, "semi", self.base)
            cy += lh


class Flow(Piece):
    def __init__(self, items, F, maxw):
        self.items, self.F = items, F
        gap = 8 * F
        rows, cur, cw = [], [], 0
        for it in items:
            if cur and cw + gap + it.w > maxw:
                rows.append(cur)
                cur, cw = [], 0
            cw += (gap if cur else 0) + it.w
            cur.append(it)
        if cur:
            rows.append(cur)
        self.rows = rows
        self.w = max(sum(i.w for i in r) + gap * (len(r) - 1) for r in rows)
        self.h = sum(max(i.h for i in r) for r in rows) + gap * (len(rows) - 1)
        self.gap = gap
        for j, it in enumerate(items):
            it.delay = 0.12 * min(j, 6)

    def place(self, x, y):
        out, cy = [], y
        for r in self.rows:
            rw = sum(i.w for i in r) + self.gap * (len(r) - 1)
            rh = max(i.h for i in r)
            cx = x + (self.w - rw) / 2
            for it in r:
                out.append((it, cx, cy + (rh - it.h) / 2))
                cx += it.w + self.gap
            cy += rh + self.gap
        return out


class Bar(Piece):
    def __init__(self, label, value, cls, F):
        self.label, self.v, self.cls, self.F = label, value, cls, F
        self.w, self.h = 630, 26 * F / 1.5 * 1.5

    def draw(self, d, x, y, t, layer):
        F = self.F
        lw, vw, gap = 165, 81, 15
        fs = 13.8 * F
        tw = text_w(self.label, "semi", fs)
        draw_text(d, x + lw - tw, y + (self.h - line_h(fs)) / 2, self.label, "semi", fs, C["text"])
        tx0, tx1 = x + lw + gap, x + self.w - vw - gap
        th = 12 * F
        ty = y + (self.h - th) / 2
        rrect(d, (tx0, ty, tx1, ty + th), th / 2, fill=C["line"])
        k = max(0.0, min(1.0, (t - 0.2) / 1.0))
        e = 1 - (1 - k) ** 3 if k < 1 else 1
        fw = (tx1 - tx0) * max(0, min(100, self.v)) / 100 * e
        col = {"good": C["green"], "weak": C["amber"], "bad": C["red"]}
        c0 = next((v for k_, v in col.items() if k_ in self.cls), C["blue"])
        c1 = mix(c0, (255, 255, 255), 0.45)
        if fw > th:
            grad = Image.new("RGB", (max(1, px(fw)), max(1, px(th))))
            gd = ImageDraw.Draw(grad)
            for i in range(grad.width):
                gd.line([(i, 0), (i, grad.height)], fill=mix(c0, c1, i / max(1, grad.width - 1)))
            mask = Image.new("L", grad.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, grad.width - 1, grad.height - 1], radius=px(th / 2), fill=255)
            d._image.paste(grad, (px(tx0), px(ty)), mask)
        val = f"{self.v:g}%"
        draw_text(d, x + self.w - vw, y + (self.h - line_h(fs)) / 2, val, "bold", fs, C["navy"])


class Table(Piece):
    def __init__(self, node, F):
        self.F = F
        self.rows = []
        for tr in [k for k in node.kids if not isinstance(k, str) and k.tag in ("tr", "tbody")]:
            for r in ([tr] if tr.tag == "tr" else [k for k in tr.kids if not isinstance(k, str) and k.tag == "tr"]):
                cells = []
                for td in [k for k in r.kids if not isinstance(k, str) and k.tag == "td"]:
                    col = None
                    for k in td.kids:
                        if not isinstance(k, str) and "color:" in k.style:
                            col = CSSVAR.get(k.style.split("color:")[1].strip().rstrip(";"))
                    cells.append((td.text().strip(), col))
                self.rows.append((cells, "h" in r.cls, "hl" in r.cls))
        fs = 13.8 * F
        self.fs = fs
        ncol = max(len(c) for c, _, _ in self.rows)
        self.cw = [0] * ncol
        for cells, head, hl in self.rows:
            for i, (t, _) in enumerate(cells):
                self.cw[i] = max(self.cw[i], text_w(t, "bold" if head or hl else "reg", fs) + 28 * F)
        self.rh = line_h(fs) + 12 * F
        self.w = sum(self.cw)
        self.h = self.rh * len(self.rows)

    def draw(self, d, x, y, t, layer):
        F = self.F
        rrect(d, (x, y, x + self.w, y + self.h), 12 * F, fill=C["card"], outline=C["line"], width=1)
        cy = y
        for n, (cells, head, hl) in enumerate(self.rows):
            if head:
                rrect(d, (x, cy, x + self.w, cy + self.rh + 12 * F), 12 * F, fill=C["navy"])
                d.rectangle([px(x), px(cy + self.rh - 1), px(x + self.w), px(cy + self.rh + 12 * F)], fill=C["card"])
                d.rectangle([px(x), px(cy + 12 * F), px(x + self.w), px(cy + self.rh)], fill=C["navy"])
            elif hl:
                k = (math.sin((t % 1.6) / 1.6 * 2 * math.pi - math.pi / 2) + 1) / 2
                d.rectangle([px(x + 1), px(cy), px(x + self.w - 1), px(cy + self.rh)],
                            fill=mix(C["card"], C["blue"], 0.14 + 0.12 * k))
            if n and not head and n < len(self.rows):
                d.line([px(x), px(cy), px(x + self.w), px(cy)], fill=C["line"], width=1)
            cx = x
            for i, (txt, col) in enumerate(cells):
                kind = "semi" if head else ("bold" if hl else "reg")
                fg = (255, 255, 255) if head else (col or C["text"])
                tw = text_w(txt, kind, self.fs)
                draw_text(d, cx + (self.cw[i] - tw) / 2, cy + (self.rh - line_h(self.fs)) / 2, txt, kind, self.fs, fg)
                cx += self.cw[i]
            cy += self.rh


def build_visual(html, F, maxw=1100):
    """-> list of top-level pieces (each a Flow / Bar / Table / Box / Chip)."""
    root = parse(html)
    out = []

    def piece(n):
        if isinstance(n, str):
            return None
        c = n.cls
        if "ex-chip" in c:
            return Chip(n.text(), c, F)
        if "ex-box" in c:
            return Box(n, F)
        if "ex-arrow" in c:
            return Arrow(F)
        if "ex-cross" in c:
            return Cross(n.text(), F)
        if "ex-bar" in c:
            spans = [k for k in n.kids if not isinstance(k, str)]
            label = spans[0].text() if spans else ""
            m = re.search(r"--w:\s*([\d.]+)%", " ".join(k.style for k in spans))
            return Bar(label, float(m.group(1)) if m else 0, c, F)
        if n.tag == "table":
            return Table(n, F)
        if "ex-flow" in c:
            items = [p for p in (piece(k) for k in n.kids) if p]
            return Flow(items, F, maxw)
        return None
    for k in root.kids:
        p = piece(k)
        if p:
            out.append(p)
    for i, p in enumerate(out):
        p.top_delay = 0.15 * min(i, 2)
    return out


# ---------------------------------------------------------------- whole frames
_bg = None
_logo = {}


def background():
    global _bg
    if _bg is None:
        img = Image.new("RGB", (W * SS, H * SS))
        d = ImageDraw.Draw(img)
        a, b, c = C["tint2"], C["tint"], (214, 238, 250)
        for yy in range(img.height):
            k = yy / img.height
            col = mix(a, b, k / 0.55) if k < 0.55 else mix(b, c, (k - 0.55) / 0.45)
            d.line([(0, yy), (img.width, yy)], fill=col)
        _bg = img
    return _bg.copy()


def logo(size):
    if size not in _logo:
        im = Image.open(os.path.join(ROOT, "web", "assets", "img", "rdps-logo.png")).convert("RGBA")
        _logo[size] = im.resize((px(size), px(size)), Image.LANCZOS)
    return _logo[size]


def topbar(img, area):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * SS, px(64)], fill=C["navy"])
    d.ellipse([px(36), px(11), px(78), px(53)], fill=(255, 255, 255))
    lg = logo(36)
    img.paste(lg, (px(39), px(14)), lg)
    draw_text(d, 92, 18, "RDPS Marks ", "bold", 20, (255, 255, 255))
    draw_text(d, 92 + text_w("RDPS Marks ", "bold", 20), 18, "Studio", "bold", 20, C["light"])
    a = area.upper()
    draw_text(d, W - 36 - text_w(a, "semi", 14), 22, a, "semi", 14, (200, 222, 236))


def anim_state(t, delay, dur=0.55):
    k = max(0.0, min(1.0, (t - delay) / dur))
    if k >= 1:
        return 1.0, 0.0
    e = ease_back(k)
    return max(0.0, min(1.0, ease_out(k))), 14 * (1 - e)


def paste_piece(frame, piece, x, y, t, delay):
    alpha, dy = anim_state(t, delay)
    if alpha <= 0:
        return
    pad = 12 * piece.F if hasattr(piece, "F") else 12
    lw, lh = piece.w + 2 * pad, piece.h + 2 * pad
    layer = Image.new("RGBA", (px(lw), px(lh)), (0, 0, 0, 0))
    glow = ImageDraw.Draw(layer)
    d = ImageDraw.Draw(layer)
    piece.draw(d, pad, pad, t - delay if not isinstance(piece, (Box, Bar, Table, Chip)) else t, glow)
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    frame.alpha_composite(layer, (px(x - pad), px(y - pad + dy)))


def wrap(text, kind, size, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        nxt = (cur + " " + w_).strip()
        if cur and text_w(nxt, kind, size) > maxw:
            lines.append(cur)
            cur = w_
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines


def title_frame(e, t):
    img = background().convert("RGBA")
    topbar(img, e["area"])
    d = ImageDraw.Draw(img)
    a, dy = anim_state(t, 0, 0.8)
    if a > 0:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        cx, cy = W / 2, 64 + 150
        ld.ellipse([px(cx - 85), px(cy - 85 + dy), px(cx + 85), px(cy + 85 + dy)], fill=mix(C["tint"], C["blue"], 0.12) + (255,))
        ld.ellipse([px(cx - 75), px(cy - 75 + dy), px(cx + 75), px(cy + 75 + dy)], fill=(255, 255, 255, 255))
        lg = logo(128)
        layer.paste(lg, (px(cx - 64), px(cy - 64 + dy)), lg)
        if a < 1:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
        img.alpha_composite(layer)
    for txt, kind, size, col, y, delay in (("H O W   I T   W O R K S", "bold", 18, C["blue2"], 64 + 262, 0.25),
                                           (e["title"], "bold", 54, C["navy"], 64 + 292, 0.4),
                                           ("Rukmini Devi Public School · Marks Studio", "reg", 20, C["muted"], 64 + 372, 0.6)):
        a, dy = anim_state(t, delay, 0.7)
        if a <= 0:
            continue
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        draw_text(ld, (W - text_w(txt, kind, size)) / 2, y + dy, txt, kind, size, col)
        if a < 1:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
        img.alpha_composite(layer)
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


class StepScene:
    def __init__(self, e, index):
        self.e, self.i = e, index
        s = e["steps"][index]
        self.caption = wrap(s["text"], "reg", 24, W - 112 - 56)
        cap_h = len(self.caption) * line_h(24) * 1.08 + 36
        self.cap_box = (56, H - 30 - 28 - cap_h, W - 56, H - 30 - 28)
        top, bottom = 64 + 26 + 50, self.cap_box[1] - 14
        avail = bottom - top
        for F in (1.5, 1.35, 1.2, 1.05, 0.9):
            pieces = build_visual(s["visual"], F)
            vh = sum(p.h for p in pieces) + 15 * F * (len(pieces) - 1)
            if vh <= avail:
                break
        self.pieces, self.F = pieces, F
        y = top + (avail - vh) / 2
        self.layout = []
        for p in pieces:
            x = (W - p.w) / 2
            if isinstance(p, Flow):
                for it, ix, iy in p.place(x, y):
                    self.layout.append((it, ix, iy, p.top_delay + it.delay))
            else:
                self.layout.append((p, x, y, p.top_delay))
            y += p.h + 15 * F

    def frame(self, t):
        e = self.e
        img = background().convert("RGBA")
        topbar(img, e["area"])
        d = ImageDraw.Draw(img)
        draw_text(d, 56, 64 + 22, e["title"], "bold", 30, C["navy"])
        cnt = f"STEP {self.i + 1} OF {len(e['steps'])}"
        draw_text(d, W - 56 - text_w(cnt, "bold", 15), 64 + 34, cnt, "bold", 15, C["muted"])
        for p, x, y, delay in self.layout:
            paste_piece(img, p, x, y, t, delay)
        # caption
        x0, y0, x1, y1 = self.cap_box
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        rrect(sd, (x0, y0 + 6, x1, y1 + 6), 18, fill=C["navy"] + (18,))
        img.alpha_composite(shadow)
        d = ImageDraw.Draw(img)
        rrect(d, (x0, y0, x1, y1), 18, fill=C["card"], outline=C["line"], width=1)
        ly = y0 + 18
        for ln in self.caption:
            draw_text(d, (W - text_w(ln, "reg", 24)) / 2, ly, ln, "reg", 24, C["text"])
            ly += line_h(24) * 1.08
        # dots
        n = len(e["steps"])
        dx = W / 2 - (n * 22 - 10) / 2
        for k in range(n):
            r = 7.5 if k == self.i else 6
            col = C["blue"] if k == self.i else C["line2"]
            cx = dx + k * 22 + 6
            d.ellipse([px(cx - r), px(H - 34 - r), px(cx + r), px(H - 34 + r)], fill=col)
        return img.convert("RGB").resize((W, H), Image.LANCZOS)
