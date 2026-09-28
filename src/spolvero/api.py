"""Spolvero 稳定函数边界（M6a 定死；SPEC §3 派生约束「UI 层零业务逻辑」）。

**本模块是唯一稳定 API。** `cli.py`、M6c 的 Flask 界面、任何脚本都只允许调用这里，
不得直接组合 core/render/dsl/transcribe 的内部件。理由：渲染与转录必须能在完全无 UI
的情况下独立运行；UI 一旦内嵌业务逻辑，等价于破坏「离线渲染铁律」（SPEC §11）。

本模块自身只做「编排 + 类型转换」，不含算法（算法在内核各包里）。

M6a 已实现                 M6b 待实现（签名先定死，避免后续改动破坏边界）
  load_project               transcribe_style
  render_project             compose_styles
  render_frame_at            
  check_project
  encode_film
  snapshot_frames
  list_styles / get_style
  save_style / render_preview
  export_lottie / import_lottie
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from spolvero.dsl.model import Project
from spolvero.styles.asset import StyleAsset

Bg = Tuple[int, int, int]


# ───────────────────────── 工程 ─────────────────────────
def load_project(dir_path: str) -> Project:
    """读工程目录（project/style/components/timeline.yaml）→ Project。"""
    from spolvero.dsl.parser import load_project as _load

    return _load(dir_path)


# ───────────────────────── 渲染 ─────────────────────────
def _styled_groups(project: Project, style: Optional[StyleAsset], t: Optional[float]):
    from spolvero.animation.film import scene_at
    from spolvero.styles.apply import recolor_all

    groups = scene_at(project, t) if t is not None else list(project.groups)
    if style is not None:
        # 相机可能把整个场景包成单个 Group：此时实例与 iid 的对应关系仍按 project.iids 逐项着色
        tints = getattr(project, "tints", None) or {}
        if len(groups) == len(project.groups):
            groups = recolor_all(groups, style, tints, project.iids)
        else:
            from spolvero.styles.apply import recolor

            groups = [recolor(g, style) for g in groups]
    return groups


def _bg_of(project: Project, style: Optional[StyleAsset]) -> Bg:
    return style.paper_rgb if style is not None else project.background


def _fx_of(style: Optional[StyleAsset], t: float):
    """作画痕迹层的逐帧参数（boil 换帧也在里面算）。无风格或全零时返回 None。"""
    if style is None:
        return None
    fx = style.effects.runtime(t, style.paper_rgb)
    return None if fx.is_noop else fx


def render_project(
    project: Project,
    backend: str = "skia",
    style: Optional[StyleAsset] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
):
    """渲染工程的静态首帧。backend='svg' 返回 str，'skia' 返回 PNG bytes。"""
    from spolvero.render.backend import render

    return render(
        _styled_groups(project, style, None),
        backend=backend,
        width=int(width or project.width),
        height=int(height or project.height),
        bg=_bg_of(project, style),
        fx=_fx_of(style, 0.0),
    )


def render_frame_at(
    project: Project,
    t: float,
    backend: str = "skia",
    style: Optional[StyleAsset] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
):
    """渲染 t 时刻的帧（含线条生长、相机抖动与曝光闪烁）。"""
    from spolvero.animation.film import flash_overlay
    from spolvero.render.backend import render

    return render(
        _styled_groups(project, style, t),
        backend=backend,
        width=int(width or project.width),
        height=int(height or project.height),
        bg=_bg_of(project, style),
        overlay=flash_overlay(project, t),
        fx=_fx_of(style, t),
    )


# ───────────────────────── 校验 ─────────────────────────
def check_project(project: Project):
    """三重校验（几何 / 相似度 / 构图四约束 + 扩展 2），返回 ValidationReport。"""
    from spolvero.validation.validator import validate_project

    return validate_project(project)


# ───────────────────────── 成片 ─────────────────────────
def encode_film(
    project: Project,
    out_path: str,
    style: Optional[StyleAsset] = None,
    fps: Optional[int] = None,
    duration: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    crf: int = 18,
) -> Dict:
    """渲染全片并合成 H.264 MP4；返回合成信息（含逐帧哈希）。"""
    from spolvero.animation.film import encode_mp4

    if style is None:
        return encode_mp4(project, out_path, fps, duration, width, height, None, crf)
    return encode_mp4_styled(project, out_path, style, fps, duration, width, height, crf)


def encode_mp4_styled(project, out_path, style, fps, duration, width, height, crf) -> Dict:
    """带风格着色的成片（`animation.film.encode_mp4` 的无风格版本保持内核纯净）。"""
    from spolvero.animation.film import frame_hash, iter_frames

    info = _encode_styled_frames(project, out_path, style, fps, duration, width, height, crf)
    return info


def _encode_styled_frames(project, out_path, style, fps, duration, width, height, crf) -> Dict:
    import imageio_ffmpeg

    from spolvero.animation.film import _resolve_timeline, frame_hash
    from spolvero.render.skia import png_to_rgb

    fps, dur = _resolve_timeline(project, fps, duration)
    w = int(width or project.width)
    h = int(height or project.height)
    if w % 2 or h % 2:
        raise ValueError(f"H.264 yuv420p 要求宽高为偶数，当前 {w}x{h}")

    import os

    out_path = os.path.abspath(out_path)
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)

    writer = imageio_ffmpeg.write_frames(
        out_path, (w, h), fps=fps, codec="libx264", pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p", macro_block_size=1, ffmpeg_log_level="error",
        output_params=["-crf", str(crf), "-movflags", "+faststart"],
    )
    writer.send(None)
    n = 0
    hashes: List[str] = []
    try:
        total = int(round(dur * fps))
        for i in range(total):
            t = i / fps
            png = render_frame_at(project, t, "skia", style, w, h)
            writer.send(png_to_rgb(png))
            hashes.append(frame_hash(png))
            n += 1
    finally:
        writer.close()

    from spolvero.animation.film import _loop_closed

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
        "style": style.id if style else "",
    }


def snapshot_frames(
    project: Project,
    out_dir: str,
    times: Sequence[float] = (0.0,),
    style: Optional[StyleAsset] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    label: str = "",
) -> Dict:
    """关键帧快照 + manifest.json（含逐帧 sha256）。"""
    import json
    import os

    from spolvero.animation.film import frame_hash

    os.makedirs(out_dir, exist_ok=True)
    entries: List[Dict] = []
    for t in times:
        png = render_frame_at(project, t, "skia", style, width, height)
        name = f"t{float(t):08.3f}.png"
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(png)
        entries.append({"t": float(t), "file": name, "sha256": frame_hash(png)})

    manifest = {
        "label": label or project.seed,
        "seed": project.seed,
        "style": style.id if style else project.style,
        "size": [int(width or project.width), int(height or project.height)],
        "frames": entries,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


# ───────────────────────── 风格预设 ─────────────────────────
def list_styles(root: str = "styles") -> List[StyleAsset]:
    from spolvero.styles import list_styles as _ls

    return _ls(root)


def get_style(style_id: str, root: str = "styles") -> Optional[StyleAsset]:
    from spolvero.styles import get_style as _gs

    return _gs(style_id, root)


def save_style(asset: StyleAsset, root: str = "styles", write_preview: bool = True) -> str:
    from spolvero.styles import save_style as _ss

    return _ss(asset, root, write_preview)


def render_preview(asset: StyleAsset, knobs: Optional[Dict] = None, size=(720, 480)) -> str:
    """返回预览 **SVG 字符串**（界面滑杆实时重渲染直接替换 DOM）。"""
    from spolvero.styles import render_preview as _rp

    return _rp(asset, knobs, size)


def render_preview_png(asset: StyleAsset, knobs: Optional[Dict] = None, size=(720, 480)) -> bytes:
    from spolvero.styles import render_preview_png as _rpp

    return _rpp(asset, knobs, size)


# ───────────────────────── Lottie（M6d）─────────────────────────
def export_lottie(project: Project, out_path: str, style: Optional[StyleAsset] = None) -> Dict:
    from spolvero.lottie.export import export_lottie as _ex

    return _ex(project, out_path, style)


def import_lottie(path: str) -> List:
    from spolvero.lottie.importer import import_lottie as _im

    return _im(path)


# ───────────────────────── M6b：风格转录器（签名定死，实现待 M6b）─────────────────────────
def transcribe_style(sources: Sequence[str], *, name: Optional[str] = None, ai: bool = True) -> StyleAsset:
    """参考画 → 风格预设资产（M6b 实现）。"""
    raise NotImplementedError(
        "M6b 未实现：风格转录器（三层确定性提取 / 三档降档 / sidecar 证据）"
    )


def compose_styles(parts: Sequence[StyleAsset], *, name: Optional[str] = None) -> StyleAsset:
    """多图合成：分层选取 + 同层合并（M6b 实现）。"""
    raise NotImplementedError("M6b 未实现：多图风格合成")
