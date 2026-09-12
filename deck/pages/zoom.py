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
    'open':        ('zoom', 'zm'),          # full-colour app icon (see _btn)
    'personal':    ('call-start', 'room'),
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
    """Two states, switched by whether a Zoom meeting window is open:

    * Idle -> launch actions: Open Zoom, Start personal room, Join (if set).
    * In a meeting -> the meeting controls (mute, video, share, ... , leave).

    The meeting is detected from the window list (osapi.zoom_meeting_active), so
    the page polls on `interval` and repaints when the state changes.
    """

    title = 'zoom'
    interval = 2.0          # poll for the meeting window

    def __init__(self, shortcuts=None, join_uri=None, personal_room=None,
                 open_command='zoom'):
        self.shortcuts = dict(shortcuts or (SHORTCUTS_MAC if osapi.MACOS else SHORTCUTS_PC))
        self.join_uri = join_uri
        self.personal_room = personal_room     # PMI number or a start URL
        self.open_command = open_command
        # Zoom does not report state back, so these are our local guess, toggled
        # on each press; pressing twice resyncs if it drifts.
        self.muted = None
        self.video_off = None
        self._active = False

    # -- helpers -----------------------------------------------------------
    def _btn(self, icon_key, label, key, accent=None, face=render.SURFACE, symbolic=True):
        name, glyph = ZOOM_ICONS[icon_key]
        img = icons.load_symbolic(name, 46) if symbolic else icons.load_icon(name, 64)
        return render.button_tile(img, label, glyph=glyph, glyph_size=20,
                                  face=face, accent=accent, key=key)

    def _personal_room_uri(self):
        pr = self.personal_room
        if not pr:
            return None
        pr = str(pr).strip()
        if pr.startswith(('http://', 'https://', 'zoommtg://')):
            return pr
        digits = pr.replace(' ', '').replace('-', '')
        if digits.isdigit():                   # a PMI number -> start it
            return 'zoommtg://zoom.us/start?confno=%s' % digits
        return pr

    def _keystroke_warning(self):
        if not osapi.LINUX:
            return None
        if osapi.ydotool_ready():
            return None
        if osapi._has('ydotool'):
            return 'run ydotoold'              # installed but daemon not running
        if osapi.os.environ.get('WAYLAND_DISPLAY'):
            return 'install ydotool'
        return None if osapi._has('xdotool') else 'no key backend'

    # -- rendering ---------------------------------------------------------
    def tiles(self, deck):
        self._active = osapi.zoom_meeting_active()
        return self._meeting_tiles() if self._active else self._idle_tiles()

    def _idle_tiles(self):
        out = {k: render.blank_tile() for k in range(1, 13)}
        out[1] = self._btn('open', 'Open Zoom', 1, symbolic=False)
        if self._personal_room_uri():
            out[2] = self._btn('personal', 'My Room', 2, accent=render.OK)
        if self.join_uri:
            out[3] = self._btn('join', 'Join', 3)
        out[10] = render.text_tile('no meeting', bg=render.BG, fg=render.MUTED, size=12)
        return out

    def _meeting_tiles(self):
        warn = self._keystroke_warning()
        mute_state = render.ALERT if self.muted else (render.OK if self.muted is False else None)
        vid_state = render.ALERT if self.video_off else (render.OK if self.video_off is False else None)
        out = {
            1: self._btn('mute_muted' if self.muted else 'mute', 'mute', 1, accent=mute_state),
            2: self._btn('video_off' if self.video_off else 'video', 'video', 2, accent=vid_state),
            3: self._btn('share', 'share', 3),
            4: self._btn('chat', 'chat', 4),
            5: self._btn('people', 'people', 5),
            6: self._btn('hand', 'hand', 6),
            7: self._btn('record', 'record', 7),
            8: self._btn('full', 'full', 8),
            9: render.blank_tile(),
            10: render.text_tile(warn, bg=render.SURFACE, fg=render.WARN,
                                 size=11) if warn else render.blank_tile(),
            11: render.blank_tile(),
            12: self._btn('leave', 'leave', 12, face=(90, 24, 24), accent=render.ALERT),
        }
        return out

    def on_press(self, deck, key):
        if not self._active:
            self._on_idle_press(deck, key)
            return
        mapping = {1: 'mute', 2: 'video', 3: 'share', 4: 'chat', 5: 'people',
                   6: 'hand', 7: 'record', 8: 'fullscr', 12: 'leave'}
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

    def _on_idle_press(self, deck, key):
        if key == 1:
            osapi.launch(self.open_command)
        elif key == 2 and self._personal_room_uri():
            osapi.open_uri(self._personal_room_uri())
        elif key == 3 and self.join_uri:
            osapi.open_uri(self.join_uri)
        else:
            return
        # Reset toggle guesses for the next meeting, then re-check shortly.
        self.muted = self.video_off = None
