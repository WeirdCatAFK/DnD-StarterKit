"""Monsters and dungeon props, drawn to match the class meeples.

The class art in `Meeples svg/` covers the player characters; this module adds
the generic enemies and the scenery. Monsters are authored as path data in a
100x100 box with the feet on y=100, so they scale the same way the meeples do.
Props are built procedurally instead -- they are boxes, staves and arcs, and
generating them is more reliable than hand-writing bezier soup.

Every shape returns (cut, engrave): the outline to cut and the detail lines to
engrave inside it.
"""

import math

import svgpath

# ---------------------------------------------------------------- monsters

# Bold silhouettes: at 22mm tall in 3mm ply, fine detail is lost anyway, and
# anything thinner than about 1.5mm snaps. Detail goes in the engrave layer.
_MONSTER_CUT = {
    # Hunched, oversized pointed ears, small body.
    "goblin": (
        "M 50,15 C 59,15 65,21 66,29 L 73,25 L 90,9 L 77,33 "
        "C 81,39 79,45 73,48 L 77,57 L 88,63 L 84,71 L 71,65 L 67,75 "
        "L 69,100 L 56,100 L 55,87 L 45,87 L 44,100 L 31,100 L 33,75 "
        "L 29,65 L 16,71 L 12,63 L 23,57 L 27,48 C 21,45 19,39 23,33 "
        "L 10,9 L 27,25 L 34,29 C 35,21 41,15 50,15 Z"
    ),
    # Narrow ribcage and long limbs; ribs and skull are engraved.
    "skeleton": (
        "M 50,4 C 63,4 72,14 72,26 C 72,33 69,38 65,41 L 65,45 "
        "L 59,45 L 59,49 L 82,57 L 79,66 L 61,60 L 60,74 L 66,100 "
        "L 55,100 L 52,82 L 48,82 L 45,100 L 34,100 L 40,74 L 39,60 "
        "L 21,66 L 18,57 L 41,49 L 41,45 L 35,45 L 35,41 "
        "C 31,38 28,33 28,26 C 28,14 37,4 50,4 Z"
    ),
    # Heavy shoulders, low head, tusks engraved.
    "orc": (
        "M 50,8 C 60,8 68,15 68,25 L 84,10 L 74,32 "
        "C 70,36 65,38 59,39 L 78,46 C 88,50 92,58 90,68 L 79,66 "
        "C 77,60 73,56 67,54 L 67,75 L 72,100 L 56,100 L 54,85 "
        "L 46,85 L 44,100 L 28,100 L 33,75 L 33,54 C 27,56 23,60 21,66 "
        "L 10,68 C 8,58 12,50 22,46 L 41,39 C 35,38 30,36 26,32 "
        "L 16,10 L 32,25 C 32,15 40,8 50,8 Z"
    ),
    # Big, lopsided, one arm dragging a club.
    "ogre": (
        "M 46,8 C 58,8 68,16 68,27 C 68,32 66,36 63,39 L 80,45 "
        "L 85,20 L 99,23 L 93,50 L 84,53 L 72,58 L 71,78 L 76,100 "
        "L 56,100 L 54,86 L 42,86 L 39,100 L 20,100 L 26,78 L 26,56 "
        "C 18,59 13,66 11,75 L 2,72 C 4,60 10,51 21,46 L 33,40 "
        "C 29,36 25,32 25,27 C 25,16 34,8 46,8 Z"
    ),
    # Wings up and back, long neck, tail curling to the ground.
    "dragon": (
        "M 62,10 C 70,10 76,16 76,24 C 76,28 74,32 71,34 L 76,40 "
        "L 92,26 L 88,46 L 97,54 L 80,56 L 74,66 L 78,88 L 84,100 "
        "L 64,100 L 60,84 L 46,86 L 40,100 L 22,100 L 28,84 L 22,70 "
        "C 12,66 6,56 8,44 L 18,50 C 20,58 26,62 34,62 L 40,50 "
        "L 24,34 L 8,16 L 30,26 L 46,40 L 52,34 C 49,32 47,28 47,24 "
        "C 47,16 54,10 62,10 Z"
    ),
    # Quadruped, long tail, low body.
    "rat": (
        "M 4,58 C -2,48 6,34 18,38 L 26,52 C 30,42 38,34 50,31 "
        "L 46,10 L 64,26 L 78,12 L 80,32 C 90,36 97,44 99,54 "
        "L 86,60 C 84,68 78,74 70,76 L 70,100 L 54,100 L 54,80 "
        "L 40,80 L 40,100 L 24,100 L 24,72 C 14,68 7,64 3,58 Z"
    ),
    # Blob with a heavy sagging base and two drips.
    "slime": (
        "M 50,20 C 70,20 84,36 86,58 C 88,78 76,92 66,92 L 66,100 "
        "L 56,100 L 56,92 L 44,92 L 44,100 L 34,100 L 34,92 "
        "C 24,92 12,78 14,58 C 16,36 30,20 50,20 Z"
    ),
    # Wings spread wide, small body -- deliberately squat so it stays strong.
    "bat": (
        "M 50,34 C 55,34 58,38 58,43 L 68,36 C 74,30 82,26 92,25 "
        "C 86,31 84,38 84,44 C 88,42 92,42 97,44 C 91,51 84,55 76,57 "
        "L 68,64 L 66,100 L 56,100 L 53,76 L 47,76 L 44,100 L 34,100 "
        "L 32,64 L 24,57 C 16,55 9,51 3,44 C 8,42 12,42 16,44 "
        "C 16,38 14,31 8,25 C 18,26 26,30 32,36 L 42,43 "
        "C 42,38 45,34 50,34 Z"
    ),
}

