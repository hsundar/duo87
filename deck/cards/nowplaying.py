"""Now-playing card: album art filling the panel, title/artist/progress over it.

Full-panel version of the media info (the interactive transport buttons live in
the edit-mode MediaPage). Reads MPRIS via osapi.media_status(), so it follows
whatever is playing. `interval` is modest -- the art only changes per track, and
LOG writes are ~1.25 s, so we re-render on a cadence and the Deck skips the
upload when the rendered frame is unchanged.
"""
import os

from PIL import Image, ImageDraw

from .. import render, osapi
from ..core import WallpaperCard


def _mmss(seconds):
    if seconds is None:
        return None
    s = int(max(0, seconds))
    return '%d:%02d' % (s // 60, s % 60)


class NowPlayingCard(WallpaperCard):
    title = 'now playing'
    interval = 15.0

    def __init__(self, show_progress=True):
        self.show_progress = show_progress
        self._art_path = None
        self._art = None

    def _cover(self, path):
        """Cover-crop the art file to the full panel, cached by path."""
        if not path or not os.path.exists(path):
            self._art_path = self._art = None
            return None
        if path != self._art_path:
            try:
                with Image.open(path) as raw:
                    raw.load()
                    src = raw.convert('RGB')
                sw, sh = src.size
                scale = max(render.CARD_W / sw, render.CARD_H / sh)
                r = src.resize((max(1, round(sw * scale)), max(1, round(sh * scale))),
                               Image.LANCZOS)
                left, top = (r.width - render.CARD_W) // 2, (r.height - render.CARD_H) // 2
                self._art = r.crop((left, top, left + render.CARD_W, top + render.CARD_H))
                self._art_path = path
            except Exception:
                self._art_path = self._art = None
        return self._art

    def render(self, deck):
        info = osapi.media_status()
        im = render.card_canvas()
        d = ImageDraw.Draw(im)

        cover = self._cover(info.get('art'))
        if cover:
            im.paste(cover, (0, 0))
        else:
            d.rectangle([0, 0, render.CARD_W, render.CARD_H], fill=render.SURFACE)
            d.text((render.CARD_W // 2, render.CARD_H // 2 - 40), '♪',
                   font=render.font(120, True), fill=(70, 72, 82), anchor='mm')

        if not info.get('title'):
            msg = 'nothing playing' if osapi.media_available() else 'no player'
            d.text((render.CARD_W // 2, render.CARD_H // 2 + 40), msg,
                   font=render.font(20), fill=render.MUTED, anchor='mm')
            return im

        # Bottom scrim so text is readable over any art. Text stays inside the
        # safe area (the Deck masks the very bottom/right).
        sx0, sy0, sx1, sy1 = render.card_safe()
        scrim_top = sy1 - 150
        overlay = Image.new('RGBA', (render.CARD_W, sy1 - scrim_top), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for i in range(sy1 - scrim_top):
            a = int(230 * (i / (sy1 - scrim_top)) ** 0.75)
            od.line([0, i, render.CARD_W, i], fill=(0, 0, 0, a))
        im.paste(overlay, (0, scrim_top), overlay)

        y = sy1 - 128
        for text, size, fill, bold in ((info.get('title'), 30, render.FG, True),
                                       (info.get('artist'), 22, (205, 207, 214), False)):
            if not text:
                continue
            f = render.font(size, bold)
            while d.textlength(text, font=f) > sx1 - 16 and size > 12:
                size -= 1
                f = render.font(size, bold)
            d.text((16, y), text, font=f, fill=fill)
            y += size + 8

        if self.show_progress:
            pos, length = info.get('position'), info.get('length')
            bx0, bx1, by = 16, sx1 - 8, sy1 - 30
            d.rectangle([bx0, by, bx1, by + 6], fill=(95, 97, 105))
            if pos and length:
                frac = max(0.0, min(1.0, pos / length))
                d.rectangle([bx0, by, bx0 + (bx1 - bx0) * frac, by + 6], fill=render.ACCENT)
            small = render.font(16)
            if _mmss(pos):
                d.text((bx0, by + 20), _mmss(pos), font=small, fill=render.MUTED, anchor='lm')
            if _mmss(length):
                d.text((bx1, by + 20), _mmss(length), font=small, fill=render.MUTED, anchor='rm')
        return im
