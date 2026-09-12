#!/usr/bin/env python3
"""Calibrate render.GAP -- the bezel compensation between tiles.

The pad's twelve tiles are separate windows in a physical bezel. An image split
naively across them is drawn as if the tiles were adjacent, so straight lines
kink and circles flatten at every seam. Compensating means discarding the
pixels that fall behind each divider.

This tool shows the same test pattern -- concentric circles plus corner-to-corner
diagonals, both of which make seam errors obvious -- at a series of candidate gap
values, and prints which is on screen. Watch the pad and note the value where
the circles look roundest and the diagonals run straight across the dividers,
then set GAP in deck/render.py.

    python3 tools/gapcal.py                 # sweep the default candidates
    python3 tools/gapcal.py 12 14 16        # sweep specific values
    python3 tools/gapcal.py --hold 14       # show one value until Ctrl-C
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

import duo87
from deck import render

CANDIDATES = [0, 6, 10, 14, 18, 24]
SECONDS = 5


def pattern(size=900):
    """Shallow diagonals. A wrong gap shows as a sideways jog where a line
    crosses a divider; the dark divider itself is unavoidable, so judge only
    whether the segments stay collinear, not whether the line is unbroken."""
    im = Image.new('RGB', (size, size), (12, 12, 16))
    d = ImageDraw.Draw(im)
    # Shallow slopes make a misalignment far more visible than a 45 degree line.
    for i, frac in enumerate((0.18, 0.45, 0.72)):
        y = size * frac
        colour = [(250, 210, 60), (90, 230, 140), (120, 170, 255)][i]
        d.line([0, y, size, y + size * 0.28], fill=colour, width=9)
    return im


def show(dev, src, gap, label=True, col_shift=None, label_value=None,
         row_shift=None):
    tiles = render.tile_block(src, 3, 4, gap=gap, col_shift=col_shift,
                              row_shift=row_shift)
    shown = gap if label_value is None else label_value
    for (c, r), im in tiles.items():
        key = render.key_at(c, r)
        if label and key == 1:
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 46, 22], fill=(0, 0, 0))
            d.text((3, 3), ('%g' % shown), font=render.font(15, True), fill=(255, 255, 0))
        buf = io.BytesIO()
        im.rotate(duo87.KEY_ROTATION).save(buf, 'JPEG', quality=90)
        dev.set_key_jpeg(key, buf.getvalue(), refresh=False)
    dev.refresh()


def main(argv):
    # --col N sweeps the crop nudge for column N (1-based) instead of the gap.
    col = row = None
    if '--col' in argv:
        i = argv.index('--col')
        col = int(argv[i + 1]) - 1
        del argv[i:i + 2]
    if '--row' in argv:
        i = argv.index('--row')
        row = int(argv[i + 1]) - 1
        del argv[i:i + 2]
    hold = '--hold' in argv
    if hold:
        argv.remove('--hold')
    if '--' in argv:                  # allows leading negative values
        argv.remove('--')
    values = [float(a) if '.' in a else int(a) for a in argv] or CANDIDATES

    dev = duo87.Duo87()
    dev.enable()
    src = pattern()
    try:
        if hold:
            for gap in values:
                show(dev, src, gap if col is None else render.GAP,
                     col_shift=None if col is None else
                     [gap if i == col else 0 for i in range(3)])
                print('showing gap=%d -- Ctrl-C to stop' % gap, flush=True)
                while True:
                    time.sleep(1)
        while True:
            for v in values:
                if row is not None:
                    rshift = list(render.ROW_SHIFT or [0, 0, 0, 0])
                    rshift += [0] * (4 - len(rshift))
                    rshift[row] = v
                    show(dev, src, render.GAP, row_shift=rshift, label_value=v)
                    print('row %d shift = %-5g' % (row + 1, v), flush=True)
                elif col is None:
                    show(dev, src, v)
                    print('gap = %-5g  (segments collinear across a seam = right)'
                          % v, flush=True)
                else:
                    # start from the calibrated defaults so the other columns
                    # stay correct while this one is swept
                    shift = list(render.COL_SHIFT or [0, 0, 0])
                    shift += [0] * (3 - len(shift))
                    shift[col] = v
                    show(dev, src, render.GAP, col_shift=shift, label_value=v)
                    print('column %d shift = %-5g' % (col + 1, v), flush=True)
                time.sleep(SECONDS)
            print('--- sweep complete, repeating ---', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
