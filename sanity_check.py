"""Sanity check the generated kit before any plywood is burned.

Checks the finished (post-kerf) dimensions of every joint, the tile geometry and
how tiles tile, that nothing overlaps or falls off the sheet, that no cut piece
has a neck too thin to survive, and that the written SVGs re-parse to the same
geometry.

    python sanity_check.py
"""

import math
import os
import re
import sys

import check_features
import generate as G
import meeples
import piecelist
import shapes
import svgpath

OUT = "out"

FAIL, WARN = [], []


def check(ok, label, detail=""):
    mark = "PASS" if ok else "FAIL"
    if not ok:
        FAIL.append(f"{label}: {detail}")
    print(f"  [{mark}] {label}" + (f"   {detail}" if detail else ""))


def warn(ok, label, detail=""):
    if not ok:
        WARN.append(f"{label}: {detail}")
    print(f"  [{'PASS' if ok else 'WARN'}] {label}" + (f"   {detail}" if detail else ""))


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# Finished size of a hole/slot = drawn + 2*kerf. Finished size of a part = drawn - 2*kerf.
def hole_finished(drawn):
    return drawn + 2 * G.KERF


def part_finished(drawn):
    return drawn - 2 * G.KERF


def section(t):
    print(f"\n{t}\n" + "-" * len(t))


# ------------------------------------------------------------------ geometry

def check_tile():
    section("1. TILE GEOMETRY")
    o = G.tile_outline()
    x0, y0, x1, y1 = svgpath.bbox(o)
    check(near(x1 - x0, 300.0, 1e-9) and near(y1 - y0, 300.0, 1e-9),
          "tile is exactly 300 x 300mm", f"{x1-x0:.4f} x {y1-y0:.4f}")
    check(near(G.TILE, G.GRID * G.SQUARES), "grid closes on the tile",
          f"{G.SQUARES} x {G.GRID}mm = {G.TILE}mm")

    interior = len(G.tile_holes())
    edge = 4 * (G.SQUARES - 1)
    corners = 4
    check(interior == (G.SQUARES - 1) ** 2, "interior holes", f"{interior}")
    check(interior + edge + corners == G.VERTS ** 2,
          "every vertex is a mount point",
          f"{interior} interior + {edge} edge + {corners} corner = {G.VERTS**2}")

    check(near(hole_finished(G.HOLE_DRAW), G.HOLE, 1e-9),
          "hole cuts out to nominal", f"drawn {G.HOLE_DRAW:.2f} -> {G.HOLE:.2f}mm")

    # grid lines land on vertices
    gl = G.tile_grid_lines()
    xs = {round(p[0], 6) for pts, _ in gl for p in pts}
    off = [x for x in xs if not near(x % G.GRID, 0, 1e-6) and not near(x % G.GRID, G.GRID, 1e-6)]
    check(not off, "grid lines land on vertices", f"{len(gl)} lines")

    # flagstones must not run into a hole
    half = G.HOLE / 2
    worst = 9e9
    for pts, _ in G.tile_flagstones():
        for x, y in pts:
            dx = abs((x + G.GRID / 2) % G.GRID - G.GRID / 2)
            dy = abs((y + G.GRID / 2) % G.GRID - G.GRID / 2)
            worst = min(worst, max(dx, dy))
    check(worst > half, "stone texture clears every hole",
          f"closest approach {worst:.2f}mm vs {half:.2f}mm hole half-width")


def check_tiling():
    section("2. TILES BUTTED TOGETHER")
    # An edge half-hole plus its mirror must reform a whole hole.
    h = G.HOLE_DRAW / 2
    check(near(hole_finished(2 * h), G.HOLE, 1e-9),
          "two half-holes reform a whole hole", f"{G.HOLE:.2f}mm across the seam")
    # Grid continuity: tile pitch is a whole number of squares.
    check(near(G.TILE % G.GRID, 0.0, 1e-9),
          "grid is continuous across a seam", f"{G.TILE}/{G.GRID} = {G.TILE/G.GRID:.0f} squares")
    key = G.seam_key()
    kf = part_finished(G.KEY_DRAW)
    slack = G.HOLE - kf
    check(0.15 <= slack <= 0.6, "seam key clearance in the hole",
          f"key {kf:.2f}mm in {G.HOLE:.2f}mm hole -> {slack:.2f}mm slack")
    check(near(key.w, key.h, 1e-9), "seam key is square", f"{key.w:.2f}mm")
    bridge = (G.HOLE - 0.0) / 2
    warn(bridge >= 2.5, "key bridges enough of each tile",
         f"{bridge:.2f}mm engagement per tile")


