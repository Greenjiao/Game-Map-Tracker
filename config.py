import copy
import json
import os
import shutil
import sys

from config_defaults import CONFIG_VERSION, DEFAULT_CONFIG, OBSOLETE_CONFIG_KEYS

# ==========================================
# 核心黑科技：兼容 PyInstaller 打包后的路径寻找
# ==========================================
if getattr(sys, 'frozen', False):
    # 如果是打包后的 .exe 运行，去 exe 所在的同级目录找配置文件
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是在代码编辑器里直接运行 main.py，去当前代码所在的目录找
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def app_path(*parts: str) -> str:
    """Return a path under the editable application directory."""
    return os.path.join(BASE_DIR, *parts)


def resolve_app_path(path: str | os.PathLike[str] | None) -> str | None:
    """Resolve relative config paths against the application directory."""
    if path is None:
        return None
    raw_path = os.fspath(path)
    if os.path.isabs(raw_path):
        return raw_path
    return app_path(raw_path)

def _clone(value):
    return copy.deepcopy(value)


def _read_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("config.json 顶层必须是 JSON 对象")
    return payload


def _write_json_file(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def _backup_config_file(path: str) -> None:
    """写回合并配置前备份用户原始配置，避免更新时误伤。"""
    if not os.path.exists(path):
        return
    try:
        shutil.copy2(path, path + ".bak")
    except Exception as e:
        print(f"备份 config.json 失败: {e}")


def _config_version(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def migrate_user_config(user_config: dict) -> dict:
    """迁移旧版用户配置；后续有字段改名时在这里追加版本迁移。"""
    migrated = _clone(user_config)
    version = _config_version(migrated.get("CONFIG_VERSION"))

    if version < 2:
        # v2 引入 CONFIG_VERSION。其他新增字段由 merge_config_payload 自动补齐。
        pass

    return migrated


def _is_compatible_value(default_value, user_value) -> bool:
    if default_value is None:
        return True
    if isinstance(default_value, bool):
        return isinstance(user_value, bool)
    if isinstance(default_value, int) and not isinstance(default_value, bool):
        return isinstance(user_value, int) and not isinstance(user_value, bool)
    if isinstance(default_value, float):
        return isinstance(user_value, (int, float)) and not isinstance(user_value, bool)
    if isinstance(default_value, str):
        return isinstance(user_value, str)
    if isinstance(default_value, list):
        return isinstance(user_value, list)
    if isinstance(default_value, dict):
        return isinstance(user_value, dict)
    return isinstance(user_value, type(default_value))


def _merge_dict(
    defaults: dict,
    user_values: dict,
    prefix: str = "",
    obsolete_config_keys: set[str] | None = None,
) -> tuple[dict, list[str]]:
    """递归合并配置：新增字段用默认值，已有有效字段保留用户值。"""
    merged: dict = {}
    repaired: list[str] = []

    for key, default_value in defaults.items():
        key_path = f"{prefix}.{key}" if prefix else str(key)
        if key not in user_values:
            merged[key] = _clone(default_value)
            continue

        user_value = user_values[key]
        if isinstance(default_value, dict):
            if isinstance(user_value, dict):
                child, child_repaired = _merge_dict(default_value, user_value, key_path, obsolete_config_keys)
                merged[key] = child
                repaired.extend(child_repaired)
            else:
                merged[key] = _clone(default_value)
                repaired.append(key_path)
            continue

        if _is_compatible_value(default_value, user_value):
            merged[key] = _clone(user_value)
        else:
            merged[key] = _clone(default_value)
            repaired.append(key_path)

    # 未知字段继续保留，列入废弃清单的旧字段会在合并时清理。
    for key, user_value in user_values.items():
        if key not in defaults:
            if not prefix and obsolete_config_keys is not None and key in obsolete_config_keys:
                repaired.append(str(key))
                continue
            merged[key] = _clone(user_value)

    return merged, repaired


def merge_config_payload(
    default_config: dict,
    user_config: dict | None,
    obsolete_config_keys: set[str] | list[str] | tuple[str, ...] | None = None,
) -> tuple[dict, list[str]]:
    """合并默认配置和用户配置，返回 (合并后配置, 被修复字段列表)。"""
    if not isinstance(user_config, dict):
        merged = _clone(default_config)
        merged["CONFIG_VERSION"] = int(default_config.get("CONFIG_VERSION", CONFIG_VERSION))
        return merged, ["<root>"]

    migrated = migrate_user_config(user_config)
    obsolete_keys = set(OBSOLETE_CONFIG_KEYS)
    if obsolete_config_keys is not None:
        obsolete_keys.update(str(key) for key in obsolete_config_keys)
    merged, repaired = _merge_dict(default_config, migrated, obsolete_config_keys=obsolete_keys)
    merged["CONFIG_VERSION"] = int(default_config.get("CONFIG_VERSION", CONFIG_VERSION))
    return merged, repaired


def merge_config_file(
    path: str = CONFIG_FILE,
    default_config: dict | None = None,
    obsolete_config_keys: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict:
    """读取、迁移、合并并写回 config.json。"""
    defaults = default_config or DEFAULT_CONFIG
    if not os.path.exists(path):
        print("未找到 config.json，正在自动生成默认配置文件...")
        merged = _clone(defaults)
        try:
            _write_json_file(path, merged)
        except Exception as e:
            print(f"生成配置文件失败: {e}")
        return merged

    try:
        user_config = _read_json_file(path)
    except Exception as e:
        print(f"读取 config.json 失败 (格式错误?)，将备份后重新生成默认配置！错误: {e}")
        _backup_config_file(path)
        merged = _clone(defaults)
        try:
            _write_json_file(path, merged)
        except Exception as write_error:
            print(f"重新生成配置文件失败: {write_error}")
        return merged

    merged_config, repaired = merge_config_payload(defaults, user_config, obsolete_config_keys)
    if merged_config != user_config:
        _backup_config_file(path)
        try:
            _write_json_file(path, merged_config)
        except Exception as e:
            print(f"写回合并后的 config.json 失败: {e}")
    if repaired:
        print(f"已修复异常配置字段: {', '.join(repaired)}")
    return merged_config


def save_config(new_values: dict) -> None:
    """把部分字段写回 config.json 并刷新本模块导出的常量。"""
    current = {}
    if os.path.exists(CONFIG_FILE):
        try:
            current = _read_json_file(CONFIG_FILE)
        except Exception:
            current = {}
    current.update(new_values)
    current, _repaired = merge_config_payload(DEFAULT_CONFIG, current)
    _write_json_file(CONFIG_FILE, current)

    # 同步更新模块级常量，避免进程内各处读到旧值
    globals().update(current)
    globals()["LOGIC_MAP_PATH"] = resolve_app_path(current.get("LOGIC_MAP_PATH"))
    settings.clear()
    settings.update(current)


def load_config():
    """读取 JSON 配置文件，并合并新版默认配置"""
    return merge_config_file()


# ==========================================
# 加载配置并导出变量 (让 main.py 可以直接 import 这些变量)
# ==========================================
settings = load_config()

# 通用设置
CONFIG_VERSION = settings.get("CONFIG_VERSION", CONFIG_VERSION)
MINIMAP = settings.get("MINIMAP")
WINDOW_GEOMETRY = settings.get("WINDOW_GEOMETRY")
SIDEBAR_COLLAPSED = settings.get("SIDEBAR_COLLAPSED")
SIDEBAR_WIDTH = settings.get("SIDEBAR_WIDTH")
PAUSED_SIDEBAR_WIDTH = settings.get("PAUSED_SIDEBAR_WIDTH")
LOCKED_VIEW_SIZE = settings.get("LOCKED_VIEW_SIZE")
PAUSED_VIEW_SIZE = settings.get("PAUSED_VIEW_SIZE")
ROUTE_SECTION_EXPANDED = settings.get("ROUTE_SECTION_EXPANDED") or {}
ANNOTATION_TYPE_IDS = settings.get("ANNOTATION_TYPE_IDS") or []
ANNOTATION_GROUP_EXPANDED = settings.get("ANNOTATION_GROUP_EXPANDED") or {}
QUARK_DOWNLOAD_URL = ""
ROUTE_RESOURCE_URL = ""
DOCUMENTATION_URL = ""
FEEDBACK_BILIBILI_URL = ""
FEEDBACK_QQ_GROUP = ""
APP_UPDATE_MANIFEST_URLS = []
APP_UPDATE_LAST_PROMPTED_VERSION = settings.get("APP_UPDATE_LAST_PROMPTED_VERSION") or ""
APP_NOTICE_LAST_ACK_KEY = settings.get("APP_NOTICE_LAST_ACK_KEY") or ""


def parse_window_geometry(raw) -> dict | None:
    """把旧的 Tk 字符串或新字典格式规整成 {x, y, width, height}。

    支持：
      - 字典 {x, y, width, height}
      - Tk 格式 "WxH+X+Y"
    无效输入返回 None。
    """
    if isinstance(raw, dict):
        try:
            return {
                "x": int(raw["x"]),
                "y": int(raw["y"]),
                "width": int(raw["width"]),
                "height": int(raw["height"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, str):
        import re
        m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", raw.strip())
        if m:
            w, h, x, y = m.groups()
            try:
                return {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}
            except ValueError:
                return None
    return None
VIEW_SIZE = settings.get("VIEW_SIZE")
LOGIC_MAP_PATH = resolve_app_path(settings.get("LOGIC_MAP_PATH"))
MAX_LOST_FRAMES = settings.get("MAX_LOST_FRAMES")

# SIFT 专属
SIFT_REFRESH_RATE = settings.get("SIFT_REFRESH_RATE")
SIFT_CLAHE_LIMIT = settings.get("SIFT_CLAHE_LIMIT")
SIFT_MATCH_RATIO = settings.get("SIFT_MATCH_RATIO")
SIFT_MIN_MATCH_COUNT = settings.get("SIFT_MIN_MATCH_COUNT")
SIFT_RANSAC_THRESHOLD = settings.get("SIFT_RANSAC_THRESHOLD")
SIFT_LOCAL_SEARCH_RADIUS = settings.get("SIFT_LOCAL_SEARCH_RADIUS")

ROUTE_GUIDE_NODE_DISTANCE = settings.get("ROUTE_GUIDE_NODE_DISTANCE")
ROUTE_GUIDE_SEGMENT_DISTANCE = settings.get("ROUTE_GUIDE_SEGMENT_DISTANCE")
ROUTE_GUIDE_POINTER_SPACING = settings.get("ROUTE_GUIDE_POINTER_SPACING")
ROUTE_GUIDE_POINTER_SIZE = settings.get("ROUTE_GUIDE_POINTER_SIZE")
ROUTE_MULTI_COLOR_ENABLED = settings.get("ROUTE_MULTI_COLOR_ENABLED")
ROUTE_DEFAULT_COLOR = settings.get("ROUTE_DEFAULT_COLOR")
ROUTE_TELEPORT_LINE_COLOR = settings.get("ROUTE_TELEPORT_LINE_COLOR")
ROUTE_GUIDE_LINE_COLOR = settings.get("ROUTE_GUIDE_LINE_COLOR")
ROUTE_POINTER_ARROW_COLOR = settings.get("ROUTE_POINTER_ARROW_COLOR")
ROUTE_POINTER_ARROW_VISIBLE = settings.get("ROUTE_POINTER_ARROW_VISIBLE")
ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR = settings.get("ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR")
ROUTE_STRICT_GUIDE_MODE = settings.get("ROUTE_STRICT_GUIDE_MODE")
TOGGLE_LOCK_HOTKEY = settings.get("TOGGLE_LOCK_HOTKEY")
ROUTE_VISITED_POINT_OPACITY = settings.get("ROUTE_VISITED_POINT_OPACITY")
ROUTE_VISITED_ICON_OPACITY = settings.get("ROUTE_VISITED_ICON_OPACITY")
WINDOW_LOCKED_OPACITY = settings.get("WINDOW_LOCKED_OPACITY")
WINDOW_NORMAL_OPACITY = settings.get("WINDOW_NORMAL_OPACITY")
