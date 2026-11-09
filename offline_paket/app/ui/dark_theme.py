"""Sayfa teması (açık palet; modül adı geriye uyumluluk için "dark_theme" kaldı) (Ana Sayfa / CAN Monitor): tek bir iç "gövde" widget'ına KAPSAMLI uygulanan
QSS. QMessageBox/QDialog gibi üst düzey pencereler bu widget'ın çocuğu olmadığı için
etkilenmez (açık tema ile okunur kalır). Kullanım:

    body = QWidget(); body.setObjectName("dashBody"); body.setStyleSheet(dark_qss("dashBody"))
"""

_BASE = """
DashboardTab { background: #EEF2F6; }
DashboardTab QWidget { background: transparent; }
DashboardTab QLabel { background: transparent; color: #121A22; }
DashboardTab QFrame#card, DashboardTab QFrame#trendCard {
    background: #FFFFFF;
    border: 1px solid #C9D3DC; border-radius: 10px; }
DashboardTab QFrame#rowFrame { background: transparent; border: none; border-bottom: 1px solid #E3E9EF; }
DashboardTab QFrame#vsep { background: #D6DEE6; border: none; }
DashboardTab QLabel#cardTitle { color: #243442; font-size: 13px; font-weight: 700; letter-spacing: 1px; }
DashboardTab QLabel#rowName { color: #121A22; font-size: 14px; font-weight: 600; }
DashboardTab QLabel#rowName:disabled { color: #7C8B98; }
DashboardTab QLabel#mutedSmall { color: #51616F; font-size: 12px; }
DashboardTab QLabel#okSmall { color: #1B8A4C; font-size: 12px; }
DashboardTab QLabel#errSmall { color: #C22A1D; font-size: 12px; }
DashboardTab QLabel#warnSmall, DashboardTab QLabel#warnDot { color: #9A6208; font-size: 12px; font-weight: 700; }
DashboardTab QLabel#colHead { color: #7C8B98; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
DashboardTab QLabel#onoff { color: #51616F; font-size: 12px; font-weight: 700; }
DashboardTab QLabel#onoff[on="true"] { color: #1B8A4C; }
DashboardTab QLabel#legendItem { color: #243442; font-size: 13px; }
DashboardTab QLabel#chipGreen { background: #E6F4EC; color: #1B8A4C; border: 1px solid #9AD1B2;
    border-radius: 10px; padding: 1px 9px; font-size: 12px; font-weight: 600; }
DashboardTab QLabel#chipBad { background: #FBE9E7; color: #C22A1D; border: 1px solid #E3A29B;
    border-radius: 10px; padding: 1px 9px; font-size: 12px; font-weight: 700; }
DashboardTab QLabel#trendReadout { background: rgba(10,24,40,235); border: 1px solid #B7C4D0;
    border-radius: 7px; padding: 5px 8px; font-size: 12px; }
DashboardTab QDoubleSpinBox#valueSpin { background: #FFFFFF; border: 1px solid #B7C4D0; border-radius: 6px;
    padding: 1px 16px 1px 8px; color: #121A22; font-size: 14px; font-weight: 700; min-height: 20px; }
DashboardTab QDoubleSpinBox#valueSpin:disabled { color: #8A98A5; border-color: #D6DEE6; }
DashboardTab QDoubleSpinBox#valueSpin:focus { border-color: #0E6E8C; }
DashboardTab QDoubleSpinBox#flightSpin { background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 1px 20px 1px 2px; color: #121A22; font-size: 15px; font-weight: 700; min-height: 24px; }
DashboardTab QDoubleSpinBox#flightSpin::up-button, DashboardTab QDoubleSpinBox#flightSpin::down-button { width: 16px; }
DashboardTab QDoubleSpinBox#flightSpin:disabled { color: #8A98A5; }
DashboardTab QDoubleSpinBox#flightSpin:focus { background: #FFFFFF; border: 1px solid #0E6E8C; }
DashboardTab QPushButton { background: #F4F7FA; border: 1px solid #B7C4D0; border-radius: 8px; color: #121A22;
    padding: 6px 14px; font-weight: 600; }
DashboardTab QPushButton:hover { border-color: #0E6E8C; color: #121A22; }
DashboardTab QPushButton:disabled { color: #7C8B98; border-color: #D6DEE6; }
DashboardTab QPushButton[compact="true"] { padding: 3px 10px; min-height: 20px; border-radius: 7px; font-size: 13px; }
DashboardTab QPushButton[tone="go"] { border-color: #6DBA8C; color: #1B6B3E; background: #E6F4EC; }
DashboardTab QPushButton[seg="true"] { border-radius: 0; padding: 3px 6px; min-height: 20px; font-size: 13px;
    color: #51616F; background: #FFFFFF; border-left: none; }
DashboardTab QPushButton[seg="true"]:checked { background: #1F6FE0; color: #ffffff; }
DashboardTab QSlider::groove:horizontal { height: 4px; background: #D0DAE3; border-radius: 2px; }
DashboardTab QSlider::sub-page:horizontal { background: #1F6FE0; border-radius: 2px; }
DashboardTab QSlider::handle:horizontal { background: #ffffff; width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; }
DashboardTab QFrame#gaugeCard { background: #F7F9FB; border: 1px solid #D6DEE6; border-radius: 9px; }
DashboardTab QFrame#gaugeCard[state="manual"] { border-color: #D9A441; }
DashboardTab QFrame#gaugeCard[state="fault"] { border: 1px solid #C22A1D; background: #FDECEA; }
DashboardTab QLabel#gaugeTitle { font-weight: 700; font-size: 14px; color: #243442; }
DashboardTab QLabel#gaugeStatus { color: #9A6208; font-size: 12px; }
"""

