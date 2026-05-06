"""为 GMT-N 发布目录生成文件级更新清单。

示例：
  python scripts/generate_update_manifest.py dist/GMT-N --version 0.2.0 --base-url https://example.com/gmt-n/0.2.0/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote


PROTECTED_USER_FILES = {
    "routes/progress.json",
    "routes/selected_routes.json",
    "tools/points_get/.cache_17173_locations.json",
}
PROTECTED_USER_PREFIXES = (
    "annotations/",
    "maps/",
    "routes/",
    "tools/",
)
DEFAULT_EXCLUDES = {
    "app-manifest.json",
    "big_map.png",
    "big_map_17173.png",
    "maps/卡洛西亚大陆/big_map_17173.png",
    "maps/卡洛西亚大陆/big_map_17173带传送图标.png",
    "maps/卡洛西亚大陆/big_map_17173带传送点图标.png",
    "installed-manifest.json",
    "update-job.json",
    "config.json.bak",
}
DEFAULT_DELETE_PATHS: tuple[str, ...] = (
    "big_map.png",
    "maps/卡洛西亚大陆/big_map_17173.png",
    "maps/卡洛西亚大陆/big_map_17173带传送图标.png",
    "maps/卡洛西亚大陆/big_map_17173带传送点图标.png",
)
DEFAULT_INCLUDE_PATHS: tuple[str, ...] = (
    "maps/卡洛西亚大陆/big_map_new.png",
)
RUNTIME_CONFIG_STRING_KEYS = (
    "QUARK_DOWNLOAD_URL",
    "ROUTE_RESOURCE_URL",
    "LICENSE_PUBLIC_KEY",
)
RUNTIME_CONFIG_NAMED_LINK_KEYS = ("ROUTE_RESOURCE_LINKS", "FEEDBACK_LINKS", "LICENSE_QQ_GROUPS")
RUNTIME_CONFIG_LIST_KEYS = ("APP_UPDATE_MANIFEST_URLS",)
RUNTIME_CONFIG_STRING_LIST_KEYS = ("APP_ENABLE_VERSIONS",)
RUNTIME_CONFIG_BOOL_KEYS = ("LICENSE_VERIFY_ENABLED",)
APP_STATUS_NORMAL = "normal"
APP_STATUS_NOTICE = "notice"
APP_STATUS_DISABLED = "disabled"
APP_STATUS_VALUES = {APP_STATUS_NORMAL, APP_STATUS_NOTICE, APP_STATUS_DISABLED}
DEFAULT_MIN_SUPPORTED_VERSION_MESSAGE = "当前版本已停止维护，请更新到最新版后继续使用。"
_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?\s*$")


def default_runtime_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "runtime_config.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_base_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError("必须提供 --base-url")
    return value if value.endswith("/") else value + "/"


def is_user_data_path(value: str) -> bool:
    rel = str(value or "").replace("\\", "/")
    return rel in PROTECTED_USER_FILES or any(rel.startswith(prefix) for prefix in PROTECTED_USER_PREFIXES)


def iter_release_files(root: Path, include_paths: set[str] | None = None):
    include_paths = include_paths or set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in include_paths:
            yield path, rel
            continue
        if rel in DEFAULT_EXCLUDES or is_user_data_path(rel):
            continue
        yield path, rel


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def sanitize_delete_paths(values: list[str] | tuple[str, ...] | None) -> list[str]:
    clean_paths: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        rel = str(value or "").replace("\\", "/").strip().lstrip("/")
        if not rel or rel in seen:
            continue
        if rel.startswith("../") or "/../" in rel:
            continue
        seen.add(rel)
        clean_paths.append(rel)
    return clean_paths


def _sanitize_named_links(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url:
            continue
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)
        result.append({"name": name, "url": url})
    return result


def sanitize_runtime_config(payload: dict) -> dict:
    runtime_config: dict = {}
    for key in RUNTIME_CONFIG_STRING_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            runtime_config[key] = value.strip()

    for key in RUNTIME_CONFIG_NAMED_LINK_KEYS:
        named_links = _sanitize_named_links(payload.get(key))
        if named_links:
            runtime_config[key] = named_links

    manifest_urls: list[str] = []
    legacy_manifest_url = payload.get("APP_UPDATE_MANIFEST_URL")
    if isinstance(legacy_manifest_url, str):
        manifest_urls.append(legacy_manifest_url)
    for key in RUNTIME_CONFIG_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            manifest_urls.extend(item for item in value if isinstance(item, str))
    clean_manifest_urls = _dedupe_strings(manifest_urls)
    if clean_manifest_urls:
        runtime_config["APP_UPDATE_MANIFEST_URLS"] = clean_manifest_urls

    for key in RUNTIME_CONFIG_STRING_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            clean_values = _dedupe_strings([item for item in value if isinstance(item, str)])
            if clean_values:
                runtime_config[key] = clean_values

    for key in RUNTIME_CONFIG_BOOL_KEYS:
        value = payload.get(key)
        if isinstance(value, bool):
            runtime_config[key] = value

    return runtime_config


def load_runtime_config(path: Path | str | None) -> dict:
    if path is None:
        return {}
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return sanitize_runtime_config(payload)


def sanitize_app_status(value: str) -> str:
    status = str(value or APP_STATUS_NORMAL).strip().lower()
    return status if status in APP_STATUS_VALUES else APP_STATUS_NORMAL


def parse_version(value: str) -> tuple[int, int, int, str]:
    match = _VERSION_RE.match(str(value or ""))
    if not match:
        raise ValueError(f"版本号格式无效：{value}")
    major, minor, patch, prerelease = match.groups()
    return int(major), int(minor), int(patch), prerelease or ""


def normalize_version(value: str) -> str:
    major, minor, patch, prerelease = parse_version(value)
    base = f"{major}.{minor}.{patch}"
    return f"{base}-{prerelease}" if prerelease else base


def _prerelease_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"[.-]", value):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.lower()))
    return tuple(parts)


def compare_versions(left: str, right: str) -> int:
    left_major, left_minor, left_patch, left_prerelease = parse_version(left)
    right_major, right_minor, right_patch, right_prerelease = parse_version(right)
    left_core = (left_major, left_minor, left_patch)
    right_core = (right_major, right_minor, right_patch)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_prerelease == right_prerelease:
        return 0
    if not left_prerelease:
        return 1
    if not right_prerelease:
        return -1
    return 1 if _prerelease_key(left_prerelease) > _prerelease_key(right_prerelease) else -1


def build_manifest(
    root: Path,
    *,
    version: str,
    base_url: str,
    notes: str,
    requires_launcher_update: bool,
    prompt_update: bool,
    force_update_prompt: bool,
    app_status: str = APP_STATUS_NORMAL,
    app_status_message: str = "",
    app_notice_force_prompt: bool = False,
    min_supported_version: str = "",
    min_supported_version_message: str = "",
    runtime_config_path: Path | str | None = None,
    obsolete_config_keys: list[str] | tuple[str, ...] | None = None,
    delete_paths: list[str] | tuple[str, ...] | None = None,
    include_paths: list[str] | tuple[str, ...] | None = None,
) -> dict:
    files = []
    clean_version = normalize_version(version)
    normalized_base_url = normalize_base_url(base_url)
    clean_app_status = sanitize_app_status(app_status)
    clean_app_status_message = str(app_status_message or "").strip() if clean_app_status != APP_STATUS_NORMAL else ""
    clean_min_supported_version = normalize_version(min_supported_version) if str(min_supported_version or "").strip() else ""
    if clean_min_supported_version and compare_versions(clean_min_supported_version, clean_version) > 0:
        raise ValueError("min_supported_version 不能大于发布版本 version")
    clean_min_supported_version_message = (
        str(min_supported_version_message or "").strip() or DEFAULT_MIN_SUPPORTED_VERSION_MESSAGE
        if clean_min_supported_version
        else ""
    )
    clean_include_paths = set(sanitize_delete_paths([*DEFAULT_INCLUDE_PATHS, *(include_paths or [])]))
    for path, rel in iter_release_files(root, clean_include_paths):
        item = {
            "path": rel,
            "url": normalized_base_url + quote(rel, safe="/"),
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
        if rel == "config.json":
            item["install"] = "merge_config"
        files.append(item)

    manifest = {
        "version": clean_version,
        "notes": notes,
        "app_status": clean_app_status,
        "app_status_message": clean_app_status_message,
        "app_notice_force_prompt": app_notice_force_prompt is True,
        "min_supported_version": clean_min_supported_version,
        "min_supported_version_message": clean_min_supported_version_message,
        "requires_launcher_update": bool(requires_launcher_update),
        "prompt_update": bool(prompt_update),
        "force_update_prompt": bool(force_update_prompt),
        "files": files,
        "delete": sanitize_delete_paths([*DEFAULT_DELETE_PATHS, *(delete_paths or [])]),
    }
    runtime_config = load_runtime_config(runtime_config_path)
    if runtime_config:
        manifest["runtime_config"] = runtime_config
    clean_obsolete_keys: list[str] = []
    seen_obsolete_keys: set[str] = set()
    for item in obsolete_config_keys or []:
        key = str(item or "").strip()
        if not key or key in seen_obsolete_keys:
            continue
        if not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        seen_obsolete_keys.add(key)
        clean_obsolete_keys.append(key)
    if clean_obsolete_keys:
        manifest["obsolete_config_keys"] = clean_obsolete_keys
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 GMT-N 更新清单。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    parser.add_argument("release_dir", help="发布目录，例如 dist/GMT-N")
    parser.add_argument("--version", required=True, help="写入清单的版本号，例如 0.2.0")
    parser.add_argument("--base-url", required=True, help="发布文件所在的基础 URL")
    parser.add_argument("--notes", default="", help="简短更新说明")
    parser.add_argument(
        "--requires-launcher-update",
        action="store_true",
        help="标记此清单需要重启或 updater 接管安装",
    )
    parser.add_argument(
        "--prompt-update",
        action="store_true",
        help="启动后检测到此更新时主动弹窗提示用户安装",
    )
    parser.add_argument(
        "--force-update-prompt",
        action="store_true",
        help="启动后检测到此更新时强制弹窗提示，绕过同版本已提示记录",
    )
    parser.add_argument(
        "--app-status",
        choices=sorted(APP_STATUS_VALUES),
        default=APP_STATUS_NORMAL,
        help="启动公告状态：normal/notice/disabled。",
    )
    parser.add_argument(
        "--app-status-message",
        default="",
        help="notice 或 disabled 时显示给用户的说明文字。",
    )
    parser.add_argument(
        "--app-notice-force-prompt",
        action="store_true",
        help="app_status=notice 时每次启动都弹窗显示公告。",
    )
    parser.add_argument(
        "--min-supported-version",
        default="",
        help="低于此版本的客户端必须更新后才能继续使用，例如 0.1.2。",
    )
    parser.add_argument(
        "--min-supported-version-message",
        default="",
        help="低版本强制更新时显示给用户的说明文字。",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="app-manifest.json",
        help="输出清单路径，默认写到当前目录的 app-manifest.json。",
    )
    parser.add_argument(
        "--runtime-config",
        default=str(default_runtime_config_path()),
        help="运行时配置 JSON 路径，默认读取仓库根目录的 runtime_config.json。",
    )
    parser.add_argument(
        "--obsolete-config-key",
        action="append",
        default=[],
        help="可重复：声明更新安装时应从用户 config.json 清理的废弃配置键。",
    )
    parser.add_argument(
        "--delete",
        action="append",
        default=[],
        help="可重复：声明更新安装时需要删除的旧文件。",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="显式把默认受保护的发布路径加入清单，例如 maps/custom.png。",
    )
    args = parser.parse_args(argv)

    root = Path(args.release_dir).resolve()
    if not root.is_dir():
        raise SystemExit(f"发布目录不存在：{root}")

    manifest = build_manifest(
        root,
        version=args.version,
        base_url=args.base_url,
        notes=args.notes,
        requires_launcher_update=args.requires_launcher_update,
        prompt_update=args.prompt_update,
        force_update_prompt=args.force_update_prompt,
        app_status=args.app_status,
        app_status_message=args.app_status_message,
        app_notice_force_prompt=args.app_notice_force_prompt,
        min_supported_version=args.min_supported_version,
        min_supported_version_message=args.min_supported_version_message,
        runtime_config_path=args.runtime_config,
        obsolete_config_keys=args.obsolete_config_key,
        delete_paths=args.delete,
        include_paths=args.include,
    )
    output = Path(args.output)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"已写入 {output}，共 {len(manifest['files'])} 个文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
