"""System monitor, drawn across the whole pad.

Twelve separate numbers is the wrong shape for this: what you want from a
monitor is the trend, and a trend needs width. Drawing on one canvas buys a
full-width history graph per metric, which a 3x4 grid of 80x80 tiles cannot do.

Uses psutil when installed and /proc otherwise, so it works on a bare Python.
Metrics this machine does not have (battery on a desktop) are simply omitted
rather than shown as '--'.
"""
import collections
import time

from .. import render, osapi
from ..core import CanvasPage

HISTORY = 120          # samples kept; at interval=1.0 that is two minutes


def _colour(pct, warn=70, alert=88):
    if pct is None:
        return render.MUTED
    if pct >= alert:
        return render.ALERT
    if pct >= warn:
        return render.WARN
    return render.OK


class SysMonPage(CanvasPage):
    title = 'system'
    interval = 1.0

    def __init__(self, disk_path='/'):
        self.disk_path = disk_path
        self.cpu = collections.deque(maxlen=HISTORY)
        self.mem = collections.deque(maxlen=HISTORY)

    def _sample(self):
        c, m = osapi.cpu_percent(), osapi.memory_percent()
        if c is not None:
            self.cpu.append(c)
        if m is not None:
            self.mem.append(m)

    @staticmethod
    def _graph(d, series, box, colour, fill=True):
        """Filled line graph of `series` (0..100) inside box (x0, y0, x1, y1)."""
        x0, y0, x1, y1 = box
        d.rectangle(box, fill=(26, 27, 33))
        if len(series) < 2:
            return
        n = len(series)
        w, h = x1 - x0, y1 - y0
        pts = [(x0 + w * i / (n - 1), y1 - h * min(100.0, max(0.0, v)) / 100.0)
               for i, v in enumerate(series)]
        if fill:
            d.polygon([(x0, y1)] + pts + [(x1, y1)], fill=tuple(int(c * 0.30) for c in colour))
        d.line(pts, fill=colour, width=2, joint='curve')

    def _metrics(self):
        return dict(cpu=self.cpu[-1] if self.cpu else None,
                    mem=self.mem[-1] if self.mem else None,
                    disk=osapi.disk_percent(self.disk_path),
                    temp=osapi.temperature(),
                    load=osapi.load_average(),
                    batt=osapi.battery_percent())

    def draw(self, deck, im, d):
        """Graphs only. They cross dividers happily; text does not (draw_overlay)."""
        self._sample()
        W, H = im.size
        rows = self.row_bands()
        d.rectangle([0, 0, W, H], fill=render.BG)
        m = self._metrics()
        for (series, cur), (by0, by1) in zip(
                ((self.cpu, m['cpu']), (self.mem, m['mem'])), rows[1:3]):
            self._graph(d, list(series), (6, by0 + 26, W - 6, by1 - 4), _colour(cur))

    def draw_overlay(self, deck, im, d):
        """All text, on the uncompensated canvas so no glyph is lost to a bezel."""
        W, H = im.size
        rows, cols = self.overlay_row_bands(), self.overlay_col_bands()
        m = self._metrics()

        # --- band 0: clock ------------------------------------------------
        # A big HH:MM would cross the column-1/2 seam (and column 1 is clipped on
        # its right), so it breaks on the physical gap. Split it: HH ends inside
        # column 1, MM starts inside column 2, and the gap reads as the separator.
        y0, y1 = rows[0]
        cy = (y0 + y1) // 2 - 2
        now = time.strftime('%H:%M').split(':')
        col1_r, col2_l = cols[0][1], cols[1][0]
        d.text((col1_r - 18, cy), now[0] + ':', font=render.font(46, True),
               fill=render.FG, anchor='rm')             # "HH:", right of column 1
        d.text((col2_l + 4, cy), now[1], font=render.font(46, True),
               fill=render.FG, anchor='lm')             # MM, left of column 2
        d.text((W - 10, y0 + 24), time.strftime('%a %d %b'),
               font=render.font(13, False), fill=render.MUTED, anchor='rm')
        d.text((W - 10, y0 + 46), 'up %s' % (self._uptime() or '--'),
               font=render.font(12, False), fill=render.MUTED, anchor='rm')

        # --- bands 1 and 2: graph labels ----------------------------------
        for (label, cur), (by0, _by1) in zip(
                (('cpu', m['cpu']), ('memory', m['mem'])), rows[1:3]):
            d.text((6, by0 + 12), label, font=render.font(13, False),
                   fill=render.MUTED, anchor='lm')
            d.text((W - 6, by0 + 12), '%d%%' % round(cur) if cur is not None else '--',
                   font=render.font(18, True), fill=_colour(cur), anchor='rm')

        # --- band 3: one stat per tile column, so none straddles a divider --
        fy0, _fy1 = rows[3]
        stats = [('disk', '%d%%' % round(m['disk']) if m['disk'] is not None else '--',
                  _colour(m['disk'])),
                 ('temp', '%d°' % round(m['temp']) if m['temp'] is not None else '--',
                  _colour(m['temp'], 70, 85)),
                 ('load', '%.2f' % m['load'] if m['load'] is not None else '--', render.FG)]
        if m['batt'] is not None:
            stats[2] = ('batt', '%d%%' % round(m['batt']),
                        render.ALERT if m['batt'] < 20 else render.FG)
        for (label, value, colour), (cx0, cx1) in zip(stats, cols):
            cx = (cx0 + cx1) // 2
            d.text((cx, fy0 + 30), value, font=render.font(22, True), fill=colour, anchor='mm')
            d.text((cx, fy0 + 58), label, font=render.font(12, False),
                   fill=render.MUTED, anchor='mm')

    @staticmethod
    def _uptime():
        try:
            with open('/proc/uptime') as f:
                secs = float(f.readline().split()[0])
        except (OSError, ValueError):
            return None
        days, rem = divmod(int(secs), 86400)
        hours, mins = divmod(rem // 60, 60)
        return '%dd %dh' % (days, hours) if days else '%dh %02dm' % (hours, mins)
