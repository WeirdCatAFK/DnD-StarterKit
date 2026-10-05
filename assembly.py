"""Build the assembly diagram, out/06_assembly.svg.

A reference page, never cut. It draws the real generated geometry rather than
sketches, so if a joint changes in generate.py the diagram changes with it.
"""

import math

import strokefont
import svgpath

WOOD = "#c8a06a"
WOOD_DARK = "#a07840"
INK = "#222222"
HINT = "#9aa0a6"
ACCENT = "#c0392b"

# The class-meeple artwork in "Meeples svg/" is not ours. Every page drawn from
# it carries the credit twice -- printed on the sheet and in the file's
# metadata -- so it survives being exported, re-saved or converted to PNG.
ART_TITLE = "RPG Meeples"
ART_AUTHOR = "Xykit"
ART_URL = "https://www.printables.com/model/212336-rpg-meeples"
ART_TERMS = "Personal use only; commercial use through the author's merchant program."
CREDIT_META = f'Figure artwork: "{ART_TITLE}" by {ART_AUTHOR}, {ART_URL}. {ART_TERMS}'
# The stroke font has no colon or parentheses, so the printed line drops the
# URL's scheme.
CREDIT_LINE = (f"FIGURE ART - {ART_TITLE} BY {ART_AUTHOR} - "
               f"{ART_URL.split('//', 1)[1]} - PERSONAL USE").upper()


