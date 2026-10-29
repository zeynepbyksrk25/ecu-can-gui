"""Uygulama genelinde AÇIK (light) tema. Kullanıcının onayladığı mockup
tasarımdaki renk paletine göre: açık gri/mavi zemin, beyaz paneller,
"instrument teal" vurgu rengi, yüksek kontrastlı koyu metin.

Tek bir QSS string'i olarak tutulur ve main.py içinde
`app.setStyleSheet(APP_QSS)` ile TÜM uygulamaya (her sekmeye) uygulanır.

Eski koyu tema (DARK_QSS) geri alma (rollback) ihtimaline karşı bu
dosyada bırakılmıştır ama artık kullanılmaz / import edilmez.
"""

# ---- Tasarım token'ları (mockup'taki CSS değişkenlerinin karşılığı) -------
BG = "#EEF2F6"           # pencere / sayfa zemini
SURFACE = "#FFFFFF"      # panel / kart zemini
BORDER = "#D6DEE6"
INK = "#121A22"          # birincil metin
INK_2 = "#5B6B79"        # ikincil metin
INK_3 = "#8697A5"        # üçüncül / ipucu metni

ACCENT = "#0E6E8C"       # birincil / aktif ("enstrüman turkuazı")
ACCENT_INK = "#064A60"   # hover / pressed
ACCENT_WEAK = "#E3EFF2"  # açık zemin tonu

OK = "#1B8A4C"
OK_WEAK = "#E6F5EC"
WARN = "#B9790F"
WARN_WEAK = "#FBF0DC"
DANGER = "#C22A1D"
DANGER_WEAK = "#FBE8E5"

# Annunciator (lamba) şeridi — yalnızca Ana Sayfa'daki uyarı lambaları paneli
LAMP_STRIP_BG = "#101820"
LAMP_CELL_BG = "#1B2630"
LAMP_BORDER = "#2A3744"
LAMP_LABEL = "#7E8E9C"
LAMP_LIT_BG = WARN
LAMP_LIT_FG = "#241A02"
LAMP_OK_TEXT = "#58D88C"

# Sol kenar çubuğu (sidebar) navigasyonu — koyu lacivert, üst çubuk/durum
# çubuğuyla aynı "enstrüman" hissini taşır ama ana içerikten ayrışsın diye
# koyu renkte kalır (bkz. app/ui/main_window.py).
SIDEBAR_BG = "#122230"
SIDEBAR_ITEM_HOVER = "#1A3242"
SIDEBAR_ITEM_SELECTED = "#1E3C50"
SIDEBAR_TEXT = "#B9C7D3"
SIDEBAR_TEXT_DIM = "#7E93A3"
SIDEBAR_BORDER = "#1E3444"

FONT_SANS = '"IBM Plex Sans", "Segoe UI", sans-serif'
FONT_MONO = '"IBM Plex Mono", Consolas, monospace'

def _arrow_icons() -> tuple[str, str]:
    """SpinBox ok simgeleri (küçük PNG) — saf Python ile üretilip geçici klasöre yazılır."""
    import os, struct, tempfile, zlib

    def png(rows, color=(91, 107, 121)):
        h, w = len(rows), len(rows[0])
        raw = b""
        for r in rows:
            raw += b"\x00" + b"".join(bytes(color) + (b"\xff" if c else b"\x00") for c in r)
        def chunk(t, d):
            c = struct.pack(">I", len(d)) + t + d
            return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    up = [[0, 0, 0, 1, 1, 0, 0, 0], [0, 0, 1, 1, 1, 1, 0, 0], [0, 1, 1, 1, 1, 1, 1, 0]]
    down = list(reversed(up))
    d = os.path.join(tempfile.gettempdir(), "openecu_icons")
    os.makedirs(d, exist_ok=True)
    out = []
    for name, rows in (("up.png", up), ("down.png", down)):
        path = os.path.join(d, name)
        try:
            with open(path, "wb") as f:
                f.write(png(rows))
        except OSError:
            return "", ""
        out.append(path.replace("\\", "/"))
    return out[0], out[1]


_ARROW_UP, _ARROW_DOWN = _arrow_icons()

