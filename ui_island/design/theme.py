"""Theme constants for the island overlay UI."""

COLLAPSED_W = 280
COLLAPSED_H = 44
EXPANDED_W = 820
EXPANDED_H = 500
TOP_MARGIN = 0
ANIMATION_MS = 220
RECENT_ROUTES_MAX_HEIGHT = 100
TRACKED_ROUTES_MAX_HEIGHT = 96
ROUTES_LIST_MIN_HEIGHT = 160
ANNOTATION_PANEL_SCROLL_HEIGHT = 330
SIDEBAR_RAIL_WIDTH = 34
MAXIMIZED_SIDEBAR_WIDTH = 360  # 最大化时侧边栏的默认固定宽度
WINDOW_MIN_W = 420
WINDOW_MIN_H = 240
TRACKING_WINDOW_MIN_H = 360
SIDEBAR_MIN_EXPANDED_W = 760
SIDEBAR_MIN_EXPANDED_H = 420
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
    border-radius: 8px;
    padding: 5px 8px;
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
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.35);
    border-radius: 3px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.35);
    border-radius: 3px;
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
"""
