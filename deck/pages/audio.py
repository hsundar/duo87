"""Audio device page: pick the default output (top half) and input (bottom half).

Tiles 1-6 are output devices (speakers/headphones), 7-12 are input devices
(microphones). The current default in each region is highlighted; tapping
another makes it the default and moves existing streams to it. Uses
osapi.audio_* (PipeWire/Pulse via pactl).
"""
from .. import render, osapi, icons
from ..core import Page


def _short(desc):
    """Trim boilerplate from a device description and cap the length for a label."""
    for junk in (' Analog Stereo', ' Digital Stereo', ' Stereo', ' Audio Controller',
                 ' High Definition', ' Digital', ' Analog'):
        desc = desc.replace(junk, '')
    desc = desc.strip()
    return desc if len(desc) <= 22 else desc[:21].rstrip() + '…'


class AudioPage(Page):
    title = 'audio'
    interval = 3.0          # devices and the default can change under us

    def __init__(self):
        self._outputs = []
        self._inputs = []

    def _dev_tile(self, dev, icon_name, key):
        active = dev.get('default')
        face = (24, 60, 40) if active else render.SURFACE     # green-tinted when active
        img = icons.load_symbolic(icon_name, 42,
                                  tint=(235, 245, 238) if active else (210, 210, 216))
        return render.button_tile(img, _short(dev['description']),
                                  face=face, accent=render.OK if active else None, key=key)

    def tiles(self, deck):
        self._outputs = osapi.audio_outputs()
        self._inputs = osapi.audio_inputs()
        out = {}
        # Top two rows: outputs (tiles 1-6). Bottom two rows: inputs (7-12).
        for i in range(6):
            key = i + 1
            out[key] = (self._dev_tile(self._outputs[i], 'audio-volume-high', key)
                        if i < len(self._outputs) else render.blank_tile())
        for i in range(6):
            key = i + 7
            out[key] = (self._dev_tile(self._inputs[i], 'audio-input-microphone', key)
                        if i < len(self._inputs) else render.blank_tile())
        if not osapi.LINUX or not osapi._has('pactl'):
            out[5] = render.text_tile('pactl not found', bg=render.SURFACE,
                                      fg=render.WARN, size=12)
        return out

    def on_press(self, deck, key):
        changed = False
        if 1 <= key <= 6 and key - 1 < len(self._outputs):
            changed = osapi.set_audio_output(self._outputs[key - 1]['name'])
        elif 7 <= key <= 12 and key - 7 < len(self._inputs):
            changed = osapi.set_audio_input(self._inputs[key - 7]['name'])
        if changed:
            deck.repaint()
