"""Turn detailed line art into an outline that survives being cut from plywood.

The class silhouettes carry weapons, cloaks and shields separated from the body
by slits well under a millimetre at the size we cut them: narrower than the laser
kerf, so the feature would simply fall out. The fix is a morphological closing.
Fill the shape into a bitmap, dilate then erode by the same radius, and re-trace.
Slits narrower than 2r merge into solid wood while the outer profile stays put.
The original art is then engraved on top, so the detail is still visible; it just
stops being a structural hole.

Standard library only: a scanline fill, a 5-7-11 chamfer distance transform,
marching squares, and Douglas-Peucker simplification.
"""

import math

import svgpath

# 5-7-11 chamfer weights, scaled by 5, so a unit orthogonal step costs 5.
_ORTHO, _DIAG, _KNIGHT, _UNIT = 5, 7, 11, 5
_BIG = 1 << 28


def fill_mask(subpaths, ppmm, pad_mm):
    """Rasterise the outline with the even-odd rule.

    Returns (mask, w, h, ox, oy) where mask is a bytearray of 0/1 and (ox, oy)
    is the mm position of pixel (0, 0).
    """
    x0, y0, x1, y1 = svgpath.bbox(subpaths)
    ox, oy = x0 - pad_mm, y0 - pad_mm
    w = int(math.ceil((x1 - x0 + 2 * pad_mm) * ppmm)) + 1
    h = int(math.ceil((y1 - y0 + 2 * pad_mm) * ppmm)) + 1
    mask = bytearray(w * h)

    edges = []
    for pts, _ in subpaths:
        # Every subpath is treated as closed for filling purposes.
        loop = list(pts)
        if loop[0] != loop[-1]:
            loop.append(loop[0])
        for (ax, ay), (bx, by) in zip(loop, loop[1:]):
            if ay == by:
                continue
            edges.append(
                ((ax - ox) * ppmm, (ay - oy) * ppmm, (bx - ox) * ppmm, (by - oy) * ppmm)
            )

    for py in range(h):
        yc = py + 0.5
        xs = []
        for ax, ay, bx, by in edges:
            if (ay <= yc < by) or (by <= yc < ay):
                xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
        if not xs:
            continue
        xs.sort()
        row = py * w
        for i in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[i] - 0.5)))
            b = min(w - 1, int(math.floor(xs[i + 1] - 0.5)))
            for px in range(a, b + 1):
                mask[row + px] = 1
    return mask, w, h, ox, oy


def _chamfer_dt(mask, w, h, seed_value):
    """Distance in chamfer units from every pixel to the nearest pixel whose
    value equals seed_value. Two raster passes, 5-7-11 neighbourhood."""
    d = [0 if mask[i] == seed_value else _BIG for i in range(w * h)]

    for y in range(h):
        base = y * w
        for x in range(w):
            i = base + x
            if d[i] == 0:
                continue
            best = d[i]
            if x > 0:
                best = min(best, d[i - 1] + _ORTHO)
            if y > 0:
                best = min(best, d[i - w] + _ORTHO)
                if x > 0:
                    best = min(best, d[i - w - 1] + _DIAG)
                if x < w - 1:
                    best = min(best, d[i - w + 1] + _DIAG)
                if x > 1:
                    best = min(best, d[i - w - 2] + _KNIGHT)
                if x < w - 2:
                    best = min(best, d[i - w + 2] + _KNIGHT)
            if y > 1:
                if x > 0:
                    best = min(best, d[i - 2 * w - 1] + _KNIGHT)
                if x < w - 1:
                    best = min(best, d[i - 2 * w + 1] + _KNIGHT)
            d[i] = best

    for y in range(h - 1, -1, -1):
        base = y * w
        for x in range(w - 1, -1, -1):
            i = base + x
            if d[i] == 0:
                continue
            best = d[i]
            if x < w - 1:
                best = min(best, d[i + 1] + _ORTHO)
            if y < h - 1:
                best = min(best, d[i + w] + _ORTHO)
                if x < w - 1:
                    best = min(best, d[i + w + 1] + _DIAG)
                if x > 0:
                    best = min(best, d[i + w - 1] + _DIAG)
                if x < w - 2:
                    best = min(best, d[i + w + 2] + _KNIGHT)
                if x > 1:
                    best = min(best, d[i + w - 2] + _KNIGHT)
            if y < h - 2:
                if x < w - 1:
                    best = min(best, d[i + 2 * w + 1] + _KNIGHT)
                if x > 0:
                    best = min(best, d[i + 2 * w - 1] + _KNIGHT)
            d[i] = best
    return d


def close(mask, w, h, r_px):
    """Morphological closing by a disk of radius r_px."""
    limit = r_px * _UNIT
    dt_out = _chamfer_dt(mask, w, h, 1)
    dilated = bytearray(1 if dt_out[i] <= limit else 0 for i in range(w * h))
    dt_in = _chamfer_dt(dilated, w, h, 0)
    return bytearray(1 if dt_in[i] > limit else 0 for i in range(w * h))


