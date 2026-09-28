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
from spolvero.core.rng import derive
from spolvero.core.scene import Node
from spolvero.core.transform import Transform
from spolvero.core.types import Point
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


# ───────────────────────── 线条生长（笔画自己画出来）─────────────────────────
def reveal(node: Node, frac: float) -> Node:
    """按**弧长比例**截断几何，使笔画看起来是被"画"出来的。

    实现位置是刻意的：**在场景求值期截断，不是渲染器特性**。
    这样四原语、渲染器、命门 3（控制点数恒定）全都不需要动——`draw` 是"可见性"，
    不是参数空间里的形变，出了这一帧的几何就丢掉。

    语义：
      frac ≥ 1   保持原样（含 fill 与闭合）
      frac < 1   ink_line/闭合线 → 截断后的开放折线（观感即"勾线"）
                 ink_shape（填充形）→ 先以轮廓勾出，画满后再落墨成面
                 ink_dot → 半径按 frac 长出（"点上去"）
    """
    if frac >= 1.0:
        return node
    if frac <= 0.0:
        frac = 0.0
    if isinstance(node, Group):
        return Group(tuple(reveal(c, frac) for c in node.children), node.transform)
    if isinstance(node, InkDot):
        return replace(node, r=node.r * frac)
    if isinstance(node, InkShape):
        pts = _trim([p.xy() for p in node.ring], frac, closed=True)
        # 生长中一律以**开放折线**呈现：frac<1 时还没落墨成面，只勾线
        return InkLine(
            points=tuple(Point(x, y) for x, y in pts),
            width=node.width,
            ink=node.ink,
            closed=False,
            color=node.color,
        )
    if isinstance(node, InkLine):
        pts = _trim([p.xy() for p in node.points], frac, closed=bool(node.closed))
        return replace(node, points=tuple(Point(x, y) for x, y in pts), closed=False)
    return node


def _trim(pts: List[Tuple[float, float]], frac: float, closed: bool) -> List[Tuple[float, float]]:
    """按累计弧长取前 frac 段，**至少返回 1 个点**。

    只有 1 个点时不构成任何可见笔迹（skia 只 moveTo、SVG polyline 单点均不绘制），
    这正是 frac=0 应有的效果——若在此处提前 return 原节点，笔画会在 draw=0 时照样画满。
    纯 +-*/，确定性。
    """
    seq = list(pts) + [pts[0]] if (closed and len(pts) >= 3) else list(pts)
    if len(seq) < 2:
        return list(pts)[:1]
    segs = []
    total = 0.0
    for i in range(len(seq) - 1):
        dx = seq[i + 1][0] - seq[i][0]
        dy = seq[i + 1][1] - seq[i][1]
        ln = (dx * dx + dy * dy) ** 0.5
        segs.append(ln)
        total += ln
    if total <= 0.0 or frac <= 0.0:
        return [seq[0]]
    target = frac * total
    out = [seq[0]]
    acc = 0.0
    for i, ln in enumerate(segs):
        if acc + ln <= target:
            out.append(seq[i + 1])
            acc += ln
            continue
        u = (target - acc) / ln if ln > 0 else 0.0
        a, b = seq[i], seq[i + 1]
        out.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
        break
    return out


def shake_offset(t: float, amp: float, fps: int = 24, salt: str = "camera-shake"):
    """相机抖动的逐帧整数偏移（复用命门 1 的派生哈希，确定性、与帧序无关）。

    刻意**逐帧**取新值（k = floor(t·fps)）：连续插值的抖动看起来像晕船，一格一抖才像手拍/冲击。
    """
    if amp <= 0.0:
        return (0.0, 0.0)
    k = int(t * fps)
    ox = (derive(salt, str(k), "x") - 0.5) * 2.0 * amp
    oy = (derive(salt, str(k), "y") - 0.5) * 2.0 * amp
    return (ox, oy)


def flash_overlay(project, t: float):
    """曝光闪烁 → 全屏叠加色。>0 闪向纸色、<0 闪向黑。返回 (r,g,b,alpha) 或 None。"""
    cam = getattr(project, "camera", None)
    if cam is None or not getattr(cam, "tracks", None):
        return None
    v = cam.flash(t)
    if v == 0.0:
        return None
    from spolvero.styles import get_style

    style = get_style(getattr(project, "style", "") or "")
    base = style.paper_rgb if style is not None else (255, 255, 255)
    if v > 0:
        rgb = base
    else:
        rgb = (0, 0, 0)
    return (rgb[0], rgb[1], rgb[2], min(1.0, abs(v)))


# ───────────────────────── 逐帧求值 ─────────────────────────
def scene_at(project, t: float) -> List[Group]:
    """求 t 时刻的场景。

    三层：先按实例施加各自的动画增量（含 `draw` 线条生长），
    再在最外层套**全局相机**（绕画布中心的推/拉/摇 + 逐帧抖动）——
    对应动漫的镜头调度：主体的位移负责"叙事"，相机的位移负责"观感"。
    """
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
        children = g.children
        frac = anim.draw(t)
        if frac < 1.0:
            children = tuple(reveal(c, frac) for c in children)
        node = Group(children, delta.compose(g.transform))
        s = anim.ink_shift(t)
        if s:
            node = Group(tuple(shift_ink(c, s) for c in node.children), node.transform)
        out.append(node)

    cam = getattr(project, "camera", None)
    if cam is not None and getattr(cam, "tracks", None):
        px, py = project.width / 2.0, project.height / 2.0
        m = cam.delta_transform(t, px, py)
        amp = cam.shake(t)
        if amp > 0.0:
            ox, oy = shake_offset(t, amp, int(getattr(project, "fps", 24) or 24))
            m = Transform.translate(ox, oy).compose(m)
        if m != Transform.identity():
            return [Group(tuple(out), m)]
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
    fx=None,
):
    w = int(width or project.width)
    h = int(height or project.height)
    b = bg if bg is not None else project.background
    return render(
        scene_at(project, t),
        backend=backend,
        width=w,
        height=h,
        bg=b,
        overlay=flash_overlay(project, t),
        fx=fx,
    )


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
        # =1 关闭 imageio-ffmpeg 的 macro-block 补齐：否则 1600x900 会被静默改成
        # 1600x912（900 不是 16 的倍数），成片尺寸与画布不一致。yuv420p 只要求偶数边长。
        macro_block_size=1,
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
