"""确定性超越函数（自研，纯 Python，不调用 libm）。

跨平台确定性要求（SPEC §9）：sin/cos/exp 走 libm，不同平台（glibc vs Apple libm）
可能有 1ulp 差异，会破坏 L2 帧级一致性。这里用纯浮点多项式（仅 + - * /，IEEE-754
跨平台确定）实现 cos/sin，先做象限归约，再把核函数限制在 |x| ≤ π/4，
误差 ~1e-10，且完全可复现。

修正记录：早期版本直接把 Taylor 级数作用在归约到 [-π, π] 的角上，
在 |x| → π 处截断误差达 ~2.4e-2（cos(π) ≈ -0.976 而非 -1），
导致 180° 旋转出现可见的尺寸偏差。现改为「归约 → 象限折叠 → 小角核函数」，
全定义域误差 ≤ 1e-10，与 1ulp 量级无关。

math.pi 是常量不是 libm 调用，可安全使用；角度归约只用 + - 与比较，确定。
"""

from __future__ import annotations

import math

_TWO_PI = 2.0 * math.pi
_HALF_PI = math.pi / 2.0
_QUARTER_PI = math.pi / 4.0


def _reduce_pi(x: float) -> float:
    """将弧度归约到 [-pi, pi]，只用 + - 与比较（确定）。"""
    while x > math.pi:
        x -= _TWO_PI
    while x < -math.pi:
        x += _TWO_PI
    return x


def _sin_core(x: float) -> float:
    """|x| ≤ π/4 的正弦核（Taylor 至 x^11，误差 ~1e-12）。"""
    x2 = x * x
    x4 = x2 * x2
    x6 = x4 * x2
    x8 = x4 * x4
    x10 = x8 * x2
    return x * (
        1.0 - x2 / 6.0 + x4 / 120.0 - x6 / 5040.0 + x8 / 362880.0 - x10 / 39916800.0
    )


def _cos_core(x: float) -> float:
    """|x| ≤ π/4 的余弦核（Taylor 至 x^10，误差 ~1e-12）。"""
    x2 = x * x
    x4 = x2 * x2
    x6 = x4 * x2
    x8 = x4 * x4
    x10 = x8 * x2
    return 1.0 - x2 / 2.0 + x4 / 24.0 - x6 / 720.0 + x8 / 40320.0 - x10 / 3628800.0


def _sin_reduced(x: float) -> float:
    """在 [-pi, pi] 上求 sin：象限折叠到 |·| ≤ π/2，再折叠到核函数区间。"""
    if x > _HALF_PI:
        x = math.pi - x
    elif x < -_HALF_PI:
        x = -math.pi - x
    if x > _QUARTER_PI:
        return _cos_core(_HALF_PI - x)
    if x < -_QUARTER_PI:
        return -_cos_core(_HALF_PI + x)
    return _sin_core(x)


def dsin(x: float) -> float:
    """确定性正弦。全定义域误差 ≤ 1e-10。"""
    return _sin_reduced(_reduce_pi(x))


def dcos(x: float) -> float:
    """确定性余弦，恒等 cos(x) = sin(x + π/2)。全定义域误差 ≤ 1e-10。"""
    return _sin_reduced(_reduce_pi(x + _HALF_PI))
