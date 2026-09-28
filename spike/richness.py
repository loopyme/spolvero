"""画面丰富度探针（spike）：把参照影片里可移植的技术在 Spolvero 引擎上验证一遍。

参照物是用户给的单文件 HTML 影片（21KB，canvas，15s，4 场）。它好看的原因**不是一招**，
而是每层都在堆质感。逐项拆解后，能移植到本项目（矢量 + 确定性）的有 4 项，本探针逐一验证：

  ① 材质层   纸纹 / 颜料颗粒 / 纤维（多尺度噪声），并支持 12fps「抖动」——
              参照物对**每一个填充**都套 createPattern 纹理，所以没有一块色是平的。
  ② 蚀刻排线  填充后再 clip 到轮廓内画斜向排线，靠线密度做明暗 —— 参照物的 etch()。
              这是纯矢量可做的，不需要光栅化，也不需要新原语（是 ink_shape 的渲染语义）。
  ③ 尘埃层   稀疏亮暗颗粒，制造"空气里有东西"的感觉。
  ④ 画幅层   不均匀的冲印边框 + 暗角，替代数字感的干净画框。

全部用整数哈希噪声 + 确定性几何，不碰 libm，保 L1/L2。
本文件是**探针**，不接入引擎；验证通过后再按 M7 立项落地。

用法：python spike/richness.py    产物：spike/out/rich_*.png
"""

from __future__ import annotations

import hashlib
import math
import os
import sys

import numpy as np
import skia

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from spolvero.animation.film import scene_at  # noqa: E402
from spolvero.api import get_style, load_project  # noqa: E402
from spolvero.core.dmath import dcos, dsin  # noqa: E402
from spolvero.core.primitives import InkDot, InkLine, InkShape  # noqa: E402
from spolvero.render.common import color_of  # noqa: E402
from spolvero.styles.apply import darken, mix, parse_hex, recolor  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "spike", "out")
STORY = os.path.join(ROOT, "projects", "lonely_boat_story")
T = 7.0  # 取叙事最强的一刻（主舟大、居中偏右）


# ══════════════════ 确定性噪声（整数哈希，不碰 libm）══════════════════
def hash01(ix, iy, seed):
    u = np.uint64
    n = (ix.astype(u) * u(73856093)) ^ (iy.astype(u) * u(19349663)) ^ (u(seed) * u(83492791))
    n = (n ^ (n >> u(13))) * u(1274126177)
    n = n ^ (n >> u(16))
    return (n & u(0xFFFFFF)).astype(np.float64) / 16777215.0


