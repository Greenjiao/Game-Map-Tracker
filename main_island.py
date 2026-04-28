"""灵动岛版跟点器主入口。

用法：
    python main_island.py            # SIFT 引擎
    python main_island.py --engine sift  # 兼容旧启动命令
"""
from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

import config
from route_manager import RouteManager
from ui_island import IslandWindow
from ui_island.dialogs.minimap_selector import run_minimap_calibrator


def build_tracker():
    from Plan_SIFT import SiftTracker
    return SiftTracker()


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
        
def main() -> int:
    os.chdir(config.BASE_DIR)

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

    if args.force_selector or (not args.no_selector and not _minimap_is_configured()):
        print(">>> 正在启动小地图选择器...")
        saved = run_minimap_calibrator()
        if not saved:
            print("⚠️ 未保存小地图坐标，程序退出。")
            return 0
        print("<<< 选择器关闭，坐标已更新！")

    tracker = build_tracker()
    route_mgr = RouteManager(config.app_path("routes"))

    window = IslandWindow(tracker, route_mgr)
    window.show()
    return app.exec()


if __name__ == "__main__":
    code = main()
    os._exit(code if code is not None else 0)
