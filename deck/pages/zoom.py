"""Zoom meeting controls.

Zoom exposes no local control API, so the only way to drive it is its keyboard
shortcuts -- which means synthesising keystrokes into whichever window has focus.
Two consequences worth being clear about:

* **The Zoom window must have focus.** A shortcut sent while the browser is
  focused goes to the browser. There is no way around this with keystrokes.
* **Wayland blocks input injection by design.** `xdotool` does nothing there.
  `ydotool` works but needs its daemon running and access to /dev/uinput. If no
  backend is usable the page shows a warning tile instead of pretending the
  buttons work.

The shortcuts themselves also differ per platform, hence SHORTCUTS below.
"""
from .. import render, osapi, icons
from ..core import Page

# freedesktop icon names per control, with an ASCII glyph fallback.
ZOOM_ICONS = {
    'mute':       ('audio-input-microphone', 'mic'),
    'mute_muted': ('microphone-disabled', 'mic'),
    'video':      ('camera-web', 'cam'),
    'video_off':  ('camera-disabled', 'cam'),
    'share':      ('video-display', 'scr'),
    'chat':       ('mail-message-new', 'msg'),
    'people':     ('system-users', 'ppl'),
    'hand':       ('go-up', 'hand'),
    'record':     ('media-record', 'rec'),
    'full':       ('view-fullscreen', 'full'),
    'join':       ('call-start', 'join'),
    'leave':      ('call-stop', 'end'),
}

# Zoom's defaults. Windows/Linux use Alt; macOS uses Cmd/Shift.
SHORTCUTS_PC = {
    'mute':     'alt+a',
    'video':    'alt+v',
    'share':    'alt+s',
    'chat':     'alt+h',
    'record':   'alt+r',
    'hand':     'alt+y',
    'people':   'alt+u',
    'fullscr':  'alt+f',
    'leave':    'alt+q',
}
SHORTCUTS_MAC = {
    'mute':     'cmd+shift+a',
    'video':    'cmd+shift+v',
    'share':    'cmd+shift+s',
    'chat':     'cmd+shift+h',
    'record':   'cmd+shift+r',
    'hand':     'option+y',
    'people':   'cmd+u',
    'fullscr':  'cmd+shift+f',
    'leave':    'cmd+w',
}


class ZoomPage(Page):
    title = 'zoom'
    interval = None

    def __init__(self, shortcuts=None, join_uri=None):
        self.shortcuts = dict(shortcuts or (SHORTCUTS_MAC if osapi.MACOS else SHORTCUTS_PC))
        self.join_uri = join_uri
        # Zoom does not report state back to us, so these are what *we* think the
        # state is: toggled locally on each press. They can drift if the user also
        # clicks in the Zoom window; pressing twice resyncs.
        self.muted = None
        self.video_off = None

    @property
    def _usable(self):
        return osapi.keystroke_backend() is not None

    def tiles(self, deck):
        warn = None
        if not self._usable:
            warn = ('install ydotool' if osapi.LINUX and osapi.os.environ.get('WAYLAND_DISPLAY')
                    else 'no key backend')

        def btn(icon_key, label, key, accent=None, face=render.SURFACE):
            name, glyph = ZOOM_ICONS[icon_key]
            img = icons.load_symbolic(name, 46)      # light monochrome icon
            return render.button_tile(img, label, glyph=glyph, glyph_size=20,
                                      face=face, accent=accent, key=key)

        mute_state = render.ALERT if self.muted else (render.OK if self.muted is False else None)
        vid_state = render.ALERT if self.video_off else (render.OK if self.video_off is False else None)

        out = {
            1: btn('mute_muted' if self.muted else 'mute', 'mute', 1, accent=mute_state),
            2: btn('video_off' if self.video_off else 'video', 'video', 2, accent=vid_state),
            3: btn('share', 'share', 3),
            4: btn('chat', 'chat', 4),
            5: btn('people', 'people', 5),
            6: btn('hand', 'hand', 6),
            7: btn('record', 'record', 7),
            8: btn('full', 'full', 8),
            9: render.blank_tile(),
            10: render.text_tile(warn, bg=render.SURFACE, fg=render.WARN,
                                 size=11) if warn else render.blank_tile(),
            11: btn('join', 'join', 11) if self.join_uri else render.blank_tile(),
            12: btn('leave', 'leave', 12, face=(90, 24, 24), accent=render.ALERT),
        }
        return out

    def on_press(self, deck, key):
        mapping = {1: 'mute', 2: 'video', 3: 'share', 4: 'chat', 5: 'people',
                   6: 'hand', 7: 'record', 8: 'fullscr', 12: 'leave'}
        if key == 11 and self.join_uri:
            osapi.open_uri(self.join_uri)
            return
        name = mapping.get(key)
        if not name:
            return
        combo = self.shortcuts.get(name)
        if not combo:
            return
        sent = osapi.keystroke(combo)
        if sent and name == 'mute':
            self.muted = not self.muted if self.muted is not None else True
        elif sent and name == 'video':
            self.video_off = not self.video_off if self.video_off is not None else True
        deck.repaint()