_EXTRA = """
DashboardTab QAbstractItemView { background: #FFFFFF; color: #121A22; selection-background-color: #1F6FE0;
    selection-color: #ffffff; border: 1px solid #B7C4D0; outline: none; }
DashboardTab QComboBox { background: #FFFFFF; border: 1px solid #B7C4D0; border-radius: 6px; color: #121A22;
    padding: 2px 8px; min-height: 22px; }
DashboardTab QComboBox:disabled { color: #7C8B98; border-color: #D6DEE6; }
DashboardTab QComboBox QAbstractItemView { background: #FFFFFF; color: #121A22; selection-background-color: #1F6FE0;
    border: 1px solid #B7C4D0; }
DashboardTab QLineEdit { background: #FFFFFF; border: 1px solid #B7C4D0; border-radius: 6px; color: #121A22;
    padding: 2px 8px; min-height: 22px; selection-background-color: #1F6FE0; }
DashboardTab QLineEdit:focus { border-color: #0E6E8C; }
DashboardTab QLineEdit:disabled { color: #7C8B98; }
DashboardTab QCheckBox { color: #243442; spacing: 6px; }
DashboardTab QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #B7C4D0; border-radius: 4px;
    background: #FFFFFF; }
DashboardTab QCheckBox::indicator:checked { background: #1F6FE0; border-color: #1F6FE0; }
DashboardTab QSpinBox, DashboardTab QDoubleSpinBox { background: #FFFFFF; border: 1px solid #B7C4D0;
    border-radius: 6px; color: #121A22; padding: 1px 16px 1px 8px; min-height: 20px; }
DashboardTab QSpinBox:disabled, DashboardTab QDoubleSpinBox:disabled { color: #8A98A5; border-color: #D6DEE6; }
DashboardTab QTableView, DashboardTab QTableWidget { background: #F7F9FB; alternate-background-color: #F1F5F8;
    color: #121A22; gridline-color: #E3E9EF; border: 1px solid #D6DEE6; border-radius: 8px;
    selection-background-color: #CFE5EE; selection-color: #121A22; }
DashboardTab QTableView::item, DashboardTab QTableWidget::item { padding: 2px 6px; border: none; }
DashboardTab QHeaderView { background: transparent; }
DashboardTab QHeaderView::section { background: #F4F7FA; color: #51616F; border: none; border-bottom: 1px solid #D6DEE6;
    border-right: 1px solid #E3E9EF; padding: 4px 8px; font-size: 12px; font-weight: 700; }
DashboardTab QTabWidget::pane { border: none; background: transparent; top: 0px; }
DashboardTab QTabBar::tab { background: transparent; color: #51616F; padding: 5px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }
DashboardTab QTabBar::tab:selected { color: #121A22; border-bottom: 2px solid #0E6E8C; }
DashboardTab QTabBar::tab:hover:!selected { color: #121A22; }
DashboardTab QListWidget { background: #F7F9FB; color: #121A22; border: 1px solid #D6DEE6; border-radius: 8px; }
DashboardTab QListWidget::item:selected { background: #CFE5EE; }
DashboardTab QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
DashboardTab QScrollBar::handle:vertical { background: #B7C4D0; border-radius: 5px; min-height: 24px; }
DashboardTab QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
DashboardTab QScrollBar::handle:horizontal { background: #B7C4D0; border-radius: 5px; min-width: 24px; }
DashboardTab QScrollBar::add-line, DashboardTab QScrollBar::sub-line { width: 0; height: 0; }
DashboardTab QSplitter::handle { background: transparent; }
DashboardTab QFrame#stripBar { background: #FFFFFF; border: 1px solid #D6DEE6; border-radius: 10px; }
DashboardTab QLabel#statusDot[state="ok"] { color: #1B8A4C; font-size: 14px; }
DashboardTab QLabel#statusDot[state="warn"] { color: #B9790F; font-size: 14px; }
DashboardTab QLabel#statusDot[state="bad"] { color: #C22A1D; font-size: 14px; }
DashboardTab QLabel#statChip { background: #FFFFFF; border: 1px solid #D6DEE6; border-radius: 10px; padding: 2px 10px;
    color: #243442; font-size: 13px; }
DashboardTab QLabel#chipDim { background: #FFFFFF; border: 1px solid #D6DEE6; border-radius: 10px; padding: 2px 10px;
    color: #51616F; font-size: 13px; }
DashboardTab QPushButton[tone="rec"] { border-color: #E3A29B; color: #C22A1D; background: #FBE9E7; }
DashboardTab QPushButton[tone="rec"]:checked { background: #C22A1D; color: #ffffff; }
DashboardTab QDialog, DashboardTab QMessageBox { background: #FFFFFF; }
DashboardTab QDialog QLabel, DashboardTab QMessageBox QLabel { color: #121A22; background: transparent; }
DashboardTab QMenu { background: #FFFFFF; color: #121A22; border: 1px solid #B7C4D0; padding: 4px; }
DashboardTab QMenu::item { padding: 5px 18px; border-radius: 4px; }
DashboardTab QMenu::item:selected { background: #CFE5EE; color: #121A22; }
DashboardTab QMenu::separator { height: 1px; background: #D6DEE6; margin: 4px 6px; }
DashboardTab QTreeView, DashboardTab QTreeWidget { background: #F7F9FB; alternate-background-color: #F1F5F8;
    color: #121A22; border: 1px solid #D6DEE6; border-radius: 8px; outline: none; }
DashboardTab QTreeView::item { padding: 3px 2px; }
DashboardTab QTreeView::item:hover { background: #E8F1F5; }
DashboardTab QTreeView::item:selected { background: #CFE5EE; color: #121A22; }
DashboardTab QTextEdit, DashboardTab QPlainTextEdit { background: #FFFFFF; color: #121A22; border: 1px solid #B7C4D0;
    border-radius: 6px; selection-background-color: #1F6FE0; }
DashboardTab QProgressBar { background: #FFFFFF; border: 1px solid #B7C4D0; border-radius: 6px; text-align: center;
    color: #121A22; min-height: 14px; }
DashboardTab QProgressBar::chunk { background: #1F6FE0; border-radius: 5px; }
DashboardTab QRadioButton { color: #243442; spacing: 6px; }
DashboardTab QListView::indicator, DashboardTab QTreeView::indicator { width: 14px; height: 14px; border: 1px solid #B7C4D0; border-radius: 3px; background: #FFFFFF; }
DashboardTab QListView::indicator:checked, DashboardTab QTreeView::indicator:checked { background: #1F6FE0; border-color: #1F6FE0; }
DashboardTab QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid #B7C4D0; border-radius: 8px; background: #FFFFFF; }
DashboardTab QRadioButton::indicator:checked { background: #1F6FE0; border-color: #1F6FE0; }
DashboardTab QLabel#pageTitle { font-size: 16px; font-weight: 700; color: #121A22; }
DashboardTab QLabel#kvKey { color: #51616F; font-size: 13px; font-weight: 600; }
DashboardTab QLabel#kvVal { color: #121A22; font-size: 14px; font-weight: 600; }
DashboardTab QLabel#chipBlue { background: #E3EEFB; color: #1F5FB5; border: 1px solid #A9C8EE; border-radius: 10px;
    padding: 2px 10px; font-size: 13px; font-weight: 600; }
DashboardTab QTabBar { background: transparent; border: none; }
DashboardTab QTabWidget::tab-bar { left: 0px; }
DashboardTab QTabBar::close-button { background: #CBD5DE; border-radius: 3px; margin: 2px; subcontrol-position: right; }
DashboardTab QTabBar::close-button:hover { background: #c0392b; }
DashboardTab QGroupBox { background: transparent; border: 1px solid #D6DEE6; border-radius: 8px; margin-top: 10px;
    padding: 8px; color: #51616F; font-weight: 700; }
DashboardTab QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #243442; }
"""


def dark_qss(root_id: str = "dashBody") -> str:
    q = _BASE + _EXTRA
    return q.replace("DashboardTab {", f"QWidget#{root_id} {{").replace("DashboardTab ", f"QWidget#{root_id} ")


def style_plot(plot_widget, bg: str = "#FFFFFF"):
    """pyqtgraph grafiğini koyu temaya uydurur (zemin, eksen, ızgara, etiket renkleri)."""
    import pyqtgraph as pg
    plot_widget.setBackground(bg)
    pi = plot_widget.getPlotItem()
    for name in ("left", "bottom", "right", "top"):
        ax = pi.getAxis(name)
        ax.setTextPen(pg.mkPen("#51616F"))
        ax.setPen(pg.mkPen("#B7C4D0"))
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
