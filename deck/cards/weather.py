"""Weather card: current conditions + today's range, full panel.

Uses Open-Meteo (no API key, no account) over stdlib urllib. Needs a location:
pass latitude/longitude, or a place name to geocode once via Open-Meteo's free
geocoder. Fetches on a slow cadence, caches the last good reading, and degrades
to "offline" text rather than failing if the network is down.
"""
import json
import threading
import time
import urllib.parse
import urllib.request

from PIL import ImageDraw

from .. import render
from ..core import WallpaperCard

# WMO weather codes -> (label, simple glyph). The glyph is drawn, not a font
# emoji, so it renders identically everywhere (see _draw_icon).
_WMO = {
    0: ('Clear', 'sun'), 1: ('Mainly clear', 'sun'), 2: ('Partly cloudy', 'cloud'),
    3: ('Overcast', 'cloud'), 45: ('Fog', 'fog'), 48: ('Rime fog', 'fog'),
    51: ('Light drizzle', 'rain'), 53: ('Drizzle', 'rain'), 55: ('Drizzle', 'rain'),
    61: ('Light rain', 'rain'), 63: ('Rain', 'rain'), 65: ('Heavy rain', 'rain'),
    66: ('Freezing rain', 'rain'), 67: ('Freezing rain', 'rain'),
    71: ('Light snow', 'snow'), 73: ('Snow', 'snow'), 75: ('Heavy snow', 'snow'),
    77: ('Snow grains', 'snow'), 80: ('Showers', 'rain'), 81: ('Showers', 'rain'),
    82: ('Heavy showers', 'rain'), 85: ('Snow showers', 'snow'),
    86: ('Snow showers', 'snow'), 95: ('Thunderstorm', 'storm'),
    96: ('Thunderstorm', 'storm'), 99: ('Thunderstorm', 'storm'),
}


class WeatherCard(WallpaperCard):
    title = 'weather'
    interval = 60.0          # redraw each minute; the network fetch is far rarer

    def __init__(self, latitude=None, longitude=None, place=None, units='metric',
                 fetch_every=900):
        self.lat = latitude
        self.lon = longitude
        self.place = place
        self.place_label = place
        self.metric = units != 'imperial'
        self.fetch_every = fetch_every
        self._data = None            # last good reading
        self._fetched = 0.0
        self._status = 'starting'
        self._lock = threading.Lock()
        self._fetching = False

    # -- network (runs on a worker thread so it never blocks the deck) ------
    def _geocode(self):
        if self.lat is not None and self.lon is not None:
            return True
        if not self.place:
            self._status = 'no location'
            return False
        try:
            url = ('https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1'
                   % urllib.parse.quote(self.place))
            with urllib.request.urlopen(url, timeout=6) as r:
                res = json.load(r).get('results') or []
            if not res:
                self._status = 'place not found'
                return False
            self.lat, self.lon = res[0]['latitude'], res[0]['longitude']
            self.place_label = res[0].get('name', self.place)
            return True
        except Exception:
            self._status = 'offline'
            return False

    def _fetch(self):
        try:
            if not self._geocode():
                return
            unit = 'celsius' if self.metric else 'fahrenheit'
            url = ('https://api.open-meteo.com/v1/forecast'
                   '?latitude=%s&longitude=%s'
                   '&current=temperature_2m,weather_code,apparent_temperature'
                   '&daily=temperature_2m_max,temperature_2m_min'
                   '&timezone=auto&temperature_unit=%s' % (self.lat, self.lon, unit))
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.load(r)
            with self._lock:
                self._data = data
                self._fetched = time.time()
                self._status = 'ok'
        except Exception:
            self._status = 'offline'
        finally:
            self._fetching = False

    def _maybe_fetch(self):
        if self._fetching:
            return
        if self._data is not None and time.time() - self._fetched < self.fetch_every:
            return
        self._fetching = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def prefetch(self, timeout=4.0):
        """Block briefly so the first render already shows conditions."""
        self._maybe_fetch()
        end = time.time() + timeout
        while self._data is None and self._fetching and time.time() < end:
            time.sleep(0.1)

    # -- drawing -----------------------------------------------------------
    @staticmethod
    def _draw_icon(d, cx, cy, kind, r=44):
        """A simple weather glyph drawn from primitives (theme-independent)."""
        sun, cloud = (240, 200, 70), (150, 152, 160)
        if kind in ('sun',):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=sun)
            return
        if kind in ('cloud', 'fog'):
            d.ellipse([cx - r, cy - r // 2, cx, cy + r // 2], fill=cloud)
            d.ellipse([cx - r // 3, cy - r, cx + r, cy + r // 2], fill=cloud)
            d.rectangle([cx - r, cy, cx + r, cy + r // 2], fill=cloud)
            return
        # rain / snow / storm: a cloud plus streaks
        d.ellipse([cx - r, cy - r, cx + r // 2, cy], fill=cloud)
        d.rectangle([cx - r, cy - r // 2, cx + r // 2, cy], fill=cloud)
        streak = {'rain': (90, 150, 230), 'snow': (230, 235, 245),
                  'storm': (240, 200, 70)}.get(kind, (90, 150, 230))
        for i in range(-1, 2):
            x = cx + i * 20
            d.line([x, cy + 8, x - 6, cy + 34], fill=streak, width=4)

    def _t(self, v):
        return '--' if v is None else '%d°' % round(v)

    def render(self, deck):
        self._maybe_fetch()
        im = render.card_canvas()
        d = ImageDraw.Draw(im)
        sx0, sy0, sx1, sy1 = render.card_safe()
        cx = sx1 // 2

        d.text((16, 30), self.place_label or 'Weather',
               font=render.font(24, True), fill=render.ACCENT, anchor='lm')

        with self._lock:
            data = self._data
        if not data:
            d.text((cx, 200), self._status, font=render.font(22), fill=render.MUTED, anchor='mm')
            return im

        cur = data.get('current', {})
        daily = data.get('daily', {})
        code = int(cur.get('weather_code', 0))
        label, kind = _WMO.get(code, ('', 'cloud'))
        temp = cur.get('temperature_2m')
        feels = cur.get('apparent_temperature')
        hi = (daily.get('temperature_2m_max') or [None])[0]
        lo = (daily.get('temperature_2m_min') or [None])[0]

        self._draw_icon(d, cx, 150, kind)
        d.text((cx, 250), self._t(temp), font=render.font(96, True), fill=render.FG, anchor='mm')
        d.text((cx, 315), label, font=render.font(24), fill=render.MUTED, anchor='mm')
        if feels is not None:
            d.text((cx, 350), 'feels %s' % self._t(feels),
                   font=render.font(18), fill=render.MUTED, anchor='mm')
        d.text((cx, 400), 'H %s   L %s' % (self._t(hi), self._t(lo)),
               font=render.font(22, True), fill=render.FG, anchor='mm')
        if self._status == 'offline':
            d.text((sx1 - 8, 30), 'offline', font=render.font(14), fill=render.WARN, anchor='rm')
        return im
