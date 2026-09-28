"""M3 DSL 解析器测试。

覆盖：DSL 渲染与 M2 demo 字节一致、确定性、非法 DSL 错误定位、裸原语模式、
components.yaml 与引擎 SPECS 不漂移。
"""

from __future__ import annotations

import hashlib
import os
import tempfile

import pytest

from spolvero.components import LONELY_BOAT_COMPONENT_SPECS, lonely_boat_library
from spolvero.dsl.parser import DSLValidationError, load_project
from spolvero.render.backend import render
from spolvero.scenes import LONELY_BOAT_SEED, lonely_boat_scene

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "projects", "lonely_boat")

# DSL 工程 golden 哈希（L1 byte-identical 门禁，与 M2 demo 同源）
GOLDEN_PNG = "a4fda813dc9f9a4bd0fff9916c606521a4e1c0c5eb86be09f69ff6c70ac90771"
GOLDEN_SVG = "773b962a6b994820a2805bca1b4622b08b2c16003fc522dfeffffa895c01fb7d"


def _render(project, backend):
    return render(
        project.groups, backend=backend,
        width=project.width, height=project.height, bg=project.background,
    )


def test_dsl_matches_m2_demo():
    proj = load_project(PROJECT)
    dsl_png = _render(proj, "skia")
    dsl_svg = _render(proj, "svg")

    lib = lonely_boat_library()
    ref = lib.build_scene(lonely_boat_scene(), LONELY_BOAT_SEED)
    ref_png = render(ref, backend="skia", width=1600, height=900)
    ref_svg = render(ref, backend="svg", width=1600, height=900)

    assert dsl_png == ref_png, "DSL 渲染须与 M2 Python 场景逐字节一致"
    assert dsl_svg == ref_svg
    assert hashlib.sha256(dsl_png).hexdigest() == GOLDEN_PNG
    assert hashlib.sha256(dsl_svg.encode()).hexdigest() == GOLDEN_SVG


def test_dsl_deterministic():
    a = load_project(PROJECT)
    b = load_project(PROJECT)
    assert _render(a, "skia") == _render(b, "skia")
    assert _render(a, "svg") == _render(b, "svg")


def _tmp_project(timeline_yaml: str, components_yaml: str | None = None) -> str:
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "project.yaml"), "w", encoding="utf-8") as f:
        f.write('seed: x\nwidth: 100\nheight: 100\nbackground: "#FFFFFF"\n')
    with open(os.path.join(d, "style.yaml"), "w", encoding="utf-8") as f:
        f.write("name: s\n")
    if components_yaml is None:
        components_yaml = (
            "- name: boat\n  pattern: boat\n  params:\n"
            "    - {name: length, default: 64.0, lo: 30.0, hi: 150.0, kind: float}\n"
        )
    with open(os.path.join(d, "components.yaml"), "w", encoding="utf-8") as f:
        f.write(components_yaml)
    with open(os.path.join(d, "timeline.yaml"), "w", encoding="utf-8") as f:
        f.write(timeline_yaml)
    return d


def test_unknown_component():
    d = _tmp_project(
        "items:\n  - component: ghost\n    iid: g\n    transform: {translate: [0,0]}\n"
    )
    with pytest.raises(DSLValidationError) as ei:
        load_project(d)
    assert "ghost" in str(ei.value)


def test_param_out_of_range():
    d = _tmp_project(
        "items:\n  - component: boat\n    iid: b\n    overrides: {length: 9999}\n"
        "    transform: {translate: [0,0]}\n"
    )
    with pytest.raises(DSLValidationError) as ei:
        load_project(d)
    assert "越界" in str(ei.value)


def test_bad_color_value():
    d = _tmp_project(
        "items:\n  - primitive: dot\n    iid: d\n    pos: [1,2]\n    color: \"#ZZZ\"\n"
    )
    with pytest.raises(DSLValidationError) as ei:
        load_project(d)
    assert "color" in str(ei.value)


def test_unknown_primitive():
    d = _tmp_project("items:\n  - primitive: blob\n    iid: d\n")
    with pytest.raises(DSLValidationError) as ei:
        load_project(d)
    assert "blob" in str(ei.value)


def test_bare_primitive_renders():
    d = _tmp_project(
        "items:\n  - primitive: line\n    iid: l\n    points: [[0,0],[10,10]]\n"
        "    transform: {translate: [5,5]}\n"
    )
    proj = load_project(d)
    assert len(proj.groups) == 1


def test_components_yaml_matches_specs():
    """声明式组件定义须与引擎 SPECS 完全一致（防止两源漂移）。"""
    import yaml

    with open(os.path.join(PROJECT, "components.yaml"), encoding="utf-8") as f:
        yaml_specs = yaml.safe_load(f)

    def norm(specs):
        out = {}
        for s in specs:
            out[s["name"]] = {"pattern": s["pattern"], "params": {}}
            for p in s["params"]:
                kind = p.get("kind")
                # p_true 仅对 bool 有意义；bool 的 lo/hi 默认值两侧不一致，统一忽略
                if kind == "bool":
                    lo = hi = None
                    pt = p.get("p_true")
                else:
                    lo = p.get("lo")
                    hi = p.get("hi")
                    pt = None
                out[s["name"]]["params"][p["name"]] = (lo, hi, kind, pt)
        return out

    a = norm(yaml_specs)
    b = norm(LONELY_BOAT_COMPONENT_SPECS)
    assert a == b, "components.yaml 与 LONELY_BOAT_COMPONENT_SPECS 不一致"
