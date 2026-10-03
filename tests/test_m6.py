"""M6a 风格预设 + M6d Lottie 对接测试。

M6a 覆盖：资产模型与 schema_version、三档灰度→RGB 映射、点染规则、
          灰度风格恒等（不破坏既有 golden）、彩色风格确定性、约束接入校验器、
          扩展 2 构图指纹、预览（SVG 字符串 + PNG）、api.py 边界、落盘 I/O 与版本守卫。
M6d 覆盖：L0 导出结构与可被 python-lottie 解析、动画层烘焙成关键帧、
          L1 导入回四原语且控制点恒定（命门 3）、错误路径。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile

import pytest

from spolvero.api import (
    check_project,
    export_lottie,
    get_style,
    import_lottie,
    list_styles,
    load_project,
    render_preview,
    render_project,
    save_style,
)
from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.transform import Transform
from spolvero.core.types import Point
from spolvero.lottie import import_summary
from spolvero.styles import StyleIOError, load_style_dir
from spolvero.styles.apply import ink_to_rgb, is_accent_leaf, parse_hex, recolor
from spolvero.styles.asset import BASE_BREAK, SCHEMA_VERSION, StyleAsset
from spolvero.validation.composition import (
    coverage_mask,
    density_profile,
    ink_centroid,
    principal_axis_deg,
    region_count,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "projects", "lonely_boat")

# M3 灰度 golden（eastern_minimal 为灰度风格，着色必须恒等，不得改动它）
GOLDEN_GRAYSCALE_PNG = "0526128ef48236c65a21e8c5da26e715b50ff7554a505b8832ef0d647219a7fd"


def _sq(ink=0.5, color=None) -> InkShape:
    return InkShape(
        ring=(Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)), ink=ink, color=color
    )


# ───────────────────────── 资产模型 ─────────────────────────
def test_builtin_presets_exist_with_schema_version():
    east = get_style("eastern_minimal")
    verm = get_style("vermilion")
    assert east is not None and verm is not None
    assert east.schema_version == SCHEMA_VERSION == 1
    assert east.grayscale is False and verm.grayscale is False
    assert len(east.tone.accents) == 3 and len(verm.tone.accents) == 1
    assert get_style("nope") is None


def test_list_styles_covers_builtins():
    ids = {a.id for a in list_styles(os.path.join(ROOT, "styles"))}
    assert {"eastern_minimal", "vermilion"} <= ids


def test_asset_dict_round_trip():
    a = get_style("vermilion")
    back = StyleAsset.from_dicts(a.style_dict(), a.constraints_dict())
    assert back.style_dict() == a.style_dict()
    assert back.constraints == a.constraints


def test_asset_round_trip_through_disk():
    a = get_style("vermilion")
    d = os.path.join(tempfile.mkdtemp(), "styles")
    save_style(a, d)
    for fn in ("style.yaml", "constraints.yaml", "preview.png"):
        assert os.path.exists(os.path.join(d, a.id, fn)), fn
    back = load_style_dir(os.path.join(d, a.id))
    assert back.style_dict() == a.style_dict()
    assert back.constraints == a.constraints


def test_save_rejects_schema_mismatch():
    a = get_style("eastern_minimal").tweaked(schema_version=99)
    with pytest.raises(StyleIOError):
        save_style(a, tempfile.mkdtemp())


# ───────────────────────── 灰度 → RGB 三档映射 ─────────────────────────
def test_ink_to_rgb_hits_three_stops():
    a = get_style("vermilion")
    assert ink_to_rgb(1.0, a) == parse_hex(a.tone.paper)
    assert ink_to_rgb(BASE_BREAK, a) == parse_hex(a.tone.base)
    assert ink_to_rgb(0.0, a) == parse_hex(a.tone.ink)


def test_ink_to_rgb_is_monotone_darkening():
    a = get_style("vermilion")
    lum = [sum(ink_to_rgb(i / 20.0, a)) for i in range(21)]
    assert lum == sorted(lum), "ink 越大应越浅（纸）"


def test_grayscale_style_is_identity():
    a = get_style("eastern_minimal").tweaked(grayscale=True)
    node = Group((_sq(0.3), InkDot(pos=Point(1, 1), r=2, ink=0.2)), Transform.identity())
    assert recolor(node, a) is node, "灰度风格不得改动场景图"


def test_colored_style_maps_and_preserves_explicit_color():
    a = get_style("vermilion")
    plain = _sq(0.1)
    explicit = _sq(0.1, color="#00ff00")
    assert getattr(recolor(plain, a), "color") is not None
    assert getattr(recolor(explicit, a), "color") == "#00ff00"


def test_accent_rule_is_deterministic_and_narrow():
    a = get_style("vermilion")
    lamp = InkDot(pos=Point(0, 0), r=2.0, ink=0.2)
    assert is_accent_leaf(lamp)
    assert getattr(recolor(lamp, a), "color") == a.tone.accents[0]
    big = InkDot(pos=Point(0, 0), r=24.0, ink=0.16)  # 月亮不是点染
    assert not is_accent_leaf(big)
    dark = InkDot(pos=Point(0, 0), r=2.0, ink=0.8)
    assert not is_accent_leaf(dark)


# ───────────────────────── 渲染接入 ─────────────────────────
def test_grayscale_preset_does_not_change_existing_golden():
    import sys
    if sys.platform != "win32":
        pytest.skip("skia PNG 编码跨平台非 byte-identical；golden 仅承诺同机 L1")
    proj = load_project(PROJECT)
    png = render_project(proj, "skia", style=get_style("eastern_minimal"))
    assert hashlib.sha256(png).hexdigest() == GOLDEN_GRAYSCALE_PNG


def test_api_render_matches_direct_render_for_grayscale():
    from spolvero.render.backend import render
    from spolvero.styles.apply import recolor_all

    proj = load_project(PROJECT)
    st = get_style("eastern_minimal")
    assert render_project(proj, "skia", style=st) == render(
        recolor_all(proj.groups, st), "skia", proj.width, proj.height, proj.background
    )


def test_colored_preset_renders_deterministically_and_differs():
    proj = load_project(PROJECT)
    st = get_style("vermilion")
    a = render_project(proj, "skia", style=st)
    b = render_project(proj, "skia", style=st)
    assert a == b
    assert a != render_project(proj, "skia", style=get_style("eastern_minimal"))
    # 底色应换成朱砂预设的纸色
    from spolvero.render.skia import png_to_rgb

    rgb = png_to_rgb(a)
    assert tuple(rgb[0:3]) == parse_hex(st.tone.paper)


def test_style_switching_does_not_touch_geometry():
    proj = load_project(PROJECT)
    gray = get_style("eastern_minimal").tweaked(grayscale=True)
    assert render_project(proj, "svg", style=gray) == render_project(proj, "svg", style=None)


# ───────────────────────── 约束接入校验器 ─────────────────────────
def test_project_passes_its_own_style_constraints():
    proj = load_project(PROJECT)
    rep = check_project(proj)
    assert rep.passed, rep.render_text()
    assert rep.warnings() == []


def test_grayscale_style_forbids_chromatic_elements():
    """灰度风格（color_area_max=0）下，孤舟灯染朱红必须报 COMP_COLOR_AREA。"""
    proj = load_project(PROJECT)
    from dataclasses import replace as _replace

    from spolvero.core.scene import flatten_all
    from spolvero.styles.apply import recolor_all
    from spolvero.validation.composition import validate_composition

    gray = get_style("eastern_minimal").tweaked(grayscale=True).with_constraints(
        {"severity": "warning", "as_error": [], "whitespace_min": 0.8,
         "color_area_max": 0.0, "density_max": 0.02, "overlap_max": 0.55,
         "region_count_min": 2, "region_count_max": 60})
    colored = recolor_all(proj.groups, get_style("vermilion"))
    leaves = flatten_all(colored)
    issues = validate_composition(leaves, proj.width, proj.height, gray.constraints)
    assert "COMP_COLOR_AREA" in {i.code for i in issues}
    # 而朱砂预设的 color_area_max 更宽，应放行
    assert validate_composition(leaves, proj.width, proj.height,
                               get_style("vermilion").constraints) == []


# ───────────────────────── 扩展 2 构图指纹 ─────────────────────────
def test_extended_fingerprint_is_deterministic():
    proj = load_project(PROJECT)
    from spolvero.core.scene import flatten_all

    lv = flatten_all(proj.groups)
    assert region_count(lv, proj.width, proj.height) == region_count(lv, proj.width, proj.height)
    assert ink_centroid(lv, proj.width, proj.height) == ink_centroid(lv, proj.width, proj.height)
    assert principal_axis_deg(lv, proj.width, proj.height) == principal_axis_deg(
        lv, proj.width, proj.height
    )
    assert len(density_profile(lv, proj.width, proj.height)) == 48
    assert 0.35 < ink_centroid(lv, proj.width, proj.height)[0] < 0.55


def test_coverage_mask_handles_out_of_canvas_points():
    far = _sq(0.5, None)
    far = InkShape(ring=(Point(-500, -500), Point(-400, -500), Point(-400, -400)), ink=0.5)
    assert coverage_mask([far], 100, 100)  # 不崩


# ───────────────────────── 预览 ─────────────────────────
def test_preview_svg_is_a_string_and_deterministic():
    a = get_style("vermilion")
    s1 = render_preview(a)
    s2 = render_preview(a)
    assert isinstance(s1, str) and s1.startswith("<svg")
    assert s1 == s2
    assert render_preview(a, {"accent": "#123456"}) != s1


def test_preview_knobs_are_non_destructive():
    a = get_style("vermilion")
    render_preview(a, {"paper": "#000000", "grayscale": True})
    assert a.tone.paper == "#F6F1E7" and a.grayscale is False


# ───────────────────────── Lottie L0 导出 ─────────────────────────
def test_export_lottie_writes_valid_document():
    proj = load_project(PROJECT)
    out = os.path.join(tempfile.mkdtemp(), "f.json")
    info = export_lottie(proj, out, style=get_style("eastern_minimal"))
    doc = json.load(open(out, encoding="utf-8"))
    assert doc["v"] and doc["w"] == proj.width and doc["h"] == proj.height
    assert doc["fr"] == proj.fps and doc["op"] >= 1
    assert len(doc["layers"]) == len(proj.groups) == info["layers"]
    assert all(l["ty"] == 4 and l["shapes"] for l in doc["layers"])


def test_export_lottie_is_loadable_by_python_lottie():
    lottie = pytest.importorskip("lottie")
    from lottie.parsers.tgs import parse_tgs

    proj = load_project(PROJECT)
    out = os.path.join(tempfile.mkdtemp(), "f.json")
    export_lottie(proj, out)
    anim = parse_tgs(out)
    assert anim.width == proj.width and anim.height == proj.height
    assert len(anim.layers) == len(proj.groups)


def test_export_lottie_is_deterministic():
    proj = load_project(PROJECT)
    d = tempfile.mkdtemp()
    export_lottie(proj, os.path.join(d, "a.json"))
    export_lottie(proj, os.path.join(d, "b.json"))
    assert open(os.path.join(d, "a.json"), "rb").read() == open(
        os.path.join(d, "b.json"), "rb"
    ).read()


# ───────────────────────── Lottie L1 导入 ─────────────────────────
def test_import_lottie_returns_primitives_with_constant_point_count():
    lottie = pytest.importorskip("lottie")

    proj = load_project(PROJECT)
    out = os.path.join(tempfile.mkdtemp(), "f.json")
    export_lottie(proj, out)
    nodes = import_lottie(out)
    leaves = [lf for n in nodes for lf in _flatten(n)]
    shapes = [len(lf.ring) for lf in leaves if isinstance(lf, InkShape)]
    lines = [len(lf.points) for lf in leaves if isinstance(lf, InkLine)]
    assert shapes and set(shapes) == {24}, f"ink_shape 控制点未归一化: {sorted(set(shapes))}"
    assert lines and set(lines) == {24}, f"ink_line 控制点未归一化: {sorted(set(lines))}"
    assert import_summary(nodes)["leaves"] == len(leaves)


def test_import_lottie_preserves_geometry_scale():
    lottie = pytest.importorskip("lottie")

    proj = load_project(PROJECT)
    out = os.path.join(tempfile.mkdtemp(), "f.json")
    export_lottie(proj, out)
    leaves = [lf for n in import_lottie(out) for lf in _flatten(n)]
    xs = [p.x for lf in leaves for p in _pts(lf)]
    ys = [p.y for lf in leaves for p in _pts(lf)]
    # 应在画布范围内（允许少量溢出），而非挤在原点
    assert min(xs) < 300 and max(xs) > 1200
    assert max(ys) < 900 and min(ys) > -50


def test_import_missing_file_raises_readable_error():
    from spolvero.lottie import LottieImportError

    with pytest.raises(LottieImportError):
        import_lottie(os.path.join(tempfile.mkdtemp(), "nope.json"))


def test_import_accepts_gzipped_tgs():
    lottie = pytest.importorskip("lottie")
    import gzip

    proj = load_project(PROJECT)
    d = tempfile.mkdtemp()
    raw = os.path.join(d, "f.json")
    export_lottie(proj, raw)
    gz = os.path.join(d, "f.json.gz")
    with open(raw, "rb") as fi, gzip.open(gz, "wb") as fo:
        fo.write(fi.read())
    assert import_lottie(gz)


def _flatten(node):
    if isinstance(node, Group):
        for c in node.children:
            yield from _flatten(c)
    else:
        yield node


def _pts(lf):
    if isinstance(lf, InkDot):
        return [lf.pos]
    return list(lf.ring if isinstance(lf, InkShape) else lf.points)


# ───────────────────────── 动画工程的 Lottie 烘焙 ─────────────────────────
def test_animated_project_exports_baked_keyframes():
    lottie = pytest.importorskip("lottie")

    from tests.test_m5 import _tmp_project, ANIM_TIMELINE

    proj = load_project(_tmp_project(ANIM_TIMELINE, duration="duration: 1.0\n"))
    out = os.path.join(tempfile.mkdtemp(), "a.json")
    info = export_lottie(proj, out)
    assert info["frames"] == 12
    doc = json.load(open(out, encoding="utf-8"))
    assert doc["op"] == 12
    for layer in doc["layers"]:
        for ch in ("p", "r", "s"):
            prop = layer["ks"][ch]
            if prop["a"] == 1:
                assert len(prop["k"]) == 12, f"{layer['nm']}.{ch} 未逐帧烘焙"
                assert all(k.get("h") == 1 for k in prop["k"])


# ───────────────────────── 实例级色调 tint ─────────────────────────
def test_tint_overrides_grayscale_style():
    """显式 tint 优先于风格的 grayscale：给了颜色却被静默忽略是最糟的意外。"""
    a = get_style("eastern_minimal").tweaked(grayscale=True)
    node = _sq(0.2)
    assert getattr(recolor(node, a), "color") is None
    assert getattr(recolor(node, a, "#2E7BB5"), "color") is not None


def test_tint_ramp_keeps_tonal_depth_within_one_hue():
    """tint 不是把实例压成单色：ink 仍在「纸→淡→本色→深」之间取层次。"""
    from spolvero.styles.apply import ink_to_rgb, tint_stops

    a = get_style("azurite")
    stops = tint_stops(a, "#2E7BB5")
    assert ink_to_rgb(1.0, a, "#2E7BB5") == parse_hex(a.tone.paper)
    assert ink_to_rgb(0.34, a, "#2E7BB5") == parse_hex("#2E7BB5")
    lum = [sum(ink_to_rgb(i / 20.0, a, "#2E7BB5")) for i in range(21)]
    assert lum == sorted(lum), "ink 越大应越浅"
    assert len(set(lum)) > 12, "层次不足，说明被压成了单色"


def test_tint_beats_palette_but_loses_to_explicit_color():
    a = get_style("azurite")
    node = _sq(0.2, color="#00ff00")
    assert getattr(recolor(node, a, "#2E7BB5"), "color") == "#00ff00"


def test_recolor_all_pairs_tints_with_iids():
    from spolvero.styles.apply import recolor_all

    a = get_style("azurite")
    nodes = [Group((_sq(0.3),), Transform.identity()) for _ in range(2)]
    out = recolor_all(nodes, a, {"a": "#2E7BB5", "b": "#C8442E"}, ("a", "b"))
    c0 = out[0].children[0].color
    c1 = out[1].children[0].color
    assert c0 != c1
    assert c0 is not None and c1 is not None


def test_azurite_preset_is_vivid_and_does_not_cap_color_area():
    a = get_style("azurite")
    assert a.grayscale is False
    assert len(a.tone.accents) == 3
    assert "color_area_max" not in a.constraints, "重彩风格不该用彩面积上限卡自己"


# ───────────────────────── 全局相机 ─────────────────────────
def _cam_project():
    import tempfile

    from tests.test_m5 import _components_yaml

    d = tempfile.mkdtemp()
    open(os.path.join(d, "project.yaml"), "w", encoding="utf-8").write(
        "seed: cam\nwidth: 200\nheight: 100\nduration: 2.0\nfps: 10\nstyle: azurite\n"
        'background: "#FFFFFF"\n'
        "camera:\n"
        "  - channel: scale\n    ease: linear\n"
        "    keys:\n      - {t: 0.0, v: 1.0}\n      - {t: 2.0, v: 2.0}\n"
    )
    open(os.path.join(d, "style.yaml"), "w", encoding="utf-8").write("name: azurite\n")
    open(os.path.join(d, "components.yaml"), "w", encoding="utf-8").write(_components_yaml())
    open(os.path.join(d, "timeline.yaml"), "w", encoding="utf-8").write(
        "items:\n  - component: boat\n    iid: b1\n    transform: {translate: [100, 50]}\n"
    )
    return load_project(d)


def test_project_camera_parses_and_wraps_scene():
    from spolvero.animation.film import scene_at

    proj = _cam_project()
    assert proj.camera is not None and len(proj.camera.tracks) == 1
    assert proj.is_animated
    wrapped = scene_at(proj, 1.0)
    assert len(wrapped) == 1, "相机应把整场包成一个合成层"
    assert len(wrapped[0].children) == len(proj.groups)


def test_camera_scale_is_about_canvas_center():
    from spolvero.animation.film import scene_at

    proj = _cam_project()
    # t=0 时相机为恒等（scale=1），scene_at 不会外包合成层，故取中间时刻比较
    at1 = scene_at(proj, 1.0)[0]
    at2 = scene_at(proj, 2.0)[0]
    cx, cy = proj.width / 2.0, proj.height / 2.0
    for t, m in ((1.0, at1.transform), (2.0, at2.transform)):
        px, py = m(cx, cy)
        assert abs(px - cx) < 1e-6 and abs(py - cy) < 1e-6, f"t={t} 相机缩放中心未钉在画布中心"
    assert at2.transform.a > at1.transform.a, "scale 通道应体现为倍率递增"


def test_camera_requires_duration():
    from spolvero.dsl.parser import DSLValidationError

    import tempfile

    from tests.test_m5 import _components_yaml

    d = tempfile.mkdtemp()
    open(os.path.join(d, "project.yaml"), "w", encoding="utf-8").write(
        'seed: cam\nwidth: 200\nheight: 100\nfps: 10\nstyle: azurite\nbackground: "#FFFFFF"\n'
        "camera:\n  - channel: scale\n    keys:\n      - {t: 0.0, v: 1.0}\n"
    )
    open(os.path.join(d, "style.yaml"), "w", encoding="utf-8").write("name: azurite\n")
    open(os.path.join(d, "components.yaml"), "w", encoding="utf-8").write(_components_yaml())
    open(os.path.join(d, "timeline.yaml"), "w", encoding="utf-8").write("items: []\n")
    with pytest.raises(DSLValidationError) as ei:
        load_project(d)
    assert "duration" in str(ei.value)


def test_tint_field_parsed_from_timeline():
    proj = load_project(os.path.join(ROOT, "projects", "lonely_boat_story"))
    assert proj.tints["boat_main"] == "#C8442E"
    assert proj.tints["m1"] == "#2E7BB5"
    assert len(proj.tints) == len(proj.groups)
