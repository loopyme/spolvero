"""仿射变换（自研纯 Python，确定性）。

用 2x3 矩阵 [a b c d e f] 表示，避免 numpy / libm，保证跨平台 L2 一致。
所有旋转/缩放使用 core.dmath 的确定性三角函数。
"""

from __future__ import annotations

from dataclasses import dataclass

from spolvero.core.dmath import dcos, dsin


@dataclass(frozen=True)
class Transform:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def identity(cls) -> "Transform":
        return cls()

    @classmethod
    def translate(cls, tx: float, ty: float) -> "Transform":
        return cls(e=tx, f=ty)

    @classmethod
    def rotate(cls, deg: float, ax: float = 0.0, ay: float = 0.0) -> "Transform":
        """绕 (ax, ay) 旋转 deg 度。"""
        rad = deg * 3.141592653589793 / 180.0
        ca, sa = dcos(rad), dsin(rad)
        return cls(
            a=ca, b=-sa, c=sa, d=ca,
            e=ax - ca * ax + sa * ay,
            f=ay - sa * ax - ca * ay,
        )

    @classmethod
    def scale(cls, sx: float, sy: float = 1.0, ax: float = 0.0, ay: float = 0.0) -> "Transform":
        return cls(a=sx, d=sy, e=ax - sx * ax, f=ay - sy * ay)

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.b * y + self.e, self.c * x + self.d * y + self.f)

    def compose(self, other: "Transform") -> "Transform":
        """返回 self ∘ other（先应用 other，再 self）。"""
        return Transform(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            e=self.a * other.e + self.b * other.f + self.e,
            f=self.c * other.e + self.d * other.f + self.f,
        )
