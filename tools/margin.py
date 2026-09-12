#!/usr/bin/env python3
"""Measure the unreachable margin along the bottom and right of the panel.

The panel is one continuous screen, but `BAT` only addresses twelve key windows
(keys 0 and 13..20 draw nothing), and images grow up-and-left from a bottom-right
anchor. So the strip along the bottom and right edges cannot be lit by anything
we know how to send -- only the firmware's own stock screen covers it.

Knowing how wide that strip is tells us the panel's true resolution, which is the
missing number behind the COL_SHIFT fudge in deck/render.py.

Step 1 -- light every key window pure white, so the dark margin is unmistakable:

    python3 tools/margin.py

Step 2 -- hold a ruler against the glass and measure, in millimetres:
    * the width of ONE key window   (bright square, edge to edge)
    * the dark strip along the RIGHT edge of the glass
    * the dark strip along the BOTTOM edge of the glass
  Measure the strip outside the outermost bright squares, not the thin lines
  between them.

Step 3 -- convert to pixels (a key window is 112 px):

    python3 tools/margin.py --tile 14.5 --right 5 --bottom 3

Compare the answer with the stock screen: swipe vertically to bring it up and
check that it really does light the strip. If it does, a command we have not
found can address it -- see captures/WINDOWS_CAPTURE.md.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

import duo87
from deck import render

COLS, ROWS = 3, 4


def report(tile_mm, right_mm, bottom_mm):
    if not tile_mm:
        raise SystemExit('--tile is required (width of one bright square, mm)')
    px_per_mm = render.SIZE / tile_mm
    right_px = right_mm * px_per_mm
    bottom_px = bottom_mm * px_per_mm
    print('key window        : %d px = %.1f mm  (%.2f px/mm)'
          % (render.SIZE, tile_mm, px_per_mm))
    print('right margin      : %.1f mm = %.0f px' % (right_mm, right_px))
    print('bottom margin     : %.1f mm = %.0f px' % (bottom_mm, bottom_px))
    # The lit area is COLS/ROWS windows plus whatever sits between them; this is
    # a lower bound on the panel, ignoring the inter-tile lines.
    w = COLS * render.SIZE + right_px
    h = ROWS * render.SIZE + bottom_px
    print()
    print('panel is at least  : %.0f x %.0f px' % (w, h))
    print('  (%d x %d of key windows, plus the margin; the thin lines between'
          % (COLS * render.SIZE, ROWS * render.SIZE))
    print('   windows are not counted, so the true panel is a little larger)')
    for guess in (320, 336, 352, 360, 384, 400, 480):
        if abs(guess - w) <= 24:
            print('  -> width is close to %d' % guess)
    for guess in (448, 460, 480, 512, 540, 600, 640):
        if abs(guess - h) <= 24:
            print('  -> height is close to %d' % guess)


def light_up():
    dev = duo87.Duo87()
    dev.enable()
    try:
        for r in range(ROWS):
            for c in range(COLS):
                im = Image.new('RGB', (render.SIZE, render.SIZE), (255, 255, 255))
                d = ImageDraw.Draw(im)
                d.rectangle([0, 0, render.SIZE - 1, render.SIZE - 1],
                            outline=(0, 0, 0), width=1)
                buf = io.BytesIO()
                im.rotate(duo87.KEY_ROTATION).save(buf, 'JPEG', quality=95)
                dev.set_key_jpeg(render.key_at(c, r), buf.getvalue(), refresh=False)
        dev.refresh()
    finally:
        dev.close()
    print('all twelve key windows lit white at %d x %d px.' % (render.SIZE, render.SIZE))
    print('measure the dark strip along the right and bottom edges, then run:')
    print('  python3 tools/margin.py --tile <mm> --right <mm> --bottom <mm>')


def main(argv):
    vals = {}
    for name in ('tile', 'right', 'bottom'):
        flag = '--' + name
        if flag in argv:
            i = argv.index(flag)
            vals[name] = float(argv[i + 1])
            del argv[i:i + 2]
    if vals:
        report(vals.get('tile'), vals.get('right', 0.0), vals.get('bottom', 0.0))
    else:
        light_up()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
