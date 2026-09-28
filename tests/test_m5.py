"""M5 时序动画与成片测试。

覆盖：
  缓动      —— 端点严格、单调、纯多项式回退
  关键帧轨  —— 维度/升序校验、区间外 hold、区间内缓动插值
  变换增量  —— translate / rotate / scale 绕锚点正确复合
  逐帧求值  —— scene_at 与基准姿态的关系、满环闭合、独立于帧序
  成片      —— iter_frames 帧数与确定性、encode_mp4 产出 H.264、snapshot manifest
  DSL 接入  —— anim 解析、缺 duration 报错、iid 重复报错
"""

from __future__ import annotations

import os
import tempfile

import pytest

from spolvero.animation import (
    EASINGS,
    AnimSet,
    Key,
    Track,
    encode_mp4,
    frame_hash,
    get_easing,
    iter_frames,
    parse_anim,
    scene_at,
)
from spolvero.animation.film import shift_ink
from spolvero.animation.track import merge_anim
from spolvero.core.primitives import Group, InkLine, InkShape
from spolvero.core.transform import Transform
from spolvero.core.types import Point
from spolvero.dsl.parser import DSLValidationError, load_project

# ───────────────────────── 确定性三角函数（动画旋转的地基）─────────────────────────
def test_dmath_is_accurate_across_full_domain():
    """回归：早期 Taylor 直接作用于 [-π,π] 的角，cos(π) 误差 ~2.4e-2（180° 旋转可见失真）。"""
    import math

    from spolvero.core.dmath import dcos, dsin

    worst_c = worst_s = 0.0
    for i in range(-720, 721):
        x = i / 180.0 * math.pi
        worst_c = max(worst_c, abs(dcos(x) - math.cos(x)))
        worst_s = max(worst_s, abs(dsin(x) - math.sin(x)))
    assert worst_c < 1e-9, worst_c
    assert worst_s < 1e-9, worst_s
    assert dcos(math.pi) == -1.0 and dsin(math.pi) == 0.0


# ───────────────────────── 缓动 ─────────────────────────
def test_easing_endpoints_and_monotonic():
    for name, fn in EASINGS.items():
        assert abs(fn(0.0) - 0.0) < 1e-12, name
        assert abs(fn(1.0) - 1.0) < 1e-12, name
        prev = -1.0
        for i in range(21):
            v = fn(i / 20.0)
            assert v >= prev - 1e-12, f"{name} 非单调 @{i}"
            prev = v


def test_unknown_easing_falls_back_to_smooth():
    assert get_easing("nope")(0.3) == get_easing("smooth")(0.3)


def test_easing_is_bitwise_deterministic():
    assert [EASINGS["smooth"](i / 97.0) for i in range(98)] == [
        EASINGS["smooth"](i / 97.0) for i in range(98)
    ]


# ───────────────────────── 关键帧轨 ─────────────────────────
def test_track_rejects_bad_arity_and_order():
    with pytest.raises(ValueError):
        Track("translate", (Key(0.0, (1.0,)),))  # translate 需 2 维
    with pytest.raises(ValueError):
        Track("rotate", (Key(1.0, (0.0,)), Key(0.0, (90.0,))))  # 时间未升序
    with pytest.raises(ValueError):
        Track("wobble", (Key(0.0, (0.0,)),))


def test_track_holds_outside_range_and_interpolates_inside():
    tr = Track("rotate", (Key(1.0, (0.0,)), Key(2.0, (100.0,))), ease="linear")
    assert tr.sample(0.0) == (0.0,)  # 前段 hold
    assert tr.sample(3.0) == (100.0,)  # 后段 hold
    assert tr.sample(1.5) == (50.0,)  # 线性中点
    assert tr.span == (1.0, 2.0)


def test_track_single_key_is_constant():
    tr = Track("scale", (Key(0.0, (2.0,)),))
    assert tr.sample(-5.0) == (2.0,) and tr.sample(99.0) == (2.0,)


def test_parse_anim_and_merge():
    a = parse_anim(
        [
            {"channel": "translate", "ease": "linear", "keys": [{"t": 0, "v": [0, 0]}, {"t": 1, "v": [10, 5]}]},
            {"channel": "ink_shift", "keys": [{"t": 0, "v": 0.1}]},
        ]
    )
    assert a.value("translate", 1.0) == (10.0, 5.0)
    assert a.ink_shift(0.0) == 0.1
    assert a.duration == 1.0

    b = parse_anim([{"channel": "ink_shift", "keys": [{"t": 0, "v": -0.2}]}])
    merged = merge_anim(a, b)
    assert merged.ink_shift(0.0) == -0.2
    assert merged.value("translate", 1.0) == (10.0, 5.0)  # 未覆盖通道保留


