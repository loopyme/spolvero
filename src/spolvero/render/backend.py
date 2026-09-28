"""渲染后端分发。

接受场景（节点或节点序列），先拍平为绝对坐标叶节点，再交给具体后端。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Union

from spolvero.core.scene import Node, flatten_all

Bg = Tuple[int, int, int]
DEFAULT_BG: Bg = (247, 245, 240)


def render(
    scene: Union[Node, Sequence[Node]],
    backend: str = "svg",
    width: int = 1600,
    height: int = 900,
    bg: Bg = DEFAULT_BG,
) -> Union[str, bytes]:
    """渲染场景。backend='svg' 返回 str；backend='skia' 返回 PNG bytes。"""
    if isinstance(scene, (list, tuple)):
        leaves = flatten_all(scene)
    else:
        leaves = flatten_all([scene])

    if backend == "svg":
        from spolvero.render.svg import render_svg

        return render_svg(leaves, width, height, bg)
    if backend == "skia":
        from spolvero.render.skia import render_png

        return render_png(leaves, width, height, bg)
    raise ValueError(f"未知后端: {backend}")