APP_QSS = f"""
QWidget {{
    background-color: {BG};
    color: {INK};
    font-family: {FONT_SANS};
    font-size: 13px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG};
    top: -1px;
}}

QTabBar::tab {{
    background: {SURFACE};
    color: {INK_2};
    padding: 8px 16px;
    border: 1px solid {BORDER};
    border-bottom: none;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background: {BG};
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {INK};
}}

/* Kalibrasyon sekmesi içindeki iç (nested) sekme çubuğu: dış sekme
   çubuğuyla karışmasın diye görsel olarak ayırt edilir (bkz.
   app/ui/kalibrasyon_tab.py). */
QTabWidget#innerTabs::pane {{
    border: 1px solid {BORDER};
    background: {SURFACE};
    top: -1px;
}}

QTabWidget#innerTabs QTabBar::tab {{
    background: {ACCENT_WEAK};
    color: {ACCENT_INK};
    padding: 5px 12px;
    border: 1px solid {BORDER};
    border-bottom: none;
    margin-right: 1px;
    font-weight: 500;
}}

QTabWidget#innerTabs QTabBar::tab:selected {{
    background: {SURFACE};
    color: {ACCENT_INK};
    border-bottom: 2px solid {ACCENT};
    font-weight: 700;
}}

QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px;
    font-weight: 600;
    color: {INK_2};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {INK};
}}

QLabel {{
    background: transparent;
    color: {INK};
}}

QPushButton {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 14px;
}}

QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}

QPushButton:pressed {{
    background: {ACCENT_INK};
    color: white;
}}

QPushButton:disabled {{
    color: {INK_3};
    border-color: {BORDER};
}}

QPushButton[danger="true"] {{
    background: {DANGER_WEAK};
    border-color: {DANGER};
    color: {DANGER};
    font-weight: 700;
}}

QPushButton[danger="true"]:hover {{
    background: {DANGER};
    color: white;
}}

QPushButton[primary="true"] {{
    background: {ACCENT};
    border-color: {ACCENT_INK};
    color: white;
    font-weight: 600;
}}

QPushButton[primary="true"]:hover {{
    background: {ACCENT_INK};
    color: white;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {ACCENT_WEAK};
    selection-color: {INK};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}

QAbstractSpinBox {{ padding-right: 18px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 16px; border: none; background: transparent;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-arrow {{ image: url({_ARROW_UP}); width: 8px; height: 3px; }}
QAbstractSpinBox::down-arrow {{ image: url({_ARROW_DOWN}); width: 8px; height: 3px; }}

QComboBox::drop-down {{
    border: none;
}}

QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {INK};
    selection-background-color: {ACCENT_WEAK};
    selection-color: {INK};
    border: 1px solid {BORDER};
}}

QTableWidget, QTreeWidget, QListWidget {{
    background: {SURFACE};
    alternate-background-color: {ACCENT_WEAK};
    color: {INK};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}

QHeaderView::section {{
    background: {ACCENT_WEAK};
    color: {INK_2};
    padding: 4px;
    border: 1px solid {BORDER};
}}

QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {ACCENT};
    color: white;
}}

QCheckBox, QRadioButton {{
    color: {INK};
    background: transparent;
}}

QScrollBar:vertical {{
    background: {BG};
    width: 12px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}

QScrollBar:horizontal {{
    background: {BG};
    height: 12px;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 24px;
}}

QToolTip {{
    background: {INK};
    color: {SURFACE};
    border: 1px solid {ACCENT};
    padding: 4px;
}}

QMessageBox {{
    background: {SURFACE};
}}

/* Ana Sayfa'daki değer/kart etiketleri (bkz. app/ui/dashboard_tab.py) */
QLabel[tile="true"] {{
    background: {ACCENT_WEAK};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px;
}}

QLabel[tileValue="true"] {{
    color: {ACCENT_INK};
    font-family: {FONT_MONO};
    font-size: 20px;
    font-weight: 700;
}}

QLabel[tileLabel="true"] {{
    color: {INK_2};
    font-size: 11px;
    font-weight: 600;
}}

/* Sensör durum tablosu rozetleri (bkz. dashboard_tab.get_sensor_status) */
QLabel[pill="ok"] {{
    background: {OK_WEAK};
    color: {OK};
    border-radius: 8px;
    padding: 1px 8px;
    font-weight: 700;
    font-size: 11px;
}}

QLabel[pill="watch"] {{
    background: {WARN_WEAK};
    color: {WARN};
    border-radius: 8px;
    padding: 1px 8px;
    font-weight: 700;
    font-size: 11px;
}}

/* ---- Sol kenar çubuğu (sidebar) navigasyonu --------------------------- */
QListWidget#sidebarNav {{
    background: {SIDEBAR_BG};
    border: none;
    outline: none;
    padding: 8px 10px;
    font-size: 13px;
}}

/* Seçili öge: referans mockup'taki gibi, ince sol kenarlık YERİNE,
   sidebar genişliğinin büyük bölümünü kaplayan yuvarlak köşeli parlak
   bir arkaplan (bkz. görev tanımı madde 8). */
QListWidget#sidebarNav::item {{
    color: {SIDEBAR_TEXT_DIM};
    padding: 11px 14px;
    margin: 2px 2px;
    border-radius: 8px;
    border-left: none;
}}

QListWidget#sidebarNav::item:selected {{
    background: {ACCENT};
    color: #FFFFFF;
    font-weight: 700;
}}

QListWidget#sidebarNav::item:hover:!selected {{
    background: {SIDEBAR_ITEM_HOVER};
    color: {SIDEBAR_TEXT};
}}

QWidget#sidebarRoot {{
    background: {SIDEBAR_BG};
}}

/* Sidebar alt durum bloğu: koyu zemin üzerinde YÜZEN beyaz/açık "kart"
   (bkz. görev tanımı madde 7) — derinlik app/ui/main_window.py'de ayrıca
   bir QGraphicsDropShadowEffect ile sağlanır. */
QFrame#sidebarStatusCard {{
    background: {SURFACE};
    border-radius: 10px;
}}

QLabel#sidebarStatusTitle {{
    color: {INK};
    font-size: 12px;
    background: transparent;
}}

QLabel#sidebarStatusDim {{
    color: {INK_2};
    font-size: 10.5px;
    background: transparent;
}}

QPushButton#sidebarSettingsLink {{
    background: transparent;
    color: {ACCENT_INK};
    border: none;
    border-top: 1px solid {BORDER};
    text-align: left;
    padding: 7px 2px 2px 2px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 0px;
}}

QPushButton#sidebarSettingsLink:hover {{
    color: {ACCENT};
}}

/* ---- Üst (koyu lacivert) başlık şeridi ---------------------------------- */
QFrame#topHeaderNavy {{
    background: {SIDEBAR_BG};
    border: none;
}}

QLabel#headerLogoBadge {{
    background: {ACCENT};
    color: white;
    border-radius: 7px;
    font-size: 14px;
}}

QLabel#headerTitle {{
    font-size: 15px;
    font-weight: 700;
    color: #FFFFFF;
    background: transparent;
}}

/* ---- Buton + durum satırı (başlık şeridinin hemen altı) ----------------- */
QFrame#actionStatusRow {{
    background: {BG};
    border-bottom: 1px solid {BORDER};
}}

QLabel#headerReadout {{
    color: {INK_2};
    font-size: 11.5px;
    font-weight: 600;
    background: transparent;
}}

QLabel#connPillOk {{
    background: {OK_WEAK};
    color: {OK};
    border-radius: 10px;
    padding: 3px 12px;
    font-weight: 700;
    font-size: 11px;
}}

QLabel#connPillBad {{
    background: {DANGER_WEAK};
    color: {DANGER};
    border-radius: 10px;
    padding: 3px 12px;
    font-weight: 700;
    font-size: 11px;
}}
"""

