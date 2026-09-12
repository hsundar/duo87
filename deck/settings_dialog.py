"""The Qt settings dialog for the deck.

Edits the config dict the daemon loaded and, on OK, returns a new dict the daemon
saves and reloads. Tabs: General, Pages, Cards, Weather, Calendar.

Pages can be several launcher pages plus the builtin media/system/zoom pages, in
any order. Each launcher page has its own button table (label/command/uri/icon).
Calendar URLs may be private (a Google "secret address"); they are stored only
in the user's config.
"""
from PyQt6 import QtCore, QtGui, QtWidgets

from . import config as cfgmod
from . import app as appmod
from . import icons

_ROLE = QtCore.Qt.ItemDataRole.UserRole
BUILTIN_PAGES = ['media', 'system', 'zoom', 'audio', 'calendar', 'nowplaying']


class IconPickerDialog(QtWidgets.QDialog):
    """Browse the icon theme and pick an icon name (with live previews)."""

    def __init__(self, current='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Pick an icon')
        self.resize(520, 460)
        self.selected = current
        self._names = icons.list_icon_names()

        self.search = QtWidgets.QLineEdit(current)
        self.search.setPlaceholderText('type to filter (e.g. firefox, terminal, mail)…')
        self.search.textChanged.connect(self._refilter)
        self.grid = QtWidgets.QListWidget()
        self.grid.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.grid.setIconSize(QtCore.QSize(48, 48))
        self.grid.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.grid.setGridSize(QtCore.QSize(96, 76))
        self.grid.itemDoubleClicked.connect(lambda _it: self.accept())

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.grid)
        lay.addWidget(bb)
        self._refilter(current)

    def _refilter(self, text):
        text = (text or '').strip().lower()
        self.grid.clear()
        if not text:
            return
        shown = 0
        for name in self._names:
            if text in name.lower():
                path = icons.find_icon(name)
                it = QtWidgets.QListWidgetItem(name)
                if path:
                    it.setIcon(QtGui.QIcon(path))
                self.grid.addItem(it)
                shown += 1
                if shown >= 300:            # cap for responsiveness
                    break

    def accept(self):
        it = self.grid.currentItem()
        if it is not None:
            self.selected = it.text()
        else:
            self.selected = self.search.text().strip()
        super().accept()


