"""Build the piece list, out/07_piece_list.svg.

A reference page, never cut. One column per sheet, every part drawn from the
same geometry that goes into the cut files -- so the list cannot drift out of
step with what the laser actually produces. Change a wall length or drop a
monster and this page changes with it.

Use it to sort the pile after a cut: each row is a thumbnail at true relative
size, the part's name, how many of it that sheet holds, and its finished
dimensions.
"""

import strokefont
import svgpath
from assembly import ACCENT, CREDIT_META, HINT, INK, WOOD, WOOD_DARK, Sheet

PAGE_W, PAGE_H = 560.0, 400.0
MARGIN = 12.0
COL_GAP = 8.0
HEAD_H = 30.0
FOOT_H = 22.0

COL_H = PAGE_H - HEAD_H - FOOT_H - 20    # height of one sheet column
THUMB_W, THUMB_H = 32.0, 17.0
ROW_PAD = 3.5
SECTION_H = 9.0
ROW_MIN = 8.5

# name -> (section, display name). Anything not listed is a figure or prop.
_TERRAIN = {
    "cornerA": "CORNER PLATE A",
    "cornerB": "CORNER PLATE B",
    "door": "DOOR",
    "key": "SEAM KEY",
}


def _key(p):
    """What makes two parts the same row.

    Bases are turned to fit their figure, so their diameters differ by fractions
    of a millimetre. Group them by the whole millimetre you would read off a
    ruler, or the column fills with near-duplicates.
    """
    return (p.name, round(p.w), round(p.h)) if p.name == "base" else            (p.name, round(p.w, 1), round(p.h, 1))


def _mm(v):
    """One decimal, but only when it says something. 31.5 must not read as 32."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _title(piece, G):
    if piece.name.startswith("wall"):
        n = int(piece.name[4:])
        return f"WALL {n} SQUARE" + ("" if n == 1 else "S")
    if piece.name in _TERRAIN:
        return _TERRAIN[piece.name]
    if piece.name == "base":
        return f"BASE {piece.w:.0f}MM"
    return piece.name.upper()


def _section(piece):
    if piece.name.startswith("wall") or piece.name in _TERRAIN:
        return 0            # terrain
    if piece.name == "base":
        return 2            # bases
    return 1                # figures and props


def _note(piece, G, pairs):
    """The dimension that matters for this kind of part.

    A base's own diameter is the least useful thing about it -- what you need
    when sorting a pile is which figure it belongs to, so say that instead.
    """
    if piece.name.startswith("wall") or piece.name in ("cornerA", "cornerB", "door"):
        return f"{_mm(piece.w)} LONG x {_mm(piece.h - G.THICKNESS)} TALL PLUS TAB"
    if piece.name == "key":
        return f"{_mm(piece.w)}MM SQUARE - DROPS IN A SEAM HOLE"
    if piece.name == "base":
        who = _tally(pairs.get(_key(piece), []))
        return f"SLOTTED - FOR {who}" if who else f"{_mm(piece.w)}MM DISC - SLOTTED"
    return f"{_mm(piece.w)} x {_mm(piece.h)} MM"


def _tally(names):
    """"GOBLIN GOBLIN ORC" -> "GOBLIN X2 ORC", first-seen order."""
    seen = []
    count = {}
    for n in names:
        if n not in count:
            seen.append(n)
        count[n] = count.get(n, 0) + 1
    return " ".join(n if count[n] == 1 else f"{n} X{count[n]}" for n in seen)


def _bases_to_figures(pieces):
    """Which figure each base was cut for.

    figure_set emits a figure immediately followed by the base sized for it, so
    adjacency is the pairing. Guarded so a stray base is simply left unpaired
    rather than credited to whatever happened to precede it.
    """
    pairs = {}
    prev = None
    for p in pieces:
        if p.name == "base" and prev is not None and _section(prev) == 1:
            pairs.setdefault(_key(p), []).append(prev.name.upper())
        prev = p
    return pairs


def _group(pieces, G):
    """Collapse a sheet's pieces into rows, terrain first, biggest first."""
    rows = {}
    order = []
    for p in pieces:
        key = _key(p)
        if key not in rows:
            rows[key] = [p, 0]
            order.append(key)
        rows[key][1] += 1
    out = [(rows[k][0], rows[k][1]) for k in order]
    out.sort(key=lambda pc: (_section(pc[0]), -pc[0].w * pc[0].h))
    return out