# ---------------------------------------------------------------------------
# Eski koyu tema (rollback için saklanıyor, artık kullanılmıyor).
# ---------------------------------------------------------------------------
_DARK_BG_MAIN = "#12181f"
_DARK_BG_PANEL = "#1a222c"
_DARK_BG_PANEL_ALT = "#212b37"
_DARK_BORDER = "#2c3a48"
_DARK_ACCENT = "#00c2b8"
_DARK_ACCENT_DIM = "#0d8f88"
_DARK_TEXT = "#e6edf3"
_DARK_TEXT_DIM = "#8ea0b0"
_DARK_DANGER = "#e5484d"
_DARK_DANGER_DIM = "#8f2f32"

DARK_QSS = f"""
QWidget {{
    background-color: {_DARK_BG_MAIN};
    color: {_DARK_TEXT};
    font-size: 13px;
}}
QTabWidget::pane {{ border: 1px solid {_DARK_BORDER}; background: {_DARK_BG_MAIN}; top: -1px; }}
QTabBar::tab {{ background: {_DARK_BG_PANEL}; color: {_DARK_TEXT_DIM}; padding: 8px 16px;
    border: 1px solid {_DARK_BORDER}; border-bottom: none; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {_DARK_BG_MAIN}; color: {_DARK_ACCENT};
    border-bottom: 2px solid {_DARK_ACCENT}; font-weight: 600; }}
QGroupBox {{ background: {_DARK_BG_PANEL}; border: 1px solid {_DARK_BORDER}; border-radius: 6px;
    margin-top: 14px; padding: 10px; font-weight: 600; color: {_DARK_TEXT_DIM}; }}
QPushButton {{ background: {_DARK_BG_PANEL_ALT}; color: {_DARK_TEXT}; border: 1px solid {_DARK_BORDER};
    border-radius: 4px; padding: 6px 14px; }}
QPushButton[danger="true"] {{ background: {_DARK_DANGER_DIM}; border-color: {_DARK_DANGER};
    color: #ffd7d7; font-weight: 700; }}
"""
