"""Now playing, drawn across the whole pad.

The tile-based MediaPage is the one with buttons; this is the one to look at.
Album art fills the entire panel, with a dark scrim at the bottom carrying the
title, artist and progress -- the layout a phone lock screen uses, for the same
reason: the art is the content, the text is an overlay on it.
"""
import os

from .. import render, osapi
from ..core import CanvasPage


def _mmss(seconds):
    if seconds is None:
        return '--:--'
    s = int(max(0, seconds))
    return '%d:%02d' % (s // 60, s % 60)


class NowPlayingPage(CanvasPage):
    title = 'now playing'
    interval = 1.0

    def __init__(self, show_progress=True):
        self.show_progress = show_progress
        self._info = {}
        self._art_path = None
        self._art = None

    def on_show(self, deck):
        self._info = osapi.media_status()

    def _cover(self, size):
        path = self._info.get('art')
        if not path or not os.path.exists(path):
            self._art_path, self._art = None, None
            return None
        if path != self._art_path or (self._art and self._art.size != size):
            try:
                from PIL import Image
                with Image.open(path) as raw:
                    raw.load()
                    src = raw.convert('RGB')
                sw, sh = src.size
                scale = max(size[0] / sw, size[1] / sh)
                resized = src.resize((max(1, round(sw * scale)), max(1, round(sh * scale))),
                                     Image.LANCZOS)
                rw, rh = resized.size
                left, top = (rw - size[0]) // 2, (rh - size[1]) // 2
                self._art = resized.crop((left, top, left + size[0], top + size[1]))
                self._art_path = path
            except Exception:
                self._art_path, self._art = None, None
        return self._art

    def draw(self, deck, im, d):
        """The art only -- bezel-compensated, so the picture stays undistorted."""
        self._info = osapi.media_status()
        W, H = im.size
        cover = self._cover((W, H))
        if cover:
            im.paste(cover, (0, 0))
        else:
            d.rectangle([0, 0, W, H], fill=render.SURFACE)
            d.text((W // 2, H // 2 - 30), '♪', font=render.font(72, True),
                   fill=(70, 72, 82), anchor='mm')

    def draw_overlay(self, deck, im, d):
        """Scrim and text, uncompensated so no character is hidden by a divider."""
        info = self._info
        W, H = im.size
        rows = self.overlay_row_bands()
        band0, band1 = rows[3]

        if not info.get('title'):
            msg = 'nothing playing' if osapi.media_available() else 'no player running'
            mid = rows[1]
            d.text((W // 2, (mid[0] + mid[1]) // 2), msg, font=render.font(15, False),
                   fill=render.MUTED + (255,), anchor='mm')
            return

        # Gradient scrim: without it, light album art makes white text unreadable.
        # Pillow has no gradient primitive, hence the line stack.
        top = rows[2][0]
        for i in range(H - top):
            alpha = int(238 * min(1.0, (i / max(1, band0 - top)) ** 0.8))
            d.line([0, top + i, W, top + i], fill=(0, 0, 0, alpha))

        y = band0 + 5
        for text, size, fill in ((info.get('title'), 18, render.FG),
                                 (info.get('artist'), 13, (198, 200, 208))):
            if not text:
                continue
            f = render.font(size, size > 15)
            while d.textlength(text, font=f) > W - 12 and size > 9:
                size -= 1
                f = render.font(size, size > 15)
            d.text((6, y), text, font=f, fill=fill + (255,))
            y += size + 5

        if self.show_progress:
            pos, length = info.get('position'), info.get('length')
            bx0, bx1, by = 6, W - 6, band1 - 19
            d.rectangle([bx0, by, bx1, by + 4], fill=(95, 97, 105, 255))
            if pos and length:
                frac = max(0.0, min(1.0, pos / length))
                d.rectangle([bx0, by, bx0 + (bx1 - bx0) * frac, by + 4],
                            fill=render.ACCENT + (255,))
            small = render.font(11, False)
            d.text((bx0, band1 - 8), _mmss(pos), font=small,
                   fill=render.MUTED + (255,), anchor='lm')
            d.text((bx1, band1 - 8), _mmss(length), font=small,
                   fill=render.MUTED + (255,), anchor='rm')
            status = (info.get('status') or '').lower()
            if status and status != 'playing':
                d.text((W // 2, band1 - 8), status.upper(), font=render.font(10, True),
                       fill=render.WARN + (255,), anchor='mm')

    def on_press(self, deck, key):
        # The whole surface is art, so give it one obvious behaviour rather than
        # invisible hit zones: any tap toggles playback.
        osapi.media('play_pause')
        import time
        time.sleep(0.2)
        deck.repaint()
