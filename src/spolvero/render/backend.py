"""渲染后端分发。

接受场景（节点或节点序列），先拍平为绝对坐标叶节点，再交给具体后端。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Union

from spolvero.core.scene import Node, flatten_all

Bg = Tuple[int, int, int]
DEFAULT_BG: Bg = (247, 245, 240)


def render(
    scene: Union[Node, Sequence[Node]],
    backend: str = "svg",
    width: int = 1600,
    height: int = 900,
    bg: Bg = DEFAULT_BG,
    overlay: Optional[Tuple[int, int, int, float]] = None,
    fx=None,
) -> Union[str, bytes]:
    """渲染场景。backend='svg' 返回 str；backend='skia' 返回 PNG bytes。

    overlay=(r,g,b,alpha)：全屏叠加色，用于曝光闪烁 / 闪白闪黑转场。
    fx=EffectsRuntime：作画痕迹层（纸纹/排线/明暗/光晕/雾化/画幅）。**仅 skia 后端生效**；
      SVG 后端刻意不实现——它是零依赖的审阅/diff 通道，不该引入光栅质感。
    """
    if isinstance(scene, (list, tuple)):
        leaves = flatten_all(scene)
    else:
        leaves = flatten_all([scene])

    if backend == "svg":
        from spolvero.render.svg import render_svg

        return render_svg(leaves, width, height, bg, overlay)
    if backend == "skia":
        from spolvero.render.skia import render_png

        return render_png(leaves, width, height, bg, overlay, fx)
    raise ValueError(f"未知后端: {backend}")
