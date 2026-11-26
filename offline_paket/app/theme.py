"""Uygulama genelinde AÇIK (light) tema. Kullanıcının onayladığı mockup
tasarımdaki renk paletine göre: açık gri/mavi zemin, beyaz paneller,
"instrument teal" vurgu rengi, yüksek kontrastlı koyu metin.

Tek bir QSS string'i olarak tutulur ve main.py içinde
`app.setStyleSheet(APP_QSS)` ile TÜM uygulamaya (her sekmeye) uygulanır.

"""

import re

# ---- Tasarım token'ları (mockup'taki CSS değişkenlerinin karşılığı) -------
BG = "#EEF2F6"           # pencere / sayfa zemini
SURFACE = "#FFFFFF"      # panel / kart zemini
BORDER = "#D6DEE6"
INK = "#121A22"          # birincil metin
INK_2 = "#5B6B79"        # ikincil metin
INK_3 = "#8697A5"        # üçüncül / ipucu metni
MUTED = "#51616F"        # sayfa içi ikincil metin (ipucu, açıklama)
DIM = "#7C8B98"          # devre dışı / soluk metin
HEAD = "#243442"         # kart ve tablo başlıkları
SURFACE_ALT = "#F4F7FA"  # düğme / ikincil yüzey
LINE_STRONG = "#B7C4D0"  # belirgin kenarlık (giriş kutusu, düğme)

ACCENT = "#0E6E8C"       # birincil / aktif ("enstrüman turkuazı")
ACCENT_INK = "#064A60"   # hover / pressed
ACCENT_WEAK = "#E3EFF2"  # açık zemin tonu

OK = "#1B8A4C"
OK_WEAK = "#E6F5EC"
WARN = "#B9790F"
WARN_WEAK = "#FBF0DC"
DANGER = "#C22A1D"
DANGER_WEAK = "#FBE8E5"
WARN_INK = "#9A6208"     # açık zemin üzerinde okunur uyarı metni
BLUE = "#1F6FE0"         # seçili / vurgu (segment düğmesi, grafik serisi)
PURPLE = "#7B3FD1"
ORANGE = "#D9710B"

# Açık zemin / kenarlık tonları (sayfa içi CSS parçalarında kullanılır)
SURFACE_SUBTLE = "#F7F9FB"   # tablo/ağaç zemini
HOVER_BG = "#F1F5F8"
ACCENT_SOFT = "#CFE5EE"      # seçili satır / vurgulu kenarlık
ACCENT_BG = "#E8F1F5"
BLUE_BG = "#E3EEFB"
SLATE = "#5F7080"
LINE_SOFT = "#E3E9EF"
LINE_MID = "#C9D3DC"
OK_BG = "#E6F4EC"
WARN_BG = "#FFF4DC"
WARN_BG_HOVER = "#FBE6B8"
WARN_LINE = "#D9A441"
WARN_DEEP = "#7A4E05"
DANGER_BG = "#FBE9E7"
DANGER_BG2 = "#FDECEA"
DANGER_LINE = "#E3A29B"

# ---- Modas Sport çalışma alanı (Ribbon + mavi zemin + iç pencereler; bkz. app/ui/modas) ----------------
MODAS_WORKSPACE = "#A9C3E8"       # mavi çalışma zemini
MODAS_RIBBON_TABBAR = "#C9D9EE"   # ribbon sekme çubuğu
MODAS_RIBBON_BG = "#E3ECF8"       # ribbon gövdesi
MODAS_RIBBON_LINE = "#8FAAD0"     # ribbon kenarlıkları / grup ayracı
MODAS_RIBBON_HOVER = "#FFF1CE"    # düğme üzerine gelince (turuncu-sarı)
MODAS_GROUP_LABEL = "#3C5B88"     # grup alt etiketi
MODAS_ORANGE = "#F6A623"          # etkin WP / RP, basılı düğme
MODAS_ORANGE_LINE = "#C77C0A"
MODAS_LED_RED = "#D32F2F"
MODAS_LED_GREEN = "#2E9E4F"
MODAS_CAL_BG = "#FFFFFF"          # ayarlanabilir (kalibrasyon) değer: beyaz
MODAS_MEAS_BG = "#D9DDE3"         # ölçüm (salt okunur): gri
PENDING_BG = "#FFE8A8"            # yazılmayı bekleyen / değişen değer (Modas değer / tablo pencereleri)
MODAS_WIN_TITLE_BG = "#D4E0F2"    # iç pencere başlığı
MODAS_WIN_TITLE_INK = "#5F7391"
MODAS_WIN_LINE = "#7F9CC6"
MODAS_TABLE_HEAD = "#C3D2EA"
MODAS_TABLE_ALT = "#EEF3FA"
MODAS_LIST_SEL = "#F6A623"


def paint(css: str) -> str:
    """CSS/QSS metnindeki ``@@AD@@`` yer tutucularını bu modüldeki renk token'larıyla doldurur. Süslü
    parantezli (f-string kullanılamayan) stil metinlerinde rengi koda elle yazmamak için kullanılır."""
    return re.sub(r"@@([A-Z0-9_]+)@@", lambda m: globals()[m.group(1)], css)

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

FONT_SANS = '"IBM Plex Sans", "Segoe UI", "DejaVu Sans", sans-serif'
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
    font-size: 14px;
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
    font-size: 12px;
    font-weight: 600;
}}

