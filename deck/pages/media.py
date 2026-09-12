"""Media control page (the interactive counterpart to the now-playing card).

Transport and volume as icon buttons, plus a small album-art thumbnail and the
title/artist. Controls whatever is playing via MPRIS (osapi.media_*). The full
-panel art view lives in the wallpaper NowPlayingCard; this page is the buttons.
"""
import os
import time

from PIL import Image

from .. import render, osapi, icons
from ..core import Page

# freedesktop icon names, with an ASCII glyph fallback if the theme lacks them.
_CONTROLS = {
    'prev':  ('media-skip-backward', '|<'),
    'play':  ('media-playback-start', '>'),
    'pause': ('media-playback-pause', '||'),
    'next':  ('media-skip-forward', '>|'),
    'voldn': ('audio-volume-low', '−'),
    'mute':  ('audio-volume-muted', 'x'),
    'volup': ('audio-volume-high', '+'),
}


def _mmss(seconds):
    if seconds is None:
        return None
    s = int(max(0, seconds))
    return '%d:%02d' % (s // 60, s % 60)


class MediaPage(Page):
    title = 'media'
    interval = 1.0

    def __init__(self, volume_step=5):
        self.volume_step = volume_step
        self._info = {}
        self._art_path = None
        self._art_tiles = None

    def on_show(self, deck):
        self._info = osapi.media_status()

    def _btn(self, which, label, key, accent=None):
        name, glyph = _CONTROLS[which]
        img = icons.load_symbolic(name, 48)          # light monochrome icon
        return render.button_tile(img, label, glyph=glyph, glyph_size=26,
                                  accent=accent, key=key)

    def _art(self):
        path = self._info.get('art')
        if not path or not os.path.exists(path):
            self._art_path, self._art_tiles = None, None
            return None
        if path != self._art_path:
            try:
                with Image.open(path) as im:
                    im.load()
                    self._art_tiles = render.tile_block(im, 2, 2)
                self._art_path = path
            except Exception:
                self._art_path, self._art_tiles = None, None
        return self._art_tiles

    def tiles(self, deck):
        self._info = osapi.media_status()
        info = self._info
        playing = (info.get('status') or '').lower() == 'playing'
        vol, muted = osapi.get_volume()
        out = {}

        # Rows 1-2: now playing. Title on 1, artist on 4, album art on 2,3,5,6.
        title = info.get('title') or ('paused' if info.get('status') else 'nothing playing')
        out[1] = render.text_tile(title, bg=render.BG, size=13,
                                  accent=render.OK if playing else None)
        out[4] = (render.text_tile(info['artist'], bg=render.BG, size=12, fg=render.MUTED)
                  if info.get('artist') else render.blank_tile())
        art = self._art()
        for (c, r) in ((0, 0), (1, 0), (0, 1), (1, 1)):
            key = render.key_at(c + 1, r)            # cols 2-3, rows 1-2 -> 2,3,5,6
            out[key] = art[(c, r)] if art else render.blank_tile()

        # Rows 3-4: transport + volume as icon buttons.
        out[7] = self._btn('prev', 'prev', 7)
        out[8] = self._btn('pause' if playing else 'play', 'pause' if playing else 'play',
                           8, accent=render.OK if playing else None)
        out[9] = self._btn('next', 'next', 9)
        out[10] = self._btn('voldn', 'vol -', 10)
        # The mute button shows the current volume level, and its muted state.
        vol_label = 'muted' if muted else ('%d%%' % vol if vol is not None else 'mute')
        out[11] = self._btn('mute' if muted else 'volup', vol_label, 11,
                            accent=render.ALERT if muted else None)
        out[12] = self._btn('volup', 'vol +', 12)
        return out

    def on_press(self, deck, key):
        actions = {
            7: lambda: osapi.media('previous'),
            8: lambda: osapi.media('play_pause'),
            9: lambda: osapi.media('next'),
            10: lambda: osapi.volume(-self.volume_step),
            11: lambda: osapi.volume(mute=True),
            12: lambda: osapi.volume(+self.volume_step),
        }
        act = actions.get(key)
        if act:
            act()
            time.sleep(0.2)      # let the player update its MPRIS state
            deck.repaint()
