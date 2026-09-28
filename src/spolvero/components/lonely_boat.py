"""「孤舟渡江」首片构件库（东方极简符号构成）。

四原型：boat（孤舟）/ mountain（远山）/ water（水纹）/ moon（月）。

约定：
- 每个 build 在局部坐标系产出几何，锚点置原点、+y 向下，不含场景布局。
- 几何形变的随机来自 (seed, iid) 派生（命门 1），且只调参数、不调控制点数量（命门 3）。
- 三角计算走 core.dmath（dcos/dsin），不调用 libm，保跨平台 L2 一致。
- ink ∈ [0,1]，低=深、高=浅（见 render.common.gray_of）。
"""

from __future__ import annotations

import math

from spolvero.core.component import (
    ComponentLibrary,
    ComponentPrototype,
    ParamSpec,
    prototype_from_spec,
    register_pattern,
)
from spolvero.core.dmath import dcos, dsin
from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.rng import derive
from spolvero.core.transform import Transform
from spolvero.core.types import Point

# ── 船体恒定 8 控制点（命门 3：实例化只调参数不调点数）──
# 船形：两端上翘（bow/stern tip），底部龙骨下沉，甲板近平 —— 有舱容，非叶形。
HULL_T = [
    (-0.50, -0.34),  # 船首上翘
    (-0.30, 0.30),
    (0.00, 0.48),    # 龙骨
    (0.30, 0.30),
    (0.50, -0.34),   # 船尾上翘
    (0.32, -0.16),
    (0.00, -0.13),   # 甲板
    (-0.32, -0.16),
]
CANOPY_T = [(-0.50, 0.0), (-0.28, -0.62), (0.0, -0.80), (0.28, -0.62), (0.50, 0.0)]


def _bump(t: float, c: float, w: float) -> float:
    """确定性钟形（纯 +-*/，无 exp/libm）。用于远山山形。"""
    d = (t - c) / w
    v = 1.0 - d * d
    return v if v > 0.0 else 0.0


def _circle(cx: float, cy: float, r: float, n: int) -> list[Point]:
    """恒定 n 点圆（命门 3）。"""
    return [
        Point(cx + r * dcos(2.0 * math.pi * k / n), cy + r * dsin(2.0 * math.pi * k / n))
        for k in range(n)
    ]


# ─────────────────────────── boat（孤舟）───────────────────────────
BOAT_PARAMS = [
    ParamSpec("length", 64.0, 30.0, 150.0, "float"),
    ParamSpec("beam_ratio", 0.22, 0.16, 0.30, "float"),
    ParamSpec("hull_ink", 0.32, 0.10, 0.85, "float"),
    ParamSpec("canopy_w", 0.42, 0.30, 0.55, "float"),
    ParamSpec("canopy_h", 0.14, 0.08, 0.22, "float"),
    ParamSpec("mast_h", 0.62, 0.35, 0.90, "float"),
    ParamSpec("tilt", 0.0, -4.0, 4.0, "float"),
    ParamSpec("has_canopy", True, p_true=0.66, kind="bool"),
    ParamSpec("has_mast", False, p_true=0.34, kind="bool"),
    ParamSpec("has_lamp", False, p_true=0.40, kind="bool"),
]


def _build_boat(params: dict, seed: str, iid: str) -> Group:
    L = params["length"]
    D = L * params["beam_ratio"]
    ink = params["hull_ink"]
    # 船体：8 控制点，逐点微抖动（不增点数，命门 3）
    hull = []
    for k, (ux, uy) in enumerate(HULL_T):
        jx = (derive(seed, iid, f"hjx{k}") - 0.5) * 0.05 * L
        jy = (derive(seed, iid, f"hjy{k}") - 0.5) * 0.10 * D
        hull.append(Point(ux * L + jx, (uy - 0.5) * D + jy))
    deck = -0.28 * D  # 甲板基准（贴合新船体上沿）
    children = [InkShape(ring=tuple(hull), ink=ink)]
    if params["has_canopy"]:
        cw = params["canopy_w"] * L
        ch = params["canopy_h"] * L
        ox = (derive(seed, iid, "cox") - 0.5) * 0.12 * L
        canopy = [Point(ox + ux * cw, deck + uy * ch) for ux, uy in CANOPY_T]
        children.append(InkLine(points=tuple(canopy), ink=ink))
    if params["has_mast"]:
        mx = (derive(seed, iid, "mox") - 0.5) * 0.20 * L
        children.append(
            InkLine(
                points=(Point(mx, deck), Point(mx, deck - params["mast_h"] * L)),
                ink=ink,
            )
        )
    if params["has_lamp"]:
        lx = (derive(seed, iid, "lox") - 0.5) * 0.30 * L
        children.append(InkDot(pos=Point(lx, deck - 0.04 * L), r=1.8 + ink, ink=ink))
    # tilt 作为局部朝向，外包一层 group 旋转
    return Group(tuple(children), Transform.rotate(params["tilt"]))


# ─────────────────────────── mountain（远山）───────────────────────────
MOUNTAIN_PARAMS = [
    ParamSpec("width", 180.0, 90.0, 320.0, "float"),
    ParamSpec("height", 54.0, 24.0, 110.0, "float"),
    ParamSpec("jag", 0.4, 0.0, 1.0, "float"),
    ParamSpec("ink", 0.72, 0.55, 0.88, "float"),  # 高=浅（远山留白）
]


