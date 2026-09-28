"""场景图拍平：将 group 的仿射变换应用到叶节点，输出绝对坐标的叶节点列表。

拍平是纯函数、确定性，与渲染后端解耦——SVG / Skia 后端都消费拍平后的叶列表。
"""

from __future__ import annotations

from typing import List, Sequence, Union

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.transform import Transform
from spolvero.core.types import Point

Leaf = Union[InkLine, InkShape, InkDot]
Node = Union[Leaf, Group]

_IDENTITY = Transform.identity()


def _transform_leaf(leaf: Leaf, t: Transform) -> Leaf:
    if isinstance(leaf, InkLine):
        return InkLine(
            points=tuple(Point(*t(p.x, p.y)) for p in leaf.points),
            width=leaf.width,
            ink=leaf.ink,
            closed=leaf.closed,
            color=leaf.color,
        )
    if isinstance(leaf, InkShape):
        return InkShape(
            ring=tuple(Point(*t(p.x, p.y)) for p in leaf.ring),
            ink=leaf.ink,
            fill=leaf.fill,
            color=leaf.color,
        )
    if isinstance(leaf, InkDot):
        nx, ny = t(leaf.pos.x, leaf.pos.y)
        return InkDot(pos=Point(nx, ny), r=leaf.r, ink=leaf.ink, color=leaf.color)
    raise TypeError(f"未知叶节点: {leaf!r}")


def flatten(node: Node, parent: Transform = _IDENTITY) -> List[Leaf]:
    """递归拍平：group 的 transform 与父变换组合后应用到子节点。"""
    if isinstance(node, Group):
        combined = parent.compose(node.transform)
        out: List[Leaf] = []
        for child in node.children:
            out.extend(flatten(child, combined))
        return out
    return [_transform_leaf(node, parent)]


def flatten_all(nodes: Sequence[Node], parent: Transform = _IDENTITY) -> List[Leaf]:
    out: List[Leaf] = []
    for n in nodes:
        out.extend(flatten(n, parent))
    return out
