# DUO87 project — handover notes

Goal: a Linux application, designed by the user to their own needs, that drives
the programmable display pad of the Womier DUO87 keyboard. The Windows vendor
app (`DUO87_Play_Deck`, a rebranded MiraBox Stream Dock app) is not to be
cloned; only its device protocol was needed, and that is now known.

## State of play (as of 2026-09-11)

Reverse engineering is done, and **`duo87.py` now runs on Linux against the
real pad**: firmware read, start-up hand-shake, all twelve key images upright
and correctly numbered, all twelve key codes, and brightness are all verified
on this machine (Manjaro, kernel 6.12.103). Read `PROTOCOL.md` first; it is the
source of truth. Short version:

- The DUO87 is two USB devices. The display pad is `0600:3001`
  ("HOTSPOTEKUSB"), vendor HID interface with usage page `0xFFA0`. The
  keyboard is `342d:e542` and has a QMK/VIA raw HID interface (`0xFF60`),
  so keymaps are a VIA/Vial job, not ours.
- Host to pad: 1024-byte output reports, `"CRT\0\0"` + command.
  `BAT` (80x80 JPEG per key, rotated 180 degrees, key 1..12, followed by
  1024-byte chunks), `STP` refresh, `CLE` clear, `LIG` brightness,
  `wake` / `sleep` / `DIS`, `CONNECT` heartbeat every 10 s, `QUCMD` config.
- Pad to host: 512-byte reports `"ACK\0\0OK\0\0\0"` + key code at byte 9
  (equals tile number 1..12) + state at byte 10 (1 down, 0 up). The pad has
  no other buttons. Code `0xFF` means the touch landed off-tile (in a gap or
  the margin) -- ignore it, or use it as "touched, but not a button".
- Physical grid is 3 columns x 4 rows, key 1 top-left, key 12 bottom-right.
- **The panel is one continuous screen and the key window is ~112x112, not
  80x80.** An 80x80 image under-fills it by about a third, and that unlit margin
  is most of what looks like a gap between tiles. Draw at 112. Only keys 1..12
  exist; the margin along the bottom and right of the panel is unreachable.
  PROTOCOL.md 2.7. **Never send a very large JPEG** (420x620 locked the USB
  endpoint until a replug).
- **The pad recognises swipes itself** and reports a direction as an ASCII digit
  (`'1'`..`'4'` = down/up/right/left) after a report with state `0x02`.
  Left/right are pure input and are what the app uses for paging; up/down make
  the pad switch to its own built-in page and are suppressed. See PROTOCOL.md
  2.6 -- this is the single most important section for the app layer.
- **The pad ignores image uploads until it gets one `DIS`.** Writes succeed and
  nothing appears on screen. Bisected: `DIS` alone is necessary and sufficient;
  the rest of the vendor hand-shake is ceremony. `Duo87.enable()` sends it
  without clearing the screen; `Duo87.startup()` is the full vendor sequence and
  blanks it. Needed once per plug-in, not per process. This was the one real
  surprise of the Linux bring-up.
- Firmware version via HID GET_REPORT on input report 0
  (`V3.X106_3_5.02.012`).

## Files

- `PROTOCOL.md` — full protocol, each item marked verified or inferred.
- `duo87.py` — Linux driver + CLI, stdlib only, Pillow optional. Class
  `Duo87` (find device, send commands, upload images, parse events) and CLI
  verbs `info`, `init`, `listen`, `demo`, `image`, `brightness`, `clear`,
  `refresh`, `wake`, `sleep`, `heartbeat`, `disconnect`, `raw`, `config`.
  **Exercised on Linux and working.**
- `99-duo87.rules` — udev rule; install to `/etc/udev/rules.d/`, then
  `sudo udevadm control --reload && sudo udevadm trigger --action=add --subsystem-match=hidraw`.
  A plain `trigger` (change event) will not apply `uaccess`. On this box
  `uaccess` did not produce an ACL at all, so the rule also sets
  `GROUP="wheel"` — adjust that group for other machines.
- `captures/` — vendor app HID traffic (Frida hook), a reassembled key
  image, the key-press log, and the hook scripts for future captures on
  Windows.
- `deck/` — the application layer; see the section below.
- `config.example.toml` — documented configuration; `config.toml` in this
  folder is a working copy using the apps found on this machine.
