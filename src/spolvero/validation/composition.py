"""构图约束校验（M4 · 第三重 / M6 四约束）。

四约束（SPEC §6 / §8，阈值写在风格预设，可配）：
  whitespace 留白 —— 画面被墨色覆盖的面积比例须 ≤ (1 - whitespace_min)
  color_area 彩面积 —— 着色（带 color 字段）叶节点占比须 ≤ color_area_max
  density    密度 —— 总笔画长度 / 画布面积须 ≤ density_max
  clustering 堆积 —— 任两元素包围盒交并比（IoU）须 ≤ overlap_max

命中返回 Issue，severity 由 constraints["severity"] 决定，可由 constraints["as_error"]
升级为 error（默认 warning，SPEC §8 分级）。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import box

from spolvero.core.primitives import InkDot, InkLine, InkShape
from spolvero.validation.diagnostics import SEVERITY_ERROR, SEVERITY_WARNING, Issue


def _leaf_bbox(leaf):
    if isinstance(leaf, InkDot):
        r = max(leaf.r, 0.5)
        return (leaf.pos.x - r, leaf.pos.y - r, leaf.pos.x + r, leaf.pos.y + r)
    pts = [(p.x, p.y) for p in (leaf.ring if isinstance(leaf, InkShape) else leaf.points)]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _stroke_length(leaf) -> float:
    if isinstance(leaf, InkDot):
        return 0.0
    pts = list(leaf.ring if isinstance(leaf, InkShape) else leaf.points)
    if len(pts) < 2:
        return 0.0
    seq = pts + [pts[0]] if isinstance(leaf, InkShape) else pts
    total = 0.0
    for i in range(len(seq) - 1):
        dx = seq[i + 1].x - seq[i].x
        dy = seq[i + 1].y - seq[i].y
        total += (dx * dx + dy * dy) ** 0.5
    return total


def coverage_ratio(leaves: Sequence, w: int, h: int) -> float:
    """墨色覆盖面积占比（所有包围盒并集 / 画布），留白 = 1 - 此值。"""
    if w <= 0 or h <= 0:
        return 0.0
    polys = []
    for leaf in leaves:
        b = _leaf_bbox(leaf)
        if b is None:
            continue
        polys.append(box(b[0], b[1], b[2], b[3]))
    if not polys:
        return 0.0
    union = polys[0]
    for p in polys[1:]:
        union = union.union(p)
    return min(1.0, max(0.0, union.area / (w * h)))


def density(leaves: Sequence, w: int, h: int) -> float:
    if w <= 0 or h <= 0:
        return 0.0
    return sum(_stroke_length(lf) for lf in leaves) / (w * h)


def color_area_ratio(leaves: Sequence) -> float:
    n = len(leaves)
    if n == 0:
        return 0.0
    colored = sum(1 for lf in leaves if getattr(lf, "color", None))
    return colored / n


def max_overlap(leaves: Sequence) -> float:
    boxes = []
    for leaf in leaves:
        b = _leaf_bbox(leaf)
        if b is None or (b[2] - b[0] < 1e-6) or (b[3] - b[1] < 1e-6):
            continue
        boxes.append(box(b[0], b[1], b[2], b[3]))
    if len(boxes) < 2:
        return 0.0
    worst = 0.0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            inter = boxes[i].intersection(boxes[j]).area
            if inter <= 0:
                continue
            union = boxes[i].union(boxes[j]).area
            iou = inter / union if union > 0 else 0.0
            worst = max(worst, iou)
    return worst


def validate_composition(
    leaves: Sequence,
    w: int,
    h: int,
    constraints: Optional[Dict] = None,
) -> List[Issue]:
    """按风格约束校验四约束。constraints 缺省时返回空（不强制）。"""
    if not constraints:
        return []
    sev = constraints.get("severity", SEVERITY_WARNING)
    as_error = set(constraints.get("as_error", []))
    out: List[Issue] = []

    cov = coverage_ratio(leaves, w, h)
    ws_min = constraints.get("whitespace_min")
    if ws_min is not None:
        if (1.0 - cov) < ws_min:
            code = "COMP_LOW_WHITESPACE"
            out.append(Issue(
                SEVERITY_ERROR if code in as_error else sev, code,
                f"留白 {(1.0-cov):.3f} < 要求 {ws_min:.3f}（覆盖 {cov:.3f} 过高）",
                "<scene>",
                "减少元素数量/尺寸或上移以维持东方极简留白",
            ))

    ca = color_area_ratio(leaves)
    ca_max = constraints.get("color_area_max")
    if ca_max is not None:
        if ca > ca_max + 1e-9:
            code = "COMP_COLOR_AREA"
            out.append(Issue(
                SEVERITY_ERROR if code in as_error else sev, code,
                f"彩面积占比 {ca:.3f} > 上限 {ca_max:.3f}（非灰度风格才允许着色）",
                "<scene>",
                "将部分着色叶节点改回 ink 灰度，或提高灰度元素比例",
            ))

    dens = density(leaves, w, h)
    dens_max = constraints.get("density_max")
    if dens_max is not None:
        if dens > dens_max:
            code = "COMP_DENSITY"
            out.append(Issue(
                SEVERITY_ERROR if code in as_error else sev, code,
                f"笔画密度 {dens:.6f} > 上限 {dens_max:.6f}",
                "<scene>",
                "拉开元素间距或降低笔画总长",
            ))

    ov = max_overlap(leaves)
    ov_max = constraints.get("overlap_max")
    if ov_max is not None:
        if ov > ov_max:
            code = "COMP_CLUSTER"
            out.append(Issue(
                SEVERITY_ERROR if code in as_error else sev, code,
                f"元素最大包围盒交并比 {ov:.3f} > 上限 {ov_max:.3f}（堆积）",
                "<scene>",
                "分散重叠元素的位置/缩放",
            ))
    return out
