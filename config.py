import copy
import json
import os
import shutil
import sys
from pathlib import PurePosixPath

from config_defaults import CONFIG_VERSION, DEFAULT_CONFIG, OBSOLETE_CONFIG_KEYS

MAPS_DIR_NAME = "maps"
MAP_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
DEFAULT_MAP_FILE = str(DEFAULT_CONFIG.get("MAP_FILE") or "")
ANNOTATIONS_DIR_NAME = "annotations"
DEFAULT_ANNOTATION_FILE = str(DEFAULT_CONFIG.get("ANNOTATION_FILE") or "")
ANNOTATION_FILE_EXTENSIONS = (".json",)
_INVALID_DIR_CHARS = set('<>:"/\\|?*')

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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


def _base_dir(base_dir: str | os.PathLike[str] | None = None) -> str:
    return BASE_DIR if base_dir is None else os.fspath(base_dir)


def _normalize_slashes(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("./")


def _relative_or_basename(raw_path: str, base_dir: str | os.PathLike[str] | None = None) -> str:
    if not os.path.isabs(raw_path):
        return raw_path
    try:
        abs_base = os.path.abspath(_base_dir(base_dir))
        abs_path = os.path.abspath(raw_path)
        if os.path.commonpath([abs_base, abs_path]) == abs_base:
            return os.path.relpath(abs_path, abs_base)
    except (OSError, ValueError):
        pass
    return os.path.basename(raw_path)


def maps_dir(base_dir: str | os.PathLike[str] | None = None) -> str:
    return os.path.join(_base_dir(base_dir), MAPS_DIR_NAME)


def ensure_maps_dir(base_dir: str | os.PathLike[str] | None = None) -> str:
    path = maps_dir(base_dir)
    os.makedirs(path, exist_ok=True)
    return path


def is_map_image(path: str) -> bool:
    return os.path.splitext(str(path or ""))[1].casefold() in MAP_IMAGE_EXTENSIONS


def normalize_map_file(value: object, base_dir: str | os.PathLike[str] | None = None) -> str:
    """Normalize config map values to a relative path under maps/ when possible."""
    raw = str(value or "").strip()
    if not raw:
        return ""

    rel = _normalize_slashes(_relative_or_basename(raw, base_dir))
    if not rel:
        return ""

    path = PurePosixPath(rel)
    if ".." in path.parts:
        rel = path.name
        path = PurePosixPath(rel)

    if len(path.parts) == 1 and is_map_image(path.name):
        return f"{MAPS_DIR_NAME}/{path.name}"

    if path.parts and path.parts[0].casefold() == MAPS_DIR_NAME:
        return path.as_posix()

    return rel


def selected_map_file_from_settings(
    payload: dict | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> str:
    source = payload if payload is not None else {"MAP_FILE": globals().get("MAP_FILE", settings.get("MAP_FILE", ""))}
    return normalize_map_file(source.get("MAP_FILE"), base_dir)


def selected_map_path_from_settings(
    payload: dict | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> str:
    selected = selected_map_file_from_settings(payload, base_dir)
    if not selected:
        return ""
    root = _base_dir(base_dir)
    return os.path.join(root, *selected.split("/"))


def selected_map_exists(payload: dict | None = None) -> bool:
    path = selected_map_path_from_settings(payload)
    return bool(path and os.path.isfile(path))


def iter_map_files(base_dir: str | os.PathLike[str] | None = None) -> list[str]:
    root_base = _base_dir(base_dir)
    root = maps_dir(root_base)
    if not os.path.isdir(root):
        return []

    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=str.casefold)
        for filename in sorted(filenames, key=str.casefold):
            if not is_map_image(filename):
                continue
            full_path = os.path.join(dirpath, filename)
            try:
                rel = os.path.relpath(full_path, root_base)
            except ValueError:
                continue
            files.append(normalize_map_file(rel, root_base))
    return files


def normalize_map_directory(value: object, base_dir: str | os.PathLike[str] | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return MAPS_DIR_NAME

    rel = _normalize_slashes(_relative_or_basename(raw, base_dir))
    if not rel:
        return MAPS_DIR_NAME

    path = PurePosixPath(rel)
    if ".." in path.parts:
        return MAPS_DIR_NAME
    if path.parts and path.parts[0].casefold() == MAPS_DIR_NAME:
        return path.as_posix().rstrip("/") or MAPS_DIR_NAME
    return MAPS_DIR_NAME


def map_directory_for_file(map_file: object, base_dir: str | os.PathLike[str] | None = None) -> str:
    rel = normalize_map_file(map_file, base_dir)
    if not rel:
        return MAPS_DIR_NAME
    path = PurePosixPath(rel)
    if len(path.parts) <= 1:
        return MAPS_DIR_NAME
    return normalize_map_directory(path.parent.as_posix(), base_dir)


def iter_map_directories(base_dir: str | os.PathLike[str] | None = None) -> list[str]:
    root_base = _base_dir(base_dir)
    root = maps_dir(root_base)
    if not os.path.isdir(root):
        return [MAPS_DIR_NAME]

    directories: list[str] = [MAPS_DIR_NAME]
    seen = {MAPS_DIR_NAME}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=str.casefold)
        if not any(is_map_image(filename) for filename in filenames):
            continue
        try:
            rel = os.path.relpath(dirpath, root_base)
        except ValueError:
            continue
        directory = normalize_map_directory(rel, root_base)
        if directory not in seen:
            seen.add(directory)
            directories.append(directory)
    return directories


def iter_map_files_in_directory(
    base_dir: str | os.PathLike[str] | None,
    directory: object,
) -> list[str]:
    root_base = _base_dir(base_dir)
    rel_dir = normalize_map_directory(directory, root_base)
    root = os.path.join(root_base, *rel_dir.split("/"))
    if not os.path.isdir(root):
        return []

    files: list[str] = []
    try:
        filenames = sorted(os.listdir(root), key=str.casefold)
    except OSError:
        return []
    for filename in filenames:
        full_path = os.path.join(root, filename)
        if not os.path.isfile(full_path) or not is_map_image(filename):
            continue
        try:
            rel = os.path.relpath(full_path, root_base)
        except ValueError:
            continue
        files.append(normalize_map_file(rel, root_base))
    return files


def map_directory_display_name(directory: object) -> str:
    rel = normalize_map_directory(directory)
    if rel == MAPS_DIR_NAME:
        return "maps/"
    return rel[len(MAPS_DIR_NAME) + 1 :] if rel.startswith(f"{MAPS_DIR_NAME}/") else rel


def _safe_dir_name(value: object) -> str:
    raw = str(value or "").strip() or "自定义底图"
    clean = "".join("_" if ch in _INVALID_DIR_CHARS or ord(ch) < 32 else ch for ch in raw)
    clean = clean.strip(" .")
    return clean or "自定义底图"


def _unique_map_destination(root: str, filename: str) -> str:
    stem, ext = os.path.splitext(os.path.basename(filename))
    stem = _safe_dir_name(stem or "map")
    candidate = os.path.join(root, stem + ext)
    if not os.path.exists(candidate):
        return candidate

    counter = 2
    while True:
        candidate = os.path.join(root, f"{stem}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def import_map_file(
    source_path: str,
    *,
    destination_dir: object | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Copy a user-selected map image into maps/ and return its relative config path."""
    root_base = _base_dir(base_dir)
    source = os.path.abspath(os.fspath(source_path))
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    if not is_map_image(source):
        raise ValueError("Unsupported map image type")

    destination_rel = normalize_map_directory(destination_dir, root_base) if destination_dir is not None else MAPS_DIR_NAME
    root = os.path.abspath(os.path.join(root_base, *destination_rel.split("/")))
    os.makedirs(root, exist_ok=True)

    try:
        if os.path.commonpath([root, source]) == root and os.path.dirname(source) == root:
            return normalize_map_file(os.path.relpath(source, root_base), root_base)
    except (OSError, ValueError):
        pass

    destination = _unique_map_destination(root, os.path.basename(source))
    shutil.copy2(source, destination)
    return normalize_map_file(os.path.relpath(destination, root_base), root_base)


def map_display_name(map_file: object) -> str:
    rel = normalize_map_file(map_file)
    if not rel:
        return "请选择底图"
    name = PurePosixPath(rel).name
    return name or rel


def available_map_files() -> list[str]:
    ensure_maps_dir()
    return iter_map_files(BASE_DIR)


def available_map_directories() -> list[str]:
    ensure_maps_dir()
    return iter_map_directories(BASE_DIR)


def available_map_files_in_directory(directory: object) -> list[str]:
    ensure_maps_dir()
    return iter_map_files_in_directory(BASE_DIR, directory)


def ensure_annotations_dir() -> str:
    path = app_path(ANNOTATIONS_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def normalize_annotation_file(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    rel = _normalize_slashes(_relative_or_basename(raw))
    if not rel:
        return ""

    path = PurePosixPath(rel)
    if ".." in path.parts:
        rel = path.name
        path = PurePosixPath(rel)

    if len(path.parts) == 1 and path.suffix.casefold() in ANNOTATION_FILE_EXTENSIONS:
        return f"{ANNOTATIONS_DIR_NAME}/{path.name}"

    if path.parts and path.parts[0].casefold() == ANNOTATIONS_DIR_NAME:
        return path.as_posix()

    return rel


def available_annotation_files() -> list[str]:
    root = ensure_annotations_dir()
    files: list[str] = []
    try:
        entries = sorted(os.scandir(root), key=lambda item: item.name.casefold())
    except OSError:
        return files
    for entry in entries:
        if entry.is_file() and entry.name.casefold().endswith(ANNOTATION_FILE_EXTENSIONS):
            files.append(f"{ANNOTATIONS_DIR_NAME}/{entry.name}")
    return files


def selected_annotation_file_from_settings(payload: dict | None = None) -> str:
    source = (
        payload
        if payload is not None
        else {"ANNOTATION_FILE": globals().get("ANNOTATION_FILE", settings.get("ANNOTATION_FILE", ""))}
    )
    return normalize_annotation_file(source.get("ANNOTATION_FILE"))


def selected_annotation_path_from_settings(payload: dict | None = None) -> str:
    selected = selected_annotation_file_from_settings(payload)
    return resolve_app_path(selected) if selected else ""


def selected_annotation_exists(payload: dict | None = None) -> bool:
    path = selected_annotation_path_from_settings(payload)
    return bool(path and os.path.isfile(path))


def _unique_annotation_destination(root: str, filename: str) -> str:
    stem, ext = os.path.splitext(os.path.basename(filename))
    stem = stem or "points"
    ext = ext or ".json"
    candidate = os.path.join(root, stem + ext)
    if not os.path.exists(candidate):
        return candidate

    counter = 2
    while True:
        candidate = os.path.join(root, f"{stem}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def import_annotation_file(source_path: str) -> str:
    source = os.path.abspath(os.fspath(source_path))
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    if not source.casefold().endswith(ANNOTATION_FILE_EXTENSIONS):
        raise ValueError("Unsupported annotation file type")

    root = os.path.abspath(ensure_annotations_dir())
    try:
        if os.path.commonpath([root, source]) == root and os.path.dirname(source) == root:
            return normalize_annotation_file(os.path.relpath(source, BASE_DIR))
    except (OSError, ValueError):
        pass

    destination = _unique_annotation_destination(root, os.path.basename(source))
    shutil.copy2(source, destination)
    return normalize_annotation_file(os.path.relpath(destination, BASE_DIR))


def annotation_display_name(annotation_file: object) -> str:
    rel = normalize_annotation_file(annotation_file)
    if not rel:
        return "请选择标注文件"
    name = PurePosixPath(rel).name
    return name or rel


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
        pass
        # v2 引入 CONFIG_VERSION。其他新增字段由 merge_config_payload 自动补齐。
        pass

    if "MAP_FILE" in migrated:
        migrated["MAP_FILE"] = normalize_map_file(migrated.get("MAP_FILE"))
    migrated.pop("LOGIC_MAP_PATH", None)

    if "ANNOTATION_FILE" in migrated:
        migrated["ANNOTATION_FILE"] = normalize_annotation_file(migrated.get("ANNOTATION_FILE"))

    return migrated


def _sync_map_config(payload: dict) -> None:
    if "MAP_FILE" not in payload:
        return
    payload["MAP_FILE"] = normalize_map_file(payload.get("MAP_FILE"))


def _sync_annotation_config(payload: dict) -> None:
    if "ANNOTATION_FILE" not in payload:
        return
    payload["ANNOTATION_FILE"] = normalize_annotation_file(payload.get("ANNOTATION_FILE"))


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
    if "MAP_FILE" in default_config:
        _sync_map_config(merged)
    if "ANNOTATION_FILE" in default_config:
        _sync_annotation_config(merged)
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
    globals()["MAP_FILE"] = selected_map_file_from_settings(current)
    globals()["ANNOTATION_FILE"] = selected_annotation_file_from_settings(current)
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
ANNOTATION_PRESETS = settings.get("ANNOTATION_PRESETS") or []
ANNOTATION_GROUP_EXPANDED = settings.get("ANNOTATION_GROUP_EXPANDED") or {}
ANNOTATION_PANEL_FOLLOW_WINDOW = settings.get("ANNOTATION_PANEL_FOLLOW_WINDOW")
PURE_NAVIGATION_MODE = settings.get("PURE_NAVIGATION_MODE")
WINDOW_LOCK_FOLLOWS_GUIDE = settings.get("WINDOW_LOCK_FOLLOWS_GUIDE")
ANNOTATION_PANEL_OFFSET = settings.get("ANNOTATION_PANEL_OFFSET") or {}
ANNOTATION_PANEL_MAXIMIZED_OFFSET = settings.get("ANNOTATION_PANEL_MAXIMIZED_OFFSET") or {}
ANNOTATION_PANEL_POSITION = settings.get("ANNOTATION_PANEL_POSITION") or {}
ANNOTATION_PANEL_MAXIMIZED_POSITION = settings.get("ANNOTATION_PANEL_MAXIMIZED_POSITION") or {}
QUARK_DOWNLOAD_URL = ""
ROUTE_RESOURCE_URL = ""
ROUTE_RESOURCE_LINKS = []
FEEDBACK_LINKS = []
APP_UPDATE_MANIFEST_URLS = []
APP_UPDATE_LAST_PROMPTED_VERSION = settings.get("APP_UPDATE_LAST_PROMPTED_VERSION") or ""
APP_NOTICE_LAST_ACK_KEY = settings.get("APP_NOTICE_LAST_ACK_KEY") or ""
LICENSE_DATA = settings.get("LICENSE_DATA") or {}
LICENSE_QQ_GROUPS: list = []
LICENSE_VERIFY_ENABLED = False
LICENSE_PUBLIC_KEY = ""


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
MAP_FILE = selected_map_file_from_settings(settings)
ANNOTATION_FILE = selected_annotation_file_from_settings(settings)
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
ACTION_HOTKEYS = settings.get("ACTION_HOTKEYS") or {}
ROUTE_VISITED_POINT_OPACITY = settings.get("ROUTE_VISITED_POINT_OPACITY")
ROUTE_VISITED_ICON_OPACITY = settings.get("ROUTE_VISITED_ICON_OPACITY")
WINDOW_LOCKED_OPACITY = settings.get("WINDOW_LOCKED_OPACITY")
WINDOW_NORMAL_OPACITY = settings.get("WINDOW_NORMAL_OPACITY")

COORD_SCALE_X = settings.get("COORD_SCALE_X")
COORD_SCALE_Y = settings.get("COORD_SCALE_Y")
COORD_OFFSET_X = settings.get("COORD_OFFSET_X")
COORD_OFFSET_Y = settings.get("COORD_OFFSET_Y")
