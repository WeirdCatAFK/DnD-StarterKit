"""Load artwork SVGs and normalise them to millimetres.

Written to cope with whatever a downloaded SVG throws at it: nested groups,
matrix/scale/rotate transforms, and shapes that are not paths. Anything drawn in
green (#00ff00) is treated as engraved detail, matching the convention already
used by the class meeples in `Meeples svg/`; everything else is outline to cut.

Public surface:
    names(directory)          -> sorted artwork names in a folder
    load(name, directory)     -> (cut, engrave, (w, h)) in mm, origin at (0, 0)
    fitted(name, w, h, dir)   -> the same, scaled to fit a box
    bottom_width(subpaths, d) -> x-range of the lowest d mm, for sizing base slots
"""

import math
import os
import re
import xml.etree.ElementTree as ET

import svgpath

SVG_NS = "{http://www.w3.org/2000/svg}"
ENGRAVE_COLOURS = {"#00ff00", "#0f0", "lime", "#00FF00"}

_UNITS = {
    "mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6,
    "": 25.4 / 96, "px": 25.4 / 96, "q": 0.25,
}


def _length_mm(value, default=None):
    if value is None:
        return default
    m = re.match(r"^\s*([-+0-9.eE]+)\s*([a-z%]*)\s*$", value.strip())
    if not m:
        return default
    n, unit = float(m.group(1)), m.group(2).lower()
    if unit == "%":
        return default
    if unit not in _UNITS:
        return default
    return n * _UNITS[unit]


# ------------------------------- transforms --------------------------------

_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)   # a b c d e f


