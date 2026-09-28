"""吴冠中风格「元素密度」对照探针（spike，不进引擎）。

背景（2026-09-28 第四轮反馈）：用户指出「界面元素太少了，留白过多，不要极简」。
复核确认这是**主因**——当前故事片全片只有 28 个叶节点、21 条线、5 个面、**2 个点**。
而吴冠中《狮子林》（1983）画面五分之四以上空间被假山石占据，
盘曲迂回的黑色墨线与飞扬激荡的彩色墨点构成点、线、面的交响；
《江南抹尽旧画图》（1987/1990）用「黑、白、灰的块面 + 飞扬的曲线 + 缤纷的色点」组织画面，
民居扭曲错落，大量柳枝上下左右飘拂。

本探针按吴冠中自述的构成法则重建一张**满构图**：
  「流水——长长的细曲线，小桥——大弧线，人家——黑与白的块面」
  「块面大小与曲线长短的对歌」
  「田埂迂回曲折，游动于坡上坡下，首尾呼应」
  「块面的大小、灰与白相抱合的气势、线与点的穿插、墨点之大小及其分布」

元素库（六类，全部落到四原语）：
  house_block   民居块面组：白墙(描边) + 黑瓦坡顶(实填重墨) + 窗，组间面积比 ≥3 拉开大小对比
  curve_run     长曲线束：田埂 / 水纹，多条迂回平行，相位递增形成「首尾呼应」
  stroke_bundle 短笔触群：柳枝，每束 14 条扇状飘拂
  big_arc       大弧线：拱桥
  dot_field     点阵：成团聚散、大小分布、高纯度色点
  lone_boat     孤舟（保留母题，作「风筝不断线」的具象锚点）

确定性：shalib 哈希派生（跨平台稳定），曲线用 core.dmath 的 dcos/dsin，不碰 libm。
产物：spike/out/wu_dense.png + 局部对照，并打印元素预算与着墨占比。
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import numpy as np
import skia

from spolvero.core.dmath import dcos, dsin
from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.types import Point
from spolvero.render.common import color_of
from spolvero.render.effects import EffectsRuntime, apply_haze, apply_material, apply_vignette

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "spike", "out")

W, H = 1600, 900

# ── 调色：黑白灰 + 缤纷色点 ──
PAPER = (242, 236, 223)       # 宣纸米黄
INK_BLACK = 0.08              # 黑瓦 / 近景重墨（ink 0=黑）
INK_GREY = 0.42
INK_LIGHT = 0.72
ACCENTS = ("#C0392B", "#E3A92B", "#2C6E8F", "#3F8A63", "#9B2D4F", "#D4691E")


def h01(*key) -> float:
    """确定性 [0,1) 哈希（sha256，跨平台一致，不碰 libm / 随机发生器）。"""
    s = "|".join(str(k) for k in key).encode("utf-8")
    return int.from_bytes(hashlib.sha256(s).digest()[:8], "big") / float(1 << 64)


def hr(lo: float, hi: float, *key) -> float:
    return lo + (hi - lo) * h01(*key)


def d2(p, a, b) -> float:
    dx, dy = a[0] - p[0], a[1] - p[1]
    return (dx * dx + dy * dy) ** 0.5


# ══════════════════ 0. 淡墨块面（远山 / 石丛，撑住上半留白）══════════════════
def mist_blocks(tag: str, n: int, y_lo: float, y_hi: float, w_lo: float, w_hi: float) -> list:
    """上半区的淡墨块：吴冠中画「石块 / 远山」用的是**成片的浅灰块面**，
    它们不吃深墨，却能把留白撑成「有物的空」——是「狮子林五分之四被占据」的真正来源。"""
    out = []
    for i in range(n):
        cx = hr(0.06, 0.94, tag, "cx", i) * W
        cy = hr(y_lo, y_hi, tag, "cy", i)
        ww = hr(w_lo, w_hi, tag, "w", i)
        wh = ww * hr(0.24, 0.55, tag, "ar", i)
        k = 10
        pts = []
        for m in range(k):
            s = m / k
            ang = s * 6.283185307179586
            rr = 0.5 + (h01(tag, "r", i, m) - 0.5) * 0.44
            pts.append(Point(cx + ww * 0.5 * rr * dcos(ang), cy + wh * 0.5 * rr * dsin(ang)))
        out.append(InkShape(ring=tuple(pts), ink=hr(0.62, 0.86, tag, "ink", i), fill=True, width=1.2))
    return out


# ══════════════════ 1. 民居块面组（黑白灰平面构架）══════════════════
def house_block(tag: str, cx: float, base: float, w: float, hh: float) -> list:
    """白墙 + 黑瓦坡顶 + 窗。四角带抖动（吴冠中的民居是扭曲错落的，非规则排列）。"""
    out = []
    j = lambda k, m=1.6: (h01(tag, "j", k) - 0.5) * m
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = base - hh, base
    # 白墙：只描边（留白即墙面），四角抖
    wall = [(x0 + j("a"), y0 + j("b")), (x1 + j("c"), y0 + j("d")),
            (x1 + j("e"), y1 + j("f")), (x0 + j("g"), y1 + j("h"))]
    out.append(InkShape(ring=tuple(Point(*p) for p in wall), ink=INK_LIGHT, fill=False, width=1.6))
    # 黑瓦坡顶：**厚重的墨块**（不是一条线）——吴冠中的「黑」全靠它撑面积
    ov = w * 0.10 + 10.0
    rise = hh * 0.46 + 20.0
    roof = [(x0 - ov, y0), (x0 - ov * 0.55, y0 - rise), (x1 + ov * 0.55, y0 - rise),
            (x1 + ov, y0), (x1, y0 + rise * 0.22), (x0, y0 + rise * 0.22)]
    out.append(InkShape(ring=tuple(Point(*p) for p in roof), ink=INK_BLACK, fill=True, width=2.0))
    # 窗：大小不等的墨块，位置错落
    n = 2 + int(h01(tag, "wn") * 3)
    for k in range(n):
        ww = hr(10.0, 26.0, tag, "ww", k)
        wh = hr(12.0, 30.0, tag, "wh", k)
        px = hr(x0 + 6.0, x1 - 6.0 - ww, tag, "px", k)
        py = hr(y0 + 8.0, y1 - 8.0 - wh, tag, "py", k)
        out.append(InkShape(
            ring=(Point(px, py), Point(px + ww, py), Point(px + ww, py + wh), Point(px, py + wh)),
            ink=0.14, fill=True, width=1.0,
        ))
    return out


# ══════════════════ 2. 长曲线束（田埂 / 水纹）══════════════════
def curve_run(tag: str, n: int, y_lo: float, y_hi: float, amp_lo: float, amp_hi: float) -> list:
    """多条迂回平行曲线，相位递增 → 「游动于坡上坡下，首尾呼应」。"""
    out = []
    for i in range(n):
        u = i / max(n - 1, 1)
        base = y_lo + (y_hi - y_lo) * u
        amp = hr(amp_lo, amp_hi, tag, "amp", i)
        ph = u * 3.6 + hr(-0.5, 0.5, tag, "ph", i)
        k = hr(0.8, 1.9, tag, "k", i)      # 波数：长短不一
        pts = []
        for m in range(16):
            s = m / 15.0
            x = -70.0 + s * (W + 140.0)
            y = base + amp * dsin(6.283185307179586 * (k * s + ph))
            y += (h01(tag, "jy", i, m) - 0.5) * 3.0
            pts.append(Point(x, y))
        out.append(InkLine(
            points=tuple(pts),
            width=hr(1.0, 2.2, tag, "w", i),
            ink=hr(0.48, 0.74, tag, "ink", i),
        ))
    return out


# ══════════════════ 3. 短笔触群（柳枝）══════════════════
def stroke_bundle(tag: str, x0: float, y0: float, n: int, spread: float, length: float) -> list:
    """扇状飘拂的短曲线：根部聚拢、梢部分散（吴冠中画柳枝的办法）。"""
    out = []
    for i in range(n):
        u = i / max(n - 1, 1) - 0.5
        ang = u * spread * 3.141592653589793 / 180.0
        L = hr(0.45, 1.0, tag, "L", i) * length
        curl = hr(-0.55, 0.55, tag, "curl", i)
        pts = []
        for m in range(8):
            s = m / 7.0
            # 沿角方向走，另叠加一个横向的正弦卷曲 → 柳枝的飘
            lateral = curl * L * 0.30 * dsin(3.141592653589793 * s)
            px = x0 + (dcos(ang) * s - dsin(ang) * 0.0) * L * 0.42 + lateral * dcos(ang + 1.5707963)
            py = y0 + (dsin(ang) * s) * L + lateral * dsin(ang + 1.5707963)
            pts.append(Point(px, py))
        out.append(InkLine(
            points=tuple(pts), width=hr(0.9, 1.7, tag, "w", i),
            ink=hr(0.18, 0.52, tag, "ink", i),
        ))
    return out


# ══════════════════ 4. 大弧线（拱桥）══════════════════
def big_arc(tag: str, cx: float, cy: float, span: float, rise: float) -> list:
    top, deck, legs = [], [], []
    pts = []
    for m in range(15):
        s = m / 14.0
        x = cx - span / 2 + s * span
        y = cy - rise * dsin(3.141592653589793 * s)
        pts.append(Point(x, y))
    top.append(InkLine(points=tuple(pts), width=3.4, ink=0.24))
    deck.append(InkLine(points=(Point(cx - span / 2 - 14, cy - rise * 0.94),
                                Point(cx + span / 2 + 14, cy - rise * 0.94)), width=2.6, ink=0.20))
    for sx in (-0.34, 0.34):
        legs.append(InkLine(points=(Point(cx + span * sx, cy - rise * 0.55),
                                    Point(cx + span * sx, cy + rise * 0.42)), width=2.2, ink=0.22))
    return top + deck + legs


# ══════════════════ 5. 点阵（缤纷色点，疏密成团）══════════════════
def dot_field(tag: str, n: int, clusters) -> list:
    """点「疏密有致、聚散无常」，穿插于块面与线条之间（吴冠中语）。"""
    out = []
    for i in range(n):
        ci = i % len(clusters)
        cx, cy = clusters[ci]
        u = h01(tag, "du", i)
        v = h01(tag, "dv", i)
        r = 300.0 * (u ** 1.7)          # 越靠团心越密
        ang = v * 6.283185307179586
        px = cx + r * dcos(ang)
        py = cy + r * dsin(ang) * 0.52
        if not (14.0 < px < W - 14.0 and 14.0 < py < H - 40.0):
            continue
        rr = hr(2.0, 7.0, tag, "dr", i)
        big = h01(tag, "big", i) > 0.94
        if big:
            rr = hr(7.5, 12.0, tag, "drb", i)
        col = None if h01(tag, "cx", i) < 0.44 else ACCENTS[int(h01(tag, "ca", i) * len(ACCENTS)) % len(ACCENTS)]
        out.append(InkDot(pos=Point(px, py), r=rr, ink=hr(0.08, 0.34, tag, "di", i), color=col))
    return out


# ══════════════════ 6. 孤舟（母题锚点）══════════════════
def lone_boat(tag: str, cx: float, cy: float, sc: float) -> list:
    hull = [(cx - 62 * sc, cy), (cx + 62 * sc, cy - 2 * sc),
            (cx + 48 * sc, cy + 13 * sc), (cx - 50 * sc, cy + 12 * sc)]
    out = [
        InkShape(ring=tuple(Point(*p) for p in hull), ink=0.16, fill=True, width=2.0),
        InkLine(points=(Point(cx - 6 * sc, cy + 1 * sc), Point(cx - 6 * sc, cy - 46 * sc),
                        Point(cx + 14 * sc, cy - 40 * sc)), width=1.8, ink=0.22),
        InkDot(pos=Point(cx - 62 * sc, cy - 2 * sc), r=3.6 * sc, ink=0.30, color="#C0392B"),
    ]
    return out


# ══════════════════ 组场景 ══════════════════
def build_scene() -> list:
    nodes = []
    # 远山/石丛：把上半的留白撑成「有物的空」（8 片淡墨块）
    nodes += mist_blocks("mst", 8, 150.0, 470.0, 210.0, 520.0)
    # 上半：江南民居群，**面积比 ≥4** 拉开大小对比
    nodes += house_block("hA", 330.0, 516.0, 392.0, 208.0)
    nodes += house_block("hB", 852.0, 530.0, 176.0, 116.0)
    nodes += house_block("hC", 1168.0, 488.0, 92.0, 72.0)
    nodes += house_block("hD", 1300.0, 512.0, 54.0, 46.0)
    # 远岸横长线（平面分割）
    nodes.append(InkLine(points=(Point(-40, 558), Point(W + 40, 553)), width=3.0, ink=0.44))
    # 柳枝：三束
    nodes += stroke_bundle("w1", 296.0, 336.0, 18, 158.0, 176.0)
    nodes += stroke_bundle("w2", 1086.0, 392.0, 15, 138.0, 140.0)
    nodes += stroke_bundle("w3", 780.0, 442.0, 12, 120.0, 104.0)
    # 下半：田埂 / 水纹，34 条迂回平行（间距 ≈9px，线与线之间才形成「面」）
    nodes += curve_run("tian", 34, 572.0, 878.0, 5.0, 15.0)
    # 拱桥 + 孤舟
    nodes += big_arc("br", 690.0, 700.0, 250.0, 62.0)
    nodes += lone_boat("bt", 1046.0, 708.0, 1.3)
    # 点阵：520 点，5 个团心
    nodes += dot_field("dots", 520, [(330.0, 452.0), (900.0, 566.0), (1246.0, 424.0),
                                     (620.0, 792.0), (1420.0, 660.0)])
    return nodes


# ══════════════════ 渲染 ══════════════════
def render(nodes, *, fx_on: bool):
    from spolvero.core.scene import flatten_all

    leaves = flatten_all(nodes)
    surface = skia.Surface(W, H)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorSetARGB(255, *PAPER))

    stroke = skia.Paint(); stroke.setAntiAlias(True)
    stroke.setStyle(skia.Paint.kStroke_Style)
    stroke.setStrokeJoin(skia.Paint.kRound_Join); stroke.setStrokeCap(skia.Paint.kRound_Cap)
    fillp = skia.Paint(); fillp.setAntiAlias(True); fillp.setStyle(skia.Paint.kFill_Style)

    fx = EffectsRuntime(
        material=0.95, ramp=0.62, hatch=0.88, glow=0.0,
        vignette=0.10, haze=0.20, border=False, paper_rgb=PAPER, grain_seed=4821,
    ) if fx_on else None

    n_hatch = 0
    for leaf in leaves:
        r, g, b = color_of(leaf.ink, leaf.color)
        col = skia.ColorSetARGB(255, r, g, b)
        if isinstance(leaf, InkDot):
            fillp.setColor(col)
            canvas.drawCircle(leaf.pos.x, leaf.pos.y, leaf.r, fillp)
            continue
        is_shape = isinstance(leaf, InkShape)
        pts = leaf.ring if is_shape else leaf.points
        if len(pts) < 2:
            continue
        path = skia.Path(); path.moveTo(pts[0].x, pts[0].y)
        for p in pts[1:]:
            path.lineTo(p.x, p.y)
        if is_shape or leaf.closed:
            path.close()
        if is_shape and leaf.fill:
            fillp.setColor(col); canvas.drawPath(path, fillp)
            if fx is not None:
                if fx.ramp > 0:
                    from spolvero.render.skia import _draw_ramp
                    _draw_ramp(canvas, path, pts, (r, g, b), PAPER, fx.ramp)
                if fx.hatch > 0:
                    from spolvero.render.skia import _draw_hatch
                    n_hatch += _draw_hatch(canvas, [(p.x, p.y) for p in pts], (r, g, b), fx.hatch)
        else:
            stroke.setColor(col); stroke.setStrokeWidth(leaf.width); canvas.drawPath(path, stroke)

    img = surface.makeImageSnapshot()
    arr = img.toarray()[:, :, [2, 1, 0]].astype(np.float64)
    if fx is not None:
        arr = apply_haze(arr, PAPER, fx.haze)
        arr = apply_material(arr, fx.grain_seed, fx.material)
        arr = apply_vignette(arr, fx.vignette)
    return np.clip(arr, 0, 255), n_hatch


def write_png(arr, path) -> str:
    a = np.ascontiguousarray(arr.astype(np.uint8))
    rgba = np.empty((a.shape[0], a.shape[1], 4), dtype=np.uint8)
    rgba[:, :, 0] = a[:, :, 2]; rgba[:, :, 1] = a[:, :, 1]
    rgba[:, :, 2] = a[:, :, 0]; rgba[:, :, 3] = 255
    img = skia.Image.fromarray(rgba, skia.kBGRA_8888_ColorType, alphaType=skia.kOpaque_AlphaType)
    data = bytes(img.encodeToData())
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    nodes = build_scene()
    from spolvero.core.scene import flatten_all
    from spolvero.core.primitives import InkDot as D

    leaves = flatten_all(nodes)
    n_line = sum(1 for x in leaves if isinstance(x, InkLine))
    n_shape = sum(1 for x in leaves if isinstance(x, InkShape))
    n_dot = sum(1 for x in leaves if isinstance(x, D))
    verts = sum(len(x.points) for x in leaves if isinstance(x, InkLine)) + \
        sum(len(x.ring) for x in leaves if isinstance(x, InkShape))
    color_dots = sum(1 for x in leaves if isinstance(x, D) and x.color)
    print(f"元素预算  叶节点={len(leaves)}  线={n_line}  面={n_shape}  点={n_dot}(彩色 {color_dots})  顶点={verts}")
    print(f"对比旧片  叶节点=28  线=21  面=5  点=2  顶点=275")

    arr_on, nh = render(nodes, fx_on=True)
    arr_off, _ = render(nodes, fx_on=False)
    p1 = os.path.join(OUT, "wu_dense.png")
    p2 = os.path.join(OUT, "wu_dense_flat.png")
    s1 = write_png(arr_on, p1)
    s2 = write_png(arr_off, p2)
    print(f"  wu_dense.png      hatch线={nh}  sha256={s1[:16]}…")
    print(f"  wu_dense_flat.png sha256={s2[:16]}…")

    lum = arr_on[:, :, 0]
    dark = float((lum < 90).mean() * 100)
    mid = float(((lum >= 90) & (lum < 190)).mean() * 100)
    light = float((lum >= 190).mean() * 100)
    print(f"明度结构  深(<=90) {dark:5.2f}%   中(90-190) {mid:5.2f}%   浅(>190) {light:5.2f}%")
    print(f"明度 min/max/mean/std = {int(lum.min())}/{int(lum.max())}/{lum.mean():.1f}/{lum.std():.1f}")

    # ── 「满不满」的真正度量：局部窗口的有笔率 ──
    # 必须在**平涂帧**上量：纸纹层本身每像素就有 ±20 的扰动，会把「有笔」判满全幅。
    bs = 64

    def busy(arr):
        ink = (np.abs(np.asarray(arr) - np.array(PAPER)).sum(axis=2) > 80).astype(np.float64)
        hh, ww = (H // bs) * bs, (W // bs) * bs
        return ink[:hh, :ww].reshape(hh // bs, bs, ww // bs, bs).mean(axis=(1, 3))

    def report(tag, arr):
        blk = busy(arr)
        empty = float((blk < 0.02).mean()) * 100
        print(f"  {tag:22s} 平均 {blk.mean() * 100:5.2f}%  中位 {np.median(blk) * 100:5.2f}%  "
              f">30%窗口 {float((blk > 0.30).mean()) * 100:5.1f}%  纯空白窗口 {empty:5.1f}%")

    print(f"局部有笔率（平涂帧，64px 窗口 {14}×{25}=350 个）")
    report("吴冠中探针（本图）", arr_off)
    # 基线：改前的故事片（关掉质感层，同口径）
    try:
        from spolvero.api import get_style, load_project, _styled_groups
        from spolvero.render.backend import render as _r
        from spolvero.render.skia import png_to_rgb

        old = load_project(os.path.join(ROOT, "projects", "lonely_boat_story"))
        st = get_style("azurite")
        png = _r(_styled_groups(old, st, 7.0), "skia", W, H, st.paper_rgb)
        a = np.frombuffer(png_to_rgb(png), dtype=np.uint8).reshape(H, W, 3).astype(np.float64)
        # 旧片纸色不同，换算到同一口径：先按旧纸色判「有无笔」，再重标为 PAPER 明度差
        dev = np.abs(a - np.array(st.paper_rgb)).sum(axis=2)
        ink = (dev > 80).astype(np.float64)[:(H // bs) * bs, :(W // bs) * bs]
        blk = ink.reshape((H // bs), bs, (W // bs), bs).mean(axis=(1, 3))
        print(f"  {'旧片（故事片 t=7）':22s} 平均 {blk.mean() * 100:5.2f}%  中位 {np.median(blk) * 100:5.2f}%  "
              f">30%窗口 {float((blk > 0.30).mean()) * 100:5.1f}%  纯空白窗口 {float((blk < 0.02).mean()) * 100:5.1f}%")
    except Exception as e:  # 分支仅为对照，失败不阻断
        print(f"  （旧片基线测量失败：{e}）")

    print(f"纸纹：质感版左上区 std={np.asarray(arr_on)[60:200, 380:600, 0].std():.2f}")

    # 局部并排（民居 / 水面田埂与舟），供人工判读细节
    for tag, (y0, y1, x0, x1) in {
        "wu_zoom_houses.png": (280, 570, 170, 700),
        "wu_zoom_water.png": (600, 880, 380, 1180),
    }.items():
        gap = np.full((y1 - y0, 14, 3), 255.0)
        sheet = np.concatenate([np.asarray(arr_off)[y0:y1, x0:x1], gap,
                                np.asarray(arr_on)[y0:y1, x0:x1]], axis=1)
        sha = write_png(sheet, os.path.join(OUT, tag))
        print(f"  {tag:22s} {sheet.shape[1]}x{sheet.shape[0]}  sha256={sha[:16]}…")
    print(f"产物目录 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
