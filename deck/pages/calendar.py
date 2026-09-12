"""Calendar page: the next few events, read from iCalendar (.ics) files.

Deliberately reads plain .ics rather than talking to a specific calendar service:
every calendar app can export or sync one, which keeps the page portable and
avoids credentials. Point it at local files, or at files something else keeps in
sync (vdirsyncer, a Nextcloud/ownCloud folder, an exported Google calendar).

The parser handles the subset that matters for "what is next": VEVENT, SUMMARY,
DTSTART/DTEND, and line unfolding. **Recurring events (RRULE) are not expanded**,
so a weekly stand-up defined once will not appear -- see the note in CLAUDE.md.
"""
import datetime
import glob
import os
import time

from .. import render, osapi
from ..core import Page


def _parse_dt(value, params):
    """iCalendar date/time -> aware datetime, or None. Handles the three forms
    that actually occur: UTC (Z suffix), floating local, and VALUE=DATE."""
    value = value.strip()
    try:
        if 'VALUE=DATE' in params or (len(value) == 8 and value.isdigit()):
            d = datetime.datetime.strptime(value, '%Y%m%d')
            return d.replace(tzinfo=datetime.timezone.utc).astimezone()
        if value.endswith('Z'):
            d = datetime.datetime.strptime(value, '%Y%m%dT%H%M%SZ')
            return d.replace(tzinfo=datetime.timezone.utc).astimezone()
        d = datetime.datetime.strptime(value, '%Y%m%dT%H%M%S')
        return d.astimezone()
    except ValueError:
        return None


def parse_ics(text):
    """Yield (start, end, summary) for each VEVENT with a usable DTSTART."""
    # Unfold: a leading space or tab continues the previous line.
    lines, buf = [], ''
    for raw in text.splitlines():
        if raw[:1] in (' ', '\t'):
            buf += raw[1:]
        else:
            if buf:
                lines.append(buf)
            buf = raw
    if buf:
        lines.append(buf)

    ev, out = None, []
    for line in lines:
        u = line.upper()
        if u.startswith('BEGIN:VEVENT'):
            ev = {}
        elif u.startswith('END:VEVENT'):
            if ev and ev.get('start'):
                out.append((ev['start'], ev.get('end'), ev.get('summary', '(no title)')))
            ev = None
        elif ev is not None and ':' in line:
            name, value = line.split(':', 1)
            params = name.upper()
            key = params.split(';', 1)[0]
            if key == 'SUMMARY':
                ev['summary'] = value.replace('\\,', ',').replace('\\n', ' ').strip()
            elif key == 'DTSTART':
                ev['start'] = _parse_dt(value, params)
            elif key == 'DTEND':
                ev['end'] = _parse_dt(value, params)
    return out


class CalendarPage(Page):
    """Shows the next `slots` upcoming events across all configured .ics files.

    `sources` is a list of file paths or glob patterns. Files are re-read at
    `reload_every` seconds, not on every repaint, so a large calendar does not
    cost anything on the once-a-minute tick.
    """

    title = 'calendar'
    interval = 30.0

    def __init__(self, sources=(), slots=9, reload_every=300, open_command=None):
        self.sources = list(sources)
        self.slots = min(slots, 11)
        self.reload_every = reload_every
        self.open_command = open_command
        self._events = []
        self._loaded = 0.0
        self._error = None

    def _load(self):
        paths = []
        for src in self.sources:
            paths.extend(sorted(glob.glob(os.path.expanduser(src))))
        events, errors = [], []
        for p in paths:
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    events.extend(parse_ics(f.read()))
            except OSError as e:
                errors.append('%s: %s' % (os.path.basename(p), e.strerror))
        self._error = None if paths else ('no .ics files' if self.sources else 'not configured')
        if errors and not events:
            self._error = errors[0]
        now = datetime.datetime.now().astimezone()
        horizon = now - datetime.timedelta(hours=1)      # keep the one in progress
        self._events = sorted((e for e in events if e[0] and e[0] >= horizon),
                              key=lambda e: e[0])
        self._loaded = time.time()

    def _label(self, start, summary):
        now = datetime.datetime.now().astimezone()
        delta = start - now
        if delta.total_seconds() < 0:
            when = 'now'
        elif start.date() == now.date():
            when = start.strftime('%H:%M')
        elif delta.days < 6:
            when = start.strftime('%a %H:%M')
        else:
            when = start.strftime('%d %b')
        return when, summary

    def tiles(self, deck):
        if time.time() - self._loaded > self.reload_every:
            self._load()

        out = {}
        if self._error:
            out[1] = render.text_tile(self._error, bg=render.SURFACE, fg=render.WARN, size=12)
        elif not self._events:
            out[1] = render.text_tile('nothing scheduled', bg=render.SURFACE,
                                      fg=render.MUTED, size=12)

        for i, (start, _end, summary) in enumerate(self._events[:self.slots], start=1):
            if i in out:
                continue
            when, what = self._label(start, summary)
            soon = (start - datetime.datetime.now().astimezone()).total_seconds() < 900
            out[i] = render.tile(sub=when, label=None, value=None, bg=render.SURFACE,
                                 accent=render.WARN if soon else None)
            # tile() centres a value; for an event we want the wrapped title
            # under the time, so compose it directly instead.
            out[i] = self._event_tile(when, what, soon)

        out[12] = render.tile(label='open', value='cal', bg=render.SURFACE, value_size=18)
        for k in range(1, 13):
            out.setdefault(k, render.blank_tile())
        return out

    @staticmethod
    def _event_tile(when, what, soon):
        from PIL import ImageDraw
        im = render.blank(render.SURFACE)
        d = ImageDraw.Draw(im)
        if soon:
            d.rectangle([0, 0, 2, render.SIZE], fill=render.WARN)
        d.text((render.SIZE // 2, 14), when, font=render.font(14, True),
               fill=render.WARN if soon else render.ACCENT, anchor='mm')
        words, lines, cur = what.split(), [], ''
        f = render.font(11, False)
        for w in words:
            trial = (cur + ' ' + w).strip()
            if d.textlength(trial, font=f) <= render.SIZE - 8 or not cur:
                cur = trial
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines[:4]):
            d.text((render.SIZE // 2, 32 + i * 13), ln, font=f, fill=render.FG, anchor='mm')
        return im

    def on_press(self, deck, key):
        if key == 12 and self.open_command:
            osapi.launch(self.open_command)
        elif key == 12:
            self._load()
            deck.repaint()
