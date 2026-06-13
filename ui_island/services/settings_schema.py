"""Field definitions for the settings dialog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type_: type
    value_range: str = ""
    desc: str = ""
    needs_restart: bool = False


SIFT_FIELDS: list[Field] = [
    Field("SIFT_REFRESH_RATE", "刷新间隔", int, "10~100 ms", "越小越跟手"),
    Field("SIFT_MATCH_RATIO", "匹配比率", float, "0.6~0.95", "越大越宽松"),
    Field("SIFT_MIN_MATCH_COUNT", "最少匹配点", int, "4~20", "低于此值判丢失"),
    Field("SIFT_RANSAC_THRESHOLD", "RANSAC 阈值", float, "2.0~15.0 px", "越小越严格"),
    Field("SIFT_CLAHE_LIMIT", "CLAHE 对比度", float, "1.0~6.0", "对比度增强上限", needs_restart=True),
    Field("SIFT_LOCAL_SEARCH_RADIUS", "局部搜索半径", int, "200~800 px", "局部匹配范围"),
]

COMMON_FIELDS: list[Field] = [
    Field("MAX_LOST_FRAMES", "最大惯性帧数", int, "10~120", "丢失判定阈值"),
    Field("ROUTE_GUIDE_NODE_DISTANCE", "导航节点偏离距离", int, "20~300 px"),
    Field("ROUTE_GUIDE_SEGMENT_DISTANCE", "导航线段吸附距离", int, "10~150 px"),
    Field("ROUTE_GUIDE_POINTER_SPACING", "导航指针间隔", int, "12~80 px"),
    Field("ROUTE_NODE_NAME_HIDE_RATIO", "节点文字隐藏阈值", int, "1~10", "地图缩小到此倍率后隐藏节点序号与名称，仅留圆点"),
    Field("ANNOTATION_CLUSTER_RATIO", "标注聚合阈值", int, "2~10", "地图缩小到此倍率后聚合标注，越大越晚聚合"),
]

COORD_FIELDS: list[Field] = [
    Field("COORD_SCALE_X", "X 缩放", float, "0.0001~10000", "默认 1.0 不变换"),
    Field("COORD_SCALE_Y", "Y 缩放", float, "0.0001~10000", "默认 1.0 不变换"),
    Field("COORD_OFFSET_X", "X 偏移", float, "-8192~8192 px", "默认 0 不偏移"),
    Field("COORD_OFFSET_Y", "Y 偏移", float, "-8192~8192 px", "默认 0 不偏移"),
]

TOOL_BUTTONS: list[str] = ["检查更新", "夸克网盘", "路线资源", "问题反馈", "标注转换", "路线转换"]

ALL_FIELDS: list[Field] = SIFT_FIELDS + COMMON_FIELDS + COORD_FIELDS
FIELD_INDEX: dict[str, Field] = {field.key: field for field in ALL_FIELDS}
