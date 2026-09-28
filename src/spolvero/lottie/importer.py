"""Lottie L1 导入（M6d）：Lottie JSON → 几何化 → 控制点归一化 → 四原语。

按 SPEC §12：`python-lottie 解析 → shapely 几何化 → 控制点归一化 → 四原语`
（Skia Skottie 未暴露，故不走 Skia）。

三个刻意的裁决：
1. **只取静态姿态（frame 0）求值**。L1 的用途是把外部素材「吃进构件体系」当素材用，
   不是逐帧搬运外部动画——逐帧搬运属 L0/L2 之间的灰区，且会让点位数爆炸。
2. **控制点归一化到恒定 N**（`IMPORT_POINTS`，命门 3）。外部 SVG/Lottie 的点数杂乱，
   不归一化则件件违反「ink_shape 控制点数恒定」，后面的参数化插值全废。
3. **贝塞尔只取顶点，丢弃切线**（直线化近似）。控制点恒定优先于曲线保真：
   本项目靠风格与构图取胜，不靠曲线精度；保留切线会让点数随素材漂移。

解析后的对象模型经内省确认：`anim.layers[*].shapes` 递归，
`Path.shape.value` 是 `Bezier`（`.vertices/.closed`），`Fill.color.value` 是 [r,g,b,a]∈[0,1]，
`Ellipse.position/size` 是 NVector，`TransformShape` 承载组内变换。
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from spolvero.core.dmath import dcos, dsin
from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.transform import Transform
from spolvero.core.types import Point
from spolvero.render.common import gray_of

IMPORT_POINTS = 24  # 导入后 ink_shape 的恒定控制点数（命门 3）

_CHROMA_EPS = 18


class LottieImportError(Exception):
    pass


# ─────────────────── python-lottie 属性读取（防御式）───────────────────
def _static(prop):
    """取属性在 frame 0 的静态值（含动画属性退化取首关键帧）。"""
    if prop is None:
        return None
    if getattr(prop, "animated", False):
        kfs = getattr(prop, "keyframes", None) or []
        if kfs:
            start = getattr(kfs[0], "start", None)
            v = getattr(start, "value", None)
            if v is not None:
                return v
    v = getattr(prop, "value", None)
    if isinstance(v, list) and v and hasattr(v[0], "start"):
        return getattr(v[0].start, "value", None)
    return v


def _vec(v, dflt: Tuple[float, float]) -> Tuple[float, float]:
    if v is None:
        return dflt
    if hasattr(v, "x"):
        return (float(v.x), float(getattr(v, "y", 0.0)))
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return (float(v[0]), float(v[1]))
    return dflt


def _scalar(v, dflt: float) -> float:
    if v is None:
        return dflt
    if isinstance(v, (list, tuple)):
        return float(v[0]) if v else dflt
    try:
        return float(v)
    except (TypeError, ValueError):
        return dflt


def _matrix_of(tf) -> Transform:
    """Lottie 变换 → 仿射矩阵。次序：锚点平移 → 缩放 → 旋转 → 定位平移。"""
    if tf is None:
        return Transform.identity()
    p = _vec(_static(getattr(tf, "position", None)), (0.0, 0.0))
    a = _vec(_static(getattr(tf, "anchor_point", None)), (0.0, 0.0))
    s = _vec(_static(getattr(tf, "scale", None)), (100.0, 100.0))
    r = _scalar(_static(getattr(tf, "rotation", None)), 0.0)
    return (
        Transform.translate(p[0], p[1])
        .compose(Transform.rotate(r))
        .compose(Transform.scale(s[0] / 100.0, s[1] / 100.0))
        .compose(Transform.translate(-a[0], -a[1]))
    )


def _rgb(cv) -> Optional[Tuple[int, int, int]]:
    v = _static(cv)
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return None
    return (
        max(0, min(255, int(round(float(v[0]) * 255)))),
        max(0, min(255, int(round(float(v[1]) * 255)))),
        max(0, min(255, int(round(float(v[2]) * 255)))),
    )


def _ink_and_color(rgb: Optional[Tuple[int, int, int]]):
    """RGB → (ink 灰度, color 十六进制或 None)。近灰只回 ink，保住灰度风格可用性。"""
    if rgb is None:
        return 0.4, None
    r, g, b = rgb
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    ink = max(0.0, min(1.0, 1.0 - lum / 255.0))
    if (max(rgb) - min(rgb)) > _CHROMA_EPS:
        return ink, "#%02x%02x%02x" % rgb
    return ink, None


# ─────────────────── 几何：重采样到恒定 N 点（命门 3）───────────────────
def _resample(coords: List[Tuple[float, float]], n: int, closed: bool) -> List[Tuple[float, float]]:
    from shapely.geometry import LineString

    if len(coords) < 2:
        return list(coords) if coords else [(0.0, 0.0)] * n
    loop = list(coords) + [coords[0]] if closed else list(coords)
    ls = LineString(loop)
    total = ls.length
    if total <= 0.0:
        return [coords[0]] * n
    if closed:
        pts = [ls.interpolate(total * k / n) for k in range(n)]
    else:
        pts = [ls.interpolate(total * k / (n - 1)) for k in range(n)]
    return [(p.x, p.y) for p in pts]


def _circle_coords(center: Tuple[float, float], size: Tuple[float, float], n: int):
    rx, ry = size[0] / 2.0, size[1] / 2.0
    return [
        (
            center[0] + rx * dcos(2.0 * math.pi * k / n),
            center[1] + ry * dsin(2.0 * math.pi * k / n),
        )
        for k in range(n)
    ]


# ─────────────────── 形状树遍历 ───────────────────
def _leaves_of(items, parent: Transform, ctx: dict, out: List) -> None:
    """遍历一个 shape 容器：收集几何、沿用其样式、递归嵌套组。"""
    geom: List = []
    local = dict(ctx)
    grp_tf = None
    for it in items or ():
        t = type(it).__name__
        if t in ("Path", "Ellipse"):
            geom.append(it)
        elif t == "Fill":
            local["fill"] = it
            local["stroked"] = False
        elif t == "Stroke":
            local["stroke"] = it
            local["stroked"] = True
        elif t == "TransformShape":
            grp_tf = it
        elif t == "Group":
            _leaves_of(getattr(it, "shapes", []), parent, local, out)

    here = parent if grp_tf is None else parent.compose(_matrix_of(grp_tf))

    for g in geom:
        leaf = _leaf_of(g, here, local)
        if leaf is not None:
            out.append(leaf)


def _leaf_of(item, m: Transform, ctx: dict):
    kind = type(item).__name__
    if kind == "Path":
        bez = getattr(getattr(item, "shape", None), "value", None)
        verts = getattr(bez, "vertices", None)
        if not verts:
            return None
        coords = [m(float(v.x), float(v.y)) for v in verts]
        closed = bool(getattr(bez, "closed", False))
        rgb = _rgb(getattr(ctx.get("fill") or ctx.get("stroke"), "color", None)
                   if (ctx.get("fill") or ctx.get("stroke")) else None)
        ink, color = _ink_and_color(rgb)
        norm = _resample(coords, IMPORT_POINTS, closed)
        pts = tuple(Point(x, y) for x, y in norm)
        width = _scalar(_static(getattr(ctx.get("stroke"), "width", None)), 1.5)
        if closed:
            return InkShape(ring=pts, ink=ink, fill=bool(ctx.get("fill")) and not ctx.get("stroked"),
                            width=width, color=color)
        return InkLine(points=pts, width=width, ink=ink, closed=False, color=color)

    if kind == "Ellipse":
        c = _vec(_static(getattr(item, "position", None)), (0.0, 0.0))
        s = _vec(_static(getattr(item, "size", None)), (2.0, 2.0))
        rgb = _rgb(getattr(ctx.get("fill") or ctx.get("stroke"), "color", None)
                   if (ctx.get("fill") or ctx.get("stroke")) else None)
        ink, color = _ink_and_color(rgb)
        if abs(s[0] - s[1]) < 0.75 and s[0] <= 12.0:
            # 小圆 → 点（保留 ink_dot 语义，而非硬塞成多边形）
            cx, cy = m(c[0], c[1])
            return InkDot(pos=Point(cx, cy), r=max(0.5, s[0] / 2.0), ink=ink, color=color)
        coords = _circle_coords(c, s, IMPORT_POINTS)
        pts = tuple(Point(*m(x, y)) for x, y in coords)
        return InkShape(ring=pts, ink=ink, fill=True, color=color)
    return None


# ─────────────────── 入口 ───────────────────
def import_lottie(path: str) -> List[Group]:
    """解析 Lottie JSON（含 gzip 的 tgs）→ 四原语场景（list[Group]）。"""
    try:
        from lottie.parsers.tgs import parse_tgs
    except ImportError as e:  # pragma: no cover
        raise LottieImportError(
            "L1 导入需要 python-lottie：pip install 'spolvero[lottie]'"
        ) from e

    try:
        anim = parse_tgs(path)
    except Exception as e:  # noqa: BLE001 — 统一成可读错误
        raise LottieImportError(f"Lottie 解析失败: {e}") from e

    layers = getattr(anim, "layers", None) or []
    if not layers:
        raise LottieImportError("Lottie 文件不含任何图层")

    nodes: List[Group] = []
    for layer in layers:
        if type(layer).__name__ != "ShapeLayer":
            continue
        base = _matrix_of(getattr(layer, "transform", None))
        leaves: List = []
        _leaves_of(getattr(layer, "shapes", []), base, {}, leaves)
        if leaves:
            nodes.append(Group(tuple(leaves), Transform.identity()))

    if not nodes:
        raise LottieImportError("Lottie 文件不含可导入的矢量形状图层")
    return nodes


def import_summary(nodes: List[Group]) -> dict:
    from spolvero.core.scene import flatten_all

    leaves = flatten_all(nodes)
    return {
        "layers": len(nodes),
        "leaves": len(leaves),
        "shapes": sum(1 for lf in leaves if isinstance(lf, InkShape)),
        "lines": sum(1 for lf in leaves if isinstance(lf, InkLine)),
        "dots": sum(1 for lf in leaves if isinstance(lf, InkDot)),
    }
