"""Tray daemon: hold the pad, run the deck, and edit config from a Qt tray icon.

    python3 -m deck.daemon         run in the tray
    python3 -m deck.daemon --config-only   just open the settings dialog

One long-lived process owns the device (the deck runs on a worker thread), which
is what keeps the pad stable -- overlapping opens and command bursts are what
destabilised it during development. The Qt event loop runs on the main thread;
the tray menu opens the settings dialog and can reload or quit.

Needs PyQt6 (system package). The deck itself has no GUI dependency; this module
is the only part that does.
"""
import sys
import threading

from PyQt6 import QtCore, QtGui, QtWidgets

from . import config as cfgmod
from .app import build_pages, build_cards
from .core import Deck
import duo87

from .settings_dialog import SettingsDialog


class DeckWorker(QtCore.QObject):
    """Runs a Deck on its own thread and can be stopped and rebuilt for reload."""

    status = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._deck = None
        self._thread = None

    def start(self, cfg):
        self.stop()
        try:
            pages = build_pages(cfg)
            cards = build_cards(cfg)
            deck = Deck(pages, cards=cards, brightness=cfg.get('brightness'))
        except duo87.DeviceNotFound as e:
            self.status.emit('device not found')
            return False
        except Exception as e:
            self.status.emit('error: %s' % e)
            return False
        self._deck = deck
        self._thread = threading.Thread(target=self._run, args=(deck,), daemon=True)
        self._thread.start()
        self.status.emit('running: %d pages, %d cards' % (len(pages), len(cards)))
        return True

    def _run(self, deck):
        try:
            deck.run()
        except Exception as e:
            self.status.emit('deck stopped: %s' % e)
        finally:
            try:
                deck.d.close()
            except Exception:
                pass

    def stop(self):
        if self._deck is not None:
            self._deck.stop()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._deck = self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()


class TrayApp:
    def __init__(self, app):
        self.app = app
        self.app.setQuitOnLastWindowClosed(False)
        self.worker = DeckWorker()
        self.worker.status.connect(self._on_status)
        self._status_text = 'starting…'
        self._dialog = None

        # A tray is optional: on a bare Wayland compositor (niri) there may be no
        # StatusNotifierItem host, in which case the deck still runs -- settings
        # are then reachable via `--config-only`. Guard so nothing here crashes.
        self.tray = None
        self._status_action = None
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            try:
                self.tray = QtWidgets.QSystemTrayIcon(self._icon())
                self.tray.setToolTip('DUO87 deck')
                self.tray.setContextMenu(self._menu())
                self.tray.activated.connect(self._on_activated)
                self.tray.show()
            except Exception as e:
                print('tray unavailable: %s' % e, file=sys.stderr)
                self.tray = None
        if self.tray is None:
            print('no system tray; deck is running. Use '
                  '`python3 -m deck.daemon --config-only` to change settings.',
                  file=sys.stderr)

        cfg, _path = cfgmod.load()
        if not cfg:
            cfg = cfgmod.default_config()
        self._cfg = cfg
        self.worker.start(cfg)

    # -- ui ----------------------------------------------------------------
    def _icon(self):
        # A simple 3x4-dot glyph so the tray icon reads as the pad.
        pm = QtGui.QPixmap(64, 64)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setBrush(QtGui.QColor(70, 130, 230))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for r in range(4):
            for c in range(3):
                p.drawRoundedRect(8 + c * 18, 4 + r * 15, 12, 11, 2, 2)
        p.end()
        return QtGui.QIcon(pm)

    def _menu(self):
        m = QtWidgets.QMenu()
        self._status_action = m.addAction('starting…')
        self._status_action.setEnabled(False)
        m.addSeparator()
        m.addAction('Settings…', self.open_settings)
        m.addAction('Reload', self.reload)
        m.addSeparator()
        m.addAction('Quit', self.quit)
        return m

    def _on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    def _on_status(self, text):
        self._status_text = text
        if self._status_action is not None:
            self._status_action.setText(text)
        if self.tray is not None:
            self.tray.setToolTip('DUO87 deck — %s' % text)

    def open_settings(self):
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_(); self._dialog.activateWindow(); return
        self._dialog = SettingsDialog(dict(self._cfg))
        if self._dialog.exec():
            self._cfg = self._dialog.result_config()
            cfgmod.save(self._cfg)
            self.reload()

    def reload(self):
        self._on_status('reloading…')
        # Rebuild on a timer tick so the menu paints first.
        QtCore.QTimer.singleShot(50, lambda: self.worker.start(self._cfg))

    def quit(self):
        self.worker.stop()
        if self.tray is not None:
            self.tray.hide()
        self.app.quit()

    def run(self):
        return self.app.exec()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # A QApplication must exist before any QtWidgets call, including the static
    # QSystemTrayIcon.isSystemTrayAvailable() -- calling it first segfaults.
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    if '--config-only' in argv:
        cfg, _ = cfgmod.load()
        dlg = SettingsDialog(cfg or cfgmod.default_config())
        if dlg.exec():
            path = cfgmod.save(dlg.result_config())
            print('saved', path)
        return 0
    tray = TrayApp(app)
    return tray.run()


if __name__ == '__main__':
    sys.exit(main())