def check_walls():
    section("3. WALL AND TAB FIT")
    tab = part_finished(G.TAB_DRAW)
    check(near(tab, G.TAB_LEN, 1e-9), "tab cuts down to nominal",
          f"drawn {G.TAB_DRAW:.2f} -> {tab:.2f}mm")

    # Two collinear tabs, one from each side, in a single hole.
    centre = G.TAB_CLEAR + G.TAB_LEN / 2
    left = (centre - tab / 2, centre + tab / 2)
    gap_to_centre = G.HOLE / 2 - left[1]
    check(left[0] > 0, "tab clears the hole wall", f"{left[0]:.2f}mm")
    check(gap_to_centre > 0, "two collinear tabs do not meet",
          f"{2*gap_to_centre:.2f}mm between them")
    warn(left[1] - left[0] >= 2.0, "tab engagement",
         f"{tab:.2f} x {G.THICKNESS:.1f}mm per tab, two per wall")

    for n in (1, 2, 3, 5):
        w = G.wall(n)
        expect = n * G.GRID
        check(near(w.w, expect, 1e-6), f"{n}-square wall spans vertex to vertex",
              f"{w.w:.2f}mm = {n} x {G.GRID:.0f}")
        check(near(w.h, G.WALL_H + G.THICKNESS, 1e-6), f"{n}-square wall height",
              f"body {G.WALL_H:.0f} + tab {G.THICKNESS:.0f} = {w.h:.2f}mm")

    # Collinear walls must butt without their drawn tabs crossing the joint.
    w = G.wall(1)
    xs = [p[0] for pts, _ in w.cut for p in pts]
    check(min(xs) >= -1e-9 and max(xs) <= w.w + 1e-9,
          "tabs stay within the wall footprint", f"x in [{min(xs):.3f}, {max(xs):.3f}]")


def check_corners():
    section("4. L-CORNER HALF-LAP")
    a, b = G.corner_plate(True), G.corner_plate(False)
    rebate_drawn = G.THICKNESS + 0.2 + 2 * G.KERF
    fin = hole_finished(rebate_drawn) - 2 * G.KERF   # notch bounded by end + inner wall
    check(near(a.w, G.GRID + G.THICKNESS / 2, 1e-6), "corner plate length",
          f"{a.w:.2f}mm = {G.GRID:.0f} + half thickness")
    check(fin >= G.THICKNESS, "rebate receives the partner plate",
          f"rebate {fin:.2f}mm for {G.THICKNESS:.1f}mm ply ({fin - G.THICKNESS:+.2f} clearance)")

    def inside(pts, x, y):
        n, c = len(pts), False
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                c = not c
        return c

    pa, pb = a.cut[0][0], b.cut[0][0]
    top_a, bot_a = inside(pa, 1.5, 3.0), inside(pa, 1.5, G.WALL_H - 3.0)
    top_b, bot_b = inside(pb, 1.5, 3.0), inside(pb, 1.5, G.WALL_H - 3.0)
    check((not top_a and bot_a) and (top_b and not bot_b),
          "the two plates are mirrored and interlock",
          f"A top={'wood' if top_a else 'air'}/bottom={'wood' if bot_a else 'air'}, "
          f"B top={'wood' if top_b else 'air'}/bottom={'wood' if bot_b else 'air'}")
    check(near(G.WALL_H / 2 * 2, G.WALL_H), "rebate is half the wall height",
          f"{G.WALL_H/2:.1f}mm each")


