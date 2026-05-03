"""GMT-N 独立更新器入口。

更新器只安装主程序已经下载并校验过的 staging 文件，不负责联网下载。
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


CONFIG_INSTALL_MODE = "merge_config"
COPY_INSTALL_MODE = "copy"
INSTALLED_MANIFEST = "installed-manifest.json"
class UpdaterError(RuntimeError):
    """更新器安装失败时抛出。"""


def _local_app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "GMT-N"
    return Path.home() / ".gmt-n"


def _log_path() -> Path:
    path = _local_app_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "update.log"


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        with _log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def normalize_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        raise UpdaterError("更新任务包含空路径。")
    if raw.startswith("/") or raw.startswith("../") or "/../" in raw or raw == "..":
        raise UpdaterError(f"更新任务包含非法路径：{raw}")
    normalized = os.path.normpath(raw).replace("\\", "/")
    if normalized.startswith("../") or normalized == ".." or os.path.isabs(normalized):
        raise UpdaterError(f"更新任务包含非法路径：{raw}")
    return normalized


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise UpdaterError(f"JSON 顶层必须是对象：{path}")
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def merge_dict(defaults: dict, user_values: dict, obsolete_config_keys: set[str] | None = None) -> dict:
    merged: dict = {}
    for key, default_value in defaults.items():
        if key not in user_values:
            merged[key] = default_value
            continue
        user_value = user_values[key]
        if isinstance(default_value, dict):
            merged[key] = (
                merge_dict(default_value, user_value, obsolete_config_keys)
                if isinstance(user_value, dict)
                else default_value
            )
        elif _is_compatible_value(default_value, user_value):
            merged[key] = user_value
        else:
            merged[key] = default_value
    for key, user_value in user_values.items():
        if key not in defaults:
            if obsolete_config_keys is not None and key in obsolete_config_keys:
                continue
            merged[key] = user_value
    if "CONFIG_VERSION" in defaults:
        merged["CONFIG_VERSION"] = defaults["CONFIG_VERSION"]
    return merged


def merge_config_file(path: Path, defaults: dict, obsolete_config_keys: set[str] | None = None) -> None:
    if path.exists():
        try:
            user_config = read_json(path)
        except Exception:
            user_config = {}
    else:
        user_config = {}
    write_json(path, merge_dict(defaults, user_config, obsolete_config_keys))


def wait_for_process_exit(pid: int, *, timeout: float = 30.0) -> bool:
    if pid <= 0 or pid == os.getpid():
        return True
    if sys.platform.startswith("win"):
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(pid))
        if not handle:
            return True
        try:
            result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            return result != wait_timeout
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.25)
    return False


def backup_root_for(version: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = _local_app_data_dir() / "update-backup" / f"{version}-{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def backup_target(app_dir: Path, backup_root: Path, relative_path: str, backed_up: dict[str, bool]) -> None:
    target = app_dir / relative_path
    if not target.exists():
        backed_up[relative_path] = False
        return
    backup = backup_root / relative_path
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    backed_up[relative_path] = True


def restore_backups(app_dir: Path, backup_root: Path, backed_up: dict[str, bool]) -> None:
    for relative_path, existed in backed_up.items():
        target = app_dir / relative_path
        if existed:
            backup = backup_root / relative_path
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def installed_manifest_payload(job: dict) -> dict:
    manifest = job.get("manifest") if isinstance(job.get("manifest"), dict) else {}
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    return {
        "version": str(manifest.get("version") or job.get("version") or ""),
        "files": {
            normalize_relative_path(str(item.get("path") or "")): {
                "sha256": str(item.get("sha256") or ""),
                "size": int(item.get("size") or 0),
                "install": str(item.get("install") or COPY_INSTALL_MODE),
            }
            for item in files
            if isinstance(item, dict)
        },
    }


def validate_job(job: dict) -> tuple[Path, Path, list[dict], list[str], set[str]]:
    app_dir = Path(str(job.get("app_dir") or "")).resolve()
    staging_dir = Path(str(job.get("staging_dir") or "")).resolve()
    if not app_dir.is_dir():
        raise UpdaterError(f"安装目录不存在：{app_dir}")
    if not staging_dir.is_dir():
        raise UpdaterError(f"更新暂存目录不存在：{staging_dir}")

    files: list[dict] = []
    for item in job.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = normalize_relative_path(str(item.get("path") or ""))
        install = str(item.get("install") or COPY_INSTALL_MODE)
        if install not in {COPY_INSTALL_MODE, CONFIG_INSTALL_MODE}:
            raise UpdaterError(f"未知安装方式：{install}")
        if install == CONFIG_INSTALL_MODE and path != "config.json":
            raise UpdaterError("merge_config 只能用于 config.json。")
        files.append(
            {
                "path": path,
                "sha256": str(item.get("sha256") or "").lower(),
                "install": install,
            }
        )

    delete: list[str] = []
    for item in job.get("delete") or []:
        path = normalize_relative_path(str(item or ""))
        delete.append(path)

    obsolete_config_keys: set[str] = set()
    for item in job.get("obsolete_config_keys") or []:
        key = str(item or "").strip()
        if key and key.replace("_", "").isalnum() and not key[0].isdigit():
            obsolete_config_keys.add(key)

    return app_dir, staging_dir, files, delete, obsolete_config_keys


def install_update_job(job_path: str | os.PathLike[str]) -> bool:
    job_file = Path(job_path).resolve()
    job = read_json(job_file)
    app_dir, staging_dir, files, delete, obsolete_config_keys = validate_job(job)
    version = str(job.get("version") or "unknown")
    backup_root = backup_root_for(version)
    backed_up: dict[str, bool] = {}

    try:
        for item in files:
            relative_path = item["path"]
            source = staging_dir / relative_path
            if not source.exists():
                raise UpdaterError(f"缺少已下载文件：{relative_path}")
            expected_hash = item["sha256"]
            if expected_hash and sha256_file(source) != expected_hash:
                raise UpdaterError(f"文件校验失败：{relative_path}")

            backup_target(app_dir, backup_root, relative_path, backed_up)
            if item["install"] == CONFIG_INSTALL_MODE:
                defaults = read_json(source)
                merge_config_file(app_dir / "config.json", defaults, obsolete_config_keys)
                continue
            target = app_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))

        for relative_path in delete:
            backup_target(app_dir, backup_root, relative_path, backed_up)
            target = app_dir / relative_path
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

        write_json(app_dir / INSTALLED_MANIFEST, installed_manifest_payload(job))
        log(f"更新安装成功：{version}")
        return True
    except Exception as exc:
        log(f"更新安装失败，开始回滚：{exc}")
        restore_backups(app_dir, backup_root, backed_up)
        raise


def start_app(exe_path: str | os.PathLike[str]) -> None:
    exe = Path(exe_path)
    if not exe.exists():
        log(f"未找到主程序，无法重启：{exe}")
        return
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GMT-N 独立更新器。")
    parser.add_argument("--pid", type=int, required=True, help="等待退出的主程序进程 ID")
    parser.add_argument("--job", required=True, help="主程序生成的 update-job.json 路径")
    args = parser.parse_args(argv)

    try:
        job = read_json(Path(args.job))
        exe_path = str(job.get("exe_path") or "")
        if not wait_for_process_exit(args.pid):
            raise UpdaterError("等待主程序退出超时。")
        time.sleep(0.8)
        install_update_job(args.job)
        start_app(exe_path)
        return 0
    except Exception as exc:
        log(f"更新器执行失败：{exc}")
        try:
            job = read_json(Path(args.job))
            start_app(str(job.get("exe_path") or ""))
        except Exception as start_exc:
            log(f"尝试重启旧版失败：{start_exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
