"""Trains the small digit reader used to read photos of the paper mark sheets (web/js/sheetscan.js).

It learns from real handwriting - MNIST, the free public set of 70,000 handwritten digits (downloaded once to
Documents/SchoolAI-data/mnist; no names or personal data in it) - and from digits drawn here in handwriting-like
fonts and as random pen strokes (Indian ways of writing 1 and 7 too), bent, slanted, thick and thin, plus an 11th
class, "not a digit" (lines, dots, letters, bits of a box). MNIST's own 10,000 test digits are never trained on and
show how well it reads real handwriting. Without the MNIST files it trains on drawn digits only. The weights go to web/assets/sheet/digits.json; the website runs the same small network in
plain JavaScript (sheetscan.js), so the photo never leaves the computer.

  python tools/digits_train.py            (needs numpy, opencv, pillow, torch - only on the developer's PC)
"""
import base64
import json
import math
import os
import random
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn as nn
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "assets", "sheet", "digits.json")
FONTS = "C:/Windows/Fonts/"
TRAIN_FONTS = ["Inkfree.ttf", "segoeprb.ttf", "segoesc.ttf", "segoescb.ttf", "comic.ttf", "comicbd.ttf", "comici.ttf",
               "mvboli.ttf", "LHANDW.TTF", "VINERITC.TTF", "JUICE___.TTF", "FRSCRIPT.TTF", "Gabriola.ttf",
               "arial.ttf", "ariali.ttf", "calibri.ttf", "calibrii.ttf", "Candarai.ttf", "corbeli.ttf", "georgiai.ttf",
               "consola.ttf", "ARIALN.TTF", "PAPYRUS.TTF"]
TEST_FONTS = ["segoepr.ttf", "comicz.ttf"]          # never seen in training
NOT_DIGIT = 10


# ---------------------------------------------------------------- the same normalising as sheetscan.js
def normalise(ink):
    """ink: float image, 1 = ink, 0 = paper -> 28x28 like MNIST: the ink fitted into 20x20 (aspect kept) and
    centred by its centre of mass. None when there is (almost) no ink."""
    mask = ink > 0.25
    if mask.sum() < 6:
        return None
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = ink[y0:y1, x0:x1]
    h, w = crop.shape
    s = 20.0 / max(h, w)
    nh, nw = max(1, round(h * s)), max(1, round(w * s))
    small = cv2.resize(crop.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((28, 28), np.float32)
    tot = small.sum()
    cy = (small.sum(1) * np.arange(nh)).sum() / tot
    cx = (small.sum(0) * np.arange(nw)).sum() / tot
    oy, ox = int(round(14 - cy)), int(round(14 - cx))
    oy, ox = min(max(oy, 0), 28 - nh), min(max(ox, 0), 28 - nw)
    out[oy:oy + nh, ox:ox + nw] = small
    return np.clip(out / max(out.max(), 1e-6), 0, 1)


# ---------------------------------------------------------------- drawing digits
def font_digit(rnd, ch, fonts):
    img = Image.new("L", (96, 96), 0)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONTS + rnd.choice(fonts), rnd.randint(46, 64))
    bb = d.textbbox((0, 0), ch, font=f)
    x = (96 - (bb[2] - bb[0])) / 2 - bb[0] + rnd.uniform(-6, 6)
    y = (96 - (bb[3] - bb[1])) / 2 - bb[1] + rnd.uniform(-6, 6)
    d.text((x, y), ch, fill=255, font=f)
    return np.asarray(img, np.float32) / 255


