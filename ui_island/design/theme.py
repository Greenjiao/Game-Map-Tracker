"""Theme constants for the island overlay UI."""

import os
import tempfile

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget


def _write_arrow_asset(name: str, svg: str) -> str:
    asset_dir = os.path.join(tempfile.gettempdir(), "gmt_island_assets")
    os.makedirs(asset_dir, exist_ok=True)
    path = os.path.join(asset_dir, name)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
    except OSError:
        pass
    return path.replace("\\", "/")


_ARROW_UP_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='5' viewBox='0 0 8 5'>"
    "<polygon points='4,0 8,5 0,5' fill='#f2f2f7'/></svg>"
)
_ARROW_DOWN_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='5' viewBox='0 0 8 5'>"
    "<polygon points='0,0 8,0 4,5' fill='#f2f2f7'/></svg>"
)
_ARROW_UP_DISABLED_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='5' viewBox='0 0 8 5'>"
    "<polygon points='4,0 8,5 0,5' fill='#404040'/></svg>"
)
_ARROW_DOWN_DISABLED_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='5' viewBox='0 0 8 5'>"
    "<polygon points='0,0 8,0 4,5' fill='#404040'/></svg>"
)

ARROW_UP_PATH = _write_arrow_asset("spin_arrow_up.svg", _ARROW_UP_SVG)
ARROW_DOWN_PATH = _write_arrow_asset("spin_arrow_down.svg", _ARROW_DOWN_SVG)
ARROW_UP_DISABLED_PATH = _write_arrow_asset("spin_arrow_up_disabled.svg", _ARROW_UP_DISABLED_SVG)
ARROW_DOWN_DISABLED_PATH = _write_arrow_asset("spin_arrow_down_disabled.svg", _ARROW_DOWN_DISABLED_SVG)

COLLAPSED_W = 280
COLLAPSED_H = 44
EXPANDED_W = 820
EXPANDED_H = 500
TOP_MARGIN = 0
ANIMATION_MS = 220
RECENT_ROUTES_MAX_HEIGHT = 100
TRACKED_ROUTES_MAX_HEIGHT = 96
ROUTES_LIST_MIN_HEIGHT = 60
ANNOTATION_PANEL_SCROLL_HEIGHT = 330
SIDEBAR_RAIL_WIDTH = 34
MAXIMIZED_SIDEBAR_WIDTH = 360  # 最大化时侧边栏的默认固定宽度
WINDOW_MIN_W = 300
WINDOW_MIN_H = 60
TRACKING_WINDOW_MIN_H = 100
SIDEBAR_MIN_EXPANDED_W = 760
SIDEBAR_MIN_EXPANDED_H = 60
COMPACT_ALERT_HEIGHT = 140
ALERT_ACTION_HEIGHT = 28
TRACK_JUMP_DETECT_THRESHOLD = 220
TRACK_JUMP_DETECT_LIMIT = 4
RECENT_ROUTE_ITEM_HEIGHT = 26
RECENT_ROUTE_CARD_PADDING = 24
TRACKED_ROUTE_CARD_PADDING = 52

BG = "rgba(18, 18, 20, 235)"
BG_HOVER = "rgba(28, 28, 30, 245)"
FG = "#f2f2f7"
FG_DIM = "#8e8e93"
ACCENT = "#0a84ff"
ACCENT_SOFT = "rgba(10, 132, 255, 0.16)"
BORDER = "rgba(255, 255, 255, 0.08)"
DOT_LOCKED = "#30d158"
DOT_INERTIAL = "#ffd60a"
DOT_LOST = "#ff453a"
DOT_SEARCHING = "#8e8e93"
RADIUS = 20

TOOLTIP_QSS = f"""
QToolTip {{
    background: rgba(28, 28, 30, 245);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 5px;
    padding: 1px 6px;
    margin: 0px;
    font-size: 11px;
}}
"""

