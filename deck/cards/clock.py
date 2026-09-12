"""Clock card: a large full-panel clock and date.

The simplest WallpaperCard and a good default -- it needs nothing external and
always renders. `interval` is short so the minute stays current while the card
is on screen; the Deck only re-uploads when the rendered image actually changes,
so a still minute costs nothing.
"""
import time

from PIL import ImageDraw

from .. import render
from ..core import WallpaperCard


class ClockCard(WallpaperCard):
    title = 'clock'
    interval = 30.0          # re-render twice a minute; unchanged frames are skipped

    def __init__(self, time_fmt='%H:%M', date_fmt='%A', sub_fmt='%d %B %Y'):
        self.time_fmt = time_fmt
        self.date_fmt = date_fmt
        self.sub_fmt = sub_fmt

    def render(self, deck):
        im = render.card_canvas()
        d = ImageDraw.Draw(im)
        sx0, sy0, sx1, sy1 = render.card_safe()
        cx = sx1 // 2          # centre within the safe area, not the raw panel
        now = time.localtime()

        # Fit the time to the safe width so wide strings (e.g. 12h "12:00 am")
        # never clip into the masked margin.
        t = time.strftime(self.time_fmt, now)
        size = 110
        f = render.font(size, True)
        while d.textlength(t, font=f) > sx1 - 16 and size > 40:
            size -= 4
            f = render.font(size, True)
        d.text((cx, 150), t, font=f, fill=render.FG, anchor='mm')
        d.text((cx, 250), time.strftime(self.date_fmt, now),
               font=render.font(34, True), fill=render.ACCENT, anchor='mm')
        d.text((cx, 300), time.strftime(self.sub_fmt, now),
               font=render.font(22), fill=render.MUTED, anchor='mm')
        return im