# pen strokes of each digit in a 0..1 box (x right, y down); several ways of writing some digits
SKELETONS = {
    0: [[[(0.5, 0.05), (0.15, 0.25), (0.12, 0.6), (0.3, 0.92), (0.65, 0.95), (0.88, 0.65), (0.85, 0.25), (0.55, 0.04), (0.45, 0.08)]]],
    1: [[[(0.5, 0.05), (0.5, 0.95)]], [[(0.3, 0.25), (0.55, 0.05), (0.55, 0.95)]],
        [[(0.3, 0.25), (0.55, 0.05), (0.55, 0.95)], [(0.3, 0.95), (0.8, 0.95)]]],
    2: [[[(0.15, 0.25), (0.35, 0.06), (0.7, 0.06), (0.85, 0.28), (0.7, 0.55), (0.15, 0.95), (0.88, 0.95)]],
        [[(0.15, 0.3), (0.45, 0.05), (0.85, 0.25), (0.6, 0.6), (0.15, 0.93), (0.5, 0.85), (0.9, 0.95)]]],
    3: [[[(0.15, 0.12), (0.5, 0.03), (0.82, 0.2), (0.7, 0.42), (0.4, 0.5), (0.75, 0.58), (0.88, 0.8), (0.5, 0.97), (0.12, 0.85)]],
        [[(0.15, 0.08), (0.85, 0.08), (0.45, 0.45), (0.8, 0.6), (0.85, 0.82), (0.5, 0.97), (0.12, 0.85)]]],
    4: [[[(0.65, 0.95), (0.65, 0.05), (0.1, 0.65), (0.92, 0.65)]],
        [[(0.25, 0.05), (0.15, 0.6), (0.88, 0.6)], [(0.68, 0.25), (0.68, 0.97)]]],
    5: [[[(0.82, 0.06), (0.25, 0.06), (0.2, 0.45), (0.55, 0.38), (0.85, 0.6), (0.75, 0.9), (0.45, 0.97), (0.12, 0.85)]],
        [[(0.25, 0.06), (0.2, 0.45), (0.55, 0.38), (0.85, 0.6), (0.75, 0.9), (0.45, 0.97), (0.12, 0.85)], [(0.25, 0.06), (0.85, 0.06)]]],
    6: [[[(0.75, 0.05), (0.4, 0.2), (0.18, 0.55), (0.25, 0.9), (0.55, 0.97), (0.82, 0.78), (0.7, 0.52), (0.4, 0.5), (0.2, 0.65)]]],
    7: [[[(0.12, 0.08), (0.88, 0.08), (0.45, 0.95)]], [[(0.12, 0.08), (0.88, 0.08), (0.45, 0.95)], [(0.3, 0.5), (0.8, 0.5)]],
        [[(0.15, 0.2), (0.15, 0.08), (0.88, 0.08), (0.5, 0.95)]]],
    8: [[[(0.5, 0.48), (0.2, 0.3), (0.3, 0.07), (0.7, 0.07), (0.8, 0.3), (0.5, 0.48), (0.15, 0.72), (0.3, 0.95), (0.72, 0.95), (0.85, 0.72), (0.5, 0.48)]]],
    9: [[[(0.8, 0.35), (0.6, 0.5), (0.3, 0.45), (0.2, 0.22), (0.45, 0.04), (0.75, 0.1), (0.8, 0.35), (0.75, 0.95)]],
        [[(0.8, 0.3), (0.55, 0.48), (0.25, 0.4), (0.25, 0.12), (0.55, 0.03), (0.82, 0.2), (0.8, 0.5), (0.6, 0.95)]]],
}


def catmull(points, n=12):
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = (np.array(p) for p in pts[i - 1:i + 3])
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(np.array(points[-1]))
    return np.array(out)


