"""「孤舟渡江」示例片（东方极简符号构成）。

演示 M2 构件系统：四原型（moon/mountain/water/boat）经 Instance 稀疏 override
实例化；布局由显式 transform 控制（与实例顺序无关，命门补充）。
运行：PYTHONPATH=src python examples/demo_lonely_boat.py
产出：examples/lonely_boat.png / examples/lonely_boat.svg
"""

from __future__ import annotations

import hashlib
import os

from spolvero.components import lonely_boat_library
from spolvero.render.backend import render
from spolvero.scenes import LONELY_BOAT_SEED, lonely_boat_scene


def main() -> None:
    lib = lonely_boat_library()
    scene = lib.build_scene(lonely_boat_scene(), LONELY_BOAT_SEED)

    here = os.path.dirname(os.path.abspath(__file__))
    png = render(scene, backend="skia", width=1600, height=900)
    svg = render(scene, backend="svg", width=1600, height=900)
    with open(os.path.join(here, "lonely_boat.png"), "wb") as f:
        f.write(png)
    with open(os.path.join(here, "lonely_boat.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"PNG {len(png)} bytes  sha256={hashlib.sha256(png).hexdigest()}")
    print(f"SVG {len(svg)} chars  sha256={hashlib.sha256(svg.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
