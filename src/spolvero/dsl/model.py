"""DSL 解析后的内存模型（frozen，确定性）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from spolvero.core.primitives import Group

Bg = Tuple[int, int, int]


@dataclass(frozen=True)
class Project:
    """一个 Spolvero 工程解析后的完整状态。"""

    seed: str
    width: int
    height: int
    fps: int
    style: str
    background: Bg
    groups: Tuple[Group, ...]
    palette: dict = field(default_factory=dict)
    src_dir: str = ""
    # —— M5 时序层 ——
    duration: float = 0.0  # 成片时长（秒）；0 表示静态工程
    iids: Tuple[str, ...] = ()  # 与 groups 一一对应的实例 id
    anims: dict = field(default_factory=dict)  # iid -> AnimSet
    # —— M6a 色彩与镜头 ——
    tints: dict = field(default_factory=dict)  # iid -> "#RRGGBB"（实例级色系）
    camera: object = None  # AnimSet | None，全局相机（绕画布中心）

    def scene(self) -> list[Group]:
        return list(self.groups)

    @property
    def is_animated(self) -> bool:
        return bool(self.anims or self.camera) and self.duration > 0.0
