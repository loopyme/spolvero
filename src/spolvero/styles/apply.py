"""风格资产 → 场景着色（M6a）。

引擎内核只认 `ink` 灰度 + 可选 `color`；本模块是**灰度到 RGB 的唯一映射入口**，
在渲染前把调度好的场景图着色。全部为整数四则与 round（银行家舍入），确定性。

两套映射：

1. **默认（全片同一色系）**——`tone.palette` 的 paper / base / ink 三档分段线性。
   适合水墨、素描、单色主题。

2. **实例级色调 tint（故事片的默认做法）**——每个实例在时间轴上给一个 `tint: #RRGGBB`，
   把该实例的 ink 映射到「纸 → 淡 tint → tint 本色 → 深 tint」四个停靠点的色系内。
   这样远山是石青、水纹是石绿、孤舟是朱红、月是藤黄，**每个构件各有其色且仍保留明暗层次**
   ——而不是整片压成同一个色相（那正是「线色不鲜亮」的成因）。

`tint` 是显式指定，**优先于风格的 `grayscale` 设定**：用户手写了一个颜色却因为它被风格
静默忽略，是比「风格约束」更糟的意外。

停靠点用「ink 从大到小」表达（ink=1 为纸、0 为最深），`_ramp` 做通用的多停靠点分段插值。
"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence, Tuple

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.styles.asset import BASE_BREAK, StyleAsset

RGB = Tuple[int, int, int]

# 点缀色适用规则（确定性、可复核）：小半径墨点视为「点染」，取 accents[0]。
ACCENT_MAX_R = 4.0
ACCENT_MAX_INK = 0.45

Stop = Tuple[float, RGB]  # (ink 上界, 颜色)，按 ink 降序


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


def lighten(c: RGB, u: float, toward: RGB = (255, 255, 255)) -> RGB:
    return mix(c, toward, u)


def darken(c: RGB, u: float) -> RGB:
    return mix(c, (0, 0, 0), u)


def sample_ramp(stops: Sequence[Stop], ink: float) -> RGB:
    """多停靠点分段线性采样。stops 按 ink 降序，首项应为 ink=1.0，末项为 ink=0.0。"""
    if not stops:
        return (0, 0, 0)
    if ink >= stops[0][0]:
        return stops[0][1]
    for i in range(len(stops) - 1):
        hi, c_hi = stops[i]
        lo, c_lo = stops[i + 1]
        if lo <= ink <= hi:
            span = hi - lo
            u = 0.0 if span <= 0.0 else (hi - ink) / span
            return mix(c_hi, c_lo, u)
    return stops[-1][1]


def palette_stops(asset: StyleAsset) -> List[Stop]:
    """默认三档停靠点（paper / base / ink）——与历史行为逐位一致，勿随意改动。"""
    return [
        (1.0, parse_hex(asset.tone.paper)),
        (BASE_BREAK, parse_hex(asset.tone.base)),
        (0.0, parse_hex(asset.tone.ink)),
    ]


def tint_stops(asset: StyleAsset, tint: str) -> List[Stop]:
    """实例级色调的四档停靠点：纸 → 淡 tint → tint 本色 → 深 tint。"""
    paper = parse_hex(asset.tone.paper)
    t = parse_hex(tint)
    return [
        (1.0, paper),
        (0.74, mix(t, paper, 0.58)),  # 淡：远景/雾中
        (0.34, t),                    # 本色：主体
        (0.0, darken(t, 0.40)),       # 深：近景/重墨
    ]


def ink_to_rgb(ink: float, asset: StyleAsset, tint: Optional[str] = None) -> RGB:
    """ink ∈ [0,1] → RGB。给 tint 则用该实例自己的色系，否则用风格调色板。"""
    stops = tint_stops(asset, tint) if tint else palette_stops(asset)
    return sample_ramp(stops, ink)


def is_accent_leaf(leaf) -> bool:
    """小半径低墨点 → 点染（如孤舟船灯）。规则写死，便于人工复核与测试。"""
    return isinstance(leaf, InkDot) and leaf.r <= ACCENT_MAX_R and leaf.ink <= ACCENT_MAX_INK


def recolor(node, asset: StyleAsset, tint: Optional[str] = None):
    """把风格资产落到场景图（返回新节点，不改原对象）。

    优先级：显式 `color` 叶节点 > 点染（小墨点取 accents[0]）> `tint` 色系 > 风格调色板。
    灰度风格且未给 tint 时原样返回（保证既有灰度 golden 逐字节不变）。
    """
    if asset.grayscale and not tint:
        return node
    if isinstance(node, Group):
        return Group(tuple(recolor(c, asset, tint) for c in node.children), node.transform)
    if getattr(node, "color", None):
        return node
    if asset.tone.accents and is_accent_leaf(node):
        return replace(node, color=asset.tone.accents[0])
    return replace(node, color=to_hex(ink_to_rgb(node.ink, asset, tint)))


def recolor_all(nodes, asset: StyleAsset, tints: Optional[dict] = None, iids=None):
    """按实例着色。

    tints 为 {iid: "#RRGGBB"}；iids 为与 nodes 对齐的实例 id 序列。
    两者缺一即退化为「全片同一个色系」。
    """
    if not tints or iids is None:
        return [recolor(n, asset) for n in nodes]
    return [recolor(n, asset, tints.get(iid)) for iid, n in zip(iids, nodes)]
