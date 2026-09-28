"""作画痕迹层（M7 前置）：纸纹 / 蚀刻排线 / 形体明暗 / 光晕 / 雾化 / 画幅。

定位（SPEC §3 红线 5 的可执行边界）：
**禁的是「光」（照明模型），不是「光感」与「作画痕迹」。** 本模块只做后者——
它不改变任何构件的参数、不进入参数空间、不改变控制点数，且**整层可关**：
`fx=None` 时渲染路径与从前逐字节一致。

关掉本层画面结构仍完整成立 → 所以它是「层」，不是「主渲染」。

确定性：几何用 shapely 裁剪（GEOS，确定）、明暗用整数 lerp、噪声用整数哈希，
不用 libm、不用随机数发生器。参考影片的颜料 alpha 只在 0.04–0.22，
本模块的量级同样按「纹理要隐、排线要密」校准（见 spike/richness.py 的分区 MAD 证据）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

RGB = Tuple[int, int, int]

# ── 量级常量（来自 spike 的分区 MAD 校准，勿凭感觉调）──
GRAIN_GAIN = 58.0      # 三尺度噪声总增益（首版 132 → 背景 std 18，糊成电视雪花）
FIBRE_GAIN = 1.0
DUST_GAIN = 9.0
HATCH_SPACING = 1.9    # 基点间距（参照物 etch() 的 gap 仅 3–5px；首版 3.6 → 几乎不可见）
HATCH_SPACING_SPAN = 2.6
HATCH_WIDTH = 1.15
HATCH_BANDS = 8        # 排线按 y 分带数：每带一次 clipRect + 一次 drawPath
HATCH_MIN_AREA = 3000.0  # 只有面积 ≥ 此值的「块面」才做明暗分带与排线；
# 笔画（细长填充条）面积仅数百 px，给它们分带既是浪费又会糊成一团。
HATCH_ALPHA_MAX = 150
RAMPS = 9              # 形体明暗分带数


@dataclass(frozen=True)
class EffectsRuntime:
    """一帧已解析好的作画痕迹参数（由风格资产 + 时刻算出，渲染器只消费）。"""

    material: float = 0.0
    ramp: float = 0.0
    hatch: float = 0.0
    glow: float = 0.0
    vignette: float = 0.0
    haze: float = 0.0
    border: bool = False
    paper_rgb: RGB = (255, 255, 255)
    grain_seed: int = 4821

    @property
    def is_noop(self) -> bool:
        return not (
            self.material or self.ramp or self.hatch or self.glow
            or self.vignette or self.haze or self.border
        )


# ══════════════════ 确定性噪声（整数哈希，不碰 libm / 不用 RNG）══════════════════
def _hash01(ix, iy, seed):
    u = np.uint64
    n = (ix.astype(u) * u(73856093)) ^ (iy.astype(u) * u(19349663)) ^ (u(seed) * u(83492791))
    n = (n ^ (n >> u(13))) * u(1274126177)
    n = n ^ (n >> u(16))
    return (n & u(0xFFFFFF)).astype(np.float64) / 16777215.0


# ── 静态场缓存（对齐参照影片的 texture()/scars[]：**一次生成、多次复用**）──
# 这些场只依赖 (h, w, seed)，与时刻无关；一部片子里 seed 只随 12fps 抖动换相（个位数取值）。
# 不缓存的话每帧都要重建 1.44M 元素的场，是性能灾难（详见下方 _block 注释）。
_FIELD_CACHE: "dict" = {}
_CACHE_MAX = 24


def _cache_put(key, arr: np.ndarray) -> np.ndarray:
    if len(_FIELD_CACHE) >= _CACHE_MAX:
        _FIELD_CACHE.clear()
    arr.flags.writeable = False  # 缓存数组不可改，防止调用方就地修改导致串帧
    _FIELD_CACHE[key] = arr
    return arr


def grid(h: int, w: int):
    """缓存的像素坐标网格（np.mgrid 本身要 20ms，且每帧都建）→ (xx, yy)。"""
    kx, ky = ("gridx", h, w), ("gridy", h, w)
    hx, hy = _FIELD_CACHE.get(kx), _FIELD_CACHE.get(ky)
    if hx is not None and hy is not None:
        return hx, hy
    yy, xx = np.mgrid[0:h, 0:w]
    return _cache_put(kx, np.ascontiguousarray(xx)), _cache_put(ky, np.ascontiguousarray(yy))


def _block(xx, yy, size, seed):
    """按 size 分块取哈希（块内常量，等效于把小哈希图上采样 size 倍）。

    性能注记（2026-09-28 实测，勿回退）：
    旧实现为 `np.repeat(np.repeat(b, size, 0), size, 1)`。当 size=32 时源块只有 29×50，
    numpy 会走「stride-0 广播拷贝」的**标量路径**去物化 1.44M 个 float64——
    实测 **4.4–6.1 s/次**，占单帧 4.95 s 的 90% 以上，是「300 帧要跑半小时」的唯一真凶。
    （本机 11.5MB 数组相加只要 3.08 ms，所以不是 numpy 慢，是这个算子选错了。）

    改为**广播构造**：ix 取列号 (1,w)、iy 取行号 (h,1)，直接 broadcasting 出 (h,w)，
    值逐元素与旧实现相同，实测 ~20 ms（快 200 倍）。
    """
    return _hash01(xx[:1, :] // size, yy[:, :1] // size, seed)


def grain_field(h: int, w: int, seed: int) -> np.ndarray:
    """三尺度噪声场：细颗粒 / 4px 颜料团块 / 32px 晕染。结果缓存。"""
    key = ("grain", h, w, seed)
    hit = _FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    xx, yy = grid(h, w)
    fine = _hash01(xx, yy, seed) - 0.5
    clump = _block(xx, yy, 4, seed + 11) - 0.5
    broad = _block(xx, yy, 32, seed + 23) - 0.5
    return _cache_put(key, 0.42 * fine + 0.40 * clump + 0.18 * broad)


def fibre_field(h: int, w: int, seed: int, n: int = 600) -> np.ndarray:
    """稀疏纤维短划：手抄纸 / 版画的经纬感。结果缓存。"""
    key = ("fibre", h, w, seed, n)
    hit = _FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    f = np.zeros((h, w), dtype=np.float64)
    rng = np.arange(n)
    xs = (_hash01(rng, rng * 0 + seed, 7) * w).astype(np.int64)
    ys = (_hash01(rng * 0 + seed, rng, 13) * h).astype(np.int64)
    ln = (_hash01(rng, rng + seed, 19) * 60 + 12).astype(np.int64)
    dl = (_hash01(rng, rng + seed, 29) * 14 - 7).astype(np.int64)
    amp = _hash01(rng, rng + seed, 31) - 0.5
    for i in range(n):
        x0, y0, L, d = int(xs[i]), int(ys[i]), int(ln[i]), int(dl[i])
        if y0 + L >= h:
            continue
        for k in range(L):
            f[y0 + k, (x0 + d * k // max(L, 1)) % w] += amp[i] * (1.0 - k / L)
    return _cache_put(key, f)


def dust_field(h: int, w: int, seed: int, n: int = 380) -> np.ndarray:
    key = ("dust", h, w, seed, n)
    hit = _FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    d = np.zeros((h, w), dtype=np.float64)
    rng = np.arange(n)
    xs = (_hash01(rng, rng + seed, 41) * w).astype(np.int64)
    ys = (_hash01(rng + seed, rng, 43) * h).astype(np.int64)
    a = _hash01(rng, rng + seed, 47) - 0.28
    for i in range(n):
        d[int(ys[i]), int(xs[i])] += float(a[i])
    return _cache_put(key, d)


def material_field(h: int, w: int, seed: int) -> np.ndarray:
    """合成好的材质场（三尺度噪声 + 纤维 + 尘埃）。**整场缓存**——
    参照影片把颜料纹理预生成成一张 640×640 图案后 `createPattern('repeat')` 复用；
    这里是同一手法：场只建一次，之后每帧只做一次全幅相加（内存带宽级）。"""
    key = ("material", h, w, seed)
    hit = _FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    g = grain_field(h, w, seed)
    g = g + fibre_field(h, w, seed, 600) * FIBRE_GAIN
    g = g + dust_field(h, w, seed + 5, 380) * DUST_GAIN
    return _cache_put(key, g)


def apply_material(arr: np.ndarray, seed: int, amount: float) -> np.ndarray:
    if amount <= 0.0:
        return arr
    h, w, _ = arr.shape
    g = material_field(h, w, seed)
    # 保持与原实现的运算顺序一致（(g*amount)*GAIN）——换序会在末位 ulp 上产生差异，
    # 进而让 PNG 字节变掉、破坏 L1 逐字节门禁。
    return np.clip(arr + (g * amount)[:, :, None] * GRAIN_GAIN, 0, 255)


def vignette_factor(h: int, w: int, amount: float, power: float = 0.75) -> np.ndarray:
    key = ("vigfac", h, w, amount, power)
    hit = _FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dx = (xx / max(w - 1, 1) - 0.5) * 2.0
    dy = (yy / max(h - 1, 1) - 0.5) * 2.0
    k = 1.0 - amount * np.clip((dx * dx + dy * dy) * power, 0.0, 1.0) ** 0.5
    return _cache_put(key, k)


def apply_vignette(arr: np.ndarray, amount: float, power: float = 0.75) -> np.ndarray:
    if amount <= 0.0:
        return arr
    h, w, _ = arr.shape
    k = vignette_factor(h, w, amount, power)
    return np.clip(arr * k[:, :, None], 0, 255)


def haze_factor(h: int, amount: float, horizon: float = 0.44, span: float = 0.34) -> np.ndarray:
    key = ("hazefac", h, amount, horizon, span)
    hit = _FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    yy = np.arange(h, dtype=np.float64) / max(h - 1, 1)
    a = np.clip(1.0 - np.abs(yy - horizon) / span, 0.0, 1.0) * amount
    return _cache_put(key, a)


def apply_haze(
    arr: np.ndarray, paper: RGB, amount: float, horizon: float = 0.44, span: float = 0.34
) -> np.ndarray:
    """大气透视：越靠近地平线越向纸色靠拢，把远景推远。"""
    if amount <= 0.0:
        return arr
    h, _w, _ = arr.shape
    a = haze_factor(h, amount, horizon, span)
    p = np.array(paper, dtype=np.float64)
    return np.clip(
        arr * (1.0 - a[:, None, None]) + p[None, None, :] * a[:, None, None], 0, 255
    )


def ring_area(pts) -> float:
    """多边形面积（鞋带公式）。纯 +-×÷，用于「值不值得做明暗/排线」的判定。"""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


# ══════════════════ 几何层（绘制期；排线用 clipPath 交给光栅器，不再用 shapely 裁剪）══════════════════
def _lines_of(geom) -> List:
    if geom.is_empty:
        return []
    t = geom.geom_type
    if t == "LineString":
        return [geom]
    if t == "MultiLineString":
        return list(geom.geoms)
    if t == "GeometryCollection":
        out: List = []
        for g in geom.geoms:
            out.extend(_lines_of(g))
        return out
    return []


def hatch_segments(ring: Sequence[Tuple[float, float]], spacing: float, angle_deg: float = -34.0) -> List:
    """斜向等距直线裁进多边形（蚀刻排线的几何基础）。确定性（GEOS）。"""
    from shapely.geometry import LineString, Polygon

    poly = Polygon(ring)
    if not poly.is_valid or poly.area <= 1.0:
        return []
    rad = angle_deg * 3.141592653589793 / 180.0
    from spolvero.core.dmath import dcos, dsin

    dx, dy = dcos(rad), dsin(rad)
    nx, ny = -dy, dx
    minx, miny, maxx, maxy = poly.bounds
    proj = [p[0] * nx + p[1] * ny for p in poly.exterior.coords]
    lo, hi = min(proj), max(proj)
    cx, cy = poly.centroid.x, poly.centroid.y
    L = ((maxx - minx) ** 2 + (maxy - miny) ** 2) ** 0.5 * 1.2 + 4.0
    segs: List = []
    d = lo
    while d <= hi:
        k = d - (cx * nx + cy * ny)
        px, py = cx + nx * k, cy + ny * k
        p0 = (px - dx * L, py - dy * L)
        p1 = (px + dx * L, py + dy * L)
        segs.extend(_lines_of(poly.intersection(LineString([p0, p1]))))
        d += spacing
    return segs