- `captures/WINDOWS_CAPTURE.md` — **the plan for the next Windows session**,
  rewritten 2026-09-11 around panel geometry (top priority), `LOG`, device
  replies, and the keyboard-side strings.
- `captures/hook.js` — **v2**. The original filtered by transfer size and
  captured *no device-to-host traffic at all*, which is why `.DEVCFG` is still
  unknown. v2 tracks the HID handle from `CreateFile` and logs every read and
  write on it, plus the `HidD_*` helpers. Verify it by pressing a pad key and
  checking `R` lines appear before trusting a session.

## The application layer (`deck/`)

Started 2026-09-11 and running on the hardware. Stdlib + Pillow; `psutil`,
`playerctl` and `ydotool` are optional and each degrades to a visible "not
available" tile rather than a silent no-op.

```
deck/core.py     Page base class + Deck (device ownership, event loop, paging)
deck/render.py   112x112 tile builders, the palette, panel geometry
                 (SIZE/GAP/COL_SHIFT), and tile styles: text_tile, icon_tile,
                 button_tile (inset rounded button w/ icon or glyph), press_effect.
deck/osapi.py    every platform-specific call: launch, media, volume, keystrokes,
                 system metrics. Linux is tested; Windows/macOS branches are
                 written from documentation and marked untested.
                 Media is MPRIS over D-Bus via `busctl` (systemd), which needs
                 no extra package and follows every player including browser
                 tabs. It also yields cover art and position, so the media page
                 shows album art across a 2x2 tile block with a progress bar.
deck/pages/      edit-surface tiles: launcher, media, sysmon, zoom. Buttons
                 use icon-theme icons via deck.icons with text fallback.
                 MULTIPLE launcher pages: any page name whose [<name>]
                 section sets type="launcher" (build_pages generalised).
deck/cards/      wallpaper-surface full-panel cards: clock, weather, calendar,
                 nowplaying (WallpaperCard; weather=Open-Meteo no key,
                 calendar=iCal files OR URLs fetched on a thread, per-source
                 colour bars; both prefetch at start and self-heal on entry)
deck/icons.py    freedesktop icon-theme lookup + SVG/PNG rasterize (GdkPixbuf
                 via gi; no Qt, no extra package). Launcher tiles use it.
deck/config.py   load/validate/save config.toml (+ a small TOML writer)
deck/daemon.py   tray daemon: holds the device, runs the deck on a worker
                 thread, Qt tray icon (Settings/Reload/Quit). `python3 -m deck.daemon`
deck/settings_dialog.py   Qt settings UI (brightness, pages, cards, weather,
                 calendar URLs, launchers); saves via config.py and reloads
tools/gapcal.py  calibrates the tile-to-panel geometry against the real pad
tools/margin.py  lights all twelve windows white to measure the panel margin
examples/mockup.py   single-process two-surface demo (5 pages + 3 cards)
deck/app.py      config loading + headless entry point (`python3 -m deck`)
config.example.toml   documented; copy to config.toml or ~/.config/duo87/
duo87-deck.desktop    autostart entry; copy to ~/.config/autostart/
```

Run it: `python3 -m deck.daemon` for the real always-on app (tray icon, holds
the device, edit settings + reload from the menu). `python3 -m deck` is the
headless runner for testing (`-v` logs events, `--list` shows what a config
builds, `--once` draws page 1 and exits). `python3 -m deck.daemon --config-only`
opens just the settings dialog.

The daemon needs PyQt6 (system package) and a system tray. On a bare Wayland
compositor like niri the tray needs a StatusNotifierItem host (e.g. waybar with
the tray module); without one the deck still runs but the menu is unreachable --
use `--config-only` or edit `~/.config/duo87/config.toml` directly.

Calendars are added by URL (Google "secret address in iCal format") in the
Calendar tab; those URLs are private and saved only to the user's config file,
never the repo.

Two design points that are easy to get wrong:

- **Tile actions fire on RELEASE, not PRESS, and a DRAG cancels them.** A swipe
  begins as a press on whatever tile the finger landed on, so firing on press
  means every swipe across a full launcher grid starts an application. Verified:
  6 swipes -> 0 actions, 5 taps -> 5 actions.