# Marching-squares edge table. Corners are read clockwise from top-left as
# bits 8, 4, 2, 1. Every segment is *directed* so that filled material lies to
# the left of travel; without that consistency the chaining below dead-ends and
# returns shredded fragments instead of loops.
_T, _R, _B, _L = (0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)
_CASES = {
    1: [(_B, _L)],
    2: [(_R, _B)],
    3: [(_R, _L)],
    4: [(_T, _R)],
    6: [(_T, _B)],
    7: [(_T, _L)],
    8: [(_L, _T)],
    9: [(_B, _T)],
    11: [(_R, _T)],
    12: [(_L, _R)],
    13: [(_B, _R)],
    14: [(_L, _B)],
    5: [(_T, _R), (_B, _L)],
    10: [(_L, _T), (_R, _B)],
}


def contours(mask, w, h):
    """Marching squares, returning closed loops in pixel coordinates."""
    segs = {}
    for y in range(h - 1):
        r0, r1 = y * w, (y + 1) * w
        for x in range(w - 1):
            code = (
                mask[r0 + x] * 8
                + mask[r0 + x + 1] * 4
                + mask[r1 + x + 1] * 2
                + mask[r1 + x]
            )
            for (ax, ay), (bx, by) in _CASES.get(code, ()):
                a = (round((x + ax) * 2), round((y + ay) * 2))
                b = (round((x + bx) * 2), round((y + by) * 2))
                segs.setdefault(a, []).append(b)

    loops = []
    while segs:
        start = next(iter(segs))
        loop = [start]
        cur = start
        while True:
            nxt = segs.get(cur)
            if not nxt:
                break
            n = nxt.pop()
            if not nxt:
                del segs[cur]
            loop.append(n)
            cur = n
            if cur == start:
                break
        if len(loop) > 8:
            loops.append([(px / 2.0, py / 2.0) for px, py in loop])
    return loops


def simplify(pts, tol):
    """Douglas-Peucker, iterative so long contours cannot blow the stack."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = pts[i]
        bx, by = pts[j]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        worst, wi = -1.0, -1
        for k in range(i + 1, j):
            px, py = pts[k]
            dist = (
                abs(dx * (ay - py) - (ax - px) * dy) / norm
                if norm
                else math.hypot(px - ax, py - ay)
            )
            if dist > worst:
                worst, wi = dist, k
        if worst > tol:
            keep[wi] = True
            stack.append((i, wi))
            stack.append((wi, j))
    return [p for p, k in zip(pts, keep) if k]


def smooth(pts, rounds=2):
    """Weighted averaging to take the stair-step off a traced contour."""
    out = pts
    for _ in range(rounds):
        n = len(out)
        out = [
            (
                (out[(i - 1) % n][0] + 2 * out[i][0] + out[(i + 1) % n][0]) / 4.0,
                (out[(i - 1) % n][1] + 2 * out[i][1] + out[(i + 1) % n][1]) / 4.0,
            )
            for i in range(n)
        ]
    return out


def cut_outline(subpaths, close_radius, ppmm=24.0, simplify_tol=0.04):
    """Cut-safe outline for detailed art: close by close_radius mm, re-trace.

    Returns flattened subpaths in the same mm coordinate system as the input.
    """
    pad = close_radius * 2 + 0.5
    mask, w, h, ox, oy = fill_mask(subpaths, ppmm, pad)
    mask = close(mask, w, h, close_radius * ppmm)
    out = []
    for loop in contours(mask, w, h):
        pts = [(ox + x / ppmm, oy + y / ppmm) for x, y in loop]
        pts = smooth(simplify(pts, simplify_tol), rounds=2)
        if len(pts) > 8:
            out.append((pts, True))
    return out


def _resample(pts, step):
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        n = max(1, int(d / step))
        for i in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
    return out


def _inside(loops, x, y):
    """Even-odd point-in-polygon across every closed loop of the outline."""
    c = False
    for pts in loops:
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                c = not c
    return c


def clip_to(engrave, cut, margin=0.12, step=0.2):
    """Trim engraved detail to the inside of the cut outline.

    Closing the silhouette pulls the cut line in slightly, so parts of the
    original art end up outside the piece and would be burned onto the waste.
    Sample each engrave polyline, keep the runs that sit at least `margin` inside
    the outline, and drop the rest. The margin is small on purpose: it is only
    there to skip art that lies on the cut line itself (engraving that is a
    wasted double-burn), while keeping the interior detail -- the arm slits and
    weapon outlines that the closing bridged over, which is what makes each
    class readable once the silhouette is solid.
    """
    loops = [pts for pts, _ in cut]
    if not loops:
        return list(engrave)
    # Dense boundary points, for a cheap distance-to-edge test.
    edge = [p for pts in loops for p in _resample(list(pts) + [pts[0]], step)]
    cell = max(margin, 0.5)
    grid = {}
    for x, y in edge:
        grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y))

    def keep(x, y):
        if not _inside(loops, x, y):
            return False
        gx, gy = int(x // cell), int(y // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for ex, ey in grid.get((gx + dx, gy + dy), ()):
                    if (ex - x) ** 2 + (ey - y) ** 2 < margin * margin:
                        return False
        return True

    out = []
    for pts, closed in engrave:
        seq = list(pts) + [pts[0]] if closed else list(pts)
        if len(seq) < 2:
            continue
        run = []
        for p in _resample(seq, step):
            if keep(*p):
                run.append(p)
            else:
                if len(run) > 1:
                    out.append((simplify(run, 0.02), False))
                run = []
        if len(run) > 1:
            out.append((simplify(run, 0.02), False))
    return out
