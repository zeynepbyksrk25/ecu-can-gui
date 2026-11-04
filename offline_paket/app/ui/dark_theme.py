"""Koyu tema (Ana Sayfa / CAN Monitor): tek bir iç "gövde" widget'ına KAPSAMLI uygulanan
QSS. QMessageBox/QDialog gibi üst düzey pencereler bu widget'ın çocuğu olmadığı için
etkilenmez (açık tema ile okunur kalır). Kullanım:

    body = QWidget(); body.setObjectName("dashBody"); body.setStyleSheet(dark_qss("dashBody"))
"""

_BASE = """
DashboardTab { background: #08121f; }
DashboardTab QWidget { background: transparent; }
DashboardTab QLabel { background: transparent; color: #e8f0f8; }
DashboardTab QFrame#card, DashboardTab QFrame#trendCard {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #12263d, stop:1 #0f2034);
    border: 1px solid #1f3853; border-radius: 10px; }
DashboardTab QFrame#rowFrame { background: transparent; border: none; border-bottom: 1px solid #1a3149; }
DashboardTab QFrame#vsep { background: #1f3853; border: none; }
DashboardTab QLabel#cardTitle { color: #cfe0f1; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
DashboardTab QLabel#rowName { color: #e8f0f8; font-size: 12.5px; font-weight: 600; }
DashboardTab QLabel#rowName:disabled { color: #5d7893; }
DashboardTab QLabel#mutedSmall { color: #8fa6bd; font-size: 11px; }
DashboardTab QLabel#okSmall { color: #6ee7a1; font-size: 11px; }
DashboardTab QLabel#errSmall { color: #ff9a9a; font-size: 11px; }
DashboardTab QLabel#warnSmall, DashboardTab QLabel#warnDot { color: #ffcb6b; font-size: 11px; font-weight: 700; }
DashboardTab QLabel#colHead { color: #5d7893; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
DashboardTab QLabel#onoff { color: #8fa6bd; font-size: 11px; font-weight: 700; }
DashboardTab QLabel#onoff[on="true"] { color: #6ee7a1; }
DashboardTab QLabel#legendItem { color: #cfe0f1; font-size: 12px; }
DashboardTab QLabel#chipGreen { background: #0e2a22; color: #6ee7a1; border: 1px solid #1b6b45;
    border-radius: 10px; padding: 1px 9px; font-size: 11px; font-weight: 600; }
DashboardTab QLabel#chipBad { background: #3a1416; color: #ff9a9a; border: 1px solid #7a2a2a;
    border-radius: 10px; padding: 1px 9px; font-size: 11px; font-weight: 700; }
DashboardTab QLabel#trendReadout { background: rgba(10,24,40,235); border: 1px solid #2a4a6b;
    border-radius: 7px; padding: 5px 8px; font-size: 11px; }
DashboardTab QDoubleSpinBox#valueSpin { background: #0a1828; border: 1px solid #2a4a6b; border-radius: 6px;
    padding: 1px 16px 1px 8px; color: #ffffff; font-size: 13px; font-weight: 700; min-height: 20px; }
DashboardTab QDoubleSpinBox#valueSpin:disabled { color: #9fb4c9; border-color: #1f3853; }
DashboardTab QDoubleSpinBox#valueSpin:focus { border-color: #35c6f4; }
DashboardTab QDoubleSpinBox#flightSpin { background: transparent; border: none; border-radius: 6px;
    padding: 1px 12px 1px 2px; color: #ffffff; font-size: 13.5px; font-weight: 700; }
DashboardTab QDoubleSpinBox#flightSpin::up-button, DashboardTab QDoubleSpinBox#flightSpin::down-button { width: 12px; }
DashboardTab QDoubleSpinBox#flightSpin:disabled { color: #9fb4c9; }
DashboardTab QDoubleSpinBox#flightSpin:focus { background: #0a1828; border: 1px solid #35c6f4; }
DashboardTab QPushButton { background: #12263d; border: 1px solid #2a4a6b; border-radius: 8px; color: #e8f0f8;
    padding: 6px 14px; font-weight: 600; }
DashboardTab QPushButton:hover { border-color: #35c6f4; color: #ffffff; }
DashboardTab QPushButton:disabled { color: #5d7893; border-color: #1f3853; }
DashboardTab QPushButton[compact="true"] { padding: 3px 10px; min-height: 20px; border-radius: 7px; font-size: 12px; }
DashboardTab QPushButton[tone="go"] { border-color: #1d7f4b; color: #8bf0b4; background: #0f2c20; }
DashboardTab QPushButton[seg="true"] { border-radius: 0; padding: 3px 8px; min-height: 20px; font-size: 12px;
    color: #8fa6bd; background: #0a1828; border-left: none; }
DashboardTab QPushButton[seg="true"]:checked { background: #2f8cff; color: #ffffff; }
DashboardTab QSlider::groove:horizontal { height: 4px; background: #25405d; border-radius: 2px; }
DashboardTab QSlider::sub-page:horizontal { background: #2f8cff; border-radius: 2px; }
DashboardTab QSlider::handle:horizontal { background: #ffffff; width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; }
DashboardTab QFrame#gaugeCard { background: #0b1a2b; border: 1px solid #1b3550; border-radius: 9px; }
DashboardTab QFrame#gaugeCard[state="manual"] { border-color: #8a6a1e; }
DashboardTab QFrame#gaugeCard[state="fault"] { border: 1px solid #ef4444; background: #1a1018; }
DashboardTab QLabel#gaugeTitle { font-weight: 700; font-size: 12.5px; color: #cfe0f1; }
DashboardTab QLabel#gaugeStatus { color: #ffcb6b; font-size: 10.5px; }
"""

