"""Modas Sport tarzı Ribbon şeridi.

Üst satır: uygulama rozeti + ``Start | Label | Worksheets | Tools | Windows`` sekmeleri + sağda durum alanı (bağlantı hapı,
CCP durumu, rol, Ayarlar, Eşleşmeler — MainWindow ekler). Altında seçili sekmenin düğme grupları; en sağda HER sekmede
görünen **Motor / Acil Durdurma** grubu (Acil Durdurma hiçbir sekmede gizlenmez).

Ribbon yalnızca düğmeleri kurar ve ``buttons[anahtar]`` olarak sunar; davranışı MainWindow bağlar (``mainwin/modas.py``).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QTabBar, QToolButton,
    QVBoxLayout, QWidget,
)

from app import theme
from app.ui.modas.style import MODAS_QSS

TABS = [("Start", "S"), ("Label", "L"), ("Worksheets", "W"), ("Tools", "T"), ("Windows", "I")]


def glyph_icon(char: str, color: str = theme.MODAS_GROUP_LABEL, size: int = 26) -> QIcon:
    """Düğme ikonu: karakteri (Unicode simgesi) ``size`` px kare bir resme çizer (dosya/varlık gerektirmez)."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    font = QFont()
    font.setPixelSize(int(size * 1.5))
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignCenter, char)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def led_icon(color: str, size: int = 30) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QColor(theme.INK_2))
    r = size * 2 // 2 - 8
    p.drawEllipse(pm.rect().center(), r, r)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class _Group(QFrame):
    """Ribbon grubu: üstte düğmeler, altta grup etiketi, sağda ince ayraç."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("modasGroup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 2, 6, 0)
        outer.setSpacing(0)
        self.body = QHBoxLayout()
        self.body.setSpacing(2)
        outer.addLayout(self.body, 1)
        label = QLabel(title)
        label.setObjectName("modasGroupLabel")
        label.setAlignment(Qt.AlignCenter)
        outer.addWidget(label)


class ModasRibbon(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("modasRibbon")
        self.setStyleSheet(MODAS_QSS)
        self.buttons: dict[str, QToolButton] = {}
        self._tab_labels = [t for t, _k in TABS]
        self._tips_on = False

        # ---- sekme satırı
        self.tab_row = QFrame()
        self.tab_row.setObjectName("modasTabRow")
        self.tab_layout = QHBoxLayout(self.tab_row)
        self.tab_layout.setContentsMargins(6, 0, 8, 0)
        self.tab_layout.setSpacing(6)
        badge = QLabel("⚡")
        badge.setObjectName("modasAppBadge")
        badge.setFixedSize(24, 24)
        badge.setAlignment(Qt.AlignCenter)
        self.tab_layout.addWidget(badge)
        self.tabs = QTabBar()
        self.tabs.setObjectName("modasRibbonTabs")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setFocusPolicy(Qt.NoFocus)
        for title, _k in TABS:
            self.tabs.addTab(title)
        self.tab_layout.addWidget(self.tabs)
        self.tab_layout.addStretch(1)
        self.title_label = QLabel("ECU CAN Arayüzü")
        self.title_label.setObjectName("modasTitle")
        self.tab_layout.addWidget(self.title_label)

        # ---- gövde: sekme sayfaları + sabit Motor grubu
        self.pages = QStackedWidget()
        self.pages.setFixedHeight(84)
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        self.motor_group = QFrame()
        self.motor_group.setObjectName("modasMotorGroup")
        self.motor_layout = QGridLayout(self.motor_group)          # 1. satır: Başlat / Durdur / Acil Durdurma; 2. satır: not
        self.motor_layout.setContentsMargins(10, 4, 8, 2)
        self.motor_layout.setHorizontalSpacing(10)
        self.motor_layout.setVerticalSpacing(2)
        self._motor_col = 0
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.pages, 1)
        body.addWidget(self.motor_group)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.tab_row)
        root.addLayout(body)

        self._build_start()
        self._build_label()
        self._build_worksheets()
        self._build_tools()
        self._build_windows()

        # F10: sekme harfleri (PDF §8 "View Shortcuts of Ribbon bar")
        self._tip_shortcuts: list[QShortcut] = []

    # ---- yardımcılar ----------------------------------------------------------------
    def _page(self) -> tuple[QWidget, QHBoxLayout]:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(0)
        self.pages.addWidget(w)
        return w, lay

    def big(self, key: str, text: str, glyph: str, tip: str = "", checkable: bool = False) -> QToolButton:
        b = QToolButton()
        b.setProperty("modas", "big")
        b.setText(text)
        b.setIcon(glyph_icon(glyph))
        b.setIconSize(QSize(26, 26))
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip or text)
        b.setAccessibleName(text)
        self.buttons[key] = b
        return b

    def small(self, key: str, text: str, tip: str = "", checkable: bool = False) -> QToolButton:
        b = QToolButton()
        b.setProperty("modas", "small")
        b.setText(text)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setToolTip(tip or text)
        b.setAccessibleName(text)
        self.buttons[key] = b
        return b

    @staticmethod
    def _group(title: str, *widgets) -> _Group:
        g = _Group(title)
        for w in widgets:
            g.body.addWidget(w)
        return g

    @staticmethod
    def _column(*widgets) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(0)
        for x in widgets:
            v.addWidget(x)
        v.addStretch(1)
        return w

    # ---- Start ------------------------------------------------------------------
    def _build_start(self):
        _page, lay = self._page()
        ecu = self.big("ecu", "OFFLINE", "●", "ECU durumu — tıkla: CAN / CCP bağlantı ayarları (CAN Monitor)")
        ecu.setIcon(led_icon(theme.MODAS_LED_RED))
        lay.addWidget(self._group("ECU", ecu))
        meas = self.big("measure", "Start", "▶", "Ölçümü başlat / durdur   F9", checkable=True)
        lay.addWidget(self._group("Measurement", meas))
        rec = self.big("record", "Start", "●", "Kaydı başlat / durdur   Ctrl+F9 (oturum kaydı)", checkable=True)
        lay.addWidget(self._group("Recording", rec))

        # Current Project and Workbase
        grid = QWidget()
        g = QGridLayout(grid)
        g.setContentsMargins(0, 4, 0, 0)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(1)
        self.fields: dict[str, QLineEdit] = {}
        for r, (key, title) in enumerate((("project", "Project:"), ("workbase", "Workbase:"), ("a2l", "A2L:"))):
            lab = QLabel(title)
            lab.setObjectName("modasFieldLabel")
            edit = QLineEdit("—")
            edit.setObjectName("modasField")
            edit.setReadOnly(True)
            edit.setMinimumWidth(150)
            edit.setFocusPolicy(Qt.NoFocus)
            g.addWidget(lab, r, 0, Qt.AlignRight)
            g.addWidget(edit, r, 1)
            self.fields[key] = edit
        lay.addWidget(self._group("Current Project and Workbase", grid))

        # Data: WP | COPY→ / Diff / COPY← | RP | Read / Write
        wp = self.big("wp", "WP", "▤", "Work page (WP): ECU RAM veri seti — düzenlenebilir   F8 ile WP↔RP", checkable=True)
        rp = self.big("rp", "RP", "▥", "Reference page (RP): yerel referans görüntüsü — salt okunur   F8", checkable=True)
        wp.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(wp)
        grp.addButton(rp)
        self._page_group = grp
        copy_fwd = self.small("copy_wp_rp", "COPY  WP ▶ RP", "WP'deki değerleri referans (RP) olarak sakla")
        self.diff_label = QLabel("Diff: 0")
        self.diff_label.setObjectName("modasDiff")
        self.diff_label.setAlignment(Qt.AlignCenter)
        copy_back = self.small("copy_rp_wp", "COPY  WP ◀ RP", "Referans (RP) değerlerini ECU RAM'ine (WP) geri yaz")
        mid = self._column(copy_fwd, self.diff_label, copy_back)
        read = self.small("read_ecu", "⇩ Read data from ECU", "Çalışma alanındaki tüm etiketleri ECU'dan oku")
        write = self.small("write_ecu", "⇧ Write data to ECU", "Bekleyen (sarı) kalibrasyon değerlerini ECU RAM'ine yaz")
        io = self._column(read, write)
        lay.addWidget(self._group("Data", wp, mid, rp, io))
        lay.addStretch(1)

    # ---- Label ------------------------------------------------------------------
    def _build_label(self):
        _page, lay = self._page()
        lay.addWidget(self._group(
            "Label",
            self.big("add_label", "Add label", "＋", "Variable list'ten seçili etiketi worksheet'e ekle   Enter"),
            self.big("remove_label", "Remove", "✕", "Etiketi görünümden kaldır   Delete"),
            self.big("var_info", "Information", "ⓘ", "Variable information   Ctrl+I"),
        ))
        fmts = [("fmt_phys", "Physical", "Ctrl+P"), ("fmt_dec", "Decimal", "Ctrl+D"),
                ("fmt_hex", "Hexadecimal", "Ctrl+H"), ("fmt_bin", "Binary", "Ctrl+B")]
        btns = [self.small(k, t, f"{t} biçimi   {sc}", checkable=True) for k, t, sc in fmts]
        self.buttons["fmt_phys"].setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in btns:
            grp.addButton(b)
        self._fmt_group = grp
        lay.addWidget(self._group("Format", self._column(*btns[:2]), self._column(*btns[2:])))
        lay.addStretch(1)

    # ---- Worksheets -------------------------------------------------------------
    def _build_worksheets(self):
        _page, lay = self._page()
        lay.addWidget(self._group(
            "Worksheets",
            self.big("sheet_new", "New", "＋", "Yeni worksheet"),
            self.big("sheet_rename", "Rename", "✎", "Aktif worksheet'i yeniden adlandır"),
            self.big("sheet_delete", "Delete", "🗑", "Aktif worksheet'i sil"),
        ))
        lay.addWidget(self._group("Workfolder", self.big("save_workfolder", "Save", "💾", "Çalışma klasörünü (worksheet düzenini) kaydet   F12")))
        lay.addStretch(1)

    # ---- Tools ------------------------------------------------------------------
    def _build_tools(self):
        self._tools_page, self._tools_layout = self._page()
        self._tools_group = _Group("Pages")
        self._tools_layout.addWidget(self._tools_group)
        self._tools_layout.addStretch(1)
        self._page_buttons: list[QToolButton] = []
        self._pages_btn_group = QButtonGroup(self)
        self._pages_btn_group.setExclusive(True)

    def set_pages(self, pages: list):
        """Tools sekmesindeki sayfa düğmeleri: ``[(simge, ad), ...]`` (sıra = ``MainWindow._nav_pages``)."""
        for i, (icon, label) in enumerate(pages):
            b = self.big(f"page_{i}", label, icon, f"{label}   Ctrl+{i + 1}", checkable=True)
            self._pages_btn_group.addButton(b, i)
            self._tools_group.body.addWidget(b)
            self._page_buttons.append(b)

    def select_page(self, index: int):
        if 0 <= index < len(self._page_buttons):
            self._page_buttons[index].setChecked(True)

    # ---- Windows ----------------------------------------------------------------
    def _build_windows(self):
        _page, lay = self._page()
        lay.addWidget(self._group(
            "Arrange",
            self.big("tile", "Tile", "▦", "Pencereleri döşe"),
            self.big("cascade", "Cascade", "❐", "Pencereleri kademeli diz"),
            self.big("close_all", "Close all", "✕", "Aktif worksheet'teki tüm pencereleri kapat"),
        ))
        lay.addWidget(self._group(
            "Show",
            self.big("toggle_vars", "Variable list", "☰", "Variable list'i göster / gizle   F2", checkable=True),
            self.big("toggle_log", "Log-Windows", "▤", "Log penceresini göster / gizle   F3", checkable=True),
            self.big("project_manager", "Project Manager", "📁", "Proje yöneticisi   F7"),
        ))
        self.buttons["toggle_vars"].setChecked(True)
        self.buttons["toggle_log"].setChecked(True)
        lay.addStretch(1)

    # ---- durum ------------------------------------------------------------------
    def add_status_widget(self, widget: QWidget, stretch: int = 0):
        """Sekme satırının sağına (başlığın yanına) durum alanı widget'ı ekler."""
        self.tab_layout.addWidget(widget, stretch)

    def add_motor_widget(self, widget: QWidget):
        """Motor grubunun üst satırına (soldan sağa) ekler."""
        self.motor_layout.addWidget(widget, 0, self._motor_col)
        self._motor_col += 1

    def add_motor_note(self, widget: QWidget):
        """Motor grubunun alt satırına (tüm genişlik) uyarı / not ekler: üst satırı genişletmez."""
        self.motor_layout.addWidget(widget, 1, 0, 1, max(1, self._motor_col))
        self.motor_layout.setRowStretch(2, 1)

    def set_ecu_state(self, state: str, text: str):
        """``state``: 'off' (kırmızı) | 'wait' (turuncu) | 'on' (yeşil). Metin düğmenin altında görünür."""
        color = {"on": theme.MODAS_LED_GREEN, "wait": theme.MODAS_ORANGE}.get(state, theme.MODAS_LED_RED)
        b = self.buttons["ecu"]
        b.setIcon(led_icon(color))
        b.setText(text)
        b.setProperty("ecuState", state)

    def set_diff(self, n: int):
        self.diff_label.setText(f"Diff: {n}")
        self.diff_label.setProperty("diff", n > 0)
        self.diff_label.style().unpolish(self.diff_label)
        self.diff_label.style().polish(self.diff_label)
        for key in ("wp", "rp"):                       # PDF §4: fark varsa WP / RP düğmeleri kırmızı gösterilir
            self.buttons[key].setProperty("alert", n > 0)
            self.buttons[key].style().unpolish(self.buttons[key])
            self.buttons[key].style().polish(self.buttons[key])

    def set_field(self, key: str, text: str):
        if key in self.fields:
            self.fields[key].setText(text or "—")
            self.fields[key].setToolTip(text or "")
            self.fields[key].setCursorPosition(0)

    def select_tab(self, index: int):
        self.tabs.setCurrentIndex(index)

    # ---- F10 sekme ipuçları ---------------------------------------------------------
    def toggle_key_tips(self) -> bool:
        """F10: sekme adlarının yanında erişim harfini gösterir; harfe basınca sekme açılır, Esc/F10 kapatır."""
        self._tips_on = not self._tips_on
        for i, (title, key) in enumerate(TABS):
            self.tabs.setTabText(i, f"{title}  [{key}]" if self._tips_on else title)
        for sc in self._tip_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._tip_shortcuts = []
        if self._tips_on:
            for i, (_t, key) in enumerate(TABS):
                sc = QShortcut(QKeySequence(key), self.window())
                sc.setContext(Qt.ApplicationShortcut)
                sc.activated.connect(lambda idx=i: (self.select_tab(idx), self.toggle_key_tips()))
                self._tip_shortcuts.append(sc)
            esc = QShortcut(QKeySequence(Qt.Key_Escape), self.window())
            esc.setContext(Qt.ApplicationShortcut)
            esc.activated.connect(self.toggle_key_tips)
            self._tip_shortcuts.append(esc)
        return self._tips_on

    @property
    def key_tips_visible(self) -> bool:
        return self._tips_on
