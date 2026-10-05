"""Generate the laser-cut D&D dungeon board.

Four 400x400x3mm plywood sheets. Each yields one 300x300mm board tile on a 30mm
grid, and the ~40mm border left around the tile is packed with the walls, doors,
figures, props and seam keys that make up the kit.

    python generate.py            # write out/*.svg
    python generate.py --report   # cut lengths, time estimates, bounds check

Edit the CONFIG block below, re-run, and every file updates. Cut
out/00_fit_test.svg first and set THICKNESS and KERF from what it measures --
every joint in the kit depends on those two numbers.
"""

import argparse
import math
import os
import random

import assembly
import meeples
import outline
import piecelist
import render
import shapes
import strokefont
import svgpath

# ============================== CONFIG =====================================

THICKNESS = 3.0        # measured plywood thickness, mm
KERF = 0.15            # measured laser kerf (half-width taken off each side)

GRID = 25.0            # grid pitch, mm
SQUARES = 8            # squares per tile edge -> TILE = GRID * SQUARES
SHEET = 300.0          # plywood sheet, mm square
SAFE = 290.0           # keep all geometry inside this, centred: 5mm margin

HOLE = 5.9             # finished vertex hole, mm square
WALL_H = 12.0          # wall body height; tabs add THICKNESS below it
TAB_LEN = 2.6          # finished tab length: the near half of a vertex hole
TAB_CLEAR = 0.25       # gap from the hole centre-line, so two tabs never meet

FIG_BOX = 20.0         # figures fit inside this box, mm
MONSTER_H = 18.5       # monster height, mm
PROP_H = 16.5          # prop height, mm
BASE_MIN, BASE_MAX = 20.0, 23.5
BIG_BASE = 30.0        # boss base; capped by the border strip it is cut from
BOSS_H = 25.0          # the dragon is cut larger than the rank-and-file monsters

CLOSE_R = 0.8          # morphological closing on class art, mm
CLOSE_R_MONSTER = 0.45
STONE_TEXTURE = True

GAP = 2.0              # spacing between packed pieces, mm

CUT_SPEED = {5: (150, 6), 10: (250, 4), 20: (400, 2)}  # module W -> (mm/min, passes)
ENGRAVE_SPEED = 3000.0

# ------------------------------- derived -----------------------------------

TILE = GRID * SQUARES
VERTS = SQUARES + 1
HOLE_DRAW = HOLE - 2 * KERF          # cuts out to HOLE
SLOT_DRAW = THICKNESS - 2 * KERF     # cuts out to THICKNESS: receives a sheet edge
TAB_DRAW = TAB_LEN + 2 * KERF        # cuts down to TAB_LEN
KEY_DRAW = HOLE - 0.3 + 2 * KERF     # seam key, 0.3mm loose in the hole
ORIGIN = (SHEET - TILE) / 2          # tile position on the sheet
MARGIN = (SHEET - SAFE) / 2

def apply_config(thickness=None, kerf=None, sheet=None, safe=None, squares=None, grid=None):
    """Re-derive everything that depends on THICKNESS, KERF, SHEET, SAFE, SQUARES or GRID.

    Lets one run of the generator produce a set for a different plywood or sheet
    size without editing the file. Clears the figure cache because a figure's
    base slot is measured over the bottom THICKNESS mm of its outline.
    """
    global THICKNESS, KERF, SHEET, SAFE, SQUARES, GRID
    global TILE, VERTS, HOLE_DRAW, SLOT_DRAW, TAB_DRAW, KEY_DRAW, ORIGIN, MARGIN
    if thickness is not None:
        THICKNESS = float(thickness)
    if kerf is not None:
        KERF = float(kerf)
    if sheet is not None:
        SHEET = float(sheet)
    if safe is not None:
        SAFE = float(safe)
    if squares is not None:
        SQUARES = int(squares)
    if grid is not None:
        GRID = float(grid)
    TILE = GRID * SQUARES
    VERTS = SQUARES + 1
    HOLE_DRAW = HOLE - 2 * KERF
    SLOT_DRAW = THICKNESS - 2 * KERF
    TAB_DRAW = TAB_LEN + 2 * KERF
    KEY_DRAW = HOLE - 0.3 + 2 * KERF
    ORIGIN = (SHEET - TILE) / 2
    MARGIN = (SHEET - SAFE) / 2
    _fig_cache.clear()
    _sheet_cache.clear()


