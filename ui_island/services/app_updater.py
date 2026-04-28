"""基于更新清单的应用更新检查和文件级安装。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

import requests

import config
from ..app.app_info import APP_UPDATE_MANIFEST_URLS, APP_VERSION
from ..design import strings


INSTALLED_MANIFEST = "installed-manifest.json"
UPDATE_JOB_FILE = "update-job.json"
CONFIG_INSTALL_MODE = "merge_config"
COPY_INSTALL_MODE = "copy"
APP_STATUS_NORMAL = "normal"
APP_STATUS_NOTICE = "notice"
APP_STATUS_DISABLED = "disabled"
APP_STATUS_VALUES = {APP_STATUS_NORMAL, APP_STATUS_NOTICE, APP_STATUS_DISABLED}
DEFAULT_APP_STATUS_MESSAGE = "请关注最新公告或维护说明。"
PROTECTED_USER_FILES = {
    "routes/progress.json",
    "routes/selected_routes.json",
    "tools/points_get/.cache_17173_locations.json",
}
PROTECTED_USER_PREFIXES = (
    "routes/",
    "tools/",
)
RESTART_PATHS = (
    "GMT-N.exe",
    "updater.exe",
    "_internal/",
    "app/current/",
)
RUNTIME_CONFIG_STRING_KEYS = (
    "QUARK_DOWNLOAD_URL",
    "ROUTE_RESOURCE_URL",
    "DOCUMENTATION_URL",
    "FEEDBACK_BILIBILI_URL",
    "FEEDBACK_QQ_GROUP",
)
RUNTIME_CONFIG_LIST_KEYS = ("APP_UPDATE_MANIFEST_URLS",)


@dataclass(frozen=True)
class ManifestFile:
    path: str
    url: str
    sha256: str
    size: int
    install: str = COPY_INSTALL_MODE


@dataclass(frozen=True)
class AppUpdateManifest:
    version: str
    notes: str
    files: tuple[ManifestFile, ...]
    delete: tuple[str, ...]
    app_status: str = APP_STATUS_NORMAL
    app_status_message: str = ""
    app_notice_force_prompt: bool = False
    requires_launcher_update: bool = False
    prompt_update: bool = False
    force_update_prompt: bool = False
    source_base_url: str = ""
    runtime_config: dict[str, object] = field(default_factory=dict)
    obsolete_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileChange:
    file: ManifestFile
    reason: str


@dataclass(frozen=True)
class AppUpdateCheckResult:
    ok: bool
    current_version: str
    latest_version: str = ""
    has_update: bool = False
    app_status: str = APP_STATUS_NORMAL
    app_status_message: str = ""
    app_notice_force_prompt: bool = False
    prompt_update: bool = False
    force_update_prompt: bool = False
    notes: str = ""
    changed_files: tuple[FileChange, ...] = ()
    delete_files: tuple[str, ...] = ()
    skipped_conflicts: tuple[str, ...] = ()
    download_size: int = 0
    requires_restart: bool = False
    manifest: AppUpdateManifest | None = None
    error: str = ""


@dataclass(frozen=True)
class AppUpdateInstallResult:
    ok: bool
    version: str = ""
    installed_files: tuple[str, ...] = ()
    skipped_conflicts: tuple[str, ...] = ()
    requires_restart: bool = False
    error: str = ""


class ManifestError(RuntimeError):
    """更新清单无效时抛出。"""


_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?\s*$")


@dataclass(frozen=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease: str = ""


def parse_version(value: str) -> ParsedVersion:
    match = _VERSION_RE.match(str(value or ""))
    if not match:
        raise ValueError(f"版本号格式无效：{value}")
    major, minor, patch, prerelease = match.groups()
    return ParsedVersion(int(major), int(minor), int(patch), prerelease or "")


def normalize_version(value: str) -> str:
    parsed = parse_version(value)
    base = f"{parsed.major}.{parsed.minor}.{parsed.patch}"
    return f"{base}-{parsed.prerelease}" if parsed.prerelease else base


def compare_versions(left: str, right: str) -> int:
    left_parsed = parse_version(left)
    right_parsed = parse_version(right)
    left_core = (left_parsed.major, left_parsed.minor, left_parsed.patch)
    right_core = (right_parsed.major, right_parsed.minor, right_parsed.patch)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_parsed.prerelease == right_parsed.prerelease:
        return 0
    if not left_parsed.prerelease:
        return 1
    if not right_parsed.prerelease:
        return -1
    return 1 if _prerelease_key(left_parsed.prerelease) > _prerelease_key(right_parsed.prerelease) else -1


def _prerelease_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"[.-]", value):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.lower()))
    return tuple(parts)


def _normalize_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        raise ManifestError("更新清单包含空路径。")
    if raw.startswith("/") or raw.startswith("../") or "/../" in raw or raw == "..":
        raise ManifestError(f"更新清单包含非法路径：{raw}")
    normalized = os.path.normpath(raw).replace("\\", "/")
    if normalized.startswith("../") or normalized == ".." or os.path.isabs(normalized):
        raise ManifestError(f"更新清单包含非法路径：{raw}")
    return normalized


def _is_user_data_path(value: str) -> bool:
    path = str(value or "").replace("\\", "/")
    return path in PROTECTED_USER_FILES or any(path.startswith(prefix) for prefix in PROTECTED_USER_PREFIXES)


def _app_path(relative_path: str) -> Path:
    return Path(config.app_path(*relative_path.split("/")))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象。")
    return payload


def _write_json_file(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _dedupe_runtime_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def sanitize_runtime_config(payload: Any) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}

    runtime_config: dict[str, object] = {}
    for key in RUNTIME_CONFIG_STRING_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            runtime_config[key] = value.strip()

    manifest_urls: list[str] = []
    legacy_manifest_url = payload.get("APP_UPDATE_MANIFEST_URL")
    if isinstance(legacy_manifest_url, str):
        manifest_urls.append(legacy_manifest_url)
    for key in RUNTIME_CONFIG_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            manifest_urls.extend(item for item in value if isinstance(item, str))
    clean_manifest_urls = _dedupe_runtime_strings(manifest_urls)
    if clean_manifest_urls:
        runtime_config["APP_UPDATE_MANIFEST_URLS"] = clean_manifest_urls

    return runtime_config


def apply_runtime_config(runtime_config: dict[str, object] | None) -> None:
    if not isinstance(runtime_config, dict) or not runtime_config:
        return

    clean_config = sanitize_runtime_config(runtime_config)
    if not clean_config:
        return

    config.settings.update(clean_config)
    for key, value in clean_config.items():
        setattr(config, key, value)


def sanitize_app_status(value: Any) -> str:
    status = str(value or APP_STATUS_NORMAL).strip().lower()
    return status if status in APP_STATUS_VALUES else APP_STATUS_NORMAL


def sanitize_app_status_message(value: Any, status: str) -> str:
    if status == APP_STATUS_NORMAL:
        return ""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_APP_STATUS_MESSAGE


def sanitize_app_notice_force_prompt(value: Any) -> bool:
    return value is True


def app_notice_ack_key(message: str) -> str:
    clean_message = str(message or "").strip()
    return hashlib.sha256(clean_message.encode("utf-8")).hexdigest()


def should_show_app_notice(
    status: str,
    message: str,
    *,
    force_prompt: bool = False,
    last_ack_key: str = "",
) -> bool:
    if sanitize_app_status(status) != APP_STATUS_NOTICE:
        return False
    if force_prompt:
        return True
    notice_key = app_notice_ack_key(message)
    return notice_key != str(last_ack_key or "").strip()


def parse_app_manifest(payload: dict[str, Any], *, source_base_url: str = "") -> AppUpdateManifest:
    if not isinstance(payload, dict) or not payload:
        raise ManifestError(strings.UPDATE_ERROR_MANIFEST_EMPTY)

    version = normalize_version(str(payload.get("version") or ""))
    app_status = sanitize_app_status(payload.get("app_status"))
    app_status_message = sanitize_app_status_message(payload.get("app_status_message"), app_status)
    app_notice_force_prompt = sanitize_app_notice_force_prompt(payload.get("app_notice_force_prompt"))
    files: list[ManifestFile] = []
    for item in payload.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = _normalize_relative_path(str(item.get("path") or ""))
        if _is_user_data_path(path):
            continue
        url = str(item.get("url") or "").strip()
        sha256 = str(item.get("sha256") or "").strip().lower()
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        install = str(item.get("install") or COPY_INSTALL_MODE).strip() or COPY_INSTALL_MODE
        if install not in {COPY_INSTALL_MODE, CONFIG_INSTALL_MODE}:
            raise ManifestError(f"未知安装方式：{install}")
        if install == CONFIG_INSTALL_MODE and path != "config.json":
            raise ManifestError("merge_config 只能用于 config.json。")
        if not url:
            raise ManifestError(f"更新文件缺少 url：{path}")
        if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
            raise ManifestError(f"更新文件 sha256 无效：{path}")
        if size < 0:
            raise ManifestError(f"更新文件 size 无效：{path}")
        files.append(ManifestFile(path=path, url=url, sha256=sha256, size=size, install=install))

    delete: list[str] = []
    for item in payload.get("delete") or []:
        path = _normalize_relative_path(str(item or ""))
        if _is_user_data_path(path) or path == "config.json":
            continue
        delete.append(path)

    obsolete_config_keys: list[str] = []
    seen_obsolete_keys: set[str] = set()
    for item in payload.get("obsolete_config_keys") or []:
        key = str(item or "").strip()
        if not key or key in seen_obsolete_keys:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        seen_obsolete_keys.add(key)
        obsolete_config_keys.append(key)

    return AppUpdateManifest(
        version=version,
        notes=str(payload.get("notes") or "").strip(),
        files=tuple(files),
        delete=tuple(delete),
        app_status=app_status,
        app_status_message=app_status_message,
        app_notice_force_prompt=app_notice_force_prompt,
        requires_launcher_update=bool(payload.get("requires_launcher_update", False)),
        prompt_update=bool(payload.get("prompt_update", False)),
        force_update_prompt=bool(payload.get("force_update_prompt", False)),
        source_base_url=source_base_url,
        runtime_config=sanitize_runtime_config(payload.get("runtime_config")),
        obsolete_config_keys=tuple(obsolete_config_keys),
    )


def _load_installed_manifest(path: Path | None = None) -> dict:
    manifest_path = path or _app_path(INSTALLED_MANIFEST)
    if not manifest_path.exists():
        return {}
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _installed_hashes(payload: dict) -> dict[str, str]:
    files = payload.get("files")
    if not isinstance(files, dict):
        return {}
    result: dict[str, str] = {}
    for path, info in files.items():
        if isinstance(info, dict):
            sha256 = str(info.get("sha256") or "").lower()
        else:
            sha256 = str(info or "").lower()
        if sha256:
            result[_normalize_relative_path(str(path))] = sha256
    return result


def _is_restart_file(path: str, manifest: AppUpdateManifest) -> bool:
    if manifest.requires_launcher_update:
        return True
    return any(path == restart_path.rstrip("/") or path.startswith(restart_path) for restart_path in RESTART_PATHS)


def build_update_plan(
    manifest: AppUpdateManifest,
    *,
    current_version: str = APP_VERSION,
    installed_manifest: dict | None = None,
) -> AppUpdateCheckResult:
    try:
        current = normalize_version(current_version)
    except ValueError as exc:
        return AppUpdateCheckResult(ok=False, current_version=current_version, error=f"本地版本号无效：{exc}")

    installed = installed_manifest if installed_manifest is not None else _load_installed_manifest()
    installed_hashes = _installed_hashes(installed)
    changed: list[FileChange] = []
    conflicts: list[str] = []
    download_size = 0
    requires_restart = manifest.requires_launcher_update
    manifest_version_newer = compare_versions(manifest.version, current) > 0

    for file in manifest.files:
        path = file.path
        if _is_user_data_path(path):
            continue
        local_path = _app_path(path)
        installed_hash = installed_hashes.get(path)
        if file.install == CONFIG_INSTALL_MODE:
            if installed_hash == file.sha256:
                continue
            if installed_hash or manifest_version_newer:
                changed.append(FileChange(file=file, reason="config-defaults"))
                download_size += file.size
            continue

        if not local_path.exists():
            changed.append(FileChange(file=file, reason="missing"))
            download_size += file.size
            requires_restart = requires_restart or _is_restart_file(path, manifest)
            continue

        try:
            local_hash = _sha256_file(local_path)
        except OSError:
            changed.append(FileChange(file=file, reason="unreadable"))
            download_size += file.size
            requires_restart = requires_restart or _is_restart_file(path, manifest)
            continue

        if local_hash == file.sha256:
            continue
        if installed_hash and local_hash != installed_hash:
            conflicts.append(path)
            continue
        changed.append(FileChange(file=file, reason="changed"))
        download_size += file.size
        requires_restart = requires_restart or _is_restart_file(path, manifest)

    safe_delete: list[str] = []
    for path in manifest.delete:
        if _is_user_data_path(path):
            continue
        local_path = _app_path(path)
        if not local_path.exists():
            continue
        installed_hash = installed_hashes.get(path)
        if installed_hash:
            try:
                if _sha256_file(local_path) != installed_hash:
                    conflicts.append(path)
                    continue
            except OSError:
                conflicts.append(path)
                continue
        safe_delete.append(path)
        requires_restart = requires_restart or _is_restart_file(path, manifest)

    has_update = bool(changed or safe_delete or manifest_version_newer)
    return AppUpdateCheckResult(
        ok=True,
        current_version=current,
        latest_version=manifest.version,
        has_update=has_update,
        app_status=manifest.app_status,
        app_status_message=manifest.app_status_message,
        app_notice_force_prompt=manifest.app_notice_force_prompt,
        prompt_update=manifest.prompt_update,
        force_update_prompt=manifest.force_update_prompt,
        notes=manifest.notes,
        changed_files=tuple(changed),
        delete_files=tuple(safe_delete),
        skipped_conflicts=tuple(dict.fromkeys(conflicts)),
        download_size=download_size,
        requires_restart=requires_restart,
        manifest=manifest,
    )


def should_show_startup_update_prompt(result: AppUpdateCheckResult, last_prompted_version: str = "") -> bool:
    if not result.ok or not result.has_update:
        return False
    if result.force_update_prompt:
        return True
    if not result.prompt_update:
        return False
    last_prompted = str(last_prompted_version or "")
    return not (result.latest_version and result.latest_version == last_prompted)


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        clean = str(url or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _configured_manifest_urls(manifest_url: str | None) -> list[str]:
    if manifest_url is not None:
        return _dedupe_urls([manifest_url])

    urls: list[str] = []
    configured_urls = getattr(config, "APP_UPDATE_MANIFEST_URLS", None)
    if isinstance(configured_urls, (list, tuple)):
        urls.extend(str(url) for url in configured_urls)
    urls.extend(str(url) for url in APP_UPDATE_MANIFEST_URLS)
    return _dedupe_urls(urls)


def _base_url_from_manifest_url(url: str) -> str:
    clean = str(url or "").strip()
    if not clean:
        return ""
    return clean.rsplit("/", 1)[0] + "/"


def _join_update_url(base_url: str, relative_path: str) -> str:
    split = urlsplit(str(base_url or ""))
    base_path = split.path
    if not base_path.endswith("/"):
        base_path += "/"
    encoded_path = quote(str(relative_path or "").replace("\\", "/"), safe="/")
    return urlunsplit((split.scheme, split.netloc, base_path + encoded_path, "", ""))


def check_app_update(
    *,
    manifest_url: str | None = None,
    current_version: str = APP_VERSION,
    timeout: float = 10.0,
    session: Any | None = None,
) -> AppUpdateCheckResult:
    urls = _configured_manifest_urls(manifest_url)
    if not urls:
        return AppUpdateCheckResult(
            ok=False,
            current_version=current_version,
            error=strings.UPDATE_ERROR_NO_MANIFEST_URL,
        )

    client = session or requests
    errors: list[str] = []
    for url in urls:
        try:
            response = client.get(url, timeout=timeout, headers={"User-Agent": "GMT-N app updater"})
        except requests.RequestException as exc:
            errors.append(strings.UPDATE_ERROR_SOURCE_CONNECT_FMT.format(error=exc))
            continue

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code != 200:
            errors.append(strings.UPDATE_ERROR_SOURCE_HTTP_FMT.format(status_code=status_code))
            continue

        try:
            manifest = parse_app_manifest(response.json(), source_base_url=_base_url_from_manifest_url(url))
        except (ValueError, ManifestError) as exc:
            errors.append(str(exc))
            continue

        apply_runtime_config(manifest.runtime_config)
        return build_update_plan(manifest, current_version=current_version)

    error = strings.UPDATE_ERROR_ALL_SOURCES_FAILED_FMT.format(count=len(urls))
    if errors:
        error = f"{error}\n" + "\n".join(f"- {item}" for item in errors)
    return AppUpdateCheckResult(ok=False, current_version=current_version, error=error)


ProgressCallback = Callable[[int, int, str], None]


def _download_file(
    url: str,
    target: Path,
    *,
    timeout: float,
    session: Any | None,
    progress_callback: ProgressCallback | None = None,
    downloaded_before: int = 0,
    total_size: int = 0,
    display_path: str = "",
) -> int:
    client = session or requests
    try:
        response = client.get(url, timeout=timeout, stream=True, headers={"User-Agent": "GMT-N app updater"})
    except requests.RequestException as exc:
        raise RuntimeError(strings.UPDATE_ERROR_DOWNLOAD_FAILED_FMT.format(error=exc)) from exc
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        raise RuntimeError(strings.UPDATE_ERROR_DOWNLOAD_HTTP_FMT.format(status_code=status_code, url=url))
    target.parent.mkdir(parents=True, exist_ok=True)
    downloaded = int(downloaded_before)
    try:
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total_size, display_path)
    except requests.RequestException as exc:
        raise RuntimeError(strings.UPDATE_ERROR_DOWNLOAD_FAILED_FMT.format(error=exc)) from exc
    return downloaded


def _download_urls_for_change(manifest: AppUpdateManifest, file: ManifestFile) -> list[str]:
    urls: list[str] = []
    if manifest.source_base_url:
        urls.append(_join_update_url(manifest.source_base_url, file.path))
    urls.append(file.url)
    return _dedupe_urls(urls)


def download_changed_files(
    plan: AppUpdateCheckResult,
    *,
    timeout: float = 30.0,
    session: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    if not plan.ok or plan.manifest is None:
        raise RuntimeError(plan.error or strings.UPDATE_ERROR_PLAN_INVALID)
    staging = Path(tempfile.mkdtemp(prefix="gmt-n-update-"))
    total_size = sum(max(0, change.file.size) for change in plan.changed_files)
    downloaded = 0
    for change in plan.changed_files:
        target = staging / change.file.path
        if progress_callback is not None:
            progress_callback(downloaded, total_size, change.file.path)
        last_error: Exception | None = None
        file_start = downloaded
        for url in _download_urls_for_change(plan.manifest, change.file):
            try:
                candidate_downloaded = _download_file(
                    url,
                    target,
                    timeout=timeout,
                    session=session,
                    progress_callback=progress_callback,
                    downloaded_before=file_start,
                    total_size=total_size,
                    display_path=change.file.path,
                )
                actual = _sha256_file(target)
                if actual != change.file.sha256:
                    raise RuntimeError(strings.UPDATE_ERROR_FILE_HASH_FMT.format(path=change.file.path))
                downloaded = candidate_downloaded
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                try:
                    target.unlink(missing_ok=True)
                except Exception:
                    pass
        if last_error is not None:
            raise RuntimeError(str(last_error))
    if progress_callback is not None:
        progress_callback(total_size, total_size, "")
    return staging


def install_non_restart_update(plan: AppUpdateCheckResult, staging: Path) -> AppUpdateInstallResult:
    if plan.requires_restart:
        return AppUpdateInstallResult(
            ok=False,
            version=plan.latest_version,
            requires_restart=True,
            error=strings.UPDATE_ERROR_RESTART_REQUIRED,
        )
    if plan.manifest is None:
        return AppUpdateInstallResult(ok=False, error=strings.UPDATE_ERROR_MANIFEST_EMPTY)

    installed_files: list[str] = []
    try:
        for change in plan.changed_files:
            source = staging / change.file.path
            if change.file.install == CONFIG_INSTALL_MODE:
                defaults = _read_json_file(str(source))
                config.merge_config_file(config.CONFIG_FILE, defaults, plan.manifest.obsolete_config_keys)
                installed_files.append(change.file.path)
                continue
            target = _app_path(change.file.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            installed_files.append(change.file.path)

        for path in plan.delete_files:
            target = _app_path(path)
            if target.exists():
                target.unlink()
                installed_files.append(path)

        _write_installed_manifest(plan.manifest)
    except Exception as exc:
        return AppUpdateInstallResult(
            ok=False,
            version=plan.latest_version,
            installed_files=tuple(installed_files),
            skipped_conflicts=plan.skipped_conflicts,
            error=str(exc),
        )

    return AppUpdateInstallResult(
        ok=True,
        version=plan.latest_version,
        installed_files=tuple(installed_files),
        skipped_conflicts=plan.skipped_conflicts,
    )


def _write_installed_manifest(manifest: AppUpdateManifest) -> None:
    payload = {
        "version": manifest.version,
        "files": {
            file.path: {
                "sha256": file.sha256,
                "size": file.size,
                "install": file.install,
            }
            for file in manifest.files
            if not _is_user_data_path(file.path)
        },
    }
    _write_json_file(str(_app_path(INSTALLED_MANIFEST)), payload)


def _manifest_files_payload(manifest: AppUpdateManifest) -> list[dict]:
    return [
        {
            "path": file.path,
            "sha256": file.sha256,
            "size": file.size,
            "install": file.install,
        }
        for file in manifest.files
        if not _is_user_data_path(file.path)
    ]


def write_restart_update_job(
    plan: AppUpdateCheckResult,
    staging: Path,
    *,
    app_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """把需要重启安装的更新任务写入 staging/update-job.json。"""
    if not plan.ok or plan.manifest is None:
        raise RuntimeError(plan.error or strings.UPDATE_ERROR_PLAN_INVALID)

    root = Path(app_dir) if app_dir is not None else Path(config.BASE_DIR)
    job = {
        "version": plan.latest_version,
        "app_dir": str(root),
        "staging_dir": str(staging),
        "exe_path": str(root / "GMT-N.exe"),
        "files": [
            {
                "path": change.file.path,
                "sha256": change.file.sha256,
                "size": change.file.size,
                "install": change.file.install,
            }
            for change in plan.changed_files
        ],
        "delete": list(plan.delete_files),
        "obsolete_config_keys": list(plan.manifest.obsolete_config_keys),
        "skipped_conflicts": list(plan.skipped_conflicts),
        "manifest": {
            "version": plan.manifest.version,
            "files": _manifest_files_payload(plan.manifest),
        },
    }
    job_path = staging / UPDATE_JOB_FILE
    _write_json_file(str(job_path), job)
    return job_path


def start_restart_update(
    plan: AppUpdateCheckResult,
    staging: Path,
    *,
    parent_pid: int | None = None,
    app_dir: str | os.PathLike[str] | None = None,
) -> AppUpdateInstallResult:
    """启动随包 updater.exe，并把真正替换动作交给独立进程。"""
    root = Path(app_dir) if app_dir is not None else Path(config.BASE_DIR)
    updater_path = root / "updater.exe"
    if not updater_path.exists():
        return AppUpdateInstallResult(
            ok=False,
            version=plan.latest_version,
            requires_restart=True,
            error=strings.UPDATE_ERROR_UPDATER_MISSING_FMT.format(path=updater_path),
        )

    try:
        job_path = write_restart_update_job(plan, staging, app_dir=root)
        runner_path = staging / "updater-runner.exe"
        shutil.copy2(updater_path, runner_path)
        pid = int(parent_pid if parent_pid is not None else os.getpid())
        subprocess.Popen(
            [str(runner_path), "--pid", str(pid), "--job", str(job_path)],
            cwd=str(root),
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0,
        )
    except Exception as exc:
        return AppUpdateInstallResult(
            ok=False,
            version=plan.latest_version,
            requires_restart=True,
            error=strings.UPDATE_ERROR_UPDATER_START_FAILED_FMT.format(error=exc),
        )

    return AppUpdateInstallResult(
        ok=True,
        version=plan.latest_version,
        requires_restart=True,
        installed_files=tuple(change.file.path for change in plan.changed_files),
        skipped_conflicts=plan.skipped_conflicts,
    )


def cleanup_staging(staging: Path) -> None:
    try:
        shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        pass
