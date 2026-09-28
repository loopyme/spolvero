"""吴冠中风格 v2：毛笔笔画化（粗细变化 / 轻微弯曲 / 抖动 / 局部断裂）+ 明度分层 + 节奏化点阵。

v1 的问题（用户 2026-09-28 反馈）：
  1. 线是等宽描边 → 机器味，不像毛笔速写
  2. 散点太多（505 个）→ 是噪音不是节奏
  3. 水纹横线等距等宽 → 呆板
  4. 黑白灰层级不清（浅区 81%，中灰只有 10%）
  5. 现代感与诗意不足

v2 的解法：
  · 线 → **填充式变宽笔画**（一条折线 → 1–4 个填充多边形）
      提按：两端细中间粗，w(u) = w_max·((1−t) + t·sin(πu))
      弯曲：低频正弦横向扰动（纯 dsin，不碰 libm）
      抖动：逐点整数哈希微扰
      断裂：按弧长分数切开 1–3 处，裂缝 2.5–7px（55% 的笔画才断，不是全都断）
  · 明度：五档显式色值（black/deep/mid/light/faint），中灰靠**成片块面**撑起来，不再靠线堆积
  · 点：505 → 约 110，且**沿结构布置**（贴水纹／屋脊／柳梢成串），彩色只做重音
  · 水纹：疏密有梯度（靠地平线密）、粗细 0.9–3.0、每条断成 1–4 段

确定性：一切随机来自 sha256 哈希；几何只用 +−×÷ 与 core.dmath 的 dcos/dsin。
"""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import numpy as np
import skia

from spolvero.core.dmath import dcos, dsin
from spolvero.core.primitives import InkDot, InkShape
from spolvero.core.types import Point
from spolvero.render.common import color_of
from spolvero.render.effects import EffectsRuntime, apply_haze, apply_material, apply_vignette

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "spike", "out")
W, H = 1600, 900

# ── 五档明度（黑白灰层级，显式色值，不靠 ink 映射猜）──
PAPER = "#F4EFE6"
TONES = {
    "black": "#1B1D1E",   #  29 墨块：瓦顶 / 窗 / 舟 / 桥
    "deep":  "#3B3F42",   #  62 深灰：柳枝 / 近景重笔
    "mid":   "#6E7070",   # 112 中深灰：石丛（压在主灰带下缘，做前景）
    "light": "#9C9A93",   # 155 中灰：远山主块面（画面的体量所在）
    "faint": "#C6C1B6",   # 194 极浅：雾中最远的山
}
PAPER_RGB = (244, 239, 230)
ACCENTS = ("#C8442E", "#C8442E", "#C8442E", "#2A6C8F", "#3E8A6A", "#E0A62B", "#A32B4E")
PI = 3.141592653589793


def h01(*key) -> float:
    s = "|".join(str(k) for k in key).encode("utf-8")
    return int.from_bytes(hashlib.sha256(s).digest()[:8], "big") / float(1 << 64)


def hr(lo: float, hi: float, *key) -> float:
    return lo + (hi - lo) * h01(*key)


