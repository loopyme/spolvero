"""M4 三重校验器测试。

覆盖：
  几何拓扑 —— 自相交 / 顶点不足 / 重复点（含「合法图元不得误报」的反向断言）
  艺术相似度 —— 近重复剪影命中、空间门限豁免远处重复、尺度自适应（相对距离）不误伤大小悬殊者
  构图四约束 —— 留白 / 彩面积 / 密度 / 堆积，阈值可配 + as_error 升级
  编排与报告 —— validate_scene / validate_project、passed 语义、结构化序列化
"""

from __future__ import annotations

import os

from shapely.geometry import Polygon

from spolvero.core.primitives import Group, InkDot, InkLine, InkShape
from spolvero.core.types import Point
from spolvero.dsl.parser import load_project
from spolvero.validation.composition import (
    color_area_ratio,
    coverage_ratio,
    density,
    max_overlap,
    validate_composition,
)
from spolvero.validation.diagnostics import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Issue,
    ValidationReport,
)
from spolvero.validation.geometry import check_leaf_geometry
from spolvero.validation.similarity import find_similar
from spolvero.validation.validator import validate_scene

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "projects", "lonely_boat")

W, H = 1600, 900


def _shape(pts, **kw) -> InkShape:
    return InkShape(ring=tuple(Point(x, y) for x, y in pts), **kw)


def _line(pts, **kw) -> InkLine:
    return InkLine(points=tuple(Point(x, y) for x, y in pts), **kw)


SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


# ───────────────────────── 几何拓扑 ─────────────────────────
def test_valid_square_is_clean():
    assert check_leaf_geometry(_shape(SQUARE, ink=0.5), "sq") == []


def test_bowtie_self_intersection_is_error():
    bow = _shape([(0, 0), (10, 10), (10, 0), (0, 10)], ink=0.5)
    codes = {i.code for i in check_leaf_geometry(bow, "bow")}
    assert "GEOM_SELF_INTERSECT" in codes
    assert all(i.severity == SEVERITY_ERROR for i in check_leaf_geometry(bow, "bow"))


def test_shape_too_few_points_is_error():
    issues = check_leaf_geometry(_shape([(0, 0), (1, 1)], ink=0.5), "s")
    assert [i.code for i in issues] == ["GEOM_TOO_FEW_POINTS"]
    assert issues[0].severity == SEVERITY_ERROR


def test_collinear_ring_is_error():
    flat = _shape([(0, 0), (5, 0), (10, 0)], ink=0.5)
    issues = check_leaf_geometry(flat, "flat")
    assert issues and all(i.severity == SEVERITY_ERROR for i in issues)
    assert issues[0].code in {"GEOM_SELF_INTERSECT", "GEOM_ZERO_AREA"}


def test_zero_area_valid_ring_is_error():
    """合法但面积≈0 的轮廓（控制点蜷缩在一处）也应被拦下。"""
    tiny = _shape([(0, 0), (1e-4, 0), (1e-4, 1e-4), (0, 1e-4)], ink=0.5)
    assert [i.code for i in check_leaf_geometry(tiny, "tiny")] == ["GEOM_ZERO_AREA"]


def test_duplicate_points_warning_only():
    dup = _shape([(0, 0), (10, 0), (10, 0), (10, 10), (0, 10)], ink=0.5)
    issues = check_leaf_geometry(dup, "dup")
    assert [i.code for i in issues] == ["GEOM_DUP_POINTS"]
    assert issues[0].severity == SEVERITY_WARNING


def test_dot_is_exempt():
    assert check_leaf_geometry(InkDot(pos=Point(1, 2)), "d") == []


def test_mountain_fix_produces_simple_polygons():
    """回归：山体抖动曾使顶点下潜到闭合边另一侧 → shapely 判自相交（M4 捕获并修复）。"""
    from spolvero.components import lonely_boat_library
    from spolvero.core.component import Instance

    lib = lonely_boat_library()
    for i in range(60):
        g = lib.instantiate(Instance("mountain", f"m_{i:03d}"), "spolvero-m4-regress")
        ring = [p.xy() for p in g.children[0].ring]
        assert Polygon(ring).is_valid, f"m_{i:03d} 山体自相交"
        assert len(ring) == 9


# ───────────────────────── 艺术相似度 ─────────────────────────
def test_near_duplicate_closed_shapes_flagged():
    a = _shape(SQUARE, ink=0.5)
    b = _shape([(0.2, 0.1), (10.1, 0.2), (9.9, 10.2), (0.1, 9.9)], ink=0.5)
    issues = find_similar([a, b], label="t")
    assert [i.code for i in issues] == ["ART_NEAR_DUPLICATE"]
    assert issues[0].severity == SEVERITY_WARNING


def test_distant_duplicate_exempt_by_spatial_gate():
    a = _shape(SQUARE, ink=0.5)
    b = _shape([(500 + x, 500 + y) for x, y in SQUARE], ink=0.5)
    assert find_similar([a, b], label="t") == []