_MONSTER_ENGRAVE = {
    "goblin": [
        "M 40,32 L 45,35 M 60,32 L 55,35",          # eyes
        "M 42,44 L 58,44",                          # mouth
        "M 40,60 L 60,60 M 42,70 L 58,70",          # belly folds
    ],
    "skeleton": [
        "M 42,22 L 46,26 M 58,22 L 54,26",          # sockets
        "M 44,33 L 56,33",                          # jaw
        "M 40,52 L 60,52 M 41,60 L 59,60 M 43,68 L 57,68",   # ribs
        "M 50,48 L 50,72",                          # spine
    ],
    "orc": [
        "M 40,24 L 45,27 M 60,24 L 55,27",
        "M 42,33 L 46,40 M 58,33 L 54,40",          # tusks
        "M 40,58 L 60,58 M 42,68 L 58,68",
    ],
    "ogre": [
        "M 38,20 L 44,24 M 60,20 L 55,24",
        "M 42,32 L 58,32",
        "M 38,60 L 62,60 M 40,72 L 60,72",
        "M 88,56 L 92,68",                          # club
    ],
    "dragon": [
        "M 66,20 L 70,23",                          # eye
        "M 62,30 L 72,32",                          # jaw
        "M 84,32 L 88,42 M 30,32 L 26,42",          # wing struts
        "M 52,54 L 68,58 M 50,64 L 66,68",          # belly scales
    ],
    "rat": [
        "M 82,44 L 88,48",                          # eye
        "M 34,58 L 46,62 M 40,70 L 54,72",          # flank
        "M 10,50 L 20,56",                          # tail
    ],
    "slime": [
        "M 38,44 L 44,50 M 62,44 L 56,50",          # eyes
        "M 42,64 C 46,70 54,70 58,64",              # mouth
        "M 28,40 C 32,32 40,28 48,28",              # highlight
    ],
    "bat": [
        "M 45,38 L 48,41 M 55,38 L 52,41",
        "M 78,38 L 72,48 M 22,38 L 28,48",          # wing ribs
        "M 86,34 L 80,46 M 14,34 L 20,46",
    ],
}

MONSTERS = tuple(_MONSTER_CUT)


def monster(name, height, close_radius=0.0):
    """Monster silhouette scaled to `height` mm, as (cut, engrave)."""
    cut = svgpath.flatten(_MONSTER_CUT[name], tol=0.3)
    eng = [svgpath.flatten(d, tol=0.3) for d in _MONSTER_ENGRAVE.get(name, ())]
    k = height / 100.0
    cut = svgpath.transform(cut, k, k, 0.0, 0.0)
    eng = [svgpath.transform(e, k, k, 0.0, 0.0) for e in eng]
    return cut, [s for e in eng for s in e]


