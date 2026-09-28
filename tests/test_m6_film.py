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


# ═══════════════════ 故事片（叙事 + 大动幅 + 重彩）═══════════════════
STORY = os.path.join(ROOT, "projects", "lonely_boat_story")


def _story():
    return load_project(STORY)


def test_story_project_shape():
    proj = _story()
    assert proj.duration == 10.0 and proj.fps == 30
    assert int(round(proj.duration * proj.fps)) == 300
    assert len(proj.groups) == 16
    assert len(proj.tints) == 16, "每个实例都应有自己的色调"
    assert proj.camera is not None
    assert {t.channel for t in proj.camera.tracks} == {
        "translate", "scale", "rotate", "shake", "flash"
    }
    # 每个实例都参与「落墨」（线条生长），这是第一幕的骨架
    assert all(proj.anims[i].track("draw") is not None for i in proj.iids)


def test_story_ink_draws_itself_on():
    """第一幕的硬指标：画面从**近乎空白**被一笔一笔画满。

    刻意用**几何量（笔画总长）**判定而不是像素：像素会被纸纹/雾化/画框这些层污染
    （首版把整片纸纹算成"墨"，t=0 直接测出 65%）。几何量是精确的，且不依赖渲染。
    """
    from spolvero.animation.film import scene_at
    from spolvero.core.primitives import InkDot, InkShape
    from spolvero.core.scene import flatten_all

    proj = _story()

    def stroke_len(t):
        total = 0.0
        for lf in flatten_all(scene_at(proj, t)):
            if isinstance(lf, InkDot):
                total += lf.r  # 点按半径计，生长时半径也按比例缩
                continue
            pts = lf.ring if isinstance(lf, InkShape) else lf.points
            for a, b in zip(pts, pts[1:]):
                total += ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
        return total

    early = stroke_len(0.0)
    mid = stroke_len(2.2)
    done = stroke_len(4.6)
    assert early < 20.0, f"t=0 应近乎空白（只剩点半径），实际笔画长 {early:.1f}"
    assert early < mid < done, f"落墨应中途推进：0.0→{early:.1f} 2.2→{mid:.1f} 4.6→{done:.1f}"
    assert done > 10000.0, f"t=4.6 应已画满，实际仅 {done:.1f}"
    seq = [stroke_len(t) for t in (0.9, 1.5, 2.2, 3.0, 3.8, 4.6)]
    assert seq == sorted(seq), f"落墨进度出现倒退：{[round(v) for v in seq]}"


def test_shake_is_per_frame_and_deterministic():
    from spolvero.animation.film import shake_offset

    proj = _story()
    amp = proj.camera.shake(6.1)
    assert amp > 0, "6.1s 应处于冲击抖动区"
    a = [shake_offset(6.0 + i / 30.0, amp, 30) for i in range(6)]
    assert len(set(a)) == len(a), "抖动必须逐帧取新值，否则看起来像晕船"
    assert a == [shake_offset(6.0 + i / 30.0, amp, 30) for i in range(6)], "抖动须可复现"
    assert shake_offset(3.0, 0.0, 30) == (0.0, 0.0)


def test_flash_overlay_at_cut_points():
    from spolvero.animation.film import flash_overlay

    proj = _story()
    assert flash_overlay(proj, 0.0) is not None, "开场应闪纸色"
    assert flash_overlay(proj, 6.0) is not None, "第二幕切点应闪一下"
    assert flash_overlay(proj, 3.0) is None, "平稳段不应有曝光闪烁"


def test_reveal_geometry_contract():
    """draw=0 必须真的不可见（可见性），draw=1 必须与原节点同一对象（零开销）。"""
    from spolvero.animation.film import reveal
    from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
    from spolvero.core.transform import Transform
    from spolvero.core.types import Point

    line = InkLine(points=(Point(0, 0), Point(10, 0), Point(20, 5)), ink=0.3)
    assert reveal(line, 1.0) is line
    assert len(reveal(line, 0.0).points) == 1, "draw=0 应退化为单点（不可见）"
    # 两段折线（弧长 10 + 11.18）：半程落在第二段上，端口点 + 一个截断点
    half = reveal(line, 0.5)
    assert len(half.points) == 3
    assert abs(half.points[-1].x - 10.0 - 10.0 * ((0.5 * 21.1803 - 10.0) / 11.1803)) < 1e-3
    # 单段线半程应精确停在弧长中点
    seg = InkLine(points=(Point(0, 0), Point(10, 0)), ink=0.3)
    h2 = reveal(seg, 0.5)
    assert len(h2.points) == 2 and abs(h2.points[-1].x - 5.0) < 1e-9

    ring = InkShape(
        ring=(Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)), ink=0.5, fill=True
    )
    assert reveal(ring, 1.0) is ring
    mid = reveal(ring, 0.5)
    assert isinstance(mid, InkLine) and not mid.closed, "填充形生长中应以开放折线勾出"
    assert reveal(ring, 0.0).points.__len__() == 1

    dot = InkDot(pos=Point(1, 1), r=8.0, ink=0.2)
    assert reveal(dot, 0.5).r == 4.0
    assert reveal(dot, 0.0).r == 0.0

    g = Group((line, dot), Transform.translate(3, 4))
    assert isinstance(reveal(g, 0.5), Group)


