# DUO87 deck

A Linux driver and application for the programmable display pad of the **Womier
DUO87** keyboard (the `0600:3001` "HOTSPOTEKUSB" display device).

- `duo87.py` — stdlib driver + CLI for the pad (info, images, brightness, key
  events, screensaver/LOG, …). No dependencies; Pillow optional.
- `deck/` — the application: a tray daemon that drives the pad with **pages**
  (touchable tiles — launchers, media, system monitor, Zoom controls) and
  **cards** (full-panel wallpaper — clock, weather, calendar, now playing).
- `PROTOCOL.md` — the reverse-engineered USB/HID protocol (the source of truth).

The pad is one continuous 320×480 panel exposed as twelve ~112px touch tiles
plus a full-panel "screensaver" image; see `PROTOCOL.md` for the details.

## Requirements

System packages (this is designed around them — a venv/pipx would hide the Qt
and GObject bindings and break the app):

- Python 3.11+, **python-pillow**, **pyqt6**, **python-gobject** (`gi`)
- Optional: `playerctl` is not needed (media uses `busctl`/MPRIS); `ydotool`
  (+ its daemon) for the Zoom keystroke controls; `wpctl`/`pactl` for volume.

On Arch/Manjaro:

```
sudo pacman -S --needed python python-pillow pyqt6 python-gobject ydotool
```

## Install

```
git clone git@github.com:hsundar/duo87.git
cd duo87
./install.sh
```

`install.sh` (no venv, re-runnable after `git pull`) installs:

- `~/.local/bin/duo87-deck` (tray daemon) and `~/.local/bin/duo87` (CLI),
- `~/.config/duo87/config.toml` (seeded from `config.example.toml`),
- autostart via niri `spawn-at-startup` and an XDG `.desktop`.

### 1. Device permissions (udev) — needs sudo, once per machine

```
sudo install -m644 99-duo87.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --action=add --subsystem-match=hidraw
```

The rule gives your user access to the pad's hidraw node. It sets both
`uaccess` and `GROUP="wheel"`; change the group if your desktop user is not in
`wheel`. A plain `udevadm trigger` (a *change* event) will not apply access —
use `--action=add` as above, or replug the pad. Verify with `duo87 info`.

### 2. Zoom controls (optional) — ydotool daemon

The Zoom control buttons synthesize keystrokes, which needs `ydotoold` running:

```
systemctl --user enable --now ydotool.service
```

Your user needs write access to `/dev/uinput` (usually granted automatically via
the login session). Zoom's window must be focused for the keystrokes to land.

### 3. Configure

Edit `~/.config/duo87/config.toml` (see `config.example.toml` for every option),
or use the tray **Settings** dialog. Add calendars by their iCal URL (a Google
"secret address in iCal format") — these live only in your config, never the
repo.

## Run

- `duo87-deck` — the tray app (also starts automatically on login).
- `python3 -m deck` — headless runner for testing (`--list`, `-v`, `--once`).
- `duo87 info | demo | listen | image | brightness | …` — the low-level CLI.

The tray needs a StatusNotifierItem host; on a bare Wayland compositor like niri
that means a bar with a tray module (e.g. waybar). Without one the deck still
runs — use `duo87-deck --config-only` or edit the config file directly.