def inventory(pieces, G):
    """One sheet's rows: (piece, count, title, note), plus the total part count.

    The page and the checks both read the list from here, so what gets printed
    and what gets verified cannot disagree.
    """
    rows = _group(pieces, G)
    pairs = _bases_to_figures(pieces)
    out = [(p, c, _title(p, G), _note(p, G, pairs)) for p, c in rows]
    return out, 1 + sum(c for _, c in rows)   # +1 for the board tile


def _thumb(s, piece, x, y, w, h):
    """Draw a part scaled into a box, never enlarged, bottom-left in the box."""
    k = min(w / piece.w, h / piece.h, 1.0)
    p = piece.scaled(k)
    p = p.at(x + (w - p.w) / 2, y + (h - p.h) / 2)
    s.poly(p.cut, fill=WOOD, stroke=WOOD_DARK, sw=0.22)
    if p.engrave:
        s.poly(p.engrave, stroke=WOOD_DARK, sw=0.13, opacity=0.75)
    return k


def _tile_thumb(s, G, x, y, w, h):
    """The board tile: outline and grid only. The 81 holes would just be mud."""
    k = min(w / G.TILE, h / G.TILE)
    side = G.TILE * k
    ox, oy = x + (w - side) / 2, y + (h - side) / 2
    box = svgpath.transform(G.tile_outline(), k, k, ox, oy)
    s.poly(box, fill=WOOD, stroke=WOOD_DARK, sw=0.22)
    s.poly(svgpath.transform(G.tile_grid_lines(), k, k, ox, oy), stroke=WOOD_DARK, sw=0.1, opacity=0.6)


def _row(s, x, y, w, h, count, title, note, thumb):
    """One list row: thumbnail, name over dimensions, count right-aligned."""
    thumb(s, x, y, THUMB_W, h)
    tx = x + THUMB_W + 4.0
    c = f"x{count}"
    room = x + w - _w(c, 4.2) - 2.0 - tx
    s.text(_fit(title, 3.4, room), tx, y + h / 2 - 0.4, 3.4, INK, 0.36)
    s.text(_fit(note, 2.4, room), tx, y + h / 2 + 4.2, 2.4, HINT, 0.25)
    s.text(c, x + w - _w(c, 4.2), y + h / 2 + 1.4, 4.2, ACCENT, 0.5)
    s.line(x, y + h + ROW_PAD / 2, x + w, y + h + ROW_PAD / 2, "#ececec", 0.2)
    return h + ROW_PAD


def _w(txt, size):
    return strokefont.width(txt, size)


def _fit(txt, size, avail):
    """Trim a note to the width the row actually has. The font is fixed pitch,
    so this is arithmetic rather than measurement."""
    per = _w("M", size)
    n = int(avail / per)
    return txt if len(txt) <= n else txt[:max(0, n - 2)].rstrip() + ".."


def column_layout(rows, avail=COL_H - 13):
    """Row height, and the height the column will actually use.

    Shrinks the rows -- and with them the thumbnails -- until the column fits.
    Sheet C carries half again as many parts as sheet A, so a fixed row height
    would either overflow that column or waste most of the others. Exposed so
    sanity_check can prove a column still fits after pieces are added.
    """
    n = 1 + len(rows)                                     # +1 for the board tile
    secs = len({_section(r[0]) for r in rows}) + 1         # +1 for the BOARD heading
    free = avail - secs * SECTION_H
    rh = max(ROW_MIN, min(THUMB_H, free / max(1, n) - ROW_PAD))
    return rh, secs * SECTION_H + n * (rh + ROW_PAD) + 3