def test_draw_absent_means_fully_drawn():
    """未声明 draw 的实例必须照常显示（向后兼容），否则老工程会整片消失。"""
    from spolvero.animation.track import AnimSet, Key, Track

    a = AnimSet((Track("draw", (Key(0.0, (0.4,)),)),))
    assert a.draw(0.0) == 0.4
    assert AnimSet(()).draw(0.0) == 1.0


def test_loop_film_has_no_draw_channel_regression():
    """循环片没加 draw，渲染结果不应受本次改动影响（除了相机抖动/闪光的缺省无操作）。"""
    proj = load_project(FILM)
    assert all(proj.anims[i].draw(0.0) == 1.0 for i in proj.iids)
    assert proj.camera is None


def test_story_is_narrative_not_loop():
    """叙事片的契约与循环片相反：首末姿态**必须**不同，否则等于没有故事。"""
    proj = _story()
    assert not _loop_closed(proj, proj.duration)
    assert scene_at(proj, 0.0) != scene_at(proj, proj.duration)


def test_story_boat_traverses_most_of_the_canvas():
    """动幅硬指标：主舟自身横移 ≥80% 画布宽度，且**自身**轨迹单向不回头。

    只看屏幕空间会误判：相机有轻微摇摆（推轨时左右微调），会让屏幕坐标瞬时回退 1px 级，
    那是镜头手感而非主体倒退。所以单调性判在主体自身位移上，跨度则两边都卡。
    """
    proj = _story()
    tr = proj.anims["boat_main"].track("translate")
    assert tr is not None
    own = [tr.sample(i / 30.0)[0] for i in range(300)]
    assert own == sorted(own), "主舟自身位移应单向渡江"
    assert own[-1] - own[0] >= 0.80 * proj.width, f"主舟自身横移仅 {own[-1] - own[0]:.0f}px"

    idx = proj.iids.index("boat_main")

    def screen_x(t):
        outer = scene_at(proj, t)[0]  # 相机合成层
        m = outer.transform.compose(outer.children[idx].transform)
        return m(0.0, 0.0)[0]

    xs = [screen_x(i / 30.0) for i in range(300)]
    assert max(xs) - min(xs) >= 0.80 * proj.width, f"屏幕空间横移仅 {max(xs) - min(xs):.0f}px"
    assert xs[0] < 0.05 * proj.width and xs[-1] > 0.75 * proj.width, "应自画外左侧入画、收于右侧"


def test_story_has_no_micro_motion_only():
    """回归用户反馈「基本没动」：相邻采样帧必须有可观差异。"""
    from spolvero.api import render_frame_at
    from spolvero.render.skia import png_to_rgb

    proj = _story()
    st = get_style("azurite")

    def diff(a, b):
        ra, rb = png_to_rgb(a), png_to_rgb(b)
        return sum(
            1
            for i in range(0, len(ra), 3)
            if abs(ra[i] - rb[i]) + abs(ra[i + 1] - rb[i + 1]) + abs(ra[i + 2] - rb[i + 2]) > 28
        ) / (len(ra) // 3)

    a = render_frame_at(proj, 0.0, "skia", st)
    b = render_frame_at(proj, 5.0, "skia", st)
    assert diff(a, b) > 0.02, f"半程间画面仅变了 {diff(a, b) * 100:.2f}%，仍属微动"


def test_story_is_vivid_not_gray():
    from spolvero.api import render_frame_at
    from spolvero.render.skia import png_to_rgb

    proj = _story()
    st = get_style("azurite")
    rgb = png_to_rgb(render_frame_at(proj, 7.0, "skia", st))
    bg = st.paper_rgb
    chroma, n = 0, 0
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 40:
            chroma += max(r, g, b) - min(r, g, b)
            n += 1
    assert n > 0
    # 灰度版实测色度 ≈1.0；墨色极深时通道极差会被压小，故只要明显大于灰度即可
    assert chroma / n > 15, f"平均色度仅 {chroma / n:.1f}，谈不上鲜亮"


def test_story_validation_passes_across_the_shot():
    from spolvero.validation.validator import validate_project

    proj = _story()
    for t in (None, 2.5, 5.0, 7.5):
        rep = validate_project(proj, t)
        assert rep.passed, f"t={t}: {rep.render_text()}"
        assert rep.warnings() == [], f"t={t}: {[i.code for i in rep.warnings()]}"


def test_story_encodes_and_exports():
    pytest.importorskip("lottie")
    proj = _story()
    st = get_style("azurite")
    out = os.path.join(tempfile.mkdtemp(), "story.mp4")
    info = encode_film(proj, out, style=st, fps=6, duration=1.0)
    assert info["frames"] == 6 and os.path.getsize(out) > 0
    lot = os.path.join(tempfile.mkdtemp(), "story.json")
    linfo = export_lottie(proj, lot, style=st)
    assert linfo["frames"] == 300 and linfo["layers"] == 16
