"""Audio device page: pick the default output (top half) and input (bottom half).

Tiles 1-6 are output devices (speakers/headphones), 7-12 are input devices
(microphones). The current default in each region is highlighted; tapping
another makes it the default and moves existing streams to it. Uses
osapi.audio_* (PipeWire/Pulse via pactl).
"""
from .. import render, osapi, icons
from ..core import Page


def _label(dev):
    """A short, distinctive label from the device's metadata."""
    desc = dev.get('description') or ''
    if 'HDMI' in desc:
        return 'HDMI'
    if dev.get('form_factor') == 'internal':
        return 'Built-in'
    name = dev.get('card_name') or desc
    for junk in ('Microsoft ', 'HDA ', ' Analog Stereo', ' Stereo'):
        name = name.replace(junk, '')
    name = name.strip()
    return name if len(name) <= 16 else name[:15].rstrip() + '…'


def _icon_for(dev, is_output):
    """Pick a distinct icon from bus / form factor / HDMI."""
    desc = (dev.get('description') or '').upper()
    ff = dev.get('form_factor') or ''
    bus = dev.get('bus') or ''
    if bus == 'bluetooth':
        return 'bluetooth'
    if is_output:
        if 'HDMI' in desc or 'DISPLAYPORT' in desc:
            return 'video-display'
        if ff in ('headphone', 'headset'):
            return 'audio-headphones'
        if bus == 'usb':
            return 'audio-speakers'
        return 'audio-card'
    else:
        if ff == 'webcam' or 'CAM' in desc.upper():
            return 'camera-web'
        if ff == 'headset':
            return 'audio-headset'
        return 'audio-input-microphone'


class AudioPage(Page):
    title = 'audio'
    interval = 3.0          # devices and the default can change under us

    def __init__(self):
        self._outputs = []
        self._inputs = []

    def _dev_tile(self, dev, is_output, key):
        active = dev.get('default')
        face = (24, 60, 40) if active else render.SURFACE     # green-tinted when active
        img = icons.load_symbolic(_icon_for(dev, is_output), 40,
                                  tint=(235, 245, 238) if active else (205, 205, 212))
        return render.button_tile(img, _label(dev), icon_size=38, label_size=15,
                                  face=face, accent=render.OK if active else None, key=key)

    def tiles(self, deck):
        self._outputs = osapi.audio_outputs()
        self._inputs = osapi.audio_inputs()
        out = {}
        # Top two rows: outputs (tiles 1-6). Bottom two rows: inputs (7-12).
        for i in range(6):
            key = i + 1
            out[key] = (self._dev_tile(self._outputs[i], True, key)
                        if i < len(self._outputs) else render.blank_tile())
        for i in range(6):
            key = i + 7
            out[key] = (self._dev_tile(self._inputs[i], False, key)
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
