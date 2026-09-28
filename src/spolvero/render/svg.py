"""SVG 后端（零依赖手写字符串）。

用途：给人看、给设计用、便于 git diff。坐标固定 3 位小数，保证同输入同输出。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from spolvero.core.primitives import InkDot, InkLine, InkShape
from spolvero.render.common import color_of

Bg = Tuple[int, int, int]


def _fmt_pts(pts) -> str:
    return " ".join(f"{p.x:.3f},{p.y:.3f}" for p in pts)


def render_svg(leaves: Sequence, width: int, height: int, bg: Bg) -> str:
    r, g, b = bg
    out: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="rgb({r},{g},{b})"/>',
    ]
    for leaf in leaves:
        r, g, b = color_of(leaf.ink, leaf.color)
        stroke = f"rgb({r},{g},{b})"
        if isinstance(leaf, InkLine):
            sw = f"{leaf.width:.3f}"
            pts = _fmt_pts(leaf.points)
            tag = "polygon" if leaf.closed else "polyline"
            out.append(
                f'<{tag} points="{pts}" fill="none" stroke="{stroke}" '
                f'stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"/>'
            )
        elif isinstance(leaf, InkShape):
            sw = f"{leaf.width:.3f}"
            pts = _fmt_pts(leaf.ring)
            fill = stroke if leaf.fill else "none"
            out.append(
                f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{sw}" stroke-linejoin="round"/>'
            )
        elif isinstance(leaf, InkDot):
            out.append(
                f'<circle cx="{leaf.pos.x:.3f}" cy="{leaf.pos.y:.3f}" '
                f'r="{leaf.r:.3f}" fill="{stroke}"/>'
            )
    out.append("</svg>")
    return "".join(out)