class ButtonsDialog(QtWidgets.QDialog):
    """Edit one launcher page's buttons: label + command/uri + icon."""

    def __init__(self, name, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Buttons — %s' % name)
        self.resize(520, 380)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Label', 'Command', 'URI', 'Icon'])
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        for it in items:
            self._add(it.get('label', ''), it.get('command', ''),
                      it.get('uri', ''), it.get('icon', ''))

        addb = QtWidgets.QPushButton('Add')
        rmb = QtWidgets.QPushButton('Remove')
        pickb = QtWidgets.QPushButton('Pick icon…')
        addb.clicked.connect(lambda: self._add('', '', '', ''))
        rmb.clicked.connect(self._remove)
        pickb.clicked.connect(self._pick_icon)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(addb); row.addWidget(rmb); row.addWidget(pickb); row.addStretch(1)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel('Up to 12 buttons. Icon = theme name '
                                       '(firefox, org.gnome.Nautilus) or a path; '
                                       'blank guesses from the command. '
                                       'Select a row, then "Pick icon…".'))
        lay.addWidget(self.table)
        lay.addLayout(row)
        lay.addWidget(bb)

    def _add(self, label, command, uri, icon):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate((label, command, uri, icon)):
            self.table.setItem(r, c, QtWidgets.QTableWidgetItem(v))

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def _pick_icon(self):
        r = self.table.currentRow()
        if r < 0:
            QtWidgets.QMessageBox.information(self, 'Pick icon', 'Select a button row first.')
            return
        cur = self.table.item(r, 3).text() if self.table.item(r, 3) else ''
        dlg = IconPickerDialog(cur, self)
        if dlg.exec() and dlg.selected:
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(dlg.selected))

    def items(self):
        out = []
        for r in range(self.table.rowCount()):
            def cell(c):
                it = self.table.item(r, c)
                return it.text().strip() if it else ''
            label, command, uri, icon = cell(0), cell(1), cell(2), cell(3)
            if not label:
                continue
            entry = {'label': label}
            if command:
                entry['command'] = command
            elif uri:
                entry['uri'] = uri
            if icon:
                entry['icon'] = icon
            out.append(entry)
        return out[:12]


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle('DUO87 deck — settings')
        self.resize(480, 560)
        self._cfg = cfg or cfgmod.default_config()
        # Working copy of each launcher page's items, keyed by page name.
        self._launcher_items = {}
        for name in self._cfg.get('pages', []):
            sec = self._cfg.get(name, {})
            if isinstance(sec, dict) and (sec.get('type') == 'launcher'
                                          or name == 'launcher'):
                self._launcher_items[name] = list(sec.get('items', []))

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._general_tab(), 'General')
        tabs.addTab(self._pages_tab(), 'Pages')
        tabs.addTab(self._cards_tab(), 'Cards')
        tabs.addTab(self._weather_tab(), 'Weather')
        tabs.addTab(self._calendar_tab(), 'Calendar')

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)

    # -- General -----------------------------------------------------------
    def _general_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        self.brightness = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setValue(int(self._cfg.get('brightness', 80)))
        lbl = QtWidgets.QLabel(str(self.brightness.value()))
        self.brightness.valueChanged.connect(lambda v: lbl.setText(str(v)))
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.brightness); row.addWidget(lbl)
        form.addRow('Brightness', row)
        form.addRow(QtWidgets.QLabel('0 is a floor, not off — the panel stays faintly lit.'))
        return w

    # -- Pages -------------------------------------------------------------
    def _pages_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel('Edit pages (horizontal swipe). Drag to reorder. '
                                       'Double-click a launcher to edit its buttons.'))
        self.pages_list = QtWidgets.QListWidget()
        self.pages_list.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        for name in self._cfg.get('pages', ['launcher', 'media', 'system', 'zoom']):
            sec = self._cfg.get(name, {})
            ptype = (sec.get('type') if isinstance(sec, dict) else None) \
                or (name if name in appmod.BUILTIN_PAGE_TYPES else 'launcher')
            self._add_page_row(name, ptype)
        self.pages_list.itemDoubleClicked.connect(self._edit_page_buttons)
        lay.addWidget(self.pages_list)

        row = QtWidgets.QHBoxLayout()
        add_launcher = QtWidgets.QPushButton('Add launcher…')
        add_builtin = QtWidgets.QPushButton('Add builtin…')
        edit_btn = QtWidgets.QPushButton('Edit buttons…')
        rm = QtWidgets.QPushButton('Remove')
        add_launcher.clicked.connect(self._add_launcher_page)
        add_builtin.clicked.connect(self._add_builtin_page)
        edit_btn.clicked.connect(lambda: self._edit_page_buttons(self.pages_list.currentItem()))
        rm.clicked.connect(self._remove_page)
        for b in (add_launcher, add_builtin, edit_btn, rm):
            row.addWidget(b)
        lay.addLayout(row)
        return w

    def _add_page_row(self, name, ptype):
        label = '%s   (%s)' % (name, ptype)
        item = QtWidgets.QListWidgetItem(label)
        item.setData(_ROLE, {'name': name, 'type': ptype})
        self.pages_list.addItem(item)

    def _add_launcher_page(self):
        name, ok = QtWidgets.QInputDialog.getText(self, 'Add launcher page', 'Page name:')
        name = name.strip()
        if not ok or not name:
            return
        if any(self.pages_list.item(i).data(_ROLE)['name'] == name
               for i in range(self.pages_list.count())):
            QtWidgets.QMessageBox.warning(self, 'Name in use', 'A page named %r exists.' % name)
            return
        self._launcher_items[name] = []
        self._add_page_row(name, 'launcher')

    def _add_builtin_page(self):
        existing = {self.pages_list.item(i).data(_ROLE)['type']
                    for i in range(self.pages_list.count())}
        choices = [t for t in BUILTIN_PAGES if t not in existing]
        if not choices:
            QtWidgets.QMessageBox.information(self, 'All added', 'All builtin pages are present.')
            return
        t, ok = QtWidgets.QInputDialog.getItem(self, 'Add builtin page', 'Type:',
                                               choices, editable=False)
        if ok and t:
            self._add_page_row(t, t)

    def _remove_page(self):
        r = self.pages_list.currentRow()
        if r >= 0:
            self.pages_list.takeItem(r)

    def _edit_page_buttons(self, item):
        if item is None:
            return
        data = item.data(_ROLE)
        if data['type'] != 'launcher':
            QtWidgets.QMessageBox.information(self, 'Not a launcher',
                                             'Only launcher pages have buttons.')
            return
        name = data['name']
        dlg = ButtonsDialog(name, self._launcher_items.get(name, []), self)
        if dlg.exec():
            self._launcher_items[name] = dlg.items()

    # -- Cards -------------------------------------------------------------
    def _cards_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel('Wallpaper cards (swipe down). Check to include, '
                                       'drag to reorder; at most %d used.' % cfgmod.MAX_CARDS))
        self.cards_list = QtWidgets.QListWidget()
        self.cards_list.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        order = list(self._cfg.get('cards', []))
        for name in order + [c for c in cfgmod.CARD_TYPES if c not in order]:
            it = QtWidgets.QListWidgetItem(name)
            it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.CheckState.Checked if name in order
                             else QtCore.Qt.CheckState.Unchecked)
            self.cards_list.addItem(it)
        lay.addWidget(self.cards_list)
        return w

    # -- Weather -----------------------------------------------------------
    def _weather_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        wc = self._cfg.get('weather', {})
        self.weather_place = QtWidgets.QLineEdit(str(wc.get('place') or ''))
        self.weather_place.setPlaceholderText('e.g. Boston, MA (or set lat/lon)')
        self.weather_units = QtWidgets.QComboBox()
        self.weather_units.addItems(['metric', 'imperial'])
        self.weather_units.setCurrentText(wc.get('units', 'metric'))
        self.weather_lat = QtWidgets.QLineEdit('' if wc.get('latitude') is None else str(wc['latitude']))
        self.weather_lon = QtWidgets.QLineEdit('' if wc.get('longitude') is None else str(wc['longitude']))
        form.addRow('Place', self.weather_place)
        form.addRow('Units', self.weather_units)
        form.addRow('Latitude', self.weather_lat)
        form.addRow('Longitude', self.weather_lon)
        form.addRow(QtWidgets.QLabel('Open-Meteo (no account). Place is geocoded; '
                                     'lat/lon override it.'))
        return w

    # -- Calendar ----------------------------------------------------------
    def _calendar_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        cc = self._cfg.get('calendar', {})
        lay.addWidget(QtWidgets.QLabel('Calendar sources: iCal URLs (Google "secret address '
                                       'in iCal format") or local .ics paths.'))
        self.cal_list = QtWidgets.QListWidget()
        for s in cc.get('sources', []):
            self.cal_list.addItem(str(s))
        lay.addWidget(self.cal_list)
        row = QtWidgets.QHBoxLayout()
        self.cal_input = QtWidgets.QLineEdit()
        self.cal_input.setPlaceholderText('https://calendar.google.com/…/basic.ics  or  ~/cal/*.ics')
        add = QtWidgets.QPushButton('Add'); rm = QtWidgets.QPushButton('Remove')
        add.clicked.connect(self._cal_add); rm.clicked.connect(self._cal_remove)
        self.cal_input.returnPressed.connect(self._cal_add)
        row.addWidget(self.cal_input); row.addWidget(add); row.addWidget(rm)
        lay.addLayout(row)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(QtWidgets.QLabel('Events shown'))
        self.cal_slots = QtWidgets.QSpinBox(); self.cal_slots.setRange(1, 20)
        self.cal_slots.setValue(int(cc.get('slots', 6)))
        srow.addWidget(self.cal_slots); srow.addStretch(1)
        lay.addLayout(srow)
        lay.addWidget(QtWidgets.QLabel('Each source gets its own colour. Private URLs are '
                                       'saved only in your config file.'))
        return w

    def _cal_add(self):
        s = self.cal_input.text().strip()
        if s:
            self.cal_list.addItem(s); self.cal_input.clear()

    def _cal_remove(self):
        for it in self.cal_list.selectedItems():
            self.cal_list.takeItem(self.cal_list.row(it))

    # -- result ------------------------------------------------------------
    def result_config(self):
        cfg = dict(self._cfg)
        cfg['brightness'] = self.brightness.value()

        pages = []
        for i in range(self.pages_list.count()):
            data = self.pages_list.item(i).data(_ROLE)
            name, ptype = data['name'], data['type']
            pages.append(name)
            if ptype == 'launcher':
                section = dict(cfg.get(name, {})) if isinstance(cfg.get(name), dict) else {}
                section['type'] = 'launcher'
                section['items'] = self._launcher_items.get(name, [])
                cfg[name] = section
            elif name not in cfg:
                cfg[name] = {'type': ptype} if name != ptype else {}
        cfg['pages'] = pages

        cards = []
        for i in range(self.cards_list.count()):
            it = self.cards_list.item(i)
            if it.checkState() == QtCore.Qt.CheckState.Checked:
                cards.append(it.text())
        cfg['cards'] = cards[:cfgmod.MAX_CARDS]

        weather = {'units': self.weather_units.currentText()}
        if self.weather_place.text().strip():
            weather['place'] = self.weather_place.text().strip()
        for key, field in (('latitude', self.weather_lat), ('longitude', self.weather_lon)):
            t = field.text().strip()
            if t:
                try:
                    weather[key] = float(t)
                except ValueError:
                    pass
        cfg['weather'] = weather

        cfg['calendar'] = {
            'slots': self.cal_slots.value(),
            'sources': [self.cal_list.item(i).text() for i in range(self.cal_list.count())],
        }
        return cfg
