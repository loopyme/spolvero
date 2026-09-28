"""艺术相似度校验（M4 · 第二重）。

目标：检测场景中高度相似的**闭合轮廓**（近重复剪影），强制参数/拓扑差异化（SPEC §8.3）。
方法：将每个 ink_shape 的控制点按弧长重采样为恒定 N 点 → 居中归一化（场景包围盒对角线）
→ 签名向量；两两 L2 距离低于阈值且空间邻近，判为近重复（warning）。
重采样与归一化均为纯 +-*/，确定性。不依赖 libm。
开放笔画（有意重复母题）默认不参与，见 find_similar 的 include_lines 说明。"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from spolvero.core.primitives import InkDot, InkLine, InkShape
from spolvero.validation.diagnostics import SEVERITY_WARNING, Issue

Pt = Tuple[float, float]


def _leaf_points(leaf) -> Tuple[List[Pt], bool]:
    if isinstance(leaf, InkShape):
        return [(p.x, p.y) for p in leaf.ring], True
    if isinstance(leaf, InkLine):
        return [(p.x, p.y) for p in leaf.points], bool(leaf.closed)
    return [], False


def _scene_diag(leaves: Sequence) -> float:
    xs, ys = [], []
    for leaf in leaves:
        if isinstance(leaf, InkDot):
            xs.append(leaf.pos.x); ys.append(leaf.pos.y)
        else:
            for x, y in _leaf_points(leaf)[0]:
                xs.append(x); ys.append(y)
    if len(xs) < 2:
        return 1.0
    return max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)


def _resample(pts: List[Pt], n: int, closed: bool) -> List[Pt]:
    if len(pts) < 2:
        return [pts[0]] * n if pts else [(0.0, 0.0)] * n
    loop = pts + [pts[0]] if closed else pts
    seg: List[float] = []
    total = 0.0
    for i in range(len(loop) - 1):
        dx = loop[i + 1][0] - loop[i][0]
        dy = loop[i + 1][1] - loop[i][1]
        d = (dx * dx + dy * dy) ** 0.5
        seg.append(d)
        total += d
    if total == 0:
        return [loop[0]] * n
    out: List[Pt] = []
    for k in range(n):
        target = (k / n) * total if closed else (k / (n - 1)) * total
        acc = 0.0
        placed = False
        for i, sl in enumerate(seg):
            if acc + sl >= target or i == len(seg) - 1:
                t = (target - acc) / sl if sl > 0 else 0.0
                x = loop[i][0] + (loop[i + 1][0] - loop[i][0]) * t
                y = loop[i][1] + (loop[i + 1][1] - loop[i][1]) * t
                out.append((x, y))
                placed = True
                break
            acc += sl
        if not placed:
            out.append(loop[-1])
    return out


def _signature(pts: List[Pt], n: int, diag: float, closed: bool) -> List[Pt]:
    rs = _resample(pts, n, closed)
    cx = sum(p[0] for p in rs) / n
    cy = sum(p[1] for p in rs) / n
    return [((x - cx) / diag, (y - cy) / diag) for x, y in rs]


def _dist(a: List[Pt], b: List[Pt]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(a, b):
        s += (x1 - x2) ** 2 + (y1 - y2) ** 2
    return (s / len(a)) ** 0.5


def _rms(sig: List[Pt]) -> float:
    """签名向量的均方根幅值（≈元素相对场景对角线的尺度）。"""
    s = 0.0
    for x, y in sig:
        s += x * x + y * y
    return (s / len(sig)) ** 0.5


def _relative_dist(a: List[Pt], b: List[Pt]) -> float:
    """尺度自适应的相对距离：绝对距离 / 较大一方的幅值。

    绝对距离会随元素变小而整体变小，导致「小元素之间几乎任何差异都 < 绝对阈值」的误报
    （如 250px 远山与 132px 船体的绝对距离仅 0.026，相对距离却达 0.33）。用相对距离后，
    阈值语义 = 「形状差异占自身尺度的比例」，与元素大小解耦。
    """
    return _dist(a, b) / max(_rms(a), _rms(b), 1e-12)


def find_similar(
    leaves: Sequence,
    n: int = 24,
    thr: float = 0.06,
    spatial_gate: float = 0.25,
    label: str = "scene",
    include_lines: bool = False,
) -> List[Issue]:
    """检测近重复形体（warning 级）。

    只在**闭合轮廓（剪影 / ink_shape）**之间比较：签名为弧长重采样 + 场景对角线归一化，
    同类型两两 L2 距离 < thr 且中心距 < spatial_gate·对角线，才判为「冗余近重复」。
    空间门限避免误伤有意为之的远处重复母题。

    开放笔画（水纹 / 云纹 / 皴线 / 篷弧 / 桅杆）是**有意的重复母题**，默认不参与比较，
    否则一条水纹组内的 16 点正弦线会互相触发误报。需要严格模式时置 include_lines=True。
    """
    items: List[Tuple[int, List[Pt], bool, str]] = []
    centers: List[Pt] = []
    for idx, leaf in enumerate(leaves):
        if isinstance(leaf, InkShape):
            kind = "shape"
        elif include_lines and isinstance(leaf, InkLine):
            kind = "line"
        else:
            continue
        pts, closed = _leaf_points(leaf)
        if len(pts) >= 3:
            items.append((idx, pts, closed, kind))
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            centers.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
    if len(items) < 2:
        return []

    diag = _scene_diag(leaves)
    sigs = {i: _signature(pts, n, diag, closed) for i, pts, closed, _ in items}
    kinds = {i: kind for i, _, _, kind in items}

    issues: List[Issue] = []
    idxs = [i for i, _, _, _ in items]
    gate = spatial_gate * diag
    for a_i in range(len(idxs)):
        for b_i in range(a_i + 1, len(idxs)):
            ia, ib = idxs[a_i], idxs[b_i]
            if kinds[ia] != kinds[ib]:
                continue
            cx = centers[a_i][0] - centers[b_i][0]
            cy = centers[a_i][1] - centers[b_i][1]
            if (cx * cx + cy * cy) ** 0.5 > gate:
                continue  # 远处重复母题，非冗余
            d = _relative_dist(sigs[ia], sigs[ib])
            if d < thr:
                issues.append(
                    Issue(
                        SEVERITY_WARNING, "ART_NEAR_DUPLICATE",
                        f"形体 #{ia} 与 #{ib} 相对签名距离 {d:.4f} < {thr}（空间冗余近重复）",
                        f"{label}[{ia}],{label}[{ib}]",
                        "调整 seed 或放宽参数值域/拓扑开关以拉开差异",
                    )
                )
    return issues
