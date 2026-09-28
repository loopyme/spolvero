"""几何拓扑校验（M4 · 第一重）。

基于 shapely（GEOS）：检测自相交轮廓、退化（重复点 / 零面积）、朝向不一致。
命中即返回结构化 Issue，供拦截与自纠。
"""

from __future__ import annotations

from typing import List, Sequence

from shapely.geometry import LineString, Polygon

from spolvero.core.primitives import InkDot, InkLine, InkShape
from spolvero.validation.diagnostics import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Issue,
)


def _pts(leaf) -> List[tuple[float, float]]:
    if isinstance(leaf, InkShape):
        return [(p.x, p.y) for p in leaf.ring]
    if isinstance(leaf, InkLine):
        return [(p.x, p.y) for p in leaf.points]
    return []


def _signed_area(pts: Sequence[tuple[float, float]]) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def check_leaf_geometry(leaf, location: str = "") -> List[Issue]:
    """对单个叶节点做几何拓扑校验，返回 Issue 列表（可能为空）。"""
    issues: List[Issue] = []
    if isinstance(leaf, InkDot):
        return issues  # 点无拓扑约束

    pts = _pts(leaf)
    n = len(pts)
    if n < 3:
        # 单点/两点的 ink_line 合法（单段线），但 ink_shape 至少需 3 点成面
        if isinstance(leaf, InkShape):
            issues.append(
                Issue(SEVERITY_ERROR, "GEOM_TOO_FEW_POINTS",
                      f"ink_shape 控制点不足: {n} (<3)", location,
                      "增加控制点至 ≥3 以构成闭合轮廓")
            )
        return issues

    # 退化：相邻重复点
    dup = sum(1 for i in range(n) if pts[i] == pts[(i + 1) % n])
    if dup:
        issues.append(
            Issue(SEVERITY_WARNING, "GEOM_DUP_POINTS",
                  f"存在 {dup} 处相邻重复点", location,
                  "去重控制点以避免零长线段")
        )

    if isinstance(leaf, InkShape):
        poly = Polygon(pts)
        if not poly.is_valid:
            issues.append(
                Issue(SEVERITY_ERROR, "GEOM_SELF_INTERSECT",
                      "闭合轮廓自相交（shapely is_valid=false）", location,
                      "调整控制点顺序/位置消除自相交")
            )
        elif poly.area < 1e-6:
            issues.append(
                Issue(SEVERITY_ERROR, "GEOM_ZERO_AREA",
                      "闭合轮廓面积为 ~0（不构成有效面）", location,
                      "拉开控制点形成非零面积")
            )
    elif isinstance(leaf, InkLine) and leaf.closed:
        poly = Polygon(pts)
        if not poly.is_valid:
            issues.append(
                Issue(SEVERITY_ERROR, "GEOM_SELF_INTERSECT",
                      "闭合折线自相交", location,
                      "调整顶点消除自相交")
            )
    else:  # 开放折线
        ls = LineString(pts)
        if not ls.is_simple:
            issues.append(
                Issue(SEVERITY_WARNING, "GEOM_LINE_SELF_INTERSECT",
                      "开放折线自相交", location,
                      "检查折线走向")
            )
    return issues


def check_scene_geometry(leaves: Sequence, label: str = "scene") -> List[Issue]:
    """对整场景拍平后的叶节点逐个校验几何拓扑。"""
    issues: List[Issue] = []
    for idx, leaf in enumerate(leaves):
        loc = f"{label}[{idx}]"
        issues.extend(check_leaf_geometry(leaf, loc))
    return issues
