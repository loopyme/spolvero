"""渲染公共工具。"""

from __future__ import annotations


def gray_of(ink: float) -> int:
    """ink ∈ [0,1] → 灰度 0..255。

    方向严格对齐 SPEC §5「`ink` 为 0（黑）–1（白/留白）」：**ink 高 = 浅**。
    round 为确定性银行家舍入。

    修正记录：早期写成了 255·(1-ink)^1.1，方向与 SPEC **相反**——于是 `Mountain.ink=0.80`
    这种按「高=浅」标注的远山被算成 43（近黑），而 `hull_ink=0.24` 的主墨船体被算成 189
    （发白）。更糟的是填充形曾误用上一次的 paint 颜色，让远山"看起来"是浅的，
    掩盖了方向错误，结果是**整幅画没有任何深色**（全在 189–210 的淡灰上），对比度仅 12%。
    """
    return int(round(255.0 * ink ** 1.1))


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
