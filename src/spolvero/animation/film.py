"""成片管线（M5）：逐帧求值 → 渲染 → PNG 帧序列 / MP4 / 快照 manifest。

确定性分级（SPEC §5）：
  L1 同机同版本 —— 帧 PNG 字节完全一致（帧哈希门禁）
  L2 跨平台     —— 帧 PNG 像素一致（几何/缓动不碰 libm）
  L3 视频       —— 像素一致，字节不保证（ffmpeg 版本/封装差异）

时间轴约定：帧 i 对应 t = i / fps，取 i ∈ [0, round(duration·fps))，
即不含 t = duration 的重复首帧 → 满环动画可无缝循环。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.scene import Node
from spolvero.render.backend import render

Bg = Tuple[int, int, int]


# ───────────────────────── ink 偏移 ─────────────────────────
def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def shift_ink(node: Node, delta: float) -> Node:
    """递归叠加 ink 偏移（钳制 [0,1]）。只改灰度值，不改几何、不改点数。"""
    if isinstance(node, Group):
        return Group(
            tuple(shift_ink(c, delta) for c in node.children), node.transform
        )
    if isinstance(node, InkLine):
        return replace(node, ink=_clamp01(node.ink + delta))
    if isinstance(node, InkShape):
        return replace(node, ink=_clamp01(node.ink + delta))
    if isinstance(node, InkDot):
        return replace(node, ink=_clamp01(node.ink + delta))
    raise TypeError(f"未知节点: {node!r}")


# ───────────────────────── 逐帧求值 ─────────────────────────
def scene_at(project, t: float) -> List[Group]:
    """求 t 时刻的场景（相对基准姿态施加各实例的动画增量）。"""
    anims = getattr(project, "anims", None) or {}
    iids = getattr(project, "iids", ()) or ()
    out: List[Group] = []
    for idx, g in enumerate(project.groups):
        iid = iids[idx] if idx < len(iids) else ""
        anim = anims.get(iid)
        if anim is None or not anim.tracks:
            out.append(g)
            continue
        ax, ay = g.transform(0.0, 0.0)  # 实例锚点（世界系）
        delta = anim.delta_transform(t, ax, ay)
        node = Group(g.children, delta.compose(g.transform))
        s = anim.ink_shift(t)
        if s:
            node = Group(tuple(shift_ink(c, s) for c in node.children), node.transform)
        out.append(node)
    return out


def frame_hash(data) -> str:
    """帧内容哈希：bytes 直接哈希，str 按 UTF-8 编码（SVG 用）。"""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def render_frame(
    project,
    t: float,
    backend: str = "skia",
    width: Optional[int] = None,
    height: Optional[int] = None,
    bg: Optional[Bg] = None,
):
    w = int(width or project.width)
    h = int(height or project.height)
    b = bg if bg is not None else project.background
    return render(scene_at(project, t), backend=backend, width=w, height=h, bg=b)


def _resolve_timeline(project, fps: Optional[int], duration: Optional[float]):
    fps = int(fps or getattr(project, "fps", 0) or 24)
    dur = duration if duration is not None else getattr(project, "duration", 0.0)
    dur = float(dur or 0.0)
    if dur <= 0.0:
        raise ValueError(
            "工程未定义 duration（在 project.yaml 写 duration: <秒>），无法成片"
        )
    return fps, dur


def iter_frames(
    project,
    backend: str = "skia",
    fps: Optional[int] = None,
    duration: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    bg: Optional[Bg] = None,
) -> Iterator[Tuple[int, float, object]]:
    """惰性产出 (帧号, 时刻, 渲染结果)。后端为 skia 时结果为 PNG bytes。"""
    fps, dur = _resolve_timeline(project, fps, duration)
    n = int(round(dur * fps))
    for i in range(n):
        t = i / fps
        yield i, t, render_frame(project, t, backend, width, height, bg)


# ───────────────────────── MP4 合成 ─────────────────────────
def encode_mp4(
    project,
    out_path: str,
    fps: Optional[int] = None,
    duration: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    bg: Optional[Bg] = None,
    crf: int = 18,
) -> Dict:
    """渲染全片并合成为 H.264 MP4（yuv420p，faststart）。返回合成信息。"""
    import imageio_ffmpeg

    from spolvero.render.skia import png_to_rgb

    fps, dur = _resolve_timeline(project, fps, duration)
    w = int(width or project.width)
    h = int(height or project.height)
    if w % 2 or h % 2:
        raise ValueError(f"H.264 yuv420p 要求宽高为偶数，当前 {w}x{h}")

    out_path = os.path.abspath(out_path)
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)

    writer = imageio_ffmpeg.write_frames(
        out_path,
        (w, h),
        fps=fps,
        codec="libx264",
        pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p",
        macro_block_size=None,
        ffmpeg_log_level="error",
        output_params=["-crf", str(crf), "-movflags", "+faststart"],
    )
    writer.send(None)

    n = 0
    hashes: List[str] = []
    try:
        for _i, _t, png in iter_frames(project, "skia", fps, dur, w, h, bg):
            writer.send(png_to_rgb(png))
            hashes.append(frame_hash(png))
            n += 1
    finally:
        writer.close()

    return {
        "path": out_path,
        "frames": n,
        "fps": fps,
        "size": [w, h],
        "duration": (n / fps) if fps else 0.0,
        "bytes": os.path.getsize(out_path),
        "frame_hashes": hashes,
        "first_frame_hash": hashes[0] if hashes else "",
        "last_frame_hash": hashes[-1] if hashes else "",
        "loop_closed": bool(hashes) and _loop_closed(project, dur),
    }


def _loop_closed(project, duration: float) -> bool:
    """首末姿态是否严格相等（满环 → MP4 可无缝循环）。"""
    a = scene_at(project, 0.0)
    b = scene_at(project, duration)
    return _node_key(a) == _node_key(b)


def _node_key(nodes: Sequence[Node]):
    from spolvero.core.scene import flatten_all

    return [
        (type(lf).__name__, tuple(round(v, 9) for p in _pts(lf) for v in p), round(lf.ink, 9))
        for lf in flatten_all(nodes)
    ]


def _pts(lf):
    if isinstance(lf, InkDot):
        return [lf.pos.xy()]
    src = lf.ring if isinstance(lf, InkShape) else lf.points
    return [p.xy() for p in src]


# ───────────────────────── 快照存档 ─────────────────────────
def snapshot(
    project,
    out_dir: str,
    times: Sequence[float] = (0.0,),
    width: Optional[int] = None,
    height: Optional[int] = None,
    bg: Optional[Bg] = None,
    label: str = "",
) -> Dict:
    """把若干关键帧渲染为 PNG 存盘，并写 manifest.json（含逐帧哈希）。

    用途：给 git 留可 diff 的中间态，供人工审核与回归比对（SPEC §10）。
    """
    os.makedirs(out_dir, exist_ok=True)
    entries: List[Dict] = []
    for t in times:
        png = render_frame(project, t, "skia", width, height, bg)
        name = f"t{t:08.3f}.png"
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(png)
        entries.append({"t": float(t), "file": name, "sha256": frame_hash(png)})

    manifest = {
        "label": label or getattr(project, "seed", ""),
        "seed": getattr(project, "seed", ""),
        "style": getattr(project, "style", ""),
        "size": [int(width or project.width), int(height or project.height)],
        "frames": entries,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest
