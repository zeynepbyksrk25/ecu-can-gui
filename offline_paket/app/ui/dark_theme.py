"""Sayfa teması (açık palet; modül adı geriye uyumluluk için "dark_theme" kaldı) (Ana Sayfa / CAN Monitor): tek bir iç "gövde" widget'ına KAPSAMLI uygulanan
QSS. QMessageBox/QDialog gibi üst düzey pencereler bu widget'ın çocuğu olmadığı için
etkilenmez (açık tema ile okunur kalır). Kullanım:

    body = QWidget(); body.setObjectName("dashBody"); body.setStyleSheet(dark_qss("dashBody"))
"""

from app import theme

_BASE = theme.paint("""
DashboardTab { background: @@BG@@; }
DashboardTab QWidget { background: transparent; }
DashboardTab QLabel { background: transparent; color: @@INK@@; }
DashboardTab QFrame#card, DashboardTab QFrame#trendCard {
    background: @@SURFACE@@;
    border: 1px solid @@LINE_MID@@; border-radius: 10px; }
DashboardTab QFrame#rowFrame { background: transparent; border: none; border-bottom: 1px solid @@LINE_SOFT@@; }
DashboardTab QFrame#vsep { background: @@BORDER@@; border: none; }
DashboardTab QLabel#cardTitle { color: @@HEAD@@; font-size: 13px; font-weight: 700; letter-spacing: 1px; }
DashboardTab QLabel#rowName { color: @@INK@@; font-size: 14px; font-weight: 600; }
DashboardTab QLabel#rowName:disabled { color: @@SLATE@@; }
DashboardTab QLabel#mutedSmall { color: @@MUTED@@; font-size: 12px; }
DashboardTab QLabel#okSmall { color: @@OK@@; font-size: 12px; }
DashboardTab QLabel#errSmall { color: @@DANGER@@; font-size: 12px; }
DashboardTab QLabel#warnSmall, DashboardTab QLabel#warnDot { color: @@WARN_INK@@; font-size: 12px; font-weight: 700; }
DashboardTab QLabel#colHead { color: @@SLATE@@; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
DashboardTab QLabel#onoff { color: @@MUTED@@; font-size: 12px; font-weight: 700; }
DashboardTab QLabel#onoff[on="true"] { color: @@OK@@; }
DashboardTab QLabel#legendItem { color: @@HEAD@@; font-size: 13px; }
DashboardTab QLabel#chipGreen { background: @@OK_BG@@; color: @@OK@@; border: 1px solid #9AD1B2;
    border-radius: 10px; padding: 1px 9px; font-size: 12px; font-weight: 600; }
DashboardTab QLabel#chipMuted { background: @@BG@@; color: @@MUTED@@; border: 1px solid @@LINE_MID@@;
    border-radius: 10px; padding: 1px 9px; font-size: 12px; font-weight: 600; }
DashboardTab QLabel#roleBanner { background: @@WARN_BG@@; color: @@WARN_DEEP@@; border: 1px solid @@WARN_LINE@@;
    border-radius: 8px; padding: 6px 10px; font-size: 13px; font-weight: 600; }
DashboardTab QPushButton#linkWarn { background: @@WARN_BG@@; color: @@WARN_DEEP@@; border: 1px solid @@WARN_LINE@@;
    border-radius: 10px; padding: 1px 10px; font-size: 12px; font-weight: 700; min-height: 18px; }
DashboardTab QPushButton#linkWarn:hover { background: @@WARN_BG_HOVER@@; border-color: @@WARN_INK@@; }
DashboardTab QListWidget#eventsList { background: transparent; border: none; outline: none; font-size: 12px; }
DashboardTab QListWidget#eventsList::item { padding: 3px 2px; border-bottom: 1px solid @@BG@@; }
DashboardTab QLabel#chipBad { background: @@DANGER_BG@@; color: @@DANGER@@; border: 1px solid @@DANGER_LINE@@;
    border-radius: 10px; padding: 1px 9px; font-size: 12px; font-weight: 700; }
DashboardTab QLabel#trendReadout { background: rgba(10,24,40,235); border: 1px solid @@LINE_STRONG@@;
    border-radius: 7px; padding: 5px 8px; font-size: 12px; }
DashboardTab QDoubleSpinBox#valueSpin { background: @@SURFACE@@; border: 1px solid @@LINE_STRONG@@; border-radius: 6px;
    padding: 1px 16px 1px 8px; color: @@INK@@; font-size: 14px; font-weight: 700; min-height: 20px; }
DashboardTab QDoubleSpinBox#valueSpin:disabled { color: @@SLATE@@; border-color: @@BORDER@@; }
DashboardTab QDoubleSpinBox#valueSpin:focus { border-color: @@ACCENT@@; }
DashboardTab QDoubleSpinBox#flightSpin { background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 1px 20px 1px 2px; color: @@INK@@; font-size: 15px; font-weight: 700; min-height: 24px; }
DashboardTab QDoubleSpinBox#flightSpin::up-button, DashboardTab QDoubleSpinBox#flightSpin::down-button { width: 16px; }
DashboardTab QDoubleSpinBox#flightSpin:disabled { color: @@SLATE@@; }
DashboardTab QDoubleSpinBox#flightSpin:focus { background: @@SURFACE@@; border: 1px solid @@ACCENT@@; }
DashboardTab QPushButton { background: @@SURFACE_ALT@@; border: 1px solid @@LINE_STRONG@@; border-radius: 8px; color: @@INK@@;
    padding: 6px 14px; font-weight: 600; }
DashboardTab QPushButton:hover { border-color: @@ACCENT@@; color: @@INK@@; }
DashboardTab QPushButton:disabled { color: @@DIM@@; border-color: @@BORDER@@; }
DashboardTab QPushButton[compact="true"] { padding: 3px 10px; min-height: 20px; border-radius: 7px; font-size: 13px; }
DashboardTab QPushButton[tone="go"] { border-color: #6DBA8C; color: #1B6B3E; background: @@OK_BG@@; }
DashboardTab QPushButton[seg="true"] { border-radius: 0; padding: 3px 6px; min-height: 20px; font-size: 13px;
    color: @@MUTED@@; background: @@SURFACE@@; border-left: none; }
DashboardTab QPushButton[seg="true"]:checked { background: @@BLUE@@; color: @@SURFACE@@; }
DashboardTab QSlider::groove:horizontal { height: 4px; background: #D0DAE3; border-radius: 2px; }
DashboardTab QSlider::sub-page:horizontal { background: @@BLUE@@; border-radius: 2px; }
DashboardTab QSlider::handle:horizontal { background: @@SURFACE@@; width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; }
DashboardTab QFrame#gaugeCard { background: @@SURFACE_SUBTLE@@; border: 1px solid @@BORDER@@; border-radius: 9px; }
DashboardTab QFrame#gaugeCard[state="manual"] { border-color: @@WARN_LINE@@; }
DashboardTab QFrame#gaugeCard[state="fault"] { border: 1px solid @@DANGER@@; background: @@DANGER_BG2@@; }
DashboardTab QLabel#gaugeTitle { font-weight: 700; font-size: 14px; color: @@HEAD@@; }
DashboardTab QLabel#gaugeStatus { color: @@WARN_INK@@; font-size: 12px; }
""")

def _accent_qss() -> str:
    """QFrame#card / #trendCard için ``accent`` özelliğine göre üst çizgi + başlık rengi."""
    colors = {"blue": theme.paint("@@BLUE@@"), "green": theme.paint("@@OK@@"), "orange": theme.paint("@@ORANGE@@"), "teal": theme.paint("@@ACCENT@@"),
              "purple": theme.paint("@@PURPLE@@"), "slate": theme.paint("@@MUTED@@")}
    out = []
    for name, col in colors.items():
        out.append(f'DashboardTab QFrame#card[accent="{name}"], DashboardTab QFrame#trendCard[accent="{name}"] '
                   f'{{ border-top: 3px solid {col}; }}\n'
                   f'DashboardTab QFrame#card[accent="{name}"] QLabel#cardTitle, '
                   f'DashboardTab QFrame#trendCard[accent="{name}"] QLabel#cardTitle {{ color: {col}; }}\n')
    return "".join(out)


_EXTRA = theme.paint("""
DashboardTab QAbstractItemView { background: @@SURFACE@@; color: @@INK@@; selection-background-color: @@BLUE@@;
    selection-color: @@SURFACE@@; border: 1px solid @@LINE_STRONG@@; outline: none; }
DashboardTab QComboBox { background: @@SURFACE@@; border: 1px solid @@LINE_STRONG@@; border-radius: 6px; color: @@INK@@;
    padding: 2px 8px; min-height: 22px; }
DashboardTab QComboBox:disabled { color: @@DIM@@; border-color: @@BORDER@@; }
DashboardTab QComboBox QAbstractItemView { background: @@SURFACE@@; color: @@INK@@; selection-background-color: @@BLUE@@;
    border: 1px solid @@LINE_STRONG@@; }
DashboardTab QLineEdit { background: @@SURFACE@@; border: 1px solid @@LINE_STRONG@@; border-radius: 6px; color: @@INK@@;
    padding: 2px 8px; min-height: 22px; selection-background-color: @@BLUE@@; }
DashboardTab QLineEdit:focus { border-color: @@ACCENT@@; }
DashboardTab QLineEdit#actValue { padding: 1px 8px; min-height: 24px; font-size: 14px; font-weight: 600; }
DashboardTab QLineEdit#actValue[bad="true"] { border: 1px solid @@DANGER@@; background: @@DANGER_BG2@@; }
DashboardTab QLineEdit:disabled { color: @@DIM@@; }
DashboardTab QCheckBox { color: @@HEAD@@; spacing: 6px; }
DashboardTab QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid @@LINE_STRONG@@; border-radius: 4px;
    background: @@SURFACE@@; }
DashboardTab QCheckBox::indicator:checked { background: @@BLUE@@; border-color: @@BLUE@@; }
DashboardTab QSpinBox, DashboardTab QDoubleSpinBox { background: @@SURFACE@@; border: 1px solid @@LINE_STRONG@@;
    border-radius: 6px; color: @@INK@@; padding: 1px 16px 1px 8px; min-height: 20px; }
DashboardTab QSpinBox:disabled, DashboardTab QDoubleSpinBox:disabled { color: #8A98A5; border-color: @@BORDER@@; }
DashboardTab QTableView, DashboardTab QTableWidget { background: @@SURFACE_SUBTLE@@; alternate-background-color: @@HOVER_BG@@;
    color: @@INK@@; gridline-color: @@LINE_SOFT@@; border: 1px solid @@BORDER@@; border-radius: 8px;
    selection-background-color: @@ACCENT_SOFT@@; selection-color: @@INK@@; }
DashboardTab QTableView::item, DashboardTab QTableWidget::item { padding: 2px 6px; border: none; }
DashboardTab QHeaderView { background: transparent; }
DashboardTab QHeaderView::section { background: @@SURFACE_ALT@@; color: @@MUTED@@; border: none; border-bottom: 1px solid @@BORDER@@;
    border-right: 1px solid @@LINE_SOFT@@; padding: 4px 8px; font-size: 12px; font-weight: 700; }
DashboardTab QTabWidget::pane { border: none; background: transparent; top: 0px; }
DashboardTab QTabBar::tab { background: transparent; color: @@MUTED@@; padding: 5px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }
DashboardTab QTabBar::tab:selected { color: @@INK@@; border-bottom: 2px solid @@ACCENT@@; }
DashboardTab QTabBar::tab:hover:!selected { color: @@INK@@; }
DashboardTab QListWidget { background: @@SURFACE_SUBTLE@@; color: @@INK@@; border: 1px solid @@BORDER@@; border-radius: 8px; }
DashboardTab QListWidget::item:selected { background: @@ACCENT_SOFT@@; }
DashboardTab QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
DashboardTab QScrollBar::handle:vertical { background: @@LINE_STRONG@@; border-radius: 5px; min-height: 24px; }
DashboardTab QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
DashboardTab QScrollBar::handle:horizontal { background: @@LINE_STRONG@@; border-radius: 5px; min-width: 24px; }
DashboardTab QScrollBar::add-line, DashboardTab QScrollBar::sub-line { width: 0; height: 0; }
DashboardTab QSplitter::handle { background: transparent; }
DashboardTab QFrame#stripBar { background: @@SURFACE@@; border: 1px solid @@BORDER@@; border-radius: 10px; }
DashboardTab QLabel#statusDot[state="ok"] { color: @@OK@@; font-size: 14px; }
DashboardTab QLabel#statusDot[state="warn"] { color: @@WARN@@; font-size: 14px; }
DashboardTab QLabel#statusDot[state="bad"] { color: @@DANGER@@; font-size: 14px; }
DashboardTab QLabel#statChip { background: @@SURFACE@@; border: 1px solid @@BORDER@@; border-radius: 10px; padding: 2px 10px;
    color: @@HEAD@@; font-size: 13px; }
DashboardTab QLabel#chipDim { background: @@SURFACE@@; border: 1px solid @@BORDER@@; border-radius: 10px; padding: 2px 10px;
    color: @@MUTED@@; font-size: 13px; }
DashboardTab QPushButton[tone="rec"] { border-color: @@DANGER_LINE@@; color: @@DANGER@@; background: @@DANGER_BG@@; }
DashboardTab QPushButton[tone="rec"]:checked { background: @@DANGER@@; color: @@SURFACE@@; }
DashboardTab QDialog, DashboardTab QMessageBox { background: @@SURFACE@@; }
DashboardTab QDialog QLabel, DashboardTab QMessageBox QLabel { color: @@INK@@; background: transparent; }
DashboardTab QMenu { background: @@SURFACE@@; color: @@INK@@; border: 1px solid @@LINE_STRONG@@; padding: 4px; }
DashboardTab QMenu::item { padding: 5px 18px; border-radius: 4px; }
DashboardTab QMenu::item:selected { background: @@ACCENT_SOFT@@; color: @@INK@@; }
DashboardTab QMenu::separator { height: 1px; background: @@BORDER@@; margin: 4px 6px; }
DashboardTab QTreeView, DashboardTab QTreeWidget { background: @@SURFACE_SUBTLE@@; alternate-background-color: @@HOVER_BG@@;
    color: @@INK@@; border: 1px solid @@BORDER@@; border-radius: 8px; outline: none; }
DashboardTab QTreeView::item { padding: 3px 2px; }
DashboardTab QTreeView::item:hover { background: @@ACCENT_BG@@; }
DashboardTab QTreeView::item:selected { background: @@ACCENT_SOFT@@; color: @@INK@@; }
DashboardTab QTextEdit, DashboardTab QPlainTextEdit { background: @@SURFACE@@; color: @@INK@@; border: 1px solid @@LINE_STRONG@@;
    border-radius: 6px; selection-background-color: @@BLUE@@; }
DashboardTab QProgressBar { background: @@SURFACE@@; border: 1px solid @@LINE_STRONG@@; border-radius: 6px; text-align: center;
    color: @@INK@@; min-height: 14px; }
DashboardTab QProgressBar::chunk { background: @@BLUE@@; border-radius: 5px; }
DashboardTab QRadioButton { color: @@HEAD@@; spacing: 6px; }
DashboardTab QListView::indicator, DashboardTab QTreeView::indicator { width: 14px; height: 14px; border: 1px solid @@LINE_STRONG@@; border-radius: 3px; background: @@SURFACE@@; }
DashboardTab QListView::indicator:checked, DashboardTab QTreeView::indicator:checked { background: @@BLUE@@; border-color: @@BLUE@@; }
DashboardTab QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid @@LINE_STRONG@@; border-radius: 8px; background: @@SURFACE@@; }
DashboardTab QRadioButton::indicator:checked { background: @@BLUE@@; border-color: @@BLUE@@; }
DashboardTab QLabel#pageTitle { font-size: 16px; font-weight: 700; color: @@INK@@; }
DashboardTab QLabel#kvKey { color: @@MUTED@@; font-size: 13px; font-weight: 600; }
DashboardTab QLabel#kvVal { color: @@INK@@; font-size: 14px; font-weight: 600; }
DashboardTab QLabel#chipBlue { background: @@BLUE_BG@@; color: #1F5FB5; border: 1px solid #A9C8EE; border-radius: 10px;
    padding: 2px 10px; font-size: 13px; font-weight: 600; }
DashboardTab QTabBar { background: transparent; border: none; }
DashboardTab QTabWidget::tab-bar { left: 0px; }
DashboardTab QTabBar::close-button { background: #CBD5DE; border-radius: 3px; margin: 2px; subcontrol-position: right; }
DashboardTab QTabBar::close-button:hover { background: #c0392b; }
DashboardTab QGroupBox { background: transparent; border: 1px solid @@BORDER@@; border-radius: 8px; margin-top: 10px;
    padding: 8px; color: @@MUTED@@; font-weight: 700; }
DashboardTab QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: @@HEAD@@; }
""")


