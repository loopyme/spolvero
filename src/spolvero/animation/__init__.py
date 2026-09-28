"""Spolvero 时序动画层（M5）。

分层：
  easing  —— 确定性缓动（纯多项式，不碰 libm，保 L2 跨平台一致）
  track   —— 关键帧轨（Keyframe / Track / AnimSet）与通道求值
  film    —— 成片管线：逐帧求值 → 渲染 → PNG 帧序列 / MP4(H.264) / 快照 manifest

设计要点（SPEC §9）：
- 动画不改几何、不改控制点数，只叠加「相对基准姿态的变换增量」与全局 ink 偏移。
- 求值只依赖 t 与关键帧表，与帧序、与实例顺序无关，因此天然可复现、可跳帧渲染。
- 满环（首末关键帧同值）时 t=0 与 t=duration 姿态严格相等 → MP4 无缝循环。
"""

from spolvero.animation.easing import EASINGS, get_easing
from spolvero.animation.film import (
    encode_mp4,
    frame_hash,
    iter_frames,
    render_frame,
    scene_at,
    snapshot,
)
from spolvero.animation.track import AnimSet, Key, Track, parse_anim

__all__ = [
    "EASINGS",
    "get_easing",
    "Key",
    "Track",
    "AnimSet",
    "parse_anim",
    "scene_at",
    "render_frame",
    "iter_frames",
    "encode_mp4",
    "snapshot",
    "frame_hash",
]
