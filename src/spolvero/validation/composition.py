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


def _bbox_area(leaf) -> float:
    b = _leaf_bbox(leaf)
    if b is None:
        return 0.0
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


# 色度判定阈值：RGB 通道极差超过它才算「彩色」。
# 取 60 而非十几：朱砂预设的墨色是**暖调**（base #7A5A48 极差 50、ink #20160F 极差 17），
# 若阈值过低会把「墨分五色」整片判成彩面积 → color_area 恒为 1，约束失去意义。
CHROMA_EPS = 60


def _is_chromatic(color, eps: int = CHROMA_EPS) -> bool:
    """是否「彩色」（RGB 通道极差 > eps）。暖调墨色不算彩色，高纯度点缀才算。"""
    if not color:
        return False
    s = str(color).lstrip("#")
    if len(s) != 6:
        return False
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return False
    return (max(r, g, b) - min(r, g, b)) > eps


def color_area_ratio(leaves: Sequence) -> float:
    """彩面积占比：**彩色**（高纯度）叶节点包围盒面积 / 全部叶节点包围盒面积。

    注意：不是「有 color 字段的叶节点占比」。彩色风格下所有叶节点都会带 color（三档墨色），
    若按字段计则恒为 1，约束失去意义。此处按**色度**判定，故「以墨为主、彩作点缀」
    的东方风格天然落在很小的值上。
    """
    total = 0.0
    colored = 0.0
    for lf in leaves:
        a = _bbox_area(lf)
        total += a
        if _is_chromatic(getattr(lf, "color", None)):
            colored += a
    if total <= 0.0:
        return 0.0
    return min(1.0, colored / total)


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


# ─────────────────── 扩展 2 指纹：色块数 / 质心 / 主轴 ───────────────────
# 用固定网格栅格化叶节点包围盒（纯下标运算，无 shapely、无随机），
# 使「色块数 / 质心 / 主轴」在跨平台下逐位一致（SPEC §9）。
GRID_COLS = 40
GRID_ROWS = 24


def coverage_mask(leaves: Sequence, w: int, h: int, cols: int = GRID_COLS, rows: int = GRID_ROWS):
    """返回 rows×cols 布尔覆盖掩膜（叶节点包围盒占据的网格单元）。"""
    mask = [[False] * cols for _ in range(rows)]
    if w <= 0 or h <= 0:
        return mask
    for leaf in leaves:
        b = _leaf_bbox(leaf)
        if b is None:
            continue
        c0 = max(0, min(cols - 1, int(b[0] / w * cols)))
        c1 = max(0, min(cols - 1, int(b[2] / w * cols)))
        r0 = max(0, min(rows - 1, int(b[1] / h * rows)))
        r1 = max(0, min(rows - 1, int(b[3] / h * rows)))
        if c1 < c0:
            c0, c1 = c1, c0
        if r1 < r0:
            r0, r1 = r1, r0
        for r in range(r0, r1 + 1):
            row = mask[r]
            for c in range(c0, c1 + 1):
                row[c] = True
    return mask


def density_profile(leaves: Sequence, w: int, h: int, cols: int = 8, rows: int = 6):
    """8×6 归一化覆盖率直方图（行优先**展平**，长度 cols*rows=48）。"""
    mask = coverage_mask(leaves, w, h, cols, rows)
    total = float(cols * rows)
    return [1.0 / total if v else 0.0 for row in mask for v in row]


