"""四原语数据模型（引擎内核，永久固定）。

所有画面最终由以下四原语构成：
  ink_line  : 自由折线 / 书法线
  ink_shape : 任意闭合轮廓（控制点数量恒定，命门 3）
  ink_dot   : 点状色点 / 墨点
  group     : 分组容器（仅做批量变换，无造型）

设计要点：
- 全部 frozen dataclass，渲染期不可变，配合派生随机保证可复现。
- ink ∈ [0,1] 灰度（0=黑，1=留白），由风格预设映射为 RGB。
- ink_shape.ring 的控制点数量在原型定义时固定，实例化只调参数不调点数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from spolvero.core.transform import Transform
from spolvero.core.types import Point


@dataclass(frozen=True)
class InkLine:
    points: Tuple[Point, ...]
    width: float = 1.5
    ink: float = 0.4
    closed: bool = False
    color: Optional[str] = None  # "#RRGGBB" 覆盖灰度；默认 None → 按 ink 灰度


@dataclass(frozen=True)
class InkShape:
    ring: Tuple[Point, ...]  # 闭合轮廓，控制点数量恒定
    ink: float = 0.4
    fill: bool = False
    width: float = 1.5
    color: Optional[str] = None


@dataclass(frozen=True)
class InkDot:
    pos: Point
    r: float = 2.0
    ink: float = 0.4
    color: Optional[str] = None


@dataclass(frozen=True)
class Group:
    children: Tuple["Node", ...]
    transform: Transform = field(default_factory=Transform)


# 叶节点联合类型
Node = "InkLine | InkShape | InkDot | Group"
