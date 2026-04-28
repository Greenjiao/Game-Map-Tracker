"""UI construction helpers for the island window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..design import strings, theme
from ..views.map_view import MapView
from ..widgets import AnnotationPanel, StatusDot
from ..widgets.factory import make_route_panel_line_edit, make_scroll_area


def build_window_ui(window) -> None:
    window.root = QFrame(window)
    window.root.setObjectName("IslandRoot")
    window.root.setStyleSheet(theme.ISLAND_QSS)

    if window._shadow_enabled:
        shadow = QGraphicsDropShadowEffect(window)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        window.root.setGraphicsEffect(shadow)

    outer = QVBoxLayout(window)
    outer.setContentsMargins(
        window._window_margin,
        window._window_margin,
        window._window_margin,
        window._window_margin,
    )
    outer.addWidget(window.root)

    root_layout = QVBoxLayout(window.root)
    root_layout.setContentsMargins(12, 8, 12, 10)
    root_layout.setSpacing(8)

    _build_header(window, root_layout)
    _build_body(window, root_layout)


def _build_header(window, root_layout: QVBoxLayout) -> None:
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(10)

    window.title_drag_area = QWidget()
    title_layout = QHBoxLayout(window.title_drag_area)
    title_layout.setContentsMargins(0, 0, 0, 0)
    title_layout.setSpacing(10)

    window.dot = StatusDot(window.title_drag_area)
    window.dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    title_layout.addWidget(window.dot)

    window.coord_label = QLabel("-- , --", window.title_drag_area)
    window.coord_label.setObjectName("CoordLabel")
    window.coord_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    title_layout.addWidget(window.coord_label)

    window.state_hint_label = QLabel("定位稳定")
    window.state_hint_label.setObjectName("StateHint")
    window.state_hint_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    title_layout.addWidget(window.state_hint_label)

    window.route_drawing_help_btn = QPushButton("?")
    window.route_drawing_help_btn.setObjectName("RouteDrawingHelpButton")
    window.route_drawing_help_btn.setToolTip(strings.ROUTE_DRAWING_HELP_TITLE)
    window.route_drawing_help_btn.hide()
    window.route_drawing_help_btn.clicked.connect(window.route_panel_controller.show_route_drawing_help)
    title_layout.addWidget(window.route_drawing_help_btn)

    window.unlock_hint_label = QLabel("快捷键 Alt+` 解锁")
    window.unlock_hint_label.setObjectName("MapHint")
    window.unlock_hint_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    window.unlock_hint_label.hide()
    title_layout.addWidget(window.unlock_hint_label)

    title_layout.addStretch()

    window.stat_label = QLabel("--- ms", window.title_drag_area)
    window.stat_label.setObjectName("StatLabel")
    window.stat_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    title_layout.addWidget(window.stat_label)

    window.title_drag_area.installEventFilter(window)
    header.addWidget(window.title_drag_area, stretch=1)

    window.settings_btn = QPushButton("⚙")
    window.settings_btn.setObjectName("WindowControl")
    window.settings_btn.setToolTip("设置")
    window.settings_btn.setCheckable(True)
    window.settings_btn.clicked.connect(window._open_settings)
    header.addWidget(window.settings_btn)

    window.min_btn = QPushButton("-")
    window.min_btn.setObjectName("WindowControl")
    window.min_btn.setToolTip("最小化")
    window.min_btn.setFont(_window_control_font(18))
    window.min_btn.clicked.connect(window._collapse_to_icon)
    header.addWidget(window.min_btn)

    window.max_btn = QPushButton("▢")
    window.max_btn.setObjectName("WindowControl")
    window.max_btn.setToolTip("最大化")
    window.max_btn.setFont(_window_control_font(18))
    window.max_btn.clicked.connect(window.window_mode_controller.toggle_maximize_restore)
    header.addWidget(window.max_btn)

    window.close_btn = QPushButton("×")
    window.close_btn.setObjectName("WindowControl")
    window.close_btn.setToolTip("关闭")
    window.close_btn.setFont(_window_control_font(18))
    window.close_btn.clicked.connect(window.close)
    header.addWidget(window.close_btn)

    window.relocate_btn = QPushButton("重定位")
    window.relocate_btn.setObjectName("HeaderActionButton")
    window.relocate_btn.setProperty("iconRole", "locate")
    window.relocate_btn.setToolTip("重定位")
    window.relocate_btn.clicked.connect(window._prompt_relocate)
    header.addWidget(window.relocate_btn)

    window.reset_view_btn = QPushButton("重置视图")
    window.reset_view_btn.setObjectName("HeaderActionButton")
    window.reset_view_btn.setProperty("iconRole", "reset")
    window.reset_view_btn.setToolTip("重置视图")
    window.reset_view_btn.clicked.connect(window._reset_map_view)
    header.addWidget(window.reset_view_btn)
    header.removeWidget(window.reset_view_btn)
    header.insertWidget(header.indexOf(window.relocate_btn), window.reset_view_btn)

    window.sidebar_toggle_btn = QPushButton("隐藏侧边栏")
    window.sidebar_toggle_btn.setObjectName("TopSidebarToggle")
    window.sidebar_toggle_btn.setProperty("iconRole", "sidebar")
    window.sidebar_toggle_btn.setToolTip("隐藏侧边栏")
    window.sidebar_toggle_btn.clicked.connect(window.window_mode_controller.handle_sidebar_action)
    header.addWidget(window.sidebar_toggle_btn)

    window.terminate_nav_btn = QPushButton("终止导航")
    window.terminate_nav_btn.setObjectName("HeaderActionButton")
    window.terminate_nav_btn.setProperty("iconRole", "terminate")
    window.terminate_nav_btn.setToolTip("终止导航")
    window.terminate_nav_btn.clicked.connect(window.tracking_controller.pause_navigation)
    header.addWidget(window.terminate_nav_btn)

    window.lock_btn = QPushButton("锁定")
    window.lock_btn.setObjectName("HeaderActionButton")
    window.lock_btn.setProperty("headerButton", True)
    window.lock_btn.setProperty("iconRole", "lock")
    window.lock_btn.setCheckable(True)
    window.lock_btn.setToolTip("锁定")
    window.lock_btn.clicked.connect(window.toggle_lock)
    header.addWidget(window.lock_btn)

    window._update_header_button_labels()
    root_layout.addLayout(header)


def _window_control_font(size: int) -> QFont:
    font = QFont()
    font.setPointSize(size)
    font.setBold(True)
    return font


def _build_body(window, root_layout: QVBoxLayout) -> None:
    window.alert_card = QFrame()
    window.alert_card.setObjectName("AlertCard")
    window.alert_card.hide()
    alert_layout = QHBoxLayout(window.alert_card)
    alert_layout.setContentsMargins(16, 10, 16, 10)
    alert_layout.setSpacing(12)
    alert_layout.addStretch()

    window.alert_message = QLabel("目标丢失，正在尝试重新定位。")
    window.alert_message.setObjectName("AlertMessage")
    window.alert_message.setAlignment(Qt.AlignCenter)
    window.alert_message.setWordWrap(True)
    alert_layout.addWidget(window.alert_message)

    window.alert_terminate_btn = QPushButton("终止导航")
    window.alert_terminate_btn.setObjectName("AlertAction")
    window.alert_terminate_btn.setFixedHeight(theme.ALERT_ACTION_HEIGHT)
    window.alert_terminate_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    window.alert_terminate_btn.clicked.connect(window.tracking_controller.pause_navigation)
    alert_layout.addWidget(window.alert_terminate_btn)
    alert_layout.addStretch()
    root_layout.addWidget(window.alert_card)

    window.body_container = QWidget()
    body = QHBoxLayout(window.body_container)
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(12)

    window.map_shell = QWidget()
    map_layout = QVBoxLayout(window.map_shell)
    map_layout.setContentsMargins(0, 0, 0, 0)
    map_layout.setSpacing(10)

    window.map_view = MapView(window.route_mgr)
    window.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    window.map_view.set_map(window.tracker.logic_map_bgr)
    window.map_view.relocate_requested.connect(window._on_relocate)
    window.map_view.manual_view_changed.connect(window._handle_manual_map_navigation)
    map_layout.addWidget(window.map_view, stretch=1)

    window.tracked_routes_card = QFrame()
    window.tracked_routes_card.setObjectName("PanelCard")
    window.tracked_routes_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    window.tracked_routes_layout = QVBoxLayout(window.tracked_routes_card)
    window.tracked_routes_layout.setContentsMargins(12, 0, 12, 0)
    window.tracked_routes_layout.setSpacing(4)

    window.tracked_routes_header = QWidget()
    window.tracked_routes_header_layout = QHBoxLayout(window.tracked_routes_header)
    window.tracked_routes_header_layout.setContentsMargins(0, 0, 0, 0)
    window.tracked_routes_header_layout.setSpacing(8)

    window.tracked_routes_title = QLabel("当前追踪路线")
    window.tracked_routes_title.setObjectName("TitleLabel")
    window.tracked_routes_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    window.tracked_routes_header_layout.addWidget(window.tracked_routes_title, stretch=0)

    window.tracked_routes_collapsed = False
    window.tracked_routes_toggle_btn = QPushButton("▾")
    window.tracked_routes_toggle_btn.setObjectName("SectionHeader")
    window.tracked_routes_toggle_btn.setProperty("compact", True)
    window.tracked_routes_toggle_btn.setProperty("sectionToggleOnly", True)
    window.tracked_routes_toggle_btn.setToolTip("收起当前追踪路线")
    window.tracked_routes_toggle_btn.setFixedWidth(26)
    window.tracked_routes_toggle_btn.clicked.connect(window.route_panel_controller.toggle_tracked_routes_collapsed)
    window.tracked_routes_header_layout.addWidget(window.tracked_routes_toggle_btn, stretch=0)
    window.tracked_routes_header_layout.addStretch(1)

    window.tracked_guide_hint_label = QLabel("")
    window.tracked_guide_hint_label.setObjectName("TrackedGuideHint")
    window.tracked_guide_hint_label.setWordWrap(True)
    window.tracked_guide_hint_label.setVisible(False)
    window.tracked_guide_hint_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
    window.tracked_guide_hint_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    window.tracked_routes_header_layout.addWidget(window.tracked_guide_hint_label, stretch=0)

    window.tracked_routes_layout.addWidget(window.tracked_routes_header)

    window.tracked_routes_scroll = make_scroll_area(
        max_height=theme.TRACKED_ROUTES_MAX_HEIGHT,
        vertical_policy=Qt.ScrollBarAsNeeded,
        size_policy=(QSizePolicy.Preferred, QSizePolicy.Fixed),
    )

    window.tracked_routes_inner = QWidget()
    window.tracked_routes_grid = QGridLayout(window.tracked_routes_inner)
    window.tracked_routes_grid.setContentsMargins(0, 0, 0, 0)
    window.tracked_routes_grid.setHorizontalSpacing(16)
    window.tracked_routes_grid.setVerticalSpacing(6)
    window.tracked_routes_grid.setColumnStretch(0, 1)
    window.tracked_routes_grid.setColumnStretch(1, 1)

    window.tracked_routes_scroll.setWidget(window.tracked_routes_inner)
    window.tracked_routes_layout.addWidget(window.tracked_routes_scroll)
    map_layout.addWidget(window.tracked_routes_card)
    map_layout.setStretch(0, 1)
    map_layout.setStretch(1, 0)

    body.addWidget(window.map_shell, stretch=7)

    window.sidebar_shell = QWidget()
    window.sidebar_shell.setObjectName("SidebarOverlay")
    window.sidebar_shell.setAttribute(Qt.WA_StyledBackground, True)
    shell_layout = QVBoxLayout(window.sidebar_shell)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(0)

    window.side_scroll = make_scroll_area(object_name="SidebarOverlayScroll", min_width=200)

    window.side_panel = QFrame()
    window.side_panel.setObjectName("PanelCard")
    side_layout = QVBoxLayout(window.side_panel)
    side_layout.setContentsMargins(12, 12, 12, 12)
    side_layout.setSpacing(10)
    side_layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)

    window.map_hint_row = QWidget()
    map_hint_layout = QHBoxLayout(window.map_hint_row)
    map_hint_layout.setContentsMargins(0, 0, 0, 0)
    map_hint_layout.setSpacing(8)
    map_hint = QLabel("滚轮缩放，左键拖动，双击选点")
    map_hint.setObjectName("MapHint")
    map_hint_layout.addWidget(map_hint, stretch=1)
    window.annotation_toggle_btn = QPushButton("标注")
    window.annotation_toggle_btn.setObjectName("AnnotationToggleButton")
    window.annotation_toggle_btn.setCheckable(True)
    map_hint_layout.addWidget(window.annotation_toggle_btn, stretch=0)
    side_layout.addWidget(window.map_hint_row)

    window.annotation_panel = AnnotationPanel(window)
    window.annotation_panel.hide()

    window.search_input = make_route_panel_line_edit(placeholder="搜索路线...")
    window.search_input.textChanged.connect(window.route_panel_controller.apply_route_filter)
    side_layout.addWidget(window.search_input)

    routes_header = QHBoxLayout()
    routes_header.setContentsMargins(0, 0, 0, 0)
    routes_header.setSpacing(8)

    routes_title = QLabel("路线列表")
    routes_title.setObjectName("TitleLabel")
    routes_header.addWidget(routes_title)
    routes_header.addStretch()

    window.refresh_routes_btn = QPushButton("刷新列表")
    window.refresh_routes_btn.setProperty("headerButton", True)
    window.refresh_routes_btn.setProperty("compact", True)
    window.refresh_routes_btn.setProperty("routePanelHeaderButton", "true")
    window.refresh_routes_btn.setToolTip("重新读取 routes 文件夹下的所有路径")
    window.refresh_routes_btn.clicked.connect(window.route_panel_controller.reload_route_list)
    routes_header.addWidget(window.refresh_routes_btn)

    window.add_category_btn = QPushButton("新增类别")
    window.add_category_btn.setProperty("headerButton", True)
    window.add_category_btn.setProperty("compact", True)
    window.add_category_btn.setProperty("routePanelHeaderButton", "true")
    window.add_category_btn.setToolTip("新增一个路线类别文件夹")
    window.add_category_btn.clicked.connect(window.route_panel_controller.show_add_category_row)
    routes_header.addWidget(window.add_category_btn)

    side_layout.addLayout(routes_header)

    window.routes_scroll = make_scroll_area(min_height=theme.ROUTES_LIST_MIN_HEIGHT)

    window.routes_scroll_inner = QWidget()
    window.routes_scroll_inner.setObjectName("RoutesScrollInner")
    window.routes_scroll_inner.setAttribute(Qt.WA_StyledBackground, True)
    window.routes_layout = QVBoxLayout(window.routes_scroll_inner)
    window.routes_layout.setContentsMargins(0, 0, 0, 0)
    window.routes_layout.setSpacing(8)
    window.route_panel_controller.build_add_category_row()
    window.route_panel_controller.rebuild_route_sections()
    window.routes_scroll.setWidget(window.routes_scroll_inner)
    side_layout.addWidget(window.routes_scroll, stretch=1)

    window.side_scroll.setWidget(window.side_panel)
    shell_layout.addWidget(window.side_scroll, stretch=1)

    body.addWidget(window.sidebar_shell, stretch=4)
    root_layout.addWidget(window.body_container, stretch=1)

    window.map_view.set_center_locked(True)
    window.route_panel_controller.refresh_tracked_routes()
    window.window_mode_controller.apply_sidebar_state()
    window.route_panel_controller.apply_route_filter()
    window._update_window_controls()