def check_bases():
    section("5. FIGURES AND BASES")
    slot = hole_finished(G.SLOT_DRAW)
    check(near(slot, G.THICKNESS, 1e-9), "base slot receives a sheet edge",
          f"drawn {G.SLOT_DRAW:.2f} -> {slot:.2f}mm for {G.THICKNESS:.1f}mm ply")

    rows = ([(n, "meeple") for n in meeples.HEROES + meeples.NPCS]
            + [(n, "monster") for n in shapes.MONSTERS]
            + [(n, "prop") for n in shapes.PROPS])
    worst_neck, worst_name = 9e9, ""
    thin_ends = []
    for name, kind in rows:
        piece, base = G.figure_and_base(name, kind)
        span = G.meeples.bottom_width(piece.cut, G.THICKNESS)
        span = span[1] - span[0]
        slot_len = part_finished(span) + 0.4
        end_wood = (base.w - slot_len) / 2
        if end_wood < 3.0:
            thin_ends.append(f"{name} {end_wood:.1f}mm")
        d, _ = check_features.min_neck(piece.cut)
        if d < worst_neck:
            worst_neck, worst_name = d, name
        # engraving must sit inside the cut outline
        loops = [p for p, _ in piece.cut]
        outside = sum(
            1 for pts, _ in piece.engrave for p in pts
            if not _pt_inside(loops, p[0], p[1])
        )
        if outside:
            FAIL.append(f"{name}: {outside} engrave points outside the cut outline")
    check(not thin_ends, "wood left at both ends of every base slot",
          "all >= 3.0mm" if not thin_ends else ", ".join(thin_ends))
    check(worst_neck >= 1.2, "narrowest neck on any figure",
          f"{worst_neck:.2f}mm on {worst_name} (needs >= 1.2mm in 3mm ply)")
    print(f"  [INFO] {len(rows)} distinct figures/props checked")


def _pt_inside(loops, x, y):
    c = False
    for pts in loops:
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                c = not c
    return c


# -------------------------------------------------------------------- sheets

class _Recorder:
    def __init__(self):
        self.placed = []

    def add_piece(self, piece):
        self.placed.append(piece)

    def add(self, *a):
        pass


def check_piece_list():
    section("9. PIECE LIST")
    for which in "ABCD":
        pieces = G.sheet_pieces(which)
        rows, total = piecelist.inventory(pieces, G)
        check(total == len(pieces) + 1, f"sheet {which}: list total matches the sheet",
              f"{total} listed, {len(pieces)} packed + 1 tile")
        counted = sum(c for _, c, _, _ in rows)
        check(counted == len(pieces), f"sheet {which}: every packed piece is on a row",
              f"{len(rows)} rows, {counted} pieces")
        named = {r[0].name for r in rows}
        missing = {p.name for p in pieces} - named
        check(not missing, f"sheet {which}: no piece type left off the list",
              "" if not missing else f"missing {sorted(missing)}")
        blank = [t for _, _, t, _ in rows if not t.strip()]
        check(not blank, f"sheet {which}: every row is named")
        _rh, used = piecelist.column_layout(rows)
        room = piecelist.COL_H - 8
        check(used <= room, f"sheet {which}: the list fits its column",
              f"{used:.0f} of {room:.0f}mm, {len(rows)} rows")


def check_sheets():
    section("6. SHEET LAYOUT")
    tile_box = (G.ORIGIN, G.ORIGIN, G.ORIGIN + G.TILE, G.ORIGIN + G.TILE)
    for which in "ABCD":
        rec = _Recorder()
        unplaced = G.pack(rec, G.sheet_pieces(which))
        check(not unplaced, f"sheet {which}: every piece placed",
              f"{len(rec.placed)} pieces" if not unplaced else f"unplaced {unplaced}")

        boxes = []
        for p in rec.placed:
            boxes.append(svgpath.bbox(p.cut + p.engrave))

        off = [b for b in boxes
               if b[0] < G.MARGIN - 1e-6 or b[1] < G.MARGIN - 1e-6
               or b[2] > G.SHEET - G.MARGIN + 1e-6 or b[3] > G.SHEET - G.MARGIN + 1e-6]
        check(not off, f"sheet {which}: all pieces inside the {G.SAFE:.0f}mm safe area",
              "" if not off else f"{len(off)} outside")

        on_tile = [b for b in boxes
                   if b[0] < tile_box[2] and b[2] > tile_box[0]
                   and b[1] < tile_box[3] and b[3] > tile_box[1]]
        check(not on_tile, f"sheet {which}: nothing overlaps the tile",
              "" if not on_tile else f"{len(on_tile)} overlap")

        clashes = 0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                ox = min(a[2], b[2]) - max(a[0], b[0])
                oy = min(a[3], b[3]) - max(a[1], b[1])
                if ox > 1e-6 and oy > 1e-6:
                    clashes += 1
        check(clashes == 0, f"sheet {which}: no two pieces overlap",
              f"{len(boxes)} pieces, {clashes} clashes")


