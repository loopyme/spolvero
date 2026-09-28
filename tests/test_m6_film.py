"""官方示例片集成测试 + 风格资产防漂移（M6 交付验收）。

把「交付物本身就是测试对象」：`projects/lonely_boat_film` 是 M4–M6 的验收样本，
这里锁死它的三条契约：
  1. 校验通过（0 error）；
  2. 每通道首末关键帧同值 → t=duration 姿态 == t=0 姿态 → 循环无缝；
  3. 整链可复跑：H.264 成片 + Lottie L0 导出均可从该工程产出。
另加：`styles/<id>/` 落盘资产必须与引擎内置预设逐字段一致（防两源漂移）。
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from spolvero.animation.film import _loop_closed, scene_at
from spolvero.api import (
    check_project,
    encode_film,
    export_lottie,
    get_style,
    load_project,
    snapshot_frames,
)
from spolvero.styles.asset import StyleAsset
from spolvero.styles.io import load_style_dir
from spolvero.styles.presets import builtin_styles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILM = os.path.join(ROOT, "projects", "lonely_boat_film")
STATIC = os.path.join(ROOT, "projects", "lonely_boat")
STYLES = os.path.join(ROOT, "styles")

EXPECTED_FRAMES = 96  # 24 fps × 4.0 s


def _film():
    return load_project(FILM)


# ───────────────────────── 工程契约 ─────────────────────────
def test_film_project_shape():
    proj = _film()
    assert proj.duration == 4.0 and proj.fps == 24
    assert len(proj.groups) == 10 and len(proj.anims) == 10
    assert proj.iids[0] == "moon" and proj.iids[-1] == "boat_far"
    assert int(round(proj.duration * proj.fps)) == EXPECTED_FRAMES


def test_film_is_same_composition_as_static_piece():
    """成片与静态首片同 seed / 同构图：t=0 时应与静态工程逐字节一致。"""
    from spolvero.api import render_project

    a = render_project(_film(), "skia", style=get_style("eastern_minimal"))
    b = render_project(load_project(STATIC), "skia", style=get_style("eastern_minimal"))
    assert a == b


def test_every_track_starts_and_ends_at_same_value():
    """循环契约：不满足则每次回卷都会「跳一下」。"""
    for iid, anim in _film().anims.items():
        for tr in anim.tracks:
            first, last = tr.keys[0].v, tr.keys[-1].v
            assert first == last, f"{iid}.{tr.channel} 首末关键帧不同值: {first} vs {last}"


def test_loop_is_closed_and_pose_at_duration_equals_zero():
    proj = _film()
    assert _loop_closed(proj, proj.duration)
    assert scene_at(proj, 0.0) == scene_at(proj, proj.duration)


def test_film_passes_validation_with_style_constraints():
    rep = check_project(_film())
    assert rep.passed, rep.render_text()
    assert rep.warnings() == []


def test_film_motion_is_not_mirrored():
    """中间关键帧刻意不等距：否则 t 与 4-t 姿态相同，96 帧只剩一半画面。"""
    proj = _film()
    a = scene_at(proj, 1.0)
    b = scene_at(proj, 3.0)
    assert [g.transform.e for g in a] != [g.transform.e for g in b]


# ───────────────────────── 整链可复跑 ─────────────────────────
def test_film_encodes_mp4_end_to_end():
    out = os.path.join(tempfile.mkdtemp(), "film.mp4")
    info = encode_film(_film(), out, style=get_style("eastern_minimal"),
                       fps=6, duration=0.5)
    assert info["frames"] == 3 and os.path.getsize(out) > 0
    assert open(out, "rb").read()[:64].find(b"ftyp") >= 0


def test_film_exports_baked_lottie():
    pytest.importorskip("lottie")
    out = os.path.join(tempfile.mkdtemp(), "film.json")
    info = export_lottie(_film(), out, style=get_style("eastern_minimal"))
    assert info["frames"] == EXPECTED_FRAMES
    doc = json.load(open(out, encoding="utf-8"))
    assert doc["op"] == EXPECTED_FRAMES and len(doc["layers"]) == 10
    animated = [l for l in doc["layers"] if l["ks"]["p"]["a"] == 1]
    assert len(animated) == 10, "所有实例都带动画，应全部烘焙为关键帧"
    assert all(len(l["ks"]["p"]["k"]) == EXPECTED_FRAMES for l in animated)


def test_film_snapshot_manifest_matches_files():
    d = tempfile.mkdtemp()
    man = snapshot_frames(_film(), d, (0.0, 2.0), style=get_style("eastern_minimal"))
    assert len(man["frames"]) == 2
    from spolvero.animation.film import frame_hash

    for fr in man["frames"]:
        raw = open(os.path.join(d, fr["file"]), "rb").read()
        assert frame_hash(raw) == fr["sha256"]


# ───────────────────────── 风格资产防漂移 ─────────────────────────
def test_repo_style_assets_match_builtin_presets():
    """styles/<id>/ 是落盘资产，presets.py 是引擎内置基线——两者必须逐字段一致。"""
    for sid, asset in builtin_styles().items():
        d = os.path.join(STYLES, sid)
        assert os.path.isdir(d), f"缺少落盘预设 {sid}；跑 `spol style export`"
        on_disk = load_style_dir(d)
        assert on_disk.style_dict() == asset.style_dict(), f"{sid} style.yaml 与内置预设漂移"
        assert on_disk.constraints == asset.constraints, f"{sid} constraints.yaml 漂移"
        assert os.path.exists(os.path.join(d, "preview.png"))


def test_repo_style_preview_is_engine_rendered():
    """缩略图必须是引擎自渲染（尺寸即预览尺寸），不得是参考画原图。"""
    import struct

    for sid in builtin_styles():
        p = os.path.join(STYLES, sid, "preview.png")
        with open(p, "rb") as f:
            head = f.read(33)
        assert head[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", head[16:24])
        assert (w, h) == (720, 480), f"{sid} 缩略图尺寸异常: {w}x{h}"


def test_style_asset_roundtrip_equality():
    for sid, asset in builtin_styles().items():
        assert StyleAsset.from_dicts(asset.style_dict(), asset.constraints_dict()).style_dict() \
            == asset.style_dict()