def stroke_digit(rnd, digit):
    img = np.zeros((96, 96), np.uint8)
    strokes = rnd.choice(SKELETONS[digit])
    wscale, hscale = rnd.uniform(0.45, 0.85), rnd.uniform(0.65, 0.85)
    x0, y0 = (96 - 96 * wscale) / 2 + rnd.uniform(-5, 5), (96 - 96 * hscale) / 2 + rnd.uniform(-5, 5)
    th = rnd.randint(2, 7)
    for st in strokes:
        pts = [(x + rnd.gauss(0, 0.035), y + rnd.gauss(0, 0.035)) for x, y in st]
        if len(pts) == 2:
            pts = [pts[0], ((pts[0][0] + pts[1][0]) / 2 + rnd.gauss(0, 0.02), (pts[0][1] + pts[1][1]) / 2), pts[1]]
        curve = catmull(pts)
        curve[:, 0] = x0 + curve[:, 0] * 96 * wscale
        curve[:, 1] = y0 + curve[:, 1] * 96 * hscale
        cv2.polylines(img, [np.round(curve * 4).astype(np.int32)], False, 255, th * 4 // 2, cv2.LINE_AA, shift=2)
    return img.astype(np.float32) / 255


def junk(rnd, fonts):
    """Not a digit: a line, a dot, a bit of a box edge, a scribble, a letter."""
    img = np.zeros((96, 96), np.uint8)
    k = rnd.random()
    th = rnd.randint(2, 6)
    if k < 0.25:                         # a line (box edge, a dash, a slash)
        a = rnd.uniform(0, math.pi)
        c, s = math.cos(a), math.sin(a)
        L = rnd.uniform(15, 45)
        cx, cy = rnd.uniform(25, 70), rnd.uniform(25, 70)
        cv2.line(img, (int(cx - c * L), int(cy - s * L)), (int(cx + c * L), int(cy + s * L)), 255, th, cv2.LINE_AA)
    elif k < 0.4:                        # an edge of the box along a side
        side = rnd.randint(0, 3)
        p = rnd.randint(2, 12)
        if side == 0:
            cv2.line(img, (0, p), (95, p), 255, th)
        elif side == 1:
            cv2.line(img, (0, 95 - p), (95, 95 - p), 255, th)
        elif side == 2:
            cv2.line(img, (p, 0), (p, 95), 255, th)
        else:
            cv2.line(img, (95 - p, 0), (95 - p, 95), 255, th)
    elif k < 0.55:                       # a scribble
        pts = np.array([[rnd.uniform(20, 76), rnd.uniform(20, 76)] for _ in range(rnd.randint(4, 9))], np.int32)
        cv2.polylines(img, [pts], False, 255, th, cv2.LINE_AA)
    elif k < 0.65:                       # a tick
        cv2.polylines(img, [np.array([[25, 50], [42, 72], [75, 22]], np.int32)], False, 255, th, cv2.LINE_AA)
    else:                                # a letter (AB, ML, x ...)
        return font_digit(rnd, rnd.choice("ABMLDXNEabmlx-/?"), fonts)
    return img.astype(np.float32) / 255


def augment(rnd, ink):
    h, w = ink.shape
    ang = rnd.uniform(-14, 14)
    sc = rnd.uniform(0.85, 1.12)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
    M[0, 1] += rnd.uniform(-0.3, 0.3)          # slant
    ink = cv2.warpAffine(ink, M, (w, h), borderValue=0)
    if rnd.random() < 0.5:                      # bent (elastic)
        a, s = rnd.uniform(4, 9), rnd.uniform(3.5, 5)
        dx = cv2.GaussianBlur(np.random.uniform(-1, 1, (h, w)).astype(np.float32), (0, 0), s) * a
        dy = cv2.GaussianBlur(np.random.uniform(-1, 1, (h, w)).astype(np.float32), (0, 0), s) * a
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        ink = cv2.remap(ink, gx + dx, gy + dy, cv2.INTER_LINEAR, borderValue=0)
    r = rnd.random()                            # thicker / thinner pen
    if r < 0.25:
        ink = cv2.dilate(ink, np.ones((3, 3), np.uint8))
    elif r < 0.4:
        ink = cv2.erode(ink, np.ones((2, 2), np.uint8))
    if rnd.random() < 0.3:
        ink = cv2.GaussianBlur(ink, (0, 0), rnd.uniform(0.6, 1.4))
    if rnd.random() < 0.3:                      # pale ink / pencil
        ink = ink * rnd.uniform(0.45, 0.9)
    return np.clip(ink, 0, 1)


def sample(rnd, fonts, stroke_share=0.5):
    label = rnd.randint(0, 10)
    if label == NOT_DIGIT:
        ink = junk(rnd, fonts)
    elif rnd.random() < stroke_share:
        ink = stroke_digit(rnd, label)
    else:
        ink = font_digit(rnd, str(label), fonts)
    x = normalise(augment(rnd, ink))
    return (x, label) if x is not None else sample(rnd, fonts, stroke_share)


def dataset(n, fonts, seed, stroke_share=0.5):
    rnd = random.Random(seed)
    np.random.seed(seed)
    xs, ys = [], []
    for _ in range(n):
        x, y = sample(rnd, fonts, stroke_share)
        xs.append(x)
        ys.append(y)
    return torch.tensor(np.stack(xs))[:, None], torch.tensor(ys)


# ---------------------------------------------------------------- real handwriting: MNIST (free public set of 70,000
# handwritten digits; downloaded once to Documents/SchoolAI-data/mnist, never part of the site)
MNIST = os.path.join(os.path.dirname(ROOT), "SchoolAI-data", "mnist")


def mnist(part):
    """part 'train' or 't10k' -> (images 0..1 float, labels) or None when the files are not there."""
    import gzip
    fi, fl = os.path.join(MNIST, f"{part}-images-idx3-ubyte.gz"), os.path.join(MNIST, f"{part}-labels-idx1-ubyte.gz")
    if not (os.path.exists(fi) and os.path.exists(fl)):
        return None
    with gzip.open(fi) as f:
        raw = f.read()
    assert int.from_bytes(raw[:4], "big") == 2051
    n = int.from_bytes(raw[4:8], "big")
    imgs = np.frombuffer(raw, np.uint8, offset=16).reshape(n, 28, 28).astype(np.float32) / 255
    with gzip.open(fl) as f:
        lab = np.frombuffer(f.read(), np.uint8, offset=8).astype(np.int64)
    return imgs, lab


def mnist_set(part, n=None, seed=0, aug=False):
    """MNIST digits put through the same normalising as the photos (and, for training, the same bending/slanting)."""
    got = mnist(part)
    if got is None:
        return None
    imgs, lab = got
    idx = np.arange(len(lab)) if n is None else np.random.RandomState(seed).choice(len(lab), n, replace=False)
    rnd = random.Random(seed)
    xs, ys = [], []
    for i in idx:
        ink = cv2.resize(imgs[i], (96, 96), interpolation=cv2.INTER_LINEAR)
        x = normalise(augment(rnd, ink) if aug else ink)
        if x is not None:
            xs.append(x)
            ys.append(int(lab[i]))
    return torch.tensor(np.stack(xs))[:, None], torch.tensor(ys)


# ---------------------------------------------------------------- the network (sheetscan.js runs the same one)
class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.c1 = nn.Conv2d(1, 16, 3, padding=1)
        self.c2 = nn.Conv2d(16, 32, 3, padding=1)
        self.c3 = nn.Conv2d(32, 48, 3, padding=1)
        self.f1 = nn.Linear(48 * 3 * 3, 96)
        self.f2 = nn.Linear(96, 11)
        self.pool = nn.MaxPool2d(2)
        self.drop = nn.Dropout(0.3)

    def forward(self, x):
        x = self.pool(torch.relu(self.c1(x)))      # 28 -> 14
        x = self.pool(torch.relu(self.c2(x)))      # 14 -> 7
        x = self.pool(torch.relu(self.c3(x)))      # 7 -> 3
        x = self.drop(torch.relu(self.f1(x.flatten(1))))
        return self.f2(x)


def main(n_train=60000, epochs=10):
    t0 = time.time()
    torch.manual_seed(1)
    xtr, ytr = dataset(n_train, TRAIN_FONTS, 1)
    real = mnist_set("train", aug=True, seed=5)                      # real handwriting, bent / slanted like the rest
    if real is not None:
        xtr, ytr = torch.cat([xtr, real[0]]), torch.cat([ytr, real[1]])
    xva, yva = dataset(6000, TRAIN_FONTS, 2)
    xfont, yfont = dataset(4000, TEST_FONTS, 3, stroke_share=0)      # fonts never seen
    xstr, ystr = dataset(4000, TRAIN_FONTS, 4, stroke_share=1)       # pen strokes only, other random shapes
    test_real = mnist_set("t10k")                                    # 10,000 real handwritten digits never seen
    print(f"made {len(xtr)} training digits in {time.time() - t0:.0f} s")
    net = Net()
    opt = torch.optim.Adam(net.parameters(), 2e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    lossf = nn.CrossEntropyLoss(label_smoothing=0.05)
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(len(xtr))
        for i in range(0, len(xtr), 128):
            idx = perm[i:i + 128]
            opt.zero_grad()
            lossf(net(xtr[idx]), ytr[idx]).backward()
            opt.step()
        sched.step()
        sets = [("check", xva, yva), ("unseen fonts", xfont, yfont), ("strokes", xstr, ystr)]
        if test_real is not None:
            sets.append(("REAL handwriting", *test_real))
        print(f"epoch {ep + 1}: " + ", ".join(f"{k} {acc(net, x, y):.1%}" for k, x, y in sets))
    net.eval()
    for k, x, y in sets[1:]:
        with torch.no_grad():
            p = torch.softmax(net(x), 1)
        conf, pred = p.max(1)
        sure = conf >= 0.9
        print(f"{k}: {acc(net, x, y):.1%} right; sure (>=90%) on {sure.float().mean():.0%} of them, and those are "
              f"{(pred[sure] == y[sure]).float().mean():.2%} right ({int(((pred != y) & sure).sum())} wrong-but-sure of {len(y)})")
    export(net)
    print(f"done in {time.time() - t0:.0f} s -> {OUT}")


def acc(net, x, y):
    net.eval()
    with torch.no_grad():
        return (net(x).argmax(1) == y).float().mean().item()


def export(net):
    layers = {}
    for name, p in net.state_dict().items():
        a = p.detach().numpy().astype("<f4")
        layers[name] = {"shape": list(a.shape), "data": base64.b64encode(a.tobytes()).decode()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"_help": "Digit reader for photos of the paper mark sheets: 28x28 -> 0-9 or 10 (not a digit). Trained on "
                        "drawn digits only (tools/digits_train.py). Float32, little-endian, base64; torch layer names.",
               "classes": 11, "layers": layers}, open(OUT, "w"))


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
