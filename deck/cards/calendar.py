"""Calendar card: the next few events, full panel.

Reuses the iCalendar parser from deck.pages.calendar. Sources may be local .ics
files (or globs) and/or http(s) iCal URLs -- e.g. a Google Calendar "secret
address in iCal format". URLs are fetched on a background thread so the network
never blocks the deck, and the last good copy is cached; put private URLs in your
own ~/.config/duo87/config.toml, never in the repo.

RRULE recurring events are still not expanded -- only concrete VEVENTs appear.
"""
import datetime
import glob
import os
import threading
import time
import urllib.request

from PIL import ImageDraw

from .. import render
from ..core import WallpaperCard
from ..pages.calendar import parse_ics

#: One colour per calendar source, in config order. Google-ish, distinct, legible.
CALENDAR_COLOURS = [
    (66, 133, 244),    # blue
    (52, 168, 83),     # green
    (251, 140, 0),     # orange
    (149, 117, 205),   # purple
    (0, 172, 193),     # teal
    (230, 74, 90),     # red
    (240, 180, 0),     # amber
    (124, 179, 66),    # light green
]


class CalendarCard(WallpaperCard):
    title = 'calendar'
    interval = 60.0          # redraw each minute (relative times drift)

    def __init__(self, sources=(), slots=6, reload_every=600):
        # Keep sources in config order so each keeps a stable colour.
        self.sources = list(sources)
        self.file_globs = [s for s in self.sources if not str(s).startswith(('http://', 'https://'))]
        self.urls = [s for s in self.sources if str(s).startswith(('http://', 'https://'))]
        self.slots = slots
        self.reload_every = reload_every
        self._events = []
        self._parsed = 0.0
        self._error = None
        self._url_text = {}          # url -> last good ics text
        self._fetched = 0.0
        self._fetching = False
        self._lock = threading.Lock()

    # -- network (worker thread) -------------------------------------------
    def _fetch_urls(self):
        try:
            for url in self.urls:
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'duo87-deck'})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        text = r.read().decode('utf-8', 'replace')
                    with self._lock:
                        self._url_text[url] = text
                except Exception:
                    pass                 # keep the last good copy
            self._fetched = time.time()
        finally:
            self._fetching = False

    def _maybe_fetch(self):
        if not self.urls or self._fetching:
            return
        if self._url_text and time.time() - self._fetched < self.reload_every:
            return
        self._fetching = True
        threading.Thread(target=self._fetch_urls, daemon=True).start()

    def prefetch(self, timeout=5.0):
        """Block briefly so the first render already lists events (URL feeds)."""
        if not self.urls:
            return
        self._maybe_fetch()
        end = time.time() + timeout
        while not self._url_text and self._fetching and time.time() < end:
            time.sleep(0.1)
        self._reparse()

    # -- parsing -----------------------------------------------------------
    def _reparse(self):
        events, errors, sources_seen = [], [], False
        with self._lock:
            url_text = dict(self._url_text)
        # Parse each configured source, tagging events with its index so each
        # calendar keeps its own colour (CALENDAR_COLOURS[idx]).
        for idx, src in enumerate(self.sources):
            if str(src).startswith(('http://', 'https://')):
                text = url_text.get(src)
                if text:
                    sources_seen = True
                    events.extend((s, e, summ, idx) for s, e, summ in parse_ics(text))
            else:
                for p in sorted(glob.glob(os.path.expanduser(src))):
                    sources_seen = True
                    try:
                        with open(p, encoding='utf-8', errors='replace') as f:
                            events.extend((s, e, summ, idx) for s, e, summ in parse_ics(f.read()))
                    except OSError as ex:
                        errors.append(ex.strerror or 'read error')
        texts = list(url_text.values())

        if not (self.file_globs or self.urls):
            self._error = 'not configured'
        elif self.urls and not texts and not sources_seen:
            self._error = 'fetching…'
        elif errors and not events:
            self._error = errors[0]
        else:
            self._error = None

        now = datetime.datetime.now().astimezone()
        horizon = now - datetime.timedelta(hours=1)
        self._events = sorted((e for e in events if e[0] and e[0] >= horizon),
                              key=lambda e: e[0])
        self._parsed = time.time()

    @staticmethod
    def _day_label(date, today):
        delta = (date - today).days
        if delta == 0:
            return 'Today'
        if delta == 1:
            return 'Tomorrow'
        if 0 < delta < 7:
            return date.strftime('%A')          # Monday, Tuesday, ...
        return date.strftime('%a %d %b')        # Sat 13 Sep

    @staticmethod
    def _time_label(start):
        return 'all day' if (start.hour == 0 and start.minute == 0) else start.strftime('%H:%M')

    def _fit(self, d, text, font, max_w):
        if d.textlength(text, font=font) <= max_w:
            return text
        while text and d.textlength(text + '…', font=font) > max_w:
            text = text[:-1]
        return text.rstrip() + '…'

    def render(self, deck):
        self._maybe_fetch()
        if time.time() - self._parsed > 20:
            self._reparse()
        im = render.card_canvas()
        d = ImageDraw.Draw(im)
        sx0, sy0, sx1, sy1 = render.card_safe()
        right = sx1 - 6

        if not self._events:
            d.text((16, 30), 'Upcoming', font=render.font(24, True),
                   fill=render.ACCENT, anchor='lm')
            msg = self._error or 'nothing scheduled'
            d.text((16, 90), msg, font=render.font(18),
                   fill=render.WARN if self._error and self._error != 'fetching…' else render.MUTED)
            return im

        now = datetime.datetime.now().astimezone()
        today = now.date()
        y = 24
        cur_day = None
        # Larger event names grouped under day headers; time is a small prefix,
        # and a colour bar on the left marks which calendar the event is from.
        name_font = render.font(20, True)
        time_font = render.font(15, True)
        day_font = render.font(15, True)
        bar_x, time_x = 12, 26
        time_col = 60
        row_h, gap = 36, 16

        for start, _end, summary, src_idx in self._events[:self.slots]:
            if y > sy1 - row_h:
                break
            if start.date() != cur_day:
                cur_day = start.date()
                if y > 24:
                    y += gap          # gap before a new day group
                if y > sy1 - row_h:
                    break
                d.text((16, y), self._day_label(cur_day, today).upper(),
                       font=day_font, fill=render.MUTED, anchor='lm')
                d.line([16, y + 20, right, y + 20], fill=(46, 48, 58), width=1)
                y += 32

            soon = 0 <= (start - now).total_seconds() < 900
            colour = CALENDAR_COLOURS[src_idx % len(CALENDAR_COLOURS)]
            d.rectangle([bar_x, y + 1, bar_x + 4, y + 22], fill=colour)
            name_col_x = time_x + time_col
            d.text((time_x, y + 3), self._time_label(start), font=time_font,
                   fill=render.WARN if soon else render.MUTED, anchor='lm')
            name = self._fit(d, summary, name_font, right - name_col_x)
            d.text((name_col_x, y + 1), name, font=name_font,
                   fill=render.WARN if soon else render.FG, anchor='lm')
            y += row_h
        return im
