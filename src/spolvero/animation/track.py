"""关键帧轨与动画集（M5）。

Channel（通道）语义——一律表达「相对实例基准姿态的增量」，不改几何、不改点数：

  translate  —— 世界系平移增量 (dx, dy)，加在实例落位之后
  rotate     —— 绕实例锚点（局部原点在世界系的位置）的旋转增量（度）
  scale      —— 绕实例锚点的等比缩放增量（倍率）
  ink_shift  —— 全实例 ink 偏移量（叠加后钳制在 [0,1]），用于明暗呼吸 / 显隐

求值确定性：仅用缓动多项式与四则运算；缺通道返回 None（该通道不施加）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from spolvero.animation.easing import get_easing
from spolvero.core.transform import Transform

Vec = Tuple[float, ...]

CHANNELS = ("translate", "rotate", "scale", "ink_shift")
# 各通道的值维度（用于校验 + 默认值）
_ARITY = {"translate": 2, "rotate": 1, "scale": 1, "ink_shift": 1}


@dataclass(frozen=True)
class Key:
    t: float
    v: Vec


@dataclass(frozen=True)
class Track:
    """单通道关键帧轨。区间外取端点值（hold），区间内按缓动插值。"""

    channel: str
    keys: Tuple[Key, ...]
    ease: str = "smooth"

    def __post_init__(self) -> None:
        if self.channel not in _ARITY:
            raise ValueError(f"未知动画通道: {self.channel!r}（可用: {list(_ARITY)}）")
        arity = _ARITY[self.channel]
        for k in self.keys:
            if len(k.v) != arity:
                raise ValueError(
                    f"通道 {self.channel} 需 {arity} 维值，实际 {len(k.v)}（t={k.t}）"
                )
        ts = [k.t for k in self.keys]
        if ts != sorted(ts):
            raise ValueError(f"通道 {self.channel} 关键帧时间必须升序: {ts}")

    @property
    def span(self) -> Tuple[float, float]:
        return (self.keys[0].t, self.keys[-1].t)

    def sample(self, t: float) -> Vec:
        ks = self.keys
        if len(ks) == 1 or t <= ks[0].t:
            return ks[0].v
        if t >= ks[-1].t:
            return ks[-1].v
        ease = get_easing(self.ease)
        for a, b in zip(ks, ks[1:]):
            if a.t <= t <= b.t:
                span = b.t - a.t
                u = 0.0 if span <= 0.0 else (t - a.t) / span
                s = ease(u)
                return tuple(av + (bv - av) * s for av, bv in zip(a.v, b.v))
        return ks[-1].v


@dataclass(frozen=True)
class AnimSet:
    """一个实例的全部动画通道。"""

    tracks: Tuple[Track, ...] = ()

    def track(self, channel: str) -> Optional[Track]:
        for tr in self.tracks:
            if tr.channel == channel:
                return tr
        return None

    def value(self, channel: str, t: float) -> Optional[Vec]:
        tr = self.track(channel)
        return tr.sample(t) if tr else None

    def ink_shift(self, t: float) -> float:
        v = self.value("ink_shift", t)
        return v[0] if v else 0.0

    def delta_transform(self, t: float, ax: float = 0.0, ay: float = 0.0) -> Transform:
        """相对基准姿态的变换增量，绕世界系锚点 (ax, ay) 施加。

        施加次序（对基准姿态产出的世界点 p）：先 rotate → 再 scale → 最后 translate。
        """
        m = Transform.identity()
        rot = self.value("rotate", t)
        if rot:
            m = Transform.rotate(rot[0], ax, ay)
        scl = self.value("scale", t)
        if scl:
            s = scl[0]
            m = Transform.scale(s, s, ax, ay).compose(m)
        tr = self.value("translate", t)
        if tr:
            m = Transform.translate(tr[0], tr[1]).compose(m)
        return m

    @property
    def duration(self) -> float:
        return max((tr.span[1] for tr in self.tracks), default=0.0)


def parse_anim(specs: Sequence[dict]) -> AnimSet:
    """从 DSL 的 anim 列表构造 AnimSet（已通过 jsonschema 校验）。"""
    tracks: List[Track] = []
    for sp in specs:
        ch = sp["channel"]
        ease = sp.get("ease", "smooth")
        keys = tuple(
            Key(float(k["t"]), _as_vec(k["v"])) for k in sp["keys"]
        )
        tracks.append(Track(ch, keys, ease))
    return AnimSet(tuple(tracks))


def _as_vec(v) -> Vec:
    if isinstance(v, (list, tuple)):
        return tuple(float(x) for x in v)
    return (float(v),)


def merge_anim(a: AnimSet, b: AnimSet) -> AnimSet:
    """合并两组轨道（b 中同名通道覆盖 a），供继承/叠加场景使用。"""
    by_ch: Dict[str, Track] = {tr.channel: tr for tr in a.tracks}
    for tr in b.tracks:
        by_ch[tr.channel] = tr
    return AnimSet(tuple(by_ch[ch] for ch in CHANNELS if ch in by_ch))
