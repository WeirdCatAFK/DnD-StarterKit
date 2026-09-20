"""Render the two reference pages to PNG.

The assembly diagram and the piece list are meant to be looked at, not cut, and
an SVG is awkward to look at: it will not go in a phone's photo roll, print
predictably, or paste into a message. So both are also written as PNGs.

Nothing here is required to produce the cut files. If no renderer is installed
the SVGs are still written and this reports what it looked for.
"""

import os
import shutil
import subprocess

DPI = 300              # 300 dpi: prints cleanly on paper, zooms in on a phone

# Inkscape is the one that ships on most machines that own a laser cutter.
# rsvg-convert and ImageMagick are accepted as stand-ins.
_INKSCAPE = [
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
    r"C:\Program Files\Inkscape\inkscape.exe",
    "/usr/bin/inkscape",
    "/usr/local/bin/inkscape",
    "/Applications/Inkscape.app/Contents/MacOS/inkscape",
]


def find_renderer():
    """(kind, path) for the first renderer available, or (None, None)."""
    exe = shutil.which("inkscape")
    if exe:
        return "inkscape", exe
    for path in _INKSCAPE:
        if os.path.exists(path):
            return "inkscape", path
    for name, kind in (("rsvg-convert", "rsvg"), ("magick", "magick"), ("convert", "magick")):
        exe = shutil.which(name)
        if exe:
            return kind, exe
    return None, None


def _command(kind, exe, svg, png, dpi):
    if kind == "inkscape":
        return [exe, "--export-type=png", f"--export-dpi={dpi}",
                f"--export-filename={png}", svg]
    if kind == "rsvg":
        return [exe, "-d", str(dpi), "-p", str(dpi), "-o", png, svg]
    return [exe, "-density", str(dpi), "-background", "white", "-flatten", svg, png]


def png(svg, dpi=DPI, renderer=None):
    """Render one SVG beside itself as .png. Returns the path, or None."""
    kind, exe = renderer or find_renderer()
    if not exe:
        return None
    out = os.path.splitext(svg)[0] + ".png"
    try:
        r = subprocess.run(_command(kind, exe, svg, out, dpi),
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out if r.returncode == 0 and os.path.exists(out) else None


def render(svgs, dpi=DPI, quiet=False):
    """Render each SVG to PNG. Reports rather than raises: a missing renderer
    must not fail a run whose real job is the cut files."""
    kind, exe = find_renderer()
    if not exe:
        if not quiet:
            print("  no PNG renderer found (looked for inkscape, rsvg-convert, magick)")
            print("  the SVGs are written either way - install Inkscape for the PNGs")
        return []
    done = []
    for svg in svgs:
        out = png(svg, dpi, (kind, exe))
        if out:
            done.append(out)
            if not quiet:
                mp = os.path.getsize(out) / 1e6
                print(f"  {os.path.basename(out)}  {dpi} dpi, {mp:.1f} MB")
        elif not quiet:
            print(f"  FAILED to render {os.path.basename(svg)}")
    return done