# ------------------------------------------------------------------- props


def _arc_pts(cx, cy, r, a0, a1, steps=24):
    return [
        (cx + r * math.cos(a0 + (a1 - a0) * i / steps), cy + r * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def _rounded_rect(x, y, w, h, r, steps=8):
    r = min(r, w / 2, h / 2)
    p = []
    p += _arc_pts(x + w - r, y + h - r, r, 0, math.pi / 2, steps)
    p += _arc_pts(x + r, y + h - r, r, math.pi / 2, math.pi, steps)
    p += _arc_pts(x + r, y + r, r, math.pi, 1.5 * math.pi, steps)
    p += _arc_pts(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi, steps)
    return p


def _line(x0, y0, x1, y1):
    return ([(x0, y0), (x1, y1)], False)


def prop(name, height):
    """Dungeon prop as (cut, engrave), sized so its overall height is `height`.

    Props are drawn feet-down in a box of `height` mm; widths follow from the
    shape. All of them stand in the same slotted base as the figures.
    """
    h = height
    cut, eng = [], []

    if name == "chest":
        w = h * 1.35
        cap = h * 0.42
        r = h * 0.06
        # One closed outline: elliptical lid straight into the rounded body.
        pts = _arc_pts(w / 2, cap, w / 2, math.pi, 2 * math.pi, 24)
        pts = [(x, cap + (y - cap) * (cap / (w / 2))) for x, y in pts]
        pts += _arc_pts(w - r, h - r, r, 0, math.pi / 2, 6)
        pts += _arc_pts(r, h - r, r, math.pi / 2, math.pi, 6)
        cut.append((pts, True))
        eng.append(_line(w * 0.02, cap, w * 0.98, cap))
        eng.append(_line(w * 0.44, cap * 0.55, w * 0.44, h * 0.86))
        eng.append(_line(w * 0.56, cap * 0.55, w * 0.56, h * 0.86))
        eng.append((_rounded_rect(w * 0.42, cap + h * 0.06, w * 0.16, h * 0.16, h * 0.03), True))

    elif name == "barrel":
        w = h * 0.78
        p = (
            _arc_pts(w / 2, h * 0.5, w / 2, math.pi, 2 * math.pi, 4)
        )
        # staved silhouette: bulge in the middle, flat top and bottom
        cut.append(
            (
                [
                    (w * 0.14, h * 0.06), (w * 0.86, h * 0.06),
                    (w * 0.98, h * 0.30), (w * 1.00, h * 0.52), (w * 0.90, h * 0.94),
                    (w * 0.10, h * 0.94), (w * 0.00, h * 0.52), (w * 0.02, h * 0.30),
                ],
                True,
            )
        )
        for f in (0.24, 0.50, 0.76):
            eng.append(_line(w * 0.02, h * f, w * 0.98, h * f))
        for f in (0.3, 0.5, 0.7):
            eng.append(_line(w * f, h * 0.08, w * f, h * 0.92))

    elif name == "table":
        w = h * 1.6
        cut.append(
            (
                [
                    (0, h * 0.18), (w, h * 0.18), (w, h * 0.34),
                    (w * 0.86, h * 0.34), (w * 0.86, h), (w * 0.68, h),
                    (w * 0.68, h * 0.34), (w * 0.32, h * 0.34), (w * 0.32, h),
                    (w * 0.14, h), (w * 0.14, h * 0.34), (0, h * 0.34),
                ],
                True,
            )
        )
        eng.append(_line(0, h * 0.26, w, h * 0.26))

    elif name == "brazier":
        w = h * 1.0
        cut.append(
            (
                [
                    (0, h * 0.26), (w, h * 0.26), (w * 0.74, h * 0.56),
                    (w * 0.58, h * 0.56), (w * 0.58, h * 0.70), (w * 0.92, h),
                    (w * 0.74, h), (w * 0.50, h * 0.80), (w * 0.26, h),
                    (w * 0.08, h), (w * 0.42, h * 0.70), (w * 0.42, h * 0.56),
                    (w * 0.26, h * 0.56),
                ],
                True,
            )
        )
        eng.append(_line(w * 0.04, h * 0.34, w * 0.96, h * 0.34))
        eng.append(
            (
                [
                    (w * 0.30, h * 0.32), (w * 0.40, h * 0.06), (w * 0.48, h * 0.20),
                    (w * 0.58, h * 0.02), (w * 0.66, h * 0.24), (w * 0.70, h * 0.32),
                ],
                False,
            )
        )

    elif name == "crate":
        w = h
        cut.append((_rounded_rect(0, 0, w, h, h * 0.05), True))
        eng.append(_line(0, 0, w, h))
        eng.append(_line(w, 0, 0, h))
        eng.append(_line(0, h * 0.14, w, h * 0.14))
        eng.append(_line(0, h * 0.86, w, h * 0.86))

    elif name == "bookshelf":
        w = h * 0.66
        cut.append((_rounded_rect(0, 0, w, h, h * 0.03), True))
        for f in (0.26, 0.52, 0.78):
            eng.append(_line(0, h * f, w, h * f))
        for row in (0.26, 0.52, 0.78):
            for i in range(5):
                x = w * (0.10 + 0.17 * i)
                eng.append(_line(x, h * (row - 0.20), x, h * row))

    elif name == "altar":
        w = h * 1.5
        cut.append(
            (
                [
                    (0, h * 0.06), (w, h * 0.06), (w, h * 0.26),
                    (w * 0.84, h * 0.26), (w * 0.84, h * 0.82), (w, h * 0.82),
                    (w, h), (0, h), (0, h * 0.82), (w * 0.16, h * 0.82),
                    (w * 0.16, h * 0.26), (0, h * 0.26),
                ],
                True,
            )
        )
        eng.append(_line(w * 0.5, h * 0.34, w * 0.5, h * 0.62))
        eng.append(_line(w * 0.38, h * 0.44, w * 0.62, h * 0.44))

    elif name == "stairs":
        w = h * 1.4
        pts = [(0, h)]
        steps = 4
        for i in range(steps):
            x = w * i / steps
            y = h - h * (i + 1) / steps
            pts += [(x, y), (x + w / steps, y)]
        pts += [(w, h)]
        cut.append((pts, True))
        for i in range(1, steps):
            x = w * i / steps
            eng.append(_line(x, h - h * i / steps, x, h))

    elif name == "well":
        w = h * 1.1
        cut.append(
            (
                [
                    (w * 0.06, h * 0.44), (w * 0.20, h * 0.44), (w * 0.20, h * 0.10),
                    (w * 0.80, h * 0.10), (w * 0.80, h * 0.44), (w * 0.94, h * 0.44),
                    (w * 0.94, h), (w * 0.06, h),
                ],
                True,
            )
        )
        eng.append(_line(w * 0.06, h * 0.56, w * 0.94, h * 0.56))
        eng.append(_line(w * 0.20, h * 0.20, w * 0.80, h * 0.20))
        eng.append(_line(w * 0.5, h * 0.20, w * 0.5, h * 0.42))
        for f in (0.68, 0.82):
            eng.append(_line(w * 0.06, h * f, w * 0.94, h * f))

    elif name == "pillar":
        w = h * 0.44
        cut.append(
            (
                [
                    (0, 0), (w, 0), (w, h * 0.12), (w * 0.82, h * 0.12),
                    (w * 0.82, h * 0.86), (w, h * 0.86), (w, h), (0, h),
                    (0, h * 0.86), (w * 0.18, h * 0.86), (w * 0.18, h * 0.12),
                    (0, h * 0.12),
                ],
                True,
            )
        )
        for f in (0.30, 0.50, 0.70):
            eng.append(_line(w * 0.18, h * f, w * 0.82, h * f))

    else:
        raise KeyError(f"unknown prop {name!r}")

    return cut, eng


PROPS = ("chest", "barrel", "table", "brazier", "crate", "bookshelf", "altar", "stairs", "well", "pillar")