# ───────────────────────── 变换增量 ─────────────────────────
def test_translate_delta_only_shifts_position():
    a = parse_anim([{"channel": "translate", "ease": "linear", "keys": [{"t": 0, "v": [0, 0]}, {"t": 2, "v": [30, -12]}]}])
    m = a.delta_transform(1.0, ax=100.0, ay=50.0)
    assert (m.e, m.f) == (15.0, -6.0)
    assert (m.a, m.d) == (1.0, 1.0)


def test_rotate_delta_is_about_anchor():
    a = parse_anim([{"channel": "rotate", "ease": "linear", "keys": [{"t": 0, "v": 0}, {"t": 2, "v": 180}]}])
    m = a.delta_transform(2.0, ax=100.0, ay=50.0)
    # 绕锚点旋转：锚点自身不动
    x, y = m(100.0, 50.0)
    assert abs(x - 100.0) < 1e-6 and abs(y - 50.0) < 1e-6
    # 锚点右方 10px 处绕 180° 后落到左方 10px
    x2, y2 = m(110.0, 50.0)
    assert abs(x2 - 90.0) < 1e-3 and abs(y2 - 50.0) < 1e-3


def test_scale_delta_is_about_anchor():
    a = parse_anim([{"channel": "scale", "keys": [{"t": 0, "v": 2.0}]}])
    m = a.delta_transform(0.0, ax=10.0, ay=10.0)
    assert m(10.0, 10.0) == (10.0, 10.0)
    assert m(20.0, 10.0) == (30.0, 10.0)


# ───────────────────────── ink 偏移 ─────────────────────────
def test_shift_ink_clamps_and_is_recursive():
    node = Group(
        (
            Group((InkLine(points=(Point(0, 0), Point(1, 1)), ink=0.95),), Transform.identity()),
            InkShape(ring=(Point(0, 0), Point(1, 0), Point(0, 1)), ink=0.05),
        ),
        Transform.identity(),
    )
    out = shift_ink(node, 0.3)
    assert out.children[0].children[0].ink == 1.0  # 上钳
    assert out.children[1].ink == 0.35
    out2 = shift_ink(node, -0.3)
    assert out2.children[1].ink == 0.0  # 下钳


# ───────────────────────── 测试工程脚手架 ─────────────────────────
def _components_yaml() -> str:
    """直接复用引擎声明式构件规格，保证与 pattern 构建器参数表完全一致。"""
    import yaml

    from spolvero.components import LONELY_BOAT_COMPONENT_SPECS

    return yaml.safe_dump(LONELY_BOAT_COMPONENT_SPECS, allow_unicode=True, sort_keys=False)


def _tmp_project(timeline: str, duration: str = "duration: 1.0\n", size=(64, 48)) -> str:
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "project.yaml"), "w", encoding="utf-8") as f:
        f.write(
            f'seed: anim-test\nwidth: {size[0]}\nheight: {size[1]}\nfps: 12\n'
            f'{duration}style: eastern_minimal\nbackground: "#F7F5F0"\n'
        )
    with open(os.path.join(d, "style.yaml"), "w", encoding="utf-8") as f:
        f.write("name: eastern_minimal\n")
    with open(os.path.join(d, "components.yaml"), "w", encoding="utf-8") as f:
        f.write(_components_yaml())
    with open(os.path.join(d, "timeline.yaml"), "w", encoding="utf-8") as f:
        f.write(timeline)
    return d


ANIM_TIMELINE = """\
items:
  - component: boat
    iid: b1
    overrides: {length: 40, hull_ink: 0.2}
    transform: {translate: [32, 24]}
    anim:
      - channel: translate
        ease: linear
        keys:
          - {t: 0.0, v: [0, 0]}
          - {t: 1.0, v: [0, 0]}
  - component: boat
    iid: b2
    overrides: {length: 40, hull_ink: 0.2}
    transform: {translate: [32, 24]}
    anim:
      - channel: translate
        ease: linear
        keys:
          - {t: 0.0, v: [-10, 0]}
          - {t: 1.0, v: [10, 0]}
"""


