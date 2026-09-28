"""风格预览（M6a / M6c 共用）。

两条硬约束：
1. **缩略图必须由引擎自渲染**（SPEC §7.2），不得使用参考画原图——本地资产要能自由传递，
   而且自渲染本身就是最好的功能演示。
2. `render_preview` 返回 **SVG 字符串**：引擎天然矢量，界面滑杆改动后直接替换 DOM 即可，
   无需落盘、无状态、且天然确定性（SPEC §7.2）。

预览场景复用「孤舟渡江」构件库，按设计空间 1600×900 等比缩放到目标尺寸——
保证缩略图与实际成片同构图，而不是另画一张示意图。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from spolvero.core.primitives import Group
from spolvero.core.transform import Transform
from spolvero.render.backend import render
from spolvero.styles.apply import recolor_all
from spolvero.styles.asset import StyleAsset

DESIGN_W, DESIGN_H = 1600, 900
PREVIEW_SEED = "spolvero-preview-v1"


def _design_scene():
    from spolvero.components import lonely_boat_library
    from spolvero.scenes import lonely_boat_scene

    lib = lonely_boat_library()
    return lib.build_scene(lonely_boat_scene(), PREVIEW_SEED)


def preview_nodes(size: Tuple[int, int] = (720, 480)):
    """把设计空间的场景等比缩放居中到目标尺寸（确定性纯函数）。"""
    w, h = int(size[0]), int(size[1])
    s = min(w / DESIGN_W, h / DESIGN_H)
    ox = (w - DESIGN_W * s) / 2.0
    oy = (h - DESIGN_H * s) / 2.0
    t = Transform.translate(ox, oy).compose(Transform.scale(s, s))
    return [Group(tuple(_design_scene()), t)]


def apply_knobs(asset: StyleAsset, knobs: Optional[Dict] = None) -> StyleAsset:
    """按滑杆/预览参数派生一份临时资产（不落盘、不改原对象）。

    可调项：paper / base / ink / accent / grayscale / default_ink。
    """
    if not knobs:
        return asset
    from spolvero.styles.asset import Tone

    tone = asset.tone
    if any(k in knobs for k in ("paper", "base", "ink", "accent", "accents")):
        accents = tone.accents
        if "accent" in knobs:
            accents = (knobs["accent"],) if knobs["accent"] else ()
        elif "accents" in knobs:
            accents = tuple(knobs["accents"] or ())
        tone = Tone(
            paper=str(knobs.get("paper", tone.paper)),
            base=str(knobs.get("base", tone.base)),
            ink=str(knobs.get("ink", tone.ink)),
            accents=accents,
            purity_axis=tone.purity_axis,
        )
    return asset.tweaked(
        tone=tone,
        grayscale=bool(knobs.get("grayscale", asset.grayscale)),
        default_ink=float(knobs.get("default_ink", asset.default_ink)),
    )


def render_preview(
    asset: StyleAsset,
    knobs: Optional[Dict] = None,
    size: Tuple[int, int] = (720, 480),
) -> str:
    """返回预览 **SVG 字符串**（供界面直接替换 DOM）。"""
    w, h = int(size[0]), int(size[1])
    a = apply_knobs(asset, knobs)
    nodes = recolor_all(preview_nodes((w, h)), a)
    return render(nodes, backend="svg", width=w, height=h, bg=a.paper_rgb)


def render_preview_png(
    asset: StyleAsset,
    knobs: Optional[Dict] = None,
    size: Tuple[int, int] = (720, 480),
) -> bytes:
    """返回预览 PNG 字节（缩略图落盘用）。"""
    w, h = int(size[0]), int(size[1])
    a = apply_knobs(asset, knobs)
    nodes = recolor_all(preview_nodes((w, h)), a)
    return render(nodes, backend="skia", width=w, height=h, bg=a.paper_rgb)
