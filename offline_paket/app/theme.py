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

/* ---- Kompakt düğme (küçük, kenarlıklı; metin KESİLMEZ) -------------------- */
QPushButton[compact="true"] {{
    padding: 3px 10px;
    min-height: 18px;
}}

/* ---- Üst başlık şeridi + yatay gezinme (sidebar YOK) ---------------------- */
QFrame#topHeaderNavy {{
    background: #07101C;
    border: none;
    border-bottom: 1px solid #1F3853;
}}

QLabel#headerLogoBadge {{
    background: #2F8CFF;
    color: white;
    border-radius: 6px;
    font-size: 13px;
}}

QLabel#headerTitle {{
    font-size: 13.5px;
    font-weight: 700;
    color: #FFFFFF;
    background: transparent;
}}

QTabBar#topNav {{
    background: transparent;
}}

QTabBar#topNav::tab {{
    background: transparent;
    color: #8FA6BD;
    padding: 0 8px;
    height: 38px;
    margin: 0 1px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12.5px;
}}

QTabBar#topNav::tab:selected {{
    color: #FFFFFF;
    background: rgba(53, 198, 244, 0.10);
    border-bottom: 2px solid #35C6F4;
    font-weight: 600;
}}

QTabBar#topNav::tab:hover:!selected {{
    color: #E8F0F8;
}}

/* ---- Komut şeridi (sekmelerin hemen altı): koyu --------------------------- */
QFrame#actionStatusRow {{
    background: #0A1626;
    border-bottom: 1px solid #1F3853;
}}

QFrame#actionStatusRow QPushButton {{
    background: #12263D;
    color: #E8F0F8;
    border: 1px solid #2A4A6B;
    border-radius: 8px;
    padding: 0 16px;
    font-weight: 600;
}}

QFrame#actionStatusRow QPushButton:hover {{
    border-color: #35C6F4;
    color: #FFFFFF;
}}

QFrame#actionStatusRow QPushButton:disabled {{
    color: #5D7893;
    border-color: #1F3853;
}}

QFrame#actionStatusRow QPushButton[primary="true"] {{
    background: #0F2C20;
    border-color: #1D7F4B;
    color: #8BF0B4;
}}

QFrame#actionStatusRow QPushButton[danger="true"] {{
    background: #3A1313;
    border-color: #8C2B2B;
    color: #FF9A9A;
}}

QFrame#actionStatusRow QPushButton[danger="true"]:hover {{
    background: #5A1B1B;
    color: #FFFFFF;
}}

QLabel#ccpChip {{
    background: #0A1828;
    border: 1px solid #1F3853;
    border-radius: 12px;
    padding: 3px 12px;
    color: #8FA6BD;
    font-size: 12px;
    font-weight: 600;
}}

QLabel#ccpChip[state="online"] {{ background: #0E2A22; border-color: #1B6B45; color: #6EE7A1; }}
QLabel#ccpChip[state="connecting"] {{ background: #2A210C; border-color: #8A6A1E; color: #FFCB6B; }}
QLabel#ccpChip[state="lost"] {{ background: #3A1416; border-color: #7A2A2A; color: #FF9A9A; }}

QLabel#headerReadout {{
    color: #8FA6BD;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}

QLabel#connPillOk {{
    background: #0E2A22;
    color: #6EE7A1;
    border: 1px solid #1B6B45;
    border-radius: 12px;
    padding: 3px 12px;
    font-weight: 600;
    font-size: 12px;
}}

QLabel#connPillBad {{
    background: #3A1416;
    color: #FF9A9A;
    border: 1px solid #7A2A2A;
    border-radius: 12px;
    padding: 3px 12px;
    font-weight: 600;
    font-size: 12px;
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