def _block(xx, yy, size, seed):
    b = hash01(xx // size, yy // size, seed)
    return np.repeat(np.repeat(b, size, 0), size, 1)[: yy.shape[0], : xx.shape[1]]


def grain_field(h, w, seed):
    """三尺度噪声场：细颗粒 / 颜料团块 / 大块晕染。返回 [-0.5, 0.5]。"""
    yy, xx = np.mgrid[0:h, 0:w]
    fine = hash01(xx, yy, seed) - 0.5
    clump = _block(xx, yy, 4, seed + 11) - 0.5
    broad = _block(xx, yy, 32, seed + 23) - 0.5
    return 0.42 * fine + 0.40 * clump + 0.18 * broad


def fibre_field(h, w, seed, n=1400):
    """稀疏纤维短划：手抄纸/版画的经纬感。"""
    f = np.zeros((h, w), dtype=np.float64)
    rng = np.arange(n)
    xs = (hash01(rng, rng * 0 + seed, 7) * w).astype(np.int64)
    ys = (hash01(rng * 0 + seed, rng, 13) * h).astype(np.int64)
    ln = (hash01(rng, rng + seed, 19) * 60 + 12).astype(np.int64)  # 长度 12–72
    dl = (hash01(rng, rng + seed, 29) * 14 - 7).astype(np.int64)
    amp = (hash01(rng, rng + seed, 31) - 0.5)
    for i in range(n):
        x0, y0, L, d = int(xs[i]), int(ys[i]), int(ln[i]), int(dl[i])
        if y0 + L >= h:
            continue
        for k in range(L):
            x = (x0 + d * k // max(L, 1)) % w
            f[y0 + k, x] += amp[i] * (1.0 - k / L)
    return f


def dust_specks(h, w, seed, n=900):
    d = np.zeros((h, w), dtype=np.float64)
    rng = np.arange(n)
    xs = (hash01(rng, rng + seed, 41) * w).astype(np.int64)
    ys = (hash01(rng + seed, rng, 43) * h).astype(np.int64)
    a = hash01(rng, rng + seed, 47) - 0.28
    for i in range(n):
        d[int(ys[i]), int(xs[i])] += float(a[i])
    return d


def apply_material(arr, seed, clump=1.0, fibre=1.0, dust=1.0):
    """把材质叠加到 RGB 数组上。

    强度刻意压得很低（目标 std ≈ 8–10）：参照物的颜料 alpha 只在 0.04–0.22。
    纹理一烈就变成电视雪花，画面立刻掉档——这是本探针第一次跑出来的教训。
    """
    h, w, _ = arr.shape
    g = grain_field(h, w, seed)
    if fibre:
        g = g + fibre_field(h, w, seed, 600) * 1.0
    if dust:
        g = g + dust_specks(h, w, seed + 5, 380) * 9.0
    out = arr + (g * clump)[:, :, None] * 58.0
    return np.clip(out, 0, 255)


def haze(arr, paper, amount=0.30, horizon=0.44, span=0.34):
    """大气雾：越靠近地平线越向纸色靠拢，把远山推远（确定性垂直斜坡）。"""
    h, _w, _ = arr.shape
    yy = np.arange(h, dtype=np.float64) / (h - 1)
    a = np.clip(1.0 - np.abs(yy - horizon) / span, 0.0, 1.0) * amount
    p = np.array(paper, dtype=np.float64)
    return np.clip(arr * (1.0 - a[:, None, None]) + p[None, None, :] * a[:, None, None], 0, 255)


def vignette(arr, strength=0.34, power=0.75):
    h, w, _ = arr.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dx = (xx / (w - 1) - 0.5) * 2.0
    dy = (yy / (h - 1) - 0.5) * 2.0
    # 用平方距离的幂次做衰减，避开 sqrt/exp（不碰 libm）
    d2 = dx * dx + dy * dy
    k = 1.0 - strength * np.clip(d2 * power, 0.0, 1.0) ** 0.5
    return np.clip(arr * k[:, :, None], 0, 255)


# ══════════════════ 蚀刻排线（纯矢量，参照物 etch()）══════════════════
def _lines_of(geom):
    if geom.is_empty:
        return []
    t = geom.geom_type
    if t == "LineString":
        return [geom]
    if t == "MultiLineString":
        return list(geom.geoms)
    if t == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(_lines_of(g))
        return out
    return []


def hatch_segments(ring, spacing=6.0, angle_deg=-34.0):
    """把斜向等距直线裁到多边形内，返回线段列表（shapely 裁剪，确定性）。"""
    from shapely.geometry import LineString, Polygon

    poly = Polygon(ring)
    if not poly.is_valid or poly.area <= 1.0:
        return []
    rad = angle_deg * math.pi / 180.0
    dx, dy = dcos(rad), dsin(rad)
    nx, ny = -dy, dx
    minx, miny, maxx, maxy = poly.bounds
    proj = [p[0] * nx + p[1] * ny for p in poly.exterior.coords]
    lo, hi = min(proj), max(proj)
    cx, cy = poly.centroid.x, poly.centroid.y
    L = math.hypot(maxx - minx, maxy - miny) * 1.2 + 4.0

    segs = []
    d = lo
    while d <= hi:
        k = d - (cx * nx + cy * ny)
        px, py = cx + nx * k, cy + ny * k
        p0 = (px - dx * L, py - dy * L)
        p1 = (px + dx * L, py + dy * L)
        for ls in _lines_of(poly.intersection(LineString([p0, p1]))):
            segs.append(ls)
        d += spacing
    return segs


# ══════════════════ 绘制 ══════════════════
def styled_leaves(proj, style, t):
    groups = scene_at(proj, t)
    if len(groups) == len(proj.groups):
        return [
            recolor(g, style, proj.tints.get(proj.iids[i]))
            for i, g in enumerate(groups)
        ]
    return [recolor(g, style) for g in groups]


def draw(canvas, leaves, hatch_amt=0.0, rough=0.0, hollow_fill=False, paper=(248, 241, 221)):
    """基础绘制（对齐 render/skia.py），可选叠加蚀刻排线与毛边轮廓。

    hollow_fill：把「闭合但只描边」的形状先铺一层极淡的底再排线（参照物的人体衣着就是这么画的）——
    空心轮廓是最显"矢量幼稚感"的一处，填上淡淡的排线体块立刻有了体积。
    """
    hatch_count = 0
    stroke = skia.Paint()
    stroke.setAntiAlias(True)
    stroke.setStyle(skia.Paint.kStroke_Style)
    stroke.setStrokeJoin(skia.Paint.kRound_Join)
    stroke.setStrokeCap(skia.Paint.kRound_Cap)
    fillp = skia.Paint()
    fillp.setAntiAlias(True)
    fillp.setStyle(skia.Paint.kFill_Style)

    from spolvero.core.scene import flatten_all

    for idx, leaf in enumerate(flatten_all(leaves)):
        r, g, b = color_of(leaf.ink, leaf.color)
        col = skia.ColorSetARGB(255, r, g, b)
        if isinstance(leaf, InkDot):
            fillp.setColor(col)
            canvas.drawCircle(leaf.pos.x, leaf.pos.y, leaf.r, fillp)
            continue

        is_shape = isinstance(leaf, InkShape)
        pts = leaf.ring if is_shape else leaf.points
        closed = is_shape or bool(getattr(leaf, "closed", False))
        path = _path(pts, closed)

        filled = is_shape and leaf.fill
        hollow = is_shape and not leaf.fill and hollow_fill
        if filled or hollow:
            if hollow:
                light = mix((r, g, b), paper, 0.70)
                fillp.setColor(skia.ColorSetARGB(255, light[0], light[1], light[2]))
                canvas.drawPath(path, fillp)
            else:
                fillp.setColor(col)
                canvas.drawPath(path, fillp)
            if hatch_amt > 0.0:
                hatch_count += _hatch(canvas, leaf, (r, g, b), hatch_amt)
            if rough > 0.0:
                _rough(canvas, pts, (r, g, b), max(leaf.width, 1.4), rough, idx, closed=True)
        else:
            stroke.setColor(col)
            stroke.setStrokeWidth(leaf.width)
            canvas.drawPath(path, stroke)
            if rough > 0.0:
                _rough(canvas, pts, (r, g, b), leaf.width, rough, idx, closed=closed)
    return hatch_count


def _path(pts, closed):
    path = skia.Path()
    path.moveTo(pts[0].x, pts[0].y)
    for p in pts[1:]:
        path.lineTo(p.x, p.y)
    if closed:
        path.close()
    return path


# 参照物的 roughOutline()：主笔之外补两笔错位淡描，边缘不再是机器切的直线。
_ROUGH_OFFSETS = ((1.7, -1.0), (-1.2, 1.4))


def _rough(canvas, pts, rgb, width, amount, idx, closed):
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setStyle(skia.Paint.kStroke_Style)
    p.setStrokeCap(skia.Paint.kRound_Cap)
    xs = [q.x for q in pts]
    ys = [q.y for q in pts]
    scale = min(max((max(xs) - min(xs) + max(ys) - min(ys)) / 260.0, 0.35), 1.6)
    for j, (ox, oy) in enumerate(_ROUGH_OFFSETS):
        jitter = 0.55 + (idx % 3) * 0.22
        path = skia.Path()
        path.moveTo(pts[0].x + ox * scale * jitter, pts[0].y + oy * scale * jitter)
        for q in pts[1:]:
            path.lineTo(q.x + ox * scale * jitter, q.y + oy * scale * jitter)
        if closed:
            path.close()
        p.setColor(skia.ColorSetARGB(int(255 * 0.30 * amount), rgb[0], rgb[1], rgb[2]))
        p.setStrokeWidth(max(0.6, width * (0.45 + 0.25 * j)))
        canvas.drawPath(path, p)


def _hatch(canvas, leaf, rgb, amount):
    ring = [(p.x, p.y) for p in leaf.ring]
    ys = [p[1] for p in ring]
    ys_lo, ys_hi = min(ys), max(ys)
    span = max(ys_hi - ys_lo, 1e-6)
    dark = darken(parse_hex("#%02x%02x%02x" % rgb), 0.55)
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setStyle(skia.Paint.kStroke_Style)
    p.setStrokeCap(skia.Paint.kRound_Cap)
    # 排线要密：参照物 etch() 的 gap 仅 3–5px，稀了等于没画（首轮 MAD 0.06 的教训）
    spacing = 1.9 + 2.6 * (1.0 - amount)
    segs = hatch_segments(ring, spacing=spacing, angle_deg=-34.0)
    for ls in segs:
        cs = list(ls.coords)
        ymid = (cs[0][1] + cs[-1][1]) / 2.0
        u = (ymid - ys_lo) / span  # 0=形顶 1=形底
        a = int(255 * (0.16 + 0.42 * u) * amount)
        a = min(a, 150)
        if a <= 3:
            continue
        p.setColor(skia.ColorSetARGB(a, dark[0], dark[1], dark[2]))
        p.setStrokeWidth(1.15)
        path = skia.Path()
        path.moveTo(cs[0][0], cs[0][1])
        for c in cs[1:]:
            path.lineTo(c[0], c[1])
        canvas.drawPath(path, p)
    return len(segs)


def emulsion_border(canvas, w, h, seed=99):
    """不均匀冲印边框（顶/底压条边缘微微抖动），替代干净的数字化画框。"""
    top = [(0, 0), (w, 0)]
    for i in range(24, w, 24):
        j = (hash01(np.array([i]), np.array([0]), seed)[0] - 0.5) * 9.0
        top.insert(len(top) - 1, (i, 20 + j))
    bot = [(0, h), (w, h)]
    for i in range(24, w, 24):
        j = (hash01(np.array([i]), np.array([1]), seed + 7)[0] - 0.5) * 9.0
        bot.insert(len(bot) - 1, (i, h - 20 + j))
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setColor(skia.ColorSetARGB(255, 12, 13, 10))
    for poly in (top, bot):
        path = skia.Path()
        path.moveTo(poly[0][0], poly[0][1])
        for x, y in poly[1:]:
            path.lineTo(x, y)
        path.close()
        canvas.drawPath(path, p)


def to_skia_image(arr):
    a = np.ascontiguousarray(arr.astype(np.uint8))
    rgba = np.empty((a.shape[0], a.shape[1], 4), dtype=np.uint8)
    rgba[:, :, 0] = a[:, :, 2]  # skia N32 在本机为 BGRA
    rgba[:, :, 1] = a[:, :, 1]
    rgba[:, :, 2] = a[:, :, 0]
    rgba[:, :, 3] = 255
    return skia.Image.fromarray(rgba, skia.kBGRA_8888_ColorType, alphaType=skia.kOpaque_AlphaType)


def write_png(arr, path):
    img = to_skia_image(arr)
    data = img.encodeToData(skia.EncodedImageFormat.kPNG, 95)
    with open(path, "wb") as f:
        f.write(bytes(data))
    return hashlib.sha256(bytes(data)).hexdigest()


def render(proj, style, t, *, hatch=0.0, rough=0.0, hollow=False, material=False, boil=0,
           vig=0.0, border=False, haze_amt=0.0):
    w, h = proj.width, proj.height
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    pr, pg, pb = style.paper_rgb
    canvas.clear(skia.ColorSetARGB(255, pr, pg, pb))
    n_hatch = draw(canvas, styled_leaves(proj, style, t), hatch, rough, hollow, style.paper_rgb)
    if border:
        emulsion_border(canvas, w, h, seed=99 + boil)
    img = surface.makeImageSnapshot()
    arr = img.toarray()[:, :, [2, 1, 0]].astype(np.float64)  # BGRA → RGB
    if haze_amt > 0:
        arr = haze(arr, style.paper_rgb, haze_amt)
    if material:
        arr = apply_material(arr, 4821 + boil * 977)
    if vig > 0:
        arr = vignette(arr, vig)
    return arr, n_hatch


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    proj = load_project(STORY)
    style = get_style("azurite", os.path.join(ROOT, "styles"))
    print(f"工程 {os.path.basename(STORY)}  t={T}s  {proj.width}x{proj.height}  style={style.id}")

    FULL = dict(hatch=0.95, rough=1.0, hollow=True, material=True, vig=0.10,
                border=True, haze_amt=0.22)
    variants = [
        ("rich_A_flat.png", dict()),
        ("rich_B_material.png", dict(material=True)),
        ("rich_C_hatch.png", dict(hatch=0.95, rough=1.0, hollow=True)),
        ("rich_D_full.png", dict(FULL)),
        ("rich_E_full_boil1.png", dict(FULL, boil=1)),
    ]
    results = {}
    for name, kw in variants:
        arr, nh = render(proj, style, T, **kw)
        sha = write_png(arr, os.path.join(OUT, name))
        results[name] = (arr, nh, sha)
        print(f"  {name:24s} hatch线={nh:5d}  sha256={sha[:16]}…")

    base = results["rich_A_flat.png"][0]

    # 分区测量：整体 MAD 会被暗角/雾这类全局层带偏，必须分区域看各层到底改了什么
    REGIONS = {
        "背景(留白)": (slice(40, 160), slice(40, 260)),
        "远山(填充形)": (slice(300, 380), slice(160, 440)),
        "主舟(线条)": (slice(560, 800), slice(980, 1420)),
    }
    print(f"\n{'变体':<24s}" + "".join(f"{k:>16s}" for k in REGIONS) + f"{'整体':>10s}")
    for name in ("rich_B_material.png", "rich_C_hatch.png", "rich_D_full.png"):
        a = results[name][0]
        row = f"{name:<24s}"
        for sl in REGIONS.values():
            row += f"{np.abs(a[sl] - base[sl]).mean():>16.2f}"
        row += f"{np.abs(a - base).mean():>10.2f}"
        print(row)
    print("（分区 MAD：背景看纹理层；远山看排线层；主舟看毛边层）")

    print("\n纹理强度自检（左上应为纯背景，平涂 std 应≈0）:")
    for name in ("rich_A_flat.png", "rich_B_material.png", "rich_D_full.png"):
        patch = results[name][0][40:160, 40:260, 0]
        print(f"  {name:24s} 背景区 std = {patch.std():5.2f}")

    a = results["rich_D_full.png"][0]
    b = results["rich_E_full_boil1.png"][0]
    print(f"\n12fps 抖动（boil）换帧 MAD = {np.abs(a - b).mean():.2f}（>0 说明纸纹在跳）")

    y0, y1, x0, x1 = 560, 800, 980, 1420
    gap = np.full((y1 - y0, 12, 3), 255.0)
    for tag, key in (("rich_zoom_flat_vs_full.png", "rich_D_full.png"),):
        sheet = np.concatenate([base[y0:y1, x0:x1], gap, results[key][0][y0:y1, x0:x1]], axis=1)
        sha = write_png(sheet, os.path.join(OUT, tag))
        print(f"\n并排对照（左=平涂 右=全效果）{sheet.shape[1]}x{sheet.shape[0]}  sha256={sha[:16]}…")

    y0, y1, x0, x1 = 320, 460, 200, 560
    sheet = np.concatenate([base[y0:y1, x0:x1], gap[: y1 - y0], results["rich_D_full.png"][0][y0:y1, x0:x1]], axis=1)
    sha = write_png(sheet, os.path.join(OUT, "rich_zoom_mountain.png"))
    print(f"远山局部对照（左=平涂 右=全效果）{sheet.shape[1]}x{sheet.shape[0]}  sha256={sha[:16]}…")
    print(f"\n产物目录: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