# ══════════════════ 笔画内核：折线 → 变宽填充笔画（含断裂）══════════════════
def _densify(pts, step: float):
    out = [pts[0]]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        n = max(1, int(d // step))
        for k in range(1, n + 1):
            u = k / n
            out.append((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u))
    return out


def _wobble(pts, amp: float, freq: float, tag: str):
    """低频正弦 = 轻微弯曲；逐点哈希 = 抖动。amp 需 ≤ 0.35×点距，否则轮廓会自交。"""
    n = len(pts)
    ph = h01(tag, "ph")
    out = []
    for i, (x, y) in enumerate(pts):
        s = i / max(n - 1, 1)
        if i == 0:
            dx, dy = pts[1][0] - x, pts[1][1] - y
        elif i == n - 1:
            dx, dy = x - pts[-2][0], y - pts[-2][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        L = ((dx * dx + dy * dy) ** 0.5) or 1.0
        nx, ny = -dy / L, dx / L
        w = amp * dsin(2 * PI * (freq * s + ph)) + amp * 0.55 * (h01(tag, "j", i) - 0.5)
        out.append((x + nx * w, y + ny * w))
    return out


def _arc(pts):
    cum = [0.0]
    for i in range(1, len(pts)):
        dx, dy = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        cum.append(cum[-1] + (dx * dx + dy * dy) ** 0.5)
    return cum


def _slice_at(pts, cum, total, s: float):
    t = s * total
    for i in range(1, len(cum)):
        if cum[i] >= t:
            a, b = pts[i - 1], pts[i]
            seg = cum[i] - cum[i - 1]
            u = (t - cum[i - 1]) / seg if seg > 0 else 0.0
            return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u), i
    return pts[-1], len(pts)


def _tapered_outline(sub, w_max: float, taper: float, tag: str, tone: str):
    """一条笔画：沿法线按 w(u) 向两侧外扩 → 闭合轮廓（毛笔的真实形态是填充，不是描线）。"""
    m = len(sub)
    if m < 2:
        return None
    left, right = [], []
    for i, (x, y) in enumerate(sub):
        u = i / (m - 1)
        w = w_max * ((1.0 - taper) + taper * dsin(PI * u))
        w *= 0.82 + 0.36 * h01(tag, "wj", i)
        if i == 0:
            dx, dy = sub[1][0] - x, sub[1][1] - y
        elif i == m - 1:
            dx, dy = x - sub[-2][0], y - sub[-2][1]
        else:
            dx, dy = sub[i + 1][0] - sub[i - 1][0], sub[i + 1][1] - sub[i - 1][1]
        L = ((dx * dx + dy * dy) ** 0.5) or 1.0
        nx, ny = -dy / L, dx / L
        left.append((x + nx * w * 0.5, y + ny * w * 0.5))
        right.append((x - nx * w * 0.5, y - ny * w * 0.5))
    ring = left + right[::-1]
    if len(ring) < 3:
        return None
    return InkShape(ring=tuple(Point(*q) for q in ring), color=TONES[tone], fill=True, width=1.0)


def brush(pts, w_max, tone, tag, amp=1.6, freq=1.3, step=9.0, taper=0.5,
          break_p=0.55, max_gap=3):
    """折线 → 一组毛笔笔画（填充多边形）。返回 (shapes, 断裂数, 宽度范围)。"""
    p = _wobble(_densify(pts, step), amp, freq, tag)
    if len(p) < 3:
        return [], 0, (0.0, 0.0)
    cum = _arc(p)
    total = cum[-1]
    if total < 5.0:
        return [], 0, (0.0, 0.0)

    n_gap = 0
    if h01(tag, "bok") < break_p:
        n_gap = 1 + int(h01(tag, "ngap") * max_gap)
    spans = []
    if n_gap == 0:
        spans = [(0.0, 1.0)]
    else:
        cs = sorted(hr(0.14, 0.88, tag, "cut", k) for k in range(n_gap))
        gw = [hr(0.010, 0.032, tag, "gw", k) for k in range(n_gap)]
        s = 0.0
        for k in range(n_gap):
            spans.append((s, max(s, cs[k] - gw[k] * 0.5)))
            s = min(1.0, cs[k] + gw[k] * 0.5)
        spans.append((s, 1.0))

    shapes, n_break = [], 0
    w_lo, w_hi = 9e9, 0.0
    for k, (s0, s1) in enumerate(spans):
        if s1 - s0 < 0.012:
            continue
        q0, i0 = _slice_at(p, cum, total, s0)
        q1, i1 = _slice_at(p, cum, total, s1)
        sub = [q0] + p[i0:i1] + [q1]
        sh = _tapered_outline(sub, w_max, taper, f"{tag}s{k}", tone)
        if sh is None:
            continue
        shapes.append(sh)
        n_break += 1
        w_lo = min(w_lo, w_max * (1.0 - taper))
        w_hi = max(w_hi, w_max)
    return shapes, max(0, len(shapes) - 1), (0.0 if not shapes else w_lo, w_hi)


# ══════════════════ 水纹横线：粗细 / 断续 / 疏密 ══════════════════
def water_lines(tag, n, y0, y1):
    shapes, breaks, anchor, widths = [], 0, [], []
    for i in range(n):
        u = i / max(n - 1, 1)
        y = y0 + (y1 - y0) * (u ** 1.42)          # 靠地平线更密（疏密梯度）
        amp = hr(1.6, 5.2, tag, "a", i)
        k = hr(0.6, 1.6, tag, "k", i)
        ph = hr(-0.6, 0.6, tag, "p", i)
        pts = []
        for m in range(15):
            s = m / 14.0
            x = -70.0 + s * (W + 140.0)
            pts.append((x, y + amp * dsin(2 * PI * (k * s + ph))))
        wd = hr(0.9, 3.0, tag, "w", i)
        tone = "deep" if h01(tag, "t", i) < 0.42 else "mid"
        sh, nb, (lo, hi) = brush(pts, wd, tone, f"wl{i}", amp=0.0, freq=0.0,
                                 step=11.0, taper=0.6, break_p=0.72, max_gap=4)
        shapes += sh
        breaks += nb
        widths.append((lo, hi))
        anchor.append((y, wd))
    return shapes, breaks, anchor, widths


# ══════════════════ 柳枝：短笔触群（细 / 大弯 / 多断裂）══════════════════
def willow(tag, x0, y0, n, spread, length):
    shapes, breaks = [], 0
    for i in range(n):
        u = i / max(n - 1, 1) - 0.5
        ang = u * spread * PI / 180.0
        L = hr(0.35, 1.0, tag, "L", i) * length
        curl = hr(-0.85, 0.85, tag, "c", i)
        pts = []
        for m in range(7):
            s = m / 6.0
            bend = curl * L * 0.42 * dsin(PI * s)
            px = x0 + dcos(ang) * L * 0.45 * s + bend * dcos(ang + PI / 2)
            py = y0 + dsin(ang) * L * 0.75 * s + bend * dsin(ang + PI / 2) + L * 0.30 * s * s
            pts.append((px, py))
        sh, nb, _ = brush(pts, hr(1.0, 2.4, tag, "w", i), "deep", f"bw{i}",
                          amp=1.0, freq=1.1, step=8.0, taper=0.62, break_p=0.62, max_gap=2)
        shapes += sh
        breaks += nb
    return shapes, breaks


# ══════════════════ 民居：黑白灰平面构架 ══════════════════
def house_block(tag, cx, base, w, hh):
    out = []
    j = lambda k, m=1.8: (h01(tag, "j", k) - 0.5) * m
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = base - hh, base
    wall = [(x0 + j("a"), y0 + j("b")), (x1 + j("c"), y0 + j("d")),
            (x1 + j("e"), y1 + j("f")), (x0 + j("g"), y1 + j("h"))]
    out.append(InkShape(ring=tuple(Point(*p) for p in wall), color=TONES["light"],
                        fill=False, width=1.5))
    ov = w * 0.10 + 10.0
    rise = hh * 0.44 + 20.0
    roof = [(x0 - ov, y0), (x0 - ov * 0.55, y0 - rise), (x1 + ov * 0.55, y0 - rise),
            (x1 + ov, y0), (x1, y0 + rise * 0.20), (x0, y0 + rise * 0.20)]
    out.append(InkShape(ring=tuple(Point(*p) for p in roof), color=TONES["black"],
                        fill=True, width=2.0))
    for k in range(2 + int(h01(tag, "wn") * 3)):
        ww = hr(10.0, 26.0, tag, "ww", k)
        wh = hr(12.0, 30.0, tag, "wh", k)
        px = hr(x0 + 6.0, x1 - 6.0 - ww, tag, "px", k)
        py = hr(y0 + 8.0, y1 - 8.0 - wh, tag, "py", k)
        out.append(InkShape(ring=(Point(px, py), Point(px + ww, py),
                                  Point(px + ww, py + wh), Point(px, py + wh)),
                            color=TONES["black"], fill=True, width=1.0))
    return out, (x0 - ov, x1 + ov, y0 - rise, y1)


# ══════════════════ 块面：几何化的远山 / 石丛（现代感来自边的简洁）══════════════════
def plane_block(tag, cx, cy, w, h, tone, sides=6):
    """几何化的块面：边数少、边直，现代感来自此。
    rr 以 w/2 为半轴（勿写成 w*0.5*rr 后再乘 0.5——那会把面积缩到 1/4）。"""
    pts = []
    for m in range(sides):
        a = (m / sides + 0.5 / sides) * 2 * PI
        rr = 1.0 + (h01(tag, "r", m) - 0.5) * 0.42
        pts.append(Point(cx + w * 0.5 * rr * dcos(a), cy + h * 0.5 * rr * dsin(a)))
    return InkShape(ring=tuple(pts), color=TONES[tone], fill=True, width=1.0)


# ══════════════════ 拱桥 / 孤舟 ══════════════════
def bridge(tag, cx, cy, span, rise):
    shapes, breaks = [], 0
    pts = [(cx - span / 2 + (m / 14.0) * span, cy - rise * dsin(PI * (m / 14.0))) for m in range(15)]
    sh, nb, _ = brush(pts, 4.2, "black", "brg", amp=0.5, freq=0.8, step=9.0,
                      taper=0.4, break_p=0.0)
    shapes += sh
    deck, nb2, _ = brush([(cx - span / 2 - 16, cy - rise * 0.9), (cx + span / 2 + 16, cy - rise * 0.9)],
                         3.0, "deep", "brgd", amp=0.6, freq=1.0, step=12.0, taper=0.3, break_p=0.0)
    shapes += deck
    for k, sx in enumerate((-0.32, 0.32)):
        leg, nb3, _ = brush([(cx + span * sx, cy - rise * 0.55), (cx + span * sx, cy + rise * 0.42)],
                            2.6, "deep", f"brgl{k}", amp=0.5, freq=1.0, step=10.0,
                            taper=0.35, break_p=0.0)
        shapes += leg
    return shapes


def lone_boat(tag, cx, cy, sc):
    hull = [(cx - 62 * sc, cy), (cx + 62 * sc, cy - 2 * sc),
            (cx + 48 * sc, cy + 13 * sc), (cx - 50 * sc, cy + 12 * sc)]
    out = [InkShape(ring=tuple(Point(*p) for p in hull), color=TONES["black"], fill=True, width=2.0)]
    sh, _, _ = brush([(cx - 6 * sc, cy + 1 * sc), (cx - 6 * sc, cy - 46 * sc),
                      (cx + 15 * sc, cy - 40 * sc)], 2.4, "deep", "btm",
                     amp=0.8, freq=1.2, step=9.0, taper=0.45, break_p=0.55)
    out += sh
    out.append(InkDot(pos=Point(cx - 62 * sc, cy - 2 * sc), r=4.2 * sc, color="#C8442E"))
    return out


# ══════════════════ 点：沿结构布置的节奏重音（不是均匀撒点）══════════════════
def dot_rhythm(tag, water_anchor, houses, willows):
    out = []
    ci = 0
    # 1) 贴水纹：每条线取 0–2 个点，取该线实际波峰处
    for i, (y, wd) in enumerate(water_anchor):
        if h01(tag, "wn", i) > 0.42:
            continue
        for k in range(1 + int(h01(tag, "wk", i) * 3)):
            x = hr(60.0, W - 60.0, tag, "wx", i, k)
            acc = h01(tag, "wa", i, k) < 0.34
            out.append(InkDot(
                pos=Point(x, y + hr(-4.0, 4.0, tag, "wy", i, k)),
                r=hr(1.6, 3.6, tag, "wr", i, k),
                color=ACCENTS[ci % len(ACCENTS)] if acc else TONES["deep"],
            ))
            ci += 1 if acc else 0
    # 2) 贴屋脊成串（3–5 个一簇 = 节奏）
    for hi, (bx0, bx1, by0, _by1) in enumerate(houses):
        n = 4 + int(h01(tag, "hn", hi) * 3)
        for k in range(n):
            acc = h01(tag, "ha", hi, k) < 0.40
            out.append(InkDot(
                pos=Point(hr(bx0 + 8, bx1 - 8, tag, "hx", hi, k), by0 + hr(-3.0, 5.0, tag, "hy", hi, k)),
                r=hr(2.0, 4.4, tag, "hr", hi, k),
                color=ACCENTS[ci % len(ACCENTS)] if acc else TONES["black"],
            ))
            ci += 1 if acc else 0
    # 3) 柳梢：散而小
    for wi, (x0, y0) in enumerate(willows):
        for k in range(4 + int(h01(tag, "ls", wi) * 4)):
            acc = h01(tag, "la", wi, k) < 0.30
            out.append(InkDot(
                pos=Point(x0 + hr(-70.0, 70.0, tag, "lx", wi, k), y0 + hr(-40.0, 70.0, tag, "ly", wi, k)),
                r=hr(1.4, 2.8, tag, "lr", wi, k),
                color=ACCENTS[ci % len(ACCENTS)] if acc else TONES["deep"],
            ))
            ci += 1 if acc else 0
    # 4) 3 个大色点 = 全曲重音
    for k, (x, y, r) in enumerate(((1226.0, 452.0, 9.0), (352.0, 566.0, 7.5), (958.0, 796.0, 8.0))):
        out.append(InkDot(pos=Point(x, y), r=r, color="#C8442E"))
    return out


# ══════════════════ 组场景 ══════════════════
def build_scene():
    nodes = []
    # 远山 / 石丛：分层块面，**远→近＝浅→深**。
    # 不用一整片大灰斑——吴冠中的体量是几片几何块面**叠出来**的，
    # 这样既有中灰的厚度，又保住白的呼吸和几何边的现代感。
    nodes.append(plane_block("f0", 900.0, 236.0, 1500.0, 236.0, "faint", 6))   # 最远：雾中山
    nodes.append(plane_block("l0", 520.0, 302.0, 900.0, 260.0, "light", 7))    # 主灰带
    nodes.append(plane_block("l1", 1180.0, 288.0, 760.0, 228.0, "light", 6))
    nodes.append(plane_block("l2", 862.0, 388.0, 620.0, 168.0, "light", 7))
    nodes.append(plane_block("m0", 402.0, 436.0, 420.0, 140.0, "mid", 5))      # 石丛（前景）
    nodes.append(plane_block("m1", 1236.0, 430.0, 340.0, 120.0, "mid", 5))
    nodes.append(plane_block("m2", 700.0, 470.0, 280.0, 90.0, "mid", 5))
    # 民居四组，面积比拉到 4 倍以上
    houses = []
    for tag, cx, base, w, hh in (("hA", 330.0, 516.0, 392.0, 208.0),
                                 ("hB", 852.0, 530.0, 176.0, 116.0),
                                 ("hC", 1168.0, 488.0, 92.0, 72.0),
                                 ("hD", 1300.0, 512.0, 54.0, 46.0)):
        blk, box = house_block(tag, cx, base, w, hh)
        nodes += blk
        houses.append(box)
    # 远岸横线（平面分割）
    shore, _, _ = brush([(-40.0, 558.0), (W + 40.0, 553.0)], 3.4, "deep", "shore",
                        amp=1.2, freq=1.0, step=13.0, taper=0.32, break_p=0.35, max_gap=2)
    nodes += shore
    # 柳枝三束
    willows = ((292.0, 332.0), (1086.0, 386.0), (782.0, 438.0))
    for wi, (x0, y0) in enumerate(willows):
        wsh, _ = willow(f"w{wi}", x0, y0, 13, 150.0, 170.0)
        nodes += wsh
    # 水纹 26 条
    wshapes, wbreaks, anchor, wwidths = water_lines("wl", 26, 572.0, 878.0)
    nodes += wshapes
    # 桥 / 舟
    nodes += bridge("br", 690.0, 700.0, 250.0, 62.0)
    nodes += lone_boat("bt", 1046.0, 708.0, 1.3)
    # 点阵（节奏化）
    nodes += dot_rhythm("dt", anchor, houses, willows)
    return nodes, wbreaks, wwidths


# ══════════════════ 渲染 ══════════════════
def render(nodes, fx_on: bool):
    from spolvero.core.scene import flatten_all

    leaves = flatten_all(nodes)
    surface = skia.Surface(W, H)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorSetARGB(255, *PAPER_RGB))
    stroke = skia.Paint(); stroke.setAntiAlias(True)
    stroke.setStyle(skia.Paint.kStroke_Style)
    stroke.setStrokeJoin(skia.Paint.kRound_Join); stroke.setStrokeCap(skia.Paint.kRound_Cap)
    fillp = skia.Paint(); fillp.setAntiAlias(True); fillp.setStyle(skia.Paint.kFill_Style)
    fx = EffectsRuntime(material=0.90, ramp=0.34, hatch=0.58, glow=0.0,
                        vignette=0.09, haze=0.16, border=False,
                        paper_rgb=PAPER_RGB, grain_seed=4821) if fx_on else None
    n_hatch = 0
    for leaf in leaves:
        r, g, b = color_of(leaf.ink, leaf.color)
        col = skia.ColorSetARGB(255, r, g, b)
        if isinstance(leaf, InkDot):
            fillp.setColor(col)
            canvas.drawCircle(leaf.pos.x, leaf.pos.y, leaf.r, fillp)
            continue
        pts = leaf.ring
        path = skia.Path(); path.moveTo(pts[0].x, pts[0].y)
        for p in pts[1:]:
            path.lineTo(p.x, p.y)
        path.close()
        if leaf.fill:
            fillp.setColor(col); canvas.drawPath(path, fillp)
            if fx is not None and _area(pts) >= 3000.0:
                # 大块面才排线：笔画本身已经够细，再排线会糊
                if fx.ramp > 0:
                    from spolvero.render.skia import _draw_ramp
                    _draw_ramp(canvas, path, pts, (r, g, b), PAPER_RGB, fx.ramp)
                if fx.hatch > 0:
                    from spolvero.render.skia import _draw_hatch
                    n_hatch += _draw_hatch(canvas, path, [(p.x, p.y) for p in pts], (r, g, b), fx.hatch)
        else:
            stroke.setColor(col); stroke.setStrokeWidth(leaf.width); canvas.drawPath(path, stroke)
    img = surface.makeImageSnapshot()
    arr = img.toarray()[:, :, [2, 1, 0]].astype(np.float64)
    if fx is not None:
        arr = apply_haze(arr, PAPER_RGB, fx.haze)
        arr = apply_material(arr, fx.grain_seed, fx.material)
        arr = apply_vignette(arr, fx.vignette)
    return np.clip(arr, 0, 255)


def _area(pts) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        a += pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y
    return abs(a) * 0.5


def write_png(arr, path) -> str:
    a = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
    h, w, _ = a.shape
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = a[:, :, 2]; rgba[:, :, 1] = a[:, :, 1]
    rgba[:, :, 2] = a[:, :, 0]; rgba[:, :, 3] = 255
    img = skia.Image.fromarray(np.ascontiguousarray(rgba), skia.kBGRA_8888_ColorType,
                               alphaType=skia.kOpaque_AlphaType)
    d = bytes(img.encodeToData())
    with open(path, "wb") as f:
        f.write(d)
    return hashlib.sha256(d).hexdigest()


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    nodes, wbreaks, wwidths = build_scene()
    from spolvero.core.scene import flatten_all

    leaves = flatten_all(nodes)
    n_shape = sum(1 for x in leaves if isinstance(x, InkShape))
    n_fill = sum(1 for x in leaves if isinstance(x, InkShape) and x.fill)
    n_dot = sum(1 for x in leaves if isinstance(x, InkDot))
    n_col = sum(1 for x in leaves if isinstance(x, InkDot) and x.color in ACCENTS)
    verts = sum(len(x.ring) for x in leaves if isinstance(x, InkShape))
    print(f"元素  叶节点={len(leaves)}  面={n_shape}(其中填充笔画 {n_fill})  点={n_dot}(彩色 {n_col})  顶点={verts}")
    print(f"水纹  20 条线 → 断成 {wbreaks + 20} 段笔画（断裂 {wbreaks} 处）；v1 为 34 条等距等宽")
    ws = [w for lo, hi in wwidths for w in (lo, hi) if w > 0]
    print(f"水纹  线宽范围 {min(ws):.2f}–{max(ws):.2f}px（v1 固定 1.0–2.2）")

    arr = render(nodes, fx_on=True)
    flat = render(nodes, fx_on=False)
    for name, a in (("wu_brush.png", arr), ("wu_brush_flat.png", flat)):
        print(f"  {name:20s} sha256={write_png(a, os.path.join(OUT, name))[:16]}…")

    lum = np.asarray(flat)[:, :, 0]   # 明度层级必须在**平涂帧**上量：纸纹本身有 ±20 扰动，会把浅灰推过档位
    print("明度层级（平涂帧；目标：中灰要够厚）")
    for tag, m in (("黑 <=70", lum <= 70), ("深灰 70-130", (lum > 70) & (lum <= 130)),
                   ("中灰 130-185", (lum > 130) & (lum <= 185)), ("浅 >185", lum > 185)):
        print(f"  {tag:14s} {float(m.mean()) * 100:5.2f}%")
    print("  v1 参考（带质感层口径）：深 8.3% / 中 10.4% / 浅 81.3%")

    bs = 64
    ink = (np.abs(np.asarray(flat) - np.array(PAPER_RGB)).sum(axis=2) > 80).astype(np.float64)
    hh, ww = (H // bs) * bs, (W // bs) * bs
    blk = ink[:hh, :ww].reshape(hh // bs, bs, ww // bs, bs).mean(axis=(1, 3))
    print(f"局部有笔率（平涂帧 64px 窗口）平均 {blk.mean() * 100:5.2f}%  "
          f"纯空白窗口 {float((blk < 0.02).mean()) * 100:5.1f}%")

    for tag, (y0, y1, x0, x1) in {"wu2_zoom_houses.png": (270, 570, 170, 700),
                                  "wu2_zoom_water.png": (600, 880, 380, 1180)}.items():
        gap = np.full((y1 - y0, 14, 3), 40.0)
        sheet = np.concatenate([np.asarray(flat)[y0:y1, x0:x1], gap,
                                np.asarray(arr)[y0:y1, x0:x1]], axis=1)
        write_png(sheet, os.path.join(OUT, tag))
    print("产物：wu_brush.png / wu_brush_flat.png / wu2_zoom_houses.png / wu2_zoom_water.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