- **Repaint uploads only tiles whose JPEG changed.** A full 12-tile repaint is
  only ~15 ms, but the once-a-second pages would otherwise re-send everything.
- **`CanvasPage` draws one image across the whole pad** instead of twelve tiles,
  for things that are pictures rather than buttons (`nowplaying`, `sysmon`). It
  splits the canvas using the calibrated geometry. Two layers: `draw()` is
  bezel-corrected (right for art and graphs) and `draw_overlay()` is not
  (right for text -- a corrected glyph loses the pixels that fall in a gap, so a
  title reads "Dil Hi T Hai Na"). Use `row_bands()` / `col_bands()` to keep text
  off the seams.

### Two-surface model (session 3, 2026-09-11) — the app's core shape

The pad has two display surfaces and the Deck now drives both (`deck/core.py`):

- **Edit surface** = 12 touchable tiles (`MOD '2'` + `BAT`). Fast (~15 ms),
  interactive. `Page` / `CanvasPage`. Horizontal swipe pages between pages
  (any number of pages; **>4 is fine**). More than four pages verified.
- **Wallpaper surface** = full-panel 320x480 cards (`MOD '1'` + `LOG`) in the
  pad's own screensaver carousel. `WallpaperCard`. Seamless, but **read-only and
  host cannot pick which card shows**: the pad shows stock (slot 0, immutable)
  and the user swipes to cycle stock->1->2->3. Cards live in slots 1..3, so at
  most **three** cards. Each `LOG` write ~1.25 s, so cards are for slow content
  (weather, calendar, album art), refreshed on entry to wallpaper, never in a
  background timer.

Navigation, all verified on hardware:
- Horizontal **left** swipe (right-to-left finger motion) = next page; **right**
  = previous. This matches the pad's own carousel direction, which is fixed in
  firmware, and the usual "drag content left = advance" convention.
- Vertical **down** = drop from edit into the wallpaper carousel (the pad
  auto-switches to its screensaver page); vertical **up** = climb back to tiles.
- The pad reports vertical swipe codes `'1'`/`'2'` as *mode/carousel* events, not
  reliable directions (PROTOCOL.md 2.9) -- the Deck treats down='1'/up='2'.

Gotchas learned the hard way:
- **A `LOG` write flips the display to screensaver mode.** So `start()` uploads
  cards first, then `set_mode(KEYS)` + repaint; and cards are refreshed only when
  about to be shown (on `enter_wallpaper`), never behind the tiles.
- **Never `LOG` while trying to stay on the tile surface** -- it resets the pad
  (re-enumerates to a new hidraw node), and there is no way to paint the
  bottom/right panel margin behind the tiles. So instead the Deck **masks**
  `render.CARD_MARGIN_RIGHT/BOTTOM` of each card to `render.BG` before upload, so
  nothing of a card lingers behind the tiles when you swipe back to edit. Those
  margins are a generous guess (40/48) and make cards look small; **measure the
  exact uncovered strip once (all 12 tiles white) and tighten them.**
- **Bursts of `LOG`/`MOD` and overlapping device opens destabilise the pad**
  (the "stock -> dark -> stock, tiles gone" state seen twice this session, both
  after rapid repeated background scripts contending for the device). The real
  app must hold the device in **one** long-lived process -- which the tray daemon
  will. `Duo87.startup()` (full handshake) recovers a wedged pad.

Try it: `python3 examples/mockup.py` (5 button pages + 3 cards), ONE process.

## What to do next (Linux)

Bring-up is done (2026-09-11). The udev rule is installed on this machine and
the following were all confirmed by eye and on the wire:

- `python3 duo87.py info` -> `/dev/hidraw0`, `V3.X106_3_5.02.012`.
- `python3 duo87.py demo` -> upright "1".."12", 1 top-left, 12 bottom-right.
  `KEY_ROTATION = 180` is correct as written.
- All twelve tiles produce their own key code on press and release; no `0xFF`
  strays appeared in this session.
- `brightness` visibly dims and brightens the panel. `0` is a floor, not off.

So the remaining work is **the user's application layer on top of `Duo87`**.
Nothing in the driver is known to be missing for that. Keep the heartbeat
running while the app is open (see the open question below), and call
`Duo87.enable()` once at start-up before drawing (or `startup()` if you also
want the screen cleared).