def _mul(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(value):
    if not value:
        return _IDENTITY
    m = _IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", value):
        v = [float(x) for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", args)]
        if name == "translate":
            m = _mul(m, (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0))
        elif name == "scale":
            sx = v[0]
            sy = v[1] if len(v) > 1 else sx
            m = _mul(m, (sx, 0, 0, sy, 0, 0))
        elif name == "matrix":
            m = _mul(m, tuple(v[:6]))
        elif name == "rotate":
            a = math.radians(v[0])
            r = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) >= 3:
                m = _mul(m, _mul(_mul((1, 0, 0, 1, v[1], v[2]), r), (1, 0, 0, 1, -v[1], -v[2])))
            else:
                m = _mul(m, r)
        elif name in ("skewX", "skewY"):
            t = math.tan(math.radians(v[0]))
            m = _mul(m, (1, t, 0, 1, 0, 0) if name == "skewY" else (1, 0, t, 1, 0, 0))
    return m


def _apply(m, subpaths):
    a, b, c, d, e, f = m
    return [([(a * x + c * y + e, b * x + d * y + f) for x, y in pts], cl) for pts, cl in subpaths]


# --------------------------------- shapes ----------------------------------


def _num(el, attr, default=0.0):
    try:
        return float(el.get(attr, default))
    except (TypeError, ValueError):
        return default


def _points(el):
    v = [float(x) for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", el.get("points", ""))]
    return list(zip(v[0::2], v[1::2]))


def _ellipse(cx, cy, rx, ry, steps=64):
    return [(cx + rx * math.cos(2 * math.pi * i / steps), cy + ry * math.sin(2 * math.pi * i / steps))
            for i in range(steps)]


def _element_geometry(el, tol):
    """Flattened subpaths for one drawable element, in its local units."""
    tag = el.tag.replace(SVG_NS, "")
    if tag == "path":
        d = el.get("d")
        return svgpath.flatten(d, tol=tol) if d else []
    if tag == "rect":
        x, y = _num(el, "x"), _num(el, "y")
        w, h = _num(el, "width"), _num(el, "height")
        rx = _num(el, "rx", _num(el, "ry"))
        if not w or not h:
            return []
        if rx > 0:
            rx = min(rx, w / 2, h / 2)
            pts = []
            for cx, cy, a0 in ((x + w - rx, y + h - rx, 0.0), (x + rx, y + h - rx, math.pi / 2),
                               (x + rx, y + rx, math.pi), (x + w - rx, y + rx, 1.5 * math.pi)):
                pts += [(cx + rx * math.cos(a0 + math.pi / 2 * i / 8), cy + rx * math.sin(a0 + math.pi / 2 * i / 8))
                        for i in range(9)]
            return [(pts, True)]
        return [([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
    if tag == "circle":
        r = _num(el, "r")
        return [(_ellipse(_num(el, "cx"), _num(el, "cy"), r, r), True)] if r else []
    if tag == "ellipse":
        rx, ry = _num(el, "rx"), _num(el, "ry")
        return [(_ellipse(_num(el, "cx"), _num(el, "cy"), rx, ry), True)] if rx and ry else []
    if tag in ("polygon", "polyline"):
        pts = _points(el)
        return [(pts, tag == "polygon")] if len(pts) > 1 else []
    if tag == "line":
        return [([(_num(el, "x1"), _num(el, "y1")), (_num(el, "x2"), _num(el, "y2"))], False)]
    return []


def _stroke_of(el, inherited):
    style = el.get("style", "") or ""
    m = re.search(r"(?:^|;)\s*stroke\s*:\s*([^;]+)", style)
    stroke = m.group(1).strip().lower() if m else (el.get("stroke") or inherited)
    return stroke


def _is_engrave(stroke):
    return stroke is not None and stroke.strip().lower() in {c.lower() for c in ENGRAVE_COLOURS}


# ---------------------------------- API ------------------------------------


def names(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(f[:-4] for f in os.listdir(directory) if f.lower().endswith(".svg"))


def _read(path, tol_units):
    root = ET.parse(path).getroot()

    vb = root.get("viewBox")
    if vb:
        vb = [float(v) for v in re.split(r"[\s,]+", vb.strip())]
    else:
        vb = None

    cut, eng = [], []

    def walk(el, matrix, stroke):
        matrix = _mul(matrix, _parse_transform(el.get("transform")))
        stroke = _stroke_of(el, stroke)
        tag = el.tag.replace(SVG_NS, "")
        if tag in ("g", "svg", "a", "switch"):
            for child in el:
                walk(child, matrix, stroke)
            return
        if tag in ("defs", "metadata", "title", "desc", "namedview"):
            return
        geo = _element_geometry(el, tol_units)
        if geo:
            (eng if _is_engrave(stroke) else cut).extend(_apply(matrix, geo))

    walk(root, _IDENTITY, None)
    if not cut and eng:      # all-green artwork: treat it as the outline
        cut, eng = eng, []
    if not cut:
        raise ValueError(f"{os.path.basename(path)}: no drawable geometry found")

    # user units -> mm
    if vb and vb[2] and vb[3]:
        w_mm = _length_mm(root.get("width"), vb[2] * _UNITS[""])
        h_mm = _length_mm(root.get("height"), vb[3] * _UNITS[""])
        sx, sy = w_mm / vb[2], h_mm / vb[3]
        if abs(sx - sy) > 1e-6:
            sx = sy = min(sx, sy)     # never skew the artwork
        ox, oy = -vb[0] * sx, -vb[1] * sy
    else:
        sx = sy = _UNITS[""]
        ox = oy = 0.0

    cut = svgpath.transform(cut, sx, sy, ox, oy)
    eng = svgpath.transform(eng, sx, sy, ox, oy)
    return cut, eng


def load(name, directory):
    """Artwork as (cut, engrave, (w, h)) in mm, top-left of the cut at (0, 0)."""
    cut, eng = _read(os.path.join(directory, f"{name}.svg"), tol_units=0.5)
    x0, y0, x1, y1 = svgpath.bbox(cut)
    return (
        svgpath.transform(cut, 1, 1, -x0, -y0),
        svgpath.transform(eng, 1, 1, -x0, -y0),
        (x1 - x0, y1 - y0),
    )


def fitted(name, box_w, box_h, directory):
    """Scaled to the largest size fitting inside box_w x box_h mm.

    These silhouettes carry weapons and cloaks, so several are wider than they
    are tall; scaling on height alone would overhang the grid square.
    """
    cut, eng, (w, h) = load(name, directory)
    k = min(box_w / w, box_h / h)
    return (
        svgpath.transform(cut, k, k, 0.0, 0.0),
        svgpath.transform(eng, k, k, 0.0, 0.0),
        (w * k, h * k),
    )


def bottom_width(subpaths, depth):
    """Widest the artwork gets over its lowest `depth` mm -- the base slot size."""
    _, _, _, ymax = svgpath.bbox(subpaths)
    xs = [p[0] for pts, _ in subpaths for p in pts if p[1] >= ymax - depth]
    return (min(xs), max(xs)) if xs else (0.0, 0.0)
