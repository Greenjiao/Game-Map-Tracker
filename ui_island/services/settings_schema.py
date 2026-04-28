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
]

TOOL_BUTTONS: list[str] = ["检查更新", "夸克网盘", "路线资源", "更新文档", "问题反馈", "拉取标注"]

ALL_FIELDS: list[Field] = SIFT_FIELDS + COMMON_FIELDS
FIELD_INDEX: dict[str, Field] = {field.key: field for field in ALL_FIELDS}