## Windows session 2 (2026-09-11 evening) — done, see PROTOCOL.md 2.8

Every item in `captures/WINDOWS_CAPTURE.md` was run with hook v2.1 (handle
tracking + `DeviceIoControl`), driving the vendor app's Qt UI with pywinauto
(`Desktop(backend='uia')`, coordinates from screenshots). Results:

- **Panel is 320x480** (stated by the app's screensaver dialog; confirmed by
  a full-panel upload seen by eye).
- **`LOG` = full-screen image**: `CRT\0\0LOG` + size u32 BE + slot (0..3),
  JPEG chunks, then the pad answers `ACK OK 00 00` (~3.5 s) and the app sends
  `STP`. Lights the whole panel including the bottom/right margin. Only used
  by the app in screensaver mode; **untested from Linux** — the obvious next
  experiment for `deck/` (a true full-panel canvas without seams), with the
  wedge warning in mind (44 KB / 44 chunks was fine).
- **`MOD '1'`** = screensaver mode, **`MOD '2'`** = keystroke mode.
- **`sleep`** is what the app's screen-off timer sends (host-side timer).
- Vertical swipes: `'1'` = pad went to its screensaver page, `'2'` = it came
  back — **mode transitions, not directions** (verified with ten same-direction
  swipes). The app ignores `'1'` and answers `'2'` with `MOD '2'` + repaint.
  Horizontal `'3'`/`'4'` are real directions; the app pages on them.
- Screen-off, Rotate, paging, key actions: all host-side, nothing new on the
  wire. No brightness control in the app. **No keyboard-side traffic ever**,
  and no `.DEVCFG` reply exists — both closed.
- Raw log `captures/windows_session2_full.log`, index
  `captures/WINDOWS_SESSION2_INDEX.md`, helper `captures/newcmds.sh`.

## Open questions worth settling when convenient

- ~~Does the pad care if `CONNECT` stops?~~ **Answered 2026-09-11: no.** After
  5 minutes of complete silence the pad still accepted an image upload and
  still reported key presses. Send it anyway if you like (it is cheap and
  matches the vendor app), but nothing is known to depend on it.
- ~~Panel resolution / full-screen image?~~ **Answered (Windows session 2 +
  Linux session 3): panel is 320x480; `LOG` lights all of it** including the
  bottom/right margin `BAT` cannot reach. It is a screensaver carousel, ~1.25 s
  per slot, host cannot pick the shown slot; slot 0 is the immutable stock image.
  See PROTOCOL.md 2.8/2.9 and the two-surface model above.
- ~~Exact uncovered margin behind the tiles?~~ **Measured 2026-09-11:**
  `render.CARD_MARGIN_RIGHT = 16`, `CARD_MARGIN_BOTTOM = 36`, tuned live against
  the tile outline in `examples/mockup.py`. Cards now line up with the tiles.
- **Windows-only, minor:** can the boot/stock wallpaper (slot 0) be changed at
  all? The vendor app's Edit-Screensaver preview seemed to, but no plain host
  command reproduced it. Not needed for the app.
- `sleep` is **done**: it blanks the screen, touching the panel wakes it with
  its content intact (nothing needs redrawing), and key events keep flowing
  while it is dark.
- Strings `SETLB`, `LBLIG`, `RGBS`, `LAYER`, `DELED`, `INTVID`, `WEB` in the
  vendor binary look like keyboard-side settings relayed through the pad.
  Procedure is written up in `captures/WINDOWS_CAPTURE.md` — attach to the
  running app (do not spawn it), one control per log file, two distinct values
  each.
- ~~What produces the stray key code `0xFF`?~~ **Answered 2026-09-11: a touch
  that hit no tile** -- the gaps between tiles or the margin round the grid.
  9 of 11 deliberate gap taps reported `0xFF`; 22 tile-centre presses reported
  none. Ignore codes outside 1..12, or use `0xFF` as "touched, but not a
  button".

## Working conventions

- Verify against the device before writing anything down as fact; keep the
  verified / inferred labelling in `PROTOCOL.md` honest.
- Don't add dependencies to `duo87.py` beyond optional Pillow; the user
  wants to design the application layer themselves.
- The keyboard interface (`342d:e542`) is out of scope unless the user asks.
