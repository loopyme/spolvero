"""渲染公共工具。"""

from __future__ import annotations


def gray_of(ink: float) -> int:
    """ink ∈ [0,1] → 灰度 0..255（0=黑，255=白）。round 为确定性银行家舍入。"""
    return int(round(255.0 * (1.0 - ink) ** 1.1))


def color_of(ink: float, color: "str | None" = None) -> tuple[int, int, int]:
    """返回 (r,g,b)。若给定 color(#RRGGBB) 则用它，否则按 ink 取灰度。

    彩色支持（M3 起 schema 就绪）：默认全片灰度；主题着色场景后续接入样式调色板。
    """
    if color:
        h = color.lstrip("#")
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    g = gray_of(ink)
    return (g, g, g)
