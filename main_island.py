"""灵动岛版跟点器主入口。

用法：
    python main_island.py            # SIFT 引擎
    python main_island.py --engine sift  # 兼容旧启动命令
"""
from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import traceback
from collections.abc import Callable
from datetime import datetime

import numpy as np
from PySide6.QtWidgets import QApplication

from Plan_SIFT.hybrid_tracker import HybridTracker
import config
from auth import get_machine_fingerprint_display, is_license_valid, verify_license

# 把 C 层崩溃（段错误等）的栈写到日志，否则 Qt native crash 会静默退出
try:
    _logs_dir = config.app_path("logs")
    os.makedirs(_logs_dir, exist_ok=True)
    _fault_log = open(os.path.join(_logs_dir, "fault.log"), "a", buffering=1, encoding="utf-8")
    faulthandler.enable(_fault_log)
except Exception:
    faulthandler.enable()
from ui_island.services.image_io import imread_unicode
from ui_island.state.tracking import BaseTracker, TrackResult, TrackState
from ui_island.services.route_manager import RouteManager
from ui_island import IslandWindow
from ui_island.dialogs.minimap_selector import run_minimap_calibrator


class MissingMapTracker(BaseTracker):
    map_available = False

    def __init__(self, map_path: str | None, error: str = "") -> None:
        self.map_path = map_path or ""
        self.error = error
        self.logic_map_bgr = np.zeros((1024, 1024, 3), dtype=np.uint8)
        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        return TrackResult(TrackState.SEARCHING, latency_ms=0.0)

    def set_anchor(self, x: int, y: int) -> None:
        return None


class LoadingMapTracker(BaseTracker):
    map_initializing = True

    def __init__(self, map_path: str, logic_map_bgr: np.ndarray) -> None:
        self.map_path = map_path
        self.logic_map_bgr = logic_map_bgr
        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        return TrackResult(TrackState.SEARCHING, latency_ms=0.0)

    def set_anchor(self, x: int, y: int) -> None:
        return None


def build_tracker() -> tuple[BaseTracker, Callable[[], BaseTracker] | None]:
    config.ensure_maps_dir()
    map_path = config.selected_map_path_from_settings()
    if not config.selected_map_exists():
        return MissingMapTracker(map_path), None
    from Plan_SIFT import SiftTracker, has_valid_descriptor_cache
    try:
        if has_valid_descriptor_cache(map_path):
            return HybridTracker(SiftTracker()), None
        logic_map_bgr = imread_unicode(map_path)
        if logic_map_bgr is None:
            raise FileNotFoundError(f"Could not load logic map: {map_path}")
        return LoadingMapTracker(map_path, logic_map_bgr), SiftTracker
    except FileNotFoundError as exc:
        return MissingMapTracker(map_path, str(exc)), None


def _minimap_is_configured() -> bool:
    cfg = config.settings.get("MINIMAP") or {}
    try:
        top = int(cfg["top"])
        left = int(cfg["left"])
        width = int(cfg["width"])
        height = int(cfg["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return width > 0 and height > 0 and top >= 0 and left >= 0
        
def _fetch_license_config() -> bool:
    try:
        from ui_island.services.app_updater import check_app_update
        result = check_app_update(timeout=8.0)
        return bool(getattr(result, "ok", False))
    except Exception:
        return False


def _show_license_error(app: QApplication, message: str) -> None:
    try:
        from ui_island.dialogs.base import StyledMessage, center_dialog
        dialog = StyledMessage(None, "许可证验证失败", message)
        center_dialog(dialog, None)
        dialog.exec()
    except Exception:
        print(f"许可证错误: {message}", file=sys.stderr)


def _check_license(app: QApplication) -> bool:
    _fetch_license_config()

    license_verify_enabled = getattr(config, "LICENSE_VERIFY_ENABLED", False)
    if not license_verify_enabled:
        return True

    public_key = getattr(config, "LICENSE_PUBLIC_KEY", "") or ""
    qq_groups = getattr(config, "LICENSE_QQ_GROUPS", None) or []

    license_data = getattr(config, "LICENSE_DATA", None) or {}
    if license_data:
        if is_license_valid(license_data):
            return True
        config.save_config({"LICENSE_DATA": {}})

    fingerprint_display = get_machine_fingerprint_display()

    if not public_key:
        _show_license_error(app, "无法获取许可证信息，请检查网络连接后重试。")
        return False

    from ui_island.design.strings import (
        LICENSE_ERROR_EXPIRED,
        LICENSE_ERROR_HW_MISMATCH,
        LICENSE_ERROR_INVALID,
    )

    error_map = {
        "LICENSE_ERROR_INVALID": LICENSE_ERROR_INVALID,
        "LICENSE_ERROR_EXPIRED": LICENSE_ERROR_EXPIRED,
        "LICENSE_ERROR_HW_MISMATCH": LICENSE_ERROR_HW_MISMATCH,
    }

    while True:
        from ui_island.dialogs.license_dialog import LicenseDialog
        code = LicenseDialog.get_activation_code(None, fingerprint_display, qq_groups)
        if code is None:
            return False

        error_key, payload = verify_license(public_key, code)
        if error_key is not None:
            _show_license_error(app, error_map.get(error_key, "激活码验证失败。"))
            continue

        config.save_config({"LICENSE_DATA": payload})
        return True


def main() -> int:
    os.chdir(config.BASE_DIR)
    config.ensure_maps_dir()
    config.ensure_annotations_dir()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine",
        choices=["sift"],
        default="sift",
        help="定位引擎；当前发行版仅保留 SIFT，AI UI 占位待未来接入",
    )
    parser.add_argument(
        "--no-selector",
        action="store_true",
        help="跳过小地图校准（使用 config.json 中已有坐标）",
    )
    parser.add_argument(
        "--force-selector",
        action="store_true",
        help="强制弹出小地图校准器即便已有坐标",
    )
    args = parser.parse_args()

    # Qt 应用必须先于选择器创建 —— 选择器本身就是 Qt 窗口
    app = QApplication(sys.argv)

    if not _check_license(app):
        return 0

    if args.force_selector or (not args.no_selector and not _minimap_is_configured()):
        print(">>> 正在启动小地图选择器...")
        saved = run_minimap_calibrator()
        if not saved:
            print("⚠️ 未保存小地图坐标，程序退出。")
            return 0
        print("<<< 选择器关闭，坐标已更新！")

    tracker, deferred_tracker_factory = build_tracker()
    route_mgr = RouteManager(config.app_path("routes"))

    window = IslandWindow(tracker, route_mgr)
    window.show()
    if deferred_tracker_factory is not None:
        window.start_deferred_tracker_load(deferred_tracker_factory)
    return app.exec()


def _write_crash_log(exc: BaseException) -> None:
    try:
        logs_dir = config.app_path("logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, "app_crash.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
        print(f"程序异常已写入：{path}", file=sys.stderr)
    except Exception as log_exc:
        print(f"写入崩溃日志失败：{log_exc}", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        _write_crash_log(exc)
        raise SystemExit(1)
