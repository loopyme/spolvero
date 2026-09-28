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

    def scene(self) -> list[Group]:
        return list(self.groups)
