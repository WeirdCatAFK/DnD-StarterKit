"""Find the narrowest feature in a flattened outline.

Plywood snaps at thin necks and slits. This measures the smallest distance
between two parts of the outline that are far apart *along* the path -- which is
exactly a neck (two outline walls close together) rather than just adjacent
points on a curve.
"""

import math
import svgpath


def resample(pts, step):
    """Even-ish point spacing so the scan does not depend on curve density."""
    out = [pts[0]]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        if d == 0:
            continue
        acc += d
        if acc >= step:
            out.append(b)
            acc = 0.0
    return out


def min_neck(subpaths, step=0.25, along=2.0, max_gap=None):
    """Narrowest neck in mm, and where it is.

    `along` is how far apart two points must be along the outline before their
    separation counts as a neck rather than local curvature. `max_gap` sets how
    wide a neck is still worth detecting; anything wider is reported as infinite,
    which for our purposes means "nothing thin here".
    """
    best = (float("inf"), None)
    for pts, closed in subpaths:
        p = resample(pts, step)
        n = len(p)
        if n < 8:
            continue
        skip = max(3, int(along / step))
        cell = max(max_gap or along, 1.0)
        grid = {}
        for i, (x, y) in enumerate(p):
            grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
        for i, (x, y) in enumerate(p):
            gx, gy = int(x // cell), int(y // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((gx + dx, gy + dy), ()):
                        if j <= i:
                            continue
                        # circular distance along the closed outline
                        sep = min(j - i, n - (j - i)) if closed else j - i
                        if sep < skip:
                            continue
                        d = math.dist(p[i], p[j])
                        if d < best[0]:
                            best = (d, ((x + p[j][0]) / 2, (y + p[j][1]) / 2))
    return best
