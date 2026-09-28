"""基础几何类型。坐标系：父级局部系，y 轴向下。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)