def _column(s, G, which, x, y, w, h, pieces):
    s.parts.append(
        f'<rect x="{x - 4}" y="{y - 12}" width="{w + 8}" height="{h + 14}" rx="2" '
        f'fill="#ffffff" stroke="{HINT}" stroke-width="0.3"/>'
    )
    s.text(f"SHEET {which}", x, y - 4, 5.0, INK, 0.6)
    fname = f"0{'ABCD'.index(which) + 1} SHEET {which}.SVG"
    s.text(fname, x + w - _w(fname, 2.6), y - 4.5, 2.6, HINT, 0.28)

    rows, total = inventory(pieces, G)
    rh, _used = column_layout(rows, h - 13)

    cy = y + 3
    s.text("BOARD", x, cy + 6.0, 3.0, ACCENT, 0.34)
    cy += SECTION_H
    cy += _row(s, x, cy, w, rh, 1, "BOARD TILE",
               f"{_mm(G.TILE)} x {_mm(G.TILE)} MM - {G.SQUARES} x {G.SQUARES} SQUARES",
               lambda s, bx, by, bw, bh: _tile_thumb(s, G, bx, by, bw, bh))

    last = None
    for piece, count, title, note in rows:
        sec = _section(piece)
        if sec != last:
            s.text(["TERRAIN", "FIGURES AND PROPS", "BASES"][sec], x, cy + 6.0, 3.0, ACCENT, 0.34)
            cy += SECTION_H
            last = sec
        cy += _row(s, x, cy, w, rh, count, title, note,
                   lambda s, bx, by, bw, bh, p=piece: _thumb(s, p, bx, by, bw, bh))

    s.line(x, y + h - 7, x + w, y + h - 7, HINT, 0.25)
    s.text(f"{total} PIECES ON THIS SHEET", x, y + h - 1.5, 3.2, INK, 0.4)
    return total


def build(path, G, sheets):
    """G is the generate module; sheets maps 'A'..'D' to that sheet's piece list."""
    s = Sheet(PAGE_W, PAGE_H)
    s.text("DUNGEON BOARD - PIECE LIST", MARGIN, 14, 6.0, INK, 0.6)
    s.text(f"{G.GRID:.0f}MM GRID   {G.THICKNESS:g}MM PLY   KERF {G.KERF:g}MM   "
           f"HOLES {G.HOLE:.0f}MM   THUMBNAILS AT TRUE RELATIVE SIZE",
           MARGIN, 21, 3.0, HINT, 0.32)
    note = "REFERENCE ONLY - NEVER CUT THIS PAGE"
    s.text(note, PAGE_W - MARGIN - _w(note, 3.4), 14, 3.4, ACCENT, 0.4)

    col_w = (PAGE_W - 2 * MARGIN - 3 * COL_GAP) / 4 - 8
    col_h = COL_H
    total = 0
    for i, which in enumerate("ABCD"):
        x = MARGIN + 4 + i * (col_w + 8 + COL_GAP)
        total += _column(s, G, which, x, HEAD_H + 6, col_w, col_h, sheets[which])

    # ------------------------------------------------------------ kit totals
    fy = PAGE_H - FOOT_H + 6
    counts = {}
    wall_mm = 0.0
    for which in "ABCD":
        for p in sheets[which]:
            counts[p.name] = counts.get(p.name, 0) + 1
            if p.name.startswith("wall"):
                wall_mm += int(p.name[4:]) * G.GRID
    walls = sum(v for k, v in counts.items() if k.startswith("wall"))
    corners = counts.get("cornerA", 0) + counts.get("cornerB", 0)
    figures = sum(v for k, v in counts.items()
                  if not k.startswith("wall") and k not in _TERRAIN and k != "base")
    bits = [
        f"4 BOARD TILES - {2 * G.TILE:.0f} x {2 * G.TILE:.0f} MM TABLE",
        f"{walls} WALLS - {wall_mm / 10:.0f} CM OF WALL",
        f"{corners // 2} L CORNERS - {corners} PLATES",
        f"{counts.get('door', 0)} DOORS",
        f"{figures} FIGURES AND PROPS",
        f"{counts.get('base', 0)} BASES",
        f"{counts.get('key', 0)} SEAM KEYS",
    ]
    s.text("WHOLE KIT", MARGIN, fy, 4.0, INK, 0.5)
    x = MARGIN + _w("WHOLE KIT ", 4.0) + 4
    for b in bits:
        s.text(b, x, fy, 3.0, HINT, 0.32)
        x += _w(b, 3.0) + 7
    s.text(f"{total} PIECES IN TOTAL", MARGIN, fy + 7, 3.2, ACCENT, 0.4)
    # The figure rows are drawn from artwork that is not ours -- credit it here
    # too, so a printed piece list carries it as well as the assembly page.
    s.credit(MARGIN, PAGE_H - 3)

    s.write(path, "Dungeon Board - Piece List",
            "Every part of the kit, per sheet, at true relative size. " + CREDIT_META)
    return s