/* Sensör durum tablosu rozetleri (bkz. dashboard_tab.get_sensor_status) */
QLabel[pill="ok"] {{
    background: {OK_WEAK};
    color: {OK};
    border-radius: 8px;
    padding: 1px 8px;
    font-weight: 700;
    font-size: 12px;
}}

QLabel[pill="watch"] {{
    background: {WARN_WEAK};
    color: {WARN};
    border-radius: 8px;
    padding: 1px 8px;
    font-weight: 700;
    font-size: 12px;
}}

/* ---- Kompakt düğme (küçük, kenarlıklı; metin KESİLMEZ) -------------------- */
QPushButton[compact="true"] {{
    padding: 3px 10px;
    min-height: 18px;
}}

/* ---- Üst başlık şeridi + yatay gezinme (sidebar YOK) ---------------------- */
QFrame#topHeaderNavy {{
    background: #FFFFFF;
    border: none;
    border-bottom: 1px solid #D6DEE6;
}}

QLabel#headerLogoBadge {{
    background: #1F6FE0;
    color: white;
    border-radius: 6px;
    font-size: 14px;
}}

QLabel#headerTitle {{
    font-size: 16px;
    font-weight: 700;
    color: #121A22;
    background: transparent;
}}

QTabBar#topNav {{
    background: transparent;
}}

QTabBar#topNav::tab {{
    background: transparent;
    color: #51616F;
    padding: 0 8px;
    height: 38px;
    margin: 0 1px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 14px;
}}

QTabBar#topNav::tab:selected {{
    color: #064A60;
    background: rgba(14, 110, 140, 0.10);
    border-bottom: 2px solid #0E6E8C;
    font-weight: 600;
}}

QTabBar#topNav::tab:hover:!selected {{
    color: #121A22;
}}

/* ---- Komut şeridi (sekmelerin hemen altı) --------------------------- */
QFrame#actionStatusRow {{
    background: #FFFFFF;
    border-bottom: 1px solid #D6DEE6;
}}

QFrame#actionStatusRow QPushButton {{
    background: #F4F7FA;
    color: #121A22;
    border: 1px solid #B7C4D0;
    border-radius: 8px;
    padding: 0 16px;
    font-weight: 600;
}}

QFrame#actionStatusRow QPushButton:hover {{
    border-color: #0E6E8C;
    color: #0E6E8C;
}}

QFrame#actionStatusRow QPushButton:disabled {{
    color: #7C8B98;
    border-color: #D6DEE6;
}}

QFrame#actionStatusRow QPushButton[primary="true"] {{
    background: #E6F4EC;
    border-color: #6DBA8C;
    color: #1B6B3E;
}}

QFrame#actionStatusRow QPushButton[danger="true"] {{
    background: #F4A19A;
    border: 1px solid #C22A1D;
    color: #6F160F;
    font-weight: 700;
}}

QFrame#actionStatusRow QPushButton[danger="true"]:hover {{
    background: #EE8A81;
    border-color: #A8241A;
    color: #5A0F0A;
}}

QFrame#actionStatusRow QPushButton[danger="true"]:checked {{
    background: #7A130B;
    border: 1px solid #4A0B06;
    color: #FFFFFF;
}}

QFrame#actionStatusRow QPushButton[danger="true"]:disabled {{
    background: #FBE9E7;
    border: 1px solid #E3A29B;
    color: #B98A85;
}}

QFrame#actionStatusRow QPushButton#motorSwitch {{
    background: transparent;
    border: none;
    padding: 0;
}}

QFrame#actionStatusRow QLabel#motorToggleTitle {{
    color: #121A22;
    font-weight: 600;
    background: transparent;
}}

QFrame#actionStatusRow QLabel#motorToggleValue {{
    color: #5B6B79;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}}

QFrame#actionStatusRow QFrame#cmdSep {{
    background: #D6DEE6;
    max-width: 1px;
    min-width: 1px;
}}

QPushButton#estopWarn, QFrame#actionStatusRow QPushButton#estopWarn {{
    color: #C22A1D;
    font-size: 13px;
    font-weight: 700;
    background: transparent;
    border: none;
    padding: 0 4px;
    text-decoration: underline;
}}
QPushButton#estopWarn:hover, QFrame#actionStatusRow QPushButton#estopWarn:hover {{
    color: #8E1D14;
    background: transparent;
    border: none;
}}

QLabel#ccpChip {{
    background: #FFFFFF;
    border: 1px solid #D6DEE6;
    border-radius: 12px;
    padding: 3px 12px;
    color: #51616F;
    font-size: 13px;
    font-weight: 600;
}}

QLabel#ccpChip[state="online"] {{ background: #E6F4EC; border-color: #9AD1B2; color: #1B8A4C; }}
QLabel#ccpChip[state="connecting"] {{ background: #FFF4DC; border-color: #D9A441; color: #9A6208; }}
QLabel#ccpChip[state="lost"] {{ background: #FBE9E7; border-color: #E3A29B; color: #C22A1D; }}

QLabel#headerReadout {{
    color: #51616F;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}

QLabel#connPillOk {{
    background: #E6F4EC;
    color: #1B8A4C;
    border: 1px solid #9AD1B2;
    border-radius: 12px;
    padding: 3px 12px;
    font-weight: 600;
    font-size: 13px;
}}

QLabel#connPillBad {{
    background: #FBE9E7;
    color: #C22A1D;
    border: 1px solid #E3A29B;
    border-radius: 12px;
    padding: 3px 12px;
    font-weight: 600;
    font-size: 13px;
}}
"""
