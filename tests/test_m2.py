"""M2 构件系统测试：原型/实例/稀疏 override/值域校验/L1-L2 差异化/确定性。

断言 SPEC §3 三条命门在构件层成立，并卡住「孤舟渡江」示例片的 golden 哈希。
"""

from __future__ import annotations

import hashlib

import pytest
from shapely.geometry import Polygon

from spolvero.components import lonely_boat_library
from spolvero.components.lonely_boat import BOAT_PARAMS, _build_boat
from spolvero.core.component import (
    ComponentPrototype,
    Instance,
    ParamSpec,
)
from spolvero.core.primitives import Group, InkShape
from spolvero.render.backend import render
from spolvero.scenes import LONELY_BOAT_SEED, lonely_boat_scene

SEED = "spolvero-m2-test"

# golden 帧哈希（L1 同机同版本 byte-identical，CI 卡死）
GOLDEN_LONELY_PNG = "a4fda813dc9f9a4bd0fff9916c606521a4e1c0c5eb86be09f69ff6c70ac90771"
GOLDEN_LONELY_SVG = "773b962a6b994820a2805bca1b4622b08b2c16003fc522dfeffffa895c01fb7d"


def _hull_of(group: Group) -> InkShape:
    return next(c for c in group.children if isinstance(c, InkShape))


# ───────────────────────── 值域校验 ─────────────────────────
def test_validation_rejects_out_of_range():
    boat = lonely_boat_library().get("boat")
    with pytest.raises(ValueError):
        boat.instantiate(SEED, "b", {"length": 9999})
    with pytest.raises(ValueError):
        boat.instantiate(SEED, "b", {"length": -5})
    with pytest.raises(ValueError):
        boat.instantiate(SEED, "b", {"hull_ink": 1.5})


def test_validation_rejects_wrong_type():
    boat = lonely_boat_library().get("boat")
    with pytest.raises(ValueError):
        boat.instantiate(SEED, "b", {"has_canopy": 1.5})  # bool 参数传 float


def test_validate_reports_messages():
    boat = lonely_boat_library().get("boat")
    errs = boat.validate({"length": 9999})  # 只给一个越界参数
    assert any("length" in e for e in errs)
    assert any("缺失" in e for e in errs)  # 其余参数缺失


# ─────────────────── 命门 2 · 稀疏 override ───────────────────
def test_sparse_override_isolation():
    boat = lonely_boat_library().get("boat")
    base = boat.derive_params(SEED, "b1")
    over = boat.derive_params(SEED, "b1", {"length": 100.0})
    assert over["length"] == 100.0
    diff = [k for k in base if base[k] != over[k]]
    assert diff == ["length"], f"override 泄漏到其他参数: {diff}"


def test_prototype_edit_propagates_and_override_wins():
    """改原型定义 → 所有无 override 的实例同步；实例 override 仍优先。"""
    lib = lonely_boat_library()
    inst = Instance("boat", "b1")
    assert isinstance(lib.get("boat").derive_params(SEED, "b1")["has_canopy"], bool)

    # 原型层改动：篷开关概率恒真
    forced = [
        ParamSpec("has_canopy", True, p_true=1.0, kind="bool") if p.name == "has_canopy" else p
        for p in BOAT_PARAMS
    ]
    lib.register(ComponentPrototype("boat", forced, _build_boat))
    assert lib.get("boat").derive_params(SEED, "b1")["has_canopy"] is True

    # 实例 override 仍优先（稀疏差分不被原型覆盖）
    inst2 = inst.with_override(has_canopy=False)
    assert lib.instantiate(inst2, SEED) is not None
    assert lib.get("boat").derive_params(SEED, "b1", inst2.overrides)["has_canopy"] is False


def test_with_override_does_not_mutate_original():
    inst = Instance("boat", "b1", {"length": 50.0})
    inst2 = inst.with_override(hull_ink=0.9)
    assert inst.overrides == {"length": 50.0}
    assert inst2.overrides == {"length": 50.0, "hull_ink": 0.9}


def test_override_isolation_between_instances():
    lib = lonely_boat_library()
    a = Instance("boat", "boat_a", {"length": 40.0})
    b = Instance("boat", "boat_b")
    lib.instantiate(a, SEED)
    pb = lib.get("boat").derive_params(SEED, "boat_b", b.overrides)
    assert pb["length"] != 40.0, "实例 A 的 override 影响了实例 B"


# ─────────────── 命门 1/3 · 差异化与点数恒定 ───────────────
def test_l1_l2_differentiation():
    lib = lonely_boat_library()
    ids = [f"boat_{i:03d}" for i in range(50)]
    params = [lib.get("boat").derive_params(SEED, i) for i in ids]

    distinct_len = len({round(p["length"], 1) for p in params})
    assert distinct_len >= 30, f"L1 尺寸差异化不足: {distinct_len}"

    n_canopy = sum(1 for p in params if p["has_canopy"])
    assert 5 < n_canopy < 45, f"L2 拓扑开关分布异常: 篷 {n_canopy}/50"

    topo_combos = {(p["has_canopy"], p["has_mast"], p["has_lamp"]) for p in params}
    assert len(topo_combos) >= 4, f"L2 拓扑组合过少: {topo_combos}"

    # 逐点抖动（不增点数）→ 首控制点 x 各不相同的比例高
    hull_x = {round(_hull_of(lib.instantiate(Instance("boat", i), SEED)).ring[0].x, 3)
              for i in ids}
    assert len(hull_x) >= 40, f"船体抖动差异化不足: {len(hull_x)}"


def test_control_point_count_constant():
    lib = lonely_boat_library()
    for i in range(30):
        g = lib.instantiate(Instance("boat", f"boat_{i:03d}"), SEED)
        assert len(_hull_of(g).ring) == 8  # 船体恒定 8 点（命门 3）
    for i in range(30):
        w = lib.instantiate(Instance("water", f"w_{i:03d}"), SEED)
        for child in w.children:  # 每条水纹恒定 16 点
            assert len(child.points) == 16
    for i in range(20):
        m = lib.instantiate(Instance("mountain", f"m_{i:03d}"), SEED)
        ring = m.children[0].ring  # 山脊 7 + 基线 2
        assert len(ring) == 9


def test_hull_geometry_valid():
    """船体轮廓无自相交（shapely is_valid），50 实例全过。"""
    lib = lonely_boat_library()
    for i in range(50):
        g = lib.instantiate(Instance("boat", f"boat_{i:03d}"), SEED)
        ring = [p.xy() for p in _hull_of(g).ring]
        assert Polygon(ring).is_valid, f"boat_{i:03d} 船体自相交"


# ───────────────────── 确定性 + golden ─────────────────────
def test_scene_deterministic():
    lib = lonely_boat_library()

    def build():
        return lib.build_scene(lonely_boat_scene(), LONELY_BOAT_SEED)

    assert render(build(), "svg") == render(build(), "svg")
    assert render(build(), "skia") == render(build(), "skia")


def test_golden_lonely_boat():
    lib = lonely_boat_library()
    scene = lib.build_scene(lonely_boat_scene(), LONELY_BOAT_SEED)
    svg = render(scene, "svg", width=1600, height=900)
    png = render(scene, "skia", width=1600, height=900)
    assert hashlib.sha256(svg.encode()).hexdigest() == GOLDEN_LONELY_SVG
    assert hashlib.sha256(png).hexdigest() == GOLDEN_LONELY_PNG