def test_open_strokes_exempt_by_default():
    """有意重复母题（水纹一类开放笔画）默认不比较，避免同组正弦线互相误报。"""
    sin_a = _line([(x, (x % 7) - 3) for x in range(0, 40, 2)], ink=0.3)
    sin_b = _line([(x, (x % 7) - 3.05) for x in range(0, 40, 2)], ink=0.3)
    assert find_similar([sin_a, sin_b], label="t") == []
    assert find_similar([sin_a, sin_b], label="t", include_lines=True) != []


def test_scale_adaptive_relative_distance_avoids_false_positive():
    """大小悬殊、形状不同的两个剪影不得因「绝对距离天然小」被判近重复。"""
    big = _shape(
        [(x * 30, (y * 30) - (40 if k == 2 else 0)) for k, (x, y) in enumerate(SQUARE)],
        ink=0.5,
    )
    small = _shape(SQUARE, ink=0.5)
    assert find_similar([big, small], label="t") == []


def test_unrelated_shapes_not_flagged():
    tri = _shape([(0, 0), (20, 0), (10, 20)], ink=0.5)
    wide = _shape([(0, 0), (60, 0), (60, 6), (0, 6)], ink=0.5)
    assert find_similar([tri, wide], label="t") == []


# ───────────────────────── 构图四约束 ─────────────────────────
def test_coverage_and_whitespace():
    full = _shape([(0, 0), (W, 0), (W, H), (0, H)], ink=0.5)
    assert coverage_ratio([full], W, H) > 0.99
    issues = validate_composition(
        [full], W, H, {"severity": SEVERITY_WARNING, "whitespace_min": 0.55}
    )
    assert [i.code for i in issues] == ["COMP_LOW_WHITESPACE"]


def test_whitespace_pass_is_silent():
    tiny = _shape(SQUARE, ink=0.5)
    assert validate_composition([tiny], W, H, {"whitespace_min": 0.55}) == []


def test_color_area_constraint_and_grayscale_style():
    plain = _shape(SQUARE, ink=0.5)
    colored = _shape(SQUARE, ink=0.5, color="#9a3b30")
    assert color_area_ratio([plain, colored]) == 0.5
    issues = validate_composition(
        [plain, colored], W, H, {"severity": SEVERITY_WARNING, "color_area_max": 0.0}
    )
    assert [i.code for i in issues] == ["COMP_COLOR_AREA"]
    # 灰度风格下不得出现任何着色叶节点
    assert validate_composition([plain, plain], W, H, {"color_area_max": 0.0}) == []


def test_density_and_overlap():
    long_line = _line([(0, 0), (W * 4, 0)], ink=0.3)
    assert density([long_line], W, H) > 0.0
    issues = validate_composition(
        [long_line], W, H, {"severity": SEVERITY_WARNING, "density_max": 1e-6}
    )
    assert [i.code for i in issues] == ["COMP_DENSITY"]

    a = _shape(SQUARE, ink=0.5)
    b = _shape([(x + 1, y + 1) for x, y in SQUARE], ink=0.5)
    assert max_overlap([a, b]) > 0.5
    issues = validate_composition(
        [a, b], W, H, {"severity": SEVERITY_WARNING, "overlap_max": 0.5}
    )
    assert [i.code for i in issues] == ["COMP_CLUSTER"]


def test_as_error_escalates_severity():
    full = _shape([(0, 0), (W, 0), (W, H), (0, H)], ink=0.5)
    warn = validate_composition([full], W, H, {"whitespace_min": 0.55})
    assert warn[0].severity == SEVERITY_WARNING
    err = validate_composition(
        [full], W, H, {"whitespace_min": 0.55, "as_error": ["COMP_LOW_WHITESPACE"]}
    )
    assert err[0].severity == SEVERITY_ERROR


def test_no_constraints_means_silent():
    full = _shape([(0, 0), (W, 0), (W, H), (0, H)], ink=0.5)
    assert validate_composition([full], W, H, None) == []


# ───────────────────────── 编排与报告 ─────────────────────────
def test_lonely_boat_project_passes_validation():
    proj = load_project(PROJECT)
    report = validate_scene(proj.groups, proj.width, proj.height, label="project")
    assert report.passed, report.render_text()
    assert report.errors() == []


def test_report_semantics_and_serialization():
    rep = ValidationReport()
    assert rep.passed and "校验通过" in rep.render_text()

    rep.add(Issue(SEVERITY_WARNING, "W1", "warn", "loc", "sug"))
    assert rep.passed, "warning 不得阻断"
    rep.add(Issue(SEVERITY_ERROR, "E1", "err", "loc", "sug"))
    assert not rep.passed
    assert len(rep.warnings()) == 1 and len(rep.errors()) == 1

    round_trip = ValidationReport.from_dicts([i.to_dict() for i in rep.issues])
    assert round_trip.issues == rep.issues
    assert "E1" in rep.render_text()


def test_validate_scene_accepts_single_group_node():
    proj = load_project(PROJECT)
    node = Group(tuple(proj.groups))
    rep = validate_scene(node, W, H)
    assert rep.passed
