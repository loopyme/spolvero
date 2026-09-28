"""Skia 后端（png 光栅，BUY skia-python 144.0.post2）。

仅使用已内省确认可用的 API（Surface/Canvas/Path/Paint/Image），不依赖
未暴露的 PathEffect.MakeDiscrete/MakeDash（笔刷质感 M7 自研）。
输出为 PNG 字节，供 ffmpeg 合成与帧级一致性比对。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import skia

from spolvero.core.primitives import InkDot, InkLine, InkShape
from spolvero.render.common import color_of

Bg = Tuple[int, int, int]


def render_png(leaves: Sequence, width: int, height: int, bg: Bg) -> bytes:
    r, g, b = bg
    surface = skia.Surface(width, height)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorSetARGB(255, r, g, b))

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

        stroke.setColor(col)
        stroke.setStrokeWidth(leaf.width)
        path = skia.Path()
        if isinstance(leaf, InkLine):
            path.moveTo(leaf.points[0].x, leaf.points[0].y)
            for p in leaf.points[1:]:
                path.lineTo(p.x, p.y)
            if leaf.closed:
                path.close()
        else:  # InkShape
            path.moveTo(leaf.ring[0].x, leaf.ring[0].y)
            for p in leaf.ring[1:]:
                path.lineTo(p.x, p.y)
            path.close()
        canvas.drawPath(path, fillp if (isinstance(leaf, InkShape) and leaf.fill) else stroke)

    img = surface.makeImageSnapshot()
    return bytes(img.encodeToData())


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