def dark_qss(root_id: str = "dashBody") -> str:
    q = _BASE + _EXTRA + _accent_qss()
    return q.replace("DashboardTab {", f"QWidget#{root_id} {{").replace("DashboardTab ", f"QWidget#{root_id} ")


def style_plot(plot_widget, bg: str = theme.paint("@@SURFACE@@")):
    """pyqtgraph grafiğini koyu temaya uydurur (zemin, eksen, ızgara, etiket renkleri)."""
    import pyqtgraph as pg
    plot_widget.setBackground(bg)
    pi = plot_widget.getPlotItem()
    for name in ("left", "bottom", "right", "top"):
        ax = pi.getAxis(name)
        ax.setTextPen(pg.mkPen(theme.paint("@@MUTED@@")))
        ax.setPen(pg.mkPen(theme.paint("@@LINE_STRONG@@")))
    pi.showGrid(x=True, y=True, alpha=0.18)


def dark_scroll_page(page, root_id: str = "darkBody"):
    """Sayfa widget'ını koyu gövdeye (kapsamlı QSS) koyar ve gövdeyi döndürür; ``body.inner`` = sayfa."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    body = QWidget()
    body.setObjectName(root_id)
    body.setStyleSheet(dark_qss(root_id))
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(page)
    body.inner = page
    return body
