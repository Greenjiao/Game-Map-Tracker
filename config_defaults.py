"""Side-effect-free default configuration for GMT-N."""

from __future__ import annotations


CONFIG_VERSION = 5

DEFAULT_CONFIG = {
    "CONFIG_VERSION": CONFIG_VERSION,
    "MINIMAP": {},
    "WINDOW_GEOMETRY": {"x": 1415, "y": 0, "width": 420, "height": 360},
    "LOCKED_VIEW_SIZE": {"width": 420, "height": 360},
    "PAUSED_VIEW_SIZE": {"width": 820, "height": 500},
    "SIDEBAR_COLLAPSED": True,
    "SIDEBAR_WIDTH": 270,
    "PAUSED_SIDEBAR_WIDTH": 270,
    "VIEW_SIZE": 400,
    "MAP_FILE": "",
    "ANNOTATION_FILE": "",
    "MAX_LOST_FRAMES": 30,
    "SIFT_REFRESH_RATE": 30,
    "SIFT_CLAHE_LIMIT": 3.0,
    "SIFT_MATCH_RATIO": 0.9,
    "SIFT_MIN_MATCH_COUNT": 5,
    "SIFT_RANSAC_THRESHOLD": 8.0,
    "SIFT_LOCAL_SEARCH_RADIUS": 400,
    "ROUTE_GUIDE_NODE_DISTANCE": 80,
    "ROUTE_GUIDE_SEGMENT_DISTANCE": 35,
    "ROUTE_GUIDE_POINTER_SPACING": 28,
    "ROUTE_GUIDE_POINTER_SIZE": 10,
    "ROUTE_MULTI_COLOR_ENABLED": True,
    "ROUTE_DEFAULT_COLOR": "#1ad1ff",
    "ROUTE_TELEPORT_LINE_COLOR": "#ffffff",
    "ROUTE_GUIDE_LINE_COLOR": "#ffffff",
    "ROUTE_POINTER_ARROW_COLOR": "#000000",
    "ROUTE_POINTER_ARROW_VISIBLE": True,
    "ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR": False,
    "ROUTE_STRICT_GUIDE_MODE": False,
    "TOGGLE_LOCK_HOTKEY": {
        "sequence": "Alt+`",
        "label": "Alt+`",
        "modifiers": ["Alt"],
        "key": "QuoteLeft",
        "vk": 0xC0,
    },
    "ACTION_HOTKEYS": {
        "reset_view": None,
        "relocate": None,
        "start_navigation": None,
        "terminate_navigation": None,
        "jump_current_route_node": None,
        "add_current_position_to_current_route": None,
    },
    "ROUTE_VISITED_POINT_OPACITY": 1.0,
    "ROUTE_VISITED_ICON_OPACITY": 0.35,
    "ROUTE_GUIDE_DISABLE_NODE_DRAG": True,
    "ROUTE_NODE_ORDER_VISIBLE": True,
    "ROUTE_NODE_ICON_SIZE": 20,
    "ANNOTATION_ICON_SIZE": 20,
    "ROUTE_NODE_DOT_SIZE": 5,
    "WINDOW_LOCK_FOLLOWS_GUIDE": True,
    "PURE_NAVIGATION_MODE": False,
    "ROUTE_NOTES_DIALOG_WIDTH": 680,
    "ROUTE_NOTES_NODE_PANEL_WIDTH": 200,
    "WINDOW_LOCKED_OPACITY": 0.8,
    "WINDOW_NORMAL_OPACITY": 1.0,
    "ROUTE_SECTION_EXPANDED": {},
    "ANNOTATION_TYPE_IDS": [],
    "ANNOTATION_PRESETS": [],
    "ANNOTATION_GROUP_EXPANDED": {},
    "ANNOTATION_PANEL_FOLLOW_WINDOW": True,
    "ANNOTATION_PANEL_OFFSET": {},
    "ANNOTATION_PANEL_MAXIMIZED_OFFSET": {},
    "ANNOTATION_PANEL_POSITION": {},
    "ANNOTATION_PANEL_MAXIMIZED_POSITION": {},
    "ANNOTATION_PRESETS": [
        {
            "id": "preset_3e2f22e82cf14888b6830b2da5047a65",
            "name": "常用传送点",
            "type_ids": [
                "17310030024",
                "17310030025",
                "17310030038",
                "17310030039",
                "17310030040",
                "17310030041"
            ]
        },
        {
            "id": "preset_7eab6eb79ce64b529cc749cbbe0fa6c9",
            "name": "常用采集路线1_只显示矿",
            "type_ids": [
                "17310030043",
                "17310030044",
                "17310030045",
                "17310030046"
            ]
        }
    ],
    "APP_UPDATE_LAST_PROMPTED_VERSION": "",
    "APP_NOTICE_LAST_ACK_KEY": "",
}

OBSOLETE_CONFIG_KEYS = {
    "QUARK_DOWNLOAD_URL",
    "ROUTE_RESOURCE_URL",
    "ROUTE_RESOURCE_LINKS",
    "FEEDBACK_BILIBILI_URL",
    "FEEDBACK_QQ_GROUP",
    "FEEDBACK_LINKS",
    "APP_UPDATE_MANIFEST_URL",
    "APP_UPDATE_MANIFEST_URLS",
    "LOGIC_MAP_PATH",
    "ROUTE_RECENT_LIMIT",
    "ANNOTATION_RECENT_TYPE_IDS",
}