COLOR_DIALOG_QSS = f"""
QColorDialog {{
    background: rgb(28, 28, 30);
    color: {FG};
}}
QColorDialog QLabel {{
    color: {FG};
    font-size: 11px;
}}
QColorDialog QFrame,
QColorDialog QWidget {{
    background: rgb(28, 28, 30);
    color: {FG};
}}
QColorDialog QLineEdit {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 7px;
    padding: 4px 6px;
    min-width: 78px;
    max-width: 96px;
}}
QColorDialog QSpinBox {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 7px;
    padding: 3px 4px;
    min-width: 44px;
    max-width: 56px;
}}
QColorDialog QPushButton {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border: none;
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
}}
QColorDialog QPushButton:hover {{
    background: rgba(255, 255, 255, 0.20);
}}
QColorDialog QPushButton:pressed {{
    background: rgba(255, 255, 255, 0.28);
}}
"""


class _ToolTipTranslucencyFilter(QObject):
    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Show and isinstance(obj, QWidget):
            if obj.windowType() == Qt.ToolTip:
                obj.setAttribute(Qt.WA_TranslucentBackground, True)
        return False


_TOOLTIP_FILTER: _ToolTipTranslucencyFilter | None = None


def ensure_tooltip_style() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return

    app = QApplication.instance()
    if app is None:
        return

    marker = "_game_map_tooltip_qss_applied"
    if app.property(marker):
        return

    base = app.styleSheet().rstrip()
    if TOOLTIP_QSS not in base:
        app.setStyleSheet(f"{base}\n{TOOLTIP_QSS}".strip())

    global _TOOLTIP_FILTER
    if _TOOLTIP_FILTER is None:
        _TOOLTIP_FILTER = _ToolTipTranslucencyFilter()
        app.installEventFilter(_TOOLTIP_FILTER)

    app.setProperty(marker, True)