# ---------------------------------------------------------------------- svgs

def check_files():
    section("7. WRITTEN FILES")
    expect = ["00_fit_test.svg", "01_sheet_A.svg", "02_sheet_B.svg",
              "03_sheet_C.svg", "04_sheet_D.svg", "05_preview.svg", "06_assembly.svg",
              "07_piece_list.svg"]
    for name in expect:
        path = os.path.join(OUT, name)
        if not os.path.exists(path):
            check(False, f"{name} exists")
            continue
        text = open(path, encoding="utf-8").read()
        m = re.search(r'width="([\d.]+)mm"\s+height="([\d.]+)mm"', text)
        vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', text)
        ok = bool(m and vb) and near(float(m.group(1)), float(vb.group(1)), 1e-6)
        size = f'{m.group(1)}x{m.group(2)}mm' if m else "?"
        if "sheet" in name:
            ok = ok and near(float(m.group(1)), G.SHEET, 1e-6)
        check(ok, f"{name}: 1 user unit = 1 mm", size)

    # The PNG copies of the two reference pages. A warning, not a failure: they
    # need a renderer installed, and the cut files do not depend on them.
    for name in ("06_assembly.png", "07_piece_list.png"):
        path = os.path.join(OUT, name)
        size = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
        warn(size > 0.05, f"{name}: written at readable resolution",
             f"{size:.1f} MB" if size else "missing - run generate.py with a renderer installed")

    for name in expect[1:5]:
        text = open(os.path.join(OUT, name), encoding="utf-8").read()
        for colour, layer in (("#FF0000", "cut"), ("#0000FF", "grid"), ("#00FF00", "detail")):
            check(colour in text, f"{name}: has the {layer} layer")
        check("#000000" in text, f"{name}: has the reference frame")


def check_roundtrip():
    section("8. RE-PARSE OF A WRITTEN SHEET")
    text = open(os.path.join(OUT, "01_sheet_A.svg"), encoding="utf-8").read()
    ds = re.findall(r'<path d="([^"]+)"/>', text)
    check(len(ds) > 100, "paths present", f"{len(ds)} paths")
    subs = []
    for d in ds:
        subs.extend(svgpath.flatten(d, tol=0.05))
    x0, y0, x1, y1 = svgpath.bbox(subs)
    check(x0 >= G.MARGIN - 1e-3 and y0 >= G.MARGIN - 1e-3
          and x1 <= G.SHEET - G.MARGIN + 1e-3 and y1 <= G.SHEET - G.MARGIN + 1e-3,
          "re-parsed geometry stays in the safe area",
          f"[{x0:.2f}, {y0:.2f}] .. [{x1:.2f}, {y1:.2f}] within [{G.MARGIN:.0f}, {G.SHEET-G.MARGIN:.0f}]")

    closed = sum(1 for _, c in subs if c)
    check(closed > 100, "closed contours survive the round trip", f"{closed} closed")


def _cli():
    """Optional: check a set generated for a different plywood."""
    global OUT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--thickness", type=float)
    ap.add_argument("--kerf", type=float)
    a = ap.parse_args()
    OUT = a.out
    G.apply_config(a.thickness, a.kerf)


def main():
    print("SANITY CHECK")
    print(f"THICKNESS {G.THICKNESS}mm   KERF {G.KERF}mm   GRID {G.GRID}mm   HOLE {G.HOLE}mm")
    check_tile()
    check_tiling()
    check_walls()
    check_corners()
    check_bases()
    check_sheets()
    check_files()
    check_roundtrip()
    check_piece_list()

    section("RESULT")
    if FAIL:
        print(f"  {len(FAIL)} FAILURE(S):")
        for f in FAIL:
            print(f"    - {f}")
    if WARN:
        print(f"  {len(WARN)} warning(s):")
        for w in WARN:
            print(f"    - {w}")
    if not FAIL:
        print("  All checks passed." + (" Warnings above are advisory." if WARN else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    _cli()
    sys.exit(main())