def region_count(leaves: Sequence, w: int, h: int, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> int:
    """色块/连通域数（4-邻接）。平涂类风格的关键特征。"""
    mask = coverage_mask(leaves, w, h, cols, rows)
    seen = [[False] * cols for _ in range(rows)]
    count = 0
    for r in range(rows):
        for c in range(cols):
            if not mask[r][c] or seen[r][c]:
                continue
            count += 1
            stack = [(r, c)]
            seen[r][c] = True
            while stack:
                cr, cc = stack.pop()
                for nr, nc in ((cr - 1, cc), (cr + 1, cc), (cr, cc - 1), (cr, cc + 1)):
                    if 0 <= nr < rows and 0 <= nc < cols and mask[nr][nc] and not seen[nr][nc]:
                        seen[nr][nc] = True
                        stack.append((nr, nc))
    return count


def ink_centroid(leaves: Sequence, w: int, h: int, cols: int = GRID_COLS, rows: int = GRID_ROWS):
    """墨质心 (cx, cy)，归一化到 [0,1]；无墨返回 (0.5, 0.5)。"""
    mask = coverage_mask(leaves, w, h, cols, rows)
    xs, ys, n = 0.0, 0.0, 0
    for r in range(rows):
        for c in range(cols):
            if mask[r][c]:
                xs += (c + 0.5) / cols
                ys += (r + 0.5) / rows
                n += 1
    if n == 0:
        return (0.5, 0.5)
    return (xs / n, ys / n)


def principal_axis_deg(leaves: Sequence, w: int, h: int, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> float:
    """墨迹二阶矩主轴角度（度，x 轴向右为正，逆时针为正）。无墨返回 0。

    仅用于报告指纹，不参与渲染路径；内部用 atan2，非 L1 门禁项。
    """
    import math

    mask = coverage_mask(leaves, w, h, cols, rows)
    n = 0
    sx = sy = 0.0
    for r in range(rows):
        for c in range(cols):
            if mask[r][c]:
                sx += (c + 0.5) / cols
                sy += (r + 0.5) / rows
                n += 1
    if n < 2:
        return 0.0
    mx, my = sx / n, sy / n
    cxx = cyy = cxy = 0.0
    for r in range(rows):
        for c in range(cols):
            if mask[r][c]:
                dx = (c + 0.5) / cols - mx
                dy = (r + 0.5) / rows - my
                cxx += dx * dx
                cyy += dy * dy
                cxy += dx * dy
    return math.degrees(0.5 * math.atan2(2.0 * cxy, cxx - cyy))


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

    # —— 扩展 2 指纹约束（M6a 起接入；缺省项不检查）——
    rc = region_count(leaves, w, h)
    rc_min, rc_max = constraints.get("region_count_min"), constraints.get("region_count_max")
    if rc_min is not None and rc < rc_min:
        code = "COMP_REGION_COUNT"
        out.append(Issue(
            SEVERITY_ERROR if code in as_error else sev, code,
            f"色块/连通域数 {rc} < 下限 {rc_min}（画面过空）", "<scene>",
            "补充元素或缩小留白",
        ))
    if rc_max is not None and rc > rc_max:
        code = "COMP_REGION_COUNT"
        out.append(Issue(
            SEVERITY_ERROR if code in as_error else sev, code,
            f"色块/连通域数 {rc} > 上限 {rc_max}（画面过碎）", "<scene>",
            "合并/减少元素或加大元素尺寸",
        ))

    target = constraints.get("centroid")
    tol = constraints.get("centroid_tol")
    if target and tol is not None:
        cx, cy = ink_centroid(leaves, w, h)
        d = ((cx - target[0]) ** 2 + (cy - target[1]) ** 2) ** 0.5
        if d > tol:
            code = "COMP_CENTROID"
            out.append(Issue(
                SEVERITY_ERROR if code in as_error else sev, code,
                f"墨质心 ({cx:.3f},{cy:.3f}) 偏离目标 ({target[0]:.2f},{target[1]:.2f}) 达 {d:.3f} > {tol}",
                "<scene>",
                "整体平移/配重以校正视觉重心",
            ))

    axis_t = constraints.get("axis_deg")
    axis_tol = constraints.get("axis_tol_deg")
    if axis_t is not None and axis_tol is not None:
        ang = principal_axis_deg(leaves, w, h)
        d = abs(((ang - axis_t + 90.0) % 180.0) - 90.0)
        if d > axis_tol:
            code = "COMP_AXIS"
            out.append(Issue(
                SEVERITY_ERROR if code in as_error else sev, code,
                f"墨迹主轴 {ang:.1f}° 偏离目标 {axis_t:.1f}° 达 {d:.1f}° > {axis_tol}°",
                "<scene>",
                "调整主体走向或收窄构图横向跨度",
            ))
    return out
