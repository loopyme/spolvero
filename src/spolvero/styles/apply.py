"""风格资产 → 场景着色（M6a）。

引擎内核只认 `ink` 灰度 + 可选 `color`；本模块是**灰度到 RGB 的唯一映射入口**，
在渲染前把调度好的场景图着色。全部为整数四则与 round（银行家舍入），确定性。

三档映射（`tone.palette`）：
    ink = 1.0            → paper（留白）
    ink = BASE_BREAK     → base（中间调 / 淡墨）
    ink = 0.0            → ink（主墨）
分段线性，避免把「墨分五色」压成两色，也不需要任意长度色卡（见 asset.py 说明）。

灰度风格（grayscale=True）不做任何着色，直接返回原节点——保证首片与既有 golden 不变。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Tuple

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.styles.asset import BASE_BREAK, StyleAsset

RGB = Tuple[int, int, int]

# 点缀色适用规则（确定性、可复核）：小半径墨点视为「点染」，取 accents[0]。
ACCENT_MAX_R = 4.0
ACCENT_MAX_INK = 0.45


def parse_hex(h: str) -> RGB:
    s = (h or "").lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return (0, 0, 0)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def to_hex(c: RGB) -> str:
    return "#%02x%02x%02x" % (c[0], c[1], c[2])


def mix(c0: RGB, c1: RGB, u: float) -> RGB:
    """整数线性插值；u 已在 [0,1] 内由调用方保证。"""
    return (
        int(round(c0[0] + (c1[0] - c0[0]) * u)),
        int(round(c0[1] + (c1[1] - c0[1]) * u)),
        int(round(c0[2] + (c1[2] - c0[2]) * u)),
    )


def ink_to_rgb(ink: float, asset: StyleAsset) -> RGB:
    """ink ∈ [0,1] → RGB（三档分段线性）。"""
    paper = parse_hex(asset.tone.paper)
    base = parse_hex(asset.tone.base)
    deep = parse_hex(asset.tone.ink)
    if ink >= 1.0:
        return paper
    if ink >= BASE_BREAK:
        u = (1.0 - ink) / (1.0 - BASE_BREAK)
        return mix(paper, base, u)
    u = 1.0 - (ink / BASE_BREAK if BASE_BREAK > 0 else 1.0)
    return mix(base, deep, u)


def is_accent_leaf(leaf) -> bool:
    """小半径低墨点 → 点染（如孤舟船灯）。规则写死，便于人工复核与测试。"""
    return isinstance(leaf, InkDot) and leaf.r <= ACCENT_MAX_R and leaf.ink <= ACCENT_MAX_INK


def recolor(node, asset: StyleAsset):
    """把风格资产落到场景图（返回新节点，不改原对象）。

    - 灰度风格：原样返回。
    - 显式 `color` 的叶节点：最高优先，不被覆盖面（裸原语模式的手动指定色）。
    - 点染叶节点：取 `tone.accents[0]`。
    - 其余：按 ink 走三档映射。
    """
    if asset.grayscale:
        return node
    if isinstance(node, Group):
        return Group(tuple(recolor(c, asset) for c in node.children), node.transform)
    if getattr(node, "color", None):
        return node
    if asset.tone.accents and is_accent_leaf(node):
        return replace(node, color=asset.tone.accents[0])
    return replace(node, color=to_hex(ink_to_rgb(node.ink, asset)))


def recolor_all(nodes, asset: StyleAsset):
    return [recolor(n, asset) for n in nodes]