_EXTRA = """
DashboardTab QAbstractItemView { background: #0f2034; color: #e8f0f8; selection-background-color: #2f8cff;
    selection-color: #ffffff; border: 1px solid #2a4a6b; outline: none; }
DashboardTab QComboBox { background: #0a1828; border: 1px solid #2a4a6b; border-radius: 6px; color: #e8f0f8;
    padding: 2px 8px; min-height: 22px; }
DashboardTab QComboBox:disabled { color: #5d7893; border-color: #1f3853; }
DashboardTab QComboBox QAbstractItemView { background: #0f2034; color: #e8f0f8; selection-background-color: #2f8cff;
    border: 1px solid #2a4a6b; }
DashboardTab QLineEdit { background: #0a1828; border: 1px solid #2a4a6b; border-radius: 6px; color: #e8f0f8;
    padding: 2px 8px; min-height: 22px; selection-background-color: #2f8cff; }
DashboardTab QLineEdit:focus { border-color: #35c6f4; }
DashboardTab QLineEdit:disabled { color: #5d7893; }
DashboardTab QCheckBox { color: #cfe0f1; spacing: 6px; }
DashboardTab QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #2a4a6b; border-radius: 4px;
    background: #0a1828; }
DashboardTab QCheckBox::indicator:checked { background: #2f8cff; border-color: #2f8cff; }
DashboardTab QSpinBox, DashboardTab QDoubleSpinBox { background: #0a1828; border: 1px solid #2a4a6b;
    border-radius: 6px; color: #ffffff; padding: 1px 16px 1px 8px; min-height: 20px; }
DashboardTab QSpinBox:disabled, DashboardTab QDoubleSpinBox:disabled { color: #9fb4c9; border-color: #1f3853; }
DashboardTab QTableView, DashboardTab QTableWidget { background: #0b1a2b; alternate-background-color: #0e2034;
    color: #e8f0f8; gridline-color: #16304a; border: 1px solid #1b3550; border-radius: 8px;
    selection-background-color: #1d4f7f; selection-color: #ffffff; }
DashboardTab QTableView::item, DashboardTab QTableWidget::item { padding: 2px 6px; border: none; }
DashboardTab QHeaderView { background: transparent; }
DashboardTab QHeaderView::section { background: #12263d; color: #8fa6bd; border: none; border-bottom: 1px solid #1f3853;
    border-right: 1px solid #16304a; padding: 4px 8px; font-size: 11px; font-weight: 700; }
DashboardTab QTabWidget::pane { border: none; background: transparent; top: 0px; }
DashboardTab QTabBar::tab { background: transparent; color: #8fa6bd; padding: 5px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }
DashboardTab QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #35c6f4; }
DashboardTab QTabBar::tab:hover:!selected { color: #e8f0f8; }
DashboardTab QListWidget { background: #0b1a2b; color: #e8f0f8; border: 1px solid #1b3550; border-radius: 8px; }
DashboardTab QListWidget::item:selected { background: #1d4f7f; }
DashboardTab QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
DashboardTab QScrollBar::handle:vertical { background: #2a4a6b; border-radius: 5px; min-height: 24px; }
DashboardTab QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
DashboardTab QScrollBar::handle:horizontal { background: #2a4a6b; border-radius: 5px; min-width: 24px; }
DashboardTab QScrollBar::add-line, DashboardTab QScrollBar::sub-line { width: 0; height: 0; }
DashboardTab QSplitter::handle { background: transparent; }
DashboardTab QFrame#stripBar { background: #0f2034; border: 1px solid #1f3853; border-radius: 10px; }
DashboardTab QLabel#statusDot[state="ok"] { color: #22c55e; font-size: 14px; }
DashboardTab QLabel#statusDot[state="warn"] { color: #f59e0b; font-size: 14px; }
DashboardTab QLabel#statusDot[state="bad"] { color: #ef4444; font-size: 14px; }
DashboardTab QLabel#statChip { background: #0a1828; border: 1px solid #1f3853; border-radius: 10px; padding: 2px 10px;
    color: #cfe0f1; font-size: 11.5px; }
DashboardTab QLabel#chipDim { background: #0a1828; border: 1px solid #1f3853; border-radius: 10px; padding: 2px 10px;
    color: #8fa6bd; font-size: 11.5px; }
DashboardTab QPushButton[tone="rec"] { border-color: #8c2b2b; color: #ff9a9a; background: #3a1313; }
DashboardTab QPushButton[tone="rec"]:checked { background: #7a1f1f; color: #ffffff; }
DashboardTab QGroupBox { background: transparent; border: 1px solid #1f3853; border-radius: 8px; margin-top: 10px;
    padding: 8px; color: #8fa6bd; font-weight: 700; }
DashboardTab QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #cfe0f1; }
"""


def dark_qss(root_id: str = "dashBody") -> str:
    q = _BASE + _EXTRA
    return q.replace("DashboardTab {", f"QWidget#{root_id} {{").replace("DashboardTab ", f"QWidget#{root_id} ")
