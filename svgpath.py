"""Minimal SVG path parsing and flattening. Standard library only.

Enough of the SVG path grammar to read Inkscape output, arcs included.
Curves are flattened to polylines so we can take exact bounding boxes, scale
artwork to a target height in mm, and emit predictable geometry for the laser.
"""

import math
import re

# A number, an optional-comma/whitespace separator, or a single command letter.
_TOKEN = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

_ARGCOUNT = {
    "M": 2, "L": 2, "T": 2,
    "H": 1, "V": 1,
    "C": 6, "S": 4, "Q": 4,
    "A": 7,
    "Z": 0,
}


def tokenize(d):
    """Split path data into command letters and floats."""
    out = []
    for tok in _TOKEN.findall(d):
        out.append(tok if tok.isalpha() else float(tok))
    return out


def _bezier3(p0, p1, p2, p3, steps):
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        yield (
            u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        )


def _bezier2(p0, p1, p2, steps):
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        yield (
            u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
        )


def _arc(p0, rx, ry, phi_deg, large_arc, sweep, p1, tol):
    """Endpoint-parameterised elliptical arc, flattened to points.

    Follows the implementation notes in SVG 1.1 appendix F.6.
    """
    if p0 == p1:
        return
    if rx == 0 or ry == 0:
        yield p1
        return
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg % 360.0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2

    # Scale the radii up if they are too small to span the endpoints (F.6.6).
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s

    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(num / den, 0.0)) * (-1 if large_arc == sweep else 1)
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2.0

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / norm))) if norm else 0.0
        return -a if ux * vy - uy * vx < 0 else a

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    steps = max(4, min(180, int(abs(dtheta) / (2 * math.acos(max(-1.0, min(1.0, 1 - tol / max(rx, ry))))) ) + 1))         if max(rx, ry) > tol else 4
    for i in range(1, steps + 1):
        t = theta1 + dtheta * i / steps
        yield (
            cos_p * rx * math.cos(t) - sin_p * ry * math.sin(t) + cx,
            sin_p * rx * math.cos(t) + cos_p * ry * math.sin(t) + cy,
        )


def _curve_steps(p0, p1, p2, p3, tol):
    """Step count from the control polygon length -- generous, cheap, stable."""
    length = (
        math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
        if p3 is not None
        else math.dist(p0, p1) + math.dist(p1, p2)
    )
    return max(4, min(160, int(math.sqrt(length / max(tol, 1e-6)) * 2) + 1))


def flatten(d, tol=0.05):
    """Flatten path data to a list of subpaths.

    Returns [(points, closed), ...] where points is a list of (x, y) in the
    path's own user units. `tol` is the flattening tolerance in those units.
    """
    toks = tokenize(d)
    subpaths = []
    pts = []
    closed = False
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_cubic_ctrl = None
    prev_quad_ctrl = None
    cmd = None
    i = 0

    def flush():
        nonlocal pts, closed
        if len(pts) > 1:
            subpaths.append((pts, closed))
        pts = []
        closed = False

    while i < len(toks):
        if isinstance(toks[i], str):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if pts:
                    closed = True
                    flush()
                cur = start
                prev_cubic_ctrl = prev_quad_ctrl = None
                continue
        elif cmd is None:
            raise ValueError("path data starts with a number")
        elif cmd in "Mm":
            # Repeated coordinates after a moveto are implicit linetos.
            cmd = "L" if cmd == "M" else "l"

        up = cmd.upper()
        rel = cmd.islower()
        n = _ARGCOUNT[up]
        args = toks[i : i + n]
        if len(args) < n or any(isinstance(a, str) for a in args):
            raise ValueError(f"truncated arguments for command {cmd!r}")
        i += n

        if up == "M":
            flush()
            cur = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
            start = cur
            pts = [cur]
            prev_cubic_ctrl = prev_quad_ctrl = None
            continue

        if up == "L":
            cur = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
            pts.append(cur)
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif up == "H":
            cur = (cur[0] + args[0], cur[1]) if rel else (args[0], cur[1])
            pts.append(cur)
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif up == "V":
            cur = (cur[0], cur[1] + args[0]) if rel else (cur[0], args[0])
            pts.append(cur)
            prev_cubic_ctrl = prev_quad_ctrl = None
        elif up in ("C", "S"):
            if up == "C":
                c1 = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
                c2 = (cur[0] + args[2], cur[1] + args[3]) if rel else (args[2], args[3])
                end = (cur[0] + args[4], cur[1] + args[5]) if rel else (args[4], args[5])
            else:
                c1 = (
                    (2 * cur[0] - prev_cubic_ctrl[0], 2 * cur[1] - prev_cubic_ctrl[1])
                    if prev_cubic_ctrl
                    else cur
                )
                c2 = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
                end = (cur[0] + args[2], cur[1] + args[3]) if rel else (args[2], args[3])
            pts.extend(_bezier3(cur, c1, c2, end, _curve_steps(cur, c1, c2, end, tol)))
            prev_cubic_ctrl = c2
            prev_quad_ctrl = None
            cur = end
        elif up in ("Q", "T"):
            if up == "Q":
                c1 = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
                end = (cur[0] + args[2], cur[1] + args[3]) if rel else (args[2], args[3])
            else:
                c1 = (
                    (2 * cur[0] - prev_quad_ctrl[0], 2 * cur[1] - prev_quad_ctrl[1])
                    if prev_quad_ctrl
                    else cur
                )
                end = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
            pts.extend(_bezier2(cur, c1, end, _curve_steps(cur, c1, end, None, tol)))
            prev_quad_ctrl = c1
            prev_cubic_ctrl = None
            cur = end
        elif up == "A":
            end = (cur[0] + args[5], cur[1] + args[6]) if rel else (args[5], args[6])
            pts.extend(
                _arc(cur, args[0], args[1], args[2], bool(args[3]), bool(args[4]), end, tol)
            )
            prev_cubic_ctrl = prev_quad_ctrl = None
            cur = end

    flush()
    return subpaths


def bbox(subpaths):
    xs = [p[0] for pts, _ in subpaths for p in pts]
    ys = [p[1] for pts, _ in subpaths for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def transform(subpaths, sx, sy, tx, ty):
    return [
        ([(x * sx + tx, y * sy + ty) for x, y in pts], closed) for pts, closed in subpaths
    ]


def to_path_d(subpaths, precision=3):
    """Emit flattened subpaths as SVG path data."""
    parts = []
    for pts, closed in subpaths:
        head = f"M {pts[0][0]:.{precision}f},{pts[0][1]:.{precision}f}"
        body = " ".join(f"{x:.{precision}f},{y:.{precision}f}" for x, y in pts[1:])
        parts.append(f"{head} L {body}" + (" Z" if closed else ""))
    return " ".join(parts)
