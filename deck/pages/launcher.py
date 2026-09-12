"""The default page: a grid of application launchers.

Each tile shows an icon from the system icon theme (SVG or PNG, via deck.icons)
with an optional label, falling back to a text tile when no icon resolves.
"""
import time

from .. import render, osapi, icons
from ..core import Page


class LauncherPage(Page):
    """Up to twelve launchers, configured as a list of dicts:

        {'label': 'Firefox', 'command': 'firefox'}
        {'label': 'Mail', 'uri': 'https://mail.example.com', 'icon': 'mail'}
        {'label': 'Files', 'command': ['nautilus'], 'icon': 'org.gnome.Nautilus'}

    `icon` is a theme icon name or an absolute image path; without it the icon is
    guessed from the command. `colour` overrides the tile background. Entries
    beyond twelve are ignored.
    """

    interval = None          # static: nothing changes unless the user edits config

    def __init__(self, items, title='apps', use_icons=True, labels=True, icon_size=None):
        self.items = list(items)[:12]
        self.title = title
        self.use_icons = use_icons
        self.labels = labels
        self.icon_size = icon_size
        self._flash = {}     # key -> (until, ok): green/red accent after a launch

    def tiles(self, deck):
        now = time.time()
        out = {}
        for i, item in enumerate(self.items, start=1):
            bg = tuple(item['colour']) if item.get('colour') else render.SURFACE
            flash = self._flash.get(i)
            accent = None
            if flash and now < flash[0]:
                accent = render.OK if flash[1] else render.ALERT
            label = item.get('label', '?')

            img = None
            if self.use_icons:
                name = icons.guess_name(item)
                if name:
                    img = icons.load_icon(name, 96)
            face = tuple(item['colour']) if item.get('colour') else render.SURFACE
            if img is not None:
                out[i] = render.button_tile(img, label if self.labels else None,
                                            face=face, accent=accent, key=i)
            else:
                # No icon: show the label as the button's own text.
                out[i] = render.button_tile(glyph=label, glyph_size=20,
                                            face=face, accent=accent, key=i)
        return out

    def on_press(self, deck, key):
        if key > len(self.items):
            return
        item = self.items[key - 1]
        if item.get('uri'):
            ok = osapi.open_uri(item['uri'])
        elif item.get('command'):
            ok = osapi.launch(item['command'])
        else:
            ok = False
        # A green/red accent after launch shows success/failure on the pad itself
        # (distinct from the press flash, which just confirms the tap landed).
        self._flash[key] = (time.time() + 1.0, ok)
        deck.repaint()
        self.interval = 1.2          # one tick to clear the flash

    def on_show(self, deck):
        self.interval = None
