"""构件接触表：单个 boat 原型 → 50 个差异化实例（M2 核心验收物）。

证明「同源不同形」：同一原型，经 L1 参数随机 + L2 拓扑开关 + 逐点抖动，
产出尺寸、墨色、篷/桅/灯组合、轮廓各不相同的实例，无复制粘贴。

注：此处为诊断用接触表，采用索引网格排布。真实片子的布局一律走 Instance 的
显式 transform（与实例顺序无关，见 SPEC 命门补充 / scenes/lonely_boat.py）。

运行：PYTHONPATH=src python examples/demo_boat_grid.py
"""

from __future__ import annotations

import os

from spolvero.components import lonely_boat_library
from spolvero.core.component import Instance
from spolvero.core.rng import derive
from spolvero.core.transform import Transform
from spolvero.render.backend import render

SEED = "spolvero-boat-grid-v1"
COLS, ROWS = 10, 5
CELL_W, CELL_H = 158.0, 168.0
OX, OY = 92.0, 108.0


def build():
    lib = lonely_boat_library()
    insts = []
    for n in range(COLS * ROWS):
        iid = f"boat_{n:03d}"
        c, r = n % COLS, n // COLS
        x = OX + c * CELL_W + (derive(SEED, iid, "px") - 0.5) * 34
        y = OY + r * CELL_H + (derive(SEED, iid, "py") - 0.5) * 30
        insts.append(Instance("boat", iid, {}, Transform.translate(x, y)))
    return lib.build_scene(insts, SEED)


def main() -> None:
    scene = build()
    here = os.path.dirname(os.path.abspath(__file__))
    png = render(scene, backend="skia", width=1600, height=900)
    svg = render(scene, backend="svg", width=1600, height=900)
    with open(os.path.join(here, "boats_grid.png"), "wb") as f:
        f.write(png)
    with open(os.path.join(here, "boats_grid.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"PNG {len(png)} bytes / SVG {len(svg)} chars")


if __name__ == "__main__":
    main()
