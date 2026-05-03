"""将三类传送点图标按 JSON 坐标贴到大地图上。

teleport/ 下 JSON 中的 (x, y) 仍是旧拟合公式坐标，贴图前先用
 legacy_coordinate_convert._old_big_map_xy_to_17173_xy 转到 big_map_17173 像素系。
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.annotation_converters.legacy_coordinate_convert import (  # noqa: E402
    _old_big_map_xy_to_17173_xy as old_to_new_xy,
)

MAP_PATH = ROOT / "maps" / "卡洛西亚大陆" / "big_map_new.png"
OUT_PATH = MAP_PATH.with_name("big_map_new_带图标.png")

ICON_SIZE = (36, 36)
HW, HH = ICON_SIZE[0] // 2, ICON_SIZE[1] // 2

TASKS = [
    ("眠枭庇护所", "17310030039"),
    ("魔力之源（传送点）", "17310030038"),
    ("炼金台", "17310030041"),
]


def load_icon(icon_id: str) -> Image.Image:
    p = ROOT / "tools" / "points_icon" / f"{icon_id}.png"
    return Image.open(p).convert("RGBA").resize(ICON_SIZE, Image.LANCZOS)


def load_points(name: str) -> list[dict]:
    p = ROOT / "tools" / "points_get" / "teleport" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8"))["points"]


def main() -> None:
    base = Image.open(MAP_PATH)
    assert base.mode == "RGB" and base.size == (8192, 8192)
    dpi = base.info.get("dpi")

    total = 0
    for name, icon_id in TASKS:
        icon = load_icon(icon_id)
        pts = load_points(name)
        for pt in pts:
            new_x, new_y = old_to_new_xy(pt["x"], pt["y"])
            base.paste(icon, (new_x - HW, new_y - HH), mask=icon)
        print(f"{name}: 贴了 {len(pts)} 个点")
        total += len(pts)

    save_kwargs = {"format": "PNG"}
    if dpi:
        save_kwargs["dpi"] = dpi
    base.save(OUT_PATH, **save_kwargs)
    print(f"完成，共 {total} 个图标，输出: {OUT_PATH}")


if __name__ == "__main__":
    main()
