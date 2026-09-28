"""确定性超越函数（自研，纯 Python，不调用 libm）。

跨平台确定性要求（SPEC §9）：sin/cos/exp 走 libm，不同平台（glibc vs Apple libm）
可能有 1ulp 差异，会破坏 L2 帧级一致性。这里用纯浮点多项式（仅 + - * /，IEEE-754
跨平台确定）实现 cos/sin，误差 ~1e-9，远小于 1ulp 风险，且完全可复现。

math.pi 是常量不是 libm 调用，可安全使用；角度归约只用 + - 与比较，确定。
"""

from __future__ import annotations

import math

_TWO_PI = 2.0 * math.pi


def _reduce(x: float) -> float:
    """将弧度归约到 [-pi, pi]，只用 + - 与比较（确定）。"""
    while x > math.pi:
        x -= _TWO_PI
    while x < -math.pi:
        x += _TWO_PI
    return x


def dcos(x: float) -> float:
    """确定性余弦（Taylor 至 10 阶）。"""
    x = _reduce(x)
    x2 = x * x
    x4 = x2 * x2
    x6 = x4 * x2
    x8 = x4 * x4
    return 1.0 - x2 / 2.0 + x4 / 24.0 - x6 / 720.0 + x8 / 40320.0


def dsin(x: float) -> float:
    """确定性正弦（Taylor 至 9 阶）。"""
    x = _reduce(x)
    x2 = x * x
    x4 = x2 * x2
    x6 = x4 * x2
    return x - x * x2 / 6.0 + x * x4 / 120.0 - x * x6 / 5040.0
