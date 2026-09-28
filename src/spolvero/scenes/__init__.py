"""场景（具体构图）集合。

构件库（components）＝可复用的参数化原型；
场景（scenes）＝某一片子的具体构图（选哪些原型、用什么 override、摆在哪、什么 seed）。

M3 起，场景将由分镜 + DSL 生成；M2 先以 Python 显式定义，供示例与测试共用。
"""

from spolvero.scenes.lonely_boat import LONELY_BOAT_SEED, lonely_boat_scene

__all__ = ["LONELY_BOAT_SEED", "lonely_boat_scene"]
