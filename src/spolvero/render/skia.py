"""Skia 后端（png 光栅，BUY skia-python 144.0.post2）。

仅使用已内省确认可用的 API（Surface/Canvas/Path/Paint/Image/Rect/clipPath），
不依赖未暴露的 PathEffect.MakeDiscrete/MakeDash（笔刷质感自研，见 render/effects.py）。

作画痕迹层（M7 前置）由 `fx: EffectsRuntime` 驱动：
- **绘制期**：glow（点光晕，画在主体之前）、ramp（形体明暗分带）、hatch（蚀刻排线，clip 到轮廓内）
- **光栅后**：haze（大气透视）、material（纸纹颗粒）、vignette（暗角）
`fx=None` 或全零时，渲染路径与从前逐字节一致。
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import skia

from spolvero.core.primitives import InkDot, InkShape
from spolvero.render.common import color_of
from spolvero.render.effects import (
    HATCH_ALPHA_MAX,
    HATCH_BANDS,
    HATCH_MIN_AREA,
    HATCH_SPACING,
    HATCH_SPACING_SPAN,
    HATCH_WIDTH,
    RAMPS,
    EffectsRuntime,
    apply_haze,
    apply_material,
    apply_vignette,
    ring_area,
)
from spolvero.styles.apply import darken, mix, parse_hex

Bg = Tuple[int, int, int]
Overlay = Tuple[int, int, int, float]


def _path_of(pts, closed: bool) -> skia.Path:
    path = skia.Path()
    path.moveTo(pts[0].x, pts[0].y)
    for p in pts[1:]:
        path.lineTo(p.x, p.y)
    if closed:
        path.close()
    return path


def _draw_glow(canvas, leaves: Sequence, amount: float) -> None:
    """点光源晕：同心圆递减 alpha 做径向衰减。是 emission（发光），不是照明模型。"""
    from spolvero.core.scene import flatten_all

    p = skia.Paint()
    p.setAntiAlias(True)
    p.setStyle(skia.Paint.kFill_Style)
    for leaf in flatten_all(leaves):
        if not isinstance(leaf, InkDot):
            continue
        r, g, b = color_of(leaf.ink, leaf.color)
        for k in range(8, 0, -1):
            rr = leaf.r * (1.0 + k * 0.40 * amount)
            a = int(44.0 / k * amount)
            if a <= 2:
                continue
            p.setColor(skia.ColorSetARGB(a, r, g, b))
            canvas.drawCircle(leaf.pos.x, leaf.pos.y, rr, p)


def _draw_ramp(canvas, path, pts, rgb, paper, amount: float) -> None:
    """形体内部自上而下的明暗分带（整数 lerp，不引入任何光源）。"""
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    lo, hi = min(ys), max(ys)
    x0, x1 = min(xs), max(xs)
    span = max(hi - lo, 1e-6)
    light = mix(rgb, paper, 0.14 * amount)
    dark = darken(rgb, 0.52 * amount)
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setStyle(skia.Paint.kFill_Style)
    canvas.save()
    canvas.clipPath(path)
    for b in range(RAMPS):
        y0 = lo + span * b / RAMPS
        y1 = lo + span * (b + 1) / RAMPS
        c = mix(light, dark, (b + 0.5) / RAMPS)
        p.setColor(skia.ColorSetARGB(255, c[0], c[1], c[2]))
        canvas.drawRect(skia.Rect.MakeLTRB(x0 - 6.0, y0 - 0.7, x1 + 6.0, y1 + 0.7), p)
    canvas.restore()


def _draw_hatch(canvas, path, ring, rgb, amount: float) -> int:
    """蚀刻排线：按 y 分带渐变 alpha，形体底部更密更重（体积靠线密度，不靠光）。

    性能（2026-09-28 实测后重写，勿回退）：
    旧实现用 `shapely` 把每条斜线**逐条裁进多边形**（GEOS 调用数千次），
    再用几千次 `drawPath` 逐个描出来 —— 单帧因此要 2.5s+。
    参照影片的 `etch()` 根本不裁剪：**`clip(p)` 之后把整束斜线塞进一条 path，只 stroke 一次**。
    这里照搬，并把「上淡下重」的明暗保留为 **HATCH_BANDS 条横向条带**（每带一次 clipRect + 一次 drawPath），
    于是成本从「数千次 GEOS + 数千次绘制」降到「每条带 2 次调用」。
    """
    from spolvero.core.dmath import dcos, dsin

    ys = [p[1] for p in ring]
    lo, hi = min(ys), max(ys)
    if hi - lo < 2.0:
        return 0
    xs = [p[0] for p in ring]
    bx0, bx1 = min(xs), max(xs)
    dark = darken(parse_hex("#%02x%02x%02x" % rgb), 0.55)
    spacing = HATCH_SPACING + HATCH_SPACING_SPAN * (1.0 - amount)
    rad = -34.0 * 3.141592653589793 / 180.0
    dx, dy = dcos(rad), dsin(rad)
    nx, ny = -dy, dx                     # 线的法向 = 排线推进方向
    cx, cy = (bx0 + bx1) * 0.5, (lo + hi) * 0.5
    # 覆盖整个包围盒所需的推进范围
    half = (((bx1 - bx0) * nx) ** 2 + ((hi - lo) * ny) ** 2) ** 0.5 * 0.5 + spacing
    L = ((bx1 - bx0) ** 2 + (hi - lo) ** 2) ** 0.5 * 1.1 + 6.0

    p = skia.Paint()
    p.setAntiAlias(True)
    p.setStyle(skia.Paint.kStroke_Style)
    p.setStrokeCap(skia.Paint.kRound_Cap)
    p.setStrokeWidth(HATCH_WIDTH)

    n_lines = 0
    band_h = (hi - lo) / HATCH_BANDS
    canvas.save()
    canvas.clipPath(path)                # ← 关键：不裁剪几何，交给光栅器
    for b in range(HATCH_BANDS):
        y0 = lo + band_h * b
        y1 = y0 + band_h
        a = min(int(255 * (0.16 + 0.42 * ((b + 0.5) / HATCH_BANDS)) * amount), HATCH_ALPHA_MAX)
        if a <= 3:
            continue
        p.setColor(skia.ColorSetARGB(a, dark[0], dark[1], dark[2]))
        hatch_path = skia.Path()
        d = -half
        while d <= half:
            px, py = cx + nx * d, cy + ny * d
            hatch_path.moveTo(px - dx * L, py - dy * L)
            hatch_path.lineTo(px + dx * L, py + dy * L)
            d += spacing
        n_lines += max(1, int((2 * half) // spacing) + 1)
        canvas.save()
        canvas.clipRect(skia.Rect.MakeLTRB(bx0 - 2.0, y0 - 0.5, bx1 + 2.0, y1 + 0.5))
        canvas.drawPath(hatch_path, p)   # 一条 path，一次 stroke
        canvas.restore()
    canvas.restore()
    return n_lines


def _draw_border(canvas, w: int, h: int, seed: int) -> None:
    """不均匀冲印画框：顶/底压条边缘微微抖动，替代干净的数字化画框。"""
    import numpy as np

    from spolvero.render.effects import _hash01

    p = skia.Paint()
    p.setAntiAlias(True)
    p.setColor(skia.ColorSetARGB(255, 12, 13, 10))
    for top, base_y, salt in ((True, 20.0, 0), (False, h - 20.0, 1)):
        xs = np.arange(0, w + 1, 24, dtype=np.int64)
        jit = (_hash01(xs, np.full_like(xs, salt), 99 + (seed % 97)) - 0.5) * 9.0
        path = skia.Path()
        if top:
            path.moveTo(0.0, 0.0)
            path.lineTo(float(w), 0.0)
        else:
            path.moveTo(0.0, float(h))
            path.lineTo(float(w), float(h))
        for x, j in zip(reversed(xs.tolist()), reversed(jit.tolist())):
            path.lineTo(float(x), base_y + j)
        path.close()
        canvas.drawPath(path, p)


def _png_from_rgb(arr, w: int, h: int) -> bytes:
    """RGB 数组 → PNG 字节（本机 Skia N32 为 BGRA，显式换序后交给 fromarray）。"""
    import numpy as np

    a = np.ascontiguousarray(arr.astype(np.uint8))
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = a[:, :, 2]
    rgba[:, :, 1] = a[:, :, 1]
    rgba[:, :, 2] = a[:, :, 0]
    rgba[:, :, 3] = 255
    img = skia.Image.fromarray(
        rgba, skia.kBGRA_8888_ColorType, alphaType=skia.kOpaque_AlphaType
    )
    return bytes(img.encodeToData())


def render_png(
    leaves: Sequence,
    width: int,
    height: int,
    bg: Bg,
    overlay: Overlay | None = None,
    fx: EffectsRuntime | None = None,
) -> bytes:
    if fx is not None and fx.is_noop:
        fx = None

    r, g, b = bg
    surface = skia.Surface(width, height)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorSetARGB(255, r, g, b))

    if fx is not None and fx.glow > 0:
        _draw_glow(canvas, leaves, fx.glow)

    stroke = skia.Paint()
    stroke.setAntiAlias(True)
    stroke.setStyle(skia.Paint.kStroke_Style)
    stroke.setStrokeJoin(skia.Paint.kRound_Join)
    stroke.setStrokeCap(skia.Paint.kRound_Cap)

    fillp = skia.Paint()
    fillp.setAntiAlias(True)
    fillp.setStyle(skia.Paint.kFill_Style)

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
            continue  # 生长中的单点笔画：不可见
        path = _path_of(pts, is_shape or bool(leaf.closed))

        if is_shape and leaf.fill:
            fillp.setColor(col)
            canvas.drawPath(path, fillp)
            # 只有成块的「面」才做明暗分带与排线：细长笔画面积不足，做了只会糊
            if fx is not None and ring_area([(q.x, q.y) for q in pts]) >= HATCH_MIN_AREA:
                if fx.ramp > 0:
                    _draw_ramp(canvas, path, pts, (r, g, b), fx.paper_rgb, fx.ramp)
                if fx.hatch > 0:
                    _draw_hatch(canvas, path, [(p.x, p.y) for p in pts], (r, g, b), fx.hatch)
        else:
            stroke.setColor(col)
            stroke.setStrokeWidth(leaf.width)
            canvas.drawPath(path, stroke)

    if fx is not None and fx.border:
        _draw_border(canvas, width, height, fx.grain_seed)

    if overlay is not None:
        orr, ogg, obb, oa = overlay
        if oa > 0.0:
            ov = skia.Paint()
            ov.setAntiAlias(False)
            ov.setStyle(skia.Paint.kFill_Style)
            ov.setColor(skia.ColorSetARGB(int(round(255.0 * min(1.0, oa))), orr, ogg, obb))
            canvas.drawRect(skia.Rect.MakeWH(width, height), ov)

    img = surface.makeImageSnapshot()
    if fx is None or not (fx.material or fx.haze or fx.vignette):
        return bytes(img.encodeToData())

    import numpy as np

    arr = img.toarray()[:, :, [2, 1, 0]].astype(np.float64)  # BGRA → RGB
    arr = apply_haze(arr, fx.paper_rgb, fx.haze)
    arr = apply_material(arr, fx.grain_seed, fx.material)
    arr = apply_vignette(arr, fx.vignette)
    return _png_from_rgb(arr, width, height)


def png_to_rgb(png: bytes) -> bytes:
    """PNG 字节 → 紧凑 RGB24 原始字节（H.264 编码输入）。

    从「已哈希的规范 PNG」解码，保证视频像素与帧哈希所对应的画面严格同源；
    解码出的图像在本机为 BGRA_8888，据 colorType 显式换序，不依赖平台默认。
    """
    img = skia.Image.MakeFromEncoded(png)
    if img is None:
        raise ValueError("PNG 解码失败")
    arr = img.toarray()  # (h, w, 4) uint8
    if img.colorType() == skia.kBGRA_8888_ColorType:
        arr = arr[:, :, [2, 1, 0]]
    else:
        arr = arr[:, :, :3]
    return arr.tobytes()
