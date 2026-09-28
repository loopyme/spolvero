"""确定性缓动函数（M5）。

全部为纯多项式 / 四则运算，不使用 exp / pow / libm，保证跨平台逐位一致（SPEC §5）。
输入 t ∈ [0,1]，输出 s ∈ [0,1]，且 s(0)=0、s(1)=1（端点严格包含）。

  linear —— 匀速
  smooth —— 平滑起步收尾 3t²-2t³（smoothstep）
  in     —— 加速 t²
  out    —— 减速 1-(1-t)²
"""

from __future__ import annotations

from typing import Callable, Dict


def linear(t: float) -> float:
    return t


def smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


EASINGS: Dict[str, Callable[[float], float]] = {
    "linear": linear,
    "smooth": smooth,
    "in": ease_in,
    "out": ease_out,
}


def get_easing(name: str) -> Callable[[float], float]:
    """取缓动函数；未知名称回退 smooth（不抛错，保证工程可降级渲染）。"""
    return EASINGS.get(name, smooth)