ISLAND_QSS = f"""
QWidget#IslandRoot {{
    background: {BG};
    border-radius: {RADIUS}px;
}}
QWidget#IslandRoot:hover {{
    background: {BG_HOVER};
}}
QLabel {{
    color: {FG};
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}}
QLabel#CoordLabel {{
    font-size: 13px;
    font-weight: 600;
}}
QLabel#StatLabel {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#TitleLabel {{
    font-size: 12px;
    color: {FG_DIM};
    font-weight: 600;
}}
QLabel#BodyLabel {{
    font-size: 12px;
    color: {FG};
}}
QLabel#DimLabel {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#FieldLabel {{
    font-size: 12px;
    color: {FG};
    font-weight: 600;
}}
QLabel#ErrorLabel {{
    font-size: 11px;
    color: #e06e6e;
}}
QLabel#ToastIcon {{
    color: {DOT_LOCKED};
    font-size: 16px;
    font-weight: 700;
}}
QLabel#EmptyHint {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#MapHint {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#TrackedGuideHint {{
    color: {FG_DIM};
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 7px;
    padding: 0px 5px;
    margin: 0px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#StateHint {{
    font-size: 11px;
    color: {FG_DIM};
    padding: 4px 8px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#AlertCard {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#AlertMessage {{
    font-size: 18px;
    font-weight: 700;
    color: {FG};
}}
QLabel#SidebarRailLabel {{
    font-size: 10px;
    color: {FG_DIM};
    font-weight: 600;
}}
QFrame#PanelCard {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#SidebarRail {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#SidebarOverlay {{
    background: rgba(18, 18, 20, 245);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#RoutesScrollInner {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#RouteSectionBody {{
    background: transparent;
}}
QPushButton {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border: none;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
}}
QPushButton:hover {{
    background: rgba(255, 255, 255, 0.20);
}}
QPushButton:pressed {{
    background: rgba(255, 255, 255, 0.28);
}}
QPushButton[headerButton="true"] {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border: 1px solid transparent;
    min-height: 28px;
    max-height: 28px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 8px;
}}
QPushButton[headerButton="true"][compact="true"] {{
    min-height: 24px;
    max-height: 24px;
    padding: 2px 8px;
    font-size: 10px;
    border-radius: 7px;
}}
QPushButton[headerButton="true"][routePanelHeaderButton="true"] {{
    min-height: {RECENT_ROUTE_ITEM_HEIGHT - 6}px;
    max-height: {RECENT_ROUTE_ITEM_HEIGHT - 6}px;
    padding: 2px 8px;
    border-radius: 7px;
}}
QPushButton[headerButton="true"]:hover {{
    background: rgba(255, 255, 255, 0.18);
}}
QPushButton[headerButton="true"]:pressed {{
    background: rgba(255, 255, 255, 0.28);
}}
QPushButton[headerButton="true"]:disabled {{
    background: rgba(255, 255, 255, 0.06);
    color: rgba(242, 242, 247, 0.45);
    border-color: rgba(255, 255, 255, 0.04);
}}
QPushButton[headerButton="true"][iconRole="lock"]:checked {{
    background: {ACCENT};
    color: white;
    border-color: {ACCENT};
}}
QPushButton[headerButton="true"][iconRole="lock"]:checked:hover {{
    background: #2590ff;
    border-color: #2590ff;
}}
QPushButton[headerButton="true"][iconRole="lock"]:checked:pressed {{
    background: #0077e6;
    border-color: #0077e6;
}}
QPushButton#HeaderWindowButton,
QPushButton#HeaderActionButton,
QPushButton#TopSidebarToggle {{
    min-height: 28px;
    max-height: 28px;
    border-radius: 8px;
}}
QPushButton#WindowControl {{
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 0px;
    font-size: 16px;
}}
QPushButton#WindowControl:checked {{
    color: #ffffff;
    background: rgba(74, 144, 226, 0.92);
    border-color: rgba(160, 205, 255, 0.42);
}}
QPushButton#HeaderWindowButton {{
    min-width: 28px;
    max-width: 28px;
    padding: 0px;
    font-weight: 700;
}}
QPushButton#HeaderWindowButton[routePanelIconButton="true"] {{
    min-width: {RECENT_ROUTE_ITEM_HEIGHT}px;
    max-width: {RECENT_ROUTE_ITEM_HEIGHT}px;
    min-height: {RECENT_ROUTE_ITEM_HEIGHT}px;
    max-height: {RECENT_ROUTE_ITEM_HEIGHT}px;
    padding: 0px;
    border-radius: 7px;
    font-size: 12px;
}}
QPushButton#HeaderActionButton,
QPushButton#TopSidebarToggle {{
    padding: 0px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#TrackedRoutesToggleButton {{
    min-height: 18px;
    max-height: 18px;
    border-radius: 6px;
    padding: 0px 5px;
    font-size: 10px;
    font-weight: 600;
}}
QPushButton#HeaderWindowButton[iconRole="settings"] {{
    font-size: 14px;
}}
QPushButton#HeaderWindowButton[iconRole="minimize"] {{
    font-size: 16px;
}}
QPushButton#HeaderWindowButton[iconRole="maximize"] {{
    font-size: 15px;
}}
QPushButton#HeaderWindowButton[iconRole="close"] {{
    font-size: 18px;
}}
QPushButton#HeaderActionButton[headerIconOnly="true"],
QPushButton#TopSidebarToggle[headerIconOnly="true"] {{
    min-width: 34px;
    max-width: 34px;
    padding: 0px;
    font-size: 13px;
    font-weight: 700;
    text-align: center;
}}
QPushButton[iconRole="locate"][headerIconOnly="true"] {{
    font-size: 14px;
    font-weight: 700;
}}
QPushButton[iconRole="reset"][headerIconOnly="true"] {{
    font-size: 14px;
    font-weight: 700;
}}
QPushButton[iconRole="sidebar"][headerIconOnly="true"] {{
    color: #ffd60a;
    font-size: 13px;
    font-weight: 800;
}}
QPushButton[iconRole="terminate"][headerIconOnly="true"] {{
    color: {DOT_LOST};
    font-size: 12px;
    font-weight: 800;
}}
QPushButton#SidebarToggle {{
    min-width: 24px;
    padding: 8px 2px;
    font-size: 12px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.05);
}}
QPushButton#SidebarToggle:hover {{
    background: rgba(255, 255, 255, 0.12);
}}
QPushButton#AlertAction {{
    padding: 6px 12px;
    font-size: 11px;
}}
QToolButton#SectionHeader,
QPushButton#SectionHeader {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {FG};
    font-size: 10px;
    font-weight: 500;
    padding: 5px 8px;
    text-align: left;
}}
QToolButton#SectionHeader[compact="true"],
QPushButton#SectionHeader[compact="true"] {{
    border-radius: 8px;
    font-size: 10px;
    padding: 3px 8px;
}}
QPushButton#SectionHeader[sectionToggleOnly="true"] {{
    min-width: 26px;
    max-width: 26px;
    padding: 0px;
    text-align: center;
    font-size: 12px;
    font-weight: 700;
}}
QToolButton#SectionHeader:hover,
QPushButton#SectionHeader:hover {{
    background: rgba(255, 255, 255, 0.14);
}}
QWidget#AnnotationGroupSection[annotationLayer="pulled"] {{
    background: rgba(10, 132, 255, 0.075);
    border: 1px solid rgba(80, 170, 255, 0.28);
    border-radius: 10px;
}}
QWidget#AnnotationGroupSection[annotationLayer="custom"] {{
    background: rgba(255, 214, 10, 0.065);
    border: 1px solid rgba(255, 214, 10, 0.26);
    border-radius: 10px;
}}
QWidget#AnnotationGroupBody[annotationLayer="pulled"] {{
    background: rgba(10, 132, 255, 0.025);
    border: none;
}}
QWidget#AnnotationGroupBody[annotationLayer="custom"] {{
    background: rgba(255, 214, 10, 0.022);
    border: none;
}}
QPushButton#SectionHeader[annotationLayer="pulled"] {{
    background: rgba(10, 132, 255, 0.18);
    border-color: rgba(80, 170, 255, 0.42);
    border-left: 3px solid rgba(80, 170, 255, 0.88);
    color: #d9ecff;
    font-size: 11px;
    font-weight: 700;
    padding-left: 9px;
}}
QPushButton#SectionHeader[annotationLayer="custom"] {{
    background: rgba(255, 214, 10, 0.15);
    border-color: rgba(255, 214, 10, 0.36);
    border-left: 3px solid rgba(255, 214, 10, 0.82);
    color: #fff5c2;
    font-size: 11px;
    font-weight: 700;
    padding-left: 9px;
}}
QPushButton#SectionHeader[annotationLayer="pulled"]:hover {{
    background: rgba(10, 132, 255, 0.25);
    border-color: rgba(110, 190, 255, 0.54);
}}
QPushButton#SectionHeader[annotationLayer="custom"]:hover {{
    background: rgba(255, 214, 10, 0.22);
    border-color: rgba(255, 224, 80, 0.50);
}}
QPushButton#SectionHeaderBatchButton,
QPushButton#SectionHeaderAddButton {{
    background: transparent;
    color: {FG};
    border: none;
    border-left: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 0px;
    padding: 0px;
    margin: 0px;
}}
QPushButton#SectionHeaderBatchButton {{
    min-width: 42px;
    max-width: 42px;
    font-size: 10px;
    font-weight: 600;
}}
QPushButton#SectionHeaderAddButton {{
    min-width: 30px;
    max-width: 30px;
    font-size: 14px;
    font-weight: 700;
}}
QPushButton#SectionHeaderBatchButton:hover,
QPushButton#SectionHeaderAddButton:hover {{
    background: rgba(255, 255, 255, 0.10);
}}
QPushButton#SectionHeaderBatchButton:pressed,
QPushButton#SectionHeaderAddButton:pressed {{
    background: rgba(255, 255, 255, 0.16);
}}
QLineEdit {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 7px 10px;
    font-size: 11px;
    selection-background-color: {ACCENT};
}}
QLineEdit[routePanelInput="true"] {{
    min-height: {RECENT_ROUTE_ITEM_HEIGHT - 8}px;
    max-height: {RECENT_ROUTE_ITEM_HEIGHT - 8}px;
    border-radius: 7px;
    padding: 3px 8px;
}}
QLineEdit:focus {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QSpinBox, QDoubleSpinBox {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px 8px;
    font-size: 11px;
    selection-background-color: {ACCENT};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: rgba(255, 255, 255, 0.35);
    background: rgba(255, 255, 255, 0.04);
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    background: rgba(255, 255, 255, 0.06);
    border: none;
    width: 16px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 9px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 9px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: rgba(255, 255, 255, 0.16);
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: rgba(255, 255, 255, 0.24);
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{ARROW_UP_PATH}");
    width: 8px;
    height: 5px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{ARROW_DOWN_PATH}");
    width: 8px;
    height: 5px;
}}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off,
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:off {{
    image: url("{ARROW_UP_DISABLED_PATH}");
}}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off,
QDoubleSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:off {{
    image: url("{ARROW_DOWN_DISABLED_PATH}");
}}
QSlider[compactSlider="true"] {{
    min-height: 18px;
    max-height: 18px;
    background: transparent;
}}
QSlider[compactSlider="true"]::groove:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.12);
}}
QSlider[compactSlider="true"]::sub-page:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: rgba(10, 132, 255, 0.70);
}}
QSlider[compactSlider="true"]::add-page:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.10);
}}
QSlider[compactSlider="true"]::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
    background: {FG};
    border: 1px solid rgba(255, 255, 255, 0.35);
}}
QSlider[compactSlider="true"]::handle:horizontal:hover {{
    background: #ffffff;
    border-color: rgba(10, 132, 255, 0.85);
}}
QSplitter#RouteNotesSplitter {{
    background: transparent;
}}
QSplitter#RouteNotesSplitter::handle:horizontal {{
    width: 8px;
    margin: 28px 1px 0px 1px;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.06);
}}
QSplitter#RouteNotesSplitter::handle:horizontal:hover {{
    background: rgba(10, 132, 255, 0.32);
}}
QSizeGrip#RouteNotesSizeGrip {{
    width: 16px;
    height: 16px;
    background: transparent;
}}
QComboBox {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px 28px 4px 10px;
    font-size: 11px;
    selection-background-color: {ACCENT};
    min-height: 18px;
}}
QComboBox:hover {{
    border: 1px solid rgba(255, 255, 255, 0.22);
}}
QComboBox:focus,
QComboBox:on {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QComboBox:disabled {{
    color: {FG_DIM};
    background: rgba(255, 255, 255, 0.04);
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background: rgba(28, 28, 30, 245);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 4px;
    outline: 0;
    selection-background-color: {ACCENT};
    selection-color: white;
}}
QComboBox QAbstractItemView::item {{
    padding: 3px 10px;
    border-radius: 6px;
    min-height: 18px;
}}
QComboBox QAbstractItemView::item:hover {{
    background: rgba(255, 255, 255, 0.10);
}}
QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT};
    color: white;
}}
QPushButton#SettingsTabButton {{
    background: transparent;
    color: {FG_DIM};
    border: none;
    border-radius: 7px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 600;
    min-height: 22px;
}}
QPushButton#SettingsTabButton:hover {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
}}
QPushButton#SettingsTabButton[selected="true"] {{
    background: rgba(255, 255, 255, 0.14);
    color: {FG};
}}
QLabel#SettingsToolGroupLabel {{
    color: {FG_DIM};
    font-size: 11px;
    font-weight: 600;
    padding: 1px 0px 0px 1px;
}}
QPushButton[settingsTopToolButton="true"] {{
    background: rgba(255, 255, 255, 0.10);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton[settingsTopToolButton="true"]:hover {{
    background: {ACCENT_SOFT};
    border-color: rgba(10, 132, 255, 0.48);
}}
QPushButton[settingsTopToolButton="true"]:pressed {{
    background: rgba(10, 132, 255, 0.22);
    border-color: rgba(10, 132, 255, 0.66);
}}
QPushButton[settingsToolButton="true"] {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 2px 7px;
    font-size: 11px;
    min-height: 26px;
}}
QPushButton[settingsToolButton="true"] QLabel#SettingsToolButtonIcon,
QPushButton[settingsToolButton="true"] QLabel#SettingsToolButtonText {{
    background: transparent;
    color: {FG};
    font-size: 11px;
}}
QPushButton[settingsToolButton="true"] QLabel#SettingsToolButtonText {{
    font-weight: 500;
}}
QPushButton[settingsToolButton="true"]:hover {{
    background: {ACCENT_SOFT};
    border-color: rgba(10, 132, 255, 0.58);
}}
QPushButton[settingsToolButton="true"]:pressed {{
    background: rgba(10, 132, 255, 0.25);
    border-color: rgba(10, 132, 255, 0.72);
}}
QPushButton[settingsConversionButton="true"] {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border-color: rgba(255, 255, 255, 0.08);
    font-weight: 600;
}}
QPushButton[settingsConversionButton="true"]:hover {{
    background: {ACCENT_SOFT};
    border-color: rgba(10, 132, 255, 0.58);
    color: {FG};
}}
QPushButton[settingsConversionButton="true"]:pressed {{
    background: rgba(10, 132, 255, 0.25);
    border-color: rgba(10, 132, 255, 0.72);
}}
QKeySequenceEdit {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 11px;
    selection-background-color: {ACCENT};
}}
QKeySequenceEdit:focus {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QPushButton#SettingsHotkeyEdit {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 11px;
    text-align: center;
}}
QPushButton#SettingsHotkeyEdit:hover {{
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(10, 132, 255, 0.45);
}}
QPushButton#SettingsHotkeyEdit:focus {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QPlainTextEdit {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 7px 10px;
    font-size: 11px;
    selection-background-color: {ACCENT};
}}
QPlainTextEdit:focus {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QCheckBox {{
    color: {FG};
    background: transparent;
    border-radius: 8px;
    font-size: 11px;
    spacing: 6px;
    padding: 2px 6px;
}}
QCheckBox:hover {{
    background: rgba(255, 255, 255, 0.08);
}}
QCheckBox:checked {{
    background: rgba(255, 255, 255, 0.12);
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.15);
    border: 1px solid rgba(255, 255, 255, 0.25);
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}
QWidget[trackedRouteItem="true"] {{
    background: transparent;
    border-radius: 8px;
}}
QWidget[trackedRouteItem="true"]:hover {{
    background: rgba(255, 255, 255, 0.08);
}}
QWidget[trackedRouteItem="true"][checked="true"] {{
    background: rgba(255, 255, 255, 0.12);
}}
QWidget[trackedRouteItem="true"] QCheckBox {{
    background: transparent;
}}
QWidget[trackedRouteItem="true"] QCheckBox:hover {{
    background: transparent;
}}
QWidget[trackedRouteItem="true"] QCheckBox:checked {{
    background: transparent;
}}
QPushButton[trackedRouteAddButton="true"] {{
    background: transparent;
    border: none;
    min-width: 26px;
    max-width: 26px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    margin: 0px;
    color: {FG};
    font-size: 15px;
    font-weight: 700;
    border-radius: 7px;
}}
QPushButton[trackedRouteAddButton="true"]:hover {{
    background: rgba(255, 255, 255, 0.12);
}}
QPushButton[trackedRouteAddButton="true"]:pressed {{
    background: rgba(255, 255, 255, 0.18);
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea#SidebarOverlayScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#SidebarOverlayScroll > QWidget {{
    background: transparent;
}}
QScrollArea#SidebarOverlayScroll > QWidget > QWidget {{
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.42);
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{
    background: rgba(255, 255, 255, 0.58);
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    height: 0px;
    width: 0px;
    background: transparent;
    border: none;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QMenu {{
    background: rgba(28, 28, 30, 245);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 6px 0px;
}}
QMenu::item {{
    padding: 6px 16px;
    margin: 2px 6px;
    border-radius: 7px;
}}
QMenu::item:selected {{
    background: rgba(255, 255, 255, 0.12);
}}
QMenu::separator {{
    height: 1px;
    margin: 6px 10px;
    background: rgba(255, 255, 255, 0.08);
}}
QMenu#RouteListContextMenu,
QMenu#MapNodeContextMenu,
QMenu#MapBlankContextMenu,
QMenu#MapAnnotationContextMenu {{
    background: rgb(28, 28, 30);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 3px 0px;
}}
QMenu#RouteListContextMenu::item,
QMenu#MapNodeContextMenu::item,
QMenu#MapBlankContextMenu::item,
QMenu#MapAnnotationContextMenu::item {{
    padding: 4px 12px;
    margin: 1px 4px;
    border-radius: 5px;
}}
QMenu#RouteListContextMenu::separator,
QMenu#MapNodeContextMenu::separator,
QMenu#MapBlankContextMenu::separator,
QMenu#MapAnnotationContextMenu::separator {{
    margin: 4px 8px;
}}
QMenu#AnnotationContextMenu {{
    background: rgb(28, 28, 30);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 5px 0px;
}}
QMenu#AnnotationContextMenu::item {{
    padding: 5px 14px;
    margin: 2px 5px;
    border-radius: 7px;
}}
QMenu#AnnotationContextMenu::separator {{
    margin: 5px 9px;
}}
QFrame#RouteDrawingToolbar {{
    background: rgba(28, 28, 30, 236);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 8px;
}}
QFrame#RouteDrawingToolbar QPushButton {{
    min-height: 26px;
    padding: 3px 10px;
    border-radius: 5px;
    color: {FG};
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.10);
}}
QFrame#RouteDrawingToolbar QPushButton:hover {{
    background: rgba(255, 255, 255, 0.15);
}}
QFrame#RouteDrawingToolbar QPushButton:checked {{
    background: rgba(74, 144, 226, 0.92);
    color: #ffffff;
}}
QFrame#RouteDrawingToolbar QPushButton#RouteNotesNodeIcon {{
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 1px;
    border-radius: 7px;
}}
QFrame#RouteDrawingToolbar QCheckBox {{
    spacing: 6px;
    color: {FG};
    font-size: 12px;
}}
QFrame#RouteDrawingToolbarSeparator {{
    color: rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.10);
    max-height: 1px;
    border: none;
}}
QPushButton#RouteDrawingHelpButton {{
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    padding: 0px;
    border-radius: 10px;
    color: {FG};
    background: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.16);
    font-weight: 700;
}}
QPushButton#RouteDrawingHelpButton:hover {{
    background: rgba(255, 255, 255, 0.18);
}}
QPushButton#AnnotationToggleButton {{
    min-height: 22px;
    padding: 2px 9px;
    border-radius: 8px;
    color: {FG};
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.10);
}}
QPushButton#AnnotationToggleButton:hover,
QPushButton#AnnotationToggleButton:checked {{
    background: rgba(255, 255, 255, 0.16);
}}
QPushButton#AnnotationToggleButton:checked {{
    color: #ffffff;
    background: rgba(74, 144, 226, 0.92);
    border-color: rgba(160, 205, 255, 0.42);
}}
QFrame#AnnotationPanel {{
    background: transparent;
    border: none;
}}
QFrame#AnnotationPanelSurface {{
    background: rgba(22, 24, 28, 250);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px;
}}
QScrollArea#AnnotationPanelScroll,
QWidget#AnnotationPanelInner {{
    background: transparent;
    border: none;
}}
QLabel#AnnotationPanelTitle {{
    color: {FG};
    font-weight: 700;
    font-size: 13px;
}}
QLabel#AnnotationPanelHint {{
    color: {FG_DIM};
    font-size: 10px;
}}
QLabel#AnnotationPanelMessage {{
    color: {FG_DIM};
    font-size: 11px;
}}
QFrame#RouteNotesStatsPanel {{
    background: rgba(255, 255, 255, 0.055);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
}}
QLabel#RouteNotesStatChip {{
    color: {FG};
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    padding: 3px 7px;
    font-size: 11px;
}}
QWidget#RouteNotesNodeRow {{
    background: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.045);
    border-radius: 7px;
}}
QWidget#RouteNotesNodeRow:hover {{
    background: rgba(255, 255, 255, 0.075);
}}
QFrame#RouteNotesDropIndicator {{
    background: rgba(255, 214, 10, 0.95);
    border-radius: 1px;
}}
QFrame#RouteNotesDragPreview {{
    background: rgba(32, 32, 36, 0.96);
    border: 1px solid rgba(255, 214, 10, 0.60);
    border-radius: 7px;
}}
QLabel#RouteNotesDragPreviewName {{
    color: {FG};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#RouteNotesDragPreviewOrder {{
    color: {FG_DIM};
    font-size: 10px;
}}
QPushButton#RouteNotesNodeIcon {{
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 1px;
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
}}
QPushButton#RouteNotesNodeIcon:hover {{
    background: rgba(74, 144, 226, 0.22);
    border-color: rgba(120, 180, 255, 0.35);
}}
QLineEdit#RouteNotesNodeName {{
    color: {FG};
    font-size: 11px;
}}
QLineEdit#RouteNotesNodeOrderInput {{
    padding-left: 2px;
    padding-right: 2px;
    font-size: 10px;
}}
QPushButton#AnnotationPanelBulkButton {{
    min-height: 18px;
    padding: 0px 6px;
    border-radius: 8px;
    color: {FG};
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    font-size: 11px;
}}
QPushButton#AnnotationPanelBulkButton:hover {{
    background: rgba(74, 144, 226, 0.22);
    border-color: rgba(120, 180, 255, 0.35);
}}
QPushButton#AnnotationPanelClose {{
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    padding: 0px;
    border-radius: 8px;
    color: {FG};
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.10);
    font-size: 15px;
    font-weight: 700;
}}
QPushButton#AnnotationPanelClose:hover {{
    background: rgba(255, 255, 255, 0.16);
}}
QLabel#AnnotationGroupTitle {{
    color: {FG_DIM};
    font-size: 11px;
    font-weight: 700;
    padding: 4px 2px 0px 2px;
}}
QPushButton#AnnotationTypeRow {{
    min-height: 24px;
    padding: 2px 6px;
    border-radius: 7px;
    text-align: left;
    color: rgba(255, 255, 255, 0.48);
    background: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.045);
}}
QPushButton#AnnotationTypeRow[selected="true"] {{
    color: {FG};
    background: rgba(74, 144, 226, 0.20);
    border-color: rgba(120, 180, 255, 0.35);
}}
QPushButton#AnnotationTypeRow:hover {{
    background: rgba(255, 255, 255, 0.08);
}}
QWidget#AnnotationPresetRow {{
    background: transparent;
    border-radius: 7px;
}}
QPushButton#AnnotationPresetNameButton {{
    min-height: 24px;
    padding: 2px 7px;
    border-radius: 7px;
    text-align: left;
    color: {FG};
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(255, 255, 255, 0.055);
}}
QPushButton#AnnotationPresetNameButton[selected="true"] {{
    background: rgba(255, 214, 10, 0.18);
    border-color: rgba(255, 224, 80, 0.42);
    color: #fff5c2;
}}
QPushButton#AnnotationPresetNameButton:hover {{
    background: rgba(255, 255, 255, 0.09);
}}
QPushButton#AnnotationPresetActionButton {{
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    border-radius: 7px;
    color: {FG};
    background: rgba(255, 255, 255, 0.055);
    border: 1px solid rgba(255, 255, 255, 0.065);
    font-size: 10px;
    font-weight: 600;
}}
QPushButton#AnnotationPresetActionButton:hover {{
    background: rgba(255, 255, 255, 0.11);
}}
QPushButton#AnnotationPresetActionButton[danger="true"]:hover {{
    background: rgba(255, 69, 58, 0.22);
    border-color: rgba(255, 110, 100, 0.40);
}}
"""
