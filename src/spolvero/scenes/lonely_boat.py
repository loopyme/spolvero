"""「孤舟渡江」场景构图（东方极简符号构成）。

构图：大量留白；月悬右上；三重远山压低地平线；水纹横贯；孤舟为视觉重心；
远岸一叶小舟作留白平衡。布局由显式 transform 控制，与实例顺序无关（命门补充）。
"""

from __future__ import annotations

from typing import List

from spolvero.core.component import Instance
from spolvero.core.transform import Transform

LONELY_BOAT_SEED = "spolvero-lonely-boat-v1"

INSTANCES: List[Instance] = [
    Instance("moon", "moon", {"r": 24, "ink": 0.88, "halo": True},
             Transform.translate(1230, 175)),

    Instance("mountain", "m1", {"width": 300, "height": 72, "ink": 0.80, "jag": 0.5},
             Transform.translate(330, 374)),
    Instance("mountain", "m2", {"width": 250, "height": 54, "ink": 0.84, "jag": 0.3},
             Transform.translate(880, 360)),
    Instance("mountain", "m3", {"width": 180, "height": 42, "ink": 0.86, "jag": 0.6},
             Transform.translate(1330, 380)),

    Instance("water", "w1", {"width": 940, "lines": 4, "amp": 4, "ink": 0.22, "spacing": 15},
             Transform.translate(360, 560)),
    Instance("water", "w2", {"width": 520, "lines": 3, "amp": 3, "ink": 0.26, "spacing": 14},
             Transform.translate(1120, 620)),
    Instance("water", "w3", {"width": 760, "lines": 3, "amp": 5, "ink": 0.20, "spacing": 18},
             Transform.translate(540, 730)),
    Instance("water", "w_boat", {"width": 300, "lines": 2, "amp": 3, "ink": 0.24, "spacing": 16},
             Transform.translate(838, 700)),

    # 孤舟（视觉重心，乌篷船：篷 + 灯，去桅以求极简）
    Instance("boat", "boat_main",
             {"length": 132, "beam_ratio": 0.20, "hull_ink": 0.24,
              "has_canopy": True, "canopy_w": 0.46, "canopy_h": 0.17,
              "has_mast": False, "has_lamp": True, "tilt": -1.0},
             Transform.translate(838, 648)),
    # 远岸小舟（留白平衡，不抢戏）
    Instance("boat", "boat_far",
             {"length": 38, "beam_ratio": 0.24, "hull_ink": 0.55,
              "has_canopy": True, "has_mast": False, "has_lamp": False, "tilt": 0.8},
             Transform.translate(250, 478)),
]


def lonely_boat_scene() -> List[Instance]:
    """返回「孤舟渡江」的实例列表（供示例渲染与测试使用）。"""
    return list(INSTANCES)