LAYERS = [
    ("frame", "#000000", "reference frame - set output OFF"),
    ("engrave-grid", "#0000FF", "grid lines"),
    ("engrave-detail", "#00FF00", "art, texture and labels"),
    ("cut", "#FF0000", "cut"),
]

# ============================== plumbing ===================================


class Piece:
    """A part: geometry to cut, geometry to engrave, normalised to (0, 0)."""

    def __init__(self, name, cut, engrave=(), grid=()):
        self.name = name
        self.cut = list(cut)
        self.engrave = list(engrave)
        self.grid = list(grid)
        # Measure across every layer: the engraved art can sit a fraction
        # outside the closed cut line, and packing has to allow for it.
        x0, y0, x1, y1 = svgpath.bbox(self.cut + self.engrave + self.grid)
        self.cut = svgpath.transform(self.cut, 1, 1, -x0, -y0)
        self.engrave = svgpath.transform(self.engrave, 1, 1, -x0, -y0)
        self.grid = svgpath.transform(self.grid, 1, 1, -x0, -y0)
        self.w, self.h = x1 - x0, y1 - y0

    def _map(self, fn):
        p = Piece.__new__(Piece)
        p.name = self.name
        p.cut = [([fn(x, y) for x, y in s], c) for s, c in self.cut]
        p.engrave = [([fn(x, y) for x, y in s], c) for s, c in self.engrave]
        p.grid = [([fn(x, y) for x, y in s], c) for s, c in self.grid]
        return p

    def at(self, dx, dy):
        p = self._map(lambda x, y: (x + dx, y + dy))
        p.w, p.h = self.w, self.h
        return p

    def rotated(self):
        """90 degrees, so tall pieces can lie along a narrow vertical strip."""
        h = self.h
        p = self._map(lambda x, y: (h - y, x))
        p.w, p.h = self.h, self.w
        return p

    def scaled(self, k):
        p = self._map(lambda x, y: (x * k, y * k))
        p.w, p.h = self.w * k, self.h * k
        return p


class Doc:
    """Accumulates geometry per layer and writes one SVG."""

    def __init__(self, width=SHEET, height=SHEET):
        self.width, self.height = width, height
        self.layers = {name: [] for name, _, _ in LAYERS}

    def add(self, layer, subpaths):
        self.layers[layer].extend(subpaths)

    def add_piece(self, piece):
        self.add("cut", piece.cut)
        self.add("engrave-detail", piece.engrave)
        self.add("engrave-grid", piece.grid)

    def cut_length(self):
        total = 0.0
        for pts, closed in self.layers["cut"]:
            seq = pts + [pts[0]] if closed else pts
            total += sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))
        return total

    def engrave_length(self):
        total = 0.0
        for layer in ("engrave-grid", "engrave-detail"):
            for pts, closed in self.layers[layer]:
                seq = pts + [pts[0]] if closed else pts
                total += sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))
        return total

    def bounds_ok(self):
        bad = []
        for name, geo in self.layers.items():
            if name == "frame" or not geo:
                continue
            x0, y0, x1, y1 = svgpath.bbox(geo)
            if x0 < MARGIN - 1e-6 or y0 < MARGIN - 1e-6 or x1 > SHEET - MARGIN + 1e-6 or y1 > SHEET - MARGIN + 1e-6:
                bad.append((name, (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))))
        return bad

    def write(self, path):
        body = []
        for name, colour, _ in LAYERS:
            geo = self.layers[name]
            if not geo:
                continue
            body.append(f'<g id="{name}" fill="none" stroke="{colour}" stroke-width="0.1">')
            for pts, closed in geo:
                body.append(f'<path d="{svgpath.to_path_d([(pts, closed)])}"/>')
            body.append("</g>")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
                f'width="{self.width}mm" height="{self.height}mm" '
                f'viewBox="0 0 {self.width} {self.height}">\n'
                + "\n".join(body)
                + "\n</svg>\n"
            )