def _build_mountain(params: dict, seed: str, iid: str) -> Group:
    W = params["width"]
    H = params["height"]
    jag = params["jag"]
    ink = params["ink"]
    # 恒定 9 点（命门 3）：山脊 x 自 -0.5W 严格单调到 +0.5W。
    # 首末点钉在基线 y=0 作闭合锚点；中间点一律钳制在基线上方（y ≤ -0.5）。
    # 「x 单调 + 全部中间顶点位于闭合边同侧」→ 必为简单多边形（shapely is_valid），
    # 旧实现追加重合基线点 / 抖动下潜会破坏该性质，被 M4 校验器捕获。
    N = 9
    p1 = 0.30 + derive(seed, iid, "m1") * 0.25
    p2 = 0.60 + derive(seed, iid, "m2") * 0.25
    a1 = 0.6 + derive(seed, iid, "a1") * 0.4
    a2 = 0.4 + derive(seed, iid, "a2") * 0.4
    pts = []
    for k in range(N):
        t = k / (N - 1)
        x = (t - 0.5) * W
        if k == 0 or k == N - 1:
            y = 0.0
        else:
            y = -(a1 * H * _bump(t, p1, 0.18) + a2 * H * _bump(t, p2, 0.15))
            y -= (derive(seed, iid, f"mj{k}") - 0.5) * jag * H * 0.18
            y = min(y, -0.5)
        pts.append(Point(x, y))
    return Group((InkShape(ring=tuple(pts), ink=ink, fill=True),), Transform.identity())


# ─────────────────────────── water（水纹）───────────────────────────
WATER_PARAMS = [
    ParamSpec("width", 240.0, 120.0, 1000.0, "float"),
    ParamSpec("lines", 3, 2, 4, "int"),
    ParamSpec("amp", 3.0, 1.0, 7.0, "float"),
    ParamSpec("spacing", 13.0, 8.0, 22.0, "float"),
    ParamSpec("base", 0.0, -40.0, 20.0, "float"),
    ParamSpec("ink", 0.30, 0.12, 0.55, "float"),
]


def _build_water(params: dict, seed: str, iid: str) -> Group:
    W = params["width"]
    nlines = int(params["lines"])
    amp = params["amp"]
    sp = params["spacing"]
    base = params["base"]
    ink = params["ink"]
    pts_per = 16  # 每条水纹恒定 16 点（命门 3）
    children = []
    for li in range(nlines):
        oy = base - li * sp
        ph = derive(seed, iid, f"wp{li}") * 6.2831853
        ln = []
        for k in range(pts_per):
            t = k / (pts_per - 1)
            x = (t - 0.5) * W
            y = oy + dsin(ph + t * 6.2831853) * amp
            ln.append(Point(x, y))
        ci = ink + (derive(seed, iid, f"wi{li}") - 0.5) * 0.12
        children.append(InkLine(points=tuple(ln), ink=max(0.05, min(0.9, ci))))
    return Group(tuple(children), Transform.identity())


# ─────────────────────────── moon（月）───────────────────────────
MOON_PARAMS = [
    ParamSpec("r", 20.0, 8.0, 30.0, "float"),
    ParamSpec("ink", 0.18, 0.05, 0.40, "float"),
    ParamSpec("halo", True, p_true=0.5, kind="bool"),
]


def _build_moon(params: dict, seed: str, iid: str) -> Group:
    r = params["r"]
    ink = params["ink"]
    children = [InkDot(pos=Point(0.0, 0.0), r=r, ink=ink)]
    if params["halo"]:
        ring = _circle(0.0, 0.0, r * 1.9, 12)
        children.append(InkLine(points=tuple(ring), closed=True, ink=min(0.9, ink + 0.18)))
    return Group(tuple(children), Transform.identity())


def _spec_from_params(name: str, pattern: str, params: list) -> dict:
    """由 ParamSpec 列表导出声明式规格（与 components.yaml 同源，供漂移校验）。"""
    return {
        "name": name,
        "pattern": pattern,
        "params": [
            {
                "name": p.name,
                "default": p.default,
                "lo": p.lo,
                "hi": p.hi,
                "kind": p.kind,
                "p_true": p.p_true,
            }
            for p in params
        ],
    }


# 声明式组件规格（与 projects/lonely_boat/components.yaml 必须一致，由测试守护）
LONELY_BOAT_COMPONENT_SPECS: list[dict] = [
    _spec_from_params("boat", "boat", BOAT_PARAMS),
    _spec_from_params("mountain", "mountain", MOUNTAIN_PARAMS),
    _spec_from_params("water", "water", WATER_PARAMS),
    _spec_from_params("moon", "moon", MOON_PARAMS),
]


# 注册引擎内置构建模式（红线性：AI 只引用 pattern 键，从不持有构建代码）
register_pattern("boat", _build_boat)
register_pattern("mountain", _build_mountain)
register_pattern("water", _build_water)
register_pattern("moon", _build_moon)


def lonely_boat_library() -> ComponentLibrary:
    """构造「孤舟渡江」构件库（含 boat/mountain/water/moon 四原型，pattern 引用）。"""
    lib = ComponentLibrary()
    for spec in LONELY_BOAT_COMPONENT_SPECS:
        lib.register(prototype_from_spec(spec))
    return lib