# ───────────────────────── 逐帧求值 ─────────────────────────
def test_scene_at_moves_only_animated_instances():
    proj = load_project(_tmp_project(ANIM_TIMELINE))
    t0 = scene_at(proj, 0.0)
    t1 = scene_at(proj, 1.0)
    # b1 静止
    assert t0[0].transform.e == t1[0].transform.e
    # b2 平移 -10 → +10
    assert t0[1].transform.e == 22.0
    assert t1[1].transform.e == 42.0


def test_scene_at_is_independent_of_frame_order():
    proj = load_project(_tmp_project(ANIM_TIMELINE))
    forward = [scene_at(proj, i / 12.0) for i in range(13)]
    backward = [scene_at(proj, i / 12.0) for i in range(12, -1, -1)][::-1]
    key = lambda nodes: [(n.transform.e, n.transform.f) for n in nodes]
    assert [key(n) for n in forward] == [key(n) for n in backward]


def test_loop_closed_when_first_last_keys_match():
    looped = ANIM_TIMELINE.replace(
        "          - {t: 0.0, v: [-10, 0]}\n          - {t: 1.0, v: [10, 0]}",
        "          - {t: 0.0, v: [-10, 0]}\n          - {t: 1.0, v: [-10, 0]}",
    )
    proj = load_project(_tmp_project(looped))
    assert scene_at(proj, 0.0) == scene_at(proj, proj.duration)


# ───────────────────────── 成片 ─────────────────────────
def test_iter_frames_count_and_determinism():
    proj = load_project(_tmp_project(ANIM_TIMELINE, duration="duration: 0.5\n"))
    run1 = [frame_hash(f) for _i, _t, f in iter_frames(proj, "skia")]
    run2 = [frame_hash(f) for _i, _t, f in iter_frames(proj, "skia")]
    assert len(run1) == 6  # 0.5s × 12fps
    assert run1 == run2


def test_encode_mp4_produces_h264_and_reports_loop():
    proj = load_project(_tmp_project(ANIM_TIMELINE, duration="duration: 0.5\n"))
    out = os.path.join(tempfile.mkdtemp(), "clip.mp4")
    info = encode_mp4(proj, out)
    assert os.path.exists(out) and info["bytes"] > 0
    assert info["frames"] == 6
    assert info["size"] == [64, 48]
    raw = open(out, "rb").read()
    assert b"ftyp" in raw[:64] and b"moov" in raw  # H.264/MP4 封装
    assert info["path"] == out


def test_encode_mp4_rejects_odd_dimensions():
    proj = load_project(_tmp_project(ANIM_TIMELINE, duration="duration: 0.2\n", size=(65, 48)))
    with pytest.raises(ValueError):
        encode_mp4(proj, os.path.join(tempfile.mkdtemp(), "x.mp4"))


def test_snapshot_writes_manifest_with_hashes():
    from spolvero.animation import snapshot

    proj = load_project(_tmp_project(ANIM_TIMELINE))
    d = tempfile.mkdtemp()
    manifest = snapshot(proj, d, times=(0.0, 0.5, 1.0))
    assert len(manifest["frames"]) == 3
    assert os.path.exists(os.path.join(d, "manifest.json"))
    for fr in manifest["frames"]:
        path = os.path.join(d, fr["file"])
        assert os.path.exists(path)
        assert frame_hash(open(path, "rb").read()) == fr["sha256"]


# ───────────────────────── DSL 接入 ─────────────────────────
def test_anim_requires_duration():
    with pytest.raises(DSLValidationError) as ei:
        load_project(_tmp_project(ANIM_TIMELINE, duration=""))
    assert "duration" in str(ei.value)


def test_duplicate_iid_rejected():
    dup = ANIM_TIMELINE.replace("iid: b2", "iid: b1")
    with pytest.raises(DSLValidationError) as ei:
        load_project(_tmp_project(dup))
    assert "重复" in str(ei.value)


def test_bad_channel_rejected():
    bad = ANIM_TIMELINE.replace("channel: translate", "channel: wobble")
    with pytest.raises(DSLValidationError) as ei:
        load_project(_tmp_project(bad))
    assert "anim" in str(ei.value)


def test_static_project_has_no_duration_and_is_not_animated():
    proj = load_project(_tmp_project("items: []\n", duration=""))
    assert proj.duration == 0.0 and not proj.is_animated
    with pytest.raises(ValueError):
        list(iter_frames(proj))