def rect(x, y, w, h):
    return ([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)


def label(s, x, y, size=3.0):
    return strokefont.text(s, x, y, size)


# ============================== the tile ===================================


def tile_outline():
    """The 300x300 perimeter, detouring into a half-hole at every edge vertex.

    The outer ring of grid vertices sits exactly on the tile edge, so those holes
    are cut in half. Butt two tiles and the halves reform a whole hole spanning
    the seam: the grid stays continuous, walls stand on the join, and a seam key
    dropped in stops the tiles drifting.
    """
    h = HOLE_DRAW / 2
    pts = []

    def edge(along, fixed, horizontal, forward):
        """Walk one edge, biting into each vertex hole."""
        ks = range(1, SQUARES) if forward else range(SQUARES - 1, 0, -1)
        for k in ks:
            c = k * GRID
            a, b = (c - h, c + h) if forward else (c + h, c - h)
            inward = h if fixed == 0 else -h
            for u, v in ((a, 0), (a, inward), (b, inward), (b, 0)):
                pts.append((u, fixed + v) if horizontal else (fixed + v, u))

    # top edge, left to right
    pts.append((h, 0))
    edge(None, 0, True, True)
    pts += [(TILE - h, 0), (TILE - h, h), (TILE, h)]
    # right edge, top to bottom
    edge(None, TILE, False, True)
    pts += [(TILE, TILE - h), (TILE - h, TILE - h), (TILE - h, TILE)]
    # bottom edge, right to left
    edge(None, TILE, True, False)
    pts += [(h, TILE), (h, TILE - h), (0, TILE - h)]
    # left edge, bottom to top
    edge(None, 0, False, False)
    pts += [(0, h), (h, h)]
    return [(pts, True)]


def tile_holes():
    """The 81 interior vertex holes. Edge vertices live in the outline."""
    h = HOLE_DRAW / 2
    out = []
    for i in range(1, SQUARES):
        for j in range(1, SQUARES):
            cx, cy = i * GRID, j * GRID
            out.append(rect(cx - h, cy - h, HOLE_DRAW, HOLE_DRAW))
    return out


def tile_grid_lines():
    """Interior grid lines only: the outer ones are the cut edge."""
    out = []
    for i in range(1, SQUARES):
        out.append(([(i * GRID, 0), (i * GRID, TILE)], False))
        out.append(([(0, i * GRID), (TILE, i * GRID)], False))
    return out


def tile_flagstones(seed=7):
    """One jittered flagstone per square, as outlines.

    Vector outlines engrave in a couple of minutes; a raster fill of the same
    area would take hours. Kept 3.2mm clear of each vertex so a stone never
    runs into a hole.
    """
    if not STONE_TEXTURE:
        return []
    rng = random.Random(seed)
    inset = 3.2
    out = []
    for i in range(SQUARES):
        for j in range(SQUARES):
            x, y = i * GRID, j * GRID
            c = [
                (x + inset + rng.uniform(0, 1.0), y + inset + rng.uniform(0, 1.0)),
                (x + GRID - inset - rng.uniform(0, 1.0), y + inset + rng.uniform(0, 1.0)),
                (x + GRID - inset - rng.uniform(0, 1.0), y + GRID - inset - rng.uniform(0, 1.0)),
                (x + inset + rng.uniform(0, 1.0), y + GRID - inset - rng.uniform(0, 1.0)),
            ]
            out.append((c, True))
    return out


def draw_tile(doc):
    ox = oy = ORIGIN
    doc.add("cut", svgpath.transform(tile_outline(), 1, 1, ox, oy))
    doc.add("cut", svgpath.transform(tile_holes(), 1, 1, ox, oy))
    doc.add("engrave-grid", svgpath.transform(tile_grid_lines(), 1, 1, ox, oy))
    doc.add("engrave-detail", svgpath.transform(tile_flagstones(), 1, 1, ox, oy))


# ============================ walls and doors ==============================


def _tab_span(at_start):
    """Drawn x-range of an end tab, in the near half of the vertex hole."""
    centre = TAB_CLEAR + TAB_LEN / 2
    c = centre if at_start else -centre
    return c - TAB_DRAW / 2, c + TAB_DRAW / 2


def wall(n_squares):
    """A straight wall spanning n grid squares, tabs at both ends.

    The body runs the full vertex-to-vertex length, so collinear walls butt with
    no gap. Only one wall direction can use a vertex, which is what the L-corner
    piece exists to solve.
    """
    L = n_squares * GRID
    a0, a1 = _tab_span(True)
    b0, b1 = (L + s for s in _tab_span(False))
    y = WALL_H
    t = THICKNESS
    pts = [
        (0, 0), (L, 0), (L, y),
        (b1, y), (b1, y + t), (b0, y + t), (b0, y),
        (a1, y), (a1, y + t), (a0, y + t), (a0, y),
        (0, y),
    ]
    return Piece(f"wall{n_squares}", [(pts, True)], _brick(L, WALL_H))


def _brick(L, H, course=4.5, brick=11.0):
    """Running-bond courses, engraved as centre lines."""
    out = []
    rows = max(1, int(round(H / course)))
    for r in range(1, rows):
        y = H * r / rows
        out.append(([(0.6, y), (L - 0.6, y)], False))
    for r in range(rows):
        y0, y1 = H * r / rows, H * (r + 1) / rows
        offset = 0 if r % 2 == 0 else brick / 2
        x = offset + brick
        while x < L - 1.0:
            out.append(([(x, y0 + 0.4), (x, y1 - 0.4)], False))
            x += brick
    return out


def corner_plate(notch_from_top):
    """One half of an L-corner: a 1-square wall plus a half-lap end rebate.

    Two plates cross at 90 degrees, one rebated from the top and one from the
    bottom, interlocking into a rigid L that fills the corner completely. The
    corner vertex carries no tab; the L is held by the tabs at its two far ends.

    The rebate is open at the end rather than an enclosed slot -- an enclosed one
    centred on the corner vertex would leave a 0.15mm sliver of plywood at the
    plate's end, which would snap off the moment it was handled.
    """
    L = GRID + THICKNESS / 2          # left end sits flush with the partner's outer face
    b0, b1 = (L + s for s in _tab_span(False))
    y, t = WALL_H, THICKNESS
    rebate = THICKNESS + 0.2 + 2 * KERF   # cuts out to THICKNESS + 0.2 clearance
    half = WALL_H / 2

    if notch_from_top:
        pts = [(rebate, 0), (L, 0), (L, y), (b1, y), (b1, y + t), (b0, y + t), (b0, y),
               (0, y), (0, half), (rebate, half)]
    else:
        pts = [(0, 0), (L, 0), (L, y), (b1, y), (b1, y + t), (b0, y + t), (b0, y),
               (rebate, y), (rebate, half), (0, half)]
    name = "cornerA" if notch_from_top else "cornerB"
    keep_from = rebate + 0.5
    eng = [s for s in _brick(L, WALL_H) if min(p[0] for p in s[0]) > keep_from]
    return Piece(name, [(pts, True)], eng)


def door():
    """A 1-square wall with an arched opening, open at the sill."""
    L = GRID
    a0, a1 = _tab_span(True)
    b0, b1 = (L + s for s in _tab_span(False))
    y, t = WALL_H, THICKNESS
    ox0, ox1 = L / 2 - 8.0, L / 2 + 8.0
    lintel = 4.0
    arch = [
        (ox1, y),
        (ox1, lintel + 3.0),
    ]
    arch += [
        (L / 2 + 8.0 * math.cos(a), lintel + 3.0 - 3.0 * math.sin(a))
        for a in [i * math.pi / 12 for i in range(1, 12)]
    ]
    arch += [(ox0, lintel + 3.0), (ox0, y)]

    pts = [(0, 0), (L, 0), (L, y), (b1, y), (b1, y + t), (b0, y + t), (b0, y)]
    pts += arch
    pts += [(a1, y), (a1, y + t), (a0, y + t), (a0, y), (0, y)]
    # Brick only on the two posts: courses running the full length would engrave
    # straight across the doorway.
    eng = [s for s in _brick(ox0, WALL_H)]
    eng += svgpath.transform(_brick(L - ox1, WALL_H), 1, 1, ox1, 0)
    return Piece("door", [(pts, True)], eng)


def seam_key():
    """Drops into a seam hole to lock two butted tiles together, sitting flush."""
    return Piece("key", [rect(0, 0, KEY_DRAW, KEY_DRAW)])


# ============================== figures ====================================

_fig_cache = {}


def _circle(cx, cy, r, steps=64):
    return ([(cx + r * math.cos(2 * math.pi * i / steps), cy + r * math.sin(2 * math.pi * i / steps))
             for i in range(steps)], True)


def base_for(span, max_d=BASE_MAX):
    """Slotted disc base. The slot takes everything in the figure's bottom 3mm.

    Diameter follows the slot, because the disc has to keep at least 4mm of wood
    beyond each end of the slot or it snaps in half there.
    """
    finished_span = span - 2 * KERF
    slot_finished = finished_span + 0.4
    d = min(max_d, max(BASE_MIN, slot_finished + 8.0))
    slot_draw = slot_finished - 2 * KERF
    r = d / 2
    body = _circle(r, r, r - KERF)
    slot = rect(r - slot_draw / 2, r - SLOT_DRAW / 2, slot_draw, SLOT_DRAW)
    return Piece("base", [body, slot])


def meeple_figure(name):
    """A class meeple: closed outline to cut, the original art to engrave."""
    key = ("meeple", name)
    if key in _fig_cache:
        return _fig_cache[key]
    art, detail, _ = meeples.fitted(name, FIG_BOX, FIG_BOX)
    cut = outline.cut_outline(art, close_radius=CLOSE_R)
    eng = outline.clip_to(art + detail, cut)
    lo, hi = meeples.bottom_width(cut, THICKNESS)
    span = hi - lo
    _fig_cache[key] = (Piece(name.lower(), cut, eng), span)
    return _fig_cache[key]


def monster_figure(name, height=MONSTER_H):
    key = ("monster", name, height)
    if key in _fig_cache:
        return _fig_cache[key]
    art, detail = shapes.monster(name, height)
    cut = outline.cut_outline(art, close_radius=CLOSE_R_MONSTER, ppmm=28.0)
    eng = outline.clip_to(detail, cut)
    lo, hi = meeples.bottom_width(cut, THICKNESS)
    piece = Piece(name, cut, eng)
    _fig_cache[key] = (piece, hi - lo)
    return _fig_cache[key]


def prop_figure(name, height=PROP_H):
    cut, detail = shapes.prop(name, height)
    eng = outline.clip_to(detail, cut)
    lo, hi = meeples.bottom_width(cut, THICKNESS)
    return Piece(name, cut, eng), hi - lo


# ============================== packing ====================================


class Strip:
    """Shelf packer for one border strip.

    Worked in terms of "along" (down the length of the strip) and "across" (its
    ~38mm depth), because the vertical strips have those two axes swapped
    relative to the sheet.
    """

    def __init__(self, x, y, w, h, rotate=False):
        self.x, self.y, self.w, self.h, self.rotate = x, y, w, h, rotate
        self.length = h if rotate else w
        self.depth = w if rotate else h
        self.cursor = 0.0      # position along the strip
        self.shelf = 0.0       # start of the current shelf, across the strip
        self.shelf_depth = 0.0

    def place(self, piece):
        p = piece.rotated() if self.rotate else piece
        along, across = (p.h, p.w) if self.rotate else (p.w, p.h)
        if along > self.length or across > self.depth:
            return None
        if self.cursor + along > self.length:
            self.shelf += self.shelf_depth + GAP
            self.shelf_depth = 0.0
            self.cursor = 0.0
        if self.shelf + across > self.depth:
            return None
        a, c = self.cursor, self.shelf
        self.cursor += along + GAP
        self.shelf_depth = max(self.shelf_depth, across)
        return p.at(self.x + c, self.y + a) if self.rotate else p.at(self.x + a, self.y + c)


def border_strips():
    """The four strips of plywood left around the tile."""
    lo, hi = MARGIN, SHEET - MARGIN
    return [
        Strip(lo, lo, hi - lo, ORIGIN - lo - GAP),                       # top
        Strip(lo, ORIGIN + TILE + GAP, hi - lo, hi - (ORIGIN + TILE + GAP)),  # bottom
        Strip(lo, ORIGIN, ORIGIN - lo - GAP, TILE, rotate=True),         # left
        Strip(ORIGIN + TILE + GAP, ORIGIN, hi - (ORIGIN + TILE + GAP), TILE, rotate=True),  # right
    ]


def pack(doc, pieces, strips=None):
    """Fill the border strips, biggest first so long walls get the long runs."""
    strips = border_strips() if strips is None else strips
    order = sorted(range(len(pieces)), key=lambda i: -max(pieces[i].w, pieces[i].h))
    unplaced = []
    for i in order:
        piece = pieces[i]
        for strip in strips:
            placed = strip.place(piece)
            if placed is not None:
                doc.add_piece(placed)
                break
        else:
            unplaced.append(piece.name)
    return unplaced


# ============================== sheets =====================================


def figure_and_base(name, kind):
    """A figure and its base, each sized so the pair actually works.

    Props and the boss are allowed a bigger disc; everything else stays on a
    24-28mm base so two figures fit in adjacent squares. If a piece is too wide
    for the largest disc its strip can hold, the piece is scaled down rather
    than the base being allowed to split.
    """
    if kind == "meeple":
        piece, span = meeple_figure(name)
        max_d = BASE_MAX
    elif kind == "monster":
        piece, span = monster_figure(name, BOSS_H if name == "dragon" else MONSTER_H)
        max_d = BIG_BASE if name == "dragon" else BASE_MAX
    else:
        piece, span = prop_figure(name)
        max_d = BIG_BASE
    max_span = max_d - 8.4 + 2 * KERF     # leaves 4mm of wood past each slot end
    if span > max_span:
        k = max_span / span
        piece, span = piece.scaled(k), span * k
    return piece, base_for(span, max_d)


def figure_set(names, kind):
    """Figures plus the base each one needs, as a flat piece list."""
    out = []
    for n in names:
        piece, base = figure_and_base(n, kind)
        out += [piece, base]
    return out


_sheet_cache = {}


def sheet_pieces(which):
    """Every part that sheet carries. Cached: the piece list is built twice,
    once to pack the sheet and once to list it."""
    if which in _sheet_cache:
        return _sheet_cache[which]
    p = []
    if which == "A":
        p += figure_set(meeples.HEROES, "meeple")
        p += figure_set(["barrel", "barrel"], "prop")
        p += [wall(1) for _ in range(10)]
        p += [wall(2) for _ in range(5)]
        p += [corner_plate(True), corner_plate(False)] * 4
        p += [door(), door()]
    elif which == "B":
        p += figure_set(["goblin", "goblin", "skeleton", "skeleton", "orc", "rat", "bat", "slime"], "monster")
        p += figure_set(meeples.NPCS, "meeple")
        p += [wall(2) for _ in range(9)]
        p += [wall(1) for _ in range(4)]
        p += [corner_plate(True), corner_plate(False)] * 4
        p += [door(), door()]
    elif which == "C":
        p += figure_set(["ogre"], "monster")
        p += figure_set(["dragon"], "monster")
        p += [wall(3) for _ in range(6)]
        p += [wall(1) for _ in range(4)]
        p += [corner_plate(True), corner_plate(False)] * 3
        p += figure_set(["chest", "chest", "table", "brazier"], "prop")
    else:
        p += figure_set(["stairs", "altar", "bookshelf", "crate", "well", "pillar", "pillar"], "prop")
        p += [wall(5) for _ in range(4)]
        p += [wall(2) for _ in range(3)]
        p += [corner_plate(True), corner_plate(False)] * 3
        p += [door() for _ in range(4)]
    p += [seam_key() for _ in range(8)]
    _sheet_cache[which] = p
    return p


def build_sheet(which, path):
    doc = Doc()
    doc.add("frame", [rect(MARGIN, MARGIN, SAFE, SAFE)])
    draw_tile(doc)

    # Reserve the start of the top strip for the sheet label, so the packer
    # cannot drop a piece underneath it and engrave the text onto that piece.
    text = f"SHEET {which}"
    size = 4.5
    strips = border_strips()
    reserved = strokefont.width(text, size) + GAP
    strips[0].cursor = reserved
    doc.add("engrave-detail", label(text, MARGIN + 1.0, MARGIN + size + 2.0, size))

    unplaced = pack(doc, sheet_pieces(which), strips)
    doc.write(path)
    return doc, unplaced


# ============================= fit test ====================================


def fit_test_slots():
    """Seven slot widths bracketing the drawn slot width, 0.1mm apart."""
    return [round(SLOT_DRAW - 0.3 + 0.1 * i, 2) for i in range(7)]


def build_fit_test(path):
    """Cut this first. Everything else depends on what it measures."""
    doc = Doc(96.0, 116.0)
    x0, y = 8.0, 14.0

    doc.add("engrave-detail", label("FIT TEST", x0, y - 4, 4.0))

    # Slots to receive a sheet edge-on: find the snuggest, that is THICKNESS-2*KERF.
    # Centred on the current value, so the sweep still brackets it on thinner ply.
    doc.add("engrave-detail", label("SLOT", x0, y + 6, 3.0))
    for i, w in enumerate(fit_test_slots()):
        sx = x0 + 22 + i * 9.5
        doc.add("cut", [rect(sx, y, w, 16.0)])
        doc.add("engrave-detail", label(f"{round(w * 10)}", sx - 1.0, y + 21, 2.6))
    y += 26

    # Vertex holes plus a matching tab: check the tab is snug and sits flush.
    doc.add("engrave-detail", label("HOLE", x0, y + 6, 3.0))
    for i in range(6):
        s = 5.4 + 0.1 * i
        sx = x0 + 22 + i * 11.0
        doc.add("cut", [rect(sx, y, s, s)])
        doc.add("engrave-detail", label(f"{54 + i}", sx - 0.5, y + 12, 2.6))
    y += 20

    # A real wall end and a real seam key, to try in the holes above.
    w = wall(1)
    doc.add_piece(w.at(x0, y))
    doc.add_piece(seam_key().at(x0 + w.w + 6, y))
    y += w.h + 6

    # Half-lap pair: they should cross without forcing.
    a, b = corner_plate(True), corner_plate(False)
    doc.add_piece(a.at(x0, y))
    doc.add_piece(b.at(x0 + a.w + 6, y))
    y += a.h + 8

    doc.add("engrave-detail", label("SET THICKNESS", x0, y + 3, 3.0))
    doc.add("engrave-detail", label("AND KERF, RERUN", x0, y + 8, 3.0))
    doc.add("frame", [rect(2, 2, 92.0, 112.0)])
    doc.write(path)
    return doc


# ============================== preview ====================================


def build_preview(path):
    """Four tiles butted, to confirm the grid runs continuously across seams."""
    doc = Doc(2 * TILE + 20, 2 * TILE + 20)
    for i in (0, 1):
        for j in (0, 1):
            ox, oy = 10 + i * TILE, 10 + j * TILE
            doc.add("cut", svgpath.transform(tile_outline(), 1, 1, ox, oy))
            doc.add("cut", svgpath.transform(tile_holes(), 1, 1, ox, oy))
            doc.add("engrave-grid", svgpath.transform(tile_grid_lines(), 1, 1, ox, oy))
            doc.add("engrave-detail", svgpath.transform(tile_flagstones(), 1, 1, ox, oy))
    doc.write(path)
    return doc


# =============================== main ======================================


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true", help="cut lengths and bounds check")
    ap.add_argument("--out", default="out")
    ap.add_argument("--thickness", type=float, help="plywood thickness in mm (default 3.0)")
    ap.add_argument("--kerf", type=float, help="laser kerf in mm (default 0.15)")
    ap.add_argument("--sheet", type=float, help="plywood sheet size in mm (default 300.0)")
    ap.add_argument("--safe", type=float, help="safe working area in mm (default 280.0)")
    ap.add_argument("--squares", type=int, help="squares per tile edge (default 8)")
    ap.add_argument("--grid", type=float, help="grid pitch in mm (default 25.0)")
    ap.add_argument("--no-png", action="store_true",
                    help="skip the PNG copies of the assembly diagram and piece list")
    ap.add_argument("--dpi", type=int, default=render.DPI,
                    help=f"resolution of those PNGs (default {render.DPI})")
    args = ap.parse_args()
    apply_config(args.thickness, args.kerf, args.sheet, args.safe, args.squares, args.grid)
    print(f"SHEET {SHEET:.0f}x{SHEET:.0f}mm  TILE {TILE:.0f}x{TILE:.0f}mm ({SQUARES}x{SQUARES} squares @ {GRID:.0f}mm)  "
          f"THICKNESS {THICKNESS}mm  KERF {KERF}mm  ->  slot {SLOT_DRAW:.2f}mm, "
          f"hole {HOLE_DRAW:.2f}mm, tab {TAB_DRAW:.2f}mm")

    built = []
    built.append(("00_fit_test", build_fit_test(os.path.join(args.out, "00_fit_test.svg")), []))
    for i, which in enumerate("ABCD", start=1):
        doc, unplaced = build_sheet(which, os.path.join(args.out, f"0{i}_sheet_{which}.svg"))
        built.append((f"0{i}_sheet_{which}", doc, unplaced))
    built.append(("05_preview", build_preview(os.path.join(args.out, "05_preview.svg")), []))
    import sys
    G = sys.modules[__name__]
    assembly.build(os.path.join(args.out, "06_assembly.svg"), G)
    piecelist.build(os.path.join(args.out, "07_piece_list.svg"), G,
                    {w: sheet_pieces(w) for w in "ABCD"})

    print(f"wrote {len(built) + 2} files to {args.out}/")

    # The two reference pages are for reading, not cutting, so they also go out
    # as PNGs -- an SVG will not open on a phone or print predictably.
    if not args.no_png:
        render.render([os.path.join(args.out, "06_assembly.svg"),
                       os.path.join(args.out, "07_piece_list.svg")], args.dpi)
    if not args.report:
        return

    print()
    print(f"{'file':16} {'cut':>9} {'engrave':>9}   {'10W est.':>9}   bounds")
    speed, passes = CUT_SPEED[10]
    problems = 0
    for name, doc, unplaced in built:
        cut_m = doc.cut_length() / 1000.0
        eng_m = doc.engrave_length() / 1000.0
        minutes = (doc.cut_length() * passes / speed) + (doc.engrave_length() / ENGRAVE_SPEED)
        is_sheet = "sheet" in name
        bad = doc.bounds_ok() if is_sheet else []
        note = "ok" if not bad else f"OUT OF BOUNDS {bad}"
        if name == "05_preview":
            note = "reference only, never cut"
        if bad or unplaced:
            problems += 1
        if unplaced:
            note += f"  UNPLACED: {unplaced}"
        print(f"{name:16} {cut_m:7.2f}m {eng_m:7.2f}m   {minutes:6.0f} min   {note}")
    print()
    for w, (speed, passes) in sorted(CUT_SPEED.items()):
        total = sum(
            d.cut_length() * passes / speed + d.engrave_length() / ENGRAVE_SPEED
            for n, d, _ in built if "sheet" in n
        )
        print(f"  {w:2d}W module: {speed:4.0f} mm/min x {passes} passes -> {total / 60:4.1f} h for all four sheets")
    if problems:
        raise SystemExit(f"\n{problems} sheet(s) need attention")


if __name__ == "__main__":
    main()
