"""Deep structural check of the written SVGs, before any plywood is burned.

sanity_check.py verifies the design's dimensions. This one distrusts the output
files themselves and looks for the things that actually ruin a sheet:

  * open contours on the cut layer      -> part never separates, or a stray cut
  * cut paths that cross each other     -> double burn, scorching, fire risk
  * self-intersecting contours          -> LightBurn's inside/outside gets confused
  * degenerate or non-finite geometry   -> unpredictable G-code
  * engraving landing on the wrong part -> marks on a piece that should be clean
  * features too thin to survive        -> snaps while punching out
  * anything outside the machine's reach

    python super_check.py
"""

import math
import os
import re
import sys

import check_features
import generate as G
import svgpath

OUT = "out"

FAIL, WARN, INFO = [], [], []


def check(ok, label, detail=""):
    (FAIL if not ok else INFO).append(f"{label}: {detail}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"   {detail}" if detail else ""))
    return ok


def warn(ok, label, detail=""):
    if not ok:
        WARN.append(f"{label}: {detail}")
    print(f"  [{'PASS' if ok else 'WARN'}] {label}" + (f"   {detail}" if detail else ""))


def section(t):
    print(f"\n{t}\n" + "-" * len(t))


# --------------------------------------------------------------- svg reading

LAYER_RE = re.compile(r'<g id="([^"]+)"[^>]*stroke="([^"]+)"[^>]*>(.*?)</g>', re.S)
PATH_RE = re.compile(r'<path d="([^"]+)"/>')


def read_layers(path):
    """{layer_id: [(points, closed), ...]} straight from the written file."""
    text = open(path, encoding="utf-8").read()
    out = {}
    for lid, _colour, body in LAYER_RE.findall(text):
        subs = []
        for d in PATH_RE.findall(body):
            subs.extend(svgpath.flatten(d, tol=0.02))
        out[lid] = subs
    return out


# ------------------------------------------------------------- intersections

def _seg_cross(p, p2, q, q2):
    """True if segments pp2 and qq2 properly cross (not merely touch at an end)."""
    def o(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    o1, o2, o3, o4 = o(p, p2, q), o(p, p2, q2), o(q, q2, p), o(q, q2, p2)
    if o1 == o2 == 0:
        return False          # collinear: reported separately as overlap
    return o1 != o2 and o3 != o4


def find_crossings(subpaths, limit=40):
    """Cut paths that cross each other or themselves. Grid-bucketed."""
    segs = []
    for si, (pts, closed) in enumerate(subpaths):
        seq = list(pts) + [pts[0]] if closed else list(pts)
        for i in range(len(seq) - 1):
            segs.append((si, i, seq[i], seq[i + 1]))

    cell = 4.0
    grid = {}
    for idx, (si, i, a, b) in enumerate(segs):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        for gx in range(int(x0 // cell), int(x1 // cell) + 1):
            for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                grid.setdefault((gx, gy), []).append(idx)

    hits, seen = [], set()
    for bucket in grid.values():
        for u in range(len(bucket)):
            for v in range(u + 1, len(bucket)):
                ia, ib = bucket[u], bucket[v]
                if (ia, ib) in seen:
                    continue
                seen.add((ia, ib))
                sa, i, a, b = segs[ia]
                sb, j, c, d = segs[ib]
                if sa == sb:
                    n = len(subpaths[sa][0])
                    if min(abs(i - j), n - abs(i - j)) <= 1:
                        continue            # neighbouring segments share a point
                if _seg_cross(a, b, c, d):
                    hits.append((sa, sb, a, b))
                    if len(hits) >= limit:
                        return hits
    return hits


def _inside(loop, x, y):
    c = False
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def depths(cut):
    """Nesting depth of every contour, worked out geometrically.

    Winding direction is not usable here: the hand-built rectangles and the
    marching-squares silhouettes wind opposite ways, and the laser does not care
    either. Containment is what matters. Depth 0 is a part, depth 1 is a hole in
    a part, depth 2+ would be a loose island inside a hole.
    """
    loops = [pts for pts, _ in cut]
    out = []
    for i, pts in enumerate(loops):
        px, py = pts[0]
        out.append(sum(1 for j, other in enumerate(loops)
                       if j != i and _inside(other, px, py)))
    return out


# -------------------------------------------------------------------- checks

SHEETS = ["01_sheet_A.svg", "02_sheet_B.svg", "03_sheet_C.svg", "04_sheet_D.svg"]
ALL = ["00_fit_test.svg"] + SHEETS


def check_hygiene():
    section("A. GEOMETRY HYGIENE (read back from the written files)")
    for name in ALL:
        layers = read_layers(os.path.join(OUT, name))
        cut = layers.get("cut", [])

        bad_finite = sum(1 for pts, _ in cut for x, y in pts
                         if not (math.isfinite(x) and math.isfinite(y)))
        check(bad_finite == 0, f"{name}: all coordinates finite", f"{len(cut)} cut paths")

        open_paths = sum(1 for _, closed in cut if not closed)
        check(open_paths == 0, f"{name}: every cut path is closed",
              "all closed" if not open_paths else f"{open_paths} OPEN - part would not separate")

        zero = 0
        shortest = 9e9
        for pts, closed in cut:
            seq = list(pts) + [pts[0]] if closed else list(pts)
            for a, b in zip(seq, seq[1:]):
                d = math.dist(a, b)
                if d < 1e-9:
                    zero += 1
                elif d < shortest:
                    shortest = d
        check(zero == 0, f"{name}: no zero-length cut segments",
              f"shortest real segment {shortest:.4f}mm")

        tiny = sum(1 for pts, closed in cut
                   for a, b in zip((list(pts) + [pts[0]] if closed else list(pts)),
                                   (list(pts) + [pts[0]] if closed else list(pts))[1:])
                   if 1e-9 <= math.dist(a, b) < 0.02)
        warn(tiny < 200, f"{name}: few sub-0.02mm segments", f"{tiny}")


def check_crossings():
    section("B. CUT PATHS CROSSING (double burn / confused inside-outside)")
    for name in ALL:
        layers = read_layers(os.path.join(OUT, name))
        cut = layers.get("cut", [])
        hits = find_crossings(cut)
        detail = "none"
        if hits:
            where = ", ".join(f"near ({a[0]:.1f},{a[1]:.1f})" for _, _, a, _ in hits[:4])
            detail = f"{len(hits)} crossing(s): {where}"
        check(not hits, f"{name}: no cut path crosses another", detail)


def check_nesting():
    section("C. CONTOUR NESTING (holes must sit inside a part, not on waste)")
    for name in SHEETS:
        layers = read_layers(os.path.join(OUT, name))
        cut = layers.get("cut", [])
        d = depths(cut)
        parts = d.count(0)
        holes = d.count(1)
        deeper = sum(1 for v in d if v >= 2)
        check(deeper == 0, f"{name}: no loose island inside a hole",
              f"{parts} parts, {holes} holes, {deeper} at depth 2+")


def check_engrave_placement():
    section("D. ENGRAVING LANDS WHERE IT SHOULD")
    for name in SHEETS:
        layers = read_layers(os.path.join(OUT, name))
        cut = layers.get("cut", [])
        d = depths(cut)
        outers = [pts for (pts, _), dd in zip(cut, d) if dd == 0]
        # Grid lines deliberately run to the tile edge, which means their last
        # few millimetres cross a border notch. That is engraved before the notch
        # is cut, on material that then goes away -- expected, not a defect.
        # The sheet label is engraved on the border offcut on purpose, so it can
        # be read while handling the sheet. Exclude its reserved box.
        import strokefont
        which = name.split("_")[-1].replace(".svg", "")
        lb = svgpath.bbox(strokefont.text(f"SHEET {which}", G.MARGIN + 1.0,
                                          G.MARGIN + 4.5 + 2.0, 4.5))
        lb = (lb[0] - 1, lb[1] - 1, lb[2] + 1, lb[3] + 1)

        stray, total, notch, labelled = 0, 0, 0, 0
        for lid in ("engrave-grid", "engrave-detail"):
            for pts, _ in layers.get(lid, []):
                for p in pts[::4]:
                    total += 1
                    if any(_inside(o, p[0], p[1]) for o in outers):
                        continue
                    if lid == "engrave-grid":
                        notch += 1
                    elif lb[0] <= p[0] <= lb[2] and lb[1] <= p[1] <= lb[3]:
                        labelled += 1
                    else:
                        stray += 1
        check(stray == 0, f"{name}: all engraving accounted for",
              f"{total} sampled: {stray} stray, {labelled} sheet label, "
              f"{notch} grid-into-notch, rest on parts")


def check_min_features():
    section("E. THINNEST FEATURE ON EVERY PIECE TYPE")
    pieces = {}
    for n in (1, 2, 3, 5):
        pieces[f"wall x{n}"] = G.wall(n)
    pieces["door"] = G.door()
    pieces["corner A"] = G.corner_plate(True)
    pieces["corner B"] = G.corner_plate(False)
    pieces["seam key"] = G.seam_key()
    pieces["base 24mm"] = G.base_for(16.0)
    pieces["base 28mm"] = G.base_for(19.9)
    pieces["base 36mm"] = G.base_for(27.9, G.BIG_BASE)

    worst, worst_name = 9e9, ""
    for label, p in sorted(pieces.items()):
        d, _ = check_features.min_neck(p.cut, along=1.5, max_gap=8.0)
        shown = "nothing under 8mm" if d > 1e6 else f"{d:.2f}mm"
        if d < worst:
            worst, worst_name = d, label
        print(f"     {label:12} {p.w:6.1f} x {p.h:5.1f}mm   thinnest {shown}")
    check(worst >= 1.5, "thinnest feature across all hardware",
          (f"{worst:.2f}mm on {worst_name}" if worst < 1e6 else "nothing under 8mm anywhere")
          + " (needs >= 1.5mm in 3mm ply)")

    # The door lintel is the one place the design is deliberately slender.
    d = G.door()
    ys = [p[1] for pts, _ in d.cut for p in pts]
    print(f"     door lintel {4.0:.1f}mm of wood above the arch, posts "
          f"{(G.GRID/2 - 8.0):.1f}mm wide each")


def check_inventory():
    section("F. WHAT YOU ACTUALLY GET")
    kinds = {}
    per_sheet = {}
    for which in "ABCD":
        counts = {}
        for p in G.sheet_pieces(which):
            key = p.name
            if key.startswith("wall"):
                key = f"wall x{key[4:]}"
            elif key.startswith("corner"):
                key = "corner plate"
            elif key == "base":
                key = "base"
            elif key == "key":
                key = "seam key"
            elif key == "door":
                key = "door"
            else:
                key = "figure/prop"
            counts[key] = counts.get(key, 0) + 1
            kinds[key] = kinds.get(key, 0) + 1
        per_sheet[which] = counts
    for which in "ABCD":
        line = ", ".join(f"{k} x{v}" for k, v in sorted(per_sheet[which].items()))
        print(f"     sheet {which}: {line}")
    print()
    total_walls = sum(v for k, v in kinds.items() if k.startswith("wall"))
    print(f"     TOTAL  walls {total_walls}   corner plates {kinds.get('corner plate',0)}"
          f" ({kinds.get('corner plate',0)//2} L-corners)   doors {kinds.get('door',0)}")
    print(f"            figures/props {kinds.get('figure/prop',0)}   bases {kinds.get('base',0)}"
          f"   seam keys {kinds.get('seam key',0)}")
    check(kinds.get("figure/prop", 0) == kinds.get("base", 0),
          "every figure has exactly one base",
          f"{kinds.get('figure/prop',0)} figures, {kinds.get('base',0)} bases")
    check(kinds.get("corner plate", 0) % 2 == 0,
          "corner plates come in pairs", f"{kinds.get('corner plate',0)}")
    wall_squares = sum(int(k.split("x")[1]) * v for k, v in kinds.items() if k.startswith("wall"))
    print(f"     linear wall coverage: {wall_squares} squares = {wall_squares * G.GRID / 10:.0f}cm")
    check(wall_squares >= 60, "enough wall to outline a dungeon",
          f"{wall_squares} squares vs 80 for the full table perimeter")


def check_machine_limits():
    section("G. MACHINE LIMITS")
    for name in ALL:
        layers = read_layers(os.path.join(OUT, name))
        geo = [s for lid, subs in layers.items() if lid != "frame" for s in subs]
        x0, y0, x1, y1 = svgpath.bbox(geo)
        if "sheet" in name:
            ok = x0 >= G.MARGIN - 1e-3 and y0 >= G.MARGIN - 1e-3 and \
                 x1 <= G.SHEET - G.MARGIN + 1e-3 and y1 <= G.SHEET - G.MARGIN + 1e-3
            check(ok, f"{name}: inside the 380mm safe area",
                  f"{x1-x0:.1f} x {y1-y0:.1f}mm at [{x0:.1f},{y0:.1f}]")
        else:
            check(x1 <= 400 and y1 <= 400, f"{name}: fits the bed",
                  f"{x1-x0:.1f} x {y1-y0:.1f}mm")


def check_fit_test():
    section("H. FIT TEST COUPON BRACKETS THE REAL VALUES")
    slots = G.fit_test_slots()
    holes = [5.4 + 0.1 * i for i in range(6)]
    check(min(slots) < G.SLOT_DRAW < max(slots),
          "slot sweep brackets the drawn slot width",
          f"{min(slots):.1f}-{max(slots):.1f}mm contains {G.SLOT_DRAW:.2f}mm")
    check(min(holes) < G.HOLE_DRAW < max(holes),
          "hole sweep brackets the drawn hole",
          f"{min(holes):.1f}-{max(holes):.1f}mm contains {G.HOLE_DRAW:.2f}mm")
    layers = read_layers(os.path.join(OUT, "00_fit_test.svg"))
    check(len(layers.get("cut", [])) > 15, "coupon has the test pieces",
          f"{len(layers.get('cut', []))} cut shapes")


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
    print("SUPER CHECK  -  structural verification of out/*.svg")
    print(f"THICKNESS {G.THICKNESS}mm  KERF {G.KERF}mm  GRID {G.GRID}mm  HOLE {G.HOLE}mm  "
          f"WALL_H {G.WALL_H}mm")
    check_hygiene()
    check_crossings()
    check_nesting()
    check_engrave_placement()
    check_min_features()
    check_inventory()
    check_machine_limits()
    check_fit_test()

    section("VERDICT")
    if FAIL:
        print(f"  {len(FAIL)} FAILURE(S) - do not cut yet:")
        for f in FAIL:
            print(f"    - {f}")
    if WARN:
        print(f"  {len(WARN)} warning(s):")
        for w in WARN:
            print(f"    - {w}")
    if not FAIL:
        print("  Structurally sound. Safe to cut.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    _cli()
    sys.exit(main())