class Sheet:
    """Plain SVG writer with fills, for a diagram rather than a cut file."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.parts = [f'<rect width="{w}" height="{h}" fill="#fbfaf7"/>']

    def poly(self, subpaths, fill="none", stroke=INK, sw=0.35, opacity=1.0):
        for pts, closed in subpaths:
            d = svgpath.to_path_d([(pts, closed)])
            self.parts.append(
                f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
                f'stroke-linejoin="round" opacity="{opacity}"/>'
            )

    def line(self, x0, y0, x1, y1, stroke=INK, sw=0.35, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<path d="M {x0:.2f},{y0:.2f} L {x1:.2f},{y1:.2f}" fill="none" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>'
        )

    def text(self, s, x, y, size=4.0, stroke=INK, sw=0.4):
        self.poly(strokefont.text(s, x, y, size), stroke=stroke, sw=sw)

    def arrow(self, x0, y0, x1, y1, stroke=ACCENT, sw=0.45):
        self.line(x0, y0, x1, y1, stroke, sw)
        a = math.atan2(y1 - y0, x1 - x0)
        for s in (2.6, -2.6):
            self.line(x1, y1, x1 - 3.2 * math.cos(a - s * 0.16 * 2), y1 - 3.2 * math.sin(a - s * 0.16 * 2), stroke, sw)

    def panel(self, x, y, w, h, title):
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#ffffff" '
            f'stroke="{HINT}" stroke-width="0.3"/>'
        )
        self.text(title, x + 4, y + 9, 4.4, INK, 0.5)

    def credit(self, x, y, size=2.4):
        """The artwork credit, as engraved-style text along the foot of a page."""
        self.text(CREDIT_LINE, x, y, size, HINT, 0.28)

    def write(self, path, title="", desc=""):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                f'xmlns:dc="http://purl.org/dc/elements/1.1/" version="1.1" '
                f'width="{self.w}mm" height="{self.h}mm" viewBox="0 0 {self.w} {self.h}">\n'
                + _metadata(title, desc)
                + "\n".join(self.parts)
                + "\n</svg>\n"
            )


def _esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _metadata(title, desc):
    """Title, description, and a Dublin Core block naming the artwork's author.

    There is no dc:creator on purpose: the diagram is ours, the figures on it
    are not, so the credit sits in dc:contributor, dc:source and dc:rights
    rather than claiming the page has a single author.
    """
    return (
        f"<title>{_esc(title)}</title>\n"
        f"<desc>{_esc(desc)}</desc>\n"
        "<metadata>\n"
        "  <rdf:RDF>\n"
        '    <rdf:Description rdf:about="">\n'
        f"      <dc:title>{_esc(title)}</dc:title>\n"
        f"      <dc:description>{_esc(desc)}</dc:description>\n"
        f"      <dc:contributor>{_esc(ART_AUTHOR)}</dc:contributor>\n"
        f'      <dc:source rdf:resource="{_esc(ART_URL)}"/>\n'
        f"      <dc:rights>{_esc(CREDIT_META)}</dc:rights>\n"
        "    </rdf:Description>\n"
        "  </rdf:RDF>\n"
        "</metadata>\n"
    )


def _board_section(s, x, y, length, G, hole, thickness, holes_at):
    """Cross-section of the board: a bar with holes punched at given offsets."""
    top = y
    pts = [(x, top), (x + length, top), (x + length, top + thickness), (x, top + thickness)]
    s.poly([(pts, True)], fill=WOOD, stroke=WOOD_DARK, sw=0.3)
    for hx in holes_at:
        s.poly([([(x + hx - hole / 2, top), (x + hx + hole / 2, top),
                  (x + hx + hole / 2, top + thickness), (x + hx - hole / 2, top + thickness)], True)],
               fill="#ffffff", stroke=WOOD_DARK, sw=0.25)


def build(path, G):
    """G is the generate module, so the diagram uses the live dimensions."""
    s = Sheet(400, 297)
    s.text("DUNGEON BOARD - ASSEMBLY", 8, 12, 6.0, INK, 0.6)
    s.text(f"{G.GRID:.0f}MM GRID   {G.THICKNESS:.0f}MM PLY   {G.HOLE:.0f}MM VERTEX HOLES", 8, 19, 3.2, HINT, 0.35)

    # ---------------------------------------------------------------- 1 walls
    s.panel(8, 26, 186, 118, "1  WALLS")
    wall = G.wall(2)
    wx, wy = 18, 52
    s.poly(wall.at(wx, wy).cut, fill=WOOD, stroke=WOOD_DARK, sw=0.32)
    s.poly(wall.at(wx, wy).engrave, stroke=WOOD_DARK, sw=0.18, opacity=0.7)
    s.text("BODY RUNS VERTEX TO VERTEX", wx, wy - 4, 2.8, HINT, 0.3)

    by = wy + wall.h + 16
    _board_section(s, wx - 8, by, 92, G.GRID, G.HOLE, G.THICKNESS,
                   [8 + 0, 8 + G.GRID, 8 + 2 * G.GRID])
    s.arrow(wx + 2, wy + wall.h + 2, wx + 2, by - 1.5)
    s.arrow(wx + 2 * G.GRID - 2, wy + wall.h + 2, wx + 2 * G.GRID - 2, by - 1.5)
    s.text("TABS DROP IN AND SIT FLUSH", wx - 8, by + G.THICKNESS + 6, 2.8, HINT, 0.3)

    # two collinear walls sharing one hole, seen from above
    tx, ty = wx - 8, by + 26
    s.text("TWO WALLS SHARE A HOLE", tx, ty - 2, 2.8, HINT, 0.3)
    s.poly([([(tx, ty + 2), (tx + 40, ty + 2), (tx + 40, ty + 5), (tx, ty + 5)], True)],
           fill=WOOD, stroke=WOOD_DARK, sw=0.3)
    s.poly([([(tx + 46, ty + 2), (tx + 86, ty + 2), (tx + 86, ty + 5), (tx + 46, ty + 5)], True)],
           fill=WOOD, stroke=WOOD_DARK, sw=0.3)
    hx = tx + 43
    s.poly([([(hx - 3, ty - 1), (hx + 3, ty - 1), (hx + 3, ty + 8), (hx - 3, ty + 8)], True)],
           stroke=ACCENT, sw=0.35)
    s.poly([([(hx - 2.85, ty + 2), (hx - 0.25, ty + 2), (hx - 0.25, ty + 5), (hx - 2.85, ty + 5)], True)],
           fill=WOOD_DARK, stroke=WOOD_DARK, sw=0.2)
    s.poly([([(hx + 0.25, ty + 2), (hx + 2.85, ty + 2), (hx + 2.85, ty + 5), (hx + 0.25, ty + 5)], True)],
           fill=WOOD_DARK, stroke=WOOD_DARK, sw=0.2)
    s.text("NEAR HALF EACH - NO CLASH", tx, ty + 14, 2.8, HINT, 0.3)

    # -------------------------------------------------------------- 2 corners
    s.panel(206, 26, 186, 118, "2  CORNERS")
    a, b = G.corner_plate(True), G.corner_plate(False)
    ax, ay = 216, 52
    s.poly(a.at(ax, ay).cut, fill=WOOD, stroke=WOOD_DARK, sw=0.32)
    s.text("A  REBATE FROM TOP", ax, ay - 4, 2.8, HINT, 0.3)
    s.poly(b.at(ax, ay + a.h + 12).cut, fill=WOOD, stroke=WOOD_DARK, sw=0.32)
    s.text("B  REBATE FROM BOTTOM", ax, ay + a.h + 8, 2.8, HINT, 0.3)

    # assembled, seen from above
    cx, cy = 300, 74
    arm = 30
    s.text("CROSS AT 90 - NO GAP", cx - 26, cy - 20, 2.8, HINT, 0.3)
    s.poly([([(cx - 1.5, cy - 1.5), (cx + arm, cy - 1.5), (cx + arm, cy + 1.5), (cx - 1.5, cy + 1.5)], True)],
           fill=WOOD, stroke=WOOD_DARK, sw=0.3)
    s.poly([([(cx - 1.5, cy - 1.5), (cx + 1.5, cy - 1.5), (cx + 1.5, cy + arm), (cx - 1.5, cy + arm)], True)],
           fill=WOOD, stroke=WOOD_DARK, sw=0.3)
    s.poly([([(cx - 4, cy - 4), (cx + 4, cy - 4), (cx + 4, cy + 4), (cx - 4, cy + 4)], True)],
           stroke=ACCENT, sw=0.3)
    s.text("CORNER VERTEX STAYS EMPTY", cx - 26, cy + arm + 8, 2.8, HINT, 0.3)
    s.text("TABS GO IN THE TWO FAR ENDS", cx - 26, cy + arm + 13, 2.8, HINT, 0.3)

    # ------------------------------------------------------------- 3 figures
    s.panel(8, 152, 186, 66, "3  FIGURES")
    s.text(f"ART BY {ART_AUTHOR.upper()}", 62, 161, 2.8, HINT, 0.3)
    fig, base = G.figure_and_base("Fighter", "meeple")
    fx, fy = 22, 172
    s.poly(fig.at(fx, fy).cut, fill=WOOD, stroke=WOOD_DARK, sw=0.32)
    s.poly(fig.at(fx, fy).engrave, stroke=WOOD_DARK, sw=0.2, opacity=0.8)
    s.poly(base.at(fx + fig.w + 14, fy + 4).cut, fill=WOOD, stroke=WOOD_DARK, sw=0.32)
    s.arrow(fx + fig.w + 3, fy + fig.h - 4, fx + fig.w + 11, fy + fig.h - 4)
    s.text("PRESS IN UNTIL FLUSH UNDERNEATH", fx - 8, fy + fig.h + 12, 2.8, HINT, 0.3)
    s.text(f"BASE {base.w:.0f}MM DIA", fx - 8, fy + fig.h + 17, 2.8, HINT, 0.3)

    # ---------------------------------------------------------------- 4 seams
    s.panel(206, 152, 186, 66, "4  SEAMS")
    sx, sy = 224, 172
    for i in (0, 1):
        s.poly([([(sx + i * 62, sy), (sx + i * 62 + 58, sy), (sx + i * 62 + 58, sy + 30), (sx + i * 62, sy + 30)], True)],
               fill=WOOD, stroke=WOOD_DARK, sw=0.32)
    mid = sx + 60
    for k in (8, 20):
        s.poly([([(mid - 3, sy + k), (mid + 3, sy + k), (mid + 3, sy + k + 6), (mid - 3, sy + k + 6)], True)],
               fill="#ffffff", stroke=ACCENT, sw=0.35)
    s.poly([([(mid - 2.7, sy + 8.3), (mid + 2.7, sy + 8.3), (mid + 2.7, sy + 13.7), (mid - 2.7, sy + 13.7)], True)],
           fill=WOOD_DARK, stroke=WOOD_DARK, sw=0.25)
    s.text("BUTT THE TILES - HALF HOLES", sx, sy - 4, 2.8, HINT, 0.3)
    s.text("MAKE WHOLE ONES", sx, sy + 34, 2.8, HINT, 0.3)
    s.text("DROP A KEY IN TO LOCK", sx, sy + 39, 2.8, HINT, 0.3)

    # --------------------------------------------------------------- 5 layout
    tot = 2 * G.SQUARES
    s.panel(8, 226, 384, 64, f"5  EXAMPLE LAYOUT   {tot} x {tot} SQUARES")
    g = 50.0 / tot
    ox, oy = 20, 238
    for i in range(tot + 1):
        s.line(ox + i * g, oy, ox + i * g, oy + tot * g, "#e2e2e2", 0.12)
        s.line(ox, oy + i * g, ox + tot * g, oy + i * g, "#e2e2e2", 0.12)
    s.line(ox + G.SQUARES * g, oy, ox + G.SQUARES * g, oy + tot * g, HINT, 0.3, dash="1.5 1.5")
    s.line(ox, oy + G.SQUARES * g, ox + tot * g, oy + G.SQUARES * g, HINT, 0.3, dash="1.5 1.5")
    if G.SQUARES == 5:
        rooms = [(1, 1, 3, 3), (5, 1, 4, 3), (1, 5, 3, 4), (5, 5, 4, 4)]
        doors = [(4, 2), (2, 5), (5, 7), (7, 5)]
    elif G.SQUARES == 8:
        rooms = [(1, 1, 6, 5), (8, 1, 7, 4), (1, 7, 5, 8), (8, 6, 7, 9)]
        doors = [(6, 2), (3, 7), (8, 9), (11, 6)]
    else:
        rooms = [(1, 1, 7, 6), (10, 1, 9, 5), (2, 9, 6, 9), (10, 8, 8, 10)]
        doors = [(8, 3), (5, 9), (10, 12), (14, 8)]
    for rx, ry, rw, rh in rooms:
        s.poly([([(ox + rx * g, oy + ry * g), (ox + (rx + rw) * g, oy + ry * g),
                  (ox + (rx + rw) * g, oy + (ry + rh) * g), (ox + rx * g, oy + (ry + rh) * g)], True)],
               fill="none", stroke=INK, sw=0.7)
    for dx, dy in doors:
        s.line(ox + dx * g - 0.9, oy + dy * g, ox + dx * g + 0.9, oy + dy * g, ACCENT, 1.4)
    s.text("HEAVY LINE = WALL RUN     RED = DOOR     DASHED = TILE SEAM", ox + tot * g + 8, oy + 10, 3.0, HINT, 0.32)
    s.text("WALLS COME IN 1 2 3 AND 5 SQUARE LENGTHS", ox + tot * g + 8, oy + 17, 3.0, HINT, 0.32)
    s.text("USE ONE LONG PIECE PER RUN - SEAMS ONLY", ox + tot * g + 8, oy + 24, 3.0, HINT, 0.32)
    s.text("AT CORNERS AND DOORWAYS", ox + tot * g + 8, oy + 31, 3.0, HINT, 0.32)
    s.text("ONE WALL DIRECTION PER VERTEX - USE AN", ox + tot * g + 8, oy + 41, 3.0, HINT, 0.32)
    s.text("L PIECE WHERE TWO RUNS MEET", ox + tot * g + 8, oy + 48, 3.0, HINT, 0.32)

    s.credit(8, 294.5)

    s.write(path, "Dungeon Board - Assembly",
            "Assembly diagram for the modular D&D dungeon board. " + CREDIT_META)
    return s
