"""Modas görünümü için QSS (renkler ``app/theme.py`` token'larından gelir; burada renk sabiti yazılmaz)."""

from app import theme

MODAS_QSS = theme.paint("""
/* ---- Ribbon ---------------------------------------------------------------------------------- */
QFrame#modasRibbon { background: @@MODAS_RIBBON_BG@@; border-bottom: 1px solid @@MODAS_RIBBON_LINE@@; }
QFrame#modasTabRow { background: @@MODAS_RIBBON_TABBAR@@; border: none; }
QTabBar#modasRibbonTabs { background: transparent; }
QTabBar#modasRibbonTabs::tab { background: transparent; color: @@INK@@; padding: 3px 14px; margin: 2px 1px 0 1px;
    border: 1px solid transparent; border-bottom: none; font-size: 12px; }
QTabBar#modasRibbonTabs::tab:hover { background: @@MODAS_RIBBON_HOVER@@; border-color: @@MODAS_ORANGE_LINE@@; }
QTabBar#modasRibbonTabs::tab:selected { background: @@MODAS_RIBBON_BG@@; border-color: @@MODAS_RIBBON_LINE@@; font-weight: 600; }
QLabel#modasAppBadge { background: @@MODAS_ORANGE@@; color: @@INK@@; border: 2px solid @@MODAS_ORANGE_LINE@@;
    border-radius: 12px; font-size: 13px; font-weight: 800; }
QLabel#modasTitle { color: @@MODAS_GROUP_LABEL@@; font-size: 12px; font-weight: 600; }
QFrame#modasGroup { background: transparent; border: none; border-right: 1px solid @@MODAS_RIBBON_LINE@@; }
QLabel#modasGroupLabel { color: @@MODAS_GROUP_LABEL@@; font-size: 11px; }
QToolButton[modas="big"] { background: transparent; border: 1px solid transparent; border-radius: 3px; color: @@INK@@;
    font-size: 11px; padding: 2px 6px; min-width: 46px; }
QToolButton[modas="big"]:hover { background: @@MODAS_RIBBON_HOVER@@; border-color: @@MODAS_ORANGE_LINE@@; }
QToolButton[modas="big"]:checked, QToolButton[modas="big"]:pressed { background: @@MODAS_ORANGE@@; border-color: @@MODAS_ORANGE_LINE@@; }
QToolButton[modas="big"]:disabled { color: @@DIM@@; }
QToolButton[modas="big"][alert="true"] { color: @@DANGER@@; font-weight: 700; }
QToolButton[modas="small"] { background: transparent; border: 1px solid transparent; border-radius: 3px; color: @@INK@@;
    font-size: 11px; padding: 1px 6px; text-align: left; }
QToolButton[modas="small"]:hover { background: @@MODAS_RIBBON_HOVER@@; border-color: @@MODAS_ORANGE_LINE@@; }
QToolButton[modas="small"]:disabled { color: @@DIM@@; }
QLabel#modasLed { border-radius: 8px; min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; border: 1px solid @@INK_2@@; }
QLabel#modasLed[state="on"] { background: @@MODAS_LED_GREEN@@; }
QLabel#modasLed[state="off"] { background: @@MODAS_LED_RED@@; }
QLabel#modasLed[state="wait"] { background: @@MODAS_ORANGE@@; }
QLabel#modasLedText { color: @@INK@@; font-size: 11px; font-weight: 700; }
QLabel#modasDiff { color: @@INK@@; font-size: 11px; }
QLabel#modasDiff[diff="true"] { color: @@DANGER@@; font-weight: 700; }
QLineEdit#modasField { background: @@SURFACE@@; border: 1px solid @@MODAS_RIBBON_LINE@@; color: @@INK@@; font-size: 11px;
    padding: 0 4px; min-height: 17px; max-height: 17px; }
QLabel#modasFieldLabel { color: @@INK@@; font-size: 11px; }
QFrame#modasMotorGroup { background: transparent; border: none; border-left: 1px solid @@MODAS_RIBBON_LINE@@; }
QFrame#modasMotorGroup QLabel { background: transparent; color: @@INK@@; }

/* ---- Çalışma alanı ------------------------------------------------------------------------- */
QMdiArea#modasMdi { background: @@MODAS_WORKSPACE@@; border: none; }
QTabBar#modasSheetTabs { background: transparent; }
QTabBar#modasSheetTabs::tab { background: @@MODAS_RIBBON_TABBAR@@; color: @@INK@@; padding: 2px 10px; margin-right: 1px;
    border: 1px solid @@MODAS_RIBBON_LINE@@; border-top: none; font-size: 11px; }
QTabBar#modasSheetTabs::tab:selected { background: @@SURFACE@@; font-weight: 700; }
QFrame#modasSheetBar { background: @@MODAS_RIBBON_BG@@; border-top: 1px solid @@MODAS_RIBBON_LINE@@; }
QFrame#modasVarPanel { background: @@MODAS_RIBBON_BG@@; border-left: 1px solid @@MODAS_RIBBON_LINE@@; }
QLabel#modasPanelTitle { color: @@MODAS_GROUP_LABEL@@; font-size: 11px; font-weight: 700; }
QComboBox#modasFilter, QLineEdit#modasSearch { background: @@SURFACE@@; border: 1px solid @@MODAS_RIBBON_LINE@@;
    color: @@INK@@; font-size: 11px; padding: 0 4px; min-height: 18px; }
QTableWidget#modasVarList { background: @@SURFACE@@; alternate-background-color: @@MODAS_TABLE_ALT@@;
    border: 1px solid @@MODAS_RIBBON_LINE@@; font-size: 11px; gridline-color: @@LINE_SOFT@@;
    selection-background-color: @@MODAS_LIST_SEL@@; selection-color: @@INK@@; }
QTableWidget#modasVarList QHeaderView::section { background: @@MODAS_TABLE_HEAD@@; color: @@INK@@; border: 1px solid @@MODAS_RIBBON_LINE@@;
    padding: 1px 4px; font-size: 11px; font-weight: 600; }
QFrame#modasLogPanel { background: @@SURFACE@@; border-top: 1px solid @@MODAS_RIBBON_LINE@@; }
QListWidget#modasLog { background: @@SURFACE@@; border: none; font-size: 11px; font-family: @@FONT_MONO@@; }
QListWidget#modasLog::item { padding: 0 2px; }

/* ---- İç pencereler -------------------------------------------------------------------------- */
QWidget#modasWinBody { background: @@MODAS_WIN_TITLE_BG@@; }
QLabel#modasWinLabel { color: @@INK@@; font-size: 11px; background: transparent; }
QLabel#modasWinUnit { color: @@INK@@; font-size: 11px; background: transparent; }
QLineEdit#modasValue { border: 1px solid @@MODAS_WIN_LINE@@; font-size: 11px; font-weight: 600; padding: 0 3px;
    min-height: 17px; color: @@INK@@; }
QLineEdit#modasValue[kind="cal"] { background: @@MODAS_CAL_BG@@; }
QLineEdit#modasValue[kind="meas"] { background: @@MODAS_MEAS_BG@@; color: @@INK_2@@; }
QLineEdit#modasValue[pending="true"] { background: @@PENDING_BG@@; }
QLineEdit#modasValue[bad="true"] { background: @@DANGER_BG@@; color: @@DANGER@@; }
QTableWidget#modasTable { background: @@MODAS_CAL_BG@@; gridline-color: @@MODAS_WIN_LINE@@; font-size: 11px;
    border: 1px solid @@MODAS_WIN_LINE@@; selection-background-color: @@MODAS_LIST_SEL@@; selection-color: @@INK@@; }
QTableWidget#modasTable QHeaderView::section { background: @@MODAS_TABLE_HEAD@@; color: @@INK@@; border: 1px solid @@MODAS_WIN_LINE@@;
    padding: 0 4px; font-size: 11px; }
QLabel#modasTableInfo { color: @@INK@@; font-size: 11px; background: transparent; }
""")
